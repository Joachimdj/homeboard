// File rules for attachments (mirrors the server) and small helpers. Pure.

import { getLocale } from "./i18n.js";

export const ALLOWED_MIME = ["image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf"];
export const FILE_ACCEPT = "image/*,application/pdf";

export const isImage = (attachment) => String(attachment?.mime || "").startsWith("image/");
export const isPdf = (attachment) => attachment?.mime === "application/pdf";

/** Returns { ok: true } or { ok: false, reason: "type" | "size" } like the server's 415 / 413. */
export function validateFile(file, { maxMb } = {}) {
  if (!ALLOWED_MIME.includes(file.type)) return { ok: false, reason: "type" };
  if (maxMb && file.size > maxMb * 1024 * 1024) return { ok: false, reason: "size" };
  return { ok: true };
}

/** Message key and variables for a failed upload, from the HTTP status (or a client-side reason). */
export function uploadError(status, { maxMb } = {}) {
  if (status === 413 || status === "size") return { key: "attachments.error_size", vars: { mb: maxMb } };
  if (status === 415 || status === "type") return { key: "attachments.error_type", vars: {} };
  if (status === 404) return { key: "attachments.error_missing", vars: {} };
  return { key: "attachments.error_upload", vars: { status } };
}

export function formatSize(bytes, locale = getLocale()) {
  const units = ["B", "KB", "MB", "GB"];
  let value = Number(bytes) || 0;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = unit === 0 || value >= 100 ? 0 : 1;
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(value)} ${units[unit]}`;
}

/** Files of a clipboard / drop DataTransfer that look like something we can attach. */
export function filesFromTransfer(transfer) {
  return transfer ? [...(transfer.files || [])] : [];
}

/** camera.* entities of hass.states as [{ entity_id, name }], sorted by name. */
export function cameraEntities(states) {
  return Object.values(states || {})
    .filter((state) => state.entity_id.startsWith("camera."))
    .map((state) => ({ entity_id: state.entity_id, name: state.attributes?.friendly_name || state.entity_id.slice(7).replace(/_/g, " ") }))
    .sort((a, b) => a.name.localeCompare(b.name));
}
