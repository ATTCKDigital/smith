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

This creates a plist at `~/Library/LaunchAgents/com.attck.smith-scheduler.plist` and loads it with `launchctl`.

### Uninstalling the LaunchAgent

```bash
launchctl unload ~/Library/LaunchAgents/com.attck.smith-scheduler.plist
rm ~/Library/LaunchAgents/com.attck.smith-scheduler.plist
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

1. **Read projects** -- The scheduler reads `~/.smith/scheduler/projects.json`, which lists the absolute paths of projects registered for autonomous processing.

2. **Scan queues** -- For each project, the scheduler scans `.smith/vault/queue/` for task files with `"status": "pending"` or `"status": "scheduled"` and `"mode": "autonomous"`.

3. **Select task** -- Tasks are processed in priority order (highest priority first), then by creation date (oldest first).

4. **Create worktree** -- A fresh git worktree is created on a new branch (`smith/auto/<task-id>`) so autonomous work does not interfere with your working directory.

5. **Run Claude** -- Claude Code is invoked in non-interactive mode (`claude -p`) with the task description as the prompt. The security guards remain active during autonomous runs.

6. **Complete** -- On success, the task file is moved to `.smith/vault/queue/history/` with the status updated to `"completed"`. On failure, the status is set to `"failed"` with an error summary.

7. **Clean up** -- The worktree is removed after processing.

---

## Logs

All scheduler output is written to:

```
~/.smith/scheduler/scheduler.log
```

Each run is timestamped. The log includes which projects were scanned, which tasks were picked up, and the outcome of each task (completed, failed, or skipped).

---

## Registering Projects

To add a project to the scheduler, edit `~/.smith/scheduler/projects.json`:

```json
{
  "projects": [
    "/Users/you/Projects/my-app",
    "/Users/you/Projects/another-app"
  ]
}
```

Only projects listed here will be scanned for autonomous tasks.

---

## Security Considerations

See [Security Model](security-model.md) for a detailed discussion of scheduler security. Key points:

- The scheduler runs as your user, not as root.
- Only tasks explicitly marked `"mode": "autonomous"` are processed.
- Each task runs in an isolated git worktree.
- Claude runs in non-interactive mode and cannot prompt for input.
- Review `~/.smith/scheduler/smith-scheduler.sh` before enabling.
