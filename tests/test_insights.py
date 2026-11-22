"""The learning maths (pure)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from custom_components.homeboard import insights
from custom_components.homeboard.insights import Row

NOW = datetime(2026, 12, 1, 12, 0, tzinfo=UTC)
TODAY = NOW.date()


def row(
    summary,
    *,
    n=1,
    assignee=None,
    labels=(),
    priority="medium",
    due_after=None,
    created=None,
    source="ui",
    recurring=False,
    category="done",
    resolved_after=None,
    type_="task",
    project="p1",
    status="Done",
    archived=False,
):
    created = created or NOW - timedelta(days=30)
    return Row(
        id=f"i{n}-{summary}",
        key=f"HOME-{n}",
        project_id=project,
        summary=summary,
        tokens=insights.tokens(summary),
        assignee=assignee,
        labels=list(labels),
        priority=priority,
        type=type_,
        created=created,
        due=(created.date() + timedelta(days=due_after)) if due_after is not None else None,
        resolved=(created + timedelta(days=resolved_after)) if resolved_after is not None else None,
        status=status,
        category=category,
        source=source,
        recurring=recurring,
        archived=archived,
    )


def test_tokens_stem_and_stopwords():
    assert insights.tokens("Order the new bin bags") == insights.tokens("order bin bag")
    assert insights.tokens("Køb nye pærer til stuen")  # Danish stopwords dropped, words kept
    assert "til" not in insights.tokens("Køb nye pærer til stuen")
    assert insights.tokens("42 !!! the a") == frozenset()
    assert (
        insights.stem("bags") == "bag"
        and insights.stem("cat") == "cat"
        and insights.stem("lamper") == "lamp"
    )


def test_similarity():
    a, b = insights.tokens("order bin bags"), insights.tokens("order new bin bag liners")
    assert insights.similarity(a, a) == pytest.approx(1.0)
    assert 0.5 < insights.similarity(a, b) < 1.0
    assert insights.similarity(a, insights.tokens("fix the gate")) == 0.0
    assert insights.similarity(frozenset(), a) == 0.0


def test_suggest_assignee_labels_priority_and_due_from_similar_issues():
    rows = [
        row(
            "Pay electricity bill",
            n=1,
            assignee="person.a",
            labels=["bills"],
            priority="high",
            due_after=5,
        ),
        row(
            "Pay the electricity bill",
            n=2,
            assignee="person.a",
            labels=["bills", "home"],
            priority="high",
            due_after=7,
        ),
        row(
            "Pay electricity bill again",
            n=3,
            assignee="person.b",
            labels=["bills"],
            priority="high",
            due_after=3,
        ),
        row("Fix gate", n=4, assignee="person.b", labels=["garden"]),
    ]
    out = insights.suggest_defaults("pay electricity bill", rows, project_id="p1", skip=set())
    assert (
        out["assignee"] == "person.a" and out["labels"] == ["bills"] and out["priority"] == "high"
    )
    assert out["due_in_days"] == 5
    assert out["evidence"] == "based on 3 similar issues" and 0 < out["confidence"] <= 1
    assert [s["key"] for s in out["similar"]] and set(out["similar"][0]) == {
        "key",
        "summary",
        "status",
    }


def test_suggest_respects_skip_and_needs_agreement():
    rows = [
        row("Pay bill", n=1, assignee="person.a", labels=["bills"], priority="high", due_after=5),
        row("Pay bill", n=2, assignee="person.b", labels=["bills"], priority="high", due_after=5),
    ]
    out = insights.suggest_defaults(
        "pay bill", rows, project_id="p1", skip={"labels", "priority", "due"}
    )
    assert out is None  # assignees disagree, everything else already given
    out = insights.suggest_defaults("pay bill", rows, project_id="p1", skip=set())
    assert out["assignee"] is None and out["labels"] == ["bills"]


def test_suggest_single_close_match_and_no_match():
    rows = [row("Service the car", n=1, assignee="person.a")]
    assert (
        insights.suggest_defaults("service the car", rows, project_id="p1", skip=set())["assignee"]
        == "person.a"
    )
    assert (
        insights.suggest_defaults("something unrelated entirely", rows, project_id="p1", skip=set())
        is None
    )
    assert insights.suggest_defaults("   ", rows, project_id="p1", skip=set()) is None
    health = [row("Service the car", n=1, assignee="person.a", source="health")]
    assert insights.suggest_defaults("service the car", health, project_id="p1", skip=set()) is None


def test_suggest_balances_by_workload_when_nothing_else_decides():
    rows = [
        row("Clean the oven", n=1, labels=["kitchen"]),
        row("Clean oven thoroughly", n=2, labels=["kitchen"]),
    ]
    out = insights.suggest_defaults(
        "clean the oven",
        rows,
        project_id="p1",
        skip=set(),
        open_counts={"person.a": 5, "person.b": 1},
        use_workload=True,
    )
    assert (
        out["assignee"] == "person.b"
        and "least busy" in out["evidence"]
        and out["labels"] == ["kitchen"]
    )
    equal = insights.suggest_defaults(
        "clean the oven",
        rows,
        project_id="p1",
        skip=set(),
        open_counts={"person.a": 2, "person.b": 2},
        use_workload=True,
    )
    assert equal["assignee"] is None


def test_same_project_matches_come_first():
    rows = [
        row("Order bags", n=1, assignee="person.a", project="other"),
        row("Order bags", n=2, assignee="person.b", project="p1"),
    ]
    rows += [row("Order bags", n=3, assignee="person.b", project="p1")]
    out = insights.suggest_defaults("order bags", rows, project_id="p1", skip=set())
    assert out["similar"][0]["key"] in ("HOME-2", "HOME-3")


def weekly(summary, *, count, every=7, start=None, **kw):
    start = start or NOW - timedelta(days=every * count)
    return [
        row(summary, n=i + 1, created=start + timedelta(days=every * i), **kw) for i in range(count)
    ]


def test_pattern_finder_proposes_a_weekly_chore():
    rows = weekly(
        "Order new bin bags", count=4, assignee="person.a", labels=["home"], priority="low"
    )
    [found] = insights.find_patterns(rows, TODAY)
    assert found["kind"] == "recurring" and found["id"].startswith("recurring:")
    assert found["evidence"] == {"count": 4, "interval_days": 7}
    assert found["title"] == "Make 'Order new bin bags' a recurring chore?"
    assert "every 7 days" in found["detail"]
    proposal = found["proposal"]
    assert (
        proposal["repeat"]["unit"] == "week"
        and proposal["assignee"] == "person.a"
        and proposal["labels"] == ["home"]
    )
    assert proposal["priority"] == "low" and date.fromisoformat(proposal["next_due"]) > TODAY


@pytest.mark.parametrize(
    ("every", "unit", "step"),
    [(14, "week", 2), (30, "month", 1), (91, "month", 3), (365, "year", 1), (10, "day", 10)],
)
def test_pattern_repeat_rules(every, unit, step):
    count = 4 if every < 200 else 3
    rows = weekly(
        "Do the thing",
        count=count,
        every=every,
        start=NOW - timedelta(days=every * (count - 1) + 1),
    )
    [found] = insights.find_patterns(rows, TODAY)
    assert (
        found["proposal"]["repeat"]["unit"] == unit and found["proposal"]["repeat"]["every"] == step
    )


def test_pattern_finder_ignores_noise():
    assert insights.find_patterns(weekly("Do thing", count=2), TODAY) == []  # too few
    irregular = [
        row("Do thing", n=i, created=NOW - timedelta(days=d))
        for i, d in enumerate((100, 95, 40, 5), 1)
    ]
    assert insights.find_patterns(irregular, TODAY) == []  # not regular
    assert insights.find_patterns(weekly("Do thing", count=5, every=1), TODAY) == []  # too frequent
    stale = weekly("Do thing", count=4, start=NOW - timedelta(days=200))
    assert insights.find_patterns(stale, TODAY) == []  # stopped long ago
    assert insights.find_patterns(weekly("Do thing", count=4, source="health"), TODAY) == []
    assert insights.find_patterns(weekly("Do thing", count=4, recurring=True), TODAY) == []
    assert insights.find_patterns(weekly("Do thing", count=4, source="recurring"), TODAY) == []
    mixed = weekly("Pay rent", count=4) + weekly(
        "Walk dog", count=4, start=NOW - timedelta(days=30)
    )
    assert len(insights.find_patterns(mixed, TODAY)) == 2


def test_describe_interval():
    assert insights.describe_interval(3) == "every 3 days"
    assert insights.describe_interval(42) == "every 6 weeks"
    assert insights.describe_interval(120) == "every 4 months"
    assert insights.describe_interval(400) == "every year"


def test_workload():
    rows = [
        row(
            "a",
            n=1,
            assignee="person.a",
            category="done",
            created=NOW - timedelta(days=10),
            resolved_after=4,
            labels=["x"],
        ),
        row(
            "b",
            n=2,
            assignee="person.a",
            category="done",
            created=NOW - timedelta(days=10),
            resolved_after=2,
            labels=["x"],
        ),
        row(
            "c",
            n=3,
            assignee="person.a",
            category="done",
            created=NOW - timedelta(days=10),
            resolved_after=6,
            labels=["x"],
            type_="bug",
        ),
        row("d", n=4, assignee="person.a", category="todo", resolved_after=None, status="To do"),
        row(
            "e",
            n=5,
            assignee="person.b",
            category="done",
            created=NOW - timedelta(days=200),
            resolved_after=2,
        ),  # too old
        row("f", n=6, assignee="person.b", category="todo", status="To do", archived=True),
        row("g", n=7, assignee="person.a", category="todo", source="health", status="To do"),
    ]
    out = insights.workload(rows, ["person.a", "person.b", "person.c"], NOW)
    assert out["people"]["person.a"] == {"open": 1, "done_30d": 3, "avg_days": 4.0}
    assert out["people"]["person.b"] == {"open": 0, "done_30d": 0, "avg_days": None}
    assert out["people"]["person.c"] == {"open": 0, "done_30d": 0, "avg_days": None}
    assert out["types"] == {"task": 3.0, "bug": 6.0} and out["labels"] == {"x": 4.0}


def test_rhythm_grid_and_digest_time():
    seen, home = insights.blank_grid(), insights.blank_grid()
    for day in range(5):
        seen[day][8] = 60
        home[day][8] = 54
        seen[day][7] = 60
        home[day][7] = 30
    probs = insights.probabilities(seen, home)
    assert probs[0][8] == 0.9 and probs[0][7] == 0.5 and probs[6][8] == 0.0
    assert insights.suggest_digest_time(seen, home) == ("08:15", 0.9)
    thin = insights.blank_grid()
    thin[0][8] = 10
    assert insights.suggest_digest_time(thin, thin) is None  # not enough data yet
    assert insights.suggest_digest_time(seen, [[0] * 24 for _ in range(7)]) is None  # never home
