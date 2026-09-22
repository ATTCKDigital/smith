#!/usr/bin/env bash
# Smith uninstaller — removes skills, hooks, scheduler, and restores the most
# recent settings.json backup.
#
# Usage:
#   ./scripts/uninstall.sh             # interactive
#   ./scripts/uninstall.sh -y           # assume yes
#
# Note: this does NOT remove per-project .smith/vault/ directories. Your session
# logs, queue state, and vault data stay where they are. To remove them, delete
# the .smith/ directory inside each project manually.

set -euo pipefail

SMITH_HOME="${SMITH_HOME:-$HOME/.smith}"
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
CLAUDE_SKILLS_DIR="$CLAUDE_HOME/skills"
CLAUDE_HOOKS_DIR="$CLAUDE_HOME/hooks"
CLAUDE_SETTINGS="$CLAUDE_HOME/settings.json"
CLAUDE_MD="$CLAUDE_HOME/CLAUDE.md"

ASSUME_YES="${SMITH_ASSUME_YES:-0}"
for arg in "$@"; do
    case "$arg" in
        -y|--yes) ASSUME_YES=1 ;;
        -h|--help) sed -n '2,13p' "$0" | sed 's/^# *//'; exit 0 ;;
    esac
done

c_reset='\033[0m'; c_bold='\033[1m'; c_green='\033[32m'; c_yellow='\033[33m'; c_red='\033[31m'; c_blue='\033[34m'
info() { printf "${c_blue}==>${c_reset} %s\n" "$*"; }
ok()   { printf "${c_green}✓${c_reset} %s\n" "$*"; }
warn() { printf "${c_yellow}!${c_reset} %s\n" "$*" >&2; }
err()  { printf "${c_red}✗${c_reset} %s\n" "$*" >&2; }
prompt_yn() {
    [ "$ASSUME_YES" = "1" ] && return 0
    local msg="$1"; local default="${2:-y}"
    local hint="[Y/n]"; [ "$default" = "n" ] && hint="[y/N]"
    printf "${c_bold}?${c_reset} %s %s " "$msg" "$hint"
    read -r reply </dev/tty || reply=""
    reply="${reply:-$default}"
    [[ "$reply" =~ ^[yY] ]]
}

info "This will remove:"
echo "  • All smith/smith-* skills (plus bundled to-mermaid; legacy clean-code from pre-rename installs) from $CLAUDE_SKILLS_DIR"
echo "  • Smith hooks from $CLAUDE_HOOKS_DIR"
echo "  • Scheduler from $SMITH_HOME/scheduler/"
echo "  • Stop the /smith-activity daemon and restore your previous statusLine"
echo "  • The /smith-activity runtime from $SMITH_HOME/scripts/activity/ and $SMITH_HOME/activity/"
echo "  • Restore settings.json from the most recent backup (if any)"
echo "  • Restore CLAUDE.md from the most recent backup (if any)"
echo
info "This will NOT remove:"
echo "  • Per-project .smith/vault/ directories (your session logs stay put)"
echo "  • $SMITH_HOME/projects.json (project index)"
echo
prompt_yn "Proceed with uninstall?" n || { info "Aborted"; exit 0; }

# Uninstall LaunchAgent (macOS)
if [ "$(uname -s)" = "Darwin" ]; then
    PLIST="$HOME/Library/LaunchAgents/com.smith.scheduler.plist"
    if [ -f "$PLIST" ]; then
        launchctl unload "$PLIST" 2>/dev/null || true
        rm -f "$PLIST"
        ok "Removed LaunchAgent"
    fi
fi

# Remove skills. Enumerated by name (NOT a blanket skills/* glob) so we only
# remove what Smith ships and never touch a user's own global skills. The
# bundled non-smith skills are listed explicitly (to-mermaid, plus legacy
# clean-code — the pre-rename name of smith-clean-code, kept so older
# installs uninstall cleanly; smith-clean-code itself matches the smith-* glob);
# add any future non-smith bundled skill here to keep uninstall symmetric
# with install.sh's skills/* copy loop.
REMOVED_SKILLS=0
for skill in "$CLAUDE_SKILLS_DIR"/smith "$CLAUDE_SKILLS_DIR"/smith-* \
             "$CLAUDE_SKILLS_DIR"/clean-code "$CLAUDE_SKILLS_DIR"/to-mermaid; do
    [ -d "$skill" ] || continue
    rm -rf "$skill"
    REMOVED_SKILLS=$((REMOVED_SKILLS + 1))
done
ok "Removed $REMOVED_SKILLS skills"

# Remove hooks.
#
# Enumerated by name for the same reason the skills loop above is: this
# directory is the operator's, and Smith removes only what Smith put there.
#
# But an enumeration is only as good as its last update, and this one had
# rotted: it named 11 of the 20 hooks/*.sh the repo shipped, so an uninstall
# left 9 behind — among them workflow-gate.sh, which goes on denying tool calls
# in every project long after the operator believes Smith is gone. The three
# lists below were generated from `ls hooks/*.{sh,py,json}` and are pinned by
# tests/uninstall-hook-coverage.test.sh (FR-63/SC-18), which fails the build
# the moment a new hook is shipped without being added here. Add the file to
# the right list; do not transcribe a count from any document.
SMITH_HOOKS=(
    active-workflow-janitor.sh activity-emitter.sh
    context-budget-guard.sh context-loader.sh
    file-change-logger.sh grade-response.sh lint-on-save.sh
    manifest-updater.sh metrics-tracker.sh question-gate-guard.sh
    security-guard-bash.sh
    security-guard-files.sh security-guard-mcp-browser.sh
    session-end-review.sh session-start-logger.sh
    stamp-response.sh subagent-vault-writeback.sh task-router.sh
    user-prompt-logger.sh workflow-gate.sh workflow-summary.sh
)
SMITH_HOOK_HELPERS=(
    context-loader-lib.py manifest-updater-lib.py workflow_summary_lib.py
)
# install.sh copies hooks/*.json too (FR-62). pricing.json had never been
# removed by this script — the third uncovered enumeration the coverage test
# now closes.
SMITH_HOOK_DATA=(
    pricing.json
)
REMOVED_HOOKS=0
for hook in "${SMITH_HOOKS[@]}"; do
    if [ -f "$CLAUDE_HOOKS_DIR/$hook" ]; then
        rm -f "$CLAUDE_HOOKS_DIR/$hook"
        REMOVED_HOOKS=$((REMOVED_HOOKS + 1))
    fi
done
for helper in "${SMITH_HOOK_HELPERS[@]}"; do
    if [ -f "$CLAUDE_HOOKS_DIR/$helper" ]; then
        rm -f "$CLAUDE_HOOKS_DIR/$helper"
        REMOVED_HOOKS=$((REMOVED_HOOKS + 1))
    fi
done
for data in "${SMITH_HOOK_DATA[@]}"; do
    if [ -f "$CLAUDE_HOOKS_DIR/$data" ]; then
        rm -f "$CLAUDE_HOOKS_DIR/$data"
        REMOVED_HOOKS=$((REMOVED_HOOKS + 1))
    fi
done
# Byte-code left behind by importing the helpers above. A regenerable cache,
# never source, so removing it can cost nothing — but leaving it means a
# "clean" uninstall still leaves a Smith-created directory in the operator's
# hooks folder, which is exactly the residue the coverage test exists to stop.
rm -rf "$CLAUDE_HOOKS_DIR/__pycache__" 2>/dev/null || true
ok "Removed $REMOVED_HOOKS hooks"

# Remove manifest-system parsers
if [ -d "$SMITH_HOME/scripts" ]; then
    REPO_ROOT_GUESS="$(cd "$(dirname "$0")/.." && pwd)"
    if [ -f "$REPO_ROOT_GUESS/scripts/install-parsers.sh" ]; then
        bash "$REPO_ROOT_GUESS/scripts/install-parsers.sh" --uninstall 2>/dev/null || true
        ok "Removed manifest-system parsers"
    fi
    rm -rf "$SMITH_HOME/scripts/smith-index" 2>/dev/null || true
fi

# Remove scheduler
if [ -d "$SMITH_HOME/scheduler" ]; then
    rm -rf "$SMITH_HOME/scheduler"
    ok "Removed scheduler directory"
fi

# ===========================================================================
# /smith-activity teardown (FR-52 / FR-46)
#
# Runs BEFORE the wholesale `.bak-` restore below, and is written so that it
# does not depend on that restore happening at all. Three reasons it cannot be
# folded into it:
#
#   1. The operator may DECLINE the restore prompt. `statusLine` would then
#      keep pointing at a statusline-tee.sh this script is about to delete —
#      a broken status bar on every single prompt, in every project.
#   2. install.sh prunes to the 3 newest backups (install.sh:155). Four
#      installs after the wrap, no backup predating it survives, so the
#      "restore" would restore a settings.json that is ALREADY wrapped.
#   3. The `.bak-` file is a whole-file snapshot. Using it to undo one key
#      also silently reverts every unrelated settings change the operator has
#      made since — which is why the statusLine undo below is surgical.
#
# Both steps are idempotent and order-independent: the statusLine rewrite is a
# no-op unless `statusLine` is currently OUR tee, so running it before or after
# a `.bak-` restore (or twice) converges on the same result.
# ===========================================================================
ACTIVITY_DIR="$SMITH_HOME/activity"
STAGED_ACTIVITY="$SMITH_HOME/scripts/activity"

# The sidecar is snapshotted to a tempfile before anything deletes it, because
# restore_statusline has to run TWICE — once here and once after the `.bak-`
# restore below — and by then $ACTIVITY_DIR is gone. See the second call site
# for why once is not enough.
SIDECAR_SNAPSHOT="$(mktemp)"
trap 'rm -f "$SIDECAR_SNAPSHOT"' EXIT
if [ -f "$ACTIVITY_DIR/wrapped-statusline" ]; then
    cp "$ACTIVITY_DIR/wrapped-statusline" "$SIDECAR_SNAPSHOT" 2>/dev/null || true
fi

# --- 1. Stop the daemon, using the LaunchAgent teardown above as the shape
#        precedent: check the recorded handle, act only if it is really ours.
stop_activity_daemon() {
    local pidfile="$ACTIVITY_DIR/activity.pid"
    local pid i
    [ -f "$pidfile" ] || return 0
    pid="$(tr -dc '0-9' < "$pidfile" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        # A pid number is recycled the moment its process exits. Signalling one
        # we cannot positively identify as the activity daemon would kill a
        # stranger's program, so the command line is checked first — the same
        # `is_our_process` guard scripts/activity/smith-activity.sh uses.
        if ps -o command= -p "$pid" 2>/dev/null | grep -q "activity/server.py"; then
            kill "$pid" 2>/dev/null || true
            i=0
            while [ "$i" -lt 50 ] && kill -0 "$pid" 2>/dev/null; do
                sleep 0.1
                i=$((i + 1))
            done
            if kill -0 "$pid" 2>/dev/null; then
                kill -9 "$pid" 2>/dev/null || true
            fi
            ok "Stopped the /smith-activity daemon (pid $pid)"
        else
            warn "activity.pid names pid $pid, which is not the activity daemon — not signalled"
        fi
    fi
    rm -f "$pidfile" "$ACTIVITY_DIR/activity.port" 2>/dev/null || true
    return 0
}

# --- 2. Put `statusLine` back exactly as it was, from the sidecar
#        install-statusline.sh captured. Surgical: one key, nothing else.
restore_statusline() {
    local sidecar="$SIDECAR_SNAPSHOT"
    local current tmp
    [ -f "$CLAUDE_SETTINGS" ] || return 0
    if ! command -v jq >/dev/null 2>&1; then
        warn "jq not found — statusLine left pointing at statusline-tee.sh; edit $CLAUDE_SETTINGS by hand"
        return 0
    fi
    # `.statusLine` is legally an object OR a bare string, so both shapes are
    # probed. If it is not our tee, the operator's own command is already in
    # place and this function has nothing to undo — which is what makes it
    # safe to run either side of the `.bak-` restore.
    current="$(jq -r '(.statusLine.command // .statusLine // "") | tostring' "$CLAUDE_SETTINGS" 2>/dev/null || echo "")"
    case "$current" in
        *statusline-tee.sh*) ;;
        *) return 0 ;;
    esac

    tmp="$(mktemp)"
    if [ -f "$sidecar" ] && jq -e '.had_statusline == true' "$sidecar" >/dev/null 2>&1; then
        # `previous` holds the WHOLE original value, object or string.
        jq --slurpfile side "$sidecar" '.statusLine = $side[0].previous' \
            "$CLAUDE_SETTINGS" > "$tmp" 2>/dev/null || true
    else
        # No sidecar, or it recorded that there was nothing to preserve. With
        # no record of an original command, removing the key is the only
        # honest outcome: leaving a tee we are about to delete would put a
        # broken status bar on every prompt.
        jq 'del(.statusLine)' "$CLAUDE_SETTINGS" > "$tmp" 2>/dev/null || true
    fi

    # Same write guard as install.sh's hook merge: tempfile → jq empty → mv.
    if [ -s "$tmp" ] && jq empty "$tmp" >/dev/null 2>&1; then
        mv "$tmp" "$CLAUDE_SETTINGS"
        if [ -f "$sidecar" ] && jq -e '.had_statusline == true' "$sidecar" >/dev/null 2>&1; then
            ok "Restored your previous statusLine ($STATUSLINE_PASS)"
        else
            ok "Removed the /smith-activity statusLine wrapper ($STATUSLINE_PASS)"
        fi
    else
        rm -f "$tmp"
        err "statusLine restore produced invalid JSON — $CLAUDE_SETTINGS left unchanged"
    fi
    return 0
}

stop_activity_daemon
STATUSLINE_PASS="before the settings restore"
restore_statusline

# --- 3. Remove the staged tree (T123/FR-52). `rm -rf` on the DIRECTORY, never
#        a list of filenames: scripts/activity/static/ grew from 4 files to 6
#        during this feature's own build (panels.js and stepper.js were split
#        out), and any enumerated delete would have silently orphaned the two
#        new ones. There is nothing to enumerate if you remove the tree.
#        $ACTIVITY_DIR goes last because the sidecar read above lives in it.
if [ -d "$STAGED_ACTIVITY" ]; then
    rm -rf "$STAGED_ACTIVITY"
    ok "Removed staged /smith-activity runtime ($STAGED_ACTIVITY)"
fi
if [ -d "$ACTIVITY_DIR" ]; then
    rm -rf "$ACTIVITY_DIR"
    ok "Removed /smith-activity state ($ACTIVITY_DIR)"
fi

# Restore most recent settings backup
LATEST_BACKUP=$(ls -1t "$CLAUDE_SETTINGS".bak-* 2>/dev/null | head -1 || true)
if [ -n "$LATEST_BACKUP" ]; then
    if prompt_yn "Restore settings.json from $LATEST_BACKUP?" y; then
        cp "$LATEST_BACKUP" "$CLAUDE_SETTINGS"
        ok "Settings restored"
    else
        warn "Settings NOT restored. Smith hook entries still present in $CLAUDE_SETTINGS"
    fi
else
    warn "No backup found. Smith hook entries may still be in $CLAUDE_SETTINGS — edit manually if needed"
fi

# Second statusLine pass — and the reason the function had to be idempotent
# and order-independent rather than merely correct once.
#
# The `.bak-` file restored above is NOT guaranteed to predate the statusLine
# wrap. install.sh snapshots settings.json at the START of every run, so the
# backup taken by the SECOND install contains the first install's wrapper. Two
# installs and a keep-3 prune is all it takes for every surviving backup to be
# a wrapped one — at which point "restore from backup" faithfully restores the
# tee, undoing the surgical fix above and leaving `statusLine` pointing at a
# script this script has already deleted. Observed on a fixture, not theorised.
#
# So the undo runs on both sides of the restore. The first pass is what saves
# the operator who DECLINES the prompt above, or who has no backup left; this
# one is what saves the operator whose backup is poisoned. Whichever pass has
# work to do does it, and the other is a no-op — `statusLine` is only touched
# when it is currently our tee.
STATUSLINE_PASS="after the settings restore"
restore_statusline

# Restore most recent CLAUDE.md backup (if any)
LATEST_MD_BACKUP=$(ls -1t "$CLAUDE_MD".bak-* 2>/dev/null | head -1 || true)
if [ -n "$LATEST_MD_BACKUP" ]; then
    if prompt_yn "Restore CLAUDE.md from $LATEST_MD_BACKUP?" y; then
        cp "$LATEST_MD_BACKUP" "$CLAUDE_MD"
        ok "CLAUDE.md restored"
    else
        warn "CLAUDE.md NOT restored. Smith rubric still present at $CLAUDE_MD"
    fi
elif [ -f "$CLAUDE_MD" ]; then
    if prompt_yn "No CLAUDE.md backup found. Remove the Smith rubric at $CLAUDE_MD?" n; then
        rm -f "$CLAUDE_MD"
        ok "Removed $CLAUDE_MD"
    else
        warn "Smith rubric still present at $CLAUDE_MD — edit or remove manually if needed"
    fi
fi

echo
ok "Smith uninstalled"
echo
echo "  Per-project .smith/ directories were left untouched. To remove them:"
echo "    find ~/Projects -name .smith -type d  # review first"
echo "    find ~/Projects -name .smith -type d -exec rm -rf {} +  # delete"
echo
