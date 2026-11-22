import assert from "node:assert/strict";
import { test } from "node:test";
import { EMPTY_FILTER, filterIssues, groupLanes, isFilterActive, matchesFilter, normaliseFilter, sortIssues } from "../../custom_components/homeboard/static/filters.js";
import { makeState } from "./fixtures.js";

const { index, payload } = makeState();
const home = [...index.projects].find((p) => p.key === "HOME");
const homeIssues = index.byProject.get(home.id);
const keys = (list) => list.map((i) => i.key);
const ctx = { me: "person.joachim", index };

test("normaliseFilter accepts objects, snake case and the comma shorthand", () => {
  assert.deepEqual(normaliseFilter(null), EMPTY_FILTER);
  assert.equal(normaliseFilter({ due_soon: true }).dueSoon, true);
  assert.equal(normaliseFilter({ dueSoon: true, label: " garden " }).label, "garden");
  const short = normaliseFilter("mine, Overdue ,auto,bogus");
  assert.equal(short.mine && short.overdue && short.auto, true);
  assert.equal(short.unassigned, false);
  assert.equal(normaliseFilter("health").auto, true);
});

test("isFilterActive", () => {
  assert.equal(isFilterActive(EMPTY_FILTER), false);
  assert.equal(isFilterActive({ ...EMPTY_FILTER, text: "  " }), false);
  assert.equal(isFilterActive({ ...EMPTY_FILTER, label: "x" }), true);
  assert.equal(isFilterActive({ ...EMPTY_FILTER, auto: true }), true);
});

test("quick filters: mine, unassigned, overdue, due soon", () => {
  const mine = filterIssues(homeIssues, { ...EMPTY_FILTER, mine: true }, ctx);
  assert.ok(mine.length > 0 && mine.every((i) => i.assignee === "person.joachim"));
  assert.deepEqual(filterIssues(homeIssues, { ...EMPTY_FILTER, mine: true }, { me: null, index }), []);
  const unassigned = filterIssues(homeIssues, { ...EMPTY_FILTER, unassigned: true }, ctx);
  assert.ok(unassigned.length > 0 && unassigned.every((i) => !i.assignee));
  assert.deepEqual(keys(filterIssues(homeIssues, { ...EMPTY_FILTER, overdue: true }, ctx)).sort(), ["HOME-15", "HOME-7"]);
  const soon = filterIssues(homeIssues, { ...EMPTY_FILTER, dueSoon: true }, ctx);
  assert.ok(soon.length >= 2 && soon.every((i) => i.due_soon && !i.overdue));
});

test("auto filter keeps only home-health issues", () => {
  const all = index.issues;
  const auto = filterIssues(all, { ...EMPTY_FILTER, auto: true }, ctx);
  assert.equal(auto.length, 6);
  assert.ok(auto.every((i) => i.source === "health"));
});

test("label, type, priority, assignee and text filters combine with AND", () => {
  assert.ok(filterIssues(homeIssues, { ...EMPTY_FILTER, label: "garden" }, ctx).every((i) => i.labels.includes("garden")));
  assert.ok(filterIssues(homeIssues, { ...EMPTY_FILTER, type: "bug" }, ctx).every((i) => i.type === "bug"));
  assert.ok(filterIssues(homeIssues, { ...EMPTY_FILTER, priority: "high" }, ctx).every((i) => i.priority === "high"));
  assert.ok(filterIssues(homeIssues, { ...EMPTY_FILTER, assignee: "person.padmaja" }, ctx).every((i) => i.assignee === "person.padmaja"));
  assert.ok(filterIssues(homeIssues, { ...EMPTY_FILTER, assignee: "me" }, ctx).every((i) => i.assignee === "person.joachim"));
  assert.deepEqual(filterIssues(homeIssues, { ...EMPTY_FILTER, assignee: "me" }, { me: null, index }), []);
  assert.deepEqual(keys(filterIssues(homeIssues, { ...EMPTY_FILTER, label: "garden", type: "bug" }, ctx)), ["HOME-9"]);
});

test("text search matches key, summary, labels and assignee name, all words", () => {
  const find = (text) => keys(filterIssues(homeIssues, { ...EMPTY_FILTER, text }, ctx));
  assert.deepEqual(find("gate latch"), ["HOME-9"]);
  assert.deepEqual(find("HOME-9"), ["HOME-9"]);
  assert.ok(find("bills").includes("HOME-7"));
  assert.ok(find("padmaja").includes("HOME-7"));
  assert.deepEqual(find("gate zzzz"), []);
  assert.equal(matchesFilter(homeIssues[0], EMPTY_FILTER, ctx), true);
});

test("groupLanes: none, assignee (people order, unassigned last), priority", () => {
  const none = groupLanes(homeIssues, "none", { people: payload.people });
  assert.equal(none.length, 1);
  assert.equal(none[0].kind, "all");

  const lanes = groupLanes(homeIssues, "assignee", { people: payload.people });
  assert.deepEqual(lanes.map((l) => l.id), ["person:person.joachim", "person:person.padmaja", "unassigned"]);
  assert.equal(lanes.reduce((n, l) => n + l.issues.length, 0), homeIssues.length);

  const byPriority = groupLanes(homeIssues, "priority", { people: [] });
  assert.deepEqual(byPriority.map((l) => l.value), ["high", "medium", "low", "lowest"]);
});

test("groupLanes keeps one empty lane when nothing matches", () => {
  assert.deepEqual(groupLanes([], "assignee", { people: payload.people }).map((l) => l.id), ["all"]);
  assert.deepEqual(groupLanes([], "priority", {}).map((l) => l.id), ["all"]);
});

test("groupLanes adds lanes for assignees that are not in the people list", () => {
  const ghost = [{ id: "x", assignee: "person.ghost", priority: "low" }];
  assert.deepEqual(groupLanes(ghost, "assignee", { people: [] }).map((l) => l.id), ["person:person.ghost"]);
});

test("sortIssues sorts by column and keeps empty values last", () => {
  const sorted = (by, dir) => sortIssues(homeIssues, { by, dir }, index);
  const dues = sorted("due", "asc").map((i) => i.due);
  const firstEmpty = dues.indexOf(null);
  assert.ok(dues.slice(0, firstEmpty).every((d, i, a) => !i || a[i - 1] <= d));
  assert.ok(dues.slice(firstEmpty).every((d) => d === null));
  assert.equal(sorted("due", "desc").at(-1).due, null);
  assert.deepEqual(keys(sorted("key", "asc")).slice(0, 3), ["HOME-1", "HOME-2", "HOME-3"]);
  assert.equal(sorted("priority", "asc")[0].priority, "high");
  assert.equal(sortIssues(homeIssues, { by: "nope", dir: "asc" }, index), homeIssues);
});
