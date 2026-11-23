"""The learning engine: smart defaults, patterns, health learning, rhythm, insights page."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.homeboard import const
from custom_components.homeboard.model import InvalidError, NotFoundError

from .conftest import setup


def weekly_bags(manager, count=4, assignee="person.padmaja"):
    """Create the same chore every week for ``count`` weeks, the last one two days ago."""
    now = dt_util.utcnow()
    for week in range(count):
        issue, _ = manager.create_issue(
            "HOME", "Order new bin bags", assignee=assignee, labels=["home"], priority="low"
        )
        created = now - timedelta(days=2 + 7 * (count - 1 - week))
        issue["created"] = created.isoformat(timespec="seconds")
        manager.move_issue(issue["id"], "Done")


# ------------------------------------------------------------------ smart defaults


async def test_smart_defaults_fill_what_the_text_left_open(hass, manager, freezer):
    freezer.move_to("2026-12-01 10:00:00+01:00")
    for _ in range(3):
        issue, _ = manager.create_issue(
            "HOME",
            "Pay electricity bill",
            assignee="person.padmaja",
            labels=["bills"],
            priority="high",
            due="2026-12-04",
        )
        manager.move_issue(issue["id"], "Done")
    freezer.move_to("2026-12-10 10:00:00+01:00")
    created, _parsed = manager.quick_add("pay the electricity bill", suggest=True)
    assert (
        created["assignee"] == "person.padmaja"
        and created["labels"] == ["bills"]
        and created["priority"] == "high"
    )
    assert created["due"] == "2026-12-13"  # three days after "today", learned from 3 earlier issues
    explicit, _ = manager.quick_add(
        "pay electricity bill @joachim !low #car due 2031-01-01", suggest=True
    )
    assert (explicit["assignee"], explicit["priority"], explicit["due"]) == (
        "person.joachim",
        "low",
        "2031-01-01",
    )
    assert explicit["labels"] == [
        "car"
    ]  # anything the text sets is final: no suggestion for that field
    plain, _ = manager.quick_add("pay electricity bill", suggest=False)
    assert plain["assignee"] is None and plain["labels"] == []  # off unless asked for


async def test_defaults_off_means_no_suggestion(hass, manager):
    manager.options = {"learn_defaults": False}
    for _ in range(3):
        manager.create_issue("HOME", "Pay electricity bill", assignee="person.padmaja")
    parsed = manager.parse_quick_add("pay electricity bill")
    assert manager.suggestion_for(parsed) is None
    issue, _ = manager.quick_add("pay electricity bill", suggest=True)
    assert issue["assignee"] is None


async def test_suggest_websocket_and_service(hass, manager, hass_ws_client):
    for _ in range(2):
        manager.create_issue(
            "HOME", "Buy light bulbs", assignee="person.joachim", labels=["shopping"]
        )
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "homeboard/quick_add/preview", "text": "buy light bulbs due friday"}
    )
    preview = (await client.receive_json())["result"]
    assert (
        preview["summary"] == "buy light bulbs"
        and preview["suggestion"]["assignee"] == "person.joachim"
    )
    assert "due" not in preview["suggestion"] or preview["suggestion"]["due_in_days"] is None
    await client.send_json_auto_id({"type": "homeboard/suggest", "text": "something new"})
    assert (await client.receive_json())["result"] is None
    await client.send_json_auto_id({"type": "homeboard/suggest", "text": "buy light bulbs"})
    assert (await client.receive_json())["result"]["labels"] == ["shopping"]
    result = await hass.services.async_call(
        const.DOMAIN, "suggest", {"text": "buy light bulbs"}, blocking=True, return_response=True
    )
    assert result["suggestion"]["assignee"] == "person.joachim"
    added = await hass.services.async_call(
        const.DOMAIN,
        "quick_add",
        {"text": "buy light bulbs", "suggest": True},
        blocking=True,
        return_response=True,
    )
    assert manager.issues[added["id"]]["assignee"] == "person.joachim"
    await client.send_json_auto_id(
        {"type": "homeboard/quick_add", "text": "buy light bulbs", "suggest": True}
    )
    assert (await client.receive_json())["result"]["issue"]["labels"] == ["shopping"]


# ------------------------------------------------------------------ patterns


async def test_pattern_becomes_a_suggestion_that_can_be_accepted(hass, manager):
    weekly_bags(manager)
    manager.learning.refresh()
    [suggestion] = manager.learning.insights()["suggestions"]
    assert suggestion["kind"] == "recurring" and suggestion["evidence"]["count"] == 4
    assert manager.settings()["insights_open"] == 1
    assert hass.states.get("sensor.homeboard_suggestions").state == "1"
    assert (
        hass.states.get("sensor.homeboard_suggestions").attributes["suggestions"][0]["id"]
        == suggestion["id"]
    )

    result = manager.learning.accept(suggestion["id"])
    rec = manager.recurring[result["recurring_id"]]
    assert (
        rec["summary"] == "Order new bin bags"
        and rec["assignee"] == "person.padmaja"
        and rec["repeat"]["unit"] == "week"
    )
    assert manager.learning.open_count() == 0 and manager.settings()["insights_open"] == 0
    with pytest.raises(NotFoundError):
        manager.learning.accept(suggestion["id"])


async def test_dismissed_and_already_recurring_patterns_stay_away(hass, manager):
    weekly_bags(manager)
    manager.learning.refresh()
    [suggestion] = manager.learning.insights()["suggestions"]
    manager.learning.dismiss(suggestion["id"])
    manager.learning.refresh()
    assert manager.learning.open_count() == 0
    with pytest.raises(NotFoundError):
        manager.learning.dismiss(suggestion["id"])
    # forgetting dismissals brings it back
    assert manager.learning.forget("patterns") == ["dismissed suggestions"]
    assert manager.learning.open_count() == 1
    manager.create_recurring(
        "HOME", summary="Order bin bags", repeat={"unit": "week"}, next_due="2099-01-01"
    )
    manager.learning.refresh()
    assert manager.learning.open_count() == 0  # a similar chore already exists


async def test_pattern_feature_off(hass, manager):
    weekly_bags(manager)
    manager.options = {"learn_patterns": False}
    manager.learning.refresh()
    assert (
        manager.learning.open_count() == 0
        and "patterns" not in manager.learning.insights()["learned"]
    )


# ------------------------------------------------------------------ health learning


@pytest.fixture
def broken(hass):
    source = MockConfigEntry(domain="fake", title="Fake Hub")
    source.add_to_hass(hass)
    return source


def make_sensor(hass, source, name, state="20", **attrs):
    devices, entities = dr.async_get(hass), er.async_get(hass)
    device = devices.async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("fake", name)}, name=name
    )
    entry = entities.async_get_or_create(
        "sensor",
        "fake",
        f"{name}-t",
        device_id=device.id,
        config_entry=source,
        suggested_object_id=f"{name}_temp",
    )
    hass.states.async_set(
        entry.entity_id,
        state,
        {"state_class": "measurement", "device_class": "temperature", **attrs},
    )
    return device.id, entry.entity_id


async def test_sensor_rhythm_is_learned_and_silence_becomes_a_health_issue(
    hass, manager, broken, freezer
):
    freezer.move_to("2026-12-01 08:00:00+01:00")
    device_id, entity_id = make_sensor(hass, broken, "Garage")
    manager.learning.sample()
    for step in range(1, 16):  # reports every 15 minutes
        freezer.tick(timedelta(minutes=15))
        hass.states.async_set(
            entity_id,
            str(20 + step % 3),
            {"state_class": "measurement", "device_class": "temperature"},
        )
        manager.learning.sample()
    stat = manager.learning_data["health"]["sensors"][entity_id]
    assert stat["n"] >= 12 and 10 <= stat["ewma"] <= 20
    assert manager.learning.silent_candidates() == []
    freezer.tick(timedelta(hours=5))
    [candidate] = manager.learning.silent_candidates()
    assert (
        candidate["entity_id"] == entity_id
        and candidate["silent_minutes"] >= 300
        and candidate["normal_minutes"] <= 20
    )
    findings = await manager.health.async_collect()
    silent = [f for f in findings if f.detector == "silent"]
    assert [f.summary for f in silent] == ["Garage stopped reporting"] and silent[
        0
    ].key == f"health:silent:{device_id}"
    assert "normally every ~" in silent[0].description and "silent for 5 h" in silent[0].description
    insight = manager.learning.insights()["learned"]["health"]
    assert insight["tracked_sensors"] == 1 and insight["silent"][0]["entity_id"] == entity_id
    # reporting again clears it
    hass.states.async_set(
        entity_id, "21", {"state_class": "measurement", "device_class": "temperature"}
    )
    assert manager.learning.silent_candidates() == []


async def test_silence_ignores_unavailable_excluded_and_slow_sensors(
    hass, manager, broken, freezer
):
    freezer.move_to("2026-12-01 08:00:00+01:00")
    _, a = make_sensor(hass, broken, "Alpha")
    _, b = make_sensor(hass, broken, "Beta")
    manager.learning.sample()
    for step in range(1, 16):
        freezer.tick(timedelta(minutes=15))
        for entity in (a, b):
            hass.states.async_set(entity, str(step), {"state_class": "measurement"})
        manager.learning.sample()
    freezer.tick(timedelta(hours=6))
    assert {c["entity_id"] for c in manager.learning.silent_candidates()} == {a, b}
    hass.states.async_set(a, "unavailable", {"state_class": "measurement"})
    manager.options = {"health_exclude_entities": [b]}
    assert manager.learning.silent_candidates() == []
    manager.learning_data["health"]["sensors"][b]["ewma"] = (
        900.0  # reports rarely: not tracked for silence
    )
    manager.options = {}
    hass.states.async_set(a, "1", {"state_class": "measurement"})
    freezer.tick(timedelta(days=3))
    assert {c["entity_id"] for c in manager.learning.silent_candidates()} == {a}


async def test_sampling_skips_helpers_ghosts_and_stateless_sensors(hass, manager, broken):
    make_sensor(hass, broken, "Real")
    hass.states.async_set("sensor.no_registry", "1", {"state_class": "measurement"})
    hass.states.async_set("sensor.text_only", "hello", {})
    entities = er.async_get(hass)
    entities.async_get_or_create("sensor", "template", "tpl", suggested_object_id="tpl")
    hass.states.async_set("sensor.tpl", "1", {"state_class": "measurement"})
    hass.states.async_set("sensor.real_temp", "unavailable", {"state_class": "measurement"})
    manager.learning.sample()
    assert manager.learning_data["health"]["sensors"] == {}
    hass.states.async_set("sensor.real_temp", "5", {"state_class": "measurement"})
    manager.learning.sample()
    assert list(manager.learning_data["health"]["sensors"]) == ["sensor.real_temp"]
    hass.states.async_remove("sensor.real_temp")
    manager.learning.sample()
    assert manager.learning_data["health"]["sensors"] == {}  # gone entities are forgotten


async def test_noisy_faults_lead_to_an_ignore_suggestion(hass, manager, broken, freezer):
    freezer.move_to("2026-12-01 08:00:00+01:00")
    from .test_health import make_device

    make_device(hass, broken, "Hallway lamp", [("switch", "main", "unavailable", {})])
    freezer.move_to("2026-12-01 12:00:00+01:00")
    monitor = manager.health
    monitor.grace_until = dt_util.utcnow() - timedelta(minutes=1)
    for _ in range(3):  # you close it by hand three times while it is still broken
        await monitor.async_scan(force=True)  # creates it, later reopens it after the snooze
        issue = next(
            i
            for i in manager.issues.values()
            if i["source"] == "health" and manager.category(i) != "done"
        )
        manager.move_issue(issue["id"], "Done", actor="person.joachim", source="ui")
        freezer.tick(timedelta(days=8))
        hass.states.async_set("switch.hallway_lamp_main", "unavailable")
    await monitor.async_scan(force=True)  # notices the third closure and reopens
    manager.learning.refresh()
    suggestions = [
        s for s in manager.learning.insights()["suggestions"] if s["kind"] == "health_ignore"
    ]
    assert len(suggestions) == 1
    assert (
        suggestions[0]["proposal"]["summary"] == "Hallway lamp is offline"
        and "closed it 3 times" in suggestions[0]["detail"]
    )
    result = manager.learning.accept(suggestions[0]["id"])
    assert result == {"applied": True}
    key = suggestions[0]["proposal"]["key"]
    assert key in manager.learning.health_ignored()
    scan = await monitor.async_scan(force=True)
    assert scan["findings"][0]["action"] == "ignored"
    open_ones = [
        i
        for i in manager.issues.values()
        if i["source"] == "health" and manager.category(i) != "done"
    ]
    assert open_ones == []


async def test_coming_back_repeatedly_is_counted(hass, manager):
    for _ in range(3):
        manager.learning.record_health("reopens", "health:offline:abc")
    manager.learning.record_health("closures", "health:offline:abc", "issue-1")
    manager.learning.record_health(
        "closures", "health:offline:abc", "issue-1"
    )  # the same issue is counted once
    assert manager.learning_data["health"]["closures"] == {"health:offline:abc": 1}
    [suggestion] = manager.learning.insights()["suggestions"]
    assert "came back 3 times" in suggestion["detail"]
    assert manager.learning.insights()["learned"]["health"]["flapping"][0]["reopened"] == 3
    manager.options = {"learn_health": False}
    manager.learning.record_health("reopens", "health:offline:zzz")
    assert "health:offline:zzz" not in manager.learning_data["health"]["reopens"]


# ------------------------------------------------------------------ rhythm


async def test_rhythm_is_off_by_default_and_samples_only_when_enabled(hass, manager, freezer):
    freezer.move_to("2026-12-01 08:10:00+01:00")  # a Tuesday
    manager.learning.sample()
    assert (
        "rhythm" not in manager.learning_data
        and "rhythm" not in manager.learning.insights()["learned"]
    )
    manager.options = {"learn_rhythm": True}
    hass.states.async_set(
        "person.padmaja", "not_home", {"friendly_name": "Padmaja", "user_id": "user-1"}
    )
    hass.states.async_set(
        "person.joachim", "unknown", {"friendly_name": "Joachim", "user_id": "user-0"}
    )
    manager.learning.sample()
    block = manager.learning_data["rhythm"]["person.padmaja"]
    assert block["seen"][1][8] == 1 and block["home"][1][8] == 0 and block["samples"] == 1
    assert "person.joachim" not in manager.learning_data["rhythm"]  # unknown state is not counted
    hass.states.async_set(
        "person.padmaja", "home", {"friendly_name": "Padmaja", "user_id": "user-1"}
    )
    manager.learning.sample()
    assert manager.learning_data["rhythm"]["person.padmaja"]["home"][1][8] == 1
    grid = manager.learning.insights()["learned"]["rhythm"]["people"]["person.padmaja"]
    assert grid["samples"] == 2 and grid["grid"][1][8] == 0.5 and len(grid["grid"]) == 7


async def test_digest_time_suggestion_from_the_rhythm(hass, manager):
    manager.options = {"learn_rhythm": True, "digest_enabled": True, "digest_time": "07:30"}
    from custom_components.homeboard import insights

    seen, home = insights.blank_grid(), insights.blank_grid()
    for day in range(5):
        seen[day][8], home[day][8] = 60, 57
    manager.learning_data["rhythm"] = {
        "person.padmaja": {"seen": seen, "home": home, "samples": 300}
    }
    manager.learning.refresh()
    [suggestion] = manager.learning.insights()["suggestions"]
    assert suggestion["kind"] == "digest_time" and suggestion["proposal"] == {
        "person": "person.padmaja",
        "time": "08:15",
    }
    assert "Padmaja" in suggestion["title"] and "95%" in suggestion["detail"]
    manager.learning.accept(suggestion["id"])
    assert manager.push.digest_time("person.padmaja").strftime("%H:%M") == "08:15"
    assert manager.learning.open_count() == 0
    manager.options = {"learn_rhythm": True, "digest_enabled": False}
    manager.learning.forget("rhythm")
    assert "rhythm" not in manager.learning_data and "digest_times" not in manager.learning_data


# ------------------------------------------------------------------ forgetting, insights, websocket


async def test_forget_everything_and_validation(hass, manager):
    manager.learning_data.update(
        dismissed=["recurring:x", "health_ignore:y"],
        rhythm={"p": 1},
        digest_times={"p": "08:00"},
        health={"sensors": {}},
    )
    with pytest.raises(InvalidError):
        manager.learning.forget("telepathy")
    assert manager.learning.forget("defaults") == []  # nothing stored: computed live from the board
    assert set(manager.learning.forget()) == {
        "dismissed suggestions",
        "sensor rhythms and fault history",
        "home / away rhythm",
        "learned digest times",
    }
    assert manager.learning_data == {"dismissed": []}


async def test_insights_page_content(hass, manager):
    manager.create_issue("HOME", "Fix gate", assignee="person.joachim", labels=["garden"])
    manager.create_issue(
        "HOME", "Water plants", assignee="person.joachim", labels=["garden", "home"]
    )
    manager.create_issue("HOME", "Auto thing", source="health", labels=["auto"])
    page = manager.learning.insights()
    assert page["features"] == {
        "defaults": True,
        "patterns": True,
        "workload": True,
        "health": True,
        "rhythm": False,
        "habits": False,
    }
    learned = page["learned"]
    assert learned["defaults"]["issues_analysed"] == 2 and learned["defaults"]["top_labels"][0] == [
        "garden",
        2,
    ]
    assert learned["defaults"]["people"] == [{"person": "person.joachim", "issues": 2}]
    assert learned["workload"]["people"]["person.joachim"]["open"] == 2
    assert "rhythm" not in learned and learned["health"] == {
        "tracked_sensors": 0,
        "silent": [],
        "flapping": [],
    }
    manager.options = {
        "learn_defaults": False,
        "learn_workload": False,
        "learn_health": False,
        "learn_patterns": False,
    }
    assert manager.learning.insights()["learned"] == {}


async def test_insights_websocket_and_permissions(
    hass, manager, hass_ws_client, hass_read_only_access_token
):
    admin = await hass_ws_client(hass)
    limited = await hass_ws_client(hass, hass_read_only_access_token)
    weekly_bags(manager)
    manager.learning.refresh()

    async def send(client, kind, **kw):
        await client.send_json_auto_id({"type": f"homeboard/insights/{kind}", **kw})
        return await client.receive_json()

    page = (await send(admin, "get"))["result"]
    assert page["suggestions"][0]["kind"] == "recurring"
    assert (await send(limited, "get"))["success"]  # everyone may look
    assert (await send(limited, "forget"))["error"]["code"] == "unauthorized"
    accepted = (await send(limited, "accept", suggestion_id=page["suggestions"][0]["id"]))["result"]
    assert accepted["applied"] and accepted["recurring_id"]
    assert (await send(admin, "dismiss", suggestion_id="nope"))["error"]["code"] == "not_found"
    assert (await send(admin, "accept", suggestion_id="nope"))["error"]["code"] == "not_found"
    forgotten = (await send(admin, "forget", feature="patterns"))["result"]
    assert forgotten == {"forgotten": ["dismissed suggestions"]}
    assert (await send(admin, "forget", feature="telepathy"))["error"]["code"] == "invalid_format"
    again = (await send(admin, "forget"))["result"]
    assert "forgotten" in again
    result = await hass.services.async_call(
        const.DOMAIN, "forget_learning", {"feature": "health"}, blocking=True, return_response=True
    )
    assert result == {"forgotten": []}


async def test_engine_ticks_refresh_the_badge_and_unload_cleanly(hass, entry):
    await setup(hass, entry)
    manager = entry.runtime_data
    weekly_bags(manager)
    assert manager.learning.open_count() == 0  # not refreshed yet
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
    await hass.async_block_till_done()
    assert (
        manager.learning.open_count() == 1
        and hass.states.get("sensor.homeboard_suggestions").state == "1"
    )
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert manager.learning._unsub is None
