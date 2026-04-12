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
echo "  • All smith/smith-* skills from $CLAUDE_SKILLS_DIR"
echo "  • Smith hooks from $CLAUDE_HOOKS_DIR"
echo "  • Scheduler from $SMITH_HOME/scheduler/"
echo "  • Restore settings.json from the most recent backup (if any)"
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

# Remove skills
REMOVED_SKILLS=0
for skill in "$CLAUDE_SKILLS_DIR"/smith "$CLAUDE_SKILLS_DIR"/smith-*; do
    [ -d "$skill" ] || continue
    rm -rf "$skill"
    REMOVED_SKILLS=$((REMOVED_SKILLS + 1))
done
ok "Removed $REMOVED_SKILLS skills"

# Remove hooks
SMITH_HOOKS=(
    file-change-logger.sh lint-on-save.sh
    security-guard-bash.sh security-guard-files.sh
    session-end-review.sh session-start-logger.sh
    subagent-vault-writeback.sh task-router.sh
)
REMOVED_HOOKS=0
for hook in "${SMITH_HOOKS[@]}"; do
    if [ -f "$CLAUDE_HOOKS_DIR/$hook" ]; then
        rm -f "$CLAUDE_HOOKS_DIR/$hook"
        REMOVED_HOOKS=$((REMOVED_HOOKS + 1))
    fi
done
ok "Removed $REMOVED_HOOKS hooks"

# Remove scheduler
if [ -d "$SMITH_HOME/scheduler" ]; then
    rm -rf "$SMITH_HOME/scheduler"
    ok "Removed scheduler directory"
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

echo
ok "Smith uninstalled"
echo
echo "  Per-project .smith/ directories were left untouched. To remove them:"
echo "    find ~/Projects -name .smith -type d  # review first"
echo "    find ~/Projects -name .smith -type d -exec rm -rf {} +  # delete"
echo
