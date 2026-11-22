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
import { debounce } from "./util.js";

const PREVIEW_DELAY_MS = 250;
const SPEECH_REGIONS = { da: "da-DK", en: "en-US", de: "de-DE", sv: "sv-SE", nb: "nb-NO", nl: "nl-NL", fr: "fr-FR", es: "es-ES" };

function speechConstructor() {
  return globalThis.SpeechRecognition || globalThis.webkitSpeechRecognition || null;
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
      const parsed = await actions.previewQuickAdd(text, this.getProject());
      if (sequence !== this.sequence) return;
      this.parsed = parsed;
      this.hint = "";
    } catch (error) {
      if (sequence !== this.sequence) return;
      this.parsed = null;
      this.hint = error.code === "invalid_format" ? t("quickadd.need_summary") : "";
    }
    this.requestRender();
  }

  async submit() {
    const text = this.text.trim();
    if (!text || this.busy) return;
    this.busy = true;
    this.requestRender();
    const result = await actions.quickAdd(text, this.getProject());
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
    );
  }
}
