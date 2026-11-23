"""Homeboard: a Jira-inspired kanban and issue tracker native to Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .ai_fix import AiFixEngine
from .assist import async_setup_assist, async_unload_assist
from .const import CONF_STARTER_PROJECT, DOMAIN
from .data import HomeboardData
from .files import FileStore, async_register_views
from .frontend import async_register_frontend, async_unregister_frontend
from .habits_scan import HabitsScanner
from .health import HealthMonitor
from .learning import LearningEngine
from .notify import async_setup_notifications
from .push import PushNotifier
from .services import async_setup_services
from .store import HomeboardStore
from .websocket_api import async_register_websocket_api

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CALENDAR,
    Platform.SENSOR,
    Platform.TODO,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type HomeboardConfigEntry = ConfigEntry[HomeboardData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register services and the websocket API (they exist even before the entry loads)."""
    async_setup_services(hass)
    async_register_websocket_api(hass)
    async_register_views(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HomeboardConfigEntry) -> bool:
    """Set up Homeboard from its config entry."""
    manager = HomeboardData(hass, HomeboardStore(hass), entry.options)
    await manager.async_load()
    integration = await async_get_integration(hass, DOMAIN)
    manager.version = str(integration.version)

    if entry.data.get(CONF_STARTER_PROJECT) and not manager.projects:
        manager.create_project(key="HOME", name="Home", icon="mdi:home")
    if entry.data.get(CONF_STARTER_PROJECT):
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_STARTER_PROJECT: False}
        )

    entry.runtime_data = manager
    hass.data[DOMAIN] = manager
    await async_setup_assist(hass, entry)
    manager.health = HealthMonitor(hass, manager)
    manager.files = FileStore(hass, manager)
    manager.push = PushNotifier(hass, manager)
    manager.learning = LearningEngine(hass, manager)
    manager.ai = AiFixEngine(hass, manager)
    manager.habits = HabitsScanner(hass, manager)

    await async_register_frontend(hass, dict(entry.options), manager.version)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    manager.async_start()
    manager.health.async_start()
    manager.push.async_start()
    manager.learning.async_start()
    manager.habits.async_start()
    async_setup_notifications(hass, entry)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HomeboardConfigEntry) -> bool:
    """Unload Homeboard."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        manager = entry.runtime_data
        manager.async_stop()
        if manager.health:
            manager.health.async_stop()
        if manager.push:
            manager.push.async_stop()
        if manager.learning:
            manager.learning.async_stop()
        if manager.ai:
            manager.ai.async_stop()
        if manager.habits:
            manager.habits.async_stop()
        async_unregister_frontend(hass)
        await async_unload_assist(hass, entry)
        await manager.async_save_now()
        hass.data.pop(DOMAIN, None)
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: HomeboardConfigEntry) -> None:
    """Leave no Assist sentence files behind when the integration is deleted."""
    await async_unload_assist(hass, entry)
