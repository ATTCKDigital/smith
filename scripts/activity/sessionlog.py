"""Session-log parsing and the three-tier session-log discovery.

Parses the four block formats and two line formats of data-model.md §4.2.
This feature owns none of them — they are written by skill prose (best-effort,
model-authored) and by hooks (reliable) — so the parser is written against the
shapes that actually occur rather than against the spec's paraphrase.

**Two facts drive every design choice here:**

1. **Every record carries its append offset, and offset is the only ordering
   key** (FR-58). Hooks write UTC; model-authored blocks use whatever the
   model types. A 4-hour skew occurs in this repository's own log, where
   ``- `[15:18:22]` **Bash** ...`` is immediately followed by
   ``### [11:18:56] /smith-new invocation``. Parsed timestamps are carried for
   display, labelled with the clock that wrote them, and never participate in
   a sequence, window-membership or phase-advance comparison.

2. **The file is append-ordered, never section-ordered.** ``## Metrics`` is
   created once and appended to forever (metrics-tracker.sh), so later ``###``
   blocks land physically *after* it.

Python 3.8, stdlib only.
"""

import os
import re
from typing import Any, Dict, List, Optional

import paths

# Which clock wrote a record's [HH:MM:SS] stamp. Carried on every record so a
# renderer can label it; never used for ordering.
CLOCK_HOOK = "hook"  # UTC, reliable
CLOCK_MODEL = "model"  # whatever the model typed — observed 4h off

_HEADING = re.compile(r"^### \[(?P<ts>\d{2}:\d{2}:\d{2})\] (?P<rest>.*?)\s*$")
_SECTION = re.compile(r"^## (?P<rest>.*?)\s*$")
_ATTR = re.compile(r"^\*\*(?P<key>[^*:]+):\*\*\s*(?P<value>.*?)\s*$")
_METRIC_ITEM = re.compile(r"^- (?P<key>[a-z_]+): (?P<value>.+?)\s*$")
_SKILL_EVENT = re.compile(r"^/(?P<skill>smith-[A-Za-z0-9._-]+)\s*(?P<event>.*?)\s*$")

# file-change-logger.sh:45 — backticks the PATH as well as the timestamp.
_FILE_CHANGE_LINE = re.compile(
    r"^- `\[(?P<ts>\d{2}:\d{2}:\d{2})\]` \*\*(?P<tool>[^*]+)\*\* `(?P<path>[^`]*)`\s*$"
)
# metrics-tracker.sh — wraps its identifier in BARE parens and truncates a Bash
# command at 60 chars with a '…' (U+2026). Entries with total < 10 are skipped
# by that hook entirely, so their absence is expected, not a parse failure.
_METRICS_LINE = re.compile(
    r"^- `\[(?P<ts>\d{2}:\d{2}:\d{2})\]` \*\*(?P<tool>[^*]+)\*\* "
    r"in:(?P<input>\d+) out:(?P<output>\d+) total:(?P<total>\d+)"
    r"(?: \((?P<identifier>.*)\))?\s*$"
)


def _classify_heading(timestamp: str, rest: str) -> Dict[str, Any]:
    """Map a ``### [HH:MM:SS] <rest>`` heading to a record skeleton."""
    if rest.startswith("Subagent invoked:"):
        return {
            "kind": "subagent_invoked",
            "clock": CLOCK_MODEL,
            "description": rest[len("Subagent invoked:") :].strip(),
        }
    if rest == "Subagent completed":
        # The heading is the bare literal: no description, no type. Pairing an
        # invocation to its completion is positional only — which is why this
        # feature pairs on the sidecar's toolUseId instead
        # (subagent-vault-writeback.sh:13-19 documents the same limitation).
        return {"kind": "subagent_completed", "clock": CLOCK_HOOK}
    if rest.startswith("workflow-start "):
        return {
            "kind": "workflow_start",
            "clock": CLOCK_HOOK,
            "branch": rest[len("workflow-start ") :].strip(),
        }
    if rest.startswith("/smith-"):
        match = _SKILL_EVENT.match(rest)
        if match:
            return {
                "kind": "skill_event",
                "clock": CLOCK_MODEL,
                "skill": match.group("skill"),
                "event": match.group("event"),
            }
    if rest == "User prompt":
        return {"kind": "user_prompt", "clock": CLOCK_HOOK}
    return {"kind": "other", "clock": CLOCK_MODEL, "heading": rest}


def parse_session_log(text: str, base_offset: int = 0) -> List[Dict[str, Any]]:
    """Parse session-log text into offset-ordered records.

    ``base_offset`` is added to every record's ``offset`` so an incremental
    tail from a remembered byte position still yields absolute offsets.

    Records come back in file order, which IS append order, which is the only
    ordering this feature trusts.
    """
    records: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    in_metrics_list = False
    offset = base_offset

    for lineno, line in enumerate(text.splitlines(True), 1):
        stripped = line.rstrip("\n")
        line_offset = offset
        offset += len(line.encode("utf-8"))

        heading = _HEADING.match(stripped)
        if heading:
            current = _classify_heading(heading.group("ts"), heading.group("rest"))
            current.update(
                {
                    "offset": line_offset,
                    "line": lineno,
                    "timestamp_text": heading.group("ts"),
                    "attrs": {},
                    "metrics": {},
                }
            )
            records.append(current)
            in_metrics_list = False
            continue

        section = _SECTION.match(stripped)
        if section:
            # `## Metrics`, `## Started: ...`, `## Ended: ...`. A section
            # heading closes the current block but is NOT a section boundary
            # in any ordering sense — later `###` blocks follow it.
            records.append(
                {
                    "kind": "section",
                    "clock": CLOCK_HOOK,
                    "offset": line_offset,
                    "line": lineno,
                    "timestamp_text": None,
                    "heading": section.group("rest"),
                }
            )
            current = None
            in_metrics_list = False
            continue

        # The two hook-written line formats. Independent records: they occur
        # both inside and between blocks. file-change first — it is the one
        # that backticks its path, and the metrics pattern would not match it
        # anyway, but ordering the checks makes that explicit.
        file_change = _FILE_CHANGE_LINE.match(stripped)
        if file_change:
            records.append(
                {
                    "kind": "file_change",
                    "clock": CLOCK_HOOK,
                    "offset": line_offset,
                    "line": lineno,
                    "timestamp_text": file_change.group("ts"),
                    "tool": file_change.group("tool"),
                    "path": file_change.group("path"),
                }
            )
            in_metrics_list = False
            continue

        metrics_line = _METRICS_LINE.match(stripped)
        if metrics_line:
            records.append(
                {
                    "kind": "tool_metrics",
                    "clock": CLOCK_HOOK,
                    "offset": line_offset,
                    "line": lineno,
                    "timestamp_text": metrics_line.group("ts"),
                    "tool": metrics_line.group("tool"),
                    "input_chars": int(metrics_line.group("input")),
                    "output_chars": int(metrics_line.group("output")),
                    "total_chars": int(metrics_line.group("total")),
                    "identifier": metrics_line.group("identifier"),
                }
            )
            in_metrics_list = False
            continue

        if current is None:
            continue

        attr = _ATTR.match(stripped)
        if attr:
            key = attr.group("key").strip()
            current["attrs"][key] = attr.group("value")
            in_metrics_list = key == "Metrics"
            continue

        if in_metrics_list:
            item = _METRIC_ITEM.match(stripped)
            if item:
                value = item.group("value")
                current["metrics"][item.group("key")] = (
                    int(value) if value.isdigit() else value
                )
                continue
            if stripped.strip():
                in_metrics_list = False

    return records


def read_session_log(path: str, from_offset: int = 0) -> List[Dict[str, Any]]:
    """``parse_session_log`` over a file, optionally tailing from an offset.

    Returns ``[]`` rather than raising when the file is unreadable: a session
    log that has not been created yet is a normal state, not an error.
    """
    try:
        with open(path, "rb") as fh:
            if from_offset:
                fh.seek(from_offset)
            raw = fh.read()
    except OSError:
        return []
    return parse_session_log(raw.decode("utf-8", "replace"), base_offset=from_offset)


def records_of_kind(records: List[Dict[str, Any]], *kinds: str) -> List[Dict[str, Any]]:
    """Filter, preserving append order."""
    wanted = set(kinds)
    return [r for r in records if r["kind"] in wanted]


# ---------------------------------------------------------------------------
# Three-tier discovery — reused from hooks/workflow-summary.sh:84-135
#
# Totals must survive a mid-workflow session rollover that repoints
# .current-session at a fresh, markerless file, which is why the marker tier
# sits above the pointer tier.
# ---------------------------------------------------------------------------


def read_current_session(root: str) -> Optional[str]:
    """Tier (c). ``<root>/.smith/vault/.current-session``.

    Double existence check on BOTH the pointer and its target, per
    metrics-tracker.sh:23-32 — a pointer left behind by a deleted session log
    is a shape that occurs, and following it blindly yields a path to nothing.
    """
    pointer = paths.current_session_pointer(root)
    if not os.path.isfile(pointer):
        return None
    try:
        with open(pointer, "r", encoding="utf-8", errors="replace") as fh:
            target = fh.read().strip()
    except OSError:
        return None
    if not target or not os.path.isfile(target):
        return None
    return target


def resolve_session_log(
    project_root: str,
    explicit: Optional[str] = None,
    marker_records: Optional[List[Dict[str, Any]]] = None,
    current_branch: Optional[str] = None,
) -> Optional[str]:
    """Pick which session log to read. Precedence, highest first:

    (a) ``explicit`` — the caller's override. Wins even when the path does not
        exist, mirroring workflow-summary.sh:99-106: caller intent is reported
        as not-found rather than silently replaced by the wrong file.
    (b) a marker's ``session_log:``. **Markers with an EMPTY ``session_log:``
        are skipped** — that is the normal shape for a worktree marker and it
        carries no information. When exactly one marker carries a value, use
        it; when several do, prefer the one whose ``branch:`` matches
        ``current_branch``; if none match, fall through.
    (c) ``.current-session``, with the double existence check.

    ``marker_records`` are markers.enumerate_markers() output. Tier (b) reads
    the marker's LITERAL value (``record["raw"]``), never markers.py's own
    fallback-resolved ``session_log`` — using the resolved value would collapse
    tiers (b) and (c) into one and defeat the rollover protection.
    """
    if explicit:
        return explicit

    only_log: Optional[str] = None
    only_count = 0
    branch_log: Optional[str] = None
    for record in marker_records or []:
        raw_log = (record.get("raw") or {}).get("session_log") or ""
        raw_log = raw_log.strip()
        if not raw_log:
            continue
        only_count += 1
        only_log = raw_log
        if current_branch and (record.get("branch") or "") == current_branch:
            branch_log = raw_log

    if only_count == 1 and only_log:
        return only_log
    if only_count > 1 and branch_log:
        return branch_log

    return read_current_session(project_root)
