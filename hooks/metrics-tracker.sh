#!/usr/bin/env bash
# metrics-tracker.sh
# Event: PostToolUse
# Matcher: *
# Scope: Universal (main session + sub-agents)
#
# Logs tool input/output character counts to the session log for token estimation.
# Token estimate = total_chars / 4
#
# Appends entries to the session log's Metrics section. At workflow end, skills
# aggregate these entries for the final summary.

set -euo pipefail

INPUT=$(cat)

VAULT_DIR="${CLAUDE_PROJECT_DIR:-.}/.smith/vault"
CURRENT_SESSION_FILE="$VAULT_DIR/.current-session"

# Exit silently if no current session
if [ ! -f "$CURRENT_SESSION_FILE" ]; then
    exit 0
fi

SESSION_FILE=$(cat "$CURRENT_SESSION_FILE")
if [ ! -f "$SESSION_FILE" ]; then
    exit 0
fi

# Extract tool name and calculate character counts using python3
METRICS=$(echo "$INPUT" | python3 -c "
import sys, json

try:
    data = json.load(sys.stdin)
    tool_name = data.get('tool_name', 'Unknown')

    # Serialize input to get character count
    tool_input = json.dumps(data.get('tool_input', {}))

    # Output may be string or object (Claude Code PostToolUse field is 'tool_response')
    tool_output = data.get('tool_response', '')
    if not isinstance(tool_output, str):
        tool_output = json.dumps(tool_output)

    input_chars = len(tool_input)
    output_chars = len(tool_output)
    total = input_chars + output_chars

    print(f'{tool_name}|{input_chars}|{output_chars}|{total}')
except Exception as e:
    print(f'Unknown|0|0|0')
" 2>/dev/null || echo "Unknown|0|0|0")

TOOL_NAME=$(echo "$METRICS" | cut -d'|' -f1)
INPUT_CHARS=$(echo "$METRICS" | cut -d'|' -f2)
OUTPUT_CHARS=$(echo "$METRICS" | cut -d'|' -f3)
TOTAL_CHARS=$(echo "$METRICS" | cut -d'|' -f4)

# Skip if no significant content (less than 10 chars total)
if [ "$TOTAL_CHARS" -lt 10 ]; then
    exit 0
fi

NOW_TIME=$(date -u +"%H:%M:%S")

# Ensure Metrics section exists at the end of the file
if ! grep -q "^## Metrics$" "$SESSION_FILE" 2>/dev/null; then
    echo -e "\n## Metrics\n" >> "$SESSION_FILE"
fi

# Append metric entry (format: timestamp, tool, in chars, out chars, total)
echo "- \`[$NOW_TIME]\` **$TOOL_NAME** in:${INPUT_CHARS} out:${OUTPUT_CHARS} total:${TOTAL_CHARS}" >> "$SESSION_FILE"

exit 0
