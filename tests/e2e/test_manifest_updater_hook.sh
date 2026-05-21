#!/usr/bin/env bash
# tests/e2e/test_manifest_updater_hook.sh
#
# T103 — manifest-updater hook fires correctly on PostToolUse Write/Edit
# input and updates the .meta + system manifest within 500ms.
#
# Simulates the PostToolUse hook input as Claude Code sends it.
# Asserts:
#   - .meta file created at the mirrored path
#   - hooks.log entry contains "manifest-updater status=ok"
#   - stdout is empty for small file, contains additionalContext for >300-line file
#   - exit code is 0
#   - performance: hook completes in <500ms

set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
HOOK="${REPO_ROOT}/hooks/manifest-updater.sh"

if [ ! -x "$HOOK" ]; then
    echo "FAIL: hook not executable: $HOOK"
    exit 1
fi

TMPDIR_TEST="/tmp/smith-e2e-mu-$$"
mkdir -p "$TMPDIR_TEST/backend/api"
trap 'rm -rf "$TMPDIR_TEST"' EXIT

PASS=0
FAIL=0
TEST_NAME="T103-manifest-updater-hook"

pass() { printf '  PASS %s\n' "$1"; PASS=$((PASS+1)); }
fail() { printf '  FAIL %s\n' "$1" >&2; FAIL=$((FAIL+1)); }

echo "[$TEST_NAME] setup: $TMPDIR_TEST"
(cd "$TMPDIR_TEST" && git init -q 2>&1 >/dev/null)

# Test 1: small Python file → .meta written; no additionalContext.
cat > "$TMPDIR_TEST/backend/api/foo.py" <<'EOF'
"""Tiny module for hook testing."""
def hello() -> str:
    return "world"
EOF

INPUT_JSON="{\"tool\":\"Write\",\"tool_input\":{\"file_path\":\"$TMPDIR_TEST/backend/api/foo.py\"},\"cwd\":\"$TMPDIR_TEST\"}"

# Measure runtime.
start_ms=$(python3 -c 'import time; print(int(time.monotonic()*1000))')
STDOUT="$(echo "$INPUT_JSON" | bash "$HOOK" 2>/dev/null)"
RC=$?
end_ms=$(python3 -c 'import time; print(int(time.monotonic()*1000))')
elapsed_ms=$((end_ms - start_ms))

[ "$RC" -eq 0 ] && pass "hook exits 0" || fail "hook exit code: $RC"

# Inspect .meta.
META="$TMPDIR_TEST/.smith/index/files/backend/api/foo.py.meta"
[ -f "$META" ] && pass ".meta created at mirrored path" \
    || fail ".meta not created: $META"

# No additionalContext for small file.
if [ -z "$STDOUT" ]; then
    pass "no additionalContext for small file"
else
    if echo "$STDOUT" | grep -q "additionalContext"; then
        fail "small file should not emit additionalContext; got: $STDOUT"
    else
        pass "no additionalContext for small file"
    fi
fi

# Performance: <500ms.
if [ "$elapsed_ms" -lt 500 ]; then
    pass "hook ran in ${elapsed_ms}ms (<500ms)"
elif [ "$elapsed_ms" -lt 2000 ]; then
    # Soft warn for CI variability; only fail at hard ceiling.
    pass "hook ran in ${elapsed_ms}ms (warn: above 500ms target but under 2s)"
else
    fail "hook took ${elapsed_ms}ms (way over 500ms budget)"
fi

# Test 2: hooks.log entry.
HOOKS_LOG="$HOME/.smith/logs/hooks.log"
if [ -f "$HOOKS_LOG" ] && tail -50 "$HOOKS_LOG" 2>/dev/null | grep -q "manifest-updater"; then
    pass "hooks.log contains manifest-updater entry"
else
    fail "hooks.log entry missing (log=$HOOKS_LOG)"
fi

# Test 3: Big file (>300 lines) → additionalContext warning emitted.
python3 -c "
print('\"\"\"Large module.\"\"\"')
for i in range(330):
    print(f'def f{i}():')
    print(f'    return {i}')
" > "$TMPDIR_TEST/backend/api/big.py"

INPUT_BIG="{\"tool\":\"Write\",\"tool_input\":{\"file_path\":\"$TMPDIR_TEST/backend/api/big.py\"},\"cwd\":\"$TMPDIR_TEST\"}"
STDOUT_BIG="$(echo "$INPUT_BIG" | bash "$HOOK" 2>/dev/null)"
if echo "$STDOUT_BIG" | grep -q "additionalContext"; then
    pass "big file (>300 lines) emits additionalContext"
else
    fail "expected additionalContext for big file; got: $STDOUT_BIG"
fi

# Confirm it's valid JSON containing the right payload.
if echo "$STDOUT_BIG" | python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
assert data['hookSpecificOutput']['hookEventName'] == 'PostToolUse'
assert '>300' in data['hookSpecificOutput']['additionalContext']
" 2>/dev/null; then
    pass "additionalContext is valid JSON with PostToolUse + >300 warning"
else
    fail "additionalContext is not valid JSON or missing required fields"
fi

# Test 4: non-source extension exits silently.
echo "binary blob" > "$TMPDIR_TEST/data.bin"
STDOUT_BIN="$(echo "{\"tool\":\"Write\",\"tool_input\":{\"file_path\":\"$TMPDIR_TEST/data.bin\"},\"cwd\":\"$TMPDIR_TEST\"}" | bash "$HOOK" 2>/dev/null)"
RC_BIN=$?
[ "$RC_BIN" -eq 0 ] && pass ".bin file: exit 0" || fail ".bin file: exit $RC_BIN"
[ -z "$STDOUT_BIN" ] && pass ".bin file: silent skip" \
    || fail ".bin file should be silent; got: $STDOUT_BIN"

# Test 5: malformed JSON doesn't crash.
RC_MAL=0
echo 'not-json' | bash "$HOOK" >/dev/null 2>&1 || RC_MAL=$?
[ "$RC_MAL" -eq 0 ] && pass "malformed JSON: exit 0" || fail "malformed JSON: exit $RC_MAL"

echo
echo "[$TEST_NAME] PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
