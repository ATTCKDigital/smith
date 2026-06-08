#!/usr/bin/env bash
# user-prompt-logger.sh
# Event: UserPromptSubmit
# Matcher: * (no matcher; logging is unconditional)
# Scope: Main session only — Claude Code does not fire UserPromptSubmit for
#        sub-agents (see context-loader.sh header). So only genuine human
#        prompts in the main session are captured.
#
# Appends the user's verbatim prompt to the current session log, timestamped,
# interleaved chronologically with metrics-tracker.sh's tool-call lines. Gives
# team leads a shared, readable record of what teammates asked the agent to do —
# the prompts that previously lived only in Claude Code's per-user, non-shared
# global JSONL transcripts.
#
# PRIVACY NOTE (intentional): prompts are stored VERBATIM and FULL — including
# anything a user pastes (which may contain secrets). This is an accepted risk
# for internal team repos where session logs are team-shared via /smith-sync.
# Do NOT add redaction or truncation without a spec change (see
# specs/42-prompt-logger/spec.md NG2/A3).
#
# Mirrors metrics-tracker.sh: resolve .current-session, no-op if the vault is
# not initialized, parse with python3 (not sed) so multi-line / quoted /
# Unicode prompts survive intact, append, always exit 0.

set -uo pipefail

INPUT=$(cat 2>/dev/null || echo '{}')

VAULT_DIR="${CLAUDE_PROJECT_DIR:-.}/.smith/vault"
CURRENT_SESSION_FILE="$VAULT_DIR/.current-session"

# Vault not initialized / no active session → no-op, never an error.
[ -f "$CURRENT_SESSION_FILE" ] || exit 0
SESSION_FILE=$(cat "$CURRENT_SESSION_FILE" 2>/dev/null || echo "")
[ -n "$SESSION_FILE" ] && [ -f "$SESSION_FILE" ] || exit 0

# Build the block in python so the verbatim prompt (newlines, quotes, unicode)
# survives. A bash/sed extraction (as in context-loader.sh) would truncate at
# the first '"' and collapse newlines — unacceptable for a verbatim record.
BLOCK=$(HOOK_INPUT="$INPUT" python3 2>/dev/null <<'PYEOF'
import os
import sys
import json
from datetime import datetime, timezone

try:
    data = json.loads(os.environ.get('HOOK_INPUT', '{}'))
except json.JSONDecodeError:
    sys.exit(0)

prompt = data.get('prompt', '')
if not isinstance(prompt, str) or not prompt.strip():
    sys.exit(0)

ts = datetime.now(timezone.utc).strftime('%H:%M:%S')

# Blockquote every line so a multi-line prompt renders as one contiguous quote.
# Blank lines become a bare '>' so the blockquote does not break.
body = "\n".join(("> " + ln) if ln else ">" for ln in prompt.split("\n"))

print("\n### [{}] User prompt\n\n{}\n".format(ts, body))
PYEOF
)

# Python exits silently on empty/whitespace prompts and JSON errors.
[ -z "$BLOCK" ] && exit 0

printf '%s\n' "$BLOCK" >> "$SESSION_FILE"

exit 0
