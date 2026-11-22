"""Pure helpers for the Homeboard data model (no Home Assistant imports).

Everything here is deterministic and unit-testable on its own: ids, project
templates, rank maths, due-date maths and field normalisation.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

from .const import (
    CATEGORIES,
    DEFAULT_PRIORITY,
    DEFAULT_TYPE,
    ISSUE_TYPES,
    ORDER_STEP,
    PRIORITIES,
    SOURCES,
    SUMMARY_MAX_LENGTH,
)

PROJECT_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]{1,5}$")
PERSON_RE = re.compile(r"^person\.[a-z0-9_]+$")


class HomeboardError(Exception):
    """Base error. ``code`` maps onto websocket error codes."""

    code = "invalid_format"


class NotFoundError(HomeboardError):
    """Something referenced does not exist."""

    code = "not_found"


class InvalidError(HomeboardError):
    """A value is not acceptable."""

    code = "invalid_format"


class ConflictError(HomeboardError):
    """The request clashes with existing data."""

    code = "conflict"


def new_id() -> str:
    """Return a short opaque id."""
    return uuid.uuid4().hex[:12]


# --- project templates ------------------------------------------------------

TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "household": [
        {"name": "Backlog", "category": "todo", "backlog": True, "wip": None},
        {"name": "To do", "category": "todo", "backlog": False, "wip": None},
        {"name": "In progress", "category": "in_progress", "backlog": False, "wip": None},
        {"name": "Done", "category": "done", "backlog": False, "wip": None},
    ],
    "software": [
        {"name": "Backlog", "category": "todo", "backlog": True, "wip": None},
        {"name": "To do", "category": "todo", "backlog": False, "wip": None},
        {"name": "In progress", "category": "in_progress", "backlog": False, "wip": 3},
        {"name": "Review", "category": "in_progress", "backlog": False, "wip": None},
        {"name": "Done", "category": "done", "backlog": False, "wip": None},
    ],
    "blank": [
        {"name": "To do", "category": "todo", "backlog": False, "wip": None},
        {"name": "Done", "category": "done", "backlog": False, "wip": None},
    ],
}


def build_statuses(template: str) -> list[dict[str, Any]]:
    """Return fresh status dicts (with ids) for a template."""
    if template not in TEMPLATES:
        raise InvalidError(f"Unknown template {template!r}")
    return [{"id": new_id(), **status} for status in TEMPLATES[template]]


# --- validation / normalisation --------------------------------------------


def normalize_key(key: str) -> str:
    """Validate and upper-case a project key."""
    key = str(key).strip().upper()
    if not PROJECT_KEY_RE.match(key):
        raise InvalidError(
            "Project key must be 2-6 characters, start with a letter and use A-Z / 0-9"
        )
    return key


def clean_text(
    value: Any,
    field: str,
    *,
    max_len: int,
    required: bool = False,
    single_line: bool = False,
) -> str:
    """Strip a free-text value and check its length."""
    text = "" if value is None else str(value).strip()
    if single_line:
        text = " ".join(text.split())
    if required and not text:
        raise InvalidError(f"{field} must not be empty")
    if len(text) > max_len:
        raise InvalidError(f"{field} is longer than {max_len} characters")
    return text


def clean_summary(value: Any) -> str:
    """Validate an issue summary (single line)."""
    return clean_text(value, "summary", max_len=SUMMARY_MAX_LENGTH, required=True, single_line=True)


def clean_labels(labels: Any) -> list[str]:
    """Normalise a label list: lower-case, unique, order preserved."""
    if labels is None:
        return []
    if isinstance(labels, str):
        labels = [labels]
    seen: list[str] = []
    for label in labels:
        text = " ".join(str(label).split()).lower().lstrip("#")
        if text and text not in seen:
            if len(text) > 40:
                raise InvalidError("Labels can be at most 40 characters")
            seen.append(text)
    return seen


def check_choice(value: Any, choices: tuple[str, ...], field: str) -> str:
    """Return value if it is one of choices."""
    if value not in choices:
        raise InvalidError(f"{field} must be one of {', '.join(choices)}")
    return str(value)


def check_type(value: Any) -> str:
    """Validate an issue type."""
    return check_choice(DEFAULT_TYPE if value is None else value, ISSUE_TYPES, "type")


def check_priority(value: Any) -> str:
    """Validate a priority."""
    return check_choice(DEFAULT_PRIORITY if value is None else value, PRIORITIES, "priority")


def check_category(value: Any) -> str:
    """Validate a status category."""
    return check_choice(value, CATEGORIES, "category")


def check_source(value: Any) -> str:
    """Validate an issue source, falling back to ``service``."""
    return value if value in SOURCES else "service"


def check_person(value: Any) -> str | None:
    """Validate a person entity id (or None / empty = nobody)."""
    if value in (None, ""):
        return None
    value = str(value).lower()
    if not PERSON_RE.match(value):
        raise InvalidError(f"{value!r} is not a person entity id")
    return value


def check_wip(value: Any) -> int | None:
    """Validate a WIP limit (None / 0 = no limit)."""
    if value in (None, "", 0):
        return None
    try:
        wip = int(value)
    except (TypeError, ValueError) as err:
        raise InvalidError("wip must be a whole number") from err
    if wip < 0 or wip > 999:
        raise InvalidError("wip must be between 0 and 999")
    return wip


# --- due dates ---------------------------------------------------------------


def normalize_due(value: Any) -> str | None:
    """Validate a due value and return it as ``YYYY-MM-DD`` or an offset datetime string."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise InvalidError("A due datetime needs a timezone offset")
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    try:
        if len(text) == 10:
            return date.fromisoformat(text).isoformat()
        parsed = datetime.fromisoformat(text)
    except ValueError as err:
        raise InvalidError(f"{text!r} is not a valid date or datetime") from err
    if parsed.tzinfo is None:
        raise InvalidError("A due datetime needs a timezone offset")
    return parsed.isoformat()


def due_moment(due: str, tz: tzinfo) -> datetime:
    """Return the instant an issue becomes overdue.

    A date-only due is overdue once that local day is over.
    """
    if len(due) == 10:
        return datetime.combine(date.fromisoformat(due), time.max, tzinfo=tz)
    return datetime.fromisoformat(due)


def is_overdue(due: str | None, now: datetime, tz: tzinfo) -> bool:
    """Return True if due is in the past."""
    return due is not None and now > due_moment(due, tz)


def is_due_soon(due: str | None, now: datetime, tz: tzinfo, hours: int) -> bool:
    """Return True if due is within the window and not yet overdue."""
    if due is None:
        return False
    moment = due_moment(due, tz)
    return now <= moment <= now + timedelta(hours=hours)


# --- statuses ---------------------------------------------------------------


def status_by_id(project: dict[str, Any], status_id: str) -> dict[str, Any]:
    """Return a status of the project by id."""
    for status in project["statuses"]:
        if status["id"] == status_id:
            return status
    raise NotFoundError(f"Unknown status {status_id!r} in project {project['key']}")


def resolve_status(project: dict[str, Any], ref: str) -> dict[str, Any]:
    """Return a status by id or (case-insensitive) name."""
    wanted = str(ref).strip().lower()
    for status in project["statuses"]:
        if status["id"] == ref or status["name"].lower() == wanted:
            return status
    raise NotFoundError(f"Unknown status {ref!r} in project {project['key']}")


def default_status(project: dict[str, Any]) -> dict[str, Any]:
    """Status new issues land in: first non-backlog 'todo' status."""
    for status in project["statuses"]:
        if status["category"] == "todo" and not status["backlog"]:
            return status
    for status in project["statuses"]:
        if status["category"] == "todo":
            return status
    return project["statuses"][0]


def first_with_category(project: dict[str, Any], category: str) -> dict[str, Any]:
    """Return the first status with a category (falls back to the default)."""
    for status in project["statuses"]:
        if status["category"] == category:
            return status
    return default_status(project)


def check_statuses(statuses: list[dict[str, Any]]) -> None:
    """A workflow needs at least one status and one 'done' status."""
    if not statuses:
        raise InvalidError("A project needs at least one status")
    if not any(s["category"] == "done" for s in statuses):
        raise InvalidError("A project needs at least one status in the 'done' category")
    names = [s["name"].strip().lower() for s in statuses]
    if len(set(names)) != len(names):
        raise ConflictError("Status names must be unique within a project")


# --- ranks --------------------------------------------------------------------


def compute_rank(
    neighbours: list[tuple[str, int]], before_id: str | None
) -> tuple[int, dict[str, int]]:
    """Return ``(new_rank, rebalanced)`` for inserting into an ordered list.

    ``neighbours`` is the ordered ``(issue_id, rank)`` list of the target status
    *without* the moving issue. ``before_id`` is the issue to insert in front of
    (``None`` = at the end). ``rebalanced`` is non-empty when the gap ran out
    and the neighbours had to be renumbered (the new rank is already consistent
    with it).
    """
    ids = [item[0] for item in neighbours]
    if before_id is not None and before_id not in ids:
        raise NotFoundError(f"Issue {before_id!r} is not in the target status")
    if not neighbours:
        return ORDER_STEP, {}
    if before_id is None:
        return neighbours[-1][1] + ORDER_STEP, {}
    idx = ids.index(before_id)
    after_rank = neighbours[idx][1]
    if idx == 0:
        return after_rank - ORDER_STEP, {}
    before_rank = neighbours[idx - 1][1]
    if after_rank - before_rank >= 2:
        return (before_rank + after_rank) // 2, {}
    # No room left: renumber everything, leaving a hole at idx.
    rebalanced: dict[str, int] = {}
    for position, (issue_id, _rank) in enumerate(neighbours):
        slot = position if position < idx else position + 1
        rebalanced[issue_id] = (slot + 1) * ORDER_STEP
    return (idx + 1) * ORDER_STEP, rebalanced


def sort_key(issue: dict[str, Any]) -> tuple[int, int]:
    """Order issues by rank, ties by number."""
    return issue["rank"], issue["number"]
