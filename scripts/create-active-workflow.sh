#!/usr/bin/env bash
# create-active-workflow.sh — Create an active-workflow marker for Smith.
#
# This is the SOLE auditable entrypoint for marker creation. The
# workflow-gate hook (hooks/workflow-gate.sh) exempts this exact script
# by basename, so it can run even when no marker exists yet — solving
# the bootstrap chicken-and-egg that bit PRs #25, #27, #28, #29, #30.
#
# Replaces the inline heredoc that the four workflow SKILL.md files
# (smith-new, smith-bugfix, smith-debug, smith-build) used to ship.
# Per spec/31-workflow-gate-bootstrap/spec.md.
#
# Usage:
#   create-active-workflow.sh --branch <BRANCH> --workflow <WORKFLOW> \
#     --slug <SLUG> --worktree <WORKTREE_PATH> [--session-log <PATH>]
#
# Behavior:
#   - Resolves project root via `git rev-parse --show-toplevel`.
#   - Computes safe branch name (non-[A-Za-z0-9._-] -> '-').
#   - Atomic write: tempfile + rename.
#   - Idempotent: re-run for the same (branch, workflow) updates the
#     `started` timestamp but otherwise no-ops.
#   - Collision: re-run with a DIFFERENT workflow on the same branch
#     exits 3 with a clear error.
#   - Also appends a workflow-start line to the current session log so
#     workflow-summary.sh --totals-only can attribute tokens correctly.
#
# Exit codes:
#   0 — marker created or updated idempotently.
#   2 — input validation error (bad branch name, missing required flag,
#       unknown workflow type, non-absolute worktree).
#   3 — collision (a marker already exists for this branch with a
#       different workflow type).
#   4 — write error (filesystem permissions, disk full, etc).
#
# Stdlib bash 4+ only. No Python dependency.

set -euo pipefail

# ---------- usage ----------

usage() {
    cat << 'USAGE'
Usage: create-active-workflow.sh --branch <BRANCH> --workflow <WORKFLOW> \
       --slug <SLUG> --worktree <WORKTREE_PATH> [--session-log <PATH>]

Creates an active-workflow marker at
<PROJECT_ROOT>/.smith/vault/active-workflows/<safe-branch>.yaml

Required:
  --branch    Git branch name (e.g. fix/foo or 23-feature). Validated.
  --workflow  One of: smith-new, smith-bugfix, smith-debug, smith-build.
  --slug      Short feature slug (used in feature: field).
  --worktree  Absolute path to the worktree.

Optional:
  --session-log  Absolute path to the session log to stamp. Defaults to
                 the path in .smith/vault/.current-session if present.
USAGE
}

# ---------- arg parsing ----------

BRANCH=""
WORKFLOW=""
SLUG=""
WORKTREE=""
SESSION_LOG=""

while [ $# -gt 0 ]; do
    case "$1" in
        --branch)       BRANCH="$2"; shift 2 ;;
        --workflow)     WORKFLOW="$2"; shift 2 ;;
        --slug)         SLUG="$2"; shift 2 ;;
        --worktree)     WORKTREE="$2"; shift 2 ;;
        --session-log)  SESSION_LOG="$2"; shift 2 ;;
        -h|--help)      usage; exit 0 ;;
        *)              printf 'create-active-workflow: unknown arg: %s\n' "$1" >&2
                        usage >&2
                        exit 2 ;;
    esac
done

# ---------- input validation ----------

err() { printf 'create-active-workflow: %s\n' "$*" >&2; }

for v in BRANCH WORKFLOW SLUG WORKTREE; do
    eval "value=\${$v}"
    if [ -z "$value" ]; then
        err "missing required --$(printf '%s' "$v" | tr '[:upper:]' '[:lower:]')"
        exit 2
    fi
done

# Branch regex: alnum, slash, dot, underscore, hyphen. No shell
# metacharacters; no spaces.
if ! printf '%s' "$BRANCH" | grep -qE '^[A-Za-z0-9._/-]+$'; then
    err "invalid --branch: must match [A-Za-z0-9._/-]+ (got: $BRANCH)"
    exit 2
fi

# Workflow allowlist.
case "$WORKFLOW" in
    smith-new|smith-bugfix|smith-debug|smith-build) ;;
    *)
        err "invalid --workflow: must be one of smith-new, smith-bugfix, smith-debug, smith-build (got: $WORKFLOW)"
        exit 2
        ;;
esac

# Worktree must be absolute.
case "$WORKTREE" in
    /*) ;;
    *)
        err "invalid --worktree: must be an absolute path (got: $WORKTREE)"
        exit 2
        ;;
esac

# Slug: same charset as branch, no slashes (it's a name fragment, not a path).
if ! printf '%s' "$SLUG" | grep -qE '^[A-Za-z0-9._-]+$'; then
    err "invalid --slug: must match [A-Za-z0-9._-]+ (got: $SLUG)"
    exit 2
fi

# ---------- resolve project root ----------

if ! PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null); then
    err "not inside a git repository; cannot resolve project root"
    exit 2
fi

# ---------- compute paths ----------

# SAFE_BRANCH: replace non-[A-Za-z0-9._-] with '-' (collapses '/' to '-').
SAFE_BRANCH=$(printf '%s' "$BRANCH" | sed 's/[^A-Za-z0-9._-]/-/g')
MARKER_DIR="$PROJECT_ROOT/.smith/vault/active-workflows"
MARKER_PATH="$MARKER_DIR/${SAFE_BRANCH}.yaml"

mkdir -p "$MARKER_DIR" 2>/dev/null || {
    err "could not create marker directory: $MARKER_DIR"
    exit 4
}

# ---------- collision check ----------

if [ -f "$MARKER_PATH" ]; then
    existing_workflow=$(grep -E '^workflow: ' "$MARKER_PATH" 2>/dev/null | head -1 | sed 's/^workflow: //')
    if [ -n "$existing_workflow" ] && [ "$existing_workflow" != "$WORKFLOW" ]; then
        err "collision: marker for branch '$BRANCH' already exists with workflow '$existing_workflow' (requested: $WORKFLOW)"
        err "marker: $MARKER_PATH"
        err "remove via .specify/scripts/bash/clear-active-workflow.sh '$BRANCH' OR pick a different branch name"
        exit 3
    fi
fi

# ---------- resolve session log path ----------

if [ -z "$SESSION_LOG" ]; then
    if [ -f "$PROJECT_ROOT/.smith/vault/.current-session" ]; then
        SESSION_LOG=$(cat "$PROJECT_ROOT/.smith/vault/.current-session" 2>/dev/null || echo "")
    fi
fi

# ---------- compose marker body ----------

NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
TMP_MARKER="${MARKER_PATH}.tmp.$$"

{
    printf 'workflow: %s\n' "$WORKFLOW"
    printf 'feature: %s\n' "$SLUG"
    printf 'branch: %s\n' "$BRANCH"
    printf 'worktree: %s\n' "$WORKTREE"
    printf 'session_log: %s\n' "$SESSION_LOG"
    printf 'started: %s\n' "$NOW"
} > "$TMP_MARKER" 2>/dev/null || {
    err "write error: could not write temp marker $TMP_MARKER"
    rm -f "$TMP_MARKER" 2>/dev/null || true
    exit 4
}

mv -f "$TMP_MARKER" "$MARKER_PATH" 2>/dev/null || {
    err "rename error: could not move temp marker into place"
    rm -f "$TMP_MARKER" 2>/dev/null || true
    exit 4
}

# ---------- stamp the session log ----------
#
# Appends one line so workflow-summary.sh --totals-only can attribute
# tokens to this workflow without the fragile $SESSION threading.
# Skip silently if session log isn't present or can't be written —
# stamping is a nice-to-have, not a precondition for marker creation.

if [ -n "$SESSION_LOG" ] && [ -f "$SESSION_LOG" ]; then
    {
        printf '\n### [%s] workflow-start %s\n' "$(date -u +"%H:%M:%S")" "$BRANCH"
        printf '\n**Workflow:** %s\n' "$WORKFLOW"
        printf '**Feature:** %s\n' "$SLUG"
        printf '**Worktree:** %s\n' "$WORKTREE"
        printf '**Marker:** %s\n' "$MARKER_PATH"
        printf '\n'
    } >> "$SESSION_LOG" 2>/dev/null || true
fi

# ---------- output ----------

printf '%s\n' "$MARKER_PATH"
exit 0
