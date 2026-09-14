#!/usr/bin/env bash
# tests/e2e/test_full_index_rebuild_gc.sh
#
# Feature 59 (WordPress-Aware Index Defaults), Part B — IndexRun.prune_
# stale_index() / mode_full()'s GC gate. Sibling of test_full_index_
# rebuild.sh (T101), reusing its pass/fail/assert helper trio + isolated
# tmpdir fixture shape, as a NEW file (Part B's fixture needs DELETED /
# newly-excluded files a fresh single-pass fixture can't represent).
#
# Phase 1 (seed): 3-file fixture project, full rebuild, confirm all three
#   .meta files + system manifests exist.
# Phase 2 (GC): delete one file, newly-exclude another's directory via
#   system-paths.json, re-run a full rebuild; assert both stale entries
#   are pruned, the still-valid third file is untouched, and the summary
#   line contains "pruned" with the correct total count.
# Phase 3 (no-prune negatives): reset to the Phase-2 stale state fresh
#   before each sub-case, then run --incremental, --check, --system, and
#   --resume in turn; assert the stale state survives every one and no
#   "pruned" substring appears in any of their output.
#
# Run under both bash and zsh (NFR-4):
#   bash tests/e2e/test_full_index_rebuild_gc.sh
#   zsh  tests/e2e/test_full_index_rebuild_gc.sh

set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")/../.." && pwd)"
RUNNER="${REPO_ROOT}/scripts/smith-index/run.py"

TMPDIR_TEST="/tmp/smith-e2e-fullindex-gc-$$"
mkdir -p "$TMPDIR_TEST"
trap 'rm -rf "$TMPDIR_TEST"' EXIT

PASS=0
FAIL=0
TEST_NAME="T014-full-index-rebuild-gc"

pass() { printf '  PASS %s\n' "$1"; PASS=$((PASS+1)); }
fail() { printf '  FAIL %s\n' "$1" >&2; FAIL=$((FAIL+1)); }
assert() {
    if [ "$2" = "true" ]; then pass "$1"; else fail "$1"; fi
}

echo "[$TEST_NAME] setup: $TMPDIR_TEST"
cd "$TMPDIR_TEST"
git init -q
echo ".smith/" > .gitignore
mkdir -p old-thing plugin-dir core
printf 'def a():\n    return 1\n' > old-thing/file_a.py
printf 'def b():\n    return 2\n' > plugin-dir/file_b.py
printf 'def c():\n    return 3\n' > core/file_c.py
git add -A
git commit -q -m "seed fixture"
SEED_REF="$(git rev-parse HEAD)"

write_exclusion_rule() {
    # No "default" key: an unmatched path (e.g. core/file_c.py) must fall
    # through to the Tier 3 heuristic ("system-core"), not short-circuit
    # to a payload-wide default — see path-resolver.py resolve()'s
    # has_explicit_default branch (OOS-1: unchanged, reused as-is here).
    mkdir -p .smith/index/config
    cat > .smith/index/config/system-paths.json <<'JSON'
{
  "rules": [
    {"_comment": "test: newly exclude plugin-dir", "prefix": "plugin-dir/", "system": "excluded"}
  ]
}
JSON
}

# --- Phase 1: seed -----------------------------------------------------
python3 "$RUNNER" --root . >/dev/null 2>&1

assert "phase1: file_a.py.meta exists" \
    "$([ -f .smith/index/files/old-thing/file_a.py.meta ] && echo true || echo false)"
assert "phase1: file_b.py.meta exists" \
    "$([ -f .smith/index/files/plugin-dir/file_b.py.meta ] && echo true || echo false)"
assert "phase1: file_c.py.meta exists" \
    "$([ -f .smith/index/files/core/file_c.py.meta ] && echo true || echo false)"
assert "phase1: system-old-thing.md exists" \
    "$([ -f .smith/index/systems/system-old-thing.md ] && echo true || echo false)"
assert "phase1: system-plugin-dir.md exists" \
    "$([ -f .smith/index/systems/system-plugin-dir.md ] && echo true || echo false)"
assert "phase1: system-core.md exists" \
    "$([ -f .smith/index/systems/system-core.md ] && echo true || echo false)"

# --- Phase 2: GC ---------------------------------------------------------
rm -f old-thing/file_a.py
write_exclusion_rule
git add -A
git commit -q -m "gc setup: delete file_a, exclude plugin-dir"
GC_REF="$(git rev-parse HEAD)"

gc_out="$(python3 "$RUNNER" --root . 2>&1)"
echo "  $gc_out"

assert "phase2: file_a.py.meta pruned (missing source)" \
    "$([ ! -f .smith/index/files/old-thing/file_a.py.meta ] && echo true || echo false)"
assert "phase2: file_b.py.meta pruned (newly excluded)" \
    "$([ ! -f .smith/index/files/plugin-dir/file_b.py.meta ] && echo true || echo false)"
assert "phase2: system-old-thing.md manifest pruned (empty)" \
    "$([ ! -f .smith/index/systems/system-old-thing.md ] && echo true || echo false)"
assert "phase2: system-plugin-dir.md manifest pruned (empty)" \
    "$([ ! -f .smith/index/systems/system-plugin-dir.md ] && echo true || echo false)"
assert "phase2: file_c.py.meta still present (untouched)" \
    "$([ -f .smith/index/files/core/file_c.py.meta ] && echo true || echo false)"
assert "phase2: system-core.md still present (untouched)" \
    "$([ -f .smith/index/systems/system-core.md ] && echo true || echo false)"

if echo "$gc_out" | grep -q "4 pruned"; then
    pass "phase2: summary line reports 4 pruned (2 files + 2 systems)"
else
    fail "phase2: summary line missing expected '4 pruned' (got: $gc_out)"
fi

# --- Phase 3: no-prune negatives -----------------------------------------
reseed_stale_state() {
    rm -rf .smith/index
    mkdir -p old-thing
    printf 'def a():\n    return 1\n' > old-thing/file_a.py
    python3 "$RUNNER" --root . >/dev/null 2>&1
    rm -f old-thing/file_a.py
    write_exclusion_rule
}

assert_stale_untouched() {
    local mode_label="$1"
    local out="$2"
    assert "phase3 ($mode_label): file_a.py.meta still present (stale, untouched)" \
        "$([ -f .smith/index/files/old-thing/file_a.py.meta ] && echo true || echo false)"
    assert "phase3 ($mode_label): file_b.py.meta still present (stale, untouched)" \
        "$([ -f .smith/index/files/plugin-dir/file_b.py.meta ] && echo true || echo false)"
    if echo "$out" | grep -q "pruned"; then
        fail "phase3 ($mode_label): unexpected 'pruned' substring in output"
    else
        pass "phase3 ($mode_label): no 'pruned' substring in output"
    fi
}

# (a) --incremental
reseed_stale_state
out="$(python3 "$RUNNER" --root . --incremental --from "$SEED_REF" --to "$GC_REF" 2>&1)"
assert_stale_untouched "incremental" "$out"

# (b) --check
reseed_stale_state
out="$(python3 "$RUNNER" --root . --check 2>&1)"
assert_stale_untouched "check" "$out"

# (c) --system <name>
reseed_stale_state
out="$(python3 "$RUNNER" --root . --system system-core 2>&1)"
assert_stale_untouched "system-filter" "$out"

# (d) --resume (via a deliberately truncated checkpoint)
reseed_stale_state
mkdir -p .smith/index
cat > .smith/index/.smith-index-checkpoint.json <<'JSON'
{"started_at": "2026-01-01T00:00:00Z", "processed_files": 1, "last_file": "core/file_c.py", "systems_seen": ["system-core"]}
JSON
out="$(python3 "$RUNNER" --root . --resume 2>&1)"
assert_stale_untouched "resume" "$out"

# --- Summary --------------------------------------------------------------
echo
echo "[$TEST_NAME] PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
