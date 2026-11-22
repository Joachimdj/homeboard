"""Attachments: photos and PDFs on issues, stored privately and served with signed URLs.

Files live in ``config/homeboard_files/`` (never under ``www``, so they are not
public). Metadata sits on the issue; the files are named after the attachment id.
Uploads arrive through an authenticated HTTP view, camera snapshots through
``async_snapshot``.
"""

from __future__ import annotations

import io
import logging
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from aiohttp import web
from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.components.http.auth import async_sign_path
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .const import (
    ALLOWED_MIME,
    CONF_ATTACHMENTS_ENABLED,
    CONF_MAX_UPLOAD_MB,
    DEFAULT_MAX_UPLOAD_MB,
    DOMAIN,
    EVENT_ATTACHMENT_ADDED,
    EVENT_ATTACHMENT_REMOVED,
    EVENT_ISSUE_UPDATED,
    FILES_DIR,
    FILES_URL_BASE,
    SIGNED_URL_SECONDS,
    THUMB_SIZE,
)
from .model import HomeboardError, InvalidError, NotFoundError, new_id

if TYPE_CHECKING:
    from .data import HomeboardData

_LOGGER = logging.getLogger(__name__)

MAX_PIXELS = 50_000_000
MAX_NAME = 120
MAX_ATTACHMENTS = 50
CHUNK = 64 * 1024


class FileTooLargeError(HomeboardError):
    """The upload is bigger than the limit."""

    code = "too_large"


class UnsupportedTypeError(HomeboardError):
    """The file is not a supported image or PDF."""

    code = "unsupported_type"


def sniff_mime(data: bytes) -> str | None:
    """Return the real type of a file from its first bytes (the client's claim is ignored)."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def clean_filename(name: str | None, mime: str) -> str:
    """Return a safe display name (no path, no control characters)."""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(ch for ch in base if ch.isprintable()).strip()
    if not base:
        base = f"file{ALLOWED_MIME[mime]}"
    return base[:MAX_NAME]


def make_thumbnail(data: bytes, mime: str) -> bytes | None:
    """Return a JPEG / PNG thumbnail for an image, or None (PDF, unreadable). Runs in the executor."""
    if not mime.startswith("image/"):
        return None
    from PIL import Image, ImageOps

    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > MAX_PIXELS:
                return None
            image = ImageOps.exif_transpose(image)
            image.thumbnail((THUMB_SIZE, THUMB_SIZE))
            has_alpha = image.mode in ("RGBA", "LA") or (
                image.mode == "P" and "transparency" in image.info
            )
            out = io.BytesIO()
            if has_alpha:
                image.convert("RGBA").save(out, format="PNG", optimize=True)
            else:
                image.convert("RGB").save(out, format="JPEG", quality=82, optimize=True)
            return out.getvalue()
    except Exception:
        return None


def image_pixels(data: bytes) -> int | None:
    """Return width * height of an image without decoding it (None if unreadable)."""
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as image:
            return image.width * image.height
    except Exception:
        return None


class FileStore:
    """Reads and writes attachment files and keeps the issue metadata in step."""

    def __init__(self, hass: HomeAssistant, manager: HomeboardData) -> None:
        """Initialise the store."""
        self.hass = hass
        self.manager = manager

    # -- settings

    @property
    def directory(self) -> Path:
        """Return the folder the files live in."""
        return Path(self.hass.config.path(FILES_DIR))

    @property
    def enabled(self) -> bool:
        """Return True if attachments are switched on."""
        return bool(self.manager.options.get(CONF_ATTACHMENTS_ENABLED, True))

    @property
    def max_bytes(self) -> int:
        """Return the upload limit in bytes."""
        return (
            int(self.manager.options.get(CONF_MAX_UPLOAD_MB, DEFAULT_MAX_UPLOAD_MB)) * 1024 * 1024
        )

    # -- lookups

    def find(self, attachment_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
        """Return ``(issue, attachment)`` for an attachment id."""
        for issue in self.manager.issues.values():
            for attachment in issue["attachments"]:
                if attachment["id"] == attachment_id:
                    return issue, attachment
        return None

    def file_path(self, attachment: dict[str, Any], *, thumb: bool = False) -> Path:
        """Return the path of an attachment's file (or its thumbnail)."""
        suffix = ".thumb" if thumb else ALLOWED_MIME[attachment["mime"]]
        return self.directory / f"{attachment['id']}{suffix}"

    def describe(self, attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return attachments with signed ``url`` / ``thumb_url`` (valid one hour)."""
        expiry = timedelta(seconds=SIGNED_URL_SECONDS)
        described = []
        for attachment in attachments:
            base = f"{FILES_URL_BASE}/files/{attachment['id']}"
            described.append(
                {
                    **attachment,
                    "url": async_sign_path(self.hass, base, expiry),
                    "thumb_url": (
                        async_sign_path(self.hass, f"{base}/thumb", expiry)
                        if attachment["mime"].startswith("image/")
                        else None
                    ),
                }
            )
        return described

    # -- writing

    async def async_add(
        self,
        issue_ref: str,
        name: str | None,
        data: bytes,
        *,
        author: str | None,
        source: str = "upload",
    ) -> dict[str, Any]:
        """Validate and store a file, then attach it to the issue."""
        if not self.enabled:
            raise InvalidError("Attachments are switched off")
        issue = self.manager.resolve_issue(issue_ref)
        if len(issue["attachments"]) >= MAX_ATTACHMENTS:
            raise InvalidError(f"An issue holds at most {MAX_ATTACHMENTS} attachments")
        if len(data) > self.max_bytes:
            raise FileTooLargeError(f"The file is larger than {self.max_bytes // (1024 * 1024)} MB")
        mime = sniff_mime(data)
        if mime is None:
            raise UnsupportedTypeError("Only jpeg, png, webp, gif and pdf files can be attached")
        if mime.startswith("image/"):
            pixels = await self.hass.async_add_executor_job(image_pixels, data)
            if pixels is None or pixels > MAX_PIXELS:
                raise UnsupportedTypeError("The image is unreadable or too large")
        attachment = {
            "id": new_id(),
            "name": clean_filename(name, mime),
            "mime": mime,
            "size": len(data),
            "ts": dt_util.utcnow().isoformat(timespec="seconds"),
            "author": author,
            "source": source,
        }
        await self.hass.async_add_executor_job(self._write, attachment, data)
        before = len(issue["attachments"])
        issue["attachments"].append(attachment)
        self._record(issue, author, before, EVENT_ATTACHMENT_ADDED, attachment)
        return attachment

    def _write(self, attachment: dict[str, Any], data: bytes) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.file_path(attachment).write_bytes(data)
        if (thumb := make_thumbnail(data, attachment["mime"])) is not None:
            self.file_path(attachment, thumb=True).write_bytes(thumb)

    def _record(
        self,
        issue: dict[str, Any],
        actor: str | None,
        before: int,
        event: str,
        attachment: dict[str, Any],
    ) -> None:
        manager = self.manager
        manager._touch(issue)
        after = len(issue["attachments"])
        manager._activity(issue, actor, "updated", "attachments", str(before), str(after))
        data = manager._issue_event(issue, actor, "ui")
        manager._commit(
            [
                (event, {**data, "attachment": attachment}),
                (
                    EVENT_ISSUE_UPDATED,
                    {**data, "changes": {"attachments": {"from": before, "to": after}}},
                ),
            ]
        )

    async def async_remove(self, issue_ref: str, attachment_id: str, *, actor: str | None) -> None:
        """Detach and delete one attachment."""
        issue = self.manager.resolve_issue(issue_ref)
        for attachment in issue["attachments"]:
            if attachment["id"] == attachment_id:
                break
        else:
            raise NotFoundError(f"Unknown attachment {attachment_id!r}")
        before = len(issue["attachments"])
        issue["attachments"].remove(attachment)
        self._record(issue, actor, before, EVENT_ATTACHMENT_REMOVED, attachment)
        self.async_delete_files([attachment_id])

    async def async_snapshot(
        self, issue_ref: str, entity_id: str, *, author: str | None
    ) -> dict[str, Any]:
        """Take a still image from a camera and attach it."""
        if not entity_id.startswith("camera."):
            raise InvalidError("entity_id must be a camera")
        from homeassistant.components.camera import async_get_image

        try:
            image = await async_get_image(self.hass, entity_id, timeout=15)
        except (HomeAssistantError, TimeoutError) as err:
            raise InvalidError(f"Could not get a picture from {entity_id}: {err}") from err
        state = self.hass.states.get(entity_id)
        stamp = dt_util.now().strftime("%Y-%m-%d %H%M")
        name = f"{(state.name if state else entity_id)} {stamp}.jpg"
        return await self.async_add(issue_ref, name, image.content, author=author, source="camera")

    # -- deleting

    @callback
    def async_delete_files(self, attachment_ids: list[str]) -> None:
        """Delete files (and thumbnails) in the background."""
        if attachment_ids:
            self.hass.async_create_task(self._async_delete(list(attachment_ids)))

    async def _async_delete(self, attachment_ids: list[str]) -> None:
        await self.hass.async_add_executor_job(self._delete, attachment_ids)

    def _delete(self, attachment_ids: list[str]) -> None:
        for attachment_id in attachment_ids:
            for path in self.directory.glob(f"{attachment_id}.*"):
                try:
                    path.unlink()
                except OSError as err:
                    _LOGGER.warning("Could not delete %s: %s", path, err)


def _json_error(view: HomeAssistantView, err: HomeboardError) -> web.Response:
    status = {
        "too_large": 413,
        "unsupported_type": 415,
        "not_found": 404,
    }.get(err.code, 400)
    return view.json_message(str(err), status_code=status, message_code=err.code)


class UploadView(HomeAssistantView):
    """``POST /api/homeboard/upload`` (multipart: ``issue_id`` and ``file``)."""

    url = f"{FILES_URL_BASE}/upload"
    name = "api:homeboard:upload"

    async def post(self, request: web.Request) -> web.Response:
        """Receive one file for an issue."""
        hass = request.app[KEY_HASS]
        manager = hass.data.get(DOMAIN)
        if manager is None or manager.files is None:
            return self.json_message("Homeboard is not set up", 503, "not_loaded")
        store: FileStore = manager.files
        if not store.enabled:
            return self.json_message("Attachments are switched off", 403, "disabled")
        limit = store.max_bytes
        if request.content_length and request.content_length > limit + CHUNK * 4:
            return self.json_message("The file is too large", 413, "too_large")

        issue_id: str | None = None
        filename: str | None = None
        data = bytearray()
        got_file = False
        try:
            reader = await request.multipart()
            while (part := await reader.next()) is not None:
                if part.name == "issue_id":
                    issue_id = (await part.text()).strip()
                elif part.name == "file":
                    got_file = True
                    filename = part.filename
                    while chunk := await part.read_chunk(CHUNK):
                        data.extend(chunk)
                        if len(data) > limit:
                            return self.json_message("The file is too large", 413, "too_large")
        except (ValueError, AssertionError):
            return self.json_message("Expected multipart form data", 400, "invalid_format")
        if not issue_id or not got_file:
            return self.json_message("issue_id and file are required", 400, "invalid_format")

        user = request.get("hass_user")
        author = manager.person_for_user(user.id) if user else None
        try:
            attachment = await store.async_add(issue_id, filename, bytes(data), author=author)
        except HomeboardError as err:
            return _json_error(self, err)
        return self.json(store.describe([attachment])[0], status_code=201)


class FileView(HomeAssistantView):
    """``GET /api/homeboard/files/<id>[/thumb]`` (signed path or bearer token)."""

    url = f"{FILES_URL_BASE}/files/{{attachment_id}}"
    extra_urls = [f"{FILES_URL_BASE}/files/{{attachment_id}}/thumb"]
    name = "api:homeboard:file"

    async def get(self, request: web.Request, attachment_id: str) -> web.StreamResponse:
        """Serve a file."""
        hass = request.app[KEY_HASS]
        manager = hass.data.get(DOMAIN)
        if manager is None or manager.files is None:
            return self.json_message("Homeboard is not set up", 503, "not_loaded")
        store: FileStore = manager.files
        found = store.find(attachment_id)
        if found is None:
            return self.json_message("Unknown attachment", 404, "not_found")
        _issue, attachment = found
        thumb = request.path.endswith("/thumb")
        path = store.file_path(attachment, thumb=thumb)
        if thumb and not await hass.async_add_executor_job(path.is_file):
            path = store.file_path(attachment)  # no thumbnail: fall back to the original
            thumb = False
        if not await hass.async_add_executor_job(path.is_file):
            return self.json_message("The file is gone", 404, "not_found")
        content_type = (
            (await hass.async_add_executor_job(_thumb_mime, path)) if thumb else attachment["mime"]
        )
        headers = {
            "Content-Type": content_type,
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(attachment['name'])}",
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'; img-src 'self'; style-src 'unsafe-inline'",
        }
        return web.FileResponse(path, headers=headers)


def _thumb_mime(path: Path) -> str:
    """Return the type of a stored thumbnail (PNG when it kept transparency, else JPEG)."""
    try:
        with path.open("rb") as handle:
            return sniff_mime(handle.read(16)) or "image/jpeg"
    except OSError:
        return "image/jpeg"


@callback
def async_register_views(hass: HomeAssistant) -> None:
    """Register the upload and download views (once per Home Assistant run)."""
    key = f"{DOMAIN}_views_registered"
    if hass.data.get(key):
        return
    hass.http.register_view(UploadView())
    hass.http.register_view(FileView())
    hass.data[key] = True
