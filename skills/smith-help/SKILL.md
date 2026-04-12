---
name: smith-help
description: Central reference for all Smith commands — overview, detailed help per command, syntax, flags, and workflow context.
argument-hint: [<command>]
---

# Smith Help System

Display help for Smith commands. With no arguments, shows the full command overview. With a command name, shows detailed help including syntax, flags, examples, and workflow context.

**Arguments:** $ARGUMENTS

## Behavior

This action is **read-only** — it does not modify any files. It should always be handled directly by the current session, never delegated to a sub-agent.

### No Arguments — Full Overview

When invoked with no arguments, display this overview:

```
SMITH — Forge Your Workflow

FEATURE DEVELOPMENT
  /smith-new              Start a new feature end-to-end
  /smith-specify          Create or update a feature spec
  /smith-clarify          Ask clarification questions on a spec
  /smith-plan             Generate implementation plan from spec
  /smith-tasks            Break plan into ordered tasks
  /smith-analyze          Check consistency across spec/plan/tasks
  /smith-implement        Execute all tasks sequentially
  /smith-build            Autonomous build (tasks → implement → test → PR → merge)
  /smith-checklist        Generate quality checklist for spec/plan
  /smith-bugfix           Autonomous bugfix (branch → fix → test → PR → merge)
  /smith-debug            Diagnostic investigation (gather evidence → report → optional bugfix)

VAULT
  /smith-vault            Dashboard — recent sessions, agents, queue status
  /smith-vault sessions   List session logs
  /smith-vault agents     List sub-agent types and history
  /smith-vault queue      Show pending queue items
  /smith-vault projects   List all registered projects
  /smith-vault status     Vault health and routing metrics

QUEUE
  /smith-queue add        Add a task to the queue
  /smith-queue list       Show pending tasks by priority
  /smith-queue process    Pick and process a task (interactive, --next, --all, or <file>)
  /smith-queue batch      Alias for process --all
  /smith-queue status     Show tasks grouped by status
  /smith-queue schedule   Schedule a task for a specific time
  /smith-queue history    View completed and failed tasks
  /smith-queue edit       Modify a queued task
  /smith-queue promote    Change task from autonomous to interactive
  /smith-queue demote     Change task from interactive to autonomous
  /smith-queue requeue    Reset a failed task to pending
  /smith-queue scheduler  Manage the automated 2am batch scheduler

BANK
  /smith-bank               Deposit an idea from the current conversation
  /smith-bank list           Show all banked ideas (--priority, --system filters)
  /smith-bank process <id>   Withdraw idea and start /smith-new workflow
  /smith-bank edit <id>      Edit a banked idea's details
  /smith-bank remove <id>    Archive a banked idea
  /smith-bank prioritize <id> --priority <level>  Change priority

LEARNING
  /smith-reflect          Analyze completed workflow and extract lessons to the Ledger
  /smith-reflect --last N Analyze last N workflows in batch
  /smith-reflect --failure Learn from recent failures specifically
  /smith-ledger           Browse the Ledger dashboard
  /smith-ledger list      List all learned patterns by category
  /smith-ledger search    Search across all Ledger entries
  /smith-ledger prune     Remove stale low-confidence entries
  /smith-ledger reset     Archive and restart the Ledger
  /smith-ledger reconcile           Trigger Ledger self-maintenance (merge, prune, budget enforce)
  /smith-ledger reconcile --dry-run Preview reconciliation without modifying files
  /smith-ledger reconcile --force   Bypass lock and threshold checks
  /smith-ledger reconcile --status  Check if reconciliation is needed

REPORTS
  /smith-report           Generate client-facing project report

PROJECT
  /smith                  Bootstrap a new project with Smith workflow
  /smith-constitution     Create or update project constitution
  /smith-taskstoissues    Convert tasks.md to GitHub Issues
  /smith-migrate-specs    Migrate flat specs into system-based hierarchy

SESSION
  /smith-finish           Commit, push, merge, update specs, clean workspace

HELP
  /smith-help             This overview
  /smith-help <command>   Detailed help for a specific command
```

After displaying the overview, also scan `.claude/commands/` for any `smith.*.md` files not listed above. If found, append them under a "ADDITIONAL" section with their description from frontmatter. This ensures newly added commands appear in help even without explicit entries.

### With Arguments — Detailed Help

When `$ARGUMENTS` contains a command name, display detailed help for that command.

Match the argument against known commands. Accept with or without the `smith-` prefix (e.g., both `queue` and `smith-queue` work). Also accept partial matches for sub-commands (e.g., `queue process` matches `smith-queue process`).

---

#### `new`

```
/smith-new — New Feature Workflow

The primary entry point for building features. Combines conversational
requirements gathering, spec generation, planning, a mandatory questions
gate, and autonomous build into a single flow.

USAGE
  /smith-new <feature description>
  /smith-new                           (prompts for description interactively)

NATURAL LANGUAGE TRIGGERS
  "let's smith this"
  "start a smith workflow"
  "kick off a new feature for this"
  "let's build this"

PHASES
  1. Branch Safety    Check current branch, pull main if needed
  2. Requirements     Conversational gathering or parse $ARGUMENTS
  3. Spec & Branch    Auto-detect system, create branch, generate spec.md
  4. Plan             Generate plan.md, research.md, data-model.md
  5. Questions Gate   Generate questions.md — MANDATORY STOP for user answers
  6. Build            Launch /smith-build for autonomous execution

SYSTEM DETECTION
  Automatically determines primary_system and also_affects by analyzing
  the feature description against .specify/systems/system-*/spec.md.
  Feature spec is created at:
    .specify/systems/<primary-system>/features/<NNN-short-name>/

CHAINS INTO
  /smith-build (Phase 6 — autonomous from tasks through merged PR)

VAULT LOGGING
  Logs invocation, system detection, spec creation, questions generated,
  questions answered, and build handoff to the vault session log.
```

#### `specify`

```
/smith-specify — Feature Specification

Create or update a feature specification from a natural language description.

USAGE
  /smith-specify <feature description>

BEHAVIOR
  1. Generate branch short-name (2-4 words)
  2. Find next feature number across branches and specs
  3. Auto-detect primary system from .specify/systems/
  4. Create feature branch and spec folder
  5. Write spec.md with frontmatter (primary_system, also_affects, branch, status)
  6. Generate quality checklist at <feature>/checklists/requirements.md
  7. Validate spec (up to 3 iterations)

NEXT STEPS
  /smith-clarify → /smith-plan
```

#### `clarify`

```
/smith-clarify — Spec Clarification

Identify underspecified areas in the current feature spec and resolve them
through up to 5 targeted questions.

USAGE
  /smith-clarify

BEHAVIOR
  Runs on the current feature branch. Scans the spec for ambiguities across
  10 taxonomy categories. Presents one question at a time with recommended
  answers. Updates the spec inline after each answer.

QUESTIONS FILE
  Stored at <feature-folder>/questions.md (inside the spec folder, not specs/questions/)

NEXT STEP
  /smith-plan
```

#### `plan`

```
/smith-plan — Implementation Planning

Generate a technical implementation plan from the feature spec.

USAGE
  /smith-plan

ARTIFACTS PRODUCED
  plan.md          Architecture, file structure, tech decisions
  research.md      Resolved unknowns, dependency research
  data-model.md    Entity definitions and relationships
  contracts/       API specifications
  quickstart.md    Integration scenarios

NEXT STEPS
  /smith-tasks → /smith-analyze → /smith-implement
```

#### `tasks`

```
/smith-tasks — Task Generation

Break the implementation plan into ordered, executable tasks.

USAGE
  /smith-tasks

OUTPUT
  tasks.md with phases:
    Phase 1: Setup (project initialization)
    Phase 2: Foundational (blocking prerequisites)
    Phase 3+: User Stories in priority order
    Final: Polish & Cross-Cutting Concerns

NEXT STEPS
  /smith-analyze → /smith-implement
```

#### `analyze`

```
/smith-analyze — Consistency Analysis

Non-destructive cross-artifact analysis across spec.md, plan.md, and tasks.md.

USAGE
  /smith-analyze

CHECKS
  - Spec ↔ plan alignment
  - Plan ↔ tasks coverage
  - Constitution compliance
  - Duplicate or contradictory requirements
  - Missing test coverage

OUTPUT
  Analysis report with findings by severity (CRITICAL/HIGH/MEDIUM/LOW)

QUEUE INTEGRATION
  After analysis, offers: "Implement now or queue for later?"
  If queued, packages spec/plan/tasks into an autonomous queue entry.
```

#### `implement`

```
/smith-implement — Task Execution

Execute all tasks defined in tasks.md sequentially.

USAGE
  /smith-implement

BEHAVIOR
  Reads tasks.md, executes each task in order, marks completed with [X],
  runs tests after each task. Logs per-task status to vault.
```

#### `build`

```
/smith-build — Autonomous Build Pipeline

Full build from tasks through merged PR. Runs without user interaction.

USAGE
  /smith-build                     (normal — on a feature branch with spec/plan)
  /smith-build                     (recovery — detects state and resumes)

PHASES
  0. Context Discovery    Load spec, plan, questions, tasks
  1. Task Generation      Generate tasks.md if missing
  2. Implementation       Execute tasks phase-by-phase in subagents
  3. Testing              Unit tests + Playwright E2E (if frontend changed)
  4. Spec Updates         Update system specs in .specify/systems/ and specs/
  5. Commit & PR          Stage, commit, push, create PR, squash-merge
  6. Service Rebuild      Docker rebuild affected services, health check
  7. Release Notes        Generate release.md, commit to main

RECOVERY
  Detects current state and resumes from the right phase:
    No tasks.md → Phase 1
    Tasks partially done → Phase 2
    All done, uncommitted → Phase 5
    PR exists → Phase 5.3
    PR merged → Phase 6
```

#### `debug`

```
/smith-debug — Diagnostic Investigation

Read-only workflow that systematically gathers evidence, identifies root
causes, and produces a structured debug report. Does not modify code.
The report feeds into /smith-bugfix if a fix is needed.

USAGE
  /smith-debug <symptom description>
  /smith-debug                           (prompts for details interactively)

NATURAL LANGUAGE TRIGGERS
  "debug this", "help me debug...", "I'm getting this error...",
  "why is X failing", "something is broken", "can you investigate..."

PHASES
  1. Symptom Capture    Extract or ask for: error, trigger, conditions, frequency
  2. System Detection   Map symptom to .specify/systems/<system>/
  3. Automated Triage   Parallel sub-agents: infra-health, log-scan,
                        dependency-trace, spec-cross-reference
  4. Diagnosis          Synthesize findings, rank hypotheses by evidence
  5. Debug Report       Write to .specify/systems/<system>/debug/debug-YYYY-MM-DD-<slug>.md
  6. Decision Gate      User chooses: fix (/smith-bugfix), investigate deeper, or close

SUB-AGENTS (launched in parallel based on symptom type)
  infra-health         docker ps, health-check.sh, docker stats, port checks
  log-scan             docker logs for affected + upstream services
  dependency-trace     map request path, check each hop end-to-end
  spec-cross-ref       prior debug reports, recent git changes, GitHub issues

REPORT STORAGE
  .specify/systems/<primary-system>/debug/debug-YYYY-MM-DD-<slug>.md

CHAINS INTO
  /smith-bugfix (if user selects "Fix it" at the decision gate)
```

#### `bugfix`

```
/smith-bugfix — Autonomous Bugfix

Streamlined alternative to /smith-new for bugs and small changes.
Fully autonomous from invocation to merged PR.

USAGE
  /smith-bugfix <bug description>

NATURAL LANGUAGE TRIGGERS
  "fix this", "bugfix this", "quick fix for...", "patch this", "just fix..."

PIPELINE
  checkout main → create fix/<slug> branch → cross-reference specs →
  implement → rebuild Docker → test → update specs & changelog →
  commit → PR → squash-merge → return to main
```

#### `checklist`

```
/smith-checklist — Quality Checklist

Generate a checklist that validates spec quality, clarity, and completeness.
Functions as "unit tests for requirements writing."

USAGE
  /smith-checklist

NOT FOR
  Verifying implementation or testing code — only validates the spec itself.
```

#### `queue`

```
/smith-queue — Task Queue Management

Manage deferred work through a persistent task queue. Supports priority
ordering, dependency tracking, scheduled execution, and batch processing
with git worktree isolation.

ADD
  /smith-queue add "<description>"
  /smith-queue add "<description>" --priority high
  /smith-queue add "<description>" --depends-on <filename>

  Complexity flags (set during add or auto-detected):
    autonomous     Can run unattended (default for clear instructions)
    interactive    Needs user input, won't run in batch
    review         Runs unattended but stages for approval

LIST & STATUS
  /smith-queue list                    Show pending tasks by priority
  /smith-queue status                  Show all tasks grouped by lifecycle status

PROCESS (primary command for running tasks)
  /smith-queue process                 Interactive picker — choose a task
  /smith-queue process <filename>      Process a specific task
  /smith-queue process --next          Process highest-priority task only
  /smith-queue process --all           Process all autonomous tasks sequentially
  /smith-queue process --all --dry-run Show what would be processed
  /smith-queue process --all --limit N Process only first N tasks
  /smith-queue process --all --priority high  Only high+ priority
  /smith-queue process --all --model haiku    Override model
  /smith-queue process --all --all-projects   Across all projects
  /smith-queue process --all --abort   Stop after current task
  /smith-queue batch [flags]           Alias for process --all

SCHEDULE
  /smith-queue schedule <file> --at "<time>"
  /smith-queue schedule-batch --at "tonight"
  /smith-queue unschedule <filename>

EDIT
  /smith-queue edit <filename>         Modify task properties
  /smith-queue promote <filename>      autonomous → interactive
  /smith-queue demote <filename>       interactive → autonomous
  /smith-queue requeue <filename>      Reset failed → pending
  /smith-queue prioritize              Interactive priority reordering
  /smith-queue remove <filename>       Delete a task from the queue

HISTORY
  /smith-queue history                 List completed/failed tasks
  /smith-queue history --status failed Only show failed tasks
  /smith-queue history --since "last week"
  /smith-queue history clear --before "<date>"

SCHEDULER
  /smith-queue scheduler install       Install daily 2am scheduler (launchd)
  /smith-queue scheduler uninstall     Remove scheduler
  /smith-queue scheduler status        Check scheduler and show recent logs
  /smith-queue scheduler set-time HH:MM  Change daily run time
  /smith-queue scheduler logs          Tail scheduler log

STORAGE
  Queue:   .smith/vault/queue/
  History: .smith/vault/queue/history/
  Config:  .smith/config.json > security (allowlist for batch operations)
```

#### `vault`

```
/smith-vault — Vault Browser

Browse the Smith vault persistent memory system.

USAGE
  /smith-vault                         Dashboard summary
  /smith-vault sessions                List all session logs
  /smith-vault sessions <file>         Show a specific session log
  /smith-vault agents                  List sub-agent types and identifiers
  /smith-vault agents <type>           Show history for an agent type
  /smith-vault queue                   Show pending queue items
  /smith-vault status                  Health metrics + routing breakdown
  /smith-vault projects                List all registered projects

VAULT LOCATION
  .smith/vault/
    sessions/      Session logs (created by hooks)
    agents/        Sub-agent memory by type
    queue/         Task queue entries
    timesheets/    Generated timesheets
    reports/       Generated project reports
    specs/         Spec change tracking
```

#### `report`

```
/smith-report — Client Report Generation

Generate client-facing project reports from vault data.

USAGE
  /smith-report
  /smith-report --range week --type progress

DATE RANGE
  week, month, or YYYY-MM-DD:YYYY-MM-DD

REPORT TYPES
  progress     What was built, in progress, next steps
  decisions    Key decisions and their reasoning
  specs        Specs created, modified, completed
  full         All of the above plus audit summary and metrics

OUTPUT
  Saved to .smith/vault/reports/
  Also printed in chat
```

#### `constitution`

```
/smith-constitution — Project Constitution

Create or update the project constitution at .specify/memory/constitution.md.

USAGE
  /smith-constitution

BEHAVIOR
  Interactive principle input, fills placeholder tokens, propagates
  amendments across dependent templates and artifacts.
```

#### `taskstoissues`

```
/smith-taskstoissues — Tasks to GitHub Issues

Convert tasks.md entries into dependency-ordered GitHub Issues.

USAGE
  /smith-taskstoissues

Maps task dependencies to issue references so the backlog reflects
the same execution order as the task breakdown.
```

#### `migrate-specs`

```
/smith-migrate-specs — Spec Migration

One-time migration of existing flat spec folders in specs/ into the
system-based hierarchy at .specify/systems/<system>/features/.

USAGE
  /smith-migrate-specs
  /smith-migrate-specs --dry-run       Show proposed mappings without moving
  /smith-migrate-specs --all           Skip individual confirmations

BEHAVIOR
  Processes one feature at a time with user confirmation.
  Copies files (originals preserved in specs/ until manually removed).
  Adds frontmatter with primary_system, also_affects, status.
```

#### `bank`

```
/smith-bank — Idea Bank

Capture ideas mid-conversation and store them in the vault for later
processing. The bank is a section of the vault where ideas get deposited
for safekeeping until you're ready to withdraw them.

USAGE
  /smith-bank                            Bank the current conversation's idea
  /smith-bank list                       Show all banked ideas
  /smith-bank list --priority high       Filter by priority
  /smith-bank list --system system-13    Filter by affected system
  /smith-bank process BANK-001           Withdraw idea → /smith-new workflow
  /smith-bank edit BANK-001              Edit a banked idea
  /smith-bank remove BANK-001            Archive a banked idea (with confirmation)
  /smith-bank prioritize BANK-001 --priority high  Change priority

NATURAL LANGUAGE TRIGGERS
  "bank this idea"
  "bank this for later"
  "save this for later"
  "let's come back to this"
  "park this idea"
  "stash this thought"
  "deposit this"

STORAGE
  Bank:    .smith/vault/bank/
  Archive: .smith/vault/bank/archive/

BANK FILE FORMAT
  Each banked idea is a markdown file with YAML frontmatter containing:
  id, title, created, source_session, primary_system, also_affects,
  status (banked|in-progress|completed|queued), priority (critical|high|medium|low)

  Sections: Origin, Idea, Requirements (Draft), Systems Affected,
  Open Questions, Conversation Reference

PROCESS WORKFLOW
  /smith-bank process <id> reads the banked idea and feeds its description,
  requirements, systems, and open questions directly into /smith-new so the
  user doesn't have to re-explain anything. The bank entry status updates
  through the lifecycle: banked → in-progress → completed/queued.
```

#### `reflect`

```
/smith-reflect — Workflow Reflection & Learning

Analyze a completed workflow and extract lessons to the Ledger. Identifies
patterns, antipatterns, tool preferences, and edge cases from real execution
history so future workflows benefit from accumulated experience.

USAGE
  /smith-reflect                   Analyze the most recently completed workflow
  /smith-reflect --last N          Analyze last N completed workflows in batch
  /smith-reflect --failure         Learn specifically from recent failures

BEHAVIOR
  1. Reads the vault session log for the target workflow(s)
  2. Identifies what worked, what failed, and any non-obvious decisions
  3. Classifies findings into Ledger categories (patterns, antipatterns,
     tool-preferences, edge-cases, project-quirks)
  4. Writes entries to .smith/vault/ledger/ with confidence scores
  5. Skips entries that duplicate existing high-confidence Ledger content

CONFIDENCE LEVELS
  high     Observed 3+ times or confirmed by explicit user feedback
  medium   Observed 1-2 times, plausible but not yet confirmed
  low      Single observation, may be coincidental

LEDGER FILES WRITTEN
  .smith/vault/ledger/patterns.md
  .smith/vault/ledger/antipatterns.md
  .smith/vault/ledger/tool-preferences.md
  .smith/vault/ledger/edge-cases.md
  .smith/vault/ledger/project-quirks.md

OUTPUT
  Summary of new entries added, entries updated, and entries skipped (duplicate)
```

#### `ledger`

```
/smith-ledger — Ledger Browser & Management

Browse, search, and maintain the accumulated learning stored in the Ledger.
The Ledger is the persistent memory that grows through /smith-reflect and
is read by /smith-implement and /smith-report.

USAGE
  /smith-ledger                    Dashboard — overview stats per file
  /smith-ledger list               List all entries grouped by category
  /smith-ledger list --category <name>   Filter by category
  /smith-ledger list --confidence high   Filter by confidence level
  /smith-ledger search <term>      Full-text search across all Ledger files
  /smith-ledger prune              Interactive review of low-confidence entries
                                   for removal or promotion
  /smith-ledger reset              Archive current Ledger to
                                   .smith/vault/ledger/archive/<date>/ and
                                   start fresh (with confirmation prompt)

LEDGER LOCATION
  .smith/vault/ledger/
    patterns.md          Known-good approaches and successful patterns
    antipatterns.md      Known failure modes and what to avoid
    tool-preferences.md  Preferred tools, libraries, flags for this project
    edge-cases.md        Non-obvious edge cases encountered
    project-quirks.md    Project-specific gotchas (infra, env, conventions)
    meta.yaml            Entry counts, last-reflect timestamp, confidence summary
    archive/             Past Ledger snapshots from reset operations

PRUNE BEHAVIOR
  Lists all low-confidence entries with: title, category, first-observed date,
  observation count. For each entry, offers: keep / promote to medium / remove.
  Writes changes back to the relevant Ledger file.

RECONCILE
  /smith-ledger reconcile           Run Ledger self-maintenance pipeline
  /smith-ledger reconcile --dry-run Preview what would change without modifying files
  /smith-ledger reconcile --force   Bypass lock and minimum-interval checks
  /smith-ledger reconcile --status  Report whether reconciliation is currently needed

  PHASES (run in order):
    1. Merge          Deduplicate entries with >90% title similarity across files
    2. Prune          Auto-remove entries below confidence threshold (no prompt)
    3. Budget Enforce Trim each Ledger file to the configured token budget
    4. Meta Update    Recompute .meta.json counts, reset reinforcement counter
    5. Lock Release   Remove reconcile lock file (.smith/vault/ledger/.reconcile-lock)

  TRIGGERS (auto-reconcile via post-reflection check):
    - estimated_tokens > thresholds.total_tokens_max (default 30000)
    - context_budget_violations > thresholds.context_violations_threshold (default 3)
    - reinforcements_since_reconcile > thresholds.reinforcements_threshold (default 50)
    - Minimum interval between reconciles: thresholds.minimum_hours_between_reconciles (default 6h)

  SAFEGUARDS:
    - Lock file prevents concurrent reconcile runs
    - --dry-run always safe — reads only, no writes
    - Pruned entries are moved to .smith/vault/ledger/archive/ not deleted

  CONFIGURATION (in .smith/config.json under ledger.reconcile):
    auto_reconcile, reconcile_model, thresholds (total_tokens_max,
    context_violations_threshold, reinforcements_threshold,
    minimum_hours_between_reconciles)
```

#### `finish`

```
/smith-finish — Session Finish

End-of-session workflow that commits, pushes, merges, updates specs,
and verifies clean workspace state.

USAGE
  /smith-finish

STEPS
  1. Inventory current state (branch, changes, PRs)
  2. Commit (explicit file staging, conventional commits)
  3. Push to remote
  4. Update system specs and changelog
  5. Create PR and squash-merge
  6. Verify clean state on main
  7. Rebuild Docker services if needed
```

#### `help`

```
You're looking at it.

/smith-help             Full command overview
/smith-help <command>   Detailed help for a specific command
```

### Fallback — Unknown Command

If `$ARGUMENTS` doesn't match any known command:

1. Scan `.claude/commands/` for files matching `smith.*$ARGUMENTS*.md`
2. If found, read the file's frontmatter `description` field and first paragraph after frontmatter
3. Display that as fallback help
4. If no match at all: "Unknown command: `<argument>`. Run `/smith-help` for the full command list."
