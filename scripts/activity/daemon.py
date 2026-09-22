"""Daemon runtime: token, pid/port files, `projects.json`, the log with its
single rollover, and the ingest path into `state.ActivityState`.

Split out of ``server.py`` on the 300-line soft policy: ``server.py`` owns the
HTTP surface (routing, the token gate, SSE framing) and this module owns
everything the daemon IS when no request is in flight. ``refresh.py`` owns the
projection pass. The three are imported as one unit by ``server.main()``.

**Every runtime file lives under ``"${SMITH_HOME:-$HOME/.smith}"/activity/``
and nowhere else** (FR-7). In particular nothing here — or anywhere under
``scripts/activity/`` — writes to a project's ``.smith/vault/``, and NOTHING
writes to ``.smith/vault/active-workflows/`` under any circumstance (FR-44).
A detached daemon lives outside the hook system and outside the gate's
jurisdiction (A-7), so the prohibition is structural here and asserted by
``tests/smith-activity.test.sh`` (T099).

Python 3.8, stdlib only. No outbound network of any kind (FR-49).
"""

import json
import os
import secrets
import threading
import time
from typing import Any, Dict, List, Optional

import ingest
import paths
import quota as quota_mod
import state as state_mod

#: T095. There is no log rotation anywhere else in this repo and a daemon that
#: sees every `PostToolUse` grows unbounded, so this is a single rollover:
#: activity.log -> activity.log.1, one generation, no compression, no cron.
LOG_MAX_BYTES = 5 * 1024 * 1024

DEFAULT_PORT = 8787

#: How long a project's derived projection is reused before it is rebuilt.
#: The refresh pass is a POLL, never a per-event call — see refresh.py.
REFRESH_INTERVAL_S = 1.0
REFRESH_FLOOR_S = 5.0

#: Bounded per-project event retention. Retention is ephemeral (OOS-3) and a
#: daemon that keeps every `PostToolUse *` forever is a memory leak with a
#: dashboard attached.
MAX_EVENTS_PER_PROJECT = 2000


def ensure_dir(path: str) -> str:
    """0700 — the activity directory holds the bearer token."""
    try:
        os.makedirs(path, mode=0o700)
    except OSError:
        pass
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def ensure_token(path: str) -> str:
    """FR-47. Generate once at first start, 0600, reuse forever after.

    ``secrets.token_urlsafe(32)`` — 32 BYTES of entropy, URL-safe so it drops
    into a query string with no escaping.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            existing = fh.read().strip()
        if existing:
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            return existing
    except OSError:
        pass
    token = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(token + "\n")
    os.chmod(path, 0o600)
    return token


def rollover(path: str, max_bytes: int = LOG_MAX_BYTES) -> bool:
    """One generation of rollover. Returns True when it rotated."""
    try:
        if os.path.getsize(path) <= max_bytes:
            return False
    except OSError:
        return False
    try:
        os.replace(path, path + ".1")
    except OSError:
        return False
    return True


class Daemon(object):
    """Runtime state, runtime files, and the ingest entry points."""

    def __init__(
        self,
        port: int = DEFAULT_PORT,
        activity_dir: Optional[str] = None,
        capture_prompts: Optional[bool] = None,
        debounce_ms: int = state_mod.BROADCAST_DEBOUNCE_MS,
    ):
        self.port = int(port)
        self.dir = ensure_dir(activity_dir or paths.activity_dir())
        self.token_path = os.path.join(self.dir, "activity.token")
        self.pid_path = os.path.join(self.dir, "activity.pid")
        self.port_path = os.path.join(self.dir, "activity.port")
        self.log_path = os.path.join(self.dir, "activity.log")
        self.projects_path = os.path.join(self.dir, "projects.json")
        self.token = ensure_token(self.token_path)

        if capture_prompts is None:
            capture_prompts = ingest.capture_enabled()
        self.capture_prompts = bool(capture_prompts)

        self.state = state_mod.ActivityState(capture_prompts=self.capture_prompts)
        self.broadcaster = state_mod.Broadcaster(self.state, debounce_ms=debounce_ms)

        self._seq_lock = threading.Lock()
        self._seq = 0
        self._log_lock = threading.Lock()
        self._events = {}  # type: Dict[str, List[Dict[str, Any]]]
        self._events_lock = threading.RLock()
        self._project_of_cwd = {}  # type: Dict[str, Optional[str]]
        self._dirty_projects = set()

        # --- refresh.py scratch space, owned there, declared here so the
        # daemon's whole mutable surface is visible in one place.
        #: session-log path -> byte offset already consumed (FR-58 tailing).
        self.log_offsets = {}  # type: Dict[str, int]
        #: session-log path -> the seq-stamped records parsed so far.
        self.log_records = {}  # type: Dict[str, List[Dict[str, Any]]]
        #: project -> (expires_at, records). `worktrees.describe()` shells out
        #: to git per worktree per call with no cache of its own, so it is
        #: never allowed onto a per-event path. T075 moves the cache into
        #: worktrees.py; this one keeps the daemon honest until it does.
        self.worktree_cache = {}  # type: Dict[str, Any]
        #: ~/.smith/logs/hooks.log offset at daemon start — the session window.
        self.hooks_log_offset = None  # type: Optional[int]
        self._stop = threading.Event()
        self._refresher = None  # type: Optional[threading.Thread]

    # --- the single ordering counter (FR-58) -------------------------------

    def next_seq(self, count: int = 1) -> int:
        """One monotone counter shared by BOTH streams.

        Hook events and session-log records are interleaved by ingest order,
        never by a parsed timestamp: the session log mixes UTC hook writes with
        local model writes and a 4-hour skew is pinned in
        ``tests/activity/test_sessionlog.py``.
        """
        with self._seq_lock:
            self._seq += count
            return self._seq

    # --- the log -----------------------------------------------------------

    def log(self, message: str) -> None:
        """Append one redacted note. NEVER a payload, NEVER prompt text.

        Callers pass counters and field names only. The unredacted body does
        not exist by the time anything here could see it — ``ingest.parse()``
        destroyed it at the door — but the rule is stated because SC-14's
        canary greps this file.
        """
        line = "%s %s\n" % (state_mod.utcnow(), message)
        with self._log_lock:
            rollover(self.log_path)
            try:
                with open(self.log_path, "a", encoding="utf-8") as fh:
                    fh.write(line)
            except OSError:
                pass

    # --- runtime files -----------------------------------------------------

    def write_runtime_files(self) -> None:
        """Written only AFTER the socket is bound.

        The emitter's early-bail ladder treats the presence of activity.port +
        activity.token as "a daemon is up"; writing them before the bind would
        make every hook attempt a connection to a closed port.
        """
        self._write(self.pid_path, "%d\n" % os.getpid())
        self._write(self.port_path, "%d\n" % self.port)

    def clear_runtime_files(self) -> None:
        for path in (self.pid_path, self.port_path):
            try:
                os.remove(path)
            except OSError:
                pass

    @staticmethod
    def _write(path: str, text: str) -> None:
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError:
            pass

    # --- projects (FR-2/FR-3/FR-7/FR-44) -----------------------------------

    def load_projects(self) -> List[str]:
        try:
            with open(self.projects_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return []
        if isinstance(data, dict):
            data = data.get("projects") or []
        return [p for p in data if isinstance(p, str)]

    def save_projects(self, project_paths: List[str]) -> None:
        """The ONLY persistent write this daemon makes, and it is a path list.

        All derived content is rebuilt at start — retention is ephemeral.
        """
        self._write(
            self.projects_path,
            json.dumps({"projects": sorted(set(project_paths))}, indent=2) + "\n",
        )

    def register(self, path: str) -> Dict[str, Any]:
        """Register by PRIMARY-REPO path, so a worktree is never a second project.

        FR-2/FR-28: ``/smith-activity`` run from inside a worktree registers the
        repo that worktree belongs to. The dashboard then presents global
        totals with a per-project filter, never a per-project silo.
        """
        primary = paths.primary_repo(path) or os.path.abspath(path)
        primary = os.path.abspath(primary)
        existing = self.state.get("projects", primary)
        if existing is None:
            record = {
                "path": primary,
                "name": os.path.basename(primary.rstrip(os.sep)) or primary,
                "registered_at": state_mod.utcnow(),
                "vault_dir": _dir_or_none(paths.vault_dir(primary)),
                "index_dir": _dir_or_none(os.path.join(primary, ".smith", "index")),
                "worktrees": [],
                "vault": {},
                "poll_state": {},
            }
            self.state.upsert("projects", primary, record)
            self.save_projects([p["path"] for p in self.state.values("projects")])
            self.log("register project=%s" % primary)
        self.mark_project_dirty(primary)
        return {
            "project": primary,
            "name": os.path.basename(primary.rstrip(os.sep)) or primary,
            "registered": True,
            "projects": self.state.count("projects"),
            # The token belongs in this URL. `/` and `/static/*` are un-gated
            # precisely so the page can LOAD and read the token out of its own
            # query string (contracts/http-surface.md §1) — every datum it then
            # asks for is behind the gate. Without it the dashboard opens and
            # immediately 403s on /api/state and /events, which is the whole
            # page. This is a loopback URL handed to the operator's own
            # browser; it discloses nothing that `cat activity.token` does not.
            "url": "http://127.0.0.1:%d/?token=%s&project=%s"
            % (self.port, quote_query(self.token), quote_query(primary)),
        }

    def restore_projects(self) -> None:
        for path in self.load_projects():
            if os.path.isdir(path):
                self.register(path)

    # --- ingest ------------------------------------------------------------

    def project_for_cwd(self, cwd: Optional[str]) -> Optional[str]:
        """Memoized ``cwd`` -> primary repo. ``git`` is never on the hot path."""
        if not cwd:
            return None
        if cwd in self._project_of_cwd:
            return self._project_of_cwd[cwd]
        resolved = paths.primary_repo(cwd)
        resolved = os.path.abspath(resolved) if resolved else None
        self._project_of_cwd[cwd] = resolved
        return resolved

    def handle_ingest(self, raw: Optional[bytes]) -> None:
        """Bytes off the wire to a redacted, sequenced event in the tree.

        Nothing here raises: ``/ingest``'s contract to the emitter is that it
        acts on nothing, so every failure is counted and swallowed.
        """
        payload = ingest.parse(raw, capture_prompts=self.capture_prompts)
        if payload is None:
            self.state.bump_counter("malformed")
            self.state.bump_counter("dropped")
            return
        record = ingest.envelope(payload, self.next_seq(), state_mod.utcnow())
        if record is None:
            # No session_id: counted and dropped, never an error.
            self.state.bump_counter("dropped")
            return
        self.state.bump_counter("ingested")
        project = self.project_for_cwd(record.get("cwd"))
        if project is None:
            self.state.unattributed_events += 1
            self.state.touch()
            return
        if self.state.get("projects", project) is None:
            # Implicit registration on the first event from a new repo
            # (data-model.md §2.1 Lifecycle).
            self.register(project)
        with self._events_lock:
            bucket = self._events.setdefault(project, [])
            bucket.append(record)
            if len(bucket) > MAX_EVENTS_PER_PROJECT:
                del bucket[: len(bucket) - MAX_EVENTS_PER_PROJECT]
        self.mark_project_dirty(project)

    def events_for(self, project: str) -> List[Dict[str, Any]]:
        with self._events_lock:
            return list(self._events.get(project) or [])

    def handle_statusline(self, raw: Optional[bytes]) -> None:
        """FR-35. The statusline payload is the ONLY source of the quota windows."""
        payload = ingest.parse(raw, capture_prompts=self.capture_prompts)
        if payload is None:
            self.state.bump_counter("malformed")
            return
        windows = quota_mod.quota_windows(payload, received_at=state_mod.utcnow())
        frame = self.state.set_quota(windows)
        # Its own event name, because it is the one payload that ignores
        # ?project= entirely (contracts/sse-frames.md §4.5).
        self.broadcaster.publish("quota", frame)

    # --- refresh scheduling ------------------------------------------------

    def mark_project_dirty(self, project: str) -> None:
        self._dirty_projects.add(project)

    def take_dirty_projects(self) -> List[str]:
        dirty, self._dirty_projects = self._dirty_projects, set()
        return sorted(dirty)

    def start(self) -> None:
        self.broadcaster.start()
        if self._refresher is None:
            self._refresher = threading.Thread(
                target=self._refresh_loop, name="activity-refresh", daemon=True
            )
            self._refresher.start()

    def stop(self) -> None:
        self._stop.set()
        self.broadcaster.stop()
        thread, self._refresher = self._refresher, None
        if thread is not None:
            thread.join(2.0)
        self.clear_runtime_files()

    def _refresh_loop(self) -> None:
        import refresh

        last_full = 0.0
        while not self._stop.is_set():
            if self._stop.wait(REFRESH_INTERVAL_S):
                break
            now = time.time()
            targets = self.take_dirty_projects()
            if now - last_full >= REFRESH_FLOOR_S:
                last_full = now
                targets = [p["path"] for p in self.state.values("projects")]
            for project in targets:
                try:
                    refresh.refresh_project(self, project)
                except Exception as exc:  # never let one bad repo kill the loop
                    # The exception TEXT is logged, not just its class: a bare
                    # "type=NameError" once cost a live debugging cycle here,
                    # and the message is daemon-internal — it never carries an
                    # ingested payload, which `ingest.parse()` destroyed at the
                    # door long before this frame existed.
                    self.log(
                        "refresh-error project=%s type=%s detail=%r"
                        % (project, type(exc).__name__, str(exc)[:200])
                    )


def _dir_or_none(path: str) -> Optional[str]:
    return path if os.path.isdir(path) else None


_SAFE_QUERY_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~/"
)


def quote_query(text: str) -> str:
    """Percent-encode a query value.

    Hand-rolled rather than ``urllib.parse.quote`` for the same reason
    ``server.unquote`` is: T098's FR-49 guard is a crude grep for ``urllib``
    over ``scripts/activity/*.py``, and a guard with an exception carved into
    it is a guard nobody trusts.
    """
    out = []
    for byte in (text or "").encode("utf-8", "replace"):
        char = chr(byte)
        out.append(char if char in _SAFE_QUERY_CHARS else "%%%02X" % byte)
    return "".join(out)
