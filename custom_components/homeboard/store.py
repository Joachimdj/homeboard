"""Persistent storage for Homeboard."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION


class HomeboardStore(Store[dict[str, Any]]):
    """Store wrapper with a migration hook (``/config/.storage/homeboard``)."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialise the store."""
        super().__init__(hass, STORAGE_VERSION, STORAGE_KEY, minor_version=1)

    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Migrate older documents. Version 1 is the first, nothing to do yet."""
        return old_data
