#!/usr/bin/env bash
# dedupe-settings.sh
#
# Collapses duplicate hook entries in a Claude Code settings.json. Invoked by
# /smith-update before re-running install.sh, so users who accumulated
# duplicate Smith-owned hook entries from past installs get cleaned up.
#
# Duplicates arise because jq's merge in install.sh concatenated hook arrays
# without dedup before this PR. This script applies the same dedup filter
# now baked into install.sh, retroactively.
#
# Idempotent. Backs up the settings.json before mutating. Touches only the
# `hooks` namespace.
#
# Usage:
#   dedupe-settings.sh <path-to-settings.json>

set -uo pipefail

SETTINGS="${1:-$HOME/.claude/settings.json}"

if [ ! -f "$SETTINGS" ]; then
    echo "settings.json not found at $SETTINGS" >&2
    exit 0
fi

if ! command -v jq >/dev/null 2>&1; then
    echo "jq required for dedupe-settings.sh" >&2
    exit 1
fi

BACKUP="${SETTINGS}.predupe-$(date +%Y%m%d-%H%M%S)"
cp "$SETTINGS" "$BACKUP"

TMP=$(mktemp)
jq '
  if .hooks then
    .hooks |= (
      to_entries
      | map({
          key: .key,
          value: (.value | unique_by(.matcher + "|" + (.hooks | tostring)))
        })
      | from_entries
    )
  else . end
' "$SETTINGS" > "$TMP"

# Sanity: file must remain valid JSON
if ! jq empty "$TMP" >/dev/null 2>&1; then
    echo "dedupe produced invalid JSON; aborting (backup at $BACKUP)" >&2
    rm -f "$TMP"
    exit 2
fi

mv "$TMP" "$SETTINGS"
echo "Deduped hook entries in $SETTINGS (backup: $BACKUP)"
