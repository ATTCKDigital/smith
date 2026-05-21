#!/usr/bin/env bash
# tests/e2e/test_4tier_resolution.sh
#
# T106 — 4-tier context-manifest resolution + field-level merge.
#
# Tier order (lowest precedence → highest):
#   1. built-in fallback   — compiled into context-loader-lib.py
#   2. repo default        — skills/smith-index/templates/context-manifest.default.json
#   3. user global         — ~/.smith/config/context-manifest.json (HOME sandboxed)
#   4. project override    — .smith/index/config/context-manifest.json
#
# Verifies:
#   - All four tiers' labels are reported in the injection header
#     (`tier=1,2,3,4`) when all four are populated.
#   - Project tier 4 overrides global tier 3 (and global overrides repo).
#   - Field-level merge: a project file that overrides one nested key
#     (e.g. vault.sessions=99) does not wipe out sibling keys
#     (vault.ledger should retain the global/repo value).
#
# We sandbox HOME so we can fake the tier-3 file without touching the
# real ~/.smith/.

set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
HELPER="${REPO_ROOT}/hooks/context-loader-lib.py"

if [ ! -f "$HELPER" ]; then
    echo "FAIL: helper not found: $HELPER"
    exit 1
fi

TMPDIR_TEST="/tmp/smith-e2e-4tier-$$"
mkdir -p "$TMPDIR_TEST/project/.smith/index/config"
mkdir -p "$TMPDIR_TEST/home/.smith/config"
trap 'rm -rf "$TMPDIR_TEST"' EXIT

PASS=0
FAIL=0
TEST_NAME="T106-4tier-resolution"

pass() { printf '  PASS %s\n' "$1"; PASS=$((PASS+1)); }
fail() { printf '  FAIL %s\n' "$1" >&2; FAIL=$((FAIL+1)); }

PROJ="$TMPDIR_TEST/project"
SANDBOX_HOME="$TMPDIR_TEST/home"

# Tier 3 (user global) — overrides vault.ledger.
cat > "$SANDBOX_HOME/.smith/config/context-manifest.json" <<'EOF'
{
  "_meta": {"version": 1, "tier_label": "user-global"},
  "smith-bugfix": {
    "vault": {
      "ledger": "from-global"
    }
  }
}
EOF

# Tier 4 (project) — overrides ONLY vault.sessions (=99). The merge
# logic must NOT wipe out vault.ledger from tier 3 nor vault.bank from
# repo defaults.
cat > "$PROJ/.smith/index/config/context-manifest.json" <<'EOF'
{
  "_meta": {"version": 1, "tier_label": "project"},
  "smith-bugfix": {
    "vault": {
      "sessions": 99
    },
    "navigator": false
  }
}
EOF

echo "[$TEST_NAME] sandbox HOME=$SANDBOX_HOME PROJ=$PROJ"

# Resolve via the lib CLI.
HOME="$SANDBOX_HOME" python3 "$HELPER" resolve-config smith-bugfix "$PROJ" \
    > "$TMPDIR_TEST/resolved.json" 2>"$TMPDIR_TEST/resolved.err" || true

cat "$TMPDIR_TEST/resolved.json" | sed 's/^/    /'

# Parse output.
RES_JSON="$(cat "$TMPDIR_TEST/resolved.json")"

# Check tiers list includes 1,2,3,4.
if echo "$RES_JSON" | python3 -c "
import json, sys
d = json.load(sys.stdin)
tiers = d.get('_tiers', [])
assert '1' in tiers, f'missing tier 1: {tiers}'
assert '2' in tiers, f'missing tier 2 (repo default): {tiers}'
assert '3' in tiers, f'missing tier 3 (user global): {tiers}'
assert '4' in tiers, f'missing tier 4 (project): {tiers}'
" 2>/dev/null; then
    pass "all 4 tiers contributed to merge"
else
    fail "tier merge did not include all 4 tiers (got: $RES_JSON)"
fi

# Project tier should win for vault.sessions.
if echo "$RES_JSON" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d['vault']['sessions'] == 99, d['vault']['sessions']
" 2>/dev/null; then
    pass "tier 4 wins: vault.sessions=99"
else
    fail "tier 4 should override vault.sessions; got: $RES_JSON"
fi

# Global tier should still provide vault.ledger (because project didn't
# touch it — field-level merge preserves sibling keys).
if echo "$RES_JSON" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d['vault']['ledger'] == 'from-global', d['vault']['ledger']
" 2>/dev/null; then
    pass "field-level merge: vault.ledger from tier 3 retained"
else
    fail "tier 3 vault.ledger should survive field-merge; got: $RES_JSON"
fi

# Repo default (tier 2) should still contribute vault.bank for smith-bugfix
# (which is "recent" by default).
if echo "$RES_JSON" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d['vault']['bank'] == 'recent', d['vault']['bank']
" 2>/dev/null; then
    pass "field-level merge: vault.bank from tier 2 retained"
else
    fail "tier 2 vault.bank should survive field-merge; got: $RES_JSON"
fi

# navigator field: project=false should override repo default=true.
if echo "$RES_JSON" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d['navigator'] is False, d['navigator']
" 2>/dev/null; then
    pass "scalar replace: navigator=false (project) overrides true (repo default)"
else
    fail "navigator override broken; got: $RES_JSON"
fi

# Negative test: only tier 1 + tier 2 (no tier 3/4) → tiers should be ['1','2'].
PROJ2="$TMPDIR_TEST/project_minimal"
mkdir -p "$PROJ2"
HOME2="$TMPDIR_TEST/home_empty"
mkdir -p "$HOME2"
HOME="$HOME2" python3 "$HELPER" resolve-config smith-bugfix "$PROJ2" \
    > "$TMPDIR_TEST/min.json" 2>/dev/null || true
if python3 -c "
import json
d = json.load(open('$TMPDIR_TEST/min.json'))
tiers = d.get('_tiers', [])
assert '1' in tiers, tiers
assert '2' in tiers, tiers
assert '3' not in tiers, tiers
assert '4' not in tiers, tiers
" 2>/dev/null; then
    pass "minimal project: tiers=['1','2'] only"
else
    fail "minimal project should only see tiers 1+2"
fi

echo
echo "[$TEST_NAME] PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
