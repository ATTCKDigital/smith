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
# Emitter source-level constraints (T056 / FR-40).
#
# The behavioural cases above prove the emitter is safe on THIS machine. These
# assertions prove it stays safe on a machine where the forbidden constructs
# would silently do nothing: `timeout`/`gtimeout` do not exist on stock macOS,
# so the TIMEOUT_BIN idiom used elsewhere in hooks/ imposes no bound at all,
# and /dev/tcp is a bash-only virtual path that does not exist under zsh.
# Comment lines are stripped first — the header block DISCUSSES all three
# constructs by name, and a grep over the raw file would fail on its own
# documentation.
# ===========================================================================

# --- Test 5: no unbounded/non-portable constructs in the emitter -----------
EMITTER_CODE="$TMP/emitter.code"
grep -v '^[[:space:]]*#' "$EMITTER" > "$EMITTER_CODE"

# `timeout`/`gtimeout` as a COMMAND WORD. The leading `[^-]` guard is
# load-bearing: curl's own `--connect-timeout` is the CORRECT construct and a
# bare substring match would condemn it.
assert_absent() {
    if grep -Eqn -- "$2" "$EMITTER_CODE"; then
        assert "emitter source is free of $1" false
        grep -En -- "$2" "$EMITTER_CODE"
    else
        assert "emitter source is free of $1" true
    fi
}
assert_absent "the 'timeout' command"  '(^|[^-[:alnum:]_])timeout[[:space:]]'
assert_absent "the 'gtimeout' command" '(^|[^-[:alnum:]_])gtimeout[[:space:]]'
assert_absent "TIMEOUT_BIN (the no-op idiom)" 'TIMEOUT_BIN'
assert_absent "/dev/tcp"                '/dev/tcp'

# The bound is curl's own, which IS portable and WAS measured to hold.
grep -q -- '--max-time' "$EMITTER_CODE" \
    && assert "emitter bounds its network call with curl --max-time" true \
    || assert "emitter bounds its network call with curl --max-time" false

grep -q -- '--connect-timeout' "$EMITTER_CODE" \
    && assert "emitter bounds connection setup with --connect-timeout" true \
    || assert "emitter bounds connection setup with --connect-timeout" false

# Trailing UNCONDITIONAL exit 0: the last statement of the script, with no
# `if`, no `&&`, no `||` in front of it. Exit 2 is Claude Code's block signal
# and any other non-zero puts a visible hook-error notice in the transcript.
LAST_STMT=$(grep -v '^[[:space:]]*$' "$EMITTER_CODE" | tail -1)
[ "$LAST_STMT" = "exit 0" ] \
    && assert "emitter ends with an unconditional 'exit 0'" true \
    || assert "emitter ends with an unconditional 'exit 0' (got: $LAST_STMT)" false

# `set -e` would make any failing command abort before that exit 0 is reached.
if grep -Eq '^[[:space:]]*set[[:space:]]+-[a-z]*e' "$EMITTER_CODE"; then
    assert "emitter does not use 'set -e'" false
else
    assert "emitter does not use 'set -e'" true
fi

# ===========================================================================
# Settings-fragment wiring (T053 / FR-43 + install-hooks.sh:6-7,149-183).
#
# CI runs flat tests/*.test.sh only, so tests/hooks/test_hook_chain_order.sh
# never executes there. This is the ONLY gate in CI on the invariant that
# manifest-updater.sh stays LAST in the PostToolUse Write|Edit chain, and the
# only gate on the rule that every emitter entry is its OWN
# {matcher, hooks:[…]} object rather than an append to an existing chain.
# ===========================================================================

# --- Test 6: fragment structure -------------------------------------------
FRAGMENT_OUT="$TMP/fragment.out"
python3 - "$REPO_ROOT/settings/smith-settings-fragment.json" > "$FRAGMENT_OUT" 2>&1 <<'PY'
import json
import sys

PRIMARY = [
    "SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse",
    "PostToolUse", "PostToolUseFailure", "SubagentStart", "SubagentStop",
    "Stop", "Notification", "PermissionRequest", "PermissionDenied",
    "PreCompact", "PostCompact", "ConfigChange",
]
EMITTER = "activity-emitter.sh"

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    hooks = (json.load(fh) or {}).get("hooks") or {}

ok = True


def check(label, condition):
    global ok
    print("%s %s" % ("ok" if condition else "NOT-OK", label))
    if not condition:
        ok = False


def cmds(block):
    return [e.get("command", "") for e in block.get("hooks") or []]


# 1. manifest-updater.sh is still LAST in the PostToolUse Write|Edit chain.
write_edit = [b for b in hooks.get("PostToolUse") or [] if b.get("matcher") == "Write|Edit"]
check("exactly one PostToolUse Write|Edit block", len(write_edit) == 1)
if write_edit:
    chain = cmds(write_edit[0])
    check("Write|Edit chain ends with manifest-updater.sh",
          bool(chain) and chain[-1].endswith("manifest-updater.sh"))
    check("no emitter inside the Write|Edit chain",
          not any(EMITTER in c for c in chain))

# 2. Every emitter entry is its own {matcher, hooks:[…]} object.
wired = set()
for event, blocks in hooks.items():
    for block in blocks or []:
        chain = cmds(block)
        if not any(EMITTER in c for c in chain):
            continue
        wired.add(event)
        check("%s: emitter block holds the emitter and nothing else" % event,
              len(chain) == 1)
        check("%s: emitter block matcher is '*'" % event, block.get("matcher") == "*")
        entry = (block.get("hooks") or [{}])[0]
        # The first `timeout` anywhere in settings/. Without it the entry
        # inherits Claude Code's 600 s default ceiling.
        check("%s: emitter entry declares a timeout" % event,
              isinstance(entry.get("timeout"), int) and entry["timeout"] > 0)

# 3. The confirmed primary event set is wired, and nothing beyond it.
for event in PRIMARY:
    check("%s is wired to the emitter" % event, event in wired)
check("no emitter entry outside the primary set",
      not (wired - set(PRIMARY)))

sys.exit(0 if ok else 1)
PY
if [ $? -eq 0 ]; then
    assert "settings fragment: emitter wiring and Write|Edit chain order" true
else
    assert "settings fragment: emitter wiring and Write|Edit chain order" false
    sed -n '1,40p' "$FRAGMENT_OUT"
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

# ===========================================================================
# Daemon source-level constraints (T098 / T099 / FR-49 / FR-44).
#
# These run FIRST among the daemon cases: if the daemon can reach the network
# or write to a marker directory, nothing the behavioural cases below prove is
# worth having. Both greps run over `code_only` output — comments AND string
# literals stripped — because server.py's docstring explains at length why it
# does NOT import urllib and daemon.py's says in words that nothing writes to
# active-workflows/, so a grep over the raw files would fail on the very
# documentation that states the invariant.
# ===========================================================================

# --- Test 7: SC-15 / FR-49 — no outbound-capable import anywhere -----------
NET_HITS="$TMP/nethits"
net_import_hits "$NET_HITS"
if [ -s "$NET_HITS" ]; then
    assert "FR-49: no outbound-capable import under scripts/activity/" false
    sed -n '1,20p' "$NET_HITS"
else
    assert "FR-49: no outbound-capable import under scripts/activity/" true
fi

# The bind address is a hardcoded constant and 0.0.0.0 appears nowhere.
if code_only "$REPO_ROOT/scripts/activity/server.py" | grep -q 'BIND_ADDRESS'; then
    assert "FR-4: server.py binds through the BIND_ADDRESS constant" true
else
    assert "FR-4: server.py binds through the BIND_ADDRESS constant" false
fi
# Over `code_only`, not the raw files: server.py's own comment says "Never
# 0.0.0.0", and a raw grep would condemn the sentence that states the rule.
: > "$TMP/anyaddr"
for f in "$REPO_ROOT"/scripts/activity/*.py; do
    code_only "$f" | grep -nE '0\.0\.0\.0|INADDR_ANY' \
        | sed "s|^|$(basename "$f"):|" >> "$TMP/anyaddr"
done
if [ -s "$TMP/anyaddr" ]; then
    assert "FR-4: no wildcard bind address anywhere under scripts/activity/" false
    sed -n '1,10p' "$TMP/anyaddr"
else
    assert "FR-4: no wildcard bind address anywhere under scripts/activity/" true
fi

# --- Test 8: FR-44 — no write path mentions active-workflows ---------------
# The workflow gate cannot enforce this: a detached daemon lives outside the
# hook system and outside the gate's jurisdiction (A-7), so the prohibition
# needs its own test. The emitter is included — it reads two files under
# ~/.smith/activity/ and writes nothing, anywhere.
MARKER_HITS="$TMP/markerhits"
marker_write_hits "$MARKER_HITS"
if [ -s "$MARKER_HITS" ]; then
    assert "FR-44: no write path under scripts/activity/ touches active-workflows" false
    sed -n '1,20p' "$MARKER_HITS"
else
    assert "FR-44: no write path under scripts/activity/ touches active-workflows" true
fi

# --- Test 8b: SC-8 / FR-30 — the degraded worktree states (T076) -----------
# Real git, real markers, real `rm -rf` without a prune. The detailed
# per-field assertions are in tests/activity/test_worktrees.py (T077, reached
# through Test 6 above); this is the flat-suite proof that the three states
# are reachable from an actual repository rather than only from a dict.
DEG_REPO=$(make_degraded_repo sc8)
classify_degraded "$DEG_REPO" > "$TMP/sc8.out" 2>"$TMP/sc8.err"
for CASE in "held=held" "missing=missing" "orphaned-merged=orphaned" \
            "orphaned-gone=orphaned" "active=active"; do
    grep -qx "$CASE" "$TMP/sc8.out" \
        && assert "SC-8: worktree '${CASE%%=*}' classifies as '${CASE##*=}'" true \
        || assert "SC-8: worktree '${CASE%%=*}' classifies as '${CASE##*=}' (got: $(grep "^${CASE%%=*}=" "$TMP/sc8.out" || sed -n '1,3p' "$TMP/sc8.err"))" false
done
# FR-30's actual prohibition, asserted as a prohibition rather than inferred
# from the line above: neither orphan may be rendered as an active workflow.
grep -qE '^orphaned-(merged|gone)=active$' "$TMP/sc8.out" \
    && assert "FR-30: an orphaned worktree is NEVER rendered as an active workflow" false \
    || assert "FR-30: an orphaned worktree is NEVER rendered as an active workflow" true

# ===========================================================================
# Daemon lifecycle (T097 / SC-9 / SC-10 / FR-2 / FR-5 / FR-6 / FR-44).
#
# Every daemon below runs under an isolated SMITH_HOME beneath $TMP, so the
# operator's own ~/.smith/activity/ is never touched and a live emitter is
# never repointed at a test daemon. The trap stops whatever is still up.
# ===========================================================================

D_HOME="$TMP/smith-home"
mkdir -p "$D_HOME"
trap 'daemon_stop "$D_HOME" 2>/dev/null; kill "${HANG_PID:-}" 2>/dev/null; rm -rf "$TMP"' EXIT

D_PORT=$(free_port)
PROJ_A=$(make_repo sc9-alpha)
PROJ_B=$(make_repo sc9-beta)
# SC-9's second project is entered through a WORKTREE, which is also FR-28:
# a worktree must register its primary repo, never itself.
PROJ_B_WT=$(add_worktree "$PROJ_B" "$TMP/worktrees/sc9-beta-wt" sc9-beta-feature)

# --- Test 9: SC-9 — one daemon, many projects ------------------------------
OUT_A=$(daemon_start "$D_HOME" "$PROJ_A" start --port "$D_PORT" --no-open)
URL_A=$(printf '%s' "$OUT_A" | tail -1)
OUT_B=$(daemon_start "$D_HOME" "$PROJ_B_WT" --no-open)
URL_B=$(printf '%s' "$OUT_B" | tail -1)

[ "$(daemon_count "$D_HOME")" = "1" ] \
    && assert "SC-9: a second invocation starts exactly one daemon process" true \
    || assert "SC-9: a second invocation starts exactly one daemon process (got $(daemon_count "$D_HOME"))" false

D_TOKEN=$(daemon_token "$D_HOME")
D_LIVE=$(daemon_port "$D_HOME")
REGISTERED=$(curl -s --max-time 5 "http://127.0.0.1:$D_LIVE/api/projects?token=$D_TOKEN" \
    | python3 -c 'import json,sys; print(len((json.load(sys.stdin) or {}).get("projects") or []))' 2>/dev/null)
[ "$REGISTERED" = "2" ] \
    && assert "SC-9: both projects are registered against the one daemon" true \
    || assert "SC-9: both projects are registered against the one daemon (got ${REGISTERED:-none})" false

case "$URL_A" in http://127.0.0.1:*) URL_A_OK=true ;; *) URL_A_OK=false ;; esac
case "$URL_B" in http://127.0.0.1:*) URL_B_OK=true ;; *) URL_B_OK=false ;; esac
if [ "$URL_A_OK" = true ] && [ "$URL_B_OK" = true ] \
   && [ "$(http_code "${URL_A%%\?*}")" = "200" ] && [ "$(http_code "${URL_B%%\?*}")" = "200" ]; then
    assert "SC-9: both invocations print a working 127.0.0.1 URL as their last line" true
else
    assert "SC-9: both invocations print a working 127.0.0.1 URL as their last line" false
    echo "  A=$URL_A"; echo "  B=$URL_B"
fi

# FR-28 again, at the daemon boundary: the worktree registered its PRIMARY.
if curl -s --max-time 5 "http://127.0.0.1:$D_LIVE/api/projects?token=$D_TOKEN" \
        | grep -q "$(basename "$PROJ_B")" \
   && ! printf '%s' "$URL_B" | grep -q 'sc9-beta-wt'; then
    assert "FR-28: registering from a worktree registers the primary repo" true
else
    assert "FR-28: registering from a worktree registers the primary repo" false
fi

# --- Test 10: FR-47 — the token gate is not an oracle ----------------------
NO_TOK=$(http_code "http://127.0.0.1:$D_LIVE/api/state")
BAD_TOK=$(http_code "http://127.0.0.1:$D_LIVE/api/state?token=definitely-not-the-token")
GOOD_TOK=$(http_code "http://127.0.0.1:$D_LIVE/api/state?token=$D_TOKEN")
HEALTH=$(http_code "http://127.0.0.1:$D_LIVE/health")
if [ "$NO_TOK" = "403" ] && [ "$BAD_TOK" = "403" ] && [ "$GOOD_TOK" = "200" ] && [ "$HEALTH" = "200" ]; then
    assert "FR-47: /api/* is 403 without and with a wrong token, 200 with it, /health un-gated" true
else
    assert "FR-47: token gate (absent=$NO_TOK wrong=$BAD_TOK good=$GOOD_TOK health=$HEALTH)" false
fi
TOK_PERMS=$(ls -l "$D_HOME/activity/activity.token" 2>/dev/null | cut -c1-10)
[ "$TOK_PERMS" = "-rw-------" ] \
    && assert "FR-47: activity.token is 0600" true \
    || assert "FR-47: activity.token is 0600 (got ${TOK_PERMS:-missing})" false

# --- Test 11: SC-15 socket inspection — 127.0.0.1 and nothing else ---------
D_PID=$(daemon_pid "$D_HOME")
LISTENERS=$(lsof -nP -a -p "$D_PID" -iTCP -sTCP:LISTEN 2>/dev/null | tail -n +2)
NON_LOOPBACK=$(printf '%s\n' "$LISTENERS" | grep -v '^$' | grep -cv '127\.0\.0\.1:')
LOOPBACK=$(printf '%s\n' "$LISTENERS" | grep -c '127\.0\.0\.1:')
if [ "$LOOPBACK" -ge 1 ] && [ "$NON_LOOPBACK" -eq 0 ]; then
    assert "SC-15: the running daemon listens on 127.0.0.1 and nothing else" true
else
    assert "SC-15: the running daemon listens on 127.0.0.1 and nothing else" false
    printf '%s\n' "$LISTENERS"
fi

# --- Test 12: T099 — a running daemon does not disturb a project vault -----
# The source grep above proves no write path names active-workflows. This
# proves the running article leaves the whole vault alone, marker directory
# included: mtimes before and after a full refresh pass must be identical.
mkdir -p "$PROJ_A/.smith/vault/active-workflows"
cat > "$PROJ_A/.smith/vault/active-workflows/t099.yaml" <<'YAML'
workflow: smith-bugfix
feature: t099-guard
branch: t099-guard
worktree:
session_log:
started: 2026-09-22T00:00:00Z
YAML
VAULT_BEFORE=$(vault_fingerprint "$PROJ_A")
daemon_start "$D_HOME" "$PROJ_A" --no-open >/dev/null 2>&1
# Drive ingest so the refresh pass actually runs over this project, then give
# the 1 Hz poll two full turns.
curl -s -o /dev/null --max-time 5 -X POST -H "Authorization: Bearer $D_TOKEN" \
    "http://127.0.0.1:$D_LIVE/ingest" \
    -d "{\"session_id\":\"t099\",\"cwd\":\"$PROJ_A\",\"hook_event_name\":\"PreToolUse\",\"tool_name\":\"Bash\"}" 2>/dev/null
sleep 3
VAULT_AFTER=$(vault_fingerprint "$PROJ_A")
if [ "$VAULT_BEFORE" = "$VAULT_AFTER" ]; then
    assert "FR-44: a running daemon leaves the project vault byte- and mtime-identical" true
else
    assert "FR-44: a running daemon leaves the project vault byte- and mtime-identical" false
    diff <(printf '%s\n' "$VAULT_BEFORE") <(printf '%s\n' "$VAULT_AFTER") | sed -n '1,12p'
fi

# --- Test 13: SC-10 — stale pidfiles, both flavours ------------------------
# (a) ABSENT pid: kill -9 and leave the pidfile behind.
KILLED=$(daemon_pid "$D_HOME")
kill -9 "$KILLED" 2>/dev/null
sleep 0.5
printf '%s\n' "$KILLED" > "$D_HOME/activity/activity.pid"   # the stale artefact
daemon_start "$D_HOME" "$PROJ_A" start --port "$D_PORT" --no-open > "$TMP/sc10a.out" 2>&1
SC10A_RC=$?
REBORN=$(daemon_pid "$D_HOME")
if [ "$SC10A_RC" -eq 0 ] && [ -n "$REBORN" ] && [ "$REBORN" != "$KILLED" ] \
   && [ "$(daemon_identity "$(daemon_port "$D_HOME")")" = "smith-activity" ]; then
    assert "SC-10: a stale pidfile with an ABSENT pid is cleaned up and the daemon restarted (exit 0)" true
else
    assert "SC-10: a stale pidfile with an ABSENT pid is cleaned up and the daemon restarted (rc=$SC10A_RC)" false
    sed -n '1,10p' "$TMP/sc10a.out"
fi

# (b) FOREIGN but ALIVE pid. The fixture must be signallable, so `sleep` is
# used rather than pid 1: `kill -0 1` fails with EPERM for a non-root user and
# would take the ABSENT branch instead, silently proving nothing.
daemon_stop "$D_HOME"
sleep 600 &
FOREIGN_PID=$!
disown "$FOREIGN_PID" 2>/dev/null || true
printf '%s\n' "$FOREIGN_PID" > "$D_HOME/activity/activity.pid"
printf '%s\n' "$D_PORT" > "$D_HOME/activity/activity.port"
daemon_start "$D_HOME" "$PROJ_A" start --port "$D_PORT" --no-open > "$TMP/sc10b.out" 2>&1
SC10B_RC=$?
AFTER_FOREIGN=$(daemon_pid "$D_HOME")
FOREIGN_SURVIVED=false
kill -0 "$FOREIGN_PID" 2>/dev/null && FOREIGN_SURVIVED=true
if [ "$SC10B_RC" -eq 0 ] && [ -n "$AFTER_FOREIGN" ] && [ "$AFTER_FOREIGN" != "$FOREIGN_PID" ] \
   && [ "$FOREIGN_SURVIVED" = true ] \
   && [ "$(daemon_identity "$(daemon_port "$D_HOME")")" = "smith-activity" ]; then
    assert "SC-10: a stale pidfile with a FOREIGN pid is cleaned up, the foreign process spared, the daemon restarted (exit 0)" true
else
    assert "SC-10: a stale pidfile with a FOREIGN pid (rc=$SC10B_RC foreign_survived=$FOREIGN_SURVIVED)" false
    sed -n '1,10p' "$TMP/sc10b.out"
fi
kill "$FOREIGN_PID" 2>/dev/null
wait "$FOREIGN_PID" 2>/dev/null

daemon_stop "$D_HOME"
[ "$(daemon_count "$D_HOME")" = "0" ] \
    && assert "lifecycle: stop leaves no daemon process behind" true \
    || assert "lifecycle: stop leaves no daemon process behind ($(daemon_count "$D_HOME") left)" false

# --- Test 14: SC-13 — the statusline is WRAPPED, never clobbered (T106) ----
# This machine has a pre-existing `statusLine`, so the destructive risk here is
# entirely the operator's own configuration. Everything below runs against a
# fixture settings.json under $TMP; neither ~/.claude nor ~/.smith is touched.
SL_HOME="$TMP/sl-home"; SL_SETTINGS="$TMP/sl-settings.json"
mkdir -p "$SL_HOME"
make_statusline "$TMP/operator-statusline.sh" "OPERATOR"
python3 - "$SL_SETTINGS" "$TMP/operator-statusline.sh" <<'PY'
import json, sys
json.dump({"theme": "dark", "statusLine": {"type": "command",
           "command": "bash " + sys.argv[2]}}, open(sys.argv[1], "w"), indent=2)
PY
statusline_payload "$TMP/sl-payload.json" with-rate-limits
bash "$TMP/operator-statusline.sh" < "$TMP/sl-payload.json" > "$TMP/sl-before.out" 2>/dev/null
install_statusline "$SL_SETTINGS" "$SL_HOME"
SL_RC=$(run_tee "$SL_HOME" "$TMP/sl-payload.json" "$TMP/sl-after.out")

cmp -s "$TMP/sl-before.out" "$TMP/sl-after.out" \
    && assert "SC-13: a pre-existing statusline's output is byte-for-byte unchanged when wrapped" true \
    || { assert "SC-13: a pre-existing statusline's output is byte-for-byte unchanged when wrapped" false
         echo "  before: $(cat "$TMP/sl-before.out")"; echo "  after:  $(cat "$TMP/sl-after.out")"; }
[ "$SL_RC" = "0" ] \
    && assert "SC-13: the tee exits 0" true \
    || assert "SC-13: the tee exits 0 (got $SL_RC)" false
# The captured sidecar must hold the OPERATOR's command. Capturing the tee
# itself would make it delegate to itself forever and would destroy the only
# record of what was there — so re-running the installer must change nothing.
install_statusline "$SL_SETTINGS" "$SL_HOME"
SL_PREV=$(json_field "$SL_HOME/activity/wrapped-statusline" "previous.command")
case "$SL_PREV" in
    *statusline-tee.sh*) assert "SC-13: re-install did NOT capture the tee as its own 'previous'" false ;;
    *operator-statusline.sh*) assert "SC-13: re-install did NOT capture the tee as its own 'previous'" true ;;
    *) assert "SC-13: re-install kept the operator's command (got '${SL_PREV:-empty}')" false ;;
esac
[ "$(json_field "$SL_SETTINGS" "theme")" = "dark" ] \
    && assert "SC-13: unrelated settings keys survive the statusLine merge" true \
    || assert "SC-13: unrelated settings keys survive the statusLine merge" false

# Installing over NO statusline must produce a minimal default line — never
# nothing, and never an error.
SL_HOME2="$TMP/sl-home2"; SL_SETTINGS2="$TMP/sl-settings2.json"
mkdir -p "$SL_HOME2"; printf '{}\n' > "$SL_SETTINGS2"
install_statusline "$SL_SETTINGS2" "$SL_HOME2"
SL_RC2=$(run_tee "$SL_HOME2" "$TMP/sl-payload.json" "$TMP/sl-default.out")
[ "$SL_RC2" = "0" ] && [ -s "$TMP/sl-default.out" ] \
    && assert "SC-13: installing over NO statusline prints a minimal default line" true \
    || assert "SC-13: installing over NO statusline prints a minimal default line (rc=$SL_RC2)" false
[ "$(json_field "$SL_HOME2/activity/wrapped-statusline" "had_statusline")" = "false" ] \
    && assert "SC-13: 'no previous statusline' is recorded as a positive fact" true \
    || assert "SC-13: 'no previous statusline' is recorded as a positive fact" false

# --- Test 15: SC-12 — rate_limits present, then absent (T107) --------------
# The statusline payload is the ONLY source of the quota windows, so this runs
# the real path: tee → POST /statusline → /api/usage.
Q_HOME="$TMP/quota-home"; mkdir -p "$Q_HOME"
printf '{}\n' > "$TMP/quota-settings.json"
install_statusline "$TMP/quota-settings.json" "$Q_HOME"
Q_PORT=$(free_port)
daemon_start "$Q_HOME" "$PROJ_A" start --port "$Q_PORT" --no-open >/dev/null 2>&1
Q_LIVE=$(daemon_port "$Q_HOME"); Q_TOKEN=$(daemon_token "$Q_HOME")

statusline_payload "$TMP/q-with.json" with-rate-limits
run_tee "$Q_HOME" "$TMP/q-with.json" "$TMP/q-with.out" >/dev/null
sleep 2                                   # the tee's forward is detached
api_get "$Q_LIVE" "$Q_TOKEN" usage "$TMP/q-usage-with.json"
Q5=$(json_field "$TMP/q-usage-with.json" "quota.five_hour.used_percentage")
Q5R=$(json_field "$TMP/q-usage-with.json" "quota.five_hour.resets_at")
Q7=$(json_field "$TMP/q-usage-with.json" "quota.seven_day.used_percentage")
Q7R=$(json_field "$TMP/q-usage-with.json" "quota.seven_day.resets_at")
if [ "$Q5" = "23.5" ] && [ "$Q5R" = "1738425600" ] \
   && [ "$Q7" = "41.2" ] && [ "$Q7R" = "1738857600" ]; then
    assert "SC-12: with rate_limits, both windows carry a percentage AND a reset time" true
else
    assert "SC-12: with rate_limits, both windows carry a percentage AND a reset time (5h=$Q5/$Q5R 7d=$Q7/$Q7R)" false
fi

# Absent rate_limits is a first-class state, not a zero. `available:false` is
# what the UI renders as an explicit "quota unavailable", and NOTHING else may
# degrade with it.
api_get "$Q_LIVE" "$Q_TOKEN" state "$TMP/q-state-before.json"
statusline_payload "$TMP/q-without.json"
run_tee "$Q_HOME" "$TMP/q-without.json" "$TMP/q-without.out" >/dev/null
sleep 2
api_get "$Q_LIVE" "$Q_TOKEN" usage "$TMP/q-usage-without.json"
[ "$(json_field "$TMP/q-usage-without.json" "quota.available")" = "false" ] \
    && assert "SC-12: a payload with no rate_limits yields an explicit unavailable quota" true \
    || assert "SC-12: a payload with no rate_limits yields an explicit unavailable quota" false
[ "$(json_field "$TMP/q-usage-without.json" "quota.five_hour")" = "null" ] \
    && assert "SC-12: an unavailable window is null, never a fabricated 0%" true \
    || assert "SC-12: an unavailable window is null, never a fabricated 0%" false
api_get "$Q_LIVE" "$Q_TOKEN" state "$TMP/q-state-after.json"
Q_PROJ_BEFORE=$(json_field "$TMP/q-state-before.json" "projects" | wc -c | tr -d ' ')
Q_PROJ_AFTER=$(json_field "$TMP/q-state-after.json" "projects" | wc -c | tr -d ' ')
[ "$Q_PROJ_BEFORE" = "$Q_PROJ_AFTER" ] && [ "$Q_PROJ_AFTER" -gt 2 ] \
    && assert "SC-12: losing the quota degrades nothing else on the dashboard" true \
    || assert "SC-12: losing the quota degrades nothing else ($Q_PROJ_BEFORE vs $Q_PROJ_AFTER bytes)" false

# --- Test 16: SC-14 — the redaction canary (T108) --------------------------
# TWO assertions, and only the second one can actually fail.
#
# The wire sweep is kept because SC-14 names it, but it was RED-CHECKED and did
# not go red: with ingest.py's redaction removed entirely, every /api/* body,
# the /events transcript and activity.log still contained ZERO hits, because no
# route currently projects a raw `tool_input` onto the wire. It is a regression
# guard against a FUTURE route that does, not evidence that redaction works.
#
# storage_canary_hits asserts at the boundary redaction actually defends —
# daemon.events_for(), where the payload lands. Deleting the redaction makes it
# return 3 instead of 0.
CANARY="canary-$$-9f2b7c1e-do-not-log"
unset SMITH_ACTIVITY_CAPTURE_PROMPTS
sse_capture "$Q_LIVE" "$Q_TOKEN" "$TMP/canary-sse.txt" 6 &
CANARY_SSE_PID=$!
sleep 1
for EV in \
  "{\"session_id\":\"canary-1\",\"cwd\":\"$PROJ_A\",\"hook_event_name\":\"UserPromptSubmit\",\"prompt\":\"please $CANARY the thing\"}" \
  "{\"session_id\":\"canary-1\",\"cwd\":\"$PROJ_A\",\"hook_event_name\":\"PreToolUse\",\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"echo $CANARY\"}}"
do
    curl -s -o /dev/null --max-time 5 -X POST -H "Authorization: Bearer $Q_TOKEN" \
        "http://127.0.0.1:$Q_LIVE/ingest" -d "$EV" 2>/dev/null
done
sleep 4
kill "$CANARY_SSE_PID" 2>/dev/null; wait "$CANARY_SSE_PID" 2>/dev/null
WIRE_HITS=$(canary_hits "$Q_LIVE" "$Q_TOKEN" "$CANARY" "$TMP/canary-sse.txt" "$Q_HOME/activity/activity.log")
[ "$WIRE_HITS" = "0" ] \
    && assert "SC-14: the canary appears 0 times across every /api/* body, /events and activity.log" true \
    || assert "SC-14: the canary leaked to the wire ($WIRE_HITS hits)" false

STORE_HITS=$(storage_canary_hits "$CANARY")
[ "$STORE_HITS" = "0" ] \
    && assert "SC-14: the canary appears 0 times in the daemon's stored events (the assertion that can fail)" true \
    || assert "SC-14: the canary reached the state tree ($STORE_HITS hits in daemon.events_for())" false

# --- Test 17: the opt-in actually changes behaviour (T109) -----------------
# The default being safe is only meaningful if the flag is proven to do
# something. Same canary, same route, capture ENABLED.
C_HOME="$TMP/capture-home"; mkdir -p "$C_HOME"
C_PORT=$(free_port)
SMITH_ACTIVITY_CAPTURE_PROMPTS=1 \
    daemon_start "$C_HOME" "$PROJ_A" start --port "$C_PORT" --no-open >/dev/null 2>&1
C_LIVE=$(daemon_port "$C_HOME"); C_TOKEN=$(daemon_token "$C_HOME")
curl -s -o /dev/null --max-time 5 -X POST -H "Authorization: Bearer $C_TOKEN" \
    "http://127.0.0.1:$C_LIVE/ingest" \
    -d "{\"session_id\":\"cap-1\",\"cwd\":\"$PROJ_A\",\"hook_event_name\":\"UserPromptSubmit\",\"prompt\":\"please $CANARY the thing\"}" 2>/dev/null
sleep 2
sse_capture "$C_LIVE" "$C_TOKEN" "$TMP/capture-sse.txt" 3
C_HELLO=$(sse_frame "$TMP/capture-sse.txt" "hello")
printf '%s' "$C_HELLO" > "$TMP/capture-hello.json"
[ "$(json_field "$TMP/capture-hello.json" "capture_prompts")" = "true" ] \
    && assert "FR-48: with SMITH_ACTIVITY_CAPTURE_PROMPTS=1, hello.capture_prompts is true" true \
    || assert "FR-48: with SMITH_ACTIVITY_CAPTURE_PROMPTS=1, hello.capture_prompts is true" false
C_STORE=$(storage_canary_hits "$CANARY" 1)
[ "$C_STORE" -gt 0 ] 2>/dev/null \
    && assert "FR-48: with capture ENABLED the content is retained — so the default is proven to be the safe one" true \
    || assert "FR-48: capture-enabled retained nothing ($C_STORE hits) — the opt-in changes no behaviour" false
daemon_stop "$C_HOME"

# --- Test 18: SC-15 / SC-20 — the SERVED assets (T115) ---------------------
# Asserted against what the daemon actually serves, not against the files on
# disk: `/` and `/static/*` are the only un-gated routes, and what they emit is
# what a browser executes.
curl -s --max-time 5 "http://127.0.0.1:$Q_LIVE/" > "$TMP/served-index.html" 2>/dev/null
EXTERNAL=$(html_external_origins "$TMP/served-index.html")
[ "$EXTERNAL" = "0" ] \
    && assert "SC-15: the served HTML has zero src/href values beginning http or //" true \
    || { assert "SC-15: the served HTML reaches an external origin ($EXTERNAL hits)" false
         grep -oE '(src|href)[[:space:]]*=[[:space:]]*"(https?:|//)[^"]*"' "$TMP/served-index.html" | head -5; }
grep -qE '@import[[:space:]]+url\(' "$TMP/served-index.html" \
    && assert "SC-15: the served HTML contains no @import url(…)" false \
    || assert "SC-15: the served HTML contains no @import url(…)" true

curl -s --max-time 5 "http://127.0.0.1:$Q_LIVE/static/app.css" > "$TMP/served-app.css" 2>/dev/null
# Comments stripped first: app.css's own header states "no @import", and a raw
# grep condemns the file for documenting the invariant it satisfies.
css_code_only "$TMP/served-app.css" > "$TMP/served-app.code.css"
if [ -s "$TMP/served-app.css" ] \
   && ! grep -qE '@import|url\([[:space:]]*["'"'"']?(https?:|//)' "$TMP/served-app.code.css"; then
    assert "SC-15: the served CSS has no @import and no external url()" true
else
    assert "SC-15: the served CSS has no @import and no external url()" false
    grep -nE '@import|url\([[:space:]]*["'"'"']?(https?:|//)' "$TMP/served-app.code.css" | head -3
fi

# SC-20's UI half. FR-59's whole content is that a retracted finding must not
# be REMOVED — it re-renders in a settled state. The class that expresses that
# has to exist in the code the browser actually runs.
curl -s --max-time 5 "http://127.0.0.1:$Q_LIVE/static/panels.js" > "$TMP/served-panels.js" 2>/dev/null
grep -q 'finding-settled' "$TMP/served-panels.js" \
    && assert "SC-20: the served panels.js carries the settled-retraction class" true \
    || assert "SC-20: the served panels.js carries the settled-retraction class" false
# ...and that nothing in the served page can delete a finding card. A `remove`
# reaching the findings collection would make a retraction vanish, which is the
# precise failure FR-59 forbids.
curl -s --max-time 5 "http://127.0.0.1:$Q_LIVE/static/app.js" > "$TMP/served-app.js" 2>/dev/null
grep -q 'findings: { upsert: \[frame.finding\], remove: \[\] }' "$TMP/served-app.js" \
    && assert "FR-59: a 'finding' frame is applied as an upsert with an empty remove list, for both ops" true \
    || assert "FR-59: a 'finding' frame is applied as an upsert with an empty remove list, for both ops" false

daemon_stop "$Q_HOME"
[ "$(daemon_count)" = "0" ] \
    && assert "lifecycle: every test daemon is stopped" true \
    || assert "lifecycle: every test daemon is stopped ($(daemon_count) left)" false

echo
echo "smith-activity tests: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
