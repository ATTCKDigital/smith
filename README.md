[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![29 Skills](https://img.shields.io/badge/skills-29-brightgreen.svg)](skills/)
[![Claude Code](https://img.shields.io/badge/Claude-Code-blueviolet.svg)](https://claude.ai/code)

# Smith

> Spec-driven development for Claude Code — requirements, plans, and tasks that ship as working code.

<!-- asciinema placeholder -->
_See [smith.attck.com](https://smith.attck.com) for a walkthrough._

---

## What is Smith?

Claude Code is a powerful AI coding assistant, but it has no built-in workflow structure. Developers jump straight from a vague idea to generated code with no specification, no plan, and no audit trail. The result is hard to review, harder to maintain, and impossible to trace back to requirements. When something goes wrong — and it will — there is no record of what was intended, what was decided, or why.

Smith fixes this by adding 28 skills that encode a full development workflow into Claude Code. The pipeline flows from **spec to plan to tasks to implementation to review to ship**. Every step produces a versioned artifact inside a `.specify/` directory in your project. Claude reads the output of each step as input to the next, so context accumulates instead of evaporating. You never have to re-explain what you're building.

The outcome: you talk to Claude about what you want to build, Smith handles the structured process, and you get a merged PR with full traceability from idea to code. Hooks log every session automatically and guard against common mistakes — dangerous shell commands, secret exposure, writes to sensitive files. A scheduler can process queued tasks overnight. Everything runs locally on your machine, nothing phones home, and every artifact is a plain text file you can read, diff, and version-control.

---

## Getting Started

### Install via the `skills` CLI (skills only)

```bash
npx skills add ATTCKDigital/smith
```

This is the fastest path — it copies all 26 Smith skills into `~/.claude/skills/` and nothing else. Use this if you only want the Smith workflow commands.

**To update:** re-run the same command. `npx skills add` is idempotent.

**To verify:** open Claude Code and type `/smith` — if it autocompletes, you're set.

### Install via the bundled installer (skills + hooks + scheduler)

```bash
curl -fsSL https://raw.githubusercontent.com/ATTCKDigital/smith/main/scripts/install.sh | bash
```

Use this for the full Smith experience. In addition to the skills, it wires up the security / logging hooks and (optionally) the macOS scheduler LaunchAgent. See [Installation](#installation) for details.

### First run

Once installed, open any new or existing project in your terminal and run `/smith` to initialize the vault, bank, and ledger for that project. Once initialized, run `/smith-new` and describe what you want to build. Smith walks you through requirements, planning, task breakdown, implementation, and PR creation — all without leaving the terminal.

> **Note:** Installation is a one-time global setup into `~/.claude/`. Running `/smith` is a separate per-project step that must be done once in each project before using other commands.

---

## What's Inside

### Skills (29)

| Category | Commands | Description |
|---|---|---|
| Feature workflow | `/smith-new`, `/smith-explore`, `/smith-specify`, `/smith-clarify`, `/smith-plan`, `/smith-tasks`, `/smith-analyze`, `/smith-implement`, `/smith-build`, `/smith-bugfix`, `/smith-checklist`, `/smith-finish` | End-to-end feature development pipeline |
| Debugging and audit | `/smith-debug`, `/smith-audit` | Diagnostic investigation and cross-system audit reporting |
| Knowledge and vault | `/smith-vault`, `/smith-bank`, `/smith-queue`, `/smith-todo`, `/smith-ledger`, `/smith-reflect` | Persistent session logs, idea storage, task queuing, and accumulated learning |
| Reporting | `/smith-report`, `/smith-taskstoissues` | Client-facing reports and GitHub issue generation |
| Manifest | `/smith-index`, `/smith-navigate`, `/smith-migrate-system-paths` | Precomputed project index, Haiku navigator, and one-shot path-frontmatter migration for structured context retrieval (see [docs/manifest-system.md](docs/manifest-system.md)) |
| Meta | `/smith`, `/smith-update`, `/smith-constitution`, `/smith-migrate-specs`, `/smith-help` | Project initialization, version sync, governance, and reference |

### Hooks (12)

| Hook | Event | Purpose |
|---|---|---|
| `session-start-logger.sh` | SessionStart | Creates a session log in `.smith/vault/sessions/` |
| `session-end-review.sh` | Stop | Reviews changes made during the session and prompts for spec updates |
| `grade-response.sh` | Stop | Grades the turn against `~/.claude/CLAUDE.md` rubric via a Haiku critic; blocks the stop and forces a retry when score < 100 (up to 3 retries) |
| `file-change-logger.sh` | PostToolUse (Write/Edit) | Logs every file change to the active session log |
| `lint-on-save.sh` | PostToolUse (Write/Edit) | Runs the project linter on changed files |
| `manifest-updater.sh` | PostToolUse (Write/Edit) | Updates `.smith/index/` metadata after edits; emits 300-line advisory warnings. Runs LAST in the chain so it sees the post-lint file state. |
| `context-loader.sh` | UserPromptSubmit | Detects `/smith-*` invocations and natural-language triggers; injects vault + navigator context as `additionalContext` before reasoning starts. Zero overhead for regular conversation. |
| `security-guard-bash.sh` | PreToolUse (Bash) | Blocks dangerous commands and secret exposure |
| `security-guard-files.sh` | PreToolUse (Write/Edit) | Blocks writes to sensitive files without explicit approval |
| `workflow-gate.sh` | PreToolUse (Bash, Write/Edit) | Denies file-modifying tool calls when no `.smith/vault/active-workflows/*.yaml` marker exists. Runs AFTER security guards so security blocks take precedence. See the [Workflow gate](#workflow-gate) section. |
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

## Manifest System

Smith ships with a **precomputed project index** plus a **Haiku-powered navigator** that injects a curated file list into Claude's context *before* reasoning starts. The goal: stop Claude from reading the wrong files, reading too many files, or missing cross-referenced helpers it actually needs.

### What it is

- A hierarchical manifest at `.smith/index/` that describes every source file — system membership, line count, exports, imports, FastAPI/Express routes, React components.
- An **optional LLM description layer in `.meta`** (v2) — per-module + per-method natural-language descriptions generated by `/smith-index --describe` (Haiku 4.5), updated in-context by smith workflows, and preserved verbatim by the save hook. Staleness is detectable via `Hash != Described-Against-Hash`.
- A `UserPromptSubmit` hook (`context-loader.sh`) that detects `/smith-*` invocations and natural-language triggers, then injects assembled context as `additionalContext` before the main session reasons.
- A `PostToolUse` hook (`manifest-updater.sh`) that keeps the manifest current as files are edited.
- Three skills: `/smith-index` (build / refresh / migrate the manifest, including `--describe` bulk LLM pass), `/smith-navigate` (return categorized Must Read / Should Read / Reference Only file lists), and `/smith-migrate-system-paths` (one-shot retrofit of `paths:` frontmatter on existing prose-only system specs).

### Why it matters

- Eliminates "Claude read the wrong files" failures by giving the model a deterministic candidate list up front.
- Reduces token waste from speculative reads — annotated whole-file reads with primary-section hints instead of grep-everything.
- Makes `/smith-explore` Phase 1 faster — manifest lookup first, grep only when the manifest doesn't cover the query.
- Surfaces file-size hygiene throughout the workflow (300/500-line thresholds appear in `.meta`, PR descriptions, and audit reports).
- Regular conversation has **zero overhead** — the hook short-circuits when no Smith skill or trigger phrase is detected.

### How to enable it

Auto-installed by `npx skills add ATTCKDigital/smith` (use `--no-hooks` to opt out). Then in any project:

```sh
/smith init        # new project — runs /smith-index as its last setup step
/smith-index       # existing project — first-time index build (~40s for 300 files)
```

### How it changes your daily flow

Mostly invisible. Hooks fire automatically when you edit files; the manifest stays current. You'll see:

- **`/smith-navigate "task description"`** — ad-hoc lookup, returns a categorized file list in under 3 seconds.
- **`/smith-index --check`** — quick freshness check (SHA-256 of first 4KB per file) without rebuilding.
- **File-size advisories** in `/smith-build` PR descriptions and `/smith-audit` reports when files cross 300 lines.

For the full design, the 4-tier `context-manifest.json` resolution, the path-resolver heuristic, and troubleshooting, see [docs/manifest-system.md](docs/manifest-system.md).

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
- Backs up your existing `~/.claude/CLAUDE.md` (if any) and installs the Smith rubric
- Copies all 26 skills to `~/.claude/skills/`
- Copies all 9 hooks to `~/.claude/hooks/`
- Merges hook configuration into `settings.json` (requires `jq`)
- Optionally installs the macOS scheduler LaunchAgent

The installer is idempotent — running it again updates skills and hooks without duplicating entries.

After installing, run `/smith` once inside each project to complete **per-project initialization**: scaffolding the vault, bank, ledger, `.specify/` templates, and generating `CLAUDE.md` and `constitution.md` for that project.

### Updating

The recommended path is via the `/smith-update` skill inside Claude Code:

```
/smith-update
```

`/smith-update` compares your installed Smith version against the latest upstream main, prompts to update, runs the installer if accepted, and (when invoked inside a Smith-initialized project) also refreshes per-project artifacts: `.specify/scripts/`, `.claude/commands/smith.*`, the `CLAUDE.md` / `constitution.md` templates (non-destructively via `/smith-index --migrate-templates`), and offers to bootstrap the manifest sidecar if the project predates the manifest system (PR #19). It snapshots the global install to `~/.smith/.backups/<timestamp>/` before destructive work so a failed install can be rolled back. The first invocation against a pre-versioning install (no `~/.smith/.installed-version` file) silently establishes a baseline — no false "X commits behind" prompts.

You can still update Smith manually if preferred:

```bash
cd /path/to/smith && git pull && ./scripts/install.sh -y
```

The manual path runs the same idempotent `install.sh` (existing duplicate hook entries in `~/.claude/settings.json` are now collapsed on every install).

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

### Coexistence with a `Bash(rm:*)` deny rule

Some projects add `"Bash(rm:*)"` to the `deny` list of `.claude/settings.json` as a safety rail against accidental deletion. In Claude Code, `deny` supersedes `allow`, so a workflow can't route around the deny rule by whitelisting a narrower `rm` pattern.

To let Smith clean up its per-branch active-workflow markers under that rule, `/smith` ships a narrow helper at `.specify/scripts/bash/clear-active-workflow.sh`. The helper only unlinks a single file matching `.smith/vault/active-workflows/<safe-branch>.yaml`, never globs, never recurses, and refuses any path that escapes the active-workflows directory. Every Smith workflow skill calls it instead of inline `rm`, and the default project permissions allow-list it explicitly — so the `Bash(rm:*)` deny stays in place and cleanup still works.

As a safety net, `hooks/active-workflow-janitor.sh` runs on every `Stop` event and sweeps orphaned markers whose branch is gone (locally and on origin) or already merged into `origin/main`. Hooks bypass the permission matcher, so the sweep works under a `Bash(rm:*)` deny rule without needing an allow-list entry, and it also collects markers left behind by sessions that crash or are interrupted before a skill's normal cleanup runs. Active branches are never touched.

See [docs/security-model.md](docs/security-model.md) for a detailed breakdown of the threat model and mitigations.

### Workflow gate

The `workflow-gate.sh` PreToolUse hook enforces Smith's core discipline at the tool layer: **all file edits must happen inside a Smith workflow.** Without an active workflow marker, every `Write`, `Edit`, and file-touching `Bash` command (`rm`, `mv`, `sed -i`, `tee`, `cp`, `chmod`, `touch`, redirection) is denied with a message pointing at the three top-level workflow commands.

#### What counts as an active workflow

A workflow is "active" if and only if at least one `*.yaml` file exists under `<project>/.smith/vault/active-workflows/`. Markers are created by these workflows:

| Workflow | Marker created |
|---|---|
| `/smith` (init) | `bootstrap.yaml` (cleared at end of init) |
| `/smith-new` | `<branch-name>.yaml` (cleared after merge) |
| `/smith-bugfix` | `<branch-name>.yaml` (cleared after merge) |
| `/smith-debug` | `debug-<slug>.yaml` (cleared at decision-gate exit) |
| `/smith-build` | inherits parent or creates `<branch>.yaml` |
| `/smith-finish` | `finish-<branch>.yaml` (cleared at end) |

Stale markers (branch already merged, branch gone) are swept on every `Stop` event by `active-workflow-janitor.sh`.

#### Layering with security guards

`workflow-gate.sh` runs *after* `security-guard-bash.sh` and `security-guard-files.sh`. A write blocked for security reasons (writing to `.env`, force-pushing to main, etc.) surfaces the security-guard's deny message — not the workflow gate's. This way the more important invariant wins.

#### Exemptions

- **Projects without Smith** — if no `.smith/` directory exists, the gate exits silently. Smith isn't installed; not its place to gate.
- **Vault-internal infrastructure writes** — writes under `.smith/vault/{sessions, bank, ledger, queue, agents, todo, reports, index, audits}/` are allowed regardless of marker (hooks and skills write to the vault constantly). The gate does NOT exempt `.smith/vault/active-workflows/` itself — this prevents a malicious Write from forging its own marker to bypass the gate.
- **Read-only Bash** — `ls`, `git status`, `cat`, `grep`, `git log`, etc. always succeed. Only file-touching subcommands are blocked.

#### Standalone-invocation impact (BREAKING)

Eight design-phase skills can no longer be invoked standalone — they only work inside a top-level workflow:

- `/smith-implement`, `/smith-plan`, `/smith-specify`, `/smith-checklist`, `/smith-clarify`, `/smith-constitution`, `/smith-tasks`, `/smith-migrate-specs`

These skills now carry a "Workflow requirement" callout at the top of their `SKILL.md`. To use them, start `/smith-new`, `/smith-bugfix`, `/smith-debug`, or `/smith-build` first.

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
