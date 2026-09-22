"""Active-workflow marker discovery and the tolerant marker read.

**Markers for one branch can live in two different vaults at the same time,
and this module's whole reason to exist is to find both.**

Verified empirically 2026-09-22, superseding research.md §Q6:

* ``scripts/create-active-workflow.sh:139`` resolves the project root with
  ``git rev-parse --show-toplevel`` — inside a worktree that is the
  **worktree**, so the marker lands in ``<worktree>/.smith/vault/``.
* ``hooks/workflow-gate.sh:60`` resolves with ``${CLAUDE_PROJECT_DIR:-$(pwd)}``
  — which stays pinned to the **primary repo**.

Consequence: ``/smith-build`` invoked on a branch ``/smith-new`` already
registered exits **0**, not 3, and a second marker is created. A
``workflow: smith-new`` marker sits in the primary vault while a
``workflow: smith-build`` marker for the same ``branch:`` sits in the
worktree's vault. The worktree marker's ``session_log:`` is **empty**, because
``.smith/vault/.current-session`` does not exist in a worktree.

So: enumerate both vaults, correlate by ``branch:``, tolerate an empty
``session_log:``, and key every record by primary repo so a worktree never
becomes a second project (FR-28).

This module only ever READS ``.smith/vault/active-workflows/``. Nothing in
this feature writes there (FR-44).

Python 3.8, stdlib only.
"""

import glob
import os
import re
from typing import Any, Dict, List, Optional

import paths

# The six fields create-active-workflow.sh:181-187 writes, plus the optional
# seventh. Nothing writes `phase:` today; FR-13 accepts it and prefers it over
# every inferred signal, which makes OOS-1's later stamping purely additive.
MARKER_FIELDS = (
    "workflow",
    "feature",
    "branch",
    "worktree",
    "session_log",
    "started",
    "phase",
)

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def marker_filename_for_branch(branch: str) -> str:
    """``fix/log`` → ``fix-log.yaml``.

    The SAFE_BRANCH mapping from create-active-workflow.sh:143 and
    skills/smith-finish/SKILL.md:76 — ``[^A-Za-z0-9._-]`` → ``-``.
    """
    return "%s.yaml" % _UNSAFE_FILENAME_CHARS.sub("-", branch or "")


def _unquote(value: str) -> str:
    """Strip a trailing CR and one layer of matching surrounding quotes.

    Smith's own markers are written unquoted, but
    ``hooks/active-workflow-janitor.sh:118`` already tolerates quotes
    defensively and this parser matches that precedent. (The collision check at
    create-active-workflow.sh:159 does not, which is a latent false-collide —
    not this feature's to fix.)
    """
    value = value.strip()
    if value.endswith("\r"):
        value = value[:-1].rstrip()
    for quote in ('"', "'"):
        if len(value) >= 2 and value.startswith(quote) and value.endswith(quote):
            return value[1:-1]
    return value


def parse_marker_text(text: str) -> Dict[str, str]:
    """Parse ``key: value`` lines into a dict. Unknown keys are kept.

    Split on the FIRST colon only: ``started: 2026-09-22T15:18:00Z`` contains
    three more. An empty value is preserved as ``""`` rather than dropped,
    because ``session_log: `` with a trailing space and nothing after it is a
    valid, occurring shape (create-active-workflow.sh:170-174 falls back to
    empty when neither --session-log nor .current-session resolves) and the
    difference between "absent" and "present but empty" is real.
    """
    fields: Dict[str, str] = {}
    for line in (text or "").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key = key.strip()
        if not key or " " in key:
            continue
        fields.setdefault(key, _unquote(value))
    return fields


def normalize_started(value: Optional[str]) -> Optional[str]:
    """Tolerate ``started:`` with and without a trailing ``Z``.

    create-active-workflow.sh writes ``date -u +"%Y-%m-%dT%H:%M:%SZ"``;
    skills/smith-finish/SKILL.md:80 writes the same format **without** the
    ``Z``. Both mean UTC. Returns an ISO-8601 Z string, or None.
    """
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    return text if text.endswith("Z") else text + "Z"


def read_marker(
    marker_path: str,
    primary_repo_path: Optional[str] = None,
    vault_root: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Read one marker into the record shape of data-model.md §2.4.

    ``primary_repo_path`` is the project this marker belongs to — always the
    PRIMARY repo, even when the marker itself lives in a worktree's vault.
    ``vault_root`` is the repo or worktree whose vault physically holds it.

    Returns None only when the file cannot be read. A marker with missing or
    nonsensical fields still comes back: ``branch:`` may name no real git ref
    (``debug-<slug>`` from smith-debug/SKILL.md:96-104, and /smith-audit's
    synthetic labels), and the ``smith-finish`` variant legitimately has
    neither ``worktree:`` nor ``session_log:``.
    """
    try:
        with open(marker_path, "r", encoding="utf-8", errors="replace") as fh:
            raw = parse_marker_text(fh.read())
    except OSError:
        return None

    vault_root = vault_root or _vault_root_of(marker_path)
    primary = primary_repo_path or paths.primary_repo(vault_root) or vault_root
    filename = os.path.basename(marker_path)

    session_log = raw.get("session_log") or ""
    session_log = session_log.strip() or None
    session_log_source = "marker" if session_log else None
    if session_log is None:
        # The worktree-marker case: .current-session does not exist in a
        # worktree, so create-active-workflow.sh wrote an empty value. Fall
        # back to the PRIMARY vault's pointer rather than yielding None.
        fallback = _read_current_session(primary)
        if fallback:
            session_log = fallback
            session_log_source = "current-session"

    worktree = raw.get("worktree") or None

    return {
        # NOT (project, branch): smith-finish writes finish-<safe>.yaml
        # alongside a possible <safe>.yaml, so two markers legitimately exist
        # for one branch.
        #
        # data-model.md §2.4 specifies (project, marker_filename). That is one
        # component short of unique once dual-vault enumeration is mandatory:
        # the smith-new/smith-build nest puts the SAME filename
        # (<safe-branch>.yaml, derived from the same branch) in BOTH vaults,
        # so the two markers of a single nest collide on that key. §2.4's
        # worked example happens to use two different branches, which hides
        # it. vault_root is therefore part of the key; §2.4's stated reason
        # for the key is preserved unchanged.
        "key": "%s|%s|%s" % (primary, vault_root, filename),
        "project": primary,
        "vault_root": vault_root,
        "is_primary_vault": os.path.realpath(vault_root) == os.path.realpath(primary),
        "marker_path": os.path.abspath(marker_path),
        "marker_filename": filename,
        "workflow_type": raw.get("workflow") or None,
        "slug": raw.get("feature") or None,
        "branch": raw.get("branch") or None,
        "worktree": worktree,
        "session_log": session_log,
        "session_log_source": session_log_source,
        "started": normalize_started(raw.get("started")),
        # FR-13: preferred over every inferred signal when present.
        "declared_phase": (raw.get("phase") or "").strip() or None,
        "raw": raw,
    }


def _vault_root_of(marker_path: str) -> str:
    """``<root>/.smith/vault/active-workflows/x.yaml`` → ``<root>``."""
    return os.path.abspath(os.path.join(os.path.dirname(marker_path), "..", "..", ".."))


def _read_current_session(root: str) -> Optional[str]:
    """Read ``<root>/.smith/vault/.current-session``.

    Double existence check — the pointer AND its target — per
    hooks/metrics-tracker.sh:23-32, because a pointer left behind by a removed
    session log is a shape that occurs.
    """
    pointer = paths.current_session_pointer(root)
    if not os.path.isfile(pointer):
        return None
    try:
        with open(pointer, "r", encoding="utf-8", errors="replace") as fh:
            target = fh.read().strip()
    except OSError:
        return None
    if not target or not os.path.isfile(target):
        return None
    return target


def vault_roots(path: str) -> List[str]:
    """Every root whose ``.smith/vault/`` may hold markers for this project.

    The primary checkout first, then every linked worktree. Deduplicated on
    realpath, so a worktree that happens to sit inside the primary tree is not
    visited twice.
    """
    primary = paths.primary_repo(path)
    roots: List[str] = []
    seen = set()

    def add(candidate: Optional[str]) -> None:
        if not candidate:
            return
        real = os.path.realpath(candidate)
        if real in seen:
            return
        seen.add(real)
        roots.append(candidate)

    add(primary)
    for tree in paths.list_worktrees(path):
        add(tree.get("path"))
    if not roots:
        add(path)
    return roots


def enumerate_markers(path: str) -> List[Dict[str, Any]]:
    """Every marker under the primary repo vault AND every linked worktree's.

    Single-vault enumeration is the bug this function exists to prevent: it
    would see the ``smith-new`` marker and miss the ``smith-build`` child
    entirely, or vice versa depending on where it was called from.

    Sorted by (vault_root, filename) so the order is stable across calls and
    the primary vault's markers come first.
    """
    primary = paths.primary_repo(path)
    records: List[Dict[str, Any]] = []
    for root in vault_roots(path):
        pattern = os.path.join(paths.active_workflows_dir(root), "*.yaml")
        for marker_path in sorted(glob.glob(pattern)):
            record = read_marker(
                marker_path, primary_repo_path=primary, vault_root=root
            )
            if record is not None:
                records.append(record)
    records.sort(
        key=lambda r: (not r["is_primary_vault"], r["vault_root"], r["marker_filename"])
    )
    return records


def correlate_by_branch(
    records: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Group markers by ``branch:``.

    A branch with two records and two different ``workflow_type`` values is
    the normal ``smith-new`` → ``smith-build`` nest (FR-17), NOT a
    contradiction — findings.py must not raise ``marker_contradiction`` for it.
    Markers with no ``branch:`` are grouped under ``""`` rather than dropped.
    """
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(record.get("branch") or "", []).append(record)
    return grouped


def find_by_branch(records: List[Dict[str, Any]], branch: str) -> List[Dict[str, Any]]:
    return [r for r in records if (r.get("branch") or "") == branch]
