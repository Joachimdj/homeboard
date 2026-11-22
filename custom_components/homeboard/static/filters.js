// Quick filters and swimlane grouping. Pure functions over payload issues.

import { PRIORITIES } from "./util.js";
import { personName } from "./indexes.js";

export const LANE_MODES = ["none", "assignee", "priority"];

export const EMPTY_FILTER = Object.freeze({
  mine: false,
  unassigned: false,
  overdue: false,
  dueSoon: false,
  auto: false, // issues created by the home-health scanner (source "health")
  label: "",
  type: "",
  priority: "",
  assignee: "", // person entity id, "me" or "unassigned"; set by summary click-through and card config
  text: "",
});

const BOOLEAN_KEYS = ["mine", "unassigned", "overdue", "dueSoon", "auto"];
const STRING_KEYS = ["label", "type", "priority", "assignee", "text"];
const SHORTHAND = { mine: "mine", me: "mine", unassigned: "unassigned", overdue: "overdue", due_soon: "dueSoon", duesoon: "dueSoon", auto: "auto", health: "auto" };

/**
 * Accepts the editor/card-config forms: an object (snake or camel case), a
 * comma separated shorthand ("mine,overdue") or nothing.
 */
export function normaliseFilter(raw) {
  const filter = { ...EMPTY_FILTER };
  if (!raw) return filter;
  if (typeof raw === "string") {
    for (const word of raw.split(",").map((w) => w.trim().toLowerCase()).filter(Boolean)) {
      if (SHORTHAND[word]) filter[SHORTHAND[word]] = true;
    }
    return filter;
  }
  if (typeof raw !== "object") return filter;
  for (const key of BOOLEAN_KEYS) {
    const snake = key === "dueSoon" ? "due_soon" : key;
    filter[key] = Boolean(raw[key] ?? raw[snake]);
  }
  for (const key of STRING_KEYS) filter[key] = String(raw[key] ?? "").trim();
  return filter;
}

export function isFilterActive(filter) {
  return (
    BOOLEAN_KEYS.some((key) => filter[key]) || STRING_KEYS.some((key) => String(filter[key] || "").trim() !== "")
  );
}

function assigneeMatches(issue, wanted, me) {
  if (wanted === "unassigned") return !issue.assignee;
  if (wanted === "me") return Boolean(me) && issue.assignee === me;
  return issue.assignee === wanted;
}

/** ctx: { me, index } (index only needed for matching on assignee names). */
export function matchesFilter(issue, filter, ctx = {}) {
  if (filter.mine && !(ctx.me && issue.assignee === ctx.me)) return false;
  if (filter.unassigned && issue.assignee) return false;
  if (filter.overdue && !issue.overdue) return false;
  if (filter.dueSoon && !issue.due_soon) return false;
  if (filter.auto && issue.source !== "health") return false;
  if (filter.label && !(issue.labels || []).includes(filter.label)) return false;
  if (filter.type && issue.type !== filter.type) return false;
  if (filter.priority && issue.priority !== filter.priority) return false;
  if (filter.assignee && !assigneeMatches(issue, filter.assignee, ctx.me)) return false;
  const text = filter.text.trim().toLowerCase();
  if (text) {
    const haystack = [
      issue.key,
      issue.summary,
      issue.description,
      ...(issue.labels || []),
      ctx.index && issue.assignee ? personName(ctx.index, issue.assignee) : "",
    ]
      .join("\n")
      .toLowerCase();
    if (!text.split(/\s+/).every((word) => haystack.includes(word))) return false;
  }
  return true;
}

export function filterIssues(issues, filter, ctx) {
  return isFilterActive(filter) ? issues.filter((issue) => matchesFilter(issue, filter, ctx)) : issues;
}

/**
 * Group issues into swimlanes. Returns [{ id, kind, value, issues }] where
 * kind is "all" | "person" | "unassigned" | "priority" and `value` the entity
 * id / priority. Empty lanes are dropped; with no issues at all a single empty
 * "all" lane is returned so the columns can still receive drops.
 */
export function groupLanes(issues, mode, { people = [] } = {}) {
  const all = [{ id: "all", kind: "all", value: null, issues }];
  if (mode === "assignee") {
    const buckets = new Map(people.map((p) => [p.entity_id, []]));
    const unassigned = [];
    for (const issue of issues) {
      if (!issue.assignee) unassigned.push(issue);
      else {
        if (!buckets.has(issue.assignee)) buckets.set(issue.assignee, []);
        buckets.get(issue.assignee).push(issue);
      }
    }
    const lanes = [...buckets].filter(([, list]) => list.length).map(([id, list]) => ({ id: `person:${id}`, kind: "person", value: id, issues: list }));
    if (unassigned.length) lanes.push({ id: "unassigned", kind: "unassigned", value: null, issues: unassigned });
    return lanes.length ? lanes : all;
  }
  if (mode === "priority") {
    const lanes = PRIORITIES.map((priority) => ({
      id: `priority:${priority}`,
      kind: "priority",
      value: priority,
      issues: issues.filter((issue) => issue.priority === priority),
    })).filter((lane) => lane.issues.length);
    return lanes.length ? lanes : all;
  }
  return all;
}

export const SORT_COLUMNS = ["key", "summary", "status", "priority", "assignee", "due", "updated"];

/** Stable sort for the List tab. `sort` = { by, dir: "asc" | "desc" }; empty values stay last. */
export function sortIssues(issues, sort, index) {
  const project = (issue) => index.projectById.get(issue.project_id);
  const value = {
    key: (i) => i.number,
    summary: (i) => i.summary.toLowerCase(),
    status: (i) => project(i)?.statuses.findIndex((s) => s.id === i.status) ?? 0,
    priority: (i) => PRIORITIES.indexOf(i.priority),
    assignee: (i) => (i.assignee ? personName(index, i.assignee).toLowerCase() : null),
    due: (i) => i.due || null,
    updated: (i) => i.updated || null,
  }[sort.by];
  if (!value) return issues;
  const direction = sort.dir === "desc" ? -1 : 1;
  return issues
    .map((issue, position) => ({ issue, position, v: value(issue) }))
    .sort((a, b) => {
      if (a.v == null || b.v == null) return a.v == null && b.v == null ? a.position - b.position : a.v == null ? 1 : -1;
      return (a.v < b.v ? -1 : a.v > b.v ? 1 : 0) * direction || a.position - b.position;
    })
    .map((entry) => entry.issue);
}
