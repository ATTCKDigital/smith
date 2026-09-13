#!/usr/bin/env bash
# Integration tests for hooks/security-guard-mcp-browser.sh (feature
# 53-mcp-browser-access — closes the blocking PreToolUse guard gap for
# mcp__playwright__* tools).
#
# Harness reused from tests/hooks/test_workflow_gate_exemption.sh:
# HERE/REPO resolution, a *_verdict() helper feeding synthesized PreToolUse
# JSON to the hook via stdin, assert_verdict() PASS/FAIL counters, and a
# closing summary with non-zero exit on any failure.
#
# Run:  bash tests/hooks/test_security_guard_mcp_browser.sh
#       zsh  tests/hooks/test_security_guard_mcp_browser.sh
#
# NFR-2/SC-4: every guard invocation below defaults to whichever shell is
# currently running *this* script (ZSH_VERSION/BASH_VERSION) — so a bash
# run exercises `bash "$GUARD"` throughout and a zsh run exercises
# `zsh "$GUARD"` throughout; diffing the two full runs' stdout is what
# actually proves bash/zsh parity, not just the harness's own portability.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
GUARD="$REPO/hooks/security-guard-mcp-browser.sh"

if [ -n "${ZSH_VERSION:-}" ]; then
    DEFAULT_INTERPRETER="zsh"
else
    DEFAULT_INTERPRETER="bash"
fi

PASS=0
FAIL=0
FAILED_NAMES=()

# Feed the guard JSON on stdin; returns "allow" or "deny" based on the
# hookSpecificOutput.permissionDecision field (absent/"allow" -> allow).
# Both a tight and a loose quoting variant are grepped for, matching the
# workflow-gate harness's dual-format tolerance.
guard_output() {
    local payload="$1" repo="$2" interpreter="${3:-$DEFAULT_INTERPRETER}"
    printf '%s' "$payload" | env CLAUDE_PROJECT_DIR="$repo" "$interpreter" "$GUARD" 2>/dev/null
}

verdict_from_output() {
    local out="$1"
    if printf '%s' "$out" | grep -q '"permissionDecision":[[:space:]]*"deny"'; then
        printf 'deny'
    elif printf '%s' "$out" | grep -q "'permissionDecision': 'deny'"; then
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
        PASS=$((PASS + 1))
        printf 'PASS  %s\n' "$name"
    else
        FAIL=$((FAIL + 1))
        FAILED_NAMES+=("$name")
        printf 'FAIL  %s\n  expected: %s\n  actual:   %s\n' "$name" "$expected" "$actual"
    fi
}

assert_contains() {
    local name="$1" haystack="$2" needle="$3"
    if printf '%s' "$haystack" | grep -qF "$needle"; then
        PASS=$((PASS + 1))
        printf 'PASS  %s\n' "$name"
    else
        FAIL=$((FAIL + 1))
        FAILED_NAMES+=("$name")
        printf 'FAIL  %s\n  expected output to contain: %s\n' "$name" "$needle"
    fi
}

# mktemp scaffold: git-init a throwaway repo with .smith/vault/ present.
# config is written per-case by the caller (or omitted, for absent-config
# cases).
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

write_config() {
    local repo="$1" allow_interactions="$2" warn_only="$3"
    cat > "$repo/.smith/security-config.json" <<EOF
{
  "warn_only_mode": $warn_only,
  "browser_verification": {
    "urls": {
      "staging": [{"name":"staging","url":"https://staging.example.com","label":"staging"}],
      "production": [{"name":"production","url":"https://app.example.com","label":"production"}]
    },
    "allow_interactions": $allow_interactions
  }
}
EOF
}

navigate_payload() {
    printf '{"tool_name":"mcp__playwright__browser_navigate","tool_input":{"url":"%s"}}' "$1"
}

interaction_payload() {
    local tool="${2:-browser_click}"
    printf '{"tool_name":"mcp__playwright__%s","tool_input":{"ref":"e1"}}' "$tool"
}

navigate_and_get_target() {
    # Runs a navigate call (which writes .mcp-browser-target) and returns
    # nothing useful by itself; callers just need the side effect.
    local repo="$1" url="$2"
    guard_verdict "$(navigate_payload "$url")" "$repo" > /dev/null
}
# ---------- 1: read-only tool always allowed, no config present, any target ----------
{
    repo=$(setup_repo)
    actual=$(guard_verdict '{"tool_name":"mcp__playwright__browser_snapshot","tool_input":{}}' "$repo")
    assert_verdict "read-only tool allowed, no config present" "allow" "$actual"
    rm -rf "$repo"
}
# ---------- 2: non-playwright tool ignored ----------
{
    repo=$(setup_repo)
    actual=$(guard_verdict '{"tool_name":"Bash","tool_input":{"command":"ls"}}' "$repo")
    assert_verdict "non-playwright tool ignored" "allow" "$actual"
    rm -rf "$repo"
}
# ---------- 3: interaction allowed on listed staging (allow_interactions true) ----------
{
    repo=$(setup_repo)
    write_config "$repo" "true" "false"
    navigate_and_get_target "$repo" "https://staging.example.com/dashboard"
    actual=$(guard_verdict "$(interaction_payload "$repo" browser_click)" "$repo")
    assert_verdict "interaction allowed on listed staging target" "allow" "$actual"
    rm -rf "$repo"
}
# ---------- 4: interaction denied on listed production, no confirmation; reason names URL + "confirmation" ----------
{
    repo=$(setup_repo)
    write_config "$repo" "true" "false"
    navigate_and_get_target "$repo" "https://app.example.com/admin/users"
    out=$(guard_output "$(interaction_payload "$repo" browser_click)" "$repo")
    assert_verdict "interaction denied on listed production, no confirmation" "deny" "$(verdict_from_output "$out")"
    assert_contains "production denial reason names the target URL" "$out" "https://app.example.com/admin/users"
    assert_contains "production denial reason states confirmation is required" "$out" "confirmation"
    rm -rf "$repo"
}
# ---------- 5: unmatched target treated as production (fail-safe default, Q3) ----------
{
    repo=$(setup_repo)
    write_config "$repo" "true" "false"
    navigate_and_get_target "$repo" "https://totally-unlisted.example.net/page"
    actual=$(guard_verdict "$(interaction_payload "$repo" browser_click)" "$repo")
    assert_verdict "unmatched target denied (fail-safe default -> production)" "deny" "$actual"
    rm -rf "$repo"
}
# ---------- 6: localhost carve-out, even with empty urls lists ----------
{
    repo=$(setup_repo)
    cat > "$repo/.smith/security-config.json" <<'EOF'
{
  "warn_only_mode": false,
  "browser_verification": {
    "urls": {"staging": [], "production": []},
    "allow_interactions": true
  }
}
EOF
    navigate_and_get_target "$repo" "http://127.0.0.1:3000/app"
    actual=$(guard_verdict "$(interaction_payload "$repo" browser_click)" "$repo")
    assert_verdict "localhost/127.0.0.1 always classified staging" "allow" "$actual"
    rm -rf "$repo"
}
# ---------- 7: interaction allowed on production once a matching confirmation fixture exists (US-8) ----------
{
    repo=$(setup_repo)
    write_config "$repo" "true" "false"
    navigate_and_get_target "$repo" "https://app.example.com/admin/users"
    printf '{"url":"https://app.example.com/admin/users","confirmed_at":"2026-09-13T00:00:00Z"}' > "$repo/.smith/vault/.mcp-browser-confirmed"
    actual=$(guard_verdict "$(interaction_payload "$repo" browser_click)" "$repo")
    assert_verdict "interaction allowed on production with matching confirmation" "allow" "$actual"
    rm -rf "$repo"
}
# ---------- 8: stale confirmation (different URL) still denied ----------
{
    repo=$(setup_repo)
    write_config "$repo" "true" "false"
    navigate_and_get_target "$repo" "https://app.example.com/admin/users"
    printf '{"url":"https://app.example.com/some/other/page","confirmed_at":"2026-09-13T00:00:00Z"}' > "$repo/.smith/vault/.mcp-browser-confirmed"
    actual=$(guard_verdict "$(interaction_payload "$repo" browser_click)" "$repo")
    assert_verdict "stale confirmation for a different URL still denied" "deny" "$actual"
    rm -rf "$repo"
}
# ---------- 9: production denial persists even with warn_only_mode: true (Q1, non-bypassable) ----------
{
    repo=$(setup_repo)
    write_config "$repo" "true" "true"
    navigate_and_get_target "$repo" "https://app.example.com/admin/users"
    actual=$(guard_verdict "$(interaction_payload "$repo" browser_click)" "$repo")
    assert_verdict "production confirm-gate NOT downgraded by warn_only_mode" "deny" "$actual"
    rm -rf "$repo"
}
# ---------- 10a: allow_interactions=false denies an interaction call on a STAGING target ----------
{
    repo=$(setup_repo)
    write_config "$repo" "false" "false"
    navigate_and_get_target "$repo" "https://staging.example.com/dashboard"
    actual=$(guard_verdict "$(interaction_payload "$repo" browser_click)" "$repo")
    assert_verdict "allow_interactions=false denies interaction on staging" "deny" "$actual"
    rm -rf "$repo"
}
# ---------- 10b: contrast — the same kill-switch denial IS downgraded under warn_only_mode: true ----------
{
    repo=$(setup_repo)
    write_config "$repo" "false" "true"
    navigate_and_get_target "$repo" "https://staging.example.com/dashboard"
    actual=$(guard_verdict "$(interaction_payload "$repo" browser_click)" "$repo")
    assert_verdict "allow_interactions kill-switch IS downgraded by warn_only_mode" "allow" "$actual"
    rm -rf "$repo"
}
# ---------- 11: browser_evaluate gated identically to browser_click (Q4 — no JS heuristic) ----------
{
    repo=$(setup_repo)
    write_config "$repo" "true" "false"
    navigate_and_get_target "$repo" "https://app.example.com/admin/users"
    payload='{"tool_name":"mcp__playwright__browser_evaluate","tool_input":{"function":"() => document.title"}}'
    actual=$(guard_verdict "$payload" "$repo")
    assert_verdict "browser_evaluate (read-only-looking script) denied on production like browser_click" "deny" "$actual"
    rm -rf "$repo"
}
# ---------- 12: missing config file -> interaction tool allowed through (no-op, FR-6/NFR-1) ----------
{
    repo=$(setup_repo)
    # No .smith/security-config.json written at all.
    actual=$(guard_verdict "$(interaction_payload "$repo" browser_click)" "$repo")
    assert_verdict "missing config file -> interaction allowed through (no-op)" "allow" "$actual"
    rm -rf "$repo"
}
# ---------- 13: malformed JSON in the config file -> no-op, never a crash ----------
{
    repo=$(setup_repo)
    printf '{ this is not valid json' > "$repo/.smith/security-config.json"
    actual=$(guard_verdict "$(interaction_payload "$repo" browser_click)" "$repo")
    assert_verdict "malformed config JSON -> no-op, no crash" "allow" "$actual"
    rm -rf "$repo"
}
# ---------- 14: malformed JSON on stdin -> no crash ----------
{
    repo=$(setup_repo)
    out=$(printf 'not json at all' | env CLAUDE_PROJECT_DIR="$repo" "$DEFAULT_INTERPRETER" "$GUARD" 2>&1)
    ec=$?
    assert_verdict "malformed stdin JSON exits 0, no crash" "0" "$ec"
    rm -rf "$repo"
}
# ---------- 15: absent vault dir -> interaction tool allowed through (no-op, FR-6/NFR-1) ----------
{
    repo=$(mktemp -d)
    (cd "$repo" && git init --quiet && git config user.email t@e.com && git config user.name t && git commit --allow-empty -m init --quiet)
    mkdir -p "$repo/.smith"
    write_config "$repo" "true" "false"
    actual=$(guard_verdict "$(interaction_payload "$repo" browser_click)" "$repo")
    assert_verdict "absent vault dir -> interaction allowed through (no-op)" "allow" "$actual"
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
