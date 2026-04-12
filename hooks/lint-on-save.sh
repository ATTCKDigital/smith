#!/usr/bin/env bash
# lint-on-save.sh
# Event: PostToolUse
# Matcher: Write|Edit
# Scope: Universal (main session + sub-agents)
#
# Runs the appropriate linter/formatter based on file extension after a file
# is written or edited. Failures do not block the workflow.

set -uo pipefail

# Consume stdin (hook input JSON)
INPUT=$(cat)

# Extract file_path from tool_input
FILE_PATH=$(echo "$INPUT" | grep -o '"file_path"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"file_path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/' || echo "")

if [ -z "$FILE_PATH" ] || [ ! -f "$FILE_PATH" ]; then
    exit 0
fi

# Get file extension
EXT="${FILE_PATH##*.}"

case "$EXT" in
    py)
        # Python: run ruff if available
        if command -v ruff &>/dev/null; then
            ruff check "$FILE_PATH" --fix --quiet 2>&1 >&2 || true
            ruff format "$FILE_PATH" --quiet 2>&1 >&2 || true
        fi
        ;;
    ts|tsx|js|jsx|css|html)
        # JS/TS/CSS/HTML: run prettier if available in the project
        if [ -f "$CLAUDE_PROJECT_DIR/node_modules/.bin/prettier" ]; then
            "$CLAUDE_PROJECT_DIR/node_modules/.bin/prettier" --write "$FILE_PATH" 2>&1 >&2 || true
        elif command -v npx &>/dev/null; then
            npx --yes prettier --write "$FILE_PATH" 2>&1 >&2 || true
        fi
        ;;
esac

exit 0
