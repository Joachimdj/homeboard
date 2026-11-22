"""The data manager: projects, statuses, issues, events, persistence and the clock."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.homeboard import const
from custom_components.homeboard.data import UNSET
from custom_components.homeboard.model import ConflictError, InvalidError, NotFoundError

from .conftest import setup, status_id

# ------------------------------------------------------------------ projects / statuses


async def test_create_project_validation(manager):
    p = manager.create_project(
        key="car", name="  Car   stuff ", template="software", lead="person.joachim"
    )
    assert p["key"] == "CAR" and p["name"] == "Car stuff" and p["lead"] == "person.joachim"
    assert len(p["statuses"]) == 5
    with pytest.raises(ConflictError):
        manager.create_project(key="CAR", name="Again")
    with pytest.raises(InvalidError):
        manager.create_project(key="x", name="Bad key")
    with pytest.raises(InvalidError):
        manager.create_project(key="NOP", name="Ghost lead", lead="person.ghost")
    custom = manager.create_project(
        key="CUS",
        name="Custom",
        statuses=[{"name": "Open", "category": "todo"}, {"name": "Shut", "category": "done"}],
    )
    assert [s["name"] for s in custom["statuses"]] == ["Open", "Shut"]
    with pytest.raises(InvalidError):
        manager.create_project(
            key="BAD", name="Bad", statuses=[{"name": "Open", "category": "todo"}]
        )


async def test_project_events_and_update(manager, hass):
    events = async_capture_events(hass, const.EVENT_PROJECT_CHANGED)
    manager.update_project(
        "HOME",
        name="House",
        description="d",
        color="#fff",
        icon="mdi:star",
        lead="person.padmaja",
        default_assignee="person.joachim",
        archived=True,
        labels=["B", "a"],
    )
    project = manager.resolve_project("HOME")
    assert project["name"] == "House" and project["archived"] and project["labels"] == ["b", "a"]
    assert project["default_assignee"] == "person.joachim"
    with pytest.raises(InvalidError):
        manager.update_project("HOME", key="NEW")
    manager.update_project("HOME", name=UNSET)  # untouched
    await hass.async_block_till_done()
    assert [e.data["action"] for e in events] == ["updated", "updated"]
    with pytest.raises(NotFoundError):
        manager.resolve_project("NOPE")


async def test_archived_project_rejects_new_issues(manager):
    manager.update_project("HOME", archived=True)
    with pytest.raises(InvalidError):
        manager.create_issue("HOME", "nope")


async def test_status_management(manager):
    todo = status_id(manager, "To do")
    done = status_id(manager, "Done")
    new = manager.add_status("HOME", name="Review", category="in_progress", wip=2, position=2)
    names = [s["name"] for s in manager.resolve_project("HOME")["statuses"]]
    assert names == ["Backlog", "To do", "Review", "In progress", "Done"]
    with pytest.raises(ConflictError):
        manager.add_status("HOME", name="review", category="todo")
    with pytest.raises(InvalidError):
        manager.add_status("HOME", name="x", category="weird")

    manager.update_status("HOME", "Review", name="QA", wip=0, backlog=True)
    status = manager.resolve_project("HOME")["statuses"][2]
    assert status["name"] == "QA" and status["wip"] is None and status["backlog"] is True
    with pytest.raises(InvalidError):
        manager.update_status("HOME", "QA", colour="red")
    with pytest.raises(InvalidError):
        manager.update_status("HOME", done, category="todo")  # no done status would be left

    ids = [s["id"] for s in manager.resolve_project("HOME")["statuses"]]
    manager.reorder_statuses("HOME", list(reversed(ids)))
    assert [s["id"] for s in manager.resolve_project("HOME")["statuses"]] == list(reversed(ids))
    with pytest.raises(InvalidError):
        manager.reorder_statuses("HOME", ids[:-1])

    issue, _ = manager.create_issue("HOME", "stuck", status=new["id"])
    with pytest.raises(ConflictError):
        manager.remove_status("HOME", new["id"])
    with pytest.raises(InvalidError):
        manager.remove_status("HOME", new["id"], move_to=new["id"])
    manager.remove_status("HOME", new["id"], move_to=todo)
    assert manager.issues[issue["id"]]["status"] == todo
    with pytest.raises(NotFoundError):
        manager.update_status("HOME", "gone")


async def test_changing_status_category_updates_resolved(manager):
    prog = status_id(manager, "In progress")
    issue, _ = manager.create_issue("HOME", "x", status=prog)
    assert issue["resolved"] is None
    manager.update_status("HOME", prog, category="done")
    assert issue["resolved"] is not None
    manager.update_status("HOME", prog, category="in_progress")
    assert issue["resolved"] is None


async def test_remove_status_into_done_resolves(manager):
    prog = status_id(manager, "In progress")
    issue, _ = manager.create_issue("HOME", "x", status=prog)
    manager.remove_status("HOME", prog, move_to=status_id(manager, "Done"))
    assert issue["resolved"] is not None


async def test_delete_project_removes_everything(manager, hass):
    manager.create_issue("HOME", "a")
    manager.create_recurring("HOME", summary="chore", repeat={"unit": "day"}, next_due="2099-01-01")
    manager.delete_project("HOME")
    assert manager.projects == {} and manager.issues == {} and manager.recurring == {}


# ------------------------------------------------------------------ creating issues


async def test_create_issue_defaults_and_numbering(manager, hass):
    events = async_capture_events(hass, const.EVENT_ISSUE_CREATED)
    a, created = manager.create_issue("HOME", "First", actor="person.joachim", source="ui")
    b, _ = manager.create_issue("home", "Second", labels=["Garden"], priority="high", type="bug")
    assert created and (a["key"], b["key"]) == ("HOME-1", "HOME-2")
    assert a["status"] == status_id(manager, "To do")  # backlog is skipped as default
    assert a["reporter"] == "person.joachim" and a["priority"] == "medium" and a["type"] == "task"
    assert b["rank"] > a["rank"]
    assert manager.resolve_project("HOME")["labels"] == ["garden"]
    manager.delete_issue(b["id"])
    c, _ = manager.create_issue("HOME", "Third")
    assert c["key"] == "HOME-3"  # numbers are never reused
    await hass.async_block_till_done()
    first = events[0].data
    assert first["key"] == "HOME-1" and first["project"] == "HOME" and first["status"] == "To do"
    assert first["actor"] == "person.joachim" and first["url"] == "/homeboard?issue=HOME-1"
    assert a["activity"][0]["kind"] == "created"


async def test_create_issue_validation(manager):
    for kwargs in (
        {"summary": " "},
        {"summary": "x", "type": "chore"},
        {"summary": "x", "priority": "p0"},
        {"summary": "x", "assignee": "person.ghost"},
        {"summary": "x", "due": "soon"},
        {"summary": "x", "status": "nope"},
        {"summary": "x", "on_duplicate": "explode"},
        {"summary": "x", "parent": "HOME-99"},
    ):
        summary = kwargs.pop("summary")
        with pytest.raises((InvalidError, NotFoundError)):
            manager.create_issue("HOME", summary, **kwargs)
    assert manager.issues == {}


async def test_default_assignee_and_explicit_none(manager):
    manager.update_project("HOME", default_assignee="person.padmaja")
    a, _ = manager.create_issue("HOME", "default")
    b, _ = manager.create_issue("HOME", "nobody", assignee=None)
    c, _ = manager.create_issue("HOME", "joachim", assignee="person.joachim")
    assert (a["assignee"], b["assignee"], c["assignee"]) == (
        "person.padmaja",
        None,
        "person.joachim",
    )


async def test_create_in_done_status_is_resolved(manager):
    issue, _ = manager.create_issue("HOME", "already done", status="Done")
    assert issue["resolved"] is not None


async def test_epic_parent_rules(manager):
    epic, _ = manager.create_issue("HOME", "Big", type="epic")
    child, _ = manager.create_issue("HOME", "Small", parent=epic["key"])
    assert child["parent"] == epic["id"]
    other = manager.create_project(key="OTH", name="Other")
    with pytest.raises(InvalidError):
        manager.create_issue(other["id"], "cross", parent=epic["key"])
    with pytest.raises(InvalidError):
        manager.update_issue(epic["id"], parent=epic["id"])
    plain, _ = manager.create_issue("HOME", "plain")
    with pytest.raises(InvalidError):
        manager.update_issue(child["id"], parent=plain["id"])
    with pytest.raises(ConflictError):
        manager.update_issue(epic["id"], type="task")  # still has a child
    manager.delete_issue(epic["id"])
    assert manager.issues[child["id"]]["parent"] is None


# ------------------------------------------------------------------ dedupe


async def test_dedupe_skip_comment_reopen(manager):
    a, created = manager.create_issue("HOME", "Battery low", dedupe_key="bat")
    assert created
    same, created = manager.create_issue("HOME", "Battery low again", dedupe_key="bat")
    assert same["id"] == a["id"] and not created and a["comments"] == []
    again, created = manager.create_issue(
        "HOME", "Still low", dedupe_key="bat", on_duplicate="comment"
    )
    assert again["id"] == a["id"] and not created and a["comments"][0]["text"] == "Still low"

    manager.move_issue(a["id"], "Done")
    fresh, created = manager.create_issue(
        "HOME", "Low again", dedupe_key="bat"
    )  # done -> a new one
    assert created and fresh["id"] != a["id"]
    manager.move_issue(fresh["id"], "Done")
    revived, created = manager.create_issue(
        "HOME", "Low once more", dedupe_key="bat", on_duplicate="reopen"
    )
    assert not created and revived["id"] == fresh["id"]
    assert manager.category(revived) == "todo" and revived["resolved"] is None
    # open one with the key exists, 'reopen' leaves it alone
    open_again, created = manager.create_issue("HOME", "x", dedupe_key="bat", on_duplicate="reopen")
    assert not created and open_again["id"] == fresh["id"]


async def test_resolve_issue_by_key_id_or_dedupe(manager):
    a, _ = manager.create_issue("HOME", "x", dedupe_key="k")
    assert manager.resolve_issue("home-1")["id"] == a["id"]
    assert manager.resolve_issue(a["id"])["id"] == a["id"]
    assert manager.resolve_issue(project="HOME", dedupe_key="k")["id"] == a["id"]
    for call in (
        lambda: manager.resolve_issue("HOME-9"),
        lambda: manager.resolve_issue(project="HOME", dedupe_key="nope"),
        lambda: manager.resolve_issue(),
    ):
        with pytest.raises((NotFoundError, InvalidError)):
            call()


# ------------------------------------------------------------------ updating


async def test_update_issue_records_changes_and_events(manager, hass):
    updated = async_capture_events(hass, const.EVENT_ISSUE_UPDATED)
    assigned = async_capture_events(hass, const.EVENT_ISSUE_ASSIGNED)
    issue, _ = manager.create_issue("HOME", "x")
    manager.update_issue(
        issue["id"],
        actor="person.joachim",
        source="ui",
        summary="y",
        description="d",
        type="bug",
        priority="high",
        assignee="person.padmaja",
        labels=["a"],
        due="2030-01-01",
    )
    await hass.async_block_till_done()
    changes = updated[0].data["changes"]
    assert set(changes) == {
        "summary",
        "description",
        "type",
        "priority",
        "assignee",
        "labels",
        "due",
    }
    assert changes["summary"] == {"from": "x", "to": "y"}
    assert (
        assigned[0].data["to_assignee"] == "person.padmaja"
        and assigned[0].data["from_assignee"] is None
    )
    kinds = [a["kind"] for a in issue["activity"]]
    assert kinds.count("assigned") == 1 and kinds.count("updated") == 6
    # no change -> no event, no churn
    before = len(updated)
    manager.update_issue(issue["id"], summary="y", priority="high")
    await hass.async_block_till_done()
    assert len(updated) == before
    with pytest.raises(InvalidError):
        manager.update_issue(issue["id"], status="done")
    manager.update_issue(issue["id"], assignee=None, due=None, parent=None)
    assert issue["assignee"] is None and issue["due"] is None


async def test_changing_due_resets_notification_flags(manager):
    issue, _ = manager.create_issue("HOME", "x", due="2020-01-01")
    issue["overdue_notified"] = issue["due_soon_notified"] = True
    manager.update_issue(issue["id"], due="2030-01-01")
    assert not issue["overdue_notified"] and not issue["due_soon_notified"]


async def test_archive_via_update(manager):
    issue, _ = manager.create_issue("HOME", "x")
    manager.update_issue(issue["id"], archived=True)
    assert manager.project_issues(manager.resolve_project("HOME")["id"]) == []
    page, total = manager.list_issues(archived=True)
    assert total == 1 and page[0]["id"] == issue["id"]
    assert [a["kind"] for a in issue["activity"]][-1] == "archived"


# ------------------------------------------------------------------ moving


async def test_move_between_statuses_fires_events(manager, hass):
    moved = async_capture_events(hass, const.EVENT_ISSUE_MOVED)
    completed = async_capture_events(hass, const.EVENT_ISSUE_COMPLETED)
    reopened = async_capture_events(hass, const.EVENT_ISSUE_REOPENED)
    issue, _ = manager.create_issue("HOME", "x")
    manager.move_issue(issue["id"], "In progress", actor="person.joachim", source="ui")
    manager.move_issue(issue["id"], "Done")
    assert issue["resolved"] is not None
    manager.move_issue(issue["id"], "To do")
    assert issue["resolved"] is None
    await hass.async_block_till_done()
    assert [(e.data["from_status"], e.data["to_status"]) for e in moved] == [
        ("To do", "In progress"),
        ("In progress", "Done"),
        ("Done", "To do"),
    ]
    assert moved[1].data["to_category"] == "done" and moved[2].data["from_category"] == "done"
    assert len(completed) == 1 and len(reopened) == 1
    assert completed[0].data["key"] == "HOME-1"
    assert [a["kind"] for a in issue["activity"] if a["kind"] in ("completed", "reopened")] == [
        "completed",
        "reopened",
    ]


async def test_move_ordering_before_top_bottom(manager):
    a, _ = manager.create_issue("HOME", "a")
    b, _ = manager.create_issue("HOME", "b")
    c, _ = manager.create_issue("HOME", "c")

    def order():
        todo = status_id(manager, "To do")
        return [
            i["summary"] for i in manager.project_issues(a["project_id"]) if i["status"] == todo
        ]

    assert order() == ["a", "b", "c"]
    manager.move_issue(c["id"], "To do", before=a["id"])
    assert order() == ["c", "a", "b"]
    manager.move_issue(c["id"], "To do", position="bottom")
    assert order() == ["a", "b", "c"]
    manager.move_issue(c["id"], "To do", position="top")
    assert order() == ["c", "a", "b"]
    manager.move_issue(a["id"], "To do", before=None)
    assert order() == ["c", "b", "a"]
    with pytest.raises(InvalidError):
        manager.move_issue(a["id"], "To do", position="middle")
    with pytest.raises(NotFoundError):
        manager.move_issue(a["id"], "Done", before=b["id"])  # b is not in Done


async def test_move_rebalances_when_ranks_run_out(manager):
    issues = [manager.create_issue("HOME", f"i{n}")[0] for n in range(4)]
    issues[1]["rank"] = issues[0]["rank"] + 1  # leave no gap between the first two
    mover = issues[3]
    manager.move_issue(mover["id"], "To do", before=issues[1]["id"])
    todo = status_id(manager, "To do")
    order = [
        i["summary"] for i in manager.project_issues(mover["project_id"]) if i["status"] == todo
    ]
    assert order == ["i0", "i3", "i1", "i2"]
    assert len({i["rank"] for i in manager.issues.values()}) == 4


async def test_moving_in_place_changes_nothing(manager, hass):
    events = async_capture_events(hass, const.EVENT_ISSUE_MOVED)
    a, _ = manager.create_issue("HOME", "a")
    updated = a["updated"]
    manager.move_issue(a["id"], "To do", position="bottom")
    manager.move_issue(a["id"], "To do")
    await hass.async_block_till_done()
    assert events == [] and a["updated"] == updated


async def test_wip_limit_event(manager, hass):
    events = async_capture_events(hass, const.EVENT_WIP_EXCEEDED)
    manager.update_status("HOME", "In progress", wip=1)
    a, _ = manager.create_issue("HOME", "a", status="In progress")
    b, _ = manager.create_issue("HOME", "b")
    manager.move_issue(b["id"], "In progress")
    await hass.async_block_till_done()
    assert len(events) == 1
    assert (
        events[0].data["wip"] == 1
        and events[0].data["count"] == 2
        and events[0].data["status"] == "In progress"
    )
    # the done status never raises WIP events
    manager.update_status("HOME", "Done", wip=1)
    manager.move_issue(a["id"], "Done")
    manager.move_issue(b["id"], "Done")
    await hass.async_block_till_done()
    assert len(events) == 1


# ------------------------------------------------------------------ comments, delete, list


async def test_comments_and_delete(manager, hass):
    commented = async_capture_events(hass, const.EVENT_ISSUE_COMMENTED)
    deleted = async_capture_events(hass, const.EVENT_ISSUE_DELETED)
    issue, _ = manager.create_issue("HOME", "x")
    comment = manager.add_comment(issue["id"], " hello ", actor="person.joachim")
    assert comment["text"] == "hello" and comment["author"] == "person.joachim"
    with pytest.raises(InvalidError):
        manager.add_comment(issue["id"], "  ")
    manager.delete_issue(issue["key"])
    await hass.async_block_till_done()
    assert commented[0].data["comment"]["text"] == "hello"
    assert deleted[0].data["key"] == "HOME-1" and manager.issues == {}


async def test_activity_log_is_capped(manager):
    issue, _ = manager.create_issue("HOME", "x")
    for n in range(150):
        manager.add_comment(issue["id"], f"c{n}")
    assert len(issue["activity"]) == const.ACTIVITY_LIMIT
    assert len(issue["comments"]) == 150


async def test_list_and_search(manager):
    a, _ = manager.create_issue("HOME", "Fix the gate", description="squeaks")
    manager.create_issue("HOME", "Buy milk")
    manager.update_issue(a["id"], archived=True)
    page, total = manager.list_issues()
    assert total == 1 and page[0]["summary"] == "Buy milk"
    assert manager.list_issues(archived=True, query="SQUEAK")[1] == 1
    assert manager.list_issues(project="HOME", query="home-2")[1] == 1
    assert manager.list_issues(limit=0)[0] == []


# ------------------------------------------------------------------ quick add


async def test_quick_add_end_to_end(manager, hass):
    issue, parsed = manager.quick_add(
        "bug: gate squeaks @padmaja !high #garden due 2031-01-02",
        actor="person.joachim",
        source="siri",
    )
    assert issue["summary"] == "gate squeaks" and issue["type"] == "bug"
    assert issue["assignee"] == "person.padmaja" and issue["priority"] == "high"
    assert (
        issue["labels"] == ["garden"] and issue["due"] == "2031-01-02" and issue["source"] == "siri"
    )
    assert parsed.project == "HOME"
    plain, _ = manager.quick_add("just a thing", project="HOME")
    assert plain["assignee"] is None
    other = manager.create_project(key="CAR", name="Car")
    routed, _ = manager.quick_add("CAR: tyres")
    assert routed["project_id"] == other["id"]
    with pytest.raises(InvalidError):
        manager.quick_add("@joachim")
    manager.delete_project("HOME")
    manager.delete_project("CAR")
    with pytest.raises(NotFoundError):
        manager.quick_add("anything")


# ------------------------------------------------------------------ recurring


async def test_recurring_creates_issue_when_due_and_advances(manager, hass, freezer):
    freezer.move_to("2026-11-25 08:00:00+01:00")
    events = async_capture_events(hass, const.EVENT_ISSUE_CREATED)
    rec = manager.create_recurring(
        "HOME",
        summary="Put out the bins",
        repeat={"unit": "week", "weekdays": [2]},
        next_due="2026-11-25",
        priority="low",
        assignee="person.padmaja",
        labels=["chore"],
    )
    await hass.async_block_till_done()
    issue = manager.resolve_issue(rec["last_issue_id"])
    assert issue["summary"] == "Put out the bins" and issue["due"] == "2026-11-25"
    assert issue["source"] == "recurring" and issue["recurring_id"] == rec["id"]
    assert issue["assignee"] == "person.padmaja" and issue["priority"] == "low"
    assert rec["next_due"] == "2026-12-02"
    assert events[0].data["source"] == "recurring"

    # previous one still open -> next occurrence is skipped, not duplicated
    freezer.move_to("2026-12-02 08:00:00+01:00")
    manager.async_tick()
    assert len([i for i in manager.issues.values() if i["recurring_id"] == rec["id"]]) == 1
    assert rec["next_due"] == "2026-12-09"
    # once done, the next one is made
    manager.move_issue(issue["id"], "Done")
    freezer.move_to("2026-12-09 08:00:00+01:00")
    manager.async_tick()
    assert len([i for i in manager.issues.values() if i["recurring_id"] == rec["id"]]) == 2


async def test_recurring_lead_days_and_downtime_collapse(manager, freezer):
    freezer.move_to("2026-11-23 08:00:00+01:00")
    rec = manager.create_recurring(
        "HOME",
        summary="Pay rent",
        repeat={"unit": "month", "day_of_month": 1},
        next_due="2026-12-01",
        create_days_before=10,
    )
    assert rec["last_issue_id"] is not None  # 10 days ahead -> created now
    assert manager.resolve_issue(rec["last_issue_id"])["due"] == "2026-12-01"

    weekly = manager.create_recurring(
        "HOME",
        summary="Water plants",
        repeat={"unit": "week", "weekdays": [0]},
        next_due="2026-10-05",
        skip_if_open=False,
    )
    mine = [i for i in manager.issues.values() if i["recurring_id"] == weekly["id"]]
    assert len(mine) == 1 and mine[0]["due"] == "2026-11-23"  # weeks of downtime -> one issue
    assert weekly["next_due"] == "2026-11-30"


async def test_recurring_disabled_and_update_delete_run_now(manager, freezer):
    freezer.move_to("2026-11-25 08:00:00+01:00")
    rec = manager.create_recurring(
        "HOME",
        summary="Bins",
        repeat={"unit": "day", "every": 2},
        next_due="2026-11-30",
        enabled=False,
    )
    assert rec["last_issue_id"] is None
    manager.update_recurring(
        rec["id"], enabled=True, summary="Bins out", next_due="2026-11-25", status="In progress"
    )
    assert rec["summary"] == "Bins out" and rec["last_issue_id"] is not None
    first = manager.resolve_issue(rec["last_issue_id"])
    assert manager.category(first) == "in_progress"
    assert manager.run_recurring_now(rec["id"]) is None  # one still open
    manager.move_issue(first["id"], "Done")
    made = manager.run_recurring_now(rec["id"], actor="person.joachim")
    assert made is not None and made["due"] == "2026-11-27"
    manager.delete_recurring(rec["id"])
    assert manager.recurring == {}
    with pytest.raises(NotFoundError):
        manager.delete_recurring(rec["id"])


async def test_recurring_validation(manager):
    for kwargs in (
        {"summary": "x"},
        {"summary": "x", "repeat": {"unit": "day"}},
        {"summary": "x", "repeat": {"unit": "hour"}, "next_due": "2026-12-01"},
        {"summary": "x", "repeat": {"unit": "day"}, "next_due": "2026-12-01T10:00:00+01:00"},
        {
            "summary": "x",
            "repeat": {"unit": "day"},
            "next_due": "2026-12-01",
            "create_days_before": 999,
        },
        {"summary": "x", "repeat": {"unit": "day"}, "next_due": "2026-12-01", "status": "nope"},
    ):
        with pytest.raises((InvalidError, NotFoundError)):
            manager.create_recurring("HOME", **kwargs)


# ------------------------------------------------------------------ clock


async def test_tick_fires_due_soon_then_overdue_once(manager, hass, freezer):
    freezer.move_to("2026-12-01 12:00:00+01:00")
    soon = async_capture_events(hass, const.EVENT_ISSUE_DUE_SOON)
    over = async_capture_events(hass, const.EVENT_ISSUE_OVERDUE)
    issue, _ = manager.create_issue("HOME", "Pay bill", due="2026-12-03")
    manager.async_tick()
    manager.async_tick()
    await hass.async_block_till_done()
    assert len(soon) == 1 and over == []
    freezer.move_to("2026-12-04 00:01:00+01:00")
    manager.async_tick()
    manager.async_tick()
    await hass.async_block_till_done()
    assert len(over) == 1 and len(soon) == 1
    assert over[0].data["key"] == issue["key"] and over[0].data["source"] == "automation"
    # done issues never alarm
    done, _ = manager.create_issue("HOME", "old", due="2020-01-01", status="Done")
    manager.async_tick()
    await hass.async_block_till_done()
    assert len(over) == 1 and not done["overdue_notified"]


async def test_tick_already_overdue_skips_due_soon(manager, hass, freezer):
    freezer.move_to("2026-12-01 12:00:00+01:00")
    soon = async_capture_events(hass, const.EVENT_ISSUE_DUE_SOON)
    over = async_capture_events(hass, const.EVENT_ISSUE_OVERDUE)
    manager.create_issue("HOME", "late", due="2026-11-01")
    manager.async_tick()
    await hass.async_block_till_done()
    assert len(over) == 1 and soon == []


async def test_reopening_allows_new_overdue_event(manager, hass, freezer):
    over = async_capture_events(hass, const.EVENT_ISSUE_OVERDUE)
    issue, _ = manager.create_issue("HOME", "late", due="2020-01-01")
    manager.async_tick()
    manager.move_issue(issue["id"], "Done")
    manager.move_issue(issue["id"], "To do")
    manager.async_tick()
    await hass.async_block_till_done()
    assert len(over) == 2


async def test_auto_archive_done_issues(manager, freezer):
    freezer.move_to("2026-12-01 12:00:00+01:00")
    old, _ = manager.create_issue("HOME", "old", status="Done")
    open_issue, _ = manager.create_issue("HOME", "open")
    freezer.move_to("2027-01-15 12:00:00+01:00")
    fresh, _ = manager.create_issue("HOME", "fresh", status="Done")
    manager.async_tick()
    assert old["archived"] and not fresh["archived"] and not open_issue["archived"]
    manager.options = {"auto_archive_done_days": 0}
    freezer.move_to("2028-01-15 12:00:00+01:00")
    manager.async_tick()
    assert not fresh["archived"]


async def test_periodic_tick_runs_on_the_timer(manager, hass, freezer):
    freezer.move_to("2026-12-01 12:00:00+01:00")
    over = async_capture_events(hass, const.EVENT_ISSUE_OVERDUE)
    manager.create_issue("HOME", "late", due="2026-11-01")
    freezer.tick(timedelta(minutes=6))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert len(over) == 1


# ------------------------------------------------------------------ people / payload / persistence


async def test_people_and_actor_mapping(manager, hass):
    names = [p["name"] for p in manager.people()]
    assert names == ["Joachim", "Padmaja"]
    assert manager.person_for_user("user-1") == "person.padmaja"
    assert manager.person_for_user("nobody") is None and manager.person_for_user(None) is None
    assert manager.tracked_people() == ["person.joachim", "person.padmaja"]
    manager.options = {"tracked_people": ["person.padmaja"]}
    assert manager.tracked_people() == ["person.padmaja"]


async def test_full_payload_shape(manager):
    epic, _ = manager.create_issue("HOME", "e", type="epic")
    issue, _ = manager.create_issue("HOME", "x", due="2020-01-01", parent=epic["id"])
    manager.add_comment(issue["id"], "c")
    payload = manager.full_payload(user_id="user-0", is_admin=True)
    assert payload["me"] == "person.joachim" and payload["is_admin"] is True
    assert (
        payload["settings"]["due_soon_hours"] == 72
        and payload["settings"]["health_enabled"] is True
    )
    view = next(i for i in payload["issues"] if i["id"] == issue["id"])
    assert view["overdue"] is True and view["comment_count"] == 1
    for hidden in ("comments", "activity", "overdue_notified", "auto_resolved"):
        assert hidden not in view
    project = payload["projects"][0]
    assert "issue_seq" not in project and len(project["statuses"]) == 4
    assert payload["stats"]["total"]["open"] == 2
    detail = manager.issue_detail(issue)
    assert detail["comments"][0]["text"] == "c" and detail["activity"]


async def test_state_survives_save_and_load(hass, entry):
    await setup(hass, entry)
    manager = entry.runtime_data
    issue, _ = manager.create_issue("HOME", "persist me", labels=["x"])
    manager.add_comment(issue["id"], "c")
    await manager.async_save_now()
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    again = entry.runtime_data.issues[issue["id"]]
    assert again["summary"] == "persist me" and again["comments"][0]["text"] == "c"
    assert entry.runtime_data.resolve_project("HOME")["issue_seq"] == 1


async def test_delayed_save_is_scheduled(manager, hass, hass_storage, freezer):
    manager.create_issue("HOME", "later")
    freezer.tick(timedelta(seconds=3))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    saved = hass_storage["homeboard"]["data"]
    assert [i["summary"] for i in saved["issues"].values()] == ["later"]


async def test_store_migration_passthrough(hass):
    from custom_components.homeboard.store import HomeboardStore

    store = HomeboardStore(hass)
    assert await store._async_migrate_func(1, 0, {"projects": {}}) == {"projects": {}}
