"""The single in-memory ``ActivityState`` tree and the FR-41 coalescing
broadcaster (T084 / T085, ``data-model.md`` §2, ``contracts/sse-frames.md`` §2).

Two things live here and nothing else:

1. **`ActivityState`** — the whole state tree from ``data-model.md`` §2, guarded
   by ONE ``threading.RLock``. Every SSE frame and every ``/api/*`` response is
   a pure projection of it. Retention is ephemeral (OOS-3): this object IS the
   history, it lives only in memory, and a restart is a blank slate the UI
   announces rather than hides.

   The storage layer sits behind this boundary deliberately. Nothing outside
   this module touches ``_maps`` directly, so adding a retained two-tier scheme
   later is a change to ``upsert``/``snapshot`` plus a config flag, not a
   redesign of every caller.

2. **`Broadcaster`** — the FR-41 fan-out. Ingest handlers mutate the tree and
   set a dirty flag; they NEVER write to a socket. One thread wakes on the
   flag, waits a **fixed** ``BROADCAST_DEBOUNCE_MS``, bumps ``generation`` and
   fans out exactly ONE ``delta``.

   The wait is a fixed-interval leaky bucket, **not** reset-on-every-event.
   A resetting debounce under a sustained ``PostToolUse *`` storm never fires
   at all; a fixed interval bounds worst-case latency at 200 ms regardless of
   event rate and caps the stream at 5 frames/second per connection. One SSE
   frame per tool call is forbidden.

Python 3.8, stdlib only.
"""

import datetime
import queue
import threading
from typing import Any, Dict, List, Optional

# --- Protocol constants (contracts/sse-frames.md §1, §4.1) -----------------

SERVICE = "smith-activity"
PROTOCOL = 1
VERSION = "1"
RETENTION = "ephemeral"

#: FR-41's 150-250 ms band. 200 ms is also exactly the 5 frames/second ceiling.
BROADCAST_DEBOUNCE_MS = 200
MAX_FRAMES_PER_SECOND = 1000.0 / BROADCAST_DEBOUNCE_MS

#: Per-connection bound (contracts/sse-frames.md §1). A slow tab must never
#: apply back-pressure to the ingest path, so overflow drains to one `resync`.
SUBSCRIBER_QUEUE_MAX = 64

#: The keyed maps that participate in `state`/`delta` framing.
#:
#: `data-model.md` §2 names five (`projects`, `sessions`, `subagents`,
#: `workflows`, `findings`) and nests worktrees under `Project.worktrees`.
#: `contracts/sse-frames.md` §4.2/§4.3 wire-serialize `worktrees` as its own
#: top-level collection keyed by path, so it is carried here as the flattened
#: projection of that nested field rather than derived on every frame.
COLLECTIONS = (
    "projects",
    "sessions",
    "subagents",
    "workflows",
    "worktrees",
    "findings",
)

RESYNC_QUEUE_OVERFLOW = "queue-overflow"
RESYNC_DAEMON_RESTART = "daemon-restart"
RESYNC_PROTOCOL_MISMATCH = "protocol-mismatch"


def utcnow() -> str:
    """ISO-8601 Z, seconds precision — the stamp format every record uses."""
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def entity_project(collection: str, entity: Any) -> Optional[str]:
    """The primary-repo path an entity belongs to, or ``None`` for "always show".

    ``?project=`` filters `state`/`delta` but never `quota`
    (``contracts/http-surface.md`` §2). An entity that cannot name a project is
    never hidden — omitting it would silently under-report, which is the exact
    failure mode this dashboard exists to expose.
    """
    if not isinstance(entity, dict):
        return None
    if collection == "projects":
        return entity.get("path")
    for field in ("project", "primary_repo", "repo"):
        value = entity.get(field)
        if value:
            return value
    # Workflow/finding keys are "<project>|<vault_root>|<filename>".
    for field in ("key", "workflow_key"):
        value = entity.get(field)
        if isinstance(value, str) and "|" in value:
            return value.split("|", 1)[0]
    return None


def _visible(collection: str, entity: Any, project: Optional[str]) -> bool:
    if not project:
        return True
    owner = entity_project(collection, entity)
    return owner is None or owner == project


class ActivityState(object):
    """The tree. One lock, six keyed maps, and a dirty flag."""

    def __init__(self, capture_prompts: bool = False, started_at: Optional[str] = None):
        self._lock = threading.RLock()
        self._dirty = threading.Event()

        self.generation = 0
        self.started_at = started_at or utcnow()
        self.capture_prompts = bool(capture_prompts)

        # FR-60: `None` means "undeterminable", which DISABLES absence
        # detection with a visible notice. It never means "no hooks wired".
        self.expected_hooks = None  # type: Optional[Dict[str, List[str]]]
        self.shipped_hooks = None  # type: Optional[List[str]]
        self.quota = None  # type: Optional[Dict[str, Any]]

        self.unattributed_events = 0
        self.degraded = []  # type: List[str]
        self.notices = []  # type: List[str]
        self.counters = {"ingested": 0, "dropped": 0, "oversize": 0, "malformed": 0}

        self._maps = {name: {} for name in COLLECTIONS}
        self._pending = {
            name: {"upsert": set(), "remove": set()} for name in COLLECTIONS
        }

    # --- mutation (ingest side; never touches a socket) --------------------

    @property
    def lock(self):
        return self._lock

    def upsert(self, collection: str, key: str, entity: Dict[str, Any]) -> None:
        with self._lock:
            self._maps[collection][key] = entity
            pending = self._pending[collection]
            pending["upsert"].add(key)
            pending["remove"].discard(key)
        self._dirty.set()

    def remove(self, collection: str, key: str) -> None:
        with self._lock:
            existed = self._maps[collection].pop(key, None) is not None
            if not existed:
                return
            pending = self._pending[collection]
            pending["remove"].add(key)
            pending["upsert"].discard(key)
        self._dirty.set()

    def replace(self, collection: str, entities: Dict[str, Dict[str, Any]]) -> None:
        """Set a collection to exactly ``entities``, upserting and removing."""
        with self._lock:
            for key in list(self._maps[collection]):
                if key not in entities:
                    self.remove(collection, key)
            for key, entity in entities.items():
                self.upsert(collection, key, entity)

    def get(self, collection: str, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._maps[collection].get(key)

    def values(self, collection: str) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._maps[collection].values())

    def items(self, collection: str):
        """``(key, entity)`` pairs — the public read of a keyed map.

        Exists so no caller reaches into ``_maps``; the storage layer stays
        behind this boundary (OOS-3).
        """
        with self._lock:
            return list(self._maps[collection].items())

    def count(self, collection: str) -> int:
        with self._lock:
            return len(self._maps[collection])

    def bump_counter(self, name: str, delta: int = 1) -> None:
        with self._lock:
            self.counters[name] = self.counters.get(name, 0) + delta

    def touch(self) -> None:
        """Mark the tree dirty without a keyed change (scalar fields moved)."""
        self._dirty.set()

    def set_quota(self, windows: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Store the account-wide quota block and return its `quota` frame."""
        with self._lock:
            self.quota = windows
            self.generation += 1
            payload = {"generation": self.generation}
            payload.update(windows or {"available": False})
            return payload

    def bump(self) -> int:
        with self._lock:
            self.generation += 1
            return self.generation

    # --- projection (read side) -------------------------------------------

    def hello(self) -> Dict[str, Any]:
        """``contracts/sse-frames.md`` §4.1 — the first frame on every stream."""
        with self._lock:
            return {
                "service": SERVICE,
                "protocol": PROTOCOL,
                "generation": self.generation,
                "daemon_started_at": self.started_at,
                "retention": RETENTION,
                "capture_prompts": self.capture_prompts,
                "degraded": list(self.degraded),
            }

    def snapshot(self, project: Optional[str] = None) -> Dict[str, Any]:
        """The full tree (``sse-frames.md`` §4.2 == ``http-surface.md`` §5).

        One shape for both the cold-start fetch and the stream, so the page has
        exactly one renderer.
        """
        with self._lock:
            out = {
                "generation": self.generation,
                "daemon_started_at": self.started_at,
                "retention": RETENTION,
                "capture_prompts": self.capture_prompts,
                "unattributed_events": self.unattributed_events,
                "degraded": list(self.degraded),
                "notices": list(self.notices),
                # Never filtered by ?project= — the windows are account-wide.
                "quota": self.quota,
            }
            for name in COLLECTIONS:
                out[name] = [
                    entity
                    for entity in self._maps[name].values()
                    if _visible(name, entity, project)
                ]
            return out

    def drain_delta(self) -> Optional[Dict[str, Any]]:
        """Collect everything that changed since the last drain, or ``None``.

        Clears the dirty flag and bumps ``generation`` under the same lock the
        mutators take, so an event landing between the two cannot be lost: it
        re-sets the flag and is picked up by the next cycle.

        Absent collection keys mean "unchanged" — never "empty"
        (``contracts/sse-frames.md`` §4.3).
        """
        with self._lock:
            changed = {
                name: pending
                for name, pending in self._pending.items()
                if pending["upsert"] or pending["remove"]
            }
            if not changed and not self._dirty.is_set():
                return None
            self._dirty.clear()
            self.generation += 1
            payload = {
                "generation": self.generation,
                "unattributed_events": self.unattributed_events,
            }
            for name, pending in changed.items():
                source = self._maps[name]
                payload[name] = {
                    # Every upsert entry is the WHOLE entity, never a partial
                    # patch: the client replaces by key and neither side owns a
                    # merge algorithm.
                    "upsert": [
                        source[key] for key in pending["upsert"] if key in source
                    ],
                    "remove": sorted(pending["remove"]),
                }
                pending["upsert"].clear()
                pending["remove"].clear()
            return payload

    def wait_dirty(self, timeout: float) -> bool:
        return self._dirty.wait(timeout)

    def is_dirty(self) -> bool:
        return self._dirty.is_set()


def filter_delta(payload: Dict[str, Any], project: Optional[str]) -> Dict[str, Any]:
    """Apply ``?project=`` to a delta. ``remove`` keys pass through unfiltered.

    A removal names an entity that no longer exists, so its project can no
    longer be looked up. Forwarding every removal is correct: a client that
    does not hold the key ignores it.
    """
    if not project:
        return payload
    out = {}
    for key, value in payload.items():
        if key in COLLECTIONS and isinstance(value, dict):
            upsert = [e for e in value.get("upsert") or [] if _visible(key, e, project)]
            remove = list(value.get("remove") or [])
            if not upsert and not remove:
                continue
            out[key] = {"upsert": upsert, "remove": remove}
        else:
            out[key] = value
    return out


class Subscriber(object):
    """One SSE connection's bounded mailbox."""

    def __init__(
        self, project: Optional[str] = None, maxsize: int = SUBSCRIBER_QUEUE_MAX
    ):
        self.project = project or None
        self.queue = queue.Queue(maxsize=maxsize)
        self.overflows = 0

    def put(self, event: str, payload: Dict[str, Any], generation: int = 0) -> None:
        """Enqueue, or collapse a backlog into ONE ``resync``.

        A consumer that falls behind gets its queue drained and one `resync`
        rather than a replay the daemon cannot produce — retention is
        ephemeral, so there is no backlog to replay even in principle.
        """
        try:
            self.queue.put_nowait((event, payload))
            return
        except queue.Full:
            pass
        self.overflows += 1
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break
        try:
            self.queue.put_nowait(
                ("resync", {"generation": generation, "reason": RESYNC_QUEUE_OVERFLOW})
            )
        except queue.Full:  # pragma: no cover - just drained, cannot happen
            pass


class Broadcaster(object):
    """One thread, one fixed-interval leaky bucket, one ``delta`` per tick."""

    def __init__(self, state: ActivityState, debounce_ms: int = BROADCAST_DEBOUNCE_MS):
        self._state = state
        self._debounce_s = debounce_ms / 1000.0
        self._subscribers = set()
        self._subs_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None  # type: Optional[threading.Thread]

    # --- subscription ------------------------------------------------------

    def subscribe(self, project: Optional[str] = None) -> Subscriber:
        sub = Subscriber(project=project)
        with self._subs_lock:
            self._subscribers.add(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        with self._subs_lock:
            self._subscribers.discard(sub)

    @property
    def subscriber_count(self) -> int:
        with self._subs_lock:
            return len(self._subscribers)

    # --- fan-out -----------------------------------------------------------

    def publish(self, event: str, payload: Dict[str, Any]) -> None:
        generation = payload.get("generation", 0) if isinstance(payload, dict) else 0
        with self._subs_lock:
            targets = list(self._subscribers)
        for sub in targets:
            shaped = payload
            if sub.project:
                if event == "delta":
                    shaped = filter_delta(payload, sub.project)
                elif event == "state":
                    shaped = self._state.snapshot(project=sub.project)
            sub.put(event, shaped, generation=generation)

    # --- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="activity-broadcaster", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        self._state.touch()  # wake the wait_dirty() immediately
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout)

    def tick(self) -> Optional[Dict[str, Any]]:
        """One coalescing cycle, exposed so a test can drive it deterministically."""
        payload = self._state.drain_delta()
        if payload is not None:
            self.publish("delta", payload)
        return payload

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self._state.wait_dirty(timeout=0.25):
                continue
            # FIXED interval. Events arriving during this wait are folded into
            # the same frame and do NOT extend it. Changing this to a
            # reset-on-event debounce reintroduces the starvation FR-41 forbids.
            if self._stop.wait(self._debounce_s):
                break
            self.tick()
