"""The real http + frontend + panel_custom stack (needs home-assistant-frontend installed)."""

from __future__ import annotations

import pytest
from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL, DATA_PANELS
from homeassistant.setup import async_setup_component

from custom_components.homeboard.const import DOMAIN

from .conftest import setup

pytestmark = pytest.mark.real_frontend


async def test_panel_cards_and_static_files_are_registered_for_real(hass, entry, hass_client):
    assert await async_setup_component(hass, "frontend", {})
    await setup(hass, entry)
    version = entry.runtime_data.version
    assert version == "0.1.0"

    panel = hass.data[DATA_PANELS]["homeboard"]
    assert panel.component_name == "custom"
    assert panel.sidebar_title == "Board" and panel.sidebar_icon == "mdi:view-column"
    assert panel.config["_panel_custom"]["name"] == "homeboard-panel"
    assert (
        panel.config["_panel_custom"]["module_url"]
        == f"/homeboard_static/{version}/homeboard-panel.js"
    )
    assert f"/homeboard_static/{version}/homeboard-card.js" in hass.data[DATA_EXTRA_MODULE_URL].urls

    client = await hass_client()
    for name in ("homeboard-panel.js", "homeboard-card.js"):
        response = await client.get(f"/homeboard_static/{version}/{name}")
        assert response.status == 200, name
        assert "javascript" in response.headers["content-type"]
        assert "max-age" in response.headers.get("cache-control", "")
    assert (await client.get(f"/homeboard_static/{version}/missing.js")).status == 404

    # options re-register the panel with the new title; unload removes it
    hass.config_entries.async_update_entry(
        entry, options={"panel_title": "Tavle", "panel_icon": "mdi:home"}
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.data[DATA_PANELS]["homeboard"].sidebar_title == "Tavle"
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert "homeboard" not in hass.data[DATA_PANELS]
    assert DOMAIN not in hass.data
