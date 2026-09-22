#!/usr/bin/env bash
# uninstall-hook-coverage.test.sh — FR-63 / SC-18.
#
# Guards a repo-wide invariant, not a feature: **everything install.sh copies
# into ~/.claude/hooks/, uninstall.sh removes.** Its own flat file rather than a
# case inside tests/smith-activity.test.sh because the invariant outlives
# feature 60 — the next hook anyone adds is the one this catches.
#
# The drift it exists to stop is not hypothetical. At the time this test was
# written the repo shipped 20 hooks/*.sh and scripts/uninstall.sh's SMITH_HOOKS
# array named 11 of them, so a Smith uninstall left 9 hook scripts behind —
# including workflow-gate.sh, which keeps denying tool calls after the operator
# believes Smith is gone. hooks/pricing.json had never been removed either,
# and workflow_summary_lib.py was absent from the helper array.
#
# Three assertions, all derived from the filesystem — none of them may ever be
# a transcribed count. A number written into this file is the same bug the file
# exists to catch, one level up.
#
#   1. every hooks/*.sh   appears in uninstall.sh's SMITH_HOOKS
#   2. every hooks/*.py   appears in uninstall.sh's SMITH_HOOK_HELPERS
#      every hooks/*.json appears in uninstall.sh's SMITH_HOOK_DATA
#   3. install.sh's hook-count install preview is DERIVED, not hardcoded
#
# Run: bash tests/uninstall-hook-coverage.test.sh
# CI:  .github/workflows/test-install.yml globs tests/*.test.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"

UNINSTALL="$REPO_ROOT/scripts/uninstall.sh"
INSTALL="$REPO_ROOT/scripts/install.sh"

PASS=0
FAIL=0
assert() {
    local ok="$1" msg="$2"
    if [ "$ok" = "0" ]; then
        printf '  ok   %s\n' "$msg"
        PASS=$((PASS + 1))
    else
        printf '  FAIL %s\n' "$msg"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== tests/uninstall-hook-coverage.test.sh ==="

[ -f "$UNINSTALL" ] || { echo "FATAL: $UNINSTALL not found"; exit 1; }
[ -f "$INSTALL" ]   || { echo "FATAL: $INSTALL not found"; exit 1; }

# ---------------------------------------------------------------------------
# array_entries <array-name> — the whitespace-separated words of a bash array
# literal in uninstall.sh, however many lines it is spread across.
#
# Read with sed/tr rather than by sourcing uninstall.sh: that script runs an
# interactive uninstall on load. A parser is the only safe reader.
# ---------------------------------------------------------------------------
array_entries() {
    local name="$1"
    sed -n "/^${name}=(/,/^)/p" "$UNINSTALL" \
        | sed -e "s/^${name}=(//" -e 's/^)//' -e 's/#.*//' \
        | tr -s ' \t' '\n' \
        | sed -e 's/^ *//' -e 's/ *$//' \
        | grep -v '^$' \
        | sort -u
}

# ---------------------------------------------------------------------------
# Assertion 1 — every shipped hooks/*.sh is removed by uninstall.sh
# ---------------------------------------------------------------------------
SHIPPED_SH=$(cd "$REPO_ROOT/hooks" && ls -1 *.sh 2>/dev/null | sort -u)
LISTED_SH=$(array_entries SMITH_HOOKS)

SHIPPED_COUNT=$(printf '%s\n' "$SHIPPED_SH" | grep -c . || true)
LISTED_COUNT=$(printf '%s\n' "$LISTED_SH" | grep -c . || true)
echo "  (repo ships $SHIPPED_COUNT hooks/*.sh; SMITH_HOOKS names $LISTED_COUNT)"

MISSING_SH=$(comm -23 <(printf '%s\n' "$SHIPPED_SH") <(printf '%s\n' "$LISTED_SH"))
if [ -n "$MISSING_SH" ]; then
    assert 1 "every hooks/*.sh appears in SMITH_HOOKS"
    echo "       uninstall.sh would leave these behind in ~/.claude/hooks/:"
    printf '         - %s\n' $MISSING_SH
else
    assert 0 "every hooks/*.sh appears in SMITH_HOOKS"
fi

# The other direction: a name in the array that the repo no longer ships is
# dead weight, and — worse — reads as coverage. Not fatal, but reported.
STALE_SH=$(comm -13 <(printf '%s\n' "$SHIPPED_SH") <(printf '%s\n' "$LISTED_SH"))
if [ -n "$STALE_SH" ]; then
    echo "  note SMITH_HOOKS names hooks the repo no longer ships (harmless, but stale):"
    printf '         - %s\n' $STALE_SH
fi

# ---------------------------------------------------------------------------
# Assertion 2 — the Python helpers and JSON data files install.sh copies
# alongside the hooks are removed too. Same invariant, same drift, and
# hooks/pricing.json is the live proof of what a third uncovered enumeration
# costs (FR-62).
# ---------------------------------------------------------------------------
SHIPPED_PY=$(cd "$REPO_ROOT/hooks" && ls -1 *.py 2>/dev/null | sort -u)
LISTED_PY=$(array_entries SMITH_HOOK_HELPERS)
MISSING_PY=$(comm -23 <(printf '%s\n' "$SHIPPED_PY") <(printf '%s\n' "$LISTED_PY"))
if [ -n "$MISSING_PY" ]; then
    assert 1 "every hooks/*.py appears in SMITH_HOOK_HELPERS"
    printf '         - %s\n' $MISSING_PY
else
    assert 0 "every hooks/*.py appears in SMITH_HOOK_HELPERS"
fi

SHIPPED_JSON=$(cd "$REPO_ROOT/hooks" && ls -1 *.json 2>/dev/null | sort -u)
LISTED_JSON=$(array_entries SMITH_HOOK_DATA)
MISSING_JSON=$(comm -23 <(printf '%s\n' "$SHIPPED_JSON") <(printf '%s\n' "$LISTED_JSON"))
if [ -n "$MISSING_JSON" ]; then
    assert 1 "every hooks/*.json appears in SMITH_HOOK_DATA"
    printf '         - %s\n' $MISSING_JSON
else
    assert 0 "every hooks/*.json appears in SMITH_HOOK_DATA"
fi

# ---------------------------------------------------------------------------
# Assertion 3 — install.sh's hook-count preview is derived (FR-63 / T119).
#
# The preview line once read "Copy 9 hooks" while the repo shipped 20. The
# check is structural: the assignment feeding the preview must be a command
# substitution over the hooks directory, and the preview line itself must
# interpolate that variable rather than any literal digit.
# ---------------------------------------------------------------------------
HOOK_TOTAL_ASSIGN=$(grep -n '^HOOK_TOTAL=' "$INSTALL" || true)
if printf '%s' "$HOOK_TOTAL_ASSIGN" | grep -q 'HOOK_TOTAL=\$(.*hooks.*)'; then
    assert 0 "install.sh derives HOOK_TOTAL from the hooks/ directory"
else
    assert 1 "install.sh derives HOOK_TOTAL from the hooks/ directory"
    echo "       found: ${HOOK_TOTAL_ASSIGN:-<no HOOK_TOTAL assignment>}"
fi

PREVIEW=$(grep -n 'Copy .* hooks' "$INSTALL" || true)
if [ -z "$PREVIEW" ]; then
    assert 1 "install.sh has a hook-count preview line"
elif printf '%s' "$PREVIEW" | grep -Eq 'Copy [0-9]+ hooks'; then
    assert 1 "install.sh's hook-count preview is not hardcoded"
    echo "       hardcoded: $PREVIEW"
elif printf '%s' "$PREVIEW" | grep -q 'Copy \$HOOK_TOTAL hooks'; then
    assert 0 "install.sh's hook-count preview is not hardcoded"
else
    assert 1 "install.sh's hook-count preview interpolates \$HOOK_TOTAL"
    echo "       found: $PREVIEW"
fi

# The derived count must also agree with what the copy loop actually globs.
DERIVED=$(cd "$REPO_ROOT" && find hooks -maxdepth 1 -type f -name '*.sh' | wc -l | tr -d ' ')
GLOBBED=$(cd "$REPO_ROOT/hooks" && ls -1 *.sh 2>/dev/null | wc -l | tr -d ' ')
if [ "$DERIVED" = "$GLOBBED" ]; then
    assert 0 "install.sh's find(1) count matches the hooks/*.sh glob ($DERIVED)"
else
    assert 1 "install.sh's find(1) count matches the hooks/*.sh glob"
    echo "       find=$DERIVED glob=$GLOBBED"
fi

echo
echo "  passed: $PASS   failed: $FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
