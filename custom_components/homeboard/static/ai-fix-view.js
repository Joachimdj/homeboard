// View of the AI Fix section in the issue dialog: plain functions from data to vnodes, no state, no
// network. Everything that comes from the model or the backend is UNTRUSTED text (PROTOCOL 11.1): it is
// only ever passed as a child string (a text node) or into an attribute through setAttribute, and never
// becomes a class name, a translation key or an element name. Those come from the fixed lists in ai-fix.js.

import { NOTE_MAX, applyLabel, confidenceLabel, confirmKey, formatCount, kindLabel, notReadyKey, parseDiff, proposalActions, riskLabel, riskLevel, statusKind, summarisePreview, summariseSent } from "./ai-fix.js";
import { icon, spinner } from "./components.js";
import { h } from "./dom.js";
import { t, tn } from "./i18n.js";
import { cx, formatDateTime, relativeTime } from "./util.js";

const text = (value) => (typeof value === "string" ? value : value == null ? "" : String(value));
const miniSpin = () => h("span.mini-spin", { "aria-hidden": "true" });

// ---- diff -------------------------------------------------------------------------------------

/** Unified diff: + green, - red, @@ muted. Scrolls sideways inside its own box. */
export function diffView(diff) {
  const lines = parseDiff(diff);
  if (!lines.length) return null;
  return h(
    "div.ai-diff",
    { role: "region", tabindex: "0", "aria-label": t("ai.diff") },
    h("div.ai-diff-lines", lines.map((line) => h(`div.dl.${line.kind}`, line.text === "" ? " " : line.text))),
  );
}

// ---- one proposal -----------------------------------------------------------------------------

function button(label, { variant = "", iconName = null, busy = false, disabled = false, onclick, attrs = {} }) {
  return h(
    `button.btn.small${variant ? `.${variant}` : ""}`,
    { type: "button", disabled: disabled || busy, "aria-busy": busy ? "true" : null, onclick, ...attrs },
    busy ? miniSpin() : iconName ? icon(iconName) : null,
    label,
  );
}

function stateLine(proposal, status) {
  if (status === "applied") {
    const key = proposal.kind === "manual_steps" ? "ai.status.applied_checklist" : "ai.status.applied";
    return h("p.ai-state.applied", { title: formatDateTime(proposal.applied_at) }, icon("mdi:check-circle-outline"), t(key, { time: relativeTime(proposal.applied_at) }).trim());
  }
  if (status === "undone") {
    return h("p.ai-state", { title: formatDateTime(proposal.undone_at) }, icon("mdi:undo"), t("ai.status.undone", { time: relativeTime(proposal.undone_at) }).trim());
  }
  if (status === "dismissed") return h("p.ai-state", icon("mdi:close-circle-outline"), t("ai.status.dismissed"));
  if (status === "failed") {
    const error = text(proposal.error).trim();
    return h("p.ai-state.failed", { role: "alert" }, icon("mdi:alert-circle-outline"), error ? t("ai.status.failed", { error }) : t("ai.status.failed_plain"));
  }
  return null;
}

/** ctx: { working, busy: {id, action}|null, confirming: id|null, on: { apply, confirm, cancel, dismiss, undo, copy } } */
export function proposalCard(proposal, ctx) {
  const { on } = ctx;
  const id = text(proposal.id);
  const status = statusKind(proposal.status);
  const buttons = proposalActions(proposal);
  const confirming = ctx.confirming === proposal.id && buttons.includes("apply");
  const closed = status === "dismissed" || status === "undone";
  const mine = ctx.busy?.id === proposal.id ? ctx.busy.action : null;
  const off = Boolean(ctx.working);
  const targetName = text(proposal.target_name).trim() || text(proposal.target).trim();
  const warnings = Array.isArray(proposal.warnings) ? proposal.warnings.filter((w) => text(w).trim()) : [];
  const steps = Array.isArray(proposal.steps) ? proposal.steps.filter((s) => text(s).trim()) : [];
  const question = confirmKey(proposal.kind);

  const actionRow = confirming
    ? h(
        "div.ai-confirm",
        { role: "group", "aria-label": t("ai.confirm_group") },
        h("p.ai-confirm-text", t(question)),
        h(
          "div.ai-p-actions",
          button(t("ai.confirm"), { variant: "primary", iconName: "mdi:check", disabled: off, onclick: () => on.confirm(proposal), attrs: { "data-ai-confirm": id } }),
          button(t("cancel"), { disabled: off, onclick: (event) => on.cancel(proposal, event) }),
        ),
      )
    : buttons.length
      ? h(
          "div.ai-p-actions",
          buttons.map((name) => {
            if (name === "apply") return button(t(applyLabel(proposal.kind)), { variant: "primary", busy: mine === "apply", disabled: off, onclick: (event) => on.apply(proposal, event), attrs: { key: "apply", "data-ai-apply": id } });
            if (name === "dismiss") return button(t("ai.dismiss"), { busy: mine === "dismiss", disabled: off, onclick: () => on.dismiss(proposal), attrs: { key: "dismiss" } });
            if (name === "undo") return button(t("undo"), { iconName: "mdi:undo", busy: mine === "undo", disabled: off, onclick: () => on.undo(proposal), attrs: { key: "undo" } });
            return button(t("ai.copy_yaml"), { iconName: "mdi:content-copy", disabled: false, onclick: () => on.copy(proposal), attrs: { key: "copy" } });
          }),
        )
      : null;

  return h(
    "article.ai-proposal",
    { key: id, class: cx(`status-${status}`, `risk-${riskLevel(proposal.risk)}`), "data-proposal": id },
    h(
      "div.ai-p-head",
      h("h4.ai-p-title", text(proposal.title)),
      h("div.ai-p-chips", h(`span.chip.risk-${riskLevel(proposal.risk)}`, t(riskLabel(proposal.risk))), h("span.chip.plain", t(kindLabel(proposal.kind)))),
    ),
    text(proposal.explanation).trim() ? h("p.ai-p-text", text(proposal.explanation)) : null,
    targetName
      ? h("p.ai-p-target", icon("mdi:target"), h("span", t("ai.target", { name: targetName })), proposal.target && text(proposal.target) !== targetName ? h("code", text(proposal.target)) : null)
      : null,
    !closed && warnings.length ? h("ul.ai-warnings", { "aria-label": t("ai.warnings") }, warnings.map((w) => h("li", icon("mdi:alert-outline"), h("span", text(w))))) : null,
    proposal.blocked && status === "proposed"
      ? h("div.ai-blocked", { role: "note" }, icon("mdi:shield-lock-outline"), h("div", h("strong", t("ai.blocked_title")), h("p", text(proposal.blocked.message))))
      : null,
    !closed && steps.length ? h("ol.ai-steps", { "aria-label": t("ai.steps") }, steps.map((s) => h("li", text(s)))) : null,
    !closed ? diffView(proposal.diff) : null,
    stateLine(proposal, status),
    actionRow,
  );
}

// ---- parts of the section -------------------------------------------------------------------

function countsLine(counts) {
  const parts = [
    tn("ai.n_chars", counts.chars, { n: formatCount(counts.chars) }),
    tn("ai.n_entities", counts.entities, { n: formatCount(counts.entities) }),
    tn("ai.n_automations", counts.automations, { n: formatCount(counts.automations) }),
  ];
  if ("redactions" in counts) parts.push(tn("ai.n_redactions", counts.redactions, { n: formatCount(counts.redactions) }));
  return parts.join(" · ");
}

function entityName(info) {
  return text(info?.entity_name).trim() || text(info?.entity).trim() || t("ai.entity_fallback");
}

function previewBlock(model) {
  const { preview, info } = model;
  if (!preview) return null;
  const where = t("ai.preview_where", { entity: entityName(info) });
  if (preview.loading) return h("div.ai-preview", { key: "ai-preview", "aria-busy": "true" }, h("p.ai-busy", miniSpin(), t("ai.preview_loading")));
  if (preview.error) return h("div.ai-preview", { key: "ai-preview" }, h("p.error-text", { role: "alert" }, preview.error));
  const counts = summarisePreview(preview.data);
  return h(
    "div.ai-preview",
    { key: "ai-preview" },
    h("p.ai-where", icon("mdi:information-outline"), h("span", where)),
    counts ? h("p.muted.small", countsLine(counts)) : null,
    h("pre.ai-prompt", { tabindex: "0", "aria-label": t("ai.preview_label") }, text(preview.data?.prompt)),
  );
}

function diagnosisBlock(record, info) {
  const confidence = confidenceLabel(record.confidence);
  const sent = summariseSent(record.sent);
  const note = text(record.note).trim();
  return h(
    "div.ai-diagnosis",
    h("div.ai-diag-head", h("strong", t("ai.diagnosis")), confidence ? h("span.chip.plain.confidence", { title: t("ai.confidence_title") }, t(confidence)) : null),
    h("p.ai-diag-text", text(record.diagnosis)),
    sent
      ? h("p.muted.small", t("ai.sent", { chars: tn("ai.n_chars", sent.chars, { n: formatCount(sent.chars) }), entities: tn("ai.n_entities", sent.entities, { n: formatCount(sent.entities) }), automations: tn("ai.n_automations", sent.automations, { n: formatCount(sent.automations) }), entity: entityName(info) }))
      : null,
    note ? h("p.muted.small.ai-your-note", t("ai.note_yours", { note })) : null,
  );
}

// ---- the section ----------------------------------------------------------------------------------

/**
 * model: { info, loadError, analysing, working, busy, note, noteOpen, preview, confirming, error }
 * on: { analyse, toggleNote, note, preview, retry, apply, confirm, cancel, dismiss, undo, copy }
 */
export function aiFixSection(model, on) {
  const { info, loadError } = model;
  const record = info?.record || null;
  const running = Boolean(model.analysing) || record?.state === "running";
  const working = Boolean(model.working);
  const reason = notReadyKey(info, running);
  const noteLength = model.note.trim().length;
  const previewing = Boolean(model.preview?.loading);
  const failed = record?.state === "failed";
  const proposals = record && !running && Array.isArray(record.proposals) ? record.proposals : [];

  const head = h("div.section-head", icon("mdi:creation"), h("h3", t("ai.title")));

  const loadBlock = loadError
    ? h("div.ai-load-error", { key: "ai-load-error" }, h("p.error-text", { role: "alert" }, t("ai.load_error", { message: loadError })), h("button.btn.small", { type: "button", onclick: () => on.retry() }, t("retry")))
    : null;
  if (!info) return h("section.section.ai-fix", { key: "ai-fix", "aria-label": t("ai.title") }, head, loadBlock || h("p.muted", { key: "ai-loading" }, t("loading")));

  const controls = h(
    "div.ai-actions",
    { key: "ai-actions" },
    h(
      "button.btn.primary.small",
      { key: "ai-analyse", type: "button", disabled: !info.ready || running || working, "aria-busy": running ? "true" : null, onclick: () => on.analyse() },
      running ? miniSpin() : icon("mdi:creation"),
      running ? t("ai.analysing") : record ? t("ai.analyse_again") : t("ai.analyse"),
    ),
    h(
      "button.btn.small",
      { key: "ai-note-toggle", type: "button", "aria-expanded": String(Boolean(model.noteOpen)), onclick: (event) => on.toggleNote(event) },
      icon(model.noteOpen ? "mdi:chevron-up" : "mdi:message-text-outline"),
      t("ai.note_toggle"),
      noteLength ? h("span.count", String(noteLength)) : null,
    ),
    h(
      "button.btn.small",
      { key: "ai-preview-toggle", type: "button", disabled: working && !previewing, "aria-busy": previewing ? "true" : null, "aria-expanded": String(Boolean(model.preview?.data)), onclick: () => on.preview() },
      previewing ? miniSpin() : icon(model.preview?.data ? "mdi:eye-off-outline" : "mdi:eye-outline"),
      previewing ? t("ai.preview_loading") : model.preview?.data ? t("ai.preview_hide") : t("ai.preview_show"),
    ),
  );

  const noteBox = model.noteOpen
    ? h(
        "div.ai-note",
        { key: "ai-note" },
        h("textarea.input", {
          key: "ai-note-input",
          rows: 3,
          maxlength: NOTE_MAX,
          value: model.note,
          placeholder: t("ai.note_placeholder"),
          "aria-label": t("ai.note_label"),
          "data-ai-note": "",
          oninput: (event) => on.note(event.target.value),
        }),
        h("span.ai-note-count.muted.small", t("ai.note_count", { n: model.note.length, max: NOTE_MAX })),
      )
    : null;

  const status = h(
    "div.ai-status",
    { key: "ai-status", "aria-live": "polite" },
    running ? h("div.ai-running", spinner(t("ai.analysing")), h("span", t("ai.analysing"))) : null,
    failed && !running
      ? h("p.ai-failed", { role: "alert" }, icon("mdi:alert-circle-outline"), text(record.error).trim() ? t("ai.failed", { error: text(record.error).trim() }) : t("ai.failed_plain"))
      : null,
    model.error ? h("p.error-text", { role: "alert" }, model.error) : null,
  );

  const cardCtx = { working, busy: model.busy, confirming: model.confirming, on };
  const result =
    record?.state === "ready" && !running
      ? [diagnosisBlock(record, info), proposals.length ? h("h4.ai-sub", t("ai.proposals")) : h("p.muted", t("ai.no_proposals"))]
      : [];

  return h(
    "section.section.ai-fix",
    { key: "ai-fix", "aria-label": t("ai.title") },
    head,
    reason ? h("p.ai-reason", { key: "ai-reason" }, icon("mdi:information-outline"), h("span", t(reason, info.limit || {}))) : null,
    loadBlock,
    controls,
    noteBox,
    previewBlock(model),
    status,
    result,
    proposals.length ? h("div.ai-proposals", { key: "ai-proposals" }, proposals.map((p) => proposalCard(p, cardCtx))) : null,
  );
}
