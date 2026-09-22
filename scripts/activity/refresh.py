"""The projection pass: markers + both streams in, one project's slice of the
state tree out.

Called on a POLL from ``daemon._refresh_loop``, never once per ingested event.
Everything expensive — ``git``, ``markers.enumerate_markers``, the session-log
tail — is behind that poll or behind a TTL cache, so a `PostToolUse *` storm
costs one dict append per event and nothing else.

Read-only with respect to every project. Nothing here opens a file under a
project's ``.smith/vault/`` for writing, and nothing anywhere under
``scripts/activity/`` touches ``.smith/vault/active-workflows/`` (FR-44).

Python 3.8, stdlib only.
"""

import os
import time
from typing import Any, Dict, List, Optional

import absence
import findings as findings_mod
import hookset
import markers as markers_mod
import phases
import resolver
import state as state_mod
import usage as usage_mod
import worktrees as worktrees_mod

#: The `worktrees.describe()` TTL. Git is never invoked per SSE frame (FR-31).
WORKTREE_CACHE_S = 3.0

#: A session with no ingest inside this window reads as idle
#: (``data-model.md`` §2.2). `claude agents --json`'s `status` is present on
#: only ~26% of records, so this recency fallback is the common path.
SESSION_IDLE_S = 30.0

MAX_LOG_RECORDS = 2000

_PHASE_MAP = None

# Seams. `sessions.py` (T078-T082) and `vault.py` (T100-T102) are later tasks;
# where they exist they own their panel, and where they do not this module
# fills the ingest-derived minimum rather than leaving the panel blank.
try:  # pragma: no cover - exercised by whichever half of the seam exists
    import sessions as sessions_mod
except ImportError:
    sessions_mod = None
try:  # pragma: no cover
    import vault as vault_mod
except ImportError:
    vault_mod = None


def phase_map() -> Dict[str, Any]:
    global _PHASE_MAP
    if _PHASE_MAP is None:
        _PHASE_MAP = phases.load_phase_map()
    return _PHASE_MAP


# ---------------------------------------------------------------------------
# Session-log tailing — one seq counter across BOTH streams (FR-58)
# ---------------------------------------------------------------------------


def tail_log(daemon, path: str) -> List[Dict[str, Any]]:
    """Consume whatever has been appended since last time, seq-stamped.

    Ordering is on the append OFFSET and the daemon's ingest counter, never on
    a parsed timestamp: the log mixes UTC hook writes with local model writes
    and a 4-hour skew is pinned in ``tests/activity/test_sessionlog.py``.

    The read is cut at the last newline so a half-written trailing line is left
    for the next pass instead of being consumed as a truncated record.
    """
    offset = daemon.log_offsets.get(path, 0)
    try:
        with open(path, "rb") as fh:
            fh.seek(offset)
            raw = fh.read()
    except OSError:
        return daemon.log_records.get(path, [])
    cut = raw.rfind(b"\n")
    if cut >= 0:
        raw = raw[: cut + 1]
        import sessionlog

        fresh = sessionlog.parse_session_log(
            raw.decode("utf-8", "replace"), base_offset=offset
        )
        daemon.log_offsets[path] = offset + cut + 1
        if fresh:
            start = daemon.next_seq(len(fresh)) - len(fresh)
            phases.sequence_records(fresh, start=start, step=1)
            bucket = daemon.log_records.setdefault(path, [])
            bucket.extend(fresh)
            if len(bucket) > MAX_LOG_RECORDS:
                del bucket[: len(bucket) - MAX_LOG_RECORDS]
    return daemon.log_records.get(path, [])


def records_for(daemon, marker_records) -> List[Dict[str, Any]]:
    """Every distinct session log the project's markers point at, merged."""
    seen = set()
    out = []  # type: List[Dict[str, Any]]
    for marker in marker_records:
        path = marker.get("session_log")
        if not path or path in seen:
            continue
        seen.add(path)
        out.extend(tail_log(daemon, path))
    out.sort(key=lambda r: (r.get("seq") or 0, r.get("offset") or 0))
    return out


# ---------------------------------------------------------------------------
# Sessions — the ingest-derived minimum (seam for T078-T082)
# ---------------------------------------------------------------------------


def sessions_from_events(project: str, events) -> List[Dict[str, Any]]:
    """`Session` records derivable from the hook stream alone.

    `pid`, `name`, `kind` and the FR-26 liveness reconciler come from
    ``claude agents --json`` and land with ``sessions.py`` (T078-T081). Until
    then the panel shows what the events prove and claims nothing else —
    stating the gap rather than filling it with a guess (A-9).
    """
    by_id = {}  # type: Dict[str, Dict[str, Any]]
    grouped = {}  # type: Dict[str, List[Dict[str, Any]]]
    for event in events:
        sid = event.get("session_id")
        if not sid:
            continue
        grouped.setdefault(sid, []).append(event)
        record = by_id.get(sid)
        if record is None:
            record = by_id[sid] = {
                "session_id": sid,
                "project": project,
                "started_at": event.get("timestamp"),
                "pid": None,
                "name": None,
                "kind": None,
                "model": None,
                "branch": None,
                "worktree": None,
                "usage": None,
            }
        for field in ("cwd", "transcript_path", "permission_mode", "agent_id"):
            if event.get(field):
                record[field] = event[field]
        record["last_event_at"] = event.get("timestamp")
        record["last_seq"] = event.get("seq")

    now = time.time()
    ended = set()
    for sid, record in by_id.items():
        stream = grouped[sid]
        if stream and stream[-1].get("hook_event_name") == "SessionEnd":
            ended.add(sid)
        permission = resolver.permission_state(stream)
        record["pending_permission"] = permission.get("pending")
        last = findings_mod.epoch_of(record.get("last_event_at"))
        if permission.get("waiting"):
            record["state"] = "waiting_permission"
        elif last is not None and now - last <= SESSION_IDLE_S:
            record["state"] = "working"
        else:
            record["state"] = "idle"
        record["status"] = None  # `claude agents --json` corroboration (T079)
        if record.get("transcript_path"):
            try:
                record["usage"] = usage_mod.session_rollup(record["transcript_path"])
            except Exception:
                record["usage"] = None
    return [r for sid, r in sorted(by_id.items()) if sid not in ended]


# ---------------------------------------------------------------------------
# Worktrees — cached, because describe() shells out to git per worktree
# ---------------------------------------------------------------------------


def worktrees_for(
    daemon, project: str, marker_records, sessions
) -> List[Dict[str, Any]]:
    cached = daemon.worktree_cache.get(project)
    now = time.time()
    if cached and cached[0] > now:
        return cached[1]
    records = worktrees_mod.describe(project, markers=marker_records, sessions=sessions)
    daemon.worktree_cache[project] = (now + WORKTREE_CACHE_S, records)
    return records


# ---------------------------------------------------------------------------
# Hook firing — the only observable "this hook ran" source (read-only)
# ---------------------------------------------------------------------------


def hooks_log_path() -> str:
    import paths

    return os.path.join(paths.smith_home(), "logs", "hooks.log")


def fired_hooks(daemon) -> Optional[set]:
    """Basenames seen in ``~/.smith/logs/hooks.log`` since the daemon started.

    ``None`` when the log cannot be read. That ``None`` DISABLES the
    ``hook_never_fired`` classification rather than substituting an empty set:
    "nothing fired" and "we cannot see what fired" have the same shape and
    opposite meanings, and manufacturing a finding out of the second is exactly
    what ``absence.expected_hook_set``'s contract forbids.
    """
    path = hooks_log_path()
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    if daemon.hooks_log_offset is None:
        daemon.hooks_log_offset = size
        return set()
    if size < daemon.hooks_log_offset:  # rotated under us
        daemon.hooks_log_offset = 0
    try:
        with open(path, "rb") as fh:
            fh.seek(daemon.hooks_log_offset)
            raw = fh.read()
    except OSError:
        return None
    seen = set(getattr(daemon, "_fired_hooks", set()))
    for line in raw.decode("utf-8", "replace").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            seen.add(parts[1] if parts[1].endswith(".sh") else parts[1] + ".sh")
    daemon.hooks_log_offset = size
    daemon._fired_hooks = seen
    return seen


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------


def refresh_project(daemon, project: str) -> None:
    """Rebuild one project's workflows, sessions, worktrees and findings."""
    pmap = phase_map()
    marker_records = markers_mod.enumerate_markers(project)
    log_records = records_for(daemon, marker_records)
    events = daemon.events_for(project)

    resolved = resolver.resolve_project(
        marker_records, records=log_records, events=events, phase_map=pmap
    )
    workflows = resolved["workflows"]

    if sessions_mod is not None:  # pragma: no cover - lands with T078
        sessions = sessions_mod.sessions_for(project, events)
    else:
        sessions = sessions_from_events(project, events)

    trees = worktrees_for(daemon, project, marker_records, sessions)

    settings, settings_error = hookset.read_installed_settings()
    wired = hookset.wired_hooks(settings) if settings is not None else None
    shipped = hookset.read_shipped_manifest()
    fired = fired_hooks(daemon)
    tools_used = {e.get("tool_name") for e in events if e.get("tool_name")}

    extra = []
    if fired is None and wired is not None:
        # Keep shipped-not-wired (it needs `wired`, not `fired`) but disable
        # hook_never_fired by handing derive_findings a `None` wired set.
        extra = list(
            absence.shipped_not_wired_findings(
                shipped, wired, timestamp=state_mod.utcnow()
            )
        )
        settings_error = (
            "%s is unreadable, so hook firing cannot be observed" % hooks_log_path()
        )
        wired = None

    derived = findings_mod.derive_findings(
        workflows=workflows,
        phase_map=pmap,
        now=state_mod.utcnow(),
        sessions=sessions,
        wired=wired,
        fired_hooks=fired or (),
        tools_used=tools_used,
        shipped=shipped,
        settings_error=settings_error,
    )
    project_findings = list(derived["findings"]) + extra

    _commit(
        daemon, project, workflows, sessions, trees, project_findings, resolved, derived
    )


def _commit(
    daemon, project, workflows, sessions, trees, project_findings, resolved, derived
):
    """Push one project's slice into the tree, removing what it no longer owns."""
    st = daemon.state
    with st.lock:
        _sync(st, "workflows", project, {w["key"]: w for w in workflows})
        _sync(st, "sessions", project, {s["session_id"]: s for s in sessions})
        _sync(st, "worktrees", project, {t["path"]: _tag(t, project) for t in trees})
        _sync(
            st,
            "findings",
            project,
            {f["finding_id"]: _tag(f, project) for f in project_findings},
        )
        st.unattributed_events = resolved.get("unattributed_events", 0)
        st.expected_hooks = (
            None if not derived["absence_enabled"] else st.expected_hooks
        )
        st.degraded = sorted(set(st.degraded) | set(derived["degraded"] or ()))
        st.notices = list(derived["notices"] or ())
        record = st.get("projects", project)
        if record is not None:
            record["worktrees"] = trees
            if vault_mod is not None:  # pragma: no cover - lands with T100
                record["vault"] = vault_mod.snapshot(project)
            st.upsert("projects", project, record)


def _tag(entity: Dict[str, Any], project: str) -> Dict[str, Any]:
    """Stamp the owning project so ``?project=`` can filter the entity."""
    if "project" not in entity:
        entity = dict(entity)
        entity["project"] = project
    return entity


def _sync(
    st, collection: str, project: str, current: Dict[str, Dict[str, Any]]
) -> None:
    """Make ``collection``'s slice for ``project`` exactly ``current``.

    Only this project's entities are considered, so one project's refresh can
    never evict another's — the dashboard is global totals with a per-project
    filter, not a per-project silo.

    An unchanged entity is NOT re-upserted: that is what keeps a poll at 1 Hz
    from marking the tree dirty every second and producing a `delta` per
    second with nothing in it.
    """
    for key, entity in st.items(collection):
        if (
            state_mod.entity_project(collection, entity) == project
            and key not in current
        ):
            st.remove(collection, key)
    for key, entity in current.items():
        if st.get(collection, key) != entity:
            st.upsert(collection, key, entity)
