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
#   Optional flag: --session <path> — read totals from <path> instead of the
#   resolved default. Takes precedence over every other source. Skills capture
#   their workflow's session-log path at start and pass it here so totals are
#   computed against the correct file even after a mid-workflow log rollover.
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
EXPLICIT_SESSION=""
# Argument parsing. Supported forms:
#   workflow-summary.sh                      (Stop-hook mode)
#   workflow-summary.sh --totals-only        (chat-block mode)
#   workflow-summary.sh --totals-only --session <path>
#   workflow-summary.sh --session <path> --totals-only
while [ "$#" -gt 0 ]; do
    case "$1" in
        --totals-only)
            TOTALS_ONLY=1
            shift
            ;;
        --session)
            EXPLICIT_SESSION="${2:-}"
            shift 2 2>/dev/null || shift
            ;;
        --session=*)
            EXPLICIT_SESSION="${1#--session=}"
            shift
            ;;
        *)
            shift
            ;;
    esac
done

if [ "$TOTALS_ONLY" = "0" ]; then
    # Stop-hook path: consume stdin (Claude Code pipes JSON). In --totals-only
    # mode we skip this so manual callers don't have to redirect /dev/null.
    INPUT=$(cat)
fi

VAULT_DIR="${CLAUDE_PROJECT_DIR:-.}/.smith/vault"
CURRENT_SESSION_PTR="$VAULT_DIR/.current-session"
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# ---------------------------------------------------------------------------
# resolve_session_file — choose which session log to read for totals.
#
# Precedence (highest first), so that totals survive a mid-workflow session
# rollover that repoints .current-session at a fresh, markerless file:
#   (a) --session <path>  — explicit CLI override; always wins if it exists.
#   (b) the `session_log:` field of an active-workflow marker:
#         .smith/vault/active-workflows/*.yaml
#       When exactly one marker carries a session_log, use it. When several do,
#       prefer the one whose `branch:` matches the current git branch; if none
#       match, fall through to (c).
#   (c) .smith/vault/.current-session — the historical default (fully
#       backwards-compatible fallback).
# Prints the resolved path to stdout, or nothing if none resolve.
# ---------------------------------------------------------------------------
resolve_session_file() {
    # (a) explicit override
    if [ -n "$EXPLICIT_SESSION" ]; then
        if [ -f "$EXPLICIT_SESSION" ]; then
            printf '%s' "$EXPLICIT_SESSION"
            return 0
        fi
        # An explicit path that doesn't exist still wins (caller intent); the
        # Python layer will report it as not-found rather than silently using
        # the wrong file.
        printf '%s' "$EXPLICIT_SESSION"
        return 0
    fi

    # (b) active-workflow marker(s) carrying session_log:
    local wf_dir="$VAULT_DIR/active-workflows"
    if [ -d "$wf_dir" ]; then
        local cur_branch
        cur_branch=$(cd "$PROJECT_ROOT" 2>/dev/null && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
        local only_log="" only_count=0 branch_log=""
        local marker log mbranch
        for marker in "$wf_dir"/*.yaml; do
            [ -f "$marker" ] || continue
            log=$(awk -F': *' '/^[[:space:]]*session_log:/ {sub(/^[^:]*:[[:space:]]*/, ""); gsub(/^"|"$/, ""); print; exit}' "$marker")
            [ -n "$log" ] || continue
            only_count=$((only_count + 1))
            only_log="$log"
            mbranch=$(awk -F': *' '/^[[:space:]]*branch:/ {sub(/^[^:]*:[[:space:]]*/, ""); gsub(/^"|"$/, ""); print; exit}' "$marker")
            if [ -n "$cur_branch" ] && [ "$mbranch" = "$cur_branch" ]; then
                branch_log="$log"
            fi
        done
        if [ "$only_count" -eq 1 ] && [ -n "$only_log" ]; then
            printf '%s' "$only_log"
            return 0
        fi
        if [ "$only_count" -gt 1 ] && [ -n "$branch_log" ]; then
            printf '%s' "$branch_log"
            return 0
        fi
        # multiple markers but none match current branch → fall through to (c)
    fi

    # (c) backwards-compatible fallback
    if [ -f "$CURRENT_SESSION_PTR" ]; then
        cat "$CURRENT_SESSION_PTR"
        return 0
    fi
    return 1
}

SESSION_FILE=$(resolve_session_file)

# Silent exit if nothing resolved (vault not initialized and no override).
[ -n "$SESSION_FILE" ] || exit 0

# In Stop-hook mode the file must exist (we read gates from it and append to
# it). In --totals-only mode we let a missing file fall through to Python so it
# can emit the loud not-found diagnostic rather than silently exiting.
if [ "$TOTALS_ONLY" = "0" ] && [ ! -f "$SESSION_FILE" ]; then
    exit 0
fi

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
#
# Resolve the hooks dir that contains workflow_summary_lib.py. Priority:
#   1. $CLAUDE_HOOKS_DIR if it contains the lib
#   2. ~/.claude/hooks/ if it contains the lib
#   3. Sibling dir of this script (repo checkout / bundled use)
# This lets a single copy of the .sh live in either location.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOOK_DIR=""
for candidate in "${CLAUDE_HOOKS_DIR:-}" "$HOME/.claude/hooks" "$SCRIPT_DIR"; do
    if [ -n "$candidate" ] && [ -f "$candidate/workflow_summary_lib.py" ]; then
        HOOK_DIR="$candidate"
        break
    fi
done

if [ -z "$HOOK_DIR" ]; then
    echo "workflow-summary.sh: cannot locate workflow_summary_lib.py (checked \$CLAUDE_HOOKS_DIR, ~/.claude/hooks, $SCRIPT_DIR)" >&2
    exit 0
fi

SESSION_FILE="$SESSION_FILE" \
  PROJECT_ROOT="$PROJECT_ROOT" \
  TOTALS_ONLY="$TOTALS_ONLY" \
  PYTHONPATH="$HOOK_DIR" \
  python3 -c "import workflow_summary_lib as L; import sys; sys.exit(L.main())"

exit 0
