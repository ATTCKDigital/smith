"""FR-12 artifact corroboration -> the I/O half.

``phases.py`` is required to be PURE (tasks.md Phase 3 header: "no file reads
except ``phases.json``, no git, no network, no clock except an injected
``now``"), which is what makes SC-1/SC-2 replayable against fixtures with no
daemon. FR-12 nevertheless needs the filesystem. The split is therefore:

* **here** -> find the feature's artifact directory and read what is on
  disk into a plain snapshot dict;
* **``phases.py``** -> map that snapshot onto phases
  (``artifact_signals``), with no idea where it came from.

A caller that already has a snapshot (a test, a replay) never touches this
module at all.

**Both layouts, worktree first.** ``specs/<n>-<slug>/`` is the flat
legacy layout; ``.specify/systems/<system>/features/<n>-<slug>/`` is
the system hierarchy ``/smith-migrate-specs`` produces. The worktree is
searched before the primary repo because that is where the workflow is
executing -> the primary repo's copy is whatever was last merged, which for
an in-flight feature is either absent or stale.

**A file READ never advances a phase** (FR-12). Nothing here observes reads;
it observes files. The rule is enforced structurally, by the resolver
consuming only the seven FR-11 signals, none of which a Read produces.

Python 3.8, stdlib only.
"""

import glob
import os
import re
from typing import Any, Dict, List, Optional

# The four artifacts FR-12 maps, in the order the workflow produces them.
ARTIFACT_NAMES = ("spec.md", "plan.md", "questions.md", "tasks.md")

# `- [ ] T001 …` / `- [X] T001 …`, the shape smith-tasks writes.
_TASK_BOX = re.compile(r"^\s*[-*]\s*\[(?P<mark>[ xX])\]\s")

# Both spellings occur: `**Answer**:` in this feature's own questions.md and
# `**Answer:**` in the global rule's stated format. An answered question has
# non-whitespace after the colon; a blank one is the gate.
_ANSWER = re.compile(
    r"^\s*\*\*Answer\*\*\s*:\s*(?P<body>.*?)\s*$"
    r"|^\s*\*\*Answer\s*:\s*\*\*\s*(?P<body2>.*?)\s*$"
)


def count_task_boxes(text: str) -> Dict[str, int]:
    """``{"checked": n, "total": N}`` over ``- [ ]`` / ``- [X]`` lines."""
    checked = 0
    total = 0
    for line in (text or "").splitlines():
        match = _TASK_BOX.match(line)
        if not match:
            continue
        total += 1
        if match.group("mark") in ("x", "X"):
            checked += 1
    return {"checked": checked, "total": total}


def count_unanswered_questions(text: str) -> Dict[str, int]:
    """``{"answered": n, "unanswered": m}`` over ``**Answer**:`` fields.

    A question whose ``**Answer**`` line has nothing after the colon is
    unanswered, which is FR-12's "sitting at the Phase 5 gate" signal.
    """
    answered = 0
    unanswered = 0
    for line in (text or "").splitlines():
        match = _ANSWER.match(line)
        if not match:
            continue
        body = match.group("body")
        if body is None:
            body = match.group("body2") or ""
        if body.strip():
            answered += 1
        else:
            unanswered += 1
    return {"answered": answered, "unanswered": unanswered}


def candidate_dirs(root: str, slug: str) -> List[str]:
    """Every directory under ``root`` that could hold ``slug``'s artifacts.

    ``slug`` comes from the marker's ``feature:`` field, which is NOT reliably
    the directory name: the live ``smith-build`` marker on this branch carries
    ``feature: activity-dashboard`` while the directory is
    ``60-activity-dashboard``. Both the bare and the ``<n>-`` prefixed
    forms are therefore globbed, in both layouts.
    """
    if not root or not slug:
        return []
    patterns = [
        os.path.join(root, "specs", slug),
        os.path.join(root, "specs", "[0-9]*-" + slug),
        os.path.join(root, ".specify", "systems", "*", "features", slug),
        os.path.join(root, ".specify", "systems", "*", "features", "[0-9]*-" + slug),
    ]
    found: List[str] = []
    seen = set()
    for pattern in patterns:
        for path in sorted(glob.glob(pattern)):
            real = os.path.realpath(path)
            if real in seen or not os.path.isdir(path):
                continue
            seen.add(real)
            found.append(path)
    return found


def _read(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def snapshot_dir(directory: str) -> Dict[str, Any]:
    """Read one artifact directory into the snapshot shape ``phases.py`` maps.

    ``files`` holds only the artifacts that exist; absence is expressed by the
    key being missing, never by a falsy placeholder, so "not written yet" and
    "written empty" stay distinguishable.
    """
    absolute = os.path.abspath(directory)
    parts = absolute.split(os.sep)
    snapshot: Dict[str, Any] = {
        "dir": absolute,
        "layout": "systems" if ".specify" in parts else "specs",
        "files": {},
        "questions": None,
        "tasks": None,
    }
    for name in ARTIFACT_NAMES:
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        text = _read(path)
        if text is None:
            continue
        snapshot["files"][name] = {"path": os.path.abspath(path), "bytes": len(text)}
        if name == "questions.md":
            snapshot["questions"] = count_unanswered_questions(text)
        elif name == "tasks.md":
            snapshot["tasks"] = count_task_boxes(text)
    return snapshot


def roots_for_marker(marker) -> List[str]:
    """The FR-12 search order for one marker: **worktree first, then primary.**

    The order is a property of this function rather than of each caller, so it
    cannot be got backwards in one place and right in another. The worktree is
    first because that is where the workflow is executing; the primary repo's
    copy of an in-flight feature is whatever was last merged, which is either
    absent or stale. Deduplicated on realpath so a marker with no ``worktree:``
    (the ``smith-finish`` shape) still searches the primary repo exactly once.
    """
    roots: List[str] = []
    seen = set()
    for candidate in ((marker or {}).get("worktree"), (marker or {}).get("project")):
        if not candidate:
            continue
        real = os.path.realpath(candidate)
        if real in seen:
            continue
        seen.add(real)
        roots.append(candidate)
    return roots


def scan_artifacts(slug: str, roots: List[str]) -> Optional[Dict[str, Any]]:
    """The FR-12 scan. ``roots`` in search order -> **worktree first**.

    Returns the first snapshot that contains at least one mapped artifact, or
    None when the feature has no artifact directory anywhere. Returning None
    rather than an empty snapshot matters: an empty snapshot would let the
    resolver "corroborate" nothing into something, and FR-20 forbids a guess.
    """
    for root in roots or []:
        for directory in candidate_dirs(root, slug):
            snapshot = snapshot_dir(directory)
            if snapshot["files"]:
                snapshot["root"] = os.path.abspath(root)
                return snapshot
    return None
