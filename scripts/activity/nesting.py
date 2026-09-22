"""FR-17 nesting (T029) -- parent/child workflows, from the REAL markers first.

**Pure.** Operates on already-resolved Workflow records from ``resolver.py``,
mutating them in place; it opens no file and runs no git.

The derivation is marker-first because two concurrent markers were measured to
exist, superseding ``research.md`` >Q6. ``scripts/create-active-workflow.sh:139``
resolves the project root with ``git rev-parse --show-toplevel`` -- the
**worktree** -- while ``hooks/workflow-gate.sh:60`` uses
``${CLAUDE_PROJECT_DIR:-$(pwd)}`` -- the **primary repo**. So ``/smith-build``
launched by ``/smith-new`` on the same branch exits 0 rather than 3, and writes
a second marker into the worktree's own vault. A ``smith-new`` marker in the
primary vault and a ``smith-build`` marker in the worktree vault, same
``branch:``, is the NORMAL shape of a handoff -- and must never raise
``marker_contradiction``.

Cross-chain phase-title matching survives only as the fallback for when a child
marker is absent.

Lives beside ``resolver.py`` rather than inside it because that file reached the
repo's 500-line decompose threshold; ``resolver.py`` answers "where is this one
workflow", this module answers "how do these workflows relate".

Python 3.8, stdlib only.
"""

import phases as P


# ---------------------------------------------------------------------------
# FR-17 nesting (T029) -- from the TWO REAL MARKERS first
# ---------------------------------------------------------------------------


def _handoff_phases(phase_map, workflow):
    """``{target_workflow: phase}`` for every declared handoff in a chain."""
    targets = {}
    for phase in P.phases_for(phase_map, workflow):
        for target in P.handoff_targets(phase):
            targets.setdefault(target, phase)
    return targets


def _pin_at_handoff(parent, phase_id, child_type, evidence, provenance):
    """Park the parent stepper at its handoff phase and render the child under
    it. The parent is never replaced -- that is the whole point of FR-17."""
    states = parent["phases"]
    index_of = {state["id"]: index for index, state in enumerate(states)}
    if phase_id not in index_of:
        return
    target = index_of[phase_id]
    for index, state in enumerate(states):
        if index < target:
            if state["state"] == P.STATE_CURRENT:
                state["state"] = P.STATE_COMPLETED
            elif state["state"] == P.STATE_REMAINING:
                # A phase the chain has now moved past with no signal is
                # SKIPPED, not REMAINING (FR-23a). Pinning moves the frontier,
                # so this re-derivation has to happen here too.
                state["state"] = P.STATE_SKIPPED
                state["evidence"] = (
                    "no signal for this phase; a later phase in the chain was "
                    "reached"
                )
        elif index == target:
            state["state"] = P.STATE_CURRENT
            if not state["evidence"]:
                state["provenance"] = provenance
                state["evidence"] = evidence
        elif state["state"] == P.STATE_CURRENT:
            state["state"] = P.STATE_REMAINING

    pinned = states[target]
    parent["current_phase_id"] = phase_id
    parent["current_number"] = pinned["number"]
    parent["current_title"] = pinned["title"]
    parent["mandatory_stop"] = pinned["mandatory_stop"]
    parent["pinned_at_handoff"] = True
    parent["provenance"] = pinned["provenance"] or P.PROV_CHILD_MARKER
    if parent["permission"]["waiting"]:
        parent["activity"] = P.ACTIVITY_WAITING_PERMISSION
    elif pinned["mandatory_stop"]:
        parent["activity"] = P.ACTIVITY_WAITING_USER
    else:
        parent["activity"] = P.ACTIVITY_WORKING
    if P.NOTE_PHASE_UNKNOWN in parent["notes"]:
        parent["notes"].remove(P.NOTE_PHASE_UNKNOWN)
    note = "pinned at handoff phase %s for child %s" % (phase_id, child_type)
    if note not in parent["notes"]:
        parent["notes"].append(note)


def infer_child(workflow, phase_map):
    """FR-17 FALLBACK, used only when no child marker exists.

    Cross-chain phase-title matching, opening a nested child **only** at a
    phase carrying a ``handoff`` entry for that workflow. This was
    ``research.md`` >Q6's primary derivation; it is demoted to the fallback
    because two real markers were measured to exist. It records the inferred
    child and deliberately does NOT pin the parent: with no second marker there
    is no second piece of evidence, and moving a stepper on one inference is
    the kind of confident wrongness this feature exists to find.
    """
    handoffs = _handoff_phases(phase_map, workflow.get("workflow_type"))
    for cross in workflow.get("cross_chain") or []:
        target = cross.get("workflow")
        phase = handoffs.get(target)
        if phase is None:
            # No declared handoff from this chain to that one. T029 is explicit
            # that a child opens ONLY at a phase carrying a `handoff` entry, so
            # this is left alone -- findings.py judges it as FR-22(c).
            continue
        workflow["child_inferred"] = {
            "workflow_type": target,
            "phase_id": cross.get("phase_id"),
            "handoff_phase_id": phase["id"],
            "evidence": cross.get("evidence"),
            "provenance": cross.get("provenance"),
        }
        _pin_at_handoff(
            workflow,
            phase["id"],
            target,
            "handoff inferred from %s (no child marker found)"
            % (cross.get("evidence") or "a cross-chain signal"),
            cross.get("provenance"),
        )
        note = "child %s inferred; no child marker found" % target
        if note not in workflow["notes"]:
            workflow["notes"].append(note)
        return workflow["child_inferred"]
    return None


def resolve_nesting(workflows, phase_map):
    """FR-17 / T029. Correlate markers by ``branch:``; fall back to inference.

    The primary derivation needs no phase-title guessing at all, because
    ``create-active-workflow.sh:139`` (worktree root) and
    ``hooks/workflow-gate.sh:60`` (primary repo) put a ``smith-new`` marker in
    the primary vault and a ``smith-build`` marker in the worktree vault for
    the SAME branch, simultaneously. Two markers, one branch, different
    ``workflow:`` values, a declared ``handoff`` between their chains: that is a
    nest, and it must never raise ``marker_contradiction``.
    """
    by_branch = {}
    for workflow in workflows:
        by_branch.setdefault(workflow.get("branch") or "", []).append(workflow)

    for group in by_branch.values():
        if len(group) < 2:
            continue
        for parent in group:
            handoffs = _handoff_phases(phase_map, parent.get("workflow_type"))
            for child in group:
                if child is parent:
                    continue
                if child.get("workflow_type") == parent.get("workflow_type"):
                    continue
                phase = handoffs.get(child.get("workflow_type"))
                if phase is None:
                    continue
                child["parent_key"] = parent.get("key")
                if child.get("key") not in parent["child_keys"]:
                    parent["child_keys"].append(child.get("key"))
                _pin_at_handoff(
                    parent,
                    phase["id"],
                    child.get("workflow_type"),
                    "child marker %s (%s) exists on the same branch"
                    % (child.get("key"), child.get("workflow_type")),
                    P.PROV_CHILD_MARKER,
                )

    for workflow in workflows:
        if not workflow["child_keys"]:
            infer_child(workflow, phase_map)
    return workflows
