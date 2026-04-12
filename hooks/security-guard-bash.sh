#!/usr/bin/env bash
# security-guard-bash.sh
# Event: PreToolUse
# Matcher: Bash
# Scope: Universal — fires in both main session and sub-agents
#
# Intercepts Bash commands before execution. Blocks dangerous patterns,
# warns on risky operations, and auto-approves known-safe read-only commands.
# Logs all blocks and warnings to the vault session log.

set -uo pipefail

INPUT=$(cat)

# Extract command from tool_input
COMMAND=$(echo "$INPUT" | python3 -c "
import sys, json
data = json.load(sys.stdin)
ti = data.get('tool_input', {})
print(ti.get('command', ''))
" 2>/dev/null || echo "")

if [ -z "$COMMAND" ]; then
    exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
VAULT_DIR="$PROJECT_DIR/.smith/vault"
CURRENT_SESSION_FILE="$VAULT_DIR/.current-session"
CONFIG_FILE="$PROJECT_DIR/.smith/security-config.json"

# Load security config if it exists
WARN_ONLY="false"
ALLOWED_COMMANDS=""
PRODUCTION_DOMAINS=""
if [ -f "$CONFIG_FILE" ]; then
    WARN_ONLY=$(python3 -c "import json; d=json.load(open('$CONFIG_FILE')); print(str(d.get('warn_only_mode', False)).lower())" 2>/dev/null || echo "false")
    ALLOWED_COMMANDS=$(python3 -c "import json; d=json.load(open('$CONFIG_FILE')); print('\n'.join(d.get('allowed_commands', [])))" 2>/dev/null || echo "")
    PRODUCTION_DOMAINS=$(python3 -c "import json; d=json.load(open('$CONFIG_FILE')); print('\n'.join(d.get('production_domains', [])))" 2>/dev/null || echo "")
fi

# Helper: log to vault session log
log_security() {
    local action="$1" cmd="$2" pattern="$3" reason="$4"
    if [ -f "$CURRENT_SESSION_FILE" ]; then
        local session_file
        session_file=$(cat "$CURRENT_SESSION_FILE")
        if [ -f "$session_file" ]; then
            local now
            now=$(date -u +"%H:%M:%S")
            printf "\n### [%s] SECURITY: Command %s\n\n**Command:** \`%s\`\n**Pattern matched:** %s\n**Reason:** %s\n" \
                "$now" "$action" "$cmd" "$pattern" "$reason" >> "$session_file"
        fi
    fi
}

# Helper: deny response
deny() {
    local reason="$1" pattern="$2"
    log_security "blocked" "$COMMAND" "$pattern" "$reason"
    if [ "$WARN_ONLY" = "true" ]; then
        cat << EOJSON
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": "SMITH SECURITY WARNING (warn-only mode): $reason"
  }
}
EOJSON
        exit 0
    fi
    cat << EOJSON
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "SMITH SECURITY: $reason"
  }
}
EOJSON
    exit 2
}

# Helper: warn response (inform but don't block)
warn() {
    local reason="$1" pattern="$2"
    log_security "warned" "$COMMAND" "$pattern" "$reason"
    cat << EOJSON
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": "SMITH SECURITY WARNING: $reason"
  }
}
EOJSON
    exit 0
}

# Helper: auto-approve
approve() {
    cat << EOJSON
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow"
  }
}
EOJSON
    exit 0
}

# Check allowlist — if command matches an allowed pattern, pass through
if [ -n "$ALLOWED_COMMANDS" ]; then
    while IFS= read -r allowed; do
        if [ -n "$allowed" ] && echo "$COMMAND" | grep -qF "$allowed"; then
            exit 0
        fi
    done <<< "$ALLOWED_COMMANDS"
fi

# Lowercase command for case-insensitive matching
CMD_LOWER=$(echo "$COMMAND" | tr '[:upper:]' '[:lower:]')

# ============================================================
# AUTO-APPROVE: Known-safe read-only commands
# ============================================================

# Simple read-only commands
if echo "$COMMAND" | grep -qE '^\s*(ls|ls\s|head\s|tail\s|wc\s|which\s|whoami|pwd|date)\b'; then
    approve
fi

# Git read-only
if echo "$COMMAND" | grep -qE '^\s*git\s+(status|log|diff|branch|rev-parse|ls-remote|fetch|show|describe|tag\s+-l)\b'; then
    approve
fi

# Version checks
if echo "$COMMAND" | grep -qE '^\s*(node|python3|npm|pnpm|poetry|docker|go|cargo|rustc)\s+--version'; then
    approve
fi

# Docker read-only
if echo "$COMMAND" | grep -qE '^\s*docker\s+compose\s+(ps|logs)\b'; then
    approve
fi

# grep/find (read-only search)
if echo "$COMMAND" | grep -qE '^\s*(grep|find|rg)\s'; then
    approve
fi

# cat — approve unless targeting protected files (checked below)
if echo "$COMMAND" | grep -qE '^\s*cat\s'; then
    # Check if cat targets a protected file
    if echo "$COMMAND" | grep -qiE '\.(env|pem|key|p12|pfx|jks|keystore)\b'; then
        : # Fall through to security checks
    elif echo "$COMMAND" | grep -qiE '(credentials\.json|service-account)'; then
        : # Fall through
    else
        approve
    fi
fi

# ============================================================
# BLOCK: Destructive filesystem operations
# ============================================================

# rm -rf of root, home, or current directory
if echo "$COMMAND" | grep -qE 'rm\s+(-[a-zA-Z]*r[a-zA-Z]*f|(-[a-zA-Z]*f[a-zA-Z]*r))\s+(/|~/|\.\s|\./)(\s|$|;)'; then
    deny "Blocked 'rm -rf' on root/home/current directory. This would destroy critical data." "Recursive delete of root/home/cwd"
fi

# rm -rf with suspicious paths (.. traversal)
if echo "$COMMAND" | grep -qE 'rm\s+(-[a-zA-Z]*r[a-zA-Z]*f|(-[a-zA-Z]*f[a-zA-Z]*r))\s+.*\.\.'; then
    deny "Blocked 'rm -rf' with path traversal (..). Path may resolve outside project directory." "Path traversal in recursive delete"
fi

# chmod -R 777
if echo "$COMMAND" | grep -qE 'chmod\s+(-[a-zA-Z]*R[a-zA-Z]*\s+777|777\s+-[a-zA-Z]*R)'; then
    deny "Blocked 'chmod -R 777'. Overly permissive recursive permissions are a security risk." "Recursive chmod 777"
fi

# chown -R
if echo "$COMMAND" | grep -qE 'chown\s+-[a-zA-Z]*R'; then
    deny "Blocked recursive 'chown -R'. Ownership changes should be targeted, not recursive." "Recursive chown"
fi

# ============================================================
# BLOCK: Git dangers
# ============================================================

# git push --force (but not --force-with-lease)
if echo "$COMMAND" | grep -qE 'git\s+push\s+.*(-f\b|--force\b)' && ! echo "$COMMAND" | grep -q 'force-with-lease'; then
    deny "Blocked 'git push --force'. Force push can destroy remote history. Use 'git push --force-with-lease' instead." "Force push"
fi

# git reset --hard on main/master
if echo "$COMMAND" | grep -qE 'git\s+reset\s+--hard' && echo "$COMMAND" | grep -qE '(main|master)'; then
    deny "Blocked 'git reset --hard' on main/master. This discards all uncommitted changes irreversibly." "Hard reset on main"
fi

# git clean -fdx
if echo "$COMMAND" | grep -qE 'git\s+clean\s+.*-[a-zA-Z]*f[a-zA-Z]*d[a-zA-Z]*x'; then
    deny "Blocked 'git clean -fdx'. This removes all untracked and ignored files. Use 'git clean -fd' (without -x) or target specific files." "Aggressive git clean"
fi

# ============================================================
# BLOCK: Database destruction
# ============================================================

if echo "$CMD_LOWER" | grep -qE '\b(drop\s+(table|database|schema))\b'; then
    deny "Blocked destructive database operation (DROP). Execute manually outside Claude Code." "DROP TABLE/DATABASE/SCHEMA"
fi

if echo "$CMD_LOWER" | grep -qE '\btruncate\b'; then
    deny "Blocked TRUNCATE. This removes all rows from a table. Execute manually if intentional." "TRUNCATE"
fi

# DELETE FROM without WHERE
if echo "$CMD_LOWER" | grep -qE 'delete\s+from\s+\w+\s*[;$]' && ! echo "$CMD_LOWER" | grep -qiE '\bwhere\b'; then
    deny "Blocked 'DELETE FROM' without WHERE clause. This deletes all rows. Add a WHERE clause or execute manually." "DELETE without WHERE"
fi

# docker compose down -v (removes volumes)
if echo "$COMMAND" | grep -qE 'docker\s+compose\s+down\s+.*-v'; then
    deny "Blocked 'docker compose down -v'. The -v flag removes volumes and destroys persistent data. Use 'docker compose down' without -v." "Docker volume removal"
fi

# ============================================================
# BLOCK: Secret exposure
# ============================================================

# cat .env files
if echo "$COMMAND" | grep -qiE '(cat|less|more|head|tail)\s+.*\.env\b'; then
    deny "Blocked reading .env file. Environment files may contain secrets. Use specific variable references instead." "Reading .env file"
fi

# env / printenv
if echo "$COMMAND" | grep -qE '^\s*(env|printenv)\s*$'; then
    deny "Blocked 'env'/'printenv'. Dumping all environment variables may expose secrets. Query specific variables instead." "Environment dump"
fi

# echo with secret variable names
if echo "$COMMAND" | grep -qE 'echo\s+.*\$(API_KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL|PRIVATE_KEY)'; then
    deny "Blocked echo of potential secret variable. Avoid printing secrets to stdout." "Echo of secret variable"
fi

# ============================================================
# BLOCK: Pipe-to-shell
# ============================================================

if echo "$COMMAND" | grep -qE '(curl|wget)\s+.*\|\s*(bash|sh|zsh)'; then
    deny "Blocked piping remote content to shell. Download and inspect scripts before executing." "Pipe-to-shell (curl|bash)"
fi

# ============================================================
# BLOCK: Package risks
# ============================================================

if echo "$COMMAND" | grep -qE 'npm\s+install\s+https?://'; then
    deny "Blocked 'npm install' from URL. Install packages by name from the registry instead." "npm install from URL"
fi

if echo "$COMMAND" | grep -qE 'pip\s+install\s+https?://'; then
    deny "Blocked 'pip install' from URL. Install packages by name from PyPI instead." "pip install from URL"
fi

# ============================================================
# BLOCK: System access
# ============================================================

if echo "$COMMAND" | grep -qE '^\s*sudo\s'; then
    deny "Blocked sudo. Elevated privileges are not needed for development tasks." "sudo"
fi

if echo "$COMMAND" | grep -qE '(systemctl|launchctl)\s+(start|stop|restart|enable|disable|load|unload)'; then
    deny "Blocked system service modification. Modifying system services requires manual intervention." "System service modification"
fi

# ============================================================
# WARN: SSH connections
# ============================================================

if echo "$COMMAND" | grep -qE '^\s*ssh\s'; then
    HOST=$(echo "$COMMAND" | grep -oE '@[a-zA-Z0-9._-]+' | head -1 | sed 's/@//')
    warn "SSH connection detected to ${HOST:-unknown host}. Verify this is intentional. This command will proceed." "SSH connection"
fi

# ============================================================
# WARN: Production domain access
# ============================================================

if [ -n "$PRODUCTION_DOMAINS" ]; then
    while IFS= read -r domain; do
        if [ -n "$domain" ] && echo "$COMMAND" | grep -qF "$domain"; then
            warn "Accessing production domain '$domain'. Verify this is intentional." "Production domain access"
        fi
    done <<< "$PRODUCTION_DOMAINS"
fi

# ============================================================
# No pattern matched — pass through to normal permission flow
# ============================================================

exit 0
