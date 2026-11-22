"""Panel and static-file registration (the real HTTP stack is mocked)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.homeboard import frontend
from custom_components.homeboard.const import DATA_FRONTEND_READY, PANEL_URL_PATH


@pytest.fixture
def stubs(hass):
    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()
    with (
        patch.object(frontend, "panel_custom") as panel_custom,
        patch.object(frontend, "frontend") as frontend_mod,
    ):
        panel_custom.async_register_panel = AsyncMock()
        yield hass, panel_custom, frontend_mod


async def test_registers_static_files_cards_and_panel(stubs, tmp_path, monkeypatch):
    hass, panel_custom, frontend_mod = stubs
    monkeypatch.setattr(frontend, "STATIC_DIR", tmp_path)
    await frontend.async_register_frontend(
        hass, {"panel_title": "Tavle", "panel_icon": "mdi:home", "panel_admin_only": True}, "1.2.3"
    )

    [config] = hass.http.async_register_static_paths.await_args.args[0]
    assert (
        config.url_path == "/homeboard_static/1.2.3"
        and config.path == str(tmp_path)
        and config.cache_headers
    )
    frontend_mod.add_extra_js_url.assert_called_once_with(
        hass, "/homeboard_static/1.2.3/homeboard-card.js"
    )
    kwargs = panel_custom.async_register_panel.await_args.kwargs
    assert (
        kwargs["frontend_url_path"] == PANEL_URL_PATH
        and kwargs["webcomponent_name"] == "homeboard-panel"
    )
    assert kwargs["module_url"] == "/homeboard_static/1.2.3/homeboard-panel.js"
    assert kwargs["sidebar_title"] == "Tavle" and kwargs["sidebar_icon"] == "mdi:home"
    assert kwargs["require_admin"] is True and kwargs["embed_iframe"] is False
    assert hass.data[DATA_FRONTEND_READY] == "/homeboard_static/1.2.3"


async def test_static_path_is_registered_once_but_the_panel_is_refreshed(
    stubs, tmp_path, monkeypatch
):
    hass, panel_custom, frontend_mod = stubs
    monkeypatch.setattr(frontend, "STATIC_DIR", tmp_path)
    await frontend.async_register_frontend(hass, {}, "1.0.0")
    await frontend.async_register_frontend(hass, {"panel_title": "Other"}, "1.0.1")
    assert hass.http.async_register_static_paths.await_count == 1
    assert panel_custom.async_register_panel.await_count == 2
    assert panel_custom.async_register_panel.await_args.kwargs["module_url"].startswith(
        "/homeboard_static/1.0.0/"
    )
    assert panel_custom.async_register_panel.await_args.kwargs["sidebar_title"] == "Other"
    assert panel_custom.async_register_panel.await_args.kwargs["require_admin"] is False
    assert frontend_mod.async_remove_panel.call_count == 2


async def test_missing_static_dir_is_a_warning_not_a_crash(stubs, tmp_path, monkeypatch, caplog):
    hass, panel_custom, _ = stubs
    monkeypatch.setattr(frontend, "STATIC_DIR", tmp_path / "nope")
    await frontend.async_register_frontend(hass, {}, "1.0.0")
    assert "frontend files are missing" in caplog.text
    panel_custom.async_register_panel.assert_not_awaited()


async def test_unregister_removes_panel_and_card(stubs, tmp_path, monkeypatch):
    hass, _, frontend_mod = stubs
    monkeypatch.setattr(frontend, "STATIC_DIR", tmp_path)
    await frontend.async_register_frontend(hass, {}, "2.0.0")
    frontend.async_unregister_frontend(hass)
    frontend_mod.async_remove_panel.assert_called_with(hass, PANEL_URL_PATH, warn_if_unknown=False)
    frontend_mod.remove_extra_js_url.assert_called_once_with(
        hass, "/homeboard_static/2.0.0/homeboard-card.js"
    )


async def test_static_assets_exist_for_the_entry_points():
    assert (frontend.STATIC_DIR / "homeboard-panel.js").is_file()
    assert (frontend.STATIC_DIR / "homeboard-card.js").is_file()
