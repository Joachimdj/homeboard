import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";
import { getLocale, languageFromHass, normaliseLanguage, setLanguage, t, tn } from "../../custom_components/homeboard/static/i18n.js";
import da from "../../custom_components/homeboard/static/strings-da.js";
import en from "../../custom_components/homeboard/static/strings-en.js";

const STATIC = new URL("../../custom_components/homeboard/static/", import.meta.url);

test("language normalisation and hass lookup", () => {
  assert.equal(normaliseLanguage("da-DK"), "da");
  assert.equal(normaliseLanguage("DA"), "da");
  assert.equal(normaliseLanguage("sv"), "en"); // unknown -> English strings
  assert.equal(normaliseLanguage(undefined), "en");
  assert.equal(languageFromHass({ locale: { language: "da" }, language: "en" }), "da");
  assert.equal(languageFromHass({ language: "de" }), "de");
  assert.equal(languageFromHass(null), "en");
});

test("t() uses the active language, falls back to English, then to the key", () => {
  setLanguage("da-DK");
  assert.equal(t("filter.mine"), da["filter.mine"]);
  assert.equal(getLocale(), "da-DK");
  setLanguage("sv-SE"); // not translated: English strings, Swedish number / date locale
  assert.equal(getLocale(), "sv-SE");
  assert.equal(t("filter.mine"), en["filter.mine"]);
  assert.equal(t("no.such.key"), "no.such.key");
  setLanguage("en");
});

test("variables and plurals", () => {
  setLanguage("en");
  assert.equal(t("toast.moved", { key: "HOME-1", status: "Done" }), "HOME-1 moved to Done");
  assert.equal(t("toast.moved", { key: "HOME-1" }), "HOME-1 moved to {status}");
  assert.equal(tn("repeat.week", 1), "Every week");
  assert.equal(tn("repeat.week", 3), "Every 3 weeks");
  setLanguage("da");
  assert.equal(tn("repeat.week", 2), "Hver 2. uge");
  setLanguage("en");
});

test("Danish has every English key and no extras", () => {
  assert.deepEqual(Object.keys(en).filter((k) => !(k in da)), []);
  assert.deepEqual(Object.keys(da).filter((k) => !(k in en)), []);
});

test("variables used by English strings also appear in the Danish ones", () => {
  const vars = (s) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort().join();
  for (const key of Object.keys(en)) assert.equal(vars(da[key]), vars(en[key]), key);
});

test("every translation key used in the source exists", () => {
  const used = new Set();
  const dynamic = new Set();
  for (const file of readdirSync(STATIC).filter((f) => f.endsWith(".js") && !f.startsWith("strings-"))) {
    const source = readFileSync(new URL(file, STATIC), "utf8");
    for (const m of source.matchAll(/\bt(n?)\(\s*(["'`])([\w.${}\-]+)\2/g)) {
      (m[3].includes("${") ? dynamic : used).add(m[1] ? `${m[3]}_other` : m[3]);
    }
    for (const m of source.matchAll(/error: "([\w.]+)"/g)) used.add(m[1]);
  }
  const missing = [...used].filter((key) => !(key in en));
  assert.deepEqual(missing, []);
  assert.ok(dynamic.size > 5, "dynamic keys are checked below");

  const families = {
    "type.": ["task", "bug", "story", "epic"],
    "priority.": ["highest", "high", "medium", "low", "lowest"],
    "category.": ["todo", "in_progress", "done"],
    "field.": ["summary", "description", "type", "priority", "assignee", "labels", "due", "status", "parent", "checklist", "attachments"],
    "lanes.": ["none", "assignee", "priority"],
    "list.col.": ["key", "summary", "status", "priority", "assignee", "due", "updated"],
    "settings.tab.": ["general", "statuses", "labels", "recurring"],
    "tab.": ["summary", "board", "backlog", "list", "insights", "comments", "history"],
    "insights.feature.": ["defaults", "patterns", "workload", "health", "rhythm"],
    "insights.data.": ["defaults", "patterns", "workload", "health", "rhythm"],
    "template.": ["household", "software", "blank"],
    "unit.": ["day", "week", "month", "year"],
    "editor.": ["project", "title", "show_backlog", "swimlanes", "filter", "kiosk", "max_height", "projects", "show_people", "show_health", "show_insights"],
  };
  for (const [prefix, names] of Object.entries(families)) for (const name of names) assert.ok(`${prefix}${name}` in en, `${prefix}${name}`);
  for (const unit of ["day", "week", "month", "year"]) for (const suffix of ["one", "other"]) assert.ok(`repeat.${unit}_${suffix}` in en);
  for (const template of ["household", "software", "blank"]) assert.ok(`template.${template}.hint` in en);
});
