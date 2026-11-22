// Drag and drop with Pointer Events (HTML5 DnD does not work on touch).
//
// Mouse: a ~5 px move picks a card up. Touch / pen: a 300 ms long press, and the
// pending pick-up is cancelled when the finger moves more than ~8 px first, so
// normal scrolling keeps working. A picked-up card is represented by a floating
// clone in the overlay layer; the real card stays in place (dimmed) so live
// pushes can keep patching the board underneath.
//
// The board is searched through DOM markers: `.card[data-id]` inside
// `.cell[data-status][data-lane]`. The owner learns about the current drop
// target through onState({ issueId, status, lane, before } | null) and gets
// onDrop({ issueId, status, before }) when the card is released over a cell.

import { overlay } from "./overlay.js";
import { clamp } from "./util.js";

const MOUSE_SLOP = 5;
const TOUCH_SLOP = 8;
const LONG_PRESS_MS = 300;
const EDGE = 56;
const MAX_SCROLL_STEP = 20;

function scrollStep(depth) {
  return Math.ceil(clamp(depth / EDGE, 0, 1) * MAX_SCROLL_STEP);
}

export class Dnd {
  constructor({ onState, onDrop, canDrag = () => true }) {
    this.onState = onState;
    this.onDrop = onDrop;
    this.canDrag = canDrag;
    this.board = null;
    this.session = null;
  }

  attach(board) {
    if (this.board === board) return;
    this.detach();
    this.board = board;
    board.addEventListener("pointerdown", this.handleDown);
    board.addEventListener("touchmove", this.handleTouchMove, { passive: false });
    board.addEventListener("contextmenu", this.handleContextMenu);
    board.addEventListener("dragstart", this.handleDragStart);
  }

  detach() {
    this.cancel();
    const board = this.board;
    if (!board) return;
    board.removeEventListener("pointerdown", this.handleDown);
    board.removeEventListener("touchmove", this.handleTouchMove);
    board.removeEventListener("contextmenu", this.handleContextMenu);
    board.removeEventListener("dragstart", this.handleDragStart);
    this.board = null;
  }

  get active() {
    return Boolean(this.session?.active);
  }

  // ---- pointer lifecycle ---------------------------------------------------

  handleDown = (event) => {
    if (this.session || !event.isPrimary) return;
    if (event.pointerType === "mouse" && event.button !== 0) return;
    const card = event.target.closest?.(".card");
    if (!card || !this.board.contains(card) || event.target.closest("button, a, input, select, textarea")) return;
    if (!this.canDrag()) return;

    const session = {
      pointerId: event.pointerId,
      pointerType: event.pointerType,
      card,
      issueId: card.dataset.id,
      startX: event.clientX,
      startY: event.clientY,
      x: event.clientX,
      y: event.clientY,
      active: false,
      timer: null,
      frame: 0,
      target: null,
      clone: null,
      removeClone: null,
      grabX: 0,
      grabY: 0,
    };
    this.session = session;
    window.addEventListener("pointermove", this.handleMove);
    window.addEventListener("pointerup", this.handleUp);
    window.addEventListener("pointercancel", this.handleCancel);
    window.addEventListener("keydown", this.handleKey, true);
    if (event.pointerType !== "mouse") session.timer = setTimeout(() => this.begin(), LONG_PRESS_MS);
  };

  handleMove = (event) => {
    const session = this.session;
    if (!session || event.pointerId !== session.pointerId) return;
    session.x = event.clientX;
    session.y = event.clientY;
    if (session.active) {
      this.update();
      return;
    }
    const distance = Math.hypot(session.x - session.startX, session.y - session.startY);
    if (session.pointerType === "mouse") {
      if (distance > MOUSE_SLOP) this.begin();
    } else if (distance > TOUCH_SLOP) {
      this.cancel(); // the finger is scrolling, not holding
    }
  };

  handleUp = (event) => {
    const session = this.session;
    if (!session || event.pointerId !== session.pointerId) return;
    session.x = event.clientX;
    session.y = event.clientY;
    if (session.active) this.update();
    this.finish(true);
  };

  handleCancel = (event) => {
    if (this.session && event.pointerId === this.session.pointerId) this.finish(false);
  };

  handleKey = (event) => {
    if (event.key === "Escape" && this.session?.active) {
      event.preventDefault();
      event.stopPropagation();
      this.finish(false);
    }
  };

  // Once a card is picked up the page must not scroll under the finger.
  handleTouchMove = (event) => {
    if (this.session?.active && event.cancelable) event.preventDefault();
  };

  handleContextMenu = (event) => {
    if (this.session && this.session.pointerType !== "mouse") event.preventDefault();
  };

  handleDragStart = (event) => event.preventDefault();

  handleSelectStart = (event) => event.preventDefault();

  // ---- drag --------------------------------------------------------------

  begin() {
    const session = this.session;
    if (!session || session.active) return;
    clearTimeout(session.timer);
    session.active = true;

    const rect = session.card.getBoundingClientRect();
    session.grabX = session.startX - rect.left;
    session.grabY = session.startY - rect.top;
    const clone = session.card.cloneNode(true);
    clone.removeAttribute("tabindex");
    clone.setAttribute("aria-hidden", "true");
    clone.classList.add("drag-clone");
    clone.style.width = `${rect.width}px`;
    session.clone = clone;
    session.removeClone = overlay.float(clone);

    window.addEventListener("selectstart", this.handleSelectStart);
    window.getSelection?.()?.removeAllRanges();
    if (session.pointerType !== "mouse" && navigator.userActivation?.hasBeenActive) navigator.vibrate?.(15); // haptic pick-up cue
    this.onState({ issueId: session.issueId, status: null, lane: null, before: null });
    this.update();
    session.frame = requestAnimationFrame(this.tick);
  }

  update() {
    const session = this.session;
    if (!session?.active) return;
    session.clone.style.transform = `translate(${Math.round(session.x - session.grabX)}px, ${Math.round(session.y - session.grabY)}px)`;
    const target = this.hitTest(session.x, session.y);
    const previous = session.target;
    if (previous?.status === target?.status && previous?.lane === target?.lane && previous?.before === target?.before) return;
    session.target = target;
    this.onState({ issueId: session.issueId, status: target?.status ?? null, lane: target?.lane ?? null, before: target?.before ?? null });
  }

  hitTest(x, y) {
    const { issueId } = this.session;
    const cell = this.board
      .getRootNode()
      .elementsFromPoint(x, y)
      .find((el) => el.classList?.contains("cell") && this.board.contains(el));
    if (!cell) return null;
    let before = null;
    for (const card of cell.querySelectorAll(":scope > .card")) {
      if (card.dataset.id === issueId) continue;
      const rect = card.getBoundingClientRect();
      if (y < rect.top + rect.height / 2) {
        before = card.dataset.id;
        break;
      }
    }
    return { status: cell.dataset.status, lane: cell.dataset.lane, before, cell };
  }

  tick = () => {
    const session = this.session;
    if (!session?.active) return;
    const moved = this.autoScroll(session);
    if (moved) this.update();
    session.frame = requestAnimationFrame(this.tick);
  };

  autoScroll({ x, y, target }) {
    const board = this.board;
    const box = board.getBoundingClientRect();
    let moved = false;

    if (x < box.left + EDGE && board.scrollLeft > 0) {
      board.scrollLeft -= scrollStep(box.left + EDGE - x);
      moved = true;
    } else if (x > box.right - EDGE && board.scrollLeft < board.scrollWidth - board.clientWidth) {
      board.scrollLeft += scrollStep(x - (box.right - EDGE));
      moved = true;
    }

    // Vertical: the column under the pointer scrolls when it can, else the board.
    const cell = target?.cell;
    const scroller = cell && cell.scrollHeight > cell.clientHeight + 1 ? cell : board;
    const area = scroller.getBoundingClientRect();
    if (y < area.top + EDGE && scroller.scrollTop > 0) {
      scroller.scrollTop -= scrollStep(area.top + EDGE - y);
      moved = true;
    } else if (y > area.bottom - EDGE && scroller.scrollTop < scroller.scrollHeight - scroller.clientHeight) {
      scroller.scrollTop += scrollStep(y - (area.bottom - EDGE));
      moved = true;
    }
    return moved;
  }

  /** Abort without dropping (also used for a pending long press). */
  cancel() {
    if (this.session) this.finish(false);
  }

  finish(drop) {
    const session = this.session;
    if (!session) return;
    this.session = null;
    clearTimeout(session.timer);
    cancelAnimationFrame(session.frame);
    session.removeClone?.();
    window.removeEventListener("pointermove", this.handleMove);
    window.removeEventListener("pointerup", this.handleUp);
    window.removeEventListener("pointercancel", this.handleCancel);
    window.removeEventListener("keydown", this.handleKey, true);
    window.removeEventListener("selectstart", this.handleSelectStart);
    if (!session.active) return;

    // The click that follows a drag must not open the card underneath.
    const swallow = (event) => {
      event.stopPropagation();
      event.preventDefault();
    };
    window.addEventListener("click", swallow, true);
    setTimeout(() => window.removeEventListener("click", swallow, true), 60);

    this.onState(null);
    const target = session.target;
    if (drop && target?.status) this.onDrop({ issueId: session.issueId, status: target.status, before: target.before });
  }
}
