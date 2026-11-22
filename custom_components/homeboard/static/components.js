// Small view helpers (vnode builders) shared by panel, dialogs and cards.

import { epicProgress, issueChecklist } from "./checklist.js";
import { h } from "./dom.js";
import { t, tn } from "./i18n.js";
import { personName } from "./indexes.js";
import { PRIORITY_META, TYPE_META, avatarColor, formatDue, initials, labelColor } from "./util.js";

export const icon = (name, props = {}) => h("ha-icon", { icon: name, ...props });

export function typeIcon(type) {
  const meta = TYPE_META[type] || TYPE_META.task;
  return h("ha-icon.type-icon", { icon: meta.icon, style: { color: meta.color }, title: t(`type.${type}`) });
}

export function priorityIcon(priority) {
  const meta = PRIORITY_META[priority] || PRIORITY_META.medium;
  return h("ha-icon.prio-icon", { icon: meta.icon, style: { color: meta.color }, title: t(`priority.${priority}`) });
}

/** Round avatar: person picture, else initials; dashed circle when unassigned. */
export function avatar(index, entityId, size = "md") {
  if (!entityId) {
    return h(`span.avatar.${size}.empty`, { title: t("unassigned") }, icon("mdi:account-outline"));
  }
  const person = index?.peopleById.get(entityId);
  const name = personName(index, entityId);
  return h(
    `span.avatar.${size}`,
    { title: name, style: { background: person?.picture ? "transparent" : avatarColor(entityId) } },
    person?.picture ? h("img", { src: person.picture, alt: name, loading: "lazy" }) : initials(name),
  );
}

export function labelChip(label, { onRemove } = {}) {
  return h(
    "span.label-chip",
    { key: label, style: { "--label-color": labelColor(label) } },
    label,
    onRemove
      ? h("button.chip-x", { type: "button", "aria-label": t("remove_label", { label }), onclick: () => onRemove(label) }, icon("mdi:close"))
      : null,
  );
}

export function dueChip(issue, now) {
  if (!issue.due) return null;
  const state = issue.overdue ? "overdue" : issue.due_soon ? "soon" : "";
  return h(
    `span.chip.due`,
    { class: state, title: `${t("field.due")}: ${issue.due}` },
    icon(issue.overdue ? "mdi:calendar-alert" : "mdi:calendar-outline"),
    formatDue(issue.due, { now }),
  );
}

/** "3/5" chip for an issue with a checklist. */
export function checklistChip(issue) {
  const progress = issueChecklist(issue);
  if (!progress) return null;
  return h(
    "span.chip.plain.checklist",
    { class: progress.done === progress.total ? "complete" : "", title: t("checklist.chip_title", progress) },
    icon("mdi:format-list-checks"),
    `${progress.done}/${progress.total}`,
  );
}

export function attachmentChip(issue) {
  if (!issue.attachment_count) return null;
  return h("span.chip.plain", { title: tn("attachments.chip_title", issue.attachment_count) }, icon("mdi:paperclip"), issue.attachment_count);
}

/** Progress bar over the child issues of an epic. */
export function epicBar(issue) {
  const progress = epicProgress(issue);
  if (!progress) return null;
  return h("div.epic-progress", progressBar(progress.percent, t("epic.progress", progress)), h("span.muted.small", `${progress.done}/${progress.total}`));
}

export function autoChip() {
  return h("span.chip.auto", { title: t("auto.title") }, icon("mdi:robot-outline"), t("auto.chip"));
}

/** Thin progress bar (checklists, epics). `label` is the accessible text. */
export function progressBar(percent, label) {
  return h(
    "div.progress",
    { role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(percent), "aria-label": label, title: label },
    h("span.progress-fill", { style: { width: `${percent}%` }, class: percent === 100 ? "complete" : "" }),
  );
}

export function spinner(label) {
  return h("span.spinner", { role: "status", "aria-label": label });
}

export function emptyState(iconName, title, text, action) {
  return h("div.empty-state", icon(iconName), h("strong", title), text ? h("span", text) : null, action || null);
}

/** Native <select> (stable across HA versions) wrapped with a label. */
export function selectField({ label, value, options, onchange, id, disabled = false, autofocus = false, wide = false }) {
  return h(
    "label.field",
    { key: id || label, class: wide ? "wide" : "" },
    h("span.field-label", label),
    h(
      "select.input",
      { value: value ?? "", disabled, onchange: (e) => onchange(e.target.value), "data-autofocus": autofocus ? "" : null },
      options.map((o) => h("option", { key: o.value, value: o.value }, o.label)),
    ),
  );
}

export function textField({ label, value, onchange, oninput, type = "text", placeholder = "", id, attrs = {} }) {
  return h(
    "label.field",
    { key: id || label },
    h("span.field-label", label),
    h("input.input", { type, value: value ?? "", placeholder, onchange: onchange && ((e) => onchange(e.target.value)), oninput: oninput && ((e) => oninput(e.target.value)), ...attrs }),
  );
}

export function checkboxField({ label, checked, onchange, id }) {
  return h(
    "label.check",
    { key: id || label },
    h("input", { type: "checkbox", checked, onchange: (e) => onchange(e.target.checked) }),
    h("span", label),
  );
}

export function personOptions(index, { none = t("unassigned") } = {}) {
  return [{ value: "", label: none }, ...(index?.peopleById ? [...index.peopleById.values()].map((p) => ({ value: p.entity_id, label: p.name })) : [])];
}

export function typeOptions() {
  return ["task", "bug", "story", "epic"].map((v) => ({ value: v, label: t(`type.${v}`) }));
}

export function priorityOptions() {
  return ["highest", "high", "medium", "low", "lowest"].map((v) => ({ value: v, label: t(`priority.${v}`) }));
}
