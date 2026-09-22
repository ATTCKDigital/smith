"""Divergence and absence findings -- the audit product (T034-T042).

**Pure.** ``now`` is a parameter, never ``datetime.now()``, so the 90-second
window is testable without sleeping. The installed settings and the shipped
manifest arrive already parsed, from ``hookset.py``. Nothing here opens a file,
and nothing here modifies, pauses or interferes with the workflow being
audited (FR-24) -- every return value is a list of dicts.

Four rules the whole module is built on:

* **FR-21/FR-24 -- both sides, always.** Every finding carries ``observed``
  (hook-derived, the value that is DISPLAYED) and ``self_reported`` side by
  side. No function may "reconcile" a conflict by dropping one of them; the
  divergence IS the product, and a ``None`` on either side is itself the point.
* **FR-22 -- the window is 90 seconds, TWO-SIDED.** All four workflow SKILLs
  instruct the ``Subagent invoked:`` block to be written BEFORE the Agent call,
  so the block may precede the ``PreToolUse`` ``Task`` event as easily as
  follow it. The comparison is therefore ``abs(...)``, and FR-11's original
  one-directional assumption was wrong.
* **FR-58 -- never a parsed session-log stamp.** ``observed_at`` is the
  daemon's own ingest time. The ``[HH:MM:SS]`` stamps in the log mix UTC with
  model-local wall time (a four-hour skew occurs in this repository's own log)
  and are display only.
* **FR-59 -- retraction is an UPSERT to a settled state, not a removal.** A
  retracted finding stays in the list with ``retracted: True`` and a settled
  severity. ``findings.remove`` is reserved for a finding whose SUBJECT no
  longer exists. A finding that appears and silently vanishes reads as a
  rendering glitch and destroys trust in the panel this feature exists to
  produce.

Python 3.8, stdlib only.
"""

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

import phases as P

RECONCILE_WINDOW_S = 90

KIND_DIVERGENCE = "divergence"
KIND_ABSENCE = "absence"

SEVERITY_INFO = "info"
SEVERITY_WARN = "warn"

CLASS_SKILL_LOGGING_BUG = "skill_logging_bug"
CLASS_UNDESIGNED_PATH = "undesigned_path"
CLASS_MARKER_CONTRADICTION = "marker_contradiction"
CLASS_PERMISSION_DISAGREEMENT = "permission_disagreement"
CLASS_SHIPPED_NOT_WIRED = "shipped_not_wired"

CLASS_PHASE_SKIPPED = "phase_skipped"
CLASS_GATE_NEVER_REACHED = "gate_never_reached"
CLASS_HOOK_NEVER_FIRED = "hook_never_fired"

# The degraded token FR-60 requires on screen when the installed
# ~/.claude/settings.json cannot be read. Absence detection is OFF, and the
# operator is told so -- it is never silently degraded and never guessed.
DEGRADED_EXPECTED_HOOKS = "expected-hooks:unknown"

_WHITESPACE = re.compile(r"\s+")


def epoch_of(stamp):
    """An ISO-8601 Z ingest stamp to epoch seconds, or None.

    Only ever applied to the daemon's own ``at`` / ``timestamp`` values. The
    session log's ``[HH:MM:SS]`` stamps never reach this function -- that is
    FR-58, and it is enforced by no caller passing them.
    """
    if stamp is None:
        return None
    if isinstance(stamp, (int, float)):
        return float(stamp)
    try:
        parsed = datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=timezone.utc).timestamp()


def finding_id(kind, classification, subject):
    """Deterministic hash of ``(kind, classification, subject)``.

    Stability across broadcasts is the whole requirement: a raise and its later
    retraction MUST carry the same id, or the client renders two findings
    instead of one finding that resolved (FR-59).
    """
    digest = hashlib.sha256(
        ("%s|%s|%s" % (kind, classification, subject)).encode("utf-8")
    )
    return digest.hexdigest()[:16]


def make_finding(
    kind,
    classification,
    subject,
    severity,
    workflow_key=None,
    phase_id=None,
    observed=None,
    self_reported=None,
    timestamp=None,
    evidence="",
    retracted=False,
):
    """The data-model.md >2.10 shape. Both FR-21 sides are ALWAYS present.

    ``observed`` and ``self_reported`` are set unconditionally, including to
    ``None``. A missing key would let a renderer show one side and quietly omit
    the other, which is the exact reconciliation FR-21 forbids.
    """
    return {
        "finding_id": finding_id(kind, classification, subject),
        "kind": kind,
        "classification": classification,
        "subject": subject,
        "severity": severity,
        "workflow_key": workflow_key,
        "phase_id": phase_id,
        "observed": observed,
        "self_reported": self_reported,
        "timestamp": timestamp,
        "evidence": evidence,
        "retracted": bool(retracted),
        # FR-24, carried on the wire rather than assumed by the reader.
        "advisory": True,
    }


def _normalize(text):
    return _WHITESPACE.sub(" ", (text or "")).strip().lower()


def _text_match(left, right):
    left, right = _normalize(left), _normalize(right)
    if not left or not right:
        return False
    return left == right or left in right or right in left


def paired(dispatch, block, window_s=RECONCILE_WINDOW_S):
    """Does ``block`` reconcile ``dispatch``? FR-22's two-sided window.

    ``abs()`` is the two-sided part and is not an implementation detail: the
    SKILLs write the block first, so a one-directional comparison would classify
    every correctly-logged dispatch in the repository as a logging bug.
    """
    if dispatch.get("workflow_key") != block.get("workflow_key"):
        return False
    left, right = dispatch.get("observed_at"), block.get("observed_at")
    if left is None or right is None:
        return False
    if abs(float(right) - float(left)) > float(window_s):
        return False
    if dispatch.get("phase_id") and dispatch.get("phase_id") == block.get("phase_id"):
        return True
    return _text_match(dispatch.get("description"), block.get("description"))


def dispatches_from_workflow(workflow):
    """The FR-11 signal-2 events of a resolved workflow, as pairing candidates."""
    rows = []
    for signal in workflow.get("signals") or []:
        if signal.get("provenance") != P.PROV_LIVE_TASK_EVENT:
            continue
        rows.append(
            {
                "id": signal.get("evidence"),
                "workflow_key": workflow.get("key"),
                "phase_id": signal.get("phase_id"),
                "observed_at": epoch_of(signal.get("at")),
                "description": signal.get("text"),
                "timestamp": signal.get("at"),
                "evidence": signal.get("evidence"),
            }
        )
    return rows


def blocks_from_workflow(workflow):
    """The FR-11 signal-1 log blocks of a resolved workflow."""
    rows = []
    for signal in workflow.get("signals") or []:
        if signal.get("provenance") != P.PROV_SUBAGENT_BLOCK:
            continue
        rows.append(
            {
                "id": signal.get("evidence"),
                "workflow_key": workflow.get("key"),
                "phase_id": signal.get("phase_id"),
                "observed_at": epoch_of(signal.get("at")),
                "description": signal.get("text"),
                "timestamp": signal.get("at"),
                "evidence": signal.get("evidence"),
            }
        )
    return rows


def skill_logging_bug_findings(
    dispatches, blocks, now=None, window_s=RECONCILE_WINDOW_S, raised=None
):
    """FR-22(a) / T035, with FR-59 retraction / T041.

    ``raised`` is the set of ``finding_id``s the daemon has already broadcast.
    It is what makes retraction expressible in a pure snapshot function:

    * dispatch with no matching block -- RAISE (``retracted: False``, ``warn``);
    * dispatch whose block arrived late, and which WAS raised -- re-emit the
      whole finding ``retracted: True`` at a settled ``info``;
    * dispatch whose block was there all along -- emit nothing. Nothing ever
      diverged, so there is nothing to resolve.

    The third case is why ``raised`` is not optional in spirit: without it every
    correctly-logged dispatch in the repository would render as a settled
    finding, and a panel full of resolved non-problems is as useless as a panel
    full of false ones.
    """
    raised = set(raised or ())
    findings = []
    for dispatch in dispatches or []:
        subject = dispatch.get("id") or dispatch.get("description") or ""
        ident = finding_id(KIND_DIVERGENCE, CLASS_SKILL_LOGGING_BUG, subject)
        match = None
        for block in blocks or []:
            if paired(dispatch, block, window_s):
                match = block
                break
        if match is not None and ident not in raised:
            continue
        window_open = True
        moment = epoch_of(now)
        if moment is not None and dispatch.get("observed_at") is not None:
            window_open = (moment - float(dispatch["observed_at"])) <= float(window_s)
        if match is not None:
            evidence = (
                "reconciled by %s inside the %ds two-sided window"
                % (match.get("evidence") or "a late `Subagent invoked:` block", window_s)
            )
        else:
            evidence = "no `Subagent invoked:` block within %ds of %s (window %s)" % (
                window_s,
                dispatch.get("evidence") or subject,
                "still open" if window_open else "elapsed",
            )
        findings.append(
            make_finding(
                KIND_DIVERGENCE,
                CLASS_SKILL_LOGGING_BUG,
                subject,
                SEVERITY_INFO if match is not None else SEVERITY_WARN,
                workflow_key=dispatch.get("workflow_key"),
                phase_id=dispatch.get("phase_id"),
                observed=dispatch.get("evidence") or subject,
                self_reported=match.get("evidence") if match else None,
                timestamp=dispatch.get("timestamp"),
                evidence=evidence,
                retracted=match is not None,
            )
        )
    return findings


def undesigned_path_findings(artifacts_seen, workflows):
    """FR-22(b) / T036. An artifact with no preceding dispatch or skill event.

    "Preceding" is decided on the ingest ``order`` the resolver already
    assigned, never on a parsed stamp. An artifact observed with an empty
    attributed stream in front of it is a path through the workflow nobody
    designed -- most often a file written by hand while a workflow was open.
    """
    by_key = {workflow.get("key"): workflow for workflow in workflows or []}
    findings = []
    for artifact in artifacts_seen or []:
        workflow = by_key.get(artifact.get("workflow_key")) or {}
        order = artifact.get("order")
        preceding = [
            signal
            for signal in workflow.get("signals") or []
            if signal.get("provenance")
            in (P.PROV_SUBAGENT_BLOCK, P.PROV_LIVE_TASK_EVENT, P.PROV_SKILL_EVENT)
            and (order is None or signal.get("order") <= order)
        ]
        if preceding:
            continue
        subject = artifact.get("path") or artifact.get("artifact") or ""
        findings.append(
            make_finding(
                KIND_DIVERGENCE,
                CLASS_UNDESIGNED_PATH,
                subject,
                SEVERITY_WARN,
                workflow_key=artifact.get("workflow_key"),
                phase_id=artifact.get("phase_id"),
                observed=subject,
                self_reported=None,
                timestamp=artifact.get("at"),
                evidence="%s appeared with no dispatch or skill-invocation event "
                "before it in the attributed stream" % subject,
            )
        )
    return findings


def marker_contradiction_findings(workflows, phase_map):
    """FR-22(c) / T036. A cross-chain signal at a phase with NO declared handoff.

    **The normal two-marker ``smith-new`` -> ``smith-build`` nest must not fire
    this** (binding constraint 10). Two guards make that structural rather than
    incidental: a workflow that has a real child marker for that type is a nest,
    and a chain that declares a ``handoff`` to that type is a designed path. The
    ``handoff`` key in phases.json exists for exactly this -- without it every
    single ``/smith-new`` run would emit a false contradiction.
    """
    findings = []
    for workflow in workflows or []:
        own = workflow.get("workflow_type")
        declared = set()
        for phase in P.phases_for(phase_map, own):
            declared.update(P.handoff_targets(phase))
        child_types = set()
        for other in workflows or []:
            if other.get("key") in (workflow.get("child_keys") or []):
                child_types.add(other.get("workflow_type"))
        seen = set()
        for cross in workflow.get("cross_chain") or []:
            target = cross.get("workflow")
            if target in declared or target in child_types or target in seen:
                continue
            seen.add(target)
            subject = "%s|%s" % (workflow.get("key"), target)
            findings.append(
                make_finding(
                    KIND_DIVERGENCE,
                    CLASS_MARKER_CONTRADICTION,
                    subject,
                    SEVERITY_WARN,
                    workflow_key=workflow.get("key"),
                    phase_id=workflow.get("current_phase_id"),
                    observed=cross.get("evidence"),
                    self_reported="marker declares workflow: %s" % own,
                    timestamp=cross.get("at"),
                    evidence="a %s signal was attributed to a %s workflow whose "
                    "current phase declares no handoff to it" % (target, own),
                )
            )
    return findings


# `claude agents --json` status vocabulary. Anything outside both sets is
# UNRECOGNIZED and produces no finding: claiming a disagreement about a value
# whose meaning is unknown would be the same guess FR-20 forbids elsewhere.
WAITING_STATUSES = frozenset(
    {"waiting", "waiting_for_input", "needs_input", "blocked", "paused"}
)
ACTIVE_STATUSES = frozenset({"idle", "busy", "running", "active", "working"})


def _status_implies_waiting(status):
    if status is None:
        return None
    text = str(status).strip().lower()
    if text in WAITING_STATUSES:
        return True
    if text in ACTIVE_STATUSES:
        return False
    return None


def permission_disagreement_findings(sessions):
    """FR-57 / T040. Exactly one finding per DISAGREEING session, zero otherwise.

    ``status`` is absent on 17 of 23 observed ``claude agents --json`` records.
    **Absence of corroboration is not disagreement**, so a record with no
    ``status`` produces nothing at all -- it must not blank the indicator and it
    must not manufacture a finding.

    The hook-derived value stays the one DISPLAYED (FR-21); the polled value
    sits beside it as ``self_reported``. ``waitingFor``, ``state`` and ``id``
    do not exist in the real records and are never read.
    """
    out = []
    for session in sessions or []:
        status = session.get("status")
        if status is None:
            continue
        implied = _status_implies_waiting(status)
        if implied is None:
            continue
        permission = session.get("permission") or {}
        waiting = bool(permission.get("waiting"))
        if implied == waiting:
            continue
        subject = session.get("session_id") or ""
        out.append(
            make_finding(
                KIND_DIVERGENCE,
                CLASS_PERMISSION_DISAGREEMENT,
                subject,
                SEVERITY_WARN,
                workflow_key=session.get("workflow_key"),
                observed="events say %s (%s)"
                % (
                    "waiting on permission" if waiting else "not waiting",
                    permission.get("evidence") or "PermissionRequest/Denied stream",
                ),
                self_reported="claude agents --json status: %s" % status,
                timestamp=session.get("timestamp"),
                evidence="session %s: hook-derived permission state disagrees with "
                "the polled status" % subject,
            )
        )
    return out


def derive_findings(
    workflows=(),
    phase_map=None,
    now=None,
    artifacts_seen=(),
    sessions=(),
    wired=None,
    fired_hooks=(),
    tools_used=None,
    shipped=None,
    settings_error=None,
    raised=None,
    ended_keys=(),
    window_s=RECONCILE_WINDOW_S,
):
    """Every finding for one project, plus the notices the UI must show.

    Deferred import of ``absence`` (the same pattern ``resolver.resolve_project``
    uses for ``attribution``) because ``absence`` imports this module for the
    ``Finding`` shape; importing it at module level would make the cycle
    import-order dependent.

    Returns ``{"findings", "notices", "absence_enabled", "degraded"}``.
    ``absence_enabled`` is False exactly when the installed settings could not
    be read, and ``degraded`` then carries FR-60's ``expected-hooks:unknown``
    token for the UI to render -- never a silent downgrade.
    """
    import absence as A

    phase_map = phase_map if phase_map is not None else P.load_phase_map()
    ended = set(ended_keys or ())
    out = []
    notices = []
    degraded = []

    for workflow in workflows or []:
        out.extend(
            skill_logging_bug_findings(
                dispatches_from_workflow(workflow),
                blocks_from_workflow(workflow),
                now=now,
                window_s=window_s,
                raised=raised,
            )
        )
        out.extend(
            A.phase_absence_findings(workflow, ended=workflow.get("key") in ended)
        )

    out.extend(undesigned_path_findings(artifacts_seen, workflows))
    out.extend(marker_contradiction_findings(workflows, phase_map))
    out.extend(permission_disagreement_findings(sessions))
    out.extend(A.shipped_not_wired_findings(shipped, wired, timestamp=now))

    expected = A.expected_hook_set(wired, tools_used=tools_used)
    if expected is None:
        degraded.append(DEGRADED_EXPECTED_HOOKS)
        notices.append(
            "Absence detection is OFF: %s. Hook expectation is never guessed."
            % (settings_error or "the installed ~/.claude/settings.json is unreadable")
        )
    else:
        out.extend(
            A.hook_never_fired_findings(expected, fired_hooks, timestamp=now)
        )

    if shipped is None:
        notices.append(
            "No installer-staged shipped-hook manifest under ~/.smith/activity/; "
            "shipped-but-not-wired detection is unavailable."
        )

    return {
        "findings": out,
        "notices": notices,
        "absence_enabled": expected is not None,
        "degraded": degraded,
    }
