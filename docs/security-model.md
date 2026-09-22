# Security Model

Smith is designed with a local-first, deny-by-default security posture. This document covers what Smith can and cannot do, how its security guards work, and what you should audit before enabling autonomous features.

---

## Local-Only Execution

Smith runs entirely on your machine. There is no telemetry, no phone-home, no analytics, and no external API calls made by Smith itself. All vault data, session logs, and scheduler output stay in your local filesystem.

The only *outbound* network activity comes from Claude Code itself (communicating with the Anthropic API), which is governed by your Claude Code configuration and authentication, not by Smith.

**One local socket, since the activity dashboard.** "No external API calls" remains true and is not a hedge — but `/smith-activity` runs a daemon that **listens**, which is a genuinely new kind of surface for Smith and is called out here rather than buried. It binds `127.0.0.1` as a hardcoded module constant with no flag, argument or config key that can change it; it makes no outbound request of any kind; and the only thing that ever connects to it is a hook on the same machine posting to loopback. It is off until you run `/smith-activity`, and `/smith-activity stop` ends it. The full surface is in [Activity Daemon Security](#activity-daemon-security) below.

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

## Supply-Chain & License Review

The Code-Content Security Review Pass above inspects diff content for hard-coded secrets, SAST findings, and LLM-reviewed vulnerability classes. The Supply-Chain & License Review Pass is different again: it runs inside `smith-build` as `## Phase 3.7: Supply-Chain Review Pass`, strictly after the Code-Content Security Review Pass and before Phase 4, and inspects the full project's dependency manifests -- not the branch diff -- exactly once per build.

### Two sub-layers

1. **Sub-layer D -- dependency CVE scan.** `scripts/security/dependency-scan.py` (wrapped by `dependency-scan.sh`) discovers every `package.json`/`pyproject.toml`/`requirements.txt`/`go.mod`/`Cargo.toml` manifest in the repository, prefers a single whole-repo pass from `osv-scanner` or `trivy` when either is present, and otherwise falls back per manifest to `npm audit` (npm, lockfile-gated) or `pip-audit` (poetry/pip). `grype`'s presence is detected and disclosed but never invoked by this v1.
2. **Sub-layer L -- dependency-free license inventory.** `scripts/security/license-inventory.py` (wrapped by `license-inventory.sh`) walks `node_modules/` for npm packages and each poetry manifest's environment (via `poetry run python3` + `importlib.metadata`, never system Python) for Python packages, merges the results into a repo-wide license inventory, and flags any package whose license matches a configured `supply_chain.license_policy.deny` entry.

Both sub-layers read manifests through the same shared discovery module (`_manifest_discovery.py`), so they never disagree about what counts as a manifest.

### No redaction -- by design

Unlike the Code-Content Security Review Pass, findings here carry no secret-shaped content -- a CVE advisory ID and a license identifier are not sensitive values -- so there is no masking/excerpt-redaction step anywhere in this pass. Worth stating explicitly so a reader does not wonder why this section has no redaction guarantee to point to.

### Flag-only -- no terminate path, ever

This pass has no decision table and no terminate branch of any kind, unlike the Code-Content Security Review Pass above: no severity from either sub-layer -- not even a Critical CVE with a known exploit, not even a deny-listed license on a production package -- can block, delay, or terminate the workflow. Smith's two non-bypassable denials remain exactly the ones documented above (the browser-production confirm-gate, and a Layer 1 Critical secret finding in the Code-Content Security Review Pass); this pass introduces no third one, and no `supply_chain` config field can ever create one -- there is no `enforcement_tier`-shaped key in its schema.

### Honest disclosure

Whenever a build's PR body includes a "Supply-Chain Review" section, it states plainly that the scan is full-project, not diff-scoped (findings may predate the change), and discloses per-manifest which scan path actually ran versus was skipped and why (`absent`, `enolock`, `enolock_wrong_format`, `no_node_modules`, `no_venv`, `timeout`, `offline`, `disabled`) -- it never implies full scanner coverage when a tool or manifest was actually skipped.

### Config home

The `supply_chain` key lives in `.smith/config.json`, a sibling of `security_review`, never nested under it -- see `data-model.md` §1 in the `56-supply-chain-gate` feature spec for the exact schema. `/smith` init and `/smith-update` both seed `supply_chain` non-destructively, including into an already-existing `.smith/config.json`.

---

## Scheduler Security

The scheduler (`~/.smith/scheduler/smith-scheduler.sh`) enables autonomous overnight processing of queued tasks. Because it runs without user interaction, it has additional constraints:

- **Runs as your user** -- The scheduler is a macOS LaunchAgent, running under your account with your permissions. It does not require or use root access.
- **Only processes autonomous tasks** -- The scheduler only picks up tasks in the vault queue that are explicitly marked with `complexity: autonomous`. Interactive or untagged tasks are skipped.
- **Git worktree isolation** -- Each task runs in a fresh git worktree, not in your working directory. This prevents autonomous work from conflicting with your in-progress changes.
- **Non-interactive Claude** -- The scheduler invokes Claude Code with the `-p` flag (non-interactive mode). Claude cannot prompt for input; if it encounters ambiguity, the task fails rather than guessing.
- **Scoped to registered projects** -- The scheduler only processes projects listed in `~/.smith/scheduler/projects.json`. It does not scan your filesystem.

### Audits step security posture

The scheduler's audits step (see [Scheduler](scheduler.md)'s "Audits Step" section) is a second, narrower pass with a distinct security profile from the queue step above:

- **Read-only sub-audits** -- Every sub-audit `/smith-audit` runs in `--scheduled` mode is read-only; per `smith-audit/SKILL.md`'s own "Key Rules," an audit never modifies code, only produces report files. A scheduled dispatch inherits this unchanged.
- **`enabled: false` shipped default** -- No project gets unattended dispatch, report-writing, or marker-bootstrapping behavior until `scheduled_audits.enabled` is explicitly set to `true` in that project's `.smith/config.json`.
- **Git-worktree-free** -- Unlike the queue step's per-task worktree isolation above, `/smith-audit` never creates or checks out a branch for a scheduled run. Its workflow-gate marker (a `maintenance`-type active-workflow marker, bootstrapped via the same helper `/smith-update` already uses) carries a synthetic `--branch` label that names no real git ref -- it exists only to satisfy the marker file's required fields, not to create or track an actual branch.

---

## Activity Daemon Security

`/smith-activity` starts a background daemon that renders a live audit of Smith's own workflows in a browser. It introduces four things Smith had never done before, and each is stated here rather than left to be discovered by reading `server.py`.

It runs only when you start it. Nothing in Smith starts it for you, `scripts/install.sh` does not launch it, and `/smith-activity stop` ends it. Until it has run once, `hooks/activity-emitter.sh` is an unconditional no-op.

### 1. A listening socket, loopback-only and not configurable

The daemon binds `127.0.0.1` as a **hardcoded module constant**. It is not a parameter, not a flag, not a config key, and not an environment variable — there is no supported or unsupported way to make it listen on `0.0.0.0`, a LAN address, or a non-loopback IPv6 address. `--port` chooses the port; nothing chooses the interface. Two tests enforce this: one inspects the live socket, the other greps `scripts/activity/*.py` for `urllib`, `http.client`, `ftplib`, `smtplib` and `socket.create_connection` and asserts zero hits outside the local port probe.

The daemon makes **no outbound requests at all**. The served dashboard has no external origin either — no `<script src="http…">`, no remote stylesheet, no web font, no CDN. Every asset is served from `scripts/activity/static/`, and a test greps the served HTML for `src`/`href` values beginning `http` or `//` and asserts zero.

### 2. A hook that makes a network call -- a first for this repo

`hooks/activity-emitter.sh` posts each hook payload to `http://127.0.0.1:<port>/ingest`. No other Smith hook has ever opened a socket, so the constraints are worth being explicit about:

- **The destination is loopback and literal.** The port comes from `~/.smith/activity/activity.port` and is rejected unless it is entirely digits — a truncated or half-written port file must never become part of a URL.
- **It exits 0 on every path and writes zero bytes to stdout.** An emitter that can fail visibly is an emitter that can break the session it is auditing.
- **It is bounded and detached** — `curl --max-time 2 --connect-timeout 1`, backgrounded — so a hung receiver costs a fork, not a stalled tool call.
- **It bails before the network call** when the port or token file is absent, which is the state of every machine that has not run `/smith-activity`.

### 3. A token gate on everything that reads state

A `secrets.token_urlsafe(32)` token is generated at first daemon start and written to `"${SMITH_HOME:-$HOME/.smith}"/activity/activity.token` with mode **0600**, inside a directory created **0700**.

| Route | Gate |
|-------|------|
| `GET /events`, `GET /api/*` | `token` query parameter, required |
| `POST /ingest`, `POST /statusline` | `Authorization: Bearer`, required |
| `GET /health`, `GET /`, `GET /static/*` | un-gated (identity probe and static assets only — they carry no captured state) |

Comparison uses `hmac.compare_digest`, never `==`. A missing token and a wrong token produce an **identical** `403 {"error":"forbidden"}` so the endpoint cannot be used as an oracle. `/static/<name>` is `os.path.basename()`-ed and resolved through an explicit allowlist dict, never joined against caller-supplied input. `POST /ingest` caps a body at 256 KiB and answers `204` to everything — including malformed and oversize payloads — because a 4xx would be a failure signal the emitter might act on, and the emitter's whole contract is that it acts on nothing.

This token protects against other **local** processes and other users on the machine reading the stream. It is not a defense against an attacker who already has your user account, and it is not claimed to be.

### 4. Prompts and tool inputs are redacted by default

This is the inverse of `user-prompt-logger.sh`'s deliberate verbatim-capture trade-off, and the two should not be confused.

With `SMITH_ACTIVITY_CAPTURE_PROMPTS` **unset** — the shipped default — `scripts/activity/ingest.py` rewrites the payload **before it reaches the state tree**, not at render time:

| Field | Becomes |
|-------|---------|
| `prompt` | `"<redacted:N chars>"` |
| `tool_input` | `{"<redacted>": N}` |
| `tool_response` | `"<redacted:N bytes>"` |
| any value under a key matching `(?i)(secret\|token\|password\|api_?key\|authorization)` | `"<redacted>"` |

Redaction at ingest rather than at projection is the load-bearing choice: a redactor that runs when a frame is built passes every unit test and still leaves the raw value sitting in memory for the next projection, the next API route, or a crash log to pick up. The byte and character lengths are retained deliberately — they are useful and they are not content. Structural fields (`tool_name`, `session_id`, `prompt_id`, `cwd`, `transcript_path`, `permission_mode`, `hook_event_name`, `agent_id`, `agent_type`, `source`, `error_type`) are always retained.

The secret-shaped-key rule is **unconditional**: it applies even with capture enabled. Opting in means opting in to seeing your own prompts, not to having credentials rendered in a browser tab.

Setting `SMITH_ACTIVITY_CAPTURE_PROMPTS=1` opts in, and the dashboard displays a "prompt capture is ACTIVE" indicator for as long as it is on — the setting is never silently in effect. A test drives a unique canary string through a `UserPromptSubmit` payload and a `PreToolUse` `tool_input` with capture off, then greps every `/api/*` response body, a captured `/events` transcript, and `~/.smith/activity/activity.log` for it, expecting zero hits in all three.

### Where state lives, and how long

Everything the daemon owns is under `"${SMITH_HOME:-$HOME/.smith}"/activity/` — `activity.pid`, `activity.port`, `activity.token`, `activity.log` (rolled at 5 MB), `wrapped-statusline`, and the registered-project list. Nothing is written into any project's `.smith/vault/`; that prohibition has its own test, because a detached daemon lives outside the hook system and `workflow-gate.sh` cannot enforce it.

**Retention is ephemeral.** Observed events live in memory and are never written to an event store. Stopping the daemon discards them. This is a deliberate boundary: an audit tool that accumulated every prompt and tool input on disk would be a larger privacy surface than the thing it audits. `scripts/uninstall.sh` stops the daemon, restores or removes the `statusLine` key it wrapped, and deletes `$SMITH_HOME/activity/` outright.

---

## What to Audit Before Enabling

Before enabling the scheduler or relying on the security guards, review these nine files:

1. **`~/.claude/hooks/security-guard-bash.sh`** -- Review the blocklist patterns. Confirm they cover the commands you consider dangerous in your environment. Add any project-specific patterns.

2. **`~/.claude/hooks/security-guard-files.sh`** -- Review the blocked file paths. Add any project-specific sensitive files (database configs, API key files, deployment manifests with secrets).

3. **`~/.smith/scheduler/smith-scheduler.sh`** -- Review the task selection logic and worktree creation. Confirm you are comfortable with the scheduler creating branches and worktrees in your registered projects.

4. **`~/.claude/hooks/security-guard-mcp-browser.sh`** -- Review the interaction-tool policy (`browser_verification.allow_interactions`, staging/production classification in `.smith/security-config.json`) and confirm the production-confirmation requirement matches your risk tolerance -- this is the one denial among the three guard hooks that `warn_only_mode` cannot downgrade or bypass.

5. **`~/.smith/scripts/security/secret-scan.sh`** -- Review the built-in exclude-path set (`vendor/`, `node_modules/`, `.venv/`, `dist/`, `build/`, `.smith/`) and the gitleaks-merge behavior. Confirm the `security_review.excludes`/`allowlist_globs` keys in your project's `.smith/config.json` match what you actually want scanned.

6. **`~/.smith/scripts/security/secret_scan.py`** -- Review the pattern catalogue and the entropy threshold for the generic high-entropy heuristic. Confirm the redaction behavior (masked excerpts only, never a secret's real value) matches your team's expectations for what may appear in a PR body or the vault session log.

7. **`~/.smith/scripts/security/detect-scanners.sh`** -- Review the presence-detection list (`gitleaks`, `semgrep`, `bandit`, `osv-scanner`, `grype`, `trivy`, `pip-audit`, `licensee`, `syft`) and confirm it matches which scanners you actually expect Layer 2 / the Supply-Chain Review Pass to pick up on your machine or CI runner -- remember that a Layer 1 Critical secret finding terminates the build regardless of what this script detects, and that no Supply-Chain Review finding ever can; see [Code-Content Security Review](#code-content-security-review) and [Supply-Chain & License Review](#supply-chain--license-review) above.

8. **`~/.smith/scripts/security/dependency-scan.py`** -- Review the scanner-hierarchy selection (`osv-scanner`/`trivy` preferred whole-repo, else per-manifest `npm audit`/`pip-audit` fallback) and the timeout handling (`supply_chain.timeout_seconds`, default 60s) for every scanner invocation that reaches out to a vulnerability database.

9. **`~/.smith/scripts/security/license-inventory.py`** -- Review the npm (`node_modules`) and Python (`importlib.metadata` via `poetry run python3`) license-resolution fallback chains and the `supply_chain.license_policy.deny` evaluation, to confirm they match which licenses you actually want flagged.

---

## Reporting Vulnerabilities

If you discover a security vulnerability in Smith, do not open a public issue. Instead, email **tech@attck.com** with a description of the vulnerability, steps to reproduce, and any relevant log output. See [SECURITY.md](../SECURITY.md) for the full disclosure policy.
