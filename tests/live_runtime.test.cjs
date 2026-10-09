const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { resolve } = require("node:path");
const { runInNewContext } = require("node:vm");
const { test } = require("node:test");

function runtime() {
  const window = new EventTarget();
  const document = new EventTarget();
  const navigator = { onLine: true };
  const timers = new Map();
  let clock = 0;
  let counter = 0;
  document.hidden = false;
  window.setTimeout = (callback, delay) => {
    timers.set(++counter, { callback, time: clock + delay });
    return counter;
  };
  window.clearTimeout = (id) => timers.delete(id);
  const source = readFileSync(resolve(__dirname, "../apps/novelclaw/local_web_portal/app/static/live_runtime.js"), "utf8");
  runInNewContext(source, { window, document, navigator, AbortController });
  return {
    window, document, navigator, timers,
    poll: window.NovelClawLive.poll,
    async next() {
      const [id, timer] = [...timers].sort((a, b) => a[1].time - b[1].time)[0];
      timers.delete(id);
      clock = timer.time;
      timer.callback();
      await Promise.resolve();
      await Promise.resolve();
      return clock;
    },
  };
}

test("a slow request never overlaps with another poll; stopping aborts it", async () => {
  const rt = runtime();
  let requests = 0;
  let signal;
  const handle = rt.poll((input) => { requests++; signal = input; return new Promise(() => {}); }, { interval: 100 });
  await rt.next();
  rt.window.dispatchEvent(new Event("online"));
  rt.document.dispatchEvent(new Event("visibilitychange"));
  assert.equal(requests, 1);
  assert.equal(rt.timers.size, 1); // Only the request deadline remains.
  handle.stop();
  assert.equal(signal.aborted, true);
});

test("failures back off and a successful response restores the normal interval", async () => {
  const rt = runtime();
  let requests = 0;
  const handle = rt.poll(async () => { if (++requests < 3) throw new Error("offline"); }, { interval: 100 });
  assert.equal(await rt.next(), 0);
  assert.equal(await rt.next(), 200);
  assert.equal(await rt.next(), 600);
  assert.equal(await rt.next(), 700);
  handle.stop();
});

test("hidden and offline pages pause; returning to the page resumes once", async () => {
  const rt = runtime();
  let requests = 0;
  rt.document.hidden = true;
  const handle = rt.poll(async () => { requests++; });
  assert.equal(rt.timers.size, 0);
  rt.document.hidden = false;
  rt.document.dispatchEvent(new Event("visibilitychange"));
  await rt.next();
  assert.equal(requests, 1);
  rt.navigator.onLine = false;
  await rt.next();
  assert.equal(requests, 1);
  rt.navigator.onLine = true;
  rt.window.dispatchEvent(new Event("online"));
  await rt.next();
  assert.equal(requests, 2);
  handle.stop();
});

test("terminal jobs stop polling and release listeners", async () => {
  const rt = runtime();
  rt.poll(async () => false);
  await rt.next();
  rt.window.dispatchEvent(new Event("online"));
  rt.document.dispatchEvent(new Event("visibilitychange"));
  assert.equal(rt.timers.size, 0);
});
