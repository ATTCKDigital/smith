#!/usr/bin/env bash
# workflow-summary-session.test.sh
#
# Regression tests for the session-rollover resilience of
# hooks/workflow-summary.sh --totals-only (see
# specs/debug/debug-2026-06-03-workflow-summary-zeros.md).
#
# Exercises the REAL hooks/workflow-summary.sh + hooks/workflow_summary_lib.py
# against synthetic vaults in temp dirs. Covers:
#   1. Session file WITH a valid /smith-new invocation marker + a minimal
#      subagent metric block → totals are NOT the n/a degenerate form.
#   2. Session file WITHOUT any marker → prints the n/a diagnostic to stderr
#      and exits non-zero (FIX 2 / S1).
#   3. --session <explicit path> overrides .current-session (FIX 1a): point
#      .current-session at a markerless file but pass --session at a marker
#      file; assert it reads the marker file.
#
# Prints PASS/FAIL per case + a summary; exits non-zero if any case fails.

set -u

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd -P)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd -P)
HOOK="$REPO_ROOT/hooks/workflow-summary.sh"

if [ ! -f "$HOOK" ]; then
    echo "FATAL: hook not found: $HOOK" >&2
    exit 2
fi

PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1"; FAIL=$((FAIL + 1)); }

# write_marker_session <path> — a well-formed session log: /smith-new
# invocation marker + one minimal v2 subagent metric block.
write_marker_session() {
    local path="$1"
    cat > "$path" <<'EOF'
# Session Log

### [13:51:02] /smith-new invocation

**User Request:**
> build the thing

**Synthesized Input:** build the thing

## Metrics

- `[13:51:05]` **Bash** ran something
- `[13:51:30]` **Edit** edited something

### [13:55:00] Subagent completed

**Metrics:**
- model: claude-opus-4
- input_tokens: 1000
- output_tokens: 500
- cache_creation_input_tokens: 200
- cache_read_input_tokens: 4000
- tool_uses: 7
- duration_ms: 42000
- total_tokens: 5700
EOF
}

# write_markerless_session <path> — a fresh, rolled-over session log with NO
# /smith- invocation marker (this is exactly the bug condition).
write_markerless_session() {
    local path="$1"
    cat > "$path" <<'EOF'
# Session Log

session_start: "2026-06-03T19:20:11"

### [19:20:15] Context compacted

**Reason:** rollover
EOF
}

# make_vault — create a temp project with .smith/vault and print its root.
make_vault() {
    local root
    root=$(mktemp -d)
    mkdir -p "$root/.smith/vault/sessions"
    printf '%s' "$root"
}

# run_totals <project_root> <extra-args...> — run the hook in --totals-only
# mode. Captures stdout to $OUT_STDOUT, stderr to $OUT_STDERR, rc to $OUT_RC.
run_totals() {
    local root="$1"; shift
    local err_file out_file
    err_file=$(mktemp)
    out_file=$(mktemp)
    # Pin CLAUDE_HOOKS_DIR to THIS repo's hooks so we exercise the worktree
    # copy of workflow_summary_lib.py, not an older installed copy in
    # ~/.claude/hooks (the wrapper prefers $CLAUDE_HOOKS_DIR first).
    CLAUDE_PROJECT_DIR="$root" CLAUDE_HOOKS_DIR="$REPO_ROOT/hooks" \
        bash "$HOOK" --totals-only "$@" \
        >"$out_file" 2>"$err_file"
    OUT_RC=$?
    OUT_STDOUT=$(cat "$out_file")
    OUT_STDERR=$(cat "$err_file")
    rm -f "$err_file" "$out_file"
}

# --- Case 1: valid marker + subagent block → non-degenerate totals ---
ROOT=$(make_vault)
SESS="$ROOT/.smith/vault/sessions/2026-05-28_183520.md"
write_marker_session "$SESS"
printf '%s' "$SESS" > "$ROOT/.smith/vault/.current-session"
run_totals "$ROOT"
if [ "$OUT_RC" -eq 0 ] \
   && printf '%s' "$OUT_STDOUT" | grep -q "Token Usage:" \
   && ! printf '%s' "$OUT_STDOUT" | grep -q "n/a"; then
    # The subagent block alone yields non-zero normalized tokens.
    if printf '%s' "$OUT_STDOUT" | grep -qE "Token Usage: [0-9]"; then
        pass "case1: valid marker → non-degenerate, non-n/a totals (rc=0)"
    else
        fail "case1: marker present but token line not numeric: $OUT_STDOUT"
    fi
else
    fail "case1: expected rc=0 + numeric Token Usage + no n/a; rc=$OUT_RC stdout=[$OUT_STDOUT] stderr=[$OUT_STDERR]"
fi
rm -rf "$ROOT"

# --- Case 2: no marker → loud n/a diagnostic on stderr + non-zero exit ---
ROOT=$(make_vault)
SESS="$ROOT/.smith/vault/sessions/2026-06-03_192011.md"
write_markerless_session "$SESS"
printf '%s' "$SESS" > "$ROOT/.smith/vault/.current-session"
run_totals "$ROOT"
if [ "$OUT_RC" -ne 0 ] \
   && printf '%s' "$OUT_STDERR" | grep -q "no /smith-(new|bugfix|debug) invocation marker found" \
   && printf '%s' "$OUT_STDERR" | grep -qF "$SESS" \
   && printf '%s' "$OUT_STDOUT" | grep -q "n/a (no workflow invocation found)"; then
    pass "case2: no marker → stderr diagnostic (names file) + n/a stdout + rc!=0"
else
    fail "case2: expected non-zero rc + stderr diagnostic naming $SESS + n/a stdout; rc=$OUT_RC stdout=[$OUT_STDOUT] stderr=[$OUT_STDERR]"
fi
rm -rf "$ROOT"

# --- Case 3: --session overrides .current-session (FIX 1a) ---
ROOT=$(make_vault)
GOOD="$ROOT/.smith/vault/sessions/2026-05-28_183520.md"   # has the marker
BAD="$ROOT/.smith/vault/sessions/2026-06-03_192011.md"    # markerless, fresh
write_marker_session "$GOOD"
write_markerless_session "$BAD"
# .current-session deliberately points at the markerless (wrong) file.
printf '%s' "$BAD" > "$ROOT/.smith/vault/.current-session"
# But we pass --session at the GOOD file: it must win.
run_totals "$ROOT" --session "$GOOD"
if [ "$OUT_RC" -eq 0 ] \
   && printf '%s' "$OUT_STDOUT" | grep -qE "Token Usage: [0-9]" \
   && ! printf '%s' "$OUT_STDOUT" | grep -q "n/a"; then
    pass "case3: --session overrides .current-session → reads marker file"
else
    fail "case3: expected --session to win (numeric totals, rc=0); rc=$OUT_RC stdout=[$OUT_STDOUT] stderr=[$OUT_STDERR]"
fi
# Sanity sub-check: without --session, the same vault is degenerate (proves the
# override is what changed the outcome, not luck).
run_totals "$ROOT"
if [ "$OUT_RC" -ne 0 ] && printf '%s' "$OUT_STDOUT" | grep -q "n/a"; then
    pass "case3b: without --session, the markerless .current-session is degenerate"
else
    fail "case3b: expected degenerate n/a without --session; rc=$OUT_RC stdout=[$OUT_STDOUT]"
fi
rm -rf "$ROOT"

# --- Case 4: active-workflow marker session_log: wins over .current-session (FIX 1b) ---
ROOT=$(make_vault)
GOOD="$ROOT/.smith/vault/sessions/2026-05-28_183520.md"   # has the marker
BAD="$ROOT/.smith/vault/sessions/2026-06-03_192011.md"    # markerless, fresh
write_marker_session "$GOOD"
write_markerless_session "$BAD"
printf '%s' "$BAD" > "$ROOT/.smith/vault/.current-session"
mkdir -p "$ROOT/.smith/vault/active-workflows"
cat > "$ROOT/.smith/vault/active-workflows/fix-something.yaml" <<EOF
workflow: smith-bugfix
feature: something
branch: fix/something
worktree: /tmp/wt
session_log: $GOOD
started: 2026-05-28T18:35:20
EOF
# No --session: resolution should pick up session_log from the single marker.
run_totals "$ROOT"
if [ "$OUT_RC" -eq 0 ] \
   && printf '%s' "$OUT_STDOUT" | grep -qE "Token Usage: [0-9]" \
   && ! printf '%s' "$OUT_STDOUT" | grep -q "n/a"; then
    pass "case4: active-workflow marker session_log overrides .current-session"
else
    fail "case4: expected marker session_log to win; rc=$OUT_RC stdout=[$OUT_STDOUT] stderr=[$OUT_STDERR]"
fi
rm -rf "$ROOT"

echo "----"
echo "SUMMARY: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
