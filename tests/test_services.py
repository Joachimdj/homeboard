"""The homeboard.* services."""

from __future__ import annotations

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import ServiceValidationError

from custom_components.homeboard.const import DOMAIN


async def call(hass, service, data, *, response=True, context=None):
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=response, context=context
    )


async def test_all_services_are_registered(hass, manager):
    names = set(hass.services.async_services_for_domain(DOMAIN))
    assert {
        "create_issue",
        "update_issue",
        "move_issue",
        "assign_issue",
        "add_comment",
        "delete_issue",
        "quick_add",
        "create_project",
        "update_project",
        "add_status",
        "update_status",
        "remove_status",
        "create_recurring",
        "update_recurring",
        "delete_recurring",
        "run_recurring",
        "scan_health",
    } <= names


async def test_create_issue_returns_key_and_dedupes(hass, manager):
    result = await call(
        hass,
        "create_issue",
        {
            "project": "HOME",
            "summary": "Battery low",
            "priority": "high",
            "type": "bug",
            "assignee": "person.joachim",
            "labels": ["battery"],
            "due": "2031-01-01",
            "dedupe_key": "bat",
            "source": "sensor",
        },
    )
    assert result == {"key": "HOME-1", "id": result["id"], "created": True}
    issue = manager.issues[result["id"]]
    assert (
        issue["source"] == "sensor"
        and issue["assignee"] == "person.joachim"
        and issue["due"] == "2031-01-01"
    )
    again = await call(
        hass, "create_issue", {"project": "HOME", "summary": "Battery low", "dedupe_key": "bat"}
    )
    assert again["created"] is False and again["key"] == "HOME-1"


async def test_create_issue_with_naive_and_aware_datetimes(hass, manager):
    a = await call(
        hass, "create_issue", {"project": "HOME", "summary": "a", "due": "2031-01-01 18:30:00"}
    )
    b = await call(
        hass,
        "create_issue",
        {"project": "HOME", "summary": "b", "due": "2031-01-01T18:30:00+00:00"},
    )
    assert manager.issues[a["id"]]["due"] == "2031-01-01T18:30:00+01:00"
    assert manager.issues[b["id"]]["due"] == "2031-01-01T18:30:00+00:00"


async def test_actor_comes_from_the_calling_user(hass, manager):
    context = Context(user_id="user-1")
    result = await call(hass, "create_issue", {"project": "HOME", "summary": "x"}, context=context)
    assert manager.issues[result["id"]]["reporter"] == "person.padmaja"


async def test_update_move_assign_comment_delete(hass, manager):
    made = await call(hass, "create_issue", {"project": "HOME", "summary": "x", "dedupe_key": "k"})
    ref = {"project": "HOME", "dedupe_key": "k"}
    await call(
        hass,
        "update_issue",
        {
            **ref,
            "summary": "y",
            "status": "In progress",
            "assignee": "person.padmaja",
            "labels": ["a"],
            "due": "2031-02-02",
            "parent": "",
        },
    )
    issue = manager.issues[made["id"]]
    assert (
        issue["summary"] == "y"
        and issue["assignee"] == "person.padmaja"
        and manager.category(issue) == "in_progress"
    )
    await call(hass, "assign_issue", {"issue": "HOME-1", "assignee": ""})
    assert issue["assignee"] is None
    await call(hass, "assign_issue", {"issue": "HOME-1", "assignee": "person.joachim"})
    assert issue["assignee"] == "person.joachim"
    await call(hass, "move_issue", {"issue": "HOME-1", "status": "Done", "position": "top"})
    assert issue["resolved"] is not None
    await call(hass, "add_comment", {"issue": "HOME-1", "text": "all good"})
    assert issue["comments"][0]["text"] == "all good"
    assert await call(hass, "delete_issue", {"issue": "HOME-1"}, response=False) is None
    assert manager.issues == {}


async def test_errors_become_validation_errors(hass, manager):
    for service, data in (
        ("create_issue", {"project": "NOPE", "summary": "x"}),
        ("create_issue", {"project": "HOME", "summary": "x", "due": "garbage"}),
        ("move_issue", {"issue": "HOME-9", "status": "Done"}),
        ("update_issue", {"summary": "no reference"}),
    ):
        with pytest.raises(ServiceValidationError):
            await call(hass, service, data)


async def test_schema_rejects_bad_values(hass, manager):
    import voluptuous as vol

    for data in (
        {"project": "HOME", "summary": "x", "priority": "p0"},
        {"project": "HOME", "summary": "x", "assignee": "light.kitchen"},
        {"project": "HOME"},
    ):
        with pytest.raises(vol.Invalid):
            await call(hass, "create_issue", data)


async def test_quick_add_service(hass, manager):
    result = await call(
        hass, "quick_add", {"text": "bug: gate @padmaja !high due 2031-03-03", "source": "siri"}
    )
    assert result["key"] == "HOME-1" and result["parsed"]["assignee"] == "person.padmaja"
    issue = manager.issues[result["id"]]
    assert issue["type"] == "bug" and issue["source"] == "siri"


async def test_project_and_status_services(hass, manager):
    project = await call(
        hass,
        "create_project",
        {"key": "CAR", "name": "Car", "template": "blank", "lead": "person.joachim"},
    )
    assert project["key"] == "CAR"
    await call(
        hass,
        "update_project",
        {"project": "CAR", "name": "Garage", "default_assignee": "person.padmaja", "lead": ""},
    )
    car = manager.resolve_project("CAR")
    assert (
        car["name"] == "Garage"
        and car["lead"] is None
        and car["default_assignee"] == "person.padmaja"
    )
    status = await call(
        hass,
        "add_status",
        {"project": "CAR", "name": "Ordered", "category": "in_progress", "wip": 2, "position": 1},
    )
    assert status["name"] == "Ordered"
    updated = await call(
        hass,
        "update_status",
        {"project": "CAR", "status": "Ordered", "name": "On order", "backlog": False},
    )
    assert updated["name"] == "On order"
    assert (
        await call(hass, "remove_status", {"project": "CAR", "status": "On order"}, response=False)
        is None
    )
    assert [s["name"] for s in car["statuses"]] == ["To do", "Done"]


async def test_recurring_services(hass, manager):
    rec = await call(
        hass,
        "create_recurring",
        {
            "project": "HOME",
            "summary": "Bins",
            "repeat": {"unit": "week", "weekdays": [2]},
            "next_due": "2099-01-07",
            "assignee": "person.padmaja",
            "create_days_before": 1,
        },
    )
    assert rec["next_due"] == "2099-01-07"
    changed = await call(
        hass,
        "update_recurring",
        {
            "recurring_id": rec["id"],
            "summary": "Bins out",
            "next_due": "2099-01-14",
            "assignee": "",
        },
    )
    assert changed["next_due"] == "2099-01-14"
    stored = manager.recurring[rec["id"]]
    assert stored["summary"] == "Bins out" and stored["assignee"] is None
    run = await call(hass, "run_recurring", {"recurring_id": rec["id"]})
    assert run["created"] is True and run["key"] == "HOME-1"
    skipped = await call(hass, "run_recurring", {"recurring_id": rec["id"]})
    assert skipped == {"created": False}
    await call(hass, "delete_recurring", {"recurring_id": rec["id"]}, response=False)
    assert manager.recurring == {}


async def test_services_fail_cleanly_when_not_loaded(hass, entry):
    from .conftest import setup

    await setup(hass, entry)
    await hass.config_entries.async_unload(entry.entry_id)
    with pytest.raises(ServiceValidationError, match="not set up"):
        await call(hass, "create_issue", {"project": "HOME", "summary": "x"})
