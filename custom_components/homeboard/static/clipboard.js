// Copy text to the clipboard. navigator.clipboard only exists on https and localhost; a Home Assistant
// on plain http (the common case on a LAN address) needs the old textarea + execCommand way.

import { deepActiveElement } from "./dom.js";

/** Resolves true when the text was copied. Never throws. */
export async function copyText(text) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // fall through to the textarea trick
  }
  const previous = deepActiveElement();
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    Object.assign(area.style, { position: "fixed", top: "0", left: "0", opacity: "0" });
    document.body.append(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  } catch {
    return false;
  } finally {
    previous?.focus?.({ preventScroll: true });
  }
}
