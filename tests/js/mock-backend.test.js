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

// ---- version 0.2 (PROTOCOL section 10) ---------------------------------------------------------

const issueOf = (backend, key) => [...backend.issues.values()].find((i) => i.key === key);

test("0.2 payload: settings, counters, epic roll-up", () => {
  const payload = makeBackend().payload();
  assert.deepEqual(payload.settings.learning, { defaults: true, patterns: true, workload: true, health: true, rhythm: false });
  assert.deepEqual(payload.settings.attachments, { enabled: true, max_mb: 10 });
  assert.equal(payload.settings.insights_open, 2);
  const beds = payload.issues.find((i) => i.key === "HOME-14");
  assert.equal(beds.checklist_total, 5);
  assert.equal(beds.checklist_done, 3);
  assert.ok(payload.issues.every((i) => !("checklist" in i) && !("attachments" in i)), "items and files are detail only");
  const epic = payload.issues.find((i) => i.type === "epic");
  assert.equal(epic.epic_total, 4);
  assert.equal(epic.epic_done, 1);
  assert.equal("epic_total" in beds, false);
});

test("issue/get has the checklist items and attachments with signed urls", () => {
  const backend = makeBackend();
  const full = run(backend, "issue/get", { issue_id: issueOf(backend, "HOME-9").id });
  assert.equal(full.checklist.length, 2);
  assert.equal(full.attachments.length, 3);
  const [picture, , pdf] = full.attachments;
  assert.match(picture.url, /^blob:/);
  assert.match(picture.thumb_url, /^blob:/);
  assert.notEqual(picture.thumb_url, picture.url);
  assert.equal(pdf.mime, "application/pdf");
  assert.equal(pdf.thumb_url, null);
  assert.equal(picture.source, "upload");
});

test("checklist commands: add, update, remove, reorder, with activity and validation", () => {
  const backend = makeBackend();
  const issue = issueOf(backend, "HOME-12");
  const item = run(backend, "checklist/add", { issue_id: issue.id, text: "  Order a bulb " });
  assert.equal(item.text, "Order a bulb");
  assert.equal(item.done, false);
  const second = run(backend, "checklist/add", { issue_id: issue.id, text: "Fit the bulb" });
  assert.deepEqual(run(backend, "checklist/update", { issue_id: issue.id, item_id: item.id, done: true }), { ...item, done: true });
  assert.equal(run(backend, "checklist/update", { issue_id: issue.id, item_id: second.id, text: "Fit it" }).text, "Fit it");
  assert.equal(backend.payload().issues.find((i) => i.id === issue.id).checklist_done, 1);
  const activity = run(backend, "issue/get", { issue_id: issue.id }).activity;
  assert.ok(activity.some((a) => a.kind === "updated" && a.field === "checklist" && a.from === "0/2" && a.to === "1/2"));

  assert.deepEqual(run(backend, "checklist/reorder", { issue_id: issue.id, item_ids: [second.id, item.id] }), { ok: true });
  assert.deepEqual(run(backend, "issue/get", { issue_id: issue.id }).checklist.map((i) => i.id), [second.id, item.id]);
  assert.equal(codeOf(() => run(backend, "checklist/reorder", { issue_id: issue.id, item_ids: [item.id] })), "invalid_format");

  assert.deepEqual(run(backend, "checklist/remove", { issue_id: issue.id, item_id: item.id }), { deleted: item.id });
  assert.equal(codeOf(() => run(backend, "checklist/remove", { issue_id: issue.id, item_id: item.id })), "not_found");
  assert.equal(codeOf(() => run(backend, "checklist/add", { issue_id: issue.id, text: "   " })), "invalid_format");
  assert.equal(codeOf(() => run(backend, "checklist/add", { issue_id: issue.id, text: "two\nlines" })), "invalid_format");
  assert.equal(codeOf(() => run(backend, "checklist/update", { issue_id: issue.id, item_id: "nope", done: true })), "not_found");
});

test("uploads: type, size and issue checks, then the file shows up on the issue", () => {
  const backend = makeBackend();
  const issue = issueOf(backend, "HOME-12");
  const png = new Uint8Array([137, 80, 78, 71, 1, 2, 3]);
  const upload = (extra = {}) => backend.upload({ issue_id: issue.id, name: "photo.png", mime: "image/png", bytes: png, ...extra });

  const ok = upload();
  assert.equal(ok.status, 200);
  assert.equal(ok.body.name, "photo.png");
  assert.equal(ok.body.size, 7);
  assert.match(ok.body.url, /^blob:/);
  assert.equal(backend.payload().issues.find((i) => i.id === issue.id).attachment_count, 1);

  assert.equal(upload({ mime: "text/plain" }).status, 415);
  assert.equal(upload({ issue_id: "nope" }).status, 404);
  backend.setSettings({ attachments: { max_mb: 0.000005 } });
  assert.equal(upload().status, 413, "7 bytes is above a 5 byte limit");
  backend.setSettings({ attachments: { max_mb: 10, enabled: false } });
  assert.equal(upload().status, 403);
  assert.equal(codeOf(() => run(backend, "attachment/snapshot", { issue_id: issue.id, entity_id: "camera.garden" })), "invalid_format");
});

test("signed urls expire and the next detail fetch signs fresh ones", async () => {
  const backend = makeBackend();
  const id = issueOf(backend, "HOME-9").id;
  const before = run(backend, "issue/get", { issue_id: id }).attachments[0];
  assert.equal((await fetch(before.url)).ok, true);
  backend.files.expire();
  await assert.rejects(fetch(before.url));
  const after = run(backend, "issue/get", { issue_id: id }).attachments[0];
  assert.notEqual(after.url, before.url);
  assert.equal((await fetch(after.url)).ok, true);
});

test("attachment/remove and attachment/snapshot", () => {
  const backend = makeBackend();
  const issue = issueOf(backend, "HOME-12");
  const shot = run(backend, "attachment/snapshot", { issue_id: issue.id, entity_id: "camera.front_door" });
  assert.equal(shot.source, "camera");
  assert.match(shot.name, /^front_door-\d{8}-\d{4}\.png$/);
  assert.equal(shot.mime, "image/png");
  assert.equal(codeOf(() => run(backend, "attachment/snapshot", { issue_id: issue.id, entity_id: "camera.nope" })), "not_found");
  assert.deepEqual(run(backend, "attachment/remove", { issue_id: issue.id, attachment_id: shot.id }), { deleted: shot.id });
  assert.equal(codeOf(() => run(backend, "attachment/remove", { issue_id: issue.id, attachment_id: shot.id })), "not_found");
  assert.equal(backend.files.url(shot.id), null, "the file is gone with the attachment");
});

test("suggest and quick_add: smart defaults from similar past issues", () => {
  const backend = makeBackend();
  const suggestion = run(backend, "suggest", { text: "Pay the internet bill" });
  assert.equal(suggestion.assignee, "person.padmaja");
  assert.deepEqual(suggestion.labels, ["bills"]);
  assert.equal(suggestion.priority, "high");
  assert.ok(suggestion.due_in_days >= 10);
  assert.match(suggestion.evidence, /^based on \d similar issues?$/);
  assert.ok(suggestion.similar.length >= 2 && suggestion.similar.every((s) => s.key && s.summary && s.status));
  assert.ok(suggestion.confidence > 0 && suggestion.confidence <= 1);
  assert.equal(run(backend, "suggest", { text: "Paint the dragon" }), null);
  assert.equal(codeOf(() => run(backend, "suggest", { text: " " })), "invalid_format");

  const preview = run(backend, "quick_add/preview", { text: "Pay the internet bill" });
  assert.equal(preview.suggestion.assignee, "person.padmaja");
  const decided = run(backend, "quick_add/preview", { text: "Pay the internet bill @joachim !low #net due tomorrow" }).suggestion;
  assert.equal(decided, null, "everything the suggestion could fill was set by the text");
  assert.equal(run(backend, "quick_add/preview", { text: "Paint the dragon" }).suggestion, null);

  const plain = run(backend, "quick_add", { text: "Pay the internet bill" }).issue;
  assert.equal(plain.assignee, null);
  const smart = run(backend, "quick_add", { text: "Pay the phone bill", suggest: true }).issue;
  assert.equal(smart.assignee, "person.padmaja");
  assert.deepEqual(smart.labels, ["bills"]);
  assert.equal(smart.priority, "high");
  assert.ok(smart.due);

  backend.setSettings({ learning: { defaults: false } });
  assert.equal(run(backend, "suggest", { text: "Pay the gas bill" }), null);
  assert.equal(run(backend, "quick_add/preview", { text: "Pay the gas bill" }).suggestion, null);
});

test("deleting an issue removes its files", () => {
  const backend = makeBackend();
  const issue = issueOf(backend, "HOME-9");
  const attachment = issue.attachments[0];
  assert.ok(backend.files.url(attachment.id));
  run(backend, "issue/delete", { issue_id: issue.id });
  assert.equal(backend.files.url(attachment.id), null);
});

test("hass.fetchWithAuth emulates POST /api/homeboard/upload with 413 / 415 / 404", async () => {
  const { MockHass } = await import("../browser/mock-hass.js");
  const backend = makeBackend();
  const mock = new MockHass(backend, { latency: 0, uploadDelay: 0 });
  const id = issueOf(backend, "HOME-12").id;
  const post = (issue_id, file) => {
    const body = new FormData();
    body.append("issue_id", issue_id);
    if (file) body.append("file", file, file.name);
    return mock.hass.fetchWithAuth("/api/homeboard/upload", { method: "POST", body });
  };
  const good = await post(id, new File([new Uint8Array(10)], "a.png", { type: "image/png" }));
  assert.equal(good.status, 200);
  assert.equal((await good.json()).name, "a.png");
  assert.equal((await post(id, new File(["x"], "a.txt", { type: "text/plain" }))).status, 415);
  assert.equal((await post("nope", new File(["x"], "a.png", { type: "image/png" }))).status, 404);
  backend.setSettings({ attachments: { max_mb: 0.000001 } });
  assert.equal((await post(id, new File([new Uint8Array(10)], "big.png", { type: "image/png" }))).status, 413);
  assert.equal((await post(id)).status, 400);
  assert.equal((await mock.hass.fetchWithAuth("/api/homeboard/other", { method: "POST", body: new FormData() })).status, 404);
  assert.deepEqual(Object.keys(mock.hass.states).filter((k) => k.startsWith("camera.")), ["camera.front_door", "camera.garden"]);
});
