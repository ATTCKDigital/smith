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
- The kill-switch denial can be downgraded to a warning by `warn_only_mode`, same as the other two guards. The production confirm-gate denial cannot — it is the sole non-bypassable denial among Smith's three `PreToolUse` guard hooks, regardless of `warn_only_mode`. (See [Code-Content Security Review](#code-content-security-review) below for a second, independent non-bypassable denial that sits outside the guard-hook layer entirely.)
- Reads `.smith/security-config.json`'s `browser_verification.urls`/`allow_interactions` keys (never `.smith/config.json`'s `mcp_mode`, which is agent-read only). No-ops silently — never blocks, never errors — when the vault or the config file is absent.

See `data-model.md` in the `53-mcp-browser-access` feature spec for the full decision table.

### Customizing guards

All three guards are plain bash scripts in `~/.claude/hooks/`. You can edit them to add or remove patterns. If you modify them, keep the deny-by-default philosophy: block first, allow explicitly.

---

## Code-Content Security Review

The three guard hooks above inspect **action intent** — what a tool call is about to do — before it happens. The Security Review Pass is different: it runs inside `smith-build` (and, in a narrower form, `smith-bugfix`) and inspects **diff content** — what the code itself says — evaluating the full branch diff against `$BASE_BRANCH` exactly once per run, never on a per-tool-call basis.

### Three layers

1. **Layer 1 — built-in secret scan (always runs).** `scripts/security/secret-scan.sh` (wrapper) plus `scripts/security/secret_scan.py` (pattern/entropy engine) scan the diff for hard-coded credentials: AWS access-key and STS temp-key IDs, AWS secret keys, GCP service-account JSON markers, PEM private-key headers, GitHub tokens, Slack tokens, generic high-entropy token-shaped assignments, and connection-string credentials. When `gitleaks` is present on `$PATH` (detected by `scripts/security/detect-scanners.sh`), its findings are merged in additively alongside the built-in scanner's own. A same-line `# smith-secret-scan: allow` comment is the sole false-positive remedy, applied before the scan runs, not after a finding is produced.
2. **Layer 2 — SAST (presence-detected, conditional).** If `semgrep` and/or `bandit` are found on `$PATH`, they run against the same diff scope; if neither is present, this layer is silently skipped. Smith never installs either tool as a dependency of itself or of a consuming project.
3. **Layer 3 — LLM review (always runs).** A single `opus`-pinned subagent (override via the `security_review.review_model` config key) evaluates the full diff against a fixed 10-area rubric: injection (SQL/command/template), authentication/authorization flaws, secrets/credential handling, unsafe deserialization or `eval`-family use, path traversal, SSRF and unvalidated redirects, cryptographic misuse, sensitive-data logging or exposure, dependency-adjacent code smells (non-CVE, not dependency/CVE scanning), and race conditions/TOCTOU in security-relevant paths.

Every finding from every layer carries a severity, `path:line`, category, a short rationale, and its originating layer. The Security Review Pass never auto-fixes anything, for any finding, from any layer, under any configuration.

### The terminate rule

A **Critical finding from Layer 1** (a detected secret) always terminates the build before Phase 4 — unconditionally, regardless of the configured `enforcement_tier`, and with no runtime-confirmation escape hatch. This makes it Smith's **second** non-bypassable denial, after the browser-production confirm-gate documented above; unlike that gate, there is no confirmation artifact that can later "unblock" a terminated run — the allowlist marker is the sole remedy, and it must be applied before the scan runs, not after a finding is produced.

Every other finding is flag-only under the shipped default (`enforcement_tier: "flag"`): Layer 1 non-Critical findings, and every Layer 2/Layer 3 finding regardless of severity, are listed in the PR body and never block, delay, or gate PR creation. A project may opt into `enforcement_tier: "block_on_critical"`, which additionally terminates on a Critical Layer 2 or Layer 3 finding — Layer 1's Critical-secret termination is unconditional either way and is not governed by this setting.

`smith-bugfix` runs Layer 1 only, with the same unconditional terminate semantics, immediately before its commit step; Layer 2 and Layer 3 never run there, keeping its pipeline lightweight.

### Scanner presence, disclosed honestly

Whenever a build's PR body includes a "Security Review" section, that section states which layers actually ran versus were skipped for absence (`gitleaks`, `semgrep`, `bandit`) — it never implies full-coverage scanning when one of those tools was silently absent from the machine that ran the build.

### Config home

The `security_review` key lives in `.smith/config.json` only — see `data-model.md` §1 in the `55-security-review-pass` feature spec for the exact schema. It is distinct from the pre-existing `security` block already in the same file, which BANK-027 confirms no guard hook actually reads, and from `.smith/security-config.json` (the guard-hook config used by the section above). `/smith` init and `/smith-update` both seed `security_review` non-destructively, including into an already-existing `.smith/config.json`.

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

Before enabling the scheduler or relying on the security guards, review these seven files:

1. **`~/.claude/hooks/security-guard-bash.sh`** -- Review the blocklist patterns. Confirm they cover the commands you consider dangerous in your environment. Add any project-specific patterns.

2. **`~/.claude/hooks/security-guard-files.sh`** -- Review the blocked file paths. Add any project-specific sensitive files (database configs, API key files, deployment manifests with secrets).

3. **`~/.smith/scheduler/smith-scheduler.sh`** -- Review the task selection logic and worktree creation. Confirm you are comfortable with the scheduler creating branches and worktrees in your registered projects.

4. **`~/.claude/hooks/security-guard-mcp-browser.sh`** -- Review the interaction-tool policy (`browser_verification.allow_interactions`, staging/production classification in `.smith/security-config.json`) and confirm the production-confirmation requirement matches your risk tolerance -- this is the one denial among the three guard hooks that `warn_only_mode` cannot downgrade or bypass.

5. **`~/.smith/scripts/security/secret-scan.sh`** -- Review the built-in exclude-path set (`vendor/`, `node_modules/`, `.venv/`, `dist/`, `build/`, `.smith/`) and the gitleaks-merge behavior. Confirm the `security_review.excludes`/`allowlist_globs` keys in your project's `.smith/config.json` match what you actually want scanned.

6. **`~/.smith/scripts/security/secret_scan.py`** -- Review the pattern catalogue and the entropy threshold for the generic high-entropy heuristic. Confirm the redaction behavior (masked excerpts only, never a secret's real value) matches your team's expectations for what may appear in a PR body or the vault session log.

7. **`~/.smith/scripts/security/detect-scanners.sh`** -- Review the presence-detection list (`gitleaks`, `semgrep`, `bandit`) and confirm it matches which scanners you actually expect Layer 2 to pick up on your machine or CI runner -- remember that a Layer 1 Critical secret finding terminates the build regardless of what this script detects; see [Code-Content Security Review](#code-content-security-review) above.

---

## Reporting Vulnerabilities

If you discover a security vulnerability in Smith, do not open a public issue. Instead, email **tech@attck.com** with a description of the vulnerability, steps to reproduce, and any relevant log output. See [SECURITY.md](../SECURITY.md) for the full disclosure policy.
