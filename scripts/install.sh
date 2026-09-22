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
NO_HOOKS=0
NO_PARSERS=0
for arg in "$@"; do
    case "$arg" in
        -y|--yes) ASSUME_YES=1 ;;
        --no-hooks) NO_HOOKS=1 ;;
        --no-parsers) NO_PARSERS=1 ;;
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

# ---------- backup retention ----------
# Keep only the N newest timestamped backups per file. Sourced after REPO_ROOT is
# resolved so the curl-pipe bootstrap above (which re-execs with a real path) is
# unaffected.
BACKUP_KEEP="${SMITH_BACKUP_KEEP:-3}"
# shellcheck source=lib/prune-backups.sh
. "$REPO_ROOT/scripts/lib/prune-backups.sh"

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
# Count shipped skills dynamically so this preview never drifts as skills are
# added (the copy loop below globs every dir under skills/, smith-namespaced
# or not — e.g. smith-clean-code, to-mermaid).
SKILL_TOTAL=$(find "$REPO_ROOT/skills" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
# Count shipped hooks dynamically too (the copy loop below globs hooks/*.sh),
# so this preview never drifts as hooks are added.
HOOK_TOTAL=$(find "$REPO_ROOT/hooks" -maxdepth 1 -name '*.sh' -type f 2>/dev/null | wc -l | tr -d ' ')
echo
info "Smith will:"
echo "  • Copy $SKILL_TOTAL skills → $CLAUDE_SKILLS_DIR/"
echo "  • Copy $HOOK_TOTAL hooks   → $CLAUDE_HOOKS_DIR/"
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
    prune_backups "$CLAUDE_SETTINGS.bak-*" "$BACKUP_KEEP"
    ok "Backed up existing settings → $BACKUP"
else
    echo '{}' > "$CLAUDE_SETTINGS"
    ok "Created new $CLAUDE_SETTINGS"
fi

# ---------- copy skills ----------
info "Copying skills"
SKILL_COUNT=0
for skill_src in "$REPO_ROOT"/skills/*; do
    [ -d "$skill_src" ] || continue
    skill_name="$(basename "$skill_src")"
    target="$CLAUDE_SKILLS_DIR/$skill_name"
    # Explicitly unlink symlinks first. Observed in practice: when
    # `npx skills add ATTCKDigital/smith` was previously run, it symlinks
    # ~/.claude/skills/<name> -> ../.agents/skills/<name> using a
    # relative path. Once the npm tree is cleaned up that link is
    # broken. A subsequent `rm -rf` on the broken-symlink path may
    # leave the link in place (rm doesn't traverse the dangling
    # target), after which `cp -R` either fails or copies INTO the
    # dangling path. Force-remove the link first so cp creates a
    # fresh directory.
    [ -L "$target" ] && unlink "$target"
    rm -rf "$target"
    cp -R "$skill_src" "$CLAUDE_SKILLS_DIR/"
    # Some skills (e.g. smith-research) carry a skill-owned Python venv +
    # caches that must NOT be shipped: a copied venv has broken absolute
    # paths, and it can be hundreds of MB. The skill rebuilds its venv at
    # the install location on first run (SKILL.md Phase 0). Strip them here.
    rm -rf "$target/scripts/.venv" 2>/dev/null || true
    find "$target" -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
    find "$target" -type d -name ".pytest_cache" -prune -exec rm -rf {} + 2>/dev/null || true
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
# Copy the Python helpers used by the manifest-system hooks.
for helper_src in "$REPO_ROOT"/hooks/*.py; do
    [ -f "$helper_src" ] || continue
    helper_name="$(basename "$helper_src")"
    cp "$helper_src" "$CLAUDE_HOOKS_DIR/$helper_name"
    chmod +x "$CLAUDE_HOOKS_DIR/$helper_name"
done
ok "Installed $HOOK_COUNT hooks (plus Python helpers)"

# ---------- install manifest-system parsers ----------
if [ "$NO_PARSERS" != "1" ]; then
    info "Installing manifest-system parsers to ~/.smith/scripts/"
    bash "$REPO_ROOT/scripts/install-parsers.sh" || warn "parser install reported errors"
    # Also stage the smith-index runtime so post-merge/post-checkout git
    # hooks (and the /smith-index skill) can find run.py.
    mkdir -p "$SMITH_HOME/scripts/smith-index"
    cp "$REPO_ROOT/scripts/smith-index/run.py" "$SMITH_HOME/scripts/smith-index/run.py" 2>/dev/null || true
    cp "$REPO_ROOT/scripts/smith-index/run.sh" "$SMITH_HOME/scripts/smith-index/run.sh" 2>/dev/null || true
    cp "$REPO_ROOT/scripts/smith-index/wp_defaults.py" "$SMITH_HOME/scripts/smith-index/wp_defaults.py" 2>/dev/null || true
    chmod +x "$SMITH_HOME/scripts/smith-index/"*.sh 2>/dev/null || true
    # Workflow marker creation helper (per spec/31-workflow-gate-bootstrap).
    # Exempted by the gate by basename, so all four workflow skills can
    # self-bootstrap without the Python Path.write_text() workaround.
    cp "$REPO_ROOT/scripts/create-active-workflow.sh" "$SMITH_HOME/scripts/create-active-workflow.sh" 2>/dev/null || true
    chmod +x "$SMITH_HOME/scripts/create-active-workflow.sh" 2>/dev/null || true
    ok "Parsers installed"
fi

# ---------- copy security scripts ----------
# Feature 55-security-review-pass: secret-scan.sh/secret_scan.py/
# detect-scanners.sh are not parsers, so this stanza is unconditional
# (not gated by --no-parsers) — mirrors the smith-index/
# create-active-workflow.sh staging precedent just above.
info "Copying security scripts"
mkdir -p "$SMITH_HOME/scripts/security"
cp "$REPO_ROOT/scripts/security/secret-scan.sh" "$SMITH_HOME/scripts/security/secret-scan.sh" 2>/dev/null || true
cp "$REPO_ROOT/scripts/security/secret_scan.py" "$SMITH_HOME/scripts/security/secret_scan.py" 2>/dev/null || true
cp "$REPO_ROOT/scripts/security/detect-scanners.sh" "$SMITH_HOME/scripts/security/detect-scanners.sh" 2>/dev/null || true
# Feature 56-supply-chain-gate: _manifest_discovery.py/dependency-scan.{py,sh}/
# license-inventory.{py,sh} — unconditional for the same reason as feature 55's
# own scripts above (not parsers, so not gated by --no-parsers).
cp "$REPO_ROOT/scripts/security/_manifest_discovery.py" "$SMITH_HOME/scripts/security/_manifest_discovery.py" 2>/dev/null || true
cp "$REPO_ROOT/scripts/security/_scan_parsers.py" "$SMITH_HOME/scripts/security/_scan_parsers.py" 2>/dev/null || true
cp "$REPO_ROOT/scripts/security/dependency-scan.py" "$SMITH_HOME/scripts/security/dependency-scan.py" 2>/dev/null || true
cp "$REPO_ROOT/scripts/security/dependency-scan.sh" "$SMITH_HOME/scripts/security/dependency-scan.sh" 2>/dev/null || true
cp "$REPO_ROOT/scripts/security/license-inventory.py" "$SMITH_HOME/scripts/security/license-inventory.py" 2>/dev/null || true
cp "$REPO_ROOT/scripts/security/license-inventory.sh" "$SMITH_HOME/scripts/security/license-inventory.sh" 2>/dev/null || true
chmod +x "$SMITH_HOME/scripts/security/"*.sh 2>/dev/null || true
ok "Security scripts installed"

# ---------- copy scheduler ----------
info "Copying scheduler"
cp "$REPO_ROOT/scheduler/smith-scheduler.sh" "$SMITH_HOME/scheduler/smith-scheduler.sh"
chmod +x "$SMITH_HOME/scheduler/smith-scheduler.sh"
ok "Installed scheduler script"

# ---------- copy shared templates ----------
# Per-project files seeded on first SessionStart (config.default.json,
# context-manifest.default.json, etc.) live under $SMITH_HOME/templates/
# so hooks and run.py can resolve them off a stable path.
info "Copying shared templates"
mkdir -p "$SMITH_HOME/templates"
for tpl in config.default.json context-manifest.default.json; do
    src="$REPO_ROOT/templates/$tpl"
    if [ -f "$src" ]; then
        cp "$src" "$SMITH_HOME/templates/$tpl"
    fi
done
ok "Templates installed"

# ---------- install global CLAUDE.md rubric ----------
info "Installing global CLAUDE.md rubric"
CLAUDE_MD_TEMPLATE="$REPO_ROOT/settings/claude-md-template.md"
if [ -f "$CLAUDE_MD" ]; then
    CLAUDE_MD_BACKUP="$CLAUDE_MD.bak-$(date +%Y%m%d-%H%M%S)"
    cp "$CLAUDE_MD" "$CLAUDE_MD_BACKUP"
    prune_backups "$CLAUDE_MD.bak-*" "$BACKUP_KEEP"
    ok "Backed up existing CLAUDE.md → $CLAUDE_MD_BACKUP"
fi
cp "$CLAUDE_MD_TEMPLATE" "$CLAUDE_MD"
ok "Installed CLAUDE.md rubric at $CLAUDE_MD"

# ---------- merge settings.json ----------
info "Merging hook entries into $CLAUDE_SETTINGS"
FRAGMENT="$REPO_ROOT/settings/smith-settings-fragment.json"
TMP_SETTINGS="$(mktemp)"
jq -s -L "$REPO_ROOT/scripts/lib" '
  include "dedupehooks";
  # True-idempotent hook merge (added per /smith-update Q1-D):
  # - Concatenate existing + fragment entries per event type
  # - Deduplicate at the individual (matcher, command) level via dedupehooks.jq.
  #   Entry-level dedup was not enough: the same commands regrouped across
  #   fragment versions produce distinct entry keys, so a command could stay
  #   registered (and run) several times per event. Command-level dedup also
  #   collapses duplicates left behind by older installs.
  .[0] as $existing | .[1] as $fragment |
  $existing * $fragment |
  .hooks = (
    (($existing.hooks // {}) | to_entries) as $existing_events |
    (($fragment.hooks // {}) | to_entries) as $fragment_events |
    (($existing_events + $fragment_events)
      | group_by(.key)
      | map({key: .[0].key, value: (map(.value) | add)})
      | from_entries
      | dedupe_hooks)
  )
' "$CLAUDE_SETTINGS" "$FRAGMENT" > "$TMP_SETTINGS"
# Never replace settings.json with the output of a failed jq run (a missing
# module path or unreadable fragment would otherwise leave it empty).
if [ -s "$TMP_SETTINGS" ] && jq empty "$TMP_SETTINGS" >/dev/null 2>&1; then
    mv "$TMP_SETTINGS" "$CLAUDE_SETTINGS"
    ok "Settings merged (idempotent: existing duplicates collapsed)"
else
    rm -f "$TMP_SETTINGS"
    err "Settings merge produced invalid JSON — left $CLAUDE_SETTINGS unchanged"
    [ -n "${BACKUP:-}" ] && info "A backup is available at $BACKUP"
fi

# ---------- install manifest-system hooks (auto-register per Q4) ----------
if [ "$NO_HOOKS" != "1" ]; then
    info "Registering manifest-system hooks in $CLAUDE_SETTINGS"
    bash "$REPO_ROOT/scripts/install-hooks.sh" --settings "$CLAUDE_SETTINGS" \
        || warn "hook registration reported errors"
else
    info "Skipping manifest-system hook registration (--no-hooks)"
fi

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

# ---------- record installed version ----------
# Written for /smith-update to read on next invocation. Single-line SHA;
# falls back to "unknown" if we can't resolve a commit (e.g., running from
# a tarball download, not a git clone).
INSTALLED_SHA=$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo "unknown")
echo "$INSTALLED_SHA" > "$SMITH_HOME/.installed-version"
ok "Recorded installed version: ${INSTALLED_SHA:0:7}"

# ---------- done ----------
echo
ok "Smith installed successfully"
echo
echo "  Next steps:"
echo "    1. Open Claude Code in any project"
echo "    2. Run /smith-new to start a new feature, or /smith-help to see all commands"
echo "    3. Session logs and vault state will be created in <project>/.smith/vault/"
echo "    4. For per-project git-hook drift catch-up, run inside the project:"
echo "         $REPO_ROOT/scripts/install-git-hooks.sh"
echo "       (Or just run /smith-index manually when needed.)"
echo
echo "  Docs: https://github.com/ATTCKDigital/smith"
echo "  Website: https://smith.attck.com"
echo
