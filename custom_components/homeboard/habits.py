"""Find habits in state history (pure Python, no Home Assistant imports).

Input is, per entity, the chronological list of ``(local datetime, state)`` over the last weeks. Output is a
list of small dicts ("candidates"), each with the numbers that justify it. Nothing here is a black box: a
candidate says how many days it saw, out of how many, and in which window.

Three patterns (see ``docs/DESIGN-0.4.md``):

* ``routine``: an entity is switched to the same state at about the same time of day (every day, on weekdays
  or at weekends),
* ``follow_up``: a motion / door sensor turns on and a light or switch turns on within a minute,
* ``switch_back``: the light or switch turns off a few minutes after the sensor went quiet.
"""

from __future__ import annotations

import bisect
from collections import Counter
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any

WINDOW_MINUTES = 30
MIN_DAYS_OF_DATA = 7  # Home Assistant keeps 10 days of history unless purge_keep_days is raised
MIN_EVENT_DAYS = 5
MIN_SHARE = 0.7
FOLLOW_SECONDS = 60
MIN_ACTIVATIONS = 8
MIN_ACTIVATION_DAYS = 5
ACTIVATION_GAP = timedelta(minutes=5)
BACK_MIN_MINUTES = 1
BACK_MAX_MINUTES = 15
ROUND_MINUTES = 5
NIGHT_SHARE = 0.8
MAX_EVENTS_PER_DAY = 6  # a switch that toggles more often is cycled by something, not by a habit
WINDOW_EVENT_SHARE = 0.25  # a routine must hold a quarter of its switchings of that kind (flapping is caught by the per-day cap)
MAX_TARGET_ON_PER_DAY = 20
MAX_SENSOR_EVENTS = 300  # most recent activations looked at per sensor
BASE_RATE_FACTOR = 5  # a follow-up must beat chance by this much

DAY_GROUPS = ("all", "weekdays", "weekends")
ON_STATES = frozenset({"on", "open"})
OFF_STATES = frozenset({"off", "closed"})

Series = list[tuple[datetime, str]]
Transitions = list[tuple[datetime, str]]


def normalise(state: str) -> str | None:
    """Map a raw state to ``on`` / ``off`` (``None`` = not a switching state, e.g. unavailable)."""
    if state in ON_STATES:
        return "on"
    if state in OFF_STATES:
        return "off"
    return None


def transitions(series: Series) -> Transitions:
    """Return the real changes between on and off. The first state is the baseline, not an event."""
    out: Transitions = []
    previous: str | None = None
    for moment, raw in series:
        state = normalise(raw)
        if state is None:
            continue
        if previous is not None and state != previous:
            out.append((moment, state))
        previous = state
    return out


def group_dates(group: str, first: date, last: date) -> list[date]:
    """Return the days of ``first..last`` (inclusive) that belong to a day group."""
    days = [first + timedelta(days=n) for n in range((last - first).days + 1)]
    if group == "weekdays":
        return [d for d in days if d.weekday() < 5]
    if group == "weekends":
        return [d for d in days if d.weekday() >= 5]
    return days


def minute_of_day(moment: datetime) -> int:
    return moment.hour * 60 + moment.minute


def best_window(events: list[tuple[date, int]]) -> tuple[set[date], list[int]]:
    """Return ``(days, minutes)`` of the ``WINDOW_MINUTES`` wide window that holds the most distinct days."""
    ordered = sorted(events, key=lambda e: e[1])
    best_days: set[date] = set()
    best: list[int] = []
    left = 0
    counts: Counter[date] = Counter()
    for right, (day, minute) in enumerate(ordered):
        counts[day] += 1
        while minute - ordered[left][1] > WINDOW_MINUTES:
            gone = ordered[left][0]
            counts[gone] -= 1
            if counts[gone] == 0:
                del counts[gone]
            left += 1
        if len(counts) > len(best_days):
            best_days = set(counts)
            best = [m for _, m in ordered[left : right + 1]]
    return best_days, best


def hhmm(minute: int) -> str:
    minute = max(0, min(23 * 60 + 59, minute))
    return f"{minute // 60:02d}:{minute % 60:02d}"


def round_minute(value: float) -> int:
    return int(round(value / ROUND_MINUTES) * ROUND_MINUTES)


def _share_of(days: set[date], group: list[date]) -> float:
    return len(days & set(group)) / len(group) if group else 1.0


def find_routines(changes: dict[str, Transitions], first: date, last: date) -> list[dict[str, Any]]:
    """Entities that are switched to the same state at about the same time on most days."""
    found: list[dict[str, Any]] = []
    weekdays = group_dates("weekdays", first, last)
    weekends = group_dates("weekends", first, last)
    for entity_id, series in sorted(changes.items()):
        for action in ("on", "off"):
            events = [
                (moment.date(), minute_of_day(moment))
                for moment, state in series
                if state == action and first <= moment.date() <= last
            ]
            if len({d for d, _ in events}) < MIN_EVENT_DAYS:
                continue
            for group in DAY_GROUPS:
                days = set(group_dates(group, first, last))
                inside = [e for e in events if e[0] in days]
                if len({d for d, _ in inside}) < MIN_EVENT_DAYS:
                    continue
                if len(inside) / len(days) > MAX_EVENTS_PER_DAY:
                    continue  # flapping: it is cycled by something, there is no habit to find
                event_days, minutes = best_window(inside)
                count = len(event_days)
                share = count / len(days) if days else 0.0
                if count < MIN_EVENT_DAYS or share < MIN_SHARE:
                    continue
                if len(minutes) < WINDOW_EVENT_SHARE * len(inside):
                    continue  # most of its switchings are somewhere else
                if group == "all" and not (
                    _share_of(event_days, weekdays) >= MIN_SHARE
                    and (len(weekends) < 2 or _share_of(event_days, weekends) >= MIN_SHARE)
                ):
                    continue  # a Monday-to-Friday routine must not pass as "every day"
                at = round_minute(median(minutes))
                found.append(
                    {
                        "id": f"habit:time:{entity_id}:{action}:{group}",
                        "pattern": "routine",
                        "entity_id": entity_id,
                        "trigger_entity": None,
                        "action": action,
                        "day_group": group,
                        "time": hhmm(at),
                        "window": [hhmm(min(minutes)), hhmm(max(minutes))],
                        "days": count,
                        "of": len(days),
                        "share": round(share, 2),
                    }
                )
                if group == "all":
                    break  # every day beats weekdays / weekends
    return found


def _activations(series: Transitions, first: date, last: date) -> list[datetime]:
    """The moments a sensor turned on, ignoring repeats within ``ACTIVATION_GAP`` (the latest ``MAX_SENSOR_EVENTS``)."""
    out: list[datetime] = []
    for moment, state in series:
        if state != "on" or not first <= moment.date() <= last:
            continue
        if out and moment - out[-1] < ACTIVATION_GAP:
            continue
        out.append(moment)
    return out[-MAX_SENSOR_EVENTS:]


def _share(hits: int, total: int) -> float:
    return hits / total if total else 0.0


def _in_window(times: list[datetime], first: date, last: date) -> list[datetime]:
    return [t for t in times if first <= t.date() <= last]


def _base_rate(times: list[datetime], first: date, last: date, seconds: float) -> float:
    """The chance that a given moment is followed by one of ``times`` within ``seconds`` (by luck)."""
    span = ((last - first).days + 1) * 86400
    return min(1.0, len(times) * seconds / span)


def find_follow_ups(
    sensors: dict[str, Transitions],
    targets: dict[str, Transitions],
    first: date,
    last: date,
) -> list[dict[str, Any]]:
    """A sensor turns on and a light / switch turns on within a minute, again and again."""
    found: list[dict[str, Any]] = []
    window_days = (last - first).days + 1
    on_times: dict[str, list[datetime]] = {}
    for entity, series in targets.items():
        times = sorted(m for m, s in series if s == "on")
        inside = _in_window(times, first, last)
        if len(inside) >= MIN_ACTIVATIONS and len(inside) / window_days <= MAX_TARGET_ON_PER_DAY:
            on_times[entity] = times
    for sensor, series in sorted(sensors.items()):
        activations = _activations(series, first, last)
        activation_days = len({a.date() for a in activations})
        if len(activations) < MIN_ACTIVATIONS or activation_days < MIN_ACTIVATION_DAYS:
            continue
        for target, times in sorted(on_times.items()):
            needed = MIN_SHARE * len(activations)
            hits: list[datetime] = []
            for position, moment in enumerate(activations):
                index = bisect.bisect_right(times, moment)
                if index < len(times) and (times[index] - moment).total_seconds() <= FOLLOW_SECONDS:
                    hits.append(moment)
                if len(hits) + (len(activations) - position - 1) < needed:
                    break  # it can no longer reach the share: stop early
            share = _share(len(hits), len(activations))
            hit_days = len({h.date() for h in hits})
            if share < MIN_SHARE or hit_days < MIN_ACTIVATION_DAYS:
                continue
            chance = _base_rate(_in_window(times, first, last), first, last, FOLLOW_SECONDS)
            if share < BASE_RATE_FACTOR * chance:
                continue  # it turns on so often that this would happen anyway
            night = sum(1 for h in hits if h.hour >= 17 or h.hour < 7)
            found.append(
                {
                    "id": f"habit:follow:{sensor}:{target}:on",
                    "pattern": "follow_up",
                    "entity_id": target,
                    "trigger_entity": sensor,
                    "action": "on",
                    "day_group": "all",
                    "days": hit_days,
                    "of": activation_days,
                    "samples": len(hits),
                    "out_of": len(activations),
                    "share": round(share, 2),
                    "night_only": _share(night, len(hits)) >= NIGHT_SHARE,
                }
            )
    return found


def find_switch_backs(
    sensors: dict[str, Transitions],
    targets: dict[str, Transitions],
    first: date,
    last: date,
) -> list[dict[str, Any]]:
    """A light / switch turns off a few minutes after the sensor went quiet, again and again."""
    found: list[dict[str, Any]] = []
    window_days = (last - first).days + 1
    off_times: dict[str, list[datetime]] = {}
    for entity, series in targets.items():
        times = sorted(m for m, s in series if s == "off")
        inside = _in_window(times, first, last)
        if len(inside) >= MIN_ACTIVATIONS and len(inside) / window_days <= MAX_TARGET_ON_PER_DAY:
            off_times[entity] = times
    for sensor, series in sorted(sensors.items()):
        clears = [m for m, s in series if s == "off" and first <= m.date() <= last]
        clears = clears[-MAX_SENSOR_EVENTS:]
        wakes = sorted(m for m, s in series if s == "on")
        clear_days = len({c.date() for c in clears})
        if len(clears) < MIN_ACTIVATIONS or clear_days < MIN_ACTIVATION_DAYS:
            continue
        for target, times in sorted(off_times.items()):
            needed = MIN_SHARE * len(clears)
            delays: list[float] = []
            matched: list[datetime] = []
            for position, moment in enumerate(clears):
                index = bisect.bisect_right(times, moment)
                if index < len(times):
                    delay = (times[index] - moment).total_seconds() / 60
                    wake = bisect.bisect_right(
                        wakes, moment
                    )  # the sensor must stay quiet until then
                    quiet = not (wake < len(wakes) and wakes[wake] < times[index])
                    if BACK_MIN_MINUTES <= delay <= BACK_MAX_MINUTES and quiet:
                        delays.append(delay)
                        matched.append(moment)
                if len(delays) + (len(clears) - position - 1) < needed:
                    break
            share = _share(len(delays), len(clears))
            if share < MIN_SHARE or len(delays) < MIN_ACTIVATIONS:
                continue
            chance = _base_rate(
                _in_window(times, first, last),
                first,
                last,
                (BACK_MAX_MINUTES - BACK_MIN_MINUTES) * 60,
            )
            if share < BASE_RATE_FACTOR * chance:
                continue
            found.append(
                {
                    "id": f"habit:back:{sensor}:{target}:off",
                    "pattern": "switch_back",
                    "entity_id": target,
                    "trigger_entity": sensor,
                    "action": "off",
                    "day_group": "all",
                    "delay_minutes": max(BACK_MIN_MINUTES, round(median(delays))),
                    "days": len({m.date() for m in matched}),
                    "of": clear_days,
                    "samples": len(delays),
                    "out_of": len(clears),
                    "share": round(share, 2),
                }
            )
    return found


def mine(
    targets: dict[str, Series],
    sensors: dict[str, Series],
    *,
    today: date,
    days: int = 28,
) -> dict[str, Any]:
    """Run every pattern. ``today`` is the local date; only complete days before it are used.

    The window is the last ``days`` complete days, or as many as the history has (at least
    ``MIN_DAYS_OF_DATA``). Returns ``{"candidates": [...], "history_days": n, "error": None | "no_history"}``.
    """
    last = today - timedelta(days=1)
    # the first item of each series is the state at the start of the window: only later items are activity
    seen = [moment for series in (*targets.values(), *sensors.values()) for moment, _ in series[1:]]
    history_days = (last - min(seen).date()).days if seen else 0  # the first day is usually cut
    if history_days < MIN_DAYS_OF_DATA:
        return {"candidates": [], "history_days": max(history_days, 0), "error": "no_history"}
    # judge shares over the days that really have history, up to ``days``
    first = max(last - timedelta(days=days - 1), min(seen).date() + timedelta(days=1))
    target_changes = {entity: transitions(series) for entity, series in targets.items()}
    sensor_changes = {entity: transitions(series) for entity, series in sensors.items()}
    candidates = [
        *find_routines(target_changes, first, last),
        *find_follow_ups(sensor_changes, target_changes, first, last),
        *find_switch_backs(sensor_changes, target_changes, first, last),
    ]
    return {"candidates": candidates, "history_days": history_days, "error": None}
