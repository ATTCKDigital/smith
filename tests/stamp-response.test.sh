#!/usr/bin/env bash
# stamp-response.test.sh — regression tests for the Stop-hook response stamp.
#
# The stamp silently disappeared once because the hook wrote it to PLAIN stdout.
# Claude Code surfaces plain hook stdout only for UserPromptSubmit,
# UserPromptExpansion, SessionStart and PostModelSwitch; for Stop it goes to the
# debug log only. The hook must therefore emit JSON with a `systemMessage` field.
#
# These tests lock in that contract plus the hook's safeguards.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HOOK="$REPO_ROOT/hooks/stamp-response.sh"
PASS=0
FAIL=0

assert() {
    if [ "$2" = "true" ]; then
        echo "PASS $1"; PASS=$((PASS+1))
    else
        echo "FAIL $1"; FAIL=$((FAIL+1))
    fi
}

# Build a Stop-event payload with correctly escaped JSON.
payload() {
    CWD="$1" ACTIVE="$2" MSG="$3" python3 -c '
import json, os
print(json.dumps({
    "hook_event_name": "Stop",
    "cwd": os.environ["CWD"],
    "stop_hook_active": os.environ["ACTIVE"] == "true",
    "last_assistant_message": os.environ["MSG"],
}))'
}

REPO_CWD="$REPO_ROOT"
NONGIT_CWD="$(mktemp -d -t stamp-nongit.XXXXXX)"
trap 'rm -rf "$NONGIT_CWD"' EXIT

# --- Test 1: a normal turn emits a systemMessage, never bare stdout -------
OUT=$(payload "$REPO_CWD" false "Here is my answer." | bash "$HOOK" 2>/dev/null)
RC=$?
FIELD=$(printf '%s' "$OUT" | python3 -c '
import sys, json
try:
    print(json.load(sys.stdin).get("systemMessage", ""))
except Exception:
    print("")' 2>/dev/null)
[ "$RC" -eq 0 ] && assert "exits 0 on a normal turn" true || assert "exits 0 on a normal turn" false
printf '%s' "$OUT" | python3 -c 'import sys,json; json.load(sys.stdin)' 2>/dev/null \
    && assert "emits valid JSON (not plain stdout)" true \
    || assert "emits valid JSON (not plain stdout)" false
printf '%s' "$FIELD" | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2} — .+$' \
    && assert "systemMessage carries a well-formed stamp with branch" true \
    || assert "systemMessage carries a well-formed stamp with branch" false

# --- Test 2: must NOT block the stop -------------------------------------
printf '%s' "$OUT" | grep -q '"decision"' \
    && assert "never returns a blocking decision" false \
    || assert "never returns a blocking decision" true
printf '%s' "$OUT" | grep -q 'additionalContext' \
    && assert "never returns additionalContext (would loop the turn)" false \
    || assert "never returns additionalContext (would loop the turn)" true

# --- Test 3: anti-recursion guard ----------------------------------------
OUT=$(payload "$REPO_CWD" true "Here is my answer." | bash "$HOOK" 2>/dev/null)
[ -z "$OUT" ] && assert "silent when stop_hook_active=true" true \
    || assert "silent when stop_hook_active=true" false

# --- Test 4: idempotency — no double stamp -------------------------------
OUT=$(payload "$REPO_CWD" false "Done.
2026-09-14 12:00:00 — main" | bash "$HOOK" 2>/dev/null)
[ -z "$OUT" ] && assert "no double-stamp when text already ends stamped" true \
    || assert "no double-stamp when text already ends stamped" false

OUT=$(payload "$NONGIT_CWD" false "ok
2026-09-14 12:00:00" | bash "$HOOK" 2>/dev/null)
[ -z "$OUT" ] && assert "no double-stamp for a bare-timestamp stamp" true \
    || assert "no double-stamp for a bare-timestamp stamp" false

# --- Test 5: branch fallback outside a git repo --------------------------
OUT=$(payload "$NONGIT_CWD" false "hi" | bash "$HOOK" 2>/dev/null)
FIELD=$(printf '%s' "$OUT" | python3 -c '
import sys, json
try:
    print(json.load(sys.stdin).get("systemMessage", ""))
except Exception:
    print("")' 2>/dev/null)
printf '%s' "$FIELD" | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$' \
    && assert "falls back to a bare timestamp outside a git repo" true \
    || assert "falls back to a bare timestamp outside a git repo" false

# --- Test 6: best-effort — malformed input still exits 0 -----------------
printf 'not json at all' | bash "$HOOK" >/dev/null 2>&1
[ $? -eq 0 ] && assert "exits 0 on malformed input" true \
    || assert "exits 0 on malformed input" false
printf '' | bash "$HOOK" >/dev/null 2>&1
[ $? -eq 0 ] && assert "exits 0 on empty input" true \
    || assert "exits 0 on empty input" false

# --- Test 7: multiline text with escaped newlines is parsed --------------
OUT=$(payload "$REPO_CWD" false "line one
line two
no stamp here" | bash "$HOOK" 2>/dev/null)
printf '%s' "$OUT" | grep -q '"systemMessage"' \
    && assert "stamps multiline unstamped text" true \
    || assert "stamps multiline unstamped text" false

echo
echo "stamp-response tests: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
