"""The VaultSnapshot — FR-37/FR-38, ``data-model.md`` §2.8. **READ-ONLY.**

Every function here opens files for reading and nothing else. The daemon does
not create, modify, move or delete anything under any project's
``.smith/vault/``, and nothing in this module names the active-workflow
directory except through ``paths.active_workflows_dir()`` (FR-44, enforced by
the source guard in ``tests/smith-activity.test.sh``).

**Polling, not watching.** Python 3.8's stdlib has no inotify and no
``kqueue`` wrapper worth depending on, so FR-38 is a ``stat`` sweep at ~1 s.
The sweep is cheap because it only ever calls ``os.stat`` — the expensive
part, parsing, happens only when a ``(mtime, size)`` pair actually moved.
That is the whole reason ``poll_state`` exists.

**One thing here reports less than it looks like it reports, and says so.**
Of the three FR-37 friction counters, only ``gate_denials`` is observable:
``workflow-gate.sh`` is one of just three hooks in the whole set that writes
to ``~/.smith/logs/hooks.log`` at all. ``security-guard-bash.sh``,
``security-guard-files.sh`` and ``grade-response.sh`` never write there, so
their counts are structurally 0 forever — not "no denials happened", but "we
have no way to see whether any did". A bare ``0`` next to a working counter
reads as the first and means the second, so every counter is published
alongside ``observable`` / ``unobservable`` lists derived from what the log
has ACTUALLY carried. See the note on ``refresh.fired_hooks`` for the same
limitation in its other form.

Python 3.8, stdlib only.
"""

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

import paths

# The friction counters live in vault_friction.py (the 500-line decompose
# rule), together with the reason two of the three cannot work. Re-exported
# so `import vault` stays the one import a caller needs.
from vault_friction import (  # noqa: F401
    FRICTION_HOOKS,
    friction,
    hooks_log_path,
    observable_hooks,
)

#: FR-38's ~1 s granularity. A stat sweep at this rate over a few hundred
#: paths is microseconds; the parse behind it is what is being avoided.
POLL_INTERVAL_S = 1.0

#: How many session logs the panel carries. The vault accumulates hundreds.
RECENT_SESSIONS = 5

#: Likewise for the idea bank.
RECENT_BANK = 5

_LOCK = threading.RLock()
_cache = {}  # type: Dict[str, Any]


def reset_cache() -> None:
    """Drop every cached snapshot and the observability probe."""
    # Function-local: a module-level `import vault_friction` alongside the
    # `from vault_friction import ...` below reads as unused to the
    # autoflake pass this repo runs on save, and was silently removed twice.
    import vault_friction

    with _LOCK:
        _cache.clear()
    vault_friction.reset_cache()


# ---------------------------------------------------------------------------
# Small read helpers — each returns a blank rather than raising
# ---------------------------------------------------------------------------


def _listdir(path: str) -> List[str]:
    try:
        return sorted(os.listdir(path))
    except OSError:
        return []


def _stat(path: str):
    try:
        info = os.stat(path)
    except OSError:
        return None
    return (info.st_mtime, info.st_size)


def _read(path: str, limit: int = 65536) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(limit)
    except OSError:
        return ""


def _read_tail(path: str, limit: int = 8192) -> str:
    """The LAST ``limit`` bytes. Not ``_read`` — that reads the head.

    An append-only log's newest line is at the end, and reading the head of
    an 8 KB-plus log and taking its last line yields whatever was truncated
    mid-write at byte 8192. That produced ``last_scheduler_run: "[20"`` on
    the operator's real log before this existed.
    """
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            fh.seek(max(0, size - limit))
            raw = fh.read()
    except OSError:
        return ""
    text = raw.decode("utf-8", "replace")
    # A seek into the middle of the file almost certainly lands mid-line;
    # drop that partial first line rather than reporting half a record.
    if size > limit and "\n" in text:
        text = text.split("\n", 1)[1]
    return text


def _iso(mtime: Optional[float]) -> Optional[str]:
    if mtime is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(mtime))


def _frontmatter(text: str) -> Dict[str, str]:
    """The leading ``---`` block as flat key/value pairs.

    Not a YAML parser and not pretending to be one: these files are written
    by ``printf`` in shell and read by ``grep`` everywhere else in Smith, so a
    line-oriented read matches how the format is actually produced.
    """
    out = {}  # type: Dict[str, str]
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return out
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, sep, value = line.partition(":")
        if not sep:
            continue
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


# ---------------------------------------------------------------------------
# T101 — the stat sweep
# ---------------------------------------------------------------------------


def watched_paths(project: str) -> List[str]:
    """Exactly the sources FR-38 lists, resolved for one project.

    Directories are watched as directories AND their entries individually: a
    directory's own mtime moves when a file is added or removed, but NOT when
    an existing file's contents change, so watching only the directory would
    miss every edit to an existing session log.
    """
    vault = paths.vault_dir(project)
    home = paths.smith_home()
    out = [
        paths.active_workflows_dir(project),
        os.path.join(vault, "sessions"),
        os.path.join(vault, "ledger"),
        os.path.join(vault, "queue"),
        os.path.join(vault, "queue", "history"),
        os.path.join(vault, "bank"),
        os.path.join(vault, "agents"),
        os.path.join(project, ".smith", "index"),
        os.path.join(home, "projects.json"),
        os.path.join(home, "scheduler", "scheduler.log"),
    ]
    # `.current-session*` — the bare pointer plus every per-author variant
    # (`.current-session-<author-slug>`), both of which exist in a real vault.
    for name in _listdir(vault):
        if name.startswith(".current-session"):
            out.append(os.path.join(vault, name))
    for directory in (
        paths.active_workflows_dir(project),
        os.path.join(vault, "sessions"),
        os.path.join(vault, "ledger"),
        os.path.join(vault, "queue"),
        os.path.join(vault, "queue", "history"),
        os.path.join(vault, "bank"),
    ):
        for name in _listdir(directory):
            out.append(os.path.join(directory, name))
    agents_root = os.path.join(vault, "agents")
    for agent_type in _listdir(agents_root):
        subdir = os.path.join(agents_root, agent_type)
        out.append(subdir)
        for name in _listdir(subdir):
            if name.endswith(".md"):
                out.append(os.path.join(subdir, name))
    return out


def fingerprint(project: str) -> Dict[str, Any]:
    """``{path: (mtime, size)}`` over every watched source. Reads nothing."""
    out = {}
    for path in watched_paths(project):
        info = _stat(path)
        if info is not None:
            out[path] = info
    return out


# ---------------------------------------------------------------------------
# T100 — the snapshot sections
# ---------------------------------------------------------------------------


def recent_sessions(vault: str, limit: int = RECENT_SESSIONS) -> List[Dict[str, Any]]:
    """The newest session logs by mtime, with their frontmatter stamps.

    Ordered by **mtime**, not by the date in the filename and not by any
    stamp inside the file: FR-58's whole point is that the log's own clocks
    are not comparable, and the filename's date is written by the same shell
    that writes the skewed stamps.
    """
    directory = os.path.join(vault, "sessions")
    rows = []
    for name in _listdir(directory):
        if not name.endswith(".md"):
            continue
        path = os.path.join(directory, name)
        info = _stat(path)
        if info is None:
            continue
        rows.append((info[0], info[1], path))
    rows.sort(reverse=True)
    out = []
    for mtime, size, path in rows[:limit]:
        meta = _frontmatter(_read(path, 4096))
        out.append(
            {
                "path": path,
                "name": os.path.basename(path),
                "mtime": _iso(mtime),
                "size": size,
                "started": meta.get("session_start"),
                # `status: active` is what the header carries while a session
                # is live; there is no `session_end` field, so "ended" is the
                # absence of `active` rather than a timestamp we do not have.
                "ended": None if meta.get("status") == "active" else _iso(mtime),
                "status": meta.get("status"),
                "branch": meta.get("branch"),
            }
        )
    return out


def ledger(vault: str) -> Dict[str, Any]:
    """Per-category entry counts, preferring ``meta.yaml``'s own tally.

    ``meta.yaml`` is written by the reflection pass and is authoritative. The
    ``---``-separator count over each ``.md`` is the fallback for a vault
    whose meta has not been written yet, and it is labelled as such: two ways
    of counting that disagree silently would be worse than one that is
    occasionally absent.
    """
    directory = os.path.join(vault, "ledger")
    meta_text = _read(os.path.join(directory, "meta.yaml"), 8192)
    counts, source = {}, None
    if meta_text:
        inside = False
        for line in meta_text.splitlines():
            if line.startswith("entries:"):
                inside = True
                continue
            if inside:
                if line[:1] not in (" ", "\t"):
                    break
                key, sep, value = line.strip().partition(":")
                if sep:
                    try:
                        counts[key] = int(value.strip())
                    except ValueError:
                        pass
        if counts:
            source = "meta.yaml"
    if not counts:
        for name in _listdir(directory):
            if not name.endswith(".md"):
                continue
            body = _read(os.path.join(directory, name))
            counts[name[: -len(".md")].replace("-", "_")] = body.count("\n---\n")
        source = "entry-count" if counts else None

    meta = _frontmatter("---\n%s\n---\n" % meta_text) if meta_text else {}
    reflections = meta.get("total_reflections")
    try:
        reflections = int(reflections)
    except (TypeError, ValueError):
        reflections = None
    return {
        "counts": counts,
        "source": source,
        "last_updated": meta.get("last_updated"),
        "total_reflections": reflections,
    }


def queue(vault: str) -> Dict[str, Any]:
    """Pending depth, history size, and the scheduler's last run line."""
    root = os.path.join(vault, "queue")
    history = os.path.join(root, "history")
    depth = len([n for n in _listdir(root) if n.endswith((".md", ".json", ".yaml"))])
    history_count = len([n for n in _listdir(history) if not n.startswith(".")])
    log = os.path.join(paths.smith_home(), "scheduler", "scheduler.log")
    last_run = None
    tail = _read_tail(log)
    for line in reversed(tail.splitlines()):
        if line.strip():
            last_run = line.strip()
            break
    return {
        "depth": depth,
        "history_count": history_count,
        "last_scheduler_run": last_run,
    }


def bank(vault: str, limit: int = RECENT_BANK) -> Dict[str, Any]:
    """Banked ideas, newest first, with the frontmatter each one carries."""
    directory = os.path.join(vault, "bank")
    names = [n for n in _listdir(directory) if n.endswith(".md")]
    recent = []
    for name in sorted(names, reverse=True)[:limit]:
        meta = _frontmatter(_read(os.path.join(directory, name), 4096))
        recent.append(
            {
                "id": meta.get("id") or name[: -len(".md")],
                "title": meta.get("title"),
                "status": meta.get("status"),
                "priority": meta.get("priority"),
            }
        )
    return {"count": len(names), "recent": recent}


def agents(vault: str) -> Dict[str, int]:
    """``{agent_type: memory-file count}``. One directory per type."""
    root = os.path.join(vault, "agents")
    out = {}
    for agent_type in _listdir(root):
        subdir = os.path.join(root, agent_type)
        if not os.path.isdir(subdir):
            continue
        out[agent_type] = len([n for n in _listdir(subdir) if n.endswith(".md")])
    return out


def index(project: str) -> Dict[str, Any]:
    """Manifest freshness. ``exists: False`` is a normal state, not an error."""
    root = os.path.join(project, ".smith", "index")
    manifest = os.path.join(root, "manifest.md")
    info = _stat(manifest)
    if info is None:
        return {
            "exists": False,
            "schema_version": None,
            "last_built": None,
            "file_count": None,
            "stale": None,
        }
    head = _read(manifest, 4096)
    last_built, file_count = None, None
    for line in head.splitlines():
        if line.lower().startswith("last updated:"):
            last_built = line.split(":", 1)[1].strip()
        elif "Total source files:" in line:
            digits = "".join(c for c in line.split(":", 1)[1] if c.isdigit())
            file_count = int(digits) if digits else None
    schema = None
    config = _read(os.path.join(root, "config", "context-manifest.json"), 4096)
    if config:
        try:
            schema = ((json.loads(config) or {}).get("_meta") or {}).get("version")
        except ValueError:
            schema = None
    return {
        "exists": True,
        "schema_version": schema,
        "last_built": last_built or _iso(info[0]),
        "file_count": file_count,
        # Staleness is left to whoever knows the source tree's mtimes; this
        # module will not guess it from the manifest alone, because "stale"
        # with no comparison behind it is an opinion, not an observation.
        "stale": None,
    }


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------


def snapshot(
    project: str, poll_state=None, now=None, start_offset: Optional[int] = None
) -> Dict[str, Any]:
    """One project's ``VaultSnapshot`` (``data-model.md`` §2.8). Reads only.

    ``poll_state`` is the per-project ``{path: (mtime, size)}`` map FR-38
    specifies. When it is supplied and the stat sweep finds nothing moved,
    the previous snapshot is returned unchanged — which is what keeps a 1 Hz
    poll from marking the state tree dirty every second and emitting a delta
    with nothing in it.
    """
    now = time.time() if now is None else now
    vault = paths.vault_dir(project)
    if not os.path.isdir(vault):
        return {
            "exists": False,
            "vault_dir": None,
            "index": index(project),
            "friction": friction(start_offset),
            "polled_at": _iso(now),
        }

    current = fingerprint(project)
    if poll_state is not None:
        with _LOCK:
            cached = _cache.get(project)
        if cached is not None:
            previous, snap, at = cached
            if previous == current and now - at < 60.0:
                return snap

    snap = {
        "exists": True,
        "vault_dir": vault,
        "recent_sessions": recent_sessions(vault),
        "ledger": ledger(vault),
        "queue": queue(vault),
        "bank": bank(vault),
        "agents": agents(vault),
        "index": index(project),
        "friction": friction(start_offset),
        "polled_at": _iso(now),
    }
    if poll_state is not None:
        poll_state.clear()
        poll_state.update(current)
        with _LOCK:
            _cache[project] = (current, snap, now)
    return snap
