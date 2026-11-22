import assert from "node:assert/strict";
import { test } from "node:test";
import { setLanguage } from "../../custom_components/homeboard/static/i18n.js";
import { buildChips } from "../../custom_components/homeboard/static/quickadd-chips.js";
import { parseQuickAdd } from "../browser/mock-backend.js";
import { NOW, makeState } from "./fixtures.js";

setLanguage("en");
const { index } = makeState();

test("chips for every parsed field, in a stable order", () => {
  const parsed = { summary: "Fix gate", project: "HOME", type: "bug", priority: "high", assignee: "person.joachim", labels: ["garden", "gate"], due: "2026-11-23", unresolved: ["@nobody"] };
  const chips = buildChips(parsed, { index, now: NOW });
  assert.deepEqual(chips.map((c) => c.kind), ["project", "type", "priority", "assignee", "due", "label", "label", "unresolved"]);
  assert.deepEqual(chips.map((c) => c.text), ["HOME", "Bug", "High", "Joachim", "Tomorrow", "#garden", "#gate", "@nobody"]);
  assert.equal(chips.find((c) => c.kind === "assignee").person, "person.joachim");
  assert.ok(chips.find((c) => c.kind === "priority").icon);
});

test("no chips for a bare summary or nothing", () => {
  assert.deepEqual(buildChips({ summary: "Just text", labels: [] }, { index, now: NOW }), []);
  assert.deepEqual(buildChips(null, { index }), []);
});

test("project may come as id or key; unknown assignee keeps a readable name", () => {
  const home = index.projects[0];
  assert.equal(buildChips({ project: home.id }, { index }).at(0).text, home.key);
  assert.equal(buildChips({ assignee: "person.ghost" }, { index }).at(0).text, "Ghost");
});

test("chips follow the language", () => {
  setLanguage("da");
  assert.equal(buildChips({ type: "bug", priority: "high" }, { index }).map((c) => c.text).join(), "Fejl,Høj");
  setLanguage("en");
});

test("the mock parser (used by the harness) understands the documented grammar", () => {
  const people = [{ entity_id: "person.joachim", name: "Joachim" }, { entity_id: "person.padmaja", name: "Padmaja" }];
  const today = new Date(2026, 10, 22);
  const parse = (text, me = "person.joachim") => parseQuickAdd(text, { people, projectKeys: ["HOME", "FIX"], today, me });
  const full = parse("bug: Fix gate latch @pad !1 #Garden due friday 18:00");
  assert.equal(full.summary, "Fix gate latch");
  assert.equal(full.type, "bug");
  assert.equal(full.assignee, "person.padmaja");
  assert.equal(full.priority, "highest");
  assert.deepEqual(full.labels, ["garden"]);
  assert.match(full.due, /^2026-11-27T18:00:00/);
  assert.equal(parse("HOME: Milk @me due tomorrow").due, "2026-11-23");
  assert.equal(parse("Milk @me").assignee, "person.joachim");
  assert.equal(parse("Milk due mon").due, "2026-11-23");
  assert.equal(parse("Milk due 1/12").due, "2026-12-01");
  assert.equal(parse("Milk due in 3 days").due, "2026-11-25");
  assert.equal(parse("Køb mælk i morgen due i morgen !vigtig").priority, "high");
  assert.deepEqual(parse("Milk @nobody !x").unresolved, ["@nobody", "!x"]);
  assert.throws(() => parse("@joachim !high"), { code: "invalid_format" });
});
