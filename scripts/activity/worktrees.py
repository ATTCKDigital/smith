"""Worktree and branch reality — FR-29, `data-model.md` §2.6.

One record per linked worktree plus the primary checkout, each cross-referenced
against the active-workflow markers that claim it.

Three things here are deliberate and easy to get wrong:

1. **The primary checkout is a worktree too**, and it is marked distinctly
   rather than omitted. ``git worktree list --porcelain`` returns it first and
   this module keeps it, because "which branch is the primary repo on" is a
   question the dashboard has to answer and dropping the row would make it
   unanswerable.

2. **Every git-derived field may be ``None``, and ``None`` is not zero.**
   ``ahead``/``behind`` are ``None`` when ``origin/<base>`` does not exist —
   which is the normal case for a repo with no remote, and for a brand-new
   base branch that has never been pushed. Rendering that as ``0/0`` would
   claim the worktree is in sync with something that is not there.

3. **``base_branch`` is resolved by the shipped script, never re-parsed.**
   ``skills/smith/scripts/get-base-branch.sh`` reads ``base_branch:`` out of
   the constitution's frontmatter and always exits 0 with a non-empty value.
   Re-implementing that awk here would be a second enumeration of a format
   this repo already owns. When the script cannot be found at all, the answer
   is ``None`` and ``base_branch_source`` says ``unresolved`` — an honest
   blank rather than a guessed ``main``, which would silently produce
   ahead/behind counts against the wrong branch.

4. **Classification is the six-row decision table from ``data-model.md``
   §2.6, evaluated top to bottom, first match wins** (T073/FR-30). Row 3
   (ORPHANED) sits ahead of row 4 (HELD) deliberately: a merged-and-deleted
   branch whose marker survives is janitor backlog, not a stalled bugfix, and
   rendering it as an active workflow is the exact phantom FR-30 forbids.

5. **git is cached per worktree on a ~3 s debounce and never runs per SSE
   frame** (T075/FR-31). The cache lives HERE rather than around
   ``describe()`` in ``refresh.py``, which is what it replaces. Caching the
   whole result would also have frozen the marker and session
   cross-references for 3 s, so a marker that appeared mid-window would go
   unrendered for no reason — the expensive thing is git, so git alone is
   what gets debounced.

Python 3.8, stdlib only.
"""

import os
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional

import paths

# The decision table lives in worktree_states.py (the 500-line decompose
# rule). Re-exported here so `import worktrees` remains the one import a
# caller needs, exactly as `usage` re-exports `subagents`.
from worktree_states import (  # noqa: F401
    CLASS_ACTIVE,
    CLASS_HELD,
    CLASS_MISSING,
    CLASS_ORPHANED,
    CLASS_PRIMARY,
    HELD_THRESHOLD_S,
    REMEDY_MISSING,
    REMEDY_ORPHANED,
    classify,
)

BASE_BRANCH_TIMEOUT_S = 5.0

#: T075/FR-31. How long a worktree's git-derived fields stay reusable.
GIT_CACHE_S = 3.0

# Where get-base-branch.sh can live, most-specific first: a project's own
# copy, this repo's checkout, then a global install. Mirrors the shape of
# usage.hook_dir()'s ladder for the same reason — one module must work from
# an install or from a worktree without being told which.
_BASE_BRANCH_CANDIDATES = (
    os.path.join(".specify", "scripts", "bash", "get-base-branch.sh"),
    os.path.join("skills", "smith", "scripts", "get-base-branch.sh"),
)

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)


def base_branch_script(primary_repo_path: str) -> Optional[str]:
    """Locate ``get-base-branch.sh``, or ``None`` if it is not installed."""
    roots = [primary_repo_path, _REPO_ROOT, os.path.join(paths.claude_home(), "skills")]
    for root in roots:
        if not root:
            continue
        for relative in _BASE_BRANCH_CANDIDATES:
            candidate = os.path.join(root, relative)
            if os.path.isfile(candidate):
                return candidate
    # The global install flattens skills/ one level: ~/.claude/skills/smith/...
    flat = os.path.join(
        paths.claude_home(), "skills", "smith", "scripts", "get-base-branch.sh"
    )
    return flat if os.path.isfile(flat) else None


def base_branch(worktree_path: str, primary_repo_path: str):
    """``(branch, source)``. ``source`` is ``get-base-branch.sh`` or
    ``unresolved``.

    Run with ``cwd`` set to the WORKTREE: the script resolves its own repo
    root with ``git rev-parse --show-toplevel``, and a worktree's constitution
    is the one that governs the branch being worked on.
    """
    script = base_branch_script(primary_repo_path)
    if not script:
        return None, "unresolved"
    try:
        proc = subprocess.run(
            ["bash", script],
            cwd=worktree_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=BASE_BRANCH_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None, "unresolved"
    value = proc.stdout.decode("utf-8", "replace").strip()
    if proc.returncode != 0 or not value:
        return None, "unresolved"
    return value, "get-base-branch.sh"


def ahead_behind(worktree_path: str, base: Optional[str]):
    """``(ahead, behind)`` versus ``origin/<base>``, or ``(None, None)``.

    ``None`` means "no comparison was possible", which is a different fact
    from "zero commits apart" and must not be collapsed into it. The usual
    cause is no ``origin`` remote, or a base branch that has never been
    pushed.
    """
    if not base:
        return None, None
    ref = "origin/%s" % base
    if paths.git(worktree_path, "rev-parse", "--verify", "--quiet", ref) is None:
        return None, None
    out = paths.git(
        worktree_path, "rev-list", "--left-right", "--count", "%s...HEAD" % ref
    )
    if not out:
        return None, None
    parts = out.split()
    if len(parts) != 2:
        return None, None
    try:
        # --left-right counts LEFT first: left is origin/<base> (commits we
        # are BEHIND by), right is HEAD (commits we are AHEAD by).
        behind, ahead = int(parts[0]), int(parts[1])
    except ValueError:
        return None, None
    return ahead, behind


def dirty_count(worktree_path: str) -> Optional[int]:
    """Number of entries in ``git status --porcelain``, or ``None``.

    ``--porcelain`` is one line per changed path, so this counts PATHS, not
    hunks. ``None`` when git could not be run at all, which again is not zero.
    """
    out = paths.git(worktree_path, "status", "--porcelain")
    if out is None:
        return None
    return len([line for line in out.splitlines() if line.strip()])


def short_path(path: str, home: Optional[str] = None) -> str:
    """``~``-collapsed display path. Purely cosmetic; nothing keys off it."""
    home = os.path.expanduser("~") if home is None else home
    if home and (path == home or path.startswith(home + os.sep)):
        return "~" + path[len(home) :]
    return path


def local_branches(repo_path: str) -> Optional[List[str]]:
    """Every local branch name, or ``None`` when git could not be asked.

    ``for-each-ref`` rather than ``rev-parse --verify refs/heads/<b>``, and
    the distinction is the whole point: ``rev-parse --verify`` exits non-zero
    both when the branch is ABSENT and when git itself failed, and
    ``paths.git`` collapses every non-zero exit to ``None``. A one-branch
    probe therefore cannot tell "this branch was deleted" (row 3, ORPHANED)
    from "we could not look" — and guessing the first would manufacture the
    very phantom FR-30 is about. Listing returns a string on success, so an
    empty list and a failure stay distinguishable.
    """
    out = paths.git(
        repo_path, "for-each-ref", "--format=%(refname:short)", "refs/heads/"
    )
    if out is None:
        return None
    return [line.strip() for line in out.splitlines() if line.strip()]


def branch_merged(repo_path: str, branch: Optional[str], base: Optional[str]):
    """Is every commit on ``branch`` already contained in the base branch?

    ``True`` / ``False`` / ``None``, and ``None`` — "no comparison was
    possible" — is a first-class answer, never collapsed into ``False``.
    ``origin/<base>`` is preferred when it exists because that is what a
    merged PR actually lands on; the local base is the fallback for a repo
    with no remote.

    **The equal-tips case is ``None``, not ``True``, and that is the whole
    reason this function is not a one-liner.** A zero count for
    ``<base>..<branch>`` says the branch adds no commits the base lacks —
    but a branch created seconds ago and never committed to satisfies that
    trivially, because it still points AT base. Returning ``True`` there
    classified every freshly-created ``/smith-new`` worktree as ORPHANED
    janitor backlog, which is the confidently-wrong output this whole feature
    exists to avoid. A fast-forwarded base is genuinely indistinguishable
    from that by refs alone, so both answer "unknown".

    **Known limitation — squash merges read as ``False``.** Smith itself
    merges with ``gh pr merge --squash --delete-branch``
    (skills/smith-build/SKILL.md:1239, skills/smith-bugfix/SKILL.md:427,
    skills/smith-finish/SKILL.md:187), and a squash rewrites the commits, so
    none of the branch's commits are ancestors of base afterwards. Detecting
    that needs a synthetic commit (``git commit-tree`` + ``git cherry``),
    which WRITES a loose object into the operator's repository — unacceptable
    from a read-only observer. In Smith's own flow the orphan is caught by
    the other half of row 3 instead: ``--delete-branch`` removes the branch,
    and ``_branch_gone`` sees that. A squash-merged branch whose local ref
    survived (git refuses to delete a branch checked out in a worktree) is
    therefore NOT detected as orphaned, and falls through to ``held``.
    """
    if not branch or not base:
        return None
    for ref in ("origin/%s" % base, base):
        base_tip = paths.git(repo_path, "rev-parse", "--verify", "--quiet", ref)
        if base_tip is None:
            continue
        out = paths.git(repo_path, "rev-list", "--count", "%s..%s" % (ref, branch))
        if out is None:
            continue
        try:
            contained = int(out.strip()) == 0
        except ValueError:
            continue
        if not contained:
            return False
        branch_tip = paths.git(repo_path, "rev-parse", "--verify", "--quiet", branch)
        if branch_tip is None or branch_tip == base_tip:
            return None  # never started, or fast-forwarded — indistinguishable
        return True
    return None


# ---------------------------------------------------------------------------
# The FR-31 per-worktree git cache (T075)
# ---------------------------------------------------------------------------

#: ``worktree path -> (expires_at, git-derived fields)``. Guarded by a lock
#: because ``server.py`` is a ``ThreadingHTTPServer``: the refresh thread and
#: an ``/api/state`` handler can both be inside ``describe()`` at once.
_GIT_CACHE = {}  # type: Dict[str, Any]
_GIT_CACHE_LOCK = threading.Lock()

#: Incremented once per genuine git fan-out. Tests assert on it, which is the
#: only way to prove the debounce actually debounces rather than merely
#: existing — a cache nobody counts is a cache nobody has verified.
_git_passes = 0


def reset_cache() -> None:
    """Drop every cached git answer. For tests and for a daemon restart."""
    global _git_passes
    with _GIT_CACHE_LOCK:
        _GIT_CACHE.clear()
        _git_passes = 0


def git_passes() -> int:
    """How many uncached git fan-outs have run since the last reset."""
    return _git_passes


def _git_fields(
    tree_path: str, branch: Optional[str], exists: bool, primary: str
) -> Dict[str, Any]:
    """Every git-derived field for one worktree, behind the FR-31 debounce."""
    global _git_passes
    now = time.time()
    with _GIT_CACHE_LOCK:
        cached = _GIT_CACHE.get(tree_path)
        if cached is not None and cached[0] > now:
            return cached[1]

    if exists:
        base, base_source = base_branch(tree_path, primary)
        ahead, behind = ahead_behind(tree_path, base)
        dirty = dirty_count(tree_path)
        merged = branch_merged(tree_path, branch, base)
        branches = local_branches(tree_path)
    else:
        # A marker can point at a worktree git still lists but that is gone
        # from disk. Every git-derived field is unknowable then, and says so.
        # The BRANCH facts are still askable — from the primary checkout,
        # which is still there — and row 3 needs them, so they are asked
        # there rather than abandoned along with the directory.
        base, base_source = None, "unresolved"
        ahead, behind = None, None
        dirty = None
        merged = None
        branches = local_branches(primary)

    fields = {
        "base_branch": base,
        "base_branch_source": base_source,
        "ahead": ahead,
        "behind": behind,
        "dirty_count": dirty,
        "branch_merged": merged,
        "local_branches": branches,
    }
    with _GIT_CACHE_LOCK:
        _GIT_CACHE[tree_path] = (time.time() + GIT_CACHE_S, fields)
        _git_passes += 1
    return fields


def _markers_for(worktree_path: str, branch: Optional[str], markers) -> List[Dict]:
    """Markers claiming this worktree, by ``worktree:`` then by ``branch:``.

    Both cross-references are needed and they disagree in practice. The
    ``smith-finish`` marker variant carries NO ``worktree:`` field at all, so
    a worktree-only match would lose it; and a marker written from inside a
    worktree records that worktree while its branch may also be checked out
    somewhere else. Path first, branch as the fallback.
    """
    by_path, by_branch = [], []
    real = os.path.realpath(worktree_path) if worktree_path else None
    for marker in markers or []:
        marker_wt = marker.get("worktree")
        if marker_wt and real and os.path.realpath(marker_wt) == real:
            by_path.append(marker)
        elif branch and (marker.get("branch") or "") == branch:
            by_branch.append(marker)
    return by_path or by_branch


def describe(
    path_in_repo: str, markers=(), sessions=(), workflows=(), now=None
) -> List[Dict[str, Any]]:
    """One record per worktree for the repo containing ``path_in_repo``.

    ``markers`` are ``markers.read_marker`` records (from BOTH vaults — see
    binding constraint 10); ``sessions`` are dicts carrying at least ``cwd``
    and ``session_id``; ``workflows`` are ``resolver.resolve_workflow``
    records, needed only by row 4 — without them HELD cannot be evaluated and
    an owned, on-disk, unmerged worktree classifies as ``active``.

    Safe to call on every poll: git sits behind the FR-31 per-worktree
    debounce, and the marker/session cross-reference is recomputed each time
    so a marker that appears mid-window is not invisible for 3 s.

    Returns ``[]`` when the path is not a git repo, rather than raising: the
    dashboard enumerates whatever projects it was told about, and one of them
    not being a repo any more is a state to render, not an error.
    """
    primary = paths.primary_repo(path_in_repo)
    if not primary:
        return []
    primary_real = os.path.realpath(primary)
    by_key = {w.get("key"): w for w in workflows or ()}

    records: List[Dict[str, Any]] = []
    for tree in paths.list_worktrees(path_in_repo):
        tree_path = tree.get("path") or ""
        real = os.path.realpath(tree_path) if tree_path else ""
        is_primary = real == primary_real
        exists = os.path.isdir(tree_path) if tree_path else False
        branch = tree.get("branch")

        git_fields = _git_fields(tree_path, branch, exists, primary)

        owning = _markers_for(tree_path, branch, markers)
        occupying = [
            session.get("session_id")
            for session in sessions or []
            if session.get("cwd") and os.path.realpath(session["cwd"]) == real
        ]

        record = {
            "path": tree_path,
            "short_path": short_path(tree_path),
            "exists": exists,
            "branch": branch,
            "head": tree.get("head"),
            "detached": bool(tree.get("detached")),
            "bare": bool(tree.get("bare")),
            "is_primary": is_primary,
            "base_branch": git_fields["base_branch"],
            "base_branch_source": git_fields["base_branch_source"],
            "ahead": git_fields["ahead"],
            "behind": git_fields["behind"],
            "dirty_count": git_fields["dirty_count"],
            "branch_merged": git_fields["branch_merged"],
            "branch_gone": _branch_gone(owning, branch, git_fields["local_branches"]),
            # A branch can legitimately carry two markers at once — the
            # primary vault's smith-new and the worktree vault's
            # smith-build (binding constraint 10) — so this is a LIST and
            # `owning_marker` names the first only for display.
            "owning_markers": [m.get("key") for m in owning],
            "owning_marker": owning[0].get("key") if owning else None,
            "occupying_sessions": occupying,
            "occupying_session": occupying[0] if occupying else None,
        }
        # `_markers_for` already did the matching; handing the records
        # themselves to the classifier keeps it from re-deriving the
        # cross-reference and getting a different answer. Stripped again
        # below so the marker dicts never reach the state tree.
        record["_markers"] = owning
        owning_workflows = [by_key[k] for k in record["owning_markers"] if k in by_key]
        record.update(classify(record, workflows=owning_workflows, now=now))
        record.pop("_markers", None)
        records.append(record)
    return records


def _branch_gone(owning, branch: Optional[str], branches) -> Optional[bool]:
    """Row 3's "branch gone", three-valued.

    ``None`` when git could not list the branches — absence of evidence is
    never evidence of deletion here, because the consequence of getting it
    wrong is declaring a live worktree orphaned.

    The branch that matters is the MARKER's, not the worktree's. git will not
    let a checked-out branch be deleted, so a worktree whose own ``branch``
    is set can never have a gone branch; the real shape is a worktree left
    detached after its branch was merged and deleted, with the marker still
    naming what used to be there.
    """
    if branches is None:
        return None
    claimed = [m.get("branch") for m in owning or () if m.get("branch")]
    if not claimed:
        return None if branch is None else False
    known = set(branches)
    return all(name not in known for name in claimed)
