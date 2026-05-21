#!/usr/bin/env bash
# tests/e2e/test_quickstart_scenarios.sh
#
# T108 — Walk through Quickstart Scenarios A, B, C end-to-end.
#
# Scenario A — New Project Bootstrap (manual /smith-index since we can't
#              run /smith init from a test harness): index a fresh
#              project, verify the expected tree.
#
# Scenario B — Existing-project adoption: vault already exists, no
#              .smith/index/; context-loader injects the soft warning,
#              then user runs /smith-index, next call gets full
#              injection.
#
# Scenario C — Daily edit flow: edit a fixture file via the
#              manifest-updater hook; verify .meta update, system
#              manifest patch, and (for >300 line file) the
#              additionalContext warning is surfaced.

set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNNER="${REPO_ROOT}/scripts/smith-index/run.py"
HOOK_MU="${REPO_ROOT}/hooks/manifest-updater.sh"
HOOK_CL="${REPO_ROOT}/hooks/context-loader.sh"
FIXTURE="${REPO_ROOT}/tests/fixtures/sample-project"

TMPDIR_TEST="/tmp/smith-e2e-quickstart-$$"
mkdir -p "$TMPDIR_TEST"
trap 'rm -rf "$TMPDIR_TEST"' EXIT

PASS=0
FAIL=0
TEST_NAME="T108-quickstart-scenarios"

pass() { printf '  PASS %s\n' "$1"; PASS=$((PASS+1)); }
fail() { printf '  FAIL %s\n' "$1" >&2; FAIL=$((FAIL+1)); }

# =======================================================================
# Scenario A — New project bootstrap
# =======================================================================
echo "[$TEST_NAME] === Scenario A: new project bootstrap ==="
SCEN_A="$TMPDIR_TEST/scenario-A"
mkdir -p "$SCEN_A"
cp -R "${FIXTURE}/." "$SCEN_A/"
(cd "$SCEN_A" && git init -q 2>&1 >/dev/null)

cd "$SCEN_A"
python3 "$RUNNER" --root . >/dev/null 2>&1 || true

# Tree expectations.
[ -f .smith/index/manifest.md ] && pass "A: manifest.md created" || fail "A: manifest.md missing"
[ -d .smith/index/systems ]     && pass "A: systems/ created"   || fail "A: systems/ missing"
[ -d .smith/index/files ]       && pass "A: files/ created"     || fail "A: files/ missing"

# config bootstrap: per spec T050, context-manifest.json is auto-created;
# system-paths.json is NOT (Q7) unless --init-system-paths.
if [ -f .smith/index/config/context-manifest.json ]; then
    pass "A: context-manifest.json bootstrapped"
else
    fail "A: context-manifest.json not bootstrapped"
fi
if [ ! -f .smith/index/config/system-paths.json ]; then
    pass "A: system-paths.json NOT auto-created (correct — opt-in)"
else
    fail "A: system-paths.json should not be auto-created"
fi

# manifest.md <=50 lines.
ml=$(wc -l < .smith/index/manifest.md | tr -d ' ')
[ "$ml" -le 50 ] && pass "A: manifest.md is $ml lines (<=50)" \
    || fail "A: manifest.md is $ml lines (>50)"

# =======================================================================
# Scenario B — existing-project adoption
# =======================================================================
echo "[$TEST_NAME] === Scenario B: existing-project adoption ==="
SCEN_B="$TMPDIR_TEST/scenario-B"
mkdir -p "$SCEN_B/.smith/vault/sessions"
cp -R "${FIXTURE}/." "$SCEN_B/"
(cd "$SCEN_B" && git init -q 2>&1 >/dev/null)

# Vault has content but no index.
echo "# existing session" > "$SCEN_B/.smith/vault/sessions/2026-05-21-existing.md"

# 1. First Smith call → soft warning expected.
INPUT_B1='{"prompt":"/smith-bugfix something is broken","session_id":"scenB","cwd":"'"$SCEN_B"'"}'
OUT_B1="$(echo "$INPUT_B1" | bash "$HOOK_CL" 2>/dev/null)"
if echo "$OUT_B1" | grep -q "Manifest not initialized"; then
    pass "B: first call emits manifest-missing warning"
else
    fail "B: expected soft warning; got: $OUT_B1"
fi

# 2. User runs /smith-index.
cd "$SCEN_B"
python3 "$RUNNER" --root . >/dev/null 2>&1 || true
if [ -f .smith/index/manifest.md ]; then
    pass "B: /smith-index produced manifest.md"
else
    fail "B: /smith-index did not produce manifest.md"
fi

# 3. Next call gets full injection (different session_id; doesn't matter).
INPUT_B2='{"prompt":"/smith-bugfix retry","session_id":"scenB-2","cwd":"'"$SCEN_B"'"}'
OUT_B2="$(echo "$INPUT_B2" | bash "$HOOK_CL" 2>/dev/null)"
if echo "$OUT_B2" | grep -q "Manifest not initialized"; then
    fail "B: post-index call should NOT emit missing warning; got: $OUT_B2"
else
    pass "B: post-index call has no missing warning"
fi
if echo "$OUT_B2" | grep -qE "Manifest Snapshot|Project Manifest|Manifest Navigator"; then
    pass "B: post-index call includes manifest snapshot"
else
    fail "B: post-index call should include manifest content; got: $(echo $OUT_B2 | head -c 200)"
fi

# =======================================================================
# Scenario C — daily edit flow
# =======================================================================
echo "[$TEST_NAME] === Scenario C: daily edit flow ==="
SCEN_C="$TMPDIR_TEST/scenario-C"
mkdir -p "$SCEN_C/backend/src/api/v1"
(cd "$SCEN_C" && git init -q 2>&1 >/dev/null)
cd "$SCEN_C"

# Initial index (empty project).
python3 "$RUNNER" --root . >/dev/null 2>&1 || true

# Simulate Claude doing a Write on a 357-line python file (>300 threshold).
TARGET="$SCEN_C/backend/src/api/v1/products.py"
python3 -c "
print('\"\"\"Products endpoints (large file fixture for >300-line warning).\"\"\"')
print('from fastapi import APIRouter')
print('router = APIRouter()')
# Need >300 lines: 160 functions * 2 lines each = 320 + 3 prelude = 323.
for i in range(160):
    print(f'@router.get(\"/items/{{i}}\".replace(\"{{i}}\", \"{i}\"))')
    print(f'def get_item_{i}(): return {i}')
" > "$TARGET"
lines=$(wc -l < "$TARGET" | tr -d ' ')
echo "  C: target file is $lines lines"

INPUT_C='{"tool":"Edit","tool_input":{"file_path":"'"$TARGET"'"},"cwd":"'"$SCEN_C"'"}'
STDOUT_C="$(echo "$INPUT_C" | bash "$HOOK_MU" 2>/dev/null)"

META="$SCEN_C/.smith/index/files/backend/src/api/v1/products.py.meta"
if [ -f "$META" ]; then
    pass "C: .meta updated by hook"
else
    fail "C: .meta not created at $META"
fi

# >300 line file → additionalContext on stdout.
if echo "$STDOUT_C" | grep -q "additionalContext"; then
    pass "C: hook emitted additionalContext for >300-line edit"
else
    fail "C: hook should emit additionalContext for $lines-line file; got: $STDOUT_C"
fi

# System manifest patched.
if [ -d "$SCEN_C/.smith/index/systems" ] && \
    find "$SCEN_C/.smith/index/systems" -name '*.md' -exec grep -l "products.py" {} \; | head -1 >/dev/null; then
    pass "C: system manifest patched with products.py"
else
    fail "C: system manifest not patched"
fi

# Top manifest updated (Files over 300 lines stat reflects the new file).
if grep -qE "Files over 300 lines: *[1-9]" "$SCEN_C/.smith/index/manifest.md" 2>/dev/null; then
    over300=$(grep -E "Files over 300 lines" "$SCEN_C/.smith/index/manifest.md" | head -1)
    pass "C: top manifest 'Files over 300 lines' stat incremented ($over300)"
else
    grep -q "Files over 300 lines" "$SCEN_C/.smith/index/manifest.md" \
        && stat=$(grep "Files over 300 lines" "$SCEN_C/.smith/index/manifest.md") \
        || stat="(missing)"
    fail "C: top manifest should show >=1 file over 300 lines; got: $stat"
fi

echo
echo "[$TEST_NAME] PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
