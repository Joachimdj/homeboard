"""Frontend wiring: static files, sidebar panel and the auto-loaded Lovelace cards.

The static files are served under ``/homeboard_static/<version>/``. Putting the
version in the *path* busts the browser cache on every release without a build
step, even for the relative ``import`` statements between the modules.
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import (
    CARD_JS,
    CONF_PANEL_ADMIN_ONLY,
    CONF_PANEL_ICON,
    CONF_PANEL_TITLE,
    DATA_FRONTEND_READY,
    DEFAULT_PANEL_ICON,
    DEFAULT_PANEL_TITLE,
    PANEL_ELEMENT,
    PANEL_JS,
    PANEL_URL_PATH,
    STATIC_URL_BASE,
)

_LOGGER = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def static_base(version: str) -> str:
    """Return the URL prefix the static files are served under."""
    return f"{STATIC_URL_BASE}/{version}"


async def async_register_frontend(hass: HomeAssistant, options: dict, version: str) -> None:
    """Serve the assets, auto-load the cards and register the sidebar panel."""
    if not STATIC_DIR.is_dir():
        _LOGGER.warning("Homeboard frontend files are missing (%s)", STATIC_DIR)
        return
    base = static_base(version)

    # Static paths and the card module can only be registered once per HA run.
    if not hass.data.get(DATA_FRONTEND_READY):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(base, str(STATIC_DIR), cache_headers=True)]
        )
        hass.data[DATA_FRONTEND_READY] = base
    frontend.add_extra_js_url(hass, f"{hass.data[DATA_FRONTEND_READY]}/{CARD_JS}")

    # (Re-)register the sidebar panel so option changes (title, icon) apply.
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_ELEMENT,
        module_url=f"{hass.data[DATA_FRONTEND_READY]}/{PANEL_JS}",
        sidebar_title=options.get(CONF_PANEL_TITLE, DEFAULT_PANEL_TITLE),
        sidebar_icon=options.get(CONF_PANEL_ICON, DEFAULT_PANEL_ICON),
        require_admin=bool(options.get(CONF_PANEL_ADMIN_ONLY, False)),
        embed_iframe=False,
        trust_external=False,
    )


def async_unregister_frontend(hass: HomeAssistant) -> None:
    """Remove the panel (the static path stays until HA restarts)."""
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
    if base := hass.data.get(DATA_FRONTEND_READY):
        frontend.remove_extra_js_url(hass, f"{base}/{CARD_JS}")
