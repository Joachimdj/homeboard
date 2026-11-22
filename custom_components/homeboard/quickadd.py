"""Quick-add text parser (pure, no Home Assistant imports).

Grammar (see docs/PROTOCOL.md section 3): ``@person``, ``!priority``, ``#label``,
``due <when>``, a leading ``bug:`` style type and a leading ``HOME:`` project key.
Everything that is not a token becomes the summary.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

from .const import ISSUE_TYPES
from .model import InvalidError, clean_labels, clean_summary

WEEKDAY_NAMES = (
    ("mon", "monday", "man", "mandag"),
    ("tue", "tuesday", "tir", "tirsdag"),
    ("wed", "wednesday", "ons", "onsdag"),
    ("thu", "thursday", "tor", "torsdag"),
    ("fri", "friday", "fre", "fredag"),
    ("sat", "saturday", "lør", "lørdag", "loerdag"),
    ("sun", "sunday", "søn", "søndag", "soendag"),
)

PRIORITY_WORDS = {
    "highest": "highest",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "lowest": "lowest",
    "1": "highest",
    "2": "high",
    "3": "medium",
    "4": "low",
    "5": "lowest",
    # Danish aliases
    "vigtig": "high",
    "haster": "highest",
    "høj": "high",
    "hoej": "high",
    "lav": "low",
}

_TIME = r"(?:\s+(?:kl\.?\s*)?(?P<time>\d{1,2}[:.]\d{2}))?"
_WHEN = (
    r"(?P<when>"
    r"today|tomorrow|tmrw|next\s+week|in\s+\d+\s+(?:days?|weeks?)"
    r"|i\s+dag|i\s+morgen|i\s+overmorgen|næste\s+uge|om\s+\d+\s+(?:dage?|uger?)"
    r"|\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?"
    r"|[a-zæøå]{3,9}"
    r")"
)
DUE_RE = re.compile(rf"(?<!\S)(?:due|deadline|frist|senest)\s+{_WHEN}{_TIME}(?!\S)", re.IGNORECASE)
PREFIX_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9]{1,5})\s*:\s*")
ASSIGNEE_RE = re.compile(r"(?<!\S)@([\w.-]+)")
PRIORITY_RE = re.compile(r"(?<!\S)!([\w]+)")
LABEL_RE = re.compile(r"(?<!\S)#([\w-]+)")


@dataclass
class Person:
    """A person the quick-add parser can resolve ``@name`` to."""

    entity_id: str
    name: str


@dataclass
class Parsed:
    """Result of parsing one quick-add line."""

    summary: str = ""
    project: str | None = None
    type: str | None = None
    priority: str | None = None
    assignee: str | None = None
    labels: list[str] = field(default_factory=list)
    due: str | None = None
    unresolved: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly dict."""
        return asdict(self)


def _weekday_index(word: str) -> int | None:
    word = word.lower()
    for index, names in enumerate(WEEKDAY_NAMES):
        if word in names:
            return index
    return None


def _resolve_when(when: str, today: date) -> date | None:
    """Turn a due phrase into a date, or None if it is not understood."""
    text = " ".join(when.lower().split())
    if text in ("today", "i dag"):
        return today
    if text in ("tomorrow", "tmrw", "i morgen"):
        return today + timedelta(days=1)
    if text == "i overmorgen":
        return today + timedelta(days=2)
    if text in ("next week", "næste uge"):
        return today + timedelta(days=7 - today.weekday())
    if match := re.fullmatch(r"(?:in|om)\s+(\d+)\s+(\w+)", text):
        count = int(match.group(1))
        if match.group(2).startswith(("week", "uge")):
            return today + timedelta(weeks=count)
        return today + timedelta(days=count)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None
    if match := re.fullmatch(r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?", text):
        day, month = int(match.group(1)), int(match.group(2))
        year = int(match.group(3)) if match.group(3) else today.year
        if year < 100:
            year += 2000
        try:
            result = date(year, month, day)
        except ValueError:
            return None
        if not match.group(3) and result < today:
            result = date(year + 1, month, day)
        return result
    weekday = _weekday_index(text)
    if weekday is not None:
        delta = (weekday - today.weekday()) % 7 or 7
        return today + timedelta(days=delta)
    return None


def _match_person(token: str, people: list[Person], me: str | None) -> str | None:
    """Resolve an ``@token`` to a person entity id."""
    wanted = token.lower()
    if wanted == "me":
        return me
    exact = [p for p in people if wanted in (p.entity_id.split(".", 1)[1].lower(), p.name.lower())]
    if len(exact) == 1:
        return exact[0].entity_id
    prefix = [
        p
        for p in people
        if p.entity_id.split(".", 1)[1].lower().startswith(wanted)
        or p.name.lower().startswith(wanted)
    ]
    return prefix[0].entity_id if len(prefix) == 1 else None


def parse_quick_add(
    text: str,
    *,
    people: list[Person],
    project_keys: list[str],
    today: date,
    tz: tzinfo,
    me: str | None = None,
) -> Parsed:
    """Parse one line of quick-add text.

    Raises InvalidError when no summary is left.
    """
    parsed = Parsed()
    rest = str(text or "")

    # Leading "HOME:" and / or "bug:" prefixes (either order).
    for _ in range(2):
        match = PREFIX_RE.match(rest)
        if not match:
            break
        word = match.group(1)
        if parsed.project is None and word.upper() in project_keys:
            parsed.project = word.upper()
        elif parsed.type is None and word.lower() in ISSUE_TYPES:
            parsed.type = word.lower()
        else:
            break
        rest = rest[match.end() :]

    # due <when> [time]
    for match in list(DUE_RE.finditer(rest)):
        when = _resolve_when(match.group("when"), today)
        if when is None:
            continue
        due = when.isoformat()
        if match.group("time"):
            hour, minute = (int(x) for x in re.split(r"[:.]", match.group("time")))
            if hour < 24 and minute < 60:
                due = datetime(when.year, when.month, when.day, hour, minute, tzinfo=tz).isoformat()
        parsed.due = due
        rest = rest[: match.start()] + " " + rest[match.end() :]
        break

    def take(regex: re.Pattern[str], handler) -> None:
        nonlocal rest
        pieces: list[str] = []
        last = 0
        for match in regex.finditer(rest):
            if handler(match.group(1)):
                pieces.append(rest[last : match.start()])
                last = match.end()
        pieces.append(rest[last:])
        rest = " ".join(pieces)

    def on_assignee(token: str) -> bool:
        person = _match_person(token, people, me)
        if person is None:
            parsed.unresolved.append(f"@{token}")
            return False
        parsed.assignee = person
        return True

    def on_priority(token: str) -> bool:
        priority = PRIORITY_WORDS.get(token.lower())
        if priority is None:
            parsed.unresolved.append(f"!{token}")
            return False
        parsed.priority = priority
        return True

    def on_label(token: str) -> bool:
        parsed.labels.append(token)
        return True

    take(ASSIGNEE_RE, on_assignee)
    take(PRIORITY_RE, on_priority)
    take(LABEL_RE, on_label)

    parsed.labels = clean_labels(parsed.labels)
    try:
        parsed.summary = clean_summary(rest)
    except InvalidError as err:
        raise InvalidError("Nothing left to use as a title") from err
    return parsed
