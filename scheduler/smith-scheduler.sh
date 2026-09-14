#!/usr/bin/env bash
# smith-scheduler.sh
#
# Daily queue processor for Smith — THIN LAUNCHER.
#
# Iterates every project registered in ~/.smith/projects.json, filters each
# project's .smith/vault/queue/ for autonomous tasks that are ready to run
# (priority-ordered, dependencies met, scheduled_for <= today), then delegates
# each selected task to the /smith-queue skill via:
#
#     "$CLAUDE_BIN" --model <model> --permission-mode bypassPermissions \
#         -p "/smith-queue process <filename>"
#
# The skill owns the full pipeline (status updates, git worktree, tests,
# PR, merge, spec updates, history archival). This script does NOT
# reimplement any of those steps — if the skill's behavior changes, the
# scheduler inherits it for free.
#
# Intended to run under macOS launchd once daily at 2:00 AM (see
# scheduler/com.smith.scheduler.plist.template). Can also run manually:
#     SMITH_SCHEDULER_ENABLED=1 bash ~/.smith/scheduler/smith-scheduler.sh
#
# Environment variables
#   SMITH_SCHEDULER_ENABLED   required=1 — kill switch; exits silently otherwise
#   SMITH_SCHEDULER_DRY_RUN   =1 to log planned dispatches without invoking claude
#   SMITH_SCHEDULER_MODEL     model for claude invocations (default: sonnet)
#   CLAUDE_BIN                explicit path to the claude CLI (skips auto-resolve)
#   SMITH_AUDIT_DISPATCH_DRY_RUN  =1 to log planned scheduled-audit dispatches
#                                 without invoking claude — independent of
#                                 SMITH_SCHEDULER_DRY_RUN, which only gates
#                                 the queue step above (see "Audits step"
#                                 below)

set -uo pipefail

SMITH_DIR="$HOME/.smith"
PROJECTS_FILE="$SMITH_DIR/projects.json"
LOG_FILE="$SMITH_DIR/scheduler/scheduler.log"
TODAY=$(date +"%Y-%m-%d")
DRY_RUN="${SMITH_SCHEDULER_DRY_RUN:-0}"
CLAUDE_MODEL="${SMITH_SCHEDULER_MODEL:-sonnet}"

log() {
    echo "[$(date -u +"%Y-%m-%d %H:%M:%S")] $1" >> "$LOG_FILE"
}

mkdir -p "$(dirname "$LOG_FILE")"
touch "$LOG_FILE"

# SAFETY GUARD: require explicit opt-in. Acts as a soft uninstall for the
# launchd agent without needing `launchctl unload`. To re-enable, invoke with:
#   SMITH_SCHEDULER_ENABLED=1 bash ~/.smith/scheduler/smith-scheduler.sh
if [ "${SMITH_SCHEDULER_ENABLED:-0}" != "1" ]; then
    log "=== Scheduler disabled (SMITH_SCHEDULER_ENABLED != 1) — exiting ==="
    exit 0
fi

# Resolve an absolute path to the `claude` binary. launchd runs with a minimal
# PATH that does not include Homebrew, nvm, or the Claude Code app bundle,
# which caused prior runs to fail with "claude: command not found" while the
# script still reported tasks as "Completed" (because $? was masked by `|| true`).
resolve_claude_bin() {
    if [ -n "${CLAUDE_BIN:-}" ] && [ -x "$CLAUDE_BIN" ]; then
        echo "$CLAUDE_BIN"
        return 0
    fi
    if command -v claude >/dev/null 2>&1; then
        command -v claude
        return 0
    fi
    local vm_root="$HOME/Library/Application Support/Claude/claude-code-vm"
    if [ -f "$vm_root/.sdk-version" ]; then
        local version
        version=$(tr -d '[:space:]' < "$vm_root/.sdk-version")
        if [ -x "$vm_root/$version/claude" ]; then
            echo "$vm_root/$version/claude"
            return 0
        fi
    fi
    return 1
}

# is_audit_due <now_date YYYY-MM-DD> <last_run_date-or-empty> <cadence_days>
# Prints "1" (due) or "0" (not due) to stdout. Pure function — no file I/O,
# no globals read/written — so tests/scheduler/ can exercise every branch
# without a filesystem fixture. Used by the audits step below.
is_audit_due() {
    local now="$1" last="$2" cadence="$3"
    [ -z "$last" ] && { echo 1; return; }   # never run → due
    local now_epoch last_epoch
    now_epoch=$(date -j -f "%Y-%m-%d" "$now" +%s 2>/dev/null || date -d "$now" +%s)
    last_epoch=$(date -j -f "%Y-%m-%d" "$last" +%s 2>/dev/null || date -d "$last" +%s)
    local days=$(( (now_epoch - last_epoch) / 86400 ))
    [ "$days" -ge "$cadence" ] && echo 1 || echo 0
}

if ! CLAUDE_BIN=$(resolve_claude_bin); then
    log "=== ERROR: cannot locate claude binary — aborting ==="
    exit 1
fi
log "Using claude binary: $CLAUDE_BIN"

log "=== Daily scheduler run started (dry_run=$DRY_RUN, model=$CLAUDE_MODEL) ==="

if [ ! -f "$PROJECTS_FILE" ]; then
    log "No projects.json found at $PROJECTS_FILE — nothing to do"
    exit 0
fi

PROJECT_PATHS=$(grep '"path"' "$PROJECTS_FILE" | sed 's/.*"path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')

if [ -z "$PROJECT_PATHS" ]; then
    log "No projects registered — nothing to do"
    exit 0
fi

TOTAL_DISPATCHED=0
TOTAL_FAILED=0
TOTAL_SKIPPED=0

while IFS= read -r vault_path; do
    QUEUE_DIR="$vault_path/queue"

    if [ ! -d "$QUEUE_DIR" ]; then
        continue
    fi

    # vault_path is always <project-root>/.smith/vault — strip that suffix to
    # get the project root. Two levels up via `dirname dirname` works too but
    # is fragile if someone relocates the vault; the suffix form is explicit.
    PROJECT_DIR="${vault_path%/.smith/vault}"
    PROJECT_NAME=$(basename "$PROJECT_DIR")

    log "Scanning project: $PROJECT_NAME ($QUEUE_DIR)"

    # Collect all processable tasks with their priority for sorting.
    TASK_LIST=""

    for queue_file in "$QUEUE_DIR"/*.md; do
        [ -f "$queue_file" ] || continue
        [ "$(basename "$queue_file")" = ".batch-progress.md" ] && continue

        STATUS=$(grep '^status:' "$queue_file" | head -1 | sed 's/status:[[:space:]]*//' | tr -d '"' | tr -d ' ')
        COMPLEXITY=$(grep '^complexity:' "$queue_file" | head -1 | sed 's/complexity:[[:space:]]*//' | tr -d '"' | tr -d ' ')

        # Only process autonomous tasks that are pending or scheduled.
        if [ "$COMPLEXITY" != "autonomous" ]; then
            continue
        fi
        if [ "$STATUS" != "pending" ] && [ "$STATUS" != "scheduled" ]; then
            continue
        fi

        # If scheduled, only run tasks whose scheduled_for is today or earlier.
        if [ "$STATUS" = "scheduled" ]; then
            SCHEDULED_FOR=$(grep '^scheduled_for:' "$queue_file" | head -1 | sed 's/scheduled_for:[[:space:]]*//' | tr -d '"')
            if [ -n "$SCHEDULED_FOR" ]; then
                SCHED_DATE=$(echo "$SCHEDULED_FOR" | cut -d'T' -f1)
                if [ "$SCHED_DATE" \> "$TODAY" ]; then
                    log "  Skipping $(basename "$queue_file") — scheduled for future date $SCHED_DATE"
                    TOTAL_SKIPPED=$((TOTAL_SKIPPED + 1))
                    continue
                fi
            fi
        fi

        # Check dependencies — skip if any depends_on task is not completed.
        DEPENDS=$(grep '^depends_on:' "$queue_file" | head -1 | sed 's/depends_on:[[:space:]]*//' | tr -d '"' | tr -d '[]')
        if [ -n "$DEPENDS" ] && [ "$DEPENDS" != "" ]; then
            DEPS_MET=true
            for dep in $(echo "$DEPENDS" | tr ',' '\n' | tr -d ' '); do
                [ -z "$dep" ] && continue
                if [ ! -f "$QUEUE_DIR/history/$dep" ]; then
                    if [ -f "$QUEUE_DIR/$dep" ]; then
                        DEP_STATUS=$(grep '^status:' "$QUEUE_DIR/$dep" | head -1 | sed 's/status:[[:space:]]*//' | tr -d '"' | tr -d ' ')
                        if [ "$DEP_STATUS" != "completed" ]; then
                            DEPS_MET=false
                            log "  Skipping $(basename "$queue_file") — dependency $dep not completed (status: $DEP_STATUS)"
                            break
                        fi
                    fi
                fi
            done
            if [ "$DEPS_MET" = "false" ]; then
                TOTAL_SKIPPED=$((TOTAL_SKIPPED + 1))
                continue
            fi
        fi

        PRIORITY=$(grep '^priority:' "$queue_file" | head -1 | sed 's/priority:[[:space:]]*//' | tr -d '"' | tr -d ' ')
        case "$PRIORITY" in
            critical) SORT_KEY="1" ;;
            high)     SORT_KEY="2" ;;
            medium)   SORT_KEY="3" ;;
            low)      SORT_KEY="4" ;;
            *)        SORT_KEY="3" ;;
        esac

        TASK_LIST="${TASK_LIST}${SORT_KEY}|${queue_file}\n"
    done

    if [ -z "$TASK_LIST" ]; then
        log "  No processable tasks found"
        continue
    fi

    SORTED_TASKS=$(echo -e "$TASK_LIST" | sort -t'|' -k1,1 | sed 's/^[0-9]|//')

    while IFS= read -r queue_file; do
        [ -z "$queue_file" ] && continue
        [ -f "$queue_file" ] || continue

        FILENAME=$(basename "$queue_file")

        # Skill-delegation invariant: do NOT mutate queue file state here
        # (status, status-history, worktree, history/ move). The /smith-queue
        # skill is the single source of truth for the pipeline; any local
        # mutation before invocation risks double-writes and the exact
        # "moved to history with no real work done" failure mode that
        # motivated this rewrite.

        if [ "$DRY_RUN" = "1" ]; then
            log "  [dry-run] would dispatch: /smith-queue process $FILENAME (project: $PROJECT_NAME)"
            TOTAL_DISPATCHED=$((TOTAL_DISPATCHED + 1))
            continue
        fi

        log "  Dispatching to skill: $FILENAME (project: $PROJECT_NAME)"

        # Invoke from the project directory in a subshell so `cd` does not
        # persist across iterations. Route claude's stdout/stderr into the
        # scheduler log so errors like "claude: command not found" are never
        # swallowed again.
        (
            cd "$PROJECT_DIR" && \
            "$CLAUDE_BIN" \
                --model "$CLAUDE_MODEL" \
                --permission-mode bypassPermissions \
                -p "/smith-queue process $FILENAME"
        ) >> "$LOG_FILE" 2>&1
        SKILL_EXIT=$?

        # Verify outcome by inspecting the queue/history filesystem state.
        # The skill moves the entry to history/ on both success and explicit
        # failure (per SKILL.md step 15 / Failure Handling). If the file is
        # still in queue/, the skill did not take ownership — we never mutate
        # it ourselves, so the task remains pending for the next run.
        if [ -f "$QUEUE_DIR/history/$FILENAME" ]; then
            HIST_STATUS=$(grep '^status:' "$QUEUE_DIR/history/$FILENAME" | head -1 | sed 's/status:[[:space:]]*//' | tr -d '"' | tr -d ' ')
            if [ "$HIST_STATUS" = "completed" ]; then
                log "    Completed: $FILENAME (skill exit=$SKILL_EXIT, status=completed)"
                TOTAL_DISPATCHED=$((TOTAL_DISPATCHED + 1))
            else
                log "    Skill recorded failure: $FILENAME (skill exit=$SKILL_EXIT, status=$HIST_STATUS)"
                TOTAL_FAILED=$((TOTAL_FAILED + 1))
            fi
        elif [ -f "$queue_file" ]; then
            POST_STATUS=$(grep '^status:' "$queue_file" | head -1 | sed 's/status:[[:space:]]*//' | tr -d '"' | tr -d ' ')
            log "    Skill exited $SKILL_EXIT but $FILENAME still in queue (status=$POST_STATUS) — investigate"
            TOTAL_FAILED=$((TOTAL_FAILED + 1))
        else
            log "    Skill exited $SKILL_EXIT and $FILENAME is neither in queue/ nor history/ — investigate"
            TOTAL_FAILED=$((TOTAL_FAILED + 1))
        fi

    done <<< "$SORTED_TASKS"

done <<< "$PROJECT_PATHS"

# ---------------------------------------------------------------------------
# Audits step — dispatches `/smith-audit --scheduled` for registered projects
# whose scheduled_audits.enabled is true and whose cadence has elapsed. Runs
# strictly AFTER the queue loop above finishes for every project (Phased
# ordering). Reuses the same already-parsed $PROJECT_PATHS — no second
# projects.json read — and the same already-resolved $CLAUDE_BIN/
# $CLAUDE_MODEL — no second resolve_claude_bin() call. Never mutates a
# /smith-queue queue file or history/ entry (NFR-3); never writes
# .scheduled-audits-state.json itself — that file is written by
# /smith-audit only, after a successful scheduled run (FR-21).
# ---------------------------------------------------------------------------

AUDIT_DRY_RUN="${SMITH_AUDIT_DISPATCH_DRY_RUN:-0}"
AUDITS_DISPATCHED=0
AUDITS_FAILED=0
AUDITS_SKIPPED=0

while IFS= read -r vault_path; do
    [ -z "$vault_path" ] && continue

    # Same idiom the queue loop above uses to recover the project root.
    PROJECT_DIR="${vault_path%/.smith/vault}"
    PROJECT_NAME=$(basename "$PROJECT_DIR")
    CONFIG_FILE="$PROJECT_DIR/.smith/config.json"
    STATE_FILE="$vault_path/.scheduled-audits-state.json"

    # scheduled_audits.enabled — an absent config file, an absent
    # scheduled_audits section, or enabled:false are all a silent skip (one
    # logged line, no dispatch, no state-file write). JSON parsing goes
    # through python3, not grep/sed, matching this repo's existing
    # convention for structured-field reads elsewhere in the hooks/scripts
    # layer (e.g. hooks/context-budget-guard.sh).
    SA_ENABLED=$(python3 -c "import json; d=json.load(open('$CONFIG_FILE')); print(str(bool((d.get('scheduled_audits') or {}).get('enabled', False))).lower())" 2>/dev/null || echo "false")

    if [ "$SA_ENABLED" != "true" ]; then
        log "  Audits: skipping $PROJECT_NAME — scheduled_audits disabled"
        AUDITS_SKIPPED=$((AUDITS_SKIPPED + 1))
        continue
    fi

    CADENCE_DAYS=$(python3 -c "import json; d=json.load(open('$CONFIG_FILE')); print((d.get('scheduled_audits') or {}).get('cadence_days', 7))" 2>/dev/null || echo "7")
    SUBSETS_JOINED=$(python3 -c "import json; d=json.load(open('$CONFIG_FILE')); print(','.join((d.get('scheduled_audits') or {}).get('subsets') or []))" 2>/dev/null || echo "")

    # .scheduled-audits-state.json's last_run.date — an absent file, an
    # unreadable file, or JSON that fails to parse are all treated
    # identically as "never run" (empty string fed into is_audit_due()),
    # never as an error that skips or crashes this project's check (FR-22).
    LAST_RUN_DATE=$(python3 -c "import json; d=json.load(open('$STATE_FILE')); print((d.get('last_run') or {}).get('date','') or '')" 2>/dev/null || echo "")

    DUE=$(is_audit_due "$TODAY" "$LAST_RUN_DATE" "$CADENCE_DAYS")

    if [ "$DUE" != "1" ]; then
        log "  Audits: skipping $PROJECT_NAME — not yet due, last run $LAST_RUN_DATE"
        AUDITS_SKIPPED=$((AUDITS_SKIPPED + 1))
        continue
    fi

    if [ "$AUDIT_DRY_RUN" = "1" ]; then
        log "  [dry-run] would dispatch audit: /smith-audit --all --scheduled $SUBSETS_JOINED (project: $PROJECT_NAME, due=true)"
        AUDITS_DISPATCHED=$((AUDITS_DISPATCHED + 1))
        continue
    fi

    log "  Dispatching scheduled audit: $PROJECT_NAME (subsets: $SUBSETS_JOINED)"

    # Snapshot the state file's last_run.timestamp BEFORE dispatch so the
    # post-dispatch read-back below can tell a fresh write apart from a
    # stale one left over from a previous run.
    PRE_TS=$(python3 -c "import json; d=json.load(open('$STATE_FILE')); print((d.get('last_run') or {}).get('timestamp','') or '')" 2>/dev/null || echo "")

    # Invoke from the project directory in a subshell so `cd` does not
    # persist across iterations. Route claude's stdout/stderr into the SAME
    # scheduler log used by the queue step above — identical contract shape
    # to the existing queue dispatch block.
    (
        cd "$PROJECT_DIR" && \
        "$CLAUDE_BIN" \
            --model "$CLAUDE_MODEL" \
            --permission-mode bypassPermissions \
            -p "/smith-audit --all --scheduled $SUBSETS_JOINED"
    ) >> "$LOG_FILE" 2>&1
    AUDIT_EXIT=$?

    # Confirm success by reading back the state file /smith-audit writes
    # AFTER a successful scheduled run (write-after-success contract,
    # FR-21) — a fresh timestamp plus a readable report_path and
    # severity_totals. Never trust the process exit code alone, mirroring
    # the queue loop's own filesystem-state verification above. A non-zero
    # exit OR a read-back that doesn't confirm success is logged with the
    # project name and reason and does NOT stop the audits step from
    # continuing to the next registered project (FR-6).
    POST_OK=$(python3 -c "
import json
try:
    d = json.load(open('$STATE_FILE'))
    lr = d.get('last_run') or {}
    ts = lr.get('timestamp', '') or ''
    rp = lr.get('report_path', '') or ''
    sev = lr.get('severity_totals')
    print('true' if (ts and ts != '$PRE_TS' and rp and isinstance(sev, dict)) else 'false')
except Exception:
    print('false')
" 2>/dev/null || echo "false")

    if [ "$AUDIT_EXIT" -eq 0 ] && [ "$POST_OK" = "true" ]; then
        log "    Completed: scheduled audit for $PROJECT_NAME (exit=$AUDIT_EXIT)"
        AUDITS_DISPATCHED=$((AUDITS_DISPATCHED + 1))
    else
        log "    Failed: scheduled audit for $PROJECT_NAME (exit=$AUDIT_EXIT, state-confirmed=$POST_OK) — will retry next run"
        AUDITS_FAILED=$((AUDITS_FAILED + 1))
    fi

done <<< "$PROJECT_PATHS"

log "=== Daily scheduler run complete — dispatched: $TOTAL_DISPATCHED, failed: $TOTAL_FAILED, skipped: $TOTAL_SKIPPED | audits dispatched: $AUDITS_DISPATCHED, failed: $AUDITS_FAILED, skipped: $AUDITS_SKIPPED ==="
