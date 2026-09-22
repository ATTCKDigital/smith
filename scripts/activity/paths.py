"""Identity and path layout for /smith-activity.

Every other module in scripts/activity/ hangs off the one rule in
data-model.md §1: **a project is its primary repo, resolved once.** A worktree
is never a second project (FR-28/SC-7), so nothing here ever uses
``git rev-parse --show-toplevel``.

Python 3.8, stdlib only.
"""

import os
import subprocess
from typing import Dict, List, Optional

# git is bounded with subprocess(timeout=) rather than a `timeout` binary:
# neither `timeout` nor `gtimeout` exists on a stock macOS, so the TIMEOUT_BIN
# idiom elsewhere in this repo imposes no bound at all.
GIT_TIMEOUT_S = 5.0


# ---------------------------------------------------------------------------
# SMITH_HOME
# ---------------------------------------------------------------------------


def smith_home() -> str:
    """The Smith home directory.

    Mirrors the installer's canonical shell expansion
    ``"${SMITH_HOME:-$HOME/.smith}"`` (scripts/install.sh:20,
    scripts/uninstall.sh:15). `or` rather than a dict default so an empty
    SMITH_HOME behaves like an unset one, exactly as `:-` does.

    Deliberately NOT modelled on scheduler/smith-scheduler.sh:36, which
    hardcodes $HOME/.smith and ignores the override — that is a latent bug,
    not a pattern.
    """
    return os.environ.get("SMITH_HOME") or os.path.expanduser("~/.smith")


def activity_dir() -> str:
    """All daemon runtime state lives here, never inside a project vault (FR-7)."""
    return os.path.join(smith_home(), "activity")


def claude_home() -> str:
    """Claude Code's own config root, home of projects/ and settings.json."""
    return os.path.expanduser("~/.claude")


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------


def git(path: str, *args: str) -> Optional[str]:
    """Run git in ``path`` and return stripped stdout, or None on any failure.

    None means "could not be determined" and is always a valid answer here —
    a project may legitimately not be a git repo, and git may be missing.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", path] + list(args),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", "replace").strip()


def primary_repo(path: str) -> Optional[str]:
    """FR-28. Absolute path to the primary checkout, or None if not a repo.

    ``--path-format=absolute`` is load-bearing. From inside a worktree
    ``--git-common-dir`` already returns an absolute path to the primary
    ``.git``, but from inside the primary repo it returns the relative string
    ``.git`` — and ``dirname(".git")`` is ``""``. Verified from both
    positions.

    This is the ONLY identity source that is trustworthy: CLAUDE_PROJECT_DIR
    is not always set, and the hook envelope's ``cwd``, ``claude agents
    --json``'s ``cwd``, the transcript's ``cwd`` and
    ``git rev-parse --show-toplevel`` all report the worktree.
    """
    if not path:
        return None
    common = git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not common:
        return None
    parent = os.path.dirname(common)
    return parent or None


def list_worktrees(path: str) -> List[Dict[str, Optional[str]]]:
    """Parse ``git worktree list --porcelain`` for the repo containing ``path``.

    Returns one dict per worktree: ``{path, head, branch, detached, bare}``,
    the primary checkout first (git's own output order). ``branch`` is the
    short name, or None for a detached HEAD.

    Lives here rather than in markers.py or worktrees.py because both of those
    need it and two parses of the same porcelain format is exactly the
    duplication this repo's reuse-before-create rule exists to prevent.
    """
    out = git(path, "worktree", "list", "--porcelain")
    if out is None:
        return []
    trees: List[Dict[str, Optional[str]]] = []
    current: Dict[str, Optional[str]] = {}
    for line in out.splitlines():
        if not line.strip():
            if current.get("path"):
                trees.append(current)
            current = {}
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            if current.get("path"):
                trees.append(current)
            current = {
                "path": value,
                "head": None,
                "branch": None,
                "detached": False,
                "bare": False,
            }
        elif key == "HEAD":
            current["head"] = value
        elif key == "branch":
            # `branch refs/heads/foo` → `foo`
            current["branch"] = (
                value[len("refs/heads/") :]
                if value.startswith("refs/heads/")
                else value
            )
        elif key == "detached":
            current["detached"] = True
        elif key == "bare":
            current["bare"] = True
    if current.get("path"):
        trees.append(current)
    return trees


# ---------------------------------------------------------------------------
# ~/.claude/projects layout (data-model.md §4.3)
# ---------------------------------------------------------------------------


def project_slug(primary_repo_path: str) -> str:
    """The ~/.claude/projects directory name for a project.

    The project path with ``/`` → ``-``, which leaves a leading ``-`` because
    the path starts with ``/``. Reused verbatim from the repo's own idiom at
    hooks/workflow_summary_lib.py:225 so the two cannot drift apart.

    Keyed on the **primary repo**, which confirms §1's identity rule from a
    second direction: two worktrees of one repo share one transcript
    directory.
    """
    return (primary_repo_path or "").replace("/", "-")


def project_transcript_dir(primary_repo_path: str) -> str:
    """~/.claude/projects/<slug> — may not exist; callers check."""
    return os.path.join(claude_home(), "projects", project_slug(primary_repo_path))


def transcript_path(primary_repo_path: str, session_id: str) -> str:
    """The parent transcript: ~/.claude/projects/<slug>/<session-id>.jsonl."""
    return os.path.join(
        project_transcript_dir(primary_repo_path), "%s.jsonl" % session_id
    )


def subagents_dir(primary_repo_path: str, session_id: str) -> str:
    """~/.claude/projects/<slug>/<session-id>/subagents/.

    The parent transcript contains zero ``isSidechain: true`` rows, so this
    directory is the ONLY source of live subagent tokens (FR-36).
    """
    return os.path.join(
        project_transcript_dir(primary_repo_path), session_id, "subagents"
    )


def subagent_jsonl(primary_repo_path: str, session_id: str, agent_id: str) -> str:
    """.../subagents/agent-<agent-id>.jsonl — the sidechain turns."""
    return os.path.join(
        subagents_dir(primary_repo_path, session_id), "agent-%s.jsonl" % agent_id
    )


def subagent_meta(primary_repo_path: str, session_id: str, agent_id: str) -> str:
    """.../subagents/agent-<agent-id>.meta.json — the dispatch metadata sidecar.

    Primary source for FR-27; SubagentStart only shortens discovery latency
    (contracts/hook-envelope.md §3).
    """
    return os.path.join(
        subagents_dir(primary_repo_path, session_id), "agent-%s.meta.json" % agent_id
    )


def agent_id_from_sidecar(filename: str) -> Optional[str]:
    """``agent-<id>.meta.json`` / ``agent-<id>.jsonl`` → ``<id>``."""
    name = os.path.basename(filename)
    if not name.startswith("agent-"):
        return None
    name = name[len("agent-") :]
    for suffix in (".meta.json", ".jsonl"):
        if name.endswith(suffix):
            return name[: -len(suffix)] or None
    return None


# ---------------------------------------------------------------------------
# Project vault layout (READ-ONLY — nothing here is ever written to)
# ---------------------------------------------------------------------------


def vault_dir(repo_or_worktree_path: str) -> str:
    """<path>/.smith/vault. Note this takes a *worktree* path deliberately:
    create-active-workflow.sh:139 writes markers into the worktree's vault,
    so both the primary and every linked worktree have one."""
    return os.path.join(repo_or_worktree_path, ".smith", "vault")


def active_workflows_dir(repo_or_worktree_path: str) -> str:
    """<path>/.smith/vault/active-workflows. READ-ONLY for this feature."""
    return os.path.join(vault_dir(repo_or_worktree_path), "active-workflows")


def current_session_pointer(repo_or_worktree_path: str) -> str:
    """<path>/.smith/vault/.current-session — the legacy alias every one of the
    ~29 existing consumers reads. Does not exist in a worktree, which is why a
    worktree marker's ``session_log:`` is empty."""
    return os.path.join(vault_dir(repo_or_worktree_path), ".current-session")
