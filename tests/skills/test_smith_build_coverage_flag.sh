#!/usr/bin/env bash
# test_smith_build_coverage_flag.sh — verify the /smith-build PR-description
# coverage flag algorithm from skills/smith-build/SKILL.md Step 5.3.1
# (data-model.md §9).
#
# Covers task T083:
#  - Synthetic: a file with a new method but no .meta description → coverage
#    flag listed.
#  - Synthetic: same file with description present → no warning.
#  - File with no changes → no warning.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PARSER="$REPO_ROOT/scripts/parsers/parse-python.py"

if [ ! -f "$PARSER" ]; then
    echo "FAIL: parser not found: $PARSER"
    exit 1
fi

TMP_PROJECT="$(mktemp -d -t scov-test.XXXXXX)"
trap 'rm -rf "$TMP_PROJECT"' EXIT

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

# Initialize a git repo with a `main` branch carrying the baseline file,
# then check out a feature branch and add a new function.
cd "$TMP_PROJECT"
git init -q -b main >/dev/null 2>&1 || git init -q >/dev/null 2>&1
git config user.email "test@example.com"
git config user.name "Test"

mkdir -p backend/src .smith/scripts
cp "$REPO_ROOT/scripts/parsers/parse-python.py" .smith/scripts/parse-python.py
chmod +x .smith/scripts/parse-python.py

cat > backend/src/widget.py <<'EOF'
def existing(x):
    """Was here on main."""
    return x * 2
EOF

git add . >/dev/null 2>&1
git commit -q -m "baseline" >/dev/null 2>&1

# Ensure we are on a branch named "main" (init -b main might not be supported
# on older git).
git branch -m main 2>/dev/null || true

git checkout -q -b feature >/dev/null 2>&1
cat > backend/src/widget.py <<'EOF'
def existing(x):
    """Was here on main."""
    return x * 2

def freshly_added(x, y):
    """New function added in this PR."""
    total = x + y
    if total > 100:
        return total // 2
    return total
EOF
git add backend/src/widget.py >/dev/null 2>&1
git commit -q -m "add freshly_added" >/dev/null 2>&1

# Reusable: run the Step 5.3.1 algorithm against the current working tree.
run_coverage() {
    git diff main --name-only > /tmp/smith-build-changed.txt
    > /tmp/smith-build-coverage-misses.txt
    while IFS= read -r f; do
        case "$f" in
            *.py|*.js|*.jsx|*.ts|*.tsx) ;;
            *) continue ;;
        esac
        [ -f "$f" ] || continue
        case "$f" in
            vendor/*|*/vendor/*|node_modules/*|*/node_modules/*|.venv/*|*/.venv/*|dist/*|*/dist/*|build/*|*/build/*|.smith/*|*/.smith/*) continue ;;
        esac
        PARSER_CMD="python3 .smith/scripts/parse-python.py"
        CUR_JSON=$($PARSER_CMD "$f" 2>/dev/null || true)
        [ -z "$CUR_JSON" ] && continue
        python3 - "$f" "$CUR_JSON" >> /tmp/smith-build-coverage-misses.txt <<'PY' || true
import json, os, sys, subprocess, re, tempfile, pathlib

rel = sys.argv[1]
cur = json.loads(sys.argv[2])

head_methods = []
for fn in cur.get("functions") or []:
    fid = fn.get("id")
    name = fn.get("name", "")
    if fid:
        head_methods.append((fid, f"{rel}::{name}"))
for cls in cur.get("classes") or []:
    cname = cls.get("name", "")
    for m in cls.get("methods") or []:
        mid = m.get("id")
        mname = m.get("name", "")
        if mid:
            head_methods.append((mid, f"{rel}::{cname}::{mname}"))

try:
    main_src = subprocess.check_output(
        ["git", "show", f"main:{rel}"], stderr=subprocess.DEVNULL
    ).decode("utf-8", errors="replace")
except subprocess.CalledProcessError:
    main_src = None

prev_ids = set()
if main_src is not None:
    suffix = pathlib.Path(rel).suffix
    parser_cmd = ""
    if suffix == ".py":
        for cand in (".smith/scripts/parse-python.py",
                     os.path.expanduser("~/.smith/scripts/parse-python.py"),
                     "scripts/parsers/parse-python.py"):
            if os.path.isfile(cand):
                parser_cmd = f"python3 {os.path.abspath(cand)}"
                break
    if parser_cmd:
        with tempfile.TemporaryDirectory() as scratch:
            staged = os.path.join(scratch, rel)
            os.makedirs(os.path.dirname(staged), exist_ok=True)
            with open(staged, "w", encoding="utf-8") as fh:
                fh.write(main_src)
            try:
                out = subprocess.check_output(
                    parser_cmd.split() + [rel],
                    stderr=subprocess.DEVNULL,
                    cwd=scratch,
                )
                prev = json.loads(out.decode("utf-8", errors="replace"))
                for fn in prev.get("functions") or []:
                    if fn.get("id"):
                        prev_ids.add(fn["id"])
                for cls in prev.get("classes") or []:
                    for m in cls.get("methods") or []:
                        if m.get("id"):
                            prev_ids.add(m["id"])
            except (subprocess.CalledProcessError, json.JSONDecodeError):
                pass

touched = [(fid, qname) for (fid, qname) in head_methods if fid not in prev_ids]

meta_path = os.path.join(".smith", "index", "files", rel + ".meta")
desc_ids = set()
if os.path.isfile(meta_path):
    in_funcs = False
    current_id = None
    with open(meta_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith("## Functions") or line.startswith("## Classes"):
                in_funcs = True
                current_id = None
                continue
            if line.startswith("## ") and in_funcs:
                in_funcs = False
                current_id = None
                continue
            if in_funcs:
                m = re.match(r"^\s*Id:\s+(\S+)", line)
                if m:
                    current_id = m.group(1)
                    continue
                m = re.match(r"^\s*Description:\s+(.+)$", line)
                if m and current_id:
                    if m.group(1).strip():
                        desc_ids.add(current_id)
                    current_id = None

for fid, qname in touched:
    if fid not in desc_ids:
        print(f"- {qname} (id: {fid})")
PY
    done < /tmp/smith-build-changed.txt
}

# --- Test 1: new method, no .meta → coverage flag includes it ----------
run_coverage
if grep -q "widget.py::freshly_added" /tmp/smith-build-coverage-misses.txt; then
    assert "new method without .meta listed in coverage" true
else
    assert "new method without .meta listed in coverage" false
    echo "  --- misses content ---"
    sed 's/^/  /' /tmp/smith-build-coverage-misses.txt
fi

# Existing method (unchanged in diff) should NOT appear.
if grep -q "widget.py::existing" /tmp/smith-build-coverage-misses.txt; then
    assert "untouched existing method NOT in coverage" false
    echo "  --- misses content ---"
    sed 's/^/  /' /tmp/smith-build-coverage-misses.txt
else
    assert "untouched existing method NOT in coverage" true
fi

# --- Test 2: same file but .meta now has a description → no warning ----
# Look up the id of freshly_added to seed the .meta.
FRESH_ID=$(python3 .smith/scripts/parse-python.py backend/src/widget.py | python3 -c '
import json, sys
d = json.load(sys.stdin)
for fn in d["functions"]:
    if fn["name"] == "freshly_added":
        print(fn["id"])
        break
')
[ -n "$FRESH_ID" ] && assert "harvested freshly_added id" true \
    || assert "harvested freshly_added id" false

mkdir -p .smith/index/files/backend/src
cat > .smith/index/files/backend/src/widget.py.meta <<EOF
# backend/src/widget.py
Last Updated: 2026-06-02T00:00:00Z
Language: python
Lines: 8
Hash: deadbeefcafef00d1234567890abcdef1234567890abcdef1234567890abcdef
**Description:** Widget helpers used by the build pipeline.
Described-Against-Hash: deadbeefcafef00d1234567890abcdef1234567890abcdef1234567890abcdef
Described-At: 2026-06-02T00:00:00Z

## Imports
_None._

## Routes
_None._

## Classes
_None._

## Functions
- \`existing(x)\` (line 1)
  Id: 0000000000000000
- \`freshly_added(x, y)\` (line 5)
  Id: $FRESH_ID
  Description: Computes the sum of x and y, halving when over 100.

## Exports
_None._

## Parse Errors
_None._
EOF

run_coverage
if [ -s /tmp/smith-build-coverage-misses.txt ]; then
    assert "described new method NOT in coverage" false
    echo "  --- misses content ---"
    sed 's/^/  /' /tmp/smith-build-coverage-misses.txt
else
    assert "described new method NOT in coverage" true
fi

# --- Test 3: no changes vs main → no warnings -------------------------
git checkout -q main >/dev/null 2>&1
run_coverage
if [ -s /tmp/smith-build-coverage-misses.txt ]; then
    assert "clean tree → no coverage warnings" false
    echo "  --- misses content ---"
    sed 's/^/  /' /tmp/smith-build-coverage-misses.txt
else
    assert "clean tree → no coverage warnings" true
fi

echo
echo "test_smith_build_coverage_flag: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
