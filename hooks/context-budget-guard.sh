#!/usr/bin/env bash
# context-budget-guard.sh
# Event: PostToolUse
# Matcher: Write|Edit
# Scope: Universal (main session + sub-agents)
#
# Warns (never blocks) when a just-written file crosses a size threshold.
# Files that are @-referenced from CLAUDE.md are flagged extra-loudly because
# they are loaded IN FULL into every session's context — re-growth there is the
# expensive case this guard exists to catch at the moment of writing.
#
# Threshold is configurable via .smith/config.json:
#   { "context_budget": { "max_file_kb": 50 } }
# Defaults to 50 KB when the key (or the file) is absent. Set max_file_kb to 0
# to disable the guard entirely.
#
# This hook is advisory: it prints to stderr and always exits 0.

set -uo pipefail

# Consume stdin (hook input JSON)
INPUT=$(cat)

# Extract file_path from tool_input
FILE_PATH=$(echo "$INPUT" | grep -o '"file_path"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"file_path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/' || echo "")

if [ -z "$FILE_PATH" ] || [ ! -f "$FILE_PATH" ]; then
    exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# --- Resolve threshold (KB) from config; default 50, 0 disables -------------
THRESHOLD_KB=50
CONFIG_FILE="$PROJECT_DIR/.smith/config.json"
if [ -f "$CONFIG_FILE" ] && command -v python3 >/dev/null 2>&1; then
    CFG_KB=$(python3 -c "import json,sys; d=json.load(open('$CONFIG_FILE')); print(d.get('context_budget',{}).get('max_file_kb',50))" 2>/dev/null || echo "")
    case "$CFG_KB" in
        ''|*[!0-9]*) : ;;          # non-numeric / empty → keep default
        *) THRESHOLD_KB="$CFG_KB" ;;
    esac
fi

# 0 disables the guard.
if [ "$THRESHOLD_KB" -eq 0 ] 2>/dev/null; then
    exit 0
fi

# --- File size in bytes (portable: BSD then GNU stat) -----------------------
SIZE_BYTES=$(stat -f%z "$FILE_PATH" 2>/dev/null || stat -c%s "$FILE_PATH" 2>/dev/null || echo 0)
THRESHOLD_BYTES=$((THRESHOLD_KB * 1024))

if [ "$SIZE_BYTES" -le "$THRESHOLD_BYTES" ] 2>/dev/null; then
    exit 0
fi

SIZE_KB=$((SIZE_BYTES / 1024))
REL_PATH="${FILE_PATH#$PROJECT_DIR/}"

# --- Is this file @-referenced from the project CLAUDE.md? ------------------
# @-referenced files are loaded in full every session — the expensive case.
IS_AT_REFERENCED=false
CLAUDE_MD="$PROJECT_DIR/CLAUDE.md"
if [ -f "$CLAUDE_MD" ]; then
    # Match a leading-@ reference to this file by its project-relative path or
    # basename (e.g. "@docs/data-model.md" or "@data-model.md").
    BASENAME=$(basename "$FILE_PATH")
    if grep -Eq "@(${REL_PATH//\//\\/}|[^[:space:]]*/${BASENAME}|${BASENAME})([[:space:]]|\$)" "$CLAUDE_MD" 2>/dev/null; then
        IS_AT_REFERENCED=true
    fi
fi

if [ "$IS_AT_REFERENCED" = true ]; then
    {
        echo "⚠️  CONTEXT BUDGET: $REL_PATH is ${SIZE_KB} KB and is @-referenced from CLAUDE.md."
        echo "    @-referenced files load IN FULL into every session's context. This one"
        echo "    exceeds the ${THRESHOLD_KB} KB soft cap — likely accumulating per-change prose."
        echo "    Keep it to durable/structural content only (ERD, tables, enums, notes);"
        echo "    per-change history belongs in .smith/vault/sessions/ + ledger + git."
    } >&2
else
    echo "⚠️  CONTEXT BUDGET: $REL_PATH is ${SIZE_KB} KB (> ${THRESHOLD_KB} KB soft cap). Consider trimming or decomposing." >&2
fi

exit 0
