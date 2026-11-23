"""Home health: Homeboard creates, updates and closes issues for smart-home faults.

The detectors only *read* Home Assistant (states and registries) and return
``Finding`` objects. ``HealthMonitor`` reconciles them against the issues on
the board through ``HomeboardData`` (the single mutation point) and carries the
rules that keep the board from flooding. See docs/PROTOCOL.md section 3b.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import (
    area_registry as ar,
)
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers import (
    issue_registry as ir,
)
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.translation import async_get_translations
from homeassistant.util import dt as dt_util

from .const import (
    CONF_HEALTH_ASSIGNEE,
    CONF_HEALTH_AUTOMATIONS,
    CONF_HEALTH_BATTERY,
    CONF_HEALTH_BATTERY_THRESHOLD,
    CONF_HEALTH_ENABLED,
    CONF_HEALTH_EXCLUDE_ENTITIES,
    CONF_HEALTH_EXCLUDE_INTEGRATIONS,
    CONF_HEALTH_INTEGRATIONS,
    CONF_HEALTH_MAX_OPEN,
    CONF_HEALTH_NOISY_DEVICES,
    CONF_HEALTH_PROJECT,
    CONF_HEALTH_REPAIRS,
    CONF_HEALTH_SNOOZE_DAYS,
    CONF_HEALTH_UNAVAILABLE,
    CONF_HEALTH_UNAVAILABLE_MINUTES,
    CONF_HEALTH_UPDATES,
    DEFAULT_HEALTH_BATTERY_THRESHOLD,
    DEFAULT_HEALTH_MAX_OPEN,
    DEFAULT_HEALTH_SNOOZE_DAYS,
    DEFAULT_HEALTH_UNAVAILABLE_MINUTES,
    DOMAIN,
    HEALTH_DEBOUNCE_SCANS,
    HEALTH_EPHEMERAL_PLATFORMS,
    HEALTH_IGNORE_LABEL,
    HEALTH_IGNORED_PLATFORMS,
    HEALTH_PROJECT_KEY,
    HEALTH_PROJECT_NAME,
    HEALTH_REOPEN_COOLDOWN_MINUTES,
    HEALTH_REVIEW_KEY,
    HEALTH_STARTUP_GRACE_MINUTES,
    PRIORITIES,
    PROTECTED_DOMAINS,
)
from .data import UNSET, HomeboardData
from .learning import SILENT_FLOOR_MINUTES, fmt_minutes
from .model import NotFoundError

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=5)
KEY_PREFIX = "health:"
PATIENCE_DETECTORS = frozenset({"offline", "silent"})
MAX_WAITING_LISTED = 30
BATTERY_HYSTERESIS = 5
BATTERY_GROUP_KEY = f"{KEY_PREFIX}battery_group"
MIN_DEVICES_FOR_GROUPING = 3
LISTED_ENTITIES = 10
LISTED_IN_REVIEW = 40

# Things that are off most of the time on purpose (televisions, speakers, bulbs on a wall
# switch) or that charge themselves (robot mowers, vacuums, phones) are not "faults".
NORMALLY_OFF_DOMAINS = frozenset({"media_player", "remote"})
SELF_CHARGING_DOMAINS = frozenset({"lawn_mower", "vacuum"})

SECURITY_CLASSES = frozenset(
    {
        "door",
        "window",
        "opening",
        "garage_door",
        "motion",
        "occupancy",
        "presence",
        "smoke",
        "gas",
        "carbon_monoxide",
        "moisture",
        "tamper",
        "safety",
        "lock",
    }
)
SECURITY_DOMAINS = frozenset({"camera", "alarm_control_panel", "lock", "siren"})
DEVICE_LESS_DOMAINS = frozenset(
    {
        "sensor",
        "binary_sensor",
        "switch",
        "light",
        "climate",
        "cover",
        "lock",
        "camera",
        "media_player",
        "vacuum",
        "fan",
        "water_heater",
        "alarm_control_panel",
        "siren",
        "humidifier",
        "valve",
        "lawn_mower",
    }
)


@dataclass
class Finding:
    """One thing that needs fixing."""

    key: str
    detector: str
    summary: str
    description: str = ""
    priority: str = "medium"
    labels: list[str] = field(default_factory=list)
    type: str = "bug"
    fingerprint: tuple[str, ...] = ()
    """Identifies *what* is affected, so the description is only rewritten when that changes."""
    refresh_summary: bool = False
    """Grouped findings carry a count in the title, which follows the group."""
    since: datetime | None = None
    """When the fault started, so the monitor can tell how long it lasted when it fixes itself."""

    def brief(self, action: str) -> dict[str, Any]:
        """Return the short form used in scan results."""
        return {
            "key": self.key,
            "summary": self.summary,
            "priority": self.priority,
            "detector": self.detector,
            "action": action,
        }


# --------------------------------------------------------------------------- helpers


def _bool_option(options: Any, name: str, default: bool) -> bool:
    return bool(options.get(name, default))


class _Context:
    """Registries and option lookups shared by the detectors."""

    def __init__(
        self,
        hass: HomeAssistant,
        options: Any,
        active_keys: set[str],
        learning: Any = None,
    ) -> None:
        self.hass = hass
        self.options = options
        self.active_keys = active_keys
        self.learning = learning
        self.waiting: list[dict[str, Any]] = []
        """Faults held back because the device has fixed itself before (see ``patience``)."""
        self.entities = er.async_get(hass)
        self.devices = dr.async_get(hass)
        self.areas = ar.async_get(hass)
        self.excluded_entities = set(options.get(CONF_HEALTH_EXCLUDE_ENTITIES) or [])
        self.excluded_integrations = {
            str(item).strip().lower()
            for item in options.get(CONF_HEALTH_EXCLUDE_INTEGRATIONS) or []
            if str(item).strip()
        }
        self.noisy = bool(options.get(CONF_HEALTH_NOISY_DEVICES, False))
        """Also report devices that are normally off or charge themselves."""
        self.battery_members: set[str] = set()
        """Entities already in the open battery group (they get the hysteresis)."""

    def patience(self, key: str) -> timedelta:
        """Return how long the fault ``key`` must last before it is reported (0 = the normal wait)."""
        if self.learning is None:
            return timedelta(0)
        return timedelta(minutes=self.learning.patience(key))

    def hold(
        self, finding_key: str, summary: str, detector: str, waited: timedelta, wait: timedelta
    ) -> None:
        """Note a fault that is not reported yet because the device is known to come back."""
        self.waiting.append(
            {
                "key": finding_key,
                "summary": summary,
                "detector": detector,
                "waited_minutes": round(waited.total_seconds() / 60),
                "reported_after_minutes": round(wait.total_seconds() / 60),
            }
        )

    def entry_excluded(self, entry: er.RegistryEntry) -> bool:
        """Return True if the entity is switched off, hidden, excluded or a helper."""
        return bool(
            entry.disabled_by
            or entry.hidden_by
            or entry.entity_id in self.excluded_entities
            or entry.platform in HEALTH_IGNORED_PLATFORMS
            or entry.platform.lower() in self.excluded_integrations
        )

    def device_name(self, device: dr.DeviceEntry) -> str:
        return device.name_by_user or device.name or device.id

    def area_name(self, device: dr.DeviceEntry) -> str | None:
        if device.area_id and (area := self.areas.async_get_area(device.area_id)):
            return area.name
        return None

    def entry_title(self, entry_id: str | None) -> str | None:
        if entry_id and (entry := self.hass.config_entries.async_get_entry(entry_id)):
            return entry.title
        return None

    def entity_class(self, entry: er.RegistryEntry, state: Any) -> str | None:
        if state is not None and state.attributes.get("device_class"):
            return str(state.attributes["device_class"])
        return entry.device_class or entry.original_device_class

    def is_normally_off(self, entries: Iterable[tuple[er.RegistryEntry, Any]]) -> bool:
        """Return True for devices that are offline as a matter of course."""
        if self.noisy:
            return False
        entries = list(entries)
        domains = {entry.domain for entry, _ in entries}
        return bool(
            domains & NORMALLY_OFF_DOMAINS
            or any(entry.platform in HEALTH_EPHEMERAL_PLATFORMS for entry, _ in entries)
            or (domains and domains <= {"light"})
        )

    def is_self_charging(self, entries: Iterable[tuple[er.RegistryEntry, Any]]) -> bool:
        """Return True for devices whose battery is recharged, not replaced."""
        if self.noisy:
            return False
        for entry, state in entries:
            if (
                entry.domain in SELF_CHARGING_DOMAINS
                or entry.platform in HEALTH_EPHEMERAL_PLATFORMS
            ):
                return True
            if (
                entry.domain == "binary_sensor"
                and self.entity_class(entry, state) == "battery_charging"
            ):
                return True
        return False

    def is_security(self, entries: Iterable[tuple[er.RegistryEntry, Any]]) -> bool:
        for entry, state in entries:
            if entry.domain in SECURITY_DOMAINS:
                return True
            if (
                entry.domain == "binary_sensor"
                and self.entity_class(entry, state) in SECURITY_CLASSES
            ):
                return True
        return False


def _all_devices(registry: dr.DeviceRegistry) -> list[dr.DeviceEntry]:
    """Return every device. Newer Home Assistant iterates entries, older versions keys."""
    devices = [item for item in registry.devices if isinstance(item, dr.DeviceEntry)]
    return devices or list(registry.devices.values())


def _config_entry_id(device: dr.DeviceEntry) -> str | None:
    """Return the config entry of a device (renamed in newer Home Assistant versions)."""
    return getattr(device, "config_entry_id", None) or device.primary_config_entry


def _friendly(state: Any, entry: er.RegistryEntry) -> str:
    return (
        (state.name if state is not None else None)
        or entry.name
        or entry.original_name
        or entry.entity_id
    )


def _listing(lines: list[str], limit: int = LISTED_ENTITIES) -> str:
    shown = lines[:limit]
    extra = len(lines) - len(shown)
    text = "\n".join(f"- {line}" for line in shown)
    return text + (f"\n- ... and {extra} more" if extra > 0 else "")


FOOTER = "\n\n_Created automatically by Homeboard. It closes itself when the problem is gone. Close it to snooze it, add the label `ignore` to stop it for good._"


def _local(value: datetime) -> str:
    return dt_util.as_local(value).strftime("%Y-%m-%d %H:%M")


# --------------------------------------------------------------------------- detectors


def collect_offline(ctx: _Context, now: datetime, minutes: int) -> list[Finding]:
    """Devices whose primary entities are all unavailable for a while."""
    findings: list[Finding] = []
    threshold = timedelta(minutes=minutes)
    by_entry: dict[str, list[Finding]] = defaultdict(list)
    entry_of: dict[str, str] = {}

    for device in _all_devices(ctx.devices):
        if device.disabled_by:
            continue
        pairs: list[tuple[er.RegistryEntry, Any]] = []
        for entry in er.async_entries_for_device(ctx.entities, device.id):
            if entry.entity_category is not None or ctx.entry_excluded(entry):
                continue
            pairs.append((entry, ctx.hass.states.get(entry.entity_id)))
        if not pairs or any(state is None for _, state in pairs):
            continue
        if ctx.is_normally_off(pairs):
            continue
        if any(
            state.state != STATE_UNAVAILABLE or state.attributes.get("restored")
            for _, state in pairs
        ):
            continue
        since = max(state.last_changed for _, state in pairs)
        if now - since < threshold:
            continue
        name = ctx.device_name(device)
        key = f"{KEY_PREFIX}offline:{device.id}"
        wait = max(threshold, ctx.patience(key))
        if now - since < wait:  # it has been gone this long before and came back by itself
            ctx.hold(key, f"{name} is offline", "offline", now - since, wait)
            continue
        security = ctx.is_security(pairs)
        lines = [f"{_friendly(state, entry)} (`{entry.entity_id}`)" for entry, state in pairs]
        where = ctx.entry_title(_config_entry_id(device))
        area = ctx.area_name(device)
        facts = [f"Offline since {_local(since)}"]
        if where:
            facts.append(f"Integration: {where}")
        if area:
            facts.append(f"Area: {area}")
        finding = Finding(
            key=key,
            detector="offline",
            summary=f"{name} is offline",
            description=" | ".join(facts) + "\n\n" + _listing(lines) + FOOTER,
            priority="high" if security else "medium",
            labels=["auto", "offline"] + (["security"] if security else []),
            fingerprint=tuple(sorted(entry.entity_id for entry, _ in pairs)),
            since=since,
        )
        findings.append(finding)
        entry_id = _config_entry_id(device)
        if entry_id:
            by_entry[entry_id].append(finding)
            entry_of[finding.key] = name

    # A whole integration being down is one problem, not a dozen.
    grouped: list[Finding] = []
    merged: set[str] = set()
    for entry_id, items in by_entry.items():
        if len(items) < MIN_DEVICES_FOR_GROUPING:
            continue
        title = ctx.entry_title(entry_id) or entry_id
        merged.update(item.key for item in items)
        security = any(item.priority == "high" for item in items)
        grouped.append(
            Finding(
                key=f"{KEY_PREFIX}offline_entry:{entry_id}",
                detector="offline",
                summary=f"{title}: {len(items)} devices are offline",
                description="\n".join(f"- {entry_of[i.key]}" for i in items[:LISTED_ENTITIES])
                + FOOTER,
                priority="high" if security else "medium",
                labels=["auto", "offline"] + (["security"] if security else []),
                fingerprint=tuple(sorted(i.key for i in items)),
                refresh_summary=True,
            )
        )
    return [f for f in findings if f.key not in merged] + grouped


def collect_battery(ctx: _Context, threshold: int) -> list[Finding]:
    """Batteries below the threshold.

    Security devices (smoke, doors, motion, ...) get an issue of their own. Every other
    battery goes into ONE grouped issue, so a house full of sensors does not flood the board.
    """
    by_device: dict[str, list[tuple[er.RegistryEntry, Any, str, float]]] = defaultdict(list)
    for state in ctx.hass.states.async_all(("sensor", "binary_sensor")):
        if state.attributes.get("device_class") != "battery" or state.attributes.get("restored"):
            continue
        entry = ctx.entities.async_get(state.entity_id)
        if entry is None or ctx.entry_excluded(entry):
            continue
        ident = entry.device_id or entry.entity_id
        held = f"{KEY_PREFIX}battery:{ident}" in ctx.active_keys or (
            entry.entity_id in ctx.battery_members
        )
        limit = threshold + (BATTERY_HYSTERESIS if held else 0)
        if state.domain == "binary_sensor":
            if state.state != STATE_ON:
                continue
            label, level = "low", 0.0
        else:
            try:
                level = float(state.state)
            except ValueError:
                continue
            if level >= limit:
                continue
            label = f"{level:g} %"
        by_device[ident].append((entry, state, label, level))

    findings: list[Finding] = []
    grouped: list[tuple[str, str | None, list[tuple[er.RegistryEntry, Any, str, float]]]] = []
    for ident, items in by_device.items():
        device = ctx.devices.async_get(ident)
        name = ctx.device_name(device) if device else _friendly(items[0][1], items[0][0])
        pairs = _device_pairs(ctx, device) or [(items[0][0], items[0][1])]
        if ctx.is_self_charging(pairs):
            continue
        if not ctx.is_security(pairs):
            grouped.append((name, ctx.area_name(device) if device else None, items))
            continue
        lines = [f"{_friendly(state, entry)}: {label}" for entry, state, label, _ in items]
        findings.append(
            Finding(
                key=f"{KEY_PREFIX}battery:{ident}",
                detector="battery",
                summary=f"Replace battery: {name}",
                description=_listing(lines) + FOOTER,
                priority="high",
                labels=["auto", "battery", "security"],
                type="task",
                fingerprint=tuple(sorted(e.entity_id for e, _, _, _ in items)),
            )
        )
    if grouped:
        grouped.sort(key=lambda g: (min(level for *_, level in g[2]), g[0].lower()))
        lines = []
        for name, area, items in grouped:
            labels = ", ".join(label for _, _, label, _ in items)
            lines.append(f"{name}{f' ({area})' if area else ''}: {labels}")
        count = len(grouped)
        findings.append(
            Finding(
                key=BATTERY_GROUP_KEY,
                detector="battery",
                summary=(
                    f"Replace battery: {grouped[0][0]}"
                    if count == 1
                    else f"{count} batteries are running low"
                ),
                description=_listing(lines, LISTED_IN_REVIEW) + FOOTER,
                priority="medium",
                labels=["auto", "battery"],
                type="task",
                fingerprint=tuple(
                    sorted(e.entity_id for _, _, items in grouped for e, *_ in items)
                ),
                refresh_summary=True,
            )
        )
    return findings


def _device_pairs(
    ctx: _Context, device: dr.DeviceEntry | None
) -> list[tuple[er.RegistryEntry, Any]]:
    if device is None:
        return []
    return [
        (entry, ctx.hass.states.get(entry.entity_id))
        for entry in er.async_entries_for_device(ctx.entities, device.id)
    ]


def collect_integrations(ctx: _Context) -> list[Finding]:
    """Config entries that fail to load, and integrations waiting for a new sign-in."""
    hass = ctx.hass
    findings: dict[str, Finding] = {}
    reauth_entries: set[str] = set()
    for flow in hass.config_entries.flow.async_progress():
        context = flow.get("context") or {}
        entry_id = context.get("entry_id")
        if context.get("source") == "reauth" and entry_id:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is None or entry.domain.lower() in ctx.excluded_integrations:
                continue
            reauth_entries.add(entry_id)
            findings[entry_id] = Finding(
                key=f"{KEY_PREFIX}reauth:{entry_id}",
                detector="reauth",
                summary=f"Sign in again: {entry.title}",
                description=(
                    f"The {entry.domain} integration needs new credentials. "
                    "Open Settings > Devices & services and finish the re-authentication." + FOOTER
                ),
                priority="high",
                labels=["auto", "integration"],
                fingerprint=(entry_id,),
            )
    bad = {
        ConfigEntryState.SETUP_ERROR: "failed to set up",
        ConfigEntryState.SETUP_RETRY: "cannot connect and keeps retrying",
        ConfigEntryState.MIGRATION_ERROR: "failed to migrate its data",
        ConfigEntryState.FAILED_UNLOAD: "failed to unload",
    }
    for entry in hass.config_entries.async_entries():
        if (
            entry.disabled_by
            or entry.domain == DOMAIN
            or entry.domain.lower() in ctx.excluded_integrations
            or entry.entry_id in reauth_entries
            or entry.state not in bad
        ):
            continue
        reason = f"\n\nReason: {entry.reason}" if entry.reason else ""
        findings[entry.entry_id] = Finding(
            key=f"{KEY_PREFIX}entry:{entry.entry_id}",
            detector="integration",
            summary=f"Integration problem: {entry.title}",
            description=f"The {entry.domain} integration {bad[entry.state]}.{reason}{FOOTER}",
            priority="medium",
            labels=["auto", "integration"],
            fingerprint=(entry.entry_id, entry.state.value),
        )
    return list(findings.values())


def collect_silent(ctx: _Context, learning: Any) -> list[Finding]:
    """Sensors that normally report regularly but have gone quiet (learned rhythm)."""
    by_device: dict[str, list[tuple[er.RegistryEntry, dict[str, Any]]]] = defaultdict(list)
    now = dt_util.utcnow()
    for candidate in learning.silent_candidates():
        entry = ctx.entities.async_get(candidate["entity_id"])
        if entry is None or ctx.entry_excluded(entry):
            continue
        by_device[entry.device_id or entry.entity_id].append((entry, candidate))
    findings = []
    for ident, items in by_device.items():
        device = ctx.devices.async_get(ident)
        first_entry, _ = items[0]
        name = (
            ctx.device_name(device)
            if device
            else _friendly(ctx.hass.states.get(first_entry.entity_id), first_entry)
        )
        key = f"{KEY_PREFIX}silent:{ident}"
        patience = ctx.patience(key)
        quiet = max(c["silent_minutes"] for _, c in items)
        if patience and timedelta(minutes=quiet) < patience:  # quiet this long before, came back
            ctx.hold(key, f"{name} stopped reporting", "silent", timedelta(minutes=quiet), patience)
            continue
        lines = [
            f"{_friendly(ctx.hass.states.get(e.entity_id), e)}: normally every ~{c['normal_minutes']} min, "
            f"silent for {fmt_minutes(c['silent_minutes'])}"
            for e, c in items
        ]
        security = ctx.is_security(
            _device_pairs(ctx, device)
            or [(first_entry, ctx.hass.states.get(first_entry.entity_id))]
        )
        findings.append(
            Finding(
                key=key,
                detector="silent",
                summary=f"{name} stopped reporting",
                description=_listing(lines) + FOOTER,
                priority="high" if security else "medium",
                labels=["auto", "silent"] + (["security"] if security else []),
                fingerprint=tuple(sorted(e.entity_id for e, _ in items)),
                since=now - timedelta(minutes=quiet),
            )
        )
    return findings


async def collect_repairs(ctx: _Context) -> list[Finding]:
    """Open Home Assistant repair issues."""
    hass = ctx.hass
    registry = ir.async_get(hass)
    open_issues = [
        issue
        for issue in registry.issues.values()
        if issue.active
        and issue.dismissed_version is None
        and issue.domain != DOMAIN
        and issue.domain.lower() not in ctx.excluded_integrations
    ]
    if not open_issues:
        return []
    texts = await async_get_translations(
        hass, hass.config.language, "issues", {issue.domain for issue in open_issues}
    )
    findings = []
    for issue in open_issues:
        title = None
        if issue.translation_key:
            template = texts.get(f"component.{issue.domain}.issues.{issue.translation_key}.title")
            if template:
                try:
                    title = template.format(**(issue.translation_placeholders or {}))
                except (KeyError, IndexError, ValueError):
                    title = template
        title = title or f"{issue.domain}: {issue.translation_key or issue.issue_id}"
        severe = issue.severity in (ir.IssueSeverity.CRITICAL, ir.IssueSeverity.ERROR)
        more = f"\n\nMore information: {issue.learn_more_url}" if issue.learn_more_url else ""
        findings.append(
            Finding(
                key=f"{KEY_PREFIX}repair:{issue.domain}:{issue.issue_id}",
                detector="repair",
                summary=f"Repair: {title}",
                description=(
                    f"Home Assistant reports a repair for {issue.domain}. "
                    f"Open Settings > System > Repairs.{more}{FOOTER}"
                ),
                priority="high" if severe else "medium",
                labels=["auto", "repair"],
                fingerprint=(issue.domain, issue.issue_id),
            )
        )
    return findings


def collect_automations(ctx: _Context) -> list[Finding]:
    """Enabled automations that use entities which no longer exist (opt-in).

    Home Assistant raises a repair when an automation fails validation or calls a missing service, but it
    does not notice an automation that silently points at a deleted or renamed entity. Automations that are
    switched off, and entities that are excluded in the options, are left alone.
    """
    try:
        from homeassistant.components.automation import entities_in_automation
    except ImportError:  # pragma: no cover - a Home Assistant without the automation integration
        return []
    hass = ctx.hass
    findings = []
    for state in hass.states.async_all("automation"):
        if state.state != STATE_ON:
            continue
        refs = sorted(set(entities_in_automation(hass, state.entity_id)))
        missing = [
            ref for ref in refs if hass.states.get(ref) is None and ref not in ctx.excluded_entities
        ]
        if not missing:
            continue
        lines = []
        for ref in missing:
            entry = ctx.entities.async_get(ref)
            lines.append(
                f"`{ref}` ({'disabled' if entry and entry.disabled_by else 'does not exist'})"
            )
        name = state.attributes.get("friendly_name") or state.entity_id
        protected = any(ref.split(".", 1)[0] in PROTECTED_DOMAINS for ref in refs)
        findings.append(
            Finding(
                key=f"{KEY_PREFIX}automation:{state.entity_id}",
                detector="automation",
                summary=f'Automation "{name}" uses {len(missing)} missing '
                + ("entity" if len(missing) == 1 else "entities"),
                description=(
                    f"The automation `{state.entity_id}` refers to entities that Home Assistant "
                    f"does not have right now, so parts of it cannot work:\n\n"
                    + _listing(lines)
                    + "\n\nUse *Analyse with AI* on this issue for a proposed fix, or edit the "
                    "automation yourself." + FOOTER
                ),
                priority="high" if protected else "medium",
                labels=["auto", "automation"] + (["security"] if protected else []),
                fingerprint=tuple(missing),
            )
        )
    return findings


def collect_updates(ctx: _Context) -> list[Finding]:
    """One grouped issue listing every pending update (opt-in)."""
    lines = []
    for state in ctx.hass.states.async_all("update"):
        if state.state != STATE_ON or state.attributes.get("in_progress"):
            continue
        entry = ctx.entities.async_get(state.entity_id)
        if entry is not None and ctx.entry_excluded(entry):
            continue
        installed = state.attributes.get("installed_version")
        latest = state.attributes.get("latest_version")
        lines.append(f"{_friendly(state, entry) if entry else state.name}: {installed} -> {latest}")
    if not lines:
        return []
    lines.sort()
    return [
        Finding(
            key=f"{KEY_PREFIX}updates",
            detector="updates",
            summary=f"{len(lines)} update{'s' if len(lines) != 1 else ''} available",
            description=_listing(lines) + FOOTER,
            priority="low",
            labels=["auto", "update"],
            type="task",
            fingerprint=tuple(lines),
        )
    ]


# --------------------------------------------------------------------------- monitor


class HealthMonitor:
    """Runs the detectors every few minutes and keeps the board in step."""

    def __init__(self, hass: HomeAssistant, manager: HomeboardData) -> None:
        """Initialise the monitor (call ``async_start``)."""
        self.hass = hass
        self.manager = manager
        self.grace_until: datetime | None = None
        self._seen: dict[str, int] = {}
        self._absent: dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._unsub_interval: CALLBACK_TYPE | None = None
        self._unsub_started: CALLBACK_TYPE | None = None
        self._fingerprints: dict[str, tuple[str, ...]] = {}
        self._review_fingerprint: tuple[str, ...] = ()
        self._since: dict[str, datetime] = {}
        """When each reported fault started (memory only: used to learn how long it took to heal)."""
        self.waiting: list[dict[str, Any]] = []
        """Faults the last collection held back because the device is known to come back."""
        self.last_result: dict[str, Any] | None = None

    # -- lifecycle

    @callback
    def async_start(self) -> None:
        """Start scanning once Home Assistant has finished starting."""

        @callback
        def started(_hass: HomeAssistant) -> None:
            self.grace_until = dt_util.utcnow() + timedelta(minutes=HEALTH_STARTUP_GRACE_MINUTES)
            self._unsub_interval = async_track_time_interval(
                self.hass, self._async_interval, SCAN_INTERVAL
            )

        self._unsub_started = async_at_started(self.hass, started)

    @callback
    def async_stop(self) -> None:
        """Stop scanning."""
        for unsub in (self._unsub_interval, self._unsub_started):
            if unsub:
                unsub()
        self._unsub_interval = self._unsub_started = None

    async def _async_interval(self, _now: datetime) -> None:
        await self.async_scan()

    # -- options

    def _opt(self, name: str, default: Any) -> Any:
        return self.manager.options.get(name, default)

    @property
    def enabled(self) -> bool:
        """Return True if automatic issue creation is switched on."""
        return bool(self._opt(CONF_HEALTH_ENABLED, True))

    # -- collecting

    async def async_collect(self) -> list[Finding]:
        """Run every enabled detector."""
        options = self.manager.options
        active = {
            issue["dedupe_key"]
            for issue in self.manager.issues.values()
            if issue.get("dedupe_key", "")
            and issue["dedupe_key"].startswith(KEY_PREFIX)
            and not issue["archived"]
            and self.manager.category(issue) != "done"
        }
        ctx = _Context(self.hass, options, active, self.manager.learning)
        for issue in self.manager.issues.values():
            if issue.get("dedupe_key") == BATTERY_GROUP_KEY and issue["id"] in self._fingerprints:
                ctx.battery_members.update(self._fingerprints[issue["id"]])
        now = dt_util.utcnow()
        findings: list[Finding] = []
        if _bool_option(options, CONF_HEALTH_UNAVAILABLE, True):
            findings += collect_offline(
                ctx,
                now,
                int(self._opt(CONF_HEALTH_UNAVAILABLE_MINUTES, DEFAULT_HEALTH_UNAVAILABLE_MINUTES)),
            )
        if _bool_option(options, CONF_HEALTH_BATTERY, True):
            findings += collect_battery(
                ctx, int(self._opt(CONF_HEALTH_BATTERY_THRESHOLD, DEFAULT_HEALTH_BATTERY_THRESHOLD))
            )
        if _bool_option(options, CONF_HEALTH_INTEGRATIONS, True):
            findings += collect_integrations(ctx)
        if _bool_option(options, CONF_HEALTH_REPAIRS, True):
            findings += await collect_repairs(ctx)
        if _bool_option(options, CONF_HEALTH_AUTOMATIONS, False):
            findings += collect_automations(ctx)
        if _bool_option(options, CONF_HEALTH_UPDATES, False):
            findings += collect_updates(ctx)
        learning = self.manager.learning
        if learning is not None and learning.enabled("health"):
            findings += collect_silent(ctx, learning)
        # Device offline findings are redundant when the integration itself is broken.
        broken = {
            f.key.split(":", 2)[2] for f in findings if f.detector in ("integration", "reauth")
        }
        findings = [
            f
            for f in findings
            if not (
                f.key.startswith(f"{KEY_PREFIX}offline_entry:") and f.key.split(":", 2)[2] in broken
            )
        ]
        self.waiting = ctx.waiting
        unique = {f.key: f for f in findings}
        order = {name: n for n, name in enumerate(reversed(PRIORITIES))}
        return sorted(unique.values(), key=lambda f: (-order.get(f.priority, 0), f.key))

    # -- reconciling

    def _project(self, *, create: bool) -> dict[str, Any] | None:
        key = str(self._opt(CONF_HEALTH_PROJECT, "") or HEALTH_PROJECT_KEY).upper()
        try:
            return self.manager.resolve_project(key)
        except NotFoundError:
            pass
        if not create or key != HEALTH_PROJECT_KEY:
            if create:
                _LOGGER.warning("Home health project %s does not exist, scan skipped", key)
            return None
        return self.manager.create_project(
            key=HEALTH_PROJECT_KEY,
            name=HEALTH_PROJECT_NAME,
            description="Created automatically by Homeboard for faults found in the smart home.",
            icon="mdi:wrench",
            color="#d9534f",
        )

    async def async_scan(self, *, dry_run: bool = False, force: bool = False) -> dict[str, Any]:
        """Collect findings and update the board.

        ``dry_run`` only reports. ``force`` (a manual scan) skips the startup
        grace and the two-scan debounce.
        """
        async with self._lock:
            result = await self._scan(dry_run=dry_run, force=force or dry_run)
            if not dry_run:
                self.last_result = result
            return result

    async def _scan(self, *, dry_run: bool, force: bool) -> dict[str, Any]:
        result: dict[str, Any] = {
            "created": 0,
            "reopened": 0,
            "closed": 0,
            "suppressed": 0,
            "findings": [],
            "waiting": [],
        }
        if (
            not dry_run
            and not force
            and (
                not self.enabled or self.grace_until is None or dt_util.utcnow() < self.grace_until
            )
        ):
            result["skipped"] = "disabled" if not self.enabled else "startup_grace"
            return result

        if not dry_run:
            self._seed_patience()
        findings = await self.async_collect()
        keys = {f.key for f in findings}
        result["waiting"] = self.waiting[:MAX_WAITING_LISTED]

        def add(finding: Finding, action: str) -> None:
            result["findings"].append(finding.brief(action))

        if not dry_run:
            for finding in findings:
                if finding.since is not None:
                    self._since.setdefault(finding.key, finding.since)
            for key in keys:
                self._seen[key] = self._seen.get(key, 0) + 1
                self._absent.pop(key, None)
            for key in [k for k in self._seen if k not in keys]:
                del self._seen[key]
            if not self.reviewed and self._hold_for_review(findings, force, result):
                return result

        project = self._project(create=not dry_run)
        if project is None:
            for finding in findings:
                add(finding, "would_create" if dry_run else "no_project")
            return result

        max_open = int(self._opt(CONF_HEALTH_MAX_OPEN, DEFAULT_HEALTH_MAX_OPEN))
        snooze = timedelta(days=int(self._opt(CONF_HEALTH_SNOOZE_DAYS, DEFAULT_HEALTH_SNOOZE_DAYS)))
        cooldown = timedelta(minutes=HEALTH_REOPEN_COOLDOWN_MINUTES)
        now = dt_util.utcnow()
        assignee = self._opt(CONF_HEALTH_ASSIGNEE, None) or None
        learning = self.manager.learning
        ignored = learning.health_ignored() if learning is not None else set()
        open_count = sum(
            1
            for issue in self.manager.project_issues(project["id"])
            if issue["source"] == "health" and self.manager.category(issue) != "done"
        )

        for finding in findings:
            existing = self.manager.find_by_dedupe(
                project, finding.key, open_only=False, include_archived=True
            )
            if finding.key in ignored:
                result["suppressed"] += 1
                add(finding, "ignored")
                continue
            if existing is not None and HEALTH_IGNORE_LABEL in existing["labels"]:
                result["suppressed"] += 1
                add(finding, "ignored")
                continue
            if existing is not None and existing["archived"]:
                existing = None
            debounced = force or self._seen.get(finding.key, 0) >= HEALTH_DEBOUNCE_SCANS

            if existing is not None and self.manager.category(existing) != "done":
                add(finding, "open")
                if (
                    not dry_run
                    and existing["description"] != finding.description
                    and (self._fingerprint(existing) != finding.fingerprint)
                ):
                    fields = {"description": finding.description}
                    if finding.refresh_summary:
                        fields["summary"] = finding.summary
                    self.manager.update_issue(existing["id"], source="health", **fields)
                self._remember_fingerprint(existing, finding, dry_run)
                continue

            if existing is not None:  # done: snoozed, cooling down, or back
                if learning is not None and not dry_run and not existing["auto_resolved"]:
                    learning.record_health(
                        "closures", finding.key, f"{existing['id']}@{existing['resolved']}"
                    )
                resolved = dt_util.parse_datetime(existing["resolved"] or "") or now
                wait = cooldown if existing["auto_resolved"] else snooze
                if now - resolved < wait and not (force and existing["auto_resolved"]):
                    result["suppressed"] += 1
                    add(finding, "snoozed")
                    continue
                if dry_run or not debounced:
                    add(finding, "would_reopen" if dry_run else "pending")
                    continue
                if open_count >= max_open:
                    result["suppressed"] += 1
                    add(finding, "capped")
                    continue
                self.manager.reopen_automatically(existing["id"], "Problem is back.")
                if learning is not None:
                    learning.record_health("reopens", finding.key)
                self._remember_fingerprint(existing, finding, dry_run)
                open_count += 1
                result["reopened"] += 1
                add(finding, "reopened")
                continue

            if dry_run:
                add(finding, "would_create")
                continue
            if not debounced:
                add(finding, "pending")
                continue
            if open_count >= max_open:
                result["suppressed"] += 1
                add(finding, "capped")
                continue
            issue, _ = self.manager.create_issue(
                project["id"],
                finding.summary,
                type=finding.type,
                priority=finding.priority,
                assignee=assignee if assignee else UNSET,
                labels=finding.labels,
                description=finding.description,
                dedupe_key=finding.key,
                source="health",
            )
            self._remember_fingerprint(issue, finding, dry_run)
            open_count += 1
            result["created"] += 1
            add(finding, "created")

        # Auto issues whose problem has not been seen for a while close themselves.
        for issue in list(self.manager.project_issues(project["id"])):
            key = issue.get("dedupe_key") or ""
            if (
                issue["source"] != "health"
                or not key.startswith(KEY_PREFIX)
                or key in keys
                or self.manager.category(issue) == "done"
            ):
                continue
            if dry_run:
                result["findings"].append(
                    {
                        "key": key,
                        "summary": issue["summary"],
                        "priority": issue["priority"],
                        "detector": key.split(":")[1],
                        "action": "would_close",
                    }
                )
                continue
            count = self._absent.get(key, 0) + 1
            self._absent[key] = count
            if force or count >= HEALTH_DEBOUNCE_SCANS:
                self._learn_patience(issue, key, now)
                self.manager.resolve_automatically(
                    issue["id"], "Resolved automatically: the problem is no longer detected."
                )
                self._absent.pop(key, None)
                result["closed"] += 1
                result["findings"].append(
                    {
                        "key": key,
                        "summary": issue["summary"],
                        "priority": issue["priority"],
                        "detector": key.split(":")[1],
                        "action": "closed",
                    }
                )
        if not dry_run:
            for key in [k for k in self._since if k not in keys and k not in self._absent]:
                del self._since[key]
        return result

    # -- patience (devices that answer once a day or come back by themselves)

    def _learn_patience(self, issue: dict[str, Any], key: str, now: datetime) -> None:
        """Remember how long a fault lasted before it fixed itself, so the next one waits longer."""
        since = self._since.pop(key, None)
        learning = self.manager.learning
        parts = key.split(":")
        if learning is None or len(parts) < 3 or parts[1] not in PATIENCE_DETECTORS:
            return
        if since is None:  # after a restart: count from the card, plus the wait before it
            created = dt_util.parse_datetime(issue.get("created") or "")
            if created is None:
                return
            since = created - self._lead(parts[1])
        learning.record_self_healed(key, (now - since).total_seconds() / 60)

    def _lead(self, detector: str) -> timedelta:
        """Return how long a fault of this kind had already lasted when its card was made."""
        if detector == "offline":
            return timedelta(
                minutes=int(
                    self._opt(CONF_HEALTH_UNAVAILABLE_MINUTES, DEFAULT_HEALTH_UNAVAILABLE_MINUTES)
                )
            )
        return timedelta(minutes=SILENT_FLOOR_MINUTES)

    def _seed_patience(self) -> None:
        """Once: learn from the faults that already closed themselves before this existed."""
        learning, state = self.manager.learning, self.manager.health_state
        if learning is None or not learning.enabled("health") or state.get("patience_seeded"):
            return
        for issue in list(self.manager.issues.values()):
            key = issue.get("dedupe_key") or ""
            parts = key.split(":")
            if (
                issue["source"] != "health"
                or len(parts) < 3
                or parts[1] not in PATIENCE_DETECTORS
                or not issue.get("auto_resolved")
                or self.manager.category(issue) != "done"
            ):
                continue
            created = dt_util.parse_datetime(issue.get("created") or "")
            resolved = dt_util.parse_datetime(issue.get("resolved") or "")
            if created is None or resolved is None:
                continue
            lasted = resolved - created + self._lead(parts[1])
            learning.record_self_healed(key, lasted.total_seconds() / 60)
        state["patience_seeded"] = True
        self.manager.save_health_state()

    # -- first-scan review

    @property
    def reviewed(self) -> bool:
        """Return True once a person has looked at the very first scan."""
        return bool(self.manager.health_state.get("reviewed"))

    @property
    def awaiting_review(self) -> bool:
        """Return True while the first scan waits for a person to look at it."""
        return not self.reviewed and bool(self.manager.health_state.get("review_issue"))

    def _mark_reviewed(self) -> None:
        state = self.manager.health_state
        state["reviewed"] = True
        state.pop("review_issue", None)
        self.manager.save_health_state()

    def _hold_for_review(
        self, findings: list[Finding], force: bool, result: dict[str, Any]
    ) -> bool:
        """Keep the first scan from flooding a board nobody has looked at yet.

        A fresh install finds whatever has been broken for months, all at once. Instead of
        creating dozens of issues, Homeboard creates ONE issue listing them. Closing that
        issue (or running ``scan_health`` by hand) lets the scanner start creating issues.
        Returns True while the scan has to wait.
        """
        manager = self.manager
        state = manager.health_state
        review = manager.issues.get(state.get("review_issue") or "")
        if force:
            if review is not None and manager.category(review) != "done":
                manager.resolve_automatically(
                    review["id"], "Reviewed: a manual scan went ahead and created the issues."
                )
            self._mark_reviewed()
            return False
        if not state.get("review_issue"):
            already = any(i["source"] == "health" for i in manager.issues.values())
            if already or not findings:  # an older install, or nothing to review
                self._mark_reviewed()
                return False
        elif review is None or review["archived"] or manager.category(review) == "done":
            self._mark_reviewed()  # a person closed or removed the review: go ahead
            return False

        for finding in findings:
            result["findings"].append(finding.brief("held"))
        result["skipped"] = "awaiting_review"
        project = self._project(create=True)
        if project is None:
            return True
        summary = f"Review: Homeboard found {len(findings)} thing{'s' if len(findings) != 1 else ''} to fix"
        description = self._review_text(findings)
        if review is None:
            issue, _ = manager.create_issue(
                project["id"],
                summary,
                type="task",
                priority="medium",
                assignee=self._opt(CONF_HEALTH_ASSIGNEE, None) or UNSET,
                labels=["auto", "review"],
                description=description,
                dedupe_key=HEALTH_REVIEW_KEY,
                source="health",
            )
            state["review_issue"] = issue["id"]
            manager.save_health_state()
            self._review_fingerprint = tuple(sorted(f.key for f in findings))
        elif review["description"] != description and self._review_fingerprint != tuple(
            sorted(f.key for f in findings)
        ):
            manager.update_issue(
                review["id"], source="health", summary=summary, description=description
            )
            self._review_fingerprint = tuple(sorted(f.key for f in findings))
        return True

    def _review_text(self, findings: list[Finding]) -> str:
        max_open = int(self._opt(CONF_HEALTH_MAX_OPEN, DEFAULT_HEALTH_MAX_OPEN))
        lines = [f"**{f.priority}** {f.summary}" for f in findings]
        return (
            "Homeboard checked your smart home for the first time and found the things below. "
            "Nothing has been created yet, so a fresh install does not flood the board.\n\n"
            + _listing(lines, LISTED_IN_REVIEW)
            + "\n\n**To go ahead**, close this issue: from then on Homeboard creates a separate "
            f"issue for each fault, most important first, at most {max_open} open at a time.\n\n"
            "**To tune first**, open the Homeboard options > Smart home health and exclude "
            "entities or integrations, change the battery threshold or the offline time. "
            "This list refreshes by itself.\n\n"
            "You can also run the `homeboard.scan_health` service, which goes ahead right away "
            "(use `dry_run: true` to only look)." + FOOTER
        )

    # The fingerprint (which entities are affected) is kept in memory only: after a
    # restart the first scan simply refreshes a changed description once.
    def _fingerprint(self, issue: dict[str, Any]) -> tuple[str, ...] | None:
        return self._fingerprints.get(issue["id"])

    def _remember_fingerprint(self, issue: dict[str, Any], finding: Finding, dry_run: bool) -> None:
        if not dry_run:
            self._fingerprints[issue["id"]] = finding.fingerprint
