// Helpers for the Insights tab (PROTOCOL 10.5). Pure.

import { getLocale, t } from "./i18n.js";
import { personName } from "./indexes.js";
import { clamp } from "./util.js";

export const FEATURES = ["defaults", "patterns", "workload", "health", "rhythm"];

/** Features whose learned data is shown (patterns only produces suggestions). */
export const LEARNED_FEATURES = ["defaults", "workload", "rhythm", "health"];

export function enabledFeatures(learning) {
  return FEATURES.filter((feature) => learning?.[feature]);
}

export function learningEnabled(settings) {
  return enabledFeatures(settings?.learning).length > 0;
}

/** Heat-map cell intensity 0..100 for a presence value 0..1. */
export function heatPercent(value) {
  return Math.round(clamp(Number(value) || 0, 0, 1) * 100);
}

export function evidenceText(kind, evidence = {}) {
  if (kind === "recurring" && evidence.count) {
    return evidence.interval_days
      ? t("insights.evidence_recurring", { count: evidence.count, days: Math.round(evidence.interval_days) })
      : t("insights.evidence_count", { count: evidence.count });
  }
  if (kind === "health_ignore" && evidence.reopened) return t("insights.evidence_reopened", { count: evidence.reopened });
  if (kind === "digest_time" && evidence.samples) return t("insights.evidence_samples", { count: evidence.samples });
  return Object.entries(evidence)
    .map(([key, value]) => `${key.replace(/_/g, " ")}: ${value}`)
    .join(", ");
}

/** Bars scaled to the largest value: [{ ...entry, percent }]. */
export function scaleBars(entries, value = (entry) => entry.value) {
  const max = Math.max(0, ...entries.map(value));
  return entries.map((entry) => ({ ...entry, percent: max ? Math.round((value(entry) / max) * 100) : 0 }));
}

/** Rows for the workload table, in people order: { id, name, open, done30d, avgDays }. */
export function workloadRows(workload, index) {
  return Object.entries(workload?.people || {})
    .map(([id, stats]) => ({ id, name: personName(index, id), open: stats.open ?? 0, done30d: stats.done_30d ?? 0, avgDays: stats.avg_days ?? null }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

/** { name, value, percent } sorted by value descending, for per-type / per-label averages. */
export function averageBars(averages) {
  return scaleBars(
    Object.entries(averages || {})
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value),
  );
}

export function topLabelBars(defaults) {
  return scaleBars((defaults?.top_labels || []).map(([name, value]) => ({ name, value })));
}

export function personIssueBars(defaults, index) {
  return scaleBars((defaults?.people || []).map((p) => ({ id: p.person, name: personName(index, p.person), value: p.issues })));
}

/** 7 rows (Mon first) of 24 values; tolerates missing rows / cells. */
export function normaliseGrid(grid) {
  return Array.from({ length: 7 }, (_, day) => Array.from({ length: 24 }, (_, hour) => Number(grid?.[day]?.[hour]) || 0));
}

export function formatDays(days, locale = getLocale()) {
  if (days == null) return "-";
  return new Intl.NumberFormat(locale, { style: "unit", unit: "day", unitDisplay: "short", maximumFractionDigits: 1 }).format(days);
}

export function formatMinutes(minutes, locale = getLocale()) {
  const [value, unit] = minutes >= 1440 ? [minutes / 1440, "day"] : minutes >= 60 ? [minutes / 60, "hour"] : [minutes, "minute"];
  return new Intl.NumberFormat(locale, { style: "unit", unit, unitDisplay: "short", maximumFractionDigits: 1 }).format(value);
}
