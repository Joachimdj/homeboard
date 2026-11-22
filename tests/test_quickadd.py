"""Quick-add parser."""

from __future__ import annotations

from datetime import date, timedelta, timezone

import pytest

from custom_components.homeboard.model import InvalidError
from custom_components.homeboard.quickadd import Person, parse_quick_add

TZ = timezone(timedelta(hours=1))
TODAY = date(2026, 11, 25)  # a Wednesday
PEOPLE = [Person("person.joachim", "Joachim"), Person("person.padmaja", "Padmaja")]


def parse(text, **kw):
    return parse_quick_add(
        text, people=PEOPLE, project_keys=["HOME", "FIX"], today=TODAY, tz=TZ, **kw
    )


def test_plain_summary():
    p = parse("  buy   milk ")
    assert p.summary == "buy milk"
    assert (p.assignee, p.priority, p.due, p.type, p.project, p.labels) == (
        None,
        None,
        None,
        None,
        None,
        [],
    )


def test_all_tokens():
    p = parse("bug: gate squeaks @joa !high #Garden #car due friday")
    assert p.type == "bug"
    assert p.summary == "gate squeaks"
    assert p.assignee == "person.joachim"
    assert p.priority == "high"
    assert p.labels == ["garden", "car"]
    assert p.due == "2026-11-27"


def test_project_prefix_and_type_in_either_order():
    a = parse("HOME: story: write a story")
    b = parse("story: write it")
    assert (a.project, a.type, a.summary) == ("HOME", "story", "write a story")
    assert b.type == "story" and b.project is None
    assert parse("home: task: lower case key").project == "HOME"


def test_unknown_prefix_stays_in_summary():
    assert parse("note: remember this").summary == "note: remember this"


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        ("today", "2026-11-25"),
        ("tomorrow", "2026-11-26"),
        ("tmrw", "2026-11-26"),
        ("wed", "2026-12-02"),  # never today
        ("monday", "2026-11-30"),
        ("next week", "2026-11-30"),
        ("in 3 days", "2026-11-28"),
        ("in 2 weeks", "2026-12-09"),
        ("2026-12-24", "2026-12-24"),
        ("1/12", "2026-12-01"),
        ("1.12", "2026-12-01"),
        ("24.11", "2027-11-24"),  # already passed this year -> next year
        ("1.12.27", "2027-12-01"),
        ("i morgen", "2026-11-26"),
        ("i dag", "2026-11-25"),
        ("i overmorgen", "2026-11-27"),
        ("fredag", "2026-11-27"),
        ("om 2 dage", "2026-11-27"),
        ("næste uge", "2026-11-30"),
    ],
)
def test_due_phrases(when, expected):
    p = parse(f"task due {when}")
    assert p.due == expected, when
    assert p.summary == "task"


def test_due_with_time_makes_a_datetime():
    p = parse("call plumber due tomorrow 18:30")
    assert p.due == "2026-11-26T18:30:00+01:00"
    assert p.summary == "call plumber"
    assert parse("x due today 25:99").due == "2026-11-25"


def test_unparseable_due_is_left_in_the_text():
    p = parse("deal with due soon")
    assert p.due is None
    assert "due soon" in p.summary
    assert parse("due 2026-02-31 thing").due is None


@pytest.mark.parametrize(
    ("token", "priority"),
    [
        ("!highest", "highest"),
        ("!1", "highest"),
        ("!2", "high"),
        ("!medium", "medium"),
        ("!low", "low"),
        ("!5", "lowest"),
        ("!vigtig", "high"),
        ("!haster", "highest"),
    ],
)
def test_priorities(token, priority):
    assert parse(f"x {token}").priority == priority


def test_unresolved_tokens_stay_and_are_reported():
    p = parse("x @nobody !urgent")
    assert p.assignee is None and p.priority is None
    assert p.unresolved == ["@nobody", "!urgent"]
    assert "@nobody" in p.summary and "!urgent" in p.summary


def test_assignee_matching():
    assert parse("x @me", me="person.padmaja").assignee == "person.padmaja"
    assert parse("x @me").assignee is None
    assert parse("x @Padmaja").assignee == "person.padmaja"
    assert parse("x @pad").assignee == "person.padmaja"
    ambiguous = parse_quick_add(
        "x @jo",
        people=[Person("person.joe", "Joe"), Person("person.joachim", "Joachim")],
        project_keys=[],
        today=TODAY,
        tz=TZ,
    )
    assert ambiguous.assignee is None


def test_empty_summary_is_an_error():
    for text in ("", "   ", "@joachim !high #x due friday"):
        with pytest.raises(InvalidError):
            parse(text)


def test_to_dict_is_json_friendly():
    d = parse("x #a").to_dict()
    assert d["labels"] == ["a"] and d["summary"] == "x"
