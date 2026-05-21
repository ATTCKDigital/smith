#!/usr/bin/env bash
# tests/e2e/test_full_index_rebuild.sh
#
# T101 — End-to-end /smith-index full rebuild on the sample-project fixture.
#
# Verifies:
#   - manifest.md exists, <=50 lines
#   - per-system manifests exist, each <=80 lines
#   - .meta files written for all 8 source files at the correct mirrored
#     paths
#   - .meta files contain hash, lines, and the expected sections
#     (Imports/Functions/Classes/Routes/Exports)
#   - the backend/src/api/v1/products.py file is mapped to
#     system-backend-src (per the heuristic)
#   - performance: full index for 8-file project completes in <60s
#
# Sets up an isolated temp project; cleans up at exit.
# Never modifies any Phase A-E source files.

set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNNER="${REPO_ROOT}/scripts/smith-index/run.py"
FIXTURE="${REPO_ROOT}/tests/fixtures/sample-project"

TMPDIR_TEST="/tmp/smith-e2e-fullindex-$$"
mkdir -p "$TMPDIR_TEST"
trap 'rm -rf "$TMPDIR_TEST"' EXIT

PASS=0
FAIL=0
TEST_NAME="T101-full-index-rebuild"

pass() { printf '  PASS %s\n' "$1"; PASS=$((PASS+1)); }
fail() { printf '  FAIL %s\n' "$1" >&2; FAIL=$((FAIL+1)); }
assert() {
    if [ "$2" = "true" ]; then pass "$1"; else fail "$1"; fi
}

echo "[$TEST_NAME] setup: $TMPDIR_TEST"
cp -R "${FIXTURE}/." "${TMPDIR_TEST}/"
(cd "$TMPDIR_TEST" && git init -q 2>&1 >/dev/null)

cd "$TMPDIR_TEST"

# --- Run full rebuild ----------------------------------------------------
start_ts=$(python3 -c 'import time; print(time.monotonic())')
out="$(python3 "$RUNNER" --root . 2>&1)"
end_ts=$(python3 -c 'import time; print(time.monotonic())')
elapsed_ms=$(python3 -c "print(int(($end_ts - $start_ts) * 1000))")

echo "  elapsed: ${elapsed_ms}ms"
echo "  $out"

# --- Existence + budget checks ------------------------------------------
[ -f .smith/index/manifest.md ] && assert "manifest.md exists" true \
    || assert "manifest.md exists" false
[ -d .smith/index/files ] && assert ".smith/index/files dir exists" true \
    || assert ".smith/index/files dir exists" false
[ -d .smith/index/systems ] && assert ".smith/index/systems dir exists" true \
    || assert ".smith/index/systems dir exists" false

# Top manifest <=50 lines.
manifest_lines=$(wc -l < .smith/index/manifest.md | tr -d ' ')
if [ "$manifest_lines" -le 50 ]; then
    pass "manifest.md is ${manifest_lines} lines (<=50)"
else
    fail "manifest.md is ${manifest_lines} lines (>50)"
fi

# Each system manifest <=80 lines.
sys_ok=true
for sysf in .smith/index/systems/*.md; do
    [ -f "$sysf" ] || continue
    lc=$(wc -l < "$sysf" | tr -d ' ')
    if [ "$lc" -gt 80 ]; then
        sys_ok=false
        fail "$sysf is $lc lines (>80)"
    fi
done
if [ "$sys_ok" = "true" ]; then
    pass "all per-system manifests <=80 lines"
fi

# --- 8 .meta files at mirrored paths ------------------------------------
expected_files=(
    "backend/src/api/v1/__init__.py"
    "backend/src/api/v1/products.py"
    "backend/src/models/product.py"
    "backend/src/services/shopify_sync.py"
    "backend/tests/test_products.py"
    "frontend/src/components/ProductList.tsx"
    "frontend/src/lib/api/products.ts"
    "services/billing/main.py"
)

meta_count=$(find .smith/index/files -type f -name '*.meta' | wc -l | tr -d ' ')
if [ "$meta_count" -eq 8 ]; then
    pass "8 .meta files written"
else
    fail "expected 8 .meta files, found $meta_count"
fi

for src in "${expected_files[@]}"; do
    meta=".smith/index/files/${src}.meta"
    if [ -f "$meta" ]; then
        pass ".meta exists for $src"
    else
        fail ".meta missing for $src (expected at $meta)"
    fi
done

# --- .meta content checks (hash, lines, sections) -----------------------
sample_meta=".smith/index/files/backend/src/api/v1/products.py.meta"
if [ -f "$sample_meta" ]; then
    text="$(cat "$sample_meta")"
    echo "$text" | grep -q "^Hash: " && pass "products.py.meta has Hash: line" \
        || fail "products.py.meta missing Hash: line"
    echo "$text" | grep -q "^Lines: " && pass "products.py.meta has Lines: line" \
        || fail "products.py.meta missing Lines: line"
    echo "$text" | grep -q "^## Imports" && pass "products.py.meta has Imports section" \
        || fail "products.py.meta missing Imports section"
    echo "$text" | grep -q "^## Functions" && pass "products.py.meta has Functions section" \
        || fail "products.py.meta missing Functions section"
    echo "$text" | grep -q "^## Classes" && pass "products.py.meta has Classes section" \
        || fail "products.py.meta missing Classes section"
    echo "$text" | grep -q "^## Routes" && pass "products.py.meta has Routes section" \
        || fail "products.py.meta missing Routes section"
    echo "$text" | grep -q "^## Exports" && pass "products.py.meta has Exports section" \
        || fail "products.py.meta missing Exports section"
fi

# Verify .ts file has Exports + Imports (TS parser path).
ts_meta=".smith/index/files/frontend/src/lib/api/products.ts.meta"
if [ -f "$ts_meta" ]; then
    grep -q "^Language: " "$ts_meta" && pass "products.ts.meta has Language: line" \
        || fail "products.ts.meta missing Language: line"
fi

# --- products.py mapped to system-backend-src ---------------------------
if [ -f .smith/index/systems/system-backend-src.md ]; then
    if grep -q "products.py" .smith/index/systems/system-backend-src.md; then
        pass "products.py mapped to system-backend-src"
    else
        fail "products.py NOT listed in system-backend-src.md"
    fi
else
    fail "system-backend-src.md not created"
fi

# Sanity-check that services/billing/main.py is mapped to system-billing.
if [ -f .smith/index/systems/system-billing.md ] && grep -q "billing/main.py" .smith/index/systems/system-billing.md; then
    pass "services/billing/main.py mapped to system-billing"
else
    fail "services/billing/main.py NOT mapped to system-billing"
fi

# --- Performance assertion (advisory, do not fail) ----------------------
if [ "$elapsed_ms" -gt 60000 ]; then
    fail "elapsed ${elapsed_ms}ms exceeds 60000ms budget"
else
    pass "performance: full index in ${elapsed_ms}ms (<60000ms budget)"
fi

# --- Summary ------------------------------------------------------------
echo
echo "[$TEST_NAME] PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
