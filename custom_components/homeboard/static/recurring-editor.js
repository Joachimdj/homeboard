// "Recurring" tab of the project settings: list of chores plus the edit form.

import { actions } from "./actions.js";
import { checkboxField, icon, personOptions, priorityOptions, selectField, textField, typeIcon, typeOptions } from "./components.js";
import { h } from "./dom.js";
import { t } from "./i18n.js";
import { overlay } from "./overlay.js";
import { UNITS, draftFromRecurring, emptyRecurring, recurringParams, repeatFromDraft, repeatSummary, weekdayLabel } from "./recurring.js";
import { store } from "./store.js";
import { WEEKDAYS, formatDue } from "./util.js";

export class RecurringEditor {
  constructor({ dialog }) {
    this.dialog = dialog;
    this.editing = null; // { id: string | null, draft }
    this.labelsText = "";
  }

  render(project) {
    return this.editing ? this.form(project) : this.list(project);
  }

  // ---- list --------------------------------------------------------------------

  list(project) {
    const chores = (store.state.payload.recurring || []).filter((r) => r.project_id === project.id);
    return [
      h("p.muted.small", { key: "hint" }, t("recurring.hint")),
      chores.length
        ? h(
            "ul.recurring-list",
            { key: "list" },
            chores.map((chore) =>
              h(
                "li.recurring-item",
                { key: chore.id, class: chore.enabled ? "" : "disabled" },
                typeIcon(chore.type),
                h(
                  "div.recurring-main",
                  h("strong", chore.summary),
                  h("span.muted.small", `${repeatSummary(chore.repeat)} · ${t("recurring.next", { date: formatDue(chore.next_due) })}`),
                ),
                h("label.switch", { title: t("recurring.enabled") }, h("input", { type: "checkbox", checked: chore.enabled, "aria-label": `${t("recurring.enabled")}: ${chore.summary}`, onchange: (e) => actions.updateRecurring(chore.id, { enabled: e.target.checked }) })),
                h("button.icon-btn", { type: "button", title: t("recurring.run_now"), "aria-label": `${t("recurring.run_now")}: ${chore.summary}`, onclick: () => this.runNow(chore) }, icon("mdi:play-circle-outline")),
                h("button.icon-btn", { type: "button", title: t("edit"), "aria-label": `${t("edit")}: ${chore.summary}`, onclick: () => this.edit(chore.id, draftFromRecurring(chore)) }, icon("mdi:pencil-outline")),
                h("button.icon-btn", { type: "button", title: t("delete"), "aria-label": `${t("delete")}: ${chore.summary}`, onclick: () => this.remove(chore) }, icon("mdi:delete-outline")),
              ),
            ),
          )
        : h("p.muted", { key: "none" }, t("recurring.none")),
      h("div.form-actions", { key: "actions" }, h("button.btn.primary", { type: "button", onclick: () => this.edit(null, emptyRecurring(project)) }, icon("mdi:plus"), t("recurring.new"))),
    ];
  }

  edit(id, draft) {
    this.editing = { id, draft };
    this.labelsText = draft.labels.join(", ");
    this.dialog.update();
  }

  async runNow(chore) {
    const result = await actions.runRecurring(chore.id);
    if (!result) return;
    overlay.toast({ message: result.issue ? t("recurring.created", { key: result.issue.key }) : t("recurring.skipped") });
  }

  async remove(chore) {
    const ok = await overlay.confirm({ title: t("recurring.delete"), message: t("recurring.delete_confirm", { name: chore.summary }), confirmLabel: t("delete"), danger: true });
    if (ok) await actions.deleteRecurring(chore.id);
  }

  // ---- form --------------------------------------------------------------------

  async save(project) {
    const { id, draft } = this.editing;
    const { params, error } = recurringParams(draft);
    if (error) {
      overlay.toast({ kind: "error", message: t(error) });
      return;
    }
    const saved = id ? await actions.updateRecurring(id, params) : await actions.createRecurring(project.id, params);
    if (saved) {
      this.editing = null;
      this.dialog.update();
    }
  }

  form(project) {
    const { id, draft } = this.editing;
    const refresh = () => this.dialog.update();
    const set = (field) => (value) => {
      draft[field] = value;
      refresh();
    };
    const statusOptions = [{ value: "", label: t("recurring.status_default") }, ...project.statuses.map((s) => ({ value: s.id, label: s.name }))];

    const repeatRow = [
      h("label.field.narrow", { key: "every" }, h("span.field-label", t("recurring.every")), h("input.input", { type: "number", min: "1", value: draft.every, oninput: (e) => { draft.every = e.target.value; refresh(); } })),
      h(
        "label.field",
        { key: "unit" },
        h("span.field-label", t("recurring.unit")),
        h("select.input", { value: draft.unit, onchange: (e) => set("unit")(e.target.value) }, UNITS.map((u) => h("option", { key: u, value: u }, t(`unit.${u}`)))),
      ),
    ];

    const weekdays =
      draft.unit === "week"
        ? h(
            "div.field",
            { key: "weekdays" },
            h("span.field-label", t("recurring.weekdays")),
            h(
              "div.weekdays",
              { role: "group", "aria-label": t("recurring.weekdays") },
              WEEKDAYS.map((day) =>
                h(
                  "button.chip-toggle",
                  {
                    key: day,
                    type: "button",
                    "aria-pressed": String(draft.weekdays.includes(day)),
                    class: draft.weekdays.includes(day) ? "on" : "",
                    onclick: () => set("weekdays")(draft.weekdays.includes(day) ? draft.weekdays.filter((d) => d !== day) : [...draft.weekdays, day]),
                  },
                  weekdayLabel(day),
                ),
              ),
            ),
            h("span.muted.small", t("recurring.weekdays_hint")),
          )
        : null;

    const monthDay =
      draft.unit === "month"
        ? h(
            "div.field",
            { key: "month-day" },
            h("span.field-label", t("recurring.day_of_month")),
            h(
              "div.inline",
              h("input.input.narrow", { type: "number", min: "1", max: "31", value: draft.dayOfMonth, disabled: draft.lastDay, "aria-label": t("recurring.day_of_month"), oninput: (e) => { draft.dayOfMonth = e.target.value; refresh(); } }),
              checkboxField({ id: "last-day", label: t("recurring.last_day"), checked: draft.lastDay, onchange: set("lastDay") }),
            ),
            h("span.muted.small", t("recurring.day_hint")),
          )
        : null;

    return [
      h(
        "div.form-grid",
        { key: "grid" },
        textField({ id: "summary", label: t("field.summary"), value: draft.summary, oninput: set("summary"), attrs: { "data-autofocus": "", maxlength: 200 } }),
        selectField({ id: "type", label: t("field.type"), value: draft.type, options: typeOptions(), onchange: set("type") }),
        selectField({ id: "priority", label: t("field.priority"), value: draft.priority, options: priorityOptions(), onchange: set("priority") }),
        selectField({ id: "assignee", label: t("field.assignee"), value: draft.assignee, options: personOptions(store.state.index), onchange: set("assignee") }),
        selectField({ id: "status", label: t("field.status"), value: draft.status, options: statusOptions, onchange: set("status") }),
        textField({
          id: "labels",
          label: t("field.labels"),
          value: this.labelsText,
          placeholder: t("recurring.labels_placeholder"),
          oninput: (v) => {
            this.labelsText = v;
            draft.labels = v.split(",").map((l) => l.trim().replace(/^#/, "").toLowerCase()).filter(Boolean);
          },
        }),
      ),
      h("label.field", { key: "description" }, h("span.field-label", t("field.description")), h("textarea.input", { rows: 2, value: draft.description, oninput: (e) => { draft.description = e.target.value; } })),
      h("fieldset.repeat-box", { key: "repeat" }, h("legend", t("recurring.repeat")), h("div.inline", repeatRow), weekdays, monthDay, h("p.repeat-preview", icon("mdi:repeat"), repeatSummary(repeatFromDraft(draft)))),
      h(
        "div.form-grid",
        { key: "timing" },
        textField({ id: "next-due", label: t("recurring.next_due"), type: "date", value: draft.nextDue, onchange: set("nextDue") }),
        textField({ id: "days-before", label: t("recurring.days_before"), type: "number", value: draft.createDaysBefore, attrs: { min: "0" }, oninput: (v) => { draft.createDaysBefore = v; } }),
      ),
      checkboxField({ id: "skip", label: t("recurring.skip_if_open"), checked: draft.skipIfOpen, onchange: set("skipIfOpen") }),
      checkboxField({ id: "enabled", label: t("recurring.enabled"), checked: draft.enabled, onchange: set("enabled") }),
      h(
        "div.form-actions",
        { key: "actions" },
        h("button.btn", { type: "button", onclick: () => { this.editing = null; refresh(); } }, t("cancel")),
        h("button.btn.primary", { type: "button", onclick: () => this.save(project) }, id ? t("save") : t("create")),
      ),
    ];
  }
}
