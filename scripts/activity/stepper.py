"""The FR-11 phase stepper: signal builders and the state machine (T021-T030).

**Pure.** Inputs are the phase map, a marker record, already-parsed
session-log records, already-ingested hook events and an already-read artifact
snapshot (``artifacts.scan_artifacts``). Nothing here opens a file, runs a
subprocess or reads a clock; ``now`` and ``ended`` are parameters. That is what
makes SC-1/SC-2 replayable from fixtures with no daemon.

**Why this is not inside ``phases.py``.** tasks.md T021-T030 name
``scripts/activity/phases.py``. That file already carries the phase-map data
layer, title normalization, the fence-aware heading extractor and the FR-11
signal vocabulary, and stands at 374 lines; folding the state machine in would
put it near 700, past the repo's 500-line decompose threshold. The split is
along the seam the module docstrings already describe -- ``phases.py`` answers
"what phases and signals exist", this module answers "where is this workflow
now" -- and the same call that sanctioned ``attribution.py`` applies here.

**FR-58 is enforced structurally.** No function in this module reads
``timestamp_text``. Ordering is ``phases._order_of`` -- ingest ``seq``, else
append ``offset`` -- and nothing else. Parsed stamps ride along on every signal
labelled with their clock, for a renderer to print and for no one to compare.

Python 3.8, stdlib only.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

import phases as P

# FR-12 corroboration, expressed against phase NUMBERS rather than ids so the
# table reads like the spec's own table (data-model.md >2.5) and survives an
# id-scheme change. `complete` marks the phase done; `current` parks the
# workflow there. Both are rank-6 signals -- corroboration and cold-start
# fallback, never an override of something observed.
ARTIFACT_PHASES = {
    "smith-new": (
        ("spec.md", "3", "complete"),
        ("plan.md", "4", "complete"),
        ("questions.md", "4", "complete"),
    ),
    "smith-build": (("tasks.md", "1", "complete"),),
}


def _phase_by_number(phase_map, workflow, number):
    for phase in P.phases_for(phase_map, workflow):
        if str(phase.get("number")) == str(number):
            return phase
    return None


def _phase_by_id(phase_map, workflow, phase_id):
    for phase in P.phases_for(phase_map, workflow):
        if phase.get("id") == phase_id:
            return phase
    return None


def _display(record):
    """The three display-only fields every signal carries (FR-19/FR-58)."""
    return {
        "at": record.get("at"),
        "timestamp_text": record.get("timestamp_text"),
        "clock": record.get("clock"),
    }


def _cross(workflow, phase, order, text, evidence, at=None, provenance=None):
    """A signal that belongs to somebody ELSE's chain.

    Carries the provenance that produced it so FR-17's fallback nesting can
    label the phase it opens (FR-19) instead of rendering it unattributed.
    """
    return {
        "workflow": workflow,
        "phase_id": phase.get("id") if phase else None,
        "order": order,
        "text": text,
        "evidence": evidence,
        "at": at,
        "provenance": provenance,
    }


# ---------------------------------------------------------------------------
# Signal builders -- one per FR-11 source
# ---------------------------------------------------------------------------


def log_signals(records, workflow, phase_map):
    """FR-11 signals 1, 3, 4 and 5, from session-log records.

    Returns ``(signals, cross_chain)``. A block that names no phase in this
    workflow's chain but does name another chain's is NOT a signal -- it is a
    cross-chain observation, handed to FR-17 nesting and FR-22(c) to judge.
    Treating it as a signal here is precisely the bug that would advance a
    ``smith-new`` stepper on its child ``smith-build``'s events.
    """
    signals: List[Dict[str, Any]] = []
    cross: List[Dict[str, Any]] = []
    last_invoked = None
    chain = P.phases_for(phase_map, workflow)
    for index, record in enumerate(records or []):
        kind = record.get("kind")
        order = P._order_of(record, index)
        where = "log offset %s" % record.get("offset")
        if kind == "subagent_invoked":
            text = record.get("description") or ""
            phase = P.match_phase(phase_map, workflow, text)
            if phase is not None:
                last_invoked = phase
                signals.append(
                    P._signal(
                        P.PROV_SUBAGENT_BLOCK,
                        phase,
                        order,
                        "Subagent invoked: %s (%s)" % (text, where),
                        text=text,
                        **_display(record)
                    )
                )
            else:
                for other, other_phase in P.match_any_chain(
                    phase_map, text, exclude=workflow
                ):
                    cross.append(
                        _cross(
                            other,
                            other_phase,
                            order,
                            text,
                            "Subagent invoked: %s (%s)" % (text, where),
                            record.get("at"),
                            P.PROV_SUBAGENT_BLOCK,
                        )
                    )
        elif kind == "subagent_completed":
            # The heading is the bare literal `Subagent completed` -- no
            # description, no type -- so pairing is positional against the most
            # recent invocation in THIS attributed stream, the same limitation
            # subagent-vault-writeback.sh:13-19 documents. A completion with no
            # preceding invocation resolves nothing and is dropped rather than
            # guessed onto a phase.
            if last_invoked is not None:
                signal = P._signal(
                    P.PROV_SUBAGENT_COMPLETION,
                    last_invoked,
                    order,
                    "Subagent completed (%s)" % where,
                    **_display(record)
                )
                signal["terminal"] = True
                signals.append(signal)
        elif kind == "skill_event":
            skill = record.get("skill") or ""
            text = ("/%s %s" % (skill, record.get("event") or "")).strip()
            phase = P.match_phase(phase_map, workflow, text)
            if phase is not None:
                signals.append(
                    P._signal(
                        P.PROV_SKILL_EVENT,
                        phase,
                        order,
                        "skill event %s (%s)" % (text, where),
                        text=text,
                        **_display(record)
                    )
                )
            elif skill in P.workflow_names(phase_map) and skill != workflow:
                # `/smith-build invocation` inside a smith-new stream. No
                # smith-build phase pattern contains its own workflow name, so
                # match_any_chain would miss this; naming the chain directly is
                # what makes the FR-17 handoff detectable at all.
                cross.append(
                    _cross(
                        skill,
                        None,
                        order,
                        text,
                        "skill event %s (%s)" % (text, where),
                        record.get("at"),
                        P.PROV_SKILL_EVENT,
                    )
                )
            else:
                for other, other_phase in P.match_any_chain(
                    phase_map, text, exclude=workflow
                ):
                    cross.append(
                        _cross(
                            other,
                            other_phase,
                            order,
                            text,
                            "skill event %s (%s)" % (text, where),
                            record.get("at"),
                            P.PROV_SKILL_EVENT,
                        )
                    )
        elif kind == "workflow_start" and chain:
            signals.append(
                P._signal(
                    P.PROV_WORKFLOW_START,
                    chain[0],
                    order,
                    "workflow-start %s (%s)" % (record.get("branch") or "", where),
                    **_display(record)
                )
            )
    return signals, cross


def event_signals(events, workflow, phase_map):
    """FR-11 signal 2 -- live ``PreToolUse`` ``Task`` hook events.

    Advance optimistically; FR-22's two-sided window reconciles against the
    log block afterwards. Nothing here assumes the event arrived before or
    after the block, because all four workflow SKILLs write the block first and
    the harness still delivers the event on its own schedule.
    """
    signals: List[Dict[str, Any]] = []
    cross: List[Dict[str, Any]] = []
    for index, event in enumerate(events or []):
        if event.get("hook_event_name") != "PreToolUse":
            continue
        if event.get("tool_name") != "Task":
            continue
        tool_input = event.get("tool_input") or {}
        text = " ".join(
            part
            for part in (
                tool_input.get("description"),
                tool_input.get("subagent_type"),
            )
            if part
        )
        order = P._order_of(event, index)
        ident = event.get("tool_use_id") or event.get("prompt_id") or text
        phase = P.match_phase(phase_map, workflow, text)
        if phase is not None:
            signals.append(
                P._signal(
                    P.PROV_LIVE_TASK_EVENT,
                    phase,
                    order,
                    "PreToolUse Task %s" % ident,
                    text=text,
                    at=event.get("timestamp"),
                    clock=None,
                )
            )
        else:
            for other, other_phase in P.match_any_chain(
                phase_map, text, exclude=workflow
            ):
                cross.append(
                    _cross(
                        other,
                        other_phase,
                        order,
                        text,
                        "PreToolUse Task %s" % ident,
                        event.get("timestamp"),
                        P.PROV_LIVE_TASK_EVENT,
                    )
                )
    return signals, cross


def artifact_signals(snapshot, workflow, phase_map):
    """FR-11 signal 6 -- artifact presence, from an ``artifacts`` snapshot.

    A file READ never reaches here: the snapshot records which files EXIST, and
    no signal in this module is derived from a tool call reading one. That is
    how FR-12's "a Read must never advance a phase" is enforced -- structurally,
    not by a guard clause. ``smith-build`` Phase 3.5 reading
    ``skills/smith-clean-code/SKILL.md`` as a rubric produces no snapshot entry
    and therefore no signal.
    """
    signals: List[Dict[str, Any]] = []
    if not snapshot:
        return signals
    files = snapshot.get("files") or {}
    chain = P.phases_for(phase_map, workflow)
    index_of = {phase.get("id"): i for i, phase in enumerate(chain)}

    def emit(phase, mode, evidence):
        if phase is None:
            return
        order = (P.ARTIFACT_ORDER, index_of.get(phase.get("id"), 0), 0)
        signal = P._signal(P.PROV_ARTIFACT, phase, order, evidence)
        signal["terminal"] = mode == "complete"
        signals.append(signal)

    for name, number, mode in ARTIFACT_PHASES.get(workflow, ()):
        if name in files:
            emit(
                _phase_by_number(phase_map, workflow, number),
                mode,
                "%s present at %s" % (name, files[name].get("path")),
            )

    questions = snapshot.get("questions")
    if workflow == "smith-new" and "questions.md" in files and questions:
        if questions.get("unanswered"):
            emit(
                _phase_by_number(phase_map, workflow, "5"),
                "current",
                "questions.md has %d unanswered question(s)"
                % questions["unanswered"],
            )

    tasks = snapshot.get("tasks")
    if workflow == "smith-build" and "tasks.md" in files and tasks:
        total = tasks.get("total") or 0
        checked = tasks.get("checked") or 0
        if total and checked > 0:
            emit(
                _phase_by_number(phase_map, workflow, "2"),
                "complete" if checked >= total else "current",
                "tasks.md %d of %d boxes checked" % (checked, total),
            )
    return signals


def build_signals(marker, records=(), events=(), snapshot=None, phase_map=None):
    """Every FR-11 signal for one workflow, in FR-58 ingest order.

    Returns ``(signals, cross_chain)``. The sort is the only place ordering is
    decided, and it keys on ``phases._order_of`` alone.
    """
    workflow = (marker or {}).get("workflow_type")
    log_sig, log_cross = log_signals(records, workflow, phase_map)
    event_sig, event_cross = event_signals(events, workflow, phase_map)
    signals = log_sig + event_sig + artifact_signals(snapshot, workflow, phase_map)
    signals.sort(key=lambda s: s["order"])
    cross = log_cross + event_cross
    cross.sort(key=lambda c: c["order"])
    return signals, cross
