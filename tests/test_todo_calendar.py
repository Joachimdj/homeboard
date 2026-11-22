"""The todo list (Assist) and calendar entities."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

TODO = "todo.home"
CAL = "calendar.home_due_dates"


async def items(hass):
    result = await hass.services.async_call(
        "todo", "get_items", {"entity_id": TODO}, blocking=True, return_response=True
    )
    return result[TODO]["items"]


async def test_add_item_creates_an_issue_like_assist_does(hass, manager):
    await hass.services.async_call(
        "todo", "add_item", {"entity_id": TODO, "item": "Buy light bulbs"}, blocking=True
    )
    issue = next(iter(manager.issues.values()))
    assert issue["summary"] == "Buy light bulbs" and issue["source"] == "todo"
    assert issue["key"] == "HOME-1" and manager.category(issue) == "todo"
    assert hass.states.get(TODO).state == "1"
    listed = await items(hass)
    assert listed[0]["summary"] == "Buy light bulbs" and listed[0]["status"] == "needs_action"


async def test_add_item_with_due_and_description(hass, manager):
    await hass.services.async_call(
        "todo",
        "add_item",
        {"entity_id": TODO, "item": "Dated", "due_date": "2031-05-05", "description": "details"},
        blocking=True,
    )
    await hass.services.async_call(
        "todo",
        "add_item",
        {"entity_id": TODO, "item": "Timed", "due_datetime": "2031-05-05 18:30:00"},
        blocking=True,
    )
    dated, timed = sorted(manager.issues.values(), key=lambda i: i["number"])
    assert dated["due"] == "2031-05-05" and dated["description"] == "details"
    assert timed["due"].startswith("2031-05-05T18:30:00")
    listed = await items(hass)
    assert {i["summary"]: i.get("due") for i in listed}["Dated"] == "2031-05-05"


async def test_complete_and_uncomplete_move_the_issue(hass, manager):
    await hass.services.async_call(
        "todo", "add_item", {"entity_id": TODO, "item": "Chore"}, blocking=True
    )
    issue = next(iter(manager.issues.values()))
    uid = issue["id"]
    await hass.services.async_call(
        "todo",
        "update_item",
        {"entity_id": TODO, "item": uid, "status": "completed"},
        blocking=True,
    )
    assert manager.category(issue) == "done" and issue["resolved"] is not None
    assert hass.states.get(TODO).state == "0"
    assert (await items(hass))[0]["status"] == "completed"
    await hass.services.async_call(
        "todo",
        "update_item",
        {"entity_id": TODO, "item": uid, "status": "needs_action"},
        blocking=True,
    )
    assert manager.category(issue) == "todo"


async def test_rename_and_clear_due(hass, manager):
    await hass.services.async_call(
        "todo",
        "add_item",
        {"entity_id": TODO, "item": "Old", "due_date": "2031-01-01"},
        blocking=True,
    )
    issue = next(iter(manager.issues.values()))
    await hass.services.async_call(
        "todo",
        "update_item",
        {"entity_id": TODO, "item": issue["id"], "rename": "New", "due_date": "2031-02-02"},
        blocking=True,
    )
    assert issue["summary"] == "New" and issue["due"] == "2031-02-02"


async def test_remove_item_deletes_the_issue(hass, manager):
    await hass.services.async_call(
        "todo", "add_item", {"entity_id": TODO, "item": "Gone"}, blocking=True
    )
    uid = next(iter(manager.issues))
    await hass.services.async_call(
        "todo", "remove_item", {"entity_id": TODO, "item": [uid]}, blocking=True
    )
    assert manager.issues == {}


async def test_domain_errors_become_validation_errors(hass, manager):
    from homeassistant.components.todo import DATA_COMPONENT, TodoItem

    entity = hass.data[DATA_COMPONENT].get_entity(TODO)
    with pytest.raises(ServiceValidationError):
        await entity.async_create_todo_item(TodoItem(summary=" "))
    with pytest.raises(ServiceValidationError):
        await entity.async_update_todo_item(TodoItem(uid="missing", summary="x"))
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "todo", "remove_item", {"entity_id": TODO, "item": ["missing"]}, blocking=True
        )


async def test_list_order_and_done_window(hass, manager, freezer):
    freezer.move_to("2026-12-01 12:00:00+01:00")
    first, _ = manager.create_issue("HOME", "first")
    manager.create_issue("HOME", "in progress", status="In progress")
    manager.create_issue("HOME", "recent done", status="Done")
    freezer.move_to("2026-12-20 12:00:00+01:00")
    manager.create_issue("HOME", "later", status="To do")
    manager.create_issue("HOME", "fresh done", status="Done")
    manager.async_tick()
    await hass.async_block_till_done()
    summaries = [i["summary"] for i in await items(hass)]
    # open ones in board order first; "recent done" is older than 7 days and is dropped
    assert summaries == ["first", "later", "in progress", "fresh done"]
    assert first["status"]


async def test_calendar_events_for_due_dates(hass, manager, freezer):
    freezer.move_to("2026-12-01 12:00:00+01:00")
    manager.create_issue("HOME", "All day", due="2026-12-03")
    manager.create_issue(
        "HOME", "Timed", due="2026-12-02T18:30:00+01:00", description="bring tools"
    )
    manager.create_issue("HOME", "Done", due="2026-12-02", status="Done")
    manager.create_issue("HOME", "Undated")
    await hass.async_block_till_done()
    start = dt_util.parse_datetime("2026-12-01T00:00:00+01:00")
    result = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": CAL,
            "start_date_time": start.isoformat(),
            "end_date_time": (start + timedelta(days=10)).isoformat(),
        },
        blocking=True,
        return_response=True,
    )
    events = result[CAL]["events"]
    assert [e["summary"] for e in events] == ["HOME-2 Timed", "HOME-1 All day"]
    assert (
        events[0]["start"].startswith("2026-12-02T18:30")
        and events[0]["description"] == "bring tools"
    )
    assert events[1]["start"] == "2026-12-03" and events[1]["end"] == "2026-12-04"
    state = hass.states.get(CAL)
    assert state.attributes["message"] == "HOME-2 Timed"
    # outside the window nothing is returned
    far = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": CAL,
            "start_date_time": "2030-01-01T00:00:00+01:00",
            "end_date_time": "2030-02-01T00:00:00+01:00",
        },
        blocking=True,
        return_response=True,
    )
    assert far[CAL]["events"] == []


async def test_calendar_has_no_event_when_nothing_is_due(hass, manager):
    manager.create_issue("HOME", "Undated")
    await hass.async_block_till_done()
    assert hass.states.get(CAL).state == "off"
    manager.create_issue("HOME", "Past", due="2001-01-01")
    await hass.async_block_till_done()
    assert hass.states.get(CAL).state == "off"
