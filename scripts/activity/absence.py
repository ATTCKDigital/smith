"""FR-23 absence, FR-60 expectation and FR-61 shipped-but-not-wired.

**Pure.** ``wired``, ``shipped``, ``fired`` and ``tools_used`` all arrive
already read, from ``hookset.py``. Nothing here opens a file.

Split out of ``findings.py`` (which reached 352 lines with only the divergence
half written) along the seam of its inputs: every function here judges
something that was EXPECTED against something that HAPPENED, and they share the
wired / shipped / applicability inputs entirely. ``shipped_not_wired`` is a
divergence classification rather than an absence one and still belongs here for
that reason -- it is the same diff, run in the other direction.

**Absence is rendered explicitly, never as the lack of a presence indicator**
(FR-23). Every function below returns findings, not gaps.

**When expectation is unknown, absence detection is OFF** (FR-60). It is never
guessed from a shipped default set and never derived from the repo's
``settings/smith-settings-fragment.json`` -- ``docs/hooks.md:5`` tells
operators to disable a hook by deleting its settings entry, so either source
would accuse the operator's own deliberate choice.

Python 3.8, stdlib only.
"""

from typing import Any, Dict, List, Optional, Sequence, Set

import findings as F
import phases as P

# FR-60's applicability table. A hook is only "expected" for a session that did
# the thing it hooks: `lint-on-save` cannot fire in a session with no Write or
# Edit, and reporting it as never-fired there would be noise indistinguishable
# from a real regression. `()` for tools means "every tool for that event".
HOOK_APPLICABILITY = {
    "lint-on-save.sh": ("PostToolUse", ("Write", "Edit")),
    "context-budget-guard.sh": ("PostToolUse", ("Write", "Edit")),
    "manifest-updater.sh": ("PostToolUse", ("Write", "Edit")),
    "file-change-logger.sh": ("PostToolUse", ("Write", "Edit", "NotebookEdit")),
    "metrics-tracker.sh": ("PostToolUse", ()),
    "security-guard-bash.sh": ("PreToolUse", ("Bash",)),
    "security-guard-files.sh": ("PreToolUse", ("Write", "Edit", "NotebookEdit")),
    "security-guard-mcp-browser.sh": ("PreToolUse", ("mcp__playwright__",)),
    "workflow-gate.sh": ("PreToolUse", ("Bash", "Write", "Edit", "NotebookEdit")),
    "task-router.sh": ("PreToolUse", ("Task",)),
    "subagent-vault-writeback.sh": ("SubagentStop", ()),
    "session-start-logger.sh": ("SessionStart", ()),
    "user-prompt-logger.sh": ("UserPromptSubmit", ()),
    "context-loader.sh": ("UserPromptSubmit", ()),
    "session-end-review.sh": ("Stop", ()),
    "active-workflow-janitor.sh": ("Stop", ()),
    "workflow-summary.sh": ("Stop", ()),
    "stamp-response.sh": ("Stop", ()),
    "grade-response.sh": ("Stop", ()),
}


def expected_hook_set(wired, tools_used=None):
    """FR-60 / T038. ``wired`` INTERSECTED with the applicability table.

    ``wired`` is ``hookset.wired_hooks()`` output, or ``None`` when the
    installed ``~/.claude/settings.json`` could not be read.

    Returns ``None`` -- meaning **absence detection is disabled** -- when
    ``wired`` is None. That ``None`` propagates all the way to the UI notice;
    it is never quietly replaced by an empty set, because an empty set would
    read as "nothing was expected, so nothing is missing", which is a lie with
    the same shape as the truth.

    A wired hook with no applicability entry is NOT expected. The table is the
    only thing that knows when a hook should fire, and inventing an expectation
    for an unknown hook would manufacture a finding out of ignorance.
    """
    if wired is None:
        return None
    tools = set(tools_used) if tools_used is not None else None
    expected = set()
    for name in wired:
        entry = HOOK_APPLICABILITY.get(name)
        if entry is None:
            continue
        _event, applies_to = entry
        if not applies_to or tools is None:
            expected.add(name)
            continue
        for tool in applies_to:
            if any(used.startswith(tool) for used in tools):
                expected.add(name)
                break
    return expected


def hook_never_fired_findings(expected, fired, workflow_key=None, timestamp=None):
    """FR-23(c) / T037. Wired, applicable, and never fired.

    ``expected is None`` yields ``[]``: detection is off, and this
    classification is never emitted from a guess.
    """
    if expected is None:
        return []
    actually_fired = set(fired or ())
    out = []
    for name in sorted(set(expected) - actually_fired):
        out.append(
            F.make_finding(
                F.KIND_ABSENCE,
                F.CLASS_HOOK_NEVER_FIRED,
                name,
                F.SEVERITY_WARN,
                workflow_key=workflow_key,
                observed="no event from %s in this session" % name,
                self_reported="wired in the installed ~/.claude/settings.json",
                timestamp=timestamp,
                evidence="%s is wired and applicable to this session but never "
                "fired" % name,
            )
        )
    return out


def shipped_not_wired_findings(shipped, wired, workflow_key=None, timestamp=None):
    """FR-61 / T039. "Smith ships this hook, your settings don't wire it."

    ``shipped is None`` (no installer-staged manifest yet) yields ``[]``. With
    no "what Smith ships" side there is nothing to diff, and diffing against an
    empty set would declare every installed hook unshipped.

    Distinct in classification from ``hook_never_fired``: that one is "wired but
    never fired", this one is "never wired at all". This feature's own planning
    produced a live instance -- ``hooks/pricing.json`` is in the repo and has
    never been installed (FR-62) -- which a repo-derived expectation would have
    reported as healthy.
    """
    if shipped is None:
        return []
    wired_names = set(wired or {})
    out = []
    for name in sorted(set(shipped) - wired_names):
        out.append(
            F.make_finding(
                F.KIND_DIVERGENCE,
                F.CLASS_SHIPPED_NOT_WIRED,
                name,
                F.SEVERITY_WARN,
                workflow_key=workflow_key,
                observed="%s is in the installer-staged shipped-hook manifest"
                % name,
                self_reported=None,
                timestamp=timestamp,
                evidence="the installed ~/.claude/settings.json wires no entry "
                "for %s" % name,
            )
        )
    return out


def phase_absence_findings(workflow, ended=False):
    """FR-23(a) and FR-23(b) / T037, from a resolved workflow's PhaseStates.

    T037 reads literally: ``phase_skipped`` is "one finding per ``skipped``
    PhaseState" and ``gate_never_reached`` is "a ``mandatory_stop`` phase the
    workflow advanced past or ended before". A skipped GATE is therefore both,
    and emits both -- they are different statements about the same phase, with
    different classifications and different subjects, and the gate finding
    carries the severity the operator needs to see. Suppressing one to make the
    count prettier would hide a gate that was jumped.
    """
    out = []
    for state in workflow.get("phases") or []:
        skipped = state.get("state") == P.STATE_SKIPPED
        unreached = ended and state.get("state") == P.STATE_REMAINING
        subject = "%s|%s" % (workflow.get("key"), state.get("id"))
        if state.get("mandatory_stop") and (skipped or unreached):
            out.append(
                F.make_finding(
                    F.KIND_ABSENCE,
                    F.CLASS_GATE_NEVER_REACHED,
                    subject,
                    F.SEVERITY_WARN,
                    workflow_key=workflow.get("key"),
                    phase_id=state.get("id"),
                    observed="no signal for %s (%s)"
                    % (state.get("id"), state.get("title")),
                    self_reported=None,
                    timestamp=None,
                    evidence="MANDATORY STOP gate %s was %s"
                    % (
                        state.get("id"),
                        "advanced past" if skipped else "never reached before the "
                        "workflow ended",
                    ),
                )
            )
        if skipped:
            out.append(
                F.make_finding(
                    F.KIND_ABSENCE,
                    F.CLASS_PHASE_SKIPPED,
                    subject,
                    F.SEVERITY_INFO,
                    workflow_key=workflow.get("key"),
                    phase_id=state.get("id"),
                    observed="no signal for %s (%s)"
                    % (state.get("id"), state.get("title")),
                    self_reported=None,
                    timestamp=None,
                    evidence=state.get("evidence")
                    or "a later phase in the chain was reached",
                )
            )
    return out
