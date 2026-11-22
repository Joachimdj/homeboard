// Numbers for the status overview. Counts are derived from the (optimistically
// patched) issues so a drag shows up instantly; `done_7d` and `last_activity`
// come from the server stats because archived issues are not in the payload.

import { categoryOf, compareIssues, isOpen, personName } from "./indexes.js";

const WEEK_MS = 7 * 86400000;

function maxIso(values) {
  let best = null;
  for (const value of values) if (value && (!best || value > best)) best = value;
  return best;
}

function doneInLastWeek(issues, index, now) {
  return issues.filter((i) => categoryOf(index, i) === "done" && i.resolved && now - new Date(i.resolved).getTime() <= WEEK_MS).length;
}

export function projectStats(payload, index, project, now = Date.now()) {
  const issues = index.byProject.get(project.id) || [];
  const server = payload.stats?.projects?.[project.id] || {};
  const byStatus = project.statuses.map((status) => ({
    status,
    count: issues.filter((i) => i.status === status.id).length,
  }));
  const open = issues.filter((i) => isOpen(index, i));
  return {
    project,
    total: issues.length,
    open: open.length,
    overdue: open.filter((i) => i.overdue).length,
    dueSoon: open.filter((i) => i.due_soon).length,
    unassigned: open.filter((i) => !i.assignee).length,
    done7d: server.done_7d ?? doneInLastWeek(issues, index, now),
    lastActivity: server.last_activity ?? maxIso(issues.map((i) => i.updated)),
    byStatus,
  };
}

/**
 * Stacked-bar segments for a project: one per status with at least one issue.
 * `shade` (0..n) distinguishes several statuses of the same category.
 */
export function barSegments(stats) {
  const total = stats.byStatus.reduce((sum, s) => sum + s.count, 0);
  const seen = {};
  const segments = [];
  for (const { status, count } of stats.byStatus) {
    const shade = seen[status.category] || 0;
    seen[status.category] = shade + 1;
    if (!count) continue;
    segments.push({ status, count, shade, percent: total ? (count / total) * 100 : 0 });
  }
  return segments;
}

/** One row per person (plus "unassigned") with open / overdue / in progress / done 7d. */
export function peopleStats(payload, index, now = Date.now()) {
  const rows = (payload.people || []).map((person) => ({
    id: person.entity_id,
    name: person.name,
    picture: person.picture || null,
  }));
  const known = new Set(rows.map((r) => r.id));
  for (const issue of index.issues) {
    if (issue.assignee && !known.has(issue.assignee)) {
      known.add(issue.assignee);
      rows.push({ id: issue.assignee, name: personName(index, issue.assignee), picture: null });
    }
  }
  rows.push({ id: "unassigned", name: null, picture: null });

  return rows.map((row) => {
    const mine = index.issues.filter((i) => (row.id === "unassigned" ? !i.assignee : i.assignee === row.id));
    const open = mine.filter((i) => isOpen(index, i));
    const server = payload.stats?.people?.[row.id] || {};
    return {
      ...row,
      open: open.length,
      overdue: open.filter((i) => i.overdue).length,
      inProgress: mine.filter((i) => categoryOf(index, i) === "in_progress").length,
      done7d: server.done_7d ?? doneInLastWeek(mine, index, now),
    };
  });
}

function dueTime(issue) {
  return issue.due ? new Date(issue.due.length === 10 ? `${issue.due}T00:00:00` : issue.due).getTime() : Infinity;
}

/** Open overdue / due-soon issues across all (non archived) projects, soonest first. */
export function attentionIssues(index, projectIds = null) {
  const visible = (issue) =>
    isOpen(index, issue) && !index.projectById.get(issue.project_id)?.archived && (!projectIds || projectIds.includes(issue.project_id));
  const byDue = (a, b) => dueTime(a) - dueTime(b) || compareIssues(a, b);
  return {
    overdue: index.issues.filter((i) => visible(i) && i.overdue).sort(byDue),
    dueSoon: index.issues.filter((i) => visible(i) && i.due_soon && !i.overdue).sort(byDue),
  };
}

const HIGH_PRIORITIES = new Set(["highest", "high"]);

/** Open auto-generated (home health) issues: total, high priority and security labelled. */
export function healthStats(payload, index) {
  const open = index.issues.filter((i) => i.source === "health" && isOpen(index, i) && !index.projectById.get(i.project_id)?.archived);
  return {
    open: payload.stats?.total?.health_open ?? open.length,
    high: open.filter((i) => HIGH_PRIORITIES.has(i.priority)).length,
    security: open.filter((i) => (i.labels || []).includes("security")).length,
    projectIds: [...new Set(open.map((i) => i.project_id))],
  };
}
