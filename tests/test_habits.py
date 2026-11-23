"""Habits: the miner (pure), the scanner and the inbox, creating and undoing a (switched off) automation."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import Unauthorized
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml

from custom_components.homeboard import habits, habits_scan

TZ = ZoneInfo("Europe/Copenhagen")
TODAY = date(2026, 11, 25)  # a Wednesday
LAST = date(2026, 11, 24)


def at(day: date, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=TZ)


def days_back(count: int) -> list[date]:
    """The ``count`` complete days before TODAY, oldest first."""
    return [LAST - timedelta(days=n) for n in range(count - 1, -1, -1)]


def routine_series(
    days: list[date], hour: int, minute: int, *, weekdays_only=False
) -> habits.Series:
    series: habits.Series = [(at(days[0] - timedelta(days=1), 0), "off")]
    for index, day in enumerate(days):
        if weekdays_only and day.weekday() >= 5:
            continue
        series.append((at(day, hour, minute + index % 3), "on"))
        series.append((at(day, 8, 0), "off"))
    return series


# ------------------------------------------------------------------ the miner


def test_transitions_ignore_unavailable_and_repeats_and_use_the_first_state_as_baseline():
    base = [
        (at(LAST, 1), "off"),
        (at(LAST, 2), "unavailable"),
        (at(LAST, 3), "off"),
        (at(LAST, 4), "on"),
        (at(LAST, 5), "on"),
        (at(LAST, 6), "closed"),
        (at(LAST, 7), "open"),
    ]
    assert [(m.hour, s) for m, s in habits.transitions(base)] == [(4, "on"), (6, "off"), (7, "on")]


def test_a_routine_on_every_day_is_found_with_a_rounded_time_and_a_window():
    found = habits.mine({"light.hall": routine_series(days_back(12), 6, 30)}, {}, today=TODAY)
    assert found["error"] is None and found["history_days"] == 11  # the first day is usually cut
    routine = next(c for c in found["candidates"] if c["action"] == "on")
    assert routine["id"] == "habit:time:light.hall:on:all" and routine["pattern"] == "routine"
    assert routine["time"] == "06:30" and routine["window"] == ["06:30", "06:32"]
    assert routine["days"] == routine["of"] == 11 and routine["share"] == 1.0
    off = next(c for c in found["candidates"] if c["action"] == "off")
    assert off["time"] == "08:00"


def test_a_weekday_routine_is_found_as_weekdays_not_as_every_day():
    series = routine_series(days_back(12), 6, 30, weekdays_only=True)
    found = habits.mine({"light.hall": series}, {}, today=TODAY)
    ids = {c["id"] for c in found["candidates"] if c["action"] == "on"}
    assert ids == {"habit:time:light.hall:on:weekdays"}
    candidate = next(c for c in found["candidates"] if c["action"] == "on")
    assert candidate["of"] == 7 and candidate["days"] == 7


def test_scattered_times_and_too_few_days_are_not_habits():
    scattered: habits.Series = [(at(days_back(12)[0], 0), "off")]
    for index, day in enumerate(days_back(12)):
        scattered.append((at(day, 5 + index % 10, 0), "on"))  # a different hour almost every day
        scattered.append((at(day, 23, 0), "off"))
    assert not [
        c
        for c in habits.mine({"light.x": scattered}, {}, today=TODAY)["candidates"]
        if c["action"] == "on"
    ]
    few = routine_series(days_back(12)[:4], 6, 30)
    assert habits.mine({"light.y": few}, {}, today=TODAY)["candidates"] == []


def test_not_enough_history_is_reported():
    result = habits.mine({"light.hall": routine_series(days_back(5), 6, 30)}, {}, today=TODAY)
    assert result["error"] == "no_history" and result["candidates"] == []
    assert habits.mine({}, {}, today=TODAY)["error"] == "no_history"


def sensor_and_light(days: list[date], *, follow_share=1.0, back_minutes=4):
    sensor: habits.Series = [(at(days[0] - timedelta(days=1), 0), "off")]
    light: habits.Series = [(at(days[0] - timedelta(days=1), 0), "off")]
    for index, day in enumerate(days):
        for n, hour in enumerate((19, 21)):
            on = at(day, hour, 10 + n)
            sensor.append((on, "on"))
            sensor.append((on + timedelta(seconds=40), "off"))
            hit = (index * 2 + n) / (len(days) * 2) < follow_share
            if hit:
                light.append((on + timedelta(seconds=15), "on"))
                light.append((on + timedelta(seconds=40, minutes=back_minutes), "off"))
    return sensor, light


def test_a_light_that_follows_a_motion_sensor_becomes_a_follow_up_and_a_switch_back():
    sensor, light = sensor_and_light(days_back(8))
    found = habits.mine({"light.hall": light}, {"binary_sensor.hall_motion": sensor}, today=TODAY)
    by_id = {c["id"]: c for c in found["candidates"]}
    follow = by_id["habit:follow:binary_sensor.hall_motion:light.hall:on"]
    assert follow["pattern"] == "follow_up" and follow["samples"] == follow["out_of"] == 14
    assert follow["night_only"] is True and follow["share"] == 1.0
    back = by_id["habit:back:binary_sensor.hall_motion:light.hall:off"]
    assert back["pattern"] == "switch_back" and back["delay_minutes"] == 4


def test_repeated_motion_within_five_minutes_counts_once_and_weak_links_are_dropped():
    sensor, light = sensor_and_light(days_back(8), follow_share=0.4)
    found = habits.mine({"light.hall": light}, {"binary_sensor.hall_motion": sensor}, today=TODAY)
    assert not [c for c in found["candidates"] if c["pattern"] == "follow_up"]
    busy: habits.Series = [(at(days_back(8)[0], 0), "off")]
    for day in days_back(8):
        for n in range(6):  # six flickers within a minute = one activation
            busy.append((at(day, 12, 0, n * 5), "on"))
            busy.append((at(day, 12, 0, n * 5 + 2), "off"))
    assert len(habits._activations(habits.transitions(busy), days_back(8)[0], LAST)) == 8


# ------------------------------------------------------------------ the scanner


@pytest.fixture
async def home(hass, tmp_path, manager, freezer):
    freezer.move_to("2026-11-25 12:00:00+01:00")
    hass.config.config_dir = str(tmp_path)
    (tmp_path / "configuration.yaml").write_text("automation: !include automations.yaml\n")
    (tmp_path / "automations.yaml").write_text("[]\n")
    registry = er.async_get(hass)
    for domain, uid, state, attrs in (
        ("light", "hall", "off", {"friendly_name": "Hall light"}),
        ("light", "kitchen", "off", {"friendly_name": "Kitchen light"}),
        (
            "binary_sensor",
            "motion",
            "off",
            {"friendly_name": "Hall motion", "device_class": "motion"},
        ),
        ("binary_sensor", "plug", "off", {"friendly_name": "A plug", "device_class": "plug"}),
        ("cover", "garage", "closed", {"friendly_name": "Garage door", "device_class": "garage"}),
        ("cover", "curtain", "closed", {"friendly_name": "Curtain", "device_class": "curtain"}),
        ("switch", "siren", "off", {"friendly_name": "Back siren"}),
        ("switch", "lamp", "off", {"friendly_name": "Reading lamp"}),
        ("lock", "front", "locked", {"friendly_name": "Front door lock"}),
        ("media_player", "tv", "off", {"friendly_name": "TV"}),
    ):
        entry = registry.async_get_or_create(domain, "fake", uid, suggested_object_id=uid)
        hass.states.async_set(entry.entity_id, state, attrs)
    assert await async_setup_component(hass, "automation", {"automation": []})
    await hass.async_block_till_done()
    manager.options = {"learn_habits": True}
    sensor, light = sensor_and_light(days_back(8))
    history = {
        "light.hall": routine_series(days_back(12), 6, 30) + light[1:],
        "binary_sensor.hall_motion": sensor,
        "light.kitchen": [(at(LAST, 0), "off")],
    }
    history["light.hall"].sort(key=lambda item: item[0])
    manager.habits._fetch = AsyncMock(return_value=history)
    return tmp_path


def inbox(manager):
    return [s for s in manager.learning.insights()["suggestions"] if s["kind"] == "automation"]


async def test_the_scanner_only_looks_at_safe_entities(hass, home, manager):
    targets, sensors = manager.habits._entities()
    assert targets == ["cover.curtain", "light.hall", "light.kitchen", "switch.lamp"]
    assert sensors == ["binary_sensor.motion"]  # no plug, no garage door, no siren, no lock, no TV
    manager.options = {"learn_habits": True, "health_exclude_entities": ["light.kitchen"]}
    assert "light.kitchen" not in manager.habits._entities()[0]


async def test_a_scan_puts_ideas_in_the_inbox_with_evidence_and_yaml_but_not_the_config(
    hass, home, manager
):
    manager.habits._fetch.return_value["binary_sensor.motion"] = (
        manager.habits._fetch.return_value.pop("binary_sensor.hall_motion")
    )
    result = await manager.habits.async_scan()
    assert result["error"] is None and result["found"] >= 3 and result["days"] == 11
    ideas = {s["id"]: s for s in inbox(manager)}
    routine = ideas["habit:time:light.hall:on:all"]
    assert (
        routine["title"] == "Turn on Hall light at 06:30?"
        and "11 of the last 11 days" in routine["detail"]
    )
    assert routine["evidence"]["pattern"] == "routine" and routine["evidence"]["window"] == [
        "06:30",
        "06:32",
    ]
    assert (
        "trigger: time" in routine["proposal"]["yaml"]
        and "light.turn_on" in routine["proposal"]["yaml"]
    )
    assert not [
        k for k in routine["proposal"] if k.startswith("_")
    ]  # the machine config stays here
    assert "habit:follow:binary_sensor.motion:light.hall:on" in ideas
    page = manager.learning.insights()
    assert page["features"]["habits"] is True and page["learned"]["habits"]["error"] is None
    assert page["learned"]["habits"]["days"] == 11 and page["learned"]["habits"]["created"] == []
    assert manager.learning.open_count() == len(inbox(manager))


async def test_the_feature_is_off_by_default_and_the_ideas_are_dismissable_for_good(
    hass, home, manager
):
    manager.options = {}
    assert manager.settings()["learning"]["habits"] is False and inbox(manager) == []
    assert "habits" not in manager.learning.insights()["learned"]
    manager.options = {"learn_habits": True}
    await manager.habits.async_scan()
    first = inbox(manager)[0]["id"]
    manager.learning.dismiss(first)
    await manager.habits.async_scan()
    assert first not in [s["id"] for s in inbox(manager)]


async def test_scan_problems_are_reported_not_raised(hass, home, manager):
    manager.habits._fetch = AsyncMock(side_effect=habits_scan.HabitError("no_recorder", "x"))
    assert (await manager.habits.async_scan())["error"] == "no_recorder"
    manager.habits._fetch = AsyncMock(side_effect=RuntimeError("boom"))
    assert (await manager.habits.async_scan())["error"] == "failed"
    manager.habits._fetch = AsyncMock(
        return_value={"light.hall": routine_series(days_back(4), 6, 30)}
    )
    result = await manager.habits.async_scan()
    assert result["error"] == "no_history" and result["days"] <= 4
    assert manager.learning.insights()["learned"]["habits"]["error"] == "no_history"


async def test_ideas_for_what_an_automation_already_does_are_not_suggested(hass, home, manager):
    (home / "automations.yaml").write_text(
        json.dumps(
            [
                {
                    "id": "morning",
                    "alias": "Morning",
                    "triggers": [
                        {"trigger": "state", "entity_id": "binary_sensor.motion", "to": "on"}
                    ],
                    "actions": [{"action": "light.turn_on", "target": {"entity_id": "light.hall"}}],
                }
            ]
        )
    )
    await hass.services.async_call("automation", "reload", blocking=True)
    await manager.habits.async_scan()
    ids = [s["id"] for s in inbox(manager)]
    assert "habit:time:light.hall:on:all" not in ids  # an automation already turns it on
    assert "habit:time:light.hall:off:all" in ids  # but nothing switches it off


async def test_creating_an_idea_makes_a_switched_off_automation_with_a_backup_and_undo(
    hass, home, manager
):
    events = []
    hass.bus.async_listen("homeboard_habit_automation_created", events.append)
    await manager.habits.async_scan()
    idea = next(s for s in inbox(manager) if s["id"] == "habit:time:light.hall:on:all")
    created = await manager.habits.async_create(idea["id"], "person.joachim")
    await hass.async_block_till_done()
    assert created["state"] == "created" and created["alias"] == "Hall light on at 06:30"
    assert created["edit_url"] == f"/config/automation/edit/{created['auto_id']}"
    assert not [k for k in created if k.startswith("_")]
    assert hass.states.get(created["entity_id"]).state == "off"  # never on by itself
    items = load_yaml(str(home / "automations.yaml"))
    new = next(i for i in items if str(i["id"]) == created["auto_id"])
    assert new["triggers"] == [{"trigger": "time", "at": "06:30:00"}]
    assert new["actions"] == [{"action": "light.turn_on", "target": {"entity_id": "light.hall"}}]
    assert list((home / "homeboard_backups").glob("automations-*.yaml"))
    assert idea["id"] not in [s["id"] for s in inbox(manager)]  # out of the inbox
    assert (
        manager.learning.insights()["learned"]["habits"]["created"][0]["auto_id"]
        == created["auto_id"]
    )
    assert len(events) == 1 and events[0].data["entity_id"] == created["entity_id"]

    gone = await manager.habits.async_undo(created["id"])
    await hass.async_block_till_done()
    assert gone["state"] == "undone"
    assert not [
        i for i in load_yaml(str(home / "automations.yaml")) if str(i["id"]) == created["auto_id"]
    ]
    assert hass.states.get(created["entity_id"]) is None
    assert idea["id"] in [s["id"] for s in inbox(manager)]  # changed my mind: the idea is back
    with pytest.raises(habits_scan.HabitError) as err:
        await manager.habits.async_undo(created["id"])
    assert err.value.code == "not_found"


async def test_every_kind_of_idea_makes_an_automation_home_assistant_accepts(hass, home, manager):
    hass.states.async_set("sun.sun", "below_horizon")
    manager.habits._fetch.return_value["binary_sensor.motion"] = manager.habits._fetch.return_value[
        "binary_sensor.hall_motion"
    ]
    await manager.habits.async_scan()
    patterns = {s["evidence"]["pattern"] for s in inbox(manager)}
    assert patterns == {"routine", "follow_up", "switch_back"}
    for idea in list(inbox(manager)):
        record = await manager.habits.async_create(idea["id"], None)
        assert hass.states.get(record["entity_id"]).state == "off", idea["id"]
    items = load_yaml(str(home / "automations.yaml"))
    follow = next(i for i in items if "detects" in i["alias"])
    assert follow["conditions"] == [
        {"condition": "state", "entity_id": "sun.sun", "state": "below_horizon"}
    ]
    assert follow["triggers"][0]["to"] == "on"
    back = next(i for i in items if "is quiet" in i["alias"])
    assert back["triggers"][0]["for"] == {"hours": 0, "minutes": 4, "seconds": 0}


async def test_creating_the_on_idea_does_not_hide_the_off_idea_but_the_same_direction_is_covered(
    hass, home, manager
):
    manager.habits._fetch.return_value["binary_sensor.motion"] = manager.habits._fetch.return_value[
        "binary_sensor.hall_motion"
    ]
    await manager.habits.async_scan()
    follow = next(s for s in inbox(manager) if s["evidence"]["pattern"] == "follow_up")
    await manager.habits.async_create(follow["id"], None)
    await manager.habits.async_scan()
    patterns = {s["evidence"]["pattern"] for s in inbox(manager)}
    assert (
        "switch_back" in patterns and "follow_up" not in patterns
    )  # the "on" is done, the "off" is not


def test_acts_on_reads_the_direction_of_an_automation():
    config = {
        "actions": [
            {"action": "light.turn_on", "target": {"entity_id": "light.a"}},
            {"action": "light.turn_off", "entity_id": ["light.b", "light.c"]},
            {"action": "light.toggle", "target": {"entity_id": "light.t"}},
            {"action": "script.turn_on", "target": {"entity_id": "light.s"}},
            {
                "choose": [
                    {
                        "sequence": [
                            {"action": "cover.close_cover", "target": {"entity_id": "cover.x"}}
                        ]
                    }
                ]
            },
        ]
    }
    assert habits_scan.acts_on(config, "light.a", "on") and not habits_scan.acts_on(
        config, "light.a", "off"
    )
    assert habits_scan.acts_on(config, "light.c", "off") and not habits_scan.acts_on(
        config, "light.c", "on"
    )
    assert habits_scan.acts_on(config, "light.t", "on") and habits_scan.acts_on(
        config, "light.t", "off"
    )
    assert habits_scan.acts_on(config, "light.s", "on")  # a script could do anything
    assert habits_scan.acts_on(config, "cover.x", "off") and not habits_scan.acts_on(
        config, "cover.x", "on"
    )
    assert not habits_scan.acts_on(config, "light.other", "on")


async def test_create_refuses_when_it_should(hass, home, manager):
    await manager.habits.async_scan()
    idea = manager.learning._suggestions[0]  # the internal form, with the machine config
    with pytest.raises(habits_scan.HabitError) as err:
        await manager.habits.async_create("habit:nope", None)
    assert err.value.code == "not_found"
    # an entity that vanished
    hass.states.async_remove(idea["proposal"]["entity_id"])
    with pytest.raises(habits_scan.HabitError) as err:
        await manager.habits.async_create(idea["id"], None)
    assert err.value.code == "blocked"
    hass.states.async_set(idea["proposal"]["entity_id"], "off", {"friendly_name": "back"})
    # something the miner never produces
    idea["proposal"]["_config"]["actions"] = [
        {"action": "lock.unlock", "target": {"entity_id": "lock.front"}}
    ]
    manager.learning._suggestions = [idea]
    with pytest.raises(habits_scan.HabitError) as err:
        await manager.habits.async_create(idea["id"], None)
    assert err.value.code == "blocked" and "never automates" in str(err.value)
    # switched off
    manager.options = {}
    with pytest.raises(habits_scan.HabitError) as err:
        await manager.habits.async_create(idea["id"], None)
    assert err.value.code == "habits_disabled"


async def test_create_refuses_a_file_it_cannot_write_and_an_idea_that_now_exists(
    hass, home, manager
):
    await manager.habits.async_scan()
    idea = next(s for s in inbox(manager) if s["id"] == "habit:time:light.hall:on:all")
    original = (home / "automations.yaml").read_text()
    (home / "automations.yaml").write_text("- id: x\n  alias: !include other.yaml\n")
    (home / "other.yaml").write_text("y\n")
    with pytest.raises(habits_scan.HabitError) as err:
        await manager.habits.async_create(idea["id"], None)
    assert err.value.code == "not_editable"
    (home / "automations.yaml").write_text(original)
    with (
        patch.object(manager.habits, "_covered", return_value=True),
        pytest.raises(habits_scan.HabitError) as err,
    ):
        await manager.habits.async_create(idea["id"], None)
    assert err.value.code == "exists"
    assert (home / "automations.yaml").read_text() == original


async def test_an_automation_that_does_not_come_up_is_removed_again(hass, home, manager):
    await manager.habits.async_scan()
    idea = next(s for s in inbox(manager) if s["id"] == "habit:time:light.hall:on:all")
    with (
        patch.object(manager.habits, "_load_and_switch_off", AsyncMock(return_value=None)),
        pytest.raises(habits_scan.HabitError) as err,
    ):
        await manager.habits.async_create(idea["id"], None)
    assert err.value.code == "create_failed"
    assert load_yaml(str(home / "automations.yaml")) in (None, [])
    assert manager.habits.status()["created"] == []


async def test_undo_will_not_throw_away_an_edit(hass, home, manager):
    await manager.habits.async_scan()
    idea = next(s for s in inbox(manager) if s["id"] == "habit:time:light.hall:on:all")
    created = await manager.habits.async_create(idea["id"], None)
    items = load_yaml(str(home / "automations.yaml"))
    items[0]["alias"] = "I renamed it"
    (home / "automations.yaml").write_text(json.dumps(items))
    with pytest.raises(habits_scan.HabitError) as err:
        await manager.habits.async_undo(created["id"])
    assert err.value.code == "stale"
    assert load_yaml(str(home / "automations.yaml"))[0]["alias"] == "I renamed it"
    assert manager.habits.status()["created"][0]["state"] == "created"


async def test_the_texts_follow_the_language_of_home_assistant(hass, home, manager):
    await hass.config.async_update(language="da")
    await manager.habits.async_scan()
    routine = next(s for s in inbox(manager) if s["id"] == "habit:time:light.hall:on:all")
    assert (
        routine["title"] == "Tænd Hall light kl. 06:30?"
        and "11 af de seneste 11 dage" in routine["detail"]
    )
    assert "Foreslået af Homeboard" in routine["proposal"]["description"]
    await manager.habits.async_scan()
    assert any(s["title"].startswith("Sluk ") for s in inbox(manager))


async def test_forget_clears_the_ideas_but_keeps_what_was_created(hass, home, manager):
    await manager.habits.async_scan()
    idea = next(s for s in inbox(manager) if s["id"] == "habit:time:light.hall:on:all")
    created = await manager.habits.async_create(idea["id"], None)
    manager.learning.dismiss(next(s["id"] for s in inbox(manager)))
    assert "habit ideas" in manager.learning.forget("habits")
    assert inbox(manager) == [] and manager.habits.status()["last_scan"] is None
    assert not any(d.startswith("habit:") for d in manager.learning.data["dismissed"])
    assert manager.habits.status()["created"][0]["id"] == created["id"]
    with pytest.raises(Exception, match="feature must be one of"):
        manager.learning.forget("nonsense")


async def test_the_scan_runs_by_night_and_after_start_only_when_needed(hass, home, manager):
    manager.habits._fetch.reset_mock()
    manager.options = {}
    await manager.habits._async_nightly(None)
    await manager.habits._async_after_start(None)
    manager.habits._fetch.assert_not_called()  # off: nothing is read
    manager.options = {"learn_habits": True}
    await manager.habits._async_after_start(None)
    assert manager.habits._fetch.call_count == 1
    await manager.habits._async_after_start(None)  # fresh enough
    assert manager.habits._fetch.call_count == 1
    await manager.habits._async_nightly(None)
    assert manager.habits._fetch.call_count == 2
    manager.habits.async_stop()


async def test_the_default_fetch_reads_the_recorder_history_in_its_executor(hass, home, manager):
    class State:
        def __init__(self, state, hour):
            self.state = state
            self.last_changed = at(LAST, hour).astimezone(ZoneInfo("UTC"))

    instance = MagicMock()
    instance.async_add_executor_job = AsyncMock(
        side_effect=lambda fetch: {"light.hall": [State("off", 0), State("on", 6)]}
    )
    with (
        patch("homeassistant.components.recorder.get_instance", return_value=instance),
        patch("homeassistant.components.recorder.history.get_significant_states"),
    ):
        data = await habits_scan.HabitsScanner(hass, manager)._fetch(
            ["light.hall"], at(LAST, 0), at(TODAY, 0)
        )
    assert [(m.hour, s) for m, s in data["light.hall"]] == [(0, "off"), (6, "on")]
    with (
        patch("homeassistant.components.recorder.get_instance", side_effect=KeyError("recorder")),
        pytest.raises(habits_scan.HabitError) as err,
    ):
        await habits_scan.HabitsScanner(hass, manager)._fetch(
            ["light.hall"], at(LAST, 0), at(TODAY, 0)
        )
    assert err.value.code == "no_recorder"


# ------------------------------------------------------------------ websocket and service


@pytest.fixture
async def ws(hass, home, hass_ws_client, hass_admin_user):
    hass.states.async_set(
        "person.admin", "home", {"friendly_name": "Admin", "user_id": hass_admin_user.id}
    )
    return await hass_ws_client(hass)


async def send(ws, type_, **kw):
    await ws.send_json_auto_id({"type": f"homeboard/{type_}", **kw})
    return await ws.receive_json()


async def test_websocket_scan_create_undo_and_the_refused_accept(hass, ws, manager):
    scan = (await send(ws, "habits/scan"))["result"]
    assert scan["error"] is None and scan["found"] >= 2
    page = (await send(ws, "insights/get"))["result"]
    idea = next(s for s in page["suggestions"] if s["id"] == "habit:time:light.hall:on:all")
    assert "_config" not in json.dumps(page)
    refused = await send(ws, "insights/accept", suggestion_id=idea["id"])
    assert not refused["success"] and refused["error"]["code"] == "use_habits_create"
    created = (await send(ws, "habits/create", suggestion_id=idea["id"]))["result"]["created"]
    assert created["state"] == "created"
    page = (await send(ws, "insights/get"))["result"]
    assert page["learned"]["habits"]["created"][0]["id"] == created["id"]
    again = await send(ws, "habits/create", suggestion_id=idea["id"])
    assert again["error"]["code"] == "not_found"
    undone = (await send(ws, "habits/undo", created_id=created["id"]))["result"]["created"]
    assert undone["state"] == "undone"
    assert (await send(ws, "habits/undo", created_id="nope"))["error"]["code"] == "not_found"
    manager.options = {}
    assert (await send(ws, "habits/scan"))["error"]["code"] == "habits_disabled"


async def test_only_administrators_may_scan_create_or_undo(
    hass, home, manager, hass_ws_client, hass_read_only_access_token
):
    client = await hass_ws_client(hass, hass_read_only_access_token)
    for cmd, args in (
        ("habits/scan", {}),
        ("habits/create", {"suggestion_id": "x"}),
        ("habits/undo", {"created_id": "x"}),
    ):
        reply = await send(client, cmd, **args)
        assert not reply["success"] and reply["error"]["code"] == "unauthorized", cmd


async def test_the_scan_service_is_for_administrators_and_needs_the_feature(
    hass, home, manager, hass_admin_user, hass_read_only_user
):
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            "homeboard",
            "scan_habits",
            {},
            blocking=True,
            context=Context(user_id=hass_read_only_user.id),
            return_response=True,
        )
    result = await hass.services.async_call(
        "homeboard",
        "scan_habits",
        {},
        blocking=True,
        context=Context(user_id=hass_admin_user.id),
        return_response=True,
    )
    assert result["error"] is None
    manager.options = {}
    with pytest.raises(Exception, match="switched off"):
        await hass.services.async_call(
            "homeboard", "scan_habits", {}, blocking=True, return_response=True
        )


# ------------------------------------------------------------------ review findings (regressions)


def test_a_monday_to_friday_routine_is_never_reported_as_every_day():
    for count in (12, 16, 21, 28):
        series = routine_series(days_back(count), 6, 30, weekdays_only=True)
        ids = {c["id"] for c in habits.mine({"light.hall": series}, {}, today=TODAY)["candidates"]}
        assert "habit:time:light.hall:on:weekdays" in ids, count
        assert "habit:time:light.hall:on:all" not in ids, count


def test_an_entity_that_flaps_all_day_has_no_habit():
    flapping: habits.Series = [(at(days_back(12)[0], 0), "off")]
    for index, day in enumerate(days_back(12)):
        for n in range(12):  # twelve switchings a day, spread out
            flapping.append(
                (at(day, 1 + n, (index * 7 + n * 13) % 60), "on" if n % 2 == 0 else "off")
            )
    assert habits.mine({"switch.heater": flapping}, {}, today=TODAY)["candidates"] == []


def test_a_light_that_is_always_switching_does_not_follow_every_motion_by_luck():
    sensor, _ = sensor_and_light(days_back(8))
    busy: habits.Series = [(at(days_back(8)[0], 0), "off")]
    for day in days_back(8):
        for minute in range(0, 24 * 60, 4):  # on every four minutes: it would "follow" anything
            moment = at(day, minute // 60, minute % 60)
            busy.append((moment, "on" if (minute // 4) % 2 == 0 else "off"))
    found = habits.mine({"light.busy": busy}, {"binary_sensor.hall_motion": sensor}, today=TODAY)
    assert not [c for c in found["candidates"] if c["pattern"] != "routine"]


def test_mining_a_big_house_is_fast():
    import time as clock

    targets = {}
    for n in range(100):
        series: habits.Series = [(at(days_back(12)[0], 0), "off")]
        for day in days_back(12):
            for k in range(3):
                series.append((at(day, 6 + k * 5, (n * 7) % 60), "on"))
                series.append((at(day, 6 + k * 5, (n * 7) % 60, 30), "off"))
        targets[f"light.l{n}"] = series
    sensors = {}
    for n in range(40):
        series = [(at(days_back(12)[0], 0), "off")]
        for day in days_back(12):
            for k in range(60):
                series.append((at(day, 6 + k // 4, (k % 4) * 15), "on"))
                series.append((at(day, 6 + k // 4, (k % 4) * 15, 20), "off"))
        sensors[f"binary_sensor.s{n}"] = series
    started = clock.perf_counter()
    habits.mine(targets, sensors, today=TODAY)
    assert clock.perf_counter() - started < 5


def test_acts_on_also_reads_data_entity_ids_registry_ids_and_device_actions():
    config = {
        "actions": [
            {"action": "light.turn_on", "data": {"entity_id": "light.d"}},
            {
                "action": "light.turn_off",
                "target": {"entity_id": "0123456789abcdef0123456789abcdef"},
            },
            {"device_id": "dev1", "domain": "light", "type": "turn_on", "entity_id": "x"},
        ]
    }
    assert habits_scan.acts_on(config, "light.d", "on")
    resolve = lambda rid: "light.r" if rid.startswith("0123") else None  # noqa: E731
    assert habits_scan.acts_on(config, "light.r", "off", resolve=resolve)
    assert not habits_scan.acts_on(config, "light.r", "off")
    assert habits_scan.acts_on(
        config, "light.z", "off", device_id="dev1"
    )  # a device action: could be anything
    assert not habits_scan.acts_on(config, "light.z", "off", device_id="dev2")


async def test_switches_only_get_off_ideas_and_risky_names_are_whole_word_matches(
    hass, home, manager
):
    registry = er.async_get(hass)
    for domain, uid, name in (
        ("switch", "heater", "Space heater"),
        ("switch", "clock", "Clock radio"),
        ("fan", "garagefan", "Garage fan"),
        ("fan", "bedfan", "Bedroom fan"),
        ("cover", "window", "Roof window"),
    ):
        entry = registry.async_get_or_create(domain, "fake", uid, suggested_object_id=uid)
        hass.states.async_set(
            entry.entity_id,
            "off",
            {"friendly_name": name, **({"device_class": "window"} if domain == "cover" else {})},
        )
    targets, _ = manager.habits._entities()
    assert (
        "switch.heater" not in targets
        and "fan.garagefan" not in targets
        and "cover.window" not in targets
    )
    assert "switch.clock" in targets and "fan.bedfan" in targets  # "clock" is not "lock"
    on = {"entity_id": "switch.lamp", "action": "on", "trigger_entity": None}
    assert manager.habits._allowed(on) is False  # a plug could be a heater: only "off" ideas
    assert manager.habits._allowed({**on, "action": "off"}) is True
    assert manager.habits._allowed({**on, "entity_id": "light.hall"}) is True


async def test_ideas_are_filtered_again_when_listed_and_when_created(hass, home, manager):
    await manager.habits.async_scan()
    stored = list(manager.learning._suggestions)
    idea = next(s for s in stored if s["id"] == "habit:time:light.hall:on:all")
    manager.options = {"learn_habits": True, "health_exclude_entities": ["light.hall"]}
    manager.learning.refresh()
    assert idea["id"] not in [
        s["id"] for s in inbox(manager)
    ]  # a new exclude rule hides stored ideas
    manager.learning._suggestions = stored  # as if the page was built before the rule changed
    with pytest.raises(habits_scan.HabitError) as err:
        await manager.habits.async_create(idea["id"], None)
    assert err.value.code == "blocked"
    assert load_yaml(str(home / "automations.yaml")) in (None, [])


async def test_two_presses_on_create_make_one_automation(hass, home, manager):
    import asyncio

    await manager.habits.async_scan()
    idea = next(s for s in inbox(manager) if s["id"] == "habit:time:light.hall:on:all")
    first, second = await asyncio.gather(
        manager.habits.async_create(idea["id"], None),
        manager.habits.async_create(idea["id"], None),
        return_exceptions=True,
    )
    results = [first, second]
    assert sum(isinstance(r, dict) for r in results) == 1
    assert (
        sum(isinstance(r, habits_scan.HabitError) and r.code == "not_found" for r in results) == 1
    )
    assert len(load_yaml(str(home / "automations.yaml"))) == 1
    assert len(manager.habits.status()["created"]) == 1


async def test_an_automation_that_cannot_be_switched_off_is_removed_and_never_left_on(
    hass, home, manager
):
    from homeassistant.exceptions import HomeAssistantError

    await manager.habits.async_scan()
    idea = next(s for s in inbox(manager) if s["id"] == "habit:time:light.hall:on:all")

    async def refuse(call):
        raise HomeAssistantError("cannot")

    hass.services.async_register("automation", "turn_off", refuse)
    with pytest.raises(habits_scan.HabitError) as err:
        await manager.habits.async_create(idea["id"], None)
    assert err.value.code == "create_failed"
    await hass.async_block_till_done()
    assert load_yaml(str(home / "automations.yaml")) in (None, [])
    assert manager.habits.status()["created"] == []
    assert not [s for s in hass.states.async_all("automation")]


async def test_when_the_rollback_fails_too_the_message_names_the_automation(hass, home, manager):
    from custom_components.homeboard.automation_config import AutomationEditError

    await manager.habits.async_scan()
    idea = next(s for s in inbox(manager) if s["id"] == "habit:time:light.hall:on:all")
    with (
        patch.object(manager.habits, "_load_and_switch_off", AsyncMock(return_value=None)),
        patch.object(
            manager.habits, "_remove", AsyncMock(side_effect=AutomationEditError("disk full"))
        ),
        pytest.raises(habits_scan.HabitError) as err,
    ):
        await manager.habits.async_create(idea["id"], None)
    assert err.value.code == "create_failed" and "Check automation" in str(err.value)


async def test_an_idea_that_already_exists_leaves_the_inbox(hass, home, manager):
    await manager.habits.async_scan()
    idea = next(s for s in inbox(manager) if s["id"] == "habit:time:light.hall:on:all")
    with (
        patch.object(manager.habits, "_covered", return_value=True),
        pytest.raises(habits_scan.HabitError),
    ):
        await manager.habits.async_create(idea["id"], None)
    assert idea["id"] not in [s["id"] for s in inbox(manager)]


async def test_undo_works_when_the_automation_was_deleted_in_home_assistant_first(
    hass, home, manager
):
    await manager.habits.async_scan()
    idea = next(s for s in inbox(manager) if s["id"] == "habit:time:light.hall:on:all")
    created = await manager.habits.async_create(idea["id"], None)
    (home / "automations.yaml").write_text("[]\n")
    gone = await manager.habits.async_undo(created["id"])
    assert gone["state"] == "undone"


async def test_a_failed_scan_is_retried_after_start_but_a_good_one_is_not(hass, home, manager):
    manager.habits._fetch = AsyncMock(side_effect=habits_scan.HabitError("no_recorder", "x"))
    await manager.habits.async_scan()
    assert manager.habits.block["error"] == "no_recorder"
    manager.habits._fetch = AsyncMock(return_value={})
    await manager.habits._async_after_start(None)  # the last scan failed: try again
    assert manager.habits._fetch.call_count == 1


async def test_the_night_remark_needs_a_sun(hass, home, manager):
    manager.habits._fetch.return_value["binary_sensor.motion"] = manager.habits._fetch.return_value[
        "binary_sensor.hall_motion"
    ]
    await manager.habits.async_scan()
    follow = next(s for s in inbox(manager) if s["evidence"]["pattern"] == "follow_up")
    assert "after dark" not in follow["detail"] and "conditions: []" in follow["proposal"]["yaml"]
    hass.states.async_set("sun.sun", "below_horizon")
    await manager.habits.async_scan()
    follow = next(s for s in inbox(manager) if s["evidence"]["pattern"] == "follow_up")
    assert "after dark" in follow["detail"] and "below_horizon" in follow["proposal"]["yaml"]


async def test_old_backups_are_pruned(hass, home, manager, monkeypatch):
    from custom_components.homeboard import automation_config

    monkeypatch.setattr(automation_config, "MAX_BACKUPS", 3)
    info = await automation_config.async_get_automation(hass, "automation.nothing")
    assert info is None
    (home / "automations.yaml").write_text(
        json.dumps([{"id": "a", "alias": "A", "triggers": [], "actions": []}])
    )
    for n in range(6):
        await automation_config.async_write_automation(
            hass, "a", {"alias": f"A{n}", "triggers": [], "actions": []}
        )
    assert len(list((home / "homeboard_backups").glob("automations-*.yaml"))) == 3


async def test_forget_habits_is_reachable_over_the_websocket_and_the_service(hass, ws, manager):
    await manager.habits.async_scan()
    assert (await send(ws, "insights/forget", feature="habits"))["result"]["forgotten"]
    assert manager.habits.status()["last_scan"] is None
    await manager.habits.async_scan()
    await hass.services.async_call(
        "homeboard", "forget_learning", {"feature": "habits"}, blocking=True
    )
    assert manager.habits.status()["last_scan"] is None


async def test_non_administrators_do_not_see_or_dismiss_automation_ideas(
    hass, home, manager, hass_ws_client, hass_read_only_access_token
):
    await manager.habits.async_scan()
    idea = next(s for s in inbox(manager) if s["id"] == "habit:time:light.hall:on:all")
    kid = await hass_ws_client(hass, hass_read_only_access_token)
    page = (await send(kid, "insights/get"))["result"]
    assert not [s for s in page["suggestions"] if s["kind"] == "automation"]
    assert "habits" not in page["learned"] and "habit:" not in json.dumps(page)
    payload = (await send(kid, "get"))["result"]
    assert payload["settings"]["insights_open"] == 0
    refused = await send(kid, "insights/dismiss", suggestion_id=idea["id"])
    assert not refused["success"] and refused["error"]["code"] == "unauthorized"
    assert idea["id"] in [s["id"] for s in inbox(manager)]  # still there for the administrators
