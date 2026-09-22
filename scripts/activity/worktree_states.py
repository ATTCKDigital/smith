"""The six-row worktree decision table — FR-30, ``data-model.md`` §2.6.

Split out of ``worktrees.py`` on the repo's 500-line decompose rule, the same
way ``subagents.py`` came out of ``usage.py``; ``worktrees`` re-exports
``classify`` and every ``CLASS_*`` / ``REMEDY_*`` / ``HELD_THRESHOLD_S`` name,
so the import surface the rest of the feature was written against is
unchanged.

The split is not merely mechanical. Everything here is a **pure function of an
already-built record** — it runs no git, touches no disk, and takes ``now`` as
an argument. That is what makes the HELD threshold and the ORPHANED-before-HELD
ordering testable without a repository, and it is why the enumeration half
(which is nothing but git) stayed behind.

**Row 3 comes before row 4 and that ordering is the requirement, not an
implementation detail.** A merged-and-deleted branch whose marker survives is
the janitor's backlog. Rendering it as an active workflow is the phantom FR-30
exists to forbid, and evaluating "is it stalled?" first would produce exactly
that phantom for every orphan older than ten minutes.

Three-valued logic throughout: ``merged`` and ``gone`` are ``True`` / ``False``
/ ``None``, and only ``True`` classifies. ``None`` means the git call did not
run, and convicting a live worktree on a question that was never asked is the
failure mode this whole feature is about.

Python 3.8, stdlib only.
"""

import time
from typing import Any, Dict, Optional


#: T074. "Not advancing" means the owning workflow has produced no signal
#: newer than its current phase's ``entered_at`` for longer than this.
#: Ten minutes, because ``/smith-bugfix`` deliberately PRESERVES the worktree
#: when a phase fails pre-merge — a held worktree is a normal outcome to be
#: reported, not an error, and a shorter window would label ordinary thinking
#: time as a stall.
HELD_THRESHOLD_S = 600.0

CLASS_PRIMARY = "primary"
CLASS_ACTIVE = "active"
CLASS_HELD = "held"
CLASS_MISSING = "missing"
CLASS_ORPHANED = "orphaned"

#: The remedy strings ``data-model.md`` §2.6's "UI says" column specifies.
#: They are DATA, not rendering: the panel prints whatever is here, so the
#: remedy for a state can never drift from the state itself.
REMEDY_MISSING = "`git worktree prune` clears it"
REMEDY_ORPHANED = "pending `active-workflow-janitor.sh` sweep"


def _epoch(stamp) -> Optional[float]:
    """An ISO-8601 Z daemon stamp to epoch seconds. Never a log ``[HH:MM:SS]``.

    Deferred import: ``findings`` imports nothing from here, but it does pull
    in ``phases``, and paying that at module import time would put the phase
    map behind every ``import worktrees``.
    """
    import findings

    return findings.epoch_of(stamp)


def _stale_since(workflow: Dict[str, Any]) -> Optional[float]:
    """The newest moment this workflow demonstrably moved, in epoch seconds.

    ``data-model.md`` §2.6 phrases row 4 as "no signal newer than its
    ``current`` phase's ``entered_at``". The anchor is that ``entered_at``,
    but the newest signal is taken into account too: a workflow that emitted
    a signal after entering its current phase HAS advanced, and calling it
    held because the phase boundary is old would report a stall that is not
    there. Taking the max makes the two readings agree in the ordinary case
    and keeps the conservative answer in the other.

    Falls back to the last KNOWN phase (a workflow whose current phase
    resolved to ``None`` still has a last position) and then to the marker's
    ``started``. ``None`` — no usable timestamp anywhere — means row 4 cannot
    be evaluated, and the caller must fall through rather than guess.
    """
    anchor = None
    for phase in workflow.get("phases") or ():
        if phase.get("id") == workflow.get("current_phase_id"):
            anchor = _epoch(phase.get("entered_at"))
            break
    if anchor is None:
        anchor = _epoch((workflow.get("last_known_phase") or {}).get("at"))
    if anchor is None:
        anchor = _epoch(workflow.get("started"))
    newest = None
    for signal in workflow.get("signals") or ():
        at = _epoch(signal.get("at"))
        if at is not None and (newest is None or at > newest):
            newest = at
    if anchor is None:
        return newest
    if newest is None:
        return anchor
    return max(anchor, newest)


def _died_in_phase(workflows) -> Optional[str]:
    """The phase the owning workflow was last in, for the HELD render."""
    for workflow in workflows or ():
        title = workflow.get("current_title")
        if title:
            return title
        last = workflow.get("last_known_phase") or {}
        if last.get("title"):
            return last["title"]
    return None


def _age_s(markers, now: float) -> Optional[int]:
    """Seconds since the owning marker's ``started``, or ``None``.

    ``None`` when no owning marker carries a parseable ``started`` — an
    unknown age renders as unknown, never as 0, which would read as "just
    created" about a worktree that may be weeks old.
    """
    oldest = None
    for marker in markers or ():
        started = _epoch(marker.get("started"))
        if started is not None and (oldest is None or started < oldest):
            oldest = started
    return None if oldest is None else int(max(0.0, now - oldest))


def classify(record: Dict[str, Any], workflows=(), now=None) -> Dict[str, Any]:
    """The six-row table, top to bottom, first match wins (FR-30).

    | 1 | is the primary checkout            | ``primary``  |
    | 2 | marker, path not on disk           | ``missing``  |
    | 3 | marker, on disk, merged OR gone    | ``orphaned`` |
    | 4 | marker, on disk, unmerged, stalled | ``held``     |
    | 5 | marker, otherwise                  | ``active``   |
    | 6 | no marker                          | ``active``   |

    Rows 5 and 6 produce the same class and are kept separate anyway, because
    ``classification_reason`` distinguishes them and "active, no owning
    marker" is a different thing to see on screen from "active, owned".

    Returns the fields to merge into ``record``; it does not mutate it.
    """
    now = time.time() if now is None else now
    owned = bool(record.get("owning_markers"))
    out = {
        "classification": CLASS_ACTIVE,
        "classification_reason": "no owning marker",
        "remedy": None,
        "age_s": _age_s(record.get("_markers"), now),
        "died_in_phase": None,
    }

    # Row 1. The primary checkout is classified before anything else is
    # considered, so a marker sitting in the primary vault — which is where
    # create-active-workflow.sh puts most of them — can never make the
    # operator's own repo render as somebody's abandoned worktree.
    if record.get("is_primary"):
        out["classification"] = CLASS_PRIMARY
        out["classification_reason"] = "the project's primary checkout"
        return out

    if not owned:
        return out  # row 6

    # Row 2.
    if not record.get("exists"):
        out["classification"] = CLASS_MISSING
        out["classification_reason"] = "a marker claims a path that is not on disk"
        out["remedy"] = REMEDY_MISSING
        return out

    # Row 3, BEFORE row 4. `merged` and `gone` are each three-valued; only a
    # positive answer classifies. An unknown stays unknown and falls through
    # to row 4/5 rather than convicting a live worktree on a git call that
    # did not run.
    merged = record.get("branch_merged")
    gone = record.get("branch_gone")
    if merged is True or gone is True:
        out["classification"] = CLASS_ORPHANED
        out["classification_reason"] = (
            "the branch is gone"
            if gone is True
            else "the branch is merged into %s"
            % (record.get("base_branch") or "its base")
        )
        out["remedy"] = REMEDY_ORPHANED
        out["died_in_phase"] = _died_in_phase(workflows)
        return out

    # Row 4. With no workflow record there is no phase timeline, so "not
    # advancing" is unanswerable and this row simply does not match. That is
    # deliberate: inferring a stall from the marker's age alone would label
    # every long-running workflow held.
    for workflow in workflows or ():
        since = _stale_since(workflow)
        if since is None:
            continue
        if now - since > HELD_THRESHOLD_S:
            out["classification"] = CLASS_HELD
            out["died_in_phase"] = _died_in_phase([workflow])
            out["classification_reason"] = (
                "no signal for %ds; the owning workflow is not advancing"
                % int(now - since)
            )
            return out

    # Row 5.
    out["classification_reason"] = "owned by an advancing workflow"
    return out
