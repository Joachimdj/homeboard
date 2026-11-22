// Glue between the board view, drag and drop, the move menu and the dialogs.
// One controller per board instance (the panel tab, or a Lovelace board card).

import { actions } from "./actions.js";
import { boardModel } from "./board-model.js";
import { renderBoard } from "./board-view.js";
import { Dnd } from "./dnd.js";
import { openIssueDialog, openNewIssueDialog } from "./issue-dialog.js";
import { t } from "./i18n.js";
import { overlay } from "./overlay.js";
import { isNoopMove } from "./ranks.js";
import { store } from "./store.js";

export class BoardController {
  constructor({ requestRender }) {
    this.requestRender = requestRender;
    this.drag = null;
    this.collapsed = new Set();
    this.dnd = new Dnd({
      onState: (state) => {
        this.drag = state;
        this.requestRender();
      },
      onDrop: (drop) => this.drop(drop),
    });
  }

  /** Called with the board element when it is created (and again after a reconnect). */
  boardRef = (element) => {
    this.element = element;
    this.dnd.attach(element);
  };

  connect() {
    if (this.element) this.dnd.attach(this.element);
  }

  dispose() {
    this.dnd.detach();
  }

  drop({ issueId, status, before }) {
    const { index } = store.state;
    const issue = index?.issueById.get(issueId);
    if (!issue) return;
    if (issue.status === status) {
      const column = (index.byProject.get(issue.project_id) || []).filter((i) => i.status === status);
      if (isNoopMove(column, issueId, before)) return;
    }
    actions.moveIssue(issueId, status, before);
  }

  openMenu(issue, anchor) {
    const project = store.state.index.projectById.get(issue.project_id);
    const card = anchor.closest?.(".card");
    const move = (statusId) => {
      actions.moveIssue(issue.id, statusId, null);
      // the card node is moved to its new column on the next frame, which drops focus
      requestAnimationFrame(() => card?.isConnected && card.focus());
    };
    overlay.menu({
      anchor,
      label: `${t("move_to")} ${issue.key}`,
      items: [
        { heading: t("move_to") },
        ...project.statuses.map((status) => ({
          label: status.name,
          selected: status.id === issue.status,
          onSelect: () => status.id !== issue.status && move(status.id),
        })),
        { divider: true },
        { label: t("open"), icon: "mdi:open-in-new", onSelect: () => openIssueDialog(issue.id) },
      ],
    });
  }

  toggleLane(id) {
    if (this.collapsed.has(id)) this.collapsed.delete(id);
    else this.collapsed.add(id);
    this.requestRender();
  }

  /**
   * options: { project, filter, laneMode, layout, showBacklog, narrow, kiosk, maxHeight }
   * Returns the board vnode.
   */
  render(options) {
    const { index } = store.state;
    const { project } = options;
    const model = boardModel({ ...options, index, me: store.me });
    return renderBoard({
      ...options,
      index,
      model,
      drag: this.drag,
      collapsed: this.collapsed,
      now: new Date(),
      boardRef: this.boardRef,
      onOpen: (issue) => openIssueDialog(issue.id),
      onMenu: (issue, anchor) => this.openMenu(issue, anchor),
      onAdd: (status) => openNewIssueDialog({ projectId: project.id, status: status.id }),
      onToggleLane: (id) => this.toggleLane(id),
    });
  }
}
