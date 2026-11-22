import assert from "node:assert/strict";
import { test } from "node:test";
import { setLanguage } from "../../custom_components/homeboard/static/i18n.js";
import { draftFromRecurring, emptyRecurring, recurringParams, repeatFromDraft, repeatSummary } from "../../custom_components/homeboard/static/recurring.js";
import { describeActivity } from "../../custom_components/homeboard/static/activity.js";
import { makeState } from "./fixtures.js";

setLanguage("en");
const { payload, index } = makeState();

test("repeatSummary", () => {
  assert.equal(repeatSummary({ every: 1, unit: "day" }, "en"), "Every day");
  assert.equal(repeatSummary({ every: 2, unit: "week", weekdays: [3, 1] }, "en"), "Every 2 weeks on Tue, Thu");
  assert.equal(repeatSummary({ every: 1, unit: "month", day_of_month: -1 }, "en"), "Every month on the last day");
  assert.equal(repeatSummary({ every: 3, unit: "month", day_of_month: 15 }, "en"), "Every 3 months on day 15");
  assert.equal(repeatSummary({ every: 1, unit: "year" }, "en"), "Every year");
  assert.equal(repeatSummary({}, "en"), "Every day");
});

test("repeatFromDraft only carries the fields of the chosen unit", () => {
  const draft = { ...emptyRecurring(null, new Date(2026, 10, 22)), every: "2", unit: "week", weekdays: [4, 0], dayOfMonth: "9", lastDay: false };
  assert.deepEqual(repeatFromDraft(draft), { every: 2, unit: "week", weekdays: [0, 4] });
  assert.deepEqual(repeatFromDraft({ ...draft, unit: "month", dayOfMonth: "40" }), { every: 2, unit: "month", day_of_month: 31 });
  assert.deepEqual(repeatFromDraft({ ...draft, unit: "month", lastDay: true }), { every: 2, unit: "month", day_of_month: -1 });
  assert.deepEqual(repeatFromDraft({ ...draft, unit: "year", every: 0 }), { every: 1, unit: "year" });
});

test("recurringParams validates and uses issue_type on the wire", () => {
  const draft = emptyRecurring(null, new Date(2026, 10, 22));
  assert.equal(recurringParams(draft).error, "recurring.error_summary");
  draft.summary = " Bins ";
  draft.type = "bug";
  const { params } = recurringParams({ ...draft, nextDue: "" });
  assert.equal(params, undefined);
  const ok = recurringParams(draft).params;
  assert.equal(ok.summary, "Bins");
  assert.equal(ok.issue_type, "bug");
  assert.equal("type" in ok, false);
  assert.equal(ok.next_due, "2026-11-22");
  assert.equal(ok.status, null);
});

test("draftFromRecurring round-trips through recurringParams", () => {
  const chore = payload.recurring.find((r) => r.summary === "Put out the bins");
  const { params } = recurringParams(draftFromRecurring(chore));
  assert.deepEqual(params.repeat, chore.repeat);
  assert.equal(params.next_due, chore.next_due);
  assert.equal(params.issue_type, chore.type);
  const monthly = payload.recurring.find((r) => r.repeat.unit === "month");
  assert.deepEqual(recurringParams(draftFromRecurring(monthly)).params.repeat, monthly.repeat);
});

test("describeActivity", () => {
  assert.equal(describeActivity({ kind: "moved", from: "To do", to: "Done" }, index), "moved it from To do to Done");
  assert.equal(describeActivity({ kind: "updated", field: "priority", from: "medium", to: "high" }, index), "changed Priority from Medium to High");
  assert.equal(describeActivity({ kind: "assigned", field: "assignee", from: null, to: "person.joachim" }, index), "changed the assignee from none to Joachim");
  assert.equal(describeActivity({ kind: "created" }, index), "created the issue");
});
