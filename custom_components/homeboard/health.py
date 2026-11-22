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
    CONF_HEALTH_BATTERY,
    CONF_HEALTH_BATTERY_THRESHOLD,
    CONF_HEALTH_ENABLED,
    CONF_HEALTH_EXCLUDE_ENTITIES,
    CONF_HEALTH_EXCLUDE_INTEGRATIONS,
    CONF_HEALTH_INTEGRATIONS,
    CONF_HEALTH_MAX_OPEN,
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
    HEALTH_IGNORE_LABEL,
    HEALTH_IGNORED_PLATFORMS,
    HEALTH_PROJECT_KEY,
    HEALTH_PROJECT_NAME,
    HEALTH_REOPEN_COOLDOWN_MINUTES,
    HEALTH_STARTUP_GRACE_MINUTES,
    PRIORITIES,
)
from .data import UNSET, HomeboardData
from .learning import fmt_minutes
from .model import NotFoundError

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=5)
KEY_PREFIX = "health:"
BATTERY_HYSTERESIS = 5
MIN_DEVICES_FOR_GROUPING = 3
LISTED_ENTITIES = 10

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

    def __init__(self, hass: HomeAssistant, options: Any, active_keys: set[str]) -> None:
        self.hass = hass
        self.options = options
        self.active_keys = active_keys
        self.entities = er.async_get(hass)
        self.devices = dr.async_get(hass)
        self.areas = ar.async_get(hass)
        self.excluded_entities = set(options.get(CONF_HEALTH_EXCLUDE_ENTITIES) or [])
        self.excluded_integrations = {
            str(item).strip().lower()
            for item in options.get(CONF_HEALTH_EXCLUDE_INTEGRATIONS) or []
            if str(item).strip()
        }

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


def _friendly(state: Any, entry: er.RegistryEntry) -> str:
    return (
        (state.name if state is not None else None)
        or entry.name
        or entry.original_name
        or entry.entity_id
    )


def _listing(lines: list[str]) -> str:
    shown = lines[:LISTED_ENTITIES]
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

    for device in ctx.devices.devices.values():
        if device.disabled_by:
            continue
        pairs: list[tuple[er.RegistryEntry, Any]] = []
        for entry in er.async_entries_for_device(ctx.entities, device.id):
            if entry.entity_category is not None or ctx.entry_excluded(entry):
                continue
            pairs.append((entry, ctx.hass.states.get(entry.entity_id)))
        if not pairs or any(state is None for _, state in pairs):
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
        security = ctx.is_security(pairs)
        lines = [f"{_friendly(state, entry)} (`{entry.entity_id}`)" for entry, state in pairs]
        where = ctx.entry_title(device.primary_config_entry)
        area = ctx.area_name(device)
        facts = [f"Offline since {_local(since)}"]
        if where:
            facts.append(f"Integration: {where}")
        if area:
            facts.append(f"Area: {area}")
        finding = Finding(
            key=f"{KEY_PREFIX}offline:{device.id}",
            detector="offline",
            summary=f"{name} is offline",
            description=" | ".join(facts) + "\n\n" + _listing(lines) + FOOTER,
            priority="high" if security else "medium",
            labels=["auto", "offline"] + (["security"] if security else []),
            fingerprint=tuple(sorted(entry.entity_id for entry, _ in pairs)),
        )
        findings.append(finding)
        entry_id = device.primary_config_entry
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
            )
        )
    return [f for f in findings if f.key not in merged] + grouped


def collect_battery(ctx: _Context, threshold: int) -> list[Finding]:
    """Batteries below the threshold, grouped per device."""
    by_device: dict[str | None, list[tuple[er.RegistryEntry, Any, str]]] = defaultdict(list)
    for state in ctx.hass.states.async_all(("sensor", "binary_sensor")):
        if state.attributes.get("device_class") != "battery" or state.attributes.get("restored"):
            continue
        entry = ctx.entities.async_get(state.entity_id)
        if entry is None or ctx.entry_excluded(entry):
            continue
        device_key = f"{KEY_PREFIX}battery:{entry.device_id or entry.entity_id}"
        limit = threshold + (BATTERY_HYSTERESIS if device_key in ctx.active_keys else 0)
        if state.domain == "binary_sensor":
            if state.state != STATE_ON:
                continue
            label = "low"
        else:
            try:
                level = float(state.state)
            except ValueError:
                continue
            if level >= limit:
                continue
            label = f"{level:g} %"
        by_device[entry.device_id or entry.entity_id].append((entry, state, label))

    findings = []
    for ident, items in by_device.items():
        device = ctx.devices.async_get(ident)
        name = ctx.device_name(device) if device else _friendly(items[0][1], items[0][0])
        security = ctx.is_security(_device_pairs(ctx, device) or [(items[0][0], items[0][1])])
        lines = [f"{_friendly(state, entry)}: {label}" for entry, state, label in items]
        findings.append(
            Finding(
                key=f"{KEY_PREFIX}battery:{ident}",
                detector="battery",
                summary=f"Replace battery: {name}",
                description=_listing(lines) + FOOTER,
                priority="high" if security else "medium",
                labels=["auto", "battery"] + (["security"] if security else []),
                type="task",
                fingerprint=tuple(sorted(e.entity_id for e, _, _ in items)),
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
                key=f"{KEY_PREFIX}silent:{ident}",
                detector="silent",
                summary=f"{name} stopped reporting",
                description=_listing(lines) + FOOTER,
                priority="high" if security else "medium",
                labels=["auto", "silent"] + (["security"] if security else []),
                fingerprint=tuple(sorted(e.entity_id for e, _ in items)),
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
        ctx = _Context(self.hass, options, active)
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

        findings = await self.async_collect()
        keys = {f.key for f in findings}
        project = self._project(create=not dry_run)

        def add(finding: Finding, action: str) -> None:
            result["findings"].append(finding.brief(action))

        if not dry_run:
            for key in keys:
                self._seen[key] = self._seen.get(key, 0) + 1
                self._absent.pop(key, None)
            for key in [k for k in self._seen if k not in keys]:
                del self._seen[key]

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
                    self.manager.update_issue(
                        existing["id"], source="health", description=finding.description
                    )
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
        return result

    # The fingerprint (which entities are affected) is kept in memory only: after a
    # restart the first scan simply refreshes a changed description once.
    def _fingerprint(self, issue: dict[str, Any]) -> tuple[str, ...] | None:
        return self._fingerprints.get(issue["id"])

    def _remember_fingerprint(self, issue: dict[str, Any], finding: Finding, dry_run: bool) -> None:
        if not dry_run:
            self._fingerprints[issue["id"]] = finding.fingerprint
