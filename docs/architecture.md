# Architecture

Smith is composed of four subsystems: skills, hooks, the scheduler, and the vault. Each operates independently but they share data through the vault's filesystem-based structure.

---

## Overview

```
Smith
  |-- Skills (25)      Claude Code slash commands for workflows
  |-- Hooks (8)        Bash scripts fired by Claude Code lifecycle events
  |-- Scheduler (1)    macOS LaunchAgent for autonomous task processing
  |-- Vault            Per-project local data store (.smith/vault/)
```

---

## Skills Architecture

Skills are directories installed to `~/.claude/skills/`. Each skill directory contains a `SKILL.md` file with YAML frontmatter that defines the skill's name, description, and trigger patterns.

The main `smith` skill (`~/.claude/skills/smith/`) is the largest and contains subdirectories:

- **agents/** -- Sub-agent definitions for specialized tasks (analysis, implementation, review)
- **templates/** -- Markdown templates for specs, plans, tasks, reports, and other artifacts
- **scripts/** -- Bash scripts used by skills during workflow execution

All other skills (`smith-new`, `smith-debug`, `smith-bugfix`, etc.) are standalone directories that reference the main smith skill's templates and agents as needed.

### SKILL.md Frontmatter

```yaml
---
name: smith-example
description: Short description of what this skill does
---
```

The body of `SKILL.md` contains the skill's instructions, which Claude Code reads when the skill is invoked.

---

## Vault Structure

Each project that uses Smith gets a `.smith/vault/` directory at the project root. The vault is a local filesystem store -- nothing is synced or transmitted externally.

```
.smith/vault/
  |-- sessions/    JSONL logs, one per Claude Code session
  |-- agents/      Markdown files persisted by sub-agents
  |-- queue/       Task files (JSON) waiting for processing
  |   |-- history/ Completed or failed tasks moved here
  |-- bank/        Ideas saved mid-conversation
  |-- ledger/      Patterns and lessons learned from past workflows
```

### Sessions

Each session log is a JSONL file named by timestamp. Lines are appended by hooks throughout the session: session start, file changes, and session end events.

### Queue

Task files are JSON documents with fields for description, status, mode, priority, and metadata. The scheduler and `/smith-queue` command both read and write to this directory.

---

## Hook Execution Model

Hooks are registered in `~/.claude/settings.json` under the `hooks` key. Each entry specifies:

- The event type (SessionStart, Stop, PreToolUse, PostToolUse, SubagentStop)
- A matcher pattern (which tool or event name to match)
- The path to a bash script in `~/.claude/hooks/`

When Claude Code fires a matching event, it executes the corresponding bash script synchronously. PreToolUse hooks can block the tool call by returning a specific exit code. PostToolUse hooks run after the tool call completes and cannot block it.

See [Hooks Reference](hooks.md) for details on each hook.

---

## Scheduler Model

The scheduler runs outside of Claude Code as a standalone process:

```
launchd (macOS)
  |-- com.attck.smith-scheduler.plist
      |-- smith-scheduler.sh
          |-- reads ~/.smith/scheduler/projects.json
          |-- for each project:
              |-- scans .smith/vault/queue/ for autonomous tasks
              |-- creates git worktree on smith/auto/<task-id> branch
              |-- runs: claude -p "<task description>"
              |-- moves task to queue/history/
              |-- removes worktree
```

See [Scheduler](scheduler.md) for configuration and usage details.

---

## Artifact Flow

Smith workflows produce artifacts in a defined sequence:

```
Requirements gathering
  --> spec.md        Feature specification
  --> plan.md        Implementation plan with design decisions
  --> tasks.md       Ordered task list with dependencies
  --> Implementation Code changes, tests, commits
  --> PR             Pull request with summary and test plan
  --> Release notes  Generated from completed tasks
```

Each artifact builds on the previous one. The questions gate between spec and plan ensures alignment before implementation begins. All artifacts are stored in the project's `.smith/` directory.
