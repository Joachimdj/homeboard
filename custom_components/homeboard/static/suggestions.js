// Smart defaults (PROTOCOL 10.4): display chips and filling a draft. Pure.

import { t, tn } from "./i18n.js";
import { personName } from "./indexes.js";
import { PRIORITY_META, localDateString } from "./util.js";

export function hasSuggestion(suggestion) {
  return Boolean(
    suggestion && (suggestion.assignee || suggestion.labels?.length || suggestion.priority || suggestion.due_in_days != null),
  );
}

export function dueFromDays(days, now = new Date()) {
  return localDateString(new Date(now.getFullYear(), now.getMonth(), now.getDate() + days));
}

/** [{ kind, text, icon?, color?, person? }] in the order assignee, labels, priority, due. */
export function suggestionChips(suggestion, { index } = {}) {
  if (!hasSuggestion(suggestion)) return [];
  const chips = [];
  if (suggestion.assignee) {
    chips.push({ kind: "assignee", text: index ? personName(index, suggestion.assignee) : suggestion.assignee, person: suggestion.assignee });
  }
  for (const label of suggestion.labels || []) chips.push({ kind: "label", text: `#${label}`, label });
  if (suggestion.priority) {
    chips.push({ kind: "priority", text: t(`priority.${suggestion.priority}`), icon: PRIORITY_META[suggestion.priority]?.icon, color: PRIORITY_META[suggestion.priority]?.color });
  }
  if (suggestion.due_in_days != null) {
    const text = suggestion.due_in_days === 0 ? t("suggest.due_today") : tn("suggest.due_in", suggestion.due_in_days);
    chips.push({ kind: "due", text, icon: "mdi:calendar-outline" });
  }
  return chips;
}

/** "Padmaja, #bills, due in 3 days" for tooltips and screen readers. */
export function suggestionSummary(chips) {
  return chips.map((chip) => chip.text).join(", ");
}

/** Similar issues with the matching board issue id when it is loaded: [{ key, summary, status, id }]. */
export function similarIssues(suggestion, index) {
  return (suggestion?.similar || []).map((s) => ({ ...s, id: index?.issueByKey.get(s.key)?.id || null }));
}

/**
 * What the new-issue form's Suggest button fills: only fields the user left empty.
 * draft: { assignee, labels, priority, due }, touched: Set of field names the user changed.
 * Returns { fields, filled } where `fields` are draft values and `filled` the field names.
 */
export function suggestionFill(suggestion, draft, { touched = new Set(), now = new Date() } = {}) {
  const fields = {};
  if (suggestion?.assignee && !draft.assignee) fields.assignee = suggestion.assignee;
  if (suggestion?.labels?.length && !(draft.labels || []).length) fields.labels = [...suggestion.labels];
  if (suggestion?.priority && !touched.has("priority")) fields.priority = suggestion.priority;
  if (suggestion?.due_in_days != null && !draft.due) fields.due = dueFromDays(suggestion.due_in_days, now);
  return { fields, filled: Object.keys(fields) };
}
