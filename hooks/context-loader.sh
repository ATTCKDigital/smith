#!/usr/bin/env bash
# context-loader.sh
# Event: UserPromptSubmit
# Matcher: * (no matcher; detection happens inside the script)
# Scope: Main session only (Claude Code does not fire UserPromptSubmit
#        for sub-agents).
#
# Detects Smith skill invocations (slash commands + natural-language
# triggers) and injects an `additionalContext` block containing:
#   - vault sections (sessions, ledger, bank, queue, agents) per the
#     resolved 4-tier context-manifest.json config
#   - manifest snapshot from .smith/index/manifest.md (when navigator
#     is enabled for the skill and the manifest exists)
#   - soft warning when the manifest is missing (once per session)
#
# Performance target: <5s p95.
#
# Sub-agent spawn strategy (v1): we DO NOT spawn /smith-navigate as a
# Haiku sub-agent from this hook. Nested `claude --print` invocations
# from inside a hook context are fragile, slow (cold start), and have
# unpredictable auth behavior. Instead the hook reads the manifest
# directly and inlines its contents (the manifest is already a curated
# index — the navigator's job is mainly to filter/categorize, which a
# more expensive interactive call can do when needed). The
# /smith-navigate skill remains fully usable for ad-hoc lookups in
# interactive sessions and is still called by /smith-explore Phase 1.

set -uo pipefail

INPUT=$(cat 2>/dev/null || echo '{}')

LOG_FILE="${HOME}/.smith/logs/hooks.log"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

log_line() {
    local ts
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '%s context-loader %s\n' "$ts" "$*" >> "$LOG_FILE" 2>/dev/null || true
}

# Cheap bash-side detection: bail fast for prompts with no Smith trigger so we
# don't pay python startup cost for every keystroke message.
PROMPT=$(printf '%s' "$INPUT" \
    | grep -o '"prompt"[[:space:]]*:[[:space:]]*"[^"]*"' \
    | head -1 \
    | sed 's/.*"prompt"[[:space:]]*:[[:space:]]*"\(.*\)".*/\1/' \
    || echo "")

PROMPT_LOWER=$(printf '%s' "$PROMPT" | tr '[:upper:]' '[:lower:]')

HAS_TRIGGER=0
# Slash commands.
case "$PROMPT" in
    *"/smith-"*) HAS_TRIGGER=1 ;;
esac
# Natural-language triggers (cheap fixed-string scan).
if [ $HAS_TRIGGER -eq 0 ]; then
    for phrase in \
        "let's smith this" \
        "lets smith this" \
        "start a smith workflow" \
        "kick off a new feature" \
        "let's build this" \
        "lets build this" \
        "start a new workflow" \
        "can you smith this" \
        "debug this" \
        "help me debug" \
        "something is broken" \
        "can you investigate" \
        "fix this" \
        "bugfix this" \
        "quick fix for" \
        "patch this" \
        "just fix" \
        "bank this idea" \
        "bank this for later" \
        "save this for later" \
        "come back to this" \
        "park this idea" \
        "stash this thought" \
        "deposit this"; do
        case "$PROMPT_LOWER" in
            *"$phrase"*) HAS_TRIGGER=1; break ;;
        esac
    done
fi

if [ $HAS_TRIGGER -eq 0 ]; then
    log_line "skill=null reason=no-trigger ms=0"
    exit 0
fi

# Resolve helper path.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HELPER=""
for cand in \
    "$SCRIPT_DIR/context-loader-lib.py" \
    "$HOME/.claude/hooks/context-loader-lib.py" \
    "$HOME/.smith/hooks/context-loader-lib.py"; do
    if [ -f "$cand" ]; then
        HELPER="$cand"
        break
    fi
done

if [ -z "$HELPER" ]; then
    log_line "status=skipped reason=no-helper"
    exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
    log_line "status=skipped reason=no-python3"
    exit 0
fi

TIMEOUT_BIN=""
if command -v timeout >/dev/null 2>&1; then
    TIMEOUT_BIN="timeout 5s"
elif command -v gtimeout >/dev/null 2>&1; then
    TIMEOUT_BIN="gtimeout 5s"
fi

STDERR_TMP="$(mktemp 2>/dev/null || echo /tmp/context-loader-$$.err)"

# Pass the full stdin payload through to the helper.
# shellcheck disable=SC2086
printf '%s' "$INPUT" | $TIMEOUT_BIN python3 "$HELPER" compose-injection \
    2>"$STDERR_TMP" || true

if [ -s "$STDERR_TMP" ]; then
    cat "$STDERR_TMP" >> "$LOG_FILE" 2>/dev/null || true
fi
rm -f "$STDERR_TMP" 2>/dev/null || true

exit 0
