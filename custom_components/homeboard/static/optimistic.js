// Pure payload transforms used for optimistic updates. Each returns a new
// payload and never mutates its input; the store replays them on top of the
// last pushed payload until the server confirms.

import { compareIssues } from "./indexes.js";
import { rankForInsert } from "./ranks.js";

function withIssues(payload, issues) {
  return { ...payload, issues };
}

export function patchIssue(payload, issueId, patch) {
  return withIssues(
    payload,
    payload.issues.map((issue) => (issue.id === issueId ? { ...issue, ...patch } : issue)),
  );
}

export function removeIssue(payload, issueId) {
  return withIssues(payload, payload.issues.filter((issue) => issue.id !== issueId));
}

export function moveIssue(payload, issueId, status, before) {
  const moving = payload.issues.find((issue) => issue.id === issueId);
  if (!moving) return payload;
  const siblings = payload.issues
    .filter((i) => i.project_id === moving.project_id && i.status === status && i.id !== issueId)
    .sort(compareIssues);
  const rank = rankForInsert(siblings, before ?? null);
  return patchIssue(payload, issueId, { status, rank });
}

function patchProject(payload, projectId, patch) {
  return {
    ...payload,
    projects: payload.projects.map((p) => (p.id === projectId ? { ...p, ...patch } : p)),
  };
}

export function reorderStatuses(payload, projectId, statusIds) {
  const project = payload.projects.find((p) => p.id === projectId);
  if (!project) return payload;
  const byId = new Map(project.statuses.map((s) => [s.id, s]));
  const statuses = statusIds.map((id) => byId.get(id)).filter(Boolean);
  return patchProject(payload, projectId, { statuses });
}
