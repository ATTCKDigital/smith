#!/usr/bin/env bash
# settings-dedupe.test.sh — regression tests for hook-entry deduplication.
#
# Claude Code runs every command in every entry of an event's array. The unit
# that must be unique is the individual (matcher, command) pair, not the entry:
# the same commands regrouped across fragment versions produce distinct entry
# keys, so entry-level dedup left commands registered — and running — several
# times per Stop. These tests lock in command-level dedup.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEDUPE="$REPO_ROOT/scripts/dedupe-settings.sh"
PASS=0
FAIL=0

assert() {
    if [ "$2" = "true" ]; then
        echo "PASS $1"; PASS=$((PASS+1))
    else
        echo "FAIL $1"; FAIL=$((FAIL+1))
    fi
}

TMP=$(mktemp -d -t settings-dedupe.XXXXXX)
trap 'rm -rf "$TMP"' EXIT

# Settings shaped like a machine that accumulated several fragment generations:
# the same commands grouped differently in each generation.
cat > "$TMP/settings.json" <<'JSON'
{
  "hooks": {
    "Stop": [
      { "matcher": "*", "hooks": [
        { "type": "command", "command": "bash ~/.claude/hooks/grade-response.sh" } ] },
      { "matcher": "*", "hooks": [
        { "type": "command", "command": "bash ~/.claude/hooks/session-end-review.sh" },
        { "type": "command", "command": "bash ~/.claude/hooks/active-workflow-janitor.sh" },
        { "type": "command", "command": "bash ~/.claude/hooks/workflow-summary.sh" } ] },
      { "matcher": "*", "hooks": [
        { "type": "command", "command": "bash ~/.claude/hooks/session-end-review.sh" },
        { "type": "command", "command": "bash ~/.claude/hooks/workflow-summary.sh" },
        { "type": "command", "command": "bash ~/.claude/hooks/active-workflow-janitor.sh" },
        { "type": "command", "command": "bash ~/.claude/hooks/grade-response.sh" } ] },
      { "matcher": "*", "hooks": [
        { "type": "command", "command": "bash ~/.claude/hooks/session-end-review.sh" },
        { "type": "command", "command": "bash ~/.claude/hooks/workflow-summary.sh" } ] },
      { "matcher": "*", "hooks": [
        { "type": "command", "command": "bash ~/.claude/hooks/stamp-response.sh" } ] }
    ],
    "PostToolUse": [
      { "matcher": "Write|Edit", "hooks": [
        { "type": "command", "command": "bash ~/.claude/hooks/lint-on-save.sh" },
        { "type": "command", "command": "bash ~/.claude/hooks/manifest-updater.sh" } ] },
      { "matcher": "*", "hooks": [
        { "type": "command", "command": "bash ~/.claude/hooks/lint-on-save.sh" } ] }
    ]
  }
}
JSON

max_dup() {
    jq -r '.hooks | to_entries[] | .key as $e | .value[] | .matcher as $m
           | .hooks[] | "\($e)|\($m)|\(.command)"' "$1" \
      | sort | uniq -c | sort -rn | head -1 | awk '{print $1}'
}

count_cmd() {
    jq -r --arg c "$2" '[.hooks.Stop[].hooks[].command | select(test($c))] | length' "$1"
}

# --- Test 1: duplicates exist in the fixture -----------------------------
[ "$(max_dup "$TMP/settings.json")" -gt 1 ] \
    && assert "fixture starts with duplicates" true \
    || assert "fixture starts with duplicates" false

bash "$DEDUPE" "$TMP/settings.json" >/dev/null 2>&1

# --- Test 2: every (event, matcher, command) is unique -------------------
[ "$(max_dup "$TMP/settings.json")" = "1" ] \
    && assert "no command registered twice in any event" true \
    || assert "no command registered twice in any event" false

# --- Test 3: nothing was lost -------------------------------------------
for cmd in grade-response session-end-review active-workflow-janitor workflow-summary stamp-response; do
    [ "$(count_cmd "$TMP/settings.json" "$cmd")" = "1" ] \
        && assert "$cmd wired exactly once" true \
        || assert "$cmd wired exactly once" false
done

# --- Test 4: a different matcher is NOT collapsed into another -----------
KEPT=$(jq -r '[.hooks.PostToolUse[] | select(.matcher == "*") | .hooks[].command] | length' "$TMP/settings.json")
[ "$KEPT" = "1" ] \
    && assert "same command under a different matcher is preserved" true \
    || assert "same command under a different matcher is preserved" false

# --- Test 5: chain order preserved (manifest-updater stays last) ---------
LAST=$(jq -r '[.hooks.PostToolUse[] | select(.matcher == "Write|Edit") | .hooks[].command] | last' "$TMP/settings.json")
printf '%s' "$LAST" | grep -q "manifest-updater" \
    && assert "hook chain order is preserved" true \
    || assert "hook chain order is preserved" false

# --- Test 6: idempotent ---------------------------------------------------
BEFORE=$(jq -S . "$TMP/settings.json")
bash "$DEDUPE" "$TMP/settings.json" >/dev/null 2>&1
AFTER=$(jq -S . "$TMP/settings.json")
[ "$BEFORE" = "$AFTER" ] \
    && assert "second run is a no-op" true \
    || assert "second run is a no-op" false

# --- Test 7: valid JSON, non-hook keys untouched -------------------------
cat > "$TMP/other.json" <<'JSON'
{ "model": "opus", "env": {"FOO": "bar"} }
JSON
bash "$DEDUPE" "$TMP/other.json" >/dev/null 2>&1
jq -e '.model == "opus" and .env.FOO == "bar"' "$TMP/other.json" >/dev/null 2>&1 \
    && assert "settings without hooks are left intact" true \
    || assert "settings without hooks are left intact" false

echo
echo "settings dedupe tests: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
