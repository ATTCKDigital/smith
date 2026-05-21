#!/usr/bin/env bash
# install-hooks.sh — register the manifest-system Claude Code hooks in
# ~/.claude/settings.json.
#
# Per Q4: hooks auto-register by default. Pass `--no-hooks` to skip.
# Per Design Decision 7: manifest-updater.sh must be LAST in the
# PostToolUse Write|Edit chain so it runs after lint-on-save.sh and
# captures the post-format file state. If it's already registered in
# the wrong position, this script re-orders it.
#
# Usage:
#   scripts/install-hooks.sh                 # install/register hooks
#   scripts/install-hooks.sh --no-hooks      # opt-out: do nothing
#   scripts/install-hooks.sh --dry-run       # preview changes
#   scripts/install-hooks.sh --uninstall     # remove entries
#   scripts/install-hooks.sh --settings <p>  # target an alternate settings.json
#                                            #  (used by tests)

set -euo pipefail

# Allow override for test fixtures.
CLAUDE_SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
DRY_RUN=false
NO_HOOKS=false
UNINSTALL=false

while [ $# -gt 0 ]; do
    case "$1" in
        --no-hooks) NO_HOOKS=true ;;
        --dry-run)  DRY_RUN=true ;;
        --uninstall) UNINSTALL=true ;;
        --settings)
            shift
            CLAUDE_SETTINGS="$1"
            ;;
        -h|--help)
            sed -n '2,17p' "$0" | sed 's/^# *//'
            exit 0
            ;;
        *)
            printf 'install-hooks: unknown arg: %s\n' "$1" >&2
            exit 2
            ;;
    esac
    shift
done

if $NO_HOOKS; then
    echo "install-hooks: --no-hooks specified, skipping registration"
    exit 0
fi

c_reset='\033[0m'; c_green='\033[32m'; c_yellow='\033[33m'; c_blue='\033[34m'
info() { printf "${c_blue}==>${c_reset} %s\n" "$*"; }
ok()   { printf "${c_green}✓${c_reset} %s\n" "$*"; }
warn() { printf "${c_yellow}!${c_reset} %s\n" "$*" >&2; }

if ! command -v python3 >/dev/null 2>&1; then
    warn "python3 not found; cannot safely edit settings.json"
    exit 1
fi

mkdir -p "$(dirname "$CLAUDE_SETTINGS")"
if [ ! -f "$CLAUDE_SETTINGS" ]; then
    echo '{}' > "$CLAUDE_SETTINGS"
    ok "Created new $CLAUDE_SETTINGS"
fi

# Define hook entries.
MANIFEST_UPDATER_CMD="bash ~/.claude/hooks/manifest-updater.sh"
CONTEXT_LOADER_CMD="bash ~/.claude/hooks/context-loader.sh"

if $DRY_RUN; then
    info "Dry-run mode — no changes will be written"
fi

# Backup.
if ! $DRY_RUN; then
    BACKUP="${CLAUDE_SETTINGS}.bak.$(date -u +%Y%m%dT%H%M%SZ)"
    cp "$CLAUDE_SETTINGS" "$BACKUP"
    ok "Backed up: $BACKUP"
fi

info "Updating $CLAUDE_SETTINGS"

# Use python3 for safe JSON parse+modify. The script reads settings.json,
# modifies the hooks dict, and writes it back. Idempotent.
TMP=$(mktemp)

PYTHON_SCRIPT=$(cat <<'PYEOF'
import json
import sys

path = sys.argv[1]
out_path = sys.argv[2]
manifest_cmd = sys.argv[3]
context_cmd = sys.argv[4]
uninstall = sys.argv[5] == "true"

with open(path, "r", encoding="utf-8") as f:
    settings = json.load(f)

hooks = settings.setdefault("hooks", {})

def _hook_entry(cmd: str) -> dict:
    return {"type": "command", "command": cmd}


def _remove_cmd(blocks, cmd_substr):
    """Walk hook blocks and drop any entry whose command contains cmd_substr."""
    removed = 0
    for block in blocks or []:
        new_hooks = []
        for h in block.get("hooks", []):
            if cmd_substr in h.get("command", ""):
                removed += 1
                continue
            new_hooks.append(h)
        block["hooks"] = new_hooks
    return removed


def _has_cmd(blocks, cmd_substr):
    for block in blocks or []:
        for h in block.get("hooks", []):
            if cmd_substr in h.get("command", ""):
                return True
    return False


actions = []

if uninstall:
    pre = hooks.get("PostToolUse") or []
    n = _remove_cmd(pre, "manifest-updater.sh")
    if n:
        actions.append(f"removed manifest-updater.sh ({n} entries)")
    ups = hooks.get("UserPromptSubmit") or []
    n = _remove_cmd(ups, "context-loader.sh")
    if n:
        actions.append(f"removed context-loader.sh ({n} entries)")
else:
    # --- manifest-updater.sh (PostToolUse, Write|Edit, LAST) ---
    pre = hooks.setdefault("PostToolUse", [])
    # Always strip any existing entry first so we can re-insert in the right
    # position (LAST in Write|Edit chain per Decision 7).
    removed = _remove_cmd(pre, "manifest-updater.sh")

    # Find the Write|Edit (or Write|Edit|NotebookEdit) block. If multiple
    # match, append to the one with the broadest matcher (Write|Edit).
    target_block = None
    for block in pre:
        matcher = block.get("matcher", "")
        if matcher == "Write|Edit":
            target_block = block
            break
    if target_block is None:
        # Fall back to any block matching both Write and Edit.
        for block in pre:
            matcher = block.get("matcher", "")
            if "Write" in matcher and "Edit" in matcher:
                target_block = block
                break
    if target_block is None:
        # Create a dedicated block.
        target_block = {"matcher": "Write|Edit", "hooks": []}
        pre.append(target_block)
        actions.append("created new PostToolUse Write|Edit block")

    target_block.setdefault("hooks", []).append(_hook_entry(manifest_cmd))
    if removed:
        actions.append(
            "manifest-updater.sh re-ordered to LAST in Write|Edit chain "
            f"(removed {removed} old entries)"
        )
    else:
        actions.append("manifest-updater.sh appended LAST to Write|Edit chain")

    # --- context-loader.sh (UserPromptSubmit) ---
    ups = hooks.setdefault("UserPromptSubmit", [])
    if not _has_cmd(ups, "context-loader.sh"):
        # Use matcher "*" to mirror existing convention.
        ups.append({"matcher": "*", "hooks": [_hook_entry(context_cmd)]})
        actions.append("context-loader.sh added to UserPromptSubmit")
    else:
        actions.append("context-loader.sh already registered (no change)")

# Write.
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")

for a in actions:
    print(a)
PYEOF
)

if $DRY_RUN; then
    OUT=$(mktemp)
    python3 -c "$PYTHON_SCRIPT" "$CLAUDE_SETTINGS" "$OUT" \
        "$MANIFEST_UPDATER_CMD" "$CONTEXT_LOADER_CMD" \
        "$($UNINSTALL && echo true || echo false)"
    echo
    info "Diff (would-be changes):"
    diff -u "$CLAUDE_SETTINGS" "$OUT" || true
    rm -f "$OUT" "$TMP"
else
    python3 -c "$PYTHON_SCRIPT" "$CLAUDE_SETTINGS" "$TMP" \
        "$MANIFEST_UPDATER_CMD" "$CONTEXT_LOADER_CMD" \
        "$($UNINSTALL && echo true || echo false)" \
        | while read -r line; do ok "$line"; done
    mv "$TMP" "$CLAUDE_SETTINGS"
fi

echo
ok "Hook registration complete."
echo "  Re-run any time — script is idempotent."
echo "  Pass --uninstall to remove the entries."
