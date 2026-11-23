// Habits (PROTOCOL 12): the pure logic, the translation keys it can produce, the controller behind the
// buttons (with the calls replaced), and the harness backend that stands in for the real one.

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  CREATED_MAX,
  MIN_HISTORY_DAYS,
  canCreate,
  confirmKey,
  createdList,
  createdView,
  errorInfo,
  errorText,
  evidenceParts,
  evidenceText,
  haEditPath,
  habitsState,
  ideaView,
  lastScanError,
  patternInfo,
  scanErrorKey,
  scanOutcome,
  scanOutcomeText,
  splitSuggestions,
  statusLine,
} from "../../custom_components/homeboard/static/habits.js";
import { HabitsSection } from "../../custom_components/homeboard/static/habits-section.js";
import { setLanguage } from "../../custom_components/homeboard/static/i18n.js";
import { ALL_FEATURES, FEATURES, LEARNED_FEATURES, enabledFeatures, learningEnabled } from "../../custom_components/homeboard/static/insights.js";
import da from "../../custom_components/homeboard/static/strings-da.js";
import en from "../../custom_components/homeboard/static/strings-en.js";
import { makeBackend } from "./fixtures.js";

setLanguage("en");

const run = (backend, command, params = {}) => backend.handle({ type: `homeboard/${command}`, ...params });
const codeOf = (fn) => {
  try {
    fn();
  } catch (error) {
    return error.code;
  }
  return null;
};
const NOW = new Date("2026-11-23T12:00:00Z").getTime();

// ---- features and the inbox --------------------------------------------------------------------------------

test("features: on, off, or absent on a 0.3 backend; only administrators create", () => {
  assert.equal(habitsState({ habits: true }), "on");
  assert.equal(habitsState({ habits: false }), "off");
  assert.equal(habitsState({}), "absent");
  assert.equal(habitsState(undefined), "absent");
  assert.equal(habitsState({ habits: "yes" }), "absent", "only a real boolean counts");
  assert.equal(canCreate(true, { habits: true }), true);
  assert.equal(canCreate(false, { habits: true }), false);
  assert.equal(canCreate(true, { habits: false }), false);
  assert.equal(canCreate(true, undefined), false);
});

test("habits is a learning feature: it keeps the Insights tab alive and has its own card", () => {
  assert.deepEqual(FEATURES, ["defaults", "patterns", "workload", "health", "rhythm"], "the 0.2 list is untouched");
  assert.deepEqual(ALL_FEATURES, [...FEATURES, "habits"]);
  assert.ok(LEARNED_FEATURES.includes("habits"));
  assert.equal(learningEnabled({ learning: { habits: true } }), true);
  assert.equal(learningEnabled({ learning: { habits: false, defaults: false } }), false);
  assert.deepEqual(enabledFeatures({ habits: true, rhythm: true }), ["rhythm", "habits"]);
});

test("splitSuggestions: kind automation is the inbox, the rest keeps its order", () => {
  const list = [{ id: "a", kind: "recurring" }, { id: "b", kind: "automation" }, { id: "c", kind: "health_ignore" }, { id: "d", kind: "automation" }, { kind: "automation" }, null];
  const { ideas, others } = splitSuggestions(list);
  assert.deepEqual(ideas.map((s) => s.id), ["b", "d"], "an idea without an id cannot be created or dismissed, so it is not shown");
  assert.deepEqual(others.map((s) => s?.id), ["a", "c", undefined, undefined]);
  assert.deepEqual(splitSuggestions(undefined), { ideas: [], others: [] });
});

// ---- patterns and evidence -----------------------------------------------------------------------------------

test("pattern: a known name picks its icon, an unknown one gets the generic icon and text", () => {
  assert.deepEqual(patternInfo("routine"), { pattern: "routine", icon: "mdi:clock-outline", labelKey: "habits.pattern.routine" });
  assert.equal(patternInfo("follow_up").icon, "mdi:motion-sensor");
  assert.equal(patternInfo("switch_back").icon, "mdi:timer-outline");
  for (const odd of ["wind_down", "", null, undefined, 7, {}, "__proto__", "constructor", "routine\"><img>"]) {
    assert.deepEqual(patternInfo(odd), { pattern: "other", icon: "mdi:auto-fix", labelKey: "habits.pattern.other" }, String(odd));
  }
});

test("evidence text: days of, share as percent, window or delay; nothing assumes 28 days", () => {
  setLanguage("en");
  assert.equal(evidenceText({ pattern: "routine", days: 17, of: 21, share: 0.81, window: ["06:28", "06:42"], samples: 17 }), "On 17 of 21 days (81%), between 06:28 and 06:42");
  assert.equal(evidenceText({ pattern: "routine", days: 5, of: 7, share: 0.714, window: ["21:08", "21:22"] }), "On 5 of 7 days (71%), between 21:08 and 21:22");
  assert.equal(evidenceText({ pattern: "switch_back", days: 8, of: 10, share: 0.8, delay_minutes: 4 }), "On 8 of 10 days (80%), about 4 min after the sensor turned off");
  assert.equal(evidenceText({ pattern: "follow_up", days: 9, of: 11, share: 0.86, samples: 14 }), "On 9 of 11 days (86%)");
  assert.equal(evidenceText({ pattern: "wind_down", days: 6, of: 8, share: 0.75 }), "On 6 of 8 days (75%)", "an unknown pattern gets the generic words");
  assert.equal(evidenceText({ days: 1 }), "On 1 day");
  assert.equal(evidenceText({ days: 4 }), "On 4 days");
  assert.equal(evidenceText({ share: 0.5 }), "50% of the time");
  assert.equal(evidenceText({ samples: 12 }), "Based on 12 samples");
  assert.equal(evidenceText({}), "");
  assert.equal(evidenceText(undefined), "");
  assert.equal(evidenceText("x"), "");
  assert.equal(evidenceText([1, 2]), "");
});

test("evidence text survives odd numbers and a window that is not two strings", () => {
  assert.equal(evidenceText({ days: 3, of: 2 }), "On 3 days", "of < days cannot be 'x of y'");
  assert.equal(evidenceText({ days: "17", of: "21" }), "", "strings are not numbers");
  assert.equal(evidenceText({ days: 3, of: 5, share: 4 }), "On 3 of 5 days (100%)");
  assert.equal(evidenceText({ days: 3, of: 5, share: -1 }), "On 3 of 5 days (0%)");
  assert.equal(evidenceText({ days: 3, of: 5, share: "0.8" }), "On 3 of 5 days");
  assert.equal(evidenceText({ days: 3, of: 5, window: ["06:00"] }), "On 3 of 5 days");
  assert.equal(evidenceText({ days: 3, of: 5, window: [1, 2] }), "On 3 of 5 days");
  assert.equal(evidenceText({ days: 3, of: 5, delay_minutes: -2 }), "On 3 of 5 days");
  assert.deepEqual(evidenceParts({ days: 17, of: 21, share: 0.81 }).lead, { key: "habits.evidence.days_of", vars: { days: 17, of: 21 } });
});

test("evidence in Danish", () => {
  setLanguage("da");
  try {
    assert.equal(evidenceText({ days: 17, of: 21, share: 0.81, window: ["06:28", "06:42"] }), "På 17 af 21 dage (81 %), mellem 06:28 og 06:42");
    assert.match(evidenceText({ days: 8, of: 10, share: 0.8, delay_minutes: 4 }), /cirka 4 min\.? efter, at sensoren slog fra/);
    assert.equal(evidenceText({ days: 1 }), "På 1 dag");
  } finally {
    setLanguage("en");
  }
});

test("ideaView turns everything into strings", () => {
  const view = ideaView({ id: "habit:x", title: "Turn on Hall light?", detail: " It did. ", evidence: { pattern: "routine", days: 2, of: 3 }, proposal: { alias: "Hall", yaml: "alias: Hall\n" } });
  assert.deepEqual(view, { id: "habit:x", title: "Turn on Hall light?", detail: "It did.", pattern: patternInfo("routine"), evidence: "On 2 of 3 days", alias: "Hall", yaml: "alias: Hall\n" });
  const bare = ideaView({ id: "y", title: { a: 1 }, detail: 5, proposal: "nope", evidence: null });
  assert.equal(bare.title, "");
  assert.equal(bare.detail, "5");
  assert.equal(bare.yaml, "");
  assert.equal(bare.evidence, "");
  assert.equal(ideaView(null).id, "");
});

// ---- created automations ----------------------------------------------------------------------------------------

test("the link to Home Assistant is a path on this origin with the documented shape, never anything else", () => {
  assert.equal(haEditPath("/config/automation/edit/1732380000123", "1732380000123"), "/config/automation/edit/1732380000123");
  assert.equal(haEditPath("/config/automation/edit/abc_DEF-1.2", null), "/config/automation/edit/abc_DEF-1.2");
  assert.equal(haEditPath(undefined, "1732380000123"), "/config/automation/edit/1732380000123", "rebuilt from auto_id");
  assert.equal(haEditPath("javascript:alert(1)", "77"), "/config/automation/edit/77");
  assert.equal(haEditPath("https://evil.example/config/automation/edit/1", "77"), "/config/automation/edit/77");
  assert.equal(haEditPath("//evil.example/config/automation/edit/1", "77"), "/config/automation/edit/77");
  assert.equal(haEditPath("/config/automation/edit/1?x=<script>", "77"), "/config/automation/edit/77");
  assert.equal(haEditPath("/config/automation/edit/../../x", "77"), "/config/automation/edit/77");
  assert.equal(haEditPath("javascript:alert(1)", "../../x"), null);
  assert.equal(haEditPath("javascript:alert(1)", '1"><img src=x>'), null);
  assert.equal(haEditPath(null, null), null);
});

test("createdView: created offers Undo and the link, undone and unknown offer nothing", () => {
  const record = { id: "hab1", suggestion_id: "habit:x", auto_id: "123", entity_id: "automation.hall", alias: "Hall light", ts: "2026-11-23T10:00:00+01:00", state: "created", edit_url: "/config/automation/edit/123" };
  assert.deepEqual(createdView(record), { id: "hab1", alias: "Hall light", state: "created", ts: "2026-11-23T10:00:00+01:00", editPath: "/config/automation/edit/123", canUndo: true });
  const undone = createdView({ ...record, state: "undone" });
  assert.deepEqual([undone.state, undone.editPath, undone.canUndo], ["undone", null, false]);
  const strange = createdView({ ...record, state: "removed" });
  assert.deepEqual([strange.state, strange.editPath, strange.canUndo], ["unknown", null, false], "an unknown state never offers Undo");
  assert.equal(createdView({ ...record, alias: "  " }).alias, "automation.hall");
  assert.equal(createdView({ ...record, id: undefined }).canUndo, false, "no id, nothing to undo");
  assert.equal(createdView(null).state, "unknown");
});

test("createdList: newest first, at most 20, junk dropped", () => {
  const rec = (n, ts) => ({ id: `h${n}`, alias: `A${n}`, state: "created", ts, auto_id: String(n) });
  const list = [rec(1, "2026-11-20T10:00:00Z"), rec(2, "2026-11-23T10:00:00Z"), rec(3, "2026-11-21T10:00:00Z"), rec(4, "garbage"), null, "x"];
  assert.deepEqual(createdList(list).map((r) => r.id), ["h2", "h3", "h1", "h4"], "an unreadable time sorts last");
  const many = Array.from({ length: 30 }, (_, n) => rec(n, new Date(NOW - n * 3600000).toISOString()));
  const shown = createdList(many);
  assert.equal(shown.length, CREATED_MAX);
  assert.equal(shown[0].id, "h0");
  assert.deepEqual(createdList(undefined), []);
});

// ---- confirm, errors ----------------------------------------------------------------------------------------------

test("confirm texts", () => {
  assert.equal(confirmKey("create"), "habits.confirm_create");
  assert.equal(confirmKey("undo"), "habits.confirm_undo");
  assert.equal(confirmKey("dismiss"), null);
  assert.equal(confirmKey(undefined), null);
  assert.equal(en["habits.confirm_create"], "Create this automation, switched off? A backup is made and you can undo it.");
  assert.equal(en["habits.confirm_undo"], "Remove this automation again?");
});

test("errors: a fixed title for the known codes, the server's message after it, a generic title for the rest", () => {
  for (const code of ["exists", "blocked", "not_editable", "create_failed", "habits_disabled", "not_found", "backup_missing"]) {
    const info = errorInfo({ code, message: "Because of reasons." });
    assert.equal(info.titleKey, `habits.error.${code}`, code);
    assert.equal(errorText(info), `${en[`habits.error.${code}`]}: Because of reasons.`, code);
  }
  assert.equal(errorText(errorInfo({ code: "blocked", message: "" })), "Homeboard will not create this");
  assert.equal(errorText(errorInfo({ code: "exists", message: "exists" })), "An automation already covers this", "a message that only repeats the code is dropped");
  const unknown = errorInfo({ code: "something_new", message: "The moon is in the wrong phase." });
  assert.equal(unknown.titleKey, "habits.error.generic");
  assert.equal(errorText(unknown), "That did not work: The moon is in the wrong phase.");
  assert.equal(errorText(errorInfo(undefined)), "That did not work");
  assert.equal(errorText(errorInfo({ code: "unauthorized", message: "Only administrators can do that" })), en["error.unauthorized"], "the existing fixed text, not the server's");
});

test("a stale undo shows the fixed text and not the server's message", () => {
  assert.equal(errorText(errorInfo({ code: "stale", message: "Edited at 10:02." })), "It was edited after it was created, so Homeboard will not remove it. Delete it in Home Assistant.");
});

// ---- scan ------------------------------------------------------------------------------------------------------------

test("scan outcome: found, nothing new, or an error with its own text", () => {
  setLanguage("en");
  assert.equal(scanOutcomeText(scanOutcome({ scanned: 120, found: 3, days: 28, error: null })), "Found 3 ideas");
  assert.equal(scanOutcomeText(scanOutcome({ scanned: 120, found: 1, days: 28, error: null })), "Found 1 idea");
  assert.equal(scanOutcomeText(scanOutcome({ scanned: 120, found: 0, days: 28, error: null })), "Nothing new");
  assert.equal(scanOutcomeText(scanOutcome({})), "Nothing new");
  assert.equal(scanOutcomeText(scanOutcome({ found: "many" })), "Nothing new");
  assert.equal(scanOutcomeText(scanOutcome({ error: "no_history", found: 0 })), "Not enough history yet: I need at least 7 days of history");
  assert.equal(MIN_HISTORY_DAYS, 7);
  assert.equal(scanOutcomeText(scanOutcome({ error: "no_recorder" })), "The Home Assistant recorder is not available, so there is no history to read.");
  assert.equal(scanOutcomeText(scanOutcome({ error: "failed" })), "The scan failed.");
  assert.equal(scanOutcomeText(scanOutcome({ error: "from_the_future" })), "The scan failed.", "an unknown error code is still an error, never 'Nothing new'");
  assert.equal(scanOutcome({ error: "no_history", found: 2 }).kind, "error", "an error wins over a count");
  assert.equal(scanErrorKey(null), null);
  assert.equal(scanErrorKey(""), null);
  assert.equal(scanOutcomeText(null), "");
});

test("scan outcome in Danish says 7 days too", () => {
  setLanguage("da");
  try {
    assert.equal(scanOutcomeText(scanOutcome({ error: "no_history" })), "Der er ikke historik nok endnu: jeg skal bruge mindst 7 dages historik");
    assert.equal(scanOutcomeText(scanOutcome({ found: 3 })), "Fandt 3 idéer");
    assert.equal(scanOutcomeText(scanOutcome({ found: 0 })), "Intet nyt");
  } finally {
    setLanguage("en");
  }
});

test("status line: last scan, entities and days of history, whatever the number of days", () => {
  const habits = { last_scan: new Date(NOW - 5 * 60000).toISOString(), scanned_entities: 120, days: 28, error: null };
  assert.equal(statusLine(habits, { now: NOW }), "Last scan 5 minutes ago, 120 entities, 28 days of history");
  assert.equal(statusLine({ ...habits, days: 9, scanned_entities: 1 }, { now: NOW }), "Last scan 5 minutes ago, 1 entity, 9 days of history");
  assert.equal(statusLine({ ...habits, days: 1 }, { now: NOW }), "Last scan 5 minutes ago, 120 entities, 1 day of history");
  assert.equal(statusLine({ last_scan: habits.last_scan }, { now: NOW }), "Last scan 5 minutes ago");
  assert.equal(statusLine({ last_scan: null }, { now: NOW }), "Not scanned yet.");
  assert.equal(statusLine({ last_scan: "garbage" }, { now: NOW }), "Not scanned yet.");
  assert.equal(statusLine(undefined), "Not scanned yet.");
  assert.equal(lastScanError({ error: "no_history" }), "Not enough history yet: I need at least 7 days of history");
  assert.equal(lastScanError({ error: null }), "");
  assert.equal(lastScanError(undefined), "");
  setLanguage("da");
  try {
    assert.equal(statusLine(habits, { now: NOW }), "Sidst scannet for 5 minutter siden, 120 entiteter, 28 dages historik");
  } finally {
    setLanguage("en");
  }
});

// ---- translations ---------------------------------------------------------------------------------------------------

test("every text key the habits modules can produce exists in English and Danish", () => {
  const keys = new Set();
  const add = (key) => key && keys.add(key);
  for (const pattern of ["routine", "follow_up", "switch_back", "x"]) add(patternInfo(pattern).labelKey);
  for (const code of ["exists", "blocked", "not_editable", "create_failed", "habits_disabled", "not_found", "stale", "backup_missing", "other", "unauthorized"]) add(errorInfo({ code }).titleKey);
  for (const code of ["no_recorder", "no_history", "failed", "other"]) add(scanErrorKey(code));
  add(confirmKey("create"));
  add(confirmKey("undo"));
  for (const evidence of [{ days: 1, of: 2, share: 0.5, window: ["a", "b"], delay_minutes: 1 }, { days: 3 }, { share: 0.1 }, { samples: 4 }]) {
    const { lead, extras } = evidenceParts(evidence);
    for (const part of [lead, ...extras].filter(Boolean)) {
      if (part.count == null) add(part.key);
      else for (const suffix of ["_one", "_other"]) add(`${part.key}${suffix}`);
    }
  }
  for (const key of ["habits.confirm_group_create", "habits.confirm_group_undo", "habits.state.created", "habits.state.undone", "habits.n_entities_one", "habits.n_entities_other", "habits.n_history_one", "habits.n_history_other", "habits.scan.found_one", "habits.scan.found_other", "insights.feature.habits", "insights.data.habits", "insights.habits.forget_note", "insights.forget_confirm_habits", "habits.off_body", "habits.off_history", "habits.status.never", "habits.status.line", "habits.status.line_short"]) add(key);
  assert.ok(keys.size > 30);
  for (const key of keys) {
    assert.ok(key in en, `en: ${key}`);
    assert.ok(key in da, `da: ${key}`);
  }
  const habitsKeys = Object.keys(en).filter((k) => k.startsWith("habits."));
  assert.ok(habitsKeys.length > 50);
});

test("the texts the owner asked for are there word for word", () => {
  assert.equal(en["habits.title"], "Inbox: automation ideas");
  assert.equal(da["habits.title"], "Indbakke: idéer til automationer");
  assert.equal(en["habits.off_note"], "It is created switched off. You turn it on in Home Assistant.");
  assert.equal(en["habits.show_yaml"], "Show automation");
  assert.equal(en["habits.copy_yaml"], "Copy YAML");
  assert.equal(en["habits.off_body"], "Habit ideas are switched off. They read how your lights, switches and sensors have been used (only inside Home Assistant) and suggest automations. Switch it on in Settings > Devices & services > Homeboard > Configure > Learning.");
  assert.equal(en["habits.off_history"], "Home Assistant keeps 10 days of history by default; more days (purge_keep_days) give steadier ideas.");
  assert.equal(en["insights.data.habits"].includes("Home Assistant"), true);
});

// ---- the controller behind the buttons ----------------------------------------------------------------------------------

/** A HabitsSection whose calls, toasts and navigation are recorded; `insights` counts refreshes and dismissals. */
function harness({ calls = {} } = {}) {
  const log = { toasts: [], refreshes: 0, renders: 0, dismissed: [], copied: [], navigated: [], called: [] };
  const insights = {
    refresh: async () => {
      log.refreshes += 1;
    },
    dismiss: async (suggestion) => {
      log.dismissed.push(suggestion.id);
    },
  };
  const gate = { release: null };
  const wait = () => new Promise((resolve) => (gate.release = resolve));
  const section = new HabitsSection({
    insights,
    requestRender: () => {
      log.renders += 1;
    },
    deps: {
      actions: {
        habitsCreate: async (id) => (log.called.push(["create", id]), calls.create ? calls.create(id, wait) : { created: { id: "hab9", alias: "Hall light on at 06:35 (weekdays)" } }),
        habitsUndo: async (id) => (log.called.push(["undo", id]), calls.undo ? calls.undo(id, wait) : { created: { id, alias: "Kitchen" } }),
        habitsScan: async () => (log.called.push(["scan"]), calls.scan ? calls.scan(wait) : { scanned: 120, found: 3, days: 28, error: null }),
      },
      toast: (toast) => log.toasts.push(toast),
      copyText: async (text) => (log.copied.push(text), true),
      navigate: (path) => log.navigated.push(path),
    },
  });
  return { section, log, gate };
}

const idea = { id: "habit:x", kind: "automation", title: "Turn on Hall light?", proposal: { alias: "Hall light on at 06:35 (weekdays)" } };
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

test("create: first press only asks, Confirm calls the backend, toasts with the alias and refetches", async () => {
  const { section, log } = harness();
  section.on.askCreate(idea);
  assert.deepEqual(section.confirming, { kind: "create", id: "habit:x" });
  assert.deepEqual(log.called, [], "nothing is created by the first press");
  await section.on.confirmCreate(idea);
  assert.deepEqual(log.called, [["create", "habit:x"]]);
  assert.deepEqual(log.toasts, [{ message: "Created, switched off: Hall light on at 06:35 (weekdays)" }]);
  assert.equal(log.refreshes, 1, "the inbox is refetched, the idea is gone from insights/get");
  assert.equal(section.confirming, null);
  assert.equal(section.busy, null);
});

test("cancel and Escape close the confirm row without calling anything", () => {
  const { section, log } = harness();
  section.on.askCreate(idea);
  section.on.cancel();
  assert.equal(section.confirming, null);
  assert.deepEqual(log.called, []);
});

test("one call at a time: while Create runs, a second Create, Undo, Dismiss and Scan do nothing", async () => {
  let release;
  const { section, log } = harness({ calls: { create: () => new Promise((resolve) => (release = () => resolve({ created: { alias: "Hall" } }))) } });
  const first = section.on.confirmCreate(idea);
  assert.deepEqual(section.busy, { id: "habit:x", action: "create" });
  assert.equal(section.working, true);
  section.on.askCreate({ ...idea, id: "other" });
  assert.equal(section.confirming, null, "no confirm row while busy");
  await section.on.confirmCreate({ ...idea, id: "other" });
  await section.on.confirmUndo({ id: "hab1", alias: "x" });
  await section.on.dismiss({ id: "other" });
  await section.on.scan();
  assert.deepEqual(log.called, [["create", "habit:x"]]);
  assert.deepEqual(log.dismissed, []);
  release();
  await first;
  assert.equal(section.busy, null);
});

test("a failed create: the error stays on that card, as a toast, and the inbox is refetched", async () => {
  const error = Object.assign(new Error("An automation already switches light.hall."), { code: "exists" });
  const { section, log } = harness({ calls: { create: async () => { throw error; } } });
  await section.on.confirmCreate(idea);
  assert.equal(section.errors.get("habit:x"), "An automation already covers this: An automation already switches light.hall.");
  assert.deepEqual(log.toasts, [{ kind: "error", message: "An automation already covers this: An automation already switches light.hall." }]);
  assert.equal(log.refreshes, 1);
  assert.equal(section.busy, null, "the buttons work again");
  section.on.askCreate(idea);
  assert.equal(section.errors.has("habit:x"), false, "asking again clears the old error");
});

test("a failure with a code nobody knows still shows a title and the server's message", async () => {
  const { section } = harness({ calls: { create: async () => { throw Object.assign(new Error("Boom."), { code: "brand_new" }); } } });
  await section.on.confirmCreate(idea);
  assert.equal(section.errors.get("habit:x"), "That did not work: Boom.");
});

test("undo: confirm, call with the created id, toast, refetch; stale keeps the fixed text on the row", async () => {
  const view = { id: "hab1", alias: "Kitchen light off", state: "created" };
  const { section, log } = harness();
  section.on.askUndo(view);
  assert.deepEqual(section.confirming, { kind: "undo", id: "hab1" });
  await section.on.confirmUndo(view);
  assert.deepEqual(log.called, [["undo", "hab1"]]);
  assert.equal(log.toasts[0].message, "Removed again: Kitchen");
  assert.equal(log.refreshes, 1);

  const stale = harness({ calls: { undo: async () => { throw Object.assign(new Error("edited"), { code: "stale" }); } } });
  await stale.section.on.confirmUndo(view);
  assert.equal(stale.section.errors.get("hab1"), "It was edited after it was created, so Homeboard will not remove it. Delete it in Home Assistant.");
  assert.equal(stale.log.toasts[0].kind, "error");
});

test("dismiss goes through the existing insights/dismiss", async () => {
  const { section, log } = harness();
  await section.on.dismiss(idea);
  assert.deepEqual(log.dismissed, ["habit:x"]);
  assert.equal(section.busy, null);
});

test("scan: busy while it runs, then the result text; the inbox is refetched; an error shows inline and as a toast", async () => {
  let release;
  const { section, log } = harness({ calls: { scan: () => new Promise((resolve) => (release = () => resolve({ scanned: 120, found: 3, days: 28, error: null }))) } });
  const running = section.on.scan();
  assert.equal(section.scan.running, true);
  assert.equal(section.working, true);
  release();
  await running;
  assert.equal(section.scan.running, false);
  assert.equal(scanOutcomeText(section.scan.outcome), "Found 3 ideas");
  assert.equal(log.refreshes, 1);

  const none = harness({ calls: { scan: async () => ({ scanned: 120, found: 0, days: 2, error: "no_history" }) } });
  await none.section.on.scan();
  assert.equal(scanOutcomeText(none.section.scan.outcome), "Not enough history yet: I need at least 7 days of history");

  const broken = harness({ calls: { scan: async () => { throw Object.assign(new Error("recorder is busy"), { code: "unauthorized" }); } } });
  await broken.section.on.scan();
  assert.equal(broken.section.scan.error, "Only administrators can do that.");
  assert.equal(broken.log.toasts[0].kind, "error");
  assert.equal(broken.log.refreshes, 1);
});

test("copy and open: the YAML goes to the clipboard; a plain click navigates in this tab, a ctrl-click does not", async () => {
  const { section, log } = harness();
  await section.on.copy("alias: x\n");
  assert.deepEqual(log.copied, ["alias: x\n"]);
  assert.equal(log.toasts[0].message, "YAML copied");
  let prevented = 0;
  const click = (extra = {}) => ({ button: 0, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false, preventDefault: () => (prevented += 1), ...extra });
  section.on.open("/config/automation/edit/1", click());
  assert.deepEqual(log.navigated, ["/config/automation/edit/1"]);
  assert.equal(prevented, 1);
  section.on.open("/config/automation/edit/2", click({ ctrlKey: true }));
  section.on.open("/config/automation/edit/3", click({ metaKey: true }));
  section.on.open("/config/automation/edit/4", click({ button: 1 }));
  assert.deepEqual(log.navigated, ["/config/automation/edit/1"], "the browser handles those as a new tab");
  await tick();
});

// ---- the harness backend follows PROTOCOL 12 -------------------------------------------------------------------------------

test("a backend without habits has no features.habits, no learned.habits, and every habits call is refused", () => {
  const backend = makeBackend();
  const get = run(backend, "insights/get");
  assert.equal("habits" in get.features, false);
  assert.equal("habits" in get.learned, false);
  assert.equal(get.suggestions.some((s) => s.kind === "automation"), false);
  assert.equal(codeOf(() => run(backend, "habits/scan")), "habits_disabled");
  assert.equal(codeOf(() => run(backend, "habits/create", { suggestion_id: "x" })), "habits_disabled");
  assert.equal(codeOf(() => run(backend, "habits/undo", { created_id: "x" })), "habits_disabled");
});

test("seed with habits: feature on, learned.habits, three ideas of the three patterns, the old ones unchanged", () => {
  const backend = makeBackend({ habits: true });
  const get = run(backend, "insights/get");
  assert.equal(get.features.habits, true);
  assert.deepEqual(get.suggestions.map((s) => s.kind), ["recurring", "health_ignore", "automation", "automation", "automation"]);
  assert.deepEqual(get.suggestions.filter((s) => s.kind === "automation").map((s) => s.evidence.pattern), ["routine", "follow_up", "switch_back"]);
  const [routine, , back] = get.suggestions.filter((s) => s.kind === "automation");
  assert.deepEqual(routine.evidence.window, ["06:28", "06:42"]);
  assert.equal(back.evidence.delay_minutes, 4);
  for (const s of get.suggestions.filter((x) => x.kind === "automation")) {
    assert.match(s.proposal.yaml, /^alias: /);
    assert.ok(s.proposal.alias && s.proposal.entity_id);
  }
  const { habits } = get.learned;
  assert.equal(habits.scanned_entities, 120);
  assert.equal(habits.days, 28);
  assert.equal(habits.error, null);
  assert.deepEqual(habits.created.map((c) => c.state), ["created", "undone"]);
  assert.match(habits.created[0].edit_url, /^\/config\/automation\/edit\/\d+$/);
  const payload = backend.payload();
  assert.equal(payload.settings.learning.habits, true);
  assert.equal(payload.settings.insights_open, 5, "the badge counts the ideas too");
});

test("habits/create: the idea leaves the inbox, a created record appears (newest first), the badge drops; accept is refused", () => {
  const backend = makeBackend({ habits: true });
  const idea = run(backend, "insights/get").suggestions.find((s) => s.kind === "automation");
  assert.equal(codeOf(() => run(backend, "insights/accept", { suggestion_id: idea.id })), "use_habits_create");
  const { created } = run(backend, "habits/create", { suggestion_id: idea.id });
  assert.equal(created.state, "created");
  assert.equal(created.alias, idea.proposal.alias);
  assert.equal(created.suggestion_id, idea.id);
  assert.match(created.edit_url, new RegExp(`^/config/automation/edit/${created.auto_id}$`));
  const after = run(backend, "insights/get");
  assert.equal(after.suggestions.some((s) => s.id === idea.id), false);
  assert.equal(after.learned.habits.created[0].id, created.id);
  assert.equal(after.learned.habits.created.length, 3);
  assert.equal(backend.payload().settings.insights_open, 4);
  assert.equal(codeOf(() => run(backend, "habits/create", { suggestion_id: idea.id })), "not_found", "twice is not possible");
});

test("habits/undo flips the state; a second undo and an unknown id are not_found", () => {
  const backend = makeBackend({ habits: true });
  const [first] = run(backend, "insights/get").learned.habits.created;
  assert.equal(run(backend, "habits/undo", { created_id: first.id }).created.state, "undone");
  assert.equal(run(backend, "insights/get").learned.habits.created[0].state, "undone");
  assert.equal(codeOf(() => run(backend, "habits/undo", { created_id: first.id })), "not_found");
  assert.equal(codeOf(() => run(backend, "habits/undo", { created_id: "nope" })), "not_found");
});

test("harness switches make create and undo fail with a chosen code, and the scan answer with an error", () => {
  const backend = makeBackend({ habits: true });
  const idea = run(backend, "insights/get").suggestions.find((s) => s.kind === "automation");
  for (const code of ["exists", "blocked", "not_editable", "create_failed", "stale"]) {
    backend.habits.fail = code;
    assert.equal(codeOf(() => run(backend, "habits/create", { suggestion_id: idea.id })), code);
  }
  backend.habits.fail = "stale";
  assert.equal(codeOf(() => run(backend, "habits/undo", { created_id: run(backend, "insights/get").learned.habits.created[0].id })), "stale");
  assert.equal(run(backend, "insights/get").suggestions.some((s) => s.id === idea.id), true, "a failed create changes nothing");
  backend.habits.fail = null;
  backend.habits.scanError = "no_history";
  const result = run(backend, "habits/scan");
  assert.equal(result.error, "no_history");
  assert.equal(result.found, 0);
  assert.equal(run(backend, "insights/get").learned.habits.error, "no_history");
});

test("habits/scan finds one new idea per scan, then nothing new; the last scan time moves", () => {
  const backend = makeBackend({ habits: true });
  const before = run(backend, "insights/get").suggestions.length;
  const first = run(backend, "habits/scan");
  assert.deepEqual([first.found, first.error, first.days, first.scanned], [1, null, 28, 120]);
  assert.equal(run(backend, "insights/get").suggestions.length, before + 1);
  assert.equal(run(backend, "habits/scan").found, 1);
  const third = run(backend, "habits/scan");
  assert.equal(third.found, 0);
  assert.equal(run(backend, "insights/get").suggestions.length, before + 2);
  assert.ok(run(backend, "insights/get").suggestions.some((s) => s.evidence.pattern === "wind_down"), "one idea has a pattern the UI does not know");
});

test("habits calls are administrator only; reading the inbox is not", () => {
  const backend = makeBackend({ habits: true });
  backend.setUser({ is_admin: false });
  assert.equal(codeOf(() => run(backend, "habits/scan")), "unauthorized");
  assert.equal(codeOf(() => run(backend, "habits/create", { suggestion_id: "x" })), "unauthorized");
  assert.equal(codeOf(() => run(backend, "habits/undo", { created_id: "x" })), "unauthorized");
  assert.equal(run(backend, "insights/get").suggestions.filter((s) => s.kind === "automation").length, 3);
  assert.equal(run(backend, "insights/dismiss", { suggestion_id: run(backend, "insights/get").suggestions.find((s) => s.kind === "automation").id }).dismissed.startsWith("habit:"), true);
});

test("switching habits off hides the ideas and the learned data; forgetting clears ideas, not what was created", () => {
  const backend = makeBackend({ habits: true });
  backend.setSettings({ learning: { habits: false } });
  const off = run(backend, "insights/get");
  assert.equal(off.features.habits, false);
  assert.equal("habits" in off.learned, false);
  assert.equal(off.suggestions.some((s) => s.kind === "automation"), false);
  assert.equal(codeOf(() => run(backend, "habits/scan")), "habits_disabled");
  backend.setSettings({ learning: { habits: true } });
  assert.deepEqual(run(backend, "insights/forget", { feature: "habits" }), { forgotten: ["habits"] });
  const forgotten = run(backend, "insights/get");
  assert.equal(forgotten.suggestions.some((s) => s.kind === "automation"), false);
  assert.equal(forgotten.learned.habits.created.length, 2, "the automations that were created stay");
  assert.deepEqual(run(backend, "insights/forget").forgotten, [...FEATURES, "habits"]);
});
