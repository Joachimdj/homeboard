// The List tab: all issues of a project as a sortable table.

import { avatar, dueChip, emptyState, icon, priorityIcon, typeIcon } from "./components.js";
import { h } from "./dom.js";
import { t } from "./i18n.js";
import { SORT_COLUMNS, filterIssues, sortIssues } from "./filters.js";
import { categoryOf, statusName } from "./indexes.js";
import { relativeTime } from "./util.js";

/** ctx: { index, project, filter, sort, me, now, onSort(column), onOpen(issue) } */
export function renderList(ctx) {
  const { index, project, sort } = ctx;
  const all = index.byProject.get(project.id) || [];
  const issues = sortIssues(filterIssues(all, ctx.filter, { me: ctx.me, index }), sort, index);

  const header = SORT_COLUMNS.map((column) =>
    h(
      "th",
      { key: column, scope: "col", "aria-sort": sort.by === column ? (sort.dir === "desc" ? "descending" : "ascending") : "none", class: `col-${column}` },
      h(
        "button.sort",
        { type: "button", onclick: () => ctx.onSort(column) },
        t(`list.col.${column}`),
        sort.by === column ? icon(sort.dir === "desc" ? "mdi:arrow-down" : "mdi:arrow-up") : null,
      ),
    ),
  );

  return h(
    "div.list-view",
    { key: "list" },
    issues.length
      ? h(
          "table.list-table",
          h("thead", h("tr", header)),
          h(
            "tbody",
            issues.map((issue) =>
              h(
                "tr",
                {
                  key: issue.id,
                  tabindex: "0",
                  class: categoryOf(index, issue) === "done" ? "done" : "",
                  "aria-label": `${issue.key} ${issue.summary}`,
                  onclick: () => ctx.onOpen(issue),
                  onkeydown: (event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      ctx.onOpen(issue);
                    }
                  },
                },
                h("td.col-key", typeIcon(issue.type), h("span.key", issue.key)),
                h("td.col-summary", issue.summary),
                h("td.col-status", h("span.chip.plain", statusName(index, issue.status))),
                h("td.col-priority", priorityIcon(issue.priority)),
                h("td.col-assignee", avatar(index, issue.assignee, "sm")),
                h("td.col-due", dueChip(issue, ctx.now)),
                h("td.col-updated", h("span.muted.small", relativeTime(issue.updated))),
              ),
            ),
          ),
        )
      : emptyState("mdi:text-box-search-outline", t("list.empty")),
  );
}
