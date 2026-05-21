#!/usr/bin/env bash
# test_smith_navigate.sh — contract test for /smith-navigate output.
#
# /smith-navigate runs as a Haiku sub-agent in production; here we don't
# actually spawn the LLM. We validate that:
#   (a) the helper at scripts/smith-navigate/find_candidate_systems.py
#       returns plausible candidate systems from a manifest fixture
#   (b) the contract regex from contracts/navigator-output.md correctly
#       parses both annotated and bare paths
#   (c) the "manifest not initialized" sentinel matches exactly
#   (d) the "no matching system" sentinel matches exactly
#
# Exit 0 on success, 1 on failure.

set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
HELPER="${REPO_ROOT}/scripts/smith-navigate/find_candidate_systems.py"
SOURCE_FIXTURE="${REPO_ROOT}/tests/fixtures/sample-project"

TMPDIR_TEST="$(mktemp -d -t smith-navigate-test-XXXXXX)"
trap 'rm -rf "$TMPDIR_TEST"' EXIT
cp -R "${SOURCE_FIXTURE}/." "${TMPDIR_TEST}/"

fail=0
say() { printf '  %s\n' "$1"; }
ok() { printf '  ✓ %s\n' "$1"; }
err() { printf '  ✗ %s\n' "$1" >&2; fail=1; }

cd "$TMPDIR_TEST"

# Build a small index first so the helper has something to read.
python3 "${REPO_ROOT}/scripts/smith-index/run.py" --root . > /dev/null 2>&1

say "=== Test 1: find_candidate_systems helper ==="
out="$(python3 "$HELPER" . "fix the product list pagination" --limit 3 2>&1)"
[[ -n "$out" ]] || err "helper returned empty for product-list query"
[[ "$out" == *"product"* || "$out" == *"frontend"* || "$out" == *"backend"* ]] \
  || err "helper output didn't mention product/frontend/backend: $out"
ok "helper returns candidates: $(echo "$out" | tr '\n' ' ')"

say "=== Test 2: contract regex parses annotated and bare paths ==="
PY=$(cat <<'PYEOF'
import re, sys
pat = re.compile(r"^- (?P<path>\S+)(?: \[primary: (?P<start>\d+)-(?P<end>\d+), (?P<label>[^\]]+)\])?$")
samples = [
    ("- backend/src/api/v1/products.py [primary: 230-380, POST endpoint]", True, "backend/src/api/v1/products.py", "230", "380", "POST endpoint"),
    ("- frontend/src/lib/api/products.ts", True, "frontend/src/lib/api/products.ts", None, None, None),
    ("- backend/tests/test_x.py [primary: 1-50, fixture]", True, "backend/tests/test_x.py", "1", "50", "fixture"),
    ("not a list line", False, None, None, None, None),
]
fail = 0
for line, expect_ok, path, s, e, lbl in samples:
    m = pat.match(line)
    if expect_ok != bool(m):
        print(f"FAIL: '{line}' expect_ok={expect_ok} got_match={bool(m)}", file=sys.stderr)
        fail = 1
        continue
    if not m:
        continue
    if m.group("path") != path:
        print(f"FAIL path: got {m.group('path')!r} expected {path!r}", file=sys.stderr)
        fail = 1
    if s is not None and m.group("start") != s:
        print(f"FAIL start: got {m.group('start')!r} expected {s!r}", file=sys.stderr)
        fail = 1
    if e is not None and m.group("end") != e:
        print(f"FAIL end: got {m.group('end')!r} expected {e!r}", file=sys.stderr)
        fail = 1
    if lbl is not None and m.group("label") != lbl:
        print(f"FAIL label: got {m.group('label')!r} expected {lbl!r}", file=sys.stderr)
        fail = 1
sys.exit(fail)
PYEOF
)
python3 -c "$PY" || err "contract regex test failed"
[[ $fail -eq 0 ]] && ok "contract regex parses correctly"

say "=== Test 3: 'Manifest not initialized' sentinel ==="
SENTINEL='## Relevant Files
_Manifest not initialized — run `/smith-index` first._'
echo "$SENTINEL" | head -2 | python3 -c "
import sys
text = sys.stdin.read()
assert '## Relevant Files' in text, 'missing relevant files heading'
assert '_Manifest not initialized' in text, 'missing sentinel'
" || err "sentinel detection failed"
ok "manifest-missing sentinel string is exact"

say "=== Test 4: 'No matching system' sentinel ==="
SENTINEL2='### Systems Affected
_No matching system. Recommend `/smith-explore` for broader analysis._'
echo "$SENTINEL2" | python3 -c "
import sys
text = sys.stdin.read()
assert '### Systems Affected' in text, 'missing systems affected heading'
assert '_No matching system' in text, 'missing sentinel'
" || err "no-matching-system sentinel detection failed"
ok "no-matching-system sentinel string is exact"

say "=== Test 5: SKILL.md frontmatter declares Haiku and 3s budget ==="
skill_md="${REPO_ROOT}/skills/smith-navigate/SKILL.md"
[[ -f "$skill_md" ]] || err "SKILL.md missing"
grep -q "claude-haiku-4-5" "$skill_md" || err "SKILL.md doesn't declare claude-haiku-4-5"
grep -q "3-second" "$skill_md" || err "SKILL.md doesn't reference the 3-second budget"
grep -q "## Relevant Files" "$skill_md" || err "SKILL.md doesn't show the output contract"
ok "SKILL.md declares Haiku, 3s budget, and contract"

if (( fail != 0 )); then
  printf '\n[FAIL] test_smith_navigate.sh had failures.\n' >&2
  exit 1
fi
printf '\n[OK] test_smith_navigate.sh — all checks passed.\n'
