#!/usr/bin/env bash
# Integration tests for hooks/workflow-gate.sh's new exemptions
# (per spec/31-workflow-gate-bootstrap).
#
# Feeds the gate hook synthesized PreToolUse JSON and asserts the
# correct allow/deny verdict for:
#   - create-active-workflow.sh Bash invocation (allow regardless of marker)
#   - cat > marker.yaml heredoc (still deny without marker)
#   - Write to .smith/index/files/foo.meta (allow)
#   - Write to .smith/vault/active-workflows/forged.yaml (still deny)
#   - Existing markers still recognized (allow everything)
#   - Write to .smith/vault/sessions/foo.md (allow — was already exempt)
#
# Run:
#   bash tests/hooks/test_workflow_gate_exemption.sh

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
GATE="$REPO/hooks/workflow-gate.sh"

PASS=0
FAIL=0
FAILED_NAMES=()

# Feed the gate JSON; returns "allow" or "deny" based on the output.
# Gate exits 0 in both cases — distinguish by presence of "permissionDecision":"deny" in the JSON output.
gate_verdict() {
    local payload="$1"
    local repo="$2"
    local out
    out=$(printf '%s' "$payload" | env CLAUDE_PROJECT_DIR="$repo" bash "$GATE" 2>/dev/null)
    if printf '%s' "$out" | grep -q '"permissionDecision":[[:space:]]*"deny"'; then
        printf 'deny'
    elif printf '%s' "$out" | grep -q "'permissionDecision': 'deny'"; then
        printf 'deny'
    else
        printf 'allow'
    fi
}

assert_verdict() {
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
    # Make it a Smith project (gate's exemption requires .smith/ exists)
    mkdir -p "$d/.smith"
    printf '%s' "$d"
}

# ---------- 1: create-active-workflow.sh allowed without marker ----------
{
    repo=$(setup_repo)
    payload='{"tool_name":"Bash","tool_input":{"command":"bash ~/.smith/scripts/create-active-workflow.sh --branch foo --workflow smith-bugfix --slug f --worktree /tmp/wt"}}'
    actual=$(gate_verdict "$payload" "$repo")
    assert_verdict "helper invocation allowed (no marker)" "allow" "$actual"
    rm -rf "$repo"
}

# ---------- 2: helper allowed via relative path ----------
{
    repo=$(setup_repo)
    payload='{"tool_name":"Bash","tool_input":{"command":"./scripts/create-active-workflow.sh --branch x --workflow smith-new --slug y --worktree /tmp/w"}}'
    actual=$(gate_verdict "$payload" "$repo")
    assert_verdict "helper invocation allowed (relative path)" "allow" "$actual"
    rm -rf "$repo"
}

# ---------- 3: cat > marker.yaml still denied (the heredoc bootstrap that doesn't work) ----------
{
    repo=$(setup_repo)
    payload='{"tool_name":"Bash","tool_input":{"command":"cat > .smith/vault/active-workflows/forged.yaml << EOF\nworkflow: smith-bugfix\nEOF"}}'
    actual=$(gate_verdict "$payload" "$repo")
    assert_verdict "cat-heredoc forgery still denied" "deny" "$actual"
    rm -rf "$repo"
}

# ---------- 4: writing to .smith/index/files/foo.meta allowed without marker ----------
{
    repo=$(setup_repo)
    payload="{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$repo/.smith/index/files/scripts/foo.py.meta\",\"content\":\"...\"}}"
    actual=$(gate_verdict "$payload" "$repo")
    assert_verdict ".smith/index/files write allowed (no marker)" "allow" "$actual"
    rm -rf "$repo"
}

# ---------- 5: .smith/index/systems write allowed ----------
{
    repo=$(setup_repo)
    payload="{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$repo/.smith/index/systems/system-01-cart.md\",\"content\":\"...\"}}"
    actual=$(gate_verdict "$payload" "$repo")
    assert_verdict ".smith/index/systems write allowed (no marker)" "allow" "$actual"
    rm -rf "$repo"
}

# ---------- 6: Write to .smith/vault/active-workflows/forged.yaml still denied ----------
{
    repo=$(setup_repo)
    payload="{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$repo/.smith/vault/active-workflows/forged.yaml\",\"content\":\"...\"}}"
    actual=$(gate_verdict "$payload" "$repo")
    assert_verdict "Write to active-workflows still denied" "deny" "$actual"
    rm -rf "$repo"
}

# ---------- 7: Write to .smith/vault/sessions allowed (pre-existing behavior) ----------
{
    repo=$(setup_repo)
    payload="{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$repo/.smith/vault/sessions/x.md\",\"content\":\"...\"}}"
    actual=$(gate_verdict "$payload" "$repo")
    assert_verdict "Write to vault/sessions still allowed" "allow" "$actual"
    rm -rf "$repo"
}

# ---------- 8: Write to project source file still denied without marker ----------
{
    repo=$(setup_repo)
    payload="{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$repo/scripts/foo.py\",\"content\":\"...\"}}"
    actual=$(gate_verdict "$payload" "$repo")
    assert_verdict "project source write still denied" "deny" "$actual"
    rm -rf "$repo"
}

# ---------- 9: With marker present, everything allowed ----------
{
    repo=$(setup_repo)
    mkdir -p "$repo/.smith/vault/active-workflows"
    printf 'workflow: smith-bugfix\nbranch: fix/foo\n' > "$repo/.smith/vault/active-workflows/fix-foo.yaml"
    payload="{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$repo/scripts/foo.py\",\"content\":\"...\"}}"
    actual=$(gate_verdict "$payload" "$repo")
    assert_verdict "with marker, source write allowed" "allow" "$actual"
    rm -rf "$repo"
}

# ---------- 10: lookalike basename in different context (e.g. echo) — not exempt ----------
{
    repo=$(setup_repo)
    # The echo contains "create-active-workflow.sh" but with `>` redirection to a file
    payload='{"tool_name":"Bash","tool_input":{"command":"echo \"talk about create-active-workflow.sh\" > /tmp/log"}}'
    actual=$(gate_verdict "$payload" "$repo")
    assert_verdict "echo containing helper name with > still denied" "deny" "$actual"
    rm -rf "$repo"
}

# ---------- 11: bash invoking helper from absolute path ----------
{
    repo=$(setup_repo)
    payload='{"tool_name":"Bash","tool_input":{"command":"bash /usr/local/share/smith/create-active-workflow.sh --branch a --workflow smith-bugfix --slug b --worktree /tmp/w"}}'
    actual=$(gate_verdict "$payload" "$repo")
    assert_verdict "helper allowed via /usr/local-style absolute path" "allow" "$actual"
    rm -rf "$repo"
}

# ---------- 12: write to .smith/index/files works even when SAFE_VAULT path check would fail ----------
{
    repo=$(setup_repo)
    # Relative path
    payload="{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\".smith/index/files/scripts/test.py.meta\",\"content\":\"...\"}}"
    actual=$(gate_verdict "$payload" "$repo")
    assert_verdict "relative .smith/index/files path allowed" "allow" "$actual"
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
