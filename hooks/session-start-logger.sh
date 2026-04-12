#!/usr/bin/env bash
# session-start-logger.sh
# Event: SessionStart
# Scope: Main session only
#
# Creates a new session log in .smith/vault/sessions/ on fresh start,
# or appends a resume entry if the session is being resumed.
# Updates the global project index at ~/.smith/projects.json.

set -euo pipefail

# Consume stdin (hook input JSON)
INPUT=$(cat)

VAULT_DIR="$CLAUDE_PROJECT_DIR/.smith/vault"
SESSIONS_DIR="$VAULT_DIR/sessions"
CURRENT_SESSION_FILE="$VAULT_DIR/.current-session"
GLOBAL_INDEX="$HOME/.smith/projects.json"

# Ensure directories exist
mkdir -p "$SESSIONS_DIR"
mkdir -p "$HOME/.smith"

# Timestamps
NOW_ISO=$(date -u +"%Y-%m-%dT%H:%M:%S")
NOW_DATE=$(date -u +"%Y-%m-%d")
NOW_TIME=$(date -u +"%H:%M:%S")
NOW_FILE=$(date -u +"%Y-%m-%d_%H%M%S")

# Detect project name and branch
PROJECT_NAME=$(basename "$CLAUDE_PROJECT_DIR")
BRANCH=$(cd "$CLAUDE_PROJECT_DIR" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")

# Check if this is a resume
TRIGGER=$(echo "$INPUT" | grep -o '"trigger"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"trigger"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/' || echo "")

if [ "$TRIGGER" = "resume" ]; then
    # Resume: append to existing active session log
    if [ -f "$CURRENT_SESSION_FILE" ]; then
        SESSION_FILE=$(cat "$CURRENT_SESSION_FILE")
        if [ -f "$SESSION_FILE" ]; then
            printf "\n## Resumed: %s %s\n\n---\n" "$NOW_DATE" "$NOW_TIME" >> "$SESSION_FILE"
        fi
    fi
elif [ "$TRIGGER" = "compact" ]; then
    # Compaction: log the event to the existing session log
    if [ -f "$CURRENT_SESSION_FILE" ]; then
        SESSION_FILE=$(cat "$CURRENT_SESSION_FILE")
        if [ -f "$SESSION_FILE" ]; then
            # Calculate approximate duration from session start
            SESSION_START=$(grep 'session_start:' "$SESSION_FILE" | head -1 | sed 's/.*"\(.*\)".*/\1/' || echo "")
            printf "\n### [%s] Context compacted\n\n**Reason:** user-initiated or auto-triggered\n**Session start:** %s\n\n---\n" "$NOW_TIME" "$SESSION_START" >> "$SESSION_FILE"
        fi
    fi
else
    # Fresh start: create new session log
    SESSION_FILE="$SESSIONS_DIR/${NOW_FILE}.md"

    cat > "$SESSION_FILE" << EOF
---
session_start: "$NOW_ISO"
project: "$PROJECT_NAME"
branch: "$BRANCH"
status: active
---

# Session Log

## Started: $NOW_DATE $NOW_TIME

---
EOF

    # Write current session pointer
    echo "$SESSION_FILE" > "$CURRENT_SESSION_FILE"
fi

# Update global project index
VAULT_PATH="$VAULT_DIR"

if [ ! -f "$GLOBAL_INDEX" ]; then
    # Create new index
    cat > "$GLOBAL_INDEX" << EOF
[
  {
    "name": "$PROJECT_NAME",
    "path": "$VAULT_PATH",
    "last_session": "$NOW_ISO"
  }
]
EOF
else
    # Check if project already exists in index
    if grep -q "\"name\": \"$PROJECT_NAME\"" "$GLOBAL_INDEX" 2>/dev/null; then
        # Update last_session for existing project
        sed -i '' "s|\"last_session\": \"[^\"]*\"|\"last_session\": \"$NOW_ISO\"|" "$GLOBAL_INDEX"
    else
        # Add new project entry before the closing bracket
        # Remove trailing newline and bracket, add comma and new entry
        sed -i '' '$ s/]$//' "$GLOBAL_INDEX"
        cat >> "$GLOBAL_INDEX" << EOF
  ,{
    "name": "$PROJECT_NAME",
    "path": "$VAULT_PATH",
    "last_session": "$NOW_ISO"
  }
]
EOF
    fi
fi

exit 0
