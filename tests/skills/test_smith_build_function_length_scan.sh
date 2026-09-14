#!/usr/bin/env bash
# test_smith_build_function_length_scan.sh — verifies /smith-build's pre-PR
# Function-Length Scan algorithm (skills/smith-build/SKILL.md §5.3.2, spec
# FR-15..FR-18). Direct sibling of test_smith_build_coverage_flag.sh
# (§5.3.1's own test): same mktemp-d/PASS-FAIL-assert/run_* harness shape.
# Unlike that file, this scan evaluates CURRENT file content only — no
# git-diff/prior-commit comparison — so fixture setup is just planted files.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
META_DESCRIBE_DIR="$REPO_ROOT/scripts/parsers"
PY_PARSER="$REPO_ROOT/scripts/parsers/parse-python.py"

if [ ! -f "$META_DESCRIBE_DIR/meta_describe.py" ] || [ ! -f "$PY_PARSER" ]; then
    echo "FAIL: meta_describe.py/parse-python.py not found under $META_DESCRIBE_DIR"
    exit 1
fi

TMP_PROJECT="$(mktemp -d -t sflscan-test.XXXXXX)"
trap 'rm -rf "$TMP_PROJECT"' EXIT
cd "$TMP_PROJECT" || exit 1

PASS=0
FAIL=0
assert() {
    if [ "$2" = "true" ]; then
        echo "PASS $1"; PASS=$((PASS + 1))
    else
        echo "FAIL $1"; FAIL=$((FAIL + 1))
    fi
}

# Fixture helper: a function named $1 whose body is $2 filler lines long.
make_fn() {
    echo "def $1(x):"
    echo '    """Doc."""'
    i=0
    while [ "$i" -lt "$2" ]; do echo "    y = $i"; i=$((i + 1)); done
    echo "    return x"
}

mkdir -p src node_modules/vendored_pkg
make_fn big_function 105 > src/big.py
{ make_fn soft_one 60; echo; make_fn soft_two 60; echo; make_fn soft_three 60; } > src/soft.py
make_fn tiny_function 10 > src/short.py
make_fn hidden_giant 200 > node_modules/vendored_pkg/lib.py
printf 'src/big.py\nsrc/soft.py\nsrc/short.py\nnode_modules/vendored_pkg/lib.py\n' \
    > /tmp/smith-build-changed.txt

# Reusable: run §5.3.2's algorithm (unchanged) against the current tree,
# calling the REAL qualifying_methods() — never re-deriving body-length logic.
run_function_length_scan() {
    > /tmp/smith-build-function-length-findings.txt
    while IFS= read -r f; do
        case "$f" in
            *.py|*.js|*.jsx|*.ts|*.tsx) ;;
            *) continue ;;
        esac
        [ -f "$f" ] || continue
        case "$f" in
            vendor/*|*/vendor/*|node_modules/*|*/node_modules/*|.venv/*|*/.venv/*|dist/*|*/dist/*|build/*|*/build/*|.smith/*|*/.smith/*) continue ;;
        esac
        CUR_JSON=$(python3 "$PY_PARSER" "$f" 2>/dev/null || true)
        [ -z "$CUR_JSON" ] && continue
        python3 - "$f" "$CUR_JSON" "$META_DESCRIBE_DIR" \
            >> /tmp/smith-build-function-length-findings.txt <<'PY' || true
import json, sys
rel, cur_json, md_dir = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, md_dir)
import meta_describe as md

try:
    with open(".smith/config.json") as f:
        config = json.load(f)
except Exception:
    config = None
quality = config.get("quality") if isinstance(config, dict) else None
fl = quality.get("function_length") if isinstance(quality, dict) else None
soft = int((fl or {}).get("soft", 50))
decompose = int((fl or {}).get("decompose", 100))

parsed = json.loads(cur_json)
entries = md.qualifying_methods(parsed, threshold=soft)
soft_count = 0
for e in entries:
    body = e["body_lines"]
    if body >= decompose:
        print(f"- `{rel}:{e['line']}` — `{e['name']}` ({body} lines, exceeds {decompose} — decompose)")
    else:
        soft_count += 1
if soft_count:
    print(f"__SOFT_COUNT__:{soft_count}")
PY
    done < /tmp/smith-build-changed.txt

    python3 - /tmp/smith-build-function-length-findings.txt <<'PY'
import sys
path = sys.argv[1]
with open(path) as f:
    lines = f.readlines()
total_soft, kept = 0, []
for line in lines:
    if line.startswith("__SOFT_COUNT__:"):
        total_soft += int(line.strip().split(":", 1)[1])
    else:
        kept.append(line)
if total_soft:
    kept.append(f"+ {total_soft} soft-tier warnings\n")
with open(path, "w") as f:
    f.writelines(kept)
PY
}

# --- Test 1: default thresholds (soft=50, decompose=100) ----------------
run_function_length_scan
OUT=$(cat /tmp/smith-build-function-length-findings.txt)

if echo "$OUT" | grep -q 'big.py:1.*big_function.*108 lines, exceeds 100 — decompose'; then
    assert "decompose-tier function (>=100) listed individually" true
else
    assert "decompose-tier function (>=100) listed individually" false
    echo "$OUT" | sed 's/^/  /'
fi

if echo "$OUT" | grep -qx '+ 3 soft-tier warnings'; then
    assert "50-99 range functions folded into one +3 line" true
else
    assert "50-99 range functions folded into one +3 line" false
    echo "$OUT" | sed 's/^/  /'
fi

echo "$OUT" | grep -q 'soft_one\|soft_two\|soft_three' \
    && assert "soft-tier functions never listed individually" false \
    || assert "soft-tier functions never listed individually" true

echo "$OUT" | grep -q 'tiny_function' \
    && assert "sub-50-line function absent from output entirely" false \
    || assert "sub-50-line function absent from output entirely" true

echo "$OUT" | grep -q 'hidden_giant' \
    && assert "excluded node_modules/ path produces NO findings" false \
    || assert "excluded node_modules/ path produces NO findings" true

# --- Test 2: quality.function_length override shifts tiers --------------
mkdir -p .smith
cat > .smith/config.json <<'EOF'
{"quality": {"function_length": {"soft": 30, "decompose": 60}}}
EOF
run_function_length_scan
OUT2=$(cat /tmp/smith-build-function-length-findings.txt)

if echo "$OUT2" | grep -q 'soft_one.*decompose' \
    && echo "$OUT2" | grep -q 'soft_two.*decompose' \
    && echo "$OUT2" | grep -q 'soft_three.*decompose'; then
    assert "override (soft=30/decompose=60) shifts soft.py fns to decompose-tier" true
else
    assert "override (soft=30/decompose=60) shifts soft.py fns to decompose-tier" false
    echo "$OUT2" | sed 's/^/  /'
fi

echo "$OUT2" | grep -q 'soft-tier warnings' \
    && assert "override: no soft-tier fold line remains (N=0, omitted)" false \
    || assert "override: no soft-tier fold line remains (N=0, omitted)" true

rm -f .smith/config.json /tmp/smith-build-changed.txt /tmp/smith-build-function-length-findings.txt

echo
echo "test_smith_build_function_length_scan: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
