// Status overview: project tiles with stacked bars, home health, issues per
// person, overdue / due-soon lists. Used by the panel's Summary tab and by the
// homeboard-status-card.

import { avatar, dueChip, emptyState, icon, typeIcon } from "./components.js";
import { h } from "./dom.js";
import { t, tn } from "./i18n.js";
import { learningEnabled } from "./insights.js";
import { attentionIssues, barSegments, healthStats, peopleStats, projectStats } from "./stats.js";
import { relativeTime } from "./util.js";

function stackedBar(stats) {
  const segments = barSegments(stats);
  const label = stats.byStatus.map((s) => `${s.status.name}: ${s.count}`).join(", ");
  return [
    h(
      "div.stack",
      { role: "img", "aria-label": label },
      segments.length
        ? segments.map((seg) => h("span.seg", { key: seg.status.id, "data-category": seg.status.category, style: { flexGrow: seg.count, "--shade": seg.shade }, title: `${seg.status.name}: ${seg.count}` }))
        : h("span.seg.empty", { style: { flexGrow: 1 } }),
    ),
    h(
      "ul.legend",
      stats.byStatus.map(({ status, count }) =>
        h("li", { key: status.id }, h("span.swatch", { "data-category": status.category }), h("span.legend-name", status.name), h("strong", count)),
      ),
    ),
  ];
}

function metric(value, label, tone, onclick) {
  return h("button.metric", { type: "button", class: tone && value ? tone : "", onclick }, h("strong", value), h("span", label));
}

function projectTile(stats, ctx) {
  const { project } = stats;
  const open = (filter) => () => ctx.onOpenBoard(project.id, filter);
  return h(
    "section.tile",
    { key: `project-${project.id}`, style: { "--project-color": project.color || "var(--primary-color)" } },
    h(
      "header.tile-head",
      h("span.project-dot"),
      h("button.tile-title", { type: "button", onclick: open({}), "aria-label": `${t("tile.open_board")}: ${project.name}` }, h("strong", project.name), h("span.key", project.key)),
      h("span.spacer"),
      h("span.muted.small", { title: stats.lastActivity || "" }, stats.lastActivity ? t("tile.last_activity", { when: relativeTime(stats.lastActivity) }) : t("tile.no_activity")),
    ),
    stackedBar(stats),
    h(
      "div.metrics",
      metric(stats.open, t("metric.open"), "", open({})),
      metric(stats.overdue, t("metric.overdue"), "bad", open({ overdue: true })),
      metric(stats.dueSoon, t("metric.due_soon"), "warn", open({ dueSoon: true })),
      metric(stats.unassigned, t("metric.unassigned"), "", open({ unassigned: true })),
    ),
  );
}

function healthTile(health, ctx) {
  return h(
    "section.tile.health",
    { key: "health" },
    h(
      "header.tile-head",
      icon("mdi:robot-outline"),
      h("strong", t("health.title")),
      h("span.spacer"),
      h("span.muted.small", t("health.subtitle")),
    ),
    health.open
      ? h(
          "div.health-body",
          h("button.big-number", { type: "button", onclick: () => ctx.onOpenBoard(health.projectIds[0] || null, { auto: true }), "aria-label": t("health.open_board") }, h("strong", health.open), h("span", tn("health.open_issues", health.open))),
          h(
            "div.metrics.small-metrics",
            metric(health.high, t("health.high"), "bad", () => ctx.onOpenBoard(health.projectIds[0] || null, { auto: true, priority: "high" })),
            metric(health.security, t("health.security"), "warn", () => ctx.onOpenBoard(health.projectIds[0] || null, { auto: true, label: "security" })),
          ),
        )
      : h("p.health-ok", icon("mdi:check-circle-outline"), t("health.all_good")),
  );
}

function insightsTile(open, ctx) {
  return h(
    "section.tile.insights",
    { key: "insights" },
    h("header.tile-head", icon("mdi:lightbulb-on-outline"), h("strong", t("insights.tile_title")), h("span.spacer"), h("span.muted.small", t("insights.tile_subtitle"))),
    h(
      "button.big-number.wide",
      { type: "button", onclick: () => ctx.onOpenInsights(), "aria-label": t("insights.tile_open") },
      h("strong", open),
      h("span", open ? tn("insights.tile", open) : t("insights.tile_none")),
    ),
  );
}

function peopleSection(rows, ctx) {
  return h(
    "section.panel-section",
    { key: "people" },
    h("h3", t("summary.people")),
    h(
      "div.people",
      rows.map((row) =>
        h(
          "button.person-row",
          { key: row.id, type: "button", onclick: () => ctx.onOpenBoard(null, { assignee: row.id === "unassigned" ? "unassigned" : row.id }), "aria-label": `${row.name || t("unassigned")}: ${tn("summary.open_count", row.open)}` },
          avatar(ctx.index, row.id === "unassigned" ? null : row.id, "md"),
          h("span.person-name", row.name || t("unassigned")),
          h("span.stat", h("strong", row.open), h("span", t("metric.open"))),
          h("span.stat", { class: row.overdue ? "bad" : "" }, h("strong", row.overdue), h("span", t("metric.overdue"))),
          h("span.stat", h("strong", row.inProgress), h("span", t("metric.in_progress"))),
          h("span.stat", h("strong", row.done7d), h("span", t("metric.done_7d"))),
        ),
      ),
    ),
  );
}

function issueList(title, iconName, issues, ctx, tone) {
  return h(
    "section.panel-section",
    { key: `list-${tone}` },
    h("h3", { class: tone }, icon(iconName), title, h("span.count", issues.length)),
    issues.length
      ? h(
          "ul.issue-list",
          issues.slice(0, 12).map((issue) =>
            h(
              "li",
              { key: issue.id },
              h(
                "button.issue-line",
                { type: "button", onclick: () => ctx.onOpenIssue(issue) },
                typeIcon(issue.type),
                h("span.key", issue.key),
                h("span.line-summary", issue.summary),
                dueChip(issue, ctx.now),
                avatar(ctx.index, issue.assignee, "sm"),
              ),
            ),
          ),
        )
      : h("p.muted.small", t("summary.nothing")),
  );
}

/**
 * ctx: { payload, index, now, projectIds?, showPeople, showHealth, showInsights, showAttention,
 *        onOpenBoard(projectId|null, filter), onOpenInsights(), onOpenIssue(issue) }
 */
export function renderSummary(ctx) {
  const { payload, index } = ctx;
  const projects = index.projects.filter((p) => !p.archived && (!ctx.projectIds || ctx.projectIds.includes(p.id) || ctx.projectIds.includes(p.key)));
  const health = healthStats(payload, index);
  const showHealth = ctx.showHealth && (payload.settings?.health_enabled || health.open > 0);
  const showInsights = ctx.showInsights && learningEnabled(payload.settings);
  const tiles = [
    showHealth ? healthTile(health, ctx) : null,
    showInsights ? insightsTile(payload.settings.insights_open || 0, ctx) : null,
    ...projects.map((p) => projectTile(projectStats(payload, index, p), ctx)),
  ];

  if (!projects.length && !showHealth && !showInsights) return h("div.summary", emptyState("mdi:view-dashboard-outline", t("summary.no_projects"), t("summary.no_projects_hint")));

  const attention = ctx.showAttention ? attentionIssues(index, projects.map((p) => p.id)) : null;
  return h(
    "div.summary",
    h("div.tiles", tiles),
    ctx.showPeople ? peopleSection(peopleStats(payload, index), ctx) : null,
    attention
      ? h(
          "div.attention",
          issueList(t("summary.overdue"), "mdi:alert-circle-outline", attention.overdue, ctx, "bad"),
          issueList(t("summary.due_soon"), "mdi:clock-outline", attention.dueSoon, ctx, "warn"),
        )
      : null,
  );
}
