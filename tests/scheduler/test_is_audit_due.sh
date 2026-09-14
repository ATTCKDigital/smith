#!/usr/bin/env bash
# test_is_audit_due.sh — unit tests for is_audit_due() in
# scheduler/smith-scheduler.sh (feature 58-scheduled-audits, T001/T008).
#
# is_audit_due() is a pure function (no file I/O, no globals read/written —
# see its docstring in smith-scheduler.sh), so this test needs no fixture
# project and no $HOME isolation. Do NOT `source scheduler/smith-scheduler.sh`
# directly — the script performs real top-level work before any function is
# reachable (creates $HOME/.smith/scheduler/scheduler.log, and would run
# BOTH loops against the real ~/.smith/projects.json once past the
# SMITH_SCHEDULER_ENABLED gate). Instead extract just the function body and
# source that.
#
# NFR-2: this file is bash/zsh portable — no bash-only syntax — so it can be
# invoked as either `bash tests/scheduler/test_is_audit_due.sh` or
# `zsh tests/scheduler/test_is_audit_due.sh` (see docs/scheduler.md's dual-
# shell precedent and tests/security/test_secret_scan.sh's self-detecting
# interpreter idiom — no separate wrapper process here, since the function
# is sourced directly into whichever shell is running this file).
#
# Run:
#   bash tests/scheduler/test_is_audit_due.sh
#   zsh  tests/scheduler/test_is_audit_due.sh

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
SCHEDULER="$REPO/scheduler/smith-scheduler.sh"

if [ ! -f "$SCHEDULER" ]; then
    echo "FATAL: scheduler not found: $SCHEDULER" >&2
    exit 2
fi

FUNC_FILE=$(mktemp -t is_audit_due.XXXXXX)
trap 'rm -f "$FUNC_FILE"' EXIT

sed -n '/^is_audit_due() {/,/^}/p' "$SCHEDULER" > "$FUNC_FILE"

if [ ! -s "$FUNC_FILE" ]; then
    echo "FATAL: could not extract is_audit_due() from $SCHEDULER" >&2
    exit 2
fi

# shellcheck source=/dev/null
source "$FUNC_FILE"

if ! command -v is_audit_due >/dev/null 2>&1; then
    echo "FATAL: is_audit_due() not defined after sourcing extracted body" >&2
    exit 2
fi

PASS=0
FAIL=0
FAILED_NAMES=()

assert_due() {
    local name="$1" now="$2" last="$3" cadence="$4" expected="$5"
    local actual
    actual=$(is_audit_due "$now" "$last" "$cadence")
    if [ "$actual" = "$expected" ]; then
        PASS=$((PASS + 1))
        printf 'PASS  %s\n' "$name"
    else
        FAIL=$((FAIL + 1))
        FAILED_NAMES+=("$name")
        printf 'FAIL  %s\n  now=%s last=%s cadence=%s\n  expected: %s\n  actual:   %s\n' \
            "$name" "$now" "$last" "$cadence" "$expected" "$actual"
    fi
}

# Fixed "now" for full determinism — no dependency on the real system clock.
NOW="2026-09-14"

# ---- last="" (never run) → due, regardless of cadence ----
assert_due "never run (last empty) → due" "$NOW" "" 7 1

# ---- last exactly cadence_days ago → due (>=, not >) ----
# 2026-09-07 is exactly 7 days before 2026-09-14.
assert_due "last exactly at cadence boundary → due" "$NOW" "2026-09-07" 7 1

# ---- last one day short of cadence → not due ----
# 2026-09-08 is 6 days before 2026-09-14 (cadence=7).
assert_due "last one day short of cadence → not due" "$NOW" "2026-09-08" 7 0

# ---- last one day past cadence → due ----
# 2026-09-06 is 8 days before 2026-09-14 (cadence=7).
assert_due "last one day past cadence → due" "$NOW" "2026-09-06" 7 1

# ---- cadence_days=1 override shortens the window ----
# 2026-09-13 is exactly 1 day before 2026-09-14 → due.
assert_due "cadence_days=1, last=1 day ago → due" "$NOW" "2026-09-13" 1 1
# 2026-09-14 (same day, 0 days elapsed) with cadence=1 → not due.
assert_due "cadence_days=1, last=today → not due" "$NOW" "2026-09-14" 1 0

# ---- cadence_days=0 → due immediately regardless of last ----
assert_due "cadence_days=0, last=today → due" "$NOW" "2026-09-14" 0 1
assert_due "cadence_days=0, last=7 days ago → due" "$NOW" "2026-09-07" 0 1

echo
echo "----------------------------------------------------------------------"
echo "Ran $((PASS + FAIL)) tests: $PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
    printf 'Failed:\n'
    for n in "${FAILED_NAMES[@]}"; do
        printf '  - %s\n' "$n"
    done
    exit 1
fi
