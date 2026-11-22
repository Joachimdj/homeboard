"""Statistics maths."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from custom_components.homeboard.model import build_statuses
from custom_components.homeboard.stats import compute_stats

TZ = timezone(timedelta(hours=1))
NOW = datetime(2026, 12, 1, 12, 0, tzinfo=TZ)


def setup():
    statuses = build_statuses("household")
    project = {"id": "p1", "key": "HOME", "statuses": statuses}
    todo, prog, done = statuses[1]["id"], statuses[2]["id"], statuses[3]["id"]

    def issue(i, status, **kw):
        base = {
            "id": f"i{i}",
            "project_id": "p1",
            "status": status,
            "type": "task",
            "priority": "medium",
            "assignee": None,
            "due": None,
            "archived": False,
            "updated": "2026-12-01T10:00:00+00:00",
            "resolved": None,
            "source": "ui",
            "number": i,
        }
        base.update(kw)
        return base

    issues = {
        "i1": issue(1, todo, due="2026-11-30", assignee="person.a"),  # overdue
        "i2": issue(2, prog, due="2026-12-02", assignee="person.a", priority="high"),  # due soon
        "i3": issue(3, todo, type="bug", source="health"),  # unassigned
        "i4": issue(
            4, done, resolved="2026-11-30T10:00:00+00:00", assignee="person.b", due="2026-11-01"
        ),  # done 7d, never overdue
        "i5": issue(5, done, resolved="2026-10-01T10:00:00+00:00"),  # done long ago
        "i6": issue(6, todo, archived=True),  # ignored
        "i7": {**issue(7, todo), "project_id": "gone"},  # orphan ignored
    }
    return {"p1": project}, issues, (todo, prog, done)


def test_totals_and_project_block():
    projects, issues, (todo, prog, done) = setup()
    stats = compute_stats(projects, issues, NOW, TZ, 72)
    total = stats["total"]
    assert (total["open"], total["overdue"], total["due_soon"], total["unassigned"]) == (3, 1, 1, 1)
    assert total["done_7d"] == 1
    assert total["health_open"] == 1
    assert total["last_activity"] == "2026-12-01T10:00:00+00:00"
    block = stats["projects"]["p1"]
    assert block["by_status"] == {todo: 2, prog: 1, done: 2}
    assert block["by_priority"] == {"medium": 2, "high": 1}
    assert block["by_type"] == {"task": 2, "bug": 1}


def test_people_and_prelisted_people():
    projects, issues, _ = setup()
    stats = compute_stats(projects, issues, NOW, TZ, 72, people=["person.c"])
    people = stats["people"]
    assert people["person.a"] == {"open": 2, "overdue": 1, "in_progress": 1, "done_7d": 0}
    assert people["person.b"]["done_7d"] == 1
    assert people["person.c"] == {"open": 0, "overdue": 0, "in_progress": 0, "done_7d": 0}
    assert people["unassigned"]["open"] == 1


def test_empty():
    stats = compute_stats({}, {}, NOW, TZ, 72)
    assert stats["total"]["open"] == 0 and stats["projects"] == {} and stats["people"] == {}
