#!/usr/bin/env bash
# Unit tests for user-prompt-logger.sh (UserPromptSubmit hook).
#
# Verifies:
#   - A simple prompt is appended as a "### [HH:MM:SS] User prompt" blockquote
#   - A multi-line prompt with embedded quotes is captured VERBATIM, every line
#     blockquoted, nothing truncated (the verbatim-fidelity guarantee)
#   - Blank lines inside a prompt become a bare ">" (contiguous blockquote)
#   - No .current-session / no vault → exit 0, writes nothing, no error
#   - Empty / whitespace-only prompt → skipped (no block appended)
#   - Malformed JSON on stdin → exit 0, no crash
#   - settings/smith-settings-fragment.json is valid JSON and wires BOTH
#     context-loader.sh and user-prompt-logger.sh under UserPromptSubmit
#   - A session log containing prompt blocks does not break
#     workflow-summary.sh aggregation assumptions (prompt headings are ignored)
#
# Run:
#   bash tests/hooks/test_user_prompt_logger.sh

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
HOOK="$REPO/hooks/user-prompt-logger.sh"
FRAGMENT="$REPO/settings/smith-settings-fragment.json"

PASS=0
FAIL=0
FAILED_NAMES=()

assert_eq() {
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
    if printf '%s' "$haystack" | grep -qF -- "$needle"; then
        PASS=$((PASS + 1)); printf 'PASS  %s\n' "$name"
    else
        FAIL=$((FAIL + 1)); FAILED_NAMES+=("$name")
        printf 'FAIL  %s\n  missing substring: %s\n' "$name" "$needle"
    fi
}

assert_not_contains() {
    local name="$1" haystack="$2" needle="$3"
    if printf '%s' "$haystack" | grep -qF -- "$needle"; then
        FAIL=$((FAIL + 1)); FAILED_NAMES+=("$name")
        printf 'FAIL  %s\n  unexpected substring present: %s\n' "$name" "$needle"
    else
        PASS=$((PASS + 1)); printf 'PASS  %s\n' "$name"
    fi
}

# Build a temp project with an initialized vault + .current-session pointer.
# Echoes: <project_dir> on line 1, <session_file> on line 2.
setup_vault() {
    local project session
    project="$(mktemp -d)"
    mkdir -p "$project/.smith/vault/sessions"
    session="$project/.smith/vault/sessions/test-session.md"
    cat > "$session" <<'EOF'
---
session_start: "2026-06-08T00:00:00"
project: "test"
status: active
---

# Session Log

## Started: 2026-06-08 00:00:00

---
EOF
    echo "$session" > "$project/.smith/vault/.current-session"
    printf '%s\n%s\n' "$project" "$session"
}

invoke_hook() {
    # $1 = project dir, $2 = JSON payload (stdin)
    local project="$1" payload="$2"
    printf '%s' "$payload" | CLAUDE_PROJECT_DIR="$project" bash "$HOOK"
}

# ---------- Test 1: simple prompt appended as blockquote ----------
test_simple_prompt() {
    local paths project session
    paths=$(setup_vault); project=$(echo "$paths" | sed -n 1p); session=$(echo "$paths" | sed -n 2p)

    invoke_hook "$project" '{"prompt":"fix the timesheet bug"}'
    local content; content=$(cat "$session")

    assert_contains "simple: heading present" "$content" "### ["
    assert_contains "simple: 'User prompt' label" "$content" "] User prompt"
    assert_contains "simple: body blockquoted verbatim" "$content" "> fix the timesheet bug"

    rm -rf "$project"
}

# ---------- Test 2: multi-line prompt with quotes, verbatim ----------
test_multiline_verbatim() {
    local paths project session
    paths=$(setup_vault); project=$(echo "$paths" | sed -n 1p); session=$(echo "$paths" | sed -n 2p)

    # JSON-encoded payload: two lines, a blank line, and an embedded double quote.
    # prompt = 'line one\n\nsaid "hello" to me'
    invoke_hook "$project" '{"prompt":"line one\n\nsaid \"hello\" to me"}'
    local content; content=$(cat "$session")

    assert_contains "multiline: line one quoted" "$content" "> line one"
    assert_contains "multiline: embedded quote survives verbatim" "$content" '> said "hello" to me'
    assert_contains "multiline: blank line becomes bare >" "$content" $'>\n'

    rm -rf "$project"
}

# ---------- Test 3: no vault / no .current-session → no-op ----------
test_no_vault() {
    local project; project="$(mktemp -d)"   # no .smith at all

    local out rc
    out=$(invoke_hook "$project" '{"prompt":"hello"}' 2>&1); rc=$?
    assert_eq "no-vault: exit 0" "0" "$rc"
    assert_eq "no-vault: no stdout" "" "$out"

    rm -rf "$project"
}

# ---------- Test 4: empty / whitespace prompt → skipped ----------
test_empty_prompt() {
    local paths project session before after
    paths=$(setup_vault); project=$(echo "$paths" | sed -n 1p); session=$(echo "$paths" | sed -n 2p)

    before=$(wc -c < "$session")
    invoke_hook "$project" '{"prompt":"   \n  "}'
    after=$(wc -c < "$session")

    assert_eq "empty-prompt: session log unchanged" "$before" "$after"

    rm -rf "$project"
}

# ---------- Test 5: malformed JSON → exit 0, no crash ----------
test_malformed_json() {
    local paths project session before after rc
    paths=$(setup_vault); project=$(echo "$paths" | sed -n 1p); session=$(echo "$paths" | sed -n 2p)

    before=$(wc -c < "$session")
    invoke_hook "$project" 'this is not json'; rc=$?
    after=$(wc -c < "$session")

    assert_eq "malformed: exit 0" "0" "$rc"
    assert_eq "malformed: session log unchanged" "$before" "$after"

    rm -rf "$project"
}

# ---------- Test 6: settings fragment valid + wires both hooks ----------
test_fragment_wiring() {
    if python3 -m json.tool "$FRAGMENT" >/dev/null 2>&1; then
        PASS=$((PASS + 1)); printf 'PASS  %s\n' "fragment: valid JSON"
    else
        FAIL=$((FAIL + 1)); FAILED_NAMES+=("fragment: valid JSON")
        printf 'FAIL  %s\n' "fragment: valid JSON"
    fi

    local ups
    ups=$(python3 - "$FRAGMENT" <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
hooks = d["hooks"]["UserPromptSubmit"][0]["hooks"]
cmds = [h["command"] for h in hooks]
print("\n".join(cmds))
PYEOF
)
    assert_contains "fragment: context-loader still wired" "$ups" "context-loader.sh"
    assert_contains "fragment: user-prompt-logger wired" "$ups" "user-prompt-logger.sh"
    # Order: context-loader before logger (Q2 answer A)
    local first; first=$(printf '%s\n' "$ups" | head -1)
    assert_contains "fragment: context-loader runs first" "$first" "context-loader.sh"
}

# ---------- Test 7: prompt blocks don't pollute metric-line aggregation ----------
test_aggregation_safe() {
    local paths project session
    paths=$(setup_vault); project=$(echo "$paths" | sed -n 1p); session=$(echo "$paths" | sed -n 2p)

    # Simulate a realistic log: a metrics line, then a prompt block.
    printf '\n## Metrics\n\n- `[00:00:01]` **Bash** in:10 out:20 total:30 (ls)\n' >> "$session"
    invoke_hook "$project" '{"prompt":"/smith-build go"}'

    # The aggregation pattern used by workflow-summary keys off lines starting
    # with "- `[" (metric lines). The prompt heading starts with "### [" and the
    # body with "> " — neither matches the metric-line prefix.
    local metric_lines
    metric_lines=$(grep -c '^- `\[' "$session")
    assert_eq "aggregation: exactly one metric line counted" "1" "$metric_lines"

    # And the slash-command prompt WAS captured (Q3 answer A).
    local content; content=$(cat "$session")
    assert_contains "aggregation: slash-command prompt logged" "$content" "> /smith-build go"

    rm -rf "$project"
}

test_simple_prompt
test_multiline_verbatim
test_no_vault
test_empty_prompt
test_malformed_json
test_fragment_wiring
test_aggregation_safe

# ---------- summary ----------
echo
echo "----------------------------------------------------------------------"
echo "Ran $((PASS + FAIL)) tests: $PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
    printf 'Failed:\n'
    for n in "${FAILED_NAMES[@]}"; do
        printf '  - %s\n' "$n"
    done
    exit 1
fi
