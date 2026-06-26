#!/usr/bin/env bash
# Unit tests for context-budget-guard.sh (PostToolUse Write|Edit hook).
#
# Verifies:
#   - Small file (<= threshold) → silent, exit 0
#   - Large non-@-referenced file → generic soft-cap warning on stderr
#   - Large @-referenced file (in CLAUDE.md) → loud @-referenced warning
#   - Threshold is configurable via .smith/config.json (context_budget.max_file_kb)
#   - max_file_kb = 0 disables the guard
#   - Hook never blocks (always exits 0) and tolerates missing file / bad JSON
#   - settings/smith-settings-fragment.json wires the hook in the Write|Edit
#     chain BEFORE manifest-updater.sh (which must remain LAST)
#
# Run:
#   bash tests/hooks/test_context_budget_guard.sh

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
HOOK="$REPO/hooks/context-budget-guard.sh"
FRAGMENT="$REPO/settings/smith-settings-fragment.json"
CONFIG_DEFAULT="$REPO/templates/config.default.json"

PASS=0
FAIL=0
FAILED_NAMES=()

assert() {
    if [ "$2" = "true" ]; then
        PASS=$((PASS+1))
    else
        FAIL=$((FAIL+1))
        FAILED_NAMES+=("$1")
        echo "FAIL $1"
    fi
}

run_hook() {
    # $1 = project dir, $2 = file path
    echo "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$2\"}}" \
        | CLAUDE_PROJECT_DIR="$1" bash "$HOOK" 2>&1
}

WORK=$(mktemp -d -t cbg.XXXXXX)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/.smith" "$WORK/docs"

# --- small file → silent --------------------------------------------------
echo "small content" > "$WORK/docs/small.md"
OUT=$(run_hook "$WORK" "$WORK/docs/small.md")
[ -z "$OUT" ] && assert "small file silent" true || assert "small file silent (got: $OUT)" false

# --- large non-@-ref file → generic warning -------------------------------
python3 -c "open('$WORK/docs/big.md','w').write('x'*60000)"
OUT=$(run_hook "$WORK" "$WORK/docs/big.md")
echo "$OUT" | grep -q "soft cap" && assert "large file generic warning" true \
    || assert "large file generic warning (got: $OUT)" false
echo "$OUT" | grep -q "@-referenced" && assert "non-@-ref must NOT claim @-ref (got: $OUT)" false \
    || assert "non-@-ref not flagged as @-ref" true

# --- large @-ref file → loud warning --------------------------------------
printf '# CLAUDE.md\n@docs/big.md\n' > "$WORK/CLAUDE.md"
OUT=$(run_hook "$WORK" "$WORK/docs/big.md")
echo "$OUT" | grep -q "@-referenced from CLAUDE.md" && assert "@-ref file loud warning" true \
    || assert "@-ref file loud warning (got: $OUT)" false

# --- @-ref detection by basename too --------------------------------------
printf '# CLAUDE.md\n@big.md\n' > "$WORK/CLAUDE.md"
OUT=$(run_hook "$WORK" "$WORK/docs/big.md")
echo "$OUT" | grep -q "@-referenced from CLAUDE.md" && assert "@-ref detected by basename" true \
    || assert "@-ref detected by basename (got: $OUT)" false
rm -f "$WORK/CLAUDE.md"

# --- configurable threshold (raise to 100KB → 60KB file silent) -----------
echo '{"context_budget":{"max_file_kb":100}}' > "$WORK/.smith/config.json"
OUT=$(run_hook "$WORK" "$WORK/docs/big.md")
[ -z "$OUT" ] && assert "threshold raised silences 60KB" true \
    || assert "threshold raised silences 60KB (got: $OUT)" false

# --- max_file_kb=0 disables -----------------------------------------------
echo '{"context_budget":{"max_file_kb":0}}' > "$WORK/.smith/config.json"
OUT=$(run_hook "$WORK" "$WORK/docs/big.md")
[ -z "$OUT" ] && assert "max_file_kb=0 disables" true \
    || assert "max_file_kb=0 disables (got: $OUT)" false

# --- default 50KB when no config ------------------------------------------
rm -f "$WORK/.smith/config.json"
OUT=$(run_hook "$WORK" "$WORK/docs/big.md")
echo "$OUT" | grep -q "50 KB soft cap" && assert "defaults to 50KB without config" true \
    || assert "defaults to 50KB without config (got: $OUT)" false

# --- never blocks (exit 0) ------------------------------------------------
echo "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$WORK/docs/big.md\"}}" \
    | CLAUDE_PROJECT_DIR="$WORK" bash "$HOOK" >/dev/null 2>&1
assert "exits 0 on warning" "$([ $? -eq 0 ] && echo true || echo false)"

# --- missing file → silent ------------------------------------------------
OUT=$(run_hook "$WORK" "$WORK/nope.md")
[ -z "$OUT" ] && assert "missing file silent" true || assert "missing file silent (got: $OUT)" false

# --- malformed JSON → no crash --------------------------------------------
OUT=$(echo "not json" | CLAUDE_PROJECT_DIR="$WORK" bash "$HOOK" 2>&1)
assert "malformed JSON exits 0" "$([ $? -eq 0 ] && echo true || echo false)"

# --- settings fragment wiring ---------------------------------------------
python3 -c "import json; json.load(open('$FRAGMENT'))" 2>/dev/null \
    && assert "settings fragment valid JSON" true || assert "settings fragment valid JSON" false

# context-budget-guard registered in a Write|Edit block, BEFORE manifest-updater
ORDER_OK=$(python3 -c "
import json
s = json.load(open('$FRAGMENT'))
for block in s['hooks']['PostToolUse']:
    if block.get('matcher') == 'Write|Edit':
        cmds = [h['command'] for h in block['hooks']]
        cbg = next((i for i,c in enumerate(cmds) if 'context-budget-guard' in c), None)
        mu  = next((i for i,c in enumerate(cmds) if 'manifest-updater' in c), None)
        if cbg is not None and mu is not None and cbg < mu:
            print('1'); break
else:
    print('0')
" 2>/dev/null)
[ "$ORDER_OK" = "1" ] && assert "guard wired before manifest-updater in Write|Edit" true \
    || assert "guard wired before manifest-updater in Write|Edit" false

# --- config default has the key -------------------------------------------
HAS_KEY=$(python3 -c "import json; d=json.load(open('$CONFIG_DEFAULT')); print('1' if d.get('context_budget',{}).get('max_file_kb')==50 else '0')" 2>/dev/null)
[ "$HAS_KEY" = "1" ] && assert "config.default seeds max_file_kb=50" true \
    || assert "config.default seeds max_file_kb=50" false

# --- summary --------------------------------------------------------------
echo "context-budget-guard tests: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || { printf 'failed: %s\n' "${FAILED_NAMES[@]}"; exit 1; }
