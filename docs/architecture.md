# Architecture

Smith is composed of four subsystems: skills, hooks, the scheduler, and the vault. Each operates independently but they share data through the vault's filesystem-based structure.

---

## Overview

```
Smith
  |-- Skills (33)      Claude Code slash commands and utilities
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

## Activity Daemon

The activity daemon is Smith's second background process, and it sits here next to the scheduler because the two share a shape: both run outside Claude Code, both outlive any one session, and both are things you can forget are running.

```
/smith-activity  (scripts/activity/smith-activity.sh)
  |-- one daemon, ~/.smith/activity/{activity.pid,port,token,log}
      |-- http.server.ThreadingHTTPServer bound to 127.0.0.1 only
          |-- POST /ingest      <- hooks/activity-emitter.sh, one per hook event
          |-- POST /statusline  <- scripts/activity/statusline-tee.sh
          |-- GET  /events      -> SSE: hello, state, delta, resync, quota, finding
          |-- GET  /api/*       -> JSON read routes (state, workflows, worktrees, usage, vault)
          |-- GET  /            -> scripts/activity/static/, no external origin
```

### One daemon, many projects

There is exactly **one** daemon per machine, not one per project. `/smith-activity` run in a second repository registers that repository with the daemon already listening and opens the same URL with a different `?project=` filter; it never starts a second process. A project is keyed by its **primary-repo path**, so a worktree is a view of a project rather than a second project, and totals are global with a per-project filter rather than per-project silos.

Idempotence is the whole contract of the CLI. A second invocation finds the running daemon by probing `/health` for `service == "smith-activity"` — the identity probe, not the HTTP status, because an unrelated process listening on the port also answers. An unrelated occupant means pick and record another port; a stale pidfile (pid gone, or alive but foreign) means clean up and restart. Neither is an error path.

### Transport: SSE, coalesced

The browser holds one `GET /events` Server-Sent Events connection. Ingest handlers never touch a socket — they mutate the state tree and set a dirty flag. A single broadcaster thread wakes on that flag, waits a fixed 200 ms, bumps a `generation` counter and fans out **one** `delta` frame, with a per-connection ceiling of 5 frames per second. The debounce is a fixed-interval leaky bucket rather than a reset-on-every-event timer, which is what bounds worst-case latency at 200 ms under a `PostToolUse` storm instead of starving the client indefinitely. One frame per tool call is explicitly forbidden.

Everything the SSE stream carries is also reachable as a plain `GET /api/*` read, which is what makes the whole projection fixture-testable with no daemon running at all.

### Retention is ephemeral, on purpose

The daemon keeps its state in memory and writes no event history to disk. Stopping it, or restarting it, discards everything it had observed. This is a deliberate v1 boundary, not an oversight: an audit tool that quietly accumulated every prompt and tool input on disk would be a far larger privacy surface than the one it is auditing. The consequence is made visible rather than hidden — the client tracks `generation`, and a **lower** generation than the one it last saw means the daemon restarted, which renders an explicit "history reset at daemon restart" banner rather than a silently truncated timeline.

### An audit, not a monitor

The distinction is the reason this component exists, and it is enforced by a trust hierarchy rather than by good intentions:

1. **Hook events are the primary source.** What the harness observed is the displayed value.
2. **Self-reported state is carried beside it, never instead of it.** A finding holds both `observed` and `self_reported`, and no layer is permitted to "reconcile" a conflict by discarding one side.
3. **Corroboration is not evidence.** `claude agents --json` is polled for liveness reconciliation only. Where its `status` field is present and disagrees with the event-derived permission state, that disagreement becomes a finding; where it is absent — the common case — it produces nothing at all, because absence of corroboration is not disagreement.
4. **Absence is a first-class observation.** A phase that was skipped, a mandatory-stop gate that was never reached, a hook that was wired and applicable and never fired: each is a finding in its own right.
5. **Blindness is never reported as absence.** When no event source is installed, or the hook log cannot be read, absence detection switches **off** and says so in a notice. It never guesses, and it never lets "I cannot see" wear the grammar of "this did not happen."

The daemon is advisory and non-blocking throughout. Nothing in it modifies, pauses, gates or interferes with the workflow it is watching, and it never writes to any project's `.smith/vault/`.

### Two project roots, and the marker the gate never reads

Building this surfaced a pre-existing inconsistency in how Smith resolves "the project root", which every marker consumer now has to know about.

**The two resolutions disagree inside a git worktree:**

| Caller | Resolution | Returns, inside a worktree |
|---|---|---|
| `scripts/create-active-workflow.sh:139` | `git rev-parse --show-toplevel` | the **worktree** |
| `hooks/workflow-gate.sh:60` | `${CLAUDE_PROJECT_DIR:-$(pwd)}` → `--git-common-dir` → `dirname` | the **primary repo** |
| `hooks/active-workflow-janitor.sh:42` | `${CLAUDE_PROJECT_DIR:-$PWD}` → `--git-common-dir` → `dirname` | the **primary repo** |

So the writer and the readers do not agree on where markers live. Four consequences, all observed live on 2026-09-22 during this feature's own build:

1. **Two concurrent markers for one branch are normal, not an error.** A `/smith-new` marker lands in the primary repo's vault; a `/smith-build` marker for the *same branch* lands in the worktree's vault. The second `create-active-workflow.sh` call exits **0**, not 3 — it never sees the first marker, because it is not looking in the same directory. `research.md` §Q6's "guaranteed exit 3, two concurrent markers never exist" conclusion is false; see the correction note appended there.
2. **The worktree marker's `session_log:` field is empty.** `.smith/vault/.current-session` does not exist in a worktree, so the field is written with a trailing space and nothing after it. That is a valid, occurring shape, not corruption.
3. **The worktree marker is write-only state.** The gate resolves to the primary repo and reads only that vault, so nothing in Smith ever consumes the marker it just wrote into the worktree.
4. **Consequence 3 broke this build.** `active-workflow-janitor.sh` runs on every `Stop` and sweeps any marker whose branch tip is reachable from `main` — trivially true before a branch's first commit. Its one-hour grace window (`SMITH_JANITOR_GRACE_SECONDS`, default 3600) bounds the damage to short runs only; a multi-hour build that has not committed yet sails straight past it. The janitor swept the **primary** marker mid-build, silently revoking the build's write authorization, while the worktree marker nothing reads sat there untouched.

**What this means for anything that reads markers.** Enumerate **both** vaults — the primary repo's and every linked worktree's, via `git worktree list --porcelain` — correlate records by `branch:`, and tolerate an empty `session_log:` with a fallback to the primary vault's `.current-session`. `scripts/activity/markers.py` does exactly this. Two markers naming one branch with different `workflow:` values is the signal for a legitimate nested workflow (`smith-new` handing off to `smith-build`), not a contradiction to report.

**This is documented, not fixed.** The fix is a behavior change to a script and two hooks with its own blast radius across every workflow, and it is banked as a separate bugfix alongside BANK-030 rather than smuggled into a dashboard feature.

See [Security Model](security-model.md#activity-daemon-security) for the daemon's network and privacy surface.

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
