// The Insights tab: open suggestions, then what Homeboard has learned per
// enabled feature, each with a plain statement of the data it uses.

import { avatar, emptyState, icon, labelChip } from "./components.js";
import { h } from "./dom.js";
import { splitSuggestions } from "./habits.js";
import { t, tn } from "./i18n.js";
import { personName } from "./indexes.js";
import {
  LEARNED_FEATURES,
  averageBars,
  evidenceText,
  formatDays,
  formatMinutes,
  heatPercent,
  normaliseGrid,
  personIssueBars,
  topLabelBars,
  workloadRows,
} from "./insights.js";
import { weekdayLabel } from "./recurring.js";

const HEAT_STEPS = [0, 0.25, 0.5, 0.75, 1];

function bar(percent, label) {
  return h("span.bar", { "aria-hidden": "true" }, h("span.bar-fill", { style: { width: `${percent}%` } }), label ? h("span.bar-label", label) : null);
}

function suggestionCard(suggestion, ctx) {
  const evidence = evidenceText(suggestion.kind, suggestion.evidence);
  return h(
    "article.suggestion-card",
    { key: suggestion.id },
    h("h4", icon("mdi:lightbulb-on-outline"), suggestion.title),
    suggestion.detail ? h("p", suggestion.detail) : null,
    evidence ? h("p.muted.small", t("insights.evidence", { text: evidence })) : null,
    h(
      "div.card-actions",
      h("button.btn.primary.small", { type: "button", onclick: () => ctx.controller.accept(suggestion) }, icon("mdi:check"), t("insights.accept")),
      h("button.btn.small", { type: "button", onclick: () => ctx.controller.dismiss(suggestion) }, icon("mdi:close"), t("insights.dismiss")),
    ),
  );
}

function barList(entries, render) {
  return h("ul.bar-list", entries.map(render));
}

function defaultsBody(learned, ctx) {
  const labels = topLabelBars(learned);
  const people = personIssueBars(learned, ctx.index);
  if (!learned.issues_analysed) return h("p.muted", t("insights.empty_learned"));
  return [
    h("p", tn("insights.defaults.analysed", learned.issues_analysed)),
    h("h5", t("insights.defaults.top_labels")),
    labels.length ? barList(labels, (l) => h("li", { key: l.name }, labelChip(l.name), bar(l.percent), h("strong", l.value))) : h("p.muted.small", t("insights.none_yet")),
    h("h5", t("insights.defaults.people")),
    people.length ? barList(people, (p) => h("li", { key: p.id }, h("span.person-cell", avatar(ctx.index, p.id, "sm"), p.name), bar(p.percent), h("strong", p.value))) : h("p.muted.small", t("insights.none_yet")),
  ];
}

function typeName(name) {
  const key = `type.${name}`;
  return t(key) === key ? name : t(key);
}

function workloadBody(learned, ctx) {
  const rows = workloadRows(learned, ctx.index);
  const types = averageBars(learned.types);
  const labels = averageBars(learned.labels);
  if (!rows.length && !types.length) return h("p.muted", t("insights.empty_learned"));
  return [
    rows.length
      ? h(
          "table.learn-table",
          h("thead", h("tr", h("th", { scope: "col" }, t("insights.workload.person")), h("th", { scope: "col" }, t("insights.workload.open")), h("th", { scope: "col" }, t("insights.workload.done30")), h("th", { scope: "col" }, t("insights.workload.avg")))),
          h(
            "tbody",
            rows.map((row) => h("tr", { key: row.id }, h("th", { scope: "row" }, h("span.person-cell", avatar(ctx.index, row.id, "sm"), row.name)), h("td", row.open), h("td", row.done30d), h("td", formatDays(row.avgDays)))),
          ),
        )
      : null,
    types.length ? [h("h5", t("insights.workload.types")), barList(types, (b) => h("li", { key: b.name }, h("span.bar-name", typeName(b.name)), bar(b.percent), h("strong", formatDays(b.value))))] : null,
    labels.length ? [h("h5", t("insights.workload.labels")), barList(labels, (b) => h("li", { key: b.name }, labelChip(b.name), bar(b.percent), h("strong", formatDays(b.value))))] : null,
  ];
}

function heatMap(person, grid, ctx) {
  const days = Array.from({ length: 7 }, (_, d) => weekdayLabel(d));
  const rows = normaliseGrid(grid);
  const name = personName(ctx.index, person);
  return h(
    "div.heat-wrap",
    { key: person },
    h("h5", t("insights.rhythm.person", { name })),
    h(
      "div.heat",
      { role: "img", "aria-label": t("insights.rhythm.person", { name }) },
      h("span.heat-corner"),
      Array.from({ length: 24 }, (_, hour) => h("span.heat-hour", { key: `h${hour}`, "aria-hidden": "true" }, hour % 3 === 0 ? String(hour) : "")),
      rows.flatMap((row, day) => [
        h("span.heat-day", { key: `d${day}`, "aria-hidden": "true" }, days[day]),
        ...row.map((value, hour) =>
          h("span.heat-cell", { key: `c${day}-${hour}`, "aria-hidden": "true", style: { "--heat": heatPercent(value) }, title: t("insights.rhythm.cell", { day: days[day], hour: String(hour).padStart(2, "0"), percent: heatPercent(value) }) }),
        ),
      ]),
    ),
  );
}

function rhythmBody(learned, ctx) {
  const people = Object.entries(learned.people || {});
  const samples = people.reduce((n, [, p]) => n + (p.samples || 0), 0);
  return [
    h("p", t("insights.rhythm.explain")),
    h(
      "div.heat-legend",
      h("span.muted.small", t("insights.rhythm.away")),
      HEAT_STEPS.map((step) => h("span.heat-cell", { key: step, "aria-hidden": "true", style: { "--heat": heatPercent(step) } })),
      h("span.muted.small", t("insights.rhythm.home")),
    ),
    samples ? people.map(([person, data]) => heatMap(person, data.grid, ctx)) : h("p.muted", t("insights.empty_learned")),
  ];
}

function healthBody(learned) {
  if (!learned.tracked_sensors && !learned.silent?.length && !learned.flapping?.length) return h("p.muted", t("insights.empty_learned"));
  return [
    h("p", tn("insights.health.tracked", learned.tracked_sensors || 0)),
    h("h5", t("insights.health.silent")),
    learned.silent?.length
      ? h(
          "ul.plain-list",
          learned.silent.map((s) => h("li", { key: s.entity_id }, h("code", s.entity_id), h("span.muted", ` ${t("insights.health.silent_row", { minutes: formatMinutes(s.silent_minutes), normal: formatMinutes(s.normal_minutes) })}`))),
        )
      : h("p.muted.small", t("insights.health.none_silent")),
    h("h5", t("insights.health.flapping")),
    learned.flapping?.length
      ? h("ul.plain-list", learned.flapping.map((f) => h("li", { key: f.key }, f.summary, h("span.muted", ` ${tn("insights.health.reopened", f.reopened)}`))))
      : h("p.muted.small", t("insights.health.none_flapping")),
  ];
}

function habitsBody() {
  return h("p.muted.small", t("insights.habits.forget_note"));
}

const BODIES = { defaults: defaultsBody, workload: workloadBody, rhythm: rhythmBody, health: healthBody, habits: habitsBody };

function featureCard(feature, ctx) {
  const learned = ctx.data.learned?.[feature];
  return h(
    "article.learn-card",
    { key: feature, "data-feature": feature },
    h(
      "header.learn-head",
      h("h4", t(`insights.feature.${feature}`)),
      ctx.isAdmin ? h("button.btn.small.ghost", { type: "button", "aria-label": t("insights.forget_title", { feature: t(`insights.feature.${feature}`) }), onclick: () => ctx.controller.forget(feature) }, icon("mdi:eraser"), t("insights.forget")) : null,
    ),
    h("p.uses", h("strong", `${t("insights.uses")} `), t(`insights.data.${feature}`)),
    BODIES[feature] && learned ? BODIES[feature](learned, ctx) : null,
  );
}

function patternsCard(ctx) {
  return h(
    "article.learn-card",
    { key: "patterns", "data-feature": "patterns" },
    h("header.learn-head", h("h4", t("insights.feature.patterns")), ctx.isAdmin ? h("button.btn.small.ghost", { type: "button", "aria-label": t("insights.forget_title", { feature: t("insights.feature.patterns") }), onclick: () => ctx.controller.forget("patterns") }, icon("mdi:eraser"), t("insights.forget")) : null),
    h("p.uses", h("strong", `${t("insights.uses")} `), t("insights.data.patterns")),
    h("p.muted", t("insights.patterns.body")),
  );
}

/** ctx: { controller, index, isAdmin } */
export function renderInsights(ctx) {
  const { controller } = ctx;
  if (controller.error && !controller.data) {
    return emptyState("mdi:alert-circle-outline", t("insights.load_error", { message: controller.error.message }), null, h("button.btn", { type: "button", onclick: () => controller.retry() }, t("retry")));
  }
  if (!controller.data) return h("div.loading", { role: "status" }, t("loading"));
  const data = controller.data;
  const features = data.features || {};
  const { ideas, others } = splitSuggestions(data.suggestions); // ideas = the inbox (kind automation), others as before
  const cards = [
    ...LEARNED_FEATURES.filter((f) => features[f]).map((f) => featureCard(f, { ...ctx, data })),
    features.patterns ? patternsCard(ctx) : null,
  ];
  return h(
    "div.insights",
    controller.habits.render(data, ideas, ctx.isAdmin),
    h(
      "section.panel-section.suggestions",
      { key: "suggestions" },
      h("h3", icon("mdi:lightbulb-on-outline"), t("insights.title"), h("span.count", others.length)),
      others.length ? h("div.suggestion-list", others.map((s) => suggestionCard(s, ctx))) : h("p.muted", t("insights.none")),
    ),
    h(
      "section.panel-section.learned",
      { key: "learned" },
      h("h3", icon("mdi:brain"), t("insights.learned_title")),
      h("p.muted", t("insights.learned_intro")),
      h("div.learn-grid", cards),
      ctx.isAdmin ? h("div.forget-all", h("button.btn.danger-outline", { type: "button", onclick: () => controller.forget(null) }, icon("mdi:delete-sweep-outline"), t("insights.forget_all"))) : null,
    ),
  );
}
