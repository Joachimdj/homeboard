// The Habits inbox rendered with the real vnode renderer into a tiny fake DOM. Main point: everything the backend
// sends is untrusted and must end up as text, never as an element, an attribute, a class or a link target.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { after, before, test } from "node:test";
import { patch } from "../../custom_components/homeboard/static/dom.js";
import { createdRow, ideaCard, inboxSection } from "../../custom_components/homeboard/static/habits-view.js";
import { createdList } from "../../custom_components/homeboard/static/habits.js";
import { setLanguage } from "../../custom_components/homeboard/static/i18n.js";
import { renderInsights } from "../../custom_components/homeboard/static/insights-view.js";
import { buttonLabels, buttonsOf, findAll, hasClass, installDom, newContainer, textOf, walk } from "./dom-shim.js";
import { makeBackend, makeState } from "./fixtures.js";

let restore;
before(() => {
  restore = installDom();
  setLanguage("en");
});
after(() => restore());

const EVIL = "<img src=x onerror=alert(1)>";
const on = new Proxy({}, { get: () => () => {} });
const HOUR = 3600000;

const render = (vnode) => {
  const container = newContainer();
  patch(container, vnode);
  return container;
};

const idea = (fields = {}) => ({
  id: "habit:time:light.hall:on:weekdays", kind: "automation", title: "Turn on Hall light at 06:35 on weekdays?",
  detail: "It turned on on 17 of the last 21 weekdays between 06:28 and 06:42 (assuming no automation did it).",
  evidence: { pattern: "routine", days: 17, of: 21, share: 0.81, window: ["06:28", "06:42"], samples: 17 },
  proposal: { alias: "Hall light on at 06:35 (weekdays)", entity_id: "light.hall", yaml: "alias: Hall light on at 06:35 (weekdays)\ntriggers:\n  - trigger: time\n    at: \"06:35:00\"\n" },
  ...fields,
});

const created = (fields = {}) => ({
  id: "hab1", suggestion_id: "habit:x", auto_id: "1732380000123", entity_id: "automation.kitchen", alias: "Kitchen light off at 23:10 (every day)",
  ts: new Date(Date.now() - 3 * HOUR).toISOString(), state: "created", edit_url: "/config/automation/edit/1732380000123", ...fields,
});

const habitsData = (fields = {}) => ({ last_scan: new Date(Date.now() - 4 * HOUR).toISOString(), scanned_entities: 120, days: 28, error: null, created: [created(), created({ id: "hab2", state: "undone", alias: "Porch light", ts: new Date(Date.now() - 50 * HOUR).toISOString() })], ...fields });

const model = (fields = {}) => ({
  features: { habits: true }, habits: habitsData(), ideas: [idea(), idea({ id: "b", title: "Second", evidence: { pattern: "follow_up", days: 9, of: 11, share: 0.86 } })], isAdmin: true,
  working: false, busy: null, confirming: null, errors: new Map(), scan: { running: false, outcome: null, error: null }, ...fields,
});

const section = (fields, handlers = on) => render(inboxSection(model(fields), handlers));
const card = (suggestion = idea(), ctx = {}) => render(ideaCard(suggestion, { canCreate: true, working: false, busy: null, confirming: null, errors: new Map(), on, ...ctx }));
const row = (record = created(), ctx = {}) => render(createdRow(createdList([record])[0], { canManage: true, working: false, busy: null, confirming: null, errors: new Map(), on, ...ctx }));

// ---- untrusted text ------------------------------------------------------------------------------------------

test("backend text ends up as text, not as elements: an <img onerror> in title, detail, yaml, alias, messages and ids", () => {
  const evil = idea({ id: EVIL, title: EVIL, detail: EVIL, evidence: { pattern: EVIL, days: 1, of: 2, window: [EVIL, EVIL] }, proposal: { alias: EVIL, entity_id: EVIL, yaml: `alias: ${EVIL}\n${EVIL}` } });
  const record = created({ id: EVIL, alias: EVIL, entity_id: EVIL, auto_id: EVIL, edit_url: EVIL, state: EVIL });
  const open = created({ id: "ok", alias: EVIL, auto_id: "5", edit_url: `/config/automation/edit/5?x=${EVIL}` });
  const root = section({
    ideas: [evil],
    habits: habitsData({ created: [record, open], error: EVIL }),
    errors: new Map([[EVIL, EVIL], ["ok", `Homeboard will not create this: ${EVIL}`]]),
    scan: { running: false, outcome: null, error: `The scan failed: ${EVIL}` },
  });

  assert.deepEqual(findAll(root, (el) => el.localName === "img"), [], "no <img> element exists");
  const attrs = [];
  walk(root, (n) => {
    if (n.nodeType === 1) for (const [name, value] of n.attributes) attrs.push([name, value]);
  });
  assert.deepEqual(attrs.filter(([name]) => /^on/i.test(name)), [], "no event handler attributes");
  // An id is also an inert `data-*` attribute (set with setAttribute, so it is never parsed); nothing live may carry text.
  assert.deepEqual(attrs.filter(([name, value]) => !name.startsWith("data-") && (value.includes("<") || value.includes("onerror"))), [], "no href, class, style or other attribute carries the payload");
  assert.ok(attrs.every(([name, value]) => name.startsWith("data-") || !value.includes(EVIL)));
  const texts = [];
  walk(root, (n) => {
    if (n.nodeType === 3 && n.nodeValue.includes(EVIL)) texts.push(n.nodeValue);
  });
  assert.ok(texts.length >= 5, `the payload is shown as plain text in several places (${texts.length})`);
  assert.ok(texts.includes(EVIL), "the title is exactly the raw string in one text node");

  const pre = findAll(root, (el) => el.localName === "pre")[0];
  assert.equal(pre.childNodes.length, 1, "the YAML is one text node");
  assert.equal(pre.childNodes[0].nodeType, 3);
  assert.equal(pre.childNodes[0].nodeValue, `alias: ${EVIL}\n${EVIL}`);
});

test("a backend-sent edit_url never becomes a link target unless it has the documented shape", () => {
  const links = (url, autoId) => findAll(row(created({ edit_url: url, auto_id: autoId })), (el) => el.localName === "a").map((a) => a.getAttribute("href"));
  assert.deepEqual(links("/config/automation/edit/1732380000123", "1732380000123"), ["/config/automation/edit/1732380000123"]);
  assert.deepEqual(links("javascript:alert(1)", "77"), ["/config/automation/edit/77"]);
  assert.deepEqual(links("https://evil.example/", "77"), ["/config/automation/edit/77"]);
  assert.deepEqual(links("javascript:alert(1)", "x\"><img>"), [], "no safe path, no link");
});

test("pattern, state and error never reach a class name as sent", () => {
  const root = section({
    ideas: [idea({ evidence: { pattern: 'routine" onmouseover="alert(1)', days: 1 } })],
    habits: habitsData({ created: [created({ state: 'created" onclick="x' })] }),
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

test("the Habits modules never build HTML from strings", () => {
  const dir = new URL("../../custom_components/homeboard/static/", import.meta.url);
  for (const file of ["habits.js", "habits-view.js", "habits-section.js", "clipboard.js"]) {
    const source = readFileSync(new URL(file, dir), "utf8");
    assert.doesNotMatch(source, /innerHTML|outerHTML|insertAdjacentHTML|document\.write|createContextualFragment|\beval\(|new Function/, file);
  }
});

// ---- the idea card ---------------------------------------------------------------------------------------------

test("an idea card: title, detail, evidence line, a collapsed YAML block, the switched-off note, Create and Dismiss", () => {
  const root = card();
  const text = textOf(root);
  assert.match(text, /Turn on Hall light at 06:35 on weekdays\?/);
  assert.match(text, /It turned on on 17 of the last 21 weekdays/);
  assert.match(text, /Routine/);
  assert.match(text, /Evidence: On 17 of 21 days \(81%\), between 06:28 and 06:42/);
  assert.match(text, /It is created switched off\. You turn it on in Home Assistant\./);
  const details = findAll(root, (el) => el.localName === "details")[0];
  assert.ok(details, "a details block");
  assert.equal(details.getAttribute("open"), null, "collapsed");
  assert.equal(textOf(findAll(details, (el) => el.localName === "summary")[0]).trim().includes("Show automation"), true);
  const box = findAll(details, (el) => hasClass(el, "yaml-box"))[0];
  assert.equal(box.getAttribute("tabindex"), "0", "scrolls with the keyboard too");
  assert.equal(box.getAttribute("role"), "region");
  assert.match(textOf(findAll(box, (el) => el.localName === "pre")[0]), /^alias: Hall light on at 06:35/);
  assert.ok(buttonLabels(details).includes("Copy YAML"));
  assert.deepEqual(buttonLabels(root).filter((l) => l !== "Copy YAML"), ["Create", "Dismiss"]);
});

test("the icon follows the pattern, an unknown pattern gets the generic icon and label", () => {
  const iconOf = (pattern) => findAll(card(idea({ evidence: { pattern, days: 1, of: 2 } })), (el) => el.localName === "h4")[0].childNodes[0].getAttribute("icon");
  assert.equal(iconOf("routine"), "mdi:clock-outline");
  assert.equal(iconOf("follow_up"), "mdi:motion-sensor");
  assert.equal(iconOf("switch_back"), "mdi:timer-outline");
  assert.equal(iconOf("wind_down"), "mdi:auto-fix");
  assert.match(textOf(card(idea({ evidence: { pattern: "wind_down", days: 6, of: 8, share: 0.75 } }))), /Idea[\s\S]*Evidence: On 6 of 8 days \(75%\)/);
  assert.match(textOf(card(idea({ evidence: { pattern: "switch_back", days: 8, of: 10, share: 0.8, delay_minutes: 4 } }))), /about 4 min after the sensor turned off/);
});

test("no YAML, no details block; no evidence, no evidence line", () => {
  const root = card(idea({ proposal: { alias: "x" }, evidence: {} }));
  assert.equal(findAll(root, (el) => el.localName === "details").length, 0);
  assert.doesNotMatch(textOf(root), /Evidence:/);
});

test("non-administrators see the card and the evidence, and can dismiss, but get no Create button", () => {
  const root = card(idea(), { canCreate: false });
  assert.deepEqual(buttonLabels(root).filter((l) => l !== "Copy YAML"), ["Dismiss"]);
  assert.match(textOf(root), /Evidence:/);
});

test("the confirm row replaces Create and Dismiss: question, Confirm, Cancel, and the right data attribute", () => {
  const root = card(idea(), { confirming: { kind: "create", id: idea().id } });
  assert.match(textOf(root), /Create this automation, switched off\? A backup is made and you can undo it\./);
  const bottom = findAll(root, (el) => hasClass(el, "habit-confirm"))[0];
  assert.deepEqual(buttonLabels(bottom), ["Confirm", "Cancel"]);
  assert.equal(buttonsOf(bottom)[0].getAttribute("data-habit-confirm"), idea().id);
  assert.equal(bottom.getAttribute("role"), "group");
  assert.ok(!buttonLabels(root).includes("Create"));
  assert.deepEqual(buttonLabels(card(idea(), { confirming: { kind: "create", id: "another" } })).filter((l) => l !== "Copy YAML"), ["Create", "Dismiss"], "another card's confirm row does not leak");
  assert.deepEqual(buttonLabels(card(idea(), { confirming: { kind: "undo", id: idea().id } })).filter((l) => l !== "Copy YAML"), ["Create", "Dismiss"], "nor does an undo confirm");
  assert.deepEqual(buttonLabels(card(idea(), { canCreate: false, confirming: { kind: "create", id: idea().id } })).filter((l) => l !== "Copy YAML"), ["Dismiss"], "a non-admin never gets the confirm row");
});

test("Escape in the confirm row cancels and goes no further; other keys do nothing", () => {
  const seen = [];
  const handlers = new Proxy({}, { get: (_, name) => (...args) => seen.push([name, ...args.map((a) => typeof a)]) });
  const vnode = ideaCard(idea(), { canCreate: true, working: false, busy: null, confirming: { kind: "create", id: idea().id }, errors: new Map(), on: handlers });
  const find = (node, test) => {
    if (typeof node === "string") return null;
    if (test(node)) return node;
    for (const child of node.children) {
      const hit = find(child, test);
      if (hit) return hit;
    }
    return null;
  };
  const group = find(vnode, (n) => n.props.role === "group");
  let stopped = 0;
  group.props.onkeydown({ key: "a", stopPropagation: () => (stopped += 1) });
  assert.deepEqual(seen, []);
  group.props.onkeydown({ key: "Escape", stopPropagation: () => (stopped += 1) });
  assert.deepEqual(seen, [["cancel", "object"]]);
  assert.equal(stopped, 1);
});

test("while a call runs every button is disabled and the pressed one shows a spinner", () => {
  const root = card(idea(), { working: true, busy: { id: idea().id, action: "create" } });
  const [create, dismiss] = buttonsOf(root).filter((b) => ["Create", "Dismiss"].includes(textOf(b).trim()));
  assert.equal(create.getAttribute("disabled"), "");
  assert.equal(create.getAttribute("aria-busy"), "true");
  assert.equal(findAll(create, (el) => hasClass(el, "mini-spin")).length, 1);
  assert.equal(dismiss.getAttribute("disabled"), "");
  const other = card(idea(), { working: true, busy: { id: "elsewhere", action: "create" } });
  assert.equal(buttonsOf(other).find((b) => textOf(b).trim() === "Create").getAttribute("aria-busy"), null, "only the busy card shows the spinner");
  assert.equal(buttonsOf(other).find((b) => textOf(b).trim() === "Create").getAttribute("disabled"), "", "but nothing else can start");
  const copy = buttonsOf(root).find((b) => textOf(b).trim() === "Copy YAML");
  assert.equal(copy.getAttribute("disabled"), null, "copying is harmless");
});

test("an error is shown inline on that card, as an alert", () => {
  const root = card(idea(), { errors: new Map([[idea().id, "An automation already covers this: light.hall is covered."]]) });
  const line = findAll(root, (el) => hasClass(el, "habit-error"))[0];
  assert.equal(line.getAttribute("role"), "alert");
  assert.match(textOf(line), /An automation already covers this: light\.hall is covered\./);
  assert.equal(findAll(card(), (el) => hasClass(el, "habit-error")).length, 0);
});

// ---- the created list --------------------------------------------------------------------------------------------

test("a created automation: alias, when, state, a link to Home Assistant and Undo", () => {
  const root = row();
  const text = textOf(root);
  assert.match(text, /Kitchen light off at 23:10 \(every day\)/);
  assert.match(text, /Created 3 hours ago/);
  assert.match(text, /Created\s*Created 3 hours ago/, "the state chip and the line");
  const link = findAll(root, (el) => el.localName === "a")[0];
  assert.equal(link.getAttribute("href"), "/config/automation/edit/1732380000123");
  assert.equal(link.getAttribute("target"), null, "same tab");
  assert.match(textOf(link), /Open in Home Assistant/);
  assert.deepEqual(buttonLabels(root), ["Undo"]);
});

test("Undo is two steps: the confirm row asks 'Remove this automation again?'", () => {
  const root = row(created(), { confirming: { kind: "undo", id: "hab1" } });
  assert.match(textOf(root), /Remove this automation again\?/);
  assert.deepEqual(buttonLabels(root), ["Confirm", "Cancel"]);
  assert.equal(findAll(root, (el) => el.localName === "a").length, 0, "the link comes back with the buttons");
  assert.deepEqual(buttonLabels(row(created(), { confirming: { kind: "undo", id: "other" } })), ["Undo"]);
});

test("an undone one is a muted line without buttons or link", () => {
  const root = row(created({ state: "undone" }));
  assert.equal(hasClass(findAll(root, (el) => el.localName === "li")[0], "muted-row"), true);
  assert.match(textOf(root), /Undone: the automation was removed again\./);
  assert.deepEqual(buttonLabels(root), []);
  assert.equal(findAll(root, (el) => el.localName === "a").length, 0);
});

test("the stale error shows the fixed text on the row, and the link stays so it can be deleted in Home Assistant", () => {
  const stale = "It was edited after it was created, so Homeboard will not remove it. Delete it in Home Assistant.";
  const root = row(created(), { errors: new Map([["hab1", stale]]) });
  assert.match(textOf(findAll(root, (el) => hasClass(el, "habit-error"))[0]), /It was edited after it was created, so Homeboard will not remove it\. Delete it in Home Assistant\./);
  assert.equal(findAll(root, (el) => el.localName === "a").length, 1);
});

test("non-administrators see the list without link or Undo", () => {
  const root = row(created(), { canManage: false });
  assert.deepEqual(buttonLabels(root), []);
  assert.equal(findAll(root, (el) => el.localName === "a").length, 0);
  assert.match(textOf(root), /Kitchen light off/);
});

// ---- the section -------------------------------------------------------------------------------------------------

test("the section: title with the number of ideas, status line, Scan now, the cards, then the created list", () => {
  const root = section();
  const text = textOf(root);
  assert.match(textOf(findAll(root, (el) => el.localName === "h3")[0]), /Inbox: automation ideas2/);
  assert.match(text, /Last scan 4 hours ago, 120 entities, 28 days of history/);
  assert.equal(findAll(root, (el) => el.localName === "article").length, 2);
  assert.ok(buttonLabels(root).includes("Scan now"));
  const ideasAt = text.indexOf("Turn on Hall light");
  const createdAt = text.indexOf("Created by Homeboard");
  assert.ok(ideasAt > 0 && createdAt > ideasAt, "created automations come under the cards");
  assert.equal(findAll(root, (el) => el.localName === "li").length, 2);
});

test("not scanned yet, no ideas: a calm line instead of cards", () => {
  const root = section({ ideas: [], habits: habitsData({ last_scan: null, created: [] }) });
  assert.match(textOf(root), /Not scanned yet\./);
  assert.match(textOf(root), /No automation ideas right now/);
  assert.equal(findAll(root, (el) => el.localName === "article").length, 0);
  assert.doesNotMatch(textOf(root), /Created by Homeboard/);
});

test("non-administrators: cards and evidence, but no Scan now and no Create", () => {
  const root = section({ isAdmin: false });
  assert.ok(!buttonLabels(root).includes("Scan now"));
  assert.ok(!buttonLabels(root).includes("Create"));
  assert.ok(!buttonLabels(root).includes("Undo"));
  assert.ok(buttonLabels(root).includes("Dismiss"));
  assert.match(textOf(root), /Last scan 4 hours ago/);
});

test("Scan now: a spinner while it runs, disabled while anything runs, and the result text afterwards", () => {
  const running = section({ scan: { running: true, outcome: null, error: null }, working: true });
  const button = buttonsOf(running).find((b) => b.getAttribute("data-habit-scan") != null);
  assert.equal(button.getAttribute("aria-busy"), "true");
  assert.equal(button.getAttribute("disabled"), "");
  assert.match(textOf(button), /Scanning\.\.\./);
  assert.equal(findAll(button, (el) => hasClass(el, "mini-spin")).length, 1);
  const busy = section({ working: true, busy: { id: "x", action: "create" } });
  assert.equal(buttonsOf(busy).find((b) => b.getAttribute("data-habit-scan") != null).getAttribute("disabled"), "");

  const outcome = (kind, key, extra = {}) => ({ running: false, outcome: { kind, key, ...extra }, error: null });
  const found = section({ scan: outcome("found", "habits.scan.found", { count: 3 }) });
  assert.match(textOf(findAll(found, (el) => hasClass(el, "habit-scan-result"))[0]), /Found 3 ideas/);
  assert.match(textOf(section({ scan: outcome("nothing", "habits.scan.nothing") })), /Nothing new/);
  const failed = section({ scan: outcome("error", "habits.scan.no_history", { vars: { days: 7 } }) });
  const line = findAll(failed, (el) => hasClass(el, "habit-scan-result"))[0];
  assert.match(textOf(line), /Not enough history yet: I need at least 7 days of history/);
  assert.equal(line.getAttribute("role"), "alert");
  assert.equal(findAll(found, (el) => hasClass(el, "habit-scan-live"))[0].getAttribute("aria-live"), "polite");
});

test("a failed scan call is shown, and the error of the last scan on record is shown until a new result comes", () => {
  assert.match(textOf(section({ scan: { running: false, outcome: null, error: "Only administrators can do that." } })), /Only administrators can do that\./);
  const kept = section({ habits: habitsData({ error: "no_recorder" }) });
  assert.match(textOf(kept), /The Home Assistant recorder is not available/);
  const fresh = section({ habits: habitsData({ error: "no_recorder" }), scan: { running: false, outcome: { kind: "nothing", key: "habits.scan.nothing" }, error: null } });
  assert.doesNotMatch(textOf(fresh), /recorder is not available/);
});

test("feature off: a calm explanation, no buttons, no cards", () => {
  const root = section({ features: { habits: false }, habits: null, ideas: [] });
  const text = textOf(root);
  assert.match(text, /Inbox: automation ideas/);
  assert.match(text, /Habit ideas are switched off\. They read how your lights, switches and sensors have been used \(only inside Home Assistant\) and suggest automations\. Switch it on in Settings > Devices & services > Homeboard > Configure > Learning\./);
  assert.match(text, /Home Assistant keeps 10 days of history by default; more days \(purge_keep_days\) give steadier ideas\./);
  assert.deepEqual(buttonLabels(root), []);
  assert.equal(findAll(root, (el) => el.localName === "article").length, 0);
});

test("a backend without habits (0.3) shows no inbox at all", () => {
  assert.equal(inboxSection(model({ features: { defaults: true } }), on), null);
  assert.equal(inboxSection(model({ features: undefined }), on), null);
});

test("the inbox is a phone-friendly list: the YAML scrolls inside its own box and the buttons are big enough", () => {
  const css = readFileSync(new URL("../../custom_components/homeboard/static/styles.js", import.meta.url), "utf8");
  assert.match(css, /\.yaml-box \{[^}]*overflow: auto/);
  assert.match(css, /pre\.yaml \{[^}]*white-space: pre/);
  assert.match(css, /pre\.yaml \{[^}]*font-family: ui-monospace/);
  const phone = css.slice(css.indexOf("@container insights (max-width: 520px)"));
  assert.match(phone, /\.inbox \.btn, \.inbox \.btn\.small \{ min-height: 44px/);
  assert.match(phone, /\.idea-yaml summary \{ min-height: 44px/);
});

test("Danish renders the whole inbox", () => {
  setLanguage("da");
  try {
    const text = textOf(section());
    assert.match(text, /Indbakke: idéer til automationer/);
    assert.match(text, /Sidst scannet for 4 timer siden, 120 entiteter, 28 dages historik/);
    assert.match(text, /Evidence|Grundlag: På 17 af 21 dage \(81 %\), mellem 06:28 og 06:42/);
    assert.match(text, /Den bliver oprettet slukket\. Du tænder den i Home Assistant\./);
    assert.ok(buttonLabels(section()).includes("Scan nu"));
    assert.ok(buttonLabels(section()).includes("Opret"));
    assert.match(textOf(section({ features: { habits: false }, habits: null, ideas: [] })), /Idéer fra vaner er slået fra\./);
    assert.match(textOf(section({ features: { habits: false }, habits: null, ideas: [] })), /purge_keep_days/);
  } finally {
    setLanguage("en");
  }
});

// ---- wired into the Insights tab -------------------------------------------------------------------------------

function insightsPage({ habits = true, isAdmin = true } = {}) {
  const backend = makeBackend({ habits });
  const data = backend.handle({ type: "homeboard/insights/get" });
  const { index } = makeState(backend);
  const sections = { habits: { render: (d, ideas, admin) => inboxSection({ features: d.features, habits: d.learned?.habits || null, ideas, isAdmin: admin, working: false, busy: null, confirming: null, errors: new Map(), scan: { running: false, outcome: null, error: null } }, on) } };
  return render(renderInsights({ controller: { data, error: null, ...sections, accept() {}, dismiss() {}, forget() {}, retry() {} }, index, isAdmin }));
}

test("the Insights tab: the inbox comes first, the other suggestions keep their own section without the ideas", () => {
  const root = insightsPage();
  const sections = findAll(root, (el) => el.localName === "section");
  assert.deepEqual(sections.map((s) => (hasClass(s, "inbox") ? "inbox" : hasClass(s, "suggestions") ? "suggestions" : "learned")), ["inbox", "suggestions", "learned"]);
  const [inbox, others] = sections;
  assert.equal(findAll(inbox, (el) => el.localName === "article").length, 3);
  assert.equal(findAll(others, (el) => el.localName === "article").length, 2, "the recurring and health suggestions only");
  assert.match(textOf(findAll(others, (el) => el.localName === "h3")[0]), /Suggestions2/);
  assert.deepEqual(buttonLabels(others), ["Accept", "Dismiss", "Accept", "Dismiss"], "ordinary suggestions render as before");
});

test("the Insights tab of a 0.3 backend has no inbox and looks as before", () => {
  const root = insightsPage({ habits: false });
  assert.deepEqual(findAll(root, (el) => el.localName === "section").map((s) => (hasClass(s, "suggestions") ? "suggestions" : "learned")), ["suggestions", "learned"]);
});

test("Habit ideas has a card with Forget in the learned list, and Forget everything stays", () => {
  const root = insightsPage();
  const card = findAll(root, (el) => el.localName === "article" && el.getAttribute("data-feature") === "habits")[0];
  assert.ok(card);
  assert.match(textOf(card), /Habit ideas/);
  assert.match(textOf(card), /Uses:.*Home Assistant's own history/);
  assert.match(textOf(card), /Forgetting clears the habit ideas and the ones you dismissed\. Automations that were created stay\./);
  assert.ok(buttonLabels(card).includes("Forget"));
  assert.equal(buttonLabels(insightsPage({ isAdmin: false })).includes("Forget"), false, "administrators only, as before");
});
