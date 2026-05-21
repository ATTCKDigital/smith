#!/usr/bin/env bash
# manifest-updater.sh
# Event: PostToolUse
# Matcher: Write|Edit
# Scope: Universal (main session + sub-agents)
#
# Updates the Smith manifest (.smith/index/) incrementally after every
# file mutation. Reads stdin JSON from Claude Code, extracts the changed
# file path, filters non-source extensions, then delegates to the
# Python helper (manifest-updater-lib.py) for parsing + .meta + system
# manifest patching + threshold-warning emission.
#
# Design notes:
#   - Registered LAST in the PostToolUse Write|Edit chain (spec Decision 7)
#     so it captures the post-lint state of the file.
#   - No kill switch (per Q3). The hook is designed to fail-open: any
#     internal error is logged and exits 0 without blocking Claude.
#   - Performance target: <500ms p95. Bash filtering is cheap; heavy
#     lifting is in the Python helper.
#   - If the file is >300 lines, the Python helper emits an
#     additionalContext JSON warning on stdout that Claude Code injects
#     into the next turn.

set -uo pipefail

# Consume stdin (Claude Code hook input JSON).
INPUT=$(cat 2>/dev/null || echo '{}')

# Extract tool_input.file_path with the same grep+sed pattern used by the
# other hooks (file-change-logger.sh, lint-on-save.sh). Avoids a jq
# dependency on the hot path.
FILE_PATH=$(printf '%s' "$INPUT" \
    | grep -o '"file_path"[[:space:]]*:[[:space:]]*"[^"]*"' \
    | head -1 \
    | sed 's/.*"file_path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/' \
    || echo "")

# Extract cwd if present (useful for project-root discovery).
PROJECT_ROOT=$(printf '%s' "$INPUT" \
    | grep -o '"cwd"[[:space:]]*:[[:space:]]*"[^"]*"' \
    | head -1 \
    | sed 's/.*"cwd"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/' \
    || echo "")
if [ -z "$PROJECT_ROOT" ]; then
    PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$PWD}"
fi

LOG_FILE="${HOME}/.smith/logs/hooks.log"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

log_status() {
    local ts
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '%s manifest-updater %s\n' "$ts" "$*" >> "$LOG_FILE" 2>/dev/null || true
}

# Bail silently if we couldn't extract a path.
if [ -z "$FILE_PATH" ]; then
    log_status "status=skipped reason=no-file-path"
    exit 0
fi

# Bail if file doesn't exist (e.g. Edit on a path being created+deleted in a
# round trip; nothing to parse).
if [ ! -f "$FILE_PATH" ]; then
    log_status "file=$FILE_PATH status=skipped reason=missing-file"
    exit 0
fi

# Cheap extension allowlist check in bash before paying for python3 startup.
ext="${FILE_PATH##*.}"
case ".$ext" in
    .py|.js|.jsx|.ts|.tsx|.css|.html|.sh)
        ;;
    *)
        log_status "file=$FILE_PATH ext=.$ext status=skipped reason=ext-not-allowed"
        exit 0
        ;;
esac

# Cheap excluded-dir check (cheaper than spawning python).
case "$FILE_PATH" in
    */.smith/*|*/node_modules/*|*/.venv/*|*/venv/*|*/vendor/*|*/dist/*|*/build/*|*/.git/*|*/__pycache__/*|*/.specify/*)
        log_status "file=$FILE_PATH status=skipped reason=excluded-dir"
        exit 0
        ;;
esac

# Resolve the Python helper. Search order:
#   1. Sibling file next to this script (repo dev layout)
#   2. ~/.claude/hooks/manifest-updater-lib.py (post-install)
#   3. ~/.smith/hooks/manifest-updater-lib.py  (alt install)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HELPER=""
for cand in \
    "$SCRIPT_DIR/manifest-updater-lib.py" \
    "$HOME/.claude/hooks/manifest-updater-lib.py" \
    "$HOME/.smith/hooks/manifest-updater-lib.py"; do
    if [ -f "$cand" ]; then
        HELPER="$cand"
        break
    fi
done

if [ -z "$HELPER" ]; then
    log_status "file=$FILE_PATH status=skipped reason=no-helper"
    exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
    log_status "file=$FILE_PATH status=skipped reason=no-python3"
    exit 0
fi

# Run the helper. It emits structured log lines to stderr; we tee them
# into hooks.log. Its stdout (if any) is the additionalContext JSON
# warning, which we pass through unchanged on our stdout for Claude Code
# to inject.
#
# Wrap with `timeout 2s` if available so a runaway parser can't block
# Claude. Bail on any failure — exit 0 always.
TIMEOUT_BIN=""
if command -v timeout >/dev/null 2>&1; then
    TIMEOUT_BIN="timeout 2s"
elif command -v gtimeout >/dev/null 2>&1; then
    TIMEOUT_BIN="gtimeout 2s"
fi

STDERR_TMP="$(mktemp 2>/dev/null || echo /tmp/manifest-updater-$$.err)"
# shellcheck disable=SC2086
$TIMEOUT_BIN python3 "$HELPER" "$FILE_PATH" "$PROJECT_ROOT" 2>"$STDERR_TMP" || true

# Append the helper's structured log lines to hooks.log.
if [ -s "$STDERR_TMP" ]; then
    cat "$STDERR_TMP" >> "$LOG_FILE" 2>/dev/null || true
fi
rm -f "$STDERR_TMP" 2>/dev/null || true

exit 0
