import assert from "node:assert/strict";
import { test } from "node:test";
import { ALLOWED_MIME, cameraEntities, formatSize, isImage, isPdf, uploadError, validateFile } from "../../custom_components/homeboard/static/attachments-util.js";

const file = (type, size) => ({ type, size });

test("validateFile mirrors the server: type first, then size", () => {
  assert.deepEqual(validateFile(file("image/png", 1000), { maxMb: 10 }), { ok: true });
  assert.deepEqual(validateFile(file("application/pdf", 10 * 1024 * 1024), { maxMb: 10 }), { ok: true });
  assert.deepEqual(validateFile(file("application/pdf", 10 * 1024 * 1024 + 1), { maxMb: 10 }), { ok: false, reason: "size" });
  assert.deepEqual(validateFile(file("text/plain", 5), { maxMb: 10 }), { ok: false, reason: "type" });
  assert.deepEqual(validateFile(file("image/svg+xml", 5), { maxMb: 10 }), { ok: false, reason: "type" });
  assert.deepEqual(validateFile(file("image/heic", 5), { maxMb: 10 }), { ok: false, reason: "type" });
  assert.deepEqual(validateFile(file("image/gif", 5 * 1024 * 1024), {}), { ok: true });
  assert.equal(ALLOWED_MIME.length, 5);
});

test("uploadError maps HTTP statuses and client reasons to message keys", () => {
  assert.deepEqual(uploadError(413, { maxMb: 10 }), { key: "attachments.error_size", vars: { mb: 10 } });
  assert.deepEqual(uploadError("size", { maxMb: 2 }), { key: "attachments.error_size", vars: { mb: 2 } });
  assert.equal(uploadError(415).key, "attachments.error_type");
  assert.equal(uploadError("type").key, "attachments.error_type");
  assert.equal(uploadError(404).key, "attachments.error_missing");
  assert.deepEqual(uploadError(500), { key: "attachments.error_upload", vars: { status: 500 } });
});

test("formatSize and file kind helpers", () => {
  assert.equal(formatSize(0, "en"), "0 B");
  assert.equal(formatSize(900, "en"), "900 B");
  assert.equal(formatSize(1536, "en"), "1.5 KB");
  assert.equal(formatSize(5 * 1024 * 1024, "en"), "5 MB");
  assert.equal(formatSize(2.5 * 1024 * 1024, "da"), "2,5 MB");
  assert.equal(isImage({ mime: "image/webp" }), true);
  assert.equal(isImage({ mime: "application/pdf" }), false);
  assert.equal(isPdf({ mime: "application/pdf" }), true);
  assert.equal(isImage(undefined), false);
});

test("cameraEntities lists camera.* states by friendly name", () => {
  const states = {
    "light.kitchen": { entity_id: "light.kitchen", attributes: { friendly_name: "Kitchen" } },
    "camera.garden": { entity_id: "camera.garden", attributes: { friendly_name: "Garden" } },
    "camera.front_door": { entity_id: "camera.front_door", attributes: {} },
    "camera.alley": { entity_id: "camera.alley", attributes: { friendly_name: "Alley" } },
  };
  assert.deepEqual(cameraEntities(states).map((c) => c.name), ["Alley", "front door", "Garden"]);
  assert.deepEqual(cameraEntities(undefined), []);
});
