#!/usr/bin/env bash
# Smith installer — copies skills, hooks, scheduler, and merges settings into
# your Claude Code config. Idempotent: re-run to upgrade.
#
# Usage:
#   ./scripts/install.sh              # interactive
#   ./scripts/install.sh -y            # assume yes to all prompts
#   curl -fsSL https://raw.githubusercontent.com/ATTCKDigital/smith/main/scripts/install.sh | bash
#
# Environment:
#   SMITH_HOME          (default: ~/.smith)        where scheduler + runtime state live
#   CLAUDE_HOME         (default: ~/.claude)       where skills and hooks are installed
#   SMITH_SKIP_SCHEDULER=1                         skip scheduler prompt even on macOS
#   SMITH_ASSUME_YES=1                             same as -y

set -euo pipefail

# ---------- constants ----------
SMITH_REPO_URL="https://github.com/ATTCKDigital/smith.git"
SMITH_HOME="${SMITH_HOME:-$HOME/.smith}"
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
CLAUDE_SKILLS_DIR="$CLAUDE_HOME/skills"
CLAUDE_HOOKS_DIR="$CLAUDE_HOME/hooks"
CLAUDE_SETTINGS="$CLAUDE_HOME/settings.json"
CLAUDE_MD="$CLAUDE_HOME/CLAUDE.md"

# ---------- arg parsing ----------
ASSUME_YES="${SMITH_ASSUME_YES:-0}"
for arg in "$@"; do
    case "$arg" in
        -y|--yes) ASSUME_YES=1 ;;
        -h|--help)
            sed -n '2,15p' "$0" | sed 's/^# *//'
            exit 0
            ;;
    esac
done

# ---------- helpers ----------
c_reset='\033[0m'; c_bold='\033[1m'; c_green='\033[32m'; c_yellow='\033[33m'; c_red='\033[31m'; c_blue='\033[34m'
info()    { printf "${c_blue}==>${c_reset} %s\n" "$*"; }
ok()      { printf "${c_green}✓${c_reset} %s\n" "$*"; }
warn()    { printf "${c_yellow}!${c_reset} %s\n" "$*" >&2; }
err()     { printf "${c_red}✗${c_reset} %s\n" "$*" >&2; }
prompt_yn() {
    [ "$ASSUME_YES" = "1" ] && return 0
    local msg="$1"; local default="${2:-y}"
    local hint="[Y/n]"; [ "$default" = "n" ] && hint="[y/N]"
    printf "${c_bold}?${c_reset} %s %s " "$msg" "$hint"
    read -r reply </dev/tty || reply=""
    reply="${reply:-$default}"
    [[ "$reply" =~ ^[yY] ]]
}

# ---------- bootstrap: if piped from curl, clone first ----------
SCRIPT_PATH="${BASH_SOURCE[0]:-}"
if [ -z "$SCRIPT_PATH" ] || [ ! -f "$SCRIPT_PATH" ]; then
    info "Bootstrapping Smith installer (no local repo detected)"
    command -v git >/dev/null || { err "git is required to bootstrap. Install git and retry."; exit 1; }
    BOOTSTRAP_DIR="$(mktemp -d -t smith-install.XXXXXX)"
    trap 'rm -rf "$BOOTSTRAP_DIR"' EXIT
    git clone --depth 1 "$SMITH_REPO_URL" "$BOOTSTRAP_DIR/smith" >/dev/null 2>&1 || {
        err "Failed to clone $SMITH_REPO_URL"; exit 1;
    }
    exec bash "$BOOTSTRAP_DIR/smith/scripts/install.sh" "$@"
fi

REPO_ROOT="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd)"

# ---------- banner ----------
cat <<'EOF'
   _____ __  __ _____ _______ _    _
  / ____|  \/  |_   _|__   __| |  | |
 | (___ | \  / | | |    | |  | |__| |
  \___ \| |\/| | | |    | |  |  __  |
  ____) | |  | |_| |_   | |  | |  | |
 |_____/|_|  |_|_____|  |_|  |_|  |_|

 Spec-driven development for Claude Code
EOF
echo
info "Installing Smith from: $REPO_ROOT"
info "Claude home:          $CLAUDE_HOME"
info "Smith home:           $SMITH_HOME"
echo

# ---------- platform detection ----------
OS="$(uname -s)"
IS_MACOS=0; IS_LINUX=0
case "$OS" in
    Darwin) IS_MACOS=1 ;;
    Linux)  IS_LINUX=1 ;;
    *) err "Unsupported OS: $OS. Smith supports macOS and Linux."; exit 1 ;;
esac

# ---------- dependency check ----------
info "Checking dependencies"
MISSING_DEPS=()
command -v git >/dev/null || MISSING_DEPS+=("git")
command -v jq  >/dev/null || MISSING_DEPS+=("jq")

if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
    err "Missing required tools: ${MISSING_DEPS[*]}"
    if [ "$IS_MACOS" = "1" ]; then
        echo "  Install with: brew install ${MISSING_DEPS[*]}"
    else
        echo "  Install with your package manager, e.g. apt install ${MISSING_DEPS[*]}"
    fi
    exit 1
fi
ok "git and jq found"

# Optional tools — warn only
if ! command -v gh >/dev/null 2>&1; then
    warn "gh (GitHub CLI) not found — smith-taskstoissues and some smith-build features will be limited"
fi

# ---------- confirm install ----------
echo
info "Smith will:"
echo "  • Copy 27 skills → $CLAUDE_SKILLS_DIR/smith*"
echo "  • Copy 9 hooks   → $CLAUDE_HOOKS_DIR/"
echo "  • Copy scheduler → $SMITH_HOME/scheduler/"
echo "  • Install global CLAUDE.md rubric → $CLAUDE_MD (backup first)"
echo "  • Merge hook entries into $CLAUDE_SETTINGS (backup first)"
if [ "$IS_MACOS" = "1" ] && [ "${SMITH_SKIP_SCHEDULER:-0}" != "1" ]; then
    echo "  • Offer to install a macOS LaunchAgent for the daily scheduler"
fi
echo
prompt_yn "Proceed?" y || { info "Aborted by user"; exit 0; }

# ---------- create target dirs ----------
mkdir -p "$CLAUDE_SKILLS_DIR" "$CLAUDE_HOOKS_DIR" "$SMITH_HOME/scheduler"

# ---------- backup settings.json ----------
if [ -f "$CLAUDE_SETTINGS" ]; then
    BACKUP="$CLAUDE_SETTINGS.bak-$(date +%Y%m%d-%H%M%S)"
    cp "$CLAUDE_SETTINGS" "$BACKUP"
    ok "Backed up existing settings → $BACKUP"
else
    echo '{}' > "$CLAUDE_SETTINGS"
    ok "Created new $CLAUDE_SETTINGS"
fi

# ---------- copy skills ----------
info "Copying skills"
SKILL_COUNT=0
for skill_src in "$REPO_ROOT"/skills/smith "$REPO_ROOT"/skills/smith-*; do
    [ -d "$skill_src" ] || continue
    skill_name="$(basename "$skill_src")"
    rm -rf "$CLAUDE_SKILLS_DIR/$skill_name"
    cp -R "$skill_src" "$CLAUDE_SKILLS_DIR/"
    SKILL_COUNT=$((SKILL_COUNT + 1))
done
ok "Installed $SKILL_COUNT skills"

# ---------- copy hooks ----------
info "Copying hooks"
HOOK_COUNT=0
for hook_src in "$REPO_ROOT"/hooks/*.sh; do
    [ -f "$hook_src" ] || continue
    hook_name="$(basename "$hook_src")"
    cp "$hook_src" "$CLAUDE_HOOKS_DIR/$hook_name"
    chmod +x "$CLAUDE_HOOKS_DIR/$hook_name"
    HOOK_COUNT=$((HOOK_COUNT + 1))
done
ok "Installed $HOOK_COUNT hooks"

# ---------- copy scheduler ----------
info "Copying scheduler"
cp "$REPO_ROOT/scheduler/smith-scheduler.sh" "$SMITH_HOME/scheduler/smith-scheduler.sh"
chmod +x "$SMITH_HOME/scheduler/smith-scheduler.sh"
ok "Installed scheduler script"

# ---------- install global CLAUDE.md rubric ----------
info "Installing global CLAUDE.md rubric"
CLAUDE_MD_TEMPLATE="$REPO_ROOT/settings/claude-md-template.md"
if [ -f "$CLAUDE_MD" ]; then
    CLAUDE_MD_BACKUP="$CLAUDE_MD.bak-$(date +%Y%m%d-%H%M%S)"
    cp "$CLAUDE_MD" "$CLAUDE_MD_BACKUP"
    ok "Backed up existing CLAUDE.md → $CLAUDE_MD_BACKUP"
fi
cp "$CLAUDE_MD_TEMPLATE" "$CLAUDE_MD"
ok "Installed CLAUDE.md rubric at $CLAUDE_MD"

# ---------- merge settings.json ----------
info "Merging hook entries into $CLAUDE_SETTINGS"
FRAGMENT="$REPO_ROOT/settings/smith-settings-fragment.json"
TMP_SETTINGS="$(mktemp)"
jq -s '
  .[0] as $existing | .[1] as $fragment |
  $existing * $fragment |
  .hooks = (
    ($existing.hooks // {}) as $eh |
    ($fragment.hooks // {}) as $fh |
    ($eh | to_entries) as $ehe |
    ($fh | to_entries) as $fhe |
    (($ehe + $fhe) | group_by(.key) | map({key: .[0].key, value: (map(.value) | add)}) | from_entries)
  )
' "$CLAUDE_SETTINGS" "$FRAGMENT" > "$TMP_SETTINGS"
mv "$TMP_SETTINGS" "$CLAUDE_SETTINGS"
ok "Settings merged"

# ---------- optional: scheduler LaunchAgent ----------
if [ "$IS_MACOS" = "1" ] && [ "${SMITH_SKIP_SCHEDULER:-0}" != "1" ]; then
    echo
    info "Smith can register a macOS LaunchAgent to run the queue processor daily at 2am."
    info "This runs bash scripts on your machine in the background. You can audit the"
    info "script at $SMITH_HOME/scheduler/smith-scheduler.sh before enabling."
    if prompt_yn "Install the daily scheduler LaunchAgent?" n; then
        LAUNCH_AGENT_DIR="$HOME/Library/LaunchAgents"
        PLIST_DEST="$LAUNCH_AGENT_DIR/com.smith.scheduler.plist"
        mkdir -p "$LAUNCH_AGENT_DIR"
        sed "s|__SMITH_HOME__|$SMITH_HOME|g" \
            "$REPO_ROOT/scheduler/com.smith.scheduler.plist.template" > "$PLIST_DEST"
        launchctl unload "$PLIST_DEST" 2>/dev/null || true
        launchctl load "$PLIST_DEST"
        ok "LaunchAgent installed: $PLIST_DEST"
    else
        info "Skipped scheduler install. You can run it later with:"
        echo "    $REPO_ROOT/scripts/install.sh -y"
    fi
fi

# ---------- done ----------
echo
ok "Smith installed successfully"
echo
echo "  Next steps:"
echo "    1. Open Claude Code in any project"
echo "    2. Run /smith-new to start a new feature, or /smith-help to see all commands"
echo "    3. Session logs and vault state will be created in <project>/.smith/vault/"
echo
echo "  Docs: https://github.com/ATTCKDigital/smith"
echo "  Website: https://smith.attck.com"
echo
