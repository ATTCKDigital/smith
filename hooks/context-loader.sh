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

# Bound the helper run.
#
# This used to build a `TIMEOUT_BIN` string from `timeout`/`gtimeout` and prefix
# the command with it. Stock macOS ships neither binary, so TIMEOUT_BIN expanded
# to nothing and the advertised 5s budget was not enforced at all — a hung helper
# hung this hook, on every single UserPromptSubmit.
#
# `timeout`/`gtimeout` are still preferred when present. Otherwise python3 —
# already a hard requirement, checked immediately above — supplies the bound
# in-process. Either way the caller's `|| true` below keeps the hook fail-open:
# a timeout is exit 124, an internal error 125, and neither stops the session.
run_bounded() {
    local secs="$1"; shift
    if command -v timeout >/dev/null 2>&1; then
        timeout "${secs}s" "$@"
    elif command -v gtimeout >/dev/null 2>&1; then
        gtimeout "${secs}s" "$@"
    else
        python3 -c 'import subprocess, sys
try:
    sys.exit(subprocess.run(sys.argv[2:], timeout=float(sys.argv[1])).returncode)
except subprocess.TimeoutExpired:
    sys.exit(124)
except Exception:
    sys.exit(125)' "$secs" "$@"
    fi
}

STDERR_TMP="$(mktemp 2>/dev/null || echo /tmp/context-loader-$$.err)"

# Pass the full stdin payload through to the helper.
printf '%s' "$INPUT" | run_bounded 5 python3 "$HELPER" compose-injection \
    2>"$STDERR_TMP" || true

if [ -s "$STDERR_TMP" ]; then
    cat "$STDERR_TMP" >> "$LOG_FILE" 2>/dev/null || true
fi
rm -f "$STDERR_TMP" 2>/dev/null || true

exit 0
