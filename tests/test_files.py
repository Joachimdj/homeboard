"""Attachments: upload view, signed downloads, thumbnails, camera snapshots, cleanup."""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import FormData
from PIL import Image
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.homeboard import const, files
from custom_components.homeboard.model import InvalidError


def png(size=(40, 30), color=(200, 30, 30), mode="RGB") -> bytes:
    out = io.BytesIO()
    Image.new(mode, size, color).save(out, format="PNG")
    return out.getvalue()


def jpeg(size=(800, 600)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (10, 120, 200)).save(out, format="JPEG")
    return out.getvalue()


def form(issue_id, data, filename="photo.png", content_type="image/png"):
    body = FormData()
    body.add_field("issue_id", issue_id)
    body.add_field("file", data, filename=filename, content_type=content_type)
    return body


@pytest.fixture(autouse=True)
def isolated_files(hass, tmp_path):
    """Keep every test's files in its own temporary config folder."""
    hass.config.config_dir = str(tmp_path)


@pytest.fixture
async def client(hass, manager, hass_client):
    return await hass_client()


@pytest.fixture
def files_dir(hass):
    from pathlib import Path

    return Path(hass.config.path(const.FILES_DIR))


async def test_sniffing_and_names():
    assert files.sniff_mime(png()) == "image/png"
    assert files.sniff_mime(jpeg()) == "image/jpeg"
    assert files.sniff_mime(b"GIF89a....") == "image/gif"
    assert files.sniff_mime(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert files.sniff_mime(b"%PDF-1.7 ...") == "application/pdf"
    for bad in (b"<svg xmlns='http://www.w3.org/2000/svg'/>", b"#!/bin/sh\n", b"", b"MZ\x90\x00"):
        assert files.sniff_mime(bad) is None
    assert files.clean_filename(
        "../../etc/pass\x00wd.png", "image/png"
    ) == "pass\x00wd.png".replace("\x00", "")
    assert files.clean_filename("C:\\dir\\pic.jpg", "image/jpeg") == "pic.jpg"
    assert files.clean_filename("", "application/pdf") == "file.pdf"
    assert len(files.clean_filename("x" * 500, "image/png")) == files.MAX_NAME


async def test_thumbnails():
    assert files.make_thumbnail(b"%PDF-1.7", "application/pdf") is None
    assert files.make_thumbnail(b"not an image", "image/png") is None
    thumb = files.make_thumbnail(jpeg((1600, 1200)), "image/jpeg")
    assert files.sniff_mime(thumb) == "image/jpeg"
    with Image.open(io.BytesIO(thumb)) as image:
        assert max(image.size) == const.THUMB_SIZE
    clear = files.make_thumbnail(png(mode="RGBA", color=(1, 2, 3, 0)), "image/png")
    assert files.sniff_mime(clear) == "image/png"  # transparency is kept
    assert files.image_pixels(png((10, 20))) == 200 and files.image_pixels(b"junk") is None


async def test_upload_download_thumbnail_and_delete(
    hass, manager, client, hass_client_no_auth, files_dir, hass_ws_client
):
    events = async_capture_events(hass, const.EVENT_ATTACHMENT_ADDED)
    issue, _ = manager.create_issue("HOME", "Gate is broken")
    response = await client.post("/api/homeboard/upload", data=form(issue["key"], jpeg()))
    assert response.status == 201
    attachment = await response.json()
    assert (
        attachment["name"] == "photo.png" and attachment["mime"] == "image/jpeg"
    )  # type from content, not the claim
    assert attachment["source"] == "upload" and attachment["size"] == len(jpeg())
    assert "authSig=" in attachment["url"] and "authSig=" in attachment["thumb_url"]
    assert manager.issue_view(issue)["attachment_count"] == 1
    assert (files_dir / f"{attachment['id']}.jpg").is_file() and (
        files_dir / f"{attachment['id']}.thumb"
    ).is_file()
    await hass.async_block_till_done()
    assert (
        events[0].data["attachment"]["id"] == attachment["id"] and events[0].data["key"] == "HOME-1"
    )

    anonymous = await hass_client_no_auth()
    full = await anonymous.get(attachment["url"])
    assert full.status == 200 and full.headers["Content-Type"] == "image/jpeg"
    assert (
        full.headers["X-Content-Type-Options"] == "nosniff"
        and "sandbox" in full.headers["Content-Security-Policy"]
    )
    assert len(await full.read()) == len(jpeg())
    thumb = await anonymous.get(attachment["thumb_url"])
    assert thumb.status == 200 and thumb.headers["Content-Type"] == "image/jpeg"
    assert len(await thumb.read()) < len(jpeg())
    assert (
        await anonymous.get(f"/api/homeboard/files/{attachment['id']}")
    ).status == 401  # unsigned, no token
    assert (
        await client.get(f"/api/homeboard/files/{attachment['id']}")
    ).status == 200  # a bearer token works too

    detail = manager.issue_detail(issue)["attachments"][0]
    assert detail["id"] == attachment["id"] and "authSig=" in detail["url"]

    ws = await hass_ws_client(hass)
    await ws.send_json_auto_id(
        {
            "type": "homeboard/attachment/remove",
            "issue_id": issue["id"],
            "attachment_id": attachment["id"],
        }
    )
    assert (await ws.receive_json())["result"] == {"deleted": attachment["id"]}
    await hass.async_block_till_done()
    assert issue["attachments"] == [] and list(files_dir.glob(f"{attachment['id']}.*")) == []
    assert (await client.get(f"/api/homeboard/files/{attachment['id']}")).status == 404
    await ws.send_json_auto_id(
        {"type": "homeboard/attachment/remove", "issue_id": issue["id"], "attachment_id": "nope"}
    )
    assert (await ws.receive_json())["error"]["code"] == "not_found"


async def test_pdf_has_no_thumbnail_and_png_thumb_keeps_type(manager, client, files_dir):
    issue, _ = manager.create_issue("HOME", "Manual")
    pdf = await (
        await client.post(
            "/api/homeboard/upload",
            data=form(issue["id"], b"%PDF-1.4 hello", "manual.pdf", "application/pdf"),
        )
    ).json()
    assert pdf["mime"] == "application/pdf" and pdf["thumb_url"] is None
    assert not (files_dir / f"{pdf['id']}.thumb").exists()
    served = await client.get(pdf["url"])
    assert served.headers["Content-Type"] == "application/pdf"
    clear = await (
        await client.post(
            "/api/homeboard/upload", data=form(issue["id"], png(mode="RGBA", color=(0, 0, 0, 0)))
        )
    ).json()
    assert (await client.get(clear["thumb_url"])).headers["Content-Type"] == "image/png"


async def test_upload_rejections(hass, manager, client):
    issue, _ = manager.create_issue("HOME", "x")
    bad_type = await client.post(
        "/api/homeboard/upload", data=form(issue["id"], b"<svg/>", "x.svg", "image/svg+xml")
    )
    assert bad_type.status == 415 and (await bad_type.json())["code"] == "unsupported_type"
    spoof = await client.post(
        "/api/homeboard/upload",
        data=form(issue["id"], b"#!/bin/sh\nrm -rf /", "x.png", "image/png"),
    )
    assert spoof.status == 415
    missing = await client.post("/api/homeboard/upload", data=form("HOME-99", png()))
    assert missing.status == 404 and (await missing.json())["code"] == "not_found"
    no_file = FormData()
    no_file.add_field("issue_id", issue["id"])
    assert (await client.post("/api/homeboard/upload", data=no_file)).status == 400
    assert (await client.post("/api/homeboard/upload", data="not multipart")).status == 400
    manager.options = {"max_upload_mb": 1}
    too_big = await client.post(
        "/api/homeboard/upload", data=form(issue["id"], png() + b"0" * (1024 * 1024 + 10))
    )
    assert too_big.status == 413 and (await too_big.json())["code"] == "too_large"
    manager.options = {"attachments_enabled": False}
    off = await client.post("/api/homeboard/upload", data=form(issue["id"], png()))
    assert off.status == 403
    assert issue["attachments"] == []


async def test_huge_images_are_refused(manager, monkeypatch):
    issue, _ = manager.create_issue("HOME", "x")
    monkeypatch.setattr(files, "MAX_PIXELS", 100)
    with pytest.raises(files.UnsupportedTypeError):
        await manager.files.async_add(issue["id"], "big.png", png((20, 20)), author=None)
    with pytest.raises(files.UnsupportedTypeError):
        await manager.files.async_add(
            issue["id"], "broken.png", b"\x89PNG\r\n\x1a\n" + b"garbage", author=None
        )


async def test_attachment_limit_per_issue(manager, monkeypatch):
    issue, _ = manager.create_issue("HOME", "x")
    monkeypatch.setattr(files, "MAX_ATTACHMENTS", 2)
    for _ in range(2):
        await manager.files.async_add(issue["id"], "a.png", png(), author=None)
    with pytest.raises(InvalidError):
        await manager.files.async_add(issue["id"], "a.png", png(), author=None)


async def test_deleting_an_issue_or_project_deletes_its_files(hass, manager, files_dir):
    a, _ = manager.create_issue("HOME", "a")
    b, _ = manager.create_issue("HOME", "b")
    one = await manager.files.async_add(a["id"], "1.png", png(), author=None)
    two = await manager.files.async_add(b["id"], "2.png", png(), author=None)
    manager.delete_issue(a["id"])
    await hass.async_block_till_done()
    assert list(files_dir.glob(f"{one['id']}.*")) == [] and list(files_dir.glob(f"{two['id']}.*"))
    manager.delete_project("HOME")
    await hass.async_block_till_done()
    assert list(files_dir.glob("*")) == []


async def test_camera_snapshot_service_and_websocket(
    hass, manager, hass_ws_client, hass_admin_user
):
    from homeassistant.components.camera import Image as CameraImage

    hass.states.async_set("camera.front_door", "idle", {"friendly_name": "Front door"})
    issue, _ = manager.create_issue("HOME", "Someone at the door", dedupe_key="door")
    fake = AsyncMock(return_value=CameraImage("image/jpeg", jpeg((320, 240))))
    with patch("homeassistant.components.camera.async_get_image", fake):
        result = await hass.services.async_call(
            const.DOMAIN,
            "attach_camera_snapshot",
            {"project": "HOME", "dedupe_key": "door", "camera": "camera.front_door"},
            blocking=True,
            return_response=True,
        )
        assert (
            result["key"] == "HOME-1"
            and result["name"].startswith("Front door ")
            and result["name"].endswith(".jpg")
        )
        client = await hass_ws_client(hass)
        await client.send_json_auto_id(
            {
                "type": "homeboard/attachment/snapshot",
                "issue_id": issue["id"],
                "entity_id": "camera.front_door",
            }
        )
        reply = await client.receive_json()
    assert (
        reply["success"]
        and reply["result"]["source"] == "camera"
        and "authSig=" in reply["result"]["url"]
    )
    assert [a["source"] for a in issue["attachments"]] == ["camera", "camera"]
    fake.assert_awaited()


async def test_camera_errors_become_messages(hass, manager):
    from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

    issue, _ = manager.create_issue("HOME", "x")
    with (
        patch(
            "homeassistant.components.camera.async_get_image",
            AsyncMock(side_effect=HomeAssistantError("offline")),
        ),
        pytest.raises(ServiceValidationError, match="Could not get a picture"),
    ):
        await hass.services.async_call(
            const.DOMAIN,
            "attach_camera_snapshot",
            {"issue": issue["id"], "camera": "camera.gone"},
            blocking=True,
            return_response=True,
        )
    with pytest.raises(InvalidError):
        await manager.files.async_snapshot(issue["id"], "light.kitchen", author=None)


async def test_camera_snapshot_websocket_checks_permissions(hass, manager, hass_ws_client):
    from pytest_homeassistant_custom_component.common import CLIENT_ID, MockUser

    user = MockUser(name="Limited").add_to_hass(hass)
    user.mock_policy({"entities": {"entity_ids": {"camera.allowed": True}}})
    refresh = await hass.auth.async_create_refresh_token(user, CLIENT_ID)
    token = hass.auth.async_create_access_token(refresh)
    issue, _ = manager.create_issue("HOME", "x")
    client = await hass_ws_client(hass, token)
    await client.send_json_auto_id(
        {
            "type": "homeboard/attachment/snapshot",
            "issue_id": issue["id"],
            "entity_id": "camera.private",
        }
    )
    assert (await client.receive_json())["error"]["code"] == "unauthorized"


async def test_views_report_not_loaded(hass, entry, hass_client):
    from .conftest import setup

    await setup(hass, entry)
    client = await hass_client()
    await hass.config_entries.async_unload(entry.entry_id)
    assert (await client.post("/api/homeboard/upload", data=form("x", png()))).status == 503
    assert (await client.get("/api/homeboard/files/abc")).status == 503
