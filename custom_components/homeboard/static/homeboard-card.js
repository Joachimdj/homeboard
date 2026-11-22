// Lovelace cards: homeboard-board-card, homeboard-status-card,
// homeboard-quick-add-card. They share the views of the panel and the single
// store subscription.

import { BoardController } from "./board-controller.js";
import "./card-editor.js";
import { icon } from "./components.js";
import { adoptStyles, h, patch } from "./dom.js";
import { normaliseFilter } from "./filters.js";
import { t } from "./i18n.js";
import { findProject } from "./indexes.js";
import { openIssueDialog, openNewIssueDialog } from "./issue-dialog.js";
import { QuickAdd } from "./quick-add.js";
import { store } from "./store.js";
import { baseCss, boardCss, cardCss, summaryCss } from "./styles.js";
import { renderSummary } from "./summary-view.js";

const NARROW_WIDTH = 640;
const PANEL_PATH = "/homeboard";

function navigate(path) {
  history.pushState(null, "", path);
  window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
}

class HomeboardBaseCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    adoptStyles(this.shadowRoot, baseCss, boardCss, summaryCss, cardCss);
    this.container = document.createElement("div");
    this.shadowRoot.append(this.container);
    this.config = {};
    this.frame = 0;
    this.compact = false;
    this.resizeObserver = new ResizeObserver(([entry]) => {
      const compact = entry.contentRect.width < NARROW_WIDTH;
      if (compact !== this.compact) {
        this.compact = compact;
        this.requestRender();
      }
    });
  }

  setConfig(config) {
    if (!config || typeof config !== "object") throw new Error(t("card.invalid_config"));
    this.config = this.normaliseConfig(config);
    this.requestRender();
  }

  normaliseConfig(config) {
    return { ...config };
  }

  set hass(value) {
    this._hass = value;
    store.setHass(value);
    if (this.isConnected && !this.release) this.release = store.acquire(value);
  }

  get hass() {
    return this._hass;
  }

  connectedCallback() {
    this.resizeObserver.observe(this);
    this.unsubscribe = store.subscribe(() => this.requestRender());
    if (this._hass) this.release = store.acquire(this._hass);
    this.connect();
    this.requestRender();
  }

  connect() {}

  disconnectedCallback() {
    this.resizeObserver.disconnect();
    this.unsubscribe?.();
    this.release?.();
    this.release = null;
    this.dispose();
    cancelAnimationFrame(this.frame);
    this.frame = 0;
  }

  dispose() {}

  requestRender() {
    if (this.frame || !this.isConnected) return;
    this.frame = requestAnimationFrame(() => {
      this.frame = 0;
      this.render();
    });
  }

  /** Header + body inside ha-card; subclasses provide the parts. */
  render() {
    const { index, loading, error } = store.state;
    this.style.colorScheme = this._hass?.themes?.darkMode ? "dark" : "light";
    let body;
    if (error && !index) body = h("div.card-message.bad", t("error.load", { message: error.message }));
    else if (loading || !index) body = h("div.card-message", { role: "status" }, t("loading"));
    else body = this.renderBody(index);
    const title = this.title(index);
    const actions = this.headerActions(index);
    patch(
      this.container,
      h(
        "ha-card",
        { key: "card", class: this.config.kiosk ? "kiosk" : "" },
        title || actions ? h("div.card-header", h("span.card-title", title || ""), h("span.spacer"), actions) : null,
        body,
      ),
    );
  }

  title() {
    return this.config.title || "";
  }

  headerActions() {
    return null;
  }

  getCardSize() {
    return 4;
  }

  getGridOptions() {
    return { columns: 12, rows: "auto", min_columns: 6 };
  }
}

class HomeboardBoardCard extends HomeboardBaseCard {
  constructor() {
    super();
    this.board = new BoardController({ requestRender: () => this.requestRender() });
  }

  static getConfigElement() {
    return document.createElement("homeboard-board-card-editor");
  }

  static getStubConfig() {
    return { project: store.state.index?.projects.find((p) => !p.archived)?.key || "", show_backlog: false, swimlanes: "none" };
  }

  normaliseConfig(config) {
    return { swimlanes: "none", show_backlog: false, kiosk: false, max_height: 560, ...config };
  }

  connect() {
    this.board.connect();
  }

  dispose() {
    this.board.dispose();
  }

  project(index) {
    const wanted = this.config.project;
    return (wanted ? findProject(index, wanted) : null) || index.projects.find((p) => !p.archived) || null;
  }

  title(index) {
    if (this.config.title !== undefined) return this.config.title;
    return index ? this.project(index)?.name || "" : "";
  }

  headerActions(index) {
    const project = index && this.project(index);
    if (!project) return null;
    return h("button.icon-btn", { type: "button", "aria-label": t("new_issue"), title: t("new_issue"), onclick: () => openNewIssueDialog({ projectId: project.id }) }, icon("mdi:plus"));
  }

  renderBody(index) {
    const project = this.project(index);
    if (!project) return h("div.card-message", t("card.no_project"));
    const height = this.config.max_height;
    return this.board.render({
      project,
      filter: normaliseFilter(this.config.filter),
      laneMode: this.config.swimlanes,
      layout: "board",
      showBacklog: Boolean(this.config.show_backlog),
      narrow: this.compact,
      kiosk: Boolean(this.config.kiosk),
      maxHeight: typeof height === "number" ? `${height}px` : height || null,
    });
  }

  getCardSize() {
    return 8;
  }
}

class HomeboardStatusCard extends HomeboardBaseCard {
  static getConfigElement() {
    return document.createElement("homeboard-status-card-editor");
  }

  static getStubConfig() {
    return { show_people: true, show_health: true };
  }

  normaliseConfig(config) {
    return { show_people: true, show_health: true, ...config };
  }

  title() {
    return this.config.title ?? "";
  }

  renderBody(index) {
    return renderSummary({
      payload: store.state.payload,
      index,
      now: new Date(),
      projectIds: this.config.projects?.length ? this.config.projects : null,
      showPeople: this.config.show_people !== false,
      showHealth: this.config.show_health !== false,
      showAttention: false,
      onOpenBoard: (projectId) => {
        const project = projectId && index.projectById.get(projectId);
        navigate(project ? `${PANEL_PATH}?project=${project.key}` : PANEL_PATH);
      },
      onOpenIssue: (issue) => openIssueDialog(issue.id),
    });
  }

  getCardSize() {
    return 5;
  }
}

class HomeboardQuickAddCard extends HomeboardBaseCard {
  constructor() {
    super();
    this.quickAdd = new QuickAdd({ getProject: () => this.config.project || undefined, requestRender: () => this.requestRender() });
  }

  static getConfigElement() {
    return document.createElement("homeboard-quick-add-card-editor");
  }

  static getStubConfig() {
    return { title: t("quickadd.card_title") };
  }

  dispose() {
    this.quickAdd.dispose();
  }

  title() {
    return this.config.title ?? "";
  }

  renderBody() {
    return h("div.card-pad", this.quickAdd.render());
  }

  getCardSize() {
    return 2;
  }

  getGridOptions() {
    return { columns: 12, rows: "auto", min_columns: 6, min_rows: 1 };
  }
}

const CARDS = [
  ["homeboard-board-card", HomeboardBoardCard, "Homeboard board", "Kanban board of one Homeboard project with drag and drop."],
  ["homeboard-status-card", HomeboardStatusCard, "Homeboard status", "Counts per status, overdue and due soon issues, home health and issues per person."],
  ["homeboard-quick-add-card", HomeboardQuickAddCard, "Homeboard quick add", "Add an issue from one line of text (@person !priority #label due tomorrow)."],
];

window.customCards = window.customCards || [];
for (const [type, constructor, name, description] of CARDS) {
  if (!customElements.get(type)) customElements.define(type, constructor);
  if (!window.customCards.some((card) => card.type === type)) window.customCards.push({ type, name, description, preview: false });
}
