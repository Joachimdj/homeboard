import assert from "node:assert/strict";
import { test } from "node:test";
import { moveIssue, patchIssue } from "../../custom_components/homeboard/static/optimistic.js";
import { Store, WsError, toWsError } from "../../custom_components/homeboard/static/store.js";
import { setLanguage } from "../../custom_components/homeboard/static/i18n.js";
import { makeBackend } from "./fixtures.js";

const tick = (ms = 0) => new Promise((resolve) => setTimeout(resolve, ms));

/** Minimal hass on top of the mock backend: counts subscriptions, rejects like HA. */
function fakeHass(backend, { latency = 5, pushDelay = 0 } = {}) {
  const hass = {
    language: "en",
    subscriptions: 0,
    active: 0,
    connection: {
      subscribeMessage: async (callback) => {
        hass.subscriptions += 1;
        hass.active += 1;
        const deliver = (payload) => (pushDelay ? setTimeout(() => callback(structuredClone(payload)), pushDelay) : callback(structuredClone(payload)));
        const stop = backend.subscribe(deliver);
        setTimeout(() => callback(structuredClone(backend.payload())), 0);
        return () => {
          hass.active -= 1;
          stop();
        };
      },
    },
    callWS: async (message) => {
      await tick(latency);
      try {
        return structuredClone(backend.handle(message));
      } catch (error) {
        throw { code: error.code, message: error.message };
      }
    },
  };
  return hass;
}

test("one subscription is shared and ref counted", async () => {
  const backend = makeBackend();
  const hass = fakeHass(backend);
  const store = new Store();
  const releaseA = store.acquire(hass);
  const releaseB = store.acquire({ ...hass }); // HA hands out a new hass object all the time
  await tick(10);
  assert.equal(hass.subscriptions, 1);
  assert.equal(hass.active, 1);
  assert.ok(store.state.index.projects.length === 2);
  assert.equal(store.state.loading, false);

  releaseA();
  releaseA(); // releasing twice must not drop the other holder
  assert.equal(hass.active, 1);
  releaseB();
  await tick(5);
  assert.equal(hass.active, 0);
});

test("releasing before the subscription is established still unsubscribes", async () => {
  const hass = fakeHass(makeBackend());
  const store = new Store();
  store.acquire(hass)();
  await tick(10);
  assert.equal(hass.active, 0);
});

test("pushes replace the state and notify listeners", async () => {
  const backend = makeBackend();
  const store = new Store();
  const hass = fakeHass(backend);
  const release = store.acquire(hass);
  await tick(10);
  let notified = 0;
  store.subscribe(() => notified++);
  const created = backend.handle({ type: "homeboard/issue/create", project_id: store.state.payload.projects[0].id, summary: "Pushed" });
  assert.equal(notified, 1);
  assert.ok(store.state.payload.issues.some((i) => i.summary === "Pushed"));
  assert.ok(store.state.index.issueByKey.has(created.key));
  release();
});

test("optimistic move is visible at once and reconciled by the push", async () => {
  const backend = makeBackend();
  const store = new Store();
  const hass = fakeHass(backend, { latency: 20 });
  const release = store.acquire(hass);
  await tick(10);
  const { index } = store.state;
  const issue = index.issueByKey.get("HOME-7");
  const home = index.projects.find((p) => p.key === "HOME");
  const done = home.statuses.find((s) => s.name === "Done").id;

  const pending = store.call("homeboard/issue/move", { issue_id: issue.id, status: done, before: null }, { optimistic: (p) => moveIssue(p, issue.id, done, null) });
  assert.equal(store.state.index.issueById.get(issue.id).status, done, "optimistic state shows immediately");
  assert.equal(backend.issues.get(issue.id).status === done, false, "server has not seen it yet");
  await pending;
  assert.equal(backend.issues.get(issue.id).status, done);
  assert.equal(store.state.index.issueById.get(issue.id).status, done);
  assert.equal(store.ops.length, 0, "the confirming push already arrived, the guess is dropped");
  release();
});

test("a rejected command rolls the optimistic update back and throws a WsError", async () => {
  const backend = makeBackend();
  const store = new Store();
  const release = store.acquire(fakeHass(backend));
  await tick(10);
  const issue = store.state.index.issueByKey.get("HOME-7");
  const before = issue.summary;
  await assert.rejects(
    store.call("homeboard/issue/update", { issue_id: issue.id, summary: "   " }, { optimistic: (p) => patchIssue(p, issue.id, { summary: "   " }) }),
    (error) => error instanceof WsError && error.code === "invalid_format",
  );
  assert.equal(store.state.index.issueById.get(issue.id).summary, before);
  assert.equal(store.ops.length, 0);
  release();
});

test("when the push lags behind the result the guess stays until the push arrives", async () => {
  const backend = makeBackend();
  const store = new Store();
  const release = store.acquire(fakeHass(backend, { latency: 1, pushDelay: 60 }));
  await tick(80);
  const issue = store.state.index.issueByKey.get("HOME-8");
  await store.call("homeboard/issue/update", { issue_id: issue.id, summary: "Lagged" }, { optimistic: (p) => patchIssue(p, issue.id, { summary: "Lagged" }) });
  assert.equal(store.state.index.issueById.get(issue.id).summary, "Lagged", "result is in, push is not: the guess is kept");
  assert.equal(store.ops.length, 1);
  await tick(100);
  assert.equal(store.ops.length, 0, "the push replaced the guess");
  assert.equal(store.state.index.issueById.get(issue.id).summary, "Lagged", "now from the server");
  release();
});

test("commands carry the command name in `type`, issue type as issue_type", async () => {
  const backend = makeBackend();
  const store = new Store();
  const hass = fakeHass(backend);
  const seen = [];
  const original = hass.callWS;
  hass.callWS = (message) => {
    seen.push(message);
    return original(message);
  };
  const release = store.acquire(hass);
  await tick(10);
  const project = store.state.payload.projects[0];
  const created = await store.call("homeboard/issue/create", { project_id: project.id, summary: "Typed", issue_type: "bug", type: "ignored" });
  assert.equal(seen.at(-1).type, "homeboard/issue/create");
  assert.equal(created.type, "bug");
  release();
});

test("a failing subscription surfaces the error and is retried on a later hass update", async () => {
  const backend = makeBackend();
  const store = new Store();
  const broken = { language: "en", connection: { subscribeMessage: async () => { throw { code: "unknown_command", message: "Unknown command" }; } }, callWS: async () => ({}) };
  const release = store.acquire(broken);
  await tick(5);
  assert.equal(store.state.error.code, "unknown_command");
  assert.equal(store.state.loading, false);

  store.setHass(fakeHass(backend)); // inside the cool-down: no retry yet
  await tick(5);
  assert.equal(store.state.error.code, "unknown_command");

  store.retryAt = 0;
  store.setHass(fakeHass(backend));
  await tick(10);
  assert.equal(store.state.error, null);
  assert.ok(store.state.index.projects.length > 0);
  release();
  setLanguage("en");
});

test("toWsError normalises HA rejections", () => {
  assert.equal(toWsError({ code: "unauthorized", message: "No" }).code, "unauthorized");
  assert.equal(toWsError(new Error("boom")).message, "boom");
  assert.equal(toWsError("text").message, "text");
  const error = new WsError("x", "y");
  assert.equal(toWsError(error), error);
});
