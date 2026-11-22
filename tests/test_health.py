"""Home health: detectors and the reconciler that fills the board by itself."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryDisabler, ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    async_capture_events,
    mock_integration,
)

from custom_components.homeboard import const, health

OLD = "2026-12-01 08:00:00+01:00"
NOW = "2026-12-01 12:00:00+01:00"


@pytest.fixture
def source(hass):
    """A fake integration whose devices we can break."""
    entry = MockConfigEntry(domain="fake", title="Fake Hub")
    entry.add_to_hass(hass)
    return entry


def make_device(hass, source, name, entities, area=None):
    """entities: [(domain, key, state, extra)] -> device id."""
    devices = dr.async_get(hass)
    entities_reg = er.async_get(hass)
    device = devices.async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("fake", name)}, name=name
    )
    if area:
        from homeassistant.helpers import area_registry as ar

        devices.async_update_device(device.id, area_id=ar.async_get(hass).async_create(area).id)
    for domain, key, state, extra in entities:
        extra = dict(extra)
        attrs = extra.pop("attrs", {})
        entry = entities_reg.async_get_or_create(
            domain,
            "fake",
            f"{name}-{key}",
            device_id=device.id,
            config_entry=source,
            suggested_object_id=f"{name}_{key}".lower().replace(" ", "_"),
            **extra,
        )
        hass.states.async_set(entry.entity_id, state, attrs)
    return device.id


def monitor(manager):
    mon = manager.health
    mon.grace_until = dt_util.utcnow() - timedelta(minutes=1)
    return mon


async def findings(manager, **options):
    manager.options = {**manager.options, **options}
    return await manager.health.async_collect()


# ------------------------------------------------------------------ offline detector


async def test_device_offline_after_threshold(hass, manager, source, freezer):
    freezer.move_to(OLD)
    make_device(
        hass,
        source,
        "Garage door",
        [
            ("binary_sensor", "contact", "unavailable", {"original_device_class": "garage_door"}),
            ("sensor", "battery", "unavailable", {}),
        ],
        area="Garage",
    )
    freezer.move_to("2026-12-01 08:30:00+01:00")
    assert await findings(manager) == []  # only 30 min
    freezer.move_to(NOW)
    [finding] = await findings(manager)
    assert finding.summary == "Garage door is offline"
    assert finding.key.startswith("health:offline:") and finding.detector == "offline"
    assert finding.priority == "high" and finding.labels == ["auto", "offline", "security"]
    assert "Fake Hub" in finding.description and "Garage" in finding.description
    assert "binary_sensor.garage_door_contact" in finding.description
    assert "Offline since 2026-12-01 08:00" in finding.description
    assert "ignore" in finding.description


async def test_offline_ignores_partial_hidden_disabled_diagnostic_restored_ghosts(
    hass, manager, source, freezer
):
    freezer.move_to(OLD)
    make_device(
        hass, source, "Partly", [("sensor", "a", "unavailable", {}), ("sensor", "b", "21", {})]
    )
    make_device(
        hass,
        source,
        "Hidden only",
        [("sensor", "a", "unavailable", {"hidden_by": er.RegistryEntryHider.USER})],
    )
    make_device(
        hass,
        source,
        "Disabled only",
        [("sensor", "a", "unavailable", {"disabled_by": er.RegistryEntryDisabler.USER})],
    )
    make_device(
        hass,
        source,
        "Diagnostic only",
        [("sensor", "a", "unavailable", {"entity_category": er.EntityCategory.DIAGNOSTIC})],
    )
    make_device(
        hass, source, "Restored", [("sensor", "a", "unavailable", {"attrs": {"restored": True}})]
    )
    ghost = make_device(hass, source, "Ghost", [("sensor", "a", "unavailable", {})])
    for registry_entry in er.async_entries_for_device(er.async_get(hass), ghost):
        hass.states.async_remove(registry_entry.entity_id)  # registry entry without a state
    make_device(hass, source, "Fine", [("sensor", "a", "1", {})])
    freezer.move_to(NOW)
    assert await findings(manager) == []


async def test_offline_exclusions_by_entity_and_integration(hass, manager, source, freezer):
    freezer.move_to(OLD)
    make_device(hass, source, "Noisy", [("sensor", "a", "unavailable", {})])
    freezer.move_to(NOW)
    assert len(await findings(manager)) == 1
    assert await findings(manager, health_exclude_entities=["sensor.noisy_a"]) == []
    assert (
        await findings(manager, health_exclude_entities=[], health_exclude_integrations=["FAKE"])
        == []
    )
    assert await findings(manager, health_unavailable=False, health_exclude_integrations=[]) == []


async def test_offline_threshold_option(hass, manager, source, freezer):
    freezer.move_to(OLD)
    make_device(hass, source, "Slow", [("sensor", "a", "unavailable", {})])
    freezer.move_to("2026-12-01 08:10:00+01:00")
    assert await findings(manager) == []
    assert len(await findings(manager, health_unavailable_minutes=5)) == 1


async def test_whole_integration_offline_is_one_issue(hass, manager, source, freezer):
    freezer.move_to(OLD)
    for name in ("Cam 1", "Cam 2"):
        make_device(hass, source, name, [("camera", "stream", "unavailable", {})])
    freezer.move_to(NOW)
    two = await findings(manager)
    assert len(two) == 2 and all(f.summary.endswith("is offline") for f in two)

    freezer.move_to(OLD)
    make_device(hass, source, "Cam 3", [("camera", "stream", "unavailable", {})])
    freezer.move_to(NOW)
    [grouped] = await findings(manager)
    assert grouped.summary == "Fake Hub: 3 devices are offline"
    assert grouped.key == f"health:offline_entry:{source.entry_id}" and grouped.priority == "high"
    assert "Cam 1" in grouped.description and "Cam 3" in grouped.description

    # ...and when the integration itself is broken that is the only finding
    source.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    [only] = await findings(manager)
    assert only.detector == "integration"


async def test_long_entity_lists_are_trimmed(hass, manager, source, freezer):
    freezer.move_to(OLD)
    entities = [("sensor", f"s{n}", "unavailable", {}) for n in range(14)]
    make_device(hass, source, "Many", entities)
    freezer.move_to(NOW)
    [finding] = await findings(manager)
    assert "and 4 more" in finding.description


# ------------------------------------------------------------------ battery detector


async def test_low_battery_grouped_per_device(hass, manager, source):
    make_device(
        hass,
        source,
        "Hallway motion",
        [
            (
                "sensor",
                "battery",
                "12",
                {"attrs": {"device_class": "battery", "unit_of_measurement": "%"}},
            ),
            ("binary_sensor", "motion", "off", {"original_device_class": "motion"}),
        ],
    )
    make_device(
        hass,
        source,
        "Remote",
        [("sensor", "battery", "85", {"attrs": {"device_class": "battery"}})],
    )
    make_device(
        hass,
        source,
        "Thermostat",
        [("binary_sensor", "battery_low", "on", {"attrs": {"device_class": "battery"}})],
    )
    make_device(
        hass,
        source,
        "Broken",
        [("sensor", "battery", "unknown", {"attrs": {"device_class": "battery"}})],
    )
    found = {f.summary: f for f in await findings(manager)}
    assert set(found) == {"Replace battery: Hallway motion", "Replace battery: Thermostat"}
    motion = found["Replace battery: Hallway motion"]
    assert motion.type == "task" and motion.priority == "high" and "security" in motion.labels
    assert "12 %" in motion.description
    assert found["Replace battery: Thermostat"].priority == "medium"


async def test_battery_threshold_hysteresis(hass, manager, source):
    make_device(
        hass, source, "Door", [("sensor", "battery", "22", {"attrs": {"device_class": "battery"}})]
    )
    assert await findings(manager) == []  # 22 % is above 20 %
    key = f"health:battery:{dr.async_get(hass).async_get_device_by_identifier(('fake', 'Door'), source.entry_id).id}"
    issue, _ = manager.create_issue("HOME", "Replace battery", dedupe_key=key, source="health")
    assert issue["dedupe_key"] == key
    # once an issue is open the battery must climb 5 points above the threshold
    assert len(await findings(manager)) == 1
    hass.states.async_set("sensor.door_battery", "30", {"device_class": "battery"})
    assert await findings(manager) == []
    assert await findings(manager, health_battery=False) == []


async def test_battery_without_device(hass, manager):
    er.async_get(hass).async_get_or_create(
        "sensor", "fake", "solo", suggested_object_id="solo_battery"
    )
    hass.states.async_set(
        "sensor.solo_battery", "5", {"device_class": "battery", "friendly_name": "Solo"}
    )
    [finding] = await findings(manager)
    assert finding.summary == "Replace battery: Solo"


# ------------------------------------------------------------------ integrations / repairs / updates


async def test_failing_integrations_and_reauth(hass, manager, monkeypatch):
    for domain in ("fake_tado", "fake_reolink", "fake_sun", "fake_old"):
        mock_integration(hass, MockModule(domain))
    bad = MockConfigEntry(domain="fake_tado", title="Tado X")
    bad.add_to_hass(hass)
    bad.mock_state(hass, ConfigEntryState.SETUP_ERROR, "bad credentials")
    retry = MockConfigEntry(domain="fake_reolink", title="Reolink hub")
    retry.add_to_hass(hass)
    retry.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    fine = MockConfigEntry(domain="fake_sun", title="Sun")
    fine.add_to_hass(hass)
    fine.mock_state(hass, ConfigEntryState.NOT_LOADED)
    off = MockConfigEntry(domain="fake_old", title="Old", disabled_by=ConfigEntryDisabler.USER)
    off.add_to_hass(hass)
    off.mock_state(hass, ConfigEntryState.NOT_LOADED)
    found = {f.summary: f for f in await findings(manager)}
    assert set(found) == {"Integration problem: Tado X", "Integration problem: Reolink hub"}
    assert "Reason: bad credentials" in found["Integration problem: Tado X"].description
    assert "cannot connect" in found["Integration problem: Reolink hub"].description

    real = hass.config_entries.flow.async_progress
    monkeypatch.setattr(
        hass.config_entries.flow,
        "async_progress",
        lambda *a, **k: [
            *real(*a, **k),
            {
                "flow_id": "f1",
                "handler": "fake_tado",
                "context": {"source": "reauth", "entry_id": bad.entry_id},
            },
        ],
    )
    again = {f.summary: f for f in await findings(manager)}
    assert "Sign in again: Tado X" in again and "Integration problem: Tado X" not in again
    assert again["Sign in again: Tado X"].priority == "high"
    assert await findings(manager, health_integrations=False) == []


async def test_repairs_become_findings(hass, manager):
    ir.async_create_issue(
        hass,
        "fake",
        "deprecated",
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="deprecated",
        learn_more_url="https://example.com/more",
    )
    ir.async_create_issue(
        hass,
        "fake",
        "minor",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="minor",
    )
    ir.async_create_issue(
        hass,
        "fake",
        "hidden",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="hidden",
    )
    ir.async_ignore_issue(hass, "fake", "hidden", True)
    ir.async_create_issue(
        hass,
        const.DOMAIN,
        "ours",
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="x",
    )
    found = {f.key: f for f in await findings(manager)}
    assert set(found) == {"health:repair:fake:deprecated", "health:repair:fake:minor"}
    assert found["health:repair:fake:deprecated"].priority == "high"
    assert found["health:repair:fake:minor"].priority == "medium"
    assert found["health:repair:fake:deprecated"].summary == "Repair: fake: deprecated"
    assert "https://example.com/more" in found["health:repair:fake:deprecated"].description
    assert await findings(manager, health_repairs=False) == []


async def test_repair_titles_use_translations(hass, manager, monkeypatch):
    async def fake_translations(hass_, language, category, integrations=None, config_flow=None):
        return {"component.fake.issues.deprecated.title": "Fake {thing} is going away"}

    monkeypatch.setattr(health, "async_get_translations", fake_translations)
    ir.async_create_issue(
        hass,
        "fake",
        "deprecated",
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="deprecated",
        translation_placeholders={"thing": "API"},
    )
    ir.async_create_issue(
        hass,
        "fake",
        "broken",
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="deprecated",
        translation_placeholders={"other": "x"},
    )
    summaries = sorted(f.summary for f in await findings(manager))
    assert summaries == ["Repair: Fake API is going away", "Repair: Fake {thing} is going away"]
    # (the second one lacks the placeholder, so the raw template is used)


async def test_updates_are_opt_in_and_grouped(hass, manager):
    hass.states.async_set(
        "update.core",
        "on",
        {"installed_version": "1", "latest_version": "2", "friendly_name": "Core"},
    )
    hass.states.async_set(
        "update.addon",
        "on",
        {"installed_version": "3", "latest_version": "4", "friendly_name": "Addon"},
    )
    hass.states.async_set("update.busy", "on", {"in_progress": True})
    hass.states.async_set("update.current", "off", {})
    assert await findings(manager) == []
    [finding] = await findings(manager, health_updates=True)
    assert (
        finding.summary == "2 updates available"
        and finding.priority == "low"
        and finding.type == "task"
    )
    assert "Core: 1 -> 2" in finding.description
    hass.states.async_remove("update.addon")
    [one] = await findings(manager)
    assert one.summary == "1 update available"


# ------------------------------------------------------------------ reconciling


async def broken_device(hass, source, freezer, name="Gate", battery=None):
    freezer.move_to(OLD)
    ents = [("sensor", "a", "unavailable", {})]
    make_device(hass, source, name, ents)
    freezer.move_to(NOW)


async def test_scan_waits_for_grace_and_debounce(hass, manager, source, freezer):
    await broken_device(hass, source, freezer)
    mon = manager.health
    mon.grace_until = dt_util.utcnow() + timedelta(minutes=10)
    assert (await mon.async_scan())["skipped"] == "startup_grace"
    mon.grace_until = dt_util.utcnow() - timedelta(minutes=1)
    first = await mon.async_scan()
    assert first["created"] == 0 and first["findings"][0]["action"] == "pending"
    assert [p["key"] for p in manager.projects.values()] == [
        "HOME",
        "FIX",
    ]  # FIX is created on demand
    second = await mon.async_scan()
    assert second["created"] == 1 and second["findings"][0]["action"] == "created"
    issue = next(i for i in manager.issues.values() if i["source"] == "health")
    assert issue["summary"] == "Gate is offline" and issue["type"] == "bug"
    assert issue["labels"] == ["auto", "offline"] and issue["dedupe_key"].startswith(
        "health:offline:"
    )
    assert manager.resolve_project("FIX")["name"] == "Smart home fixes"
    third = await mon.async_scan()  # nothing new, no duplicate
    assert third["created"] == 0 and len(manager.issues) == 1
    assert hass.states.get("sensor.homeboard_auto_generated_issues").state == "1"
    assert (
        hass.states.get("sensor.homeboard_auto_generated_issues").attributes["last_scan"]["created"]
        == 0
    )


async def test_disabled_scan_does_nothing(hass, manager, source, freezer):
    await broken_device(hass, source, freezer)
    mon = monitor(manager)
    manager.options = {"health_enabled": False}
    assert (await mon.async_scan())["skipped"] == "disabled"
    assert not manager.health.enabled


async def test_created_issue_uses_assignee_and_fires_event(hass, manager, source, freezer):
    await broken_device(hass, source, freezer)
    mon = monitor(manager)
    manager.options = {"health_assignee": "person.joachim"}
    events = async_capture_events(hass, const.EVENT_ISSUE_CREATED)
    await mon.async_scan()
    await mon.async_scan()
    await hass.async_block_till_done()
    assert events[0].data["source"] == "health" and events[0].data["assignee"] == "person.joachim"


async def test_issue_closes_itself_after_two_clean_scans_and_comes_back(
    hass, manager, source, freezer
):
    await broken_device(hass, source, freezer)
    mon = monitor(manager)
    await mon.async_scan()
    await mon.async_scan()
    issue = next(i for i in manager.issues.values() if i["source"] == "health")
    hass.states.async_set("sensor.gate_a", "5")
    one = await mon.async_scan()
    assert one["closed"] == 0 and manager.category(issue) != "done"
    two = await mon.async_scan()
    assert two["closed"] == 1 and manager.category(issue) == "done" and issue["auto_resolved"]
    assert "Resolved automatically" in issue["comments"][-1]["text"]
    assert two["findings"][-1]["action"] == "closed"

    # the fault returns: seen twice again, then the same issue is reopened
    hass.states.async_set("sensor.gate_a", "unavailable")
    freezer.tick(timedelta(minutes=61))
    assert (await mon.async_scan())["findings"][0]["action"] == "pending"
    assert (await mon.async_scan())["reopened"] == 1
    assert manager.category(issue) != "done" and not issue["auto_resolved"]
    assert issue["comments"][-1]["text"] == "Problem is back."


async def test_flapping_inside_the_cooldown_is_suppressed(hass, manager, source, freezer):
    await broken_device(hass, source, freezer)
    mon = monitor(manager)
    await mon.async_scan()
    await mon.async_scan()
    issue = next(i for i in manager.issues.values() if i["source"] == "health")
    manager.resolve_automatically(issue["id"], "gone")
    result = await mon.async_scan()
    assert result["suppressed"] == 1 and result["findings"][0]["action"] == "snoozed"
    assert manager.category(issue) == "done"


async def test_closing_by_hand_snoozes_for_a_week(hass, manager, source, freezer):
    await broken_device(hass, source, freezer)
    mon = monitor(manager)
    await mon.async_scan()
    await mon.async_scan()
    issue = next(i for i in manager.issues.values() if i["source"] == "health")
    manager.move_issue(issue["id"], "Done", actor="person.joachim", source="ui")
    assert not issue["auto_resolved"]
    freezer.tick(timedelta(days=3))
    hass.states.async_set("sensor.gate_a", "unavailable")
    assert (await mon.async_scan())["findings"][0]["action"] == "snoozed"
    freezer.tick(timedelta(days=5))
    hass.states.async_set("sensor.gate_a", "unavailable")
    after = await mon.async_scan()  # the fault kept being seen, so no new debounce is needed
    assert after["reopened"] == 1 and manager.category(issue) != "done"
    assert not any(i is not issue and i["source"] == "health" for i in manager.issues.values())


async def test_ignore_label_silences_a_fault_for_good(hass, manager, source, freezer):
    await broken_device(hass, source, freezer)
    mon = monitor(manager)
    await mon.async_scan()
    await mon.async_scan()
    issue = next(i for i in manager.issues.values() if i["source"] == "health")
    manager.update_issue(issue["id"], labels=[*issue["labels"], "ignore"])
    manager.move_issue(issue["id"], "Done")
    freezer.tick(timedelta(days=60))
    manager.async_tick()
    hass.states.async_set("sensor.gate_a", "unavailable")
    result = await mon.async_scan()
    assert result["suppressed"] == 1 and result["findings"][0]["action"] == "ignored"
    manager.update_issue(issue["id"], archived=True)
    assert (await mon.async_scan())["suppressed"] == 1  # archived ones still count


async def test_description_refreshes_only_when_the_affected_set_changes(
    hass, manager, source, freezer
):
    await broken_device(hass, source, freezer)
    mon = monitor(manager)
    await mon.async_scan()
    await mon.async_scan()
    issue = next(i for i in manager.issues.values() if i["source"] == "health")
    before = issue["description"]
    entities = er.async_get(hass)
    dev = dr.async_get(hass).async_get_device_by_identifier(("fake", "Gate"), source.entry_id)
    entities.async_get_or_create(
        "sensor",
        "fake",
        "Gate-b",
        device_id=dev.id,
        config_entry=source,
        suggested_object_id="gate_b",
    )
    freezer.move_to(OLD)
    hass.states.async_set("sensor.gate_b", "unavailable")
    freezer.move_to(NOW)
    await mon.async_scan()
    assert issue["description"] != before and "sensor.gate_b" in issue["description"]
    updated = issue["updated"]
    freezer.tick(timedelta(minutes=10))
    await mon.async_scan()
    assert issue["updated"] == updated  # nothing changed, nothing written


async def test_cap_keeps_the_most_important_issues(hass, manager, source, freezer):
    freezer.move_to(OLD)
    make_device(hass, source, "Lamp", [("sensor", "a", "unavailable", {})])
    make_device(
        hass,
        source,
        "Front door",
        [("binary_sensor", "c", "unavailable", {"original_device_class": "door"})],
    )
    freezer.move_to(NOW)
    mon = monitor(manager)
    manager.options = {"health_max_open": 1}
    await mon.async_scan()
    result = await mon.async_scan()
    assert result["created"] == 1 and result["suppressed"] == 1
    [issue] = [i for i in manager.issues.values() if i["source"] == "health"]
    assert issue["summary"] == "Front door is offline"  # the security device wins
    assert {f["action"] for f in result["findings"]} == {"created", "capped"}


async def test_manual_scan_acts_immediately_and_dry_run_changes_nothing(
    hass, manager, source, freezer
):
    await broken_device(hass, source, freezer)
    dry = await manager.health.async_scan(dry_run=True)
    assert dry["created"] == 0 and dry["findings"][0]["action"] == "would_create"
    assert [p["key"] for p in manager.projects.values()] == ["HOME"]  # not even the project
    assert manager.issues == {}
    real = await manager.health.async_scan(force=True)
    assert real["created"] == 1 and real["findings"][0]["action"] == "created"
    hass.states.async_set("sensor.gate_a", "5")
    dry_close = await manager.health.async_scan(dry_run=True)
    assert dry_close["findings"][-1]["action"] == "would_close"
    forced = await manager.health.async_scan(force=True)
    assert forced["closed"] == 1


async def test_dry_run_reports_reopen_and_unknown_project(hass, manager, source, freezer):
    await broken_device(hass, source, freezer)
    await manager.health.async_scan(force=True)
    issue = next(i for i in manager.issues.values() if i["source"] == "health")
    manager.resolve_automatically(issue["id"], "gone")
    freezer.tick(timedelta(hours=2))
    dry = await manager.health.async_scan(dry_run=True)
    assert dry["findings"][0]["action"] == "would_reopen"
    manager.options = {"health_project": "NOPE"}
    nothing = await manager.health.async_scan(force=True)
    assert nothing["created"] == 0 and nothing["findings"][0]["action"] == "no_project"


async def test_custom_project_option(hass, manager, source, freezer):
    await broken_device(hass, source, freezer)
    manager.options = {"health_project": "home"}
    await manager.health.async_scan(force=True)
    [issue] = [i for i in manager.issues.values() if i["source"] == "health"]
    assert issue["project_id"] == manager.resolve_project("HOME")["id"]


async def test_service_and_websocket_trigger_a_scan(hass, manager, source, freezer, hass_ws_client):
    client = await hass_ws_client(hass)  # authenticate before the clock moves
    await broken_device(hass, source, freezer)
    dry = await hass.services.async_call(
        const.DOMAIN, "scan_health", {"dry_run": True}, blocking=True, return_response=True
    )
    assert dry["findings"][0]["action"] == "would_create"
    await client.send_json_auto_id({"type": "homeboard/health/scan"})
    reply = await client.receive_json()
    assert reply["success"] and reply["result"]["created"] == 1
    again = await hass.services.async_call(
        const.DOMAIN, "scan_health", {}, blocking=True, return_response=True
    )
    assert again["created"] == 0


async def test_monitor_starts_after_ha_started_and_runs_on_a_timer(hass, manager, source, freezer):
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    await broken_device(hass, source, freezer)
    mon = manager.health
    mon.async_stop()
    mon.async_start()  # HA is already running, so the grace period starts now
    await hass.async_block_till_done()
    assert mon.grace_until is not None
    freezer.tick(timedelta(minutes=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=5))
    freezer.tick(timedelta(minutes=5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert any(i["source"] == "health" for i in manager.issues.values())
