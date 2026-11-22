"""The maths of Homeboard's learning (pure Python, no Home Assistant imports).

Everything here is plain statistics over the board's own issues and a few
counters: token overlap between titles, medians, shares, intervals. Nothing is
a black box and every result can say what it was based on.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import pairwise
from statistics import mean, median, pstdev
from typing import Any

from . import recurrence

STOPWORDS = frozenset(
    {
        # English
        "the",
        "a",
        "an",
        "to",
        "of",
        "and",
        "or",
        "for",
        "in",
        "on",
        "at",
        "with",
        "my",
        "our",
        "is",
        "it",
        "up",
        "out",
        "new",
        "get",
        "do",
        "be",
        "this",
        "that",
        # Danish
        "og",
        "i",
        "på",
        "af",
        "en",
        "et",
        "til",
        "den",
        "det",
        "de",
        "med",
        "er",
        "som",
        "vi",
        "jeg",
        "min",
        "vores",
        "skal",
        "ny",
        "nyt",
        "nye",
    }
)
SUFFIXES = ("ers", "ing", "er", "en", "et", "es", "s", "e")
WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)

MIN_SIMILARITY = 0.5
CLUSTER_SIMILARITY = 0.7
MAX_SIMILAR = 8
MIN_PATTERN_COUNT = 3
MIN_PATTERN_INTERVAL_DAYS = 3.0
MAX_INTERVAL_VARIATION = 0.5


def stem(word: str) -> str:
    """Crude suffix stripping, good enough to match 'bin bags' with 'bin bag'."""
    for suffix in SUFFIXES:
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def tokens(text: str) -> frozenset[str]:
    """Return the meaningful lower-cased word stems of a title."""
    found = set()
    for word in WORD_RE.findall(text.lower()):
        if len(word) < 2 or word in STOPWORDS or word.isdigit():
            continue
        found.add(stem(word))
    return frozenset(found)


def similarity(a: frozenset[str], b: frozenset[str]) -> float:
    """Cosine similarity of two token sets (0..1)."""
    if not a or not b:
        return 0.0
    return len(a & b) / math.sqrt(len(a) * len(b))


# ------------------------------------------------------------------ corpus rows


@dataclass
class Row:
    """One issue as the learner sees it."""

    id: str
    key: str
    project_id: str
    summary: str
    tokens: frozenset[str]
    assignee: str | None
    labels: list[str]
    priority: str
    type: str
    created: datetime
    due: date | None
    resolved: datetime | None
    status: str
    category: str
    source: str
    recurring: bool
    archived: bool


def parse_due(due: str | None) -> date | None:
    """Return the date part of a stored due value."""
    if not due:
        return None
    try:
        return date.fromisoformat(due) if len(due) == 10 else datetime.fromisoformat(due).date()
    except ValueError:
        return None


# ------------------------------------------------------------------ smart defaults


def _share(counter: Counter[str], total: float) -> tuple[str | None, float]:
    if not counter or total <= 0:
        return None, 0.0
    value, weight = counter.most_common(1)[0]
    return value, weight / total


def suggest_defaults(
    summary: str,
    rows: list[Row],
    *,
    project_id: str | None,
    skip: set[str],
    open_counts: dict[str, int] | None = None,
    use_workload: bool = False,
) -> dict[str, Any] | None:
    """Suggest assignee, labels, priority and a due offset for a new issue.

    ``skip`` names fields the user already set (``assignee``, ``labels``,
    ``priority``, ``due``). Returns None when there is nothing to suggest.
    """
    wanted = tokens(summary)
    if not wanted:
        return None
    scored = [
        (similarity(wanted, row.tokens), row)
        for row in rows
        if row.source != "health" and row.tokens
    ]
    matches = sorted(
        ((s, r) for s, r in scored if s >= MIN_SIMILARITY),
        key=lambda pair: (pair[1].project_id == project_id, pair[0], pair[1].created),
        reverse=True,
    )[:MAX_SIMILAR]
    if not matches:
        return None
    total = sum(s for s, _ in matches)
    n = len(matches)

    assignee = None
    assignee_share = 0.0
    if "assignee" not in skip:
        counter: Counter[str] = Counter()
        for s, row in matches:
            if row.assignee:
                counter[row.assignee] += s
        top, share = _share(counter, total)
        if top and ((n >= 2 and share >= 0.6) or (n == 1 and matches[0][0] >= 0.8)):
            assignee, assignee_share = top, share

    labels: list[str] = []
    if "labels" not in skip:
        counter = Counter()
        for s, row in matches:
            for label in set(row.labels):
                counter[label] += s
        labels = [label for label, weight in counter.most_common(3) if weight / total >= 0.5]

    priority = None
    if "priority" not in skip:
        counter = Counter()
        for s, row in matches:
            counter[row.priority] += s
        top, share = _share(counter, total)
        if top and top != "medium" and share >= 0.6:
            priority = top

    due_in_days = None
    if "due" not in skip:
        offsets = [
            (row.due - row.created.date()).days
            for _s, row in matches
            if row.due is not None and 0 <= (row.due - row.created.date()).days <= 365
        ]
        if offsets:
            due_in_days = max(0, round(median(offsets)))

    evidence = f"based on {n} similar issue{'s' if n != 1 else ''}"
    balanced = False
    if (
        assignee is None
        and "assignee" not in skip
        and use_workload
        and open_counts
        and len(open_counts) >= 2
    ):
        least = min(open_counts, key=lambda p: (open_counts[p], p))
        if open_counts[least] < max(open_counts.values()):
            assignee, balanced = least, True
            evidence += ", least busy person"

    if not (assignee or labels or priority or due_in_days is not None):
        return None
    agreement = assignee_share or 0.6
    confidence = round(min(1.0, (0.2 + 0.15 * n) * agreement * (0.6 if balanced else 1.0)), 2)
    return {
        "assignee": assignee,
        "labels": labels,
        "priority": priority,
        "due_in_days": due_in_days,
        "similar": [
            {"key": row.key, "summary": row.summary, "status": row.status}
            for _s, row in matches[:3]
        ],
        "evidence": evidence,
        "confidence": confidence,
    }


# ------------------------------------------------------------------ patterns


def _repeat_for(interval: float, last: date) -> dict[str, Any]:
    """Turn an average gap in days into a repeat rule."""
    if 6 <= interval <= 8:
        return {"unit": "week", "every": 1, "weekdays": [last.weekday()], "day_of_month": None}
    if 12 <= interval <= 16:
        return {"unit": "week", "every": 2, "weekdays": [last.weekday()], "day_of_month": None}
    if 27 <= interval <= 34:
        return {"unit": "month", "every": 1, "weekdays": None, "day_of_month": last.day}
    if 85 <= interval <= 95:
        return {"unit": "month", "every": 3, "weekdays": None, "day_of_month": last.day}
    if 350 <= interval <= 380:
        return {"unit": "year", "every": 1, "weekdays": None, "day_of_month": None}
    return {"unit": "day", "every": max(1, round(interval)), "weekdays": None, "day_of_month": None}


def describe_interval(days: float) -> str:
    """Return a human phrase for an average gap ('every 6 weeks')."""
    days = round(days)
    if days < 14:
        return f"every {days} days"
    if days < 60:
        weeks = round(days / 7)
        return f"every {weeks} weeks"
    if days < 330:
        return f"every {round(days / 30)} months"
    return "every year"


def find_patterns(rows: list[Row], today: date) -> list[dict[str, Any]]:
    """Find tasks that keep being created again at a regular rhythm."""
    candidates = sorted(
        (
            r
            for r in rows
            if r.source not in ("health", "recurring") and not r.recurring and r.tokens
        ),
        key=lambda r: r.created,
    )
    clusters: list[list[Row]] = []
    for row in candidates:
        for cluster in clusters:
            if similarity(cluster[0].tokens, row.tokens) >= CLUSTER_SIMILARITY:
                cluster.append(row)
                break
        else:
            clusters.append([row])

    found = []
    for cluster in clusters:
        if len(cluster) < MIN_PATTERN_COUNT:
            continue
        dates = [r.created.date() for r in cluster]
        gaps = [(b - a).days for a, b in pairwise(dates) if (b - a).days >= 1]
        if len(gaps) < MIN_PATTERN_COUNT - 1:
            continue
        average = mean(gaps)
        if average < MIN_PATTERN_INTERVAL_DAYS:
            continue
        if pstdev(gaps) / average > MAX_INTERVAL_VARIATION:
            continue
        last = cluster[-1]
        if (today - dates[-1]).days > 2.5 * average:
            continue  # stopped happening
        repeat = _repeat_for(average, dates[-1])
        normalized = recurrence.normalize_repeat(repeat, dates[-1])
        next_due = recurrence.next_occurrence(normalized, dates[-1])
        guard = 0
        while next_due <= today and guard < 500:
            next_due = recurrence.next_occurrence(normalized, next_due)
            guard += 1
        owners = Counter(r.assignee for r in cluster if r.assignee)
        owner, share = _share(owners, sum(owners.values()))
        label_counts = Counter(label for r in cluster for label in set(r.labels))
        priorities = Counter(r.priority for r in cluster)
        key = "recurring:" + "-".join(sorted(cluster[0].tokens))[:60]
        found.append(
            {
                "id": key,
                "kind": "recurring",
                "title": f"Make '{last.summary}' a recurring chore?",
                "detail": (
                    f"Created {len(cluster)} times, about {describe_interval(average)}. "
                    f"Next one would be due {next_due.isoformat()}."
                ),
                "evidence": {"count": len(cluster), "interval_days": round(average)},
                "proposal": {
                    "project_id": last.project_id,
                    "summary": last.summary,
                    "repeat": normalized,
                    "next_due": next_due.isoformat(),
                    "assignee": owner if share >= 0.6 else None,
                    "labels": [lab for lab, c in label_counts.items() if c / len(cluster) >= 0.5],
                    "priority": priorities.most_common(1)[0][0],
                },
            }
        )
    return found


# ------------------------------------------------------------------ workload


def workload(rows: list[Row], people: list[str], now: datetime) -> dict[str, Any]:
    """Return per person load and average days to finish, per type and per label."""
    month_ago = now - timedelta(days=30)
    quarter_ago = now - timedelta(days=90)
    per_person: dict[str, dict[str, Any]] = {
        p: {"open": 0, "done_30d": 0, "avg_days": None} for p in people
    }
    spans: dict[str, list[float]] = defaultdict(list)
    by_type: dict[str, list[float]] = defaultdict(list)
    by_label: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if row.source == "health":
            continue
        who = row.assignee
        if who is not None:
            block = per_person.setdefault(who, {"open": 0, "done_30d": 0, "avg_days": None})
            if row.category != "done" and not row.archived:
                block["open"] += 1
            if row.resolved and row.resolved >= month_ago:
                block["done_30d"] += 1
        if row.category == "done" and row.resolved and row.resolved >= quarter_ago:
            days = max(0.0, (row.resolved - row.created).total_seconds() / 86400)
            if who is not None:
                spans[who].append(days)
            by_type[row.type].append(days)
            for label in set(row.labels):
                by_label[label].append(days)
    for who, values in spans.items():
        per_person[who]["avg_days"] = round(mean(values), 1)
    return {
        "people": per_person,
        "types": {t: round(mean(v), 1) for t, v in by_type.items()},
        "labels": {lab: round(mean(v), 1) for lab, v in by_label.items() if len(v) >= 3},
    }


# ------------------------------------------------------------------ rhythm


def blank_grid() -> list[list[int]]:
    """Return an empty 7 x 24 counter grid (Monday first)."""
    return [[0] * 24 for _ in range(7)]


def probabilities(seen: list[list[int]], home: list[list[int]]) -> list[list[float]]:
    """Return home / seen per weekday and hour (0 where nothing was seen)."""
    return [
        [round(home[d][h] / seen[d][h], 2) if seen[d][h] else 0.0 for h in range(24)]
        for d in range(7)
    ]


def suggest_digest_time(
    seen: list[list[int]], home: list[list[int]], *, min_samples: int = 48
) -> tuple[str, float] | None:
    """Pick a morning time when the person is usually home on weekdays.

    Looks at 07:00-09:59, needs ``min_samples`` per weekday-hour cell (about
    four weeks of data) and at least 60 % home.
    """
    best: tuple[float, int] | None = None
    for hour in range(7, 10):
        cells = [(seen[d][hour], home[d][hour]) for d in range(5)]
        if any(s < min_samples for s, _ in cells):
            continue
        share = sum(h for _, h in cells) / sum(s for s, _ in cells)
        if best is None or share > best[0] + 1e-9:
            best = (share, hour)
    if best is None or best[0] < 0.6:
        return None
    return f"{best[1]:02d}:15", round(best[0], 2)
