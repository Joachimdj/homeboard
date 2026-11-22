// Derived lookups over the pushed payload. Pure, rebuilt after every push.

import { nameFromEntityId } from "./util.js";

export function compareIssues(a, b) {
  return a.rank - b.rank || a.number - b.number;
}

export function buildIndex(payload) {
  const projects = payload?.projects || [];
  const issues = payload?.issues || [];
  const people = payload?.people || [];

  const projectById = new Map(projects.map((p) => [p.id, p]));
  const projectByKey = new Map(projects.map((p) => [p.key, p]));
  const peopleById = new Map(people.map((p) => [p.entity_id, p]));
  const issueById = new Map();
  const issueByKey = new Map();
  const byProject = new Map(projects.map((p) => [p.id, []]));
  const children = new Map();
  const statusById = new Map();

  for (const project of projects) {
    for (const status of project.statuses || []) statusById.set(status.id, { status, project });
  }
  for (const issue of issues) {
    issueById.set(issue.id, issue);
    issueByKey.set(issue.key, issue);
    if (!byProject.has(issue.project_id)) byProject.set(issue.project_id, []);
    byProject.get(issue.project_id).push(issue);
    if (issue.parent) {
      if (!children.has(issue.parent)) children.set(issue.parent, []);
      children.get(issue.parent).push(issue);
    }
  }
  for (const list of byProject.values()) list.sort(compareIssues);
  for (const list of children.values()) list.sort(compareIssues);

  return { projects, projectById, projectByKey, peopleById, issues, issueById, issueByKey, byProject, children, statusById };
}

/** Issues of one project grouped by status id, each list sorted by rank. */
export function groupByStatus(issues) {
  const groups = new Map();
  for (const issue of issues) {
    if (!groups.has(issue.status)) groups.set(issue.status, []);
    groups.get(issue.status).push(issue);
  }
  return groups;
}

export function categoryOf(index, issue) {
  return index.statusById.get(issue.status)?.status.category || "todo";
}

export function isOpen(index, issue) {
  return categoryOf(index, issue) !== "done";
}

export function statusName(index, statusId) {
  return index.statusById.get(statusId)?.status.name || "";
}

export function personName(index, entityId) {
  if (!entityId) return "";
  return index.peopleById.get(entityId)?.name || nameFromEntityId(entityId);
}

/** Project by id or key, used for server answers that may carry either. */
export function findProject(index, idOrKey) {
  if (!idOrKey) return null;
  return index.projectById.get(idOrKey) || index.projectByKey.get(String(idOrKey).toUpperCase()) || null;
}

function firstStatus(project, predicate) {
  return (project?.statuses || []).find(predicate) || null;
}

/** Default landing status of a new issue: first non-backlog "todo" column. */
export function defaultStatus(project) {
  return (
    firstStatus(project, (s) => s.category === "todo" && !s.backlog) ||
    firstStatus(project, (s) => !s.backlog) ||
    project?.statuses?.[0] ||
    null
  );
}
