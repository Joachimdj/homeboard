// AI Fix section of the issue dialog (PROTOCOL 11, administrators only): state, loading and the calls
// behind the buttons. The picture is drawn by ai-fix-view.js, the decisions are in ai-fix.js.
//
// `homeboard/ai/get` is fetched when the dialog opens and again whenever `issue.ai.rev` changes in the live
// payload (there is no polling: an analysis can take a minute, and the push tells us when it moves).

import { actions } from "./actions.js";
import { NOTE_MAX, aiRev, canAnalyse, confirmKey, errorKey, replaceProposal, sectionVisible } from "./ai-fix.js";
import { aiFixSection } from "./ai-fix-view.js";
import { deepActiveElement } from "./dom.js";
import { t } from "./i18n.js";
import { overlay } from "./overlay.js";
import { store } from "./store.js";

function messageOf(error) {
  if (error?.code === "unauthorized") return t("error.unauthorized");
  const key = errorKey(error?.code);
  return key ? t(key) : error?.message || t("error.generic");
}

/** navigator.clipboard only exists on https and localhost; a Home Assistant on plain http needs the old way. */
async function copyText(text) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // fall through to the textarea trick
  }
  const previous = deepActiveElement();
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    Object.assign(area.style, { position: "fixed", top: "0", left: "0", opacity: "0" });
    document.body.append(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  } catch {
    return false;
  } finally {
    previous?.focus?.({ preventScroll: true });
  }
}

export class AiFixSection {
  constructor({ dialog }) {
    this.dialog = dialog;
    this.disposed = false;
    this.token = 0; // changes when the dialog moves to another issue; late answers for the old one are dropped
    this.on = {
      analyse: () => this.analyse(),
      toggleNote: (event) => this.toggleNote(event),
      note: (value) => this.setNote(value),
      preview: () => this.togglePreview(),
      retry: () => this.retry(),
      apply: (proposal, event) => this.ask(proposal, event),
      confirm: (proposal) => this.act("apply", proposal),
      cancel: (proposal, event) => this.cancel(proposal, event),
      dismiss: (proposal) => this.act("dismiss", proposal),
      undo: (proposal) => this.act("undo", proposal),
      copy: (proposal) => this.copy(proposal),
    };
    this.reset();
  }

  /** New issue in the same dialog (an epic's child), or the first start. */
  reset() {
    this.token += 1;
    this.info = null; // the ai/get result
    this.requested = null; // key of the last fetch (issue, rev, entity)
    this.loading = false;
    this.refetch = false;
    this.fetchSeq = 0;
    this.loadError = null;
    this.analysing = false;
    this.busy = null; // { id, action } of an apply / undo / dismiss in flight
    this.preview = null; // { loading } | { error } | { data }
    this.previewSeq = 0;
    this.confirming = null;
    this.error = null;
    this.note = "";
    this.noteOpen = false;
    this.root = null;
  }

  dispose() {
    this.disposed = true;
    this.token += 1;
  }

  get enabled() {
    return !this.disposed && Boolean(this.dialog.issue) && sectionVisible({ aiFix: store.state.payload?.settings?.ai_fix, isAdmin: store.isAdmin, create: this.dialog.create });
  }

  get working() {
    return this.analysing || Boolean(this.busy) || Boolean(this.preview?.loading);
  }

  update() {
    if (!this.disposed) this.dialog.update();
  }

  // ---- loading ----------------------------------------------------------------------------------

  key() {
    const entity = store.state.payload?.settings?.ai_fix?.entity || "";
    return `${this.dialog.issueId}|${aiRev(this.dialog.issue) ?? ""}|${entity}`;
  }

  /** Called on open, after every push and when the dialog moves to another issue. */
  sync() {
    if (this.enabled && !this.loading && this.key() !== this.requested) this.load();
  }

  async load() {
    const { token } = this;
    const key = this.key();
    this.loading = true;
    try {
      const info = await actions.aiGet(this.dialog.issueId);
      if (token !== this.token) return;
      this.info = info;
      this.loadError = null;
    } catch (error) {
      if (token !== this.token) return;
      this.loadError = messageOf(error); // the key is remembered below, so a failing server is not asked in a loop
    }
    this.loading = false;
    this.fetchSeq += 1;
    this.requested = this.refetch ? null : key;
    this.refetch = false;
    this.sync(); // a push arrived while the request was in flight
    this.update();
  }

  retry() {
    this.requested = null;
    this.loadError = null;
    this.sync();
    this.update();
  }

  /** A call failed: show it in the section and as a toast, and look at the truth again. */
  fail(error) {
    const message = messageOf(error);
    this.error = message;
    overlay.toast({ kind: "error", message });
    this.requested = null;
    if (this.loading) this.refetch = true;
    else this.sync();
  }

  // ---- the note and the preview --------------------------------------------------------------------

  toggleNote(event) {
    this.noteOpen = !this.noteOpen;
    this.root = event?.currentTarget?.getRootNode?.() || this.root;
    this.update();
    if (this.noteOpen) this.root?.querySelector?.("[data-ai-note]")?.focus({ preventScroll: true }); // ready to type
  }

  setNote(value) {
    this.note = String(value).slice(0, NOTE_MAX);
    if (this.preview) {
      this.previewSeq += 1; // what was shown is no longer what would be sent
      this.preview = null;
    }
    this.update();
  }

  async togglePreview() {
    if (this.preview?.data) {
      this.preview = null;
      this.update();
      return;
    }
    if (this.working) return;
    const { token } = this;
    const seq = ++this.previewSeq;
    this.preview = { loading: true };
    this.error = null;
    this.update();
    try {
      const data = await actions.aiPreview(this.dialog.issueId, this.note.trim());
      if (token !== this.token || seq !== this.previewSeq) return;
      this.preview = { data };
    } catch (error) {
      if (token !== this.token || seq !== this.previewSeq) return;
      const message = messageOf(error);
      this.preview = { error: message };
      overlay.toast({ kind: "error", message });
    }
    this.update();
  }

  // ---- analyse -------------------------------------------------------------------------------------

  async analyse() {
    if (!canAnalyse(this.info, { running: this.info?.record?.state === "running", working: this.working })) return;
    const { token } = this;
    const seq = this.fetchSeq;
    this.analysing = true;
    this.error = null;
    this.preview = null; // it was only there to be read before sending
    this.previewSeq += 1;
    this.update();
    try {
      await actions.aiAnalyze(this.dialog.issueId, this.note.trim());
      if (token !== this.token) return;
      // The push with the new `rev` brings the real record; until then show "running" (unless it already did).
      if (this.fetchSeq === seq && this.info) this.info = { ...this.info, ready: false, record: { ...(this.info.record || {}), state: "running", error: null } };
    } catch (error) {
      if (token !== this.token) return;
      this.fail(error);
    }
    this.analysing = false;
    this.update();
  }

  // ---- proposals -----------------------------------------------------------------------------------

  /** Apply, first press: ask again (not needed for checklist items), then focus the confirm button. */
  ask(proposal, event) {
    if (this.working) return;
    if (!confirmKey(proposal.kind)) {
      this.act("apply", proposal);
      return;
    }
    this.root = event?.currentTarget?.getRootNode?.() || null;
    this.confirming = proposal.id;
    this.update();
    this.focus("[data-ai-confirm]", "aiConfirm", proposal.id);
  }

  cancel(proposal, event) {
    this.root = event?.currentTarget?.getRootNode?.() || this.root;
    this.confirming = null;
    this.update();
    this.focus("[data-ai-apply]", "aiApply", proposal.id);
  }

  focus(selector, dataKey, id) {
    [...(this.root?.querySelectorAll?.(selector) || [])].find((el) => el.dataset[dataKey] === String(id))?.focus({ preventScroll: true });
  }

  /** Escape closes the confirm row first. Returns true when it did something. */
  onEscape() {
    if (this.confirming == null) return false;
    const id = this.confirming;
    this.confirming = null;
    this.update();
    this.focus("[data-ai-apply]", "aiApply", id);
    return true;
  }

  async act(action, proposal) {
    if (this.busy || this.analysing) return;
    const { token } = this;
    const call = { apply: actions.aiApply, undo: actions.aiUndo, dismiss: actions.aiDismiss }[action];
    this.busy = { id: proposal.id, action };
    this.confirming = null;
    this.error = null;
    this.update();
    try {
      const result = await call(this.dialog.issueId, proposal.id);
      if (token !== this.token) return;
      if (result?.proposal && this.info) this.info = { ...this.info, record: replaceProposal(this.info.record, result.proposal) };
      if (action === "apply") overlay.toast({ message: t(proposal.kind === "manual_steps" ? "ai.toast.checklist" : "ai.toast.applied") });
      else if (action === "undo") overlay.toast({ message: t("ai.toast.undone") });
      if (action !== "dismiss") this.dialog.loadDetail(); // a comment, an activity line, maybe checklist items
    } catch (error) {
      if (token !== this.token) return;
      this.fail(error);
    }
    this.busy = null;
    this.update();
  }

  async copy(proposal) {
    const ok = await copyText(String(proposal.new_yaml || ""));
    overlay.toast(ok ? { message: t("ai.copied") } : { kind: "error", message: t("ai.copy_failed") });
  }

  // ---- view ------------------------------------------------------------------------------------------

  render() {
    if (!this.enabled) return null;
    return aiFixSection(
      {
        info: this.info,
        loadError: this.loadError,
        analysing: this.analysing,
        working: this.working,
        busy: this.busy,
        note: this.note,
        noteOpen: this.noteOpen,
        preview: this.preview,
        confirming: this.confirming,
        error: this.error,
      },
      this.on,
    );
  }
}
