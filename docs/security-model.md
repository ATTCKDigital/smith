# Security Model

Smith is designed with a local-first, deny-by-default security posture. This document covers what Smith can and cannot do, how its security guards work, and what you should audit before enabling autonomous features.

---

## Local-Only Execution

Smith runs entirely on your machine. There is no telemetry, no phone-home, no analytics, and no external API calls made by Smith itself. All vault data, session logs, and scheduler output stay in your local filesystem.

The only network activity comes from Claude Code itself (communicating with the Anthropic API), which is governed by your Claude Code configuration and authentication, not by Smith.

---

## Hook Security

Hooks are bash scripts that Claude Code executes automatically at specific lifecycle events. Each hook is registered in `~/.claude/settings.json` and runs with your user permissions.

### What hooks can access

- The current working directory and its contents
- Environment variables available to your shell
- The `.smith/vault/` directory in the current project
- Standard CLI tools (git, jq, bash builtins)

### What hooks cannot do

- Hooks cannot escalate privileges beyond your user account
- Hooks do not have network access beyond what your shell provides
- Hooks cannot modify Claude Code's own configuration at runtime

### Hook event types

| Event | When it fires | Hooks using it |
|-------|--------------|----------------|
| SessionStart | Claude Code session begins | session-start-logger |
| Stop | Claude Code session ends | session-end-review |
| PreToolUse | Before Claude executes a tool call | security-guard-bash, security-guard-files, security-guard-mcp-browser, task-router |
| PostToolUse | After Claude executes a tool call | file-change-logger, lint-on-save |
| SubagentStop | When a sub-agent completes | subagent-vault-writeback |

See [Hooks Reference](hooks.md) for full details on each hook.

---

## Security Guards

Smith ships three security guard hooks that implement a deny-by-default approach:

### security-guard-bash.sh (PreToolUse, Bash)

Inspects every Bash command before execution and blocks patterns that are commonly dangerous or leak sensitive data:

- Destructive filesystem operations (`rm -rf /`, `rm -rf ~`, etc.)
- Environment variable dumps that could expose secrets
- Direct echoing of secret/credential variables
- Commands that attempt to disable or bypass other hooks

The guard uses a blocklist of known-dangerous patterns. Commands not matching any blocked pattern are allowed through.

### security-guard-files.sh (PreToolUse, Write/Edit)

Inspects every file write or edit before execution and blocks writes to sensitive file paths:

- `.env` files and variants (`.env.local`, `.env.production`, etc.)
- Credential files (`credentials.json`, `*.pem`, `*.key`)
- SSH configuration and keys (`~/.ssh/*`)
- Claude Code's own configuration files

The guard uses an allowlist approach for the vault directory (writes to `.smith/vault/` are always permitted) and a blocklist for known sensitive paths.

### security-guard-mcp-browser.sh (PreToolUse, mcp__playwright__)

Inspects every Playwright MCP browser tool call before execution:

- Read-only tools (`browser_navigate`, `browser_snapshot`, `browser_take_screenshot`, `browser_console_messages`, `browser_network_requests`, `browser_wait_for`, `browser_tabs`) always run, on any target, including production.
- Interaction tools (`browser_click`, `browser_type`, `browser_fill_form`, `browser_select_option`, `browser_press_key`, `browser_drag`, `browser_hover`, and `browser_evaluate` — always interaction-class, no JS-source heuristic) are denied outright when `browser_verification.allow_interactions` is `false` (a project-level kill-switch), and denied against a production-labeled or unclassified target (fail-safe default) unless a matching human confirmation was already recorded for that exact target.
- The kill-switch denial can be downgraded to a warning by `warn_only_mode`, same as the other two guards. The production confirm-gate denial cannot — it is the sole non-bypassable denial across all three guards, regardless of `warn_only_mode`.
- Reads `.smith/security-config.json`'s `browser_verification.urls`/`allow_interactions` keys (never `.smith/config.json`'s `mcp_mode`, which is agent-read only). No-ops silently — never blocks, never errors — when the vault or the config file is absent.

See `data-model.md` in the `53-mcp-browser-access` feature spec for the full decision table.

### Customizing guards

All three guards are plain bash scripts in `~/.claude/hooks/`. You can edit them to add or remove patterns. If you modify them, keep the deny-by-default philosophy: block first, allow explicitly.

---

## Scheduler Security

The scheduler (`~/.smith/scheduler/smith-scheduler.sh`) enables autonomous overnight processing of queued tasks. Because it runs without user interaction, it has additional constraints:

- **Runs as your user** -- The scheduler is a macOS LaunchAgent, running under your account with your permissions. It does not require or use root access.
- **Only processes autonomous tasks** -- The scheduler only picks up tasks in the vault queue that are explicitly marked with `"mode": "autonomous"`. Interactive or untagged tasks are skipped.
- **Git worktree isolation** -- Each task runs in a fresh git worktree, not in your working directory. This prevents autonomous work from conflicting with your in-progress changes.
- **Non-interactive Claude** -- The scheduler invokes Claude Code with the `-p` flag (non-interactive mode). Claude cannot prompt for input; if it encounters ambiguity, the task fails rather than guessing.
- **Scoped to registered projects** -- The scheduler only processes projects listed in `~/.smith/scheduler/projects.json`. It does not scan your filesystem.

---

## What to Audit Before Enabling

Before enabling the scheduler or relying on the security guards, review these four files:

1. **`~/.claude/hooks/security-guard-bash.sh`** -- Review the blocklist patterns. Confirm they cover the commands you consider dangerous in your environment. Add any project-specific patterns.

2. **`~/.claude/hooks/security-guard-files.sh`** -- Review the blocked file paths. Add any project-specific sensitive files (database configs, API key files, deployment manifests with secrets).

3. **`~/.smith/scheduler/smith-scheduler.sh`** -- Review the task selection logic and worktree creation. Confirm you are comfortable with the scheduler creating branches and worktrees in your registered projects.

4. **`~/.claude/hooks/security-guard-mcp-browser.sh`** -- Review the interaction-tool policy (`browser_verification.allow_interactions`, staging/production classification in `.smith/security-config.json`) and confirm the production-confirmation requirement matches your risk tolerance -- this is the one denial in all of Smith's guards that `warn_only_mode` cannot downgrade or bypass.

---

## Reporting Vulnerabilities

If you discover a security vulnerability in Smith, do not open a public issue. Instead, email **tech@attck.com** with a description of the vulnerability, steps to reproduce, and any relevant log output. See [SECURITY.md](../SECURITY.md) for the full disclosure policy.
