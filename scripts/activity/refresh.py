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

import time
from typing import Any, Dict, List

import absence
import findings as findings_mod
import hookset
import markers as markers_mod
import paths as paths_mod
import phases
import resolver
import state as state_mod
import usage as usage_mod
import worktrees as worktrees_mod

# Hook-firing observation, split into hookfiring.py on the 500-line decompose
# rule. Re-exported because the whole reason that module exists is the size of
# its blind spot, and a caller that only ever sees `refresh.fired_hooks`
# should still land on that docstring.
from hookfiring import (  # noqa: F401
    events_ingested,
    fired_hooks,
    hook_observability_notice,
    hooks_log_path,
)

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
# Worktrees — the debounce now lives in worktrees.py (T075)
# ---------------------------------------------------------------------------


def worktrees_for(
    daemon, project: str, marker_records, sessions, workflows
) -> List[Dict[str, Any]]:
    """One passthrough, kept as a named seam for the refresh pass to read.

    There used to be a 3 s TTL around this whole call. It has moved INSIDE
    ``worktrees.describe`` and been narrowed to the git calls alone (FR-31),
    which is strictly better in both directions: git is still never invoked
    per SSE frame, and the marker/session cross-reference is no longer frozen
    for three seconds alongside it — a marker that appeared mid-window used
    to go unrendered for no reason at all.
    """
    return worktrees_mod.describe(
        project, markers=marker_records, sessions=sessions, workflows=workflows
    )


def polled_in_project(project: str, snapshot) -> int:
    """How many live polled sessions sit inside THIS project's tree.

    Per project, never machine-wide: `claude agents --json` returns every live
    session on the box, and a notice claiming N invisible sessions that all
    belong to another repository would be the exact failure mode the notice
    exists to prevent, committed by the notice itself.

    Costs ONE `git worktree list` for the whole loop (`worktree_of` is prefix
    matching), and is called only from the blind branch -- when an event source
    IS installed the answer cannot change anything, so the hot path skips it.
    """
    if sessions_mod is None or not snapshot or not snapshot.get("available"):
        return 0
    records = list((snapshot.get("by_session") or {}).values())
    if not records:
        return 0
    trees = paths_mod.list_worktrees(project)
    return sum(
        1
        for record in records
        if sessions_mod.worktree_of(project, record.get("cwd"), trees=trees)
    )


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

    poll_snapshot = None
    if sessions_mod is not None:
        # One poll per pass, taken here and handed to sessions_for rather than
        # left for it to take, so the blindness notice below counts off the
        # same snapshot the panel was built from. Two polls could legitimately
        # disagree, and a notice naming a number the panel never saw is its own
        # small lie.
        poll_snapshot = sessions_mod.poll()
        sessions = sessions_mod.sessions_for(project, events, snapshot=poll_snapshot)
        subagent_records = sessions_mod.subagents_for(project, events, sessions)
        session_degraded = sessions_mod.degraded_tokens()
    else:
        sessions = sessions_from_events(project, events)
        subagent_records = []
        session_degraded = []

    trees = worktrees_for(daemon, project, marker_records, sessions, workflows)

    settings, settings_error = hookset.read_installed_settings()
    wired = hookset.wired_hooks(settings) if settings is not None else None
    shipped = hookset.read_shipped_manifest()
    fired = fired_hooks(daemon)
    tools_used = {e.get("tool_name") for e in events if e.get("tool_name")}

    # Two ways the daemon can be blind to hook firing, handled identically
    # because they mean the same thing to the operator: the finding would be a
    # statement about our own instrumentation wearing the costume of a
    # statement about their workflow.
    #
    #   1. ~/.smith/logs/hooks.log cannot be read.
    #   2. No event source is installed at all and nothing has arrived
    #      (FR-23 applied to the transport instead of the settings).
    #
    # In both, `hook_never_fired` is suppressed and the REASON is put on
    # screen, because "absence detection is off" with no explanation reads as a
    # missing feature rather than as a deliberate refusal to guess.
    #
    # Hoisted out of the branch below because the SESSIONS panel needs the same
    # answer, and the two must never disagree about whether an event source
    # exists. Safe to ask unconditionally: unreadable settings yield False.
    no_event_source = absence.event_source_missing(
        hookset.emitter_wired(settings), events_ingested(daemon)
    )

    blind_reason = None
    if wired is not None:
        if fired is None:
            blind_reason = (
                "%s is unreadable, so hook firing cannot be observed" % hooks_log_path()
            )
        elif no_event_source:
            blind_reason = absence.EVENT_SOURCE_MISSING_NOTICE

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
    project_findings = list(derived["findings"])

    if blind_reason is not None:
        # derive_findings runs with the REAL `wired`, and hook_never_fired is
        # dropped from its OUTPUT rather than disabled at its input.
        #
        # Nulling `wired` on the way in was the obvious move and it was wrong:
        # derive_findings uses that same argument for shipped_not_wired, where
        # `None` means "nothing is wired" rather than "we are not asking". With
        # a staged manifest in place (T118) that turned one honest silence into
        # twenty false "Smith ships this, your settings don't wire it" findings
        # about hooks the settings demonstrably DO wire -- the same
        # confidently-wrong shape as the nine warnings this whole guard exists
        # to stop, re-emitted by the guard itself.
        #
        # shipped_not_wired needs `wired`, not `fired`, so it stays VALID while
        # absence detection is off and is deliberately kept: suppressing it too
        # would hide a real, answerable question behind an unrelated blindness.
        project_findings = [
            f
            for f in project_findings
            if f.get("classification") != findings_mod.CLASS_HOOK_NEVER_FIRED
        ]
        derived = dict(
            derived,
            absence_enabled=False,
            notices=[absence.ABSENCE_OFF_NOTICE % blind_reason]
            + list(derived["notices"] or ()),
            degraded=list(derived["degraded"] or ())
            + [findings_mod.DEGRADED_EXPECTED_HOOKS],
        )

    # FR-60. `claude agents --json` being absent, or carrying no `status`, is
    # a capability gap the operator is TOLD about (static/ui.js already holds
    # the sentence for each token) rather than a panel that quietly means
    # less than it looks like it means.
    if session_degraded:
        derived = dict(
            derived,
            degraded=list(derived["degraded"] or ()) + list(session_degraded),
        )

    # The sessions panel's own blindness — the same defect as the suppressed
    # hook_never_fired warnings, one panel over: no event source means no
    # events, so no Session records, so an empty panel that reads as "nothing
    # is running" while the poll can see live sessions. Explained, never
    # filled in from the poll.
    #
    # Independent of `blind_reason` on purpose: an unreadable hooks.log blinds
    # absence detection without touching the event stream, so it must not put
    # this sentence on screen. Only a missing event SOURCE empties this panel.
    blind_sessions = 0
    if not sessions and no_event_source:
        blind_sessions = absence.sessions_blind(
            sessions, polled_in_project(project, poll_snapshot), no_event_source
        )
    if blind_sessions:
        derived = dict(
            derived,
            notices=list(derived["notices"] or ())
            + [absence.SESSIONS_BLIND_NOTICE % blind_sessions],
        )

    # Defect B disclosure. Only while absence detection is actually ON: with
    # it off, `blind_reason` above already says the stronger thing, and two
    # overlapping "we cannot see" banners read as one bug reported twice.
    if derived["absence_enabled"] and blind_reason is None:
        partial = hook_observability_notice(
            absence.expected_hook_set(wired, tools_used=tools_used)
        )
        if partial:
            derived = dict(derived, notices=list(derived["notices"] or ()) + [partial])

    _commit(
        daemon,
        project,
        workflows,
        sessions,
        subagent_records,
        trees,
        project_findings,
        resolved,
        derived,
    )


def _subagent_key(record: Dict[str, Any]) -> str:
    """A stable map key for a subagent, including the sidecar-less tier.

    A third-tier record has no ``agent_id`` yet — the sidecar has not landed —
    so it is keyed by its dispatch instead. Keying every record on
    ``agent_id`` would collapse every pending dispatch onto the single key
    ``None`` and render one row for all of them.
    """
    return record.get("agent_id") or "task:%s" % (record.get("tool_use_id") or "?")


def _commit(
    daemon,
    project,
    workflows,
    sessions,
    subagent_records,
    trees,
    project_findings,
    resolved,
    derived,
):
    """Push one project's slice into the tree, removing what it no longer owns."""
    st = daemon.state
    with st.lock:
        _sync(st, "workflows", project, {w["key"]: w for w in workflows})
        _sync(st, "sessions", project, {s["session_id"]: s for s in sessions})
        _sync(
            st,
            "subagents",
            project,
            {_subagent_key(a): _tag(a, project) for a in subagent_records},
        )
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
            before = (record.get("worktrees"), record.get("vault"))
            record["worktrees"] = trees
            if vault_mod is not None:
                # FR-38's `poll_state` is the project's own `(mtime, size)`
                # map; vault.snapshot fills it and reuses the previous
                # snapshot when the stat sweep finds nothing moved.
                record["vault"] = vault_mod.snapshot(
                    project,
                    poll_state=record.setdefault("poll_state", {}),
                    start_offset=getattr(daemon, "hooks_log_start", None),
                )
            # Only upsert when something actually moved. `_sync` takes the
            # same care for every other collection and says why: an
            # unconditional upsert at 1 Hz marks the tree dirty every second
            # and emits a `delta` per second with nothing in it.
            if before != (record.get("worktrees"), record.get("vault")):
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
