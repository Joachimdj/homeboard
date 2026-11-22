// Checklist section of the issue dialog: add with Enter, tick, edit in place,
// remove, reorder by dragging the handle or with the move buttons / Alt+Arrows.
// Items come from `issue/get`; changes are applied to the dialog's copy at once
// and written through homeboard/checklist/*.

import { actions } from "./actions.js";
import { icon, progressBar } from "./components.js";
import { h } from "./dom.js";
import { t } from "./i18n.js";
import { CHECKLIST_MAX_ITEMS, CHECKLIST_TEXT_MAX, checklistProgress, moveBy, moveIndex, rowIndexAt, splitItems } from "./checklist.js";
import { cx } from "./util.js";

let tempCounter = 0;

export class ChecklistEditor {
  constructor({ dialog }) {
    this.dialog = dialog;
    this.draft = "";
    this.order = null; // item ids while a drag is in progress
    this.drag = null;
  }

  get issueId() {
    return this.dialog.issueId;
  }

  get items() {
    const items = this.dialog.detail?.checklist || [];
    if (!this.order) return items;
    const byId = new Map(items.map((item) => [item.id, item]));
    return this.order.map((id) => byId.get(id)).filter(Boolean);
  }

  setItems(items) {
    this.dialog.detail = { ...this.dialog.detail, checklist: items };
    this.dialog.update();
  }

  counts(items) {
    const { done, total } = checklistProgress(items.filter((item) => !item.pending));
    return { done, total };
  }

  /** The write failed: fetch the truth again. */
  recover() {
    this.dialog.loadDetail();
  }

  // ---- operations ---------------------------------------------------------------

  async add(text) {
    const room = CHECKLIST_MAX_ITEMS - this.items.length;
    for (const line of splitItems(text).slice(0, Math.max(0, room))) {
      const temp = { id: `pending-${++tempCounter}`, text: line, done: false, pending: true };
      this.setItems([...this.items, temp]);
      const created = await actions.addChecklistItem(this.issueId, line, this.counts([...this.items.filter((i) => i.id !== temp.id), { ...temp, pending: false }]));
      if (created) this.setItems(this.items.map((item) => (item.id === temp.id ? created : item)));
      else this.setItems(this.items.filter((item) => item.id !== temp.id));
    }
  }

  async toggle(item, done) {
    const items = this.items.map((i) => (i.id === item.id ? { ...i, done } : i));
    this.setItems(items);
    if (!(await actions.updateChecklistItem(this.issueId, item.id, { done }, this.counts(items)))) this.recover();
  }

  async rename(item, text) {
    const clean = text.trim();
    if (!clean || clean === item.text) {
      this.dialog.update(); // restores an emptied or unchanged text
      return;
    }
    this.setItems(this.items.map((i) => (i.id === item.id ? { ...i, text: clean } : i)));
    if (!(await actions.updateChecklistItem(this.issueId, item.id, { text: clean }))) this.recover();
  }

  async remove(item) {
    const items = this.items.filter((i) => i.id !== item.id);
    this.setItems(items);
    if (!(await actions.removeChecklistItem(this.issueId, item.id, this.counts(items)))) this.recover();
  }

  async reorder(ids) {
    const byId = new Map(this.items.map((item) => [item.id, item]));
    this.setItems(ids.map((id) => byId.get(id)));
    if (!(await actions.reorderChecklist(this.issueId, ids))) this.recover();
  }

  /** Move one step; keyboard focus follows the item (the row's node is moved, which drops focus). */
  move(item, delta, event, focusSelector) {
    const root = event.currentTarget.getRootNode();
    const ids = this.items.map((i) => i.id);
    const next = moveBy(ids, item.id, delta);
    if (next === ids) return;
    this.reorder(next);
    requestAnimationFrame(() => {
      const row = [...root.querySelectorAll(".check-item")].find((li) => li.dataset.id === item.id);
      (row?.querySelector(`${focusSelector}:not([disabled])`) || row?.querySelector(".item-text"))?.focus();
    });
  }

  // ---- dragging the handle --------------------------------------------------------

  startDrag(event, item) {
    if (item.pending || (event.pointerType === "mouse" && event.button !== 0)) return;
    const list = event.currentTarget.closest("ul");
    try {
      list.setPointerCapture(event.pointerId); // keeps the move events coming while the rows are re-ordered under the finger
    } catch {
      // the pointer is already gone (cancelled); the drag then ends with the next pointer event
    }
    this.drag = { id: item.id, original: this.items.map((i) => i.id) };
    this.order = this.drag.original;
    event.preventDefault();
    this.dialog.update();
  }

  dragMove(event) {
    if (!this.drag) return;
    const rows = [...event.currentTarget.querySelectorAll(":scope > li")];
    const index = rowIndexAt(rows.map((row) => [row.getBoundingClientRect().top, row.getBoundingClientRect().bottom]), event.clientY);
    const next = moveIndex(this.order, this.order.indexOf(this.drag.id), index);
    if (next !== this.order) {
      this.order = next;
      this.dialog.update();
    }
  }

  dragEnd(commit) {
    if (!this.drag) return;
    const { original } = this.drag;
    const order = this.order;
    this.drag = null;
    this.order = null;
    if (commit && order.join() !== original.join()) this.reorder(order);
    else this.dialog.update();
  }

  /** Escape: cancel a drag or revert an edited item. Returns true when it did something. */
  onEscape(active) {
    if (this.drag) {
      this.dragEnd(false);
      return true;
    }
    const id = active?.dataset?.checklistItem;
    const item = id && this.items.find((i) => i.id === id);
    if (item && active.value !== item.text) {
      active.value = item.text;
      return true;
    }
    return false;
  }

  // ---- view ------------------------------------------------------------------------

  row(item, index, items) {
    const dragging = this.drag?.id === item.id;
    return h(
      "li.check-item",
      { key: item.id, "data-id": item.id, class: cx(item.done && "done", dragging && "dragging", item.pending && "pending") },
      h("button.drag-handle", { type: "button", "aria-label": t("checklist.drag", { text: item.text }), title: t("checklist.drag", { text: item.text }), disabled: item.pending, onpointerdown: (event) => this.startDrag(event, item) }, icon("mdi:drag-vertical")),
      h("input.check-box", { type: "checkbox", checked: item.done, disabled: item.pending, "aria-label": t("checklist.done_toggle", { text: item.text }), onchange: (event) => this.toggle(item, event.target.checked) }),
      h("input.input.item-text", {
        type: "text",
        value: item.text,
        maxlength: CHECKLIST_TEXT_MAX,
        disabled: item.pending,
        "aria-label": t("checklist.item"),
        "data-checklist-item": item.id,
        onchange: (event) => this.rename(item, event.target.value),
        onkeydown: (event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            event.target.blur();
          } else if (event.altKey && (event.key === "ArrowUp" || event.key === "ArrowDown")) {
            event.preventDefault();
            this.move(item, event.key === "ArrowUp" ? -1 : 1, event, ".item-text");
          }
        },
      }),
      h("button.icon-btn.small.move-up", { type: "button", disabled: item.pending || index === 0, "aria-label": t("checklist.move_up", { text: item.text }), title: t("checklist.move_up", { text: item.text }), onclick: (event) => this.move(item, -1, event, ".move-up") }, icon("mdi:arrow-up")),
      h("button.icon-btn.small.move-down", { type: "button", disabled: item.pending || index === items.length - 1, "aria-label": t("checklist.move_down", { text: item.text }), title: t("checklist.move_down", { text: item.text }), onclick: (event) => this.move(item, 1, event, ".move-down") }, icon("mdi:arrow-down")),
      h("button.icon-btn.small", { type: "button", disabled: item.pending, "aria-label": t("checklist.remove", { text: item.text }), title: t("checklist.remove", { text: item.text }), onclick: () => this.remove(item) }, icon("mdi:close")),
    );
  }

  render() {
    const items = this.items;
    const { done, total, percent } = checklistProgress(items.filter((item) => !item.pending));
    const full = items.length >= CHECKLIST_MAX_ITEMS;
    return h(
      "section.section.checklist",
      { key: "checklist" },
      h("div.section-head", h("h3", t("checklist.title")), total ? h("span.muted.small", t("checklist.progress", { done, total })) : null),
      total ? progressBar(percent, t("checklist.progress", { done, total })) : null,
      !this.dialog.detail
        ? h("p.muted", t("loading"))
        : items.length
          ? h(
              "ul.checklist-items",
              {
                onpointermove: (event) => this.dragMove(event),
                onpointerup: () => this.dragEnd(true),
                onpointercancel: () => this.dragEnd(false),
              },
              items.map((item, index) => this.row(item, index, items)),
            )
          : h("p.muted.small", t("checklist.empty")),
      h("input.input.checklist-add", {
        key: "checklist-add",
        type: "text",
        value: this.draft,
        disabled: full,
        maxlength: 2000,
        placeholder: full ? t("checklist.full", { max: CHECKLIST_MAX_ITEMS }) : t("checklist.add"),
        "aria-label": t("checklist.add_label"),
        oninput: (event) => {
          this.draft = event.target.value;
          this.dialog.update(); // keeps the rendered value in step, so clearing it later takes effect
        },
        onkeydown: (event) => {
          if (event.key === "Enter" && this.draft.trim()) {
            event.preventDefault();
            const text = this.draft;
            this.draft = "";
            this.dialog.update();
            this.add(text);
          }
        },
        onpaste: (event) => {
          const text = event.clipboardData?.getData("text") || "";
          if (!/\r?\n/.test(text.trim())) return; // single lines paste as usual
          event.preventDefault();
          this.add(text);
        },
      }),
    );
  }
}
