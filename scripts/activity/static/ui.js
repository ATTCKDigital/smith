/* ui.js — the shared DOM helpers, the top bar, and the banners.
 *
 * Second split off panels.js. T113 pre-decided ONE split (the stepper, D-5/Q4)
 * on the 300-line soft target; panels.js with the T114 honesty surfaces landed
 * at 554, past the repo's 500-line DECOMPOSE threshold, which is a hard rule
 * rather than a target. The seam taken here is a real one: everything in this
 * file is driven by the STREAM's state — link health, generation, restart,
 * degraded capabilities, prompt capture — while panels.js is driven by the
 * entity collections. They change for different reasons.
 *
 * Exposes two globals: window.SmithDom (helpers) and window.SmithBanners.
 */

(function () {
  "use strict";

  /* --- DOM helpers. textContent only; there is no innerHTML in this page. --- */

  var dom = {
    byId: function (id) {
      return document.getElementById(id);
    },
    tpl: function (id) {
      return document.getElementById(id).content.firstElementChild;
    },
    clear: function (node) {
      while (node.firstChild) node.removeChild(node.firstChild);
      return node;
    },
    put: function (node, selector, value) {
      node.querySelector(selector).textContent =
        value == null ? "" : String(value);
    },
    line: function (parent, text, cls) {
      var div = document.createElement("div");
      if (cls) div.className = cls;
      div.textContent = text;
      parent.appendChild(div);
      return div;
    },
    empty: function (node, text) {
      dom.line(dom.clear(node), text, "empty");
    },
    fmt: function (n) {
      return (n || 0).toLocaleString();
    },
    ago: function (stamp) {
      var s = Math.max(0, Math.round((Date.now() - stamp) / 1000));
      if (s < 90) return s + "s";
      if (s < 5400) return Math.round(s / 60) + "m";
      return Math.round(s / 3600) + "h";
    },
  };

  /* contracts/sse-frames.md §4.1. A capability gap is STATED in the operator's
     own words, never swallowed. An unrecognised token is printed verbatim
     rather than dropped: a page that silently ignores a gap it does not
     recognise is the exact failure A-9 forbids. */
  var DEGRADED = {
    "claude-agents-json:absent":
      "`claude agents --json` is unavailable. The sessions panel is hook-derived only and the dead-session reaper is off.",
    "claude-agents-json:no-waitingFor":
      "The installed Claude Code returns no `waitingFor`. “Waiting on permission” is derived from the PermissionRequest/PermissionDenied event stream instead, which is the primary source anyway.",
    "claude-agents-json:no-status":
      "The polled agent records carry no `status`, so no self-report exists to compare against. The permission indicator itself is unaffected — it is event-derived.",
    "pricing:missing":
      "Pricing data could not be loaded, so every USD figure is unavailable. Token counts are unaffected.",
    "expected-hooks:unknown":
      "~/.claude/settings.json was unreadable, so absence detection is DISABLED. That is a stated refusal, not a silent gap: Smith will not manufacture “this hook never fired” findings out of data it cannot see.",
  };

  /* --- top bar ------------------------------------------------------------- */

  function renderTop(model) {
    var link = dom.byId("link-state");
    link.className =
      "link-state " +
      (model.link === "live"
        ? "link-live"
        : model.link === "down"
          ? "link-down"
          : "link-connecting");
    /* A quiet stream is a WORKING stream. Unchanged entities are never
       re-upserted, so an idle dashboard legitimately receives nothing at all
       between the daemon's 20 s keepalive comments — and EventSource does not
       surface comments to JS. "live · last frame 6m ago" is the truth; a red
       dot after N silent seconds would be a lie about a healthy system. */
    link.textContent =
      model.link === "live"
        ? "live" +
          (model.lastFrameAt
            ? " · last frame " + dom.ago(model.lastFrameAt) + " ago"
            : "")
        : model.link;

    dom.byId("generation").textContent = "gen " + model.generation;

    /* `unattributed_events` is itself an audit signal (sse-frames §4.2):
       events the resolver DECLINED to place rather than guess. It is always
       shown, even at zero, so a rise is visible as a change rather than as the
       sudden appearance of a widget. */
    var un = dom.byId("unattributed");
    var count = model.data.unattributed_events || 0;
    un.hidden = false;
    un.textContent = count + " unattributed";
    un.style.color = count ? "" : "var(--muted)";
    un.style.fontWeight = count ? "" : "400";
    un.title =
      "Hook events the resolver could not attribute to any workflow and refused to guess about. " +
      "A rising count means this page is seeing less than is actually happening.";
  }

  /* --- banners ------------------------------------------------------------- */

  function banner(host, title, body, cls) {
    var div = document.createElement("div");
    div.className = "banner" + (cls ? " " + cls : "");
    var b = document.createElement("b");
    b.textContent = title;
    div.appendChild(b);
    if (body) {
      var span = document.createElement("span");
      span.textContent = body;
      div.appendChild(span);
    }
    host.appendChild(div);
    return div;
  }

  function bulletBanner(host, title, items, cls) {
    var div = banner(host, title, "", cls);
    var ul = document.createElement("ul");
    items.forEach(function (text) {
      var li = document.createElement("li");
      li.textContent = text;
      ul.appendChild(li);
    });
    div.appendChild(ul);
  }

  function render(model) {
    var host = dom.clear(dom.byId("banners"));

    if (model.error) {
      banner(host, "Not reading any data", model.error, "banner-alarm");
    }

    /* OOS-3. Retention is ephemeral and a restart is a blank slate. The page
       announces that, rather than showing a timeline that quietly lost its
       first half and looks merely short. */
    if (model.restarted) {
      banner(
        host,
        "History reset at daemon restart",
        "The daemon's generation counter went backwards, so this is a new process. " +
          "Retention is ephemeral: everything before the restart is gone, and none of " +
          "it is being shown here in truncated form.",
        "banner-alarm",
      );
    }
    if (model.resyncReason && model.resyncReason !== "daemon-restart") {
      banner(
        host,
        "Stream resynchronised (" + model.resyncReason + ")",
        "The daemon could not express a change as a delta, so this page re-fetched the full state.",
        "banner-warn",
      );
    }

    /* FR-48. Capture is OFF by default. When it is on the operator is told so
       on every render, because it changes what is retained about their
       prompts and tool calls. */
    if (model.data.capture_prompts) {
      banner(
        host,
        "Prompt capture is ACTIVE",
        "SMITH_ACTIVITY_CAPTURE_PROMPTS=1 — prompt text, tool inputs and tool " +
          "responses are being retained in the daemon's state and in activity.log. " +
          "Unset it and restart the daemon to return to the redacted default.",
        "banner-alarm",
      );
    }

    var degraded = model.data.degraded || [];
    if (degraded.length) {
      bulletBanner(
        host,
        "Degraded capabilities (" + degraded.length + ")",
        degraded.map(function (token) {
          return (
            token +
            " — " +
            (DEGRADED[token] || "no description for this token.")
          );
        }),
        "banner-warn",
      );
    }

    var notices = model.data.notices || [];
    if (notices.length) {
      bulletBanner(host, "Notices", notices, "banner-warn");
    }
  }

  window.SmithDom = dom;
  window.SmithBanners = { renderTop: renderTop, render: render };
})();
