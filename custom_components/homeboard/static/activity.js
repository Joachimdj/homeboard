// Human text for activity log entries. Pure.

import { t } from "./i18n.js";
import { personName } from "./indexes.js";

const FIELD_KEYS = new Set(["summary", "description", "type", "priority", "assignee", "labels", "due", "parent", "status", "checklist", "attachments"]);

function formatValue(field, value, index) {
  if (value == null || value === "" || (Array.isArray(value) && !value.length)) return t("activity.none");
  if (field === "assignee") return personName(index, value);
  if (field === "type") return t(`type.${value}`);
  if (field === "priority") return t(`priority.${value}`);
  if (Array.isArray(value)) return value.join(", ");
  const text = String(value);
  return text.length > 60 ? `${text.slice(0, 57)}...` : text;
}

/** Sentence fragment without the actor, e.g. "moved from To do to Done". */
export function describeActivity(entry, index) {
  const from = formatValue(entry.field, entry.from, index);
  const to = formatValue(entry.field, entry.to, index);
  switch (entry.kind) {
    case "created":
      return t("activity.created");
    case "moved":
      return t("activity.moved", { from, to });
    case "assigned":
      return t("activity.assigned", { from, to });
    case "commented":
      return t("activity.commented");
    case "completed":
      return t("activity.completed");
    case "reopened":
      return t("activity.reopened");
    case "archived":
      return t("activity.archived");
    default: {
      const field = FIELD_KEYS.has(entry.field) ? t(`field.${entry.field}`) : entry.field || "";
      return t("activity.updated", { field, from, to });
    }
  }
}
