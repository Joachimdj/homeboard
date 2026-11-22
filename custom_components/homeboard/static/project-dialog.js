// Project settings: create / rename / colour / statuses / labels / lead /
// default assignee (admin only) and the recurring chores of the project
// (open to every user, as in the protocol).

import { actions } from "./actions.js";
import { checkboxField, icon, labelChip, personOptions, selectField, textField } from "./components.js";
import { h } from "./dom.js";
import { t, tn } from "./i18n.js";
import { RecurringEditor } from "./recurring-editor.js";
import { dialogShell, overlay } from "./overlay.js";
import { store } from "./store.js";
import { CATEGORIES, uniqueSorted } from "./util.js";

const COLORS = ["#2f80ed", "#27ae60", "#f2994a", "#eb5757", "#9b51e0", "#00a6a6", "#e91e63", "#6d7b8a"];
const TEMPLATES = ["household", "software", "blank"];
const KEY_PATTERN = /^[A-Z0-9]{2,6}$/;

export function openProjectSettings(options = {}) {
  return new ProjectDialog(options).open();
}

class ProjectDialog {
  constructor({ projectId = null, tab = "general", create = false, onSelectProject = null } = {}) {
    this.projectId = projectId;
    this.tab = store.isAdmin ? tab : "recurring";
    this.creating = create && store.isAdmin;
    this.onSelectProject = onSelectProject;
    this.draft = { key: "", name: "", template: "household", color: COLORS[0], description: "" };
    this.status = { name: "", category: "todo" };
    this.labelText = "";
    this.recurring = null; // RecurringEditor while a chore is being edited
  }

  open() {
    this.release = store.acquire(store.hass);
    this.unsubscribe = store.subscribe(() => this.update());
    this.handle = overlay.dialog(this);
    return this;
  }

  onClose() {
    this.unsubscribe?.();
    this.release?.();
  }

  update() {
    this.handle?.update();
  }

  close() {
    this.handle.close();
  }

  get index() {
    return store.state.index;
  }

  get project() {
    return this.index?.projectById.get(this.projectId) || null;
  }

  size = "tall";

  label() {
    return t("settings.title");
  }

  selectProject(id) {
    this.projectId = id;
    this.recurring = null;
    this.onSelectProject?.(id);
    this.update();
  }

  // ---- create ----------------------------------------------------------------

  async submitCreate() {
    const d = this.draft;
    const key = d.key.trim().toUpperCase();
    if (!KEY_PATTERN.test(key) || !d.name.trim()) return;
    const project = await actions.createProject({ key, name: d.name.trim(), template: d.template, color: d.color, description: d.description });
    if (!project) return;
    this.creating = false;
    this.draft = { key: "", name: "", template: "household", color: COLORS[0], description: "" };
    this.tab = "general";
    this.selectProject(project.id);
  }

  colorPicker(value, onpick) {
    return h(
      "div.colors",
      COLORS.map((color) =>
        h("button.swatch", {
          key: color,
          type: "button",
          style: { background: color },
          "aria-label": color,
          "aria-pressed": String(value === color),
          class: value === color ? "selected" : "",
          onclick: () => onpick(color),
        }),
      ),
      h("input.color-input", { key: "custom", type: "color", value, "aria-label": t("settings.color_custom"), onchange: (e) => onpick(e.target.value) }),
    );
  }

  createForm() {
    const d = this.draft;
    const valid = KEY_PATTERN.test(d.key.trim().toUpperCase()) && d.name.trim();
    return [
      h("p.muted", { key: "intro" }, t("settings.new_intro")),
      h(
        "div.form-grid",
        { key: "grid" },
        textField({ id: "key", label: t("settings.key"), value: d.key, placeholder: "HOME", attrs: { maxlength: 6, "data-autofocus": "", autocapitalize: "characters" }, oninput: (v) => { d.key = v.toUpperCase(); this.update(); } }),
        textField({ id: "name", label: t("settings.name"), value: d.name, placeholder: t("settings.name_placeholder"), oninput: (v) => { d.name = v; this.update(); } }),
        selectField({ id: "template", label: t("settings.template"), value: d.template, options: TEMPLATES.map((v) => ({ value: v, label: t(`template.${v}`) })), onchange: (v) => { d.template = v; this.update(); } }),
      ),
      h("p.muted.small", { key: "template-hint" }, t(`template.${d.template}.hint`)),
      h("div.field", { key: "color" }, h("span.field-label", t("settings.color")), this.colorPicker(d.color, (c) => { d.color = c; this.update(); })),
      d.key && !KEY_PATTERN.test(d.key.trim().toUpperCase()) ? h("p.error-text", { key: "key-error" }, t("settings.key_invalid")) : null,
      h("div.form-actions", { key: "actions" }, h("button.btn", { type: "button", onclick: () => { this.creating = false; this.update(); } }, t("cancel")), h("button.btn.primary", { type: "button", disabled: !valid, onclick: () => this.submitCreate() }, t("create"))),
    ];
  }

  // ---- general ---------------------------------------------------------------

  general(project) {
    const set = (fields) => actions.updateProject(project.id, fields);
    return [
      h(
        "div.form-grid",
        { key: "grid" },
        h("div.field", { key: "key" }, h("span.field-label", t("settings.key")), h("div.static-value", project.key)),
        textField({ id: "name", label: t("settings.name"), value: project.name, onchange: (v) => v.trim() && v.trim() !== project.name && set({ name: v.trim() }) }),
        selectField({ id: "lead", label: t("settings.lead"), value: project.lead || "", options: personOptions(this.index, { none: t("none") }), onchange: (v) => set({ lead: v || null }) }),
        selectField({ id: "default_assignee", label: t("settings.default_assignee"), value: project.default_assignee || "", options: personOptions(this.index, { none: t("unassigned") }), onchange: (v) => set({ default_assignee: v || null }) }),
        textField({ id: "icon", label: t("settings.icon"), value: project.icon || "", placeholder: "mdi:home", onchange: (v) => v !== (project.icon || "") && set({ icon: v }) }),
      ),
      h(
        "label.field",
        { key: "description" },
        h("span.field-label", t("settings.description")),
        h("textarea.input", { rows: 3, value: project.description || "", onchange: (e) => e.target.value !== (project.description || "") && set({ description: e.target.value }) }),
      ),
      h("div.field", { key: "color" }, h("span.field-label", t("settings.color")), this.colorPicker(project.color, (c) => set({ color: c }))),
      h(
        "section.danger-zone",
        { key: "danger" },
        checkboxField({ id: "archived", label: t("settings.archived"), checked: project.archived, onchange: (v) => set({ archived: v }) }),
        h("button.btn.danger-outline", { type: "button", onclick: () => this.deleteProject(project) }, icon("mdi:delete-outline"), t("settings.delete_project")),
      ),
    ];
  }

  async deleteProject(project) {
    const count = (this.index.byProject.get(project.id) || []).length;
    const ok = await overlay.confirm({
      title: t("settings.delete_project"),
      message: t("settings.delete_project_confirm", { name: project.name, n: count }),
      confirmLabel: t("delete"),
      danger: true,
    });
    if (!ok || !(await actions.deleteProject(project.id))) return;
    const next = this.index.projects.find((p) => p.id !== project.id && !p.archived);
    this.selectProject(next?.id || null);
  }

  // ---- statuses ----------------------------------------------------------------

  statuses(project) {
    const ids = project.statuses.map((s) => s.id);
    const move = (from, to) => {
      const next = [...ids];
      next.splice(to, 0, next.splice(from, 1)[0]);
      actions.reorderStatuses(project.id, next);
    };
    return [
      h("p.muted.small", { key: "hint" }, t("statuses.hint")),
      h(
        "ul.status-list",
        { key: "list" },
        project.statuses.map((status, i) =>
          h(
            "li.status-row",
            { key: status.id },
            h(
              "div.status-order",
              h("button.icon-btn", { type: "button", disabled: i === 0, "aria-label": t("statuses.move_up", { name: status.name }), onclick: () => move(i, i - 1) }, icon("mdi:arrow-up")),
              h("button.icon-btn", { type: "button", disabled: i === ids.length - 1, "aria-label": t("statuses.move_down", { name: status.name }), onclick: () => move(i, i + 1) }, icon("mdi:arrow-down")),
            ),
            h("input.input.status-name", {
              type: "text",
              value: status.name,
              "aria-label": t("statuses.name"),
              onchange: (e) => (e.target.value.trim() && e.target.value.trim() !== status.name ? actions.updateStatus(project.id, status.id, { name: e.target.value.trim() }) : this.update()),
            }),
            h(
              "select.input.status-category",
              { value: status.category, "aria-label": t("statuses.category"), onchange: (e) => actions.updateStatus(project.id, status.id, { category: e.target.value }) },
              CATEGORIES.map((c) => h("option", { key: c, value: c }, t(`category.${c}`))),
            ),
            h("input.input.status-wip", {
              type: "number",
              min: "1",
              value: status.wip ?? "",
              placeholder: t("statuses.wip"),
              "aria-label": t("statuses.wip_label"),
              onchange: (e) => actions.updateStatus(project.id, status.id, { wip: e.target.value === "" ? null : Math.max(1, Math.floor(Number(e.target.value))) }),
            }),
            h(
              "label.check.status-backlog",
              h("input", { type: "checkbox", checked: status.backlog, onchange: (e) => actions.updateStatus(project.id, status.id, { backlog: e.target.checked }) }),
              h("span", t("statuses.backlog")),
            ),
            h("button.icon-btn", { type: "button", "aria-label": t("statuses.delete", { name: status.name }), title: t("delete"), disabled: project.statuses.length <= 1, onclick: () => this.deleteStatus(project, status) }, icon("mdi:delete-outline")),
          ),
        ),
      ),
      h(
        "form.add-status",
        {
          key: "add",
          onsubmit: async (event) => {
            event.preventDefault();
            if (!this.status.name.trim()) return;
            if (await actions.createStatus(project.id, { name: this.status.name.trim(), category: this.status.category })) {
              this.status.name = "";
              this.update();
            }
          },
        },
        h("input.input", { type: "text", value: this.status.name, placeholder: t("statuses.new_name"), "aria-label": t("statuses.new_name"), oninput: (e) => { this.status.name = e.target.value; this.update(); } }),
        h(
          "select.input",
          { value: this.status.category, "aria-label": t("statuses.category"), onchange: (e) => { this.status.category = e.target.value; } },
          CATEGORIES.map((c) => h("option", { key: c, value: c }, t(`category.${c}`))),
        ),
        h("button.btn.primary", { type: "submit" }, icon("mdi:plus"), t("statuses.add")),
      ),
    ];
  }

  async deleteStatus(project, status) {
    const count = (this.index.byProject.get(project.id) || []).filter((i) => i.status === status.id).length;
    if (!count) {
      const ok = await overlay.confirm({ title: t("statuses.delete", { name: status.name }), message: t("statuses.delete_confirm", { name: status.name }), confirmLabel: t("delete"), danger: true });
      if (ok) await actions.deleteStatus(project.id, status.id);
      return;
    }
    const target = await overlay.choose({
      title: t("statuses.delete", { name: status.name }),
      message: tn("statuses.move_issues", count, { name: status.name }),
      options: project.statuses.filter((s) => s.id !== status.id).map((s) => ({ value: s.id, label: s.name })),
      confirmLabel: t("statuses.move_and_delete"),
    });
    if (target) await actions.deleteStatus(project.id, status.id, target);
  }

  // ---- labels ------------------------------------------------------------------

  labels(project) {
    const labels = project.labels || [];
    const save = (next) => actions.updateProject(project.id, { labels: uniqueSorted(next) });
    const add = () => {
      const label = this.labelText.trim().replace(/^#/, "").replace(/\s+/g, "-").toLowerCase();
      this.labelText = "";
      if (label && !labels.includes(label)) save([...labels, label]);
      else this.update();
    };
    return [
      h("p.muted.small", { key: "hint" }, t("labels.hint")),
      h("div.labels-edit.big", { key: "list" }, labels.length ? labels.map((l) => labelChip(l, { onRemove: (x) => save(labels.filter((y) => y !== x)) })) : h("span.muted", t("labels.none"))),
      h(
        "form.add-status",
        { key: "add", onsubmit: (event) => { event.preventDefault(); add(); } },
        h("input.input", { type: "text", value: this.labelText, placeholder: t("labels.new"), "aria-label": t("labels.new"), oninput: (e) => { this.labelText = e.target.value; this.update(); } }),
        h("button.btn.primary", { type: "submit" }, icon("mdi:plus"), t("statuses.add")),
      ),
    ];
  }

  // ---- render ------------------------------------------------------------------

  tabs() {
    const names = store.isAdmin ? ["general", "statuses", "labels", "recurring"] : ["recurring"];
    return h(
      "div.tabs.small",
      { key: "tabs", role: "tablist" },
      names.map((name) =>
        h("button.tab", { key: name, type: "button", role: "tab", "aria-selected": String(this.tab === name), class: this.tab === name ? "active" : "", onclick: () => { this.tab = name; this.update(); } }, t(`settings.tab.${name}`)),
      ),
    );
  }

  render() {
    const index = this.index;
    if (!index) return dialogShell({ title: t("settings.title"), onClose: () => this.close(), body: h("p.muted", t("loading")) });
    const projects = index.projects.filter((p) => !p.archived || p.id === this.projectId);
    if (!this.project && !this.creating && projects.length) this.projectId = projects[0].id;
    const project = this.project;

    let body;
    if (this.creating) body = this.createForm();
    else if (!project) body = [h("p.muted", t("settings.no_project"))];
    else {
      if (!this.recurring && this.tab === "recurring") this.recurring = new RecurringEditor({ dialog: this });
      body = [
        this.tabs(),
        h("div.settings-body", { key: `tab-${this.tab}` }, this.tab === "general" ? this.general(project) : this.tab === "statuses" ? this.statuses(project) : this.tab === "labels" ? this.labels(project) : this.recurring.render(project)),
      ];
    }

    return dialogShell({
      title: this.creating ? t("settings.new_project") : t("settings.title"),
      icon: "mdi:cog-outline",
      onClose: () => this.close(),
      headerRight: [
        !this.creating && projects.length
          ? h("select.input.project-select", { "aria-label": t("project"), value: this.projectId || "", onchange: (e) => this.selectProject(e.target.value) }, projects.map((p) => h("option", { key: p.id, value: p.id }, `${p.key} - ${p.name}`)))
          : null,
        !this.creating && store.isAdmin
          ? h("button.btn.small", { type: "button", onclick: () => { this.creating = true; this.update(); } }, icon("mdi:plus"), t("settings.new_project"))
          : null,
      ],
      body,
    });
  }
}
