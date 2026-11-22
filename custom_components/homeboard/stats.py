"""Aggregate statistics over projects and issues (pure, no Home Assistant imports)."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any

from .model import is_due_soon, is_overdue, status_by_id

UNASSIGNED = "unassigned"


def issue_flags(
    issue: dict[str, Any], category: str, now: datetime, tz: tzinfo, due_soon_hours: int
) -> tuple[bool, bool]:
    """Return ``(overdue, due_soon)`` for an issue; done issues are neither."""
    if category == "done":
        return False, False
    due = issue.get("due")
    return (
        is_overdue(due, now, tz),
        is_due_soon(due, now, tz, due_soon_hours),
    )


def _blank() -> dict[str, Any]:
    return {
        "open": 0,
        "overdue": 0,
        "due_soon": 0,
        "unassigned": 0,
        "done_7d": 0,
        "last_activity": None,
        "health_open": 0,
    }


def _latest(current: str | None, candidate: str | None) -> str | None:
    if candidate and (current is None or candidate > current):
        return candidate
    return current


def compute_stats(
    projects: dict[str, dict[str, Any]],
    issues: dict[str, dict[str, Any]],
    now: datetime,
    tz: tzinfo,
    due_soon_hours: int,
    *,
    people: list[str] | None = None,
) -> dict[str, Any]:
    """Return the ``stats`` block of the frontend payload (PROTOCOL.md section 4).

    Archived issues are ignored. ``people`` lists person entity ids that should
    always appear (with zeros) even when nothing is assigned to them.
    """
    week_ago = (now - timedelta(days=7)).astimezone(UTC).isoformat(timespec="seconds")
    total = _blank()
    per_project: dict[str, dict[str, Any]] = {}
    for project_id in projects:
        block = _blank()
        block.update(by_status=Counter(), by_priority=Counter(), by_type=Counter())
        per_project[project_id] = block
    per_person: dict[str, dict[str, int]] = {
        person: {"open": 0, "overdue": 0, "in_progress": 0, "done_7d": 0}
        for person in (people or [])
    }

    for issue in issues.values():
        if issue.get("archived"):
            continue
        project = projects.get(issue["project_id"])
        if project is None:
            continue
        category = status_by_id(project, issue["status"])["category"]
        overdue, due_soon = issue_flags(issue, category, now, tz, due_soon_hours)
        block = per_project[project["id"]]
        owner = issue["assignee"] or UNASSIGNED
        person = per_person.setdefault(
            owner, {"open": 0, "overdue": 0, "in_progress": 0, "done_7d": 0}
        )
        for target in (total, block):
            target["last_activity"] = _latest(target["last_activity"], issue["updated"])
        if category == "done":
            recent = bool(issue.get("resolved")) and issue["resolved"] >= week_ago
            for target in (total, block, person):
                target["done_7d"] += int(recent)
            block["by_status"][issue["status"]] += 1
            continue
        for target in (total, block):
            target["open"] += 1
            target["overdue"] += int(overdue)
            target["due_soon"] += int(due_soon)
            target["unassigned"] += int(issue["assignee"] is None)
            target["health_open"] += int(issue["source"] == "health")
        person["open"] += 1
        person["overdue"] += int(overdue)
        person["in_progress"] += int(category == "in_progress")
        block["by_status"][issue["status"]] += 1
        block["by_priority"][issue["priority"]] += 1
        block["by_type"][issue["type"]] += 1

    for block in per_project.values():
        for key in ("by_status", "by_priority", "by_type"):
            block[key] = dict(block[key])
    return {"total": total, "projects": per_project, "people": per_person}
