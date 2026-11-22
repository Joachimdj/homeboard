"""Checklists on issues."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.homeboard import const
from custom_components.homeboard.checklist import checklist_counts
from custom_components.homeboard.model import ConflictError, InvalidError, NotFoundError


async def test_add_tick_edit_remove_with_events_and_activity(hass, manager):
    events = async_capture_events(hass, const.EVENT_ISSUE_UPDATED)
    issue, _ = manager.create_issue("HOME", "Plan the trip")
    a = manager.add_checklist_item(
        issue["id"], "  Book   flights ", actor="person.joachim", source="ui"
    )
    b = manager.add_checklist_item(issue["key"], "Book hotel")
    assert a["text"] == "Book flights" and a["done"] is False
    assert checklist_counts(issue) == (0, 2)
    manager.update_checklist_item(issue["id"], a["id"], done=True)
    manager.update_checklist_item(issue["id"], "book hotel", text="Book a hotel", done=True)
    assert checklist_counts(issue) == (2, 2)
    assert b["text"] == "Book a hotel"
    manager.update_checklist_item(issue["id"], a["id"], done=True)  # no change -> nothing happens
    manager.remove_checklist_item(issue["id"], a["id"])
    assert checklist_counts(issue) == (1, 1)
    await hass.async_block_till_done()
    changes = [e.data["changes"]["checklist"] for e in events]
    assert changes == [
        {"from": "0/0", "to": "0/1"},
        {"from": "0/1", "to": "0/2"},
        {"from": "0/2", "to": "1/2"},
        {"from": "1/2", "to": "2/2"},
        {"from": "2/2", "to": "1/1"},
    ]
    assert events[0].data["actor"] == "person.joachim"
    assert [x["field"] for x in issue["activity"] if x["field"] == "checklist"] == ["checklist"] * 5


async def test_validation(manager):
    issue, _ = manager.create_issue("HOME", "x")
    for bad in ("", "   ", "x" * 300):
        with pytest.raises(InvalidError):
            manager.add_checklist_item(issue["id"], bad)
    manager.add_checklist_item(issue["id"], "same")
    manager.add_checklist_item(issue["id"], "Same")
    with pytest.raises(ConflictError):
        manager.update_checklist_item(issue["id"], "same", done=True)  # ambiguous by text
    with pytest.raises(NotFoundError):
        manager.update_checklist_item(issue["id"], "missing", done=True)
    with pytest.raises(NotFoundError):
        manager.remove_checklist_item(issue["id"], "missing")
    with pytest.raises(InvalidError):
        manager.update_checklist_item(issue["id"], issue["checklist"][0]["id"], text=" ")
    for n in range(const.CHECKLIST_MAX_ITEMS - 2):
        manager.add_checklist_item(issue["id"], f"item {n}")
    with pytest.raises(InvalidError):
        manager.add_checklist_item(issue["id"], "one too many")


async def test_reorder(manager):
    issue, _ = manager.create_issue("HOME", "x")
    ids = [manager.add_checklist_item(issue["id"], t)["id"] for t in "abc"]
    manager.reorder_checklist(issue["id"], [ids[2], ids[0], ids[1]])
    assert [i["text"] for i in issue["checklist"]] == ["c", "a", "b"]
    for bad in (ids[:2], ids + ids[:1], ["x", "y", "z"]):
        with pytest.raises(InvalidError):
            manager.reorder_checklist(issue["id"], bad)


async def test_list_payload_counts_but_hides_items_detail_has_them(manager):
    issue, _ = manager.create_issue("HOME", "x")
    manager.add_checklist_item(issue["id"], "one")
    item = manager.add_checklist_item(issue["id"], "two")
    manager.update_checklist_item(issue["id"], item["id"], done=True)
    view = manager.issue_view(issue)
    assert (view["checklist_done"], view["checklist_total"], view["attachment_count"]) == (1, 2, 0)
    assert "checklist" not in view and "attachments" not in view
    detail = manager.issue_detail(issue)
    assert [i["text"] for i in detail["checklist"]] == ["one", "two"] and detail[
        "attachments"
    ] == []


async def test_autodone_moves_the_issue_when_the_last_item_is_ticked(manager):
    manager.options = {"checklist_autodone": True}
    issue, _ = manager.create_issue("HOME", "x")
    a = manager.add_checklist_item(issue["id"], "a")
    b = manager.add_checklist_item(issue["id"], "b")
    manager.update_checklist_item(issue["id"], a["id"], done=True)
    assert manager.category(issue) == "todo"
    manager.update_checklist_item(issue["id"], b["id"], done=True)
    assert manager.category(issue) == "done" and issue["resolved"]
    manager.options = {}
    other, _ = manager.create_issue("HOME", "y")
    c = manager.add_checklist_item(other["id"], "c")
    manager.update_checklist_item(other["id"], c["id"], done=True)
    assert manager.category(other) == "todo"  # off by default


async def test_epic_progress_in_the_list_payload(manager):
    epic, _ = manager.create_issue("HOME", "Big", type="epic")
    a, _ = manager.create_issue("HOME", "a", parent=epic["id"])
    manager.create_issue("HOME", "b", parent=epic["id"])
    manager.move_issue(a["id"], "Done")
    view = manager.issue_view(epic)
    assert (view["epic_done"], view["epic_total"]) == (1, 2)
    assert "epic_total" not in manager.issue_view(a)


async def test_documents_from_0_1_get_the_new_fields(hass, entry):
    from .conftest import setup

    await setup(hass, entry)
    manager = entry.runtime_data
    issue, _ = manager.create_issue("HOME", "from 0.1")
    del issue["checklist"], issue["attachments"]  # what a 0.1 document looks like
    manager.learning_data = {}
    await manager.async_save_now()
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    again = entry.runtime_data.issues[issue["id"]]
    assert again["checklist"] == [] and again["attachments"] == []


async def test_services(hass, manager):
    issue, _ = manager.create_issue("HOME", "x", dedupe_key="k")
    added = await hass.services.async_call(
        const.DOMAIN,
        "add_checklist_item",
        {"project": "HOME", "dedupe_key": "k", "text": "first"},
        blocking=True,
        return_response=True,
    )
    assert added["key"] == "HOME-1" and added["item_id"]
    ticked = await hass.services.async_call(
        const.DOMAIN,
        "check_item",
        {"issue": "HOME-1", "item": "first"},
        blocking=True,
        return_response=True,
    )
    assert ticked["done"] is True and checklist_counts(issue) == (1, 1)
    await hass.services.async_call(
        const.DOMAIN,
        "check_item",
        {"issue": "HOME-1", "item": added["item_id"], "done": False},
        blocking=True,
        return_response=True,
    )
    assert checklist_counts(issue) == (0, 1)
    await hass.services.async_call(
        const.DOMAIN,
        "remove_checklist_item",
        {"issue": "HOME-1", "item": "first"},
        blocking=True,
        return_response=True,
    )
    assert issue["checklist"] == []


async def test_websocket_commands(hass, manager, hass_ws_client):
    client = await hass_ws_client(hass)
    issue, _ = manager.create_issue("HOME", "x")

    async def send(kind, **kw):
        await client.send_json_auto_id(
            {"type": f"homeboard/checklist/{kind}", "issue_id": issue["id"], **kw}
        )
        return await client.receive_json()

    one = (await send("add", text="one"))["result"]
    two = (await send("add", text="two"))["result"]
    assert (await send("update", item_id=one["id"], done=True, text="uno"))["result"][
        "text"
    ] == "uno"
    assert (await send("reorder", item_ids=[two["id"], one["id"]]))["result"] == {"ok": True}
    assert [i["text"] for i in issue["checklist"]] == ["two", "uno"]
    assert (await send("remove", item_id=two["id"]))["result"] == {"deleted": two["id"]}
    missing = await send("update", item_id="nope", done=True)
    assert missing["error"]["code"] == "not_found"
    detail = None
    await client.send_json_auto_id({"type": "homeboard/issue/get", "issue_id": issue["id"]})
    detail = (await client.receive_json())["result"]
    assert detail["checklist"] == [{"id": one["id"], "text": "uno", "done": True}]
