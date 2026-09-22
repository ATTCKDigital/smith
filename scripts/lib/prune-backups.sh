#!/usr/bin/env bash
# prune-backups.sh — bounded retention for timestamped backup files.
#
# install.sh, install-hooks.sh and dedupe-settings.sh each copy settings.json
# (and CLAUDE.md) to a timestamped sidecar before mutating it, but none of them
# ever removed an old one, so the sidecars grew without limit — 56 files / 2.2MB
# on one machine after four months. The ~/.smith/.backups snapshot directory
# already keeps only the last 3; this applies the same bound to the per-run
# sidecars.
#
# Source it, then call:
#     prune_backups "<glob>" [keep]
#
# Keeps the `keep` newest matches (default 3) and deletes the rest. Safe under
# `set -euo pipefail` and a no-op when the glob matches nothing.
#
# NOTE: uninstall.sh restores from the NEWEST "$CLAUDE_SETTINGS".bak-* and
# "$CLAUDE_MD".bak-*, so `keep` must always be >= 1 to leave it something to
# restore from.

# shellcheck disable=SC2086  # $pattern must stay unquoted so the glob expands.
prune_backups() {
    pattern="${1:-}"
    keep="${2:-3}"

    [ -n "$pattern" ] || return 0
    case "$keep" in
        ''|*[!0-9]*) keep=3 ;;
    esac
    [ "$keep" -ge 1 ] || keep=1

    stale=$(ls -1t $pattern 2>/dev/null | tail -n +$((keep + 1)) || true)
    [ -n "$stale" ] || return 0

    printf '%s\n' "$stale" | while IFS= read -r old; do
        [ -n "$old" ] && [ -f "$old" ] && rm -f "$old"
    done

    return 0
}
