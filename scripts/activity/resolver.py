"""PhaseState derivation, the honest unknown, nesting and the project pass.

**Pure.** ``now``, ``ended`` and every input are parameters. Third and last
piece of the T021-T030 state machine: ``phases.py`` holds the vocabulary,
``stepper.py`` turns raw records into FR-11 signals, and this module turns
signals into the ``data-model.md`` >2.5 PhaseState list and the >2.4
Workflow projection.

Three rules drive everything here:

* **FR-20 -- never guess.** When no signal resolves a phase the answer is
  ``current_phase_id: None`` plus ``last_known_phase``. There is no
  nearest-match, no interpolation and no carry-forward.
* **FR-11 signal 5 -- a completion means DONE, not running.** When the newest
  signal is terminal the workflow is BETWEEN phases, so ``current`` is None and
  the finished phase reports ``completed``. That reads as ``phase unknown``,
  which is the honest rendering of "nothing is running right now".
* **``skipped`` is first-class (FR-23a).** A phase that a later phase overtook
  without ever being signalled is ``skipped``, distinct from both ``completed``
  and ``remaining``, and it is what feeds the absence finding.

Python 3.8, stdlib only.
"""

from typing import Any, Dict, List, Optional, Sequence

import nesting
import phases as P
import stepper


def permission_state(events):
    """FR-18 PRIMARY source, T028: event-derived "waiting on permission".

    A ``PermissionRequest`` with no ``PermissionDenied`` and no ``PostToolUse``
    for the same call means waiting. Correlation prefers ``tool_use_id`` when
    both sides carry one and falls back to ``prompt_id``, because a turn can
    contain several tool calls under one prompt and clearing on the turn id
    alone would resolve the wrong request.

    ``claude agents --json`` is NOT consulted. Its ``status`` is corroboration
    only (FR-26, consumed in a later phase) and is absent on 17 of 23 observed
    records; letting it participate here would blank the indicator most of the
    time. ``waitingFor``, ``state`` and ``id`` do not exist and are never read.
    """
    pending: List[Dict[str, Any]] = []
    for event in events or []:
        name = event.get("hook_event_name")
        if name == "PermissionRequest":
            pending.append(event)
        elif name in ("PermissionDenied", "PostToolUse", "PostToolUseFailure"):
            keep = []
            for request in pending:
                if request.get("tool_use_id") and event.get("tool_use_id"):
                    resolved = request["tool_use_id"] == event["tool_use_id"]
                else:
                    resolved = (
                        request.get("prompt_id") is not None
                        and request.get("prompt_id") == event.get("prompt_id")
                    )
                if not resolved:
                    keep.append(request)
            pending = keep
    if not pending:
        return {
            "waiting": False,
            "prompt_id": None,
            "tool_use_id": None,
            "since": None,
            "evidence": "no outstanding PermissionRequest",
        }
    outstanding = pending[-1]
    return {
        "waiting": True,
        "prompt_id": outstanding.get("prompt_id"),
        "tool_use_id": outstanding.get("tool_use_id"),
        "since": outstanding.get("timestamp"),
        "evidence": "PermissionRequest %s with no PermissionDenied and no "
        "PostToolUse"
        % (outstanding.get("tool_use_id") or outstanding.get("prompt_id") or "?"),
    }


def _declared(marker, phase_map, workflow):
    """FR-13 / T023. The marker's ``phase:`` beats every inferred signal.

    Accepted as an id (``smith-new:5``), a bare number (``5``) or a title.
    Nothing writes one today; that is the point -- OOS-1's later stamping is a
    pure addition with no resolver rework.
    """
    declared = (marker or {}).get("declared_phase")
    if not declared:
        return None
    text = str(declared).strip()
    for phase in P.phases_for(phase_map, workflow):
        if text in (phase.get("id"), str(phase.get("number")), phase.get("title")):
            return phase
    return P.match_phase(phase_map, workflow, text)


def resolve_phases(marker, signals, phase_map, ended=False):
    """Signals in, ``data-model.md`` >2.5 PhaseState list out."""
    workflow = (marker or {}).get("workflow_type")
    chain = P.phases_for(phase_map, workflow)
    if not chain:
        # T030 / FR-20: an unmapped workflow type gets an EMPTY chain and an
        # explicit note. The resolver never invents one.
        return {
            "phases": [],
            "current_phase_id": None,
            "last_known_phase": None,
            "provenance": None,
            "notes": [P.NOTE_NO_PHASE_MAP],
        }

    index_of = {phase["id"]: i for i, phase in enumerate(chain)}
    best: Dict[str, Dict[str, Any]] = {}
    first: Dict[str, Dict[str, Any]] = {}
    terminal = set()
    latest = None

    for signal in signals or []:
        phase_id = signal.get("phase_id")
        if phase_id not in index_of:
            continue
        previous = best.get(phase_id)
        if previous is None or signal["rank"] < previous["rank"]:
            best[phase_id] = signal
        first.setdefault(phase_id, signal)
        if signal.get("terminal"):
            terminal.add(phase_id)
        # `latest` only ever moves FORWARD along the chain. The case this
        # exists for is real and was caught on the SC-1 fixture: the
        # `workflow-start` stamp that create-active-workflow.sh writes for the
        # CHILD workflow lands in the same log, later than the parent's Phase 5
        # block, and resolves to the parent chain's first phase. Without the
        # guard a completed smith-new snaps back to "Pre-Change Exploration"
        # the moment smith-build registers. phases.json invariant 2 makes the
        # chains strictly increasing, so forward-only is the shape of the data;
        # a rank-0 marker `phase:` (FR-13) is the one thing allowed to move it
        # anywhere, and it is applied after this loop.
        if latest is None or index_of[phase_id] >= index_of[latest["phase_id"]]:
            latest = signal

    declared_phase = _declared(marker, phase_map, workflow)
    notes: List[str] = []
    if declared_phase is not None:
        current_id = declared_phase["id"]
        provenance = P.PROV_MARKER_PHASE
        best[current_id] = P._signal(
            P.PROV_MARKER_PHASE,
            declared_phase,
            (0, 0, 0),
            "marker phase: %s" % marker.get("declared_phase"),
        )
    elif latest is None:
        current_id = None
        provenance = None
    elif latest.get("terminal"):
        # FR-11 signal 5: the phase is DONE, so nothing is running.
        current_id = None
        provenance = None
    else:
        current_id = latest["phase_id"]
        provenance = latest["provenance"]

    reached = set(best)
    frontier = -1
    for phase_id in reached:
        frontier = max(frontier, index_of[phase_id])
    if current_id is not None:
        frontier = max(frontier, index_of[current_id])

    states = []
    for index, phase in enumerate(chain):
        phase_id = phase["id"]
        signal = best.get(phase_id)
        if phase_id == current_id:
            state = P.STATE_CURRENT
        elif index > frontier:
            state = P.STATE_REMAINING
        elif signal is not None:
            state = P.STATE_COMPLETED
        else:
            state = P.STATE_SKIPPED
        states.append(
            {
                "id": phase_id,
                "number": phase.get("number"),
                "title": phase.get("title"),
                "mandatory_stop": bool(phase.get("mandatory_stop")),
                "state": state,
                "provenance": signal["provenance"] if signal else None,
                "entered_at": first.get(phase_id, {}).get("at") if signal else None,
                "exited_at": None,
                "evidence": signal["evidence"] if signal else "",
                "timestamp_text": signal.get("timestamp_text") if signal else None,
                "clock": signal.get("clock") if signal else None,
            }
        )

    # exited_at: a completed phase left when the next reached phase was entered,
    # or when its own terminal signal landed. Unknown stays None rather than
    # being back-filled from a neighbour.
    for index, state in enumerate(states):
        if state["state"] != P.STATE_COMPLETED:
            continue
        if state["id"] in terminal:
            state["exited_at"] = best[state["id"]].get("at")
        for later in states[index + 1 :]:
            if later["entered_at"]:
                state["exited_at"] = state["exited_at"] or later["entered_at"]
                break

    for state in states:
        if state["state"] == P.STATE_SKIPPED:
            state["evidence"] = (
                "no signal for this phase; a later phase in the chain was reached"
            )

    last_known = None
    if latest is not None:
        last_known = {
            "id": latest["phase_id"],
            "number": latest.get("number"),
            "title": latest.get("title"),
            "at": latest.get("at"),
            "timestamp_text": latest.get("timestamp_text"),
            "clock": latest.get("clock"),
            "provenance": latest["provenance"],
        }
    if current_id is None:
        notes.append(P.NOTE_PHASE_UNKNOWN)
    return {
        "phases": states,
        "current_phase_id": current_id,
        "last_known_phase": last_known,
        "provenance": provenance,
        "notes": notes,
    }


def resolve_workflow(
    marker, records=(), events=(), snapshot=None, phase_map=None, ended=False
):
    """One marker plus its ATTRIBUTED records and events -- one Workflow record.

    ``records`` and ``events`` must already have passed the FR-14 attribution
    pass (``attribution.attribute``). Handing this function an unattributed
    stream is the exact bug SC-2 exists to catch.
    """
    phase_map = phase_map if phase_map is not None else P.load_phase_map()
    signals, cross = stepper.build_signals(
        marker, records=records, events=events, snapshot=snapshot,
        phase_map=phase_map,
    )
    resolved = resolve_phases(marker, signals, phase_map, ended=ended)
    by_id = {state["id"]: state for state in resolved["phases"]}
    current = by_id.get(resolved["current_phase_id"])
    permission = permission_state(events)

    if permission["waiting"]:
        activity = P.ACTIVITY_WAITING_PERMISSION
    elif current is not None and current["mandatory_stop"]:
        # FR-18 / T027: "waiting on you" is never rendered as "working".
        activity = P.ACTIVITY_WAITING_USER
    elif current is not None:
        activity = P.ACTIVITY_WORKING
    else:
        activity = P.ACTIVITY_UNKNOWN

    return {
        "key": marker.get("key"),
        "workflow_type": marker.get("workflow_type"),
        "slug": marker.get("slug"),
        "branch": marker.get("branch"),
        "worktree": marker.get("worktree"),
        "session_log": marker.get("session_log"),
        "started": marker.get("started"),
        "declared_phase": marker.get("declared_phase"),
        "marker_path": marker.get("marker_path"),
        "vault_root": marker.get("vault_root"),
        "is_primary_vault": marker.get("is_primary_vault"),
        "phases": resolved["phases"],
        "current_phase_id": resolved["current_phase_id"],
        "current_number": current["number"] if current else None,
        "current_title": current["title"] if current else None,
        "mandatory_stop": bool(current["mandatory_stop"]) if current else False,
        "last_known_phase": resolved["last_known_phase"],
        "provenance": resolved["provenance"],
        "notes": resolved["notes"],
        "activity": activity,
        "permission": permission,
        "cross_chain": cross,
        "signals": signals,
        "parent_key": None,
        "child_keys": [],
        "pinned_at_handoff": False,
        "child_inferred": None,
        "ended": bool(ended),
        "attributed_events": len(list(records or [])) + len(list(events or [])),
    }


# ---------------------------------------------------------------------------
# The project pass (T048)
# ---------------------------------------------------------------------------


# FR-17 nesting lives in nesting.py; re-exported so a caller that resolved a
# project does not need to know the module split.
resolve_nesting = nesting.resolve_nesting
infer_child = nesting.infer_child


def resolve_project(
    markers,
    records=(),
    events=(),
    snapshots=None,
    phase_map=None,
    resolve_branch=None,
    ended_keys=(),
):
    """Markers plus both raw streams in, one project projection out.

    ``unattributed_events`` is surfaced as its own number rather than buried in
    a per-workflow field: it counts evidence the resolver DECLINED to place,
    and a rising count is itself an audit signal
    (contracts/sse-frames.md >4.2).
    """
    import attribution

    phase_map = phase_map if phase_map is not None else P.load_phase_map()
    split = attribution.attribute_streams(
        records=attribution.evidence_records(records),
        events=events,
        markers=markers,
        phase_map=phase_map,
        resolve_branch=resolve_branch,
    )
    ended = set(ended_keys or ())
    workflows = []
    for marker in markers or []:
        key = marker.get("key")
        workflows.append(
            resolve_workflow(
                marker,
                records=split["records"].get(key, []),
                events=split["events"].get(key, []),
                snapshot=(snapshots or {}).get(key),
                phase_map=phase_map,
                ended=key in ended,
            )
        )
    nesting.resolve_nesting(workflows, phase_map)
    return {
        "workflows": workflows,
        "unattributed_events": split["unattributed_events"],
        "attribution": split,
    }
