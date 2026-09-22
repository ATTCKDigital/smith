#!/usr/bin/env bash
# install-activity.sh — stage the /smith-activity runtime and the FR-61
# shipped-hook manifest (T116 / T118). Called by scripts/install.sh immediately
# before the transport and statusline steps; safe to run standalone.
#
# Usage:
#   scripts/install-activity.sh
#
# Environment:
#   SMITH_HOME   default ~/.smith
#
# Its own file rather than two blocks inside install.sh, following the
# scripts/install-activity-transport.sh and scripts/install-statusline.sh
# precedent that the two steps after it already set. install.sh stood at 418
# lines; inlining the staging copy and the manifest generator would have pushed
# it to the wrong side of this repo's 500-line decompose threshold, and — the
# reason that actually matters — the staging has to be runnable against a
# FIXTURE SMITH_HOME without running the whole installer. A test that has to
# run the whole installer to exercise one copy is a test nobody runs.
#
# ---------------------------------------------------------------------------
# T116 — the staging copy
# ---------------------------------------------------------------------------
# `cp -R` on the DIRECTORY, never a list of files. scripts/activity/ holds
# phases.json and six static/ assets that are neither *.sh nor *.py (FR-51), and
# the file list is not stable: static/ grew from 4 files to 6 during this
# feature's own build when panels.js was split at 554 lines and stepper.js was
# split out after it. Any enumerated copy here would have silently shipped a
# dashboard missing two of its own modules, and would do it again at the next
# split. Enumerating a directory's contents is the bug; copying the directory
# is the fix.
#
# ---------------------------------------------------------------------------
# T118 — the shipped-hook manifest
# ---------------------------------------------------------------------------
# FR-61's "Smith ships this hook, your settings don't wire it" needs a
# "what Smith ships" side. FR-60 forbids the daemon from reading the repo
# fragment, and the daemon has no way to find a checkout anyway — it runs from
# ~/.smith. So the INSTALLER, which is standing in the checkout, writes what it
# actually saw in hooks/ to ~/.smith/activity/shipped-hooks.json.
#
# Derived from `ls hooks/*.sh`, never from a number in spec.md, plan.md or
# questions.md. Those documents said 9 while the repo shipped 20.
#
# Until this file exists the daemon reports "shipped-but-not-wired detection is
# unavailable" as a NOTICE rather than guessing — absence of the manifest reads
# as unknown, never as "nothing is shipped".

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"

SMITH_HOME="${SMITH_HOME:-$HOME/.smith}"

while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) sed -n '2,12p' "$0" | sed 's/^# *//'; exit 0 ;;
        *) ;;
    esac
    shift
done

info() { echo "  → $*"; }
ok()   { echo "  ✓ $*"; }
warn() { echo "  ! $*" >&2; }
err()  { echo "  ✗ $*" >&2; }

SRC="$REPO_ROOT/scripts/activity"
STAGED="$SMITH_HOME/scripts/activity"
ACTIVITY_DIR="$SMITH_HOME/activity"

[ -d "$SRC" ] || { err "$SRC not found — nothing to stage"; exit 1; }

# ---------------------------------------------------------------------------
# Stage the runtime (T116)
# ---------------------------------------------------------------------------
mkdir -p "$SMITH_HOME/scripts" "$ACTIVITY_DIR"

# Replaced wholesale rather than copied over, so a module deleted upstream does
# not linger in the staged tree and get imported forever. A running daemon
# keeps its open file handles through this and picks the new code up on its
# next restart — the same upgrade path every other staged script here takes.
rm -rf "$STAGED"
if ! cp -R "$SRC" "$SMITH_HOME/scripts/"; then
    err "Failed to stage $SRC → $STAGED"
    exit 1
fi

# Byte-compiled caches carry absolute paths from the checkout and are worthless
# at the install location — the same strip install.sh does for skills.
find "$STAGED" -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGED" -name "*.pyc" -delete 2>/dev/null || true

chmod +x "$STAGED"/*.sh 2>/dev/null || true
chmod +x "$STAGED"/*.py 2>/dev/null || true

STATIC_COUNT=$(find "$STAGED/static" -maxdepth 1 -type f 2>/dev/null | wc -l | tr -d ' ')
ok "Staged the /smith-activity runtime → $STAGED (${STATIC_COUNT:-0} static assets)"

# Report, never assume. If the tree that just landed is missing something the
# daemon cannot run without, say so here — at install time, in front of the
# operator — rather than leaving a 500 on first open.
for required in server.py daemon.py phases.json static/index.html; do
    [ -e "$STAGED/$required" ] || warn "staged tree is missing $required"
done

# ---------------------------------------------------------------------------
# Write the shipped-hook manifest (T118)
# ---------------------------------------------------------------------------
if ! command -v jq >/dev/null 2>&1; then
    warn "jq not found — shipped-hook manifest not written; FR-61 detection stays unavailable"
    exit 0
fi

MANIFEST="$ACTIVITY_DIR/shipped-hooks.json"
MANIFEST_TMP="$(mktemp)"

# `find … -name '*.sh'` mirrors install.sh's own copy loop exactly, so the
# manifest can never claim a hook the installer did not copy.
if find "$REPO_ROOT/hooks" -maxdepth 1 -type f -name '*.sh' -exec basename {} \; 2>/dev/null \
    | sort \
    | jq -R -s \
        --arg generated_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        --arg source "hooks/*.sh" \
        '{
           hooks: (split("\n") | map(select(length > 0))),
           generated_at: $generated_at,
           source: $source
         }' > "$MANIFEST_TMP" 2>/dev/null
then
    # Same write guard as install.sh's hook merge: tempfile → jq empty → mv.
    # A half-written manifest is worse than none: none reads as "unknown" and
    # suppresses the classification, while a truncated one would report every
    # hook it lost as shipped-but-not-wired.
    if [ -s "$MANIFEST_TMP" ] && jq empty "$MANIFEST_TMP" >/dev/null 2>&1; then
        mv "$MANIFEST_TMP" "$MANIFEST"
        SHIPPED_N=$(jq -r '.hooks | length' "$MANIFEST" 2>/dev/null || echo "?")
        ok "Wrote shipped-hook manifest ($SHIPPED_N hooks) → $MANIFEST"
    else
        rm -f "$MANIFEST_TMP"
        err "shipped-hook manifest produced invalid JSON — $MANIFEST left unchanged"
    fi
else
    rm -f "$MANIFEST_TMP"
    warn "could not enumerate hooks/ — shipped-hook manifest not written"
fi

exit 0
