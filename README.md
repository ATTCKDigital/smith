[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![24 Skills](https://img.shields.io/badge/skills-24-brightgreen.svg)](skills/)
[![Claude Code](https://img.shields.io/badge/Claude-Code-blueviolet.svg)](https://claude.ai/code)

# Smith

> Spec-driven development for Claude Code — requirements, plans, and tasks that ship as working code.

<!-- asciinema placeholder -->
_Demo coming soon — see [smith.attck.com](https://smith.attck.com) for a walkthrough._

---

## What is Smith?

Claude Code is a powerful AI coding assistant, but it has no built-in workflow structure. Developers jump straight from a vague idea to generated code with no specification, no plan, and no audit trail. The result is hard to review, harder to maintain, and impossible to trace back to requirements. When something goes wrong — and it will — there is no record of what was intended, what was decided, or why.

Smith fixes this by adding 25 skills that encode a full development workflow into Claude Code. The pipeline flows from **spec to plan to tasks to implementation to review to ship**. Every step produces a versioned artifact inside a `.specify/` directory in your project. Claude reads the output of each step as input to the next, so context accumulates instead of evaporating. You never have to re-explain what you're building.

The outcome: you talk to Claude about what you want to build, Smith handles the structured process, and you get a merged PR with full traceability from idea to code. Hooks log every session automatically and guard against common mistakes — dangerous shell commands, secret exposure, writes to sensitive files. A scheduler can process queued tasks overnight. Everything runs locally on your machine, nothing phones home, and every artifact is a plain text file you can read, diff, and version-control.

---

## Quick Start

```bash
curl -fsSL https://raw.githubusercontent.com/ATTCKDigital/smith/main/scripts/install.sh | bash
```

Then open any project in your terminal and run `/smith` to initialize the vault, bank, and ledger for that project. Once initialized, run `/smith-new` and describe what you want to build. Smith walks you through requirements, planning, task breakdown, implementation, and PR creation — all without leaving the terminal.

> **Note:** `install.sh` is a one-time global setup that installs skills, hooks, and the scheduler into `~/.claude/`. Running `/smith` is a separate per-project step that must be done once in each project before using other commands.

---

## What's Inside

### Skills (25)

| Category | Commands | Description |
|---|---|---|
| Feature workflow | `/smith-new`, `/smith-specify`, `/smith-clarify`, `/smith-plan`, `/smith-tasks`, `/smith-analyze`, `/smith-implement`, `/smith-build`, `/smith-bugfix`, `/smith-checklist`, `/smith-finish` | End-to-end feature development pipeline |
| Debugging | `/smith-debug` | Diagnostic investigation with structured evidence gathering |
| Knowledge and vault | `/smith-vault`, `/smith-bank`, `/smith-queue`, `/smith-todo`, `/smith-ledger`, `/smith-reflect` | Persistent session logs, idea storage, task queuing, and accumulated learning |
| Reporting | `/smith-report`, `/smith-taskstoissues` | Client-facing reports and GitHub issue generation |
| Meta | `/smith`, `/smith-constitution`, `/smith-migrate-specs`, `/smith-help` | Project initialization, governance, and reference |

### Hooks (8)

| Hook | Event | Purpose |
|---|---|---|
| `session-start-logger.sh` | SessionStart | Creates a session log in `.smith/vault/sessions/` |
| `session-end-review.sh` | Stop | Reviews changes made during the session and prompts for spec updates |
| `file-change-logger.sh` | PostToolUse (Write/Edit) | Logs every file change to the active session log |
| `lint-on-save.sh` | PostToolUse (Write/Edit) | Runs the project linter on changed files |
| `security-guard-bash.sh` | PreToolUse (Bash) | Blocks dangerous commands and secret exposure |
| `security-guard-files.sh` | PreToolUse (Write/Edit) | Blocks writes to sensitive files without explicit approval |
| `task-router.sh` | PreToolUse (Task) | Routes sub-agent tasks during active workflows |
| `subagent-vault-writeback.sh` | SubagentStop | Persists sub-agent findings to the vault |

### Scheduler

Smith includes a macOS LaunchAgent that runs the queue processor daily at 2:00 AM. It picks up autonomous tasks from `.smith/vault/queue/`, processes them in isolated git worktrees, and writes results back. This lets you queue up low-priority work during the day and have it done by morning. macOS only for now; Linux systemd support is planned.

---

## How It Works

```
idea
  |
  v
/smith-new        Capture the idea, set up project structure
  |
  v
spec.md           Requirements document with acceptance criteria
  |
  v
plan.md           Technical plan: approach, components, risks
  |
  v
tasks.md          Ordered task breakdown with dependencies
  |
  v
/smith-build      Implement tasks, run tests, commit
  |
  v
PR merged         Reviewed, approved, shipped
```

The **vault** (`.smith/vault/`) is the persistent memory layer. It stores:

- **Session logs** — automatic record of every Claude Code session
- **Agent findings** — sub-agent investigation results that survive across sessions
- **Queue** — deferred tasks for autonomous processing
- **Idea bank** — parked ideas to revisit later
- **Ledger** — accumulated lessons learned from past work

**Hooks** fire on every tool use for security and logging. They require no configuration — the installer wires them into Claude Code's settings automatically.

The **scheduler** processes autonomous tasks from the queue overnight using git worktrees so your working tree stays clean.

---

## Installation

### Quick install

```bash
curl -fsSL https://raw.githubusercontent.com/ATTCKDigital/smith/main/scripts/install.sh | bash
```

### Manual install

```bash
git clone https://github.com/ATTCKDigital/smith.git
cd smith
./scripts/install.sh
```

### What the installer does

The installer is a **one-time global setup** — it installs Smith into `~/.claude/` and does not modify any project.

- Backs up your existing `~/.claude/settings.json`
- Copies all 25 skills to `~/.claude/skills/`
- Copies all 8 hooks to `~/.claude/hooks/`
- Merges hook configuration into `settings.json` (requires `jq`)
- Optionally installs the macOS scheduler LaunchAgent

The installer is idempotent — running it again updates skills and hooks without duplicating entries.

After installing, run `/smith` once inside each project to complete **per-project initialization**: scaffolding the vault, bank, ledger, `.specify/` templates, and generating `CLAUDE.md` and `constitution.md` for that project.

### Updating

```bash
cd /path/to/smith && git pull && ./scripts/install.sh -y
```

### Uninstalling

```bash
./scripts/uninstall.sh
```

This removes skills, hooks, and the scheduler LaunchAgent. It restores your original `settings.json` from the backup created during install.

---

## Requirements

- **Claude Code** ([claude.ai/code](https://claude.ai/code))
- **macOS or Linux**
- **git**
- **jq** — required for settings.json manipulation during install
- **gh CLI** (optional) — for PR creation and GitHub issue management

---

## Configuration

All configuration is through environment variables. Everything is optional — Smith works out of the box with sensible defaults.

| Variable | Default | Purpose |
|---|---|---|
| `SMITH_HOME` | `~/.smith` | Scheduler and runtime state directory |
| `CLAUDE_HOME` | `~/.claude` | Claude Code config directory |
| `SMITH_SKIP_SCHEDULER` | (unset) | Set to `1` to skip the scheduler prompt during install |
| `SMITH_ASSUME_YES` | (unset) | Set to `1` to auto-accept all install prompts |

---

## Security

Smith runs entirely on your machine. **No telemetry. No phone-home. No external services.**

The security guard hooks block:

- **Dangerous shell commands** — `rm -rf /`, force pushes to main, `git reset --hard`, and similar destructive operations
- **Secret exposure** — reading or printing `.env` files, credentials, API keys, and tokens
- **Sensitive file writes** — modifications to lock files, CI configs, and other protected files without explicit approval
- **Credential echo** — printing environment variables that contain secrets

The scheduler runs bash scripts via macOS `launchd`. You can audit the full script at `scheduler/smith-scheduler.sh` before enabling it.

See [docs/security-model.md](docs/security-model.md) for a detailed breakdown of the threat model and mitigations.

---

## Troubleshooting

**"jq not found"**
Install jq before running the installer:
```bash
brew install jq        # macOS
apt install jq         # Debian/Ubuntu
```

**Skills not appearing in Claude Code**
Verify the skills directory exists:
```bash
ls ~/.claude/skills/smith/
```
If missing, re-run `./scripts/install.sh`.

**Hooks not firing**
Check that `~/.claude/settings.json` contains the hook entries. Compare your settings with the reference fragment:
```bash
cat settings/smith-settings-fragment.json
```

**Scheduler not running**
```bash
launchctl list | grep smith
```
Review logs at `~/.smith/scheduler/scheduler.log` for errors.

**Vault directories missing**
Run `/smith` inside the project to run per-project initialization (vault, bank, ledger, `.specify/` scaffolding, `CLAUDE.md`). This is required once per project before using other Smith commands. To create just the vault directories manually:
```bash
mkdir -p .smith/vault/{sessions,agents,queue,bank,ledger}
```

---

## Contributing

Issues and bug reports are welcome. Pull requests are by invitation — see [CONTRIBUTING.md](CONTRIBUTING.md) for details.

---

## License

MIT — see [LICENSE](LICENSE).

---

## Credits

Built by [ATTCK](https://attck.com). Inspired by [superpowers](https://github.com/obra/superpowers), [ralph](https://github.com/snarktank/ralph), [claude-mem](https://github.com/thedotmack/claude-mem), and [claude-skills](https://github.com/alirezarezvani/claude-skills).
