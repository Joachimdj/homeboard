import assert from "node:assert/strict";
import { test } from "node:test";
import { attentionIssues, barSegments, healthStats, peopleStats, projectStats } from "../../custom_components/homeboard/static/stats.js";
import { NOW, makeState } from "./fixtures.js";

const { payload, index } = makeState();
const home = index.projects.find((p) => p.key === "HOME");

test("projectStats counts per status and open / overdue / due soon / unassigned", () => {
  const stats = projectStats(payload, index, home, NOW.getTime());
  assert.deepEqual(stats.byStatus.map((s) => [s.status.name, s.count]), [["Backlog", 5], ["To do", 7], ["In progress", 5], ["Done", 9]]);
  assert.equal(stats.open, 17);
  assert.equal(stats.overdue, 2);
  assert.ok(stats.dueSoon >= 2);
  assert.equal(stats.unassigned, 7);
  assert.equal(stats.done7d, 4); // the 12-day-old one does not count
  assert.ok(stats.lastActivity);
});

test("local counts agree with the server stats of the payload", () => {
  const server = payload.stats.projects[home.id];
  const stats = projectStats(payload, index, home, NOW.getTime());
  for (const [local, remote] of [["open", "open"], ["overdue", "overdue"], ["dueSoon", "due_soon"], ["unassigned", "unassigned"]]) {
    assert.equal(stats[local], server[remote], local);
  }
});

test("done7d falls back to resolved timestamps when the server omits stats", () => {
  const bare = { ...payload, stats: undefined };
  assert.equal(projectStats(bare, index, home, NOW.getTime()).done7d, 4);
});

test("barSegments skips empty statuses and shades repeats of a category", () => {
  const segments = barSegments(projectStats(payload, index, home, NOW.getTime()));
  assert.equal(segments.length, 4);
  assert.ok(Math.abs(segments.reduce((n, s) => n + s.percent, 0) - 100) < 1e-9);
  assert.deepEqual(segments.map((s) => s.shade), [0, 1, 0, 0]); // Backlog and To do are both "todo"

  const empty = { byStatus: [{ status: { id: "a", category: "todo" }, count: 0 }] };
  assert.deepEqual(barSegments(empty), []);
});

test("peopleStats: one row per person plus unassigned, in that order", () => {
  const rows = peopleStats(payload, index, NOW.getTime());
  assert.deepEqual(rows.map((r) => r.id), ["person.joachim", "person.padmaja", "unassigned"]);
  const joachim = rows[0];
  assert.ok(joachim.open > 0 && joachim.inProgress > 0);
  assert.equal(rows.reduce((n, r) => n + r.open, 0), index.issues.filter((i) => index.statusById.get(i.status).status.category !== "done").length);
  assert.equal(rows[2].name, null);
});

test("peopleStats adds rows for assignees missing from the people list", () => {
  const ghost = { ...payload, issues: payload.issues.map((i, n) => (n === 0 ? { ...i, assignee: "person.ghost" } : i)) };
  const rows = peopleStats(ghost, { ...index, issues: ghost.issues }, NOW.getTime());
  assert.ok(rows.some((r) => r.id === "person.ghost" && r.name === "Ghost"));
});

test("attentionIssues returns open overdue and due soon issues, soonest first", () => {
  const { overdue, dueSoon } = attentionIssues(index);
  assert.deepEqual(overdue.map((i) => i.key), ["HOME-7", "HOME-15"]);
  assert.ok(dueSoon.length >= 2);
  assert.ok(dueSoon.every((i) => !i.overdue));
  assert.ok(dueSoon.every((issue, n, list) => !n || list[n - 1].due <= issue.due));
  assert.deepEqual(attentionIssues(index, ["nope"]).overdue, []);
});

test("healthStats counts open auto issues, high priority and security labelled", () => {
  const health = healthStats(payload, index);
  assert.equal(health.open, 6);
  assert.equal(health.open, payload.stats.total.health_open);
  assert.equal(health.high, 2);
  assert.equal(health.security, 2);
  assert.equal(health.projectIds.length, 1);
});
