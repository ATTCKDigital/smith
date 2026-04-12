#!/usr/bin/env bash
# session-end-review.sh
# Event: Stop
# Scope: Main session only
#
# On session end: reviews file changes logged during the session, checks if any
# changed files fall under system spec directories, outputs a reminder if spec
# updates may be needed, and marks the session log as completed.

set -euo pipefail

# Consume stdin (hook input JSON)
INPUT=$(cat)

# Check for stop_hook_active to prevent infinite loops
if echo "$INPUT" | grep -q '"stop_hook_active"[[:space:]]*:[[:space:]]*true'; then
    exit 0
fi

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

# Extract file paths from session log (lines matching **Edit** or **Write** pattern)
CHANGED_FILES=$(grep -oE '\*\*(Edit|Write)\*\* `[^`]+`' "$SESSION_FILE" 2>/dev/null | sed 's/.*`\(.*\)`/\1/' | sort -u || echo "")

if [ -n "$CHANGED_FILES" ]; then
    # Check if any changed files map to system specs
    SPECS_DIR="$CLAUDE_PROJECT_DIR/.specify"
    SPEC_WARNINGS=""

    if [ -d "$SPECS_DIR" ]; then
        while IFS= read -r filepath; do
            # Check if file is under services/ (most common case)
            if echo "$filepath" | grep -q "^services/"; then
                SERVICE=$(echo "$filepath" | cut -d'/' -f2)
                SPEC_WARNINGS="${SPEC_WARNINGS}\n  - $filepath (service: $SERVICE)"
            fi
        done <<< "$CHANGED_FILES"
    fi

    if [ -n "$SPEC_WARNINGS" ]; then
        echo ""
        echo "Files changed this session that may need spec updates:"
        echo -e "$SPEC_WARNINGS"
        echo ""
        echo "Review and update relevant system specs before ending the session."
    fi
fi

# Mark session as completed
NOW_ISO=$(date -u +"%Y-%m-%dT%H:%M:%S")
NOW_DATE=$(date -u +"%Y-%m-%d")
NOW_TIME=$(date -u +"%H:%M:%S")

# Update frontmatter status
sed -i '' 's/^status: active$/status: completed/' "$SESSION_FILE"

# Append session end
printf "\n## Ended: %s %s\n" "$NOW_DATE" "$NOW_TIME" >> "$SESSION_FILE"

exit 0
