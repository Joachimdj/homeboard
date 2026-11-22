// Quick-add box: one text line, live preview chips from the server parser,
// Enter to create, optional microphone (browser speech recognition).

import { actions } from "./actions.js";
import { avatar, icon } from "./components.js";
import { h } from "./dom.js";
import { getLocale, t } from "./i18n.js";
import { openIssueDialog } from "./issue-dialog.js";
import { overlay } from "./overlay.js";
import { buildChips } from "./quickadd-chips.js";
import { store } from "./store.js";
import { hasSuggestion, similarIssues, suggestionChips, suggestionSummary } from "./suggestions.js";
import { debounce } from "./util.js";

const PREVIEW_DELAY_MS = 250;
const SUGGEST_PREF_KEY = "homeboard.useSuggestions";
const SPEECH_REGIONS = { da: "da-DK", en: "en-US", de: "de-DE", sv: "sv-SE", nb: "nb-NO", nl: "nl-NL", fr: "fr-FR", es: "es-ES" };

function speechConstructor() {
  return globalThis.SpeechRecognition || globalThis.webkitSpeechRecognition || null;
}

function loadUseSuggestions() {
  try {
    return localStorage.getItem(SUGGEST_PREF_KEY) !== "0";
  } catch {
    return true;
  }
}

function saveUseSuggestions(value) {
  try {
    localStorage.setItem(SUGGEST_PREF_KEY, value ? "1" : "0");
  } catch {
    // storage blocked: the choice just lasts until the page is reloaded
  }
}

function speechLanguage() {
  const locale = getLocale();
  return locale.includes("-") ? locale : SPEECH_REGIONS[locale] || locale;
}

export class QuickAdd {
  /** getProject() returns the project key or id to file the issue under (or undefined). */
  constructor({ getProject, requestRender }) {
    this.getProject = getProject;
    this.requestRender = requestRender;
    this.text = "";
    this.parsed = null;
    this.suggestion = null;
    this.useSuggestions = loadUseSuggestions();
    this.showWhy = false;
    this.hint = "";
    this.busy = false;
    this.recognition = null;
    this.sequence = 0;
    this.preview = debounce(() => this.loadPreview(), PREVIEW_DELAY_MS);
  }

  dispose() {
    this.preview.cancel();
    this.recognition?.abort?.();
  }

  setText(text) {
    this.text = text;
    if (!text.trim()) {
      this.sequence += 1;
      this.preview.cancel();
      this.parsed = null;
      this.suggestion = null;
      this.showWhy = false;
      this.hint = "";
    } else {
      this.preview();
    }
    this.requestRender();
  }

  async loadPreview() {
    const sequence = ++this.sequence;
    const text = this.text;
    try {
      const { suggestion, ...parsed } = await actions.previewQuickAdd(text, this.getProject());
      if (sequence !== this.sequence) return;
      this.parsed = parsed;
      this.suggestion = suggestion || null;
      this.hint = "";
    } catch (error) {
      if (sequence !== this.sequence) return;
      this.parsed = null;
      this.suggestion = null;
      this.hint = error.code === "invalid_format" ? t("quickadd.need_summary") : "";
    }
    this.requestRender();
  }

  async submit() {
    const text = this.text.trim();
    if (!text || this.busy) return;
    this.busy = true;
    this.requestRender();
    const result = await actions.quickAdd(text, this.getProject(), { suggest: this.useSuggestions });
    this.busy = false;
    if (result) {
      this.setText("");
      overlay.toast({
        message: t("toast.created", { key: result.issue.key }),
        action: { label: t("open"), run: () => openIssueDialog(result.issue.id) },
      });
    }
    this.requestRender();
  }

  toggleMicrophone() {
    if (this.recognition) {
      this.recognition.stop();
      return;
    }
    const Recognition = speechConstructor();
    if (!Recognition) return;
    const recognition = new Recognition();
    recognition.lang = speechLanguage();
    recognition.interimResults = true;
    recognition.continuous = false;
    recognition.onresult = (event) => this.setText(Array.from(event.results).map((r) => r[0].transcript).join(" "));
    recognition.onerror = (event) => {
      if (event.error !== "no-speech" && event.error !== "aborted") overlay.toast({ kind: "error", message: t("quickadd.mic_error") });
    };
    recognition.onend = () => {
      this.recognition = null;
      this.requestRender();
    };
    this.recognition = recognition;
    try {
      recognition.start();
    } catch {
      this.recognition = null;
    }
    this.requestRender();
  }

  chips() {
    const index = store.state.index;
    return buildChips(this.parsed, { index }).map((chip) =>
      h(
        `span.chip.qa-chip.${chip.kind}`,
        { key: `${chip.kind}-${chip.text}`, style: chip.color ? { "--chip-color": chip.color } : null },
        chip.person ? avatar(index, chip.person, "xs") : chip.icon ? icon(chip.icon) : null,
        chip.text,
      ),
    );
  }

  setUseSuggestions(value) {
    this.useSuggestions = value;
    saveUseSuggestions(value);
    this.requestRender();
  }

  /** Dimmed "Suggested: ..." chips with the evidence behind them and a switch to use them. */
  suggestionRow() {
    const index = store.state.index;
    const learning = store.state.payload?.settings?.learning;
    if (!learning?.defaults) return null;
    const chips = hasSuggestion(this.suggestion) ? suggestionChips(this.suggestion, { index }) : [];
    const evidence = this.suggestion?.evidence || "";
    const similar = similarIssues(this.suggestion, index);
    return h(
      "div.qa-suggest",
      { key: "suggest", class: this.useSuggestions ? "" : "off" },
      chips.length
        ? [
            h("span.qa-suggest-label", { title: evidence }, t("suggest.label")),
            ...chips.map((chip) =>
              h(
                `span.chip.qa-chip.suggested.${chip.kind}`,
                { key: `s-${chip.kind}-${chip.text}`, title: evidence, style: chip.color ? { "--chip-color": chip.color } : null },
                chip.person ? avatar(index, chip.person, "xs") : chip.icon ? icon(chip.icon) : null,
                chip.text,
              ),
            ),
            h("button.icon-btn.small.why", { key: "why", type: "button", "aria-expanded": String(this.showWhy), "aria-label": t("suggest.why"), title: t("suggest.why"), onclick: () => { this.showWhy = !this.showWhy; this.requestRender(); } }, icon("mdi:help-circle-outline")),
          ]
        : null,
      h(
        "label.check.small.use-suggestions",
        { key: "use", title: t("suggest.use_hint") },
        h("input", { type: "checkbox", checked: this.useSuggestions, onchange: (event) => this.setUseSuggestions(event.target.checked) }),
        h("span", t("suggest.use")),
      ),
      chips.length && this.showWhy
        ? h(
            "div.qa-why",
            { key: "why-text", "aria-live": "polite" },
            h("span", `${t("suggest.evidence_title")}: ${evidence} (${suggestionSummary(chips)})`),
            similar.length
              ? h(
                  "span.similar",
                  `${t("suggest.similar")}: `,
                  similar.map((issue) =>
                    issue.id
                      ? h("button.link", { key: issue.key, type: "button", title: `${issue.summary} (${issue.status})`, onclick: () => openIssueDialog(issue.id) }, issue.key)
                      : h("span.muted", { key: issue.key, title: issue.summary }, issue.key),
                  ),
                )
              : null,
          )
        : null,
    );
  }

  render({ placeholder } = {}) {
    const listening = Boolean(this.recognition);
    return h(
      "div.quickadd",
      h(
        "form.qa-row",
        { key: "form", onsubmit: (event) => { event.preventDefault(); this.submit(); } },
        h("input.input.qa-input", {
          key: "input",
          type: "text",
          value: this.text,
          placeholder: placeholder || t("quickadd.placeholder"),
          "aria-label": t("quickadd.label"),
          autocomplete: "off",
          enterkeyhint: "send",
          oninput: (event) => this.setText(event.target.value),
        }),
        speechConstructor()
          ? h(
              "button.icon-btn.mic",
              { key: "mic", type: "button", class: listening ? "listening" : "", "aria-pressed": String(listening), "aria-label": t("quickadd.mic"), title: t("quickadd.mic"), onclick: () => this.toggleMicrophone() },
              icon(listening ? "mdi:microphone-off" : "mdi:microphone"),
            )
          : null,
        h("button.btn.primary.qa-send", { key: "send", type: "submit", disabled: !this.text.trim() || this.busy, "aria-label": t("quickadd.add") }, icon("mdi:plus"), h("span.qa-send-text", t("quickadd.add"))),
      ),
      this.parsed || this.hint
        ? h("div.qa-preview", { key: "preview", "aria-live": "polite" }, this.parsed ? [h("span.qa-summary", this.parsed.summary), this.chips()] : h("span.muted", this.hint))
        : null,
      this.parsed ? this.suggestionRow() : null,
    );
  }
}
