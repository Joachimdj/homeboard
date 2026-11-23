// Pure logic of AI Fix (PROTOCOL section 11): which buttons a proposal gets, how a diff is
// classified, which text keys a status maps to. No DOM access in here. Everything that comes
// from the model (titles, diffs, steps, errors) is untrusted; this module never turns such a
// string into a translation key or a class name, it only picks from fixed lists.

import { getLocale } from "./i18n.js";

export const NOTE_MAX = 500;

export const KINDS = ["automation_edit", "automation_disable", "reload_integration", "manual_steps"];
export const RISKS = ["low", "medium", "high"];
export const CONFIDENCES = ["low", "medium", "high"];
export const STATUSES = ["proposed", "applied", "dismissed", "failed", "undone"];
export const REASONS = ["disabled", "no_entity", "choose_entity", "unsupported", "limit"];
export const ERROR_CODES = ["ai_disabled", "ai_unavailable", "ai_limit", "ai_busy", "not_applied"];

// ---- visibility and chips ---------------------------------------------------------------------

/** The dialog section exists for administrators, when the option is on, and not while an issue is being created. */
export function sectionVisible({ aiFix, isAdmin, create }) {
  return Boolean(isAdmin) && !create && aiFix?.enabled === true;
}

/** Chip on cards and rows: "ready" (a proposal waits), "running", or null. Non-admin payloads have no `ai`. */
export function chipState(issue) {
  const ai = issue?.ai;
  if (!ai) return null;
  if (ai.state === "running") return "running";
  if (ai.state === "ready" && Number(ai.proposals) > 0) return "ready";
  return null;
}

/** `issue.ai.rev`, or null while the issue has no record. The dialog refetches `ai/get` when it changes. */
export function aiRev(issue) {
  const rev = issue?.ai?.rev;
  return rev == null ? null : rev;
}

// ---- reasons, errors ----------------------------------------------------------------------------

/** Key for `ai/get`.reason. null = no reason; unknown values fall back to the generic text, never to nothing. */
export function reasonText(reason) {
  if (reason == null || reason === "") return null;
  return REASONS.includes(reason) ? `ai.reason.${reason}` : "ai.reason.unknown";
}

/** Key of the line shown while the AI cannot be used, or null. `running` explains a not-ready state by itself. */
export function notReadyKey(info, running = false) {
  if (!info || info.ready) return null;
  return reasonText(info.reason) || (running ? null : "ai.reason.unknown");
}

/** Friendly key for a websocket error code, or null (then the server message is shown). */
export function errorKey(code) {
  return ERROR_CODES.includes(code) ? `ai.error.${code}` : null;
}

// ---- labels (always picked from fixed lists) --------------------------------------------------

export function riskLevel(risk) {
  return RISKS.includes(risk) ? risk : "medium";
}

export const riskLabel = (risk) => `ai.risk.${riskLevel(risk)}`;

export function confidenceLabel(confidence) {
  return CONFIDENCES.includes(confidence) ? `ai.confidence.${confidence}` : null;
}

export const isKnownKind = (kind) => KINDS.includes(kind);

export const kindLabel = (kind) => `ai.kind.${isKnownKind(kind) ? kind : "unknown"}`;

/** The main button: "Apply", or "Add to checklist" for manual steps. */
export const applyLabel = (kind) => (kind === "manual_steps" ? "ai.add_to_checklist" : "ai.apply");

/** Question of the confirm row, or null when a single press is enough (adding checklist items). */
export function confirmKey(kind) {
  if (kind === "automation_edit") return "ai.confirm_edit";
  if (kind === "automation_disable") return "ai.confirm_disable";
  if (kind === "reload_integration") return "ai.confirm_reload";
  return null;
}

export const statusKind = (status) => (STATUSES.includes(status) ? status : "proposed");

// ---- buttons ---------------------------------------------------------------------------------

const hasText = (value) => typeof value === "string" && value.trim() !== "";

/**
 * Buttons of one proposal, in display order: "apply", "dismiss", "undo", "copy".
 * A blocked proposal cannot be applied but can still be dismissed and copied. Undo needs `undoable`
 * (the backend sets it only for applied automation edits and disables).
 */
export function proposalActions(proposal) {
  if (!proposal) return [];
  const copy = hasText(proposal.new_yaml);
  switch (proposal.status) {
    case "proposed": {
      const list = [];
      if (!proposal.blocked && isKnownKind(proposal.kind)) list.push("apply");
      list.push("dismiss");
      if (copy) list.push("copy");
      return list;
    }
    case "applied":
      return proposal.undoable === true ? ["undo"] : [];
    case "failed":
      return copy ? ["copy"] : [];
    default:
      return [];
  }
}

/** Replace one proposal in a record by the one the server returned; the record is not mutated. */
export function replaceProposal(record, proposal) {
  if (!record || !proposal) return record;
  return { ...record, proposals: (record.proposals || []).map((p) => (p.id === proposal.id ? proposal : p)) };
}

// ---- diff ------------------------------------------------------------------------------------

/**
 * "add" | "del" | "hunk" | "meta" | "ctx" for one unified-diff line. Outside a hunk, "---" / "+++" are the
 * file headers ("meta"); inside a hunk they are an ordinary removed / added line (a YAML "---").
 */
export function classifyDiffLine(line, { inHunk = false } = {}) {
  const text = String(line ?? "");
  if (text.startsWith("@@")) return "hunk";
  if (!inHunk && (text.startsWith("--- ") || text.startsWith("+++ ") || text === "---" || text === "+++")) return "meta";
  if (text.startsWith("\\")) return "meta"; // "\ No newline at end of file"
  if (text.startsWith("+")) return "add";
  if (text.startsWith("-")) return "del";
  return "ctx";
}

/** A unified diff as [{ kind, text }], tracking where the hunks start. Anything that is not text gives []. */
export function parseDiff(diff) {
  if (typeof diff !== "string" || !diff.trim()) return [];
  const lines = diff.replace(/\r\n?/g, "\n").split("\n");
  if (lines.at(-1) === "") lines.pop();
  let inHunk = false;
  return lines.map((text) => {
    const kind = classifyDiffLine(text, { inHunk });
    if (kind === "hunk") inHunk = true;
    return { kind, text };
  });
}

// ---- numbers ---------------------------------------------------------------------------------

export function formatCount(count, locale = getLocale()) {
  const n = Number(count) || 0;
  try {
    return new Intl.NumberFormat(locale).format(n);
  } catch {
    return String(n);
  }
}

const count = (value) => Math.max(0, Math.floor(Number(value) || 0));

/** `record.sent` as three clean integers, or null when the server sent nothing usable. */
export function summariseSent(sent) {
  if (!sent || typeof sent !== "object") return null;
  return { chars: count(sent.chars), entities: count(sent.entities), automations: count(sent.automations) };
}

/** Same for the `ai/preview` answer (adds the number of masked values). */
export function summarisePreview(preview) {
  if (!preview || typeof preview !== "object") return null;
  return { chars: count(preview.chars), entities: count(preview.entities), automations: count(preview.automations), redactions: count(preview.redactions) };
}

/** The "Analyse" button may be pressed. `working` = any AI call is in flight. */
export function canAnalyse(info, { running = false, working = false } = {}) {
  return Boolean(info?.ready) && !running && !working;
}
