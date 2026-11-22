// Board and backlog rendering. Pure vnode builders; the BoardController in
// board-controller.js owns the state (drag, collapsed lanes) and the events.

import { attachmentChip, autoChip, avatar, checklistChip, dueChip, emptyState, epicBar, icon, labelChip, priorityIcon, typeIcon } from "./components.js";
import { h } from "./dom.js";
import { t } from "./i18n.js";
import { categoryOf, personName } from "./indexes.js";
import { cx } from "./util.js";

function laneLabel(lane, index) {
  if (lane.kind === "person") return [avatar(index, lane.value, "sm"), h("span.lane-name", personName(index, lane.value))];
  if (lane.kind === "unassigned") return [avatar(index, null, "sm"), h("span.lane-name", t("unassigned"))];
  return [priorityIcon(lane.value), h("span.lane-name", t(`priority.${lane.value}`))];
}

function columnHead(status, count, ctx) {
  const over = status.wip != null && count > status.wip;
  return h(
    "div.col-head",
    { key: `head-${status.id}`, "data-category": status.category },
    h("span.col-name", status.name),
    status.wip != null
      ? h("span.wip", { class: over ? "over" : "", title: t("wip.title", { wip: status.wip }), "aria-label": t("wip.label", { count, wip: status.wip }) }, `${count}/${status.wip}`)
      : h("span.count", count),
    h("span.spacer"),
    h(
      "button.icon-btn.col-add",
      { type: "button", "aria-label": t("add_to_status", { status: status.name }), title: t("add_to_status", { status: status.name }), onclick: () => ctx.onAdd(status) },
      icon("mdi:plus"),
    ),
  );
}

function focusNeighbour(card, key) {
  const cell = card.parentElement;
  const cards = [...cell.querySelectorAll(":scope > .card")];
  const position = cards.indexOf(card);
  let target = null;
  if (key === "ArrowDown") target = cards[position + 1];
  else if (key === "ArrowUp") target = cards[position - 1];
  else {
    const cells = [...cell.parentElement.querySelectorAll(":scope > .cell")].filter((c) => c.dataset.lane === cell.dataset.lane);
    const next = cells[cells.indexOf(cell) + (key === "ArrowRight" ? 1 : -1)];
    const nextCards = next ? [...next.querySelectorAll(":scope > .card")] : [];
    target = nextCards[Math.min(position, nextCards.length - 1)];
  }
  target?.focus();
  return Boolean(target);
}

function onCardKey(event, issue, ctx) {
  if (event.target !== event.currentTarget) return;
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    ctx.onOpen(issue);
  } else if (event.key === "m" || event.key === "M" || event.key === "ContextMenu") {
    event.preventDefault();
    ctx.onMenu(issue, event.currentTarget.querySelector(".card-menu") || event.currentTarget);
  } else if (event.key.startsWith("Arrow") && focusNeighbour(event.currentTarget, event.key)) {
    event.preventDefault();
  }
}

function menuButton(issue, ctx) {
  return h(
    "button.icon-btn.card-menu",
    {
      type: "button",
      "aria-label": `${t("move_to")} ${issue.key}`,
      "aria-haspopup": "menu",
      title: t("move_to"),
      onclick: (event) => {
        event.stopPropagation();
        ctx.onMenu(issue, event.currentTarget);
      },
    },
    icon("mdi:dots-vertical"),
  );
}

function issueCard(issue, ctx) {
  const { index, drag, now } = ctx;
  const epic = issue.parent ? index.issueById.get(issue.parent) : null;
  const labels = issue.labels || [];
  return h(
    "div.card",
    {
      key: issue.id,
      "data-id": issue.id,
      role: "listitem",
      tabindex: "0",
      class: cx(categoryOf(index, issue) === "done" && "done", drag?.issueId === issue.id && "is-source", issue.overdue && "is-overdue"),
      "aria-label": `${issue.key} ${issue.summary}`,
      onclick: (event) => {
        if (!event.target.closest("button")) ctx.onOpen(issue);
      },
      onkeydown: (event) => onCardKey(event, issue, ctx),
    },
    h("div.card-top", typeIcon(issue.type), h("span.key", issue.key), h("span.spacer"), priorityIcon(issue.priority), menuButton(issue, ctx)),
    h("div.card-summary", issue.summary),
    epicBar(issue),
    labels.length || issue.source === "health" ? h("div.card-labels", issue.source === "health" ? autoChip() : null, labels.filter((l) => l !== "auto").map((l) => labelChip(l))) : null,
    h(
      "div.card-foot",
      dueChip(issue, now),
      epic ? h("span.chip.epic", { title: epic.summary }, icon("mdi:lightning-bolt"), epic.key) : null,
      checklistChip(issue),
      attachmentChip(issue),
      issue.comment_count ? h("span.chip.plain", { title: t("comments") }, icon("mdi:comment-outline"), issue.comment_count) : null,
      h("span.spacer"),
      avatar(index, issue.assignee, "sm"),
    ),
  );
}

function issueRow(issue, ctx) {
  const { index, drag, now } = ctx;
  const labels = (issue.labels || []).filter((l) => l !== "auto");
  return h(
    "div.card.row",
    {
      key: issue.id,
      "data-id": issue.id,
      role: "listitem",
      tabindex: "0",
      class: cx(categoryOf(index, issue) === "done" && "done", drag?.issueId === issue.id && "is-source"),
      "aria-label": `${issue.key} ${issue.summary}`,
      onclick: (event) => {
        if (!event.target.closest("button")) ctx.onOpen(issue);
      },
      onkeydown: (event) => onCardKey(event, issue, ctx),
    },
    typeIcon(issue.type),
    h("span.key", issue.key),
    h("span.row-summary", issue.summary),
    issue.source === "health" ? autoChip() : null,
    labels.length ? h("span.row-labels", labels.map((l) => labelChip(l))) : null,
    checklistChip(issue),
    attachmentChip(issue),
    dueChip(issue, now),
    priorityIcon(issue.priority),
    avatar(index, issue.assignee, "sm"),
    menuButton(issue, ctx),
  );
}

function cellView(status, lane, issues, ctx, variant) {
  const { drag } = ctx;
  const marker = drag && drag.status === status.id && drag.lane === lane.id;
  const children = [];
  for (const issue of issues) {
    if (marker && drag.before === issue.id) children.push(h("div.drop-marker", { key: "__marker" }));
    children.push(variant === "row" ? issueRow(issue, ctx) : issueCard(issue, ctx));
  }
  if (marker && !issues.some((i) => i.id === drag.before)) children.push(h("div.drop-marker", { key: "__marker" }));
  return h(
    "div.cell",
    {
      key: `cell-${lane.id}-${status.id}`,
      role: "list",
      "aria-label": status.name,
      "data-status": status.id,
      "data-lane": lane.id,
      "data-category": status.category,
      class: marker ? "drop-target" : "",
    },
    children,
  );
}

/**
 * ctx: { index, project, model, drag, narrow, kiosk, layout, collapsed, now, maxHeight,
 *        boardRef, onOpen, onMenu, onAdd, onToggleLane }
 */
export function renderBoard(ctx) {
  const { model, layout, index } = ctx;
  const boardClass = cx("board", ctx.narrow && "narrow", ctx.drag && "dragging", layout === "backlog" && "list", ctx.kiosk && "kiosk");
  const style = ctx.maxHeight ? { maxHeight: ctx.maxHeight } : null;
  const common = { key: `board-${ctx.project.id}-${layout}`, ref: ctx.boardRef, class: boardClass, style, role: "region", "aria-label": ctx.project.name };

  if (!model.statuses.length) {
    return h(
      "div.board",
      common,
      layout === "backlog"
        ? emptyState("mdi:tray-full", t("backlog.no_status"), t("backlog.no_status_hint"))
        : emptyState("mdi:view-column-outline", t("board.no_status")),
    );
  }

  if (layout === "backlog") {
    const lane = model.lanes[0];
    return h(
      "div.board",
      common,
      h(
        "div.list-grid",
        model.statuses.map((status) =>
          h(
            "section.list-section",
            { key: `section-${status.id}` },
            columnHead(status, model.counts.get(status.id) || 0, ctx),
            cellView(status, lane, lane.byStatus.get(status.id) || [], ctx, "row"),
          ),
        ),
      ),
    );
  }

  const cells = [];
  for (const lane of model.lanes) {
    if (lane.kind !== "all") {
      const collapsed = ctx.collapsed.has(lane.id);
      cells.push(
        h(
          "div.lane-head",
          { key: `lane-${lane.id}` },
          h(
            "button.lane-toggle",
            { type: "button", "aria-expanded": String(!collapsed), onclick: () => ctx.onToggleLane(lane.id) },
            icon(collapsed ? "mdi:chevron-right" : "mdi:chevron-down"),
            laneLabel(lane, index),
            h("span.count", lane.issues.length),
          ),
        ),
      );
      if (collapsed) continue;
    }
    for (const status of model.statuses) cells.push(cellView(status, lane, lane.byStatus.get(status.id) || [], ctx, "card"));
  }

  return h(
    "div.board",
    common,
    h(
      "div.grid",
      { class: model.lanes.length === 1 && model.lanes[0].kind === "all" ? "single" : "", style: { "--cols": model.statuses.length } },
      model.statuses.map((status) => columnHead(status, model.counts.get(status.id) || 0, ctx)),
      cells,
    ),
  );
}
