// A fake Home Assistant `hass` object on top of MockBackend, plus stand-ins for
// the two HA elements the frontend uses (ha-icon, ha-card) so the real
// components render in a plain page.

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export class MockHass {
  /**
   * latency: ms before a command answers. pushDelay: ms the subscription push
   * lags behind the change (0 = the push arrives before the command result).
   */
  constructor(backend, { language = "en", dark = false, latency = 25, pushDelay = 0, uploadDelay = 700 } = {}) {
    this.backend = backend;
    this.latency = latency;
    this.pushDelay = pushDelay;
    this.uploadDelay = uploadDelay; // long enough to see the spinner
    this.calls = [];
    this.subscriptions = 0;
    this.activeSubscriptions = 0;
    this.base = {
      language,
      locale: { language, number_format: "language", time_format: "24" },
      themes: { darkMode: dark },
      user: { id: "u-joachim", name: "Joachim", is_admin: true },
      states: {
        "person.joachim": { entity_id: "person.joachim", state: "home", attributes: { friendly_name: "Joachim" } },
        "person.padmaja": { entity_id: "person.padmaja", state: "not_home", attributes: { friendly_name: "Padmaja" } },
        ...Object.fromEntries(backend.cameras.map((c) => [c.entity_id, { entity_id: c.entity_id, state: "idle", attributes: { friendly_name: c.name } }])),
      },
      connection: {
        subscribeMessage: (callback, message) => this.subscribe(callback, message),
      },
      callWS: (message) => this.callWS(message),
      fetchWithAuth: (path, init) => this.fetchWithAuth(path, init),
      callService: (domain, service, data) => {
        this.calls.push({ type: `service:${domain}.${service}`, params: data, ok: true });
        return Promise.resolve();
      },
    };
  }

  /** A fresh object like HA creates on every state change, same connection. */
  get hass() {
    return { ...this.base, user: { ...this.base.user }, themes: { ...this.base.themes }, locale: { ...this.base.locale } };
  }

  configure({ language, dark, admin }) {
    if (language) {
      this.base.language = language;
      this.base.locale = { ...this.base.locale, language };
    }
    if (dark !== undefined) this.base.themes = { darkMode: dark };
    if (admin !== undefined) {
      this.base.user = { ...this.base.user, is_admin: admin };
      this.backend.setUser({ is_admin: admin });
    }
    return this.hass;
  }

  subscribe(callback, message) {
    if (message.type !== "homeboard/subscribe") return Promise.reject({ code: "unknown_command", message: "Unknown command" });
    this.subscriptions += 1;
    this.activeSubscriptions += 1;
    const deliver = (payload) => (this.pushDelay ? setTimeout(() => callback(structuredClone(payload)), this.pushDelay) : callback(structuredClone(payload)));
    const stop = this.backend.subscribe(deliver);
    setTimeout(() => deliver(this.backend.payload()), 0);
    return Promise.resolve(() => {
      this.activeSubscriptions -= 1;
      stop();
    });
  }

  async callWS(message) {
    await sleep(this.latency);
    const entry = { type: message.type, params: { ...message, type: undefined }, ok: true };
    this.calls.push(entry);
    try {
      return structuredClone(this.backend.handle(message));
    } catch (error) {
      entry.ok = false;
      throw { code: error.code || "unknown_error", message: error.message }; // HA rejects with plain objects
    }
  }
}

/** Stands in for hass.fetchWithAuth: only POST /api/homeboard/upload exists (PROTOCOL 10.3). */
MockHass.prototype.fetchWithAuth = async function fetchWithAuth(path, init = {}) {
  await sleep(this.uploadDelay);
  const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  const entry = { type: `${init.method || "GET"} ${path}`, params: {}, ok: true };
  this.calls.push(entry);
  if (path !== "/api/homeboard/upload" || init.method !== "POST" || !(init.body instanceof FormData)) {
    entry.ok = false;
    return json(404, { message: "Not found" });
  }
  const file = init.body.get("file");
  const issueId = init.body.get("issue_id");
  entry.params = { issue_id: issueId, name: file?.name, type: file?.type, size: file?.size };
  if (!file || typeof file === "string") {
    entry.ok = false;
    return json(400, { message: "file is required" });
  }
  const { status, body } = this.backend.upload({ issue_id: issueId, name: file.name || "upload", mime: file.type, bytes: new Uint8Array(await file.arrayBuffer()) });
  entry.ok = status < 300;
  return json(status, body);
};

const GLYPHS = {
  "mdi:paperclip": "\u00a7", "mdi:format-list-checks": "\u2611", "mdi:drag-vertical": "\u2807", "mdi:camera-outline": "\u25ce", "mdi:camera-off-outline": "\u2298",
  "mdi:file-pdf-box": "PDF", "mdi:file-outline": "\u25a4", "mdi:chevron-left": "\u2039", "mdi:auto-fix": "\u2726", "mdi:lightbulb-on-outline": "\u2600", "mdi:brain": "\u2699",
  "mdi:eraser": "\u232b", "mdi:delete-sweep-outline": "\u2717",
  "mdi:checkbox-marked-circle-outline": "✔", "mdi:bug-outline": "❖", "mdi:bookmark-outline": "⚑", "mdi:lightning-bolt": "⚡",
  "mdi:chevron-double-up": "⇈", "mdi:chevron-up": "↑", "mdi:equal": "=", "mdi:chevron-down": "↓", "mdi:chevron-double-down": "⇊",
  "mdi:plus": "+", "mdi:plus-circle-outline": "⊕", "mdi:close": "✕", "mdi:close-circle-outline": "⊗", "mdi:dots-vertical": "⋮", "mdi:dots-horizontal": "⋯",
  "mdi:cog-outline": "⚙", "mdi:repeat": "⟳", "mdi:fullscreen": "⛶", "mdi:fullscreen-exit": "⤢", "mdi:microphone": "☎", "mdi:microphone-off": "⊘",
  "mdi:menu": "☰", "mdi:calendar-outline": "▦", "mdi:calendar-alert": "▦", "mdi:comment-outline": "✉", "mdi:robot-outline": "⚙",
  "mdi:account-outline": "☺", "mdi:account-off-outline": "☹", "mdi:alert-circle-outline": "!", "mdi:clock-outline": "◴", "mdi:flag-outline": "⚑",
  "mdi:filter-off-outline": "⨯", "mdi:chart-box-outline": "▤", "mdi:view-column-outline": "\u2016", "mdi:tray-full": "☰", "mdi:format-list-bulleted": "≡",
  "mdi:check": "✓", "mdi:arrow-up": "↑", "mdi:arrow-down": "↓", "mdi:delete-outline": "✗", "mdi:archive-outline": "▣", "mdi:link-variant": "∞",
  "mdi:open-in-new": "↗", "mdi:pencil-outline": "✎", "mdi:play-circle-outline": "▶", "mdi:chevron-right": "›",
  "mdi:check-circle-outline": "✓", "mdi:help-circle-outline": "?", "mdi:folder-outline": "▢", "mdi:text-box-search-outline": "⌕", "mdi:view-dashboard-outline": "▦",
};

/** Defines the two stand-in elements; skipped where there is no DOM (node tests). */
function defineStubs() {
  class StubIcon extends HTMLElement {
    static observedAttributes = ["icon"];

    constructor() {
      super();
      this.attachShadow({ mode: "open" }).innerHTML =
        '<style>:host{display:inline-flex;align-items:center;justify-content:center;width:var(--mdc-icon-size,24px);height:var(--mdc-icon-size,24px);font-size:calc(var(--mdc-icon-size,24px) * .85);line-height:1;font-family:system-ui,sans-serif}</style><span></span>';
    }

    connectedCallback() {
      this.paint();
    }

    attributeChangedCallback() {
      this.paint();
    }

    paint() {
      const name = this.getAttribute("icon") || "";
      this.shadowRoot.querySelector("span").textContent = name ? GLYPHS[name] || "□" : "";
    }
  }

  class StubCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" }).innerHTML =
        "<style>:host{display:block;position:relative;background:var(--ha-card-background,var(--card-background-color,#fff));color:var(--primary-text-color);border-radius:var(--ha-card-border-radius,12px);border:1px solid var(--ha-card-border-color,var(--divider-color,#e0e0e0));box-shadow:var(--ha-card-box-shadow,none)}</style><slot></slot>";
    }
  }

  if (!customElements.get("ha-icon")) customElements.define("ha-icon", StubIcon);
  if (!customElements.get("ha-card")) customElements.define("ha-card", StubCard);
}

if (typeof HTMLElement !== "undefined") defineStubs();
