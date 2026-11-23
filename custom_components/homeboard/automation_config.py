"""Read, check and (with a backup) rewrite UI automations (``automations.yaml``).

This does what Home Assistant's own automation editor does behind ``/api/config/automation/config/<id>``
(validate with the automation schema, write ``automations.yaml``, reload that automation), plus what an
unattended editor must add: a copy of the whole file before every write, a way to put one automation back,
and a check of what the automation touches.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util.file import write_utf8_file_atomic
from homeassistant.util.yaml import dump, load_yaml

from .const import BACKUP_DIR, PROTECTED_DOMAINS

_LOGGER = logging.getLogger(__name__)

AUTOMATION_FILE = "automations.yaml"
ENTITY_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
QUOTED_ENTITY_RE = re.compile(r"""["']([a-z0-9_]+\.[a-z0-9_]+)["']""")
REGISTRY_ID_RE = re.compile(r"^[0-9a-f]{32}$")
KEY_ORDER = (
    "alias",
    "description",
    "triggers",
    "trigger",
    "conditions",
    "condition",
    "actions",
    "action",
)
MAX_CONFIG_CHARS = 30_000

_LOCK = asyncio.Lock()


TAGS_REASON = "automations.yaml uses !secret or !include tags, which Homeboard would write back as plain values"


class AutomationEditError(HomeAssistantError):
    """An automation could not be read, validated or written."""


class AutomationGone(AutomationEditError):
    """The automation is not in the file (any more)."""


class AutomationChanged(AutomationEditError):
    """The automation in the file is not the one the caller looked at."""


class WriteResult(NamedTuple):
    """What ``async_write_automation`` returns."""

    backup: Path
    """The copy of the whole file made before the write."""
    fingerprint: str
    """Fingerprint of the automation as it now stands in the file."""


# ------------------------------------------------------------------ what a config touches


def _entity_candidates(value: Any) -> list[str]:
    """Split an ``entity_id`` value (string, comma list or list) into candidate ids."""
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [item for part in value for item in _entity_candidates(part)]
    return []


def entity_refs(
    config: Any, known_domains: set[str], resolve: Any = None, is_service: Any = None
) -> set[str]:
    """Return the entity ids an automation / script config refers to.

    Looks at ``entity_id`` keys (also inside ``target`` and ``data``) and at quoted ids inside templates
    (``states('sensor.x')``). Service names such as ``light.turn_on`` are NOT entities and are not returned.
    ``resolve`` turns an entity-registry id (device automations) into an entity id. ``is_service(domain, name)``
    drops quoted ``light.turn_on`` strings in templates (they are services, not entities).
    """
    found: set[str] = set()

    def add(candidate: str) -> None:
        if REGISTRY_ID_RE.match(candidate) and resolve is not None:
            resolved = resolve(candidate)
            if resolved:
                found.add(resolved)
        elif ENTITY_RE.match(candidate) and candidate.split(".", 1)[0] in known_domains:
            if is_service is not None and is_service(*candidate.split(".", 1)):
                return
            found.add(candidate)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "entity_id":
                    for candidate in _entity_candidates(value):
                        add(candidate)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, str) and ("{{" in node or "{%" in node):
            for candidate in QUOTED_ENTITY_RE.findall(node):
                add(candidate)

    walk(config)
    return found


PROTECTED_RE = re.compile(
    r"(?<![a-z0-9_])(?:" + "|".join(sorted(PROTECTED_DOMAINS)) + r")\.[a-z0-9_]+"
)
SERVICE_KEYS = ("action", "service", "service_template")
TARGET_KEYS = ("entity_id", "device_id", "area_id", "floor_id", "label_id")
# Calls that run other things (a script may well unlock a door): fine where they already were, but a
# proposal must not introduce them in an automation we cannot show to be harmless.
INDIRECT_SERVICE_DOMAINS = frozenset({"script", "scene", "homeassistant", "automation"})


def _is_template(value: str) -> bool:
    return "{{" in value or "{%" in value


def _strings(node: Any) -> Any:
    """Yield every string in a config: values and dict keys."""
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str):
                yield key
            yield from _strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from _strings(item)
    elif isinstance(node, str):
        yield node


def _walk_keys(node: Any, wanted: tuple[str, ...]) -> Any:
    """Yield ``(key, value)`` for every dict entry whose key is in ``wanted``."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in wanted:
                yield key, value
            yield from _walk_keys(value, wanted)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_keys(item, wanted)


def _indirect_entities(hass: HomeAssistant, config: Any) -> set[str]:
    """Protected entities reached through devices, areas, floors, labels or groups named in a config."""
    wanted: dict[str, set[str]] = {
        k: set() for k in ("device_id", "area_id", "floor_id", "label_id")
    }
    groups: set[str] = set()
    for key, value in _walk_keys(
        config, ("device_id", "area_id", "floor_id", "label_id", "entity_id")
    ):
        for candidate in _entity_candidates(value):
            if key == "entity_id":
                if candidate.lower().startswith("group."):
                    groups.add(candidate.lower())
            else:
                wanted[key].add(candidate)
    found: set[str] = set()
    for group in groups:
        state = hass.states.get(group)
        members = state.attributes.get("entity_id") if state else None
        for member in members if isinstance(members, (list, tuple)) else []:
            if str(member).split(".", 1)[0] in PROTECTED_DOMAINS:
                found.add(str(member))
    if not any(wanted.values()):
        return found
    devices, areas = dr.async_get(hass), ar.async_get(hass)
    for entry in er.async_get(hass).entities.values():
        if entry.domain not in PROTECTED_DOMAINS:
            continue
        device = devices.async_get(entry.device_id) if entry.device_id else None
        area_id = entry.area_id or (device.area_id if device else None)
        area = areas.async_get_area(area_id) if area_id else None
        labels = set(entry.labels) | set(device.labels if device else ())
        if (
            (entry.device_id and entry.device_id in wanted["device_id"])
            or (area_id and area_id in wanted["area_id"])
            or (area and area.floor_id and area.floor_id in wanted["floor_id"])
            or labels & wanted["label_id"]
        ):
            found.add(entry.entity_id)
    return found


def protected_hits(hass: HomeAssistant, config: Any) -> list[str]:
    """Return what in a config touches the alarm, sirens, locks, valves or Alarmo (sorted, unique).

    Conservative on purpose: every string and every dict key is searched (case-insensitively), and devices,
    areas, floors, labels and groups that contain such an entity count too.
    """
    hits: set[str] = set()
    for text in _strings(config):
        hits.update(m.group(0) for m in PROTECTED_RE.finditer(text.strip().lower()))
    for _key, value in _walk_keys(config, ("domain",)):
        if isinstance(value, str) and value.strip().lower() in PROTECTED_DOMAINS:
            hits.add(f"domain:{value.strip().lower()}")
    hits.update(_indirect_entities(hass, config))
    return sorted(hits)


def opaque_constructs(config: Any) -> set[str]:
    """Things whose effect cannot be read from the config: templated service / target, ``all``, scripts ..."""
    found: set[str] = set()
    for key, value in _walk_keys(config, SERVICE_KEYS):
        if not isinstance(value, str):
            continue
        text = value.strip().lower()
        if key == "service_template" or _is_template(text):
            found.add(f"{key}: {value.strip()}")
        elif text.split(".", 1)[0] in INDIRECT_SERVICE_DOMAINS:
            found.add(f"{key}: {text}")
    for key, value in _walk_keys(config, (*TARGET_KEYS, "target")):
        for candidate in _entity_candidates(value) if key != "target" else [value]:
            if not isinstance(candidate, str):
                continue
            text = candidate.strip()
            if _is_template(text) or (key == "entity_id" and text.lower() == "all"):
                found.add(f"{key}: {text}")
    return found


def config_hash(config: Any) -> str:
    """Return a stable fingerprint of a config (to notice that it changed after an analysis)."""

    def canon(node: Any) -> Any:
        if isinstance(node, dict):
            return {str(k): canon(v) for k, v in node.items()}
        if isinstance(node, list):
            return [canon(v) for v in node]
        return node

    text = json.dumps(canon(config), sort_keys=True, default=str)
    return hashlib.sha1(text.encode()).hexdigest()


def order_config(auto_id: str, new_config: dict[str, Any]) -> dict[str, Any]:
    """Put the keys in the order Home Assistant's editor writes them (id first)."""
    ordered: dict[str, Any] = {"id": auto_id}
    for key in KEY_ORDER:
        if key in new_config:
            ordered[key] = new_config[key]
    ordered.update(new_config)
    ordered["id"] = auto_id
    return ordered


# ------------------------------------------------------------------ the file


def _read(path: str) -> list[dict[str, Any]]:
    try:
        data = load_yaml(path)
    except FileNotFoundError:
        return []
    except HomeAssistantError as err:
        raise AutomationEditError(f"Cannot read {AUTOMATION_FILE}: {err}") from err
    if data is None:
        return []
    if not isinstance(data, list):
        raise AutomationEditError(f"{AUTOMATION_FILE} is not a list of automations")
    return data


TAG_RE = re.compile(r"(?:^|[\s\[{,:-])!(?:secret|include\w*|env_var|input)\b", re.MULTILINE)


def _has_tags(path: str) -> bool:
    """True when the file uses YAML tags (``!secret``, ``!include`` ...): writing it back would flatten them."""
    try:
        return bool(TAG_RE.search(Path(path).read_text(encoding="utf-8")))
    except OSError:
        return False


def _write(path: str, data: list[dict[str, Any]]) -> None:
    write_utf8_file_atomic(path, dump(data))


@dataclass
class AutomationInfo:
    """One automation as Homeboard sees it."""

    entity_id: str
    name: str
    state: str
    auto_id: str | None
    config: dict[str, Any] | None
    """The config from ``automations.yaml`` (``None`` when it is not a UI automation)."""
    editable: bool
    reasons: list[str] = field(default_factory=list)

    @property
    def fingerprint(self) -> str | None:
        return config_hash(self.config) if self.config is not None else None


async def async_get_automation(hass: HomeAssistant, entity_id: str) -> AutomationInfo | None:
    """Look an automation up by entity id. ``None`` if there is no such automation."""
    state = hass.states.get(entity_id)
    entry = er.async_get(hass).async_get(entity_id)
    if state is None and entry is None:
        return None
    name = (
        (state.attributes.get("friendly_name") if state else None)
        or (entry.name or entry.original_name if entry else None)
        or entity_id
    )
    auto_id = (entry.unique_id if entry else None) or (
        state.attributes.get("id") if state else None
    )
    auto_id = str(auto_id) if auto_id else None
    config: dict[str, Any] | None = None
    reasons: list[str] = []
    if auto_id is None:
        reasons.append("the automation has no id")
    else:
        try:
            items = await hass.async_add_executor_job(_read, hass.config.path(AUTOMATION_FILE))
        except AutomationEditError as err:
            items = []
            reasons.append(str(err))
        config = next((i for i in items if str(i.get("id")) == auto_id), None)
        if config is None and not reasons:
            reasons.append("it is not in automations.yaml (YAML mode or another file)")
        if config is not None and await hass.async_add_executor_job(
            _has_tags, hass.config.path(AUTOMATION_FILE)
        ):
            reasons.append(TAGS_REASON)
            return AutomationInfo(
                entity_id=entity_id,
                name=str(name),
                state=state.state if state else "unknown",
                auto_id=auto_id,
                config=config,
                editable=False,
                reasons=reasons,
            )
    if config is not None and "use_blueprint" in config:
        reasons.append("it is based on a blueprint: only the blueprint inputs can change")
    editable = config is not None
    return AutomationInfo(
        entity_id=entity_id,
        name=str(name),
        state=state.state if state else "unknown",
        auto_id=auto_id,
        config=config,
        editable=editable,
        reasons=reasons,
    )


def _backup_path(hass: HomeAssistant, auto_id: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", auto_id)[:40]
    unique = uuid.uuid4().hex[:8]  # two backups in the same second must never share a name
    return Path(hass.config.path(BACKUP_DIR)) / f"automations-{stamp}-{safe}-{unique}.yaml"


MAX_BACKUPS = 50


def _copy_file(source: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if Path(source).exists():
        shutil.copy2(source, target)
    else:
        target.write_text("[]\n", encoding="utf-8")
    old = sorted(target.parent.glob("automations-*.yaml"), key=lambda p: p.stat().st_mtime)
    for path in old[:-MAX_BACKUPS]:  # keep the newest ones, never the one just made
        if path != target:
            path.unlink(missing_ok=True)


async def async_validate(hass: HomeAssistant, auto_id: str, config: dict[str, Any]) -> None:
    """Validate with Home Assistant's own automation schema (raises ``AutomationEditError``)."""
    if len(json.dumps(config, default=str)) > MAX_CONFIG_CHARS:
        raise AutomationEditError("The automation is too large")
    try:
        from homeassistant.components.automation.config import (
            async_validate_config_item,
        )
    except (
        ImportError
    ) as err:  # pragma: no cover - a Home Assistant without the automation component
        raise AutomationEditError("This Home Assistant cannot validate automations") from err
    try:
        await async_validate_config_item(hass, auto_id, config)
    except Exception as err:
        raise AutomationEditError(str(err) or type(err).__name__) from err


async def async_write_automation(
    hass: HomeAssistant,
    auto_id: str,
    new_config: dict[str, Any],
    expected_fingerprint: str | None = None,
) -> WriteResult:
    """Replace one automation in ``automations.yaml``; return the backup of the whole file.

    The caller has validated ``new_config``. With ``expected_fingerprint`` the write only happens if the
    automation in the file is still the one that was looked at (checked under the lock, so a second
    request cannot slip in between). Reloading is a separate step (``async_reload``).
    """
    path = hass.config.path(AUTOMATION_FILE)
    async with _LOCK:
        if await hass.async_add_executor_job(_has_tags, path):
            raise AutomationEditError(TAGS_REASON)
        items = await hass.async_add_executor_job(_read, path)
        index = next((n for n, i in enumerate(items) if str(i.get("id")) == auto_id), None)
        if index is None:
            raise AutomationEditError("The automation is no longer in automations.yaml")
        if expected_fingerprint is not None and config_hash(items[index]) != expected_fingerprint:
            raise AutomationChanged("The automation changed after it was looked at")
        backup = _backup_path(hass, auto_id)
        await hass.async_add_executor_job(_copy_file, path, backup)
        items[index] = order_config(auto_id, new_config)
        await hass.async_add_executor_job(_write, path, items)
        written = await hass.async_add_executor_job(_read, path)
        now = next((i for i in written if str(i.get("id")) == auto_id), items[index])
    return WriteResult(backup, config_hash(now))


async def async_restore_automation(
    hass: HomeAssistant, auto_id: str, backup: Path, expected_fingerprint: str | None = None
) -> None:
    """Put one automation back as it was in a backup copy (the other automations stay as they are now).

    With ``expected_fingerprint`` the automation must still be the one that was written; otherwise a
    person's later edit would be overwritten.
    """
    path = hass.config.path(AUTOMATION_FILE)
    async with _LOCK:
        try:
            old_items = await hass.async_add_executor_job(_read, str(backup))
        except AutomationEditError as err:
            raise AutomationEditError(f"The backup cannot be read: {err}") from err
        old = next((i for i in old_items if str(i.get("id")) == auto_id), None)
        if old is None:
            raise AutomationEditError("The backup does not contain that automation")
        if await hass.async_add_executor_job(_has_tags, path):
            raise AutomationEditError(TAGS_REASON)
        items = await hass.async_add_executor_job(_read, path)
        index = next((n for n, i in enumerate(items) if str(i.get("id")) == auto_id), None)
        if (
            expected_fingerprint is not None
            and index is not None
            and config_hash(items[index]) != expected_fingerprint
        ):
            raise AutomationChanged("The automation was edited after the fix was applied")
        if index is None:
            items.append(old)
        else:
            items[index] = old
        await hass.async_add_executor_job(_write, path, items)


async def async_reload(hass: HomeAssistant, auto_id: str) -> None:
    """Reload one automation after its file changed."""
    await hass.services.async_call("automation", "reload", {"id": auto_id}, blocking=True)


# ------------------------------------------------------------------ creating and removing (habit ideas)


def new_automation_id() -> str:
    """An id like the ones Home Assistant's own editor makes (milliseconds since the epoch)."""
    return str(int(datetime.now().timestamp() * 1000))


async def async_add_automation(
    hass: HomeAssistant, config: dict[str, Any]
) -> tuple[str, WriteResult]:
    """Append a NEW automation to ``automations.yaml`` (backup first). Returns ``(id, WriteResult)``.

    The caller has validated ``config``. Reloading and switching it off are separate steps.
    """
    path = hass.config.path(AUTOMATION_FILE)
    async with _LOCK:
        if await hass.async_add_executor_job(_has_tags, path):
            raise AutomationEditError(TAGS_REASON)
        items = await hass.async_add_executor_job(_read, path)
        taken = {str(i.get("id")) for i in items}
        auto_id = new_automation_id()
        while auto_id in taken:
            auto_id = str(int(auto_id) + 1)
        backup = _backup_path(hass, auto_id)
        await hass.async_add_executor_job(_copy_file, path, backup)
        items.append(order_config(auto_id, config))
        await hass.async_add_executor_job(_write, path, items)
        written = await hass.async_add_executor_job(_read, path)
        now = next((i for i in written if str(i.get("id")) == auto_id), items[-1])
    return auto_id, WriteResult(backup, config_hash(now))


async def async_remove_automation(
    hass: HomeAssistant, auto_id: str, expected_fingerprint: str | None = None
) -> Path:
    """Remove one automation from ``automations.yaml`` (backup first); returns the backup.

    With ``expected_fingerprint`` the automation must still be the one that was written, otherwise a person's
    later edit would be thrown away. Removing the entity from the registry is the caller's job.
    """
    path = hass.config.path(AUTOMATION_FILE)
    async with _LOCK:
        if await hass.async_add_executor_job(_has_tags, path):
            raise AutomationEditError(TAGS_REASON)
        items = await hass.async_add_executor_job(_read, path)
        index = next((n for n, i in enumerate(items) if str(i.get("id")) == auto_id), None)
        if index is None:
            raise AutomationGone("The automation is not in automations.yaml any more")
        if expected_fingerprint is not None and config_hash(items[index]) != expected_fingerprint:
            raise AutomationChanged("The automation was edited after it was created")
        backup = _backup_path(hass, auto_id)
        await hass.async_add_executor_job(_copy_file, path, backup)
        del items[index]
        await hass.async_add_executor_job(_write, path, items)
    return backup
