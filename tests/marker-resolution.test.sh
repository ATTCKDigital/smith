#!/usr/bin/env bash
# marker-resolution.test.sh
#
# Two halves of one bug: an active-workflow marker that is written where
# nothing reads it, and a marker that is swept while its workflow is still
# running. Together they silently revoke write authorization mid-workflow —
# observed live during feature 60, where the sweep caused workflow-gate.sh to
# deny every Write/Edit and a subagent then circumvented the gate rather than
# halting.
#
# HALF 1 — janitor sweep.
#   hooks/active-workflow-janitor.sh guards the "fresh branch tip == main tip"
#   false positive with a TIME-based grace period (SMITH_JANITOR_GRACE_SECONDS,
#   default 3600). That is a heuristic, not a correctness guard: any workflow
#   that takes longer than the grace period to make its first commit loses its
#   marker. Feature 60's build ran six hours and did not commit for three.
#   The guard must be STATE-based — a branch whose tip equals the base has not
#   been merged, it has not started, and its age is irrelevant.
#
# HALF 2 — marker location.
#   scripts/create-active-workflow.sh resolves the project root with
#   `git rev-parse --show-toplevel`, which inside a linked worktree returns the
#   WORKTREE. hooks/workflow-gate.sh and hooks/active-workflow-janitor.sh both
#   resolve with `git rev-parse --git-common-dir`, which returns the PRIMARY
#   repo. So a marker created from inside a worktree lands where neither of
#   them will ever look.

set -u

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd -P)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd -P)
JANITOR="$REPO_ROOT/hooks/active-workflow-janitor.sh"
CREATOR="$REPO_ROOT/scripts/create-active-workflow.sh"

for f in "$JANITOR" "$CREATOR"; do
    [ -f "$f" ] || { echo "FATAL: not found: $f" >&2; exit 2; }
done

PASS=0
FAIL=0
pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1"; FAIL=$((FAIL + 1)); }

# make_origin <dir> — a bare "remote" plus a primary clone with one commit on
# main, so `origin/main` exists and branches can be compared against it.
make_origin() {
    local root="$1"
    mkdir -p "$root/remote" "$root/primary"
    git init -q --bare "$root/remote"
    git init -q "$root/primary"
    git -C "$root/primary" config user.email t@t.t
    git -C "$root/primary" config user.name t
    git -C "$root/primary" config commit.gpgsign false
    echo base > "$root/primary/README.md"
    git -C "$root/primary" add README.md
    git -C "$root/primary" commit -qm base
    git -C "$root/primary" branch -M main
    git -C "$root/primary" remote add origin "$root/remote"
    git -C "$root/primary" push -q -u origin main
    mkdir -p "$root/primary/.smith/vault/active-workflows"
}

# mktemp -d hands back /var/... on macOS while git resolves the same directory
# to /private/var/... . Every fixture root goes through this so the premise
# check below compares physical paths, not one of each.
new_root() { cd "$(mktemp -d)" && pwd -P; }

marker_at() {
    # marker_at <vault-root> <safe-branch> <branch> — minimal but real shape.
    printf 'workflow: smith-bugfix\nfeature: t\nbranch: %s\nworktree: /tmp/x\nsession_log: \nstarted: %s\n' \
        "$3" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        > "$1/.smith/vault/active-workflows/$2.yaml"
}

age_marker() {
    # Push the marker's mtime well past any grace period. The whole point of
    # half 1 is that age must not decide this.
    touch -t 202001010000 "$1" 2>/dev/null
}

# ---------------------------------------------------------------------------
# HALF 1a: a branch with ZERO commits is not swept, however old the marker is.
# ---------------------------------------------------------------------------
ROOT=$(new_root)
make_origin "$ROOT"
P="$ROOT/primary"
git -C "$P" branch fix/never-started main
marker_at "$P" "fix-never-started" "fix/never-started"
M="$P/.smith/vault/active-workflows/fix-never-started.yaml"
age_marker "$M"

CLAUDE_PROJECT_DIR="$P" bash "$JANITOR" >/dev/null 2>&1

if [ -f "$M" ]; then
    pass "half1a: a zero-commit branch's marker survives, regardless of marker age"
else
    fail "half1a: a zero-commit branch's marker was SWEPT — the workflow lost write authorization while still running"
fi
rm -rf "$ROOT"

# ---------------------------------------------------------------------------
# HALF 1b: control — a branch that genuinely diverged AND merged IS swept.
# A guard that never sweeps anything would pass 1a and be useless.
# ---------------------------------------------------------------------------
ROOT=$(new_root)
make_origin "$ROOT"
P="$ROOT/primary"
git -C "$P" checkout -q -b fix/really-merged
echo change > "$P/f.txt"
git -C "$P" add f.txt
git -C "$P" commit -qm "real work"
git -C "$P" checkout -q main
git -C "$P" merge -q --no-ff -m merge fix/really-merged
git -C "$P" push -q origin main
marker_at "$P" "fix-really-merged" "fix/really-merged"
M="$P/.smith/vault/active-workflows/fix-really-merged.yaml"
age_marker "$M"

CLAUDE_PROJECT_DIR="$P" bash "$JANITOR" >/dev/null 2>&1

if [ ! -f "$M" ]; then
    pass "half1b: a genuinely diverged-and-merged branch's marker IS swept (guard is not a blanket no-op)"
else
    fail "half1b: a merged branch's marker survived — the sweep no longer works at all"
fi
rm -rf "$ROOT"

# ---------------------------------------------------------------------------
# HALF 1c: control — a branch deleted from local and remote is still swept.
# ---------------------------------------------------------------------------
ROOT=$(new_root)
make_origin "$ROOT"
P="$ROOT/primary"
marker_at "$P" "fix-long-gone" "fix/long-gone"
M="$P/.smith/vault/active-workflows/fix-long-gone.yaml"
age_marker "$M"

CLAUDE_PROJECT_DIR="$P" bash "$JANITOR" >/dev/null 2>&1

if [ ! -f "$M" ]; then
    pass "half1c: a marker whose branch exists nowhere is still swept"
else
    fail "half1c: a marker for a nonexistent branch survived"
fi
rm -rf "$ROOT"

# ---------------------------------------------------------------------------
# HALF 2: create-active-workflow.sh run from INSIDE a linked worktree must
# write into the PRIMARY repo's vault — where the gate and janitor look.
# ---------------------------------------------------------------------------
ROOT=$(new_root)
make_origin "$ROOT"
P="$ROOT/primary"
WT="$ROOT/wt"
git -C "$P" worktree add -q "$WT" -b fix/from-worktree main 2>/dev/null

OUT=$(cd "$WT" && bash "$CREATOR" \
    --branch "fix/from-worktree" \
    --workflow smith-bugfix \
    --slug "from-worktree" \
    --worktree "$WT" 2>&1)
RC=$?

PRIMARY_MARKER="$P/.smith/vault/active-workflows/fix-from-worktree.yaml"
WT_MARKER="$WT/.smith/vault/active-workflows/fix-from-worktree.yaml"

if [ "$RC" -eq 0 ]; then
    pass "half2: the helper exits 0 when run from inside a worktree"
else
    fail "half2: the helper exited $RC from inside a worktree; output=[$OUT]"
fi

if [ -f "$PRIMARY_MARKER" ]; then
    pass "half2: the marker lands in the PRIMARY repo's vault, where the gate reads it"
else
    fail "half2: no marker in the primary vault — the gate will never see it (found at: $(ls "$WT/.smith/vault/active-workflows/" 2>/dev/null | tr '\n' ' '))"
fi

if [ ! -f "$WT_MARKER" ]; then
    pass "half2: no stray duplicate marker is left in the worktree's own vault"
else
    fail "half2: a second marker was written into the worktree vault — two markers for one branch"
fi

if [ -f "$PRIMARY_MARKER" ] && grep -q "^worktree: $WT$" "$PRIMARY_MARKER"; then
    pass "half2: the worktree: field still records the worktree path (smith-activity depends on it)"
else
    fail "half2: the worktree: field is wrong or missing; got [$(grep '^worktree:' "$PRIMARY_MARKER" 2>/dev/null)]"
fi

# The gate's own resolution must agree with where the helper wrote.
GATE_ROOT=$(cd "$WT" && dirname "$(git rev-parse --git-common-dir)")
if [ "$GATE_ROOT" = "$P" ]; then
    pass "half2: the gate's --git-common-dir resolution points at the primary repo (premise check)"
else
    fail "half2: premise check failed — gate resolves to [$GATE_ROOT], primary is [$P]"
fi

rm -rf "$ROOT"

echo "----"
echo "SUMMARY: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
