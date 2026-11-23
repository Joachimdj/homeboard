"""Websocket API for the panel and the Lovelace cards (``homeboard/*``)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import voluptuous as vol
from homeassistant.auth.permissions.const import POLICY_READ
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import Unauthorized
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import (
    AI_NOTE_MAX,
    CATEGORIES,
    DOMAIN,
    ISSUE_TYPES,
    PRIORITIES,
    REPEAT_UNITS,
    SIGNAL_UPDATED,
)
from .data import HomeboardData
from .model import HomeboardError, NotFoundError

PERSON = vol.Any(None, "", cv.entity_domain("person"))
DUE = vol.Any(None, "", cv.string)
REPEAT = vol.Schema(
    {
        vol.Required("unit"): vol.In(REPEAT_UNITS),
        vol.Optional("every"): vol.Coerce(int),
        vol.Optional("weekdays"): [vol.Coerce(int)],
        vol.Optional("day_of_month"): vol.Coerce(int),
    }
)

Handler = Callable[[HomeboardData, websocket_api.ActiveConnection, dict[str, Any], str | None], Any]


def _run(handler: Handler) -> Callable[..., None]:
    """Wrap a handler: find the manager, map errors, send the result."""

    def wrapper(
        hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
    ) -> None:
        manager: HomeboardData | None = hass.data.get(DOMAIN)
        if manager is None:
            connection.send_error(msg["id"], "not_loaded", "Homeboard is not set up")
            return
        actor = manager.person_for_user(connection.user.id)
        try:
            result = handler(manager, connection, msg, actor)
        except HomeboardError as err:
            connection.send_error(msg["id"], err.code, str(err))
            return
        connection.send_result(msg["id"], result)

    return wrapper


def _fields(msg: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    return {name: msg[name] for name in names if name in msg}


def _blank_to_none(fields: dict[str, Any], *names: str) -> dict[str, Any]:
    for name in names:
        if name in fields and fields[name] == "":
            fields[name] = None
    return fields


# ---------------------------------------------------------------- read / subscribe


@websocket_api.websocket_command({vol.Required("type"): "homeboard/get"})
@callback
def ws_get(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the full payload once."""
    manager: HomeboardData | None = hass.data.get(DOMAIN)
    if manager is None:
        connection.send_error(msg["id"], "not_loaded", "Homeboard is not set up")
        return
    connection.send_result(
        msg["id"],
        manager.full_payload(user_id=connection.user.id, is_admin=connection.user.is_admin),
    )


@websocket_api.websocket_command({vol.Required("type"): "homeboard/subscribe"})
@callback
def ws_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Stream the full payload now and after every change."""
    manager: HomeboardData | None = hass.data.get(DOMAIN)
    if manager is None:
        connection.send_error(msg["id"], "not_loaded", "Homeboard is not set up")
        return
    pending = False

    @callback
    def flush() -> None:
        nonlocal pending
        pending = False
        connection.send_message(
            websocket_api.event_message(
                msg["id"],
                manager.full_payload(user_id=connection.user.id, is_admin=connection.user.is_admin),
            )
        )

    @callback
    def on_update() -> None:
        # Coalesce bursts (a recurring run, a bulk move) into one push.
        nonlocal pending
        if not pending:
            pending = True
            hass.loop.call_soon(flush)

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(hass, SIGNAL_UPDATED, on_update)
    connection.send_result(msg["id"])
    flush()


# ---------------------------------------------------------------- projects (admin)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "homeboard/project/create",
        vol.Required("key"): cv.string,
        vol.Required("name"): cv.string,
        vol.Optional("description"): cv.string,
        vol.Optional("color"): cv.string,
        vol.Optional("icon"): cv.string,
        vol.Optional("lead"): PERSON,
        vol.Optional("template"): vol.In(("household", "software", "blank")),
    }
)
@callback
def ws_project_create(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Create a project."""
    _run(
        lambda m, c, msg, actor: m.create_project(
            key=msg["key"],
            name=msg["name"],
            description=msg.get("description", ""),
            color=msg.get("color", "#2f80ed"),
            icon=msg.get("icon", "mdi:view-column"),
            lead=msg.get("lead") or None,
            template=msg.get("template", "household"),
        )
    )(hass, connection, msg)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "homeboard/project/update",
        vol.Required("project_id"): cv.string,
        vol.Optional("name"): cv.string,
        vol.Optional("description"): cv.string,
        vol.Optional("color"): cv.string,
        vol.Optional("icon"): cv.string,
        vol.Optional("lead"): PERSON,
        vol.Optional("default_assignee"): PERSON,
        vol.Optional("archived"): cv.boolean,
        vol.Optional("labels"): [cv.string],
    }
)
@callback
def ws_project_update(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Update a project."""
    fields = _blank_to_none(
        _fields(
            msg,
            (
                "name",
                "description",
                "color",
                "icon",
                "lead",
                "default_assignee",
                "archived",
                "labels",
            ),
        ),
        "lead",
        "default_assignee",
    )
    _run(lambda m, c, msg, actor: m.update_project(msg["project_id"], **fields))(
        hass, connection, msg
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "homeboard/project/delete",
        vol.Required("project_id"): cv.string,
        vol.Required("confirm"): True,
    }
)
@callback
def ws_project_delete(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Delete a project and everything in it."""

    def handler(m: HomeboardData, c: Any, msg: dict[str, Any], actor: str | None) -> dict[str, Any]:
        m.delete_project(msg["project_id"])
        return {"deleted": msg["project_id"]}

    _run(handler)(hass, connection, msg)


# ---------------------------------------------------------------- statuses (admin)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "homeboard/status/create",
        vol.Required("project_id"): cv.string,
        vol.Required("name"): cv.string,
        vol.Required("category"): vol.In(CATEGORIES),
        vol.Optional("backlog"): cv.boolean,
        vol.Optional("wip"): vol.Any(None, vol.Coerce(int)),
        vol.Optional("position"): vol.Coerce(int),
    }
)
@callback
def ws_status_create(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Add a status."""
    _run(
        lambda m, c, msg, actor: m.add_status(
            msg["project_id"],
            name=msg["name"],
            category=msg["category"],
            backlog=msg.get("backlog", False),
            wip=msg.get("wip"),
            position=msg.get("position"),
        )
    )(hass, connection, msg)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "homeboard/status/update",
        vol.Required("project_id"): cv.string,
        vol.Required("status_id"): cv.string,
        vol.Optional("name"): cv.string,
        vol.Optional("category"): vol.In(CATEGORIES),
        vol.Optional("backlog"): cv.boolean,
        vol.Optional("wip"): vol.Any(None, vol.Coerce(int)),
    }
)
@callback
def ws_status_update(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Update a status."""
    fields = _fields(msg, ("name", "category", "backlog", "wip"))
    _run(lambda m, c, msg, actor: m.update_status(msg["project_id"], msg["status_id"], **fields))(
        hass, connection, msg
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "homeboard/status/reorder",
        vol.Required("project_id"): cv.string,
        vol.Required("status_ids"): [cv.string],
    }
)
@callback
def ws_status_reorder(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Reorder statuses."""

    def handler(
        m: HomeboardData, c: Any, msg: dict[str, Any], actor: str | None
    ) -> dict[str, bool]:
        m.reorder_statuses(msg["project_id"], msg["status_ids"])
        return {"ok": True}

    _run(handler)(hass, connection, msg)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "homeboard/status/delete",
        vol.Required("project_id"): cv.string,
        vol.Required("status_id"): cv.string,
        vol.Optional("move_to"): cv.string,
    }
)
@callback
def ws_status_delete(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Remove a status."""

    def handler(m: HomeboardData, c: Any, msg: dict[str, Any], actor: str | None) -> dict[str, str]:
        m.remove_status(msg["project_id"], msg["status_id"], move_to=msg.get("move_to"))
        return {"deleted": msg["status_id"]}

    _run(handler)(hass, connection, msg)


# ---------------------------------------------------------------- issues


@websocket_api.websocket_command(
    {
        vol.Required("type"): "homeboard/issue/create",
        vol.Required("project_id"): cv.string,
        vol.Required("summary"): cv.string,
        vol.Optional("issue_type"): vol.In(ISSUE_TYPES),
        vol.Optional("priority"): vol.In(PRIORITIES),
        vol.Optional("assignee"): PERSON,
        vol.Optional("labels"): [cv.string],
        vol.Optional("due"): DUE,
        vol.Optional("description"): cv.string,
        vol.Optional("status"): cv.string,
        vol.Optional("parent"): vol.Any(None, "", cv.string),
    }
)
@callback
def ws_issue_create(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Create an issue."""

    def handler(m: HomeboardData, c: Any, msg: dict[str, Any], actor: str | None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if "assignee" in msg:
            kwargs["assignee"] = msg["assignee"] or None
        issue, _ = m.create_issue(
            msg["project_id"],
            msg["summary"],
            type=msg.get("issue_type"),
            priority=msg.get("priority"),
            labels=msg.get("labels"),
            due=msg.get("due") or None,
            description=msg.get("description", ""),
            status=msg.get("status"),
            parent=msg.get("parent") or None,
            actor=actor,
            source="ui",
            **kwargs,
        )
        return m.issue_view(issue)

    _run(handler)(hass, connection, msg)


@websocket_api.websocket_command(
    {vol.Required("type"): "homeboard/issue/get", vol.Required("issue_id"): cv.string}
)
@callback
def ws_issue_get(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return one issue with comments and activity."""
    _run(lambda m, c, msg, actor: m.issue_detail(m.resolve_issue(msg["issue_id"])))(
        hass, connection, msg
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "homeboard/issue/update",
        vol.Required("issue_id"): cv.string,
        vol.Optional("summary"): cv.string,
        vol.Optional("description"): cv.string,
        vol.Optional("issue_type"): vol.In(ISSUE_TYPES),
        vol.Optional("priority"): vol.In(PRIORITIES),
        vol.Optional("assignee"): PERSON,
        vol.Optional("labels"): [cv.string],
        vol.Optional("due"): DUE,
        vol.Optional("parent"): vol.Any(None, "", cv.string),
        vol.Optional("archived"): cv.boolean,
    }
)
@callback
def ws_issue_update(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Update an issue."""
    fields = _fields(
        msg,
        ("summary", "description", "priority", "assignee", "labels", "due", "parent", "archived"),
    )
    if "issue_type" in msg:
        fields["type"] = msg["issue_type"]
    _blank_to_none(fields, "assignee", "due", "parent")

    def handler(m: HomeboardData, c: Any, msg: dict[str, Any], actor: str | None) -> dict[str, Any]:
        issue = m.update_issue(msg["issue_id"], actor=actor, source="ui", **fields)
        return m.issue_view(issue)

    _run(handler)(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "homeboard/issue/move",
        vol.Required("issue_id"): cv.string,
        vol.Required("status"): cv.string,
        vol.Optional("before"): vol.Any(None, cv.string),
    }
)
@callback
def ws_issue_move(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Move an issue (drag and drop)."""

    def handler(m: HomeboardData, c: Any, msg: dict[str, Any], actor: str | None) -> dict[str, Any]:
        issue = m.move_issue(
            msg["issue_id"], msg["status"], before=msg.get("before"), actor=actor, source="ui"
        )
        return m.issue_view(issue)

    _run(handler)(hass, connection, msg)


@websocket_api.websocket_command(
    {vol.Required("type"): "homeboard/issue/delete", vol.Required("issue_id"): cv.string}
)
@callback
def ws_issue_delete(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Delete an issue."""

    def handler(m: HomeboardData, c: Any, msg: dict[str, Any], actor: str | None) -> dict[str, str]:
        m.delete_issue(msg["issue_id"], actor=actor, source="ui")
        return {"deleted": msg["issue_id"]}

    _run(handler)(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "homeboard/issue/comment",
        vol.Required("issue_id"): cv.string,
        vol.Required("text"): cv.string,
    }
)
@callback
def ws_issue_comment(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Add a comment."""
    _run(
        lambda m, c, msg, actor: m.add_comment(
            msg["issue_id"], msg["text"], actor=actor, source="ui"
        )
    )(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "homeboard/issue/list",
        vol.Optional("project_id"): cv.string,
        vol.Optional("archived"): cv.boolean,
        vol.Optional("query"): cv.string,
        vol.Optional("limit"): vol.All(vol.Coerce(int), vol.Range(min=1, max=500)),
        vol.Optional("offset"): vol.All(vol.Coerce(int), vol.Range(min=0)),
    }
)
@callback
def ws_issue_list(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """List archived issues / search."""

    def handler(m: HomeboardData, c: Any, msg: dict[str, Any], actor: str | None) -> dict[str, Any]:
        issues, total = m.list_issues(
            project=msg.get("project_id"),
            archived=msg.get("archived", False),
            query=msg.get("query"),
            limit=msg.get("limit", 100),
            offset=msg.get("offset", 0),
        )
        return {"issues": [m.issue_view(i) for i in issues], "total": total}

    _run(handler)(hass, connection, msg)


# ---------------------------------------------------------------- quick add


@websocket_api.websocket_command(
    {
        vol.Required("type"): "homeboard/quick_add",
        vol.Required("text"): cv.string,
        vol.Optional("project"): cv.string,
        vol.Optional("suggest"): cv.boolean,
    }
)
@callback
def ws_quick_add(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Create an issue from a quick-add line."""

    def handler(m: HomeboardData, c: Any, msg: dict[str, Any], actor: str | None) -> dict[str, Any]:
        issue, parsed = m.quick_add(
            msg["text"],
            project=msg.get("project"),
            actor=actor,
            source="ui",
            suggest=msg.get("suggest", False),
        )
        return {"issue": m.issue_view(issue), "parsed": parsed.to_dict()}

    _run(handler)(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "homeboard/quick_add/preview",
        vol.Required("text"): cv.string,
        vol.Optional("project"): cv.string,
    }
)
@callback
def ws_quick_add_preview(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Parse a quick-add line without writing anything (plus the learned suggestion)."""

    def handler(m: HomeboardData, c: Any, msg: dict[str, Any], actor: str | None) -> dict[str, Any]:
        parsed = m.parse_quick_add(msg["text"], project=msg.get("project"), actor=actor)
        return {**parsed.to_dict(), "suggestion": m.suggestion_for(parsed)}

    _run(handler)(hass, connection, msg)


# ---------------------------------------------------------------- recurring


RECURRING_FIELDS = {
    vol.Optional("summary"): cv.string,
    vol.Optional("description"): cv.string,
    vol.Optional("issue_type"): vol.In(ISSUE_TYPES),
    vol.Optional("priority"): vol.In(PRIORITIES),
    vol.Optional("assignee"): PERSON,
    vol.Optional("labels"): [cv.string],
    vol.Optional("status"): vol.Any(None, "", cv.string),
    vol.Optional("repeat"): REPEAT,
    vol.Optional("next_due"): cv.string,
    vol.Optional("create_days_before"): vol.Coerce(int),
    vol.Optional("skip_if_open"): cv.boolean,
    vol.Optional("enabled"): cv.boolean,
}


def _recurring_fields(msg: dict[str, Any]) -> dict[str, Any]:
    fields = _fields(
        msg,
        (
            "summary",
            "description",
            "priority",
            "assignee",
            "labels",
            "status",
            "repeat",
            "next_due",
            "create_days_before",
            "skip_if_open",
            "enabled",
        ),
    )
    if "issue_type" in msg:
        fields["type"] = msg["issue_type"]
    return _blank_to_none(fields, "assignee", "status")


@websocket_api.websocket_command(
    {
        vol.Required("type"): "homeboard/recurring/create",
        vol.Required("project_id"): cv.string,
        **RECURRING_FIELDS,
    }
)
@callback
def ws_recurring_create(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Create a recurring chore."""
    fields = _recurring_fields(msg)
    _run(lambda m, c, msg, actor: m.create_recurring(msg["project_id"], **fields))(
        hass, connection, msg
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "homeboard/recurring/update",
        vol.Required("recurring_id"): cv.string,
        **RECURRING_FIELDS,
    }
)
@callback
def ws_recurring_update(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Update a recurring chore."""
    fields = _recurring_fields(msg)
    _run(lambda m, c, msg, actor: m.update_recurring(msg["recurring_id"], **fields))(
        hass, connection, msg
    )


@websocket_api.websocket_command(
    {vol.Required("type"): "homeboard/recurring/delete", vol.Required("recurring_id"): cv.string}
)
@callback
def ws_recurring_delete(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Delete a recurring chore."""

    def handler(m: HomeboardData, c: Any, msg: dict[str, Any], actor: str | None) -> dict[str, str]:
        m.delete_recurring(msg["recurring_id"])
        return {"deleted": msg["recurring_id"]}

    _run(handler)(hass, connection, msg)


@websocket_api.websocket_command(
    {vol.Required("type"): "homeboard/recurring/run_now", vol.Required("recurring_id"): cv.string}
)
@callback
def ws_recurring_run_now(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Create the issue of a recurring chore right now."""

    def handler(m: HomeboardData, c: Any, msg: dict[str, Any], actor: str | None) -> dict[str, Any]:
        issue = m.run_recurring_now(msg["recurring_id"], actor=actor)
        return {"issue": m.issue_view(issue) if issue else None}

    _run(handler)(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "homeboard/checklist/add",
        vol.Required("issue_id"): cv.string,
        vol.Required("text"): cv.string,
    }
)
@callback
def ws_checklist_add(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Add a checklist item."""
    _run(
        lambda m, c, msg, actor: m.add_checklist_item(
            msg["issue_id"], msg["text"], actor=actor, source="ui"
        )
    )(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "homeboard/checklist/update",
        vol.Required("issue_id"): cv.string,
        vol.Required("item_id"): cv.string,
        vol.Optional("text"): cv.string,
        vol.Optional("done"): cv.boolean,
    }
)
@callback
def ws_checklist_update(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Rename or tick a checklist item."""
    _run(
        lambda m, c, msg, actor: m.update_checklist_item(
            msg["issue_id"],
            msg["item_id"],
            text=msg.get("text"),
            done=msg.get("done"),
            actor=actor,
            source="ui",
        )
    )(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "homeboard/checklist/remove",
        vol.Required("issue_id"): cv.string,
        vol.Required("item_id"): cv.string,
    }
)
@callback
def ws_checklist_remove(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Remove a checklist item."""

    def handler(m: HomeboardData, c: Any, msg: dict[str, Any], actor: str | None) -> dict[str, str]:
        m.remove_checklist_item(msg["issue_id"], msg["item_id"], actor=actor, source="ui")
        return {"deleted": msg["item_id"]}

    _run(handler)(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "homeboard/checklist/reorder",
        vol.Required("issue_id"): cv.string,
        vol.Required("item_ids"): [cv.string],
    }
)
@callback
def ws_checklist_reorder(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Reorder a checklist."""

    def handler(
        m: HomeboardData, c: Any, msg: dict[str, Any], actor: str | None
    ) -> dict[str, bool]:
        m.reorder_checklist(msg["issue_id"], msg["item_ids"])
        return {"ok": True}

    _run(handler)(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "homeboard/attachment/remove",
        vol.Required("issue_id"): cv.string,
        vol.Required("attachment_id"): cv.string,
    }
)
@websocket_api.async_response
async def ws_attachment_remove(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Delete an attachment."""
    manager: HomeboardData | None = hass.data.get(DOMAIN)
    if manager is None or manager.files is None:
        connection.send_error(msg["id"], "not_loaded", "Homeboard is not set up")
        return
    try:
        await manager.files.async_remove(
            msg["issue_id"], msg["attachment_id"], actor=manager.person_for_user(connection.user.id)
        )
    except HomeboardError as err:
        connection.send_error(msg["id"], err.code, str(err))
        return
    connection.send_result(msg["id"], {"deleted": msg["attachment_id"]})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "homeboard/attachment/snapshot",
        vol.Required("issue_id"): cv.string,
        vol.Required("entity_id"): cv.entity_domain("camera"),
    }
)
@websocket_api.async_response
async def ws_attachment_snapshot(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Attach a still picture from a camera (the user must be allowed to read the camera)."""
    manager: HomeboardData | None = hass.data.get(DOMAIN)
    if manager is None or manager.files is None:
        connection.send_error(msg["id"], "not_loaded", "Homeboard is not set up")
        return
    if not connection.user.permissions.check_entity(msg["entity_id"], POLICY_READ):
        connection.send_error(msg["id"], "unauthorized", "You may not read this camera")
        return
    try:
        attachment = await manager.files.async_snapshot(
            msg["issue_id"], msg["entity_id"], author=manager.person_for_user(connection.user.id)
        )
    except HomeboardError as err:
        connection.send_error(msg["id"], err.code, str(err))
        return
    connection.send_result(msg["id"], manager.files.describe([attachment])[0])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "homeboard/suggest",
        vol.Required("text"): cv.string,
        vol.Optional("project"): cv.string,
    }
)
@callback
def ws_suggest(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the learned suggestion for a title (null = nothing to suggest)."""

    def handler(m: HomeboardData, c: Any, msg: dict[str, Any], actor: str | None) -> Any:
        return m.suggestion_for(
            m.parse_quick_add(msg["text"], project=msg.get("project"), actor=actor)
        )

    _run(handler)(hass, connection, msg)


def _learning(m: HomeboardData) -> Any:
    if m.learning is None:
        raise NotFoundError("Learning is not running")
    return m.learning


@websocket_api.websocket_command({vol.Required("type"): "homeboard/insights/get"})
@callback
def ws_insights_get(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return suggestions and what has been learned (automation ideas are for administrators only)."""
    _run(lambda m, c, msg, actor: _learning(m).insights(admin=c.user.is_admin))(
        hass, connection, msg
    )


@websocket_api.websocket_command(
    {vol.Required("type"): "homeboard/insights/accept", vol.Required("suggestion_id"): cv.string}
)
@callback
def ws_insights_accept(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Accept a suggestion."""
    _run(lambda m, c, msg, actor: _learning(m).accept(msg["suggestion_id"]))(hass, connection, msg)


@websocket_api.websocket_command(
    {vol.Required("type"): "homeboard/insights/dismiss", vol.Required("suggestion_id"): cv.string}
)
@callback
def ws_insights_dismiss(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Dismiss a suggestion."""

    def handler(m: HomeboardData, c: Any, msg: dict[str, Any], actor: str | None) -> dict[str, str]:
        if not c.user.is_admin and _learning(m).kind_of(msg["suggestion_id"]) == "automation":
            raise Unauthorized(context=c.context(msg))
        _learning(m).dismiss(msg["suggestion_id"])
        return {"dismissed": msg["suggestion_id"]}

    _run(handler)(hass, connection, msg)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "homeboard/insights/forget",
        vol.Optional("feature"): vol.In(
            ("defaults", "patterns", "workload", "health", "rhythm", "habits")
        ),
    }
)
@callback
def ws_insights_forget(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Forget what a learning feature stored."""
    _run(lambda m, c, msg, actor: {"forgotten": _learning(m).forget(msg.get("feature"))})(
        hass, connection, msg
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "homeboard/health/scan", vol.Optional("dry_run"): cv.boolean}
)
@websocket_api.async_response
async def ws_health_scan(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Run the home-health scan now (dry_run = report only)."""
    manager: HomeboardData | None = hass.data.get(DOMAIN)
    if manager is None or manager.health is None:
        connection.send_error(msg["id"], "not_loaded", "Homeboard is not set up")
        return
    try:
        result = await manager.health.async_scan(dry_run=msg.get("dry_run", False), force=True)
    except HomeboardError as err:
        connection.send_error(msg["id"], err.code, str(err))
        return
    connection.send_result(msg["id"], result)


def _ai(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> Any:
    """Return the AI Fix engine or answer with an error."""
    manager: HomeboardData | None = hass.data.get(DOMAIN)
    if manager is None or manager.ai is None:
        connection.send_error(msg["id"], "not_loaded", "Homeboard is not set up")
        return None
    return manager


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "homeboard/ai/get", vol.Required("issue_id"): cv.string}
)
@callback
def ws_ai_get(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """AI Fix state of one issue (settings, readiness, the record)."""
    manager = _ai(hass, connection, msg)
    if manager is None:
        return
    try:
        connection.send_result(msg["id"], manager.ai.status(msg["issue_id"]))
    except HomeboardError as err:
        connection.send_error(msg["id"], err.code, str(err))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "homeboard/ai/preview",
        vol.Required("issue_id"): cv.string,
        vol.Optional("note"): cv.string,
    }
)
@websocket_api.async_response
async def ws_ai_preview(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Show exactly what would be sent to the AI (nothing is sent)."""
    manager = _ai(hass, connection, msg)
    if manager is None:
        return
    try:
        result = await manager.ai.preview(msg["issue_id"], msg.get("note", ""))
    except HomeboardError as err:
        connection.send_error(msg["id"], err.code, str(err))
        return
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "homeboard/ai/analyze",
        vol.Required("issue_id"): cv.string,
        vol.Optional("note"): vol.All(cv.string, vol.Length(max=AI_NOTE_MAX)),
    }
)
@websocket_api.async_response
async def ws_ai_analyze(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Start an analysis in the background."""
    manager = _ai(hass, connection, msg)
    if manager is None:
        return
    try:
        result = await manager.ai.analyze(
            msg["issue_id"], msg.get("note", ""), manager.person_for_user(connection.user.id)
        )
    except HomeboardError as err:
        connection.send_error(msg["id"], err.code, str(err))
        return
    connection.send_result(msg["id"], result)


def _ai_proposal_command(name: str, method: str) -> Callable[..., Any]:
    @websocket_api.require_admin
    @websocket_api.websocket_command(
        {
            vol.Required("type"): f"homeboard/ai/{name}",
            vol.Required("issue_id"): cv.string,
            vol.Required("proposal_id"): cv.string,
        }
    )
    @websocket_api.async_response
    async def command(
        hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
    ) -> None:
        manager = _ai(hass, connection, msg)
        if manager is None:
            return
        actor = manager.person_for_user(connection.user.id)
        try:
            if method == "dismiss":
                proposal = manager.ai.dismiss(msg["issue_id"], msg["proposal_id"])
            else:
                proposal = await getattr(manager.ai, method)(
                    msg["issue_id"], msg["proposal_id"], actor
                )
        except HomeboardError as err:
            connection.send_error(msg["id"], err.code, str(err))
            return
        connection.send_result(msg["id"], {"proposal": proposal})

    command.__name__ = f"ws_ai_{name}"
    return command


ws_ai_apply = _ai_proposal_command("apply", "apply")
ws_ai_undo = _ai_proposal_command("undo", "undo")
ws_ai_dismiss = _ai_proposal_command("dismiss", "dismiss")


def _habits(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> Any:
    """Return the habits scanner or answer with an error."""
    manager: HomeboardData | None = hass.data.get(DOMAIN)
    if manager is None or manager.habits is None:
        connection.send_error(msg["id"], "not_loaded", "Homeboard is not set up")
        return None
    return manager


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "homeboard/habits/scan"})
@websocket_api.async_response
async def ws_habits_scan(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Scan the history for habits now."""
    manager = _habits(hass, connection, msg)
    if manager is None:
        return
    if not manager.habits.enabled:
        connection.send_error(msg["id"], "habits_disabled", "Habits is switched off")
        return
    connection.send_result(msg["id"], await manager.habits.async_scan())


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "homeboard/habits/create", vol.Required("suggestion_id"): cv.string}
)
@websocket_api.async_response
async def ws_habits_create(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Create the (switched off) automation of an idea."""
    manager = _habits(hass, connection, msg)
    if manager is None:
        return
    try:
        created = await manager.habits.async_create(
            msg["suggestion_id"], manager.person_for_user(connection.user.id)
        )
    except HomeboardError as err:
        connection.send_error(msg["id"], err.code, str(err))
        return
    connection.send_result(msg["id"], {"created": created})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "homeboard/habits/undo", vol.Required("created_id"): cv.string}
)
@websocket_api.async_response
async def ws_habits_undo(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Remove an automation that was created from an idea."""
    manager = _habits(hass, connection, msg)
    if manager is None:
        return
    try:
        created = await manager.habits.async_undo(msg["created_id"])
    except HomeboardError as err:
        connection.send_error(msg["id"], err.code, str(err))
        return
    connection.send_result(msg["id"], {"created": created})


COMMANDS = (
    ws_get,
    ws_subscribe,
    ws_project_create,
    ws_project_update,
    ws_project_delete,
    ws_status_create,
    ws_status_update,
    ws_status_reorder,
    ws_status_delete,
    ws_issue_create,
    ws_issue_get,
    ws_issue_update,
    ws_issue_move,
    ws_issue_delete,
    ws_issue_comment,
    ws_issue_list,
    ws_quick_add,
    ws_quick_add_preview,
    ws_recurring_create,
    ws_recurring_update,
    ws_recurring_delete,
    ws_recurring_run_now,
    ws_checklist_add,
    ws_checklist_update,
    ws_checklist_remove,
    ws_checklist_reorder,
    ws_attachment_remove,
    ws_attachment_snapshot,
    ws_suggest,
    ws_insights_get,
    ws_insights_accept,
    ws_insights_dismiss,
    ws_insights_forget,
    ws_health_scan,
    ws_ai_get,
    ws_ai_preview,
    ws_ai_analyze,
    ws_ai_apply,
    ws_ai_undo,
    ws_ai_dismiss,
    ws_habits_scan,
    ws_habits_create,
    ws_habits_undo,
)


@callback
def async_register_websocket_api(hass: HomeAssistant) -> None:
    """Register every command."""
    for command in COMMANDS:
        websocket_api.async_register_command(hass, command)
