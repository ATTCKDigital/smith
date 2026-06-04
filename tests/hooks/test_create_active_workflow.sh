#!/usr/bin/env bash
# Unit tests for scripts/create-active-workflow.sh.
#
# Covers: input validation, marker shape, idempotency, collision,
# atomic write, optional session-log stamping.
#
# Run:
#   bash tests/hooks/test_create_active_workflow.sh

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
HELPER="$REPO/scripts/create-active-workflow.sh"

PASS=0
FAIL=0
FAILED_NAMES=()

assert_eq() {
    local name="$1"
    local expected="$2"
    local actual="$3"
    if [ "$expected" = "$actual" ]; then
        PASS=$((PASS + 1))
        printf 'PASS  %s\n' "$name"
    else
        FAIL=$((FAIL + 1))
        FAILED_NAMES+=("$name")
        printf 'FAIL  %s\n  expected: %s\n  actual:   %s\n' "$name" "$expected" "$actual"
    fi
}

assert_file_contains() {
    local name="$1"
    local file="$2"
    local needle="$3"
    if grep -qF "$needle" "$file" 2>/dev/null; then
        PASS=$((PASS + 1))
        printf 'PASS  %s\n' "$name"
    else
        FAIL=$((FAIL + 1))
        FAILED_NAMES+=("$name")
        printf 'FAIL  %s\n  needle missing: %s\n  in: %s\n' "$name" "$needle" "$file"
    fi
}

setup_repo() {
    local d
    d=$(mktemp -d)
    (
        cd "$d"
        git init --quiet
        git config user.email test@example.com
        git config user.name test
        git commit --allow-empty -m init --quiet
    )
    printf '%s' "$d"
}

# ---------- 1: usage exits 0 ----------
{
    out=$(bash "$HELPER" --help 2>&1)
    rc=$?
    assert_eq "usage exit code" 0 "$rc"
}

# ---------- 2: missing required flag ----------
{
    repo=$(setup_repo)
    out=$(cd "$repo" && bash "$HELPER" --workflow smith-bugfix --slug foo --worktree /tmp/x 2>&1)
    rc=$?
    assert_eq "missing --branch exit code" 2 "$rc"
    rm -rf "$repo"
}

# ---------- 3: invalid workflow ----------
{
    repo=$(setup_repo)
    out=$(cd "$repo" && bash "$HELPER" --branch foo --workflow not-a-workflow --slug f --worktree /tmp/x 2>&1)
    rc=$?
    assert_eq "invalid --workflow exit code" 2 "$rc"
    rm -rf "$repo"
}

# ---------- 4: invalid branch (shell metachar) ----------
{
    repo=$(setup_repo)
    out=$(cd "$repo" && bash "$HELPER" --branch 'foo; rm -rf /' --workflow smith-bugfix --slug f --worktree /tmp/x 2>&1)
    rc=$?
    assert_eq "invalid --branch exit code" 2 "$rc"
    rm -rf "$repo"
}

# ---------- 5: relative worktree path rejected ----------
{
    repo=$(setup_repo)
    out=$(cd "$repo" && bash "$HELPER" --branch foo --workflow smith-bugfix --slug f --worktree relative/path 2>&1)
    rc=$?
    assert_eq "relative --worktree exit code" 2 "$rc"
    rm -rf "$repo"
}

# ---------- 6: happy path creates marker ----------
{
    repo=$(setup_repo)
    out=$(cd "$repo" && bash "$HELPER" --branch fix/foo --workflow smith-bugfix --slug foo-fix --worktree /tmp/wt-foo 2>&1)
    rc=$?
    assert_eq "happy-path exit code" 0 "$rc"
    marker="$repo/.smith/vault/active-workflows/fix-foo.yaml"
    [ -f "$marker" ] && PASS=$((PASS + 1)) && printf 'PASS  happy-path marker exists\n' || {
        FAIL=$((FAIL + 1)); FAILED_NAMES+=("happy-path marker exists"); printf 'FAIL  happy-path marker exists\n'
    }
    assert_file_contains "marker has workflow field" "$marker" "workflow: smith-bugfix"
    assert_file_contains "marker has feature field" "$marker" "feature: foo-fix"
    assert_file_contains "marker has branch field" "$marker" "branch: fix/foo"
    assert_file_contains "marker has worktree field" "$marker" "worktree: /tmp/wt-foo"
    assert_file_contains "marker has started field" "$marker" "started:"
    rm -rf "$repo"
}

# ---------- 7: idempotent re-run ----------
{
    repo=$(setup_repo)
    bash "$HELPER" --branch fix/bar --workflow smith-new --slug bar --worktree /tmp/wt-bar >/dev/null 2>&1
    (cd "$repo" || exit 1)
    marker="$repo/.smith/vault/active-workflows/fix-bar.yaml"
    cp "$marker" "$marker.first" 2>/dev/null
    sleep 1
    out=$(cd "$repo" && bash "$HELPER" --branch fix/bar --workflow smith-new --slug bar --worktree /tmp/wt-bar 2>&1)
    rc=$?
    assert_eq "idempotent re-run exit code" 0 "$rc"
    # started timestamp should update; workflow/branch unchanged
    new_started=$(grep -E '^started:' "$marker")
    old_started=$(grep -E '^started:' "$marker.first" 2>/dev/null || printf '')
    if [ "$new_started" != "$old_started" ]; then
        PASS=$((PASS + 1)); printf 'PASS  idempotent updates timestamp\n'
    else
        FAIL=$((FAIL + 1)); FAILED_NAMES+=("idempotent updates timestamp"); printf 'FAIL  idempotent updates timestamp\n  old=%s\n  new=%s\n' "$old_started" "$new_started"
    fi
    rm -rf "$repo"
}

# ---------- 8: collision detection ----------
{
    repo=$(setup_repo)
    (cd "$repo" && bash "$HELPER" --branch fix/baz --workflow smith-bugfix --slug baz --worktree /tmp/wt-baz) >/dev/null 2>&1
    out=$(cd "$repo" && bash "$HELPER" --branch fix/baz --workflow smith-new --slug baz --worktree /tmp/wt-baz 2>&1)
    rc=$?
    assert_eq "collision exit code" 3 "$rc"
    rm -rf "$repo"
}

# ---------- 9: marker NOT created when validation fails (atomic semantics) ----------
{
    repo=$(setup_repo)
    out=$(cd "$repo" && bash "$HELPER" --branch 'invalid;' --workflow smith-bugfix --slug f --worktree /tmp/x 2>&1)
    [ ! -d "$repo/.smith/vault/active-workflows" ] || ls "$repo/.smith/vault/active-workflows/" | grep -q . && true
    # Marker dir may exist but should be empty
    count=$(ls "$repo/.smith/vault/active-workflows/" 2>/dev/null | wc -l | tr -d ' ')
    assert_eq "no marker on validation failure" 0 "$count"
    rm -rf "$repo"
}

# ---------- 10: not in a git repo ----------
{
    d=$(mktemp -d)
    out=$(cd "$d" && bash "$HELPER" --branch foo --workflow smith-bugfix --slug f --worktree /tmp/x 2>&1)
    rc=$?
    assert_eq "non-git-repo exit code" 2 "$rc"
    rm -rf "$d"
}

# ---------- 11: session log stamping ----------
{
    repo=$(setup_repo)
    mkdir -p "$repo/.smith/vault/sessions"
    session_log="$repo/.smith/vault/sessions/test.md"
    printf '# Session\n\n' > "$session_log"
    out=$(cd "$repo" && bash "$HELPER" --branch fix/log --workflow smith-bugfix --slug log --worktree /tmp/wt-log --session-log "$session_log" 2>&1)
    rc=$?
    assert_eq "session-log stamping exit code" 0 "$rc"
    assert_file_contains "session log contains workflow-start" "$session_log" "workflow-start fix/log"
    assert_file_contains "session log contains Workflow:" "$session_log" "**Workflow:** smith-bugfix"
    rm -rf "$repo"
}

# ---------- summary ----------
TOTAL=$((PASS + FAIL))
printf '\n%s\n' "----------------------------------------------------------------------"
printf 'Ran %d tests: %d passed, %d failed\n' "$TOTAL" "$PASS" "$FAIL"
if [ "$FAIL" -gt 0 ]; then
    printf 'Failed: %s\n' "${FAILED_NAMES[*]}"
    exit 1
fi
exit 0
