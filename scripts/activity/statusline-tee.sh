#!/usr/bin/env bash
# statusline-tee.sh — FR-45 / T104.
#
# Purpose: wrap whatever `statusLine` command the operator already had, feed a
#          copy of the payload to the local /smith-activity daemon, and hand
#          the operator's own statusline through UNCHANGED.
#
# The whole point of this file is that it is NOT a statusline. Smith owns no
# statusline and must not acquire one by accident: a dashboard that silently
# replaced the operator's carefully-tuned status bar would be a worse trade
# than no quota panel at all. SC-13 asserts the pass-through is BYTE-FOR-BYTE.
#
# What it does:
#   1. Reads stdin EXACTLY ONCE into $INPUT. stdin is a pipe — a second `cat`
#      reads zero bytes, so the delegate would receive an empty payload and
#      render an empty bar. This is the single most important line here.
#   2. Forwards a copy to POST /statusline, detached and bounded, output
#      discarded. This is the ONLY source of the FR-35 quota windows: there is
#      no API, no file and no CLI that reports the 5-hour / 7-day rolling
#      limits, which is why they are scraped off the statusline payload.
#   3. Delegates to the command captured at install time in
#      "${SMITH_HOME:-$HOME/.smith}"/activity/wrapped-statusline, piping the
#      same bytes in. When there was no prior command it prints a minimal
#      default line — never nothing, never an error.
#
# Exit contract: exits 0 on every path. A statusline that exits non-zero, or
# writes to stderr in the operator's face, is a visible defect on every single
# prompt. `set -uo pipefail` deliberately omits -e.
#
# Bounded without `timeout`: neither `timeout` nor `gtimeout` exists on a
# stock macOS. The bound is curl's own --max-time / --connect-timeout, which
# are built in, and the call is detached so the foreground cost is a fork.
#
# Files touched: reads activity.port, activity.token and wrapped-statusline
# under "${SMITH_HOME:-$HOME/.smith}"/activity/. Writes nothing, anywhere.
#
# Network: one loopback POST to 127.0.0.1 and nothing else.
#
# Privacy note: the statusline payload carries no prompt text and no tool
# input. It does carry `cwd`, `transcript_path` and the cost/context blocks.
# The daemon is the sole parser and the sole redaction point, exactly as for
# hooks/activity-emitter.sh (contracts/hook-envelope.md §4).
#
# To restore the previous statusline by hand: read the `previous` value out of
# wrapped-statusline and put it back under `statusLine` in
# ~/.claude/settings.json. scripts/uninstall.sh does this for you (T122).

set -uo pipefail

# --- 1. stdin, exactly once ------------------------------------------------
# `|| echo '{}'` keeps a closed or empty stdin from tripping -u; a statusline
# invoked by hand with no pipe must still print something.
INPUT=$(cat 2>/dev/null || echo '{}')
[ -n "$INPUT" ] || INPUT='{}'

ACTIVITY_DIR="${SMITH_HOME:-$HOME/.smith}/activity"
PORTFILE="$ACTIVITY_DIR/activity.port"
TOKFILE="$ACTIVITY_DIR/activity.token"
WRAPFILE="$ACTIVITY_DIR/wrapped-statusline"

# --- 2. forward a copy, detached and bounded -------------------------------
# Same early-bail ladder as hooks/activity-emitter.sh: with the daemon down
# there is no port file, and this whole block is skipped for the cost of two
# stat calls. The forward must never delay the operator's status bar.
if [ -f "$PORTFILE" ] && [ -f "$TOKFILE" ] && command -v curl >/dev/null 2>&1; then
    STATUS_PORT=$(cat "$PORTFILE" 2>/dev/null) || STATUS_PORT=""
    STATUS_TOKEN=$(cat "$TOKFILE" 2>/dev/null) || STATUS_TOKEN=""
    case "$STATUS_PORT" in
        ''|*[!0-9]*) STATUS_PORT="" ;;   # truncated/half-written: not a URL
    esac
    if [ -n "$STATUS_PORT" ] && [ -n "$STATUS_TOKEN" ]; then
        (
            printf '%s' "$INPUT" | curl -s -o /dev/null \
                --max-time 2 --connect-timeout 1 \
                -X POST \
                -H 'Content-Type: application/json' \
                -H "Authorization: Bearer $STATUS_TOKEN" \
                --data-binary @- \
                "http://127.0.0.1:$STATUS_PORT/statusline" >/dev/null 2>&1 &
        ) >/dev/null 2>&1
    fi
fi

# --- 3. decide what to delegate to -----------------------------------------
# One python3 spawn decides BOTH the wrapped command and the fallback line, so
# the hot path costs one interpreter start rather than two. The protocol is
# deliberately line-oriented: line 1 is the mode, everything after it is the
# value, so a multi-line wrapped command survives intact.
#
# python3 rather than jq: jq is an install-time dependency of this repo, not a
# runtime one, and a statusline that breaks when jq is missing breaks on every
# prompt. `previous` is also a *value* of unknown shape — Claude Code's
# `statusLine` is normally {"type":"command","command":"…"} but a bare string
# is legal — and a shape-tolerant read is easier to get right in Python.
STATUSLINE_DECIDER=$(cat <<'PY'
import json
import os
import sys

sidecar = sys.argv[1] if len(sys.argv) > 1 else ""

try:
    payload = json.loads(sys.stdin.read() or "{}")
except Exception:
    payload = {}
if not isinstance(payload, dict):
    payload = {}


def wrapped_command(path):
    """The command captured at install time, or None.

    `had_statusline: false` means the operator had none, which is a POSITIVE
    fact recorded at install time, not an absence. It is honoured as such: the
    default line is printed and nothing is delegated to.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            sidecar_data = json.load(handle)
    except Exception:
        return None
    if not isinstance(sidecar_data, dict):
        return None
    if not sidecar_data.get("had_statusline"):
        return None
    previous = sidecar_data.get("previous")
    if isinstance(previous, str):
        return previous.strip() or None
    if isinstance(previous, dict):
        command = previous.get("command")
        if isinstance(command, str) and command.strip():
            return command.strip()
    return None


def default_line(data):
    """The minimal line printed when the operator had no statusline at all.

    Built only from fields the payload actually carries. A field that is
    missing is omitted rather than rendered as a placeholder or a zero — the
    same honesty rule the dashboard itself follows (FR-20/A-9).
    """
    parts = []
    model = data.get("model")
    if isinstance(model, dict) and model.get("display_name"):
        parts.append(str(model["display_name"]))
    workspace = data.get("workspace")
    directory = None
    if isinstance(workspace, dict):
        directory = workspace.get("current_dir") or workspace.get("project_dir")
    directory = directory or data.get("cwd")
    if directory:
        parts.append(os.path.basename(str(directory).rstrip("/")) or str(directory))
    window = data.get("context_window")
    if isinstance(window, dict) and window.get("used_percentage") is not None:
        try:
            parts.append("ctx %d%%" % round(float(window["used_percentage"])))
        except (TypeError, ValueError):
            pass
    return " | ".join(parts) if parts else "smith"


command = wrapped_command(sidecar)
if command:
    sys.stdout.write("CMD\n")
    sys.stdout.write(command)
else:
    sys.stdout.write("DEFAULT\n")
    sys.stdout.write(default_line(payload))
PY
)

DECISION=""
if command -v python3 >/dev/null 2>&1; then
    DECISION=$(printf '%s' "$INPUT" | python3 -c "$STATUSLINE_DECIDER" "$WRAPFILE" 2>/dev/null) \
        || DECISION=""
fi

MODE=$(printf '%s\n' "$DECISION" | head -n 1)
VALUE=$(printf '%s\n' "$DECISION" | tail -n +2)

# --- 4. delegate, or print the minimal default -----------------------------
if [ "$MODE" = "CMD" ] && [ -n "$VALUE" ]; then
    # The delegate receives the SAME bytes on stdin that Claude Code sent us,
    # and its stdout goes straight through. Nothing is added, prefixed,
    # suffixed or trimmed: SC-13 diffs this against the unwrapped output and
    # requires them identical.
    #
    # `sh -c` rather than `eval`: the stored value is a command line the way
    # Claude Code itself would run it, and `eval` would additionally expand it
    # in THIS shell's context, where $INPUT and friends are in scope.
    printf '%s' "$INPUT" | sh -c "$VALUE"
elif [ -n "$VALUE" ]; then
    printf '%s\n' "$VALUE"
else
    # python3 missing, or the decider itself failed. Still print something.
    printf '%s\n' "smith"
fi

exit 0
