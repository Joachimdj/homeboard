"""The homeboard/* websocket API."""

from __future__ import annotations

import pytest

from .conftest import status_id


@pytest.fixture
async def ws(hass, manager, hass_ws_client, hass_admin_user):
    hass.states.async_set(
        "person.admin", "home", {"friendly_name": "Admin", "user_id": hass_admin_user.id}
    )
    return await hass_ws_client(hass)


async def send(ws, type_, **kw):
    await ws.send_json_auto_id({"type": f"homeboard/{type_}", **kw})
    return await ws.receive_json()


async def test_get_returns_the_payload(ws, manager, hass_admin_user):
    manager.create_issue("HOME", "x")
    reply = await send(ws, "get")
    assert reply["success"]
    payload = reply["result"]
    assert payload["is_admin"] is True and payload["me"] == "person.admin"
    assert [i["summary"] for i in payload["issues"]] == ["x"]
    assert {p["entity_id"] for p in payload["people"]} >= {"person.admin", "person.joachim"}
    assert payload["stats"]["total"]["open"] == 1


async def test_subscribe_pushes_now_and_after_every_change(ws, manager, hass):
    await ws.send_json_auto_id({"type": "homeboard/subscribe"})
    assert (await ws.receive_json())["success"]
    first = await ws.receive_json()
    assert first["type"] == "event" and first["event"]["issues"] == []
    manager.create_issue("HOME", "live")
    manager.create_issue("HOME", "burst")  # coalesced into the same push
    await hass.async_block_till_done()
    pushed = await ws.receive_json()
    assert [i["summary"] for i in pushed["event"]["issues"]] == ["live", "burst"]


async def test_issue_lifecycle_over_the_wire(ws, manager):
    project_id = manager.resolve_project("HOME")["id"]
    made = (
        await send(
            ws,
            "issue/create",
            project_id=project_id,
            summary="Wire it",
            issue_type="bug",
            priority="high",
            assignee="person.joachim",
            labels=["a"],
            due="2031-01-01",
        )
    )["result"]
    assert made["key"] == "HOME-1" and made["type"] == "bug" and made["source"] == "ui"
    assert made["reporter"] == "person.admin"
    issue_id = made["id"]

    updated = (
        await send(
            ws,
            "issue/update",
            issue_id=issue_id,
            summary="Wired",
            assignee="",
            issue_type="task",
            due="",
        )
    )["result"]
    assert (
        updated["summary"] == "Wired"
        and updated["assignee"] is None
        and updated["due"] is None
        and updated["type"] == "task"
    )

    done = status_id(manager, "Done")
    moved = (await send(ws, "issue/move", issue_id=issue_id, status=done))["result"]
    assert moved["resolved"] is not None
    second = (await send(ws, "issue/create", project_id=project_id, summary="Second"))["result"]
    top = (await send(ws, "issue/move", issue_id=second["id"], status=done, before=issue_id))[
        "result"
    ]
    assert top["rank"] < moved["rank"]

    comment = (await send(ws, "issue/comment", issue_id=issue_id, text="hi"))["result"]
    assert comment["author"] == "person.admin"
    detail = (await send(ws, "issue/get", issue_id=issue_id))["result"]
    assert detail["comments"][0]["text"] == "hi" and detail["activity"]

    listing = (await send(ws, "issue/list", query="wired"))["result"]
    assert listing["total"] == 1
    assert (await send(ws, "issue/update", issue_id=issue_id, archived=True))["success"]
    assert (await send(ws, "issue/list", archived=True, limit=5, offset=0, project_id=project_id))[
        "result"
    ]["total"] == 1
    assert (await send(ws, "issue/delete", issue_id=second["id"]))["result"] == {
        "deleted": second["id"]
    }


async def test_errors_carry_codes(ws, manager):
    missing = await send(ws, "issue/get", issue_id="nope")
    assert not missing["success"] and missing["error"]["code"] == "not_found"
    bad = await send(ws, "issue/create", project_id="nope", summary="x")
    assert bad["error"]["code"] == "not_found"
    invalid = await send(
        ws, "issue/create", project_id=manager.resolve_project("HOME")["id"], summary="   "
    )
    assert invalid["error"]["code"] == "invalid_format"
    conflict = await send(ws, "project/create", key="HOME", name="Dup")
    assert conflict["error"]["code"] == "conflict"
    schema = await send(ws, "issue/create", project_id="x", summary="x", priority="p0")
    assert schema["error"]["code"] == "invalid_format"


async def test_quick_add_and_preview(ws, manager):
    preview = (
        await send(ws, "quick_add/preview", text="bug: gate @padmaja !high #garden due 2031-04-04")
    )["result"]
    assert (
        preview["summary"] == "gate"
        and preview["assignee"] == "person.padmaja"
        and preview["project"] == "HOME"
    )
    assert manager.issues == {}
    me = (await send(ws, "quick_add/preview", text="x @me"))["result"]
    assert me["assignee"] == "person.admin"
    added = (await send(ws, "quick_add", text="Buy milk !low", project="HOME"))["result"]
    assert added["issue"]["summary"] == "Buy milk" and added["issue"]["source"] == "ui"
    assert added["parsed"]["priority"] == "low"
    bad = await send(ws, "quick_add", text="@joachim")
    assert bad["error"]["code"] == "invalid_format"


async def test_project_and_status_admin_commands(ws, manager):
    created = (
        await send(
            ws,
            "project/create",
            key="car",
            name="Car",
            template="software",
            color="#000",
            icon="mdi:car",
            description="d",
            lead="person.joachim",
        )
    )["result"]
    pid = created["id"]
    assert created["key"] == "CAR"
    assert (
        await send(
            ws,
            "project/update",
            project_id=pid,
            name="Garage",
            lead="",
            default_assignee="person.padmaja",
            labels=["x"],
            archived=False,
            color="#111",
            icon="mdi:home",
            description="e",
        )
    )["result"]["name"] == "Garage"
    new = (
        await send(
            ws,
            "status/create",
            project_id=pid,
            name="Parts",
            category="in_progress",
            wip=2,
            backlog=False,
            position=1,
        )
    )["result"]
    assert (
        await send(
            ws,
            "status/update",
            project_id=pid,
            status_id=new["id"],
            name="Ordered",
            category="todo",
            backlog=True,
            wip=None,
        )
    )["result"]["name"] == "Ordered"
    ids = [s["id"] for s in manager.resolve_project(pid)["statuses"]]
    assert (await send(ws, "status/reorder", project_id=pid, status_ids=list(reversed(ids))))[
        "result"
    ] == {"ok": True}
    assert (await send(ws, "status/delete", project_id=pid, status_id=new["id"]))["result"] == {
        "deleted": new["id"]
    }
    assert (await send(ws, "project/delete", project_id=pid, confirm=True))["result"] == {
        "deleted": pid
    }
    no_confirm = await send(ws, "project/delete", project_id="x", confirm=False)
    assert not no_confirm["success"]


async def test_recurring_commands(ws, manager):
    pid = manager.resolve_project("HOME")["id"]
    rec = (
        await send(
            ws,
            "recurring/create",
            project_id=pid,
            summary="Bins",
            issue_type="task",
            repeat={"unit": "week", "weekdays": [2]},
            next_due="2099-01-07",
            assignee="person.joachim",
            create_days_before=1,
            skip_if_open=True,
            enabled=True,
            priority="low",
            labels=["c"],
            description="d",
            status="",
        )
    )["result"]
    assert rec["next_due"] == "2099-01-07"
    changed = (
        await send(ws, "recurring/update", recurring_id=rec["id"], summary="Bins out", assignee="")
    )["result"]
    assert changed["summary"] == "Bins out" and changed["assignee"] is None
    ran = (await send(ws, "recurring/run_now", recurring_id=rec["id"]))["result"]
    assert ran["issue"]["recurring_id"] == rec["id"]
    assert (await send(ws, "recurring/run_now", recurring_id=rec["id"]))["result"] == {
        "issue": None
    }
    assert (await send(ws, "recurring/delete", recurring_id=rec["id"]))["result"] == {
        "deleted": rec["id"]
    }


async def test_non_admin_cannot_manage_projects_but_can_edit_issues(
    hass, manager, hass_ws_client, hass_read_only_access_token
):
    client = await hass_ws_client(hass, hass_read_only_access_token)
    payload = (await send(client, "get"))["result"]
    assert payload["is_admin"] is False
    for cmd, args in (
        ("project/create", {"key": "NEW", "name": "New"}),
        ("project/update", {"project_id": "x", "name": "n"}),
        ("project/delete", {"project_id": "x", "confirm": True}),
        ("status/create", {"project_id": "x", "name": "n", "category": "todo"}),
        ("status/update", {"project_id": "x", "status_id": "y", "name": "n"}),
        ("status/reorder", {"project_id": "x", "status_ids": []}),
        ("status/delete", {"project_id": "x", "status_id": "y"}),
        ("health/scan", {}),
    ):
        reply = await send(client, cmd, **args)
        assert not reply["success"] and reply["error"]["code"] == "unauthorized", cmd
    pid = manager.resolve_project("HOME")["id"]
    assert (await send(client, "issue/create", project_id=pid, summary="kids can add"))["success"]


async def test_commands_report_not_loaded(hass, entry, hass_ws_client):
    from .conftest import setup

    await setup(hass, entry)
    client = await hass_ws_client(hass)
    await hass.config_entries.async_unload(entry.entry_id)
    for cmd in ("get", "subscribe", "issue/get"):
        extra = {"issue_id": "x"} if cmd == "issue/get" else {}
        reply = await send(client, cmd, **extra)
        assert reply["error"]["code"] == "not_loaded"
