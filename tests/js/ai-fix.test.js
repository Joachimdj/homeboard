// Pure logic of AI Fix (PROTOCOL section 11): buttons, diff lines, text keys, counts.

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  ERROR_CODES,
  KINDS,
  REASONS,
  aiRev,
  applyLabel,
  canAnalyse,
  chipState,
  classifyDiffLine,
  confidenceLabel,
  confirmKey,
  errorKey,
  formatCount,
  kindLabel,
  notReadyKey,
  parseDiff,
  proposalActions,
  reasonText,
  replaceProposal,
  riskLabel,
  riskLevel,
  sectionVisible,
  statusKind,
  summarisePreview,
  summariseSent,
} from "../../custom_components/homeboard/static/ai-fix.js";
import da from "../../custom_components/homeboard/static/strings-da.js";
import en from "../../custom_components/homeboard/static/strings-en.js";

const proposal = (fields) => ({ id: "p1", kind: "automation_edit", status: "proposed", blocked: null, undoable: false, new_yaml: "alias: x", ...fields });

test("diff lines: + green, - red, @@ muted, headers meta, the rest context", () => {
  assert.equal(classifyDiffLine("+      - binary_sensor.new"), "add");
  assert.equal(classifyDiffLine("-      - binary_sensor.old"), "del");
  assert.equal(classifyDiffLine("@@ -3,7 +3,7 @@"), "hunk");
  assert.equal(classifyDiffLine("--- current"), "meta");
  assert.equal(classifyDiffLine("+++ proposed"), "meta");
  assert.equal(classifyDiffLine("\\ No newline at end of file"), "meta");
  assert.equal(classifyDiffLine(" alias: Hallway"), "ctx");
  assert.equal(classifyDiffLine(""), "ctx");
  assert.equal(classifyDiffLine(undefined), "ctx");
});

test("inside a hunk a removed or added YAML '---' is an ordinary line, not a file header", () => {
  const diff = ["--- current", "+++ proposed", "@@ -1,2 +1,2 @@", "---", "+--- ", " alias: x", "-- note", "+++"].join("\n");
  assert.deepEqual(
    parseDiff(diff).map((line) => line.kind),
    ["meta", "meta", "hunk", "del", "add", "ctx", "del", "add"],
  );
});

test("parseDiff: CRLF, trailing newline, empty and non-string input", () => {
  assert.deepEqual(parseDiff("@@ -1 +1 @@\r\n-a\r\n+b\r\n").map((l) => l.text), ["@@ -1 +1 @@", "-a", "+b"]);
  assert.deepEqual(parseDiff(""), []);
  assert.deepEqual(parseDiff("   "), []);
  assert.deepEqual(parseDiff(null), []);
  assert.deepEqual(parseDiff({ not: "text" }), []);
});

test("buttons of a proposed change: apply, dismiss, copy", () => {
  assert.deepEqual(proposalActions(proposal()), ["apply", "dismiss", "copy"]);
  assert.deepEqual(proposalActions(proposal({ kind: "manual_steps", new_yaml: "", steps: ["a"] })), ["apply", "dismiss"]);
  assert.deepEqual(proposalActions(proposal({ kind: "reload_integration", new_yaml: "" })), ["apply", "dismiss"]);
});

test("a blocked proposal can be dismissed and copied but never applied", () => {
  const blocked = proposal({ blocked: { code: "protected", message: "no" } });
  assert.deepEqual(proposalActions(blocked), ["dismiss", "copy"]);
  assert.deepEqual(proposalActions({ ...blocked, new_yaml: "" }), ["dismiss"]);
});

test("Undo needs `undoable`: only applied automation edits and disables", () => {
  assert.deepEqual(proposalActions(proposal({ status: "applied", undoable: true })), ["undo"]);
  assert.deepEqual(proposalActions(proposal({ status: "applied", undoable: false })), []);
  assert.deepEqual(proposalActions(proposal({ status: "applied", kind: "reload_integration", undoable: false })), []);
  assert.deepEqual(proposalActions(proposal({ status: "applied", kind: "manual_steps", undoable: false })), []);
  assert.deepEqual(proposalActions(proposal({ status: "applied" })), [], "a missing flag is not undoable");
  assert.deepEqual(proposalActions(proposal({ status: "applied", undoable: "yes" })), []);
});

test("finished proposals: a failed one can still be copied, dismissed / undone ones have no buttons", () => {
  assert.deepEqual(proposalActions(proposal({ status: "failed" })), ["copy"]);
  assert.deepEqual(proposalActions(proposal({ status: "failed", new_yaml: "" })), []);
  assert.deepEqual(proposalActions(proposal({ status: "dismissed" })), []);
  assert.deepEqual(proposalActions(proposal({ status: "undone" })), []);
  assert.deepEqual(proposalActions(proposal({ status: "whatever" })), []);
  assert.deepEqual(proposalActions(null), []);
});

test("an unknown kind is never applied from here", () => {
  assert.deepEqual(proposalActions(proposal({ kind: "run_shell" })), ["dismiss", "copy"]);
});

test("labels and the confirm question per kind", () => {
  assert.equal(applyLabel("manual_steps"), "ai.add_to_checklist");
  assert.equal(applyLabel("automation_edit"), "ai.apply");
  assert.equal(applyLabel("reload_integration"), "ai.apply");
  assert.equal(confirmKey("automation_edit"), "ai.confirm_edit");
  assert.equal(confirmKey("automation_disable"), "ai.confirm_disable");
  assert.equal(confirmKey("reload_integration"), "ai.confirm_reload");
  assert.equal(confirmKey("manual_steps"), null, "adding checklist items needs one press");
});

test("risk, confidence, kind and status only ever map to fixed keys", () => {
  assert.equal(riskLabel("low"), "ai.risk.low");
  assert.equal(riskLabel("high"), "ai.risk.high");
  assert.equal(riskLabel('high" onmouseover="x'), "ai.risk.medium");
  assert.equal(riskLevel(undefined), "medium");
  assert.equal(confidenceLabel("medium"), "ai.confidence.medium");
  assert.equal(confidenceLabel("certain"), null);
  assert.equal(kindLabel("manual_steps"), "ai.kind.manual_steps");
  assert.equal(kindLabel("x\"><img>"), "ai.kind.unknown");
  assert.equal(statusKind("applied"), "applied");
  assert.equal(statusKind("applied\" onclick=\"x"), "proposed");
});

test("reasons: the five known ones, null for none, a generic text for anything else", () => {
  for (const reason of ["disabled", "no_entity", "choose_entity", "unsupported", "limit"]) assert.equal(reasonText(reason), `ai.reason.${reason}`);
  assert.equal(reasonText(null), null);
  assert.equal(reasonText(undefined), null);
  assert.equal(reasonText(""), null);
  assert.equal(reasonText("quota_of_the_moon"), "ai.reason.unknown");
  assert.equal(reasonText(42), "ai.reason.unknown");
});

test("the not-ready line never comes out empty", () => {
  assert.equal(notReadyKey({ ready: true, reason: "limit" }), null);
  assert.equal(notReadyKey({ ready: false, reason: "choose_entity" }), "ai.reason.choose_entity");
  assert.equal(notReadyKey({ ready: false, reason: "something new" }), "ai.reason.unknown");
  assert.equal(notReadyKey({ ready: false, reason: null }), "ai.reason.unknown");
  assert.equal(notReadyKey({ ready: false, reason: null }, true), null, "an analysis in progress explains itself");
  assert.equal(notReadyKey({ ready: false, reason: "something new" }, true), "ai.reason.unknown");
  assert.equal(notReadyKey(null), null);
});

test("error codes get friendly keys, anything else shows the server message", () => {
  for (const code of ERROR_CODES) assert.equal(errorKey(code), `ai.error.${code}`);
  assert.equal(errorKey("blocked"), null);
  assert.equal(errorKey("not_found"), null);
  assert.equal(errorKey(undefined), null);
});

test("the Analyse button needs a ready AI and no call in flight", () => {
  assert.equal(canAnalyse({ ready: true }), true);
  assert.equal(canAnalyse({ ready: false }), false);
  assert.equal(canAnalyse({ ready: true }, { running: true }), false);
  assert.equal(canAnalyse({ ready: true }, { working: true }), false);
  assert.equal(canAnalyse(null), false);
});

test("sent counts: three clean integers, null when there is nothing", () => {
  assert.deepEqual(summariseSent({ chars: 11800, entities: 14, automations: 1 }), { chars: 11800, entities: 14, automations: 1 });
  assert.deepEqual(summariseSent({ chars: "12", entities: -3, automations: 2.9 }), { chars: 12, entities: 0, automations: 2 });
  assert.deepEqual(summariseSent({}), { chars: 0, entities: 0, automations: 0 });
  assert.equal(summariseSent(null), null);
  assert.equal(summariseSent("lots"), null);
  assert.deepEqual(summarisePreview({ chars: 5, entities: 1, automations: 2, redactions: 3, prompt: "x" }), { chars: 5, entities: 1, automations: 2, redactions: 3 });
  assert.equal(formatCount(11800, "en"), "11,800");
  assert.equal(formatCount(11800, "da"), "11.800");
  assert.equal(formatCount("nope", "en"), "0");
});

test("card chip: AI when a proposal waits, AI... while running, nothing otherwise (non-admins have no ai)", () => {
  assert.equal(chipState({ ai: { state: "ready", rev: 2, proposals: 2, applied: 0 } }), "ready");
  assert.equal(chipState({ ai: { state: "ready", rev: 2, proposals: 0, applied: 1 } }), null);
  assert.equal(chipState({ ai: { state: "running", rev: 1, proposals: 0, applied: 0 } }), "running");
  assert.equal(chipState({ ai: { state: "failed", rev: 1, proposals: 0, applied: 0 } }), null);
  assert.equal(chipState({}), null);
  assert.equal(chipState(null), null);
});

test("rev of an issue: null while there is no record", () => {
  assert.equal(aiRev({ ai: { rev: 4 } }), 4);
  assert.equal(aiRev({ ai: { rev: 0 } }), 0);
  assert.equal(aiRev({}), null);
  assert.equal(aiRev(undefined), null);
});

test("settings.ai_fix guard: only for administrators, with the option on, and not in the new-issue form", () => {
  const on = { enabled: true, entity: "ai_task.x", allow_protected: false };
  assert.equal(sectionVisible({ aiFix: on, isAdmin: true, create: false }), true);
  assert.equal(sectionVisible({ aiFix: on, isAdmin: false, create: false }), false);
  assert.equal(sectionVisible({ aiFix: on, isAdmin: true, create: true }), false);
  assert.equal(sectionVisible({ aiFix: { ...on, enabled: false }, isAdmin: true, create: false }), false);
  assert.equal(sectionVisible({ aiFix: { ...on, enabled: "yes" }, isAdmin: true, create: false }), false);
  assert.equal(sectionVisible({ aiFix: undefined, isAdmin: true, create: false }), false, "non-admin payloads have no settings.ai_fix");
});

test("replacing a proposal returns a new record and leaves the others alone", () => {
  const record = { state: "ready", proposals: [{ id: "p1", status: "proposed" }, { id: "p2", status: "proposed" }] };
  const next = replaceProposal(record, { id: "p2", status: "applied" });
  assert.deepEqual(next.proposals.map((p) => p.status), ["proposed", "applied"]);
  assert.equal(record.proposals[1].status, "proposed");
  assert.equal(replaceProposal(null, { id: "p1" }), null);
  assert.equal(replaceProposal(record, null), record);
});

test("every text key AI Fix can ask for exists in English and Danish", () => {
  const keys = new Set(["ai.reason.unknown", "ai.kind.unknown", "ai.add_to_checklist", "ai.apply"]);
  for (const reason of REASONS) keys.add(reasonText(reason));
  for (const code of ERROR_CODES) keys.add(errorKey(code));
  for (const kind of KINDS) {
    keys.add(kindLabel(kind));
    keys.add(applyLabel(kind));
    if (confirmKey(kind)) keys.add(confirmKey(kind));
  }
  for (const risk of ["low", "medium", "high"]) {
    keys.add(riskLabel(risk));
    keys.add(confidenceLabel(risk));
  }
  for (const key of keys) {
    assert.ok(key in en, `en: ${key}`);
    assert.ok(key in da, `da: ${key}`);
  }
  // Danish is written, not copied: only the "AI" chips read the same in both languages.
  const same = Object.keys(en).filter((k) => k.startsWith("ai.") && da[k] === en[k]);
  assert.deepEqual(same, ["ai.chip", "ai.chip_running"]);
});
