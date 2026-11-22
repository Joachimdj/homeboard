// What a board / backlog shows: visible statuses, filtered issues, swimlanes. Pure.

import { filterIssues, groupLanes } from "./filters.js";
import { groupByStatus } from "./indexes.js";

/**
 * layout: "board" (non-backlog columns, backlog too with showBacklog) or
 * "backlog" (only statuses flagged as backlog, as a list).
 * Returns { statuses, counts, lanes: [{ id, kind, value, issues, byStatus }], total }.
 * `counts` are unfiltered per-status totals (for the WIP badge).
 */
export function boardModel({ index, project, filter, laneMode = "none", layout = "board", showBacklog = false, me = null }) {
  const statuses = project.statuses.filter((s) => (layout === "backlog" ? s.backlog : showBacklog || !s.backlog));
  const visibleIds = new Set(statuses.map((s) => s.id));
  const all = index.byProject.get(project.id) || [];

  const counts = new Map(project.statuses.map((s) => [s.id, 0]));
  for (const issue of all) counts.set(issue.status, (counts.get(issue.status) || 0) + 1);

  const visible = filterIssues(
    all.filter((i) => visibleIds.has(i.status)),
    filter,
    { me, index },
  );
  const rawLanes =
    layout === "board" ? groupLanes(visible, laneMode, { people: [...index.peopleById.values()] }) : [{ id: "all", kind: "all", value: null, issues: visible }];
  const lanes = rawLanes.map((lane) => ({ ...lane, byStatus: groupByStatus(lane.issues) }));
  return { statuses, counts, lanes, total: visible.length };
}
