#!/usr/bin/env bash
# get-base-branch.test.sh — fixture tests for skills/smith/scripts/get-base-branch.sh
#
# Builds throwaway git repos with constitution fixtures, runs the helper, and
# asserts stdout. Covers: field present, field absent, field empty, no
# constitution file, and not-in-a-git-tree. Prints PASS/FAIL per case plus a
# summary line; exits non-zero if any case fails.

set -u

# Resolve the helper relative to this test file's repo root.
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd -P)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd -P)
HELPER="$REPO_ROOT/skills/smith/scripts/get-base-branch.sh"

if [ ! -x "$HELPER" ]; then
    echo "FATAL: helper not found or not executable: $HELPER" >&2
    exit 2
fi

PASS=0
FAIL=0

# make_repo <fixture-content-or-NONE> -> prints the new repo dir
make_repo() {
    local content="$1"
    local dir
    dir=$(mktemp -d)
    (
        cd "$dir" || exit 1
        git init -q
        git config user.email test@example.com
        git config user.name test
        if [ "$content" != "__NOFILE__" ]; then
            mkdir -p .specify/memory
            printf '%s' "$content" > .specify/memory/constitution.md
        fi
    )
    printf '%s' "$dir"
}

# run_case <name> <expected> <repo-dir>
run_case() {
    local name="$1" expected="$2" dir="$3"
    local actual
    actual=$(cd "$dir" && "$HELPER")
    if [ "$actual" = "$expected" ]; then
        echo "PASS: $name (got '$actual')"
        PASS=$((PASS + 1))
    else
        echo "FAIL: $name (expected '$expected', got '$actual')"
        FAIL=$((FAIL + 1))
    fi
    rm -rf "$dir"
}

# --- Case 1: field present ---
DIR=$(make_repo '---
base_branch: development
---

# Project Constitution
')
run_case "field present -> development" "development" "$DIR"

# --- Case 1b: field present with quotes + trailing whitespace ---
DIR=$(make_repo '---
base_branch: "develop"
---

# Project Constitution
')
run_case "field quoted/padded -> develop" "develop" "$DIR"

# --- Case 2: field absent (frontmatter present, no base_branch) ---
DIR=$(make_repo '---
version: 1.0.0
---

# Project Constitution
')
run_case "field absent -> main" "main" "$DIR"

# --- Case 2b: no frontmatter at all ---
DIR=$(make_repo '# Project Constitution

No frontmatter here.
')
run_case "no frontmatter -> main" "main" "$DIR"

# --- Case 3: field empty ---
DIR=$(make_repo '---
base_branch:
---

# Project Constitution
')
run_case "field empty -> main" "main" "$DIR"

# --- Case 3b: field whitespace-only (explicit spaces after colon) ---
DIR=$(make_repo "$(printf '%s\n' '---' 'base_branch:   ' '---' '' '# Project Constitution')")
run_case "field whitespace-only -> main" "main" "$DIR"

# --- Case 4: no constitution file ---
DIR=$(make_repo '__NOFILE__')
run_case "no constitution file -> main" "main" "$DIR"

# --- Case 5: not in a git tree ---
DIR=$(mktemp -d)
run_case "not in git tree -> main" "main" "$DIR"

echo "----"
echo "SUMMARY: $PASS passed, $FAIL failed"

[ "$FAIL" -eq 0 ]
