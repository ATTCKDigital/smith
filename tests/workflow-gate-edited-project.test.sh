#!/usr/bin/env bash
# workflow-gate-edited-project.test.sh — the gate accepts an active marker in
# the project being EDITED, not only in the session's own project.
#
# Layout (all throwaway):
#   SESSION/   non-git folder with .smith/ and no marker (the session started here)
#   MARKED/    git repo with .smith/ and an active marker
#   UNMARKED/  git repo with .smith/ and no marker
#   WT/        git worktree of MARKED (markers live in the primary repo)
# Drives the REAL hook with CLAUDE_PROJECT_DIR=SESSION and asserts ALLOW/DENY.

set -u

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd -P)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd -P)
HOOK="$REPO_ROOT/hooks/workflow-gate.sh"
[ -f "$HOOK" ] || { echo "FATAL: hook not found: $HOOK" >&2; exit 2; }

PASS=0
FAIL=0
BASE=$(cd "$(mktemp -d)" && pwd -P)
SESSION="$BASE/session"
MARKED="$BASE/marked"
UNMARKED="$BASE/unmarked"
WT="$BASE/wt"
cleanup() { git -C "$MARKED" worktree remove --force "$WT" >/dev/null 2>&1; rm -rf "$BASE"; }
trap cleanup EXIT

make_repo() {
    mkdir -p "$1/.smith/vault/active-workflows"
    git -C "$1" init -q
    git -C "$1" config user.email test@example.com
    git -C "$1" config user.name test
    touch "$1/README"
    git -C "$1" add README
    git -C "$1" commit -q -m init
}
mkdir -p "$SESSION/.smith/vault/active-workflows"
make_repo "$MARKED"
make_repo "$UNMARKED"
printf 'branch: fix/x\nworkflow: smith-bugfix\n' > "$MARKED/.smith/vault/active-workflows/fix-x.yaml"
git -C "$MARKED" worktree add -q "$WT" -b fix/x

# run_hook <tool> <field> <value> -> DENY | ALLOW
run_hook() {
    local payload out
    payload=$(TOOL="$1" FIELD="$2" VALUE="$3" python3 -c '
import json, os
print(json.dumps({"tool_name": os.environ["TOOL"],
                  "tool_input": {os.environ["FIELD"]: os.environ["VALUE"]}}))')
    out=$(cd "$SESSION" && printf '%s' "$payload" | CLAUDE_PROJECT_DIR="$SESSION" bash "$HOOK" 2>/dev/null)
    if printf '%s' "$out" | grep -q '"permissionDecision": "deny"'; then echo DENY; else echo ALLOW; fi
}

assert() {
    local expected="$1" tool="$2" field="$3" value="$4" label="$5" got
    got=$(run_hook "$tool" "$field" "$value")
    if [ "$got" = "$expected" ]; then
        echo "PASS [$expected] $label"; PASS=$((PASS + 1))
    else
        echo "FAIL  expected=$expected got=$got :: $label"; echo "        $field: $value"; FAIL=$((FAIL + 1))
    fi
}

echo "=== Write / Edit ==="
assert ALLOW Write file_path "$MARKED/src/app.js"        'write into a repo with an active marker'
assert ALLOW Edit  file_path "$WT/src/app.js"            'edit inside that repo'"'"'s worktree'
assert DENY  Write file_path "$UNMARKED/src/app.js"      'write into a repo without a marker'
assert DENY  Write file_path "$SESSION/notes.md"         'write into the marker-less session folder'
assert DENY  Write file_path "$BASE/loose/file.txt"      'write outside any Smith project'

echo "=== Bash ==="
assert ALLOW Bash command "cd $MARKED && echo hi > out.txt"           'cd into the marked repo, then redirect'
assert ALLOW Bash command "cp /etc/hosts $WT/hosts"                    'copy into the marked worktree'
assert ALLOW Bash command "rm $MARKED/README"                          'remove a file in the marked repo'
assert DENY  Bash command "echo hi > $UNMARKED/out.txt"                'redirect into the unmarked repo'
assert DENY  Bash command "rm $UNMARKED/README"                        'remove a file in the unmarked repo'
assert DENY  Bash command "echo hi > out.txt"                          'redirect with no path (session folder)'
assert ALLOW Bash command "ls $UNMARKED"                               'read-only command stays allowed'

echo
echo "Summary: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
