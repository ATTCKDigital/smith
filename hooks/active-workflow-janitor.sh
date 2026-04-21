#!/usr/bin/env bash
# active-workflow-janitor.sh
# Event: Stop
# Scope: Main session only (no-op in subagents)
#
# Sweeps stale active-workflow marker files in .smith/vault/active-workflows/.
# Removes any <name>.yaml whose `branch:` field points to a branch that is:
#   (a) gone from both local and origin, or
#   (b) already merged into origin/main (tip reachable from main).
#
# Why this hook exists:
#   - Projects that add `Bash(rm:*)` to their deny list block skill-level
#     cleanup even when the narrow clear-active-workflow.sh helper misses.
#   - Sessions that crash or are interrupted never run skill cleanup, leaving
#     orphaned marker files that mislead future workflow-state checks.
#   - Hooks run without permission prompts, so this catches both cases.
#
# Safety:
#   - Only removes files under <project>/.smith/vault/active-workflows/.
#   - Never removes a marker for a branch with unmerged commits.
#   - No-op outside git repos, missing active-workflows dir, or when
#     origin/main (or origin/master) is absent.

set -u

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
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

is_stale() {
    local branch="$1"
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
    if is_stale "$branch"; then
        rm -f "$yaml" && removed=$((removed + 1))
    fi
done

if [ "$removed" -gt 0 ]; then
    echo "[active-workflow-janitor] removed $removed stale marker(s)" >&2
fi

exit 0
