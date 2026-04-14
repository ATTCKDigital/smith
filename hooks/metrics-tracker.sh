#!/usr/bin/env bash
# metrics-tracker.sh
# Event: PostToolUse
# Matcher: *
# Scope: Universal (main session + sub-agents)
#
# Logs tool input/output character counts to the session log for token estimation.
# Token estimate = total_chars / 4
#
# Also appends a per-tool identifier in parentheses so token-use audits can see
# which file/command/pattern contributed to a heavy entry:
#   - Read / Write / Edit / NotebookEdit → file_path (relative to project dir if
#     possible, else basename)
#   - Bash → command (first ~60 chars, newlines collapsed)
#   - Grep / Glob → pattern
#   - Other tools → no identifier
#
# Appends entries to the session log's Metrics section. At workflow end, the
# workflow-summary Stop hook aggregates these entries for the final summary.

set -euo pipefail

INPUT=$(cat)

VAULT_DIR="${CLAUDE_PROJECT_DIR:-.}/.smith/vault"
CURRENT_SESSION_FILE="$VAULT_DIR/.current-session"

[ -f "$CURRENT_SESSION_FILE" ] || exit 0

SESSION_FILE=$(cat "$CURRENT_SESSION_FILE")
[ -f "$SESSION_FILE" ] || exit 0

# Let python build the complete log line (including optional identifier). Avoids
# pipe-delimited parsing back in bash, which is fragile when identifiers contain
# pipes (e.g., Bash commands piping output).
LOG_LINE=$(HOOK_INPUT="$INPUT" CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-}" python3 2>/dev/null <<'PYEOF'
import os
import sys
import json
from datetime import datetime, timezone


def extract_identifier(tool_name, tool_input_obj, project_dir):
    if not isinstance(tool_input_obj, dict):
        return ''

    if tool_name in ('Read', 'Write', 'Edit', 'NotebookEdit'):
        path = tool_input_obj.get('file_path') or tool_input_obj.get('notebook_path') or ''
        if not path:
            return ''
        if project_dir and path.startswith(project_dir + '/'):
            return path[len(project_dir) + 1:]
        if os.path.isabs(path):
            return os.path.basename(path)
        return path

    if tool_name == 'Bash':
        cmd = tool_input_obj.get('command') or ''
        cmd = cmd.replace('\n', ' ').replace('\r', '').strip()
        if len(cmd) > 60:
            cmd = cmd[:60] + '…'
        return cmd

    if tool_name in ('Grep', 'Glob'):
        return tool_input_obj.get('pattern') or ''

    return ''


try:
    data = json.loads(os.environ.get('HOOK_INPUT', '{}'))
except json.JSONDecodeError:
    sys.exit(0)

tool_name = data.get('tool_name', 'Unknown')

tool_input_raw = data.get('tool_input', {})
tool_input_serialized = json.dumps(tool_input_raw) if not isinstance(tool_input_raw, str) else tool_input_raw

tool_output = data.get('tool_response', '')
if not isinstance(tool_output, str):
    tool_output = json.dumps(tool_output)

input_chars = len(tool_input_serialized)
output_chars = len(tool_output)
total = input_chars + output_chars

# Skip trivial entries
if total < 10:
    sys.exit(0)

identifier = extract_identifier(
    tool_name,
    tool_input_raw,
    os.environ.get('CLAUDE_PROJECT_DIR', '').rstrip('/'),
)

now_time = datetime.now(timezone.utc).strftime('%H:%M:%S')

line = f"- `[{now_time}]` **{tool_name}** in:{input_chars} out:{output_chars} total:{total}"
if identifier:
    line += f" ({identifier})"

print(line)
PYEOF
)

# Python exits silently on trivial entries, json errors, etc.
[ -z "$LOG_LINE" ] && exit 0

# Ensure Metrics section exists
if ! grep -q "^## Metrics$" "$SESSION_FILE" 2>/dev/null; then
    printf '\n## Metrics\n\n' >> "$SESSION_FILE"
fi

echo "$LOG_LINE" >> "$SESSION_FILE"

exit 0
