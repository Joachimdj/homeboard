// One shared subscription to `homeboard/subscribe` for the panel and every card.
//
// Views call store.acquire(hass) while mounted (ref counted) and
// store.subscribe(listener) to be told about changes. Mutations go through
// store.call(), which applies an optional optimistic transform on top of the
// last pushed payload, drops it again when the server rejects the call, and
// lets the next push reconcile otherwise.

import { buildIndex } from "./indexes.js";
import { languageFromHass, setLanguage } from "./i18n.js";

const SETTLE_TIMEOUT_MS = 1500;
const RETRY_AFTER_MS = 5000;

export class WsError extends Error {
  constructor(code, message) {
    super(message || code);
    this.name = "WsError";
    this.code = code;
  }
}

/** HA rejects callWS with a plain { code, message } object. */
export function toWsError(error) {
  if (error instanceof WsError) return error;
  if (error && typeof error === "object") return new WsError(error.code || "unknown", error.message || String(error.code || "Error"));
  return new WsError("unknown", String(error));
}

export class Store {
  constructor() {
    this.hass = null;
    this.server = null; // last pushed payload
    this.state = { payload: null, index: null, loading: true, error: null };
    this.listeners = new Set();
    this.refs = 0;
    this.generation = 0;
    this.connection = null;
    this.unsubscribe = null;
    this.ops = [];
    this.seq = 0;
    this.retryAt = 0;
  }

  /** Keep the subscription alive until the returned release function is called. */
  acquire(hass) {
    this.setHass(hass);
    this.refs += 1;
    if (this.refs === 1) this.start();
    let released = false;
    return () => {
      if (released) return;
      released = true;
      this.refs -= 1;
      if (this.refs === 0) this.stop();
    };
  }

  /** Called on every hass update (HA replaces the object constantly). */
  setHass(hass) {
    if (!hass) return;
    const before = `${this.hass?.locale?.language}|${this.hass?.language}|${this.hass?.themes?.darkMode}`;
    this.hass = hass;
    setLanguage(languageFromHass(hass));
    if (this.refs > 0 && this.connection && hass.connection !== this.connection) {
      this.stop();
      this.start();
    } else if (this.refs > 0 && !this.connection && Date.now() >= this.retryAt) {
      this.start(); // an earlier subscribe failed (integration still loading?)
    }
    const after = `${hass.locale?.language}|${hass.language}|${hass.themes?.darkMode}`;
    if (before !== after) this.emit();
  }

  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  emit() {
    for (const listener of [...this.listeners]) listener(this.state);
  }

  start() {
    const generation = ++this.generation;
    this.connection = this.hass.connection;
    this.state = { ...this.state, loading: !this.server, error: null };
    Promise.resolve()
      .then(() => this.connection.subscribeMessage((payload) => this.onPush(payload), { type: "homeboard/subscribe" }))
      .then((unsubscribe) => {
        if (generation === this.generation) this.unsubscribe = unsubscribe;
        else unsubscribe();
      })
      .catch((error) => {
        if (generation !== this.generation) return;
        this.connection = null;
        this.retryAt = Date.now() + RETRY_AFTER_MS;
        this.state = { ...this.state, loading: false, error: toWsError(error) };
        this.emit();
      });
  }

  stop() {
    this.generation += 1;
    this.connection = null;
    const unsubscribe = this.unsubscribe;
    this.unsubscribe = null;
    if (unsubscribe) Promise.resolve(unsubscribe()).catch(() => {});
  }

  onPush(payload) {
    this.server = payload;
    this.seq += 1;
    this.ops = this.ops.filter((op) => !op.settled);
    this.recompute();
  }

  recompute() {
    if (!this.server) return;
    let payload = this.server;
    for (const op of this.ops) {
      try {
        payload = op.apply(payload);
      } catch {
        // an optimistic guess that no longer fits the data is simply skipped
      }
    }
    this.state = { payload, index: buildIndex(payload), loading: false, error: null };
    this.emit();
  }

  /**
   * Run a websocket command. `optimistic(payload) -> payload` is shown until
   * the next push after the command settled; a rejection rolls it back and
   * rethrows a WsError.
   */
  async call(type, params = {}, { optimistic } = {}) {
    const op = optimistic ? { apply: optimistic, settled: false, seq: this.seq } : null;
    if (op) {
      this.ops.push(op);
      this.recompute();
    }
    try {
      const result = await this.hass.callWS({ ...params, type }); // `type` is the command, so issue types travel as `issue_type`
      if (op) this.settle(op);
      return result;
    } catch (error) {
      if (op) this.drop(op);
      throw toWsError(error);
    }
  }

  settle(op) {
    if (this.seq > op.seq) {
      this.drop(op); // the confirming push already arrived
      return;
    }
    op.settled = true;
    setTimeout(() => this.drop(op), SETTLE_TIMEOUT_MS);
  }

  drop(op) {
    const before = this.ops.length;
    this.ops = this.ops.filter((o) => o !== op);
    if (this.ops.length !== before) this.recompute();
  }

  get me() {
    return this.state.payload?.me || null;
  }

  get isAdmin() {
    return Boolean(this.state.payload?.is_admin);
  }
}

export const store = new Store();
