import assert from "node:assert/strict";
import { test } from "node:test";
import { setLanguage } from "../../custom_components/homeboard/static/i18n.js";
import { dueFromDays, hasSuggestion, similarIssues, suggestionChips, suggestionFill, suggestionSummary } from "../../custom_components/homeboard/static/suggestions.js";
import { NOW, makeState } from "./fixtures.js";

setLanguage("en");
const { index } = makeState();
const full = {
  assignee: "person.padmaja",
  labels: ["bills"],
  priority: "high",
  due_in_days: 3,
  similar: [{ key: "HOME-7", summary: "Pay the electricity bill", status: "To do" }, { key: "HOME-999", summary: "Gone", status: "Done" }],
  evidence: "based on 4 similar issues",
  confidence: 0.8,
};

test("hasSuggestion is false for null and for a suggestion with nothing to offer", () => {
  assert.equal(hasSuggestion(null), false);
  assert.equal(hasSuggestion({ assignee: null, labels: [], priority: null, due_in_days: null }), false);
  assert.equal(hasSuggestion({ assignee: null, labels: [], priority: null, due_in_days: 0 }), true, "due today is a suggestion");
  assert.equal(hasSuggestion(full), true);
});

test("suggestionChips in a stable order, with readable text", () => {
  const chips = suggestionChips(full, { index });
  assert.deepEqual(chips.map((c) => c.kind), ["assignee", "label", "priority", "due"]);
  assert.deepEqual(chips.map((c) => c.text), ["Padmaja", "#bills", "High", "due in 3 days"]);
  assert.equal(suggestionSummary(chips), "Padmaja, #bills, High, due in 3 days");
  assert.equal(chips[0].person, "person.padmaja");
  assert.deepEqual(suggestionChips(null, { index }), []);
});

test("due wording: today, one day, many days, Danish", () => {
  const text = (days) => suggestionChips({ due_in_days: days }, { index })[0].text;
  assert.equal(text(0), "due today");
  assert.equal(text(1), "due in 1 day");
  assert.equal(text(14), "due in 14 days");
  setLanguage("da");
  assert.equal(text(1), "frist om 1 dag");
  assert.equal(text(3), "frist om 3 dage");
  setLanguage("en");
});

test("similarIssues links to issues that are on the board", () => {
  const similar = similarIssues(full, index);
  assert.equal(similar[0].id, index.issueByKey.get("HOME-7").id);
  assert.equal(similar[1].id, null);
  assert.deepEqual(similarIssues(null, index), []);
});

test("dueFromDays counts calendar days from today", () => {
  assert.equal(dueFromDays(0, NOW), "2026-11-22");
  assert.equal(dueFromDays(9, NOW), "2026-12-01");
  assert.equal(dueFromDays(-1, NOW), "2026-11-21");
});

test("suggestionFill only touches fields the user left empty", () => {
  const empty = { assignee: "", labels: [], priority: "medium", due: "" };
  const all = suggestionFill(full, empty, { now: NOW });
  assert.deepEqual(all.filled, ["assignee", "labels", "priority", "due"]);
  assert.deepEqual(all.fields, { assignee: "person.padmaja", labels: ["bills"], priority: "high", due: "2026-11-25" });

  const partial = suggestionFill(full, { assignee: "person.joachim", labels: ["x"], priority: "low", due: "2026-12-24" }, { touched: new Set(["priority"]), now: NOW });
  assert.deepEqual(partial.filled, []);

  const untouchedPriority = suggestionFill({ priority: "low" }, { assignee: "", labels: [], priority: "medium", due: "" }, { now: NOW });
  assert.deepEqual(untouchedPriority.fields, { priority: "low" });
  assert.deepEqual(suggestionFill(null, empty).filled, []);
});
