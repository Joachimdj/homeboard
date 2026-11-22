// Turns the parsed quick-add result into display chips. Pure.

import { t } from "./i18n.js";
import { findProject, personName } from "./indexes.js";
import { PRIORITY_META, TYPE_META, formatDue } from "./util.js";

/**
 * parsed: { summary, project, type, priority, assignee, labels, due, unresolved? }
 * Returns [{ kind, text, icon?, color?, person? }]; the summary itself is not a chip.
 */
export function buildChips(parsed, { index, now = new Date() } = {}) {
  if (!parsed) return [];
  const chips = [];
  const project = index ? findProject(index, parsed.project) : null;
  if (parsed.project) chips.push({ kind: "project", text: project ? project.key : String(parsed.project), icon: "mdi:folder-outline" });
  if (parsed.type) chips.push({ kind: "type", text: t(`type.${parsed.type}`), icon: TYPE_META[parsed.type]?.icon, color: TYPE_META[parsed.type]?.color });
  if (parsed.priority) {
    chips.push({ kind: "priority", text: t(`priority.${parsed.priority}`), icon: PRIORITY_META[parsed.priority]?.icon, color: PRIORITY_META[parsed.priority]?.color });
  }
  if (parsed.assignee) {
    chips.push({ kind: "assignee", text: index ? personName(index, parsed.assignee) : parsed.assignee, person: parsed.assignee });
  }
  if (parsed.due) chips.push({ kind: "due", text: formatDue(parsed.due, { now }), icon: "mdi:calendar-outline" });
  for (const label of parsed.labels || []) chips.push({ kind: "label", text: `#${label}`, label });
  for (const token of parsed.unresolved || []) chips.push({ kind: "unresolved", text: token, icon: "mdi:help-circle-outline" });
  return chips;
}
