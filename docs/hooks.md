# Hooks Reference

Smith installs **every `hooks/*.sh` script this repository ships** into `~/.claude/hooks/` — 20 of them as of this writing — plus the Python helpers (`hooks/*.py`) and data files (`hooks/*.json`) those scripts read. Each hook is a bash script registered in `~/.claude/settings.json` under the `hooks` key. Claude Code fires hooks automatically at specific lifecycle events.

The installer never hardcodes that number: `scripts/install.sh` derives `HOOK_TOTAL`, `HELPER_TOTAL` and `HOOKDATA_TOTAL` from the `hooks/` directory itself, and its copy loops glob rather than enumerate. The figure above is prose and can drift, so re-derive it with `ls hooks/*.sh | wc -l` before quoting it anywhere. (The previous "10" in this sentence had drifted to half the real number.)

The table below documents the operator-facing subset. Seven installed hooks — `active-workflow-janitor.sh`, `context-loader.sh`, `manifest-updater.sh`, `metrics-tracker.sh`, `stamp-response.sh`, `workflow-gate.sh`, `workflow-summary.sh` — are internal to Smith's own workflows and are documented in their respective feature specs rather than here.

To disable any hook, remove its entry from `~/.claude/settings.json`. The script file can remain in `~/.claude/hooks/` without effect.

---

## Hook Summary

| Hook | Event | Matcher | Purpose |
|------|-------|---------|---------|
| session-start-logger | SessionStart | * | Create session log |
| session-end-review | Stop | * | Review changes, prompt for spec updates |
| grade-response | Stop | * | Grade response against CLAUDE.md rubric; block stop and retry if score < 100 |
| file-change-logger | PostToolUse | Write, Edit, NotebookEdit | Log file changes to session |
| lint-on-save | PostToolUse | Write, Edit | Run linter on saved files |
| context-budget-guard | PostToolUse | Write, Edit | Warn when an edited file exceeds the size soft cap (default 50 KB); flag `@`-referenced files loudly |
| security-guard-bash | PreToolUse | Bash | Block dangerous commands |
| security-guard-files | PreToolUse | Write, Edit, NotebookEdit | Block writes to sensitive files |
| security-guard-mcp-browser | PreToolUse | mcp__playwright__ | Gate Playwright MCP browser interaction tools; block production actions without confirmation |
| task-router | PreToolUse | Task | Route tasks during workflows |
| question-gate-guard | PreToolUse | AskUserQuestion | Suppress the interactive question popup in favor of Smith's markdown Q&A contract (config `question_gate.mode`) |
| subagent-vault-writeback | SubagentStop | * | Persist sub-agent findings |
| user-prompt-logger | UserPromptSubmit | * | Append each user prompt verbatim to the session log |
| activity-emitter | SessionStart, SessionEnd, UserPromptSubmit, PreToolUse, PostToolUse, PostToolUseFailure, SubagentStart, SubagentStop, Stop, Notification, PermissionRequest, PermissionDenied, PreCompact, PostCompact, ConfigChange | * | Forward hook events to the local `/smith-activity` daemon; silent no-op when the daemon is down |

---

## Detailed Reference

### session-start-logger.sh

- **Event:** SessionStart
- **Matcher:** `*` (fires on every session start)
- **What it does:** Creates a new session log file in `.smith/vault/sessions/` with a timestamped filename. Records the session start time, working directory, and git branch (if applicable). This log file is then used by other hooks to append events throughout the session.
- **Files touched:** Creates `.smith/vault/sessions/<timestamp>.jsonl`
- **To disable:** Remove the `SessionStart` entry referencing this script from `settings.json`.

---

### session-end-review.sh

- **Event:** Stop
- **Matcher:** `*` (fires on every session end)
- **What it does:** Runs when a Claude Code session ends. Reviews the changes made during the session by reading the session log and git diff. If spec files exist in the project, it checks whether the changes are consistent with the spec and prompts the user to update specs if they have drifted.
- **Files touched:** Reads `.smith/vault/sessions/<current>.jsonl`, reads spec files under `.smith/` or `specs/`
- **To disable:** Remove the `Stop` entry referencing this script from `settings.json`.

---

### grade-response.sh

- **Event:** Stop
- **Matcher:** `*` (fires on every session end)
- **What it does:** Grades the just-completed turn against the weighted rubric in `~/.claude/CLAUDE.md` via a Haiku critic (`claude --model haiku -p`). If the total score is less than 100, the hook exits 2 to block the stop and force a retry. Capped at 3 retries per turn — after that, warns on stderr and passes. Fails open on any error (missing transcript, bad JSON, unreachable critic).
- **Files touched:** Reads `$HOME/.claude/CLAUDE.md` and the current session transcript. Writes a retry counter to `/tmp/claude-grade-retry-<session-id>`, cleaned up on pass or max-retries-exhausted.
- **Tuning:** Edit `~/.claude/CLAUDE.md` to change rule weights, add sub-criteria, or introduce new rules. The total must sum to 100; rules are all-or-nothing. See the "Rule Enforcement System" section of the rubric for the grading contract. The `MAX_RETRIES` constant (default: 3) inside `grade-response.sh` caps retries per turn.
- **Anti-recursion:** The hook skips grading when invoked with `stop_hook_active: true` so a blocked stop does not re-trigger itself.
- **To disable:** Remove the `Stop` entry referencing this script from `settings.json`. It is registered as a separate Stop entry from `session-end-review` / `workflow-summary` so it can be toggled independently.

---

### file-change-logger.sh

- **Event:** PostToolUse
- **Matcher:** `Write`, `Edit`, `NotebookEdit`
- **What it does:** Fires after any file write or edit operation. Appends a JSON line to the current session log recording the file path, operation type (write/edit), and timestamp. This creates an audit trail of all file modifications made during the session.
- **Files touched:** Appends to `.smith/vault/sessions/<current>.jsonl`
- **To disable:** Remove the `PostToolUse` entry referencing this script from `settings.json`. Note: removing this hook means session logs will not contain file change records.

---

### lint-on-save.sh

- **Event:** PostToolUse
- **Matcher:** `Write`, `Edit`
- **What it does:** Fires after file writes and edits. Detects the file type and runs the appropriate linter if one is available (e.g., eslint for JavaScript/TypeScript, ruff for Python, shellcheck for bash). Reports lint errors back to Claude Code so they can be addressed immediately. If no linter is found for the file type, the hook exits silently.
- **Files touched:** Reads the saved file; does not modify any files
- **To disable:** Remove the `PostToolUse` entry referencing this script from `settings.json`.

---

### context-budget-guard.sh

- **Event:** PostToolUse
- **Matcher:** `Write`, `Edit`
- **What it does:** Fires after file writes and edits. Stats the saved file and, if it exceeds the size soft cap, prints an advisory to stderr. Files that are `@`-referenced from the project `CLAUDE.md` are flagged extra-loudly because they are loaded **in full into every session's context** — re-growth there is the expensive case (e.g. a `data-model.md` accumulating per-change changelog prose). The guard never blocks; it always exits 0.
- **Configuration:** Reads `context_budget.max_file_kb` from `.smith/config.json` (default `50`). Set it to `0` to disable the guard entirely. Seeded by `templates/config.default.json`.
- **Files touched:** Reads the saved file and `CLAUDE.md`; does not modify any files
- **To disable:** Set `context_budget.max_file_kb` to `0` in `.smith/config.json`, or remove the `PostToolUse` entry referencing this script from `settings.json`.

---

### security-guard-bash.sh

- **Event:** PreToolUse
- **Matcher:** `Bash`
- **What it does:** Intercepts every Bash command before execution. Checks the command against a blocklist of dangerous patterns including recursive deletion of critical paths, environment variable dumps, secret exfiltration attempts, and hook bypass commands. If a match is found, the hook returns a block response that prevents the command from executing and logs the blocked attempt.
- **Files touched:** None (inspection only)
- **To disable:** Remove the `PreToolUse` entry for Bash referencing this script from `settings.json`. Warning: disabling this hook removes a safety layer against destructive commands.

---

### security-guard-files.sh

- **Event:** PreToolUse
- **Matcher:** `Write`, `Edit`, `NotebookEdit`
- **What it does:** Intercepts every file write or edit before execution. Checks the target file path against a blocklist of sensitive file patterns (environment files, credentials, keys, SSH config, Claude Code config). Writes to `.smith/vault/` are always allowed. If a blocked path is detected, the hook returns a block response and logs the attempt.
- **Files touched:** None (inspection only)
- **To disable:** Remove the `PreToolUse` entry for Write/Edit/NotebookEdit referencing this script from `settings.json`. Warning: disabling this hook removes protection against accidental writes to sensitive files.

---

### security-guard-mcp-browser.sh

- **Event:** PreToolUse
- **Matcher:** `mcp__playwright__`
- **What it does:** Intercepts every Playwright MCP browser tool call before execution. Read-only tools (navigate, snapshot, screenshot, console/network inspection, wait_for, tabs) always run, on any target including production. Interaction tools (click, type, fill_form, select_option, press_key, drag, hover, and `browser_evaluate` — always treated as interaction-class, no read-only heuristic) are denied when `browser_verification.allow_interactions` is `false`, and denied against a production-labeled or unclassified target unless a matching human confirmation was already recorded for that exact target. The production-confirmation denial cannot be downgraded by `warn_only_mode`; every other denial in this guard can.
- **Configuration:** Reads `browser_verification.urls` and `browser_verification.allow_interactions` from `.smith/security-config.json`, and the existing `warn_only_mode` key. Does not read `.smith/config.json`'s `browser_verification.mcp_mode` (that key is agent-read only, not consulted by this guard).
- **Files touched:** Writes `.smith/vault/.mcp-browser-target` on every allowed `browser_navigate` call, and reads (never writes) `.smith/vault/.mcp-browser-confirmed` when deciding whether a production interaction is confirmed.
- **To disable:** Remove the `PreToolUse` entry for `mcp__playwright__` referencing this script from `settings.json`. Warning: disabling this hook removes the confirmation requirement for interaction tools against production targets.

---

### task-router.sh

- **Event:** PreToolUse
- **Matcher:** `Task`
- **What it does:** Intercepts task tool calls during active Smith workflows. Checks whether a workflow is currently in progress (by looking for active spec/plan/task files in `.smith/`). If a workflow is active, routes the task according to the current workflow phase (spec, plan, implement). If no workflow is active, the task passes through unmodified.
- **Files touched:** Reads `.smith/` workflow state files
- **To disable:** Remove the `PreToolUse` entry for Task referencing this script from `settings.json`.

---

### question-gate-guard.sh

- **Event:** PreToolUse
- **Matcher:** `AskUserQuestion`
- **What it does:** Intercepts the harness-native interactive question popup (`AskUserQuestion`) and, by default, suppresses it so questions are presented as markdown per Smith's Q&A contract (Context → Options with pros/cons → Recommended + reasoning, one at a time — see the `smith-question` skill). Any other tool passes through untouched. Behavior is driven by `question_gate.mode` in `.smith/config.json`:
  - **`deny`** (shipped default) — block the popup; the deny reason redirects the model to present the question as markdown.
  - **`warn`** — allow the popup but attach a reminder of the Q&A contract.
  - **`workflow-gated`** — deny only when a Smith workflow marker is active under `.smith/vault/active-workflows/`; otherwise allow (freeform, non-workflow sessions keep the popup).
  - **`off`** — inert; allow the popup.
- **Scope caveat:** the hook is registered in `~/.claude/settings.json`, so `deny` mode applies to **every** project on the machine, not only Smith ones. Use `workflow-gated` or a per-project `off` to narrow it.
- **Fail-open:** a missing/unreadable/unparseable `.smith/config.json`, an **absent** `question_gate` key, or an unrecognized mode all resolve to `off` (allow). This means installing the hook never silently changes an existing project's behavior — a project only gets `deny` once it is (re-)seeded. A fresh `/smith` init ships `deny` (from `templates/config.default.json`); an existing project activates `deny` when you run `/smith-update` there.
- **Files touched:** Reads `.smith/config.json` and globs `.smith/vault/active-workflows/`.
- **To disable:** set `question_gate.mode` to `off`, or remove the `PreToolUse` entry for `AskUserQuestion` from `settings.json`.

---

### subagent-vault-writeback.sh

- **Event:** SubagentStop
- **Matcher:** `*` (fires on every sub-agent completion)
- **What it does:** Fires when a sub-agent finishes its work. Reads the sub-agent's output and writes a summary to `.smith/vault/agents/<agent-id>.md`. This persists the sub-agent's findings, decisions, and any artifacts it produced so they are available to future sessions and workflows.
- **Files touched:** Creates or updates `.smith/vault/agents/<agent-id>.md`
- **To disable:** Remove the `SubagentStop` entry referencing this script from `settings.json`.

---

### user-prompt-logger.sh

- **Event:** UserPromptSubmit
- **Matcher:** `*` (fires on every user prompt)
- **What it does:** Appends each user prompt — **verbatim and full text**, with an `HH:MM:SS` timestamp — to the current session log as a `### [HH:MM:SS] User prompt` blockquote block, interleaved chronologically with the tool-call lines written by `metrics-tracker.sh`. This gives team leads a shared, readable record of what teammates asked the agent to do. The prompts previously lived only in Claude Code's per-user global JSONL transcripts (`~/.claude/projects/<slug>/*.jsonl`), which are never team-shared; this hook surfaces them in the `/smith-sync`-shared session log. Resolves the target via `.smith/vault/.current-session` and no-ops silently if the vault is not initialized. Runs after `context-loader.sh` so context injection is never delayed. Only fires for genuine human prompts — Claude Code does not fire `UserPromptSubmit` for sub-agents.
- **Privacy note (intentional):** Prompts are stored verbatim, including anything a user pastes (which may contain secrets), because the session log is team-shared. This is an accepted trade-off for internal team repos. Do not add redaction/truncation without a spec change.
- **Files touched:** Appends to the current `.smith/vault/sessions/<session>.md`
- **To disable:** Remove the `UserPromptSubmit` entry referencing this script from `settings.json` (leave `context-loader.sh` in place).

---

### activity-emitter.sh

- **Event:** SessionStart, SessionEnd, UserPromptSubmit, PreToolUse, PostToolUse, PostToolUseFailure, SubagentStart, SubagentStop, Stop, Notification, PermissionRequest, PermissionDenied, PreCompact, PostCompact, ConfigChange
- **Matcher:** `*` — and, importantly, **its own `{matcher, hooks}` entry per event**. It is never appended to an existing chain, so `manifest-updater.sh` stays last in the `PostToolUse` `Write|Edit` chain (`scripts/install-hooks.sh:6-7`). Each entry declares `timeout: 5`; Claude Code's default for a `command` hook is 600 s, which an emitter must never inherit.
- **What it does:** Forwards the hook payload on stdin **byte-for-byte** to the local `/smith-activity` daemon at `POST http://127.0.0.1:<port>/ingest`. It parses nothing — no jq, no grep, no sed. Parsing is the only thing in an emitter that can fail in an interesting way, and on `PreToolUse` an interesting failure blocks the operator's tool call. The daemon is the sole parser and the sole redaction point, which keeps the redaction rules in exactly one file.
- **Exit contract:** Absolute, and the reason this hook is safe to wire on fifteen events. It exits `0` on **every** path, including every error path (`set -uo pipefail` deliberately omits `-e`) — exit 2 is Claude Code's block signal and any other non-zero puts a visible "hook error" notice in the transcript. It writes **zero bytes** to stdout, which is not cosmetic: on `UserPromptSubmit` and `SessionStart`, stdout is injected into Claude's context. With `~/.smith/activity/activity.port` or `activity.token` absent — the state of every machine until `/smith-activity` is first run — it exits 0 before attempting any network call. The bound is `curl --max-time 2 --connect-timeout 1`, not `timeout`/`gtimeout` (neither exists on a stock macOS), and the call is detached, so the foreground cost is a fork rather than the ceiling. No `/dev/tcp` anywhere — it is a bash-only virtual path and this repo runs its shell surfaces under zsh too.
- **Files touched:** Reads `"${SMITH_HOME:-$HOME/.smith}"/activity/activity.port` and `.../activity.token`. Writes nothing, anywhere — in particular it never writes to any project's `.smith/vault/`.
- **Network:** One loopback `POST` to `127.0.0.1` and nothing else. No outbound network of any kind. See [Security Model](security-model.md#activity-daemon-security) for the full surface.
- **Privacy note (default-safe, opposite of `user-prompt-logger.sh`):** The payload leaves this script unredacted because the receiver redacts it. With `SMITH_ACTIVITY_CAPTURE_PROMPTS` unset — the shipped default — the daemon replaces `prompt`, `tool_input` and `tool_response` with byte-length placeholders **before the payload reaches its state tree**, so nothing renderable, logged or served over `/api/*` retains prompt text. Set `SMITH_ACTIVITY_CAPTURE_PROMPTS=1` to opt in; the dashboard then shows a "prompt capture is ACTIVE" indicator for as long as it is on.
- **To disable:** Remove the entries referencing this script from `~/.claude/settings.json`, or simply stop the daemon (`/smith-activity stop`) — with no port file the emitter bails before any network call, measured at a ~4.4 ms median (barely above the ~4.0 ms floor for a bash script that reads stdin and exits).

---

## Adding Custom Hooks

To add your own hook:

1. Write a bash script and place it in `~/.claude/hooks/`.
2. Add an entry to `~/.claude/settings.json` under the `hooks` key, specifying the event type, matcher pattern, and script path.
3. Test the hook by triggering the relevant event in Claude Code.

Refer to the Claude Code documentation for the full hook API specification.
