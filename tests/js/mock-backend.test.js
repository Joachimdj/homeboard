// The harness backend must follow PROTOCOL.md closely, otherwise eyeballing the UI proves little.

import assert from "node:assert/strict";
import { test } from "node:test";
import { makeBackend } from "./fixtures.js";

const run = (backend, command, params = {}) => backend.handle({ type: `homeboard/${command}`, ...params });
const codeOf = (fn) => {
  try {
    fn();
  } catch (error) {
    return error.code;
  }
  return null;
};

function home(backend) {
  return [...backend.projects.values()].find((p) => p.key === "HOME");
}

test("seed data: two projects, two people, recurring chores, health issues", () => {
  const payload = makeBackend().payload();
  assert.equal(payload.projects.length, 2);
  assert.equal(payload.people.length, 2);
  assert.ok(payload.recurring.length >= 3);
  assert.equal(payload.settings.health_enabled, true);
  assert.equal(payload.issues.filter((i) => i.source === "health").length, 6);
  assert.ok(payload.issues.length >= 25);
  assert.ok(payload.issues.every((i) => !("comments" in i) && !("activity" in i) && typeof i.comment_count === "number"));
  assert.ok(payload.issues.some((i) => i.overdue) && payload.issues.some((i) => i.due_soon));
  assert.ok(payload.issues.some((i) => i.type === "epic") && payload.issues.some((i) => i.type === "bug"));
  assert.equal(payload.stats.total.health_open, 6);
});

test("issue/create allocates numbers, ranks at the end and takes issue_type", () => {
  const backend = makeBackend();
  const project = home(backend);
  const todo = project.statuses.find((s) => s.name === "To do").id;
  const last = backend.column(project.id, todo).at(-1);
  const issue = run(backend, "issue/create", { project_id: project.id, summary: "  New one ", issue_type: "bug", status: todo, labels: ["#Garden", "garden"] });
  assert.equal(issue.key, `HOME-${project.issue_seq}`);
  assert.equal(issue.type, "bug");
  assert.equal(issue.summary, "New one");
  assert.deepEqual(issue.labels, ["garden"]);
  assert.equal(issue.rank, last.rank + 1000);
  assert.equal(codeOf(() => run(backend, "issue/create", { project_id: project.id, summary: " " })), "invalid_format");
  assert.equal(codeOf(() => run(backend, "issue/create", { project_id: "nope", summary: "x" })), "not_found");
});

test("issue/move: `before` insertion, end of column, gap rebalancing, completion events", () => {
  const backend = makeBackend();
  const project = home(backend);
  const status = (name) => project.statuses.find((s) => s.name === name).id;
  const moving = [...backend.issues.values()].find((i) => i.key === "HOME-7");
  const target = backend.column(project.id, status("In progress"));

  run(backend, "issue/move", { issue_id: moving.id, status: status("In progress"), before: target[1].id });
  const order = backend.column(project.id, status("In progress")).map((i) => i.id);
  assert.equal(order.indexOf(moving.id), order.indexOf(target[1].id) - 1);

  run(backend, "issue/move", { issue_id: moving.id, status: status("In progress"), before: null });
  assert.equal(backend.column(project.id, status("In progress")).at(-1).id, moving.id);

  run(backend, "issue/move", { issue_id: moving.id, status: status("Done") });
  assert.ok(backend.issues.get(moving.id).resolved);
  assert.ok(backend.issues.get(moving.id).activity.some((a) => a.kind === "completed"));
  run(backend, "issue/move", { issue_id: moving.id, status: status("To do") });
  assert.equal(backend.issues.get(moving.id).resolved, null);
  assert.ok(backend.issues.get(moving.id).activity.some((a) => a.kind === "reopened"));

  // tight ranks are rebalanced instead of colliding
  const [a, b, c] = backend.column(project.id, status("To do"));
  a.rank = 10;
  b.rank = 11;
  run(backend, "issue/move", { issue_id: c.id, status: status("To do"), before: b.id });
  const ranks = backend.column(project.id, status("To do")).map((i) => i.rank);
  assert.deepEqual(ranks, [...ranks].sort((x, y) => x - y));
  assert.equal(new Set(ranks).size, ranks.length);

  assert.equal(codeOf(() => run(backend, "issue/move", { issue_id: moving.id, status: "nope" })), "not_found");
  assert.equal(codeOf(() => run(backend, "issue/move", { issue_id: moving.id, status: status("Done"), before: moving.id })), "invalid_format");
});

test("issue/get returns comments and activity; comment and update write the log", () => {
  const backend = makeBackend();
  const issue = [...backend.issues.values()].find((i) => i.key === "HOME-9");
  assert.equal(run(backend, "issue/get", { issue_id: issue.id }).comments.length, 2);
  run(backend, "issue/comment", { issue_id: issue.id, text: "Hello" });
  run(backend, "issue/update", { issue_id: issue.id, priority: "low", assignee: "person.padmaja", due: null });
  const full = run(backend, "issue/get", { issue_id: issue.id });
  assert.equal(full.comments.at(-1).text, "Hello");
  assert.equal(full.priority, "low");
  assert.equal(full.due, null);
  assert.deepEqual(full.activity.slice(-4).map((a) => a.kind), ["commented", "updated", "assigned", "updated"]);
  assert.equal(codeOf(() => run(backend, "issue/comment", { issue_id: issue.id, text: "" })), "invalid_format");
});

test("issue/update: type is issue_type, archive hides from the payload, parent must be an epic", () => {
  const backend = makeBackend();
  const issue = [...backend.issues.values()].find((i) => i.key === "HOME-9");
  const epic = [...backend.issues.values()].find((i) => i.type === "epic");
  assert.equal(run(backend, "issue/update", { issue_id: issue.id, issue_type: "story" }).type, "story");
  assert.equal(codeOf(() => run(backend, "issue/update", { issue_id: issue.id, issue_type: "nope" })), "invalid_format");
  assert.equal(run(backend, "issue/update", { issue_id: issue.id, parent: epic.id }).parent, epic.id);
  assert.equal(codeOf(() => run(backend, "issue/update", { issue_id: issue.id, parent: issue.id })), "invalid_format");
  run(backend, "issue/update", { issue_id: issue.id, archived: true });
  assert.ok(!backend.payload().issues.some((i) => i.id === issue.id));
  assert.equal(run(backend, "issue/list", { archived: true }).total, 1);
});

test("issue/delete, issue/list search and paging", () => {
  const backend = makeBackend();
  const issue = [...backend.issues.values()].find((i) => i.key === "HOME-9");
  const found = run(backend, "issue/list", { query: "latch" });
  assert.equal(found.total, 1);
  assert.equal(run(backend, "issue/list", { limit: 5, offset: 2 }).issues.length, 5);
  run(backend, "issue/delete", { issue_id: issue.id });
  assert.equal(codeOf(() => run(backend, "issue/get", { issue_id: issue.id })), "not_found");
});

test("project and status administration", () => {
  const backend = makeBackend();
  const created = run(backend, "project/create", { key: "TRIP", name: "Trip", template: "software" });
  assert.equal(created.statuses.length, 5);
  assert.equal(codeOf(() => run(backend, "project/create", { key: "TRIP", name: "Again" })), "conflict");
  assert.equal(codeOf(() => run(backend, "project/create", { key: "x", name: "Bad" })), "invalid_format");
  assert.equal(run(backend, "project/update", { project_id: created.id, name: "Holiday", color: "#ff0000", labels: ["Sun"] }).labels[0], "sun");

  const status = run(backend, "status/create", { project_id: created.id, name: "Waiting", category: "in_progress", wip: 2, position: 1 });
  assert.equal(backend.projects.get(created.id).statuses[1].id, status.id);
  assert.equal(run(backend, "status/update", { project_id: created.id, status_id: status.id, name: "Parked", wip: null }).wip, null);
  const ids = backend.projects.get(created.id).statuses.map((s) => s.id).reverse();
  assert.deepEqual(run(backend, "status/reorder", { project_id: created.id, status_ids: ids }), { ok: true });
  assert.equal(codeOf(() => run(backend, "status/reorder", { project_id: created.id, status_ids: ids.slice(1) })), "invalid_format");

  const hm = home(backend);
  const todo = hm.statuses.find((s) => s.name === "To do").id;
  const progress = hm.statuses.find((s) => s.name === "In progress").id;
  assert.equal(codeOf(() => run(backend, "status/delete", { project_id: hm.id, status_id: todo })), "invalid_format");
  const moved = backend.column(hm.id, todo).length;
  run(backend, "status/delete", { project_id: hm.id, status_id: todo, move_to: progress });
  assert.equal(backend.column(hm.id, progress).length >= moved, true);
  assert.equal(codeOf(() => run(backend, "project/delete", { project_id: created.id })), "invalid_format");
  assert.deepEqual(run(backend, "project/delete", { project_id: created.id, confirm: true }), { deleted: created.id });
});

test("non-admins get `unauthorized` for project, status and health commands only", () => {
  const backend = makeBackend();
  backend.setUser({ is_admin: false });
  const project = home(backend);
  assert.equal(backend.payload().is_admin, false);
  for (const [command, params] of [
    ["project/create", { key: "ABC", name: "x" }],
    ["project/update", { project_id: project.id, name: "x" }],
    ["project/delete", { project_id: project.id, confirm: true }],
    ["status/create", { project_id: project.id, name: "x", category: "todo" }],
    ["status/update", { project_id: project.id, status_id: project.statuses[0].id, name: "x" }],
    ["status/reorder", { project_id: project.id, status_ids: [] }],
    ["status/delete", { project_id: project.id, status_id: project.statuses[0].id }],
    ["health/scan", {}],
  ]) assert.equal(codeOf(() => run(backend, command, params)), "unauthorized", command);
  assert.ok(run(backend, "issue/create", { project_id: project.id, summary: "Allowed" }));
  assert.ok(run(backend, "recurring/run_now", { recurring_id: [...backend.recurring.keys()][0] }));
});

test("recurring CRUD and run_now", () => {
  const backend = makeBackend();
  const project = home(backend);
  const fields = { summary: "Check smoke alarms", issue_type: "task", priority: "high", labels: ["safety"], repeat: { every: 2, unit: "week", weekdays: [0] }, next_due: "2026-11-23", skip_if_open: true };
  const created = run(backend, "recurring/create", { project_id: project.id, ...fields });
  assert.equal(created.type, "task");
  assert.equal(codeOf(() => run(backend, "recurring/create", { project_id: project.id, ...fields, repeat: { every: 0, unit: "week" } })), "invalid_format");

  const first = run(backend, "recurring/run_now", { recurring_id: created.id });
  assert.equal(first.issue.source, "recurring");
  assert.equal(first.issue.recurring_id, created.id);
  assert.equal(first.issue.due, "2026-11-23");
  assert.equal(backend.recurring.get(created.id).next_due, "2026-12-07");
  assert.deepEqual(run(backend, "recurring/run_now", { recurring_id: created.id }), { issue: null }, "skipped while the previous one is open");

  const updated = run(backend, "recurring/update", { recurring_id: created.id, issue_type: "bug", enabled: false });
  assert.equal(updated.type, "bug");
  assert.equal(updated.enabled, false);
  assert.equal(updated.summary, "Check smoke alarms");
  assert.deepEqual(run(backend, "recurring/delete", { recurring_id: created.id }), { deleted: created.id });
  assert.equal(codeOf(() => run(backend, "recurring/delete", { recurring_id: created.id })), "not_found");
});

test("quick_add and quick_add/preview", () => {
  const backend = makeBackend();
  const before = backend.issues.size;
  const preview = run(backend, "quick_add/preview", { text: "bug: Fix door @padmaja !high #house due tomorrow" });
  assert.equal(preview.project, "HOME");
  assert.equal(preview.assignee, "person.padmaja");
  assert.equal(backend.issues.size, before, "preview writes nothing");
  const { issue, parsed } = run(backend, "quick_add", { text: "FIX: Replace battery !low", project: "HOME" });
  assert.equal(issue.key.startsWith("FIX-"), true);
  assert.equal(parsed.priority, "low");
  assert.equal(codeOf(() => run(backend, "quick_add", { text: "#only #labels" })), "invalid_format");
  assert.equal(codeOf(() => run(backend, "nonsense")), "not_found");
});

test("subscribers get the full payload after every change", () => {
  const backend = makeBackend();
  const seen = [];
  const stop = backend.subscribe((payload) => seen.push(payload.issues.length));
  const project = home(backend);
  const base = backend.payload().issues.length;
  run(backend, "issue/create", { project_id: project.id, summary: "One" });
  run(backend, "issue/create", { project_id: project.id, summary: "Two" });
  stop();
  run(backend, "issue/create", { project_id: project.id, summary: "Three" });
  assert.deepEqual(seen, [base + 1, base + 2]);
});
