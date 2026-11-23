// The harness backend must follow PROTOCOL section 11, otherwise looking at the AI Fix UI proves little.

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
const issue = (backend, key) => [...backend.issues.values()].find((i) => i.key === key);

/** A backend whose "model" answers when the test says so. */
function slowBackend() {
  const backend = makeBackend();
  const queue = [];
  backend.ai.schedule = (fn) => queue.push(fn);
  return { backend, answer: () => queue.splice(0).forEach((fn) => fn()) };
}

test("seed: records on four FIX issues, none on the others", () => {
  const { issues, settings } = makeBackend().payload();
  const ai = Object.fromEntries(issues.filter((i) => i.ai).map((i) => [i.key, i.ai]));
  assert.deepEqual(Object.keys(ai).sort(), ["FIX-1", "FIX-2", "FIX-3", "FIX-6"]);
  assert.deepEqual(ai["FIX-2"], { state: "ready", rev: 1, proposals: 3, applied: 0 });
  assert.deepEqual(ai["FIX-6"], { state: "ready", rev: 1, proposals: 1, applied: 1 });
  assert.equal(ai["FIX-1"].state, "failed");
  assert.equal(ai["FIX-3"].state, "running");
  assert.deepEqual(settings.ai_fix, { enabled: true, entity: "ai_task.claude_ai_task", allow_protected: false });
});

test("non-admins get no ai key, no settings.ai_fix, and every ai/* call is refused", () => {
  const backend = makeBackend();
  const fix2 = issue(backend, "FIX-2");
  backend.setUser({ is_admin: false });
  const payload = backend.payload();
  assert.ok(payload.issues.every((i) => !("ai" in i)));
  assert.ok(!("ai_fix" in payload.settings));
  for (const command of ["get", "preview", "analyze", "apply", "undo", "dismiss"]) {
    assert.equal(codeOf(() => run(backend, `ai/${command}`, { issue_id: fix2.id, proposal_id: "p1" })), "unauthorized", command);
  }
});

test("ai/get: readiness, entity, limit and the record with all proposal fields", () => {
  const backend = makeBackend();
  const result = run(backend, "ai/get", { issue_id: issue(backend, "FIX-2").id });
  assert.equal(result.enabled, true);
  assert.equal(result.ready, true);
  assert.equal(result.reason, null);
  assert.equal(result.entity, "ai_task.claude_ai_task");
  assert.equal(result.entity_name, "Claude AI Task");
  assert.deepEqual(result.limit, { used: 3, max: 20 });
  assert.equal(result.record.state, "ready");
  assert.deepEqual(result.record.sent, { chars: 11800, entities: 14, automations: 1 });
  const [edit, steps, blocked] = result.record.proposals;
  assert.equal(edit.kind, "automation_edit");
  assert.match(edit.diff, /^--- current\n\+\+\+ proposed\n@@ /);
  assert.ok(edit.new_yaml.startsWith("alias:"));
  assert.deepEqual([steps.kind, steps.steps.length], ["manual_steps", 3]);
  assert.equal(blocked.blocked.code, "protected");
  for (const p of result.record.proposals) {
    for (const field of ["id", "kind", "title", "explanation", "risk", "target", "target_name", "status", "blocked", "warnings", "diff", "new_yaml", "steps", "applied_at", "undone_at", "error", "undoable"]) assert.ok(field in p, `${p.id}.${field}`);
  }
  assert.equal(run(backend, "ai/get", { issue_id: issue(backend, "FIX-4").id }).record, null);
});

test("ai/get reasons: disabled, limit, harness overrides; ready is false while running", () => {
  const backend = makeBackend();
  const fix4 = issue(backend, "FIX-4").id;
  backend.setSettings({ ai_fix: { enabled: false } });
  assert.equal(run(backend, "ai/get", { issue_id: fix4 }).reason, "disabled");
  backend.setSettings({ ai_fix: { enabled: true } });
  backend.ai.usage.count = backend.ai.max;
  assert.deepEqual([run(backend, "ai/get", { issue_id: fix4 }).reason, run(backend, "ai/get", { issue_id: fix4 }).ready], ["limit", false]);
  backend.ai.usage.count = 3;
  for (const reason of ["no_entity", "choose_entity", "unsupported"]) {
    backend.ai.reason = reason;
    assert.equal(run(backend, "ai/get", { issue_id: fix4 }).reason, reason);
  }
  backend.ai.reason = null;
  const running = run(backend, "ai/get", { issue_id: issue(backend, "FIX-3").id });
  assert.deepEqual([running.ready, running.reason], [false, null]);
});

test("ai/analyze: returns running at once, bumps the rev, then the answer arrives and bumps it again", () => {
  const { backend, answer } = slowBackend();
  const fix4 = issue(backend, "FIX-4");
  const pushes = [];
  backend.subscribe((payload) => pushes.push(payload.issues.find((i) => i.id === fix4.id).ai));
  assert.deepEqual(run(backend, "ai/analyze", { issue_id: fix4.id, note: "  battery was changed in June  " }), { state: "running" });
  assert.deepEqual(pushes.at(-1), { state: "running", rev: 1, proposals: 0, applied: 0 });
  assert.equal(codeOf(() => run(backend, "ai/analyze", { issue_id: fix4.id })), "ai_busy");
  assert.equal(run(backend, "ai/get", { issue_id: fix4.id }).record.note, "battery was changed in June");
  answer();
  assert.deepEqual(pushes.at(-1), { state: "ready", rev: 2, proposals: 1, applied: 0 });
  assert.equal(backend.ai.usage.count, 4);
  const record = run(backend, "ai/get", { issue_id: fix4.id }).record;
  assert.equal(record.proposals[0].kind, "manual_steps");
  assert.ok(record.finished);
  // analysing again replaces the record and keeps counting the rev up
  run(backend, "ai/analyze", { issue_id: fix4.id });
  assert.equal(pushes.at(-1).rev, 3);
});

test("ai/analyze errors: limit, disabled, unavailable, too long a note, failing harness", () => {
  const { backend } = slowBackend();
  const fix4 = issue(backend, "FIX-4").id;
  assert.equal(codeOf(() => run(backend, "ai/analyze", { issue_id: fix4, note: "x".repeat(501) })), "invalid_format");
  backend.ai.usage.count = backend.ai.max;
  assert.equal(codeOf(() => run(backend, "ai/analyze", { issue_id: fix4 })), "ai_limit");
  backend.ai.usage.count = 0;
  backend.ai.reason = "no_entity";
  assert.equal(codeOf(() => run(backend, "ai/analyze", { issue_id: fix4 })), "ai_unavailable");
  backend.ai.reason = null;
  backend.setSettings({ ai_fix: { enabled: false } });
  assert.equal(codeOf(() => run(backend, "ai/analyze", { issue_id: fix4 })), "ai_disabled");
  backend.setSettings({ ai_fix: { enabled: true } });
  backend.ai.fail = true;
  assert.equal(codeOf(() => run(backend, "ai/analyze", { issue_id: fix4 })), "ai_unavailable");
  assert.equal(codeOf(() => run(backend, "ai/get", { issue_id: fix4 })), "ai_unavailable");
  assert.equal(codeOf(() => run(backend, "ai/analyze", { issue_id: "nope" })), "ai_unavailable");
  backend.ai.fail = false;
  assert.equal(codeOf(() => run(backend, "ai/analyze", { issue_id: "nope" })), "not_found");
});

test("ai/analyze on the hallway issue gives the full demo answer", () => {
  const { backend, answer } = slowBackend();
  const fix2 = issue(backend, "FIX-2").id;
  run(backend, "ai/analyze", { issue_id: fix2 });
  answer();
  assert.deepEqual(run(backend, "ai/get", { issue_id: fix2 }).record.proposals.map((p) => p.status), ["proposed", "proposed", "proposed"]);
});

test("ai/preview: the exact prompt, counts, the note included", () => {
  const backend = makeBackend();
  const result = run(backend, "ai/preview", { issue_id: issue(backend, "FIX-2").id, note: "Replaced last week" });
  assert.equal(result.chars, result.prompt.length);
  assert.deepEqual([result.entities, result.automations, result.redactions], [14, 1, 2]);
  assert.match(result.prompt, /FIX-2/);
  assert.match(result.prompt, /Replaced last week/);
  assert.match(result.prompt, /<redacted:1>/);
});

test("ai/apply of an automation edit: applied, undoable, comment written; undo restores it", () => {
  const backend = makeBackend();
  const fix2 = issue(backend, "FIX-2");
  const comments = fix2.comments.length;
  const { proposal } = run(backend, "ai/apply", { issue_id: fix2.id, proposal_id: "p1" });
  assert.deepEqual([proposal.status, proposal.undoable, proposal.error], ["applied", true, null]);
  assert.ok(proposal.applied_at);
  assert.equal(fix2.comments.length, comments + 1);
  assert.deepEqual(backend.payload().issues.find((i) => i.id === fix2.id).ai, { state: "ready", rev: 2, proposals: 2, applied: 1 });
  assert.equal(codeOf(() => run(backend, "ai/apply", { issue_id: fix2.id, proposal_id: "p1" })), "conflict");
  const undone = run(backend, "ai/undo", { issue_id: fix2.id, proposal_id: "p1" }).proposal;
  assert.deepEqual([undone.status, undone.undoable], ["undone", false]);
  assert.ok(undone.undone_at);
  assert.equal(codeOf(() => run(backend, "ai/undo", { issue_id: fix2.id, proposal_id: "p1" })), "not_applied");
});

test("ai/apply of manual steps adds checklist items and cannot be undone", () => {
  const backend = makeBackend();
  const fix2 = issue(backend, "FIX-2");
  const { proposal } = run(backend, "ai/apply", { issue_id: fix2.id, proposal_id: "p2" });
  assert.deepEqual([proposal.status, proposal.undoable], ["applied", false]);
  assert.deepEqual(fix2.checklist.map((i) => i.text), proposal.steps);
  assert.equal(codeOf(() => run(backend, "ai/undo", { issue_id: fix2.id, proposal_id: "p2" })), "not_applied");
});

test("a blocked proposal cannot be applied, but it can be dismissed", () => {
  const backend = makeBackend();
  const fix2 = issue(backend, "FIX-2").id;
  assert.equal(codeOf(() => run(backend, "ai/apply", { issue_id: fix2, proposal_id: "p3" })), "blocked");
  assert.equal(run(backend, "ai/dismiss", { issue_id: fix2, proposal_id: "p3" }).proposal.status, "dismissed");
  assert.equal(codeOf(() => run(backend, "ai/dismiss", { issue_id: fix2, proposal_id: "p3" })), "conflict");
  assert.equal(codeOf(() => run(backend, "ai/apply", { issue_id: fix2, proposal_id: "p9" })), "not_found");
  assert.equal(codeOf(() => run(backend, "ai/apply", { issue_id: issue(backend, "FIX-4").id, proposal_id: "p1" })), "not_found");
});

test("the seeded applied disable can be undone, the reload cannot", () => {
  const backend = makeBackend();
  const fix6 = issue(backend, "FIX-6").id;
  const [reload, disable] = run(backend, "ai/get", { issue_id: fix6 }).record.proposals;
  assert.deepEqual([reload.status, reload.undoable], ["proposed", false]);
  assert.deepEqual([disable.status, disable.undoable], ["applied", true]);
  assert.equal(run(backend, "ai/apply", { issue_id: fix6, proposal_id: "p1" }).proposal.undoable, false);
  assert.equal(codeOf(() => run(backend, "ai/undo", { issue_id: fix6, proposal_id: "p1" })), "not_applied");
  assert.equal(run(backend, "ai/undo", { issue_id: fix6, proposal_id: "p2" }).proposal.status, "undone");
});

test("deleting an issue drops its record", () => {
  const backend = makeBackend();
  const fix2 = issue(backend, "FIX-2");
  run(backend, "issue/delete", { issue_id: fix2.id });
  assert.equal(backend.ai.fixes.has(fix2.id), false);
});
