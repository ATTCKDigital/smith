/* stepper.js — the phase stepper and the FR-17 nesting label.
 *
 * Split out of panels.js exactly as T113 pre-decided (D-5/Q4): the four-state
 * rendering plus the nested-handoff case is the single largest renderer on the
 * page, and keeping it here leaves panels.js a readable list of panels.
 *
 * Everything in this file exists to let an operator tell EVIDENCE from
 * INFERENCE from a SELF-REPORT at a glance. That distinction is the product.
 * A stepper that renders "Phase 6 of 11" without saying how it knows is a
 * status monitor, and Smith already has one of those in its own logs.
 *
 * Exposes one global: window.SmithStepper.
 */

(function () {
  "use strict";

  /* Four states, four glyphs, four badge texts (FR-23a). The glyph is a
     SECOND channel beside colour, not decoration: SKIPPED and REMAINING are
     the pair an operator is most likely to confuse, and they are the pair
     that matters most — a skipped phase is a finding, a remaining one is not. */
  var STATE = {
    completed: { glyph: "✓", label: "completed" },
    current: { glyph: "▶", label: "current" },
    remaining: { glyph: "○", label: "remaining" },
    skipped: { glyph: "⊘", label: "SKIPPED" },
  };

  /* FR-19. Each provenance is labelled with WHAT KIND of knowledge it is.
     `marker_phase` is the highest-ranked signal the resolver has and is also
     the only one that is a SELF-REPORT — Smith writing down where it thinks it
     is. Rendering it identically to a hook-observed subagent block would hide
     the exact gap this dashboard exists to expose. */
  var PROVENANCE = {
    marker_phase: { kind: "declared", text: "marker phase (self-reported)" },
    subagent_block: { kind: "evidence", text: "subagent block" },
    live_task_event: { kind: "evidence", text: "live Task event" },
    skill_event: { kind: "evidence", text: "skill event" },
    workflow_start: { kind: "evidence", text: "workflow start" },
    subagent_completion: { kind: "evidence", text: "subagent completion" },
    artifact: { kind: "inferred", text: "from artifacts on disk" },
    child_marker: { kind: "inferred", text: "from a child workflow marker" },
  };

  function provenanceLabel(name) {
    var known = PROVENANCE[name];
    if (!known) return name ? "provenance: " + name : "";
    return known.kind + ": " + known.text;
  }

  /* --- the nesting label (FR-17) ----------------------------------------- */

  function segment(workflow) {
    var type = workflow.workflow_type || "workflow";
    var total = (workflow.phases || []).length;
    if (workflow.current_phase_id == null) {
      return type + " › phase unknown";
    }
    var where = total
      ? workflow.current_number + "/" + total
      : workflow.current_number;
    return type + " › " + where + " " + (workflow.current_title || "");
  }

  /* `smith-new › 6/6 Build Handoff → smith-build › 3/11 Testing`.
     The chain is rendered from the ROOT down to this workflow, and every
     workflow still gets its own card and its own stepper: nesting is SHOWN,
     never substituted for the thing it nests. */
  function nesting(workflow, byKey) {
    var chain = [workflow];
    var seen = {};
    var cursor = workflow;
    while (cursor && cursor.parent_key && !seen[cursor.parent_key]) {
      seen[cursor.parent_key] = true;
      cursor = byKey[cursor.parent_key];
      if (cursor) chain.unshift(cursor);
    }
    return chain.map(segment).join(" → ");
  }

  /* --- the honest unknown (FR-20) ---------------------------------------- */

  /* Never guess a phase name. When nothing resolves, say so and hand over the
     last phase that DID resolve, with its timestamp, so the operator has a
     floor to reason from rather than a blank. */
  function unknownText(workflow) {
    if (workflow.current_phase_id != null) return "";
    var last = workflow.last_known_phase;
    if (!last) {
      return "phase unknown — no signal has ever resolved a phase for this workflow.";
    }
    var where = last.number != null ? last.number + " " : "";
    var when = last.at || last.timestamp_text || "time unknown";
    return (
      "phase unknown — last known phase was " +
      where +
      (last.title || last.id || "?") +
      " at " +
      when +
      " (" +
      provenanceLabel(last.provenance) +
      ")."
    );
  }

  /* --- one phase row ------------------------------------------------------ */

  function phaseRow(phase, tplPhase) {
    var node = tplPhase.content.firstElementChild.cloneNode(true);
    var state = STATE[phase.state] || { glyph: "?", label: phase.state || "?" };
    node.classList.add("phase-" + (phase.state || "unknown"));
    node.querySelector(".phase-marker").textContent = state.glyph;
    node.querySelector(".phase-num").textContent =
      phase.number != null ? "#" + phase.number : "";
    node.querySelector(".phase-title").textContent =
      phase.title || phase.id || "";
    node.querySelector(".phase-state").textContent = state.label;

    /* FR-18. A MANDATORY STOP that is the current phase is not progress: it is
       the workflow waiting on the operator, and it is called that in words. */
    var stop = node.querySelector(".phase-stop");
    if (phase.mandatory_stop) {
      stop.hidden = false;
      if (phase.state === "current") node.classList.add("is-stop");
      else stop.textContent = "mandatory stop";
    }

    var prov = node.querySelector(".phase-prov");
    if (phase.provenance) {
      prov.hidden = false;
      prov.textContent = provenanceLabel(phase.provenance);
      prov.title = phase.evidence || "";
    }

    /* FR-58: the daemon-observed `entered_at` and the session log's own
       `timestamp_text` are labelled with their clocks and printed side by
       side. Nothing here compares them — a 4-hour skew between the two is
       pinned in the daemon's own tests and is not this renderer's to resolve. */
    var when = [];
    if (phase.entered_at) when.push("entered " + phase.entered_at);
    if (phase.exited_at) when.push("exited " + phase.exited_at);
    if (phase.timestamp_text) {
      when.push(
        "log says “" +
          phase.timestamp_text +
          "”" +
          (phase.clock ? " (" + phase.clock + " clock)" : ""),
      );
    }
    var at = node.querySelector(".phase-at");
    at.textContent = when.join(" · ");
    at.title = phase.evidence || "";
    return node;
  }

  function render(workflow, list, tplPhase) {
    var phases = workflow.phases || [];
    if (!phases.length) {
      var li = document.createElement("li");
      li.className = "empty";
      li.textContent =
        "no phase chain for workflow type “" +
        (workflow.workflow_type || "?") +
        "” — the resolver does not invent one.";
      list.appendChild(li);
      return;
    }
    phases.forEach(function (phase) {
      list.appendChild(phaseRow(phase, tplPhase));
    });
  }

  window.SmithStepper = {
    render: render,
    nesting: nesting,
    unknownText: unknownText,
    provenanceLabel: provenanceLabel,
  };
})();
