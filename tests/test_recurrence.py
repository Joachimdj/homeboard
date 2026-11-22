"""Recurring schedule maths."""

from __future__ import annotations

from datetime import date

import pytest

from custom_components.homeboard import recurrence
from custom_components.homeboard.model import InvalidError


def rule(unit, every=1, **kw):
    return recurrence.normalize_repeat({"unit": unit, "every": every, **kw}, date(2026, 11, 25))


def test_day():
    assert recurrence.next_occurrence(rule("day", 3), date(2026, 11, 25)) == date(2026, 11, 28)


def test_week_single_weekday_default_is_anchor_weekday():
    r = rule("week")
    assert r["weekdays"] == [2]  # 2026-11-25 is a Wednesday
    assert recurrence.next_occurrence(r, date(2026, 11, 25)) == date(2026, 12, 2)


def test_week_multiple_weekdays_and_interval():
    r = rule("week", 1, weekdays=[0, 4])
    assert recurrence.next_occurrence(r, date(2026, 11, 23)) == date(2026, 11, 27)  # Mon -> Fri
    assert recurrence.next_occurrence(r, date(2026, 11, 27)) == date(
        2026, 11, 30
    )  # Fri -> next Mon
    biweekly = rule("week", 2, weekdays=[0])
    assert recurrence.next_occurrence(biweekly, date(2026, 11, 23)) == date(2026, 12, 7)


def test_month_clamps_and_last_day():
    r = rule("month", 1, day_of_month=31)
    assert recurrence.next_occurrence(r, date(2026, 1, 31)) == date(2026, 2, 28)
    assert recurrence.next_occurrence(r, date(2026, 2, 28)) == date(2026, 3, 31)
    last = rule("month", 1, day_of_month=-1)
    assert recurrence.next_occurrence(last, date(2026, 2, 28)) == date(2026, 3, 31)
    # later in the same month counts
    r20 = rule("month", 1, day_of_month=20)
    assert recurrence.next_occurrence(r20, date(2026, 11, 15)) == date(2026, 11, 20)
    assert recurrence.next_occurrence(
        rule("month", 3, day_of_month=15), date(2026, 11, 15)
    ) == date(2027, 2, 15)


def test_year_leap_day():
    r = rule("year")
    assert recurrence.next_occurrence(r, date(2028, 2, 29)) == date(2029, 2, 28)
    assert recurrence.next_occurrence(r, date(2026, 11, 25)) == date(2027, 11, 25)


@pytest.mark.parametrize(
    "bad",
    [
        {"unit": "hour"},
        {"unit": "day", "every": 0},
        {"unit": "day", "every": "x"},
        {"unit": "week", "weekdays": [7]},
        {"unit": "month", "day_of_month": 40},
    ],
)
def test_normalize_repeat_rejects(bad):
    with pytest.raises(InvalidError):
        recurrence.normalize_repeat(bad, date(2026, 11, 25))


def test_plan_nothing_ready():
    r = rule("week")
    assert recurrence.plan(date(2026, 12, 2), r, 0, date(2026, 11, 25)) == (None, date(2026, 12, 2))


def test_plan_due_today_and_lead_days():
    r = rule("week")
    assert recurrence.plan(date(2026, 11, 25), r, 0, date(2026, 11, 25)) == (
        date(2026, 11, 25),
        date(2026, 12, 2),
    )
    # created two days early
    assert recurrence.plan(date(2026, 11, 25), r, 2, date(2026, 11, 23)) == (
        date(2026, 11, 25),
        date(2026, 12, 2),
    )


def test_plan_collapses_missed_occurrences_into_one():
    r = rule("week")
    candidate, new_next = recurrence.plan(date(2026, 11, 4), r, 0, date(2026, 11, 25))
    assert candidate == date(2026, 11, 25)  # the most recent one only
    assert new_next == date(2026, 12, 2)
