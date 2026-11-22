// A fake Home Assistant `hass` object on top of MockBackend, plus stand-ins for
// the two HA elements the frontend uses (ha-icon, ha-card) so the real
// components render in a plain page.

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export class MockHass {
  /**
   * latency: ms before a command answers. pushDelay: ms the subscription push
   * lags behind the change (0 = the push arrives before the command result).
   */
  constructor(backend, { language = "en", dark = false, latency = 25, pushDelay = 0 } = {}) {
    this.backend = backend;
    this.latency = latency;
    this.pushDelay = pushDelay;
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
      },
      connection: {
        subscribeMessage: (callback, message) => this.subscribe(callback, message),
      },
      callWS: (message) => this.callWS(message),
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

const GLYPHS = {
  "mdi:checkbox-marked-circle-outline": "✔", "mdi:bug-outline": "❖", "mdi:bookmark-outline": "⚑", "mdi:lightning-bolt": "⚡",
  "mdi:chevron-double-up": "⇈", "mdi:chevron-up": "↑", "mdi:equal": "=", "mdi:chevron-down": "↓", "mdi:chevron-double-down": "⇊",
  "mdi:plus": "+", "mdi:plus-circle-outline": "⊕", "mdi:close": "✕", "mdi:close-circle-outline": "⊗", "mdi:dots-vertical": "⋮", "mdi:dots-horizontal": "⋯",
  "mdi:cog-outline": "⚙", "mdi:repeat": "⟳", "mdi:fullscreen": "⛶", "mdi:fullscreen-exit": "⤢", "mdi:microphone": "☎", "mdi:microphone-off": "⊘",
  "mdi:menu": "☰", "mdi:calendar-outline": "▦", "mdi:calendar-alert": "▦", "mdi:comment-outline": "✉", "mdi:robot-outline": "⚙",
  "mdi:account-outline": "☺", "mdi:account-off-outline": "☹", "mdi:alert-circle-outline": "!", "mdi:clock-outline": "◴", "mdi:flag-outline": "⚑",
  "mdi:filter-off-outline": "⨯", "mdi:chart-box-outline": "▤", "mdi:view-column-outline": "\u2016", "mdi:tray-full": "☰", "mdi:format-list-bulleted": "≡",
  "mdi:check": "✓", "mdi:arrow-up": "↑", "mdi:arrow-down": "↓", "mdi:delete-outline": "✗", "mdi:archive-outline": "▣", "mdi:link-variant": "∞",
  "mdi:open-in-new": "↗", "mdi:pencil-outline": "✎", "mdi:play-circle-outline": "▶", "mdi:chevron-right": "›", "mdi:chevron-down-small": "⌄",
  "mdi:check-circle-outline": "✓", "mdi:help-circle-outline": "?", "mdi:folder-outline": "▢", "mdi:text-box-search-outline": "⌕", "mdi:view-dashboard-outline": "▦",
};

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
    this.shadowRoot.querySelector("span").textContent = name ? GLYPHS[name] || (name === "mdi:chevron-down" ? "⌄" : "□") : "";
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
