#!/usr/bin/env bash
# task-router.sh
# Event: UserPromptSubmit
# Scope: Main session only (NOT sub-agents — prevents recursive delegation)
#
# Classifies user messages and injects routing guidance via additionalContext
# ONLY when an active Smith workflow is in progress (.smith/vault/.active-workflow).
# During regular conversation (no workflow), exits immediately with no overhead.
# Manual prefixes (haiku:, sonnet:, opus:, direct:) always work regardless.

set -uo pipefail

INPUT=$(cat)

# Extract user message using python3 for reliable JSON parsing
MESSAGE=$(echo "$INPUT" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data.get('message', data.get('content', '')))
" 2>/dev/null || echo "")

if [ -z "$MESSAGE" ]; then
    exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
ACTIVE_WORKFLOW="$PROJECT_DIR/.smith/vault/.active-workflow"

# Check for manual prefixes first — these work regardless of workflow state
# Use python3 for reliable prefix detection
OVERRIDE_RESULT=$(python3 -c "
msg = '''$MESSAGE'''
for model in ['haiku', 'sonnet', 'opus', 'direct']:
    if msg.lower().startswith(model + ':') or msg.lower().startswith(model + ' :'):
        stripped = msg[len(model)+1:].lstrip(' :')
        print(f'{model}|{stripped}')
        break
else:
    print('none|')
" 2>/dev/null || echo "none|")

MODEL_OVERRIDE="${OVERRIDE_RESULT%%|*}"

# direct: prefix — pass through with no routing, no classification
if [ "$MODEL_OVERRIDE" = "direct" ]; then
    exit 0
fi

# Model override prefixes (haiku:, sonnet:, opus:) — route to specified model
if [ "$MODEL_OVERRIDE" != "none" ]; then
    STRIPPED_MESSAGE="${OVERRIDE_RESULT#*|}"
    # Escape for JSON
    ESCAPED_MSG=$(echo "$STRIPPED_MESSAGE" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read().strip())[1:-1])" 2>/dev/null || echo "$STRIPPED_MESSAGE")
    cat << EOJSON
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "SMITH ROUTING: Manual override — user specified $MODEL_OVERRIDE. Handle this directly or delegate to a $MODEL_OVERRIDE sub-agent as appropriate. Original message (prefix stripped): $ESCAPED_MSG"
  }
}
EOJSON
    exit 0
fi

# Skip classification for /smith actions and slash commands
if echo "$MESSAGE" | grep -qE '^\s*/'; then
    exit 0
fi

# Numbered response to a question's follow-up options — treat as command, pass through
if echo "$MESSAGE" | grep -qE '^\s*[1-9]\s*$|^\s*(do|yes|go with|let.s do|pick)\s+(option\s+)?[1-9]'; then
    exit 0
fi

# Bank triggers — handle in main session, never delegate
if echo "$MESSAGE" | grep -qiE '(bank this|save this for later|come back to this|park this idea|stash this thought|deposit this)'; then
    exit 0
fi

# ============================================================
# DEBUG INTENT DETECTION: Suggest /smith-debug for error reports
# Runs ALWAYS (not gated by active workflow) — fast local check.
# Catches messages that describe errors/failures before the
# question detector would swallow them as pure questions.
# ============================================================
IS_DEBUG=$(python3 -c "
import re, sys
msg = '''${MESSAGE}'''.strip()
lower = msg.lower()

# Skip if message starts with an imperative verb (user wants action, not diagnosis)
imperative = re.match(r'^\s*(fix|build|create|update|add|remove|delete|implement|refactor|run|start|stop|deploy|install|merge|push|commit|write|edit|move|rename|copy|migrate|ship|generate|set up|configure|enable|disable)\b', lower)
if imperative:
    print('no')
    sys.exit(0)

# Debug intent signals — error descriptions, failure reports, investigation requests
debug_patterns = [
    r'(i\'m|i am)\s+(getting|seeing|having|experiencing)\s+(this|an?|the)?\s*(error|issue|problem|failure|exception|crash)',
    r'(error|errno|exception|traceback|stack\s*trace|connection\s*refused|timeout|502|503|500)\b',
    r'(something|things?)\s+(is|are)\s+(broken|failing|not working|down)',
    r'(why|how come)\s+(is|does|did|are|do)\s+.*(fail|crash|error|break|refuse|timeout|hang|stuck)',
    r'(help|can you help)\s+(me\s+)?(debug|diagnose|investigate|figure out|troubleshoot)',
    r'(debug|diagnose|investigate|troubleshoot)\s+this',
    r'(keeps?\s+(failing|crashing|erroring|timing out|refusing))',
    r'(not\s+(responding|working|connecting|starting|loading))',
    r'\[Errno\b',
    r'(failed|failure)\s+(to|with|when|during)',
]

for pat in debug_patterns:
    if re.search(pat, lower):
        print('yes')
        sys.exit(0)

print('no')
" 2>/dev/null || echo "no")

if [ "$IS_DEBUG" = "yes" ]; then
    cat << EOJSON
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "SMITH: This message describes an error or unexpected behavior. Suggest running /smith-debug to systematically investigate. Present the suggestion like:\n\nThis sounds like it could benefit from a structured investigation. Would you like me to:\n[1] Run /smith-debug to systematically diagnose this (recommended)\n[2] Just answer the question without a full investigation\n\nWait for the user to choose before taking action. If they pick [1], invoke /smith-debug with the conversation context as the symptom description."
  }
}
EOJSON
    exit 0
fi

# ============================================================
# QUESTION DETECTION: Enforce "questions are not action requests"
# Runs ALWAYS (not gated by active workflow) — fast local check.
# ============================================================
IS_QUESTION=$(python3 -c "
import re, sys
msg = '''${MESSAGE}'''.strip()
lower = msg.lower()

# Skip if message starts with an imperative verb (it's a command, not a question)
imperative = re.match(r'^\s*(fix|build|create|update|add|remove|delete|implement|refactor|run|start|stop|deploy|install|merge|push|commit|write|edit|move|rename|copy|migrate|ship|generate|set up|configure|enable|disable)\b', lower)
if imperative:
    print('no')
    sys.exit(0)

# Question-word starters
question_starters = [
    r'^can\s+we\b', r'^does\b', r'^is\s+there\b', r'^how\s+does\b',
    r'^what\s+if\b', r'^would\s+it\b', r'^could\s+we\b', r'^is\s+it\s+possible\b',
    r'^should\s+we\b', r'^what\s+happens?\s+if\b', r'^do\s+we\b', r'^do\s+you\b',
    r'^are\s+there\b', r'^have\s+we\b', r'^has\b', r'^why\b', r'^where\b',
    r'^when\b', r'^which\b', r'^who\b', r'^how\s+(many|much|long|often)\b',
    r'^can\s+(you|i|it)\b', r'^could\s+(you|i|it)\b', r'^would\b',
    r'^will\b', r'^shall\b', r'^what\s+(is|are|was|were|do|does)\b',
    r'^how\s+(is|are|do|does|can|could|would|should)\b',
]
for pat in question_starters:
    if re.match(pat, lower):
        print('yes')
        sys.exit(0)

# Contains a question mark but no imperative verb
if '?' in msg and not imperative:
    print('yes')
    sys.exit(0)

print('no')
" 2>/dev/null || echo "no")

if [ "$IS_QUESTION" = "yes" ]; then
    cat << EOJSON
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "SMITH: This is a QUESTION, not a command. Answer the question only. Do NOT modify any files, run any commands, or take any action. After answering, suggest 2-3 optional follow-up actions the user might want, formatted as a numbered list like:\n\nWould you like me to:\n[1] <action option>\n[2] <action option>\n[3] <action option>\n\nWait for the user to select an option or give a different instruction before taking any action."
  }
}
EOJSON
    exit 0
fi

# ============================================================
# WORKFLOW GATE: Only classify if an active Smith workflow exists.
# No workflow = no Haiku API call = instant pass-through.
# ============================================================
if [ ! -f "$ACTIVE_WORKFLOW" ]; then
    exit 0
fi

# Check for image paths in the message
IMAGE_PATH=""
if echo "$MESSAGE" | grep -qiE '\.(png|jpg|jpeg|gif|webp|svg)\b'; then
    IMAGE_PATH=$(echo "$MESSAGE" | grep -oiE '[a-zA-Z0-9_./ -]+\.(png|jpg|jpeg|gif|webp|svg)' | head -1 | sed 's/^[[:space:]]*//')
fi

# Classify with Haiku API call
# Escape the message for safe embedding in the prompt
ESCAPED_FOR_PROMPT=$(echo "$MESSAGE" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read().strip())[1:-1])" 2>/dev/null || echo "$MESSAGE")

CLASSIFICATION=$(claude --model haiku -p "Classify this user message into exactly one category. Respond with ONLY the category name on a single line, nothing else.

Categories:
- simple-question: A quick factual question answerable from existing knowledge or a brief file read
- explore: Searching, navigating, or investigating the codebase without making changes
- docs: Writing or updating documentation, specs, README files, or other prose
- review: Reviewing existing code for quality, security, performance, or correctness
- implement: Writing new code, modifying existing code, building features, or refactoring
- debug: Investigating bugs, analyzing errors, tracing issues, examining screenshots or logs
- plan: Designing architecture, making structural decisions, planning implementations
- smith-action: The message invokes a /smith command or uses a natural language trigger for one

Message: \"$ESCAPED_FOR_PROMPT\"" 2>/dev/null | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')

# Normalize classification — handle slight variations
case "$CLASSIFICATION" in
    simple-question|simplequestion|simple_question) CLASSIFICATION="simple-question" ;;
    smith-action|smithaction|smith_action) CLASSIFICATION="smith-action" ;;
    explore|search|find|navigate) CLASSIFICATION="explore" ;;
    docs|documentation|doc) CLASSIFICATION="docs" ;;
    review|audit|check) CLASSIFICATION="review" ;;
    implement|build|code|refactor) CLASSIFICATION="implement" ;;
    debug|fix|investigate|error) CLASSIFICATION="debug" ;;
    plan|design|architect|architecture) CLASSIFICATION="plan" ;;
    *) CLASSIFICATION="simple-question" ;;  # Default: pass through
esac

# Override to debug if image path detected
if [ -n "$IMAGE_PATH" ] && [ "$CLASSIFICATION" != "debug" ]; then
    CLASSIFICATION="debug"
fi

# Simple questions and smith actions pass through — no routing needed
case "$CLASSIFICATION" in
    simple-question|smith-action)
        exit 0
        ;;
esac

# Map classification to target model
case "$CLASSIFICATION" in
    explore)           TARGET_MODEL="haiku" ;;
    docs|review)       TARGET_MODEL="sonnet" ;;
    implement|debug|plan) TARGET_MODEL="opus" ;;
    *)                 exit 0 ;;
esac

# Build vault context injection hint based on task type
CONTEXT_HINT=""
case "$CLASSIFICATION" in
    explore)   CONTEXT_HINT="Inject recent session log entries about the files or systems being explored." ;;
    implement) CONTEXT_HINT="Inject recent explore and plan findings from the vault." ;;
    debug)     CONTEXT_HINT="Inject previous IMG-XXX findings if this is a follow-up screenshot analysis." ;;
    review)    CONTEXT_HINT="Inject recent implementation changes from the vault." ;;
    docs)      CONTEXT_HINT="Inject recent spec changes and implementation decisions from the vault." ;;
    plan)      CONTEXT_HINT="Inject relevant system specs and recent explore findings from the vault." ;;
esac

# Build image-specific instructions if an image path was detected
IMAGE_HINT=""
if [ -n "$IMAGE_PATH" ]; then
    IMAGE_HINT=" Image file detected at $IMAGE_PATH. Assign sub-agent identifier IMG-XXX based on next available number in .smith/vault/agents/image-analysis/."
fi

# Output routing instruction via additionalContext
cat << EOJSON
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "SMITH ROUTING: Task classified as $CLASSIFICATION. Delegate to a sub-agent using model=$TARGET_MODEL. $CONTEXT_HINT$IMAGE_HINT The sub-agent should write findings back to the vault. Return only the sub-agent summary to this session. Log this routing decision to the vault session log with format: ### [HH:MM:SS] Task routed / **User request:** <summary> / **Classification:** $CLASSIFICATION / **Routed to:** $TARGET_MODEL sub-agent"
  }
}
EOJSON

exit 0
