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


async def open_section(hass, entry, section):
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert flow["type"] is FlowResultType.MENU and flow["step_id"] == "init"
    assert set(flow["menu_options"]) == {
        "general",
        "alerts",
        "people",
        "files",
        "health",
        "learning",
    }
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": section}
    )
    assert flow["type"] is FlowResultType.FORM and flow["step_id"] == section
    return flow


async def test_options_general_section_saves_and_reloads(hass, entry):
    await setup(hass, entry)
    flow = await open_section(hass, entry, "general")
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {
            "due_soon_hours": 24.0,
            "auto_archive_done_days": 0.0,
            "checklist_autodone": True,
            "panel_title": "Tavle",
            "panel_icon": "mdi:home",
            "panel_admin_only": False,
            "tracked_people": ["person.padmaja"],
        },
    )
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    options = dict(entry.options)
    assert options["due_soon_hours"] == 24 and isinstance(options["due_soon_hours"], int)
    assert options["checklist_autodone"] is True and options["tracked_people"] == ["person.padmaja"]
    assert entry.state is ConfigEntryState.LOADED  # reloaded with the new options
    assert (
        entry.runtime_data.due_soon_hours == 24
        and entry.runtime_data.settings()["panel_title"] == "Tavle"
    )
    # another section keeps what the first one saved and drops blanks
    flow = await open_section(hass, entry, "alerts")
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
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    assert (
        entry.options["notify_services"] == ["mobile_app_phone"]
        and entry.options["due_soon_hours"] == 24
    )


async def test_options_people_section_walks_through_each_person(hass, entry):
    await setup(hass, entry)
    hass.services.async_register("notify", "mobile_app_joachim_phone", lambda call: None)
    flow = await open_section(hass, entry, "people")
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {
            "push_assigned": True,
            "push_comment": False,
            "push_overdue": True,
            "push_reported_done": True,
            "digest_enabled": True,
            "digest_time": "07:45",
            "quiet_start": "22:30",
            "quiet_end": "06:30",
        },
    )
    assert flow["step_id"] == "person" and flow["description_placeholders"] == {"person": "Joachim"}
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"notify_service": "notify.mobile_app_joachim_phone"}
    )
    assert flow["step_id"] == "person" and flow["description_placeholders"] == {"person": "Padmaja"}
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {}
    )  # auto-detect for her
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options["person_notify"] == {"person.joachim": ["mobile_app_joachim_phone"]}
    assert entry.options["push_comment"] is False and entry.options["digest_time"] == "07:45"
    assert entry.runtime_data.push.services_for("person.joachim") == ["mobile_app_joachim_phone"]
    # clearing the last mapping removes the key again
    flow = await open_section(hass, entry, "people")
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"push_assigned": True}
    )
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {})
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {})
    assert flow["type"] is FlowResultType.CREATE_ENTRY and "person_notify" not in entry.options


async def test_options_files_learning_and_health_sections(hass, entry):
    await setup(hass, entry)
    flow = await open_section(hass, entry, "files")
    await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {"attachments_enabled": False, "max_upload_mb": 5.0, "assist_sentences": True},
    )
    await hass.async_block_till_done()
    assert entry.options["max_upload_mb"] == 5 and entry.options["assist_sentences"] is True
    assert entry.runtime_data.settings()["attachments"] == {"enabled": False, "max_mb": 5}

    flow = await open_section(hass, entry, "learning")
    await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {
            "learn_defaults": True,
            "learn_patterns": False,
            "learn_workload": True,
            "learn_health": True,
            "learn_rhythm": True,
        },
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.settings()["learning"] == {
        "defaults": True,
        "patterns": False,
        "workload": True,
        "health": True,
        "rhythm": True,
    }

    flow = await open_section(hass, entry, "health")
    await hass.config_entries.options.async_configure(
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
    await hass.async_block_till_done()
    assert entry.options["health_enabled"] is False and "health_project" not in entry.options
    assert entry.runtime_data.health.enabled is False
    assert entry.options["max_upload_mb"] == 5  # earlier sections survive
