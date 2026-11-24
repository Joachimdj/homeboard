"""Optional push notifications."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.core import ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.homeboard.const import CONF_STARTER_PROJECT, DOMAIN

from .conftest import add_persons


async def setup_with(hass, **options):
    add_persons(hass, "joachim")
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_STARTER_PROJECT: True}, options=options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def settle(hass, minutes=31):
    """Let the time a new fault waits before it is pushed pass."""
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=minutes))
    await hass.async_block_till_done()


@pytest.fixture
def sent(hass):
    calls: list[ServiceCall] = []

    async def handler(call: ServiceCall) -> None:
        calls.append(call)

    hass.services.async_register("notify", "mobile_app_phone", handler)
    hass.services.async_register("notify", "other", handler)
    return calls


async def test_done_notification(hass, sent):
    manager = await setup_with(
        hass, notify_services=["notify.mobile_app_phone", "other"], notify_done=True
    )
    issue, _ = manager.create_issue("HOME", "Take out the bins")
    manager.move_issue(issue["id"], "Done")
    await hass.async_block_till_done()
    assert len(sent) == 2
    assert (
        sent[0].data["title"] == "Done: HOME-1" and sent[0].data["message"] == "Take out the bins"
    )
    assert sent[0].data["data"] == {"url": "/homeboard?issue=HOME-1", "tag": "homeboard-HOME-1"}


async def test_overdue_and_due_soon_notifications(hass, sent, freezer):
    manager = await setup_with(
        hass, notify_services=["mobile_app_phone"], notify_overdue=True, notify_due_soon=True
    )
    freezer.move_to("2026-12-01 12:00:00+01:00")
    manager.create_issue("HOME", "Soon", due="2026-12-02")
    manager.create_issue("HOME", "Late", due="2026-11-01")
    manager.async_tick()
    await hass.async_block_till_done()
    titles = sorted(c.data["title"] for c in sent)
    assert titles == ["Due soon: HOME-1", "Overdue: HOME-2"]
    assert "(due 2026-11-01)" in next(
        c.data["message"] for c in sent if c.data["title"].startswith("Overdue")
    )
    assert any(c.data["message"] == "Soon (due 2026-12-02)" for c in sent)


async def test_only_enabled_events_notify(hass, sent):
    manager = await setup_with(hass, notify_services=["mobile_app_phone"], notify_overdue=True)
    issue, _ = manager.create_issue("HOME", "x")
    manager.move_issue(issue["id"], "Done")
    await hass.async_block_till_done()
    assert sent == []


async def test_nothing_is_sent_without_services(hass, sent):
    manager = await setup_with(hass, notify_done=True)
    issue, _ = manager.create_issue("HOME", "x")
    manager.move_issue(issue["id"], "Done")
    await hass.async_block_till_done()
    assert sent == []


async def test_new_high_priority_auto_issues_notify_but_other_creations_do_not(hass, sent):
    manager = await setup_with(hass, notify_services=["mobile_app_phone"], notify_health=True)
    manager.create_issue("HOME", "Manual high", priority="high")
    manager.create_issue("HOME", "Auto low", priority="low", source="health")
    manager.create_issue("HOME", "Auto high", priority="high", source="health")
    await hass.async_block_till_done()
    await settle(hass)
    assert [c.data["message"] for c in sent] == ["Auto high"]
    assert sent[0].data["title"] == "Needs attention: HOME-3"


async def test_a_failing_notify_service_is_logged_not_raised(hass, caplog):
    async def broken(call: ServiceCall) -> None:
        raise HomeAssistantError("phone is asleep")

    hass.services.async_register("notify", "mobile_app_phone", broken)
    manager = await setup_with(hass, notify_services=["mobile_app_phone"], notify_done=True)
    issue, _ = manager.create_issue("HOME", "x")
    manager.move_issue(issue["id"], "Done")
    await hass.async_block_till_done()
    assert "Could not send notification through notify.mobile_app_phone" in caplog.text


async def test_a_new_fault_is_pushed_only_if_it_is_still_open_after_the_settling_time(hass, sent):
    manager = await setup_with(hass, notify_services=["mobile_app_phone"], notify_health=True)
    gone, _ = manager.create_issue("HOME", "Blinked", priority="high", source="health")
    deleted, _ = manager.create_issue("HOME", "Removed", priority="high", source="health")
    stays, _ = manager.create_issue("HOME", "Stays", priority="high", source="health")
    await settle(hass, 29)
    assert sent == []  # nothing before the time is up
    manager.resolve_automatically(gone["id"], "Resolved automatically")
    manager.delete_issue(deleted["id"])
    await settle(hass, 31)
    assert [c.data["message"] for c in sent] == ["Stays"] and stays["key"] in sent[0].data["title"]
    await settle(hass, 120)
    assert len(sent) == 1  # once only


async def test_a_pending_fault_push_is_dropped_when_the_integration_unloads(hass, sent):
    manager = await setup_with(hass, notify_services=["mobile_app_phone"], notify_health=True)
    manager.create_issue("HOME", "Late", priority="high", source="health")
    [entry] = hass.config_entries.async_entries(DOMAIN)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await settle(hass)
    assert sent == []


async def test_the_scanner_closing_a_fault_is_not_announced_but_a_person_closing_it_is(hass, sent):
    manager = await setup_with(hass, notify_services=["mobile_app_phone"], notify_done=True)
    auto, _ = manager.create_issue("HOME", "Went away", source="health")
    manager.resolve_automatically(auto["id"], "Resolved automatically")
    await hass.async_block_till_done()
    assert sent == []
    mine, _ = manager.create_issue("HOME", "Fixed by me", source="health")
    manager.move_issue(mine["id"], "Done", actor="person.joachim", source="ui")
    await hass.async_block_till_done()
    assert [c.data["message"] for c in sent] == ["Fixed by me"]
