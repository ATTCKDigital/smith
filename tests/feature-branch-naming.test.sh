#!/usr/bin/env bash
# feature-branch-naming.test.sh — pins the branch shapes check_feature_branch()
# accepts and, just as importantly, the ones it must keep rejecting.
#
# The bug this file exists to catch:
#   skills/smith/scripts/common.sh required `^[0-9]{3}-`, but this repo's own
#   feature branches are two-digit (`60-activity-dashboard`). Both callers —
#   skills/smith/scripts/setup-plan.sh and skills/smith/scripts/check-prerequisites.sh
#   — do `check_feature_branch ... || exit 1`, so every feature from 53 onward
#   exited 1 immediately. That silently disabled the documented first step of
#   /smith-new Phase 4, and every recent plan was written without it.
#
# What the check is FOR (and must keep doing): stopping those scripts from
# scaffolding plan artifacts while sitting on a non-feature branch. `main` and
# `master` must still be rejected after the widening, or the fix trades a
# false negative for a much worse false positive.
#
# `fix/<slug>` is asserted as REJECTED — see the comment in common.sh for the
# reasoning. The assertion is here so that the decision is a pinned contract
# rather than an accident of the regex.
#
# Run: bash tests/feature-branch-naming.test.sh
# CI:  .github/workflows/test-install.yml globs tests/*.test.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
COMMON="$REPO_ROOT/skills/smith/scripts/common.sh"

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

echo "=== tests/feature-branch-naming.test.sh ==="

[ -f "$COMMON" ] || { echo "FATAL: $COMMON not found"; exit 1; }

# common.sh only defines functions at source time — nothing executes.
# shellcheck source=/dev/null
. "$COMMON"

if ! command -v check_feature_branch >/dev/null 2>&1; then
    echo "FATAL: check_feature_branch not defined after sourcing $COMMON"
    exit 1
fi

# ---------------------------------------------------------------------------
# accepts <branch> — the branch must be treated as a feature branch (rc 0)
# rejects <branch> — the branch must be refused (rc non-zero)
#
# The second argument to check_feature_branch is the has-git flag; "true" is
# the path under test (the "false" path deliberately skips validation and is
# asserted separately at the bottom).
# ---------------------------------------------------------------------------
accepts() {
    local branch="$1"
    check_feature_branch "$branch" "true" >/dev/null 2>&1
    local rc=$?
    if [ "$rc" -eq 0 ]; then
        assert 0 "accepts '$branch'"
    else
        assert 1 "accepts '$branch' (got rc=$rc)"
    fi
}

rejects() {
    local branch="$1"
    check_feature_branch "$branch" "true" >/dev/null 2>&1
    local rc=$?
    if [ "$rc" -ne 0 ]; then
        assert 0 "rejects '$branch'"
    else
        assert 1 "rejects '$branch' (got rc=0 — the guard is open)"
    fi
}

# --- the regression: this repo's own two-digit branches -------------------
accepts "60-activity-dashboard"
accepts "53-some-feature"
accepts "12-x"

# --- the legacy three-digit shape must keep working -----------------------
accepts "003-old-style"
accepts "001-feature-name"

# --- and the shape does not cap out at three digits -----------------------
accepts "1004-far-future"

# --- the guarantee the check exists to provide ----------------------------
rejects "main"
rejects "master"

# --- /smith-bugfix branches: rejected, by decision (see common.sh) --------
rejects "fix/smith-self-consistency"

# --- other non-feature shapes stay out ------------------------------------
rejects "9-single-digit"
rejects "feature/login"
rejects "develop"
rejects ""

# --- non-git repos keep their documented skip-with-warning behavior -------
check_feature_branch "main" "false" >/dev/null 2>&1
if [ $? -eq 0 ]; then
    assert 0 "non-git repo skips branch validation (rc=0)"
else
    assert 1 "non-git repo skips branch validation"
fi

echo
echo "  passed: $PASS   failed: $FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
