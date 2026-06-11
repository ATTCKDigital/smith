#!/usr/bin/env bash
# stamp-response.sh
# Event: Stop
# Scope: Main session only
#
# Deterministically appends a "YYYY-MM-DD HH:MM:SS — <branch-name>" stamp to
# the assistant's last turn when it is missing. This replaces the fail-open
# enforcement that previously lived in grade-response.sh / Rule 6: the Haiku
# critic could time out, mis-parse, or exhaust its retry budget and let a turn
# through with no stamp. A string-level append has no such failure mode.
#
# Mechanism: Stop hooks may emit additional assistant-visible context. We print
# the stamp to stdout, which Claude Code surfaces as a system message appended
# after the turn. The hook is a no-op when the transcript's last assistant text
# already ends with a well-formed stamp (idempotent across the anti-recursion
# re-fire below).
#
# Never blocks the stop (always exit 0). Best-effort: any error → silent exit 0.

set -uo pipefail

INPUT=$(cat)

# Anti-recursion: Stop hooks re-fire with stop_hook_active=true after they
# inject context. On the re-fire, do nothing — the stamp is already present.
if echo "$INPUT" | grep -q '"stop_hook_active"[[:space:]]*:[[:space:]]*true'; then
    exit 0
fi

TRANSCRIPT_PATH=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('transcript_path',''))" 2>/dev/null || echo "")
CWD=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('cwd',''))" 2>/dev/null || echo "")
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

# If the last assistant text already ends with a stamp, do nothing. Match the
# date prefix at the tail of the message to stay idempotent.
if [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ]; then
    LAST_TEXT=$(TRANSCRIPT_PATH="$TRANSCRIPT_PATH" python3 <<'PYEOF' 2>/dev/null
import json, os
text = ""
with open(os.environ["TRANSCRIPT_PATH"]) as f:
    for line in f:
        try:
            entry = json.loads(line)
            if entry.get("role") == "assistant":
                content = entry.get("content", entry.get("message", {}).get("content", ""))
                if isinstance(content, list):
                    parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                    content = "\n".join(p for p in parts if p)
                if isinstance(content, str) and content.strip():
                    text = content
        except Exception:
            pass
print(text.strip())
PYEOF
)
    # Already stamped? (tail line looks like "YYYY-MM-DD HH:MM:SS[ — branch]")
    if printf '%s' "$LAST_TEXT" | tail -n 1 | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}( — .+)?$'; then
        exit 0
    fi
fi

# Emit the stamp as appended context for the just-completed turn.
printf '%s\n' "$STAMP"
exit 0
