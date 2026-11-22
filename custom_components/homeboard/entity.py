"""Shared entity plumbing for Homeboard platforms."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, NAME, SIGNAL_UPDATED
from .data import HomeboardData

SERVICE_DEVICE_ID = "service"


class HomeboardEntity(Entity):
    """Base class: a live view over the data manager."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, manager: HomeboardData, project_id: str | None = None) -> None:
        """Initialise a view entity (project_id None = the service device)."""
        self.manager = manager
        self.project_id = project_id

    @property
    def project(self) -> dict[str, Any] | None:
        """Return the project this entity belongs to."""
        return self.manager.projects.get(self.project_id) if self.project_id else None

    @property
    def available(self) -> bool:
        """Project entities are unavailable once their project is gone."""
        return self.project_id is None or self.project is not None

    @property
    def device_info(self) -> DeviceInfo:
        """Group entities under a project device (or the global device)."""
        if self.project_id is None:
            return DeviceInfo(
                identifiers={(DOMAIN, SERVICE_DEVICE_ID)},
                name=NAME,
                manufacturer=NAME,
                entry_type=DeviceEntryType.SERVICE,
            )
        project = self.project
        return DeviceInfo(
            identifiers={(DOMAIN, self.project_id)},
            name=project["name"] if project else self.project_id,
            manufacturer=NAME,
            model="Project",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        """Refresh whenever the data changes."""
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_UPDATED, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


@callback
def async_setup_synced_entities(
    hass: HomeAssistant,
    manager: HomeboardData,
    platform: str,
    async_add_entities: AddConfigEntryEntitiesCallback,
    desired: Callable[[], dict[str, Callable[[], Entity]]],
    unsub_register: Callable[[Callable[[], None]], None],
    *,
    after_sync: Callable[[], None] | None = None,
) -> None:
    """Keep a platform's entities in step with the data.

    ``desired()`` returns ``{unique_id: factory}``. Entities that appear are
    added, entities whose unique id is no longer wanted are removed from the
    registry (a deleted project, status or person).
    """
    known: set[str] = set()

    @callback
    def sync() -> None:
        wanted = desired()
        new = [factory() for uid, factory in wanted.items() if uid not in known]
        known.update(wanted)
        if new:
            async_add_entities(new)
        stale = known - set(wanted)
        if stale:
            registry = er.async_get(hass)
            for uid in stale:
                if entity_id := registry.async_get_entity_id(platform, DOMAIN, uid):
                    registry.async_remove(entity_id)
            known.difference_update(stale)
        if after_sync:
            after_sync()

    sync()
    unsub_register(async_dispatcher_connect(hass, SIGNAL_UPDATED, sync))


@callback
def async_sync_devices(hass: HomeAssistant, manager: HomeboardData) -> None:
    """Rename project devices and drop devices of deleted projects."""
    registry = dr.async_get(hass)
    for device in list(dr.async_entries_for_config_entry(registry, _entry_id(hass))):
        ids = {i[1] for i in device.identifiers if i[0] == DOMAIN}
        if not ids or SERVICE_DEVICE_ID in ids:
            continue
        project = manager.projects.get(next(iter(ids)))
        if project is None:
            registry.async_remove_device(device.id)
        elif device.name != project["name"] and not device.name_by_user:
            registry.async_update_device(device.id, name=project["name"])


def _entry_id(hass: HomeAssistant) -> str:
    entries = hass.config_entries.async_entries(DOMAIN)
    return entries[0].entry_id if entries else ""
