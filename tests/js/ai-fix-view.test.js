// The AI Fix section rendered with the real vnode renderer into a tiny fake DOM. Main point: everything the
// model or the backend sends is untrusted and must end up as text, never as an element or an attribute.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { after, before, test } from "node:test";
import { aiFixSection, diffView, proposalCard } from "../../custom_components/homeboard/static/ai-fix-view.js";
import { aiChip } from "../../custom_components/homeboard/static/components.js";
import { patch } from "../../custom_components/homeboard/static/dom.js";
import { setLanguage } from "../../custom_components/homeboard/static/i18n.js";
import { buttonLabels, buttonsOf, findAll, hasClass, installDom, newContainer, textOf, walk } from "./dom-shim.js";

let restore;
before(() => {
  restore = installDom();
  setLanguage("en");
});
after(() => restore());

const EVIL = "<img src=x onerror=alert(1)>";
const on = new Proxy({}, { get: () => () => {} });

const proposal = (fields = {}) => ({
  id: "p1", kind: "automation_edit", title: "Point the light at the new sensor", explanation: "The old entity is gone.", risk: "low",
  target: "automation.hallway", target_name: "Hallway light", status: "proposed", blocked: null, warnings: [], steps: [],
  diff: "--- current\n+++ proposed\n@@ -1,2 +1,2 @@\n alias: Hallway\n-  - binary_sensor.old\n+  - binary_sensor.new", new_yaml: "alias: Hallway",
  applied_at: null, undone_at: null, error: null, undoable: false, ...fields,
});

const info = (fields = {}, record = {}) => ({
  enabled: true, ready: true, reason: null, entity: "ai_task.claude_ai_task", entity_name: "Claude AI Task", limit: { used: 3, max: 20 },
  record: { state: "ready", rev: 2, note: "", diagnosis: "The sensor was renamed.", confidence: "high", error: null, sent: { chars: 11800, entities: 14, automations: 1 }, proposals: [proposal()], ...record },
  ...fields,
});

const model = (fields = {}) => ({ info: info(), loadError: null, analysing: false, working: false, busy: null, note: "", noteOpen: false, preview: null, confirming: null, error: null, ...fields });

function render(vnode) {
  const container = newContainer();
  patch(container, vnode);
  return container;
}

const section = (fields, handlers = on) => render(aiFixSection(model(fields), handlers));
const card = (fields, ctx = {}) => render(proposalCard(proposal(fields), { working: false, busy: null, confirming: null, on, ...ctx }));

// ---- untrusted text ------------------------------------------------------------------------------------

test("model text ends up as text, not as elements: an <img onerror> in every field", () => {
  const evil = proposal({ title: EVIL, explanation: EVIL, target_name: EVIL, target: EVIL, warnings: [EVIL], steps: [EVIL], diff: `--- current\n+++ proposed\n@@ -1 +1 @@\n-${EVIL}\n+${EVIL}`, new_yaml: EVIL, error: EVIL, status: "failed" });
  const blocked = proposal({ id: "p2", title: EVIL, blocked: { code: "protected", message: EVIL } });
  const root = section({
    info: info({ entity_name: EVIL }, { diagnosis: EVIL, note: EVIL, error: EVIL, proposals: [evil, blocked] }),
    preview: { data: { prompt: EVIL, chars: 5, entities: 1, automations: 1, redactions: 0 } },
    error: EVIL,
    loadError: EVIL,
  });

  assert.deepEqual(findAll(root, (el) => el.localName === "img"), [], "no <img> element exists");
  const attrs = [];
  walk(root, (n) => {
    if (n.nodeType === 1) for (const [name, value] of n.attributes) attrs.push([name, value]);
  });
  assert.deepEqual(attrs.filter(([name]) => /^on/i.test(name)), [], "no event handler attributes");
  assert.deepEqual(attrs.filter(([, value]) => value.includes("<") || value.includes("onerror")), [], "no attribute carries the payload");
  const texts = [];
  walk(root, (n) => {
    if (n.nodeType === 3 && n.nodeValue.includes(EVIL)) texts.push(n.nodeValue);
  });
  assert.ok(texts.length >= 10, `the payload is shown as plain text in many places (${texts.length})`);
  assert.ok(texts.includes(EVIL), "the title is exactly the raw string in one text node");
});

test("risk, kind, status and confidence never reach a class name or attribute as sent", () => {
  const root = section({
    info: info({}, { confidence: 'high" onmouseover="alert(1)', proposals: [proposal({ risk: 'high" onmouseover="alert(1)', kind: 'x"><img src=x>', status: 'applied" onclick="x', id: 'p"1' })] }),
  });
  assert.deepEqual(findAll(root, (el) => el.localName === "img"), []);
  walk(root, (n) => {
    if (n.nodeType !== 1) return;
    for (const [name, value] of n.attributes) {
      assert.ok(!/^on/i.test(name), name);
      if (name === "class") assert.match(value, /^[\w -]+$/, value);
    }
  });
});

test("the AI Fix modules never build HTML from strings", () => {
  const dir = new URL("../../custom_components/homeboard/static/", import.meta.url);
  for (const file of ["ai-fix.js", "ai-fix-view.js", "ai-fix-section.js"]) {
    const source = readFileSync(new URL(file, dir), "utf8");
    assert.doesNotMatch(source, /innerHTML|outerHTML|insertAdjacentHTML|document\.write|createContextualFragment|\beval\(|new Function/, file);
  }
});

// ---- proposals ---------------------------------------------------------------------------------------------

test("a proposal shows title, risk, kind, target, warnings and the diff", () => {
  const root = card({ warnings: ["Two references change."] });
  const text = textOf(root);
  assert.match(text, /Point the light at the new sensor/);
  assert.match(text, /Low risk/);
  assert.match(text, /Edit automation/);
  assert.match(text, /Target: Hallway light/);
  assert.match(text, /automation\.hallway/);
  assert.match(text, /Two references change\./);
  const lines = findAll(root, (el) => hasClass(el, "dl"));
  assert.deepEqual(lines.map((l) => ["meta", "meta", "hunk", "ctx", "del", "add"].find((k) => hasClass(l, k))), ["meta", "meta", "hunk", "ctx", "del", "add"]);
  assert.equal(findAll(root, (el) => hasClass(el, "risk-low")).length >= 1, true);
  const diff = findAll(root, (el) => hasClass(el, "ai-diff"))[0];
  assert.equal(diff.getAttribute("tabindex"), "0", "the diff scrolls with the keyboard too");
});

test("a proposed change: Apply, Dismiss, Copy YAML", () => {
  assert.deepEqual(buttonLabels(card()), ["Apply", "Dismiss", "Copy YAML"]);
});

test("manual steps: a list, and the button says Add to checklist", () => {
  const root = card({ kind: "manual_steps", diff: "", new_yaml: "", steps: ["Replace the battery.", "Pair it again."] });
  assert.deepEqual(buttonLabels(root), ["Add to checklist", "Dismiss"]);
  const items = findAll(root, (el) => el.localName === "li").map(textOf);
  assert.deepEqual(items, ["Replace the battery.", "Pair it again."]);
  assert.equal(findAll(root, (el) => hasClass(el, "ai-diff")).length, 0);
});

test("a blocked proposal: no Apply, the message in a warning box, Copy YAML stays", () => {
  const root = card({ blocked: { code: "protected", message: "It touches the alarm." } });
  assert.deepEqual(buttonLabels(root), ["Dismiss", "Copy YAML"]);
  const box = findAll(root, (el) => hasClass(el, "ai-blocked"))[0];
  assert.match(textOf(box), /It touches the alarm\./);
  assert.equal(box.getAttribute("role"), "note");
});

test("the confirm row replaces the buttons: question, Confirm, Cancel", () => {
  const root = card({}, { confirming: "p1" });
  assert.deepEqual(buttonLabels(root), ["Confirm", "Cancel"]);
  assert.match(textOf(root), /Apply this change\? A backup is made and you can undo it\./);
  const confirm = buttonsOf(root)[0];
  assert.equal(confirm.getAttribute("data-ai-confirm"), "p1");
  assert.deepEqual(buttonLabels(card({}, { confirming: "p2" })), ["Apply", "Dismiss", "Copy YAML"], "another proposal's confirm row does not leak");
});

test("applied: green line, Undo only when `undoable`", () => {
  const at = new Date(Date.now() - 5 * 60000).toISOString();
  const undoable = card({ status: "applied", applied_at: at, undoable: true });
  assert.deepEqual(buttonLabels(undoable), ["Undo"]);
  assert.ok(findAll(undoable, (el) => hasClass(el, "ai-state") && hasClass(el, "applied")).length === 1);
  assert.match(textOf(undoable), /Applied 5 minutes ago/);
  assert.deepEqual(buttonLabels(card({ status: "applied", applied_at: at, undoable: false, kind: "reload_integration" })), []);
  assert.match(textOf(card({ status: "applied", applied_at: at, kind: "manual_steps", steps: ["x"] })), /Added to the checklist 5 minutes ago/);
});

test("dismissed, undone and failed show a muted state line (failed shows the error)", () => {
  assert.match(textOf(card({ status: "dismissed" })), /Dismissed/);
  assert.match(textOf(card({ status: "undone", undone_at: new Date().toISOString() })), /Undone/);
  assert.deepEqual(buttonLabels(card({ status: "dismissed" })), []);
  const failed = card({ status: "failed", error: "The reload did not bring the automation back." });
  assert.match(textOf(failed), /Failed: The reload did not bring the automation back\./);
  assert.match(textOf(card({ status: "failed", error: null })), /Failed/);
  assert.equal(findAll(card({ status: "dismissed" }), (el) => hasClass(el, "ai-diff")).length, 0, "a dismissed proposal drops its diff");
});

test("while a call runs the buttons are disabled and the pressed one shows a spinner", () => {
  const root = card({}, { working: true, busy: { id: "p1", action: "apply" } });
  const [apply, dismiss, copy] = buttonsOf(root);
  assert.equal(apply.getAttribute("disabled"), "");
  assert.equal(dismiss.getAttribute("disabled"), "");
  assert.equal(copy.getAttribute("disabled"), null, "copying is harmless");
  assert.equal(apply.getAttribute("aria-busy"), "true");
  assert.equal(findAll(apply, (el) => hasClass(el, "mini-spin")).length, 1);
});

test("diff view: empty diff gives nothing, long lines stay inside the scroll box", () => {
  assert.equal(diffView(""), null);
  const root = render(diffView("@@ -1 +1 @@\n+" + "x".repeat(400)));
  const box = findAll(root, (el) => hasClass(el, "ai-diff"))[0];
  assert.equal(box.getAttribute("role"), "region");
  assert.equal(findAll(box, (el) => hasClass(el, "add"))[0].childNodes[0].nodeValue.length, 401);
});

// ---- the section --------------------------------------------------------------------------------------------

test("ready record: diagnosis, confidence, what was sent, then the proposals", () => {
  const root = section();
  const text = textOf(root);
  assert.match(text, /Diagnosis/);
  assert.match(text, /The sensor was renamed\./);
  assert.match(text, /High confidence/);
  assert.match(text, /Sent 11,800 characters about 14 entities and 1 automation to Claude AI Task\./);
  assert.equal(findAll(root, (el) => el.localName === "article").length, 1);
  assert.deepEqual(buttonLabels(root).slice(0, 3), ["Analyse again", "Tell the AI something", "Show what is sent"]);
});

test("no record yet: plain Analyse button, no diagnosis", () => {
  const root = section();
  const none = section({ info: { ...info(), record: null } });
  assert.ok(buttonLabels(root)[0].includes("Analyse again"));
  assert.ok(buttonLabels(none)[0].includes("Analyse with AI"));
  assert.doesNotMatch(textOf(none), /Diagnosis/);
});

test("not ready: a reason in plain words, the Analyse button disabled; unknown reasons never give an empty line", () => {
  const cases = [
    ["limit", /daily limit is reached \(3 of 20 analyses today\)/],
    ["disabled", /switched off in the Homeboard options/],
    ["no_entity", /No AI Task entity was found/],
    ["choose_entity", /Several AI Task entities exist/],
    ["unsupported", /no AI Task support/],
    ["from_the_future", /AI Fix is not ready\./],
    [null, /AI Fix is not ready\./],
  ];
  for (const [reason, pattern] of cases) {
    const root = section({ info: info({ ready: false, reason }, { state: "failed", proposals: [] }) });
    const line = findAll(root, (el) => hasClass(el, "ai-reason"))[0];
    assert.ok(line, String(reason));
    assert.match(textOf(line), pattern);
    assert.equal(buttonsOf(root)[0].getAttribute("disabled"), "", String(reason));
  }
  assert.equal(findAll(section(), (el) => hasClass(el, "ai-reason")).length, 0, "nothing to explain when it is ready");
});

test("running: a spinner and Analysing..., no stale proposals", () => {
  const root = section({ info: info({ ready: false }, { state: "running", proposals: [proposal()] }) });
  assert.match(textOf(findAll(root, (el) => hasClass(el, "ai-running"))[0]), /Analysing\.\.\./);
  const analyse = buttonsOf(root)[0];
  assert.match(textOf(analyse), /Analysing\.\.\./);
  assert.equal(analyse.getAttribute("disabled"), "");
  assert.equal(findAll(root, (el) => el.localName === "article").length, 0);
  assert.equal(findAll(root, (el) => hasClass(el, "ai-reason")).length, 0, "running explains the missing readiness itself");
  assert.equal(findAll(root, (el) => hasClass(el, "ai-status"))[0].getAttribute("aria-live"), "polite");
});

test("failed: the error is shown plainly and the Analyse button works again", () => {
  const root = section({ info: info({}, { state: "failed", error: "The AI did not answer in 60 seconds.", proposals: [] }) });
  assert.match(textOf(findAll(root, (el) => hasClass(el, "ai-failed"))[0]), /The analysis failed: The AI did not answer in 60 seconds\./);
  assert.equal(buttonsOf(root)[0].getAttribute("disabled"), null);
});

test("the Analyse button shows a busy state while the call runs (it can take a minute)", () => {
  const root = section({ analysing: true, working: true });
  const analyse = buttonsOf(root)[0];
  assert.equal(analyse.getAttribute("aria-busy"), "true");
  assert.equal(analyse.getAttribute("disabled"), "");
  assert.match(textOf(analyse), /Analysing\.\.\./);
  assert.equal(findAll(analyse, (el) => hasClass(el, "mini-spin")).length, 1);
});

test("the preview button shows a busy state while the text is built, and the preview once it is there", () => {
  const busy = section({ preview: { loading: true }, working: true });
  const button = buttonsOf(busy)[2];
  assert.equal(button.getAttribute("aria-busy"), "true");
  assert.match(textOf(button), /Building the text\.\.\./);
  assert.equal(findAll(button, (el) => hasClass(el, "mini-spin")).length, 1);

  const shown = section({ preview: { data: { prompt: "line one\nline two", chars: 17, entities: 2, automations: 1, redactions: 2 } } });
  const text = textOf(shown);
  assert.match(text, /Exactly this text is sent to Claude AI Task\. That may be a cloud service/);
  assert.match(text, /17 characters · 2 entities · 1 automation · 2 values masked/);
  assert.equal(textOf(findAll(shown, (el) => el.localName === "pre")[0]), "line one\nline two");
  assert.ok(buttonLabels(shown).includes("Hide what is sent"));
});

test("the note box: collapsed by default, a counter when open", () => {
  assert.equal(findAll(section(), (el) => el.localName === "textarea").length, 0);
  const root = section({ noteOpen: true, note: "hello" });
  const area = findAll(root, (el) => el.localName === "textarea")[0];
  assert.equal(area.getAttribute("maxlength"), "500");
  assert.match(textOf(root), /5 of 500/);
  assert.match(textOf(buttonsOf(section({ note: "hello" }))[1]), /5/, "the toggle hints that a note is typed");
});

test("loading and load errors", () => {
  assert.match(textOf(section({ info: null })), /Loading\.\.\./);
  const failed = section({ info: null, loadError: "Not allowed" });
  assert.match(textOf(failed), /Could not load AI Fix: Not allowed/);
  assert.deepEqual(buttonLabels(failed), ["Try again"]);
});

test("Danish renders too", () => {
  setLanguage("da");
  try {
    const text = textOf(section({ info: info({ ready: false, reason: "choose_entity" }) }));
    assert.match(text, /AI-rettelse/);
    assert.match(text, /Der findes flere AI Task-entiteter/);
    assert.match(textOf(section()), /Sendt 11\.800 tegn om 14 entiteter og 1 automatisering til Claude AI Task\./);
  } finally {
    setLanguage("en");
  }
});

// ---- card chips -----------------------------------------------------------------------------------------------

test("card chip: AI with a tooltip when a proposal waits, AI... while running, nothing otherwise", () => {
  const ready = render(aiChip({ ai: { state: "ready", rev: 2, proposals: 1, applied: 0 } }));
  const chip = findAll(ready, (el) => hasClass(el, "ai"))[0];
  assert.equal(chip.getAttribute("title"), "AI has a fix proposal");
  assert.equal(chip.getAttribute("aria-label"), "AI has a fix proposal");
  assert.equal(textOf(chip).trim(), " ".length ? "AI" : "AI");
  const running = render(aiChip({ ai: { state: "running", rev: 1, proposals: 0, applied: 0 } }));
  assert.match(textOf(running), /AI\.\.\./);
  assert.ok(findAll(running, (el) => hasClass(el, "mini-spin")).length === 1);
  assert.equal(render(aiChip({ ai: { state: "failed", rev: 1, proposals: 0, applied: 0 } })).childNodes.length, 0);
  assert.equal(render(aiChip({})).childNodes.length, 0);
});
