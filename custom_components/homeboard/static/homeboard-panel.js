// Sidebar panel: Summary / Board / Backlog / List with project switcher, quick
// add, quick filters and swimlanes. Registered by HA's panel_custom as
// <homeboard-panel> and fed `hass`, `narrow`, `route` and `panel` properties.

import { BoardController } from "./board-controller.js";
import { emptyState, icon } from "./components.js";
import { adoptStyles, h, patch } from "./dom.js";
import { EMPTY_FILTER, LANE_MODES, isFilterActive, normaliseFilter } from "./filters.js";
import { t, tn } from "./i18n.js";
import { personName } from "./indexes.js";
import { InsightsController } from "./insights-controller.js";
import { learningEnabled } from "./insights.js";
import { renderInsights } from "./insights-view.js";
import { openIssueDialog, openNewIssueDialog } from "./issue-dialog.js";
import { renderList } from "./list-view.js";
import { overlay } from "./overlay.js";
import { openProjectSettings } from "./project-dialog.js";
import { QuickAdd } from "./quick-add.js";
import { store } from "./store.js";
import { baseCss, boardCss, panelCss, summaryCss } from "./styles.js";
import { renderSummary } from "./summary-view.js";
import { uniqueSorted } from "./util.js";

const STORAGE_KEY = "homeboard.ui.v1";
const TABS = [
  { id: "summary", icon: "mdi:chart-box-outline" },
  { id: "board", icon: "mdi:view-column-outline" },
  { id: "backlog", icon: "mdi:tray-full" },
  { id: "list", icon: "mdi:format-list-bulleted" },
  { id: "insights", icon: "mdi:lightbulb-on-outline" },
];
const NO_PROJECT_TABS = ["summary", "insights"];
const NARROW_WIDTH = 640;

function loadUi() {
  const defaults = { tab: "board", projectId: null, laneMode: "none", showBacklog: false, sort: { by: "updated", dir: "desc" } };
  try {
    return { ...defaults, ...JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}") };
  } catch {
    return defaults;
  }
}

class HomeboardPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    adoptStyles(this.shadowRoot, baseCss, boardCss, summaryCss, panelCss);
    this.container = document.createElement("div");
    this.container.className = "root";
    this.shadowRoot.append(this.container);

    this.ui = loadUi();
    this.filter = { ...EMPTY_FILTER };
    this.kiosk = false;
    this.compact = false;
    this.pendingIssue = null;
    this.frame = 0;
    this.board = new BoardController({ requestRender: () => this.requestRender() });
    this.insights = new InsightsController({ requestRender: () => this.requestRender(), onSelectProject: (id) => this.setUi({ projectId: id }) });
    this.quickAdd = new QuickAdd({ getProject: () => this.currentProject()?.key, requestRender: () => this.requestRender() });
    this.resizeObserver = new ResizeObserver(([entry]) => {
      const compact = entry.contentRect.width < NARROW_WIDTH;
      if (compact !== this.compact) {
        this.compact = compact;
        this.requestRender();
      }
    });
    this.onLocation = () => this.readUrl();
  }

  set hass(value) {
    this._hass = value;
    store.setHass(value);
    if (this.isConnected && !this.release) this.start();
  }

  get hass() {
    return this._hass;
  }

  set narrow(value) {
    if (value !== this._narrow) {
      this._narrow = value;
      this.requestRender();
    }
  }

  get narrow() {
    return this._narrow;
  }

  // HA also sets `route` and `panel`; the panel needs neither.
  set route(value) {
    this._route = value;
  }

  set panel(value) {
    this._panel = value;
  }

  connectedCallback() {
    this.resizeObserver.observe(this);
    window.addEventListener("location-changed", this.onLocation);
    window.addEventListener("popstate", this.onLocation);
    this.board.connect();
    this.readUrl();
    this.unsubscribe = store.subscribe(() => this.requestRender());
    if (this._hass) this.start();
    this.requestRender();
  }

  disconnectedCallback() {
    this.resizeObserver.disconnect();
    window.removeEventListener("location-changed", this.onLocation);
    window.removeEventListener("popstate", this.onLocation);
    this.unsubscribe?.();
    this.release?.();
    this.release = null;
    this.board.dispose();
    this.quickAdd.dispose();
    cancelAnimationFrame(this.frame);
    this.frame = 0;
  }

  start() {
    this.release = store.acquire(this._hass);
  }

  // ---- state -----------------------------------------------------------------

  /** The tab that is actually shown: Insights only exists while a learning feature is on. */
  get tab() {
    const { tab } = this.ui;
    return tab === "insights" && !learningEnabled(store.state.payload?.settings) ? "board" : tab;
  }

  /** Deep links: ?issue=HOME-12, ?project=HOME, ?kiosk, ?tab=insights */
  readUrl() {
    const params = new URLSearchParams(location.search);
    this.kiosk = params.has("kiosk");
    if (params.has("project")) this.pendingProject = params.get("project").toUpperCase();
    if (params.has("issue")) this.pendingIssue = params.get("issue").toUpperCase();
    if (TABS.some((tab) => tab.id === params.get("tab"))) this.ui.tab = params.get("tab");
    if (params.has("issue") || params.has("project") || params.has("tab")) {
      params.delete("issue");
      params.delete("project");
      params.delete("tab");
      const query = params.toString();
      history.replaceState(history.state, "", `${location.pathname}${query ? `?${query}` : ""}${location.hash}`);
    }
    this.requestRender();
  }

  saveUi() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(this.ui));
    } catch {
      // private mode / storage blocked: the setting just does not persist
    }
  }

  setUi(patchValues) {
    Object.assign(this.ui, patchValues);
    this.saveUi();
    this.requestRender();
  }

  setFilter(patchValues) {
    this.filter = { ...this.filter, ...patchValues };
    this.requestRender();
  }

  /** Resolve pending deep links and pick a valid project once data is there. */
  syncProject(index) {
    if (this.pendingProject) {
      const project = index.projectByKey.get(this.pendingProject);
      if (project) {
        this.ui.projectId = project.id;
        if (this.ui.tab === "summary") this.ui.tab = "board";
        this.saveUi();
      }
      this.pendingProject = null;
    }
    const usable = index.projects.filter((p) => !p.archived);
    if (!index.projectById.has(this.ui.projectId) || (!store.isAdmin && index.projectById.get(this.ui.projectId).archived)) {
      this.ui.projectId = usable[0]?.id || null;
    }
    if (this.pendingIssue) {
      const issue = index.issueByKey.get(this.pendingIssue);
      this.pendingIssue = null;
      if (issue) {
        this.ui.projectId = issue.project_id;
        openIssueDialog(issue.id);
      } else {
        overlay.toast({ message: t("toast.issue_gone") });
      }
    }
  }

  currentProject() {
    return store.state.index?.projectById.get(this.ui.projectId) || null;
  }

  openBoard(projectId, filter) {
    this.filter = normaliseFilter(filter);
    this.setUi({ tab: "board", ...(projectId ? { projectId } : {}) });
  }

  // ---- rendering ---------------------------------------------------------------

  requestRender() {
    if (this.frame) return;
    this.frame = requestAnimationFrame(() => {
      this.frame = 0;
      this.render();
    });
  }

  render() {
    if (!this.isConnected) return;
    const { index, loading, error } = store.state;
    this.style.colorScheme = this._hass?.themes?.darkMode ? "dark" : "light";
    if (index) this.syncProject(index);
    const project = this.currentProject();
    patch(
      this.container,
      h(
        "div.app",
        { class: [this.compact ? "narrow" : "", this.kiosk ? "kiosk" : ""].join(" ").trim(), key: "app" },
        this.kiosk ? this.kioskBar(index, project) : [this.topBar(index, project), this.tabBar()],
        !this.kiosk && project ? this.quickAddBar() : null,
        !this.kiosk && index && !NO_PROJECT_TABS.includes(this.tab) && project ? this.filterBar(index, project) : null,
        h("main.content", { key: "content", class: `tab-${this.tab}` }, this.content({ index, loading, error, project })),
      ),
    );
  }

  topBar(index, project) {
    const projects = index ? index.projects.filter((p) => !p.archived || p.id === project?.id) : [];
    const select = !NO_PROJECT_TABS.includes(this.tab) && projects.length > 1 ? this.projectSelect(projects, project) : null;
    return h(
      "header.topbar",
      { key: "topbar", class: select ? "with-select" : "" },
      this._narrow
        ? h("button.icon-btn.on-bar", { type: "button", "aria-label": t("menu"), onclick: () => this.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true })) }, icon("mdi:menu"))
        : null,
      h("h1.title", store.state.payload?.settings?.panel_title || t("panel.title")),
      select,
      h("span.spacer"),
      index && project
        ? h("button.btn.on-bar", { type: "button", onclick: () => openNewIssueDialog({ projectId: project.id }) }, icon("mdi:plus"), h("span.btn-text", t("new_issue")))
        : null,
      index
        ? h(
            "button.icon-btn.on-bar",
            {
              type: "button",
              "aria-label": store.isAdmin ? t("settings.title") : t("settings.recurring_only"),
              title: store.isAdmin ? t("settings.title") : t("settings.recurring_only"),
              onclick: () => openProjectSettings({ projectId: project?.id, onSelectProject: (id) => this.setUi({ projectId: id }) }),
            },
            icon(store.isAdmin ? "mdi:cog-outline" : "mdi:repeat"),
          )
        : null,
      h("button.icon-btn.on-bar", { type: "button", "aria-label": t("kiosk.enter"), title: t("kiosk.enter"), onclick: () => this.setKiosk(true) }, icon("mdi:fullscreen")),
    );
  }

  projectSelect(projects, project) {
    return h(
      "select.input.project-select",
      { "aria-label": t("project"), value: project?.id || "", onchange: (event) => this.setUi({ projectId: event.target.value }) },
      projects.map((p) => h("option", { key: p.id, value: p.id }, `${p.key} · ${p.name}${p.archived ? ` (${t("settings.archived_short")})` : ""}`)),
    );
  }

  setKiosk(on) {
    this.kiosk = on;
    const url = new URL(location.href);
    if (on) url.searchParams.set("kiosk", "");
    else url.searchParams.delete("kiosk");
    history.replaceState(history.state, "", url);
    this.requestRender();
  }

  kioskBar(index, project) {
    const projects = index ? index.projects.filter((p) => !p.archived) : [];
    return h(
      "header.kiosk-bar",
      { key: "kiosk" },
      h("h1.title", project ? project.name : t("panel.title")),
      projects.length > 1 ? this.projectSelect(projects, project) : null,
      h("span.spacer"),
      project ? h("button.btn.primary.big", { type: "button", onclick: () => openNewIssueDialog({ projectId: project.id }) }, icon("mdi:plus"), t("new_issue")) : null,
      h("button.icon-btn.big", { type: "button", "aria-label": t("kiosk.exit"), title: t("kiosk.exit"), onclick: () => this.setKiosk(false) }, icon("mdi:fullscreen-exit")),
    );
  }

  tabBar() {
    const settings = store.state.payload?.settings;
    const open = settings?.insights_open || 0;
    return h(
      "nav.tabs",
      { key: "tabs", role: "tablist", "aria-label": t("panel.title") },
      TABS.filter((tab) => tab.id !== "insights" || learningEnabled(settings)).map((tab) =>
        h(
          "button.tab",
          {
            key: tab.id,
            type: "button",
            role: "tab",
            "aria-selected": String(this.tab === tab.id),
            class: this.tab === tab.id ? "active" : "",
            onclick: () => this.setUi({ tab: tab.id }),
          },
          icon(tab.icon),
          h("span", t(`tab.${tab.id}`)),
          tab.id === "insights" && open ? h("span.count.badge", { "aria-label": tn("insights.badge", open) }, open) : null,
        ),
      ),
    );
  }

  quickAddBar() {
    return h("div.quickadd-bar", { key: "quickadd" }, this.quickAdd.render());
  }

  filterBar(index, project) {
    const f = this.filter;
    const issues = index.byProject.get(project.id) || [];
    const labels = uniqueSorted([...(project.labels || []), ...issues.flatMap((i) => i.labels || [])]);
    const types = uniqueSorted(issues.map((i) => i.type));
    const hasHealth = Boolean(store.state.payload.settings?.health_enabled) || issues.some((i) => i.source === "health");
    const toggle = (key, label, iconName, disabled = false) =>
      h("button.chip-toggle", { key, type: "button", "aria-pressed": String(Boolean(f[key])), class: f[key] ? "on" : "", disabled, onclick: () => this.setFilter({ [key]: !f[key] }) }, icon(iconName), label);

    return h(
      "div.filterbar",
      { key: "filters", role: "group", "aria-label": t("filters.label") },
      h(
        "div.chips",
        toggle("mine", t("filter.mine"), "mdi:account-outline", !store.me),
        toggle("unassigned", t("filter.unassigned"), "mdi:account-off-outline"),
        toggle("overdue", t("filter.overdue"), "mdi:alert-circle-outline"),
        toggle("dueSoon", t("filter.due_soon"), "mdi:clock-outline"),
        hasHealth ? toggle("auto", t("filter.auto"), "mdi:robot-outline") : null,
        f.assignee
          ? h("button.chip-toggle.on", { key: "assignee", type: "button", title: t("filters.clear"), onclick: () => this.setFilter({ assignee: "" }) }, icon("mdi:account-outline"), f.assignee === "unassigned" ? t("unassigned") : personName(index, f.assignee), icon("mdi:close"))
          : null,
        f.priority
          ? h("button.chip-toggle.on", { key: "priority", type: "button", title: t("filters.clear"), onclick: () => this.setFilter({ priority: "" }) }, icon("mdi:flag-outline"), t(`priority.${f.priority}`), icon("mdi:close"))
          : null,
      ),
      h(
        "div.filter-controls",
        labels.length
          ? h("select.input.small", { key: "label", "aria-label": t("field.labels"), value: f.label, onchange: (e) => this.setFilter({ label: e.target.value }) }, [h("option", { key: "", value: "" }, t("filter.any_label")), ...labels.map((l) => h("option", { key: l, value: l }, `#${l}`))])
          : null,
        types.length > 1
          ? h("select.input.small", { key: "type", "aria-label": t("field.type"), value: f.type, onchange: (e) => this.setFilter({ type: e.target.value }) }, [h("option", { key: "", value: "" }, t("filter.any_type")), ...types.map((v) => h("option", { key: v, value: v }, t(`type.${v}`)))])
          : null,
        h("input.input.small.search", { key: "search", type: "search", value: f.text, placeholder: t("filter.search"), "aria-label": t("filter.search"), oninput: (e) => this.setFilter({ text: e.target.value }) }),
        this.ui.tab === "board"
          ? [
              h("select.input.small", { key: "lanes", "aria-label": t("lanes.label"), value: this.ui.laneMode, onchange: (e) => this.setUi({ laneMode: e.target.value }) }, LANE_MODES.map((m) => h("option", { key: m, value: m }, t(`lanes.${m}`)))),
              h("label.check.small", { key: "backlog" }, h("input", { type: "checkbox", checked: this.ui.showBacklog, onchange: (e) => this.setUi({ showBacklog: e.target.checked }) }), h("span", t("filter.show_backlog"))),
            ]
          : null,
        isFilterActive(f) ? h("button.btn.small.ghost", { key: "clear", type: "button", onclick: () => this.setFilter({ ...EMPTY_FILTER }) }, icon("mdi:filter-off-outline"), t("filters.clear")) : null,
      ),
    );
  }

  content({ index, loading, error, project }) {
    if (error && !index) return emptyState("mdi:alert-circle-outline", t("error.load_title"), t("error.load", { message: error.message }));
    if (loading || !index) return h("div.loading", { role: "status" }, t("loading"));
    if (!project && !NO_PROJECT_TABS.includes(this.tab)) {
      return emptyState(
        "mdi:view-column-outline",
        t("summary.no_projects"),
        store.isAdmin ? t("summary.no_projects_hint") : t("summary.no_projects_user"),
        store.isAdmin ? h("button.btn.primary", { type: "button", onclick: () => openProjectSettings({ create: true, onSelectProject: (id) => this.setUi({ projectId: id }) }) }, icon("mdi:plus"), t("settings.new_project")) : null,
      );
    }
    const now = new Date();
    if (this.tab === "summary") {
      return renderSummary({
        payload: store.state.payload,
        index,
        now,
        showPeople: true,
        showHealth: true,
        showInsights: true,
        showAttention: true,
        onOpenBoard: (projectId, filter) => this.openBoard(projectId, filter),
        onOpenInsights: () => this.setUi({ tab: "insights" }),
        onOpenIssue: (issue) => openIssueDialog(issue.id),
      });
    }
    if (this.tab === "insights") {
      this.insights.ensure(store.state.payload.settings.insights_open ?? 0);
      return renderInsights({ controller: this.insights, index, isAdmin: store.isAdmin });
    }
    if (this.tab === "list") {
      return renderList({
        index,
        project,
        filter: this.filter,
        sort: this.ui.sort,
        me: store.me,
        now,
        onSort: (by) => this.setUi({ sort: { by, dir: this.ui.sort.by === by && this.ui.sort.dir === "asc" ? "desc" : "asc" } }),
        onOpen: (issue) => openIssueDialog(issue.id),
      });
    }
    return this.board.render({
      project,
      filter: this.filter,
      laneMode: this.ui.laneMode,
      layout: this.tab === "backlog" ? "backlog" : "board",
      showBacklog: this.ui.showBacklog,
      narrow: this.compact,
      kiosk: this.kiosk,
    });
  }
}

if (!customElements.get("homeboard-panel")) customElements.define("homeboard-panel", HomeboardPanel);
