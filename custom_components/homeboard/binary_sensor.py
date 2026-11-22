"""Binary sensor: does a project have overdue issues?"""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HomeboardConfigEntry
from .data import HomeboardData
from .entity import HomeboardEntity, async_setup_synced_entities

PARALLEL_UPDATES = 0


class HomeboardOverdueBinarySensor(HomeboardEntity, BinarySensorEntity):
    """On when at least one open issue of the project is overdue."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "has_overdue"

    def __init__(self, manager: HomeboardData, project_id: str) -> None:
        """Initialise the sensor."""
        super().__init__(manager, project_id)
        self._attr_unique_id = f"{project_id}_has_overdue"

    @property
    def is_on(self) -> bool | None:
        """Return True when something is overdue."""
        block = self.manager.stats()["projects"].get(self.project_id or "")
        return None if block is None else block["overdue"] > 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeboardConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one binary sensor per project."""
    manager = entry.runtime_data

    def desired() -> dict[str, Callable[[], Entity]]:
        return {
            f"{pid}_has_overdue": lambda p=pid: HomeboardOverdueBinarySensor(manager, p)
            for pid in manager.projects
        }

    async_setup_synced_entities(
        hass, manager, "binary_sensor", async_add_entities, desired, entry.async_on_unload
    )
