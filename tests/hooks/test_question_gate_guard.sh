#!/usr/bin/env bash
# Integration tests for hooks/question-gate-guard.sh (feature
# 67-deterministic-questions — PreToolUse guard that suppresses the interactive
# AskUserQuestion popup in favor of Smith's markdown Q&A contract).
#
# Harness reused from tests/hooks/test_security_guard_mcp_browser.sh:
# HERE/REPO resolution, a guard_verdict() helper feeding synthesized PreToolUse
# JSON to the hook via stdin, assert_verdict()/assert_contains() PASS/FAIL
# counters, and a closing summary with non-zero exit on any failure.
#
# Run:  bash tests/hooks/test_question_gate_guard.sh
#       zsh  tests/hooks/test_question_gate_guard.sh
#
# Each guard invocation defaults to whichever shell runs this script, so a bash
# run exercises `bash "$GUARD"` and a zsh run exercises `zsh "$GUARD"` — proving
# bash/zsh parity (NFR-2).

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
GUARD="$REPO/hooks/question-gate-guard.sh"

if [ -n "${ZSH_VERSION:-}" ]; then
    DEFAULT_INTERPRETER="zsh"
else
    DEFAULT_INTERPRETER="bash"
fi

PASS=0
FAIL=0
FAILED_NAMES=()

guard_output() {
    local payload="$1" repo="$2" interpreter="${3:-$DEFAULT_INTERPRETER}"
    printf '%s' "$payload" | env CLAUDE_PROJECT_DIR="$repo" "$interpreter" "$GUARD" 2>/dev/null
}

verdict_from_output() {
    local out="$1"
    if printf '%s' "$out" | grep -q '"permissionDecision":[[:space:]]*"deny"'; then
        printf 'deny'
    else
        printf 'allow'
    fi
}

guard_verdict() {
    verdict_from_output "$(guard_output "$1" "$2" "${3:-}")"
}

assert_verdict() {
    local name="$1" expected="$2" actual="$3"
    if [ "$expected" = "$actual" ]; then
        PASS=$((PASS + 1)); printf 'PASS  %s\n' "$name"
    else
        FAIL=$((FAIL + 1)); FAILED_NAMES+=("$name")
        printf 'FAIL  %s\n  expected: %s\n  actual:   %s\n' "$name" "$expected" "$actual"
    fi
}

assert_contains() {
    local name="$1" haystack="$2" needle="$3"
    if printf '%s' "$haystack" | grep -qF "$needle"; then
        PASS=$((PASS + 1)); printf 'PASS  %s\n' "$name"
    else
        FAIL=$((FAIL + 1)); FAILED_NAMES+=("$name")
        printf 'FAIL  %s\n  expected output to contain: %s\n' "$name" "$needle"
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
    mkdir -p "$d/.smith/vault"
    printf '%s' "$d"
}

write_mode() {
    local repo="$1" mode="$2"
    cat > "$repo/.smith/config.json" <<EOF
{ "question_gate": { "mode": "$mode" } }
EOF
}

add_marker() {
    local repo="$1"
    mkdir -p "$repo/.smith/vault/active-workflows"
    printf 'branch: x\n' > "$repo/.smith/vault/active-workflows/x.yaml"
}

ASK='{"tool_name":"AskUserQuestion","tool_input":{"questions":[{"question":"pick"}]}}'

# ---------- 1: non-AskUserQuestion tool -> inert (allow), no config ----------
{
    repo=$(setup_repo)
    actual=$(guard_verdict '{"tool_name":"Bash","tool_input":{"command":"ls"}}' "$repo")
    assert_verdict "non-AskUserQuestion tool ignored" "allow" "$actual"
    rm -rf "$repo"
}
# ---------- 2: mode deny -> deny, reason redirects to the Q&A contract ----------
{
    repo=$(setup_repo); write_mode "$repo" "deny"
    out=$(guard_output "$ASK" "$repo")
    assert_verdict "mode deny blocks the popup" "deny" "$(verdict_from_output "$out")"
    assert_contains "deny reason mentions the smith-question contract" "$out" "smith-question"
    assert_contains "deny reason instructs markdown presentation" "$out" "markdown"
    rm -rf "$repo"
}
# ---------- 3: mode warn -> allow, attaches a reminder ----------
{
    repo=$(setup_repo); write_mode "$repo" "warn"
    out=$(guard_output "$ASK" "$repo")
    assert_verdict "mode warn allows the popup" "allow" "$(verdict_from_output "$out")"
    assert_contains "warn output carries a reminder" "$out" "additionalContext"
    rm -rf "$repo"
}
# ---------- 4: mode off -> allow ----------
{
    repo=$(setup_repo); write_mode "$repo" "off"
    assert_verdict "mode off allows the popup" "allow" "$(guard_verdict "$ASK" "$repo")"
    rm -rf "$repo"
}
# ---------- 5: workflow-gated WITH marker -> deny ----------
{
    repo=$(setup_repo); write_mode "$repo" "workflow-gated"; add_marker "$repo"
    assert_verdict "workflow-gated denies when a marker is active" "deny" "$(guard_verdict "$ASK" "$repo")"
    rm -rf "$repo"
}
# ---------- 6: workflow-gated WITHOUT marker -> allow ----------
{
    repo=$(setup_repo); write_mode "$repo" "workflow-gated"
    assert_verdict "workflow-gated allows with no active marker" "allow" "$(guard_verdict "$ASK" "$repo")"
    rm -rf "$repo"
}
# ---------- 7: absent config file -> allow (fail-open) ----------
{
    repo=$(setup_repo)
    assert_verdict "absent config -> fail-open allow" "allow" "$(guard_verdict "$ASK" "$repo")"
    rm -rf "$repo"
}
# ---------- 8: malformed config JSON -> allow (fail-open), no crash ----------
{
    repo=$(setup_repo)
    printf '{ this is not valid json' > "$repo/.smith/config.json"
    assert_verdict "malformed config -> fail-open allow" "allow" "$(guard_verdict "$ASK" "$repo")"
    rm -rf "$repo"
}
# ---------- 9: absent question_gate key -> allow (fail-open to off) ----------
{
    repo=$(setup_repo)
    printf '{ "quality": {} }' > "$repo/.smith/config.json"
    assert_verdict "absent question_gate key -> off (allow)" "allow" "$(guard_verdict "$ASK" "$repo")"
    rm -rf "$repo"
}
# ---------- 10: unknown mode value -> allow (fail-open to off) ----------
{
    repo=$(setup_repo); write_mode "$repo" "banana"
    assert_verdict "unknown mode -> off (allow)" "allow" "$(guard_verdict "$ASK" "$repo")"
    rm -rf "$repo"
}
# ---------- 11: malformed stdin JSON -> exit 0, no crash ----------
{
    repo=$(setup_repo)
    printf 'not json at all' | env CLAUDE_PROJECT_DIR="$repo" "$DEFAULT_INTERPRETER" "$GUARD" >/dev/null 2>&1
    assert_verdict "malformed stdin JSON exits 0" "0" "$?"
    rm -rf "$repo"
}
# ---------- 12: deny persists regardless of marker in plain deny mode ----------
{
    repo=$(setup_repo); write_mode "$repo" "deny"; add_marker "$repo"
    assert_verdict "deny mode is global (denies with a marker too)" "deny" "$(guard_verdict "$ASK" "$repo")"
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
