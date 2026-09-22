#!/usr/bin/env bash
# activity-emitter.sh
# Event: SessionStart, SessionEnd, UserPromptSubmit, PreToolUse, PostToolUse,
#        PostToolUseFailure, SubagentStart, SubagentStop, Stop, Notification,
#        PermissionRequest, PermissionDenied, PreCompact, PostCompact,
#        ConfigChange
# Matcher: * (its own {matcher, hooks} entry per event — never appended to an
#          existing chain, so manifest-updater.sh stays LAST in the
#          PostToolUse Write|Edit chain; see scripts/install-hooks.sh:6-7)
# Scope: Universal (main session + sub-agents)
#
# What it does: forwards the hook payload on stdin BYTE-FOR-BYTE to the local
# /smith-activity daemon at POST http://127.0.0.1:<port>/ingest. It parses
# nothing — no jq, no grep, no sed. Parsing is the only thing in an emitter
# that can fail in an interesting way, and on PreToolUse an interesting failure
# blocks the operator's tool call.
#
# Exit contract (FR-40 / SC-4), which is absolute:
#   - exits 0 on EVERY path, including every error path. Exit 2 is Claude
#     Code's block signal and any other non-zero puts a visible "hook error"
#     notice in the operator's transcript; US-4 forbids both. `set -uo pipefail`
#     deliberately omits -e so a failing curl cannot abort the script.
#   - writes ZERO bytes to stdout. On UserPromptSubmit and SessionStart stdout
#     is injected into Claude's context, so noise here is not cosmetic.
#   - silent no-op when the daemon is down: with activity.port / activity.token
#     absent — the state of every machine until /smith-activity is first run —
#     it exits 0 before attempting any network call.
#   - bounded without `timeout`. Neither `timeout` nor `gtimeout` exists on a
#     stock macOS, so the TIMEOUT_BIN idiom at hooks/context-loader.sh:117-122
#     imposes no bound at all and is NOT copied here. The bound is curl's own
#     --max-time / --connect-timeout, which are built in. The call is also
#     detached, so the foreground cost is a fork, not the ceiling.
#   - no /dev/tcp anywhere: it is a bash-only virtual path and this repo runs
#     its shell surfaces under zsh too.
#
# Files touched: reads "${SMITH_HOME:-$HOME/.smith}"/activity/activity.port and
# .../activity.token. Writes nothing, anywhere. In particular it never writes
# to any project's .smith/vault/ (FR-44).
#
# Network: one loopback POST to 127.0.0.1 and nothing else. No outbound
# network of any kind.
#
# Privacy note: the payload leaves this script unredacted because the daemon is
# the sole parser and the sole redaction point (contracts/hook-envelope.md §4),
# which keeps the redaction rules in exactly one file. The transport is
# loopback-only and the receiver is token-gated. With
# SMITH_ACTIVITY_CAPTURE_PROMPTS unset the daemon replaces `prompt`,
# `tool_input` and `tool_response` with byte-length placeholders before the
# payload reaches its state tree, so nothing renderable retains prompt text.
#
# To disable: remove the entries referencing this script from
# ~/.claude/settings.json, or simply stop the daemon — with no port file the
# emitter is a ~6 ms no-op.

set -uo pipefail

# Read stdin unconditionally. A hook that does not drain stdin can leave the
# writer blocked; `|| echo '{}'` keeps a closed/empty stdin from tripping -u.
INPUT=$(cat 2>/dev/null || echo '{}')

ACTIVITY_DIR="${SMITH_HOME:-$HOME/.smith}/activity"
PORTFILE="$ACTIVITY_DIR/activity.port"
TOKFILE="$ACTIVITY_DIR/activity.token"

# --- Early-bail ladder. Every rung is a silent exit 0. --------------------
# daemon never started, or stopped and cleaned up
[ -f "$PORTFILE" ] && [ -f "$TOKFILE" ] || exit 0
# no transport
command -v curl >/dev/null 2>&1 || exit 0

PORT=$(cat "$PORTFILE" 2>/dev/null) || exit 0
TOKEN=$(cat "$TOKFILE" 2>/dev/null) || exit 0

# A truncated or half-written port file must not become part of a URL.
case "$PORT" in
    ''|*[!0-9]*) exit 0 ;;
esac
[ -n "$TOKEN" ] || exit 0

# --- The one network call, detached and bounded. --------------------------
# The subshell-plus-& detaches the curl so the hook does not wait even for
# --max-time; >/dev/null 2>&1 on the subshell itself is what guarantees zero
# bytes on stdout regardless of what curl or the shell's job control emit.
(
    printf '%s' "$INPUT" | curl -s -o /dev/null \
        --max-time 2 --connect-timeout 1 \
        -X POST \
        -H 'Content-Type: application/json' \
        -H "Authorization: Bearer $TOKEN" \
        --data-binary @- \
        "http://127.0.0.1:$PORT/ingest" >/dev/null 2>&1 &
) >/dev/null 2>&1

exit 0
