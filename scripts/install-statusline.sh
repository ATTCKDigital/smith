#!/usr/bin/env bash
# install-statusline.sh — WRAP the operator's statusLine, never clobber it
# (FR-45 / T105). Called by scripts/install.sh; safe to run standalone.
#
# Usage:
#   scripts/install-statusline.sh [--settings <path>]
#
# Environment:
#   CLAUDE_SETTINGS   default ~/.claude/settings.json
#   SMITH_HOME        default ~/.smith
#
# Its own file rather than a block inside install.sh, following the
# scripts/install-activity-transport.sh precedent two steps earlier in the same
# install: install.sh is already at ~486 lines, and — more importantly — SC-13
# has to be able to run this against a FIXTURE settings.json. A test that has
# to run the whole installer to exercise one merge is a test nobody runs.
#
# Why Smith touches `statusLine` at all: the statusline payload is the ONLY
# source of the FR-35 rolling quota windows. No API, no file and no CLI reports
# the 5-hour / 7-day limits. So the dashboard has to sit on that key — and it
# does so by delegating, with the payload passed through byte-for-byte.
#
# `statusLine` is a NEW TOP-LEVEL settings key, not a hook entry, so it merges
# through `$existing * $fragment` rather than the `.hooks` rebuild and
# dedupehooks.jq, neither of which can see it.
#
# Idempotent: a second run over an already-wrapped settings.json keeps the
# sidecar untouched. Re-capturing would record the TEE as the "previous"
# command and delegate to itself forever, and would also destroy the only
# record of what the operator originally had.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"

CLAUDE_SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
SMITH_HOME="${SMITH_HOME:-$HOME/.smith}"

while [ $# -gt 0 ]; do
    case "$1" in
        --settings) shift; CLAUDE_SETTINGS="${1:-$CLAUDE_SETTINGS}" ;;
        *) ;;
    esac
    shift
done

info() { echo "  → $*"; }
ok()   { echo "  ✓ $*"; }
warn() { echo "  ! $*" >&2; }
err()  { echo "  ✗ $*" >&2; }

command -v jq >/dev/null 2>&1 || { warn "jq not found — statusLine left unchanged"; exit 0; }
[ -f "$CLAUDE_SETTINGS" ] || printf '{}\n' > "$CLAUDE_SETTINGS"

ACTIVITY_DIR="$SMITH_HOME/activity"
STATUSLINE_TEE="$SMITH_HOME/scripts/activity/statusline-tee.sh"
WRAPPED_SIDECAR="$ACTIVITY_DIR/wrapped-statusline"
mkdir -p "$ACTIVITY_DIR" "$SMITH_HOME/scripts/activity"

# Stage the tee itself. T116 copies the whole scripts/activity/ tree; this one
# file is staged here as well because the statusLine key written below NAMES
# it, and pointing statusLine at a file that does not exist yet would put a
# broken status bar on every prompt — a worse failure than the clobbering this
# script exists to prevent. Copying it twice is idempotent.
cp "$REPO_ROOT/scripts/activity/statusline-tee.sh" "$STATUSLINE_TEE" 2>/dev/null || true
chmod +x "$STATUSLINE_TEE" 2>/dev/null || true

CURRENT=$(jq -c '.statusLine // null' "$CLAUDE_SETTINGS" 2>/dev/null || echo 'null')
[ -n "$CURRENT" ] || CURRENT='null'

CAPTURED=1
case "$CURRENT" in
    *statusline-tee.sh*)
        if [ -f "$WRAPPED_SIDECAR" ]; then
            info "statusLine already wrapped; $WRAPPED_SIDECAR kept unchanged"
        else
            printf '{"had_statusline":false,"previous":null}\n' > "$WRAPPED_SIDECAR"
            warn "statusLine was wrapped but the sidecar was missing — recorded 'none'"
        fi
        ;;
    null|'')
        printf '{"had_statusline":false,"previous":null}\n' > "$WRAPPED_SIDECAR"
        ok "No previous statusLine — the tee prints a minimal default line"
        ;;
    *)
        # `previous` stores the WHOLE original value, not just its `command`
        # string: the shape is Claude Code's (an object normally, a bare string
        # legally), and uninstall (T122) has to put back exactly what was there.
        TMP_SIDECAR="$(mktemp)"
        if jq -n --argjson prev "$CURRENT" '{had_statusline: true, previous: $prev}' \
               > "$TMP_SIDECAR" 2>/dev/null && [ -s "$TMP_SIDECAR" ]; then
            mv "$TMP_SIDECAR" "$WRAPPED_SIDECAR"
            ok "Captured the existing statusLine to $WRAPPED_SIDECAR"
        else
            rm -f "$TMP_SIDECAR"
            err "Could not capture the existing statusLine — leaving it UNWRAPPED"
            CAPTURED=0
        fi
        ;;
esac

# Wrapping a command we failed to record is the one outcome worse than not
# wrapping at all, so the rewrite is gated on the capture having landed.
if [ "$CAPTURED" != "1" ]; then
    exit 1
fi

TMP_SETTINGS="$(mktemp)"
jq -s --arg tee "$STATUSLINE_TEE" '
  .[0] as $existing |
  {statusLine: {type: "command", command: ("bash " + $tee)}} as $fragment |
  $existing * $fragment
' "$CLAUDE_SETTINGS" > "$TMP_SETTINGS" 2>/dev/null

# Same write guard as install.sh's hook merge: tempfile → jq empty → mv.
if [ -s "$TMP_SETTINGS" ] && jq empty "$TMP_SETTINGS" >/dev/null 2>&1; then
    mv "$TMP_SETTINGS" "$CLAUDE_SETTINGS"
    ok "statusLine now runs $STATUSLINE_TEE"
else
    rm -f "$TMP_SETTINGS"
    err "statusLine merge produced invalid JSON — $CLAUDE_SETTINGS left unchanged"
    exit 1
fi

exit 0
