#!/usr/bin/env bash
# get-base-branch.sh — resolve the project's configured integration/base branch.
#
# Reads the `base_branch:` field from the YAML frontmatter of
# .specify/memory/constitution.md and echoes it to stdout. Falls back to the
# literal `main` whenever the value cannot be resolved (no git tree, no
# constitution file, no/empty/whitespace-only field), so existing main-based
# projects behave byte-for-byte as before.
#
# This is a VALUE PRODUCER consumed in command substitution under `set -e`,
# e.g. BASE="$(.specify/scripts/bash/get-base-branch.sh)". It therefore ALWAYS
# exits 0 and ALWAYS emits a non-empty branch name on stdout — it must never
# abort a calling workflow or produce empty output. This deliberately diverges
# from clear-active-workflow.sh's strict non-zero exit posture.
#
# Read-only: no writes, no globbing, no recursion (mirrors the
# clear-active-workflow.sh security posture, minus the strict exit codes).

set -eu

DEFAULT_BRANCH="main"

# Resolve repo root; on failure (not inside a git tree) fall back to main.
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
    printf '%s\n' "$DEFAULT_BRANCH"
    exit 0
}

CONST="$REPO_ROOT/.specify/memory/constitution.md"

# No constitution file → main.
[ -f "$CONST" ] || {
    printf '%s\n' "$DEFAULT_BRANCH"
    exit 0
}

# Extract base_branch: from inside the FIRST frontmatter block only
# (between the first two '---' fences). fence==1 means we are past the
# opening fence and before the closing one.
VALUE=$(awk '
  /^---[[:space:]]*$/ { fence++; next }
  fence == 1 && /^[[:space:]]*base_branch[[:space:]]*:/ {
    sub(/^[[:space:]]*base_branch[[:space:]]*:[[:space:]]*/, "")
    print
    exit
  }
' "$CONST") || VALUE=""

# Trim trailing whitespace and surrounding single/double quotes.
VALUE=$(printf '%s' "$VALUE" | sed -e 's/[[:space:]]*$//' -e 's/^[[:space:]]*//' -e "s/^['\"]//" -e "s/['\"]$//")

# Empty / whitespace-only / absent → main.
if [ -z "$VALUE" ]; then
    printf '%s\n' "$DEFAULT_BRANCH"
    exit 0
fi

printf '%s\n' "$VALUE"
exit 0
