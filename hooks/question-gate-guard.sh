#!/usr/bin/env bash
# question-gate-guard.sh
# Event: PreToolUse
# Matcher: AskUserQuestion
# Scope: Universal — fires in both main session and sub-agents.
#
# Suppresses the interactive AskUserQuestion popup in favor of Smith's markdown
# Q&A contract (see the `smith-question` skill). Behavior is config-driven via
# `.smith/config.json` -> question_gate.mode:
#
#   deny            (shipped default) — block the popup; the deny reason redirects
#                   the model to present the question as markdown.
#   warn            — allow the popup but attach a reminder of the Q&A contract.
#   workflow-gated  — deny only when a Smith workflow marker is active; otherwise
#                   allow (freeform, non-workflow sessions keep the popup).
#   off             — inert; allow the popup.
#
# FAIL-OPEN: a missing / unreadable / unparseable config, an absent question_gate
# key, or an unrecognized mode all resolve to "off" (allow). A globally-installed
# guard must never make a project unable to ask the user anything.

set -uo pipefail

INPUT=$(cat)

# ---------- act only on AskUserQuestion ----------

TOOL_NAME=$(printf '%s' "$INPUT" | python3 -c "
import sys, json
try:
    print(json.load(sys.stdin).get('tool_name', ''))
except Exception:
    print('')
" 2>/dev/null || echo "")

if [ "$TOOL_NAME" != "AskUserQuestion" ]; then
    exit 0
fi

# ---------- locate the project root ----------
#
# Mirror workflow-gate.sh: from inside a worktree, `git rev-parse
# --git-common-dir` points at the primary repo's .git, whose dirname is the
# project root (where .smith/config.json and the active-workflow markers live).
# Falls back to $CLAUDE_PROJECT_DIR / $PWD outside git.

RESOLVED_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
GIT_COMMON_DIR=$(git -C "$RESOLVED_DIR" rev-parse --git-common-dir 2>/dev/null || true)
if [ -n "$GIT_COMMON_DIR" ]; then
    case "$GIT_COMMON_DIR" in
        /*) PROJECT_DIR=$(dirname "$GIT_COMMON_DIR") ;;
        *)  PROJECT_DIR=$(cd "$RESOLVED_DIR" && cd "$(dirname "$GIT_COMMON_DIR")" 2>/dev/null && pwd) ;;
    esac
    : "${PROJECT_DIR:=$RESOLVED_DIR}"
else
    PROJECT_DIR="$RESOLVED_DIR"
fi

CONFIG_FILE="$PROJECT_DIR/.smith/config.json"

# ---------- resolve mode (fail-open to "off") ----------

MODE="off"
if [ -f "$CONFIG_FILE" ]; then
    MODE=$(python3 -c "
import json
try:
    with open('$CONFIG_FILE') as f:
        d = json.load(f)
    qg = d.get('question_gate') or {}
    m = qg.get('mode', 'off')
    print(m if m in ('deny', 'warn', 'workflow-gated', 'off') else 'off')
except Exception:
    print('off')
" 2>/dev/null || echo "off")
fi

# ---------- shared reason text ----------

REASON="Interactive questions are disabled by Smith (question_gate). Present the \
question as markdown instead: Context -> Options (each with pros/cons) -> a \
Recommended option with reasoning, one question at a time, then wait for the \
answer. See the /smith-question skill for the full contract."

emit_deny() {
    cat << EOJSON
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "SMITH question_gate: $REASON"
  }
}
EOJSON
    exit 2
}

emit_warn() {
    cat << EOJSON
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": "SMITH question_gate (warn): $REASON"
  }
}
EOJSON
    exit 0
}

# ---------- is a Smith workflow marker active? (workflow-gated mode) ----------

marker_present() {
    local active_dir="$PROJECT_DIR/.smith/vault/active-workflows"
    [ -d "$active_dir" ] || return 1
    shopt -s nullglob
    local markers=( "$active_dir"/*.yaml )
    shopt -u nullglob
    [ "${#markers[@]}" -gt 0 ]
}

# ---------- dispatch ----------

case "$MODE" in
    deny)
        emit_deny
        ;;
    warn)
        emit_warn
        ;;
    workflow-gated)
        if marker_present; then
            emit_deny
        fi
        exit 0
        ;;
    off|*)
        exit 0
        ;;
esac

exit 0
