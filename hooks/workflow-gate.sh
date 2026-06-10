#!/usr/bin/env bash
# workflow-gate.sh
# Event: PreToolUse
# Matchers: Bash, Write|Edit
# Scope: Universal — fires in both main session and sub-agents
#
# Hard, tool-layer enforcement of Smith's workflow discipline. Denies any
# file-modifying tool call unless a Smith workflow marker exists at
# <project>/.smith/vault/active-workflows/*.yaml.
#
# Markers are created by the four top-level workflow skills (smith-new,
# smith-bugfix, smith-debug, smith-build) plus the smith bootstrap and
# smith-finish utility skills, and removed by clear-active-workflow.sh
# or the active-workflow-janitor.sh sweep.
#
# Exemptions:
#   - Smith not installed at all (no .smith/ directory) → exit silently.
#     Bootstrap and non-Smith projects are not our place to gate.
#   - Vault-internal writes to known-safe subdirectories under
#     .smith/vault/{sessions,bank,ledger,queue,agents,todo,reports,
#     index,audits}. active-workflows/ is NOT exempt (prevents forged
#     markers from bypassing the gate).
#   - Read-only Bash commands.
#
# Layers AFTER security-guard-bash.sh / security-guard-files.sh — security
# blocks take precedence (the deny message users see is the more important
# one).

set -uo pipefail

INPUT=$(cat)

# ---------- extract tool name + relevant input fields ----------

TOOL_NAME=$(echo "$INPUT" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data.get('tool_name', ''))
" 2>/dev/null || echo "")

if [ -z "$TOOL_NAME" ]; then
    exit 0
fi

case "$TOOL_NAME" in
    Bash|Write|Edit|NotebookEdit) ;;
    *) exit 0 ;;
esac

# ---------- locate project + check Smith install ----------
#
# Subagent contexts (Smith's bread and butter — every workflow spawns them
# in worktrees) inherit a $PWD pointing at the worktree, and $CLAUDE_PROJECT_DIR
# is unset. The active-workflow marker lives in the PRIMARY repo's
# .smith/vault/, not the worktree. Use git's own resolution to walk back:
# `git rev-parse --git-common-dir` returns the primary repo's `.git` from
# inside a worktree (and `.git` from the primary repo itself). Its dirname
# is the primary repo root. Falls back to the literal PWD outside git.

RESOLVED_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
GIT_COMMON_DIR=$(git -C "$RESOLVED_DIR" rev-parse --git-common-dir 2>/dev/null || true)
if [ -n "$GIT_COMMON_DIR" ]; then
    case "$GIT_COMMON_DIR" in
        /*) PROJECT_DIR=$(dirname "$GIT_COMMON_DIR") ;;
        *)  PROJECT_DIR=$(cd "$RESOLVED_DIR" && cd "$(dirname "$GIT_COMMON_DIR")" 2>/dev/null && pwd) ;;
    esac
    : "${PROJECT_DIR:=$RESOLVED_DIR}"
else
    PROJECT_DIR="$RESOLVED_DIR"
fi

# Q1-A path: no .smith/ at all → not a Smith project; exit silently.
if [ ! -d "$PROJECT_DIR/.smith" ]; then
    exit 0
fi

# ---------- marker existence check ----------

ACTIVE_DIR="$PROJECT_DIR/.smith/vault/active-workflows"
MARKER_PRESENT=0
if [ -d "$ACTIVE_DIR" ]; then
    # Use a glob expansion with nullglob semantics via shopt
    shopt -s nullglob
    markers=( "$ACTIVE_DIR"/*.yaml )
    shopt -u nullglob
    if [ "${#markers[@]}" -gt 0 ]; then
        MARKER_PRESENT=1
    fi
fi

if [ "$MARKER_PRESENT" = "1" ]; then
    exit 0
fi

# ---------- no marker; decide whether to deny based on the tool ----------

SAFE_VAULT_DIRS=(sessions bank ledger queue agents todo reports index audits)
# Per spec/31-workflow-gate-bootstrap (Q4 answer A): a parallel exemption
# list for .smith/index/ subdirs. /smith-index --describe writes to
# .smith/index/files/*.meta and shouldn't need a marker — it's a
# maintenance command, not a workflow. Keeping this distinct from
# SAFE_VAULT_DIRS preserves the semantic split (vault = workflow state,
# index = structural metadata).
SAFE_INDEX_DIRS=(files systems config logs)

# Helper: is a path under one of the safe vault subdirs?
is_safe_vault_path() {
    local file_path="$1"
    # Normalize to absolute path relative to project if relative
    case "$file_path" in
        /*) ;;
        *) file_path="$PROJECT_DIR/$file_path" ;;
    esac
    # Must be under .smith/vault/
    local vault_prefix="$PROJECT_DIR/.smith/vault/"
    case "$file_path" in
        "$vault_prefix"*)
            local rest="${file_path#$vault_prefix}"
            local first_seg="${rest%%/*}"
            for safe in "${SAFE_VAULT_DIRS[@]}"; do
                if [ "$first_seg" = "$safe" ]; then
                    return 0
                fi
            done
            ;;
    esac
    return 1
}

# Helper: is a path under one of the safe .smith/index/ subdirs?
# Per spec/31-workflow-gate-bootstrap §B1.
is_safe_index_path() {
    local file_path="$1"
    case "$file_path" in
        /*) ;;
        *) file_path="$PROJECT_DIR/$file_path" ;;
    esac
    local index_prefix="$PROJECT_DIR/.smith/index/"
    case "$file_path" in
        "$index_prefix"*)
            local rest="${file_path#$index_prefix}"
            local first_seg="${rest%%/*}"
            for safe in "${SAFE_INDEX_DIRS[@]}"; do
                if [ "$first_seg" = "$safe" ]; then
                    return 0
                fi
            done
            ;;
    esac
    return 1
}

# Helper: emit Q4-C deny response and exit
DENY_BODY_HEADER="SMITH WORKFLOW-GATE: No active Smith workflow.

To edit files, start a workflow first:
  • /smith-new    — new feature
  • /smith-bugfix — quick fix
  • /smith-debug  — investigate

Smith enforces workflow-scoped edits to keep changes spec-driven."

deny() {
    local appendix="$1"
    local reason="$DENY_BODY_HEADER

($appendix)"

    # Log the block to the hooks log
    local log_dir="$HOME/.smith/logs"
    mkdir -p "$log_dir" 2>/dev/null || true
    local log_file="$log_dir/hooks.log"
    {
        printf '[%s] workflow-gate DENY tool=%s project=%s appendix=%s\n' \
            "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" "$TOOL_NAME" "$PROJECT_DIR" "$appendix"
    } >> "$log_file" 2>/dev/null || true

    # Emit Claude Code hook deny response
    python3 -c "
import json, sys
print(json.dumps({
    'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': 'deny',
        'permissionDecisionReason': '''$reason'''
    }
}))
" 2>/dev/null || cat << EOF
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "$reason"
  }
}
EOF
    exit 0
}

# ---------- per-tool decision ----------

case "$TOOL_NAME" in
    Write|Edit|NotebookEdit)
        FILE_PATH=$(echo "$INPUT" | python3 -c "
import sys, json
data = json.load(sys.stdin)
ti = data.get('tool_input', {})
print(ti.get('file_path', ti.get('notebook_path', '')))
" 2>/dev/null || echo "")

        # Allow vault-internal writes regardless of marker
        if [ -n "$FILE_PATH" ] && is_safe_vault_path "$FILE_PATH"; then
            exit 0
        fi

        # Allow .smith/index/ writes (maintenance commands; per
        # spec/31-workflow-gate-bootstrap §B1).
        if [ -n "$FILE_PATH" ] && is_safe_index_path "$FILE_PATH"; then
            exit 0
        fi

        if [ -n "$FILE_PATH" ]; then
            deny "Blocked write to: $FILE_PATH"
        else
            deny "Blocked write (file_path unknown)"
        fi
        ;;

    Bash)
        COMMAND=$(echo "$INPUT" | python3 -c "
import sys, json
data = json.load(sys.stdin)
ti = data.get('tool_input', {})
print(ti.get('command', ''))
" 2>/dev/null || echo "")

        if [ -z "$COMMAND" ]; then
            exit 0
        fi

        # Exempt the marker-creation helper. This is the ONE auditable
        # entrypoint for marker creation; the bootstrap chicken-and-egg
        # that bit PRs #25/#27/#28/#29/#30 is resolved by allowing this
        # exact basename through regardless of marker presence.
        # Anchor: must be preceded by whitespace or '/', followed by
        # whitespace or end-of-string. That rejects e.g.
        # `cat > create-active-workflow.sh` (the '>' interposes
        # whitespace but the basename is followed by '"' or EOF in
        # that pattern, not the required boundary) while accepting
        # `bash /path/to/create-active-workflow.sh ...` and
        # `~/.smith/scripts/create-active-workflow.sh ...`.
        if printf '%s' "$COMMAND" | grep -qE '(^|[[:space:]/])create-active-workflow\.sh([[:space:]]|$)'; then
            exit 0
        fi

        # Build a redirect-test copy of COMMAND with the CONTENTS of quoted
        # spans blanked out, so a '>' that lives inside '...' or "..." (a git
        # trailer like <a@b.com>, an echo banner, a --format string) is not
        # mistaken for a shell redirect. Real redirects (foo > bar) keep their
        # '>' OUTSIDE quotes and still trip the check below.
        #
        # FAIL-SAFE: the stripper is conservative. If quoting is unbalanced or
        # otherwise ambiguous, it returns the command UNCHANGED, so the raw
        # text is tested and we fall back to the original (blocking) behavior.
        # Worst case is a false block, never a missed real redirect.
        REDIR_TEST=$(printf '%s' "$COMMAND" | python3 -c '
import sys
s = sys.stdin.read()
out = []
i = 0
n = len(s)
quote = None  # None, "\x27" (single), or "\x22" (double)
ok = True
while i < n:
    c = s[i]
    if quote is None:
        if c == "\x27" or c == "\x22":
            quote = c
            out.append(" ")  # blank the opening quote
        else:
            out.append(c)
    else:
        # Inside a quote. Single quotes are literal in shell (no escapes).
        # Double quotes allow backslash-escapes; treat \\X as two blanked chars.
        if c == "\\" and quote == "\x22" and i + 1 < n:
            out.append("  ")
            i += 2
            continue
        if c == quote:
            quote = None
            out.append(" ")  # blank the closing quote
        else:
            out.append(" ")  # blank the quoted content
    i += 1
if quote is not None:
    ok = False  # unterminated quote → ambiguous
# On any ambiguity, hand back the ORIGINAL so the raw text is tested (block).
sys.stdout.write("".join(out) if ok else s)
' 2>/dev/null || printf '%s' "$COMMAND")
        # If python3 was unavailable, REDIR_TEST falls back to the raw command.
        if [ -z "$REDIR_TEST" ]; then
            REDIR_TEST="$COMMAND"
        fi

        # Identify the first file-touching subcommand, if any.
        # Word-boundary check against known mutators; also detect `sed -i`
        # and unescaped shell write-redirection that isn't a stderr-only
        # redirection (2> or 2>>).
        MATCHED_SUBCMD=""

        # Mutator command words (whole-word match).
        for cmd in rm rmdir mv cp chmod chown touch truncate tee dd; do
            if printf '%s' "$COMMAND" | grep -qE "(^|[ 	;|&\(])${cmd}([ 	]|$)"; then
                MATCHED_SUBCMD="$cmd"
                break
            fi
        done

        # sed -i (in-place edit)
        if [ -z "$MATCHED_SUBCMD" ]; then
            if printf '%s' "$COMMAND" | grep -qE '(^|[ 	;|&\(])sed[ 	]+(-[a-zA-Z]*i|--in-place)'; then
                MATCHED_SUBCMD="sed -i"
            fi
        fi

        # Shell redirection: > or >> but NOT 2> or 2>>. Also accept &>.
        # Tested against REDIR_TEST (quoted spans blanked) so a '>' inside a
        # quoted string is not a false positive; a real redirect survives.
        if [ -z "$MATCHED_SUBCMD" ]; then
            if printf '%s' "$REDIR_TEST" | grep -qE '(^|[^0-9&])>>?[^&|]'; then
                # Subtract stderr-only redirections.
                # Strip 2> 2>> from a copy and re-check.
                stripped=$(printf '%s' "$REDIR_TEST" | sed -E 's/2>>?//g')
                if printf '%s' "$stripped" | grep -qE '(^|[^0-9&])>>?[^&|]'; then
                    MATCHED_SUBCMD="redirection (>, >>)"
                fi
            fi
            # Match combined-stream redirect: &>
            if [ -z "$MATCHED_SUBCMD" ] && printf '%s' "$REDIR_TEST" | grep -qE '&>'; then
                MATCHED_SUBCMD="redirection (&>)"
            fi
        fi

        if [ -z "$MATCHED_SUBCMD" ]; then
            # Read-only / non-file-touching Bash → allow.
            exit 0
        fi

        # Trim COMMAND for the deny message if very long
        DISPLAY_CMD="$COMMAND"
        if [ ${#DISPLAY_CMD} -gt 200 ]; then
            DISPLAY_CMD="${DISPLAY_CMD:0:200}..."
        fi
        deny "Blocked subcommand: $MATCHED_SUBCMD in command \"$DISPLAY_CMD\""
        ;;
esac

exit 0
