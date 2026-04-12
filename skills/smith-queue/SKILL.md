---
name: smith-queue
description: Manage a deferred task queue — add, list, process, remove, batch-execute, schedule, prioritize, and browse history of tasks stored in the vault.
argument-hint: add|list|process|remove|batch|status|prioritize|schedule|unschedule|edit|promote|demote|requeue|history|scheduler "<args>"
---

# Smith Task Queue

Manage deferred work through a persistent task queue in `.smith/vault/queue/`. Supports priority ordering, dependency tracking, scheduled execution, status lifecycle management, and batch processing with git worktree isolation.

**Arguments:** $ARGUMENTS

## Vault Logging

Throughout this action, log significant events to the vault session log. Read the session log path from `.smith/vault/.current-session`. If the file is missing or the vault is not initialized, skip all logging silently.

Append entries using this format:

```
### [HH:MM:SS] /smith-queue <event>

**Input:** <brief summary>
**Outcome:** <what happened>
**Artifacts:** <files created/modified>
```

Log at these points:
1. **On invocation** — which subcommand was used
2. **After task added/removed/processed/scheduled** — task description, queue file path, status change

## Queue Entry Format

All queue entries are markdown files in `.smith/vault/queue/` with this frontmatter:

```yaml
---
task: "<task description>"
branch: "<feature branch name — the queue processor checks out this branch via worktree>"
spec_path: "<path to the feature spec folder on the feature branch>"
primary_system: "<system ID, e.g., system-13-trend-intelligence>"
created: "YYYY-MM-DDTHH:MM:SS"
project: "<project directory basename>"
complexity: autonomous|interactive|review
priority: critical|high|medium|low
status: pending|scheduled|in-progress|completed|failed|blocked
depends_on: []
scheduled_for: ""
---

## Context

<brief description of what this feature does and key decisions>

## Artifacts on branch

- spec.md — feature specification
- plan.md — implementation plan
- questions.md — clarification questions (all answered)
- <any other artifacts>

## Execution Instructions

Run `/smith-build` from the `<branch>` branch with feature dir `<spec_path>`.
```

**Required fields:** `task`, `branch`, `spec_path`, `status`, `complexity`, `priority`.

**Backwards compatibility:**
- Entries without `priority`, `depends_on`, or `scheduled_for` → treated as `priority: medium`, `depends_on: []`, `scheduled_for: ""`
- Entries with `description` instead of `task` → read `description` as the task name
- Entries with `status: queued` → treated as `status: pending`

## Status Lifecycle

```
pending → scheduled → in-progress → completed
                                   → failed → pending (via requeue)
                    → blocked (if dependency failed)
```

Every status change MUST append to the `## Status History` section in the queue file body:

```markdown
- `[YYYY-MM-DD HH:MM]` <Status> — <reason or details>
```

## Subcommands

Parse the first word of `$ARGUMENTS` to determine the subcommand.

---

### `add "<description>"` [--priority <level>] [--depends-on <filename>]

Creates a new task entry in `.smith/vault/queue/`.

1. **Capture context:**
   - Task description (from arguments after `add`, excluding flags)
   - Current project directory (`$CLAUDE_PROJECT_DIR`)
   - Current git branch: `git rev-parse --abbrev-ref HEAD`
   - Active feature spec (if on a feature branch, check `.specify/systems/`)
   - Timestamp (UTC)

2. **Parse flags:**
   - `--priority <level>` — set priority (critical/high/medium/low). Default: `medium`
   - `--depends-on <filename>` — add dependency on another queue entry. Can be specified multiple times.

3. **Determine complexity flag** from the description:
   - `autonomous` — task can run without user input (default for clear, specific instructions)
   - `interactive` — task needs user decisions or clarification
   - `review` — run autonomously but stage results for approval
   - If unclear, ask the user

4. **Generate queue file** at `.smith/vault/queue/YYYY-MM-DD_HHMMSS-<slug>.md`:

   ```markdown
   ---
   task: "<task description>"
   created: "YYYY-MM-DDTHH:MM:SS"
   project: "<project name>"
   branch: "<current branch>"
   spec_path: "<spec path or empty>"
   complexity: <flag>
   priority: <level>
   status: pending
   depends_on: [<filenames>]
   scheduled_for: ""
   ---

   # Task: <description>

   ## Context

   - **Project:** <project name>
   - **Branch at creation:** <branch>
   - **Active spec:** <spec path or "none">
   - **Priority:** <level>
   - **Dependencies:** <list or "none">

   ## Instructions

   <full task description>

   ## Notes

   <additional context from the conversation>

   ## Status History

   - `[YYYY-MM-DD HH:MM]` Created — priority: <level>, complexity: <flag>
   ```

5. **Confirm:** "Queued: `<filename>` (priority: `<level>`, complexity: `<flag>`)"

---

### `list`

Show all pending/scheduled queue items sorted by priority then date.

1. Read all `.md` files in `.smith/vault/queue/` (excluding `history/` subdirectory and `.batch-progress.md`)
2. Parse frontmatter for `task`, `created`, `complexity`, `priority`, `status`, `depends_on`
3. Sort: critical → high → medium → low, then oldest first within each level
4. Display:

   ```
   ## Queue — N items

   | # | Priority | Created | Complexity | Status | Description | File |
   |---|----------|---------|------------|--------|-------------|------|
   | 1 | 🔴 critical | 04-05 08:30 | autonomous | pending | Fix auth bypass | ... |
   | 2 | 🟠 high | 04-05 09:00 | review | scheduled 04-06 02:00 | Add rate limiting | ... |
   | 3 | 🟡 medium | 04-05 09:15 | interactive | pending | Redesign popup | ... |
   | 4 | 🔵 low | 04-05 10:00 | autonomous | pending | Update docs | ... |

   Total: 4 items (2 autonomous, 1 interactive, 1 review)
   Dependencies: #4 depends on #1

   Process a specific task with `/smith-queue process <filename>`, or run all with `/smith-queue process --all`.
   ```

5. If empty: "Queue is empty. Use `/smith-queue add \"<description>\"` to add a task."

---

### `status`

Display all queue items grouped by status.

1. Read all files in `.smith/vault/queue/` (including `history/`)
2. Group by status and display:

   ```
   ## Queue Status

   ### In Progress
   - <task> (started <time>)

   ### Blocked
   - <task> — blocked by: <dependency filename> (status: failed)

   ### Scheduled
   - <task> — scheduled for <datetime>

   ### Pending (by priority)
   - 🔴 <task>
   - 🟡 <task>

   ### Recently Completed (last 5)
   - <task> — completed <date>

   ### Recently Failed (last 5)
   - <task> — failed <date>: <error summary>
   ```

---

### `process` [<filename>] [--all] [--next] [--dry-run] [--limit N] [--priority <level>] [--project <name>] [--all-projects] [--model <model>] [--abort]

The primary command for running queued tasks. Supports interactive selection, specific file processing, and batch execution.

#### `process` (no arguments) — Interactive Picker

1. Scan `.smith/vault/queue/` for all processable tasks: `complexity: autonomous`, `status: pending` or `status: queued`
2. Sort by priority (critical → high → medium → low), then oldest first
3. Skip items with unmet dependencies
4. Display the list numbered:
   ```
   ## Pending Autonomous Tasks

   | # | Priority | Task | Branch | File |
   |---|----------|------|--------|------|
   | 1 | 🟡 medium | Trends Article Explorer Tab | 057-trends-article-explorer | 057-trends-article-explorer.md |

   Which task would you like to process? Enter a number, or "all" to process everything.
   ```
5. Wait for user to select a number. Then process that single task (see execution steps below).
6. If user says "all", behave as `process --all`.

#### `process <filename>` — Specific Task

Process a specific queue entry by filename. Accepts full filename or partial match.

#### `process --next` — Next Highest Priority

Process only the single highest-priority autonomous pending task, then stop. No prompt — just picks the top item and runs it.

#### `process --all` — All Pending Tasks

Process all autonomous + pending tasks sequentially in priority order. This is the batch execution mode.

Accepts all batch flags:
- `--dry-run` — show what would be processed without executing
- `--limit <N>` — process only the first N items after ordering
- `--priority <level>` — process only items at or above the given priority (`--priority high` = critical + high only)
- `--project <name>` — process queue for a specific project (from `~/.smith/projects.json`)
- `--all-projects` — process across all registered projects, most recently active first
- `--model <model>` — override model for processing. Default: `sonnet`. Options: `haiku`, `sonnet`, `opus`
- `--abort` — if processing is running, create `.smith/vault/queue/.abort-batch` flag. Current task finishes; remaining return to `pending`.

#### Full Pipeline Steps (per task)

These steps apply whether processing a single task or batch. **The queue entry is only marked `completed` after the PR is merged.** If any step fails, the entry is marked `failed` with error details and the branch is left intact for manual review.

1. Read the queue file, parse frontmatter
2. **Validate:** Cannot process if status is `completed`, `in-progress`, or `blocked`. Treat `status: queued` as `status: pending`.
3. **Check dependencies:** If `depends_on` has entries, verify all are `completed`. If any are not, show which are blocking and abort.
4. Update frontmatter: `status: in-progress`
5. Append status history: `- [YYYY-MM-DD HH:MM] In Progress — processing started`
6. **Create a git worktree** from the queue entry's `branch` field:
   ```bash
   git worktree add /tmp/smith-queue-<slug> <branch>
   ```
   Do NOT checkout the branch in the main working directory — the worktree is an isolated copy.
7. **Run `/smith-build`** within the worktree directory, using `spec_path` from the queue entry frontmatter to locate spec artifacts. This handles task generation, implementation, and initial testing.
8. **Rebuild affected Docker services.** Identify which services were modified:
   ```bash
   git diff main --name-only | grep '^services/' | cut -d'/' -f2 | sort -u
   ```
   For each affected service: `docker compose up -d --build <service-name>`. Wait for healthy status. **If Docker build fails:** mark `failed`, STOP.
9. **Run final tests** to verify the build is healthy:
   - Frontend changed → `cd services/command-center && pnpm test`
   - Python service changed → `cd services/<service> && poetry run pytest`
   - Playwright tests for changed components if applicable
   **If tests fail:** mark `failed`, STOP.
10. **Push the branch** if not already pushed: `git push -u origin <branch>`
11. **Create PR** via `gh pr create`. **If fails:** mark `failed`, STOP.
12. **Merge PR** via `gh pr merge <number> --squash --delete-branch`. **If fails (conflicts, checks):** mark `failed`, leave PR open, STOP.
13. **Return to main:** `git checkout main && git pull origin main`
14. **Update system specs, CHANGELOG.md, STATUS.md:**
    - Read `primary_system` and `also_affects` from queue entry
    - Update `.specify/systems/<system>/spec.md` with dated implementation history
    - Update CHANGELOG.md and STATUS.md
    - Commit and push spec updates to main
15. **Mark completed and archive:**
    - Update frontmatter: `status: completed`
    - Append: `- [YYYY-MM-DD HH:MM] Completed — PR #<number> merged, specs updated`
    - Add `## Result` section with PR link, files changed, services rebuilt, test results
    - **Move file** to `.smith/vault/queue/history/`
    - Log results to vault session log
16. **Clean up worktree:** `git worktree remove /tmp/smith-queue-<slug>`

#### Failure Handling

If ANY step 8-12 fails:
- Update frontmatter: `status: failed`
- Append: `- [YYYY-MM-DD HH:MM] Failed — <step name>: <error summary>`
- **Move file** to `.smith/vault/queue/history/`
- Check dependents → mark as `blocked`
- Do NOT remove worktree — leave for debugging
- Do NOT continue to subsequent steps
- Log failure to vault session log

#### Batch Progress (for --all mode)

During batch processing, write a live progress file at `.smith/vault/queue/.batch-progress.md`:

```markdown
# Processing Progress — YYYY-MM-DD HH:MM

| # | Task | Priority | Status | Duration |
|---|------|----------|--------|----------|
| 1 | Fix auth | critical | completed | 4m 32s |
| 2 | Add filters | medium | in-progress | 2m 15s... |
| 3 | Update docs | low | pending | — |

**Started:** HH:MM:SS
**Completed:** 1 of 3
**Failed:** 0
```

After processing completes, move progress file to `.smith/vault/queue/history/batch-YYYY-MM-DD_HHMMSS.md`.

---

### `remove <filename>`

Remove a task from the queue.

1. Check file exists in `.smith/vault/queue/`
2. **Validate:** Cannot remove `in-progress` items. Warn if removing a task that others depend on.
3. Show task description and ask: "Remove task: `<description>`? [y/n]"
4. If confirmed, delete the file

---

### `prioritize`

Interactive reordering of pending items.

1. List all pending items in current priority order (numbered)
2. Ask: "Which item number would you like to reprioritize?"
3. After selection, ask: "New priority for `<task>`? (critical/high/medium/low)"
4. Update the item's `priority` field in frontmatter
5. Append status history: `- [YYYY-MM-DD HH:MM] Edited — priority changed from <old> to <new>`
6. Show the reordered list

---

### `schedule <filename> --at "<datetime>"`

Schedule a task for future processing.

1. Read the queue file
2. **Validate:** Must be `pending` or `scheduled` status
3. Parse `--at` value:
   - ISO datetime: `2026-04-07T02:00:00`
   - `tonight` → next occurrence of 02:00 local time
   - `off-peak` → same as `tonight`
   - `tomorrow` → next day at 02:00 local time
4. Update frontmatter: `status: scheduled`, `scheduled_for: "<ISO datetime>"`
5. Append: `- [YYYY-MM-DD HH:MM] Scheduled — processing at <datetime>`

### `schedule-batch --at "<datetime>"`

Schedule all `autonomous` + `pending` tasks for batch processing.

1. Find all queue items with `complexity: autonomous` and `status: pending`
2. Parse `--at` value (same rules as above)
3. Update each item: `status: scheduled`, `scheduled_for: "<datetime>"`
4. Append status history to each
5. Show count: "Scheduled N tasks for <datetime>"

### `unschedule <filename>`

Remove schedule from a task.

1. Read the queue file
2. **Validate:** Must be `scheduled` status
3. Update frontmatter: `status: pending`, `scheduled_for: ""`
4. Append: `- [YYYY-MM-DD HH:MM] Unscheduled — returned to pending`

---

### `edit <filename>`

Modify task properties.

1. Read the queue file
2. **Validate:** Cannot edit `in-progress` or `completed` items
3. Present current properties: task description, priority, complexity, dependencies
4. Ask what to change (allow multiple changes at once)
5. Update frontmatter fields
6. Append: `- [YYYY-MM-DD HH:MM] Edited — <list of changes>`
7. If editing a `scheduled` item, preserve the schedule unless explicitly changed

### `promote <filename>`

Shorthand to change complexity from `autonomous` → `interactive`.

1. Read file, validate not `in-progress`/`completed`
2. Update `complexity: interactive`
3. Append: `- [YYYY-MM-DD HH:MM] Promoted — complexity changed from autonomous to interactive`

### `demote <filename>`

Shorthand to change complexity from `interactive` → `autonomous`.

1. Read file, validate not `in-progress`/`completed`
2. Update `complexity: autonomous`
3. Append: `- [YYYY-MM-DD HH:MM] Demoted — complexity changed from interactive to autonomous`

### `requeue <filename>`

Reset a `failed` task back to `pending`.

1. Read file from `.smith/vault/queue/history/` (failed items are archived)
2. **Validate:** Must be `failed` status
3. Update: `status: pending`
4. Append: `- [YYYY-MM-DD HH:MM] Requeued — reset to pending for retry`
5. **Move file** back from `history/` to `.smith/vault/queue/`

---

### `history` [<filename>] [--status completed|failed] [--since "<date>"]

Browse completed and failed task archives.

**No arguments** — list all items in `.smith/vault/queue/history/` sorted by completion date (most recent first):

```
## Queue History

| # | Task | Status | Priority | Completed | File |
|---|------|--------|----------|-----------|------|
| 1 | Add email filters | ✅ completed | medium | 04-05 14:30 | ... |
| 2 | Fix auth bypass | ❌ failed | critical | 04-05 12:00 | ... |

Total: 2 archived (1 completed, 1 failed)
```

**With filename** — show full contents of a specific history entry including all status history.

**With `--status`** — filter to `completed` or `failed` only.

**With `--since`** — filter to items completed/failed after a date. Supports:
- ISO date: `2026-04-01`
- Natural language: `last week`, `this month`, `yesterday`

### `history clear --before "<date>"`

Remove history entries older than a date. **Requires user confirmation:**

1. Count matching entries
2. Ask: "Delete N history entries from before <date>? This cannot be undone. [y/n]"
3. If confirmed, delete the files

---

### `batch` [flags]

**Alias for `/smith-queue process --all`.** All flags accepted (`--dry-run`, `--limit`, `--priority`, `--project`, `--all-projects`, `--model`, `--abort`). See `process --all` above for full documentation.

#### Batch execution per task

Each task runs through the **Full Pipeline Steps** defined above (steps 1-16: implementation → Docker rebuild → tests → PR → merge → spec updates → archive).

Between tasks, check for the `.abort-batch` flag — if present, stop and return remaining tasks to `pending`.

Update the batch progress file after each task completes or fails.
10. Update progress file

---

### `scheduler install|uninstall|status|logs|set-time`

Manage the macOS launchd scheduler for automatic daily queue processing.

**The scheduler is optional.** Users who prefer manual processing can use `/smith-queue batch` directly.

- `scheduler install` — copies `~/.smith/scheduler/com.smith.scheduler.plist` to `~/Library/LaunchAgents/` and loads it with `launchctl load`. Creates `~/.smith/scheduler/` and the plist if they don't exist. The scheduler runs daily at **2:00 AM local time**, processing all autonomous pending tasks across all registered projects.

- `scheduler uninstall` — runs `launchctl unload` and removes the plist from `~/Library/LaunchAgents/`.

- `scheduler status` — checks if the scheduler is loaded (`launchctl list | grep com.smith.scheduler`), shows the configured run time, and displays last 10 lines of `~/.smith/scheduler/scheduler.log`.

- `scheduler logs` — tails `~/.smith/scheduler/scheduler.log` (last 50 lines).

- `scheduler set-time <HH:MM>` — updates the daily run time. Parses the hour and minute from the argument, updates `~/.smith/scheduler/com.smith.scheduler.plist` (replaces the `StartCalendarInterval` Hour and Minute values), then reloads the agent if installed:
  1. Parse `<HH:MM>` (e.g., `03:30`, `23:00`, `00:15`)
  2. Update the plist file using `sed` or `python3` to replace the Hour integer and Minute integer
  3. If the plist is loaded in launchd (`launchctl list | grep com.smith.scheduler`), run `launchctl unload` then `launchctl load` to pick up the new time
  4. Confirm: "Scheduler updated to run daily at HH:MM. Next run: <calculated next occurrence>."

The scheduler script (`~/.smith/scheduler/smith-scheduler.sh`):
1. Reads `~/.smith/projects.json` to find all project vaults
2. Scans each project's `.smith/vault/queue/` for all `autonomous` tasks with `status: pending` or `status: scheduled` (skips items scheduled for a future date beyond today)
3. Sorts tasks by priority (critical → high → medium → low), then by creation date
4. Checks dependency chains — skips tasks whose dependencies aren't completed
5. For each processable task: updates status → `in-progress`, creates git worktree, runs `claude --model sonnet -p "<task context>"`, updates status on completion, moves to history
6. Logs all activity to `~/.smith/scheduler/scheduler.log`

---

## No Arguments

If invoked with no arguments, show usage:

```
Usage:
  /smith-queue add "<desc>" [--priority P] [--depends-on F]  — Add a task
  /smith-queue list                                           — Show pending tasks
  /smith-queue status                                         — Show all tasks by status
  /smith-queue process                                        — Interactive picker: choose a task to process
  /smith-queue process <file>                                 — Process a specific task
  /smith-queue process --next                                 — Process the next highest-priority task
  /smith-queue process --all [--dry-run] [--limit N] [...]    — Process all autonomous tasks sequentially
  /smith-queue remove <file>                                  — Remove a task
  /smith-queue prioritize                                     — Reorder task priorities
  /smith-queue edit <file>                                    — Modify task properties
  /smith-queue promote <file>                                 — Change autonomous → interactive
  /smith-queue demote <file>                                  — Change interactive → autonomous
  /smith-queue requeue <file>                                 — Reset failed → pending
  /smith-queue schedule <file> --at "<time>"                  — Schedule for future
  /smith-queue schedule-batch --at "<time>"                   — Schedule all autonomous tasks
  /smith-queue unschedule <file>                              — Remove schedule
  /smith-queue batch [flags]                                  — Alias for process --all
  /smith-queue history [--status S] [--since D]               — Browse archived tasks
  /smith-queue scheduler install|uninstall|status|logs        — Manage daily 2am scheduler
  /smith-queue scheduler set-time <HH:MM>                     — Change scheduled run time

Queue: .smith/vault/queue/  |  History: .smith/vault/queue/history/
```
