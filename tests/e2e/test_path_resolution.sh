#!/usr/bin/env bash
# tests/e2e/test_path_resolution.sh
#
# T107 — System path resolution with explicit overrides + heuristic.
#
# Verifies:
#   1. Fresh project (no system-paths.json): heuristic assigns every
#      file. backend/<x>/* → system-backend-<x>, services/<x>/* →
#      system-<x>, etc.
#   2. After adding a system-paths.json override (prefix
#      "backend/src/api/v1/products" → "system-15-command-center"),
#      the override wins for matching files.
#   3. Heuristic still applies for files that do NOT match any rule.
#   4. Longest-prefix wins when multiple rules could match the same
#      path.

set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNNER="${REPO_ROOT}/scripts/smith-index/run.py"
RESOLVER="${REPO_ROOT}/scripts/parsers/path-resolver.py"
FIXTURE="${REPO_ROOT}/tests/fixtures/sample-project"

TMPDIR_TEST="/tmp/smith-e2e-paths-$$"
mkdir -p "$TMPDIR_TEST"
trap 'rm -rf "$TMPDIR_TEST"' EXIT

PASS=0
FAIL=0
TEST_NAME="T107-path-resolution"

pass() { printf '  PASS %s\n' "$1"; PASS=$((PASS+1)); }
fail() { printf '  FAIL %s\n' "$1" >&2; FAIL=$((FAIL+1)); }

echo "[$TEST_NAME] setup: $TMPDIR_TEST"
cp -R "${FIXTURE}/." "${TMPDIR_TEST}/"
(cd "$TMPDIR_TEST" && git init -q 2>&1 >/dev/null)
cd "$TMPDIR_TEST"

# --- Phase 1: Heuristic only (no overrides) -----------------------------
python3 "$RUNNER" --root . >/dev/null 2>&1 || true

# Heuristic should produce these system names.
expected_heuristic=(
    "backend/src/api/v1/products.py:system-backend-src"
    "services/billing/main.py:system-billing"
    "frontend/src/components/ProductList.tsx:system-frontend-src"
    "backend/tests/test_products.py:system-backend-tests"
)
for pair in "${expected_heuristic[@]}"; do
    src="${pair%%:*}"
    want="${pair##*:}"
    got="$(python3 "$RESOLVER" "$src" "" 2>/dev/null | tr -d '\n')"
    if [ "$got" = "$want" ]; then
        pass "heuristic: $src → $got"
    else
        fail "heuristic: $src → got $got, want $want"
    fi
done

# Also verify the corresponding system manifest files were created.
for want in system-backend-src system-billing system-frontend-src; do
    if [ -f ".smith/index/systems/${want}.md" ]; then
        pass "heuristic created systems/${want}.md"
    else
        fail "heuristic did not create systems/${want}.md"
    fi
done

# --- Phase 2: Add system-paths.json override ----------------------------
# NOTE: we deliberately omit `"default": ...` so the resolver falls
# through to the heuristic for non-matching files. With an explicit
# default the resolver short-circuits to that value (per data-model.md
# section 6); we test that path separately below.
mkdir -p .smith/index/config
cat > .smith/index/config/system-paths.json <<'EOF'
{
  "rules": [
    {"prefix": "backend/src/api", "system": "system-01-api"},
    {"prefix": "backend/src/api/v1/products", "system": "system-15-command-center"},
    {"prefix": "frontend/src", "system": "system-03-frontend"}
  ]
}
EOF

# Wipe the systems/ dir so the second rebuild can't "leak" stale data
# from the heuristic-only Phase 1 run. (The indexer rewrites per-system
# files but does not prune systems removed by override-driven renames.)
rm -rf .smith/index/systems

# Rebuild with overrides.
python3 "$RUNNER" --root . --system-paths .smith/index/config/system-paths.json >/dev/null 2>&1 || true

# Override winning for matching files.
got1="$(python3 "$RESOLVER" "backend/src/api/v1/products.py" "" .smith/index/config/system-paths.json 2>/dev/null | tr -d '\n')"
if [ "$got1" = "system-15-command-center" ]; then
    pass "override (longest-prefix): products.py → system-15-command-center"
else
    fail "products.py should be system-15-command-center; got $got1"
fi

# A backend file that doesn't match the longer "products" rule, but
# matches the shorter "backend/src/api" rule.
got2="$(python3 "$RESOLVER" "backend/src/api/other.py" "" .smith/index/config/system-paths.json 2>/dev/null | tr -d '\n')"
if [ "$got2" = "system-01-api" ]; then
    pass "override (shorter prefix wins when no longer match): system-01-api"
else
    fail "non-matching longer rule should fall back to shorter; got $got2"
fi

# A file that doesn't match any rule → falls back to heuristic (no
# explicit "default" in the overrides file).
got3="$(python3 "$RESOLVER" "services/billing/main.py" "" .smith/index/config/system-paths.json 2>/dev/null | tr -d '\n')"
if [ "$got3" = "system-billing" ]; then
    pass "no rule match → heuristic still applied (system-billing)"
else
    fail "expected heuristic fallback for services/billing/main.py; got $got3"
fi

# Explicit "default" short-circuits past the heuristic.
got_def="$(python3 -c "
import json, importlib.util
spec = importlib.util.spec_from_file_location('pr', '${RESOLVER}')
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
print(mod.resolve('services/billing/main.py', overrides_dict={'rules': [], 'default': 'system-default-bucket'}))
")"
if [ "$got_def" = "system-default-bucket" ]; then
    pass "explicit 'default' in overrides short-circuits heuristic"
else
    fail "explicit default not honored; got $got_def"
fi

# --- Phase 3: After rebuild, the system manifests reflect the override --
# The products.py file should now be in system-15-command-center.md.
if [ -f .smith/index/systems/system-15-command-center.md ] \
    && grep -q "products.py" .smith/index/systems/system-15-command-center.md; then
    pass "rebuild placed products.py in system-15-command-center"
else
    fail "products.py not in system-15-command-center.md after rebuild"
fi

# Since we wiped systems/ before rebuild, system-backend-src.md should
# NOT have been recreated (no file now resolves to that system).
if [ ! -f .smith/index/systems/system-backend-src.md ]; then
    pass "system-backend-src.md absent (no files resolve to it under override)"
else
    if grep -q "api/v1/products.py" .smith/index/systems/system-backend-src.md; then
        fail "products.py should have moved out of system-backend-src.md"
    else
        pass "system-backend-src.md present but does not contain products.py"
    fi
fi

# --- Phase 4: Longest-prefix wins (resolver-only assertion) -------------
got_long="$(python3 -c "
import importlib.util
spec = importlib.util.spec_from_file_location('pr', '${RESOLVER}')
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
overrides = {
    'rules': [
        {'prefix': 'backend/src/api', 'system': 'system-short'},
        {'prefix': 'backend/src/api/v1/products', 'system': 'system-long'},
    ]
}
print(mod.resolve('backend/src/api/v1/products.py', overrides_dict=overrides))
")"
if [ "$got_long" = "system-long" ]; then
    pass "longest-prefix wins (system-long)"
else
    fail "longest-prefix should win; got $got_long"
fi

echo
echo "[$TEST_NAME] PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
