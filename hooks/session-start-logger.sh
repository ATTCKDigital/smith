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
PROJECT_CONFIG="$CLAUDE_PROJECT_DIR/.smith/config.json"

# Ensure directories exist
mkdir -p "$SESSIONS_DIR"
mkdir -p "$HOME/.smith"

# Seed .smith/config.json from the shipped default if missing. Idempotent:
# no-op when a config already exists, even if it's an older shape. Users
# who want to reset can delete the file and let the next SessionStart
# re-seed it. Silent skip when no template is found — historically this
# file didn't exist and skills tolerate its absence.
if [ ! -f "$PROJECT_CONFIG" ]; then
    for candidate in \
        "$HOME/.smith/templates/config.default.json" \
        "$HOME/.claude/skills/smith/templates/config.default.json" \
        "$CLAUDE_PROJECT_DIR/templates/config.default.json"; do
        if [ -f "$candidate" ]; then
            cp "$candidate" "$PROJECT_CONFIG" 2>/dev/null || true
            break
        fi
    done
fi

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
    # Fresh start: create new session log.
    #
    # Naming scheme (feature 36-team-shareable-vault): conflict-free and
    # team-attributable. Filename = <name-slug>_<email-hash>_<datetime>.md
    #   name-slug  = git user.name, lowercased, non-alnum -> '-', trimmed
    #   email-hash = first 6 hex of sha256(git user.email)
    # Fallbacks keep the hash stable per machine-user when git identity is unset.
    RAW_NAME=$(git -C "$CLAUDE_PROJECT_DIR" config user.name 2>/dev/null || echo "")
    RAW_EMAIL=$(git -C "$CLAUDE_PROJECT_DIR" config user.email 2>/dev/null || echo "")
    [ -z "$RAW_NAME" ] && RAW_NAME="${USER:-unknown}"

    NAME_SLUG=$(printf '%s' "$RAW_NAME" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')
    [ -z "$NAME_SLUG" ] && NAME_SLUG="unknown"

    HASH_INPUT="$RAW_EMAIL"
    [ -z "$HASH_INPUT" ] && HASH_INPUT="${USER:-unknown}@$(hostname 2>/dev/null || echo localhost)"
    EMAIL_HASH=$(printf '%s' "$HASH_INPUT" | (shasum -a 256 2>/dev/null || sha256sum) | cut -c1-6)

    SESSION_FILE="$SESSIONS_DIR/${NAME_SLUG}_${EMAIL_HASH}_${NOW_FILE}.md"

    # author: raw git identity (name + email). Escape embedded double quotes.
    AUTHOR_NAME=$(printf '%s' "$RAW_NAME" | sed 's/"/\\"/g')
    AUTHOR_EMAIL=$(printf '%s' "$RAW_EMAIL" | sed 's/"/\\"/g')

    cat > "$SESSION_FILE" << EOF
---
session_start: "$NOW_ISO"
project: "$PROJECT_NAME"
branch: "$BRANCH"
author: "$AUTHOR_NAME <$AUTHOR_EMAIL>"
status: active
---

# Session Log

## Started: $NOW_DATE $NOW_TIME

---
EOF

    # Write current session pointers (per Q2-A):
    #   .current-session-<slug>  → canonical per-user pointer (gitignored)
    #   .current-session         → legacy local alias (gitignored); ~29
    #                              existing consumers keep reading this.
    echo "$SESSION_FILE" > "$VAULT_DIR/.current-session-${NAME_SLUG}"
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
