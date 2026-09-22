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

Classification (the six-row decision table), the HELD/MISSING/ORPHANED states
and FR-31's git debounce are T073-T075 and are deliberately NOT here yet.
``classification`` is therefore absent from these records rather than present
and wrong.

Python 3.8, stdlib only.
"""

import os
import subprocess
from typing import Any, Dict, List, Optional

import paths

BASE_BRANCH_TIMEOUT_S = 5.0

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


def describe(path_in_repo: str, markers=(), sessions=()) -> List[Dict[str, Any]]:
    """One record per worktree for the repo containing ``path_in_repo``.

    ``markers`` are ``markers.read_marker`` records (from BOTH vaults — see
    binding constraint 10); ``sessions`` are dicts carrying at least ``cwd``
    and ``session_id``.

    Returns ``[]`` when the path is not a git repo, rather than raising: the
    dashboard enumerates whatever projects it was told about, and one of them
    not being a repo any more is a state to render, not an error.
    """
    primary = paths.primary_repo(path_in_repo)
    if not primary:
        return []
    primary_real = os.path.realpath(primary)

    records: List[Dict[str, Any]] = []
    for tree in paths.list_worktrees(path_in_repo):
        tree_path = tree.get("path") or ""
        real = os.path.realpath(tree_path) if tree_path else ""
        is_primary = real == primary_real
        exists = os.path.isdir(tree_path) if tree_path else False
        branch = tree.get("branch")

        if exists:
            base, base_source = base_branch(tree_path, primary)
            ahead, behind = ahead_behind(tree_path, base)
            dirty = dirty_count(tree_path)
        else:
            # A marker can point at a worktree git still lists but that is
            # gone from disk. Every git-derived field is unknowable then, and
            # says so. (T073 classifies this as MISSING.)
            base, base_source = None, "unresolved"
            ahead, behind = None, None
            dirty = None

        owning = _markers_for(tree_path, branch, markers)
        occupying = [
            session.get("session_id")
            for session in sessions or []
            if session.get("cwd") and os.path.realpath(session["cwd"]) == real
        ]

        records.append(
            {
                "path": tree_path,
                "short_path": short_path(tree_path),
                "exists": exists,
                "branch": branch,
                "head": tree.get("head"),
                "detached": bool(tree.get("detached")),
                "bare": bool(tree.get("bare")),
                "is_primary": is_primary,
                "base_branch": base,
                "base_branch_source": base_source,
                "ahead": ahead,
                "behind": behind,
                "dirty_count": dirty,
                # A branch can legitimately carry two markers at once — the
                # primary vault's smith-new and the worktree vault's
                # smith-build (binding constraint 10) — so this is a LIST and
                # `owning_marker` names the first only for display.
                "owning_markers": [m.get("key") for m in owning],
                "owning_marker": owning[0].get("key") if owning else None,
                "occupying_sessions": occupying,
                "occupying_session": occupying[0] if occupying else None,
            }
        )
    return records
