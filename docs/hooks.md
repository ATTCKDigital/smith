# Hooks Reference

Smith installs 9 hooks into `~/.claude/hooks/`. Each hook is a bash script registered in `~/.claude/settings.json` under the `hooks` key. Claude Code fires hooks automatically at specific lifecycle events.

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
| security-guard-bash | PreToolUse | Bash | Block dangerous commands |
| security-guard-files | PreToolUse | Write, Edit, NotebookEdit | Block writes to sensitive files |
| task-router | PreToolUse | Task | Route tasks during workflows |
| subagent-vault-writeback | SubagentStop | * | Persist sub-agent findings |

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

### task-router.sh

- **Event:** PreToolUse
- **Matcher:** `Task`
- **What it does:** Intercepts task tool calls during active Smith workflows. Checks whether a workflow is currently in progress (by looking for active spec/plan/task files in `.smith/`). If a workflow is active, routes the task according to the current workflow phase (spec, plan, implement). If no workflow is active, the task passes through unmodified.
- **Files touched:** Reads `.smith/` workflow state files
- **To disable:** Remove the `PreToolUse` entry for Task referencing this script from `settings.json`.

---

### subagent-vault-writeback.sh

- **Event:** SubagentStop
- **Matcher:** `*` (fires on every sub-agent completion)
- **What it does:** Fires when a sub-agent finishes its work. Reads the sub-agent's output and writes a summary to `.smith/vault/agents/<agent-id>.md`. This persists the sub-agent's findings, decisions, and any artifacts it produced so they are available to future sessions and workflows.
- **Files touched:** Creates or updates `.smith/vault/agents/<agent-id>.md`
- **To disable:** Remove the `SubagentStop` entry referencing this script from `settings.json`.

---

## Adding Custom Hooks

To add your own hook:

1. Write a bash script and place it in `~/.claude/hooks/`.
2. Add an entry to `~/.claude/settings.json` under the `hooks` key, specifying the event type, matcher pattern, and script path.
3. Test the hook by triggering the relevant event in Claude Code.

Refer to the Claude Code documentation for the full hook API specification.
