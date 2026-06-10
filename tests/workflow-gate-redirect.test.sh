#!/usr/bin/env bash
# workflow-gate-redirect.test.sh — regression tests for the quote-aware
# redirect detection in hooks/workflow-gate.sh.
#
# Drives the REAL hook end-to-end: builds a throwaway git repo with a .smith/
# dir and NO active-workflow marker (so the gate is armed), pipes a PreToolUse
# Bash payload, and asserts whether the hook DENIES (redirect detected) or
# ALLOWS (read-only / quoted '>' is not a redirect).
#
# Asserting on the hook's actual output means the test can't drift from the
# implementation. Prints PASS/FAIL per case + a summary; exits non-zero on any
# failure so it can run in CI.

set -u

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd -P)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd -P)
HOOK="$REPO_ROOT/hooks/workflow-gate.sh"

if [ ! -f "$HOOK" ]; then
    echo "FATAL: hook not found: $HOOK" >&2
    exit 2
fi

PASS=0
FAIL=0

# A marker-less Smith project so the gate is armed.
FIXTURE=$(mktemp -d)
(
    cd "$FIXTURE" || exit 1
    git init -q
    git config user.email test@example.com
    git config user.name test
    mkdir -p .smith/vault/active-workflows   # exists but EMPTY → no marker
)
cleanup() { rm -rf "$FIXTURE"; }
trap cleanup EXIT

# run_hook <command-string> -> prints "DENY" or "ALLOW"
# Feeds a PreToolUse Bash payload to the hook with CLAUDE_PROJECT_DIR=fixture.
run_hook() {
    local cmd="$1"
    local payload
    payload=$(CMD="$cmd" python3 -c '
import json, os
print(json.dumps({
    "tool_name": "Bash",
    "tool_input": {"command": os.environ["CMD"]},
}))')
    local out
    out=$(printf '%s' "$payload" | CLAUDE_PROJECT_DIR="$FIXTURE" bash "$HOOK" 2>/dev/null)
    # The hook prints a JSON deny object when blocking; empty/exit-0 when allowing.
    if printf '%s' "$out" | grep -q '"permissionDecision": "deny"'; then
        echo "DENY"
    else
        echo "ALLOW"
    fi
}

# assert <expected DENY|ALLOW> <command> <label>
assert() {
    local expected="$1" cmd="$2" label="$3"
    local got
    got=$(run_hook "$cmd")
    if [ "$got" = "$expected" ]; then
        echo "PASS [$expected] $label"
        PASS=$((PASS + 1))
    else
        echo "FAIL  expected=$expected got=$got :: $label"
        echo "        cmd: $cmd"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== SHOULD NOT BLOCK (quoted '>' / '<' is not a redirect) ==="
assert ALLOW 'git commit -m "msg <a@b.com>"'              'git trailer with <email> in double quotes'
assert ALLOW 'echo "=== >>> banner <<< ==="'              'echo banner with >>> and <<< quoted'
assert ALLOW "git log --format='%an <%ae>'"               'git log --format with <%ae> single-quoted'
assert ALLOW "grep '# >>> marker'"                        'grep pattern with >>> single-quoted'
assert ALLOW 'echo "a -> b"'                              'echo arrow a -> b quoted'
assert ALLOW 'git commit -m "fix: handle a<b and c>d cases"' 'inequality glyphs inside quoted commit msg'

echo ""
echo "=== SHOULD BLOCK (real redirects still caught) ==="
assert DENY 'echo x > file.txt'                           'plain > redirect'
assert DENY 'cat a >> b'                                  'append >> redirect'
assert DENY 'foo &> out'                                  'combined &> redirect'
assert DENY 'command > /tmp/x'                            'redirect to absolute path'
assert DENY 'echo hello > out.txt'                        'unquoted redirect after echo'

echo ""
echo "=== FAIL-SAFE (ambiguous/unbalanced quoting → block) ==="
assert DENY 'echo "unterminated > thing'                  'unbalanced double-quote with > → fail-safe block'

echo ""
echo "=== sanity: real mutators still blocked (unchanged behavior) ==="
assert DENY 'rm -rf /tmp/x'                               'rm still blocked'
assert DENY "sed -i 's/a/b/' file"                        'sed -i still blocked'

echo ""
echo "--- $PASS passed, $FAIL failed ---"
[ "$FAIL" -eq 0 ] || exit 1
