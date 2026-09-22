#!/usr/bin/env bash
# smith-activity.test.sh — the flat CI gate for /smith-activity (FR-54/SC-16).
#
# .github/workflows/test-install.yml runs `for t in tests/*.test.sh` and nothing
# else: no recursion, no find. Every assertion this feature relies on therefore
# either lives here or is reached from here. In particular this file is the only
# thing that makes tests/activity/test_*.py run in CI at all.
#
# Shape copied from tests/settings-dedupe.test.sh:10-27 — `set -uo pipefail`
# (never -e: an assertion that fails must be counted, not abort the run),
# SCRIPT_DIR/REPO_ROOT, PASS/FAIL counters, one assert helper, `mktemp -d -t`
# plus a trap, `# --- Test N ---` banners, and a summary line whose exit status
# is the suite's.

set -uo pipefail

# ${BASH_SOURCE[0]:-$0} rather than a bare ${BASH_SOURCE[0]}: this file is run
# under zsh as well as bash (the dual-shell convention this repo applies to
# every shell surface), and zsh has no BASH_SOURCE, which `set -u` would make
# fatal.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
PASS=0
FAIL=0

assert() {
    if [ "$2" = "true" ]; then
        echo "PASS $1"; PASS=$((PASS+1))
    else
        echo "FAIL $1"; FAIL=$((FAIL+1))
    fi
}

TMP=$(mktemp -d -t smith-activity.XXXXXX)
trap 'rm -rf "$TMP"' EXIT

# Sourced helpers: the emitter harness (run_emitter/emitter_cases and the two
# payload fixtures) and the scratch-repo builders. See tests/lib/
# activity-helpers.sh for the sourcing contract. CI globs `tests/*.test.sh`,
# so a sourced `.sh` adds no CI-invisible test.
# shellcheck source=tests/lib/activity-helpers.sh
. "$SCRIPT_DIR/lib/activity-helpers.sh"

# --- Test 1: the emitter exists and is executable --------------------------
[ -x "$EMITTER" ] \
    && assert "hooks/activity-emitter.sh exists and is executable" true \
    || assert "hooks/activity-emitter.sh exists and is executable" false

# --- Test 2: emitter safety under bash and zsh -----------------------------
# One hanging listener serves every shell. It binds an ephemeral 127.0.0.1
# port, accepts, and deliberately never replies.
cat > "$TMP/hanglistener.py" <<'PY'
import socket
import sys
import time

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 0))
srv.listen(32)
with open(sys.argv[1], "w") as fh:
    fh.write("%d\n" % srv.getsockname()[1])
held = []
deadline = time.time() + float(sys.argv[2])
srv.settimeout(0.5)
while time.time() < deadline:
    try:
        conn, _ = srv.accept()
        held.append(conn)        # accept, then say nothing at all
    except socket.timeout:
        pass
    except OSError:
        break
PY
python3 "$TMP/hanglistener.py" "$TMP/hangport" 120 >/dev/null 2>&1 &
HANG_PID=$!
# disown so the shell does not print a "Terminated: 15" job notice when the
# fixture is killed below; that notice would be stray output on a green run.
disown "$HANG_PID" 2>/dev/null || true
trap 'kill "$HANG_PID" 2>/dev/null; rm -rf "$TMP"' EXIT
# Bounded readiness wait — python3, never `timeout`.
python3 - "$TMP/hangport" <<'PY'
import os
import sys
import time

path = sys.argv[1]
for _ in range(200):
    if os.path.exists(path):
        with open(path) as fh:
            if fh.read().strip():
                sys.exit(0)
    time.sleep(0.05)
sys.exit(1)
PY
if [ $? -eq 0 ]; then
    assert "hanging-listener fixture came up" true
else
    assert "hanging-listener fixture came up" false
    printf '%s\n' "0" > "$TMP/hangport"
fi

emitter_cases bash bash
if command -v zsh >/dev/null 2>&1; then
    emitter_cases zsh zsh
else
    echo "SKIP zsh emitter cases (zsh not installed)"
fi

kill "$HANG_PID" 2>/dev/null
wait "$HANG_PID" 2>/dev/null
trap 'rm -rf "$TMP"' EXIT

# ===========================================================================
# Identity (SC-7 / FR-28) — a worktree is never a second project.
# ===========================================================================

# --- Test 3: SC-7 — primary-repo resolution from inside a worktree ---------
PRIMARY=$(make_repo sc7-primary)
# Outside the primary tree on purpose: $TMP/worktrees, not $PRIMARY/wt.
WT=$(add_worktree "$PRIMARY" "$TMP/worktrees/sc7-feature" sc7-feature)

if [ -d "$WT/.git" ] || [ -f "$WT/.git" ]; then
    assert "SC-7 fixture: linked worktree created outside the primary tree" true
else
    assert "SC-7 fixture: linked worktree created outside the primary tree" false
fi

SC7_OUT="$TMP/sc7.out"
PYTHONPATH="$REPO_ROOT/scripts/activity" python3 - "$PRIMARY" "$WT" > "$SC7_OUT" 2>&1 <<'PY'
import os
import sys

import paths

primary_arg, worktree_arg = sys.argv[1], sys.argv[2]
primary = os.path.realpath(primary_arg)
worktree = os.path.realpath(worktree_arg)

from_primary = paths.primary_repo(primary)
from_worktree = paths.primary_repo(worktree)

ok = True


def check(label, condition):
    global ok
    print("%s %s" % ("ok" if condition else "NOT-OK", label))
    if not condition:
        ok = False


check("resolves from the primary checkout",
      from_primary is not None and os.path.realpath(from_primary) == primary)
# The point of FR-28: the worktree resolves to the PRIMARY, not to itself.
check("resolves from inside the worktree to the primary checkout",
      from_worktree is not None and os.path.realpath(from_worktree) == primary)
check("worktree does not register as a second project",
      from_worktree is not None and os.path.realpath(from_worktree) != worktree)
check("both positions agree",
      from_primary is not None and from_worktree is not None
      and os.path.realpath(from_primary) == os.path.realpath(from_worktree))
# One project slug, therefore one ~/.claude/projects transcript directory.
check("one project slug for both positions",
      paths.project_slug(os.path.realpath(from_primary))
      == paths.project_slug(os.path.realpath(from_worktree)))
# git worktree list, parsed from either position, sees both trees.
seen = {os.path.realpath(w["path"]) for w in paths.list_worktrees(worktree)}
check("list_worktrees() from the worktree sees primary and worktree",
      primary in seen and worktree in seen)
check("a non-repo path resolves to None, not to a guess",
      paths.primary_repo(os.path.realpath(os.path.dirname(primary))) != worktree)

sys.exit(0 if ok else 1)
PY
if [ $? -eq 0 ]; then
    assert "SC-7 paths.primary_repo() from a worktree resolves to the primary repo" true
else
    assert "SC-7 paths.primary_repo() from a worktree resolves to the primary repo" false
    sed -n '1,30p' "$SC7_OUT"
fi

# ===========================================================================
# The Python unit suite (FR-54 / SC-16).
#
# This single assertion is what makes every tests/activity/test_*.py run in
# CI. No existing flat test in this repo wraps a python3 -m unittest run — the
# only `python3 -m unittest` strings anywhere are docstrings telling a human
# how to run them — so this ESTABLISHES the pattern rather than following it.
#
# -t "$REPO_ROOT" sets the top-level import directory so `tests._harness`
# resolves, which is what puts hooks/ and scripts/activity/ on sys.path. That
# is the same mechanism tests/test_normalized.py and its four siblings already
# use. python3 is already an unconditional dependency of the flat suite
# (tests/stamp-response.test.sh:29,46,53), so this adds no CI requirement.
# ===========================================================================

# --- Test 4: Python unit suite --------------------------------------------
if PYTHONPATH="$REPO_ROOT" python3 -m unittest discover \
        -s "$REPO_ROOT/tests/activity" -t "$REPO_ROOT" -q > "$TMP/py.out" 2>&1; then
    assert "python unit suite (tests/activity)" true
else
    assert "python unit suite (tests/activity)" false
    sed -n '1,60p' "$TMP/py.out"
fi

echo
echo "smith-activity tests: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
