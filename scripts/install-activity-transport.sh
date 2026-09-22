#!/usr/bin/env bash
# install-activity-transport.sh — choose the /smith-activity hook transport
# (FR-42). Called by scripts/install.sh immediately after the settings-fragment
# merge; safe to run standalone.
#
# Usage:
#   scripts/install-activity-transport.sh [--settings <path>]
#
# Environment:
#   CLAUDE_SETTINGS                 default ~/.claude/settings.json
#   SMITH_HOME                      default ~/.smith
#   SMITH_ACTIVITY_NO_NATIVE_HTTP=1 force the shell emitter
#
# The fragment merge wires hooks/activity-emitter.sh on 15 events. A native
# `{"type":"http", …}` entry is strictly better where it works — zero process
# spawn per tool call instead of the measured ~9.8 ms — so this script UPGRADES
# those entries in place when, and only when, every precondition is positively
# confirmed.
#
# "On any doubt, keep the emitter" is not caution for its own sake: the
# fallback was measured at 9.8 ms against a live daemon and 4.4 ms with no
# daemon installed (contracts/hook-envelope.md §6), so conservative detection
# is nearly free — while a native entry pointed at a port nothing is listening
# on is a hook that fails on every single tool call.
#
# Three preconditions, ALL required:
#   1. not opted out via SMITH_ACTIVITY_NO_NATIVE_HTTP=1;
#   2. the installed Claude Code positively advertises the native-http entry
#      shape. 2.1.269 ships a ~200 MB compiled binary rather than a greppable
#      JS bundle, so the probe looks for `allowedEnvVars` — a field that exists
#      ONLY on an http hook entry — in whatever `claude` resolves to. Absence
#      of evidence is treated as absence of support, never as permission;
#   3. the daemon is running NOW, so activity.port names a real port. The url
#      is baked in at install time and cannot follow a later port change
#      (FR-5) — which is the whole reason the emitter, which reads the port
#      file live, stays the shipped default rather than a legacy path.
#
# Precondition 3 fails on a normal first install, so the emitter is what almost
# every machine gets. That is the intended outcome, not a degraded one.

set -uo pipefail

CLAUDE_SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
SMITH_HOME="${SMITH_HOME:-$HOME/.smith}"

while [ $# -gt 0 ]; do
    case "$1" in
        --settings) shift; CLAUDE_SETTINGS="${1:-$CLAUDE_SETTINGS}" ;;
        -h|--help) sed -n '2,10p' "$0" | sed 's/^# *//'; exit 0 ;;
    esac
    shift
done

c_reset='\033[0m'; c_green='\033[32m'; c_yellow='\033[33m'; c_blue='\033[34m'
info() { printf "${c_blue}==>${c_reset} %s\n" "$*"; }
ok()   { printf "${c_green}✓${c_reset} %s\n" "$*"; }
warn() { printf "${c_yellow}!${c_reset} %s\n" "$*" >&2; }

[ -f "$CLAUDE_SETTINGS" ] || { info "/smith-activity: no $CLAUDE_SETTINGS — nothing to do"; exit 0; }
command -v python3 >/dev/null 2>&1 || { warn "/smith-activity: python3 absent — emitter entries left as merged"; exit 0; }

ACTIVITY_DIR="$SMITH_HOME/activity"
ACTIVITY_PORT=""
NATIVE_HTTP=0
NATIVE_DOUBT="native http not attempted"

if [ "${SMITH_ACTIVITY_NO_NATIVE_HTTP:-0}" = "1" ]; then
    NATIVE_DOUBT="opted out via SMITH_ACTIVITY_NO_NATIVE_HTTP=1"
elif [ ! -f "$ACTIVITY_DIR/activity.port" ] || [ ! -s "$ACTIVITY_DIR/activity.token" ]; then
    NATIVE_DOUBT="no running daemon at install time (no activity.port/token)"
else
    ACTIVITY_PORT="$(tr -dc '0-9' < "$ACTIVITY_DIR/activity.port" 2>/dev/null || true)"
    if [ -z "$ACTIVITY_PORT" ]; then
        NATIVE_DOUBT="activity.port is empty or non-numeric"
    elif ! command -v claude >/dev/null 2>&1; then
        NATIVE_DOUBT="claude not on PATH — cannot confirm native http support"
    elif python3 - "$(command -v claude)" <<'PY'
import os
import subprocess
import sys

# Bounded WITHOUT `timeout`: neither timeout nor gtimeout exists on stock
# macOS, so a TIMEOUT_BIN idiom here would impose no bound at all.
try:
    target = os.path.realpath(sys.argv[1])
except OSError:
    sys.exit(1)
try:
    # -a: the 2.1.269 payload is a compiled binary, not text.
    rc = subprocess.run(["grep", "-aqm1", "allowedEnvVars", target], timeout=10).returncode
except (subprocess.SubprocessError, OSError):
    sys.exit(1)
sys.exit(0 if rc == 0 else 1)
PY
    then
        NATIVE_HTTP=1
    else
        NATIVE_DOUBT="installed Claude Code does not advertise 'allowedEnvVars'"
    fi
fi

# Runs on BOTH branches and is idempotent: it first strips any native activity
# entry a previous install wrote, so a machine that once qualified and no
# longer does falls back cleanly instead of pointing at a stale port forever.
ACTIVITY_TMP="$(mktemp)"
ACTIVITY_COUNT="$(mktemp)"
if python3 - "$CLAUDE_SETTINGS" "$ACTIVITY_TMP" "$NATIVE_HTTP" "$ACTIVITY_PORT" > "$ACTIVITY_COUNT" <<'PY'
import json
import sys

settings_path, out_path, native, port = sys.argv[1], sys.argv[2], sys.argv[3] == "1", sys.argv[4]
EMITTER = "activity-emitter.sh"
URL_MARK = "/ingest"

try:
    with open(settings_path, "r", encoding="utf-8") as fh:
        settings = json.load(fh)
except (OSError, ValueError):
    sys.exit(1)
if not isinstance(settings, dict):
    sys.exit(1)

hooks = settings.get("hooks")
if not isinstance(hooks, dict):
    print(0)
    sys.exit(0)


def is_native(entry):
    return (isinstance(entry, dict) and entry.get("type") == "http"
            and URL_MARK in (entry.get("url") or ""))


def is_emitter(entry):
    return isinstance(entry, dict) and EMITTER in (entry.get("command") or "")


converted = 0
for blocks in hooks.values():
    if not isinstance(blocks, list):
        continue
    for block in blocks:
        if not isinstance(block, dict):
            continue
        chain = block.get("hooks")
        if not isinstance(chain, list):
            continue
        # Drop stale native entries unconditionally; the command entries are
        # re-supplied by the fragment merge on every run.
        kept = [e for e in chain if not is_native(e)]
        if native:
            for i, entry in enumerate(kept):
                if not is_emitter(entry):
                    continue
                kept[i] = {
                    "type": "http",
                    "url": "http://127.0.0.1:%s/ingest" % port,
                    "headers": {"Authorization": "Bearer $SMITH_ACTIVITY_TOKEN"},
                    "allowedEnvVars": ["SMITH_ACTIVITY_TOKEN"],
                    "timeout": 5,
                }
                converted += 1
        block["hooks"] = kept

with open(out_path, "w", encoding="utf-8") as fh:
    json.dump(settings, fh, indent=2)
    fh.write("\n")
print(converted)
PY
then
    # Never replace settings.json with the output of a failed run.
    if [ -s "$ACTIVITY_TMP" ] && python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$ACTIVITY_TMP" 2>/dev/null; then
        mv "$ACTIVITY_TMP" "$CLAUDE_SETTINGS"
        CONVERTED="$(tr -dc '0-9' < "$ACTIVITY_COUNT" 2>/dev/null || true)"
        if [ "$NATIVE_HTTP" = "1" ]; then
            ok "/smith-activity: ${CONVERTED:-0} native \"type\": \"http\" entries → 127.0.0.1:$ACTIVITY_PORT"
        else
            info "/smith-activity: using hooks/activity-emitter.sh ($NATIVE_DOUBT)"
        fi
    else
        rm -f "$ACTIVITY_TMP"
        warn "/smith-activity: transport rewrite produced invalid JSON — settings left unchanged"
    fi
else
    rm -f "$ACTIVITY_TMP"
    warn "/smith-activity: transport selection skipped; emitter entries left as merged"
fi
rm -f "$ACTIVITY_COUNT"

exit 0
