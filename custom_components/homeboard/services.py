"""Homeboard services (``homeboard.*``)."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError, Unauthorized
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import (
    AI_NOTE_MAX,
    CATEGORIES,
    DOMAIN,
    ISSUE_TYPES,
    PRIORITIES,
    REPEAT_UNITS,
    SERVICE_ADD_CHECKLIST_ITEM,
    SERVICE_ADD_COMMENT,
    SERVICE_ADD_STATUS,
    SERVICE_AI_ANALYZE,
    SERVICE_ASSIGN_ISSUE,
    SERVICE_ATTACH_CAMERA_SNAPSHOT,
    SERVICE_CHECK_ITEM,
    SERVICE_CREATE_ISSUE,
    SERVICE_CREATE_PROJECT,
    SERVICE_CREATE_RECURRING,
    SERVICE_DELETE_ISSUE,
    SERVICE_DELETE_RECURRING,
    SERVICE_FORGET_LEARNING,
    SERVICE_MOVE_ISSUE,
    SERVICE_QUICK_ADD,
    SERVICE_REMOVE_CHECKLIST_ITEM,
    SERVICE_REMOVE_STATUS,
    SERVICE_RUN_RECURRING,
    SERVICE_SCAN_HEALTH,
    SERVICE_SEND_DIGEST,
    SERVICE_SUGGEST,
    SERVICE_UPDATE_ISSUE,
    SERVICE_UPDATE_PROJECT,
    SERVICE_UPDATE_RECURRING,
    SERVICE_UPDATE_STATUS,
    SOURCES,
)
from .data import HomeboardData
from .model import HomeboardError

PERSON = vol.Any(None, "", cv.entity_domain("person"))
LABELS = vol.Any(None, cv.ensure_list)
DUE = vol.Any(None, "", cv.date, cv.datetime, cv.string)
REPEAT = vol.Schema(
    {
        vol.Required("unit"): vol.In(REPEAT_UNITS),
        vol.Optional("every", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=366)),
        vol.Optional("weekdays"): [vol.All(vol.Coerce(int), vol.Range(min=0, max=6))],
        vol.Optional("day_of_month"): vol.All(vol.Coerce(int), vol.Range(min=-1, max=31)),
    }
)

ISSUE_REF = {
    vol.Optional("issue"): cv.string,
    vol.Optional("project"): cv.string,
    vol.Optional("dedupe_key"): cv.string,
}
ISSUE_FIELDS = {
    vol.Optional("summary"): cv.string,
    vol.Optional("description"): cv.string,
    vol.Optional("type"): vol.In(ISSUE_TYPES),
    vol.Optional("priority"): vol.In(PRIORITIES),
    vol.Optional("assignee"): PERSON,
    vol.Optional("labels"): LABELS,
    vol.Optional("due"): DUE,
    vol.Optional("parent"): vol.Any(None, "", cv.string),
}
RECURRING_FIELDS = {
    vol.Optional("summary"): cv.string,
    vol.Optional("description"): cv.string,
    vol.Optional("type"): vol.In(ISSUE_TYPES),
    vol.Optional("priority"): vol.In(PRIORITIES),
    vol.Optional("assignee"): PERSON,
    vol.Optional("labels"): LABELS,
    vol.Optional("status"): vol.Any(None, "", cv.string),
    vol.Optional("repeat"): REPEAT,
    vol.Optional("next_due"): cv.date,
    vol.Optional("create_days_before"): vol.All(vol.Coerce(int), vol.Range(min=0, max=365)),
    vol.Optional("skip_if_open"): cv.boolean,
    vol.Optional("enabled"): cv.boolean,
}


def _manager(hass: HomeAssistant) -> HomeboardData:
    manager: HomeboardData | None = hass.data.get(DOMAIN)
    if manager is None:
        raise ServiceValidationError("Homeboard is not set up or is still starting")
    return manager


def _due(value: Any) -> Any:
    """Treat naive datetimes as local time; pass everything else through."""
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=dt_util.get_default_time_zone())
    if isinstance(value, (date, datetime)):
        return value
    return value if value not in ("", None) else None


def _given(call: ServiceCall, *names: str) -> dict[str, Any]:
    """Return the optional fields the caller actually passed."""
    return {name: call.data[name] for name in names if name in call.data}


def _handler(
    hass: HomeAssistant, func: Callable[[HomeboardData, ServiceCall, str | None], Any]
) -> Callable[[ServiceCall], Any]:
    async def handle(call: ServiceCall) -> Any:
        manager = _manager(hass)
        actor = manager.person_for_user(call.context.user_id)
        try:
            result = func(manager, call, actor)
            if inspect.isawaitable(result):
                result = await result
            return result
        except HomeboardError as err:
            raise ServiceValidationError(str(err)) from err

    return handle


def _issue_of(manager: HomeboardData, call: ServiceCall) -> dict[str, Any]:
    return manager.resolve_issue(
        call.data.get("issue"),
        project=call.data.get("project"),
        dedupe_key=call.data.get("dedupe_key"),
    )


def _ref(issue: dict[str, Any]) -> dict[str, Any]:
    return {"key": issue["key"], "id": issue["id"]}


def _create_issue(manager: HomeboardData, call: ServiceCall, actor: str | None) -> dict[str, Any]:
    data = call.data
    kwargs: dict[str, Any] = {}
    if "assignee" in data:
        kwargs["assignee"] = data["assignee"] or None
    issue, created = manager.create_issue(
        data["project"],
        data["summary"],
        type=data.get("type"),
        priority=data.get("priority"),
        labels=data.get("labels"),
        due=_due(data.get("due")),
        description=data.get("description", ""),
        status=data.get("status"),
        parent=data.get("parent") or None,
        dedupe_key=data.get("dedupe_key"),
        on_duplicate=data.get("on_duplicate", "skip"),
        actor=actor,
        source=data.get("source", "service"),
        **kwargs,
    )
    return {**_ref(issue), "created": created}


def _update_issue(manager: HomeboardData, call: ServiceCall, actor: str | None) -> dict[str, Any]:
    issue = _issue_of(manager, call)
    fields = _given(
        call, "summary", "description", "type", "priority", "assignee", "labels", "parent"
    )
    if "due" in call.data:
        fields["due"] = _due(call.data["due"])
    if fields.get("assignee") == "":
        fields["assignee"] = None
    if fields.get("parent") == "":
        fields["parent"] = None
    manager.update_issue(issue["id"], actor=actor, source="service", **fields)
    if "status" in call.data:
        manager.move_issue(issue["id"], call.data["status"], actor=actor, source="service")
    return _ref(issue)


def _move_issue(manager: HomeboardData, call: ServiceCall, actor: str | None) -> dict[str, Any]:
    issue = _issue_of(manager, call)
    manager.move_issue(
        issue["id"],
        call.data["status"],
        position=call.data.get("position"),
        actor=actor,
        source="service",
    )
    return _ref(issue)


def _assign_issue(manager: HomeboardData, call: ServiceCall, actor: str | None) -> dict[str, Any]:
    issue = _issue_of(manager, call)
    manager.update_issue(
        issue["id"], actor=actor, source="service", assignee=call.data.get("assignee") or None
    )
    return _ref(issue)


def _add_comment(manager: HomeboardData, call: ServiceCall, actor: str | None) -> dict[str, Any]:
    issue = _issue_of(manager, call)
    manager.add_comment(issue["id"], call.data["text"], actor=actor, source="service")
    return _ref(issue)


def _delete_issue(manager: HomeboardData, call: ServiceCall, actor: str | None) -> None:
    manager.delete_issue(_issue_of(manager, call)["id"], actor=actor, source="service")


def _quick_add(manager: HomeboardData, call: ServiceCall, actor: str | None) -> dict[str, Any]:
    issue, parsed = manager.quick_add(
        call.data["text"],
        project=call.data.get("project"),
        actor=actor,
        source=call.data.get("source", "service"),
        suggest=call.data.get("suggest", False),
    )
    return {**_ref(issue), "parsed": parsed.to_dict()}


def _create_project(manager: HomeboardData, call: ServiceCall, actor: str | None) -> dict[str, Any]:
    data = call.data
    project = manager.create_project(
        key=data["key"],
        name=data["name"],
        description=data.get("description", ""),
        color=data.get("color", "#2f80ed"),
        icon=data.get("icon", "mdi:view-column"),
        lead=data.get("lead") or None,
        template=data.get("template", "household"),
    )
    return {"key": project["key"], "id": project["id"]}


def _update_project(manager: HomeboardData, call: ServiceCall, actor: str | None) -> dict[str, Any]:
    fields = _given(
        call, "name", "description", "color", "icon", "lead", "default_assignee", "archived"
    )
    for name in ("lead", "default_assignee"):
        if name in fields:
            fields[name] = fields[name] or None
    project = manager.update_project(call.data["project"], **fields)
    return {"key": project["key"], "id": project["id"]}


def _add_status(manager: HomeboardData, call: ServiceCall, actor: str | None) -> dict[str, Any]:
    status = manager.add_status(
        call.data["project"],
        name=call.data["name"],
        category=call.data["category"],
        backlog=call.data.get("backlog", False),
        wip=call.data.get("wip"),
        position=call.data.get("position"),
    )
    return {"id": status["id"], "name": status["name"]}


def _update_status(manager: HomeboardData, call: ServiceCall, actor: str | None) -> dict[str, Any]:
    status = manager.update_status(
        call.data["project"],
        call.data["status"],
        **_given(call, "name", "category", "backlog", "wip"),
    )
    return {"id": status["id"], "name": status["name"]}


def _remove_status(manager: HomeboardData, call: ServiceCall, actor: str | None) -> None:
    manager.remove_status(
        call.data["project"], call.data["status"], move_to=call.data.get("move_to")
    )


def _create_recurring(
    manager: HomeboardData, call: ServiceCall, actor: str | None
) -> dict[str, Any]:
    fields = {k: v for k, v in call.data.items() if k != "project"}
    if "next_due" in fields:
        fields["next_due"] = fields["next_due"].isoformat()
    if fields.get("assignee") == "":
        fields["assignee"] = None
    rec = manager.create_recurring(call.data["project"], **fields)
    return {"id": rec["id"], "next_due": rec["next_due"]}


def _update_recurring(
    manager: HomeboardData, call: ServiceCall, actor: str | None
) -> dict[str, Any]:
    fields = {k: v for k, v in call.data.items() if k != "recurring_id"}
    if "next_due" in fields:
        fields["next_due"] = fields["next_due"].isoformat()
    if fields.get("assignee") == "":
        fields["assignee"] = None
    rec = manager.update_recurring(call.data["recurring_id"], **fields)
    return {"id": rec["id"], "next_due": rec["next_due"]}


def _delete_recurring(manager: HomeboardData, call: ServiceCall, actor: str | None) -> None:
    manager.delete_recurring(call.data["recurring_id"])


def _run_recurring(manager: HomeboardData, call: ServiceCall, actor: str | None) -> dict[str, Any]:
    issue = manager.run_recurring_now(call.data["recurring_id"], actor=actor)
    return {"created": issue is not None, **(_ref(issue) if issue else {})}


def _add_checklist_item(
    manager: HomeboardData, call: ServiceCall, actor: str | None
) -> dict[str, Any]:
    issue = _issue_of(manager, call)
    item = manager.add_checklist_item(issue["id"], call.data["text"], actor=actor, source="service")
    return {**_ref(issue), "item_id": item["id"]}


def _check_item(manager: HomeboardData, call: ServiceCall, actor: str | None) -> dict[str, Any]:
    issue = _issue_of(manager, call)
    item = manager.update_checklist_item(
        issue["id"],
        call.data["item"],
        done=call.data.get("done", True),
        actor=actor,
        source="service",
    )
    return {**_ref(issue), "item_id": item["id"], "done": item["done"]}


def _remove_checklist_item(
    manager: HomeboardData, call: ServiceCall, actor: str | None
) -> dict[str, Any]:
    issue = _issue_of(manager, call)
    manager.remove_checklist_item(issue["id"], call.data["item"], actor=actor, source="service")
    return _ref(issue)


async def _attach_camera_snapshot(
    manager: HomeboardData, call: ServiceCall, actor: str | None
) -> dict[str, Any]:
    if manager.files is None:
        raise ServiceValidationError("Attachments are not available")
    issue = _issue_of(manager, call)
    attachment = await manager.files.async_snapshot(issue["id"], call.data["camera"], author=actor)
    return {**_ref(issue), "attachment_id": attachment["id"], "name": attachment["name"]}


def _send_digest(manager: HomeboardData, call: ServiceCall, actor: str | None) -> dict[str, Any]:
    if manager.push is None:
        raise ServiceValidationError("Push notifications are not running")
    return {"sent": manager.push.send_digests_now(call.data.get("person") or None)}


def _suggest(manager: HomeboardData, call: ServiceCall, actor: str | None) -> dict[str, Any]:
    parsed = manager.parse_quick_add(
        call.data["text"], project=call.data.get("project"), actor=actor
    )
    return {"suggestion": manager.suggestion_for(parsed)}


def _forget_learning(
    manager: HomeboardData, call: ServiceCall, actor: str | None
) -> dict[str, Any]:
    if manager.learning is None:
        raise ServiceValidationError("Learning is not running")
    return {"forgotten": manager.learning.forget(call.data.get("feature"))}


async def _ai_analyze(
    manager: HomeboardData, call: ServiceCall, actor: str | None
) -> dict[str, Any]:
    if manager.ai is None:
        raise ServiceValidationError("AI Fix is not running")
    if call.context.user_id:  # an automation has no user; a person must be an administrator
        user = await manager.hass.auth.async_get_user(call.context.user_id)
        if user is None or not user.is_admin:
            raise Unauthorized(context=call.context)
    issue = manager.resolve_issue(
        call.data.get("issue"),
        project=call.data.get("project"),
        dedupe_key=call.data.get("dedupe_key"),
    )
    return await manager.ai.analyze(issue["id"], call.data.get("note", ""), actor)


async def _scan_health(
    manager: HomeboardData, call: ServiceCall, actor: str | None
) -> dict[str, Any]:
    if manager.health is None:
        raise ServiceValidationError("Home health is not running")
    return await manager.health.async_scan(dry_run=call.data.get("dry_run", False), force=True)


# (name, handler, schema, returns a response)
SERVICES: tuple[tuple[str, Callable[..., Any], vol.Schema, bool], ...] = (
    (
        SERVICE_CREATE_ISSUE,
        _create_issue,
        vol.Schema(
            {
                vol.Required("project"): cv.string,
                vol.Required("summary"): cv.string,
                **{k: v for k, v in ISSUE_FIELDS.items() if k.schema != "summary"},
                vol.Optional("status"): cv.string,
                vol.Optional("dedupe_key"): cv.string,
                vol.Optional("on_duplicate"): vol.In(("skip", "comment", "reopen")),
                vol.Optional("source"): vol.In(SOURCES),
            }
        ),
        True,
    ),
    (
        SERVICE_UPDATE_ISSUE,
        _update_issue,
        vol.Schema({**ISSUE_REF, **ISSUE_FIELDS, vol.Optional("status"): cv.string}),
        True,
    ),
    (
        SERVICE_MOVE_ISSUE,
        _move_issue,
        vol.Schema(
            {
                **ISSUE_REF,
                vol.Required("status"): cv.string,
                vol.Optional("position"): vol.In(("top", "bottom")),
            }
        ),
        True,
    ),
    (
        SERVICE_ASSIGN_ISSUE,
        _assign_issue,
        vol.Schema({**ISSUE_REF, vol.Optional("assignee"): PERSON}),
        True,
    ),
    (
        SERVICE_ADD_COMMENT,
        _add_comment,
        vol.Schema({**ISSUE_REF, vol.Required("text"): cv.string}),
        True,
    ),
    (SERVICE_DELETE_ISSUE, _delete_issue, vol.Schema(ISSUE_REF), False),
    (
        SERVICE_QUICK_ADD,
        _quick_add,
        vol.Schema(
            {
                vol.Required("text"): cv.string,
                vol.Optional("project"): cv.string,
                vol.Optional("source"): vol.In(SOURCES),
                vol.Optional("suggest"): cv.boolean,
            }
        ),
        True,
    ),
    (
        SERVICE_CREATE_PROJECT,
        _create_project,
        vol.Schema(
            {
                vol.Required("key"): cv.string,
                vol.Required("name"): cv.string,
                vol.Optional("description"): cv.string,
                vol.Optional("color"): cv.string,
                vol.Optional("icon"): cv.string,
                vol.Optional("lead"): PERSON,
                vol.Optional("template"): vol.In(("household", "software", "blank")),
            }
        ),
        True,
    ),
    (
        SERVICE_UPDATE_PROJECT,
        _update_project,
        vol.Schema(
            {
                vol.Required("project"): cv.string,
                vol.Optional("name"): cv.string,
                vol.Optional("description"): cv.string,
                vol.Optional("color"): cv.string,
                vol.Optional("icon"): cv.string,
                vol.Optional("lead"): PERSON,
                vol.Optional("default_assignee"): PERSON,
                vol.Optional("archived"): cv.boolean,
            }
        ),
        True,
    ),
    (
        SERVICE_ADD_STATUS,
        _add_status,
        vol.Schema(
            {
                vol.Required("project"): cv.string,
                vol.Required("name"): cv.string,
                vol.Required("category"): vol.In(CATEGORIES),
                vol.Optional("backlog"): cv.boolean,
                vol.Optional("wip"): vol.Any(None, vol.Coerce(int)),
                vol.Optional("position"): vol.Coerce(int),
            }
        ),
        True,
    ),
    (
        SERVICE_UPDATE_STATUS,
        _update_status,
        vol.Schema(
            {
                vol.Required("project"): cv.string,
                vol.Required("status"): cv.string,
                vol.Optional("name"): cv.string,
                vol.Optional("category"): vol.In(CATEGORIES),
                vol.Optional("backlog"): cv.boolean,
                vol.Optional("wip"): vol.Any(None, vol.Coerce(int)),
            }
        ),
        True,
    ),
    (
        SERVICE_REMOVE_STATUS,
        _remove_status,
        vol.Schema(
            {
                vol.Required("project"): cv.string,
                vol.Required("status"): cv.string,
                vol.Optional("move_to"): cv.string,
            }
        ),
        False,
    ),
    (
        SERVICE_CREATE_RECURRING,
        _create_recurring,
        vol.Schema(
            {
                vol.Required("project"): cv.string,
                vol.Required("summary"): cv.string,
                vol.Required("repeat"): REPEAT,
                vol.Required("next_due"): cv.date,
                **{
                    k: v
                    for k, v in RECURRING_FIELDS.items()
                    if k.schema not in ("summary", "repeat", "next_due")
                },
            }
        ),
        True,
    ),
    (
        SERVICE_UPDATE_RECURRING,
        _update_recurring,
        vol.Schema({vol.Required("recurring_id"): cv.string, **RECURRING_FIELDS}),
        True,
    ),
    (
        SERVICE_DELETE_RECURRING,
        _delete_recurring,
        vol.Schema({vol.Required("recurring_id"): cv.string}),
        False,
    ),
    (
        SERVICE_RUN_RECURRING,
        _run_recurring,
        vol.Schema({vol.Required("recurring_id"): cv.string}),
        True,
    ),
    (
        SERVICE_ADD_CHECKLIST_ITEM,
        _add_checklist_item,
        vol.Schema({**ISSUE_REF, vol.Required("text"): cv.string}),
        True,
    ),
    (
        SERVICE_CHECK_ITEM,
        _check_item,
        vol.Schema(
            {**ISSUE_REF, vol.Required("item"): cv.string, vol.Optional("done"): cv.boolean}
        ),
        True,
    ),
    (
        SERVICE_REMOVE_CHECKLIST_ITEM,
        _remove_checklist_item,
        vol.Schema({**ISSUE_REF, vol.Required("item"): cv.string}),
        True,
    ),
    (
        SERVICE_ATTACH_CAMERA_SNAPSHOT,
        _attach_camera_snapshot,
        vol.Schema({**ISSUE_REF, vol.Required("camera"): cv.entity_domain("camera")}),
        True,
    ),
    (
        SERVICE_SUGGEST,
        _suggest,
        vol.Schema({vol.Required("text"): cv.string, vol.Optional("project"): cv.string}),
        True,
    ),
    (
        SERVICE_FORGET_LEARNING,
        _forget_learning,
        vol.Schema(
            {
                vol.Optional("feature"): vol.In(
                    ("defaults", "patterns", "workload", "health", "rhythm")
                )
            }
        ),
        True,
    ),
    (
        SERVICE_SEND_DIGEST,
        _send_digest,
        vol.Schema({vol.Optional("person"): vol.Any(None, "", cv.entity_domain("person"))}),
        True,
    ),
    (SERVICE_SCAN_HEALTH, _scan_health, vol.Schema({vol.Optional("dry_run"): cv.boolean}), True),
    (
        SERVICE_AI_ANALYZE,
        _ai_analyze,
        vol.Schema(
            {**ISSUE_REF, vol.Optional("note"): vol.All(cv.string, vol.Length(max=AI_NOTE_MAX))}
        ),
        True,
    ),
)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register all services (called once from ``async_setup``)."""
    for name, func, schema, responds in SERVICES:
        hass.services.async_register(
            DOMAIN,
            name,
            _handler(hass, func),
            schema=schema,
            supports_response=SupportsResponse.OPTIONAL if responds else SupportsResponse.NONE,
        )
