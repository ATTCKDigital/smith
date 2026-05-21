#!/usr/bin/env bash
# test_smith_index.sh — smoke test for /smith-index against the sample fixture.
#
# Verifies:
#   (a) first full run produces all expected artifacts
#   (b) --check on a freshly-built index reports zero staleness
#   (c) touching a file makes --check report it stale
#   (d) --migrate-templates appends missing sections and is idempotent
#   (e) total runtime well under the 60s budget for the small fixture
#
# Exit 0 on success, 1 on failure.

set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNNER="${REPO_ROOT}/scripts/smith-index/run.py"
SOURCE_FIXTURE="${REPO_ROOT}/tests/fixtures/sample-project"

TMPDIR_TEST="$(mktemp -d -t smith-index-test-XXXXXX)"
trap 'rm -rf "$TMPDIR_TEST"' EXIT

cp -R "${SOURCE_FIXTURE}/." "${TMPDIR_TEST}/"

fail=0
say() { printf '  %s\n' "$1"; }
ok() { printf '  ✓ %s\n' "$1"; }
err() { printf '  ✗ %s\n' "$1" >&2; fail=1; }

cd "$TMPDIR_TEST"

say "=== Test 1: full rebuild ==="
start_ts=$(date +%s)
out="$(python3 "$RUNNER" --root . 2>&1)"
end_ts=$(date +%s)
elapsed=$((end_ts - start_ts))

[[ -f .smith/index/manifest.md ]] || err "manifest.md missing"
[[ -d .smith/index/files ]]       || err ".smith/index/files dir missing"
[[ -d .smith/index/systems ]]     || err ".smith/index/systems dir missing"
[[ "$out" == *"files indexed"* ]] || err "summary line missing: $out"
(( elapsed < 60 )) || err "took ${elapsed}s, exceeds 60s budget"

meta_count=$(find .smith/index/files -name '*.meta' | wc -l | tr -d ' ')
[[ "$meta_count" -gt 0 ]] || err "no .meta files produced"

manifest_lines=$(wc -l < .smith/index/manifest.md | tr -d ' ')
(( manifest_lines <= 50 )) || err "manifest.md is ${manifest_lines} lines (>50)"

for sysf in .smith/index/systems/*.md; do
  lc=$(wc -l < "$sysf" | tr -d ' ')
  (( lc <= 80 )) || err "$sysf is $lc lines (>80)"
done

[[ $fail -eq 0 ]] && ok "full rebuild: $meta_count metas, ${elapsed}s, manifest ${manifest_lines} lines"

say "=== Test 2: --check reports fresh ==="
out2="$(python3 "$RUNNER" --root . --check 2>&1)"
[[ "$out2" == *"0 stale"* ]] || err "expected '0 stale', got: $out2"
[[ "$out2" == *"0 missing-source"* ]] || err "expected '0 missing-source', got: $out2"
ok "--check reports fresh"

say "=== Test 3: touch a file, --check detects staleness ==="
echo "# stale-trigger" >> backend/src/api/v1/products.py
out3="$(python3 "$RUNNER" --root . --check 2>&1)"
[[ "$out3" == *"1 stale"* ]] || err "expected '1 stale', got: $out3"
[[ "$out3" == *"backend/src/api/v1/products.py"* ]] || err "expected stale file path in output"
ok "--check detects edited file"

say "=== Test 4: --migrate-templates ==="
cat > CLAUDE.md <<'EOF'
# Project CLAUDE.md
some content
EOF
cat > constitution.md <<'EOF'
# Constitution
some content
EOF
out4="$(python3 "$RUNNER" --root . --migrate-templates 2>&1)"
[[ "$out4" == *"2 file(s) updated"* ]] || err "expected '2 file(s) updated', got: $out4"
grep -q "## File Size Policy" constitution.md || err "constitution.md missing File Size Policy"
grep -q "## Project Manifest" constitution.md || err "constitution.md missing Project Manifest"
grep -q "## Smith Context System" CLAUDE.md || err "CLAUDE.md missing Smith Context System"
grep -q "## File Size Awareness" CLAUDE.md || err "CLAUDE.md missing File Size Awareness"
ls CLAUDE.md.bak.* >/dev/null 2>&1 || err "no CLAUDE.md backup created"
ls constitution.md.bak.* >/dev/null 2>&1 || err "no constitution.md backup created"
ok "--migrate-templates appends missing sections + creates backups"

say "=== Test 5: --migrate-templates idempotency ==="
out5="$(python3 "$RUNNER" --root . --migrate-templates 2>&1)"
[[ "$out5" == *"0 file(s) updated"* ]] || err "expected idempotent no-op, got: $out5"
ok "--migrate-templates is idempotent"

if (( fail != 0 )); then
  printf '\n[FAIL] test_smith_index.sh had failures.\n' >&2
  exit 1
fi

printf '\n[OK] test_smith_index.sh — all checks passed (%ss total).\n' "$elapsed"
