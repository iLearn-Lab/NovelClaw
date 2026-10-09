(function () {
  "use strict";

  function poll(work, options = {}) {
    const interval = options.interval || 1500;
    let timer = null;
    let inFlight = false;
    let stopped = false;
    let suspended = false;
    let failures = 0;
    let controller = null;
    const paused = () => suspended || document.hidden || navigator.onLine === false;

    function schedule(delay) {
      window.clearTimeout(timer);
      if (!stopped && !paused()) timer = window.setTimeout(tick, delay);
    }

    function stop() {
      stopped = true;
      window.clearTimeout(timer);
      if (controller) controller.abort();
      document.removeEventListener("visibilitychange", resume);
      window.removeEventListener("online", resume);
      window.removeEventListener("pagehide", hide);
      window.removeEventListener("pageshow", show);
    }

    async function tick() {
      if (stopped || inFlight || paused()) return;
      inFlight = true;
      controller = new AbortController();
      const timeout = window.setTimeout(() => controller?.abort(), options.timeout || 15000);
      try {
        const keepGoing = await work(controller.signal);
        failures = 0;
        if (keepGoing === false) stop();
      } catch (error) {
        if (!stopped && !paused()) {
          failures += 1;
          if (options.onError) options.onError(error, failures);
        }
      } finally {
        window.clearTimeout(timeout);
        controller = null;
        inFlight = false;
        schedule(Math.min(interval * (2 ** failures), options.maxInterval || 15000));
      }
    }

    function resume() { if (!inFlight) schedule(0); }
    function hide() {
      suspended = true;
      window.clearTimeout(timer);
      if (controller) controller.abort();
    }
    function show() { suspended = false; resume(); }
    document.addEventListener("visibilitychange", resume);
    window.addEventListener("online", resume);
    window.addEventListener("pagehide", hide);
    window.addEventListener("pageshow", show);
    schedule(0);
    return { stop, refresh: resume };
  }

  window.NovelClawLive = { poll };
})();
