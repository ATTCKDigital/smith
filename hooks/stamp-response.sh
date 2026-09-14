#!/usr/bin/env bash
# stamp-response.sh
# Event: Stop
# Scope: Main session only (SubagentStop is a separate event and is not wired)
#
# Deterministically surfaces a "YYYY-MM-DD HH:MM:SS — <branch-name>" stamp for
# the assistant's just-completed turn. This replaces the fail-open enforcement
# that previously lived in grade-response.sh / Rule 6: the Haiku critic could
# time out, mis-parse, or exhaust its retry budget and let a turn through with
# no stamp. A hook-emitted stamp has no such failure mode.
#
# Mechanism: a Stop hook's PLAIN stdout is NOT shown to the user. Per the hooks
# reference, Claude Code writes hook stdout to the debug log and surfaces it
# only for UserPromptSubmit, UserPromptExpansion, SessionStart, and
# PostModelSwitch. Stop is not in that list, so the earlier `printf "$STAMP"`
# computed the stamp correctly but never displayed it. To surface text, a Stop
# hook must return JSON on stdout; we emit
#     {"systemMessage": "<stamp>"}
# which Claude Code shows to the user after the turn without blocking the stop.
#
# Deliberately NOT used:
#   - hookSpecificOutput.additionalContext — on Stop this CONTINUES the
#     conversation (same loop protections as decision:"block"), i.e. a retry loop.
#   - exit 2 / stderr — blocks the stop for the same reason.
#   - terminalSequence — OSC escapes only; invisible in non-terminal hosts.
#
# A Stop hook cannot edit the already-emitted assistant message, so the stamp
# renders as a system line after the turn rather than inside the message body.
#
# Never blocks the stop (always exit 0). Best-effort: any error -> silent exit 0.
# Intentionally `set -uo pipefail` WITHOUT `-e`: this hook must never abort a
# turn because of an internal failure.

set -uo pipefail

INPUT=$(cat)

# Anti-recursion: Stop hooks re-fire with stop_hook_active=true when a hook has
# continued the turn. On the re-fire, do nothing — the stamp is already emitted.
if printf '%s' "$INPUT" | grep -q '"stop_hook_active"[[:space:]]*:[[:space:]]*true'; then
    exit 0
fi

CWD=$(printf '%s' "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('cwd',''))" 2>/dev/null || echo "")
[ -z "$CWD" ] && CWD="$PWD"

# Resolve the branch from the session's cwd. Fall back to a bare timestamp
# (matching Rule 6: "or just the timestamp if not in a git repo").
BRANCH=$(git -C "$CWD" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
NOW=$(date '+%Y-%m-%d %H:%M:%S')
if [ -n "$BRANCH" ]; then
    STAMP="$NOW — $BRANCH"
else
    STAMP="$NOW"
fi

# Idempotency: if the assistant's own text already ends with a well-formed
# stamp, stay silent rather than showing a second one. Prefer the Stop input's
# last_assistant_message — the hooks reference warns the transcript file is not
# guaranteed to contain the final message at Stop time on all versions — and
# fall back to parsing transcript_path on hosts that omit that field.
LAST_TEXT=$(HOOK_INPUT="$INPUT" python3 <<'PYEOF' 2>/dev/null || echo ""
import os, json


def blocks_to_text(content):
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content
                 if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(p for p in parts if p)
    return content if isinstance(content, str) else ""


try:
    data = json.loads(os.environ.get("HOOK_INPUT", "") or "{}")
except Exception:
    data = {}

text = blocks_to_text(data.get("last_assistant_message", ""))

if not text.strip():
    transcript_path = data.get("transcript_path", "")
    if transcript_path:
        try:
            with open(transcript_path) as handle:
                for line in handle:
                    try:
                        entry = json.loads(line)
                    except Exception:
                        continue
                    if entry.get("role") != "assistant":
                        continue
                    content = entry.get(
                        "content", entry.get("message", {}).get("content", ""))
                    content = blocks_to_text(content)
                    if content.strip():
                        text = content
        except Exception:
            pass

print(text.strip())
PYEOF
)

# Already stamped? (tail line looks like "YYYY-MM-DD HH:MM:SS[ — branch]")
if [ -n "$LAST_TEXT" ] && printf '%s' "$LAST_TEXT" | tail -n 1 \
    | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}( — .+)?$'; then
    exit 0
fi

# Surface the stamp to the user as a Stop-hook systemMessage.
STAMP="$STAMP" python3 -c \
    'import json, os; print(json.dumps({"systemMessage": os.environ["STAMP"]}))' \
    2>/dev/null \
    || printf '{"systemMessage": "%s"}\n' "$(printf '%s' "$STAMP" | tr -d '"\\')"
exit 0
