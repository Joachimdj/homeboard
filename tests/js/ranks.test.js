import assert from "node:assert/strict";
import { test } from "node:test";
import { moveIssue, patchIssue, removeIssue, reorderStatuses } from "../../custom_components/homeboard/static/optimistic.js";
import { RANK_GAP, followingId, isNoopMove, rankForInsert } from "../../custom_components/homeboard/static/ranks.js";
import { makeState } from "./fixtures.js";

const col = (...ranks) => ranks.map((rank, i) => ({ id: `i${i + 1}`, rank, number: i + 1 }));

test("rankForInsert: empty column, end, front and between", () => {
  assert.equal(rankForInsert([], null), RANK_GAP);
  assert.equal(rankForInsert(col(1000, 2000, 3000), null), 4000);
  assert.equal(rankForInsert(col(1000, 2000, 3000), "i1"), 0);
  assert.equal(rankForInsert(col(1000, 2000, 3000), "i2"), 1500);
  assert.equal(rankForInsert(col(1000, 2000, 3000), "i3"), 2500);
});

test("rankForInsert falls back to the end for an unknown `before` and handles tight gaps", () => {
  assert.equal(rankForInsert(col(1000, 2000), "nope"), 3000);
  const tight = rankForInsert(col(1000, 1001), "i2");
  assert.ok(tight > 1000 && tight < 1001);
});

test("followingId / isNoopMove", () => {
  const list = col(1000, 2000, 3000);
  assert.equal(followingId(list, "i1"), "i2");
  assert.equal(followingId(list, "i3"), null);
  assert.equal(followingId(list, "zzz"), null);
  assert.equal(isNoopMove(list, "i2", "i3"), true); // already in front of i3
  assert.equal(isNoopMove(list, "i3", null), true); // already last
  assert.equal(isNoopMove(list, "i2", "i2"), true);
  assert.equal(isNoopMove(list, "i1", "i3"), false);
  assert.equal(isNoopMove(list, "i1", null), false);
});

test("moveIssue transform places the card and does not mutate the input", () => {
  const { payload, index } = makeState();
  const home = index.projects.find((p) => p.key === "HOME");
  const todo = home.statuses.find((s) => s.name === "To do");
  const progress = home.statuses.find((s) => s.name === "In progress");
  const issue = index.issueByKey.get("HOME-7");
  const target = index.byProject.get(home.id).filter((i) => i.status === progress.id);

  const snapshot = JSON.stringify(payload);
  const moved = moveIssue(payload, issue.id, progress.id, target[0].id);
  assert.equal(JSON.stringify(payload), snapshot);
  const after = moved.issues.find((i) => i.id === issue.id);
  assert.equal(after.status, progress.id);
  assert.ok(after.rank < target[0].rank);

  const atEnd = moveIssue(payload, issue.id, progress.id, null).issues.find((i) => i.id === issue.id);
  assert.ok(atEnd.rank > target.at(-1).rank);
  assert.equal(moveIssue(payload, "missing", todo.id, null), payload);
});

test("patchIssue, removeIssue and reorderStatuses", () => {
  const { payload, index } = makeState();
  const issue = payload.issues[0];
  assert.equal(patchIssue(payload, issue.id, { summary: "x" }).issues[0].summary, "x");
  assert.equal(payload.issues[0].summary === "x", false);
  assert.equal(removeIssue(payload, issue.id).issues.length, payload.issues.length - 1);
  const home = index.projects.find((p) => p.key === "HOME");
  const ids = home.statuses.map((s) => s.id).reverse();
  assert.deepEqual(reorderStatuses(payload, home.id, ids).projects.find((p) => p.id === home.id).statuses.map((s) => s.id), ids);
});
