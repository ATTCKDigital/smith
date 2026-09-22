/* panels.js — T113/T114. One render function per entity panel.
 *
 * Every string that reaches the DOM goes through textContent. There is no
 * innerHTML anywhere in this page, so no session path, branch name, evidence
 * string or finding body can become markup.
 *
 * The T114 honesty surfaces are not decoration on top of these panels — they
 * are what the panels are for. Owned here:
 *   - `phase unknown` with the last known phase and its timestamp (FR-20)
 *   - mandatory-stop rendered as WAITING, never as working (FR-18)
 *   - a retracted finding re-rendered SETTLED, never removed (FR-59)
 *   - both sides of a finding, including a null side (FR-21)
 *   - usd: null rendered "unavailable", never $0.00 (FR-34)
 *   - an explicit "quota unavailable" state that degrades nothing else (FR-35)
 * Owned by stepper.js: the four phase states (FR-23a) and the provenance
 * badges (FR-19). Owned by ui.js: the degraded[] list, prompt capture, the
 * daemon-restart banner and the unattributed_events counter.
 *
 * Exposes one global: window.SmithPanels.
 */

(function () {
  "use strict";

  var D = window.SmithDom;

  var ACTIVITY = {
    working: "working",
    waiting_on_user: "WAITING ON YOU",
    waiting_on_permission: "WAITING ON PERMISSION",
    unknown: "phase unknown",
  };

  /* --- workflows ----------------------------------------------------------- */

  function renderWorkflows(model) {
    var host = D.clear(D.byId("workflows"));
    var workflows = model.data.workflows || [];
    if (!workflows.length) {
      return D.empty(
        host,
        "No active workflows. One appears here when an active-workflow marker exists in a registered project's vault.",
      );
    }
    var byKey = {};
    workflows.forEach(function (w) {
      byKey[w.key] = w;
    });
    var tplWorkflow = D.tpl("tpl-workflow");
    var tplPhase = D.byId("tpl-phase");

    workflows.forEach(function (workflow) {
      var node = tplWorkflow.cloneNode(true);
      D.put(node, ".wf-nesting", window.SmithStepper.nesting(workflow, byKey));

      /* FR-18: "waiting on you" is never dressed up as progress. */
      var activity = node.querySelector(".wf-activity");
      activity.textContent =
        ACTIVITY[workflow.activity] || workflow.activity || "?";
      if (workflow.activity !== "working") activity.classList.add("badge-stop");

      /* The key is "<project>|<vault_root>|<filename>" with both paths
         absolute, so printing it whole buries the identifying part — the
         marker filename — at the end of a 200-character line. The project is
         already the page filter and the vault root is implied by
         is_primary_vault, so only the tail is shown. */
      var meta = [
        workflow.slug,
        workflow.branch && "branch " + workflow.branch,
        workflow.worktree,
        String(workflow.key || "")
          .split("|")
          .pop(),
        workflow.is_primary_vault === false && "worktree vault",
      ].filter(Boolean);
      if (workflow.ended) meta.push("ENDED");
      D.put(node, ".wf-meta", meta.join("  ·  "));

      /* FR-20: the honest unknown, with the last phase that did resolve. */
      var unknown = node.querySelector(".wf-unknown");
      var text = window.SmithStepper.unknownText(workflow);
      if (text) {
        unknown.hidden = false;
        unknown.textContent = text;
      }

      window.SmithStepper.render(
        workflow,
        node.querySelector(".stepper"),
        tplPhase,
      );

      var notes = (workflow.notes || []).slice();
      if (workflow.permission && workflow.permission.waiting) {
        notes.push("permission: " + workflow.permission.evidence);
      }
      if (workflow.pinned_at_handoff) {
        notes.push(
          "pinned at its handoff phase because a child workflow marker exists",
        );
      }
      notes.push(workflow.attributed_events + " attributed records/events");
      D.put(node, ".wf-notes", notes.join("  ·  "));
      host.appendChild(node);
    });
  }

  /* --- findings ------------------------------------------------------------ */

  function renderFindings(model) {
    var host = D.clear(D.byId("findings"));
    var findings = (model.data.findings || []).slice();
    if (!findings.length) {
      return D.empty(
        host,
        "No findings. Nothing Smith reported about itself disagrees with what the hooks observed.",
      );
    }
    /* Settled findings sort last. They are never dropped (FR-59). */
    findings.sort(function (a, b) {
      if (!!a.retracted !== !!b.retracted) return a.retracted ? 1 : -1;
      if (a.severity !== b.severity) return a.severity === "warn" ? -1 : 1;
      return String(b.timestamp || "").localeCompare(String(a.timestamp || ""));
    });
    var tplFinding = D.tpl("tpl-finding");

    findings.forEach(function (finding) {
      var node = tplFinding.cloneNode(true);
      node.classList.add("finding-" + (finding.kind || "divergence"));
      D.put(node, ".fi-class", finding.classification || "finding");
      D.put(node, ".fi-kind", finding.kind || "");
      var sev = node.querySelector(".fi-sev");
      sev.textContent = finding.severity || "";
      sev.classList.add("sev-" + (finding.severity || "info"));

      /* A retraction arrives as an UPSERT carrying retracted:true and a
         settled severity. The card stays on screen and visibly RESOLVES.
         There is no code path in this page that removes a finding card: a
         card that silently vanishes reads as a rendering glitch and destroys
         trust in the one panel that is this feature's product (FR-59). */
      if (finding.retracted) {
        node.classList.add("finding-settled");
        node.querySelector(".fi-settled").hidden = false;
      }

      /* FR-21: both sides, always, including a null side. A null IS the
         finding — it is one party having said nothing at all. */
      side(
        node.querySelector(".fi-observed"),
        finding.observed,
        "nothing observed",
      );
      side(
        node.querySelector(".fi-self"),
        finding.self_reported,
        "Smith reported nothing",
      );

      D.put(node, ".fi-evidence", finding.evidence || "");
      D.put(
        node,
        ".fi-where",
        [finding.workflow_key, finding.phase_id, finding.timestamp]
          .filter(Boolean)
          .join("  ·  ") + (finding.advisory ? "  ·  advisory" : ""),
      );
      host.appendChild(node);
    });
  }

  function side(node, value, nullText) {
    if (value == null || value === "") {
      node.textContent = nullText;
      node.classList.add("side-null");
    } else {
      node.textContent = String(value);
    }
  }

  /* --- the row panels ------------------------------------------------------ */

  function rows(hostId, items, emptyText, shape) {
    var host = D.clear(D.byId(hostId));
    if (!items || !items.length) return D.empty(host, emptyText);
    var tplRow = D.tpl("tpl-row");
    items.forEach(function (item) {
      var node = tplRow.cloneNode(true);
      var built = shape(item);
      D.put(node, ".row-title", built.title);
      if (built.badge) {
        var badge = node.querySelector(".row-badge");
        badge.hidden = false;
        badge.textContent = built.badge;
        if (built.alarm) badge.classList.add("badge-stop");
      }
      D.put(
        node,
        ".row-detail",
        (built.detail || []).filter(Boolean).join("  ·  "),
      );
      host.appendChild(node);
    });
  }

  function renderSessions(model) {
    rows(
      "sessions",
      model.data.sessions,
      "No live sessions for this filter.",
      function (s) {
        return {
          title: s.session_id,
          badge: (s.state || "unknown").replace(/_/g, " "),
          /* Blocked on a permission prompt is visually distinct from working:
           it is the operator who is the blocker, not the machine (FR-18). */
          alarm: s.state === "waiting_permission",
          detail: [
            s.cwd,
            s.model,
            s.branch,
            s.started_at && "started " + s.started_at,
            s.last_event_at && "last event " + s.last_event_at,
            s.usage &&
              s.usage.normalized != null &&
              D.fmt(s.usage.normalized) + " norm tokens",
          ],
        };
      },
    );
  }

  function renderSubagents(model) {
    rows(
      "subagents",
      model.data.subagents,
      "No subagents reported for this filter.",
      function (a) {
        return {
          title: a.agent_type || a.agent_id || "subagent",
          /* An unknown elapsed time is NOT zero: a dispatch whose start time
           could not be read renders as unknown, never as "just started". */
          badge:
            a.elapsed_s != null
              ? Math.round(a.elapsed_s) + "s"
              : "elapsed unknown",
          detail: [a.description, a.agent_id, a.tool_use_id],
        };
      },
    );
  }

  function renderWorktrees(model) {
    rows(
      "worktrees",
      model.data.worktrees,
      "No worktrees reported for this filter.",
      function (t) {
        var counts = [];
        if (t.ahead != null || t.behind != null) {
          counts.push("ahead " + nn(t.ahead) + " / behind " + nn(t.behind));
        }
        if (t.dirty_count != null) counts.push(t.dirty_count + " dirty");
        return {
          title: t.short_path || t.path,
          badge: t.is_primary
            ? "primary checkout"
            : t.exists
              ? "worktree"
              : "MISSING FROM DISK",
          alarm: !t.exists,
          detail: [
            t.branch ? "branch " + t.branch : "detached",
            t.base_branch ? "base " + t.base_branch : "base unresolved",
            counts.join(" · "),
            t.owning_marker && "marker " + t.owning_marker,
            t.occupying_session && "session " + t.occupying_session,
            !t.exists && "remedy: git worktree prune",
          ],
        };
      },
    );
  }

  function renderVault(model) {
    var host = D.clear(D.byId("vault"));
    var projects = model.data.projects || [];
    if (!projects.length) return D.empty(host, "No projects registered.");
    projects.forEach(function (project) {
      var snapshot = project.vault || {};
      var keys = Object.keys(snapshot);
      D.line(host, project.name || project.path, "row-title");
      if (!keys.length) {
        D.line(host, "no vault snapshot for this project", "empty");
        return;
      }
      keys.forEach(function (key) {
        D.line(host, key + ": " + JSON.stringify(snapshot[key]), "row-detail");
      });
    });
  }

  /* --- tokens and quota ---------------------------------------------------- */

  var WINDOWS = [
    ["five_hour", "5-hour window"],
    ["seven_day", "7-day window"],
    ["spend_limit", "spend limit"],
  ];

  function renderQuota(model) {
    var host = D.clear(D.byId("quota"));
    var quota = model.data.quota;
    if (!quota || !quota.available) {
      /* FR-35/SC-12. The windows come ONLY from the statusline payload; there
         is no API, file or CLI to fall back to. So "unavailable" is a real
         rendered state, and nothing else on the page degrades alongside it. A
         quota panel reading 0% beside eight working panels would be a lie. */
      D.line(host, "quota unavailable", "unknown");
      D.line(
        host,
        quota
          ? "The statusline payload carried no rate_limits (received " +
              (quota.received_at || "?") +
              ")."
          : "No statusline payload has reached the daemon yet, and the rolling windows have no other source.",
        "muted",
      );
      return;
    }
    var tplQuota = D.tpl("tpl-quota");
    WINDOWS.forEach(function (pair) {
      var win = quota[pair[0]];
      if (!win) return;
      var node = tplQuota.cloneNode(true);
      D.put(node, ".quota-name", pair[1]);
      D.put(node, ".quota-pct", win.used_percentage.toFixed(1) + "%");
      var fill = node.querySelector(".meter-fill");
      fill.style.width = Math.max(0, Math.min(100, win.used_percentage)) + "%";
      if (win.used_percentage >= 80) fill.classList.add("hot");
      D.put(
        node,
        ".quota-reset",
        win.resets_at
          ? "resets " + new Date(win.resets_at * 1000).toLocaleString()
          : "reset time unknown",
      );
      host.appendChild(node);
    });
    D.line(
      host,
      "account-wide · received " + (quota.received_at || "?"),
      "muted",
    );
  }

  function renderUsage(model) {
    var host = D.clear(D.byId("usage"));
    var parts = (model.data.sessions || [])
      .map(function (s) {
        return s.usage;
      })
      .filter(Boolean);
    if (!parts.length)
      return D.empty(host, "No token rollups for this filter.");

    /* Summed here from the per-session rollups, using the daemon's own rule
       (usage.merge_rollups): usd stays null only if EVERY part was null, and
       any incomplete part makes the whole figure incomplete. USD is never
       re-derived from the merged token totals, which would be wrong the
       moment two sessions used different models. */
    var total = {
      input: 0,
      output: 0,
      cache_write: 0,
      cache_read: 0,
      normalized: 0,
    };
    var usd = null;
    var complete = true;
    parts.forEach(function (part) {
      Object.keys(total).forEach(function (k) {
        total[k] += part[k] || 0;
      });
      if (part.usd != null) usd = (usd || 0) + part.usd;
      if (part.usd_complete === false || part.pricing_available === false)
        complete = false;
    });

    D.line(
      host,
      "tokens (summed from " + parts.length + " session rollups)",
      "row-title",
    );
    D.line(
      host,
      "in " +
        D.fmt(total.input) +
        " · out " +
        D.fmt(total.output) +
        " · cache w " +
        D.fmt(total.cache_write) +
        " / r " +
        D.fmt(total.cache_read) +
        " · normalized " +
        D.fmt(total.normalized),
      "row-detail",
    );
    /* FR-34: an unavailable cost is the WORD "unavailable". Never $0.00 —
       zero is a number, and a number here would be a claim. */
    D.line(
      host,
      usd == null
        ? "cost: unavailable (no priced model in these rollups)"
        : "cost: $" +
            usd.toFixed(4) +
            (complete ? "" : " (INCOMPLETE — some models are unpriced)"),
      usd == null ? "unknown" : "row-detail",
    );
  }

  function nn(v) {
    return v == null ? "?" : v;
  }

  /* --- the project filter -------------------------------------------------- */

  function renderFilter(model) {
    var select = D.byId("project-filter");
    var want = [""]
      .concat(
        (model.data.projects || []).map(function (p) {
          return p.path;
        }),
      )
      .join(" ");
    // Rebuilding the <select> on every render would reset an open dropdown a
    // second after the operator opened it, at the 1 Hz poll rate.
    if (select.dataset.built !== want) {
      select.dataset.built = want;
      D.clear(select);
      var all = document.createElement("option");
      all.value = "";
      all.textContent = "all projects";
      select.appendChild(all);
      (model.data.projects || []).forEach(function (project) {
        var option = document.createElement("option");
        option.value = project.path;
        option.textContent = project.name || project.path;
        select.appendChild(option);
      });
    }
    select.value = model.project;
  }

  function renderAll(model) {
    window.SmithBanners.renderTop(model);
    window.SmithBanners.render(model);
    renderFilter(model);
    renderWorkflows(model);
    renderFindings(model);
    renderSessions(model);
    renderSubagents(model);
    renderWorktrees(model);
    renderQuota(model);
    renderUsage(model);
    renderVault(model);
  }

  window.SmithPanels = { renderAll: renderAll };
})();
