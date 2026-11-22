import assert from "node:assert/strict";
import { test } from "node:test";
import { CHECKLIST_MAX_ITEMS, checklistProgress, epicProgress, issueChecklist, moveBy, moveIndex, rowIndexAt, splitItems } from "../../custom_components/homeboard/static/checklist.js";
import { makeState } from "./fixtures.js";

test("checklistProgress counts done items and rounds the percentage", () => {
  assert.deepEqual(checklistProgress([]), { done: 0, total: 0, percent: 0 });
  assert.deepEqual(checklistProgress(undefined), { done: 0, total: 0, percent: 0 });
  assert.deepEqual(checklistProgress([{ done: true }, { done: false }, { done: false }]), { done: 1, total: 3, percent: 33 });
  assert.deepEqual(checklistProgress([{ done: true }, { done: true }]), { done: 2, total: 2, percent: 100 });
});

test("issueChecklist and epicProgress read the list payload counters", () => {
  assert.equal(issueChecklist({ checklist_total: 0, checklist_done: 0 }), null);
  assert.equal(issueChecklist({}), null);
  assert.deepEqual(issueChecklist({ checklist_total: 5, checklist_done: 3 }), { done: 3, total: 5, percent: 60 });
  assert.equal(epicProgress({ type: "task", epic_total: 3, epic_done: 1 }), null);
  assert.equal(epicProgress({ type: "epic", epic_total: 0, epic_done: 0 }), null);
  assert.deepEqual(epicProgress({ type: "epic", epic_total: 4, epic_done: 1 }), { done: 1, total: 4, percent: 25 });
});

test("the demo payload carries consistent counters", () => {
  const { index } = makeState();
  const beds = index.issueByKey.get("HOME-14");
  assert.deepEqual(issueChecklist(beds), { done: 3, total: 5, percent: 60 });
  const epic = index.issues.find((i) => i.type === "epic");
  const progress = epicProgress(epic);
  assert.equal(progress.total, 4);
  assert.equal(progress.done, 1);
  assert.equal(index.issueByKey.get("HOME-9").attachment_count, 3);
});

test("moveIndex and moveBy reorder ids and clamp at the ends", () => {
  const ids = ["a", "b", "c", "d"];
  assert.deepEqual(moveIndex(ids, 0, 2), ["b", "c", "a", "d"]);
  assert.deepEqual(moveIndex(ids, 3, 0), ["d", "a", "b", "c"]);
  assert.deepEqual(moveIndex(ids, 1, 99), ["a", "c", "d", "b"]);
  assert.equal(moveIndex(ids, 1, 1), ids, "same position returns the same array");
  assert.equal(moveIndex(ids, 9, 0), ids);
  assert.deepEqual(ids, ["a", "b", "c", "d"], "input is never mutated");
  assert.deepEqual(moveBy(ids, "c", -1), ["a", "c", "b", "d"]);
  assert.deepEqual(moveBy(ids, "c", 1), ["a", "b", "d", "c"]);
  assert.equal(moveBy(ids, "a", -1), ids);
  assert.equal(moveBy(ids, "d", 1), ids);
  assert.equal(moveBy(ids, "zzz", 1), ids);
});

test("rowIndexAt finds the row under the pointer and clamps outside the list", () => {
  const spans = [[0, 30], [30, 60], [60, 90]];
  assert.equal(rowIndexAt(spans, 10), 0);
  assert.equal(rowIndexAt(spans, 30), 1);
  assert.equal(rowIndexAt(spans, 89), 2);
  assert.equal(rowIndexAt(spans, -50), 0);
  assert.equal(rowIndexAt(spans, 500), 2);
  assert.equal(rowIndexAt([], 10), -1);
});

test("splitItems turns pasted text into one item per line without list markers", () => {
  assert.deepEqual(splitItems("Buy milk"), ["Buy milk"]);
  assert.deepEqual(splitItems("- Buy milk\r\n* Call mum\n\n[ ] Pay bill\n[x] Done thing\n• Dot"), ["Buy milk", "Call mum", "Pay bill", "Done thing", "Dot"]);
  assert.deepEqual(splitItems("   \n  "), []);
  assert.equal(splitItems("x".repeat(500))[0].length, 200);
  assert.ok(CHECKLIST_MAX_ITEMS >= 100);
});
