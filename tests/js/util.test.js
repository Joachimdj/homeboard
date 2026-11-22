import assert from "node:assert/strict";
import { test } from "node:test";
import { setLanguage } from "../../custom_components/homeboard/static/i18n.js";
import { clamp, debounce, formatDue, initials, joinDue, labelColor, nameFromEntityId, parseDue, relativeTime, splitDue, todayString } from "../../custom_components/homeboard/static/util.js";

const NOW = new Date(2026, 10, 22, 12, 0, 0);
setLanguage("en");

test("relativeTime: seconds, minutes, hours, days, then a date", () => {
  const ago = (ms) => new Date(NOW.getTime() - ms).toISOString();
  assert.equal(relativeTime(ago(10_000), { now: NOW, locale: "en" }), "now");
  assert.equal(relativeTime(ago(5 * 60_000), { now: NOW, locale: "en" }), "5 minutes ago");
  assert.equal(relativeTime(ago(3 * 3600_000), { now: NOW, locale: "en" }), "3 hours ago");
  assert.equal(relativeTime(ago(86400_000), { now: NOW, locale: "en" }), "yesterday");
  assert.equal(relativeTime(ago(4 * 86400_000), { now: NOW, locale: "en" }), "4 days ago");
  assert.equal(relativeTime(ago(20 * 86400_000), { now: NOW, locale: "en-GB" }), "2 Nov");
  assert.equal(relativeTime(ago(400 * 86400_000), { now: NOW, locale: "en-GB" }), "18 Oct 2025");
  assert.equal(relativeTime(null, { now: NOW }), "");
  assert.equal(relativeTime("garbage", { now: NOW }), "");
});

test("relativeTime speaks Danish", () => {
  const then = new Date(NOW.getTime() - 5 * 60_000).toISOString();
  assert.equal(relativeTime(then, { now: NOW, locale: "da" }), "for 5 minutter siden");
});

test("formatDue: relative days, weekday, date, time", () => {
  const opts = { now: NOW, locale: "en-GB" };
  assert.equal(formatDue("2026-11-22", opts), "Today");
  assert.equal(formatDue("2026-11-23", opts), "Tomorrow");
  assert.equal(formatDue("2026-11-21", opts), "Yesterday");
  assert.equal(formatDue("2026-11-25", opts), "Wed");
  assert.equal(formatDue("2026-12-24", opts), "24 Dec");
  assert.equal(formatDue("2027-01-05", opts), "5 Jan 2027");
  assert.equal(formatDue("2026-11-23T18:30:00+01:00", opts).startsWith("Tomorrow"), true);
  assert.equal(formatDue(null, opts), "");
  assert.equal(formatDue("2026-11-22", { now: NOW, locale: "da" }), "I dag");
});

test("due values split into form fields and join back", () => {
  assert.deepEqual(splitDue("2026-11-30"), { date: "2026-11-30", time: "" });
  assert.deepEqual(splitDue(null), { date: "", time: "" });
  assert.equal(joinDue("2026-11-30", ""), "2026-11-30");
  assert.equal(joinDue("", "12:00"), null);
  const dt = joinDue("2026-11-30", "18:05");
  assert.match(dt, /^2026-11-30T18:05:00[+-]\d\d:\d\d$/);
  assert.deepEqual(splitDue(dt), { date: "2026-11-30", time: "18:05" });
});

test("parseDue treats date-only strings as local midnight", () => {
  const d = parseDue("2026-11-30");
  assert.equal(d.getHours(), 0);
  assert.equal(d.getDate(), 30);
  assert.equal(parseDue("nope"), null);
  assert.equal(todayString(NOW), "2026-11-22");
});

test("small helpers", () => {
  assert.equal(initials("Joachim Dittman"), "JD");
  assert.equal(initials("padmaja"), "PA");
  assert.equal(initials(""), "?");
  assert.equal(nameFromEntityId("person.joachim_d"), "Joachim D");
  assert.equal(labelColor("Garden"), labelColor("garden"));
  assert.notEqual(labelColor("garden"), labelColor("car"));
  assert.equal(clamp(5, 0, 3), 3);
});

test("debounce collapses calls and can be cancelled", async () => {
  let calls = [];
  const fn = debounce((x) => calls.push(x), 10);
  fn(1);
  fn(2);
  await new Promise((r) => setTimeout(r, 30));
  assert.deepEqual(calls, [2]);
  fn(3);
  fn.cancel();
  await new Promise((r) => setTimeout(r, 30));
  assert.deepEqual(calls, [2]);
});
