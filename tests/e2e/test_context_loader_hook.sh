#!/usr/bin/env bash
# tests/e2e/test_context_loader_hook.sh
#
# T104 — context-loader hook detects Smith skills and injects context.
#
# Verifies:
#   - Smith slash command (/smith-new) triggers additionalContext
#     injection
#   - Non-Smith prompt (e.g. "what is 2+2") produces zero output
#   - Manifest content is included when navigator is enabled for the
#     skill and manifest exists
#   - exit code is 0
#   - performance: <5s total (in-process navigator, no sub-agent in v1)

set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
HOOK="${REPO_ROOT}/hooks/context-loader.sh"

if [ ! -x "$HOOK" ]; then
    echo "FAIL: hook not executable: $HOOK"
    exit 1
fi

TMPDIR_TEST="/tmp/smith-e2e-cl-$$"
mkdir -p "$TMPDIR_TEST/.smith/vault/sessions"
mkdir -p "$TMPDIR_TEST/.smith/index"
mkdir -p "$TMPDIR_TEST/.smith/index/config"
trap 'rm -rf "$TMPDIR_TEST"' EXIT

# Seed minimal vault + manifest so navigator path can fire.
cat > "$TMPDIR_TEST/.smith/vault/sessions/2026-05-21-test.md" <<'EOF'
# Test session
- something happened
EOF

cat > "$TMPDIR_TEST/.smith/index/manifest.md" <<'EOF'
# Project Manifest

| System | Files | Lines | Topics |
|--------|-------|-------|--------|
| system-backend-src | 4 | 120 | API |
| system-frontend-src | 2 | 80 | UI |

## Stats
- Total source files: 6
- Files > 200 lines: 0
- Files > 300 lines: 0
- Files > 500 lines: 0
- Last full index: 0.2s (2026-05-21T22:00:00Z)
EOF

PASS=0
FAIL=0
TEST_NAME="T104-context-loader-hook"

pass() { printf '  PASS %s\n' "$1"; PASS=$((PASS+1)); }
fail() { printf '  FAIL %s\n' "$1" >&2; FAIL=$((FAIL+1)); }

echo "[$TEST_NAME] setup: $TMPDIR_TEST"

# --- Test 1: Smith slash command triggers injection ---------------------
INPUT='{"prompt":"/smith-new add a new feature","session_id":"e2e-t104-1","cwd":"'"$TMPDIR_TEST"'"}'

start_ms=$(python3 -c 'import time; print(int(time.monotonic()*1000))')
STDOUT="$(echo "$INPUT" | bash "$HOOK" 2>/dev/null)"
RC=$?
end_ms=$(python3 -c 'import time; print(int(time.monotonic()*1000))')
elapsed_ms=$((end_ms - start_ms))

[ "$RC" -eq 0 ] && pass "hook exits 0 for /smith-new" || fail "exit $RC for /smith-new"

if echo "$STDOUT" | grep -q "additionalContext"; then
    pass "additionalContext present for /smith-new"
else
    fail "missing additionalContext for /smith-new; got: $STDOUT"
fi

if echo "$STDOUT" | grep -q "smith-context-injection"; then
    pass "injection header present"
else
    fail "injection header absent"
fi

# Manifest content surfaced (navigator=true for smith-new).
if echo "$STDOUT" | grep -qE "Manifest Snapshot|Project Manifest|Manifest Navigator"; then
    pass "manifest snapshot surfaced for navigator-enabled skill"
else
    fail "expected manifest snapshot for smith-new; got: $(echo $STDOUT | head -c 200)"
fi

# Performance: <5s budget. In-process implementation: typically <500ms.
if [ "$elapsed_ms" -lt 5000 ]; then
    pass "performance: ${elapsed_ms}ms (<5000ms)"
else
    fail "performance: ${elapsed_ms}ms exceeds 5s budget"
fi

# --- Test 2: Plain question yields zero output --------------------------
INPUT2='{"prompt":"what is 2+2","session_id":"e2e-t104-2","cwd":"'"$TMPDIR_TEST"'"}'
STDOUT2="$(echo "$INPUT2" | bash "$HOOK" 2>/dev/null)"
RC2=$?

[ "$RC2" -eq 0 ] && pass "hook exits 0 for plain question" || fail "exit $RC2 for plain question"

if [ -z "$STDOUT2" ]; then
    pass "no injection for non-Smith prompt"
else
    fail "non-Smith prompt produced output: $STDOUT2"
fi

# --- Test 3: NL trigger fires injection ---------------------------------
INPUT3='{"prompt":"let'"'"'s smith this idea","session_id":"e2e-t104-3","cwd":"'"$TMPDIR_TEST"'"}'
STDOUT3="$(echo "$INPUT3" | bash "$HOOK" 2>/dev/null)"
if echo "$STDOUT3" | grep -q "additionalContext"; then
    pass "NL trigger 'let's smith this' produces injection"
else
    fail "NL trigger should produce injection; got: $STDOUT3"
fi

echo
echo "[$TEST_NAME] PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
