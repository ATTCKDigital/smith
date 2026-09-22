"""FR-14 concurrent-workflow attribution -- the feature's correctness thesis.

Two concurrent workflows in one repository write to the SAME session log.
Observed live while this feature was specified: ``60-activity-dashboard`` and
``67-deterministic-questions`` both named
``sessions/dennis-plucinik_ad8161_2026-09-22_145028.md``, and that one file
carries ``workflow-start 67-deterministic-questions`` at line 287 and
``workflow-start 60-activity-dashboard`` at line 310.

**Single assignment.** Every item lands in exactly one bucket: one workflow, or
the unattributed pile. There is no path on which an item reaches two
workflows, because the pass appends once and then moves on. "No block is
attributed to more than one" is therefore a structural property, not a
heuristic that happens to hold on the fixture.

**Ambiguity is DROPPED, never duplicated, never guessed.** For an audit tool a
confidently wrong stepper is worse than an honest blank one: the whole premise
is not trusting self-reports, and a dashboard that silently splits one
workflow's evidence across two panels would be the exact failure it exists to
detect. Dropped items are counted and surfaced (T048) -- a rising count is
itself an audit signal.

**The four rules NARROW, they do not each decide.** data-model.md >2.4 rule 3
says "matches exactly one **candidate** marker", so rules 1 and 2 are filters
over the candidate set and only a singleton assigns. This matters for the
normal ``smith-new`` -> ``smith-build`` nest, where BOTH markers carry the
same ``branch:`` and the same ``worktree:``: rules 1 and 2 cannot separate
them, and rule 3's chain match is what does.

A rule whose input is unavailable is SKIPPED, never applied to nothing. A
session-log block has no ``cwd``, and narrowing to the empty set on that basis
would discard evidence the next rule could have placed.

Python 3.8, stdlib only.
"""

import os
from typing import Any, Dict, List

import phases as P

RULE_SOLE = "sole_candidate"
RULE_WORKTREE = "worktree_prefix"
RULE_BRANCH = "branch"
RULE_PHASE_TEXT = "phase_text"
RULE_UNATTRIBUTED = "unattributed"


def _under(child, parent):
    """Exact prefix on realpathed absolute paths (data-model.md >2.4 rule 1).

    ``startswith`` on the raw strings would place ``/tmp/smith-activity`` inside
    ``/tmp/smith-act``; the separator guard is what makes it a PATH prefix
    rather than a string prefix. ``realpath`` is lexical for a path that does
    not exist, so a fixture with invented worktree paths behaves identically to
    a live one.
    """
    if not child or not parent:
        return False
    child = os.path.realpath(child)
    parent = os.path.realpath(parent)
    return child == parent or child.startswith(parent + os.sep)


def item_text(item):
    """The text rule 3 matches against a chain."""
    kind = item.get("kind")
    if kind == "subagent_invoked":
        return item.get("description") or ""
    if kind == "skill_event":
        return ("/%s %s" % (item.get("skill") or "", item.get("event") or "")).strip()
    if kind == "workflow_start":
        return item.get("branch") or ""
    if item.get("hook_event_name") == "PreToolUse" and item.get("tool_name") == "Task":
        tool_input = item.get("tool_input") or {}
        return " ".join(
            part
            for part in (tool_input.get("description"), tool_input.get("subagent_type"))
            if part
        )
    return item.get("text") or ""


def item_branch(item, resolve_branch=None):
    """The branch rule 2 compares, or None when it cannot be established.

    The ``workflow-start`` log record carries its branch in the line itself,
    which is why that one record type attributes cleanly in the observed
    two-workflow log while the ``Subagent invoked:`` blocks around it do not.
    """
    branch = item.get("branch")
    if branch:
        return branch
    cwd = item.get("cwd")
    if cwd and resolve_branch is not None:
        try:
            return resolve_branch(cwd)
        except Exception:
            return None
    return None


def attribute_item(item, markers, phase_map=None, resolve_branch=None):
    """Assign one item to at most one marker. Returns a decision dict.

    ``{"key", "rule", "reason", "candidates"}`` -- ``key`` is None for an
    unattributed item, and ``reason`` always says why, because "why was this
    dropped" is a question the findings panel has to be able to answer.
    """
    candidates = list(markers or [])
    log_path = item.get("session_log")
    if log_path:
        scoped = [
            marker
            for marker in candidates
            if not marker.get("session_log") or marker.get("session_log") == log_path
        ]
        if scoped:
            candidates = scoped

    if not candidates:
        return {
            "key": None,
            "rule": RULE_UNATTRIBUTED,
            "reason": "no candidate marker",
            "candidates": 0,
        }
    if len(candidates) == 1:
        return {
            "key": candidates[0].get("key"),
            "rule": RULE_SOLE,
            "reason": "only one active workflow could own this item",
            "candidates": 1,
        }

    # Rule 1 -- cwd inside the marker's worktree.
    cwd = item.get("cwd")
    if cwd:
        narrowed = [m for m in candidates if _under(cwd, m.get("worktree"))]
        if len(narrowed) == 1:
            return {
                "key": narrowed[0].get("key"),
                "rule": RULE_WORKTREE,
                "reason": "cwd %s is inside worktree %s"
                % (cwd, narrowed[0].get("worktree")),
                "candidates": 1,
            }
        if len(narrowed) > 1:
            candidates = narrowed

    # Rule 2 -- resolved branch equals the marker's branch.
    branch = item_branch(item, resolve_branch)
    if branch:
        narrowed = [m for m in candidates if (m.get("branch") or "") == branch]
        if len(narrowed) == 1:
            return {
                "key": narrowed[0].get("key"),
                "rule": RULE_BRANCH,
                "reason": "branch %s" % branch,
                "candidates": 1,
            }
        if len(narrowed) > 1:
            candidates = narrowed

    # Rule 3 -- the text names a phase in exactly one candidate's chain.
    text = item_text(item)
    if text and phase_map is not None:
        narrowed = []
        for marker in candidates:
            phase = P.match_phase(phase_map, marker.get("workflow_type"), text)
            if phase is not None:
                narrowed.append((marker, phase))
        if len(narrowed) == 1:
            marker, phase = narrowed[0]
            return {
                "key": marker.get("key"),
                "rule": RULE_PHASE_TEXT,
                "reason": "text names %s in the %s chain"
                % (phase.get("id"), marker.get("workflow_type")),
                "candidates": 1,
            }
        if len(narrowed) > 1:
            return {
                "key": None,
                "rule": RULE_UNATTRIBUTED,
                "reason": "text matches %d chains; dropped rather than duplicated"
                % len(narrowed),
                "candidates": len(narrowed),
            }

    return {
        "key": None,
        "rule": RULE_UNATTRIBUTED,
        "reason": "%d candidate markers and no rule separated them"
        % len(candidates),
        "candidates": len(candidates),
    }


# The session-log record kinds that carry FR-11 phase evidence. `section`,
# `user_prompt`, `file_change` and `tool_metrics` records are not evidence of a
# phase, and feeding them to the attribution pass would inflate
# `unattributed_events` with noise -- turning the one number that is supposed to
# mean "evidence this tool declined to place" into a line count. The token
# rollup (T068) attributes `tool_metrics` separately, with its own call.
EVIDENCE_KINDS = (
    "subagent_invoked",
    "subagent_completed",
    "skill_event",
    "workflow_start",
)


def evidence_records(records):
    """Filter session-log records to the kinds that carry phase evidence."""
    return [r for r in records or [] if r.get("kind") in EVIDENCE_KINDS]


def attribute_streams(
    records=(), events=(), markers=(), phase_map=None, resolve_branch=None
):
    """The whole FR-14 pass over both streams.

    Returns the per-key buckets plus ``unattributed_events`` -- one number
    across BOTH streams, because the operator's question is "how much evidence
    did this thing decline to place", not "how much of each kind".
    """
    keys = [m.get("key") for m in markers or []]
    by_records: Dict[str, List[Dict[str, Any]]] = {key: [] for key in keys}
    by_events: Dict[str, List[Dict[str, Any]]] = {key: [] for key in keys}
    dropped_records: List[Dict[str, Any]] = []
    dropped_events: List[Dict[str, Any]] = []
    decisions: List[Dict[str, Any]] = []

    for stream, items, bucket, dropped in (
        ("records", records, by_records, dropped_records),
        ("events", events, by_events, dropped_events),
    ):
        for index, item in enumerate(items or []):
            decision = attribute_item(
                item, markers, phase_map=phase_map, resolve_branch=resolve_branch
            )
            decision["stream"] = stream
            decision["index"] = index
            decisions.append(decision)
            key = decision["key"]
            if key is not None and key in bucket:
                bucket[key].append(item)
            else:
                dropped.append(item)

    return {
        "records": by_records,
        "events": by_events,
        "unattributed": {"records": dropped_records, "events": dropped_events},
        "unattributed_events": len(dropped_records) + len(dropped_events),
        "decisions": decisions,
    }
