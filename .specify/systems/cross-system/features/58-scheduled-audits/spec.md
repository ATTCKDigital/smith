---
feature: 58-scheduled-audits
primary_system: cross-system
also_affects: []
branch: 58-scheduled-audits
created: 2026-09-14
status: in-progress
answers_applied: 2026-09-14
---

# Scheduled Audit Subsets

## Overview

The scheduler (`scheduler/smith-scheduler.sh`) today does exactly one thing:
scan every registered project's `.smith/vault/queue/` and dispatch
autonomous queue tasks to `/smith-queue process <file>`. There is no
mechanism for a project to get a recurring, unattended `/smith-audit` pass
— today `/smith-audit` is purely interactive (it prompts for system
selection on empty args) and has no notion of "run this again in N days."
This feature adds a **second, narrow scheduler step** — cadence-gated,
per-project, direct-dispatch — that runs AFTER the existing queue step, plus
the `/smith-audit` additions that make an unattended invocation safe: a
`--scheduled` mode, subset selection, a workflow-gate marker (closing a real
gate gap `/smith-audit` has today), scoped report naming, a drift block, and
a rolling cross-run log.

It is informed by a pre-feature exploration
(`.smith/vault/explore/explore-2026-09-14-scheduled-audits.md`, status:
clear, 6 binding findings, no blocking conflicts) whose findings are binding
design constraints encoded throughout this spec (traced in this feature's
requirements checklist). All 6 findings were independently re-verified
against the current worktree state while writing this spec (exact line/file
citations below) — none required correction.

**Terminology used throughout this spec:**
- **Scheduled audit run** — one invocation of `/smith-audit --all
  --scheduled <subsets>` dispatched by the scheduler's new audits step for
  one project, covering every sub-audit category named in `<subsets>`
  across the project's `scheduled_audits.systems` scope (default `--all`,
  i.e. every system).
- **Subset** — one of the 11 named `/smith-audit` sub-audit categories
  (`requirements`, `codequality`, `performance`, `security`,
  `accessibility`, `ux`, `dependencies`, `infrastructure`, `workflow`,
  `seo`, `feature`), exactly as already enumerated in `skills/smith-audit/
  SKILL.md`'s "Sub-Audit Orchestration" section.
- **Headless-safe subset** — a subset that can run to completion inside a
  non-interactive `claude -p` invocation with no human present: the
  default five (`requirements`, `codequality`, `security`, `dependencies`,
  `workflow`), plus `infrastructure`, `performance`, and `accessibility` as
  configurable opt-ins, plus `ux`/`seo` as configurable opt-ins that use
  their existing MCP-first-with-silent-fallback contract (`skills/
  smith-audit/SKILL.md` items 6/10) rather than requiring an authenticated
  browser session. `feature` is NEVER headless-safe — it has a user
  interview phase (`skills/smith-audit/SKILL.md` item 11) — and is refused
  outright whenever `--scheduled` is present, regardless of configuration.
- **Cadence** — the `scheduled_audits.cadence_days` interval (default 7)
  that gates whether a project's scheduled audit is due, computed from the
  state file's `last_run.date`, never from wall-clock time-of-day.
- **Maintenance marker** — an `.smith/vault/active-workflows/*.yaml` file
  created via `scripts/create-active-workflow.sh --workflow maintenance`
  (the exact bootstrap pattern `skills/smith-update/SKILL.md`'s Phase 0
  already uses), satisfying `hooks/workflow-gate.sh`'s marker-presence
  check for the duration of one `/smith-audit` run, with a **synthetic**
  `--branch` value (`scheduled-audit-<TS>` or `audit-<TS>` — see FR-11) that
  names no real git ref, since `/smith-audit` never creates a worktree or
  branch.

## Problem Statement

1. **No unattended audit mechanism exists.** `/smith-audit` only runs
   interactively; there is no way for a project to get a recurring health
   check without a human invoking it each time.
2. **The queue pipeline is the wrong shape for this.** `/smith-queue
   process` is merge-oriented — worktree → `/smith-build` → Docker rebuild
   → tests → `gh pr create` → `gh pr merge` → history archival — and a task
   is "completed" only after a real merge. `/smith-audit` is read-only and
   produces a report, never a PR; routing it through `/smith-queue` would
   either force a no-op PR/merge around a report file or silently break the
   pipeline's own completion semantics (exploration finding 1).
3. **`/smith-audit` has a real workflow-gate hole.** `hooks/workflow-gate.sh`
   denies any file-modifying tool call without an active-workflow marker.
   `/smith-audit` writes report files (`specs/audits/*.md`, per-system
   `audits/*.md`) but has zero marker-handling logic anywhere in its
   `SKILL.md`, and `scripts/create-active-workflow.sh`'s `--workflow`
   allowlist (`smith-new|smith-bugfix|smith-debug|smith-build|smith-index|
   smith-update|smith-queue|maintenance`) has no `smith-audit` entry
   (exploration finding 3, independently confirmed by reading both files:
   `scripts/create-active-workflow.sh` lines 114-120, `skills/smith-audit/
   SKILL.md` in full — no Phase 0/marker section exists). Today this only
   "works" because an interactive `/smith-audit` invocation typically runs
   inside a session that already has an unrelated marker active from
   whatever workflow the user ran last, or fails closed with a gate denial
   when none exists — either way it's an unaudited accident, not a
   contract, and a non-interactive scheduled dispatch has no such
   accidental cover at all.
4. **No report continuity across unattended runs.** `/smith-audit`'s
   existing report format (`## Executive Summary` table, per-category
   Critical/Warning/Info/Score) is a point-in-time snapshot with no
   mechanism to compare against a prior run, and no single place records
   that scheduled runs happened at all — a project owner checking in after
   a week of nightly runs has no rolling history to scan.
5. **No config surface or mutable state for cadence.** Nothing in
   `.smith/config.json` or `templates/config.default.json` describes a
   per-project audit cadence, and no existing state file tracks "when did
   this project's scheduled audit last run."

## User Scenarios

### US-1 — Cadence due: scheduler dispatches a scheduled audit run
```gherkin
Given a registered project's `.smith/config.json` has
    `scheduled_audits.enabled: true` and `cadence_days: 7`
Given `.smith/vault/.scheduled-audits-state.json` has `last_run.date` 8 days
    in the past (or the file is absent)
When the scheduler's audits step runs, after the queue step has finished
    for all projects
Then the scheduler dispatches `"$CLAUDE_BIN" --model "$CLAUDE_MODEL"
    --permission-mode bypassPermissions -p "/smith-audit --all --scheduled
    <configured-subsets-comma-joined>"` from the project root, logging to
    the same `scheduler.log` the queue step already uses
And on successful completion the state file's `last_run` is overwritten
    with today's date, the dispatched subsets, the report path, and the
    run's severity totals
```

### US-2 — Cadence not due, or audits disabled: scheduler skips silently
```gherkin
Given a registered project's `scheduled_audits.enabled` is `false` (the
    MANDATORY shipped default), OR is `true` but `last_run.date` is within
    `cadence_days` of today
When the scheduler's audits step runs
Then the scheduler does not dispatch `/smith-audit` for that project, logs
    a one-line skip reason (disabled / not yet due), and continues to the
    next registered project
And no `.smith/vault/.scheduled-audits-state.json` write occurs for a
    skipped project
```

### US-3 — `--scheduled` invocation bootstraps and always clears its marker, including on failure
```gherkin
Given `/smith-audit --all --scheduled requirements,security` is invoked
    non-interactively with no pre-existing active-workflow marker
When `/smith-audit` begins
Then it creates a maintenance marker via `scripts/create-active-workflow.sh
    --workflow maintenance --branch scheduled-audit-<TS> --slug
    scheduled-audit-<TS> --worktree <project-root>` BEFORE any report file
    is written
Given a sub-audit subsequently crashes, or report generation fails
Then the marker is still cleared via `clear-active-workflow.sh
    scheduled-audit-<TS>` before `/smith-audit` returns control, and the
    failure is logged (to the scheduler's captured stdout/stderr and the
    vault session log when present) rather than left as a lingering marker
And a lingering marker is never relied upon as an acceptable outcome —
    leaving one active would silently disable the workflow-gate for every
    other file-modifying tool call in that project until the
    1-hour-minimum-grace-period janitor sweep (`hooks/
    active-workflow-janitor.sh`) eventually removes it
```

### US-4 — `feature` subset is refused in scheduled mode, never silently dropped
```gherkin
Given `/smith-audit --all --scheduled requirements,feature` is invoked
When `/smith-audit` parses the subset list
Then it refuses the invocation before creating a marker or running any
    sub-audit, logs a clear "feature sub-audit is not permitted in
    --scheduled mode (requires interactive interview)" failure line, and
    exits without writing a report
And this is a logged failure, not a crash — the scheduler's dispatch step
    (US-1) continues to the next registered project exactly as it does for
    any other dispatch failure
```

### US-5 — Drift block compares against the prior scheduled report
```gherkin
Given a prior scheduled report exists at the path recorded in
    `.smith/vault/.scheduled-audits-state.json`'s `last_run.report_path`,
    with an `## Executive Summary` table showing Security: 2 Critical / 3
    Warning / 5 Info
Given today's scheduled run's Security row is 0 Critical / 5 Warning / 5
    Info
When the new report is generated
Then a `## Drift Since Last Scheduled Audit` section is written
    immediately after the report's header block and before `## Executive
    Summary`, showing Security: Critical -2 (resolved), Warning +2 (new),
    Info +0, with the same per-category breakdown for every category
    present in both reports
And a category present in one report but not the other (a subset that
    wasn't run this time, or wasn't run last time) is disclosed as
    "not compared — subset not run in both audits", never silently omitted
    or shown as a misleading 0
```

### US-6 — First-ever scheduled run: no drift block, but the rolling log still gets an entry
```gherkin
Given `.smith/vault/.scheduled-audits-state.json` is absent, or present but
    fails to parse as JSON (corrupt)
When a scheduled run completes
Then this is treated as "never run before" — no `## Drift Since Last
    Scheduled Audit` section is written (there is nothing to compare
    against, and a corrupt file is never trusted as a comparison baseline)
And the state file is still written fresh with this run's results (FR-19),
    and `.smith/vault/reports/audits-log.md` still gets exactly one new
    rolling-log line for this run
```

## Functional Requirements

### Scheduler: audits step (`scheduler/smith-scheduler.sh`)

- **FR-1**: `smith-scheduler.sh` MUST gain a second, top-level loop over
  `$PROJECT_PATHS` — structurally separate from the existing queue-scan
  loop, not interleaved per-project with it — that runs to completion only
  AFTER the existing queue loop's `done <<< "$PROJECT_PATHS"` has finished
  for every project. This mirrors the existing script's own "thin
  launcher, one concern per step" shape and keeps the two steps
  independently testable (exploration finding 1: audits are a
  fundamentally different pipeline shape than queue tasks, so they get
  their own pass, not a shared iteration).
- **FR-2**: For each registered project, the audits step MUST read
  `.smith/config.json`'s `scheduled_audits.enabled` key. Absent config
  file, absent key, or `enabled: false` (the MANDATORY shipped default,
  FR-16) MUST skip that project silently apart from one logged skip line
  — no dispatch, no state-file write.
- **FR-3**: The due-or-not decision MUST be implemented as a small,
  independently testable function — `is_audit_due(now_date, last_run_date,
  cadence_days)` — taking three plain values (not reading files itself)
  and returning due/not-due. It is due when `last_run_date` is empty/absent
  (never run) OR `now_date - last_run_date` in days is `>= cadence_days`.
  This mirrors the task's explicit testability requirement and gives
  `tests/scheduler/` a pure function to exercise without a filesystem
  fixture for every case.
- **FR-4**: The audits step MUST read `last_run_date` from
  `.smith/vault/.scheduled-audits-state.json` (FR-18) for each project.
  Absent file, unreadable file, or a file that fails to parse as JSON MUST
  be treated identically to "never run" (empty `last_run_date` into FR-3),
  never as an error that skips or crashes the project's check (US-6).
- **FR-5**: When FR-3 returns "due", the audits step MUST dispatch:
  ```bash
  "$CLAUDE_BIN" --model "$CLAUDE_MODEL" --permission-mode bypassPermissions \
      -p "/smith-audit --all --scheduled <subsets>"
  ```
  run from the project root in a subshell exactly like the existing queue
  step's dispatch block (`smith-scheduler.sh` lines 215-221), reusing the
  SAME `$CLAUDE_BIN`/`$CLAUDE_MODEL` resolution the queue step already
  performed earlier in the same script run (`resolve_claude_bin`,
  `SMITH_SCHEDULER_MODEL`) — no second binary/model resolution pass.
  `<subsets>` is `scheduled_audits.subsets` (FR-16) comma-joined in
  configured order. stdout/stderr route into the same `$LOG_FILE`
  (`scheduler.log`) the queue step already writes to.
- **FR-6**: A dispatch failure (non-zero exit, or a report-path/severity
  read-back that doesn't confirm success — see FR-18's write-after-success
  contract) MUST be logged with the project name and reason, and MUST NOT
  raise, `exit`, or otherwise stop the audits step from continuing to the
  next registered project — identical in spirit to the queue step's own
  "log and continue" contract for a single task's failure.
- **FR-7**: `SMITH_AUDIT_DISPATCH_DRY_RUN=1` MUST log the planned dispatch
  (project, resolved subsets, computed due/not-due) without invoking
  `$CLAUDE_BIN`, mirroring `SMITH_SCHEDULER_DRY_RUN`'s existing contract
  for the queue step (`smith-scheduler.sh` lines 203-207) but as its own
  distinct variable — the two steps' dry-run modes are independently
  toggleable since a caller may want to dry-run only one of them while
  exercising the other for real.

### `/smith-audit`: `--scheduled` mode (`skills/smith-audit/SKILL.md`)

- **FR-8**: `/smith-audit` MUST recognize `--scheduled` in `$ARGUMENTS` as
  a mode flag (independent of, but always co-occurring in practice with,
  `--all` per FR-5's dispatch string). When present, `/smith-audit` MUST
  NOT fall through to the empty-args interactive system-selection prompt
  under any circumstance — if `--scheduled` is present without `--all` and
  without a resolvable system identifier, this is a refused invocation
  (logged failure, no marker created, no report written), not a prompt.
  This closes the one prompt branch a non-interactive `claude -p`
  invocation could otherwise hang on (exploration finding 2).
- **FR-9**: `/smith-audit` MUST parse a comma-separated subset list
  immediately following `--scheduled` (e.g. `--scheduled
  requirements,codequality,security,dependencies,workflow`), validating
  each token against the 11 named sub-audit categories (`skills/
  smith-audit/SKILL.md`'s existing "Sub-Audit Orchestration" list). An
  unrecognized token is a refused invocation (logged failure, no marker,
  no report) — never silently ignored or silently run as "all categories."
- **FR-10**: `feature` MUST be refused whenever it appears in the
  `--scheduled` subset list, regardless of configuration — validated
  BEFORE marker creation and BEFORE any sub-audit dispatch (US-4). This is
  unconditional: no `scheduled_audits` config field can permit it, since
  its interview phase has no non-interactive substitute.
- **FR-11**: `/smith-audit` MUST bootstrap a maintenance marker via
  `scripts/create-active-workflow.sh --workflow maintenance --branch
  <label> --slug <label> --worktree <project-root>` before writing any
  report file, for BOTH invocation modes — `--scheduled` (`<label> =
  scheduled-audit-<TS>`) AND plain interactive invocation (`<label> =
  audit-<TS>`) — see the scope decision below. `<TS>` uses the same
  `%Y-%m-%dT%H-%M-%SZ` UTC format `skills/smith-update/SKILL.md`'s Phase 0
  already uses. The marker's `--branch` value is a synthetic label, not a
  real git ref — `/smith-audit` never creates a worktree or branch, so
  `hooks/active-workflow-janitor.sh`'s stale-branch sweep will find no
  matching local/remote ref and would eventually sweep it as "gone from
  both" after its 1-hour grace period, but this feature does not rely on
  that fallback (FR-12).
- **FR-12**: The marker created in FR-11 MUST be cleared via
  `clear-active-workflow.sh <label>` before `/smith-audit` returns control
  on EVERY exit path — normal completion, a refused-subset validation
  failure that occurred AFTER marker creation (not applicable to FR-9/
  FR-10, which are validated before marker creation and thus need no
  clearing), a sub-audit crash, or a report/drift/log-write failure.
  Because `/smith-audit`'s orchestration spans multiple separately-invoked
  bash blocks and Claude tool calls (subagent dispatch, report writes) —
  not one OS process — a single shell `trap ... EXIT` cannot span the
  whole flow. This requirement is satisfied the same way `skills/
  smith-update/SKILL.md` already solves the identical problem: the marker
  clear-up is called out as a MANDATORY step at every documented exit
  point in `/smith-audit`'s own SKILL.md (mirroring smith-update's
  per-early-return "cleanup marker, exit cleanly" comments), reinforced by
  a narrow `trap ... EXIT` only around the single bash block that performs
  marker creation itself (guarding that one block's own internal failure
  mode), not the entire skill run.
- **FR-13**: `/smith-audit`'s report-path resolution MUST substitute the
  filename stem `<YYYY-MM-DD>-scheduled-<name>` for whatever stem the
  existing System Selection section would otherwise use
  (`<date>-full-spectrum` for `--all`, `<date>-full` for a single system)
  whenever `--scheduled` is present — same directory placement in both
  cases (`specs/audits/` for `--all`, `specs/system-XX-<name>/audits/` for
  a single system). `<name>` is the validated subset list (FR-9) joined
  with hyphens in configured order (e.g.
  `requirements-codequality-security-dependencies-workflow`).
- **FR-14**: When `--scheduled` is present and a prior scheduled report
  exists at `.smith/vault/.scheduled-audits-state.json`'s
  `last_run.report_path` (FR-18) and that file is still readable,
  `/smith-audit` MUST parse its `## Executive Summary` table (Category |
  Critical | Warning | Info | Score rows) and write a `## Drift Since Last
  Scheduled Audit` section into the new report, positioned immediately
  after the report's header block (Date/System/Auditor) and before `##
  Executive Summary`, with one row per category present in EITHER report
  showing the Critical/Warning/Info delta, each delta annotated "(new)"
  when it increased, "(resolved)" when it decreased, and a category
  missing from one side disclosed as "not compared — subset not run in
  both audits" (US-5) rather than treated as a 0-count.
- **FR-15**: When no prior scheduled report is resolvable (state file
  absent, corrupt, or its `report_path` no longer readable), the `##
  Drift Since Last Scheduled Audit` section MUST be omitted entirely —
  never rendered empty or with placeholder text (US-6).
- **FR-16**: On successful completion of a `--scheduled` run,
  `/smith-audit` MUST append exactly one line to `.smith/vault/reports/
  audits-log.md` (created fresh with no header if absent) in the format:
  `<UTC-timestamp> | scheduled | subsets=<comma-list> | report=<report
  path> | critical=<N> warning=<N> info=<N>` — sourced from the Overall
  row of the new report's own Executive Summary table. This file lives
  under `.smith/vault/reports/`, already in `hooks/workflow-gate.sh`'s
  `SAFE_VAULT_DIRS` exemption list (line 97) and already outside the
  `IGNORED` section of `skills/smith-index/templates/
  .gitignore-smith-additions` (verified: no matching line exists there),
  so no gate-marker requirement and no template change apply to this file
  specifically (exploration finding 4, re-verified against both files on
  disk).
- **FR-17**: When `--scheduled` is present, `/smith-audit` MUST read
  `scheduled_audits.skip_pdf` (default `true`, FR-20) from `.smith/
  config.json` and skip the existing "PDF Report Generation" section
  (puppeteer setup + `audit-pdf-generator.mjs` invocation) entirely when
  `true`. When `false`, PDF generation still runs best-effort exactly as
  it does today for an interactive run (a PDF-generation failure was
  already non-fatal to report delivery before this feature; that is
  unchanged).

### Scope decision — marker bootstrap covers interactive `/smith-audit` too

- **FR-18 (scope decision, not a delegated gate item)**: FR-11/FR-12's
  marker bootstrap-and-clear applies to EVERY `/smith-audit` invocation,
  not only `--scheduled` ones. The pre-feature exploration scoped the gate
  gap fix to the scheduled path only, flagging the interactive gap as a
  known, separately-fixable issue. Evaluated explicitly for this spec: the
  exact same `create-active-workflow.sh`/`clear-active-workflow.sh` code
  path already has to exist for `--scheduled` (FR-11/FR-12); gating it
  behind `--scheduled` specifically would leave interactive `/smith-audit`
  runs relying on the same unaudited "borrows whatever marker happens to
  already be active, or fails closed" behavior described in Problem
  Statement item 3, for zero additional implementation cost. Covering both
  is the decision recorded here — see `questions.md` for why this sits
  outside the 6 delegated gate items (it is this spec's own scope call,
  not an exploration-recommended-and-accepted answer).

### Configuration

- **FR-19**: A NEW top-level `scheduled_audits` key MUST be added to
  `.smith/config.json`:
  ```json
  "scheduled_audits": {
    "enabled": false,
    "cadence_days": 7,
    "subsets": ["requirements", "codequality", "security", "dependencies", "workflow"],
    "systems": "--all",
    "skip_pdf": true
  }
  ```
  `enabled: false` is MANDATORY as the shipped default — no project gets
  unattended, unattended-report-writing, unattended-marker-bootstrapping
  behavior without explicit opt-in (exploration finding 5). `subsets`
  ships with the five headless-safe defaults (exploration finding 2, this
  spec's Overview). `systems` defaults to `--all` (full-spectrum), a
  string sibling to `--all`/a system identifier exactly as `/smith-audit`'s
  own existing `$ARGUMENTS` grammar already accepts. `skip_pdf: true`
  matches this pipeline's precedent of not assuming `puppeteer`/`npm` are
  available or wanted on an unattended nightly run.
- **FR-20**: Config seeding MUST follow the exact three-site,
  non-destructive mechanism `quality`/`supply_chain`/`security_review`
  already established (feature 57's own FR-22, reused verbatim as a
  pattern): `templates/config.default.json` gains the `scheduled_audits`
  block (placed after `quality`, before `context_budget`, continuing the
  file's existing "each feature's key appended after the prior feature's"
  insertion order); `skills/smith/SKILL.md`'s init scaffold gains a new
  unlettered paragraph + python3 heredoc seeding `scheduled_audits` the
  same way it seeds `quality`; `/smith-update` gains a new `### 5.1f Seed
  \`scheduled_audits\` in \`.smith/config.json\`` step, immediately after
  the existing `5.1e` step and before `5.2`, using the identical
  read-modify-write idiom (key present → no-op; file exists, key absent →
  merge; file absent → leave absent).

### State file

- **FR-21**: `.smith/vault/.scheduled-audits-state.json` MUST be written
  ONLY after a scheduled run's report (and, when applicable, drift block)
  has been successfully generated and the rolling log line (FR-16)
  appended — write-after-success, never write-before-dispatch or
  write-on-failure. Shape:
  ```json
  {
    "last_run": {
      "date": "2026-09-14",
      "timestamp": "2026-09-14T02:00:03Z",
      "subsets": ["requirements", "codequality", "security", "dependencies", "workflow"],
      "report_path": "specs/audits/2026-09-14-scheduled-requirements-codequality-security-dependencies-workflow.md",
      "severity_totals": {"critical": 1, "warning": 12, "info": 30}
    }
  }
  ```
  `date` (not `timestamp`) is the field FR-3's `is_audit_due` compares
  against — cadence is calendar-day-granular, never time-of-day-granular,
  so a run that starts just after midnight doesn't get a spuriously short
  next interval.
- **FR-22**: An absent file, an unreadable file, or a file that fails to
  parse as JSON MUST all be treated identically as "never run" by both
  FR-4 (scheduler's due check) and FR-14/FR-15 (`/smith-audit`'s drift
  lookup) — never as an error that blocks the cadence check or the report
  write (US-6).
- **FR-23**: `.smith/vault/.scheduled-audits-state.json` MUST be added to
  the `IGNORED` section of `skills/smith-index/templates/
  .gitignore-smith-additions` — exactly ONE new line, grouped with the
  file's existing dotfile-shaped, per-machine runtime state entries
  (`.smith/vault/.current-session`, `.smith/vault/.active-workflow`), not
  the file's `COMMITTED` (shared) category. This is mutable, per-machine
  cadence state, not a team-shareable artifact (exploration finding 5).

### Documentation

- **FR-24**: `docs/scheduler.md` MUST gain a new section (sibling to the
  existing "How Task Processing Works" section) describing the audits
  step: what it scans (`scheduled_audits.enabled` + cadence), what it
  dispatches (the exact `/smith-audit --all --scheduled <subsets>`
  invocation string), that it runs strictly after the queue step, its
  `SMITH_AUDIT_DISPATCH_DRY_RUN` dry-run variable, and a short "Linux: not
  automated, run manually" note pointing at the same manual-cron pattern
  already documented for the queue step (Out of Scope item 1 — doc note
  only, no new automation).
- **FR-25**: `docs/security-model.md` MUST gain a new paragraph under its
  existing "Scheduler Security" section describing the audits step's
  security posture (read-only sub-audits, `enabled: false` default,
  git-worktree-free — it never creates or checks out a branch, unlike the
  queue step's per-task worktree isolation). In the SAME edit, the
  existing "Scheduler Security" bullet reading `` `"mode": "autonomous"` ``
  MUST be corrected to `` `complexity: autonomous` `` — the field the code
  actually reads (`scheduler/smith-scheduler.sh` line 125/128 and `skills/
  smith-queue/SKILL.md`'s "Scheduler invocation contract" table both agree
  on `complexity`; `docs/scheduler.md` line 64 already says `complexity:
  autonomous` correctly — only `docs/security-model.md` line 153 has the
  stale field name). Cited here as an in-passing correction per
  exploration finding 6, re-verified directly against `docs/
  security-model.md` on disk during this spec's own drafting (not taken
  on the exploration's word alone).
- **FR-26**: `CHANGELOG.md` MUST gain a new `[Unreleased]` → `### Added`
  entry, written last after every other file's changes are final,
  describing the scheduler's new audits step, `/smith-audit`'s
  `--scheduled` mode and workflow-gate marker fix (for both invocation
  modes per FR-18), the `scheduled_audits` config key, the drift block,
  and the rolling `audits-log.md` log.

## Non-Functional Requirements

- **NFR-1**: No check or step this feature adds introduces any new
  block/terminate path anywhere in the pipeline it touches. A scheduled
  audit run's findings are exactly as advisory as an interactive audit's
  findings already are — `/smith-audit` has never had a pass/fail gate,
  and this feature does not add one. The ONLY things that can make a
  scheduled invocation fail outright are the pre-marker validation
  refusals (FR-8/FR-9/FR-10), which are argument-shape errors, not
  finding-severity gates.
- **NFR-2**: Every new shell snippet in `scheduler/smith-scheduler.sh` and
  every shell/python snippet added to `skills/smith-audit/SKILL.md`,
  `skills/smith/SKILL.md`, and `skills/smith-update/SKILL.md` for this
  feature MUST run correctly under both `bash` and `zsh`; every Python
  snippet uses `python3`, matching this repo's existing shell-content
  convention and Rule 6 of `~/.claude/CLAUDE.md`.
- **NFR-3**: The audits step MUST NOT mutate any `/smith-queue` queue file
  or `history/` entry — it is a fully independent step reading only
  `.smith/config.json` and `.smith/vault/.scheduled-audits-state.json`,
  matching FR-1's "structurally separate, not interleaved" requirement.
- **NFR-4**: `/smith-audit`'s marker bootstrap (FR-11/FR-12) MUST NOT
  create a git worktree, branch, or any filesystem artifact beyond the
  marker YAML file itself — `/smith-audit` remains read-only with respect
  to project source code and git state, exactly as its existing "Key
  Rules" section already requires ("Never modify code during an audit").
- **NFR-5**: All of this feature's scheduled-mode logic runs without any
  user interaction of any kind — no prompts, confirmations, or pauses —
  consistent with FR-8's prompt-avoidance requirement and the scheduler's
  own existing non-interactive contract for the queue step.

## Out of Scope

- **OOS-1 — Linux cron automation.** The scheduler's audits step is
  reachable manually the same way the queue step already is
  (`bash ~/.smith/scheduler/smith-scheduler.sh`, or directly via cron on
  Linux); this feature adds a documentation note (FR-24) pointing at the
  existing manual-cron pattern, not a new Linux daemon or installer path.
- **OOS-2 — `/smith-queue` pipeline changes.** No file under `skills/
  smith-queue/` or `smith-scheduler.sh`'s existing queue-scan loop is
  modified by this feature (FR-1's structural separation is the guarantee
  here).
- **OOS-3 — UX/SEO/feature default-subset changes.** `ux` and `seo` stay
  configurable opt-ins (never added to the shipped default five); `feature`
  is never permitted in `--scheduled` mode under any configuration
  (FR-10). This feature does not change any sub-audit's own internal
  behavior, scoring, or report content — only which subsets get selected
  for a scheduled run and how the resulting report is named/diffed/logged.
- **OOS-4 — Notification infrastructure.** No email, Slack, webhook, or
  push-notification mechanism is added for scheduled-audit completion or
  findings. The rolling log (FR-16) and the report file itself are the
  only surfacing mechanisms this feature ships; a project owner checks
  them the same way they'd check `scheduler.log` today.
- **NOT out of scope — interactive `/smith-audit` marker gap.** Unlike the
  exploration's own initial framing, this spec does NOT defer the
  interactive-invocation marker gap — FR-18 explicitly covers both modes
  with the same code path. Documented here so a reader comparing this spec
  against the exploration report understands the scope was deliberately
  widened, not narrowed by omission.

## Assumptions

- **A-1**: The pre-feature exploration
  (`.smith/vault/explore/explore-2026-09-14-scheduled-audits.md`) found no
  blocking conflicts; its 6 findings are design constraints resolved by
  encoding them into this spec, confirmed by this feature's requirements
  checklist. All 6 were independently re-verified against the current
  worktree's actual files while drafting this spec (spec body cites exact
  file/line evidence per finding) rather than trusted on the exploration
  report's word alone; none required correction.
- **A-2**: `scripts/create-active-workflow.sh`'s existing `maintenance`
  workflow-type catch-all (line 115) is reused unchanged for `/smith-audit`'s
  marker — no new entry is added to that script's `--workflow` allowlist,
  since `maintenance` already exists precisely for commands like this that
  need a marker but aren't one of the four named top-level workflow skills
  (exploration finding 3).
- **A-3 — RESOLVED at questions gate (delegation).** The feature
  description named six gate decisions the exploration pass
  evidence-backed with a recommendation each. Per this workflow's standing
  delegation, the user accepted every recommendation as-is
  (`questions.md`, generated 2026-09-14, status ANSWERED). No FR above
  contradicts these outcomes; see `questions.md` for the full options/
  recommendation/outcome trail for each of the 6 items. FR-18 (marker
  bootstrap covering interactive invocations too) is a SEPARATE,
  spec-level scope decision this task explicitly asked to be evaluated and
  made directly — it is not one of the 6 delegated items and is recorded
  as its own decision above, not folded into the delegation trail.
- **A-4**: `.smith/vault/reports/` requires no gitignore-template or
  workflow-gate change for `audits-log.md` — it is already in `hooks/
  workflow-gate.sh`'s `SAFE_VAULT_DIRS` (line 97) and already absent from
  the `IGNORED` section of the managed `.gitignore-smith-additions`
  template, both re-verified directly against the files on disk rather
  than assumed from the exploration report (FR-16).
  `.scheduled-audits-state.json` is the one artifact this feature adds
  that DOES need a new gitignore-template line (FR-23), since it is
  per-machine mutable state, not a shared report.
  This distinction — some new files need a template change, some don't —
  is exactly the discrimination exploration finding 5 already drew, and is
  restated here because it is easy to conflate the two paths.

## Success Criteria

- **SC-1**: With `scheduled_audits.enabled: true` and a due cadence, the
  scheduler's audits step dispatches the exact `/smith-audit --all
  --scheduled <subsets>` invocation string via the same
  `$CLAUDE_BIN`/`$CLAUDE_MODEL`/`bypassPermissions` contract the queue step
  already uses, strictly after the queue loop has finished for every
  project (FR-1/FR-5).
- **SC-2**: With `scheduled_audits.enabled: false` (the shipped default),
  or a cadence not yet due, the scheduler's audits step performs zero
  dispatches and zero state-file writes for that project, logging exactly
  one skip line (FR-2/FR-3/US-2).
- **SC-3**: A `/smith-audit --all --scheduled feature` invocation (or any
  subset list containing `feature`) is refused before any marker is
  created or any sub-audit runs, with a clear logged reason (FR-10/US-4).
- **SC-4**: A `--scheduled` invocation always ends with its maintenance
  marker cleared — verified across three paths: normal completion, a
  mid-run sub-audit crash, and a report-write failure — with the marker
  absent from `.smith/vault/active-workflows/` in all three cases
  (FR-11/FR-12/US-3).
- **SC-5**: Given a prior scheduled report recorded in the state file, a
  new scheduled report's `## Drift Since Last Scheduled Audit` section
  correctly shows per-category Critical/Warning/Info deltas annotated
  (new)/(resolved), with a category absent from either side disclosed as
  "not compared" rather than a false 0 (FR-14/US-5).
- **SC-6**: With the state file absent or corrupt, a scheduled run
  produces no drift section, still writes a fresh state file on success,
  and still appends exactly one rolling-log line to `audits-log.md`
  (FR-15/FR-21/FR-22/US-6).
- **SC-7**: An interactive (non-`--scheduled`) `/smith-audit` invocation
  also creates and clears an `audit-<TS>` maintenance marker across its
  run — verified this closes the pre-existing gate gap for BOTH invocation
  modes, not scheduled-only (FR-18).
