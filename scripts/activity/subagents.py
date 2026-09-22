"""Subagent dispatch sidecars — FR-27 / contracts/hook-envelope.md §3.

Split out of ``usage.py`` on the 500-line decompose rule; ``usage`` re-exports
``read_sidecar`` / ``list_sidecars`` / ``elapsed_s`` so the import surface the
rest of the feature was written against is unchanged.

**Sidecar discovery is PRIMARY, `SubagentStart` is an optimization.** Claude
Code writes ``agent-<id>.meta.json`` at dispatch, carrying every field FR-27
needs — ``agentType``, ``description``, and via ctime the start time for
elapsed — plus ``parentAgentId``/``spawnDepth`` for nesting and ``toolUseId``
for exact correlation back to the ``PreToolUse`` ``Task`` event. If the
`SubagentStart` event were withdrawn tomorrow the panel would lose up to one
poll of latency and nothing else. That is the right dependency posture for a
tool whose premise is not trusting self-reports.

Python 3.8, stdlib only.
"""

import json
import os
import time
from typing import Any, Dict, List, Optional

import paths


def read_sidecar(meta_path: str) -> Optional[Dict[str, Any]]:
    """One ``agent-<id>.meta.json``, or ``None`` if it cannot be read.

    ``toolUseId`` is the field that matters most: it is what ties this sidecar
    back to the ``PreToolUse`` ``Task`` event that created it. Positional
    pairing is the alternative, and it is wrong the moment two agents are in
    flight — ``subagent-vault-writeback.sh:13-19`` documents the same
    limitation from the other side.

    ``started`` comes from the file's ctime because nothing inside the sidecar
    records a start time, and the sidecar is written at dispatch.

    Unreadable or non-dict content returns ``None`` rather than raising: this
    directory is written by another process while it is being listed.
    """
    try:
        with open(meta_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        started = os.stat(meta_path).st_ctime
    except OSError:
        started = None
    return {
        "agent_id": paths.agent_id_from_sidecar(os.path.basename(meta_path)),
        "agent_type": data.get("agentType"),
        "description": data.get("description"),
        "parent_agent_id": data.get("parentAgentId"),
        "spawn_depth": data.get("spawnDepth"),
        "tool_use_id": data.get("toolUseId"),
        "request_shape": data.get("requestShape"),
        "started": started,
        "meta_path": meta_path,
    }


def list_sidecars(primary_repo_path: str, session_id: str) -> List[Dict[str, Any]]:
    """Every readable sidecar under one session's ``subagents/``, oldest first.

    Each record gains ``jsonl_path``, the sidechain transcript
    ``usage.subagent_rollup`` tails for FR-36. The file may not exist yet — a
    sidecar is written at dispatch and the transcript only once the agent
    produces a turn — so callers must tolerate its absence, which
    ``usage.tail_lines`` already does.
    """
    directory = paths.subagents_dir(primary_repo_path, session_id)
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return []
    found = []
    for name in names:
        if not name.endswith(".meta.json"):
            continue
        record = read_sidecar(os.path.join(directory, name))
        if record is None:
            continue
        record["jsonl_path"] = os.path.join(
            directory, name[: -len(".meta.json")] + ".jsonl"
        )
        found.append(record)
    # A sidecar with no readable ctime sorts last rather than crashing the sort
    # or silently claiming to be the oldest.
    found.sort(
        key=lambda r: (r["started"] is None, r["started"] or 0.0, r["agent_id"] or "")
    )
    return found


def elapsed_s(record: Dict[str, Any], now: Optional[float] = None) -> Optional[float]:
    """Seconds since dispatch, or ``None`` when ctime was unreadable.

    ``None`` is not zero: an agent whose start time is unknown must render as
    unknown, not as "just started".
    """
    started = (record or {}).get("started")
    if started is None:
        return None
    return max(0.0, (time.time() if now is None else now) - started)
