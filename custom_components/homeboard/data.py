"""The Homeboard data manager: the single mutation point over the store.

Every change goes through a public method here, which validates, applies,
records activity, fires bus events, signals the entities / websocket
subscribers and schedules a (debounced) save. Entities, services and the
websocket API are thin views over this class.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from . import model, recurrence
from .const import (
    ACTIVITY_LIMIT,
    COMMENT_MAX_LENGTH,
    CONF_AUTO_ARCHIVE_DAYS,
    CONF_DUE_SOON_HOURS,
    CONF_HEALTH_ENABLED,
    CONF_PANEL_TITLE,
    CONF_TRACKED_PEOPLE,
    DEFAULT_AUTO_ARCHIVE_DAYS,
    DEFAULT_DUE_SOON_HOURS,
    DEFAULT_PANEL_TITLE,
    EVENT_ISSUE_ASSIGNED,
    EVENT_ISSUE_COMMENTED,
    EVENT_ISSUE_COMPLETED,
    EVENT_ISSUE_CREATED,
    EVENT_ISSUE_DELETED,
    EVENT_ISSUE_DUE_SOON,
    EVENT_ISSUE_MOVED,
    EVENT_ISSUE_OVERDUE,
    EVENT_ISSUE_REOPENED,
    EVENT_ISSUE_UPDATED,
    EVENT_PROJECT_CHANGED,
    EVENT_WIP_EXCEEDED,
    ORDER_STEP,
    PANEL_URL_PATH,
    SAVE_DELAY,
    SIGNAL_UPDATED,
)
from .model import (
    ConflictError,
    InvalidError,
    NotFoundError,
    check_category,
    check_person,
    check_priority,
    check_source,
    check_type,
    check_wip,
    clean_labels,
    clean_summary,
    clean_text,
    compute_rank,
    default_status,
    first_with_category,
    new_id,
    normalize_due,
    normalize_key,
    resolve_status,
    sort_key,
    status_by_id,
)
from .quickadd import Parsed, Person, parse_quick_add
from .stats import compute_stats, issue_flags
from .store import HomeboardStore

_LOGGER = logging.getLogger(__name__)

TICK_INTERVAL = timedelta(minutes=5)

UNSET: Any = object()
"""Marks "argument not given" where ``None`` is a meaningful value."""

EDITABLE_FIELDS = (
    "summary",
    "description",
    "type",
    "priority",
    "assignee",
    "labels",
    "due",
    "parent",
    "archived",
)


def _utc_iso() -> str:
    return dt_util.utcnow().isoformat(timespec="seconds")


class HomeboardData:
    """All projects, issues and recurring chores, plus the rules that change them."""

    def __init__(
        self,
        hass: HomeAssistant,
        store: HomeboardStore,
        options: Mapping[str, Any] | None = None,
    ) -> None:
        """Initialise an empty manager (call ``async_load``)."""
        self.hass = hass
        self._store = store
        self.options: Mapping[str, Any] = options or {}
        self.projects: dict[str, dict[str, Any]] = {}
        self.issues: dict[str, dict[str, Any]] = {}
        self.recurring: dict[str, dict[str, Any]] = {}
        self._unsub_tick: CALLBACK_TYPE | None = None
        self._stats_cache: dict[str, Any] | None = None
        self.version = "0"
        self.health: Any = None
        """The ``HealthMonitor`` (set by the integration setup)."""

    # ------------------------------------------------------------------ lifecycle

    async def async_load(self) -> None:
        """Load the store."""
        raw = await self._store.async_load() or {}
        self.projects = raw.get("projects", {})
        self.issues = raw.get("issues", {})
        self.recurring = raw.get("recurring", {})

    def _as_dict(self) -> dict[str, Any]:
        return {
            "projects": self.projects,
            "issues": self.issues,
            "recurring": self.recurring,
        }

    async def async_save_now(self) -> None:
        """Write the store immediately."""
        await self._store.async_save(self._as_dict())

    @callback
    def async_start(self) -> None:
        """Start the clock-driven checks (overdue, auto-archive, recurring)."""
        self._unsub_tick = async_track_time_interval(
            self.hass, self._async_tick_listener, TICK_INTERVAL
        )
        self.async_tick()

    @callback
    def async_stop(self) -> None:
        """Stop the clock-driven checks."""
        if self._unsub_tick:
            self._unsub_tick()
            self._unsub_tick = None

    async def _async_tick_listener(self, _now: datetime) -> None:
        self.async_tick()

    # ------------------------------------------------------------------ settings

    @property
    def due_soon_hours(self) -> int:
        """Return the due-soon window in hours."""
        return int(self.options.get(CONF_DUE_SOON_HOURS, DEFAULT_DUE_SOON_HOURS))

    @property
    def auto_archive_days(self) -> int:
        """Return after how many days done issues are archived (0 = never)."""
        return int(self.options.get(CONF_AUTO_ARCHIVE_DAYS, DEFAULT_AUTO_ARCHIVE_DAYS))

    def settings(self) -> dict[str, Any]:
        """Return the settings block of the frontend payload."""
        return {
            "due_soon_hours": self.due_soon_hours,
            "panel_title": self.options.get(CONF_PANEL_TITLE, DEFAULT_PANEL_TITLE),
            "auto_archive_done_days": self.auto_archive_days,
            "health_enabled": bool(self.options.get(CONF_HEALTH_ENABLED, True)),
        }

    # ------------------------------------------------------------------ people

    def people(self) -> list[dict[str, Any]]:
        """Return all HA person entities."""
        people = []
        for state in self.hass.states.async_all("person"):
            people.append(
                {
                    "entity_id": state.entity_id,
                    "name": state.attributes.get("friendly_name") or state.name,
                    "picture": state.attributes.get("entity_picture"),
                    "user_id": state.attributes.get("user_id"),
                }
            )
        return sorted(people, key=lambda p: p["name"].lower())

    def tracked_people(self) -> list[str]:
        """Return person entity ids that get their own sensors."""
        chosen = self.options.get(CONF_TRACKED_PEOPLE) or []
        if chosen:
            return list(chosen)
        return [p["entity_id"] for p in self.people()]

    def person_for_user(self, user_id: str | None) -> str | None:
        """Map a Home Assistant user id to its person entity id."""
        if not user_id:
            return None
        for person in self.people():
            if person["user_id"] == user_id:
                return person["entity_id"]
        return None

    def _check_assignee(self, value: Any) -> str | None:
        person = check_person(value)
        if person is not None and self.hass.states.get(person) is None:
            raise InvalidError(f"Unknown person {person}")
        return person

    # ------------------------------------------------------------------ lookups

    def resolve_project(self, ref: str) -> dict[str, Any]:
        """Return a project by id or key."""
        ref = str(ref).strip()
        if ref in self.projects:
            return self.projects[ref]
        for project in self.projects.values():
            if project["key"] == ref.upper():
                return project
        raise NotFoundError(f"Unknown project {ref!r}")

    def resolve_issue(
        self,
        ref: str | None = None,
        *,
        project: str | None = None,
        dedupe_key: str | None = None,
    ) -> dict[str, Any]:
        """Return an issue by id / key, or by project + dedupe key."""
        if ref:
            ref = str(ref).strip()
            if ref in self.issues:
                return self.issues[ref]
            wanted = ref.upper()
            for issue in self.issues.values():
                if issue["key"] == wanted:
                    return issue
            raise NotFoundError(f"Unknown issue {ref!r}")
        if project and dedupe_key:
            found = self.find_by_dedupe(self.resolve_project(project), dedupe_key)
            if found:
                return found
            raise NotFoundError(f"No issue with dedupe_key {dedupe_key!r} in {project}")
        raise InvalidError("Give either issue, or project together with dedupe_key")

    def find_by_dedupe(
        self,
        project: dict[str, Any],
        dedupe_key: str,
        *,
        open_only: bool = True,
        include_archived: bool = False,
    ) -> dict[str, Any] | None:
        """Return the newest issue of the project with this dedupe key."""
        matches = [
            issue
            for issue in self.issues.values()
            if issue["project_id"] == project["id"]
            and issue.get("dedupe_key") == dedupe_key
            and (include_archived or not issue["archived"])
            and (not open_only or self.category(issue) != "done")
        ]
        return max(matches, key=lambda i: i["number"], default=None)

    def category(self, issue: dict[str, Any]) -> str:
        """Return the category of the issue's status."""
        project = self.projects[issue["project_id"]]
        return status_by_id(project, issue["status"])["category"]

    def project_issues(
        self, project_id: str, *, include_archived: bool = False
    ) -> list[dict[str, Any]]:
        """Return a project's issues ordered by rank."""
        return sorted(
            (
                issue
                for issue in self.issues.values()
                if issue["project_id"] == project_id and (include_archived or not issue["archived"])
            ),
            key=sort_key,
        )

    # ------------------------------------------------------------------ plumbing

    def _issue_event(self, issue: dict[str, Any], actor: str | None, source: str) -> dict[str, Any]:
        project = self.projects[issue["project_id"]]
        status = status_by_id(project, issue["status"])
        return {
            "project": project["key"],
            "project_id": project["id"],
            "key": issue["key"],
            "issue_id": issue["id"],
            "summary": issue["summary"],
            "type": issue["type"],
            "priority": issue["priority"],
            "status": status["name"],
            "category": status["category"],
            "assignee": issue["assignee"],
            "reporter": issue["reporter"],
            "labels": list(issue["labels"]),
            "due": issue["due"],
            "actor": actor,
            "source": source,
            "url": f"/{PANEL_URL_PATH}?issue={issue['key']}",
        }

    def _commit(self, events: list[tuple[str, dict[str, Any]]] | None = None) -> None:
        self._store.async_delay_save(self._as_dict, SAVE_DELAY)
        for name, data in events or []:
            self.hass.bus.async_fire(name, data)
        self._signal()

    def _signal(self) -> None:
        """Invalidate caches and tell entities / subscribers to refresh."""
        self._stats_cache = None
        async_dispatcher_send(self.hass, SIGNAL_UPDATED)

    @staticmethod
    def _activity(
        issue: dict[str, Any],
        actor: str | None,
        kind: str,
        field: str | None = None,
        old: Any = None,
        new: Any = None,
    ) -> None:
        issue["activity"].append(
            {
                "ts": _utc_iso(),
                "actor": actor,
                "kind": kind,
                "field": field,
                "from": old,
                "to": new,
            }
        )
        del issue["activity"][:-ACTIVITY_LIMIT]

    def _touch(self, issue: dict[str, Any]) -> None:
        issue["updated"] = _utc_iso()

    def _remember_labels(self, project: dict[str, Any], labels: list[str]) -> None:
        extra = [label for label in labels if label not in project["labels"]]
        if extra:
            project["labels"] = sorted({*project["labels"], *extra})

    # ------------------------------------------------------------------ projects

    def create_project(
        self,
        *,
        key: str,
        name: str,
        description: str = "",
        color: str = "#2f80ed",
        icon: str = "mdi:view-column",
        lead: str | None = None,
        template: str = "household",
        statuses: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a project (one board)."""
        key = normalize_key(key)
        if any(p["key"] == key for p in self.projects.values()):
            raise ConflictError(f"Project key {key} already exists")
        if statuses is None:
            statuses = model.build_statuses(template)
        else:
            statuses = [
                {
                    "id": new_id(),
                    "name": clean_text(s["name"], "status name", max_len=40, required=True),
                    "category": check_category(s["category"]),
                    "backlog": bool(s.get("backlog", False)),
                    "wip": check_wip(s.get("wip")),
                }
                for s in statuses
            ]
        model.check_statuses(statuses)
        project = {
            "id": new_id(),
            "key": key,
            "name": clean_text(name, "name", max_len=60, required=True, single_line=True),
            "description": clean_text(description, "description", max_len=2000),
            "color": clean_text(color, "color", max_len=20) or "#2f80ed",
            "icon": clean_text(icon, "icon", max_len=60) or "mdi:view-column",
            "lead": self._check_assignee(lead),
            "default_assignee": None,
            "archived": False,
            "created": _utc_iso(),
            "statuses": statuses,
            "labels": [],
            "issue_seq": 0,
        }
        self.projects[project["id"]] = project
        self._commit([self._project_event(project, "created")])
        return project

    def _project_event(self, project: dict[str, Any], action: str) -> tuple[str, dict[str, Any]]:
        return (
            EVENT_PROJECT_CHANGED,
            {"project": project["key"], "project_id": project["id"], "action": action},
        )

    def update_project(self, ref: str, **fields: Any) -> dict[str, Any]:
        """Update project fields (name, description, color, icon, lead, default_assignee, archived, labels)."""
        project = self.resolve_project(ref)
        for name, value in fields.items():
            if value is UNSET:
                continue
            if name == "name":
                project["name"] = clean_text(
                    value, "name", max_len=60, required=True, single_line=True
                )
            elif name == "description":
                project["description"] = clean_text(value, "description", max_len=2000)
            elif name in ("color", "icon"):
                project[name] = clean_text(value, name, max_len=60) or project[name]
            elif name in ("lead", "default_assignee"):
                project[name] = self._check_assignee(value)
            elif name == "archived":
                project["archived"] = bool(value)
            elif name == "labels":
                project["labels"] = clean_labels(value)
            else:
                raise InvalidError(f"Cannot update project field {name!r}")
        self._commit([self._project_event(project, "updated")])
        return project

    def delete_project(self, ref: str) -> None:
        """Delete a project with all its issues and recurring chores."""
        project = self.resolve_project(ref)
        event = self._project_event(project, "deleted")
        removed = [i for i, v in self.issues.items() if v["project_id"] == project["id"]]
        for issue_id in removed:
            del self.issues[issue_id]
        for rec_id in [r for r, v in self.recurring.items() if v["project_id"] == project["id"]]:
            del self.recurring[rec_id]
        del self.projects[project["id"]]
        self._commit([event])

    # ------------------------------------------------------------------ statuses

    def add_status(
        self,
        project_ref: str,
        *,
        name: str,
        category: str,
        backlog: bool = False,
        wip: int | None = None,
        position: int | None = None,
    ) -> dict[str, Any]:
        """Add a status (column) to a project."""
        project = self.resolve_project(project_ref)
        status = {
            "id": new_id(),
            "name": clean_text(name, "status name", max_len=40, required=True, single_line=True),
            "category": check_category(category),
            "backlog": bool(backlog),
            "wip": check_wip(wip),
        }
        statuses = list(project["statuses"])
        statuses.insert(len(statuses) if position is None else max(0, position), status)
        model.check_statuses(statuses)
        project["statuses"] = statuses
        self._commit([self._project_event(project, "updated")])
        return status

    def update_status(self, project_ref: str, status_ref: str, **fields: Any) -> dict[str, Any]:
        """Update a status: name, category, backlog, wip."""
        project = self.resolve_project(project_ref)
        status = resolve_status(project, status_ref)
        previous = status["category"]
        candidate = dict(status)
        for name, value in fields.items():
            if value is UNSET:
                continue
            if name == "name":
                candidate["name"] = clean_text(
                    value, "status name", max_len=40, required=True, single_line=True
                )
            elif name == "category":
                candidate["category"] = check_category(value)
            elif name == "backlog":
                candidate["backlog"] = bool(value)
            elif name == "wip":
                candidate["wip"] = check_wip(value)
            else:
                raise InvalidError(f"Cannot update status field {name!r}")
        statuses = [candidate if s is status else s for s in project["statuses"]]
        model.check_statuses(statuses)
        status.update(candidate)
        if status["category"] != previous:
            for issue in self.issues.values():
                if issue["project_id"] == project["id"] and issue["status"] == status["id"]:
                    issue["resolved"] = (
                        issue["resolved"] or _utc_iso() if status["category"] == "done" else None
                    )
        self._commit([self._project_event(project, "updated")])
        return status

    def reorder_statuses(self, project_ref: str, status_ids: list[str]) -> None:
        """Reorder statuses; ``status_ids`` must be the complete list."""
        project = self.resolve_project(project_ref)
        current = {s["id"]: s for s in project["statuses"]}
        if sorted(status_ids) != sorted(current) or len(set(status_ids)) != len(status_ids):
            raise InvalidError("status_ids must list every status exactly once")
        project["statuses"] = [current[i] for i in status_ids]
        self._commit([self._project_event(project, "updated")])

    def remove_status(
        self, project_ref: str, status_ref: str, *, move_to: str | None = None
    ) -> None:
        """Remove a status; its issues go to ``move_to`` (required when not empty)."""
        project = self.resolve_project(project_ref)
        status = resolve_status(project, status_ref)
        members = [
            i
            for i in self.project_issues(project["id"], include_archived=True)
            if i["status"] == status["id"]
        ]
        statuses = [s for s in project["statuses"] if s is not status]
        model.check_statuses(statuses)
        if members:
            if move_to is None:
                raise ConflictError("The status still has issues: pass move_to")
            target = resolve_status(project, move_to)
            if target is status:
                raise InvalidError("move_to must be a different status")
            rank = max(
                (
                    i["rank"]
                    for i in self.issues.values()
                    if i["project_id"] == project["id"] and i["status"] == target["id"]
                ),
                default=0,
            )
            for issue in members:
                rank += ORDER_STEP
                issue["status"] = target["id"]
                issue["rank"] = rank
                issue["resolved"] = (
                    issue["resolved"] or _utc_iso() if target["category"] == "done" else None
                )
                self._touch(issue)
        project["statuses"] = statuses
        self._commit([self._project_event(project, "updated")])

    # ------------------------------------------------------------------ issues

    def create_issue(
        self,
        project_ref: str,
        summary: str,
        *,
        type: str | None = None,
        priority: str | None = None,
        assignee: Any = UNSET,
        labels: list[str] | None = None,
        due: Any = None,
        description: str = "",
        status: str | None = None,
        parent: str | None = None,
        dedupe_key: str | None = None,
        on_duplicate: str = "skip",
        recurring_id: str | None = None,
        actor: str | None = None,
        source: str = "service",
    ) -> tuple[dict[str, Any], bool]:
        """Create an issue. Returns ``(issue, created)``; ``created`` is False for a dedupe hit."""
        project = self.resolve_project(project_ref)
        source = check_source(source)
        summary = clean_summary(summary)
        if on_duplicate not in ("skip", "comment", "reopen"):
            raise InvalidError("on_duplicate must be skip, comment or reopen")

        if dedupe_key:
            existing = self.find_by_dedupe(project, dedupe_key)
            if existing is None and on_duplicate == "reopen":
                existing = self.find_by_dedupe(project, dedupe_key, open_only=False)
                if existing is not None:
                    self.move_issue(
                        existing["id"], default_status(project)["id"], actor=actor, source=source
                    )
                    return existing, False
            if existing is not None:
                if on_duplicate == "comment":
                    self.add_comment(existing["id"], summary, actor=actor, source=source)
                return existing, False

        if project["archived"]:
            raise InvalidError(f"Project {project['key']} is archived")
        target = resolve_status(project, status) if status else default_status(project)
        if assignee is UNSET:
            assignee = project["default_assignee"]
        assignee = self._check_assignee(assignee)
        labels = clean_labels(labels)
        parent_id = self._check_parent(project, None, parent)

        project["issue_seq"] += 1
        now = _utc_iso()
        neighbours = [
            (i["id"], i["rank"])
            for i in self.project_issues(project["id"])
            if i["status"] == target["id"]
        ]
        rank, rebalanced = compute_rank(neighbours, None)
        for other_id, other_rank in rebalanced.items():
            self.issues[other_id]["rank"] = other_rank
        issue = {
            "id": new_id(),
            "project_id": project["id"],
            "number": project["issue_seq"],
            "key": f"{project['key']}-{project['issue_seq']}",
            "type": check_type(type),
            "summary": summary,
            "description": clean_text(description, "description", max_len=20000),
            "status": target["id"],
            "priority": check_priority(priority),
            "assignee": assignee,
            "reporter": actor,
            "labels": labels,
            "parent": parent_id,
            "due": normalize_due(due),
            "rank": rank,
            "dedupe_key": dedupe_key or None,
            "recurring_id": recurring_id,
            "source": source,
            "created": now,
            "updated": now,
            "resolved": now if target["category"] == "done" else None,
            "archived": False,
            "overdue_notified": False,
            "due_soon_notified": False,
            "auto_resolved": False,
            "comments": [],
            "activity": [],
        }
        self._activity(issue, actor, "created")
        self.issues[issue["id"]] = issue
        self._remember_labels(project, labels)
        events = [(EVENT_ISSUE_CREATED, self._issue_event(issue, actor, source))]
        events.extend(self._wip_events(project, target, actor, source))
        self._commit(events)
        return issue, True

    def _check_parent(
        self, project: dict[str, Any], issue: dict[str, Any] | None, parent: Any
    ) -> str | None:
        if parent in (None, ""):
            return None
        epic = self.resolve_issue(parent)
        if epic["project_id"] != project["id"] or epic["type"] != "epic":
            raise InvalidError("parent must be an epic in the same project")
        if issue is not None and epic["id"] == issue["id"]:
            raise InvalidError("An issue cannot be its own parent")
        return epic["id"]

    def update_issue(
        self,
        ref: str,
        *,
        actor: str | None = None,
        source: str = "service",
        **fields: Any,
    ) -> dict[str, Any]:
        """Update editable fields (status changes go through ``move_issue``)."""
        issue = self.resolve_issue(ref)
        project = self.projects[issue["project_id"]]
        source = check_source(source)
        changes: dict[str, dict[str, Any]] = {}

        def apply(field: str, value: Any) -> None:
            if issue[field] != value:
                changes[field] = {"from": issue[field], "to": value}
                issue[field] = value

        for name, value in fields.items():
            if value is UNSET:
                continue
            if name not in EDITABLE_FIELDS:
                raise InvalidError(f"Cannot update issue field {name!r}")
            if name == "summary":
                apply("summary", clean_summary(value))
            elif name == "description":
                apply("description", clean_text(value, "description", max_len=20000))
            elif name == "type":
                new_type = check_type(value)
                if (
                    issue["type"] == "epic"
                    and new_type != "epic"
                    and any(i["parent"] == issue["id"] for i in self.issues.values())
                ):
                    raise ConflictError("The epic still has linked issues")
                apply("type", new_type)
            elif name == "priority":
                apply("priority", check_priority(value))
            elif name == "assignee":
                apply("assignee", self._check_assignee(value))
            elif name == "labels":
                labels = clean_labels(value)
                self._remember_labels(project, labels)
                apply("labels", labels)
            elif name == "due":
                apply("due", normalize_due(value))
                if "due" in changes:
                    issue["overdue_notified"] = issue["due_soon_notified"] = False
            elif name == "parent":
                apply("parent", self._check_parent(project, issue, value))
            elif name == "archived":
                apply("archived", bool(value))
        if not changes:
            return issue

        self._touch(issue)
        for name, change in changes.items():
            if name == "assignee":
                kind = "assigned"
            elif name == "archived":
                kind = "archived"
            else:
                kind = "updated"
            self._activity(issue, actor, kind, name, change["from"], change["to"])
        data = self._issue_event(issue, actor, source)
        events = [(EVENT_ISSUE_UPDATED, {**data, "changes": changes})]
        if "assignee" in changes:
            events.append(
                (
                    EVENT_ISSUE_ASSIGNED,
                    {
                        **data,
                        "from_assignee": changes["assignee"]["from"],
                        "to_assignee": changes["assignee"]["to"],
                    },
                )
            )
        self._commit(events)
        return issue

    def move_issue(
        self,
        ref: str,
        status_ref: str,
        *,
        before: str | None = None,
        position: str | None = None,
        actor: str | None = None,
        source: str = "service",
    ) -> dict[str, Any]:
        """Move an issue to a status, optionally in front of another issue."""
        issue = self.resolve_issue(ref)
        project = self.projects[issue["project_id"]]
        source = check_source(source)
        target = resolve_status(project, status_ref)
        old_status = status_by_id(project, issue["status"])
        neighbours = [
            (i["id"], i["rank"])
            for i in self.project_issues(project["id"])
            if i["status"] == target["id"] and i["id"] != issue["id"]
        ]
        before_id = None
        if before:
            before_id = self.resolve_issue(before)["id"]
        elif position == "top" and neighbours:
            before_id = neighbours[0][0]
        elif position not in (None, "top", "bottom"):
            raise InvalidError("position must be top or bottom")
        rank, rebalanced = compute_rank(neighbours, before_id)
        for other_id, other_rank in rebalanced.items():
            self.issues[other_id]["rank"] = other_rank

        status_changed = target["id"] != old_status["id"]
        if not status_changed and rank == issue["rank"]:
            return issue
        issue["rank"] = rank
        if not status_changed:
            self._commit()
            return issue

        issue["status"] = target["id"]
        self._touch(issue)
        entering_done = target["category"] == "done" and old_status["category"] != "done"
        leaving_done = old_status["category"] == "done" and target["category"] != "done"
        if entering_done:
            issue["resolved"] = _utc_iso()
        elif leaving_done:
            issue["resolved"] = None
            issue["auto_resolved"] = False
            issue["overdue_notified"] = issue["due_soon_notified"] = False
        self._activity(issue, actor, "moved", "status", old_status["name"], target["name"])
        if entering_done:
            self._activity(issue, actor, "completed")
        elif leaving_done:
            self._activity(issue, actor, "reopened")

        data = self._issue_event(issue, actor, source)
        events = [
            (
                EVENT_ISSUE_MOVED,
                {
                    **data,
                    "from_status": old_status["name"],
                    "to_status": target["name"],
                    "from_category": old_status["category"],
                    "to_category": target["category"],
                },
            )
        ]
        if entering_done:
            events.append((EVENT_ISSUE_COMPLETED, data))
        elif leaving_done:
            events.append((EVENT_ISSUE_REOPENED, data))
        events.extend(self._wip_events(project, target, actor, source))
        self._commit(events)
        return issue

    def resolve_automatically(self, ref: str, reason: str) -> dict[str, Any]:
        """Close an issue on Homeboard's own initiative (the health scanner)."""
        issue = self.resolve_issue(ref)
        project = self.projects[issue["project_id"]]
        self.move_issue(issue["id"], first_with_category(project, "done")["id"], source="health")
        issue["auto_resolved"] = True
        self.add_comment(issue["id"], reason, source="health")
        return issue

    def reopen_automatically(self, ref: str, reason: str) -> dict[str, Any]:
        """Reopen an issue because the problem is back (the health scanner)."""
        issue = self.resolve_issue(ref)
        project = self.projects[issue["project_id"]]
        self.move_issue(issue["id"], default_status(project)["id"], source="health")
        self.add_comment(issue["id"], reason, source="health")
        return issue

    def _wip_events(
        self,
        project: dict[str, Any],
        status: dict[str, Any],
        actor: str | None,
        source: str,
    ) -> list[tuple[str, dict[str, Any]]]:
        wip = status.get("wip")
        if not wip or status["category"] == "done":
            return []
        count = sum(
            1
            for i in self.issues.values()
            if i["project_id"] == project["id"]
            and i["status"] == status["id"]
            and not i["archived"]
        )
        if count <= wip:
            return []
        return [
            (
                EVENT_WIP_EXCEEDED,
                {
                    "project": project["key"],
                    "project_id": project["id"],
                    "status": status["name"],
                    "wip": wip,
                    "count": count,
                    "actor": actor,
                    "source": source,
                },
            )
        ]

    def add_comment(
        self,
        ref: str,
        text: str,
        *,
        actor: str | None = None,
        source: str = "service",
    ) -> dict[str, Any]:
        """Append a comment."""
        issue = self.resolve_issue(ref)
        comment = {
            "id": new_id(),
            "author": actor,
            "ts": _utc_iso(),
            "text": clean_text(text, "text", max_len=COMMENT_MAX_LENGTH, required=True),
        }
        issue["comments"].append(comment)
        self._touch(issue)
        self._activity(issue, actor, "commented")
        data = self._issue_event(issue, actor, check_source(source))
        self._commit([(EVENT_ISSUE_COMMENTED, {**data, "comment": comment})])
        return comment

    def delete_issue(self, ref: str, *, actor: str | None = None, source: str = "service") -> None:
        """Delete an issue for good."""
        issue = self.resolve_issue(ref)
        data = self._issue_event(issue, actor, check_source(source))
        del self.issues[issue["id"]]
        for other in self.issues.values():
            if other["parent"] == issue["id"]:
                other["parent"] = None
        self._commit([(EVENT_ISSUE_DELETED, data)])

    def list_issues(
        self,
        *,
        project: str | None = None,
        archived: bool = False,
        query: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return ``(page, total)`` of issues, newest first, for archive / search views."""
        project_id = self.resolve_project(project)["id"] if project else None
        needle = (query or "").strip().lower()
        matches = [
            issue
            for issue in self.issues.values()
            if (project_id is None or issue["project_id"] == project_id)
            and issue["archived"] == archived
            and (
                not needle
                or needle in issue["summary"].lower()
                or needle in issue["key"].lower()
                or needle in issue["description"].lower()
            )
        ]
        matches.sort(key=lambda i: i["updated"], reverse=True)
        return matches[offset : offset + limit], len(matches)

    # ------------------------------------------------------------------ quick add

    def parse_quick_add(
        self, text: str, *, project: str | None = None, actor: str | None = None
    ) -> Parsed:
        """Parse quick-add text without writing anything."""
        today = dt_util.now().date()
        parsed = parse_quick_add(
            text,
            people=[Person(p["entity_id"], p["name"]) for p in self.people()],
            project_keys=[p["key"] for p in self.projects.values()],
            today=today,
            tz=dt_util.get_default_time_zone(),
            me=actor,
        )
        if parsed.project is None:
            parsed.project = self._default_project_key(project)
        return parsed

    def _default_project_key(self, ref: str | None) -> str:
        if ref:
            return self.resolve_project(ref)["key"]
        for project in self.projects.values():
            if not project["archived"]:
                return project["key"]
        raise NotFoundError("There is no project yet: create one first")

    def quick_add(
        self,
        text: str,
        *,
        project: str | None = None,
        actor: str | None = None,
        source: str = "service",
    ) -> tuple[dict[str, Any], Parsed]:
        """Parse a quick-add line and create the issue."""
        parsed = self.parse_quick_add(text, project=project, actor=actor)
        assert parsed.project is not None
        issue, _created = self.create_issue(
            parsed.project,
            parsed.summary,
            type=parsed.type,
            priority=parsed.priority,
            assignee=parsed.assignee if parsed.assignee else UNSET,
            labels=parsed.labels,
            due=parsed.due,
            actor=actor,
            source=source,
        )
        return issue, parsed

    # ------------------------------------------------------------------ recurring

    def _recurring_fields(
        self, fields: dict[str, Any], base: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Validate recurring fields; ``base`` supplies defaults when updating."""
        base = base or {}
        out: dict[str, Any] = {}
        if "summary" in fields or "summary" not in base:
            out["summary"] = clean_summary(fields.get("summary"))
        if "description" in fields:
            out["description"] = clean_text(fields["description"], "description", max_len=20000)
        if "type" in fields:
            out["type"] = check_type(fields["type"])
        if "priority" in fields:
            out["priority"] = check_priority(fields["priority"])
        if "assignee" in fields:
            out["assignee"] = self._check_assignee(fields["assignee"])
        if "labels" in fields:
            out["labels"] = clean_labels(fields["labels"])
        if "enabled" in fields:
            out["enabled"] = bool(fields["enabled"])
        if "skip_if_open" in fields:
            out["skip_if_open"] = bool(fields["skip_if_open"])
        if "create_days_before" in fields:
            days = int(fields["create_days_before"])
            if not 0 <= days <= 365:
                raise InvalidError("create_days_before must be between 0 and 365")
            out["create_days_before"] = days
        if "next_due" in fields:
            due = normalize_due(fields["next_due"])
            if due is None or len(due) != 10:
                raise InvalidError("next_due must be a date (YYYY-MM-DD)")
            out["next_due"] = due
        if "repeat" in fields or "next_due" in out:
            anchor = date.fromisoformat(out.get("next_due") or base["next_due"])
            out["repeat"] = recurrence.normalize_repeat(
                fields.get("repeat") or base["repeat"], anchor
            )
        if "status" in fields:
            out["status"] = fields["status"] or None
        return out

    def create_recurring(self, project_ref: str, **fields: Any) -> dict[str, Any]:
        """Create a recurring chore template and run the engine once."""
        project = self.resolve_project(project_ref)
        if "repeat" not in fields or "next_due" not in fields:
            raise InvalidError("repeat and next_due are required")
        values = self._recurring_fields(fields)
        if values.get("status"):
            values["status"] = resolve_status(project, values["status"])["id"]
        rec = {
            "id": new_id(),
            "project_id": project["id"],
            "enabled": True,
            "description": "",
            "type": "task",
            "priority": "medium",
            "assignee": None,
            "labels": [],
            "status": None,
            "create_days_before": 0,
            "skip_if_open": True,
            "last_issue_id": None,
            "last_created": None,
            **values,
        }
        self.recurring[rec["id"]] = rec
        self._run_recurring_engine(self._today())
        self._commit()
        return rec

    def update_recurring(self, rec_id: str, **fields: Any) -> dict[str, Any]:
        """Update a recurring template."""
        rec = self._get_recurring(rec_id)
        fields = {k: v for k, v in fields.items() if v is not UNSET}
        values = self._recurring_fields(fields, rec)
        if values.get("status"):
            values["status"] = resolve_status(self.projects[rec["project_id"]], values["status"])[
                "id"
            ]
        rec.update(values)
        self._run_recurring_engine(self._today())
        self._commit()
        return rec

    def delete_recurring(self, rec_id: str) -> None:
        """Delete a recurring template (issues it created stay)."""
        rec = self._get_recurring(rec_id)
        del self.recurring[rec["id"]]
        self._commit()

    def run_recurring_now(self, rec_id: str, *, actor: str | None = None) -> dict[str, Any] | None:
        """Create the issue for a template right now (None = skipped, one still open)."""
        rec = self._get_recurring(rec_id)
        issue = self._spawn_recurring(rec, date.fromisoformat(rec["next_due"]), actor=actor)
        if issue is not None:
            rec["next_due"] = recurrence.next_occurrence(
                rec["repeat"], date.fromisoformat(rec["next_due"])
            ).isoformat()
        self._commit()
        return issue

    def _get_recurring(self, rec_id: str) -> dict[str, Any]:
        if rec_id not in self.recurring:
            raise NotFoundError(f"Unknown recurring chore {rec_id!r}")
        return self.recurring[rec_id]

    def _today(self) -> date:
        return dt_util.now().date()

    def _spawn_recurring(
        self, rec: dict[str, Any], due: date, *, actor: str | None = None
    ) -> dict[str, Any] | None:
        last = self.issues.get(rec["last_issue_id"]) if rec["last_issue_id"] else None
        if (
            rec["skip_if_open"]
            and last is not None
            and not last["archived"]
            and self.category(last) != "done"
        ):
            return None
        project = self.projects.get(rec["project_id"])
        if project is None or project["archived"]:
            return None
        issue, _ = self.create_issue(
            project["id"],
            rec["summary"],
            type=rec["type"],
            priority=rec["priority"],
            assignee=rec["assignee"],
            labels=rec["labels"],
            due=due.isoformat(),
            description=rec["description"],
            status=rec["status"],
            recurring_id=rec["id"],
            actor=actor,
            source="recurring",
        )
        rec["last_issue_id"] = issue["id"]
        rec["last_created"] = _utc_iso()
        return issue

    def _run_recurring_engine(self, today: date) -> bool:
        changed = False
        for rec in list(self.recurring.values()):
            if not rec["enabled"]:
                continue
            candidate, new_next = recurrence.plan(
                date.fromisoformat(rec["next_due"]),
                rec["repeat"],
                rec["create_days_before"],
                today,
            )
            if candidate is None:
                continue
            rec["next_due"] = new_next.isoformat()
            self._spawn_recurring(rec, candidate)
            changed = True
        return changed

    # ------------------------------------------------------------------ clock

    @callback
    def async_tick(self, now: datetime | None = None) -> None:
        """Run the clock-driven checks and refresh all views."""
        now = now or dt_util.now()
        tz = dt_util.get_default_time_zone()
        events: list[tuple[str, dict[str, Any]]] = []
        changed = self._run_recurring_engine(
            now.date() if now.tzinfo is None else now.astimezone(tz).date()
        )

        for issue in self.issues.values():
            if issue["archived"] or not issue["due"]:
                continue
            category = self.category(issue)
            overdue, due_soon = issue_flags(issue, category, now, tz, self.due_soon_hours)
            if overdue and not issue["overdue_notified"]:
                issue["overdue_notified"] = issue["due_soon_notified"] = True
                events.append((EVENT_ISSUE_OVERDUE, self._issue_event(issue, None, "automation")))
            elif due_soon and not issue["due_soon_notified"]:
                issue["due_soon_notified"] = True
                events.append((EVENT_ISSUE_DUE_SOON, self._issue_event(issue, None, "automation")))

        days = self.auto_archive_days
        if days > 0:
            cutoff = (now - timedelta(days=days)).astimezone(UTC).isoformat(timespec="seconds")
            for issue in self.issues.values():
                if (
                    not issue["archived"]
                    and issue["resolved"]
                    and issue["resolved"] < cutoff
                    and self.category(issue) == "done"
                ):
                    issue["archived"] = True
                    self._activity(issue, None, "archived", "archived", False, True)
                    changed = True

        if events or changed:
            self._commit(events)
        else:
            self._signal()

    # ------------------------------------------------------------------ views

    def issue_view(self, issue: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
        """Return an issue for the list payload (no comments / activity bodies)."""
        now = now or dt_util.now()
        tz = dt_util.get_default_time_zone()
        overdue, due_soon = issue_flags(issue, self.category(issue), now, tz, self.due_soon_hours)
        view = {
            k: v
            for k, v in issue.items()
            if k
            not in (
                "comments",
                "activity",
                "overdue_notified",
                "due_soon_notified",
                "auto_resolved",
            )
        }
        view.update(overdue=overdue, due_soon=due_soon, comment_count=len(issue["comments"]))
        return view

    def issue_detail(self, issue: dict[str, Any]) -> dict[str, Any]:
        """Return one issue with comments and activity."""
        view = self.issue_view(issue)
        view["comments"] = list(issue["comments"])
        view["activity"] = list(issue["activity"])
        return view

    def stats(self, now: datetime | None = None) -> dict[str, Any]:
        """Return the aggregate statistics block (cached until the next change)."""
        if self._stats_cache is None:
            self._stats_cache = compute_stats(
                self.projects,
                self.issues,
                now or dt_util.now(),
                dt_util.get_default_time_zone(),
                self.due_soon_hours,
                people=self.tracked_people(),
            )
        return self._stats_cache

    def top_issues(
        self,
        flag: str,
        *,
        project_id: str | None = None,
        person: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Return short descriptions of open issues for sensor attributes.

        ``flag`` is ``overdue``, ``due_soon`` or ``open``.
        """
        now = dt_util.now()
        found = []
        for issue in self.issues.values():
            if issue["archived"] or (project_id and issue["project_id"] != project_id):
                continue
            if person is not None and (issue["assignee"] or "unassigned") != person:
                continue
            if self.category(issue) == "done":
                continue
            view = self.issue_view(issue, now)
            if flag == "open" or view[flag]:
                found.append(view)
        found.sort(key=lambda v: (v["due"] or "9999", v["number"]))
        return [
            {
                "key": v["key"],
                "summary": v["summary"],
                "due": v["due"],
                "assignee": v["assignee"],
                "priority": v["priority"],
            }
            for v in found[:limit]
        ]

    def full_payload(self, *, user_id: str | None = None, is_admin: bool = False) -> dict[str, Any]:
        """Return the complete frontend payload (docs/PROTOCOL.md section 4)."""
        now = dt_util.now()
        return {
            "version": self.version,
            "settings": self.settings(),
            "me": self.person_for_user(user_id),
            "is_admin": is_admin,
            "people": self.people(),
            "projects": [
                {k: v for k, v in project.items() if k != "issue_seq" and k != "created"}
                for project in self.projects.values()
            ],
            "issues": [
                self.issue_view(issue, now)
                for issue in self.issues.values()
                if not issue["archived"]
            ],
            "recurring": list(self.recurring.values()),
            "stats": self.stats(now),
        }
