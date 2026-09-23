#!/usr/bin/env bash
# workflow-gate-quoted-verbs.test.sh — a mutating verb inside a QUOTED
# ARGUMENT is not a command, and must not arm the gate.
#
# hooks/workflow-gate.sh already blanks quoted spans before testing for shell
# redirection (see workflow-gate-redirect.test.sh, and the REDIR_TEST builder
# in the hook). The mutator-word loop and the `sed -i` check did not use that
# same blanked copy — they matched against the raw command — so a verb sitting
# inside a grep pattern or an echo string read as a command in command
# position.
#
# Two real denials from one session, both read-only:
#   grep -nE 'foo|rm |bar' file      -> the `|` before `rm` satisfies the
#                                       command-position class
#   echo "(must not become the tee itself)"
#                                    -> `tee` surrounded by spaces
#
# False positives on a security control are not free. An agent that learns
# denials are noise is an agent that routes around them — which is exactly
# what happened earlier in the same session that produced these two cases.
#
# `bash -c '<payload>'` is handled deliberately, see the SHELL-C section.

set -u

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd -P)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd -P)
HOOK="$REPO_ROOT/hooks/workflow-gate.sh"
[ -f "$HOOK" ] || { echo "FATAL: hook not found: $HOOK" >&2; exit 2; }

PASS=0
FAIL=0

# A markerless Smith project, so the gate is armed.
FIXTURE=$(mktemp -d)
(
    cd "$FIXTURE" || exit 1
    git init -q
    git config user.email test@example.com
    git config user.name test
    mkdir -p .smith/vault/active-workflows   # exists but EMPTY -> no marker
)
cleanup() { rm -rf "$FIXTURE"; }
trap cleanup EXIT

run_bash_hook() {
    local out
    out=$(CMD="$1" python3 -c '
import json, os
print(json.dumps({
    "tool_name": "Bash",
    "tool_input": {"command": os.environ["CMD"]},
}))' | CLAUDE_PROJECT_DIR="$FIXTURE" bash "$HOOK" 2>/dev/null)
    if printf '%s' "$out" | grep -q '"permissionDecision": "deny"'; then
        echo "DENY"
    else
        echo "ALLOW"
    fi
}

run_write_hook() {
    local out
    out=$(P="$1" python3 -c '
import json, os
print(json.dumps({
    "tool_name": "Write",
    "tool_input": {"file_path": os.environ["P"], "content": "x"},
}))' | CLAUDE_PROJECT_DIR="$FIXTURE" bash "$HOOK" 2>/dev/null)
    if printf '%s' "$out" | grep -q '"permissionDecision": "deny"'; then
        echo "DENY"
    else
        echo "ALLOW"
    fi
}

expect() {
    local want="$1" got="$2" label="$3"
    if [ "$want" = "$got" ]; then
        PASS=$((PASS + 1)); printf 'PASS  %s\n' "$label"
    else
        FAIL=$((FAIL + 1)); printf 'FAIL  %s\n        wanted %s, got %s\n' "$label" "$want" "$got"
    fi
}

# --- verbs inside quoted arguments are ARGUMENTS, not commands -------------
expect ALLOW "$(run_bash_hook "grep -nE 'foo|rm |bar' somefile")" \
    "a grep pattern containing '|rm ' is read-only"
expect ALLOW "$(run_bash_hook "echo '(must not become the tee itself)'")" \
    "an echo string containing ' tee ' is read-only"
expect ALLOW "$(run_bash_hook 'echo "do not rm the file"')" \
    "a double-quoted string containing ' rm ' is read-only"
expect ALLOW "$(run_bash_hook "grep -c 'cp \\|mv ' notes.txt")" \
    "several verbs inside one quoted pattern are still read-only"

# --- real mutations must still be DENIED -----------------------------------
expect DENY "$(run_bash_hook 'rm -rf x')" \
    "a bare mutator in command position is still denied"
expect DENY "$(run_bash_hook 'foo && rm bar')" \
    "a mutator after && is still denied"
expect DENY "$(run_bash_hook 'cat a | tee b')" \
    "a mutator after a real pipe is still denied"
expect DENY "$(run_bash_hook "sed -i 's/a/b/' f")" \
    "sed -i is still denied"
expect DENY "$(run_bash_hook 'echo x > file')" \
    "redirection is still denied (unchanged path)"

# --- SHELL-C: a quoted payload handed to a shell IS executed ---------------
# Decision: `bash -c '<payload>'` must stay DENIED. Blanking quoted spans
# would otherwise hide the payload, which is a real weakening rather than a
# false-positive fix — the payload is not an argument being matched on, it is
# a command the shell will run. So when the command invokes an interpreter
# with -c, the raw text is examined as well.
#
# This does NOT close the wider hole where a program writes files without
# naming a mutating verb at all (e.g. `python3 -c "open(p,'w')"`). That is a
# separate, known, design-level limitation of the gate and is out of scope
# here; it is tracked as its own defect.
expect DENY "$(run_bash_hook "bash -c 'rm x'")" \
    "bash -c with a mutating payload is still denied"
expect DENY "$(run_bash_hook "sh -c \"rm x\"")" \
    "sh -c with a mutating payload is still denied"

# --- fail-safe: unbalanced quoting must not become an escape hatch ---------
expect DENY "$(run_bash_hook "echo 'unbalanced && rm x")" \
    "unbalanced quoting falls back to the raw command and stays denied"

# --- the explore vault directory is writable (smith-explore Phase 4) -------
# /smith-new runs exploration at Phase 0 but creates the marker at Phase 1,
# so without this exemption smith-explore's report-writing phase is
# unreachable in its primary invocation path.
expect ALLOW "$(run_write_hook "$FIXTURE/.smith/vault/explore/explore-2026-01-01-x.md")" \
    "a write into .smith/vault/explore/ is allowed without a marker"

# --- control: a write OUTSIDE the vault is still denied --------------------
expect DENY "$(run_write_hook "$FIXTURE/src/app.py")" \
    "a write outside the vault is still denied (exemption is not a blanket allow)"

echo "----"
echo "SUMMARY: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
