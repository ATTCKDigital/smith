#!/usr/bin/env bash
# test_manifest_updater.sh — smoke tests for hooks/manifest-updater.sh.
#
# Covers acceptance criteria:
#  - PostToolUse hook writes .meta within budget (<500ms p95).
#  - 300-line file emits additionalContext warning on stdout.
#  - Non-source extension exits silently.
#  - Malformed stdin JSON exits 0 (never blocks).

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$REPO_ROOT/hooks/manifest-updater.sh"

if [ ! -x "$HOOK" ]; then
    echo "FAIL: hook not executable: $HOOK"
    exit 1
fi

TMP_PROJECT="$(mktemp -d -t mu-test.XXXXXX)"
trap 'rm -rf "$TMP_PROJECT"' EXIT

mkdir -p "$TMP_PROJECT/backend/api"
(cd "$TMP_PROJECT" && git init -q 2>&1 >/dev/null)

PASS=0
FAIL=0

assert() {
    local label="$1"
    if [ "$2" = "true" ]; then
        echo "PASS $label"
        PASS=$((PASS+1))
    else
        echo "FAIL $label"
        FAIL=$((FAIL+1))
    fi
}

# --- Test 1: small Python file → .meta written, no warning ----------------
cat > "$TMP_PROJECT/backend/api/small.py" <<'EOF'
def foo():
    return 1
EOF
STDOUT="$(echo "{\"tool_input\":{\"file_path\":\"$TMP_PROJECT/backend/api/small.py\"},\"cwd\":\"$TMP_PROJECT\"}" \
    | bash "$HOOK" 2>/dev/null || true)"
META="$TMP_PROJECT/.smith/index/files/backend/api/small.py.meta"
[ -f "$META" ] && assert "small py meta written" true || assert "small py meta written" false
[ -z "$STDOUT" ] && assert "small py no warning emitted" true \
    || assert "small py no warning emitted (got: $STDOUT)" false

# --- Test 2: 350-line file → warning emitted -----------------------------
python3 -c "
for i in range(330):
    print(f'def f{i}():')
    print(f'    pass')
" > "$TMP_PROJECT/backend/api/big.py"
STDOUT="$(echo "{\"tool_input\":{\"file_path\":\"$TMP_PROJECT/backend/api/big.py\"},\"cwd\":\"$TMP_PROJECT\"}" \
    | bash "$HOOK" 2>/dev/null || true)"
if echo "$STDOUT" | grep -q "Exceeds\|>300\|additionalContext"; then
    assert "big py emits warning" true
else
    assert "big py emits warning (got: $STDOUT)" false
fi

# --- Test 3: non-source extension → silent skip --------------------------
echo "binary blob" > "$TMP_PROJECT/blob.bin"
STDOUT="$(echo "{\"tool_input\":{\"file_path\":\"$TMP_PROJECT/blob.bin\"},\"cwd\":\"$TMP_PROJECT\"}" \
    | bash "$HOOK" 2>/dev/null || true)"
[ -z "$STDOUT" ] && assert ".bin file silent skip" true \
    || assert ".bin file silent skip" false

# --- Test 4: missing file → silent skip ---------------------------------
STDOUT="$(echo '{"tool_input":{"file_path":"/tmp/nonexistent-xyz.py"}}' \
    | bash "$HOOK" 2>/dev/null || true)"
[ -z "$STDOUT" ] && assert "missing file silent skip" true \
    || assert "missing file silent skip" false

# --- Test 5: malformed JSON → exit 0 ------------------------------------
RC=0
echo 'not-json-at-all' | bash "$HOOK" >/dev/null 2>&1 || RC=$?
[ "$RC" -eq 0 ] && assert "malformed JSON exits 0" true \
    || assert "malformed JSON exits 0 (rc=$RC)" false

# --- Test 6: performance (p95 < 500ms over 10 runs) ---------------------
runs=()
for i in 1 2 3 4 5 6 7 8 9 10; do
    start=$(python3 -c 'import time; print(int(time.monotonic()*1000))')
    echo "{\"tool_input\":{\"file_path\":\"$TMP_PROJECT/backend/api/small.py\"},\"cwd\":\"$TMP_PROJECT\"}" \
        | bash "$HOOK" >/dev/null 2>&1
    end=$(python3 -c 'import time; print(int(time.monotonic()*1000))')
    runs+=($((end - start)))
done
# Sort and pick the 9th (p95-ish for 10 samples).
sorted=($(printf '%s\n' "${runs[@]}" | sort -n))
p95=${sorted[8]}
echo "  manifest-updater runs (ms): ${sorted[*]}"
if [ "$p95" -lt 500 ]; then
    assert "p95 < 500ms (was ${p95}ms)" true
else
    assert "p95 < 500ms (was ${p95}ms)" false
fi

echo
echo "manifest-updater tests: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
