"""Setup, unload, config flow, options flow and entities."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homeboard.const import CONF_STARTER_PROJECT, DOMAIN

from .conftest import setup


async def test_setup_creates_starter_project_once(hass, entry):
    await setup(hass, entry)
    manager = entry.runtime_data
    assert entry.state is ConfigEntryState.LOADED
    assert [p["key"] for p in manager.projects.values()] == ["HOME"]
    assert hass.data[DOMAIN] is manager
    # The flag is consumed so deleting the project later never recreates it.
    assert entry.data[CONF_STARTER_PROJECT] is False
    manager.delete_project("HOME")
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.projects == {}


async def test_setup_without_starter_project(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_STARTER_PROJECT: False})
    await setup(hass, entry)
    assert entry.runtime_data.projects == {}


async def test_unload_and_reload_keep_the_data(hass, entry):
    await setup(hass, entry)
    manager = entry.runtime_data
    manager.create_issue("HOME", "Keep me")
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert DOMAIN not in hass.data
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    again = entry.runtime_data
    assert again is not manager
    assert [i["summary"] for i in again.issues.values()] == ["Keep me"]


async def test_entities_for_project_and_people(hass, entry):
    await setup(hass, entry)
    manager = entry.runtime_data
    manager.create_issue("HOME", "Overdue", due="2020-01-01", assignee="person.joachim")
    manager.create_issue("HOME", "Plain")
    await hass.async_block_till_done()

    state = hass.states.get("sensor.home_open_issues")
    assert state.state == "2"
    assert state.attributes["by_priority"] == {"medium": 2}
    assert hass.states.get("sensor.home_overdue").state == "1"
    assert hass.states.get("sensor.home_overdue").attributes["issues"][0]["summary"] == "Overdue"
    assert hass.states.get("sensor.home_unassigned").state == "1"
    assert hass.states.get("sensor.home_due_soon").state == "0"
    assert hass.states.get("sensor.home_last_activity").state not in ("unknown", "unavailable")
    assert hass.states.get("binary_sensor.home_has_overdue").state == "on"
    assert hass.states.get("sensor.homeboard_open_issues").state == "2"
    assert hass.states.get("sensor.homeboard_overdue_issues").state == "1"
    assert hass.states.get("sensor.homeboard_auto_generated_issues").state == "0"

    to_do = hass.states.get("sensor.home_to_do")
    assert to_do.state == "2"
    assert to_do.attributes["category"] == "todo"
    assert hass.states.get("sensor.home_done").state == "0"

    joachim = hass.states.get("sensor.homeboard_joachim_assigned")
    assert joachim.state == "1"
    assert joachim.attributes["overdue"] == 1
    assert hass.states.get("sensor.homeboard_padmaja_assigned").state == "0"
    assert hass.states.get("todo.home") is not None
    assert hass.states.get("calendar.home_due_dates") is not None


async def test_entities_follow_renames_and_removals(hass, entry):
    await setup(hass, entry)
    manager = entry.runtime_data
    registry = er.async_get(hass)
    devices = dr.async_get(hass)
    project = manager.resolve_project("HOME")
    status = manager.add_status("HOME", name="Waiting", category="in_progress")
    await hass.async_block_till_done()
    assert hass.states.get("sensor.home_waiting") is not None

    manager.update_status("HOME", status["id"], name="Blocked")
    await hass.async_block_till_done()
    assert hass.states.get("sensor.home_waiting").name == "Home Blocked"

    manager.remove_status("HOME", status["id"])
    await hass.async_block_till_done()
    assert (
        registry.async_get_entity_id("sensor", DOMAIN, f"{project['id']}_status_{status['id']}")
        is None
    )
    assert hass.states.get("sensor.home_waiting") is None

    # rename project -> device name follows, entity ids stay
    manager.update_project("HOME", name="House")
    await hass.async_block_till_done()
    device = devices.async_get_device_by_identifier((DOMAIN, project["id"]), entry.entry_id)
    assert device.name == "House"
    assert hass.states.get("sensor.home_open_issues") is not None

    # delete project -> its entities and its device disappear
    manager.delete_project("HOME")
    await hass.async_block_till_done()
    assert hass.states.get("sensor.home_open_issues") is None
    assert hass.states.get("todo.home") is None
    assert devices.async_get_device_by_identifier((DOMAIN, project["id"]), entry.entry_id) is None
    # global sensors and per-person sensors remain
    assert hass.states.get("sensor.homeboard_open_issues").state == "0"


async def test_new_project_and_new_person_get_entities(hass, entry):
    await setup(hass, entry)
    manager = entry.runtime_data
    manager.create_project(key="CAR", name="Car")
    hass.states.async_set("person.guest", "home", {"friendly_name": "Guest"})
    manager.create_issue("CAR", "Tyres")
    await hass.async_block_till_done()
    assert hass.states.get("sensor.car_open_issues").state == "1"
    assert hass.states.get("sensor.homeboard_guest_assigned") is not None


async def test_config_flow_creates_single_entry(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STARTER_PROJECT: False}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_STARTER_PROJECT: False}
    again = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert again["type"] is FlowResultType.ABORT
    assert again["reason"] == "single_instance_allowed"


async def test_options_flow_walks_three_pages_and_reloads(hass, entry):
    await setup(hass, entry)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert flow["step_id"] == "init"
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {
            "due_soon_hours": 24.0,
            "auto_archive_done_days": 0.0,
            "panel_title": "Tavle",
            "panel_icon": "mdi:home",
            "panel_admin_only": False,
        },
    )
    assert flow["step_id"] == "notifications"
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {
            "notify_services": ["mobile_app_phone"],
            "notify_done": True,
            "notify_overdue": False,
            "notify_due_soon": False,
            "notify_health": False,
        },
    )
    assert flow["step_id"] == "health"
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {
            "health_enabled": False,
            "health_unavailable": True,
            "health_battery": True,
            "health_integrations": True,
            "health_repairs": True,
            "health_updates": False,
            "health_unavailable_minutes": 30.0,
            "health_battery_threshold": 15.0,
            "health_snooze_days": 3.0,
            "health_max_open": 10.0,
        },
    )
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    options = dict(entry.options)
    assert options["due_soon_hours"] == 24 and isinstance(options["due_soon_hours"], int)
    assert options["auto_archive_done_days"] == 0
    assert options["notify_services"] == ["mobile_app_phone"]
    assert options["health_enabled"] is False
    assert "health_project" not in options  # blank optional fields are dropped
    # the entry was reloaded and picked the new options up
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.due_soon_hours == 24
    assert entry.runtime_data.settings()["panel_title"] == "Tavle"
    assert entry.runtime_data.health.enabled is False
