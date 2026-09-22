/* app.js — T112. The EventSource client, the state model, and the honesty
 * surfaces that belong to the STREAM rather than to a panel (T114).
 *
 * No framework, no build step, no module system: three plain <script defer>
 * tags in document order, communicating through two globals. The page is
 * versioned with the daemon it is served by, so there is nothing to bundle.
 *
 * Three things here are easy to get wrong and are therefore written out:
 *
 *  1. SILENCE IS NOT DEATH. Steady state is ~1 Hz and an IDLE dashboard
 *     receives nothing at all — unchanged entities are not re-upserted. The
 *     daemon's liveness signal is a `: keepalive` SSE comment every 20 s, and
 *     EventSource consumes comments without surfacing them to JS. So there is
 *     deliberately NO "no frame for N seconds → dead" timer here: it would
 *     light up red on a working, quiet system. Liveness comes from
 *     `EventSource.readyState` alone, and "last frame 4m ago" is reported as
 *     information, not as an alarm.
 *
 *  2. A LOWER GENERATION MEANS THE DAEMON RESTARTED (OOS-3). Retention is
 *     ephemeral; a restart is a blank slate. The page says so in a banner
 *     rather than showing a timeline that silently lost its first half.
 *
 *  3. AN UNKNOWN `event:` IS IGNORED. A stale cached tab degrades to "shows
 *     less", never to a JS exception.
 */

(function () {
  "use strict";

  var KEYS = {
    projects: "path",
    sessions: "session_id",
    subagents: "agent_id",
    workflows: "key",
    worktrees: "path",
    findings: "finding_id",
  };
  var COLLECTIONS = Object.keys(KEYS);

  var params = new URLSearchParams(window.location.search);
  var token = params.get("token") || "";
  var project = params.get("project") || "";

  var model = {
    token: token,
    project: project,
    generation: 0,
    stateGeneration: 0,
    hello: null,
    restarted: false,
    resyncReason: null,
    lastFrameAt: null,
    link: "connecting",
    error: null,
    data: emptyData(),
  };

  function emptyData() {
    var out = {
      quota: null,
      unattributed_events: 0,
      degraded: [],
      notices: [],
      capture_prompts: false,
    };
    COLLECTIONS.forEach(function (name) {
      out[name] = [];
    });
    return out;
  }

  function url(path, extra) {
    var q = new URLSearchParams();
    q.set("token", model.token);
    if (model.project) q.set("project", model.project);
    Object.keys(extra || {}).forEach(function (k) {
      q.set(k, extra[k]);
    });
    return path + "?" + q.toString();
  }

  /* --- generation tracking (OOS-3) --------------------------------------- */

  function noteGeneration(gen) {
    if (typeof gen !== "number") return;
    if (gen < model.generation) {
      // The daemon's counter only ever goes up while it lives, so a value
      // BELOW what we have already seen can only mean a new process. Reset to
      // zero so the fresh, smaller generations are accepted normally.
      model.restarted = true;
      model.generation = 0;
      model.stateGeneration = 0;
    }
    if (gen > model.generation) model.generation = gen;
  }

  /* --- applying frames ---------------------------------------------------- */

  function applyState(snap) {
    if (!snap || typeof snap !== "object") return;
    noteGeneration(snap.generation);
    // contracts/sse-frames.md §4.4: after a `resync` BOTH the re-fetched
    // /api/state and the daemon's own `state` frame arrive. Take whichever
    // lands first and discard the other by generation.
    if (
      typeof snap.generation === "number" &&
      snap.generation < model.stateGeneration
    ) {
      return;
    }
    COLLECTIONS.forEach(function (name) {
      if (Array.isArray(snap[name])) model.data[name] = snap[name].slice();
    });
    [
      "quota",
      "unattributed_events",
      "degraded",
      "notices",
      "capture_prompts",
    ].forEach(function (field) {
      if (Object.prototype.hasOwnProperty.call(snap, field)) {
        model.data[field] = snap[field];
      }
    });
    if (typeof snap.generation === "number")
      model.stateGeneration = snap.generation;
    render();
  }

  function applyDelta(delta) {
    if (!delta || typeof delta !== "object") return;
    noteGeneration(delta.generation);
    COLLECTIONS.forEach(function (name) {
      // An ABSENT key means "unchanged" — never "empty" (§4.3). Touching a
      // collection the daemon did not mention would blank a working panel.
      var change = delta[name];
      if (!change || typeof change !== "object") return;
      var key = KEYS[name];
      var index = {};
      model.data[name].forEach(function (entity) {
        if (entity && entity[key] != null) index[entity[key]] = entity;
      });
      // Every upsert is the WHOLE entity, so this is replace-by-key with no
      // patch-merge on either side.
      (change.upsert || []).forEach(function (entity) {
        if (entity && entity[key] != null) index[entity[key]] = entity;
      });
      (change.remove || []).forEach(function (k) {
        delete index[k];
      });
      model.data[name] = Object.keys(index).map(function (k) {
        return index[k];
      });
    });
    if (typeof delta.unattributed_events === "number") {
      model.data.unattributed_events = delta.unattributed_events;
    }
    render();
  }

  function applyQuota(frame) {
    if (!frame || typeof frame !== "object") return;
    noteGeneration(frame.generation);
    // The quota block ignores ?project= entirely, which is exactly why it
    // arrives on its own event name (§4.5).
    model.data.quota = frame;
    render();
  }

  function applyFinding(frame) {
    if (!frame || !frame.finding) return;
    noteGeneration(frame.generation);
    // `op: "retract"` carries the WHOLE finding with retracted: true. It is an
    // UPSERT of a settled entity, never a removal (FR-59) — so both ops take
    // the identical path here, and there is no code that can delete a card.
    applyDelta({
      generation: frame.generation,
      findings: { upsert: [frame.finding], remove: [] },
    });
  }

  /* --- the stream --------------------------------------------------------- */

  var source = null;

  function connect() {
    if (source) source.close();
    model.link = "connecting";
    render();
    source = new EventSource(url("/events"));

    source.onopen = function () {
      model.link = "live";
      render();
    };
    source.onerror = function () {
      // EventSource reconnects on its own and replays Last-Event-ID for us;
      // that header is what lets the daemon answer `resync` instead of a
      // history it cannot reproduce. Nothing to do but report the state.
      model.link = source && source.readyState === 1 ? "live" : "connecting";
      render();
    };

    on(source, "hello", function (data) {
      model.hello = data;
      model.data.capture_prompts = !!data.capture_prompts;
      model.data.degraded = data.degraded || [];
      noteGeneration(data.generation);
      model.link = "live";
      render();
    });
    on(source, "state", applyState);
    on(source, "delta", applyDelta);
    on(source, "quota", applyQuota);
    on(source, "finding", applyFinding);
    on(source, "resync", function (data) {
      model.resyncReason = (data && data.reason) || "unknown";
      if (model.resyncReason === "daemon-restart") {
        model.restarted = true;
        model.generation = 0;
        model.stateGeneration = 0;
      }
      coldStart();
    });
    // Any other `event:` name simply has no listener, so it is ignored.
  }

  function on(es, name, handler) {
    es.addEventListener(name, function (event) {
      model.lastFrameAt = Date.now();
      var data;
      try {
        data = JSON.parse(event.data);
      } catch (err) {
        return; // a frame we cannot parse is dropped, not thrown
      }
      handler(data);
    });
  }

  function coldStart() {
    fetch(url("/api/state"), { cache: "no-store" })
      .then(function (response) {
        if (response.status === 403) throw new Error("forbidden");
        return response.json();
      })
      .then(function (snap) {
        model.error = null;
        applyState(snap);
      })
      .catch(function (err) {
        model.error =
          err && err.message === "forbidden"
            ? "403 forbidden — the ?token= in this URL is absent or wrong."
            : "could not reach GET /api/state";
        render();
      });
  }

  /* --- project filter ----------------------------------------------------- */

  function onFilterChange(event) {
    model.project = event.target.value || "";
    var next = new URLSearchParams();
    if (model.token) next.set("token", model.token);
    if (model.project) next.set("project", model.project);
    window.history.replaceState({}, "", "/?" + next.toString());
    model.data = emptyData();
    model.stateGeneration = 0;
    coldStart();
    connect();
  }

  function render() {
    window.SmithPanels.renderAll(model);
  }

  var started = false;

  function start() {
    // `defer` scripts run at readyState "interactive", and DOMContentLoaded
    // then fires afterwards — so BOTH bootstrap paths below can fire for the
    // same load. This guard is what keeps that from opening two EventSource
    // connections and binding the filter twice. Declared with the rest of the
    // module state rather than after the call sites, because `var started`
    // hoists as undefined and an assignment below a call site would reset it.
    if (started) return;
    started = true;
    document
      .getElementById("project-filter")
      .addEventListener("change", onFilterChange);
    if (!model.token) {
      // /  and /static/* are un-gated so the page can LOAD and read its own
      // token; every datum is behind the gate (http-surface.md §1). With no
      // token the honest answer is to say so and stop, not to retry forever.
      model.error =
        "No ?token= in this URL. Open the dashboard with /smith-activity, " +
        "or append ?token=$(cat ~/.smith/activity/activity.token).";
      model.link = "down";
      render();
      return;
    }
    coldStart();
    connect();
    // Re-render on a slow timer purely so the relative "last frame N ago"
    // label stays truthful. It does not poll, and it never marks a quiet
    // stream as dead.
    window.setInterval(render, 5000);
  }

  document.addEventListener("DOMContentLoaded", start);
  if (document.readyState !== "loading") start();
})();
