#!/usr/bin/env bash
# start-playwright-server.sh — host-side Playwright server for smith-research.
#
# Adapted from armory/scripts/start-playwright-server.sh (provenance: the armory
# trend-intelligence Reddit collector's Cloudflare evasion relies on a real-Chrome
# TLS fingerprint served by a persistent `playwright run-server`). smith-research
# runs NATIVELY (not in Docker), so it connects via ws://localhost:<PORT>/ rather
# than host.docker.internal, and uses its OWN port (9224) to avoid colliding with
# armory's 9223.
#
# Idempotent: if a server is already listening on PORT, skip. Kills a stale pid
# that is alive but not listening. Waits up to 10s for readiness.
#
# Usage:
#   start-playwright-server.sh [--port N] [--pid-file PATH] [--log-file PATH]
#
# Exit codes: 0 started/already-up · 1 failed to start within timeout.

set -euo pipefail

PORT="${SMITH_RESEARCH_PLAYWRIGHT_PORT:-9224}"
PID_FILE=""
LOG_FILE=""

while [ $# -gt 0 ]; do
    case "$1" in
        --port)     PORT="$2"; shift 2 ;;
        --pid-file) PID_FILE="$2"; shift 2 ;;
        --log-file) LOG_FILE="$2"; shift 2 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

# Default pid/log to a temp location if not given (the SKILL.md passes the run
# workspace so they land under ~/Documents/.../<run>/).
: "${PID_FILE:=${TMPDIR:-/tmp}/smith-research-playwright-${PORT}.pid}"
: "${LOG_FILE:=${TMPDIR:-/tmp}/smith-research-playwright-${PORT}.log}"

port_listening() {
    # nc -z is present on macOS; fall back to bash /dev/tcp if missing.
    if command -v nc >/dev/null 2>&1; then
        nc -z localhost "$PORT" 2>/dev/null
    else
        (exec 3<>"/dev/tcp/localhost/$PORT") 2>/dev/null && exec 3>&-
    fi
}

if port_listening; then
    echo "[playwright-server] already listening on :$PORT — skipping"
    echo "ws://localhost:$PORT/"
    exit 0
fi

if [ -f "$PID_FILE" ]; then
    OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "[playwright-server] stale pid $OLD_PID alive but not listening — killing"
        kill "$OLD_PID" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
fi

mkdir -p "$(dirname "$LOG_FILE")" "$(dirname "$PID_FILE")"

# Start from the skill's OWN venv Python so the served browser version matches
# the venv's playwright package (mismatched Node-npx vs venv-Python browsers
# cause "Executable doesn't exist" render failures). Falls back to npx only if
# the venv isn't present yet.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PY="$SCRIPT_DIR/.venv/bin/python"

if [ -x "$VENV_PY" ]; then
    nohup "$VENV_PY" -m playwright run-server --port "$PORT" --path / \
        > "$LOG_FILE" 2>&1 &
else
    # --path / matches the armory contract (collector connects to ws://host:port/).
    nohup npx --yes playwright run-server --port "$PORT" --path / \
        > "$LOG_FILE" 2>&1 &
fi
echo $! > "$PID_FILE"

for _ in 1 2 3 4 5 6 7 8 9 10; do
    if port_listening; then
        echo "[playwright-server] started on :$PORT (pid $(cat "$PID_FILE")) — log: $LOG_FILE"
        echo "ws://localhost:$PORT/"
        exit 0
    fi
    sleep 1
done

echo "[playwright-server] FAILED to start on :$PORT within 10s — see $LOG_FILE" >&2
exit 1
