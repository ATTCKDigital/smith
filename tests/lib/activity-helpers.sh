#!/usr/bin/env bash
# activity-helpers.sh — sourced helpers for tests/smith-activity.test.sh.
#
# NOT a test file. CI globs `tests/*.test.sh`
# (.github/workflows/test-install.yml:58) and nothing else, so this filename is
# deliberately outside that glob: a sourced helper cannot become a
# CI-invisible test the way a `tests/lib/*.test.sh` would.
#
# Extracted because tests/smith-activity.test.sh stood at 364 lines with 4 of
# ~10 planned test tasks done. T053, T056, T076, T097 and the SC-12/13/14/15
# cases all append to that file, which would have carried it past the repo's
# 500-line decompose threshold. Splitting the helpers out now leaves the test
# file as a readable list of what is asserted, and puts the machinery that
# never changes somewhere it does not have to be re-read.
#
# Sourcing contract — the caller must already have set:
#   SCRIPT_DIR, REPO_ROOT   (paths)
#   TMP                     (mktemp -d, with its EXIT trap installed)
#   assert()                (the PASS/FAIL counter helper)
# Nothing here defines those; nothing here runs a test. Sourcing it only
# defines functions and writes two payload fixtures under $TMP.

# ===========================================================================
# Emitter safety (SC-4 / FR-40) — the cheapest and most important cases in the
# suite. They need no daemon, no fixtures and no git.
# ===========================================================================

EMITTER="$REPO_ROOT/hooks/activity-emitter.sh"

# Foreground wall-clock ceiling for one emitter invocation, in seconds. The
# measured figures are ~6 ms (daemon down), ~10 ms (port closed) and ~30 ms
# (hanging listener, because the curl is detached). 2.0 s is two orders of
# magnitude of slack: this assertion exists to catch "unbounded", not to
# benchmark. It is measured with python3 because neither `timeout` nor
# `gtimeout` exists on a stock macOS.
EMITTER_BOUND_S=2.0

now_s() { python3 -c 'import time; print(repr(time.time()))'; }

# run_emitter <shell> <payload-file> <smith-home> <stdout-file> <stderr-file>
# Echoes "<rc> <elapsed-seconds>". The emitter's stdout is captured to a file
# rather than a variable so a trailing newline is not silently eaten — SC-4's
# claim is ZERO bytes, not "nothing interesting".
run_emitter() {
    local shell_bin="$1" payload="$2" home="$3" outf="$4" errf="$5"
    local t0 t1 rc
    t0=$(now_s)
    SMITH_HOME="$home" "$shell_bin" "$EMITTER" < "$payload" > "$outf" 2> "$errf"
    rc=$?
    t1=$(now_s)
    printf '%s %s' "$rc" "$(python3 -c "print('%.3f' % ($t1 - $t0))")"
}

bytes_of() { wc -c < "$1" | tr -d ' '; }

within_bound() {
    python3 -c "import sys; sys.exit(0 if float('$1') <= float('$EMITTER_BOUND_S') else 1)"
}

# Realistic payloads, shaped per contracts/hook-envelope.md §1. PreToolUse is
# the one that matters most: there a non-zero exit BLOCKS the operator's tool
# call.
cat > "$TMP/pretooluse.json" <<'JSON'
{"session_id":"046b6482-59f3-46fb-a5c5-d3ec7f3eb6de","prompt_id":"33a1f0e2-1b27-4f3a-9d61-5c7b2e8a4411","transcript_path":"/Users/x/.claude/projects/-tmp-smith/046b6482.jsonl","cwd":"/private/tmp/smith-activity-dashboard","permission_mode":"default","hook_event_name":"PreToolUse","tool_name":"Task","tool_input":{"description":"Implement phase 2","subagent_type":"general-purpose","prompt":"do the thing"}}
JSON
cat > "$TMP/posttooluse.json" <<'JSON'
{"session_id":"046b6482-59f3-46fb-a5c5-d3ec7f3eb6de","prompt_id":"33a1f0e2-1b27-4f3a-9d61-5c7b2e8a4411","transcript_path":"/Users/x/.claude/projects/-tmp-smith/046b6482.jsonl","cwd":"/private/tmp/smith-activity-dashboard","permission_mode":"default","hook_event_name":"PostToolUse","tool_name":"Bash","tool_input":{"command":"ls -la"},"tool_response":{"stdout":"total 0\n","stderr":"","interrupted":false}}
JSON

# emitter_cases <shell-bin> <shell-label> — every emitter assertion, run under
# one shell. Called once per shell so the no-/dev/tcp and no-`timeout`
# constraints are enforced by the suite rather than by review (T007).
emitter_cases() {
    local shell_bin="$1" label="$2"
    local home_down="$TMP/home-down-$label"
    local home_closed="$TMP/home-closed-$label"
    local res rc elapsed port

    # --- Test: SC-4 daemon down — no port/token files at all -------------
    # This is the state of every machine until /smith-activity is first run,
    # so it is the path the operator lives in most of the time.
    rm -rf "$home_down"
    for ev in pretooluse posttooluse; do
        res=$(run_emitter "$shell_bin" "$TMP/$ev.json" "$home_down" \
                          "$TMP/out.$ev.$label" "$TMP/err.$ev.$label")
        rc=${res% *}; elapsed=${res#* }
        [ "$rc" = "0" ] \
            && assert "[$label] $ev daemon-down: exit 0" true \
            || assert "[$label] $ev daemon-down: exit 0 (got $rc)" false
        [ "$(bytes_of "$TMP/out.$ev.$label")" = "0" ] \
            && assert "[$label] $ev daemon-down: zero bytes on stdout" true \
            || assert "[$label] $ev daemon-down: zero bytes on stdout" false
        within_bound "$elapsed" \
            && assert "[$label] $ev daemon-down: returned in ${elapsed}s" true \
            || assert "[$label] $ev daemon-down: returned in ${elapsed}s (> ${EMITTER_BOUND_S}s)" false
    done

    # --- Test: port/token present but the port is CLOSED -----------------
    # A daemon killed without cleaning up its port file. The emitter must not
    # care that the connection is refused.
    rm -rf "$home_closed"; mkdir -p "$home_closed/activity"
    port=$(python3 -c 'import socket
s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); print(p)')
    printf '%s\n' "$port" > "$home_closed/activity/activity.port"
    printf 'test-token-not-a-real-secret\n' > "$home_closed/activity/activity.token"
    res=$(run_emitter "$shell_bin" "$TMP/pretooluse.json" "$home_closed" \
                      "$TMP/out.closed.$label" "$TMP/err.closed.$label")
    rc=${res% *}; elapsed=${res#* }
    [ "$rc" = "0" ] && [ "$(bytes_of "$TMP/out.closed.$label")" = "0" ] \
        && assert "[$label] closed port: exit 0, zero stdout" true \
        || assert "[$label] closed port: exit 0, zero stdout (rc=$rc)" false
    within_bound "$elapsed" \
        && assert "[$label] closed port: returned in ${elapsed}s" true \
        || assert "[$label] closed port: returned in ${elapsed}s (> ${EMITTER_BOUND_S}s)" false

    # --- Test: malformed port file ---------------------------------------
    # A half-written port file must never become part of a URL.
    printf 'not-a-port\n' > "$home_closed/activity/activity.port"
    res=$(run_emitter "$shell_bin" "$TMP/pretooluse.json" "$home_closed" \
                      "$TMP/out.badport.$label" "$TMP/err.badport.$label")
    rc=${res% *}
    [ "$rc" = "0" ] && [ "$(bytes_of "$TMP/out.badport.$label")" = "0" ] \
        && assert "[$label] malformed port file: exit 0, zero stdout" true \
        || assert "[$label] malformed port file: exit 0, zero stdout (rc=$rc)" false

    # --- Test: empty stdin -------------------------------------------------
    res=$(run_emitter "$shell_bin" /dev/null "$home_closed" \
                      "$TMP/out.empty.$label" "$TMP/err.empty.$label")
    rc=${res% *}
    [ "$rc" = "0" ] && [ "$(bytes_of "$TMP/out.empty.$label")" = "0" ] \
        && assert "[$label] empty stdin: exit 0, zero stdout" true \
        || assert "[$label] empty stdin: exit 0, zero stdout (rc=$rc)" false

    # --- Test: a listener that ACCEPTS and never responds (FR-40) --------
    # The case a plain connect-refused check misses entirely: the TCP
    # handshake completes and the peer then says nothing. Without a bound the
    # emitter would sit here until the operator gave up.
    printf '%s\n' "$(cat "$TMP/hangport")" > "$home_closed/activity/activity.port"
    for ev in pretooluse posttooluse; do
        res=$(run_emitter "$shell_bin" "$TMP/$ev.json" "$home_closed" \
                          "$TMP/out.hang.$ev.$label" "$TMP/err.hang.$ev.$label")
        rc=${res% *}; elapsed=${res#* }
        [ "$rc" = "0" ] \
            && assert "[$label] $ev hanging listener: exit 0" true \
            || assert "[$label] $ev hanging listener: exit 0 (got $rc)" false
        [ "$(bytes_of "$TMP/out.hang.$ev.$label")" = "0" ] \
            && assert "[$label] $ev hanging listener: zero bytes on stdout" true \
            || assert "[$label] $ev hanging listener: zero bytes on stdout" false
        within_bound "$elapsed" \
            && assert "[$label] $ev hanging listener: returned in ${elapsed}s" true \
            || assert "[$label] $ev hanging listener: returned in ${elapsed}s (> ${EMITTER_BOUND_S}s)" false
    done
}


# make_repo <name> — create a throwaway git repo under $TMP and print its path.
# Shape borrowed from tests/get-base-branch.test.sh:24-40; extended below with
# `git worktree add`, which no existing test in this repo uses.
make_repo() {
    local name="$1"
    local dir="$TMP/repos/$name"
    mkdir -p "$dir"
    (
        cd "$dir" || exit 1
        git init -q
        git config user.email test@example.com
        git config user.name test
        git config commit.gpgsign false
        mkdir -p .smith/vault/active-workflows
        printf 'seed\n' > README.md
        git add -A
        git commit -qm "seed"
    ) >/dev/null 2>&1
    printf '%s' "$dir"
}

# add_worktree <repo-dir> <worktree-dir> <branch> — attach a linked worktree,
# deliberately placed OUTSIDE the primary tree, which is where /smith-new puts
# its worktrees (/tmp/smith-<slug>) and the case SC-7 is about.
add_worktree() {
    local repo="$1" wt="$2" branch="$3"
    (cd "$repo" && git worktree add -q -b "$branch" "$wt") >/dev/null 2>&1
    printf '%s' "$wt"
}

# ===========================================================================
# Daemon lifecycle harness (T097 / SC-9 / SC-10).
#
# Every daemon a test starts runs under an ISOLATED SMITH_HOME beneath $TMP,
# so a test run never touches the operator's own ~/.smith/activity/ — and in
# particular never repoints a live hooks.log-wired emitter at a test daemon.
#
# Bounds are python3 socket timeouts and curl --max-time. Neither `timeout`
# nor `gtimeout` exists on a stock macOS, so the TIMEOUT_BIN idiom would
# impose no bound at all and is not used here.
# ===========================================================================

ACTIVITY_CLI="$REPO_ROOT/scripts/activity/smith-activity.sh"

# free_port — a port nothing is listening on right now.
free_port() {
    python3 - <<'PY'
import socket

sock = socket.socket()
sock.bind(("127.0.0.1", 0))
print(sock.getsockname()[1])
sock.close()
PY
}

daemon_token() { tr -d '[:space:]' < "$1/activity/activity.token" 2>/dev/null; }
daemon_port()  { tr -d '[:space:]' < "$1/activity/activity.port"  2>/dev/null; }
daemon_pid()   { tr -d '[:space:]' < "$1/activity/activity.pid"   2>/dev/null; }

# daemon_identity PORT — the /health `service` string, or "". The FR-5 probe.
daemon_identity() {
    curl -s --max-time 3 --connect-timeout 1 "http://127.0.0.1:$1/health" 2>/dev/null \
        | python3 -c '
import json
import sys

try:
    print((json.load(sys.stdin) or {}).get("service", ""))
except Exception:
    print("")
' 2>/dev/null
}

# --- the started-daemon registry -------------------------------------------
#
# `daemon_count` used to be `pgrep -f 'activity/server.py' | wc -l` — every
# daemon on the machine "whatever their home". That made three lifecycle
# assertions fail whenever the operator had a legitimate /smith-activity
# daemon of their own running: 81/81 with it stopped, 78/81 with it up. A
# suite that fails because the feature it tests is IN USE teaches people to
# skim past its failures, which is worse than the coverage it bought.
#
# The count is now scoped to the daemons THIS SUITE started. Scoping by
# SMITH_HOME is what is wanted semantically, but it cannot be read back off a
# running process: `ps -E` does not surface the environment of another
# process on a stock macOS (verified), and the pidfile under
# $SMITH_HOME/activity/ is DELETED by `stop` — which is precisely the moment
# "did stop leave anything behind?" needs to look.
#
# So each `daemon_start` records the port the daemon actually bound, keyed by
# home, and the count matches running processes against those ports. The
# registry outlives the pidfile, so a leftover process is still caught after
# a stop, and a foreign daemon on a port this suite never asked for is not.
DAEMON_PORT_REGISTRY="$TMP/.daemon-ports"

_home_slug() { printf '%s' "$1" | tr -c 'A-Za-z0-9._-' '-'; }

# _remember_daemon_port <smith-home> — append the LIVE port (not the requested
# one: the CLI may bind elsewhere) to this home's registry, deduplicated.
_remember_daemon_port() {
    local home="$1" port reg
    port=$(daemon_port "$home")
    [ -n "$port" ] || return 0
    mkdir -p "$DAEMON_PORT_REGISTRY"
    reg="$DAEMON_PORT_REGISTRY/$(_home_slug "$home")"
    grep -qxF "$port" "$reg" 2>/dev/null || printf '%s\n' "$port" >> "$reg"
}

# daemon_start <smith-home> <cwd> [args…] — run the CLI from <cwd>. Echoes the
# whole stdout of the CLI; its LAST line is the dashboard URL.
daemon_start() {
    local home="$1" where="$2"; shift 2
    local out
    out=$( cd "$where" && SMITH_HOME="$home" "$ACTIVITY_CLI" "$@" 2>&1 )
    _remember_daemon_port "$home"
    printf '%s\n' "$out"
}

daemon_stop() {
    SMITH_HOME="$1" "$ACTIVITY_CLI" stop >/dev/null 2>&1
}

# _daemon_running_on_port <port> — 0 when a server.py is serving exactly that
# port. `smith-activity.sh` always invokes `python3 <server.py> --port <port>`
# with the port LAST, so an exact suffix match cannot confuse 878 with 8787.
_daemon_running_on_port() {
    local port="$1" pid cmd
    for pid in $(pgrep -f 'activity/server\.py' 2>/dev/null); do
        cmd=$(ps -ww -o command= -p "$pid" 2>/dev/null)
        case "$cmd" in
            *"activity/server.py --port $port") return 0 ;;
        esac
    done
    return 1
}

# daemon_count [smith-home] — how many of THIS SUITE's daemons are running.
# With a home, only that home's; with none, every home the suite has started,
# which is what the end-of-run "every test daemon is stopped" sweep means.
# A daemon belonging to the operator is never counted (see the note above).
daemon_count() {
    local reg n=0 port
    set -- ${1:+"$DAEMON_PORT_REGISTRY/$(_home_slug "$1")"}
    if [ "$#" -eq 0 ]; then
        set -- "$DAEMON_PORT_REGISTRY"/*
    fi
    for reg in "$@"; do
        [ -f "$reg" ] || continue
        while IFS= read -r port; do
            [ -n "$port" ] || continue
            _daemon_running_on_port "$port" && n=$((n+1))
        done < "$reg"
    done
    printf '%s' "$n"
}

# http_code <url> — the status alone.
http_code() {
    curl -s -o /dev/null -w '%{http_code}' --max-time 5 --connect-timeout 2 "$1" 2>/dev/null
}

# code_only <file> — a Python source file with its COMMENTS and DOCSTRINGS
# removed, and every other string literal KEPT.
#
# Stripping prose is load-bearing: server.py's docstring explains at length why
# it does NOT import urllib, and daemon.py's says in words that nothing writes
# to active-workflows/, so a grep over the raw files fails on the very
# documentation that states the invariant. The emitter test above strips `#`
# comments for the same reason; Python docstrings need an AST pass.
#
# Keeping ordinary string literals is equally load-bearing, and was learned the
# hard way: an earlier version stripped ALL strings, and a deliberately
# sabotaged `open(os.path.join(root, '.smith', 'vault', 'active-workflows',
# 'x.yaml'), 'w')` sailed through the FR-44 guard untouched, because the path
# it writes to lives entirely inside string literals. A guard blind to string
# literals is blind to every filesystem path in the program.
code_only() {
    python3 - "$1" <<'PY'
import ast
import io
import sys
import tokenize

path = sys.argv[1]
with open(path, "rb") as fh:
    source = fh.read()

# Docstring line ranges: a bare string expression opening a module, class or
# function body. Every other string is a value and stays.
prose = set()
try:
    tree = ast.parse(source)
except (SyntaxError, ValueError):
    sys.exit(0)          # unparseable: emit nothing rather than a false pass
for node in ast.walk(tree):
    body = getattr(node, "body", None)
    if not isinstance(body, list) or not body:
        continue
    if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
        continue
    first = body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
            and isinstance(first.value.value, str):
        end = getattr(first, "end_lineno", first.lineno) or first.lineno
        prose.update(range(first.lineno, end + 1))

out = []
try:
    for tok in tokenize.tokenize(io.BytesIO(source).readline):
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING and tok.start[0] in prose:
            continue
        out.append((tok.start[0], tok.string))
except (tokenize.TokenError, IndentationError):
    sys.exit(0)

line, buf = None, []
for row, text in out:
    if row != line:
        if buf:
            print(" ".join(buf))
        line, buf = row, []
    buf.append(text)
if buf:
    print(" ".join(buf))
PY
}

# net_import_hits <outfile> — every outbound-capable import in the daemon's
# source (FR-49). `urllib.parse` is deliberately NOT exempted: an exception
# carved into a guard is a guard nobody trusts, so server.py hand-rolls its
# query parsing and this pattern stays absolute.
net_import_hits() {
    local out="$1" f
    : > "$out"
    for f in "$REPO_ROOT"/scripts/activity/*.py; do
        code_only "$f" \
            | grep -nE '(^|[^a-zA-Z_.])(urllib|ftplib|smtplib|telnetlib)([^a-zA-Z_]|$)|http[[:space:]]*\.[[:space:]]*client|socket[[:space:]]*\.[[:space:]]*create_connection|requests[[:space:]]*\.[[:space:]]*(get|post)' \
            | sed "s|^|$(basename "$f"):|" >> "$out"
    done
}

# marker_write_hits <outfile> — FR-44, in two layers.
#
# LAYER 1 — containment. The on-disk directory name `active-workflows` may
# appear in the executable code of exactly ONE file under scripts/activity/:
# paths.py, which defines the read helper `active_workflows_dir()`. Everything
# else must go through that helper, so the literal anywhere else is a hit on
# sight, write verb or not.
#
# Layer 1 exists because layer 2 alone was RED-CHECKED AND FAILED. A sabotage
# of the form
#     target = os.path.join(root, '.smith', 'vault', 'active-workflows', 'x')
#     with open(target, 'w') as fh: ...
# splits the path from the write across two lines, and a line-scoped
# co-occurrence grep sees neither line as dangerous. Real code that writes to a
# directory almost always looks exactly like that.
#
# LAYER 2 — co-occurrence. A write primitive on a line that also names
# active-workflows, in any of those files AND in the emitter. The `[^-=]` guard
# in front of the redirect alternative is load-bearing: without it Python's
# `->` return annotation reads as a shell redirect and the READ helper
# `def active_workflows_dir(p: str) -> str:` is condemned. That exact false
# positive was observed, which is why the guard exists.
#
# Layer 3 is behavioural and lives in the test file: a running daemon must
# leave a fixture project's whole .smith/ mtime set unchanged.
MARKER_LITERAL_OWNER="paths.py"
MARKER_WRITE_VERB='open[[:space:]]*\(|makedirs|\bmkdir\b|os\.(remove|unlink|rename|replace)|shutil\.|\.write|(^|[^-=])>>?[[:space:]]|\btouch\b|\brm\b|\btee\b'
marker_write_hits() {
    local out="$1" f base
    : > "$out"
    for f in "$REPO_ROOT"/scripts/activity/*.py; do
        base=$(basename "$f")
        if [ "$base" != "$MARKER_LITERAL_OWNER" ]; then
            code_only "$f" | grep -n 'active-workflows' \
                | sed "s|^|$base: [layer-1 containment] |" >> "$out"
        fi
        code_only "$f" | grep -E 'active[-_]workflow' | grep -nE "$MARKER_WRITE_VERB" \
            | sed "s|^|$base: [layer-2 write-verb] |" >> "$out"
    done
    grep -v '^[[:space:]]*#' "$EMITTER" \
        | grep -E 'active[-_]workflow' | grep -nE "$MARKER_WRITE_VERB" \
        | sed 's|^|activity-emitter.sh: [layer-2 write-verb] |' >> "$out"
}

# vault_fingerprint <repo> — every path under .smith with its mtime and size.
vault_fingerprint() {
    find "$1/.smith" -print0 2>/dev/null \
        | xargs -0 stat -f '%N %m %z' 2>/dev/null | sort
}


# The T104-T109 statusline and redaction machinery, split off at the 500-line
# decompose threshold. Sourced here rather than from the test file so the test
# file still sources exactly one helper.
# shellcheck source=tests/lib/activity-statusline.sh
. "$REPO_ROOT/tests/lib/activity-statusline.sh"

# The T076 degraded-worktree fixture builder, split off for the same reason.
# shellcheck source=tests/lib/activity-worktrees.sh
. "$REPO_ROOT/tests/lib/activity-worktrees.sh"
