#!/usr/bin/env bash
# clear-active-workflow.sh — safely remove a single active-workflow marker file.
#
# Exists so Smith skills can clean up .smith/vault/active-workflows/<branch>.yaml
# on projects whose .claude/settings.json denies `Bash(rm:*)` as a safety rail.
# This helper never globs, never recurses, and refuses any path that escapes
# .smith/vault/active-workflows/.

set -eu

BRANCH="${1:-}"
[ -n "$BRANCH" ] || { echo "usage: $(basename "$0") <branch-name>" >&2; exit 2; }

SAFE=$(printf '%s' "$BRANCH" | sed 's/[^a-zA-Z0-9._-]/-/g')
case "$SAFE" in
    ''|.|..) echo "error: invalid sanitized name: '$SAFE'" >&2; exit 3 ;;
esac

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) \
    || { echo "error: not inside a git working tree" >&2; exit 4; }

DIR="$REPO_ROOT/.smith/vault/active-workflows"
TARGET="$DIR/$SAFE.yaml"

# No-op when nothing to clean (also handles the case where DIR doesn't exist).
[ -e "$TARGET" ] || [ -L "$TARGET" ] || exit 0

EXPECTED=$(cd "$DIR" && pwd -P)
ACTUAL=$(cd "$(dirname "$TARGET")" && pwd -P)
[ "$EXPECTED" = "$ACTUAL" ] \
    || { echo "error: target escapes active-workflows dir" >&2; exit 5; }

if [ -L "$TARGET" ]; then
    LINK=$(readlink "$TARGET")
    RESOLVED=$(cd "$DIR" && cd "$(dirname "$LINK")" 2>/dev/null && pwd -P) || RESOLVED=""
    case "$RESOLVED" in
        "$EXPECTED"|"$EXPECTED"/*) ;;
        *) echo "error: symlink resolves outside active-workflows" >&2; exit 6 ;;
    esac
fi

unlink "$TARGET"
