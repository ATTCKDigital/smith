#!/usr/bin/env bash
# active-workflow-janitor.sh
# Event: Stop
# Scope: Main session only (no-op in subagents)
#
# Sweeps stale active-workflow marker files in .smith/vault/active-workflows/.
# Removes any <name>.yaml whose `branch:` field points to a branch that is:
#   (a) gone from both local and origin, or
#   (b) already merged into origin/main (tip reachable from main),
#       AND the marker is past the grace period.
#
# Why this hook exists:
#   - Projects that add `Bash(rm:*)` to their deny list block skill-level
#     cleanup even when the narrow clear-active-workflow.sh helper misses.
#   - Sessions that crash or are interrupted never run skill cleanup, leaving
#     orphaned marker files that mislead future workflow-state checks.
#   - Hooks run without permission prompts, so this catches both cases.
#
# Safety (refined from PR #20's research findings):
#   - Project root is resolved via `git rev-parse --git-common-dir` so
#     subagent contexts (where CLAUDE_PROJECT_DIR is unset and $PWD is a
#     worktree) still find the primary repo where the marker actually lives.
#   - Grace period (default: 1 hour) protects freshly-created markers from
#     being false-swept. The window between `marker creation` and `first
#     commit on the branch` is the danger zone — during it, branch tip ==
#     main tip and the naive is-ancestor check returns true. Markers under
#     the grace period are kept regardless of git state.
#   - Only removes files under <project>/.smith/vault/active-workflows/.
#   - Never removes a marker for a branch with unmerged commits.
#   - No-op outside git repos, missing active-workflows dir, or when
#     origin/main (or origin/master) is absent.

set -u

# Resolve project root. Subagent contexts inherit a $PWD pointing at the
# worktree, and $CLAUDE_PROJECT_DIR is unset. The active-workflow marker
# lives in the PRIMARY repo's .smith/vault/, not the worktree. Use git's
# own resolution to walk back: `git rev-parse --git-common-dir` returns
# the primary repo's `.git` from inside a worktree (and `.git` from the
# primary repo itself). Its dirname is the primary repo root.
RESOLVED_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
GIT_COMMON_DIR=$(git -C "$RESOLVED_DIR" rev-parse --git-common-dir 2>/dev/null || true)
if [ -n "$GIT_COMMON_DIR" ]; then
    case "$GIT_COMMON_DIR" in
        /*) PROJECT_DIR=$(dirname "$GIT_COMMON_DIR") ;;
        *)  PROJECT_DIR=$(cd "$RESOLVED_DIR" && cd "$(dirname "$GIT_COMMON_DIR")" 2>/dev/null && pwd) ;;
    esac
    : "${PROJECT_DIR:=$RESOLVED_DIR}"
else
    PROJECT_DIR="$RESOLVED_DIR"
fi
cd "$PROJECT_DIR" 2>/dev/null || exit 0

[ -d .smith/vault/active-workflows ] || exit 0
git rev-parse --git-dir >/dev/null 2>&1 || exit 0

MAIN_REF=""
for ref in origin/main origin/master; do
    if git rev-parse --verify --quiet "$ref" >/dev/null 2>&1; then
        MAIN_REF="$ref"
        break
    fi
done
[ -n "$MAIN_REF" ] || exit 0

# Grace period: don't sweep markers younger than this. Avoids false-positive
# on freshly-created markers where the branch hasn't yet diverged from main
# (smith-new's Phase 0 creates the marker BEFORE the worktree exists and
# before any commits are made — branch tip == main tip transiently, which
# would otherwise trigger the merged-check). Once the workflow makes any
# commit, the branch diverges and the merged-check correctly returns false
# until a real merge happens. Override via SMITH_JANITOR_GRACE_SECONDS.
GRACE_SECONDS="${SMITH_JANITOR_GRACE_SECONDS:-3600}"

# Cross-platform mtime in seconds since epoch (macOS / Linux).
mtime_of() {
    stat -f %m "$1" 2>/dev/null || stat -c %Y "$1" 2>/dev/null || echo 0
}

is_stale() {
    local branch="$1"
    local marker_file="$2"

    # Grace period guard: leave markers younger than GRACE_SECONDS alone.
    # This is the fix for the "branch tip == main tip on a fresh branch"
    # false-positive observed during PR #20's smith-build.
    local now=$(date +%s)
    local mtime=$(mtime_of "$marker_file")
    if [ "$mtime" -gt 0 ] && [ $((now - mtime)) -lt "$GRACE_SECONDS" ]; then
        return 1
    fi

    local local_exists=0 remote_exists=0
    git show-ref --verify --quiet "refs/heads/$branch" && local_exists=1
    git show-ref --verify --quiet "refs/remotes/origin/$branch" && remote_exists=1

    # Gone from local and remote — workflow is definitively over.
    if [ "$local_exists" = "0" ] && [ "$remote_exists" = "0" ]; then
        return 0
    fi

    # Merged: branch tip is reachable from origin/main (covers merge-commit
    # and fast-forward merges). Squash/rebase merges that rewrite SHAs won't
    # match here — those get caught when the branch is eventually deleted,
    # at which point case (a) applies.
    local ref=""
    [ "$local_exists" = "1" ] && ref="refs/heads/$branch"
    [ -z "$ref" ] && ref="refs/remotes/origin/$branch"
    if git merge-base --is-ancestor "$ref" "$MAIN_REF" 2>/dev/null; then
        return 0
    fi

    return 1
}

extract_branch() {
    # Read the first `branch:` line, strip the key and trim whitespace/CR.
    # Values in smith yamls are plain (no quotes), but tolerate wrapped
    # quotes defensively.
    local raw
    raw=$(awk -F: '/^branch:/ {sub(/^[[:space:]]*/, "", $2); print $2; exit}' "$1")
    raw="${raw%$'\r'}"
    raw="${raw#\"}"; raw="${raw%\"}"
    raw="${raw#\'}"; raw="${raw%\'}"
    printf '%s' "$raw"
}

removed=0
for yaml in .smith/vault/active-workflows/*.yaml; do
    [ -f "$yaml" ] || continue
    branch=$(extract_branch "$yaml")
    [ -n "$branch" ] || continue
    if is_stale "$branch" "$yaml"; then
        rm -f "$yaml" && removed=$((removed + 1))
    fi
done

if [ "$removed" -gt 0 ]; then
    echo "[active-workflow-janitor] removed $removed stale marker(s)" >&2
fi

exit 0
