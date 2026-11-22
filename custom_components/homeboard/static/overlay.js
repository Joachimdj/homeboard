// Page-level layer for everything that must not be clipped or transformed by a
// card or panel: dialogs, popup menus, toasts and the floating drag clone.
// It lives in its own shadow root appended to <body> and inherits HA's theme
// variables from the document.

import { adoptStyles, deepActiveElement, h, patch } from "./dom.js";
import { t } from "./i18n.js";
import { store } from "./store.js";
import { baseCss, boardCss, overlayCss } from "./styles.js";

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

const state = { dialogs: [], menu: null, toasts: [] };
let nextId = 1;
let host = null;
let layer = null;
let floats = null;

function ensure() {
  if (host) return;
  host = document.createElement("div");
  host.id = "homeboard-overlay";
  const root = host.attachShadow({ mode: "open" });
  adoptStyles(root, baseCss, boardCss, overlayCss);
  floats = document.createElement("div");
  floats.className = "floats";
  layer = document.createElement("div");
  layer.className = "layer";
  root.append(floats, layer);
  document.body.append(host);
  window.addEventListener("keydown", onWindowKey, true);
  layer.addEventListener("keydown", trapTab);
}

function render() {
  if (!host) return;
  host.style.colorScheme = store.hass?.themes?.darkMode ? "dark" : "light";
  patch(layer, [
    state.dialogs.map((entry, index) => dialogView(entry, index === state.dialogs.length - 1)),
    state.menu ? menuView(state.menu) : null,
    h(
      "div.toasts",
      { key: "toasts", "aria-live": "polite" },
      state.toasts.map((toast) =>
        h(
          `div.toast.${toast.kind}`,
          { key: toast.id, role: toast.kind === "error" ? "alert" : "status" },
          h("span.toast-text", toast.message),
          toast.action
            ? h("button.toast-action", { onclick: () => { dismissToast(toast.id); toast.action.run(); } }, toast.action.label)
            : null,
          h("button.icon-btn.toast-close", { "aria-label": t("close"), onclick: () => dismissToast(toast.id) }, h("ha-icon", { icon: "mdi:close" })),
        ),
      ),
    ),
  ]);
}

// ---- toasts ---------------------------------------------------------------

function toast({ message, kind = "info", action = null, timeout }) {
  ensure();
  const id = nextId++;
  const entry = { id, message, kind, action, timer: null };
  const ms = timeout ?? (action ? 8000 : kind === "error" ? 7000 : 4000);
  entry.timer = setTimeout(() => dismissToast(id), ms);
  state.toasts = [...state.toasts.slice(-2), entry];
  render();
  return id;
}

function dismissToast(id) {
  const entry = state.toasts.find((x) => x.id === id);
  if (!entry) return;
  clearTimeout(entry.timer);
  state.toasts = state.toasts.filter((x) => x.id !== id);
  render();
}

// ---- dialogs --------------------------------------------------------------

function dialogView(entry, isTop) {
  const { component } = entry;
  return h(
    "div.backdrop",
    {
      key: `dialog-${entry.id}`,
      "aria-hidden": isTop ? null : "true",
      onpointerdown: (event) => {
        entry.downOnBackdrop = event.target === event.currentTarget;
      },
      onclick: (event) => {
        if (event.target === event.currentTarget && entry.downOnBackdrop) entry.close();
      },
    },
    h(
      "div.dialog",
      { class: component.size || "", role: "dialog", "aria-modal": "true", "aria-label": component.label ? component.label() : "" },
      component.render(),
    ),
  );
}

function openDialog(component) {
  ensure();
  const entry = {
    id: nextId++,
    component,
    returnFocus: deepActiveElement(),
    downOnBackdrop: false,
    update: () => render(),
    close: () => closeDialog(entry),
  };
  state.dialogs.push(entry);
  render();
  queueMicrotask(() => focusDialog(entry));
  return entry;
}

function closeDialog(entry) {
  const index = state.dialogs.indexOf(entry);
  if (index === -1) return;
  state.dialogs.splice(index, 1);
  render();
  entry.component.onClose?.();
  if (entry.returnFocus?.isConnected) entry.returnFocus.focus({ preventScroll: true });
}

function dialogElements(entry) {
  const index = state.dialogs.indexOf(entry);
  return layer.querySelectorAll(":scope > .backdrop")[index]?.querySelector(".dialog");
}

function focusDialog(entry) {
  const dialog = dialogElements(entry);
  if (!dialog) return;
  const target = dialog.querySelector("[data-autofocus]") || dialog.querySelector(".dialog-body input, .dialog-body textarea, .dialog-body select") || dialog.querySelector(FOCUSABLE);
  target?.focus({ preventScroll: true });
}

function onWindowKey(event) {
  if (event.key !== "Escape") return;
  if (state.menu) {
    closeMenu();
  } else if (state.dialogs.length) {
    const top = state.dialogs[state.dialogs.length - 1];
    if (!top.component.onEscape?.()) top.close();
  } else {
    return;
  }
  event.preventDefault();
  event.stopPropagation();
}

function trapTab(event) {
  if (event.key !== "Tab" || state.menu || !state.dialogs.length) return;
  const dialog = dialogElements(state.dialogs[state.dialogs.length - 1]);
  if (!dialog) return;
  const items = [...dialog.querySelectorAll(FOCUSABLE)].filter((el) => el.offsetParent !== null || el === layer.getRootNode().activeElement);
  if (!items.length) return;
  const active = layer.getRootNode().activeElement;
  if (event.shiftKey && (active === items[0] || !dialog.contains(active))) {
    items[items.length - 1].focus();
    event.preventDefault();
  } else if (!event.shiftKey && active === items[items.length - 1]) {
    items[0].focus();
    event.preventDefault();
  }
}

/** Standard dialog chrome: header with title + close, scrolling body, footer. */
export function dialogShell({ title, icon, body, footer, onClose, headerLeft, headerRight }) {
  return [
    h(
      "header.dialog-header",
      { key: "header" },
      icon ? h("ha-icon", { icon }) : null,
      title ? h("h2.dialog-title", title) : null,
      headerLeft,
      h("span.spacer"),
      headerRight,
      h("button.icon-btn", { "aria-label": t("close"), title: t("close"), onclick: onClose }, h("ha-icon", { icon: "mdi:close" })),
    ),
    h("div.dialog-body", { key: "body" }, body),
    footer ? h("footer.dialog-footer", { key: "footer" }, footer) : null,
  ];
}

function confirm({ title, message, confirmLabel, danger = false }) {
  return new Promise((resolve) => {
    let answer = false;
    const finish = (value) => {
      answer = value;
      entry.close();
    };
    const entry = openDialog({
      size: "small",
      label: () => title,
      onClose: () => resolve(answer),
      render: () =>
        dialogShell({
          title,
          onClose: () => finish(false),
          body: h("p.dialog-message", message),
          footer: [
            h("button.btn", { "data-autofocus": danger ? "" : null, onclick: () => finish(false) }, t("cancel")),
            h("button.btn.primary", { class: danger ? "danger" : "", "data-autofocus": danger ? null : "", onclick: () => finish(true) }, confirmLabel || t("ok")),
          ],
        }),
    });
  });
}

/** Ask the user to pick one of `options` ([{value, label}]); resolves null on cancel. */
function choose({ title, message, options, confirmLabel }) {
  return new Promise((resolve) => {
    let answer = null;
    let value = options[0]?.value ?? null;
    const entry = openDialog({
      size: "small",
      label: () => title,
      onClose: () => resolve(answer),
      render: () =>
        dialogShell({
          title,
          onClose: () => entry.close(),
          body: [
            h("p.dialog-message", message),
            h(
              "select.input",
              { "aria-label": title, "data-autofocus": "", value, onchange: (e) => { value = e.target.value; } },
              options.map((o) => h("option", { value: o.value }, o.label)),
            ),
          ],
          footer: [
            h("button.btn", { onclick: () => entry.close() }, t("cancel")),
            h("button.btn.primary", { onclick: () => { answer = value; entry.close(); } }, confirmLabel || t("ok")),
          ],
        }),
    });
  });
}

// ---- popup menu -----------------------------------------------------------

function openMenu({ anchor, items, label }) {
  ensure();
  closeMenu();
  state.menu = { rect: anchor.getBoundingClientRect(), items, label, returnFocus: deepActiveElement() };
  render();
  const menu = layer.querySelector(".menu");
  placeMenu(menu, state.menu.rect);
  (menu.querySelector(".menu-item.selected") || menu.querySelector(".menu-item:not([disabled])"))?.focus();
}

function closeMenu() {
  if (!state.menu) return;
  const { returnFocus } = state.menu;
  state.menu = null;
  render();
  if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true });
}

function placeMenu(menu, rect) {
  const margin = 8;
  const { width, height } = menu.getBoundingClientRect();
  const left = Math.max(margin, Math.min(rect.left, window.innerWidth - width - margin));
  const below = rect.bottom + 4;
  const top = below + height + margin > window.innerHeight ? Math.max(margin, rect.top - height - 4) : below;
  menu.style.left = `${left}px`;
  menu.style.top = `${top}px`;
  menu.style.maxHeight = `${window.innerHeight - 2 * margin}px`;
}

function menuKey(event) {
  const items = [...event.currentTarget.querySelectorAll(".menu-item:not([disabled])")];
  const index = items.indexOf(layer.getRootNode().activeElement);
  const move = (next) => {
    items[(next + items.length) % items.length]?.focus();
    event.preventDefault();
  };
  if (event.key === "ArrowDown") move(index + 1);
  else if (event.key === "ArrowUp") move(index - 1);
  else if (event.key === "Home") move(0);
  else if (event.key === "End") move(items.length - 1);
  else if (event.key === "Tab") {
    closeMenu();
    event.preventDefault();
  }
}

function menuView(menu) {
  return h(
    "div.menu-backdrop",
    { key: "menu", onpointerdown: (event) => { if (event.target === event.currentTarget) closeMenu(); }, oncontextmenu: (event) => { event.preventDefault(); closeMenu(); } },
    h(
      "div.menu",
      { role: "menu", "aria-label": menu.label || "", onkeydown: menuKey },
      menu.items.map((item, index) =>
        item.divider
          ? h("div.menu-sep", { key: `sep-${index}` })
          : item.heading
            ? h("div.menu-heading", { key: `head-${index}` }, item.heading)
            : h(
                "button.menu-item",
                {
                  key: `item-${index}`,
                  role: "menuitem",
                  class: item.selected ? "selected" : "",
                  disabled: item.disabled,
                  onclick: () => {
                    closeMenu();
                    item.onSelect?.();
                  },
                },
                h("ha-icon", { icon: item.icon || (item.selected ? "mdi:check" : "") }),
                h("span", item.label),
              ),
      ),
    ),
  );
}

// ---- floating layer (drag clone) -------------------------------------------

function float(element) {
  ensure();
  floats.append(element);
  return () => element.remove();
}

export const overlay = {
  toast,
  dismissToast,
  dialog: openDialog,
  confirm,
  choose,
  menu: openMenu,
  closeMenu,
  float,
  get menuOpen() {
    return Boolean(state.menu);
  },
};
