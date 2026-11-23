// AI Fix for the harness backend (PROTOCOL section 11): demo records and the six `ai/*` commands.
// DOM free, used by the browser harness and the node tests. The "model" is a canned answer that comes
// back after `backend.ai.delay` ms; `backend.ai.schedule` can be replaced to drive time by hand.

const CONFIG_ENTITY = "ai_task.claude_ai_task";
const NOTE_MAX = 500;
const UNDOABLE = ["automation_edit", "automation_disable"];

function fail(code, message) {
  const error = new Error(message);
  error.code = code;
  throw error;
}

/** `new MockBackend().ai`. */
export function newAiState(today) {
  return {
    fixes: new Map(), // issue id -> record
    usage: { day: today, count: 3 },
    max: 20,
    delay: 1500, // ms until a started analysis is answered
    fail: false, // harness switch: every call fails with ai_unavailable
    reason: null, // harness switch: forces `ai/get`.reason (no_entity, choose_entity, unsupported, limit)
    schedule: (fn, ms) => {
      const timer = setTimeout(fn, ms);
      timer.unref?.();
      return timer;
    },
  };
}

export const defaultAiSettings = () => ({ enabled: true, entity: CONFIG_ENTITY, allow_protected: false });

const undoable = (proposal) => proposal.status === "applied" && UNDOABLE.includes(proposal.kind);

/** What the list payload carries on an issue (administrators only). */
export function aiSummary(record) {
  const count = (status) => record.proposals.filter((p) => p.status === status).length;
  return { state: record.state, rev: record.rev, proposals: count("proposed"), applied: count("applied") };
}

// ---- canned answers --------------------------------------------------------------------------

const HALLWAY_YAML = `alias: Hallway light on motion
description: Night light when someone walks through the hallway
triggers:
  - trigger: state
    entity_id:
      - binary_sensor.hallway_motion_occupancy
    to: "on"
conditions:
  - condition: sun
    after: sunset
actions:
  - action: light.turn_on
    target:
      entity_id: light.hallway
    data:
      brightness_pct: 30
  - wait_for_trigger:
      - trigger: state
        entity_id: binary_sensor.hallway_motion_occupancy
        to: "off"
        for: "00:02:00"
  - action: light.turn_off
    target:
      entity_id: light.hallway
mode: restart
`;

const HALLWAY_DIFF = `--- current
+++ proposed
@@ -3,7 +3,7 @@
 triggers:
   - trigger: state
     entity_id:
-      - binary_sensor.hallway_motion
+      - binary_sensor.hallway_motion_occupancy
     to: "on"
 conditions:
   - condition: sun
@@ -16,7 +16,7 @@
       brightness_pct: 30
   - wait_for_trigger:
       - trigger: state
-        entity_id: binary_sensor.hallway_motion
+        entity_id: binary_sensor.hallway_motion_occupancy
         to: "off"
         for: "00:02:00"
   - action: light.turn_off`;

const ALARM_YAML = `alias: "Alarm: arm when everyone leaves"
description: Arm the alarm 5 minutes after the last person has left
triggers:
  - trigger: state
    entity_id: group.family
    to: not_home
    for: "00:05:00"
conditions:
  - condition: state
    entity_id: binary_sensor.hallway_motion_occupancy
    state: "off"
actions:
  - action: alarm_control_panel.alarm_arm_away
    target:
      entity_id: alarm_control_panel.home_alarm
mode: single
`;

const ALARM_DIFF = `--- current
+++ proposed
@@ -7,7 +7,7 @@
     for: "00:05:00"
 conditions:
   - condition: state
-    entity_id: binary_sensor.hallway_motion
+    entity_id: binary_sensor.hallway_motion_occupancy
     state: "off"
 actions:
   - action: alarm_control_panel.alarm_arm_away`;

function proposal(fields) {
  const result = { status: "proposed", blocked: null, warnings: [], diff: "", new_yaml: "", steps: [], target: null, target_name: null, applied_at: null, undone_at: null, error: null, ...fields };
  result.undoable = undoable(result);
  return result;
}

function hallwayProposals() {
  return [
    proposal({
      id: "p1",
      kind: "automation_edit",
      title: "Point the hallway light at the new motion entity",
      explanation:
        "The trigger and the wait step use binary_sensor.hallway_motion, which no longer exists. After the last Zigbee update the sensor reports as binary_sensor.hallway_motion_occupancy. Changing the two references makes the automation work again. Nothing else changes.",
      risk: "low",
      target: "automation.hallway_light_on_motion",
      target_name: "Hallway light on motion",
      warnings: ["Two references are changed. The new entity has reported every few minutes for the last 3 days."],
      diff: HALLWAY_DIFF,
      new_yaml: HALLWAY_YAML,
    }),
    proposal({
      id: "p2",
      kind: "manual_steps",
      title: "Clean up the old entity and test the light",
      explanation: "The old entity is still in the entity registry and keeps this issue open. Removing it is a click job in the settings.",
      risk: "low",
      steps: [
        "Open Settings > Devices & services > Entities and delete the old, unavailable entity binary_sensor.hallway_motion.",
        "Search your dashboards for the old name and replace it with binary_sensor.hallway_motion_occupancy.",
        "Walk through the hallway after sunset and check that the light turns on and off again.",
      ],
    }),
    proposal({
      id: "p3",
      kind: "automation_edit",
      title: "Update the alarm automation too",
      explanation: "The automation that arms the alarm waits for the same old sensor to be quiet. Without a change the condition never becomes true.",
      risk: "high",
      target: "automation.alarm_arm_when_everyone_leaves",
      target_name: "Alarm: arm when everyone leaves",
      warnings: ["This changes how the alarm is armed. Test it with the siren disconnected."],
      blocked: {
        code: "protected",
        message: "This automation controls alarm_control_panel.home_alarm. Homeboard does not change automations that touch the alarm unless \"allow protected\" is switched on in the options. You can copy the YAML and change it yourself.",
      },
      diff: ALARM_DIFF,
      new_yaml: ALARM_YAML,
    }),
  ];
}

function hueProposals(stamp) {
  return [
    proposal({
      id: "p1",
      kind: "reload_integration",
      title: "Reload the Philips Hue integration",
      explanation: "The bridge answers on the network, so the integration is most likely stuck after the bridge restarted last night. Reloading connects to it again. This is safe and takes a few seconds.",
      risk: "low",
      target: "config_entry.hue",
      target_name: "Philips Hue (Hue Bridge)",
    }),
    proposal({
      id: "p2",
      kind: "automation_disable",
      title: "Turn off the evening scenes until the bridge is back",
      explanation: "The automation tries to activate a Hue scene every 5 minutes and fails each time, which fills the log.",
      risk: "medium",
      target: "automation.evening_scenes",
      target_name: "Evening scenes",
      status: "applied",
      applied_at: stamp(-25 * 60000),
    }),
  ];
}

function genericProposals(issue) {
  return [
    proposal({
      id: "p1",
      kind: "manual_steps",
      title: "Check the device by hand",
      explanation: `Home Assistant only reports the symptom ("${issue.summary}"). The cause is on the device itself, so these steps are for you.`,
      risk: "low",
      steps: ["Look at the device and check that it has power or a good battery.", "If it is a battery device, replace the battery and press the pairing button once.", "Come back here when it reports again: Homeboard closes the issue by itself."],
    }),
  ];
}

const SENT = { chars: 11800, entities: 14, automations: 1 };

/** The answer of the "model" for one issue, as a finished record (without rev / timestamps). */
function cannedResult(backend, issue) {
  const stamp = (ms) => backend.stamp(ms);
  if (issue.dedupe_key === "health:offline:dev-motion") {
    return {
      diagnosis:
        "The hallway motion sensor is not offline: after the last Zigbee update it was re-created as binary_sensor.hallway_motion_occupancy, and the old entity binary_sensor.hallway_motion now shows unavailable. Two automations still use the old name, so the hallway light never turns on.",
      confidence: "high",
      sent: { ...SENT },
      proposals: hallwayProposals(),
    };
  }
  if (issue.dedupe_key === "health:entry:hue") {
    return {
      diagnosis: "Philips Hue could not be set up three times in a row, although the bridge (192.168.1.20) answers on the network. That points to a stuck integration after the bridge restarted last night, not to a broken bridge.",
      confidence: "medium",
      sent: { chars: 8420, entities: 9, automations: 1 },
      proposals: hueProposals(stamp),
    };
  }
  return {
    diagnosis: `Home Assistant reports "${issue.summary}" but nothing in your automations depends on it, so there is nothing to edit. This looks like a hardware problem.`,
    confidence: "low",
    sent: { chars: 4210, entities: 5, automations: 0 },
    proposals: genericProposals(issue),
  };
}

function buildPrompt(issue, note) {
  const lines = [
    "You are an expert in Home Assistant configuration. Answer with exactly one JSON object:",
    '{"diagnosis": "...", "confidence": "low|medium|high", "proposals": [{"kind": "automation_edit|automation_disable|reload_integration|manual_steps", ...}]}',
    "At most 3 proposals. Only use automations and entities listed below. Never invent entity ids.",
    "",
    "## Issue",
    `Key: ${issue.key}`,
    `Title: ${issue.summary}`,
    `Source: ${issue.source} (${issue.dedupe_key || "no key"})`,
    `Labels: ${issue.labels.join(", ") || "-"}`,
    `Description: ${issue.description || "-"}`,
    "",
    "## Home Assistant",
    "Version: 2026.11.1, language: da",
    "",
    "## Device",
    "Hallway motion (Zigbee, last seen 2 days ago)",
    "  binary_sensor.hallway_motion               unavailable  (since 2 days)",
    "  binary_sensor.hallway_motion_occupancy     off          (changed 4 min ago, area: Hallway)",
    "  sensor.hallway_motion_battery              87 %",
    "",
    "## Automations that use these entities",
    "### automation.hallway_light_on_motion (last trace: ok, 0 runs since the entity went missing)",
    ...HALLWAY_YAML.replaceAll("binary_sensor.hallway_motion_occupancy", "binary_sensor.hallway_motion").trimEnd().split("\n"),
    "",
    "### automation.notify_hallway_motion (last trace error: none)",
    "alias: Notify when the hallway moves while we are away",
    "actions:",
    "  - action: rest_command.push_message",
    '    data:',
    '      webhook_id: "<redacted:1>"',
    '      api_key: "<redacted:2>"',
    "",
    "## Candidate replacements for binary_sensor.hallway_motion",
    "  binary_sensor.hallway_motion_occupancy   off   area: Hallway",
    "  binary_sensor.hallway_motion_tamper      off   area: Hallway",
  ];
  if (note) lines.push("", "## Note from the owner", note);
  lines.push("", "(output cut to 24 000 characters if needed)");
  return lines.join("\n");
}

// ---- commands -------------------------------------------------------------------------------------

const ENTITY_NAME = "Claude AI Task";

function recordFor(backend, issueId) {
  backend.issue(issueId);
  return backend.ai.fixes.get(issueId) || null;
}

function guard(backend) {
  if (backend.ai.fail) fail("ai_unavailable", "The AI Task entity is not available right now (harness switch).");
}

function infoFor(backend, issueId) {
  const { ai, settings } = backend;
  const config = settings.ai_fix;
  const record = recordFor(backend, issueId);
  const limitReached = ai.usage.count >= ai.max;
  const reason = !config.enabled ? "disabled" : ai.reason || (limitReached ? "limit" : null);
  const used = reason === "limit" ? ai.max : ai.usage.count;
  return {
    enabled: config.enabled,
    ready: !reason && record?.state !== "running",
    reason,
    entity: config.entity,
    entity_name: config.entity ? ENTITY_NAME : null,
    limit: { used, max: ai.max },
    record: record ? structuredClone(record) : null,
  };
}

function bump(backend, issueId, record) {
  record.rev = (record.rev || 0) + 1;
  backend.ai.fixes.set(issueId, record);
  backend.changed();
}

function finishAnalysis(backend, issueId) {
  const record = backend.ai.fixes.get(issueId);
  const issue = backend.issues.get(issueId);
  if (!record || !issue || record.state !== "running") return;
  Object.assign(record, cannedResult(backend, issue), { state: "ready", finished: backend.stamp(), error: null });
  backend.ai.usage.count += 1;
  bump(backend, issueId, record);
}

function findProposal(backend, issueId, proposalId) {
  const issue = backend.issue(issueId);
  const record = backend.ai.fixes.get(issueId) || fail("not_found", "There is no analysis for this issue");
  const found = record.proposals.find((p) => p.id === proposalId) || fail("not_found", `Proposal ${proposalId} not found`);
  return { issue, record, proposal: found };
}

function addComment(backend, issue, text) {
  backend.issues.get(issue.id)?.comments.push({ id: backend.id("com"), author: backend.user.person, ts: backend.stamp(), text });
  backend.log(issue, "commented");
}

export const AI_COMMANDS = {
  "ai/get"({ issue_id }) {
    guard(this);
    return infoFor(this, issue_id);
  },

  "ai/preview"({ issue_id, note: hint = "" }) {
    guard(this);
    const issue = this.issue(issue_id);
    const prompt = buildPrompt(issue, String(hint).trim());
    return { prompt, chars: prompt.length, entities: 14, automations: 1, redactions: 2 };
  },

  "ai/analyze"({ issue_id, note: hint = "" }) {
    guard(this);
    const issue = this.issue(issue_id);
    const info = infoFor(this, issue_id);
    if (!info.enabled) fail("ai_disabled", "AI Fix is switched off");
    if (info.record?.state === "running") fail("ai_busy", "An analysis is already running for this issue");
    if (info.reason === "limit") fail("ai_limit", "The daily limit of analyses is reached");
    if (info.reason) fail("ai_unavailable", "No AI Task entity is available");
    if (String(hint).length > NOTE_MAX) fail("invalid_format", `note must be at most ${NOTE_MAX} characters`);
    const previous = this.ai.fixes.get(issue_id);
    const record = {
      state: "running", rev: previous?.rev || 0, started: this.stamp(), finished: null, entity: this.settings.ai_fix.entity,
      note: String(hint).trim(), diagnosis: "", confidence: null, error: null, sent: null, proposals: [],
    };
    bump(this, issue_id, record);
    this.ai.schedule(() => finishAnalysis(this, issue_id), this.ai.delay);
    return { state: "running" };
  },

  "ai/apply"({ issue_id, proposal_id }) {
    guard(this);
    const { issue, record, proposal: p } = findProposal(this, issue_id, proposal_id);
    if (p.blocked) fail("blocked", `Not applied (${p.blocked.code}): ${p.blocked.message}`);
    if (p.status !== "proposed") fail("conflict", "This proposal was already handled");
    p.status = "applied";
    p.applied_at = this.stamp();
    p.error = null;
    p.undoable = undoable(p);
    if (p.kind === "manual_steps") {
      for (const step of p.steps) issue.checklist.push({ id: this.id("chk"), text: step.slice(0, 200), done: false });
      this.log(issue, "updated", "checklist", String(issue.checklist.length - p.steps.length), String(issue.checklist.length));
    }
    addComment(this, issue, `AI Fix applied: ${p.title}`);
    bump(this, issue_id, record);
    return { proposal: structuredClone(p) };
  },

  "ai/undo"({ issue_id, proposal_id }) {
    guard(this);
    const { issue, record, proposal: p } = findProposal(this, issue_id, proposal_id);
    if (!p.undoable) fail("not_applied", "Only an applied automation change can be undone");
    p.status = "undone";
    p.undone_at = this.stamp();
    p.undoable = false;
    addComment(this, issue, `AI Fix undone: ${p.title}`);
    bump(this, issue_id, record);
    return { proposal: structuredClone(p) };
  },

  "ai/dismiss"({ issue_id, proposal_id }) {
    guard(this);
    const { record, proposal: p } = findProposal(this, issue_id, proposal_id);
    if (p.status !== "proposed") fail("conflict", "This proposal was already handled");
    p.status = "dismissed";
    bump(this, issue_id, record);
    return { proposal: structuredClone(p) };
  },
};

// ---- demo data ---------------------------------------------------------------------------------------

/** Records for a few of the FIX issues: ready (hallway, hue), failed (door lock), running (irrigation). */
export function seedAi(backend, issueByKey) {
  const put = (key, record) => {
    const issue = issueByKey(key);
    backend.ai.fixes.set(issue.id, { rev: 1, started: backend.stamp(-12 * 60000), finished: backend.stamp(-11 * 60000), entity: CONFIG_ENTITY, note: "", error: null, ...record });
  };
  const ready = (key) => {
    const issue = issueByKey(key);
    put(key, { state: "ready", ...cannedResult(backend, issue) });
  };
  ready("FIX-2");
  ready("FIX-6");
  put("FIX-1", { state: "failed", finished: backend.stamp(-30 * 60000), diagnosis: "", confidence: null, sent: null, proposals: [], error: "The AI Task entity did not answer within 60 seconds. Try again, or pick a faster model in the Homeboard options." });
  put("FIX-3", { state: "running", finished: null, diagnosis: "", confidence: null, sent: null, proposals: [], started: backend.stamp(-20000) });
}
