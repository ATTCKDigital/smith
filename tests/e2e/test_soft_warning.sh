#!/usr/bin/env bash
# tests/e2e/test_soft_warning.sh
#
# T105 — Soft-warning fires once when the manifest is missing, then is
# suppressed for the rest of the session.
#
# Verifies:
#   - First Smith-skill prompt → soft warning emitted in additionalContext
#   - .smith/vault/.warned-manifest-missing-<session-id> marker created
#   - Second prompt with the same session_id → no warning (silent)
#   - Different session_id → warning appears again (per-session, not
#     per-project)

set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
HOOK="${REPO_ROOT}/hooks/context-loader.sh"

if [ ! -x "$HOOK" ]; then
    echo "FAIL: hook not executable: $HOOK"
    exit 1
fi

TMPDIR_TEST="/tmp/smith-e2e-warn-$$"
# vault present, but NOT .smith/index/ → triggers soft warning path.
mkdir -p "$TMPDIR_TEST/.smith/vault/sessions"
trap 'rm -rf "$TMPDIR_TEST"' EXIT

PASS=0
FAIL=0
TEST_NAME="T105-soft-warning"

pass() { printf '  PASS %s\n' "$1"; PASS=$((PASS+1)); }
fail() { printf '  FAIL %s\n' "$1" >&2; FAIL=$((FAIL+1)); }

echo "[$TEST_NAME] setup: $TMPDIR_TEST"

SESSION="e2e-t105-A"
INPUT1='{"prompt":"/smith-bugfix something","session_id":"'"$SESSION"'","cwd":"'"$TMPDIR_TEST"'"}'

OUT1="$(echo "$INPUT1" | bash "$HOOK" 2>/dev/null)"
if echo "$OUT1" | grep -q "Manifest not initialized"; then
    pass "first prompt emits soft warning"
else
    fail "expected 'Manifest not initialized' in first prompt; got: $OUT1"
fi

MARKER="$TMPDIR_TEST/.smith/vault/.warned-manifest-missing-$SESSION"
if [ -f "$MARKER" ]; then
    pass "marker file created: $MARKER"
else
    fail "marker not created: $MARKER"
fi

# Second prompt, same session_id → no warning, but injection still happens.
OUT2="$(echo "$INPUT1" | bash "$HOOK" 2>/dev/null)"
if echo "$OUT2" | grep -q "Manifest not initialized"; then
    fail "second prompt should suppress warning; got: $OUT2"
else
    pass "second prompt suppresses warning"
fi

# Different session_id → warning reappears (different marker).
INPUT3='{"prompt":"/smith-bugfix something else","session_id":"e2e-t105-B","cwd":"'"$TMPDIR_TEST"'"}'
OUT3="$(echo "$INPUT3" | bash "$HOOK" 2>/dev/null)"
if echo "$OUT3" | grep -q "Manifest not initialized"; then
    pass "new session emits warning again"
else
    fail "new session should emit warning; got: $OUT3"
fi

MARKER_B="$TMPDIR_TEST/.smith/vault/.warned-manifest-missing-e2e-t105-B"
if [ -f "$MARKER_B" ]; then
    pass "second marker file created"
else
    fail "second marker not created"
fi

echo
echo "[$TEST_NAME] PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
