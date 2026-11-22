"""Recurring-issue schedule maths (pure, no Home Assistant imports)."""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any

from .const import REPEAT_UNITS
from .model import InvalidError


def _month_length(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def _clamped(year: int, month: int, day: int) -> date:
    """Return a date, clamping the day into the month (``-1`` = last day)."""
    length = _month_length(year, month)
    day = length if day == -1 else min(day, length)
    return date(year, month, day)


def _add_months(year: int, month: int, months: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + months
    return index // 12, index % 12 + 1


def normalize_repeat(repeat: dict[str, Any], anchor: date) -> dict[str, Any]:
    """Validate a repeat rule and fill defaults from the anchor date."""
    unit = repeat.get("unit")
    if unit not in REPEAT_UNITS:
        raise InvalidError(f"repeat.unit must be one of {', '.join(REPEAT_UNITS)}")
    try:
        every = int(repeat.get("every", 1))
    except (TypeError, ValueError) as err:
        raise InvalidError("repeat.every must be a whole number") from err
    if not 1 <= every <= 366:
        raise InvalidError("repeat.every must be between 1 and 366")
    result: dict[str, Any] = {
        "every": every,
        "unit": unit,
        "weekdays": None,
        "day_of_month": None,
    }
    if unit == "week":
        weekdays = repeat.get("weekdays") or [anchor.weekday()]
        if not all(isinstance(d, int) and 0 <= d <= 6 for d in weekdays):
            raise InvalidError("repeat.weekdays must be numbers 0 (Mon) to 6 (Sun)")
        result["weekdays"] = sorted(set(weekdays))
    if unit == "month":
        day = repeat.get("day_of_month") or anchor.day
        if not (day == -1 or 1 <= day <= 31):
            raise InvalidError("repeat.day_of_month must be 1-31 or -1 (last day)")
        result["day_of_month"] = day
    return result


def next_occurrence(repeat: dict[str, Any], after: date) -> date:
    """Return the first occurrence strictly after ``after``."""
    every = repeat["every"]
    unit = repeat["unit"]
    if unit == "day":
        return after + timedelta(days=every)
    if unit == "week":
        weekdays = repeat.get("weekdays") or [after.weekday()]
        monday = after - timedelta(days=after.weekday())
        for weekday in weekdays:
            if weekday > after.weekday():
                return monday + timedelta(days=weekday)
        return monday + timedelta(weeks=every, days=weekdays[0])
    if unit == "month":
        day = repeat.get("day_of_month") or after.day
        same_month = _clamped(after.year, after.month, day)
        if same_month > after:
            return same_month
        year, month = _add_months(after.year, after.month, every)
        return _clamped(year, month, day)
    # year
    return _clamped(after.year + every, after.month, after.day)


def plan(
    next_due: date, repeat: dict[str, Any], create_days_before: int, today: date
) -> tuple[date | None, date]:
    """Return ``(candidate_due, new_next_due)`` for the engine run at ``today``.

    ``candidate_due`` is the due date of the single issue to create (``None`` =
    nothing is ready). Missed occurrences while Home Assistant was down are
    collapsed into one issue: the most recent one.
    """
    lead = timedelta(days=max(create_days_before, 0))
    candidate: date | None = None
    guard = 0
    while next_due - lead <= today:
        candidate = next_due
        next_due = next_occurrence(repeat, next_due)
        guard += 1
        if guard > 5000:  # pragma: no cover - defensive, rules always advance
            break
    return candidate, next_due
