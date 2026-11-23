// Habits for the harness backend (PROTOCOL section 12): the demo ideas, the created list and the three
// `habits/*` commands. DOM free, used by the browser harness and the node tests.
//
// The ideas are ordinary suggestions of kind `automation` in `backend.suggestions`, so `insights/get`,
// `insights/dismiss` and `settings.insights_open` need no special code. Slow calls (create 1 s, scan 1.5 s)
// are set up by the harness page through `mock.extraLatency`; here everything answers at once.

const CREATED_MAX = 20;

function fail(code, message) {
  const error = new Error(message);
  error.code = code;
  throw error;
}

/** `new MockBackend().habits`. */
export function newHabitsState() {
  return {
    last_scan: null,
    scanned_entities: 120,
    days: 28,
    error: null, // what `learned.habits.error` says
    created: [], // newest first
    fail: null, // harness switch: create and undo fail with this code
    scanError: null, // harness switch: the scan answers with this `error` (no_recorder, no_history, failed)
    nextIdeas: [], // what the next scans find, one idea per scan
  };
}

const HALL_YAML = `alias: Hall light on at 06:35 (weekdays)
description: Suggested by Homeboard from habits. Created switched off.
triggers:
  - trigger: time
    at: "06:35:00"
conditions:
  - condition: time
    weekday:
      - mon
      - tue
      - wed
      - thu
      - fri
actions:
  - action: light.turn_on
    target:
      entity_id: light.hall
mode: single
`;

const FOLLOW_YAML = `alias: Hall light on when the hall motion sensor sees someone
description: Suggested by Homeboard from habits. Created switched off.
triggers:
  - trigger: state
    entity_id: binary_sensor.hall_motion
    to: "on"
actions:
  - action: light.turn_on
    target:
      entity_id: light.hall
mode: single
`;

const BACK_YAML = `alias: Hall light off 4 minutes after the motion stopped
description: Suggested by Homeboard from habits. Created switched off.
triggers:
  - trigger: state
    entity_id: binary_sensor.hall_motion
    to: "off"
    for: "00:04:00"
actions:
  - action: light.turn_off
    target:
      entity_id: light.hall
mode: restart
`;

const FAN_YAML = `alias: Kitchen fan off at 21:15 (every day)
description: Suggested by Homeboard from habits. Created switched off.
triggers:
  - trigger: time
    at: "21:15:00"
actions:
  - action: fan.turn_off
    target:
      entity_id: fan.kitchen
mode: single
`;

const TV_YAML = `alias: Living room lamp off 30 minutes after the TV went off
description: Suggested by Homeboard from habits. Created switched off.
triggers:
  - trigger: state
    entity_id: switch.living_room_tv_plug
    to: "off"
    for: "00:30:00"
actions:
  - action: light.turn_off
    target:
      entity_id: light.living_room_lamp
mode: single
`;

const idea = (id, title, detail, evidence, proposal) => ({ id, kind: "automation", title, detail, evidence, proposal: { description: "Suggested by Homeboard from habits. Created switched off.", trigger_entity: null, ...proposal } });

/** The three demo ideas of the seed (a routine, a follow-up, a switch back). */
export function seedIdeas() {
  return [
    idea(
      "habit:time:light.hall:on:weekdays",
      "Turn on Hall light at 06:35 on weekdays?",
      "It turned on on 17 of the last 21 weekdays between 06:28 and 06:42 (assuming no automation did it).",
      { pattern: "routine", days: 17, of: 21, share: 0.81, window: ["06:28", "06:42"], samples: 17 },
      { alias: "Hall light on at 06:35 (weekdays)", entity_id: "light.hall", yaml: HALL_YAML },
    ),
    idea(
      "habit:follow:binary_sensor.hall_motion:light.hall",
      "When the hall motion sensor sees someone, turn on the Hall light?",
      "The Hall light turned on within a minute of the motion sensor in 12 of 14 cases (assuming no automation did it).",
      { pattern: "follow_up", days: 9, of: 11, share: 0.86, samples: 14 },
      { alias: "Hall light on when the hall motion sensor sees someone", entity_id: "light.hall", trigger_entity: "binary_sensor.hall_motion", yaml: FOLLOW_YAML },
    ),
    idea(
      "habit:back:binary_sensor.hall_motion:light.hall",
      "Turn the Hall light off 4 minutes after the motion has stopped?",
      "The Hall light turned off 1 to 15 minutes after the motion stopped in 8 of 10 cases, typically after 4 minutes (assuming no automation did it).",
      { pattern: "switch_back", days: 8, of: 10, share: 0.8, delay_minutes: 4, samples: 18 },
      { alias: "Hall light off 4 minutes after the motion stopped", entity_id: "light.hall", trigger_entity: "binary_sensor.hall_motion", yaml: BACK_YAML },
    ),
  ];
}

/** Found by the next scans, one per scan. The second one has a pattern the UI does not know. */
function laterIdeas() {
  return [
    idea(
      "habit:time:fan.kitchen:off:daily",
      "Turn off Kitchen fan at 21:15 every day?",
      "It turned off on 5 of the last 7 days between 21:08 and 21:22 (assuming no automation did it).",
      { pattern: "routine", days: 5, of: 7, share: 0.71, window: ["21:08", "21:22"], samples: 5 },
      { alias: "Kitchen fan off at 21:15 (every day)", entity_id: "fan.kitchen", yaml: FAN_YAML },
    ),
    idea(
      "habit:wind_down:light.living_room_lamp:switch.living_room_tv_plug",
      "Turn off the Living room lamp 30 minutes after the TV plug went off?",
      "A pattern from a newer Homeboard that this screen does not know by name.",
      { pattern: "wind_down", days: 6, of: 8, share: 0.75, samples: 6 },
      { alias: "Living room lamp off 30 minutes after the TV went off", entity_id: "light.living_room_lamp", trigger_entity: "switch.living_room_tv_plug", yaml: TV_YAML },
    ),
  ];
}

/** Seed: the habits state with one created and one undone record, and three open ideas. */
export function seedHabits(backend) {
  const habits = backend.habits;
  const record = (fields) => ({ id: backend.id("hab"), suggestion_id: "", auto_id: "", entity_id: "", alias: "", ts: backend.stamp(), state: "created", edit_url: "", ...fields });
  const make = (autoId, slug, alias, offsetMs, state) =>
    record({ suggestion_id: `habit:${slug}`, auto_id: autoId, entity_id: `automation.${slug}`, alias, ts: backend.stamp(offsetMs), state, edit_url: `/config/automation/edit/${autoId}` });
  habits.created = [
    make("1732380000123", "kitchen_light_off_at_2310_every_day", "Kitchen light off at 23:10 (every day)", -3 * 3600000, "created"),
    make("1732100000456", "porch_light_on_at_1730_weekends", "Porch light on at 17:30 (weekends)", -2 * 86400000, "undone"),
  ];
  habits.last_scan = backend.stamp(-4 * 3600000);
  habits.nextIdeas = laterIdeas();
  backend.suggestions.push(...seedIdeas());
}

/** `learned.habits` (only while the feature is on). */
export function habitsLearned(backend) {
  const { last_scan, scanned_entities, days, error, created } = backend.habits;
  return { last_scan, scanned_entities, days, error, created: structuredClone(created.slice(0, CREATED_MAX)) };
}

/** Forgetting `habits` clears the cached ideas and the dismissed ones, not what was created. */
export function forgetHabits(backend) {
  const ids = new Set(backend.suggestions.filter((s) => s.kind === "automation").map((s) => s.id));
  backend.suggestions = backend.suggestions.filter((s) => !ids.has(s.id));
  for (const id of ids) backend.handled.delete(id);
  backend.habits.nextIdeas = [];
}

// ---- commands -------------------------------------------------------------------------------------------

const FAIL_MESSAGES = {
  exists: "An automation already switches light.hall, so Homeboard will not add another one.",
  blocked: "The proposed automation was rejected by validation: unknown service light.turn_onn.",
  not_editable: "automations.yaml uses !include, so Homeboard will not write to it.",
  create_failed: "The automation did not load after the reload and was rolled back from the backup.",
  habits_disabled: "Habit ideas are switched off in the Homeboard options.",
  stale: "The automation was edited after Homeboard created it.",
  backup_missing: "The backup homeboard_backups/automations-20261123-0635.yaml is missing.",
  not_found: "That record does not exist.",
};

function enabled(backend) {
  if (!backend.settings.learning.habits) fail("habits_disabled", FAIL_MESSAGES.habits_disabled);
}

function simulated(backend) {
  const code = backend.habits.fail;
  if (code) fail(code, FAIL_MESSAGES[code] || "Something odd happened inside Home Assistant (harness switch).");
}

const slug = (text) => String(text).toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");

export const HABITS_COMMANDS = {
  "habits/scan"() {
    enabled(this);
    const state = this.habits;
    if (state.scanError) {
      state.error = state.scanError;
      return { scanned: 0, found: 0, days: state.scanError === "no_history" ? 3 : 0, error: state.scanError };
    }
    const taken = new Set([...this.suggestions.map((s) => s.id), ...state.created.map((c) => c.suggestion_id)]);
    const fresh = state.nextIdeas.find((s) => !taken.has(s.id));
    state.nextIdeas = state.nextIdeas.filter((s) => s !== fresh);
    if (fresh) this.suggestions.push(structuredClone(fresh));
    Object.assign(state, { last_scan: this.stamp(), error: null });
    this.changed();
    return { scanned: state.scanned_entities, found: fresh ? 1 : 0, days: state.days, error: null };
  },

  "habits/create"({ suggestion_id }) {
    enabled(this);
    simulated(this);
    const suggestion = this.openSuggestions().find((s) => s.kind === "automation" && s.id === suggestion_id) || fail("not_found", `Suggestion ${suggestion_id} not found`);
    const autoId = String(1732400000000 + this.counter * 7919);
    const alias = suggestion.proposal.alias;
    const record = {
      id: this.id("hab"), suggestion_id, auto_id: autoId, entity_id: `automation.${slug(alias)}`, alias, ts: this.stamp(), state: "created", edit_url: `/config/automation/edit/${autoId}`,
    };
    this.habits.created = [record, ...this.habits.created].slice(0, CREATED_MAX);
    this.handled.add(suggestion.id);
    this.changed();
    return { created: structuredClone(record) };
  },

  "habits/undo"({ created_id }) {
    enabled(this);
    simulated(this);
    const record = this.habits.created.find((c) => c.id === created_id) || fail("not_found", `Record ${created_id} not found`);
    if (record.state !== "created") fail("not_found", "That automation was already removed.");
    record.state = "undone";
    this.changed();
    return { created: structuredClone(record) };
  },
};
