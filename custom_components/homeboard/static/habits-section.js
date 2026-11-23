// State and calls behind the Habits inbox in the Insights tab (PROTOCOL 12, administrators for everything that
// creates or removes something). The picture is drawn by habits-view.js, the decisions are in habits.js.
//
// The ideas themselves are suggestions of kind `automation` in `homeboard/insights/get`, which the
// InsightsController already loads (and loads again when `settings.insights_open` changes in the live payload).
// This class only adds: the confirm step, the busy state, errors per card, the scan and the copy button.
// One call at a time: while Create, Undo, Dismiss or a scan runs, every one of those buttons is disabled
// (two writes to automations.yaml must never overlap, and a scan replaces the ideas Create refers to).

import { actions } from "./actions.js";
import { copyText } from "./clipboard.js";
import { errorInfo, errorText, scanOutcome } from "./habits.js";
import { inboxSection } from "./habits-view.js";
import { t } from "./i18n.js";
import { overlay } from "./overlay.js";

/** Same-tab navigation inside Home Assistant, the way the cards do it (history + `location-changed`). */
function navigateHa(path) {
  history.pushState(null, "", path);
  window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
}

const plainClick = (event) => !event || (event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey);

export class HabitsSection {
  /**
   * insights: the InsightsController (refresh / dismiss). requestRender: re-render the panel.
   * deps: replaces the calls, toasts, clipboard and navigation (the tests do that).
   */
  constructor({ insights, requestRender, deps = {} }) {
    this.insights = insights;
    this.requestRender = requestRender;
    this.deps = { actions, toast: (toast) => overlay.toast(toast), copyText, navigate: navigateHa, ...deps };
    this.busy = null; // { id, action: "create" | "undo" | "dismiss" }
    this.confirming = null; // { kind: "create" | "undo", id }
    this.errors = new Map(); // card or row id -> text shown inline
    this.scan = { running: false, outcome: null, error: null };
    this.root = null; // shadow root, to find a button again after a render
    this.on = {
      askCreate: (suggestion, event) => this.ask("create", suggestion.id, event),
      confirmCreate: (suggestion) => this.create(suggestion),
      askUndo: (view, event) => this.ask("undo", view.id, event),
      confirmUndo: (view) => this.undo(view),
      cancel: (event) => this.cancel(event),
      dismiss: (suggestion) => this.dismiss(suggestion),
      copy: (yaml) => this.copy(yaml),
      open: (path, event) => this.open(path, event),
      scan: () => this.scanNow(),
    };
  }

  get working() {
    return Boolean(this.busy) || this.scan.running;
  }

  update() {
    this.requestRender();
  }

  // ---- confirm step --------------------------------------------------------------------------------------

  ask(kind, id, event) {
    if (this.working) return;
    this.root = event?.currentTarget?.getRootNode?.() || this.root;
    this.confirming = { kind, id };
    this.errors.delete(id);
    this.update();
    this.focusLater("[data-habit-confirm]", "habitConfirm", id);
  }

  cancel(event) {
    const confirming = this.confirming;
    this.root = event?.currentTarget?.getRootNode?.() || this.root;
    this.confirming = null;
    this.update();
    if (confirming) this.focusLater(confirming.kind === "create" ? "[data-habit-create]" : "[data-habit-undo]", confirming.kind === "create" ? "habitCreate" : "habitUndo", confirming.id);
  }

  /** The panel renders on the next animation frame; ours is registered after it, so the element exists by then. */
  focusLater(selector, dataKey, id) {
    globalThis.requestAnimationFrame?.(() => {
      [...(this.root?.querySelectorAll?.(selector) || [])].find((el) => el.dataset[dataKey] === String(id))?.focus({ preventScroll: true });
    });
  }

  // ---- calls ----------------------------------------------------------------------------------------------

  /** A call failed: inline on the card or row, as a toast, and look at the truth again. */
  fail(id, error) {
    const message = errorText(errorInfo(error));
    this.errors.set(id, message);
    this.deps.toast({ kind: "error", message });
    return this.insights.refresh();
  }

  async create(suggestion) {
    if (this.working) return;
    const { id } = suggestion;
    this.busy = { id, action: "create" };
    this.confirming = null;
    this.errors.delete(id);
    this.update();
    try {
      const result = await this.deps.actions.habitsCreate(id);
      const alias = result?.created?.alias || suggestion.proposal?.alias || suggestion.title || "";
      this.deps.toast({ message: t("habits.toast.created", { alias }) });
      await this.insights.refresh(); // the idea is gone from insights/get now (and from the live badge)
    } catch (error) {
      await this.fail(id, error);
    }
    this.busy = null;
    this.update();
  }

  async undo(view) {
    if (this.working) return;
    const { id } = view;
    this.busy = { id, action: "undo" };
    this.confirming = null;
    this.errors.delete(id);
    this.update();
    try {
      const result = await this.deps.actions.habitsUndo(id);
      this.deps.toast({ message: t("habits.toast.undone", { alias: result?.created?.alias || view.alias }) });
      await this.insights.refresh();
    } catch (error) {
      await this.fail(id, error);
    }
    this.busy = null;
    this.update();
  }

  async dismiss(suggestion) {
    if (this.working) return;
    this.busy = { id: suggestion.id, action: "dismiss" };
    this.confirming = null;
    this.update();
    await this.insights.dismiss(suggestion); // toast, refetch and error toast as for every other suggestion
    this.busy = null;
    this.update();
  }

  async scanNow() {
    if (this.working) return;
    this.scan = { running: true, outcome: null, error: null };
    this.confirming = null;
    this.update();
    try {
      this.scan = { running: false, outcome: scanOutcome(await this.deps.actions.habitsScan()), error: null };
    } catch (error) {
      const message = errorText(errorInfo(error));
      this.scan = { running: false, outcome: null, error: message };
      this.deps.toast({ kind: "error", message });
    }
    await this.insights.refresh();
    this.update();
  }

  async copy(yaml) {
    const ok = await this.deps.copyText(String(yaml || ""));
    this.deps.toast(ok ? { message: t("habits.copied") } : { kind: "error", message: t("habits.copy_failed") });
  }

  open(path, event) {
    if (!plainClick(event)) return; // ctrl / cmd / middle click: the browser opens the link in a new tab
    event?.preventDefault?.();
    this.deps.navigate(path);
  }

  // ---- view -------------------------------------------------------------------------------------------------

  /** `data` = the insights/get result, ideas = its automation suggestions. Null when this Homeboard has no habits. */
  render(data, ideas, isAdmin) {
    return inboxSection(
      {
        features: data.features,
        habits: data.learned?.habits || null,
        ideas,
        isAdmin,
        working: this.working,
        busy: this.busy,
        confirming: this.confirming,
        errors: this.errors,
        scan: this.scan,
      },
      this.on,
    );
  }
}
