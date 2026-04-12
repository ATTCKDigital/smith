#!/usr/bin/env bash
# file-change-logger.sh
# Event: PostToolUse
# Matcher: Write|Edit
# Scope: Universal (main session + sub-agents)
#
# Logs file change entries to the current session log.
# Appends a one-line timestamped entry with the tool name and file path.

set -euo pipefail

# Consume stdin (hook input JSON)
INPUT=$(cat)

VAULT_DIR="$CLAUDE_PROJECT_DIR/.smith/vault"
CURRENT_SESSION_FILE="$VAULT_DIR/.current-session"

# Exit silently if no current session
if [ ! -f "$CURRENT_SESSION_FILE" ]; then
    exit 0
fi

SESSION_FILE=$(cat "$CURRENT_SESSION_FILE")

if [ ! -f "$SESSION_FILE" ]; then
    exit 0
fi

# Extract tool name
TOOL_NAME=$(echo "$INPUT" | grep -o '"tool_name"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"tool_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/' || echo "Unknown")

# Extract file_path from tool_input
FILE_PATH=$(echo "$INPUT" | grep -o '"file_path"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"file_path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/' || echo "unknown")

# Make path relative to project dir if possible
REL_PATH="${FILE_PATH#$CLAUDE_PROJECT_DIR/}"

# Timestamp
NOW_TIME=$(date -u +"%H:%M:%S")

# Append entry to session log
echo "- \`[$NOW_TIME]\` **$TOOL_NAME** \`$REL_PATH\`" >> "$SESSION_FILE"

exit 0
