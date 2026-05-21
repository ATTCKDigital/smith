#!/usr/bin/env bash
# test_context_loader.sh — covers the UserPromptSubmit detection +
# injection logic in hooks/context-loader.sh.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$REPO_ROOT/hooks/context-loader.sh"

if [ ! -x "$HOOK" ]; then
    echo "FAIL: hook not executable: $HOOK"
    exit 1
fi

TMP_PROJECT="$(mktemp -d -t cl-test.XXXXXX)"
trap 'rm -rf "$TMP_PROJECT"' EXIT

mkdir -p "$TMP_PROJECT/.smith/vault/sessions"
mkdir -p "$TMP_PROJECT/.smith/index"
echo "# Test session" > "$TMP_PROJECT/.smith/vault/sessions/2026-05-20-test.md"
echo "# Project Manifest" > "$TMP_PROJECT/.smith/index/manifest.md"

PASS=0
FAIL=0

assert() {
    if [ "$2" = "true" ]; then
        echo "PASS $1"
        PASS=$((PASS+1))
    else
        echo "FAIL $1"
        FAIL=$((FAIL+1))
    fi
}

# --- Test 1: slash command triggers injection ----------------------------
OUT=$(echo "{\"prompt\":\"/smith-bugfix fix the foo\",\"session_id\":\"s1\",\"cwd\":\"$TMP_PROJECT\"}" \
    | bash "$HOOK" 2>/dev/null || true)
if echo "$OUT" | grep -q "smith-context-injection"; then
    assert "slash command triggers injection" true
else
    assert "slash command triggers injection" false
fi

# --- Test 2: NL trigger triggers injection -------------------------------
OUT=$(echo "{\"prompt\":\"let's smith this thing\",\"session_id\":\"s2\",\"cwd\":\"$TMP_PROJECT\"}" \
    | bash "$HOOK" 2>/dev/null || true)
if echo "$OUT" | grep -q "smith-new"; then
    assert "NL trigger 'lets smith this' → smith-new" true
else
    assert "NL trigger 'lets smith this' → smith-new" false
fi

# --- Test 3: plain question → no injection (zero overhead) --------------
OUT=$(echo "{\"prompt\":\"what is the meaning of life\",\"session_id\":\"s3\",\"cwd\":\"$TMP_PROJECT\"}" \
    | bash "$HOOK" 2>/dev/null || true)
[ -z "$OUT" ] && assert "plain question → no injection" true \
    || assert "plain question → no injection (got: $OUT)" false

# --- Test 4: /smith-help → injection with empty body --------------------
OUT=$(echo "{\"prompt\":\"/smith-help queue\",\"session_id\":\"s4\",\"cwd\":\"$TMP_PROJECT\"}" \
    | bash "$HOOK" 2>/dev/null || true)
if echo "$OUT" | grep -q "Navigator disabled\|No vault sections"; then
    assert "/smith-help injection is empty-body" true
else
    assert "/smith-help injection is empty-body" false
fi

# --- Test 5: malformed JSON → exit 0 ------------------------------------
RC=0
echo 'not-json' | bash "$HOOK" >/dev/null 2>&1 || RC=$?
[ "$RC" -eq 0 ] && assert "malformed JSON exits 0" true \
    || assert "malformed JSON exits 0 (rc=$RC)" false

# --- Test 6: missing manifest → soft warning emitted ONCE per session ----
rm "$TMP_PROJECT/.smith/index/manifest.md"
OUT1=$(echo "{\"prompt\":\"/smith-bugfix fix\",\"session_id\":\"warn-1\",\"cwd\":\"$TMP_PROJECT\"}" \
    | bash "$HOOK" 2>/dev/null || true)
OUT2=$(echo "{\"prompt\":\"/smith-bugfix fix again\",\"session_id\":\"warn-1\",\"cwd\":\"$TMP_PROJECT\"}" \
    | bash "$HOOK" 2>/dev/null || true)
if echo "$OUT1" | grep -q "Manifest not initialized"; then
    assert "first call emits soft warning" true
else
    assert "first call emits soft warning" false
fi
if echo "$OUT2" | grep -q "Manifest not initialized"; then
    assert "second call suppresses warning" false
else
    assert "second call suppresses warning" true
fi

# --- Test 7: 4-tier resolution observable in log -------------------------
HOOKS_LOG="$HOME/.smith/logs/hooks.log"
if [ -f "$HOOKS_LOG" ] && grep -q "tiers=" "$HOOKS_LOG"; then
    assert "tier breakdown logged" true
else
    assert "tier breakdown logged" false
fi

echo
echo "context-loader tests: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
