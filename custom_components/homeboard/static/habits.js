// Pure logic of Habits: automation ideas in the Insights inbox (PROTOCOL section 12). No DOM access in
// here. Everything the backend sends (titles, details, YAML, aliases, messages, entity ids, patterns) is
// untrusted: this module never turns such a string into a translation key, a class name or a URL. It only
// picks from fixed lists, and the one link it produces (`haEditPath`) is checked against a fixed shape.

import { t, tn } from "./i18n.js";
import { formatMinutes } from "./insights.js";
import { clamp, relativeTime } from "./util.js";

export const IDEA_KIND = "automation";
export const PATTERNS = ["routine", "follow_up", "switch_back"];
export const GENERIC_PATTERN_ICON = "mdi:auto-fix";
const PATTERN_ICONS = { routine: "mdi:clock-outline", follow_up: "mdi:motion-sensor", switch_back: "mdi:timer-outline" };

/** The scanner needs at least this many days of recorder history (the owner's recorder keeps about 11). */
export const MIN_HISTORY_DAYS = 7;
export const CREATED_MAX = 20;

export const ERROR_CODES = ["exists", "blocked", "not_editable", "create_failed", "habits_disabled", "not_found", "stale", "backup_missing"];
export const SCAN_ERRORS = ["no_recorder", "no_history", "failed"];

const text = (value) => (typeof value === "string" ? value : typeof value === "number" && Number.isFinite(value) ? String(value) : "");
const hasText = (value) => typeof value === "string" && value.trim() !== "";
const clip = (value, max) => (value.length > max ? `${value.slice(0, max - 1)}…` : value);

/** A non-negative whole number, or null for anything else (strings, NaN, negatives). */
function whole(value) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? Math.round(value) : null;
}

// ---- features and permissions -------------------------------------------------------------------

/** "on" | "off" | "absent". A 0.3 backend has no `features.habits` at all: then there is nothing to show. */
export function habitsState(features) {
  if (features?.habits === true) return "on";
  if (features?.habits === false) return "off";
  return "absent";
}

/** Create, Undo and Scan now are for administrators, and only while the feature is on. */
export function canCreate(isAdmin, features) {
  return Boolean(isAdmin) && habitsState(features) === "on";
}

// ---- the inbox -------------------------------------------------------------------------------------

export const isIdea = (suggestion) => Boolean(suggestion) && suggestion.kind === IDEA_KIND && hasText(suggestion.id);

/** Splits `insights/get` suggestions into the inbox (kind `automation`) and everything else, order kept. */
export function splitSuggestions(suggestions) {
  const list = Array.isArray(suggestions) ? suggestions : [];
  return { ideas: list.filter(isIdea), others: list.filter((s) => !isIdea(s)) };
}

/** Icon, text key and (known) name of a pattern. An unknown one gets the generic icon and text. */
export function patternInfo(pattern) {
  const known = typeof pattern === "string" && PATTERNS.includes(pattern);
  return { pattern: known ? pattern : "other", icon: known ? PATTERN_ICONS[pattern] : GENERIC_PATTERN_ICON, labelKey: `habits.pattern.${known ? pattern : "other"}` };
}

function windowOf(value) {
  if (!Array.isArray(value) || value.length < 2) return null;
  const [from, to] = value;
  return hasText(from) && hasText(to) ? { from: clip(from.trim(), 16), to: clip(to.trim(), 16) } : null;
}

/**
 * The evidence of an idea as language independent parts:
 * `{ lead, percent, extras }`. `lead` and every extra are `{ key, count?, vars?, minutes? }`.
 * Nothing here assumes 28 days or a certain pattern: whatever numbers exist are used, in the same words for
 * every pattern (an unknown pattern simply gets the generic text).
 */
export function evidenceParts(evidence) {
  const e = evidence && typeof evidence === "object" && !Array.isArray(evidence) ? evidence : {};
  const days = whole(e.days);
  const of = whole(e.of);
  const share = typeof e.share === "number" && Number.isFinite(e.share) ? e.share : null;
  const percent = share == null ? null : Math.round(clamp(share, 0, 1) * 100);
  let lead = null;
  if (days != null && of != null && of >= days) lead = { key: "habits.evidence.days_of", vars: { days, of } };
  else if (days != null) lead = { key: "habits.evidence.days", count: days };
  const extras = [];
  const window = windowOf(e.window);
  if (window) extras.push({ key: "habits.evidence.window", vars: window });
  const delay = typeof e.delay_minutes === "number" && Number.isFinite(e.delay_minutes) && e.delay_minutes >= 0 ? e.delay_minutes : null;
  if (delay != null) extras.push({ key: "habits.evidence.delay", minutes: delay });
  const samples = whole(e.samples);
  if (!lead && percent == null && !extras.length && samples) extras.push({ key: "insights.evidence_samples", vars: { count: samples } });
  return { lead, percent, extras };
}

function renderPart(part) {
  if (part.count != null) return tn(part.key, part.count);
  if (part.minutes != null) return t(part.key, { delay: formatMinutes(part.minutes) });
  return t(part.key, part.vars);
}

/** "On 17 of 21 days (81%), between 06:28 and 06:42", or "" when the evidence has nothing to say. */
export function evidenceText(evidence) {
  const { lead, percent, extras } = evidenceParts(evidence);
  const segments = [];
  if (lead) segments.push(percent == null ? renderPart(lead) : `${renderPart(lead)} (${t("habits.evidence.percent", { percent })})`);
  else if (percent != null) segments.push(t("habits.evidence.share_only", { percent }));
  segments.push(...extras.map(renderPart));
  return segments.join(", ");
}

/** What an idea card shows, with every field coerced to a string. */
export function ideaView(suggestion) {
  const s = suggestion && typeof suggestion === "object" ? suggestion : {};
  const proposal = s.proposal && typeof s.proposal === "object" ? s.proposal : {};
  return {
    id: text(s.id),
    title: text(s.title),
    detail: text(s.detail).trim(),
    pattern: patternInfo(s.evidence?.pattern),
    evidence: evidenceText(s.evidence),
    alias: text(proposal.alias).trim(),
    yaml: hasText(proposal.yaml) ? proposal.yaml : "",
  };
}

// ---- created automations -------------------------------------------------------------------------

const EDIT_PATH = /^\/config\/automation\/edit\/[A-Za-z0-9_.~%-]+$/;
const AUTO_ID = /^[A-Za-z0-9_.~-]+$/;

/**
 * The Home Assistant page of an automation, as a path on this same origin, or null. `edit_url` is only
 * accepted when it has exactly the documented shape; otherwise the path is rebuilt from `auto_id`.
 * (An `href` from the backend is never used as it is: `javascript:` and other origins are refused.)
 */
export function haEditPath(editUrl, autoId) {
  if (typeof editUrl === "string" && EDIT_PATH.test(editUrl)) return editUrl;
  const id = text(autoId);
  return AUTO_ID.test(id) ? `/config/automation/edit/${id}` : null;
}

/** One record of `learned.habits.created` as the list shows it. `state` is created | undone | unknown. */
export function createdView(record) {
  const r = record && typeof record === "object" ? record : {};
  const state = r.state === "created" || r.state === "undone" ? r.state : "unknown";
  const id = text(r.id);
  return {
    id,
    alias: text(r.alias).trim() || text(r.entity_id).trim() || "",
    state,
    ts: typeof r.ts === "string" ? r.ts : null,
    editPath: state === "created" ? haEditPath(r.edit_url, r.auto_id) : null,
    canUndo: state === "created" && id !== "",
  };
}

const time = (iso) => {
  const ms = new Date(iso).getTime();
  return Number.isNaN(ms) ? -Infinity : ms;
};

/** The list under the inbox: newest first (the backend already sends it so), at most 20. */
export function createdList(created) {
  const list = (Array.isArray(created) ? created : []).filter((r) => r && typeof r === "object");
  return list
    .map((record, index) => ({ view: createdView(record), index }))
    .sort((a, b) => time(b.view.ts) - time(a.view.ts) || a.index - b.index)
    .slice(0, CREATED_MAX)
    .map((entry) => entry.view);
}

// ---- confirm, errors ----------------------------------------------------------------------------------

/** Question of the confirm row for "create" or "undo", else null. */
export function confirmKey(action) {
  if (action === "create") return "habits.confirm_create";
  if (action === "undo") return "habits.confirm_undo";
  return null;
}

/**
 * A websocket error as `{ code, titleKey, message }`: a fixed friendly title for the known codes, a generic one
 * for anything else, and the server's own message (never for `stale`, whose fixed text says it all).
 */
export function errorInfo(error) {
  const code = typeof error?.code === "string" ? error.code : "";
  if (code === "unauthorized") return { code, titleKey: "error.unauthorized", message: "" };
  const known = ERROR_CODES.includes(code);
  const message = typeof error?.message === "string" ? error.message.trim() : "";
  return { code, titleKey: known ? `habits.error.${code}` : "habits.error.generic", message: code === "stale" || message === code ? "" : message };
}

/** "Homeboard will not create this: <server message>", or just the title. */
export function errorText(info) {
  const title = t(info.titleKey);
  return info.message && info.message !== title ? `${title.replace(/\.$/, "")}: ${info.message}` : title;
}

// ---- scan --------------------------------------------------------------------------------------------------

/** Key for the `error` of a scan (the call result or `learned.habits.error`), or null when there is none. */
export function scanErrorKey(code) {
  if (code == null || code === "") return null;
  return SCAN_ERRORS.includes(code) ? `habits.scan.${code}` : "habits.scan.failed";
}

/** `{ kind: "error" | "found" | "nothing", key, count?, vars? }` for the answer of `habits/scan`. */
export function scanOutcome(result) {
  const errorKey = scanErrorKey(result?.error);
  if (errorKey) return { kind: "error", key: errorKey, vars: { days: MIN_HISTORY_DAYS } };
  const found = whole(result?.found) || 0;
  return found > 0 ? { kind: "found", key: "habits.scan.found", count: found } : { kind: "nothing", key: "habits.scan.nothing" };
}

export function scanOutcomeText(outcome) {
  if (!outcome) return "";
  return outcome.count != null ? tn(outcome.key, outcome.count) : t(outcome.key, outcome.vars);
}

/** The error of the last scan that is still on record (`learned.habits.error`), as text, or "". */
export function lastScanError(habits) {
  const key = scanErrorKey(habits?.error);
  return key ? t(key, { days: MIN_HISTORY_DAYS }) : "";
}

/** "Last scan 5 minutes ago, 120 entities, 28 days of history". */
export function statusLine(habits, { now = Date.now() } = {}) {
  const when = hasText(habits?.last_scan) ? relativeTime(habits.last_scan, { now }) : "";
  if (!when) return t("habits.status.never");
  const entities = whole(habits.scanned_entities);
  const days = whole(habits.days);
  if (entities == null || days == null) return t("habits.status.line_short", { time: when });
  return t("habits.status.line", { time: when, entities: tn("habits.n_entities", entities), history: tn("habits.n_history", days) });
}
