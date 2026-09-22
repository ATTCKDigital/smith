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
