#!/usr/bin/env bash
# tests/e2e/test_check_staleness.sh
#
# T102 — --check correctly detects fresh vs stale.
#
# Verifies the hash-only staleness scan flow:
#   1. After a fresh full index, --check reports 0 stale.
#   2. After modifying one source file (first 4KB), --check reports
#      that file stale.
#   3. After a re-run of the full index, --check reports 0 stale again.

set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNNER="${REPO_ROOT}/scripts/smith-index/run.py"
FIXTURE="${REPO_ROOT}/tests/fixtures/sample-project"

TMPDIR_TEST="/tmp/smith-e2e-check-$$"
mkdir -p "$TMPDIR_TEST"
trap 'rm -rf "$TMPDIR_TEST"' EXIT

PASS=0
FAIL=0
TEST_NAME="T102-check-staleness"

pass() { printf '  PASS %s\n' "$1"; PASS=$((PASS+1)); }
fail() { printf '  FAIL %s\n' "$1" >&2; FAIL=$((FAIL+1)); }

echo "[$TEST_NAME] setup: $TMPDIR_TEST"
cp -R "${FIXTURE}/." "${TMPDIR_TEST}/"
(cd "$TMPDIR_TEST" && git init -q 2>&1 >/dev/null)
cd "$TMPDIR_TEST"

# Initial index.
python3 "$RUNNER" --root . >/dev/null 2>&1 || true

# 1) Immediate --check → all fresh.
out1="$(python3 "$RUNNER" --root . --check 2>&1)"
echo "  check1: $out1"
if echo "$out1" | grep -q "0 stale" && echo "$out1" | grep -q "0 missing-source"; then
    pass "fresh index reports 0 stale, 0 missing-source"
else
    fail "fresh index should report 0 stale; got: $out1"
fi

# 2) Modify one source file.
target="backend/src/api/v1/products.py"
# Prepend a comment to the very first byte — guaranteed change in first 4KB.
{ printf '# staleness-test-touch\n'; cat "$target"; } > "${target}.tmp"
mv "${target}.tmp" "$target"

out2="$(python3 "$RUNNER" --root . --check 2>&1)"
echo "  check2: $out2"
if echo "$out2" | grep -q "1 stale"; then
    pass "modified file detected as stale"
else
    fail "expected '1 stale'; got: $out2"
fi
if echo "$out2" | grep -q "$target"; then
    pass "stale file path reported in output"
else
    fail "stale file path not in output: $out2"
fi

# 3) Re-run full index → should be fresh again.
python3 "$RUNNER" --root . >/dev/null 2>&1 || true
out3="$(python3 "$RUNNER" --root . --check 2>&1)"
echo "  check3: $out3"
if echo "$out3" | grep -q "0 stale"; then
    pass "after rebuild, all fresh"
else
    fail "after rebuild, should report 0 stale; got: $out3"
fi

echo
echo "[$TEST_NAME] PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
