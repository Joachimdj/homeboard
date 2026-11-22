// Recurring chores: form drafts, API params and the "Every 2 weeks on Mon" text. Pure.

import { getLocale, t, tn } from "./i18n.js";
import { todayString } from "./util.js";

export const UNITS = ["day", "week", "month", "year"];

export function weekdayLabel(index, { locale = getLocale(), style = "short" } = {}) {
  // 2024-01-01 was a Monday.
  return new Intl.DateTimeFormat(locale, { weekday: style }).format(new Date(2024, 0, 1 + index));
}

export function repeatSummary(repeat, locale = getLocale()) {
  const every = Math.max(1, Number(repeat?.every) || 1);
  const unit = UNITS.includes(repeat?.unit) ? repeat.unit : "day";
  let text = tn(`repeat.${unit}`, every);
  if (unit === "week" && repeat.weekdays?.length) {
    const days = [...repeat.weekdays].sort((a, b) => a - b).map((d) => weekdayLabel(d, { locale }));
    text += ` ${t("repeat.on_weekdays", { days: days.join(", ") })}`;
  }
  if (unit === "month" && repeat.day_of_month) {
    text += ` ${repeat.day_of_month === -1 ? t("repeat.on_last_day") : t("repeat.on_day", { day: repeat.day_of_month })}`;
  }
  return text;
}

export function emptyRecurring(project, now = new Date()) {
  return {
    summary: "",
    description: "",
    type: "task",
    priority: "medium",
    assignee: project?.default_assignee || "",
    labels: [],
    status: "", // empty = the backend picks the first non-backlog todo status
    enabled: true,
    every: 1,
    unit: "week",
    weekdays: [],
    dayOfMonth: "",
    lastDay: false,
    nextDue: todayString(now),
    createDaysBefore: 0,
    skipIfOpen: true,
  };
}

export function draftFromRecurring(recurring) {
  const repeat = recurring.repeat || {};
  const lastDay = repeat.day_of_month === -1;
  return {
    summary: recurring.summary || "",
    description: recurring.description || "",
    type: recurring.type || "task",
    priority: recurring.priority || "medium",
    assignee: recurring.assignee || "",
    labels: [...(recurring.labels || [])],
    status: recurring.status || "",
    enabled: recurring.enabled !== false,
    every: repeat.every || 1,
    unit: repeat.unit || "week",
    weekdays: [...(repeat.weekdays || [])],
    dayOfMonth: repeat.day_of_month && !lastDay ? String(repeat.day_of_month) : "",
    lastDay,
    nextDue: recurring.next_due || "",
    createDaysBefore: recurring.create_days_before || 0,
    skipIfOpen: recurring.skip_if_open !== false,
  };
}

/** Build the `repeat` object of the protocol from a form draft. */
export function repeatFromDraft(draft) {
  const repeat = { every: Math.max(1, Math.floor(Number(draft.every) || 1)), unit: draft.unit };
  if (draft.unit === "week" && draft.weekdays.length) repeat.weekdays = [...draft.weekdays].sort((a, b) => a - b);
  if (draft.unit === "month") {
    if (draft.lastDay) repeat.day_of_month = -1;
    else if (draft.dayOfMonth !== "" && draft.dayOfMonth != null) repeat.day_of_month = clampDay(draft.dayOfMonth);
  }
  return repeat;
}

function clampDay(value) {
  return Math.min(31, Math.max(1, Math.floor(Number(value) || 1)));
}

/** Returns { error } for an invalid form, else { params } for create / update. */
export function recurringParams(draft) {
  const summary = draft.summary.trim();
  if (!summary) return { error: "recurring.error_summary" };
  if (!draft.nextDue) return { error: "recurring.error_next_due" };
  return {
    params: {
      summary,
      description: draft.description,
      issue_type: draft.type,
      priority: draft.priority,
      assignee: draft.assignee || null,
      labels: draft.labels,
      status: draft.status || null,
      enabled: draft.enabled,
      repeat: repeatFromDraft(draft),
      next_due: draft.nextDue,
      create_days_before: Math.max(0, Math.floor(Number(draft.createDaysBefore) || 0)),
      skip_if_open: draft.skipIfOpen,
    },
  };
}
