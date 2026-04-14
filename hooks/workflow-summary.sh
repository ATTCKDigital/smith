#!/usr/bin/env bash
# workflow-summary.sh
# Event: Stop (default) — or invoked manually with --totals-only for inline chat use.
# Scope: Main session only
#
# Default mode (Stop hook):
#   Appends a "=== Workflow Summary ===" block to the current session log when a
#   primary workflow (smith-new, smith-bugfix, smith-debug) completes. Gated by:
#     1. Session log has a /smith-(new|bugfix|debug) invocation entry
#     2. Session log does NOT already contain "=== Workflow Summary ==="
#     3. No active-workflows/*.yaml file exists (workflow cleaned up)
#
# --totals-only mode (manual invocation from a skill):
#   Prints a 3-line chat block to stdout, no session-log write, no gating:
#     Token Usage: <N> normalized
#     Est. cost: $<X> USD
#     Active duration: <t> (total elapsed <T>)
#   Skills invoke this to include totals inline in their final chat message
#   BEFORE Stop fires (Stop-hook stdout doesn't reach the preceding chat bubble).
#
# Computations are implemented in hooks/workflow_summary_lib.py. This script is
# a thin wrapper that enforces gates, sets env vars, and hands off to Python.
#
# Inputs (best-effort — all missing sources degrade gracefully):
#   - $VAULT_DIR/.current-session → session log path
#   - Session log ## Metrics section (tool timestamps for gap-detected active duration)
#   - Session log ### Subagent completed blocks (extended v2 schema, legacy v1 fallback)
#   - ~/.claude/projects/<slug>/<session-id>.jsonl for parent-session tokens
#   - hooks/pricing.json for per-model USD rates
#
# Output (per specs/003-accurate-workflow-summary/contracts/workflow-summary-cli.md):
#   - --totals-only: 3 lines to stdout. No session-log write.
#   - Default: audit block appended to session log; echoed to stdout.
#   - Exit code: 0 in all v1 paths (including silent exit when gates unmet).

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

# Hand off to the Python library.
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
SESSION_FILE="$SESSION_FILE" \
  PROJECT_ROOT="$PROJECT_ROOT" \
  TOTALS_ONLY="$TOTALS_ONLY" \
  PYTHONPATH="$HOOK_DIR" \
  python3 -c "import workflow_summary_lib as L; import sys; sys.exit(L.main())"

exit 0
