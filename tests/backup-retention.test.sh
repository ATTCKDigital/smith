#!/usr/bin/env bash
# backup-retention.test.sh — regression tests for bounded backup retention.
#
# install.sh, install-hooks.sh and dedupe-settings.sh each write a timestamped
# backup of settings.json (and CLAUDE.md) before mutating it. None of them ever
# pruned, so the sidecars grew without bound — 56 files / 2.2MB on one machine.
# These tests lock in the keep-last-N behaviour.
#
# uninstall.sh restores from the NEWEST "$CLAUDE_SETTINGS".bak-*, so the newest
# backup must always survive a prune.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PASS=0
FAIL=0

assert() {
    if [ "$2" = "true" ]; then
        echo "PASS $1"; PASS=$((PASS+1))
    else
        echo "FAIL $1"; FAIL=$((FAIL+1))
    fi
}

# shellcheck source=../scripts/lib/prune-backups.sh
. "$REPO_ROOT/scripts/lib/prune-backups.sh"

TMP=$(mktemp -d -t backup-retention.XXXXXX)
trap 'rm -rf "$TMP"' EXIT

seed() {
    rm -f "$TMP"/settings.json.bak-* 2>/dev/null
    for i in 1 2 3 4 5 6 7 8; do
        printf 'backup %s\n' "$i" > "$TMP/settings.json.bak-2026010${i}-000000"
        # distinct mtimes, oldest first
        touch -t "2026010${i}0000" "$TMP/settings.json.bak-2026010${i}-000000"
    done
}

count() { ls -1 "$TMP"/settings.json.bak-* 2>/dev/null | wc -l | tr -d ' '; }
newest() { ls -1t "$TMP"/settings.json.bak-* 2>/dev/null | head -1; }

# --- Test 1: prunes down to the default keep (3) --------------------------
seed
[ "$(count)" = "8" ] && assert "fixture seeds 8 backups" true || assert "fixture seeds 8 backups" false
prune_backups "$TMP/settings.json.bak-*"
[ "$(count)" = "3" ] && assert "default keep is 3" true || assert "default keep is 3" false

# --- Test 2: the survivors are the NEWEST ones ----------------------------
REMAIN=$(ls -1t "$TMP"/settings.json.bak-* 2>/dev/null | xargs -n1 basename | sort | tr '\n' ' ')
[ "$REMAIN" = "settings.json.bak-20260106-000000 settings.json.bak-20260107-000000 settings.json.bak-20260108-000000 " ] \
    && assert "keeps the newest 3, deletes older" true \
    || assert "keeps the newest 3, deletes older (got: $REMAIN)" false

# --- Test 3: newest survives — uninstall.sh restore path stays usable -----
printf '%s' "$(newest)" | grep -q "20260108" \
    && assert "newest backup survives (uninstall restore path)" true \
    || assert "newest backup survives (uninstall restore path)" false

# --- Test 4: explicit keep honoured ---------------------------------------
seed
prune_backups "$TMP/settings.json.bak-*" 5
[ "$(count)" = "5" ] && assert "explicit keep=5 honoured" true || assert "explicit keep=5 honoured" false

# --- Test 5: keep is clamped to >= 1 (never wipe every backup) ------------
seed
prune_backups "$TMP/settings.json.bak-*" 0
[ "$(count)" = "1" ] && assert "keep=0 clamped to 1 (never wipes all)" true || assert "keep=0 clamped to 1 (never wipes all)" false
seed
prune_backups "$TMP/settings.json.bak-*" "garbage"
[ "$(count)" = "3" ] && assert "non-numeric keep falls back to 3" true || assert "non-numeric keep falls back to 3" false

# --- Test 6: idempotent, and no-op when already under the limit -----------
prune_backups "$TMP/settings.json.bak-*"
[ "$(count)" = "3" ] && assert "second prune is a no-op" true || assert "second prune is a no-op" false

# --- Test 7: no matches -> clean no-op, still exit 0 ----------------------
prune_backups "$TMP/does-not-exist-*" && assert "no matches returns success" true || assert "no matches returns success" false
prune_backups "" && assert "empty pattern returns success" true || assert "empty pattern returns success" false

# --- Test 8: safe under set -e (must not abort the caller) ---------------
( set -euo pipefail
  . "$REPO_ROOT/scripts/lib/prune-backups.sh"
  prune_backups "$TMP/no-such-glob-*"
  exit 0 ) >/dev/null 2>&1 \
    && assert "no-match prune is safe under set -e" true \
    || assert "no-match prune is safe under set -e" false

# --- Test 9: separator pools are independent (.bak- vs .bak.) ------------
printf 'x' > "$TMP/settings.json.bak.20260101T000000Z"
prune_backups "$TMP/settings.json.bak-*"
[ -f "$TMP/settings.json.bak.20260101T000000Z" ] \
    && assert ".bak.* pool untouched when pruning .bak-*" true \
    || assert ".bak.* pool untouched when pruning .bak-*" false

# --- Test 10: all four call sites are wired ------------------------------
WIRED=$(grep -l "prune_backups" "$REPO_ROOT"/scripts/install.sh "$REPO_ROOT"/scripts/install-hooks.sh "$REPO_ROOT"/scripts/dedupe-settings.sh 2>/dev/null | wc -l | tr -d ' ')
[ "$WIRED" = "3" ] && assert "all three scripts call prune_backups" true || assert "all three scripts call prune_backups" false
SITES=$(grep -c "prune_backups \"" "$REPO_ROOT"/scripts/install.sh 2>/dev/null)
[ "$SITES" = "2" ] && assert "install.sh prunes BOTH settings.json and CLAUDE.md" true || assert "install.sh prunes BOTH settings.json and CLAUDE.md" false

echo
echo "backup retention tests: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
