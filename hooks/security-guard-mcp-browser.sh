#!/usr/bin/env bash
# security-guard-mcp-browser.sh
# Event: PreToolUse
# Matcher: mcp__playwright__
# Scope: Universal — fires in both main session and sub-agents
#
# Intercepts Playwright MCP browser tool calls before execution. Read-only
# tools (navigate/snapshot/screenshot/inspection) always pass. Interaction
# tools (click/type/fill_form/select_option/press_key/drag/hover/evaluate —
# browser_evaluate is ALWAYS interaction-class, no JS heuristic, per
# questions.md Q4) are gated: denied outright when
# browser_verification.allow_interactions is false (master kill-switch,
# downgradable by warn_only_mode), and denied against a production-labeled
# target (fail-safe default for any unmatched target, per Q3) unless a
# matching human confirmation has been recorded — that production
# confirm-gate is the sole denial in this guard warn_only_mode can never
# downgrade or bypass (Q1). See data-model.md for the full decision table.

set -uo pipefail

INPUT=$(cat)

# Defensive: malformed JSON must never crash this hook.
TOOL_NAME=$(echo "$INPUT" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data.get('tool_name', ''))
" 2>/dev/null || echo "")

# Defense-in-depth: only act on Playwright MCP tools even though the
# settings matcher already pre-filters. Everything else passes silently.
case "$TOOL_NAME" in
    *mcp__playwright__*) ;;
    *) exit 0 ;;
esac

SUFFIX="${TOOL_NAME#*mcp__playwright__}"

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
VAULT_DIR="$PROJECT_DIR/.smith/vault"
CURRENT_SESSION_FILE="$VAULT_DIR/.current-session"
CONFIG_FILE="$PROJECT_DIR/.smith/security-config.json"
TARGET_FILE="$VAULT_DIR/.mcp-browser-target"
CONFIRMED_FILE="$VAULT_DIR/.mcp-browser-confirmed"

# ---- tool classification (data-model.md §4 — exact lists, no heuristics) ----

is_read_only() {
    case "$1" in
        browser_navigate|browser_snapshot|browser_take_screenshot|browser_console_messages|browser_network_requests|browser_wait_for|browser_tabs) return 0 ;;
        *) return 1 ;;
    esac
}

is_interaction() {
    case "$1" in
        browser_click|browser_type|browser_fill_form|browser_select_option|browser_press_key|browser_drag|browser_hover|browser_evaluate) return 0 ;;
        *) return 1 ;;
    esac
}

# ---- logging (mirrors security-guard-bash.sh's log_security()) ----

log_security() {
    local action="$1" reason="$2"
    [ -f "$CURRENT_SESSION_FILE" ] || return 0
    local session_file
    session_file=$(cat "$CURRENT_SESSION_FILE" 2>/dev/null || echo "")
    [ -n "$session_file" ] && [ -f "$session_file" ] || return 0
    local now
    now=$(date -u +"%H:%M:%S")
    printf "\n### [%s] SECURITY: mcp_browser %s\n\n**Tool:** \`%s\`\n**Reason:** %s\n" \
        "$now" "$action" "$TOOL_NAME" "$reason" >> "$session_file"
}

# ---- response helpers (mirror security-guard-bash.sh's convention exactly) ----

approve() {
    cat << EOJSON
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow"
  }
}
EOJSON
    exit 0
}

# Downgradable deny — respects warn_only_mode (every denial in this guard
# except the production confirm-gate below).
deny_soft() {
    local reason="$1"
    log_security "blocked" "$reason"
    if [ "$WARN_ONLY" = "true" ]; then
        cat << EOJSON
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": "SMITH SECURITY WARNING (warn-only mode): $reason"
  }
}
EOJSON
        exit 0
    fi
    cat << EOJSON
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "SMITH SECURITY: $reason"
  }
}
EOJSON
    exit 2
}

# Non-bypassable deny — the FR-4 production confirm-gate (Q1).
deny_hard() {
    local reason="$1"
    log_security "blocked (non-bypassable production confirm-gate)" "$reason"
    cat << EOJSON
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "SMITH SECURITY: $reason"
  }
}
EOJSON
    exit 2
}

# ---- target classification + guard-owned state (data-model.md §3) ----

# localhost/127.0.0.1/::1 -> always staging; else prefix/host match against
# browser_verification.urls.production/.staging; unmatched -> unclassified
# (treated as production for gating, per Q3).
classify_url() {
    local url="$1"
    NAV_URL="$url" CONFIG_FILE="$CONFIG_FILE" python3 2>/dev/null <<'PYEOF' || echo "unclassified"
import os, json
from urllib.parse import urlparse
url = os.environ.get("NAV_URL", "") or ""
config_file = os.environ.get("CONFIG_FILE", "")
def hostname(u):
    try:
        return (urlparse(u).hostname or "").lower()
    except Exception:
        return ""
if not url:
    print("unclassified"); raise SystemExit(0)
if hostname(url) in ("localhost", "127.0.0.1", "::1"):
    print("staging"); raise SystemExit(0)
staging, production = [], []
if config_file and os.path.isfile(config_file):
    try:
        d = json.load(open(config_file))
        bv = d.get("browser_verification", {}) or {}
        urls = bv.get("urls", {}) or {}
        staging = urls.get("staging", []) or []
        production = urls.get("production", []) or []
    except Exception:
        staging, production = [], []
def matches(u, entries):
    uh = hostname(u)
    for e in entries:
        cand = (e.get("url", "") if isinstance(e, dict) else "") or ""
        if cand and (u.startswith(cand) or (uh and uh == hostname(cand))):
            return True
    return False
if matches(url, production):
    print("production")
elif matches(url, staging):
    print("staging")
else:
    print("unclassified")
PYEOF
}

# Best-effort write; never errors, never blocks the (already-approved) call.
write_target_state() {
    local url="$1" classification="$2"
    [ -d "$VAULT_DIR" ] || return 0
    NAV_URL="$url" NAV_CLASS="$classification" TARGET_FILE="$TARGET_FILE" python3 2>/dev/null <<'PYEOF' || true
import os, json
from datetime import datetime, timezone
target_file = os.environ.get("TARGET_FILE", "")
if target_file:
    out = {
        "url": os.environ.get("NAV_URL", ""),
        "classification": os.environ.get("NAV_CLASS", "unclassified"),
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    json.dump(out, open(target_file, "w"))
PYEOF
    return 0
}

# ================================ main ================================

if is_read_only "$SUFFIX"; then
    if [ "$SUFFIX" = "browser_navigate" ]; then
        NAV_URL=$(echo "$INPUT" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data.get('tool_input', {}).get('url', ''))
" 2>/dev/null || echo "")
        if [ -n "$NAV_URL" ]; then
            NAV_CLASS=$(classify_url "$NAV_URL")
            write_target_state "$NAV_URL" "$NAV_CLASS"
        fi
    fi
    approve
fi

if ! is_interaction "$SUFFIX"; then
    # Unrecognized mcp__playwright__ tool (not in data-model.md's lists) —
    # no classification exists; fall through rather than guessing.
    exit 0
fi

# Interaction tool. FR-6/NFR-1: absent vault, absent config, or malformed
# config JSON must never crash and must never block — silent no-op/allow.
CONFIG_VALID="false"
if [ -f "$CONFIG_FILE" ]; then
    CONFIG_VALID=$(python3 -c "
import json
try:
    json.load(open('$CONFIG_FILE'))
    print('true')
except Exception:
    print('false')
" 2>/dev/null || echo "false")
fi
[ -d "$VAULT_DIR" ] && [ "$CONFIG_VALID" = "true" ] || exit 0

WARN_ONLY=$(python3 -c "import json; d=json.load(open('$CONFIG_FILE')); print(str(d.get('warn_only_mode', False)).lower())" 2>/dev/null || echo "false")
ALLOW_INTERACTIONS=$(python3 -c "import json; d=json.load(open('$CONFIG_FILE')); bv=d.get('browser_verification', {}) or {}; print(str(bool(bv.get('allow_interactions', True))).lower())" 2>/dev/null || echo "true")

# Master kill-switch (FR-21/Q5) — applies regardless of target class.
if [ "$ALLOW_INTERACTIONS" = "false" ]; then
    deny_soft "Interaction tool '$TOOL_NAME' blocked. This project has browser_verification.allow_interactions set to false -- only read-only Playwright MCP tools (navigate, snapshot, screenshot, console/network inspection) may run. Read-only verification is unaffected."
fi

TARGET_URL=""
TARGET_CLASS="unclassified"
if [ -f "$TARGET_FILE" ]; then
    TARGET_URL=$(python3 -c "import json; d=json.load(open('$TARGET_FILE')); print(d.get('url',''))" 2>/dev/null || echo "")
    TARGET_CLASS=$(python3 -c "
import json
d = json.load(open('$TARGET_FILE'))
c = d.get('classification', 'unclassified')
print(c if c in ('staging', 'production', 'unclassified') else 'unclassified')
" 2>/dev/null || echo "unclassified")
fi

[ "$TARGET_CLASS" = "staging" ] && approve

# production, or unclassified (fail-safe default per Q3) — the
# non-bypassable production confirm-gate (FR-4/Q1).
CONFIRMED_URL=""
if [ -f "$CONFIRMED_FILE" ]; then
    CONFIRMED_URL=$(python3 -c "import json; d=json.load(open('$CONFIRMED_FILE')); print(d.get('url',''))" 2>/dev/null || echo "")
fi

if [ -n "$CONFIRMED_URL" ] && [ -n "$TARGET_URL" ] && [ "$CONFIRMED_URL" = "$TARGET_URL" ]; then
    approve
fi

DISPLAY_URL="$TARGET_URL"
[ -n "$DISPLAY_URL" ] || DISPLAY_URL="(no navigation target recorded this session)"

deny_hard "Interaction tool '$TOOL_NAME' blocked against production target '$DISPLAY_URL'. This target is listed as production in the project's staging/production URL table. Explicit human confirmation is required before any interaction tool may run against it -- stop and ask the user to confirm interaction is authorized for this target before retrying."
