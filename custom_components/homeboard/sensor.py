"""Sensors: counts per project, per status and per person."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import HomeboardConfigEntry
from .data import HomeboardData
from .entity import HomeboardEntity, async_setup_synced_entities, async_sync_devices

PARALLEL_UPDATES = 0
UNIT = "issues"


@dataclass(frozen=True, kw_only=True)
class HomeboardSensorDescription(SensorEntityDescription):
    """Describes a sensor over the stats block."""

    value_fn: Callable[[dict[str, Any]], Any]
    attrs_fn: Callable[[HomeboardData, str | None, dict[str, Any]], dict[str, Any]] | None = None


def _count(key: str) -> Callable[[dict[str, Any]], int]:
    return lambda block: block[key]


def _last_activity(block: dict[str, Any]) -> datetime | None:
    value = block["last_activity"]
    return dt_util.parse_datetime(value) if value else None


def _open_attrs(
    manager: HomeboardData, project_id: str | None, block: dict[str, Any]
) -> dict[str, Any]:
    if project_id is None:
        return {
            "projects": {
                p["key"]: manager.stats()["projects"][p["id"]]["open"]
                for p in manager.projects.values()
            }
        }
    project = manager.projects[project_id]
    names = {s["id"]: s["name"] for s in project["statuses"]}
    return {
        "project": project["key"],
        "by_status": {names[k]: v for k, v in block["by_status"].items() if k in names},
        "by_priority": block["by_priority"],
        "by_type": block["by_type"],
    }


def _issues_attrs(
    flag: str,
) -> Callable[[HomeboardData, str | None, dict[str, Any]], dict[str, Any]]:
    def attrs(
        manager: HomeboardData, project_id: str | None, _block: dict[str, Any]
    ) -> dict[str, Any]:
        return {"issues": manager.top_issues(flag, project_id=project_id)}

    return attrs


def _description(key: str, value_fn, *, attrs_fn=None, **extra) -> HomeboardSensorDescription:
    return HomeboardSensorDescription(
        key=key,
        translation_key=key,
        value_fn=value_fn,
        attrs_fn=attrs_fn,
        **extra,
    )


COUNT_KWARGS = {
    "native_unit_of_measurement": UNIT,
    "state_class": SensorStateClass.MEASUREMENT,
}

PROJECT_SENSORS = (
    _description("open_issues", _count("open"), attrs_fn=_open_attrs, **COUNT_KWARGS),
    _description("overdue", _count("overdue"), attrs_fn=_issues_attrs("overdue"), **COUNT_KWARGS),
    _description(
        "due_soon", _count("due_soon"), attrs_fn=_issues_attrs("due_soon"), **COUNT_KWARGS
    ),
    _description("unassigned", _count("unassigned"), **COUNT_KWARGS),
    _description("last_activity", _last_activity, device_class=SensorDeviceClass.TIMESTAMP),
)


def _health_attrs(
    manager: HomeboardData, _project_id: str | None, _block: dict[str, Any]
) -> dict[str, Any]:
    last = manager.health.last_result if manager.health else None
    return {
        "last_scan": {k: last[k] for k in ("created", "reopened", "closed", "suppressed")}
        if last and "created" in last
        else None,
        "enabled": bool(manager.health and manager.health.enabled),
        "awaiting_review": bool(manager.health and manager.health.awaiting_review),
    }


GLOBAL_SENSORS = (
    _description("total_open", _count("open"), attrs_fn=_open_attrs, **COUNT_KWARGS),
    _description(
        "total_overdue", _count("overdue"), attrs_fn=_issues_attrs("overdue"), **COUNT_KWARGS
    ),
    _description(
        "total_due_soon", _count("due_soon"), attrs_fn=_issues_attrs("due_soon"), **COUNT_KWARGS
    ),
    _description("auto_issues", _count("health_open"), attrs_fn=_health_attrs, **COUNT_KWARGS),
    _description("total_last_activity", _last_activity, device_class=SensorDeviceClass.TIMESTAMP),
)


class HomeboardSensor(HomeboardEntity, SensorEntity):
    """A statistic of one project or of everything."""

    entity_description: HomeboardSensorDescription

    def __init__(
        self,
        manager: HomeboardData,
        description: HomeboardSensorDescription,
        project_id: str | None,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(manager, project_id)
        self.entity_description = description
        self._attr_unique_id = f"{project_id or 'global'}_{description.key}"

    def _block(self) -> dict[str, Any]:
        stats = self.manager.stats()
        if self.project_id is None:
            return stats["total"]
        return stats["projects"].get(self.project_id) or {}

    @property
    def native_value(self) -> Any:
        """Return the statistic."""
        block = self._block()
        return self.entity_description.value_fn(block) if block else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return attributes with details for dashboards / templates."""
        block = self._block()
        if not block or self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.manager, self.project_id, block)


class HomeboardStatusSensor(HomeboardEntity, SensorEntity):
    """Number of issues in one status (column) of a project."""

    _attr_native_unit_of_measurement = UNIT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, manager: HomeboardData, project_id: str, status_id: str) -> None:
        """Initialise the sensor."""
        super().__init__(manager, project_id)
        self.status_id = status_id
        self._attr_unique_id = f"{project_id}_status_{status_id}"

    @property
    def _status(self) -> dict[str, Any] | None:
        project = self.project
        if project is None:
            return None
        return next((s for s in project["statuses"] if s["id"] == self.status_id), None)

    @property
    def name(self) -> str | None:  # type: ignore[override]
        """Return the status name (changes when the column is renamed)."""
        status = self._status
        return status["name"] if status else self.status_id

    @property
    def available(self) -> bool:
        """Unavailable once the status is removed."""
        return self._status is not None

    @property
    def native_value(self) -> int | None:
        """Return how many issues sit in the status."""
        block = self.manager.stats()["projects"].get(self.project_id or "")
        return block["by_status"].get(self.status_id, 0) if block else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return category and WIP limit."""
        status = self._status
        if status is None:
            return None
        return {"category": status["category"], "wip": status["wip"], "backlog": status["backlog"]}


class HomeboardPersonSensor(HomeboardEntity, SensorEntity):
    """Open issues assigned to one person."""

    _attr_native_unit_of_measurement = UNIT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:account-clock"

    def __init__(self, manager: HomeboardData, person: str) -> None:
        """Initialise the sensor."""
        super().__init__(manager, None)
        self.person = person
        self._attr_unique_id = f"person_{person}"

    @property
    def name(self) -> str:  # type: ignore[override]
        """Return '<person name> assigned'."""
        state = self.hass.states.get(self.person) if self.hass else None
        who = state.name if state else self.person.split(".", 1)[1].replace("_", " ").title()
        return f"{who} assigned"

    @property
    def native_value(self) -> int:
        """Return the number of open issues assigned."""
        return self.manager.stats()["people"].get(self.person, {}).get("open", 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the workload breakdown and the next issues."""
        block = self.manager.stats()["people"].get(self.person, {})
        return {
            "person": self.person,
            "overdue": block.get("overdue", 0),
            "in_progress": block.get("in_progress", 0),
            "done_7d": block.get("done_7d", 0),
            "issues": self.manager.top_issues("open", person=self.person),
        }


class HomeboardSuggestionsSensor(HomeboardEntity, SensorEntity):
    """Number of open learning suggestions (recurring chores, noisy faults, digest times)."""

    _attr_translation_key = "suggestions"
    _attr_native_unit_of_measurement = "suggestions"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_unique_id = "global_suggestions"

    def __init__(self, manager: HomeboardData) -> None:
        """Initialise the sensor."""
        super().__init__(manager, None)

    @property
    def native_value(self) -> int:
        """Return how many suggestions are open."""
        return self.manager.learning.open_count() if self.manager.learning else 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """List the open suggestions."""
        items = self.manager.learning._suggestions if self.manager.learning else []
        return {
            "suggestions": [{"id": i["id"], "kind": i["kind"], "title": i["title"]} for i in items]
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeboardConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors and keep them in sync with projects, statuses and people."""
    manager = entry.runtime_data

    def desired() -> dict[str, Callable[[], Entity]]:
        wanted: dict[str, Callable[[], Entity]] = {}
        for description in GLOBAL_SENSORS:
            wanted[f"global_{description.key}"] = lambda d=description: HomeboardSensor(
                manager, d, None
            )
        wanted["global_suggestions"] = lambda: HomeboardSuggestionsSensor(manager)
        for project in manager.projects.values():
            pid = project["id"]
            for description in PROJECT_SENSORS:
                wanted[f"{pid}_{description.key}"] = lambda d=description, p=pid: HomeboardSensor(
                    manager, d, p
                )
            for status in project["statuses"]:
                wanted[f"{pid}_status_{status['id']}"] = lambda p=pid, s=status["id"]: (
                    HomeboardStatusSensor(manager, p, s)
                )
        for person in manager.tracked_people():
            wanted[f"person_{person}"] = lambda p=person: HomeboardPersonSensor(manager, p)
        return wanted

    async_setup_synced_entities(
        hass,
        manager,
        "sensor",
        async_add_entities,
        desired,
        entry.async_on_unload,
        after_sync=lambda: async_sync_devices(hass, manager),
    )
