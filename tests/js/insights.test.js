import assert from "node:assert/strict";
import { test } from "node:test";
import { setLanguage } from "../../custom_components/homeboard/static/i18n.js";
import {
  FEATURES,
  averageBars,
  enabledFeatures,
  evidenceText,
  formatDays,
  formatMinutes,
  heatPercent,
  learningEnabled,
  normaliseGrid,
  personIssueBars,
  scaleBars,
  topLabelBars,
  workloadRows,
} from "../../custom_components/homeboard/static/insights.js";
import { makeBackend, makeState } from "./fixtures.js";

setLanguage("en");
const run = (backend, command, params = {}) => backend.handle({ type: `homeboard/${command}`, ...params });

test("learning switches decide whether the tab exists", () => {
  assert.equal(learningEnabled(undefined), false);
  assert.equal(learningEnabled({}), false);
  assert.equal(learningEnabled({ learning: { defaults: false, rhythm: false } }), false);
  assert.equal(learningEnabled({ learning: { defaults: false, rhythm: true } }), true);
  assert.deepEqual(enabledFeatures({ rhythm: true, defaults: true, bogus: true }), ["defaults", "rhythm"]);
  assert.deepEqual(FEATURES, ["defaults", "patterns", "workload", "health", "rhythm"]);
});

test("heat-map colour scale clamps, rounds and is monotonic", () => {
  assert.equal(heatPercent(0), 0);
  assert.equal(heatPercent(1), 100);
  assert.equal(heatPercent(0.5), 50);
  assert.equal(heatPercent(0.456), 46);
  assert.equal(heatPercent(-3), 0);
  assert.equal(heatPercent(7), 100);
  assert.equal(heatPercent("x"), 0);
  assert.equal(heatPercent(undefined), 0);
  let last = -1;
  for (let v = 0; v <= 1.0001; v += 0.01) {
    const percent = heatPercent(v);
    assert.ok(percent >= last);
    last = percent;
  }
});

test("normaliseGrid always yields 7 rows of 24 numbers", () => {
  const grid = normaliseGrid([[0.5, "0.25"], null, [1]]);
  assert.equal(grid.length, 7);
  assert.ok(grid.every((row) => row.length === 24));
  assert.deepEqual(grid[0].slice(0, 3), [0.5, 0.25, 0]);
  assert.deepEqual(grid[1], Array(24).fill(0));
  assert.equal(normaliseGrid(undefined).flat().length, 168);
});

test("evidenceText explains each suggestion kind in words", () => {
  assert.equal(evidenceText("recurring", { count: 4, interval_days: 42 }), "Created 4 times, about every 42 days");
  assert.equal(evidenceText("recurring", { count: 3 }), "Created 3 times");
  assert.equal(evidenceText("health_ignore", { reopened: 3 }), "Came back 3 times");
  assert.equal(evidenceText("digest_time", { samples: 2016 }), "Based on 2016 samples");
  assert.equal(evidenceText("mystery", { some_value: 5, other: "x" }), "some value: 5, other: x");
  assert.equal(evidenceText("recurring", undefined), "");
});

test("scaleBars scales to the largest value and survives all zeros", () => {
  assert.deepEqual(scaleBars([{ value: 5 }, { value: 10 }, { value: 0 }]).map((b) => b.percent), [50, 100, 0]);
  assert.deepEqual(scaleBars([{ value: 0 }]).map((b) => b.percent), [0]);
  assert.deepEqual(scaleBars([]), []);
  assert.deepEqual(averageBars({ bug: 4.2, story: 6.5, task: 3.1 }).map((b) => b.name), ["story", "bug", "task"]);
  assert.equal(averageBars({ a: 2, b: 4 })[0].percent, 100);
  assert.deepEqual(averageBars(undefined), []);
});

test("insights helpers read the learned structures of PROTOCOL 10.5", () => {
  const backend = makeBackend();
  backend.setSettings({ learning: { rhythm: true } });
  const { learned } = run(backend, "insights/get");
  const { index } = makeState(backend);

  const labels = topLabelBars(learned.defaults);
  assert.ok(labels.length > 1);
  assert.equal(labels[0].percent, 100);
  assert.ok(labels.every((l, i) => !i || labels[i - 1].value >= l.value));
  assert.deepEqual(personIssueBars(learned.defaults, index).map((p) => p.name).sort(), ["Joachim", "Padmaja"]);

  const rows = workloadRows(learned.workload, index);
  assert.deepEqual(rows.map((r) => r.name), ["Joachim", "Padmaja"]);
  assert.ok(rows.every((r) => r.open > 0 && r.done30d > 0 && r.avgDays > 0));

  const grids = Object.values(learned.rhythm.people).map((p) => normaliseGrid(p.grid));
  assert.equal(grids.length, 2);
  assert.ok(grids.flat(2).every((v) => v >= 0 && v <= 1));
  assert.notDeepEqual(grids[0], grids[1]);
});

test("duration formatting uses sensible units and the language", () => {
  assert.equal(formatMinutes(15, "en"), "15 min");
  assert.equal(formatMinutes(190, "en"), "3.2 hr");
  assert.equal(formatMinutes(1500, "en"), "1 day");
  assert.equal(formatMinutes(3000, "en"), "2.1 days");
  assert.equal(formatDays(3.5, "en"), "3.5 days");
  assert.equal(formatDays(null, "en"), "-");
  assert.match(formatDays(3.5, "da"), /3,5/);
});

test("the mock follows PROTOCOL 10.5: suggestions, accept, dismiss, forget", () => {
  const backend = makeBackend();
  const first = run(backend, "insights/get");
  assert.deepEqual(first.features, { defaults: true, patterns: true, workload: true, health: true, rhythm: false });
  assert.deepEqual(first.suggestions.map((s) => s.kind), ["recurring", "health_ignore"]);
  assert.equal(backend.payload().settings.insights_open, 2);
  assert.equal("rhythm" in first.learned, false, "rhythm is absent unless the feature is on");
  assert.equal("patterns" in first.learned, false);
  assert.equal(first.learned.health.tracked_sensors, 812);

  const recurring = first.suggestions[0];
  const before = backend.recurring.size;
  const accepted = run(backend, "insights/accept", { suggestion_id: recurring.id });
  assert.equal(accepted.applied, true);
  assert.ok(accepted.recurring_id);
  assert.equal(backend.recurring.size, before + 1);
  assert.equal(backend.payload().settings.insights_open, 1);

  const ignore = first.suggestions[1];
  assert.deepEqual(run(backend, "insights/dismiss", { suggestion_id: ignore.id }), { dismissed: ignore.id });
  assert.equal(run(backend, "insights/get").suggestions.length, 0);
  assert.throws(() => run(backend, "insights/accept", { suggestion_id: ignore.id }), { code: "not_found" });

  assert.deepEqual(run(backend, "insights/forget", { feature: "workload" }), { forgotten: ["workload"] });
  assert.deepEqual(run(backend, "insights/get").learned.workload, { people: {}, types: {}, labels: {} });
  assert.deepEqual(run(backend, "insights/forget").forgotten, FEATURES);
  assert.equal(run(backend, "insights/get").learned.defaults.issues_analysed, 0);
  assert.throws(() => run(backend, "insights/forget", { feature: "nonsense" }), { code: "invalid_format" });
});

test("forgetting is admin only, and a feature that is switched off hides its suggestions", () => {
  const backend = makeBackend();
  backend.setUser({ is_admin: false });
  assert.throws(() => run(backend, "insights/forget", {}), { code: "unauthorized" });
  assert.ok(run(backend, "insights/get"), "everyone may read");
  backend.setSettings({ learning: { health: false } });
  assert.deepEqual(run(backend, "insights/get").suggestions.map((s) => s.kind), ["recurring"]);
  assert.equal(backend.payload().settings.insights_open, 1);
  assert.equal("health" in run(backend, "insights/get").learned, false);
});
