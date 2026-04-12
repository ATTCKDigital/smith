#!/usr/bin/env bash
# smith-scheduler.sh
# Daily queue processor for Smith.
# Reads ~/.smith/projects.json, scans each project's queue for all autonomous
# tasks that are ready (pending or scheduled), and processes them via Claude
# Code in non-interactive mode with git worktree isolation.
#
# Intended to be run by macOS launchd once daily at 2:00 AM (configurable).
# Can also be run manually: bash ~/.smith/scheduler/smith-scheduler.sh

set -uo pipefail

SMITH_DIR="$HOME/.smith"
PROJECTS_FILE="$SMITH_DIR/projects.json"
LOG_FILE="$SMITH_DIR/scheduler/scheduler.log"
NOW_ISO=$(date -u +"%Y-%m-%dT%H:%M:%S")
NOW_EPOCH=$(date +%s)
TODAY=$(date +"%Y-%m-%d")

log() {
    echo "[$(date -u +"%Y-%m-%d %H:%M:%S")] $1" >> "$LOG_FILE"
}

# Ensure log file exists
mkdir -p "$(dirname "$LOG_FILE")"
touch "$LOG_FILE"

log "=== Daily scheduler run started ==="

# Check projects file
if [ ! -f "$PROJECTS_FILE" ]; then
    log "No projects.json found at $PROJECTS_FILE — nothing to do"
    exit 0
fi

# Parse project paths from JSON (simple grep-based extraction for macOS compatibility)
PROJECT_PATHS=$(grep '"path"' "$PROJECTS_FILE" | sed 's/.*"path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')

if [ -z "$PROJECT_PATHS" ]; then
    log "No projects registered — nothing to do"
    exit 0
fi

TOTAL_PROCESSED=0
TOTAL_FAILED=0
TOTAL_SKIPPED=0

while IFS= read -r vault_path; do
    QUEUE_DIR="$vault_path/queue"

    if [ ! -d "$QUEUE_DIR" ]; then
        continue
    fi

    PROJECT_NAME=$(basename "$(dirname "$vault_path")")
    PROJECT_DIR=$(dirname "$vault_path")  # .smith is inside the project dir

    log "Scanning project: $PROJECT_NAME ($QUEUE_DIR)"

    # Collect all processable tasks with their priority for sorting
    TASK_LIST=""

    for queue_file in "$QUEUE_DIR"/*.md; do
        [ -f "$queue_file" ] || continue
        [ "$(basename "$queue_file")" = ".batch-progress.md" ] && continue

        # Read status and complexity
        STATUS=$(grep '^status:' "$queue_file" | head -1 | sed 's/status:[[:space:]]*//' | tr -d '"' | tr -d ' ')
        COMPLEXITY=$(grep '^complexity:' "$queue_file" | head -1 | sed 's/complexity:[[:space:]]*//' | tr -d '"' | tr -d ' ')

        # Only process autonomous tasks that are pending or scheduled
        if [ "$COMPLEXITY" != "autonomous" ]; then
            continue
        fi
        if [ "$STATUS" != "pending" ] && [ "$STATUS" != "scheduled" ]; then
            continue
        fi

        # If scheduled, check that scheduled_for is not in the future (beyond today)
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

        # Check dependencies — skip if any depend_on task is not completed
        DEPENDS=$(grep '^depends_on:' "$queue_file" | head -1 | sed 's/depends_on:[[:space:]]*//' | tr -d '"' | tr -d '[]')
        if [ -n "$DEPENDS" ] && [ "$DEPENDS" != "" ]; then
            DEPS_MET=true
            for dep in $(echo "$DEPENDS" | tr ',' '\n' | tr -d ' '); do
                [ -z "$dep" ] && continue
                # Check if dependency is completed (in history)
                if [ ! -f "$QUEUE_DIR/history/$dep" ]; then
                    # Check if it's still in the queue (not completed)
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

        # Read priority for sorting (default: medium)
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

    # Sort tasks by priority then process
    if [ -z "$TASK_LIST" ]; then
        log "  No processable tasks found"
        continue
    fi

    SORTED_TASKS=$(echo -e "$TASK_LIST" | sort -t'|' -k1,1 | sed 's/^[0-9]|//')

    while IFS= read -r queue_file; do
        [ -z "$queue_file" ] && continue

        TASK_DESC=$(grep '^task:' "$queue_file" | head -1 | sed 's/task:[[:space:]]*//' | tr -d '"')
        if [ -z "$TASK_DESC" ]; then
            TASK_DESC=$(grep '^description:' "$queue_file" | head -1 | sed 's/description:[[:space:]]*//' | tr -d '"')
        fi
        FILENAME=$(basename "$queue_file")
        SLUG=$(echo "$FILENAME" | sed 's/^[0-9_-]*//;s/\.md$//')

        log "  Processing: $FILENAME — $TASK_DESC"

        # Update status to in-progress
        sed -i '' 's/^status: \(pending\|scheduled\)/status: in-progress/' "$queue_file"
        NOW_STAMP=$(date -u +"%Y-%m-%d %H:%M")
        echo "- \`[$NOW_STAMP]\` In Progress — daily scheduler picked up" >> "$queue_file"

        # Create worktree
        WORKTREE_DIR="/tmp/smith-queue-$SLUG"
        cd "$PROJECT_DIR" || continue

        if git worktree add "$WORKTREE_DIR" -b "queue/$SLUG" main 2>>"$LOG_FILE"; then
            log "  Worktree created: $WORKTREE_DIR"
        else
            log "  ERROR: Failed to create worktree for $SLUG"
            sed -i '' 's/^status: in-progress/status: failed/' "$queue_file"
            echo "- \`[$NOW_STAMP]\` Failed — could not create git worktree" >> "$queue_file"
            mkdir -p "$QUEUE_DIR/history"
            mv "$queue_file" "$QUEUE_DIR/history/"
            TOTAL_FAILED=$((TOTAL_FAILED + 1))
            continue
        fi

        # Run Claude in non-interactive mode
        CLAUDE_OUTPUT=$(claude --model sonnet -p "You are processing a queued task for the $PROJECT_NAME project. Task: $TASK_DESC. Work in directory: $WORKTREE_DIR. Implement the task, commit changes, and provide a brief summary of what was done." 2>&1) || true

        RESULT_STAMP=$(date -u +"%Y-%m-%d %H:%M")

        if [ $? -eq 0 ]; then
            sed -i '' 's/^status: in-progress/status: completed/' "$queue_file"
            echo "- \`[$RESULT_STAMP]\` Completed — branch queue/$SLUG ready for review" >> "$queue_file"
            echo "" >> "$queue_file"
            echo "## Result" >> "$queue_file"
            echo "" >> "$queue_file"
            echo "$CLAUDE_OUTPUT" | head -50 >> "$queue_file"
            log "  Completed: $FILENAME — branch queue/$SLUG"
            TOTAL_PROCESSED=$((TOTAL_PROCESSED + 1))
        else
            sed -i '' 's/^status: in-progress/status: failed/' "$queue_file"
            echo "- \`[$RESULT_STAMP]\` Failed — claude execution error" >> "$queue_file"
            echo "" >> "$queue_file"
            echo "## Error" >> "$queue_file"
            echo "" >> "$queue_file"
            echo "$CLAUDE_OUTPUT" | tail -20 >> "$queue_file"
            log "  Failed: $FILENAME"
            TOTAL_FAILED=$((TOTAL_FAILED + 1))
        fi

        # Clean up worktree (leave branch for review)
        git worktree remove "$WORKTREE_DIR" 2>>"$LOG_FILE" || true

        # Move to history
        mkdir -p "$QUEUE_DIR/history"
        mv "$queue_file" "$QUEUE_DIR/history/" 2>/dev/null || true

    done <<< "$SORTED_TASKS"

done <<< "$PROJECT_PATHS"

log "=== Daily scheduler run complete — processed: $TOTAL_PROCESSED, failed: $TOTAL_FAILED, skipped: $TOTAL_SKIPPED ==="
