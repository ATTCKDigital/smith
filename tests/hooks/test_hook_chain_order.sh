#!/usr/bin/env bash
# test_hook_chain_order.sh — assert manifest-updater.sh is registered LAST
# in the PostToolUse Write|Edit chain (Decision 7 + Risk R2).

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
INSTALLER="$REPO_ROOT/scripts/install-hooks.sh"
PASS=0
FAIL=0

assert() {
    if [ "$2" = "true" ]; then
        echo "PASS $1"
        PASS=$((PASS+1))
    else
        echo "FAIL $1"
        FAIL=$((FAIL+1))
    fi
}

# --- Test 1: fresh install puts manifest-updater LAST --------------------
TMP=$(mktemp -d -t hco.XXXXXX)
trap 'rm -rf "$TMP"' EXIT
cat > "$TMP/settings.json" <<'EOF'
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          { "type": "command", "command": "bash ~/.claude/hooks/lint-on-save.sh" }
        ]
      }
    ]
  }
}
EOF

bash "$INSTALLER" --settings "$TMP/settings.json" >/dev/null 2>&1
LAST=$(python3 -c "
import json
data = json.load(open('$TMP/settings.json'))
for b in data['hooks']['PostToolUse']:
    if b.get('matcher') == 'Write|Edit':
        print(b['hooks'][-1]['command'])
")
if echo "$LAST" | grep -q manifest-updater.sh; then
    assert "fresh install: manifest-updater LAST" true
else
    assert "fresh install: manifest-updater LAST (got: $LAST)" false
fi

# --- Test 2: re-running is idempotent (no duplicates) -------------------
bash "$INSTALLER" --settings "$TMP/settings.json" >/dev/null 2>&1
COUNT=$(python3 -c "
import json
data = json.load(open('$TMP/settings.json'))
c = 0
for b in data['hooks']['PostToolUse']:
    for h in b.get('hooks', []):
        if 'manifest-updater' in h.get('command', ''):
            c += 1
print(c)
")
[ "$COUNT" = "1" ] && assert "idempotent: only 1 manifest-updater entry" true \
    || assert "idempotent: only 1 manifest-updater entry (count=$COUNT)" false

# --- Test 3: wrong-order existing config gets re-ordered ----------------
cat > "$TMP/settings.json" <<'EOF'
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          { "type": "command", "command": "bash ~/.claude/hooks/manifest-updater.sh" },
          { "type": "command", "command": "bash ~/.claude/hooks/lint-on-save.sh" }
        ]
      }
    ]
  }
}
EOF
bash "$INSTALLER" --settings "$TMP/settings.json" >/dev/null 2>&1
LAST=$(python3 -c "
import json
data = json.load(open('$TMP/settings.json'))
for b in data['hooks']['PostToolUse']:
    if b.get('matcher') == 'Write|Edit':
        print(b['hooks'][-1]['command'])
")
if echo "$LAST" | grep -q manifest-updater.sh; then
    assert "re-order: manifest-updater moved to LAST" true
else
    assert "re-order: manifest-updater moved to LAST (got: $LAST)" false
fi

# --- Test 4: context-loader registered exactly once ---------------------
CTX_COUNT=$(python3 -c "
import json
data = json.load(open('$TMP/settings.json'))
c = 0
for b in data['hooks'].get('UserPromptSubmit', []):
    for h in b.get('hooks', []):
        if 'context-loader' in h.get('command', ''):
            c += 1
print(c)
")
[ "$CTX_COUNT" = "1" ] && assert "context-loader registered exactly once" true \
    || assert "context-loader registered exactly once (count=$CTX_COUNT)" false

# --- Test 5: --no-hooks skips registration ------------------------------
cat > "$TMP/settings2.json" <<'EOF'
{ "hooks": {} }
EOF
bash "$INSTALLER" --settings "$TMP/settings2.json" --no-hooks >/dev/null 2>&1
ANY=$(python3 -c "
import json
data = json.load(open('$TMP/settings2.json'))
s = json.dumps(data)
print('1' if 'manifest-updater' in s or 'context-loader' in s else '0')
")
[ "$ANY" = "0" ] && assert "--no-hooks does not register" true \
    || assert "--no-hooks does not register" false

# --- Test 6: --uninstall removes entries --------------------------------
bash "$INSTALLER" --settings "$TMP/settings.json" --uninstall >/dev/null 2>&1
LEFT=$(python3 -c "
import json
data = json.load(open('$TMP/settings.json'))
s = json.dumps(data)
print('1' if 'manifest-updater' in s or 'context-loader' in s else '0')
")
[ "$LEFT" = "0" ] && assert "--uninstall removes entries" true \
    || assert "--uninstall removes entries" false

echo
echo "hook chain order tests: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
