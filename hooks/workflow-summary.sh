#!/usr/bin/env bash
# workflow-summary.sh
# Event: Stop (default) — or invoked manually with --totals-only for inline chat use.
# Scope: Main session only
#
# Default mode (Stop hook):
#   Emits a "=== Workflow Summary ===" block to the current session log at the end
#   of a primary workflow (smith-new, smith-bugfix, smith-debug). Idempotent and
#   safe to run on every Stop: will only emit once per workflow.
#
#   Gating conditions (all must be true to emit):
#     1. Session log has a /smith-(new|bugfix|debug) invocation entry
#     2. Session log does NOT already contain "=== Workflow Summary ==="
#     3. No active-workflows/<branch>.yaml file exists (workflow cleaned up)
#
# --totals-only mode (manual invocation from a skill):
#   Prints just two lines to stdout — no session-log write, no gating:
#     Total tokens used: ~<n>
#     Total duration: <duration>
#   Intended for the skill to include inline in its final user-facing message
#   BEFORE Stop fires (Stop-hook stdout does not reach the preceding chat bubble).
#
# Aggregates:
#   - Main session: tool calls count, estimated tokens (chars/4) from Metrics entries
#   - Subagents: count, total_tokens, total tool_uses, total duration_ms
#   - Duration: session file's timestamp in filename to now

set -euo pipefail

TOTALS_ONLY=0
if [ "${1:-}" = "--totals-only" ]; then
    TOTALS_ONLY=1
else
    # Stop-hook path: consume stdin (Claude Code pipes JSON). In --totals-only
    # mode we skip this so manual callers don't have to redirect /dev/null.
    INPUT=$(cat)
fi

VAULT_DIR="${CLAUDE_PROJECT_DIR:-.}/.smith/vault"
CURRENT_SESSION_PTR="$VAULT_DIR/.current-session"

# Silent exit if vault not initialized
[ -f "$CURRENT_SESSION_PTR" ] || exit 0

SESSION_FILE=$(cat "$CURRENT_SESSION_PTR")
[ -f "$SESSION_FILE" ] || exit 0

PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"

if [ "$TOTALS_ONLY" = "0" ]; then
    # Guard: already emitted?
    if grep -q "^=== Workflow Summary ===" "$SESSION_FILE" 2>/dev/null; then
        exit 0
    fi

    # Guard: is this session a primary workflow?
    if ! grep -qE "^### \[[0-9:]+\] /smith-(new|bugfix|debug) (invoked|invocation)" "$SESSION_FILE" 2>/dev/null; then
        exit 0
    fi

    # Guard: active-workflows file must NOT exist (workflow cleaned up).
    # We check the current branch's file; if we can't determine the branch, skip.
    BRANCH=$(cd "$PROJECT_ROOT" 2>/dev/null && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")

    if [ -n "$BRANCH" ]; then
        SAFE_BRANCH=$(echo "$BRANCH" | sed 's/[^a-zA-Z0-9._-]/-/g')
        if [ -f "$VAULT_DIR/active-workflows/${SAFE_BRANCH}.yaml" ]; then
            exit 0
        fi
    fi

    # Also guard against "any active-workflow file exists" as a secondary safety net
    # for workflows launched from worktrees where branch detection may differ.
    if [ -d "$VAULT_DIR/active-workflows" ]; then
        ACTIVE_COUNT=$(find "$VAULT_DIR/active-workflows" -maxdepth 1 -name '*.yaml' 2>/dev/null | wc -l | tr -d ' ')
        if [ "$ACTIVE_COUNT" != "0" ]; then
            exit 0
        fi
    fi
fi

SESSION_FILE="$SESSION_FILE" PROJECT_ROOT="$PROJECT_ROOT" TOTALS_ONLY="$TOTALS_ONLY" python3 <<'PYEOF'
import os
import re
import sys
import subprocess
from datetime import datetime, timezone

session_file = os.environ['SESSION_FILE']
project_root = os.environ.get('PROJECT_ROOT', '.')
totals_only = os.environ.get('TOTALS_ONLY', '0') == '1'

with open(session_file, 'r', encoding='utf-8') as f:
    content = f.read()

# Identify which primary workflow ran (use first invocation in log)
invoke_match = re.search(
    r'### \[(\d{2}:\d{2}:\d{2})\] /smith-(new|bugfix|debug) (invoked|invocation)',
    content
)
if not invoke_match:
    sys.exit(0)

start_time_str = invoke_match.group(1)
workflow_type = invoke_match.group(2)

# Aggregate main-session tool calls from Metrics entries
# Format: - `[HH:MM:SS]` **Tool** in:N out:N total:N
metrics_total_chars = 0
metrics_count = 0
for m in re.finditer(r'- `\[\d{2}:\d{2}:\d{2}\]` \*\*\w+\*\*.*?total:(\d+)', content):
    metrics_total_chars += int(m.group(1))
    metrics_count += 1

estimated_tokens = metrics_total_chars // 4

# Aggregate subagent completions
sa_pattern = re.compile(
    r'### \[\d{2}:\d{2}:\d{2}\] Subagent completed\n\n'
    r'\*\*Metrics:\*\*\n'
    r'- total_tokens: (\d+)\n'
    r'- tool_uses: (\d+)\n'
    r'- duration_ms: (\d+)'
)
sa_matches = sa_pattern.findall(content)
sa_count = len(sa_matches)
sa_tokens = sum(int(t) for t, _, _ in sa_matches)
sa_tools = sum(int(u) for _, u, _ in sa_matches)
sa_duration_ms = sum(int(d) for _, _, d in sa_matches)

# Duration: session filename YYYY-MM-DD_HHMMSS.md gives start; end is "now"
# (this hook fires at Stop immediately after workflow cleanup, per the
# active-workflows guard).
fn = os.path.basename(session_file).replace('.md', '')
duration_str = 'unknown'
try:
    start_dt = datetime.strptime(fn, '%Y-%m-%d_%H%M%S').replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - start_dt
    total_sec = int(delta.total_seconds())
    hours, rem = divmod(total_sec, 3600)
    mins, secs = divmod(rem, 60)
    if hours:
        duration_str = f"{hours}h{mins}m{secs}s"
    elif mins:
        duration_str = f"{mins}m{secs}s"
    else:
        duration_str = f"{secs}s"
except ValueError:
    pass

# Files changed: git diff vs main (best effort — may be on main already)
files_changed = []
try:
    result = subprocess.run(
        ['git', 'diff', '--name-only', 'main..HEAD'],
        cwd=project_root, capture_output=True, text=True, timeout=5
    )
    if result.returncode == 0:
        files_changed = [line.strip() for line in result.stdout.splitlines() if line.strip()]
except (subprocess.SubprocessError, FileNotFoundError, OSError):
    pass

files_section = ''
if files_changed:
    files_section = '\n'.join(f'  - {f}' for f in files_changed[:30])
    if len(files_changed) > 30:
        files_section += f'\n  - ... ({len(files_changed) - 30} more)'
else:
    files_section = '  (none detected — may already be merged or no diff)'

sa_duration_display = f"{sa_duration_ms}ms ({sa_duration_ms // 1000}s)" if sa_duration_ms else "0ms"

# --totals-only: print just the two lines the user wants in chat and exit.
# No session-log write, no full summary block.
if totals_only:
    combined_tokens = estimated_tokens + sa_tokens
    print(f"Total tokens used: ~{combined_tokens:,}")
    print(f"Total duration: {duration_str}")
    sys.exit(0)

summary = f"""

=== Workflow Summary ===

Workflow: /smith-{workflow_type}
Started: {start_time_str}
Duration: {duration_str}

Main Session:
- Estimated tokens: ~{estimated_tokens:,}
- Tool calls: {metrics_count}

Subagents:
- Count: {sa_count}
- Total tokens: {sa_tokens:,}
- Total tool uses: {sa_tools}
- Total duration: {sa_duration_display}

Files Changed:
{files_section}

"""

with open(session_file, 'a', encoding='utf-8') as f:
    f.write(summary)

# Stdout is shown in the transcript per Claude Code hook docs
print(summary)
PYEOF

exit 0
