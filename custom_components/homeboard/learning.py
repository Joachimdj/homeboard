"""The learning engine: suggestions and insights from the board and from everyday life.

Opt-in per feature, local only, explainable. It never changes anything by
itself: it makes suggestions (smart defaults, recurring chores, ignoring noisy
faults, a better digest time) that a person accepts or dismisses.

Persisted private state lives in ``HomeboardData.learning_data``:
``dismissed``, ``rhythm`` (per person weekday x hour counters), ``digest_times``
and ``health`` (per sensor reporting rhythm, closure / reopen counters, ignored keys).
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from . import insights
from .const import (
    CONF_DIGEST_ENABLED,
    CONF_HEALTH_EXCLUDE_ENTITIES,
    CONF_HEALTH_EXCLUDE_INTEGRATIONS,
    HEALTH_IGNORED_PLATFORMS,
    SAVE_DELAY,
)
from .model import InvalidError, NotFoundError, status_by_id
from .presence import is_home

if TYPE_CHECKING:
    from .data import HomeboardData

_LOGGER = logging.getLogger(__name__)

TICK = timedelta(minutes=5)
FEATURES = ("defaults", "patterns", "workload", "health", "rhythm")
MAX_TRACKED_SENSORS = 1500
MIN_UPDATES_FOR_SILENCE = 12
MAX_NORMAL_MINUTES = 720
SILENT_FACTOR = 8
SILENT_FLOOR_MINUTES = 180
IGNORE_AFTER = 3
MAX_NOTED = 200
LISTED = 20


def _reported(state: Any) -> float:
    """Return when the entity last wrote its state (even an unchanged one), as a timestamp."""
    moment = getattr(state, "last_reported", None) or state.last_updated
    return moment.timestamp()


def fmt_minutes(minutes: float) -> str:
    minutes = round(minutes)
    if minutes < 90:
        return f"{minutes} min"
    hours = minutes / 60
    return f"{hours:.0f} h" if hours < 48 else f"{hours / 24:.0f} days"


class LearningEngine:
    """Computes insights and keeps the small persisted counters."""

    def __init__(self, hass: HomeAssistant, manager: HomeboardData) -> None:
        """Initialise the engine (call ``async_start``)."""
        self.hass = hass
        self.manager = manager
        self._unsub: CALLBACK_TYPE | None = None
        self._suggestions: list[dict[str, Any]] = []
        self._tokens: dict[str, tuple[str, frozenset[str]]] = {}

    # ------------------------------------------------------------------ lifecycle

    @callback
    def async_start(self) -> None:
        """Start sampling and refreshing."""
        self._unsub = async_track_time_interval(self.hass, self._async_tick, TICK)
        self.refresh(signal=False)

    @callback
    def async_stop(self) -> None:
        """Stop sampling."""
        if self._unsub:
            self._unsub()
            self._unsub = None

    async def _async_tick(self, _now: datetime) -> None:
        self.sample()
        self.refresh()

    @property
    def data(self) -> dict[str, Any]:
        """Return the persisted private state."""
        return self.manager.learning_data

    def features(self) -> dict[str, bool]:
        """Return which features are switched on."""
        return dict(self.manager.settings()["learning"])

    def enabled(self, feature: str) -> bool:
        """Return True if a feature is on."""
        return bool(self.features().get(feature))

    def _save(self) -> None:
        self.manager._store.async_delay_save(self.manager._as_dict, SAVE_DELAY)

    # ------------------------------------------------------------------ corpus

    def rows(self) -> list[insights.Row]:
        """Return every issue (archived ones too) as learner rows."""
        manager = self.manager
        rows = []
        for issue in manager.issues.values():
            project = manager.projects.get(issue["project_id"])
            if project is None:
                continue
            cached = self._tokens.get(issue["id"])
            if cached is None or cached[0] != issue["summary"]:
                cached = (issue["summary"], insights.tokens(issue["summary"]))
                self._tokens[issue["id"]] = cached
            status = status_by_id(project, issue["status"])
            created = dt_util.parse_datetime(issue["created"])
            if created is None:
                continue
            rows.append(
                insights.Row(
                    id=issue["id"],
                    key=issue["key"],
                    project_id=issue["project_id"],
                    summary=issue["summary"],
                    tokens=cached[1],
                    assignee=issue["assignee"],
                    labels=list(issue["labels"]),
                    priority=issue["priority"],
                    type=issue["type"],
                    created=created,
                    due=insights.parse_due(issue["due"]),
                    resolved=dt_util.parse_datetime(issue["resolved"])
                    if issue["resolved"]
                    else None,
                    status=status["name"],
                    category=status["category"],
                    source=issue["source"],
                    recurring=bool(issue.get("recurring_id")),
                    archived=issue["archived"],
                )
            )
        if len(self._tokens) > len(manager.issues) + 50:
            self._tokens = {k: v for k, v in self._tokens.items() if k in manager.issues}
        return rows

    # ------------------------------------------------------------------ smart defaults

    def suggest(
        self, summary: str, *, project_id: str | None = None, skip: set[str] | None = None
    ) -> dict[str, Any] | None:
        """Suggest assignee / labels / priority / due offset for a new issue (None = nothing)."""
        if not self.enabled("defaults"):
            return None
        counts: dict[str, int] | None = None
        use_workload = self.enabled("workload")
        if use_workload:
            stats = self.manager.stats()["people"]
            counts = {p: stats.get(p, {}).get("open", 0) for p in self.manager.tracked_people()}
        return insights.suggest_defaults(
            summary,
            self.rows(),
            project_id=project_id,
            skip=skip or set(),
            open_counts=counts,
            use_workload=use_workload,
        )

    # ------------------------------------------------------------------ suggestions

    def open_count(self) -> int:
        """Return the number of open suggestions (for the badge)."""
        return len(self._suggestions)

    def refresh(self, *, signal: bool = True) -> None:
        """Recompute the suggestion list; signal the UI when the count changed."""
        before = [s["id"] for s in self._suggestions]
        self._suggestions = self._build_suggestions()
        if signal and before != [s["id"] for s in self._suggestions]:
            self.manager._signal()

    def _build_suggestions(self) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        if self.enabled("patterns"):
            known = [insights.tokens(r["summary"]) for r in self.manager.recurring.values()]
            for item in insights.find_patterns(self.rows(), dt_util.now().date()):
                words = insights.tokens(item["proposal"]["summary"])
                if not any(
                    insights.similarity(words, other) >= insights.CLUSTER_SIMILARITY
                    for other in known
                ):
                    found.append(item)
        if self.enabled("health"):
            found += self._health_suggestions()
        if self.enabled("rhythm") and self.manager.options.get(CONF_DIGEST_ENABLED, False):
            found += self._digest_suggestions()
        dismissed = set(self.data.get("dismissed", []))
        return [item for item in found if item["id"] not in dismissed]

    def _health_suggestions(self) -> list[dict[str, Any]]:
        health = self.data.get("health", {})
        ignored = set(health.get("ignored", []))
        found = []
        for key in set(health.get("closures", {})) | set(health.get("reopens", {})):
            closures = health.get("closures", {}).get(key, 0)
            reopens = health.get("reopens", {}).get(key, 0)
            if key in ignored or max(closures, reopens) < IGNORE_AFTER:
                continue
            summary = key
            for issue in sorted(
                self.manager.issues.values(), key=lambda i: i["number"], reverse=True
            ):
                if issue.get("dedupe_key") == key:
                    summary = issue["summary"]
                    break
            why = (
                f"You closed it {closures} times while the fault was still there"
                if closures >= reopens
                else f"It went away and came back {reopens} times"
            )
            found.append(
                {
                    "id": f"health_ignore:{key}",
                    "kind": "health_ignore",
                    "title": f"Stop reporting '{summary}'?",
                    "detail": why + ". Accepting stops Homeboard from creating this issue again.",
                    "evidence": {"closed": closures, "reopened": reopens},
                    "proposal": {"key": key, "summary": summary},
                }
            )
        return found

    def _digest_suggestions(self) -> list[dict[str, Any]]:
        found = []
        push = self.manager.push
        for person, block in (self.data.get("rhythm") or {}).items():
            picked = insights.suggest_digest_time(block["seen"], block["home"])
            if picked is None:
                continue
            at, share = picked
            current = push.digest_time(person).strftime("%H:%M") if push else None
            if at == current:
                continue
            state = self.hass.states.get(person)
            name = state.name if state else person
            found.append(
                {
                    "id": f"digest_time:{person}",
                    "kind": "digest_time",
                    "title": f"Send {name}'s morning digest at {at}?",
                    "detail": f"{name} is usually home around then on weekdays ({round(share * 100)}% of the time I have seen).",
                    "evidence": {"home_share": share},
                    "proposal": {"person": person, "time": at},
                }
            )
        return found

    def accept(self, suggestion_id: str) -> dict[str, Any]:
        """Apply a suggestion (always a user action). Returns what was done."""
        suggestion = next((s for s in self._suggestions if s["id"] == suggestion_id), None)
        if suggestion is None:
            raise NotFoundError(f"Unknown suggestion {suggestion_id!r}")
        proposal = suggestion["proposal"]
        manager = self.manager
        result: dict[str, Any] = {"applied": True}
        if suggestion["kind"] == "recurring":
            rec = manager.create_recurring(
                proposal["project_id"],
                summary=proposal["summary"],
                repeat=proposal["repeat"],
                next_due=proposal["next_due"],
                assignee=proposal.get("assignee"),
                labels=proposal.get("labels") or [],
                priority=proposal.get("priority") or "medium",
            )
            result["recurring_id"] = rec["id"]
        elif suggestion["kind"] == "health_ignore":
            health = self.data.setdefault("health", {})
            health.setdefault("ignored", []).append(proposal["key"])
            for issue in list(manager.issues.values()):
                if (
                    issue.get("dedupe_key") == proposal["key"]
                    and not issue["archived"]
                    and manager.category(issue) != "done"
                ):
                    manager.resolve_automatically(
                        issue["id"], "Ignored on your request (Insights)."
                    )
        elif suggestion["kind"] == "digest_time":
            self.data.setdefault("digest_times", {})[proposal["person"]] = proposal["time"]
        else:  # pragma: no cover - kinds are produced above
            raise InvalidError("Unknown suggestion kind")
        self._dismiss_id(suggestion_id)
        self._save()
        self.refresh()
        return result

    def dismiss(self, suggestion_id: str) -> None:
        """Dismiss a suggestion for good."""
        if not any(s["id"] == suggestion_id for s in self._suggestions):
            raise NotFoundError(f"Unknown suggestion {suggestion_id!r}")
        self._dismiss_id(suggestion_id)
        self._save()
        self.refresh()

    def _dismiss_id(self, suggestion_id: str) -> None:
        dismissed = self.data.setdefault("dismissed", [])
        if suggestion_id not in dismissed:
            dismissed.append(suggestion_id)

    def forget(self, feature: str | None = None) -> list[str]:
        """Forget what a feature stored (``None`` = everything). Returns what was cleared.

        Defaults, patterns and workload are computed live from the board's own
        issues, so only their dismissed suggestions are stored; the knowledge
        itself goes when the issues are deleted.
        """
        if feature is not None and feature not in FEATURES:
            raise InvalidError(f"feature must be one of {', '.join(FEATURES)}")
        cleared: list[str] = []
        data = self.data
        prefixes = {"patterns": "recurring:", "health": "health_ignore:", "rhythm": "digest_time:"}
        dismissed = data.get("dismissed", [])
        if feature is None:
            kept: list[str] = []
        elif feature in prefixes:
            kept = [d for d in dismissed if not d.startswith(prefixes[feature])]
        else:
            kept = dismissed
        if len(kept) != len(dismissed):
            cleared.append("dismissed suggestions")
        data["dismissed"] = kept
        if feature in (None, "health") and data.pop("health", None) is not None:
            cleared.append("sensor rhythms and fault history")
        if feature in (None, "rhythm"):
            if data.pop("rhythm", None) is not None:
                cleared.append("home / away rhythm")
            if data.pop("digest_times", None) is not None:
                cleared.append("learned digest times")
        self._save()
        self.refresh()
        return cleared

    # ------------------------------------------------------------------ sampling

    @callback
    def sample(self) -> None:
        """Take one sample of presence and sensor rhythm (every 5 minutes)."""
        if self.enabled("rhythm"):
            self._sample_presence()
        if self.enabled("health"):
            self._sample_sensors()

    def _sample_presence(self) -> None:
        now = dt_util.now()
        weekday, hour = now.weekday(), now.hour
        rhythm = self.data.setdefault("rhythm", {})
        changed = False
        for person in self.manager.tracked_people():
            home = is_home(self.hass, self.hass.states.get(person))
            if home is None:
                continue
            block = rhythm.setdefault(
                person, {"seen": insights.blank_grid(), "home": insights.blank_grid(), "samples": 0}
            )
            block["seen"][weekday][hour] += 1
            block["home"][weekday][hour] += int(home)
            block["samples"] += 1
            changed = True
        if changed:
            self._save()

    def _excluded(self) -> tuple[set[str], set[str]]:
        options = self.manager.options
        return (
            set(options.get(CONF_HEALTH_EXCLUDE_ENTITIES) or []),
            {str(i).lower() for i in options.get(CONF_HEALTH_EXCLUDE_INTEGRATIONS) or []},
        )

    def _sample_sensors(self) -> None:
        sensors: dict[str, dict[str, float]] = self.data.setdefault("health", {}).setdefault(
            "sensors", {}
        )
        registry = er.async_get(self.hass)
        excluded_entities, excluded_integrations = self._excluded()
        seen: set[str] = set()
        for state in self.hass.states.async_all("sensor"):
            if (
                state.attributes.get("restored")
                or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN)
                or state.attributes.get("state_class") is None
            ):
                continue
            entity_id = state.entity_id
            entry = registry.async_get(entity_id)
            if (
                entry is None
                or entry.device_id is None
                or entry.disabled_by
                or entry.hidden_by
                or entity_id in excluded_entities
                or entry.platform in HEALTH_IGNORED_PLATFORMS
                or entry.platform.lower() in excluded_integrations
            ):
                continue
            seen.add(entity_id)
            stamp = _reported(state)
            stat = sensors.get(entity_id)
            if stat is None:
                if len(sensors) < MAX_TRACKED_SENSORS:
                    sensors[entity_id] = {"n": 0, "ewma": 0.0, "last": stamp}
                continue
            if stamp <= stat["last"]:
                continue
            gap = (stamp - stat["last"]) / 60
            if gap >= 1 and (stat["n"] < 5 or gap <= 4 * stat["ewma"]):
                stat["ewma"] = round(gap if stat["n"] == 0 else 0.8 * stat["ewma"] + 0.2 * gap, 1)
                stat["n"] += 1
            stat["last"] = stamp
        for entity_id in [e for e in sensors if e not in seen and self.hass.states.get(e) is None]:
            del sensors[entity_id]
        self._save()

    def silent_candidates(self) -> list[dict[str, Any]]:
        """Sensors that normally report often but have been quiet for much longer."""
        sensors = (self.data.get("health") or {}).get("sensors") or {}
        now = dt_util.utcnow().timestamp()
        excluded_entities, _ = self._excluded()
        found = []
        for entity_id, stat in sensors.items():
            if stat["n"] < MIN_UPDATES_FOR_SILENCE or entity_id in excluded_entities:
                continue
            normal = max(stat["ewma"], 5.0)
            if normal > MAX_NORMAL_MINUTES:
                continue
            state = self.hass.states.get(entity_id)
            if (
                state is None
                or state.state == STATE_UNAVAILABLE
                or state.attributes.get("restored")
            ):
                continue  # unavailable devices are the offline detector's job
            last = stat["last"]
            if state.state != STATE_UNKNOWN:
                last = max(last, _reported(state))
            silent = (now - last) / 60
            if silent > max(SILENT_FACTOR * normal, SILENT_FLOOR_MINUTES):
                found.append(
                    {
                        "entity_id": entity_id,
                        "normal_minutes": round(normal),
                        "silent_minutes": round(silent),
                    }
                )
        return sorted(found, key=lambda c: c["silent_minutes"] / c["normal_minutes"], reverse=True)

    # -- counters fed by the health monitor

    def record_health(self, kind: str, key: str, issue_id: str | None = None) -> None:
        """Count a fault being closed by hand (``closures``) or coming back (``reopens``)."""
        if not self.enabled("health"):
            return
        health = self.data.setdefault("health", {})
        if kind == "closures" and issue_id:
            noted = health.setdefault("noted", [])
            if issue_id in noted:
                return
            noted.append(issue_id)
            del noted[:-MAX_NOTED]
        counters = health.setdefault(kind, {})
        counters[key] = counters.get(key, 0) + 1
        self._save()
        self.refresh()

    def health_ignored(self) -> set[str]:
        """Return the fault keys the user told Homeboard to stop reporting."""
        return set((self.data.get("health") or {}).get("ignored", []))

    # ------------------------------------------------------------------ insights page

    def insights(self) -> dict[str, Any]:
        """Return everything the Insights page shows."""
        features = self.features()
        manager = self.manager
        learned: dict[str, Any] = {}
        rows = self.rows() if (features["defaults"] or features["workload"]) else []
        if features["defaults"]:
            labels = Counter(label for r in rows if r.source != "health" for label in set(r.labels))
            people = Counter(r.assignee for r in rows if r.assignee and r.source != "health")
            learned["defaults"] = {
                "issues_analysed": sum(1 for r in rows if r.source != "health"),
                "top_labels": [[label, n] for label, n in labels.most_common(8)],
                "people": [{"person": p, "issues": n} for p, n in people.most_common()],
            }
        if features["workload"]:
            learned["workload"] = insights.workload(
                rows, manager.tracked_people(), dt_util.utcnow()
            )
        if features["rhythm"]:
            learned["rhythm"] = {
                "people": {
                    person: {
                        "samples": block["samples"],
                        "grid": insights.probabilities(block["seen"], block["home"]),
                    }
                    for person, block in (self.data.get("rhythm") or {}).items()
                }
            }
        if features["health"]:
            health = self.data.get("health") or {}
            flapping = []
            for key, count in sorted((health.get("reopens") or {}).items(), key=lambda kv: -kv[1]):
                if count >= 2:
                    flapping.append(
                        {"key": key, "summary": self._summary_for(key), "reopened": count}
                    )
            learned["health"] = {
                "tracked_sensors": len(health.get("sensors") or {}),
                "silent": self.silent_candidates()[:LISTED],
                "flapping": flapping[:LISTED],
            }
        return {"features": features, "suggestions": list(self._suggestions), "learned": learned}

    def _summary_for(self, key: str) -> str:
        for issue in sorted(self.manager.issues.values(), key=lambda i: i["number"], reverse=True):
            if issue.get("dedupe_key") == key:
                return issue["summary"]
        return key
