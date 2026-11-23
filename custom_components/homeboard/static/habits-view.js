// View of the Habits inbox in the Insights tab: plain functions from data to vnodes, no state, no network.
// Everything that comes from the backend (title, detail, YAML, alias, error messages, entity ids) is
// UNTRUSTED text: it is only ever passed as a child string (a text node), never as HTML, and it never
// becomes a class name, a translation key, an element name or a link target. Those come from the fixed
// lists and the checked path in habits.js.

import { icon } from "./components.js";
import { h } from "./dom.js";
import { createdList, canCreate, confirmKey, habitsState, ideaView, lastScanError, scanOutcomeText, statusLine } from "./habits.js";
import { t } from "./i18n.js";
import { formatDateTime, relativeTime } from "./util.js";

const miniSpin = () => h("span.mini-spin", { "aria-hidden": "true" });

function button(label, { variant = "", iconName = null, busy = false, disabled = false, onclick, attrs = {} }) {
  return h(
    `button.btn.small${variant ? `.${variant}` : ""}`,
    { type: "button", disabled: disabled || busy, "aria-busy": busy ? "true" : null, onclick, ...attrs },
    busy ? miniSpin() : iconName ? icon(iconName) : null,
    label,
  );
}

const errorLine = (message) => (message ? h("p.habit-error", { role: "alert" }, icon("mdi:alert-circle-outline"), h("span", message)) : null);

/** Question, Confirm, Cancel. Escape cancels (and does not reach anything else). */
function confirmRow({ id, action, working, on, onConfirm }) {
  return h(
    "div.habit-confirm",
    {
      key: `confirm-${id}`,
      role: "group",
      "aria-label": t(`habits.confirm_group_${action}`),
      onkeydown: (event) => {
        if (event.key !== "Escape") return;
        event.stopPropagation();
        on.cancel(event);
      },
    },
    h("p.habit-confirm-text", t(confirmKey(action))),
    h(
      "div.habit-actions",
      button(t("habits.confirm"), { variant: "primary", iconName: "mdi:check", disabled: working, onclick: onConfirm, attrs: { "data-habit-confirm": id } }),
      button(t("cancel"), { disabled: working, onclick: (event) => on.cancel(event) }),
    ),
  );
}

// ---- one idea ---------------------------------------------------------------------------------------

/** ctx: { canCreate, working, busy: {id, action}|null, confirming: {kind, id}|null, errors: Map, on } */
export function ideaCard(suggestion, ctx) {
  const { on } = ctx;
  const view = ideaView(suggestion);
  const { id } = view;
  const mine = ctx.busy?.id === id ? ctx.busy.action : null;
  const working = Boolean(ctx.working);
  const confirming = ctx.canCreate && ctx.confirming?.kind === "create" && ctx.confirming.id === id;

  const actions = confirming
    ? confirmRow({ id, action: "create", working, on, onConfirm: () => on.confirmCreate(suggestion) })
    : h(
        "div.habit-actions",
        { key: `actions-${id}` },
        ctx.canCreate ? button(t("habits.create"), { variant: "primary", iconName: "mdi:plus", busy: mine === "create", disabled: working, onclick: (event) => on.askCreate(suggestion, event), attrs: { "data-habit-create": id } }) : null,
        button(t("insights.dismiss"), { iconName: "mdi:close", busy: mine === "dismiss", disabled: working, onclick: () => on.dismiss(suggestion), attrs: { "data-habit-dismiss": id } }),
      );

  return h(
    "article.suggestion-card.idea-card",
    { key: id, "data-idea": id },
    h("h4", icon(view.pattern.icon), h("span.idea-title", view.title)),
    view.detail ? h("p.idea-detail", view.detail) : null,
    h("p.idea-evidence.muted.small", h("span.chip.plain.idea-pattern", t(view.pattern.labelKey)), view.evidence ? t("insights.evidence", { text: view.evidence }) : null),
    view.yaml
      ? h(
          "details.idea-yaml",
          h("summary", icon("mdi:code-braces"), t("habits.show_yaml")),
          h("div.yaml-box", { role: "region", tabindex: "0", "aria-label": t("habits.yaml_label") }, h("pre.yaml", view.yaml)),
          h("div.habit-actions", button(t("habits.copy_yaml"), { iconName: "mdi:content-copy", onclick: () => on.copy(view.yaml) })),
        )
      : null,
    h("p.idea-note.muted.small", icon("mdi:toggle-switch-off-outline"), h("span", t("habits.off_note"))),
    errorLine(ctx.errors?.get(id)),
    actions,
  );
}

// ---- created automations --------------------------------------------------------------------------

/** `view` comes from createdList(). ctx: { canManage, working, busy, confirming, errors, on } */
export function createdRow(view, ctx) {
  const { on } = ctx;
  const { id } = view;
  const mine = ctx.busy?.id === id ? ctx.busy.action : null;
  const working = Boolean(ctx.working);
  const confirming = ctx.canManage && ctx.confirming?.kind === "undo" && ctx.confirming.id === id;
  const when = view.ts ? relativeTime(view.ts) : "";
  const stateLabel = t(view.state === "undone" ? "habits.state.undone" : "habits.state.created");

  let actions = null;
  if (confirming) {
    actions = confirmRow({ id, action: "undo", working, on, onConfirm: () => on.confirmUndo(view) });
  } else if (ctx.canManage && view.state === "created") {
    actions = h(
      "div.habit-actions",
      { key: `actions-${id}` },
      view.editPath
        ? h("a.btn.small", { href: view.editPath, onclick: (event) => on.open(view.editPath, event), "data-habit-open": id }, icon("mdi:open-in-new"), t("habits.open_ha"))
        : null,
      view.canUndo ? button(t("undo"), { iconName: "mdi:undo", busy: mine === "undo", disabled: working, onclick: (event) => on.askUndo(view, event), attrs: { "data-habit-undo": id } }) : null,
    );
  }

  return h(
    "li.created-row",
    { key: id || `row-${view.alias}`, class: view.state === "created" ? "" : "muted-row", "data-created": id },
    h(
      "div.created-main",
      h("strong.created-alias", view.alias || t("habits.created.unnamed")),
      view.state === "unknown" ? null : h("span.chip.plain", { class: `state-${view.state}` }, stateLabel),
    ),
    view.state === "undone"
      ? h("p.created-line.muted.small", icon("mdi:undo"), h("span", t("habits.undone_line")))
      : when
        ? h("p.created-line.muted.small", { title: formatDateTime(view.ts) }, t("habits.created_line", { time: when }))
        : null,
    errorLine(ctx.errors?.get(id)),
    actions,
  );
}

// ---- status and scan ---------------------------------------------------------------------------------

/** model: { habits, canManage, working, scan: { running, outcome, error } } */
function statusRow(model, on) {
  const { scan } = model;
  const outcomeText = scan.outcome ? scanOutcomeText(scan.outcome) : "";
  const kept = !scan.outcome && !scan.error ? lastScanError(model.habits) : "";
  const result = scan.error
    ? h("p.habit-scan-result.error", { role: "alert" }, icon("mdi:alert-circle-outline"), h("span", scan.error))
    : outcomeText
      ? h("p.habit-scan-result", { class: scan.outcome.kind === "error" ? "error" : "", role: scan.outcome.kind === "error" ? "alert" : "status" }, icon(scan.outcome.kind === "error" ? "mdi:alert-circle-outline" : "mdi:check-circle-outline"), h("span", outcomeText))
      : kept
        ? h("p.habit-scan-result.error", icon("mdi:alert-circle-outline"), h("span", kept))
        : null;
  return h(
    "div.habit-status",
    { key: "habit-status" },
    h(
      "div.habit-status-main",
      h("p.habit-status-line.muted.small", icon("mdi:history"), h("span", statusLine(model.habits))),
      model.canManage
        ? button(scan.running ? t("habits.scanning") : t("habits.scan"), { iconName: "mdi:magnify-scan", busy: scan.running, disabled: model.working, onclick: () => on.scan(), attrs: { "data-habit-scan": "" } })
        : null,
    ),
    h("div.habit-scan-live", { "aria-live": "polite" }, result),
  );
}

/**
 * The whole inbox section, or null when the backend has no `features.habits` (0.3).
 * model: { features, habits, ideas, isAdmin, working, busy, confirming, errors, scan }
 */
export function inboxSection(model, on) {
  const state = habitsState(model.features);
  if (state === "absent") return null;
  const title = h("h3", icon("mdi:inbox-arrow-down"), t("habits.title"), state === "on" ? h("span.count", model.ideas.length) : null);

  if (state === "off") {
    return h(
      "section.panel-section.inbox",
      { key: "inbox" },
      title,
      h("div.habit-off", icon("mdi:information-outline"), h("div", h("p", t("habits.off_body")), h("p.muted.small", t("habits.off_history")))),
    );
  }

  const manage = canCreate(model.isAdmin, model.features);
  const ctx = { canCreate: manage, canManage: manage, working: model.working, busy: model.busy, confirming: model.confirming, errors: model.errors, on };
  const created = createdList(model.habits?.created);
  return h(
    "section.panel-section.inbox",
    { key: "inbox" },
    title,
    h("p.muted.habit-intro", t("habits.intro")),
    model.habits ? statusRow({ habits: model.habits, canManage: manage, working: model.working, scan: model.scan }, on) : null,
    model.ideas.length ? h("div.suggestion-list.idea-list", model.ideas.map((suggestion) => ideaCard(suggestion, ctx))) : h("p.muted.habit-none", t("habits.none")),
    created.length
      ? h(
          "div.habit-created",
          { key: "habit-created" },
          h("h4.habit-sub", t("habits.created_title"), h("span.count", created.length)),
          h("p.muted.small", t("habits.created_note")),
          h("ul.created-list", created.map((view) => createdRow(view, ctx))),
        )
      : null,
  );
}
