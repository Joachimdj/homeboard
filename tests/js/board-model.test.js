import assert from "node:assert/strict";
import { test } from "node:test";
import { boardModel } from "../../custom_components/homeboard/static/board-model.js";
import { EMPTY_FILTER } from "../../custom_components/homeboard/static/filters.js";
import { makeState } from "./fixtures.js";

const { index } = makeState();
const home = index.projects.find((p) => p.key === "HOME");
const base = { index, project: home, filter: EMPTY_FILTER, me: "person.joachim" };

test("board hides backlog statuses unless asked", () => {
  assert.deepEqual(boardModel(base).statuses.map((s) => s.name), ["To do", "In progress", "Done"]);
  assert.deepEqual(boardModel({ ...base, showBacklog: true }).statuses.map((s) => s.name), ["Backlog", "To do", "In progress", "Done"]);
});

test("backlog layout lists only backlog statuses, in a single lane", () => {
  const model = boardModel({ ...base, layout: "backlog", laneMode: "assignee" });
  assert.deepEqual(model.statuses.map((s) => s.name), ["Backlog"]);
  assert.equal(model.lanes.length, 1);
  assert.ok(model.total >= 4);
});

test("WIP counts are unfiltered while the cards are filtered", () => {
  const progress = home.statuses.find((s) => s.name === "In progress");
  const model = boardModel({ ...base, filter: { ...EMPTY_FILTER, label: "bills" } });
  assert.equal(model.counts.get(progress.id), 5);
  const shown = model.lanes[0].byStatus.get(progress.id);
  assert.deepEqual(shown.map((i) => i.key), ["HOME-16"]);
});

test("cards inside a column are sorted by rank, then number", () => {
  const model = boardModel(base);
  for (const list of model.lanes[0].byStatus.values()) {
    for (let i = 1; i < list.length; i++) assert.ok(list[i - 1].rank <= list[i].rank);
  }
});

test("swimlanes split the same issues without losing any", () => {
  const flat = boardModel(base);
  const lanes = boardModel({ ...base, laneMode: "assignee" });
  assert.ok(lanes.lanes.length > 1);
  assert.equal(lanes.lanes.reduce((n, l) => n + l.issues.length, 0), flat.total);
});
