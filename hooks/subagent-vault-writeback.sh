#!/usr/bin/env bash
# subagent-vault-writeback.sh
# Event: SubagentStop
# Scope: Sub-agents only
#
# Writes sub-agent findings back to .smith/vault/agents/<type>/<identifier>.md
# on sub-agent completion. Extracts type from the agent description or defaults
# to "general".

set -euo pipefail

# Consume stdin (hook input JSON)
INPUT=$(cat)

VAULT_DIR="$CLAUDE_PROJECT_DIR/.smith/vault"
AGENTS_DIR="$VAULT_DIR/agents"

# Timestamp
NOW_ISO=$(date -u +"%Y-%m-%dT%H:%M:%S")

# Extract identifier (agent name or id)
IDENTIFIER=$(echo "$INPUT" | grep -o '"agent_name"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"agent_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/' || echo "")
if [ -z "$IDENTIFIER" ]; then
    IDENTIFIER=$(echo "$INPUT" | grep -o '"identifier"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"identifier"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/' || echo "unknown")
fi

# Extract description
DESCRIPTION=$(echo "$INPUT" | grep -o '"description"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"description"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/' || echo "")

# Determine agent type from description or identifier
AGENT_TYPE="general"
DESC_LOWER=$(echo "$DESCRIPTION $IDENTIFIER" | tr '[:upper:]' '[:lower:]')

if echo "$DESC_LOWER" | grep -q "image\|screenshot\|visual"; then
    AGENT_TYPE="image-analysis"
elif echo "$DESC_LOWER" | grep -q "review\|architect\|audit"; then
    AGENT_TYPE="code-review"
elif echo "$DESC_LOWER" | grep -q "implement\|build\|write\|create\|fix"; then
    AGENT_TYPE="implementation"
elif echo "$DESC_LOWER" | grep -q "search\|explore\|find\|research\|read"; then
    AGENT_TYPE="exploration"
elif echo "$DESC_LOWER" | grep -q "test\|qa\|quality"; then
    AGENT_TYPE="testing"
fi

# Create agent type directory
mkdir -p "$AGENTS_DIR/$AGENT_TYPE"

# Sanitize identifier for filename (replace non-alphanumeric with dashes)
SAFE_ID=$(echo "$IDENTIFIER" | sed 's/[^a-zA-Z0-9._-]/-/g' | head -c 100)
if [ -z "$SAFE_ID" ]; then
    SAFE_ID="unknown"
fi

AGENT_FILE="$AGENTS_DIR/$AGENT_TYPE/${SAFE_ID}.md"

# Extract result/output (truncate to first 500 lines)
RESULT=$(echo "$INPUT" | grep -o '"result"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"result"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/' || echo "No result captured")

# Append entry
cat >> "$AGENT_FILE" << EOF

### Invocation — $NOW_ISO

**Task:** $DESCRIPTION

**Findings:**
$RESULT

---
EOF

exit 0
