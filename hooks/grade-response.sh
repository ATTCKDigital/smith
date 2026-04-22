#!/usr/bin/env bash
# grade-response.sh
# Event: Stop
# Scope: Main session only
#
# Grades the just-completed turn against the rubric in ~/.claude/CLAUDE.md.
# Exit 2 to block the stop and force a retry when score < 100.
# Capped at 3 retries per turn — after that, warn and pass.

set -uo pipefail

INPUT=$(cat)

# Anti-recursion: if this hook already blocked a stop, let it through now
if echo "$INPUT" | grep -q '"stop_hook_active"[[:space:]]*:[[:space:]]*true'; then
    exit 0
fi

SESSION_ID=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('session_id',''))" 2>/dev/null || echo "")
TRANSCRIPT_PATH=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('transcript_path',''))" 2>/dev/null || echo "")

if [ -z "$SESSION_ID" ] || [ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ]; then
    exit 0
fi

RETRY_FILE="/tmp/claude-grade-retry-${SESSION_ID}"
MAX_RETRIES=3
CLAUDE_MD="$HOME/.claude/CLAUDE.md"
RETRIES=$(cat "$RETRY_FILE" 2>/dev/null || echo 0)

# Extract last user message + last assistant turn (with tool calls) from JSONL transcript
TURN_DATA=$(TRANSCRIPT_PATH="$TRANSCRIPT_PATH" python3 <<'PYEOF' 2>/dev/null
import json, os
user_msg, assistant_turn = "", ""
with open(os.environ["TRANSCRIPT_PATH"]) as f:
    for line in f:
        try:
            entry = json.loads(line)
            if entry.get("role") == "user":
                content = entry.get("content", "")
                if isinstance(content, list):
                    content = " ".join(b.get("text","") for b in content if isinstance(b,dict))
                user_msg = content
            elif entry.get("role") == "assistant":
                assistant_turn = json.dumps(entry)
        except Exception:
            pass
print(json.dumps({"user": user_msg, "assistant": assistant_turn}))
PYEOF
)

LAST_USER=$(echo "$TURN_DATA" | python3 -c "import sys,json; print(json.load(sys.stdin)['user'])" 2>/dev/null || echo "")
LAST_ASSISTANT=$(echo "$TURN_DATA" | python3 -c "import sys,json; print(json.load(sys.stdin)['assistant'])" 2>/dev/null || echo "")

if [ -z "$LAST_ASSISTANT" ]; then
    exit 0
fi

# Call Haiku critic
RUBRIC=$(cat "$CLAUDE_MD")
PROMPT="You are a strict compliance critic. Score the assistant's last turn against the rubric.

<rubric>
$RUBRIC
</rubric>

<user_message>
$LAST_USER
</user_message>

<assistant_turn>
$LAST_ASSISTANT
</assistant_turn>

For each rule: does it apply to this turn? If not, auto-pass full weight. If it applies, did EVERY binary sub-criterion pass? (All-or-nothing.)

Return ONLY valid JSON, no prose:
{
  \"rule_scores\": [{\"rule\": 1, \"applies\": true, \"passed\": true, \"score\": 25, \"violations\": []}],
  \"total\": 100,
  \"blocking_violations\": []
}"

CRITIC_OUTPUT=$(echo "$PROMPT" | claude --model haiku -p 2>/dev/null || echo '{"total":100,"blocking_violations":[]}')

TOTAL=$(echo "$CRITIC_OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('total', 100))" 2>/dev/null || echo 100)
VIOLATIONS=$(echo "$CRITIC_OUTPUT" | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin).get('blocking_violations', [])))" 2>/dev/null || echo "[]")

if [ "$TOTAL" -ge 100 ]; then
    rm -f "$RETRY_FILE"
    exit 0
fi

if [ "$RETRIES" -ge "$MAX_RETRIES" ]; then
    echo "⚠ Grading retries exhausted ($MAX_RETRIES). Final: $TOTAL/100. Violations: $VIOLATIONS" >&2
    rm -f "$RETRY_FILE"
    exit 0
fi

echo $((RETRIES + 1)) > "$RETRY_FILE"
cat >&2 <<EOF
COMPLIANCE CHECK FAILED — Score: $TOTAL/100 (retry $((RETRIES + 1)) of $MAX_RETRIES)

Violations:
$VIOLATIONS

Regenerate your response correcting these violations. Same user prompt — but comply with the failed rules.
EOF
exit 2
