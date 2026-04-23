# Scheduler

The Smith scheduler enables autonomous overnight processing of queued tasks. It runs as a macOS LaunchAgent, executing once daily at 2:00 AM.

---

## What the Scheduler Does

The scheduler reads your registered projects, scans each project's vault queue for tasks marked as autonomous, and processes them one at a time in isolated git worktrees using Claude Code in non-interactive mode.

A typical use case: during the day you queue up tasks with `/smith-queue add --mode autonomous "Refactor the auth module to use middleware pattern"`. At 2:00 AM, the scheduler picks up those tasks, creates worktrees, runs Claude against each one, commits the results, and moves completed tasks to history.

---

## Platform Support

- **macOS**: Fully supported via LaunchAgent
- **Linux**: Not yet supported as a daemon. Run manually via cron (see below).
- **Windows**: Not supported.

---

## Installing the LaunchAgent

The installer offers to set up the LaunchAgent during `scripts/install.sh`. To install it manually:

```bash
bash ~/.smith/scheduler/install-launchagent.sh
```

This creates a plist at `~/Library/LaunchAgents/com.smith.scheduler.plist` and loads it with `launchctl`.

### Uninstalling the LaunchAgent

```bash
launchctl unload ~/Library/LaunchAgents/com.smith.scheduler.plist
rm ~/Library/LaunchAgents/com.smith.scheduler.plist
```

---

## Running Manually

You can run the scheduler at any time without the LaunchAgent:

```bash
bash ~/.smith/scheduler/smith-scheduler.sh
```

For Linux users, add this to your crontab:

```
0 2 * * * bash ~/.smith/scheduler/smith-scheduler.sh >> ~/.smith/scheduler/scheduler.log 2>&1
```

---

## How Task Processing Works

The scheduler is a **thin launcher**. It decides *what* to run, then delegates each task to the `/smith-queue` skill which owns the full pipeline.

1. **Read projects** — The scheduler reads `~/.smith/projects.json`, which lists the absolute paths of project vaults registered for autonomous processing.

2. **Scan queues** — For each project, the scheduler scans `.smith/vault/queue/` for entries with `complexity: autonomous` and `status: pending` or `status: scheduled`. Scheduled items whose `scheduled_for` is a future date are skipped.

3. **Filter and sort** — Tasks with unmet `depends_on` references are skipped. Remaining tasks are priority-sorted (critical → high → medium → low), then by creation date (oldest first).

4. **Dispatch to the skill** — For each selected task, the scheduler invokes:

   ```bash
   "$CLAUDE_BIN" --model "$CLAUDE_MODEL" --permission-mode bypassPermissions \
       -p "/smith-queue process <filename>"
   ```

   from the project root. The `/smith-queue process` pipeline then runs in-process: status updates → git worktree on the entry's `branch` field → `/smith-build` → Docker rebuild → tests → `gh pr create` → `gh pr merge` → spec + CHANGELOG updates → move entry to `history/` → worktree cleanup. See `skills/smith-queue/SKILL.md` for the full pipeline spec and the "Scheduler invocation contract" section.

5. **Verify outcome** — The scheduler captures the skill's exit code and checks whether the queue entry was moved to `history/`. The scheduler does NOT mutate queue files itself — pre-mutating state before the skill took ownership was the root cause of the 2026-04-23 silent-completion regression.

### Dry run

Set `SMITH_SCHEDULER_DRY_RUN=1` to log what would be dispatched without invoking Claude. Useful for verifying filter/sort logic after changes without billing a real run.

```bash
SMITH_SCHEDULER_ENABLED=1 SMITH_SCHEDULER_DRY_RUN=1 \
    bash ~/.smith/scheduler/smith-scheduler.sh
```

### Model override

Default model is `sonnet`. Override per-run with `SMITH_SCHEDULER_MODEL`:

```bash
SMITH_SCHEDULER_ENABLED=1 SMITH_SCHEDULER_MODEL=haiku \
    bash ~/.smith/scheduler/smith-scheduler.sh
```

### Kill switch

`SMITH_SCHEDULER_ENABLED` must be `1` for the scheduler to do anything. Without it the script logs a disabled message and exits 0. This acts as a soft uninstall — the launchd agent can remain loaded while the script is inert, which is useful for debugging without unloading the agent.

---

## Logs

All scheduler output is written to:

```
~/.smith/scheduler/scheduler.log
```

Each run is timestamped. The log includes which projects were scanned, which tasks were picked up, and the outcome of each task (completed, failed, or skipped).

---

## Registering Projects

Registered projects live in `~/.smith/projects.json` as a JSON array of entries. Each entry's `path` points at the project's `.smith/vault` directory (not the project root):

```json
[
  {
    "name": "my-app",
    "path": "/Users/you/Projects/my-app/.smith/vault",
    "last_session": "2026-04-23T13:01:16"
  }
]
```

Only projects listed here will be scanned for autonomous tasks. New entries are usually created automatically the first time you run `/smith` in a project.

---

## Security Considerations

See [Security Model](security-model.md) for a detailed discussion of scheduler security. Key points:

- The scheduler runs as your user, not as root.
- Only tasks explicitly marked `complexity: autonomous` are processed.
- Each task runs in an isolated git worktree.
- Claude runs in non-interactive mode and cannot prompt for input.
- Review `~/.smith/scheduler/smith-scheduler.sh` before enabling.
