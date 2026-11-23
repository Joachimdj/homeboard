// Guards for the phone layout of dialogs. Home Assistant sets viewport-fit=cover, so the page draws under
// the notch and the status bar; a full-screen dialog without safe-area padding hides its close button.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("../../custom_components/homeboard/static/styles.js", import.meta.url), "utf8");
const phone = css.slice(css.indexOf("@media (max-width: 720px)"));

test("full-screen dialogs keep their header below the notch", () => {
  assert.match(phone, /\.dialog:not\(\.small\) \.dialog-header[^}]*env\(safe-area-inset-top/);
});

test("dialog footers stay above the home indicator", () => {
  assert.match(phone, /\.dialog-footer[^}]*env\(safe-area-inset-bottom/);
});

test("the phone Close button is only shown on phones", () => {
  assert.match(css, /\n\.mobile-only \{ display: none; \}/);
  assert.match(phone, /\.dialog-footer\.mobile-only \{ display: flex; \}/);
});
