"""Pure model helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from custom_components.homeboard import model
from custom_components.homeboard.const import ORDER_STEP

CET = timezone(timedelta(hours=1))


def test_new_id_is_unique_and_short():
    ids = {model.new_id() for _ in range(500)}
    assert len(ids) == 500
    assert all(len(i) == 12 for i in ids)


@pytest.mark.parametrize("key", ["HOME", "ab", "H2", "ABCDEF"])
def test_normalize_key_ok(key):
    assert model.normalize_key(key) == key.upper()


@pytest.mark.parametrize("key", ["", "A", "1AB", "TOOLONG1", "AB-C", "A B"])
def test_normalize_key_rejects(key):
    with pytest.raises(model.InvalidError):
        model.normalize_key(key)


def test_templates_are_valid_workflows():
    for name in model.TEMPLATES:
        statuses = model.build_statuses(name)
        model.check_statuses(statuses)
        assert len({s["id"] for s in statuses}) == len(statuses)
    with pytest.raises(model.InvalidError):
        model.build_statuses("nope")


def test_check_statuses_rules():
    with pytest.raises(model.InvalidError):
        model.check_statuses([])
    with pytest.raises(model.InvalidError):
        model.check_statuses([{"name": "A", "category": "todo"}])
    with pytest.raises(model.ConflictError):
        model.check_statuses([{"name": "A", "category": "todo"}, {"name": "a", "category": "done"}])


def test_clean_helpers():
    assert model.clean_summary("  fix   the  gate ") == "fix the gate"
    with pytest.raises(model.InvalidError):
        model.clean_summary("   ")
    with pytest.raises(model.InvalidError):
        model.clean_summary("x" * 300)
    assert model.clean_labels(["#Garden", "garden", " Car "]) == ["garden", "car"]
    assert model.clean_labels("one") == ["one"]
    assert model.clean_labels(None) == []
    with pytest.raises(model.InvalidError):
        model.clean_labels(["x" * 50])


def test_choices():
    assert model.check_type(None) == "task"
    assert model.check_priority(None) == "medium"
    assert model.check_category("done") == "done"
    for bad in (
        lambda: model.check_type("epos"),
        lambda: model.check_priority("urgent"),
        lambda: model.check_category("x"),
    ):
        with pytest.raises(model.InvalidError):
            bad()
    assert model.check_source("siri") == "siri"
    assert model.check_source("weird") == "service"


def test_person_and_wip():
    assert model.check_person(None) is None
    assert model.check_person("") is None
    assert model.check_person("person.joachim") == "person.joachim"
    with pytest.raises(model.InvalidError):
        model.check_person("light.kitchen")
    assert model.check_wip(None) is None
    assert model.check_wip(0) is None
    assert model.check_wip("3") == 3
    with pytest.raises(model.InvalidError):
        model.check_wip("abc")
    with pytest.raises(model.InvalidError):
        model.check_wip(5000)


def test_normalize_due():
    assert model.normalize_due(None) is None
    assert model.normalize_due("") is None
    assert model.normalize_due("2026-12-01") == "2026-12-01"
    assert model.normalize_due(date(2026, 12, 1)) == "2026-12-01"
    assert model.normalize_due("2026-12-01T18:00:00+01:00") == "2026-12-01T18:00:00+01:00"
    assert model.normalize_due(datetime(2026, 12, 1, 18, tzinfo=UTC)).startswith("2026-12-01T18")
    for bad in ("tomorrow", "2026-13-01", "2026-12-01T18:00:00"):
        with pytest.raises(model.InvalidError):
            model.normalize_due(bad)
    with pytest.raises(model.InvalidError):
        model.normalize_due(datetime(2026, 12, 1, 18))


def test_overdue_and_due_soon_date_only():
    now = datetime(2026, 12, 1, 12, 0, tzinfo=CET)
    # A date due is overdue only once that day is over.
    assert not model.is_overdue("2026-12-01", now, CET)
    assert model.is_overdue("2026-11-30", now, CET)
    assert model.is_due_soon("2026-12-01", now, CET, 24)
    assert model.is_due_soon("2026-12-03", now, CET, 72)
    assert not model.is_due_soon("2026-12-06", now, CET, 72)
    assert not model.is_due_soon("2026-11-30", now, CET, 72)  # already overdue
    assert not model.is_overdue(None, now, CET)
    assert not model.is_due_soon(None, now, CET, 72)


def test_overdue_datetime():
    now = datetime(2026, 12, 1, 12, 0, tzinfo=CET)
    assert model.is_overdue("2026-12-01T11:59:00+01:00", now, CET)
    assert not model.is_overdue("2026-12-01T12:01:00+01:00", now, CET)
    assert model.is_due_soon("2026-12-01T13:00:00+01:00", now, CET, 2)


def project():
    return {
        "key": "T",
        "statuses": [
            {"id": "b", "name": "Backlog", "category": "todo", "backlog": True, "wip": None},
            {"id": "t", "name": "To do", "category": "todo", "backlog": False, "wip": None},
            {
                "id": "p",
                "name": "In progress",
                "category": "in_progress",
                "backlog": False,
                "wip": None,
            },
            {"id": "d", "name": "Done", "category": "done", "backlog": False, "wip": None},
        ],
    }


def test_status_lookups():
    p = project()
    assert model.status_by_id(p, "p")["name"] == "In progress"
    assert model.resolve_status(p, "in PROGRESS")["id"] == "p"
    assert model.resolve_status(p, "d")["name"] == "Done"
    assert model.default_status(p)["id"] == "t"
    assert model.first_with_category(p, "done")["id"] == "d"
    for bad in (lambda: model.status_by_id(p, "x"), lambda: model.resolve_status(p, "nope")):
        with pytest.raises(model.NotFoundError):
            bad()
    only_backlog = {"key": "T", "statuses": [p["statuses"][0], p["statuses"][3]]}
    assert model.default_status(only_backlog)["id"] == "b"
    only_done = {"key": "T", "statuses": [p["statuses"][3]]}
    assert model.default_status(only_done)["id"] == "d"
    assert model.first_with_category(only_done, "in_progress")["id"] == "d"


def test_compute_rank_cases():
    assert model.compute_rank([], None) == (ORDER_STEP, {})
    assert model.compute_rank([("a", 1000), ("b", 2000)], None) == (3000, {})
    # in front of the first
    assert model.compute_rank([("a", 1000), ("b", 2000)], "a") == (0, {})
    # between two
    assert model.compute_rank([("a", 1000), ("b", 2000)], "b") == (1500, {})
    with pytest.raises(model.NotFoundError):
        model.compute_rank([("a", 1000)], "zzz")


def test_compute_rank_rebalances_when_no_gap():
    rank, rebalanced = model.compute_rank([("a", 1000), ("b", 1001), ("c", 5000)], "b")
    assert rebalanced == {"a": 1000, "b": 3000, "c": 4000}
    order = sorted([(rank, "new")] + [(r, i) for i, r in rebalanced.items()])
    assert [name for _, name in order] == ["a", "new", "b", "c"]


def test_sort_key():
    issues = [{"rank": 2, "number": 1}, {"rank": 1, "number": 5}, {"rank": 1, "number": 2}]
    assert [i["number"] for i in sorted(issues, key=model.sort_key)] == [2, 5, 1]
