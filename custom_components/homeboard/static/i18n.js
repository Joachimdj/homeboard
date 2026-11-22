// Tiny translation layer: t(key, vars), tn(key, count, vars), language from hass.

import en from "./strings-en.js";
import da from "./strings-da.js";

const dictionaries = { en, da };

let language = "en";
let locale = "en";

/** "da-DK" -> "da"; unknown languages fall back to English strings. */
export function normaliseLanguage(code) {
  const base = String(code || "en").toLowerCase().split(/[-_]/)[0];
  return dictionaries[base] ? base : "en";
}

export function languageFromHass(hass) {
  return hass?.locale?.language || hass?.language || "en";
}

export function setLanguage(code) {
  language = normaliseLanguage(code);
  locale = String(code || "en").replace("_", "-");
}

/** BCP-47 tag for Intl (keeps a region such as en-GB when the user has one). */
export function getLocale() {
  return locale;
}

function format(text, vars) {
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (match, name) => (name in vars ? String(vars[name]) : match));
}

export function t(key, vars) {
  const text = dictionaries[language]?.[key] ?? en[key] ?? key;
  return format(text, vars);
}

/** Plural-aware lookup: uses `<key>_one` for 1, `<key>_other` otherwise. */
export function tn(key, count, vars) {
  const suffix = count === 1 ? "_one" : "_other";
  return t(key + suffix, { n: count, ...vars });
}
