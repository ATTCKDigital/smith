#!/usr/bin/env bash
# activity-worktrees.sh — the T076 degraded-worktree fixture builder.
#
# NOT a test file. CI globs `tests/*.test.sh` and nothing else, so this
# filename is deliberately outside that glob; it is sourced from
# tests/lib/activity-helpers.sh, which tests/smith-activity.test.sh sources.
#
# Split from activity-helpers.sh rather than appended to it: that file stood
# at 456 lines and this machinery is ~120 more, which would have carried it
# past the repo's 500-line decompose threshold.
#
# WHY A WHOLE FILE FOR THREE FIXTURES. SC-8's three degraded states cannot be
# faked with a stub, because every one of them is a statement about what GIT
# reports, not about what a dict contains:
#
#   MISSING   the directory is gone but `git worktree list` still names it.
#             Only `rm -rf` WITHOUT `git worktree prune` produces that, and
#             the distinction is the entire point of the state.
#   ORPHANED  the branch is merged into base, or the branch is gone. "Gone"
#             is only reachable by detaching the worktree first, because git
#             refuses to delete a branch that is checked out — so a fixture
#             that just deletes the branch silently builds nothing.
#   HELD      the worktree is on disk with an UNMERGED branch, and the owning
#             workflow has not advanced. The git half is real; the stalled
#             half is a timestamp, and is injected as a synthetic workflow.
#
# Sourcing contract: TMP and the `git` binary. Nothing here runs a test.

# make_degraded_repo <name> — a scratch repo carrying all three degraded
# states at once, plus one healthy ACTIVE worktree as the control. Prints the
# repo path.
#
# The control matters: a classifier that returned "orphaned" for everything
# would satisfy the three degraded assertions and be completely broken, and
# only a worktree that must NOT be degraded catches it.
make_degraded_repo() {
    local name="$1"
    local dir="$TMP/repos/$name"
    local wts="$TMP/worktrees/$name"
    mkdir -p "$dir" "$wts"
    (
        cd "$dir" || exit 1
        git init -q -b main
        git config user.email test@example.com
        git config user.name test
        git config commit.gpgsign false
        mkdir -p .smith/vault/active-workflows
        printf 'seed\n' > README.md
        git add -A && git commit -qm seed

        # --- HELD: on disk, branch unmerged ------------------------------
        git worktree add -q -b held-branch "$wts/held"
        ( cd "$wts/held" && printf 'held\n' > held.txt && git add -A \
            && git commit -qm "work in progress" )

        # --- MISSING: git still lists it, the disk does not have it ------
        git worktree add -q -b missing-branch "$wts/missing"
        rm -rf "$wts/missing"          # deliberately NO `git worktree prune`

        # --- ORPHANED (merged): on disk, branch merged into main ---------
        git worktree add -q -b orphaned-merged "$wts/orphaned-merged"
        ( cd "$wts/orphaned-merged" && printf 'done\n' > done.txt && git add -A \
            && git commit -qm "finished work" )
        git merge -q --no-ff -m "merge orphaned-merged" orphaned-merged

        # --- ORPHANED (branch gone): on disk, its branch deleted ---------
        # Detach FIRST. `git branch -D` on a branch checked out in a worktree
        # is refused, so without the detach this fixture would build an
        # ACTIVE worktree and the assertion that reads it would pass
        # vacuously against the wrong state.
        git worktree add -q -b orphaned-gone "$wts/orphaned-gone"
        ( cd "$wts/orphaned-gone" && git checkout -q --detach )
        git branch -q -D orphaned-gone

        # --- ACTIVE: the control. On disk, unmerged, and its workflow is
        # advancing, so nothing may classify it as degraded.
        git worktree add -q -b active-branch "$wts/active"
        ( cd "$wts/active" && printf 'live\n' > live.txt && git add -A \
            && git commit -qm "live work" )

        # One marker per worktree. `branch:` is what row 3's "branch gone"
        # reads, so the orphaned-gone marker keeps naming the branch that no
        # longer exists — which is exactly the real-world shape: the janitor
        # has not swept, so the marker still claims what smith-finish deleted.
        _degraded_marker "$dir" held-branch     "$wts/held"
        _degraded_marker "$dir" missing-branch  "$wts/missing"
        _degraded_marker "$dir" orphaned-merged "$wts/orphaned-merged"
        _degraded_marker "$dir" orphaned-gone   "$wts/orphaned-gone"
        _degraded_marker "$dir" active-branch   "$wts/active"
    ) >/dev/null 2>&1
    printf '%s' "$dir"
}

# _degraded_marker <repo> <branch> <worktree> — one active-workflow marker in
# the PRIMARY vault, in create-active-workflow.sh's own field order and
# `date -u` stamp format.
#
# `started:` is backdated an hour so `age_s` is a real number rather than 0;
# a fixture whose age is zero cannot tell "we measured it" from "we defaulted
# it", which is the distinction the HELD render depends on.
_degraded_marker() {
    local repo="$1" branch="$2" worktree="$3"
    local safe started
    safe=$(printf '%s' "$branch" | tr -c 'A-Za-z0-9._-' '-')
    started=$(python3 -c "
import time
print(time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() - 3600)))")
    cat > "$repo/.smith/vault/active-workflows/$safe.yaml" <<YAML
workflow: smith-bugfix
feature: $branch
branch: $branch
worktree: $worktree
session_log:
started: $started
YAML
}

# classify_degraded <repo> — run the real classifier over the fixture and
# print `<worktree-basename>=<classification>` per line, sorted.
#
# The owning workflows are synthesized here rather than resolved from a
# session log, and only the HELD one is stalled: row 4 needs a phase timeline
# with an `entered_at` older than HELD_THRESHOLD_S, and manufacturing one is
# far more honest than writing a session log whose parse is a second thing
# that could be wrong. Everything the six-row table actually branches on —
# marker presence, on-disk-ness, merged-ness, branch existence — is real git
# and real marker files.
classify_degraded() {
    local repo="$1"
    PYTHONPATH="$REPO_ROOT/scripts/activity" python3 - "$repo" <<'PY'
import os
import sys
import time

import markers as M
import worktrees as WT

repo = sys.argv[1]
marker_records = M.enumerate_markers(repo)

STALE = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
FRESH = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time()))

workflows = []
for marker in marker_records:
    at = STALE if marker.get("branch") == "held-branch" else FRESH
    workflows.append({
        "key": marker["key"],
        "started": marker.get("started"),
        "current_phase_id": "smith-bugfix:2",
        "current_title": "Implementation",
        "phases": [{"id": "smith-bugfix:2", "entered_at": at}],
        "signals": [{"at": at}],
    })

WT.reset_cache()
for record in sorted(WT.describe(repo, markers=marker_records, workflows=workflows),
                     key=lambda r: r["path"]):
    print("%s=%s" % (os.path.basename(record["path"]), record["classification"]))
PY
}
