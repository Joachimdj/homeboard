// Checklist and epic progress maths, item ordering. Pure.

export const CHECKLIST_MAX_ITEMS = 100;
export const CHECKLIST_TEXT_MAX = 200;

function progress(done, total) {
  return { done, total, percent: total ? Math.round((done / total) * 100) : 0 };
}

export function checklistProgress(items) {
  return progress((items || []).filter((item) => item.done).length, (items || []).length);
}

/** Progress of an issue's checklist from the list payload counters; null without items. */
export function issueChecklist(issue) {
  return issue.checklist_total ? progress(issue.checklist_done || 0, issue.checklist_total) : null;
}

/** Progress of an epic over its child issues; null for other types or no children. */
export function epicProgress(issue) {
  return issue.type === "epic" && issue.epic_total ? progress(issue.epic_done || 0, issue.epic_total) : null;
}

/** Ids with the item at `from` moved to position `to` (clamped). */
export function moveIndex(ids, from, to) {
  if (from < 0 || from >= ids.length) return ids;
  const target = Math.max(0, Math.min(ids.length - 1, to));
  if (target === from) return ids;
  const next = [...ids];
  next.splice(target, 0, next.splice(from, 1)[0]);
  return next;
}

/** Move the item `id` one step up (-1) or down (+1). */
export function moveBy(ids, id, delta) {
  return moveIndex(ids, ids.indexOf(id), ids.indexOf(id) + delta);
}

/** Index of the row under `y` given the rows' [top, bottom] spans; clamps above / below the list. */
export function rowIndexAt(spans, y) {
  if (!spans.length) return -1;
  const found = spans.findIndex(([top, bottom]) => y >= top && y < bottom);
  if (found !== -1) return found;
  return y < spans[0][0] ? 0 : spans.length - 1;
}

/** Split pasted text into item texts: one per non-empty line, list markers removed. */
export function splitItems(text) {
  return String(text || "")
    .split(/\r?\n/)
    .map((line) => line.replace(/^\s*(?:[-*•]|\[[ xX]?\])\s*/, "").trim())
    .filter(Boolean)
    .map((line) => line.slice(0, CHECKLIST_TEXT_MAX));
}
