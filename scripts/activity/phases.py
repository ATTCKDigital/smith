"""Phase-chain loading, title normalization and SKILL.md heading extraction.

**Pure.** The only I/O in this module is reading ``phases.json`` once and, for
the FR-16 sync check, reading the SKILL.md files it names. No git, no network,
no clock. That is what makes SC-1/SC-2 replayable against fixtures with no
daemon running (plan.md §Architecture Summary).

This module carries the phase-map DATA layer plus the FR-11 signal VOCABULARY
-- the provenance names, their priority ranks, the FR-58 ordering key and the
matcher that maps signal text to a phase. The machinery built on it lives in
four siblings, split off as this file approached the repo's 500-line decompose
threshold:

* ``stepper.py``     -- FR-11 signal builders (log, hook event, artifact)
* ``resolver.py``    -- PhaseState derivation, FR-20's honest unknown, FR-18
                        permission state, and the project pass
* ``nesting.py``     -- FR-17 parent/child, from the two real markers first
* ``attribution.py`` -- FR-14 single-assignment, ambiguity dropped not guessed

The two impure helpers they consume are ``artifacts.py`` (FR-12 disk scan) and
``hookset.py`` (FR-60/FR-61 installed settings and shipped manifest); findings
derive in ``findings.py`` and ``absence.py``. Everything except those two
readers is pure.

Python 3.8, stdlib only.
"""

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

PHASES_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "phases.json")

EM_DASH = "—"

# ---------------------------------------------------------------------------
# Title normalization — contracts/phases-json.md §3
#
# FR-16 requires extracted headings to match phases.json "exactly". Taken
# literally against the raw headings that is impossible:
# `## Phase 0: Pre-Change Exploration (Conditional)` is not the string
# `Pre-Change Exploration`. The contract is therefore the NORMALIZED form,
# applied identically to both sides before comparison.
#
# These rules live in exactly one function and the sync test imports it rather
# than reimplementing it. If normalization and comparison could drift apart,
# the sync test would be testing the wrong thing.
# ---------------------------------------------------------------------------

_EM_DASH_CLAUSE = re.compile(r"\s+" + EM_DASH + r"\s+.*$")
_WHITESPACE = re.compile(r"\s+")


def _strip_one_trailing_paren_group(text: str) -> str:
    """Rule 2: remove exactly ONE trailing parenthesized group, and only a
    trailing one. An interior ``(...)`` is content, not a qualifier.

    Scanned with a depth counter rather than matched with ``\\([^()]*\\)$`` so
    a nested group (``(a (b) c)``) is removed whole instead of being mangled.
    """
    stripped = text.rstrip()
    if not stripped.endswith(")"):
        return text
    depth = 0
    for i in range(len(stripped) - 1, -1, -1):
        ch = stripped[i]
        if ch == ")":
            depth += 1
        elif ch == "(":
            depth -= 1
            if depth == 0:
                return stripped[:i]
        # Unbalanced before reaching the start → leave the text alone.
    return text


def normalize_phase_title(raw: str) -> str:
    """Normalize a SKILL.md heading title to its ``phases.json`` form.

    The five rules of contracts/phases-json.md §3, in order:

    1. Remove all backtick characters.
    2. Remove one trailing parenthesized group and any whitespace before it.
    3. Remove a trailing ``  <rest>`` em-dash clause (U+2014, space-delimited).
    4. Collapse runs of whitespace to one space; strip.
    5. Compare case-sensitively — so nothing here changes case. A case change
       in a heading is a real edit and should fail the sync test.

    ``&``, ``.``, ``,`` and ``-`` are preserved verbatim; titles legitimately
    contain all four (``Worktree Creation & Setup``).
    """
    if raw is None:
        return ""
    text = raw.replace("`", "")  # 1
    text = _strip_one_trailing_paren_group(text)  # 2
    text = _EM_DASH_CLAUSE.sub("", text)  # 3
    text = _WHITESPACE.sub(" ", text).strip()  # 4
    return text  # 5: case untouched


def phase_sort_key(number: str) -> float:
    """``number`` is a STRING compared as a decimal.

    ``"3.5"``, ``"3.6"``, ``"3.7"``, ``"5.5"``, ``"1.5"`` and ``"6.5"`` all
    occur, and a numeric sort must treat ``3.7 < 4``. Integer parsing loses
    them silently.
    """
    try:
        return float(number)
    except (TypeError, ValueError):
        return float("inf")


# ---------------------------------------------------------------------------
# phases.json
# ---------------------------------------------------------------------------


def load_phase_map(path: Optional[str] = None) -> Dict[str, Any]:
    """Read ``phases.json``. Raises on a malformed file — a broken phase map is
    a build error, not a runtime degradation, and the sync test is what keeps
    it from shipping."""
    with open(path or PHASES_JSON, "r", encoding="utf-8") as fh:
        return json.load(fh)


def workflow_names(phase_map: Dict[str, Any]) -> List[str]:
    return list((phase_map.get("workflows") or {}).keys())


def phases_for(phase_map: Dict[str, Any], workflow: str) -> List[Dict[str, Any]]:
    """The chain for ``workflow``, or ``[]`` when it has no entry.

    An empty list is the correct answer for an unmapped workflow type: the
    resolver never invents a chain (FR-20, data-model.md §2.5).
    """
    wf = (phase_map.get("workflows") or {}).get(workflow)
    if not wf:
        return []
    return wf.get("phases") or []


def workflow_source(phase_map: Dict[str, Any], workflow: str) -> Optional[str]:
    """The repo-relative SKILL.md path this chain is kept in sync with."""
    wf = (phase_map.get("workflows") or {}).get(workflow)
    return wf.get("source") if wf else None


def handoff_targets(phase: Dict[str, Any]) -> List[str]:
    """``handoff`` is optional; absent means ``[]`` (data-model.md §3)."""
    return list(phase.get("handoff") or [])


# ---------------------------------------------------------------------------
# Heading extraction — contracts/phases-json.md §4 (FR-16 / SC-3)
# ---------------------------------------------------------------------------


def _heading_pattern(heading_level: int, heading_keyword: str) -> "re.Pattern":
    """``^#{level} *<Keyword> +<number>: <title>$``.

    Anchoring to the exact level is not optional. ``smith-finish`` uses
    ``###`` and the other four use ``##``; ``^## `` misses all nine
    ``smith-finish`` steps, and a loose ``^#{2,3}`` pulls in unrelated ``###``
    subsections from the other four. Reading the level from the data file is
    what keeps both correct.
    """
    return re.compile(
        r"^#{%d} *%s +(?P<number>[0-9]+(?:\.[0-9]+)?) *: *(?P<title>.+?)\s*$"
        % (int(heading_level), re.escape(str(heading_keyword)))
    )


def extract_headings(
    text: str, heading_level: int, heading_keyword: str
) -> List[Tuple[str, str, int]]:
    """Extract ``(number, normalized_title, line_number)`` from SKILL.md text.

    **Fence-aware.** ``skills/smith-finish/SKILL.md:174`` and ``:177`` are
    ``## Summary`` and ``## Test plan`` sitting inside a fenced bash block,
    inside a ``gh pr create --body`` heredoc. The keyword filter happens to
    exclude those two today, but fence state is tracked regardless so a future
    heredoc containing ``## Phase 9: ...`` is not picked up as a real phase.

    Titles come back normalized, so the caller compares like with like.
    """
    pattern = _heading_pattern(heading_level, heading_keyword)
    rows: List[Tuple[str, str, int]] = []
    in_fence = False
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = pattern.match(line.rstrip("\n"))
        if match:
            rows.append(
                (
                    match.group("number"),
                    normalize_phase_title(match.group("title")),
                    lineno,
                )
            )
    return rows


def extract_headings_from_file(
    source_path: str, heading_level: int, heading_keyword: str
) -> List[Tuple[str, str, int]]:
    """``extract_headings`` over a file. Propagates OSError: the sync test's
    job includes failing when a SKILL.md is moved or renamed (SC-3)."""
    with open(source_path, "r", encoding="utf-8") as fh:
        return extract_headings(fh.read(), heading_level, heading_keyword)


def workflow_heading_dialect(
    phase_map: Dict[str, Any], workflow: str
) -> Tuple[int, str]:
    """``(heading_level, heading_keyword)`` for a workflow, defaulting to the
    ``## Phase`` dialect four of the five chains use."""
    wf = (phase_map.get("workflows") or {}).get(workflow) or {}
    return int(wf.get("heading_level", 2)), str(wf.get("heading_keyword", "Phase"))


# ===========================================================================
# FR-11 signal-precedence state machine (T021-T030)
#
# Everything below is PURE: the only inputs are the phase map, marker records,
# already-parsed session-log records, already-ingested hook events and an
# already-read artifact snapshot. No file is opened, no subprocess is run, and
# `now` is a parameter. That is what makes SC-1/SC-2 replayable from fixtures
# with no daemon running.
#
# FR-58 is enforced structurally rather than by review: no function here ever
# reads `timestamp_text`. It is carried on every signal, labelled with the
# clock that wrote it, and consumed only by a renderer.
# ===========================================================================

PROV_MARKER_PHASE = "marker_phase"
PROV_SUBAGENT_BLOCK = "subagent_block"
PROV_LIVE_TASK_EVENT = "live_task_event"
PROV_SKILL_EVENT = "skill_event"
PROV_WORKFLOW_START = "workflow_start"
PROV_SUBAGENT_COMPLETION = "subagent_completion"
PROV_ARTIFACT = "artifact"
# FR-17 addition beyond data-model.md >2.5's seven values. A parent pinned
# at its handoff phase because a CHILD MARKER exists is resolved by evidence,
# not by inference, and FR-19 requires every rendered phase to name the signal
# that produced it -- leaving the pinned phase with `provenance: None` would
# render the one phase the operator is looking at as unattributed.
PROV_CHILD_MARKER = "child_marker"

# FR-11's priority order, lowest number = strongest. The marker `phase:` field
# sits at 0 and beats every inferred signal (FR-13), even though nothing writes
# one today -- which is exactly what makes OOS-1's later stamping additive.
SIGNAL_RANK = {
    PROV_MARKER_PHASE: 0,
    PROV_SUBAGENT_BLOCK: 1,
    PROV_LIVE_TASK_EVENT: 2,
    PROV_SKILL_EVENT: 3,
    PROV_WORKFLOW_START: 4,
    PROV_SUBAGENT_COMPLETION: 5,
    PROV_ARTIFACT: 6,
    # Marker-derived, so it sits with the other marker evidence at the top.
    PROV_CHILD_MARKER: 0,
}

STATE_COMPLETED = "completed"
STATE_CURRENT = "current"
STATE_REMAINING = "remaining"
STATE_SKIPPED = "skipped"

ACTIVITY_WORKING = "working"
ACTIVITY_WAITING_USER = "waiting_on_user"
ACTIVITY_WAITING_PERMISSION = "waiting_on_permission"
ACTIVITY_UNKNOWN = "unknown"

NOTE_NO_PHASE_MAP = "no phase map entry"
NOTE_PHASE_UNKNOWN = "phase unknown"

# Artifact signals are ordered BELOW every live signal so corroboration can
# never outrank an observed event. -1 puts them first in append order, which
# means the last live signal always wins `latest`; on a cold start, where they
# are the only signals, the furthest-along artifact wins because artifact
# signals are emitted in chain order.
ARTIFACT_ORDER = -1


def sequence_records(records, start=0, step=1):
    """Stamp session-log records with a monotonic ingest ``seq`` (FR-58).

    This is what the daemon's tailer does: it reads a batch in append-offset
    order and assigns each record the next ingest sequence number, the same
    counter hook events draw from. Exposed here so a fixture, a replay and the
    daemon all build the same ordered stream.

    Records are mutated in place and returned, so a caller can chain.

    ``step`` leaves gaps so a caller can interleave hook events between two
    log records without renumbering either stream.
    """
    for index, record in enumerate(records or []):
        record["seq"] = start + (index + 1) * step
    return records


def _order_of(record, index):
    """The FR-58 ordering key: ingest ``seq``, else append ``offset``.

    **Mixing sequenced and unsequenced records in one call is not supported.**
    Either the daemon has stamped every record (the live path, where the two
    streams share one counter) or nothing is stamped and a pure session-log
    replay orders correctly on byte offset alone. ``index`` is the final
    tie-break so the sort is stable and total either way.
    """
    key = record.get("seq")
    if key is None:
        key = record.get("offset")
    if key is None:
        return (1, 0, index)
    return (0, int(key), index)


# ---------------------------------------------------------------------------
# Matching signal text to a phase
# ---------------------------------------------------------------------------


def match_phase(phase_map, workflow, text):
    """The phase in ``workflow``'s chain whose ``match`` text best fits ``text``.

    Case-insensitive substring, **longest pattern wins**. Length is the
    tie-break that matters in practice: ``smith-build`` carries both
    ``"Phase 3: Testing"`` and (via its title) ``"Testing"``, and a
    description naming the former must not be resolved by the latter's shorter,
    vaguer match. Ties keep the earlier chain entry, so the result is
    deterministic.

    The phase ``title`` is tried after the explicit ``match`` list, never
    instead of it -- data-model.md >3 makes ``match`` required precisely so a
    title can stay human-readable while the patterns stay discriminating.
    """
    low = (text or "").lower()
    if not low:
        return None
    best = None
    for index, phase in enumerate(phases_for(phase_map, workflow)):
        patterns = list(phase.get("match") or [])
        title = phase.get("title")
        if title:
            patterns.append(title)
        for pattern in patterns:
            needle = (pattern or "").lower().strip()
            if needle and needle in low:
                if best is None or len(needle) > best[0]:
                    best = (len(needle), index, phase)
    return best[2] if best else None


def match_any_chain(phase_map, text, exclude=None):
    """``[(workflow, phase)]`` for every chain but ``exclude`` that matches.

    Used for two things and nothing else: FR-22(c)'s cross-chain signal test
    and FR-17's fallback nesting derivation. Both need to know that a signal
    belongs to somebody else's chain; neither may act on it without first
    checking for a declared ``handoff``.
    """
    hits = []
    for workflow in workflow_names(phase_map):
        if workflow == exclude:
            continue
        phase = match_phase(phase_map, workflow, text)
        if phase is not None:
            hits.append((workflow, phase))
    return hits


def _signal(provenance, phase, order, evidence, **extra):
    signal = {
        "provenance": provenance,
        "rank": SIGNAL_RANK[provenance],
        "phase_id": phase.get("id") if phase else None,
        "number": phase.get("number") if phase else None,
        "title": phase.get("title") if phase else None,
        "order": order,
        "terminal": False,
        "evidence": evidence,
        # Daemon-observed, reliable, ISO-8601 Z. Distinct from timestamp_text.
        "at": None,
        # FR-58: display only. Never read by anything in this module.
        "timestamp_text": None,
        "clock": None,
        "text": "",
    }
    signal.update(extra)
    return signal
