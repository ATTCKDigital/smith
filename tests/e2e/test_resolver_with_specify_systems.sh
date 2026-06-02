#!/usr/bin/env bash
# Snapshot regression test for tier-1 (.specify/systems/<name>/spec.md).
#
# Builds a fixture project with two systems declared via frontmatter and
# asserts the resolver buckets files into the right system. Verifies the
# longest-prefix-wins rule and the fall-through to heuristic for files
# outside any declared path.
#
# Usage: bash tests/e2e/test_resolver_with_specify_systems.sh

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RESOLVER="$REPO/scripts/parsers/path-resolver.py"

TMP="$(mktemp -d -t smith-tier1-e2e-XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

PASS=0
FAIL=0
FAILED_TESTS=()

assert_eq() {
  local label="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    PASS=$((PASS + 1))
    echo "PASS  $label"
  else
    FAIL=$((FAIL + 1))
    FAILED_TESTS+=("$label (expected=$expected got=$actual)")
    echo "FAIL  $label (expected=$expected got=$actual)"
  fi
}

# Build fixture: two declared systems with overlapping prefixes.
mkdir -p "$TMP/.specify/systems/system-auth"
cat > "$TMP/.specify/systems/system-auth/spec.md" <<'EOF'
---
system: system-auth
status: active
paths:
  - services/auth/
---

# System Auth
EOF

mkdir -p "$TMP/.specify/systems/system-oauth"
cat > "$TMP/.specify/systems/system-oauth/spec.md" <<'EOF'
---
system: system-oauth
status: active
paths:
  - services/auth/oauth/
---

# System OAuth
EOF

resolve() {
  python3 "$RESOLVER" "$1" "$TMP"
}

# Tier 1: oauth (longer prefix) wins for files under services/auth/oauth/.
assert_eq "oauth file routes to system-oauth" "system-oauth" "$(resolve services/auth/oauth/cb.py)"
# Tier 1: auth wins for files under services/auth/ not in oauth.
assert_eq "auth file routes to system-auth" "system-auth" "$(resolve services/auth/session.py)"
# Tier 3 fallback: file outside any declared path uses heuristic.
assert_eq "billing file falls to heuristic" "system-billing" "$(resolve services/billing/main.py)"

echo
echo "Total: $((PASS + FAIL))  Passed: $PASS  Failed: $FAIL"

if [ "$FAIL" -ne 0 ]; then
  echo
  echo "Failures:"
  for t in "${FAILED_TESTS[@]}"; do
    echo "  - $t"
  done
  exit 1
fi

exit 0
