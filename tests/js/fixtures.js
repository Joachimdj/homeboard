// Shared test data: the browser harness backend with a frozen clock.

import { MockBackend } from "../browser/mock-backend.js";
import { buildIndex } from "../../custom_components/homeboard/static/indexes.js";

export const NOW = new Date(2026, 10, 22, 12, 0, 0); // Sunday 22 Nov 2026, local time

export function makeBackend(options = {}) {
  return new MockBackend({ now: () => NOW, ...options });
}

export function makeState(backend = makeBackend()) {
  const payload = backend.payload();
  return { backend, payload, index: buildIndex(payload) };
}

export const issueByKey = (index, key) => index.issueByKey.get(key);
