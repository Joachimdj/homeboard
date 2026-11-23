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


def make_device(hass, source, name, entities, area=None, platform="fake"):
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
            platform,
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


# ------------------------------------------------------------------ 0.2.1: less noise


def _battery(level="12", **extra):
    return ("sensor", "battery", level, {"attrs": {"device_class": "battery"}, **extra})


async def test_ordinary_batteries_share_one_issue_security_ones_do_not(hass, manager, source):
    make_device(
        hass,
        source,
        "Smoke alarm",
        [_battery("9"), ("binary_sensor", "smoke", "off", {"original_device_class": "smoke"})],
    )
    for name, level in (("Kitchen switch", "15"), ("Palm", "4"), ("Office remote", "18")):
        make_device(
            hass,
            source,
            name,
            [_battery(level)],
            area="Office" if name == "Office remote" else None,
        )
    found = {f.key: f for f in await findings(manager)}
    group = found[health.BATTERY_GROUP_KEY]
    assert group.summary == "3 batteries are running low" and group.priority == "medium"
    assert group.labels == ["auto", "battery"] and group.type == "task"
    # lowest first, with the area when there is one
    assert [line.lstrip("- ") for line in group.description.splitlines()[:3]] == [
        "Palm: 4 %",
        "Kitchen switch: 15 %",
        "Office remote (Office): 18 %",
    ]
    [smoke] = [f for k, f in found.items() if k != health.BATTERY_GROUP_KEY]
    assert smoke.summary == "Replace battery: Smoke alarm" and smoke.priority == "high"
    assert "security" in smoke.labels and len(found) == 2


async def test_battery_group_title_follows_the_count_and_keeps_its_hysteresis(
    hass, manager, source, freezer
):
    make_device(hass, source, "Palm", [_battery("12")])
    mon = monitor(manager)
    await mon.async_scan(force=True)
    [issue] = [i for i in manager.issues.values() if i["source"] == "health"]
    assert issue["summary"] == "Replace battery: Palm"
    make_device(hass, source, "Ficus", [_battery("8")])
    await mon.async_scan(force=True)
    assert (
        issue["summary"] == "2 batteries are running low" and "Ficus: 8 %" in issue["description"]
    )
    # a battery at 22 % stays listed once it is in the group (threshold 20 + 5), 26 % leaves it
    hass.states.async_set("sensor.palm_battery", "22", {"device_class": "battery"})
    await mon.async_scan(force=True)
    assert "Palm" in issue["description"]
    hass.states.async_set("sensor.palm_battery", "26", {"device_class": "battery"})
    await mon.async_scan(force=True)
    assert issue["summary"] == "Replace battery: Ficus" and "Palm" not in issue["description"]
    assert len([i for i in manager.issues.values() if i["source"] == "health"]) == 1


async def test_rechargeable_devices_are_not_a_battery_replacement(hass, manager, source):
    make_device(hass, source, "Mower", [_battery("5"), ("lawn_mower", "m", "docked", {})])
    make_device(hass, source, "Vac", [_battery("5"), ("vacuum", "v", "docked", {})])
    make_device(
        hass,
        source,
        "Tablet",
        [_battery("5")],
        platform="mobile_app",
    )
    make_device(
        hass,
        source,
        "Scooter",
        [
            _battery("5"),
            ("binary_sensor", "chg", "off", {"attrs": {"device_class": "battery_charging"}}),
        ],
    )
    assert await findings(manager) == []
    got = await findings(manager, health_noisy_devices=True)
    assert [f.summary for f in got] == ["4 batteries are running low"]


async def test_normally_off_devices_are_not_reported_offline(hass, manager, source, freezer):
    freezer.move_to(OLD)
    make_device(
        hass,
        source,
        "Telly",
        [("media_player", "tv", "unavailable", {}), ("remote", "r", "unavailable", {})],
    )
    make_device(hass, source, "Bulb", [("light", "l", "unavailable", {})])
    make_device(
        hass, source, "Browser", [("camera", "c", "unavailable", {})], platform="browser_mod"
    )
    make_device(hass, source, "Plug", [("switch", "s", "unavailable", {})])
    make_device(
        hass,
        source,
        "Lamp and fan",
        [("light", "l", "unavailable", {}), ("fan", "f", "unavailable", {})],
    )
    freezer.move_to(NOW)
    got = await findings(manager)
    assert sorted(f.summary for f in got) == ["Lamp and fan is offline", "Plug is offline"]
    everything = await findings(manager, health_noisy_devices=True)
    assert [f.summary for f in everything] == ["Fake Hub: 5 devices are offline"]


async def test_offline_group_title_follows_the_count(hass, manager, source, freezer):
    freezer.move_to(OLD)
    for name in ("Cam 1", "Cam 2", "Cam 3"):
        make_device(hass, source, name, [("camera", "stream", "unavailable", {})])
    freezer.move_to(NOW)
    mon = monitor(manager)
    await mon.async_scan(force=True)
    [issue] = [i for i in manager.issues.values() if i["source"] == "health"]
    assert issue["summary"] == "Fake Hub: 3 devices are offline"
    freezer.move_to(OLD)
    make_device(hass, source, "Cam 4", [("camera", "stream", "unavailable", {})])
    freezer.move_to(NOW)
    await mon.async_scan(force=True)
    assert issue["summary"] == "Fake Hub: 4 devices are offline" and "Cam 4" in issue["description"]


def test_default_cap_is_lower_than_before():
    assert const.DEFAULT_HEALTH_MAX_OPEN == 15


# ------------------------------------------------------------------ 0.2.1: first-scan review


def _health_issues(manager):
    return [i for i in manager.issues.values() if i["source"] == "health"]


async def test_first_scan_only_creates_one_review_issue(hass, fresh_manager, source, freezer):
    manager = fresh_manager
    await broken_device(hass, source, freezer, "Gate")
    await broken_device(hass, source, freezer, "Barn")
    mon = monitor(manager)
    first = await mon.async_scan()
    assert first["skipped"] == "awaiting_review" and first["created"] == 0
    assert {f["action"] for f in first["findings"]} == {"held"}
    [review] = _health_issues(manager)
    assert review["dedupe_key"] == const.HEALTH_REVIEW_KEY
    assert review["summary"] == "Review: Homeboard found 2 things to fix"
    assert review["labels"] == ["auto", "review"]
    assert (
        "Gate is offline" in review["description"] and "close this issue" in review["description"]
    )
    assert not manager.health_state.get("reviewed") and mon.awaiting_review
    assert hass.states.get("sensor.homeboard_auto_generated_issues").attributes["awaiting_review"]

    # nothing piles up while it waits, and the list refreshes when the findings change
    again = await mon.async_scan()
    assert again["skipped"] == "awaiting_review" and len(_health_issues(manager)) == 1
    await broken_device(hass, source, freezer, "Shed")
    await mon.async_scan()
    # three devices of one integration become a single finding
    assert review["summary"] == "Review: Homeboard found 1 thing to fix"
    assert "Fake Hub: 3 devices are offline" in review["description"]
    updated = review["updated"]
    await mon.async_scan()
    assert review["updated"] == updated  # unchanged list, nothing written


async def test_closing_the_review_lets_the_scanner_go_ahead(hass, fresh_manager, source, freezer):
    manager = fresh_manager
    await broken_device(hass, source, freezer, "Gate")
    mon = monitor(manager)
    await mon.async_scan()
    [review] = _health_issues(manager)
    manager.move_issue(review["id"], "Done", actor="person.joachim", source="ui")
    result = await mon.async_scan()
    assert result["created"] == 1 and "skipped" not in result
    assert manager.health_state["reviewed"] and not mon.awaiting_review
    assert manager.health_state.get("review_issue") is None
    gate = next(i for i in _health_issues(manager) if i["dedupe_key"].startswith("health:"))
    assert gate["summary"] == "Gate is offline"
    assert manager._as_dict()["health"]["reviewed"] is True  # it is persisted


async def test_deleting_the_review_counts_as_a_yes(hass, fresh_manager, source, freezer):
    manager = fresh_manager
    await broken_device(hass, source, freezer, "Gate")
    mon = monitor(manager)
    await mon.async_scan()
    [review] = _health_issues(manager)
    manager.delete_issue(review["id"])
    assert (await mon.async_scan())["created"] == 1 and manager.health_state["reviewed"]


async def test_a_manual_scan_goes_ahead_and_closes_the_review(hass, fresh_manager, source, freezer):
    manager = fresh_manager
    await broken_device(hass, source, freezer, "Gate")
    mon = monitor(manager)
    await mon.async_scan()
    [review] = _health_issues(manager)
    manual = await mon.async_scan(force=True)
    assert manual["created"] == 1 and manager.category(review) == "done"
    assert review["auto_resolved"] and "manual scan" in review["comments"][-1]["text"]


async def test_dry_run_does_not_touch_the_review(hass, fresh_manager, source, freezer):
    manager = fresh_manager
    await broken_device(hass, source, freezer, "Gate")
    dry = await manager.health.async_scan(dry_run=True)
    assert dry["findings"][0]["action"] == "would_create" and manager.issues == {}
    assert not manager.health_state


async def test_nothing_found_or_older_install_needs_no_review(hass, fresh_manager, source, freezer):
    manager = fresh_manager
    mon = monitor(manager)
    assert (await mon.async_scan())["created"] == 0 and manager.health_state["reviewed"]
    assert _health_issues(manager) == []

    # a board that already has auto issues (installed before 0.2.1) is not held back
    manager.health_state.clear()
    manager.create_issue("HOME", "old one", dedupe_key="health:offline:x", source="health")
    await broken_device(hass, source, freezer, "Gate")
    result = await mon.async_scan()
    assert "skipped" not in result and manager.health_state["reviewed"]


async def test_upgrade_from_0_2_0_swaps_per_device_battery_issues_for_the_group(
    hass, fresh_manager, source, freezer
):
    """The board of a 0.2.0 install: many per-device battery issues, no review wanted."""
    manager = fresh_manager
    monitor(manager)._project(create=True)  # the FIX project of the old install
    for name in ("Kitchen switch", "Palm", "Office remote"):
        device_id = make_device(hass, source, name, [_battery("10")])
        manager.create_issue(
            "FIX",
            f"Replace battery: {name}",
            dedupe_key=f"health:battery:{device_id}",
            source="health",
            labels=["auto", "battery"],
        )
    mon = monitor(manager)
    first = await mon.async_scan()
    assert first["created"] == 0 and first["closed"] == 0 and manager.health_state["reviewed"]
    second = await mon.async_scan()
    assert second["created"] == 1 and second["closed"] == 3
    open_now = [i for i in _health_issues(manager) if manager.category(i) != "done"]
    assert [i["summary"] for i in open_now] == ["3 batteries are running low"]
    assert all(i["auto_resolved"] for i in _health_issues(manager) if manager.category(i) == "done")


async def test_review_without_its_project_waits_quietly(hass, fresh_manager, source, freezer):
    manager = fresh_manager
    await broken_device(hass, source, freezer, "Gate")
    manager.options = {"health_project": "NOPE"}
    result = await monitor(manager).async_scan()
    assert result["skipped"] == "awaiting_review" and _health_issues(manager) == []


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

    # the fault returns: seen twice again, then the same issue is reopened. The gate has been
    # gone for 4 hours before, so Homeboard waits 1.5 x that before it counts as a fault again.
    hass.states.async_set("sensor.gate_a", "unavailable")
    freezer.tick(timedelta(minutes=61))
    assert (await mon.async_scan())["findings"] == []
    freezer.tick(timedelta(hours=6))
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


# ------------------------------------------------------------------ patience (devices that come back)


async def test_a_device_that_came_back_by_itself_is_reported_later_next_time(
    hass, manager, source, freezer
):
    await broken_device(hass, source, freezer)  # gone since 08:00, now 12:00
    mon = monitor(manager)
    await mon.async_scan()
    await mon.async_scan()
    issue = next(i for i in manager.issues.values() if i["source"] == "health")
    key = issue["dedupe_key"]
    assert manager.learning.patience(key) == 0
    hass.states.async_set("sensor.gate_a", "5")
    await mon.async_scan()
    assert (await mon.async_scan())["closed"] == 1
    assert manager.learning.patience(key) == 360  # 1.5 x the 4 hours it was gone

    hass.states.async_set("sensor.gate_a", "unavailable")  # gone again at 12:00
    freezer.tick(timedelta(hours=3))
    assert await findings(manager) == []  # 3 h is past the normal hour, but not past 6 h
    [held] = mon.waiting
    assert held["key"] == key and held["waited_minutes"] == 180
    assert held["reported_after_minutes"] == 360 and held["summary"] == "Gate is offline"
    result = await mon.async_scan(dry_run=True)
    assert result["findings"] == [] and result["waiting"] == [held]
    freezer.tick(timedelta(hours=3, minutes=1))
    [again] = await findings(manager)
    assert again.key == key and not mon.waiting


async def test_patience_ignores_learning_switched_off_and_is_capped(manager):
    learning = manager.learning
    key = "health:offline:abc"
    assert learning.record_self_healed(key, 600) and learning.patience(key) == 900
    assert (
        learning.record_self_healed(key, 60) and learning.patience(key) == 900
    )  # keeps the longest
    assert learning.record_self_healed(key, 2 * 24 * 60)
    assert learning.patience(key) == 3 * 24 * 60  # 1.5 x 48 h, capped at 3 days
    assert not learning.record_self_healed("health:offline:long", 2 * 24 * 60 + 1)
    assert not learning.record_self_healed("health:offline:tiny", 0.5)
    assert learning.patience("health:offline:long") == 0
    manager.options = {**manager.options, "learn_health": False}
    assert learning.patience(key) == 0 and not learning.record_self_healed("health:x:y", 100)
    manager.options = {**manager.options, "learn_health": True}
    assert learning.patience(key) == 3 * 24 * 60  # nothing was thrown away


async def test_forgetting_health_knowledge_removes_the_patience(manager):
    manager.learning.record_self_healed("health:offline:abc", 300)
    assert manager.learning.insights()["learned"]["health"]["patient"] == 1
    manager.learning.forget("health")
    assert manager.learning.patience("health:offline:abc") == 0


async def test_old_patience_is_forgotten(manager, freezer):
    freezer.move_to(OLD)
    manager.learning.record_self_healed("health:offline:old", 300)
    freezer.tick(timedelta(days=const.HEALTH_PATIENCE_KEEP_DAYS + 1))
    manager.learning.record_self_healed("health:offline:new", 300)
    assert manager.learning.patience("health:offline:old") == 0
    assert manager.learning.patience("health:offline:new") == 450


async def test_cards_that_closed_themselves_before_teach_patience_once(
    hass, manager, source, freezer
):
    freezer.move_to("2026-12-01 08:00:00+01:00")
    project = manager.create_project(key="FIX", name="Fixes")
    old = []
    for key in ("health:offline:aaa", "health:silent:bbb", "health:battery:ccc"):
        issue, _ = manager.create_issue(
            project["id"], key, dedupe_key=key, source="health", labels=["auto"]
        )
        old.append(issue)
    freezer.tick(timedelta(hours=2))
    for issue in old:
        manager.resolve_automatically(issue["id"], "gone")
    manual, _ = manager.create_issue(
        project["id"], "by hand", dedupe_key="health:offline:ddd", source="health"
    )
    manager.move_issue(manual["id"], "Done")  # a person closed it: not a device that heals itself
    mon = monitor(manager)
    await mon.async_scan()
    learning = manager.learning
    assert learning.patience("health:offline:aaa") == 270  # (2 h + the 60 min wait) x 1.5
    assert learning.patience("health:silent:bbb") == 450  # (2 h + the 180 min floor) x 1.5
    assert (
        learning.patience("health:battery:ccc") == 0
        and learning.patience("health:offline:ddd") == 0
    )
    assert manager.health_state["patience_seeded"] is True
    await mon.async_scan()
    assert learning.data["health"]["patience"]["health:offline:aaa"]["n"] == 1  # only once


async def test_devices_held_back_do_not_make_an_integration_group(hass, manager, source, freezer):
    freezer.move_to(OLD)
    ids = {
        name: make_device(hass, source, name, [("sensor", "a", "unavailable", {})])
        for name in ("Cam 1", "Cam 2", "Cam 3")
    }
    freezer.move_to(NOW)
    [group] = await findings(manager)
    assert group.summary == "Fake Hub: 3 devices are offline"
    manager.learning.record_self_healed(
        f"health:offline:{ids['Cam 3']}", 300
    )  # it comes back daily
    got = await findings(manager)
    assert sorted(f.summary for f in got) == ["Cam 1 is offline", "Cam 2 is offline"]
    assert [w["summary"] for w in manager.health.waiting] == ["Cam 3 is offline"]
