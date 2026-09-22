"""Live sessions and live subagents — FR-25/FR-26/FR-27/FR-57.

Replaces ``refresh.sessions_from_events``, which produced the ingest-derived
minimum while this module was a later task. The seam is
``sessions_for(project, events)``; ``refresh`` imports this module if it
exists and falls back if it does not.

**What `claude agents --json` actually returns, and what this module
therefore refuses to read.** On the installed v2.1.269 a record is
``{pid, cwd, kind, name, sessionId, startedAt, status?}``. Verified across 23
live records: ``waitingFor``, ``state`` and ``id`` appear in **zero** of them,
and ``status`` in only 6 of 23. Those three names appear nowhere in this file
and must not be added — not read, not defaulted, not "handled if present".
Building the panel on them is how a dashboard ends up confidently blank.

So the poll has exactly two jobs, and neither of them is deciding what a
session is doing:

1. **Liveness reconciliation** (FR-26/T080). A session that died without
   firing ``SessionEnd`` lingers in the event-derived view forever, because
   the absence of an event is not an event. The poll is the only thing that
   can notice, and the reaper is the only reason the poll is not optional.
2. **Corroboration** (FR-57/T081). Where ``status`` is present it is compared
   against the event-derived permission state and a DISAGREEMENT becomes a
   finding. Where it is absent there is nothing to compare, which is not the
   same as agreement and not the same as a problem — it emits the
   ``claude-agents-json:no-status`` degraded token and no comparison.

"Waiting on a permission prompt" is decided by the ``PermissionRequest`` /
``PermissionDenied`` hook stream and nothing else (FR-21, questions.md Q1
answer C). That is the displayed value even when the poll disagrees; the
poll's opinion rides along as ``self_reported`` inside the finding.

``branch`` comes from ``git -C <cwd> rev-parse --abbrev-ref HEAD``, debounced,
and **never** from the transcript's ``gitBranch``: that field is captured at
session start and does not follow a ``cd``, so it silently reports the wrong
branch for exactly the long-lived sessions the dashboard exists to watch.

Read-only. Nothing here opens any file under a project's ``.smith/vault/``.

Python 3.8, stdlib only.
"""

import json
import os
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional

import findings as findings_mod
import paths
import resolver
import subagents as subagents_mod
import usage as usage_mod

#: T079. The FR-26 poll interval, inside the required 5-10 s band. This is a
#: liveness check, not a data source, so the slow end of the band costs
#: nothing but a few seconds of reaper latency.
POLL_INTERVAL_S = 7.0

#: ``subprocess(timeout=)``, never a shell ``timeout``: neither ``timeout``
#: nor ``gtimeout`` exists on a stock macOS, so the TIMEOUT_BIN idiom used
#: elsewhere in this repo imposes no bound at all.
AGENTS_TIMEOUT_S = 5.0

#: Branch resolution debounce. Same reasoning as FR-31's worktree cache: a
#: session's branch is re-asked on a poll, never per SSE frame.
BRANCH_CACHE_S = 3.0

#: A session with no ingest inside this window reads as idle
#: (``data-model.md`` §2.2). ``status`` is present on only ~26% of records, so
#: this recency fallback is the common path, not the exception.
SESSION_IDLE_S = 30.0

#: ``contracts/sse-frames.md`` §4.1 tokens. ``static/ui.js`` already carries
#: the operator-facing sentence for each; they are stated, never swallowed.
DEGRADED_ABSENT = "claude-agents-json:absent"
DEGRADED_NO_STATUS = "claude-agents-json:no-status"

STATE_WAITING_PERMISSION = "waiting_permission"
STATE_WORKING = "working"
STATE_IDLE = "idle"

#: The ONLY keys read off a polled record. Named as data so the prohibition
#: above is checkable rather than merely documented.
POLLED_FIELDS = ("pid", "cwd", "kind", "name", "sessionId", "startedAt", "status")

_LOCK = threading.RLock()
_poll_cache = None  # type: Optional[Dict[str, Any]]
_branch_cache = {}  # type: Dict[str, Any]
_degraded = set()  # type: set


def reset_cache() -> None:
    """Drop the poll and branch caches. For tests and a daemon restart."""
    global _poll_cache
    with _LOCK:
        _poll_cache = None
        _branch_cache.clear()
        _degraded.clear()


def degraded_tokens() -> List[str]:
    """The FR-60 tokens this module currently wants the UI to render.

    A set rather than a raised exception because a missing ``claude`` binary
    is a normal state of the world, not an error: the sessions panel degrades
    to hook-derived data and **says so** (A-9). Silently showing the same
    panel with the reaper switched off would be the lie.
    """
    with _LOCK:
        return sorted(_degraded)


# ---------------------------------------------------------------------------
# The FR-26 poll (T079) — liveness reconciliation only
# ---------------------------------------------------------------------------


def _run_agents_json() -> Dict[str, Any]:
    """One ``claude agents --json`` invocation. Never raises."""
    try:
        proc = subprocess.run(
            ["claude", "agents", "--json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=AGENTS_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "records": [], "error": type(exc).__name__}
    if proc.returncode != 0:
        return {"available": False, "records": [], "error": "exit %d" % proc.returncode}
    try:
        data = json.loads(proc.stdout.decode("utf-8", "replace") or "[]")
    except ValueError as exc:
        return {"available": False, "records": [], "error": "unparseable: %s" % exc}
    if isinstance(data, dict):  # tolerate {"agents": [...]} without depending on it
        data = data.get("agents") or data.get("sessions") or []
    if not isinstance(data, list):
        return {"available": False, "records": [], "error": "unexpected shape"}
    return {
        "available": True,
        "records": [r for r in data if isinstance(r, dict)],
        "error": None,
    }


def poll(now: Optional[float] = None, runner=None) -> Dict[str, Any]:
    """The debounced poll. ``{available, by_session, any_status, at, error}``.

    ``available`` False means the command could not be run or understood, and
    it is the switch that DISABLES the reaper: "we could not ask" and "nothing
    is running" have the same shape and opposite meanings, and reaping on the
    first would clear the whole panel every time ``claude`` is not on PATH.
    """
    global _poll_cache
    now = time.time() if now is None else now
    with _LOCK:
        if _poll_cache is not None and now - _poll_cache["at"] < POLL_INTERVAL_S:
            return _poll_cache

    result = (runner or _run_agents_json)()
    by_session = {}  # type: Dict[str, Dict[str, Any]]
    any_status = False
    for record in result.get("records") or ():
        sid = record.get("sessionId")
        if not sid:
            continue
        kept = {k: record.get(k) for k in POLLED_FIELDS if k in record}
        if kept.get("status") is not None:
            any_status = True
        by_session[sid] = kept

    snapshot = {
        "available": bool(result.get("available")),
        "by_session": by_session,
        "any_status": any_status,
        "at": now,
        "error": result.get("error"),
    }
    with _LOCK:
        _poll_cache = snapshot
        _degraded.discard(DEGRADED_ABSENT)
        _degraded.discard(DEGRADED_NO_STATUS)
        if not snapshot["available"]:
            _degraded.add(DEGRADED_ABSENT)
        elif by_session and not any_status:
            # Only when there ARE records. An empty poll carries no status
            # because it carries nothing, which is not a capability gap.
            _degraded.add(DEGRADED_NO_STATUS)
    return snapshot


# ---------------------------------------------------------------------------
# Branch and worktree resolution (T078)
# ---------------------------------------------------------------------------


def branch_of(cwd: Optional[str], now: Optional[float] = None) -> Optional[str]:
    """The branch a session is ACTUALLY on, debounced per cwd.

    ``rev-parse --abbrev-ref HEAD`` returns the literal ``HEAD`` on a detached
    checkout; that is mapped to ``None`` rather than passed through, because a
    branch named "HEAD" does not exist and rendering one would be a lie.

    The transcript's ``gitBranch`` is deliberately not consulted anywhere.
    """
    if not cwd:
        return None
    now = time.time() if now is None else now
    with _LOCK:
        cached = _branch_cache.get(cwd)
        if cached is not None and cached[0] > now:
            return cached[1]
    value = paths.git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    if value == "HEAD" or not value:
        value = None
    with _LOCK:
        _branch_cache[cwd] = (time.time() + BRANCH_CACHE_S, value)
    return value


def worktree_of(project: str, cwd: Optional[str], trees=None) -> Optional[str]:
    """Which linked worktree (or the primary checkout) a ``cwd`` sits in.

    Matched against ``git worktree list``, deepest path first so a worktree
    nested inside another repo resolves to the inner one rather than to
    whichever entry git happened to print first.
    """
    if not cwd:
        return None
    real = os.path.realpath(cwd)
    trees = paths.list_worktrees(project) if trees is None else trees
    best = None
    for tree in trees or ():
        path = tree.get("path")
        if not path:
            continue
        candidate = os.path.realpath(path)
        if real == candidate or real.startswith(candidate + os.sep):
            if best is None or len(candidate) > len(best):
                best = candidate
    return best


# ---------------------------------------------------------------------------
# Session assembly (T078/T080/T081)
# ---------------------------------------------------------------------------


def _state_for(permission, status, last_event_at, now) -> str:
    """``data-model.md`` §2.2's three-row precedence table.

    Row 1 is hook-sourced and wins under FR-21 even when the poll disagrees —
    the disagreement becomes a finding (T081), never a silent override.
    """
    if permission.get("waiting"):
        return STATE_WAITING_PERMISSION
    text = None if status is None else str(status).strip().lower()
    if text == "busy":
        return STATE_WORKING
    if text == "idle":
        return STATE_IDLE
    last = findings_mod.epoch_of(last_event_at)
    if last is not None and now - last <= SESSION_IDLE_S:
        return STATE_WORKING
    return STATE_IDLE


def _group(project: str, events) -> Dict[str, Dict[str, Any]]:
    """Fold the hook stream into one skeleton record per session."""
    by_id = {}  # type: Dict[str, Dict[str, Any]]
    for event in events or ():
        sid = event.get("session_id")
        if not sid:
            continue
        record = by_id.get(sid)
        if record is None:
            record = by_id[sid] = {
                "session_id": sid,
                "project": project,
                "started_at": event.get("timestamp"),
                "events": [],
            }
        for field in ("cwd", "transcript_path", "permission_mode", "agent_id"):
            if event.get(field):
                record[field] = event[field]
        record["events"].append(event)
        record["last_event_at"] = event.get("timestamp")
        record["last_seq"] = event.get("seq")
    return by_id


def _started_at(polled, fallback):
    """``startedAt`` is epoch **milliseconds** in the polled record.

    Guarded rather than trusted: a value that does not convert leaves the
    event-derived stamp in place instead of producing a 1970 timestamp, which
    would sort to the top of every "oldest session" view.
    """
    raw = (polled or {}).get("startedAt")
    if raw is None:
        return fallback
    try:
        seconds = float(raw) / 1000.0
    except (TypeError, ValueError):
        return fallback
    if seconds <= 0:
        return fallback
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seconds))


def sessions_for(project: str, events, now=None, snapshot=None) -> List[Dict[str, Any]]:
    """Every LIVE session for one project (FR-25), reconciled against the poll.

    A session leaves this list by one of two doors, and they are different
    facts kept separate on purpose:

    * it fired ``SessionEnd`` — it ended, and said so;
    * the T080 reaper removed it — it stopped existing without saying so.

    The reaper only fires against a SUCCESSFUL poll taken after the session's
    last observed event. Both halves of that guard are load-bearing: a failed
    poll would otherwise empty the panel, and a poll older than the session
    would reap one that started a moment ago and simply has not been seen yet.
    """
    now = time.time() if now is None else now
    snapshot = poll(now=now) if snapshot is None else snapshot
    polled = snapshot.get("by_session") or {}
    trees = paths.list_worktrees(project)

    out = []  # type: List[Dict[str, Any]]
    for sid, skeleton in sorted(_group(project, events).items()):
        stream = skeleton.pop("events")
        if stream and stream[-1].get("hook_event_name") == "SessionEnd":
            continue

        agent = polled.get(sid)
        if snapshot.get("available") and agent is None:
            last = findings_mod.epoch_of(skeleton.get("last_event_at"))
            if last is not None and last <= snapshot.get("at", now):
                continue  # T080: died without ever firing SessionEnd

        permission = resolver.permission_state(stream)
        status = (agent or {}).get("status")
        cwd = skeleton.get("cwd")
        rollup = None
        if skeleton.get("transcript_path"):
            try:
                rollup = usage_mod.session_rollup(skeleton["transcript_path"])
            except Exception:
                rollup = None

        record = dict(skeleton)
        record.update(
            {
                "pid": (agent or {}).get("pid"),
                "name": (agent or {}).get("name"),
                "kind": (agent or {}).get("kind"),
                "started_at": _started_at(agent, skeleton.get("started_at")),
                "branch": branch_of(cwd, now=now),
                "worktree": worktree_of(project, cwd, trees=trees),
                "model": (rollup or {}).get("model"),
                "usage": rollup,
                # FR-21: the DISPLAYED permission state is the event-derived
                # one. `status` sits beside it untouched so T081's comparison
                # has both sides; findings.permission_disagreement_findings
                # reads exactly these two keys.
                "permission": permission,
                "pending_permission": permission.get("prompt_id"),
                "status": status,
                "corroborated": status is not None,
                "state": _state_for(
                    permission, status, skeleton.get("last_event_at"), now
                ),
            }
        )
        out.append(record)
    return out


# ---------------------------------------------------------------------------
# Live subagents (T082/FR-27)
# ---------------------------------------------------------------------------


def _task_dispatches(events) -> Dict[str, Dict[str, Any]]:
    """``PreToolUse`` ``Task`` events keyed by ``tool_use_id``.

    This is the corroborating SPINE: ``contracts/hook-envelope.md`` §2 calls
    ``PreToolUse`` the ground truth, and ``toolUseId`` in the sidecar is what
    makes FR-22(a) name a specific dispatch instead of a time range.
    """
    out = {}
    for event in events or ():
        if event.get("hook_event_name") != "PreToolUse":
            continue
        if event.get("tool_name") != "Task":
            continue
        key = event.get("tool_use_id")
        if key:
            out[key] = event
    return out


def _description_of(event) -> Optional[str]:
    """The dispatch description from a ``PreToolUse`` event, if it survived.

    With FR-48 prompt capture OFF — the default — ``ingest`` has already
    replaced ``tool_input`` with ``{"<redacted>": N}``, so there is no
    description to recover and the answer is ``None``. That is the honest
    answer, not a gap to paper over: the sidecar carries the real one, and
    this path exists only for the window before the sidecar appears.
    """
    payload = (event or {}).get("tool_input")
    if not isinstance(payload, dict) or "<redacted>" in payload:
        return None
    value = payload.get("description")
    return value if isinstance(value, str) and value.strip() else None


def subagents_for(project: str, events, sessions=(), now=None) -> List[Dict[str, Any]]:
    """Live subagent records, sidecar-first with a dispatch-only third tier.

    Three tiers, in the order FR-27 and ``research.md`` §Q4 establish:

    1. **The ``.meta.json`` sidecar** is primary. It carries ``agentType``,
       ``description``, ``toolUseId``, the nesting fields, and via ctime the
       start time that makes ``elapsed`` real.
    2. **The ``PreToolUse`` ``Task`` event** corroborates it on
       ``tool_use_id`` and supplies the dispatch's own ingest stamp.
    3. **A dispatch with no sidecar yet** still produces a record. Claude Code
       writes the sidecar at dispatch, but "at dispatch" and "before the next
       1 s poll" are not the same instant, and a subagent that is invisible
       for its first second is a panel that flickers. ``agent_id`` is ``None``
       there and ``description`` is ``None`` whenever prompt capture is off —
       both stated rather than invented.
    """
    now = time.time() if now is None else now
    dispatches = _task_dispatches(events)
    seen_tool_ids = set()
    out = []  # type: List[Dict[str, Any]]

    for session in sessions or ():
        sid = session.get("session_id")
        if not sid:
            continue
        for sidecar in subagents_mod.list_sidecars(project, sid):
            tool_use_id = sidecar.get("tool_use_id")
            if tool_use_id:
                seen_tool_ids.add(tool_use_id)
            dispatch = dispatches.get(tool_use_id) if tool_use_id else None
            out.append(
                {
                    "agent_id": sidecar.get("agent_id"),
                    "session_id": sid,
                    "project": project,
                    "agent_type": sidecar.get("agent_type"),
                    "description": sidecar.get("description"),
                    "tool_use_id": tool_use_id,
                    "parent_agent_id": sidecar.get("parent_agent_id"),
                    "spawn_depth": sidecar.get("spawn_depth"),
                    "request_shape": sidecar.get("request_shape"),
                    "elapsed_s": subagents_mod.elapsed_s(sidecar, now=now),
                    "source": "sidecar",
                    # The spine confirms the dispatch happened and when the
                    # daemon saw it. Its absence is itself FR-22(a) material,
                    # so it is recorded rather than quietly tolerated.
                    "dispatch_seen": dispatch is not None,
                    "dispatched_at": (dispatch or {}).get("timestamp"),
                }
            )

    for tool_use_id, dispatch in sorted(dispatches.items()):
        if tool_use_id in seen_tool_ids:
            continue
        started = findings_mod.epoch_of(dispatch.get("timestamp"))
        out.append(
            {
                "agent_id": None,
                "session_id": dispatch.get("session_id"),
                "project": project,
                "agent_type": dispatch.get("agent_type"),
                "description": _description_of(dispatch),
                "tool_use_id": tool_use_id,
                "parent_agent_id": None,
                "spawn_depth": None,
                "request_shape": None,
                "elapsed_s": None if started is None else max(0.0, now - started),
                "source": "dispatch",
                "dispatch_seen": True,
                "dispatched_at": dispatch.get("timestamp"),
            }
        )
    return out
