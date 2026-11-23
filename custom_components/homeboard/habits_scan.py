"""Habits: scan the recorder for patterns, keep the ideas, create or undo an automation.

Opt-in learning feature ``habits`` (off by default). Everything stays inside Home Assistant. A created
automation is always switched off. See ``docs/DESIGN-0.4.md``.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, time, timedelta
from functools import partial
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later, async_track_time_change
from homeassistant.util import dt as dt_util
from homeassistant.util.yaml import dump

from . import habits
from .ai_context import _raw_config, registry_resolver
from .automation_config import (
    AutomationChanged,
    AutomationEditError,
    AutomationGone,
    async_add_automation,
    async_reload,
    async_remove_automation,
    async_validate,
    opaque_constructs,
    protected_hits,
)
from .const import EVENT_HABIT_AUTOMATION_CREATED, HEALTH_IGNORED_PLATFORMS
from .model import HomeboardError

if TYPE_CHECKING:
    from .data import HomeboardData

_LOGGER = logging.getLogger(__name__)

HABIT_DOMAINS = frozenset({"light", "switch", "fan", "cover"})
SENSOR_CLASSES = frozenset({"motion", "occupancy", "door", "window", "opening"})
# something that opens a garage or a gate, or is a lock / alarm in disguise, is never an "idea"
RISKY_COVER_CLASSES = frozenset({"garage", "gate", "door", "window", "awning"})
# names: long, specific words are matched anywhere, short generic ones only as whole words ("clock" is not "lock")
RISKY_SUBSTRINGS = ("alarm", "siren", "sirene", "garage")
RISKY_TOKENS = frozenset(
    {
        "lock", "lås", "gate", "port", "door", "dør", "valve", "ventil", "heat", "heater",
        "heating", "varme", "radiator", "oven", "ovn", "kedel", "boiler", "pump", "pumpe",
        "sprinkler", "vanding", "furnace", "kamin",
    }
)  # fmt: skip
# turning something off is the safe direction: a plug may be a heater, so "on" ideas are never made for these
OFF_ONLY_DOMAINS = frozenset({"switch"})
WORD_RE = re.compile(r"[a-zæøåéü0-9]+")
MAX_TARGETS = 150
MAX_SENSORS = 60
CHUNK = 40
MAX_CREATED = 20
HISTORY_DAYS = 28
SCAN_HOUR = 4
STALE_AFTER = timedelta(hours=36)
START_DELAY_SECONDS = 120

SERVICES = {
    ("light", "on"): "light.turn_on",
    ("light", "off"): "light.turn_off",
    ("switch", "on"): "switch.turn_on",
    ("switch", "off"): "switch.turn_off",
    ("fan", "on"): "fan.turn_on",
    ("fan", "off"): "fan.turn_off",
    ("cover", "on"): "cover.open_cover",
    ("cover", "off"): "cover.close_cover",
}
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri"]
WEEKEND = ["sat", "sun"]

TEXT: dict[str, dict[str, str]] = {
    "en": {
        "on": "on",
        "off": "off",
        "weekdays": " on weekdays",
        "weekends": " at weekends",
        "all": "",
        "g_all": "days",
        "g_weekdays": "weekdays",
        "g_weekends": "weekend days",
        "routine_title": "Turn {action} {name} at {time}{days}?",
        "routine_detail": "It was switched {action} on {n} of the last {of} {group}, between {lo} and {hi} (assuming no automation did it).",
        "follow_title": "Turn on {name} when {sensor} detects something?",
        "follow_detail": "{name} turned on within a minute of {sensor} in {n} of {out_of} cases.{night}",
        "night": " It happened after dark, so the idea only runs when the sun is down.",
        "back_title": "Turn off {name} {minutes} minutes after {sensor} goes quiet?",
        "back_detail": "{name} turned off about {minutes} minutes after {sensor} had gone quiet in {n} of {out_of} cases.",
        "alias_routine": "{name} {action} at {time}{days}",
        "alias_follow": "{name} on when {sensor} detects",
        "alias_back": "{name} off after {sensor} is quiet",
        "description": "Suggested by Homeboard from how the devices have been used. Created switched off: review it, then switch it on.",
    },
    "da": {
        "on": "tændt",
        "off": "slukket",
        "weekdays": " på hverdage",
        "weekends": " i weekenden",
        "all": "",
        "g_all": "dage",
        "g_weekdays": "hverdage",
        "g_weekends": "weekenddage",
        "routine_title": "{verb} {name} kl. {time}{days}?",
        "routine_detail": "Den blev {action} {n} af de seneste {of} {group} mellem {lo} og {hi} (hvis ikke en automation gjorde det).",
        "follow_title": "Tænd {name}, når {sensor} registrerer noget?",
        "follow_detail": "{name} blev tændt inden for et minut efter {sensor} i {n} af {out_of} tilfælde.{night}",
        "night": " Det skete efter mørkets frembrud, så idéen kører kun når solen er nede.",
        "back_title": "Sluk {name} {minutes} minutter efter {sensor} er blevet stille?",
        "back_detail": "{name} blev slukket ca. {minutes} minutter efter {sensor} var blevet stille i {n} af {out_of} tilfælde.",
        "alias_routine": "{name} {verb_ing} kl. {time}{days}",
        "alias_follow": "{name} tændes når {sensor} registrerer",
        "alias_back": "{name} slukkes når {sensor} er stille",
        "description": "Foreslået af Homeboard ud fra hvordan enhederne er blevet brugt. Oprettet slukket: gennemse den og slå den så til.",
    },
}


ON_SUFFIXES = ("turn_on", "open_cover", "open", "start")
OFF_SUFFIXES = ("turn_off", "close_cover", "close", "stop")


def acts_on(
    config: Any,
    entity_id: str,
    action: str,
    *,
    device_id: str | None = None,
    resolve: Any = None,
) -> bool:
    """True when an automation config could switch ``entity_id`` in the direction ``action`` ("on" / "off").

    Anything it cannot read (a script, ``toggle``, a template, a group, a device action) counts as "could".
    ``resolve`` turns an entity-registry id into an entity id.
    """
    found = False

    def refers(node: dict[str, Any]) -> bool:
        target = node.get("target") if isinstance(node.get("target"), dict) else {}
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        for value in (node.get("entity_id"), target.get("entity_id"), data.get("entity_id")):
            ids = value if isinstance(value, list) else [value] if isinstance(value, str) else []
            for item in ids:
                for part in str(item).split(","):
                    part = part.strip()
                    if part == entity_id or (resolve is not None and resolve(part) == entity_id):
                        return True
        return False

    def walk(node: Any) -> None:
        nonlocal found
        if isinstance(node, dict):
            service = node.get("action") or node.get("service")
            if device_id and node.get("device_id") == device_id and "domain" in node:
                found = True  # a device action: its direction is not readable here
            if isinstance(service, str) and refers(node):
                name = service.rsplit(".", 1)[-1].lower()
                domain = service.split(".", 1)[0].lower()
                if domain in ("script", "scene", "homeassistant", "automation") or "{{" in service:
                    found = True
                elif name in ON_SUFFIXES:
                    found = found or action == "on"
                elif name in OFF_SUFFIXES:
                    found = found or action == "off"
                else:  # toggle and friends
                    found = True
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(config.get("actions") or config.get("action") or [])
    return found


class HabitError(HomeboardError):
    """A refused or failed habits request (the code travels to the websocket client)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _lang(hass: HomeAssistant) -> str:
    return "da" if str(hass.config.language).lower().startswith("da") else "en"


def build_config(
    hass: HomeAssistant, candidate: dict[str, Any], names: dict[str, str]
) -> dict[str, Any]:
    """Return the automation config (a plain dict) for a candidate."""
    t = TEXT[_lang(hass)]
    entity = candidate["entity_id"]
    domain = entity.split(".", 1)[0]
    action = candidate["action"]
    name = names.get(entity, entity)
    service = SERVICES[(domain, action)]
    actions = [{"action": service, "target": {"entity_id": entity}}]
    conditions: list[dict[str, Any]] = []
    pattern = candidate["pattern"]
    sensor = candidate.get("trigger_entity")
    sensor_name = names.get(sensor or "", sensor or "")
    if pattern == "routine":
        hour, minute = candidate["time"].split(":")
        triggers = [{"trigger": "time", "at": f"{hour}:{minute}:00"}]
        group = candidate["day_group"]
        if group == "weekdays":
            conditions.append({"condition": "time", "weekday": list(WEEKDAYS)})
        elif group == "weekends":
            conditions.append({"condition": "time", "weekday": list(WEEKEND)})
        verb_ing = ("tændes" if action == "on" else "slukkes") if _lang(hass) == "da" else ""
        alias = t["alias_routine"].format(
            name=name,
            action=t[action],
            time=candidate["time"],
            days=t[group],
            verb_ing=verb_ing,
        )
    elif pattern == "follow_up":
        triggers = [{"trigger": "state", "entity_id": sensor, "to": "on"}]
        if candidate.get("night_only") and hass.states.get("sun.sun") is not None:
            conditions.append(
                {"condition": "state", "entity_id": "sun.sun", "state": "below_horizon"}
            )
        alias = t["alias_follow"].format(name=name, sensor=sensor_name)
    else:  # switch_back
        triggers = [
            {
                "trigger": "state",
                "entity_id": sensor,
                "to": "off",
                "for": {"hours": 0, "minutes": int(candidate["delay_minutes"]), "seconds": 0},
            }
        ]
        alias = t["alias_back"].format(name=name, sensor=sensor_name)
    config: dict[str, Any] = {
        "alias": alias,
        "description": t["description"],
        "mode": "single",
        "triggers": triggers,
        "conditions": conditions,
        "actions": actions,
    }
    return config


class HabitsScanner:
    """Mines the recorder history for habits and turns accepted ideas into (switched off) automations."""

    def __init__(self, hass: HomeAssistant, manager: HomeboardData) -> None:
        self.hass = hass
        self.manager = manager
        self._unsubs: list[CALLBACK_TYPE] = []
        self._scan_lock = asyncio.Lock()
        self._create_lock = asyncio.Lock()

    # ------------------------------------------------------------------ lifecycle

    @callback
    def async_start(self) -> None:
        self._unsubs.append(
            async_track_time_change(
                self.hass, self._async_nightly, hour=SCAN_HOUR, minute=0, second=0
            )
        )
        self._unsubs.append(
            async_call_later(self.hass, START_DELAY_SECONDS, self._async_after_start)
        )

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    async def _async_nightly(self, _now: datetime) -> None:
        if self.enabled:
            await self.async_scan()

    async def _async_after_start(self, _now: datetime) -> None:
        if not self.enabled:
            return
        block = self.block
        last = dt_util.parse_datetime(block.get("last_scan") or "")
        failed = block.get("error") in ("failed", "no_recorder")  # try again soon, not in 36 hours
        if last is None or failed or dt_util.utcnow() - last > STALE_AFTER:
            await self.async_scan()

    # ------------------------------------------------------------------ state

    @property
    def enabled(self) -> bool:
        learning = self.manager.learning
        return bool(learning is not None and learning.enabled("habits"))

    @property
    def block(self) -> dict[str, Any]:
        block = self.manager.learning_data.setdefault("habits", {})
        block.setdefault("candidates", [])
        block.setdefault("created", [])
        return block

    def _save(self) -> None:
        self.manager.learning._save()

    def status(self) -> dict[str, Any]:
        """The ``learned.habits`` block of the Insights page."""
        block = self.block
        return {
            "last_scan": block.get("last_scan"),
            "scanned_entities": block.get("scanned", 0),
            "days": block.get("days", 0),
            "error": block.get("error"),
            "created": [self.public_created(c) for c in block["created"]],
        }

    @staticmethod
    def public_created(record: dict[str, Any]) -> dict[str, Any]:
        view = {k: v for k, v in record.items() if not k.startswith("_")}
        view["edit_url"] = f"/config/automation/edit/{record['auto_id']}"
        return view

    # ------------------------------------------------------------------ scanning

    def _classify(self, entity_id: str) -> str | None:
        """Return ``"target"``, ``"sensor"`` or ``None`` (not something habits may look at or automate).

        One place for every rule, used when scanning, when listing the ideas and again right before creating.
        """
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        domain = entity_id.split(".", 1)[0]
        device_class = state.attributes.get("device_class")
        if domain in HABIT_DOMAINS:
            kind = "target"
        elif domain == "binary_sensor" and device_class in SENSOR_CLASSES:
            kind = "sensor"
        else:
            return None
        excluded_entities, excluded_integrations = self.manager.learning._excluded()
        entry = er.async_get(self.hass).async_get(entity_id)
        if (
            entry is None
            or entry.disabled_by
            or entry.hidden_by
            or entry.entity_category
            or entity_id in excluded_entities
            or entry.platform in HEALTH_IGNORED_PLATFORMS
            or entry.platform.lower() in excluded_integrations
            or state.attributes.get("restored")
        ):
            return None
        if domain == "cover" and device_class in RISKY_COVER_CLASSES:
            return None
        if kind == "target" and domain != "light":
            label = f"{entity_id} {state.attributes.get('friendly_name', '')}".lower()
            if any(word in label for word in RISKY_SUBSTRINGS) or RISKY_TOKENS & set(
                WORD_RE.findall(label)
            ):
                return None
        return kind

    def _allowed(self, candidate: dict[str, Any]) -> bool:
        """True when an idea may be shown and created now (every filter, also for ideas stored earlier)."""
        domain = candidate["entity_id"].split(".", 1)[0]
        if self._classify(candidate["entity_id"]) != "target":
            return False
        if domain in OFF_ONLY_DOMAINS and candidate["action"] == "on":
            return False
        sensor = candidate.get("trigger_entity")
        return sensor is None or self._classify(sensor) == "sensor"

    def _entities(self) -> tuple[list[str], list[str]]:
        """Return ``(targets, sensors)`` worth looking at."""
        targets: list[str] = []
        sensors: list[str] = []
        for state in self.hass.states.async_all():
            kind = self._classify(state.entity_id)
            if kind == "target":
                targets.append(state.entity_id)
            elif kind == "sensor":
                sensors.append(state.entity_id)
        return sorted(targets)[:MAX_TARGETS], sorted(sensors)[:MAX_SENSORS]

    async def _fetch(
        self, entity_ids: list[str], start: datetime, end: datetime
    ) -> dict[str, list[tuple[datetime, str]]]:
        """Read state history from the recorder (replaced in tests)."""
        try:
            from homeassistant.components import recorder
            from homeassistant.components.recorder import history

            instance = recorder.get_instance(self.hass)
        except (ImportError, KeyError) as err:
            raise HabitError("no_recorder", "The recorder is not available") from err
        out: dict[str, list[tuple[datetime, str]]] = {}
        for index in range(0, len(entity_ids), CHUNK):
            chunk = entity_ids[index : index + CHUNK]
            fetch = partial(
                history.get_significant_states,
                self.hass,
                start,
                end,
                chunk,
                include_start_time_state=True,
                significant_changes_only=True,
                minimal_response=False,
                no_attributes=True,
            )
            states = await instance.async_add_executor_job(fetch)
            for entity_id, items in states.items():
                out[entity_id] = [(dt_util.as_local(s.last_changed), s.state) for s in items]
        return out

    async def async_scan(self) -> dict[str, Any]:
        """Read the history, mine it, keep the ideas. Never raises: problems are in ``error``."""
        async with self._scan_lock:  # two scans at once would only read the recorder twice
            return await self._scan()

    async def _scan(self) -> dict[str, Any]:
        block = self.block
        result: dict[str, Any] = {"scanned": 0, "found": 0, "days": 0, "error": None}
        targets, sensors = self._entities()
        today = dt_util.now().date()
        tz = dt_util.get_default_time_zone()
        start = datetime.combine(today - timedelta(days=HISTORY_DAYS + 1), time.min, tzinfo=tz)
        try:
            if not targets:
                raise HabitError("no_history", "No lights, switches, fans or covers to look at")
            history_data = await self._fetch(
                targets + sensors, dt_util.as_utc(start), dt_util.utcnow()
            )
            mined = await self.hass.async_add_executor_job(
                partial(
                    habits.mine,
                    {e: s for e, s in history_data.items() if e in targets},
                    {e: s for e, s in history_data.items() if e in sensors},
                    today=today,
                    days=HISTORY_DAYS,
                )
            )
        except HabitError as err:
            result["error"] = err.code
        except Exception:
            _LOGGER.exception("Habit scan failed")
            result["error"] = "failed"
        else:
            result["scanned"] = len(history_data)
            result["days"] = mined["history_days"]
            result["error"] = mined["error"]
            if mined["error"] is None:
                candidates = [
                    c for c in mined["candidates"] if self._allowed(c) and not self._covered(c)
                ]
                block["candidates"] = candidates
                result["found"] = len(self.suggestions())
        block.update(
            last_scan=dt_util.utcnow().isoformat(),
            scanned=result["scanned"],
            days=result["days"],
            error=result["error"],
        )
        self._save()
        self.manager.learning.refresh()
        return result

    def _covered(self, candidate: dict[str, Any]) -> bool:
        """True when an automation already does what the idea would do (same entity, same direction).

        For a follow-up or a switch-back the automation must use the sensor as well. An automation whose
        config cannot be read counts as covering (better silent than a duplicate).
        """
        from homeassistant.components.automation import automations_with_entity

        target, action = candidate["entity_id"], candidate["action"]
        acting = set(automations_with_entity(self.hass, target))
        if candidate["pattern"] != "routine":
            acting &= set(automations_with_entity(self.hass, candidate["trigger_entity"]))
        entry = er.async_get(self.hass).async_get(target)
        device_id = entry.device_id if entry else None
        resolve = registry_resolver(self.hass)
        for automation in acting:
            config = _raw_config(self.hass, automation)
            if config is None or acts_on(
                config, target, action, device_id=device_id, resolve=resolve
            ):
                return True
        return False

    # ------------------------------------------------------------------ the inbox

    def _names(self, entity_ids: list[str | None]) -> dict[str, str]:
        names = {}
        for entity_id in entity_ids:
            if entity_id:
                state = self.hass.states.get(entity_id)
                names[entity_id] = str(
                    (state.attributes.get("friendly_name") if state else None) or entity_id
                )
        return names

    def suggestions(self) -> list[dict[str, Any]]:
        """The open ideas as suggestions of kind ``automation`` (the learning engine filters dismissed ones)."""
        lang = _lang(self.hass)
        t = TEXT[lang]
        found = []
        for c in self.block["candidates"]:
            if not self._allowed(c):  # also ideas stored before a rule changed
                continue
            names = self._names([c["entity_id"], c.get("trigger_entity")])
            name = names[c["entity_id"]]
            sensor = names.get(c.get("trigger_entity") or "", "")
            config = build_config(self.hass, c, names)
            evidence = {
                k: c[k]
                for k in ("pattern", "days", "of", "share", "window", "delay_minutes", "samples")
                if k in c
            }
            if c["pattern"] == "routine":
                action = t[c["action"]]
                verb = ("Tænd" if c["action"] == "on" else "Sluk") if lang == "da" else ""
                title = t["routine_title"].format(
                    action=action, verb=verb, name=name, time=c["time"], days=t[c["day_group"]]
                )
                detail = t["routine_detail"].format(
                    action=action,
                    n=c["days"],
                    of=c["of"],
                    group=t["g_" + c["day_group"]],
                    lo=c["window"][0],
                    hi=c["window"][1],
                )
            elif c["pattern"] == "follow_up":
                title = t["follow_title"].format(name=name, sensor=sensor)
                detail = t["follow_detail"].format(
                    name=name,
                    sensor=sensor,
                    n=c["samples"],
                    out_of=c["out_of"],
                    night=t["night"]
                    if c.get("night_only") and self.hass.states.get("sun.sun") is not None
                    else "",
                )
            else:
                title = t["back_title"].format(name=name, sensor=sensor, minutes=c["delay_minutes"])
                detail = t["back_detail"].format(
                    name=name,
                    sensor=sensor,
                    minutes=c["delay_minutes"],
                    n=c["samples"],
                    out_of=c["out_of"],
                )
            found.append(
                {
                    "id": c["id"],
                    "kind": "automation",
                    "title": title,
                    "detail": detail,
                    "evidence": evidence,
                    "proposal": {
                        "alias": config["alias"],
                        "description": config["description"],
                        "entity_id": c["entity_id"],
                        "trigger_entity": c.get("trigger_entity"),
                        "yaml": dump(config).rstrip(),
                        "_config": config,
                        "_candidate": c,
                    },
                }
            )
        return found

    # ------------------------------------------------------------------ create / undo

    def _suggestion(self, suggestion_id: str) -> dict[str, Any]:
        learning = self.manager.learning
        found = next(
            (
                s
                for s in learning._suggestions
                if s["id"] == suggestion_id and s["kind"] == "automation"
            ),
            None,
        )
        if found is None:
            raise HabitError("not_found", "That idea is no longer in the inbox.")
        return found

    async def async_create(self, suggestion_id: str, actor: str | None) -> dict[str, Any]:
        """Create the automation of an idea, switched off (an administrator pressed the button)."""
        if not self.enabled:
            raise HabitError("habits_disabled", "Habits is switched off in the Homeboard options.")
        async with self._create_lock:  # two presses never make two automations
            return await self._create(suggestion_id)

    async def _create(self, suggestion_id: str) -> dict[str, Any]:
        suggestion = self._suggestion(suggestion_id)
        proposal = suggestion["proposal"]
        candidate, config = proposal["_candidate"], proposal["_config"]
        if not self._allowed(candidate):
            raise HabitError("blocked", "This is not something Homeboard automates (any more).")
        if self._covered(candidate):
            self.block["candidates"] = [
                c for c in self.block["candidates"] if c["id"] != suggestion_id
            ]  # it is done already: it leaves the inbox
            self.manager.learning.refresh()
            raise HabitError("exists", "An automation already does this.")
        if protected_hits(self.hass, config) or opaque_constructs(config):
            raise HabitError("blocked", "This touches something Homeboard never automates.")
        try:
            await async_validate(self.hass, "habit", config)
        except AutomationEditError as err:
            raise HabitError("blocked", str(err)[:300]) from err
        try:
            auto_id, written = await async_add_automation(self.hass, config)
        except (AutomationEditError, OSError) as err:
            raise HabitError("not_editable", str(err)[:300]) from err
        try:
            entity_id = await self._load_and_switch_off(auto_id)
        except Exception:
            _LOGGER.exception("Could not switch the new automation off")
            entity_id = None
        if entity_id is None:
            try:
                await self._remove(auto_id, written.fingerprint)
            except (AutomationEditError, OSError, HomeAssistantError) as err:
                raise HabitError(
                    "create_failed",
                    f"The new automation did not come up switched off and could not be removed "
                    f"({str(err)[:120]}). Check automation {auto_id} in Home Assistant.",
                ) from err
            raise HabitError(
                "create_failed", "The new automation did not load. It was removed again."
            )
        record = {
            "id": dt_util.utcnow().strftime("%Y%m%d%H%M%S%f"),
            "suggestion_id": suggestion_id,
            "auto_id": auto_id,
            "entity_id": entity_id,
            "alias": config["alias"],
            "ts": dt_util.utcnow().isoformat(),
            "state": "created",
            "_fingerprint": written.fingerprint,
            "_backup": str(written.backup),
        }
        block = self.block
        block["created"].insert(0, record)
        del block["created"][MAX_CREATED:]
        self.manager.learning._dismiss_id(suggestion_id)
        self._save()
        self.manager.learning.refresh()
        self.hass.bus.async_fire(
            EVENT_HABIT_AUTOMATION_CREATED,
            {"suggestion_id": suggestion_id, "auto_id": auto_id, "entity_id": entity_id},
        )
        return self.public_created(record)

    async def _load_and_switch_off(self, auto_id: str) -> str | None:
        """Reload, find the new automation, switch it off and CHECK it is off. ``None`` otherwise."""
        try:
            await async_reload(self.hass, auto_id)
        except HomeAssistantError:
            return None
        entity_id = er.async_get(self.hass).async_get_entity_id("automation", "automation", auto_id)
        state = self.hass.states.get(entity_id) if entity_id else None
        if entity_id is None or state is None or state.state == "unavailable":
            return None
        await self.hass.services.async_call(
            "automation", "turn_off", {"entity_id": entity_id}, blocking=True
        )
        state = self.hass.states.get(entity_id)
        if state is None or state.state != "off":
            return None
        try:  # the "off" is remembered across a crash, not only at the next 15 minute dump
            from homeassistant.helpers.restore_state import async_get as restore_state

            await restore_state(self.hass).async_dump_states()
        except Exception:
            _LOGGER.debug("Could not dump the restore state")
        return entity_id

    async def _remove(self, auto_id: str, fingerprint: str | None) -> None:
        await async_remove_automation(self.hass, auto_id, fingerprint)
        self._forget_entity(auto_id)

    def _forget_entity(self, auto_id: str) -> None:
        registry = er.async_get(self.hass)
        entity_id = registry.async_get_entity_id("automation", "automation", auto_id)
        if entity_id:
            registry.async_remove(entity_id)

    async def async_undo(self, created_id: str) -> dict[str, Any]:
        """Remove an automation that was created from an idea."""
        record = next((c for c in self.block["created"] if c["id"] == created_id), None)
        if record is None:
            raise HabitError("not_found", "There is no such created automation.")
        if record["state"] != "created":
            raise HabitError("not_found", "It was already removed.")
        try:
            await self._remove(record["auto_id"], record.get("_fingerprint"))
        except AutomationGone:  # deleted in Home Assistant already: nothing left to remove
            self._forget_entity(record["auto_id"])
        except AutomationChanged as err:
            raise HabitError(
                "stale",
                "The automation was edited after it was created, so it is not removed. Delete it in Home Assistant.",
            ) from err
        except AutomationEditError as err:
            raise HabitError("not_editable", str(err)[:300]) from err
        record["state"] = "undone"
        dismissed = self.manager.learning.data.get("dismissed", [])
        if record["suggestion_id"] in dismissed:
            dismissed.remove(record["suggestion_id"])  # changed my mind: the idea may come back
        self._save()
        self.manager.learning.refresh()
        return self.public_created(record)

    # ------------------------------------------------------------------ forget

    def forget(self) -> bool:
        """Drop the ideas and what was learned from the scan (created automations stay)."""
        block = self.manager.learning_data.get("habits")
        if block is None:
            return False
        had = bool(block.get("candidates") or block.get("last_scan"))
        block["candidates"] = []
        for key in ("last_scan", "scanned", "days", "error"):
            block.pop(key, None)
        if not block.get("created"):
            del self.manager.learning_data["habits"]  # nothing left worth keeping
        return had
