#!/usr/bin/env bash
# install-git-hooks.sh — copy Smith manifest catch-up hooks into the current
# project's .git/hooks/ directory.
#
# Per Design Decision 8: git hooks layer that keeps the manifest in sync
# with external mutation sources (git pull, branch switches, merges). The
# hooks run `/smith-index --incremental` for the diff between the prior
# HEAD and the new HEAD.
#
# Usage:
#   scripts/install-git-hooks.sh             # install into current project
#   scripts/install-git-hooks.sh --force     # overwrite existing hooks
#   scripts/install-git-hooks.sh --dry-run   # preview
#   scripts/install-git-hooks.sh --uninstall # remove
#
# If a hook already exists at the target path and --force is not passed,
# the installer warns and writes the Smith hook to `<hook>.smith` instead,
# leaving the original untouched.

set -uo pipefail

DRY_RUN=false
FORCE=false
UNINSTALL=false
PROJECT_ROOT=""

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=true ;;
        --force) FORCE=true ;;
        --uninstall) UNINSTALL=true ;;
        --root)
            shift
            PROJECT_ROOT="$1"
            ;;
        -h|--help)
            sed -n '2,17p' "$0" | sed 's/^# *//'
            exit 0
            ;;
        *)
            printf 'install-git-hooks: unknown arg: %s\n' "$1" >&2
            exit 2
            ;;
    esac
    shift
done

if [ -z "$PROJECT_ROOT" ]; then
    PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "")"
fi

if [ -z "$PROJECT_ROOT" ] || [ ! -d "$PROJECT_ROOT/.git" ]; then
    echo "install-git-hooks: no .git directory found; pass --root <repo-path>" >&2
    exit 1
fi

HOOK_DIR="$PROJECT_ROOT/.git/hooks"
mkdir -p "$HOOK_DIR"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="$REPO_ROOT/templates/git-hooks"

c_reset='\033[0m'; c_green='\033[32m'; c_yellow='\033[33m'; c_blue='\033[34m'
info() { printf "${c_blue}==>${c_reset} %s\n" "$*"; }
ok()   { printf "${c_green}✓${c_reset} %s\n" "$*"; }
warn() { printf "${c_yellow}!${c_reset} %s\n" "$*" >&2; }

install_one() {
    local name="$1"
    local src="$SOURCE_DIR/$name"
    local dst="$HOOK_DIR/$name"
    local alt="$HOOK_DIR/$name.smith"

    if [ ! -f "$src" ]; then
        warn "source template missing: $src"
        return 1
    fi

    if $DRY_RUN; then
        info "would install $src -> $dst"
        return 0
    fi

    if [ -e "$dst" ] && ! $FORCE; then
        # Check if it's already our hook.
        if grep -q "Smith manifest catch-up" "$dst" 2>/dev/null; then
            cp "$src" "$dst"
            chmod +x "$dst"
            ok "updated $name (Smith hook detected, refreshed)"
            return 0
        fi
        warn "$dst already exists (not a Smith hook). Writing $alt instead."
        echo "  Diff between your hook and the Smith hook:"
        diff -u "$dst" "$src" 2>&1 | head -20 || true
        echo "  To merge: review and integrate the Smith logic from $alt."
        cp "$src" "$alt"
        chmod +x "$alt"
        return 0
    fi

    cp "$src" "$dst"
    chmod +x "$dst"
    ok "installed $name"
}

uninstall_one() {
    local name="$1"
    local dst="$HOOK_DIR/$name"
    local alt="$HOOK_DIR/$name.smith"

    if $DRY_RUN; then
        [ -e "$dst" ] && info "would remove $dst"
        [ -e "$alt" ] && info "would remove $alt"
        return 0
    fi

    if [ -e "$dst" ] && grep -q "Smith manifest catch-up" "$dst" 2>/dev/null; then
        rm -f "$dst"
        ok "removed $name"
    elif [ -e "$dst" ]; then
        warn "$dst exists but is not a Smith hook; leaving it alone"
    fi
    if [ -e "$alt" ]; then
        rm -f "$alt"
        ok "removed $name.smith"
    fi
}

info "Project: $PROJECT_ROOT"

if $UNINSTALL; then
    uninstall_one post-merge
    uninstall_one post-checkout
else
    install_one post-merge
    install_one post-checkout
fi

echo
ok "Git hook setup complete."
echo "  Hooks fire after \`git pull\` (post-merge) and branch switches"
echo "  (post-checkout). They exit silently if .smith/index/ is absent."
