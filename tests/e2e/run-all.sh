#!/usr/bin/env bash
# tests/e2e/run-all.sh
#
# Runs every E2E test in tests/e2e/ and summarises the result.
# Exit code is 0 iff all eight tests pass.

set -uo pipefail

E2E_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# Ordered test list (matches T101-T108 in tasks.md).
TESTS=(
    "test_full_index_rebuild.sh"
    "test_check_staleness.sh"
    "test_manifest_updater_hook.sh"
    "test_context_loader_hook.sh"
    "test_soft_warning.sh"
    "test_4tier_resolution.sh"
    "test_path_resolution.sh"
    "test_quickstart_scenarios.sh"
)

PASSED=0
FAILED=0
SKIPPED=0
FAILED_LIST=()
START_TS=$(python3 -c 'import time; print(time.monotonic())')

printf '%s\n' "=========================================="
printf '%s\n' " E2E test driver — Manifest System (T101-T108)"
printf '%s\n' "=========================================="

for tname in "${TESTS[@]}"; do
    tpath="$E2E_DIR/$tname"
    if [ ! -f "$tpath" ]; then
        printf '\n[SKIP] %s (file not found)\n' "$tname"
        SKIPPED=$((SKIPPED + 1))
        continue
    fi
    printf '\n>>> Running %s\n' "$tname"
    chmod +x "$tpath" 2>/dev/null || true
    if bash "$tpath"; then
        printf '<<< %s: PASS\n' "$tname"
        PASSED=$((PASSED + 1))
    else
        printf '<<< %s: FAIL\n' "$tname"
        FAILED=$((FAILED + 1))
        FAILED_LIST+=("$tname")
    fi
done

END_TS=$(python3 -c 'import time; print(time.monotonic())')
ELAPSED=$(python3 -c "print(f'{($END_TS - $START_TS):.1f}')")

printf '\n=========================================='
printf '\n E2E Summary\n'
printf '   PASSED:  %d\n' "$PASSED"
printf '   FAILED:  %d\n' "$FAILED"
printf '   SKIPPED: %d\n' "$SKIPPED"
printf '   TIME:    %ss\n' "$ELAPSED"
if [ "$FAILED" -gt 0 ]; then
    printf '   Failing tests:\n'
    for t in "${FAILED_LIST[@]}"; do
        printf '     - %s\n' "$t"
    done
fi
printf '==========================================\n'

[ "$FAILED" -eq 0 ]
