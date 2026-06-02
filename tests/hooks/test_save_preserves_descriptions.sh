#!/usr/bin/env bash
# test_save_preserves_descriptions.sh — verify hooks/manifest-updater-lib.py
# preserves the v2 .meta description layer across edits to the source file.
#
# Covers tasks T063 + T064 from specs/20-manifest-fixes/tasks.md:
#  - Seed a .meta with `**Description:**`, `Described-Against-Hash:`,
#    `Described-At:`, and per-method `Id:`/`Description:` pairs.
#  - Simulate a file edit (write new content), invoke the save hook.
#  - Assert the description layer is byte-identical AND `Hash:` was updated.
#  - Assert `Hash != Described-Against-Hash` after the body edit (staleness
#    signal detectable without any extra marker).
#  - Assert a v1 .meta (no description layer) round-trips without growth.
#  - Assert the save hook NEVER calls Haiku (no ANTHROPIC_API_KEY needed).

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$REPO_ROOT/hooks/manifest-updater.sh"
LIB="$REPO_ROOT/hooks/manifest-updater-lib.py"

if [ ! -x "$HOOK" ]; then
    echo "FAIL: hook not executable: $HOOK"
    exit 1
fi
if [ ! -f "$LIB" ]; then
    echo "FAIL: lib not found: $LIB"
    exit 1
fi

TMP_PROJECT="$(mktemp -d -t spd-test.XXXXXX)"
trap 'rm -rf "$TMP_PROJECT"' EXIT

mkdir -p "$TMP_PROJECT/backend/api"
(cd "$TMP_PROJECT" && git init -q >/dev/null 2>&1)

# Force the save hook to pick up the repo's v2 parser (with stable ids) by
# overriding via the project-local <project>/.smith/scripts/ path. This
# avoids relying on whatever older parser may live in ~/.smith/scripts/.
mkdir -p "$TMP_PROJECT/.smith/scripts"
cp "$REPO_ROOT/scripts/parsers/parse-python.py" "$TMP_PROJECT/.smith/scripts/parse-python.py"
cp "$REPO_ROOT/scripts/parsers/parse-js.js"     "$TMP_PROJECT/.smith/scripts/parse-js.js"
chmod +x "$TMP_PROJECT/.smith/scripts/parse-python.py" "$TMP_PROJECT/.smith/scripts/parse-js.js"

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

# Ensure the save hook never reaches Haiku (it must be LLM-free).
unset ANTHROPIC_API_KEY

# --- Test 1: v1 .meta (no description layer) — preserved on re-save ----
cat > "$TMP_PROJECT/backend/api/legacy.py" <<'EOF'
def alpha():
    return 1

def beta(x):
    return x + 1
EOF

# First save: produces a fresh v1-style .meta (no description layer yet).
echo "{\"tool_input\":{\"file_path\":\"$TMP_PROJECT/backend/api/legacy.py\"},\"cwd\":\"$TMP_PROJECT\"}" \
    | bash "$HOOK" >/dev/null 2>&1
META1="$TMP_PROJECT/.smith/index/files/backend/api/legacy.py.meta"
[ -f "$META1" ] && assert "v1 meta initial write" true || assert "v1 meta initial write" false

if grep -q '^\*\*Description:\*\* ' "$META1"; then
    assert "v1 meta has NO description layer initially" false
else
    assert "v1 meta has NO description layer initially" true
fi

# Edit source and re-save — should still be v1 (no description layer added).
cat > "$TMP_PROJECT/backend/api/legacy.py" <<'EOF'
def alpha():
    return 1

def beta(x, y=2):
    return x + y
EOF
echo "{\"tool_input\":{\"file_path\":\"$TMP_PROJECT/backend/api/legacy.py\"},\"cwd\":\"$TMP_PROJECT\"}" \
    | bash "$HOOK" >/dev/null 2>&1

if grep -q '^\*\*Description:\*\* ' "$META1"; then
    assert "v1 meta stays v1 after edit (no LLM, no description added)" false
else
    assert "v1 meta stays v1 after edit (no LLM, no description added)" true
fi

# --- Test 2: v2 .meta with description layer — preserved on save ---------
cat > "$TMP_PROJECT/backend/api/sample.py" <<'EOF'
def alpha():
    """Original alpha."""
    return 1

def beta(x):
    """Original beta."""
    return x + 1
EOF

# Initial save to produce the .meta structure with stable method ids.
echo "{\"tool_input\":{\"file_path\":\"$TMP_PROJECT/backend/api/sample.py\"},\"cwd\":\"$TMP_PROJECT\"}" \
    | bash "$HOOK" >/dev/null 2>&1
META="$TMP_PROJECT/.smith/index/files/backend/api/sample.py.meta"
[ -f "$META" ] && assert "v2 baseline meta written" true || assert "v2 baseline meta written" false

# Harvest the auto-generated function ids so we can inject descriptions
# keyed on real ids (matches what /smith-index --describe would do).
ALPHA_ID="$(grep -A1 '`alpha' "$META" | grep '^  Id: ' | head -1 | awk '{print $2}')"
BETA_ID="$(grep -A1  '`beta'  "$META" | grep '^  Id: ' | head -1 | awk '{print $2}')"
[ -n "$ALPHA_ID" ] && [ -n "$BETA_ID" ] \
    && assert "harvested method ids from baseline meta" true \
    || assert "harvested method ids from baseline meta (alpha=$ALPHA_ID beta=$BETA_ID)" false

# Inject a complete description layer at the locations render_meta expects:
#   - module header lines after `Hash:` and before the blank separator
#   - per-method `Description:` line immediately after each `Id:` line
ORIGINAL_HASH="$(grep '^Hash: ' "$META" | awk '{print $2}')"
[ -n "$ORIGINAL_HASH" ] && assert "harvested original Hash" true \
    || assert "harvested original Hash" false

python3 <<PY
import re, pathlib
meta = pathlib.Path("$META")
text = meta.read_text()

# Splice module description block AFTER the Hash: line.
lines = text.splitlines()
out = []
for line in lines:
    out.append(line)
    if line.startswith("Hash: "):
        out.append("**Description:** Demo module exercising save-hook description preservation.")
        out.append("Described-Against-Hash: $ORIGINAL_HASH")
        out.append("Described-At: 2026-06-02T00:00:00Z")

# Splice per-method Description: AFTER each Id: line.
spliced = []
for line in out:
    spliced.append(line)
    if line.startswith("  Id: $ALPHA_ID"):
        spliced.append("  Description: Returns the constant 1. Used by tests.")
    elif line.startswith("  Id: $BETA_ID"):
        spliced.append("  Description: Adds 1 to the supplied argument.")

meta.write_text("\n".join(spliced) + ("\n" if text.endswith("\n") else ""))
PY

# Sanity-check we actually got 5 description lines after the splice.
COUNT_BEFORE="$(grep -c '^\(\*\*Description:\*\* \|Described-Against-Hash: \|Described-At: \|  Description: \)' "$META")"
if [ "$COUNT_BEFORE" -ge 5 ]; then
    assert "description layer seeded into meta ($COUNT_BEFORE lines)" true
else
    assert "description layer seeded into meta (only $COUNT_BEFORE lines)" false
fi

# Snapshot the description lines for byte-for-byte comparison after re-save.
grep '^\(\*\*Description:\*\* \|Described-Against-Hash: \|Described-At: \|  Description: \)' "$META" \
    > "$TMP_PROJECT/desc-before.txt"

# --- Test 2a: edit source body (changes Hash) ----------------------------
cat > "$TMP_PROJECT/backend/api/sample.py" <<'EOF'
def alpha():
    """Original alpha — body edited."""
    return 1 + 0

def beta(x):
    """Original beta — body edited."""
    return x + 1 + 0
EOF
echo "{\"tool_input\":{\"file_path\":\"$TMP_PROJECT/backend/api/sample.py\"},\"cwd\":\"$TMP_PROJECT\"}" \
    | bash "$HOOK" >/dev/null 2>&1

# Compare description lines BEFORE vs AFTER the body edit — must be identical.
grep '^\(\*\*Description:\*\* \|Described-Against-Hash: \|Described-At: \|  Description: \)' "$META" \
    > "$TMP_PROJECT/desc-after.txt"

if diff -q "$TMP_PROJECT/desc-before.txt" "$TMP_PROJECT/desc-after.txt" >/dev/null 2>&1; then
    assert "description layer byte-identical after body edit" true
else
    assert "description layer byte-identical after body edit" false
    echo "    --- diff ---"
    diff "$TMP_PROJECT/desc-before.txt" "$TMP_PROJECT/desc-after.txt" | sed 's/^/    /'
fi

# Hash MUST have updated to reflect the new body.
NEW_HASH="$(grep '^Hash: ' "$META" | awk '{print $2}')"
if [ -n "$NEW_HASH" ] && [ "$NEW_HASH" != "$ORIGINAL_HASH" ]; then
    assert "Hash: updated after body edit" true
else
    assert "Hash: updated after body edit (was=$ORIGINAL_HASH now=$NEW_HASH)" false
fi

# Described-Against-Hash MUST be unchanged (save hook never touches it).
PRESERVED_DAH="$(grep '^Described-Against-Hash: ' "$META" | awk '{print $2}')"
if [ "$PRESERVED_DAH" = "$ORIGINAL_HASH" ]; then
    assert "Described-Against-Hash preserved verbatim" true
else
    assert "Described-Against-Hash preserved (expected=$ORIGINAL_HASH got=$PRESERVED_DAH)" false
fi

# Staleness signal: Hash != Described-Against-Hash after body edit.
if [ "$NEW_HASH" != "$PRESERVED_DAH" ]; then
    assert "Hash != Described-Against-Hash → staleness detectable" true
else
    assert "Hash != Described-Against-Hash → staleness detectable" false
fi

# --- Test 3: save-hook latency on a sample edit (<500ms target) ---------
runs=()
for i in 1 2 3 4 5; do
    start=$(python3 -c 'import time; print(int(time.monotonic()*1000))')
    echo "{\"tool_input\":{\"file_path\":\"$TMP_PROJECT/backend/api/sample.py\"},\"cwd\":\"$TMP_PROJECT\"}" \
        | bash "$HOOK" >/dev/null 2>&1
    end=$(python3 -c 'import time; print(int(time.monotonic()*1000))')
    runs+=($((end - start)))
done
sorted=($(printf '%s\n' "${runs[@]}" | sort -n))
p95=${sorted[4]}
echo "  save-hook runs (ms): ${sorted[*]}"
if [ "$p95" -lt 500 ]; then
    assert "save-hook p95 < 500ms with description-preservation (was ${p95}ms)" true
else
    assert "save-hook p95 < 500ms with description-preservation (was ${p95}ms)" false
fi

echo
echo "test_save_preserves_descriptions: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
