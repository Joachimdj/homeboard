// Visual editors for the three Lovelace cards (own inputs, no HA form helpers).
// Each fires `config-changed` like any card editor.

import { adoptStyles, h, patch } from "./dom.js";
import { LANE_MODES } from "./filters.js";
import { t } from "./i18n.js";
import { store } from "./store.js";
import { baseCss, editorCss } from "./styles.js";

class CardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    adoptStyles(this.shadowRoot, baseCss, editorCss);
    this.container = document.createElement("div");
    this.shadowRoot.append(this.container);
    this.config = {};
    this.frame = 0;
  }

  setConfig(config) {
    this.config = { ...config };
    this.requestRender();
  }

  set hass(value) {
    this._hass = value;
    store.setHass(value);
    if (this.isConnected && !this.release) this.release = store.acquire(value);
  }

  get hass() {
    return this._hass;
  }

  connectedCallback() {
    this.unsubscribe = store.subscribe(() => this.requestRender());
    if (this._hass) this.release = store.acquire(this._hass);
    this.requestRender();
  }

  disconnectedCallback() {
    this.unsubscribe?.();
    this.release?.();
    this.release = null;
    cancelAnimationFrame(this.frame);
    this.frame = 0;
  }

  requestRender() {
    if (this.frame || !this.isConnected) return;
    this.frame = requestAnimationFrame(() => {
      this.frame = 0;
      patch(this.container, h("div.editor", this.fields().map((field) => this.renderField(field))));
    });
  }

  /** Empty values remove the key so the YAML stays short. */
  setValue(name, value) {
    const config = { ...this.config };
    if (value === "" || value == null || (Array.isArray(value) && !value.length)) delete config[name];
    else config[name] = value;
    this.config = config;
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
    this.requestRender();
  }

  projectOptions(none) {
    const projects = store.state.index?.projects.filter((p) => !p.archived) || [];
    return [{ value: "", label: none }, ...projects.map((p) => ({ value: p.key, label: `${p.key} · ${p.name}` }))];
  }

  renderField(field) {
    const value = this.config[field.name];
    const label = t(`editor.${field.name}`);
    switch (field.kind) {
      case "bool":
        return h(
          "label.check",
          { key: field.name },
          h("input", { type: "checkbox", checked: value === undefined ? field.default : Boolean(value), onchange: (e) => this.setValue(field.name, e.target.checked === field.default ? undefined : e.target.checked) }),
          h("span", label),
        );
      case "select":
        return h(
          "label.field",
          { key: field.name },
          h("span.field-label", label),
          h("select.input", { value: value ?? field.default ?? "", onchange: (e) => this.setValue(field.name, e.target.value) }, field.options.map((o) => h("option", { key: o.value, value: o.value }, o.label))),
        );
      case "projects":
        return h(
          "div.field",
          { key: field.name },
          h("span.field-label", label),
          this.projectOptions("")
            .filter((o) => o.value)
            .map((o) =>
              h(
                "label.check",
                { key: o.value },
                h("input", { type: "checkbox", checked: (value || []).includes(o.value), onchange: (e) => this.setValue(field.name, e.target.checked ? [...(value || []), o.value] : (value || []).filter((k) => k !== o.value)) }),
                h("span", o.label),
              ),
            ),
          h("span.muted.small", t("editor.projects_hint")),
        );
      default:
        return h(
          "label.field",
          { key: field.name },
          h("span.field-label", label),
          h("input.input", {
            type: field.kind === "number" ? "number" : "text",
            value: value ?? "",
            placeholder: field.placeholder || "",
            onchange: (e) => this.setValue(field.name, field.kind === "number" && e.target.value !== "" ? Number(e.target.value) : e.target.value.trim()),
          }),
        );
    }
  }
}

class BoardCardEditor extends CardEditor {
  fields() {
    return [
      { name: "project", kind: "select", options: this.projectOptions(t("editor.first_project")) },
      { name: "title", kind: "text" },
      { name: "show_backlog", kind: "bool", default: false },
      { name: "swimlanes", kind: "select", default: "none", options: LANE_MODES.map((m) => ({ value: m, label: t(`lanes.${m}`) })) },
      { name: "filter", kind: "text", placeholder: "mine, overdue, due_soon, unassigned, auto" },
      { name: "kiosk", kind: "bool", default: false },
      { name: "max_height", kind: "number", placeholder: "560" },
    ];
  }
}

class StatusCardEditor extends CardEditor {
  fields() {
    return [
      { name: "title", kind: "text" },
      { name: "projects", kind: "projects" },
      { name: "show_people", kind: "bool", default: true },
      { name: "show_health", kind: "bool", default: true },
      { name: "show_insights", kind: "bool", default: true },
    ];
  }
}

class QuickAddCardEditor extends CardEditor {
  fields() {
    return [
      { name: "title", kind: "text" },
      { name: "project", kind: "select", options: this.projectOptions(t("editor.first_project")) },
    ];
  }
}

for (const [name, constructor] of [
  ["homeboard-board-card-editor", BoardCardEditor],
  ["homeboard-status-card-editor", StatusCardEditor],
  ["homeboard-quick-add-card-editor", QuickAddCardEditor],
]) {
  if (!customElements.get(name)) customElements.define(name, constructor);
}
