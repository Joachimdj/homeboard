// Issue dialog: edit-in-place (every change is saved at once, like Jira) and the
// "New issue" form (same fields, saved with the Create button).

import { actions } from "./actions.js";
import { describeActivity } from "./activity.js";
import { AttachmentsSection } from "./attachments.js";
import { ChecklistEditor } from "./checklist-editor.js";
import { autoChip, avatar, icon, labelChip, personOptions, priorityOptions, selectField, typeIcon, typeOptions } from "./components.js";
import { deepActiveElement, h } from "./dom.js";
import { t } from "./i18n.js";
import { defaultStatus, personName } from "./indexes.js";
import { dialogShell, overlay } from "./overlay.js";
import { store } from "./store.js";
import { hasSuggestion, suggestionFill } from "./suggestions.js";
import { formatDateTime, joinDue, relativeTime, splitDue, uniqueSorted } from "./util.js";

const TEXT_FIELDS = new Set(["summary", "description"]);

/** What makes the fetched detail stale. Checklist counters are left out on purpose: they change optimistically. */
const detailKeyOf = (issue) => `${issue.updated}|${issue.comment_count}|${issue.attachment_count}`;

function normaliseLabel(text) {
  return text.trim().replace(/^#/, "").replace(/\s+/g, "-").toLowerCase();
}

export function openIssueDialog(issueId) {
  return new IssueDialog({ issueId }).open();
}

export function openNewIssueDialog(options = {}) {
  return new IssueDialog({ ...options, issueId: null }).open();
}

class IssueDialog {
  constructor({ issueId, projectId = null, status = "", parent = "" }) {
    this.issueId = issueId;
    this.create = !issueId;
    this.draft = {};
    this.detail = null;
    this.detailKey = "";
    this.loading = false;
    this.tab = "comments";
    this.comment = "";
    this.sending = false;
    this.labelText = "";
    this.touched = new Set(); // fields the user changed in the new-issue form
    this.suggesting = false;
    this.checklist = new ChecklistEditor({ dialog: this });
    this.files = new AttachmentsSection({ dialog: this });
    if (this.create) {
      const { index } = store.state;
      const project = index?.projectById.get(projectId) || index?.projects.find((p) => !p.archived);
      this.draft = this.defaults(project, { status, parent });
    }
  }

  defaults(project, { status = "", parent = "" } = {}) {
    return {
      project_id: project?.id || "",
      summary: "",
      description: "",
      type: "task",
      priority: "medium",
      assignee: project?.default_assignee || "",
      labels: [],
      due: "",
      status: status || defaultStatus(project)?.id || "",
      parent,
    };
  }

  open() {
    this.release = store.acquire(store.hass);
    this.unsubscribe = store.subscribe(() => this.onStore());
    this.handle = overlay.dialog(this);
    this.files.bind();
    if (!this.create) this.loadDetail();
    return this;
  }

  onClose() {
    this.files.unbind();
    this.unsubscribe?.();
    this.release?.();
  }

  isTop() {
    return overlay.isTop(this.handle);
  }

  close() {
    this.handle.close();
  }

  update() {
    this.handle?.update();
  }

  get index() {
    return store.state.index;
  }

  get issue() {
    return this.create ? null : this.index?.issueById.get(this.issueId) || null;
  }

  get project() {
    const id = this.create ? this.draft.project_id : this.issue?.project_id;
    return this.index?.projectById.get(id) || null;
  }

  label() {
    return this.create ? t("new_issue") : this.issue ? `${this.issue.key} ${this.issue.summary}` : t("issue");
  }

  // ---- data ----------------------------------------------------------------

  onStore() {
    if (this.closing) return;
    if (!this.create && this.index && !this.issue) {
      overlay.toast({ message: t("toast.issue_gone") });
      this.close();
      return;
    }
    const issue = this.issue;
    if (issue && detailKeyOf(issue) !== this.detailKey) this.loadDetail();
    this.update();
  }

  async loadDetail() {
    const issue = this.issue;
    if (!issue || this.loading) return;
    this.loading = true;
    const key = detailKeyOf(issue);
    try {
      this.detail = await actions.getIssue(this.issueId);
      this.detailKey = key;
    } catch {
      this.detailKey = key; // do not retry in a loop; the next push tries again
    }
    this.loading = false;
    const current = this.issue;
    if (current && detailKeyOf(current) !== this.detailKey) {
      this.loadDetail(); // a push arrived while the request was in flight
      return;
    }
    this.update();
  }

  value(field) {
    if (this.create) return this.draft[field] ?? "";
    const value = this.issue?.[field];
    if (field === "due") return value || "";
    return value ?? "";
  }

  /** Save one field: edit mode writes through, create mode keeps it in the draft. */
  set(field, value) {
    if (this.create) {
      this.draft[field] = value;
      this.touched.add(field);
      if (field === "project_id") Object.assign(this.draft, this.defaults(this.index.projectById.get(value)), { summary: this.draft.summary, description: this.draft.description });
      this.update();
      return;
    }
    const issue = this.issue;
    if (!issue) return;
    if (field === "status") {
      if (value !== issue.status) actions.moveIssue(issue.id, value, null);
      return;
    }
    const wire = field === "assignee" || field === "parent" ? value || null : field === "due" ? value || null : value;
    actions.updateIssue(issue.id, { [field]: wire }).then(() => this.loadDetail());
  }

  commitText(field, element) {
    if (this.create) {
      this.draft[field] = element.value;
      return;
    }
    delete this.draft[field];
    const issue = this.issue;
    const text = field === "summary" ? element.value.trim() : element.value;
    if (issue && text !== (issue[field] || "") && (field !== "summary" || text)) this.set(field, text);
    else this.update(); // restores an emptied summary or an unchanged value
  }

  onEscape() {
    const active = deepActiveElement();
    if (this.checklist.onEscape(active)) return true;
    const field = active?.dataset?.field;
    if (!this.create && field && TEXT_FIELDS.has(field) && field in this.draft && this.draft[field] !== (this.issue?.[field] || "")) {
      delete this.draft[field];
      this.update();
      return true;
    }
    return false;
  }

  /** New-issue form: ask the server for smart defaults for the typed title and fill what is still empty. */
  async suggest() {
    const text = this.draft.summary.trim();
    if (!text || this.suggesting) return;
    this.suggesting = true;
    this.update();
    try {
      const suggestion = await actions.suggest(text, this.project?.key);
      const { fields, filled } = hasSuggestion(suggestion) ? suggestionFill(suggestion, this.draft, { touched: this.touched }) : { fields: {}, filled: [] };
      if (!filled.length) {
        overlay.toast({ message: t("suggest.none") });
      } else {
        Object.assign(this.draft, fields);
        const fields = filled.map((f) => t(`field.${f}`)).join(", ");
        overlay.toast({ message: t("suggest.filled", { fields }) + (suggestion.evidence ? ` (${suggestion.evidence})` : "") });
      }
    } catch (error) {
      overlay.toast({ kind: "error", message: error.message });
    }
    this.suggesting = false;
    this.update();
  }

  async submitCreate() {
    const d = this.draft;
    if (!d.summary.trim() || !d.project_id) return;
    const fields = { project_id: d.project_id, summary: d.summary.trim(), type: d.type, priority: d.priority, labels: d.labels };
    if (d.description.trim()) fields.description = d.description;
    if (d.assignee) fields.assignee = d.assignee;
    if (d.due) fields.due = d.due;
    if (d.status) fields.status = d.status;
    if (d.parent) fields.parent = d.parent;
    const issue = await actions.createIssue(fields);
    if (!issue) return;
    this.close();
    overlay.toast({ message: t("toast.created", { key: issue.key }), action: { label: t("open"), run: () => openIssueDialog(issue.id) } });
  }

  async sendComment() {
    const text = this.comment.trim();
    if (!text || this.sending) return;
    this.sending = true;
    this.update();
    const saved = await actions.addComment(this.issueId, text);
    this.sending = false;
    if (saved) this.comment = "";
    await this.loadDetail();
    this.update();
  }

  async remove() {
    const issue = this.issue;
    const ok = await overlay.confirm({
      title: t("delete_issue"),
      message: t("delete_issue_confirm", { key: issue.key }),
      confirmLabel: t("delete"),
      danger: true,
    });
    if (!ok) return;
    this.closing = true;
    if (await actions.deleteIssue(issue.id)) this.close();
    else this.closing = false;
  }

  async archive() {
    const key = this.issue.key;
    this.closing = true;
    if (await actions.updateIssue(this.issueId, { archived: true })) {
      overlay.toast({ message: t("toast.archived", { key }) });
      this.close();
    } else {
      this.closing = false;
    }
  }

  openMenu(event) {
    const issue = this.issue;
    overlay.menu({
      anchor: event.currentTarget,
      label: t("actions"),
      items: [
        {
          label: t("copy_link"),
          icon: "mdi:link-variant",
          onSelect: () => navigator.clipboard?.writeText(`${location.origin}/homeboard?issue=${issue.key}`).then(() => overlay.toast({ message: t("toast.link_copied") }), () => {}),
        },
        { label: t("archive"), icon: "mdi:archive-outline", onSelect: () => this.archive() },
        { divider: true },
        { label: t("delete"), icon: "mdi:delete-outline", onSelect: () => this.remove() },
      ],
    });
  }

  // ---- fields ----------------------------------------------------------------

  textInput(field, { multiline = false, placeholder = "" } = {}) {
    const props = {
      key: `field-${field}`,
      "data-field": field,
      "aria-label": t(`field.${field}`),
      placeholder,
      value: this.draft[field] ?? this.value(field),
      oninput: (event) => {
        this.draft[field] = event.target.value;
        if (this.create && field === "summary") this.update();
      },
      onchange: (event) => this.commitText(field, event.target),
      onkeydown: (event) => {
        if (event.key === "Enter" && !multiline) {
          event.preventDefault();
          if (this.create) this.submitCreate();
          else event.target.blur();
        }
      },
    };
    return multiline ? h("textarea.input.description", { ...props, rows: 6 }) : h("input.input.summary-input", { ...props, type: "text", maxlength: 200 });
  }

  statusOptions() {
    return (this.project?.statuses || []).map((s) => ({ value: s.id, label: s.name }));
  }

  epicOptions() {
    const projectId = this.project?.id;
    const epics = (this.index?.byProject.get(projectId) || []).filter((i) => i.type === "epic" && i.id !== this.issueId);
    return [{ value: "", label: t("none") }, ...epics.map((e) => ({ value: e.id, label: `${e.key} ${e.summary}` }))];
  }

  labelsField() {
    const labels = this.create ? this.draft.labels : this.issue?.labels || [];
    const suggestions = uniqueSorted([...(this.project?.labels || []), ...labels]);
    const add = (raw) => {
      const next = [...labels];
      for (const part of raw.split(",")) {
        const label = normaliseLabel(part);
        if (label && !next.includes(label)) next.push(label);
      }
      this.labelText = "";
      if (next.length !== labels.length) this.set("labels", next);
      else this.update();
    };
    return h(
      "div.field.wide",
      { key: "field-labels" },
      h("span.field-label", t("field.labels")),
      h("div.labels-edit", labels.map((label) => labelChip(label, { onRemove: (l) => this.set("labels", labels.filter((x) => x !== l)) }))),
      h("input.input", {
        key: "labels-input",
        type: "text",
        list: "hb-label-suggestions",
        placeholder: t("labels.add"),
        "aria-label": t("labels.add"),
        value: this.labelText,
        oninput: (event) => {
          this.labelText = event.target.value;
          if (event.target.value.endsWith(",")) add(event.target.value);
          else this.update();
        },
        onkeydown: (event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            event.stopPropagation();
            if (this.labelText.trim()) add(this.labelText);
          } else if (event.key === "Backspace" && !this.labelText && labels.length) {
            this.set("labels", labels.slice(0, -1));
          }
        },
        onchange: (event) => {
          if (event.target.value.trim()) add(event.target.value);
        },
      }),
      h("datalist", { id: "hb-label-suggestions" }, suggestions.filter((s) => !labels.includes(s)).map((s) => h("option", { key: s, value: s }))),
    );
  }

  dueField() {
    const { date, time } = splitDue(this.value("due"));
    return h(
      "div.field.wide",
      { key: "field-due" },
      h("span.field-label", t("field.due")),
      h(
        "div.due-edit",
        h("input.input", {
          key: "due-date",
          type: "date",
          value: date,
          "aria-label": t("field.due"),
          onchange: (event) => this.set("due", joinDue(event.target.value, event.target.value ? time : "") || ""),
        }),
        h("input.input", {
          key: "due-time",
          type: "time",
          value: time,
          disabled: !date,
          "aria-label": t("due.time"),
          onchange: (event) => this.set("due", joinDue(date, event.target.value) || ""),
        }),
        date ? h("button.icon-btn", { type: "button", "aria-label": t("due.clear"), title: t("due.clear"), onclick: () => this.set("due", "") }, icon("mdi:close-circle-outline")) : null,
      ),
    );
  }

  fields() {
    const issue = this.issue;
    const fields = [];
    if (this.create && this.index.projects.filter((p) => !p.archived).length > 1) {
      fields.push(
        selectField({
          id: "project",
          wide: true,
          label: t("field.project"),
          value: this.draft.project_id,
          options: this.index.projects.filter((p) => !p.archived).map((p) => ({ value: p.id, label: `${p.key} - ${p.name}` })),
          onchange: (v) => this.set("project_id", v),
        }),
      );
    }
    fields.push(
      selectField({ id: "status", label: t("field.status"), value: this.value("status"), options: this.statusOptions(), onchange: (v) => this.set("status", v) }),
      selectField({ id: "assignee", label: t("field.assignee"), value: this.value("assignee"), options: personOptions(this.index), onchange: (v) => this.set("assignee", v) }),
      selectField({ id: "priority", label: t("field.priority"), value: this.value("priority"), options: priorityOptions(), onchange: (v) => this.set("priority", v) }),
      selectField({ id: "type", label: t("field.type"), value: this.value("type"), options: typeOptions(), onchange: (v) => this.set("type", v) }),
      this.labelsField(),
      this.dueField(),
    );
    if (this.value("type") !== "epic") {
      fields.push(selectField({ id: "parent", wide: true, label: t("field.parent"), value: this.value("parent"), options: this.epicOptions(), onchange: (v) => this.set("parent", v) }));
    }
    if (issue) {
      fields.push(
        h(
          "dl.meta.wide",
          { key: "meta" },
          h("dt", t("field.reporter")),
          h("dd", issue.reporter ? personName(this.index, issue.reporter) : "-"),
          h("dt", t("field.created")),
          h("dd", { title: formatDateTime(issue.created) }, relativeTime(issue.created)),
          h("dt", t("field.updated")),
          h("dd", { title: formatDateTime(issue.updated) }, relativeTime(issue.updated)),
        ),
      );
    }
    return fields;
  }

  // ---- sections ----------------------------------------------------------------

  epicChildren() {
    const issue = this.issue;
    const children = issue?.type === "epic" ? this.index.children.get(issue.id) || [] : [];
    if (!children.length) return null;
    return h(
      "section.section",
      { key: "children" },
      h("h3", t("epic.issues", { n: children.length })),
      h(
        "ul.child-list",
        children.map((child) =>
          h(
            "li",
            { key: child.id },
            h(
              "button.child",
              { type: "button", onclick: () => this.navigate(child.id) },
              typeIcon(child.type),
              h("span.key", child.key),
              h("span.child-summary", child.summary),
              h("span.chip.plain", this.index.statusById.get(child.status)?.status.name || ""),
            ),
          ),
        ),
      ),
    );
  }

  navigate(issueId) {
    this.issueId = issueId;
    this.detail = null;
    this.detailKey = "";
    this.loadDetail();
    this.update();
  }

  commentsSection() {
    const comments = this.detail?.comments || [];
    return h(
      "div.thread",
      { key: "comments" },
      comments.length ? null : h("p.muted", this.loading || !this.detail ? t("loading") : t("comments.none")),
      comments.map((c) =>
        h(
          "div.comment",
          { key: c.id },
          avatar(this.index, c.author, "md"),
          h(
            "div.comment-body",
            h("div.comment-head", h("strong", c.author ? personName(this.index, c.author) : t("someone")), h("span.muted", { title: formatDateTime(c.ts) }, relativeTime(c.ts))),
            h("div.comment-text", c.text),
          ),
        ),
      ),
      h(
        "div.comment-new",
        avatar(this.index, store.me, "md"),
        h(
          "div.comment-new-body",
          h("textarea.input", {
            key: "comment-box",
            rows: 2,
            placeholder: t("comments.placeholder"),
            "aria-label": t("comments.placeholder"),
            value: this.comment,
            oninput: (event) => {
              this.comment = event.target.value;
              this.update();
            },
            onkeydown: (event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                event.preventDefault();
                this.sendComment();
              }
            },
          }),
          h("button.btn.primary.small", { key: "comment-send", type: "button", disabled: !this.comment.trim() || this.sending, onclick: () => this.sendComment() }, t("comments.add")),
        ),
      ),
    );
  }

  activitySection() {
    const entries = [...(this.detail?.activity || [])].reverse();
    if (!entries.length) return h("p.muted", { key: "activity" }, this.loading || !this.detail ? t("loading") : t("activity.none_yet"));
    return h(
      "ul.activity",
      { key: "activity" },
      entries.map((entry, i) =>
        h(
          "li",
          { key: `${entry.ts}-${i}` },
          h("strong", entry.actor ? personName(this.index, entry.actor) : t("someone")),
          ` ${describeActivity(entry, this.index)}`,
          h("span.muted", { title: formatDateTime(entry.ts) }, ` ${relativeTime(entry.ts)}`),
        ),
      ),
    );
  }

  // ---- render ----------------------------------------------------------------

  render() {
    const index = this.index;
    if (!index) return dialogShell({ title: t("issue"), onClose: () => this.close(), body: h("p.muted", t("loading")) });
    const issue = this.issue;
    if (!this.create && !issue) return dialogShell({ title: t("issue"), onClose: () => this.close(), body: h("p.muted", t("loading")) });

    const canSuggest = this.create && store.state.payload.settings?.learning?.defaults;
    const head = [
      canSuggest
        ? h(
            "div.summary-row",
            { key: "summary-row" },
            this.textInput("summary", { placeholder: t("summary_placeholder") }),
            h("button.btn.small", { type: "button", disabled: !this.draft.summary.trim() || this.suggesting, title: t("suggest.button_hint"), onclick: () => this.suggest() }, icon("mdi:auto-fix"), t("suggest.button")),
          )
        : this.textInput("summary", { placeholder: t("summary_placeholder") }),
      issue?.source === "health" ? h("p.hint", { key: "auto-hint" }, icon("mdi:robot-outline"), t("auto.hint")) : null,
      h("h3.section-title", { key: "desc-title" }, t("field.description")),
      this.textInput("description", { multiline: true, placeholder: t("description_placeholder") }),
    ];
    const thread = [this.epicChildren()];
    if (!this.create) {
      thread.push(
        this.checklist.render(),
        this.files.render(),
        h(
          "div.tabs.small",
          { key: "tabs", role: "tablist" },
          ["comments", "history"].map((tab) =>
            h(
              "button.tab",
              { key: tab, type: "button", role: "tab", "aria-selected": String(this.tab === tab), class: this.tab === tab ? "active" : "", onclick: () => { this.tab = tab; this.update(); } },
              t(`tab.${tab}`),
              tab === "comments" && issue.comment_count ? h("span.count", issue.comment_count) : null,
            ),
          ),
        ),
        this.tab === "comments" ? this.commentsSection() : this.activitySection(),
      );
    }

    const body = [
      this.files.dragging ? h("div.drop-overlay", { key: "drop-overlay" }, icon("mdi:paperclip"), t("attachments.drop")) : null,
      h("div.issue-layout", { key: "layout" }, h("div.issue-main", h("div.issue-head", head), h("div.issue-thread", thread)), h("div.issue-side", this.fields())),
    ];
    if (this.create) {
      return dialogShell({
        title: t("new_issue"),
        icon: "mdi:plus-circle-outline",
        onClose: () => this.close(),
        body,
        footer: [
          h("button.btn", { type: "button", onclick: () => this.close() }, t("cancel")),
          h("button.btn.primary", { type: "button", disabled: !this.draft.summary.trim() || !this.draft.project_id, onclick: () => this.submitCreate() }, t("create")),
        ],
      });
    }
    return dialogShell({
      headerLeft: [
        h("span.issue-ref", typeIcon(issue.type), h("span.key", issue.key), issue.source === "health" ? autoChip() : null),
        h("span.muted.project-name", this.project?.name || ""),
      ],
      headerRight: h("button.icon-btn", { type: "button", "aria-label": t("actions"), title: t("actions"), "aria-haspopup": "menu", onclick: (event) => this.openMenu(event) }, icon("mdi:dots-horizontal")),
      onClose: () => this.close(),
      body,
    });
  }
}
