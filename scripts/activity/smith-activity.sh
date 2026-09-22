#!/usr/bin/env bash
# smith-activity.sh — lifecycle CLI for the /smith-activity daemon (T094/T095).
#
# Usage:
#   smith-activity.sh [start|stop|restart|status|open] [--port N] [--no-open]
#                     [--foreground]
#
# No subcommand => ensure running, register this project, open the dashboard
# (FR-1). A second invocation from another project starts NO second daemon: it
# registers that project against the running one and opens a new tab (FR-2).
# One daemon serves every project.
#
# Discipline adapted from skills/smith-research/scripts/start-playwright-server.sh
# — port probe, pidfile, stale-PID detection via `kill -0`, `nohup ... &`,
# bounded readiness polling. TWO deliberate substitutions from that script:
#
#   1. NO /dev/tcp. It is a bash-only virtual path; this repo runs its shell
#      surfaces under zsh too, where it does not exist and the probe would
#      silently report every port free.
#   2. NO `timeout` / `gtimeout` / TIMEOUT_BIN. Neither binary exists on a
#      stock macOS, so the TIMEOUT_BIN idiom used elsewhere in hooks/ imposes
#      no bound at all. Every bound here is curl's own --max-time /
#      --connect-timeout or a python3 socket timeout, both of which are built
#      in and portable.
#
# Port occupancy is resolved by the /health IDENTITY probe, never by the HTTP
# status: an existing Smith daemon is REUSED, an unrelated program means the
# next port is tried, and neither case aborts (FR-5).
#
# A stale pidfile — pid gone, or alive but not our daemon — is cleaned up and
# the daemon restarted. It is never a failure (FR-6).
#
# All runtime state lives under "${SMITH_HOME:-$HOME/.smith}"/activity/ and
# never inside any project vault (FR-7). This script writes nothing to any
# project's .smith/, and nothing at all to .smith/vault/active-workflows/
# (FR-44) — the /smith-activity SKILL's own marker is created by
# create-active-workflow.sh, not here.
#
# The LAST line of stdout is always the dashboard URL when a daemon is up.
#
# `set -e` is deliberately omitted: a failed probe is a normal branch, not an
# abort.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd -P)"
SERVER_PY="$SCRIPT_DIR/server.py"

ACTIVITY_DIR="${SMITH_HOME:-$HOME/.smith}/activity"
PIDFILE="$ACTIVITY_DIR/activity.pid"
PORTFILE="$ACTIVITY_DIR/activity.port"
TOKFILE="$ACTIVITY_DIR/activity.token"
LOGFILE="$ACTIVITY_DIR/activity.log"

DEFAULT_PORT=8787
PORT_PROBE_LIMIT=20
READY_TRIES=100      # x 0.1s = 10s ceiling
LOG_MAX_BYTES=5242880   # 5 MB, single rollover (T095)

ACTION=""
WANT_PORT=""
NO_OPEN=0
FOREGROUND=0

while [ $# -gt 0 ]; do
    case "$1" in
        start|stop|restart|status|open) ACTION="$1"; shift ;;
        --port) WANT_PORT="${2:-}"; shift 2 ;;
        --port=*) WANT_PORT="${1#--port=}"; shift ;;
        --no-open) NO_OPEN=1; shift ;;
        --foreground) FOREGROUND=1; shift ;;
        -h|--help) sed -n '3,12p' "$0"; exit 0 ;;
        *) echo "smith-activity: unknown argument: $1" >&2; exit 2 ;;
    esac
done
: "${ACTION:=default}"

mkdir -p "$ACTIVITY_DIR" 2>/dev/null
chmod 700 "$ACTIVITY_DIR" 2>/dev/null

# --------------------------------------------------------------------------
# Probes. Every one is bounded without `timeout`.
# --------------------------------------------------------------------------

# port_in_use PORT — 0 when something is listening. python3, never /dev/tcp.
port_in_use() {
    python3 - "$1" <<'PY'
import socket
import sys

sock = socket.socket()
sock.settimeout(0.5)          # the bound; no external timeout binary needed
try:
    sock.connect(("127.0.0.1", int(sys.argv[1])))
    sys.exit(0)
except (OSError, ValueError):
    sys.exit(1)
finally:
    sock.close()
PY
}

# identity PORT — echoes the /health `service` value, or "" for anything else.
# The FR-5 probe is this string, NOT the HTTP status: an unrelated program
# either refuses, returns non-JSON, or returns JSON without the key, and all
# three resolve to "pick another port".
identity() {
    curl -s --max-time 2 --connect-timeout 1 \
        "http://127.0.0.1:$1/health" 2>/dev/null | python3 -c '
import json
import sys

try:
    print((json.load(sys.stdin) or {}).get("service", ""))
except Exception:
    print("")
' 2>/dev/null
}

is_smith_daemon() { [ "$(identity "$1")" = "smith-activity" ]; }

pid_alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }

# is_our_process PID — the daemon's own command line. Checked before any kill:
# a recycled pid belongs to somebody else's program and must never be signalled.
is_our_process() {
    ps -o command= -p "$1" 2>/dev/null | grep -q "activity/server.py"
}

read_file() { [ -f "$1" ] && tr -d '[:space:]' < "$1" || echo ""; }

rollover_log() {
    [ -f "$LOGFILE" ] || return 0
    local size
    size=$(wc -c < "$LOGFILE" 2>/dev/null | tr -d ' ')
    [ -n "$size" ] || return 0
    if [ "$size" -gt "$LOG_MAX_BYTES" ]; then
        mv -f "$LOGFILE" "$LOGFILE.1" 2>/dev/null
    fi
}

# --------------------------------------------------------------------------
# Stale-state recovery (FR-6). Never an error path.
# --------------------------------------------------------------------------

clean_stale() {
    local pid port
    pid="$(read_file "$PIDFILE")"
    port="$(read_file "$PORTFILE")"
    [ -n "$pid" ] || return 0
    if pid_alive "$pid" && is_our_process "$pid"; then
        # Alive and ours. Still stale if it is not answering on its own port —
        # a wedged daemon is indistinguishable from an absent one to a hook.
        if [ -n "$port" ] && is_smith_daemon "$port"; then
            return 0
        fi
        kill "$pid" 2>/dev/null
        sleep 0.5
        pid_alive "$pid" && kill -9 "$pid" 2>/dev/null
    fi
    # pid gone, or alive but foreign (a recycled number): drop the files and
    # carry on. Removing activity.port also returns the emitter to its silent
    # no-op, which is the correct state while no daemon is up.
    rm -f "$PIDFILE" "$PORTFILE" 2>/dev/null
    return 0
}

# --------------------------------------------------------------------------
# Port selection (FR-5)
# --------------------------------------------------------------------------

# Echoes "<port> <reuse:0|1>".
choose_port() {
    local start port i
    start="${WANT_PORT:-$(read_file "$PORTFILE")}"
    [ -n "$start" ] || start="$DEFAULT_PORT"
    port="$start"
    i=0
    while [ "$i" -lt "$PORT_PROBE_LIMIT" ]; do
        if ! port_in_use "$port"; then
            echo "$port 0"; return 0
        fi
        if is_smith_daemon "$port"; then
            echo "$port 1"; return 0        # reuse — never a second daemon
        fi
        port=$((port + 1))                   # unrelated program: move along
        i=$((i + 1))
    done
    # Exhausted the window. Hand back the last candidate rather than aborting;
    # the bind will fail loudly in the log and `status` will say so.
    echo "$port 0"
    return 0
}

wait_ready() {
    local port i=0
    port="$1"
    while [ "$i" -lt "$READY_TRIES" ]; do
        if is_smith_daemon "$port"; then return 0; fi
        sleep 0.1
        i=$((i + 1))
    done
    return 1
}

# --------------------------------------------------------------------------
# Registration + URL
# --------------------------------------------------------------------------

register_here() {
    local port token payload
    port="$1"
    token="$(read_file "$TOKFILE")"
    [ -n "$token" ] || return 1
    payload=$(printf '{"path":%s}' "$(python3 -c '
import json
import os
import sys

print(json.dumps(os.path.abspath(sys.argv[1])))
' "$(pwd)")")
    curl -s --max-time 5 --connect-timeout 2 \
        -H "Content-Type: application/json" \
        -X POST "http://127.0.0.1:$port/api/register?token=$token" \
        -d "$payload" 2>/dev/null
}

url_from_registration() {
    python3 -c '
import json
import sys

try:
    print((json.load(sys.stdin) or {}).get("url", ""))
except Exception:
    print("")
' 2>/dev/null
}

open_url() {
    [ "$NO_OPEN" -eq 1 ] && return 0
    if command -v open >/dev/null 2>&1; then
        open "$1" >/dev/null 2>&1 &
    elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$1" >/dev/null 2>&1 &
    fi
    return 0
}

# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------

do_start() {
    rollover_log
    clean_stale

    local chosen port reuse
    chosen="$(choose_port)"
    port="${chosen%% *}"
    reuse="${chosen##* }"

    if [ "$FOREGROUND" -eq 1 ]; then
        exec python3 "$SERVER_PY" --port "$port"
    fi

    if [ "$reuse" = "1" ]; then
        echo "[smith-activity] reusing the daemon already listening on :$port"
    else
        nohup python3 "$SERVER_PY" --port "$port" >> "$LOGFILE" 2>&1 &
        if ! wait_ready "$port"; then
            echo "[smith-activity] daemon did not become ready on :$port — see $LOGFILE" >&2
            return 1
        fi
        echo "[smith-activity] started on :$port (pid $(read_file "$PIDFILE"))"
    fi

    local response url
    response="$(register_here "$port")"
    url="$(printf '%s' "$response" | url_from_registration)"
    # Fallback when registration did not answer. The ?token= matters: the page
    # is served un-gated so it can read its own token out of the query string,
    # and without one it loads and then 403s on everything it needs.
    if [ -z "$url" ]; then
        url="http://127.0.0.1:$port/"
        local tok
        tok="$(read_file "$TOKFILE")"
        [ -n "$tok" ] && url="http://127.0.0.1:$port/?token=$tok"
    fi
    open_url "$url"
    echo "$url"          # LAST line of stdout, always
    return 0
}

do_stop() {
    local pid port
    pid="$(read_file "$PIDFILE")"
    port="$(read_file "$PORTFILE")"
    if [ -n "$pid" ] && pid_alive "$pid" && is_our_process "$pid"; then
        kill "$pid" 2>/dev/null
        local i=0
        while [ "$i" -lt 50 ] && pid_alive "$pid"; do sleep 0.1; i=$((i + 1)); done
        pid_alive "$pid" && kill -9 "$pid" 2>/dev/null
        echo "[smith-activity] stopped pid $pid (was :${port:-?})"
    else
        echo "[smith-activity] no daemon running"
    fi
    rm -f "$PIDFILE" "$PORTFILE" 2>/dev/null
    return 0
}

do_status() {
    local pid port
    pid="$(read_file "$PIDFILE")"
    port="$(read_file "$PORTFILE")"
    if [ -n "$port" ] && is_smith_daemon "$port"; then
        echo "[smith-activity] running  pid=${pid:-?} port=$port"
        curl -s --max-time 2 --connect-timeout 1 "http://127.0.0.1:$port/health" 2>/dev/null
        echo
        local tok
        tok="$(read_file "$TOKFILE")"
        if [ -n "$tok" ]; then
            echo "http://127.0.0.1:$port/?token=$tok"
        else
            echo "http://127.0.0.1:$port/"
        fi
        return 0
    fi
    if [ -n "$pid" ]; then
        echo "[smith-activity] not running (stale pidfile: pid=${pid}, port=${port:-?})"
    else
        echo "[smith-activity] not running"
    fi
    return 1
}

case "$ACTION" in
    start|default|open) do_start ;;
    stop)               do_stop ;;
    restart)            do_stop; do_start ;;
    status)             do_status ;;
    *)                  echo "smith-activity: unknown action: $ACTION" >&2; exit 2 ;;
esac
