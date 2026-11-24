"""Per-person push notifications and the digest."""

from __future__ import annotations

from datetime import time, timedelta

import pytest
from homeassistant.core import ServiceCall
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.homeboard import presence
from custom_components.homeboard.const import CONF_STARTER_PROJECT, DOMAIN

from .conftest import add_persons

NOON = "2026-12-01 12:00:00+01:00"


async def boot(hass, **options):
    add_persons(hass, "joachim", "padmaja")
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_STARTER_PROJECT: True}, options=options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


@pytest.fixture
def sent(hass):
    calls: list[ServiceCall] = []

    async def handler(call: ServiceCall) -> None:
        calls.append(call)

    for name in ("mobile_app_joachim_phone", "mobile_app_padmaja_phone", "other"):
        hass.services.async_register("notify", name, handler)
    return calls


def mapping():
    return {
        "person_notify": {
            "person.joachim": ["mobile_app_joachim_phone"],
            "person.padmaja": "notify.mobile_app_padmaja_phone",
        }
    }


async def test_assignment_notifies_the_new_assignee_only_and_never_yourself(hass, sent, freezer):
    freezer.move_to(NOON)
    manager = await boot(hass, **mapping())
    issue, _ = manager.create_issue("HOME", "Fix the gate")
    manager.update_issue(issue["id"], assignee="person.padmaja", actor="person.joachim")
    manager.update_issue(
        issue["id"], assignee="person.joachim", actor="person.joachim"
    )  # self-assign: silent
    await hass.async_block_till_done()
    assert len(sent) == 1
    call = sent[0]
    assert call.data["title"] == "Assigned to you: HOME-1" and "Joachim" in call.data["message"]
    assert call.data["data"] == {
        "url": "/homeboard?issue=HOME-1",
        "tag": "homeboard-HOME-1",
        "group": "homeboard",
    }


async def test_comment_goes_to_assignee_and_reporter_but_not_the_author(hass, sent, freezer):
    freezer.move_to(NOON)
    manager = await boot(hass, **mapping())
    issue, _ = manager.create_issue("HOME", "x", actor="person.joachim", assignee="person.padmaja")
    manager.add_comment(issue["id"], "I looked at it", actor="person.padmaja")
    await hass.async_block_till_done()
    assert [c.service for c in sent] == ["mobile_app_joachim_phone"]
    assert (
        sent[0].data["title"] == "Padmaja commented on HOME-1"
        and "I looked at it" in sent[0].data["message"]
    )
    sent.clear()
    manager.add_comment(issue["id"], "from the automation")  # no actor: both are told
    await hass.async_block_till_done()
    assert sorted(c.service for c in sent) == [
        "mobile_app_joachim_phone",
        "mobile_app_padmaja_phone",
    ]


async def test_the_scanners_own_comments_are_not_pushed(hass, sent, freezer):
    freezer.move_to(NOON)
    manager = await boot(hass, **mapping())
    issue, _ = manager.create_issue(
        "HOME", "Gate is offline", assignee="person.joachim", source="health"
    )
    manager.resolve_automatically(issue["id"], "Resolved automatically: no longer detected.")
    manager.reopen_automatically(issue["id"], "Problem is back.")
    await hass.async_block_till_done()
    assert sent == []
    manager.add_comment(issue["id"], "Looked at it", actor="person.padmaja")  # people still count
    await hass.async_block_till_done()
    assert [c.service for c in sent] == ["mobile_app_joachim_phone"]


async def test_deadlines_and_reporter_done(hass, sent, freezer):
    freezer.move_to(NOON)
    manager = await boot(hass, **mapping())
    manager.create_issue("HOME", "Late", due="2026-11-01", assignee="person.padmaja")
    manager.create_issue("HOME", "Soon", due="2026-12-02", assignee="person.joachim")
    manager.create_issue("HOME", "Nobody", due="2026-11-01")
    manager.async_tick()
    await hass.async_block_till_done()
    assert sorted((c.service, c.data["title"]) for c in sent) == [
        ("mobile_app_joachim_phone", "Due soon: HOME-2"),
        ("mobile_app_padmaja_phone", "Overdue: HOME-1"),
    ]
    sent.clear()
    done, _ = manager.create_issue("HOME", "Reported", actor="person.joachim")
    manager.move_issue(done["id"], "Done", actor="person.padmaja")
    manager.move_issue(
        manager.create_issue("HOME", "Mine", actor="person.joachim")[0]["id"],
        "Done",
        actor="person.joachim",
    )
    await hass.async_block_till_done()
    assert [(c.service, c.data["title"]) for c in sent] == [
        ("mobile_app_joachim_phone", "Done: HOME-4")
    ]
    assert "by Padmaja" in sent[0].data["message"]


async def test_switches_turn_pushes_off(hass, sent, freezer):
    freezer.move_to(NOON)
    manager = await boot(
        hass,
        **mapping(),
        push_assigned=False,
        push_comment=False,
        push_overdue=False,
        push_reported_done=False,
    )
    issue, _ = manager.create_issue("HOME", "x", actor="person.joachim", due="2020-01-01")
    manager.update_issue(issue["id"], assignee="person.padmaja", actor="person.joachim")
    manager.add_comment(issue["id"], "hi", actor="person.padmaja")
    manager.move_issue(issue["id"], "Done", actor="person.padmaja")
    manager.async_tick()
    await hass.async_block_till_done()
    assert sent == []


async def test_people_without_a_phone_are_skipped(hass, sent, freezer):
    freezer.move_to(NOON)
    manager = await boot(hass)  # nothing mapped, nothing detectable
    issue, _ = manager.create_issue("HOME", "x")
    manager.update_issue(issue["id"], assignee="person.padmaja", actor="person.joachim")
    await hass.async_block_till_done()
    assert sent == []


async def test_phone_is_detected_from_the_device_tracker(hass, sent, freezer):
    freezer.move_to(NOON)
    manager = await boot(hass)
    mobile = MockConfigEntry(domain="mobile_app", data={"device_name": "Padmaja Mobile"})
    mobile.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "device_tracker",
        "mobile_app",
        "p1",
        config_entry=mobile,
        suggested_object_id="padmaja_phone",
    )
    registry.async_get_or_create(
        "device_tracker", "other_platform", "p2", suggested_object_id="router"
    )
    hass.services.async_register("notify", "mobile_app_padmaja_mobile", lambda call: None)
    hass.states.async_set(
        "person.padmaja",
        "home",
        {
            "friendly_name": "Padmaja",
            "user_id": "user-1",
            "device_trackers": [
                "device_tracker.padmaja_phone",
                "device_tracker.router",
                "device_tracker.gone",
            ],
        },
    )
    assert manager.push.services_for("person.padmaja") == ["mobile_app_padmaja_mobile"]
    assert manager.push.services_for("person.joachim") == []
    assert manager.push.detect_services("person.ghost") == []
    hass.services.async_remove("notify", "mobile_app_padmaja_mobile")
    assert (
        manager.push.services_for("person.padmaja") == []
    )  # a service that does not exist is not used


async def test_quiet_hours_hold_back_then_deliver_one_push(hass, sent, freezer):
    freezer.move_to("2026-12-01 23:30:00+01:00")
    manager = await boot(hass, **mapping())
    issue, _ = manager.create_issue("HOME", "Night task")
    manager.update_issue(issue["id"], assignee="person.padmaja", actor="person.joachim")
    await hass.async_block_till_done()
    assert sent == []  # 23:30 is inside the default quiet hours
    freezer.move_to("2026-12-02 07:05:00+01:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert [c.data["title"] for c in sent] == ["Assigned to you: HOME-1"]
    sent.clear()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=2))
    await hass.async_block_till_done()
    assert sent == []  # delivered once only


async def test_many_queued_pushes_are_batched_and_urgent_ones_skip_the_queue(hass, sent, freezer):
    freezer.move_to("2026-12-01 23:30:00+01:00")
    manager = await boot(hass, **mapping())
    for n in range(5):
        issue, _ = manager.create_issue("HOME", f"Task {n}")
        manager.update_issue(issue["id"], assignee="person.padmaja", actor="person.joachim")
    urgent, _ = manager.create_issue("HOME", "Fire", priority="highest")
    manager.update_issue(urgent["id"], assignee="person.padmaja", actor="person.joachim")
    security, _ = manager.create_issue("HOME", "Door open", labels=["security"])
    manager.update_issue(security["id"], assignee="person.padmaja", actor="person.joachim")
    await hass.async_block_till_done()
    assert sorted(c.data["title"] for c in sent) == [
        "Assigned to you: HOME-6",
        "Assigned to you: HOME-7",
    ]
    sent.clear()
    freezer.move_to("2026-12-02 08:00:00+01:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(sent) == 1 and sent[0].data["title"] == "5 updates on the board"
    assert sent[0].data["data"]["tag"] == "homeboard-batch" and "HOME-5" in sent[0].data["message"]


async def test_away_people_wait_when_the_rhythm_learner_is_on(hass, sent, freezer):
    freezer.move_to(NOON)
    manager = await boot(hass, **mapping(), learn_rhythm=True)
    hass.states.async_set(
        "person.padmaja", "not_home", {"friendly_name": "Padmaja", "user_id": "user-1"}
    )
    issue, _ = manager.create_issue("HOME", "x")
    manager.update_issue(issue["id"], assignee="person.padmaja", actor="person.joachim")
    await hass.async_block_till_done()
    assert sent == []
    hass.states.async_set(
        "person.padmaja", "home", {"friendly_name": "Padmaja", "user_id": "user-1"}
    )
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=2))
    await hass.async_block_till_done()
    assert len(sent) == 1
    # without the learner the same push goes out at once
    manager.options = {**mapping()}
    hass.states.async_set(
        "person.padmaja", "not_home", {"friendly_name": "Padmaja", "user_id": "user-1"}
    )
    sent.clear()
    other, _ = manager.create_issue("HOME", "y")
    manager.update_issue(other["id"], assignee="person.padmaja", actor="person.joachim")
    await hass.async_block_till_done()
    assert [c.data["title"] for c in sent] == ["Assigned to you: HOME-2"]


async def test_digest_at_the_chosen_time_once_a_day(hass, sent, freezer):
    freezer.move_to("2026-12-01 07:00:00+01:00")
    manager = await boot(hass, **mapping(), digest_enabled=True, digest_time="07:30")
    manager.create_issue("HOME", "Overdue thing", assignee="person.padmaja", due="2026-11-01")
    manager.create_issue("HOME", "Soon thing", assignee="person.padmaja", due="2026-12-02")
    manager.create_issue("HOME", "Plain thing", assignee="person.padmaja")
    manager.create_issue("HOME", "Not hers", assignee="person.joachim")
    await hass.async_block_till_done()
    sent.clear()
    freezer.move_to("2026-12-01 07:31:00+01:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    digests = [c for c in sent if c.data["title"] == "Your board today"]
    by_service = {c.service: c for c in digests}
    padmaja = by_service["mobile_app_padmaja_phone"]
    assert padmaja.data["title"] == "Your board today"
    assert padmaja.data["message"].startswith("3 open, 1 overdue, 1 due soon\nHOME-1 Overdue thing")
    assert "Not hers" not in padmaja.data["message"] and "mobile_app_joachim_phone" in by_service
    sent.clear()
    freezer.move_to("2026-12-01 07:40:00+01:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert [c for c in sent if c.data["title"] == "Your board today"] == []  # once a day
    freezer.move_to("2026-12-02 07:31:00+01:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len([c for c in sent if c.data["title"] == "Your board today"]) == 2


async def test_digest_skips_when_nothing_is_open_off_by_default_and_after_a_restart_window(
    hass, sent, freezer
):
    freezer.move_to("2026-12-01 09:00:00+01:00")
    manager = await boot(hass, **mapping(), digest_enabled=True, digest_time="07:30")
    manager.create_issue("HOME", "x", assignee="person.padmaja")
    sent.clear()
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert sent == []  # 07:30 passed more than 30 minutes ago: not sent late
    assert manager.push.send_digest("person.joachim") is False  # nothing assigned
    assert manager.push.send_digest("person.ghost") is False
    manager.options = {}
    manager.push._digest_sent.clear()
    freezer.move_to("2026-12-02 07:40:00+01:00")
    manager.push.send_due_digests()
    await hass.async_block_till_done()
    assert sent == []  # digest_enabled is off


async def test_learned_digest_time_wins_over_the_option_and_the_service_sends_now(
    hass, sent, freezer
):
    freezer.move_to(NOON)
    manager = await boot(hass, **mapping(), digest_time="07:30")
    manager.learning_data["digest_times"] = {"person.padmaja": "08:15"}
    assert manager.push.digest_time("person.padmaja") == time(8, 15)
    assert manager.push.digest_time("person.joachim") == time(7, 30)
    manager.create_issue("HOME", "x", assignee="person.padmaja")
    result = await hass.services.async_call(
        DOMAIN, "send_digest", {"person": "person.padmaja"}, blocking=True, return_response=True
    )
    assert result == {"sent": ["person.padmaja"]}
    everyone = await hass.services.async_call(
        DOMAIN, "send_digest", {}, blocking=True, return_response=True
    )
    assert everyone == {"sent": ["person.padmaja"]}
    await hass.async_block_till_done()
    assert len(sent) == 2


async def test_presence_helpers(hass):
    hass.states.async_set("zone.home", "0", {"latitude": 55.0, "longitude": 12.0, "radius": 100})
    from homeassistant.core import State

    assert presence.is_home(hass, None) is None
    assert presence.is_home(hass, State("person.a", "unknown")) is None
    assert presence.is_home(hass, State("person.a", "home")) is True
    assert presence.is_home(hass, State("person.a", "not_home")) is False
    inside = State("person.a", "House", {"latitude": 55.0003, "longitude": 12.0})
    outside = State("person.a", "Work", {"latitude": 55.1, "longitude": 12.0})
    assert presence.is_home(hass, inside) is True and presence.is_home(hass, outside) is False
    hass.states.async_remove("zone.home")
    assert presence.is_home(hass, inside) is False
    assert presence.parse_hhmm("07:45", time(1, 0)) == time(7, 45)
    assert presence.parse_hhmm("nonsense", time(1, 0)) == time(1, 0)
    assert presence.in_quiet_hours(
        time(23, 0), time(22, 0), time(7, 0)
    ) and presence.in_quiet_hours(time(3, 0), time(22, 0), time(7, 0))
    assert not presence.in_quiet_hours(time(12, 0), time(22, 0), time(7, 0))
    assert presence.in_quiet_hours(
        time(13, 0), time(12, 0), time(14, 0)
    ) and not presence.in_quiet_hours(time(1, 0), time(0, 0), time(0, 0))
