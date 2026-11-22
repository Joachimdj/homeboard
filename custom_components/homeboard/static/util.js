// Small pure helpers shared by every module. No DOM access in here.

import { getLocale } from "./i18n.js";

export const PRIORITIES = ["highest", "high", "medium", "low", "lowest"];
export const CATEGORIES = ["todo", "in_progress", "done"];
export const WEEKDAYS = [0, 1, 2, 3, 4, 5, 6]; // Monday = 0, like the backend

export const TYPE_META = {
  task: { icon: "mdi:checkbox-marked-circle-outline", color: "#3b9ee0" },
  bug: { icon: "mdi:bug-outline", color: "#e5493a" },
  story: { icon: "mdi:bookmark-outline", color: "#4caf50" },
  epic: { icon: "mdi:lightning-bolt", color: "#9b59d0" },
};

export const PRIORITY_META = {
  highest: { icon: "mdi:chevron-double-up", color: "#d32f2f" },
  high: { icon: "mdi:chevron-up", color: "#f4511e" },
  medium: { icon: "mdi:equal", color: "#f9a825" },
  low: { icon: "mdi:chevron-down", color: "#1e88e5" },
  lowest: { icon: "mdi:chevron-double-down", color: "#64b5f6" },
};

export function cx(...parts) {
  return parts.filter(Boolean).join(" ");
}

export function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

export function debounce(fn, ms) {
  let timer = null;
  const wrapped = (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      fn(...args);
    }, ms);
  };
  wrapped.cancel = () => {
    clearTimeout(timer);
    timer = null;
  };
  return wrapped;
}

function hashString(text) {
  let hash = 5381;
  for (let i = 0; i < text.length; i++) {
    hash = ((hash << 5) + hash + text.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

export function labelColor(label) {
  return `hsl(${hashString(String(label).toLowerCase()) % 360} 55% 42%)`;
}

export function avatarColor(seed) {
  return `hsl(${hashString(String(seed)) % 360} 45% 38%)`;
}

export function initials(name) {
  const words = String(name || "").trim().split(/\s+/).filter(Boolean);
  if (!words.length) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[words.length - 1][0]).toUpperCase();
}

/** "person.joachim" -> "Joachim" when no friendly name is known. */
export function nameFromEntityId(entityId) {
  const object = String(entityId || "").split(".").pop() || "";
  return object.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

const pad = (n) => String(n).padStart(2, "0");

function localDateString(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function todayString(now = new Date()) {
  return localDateString(now instanceof Date ? now : new Date(now));
}

function isDateOnly(due) {
  return typeof due === "string" && /^\d{4}-\d{2}-\d{2}$/.test(due);
}

/** Parse a `due` value; date-only strings become local midnight. */
export function parseDue(due) {
  if (!due) return null;
  if (isDateOnly(due)) {
    const [y, m, d] = due.split("-").map(Number);
    return new Date(y, m - 1, d);
  }
  const date = new Date(due);
  return Number.isNaN(date.getTime()) ? null : date;
}

function startOfDay(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function dayDiff(date, now = new Date()) {
  return Math.round((startOfDay(date) - startOfDay(now)) / 86400000);
}

function capitalise(text) {
  return text ? text[0].toUpperCase() + text.slice(1) : text;
}

/** Short human text for a due value: "Today", "Fri", "24 Nov", "24 Nov 18:00". */
export function formatDue(due, { now = new Date(), locale = getLocale() } = {}) {
  const date = parseDue(due);
  if (!date) return "";
  const diff = dayDiff(date, now);
  let day;
  if (diff >= -1 && diff <= 1) {
    day = capitalise(new Intl.RelativeTimeFormat(locale, { numeric: "auto" }).format(diff, "day"));
  } else if (diff > 1 && diff < 7) {
    day = capitalise(new Intl.DateTimeFormat(locale, { weekday: "short" }).format(date));
  } else {
    const opts = { day: "numeric", month: "short" };
    if (date.getFullYear() !== now.getFullYear()) opts.year = "numeric";
    day = new Intl.DateTimeFormat(locale, opts).format(date);
  }
  if (isDateOnly(due)) return day;
  return `${day} ${new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" }).format(date)}`;
}

/** "5 minutes ago" style text; null/invalid input gives "". */
export function relativeTime(iso, { now = Date.now(), locale = getLocale() } = {}) {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const seconds = Math.round((then - now) / 1000);
  const abs = Math.abs(seconds);
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  if (abs < 45) return rtf.format(0, "second");
  if (abs < 3600) return rtf.format(Math.round(seconds / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(seconds / 3600), "hour");
  if (abs < 7 * 86400) return rtf.format(Math.round(seconds / 86400), "day");
  const date = new Date(then);
  const opts = { day: "numeric", month: "short" };
  if (date.getFullYear() !== new Date(now).getFullYear()) opts.year = "numeric";
  return new Intl.DateTimeFormat(locale, opts).format(date);
}

export function formatDateTime(iso, locale = getLocale()) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

/** Split a `due` value into the two form inputs ("2026-11-30", "18:00"). */
export function splitDue(due) {
  if (!due) return { date: "", time: "" };
  if (isDateOnly(due)) return { date: due, time: "" };
  const date = parseDue(due);
  if (!date) return { date: "", time: "" };
  return { date: localDateString(date), time: `${pad(date.getHours())}:${pad(date.getMinutes())}` };
}

/** Inverse of splitDue; datetimes carry the browser's UTC offset. */
export function joinDue(date, time) {
  if (!date) return null;
  if (!time) return date;
  const [y, m, d] = date.split("-").map(Number);
  const [hh, mm] = time.split(":").map(Number);
  const local = new Date(y, m - 1, d, hh, mm);
  const offset = -local.getTimezoneOffset();
  const sign = offset >= 0 ? "+" : "-";
  const abs = Math.abs(offset);
  return `${date}T${pad(hh)}:${pad(mm)}:00${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
}

export function uniqueSorted(values) {
  return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b));
}
