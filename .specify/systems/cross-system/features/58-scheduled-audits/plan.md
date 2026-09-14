---
feature: 58-scheduled-audits
primary_system: cross-system
branch: 58-scheduled-audits
status: planned
---

# Implementation Plan: Scheduled Audit Subsets

## Technical Context

- **Repo**: Smith skills distribution (this repo). No application runtime
  — deliverables are one bash script (`scheduler/smith-scheduler.sh`),
  markdown skill prose (`skills/smith-audit/SKILL.md`, plus config-seeding
  steps in `skills/smith/SKILL.md` and `skills/smith-update/SKILL.md`), one
  config key (`templates/config.default.json`), one gitignore-template
  line, three doc files, a new test directory, and a `CHANGELOG.md` entry.
- **Features 54-57 are already shipped and merged in this worktree** —
  `security_review`/`supply_chain`/`quality` all exist in `templates/
  config.default.json` exactly as their own plans describe, and the
  three-site non-destructive config-seeding idiom (`templates/
  config.default.json` + `skills/smith/SKILL.md` init scaffold + `skills/
  smith-update/SKILL.md` lettered `§5.1x` step) is real, on-disk, and
  reused verbatim here for `scheduled_audits` (new `§5.1f`, immediately
  after the existing `§5.1e`).
- **No `constitution.md` exists in this repo** — matching every prior
  feature's plan.md in this worktree.
- **This feature spans two independently-versioned surfaces that must
  ship together**: the scheduler script (which DISPATCHES a
  `--scheduled` invocation) and `/smith-audit`'s SKILL.md (which
  INTERPRETS one). Neither is useful alone — a scheduler dispatch with
  no `--scheduled` handling in `/smith-audit` either falls through to the
  interactive prompt (hangs a non-interactive `claude -p` call
  indefinitely) or, worse, runs `feature`'s interview phase against no
  human. Phased ordering below sequences `/smith-audit`'s changes BEFORE
  the scheduler's dispatch code for exactly this reason.
- **Endpoint — RESOLVED**: the questions gate closed 2026-09-14
  (`questions.md`, status ANSWERED) with all six named gate decisions
  accepted exactly as recommended, plus one additional non-gate scope
  decision (FR-18: marker bootstrap covers interactive invocations too)
  made directly per this feature's task framing. `spec.md`'s own
  Assumptions (A-3) record the gate outcomes; this plan's content is
  written as concrete and unconditional.

## Constitution Gates

**N/A — no `constitution.md` or `.specify/memory/constitution.md` exists in
this repo**, so there are no constitution-derived gates to check. File-size
discipline is enforced via this plan's own File Size Policy section
instead, the same substitution every prior feature in this worktree
already used.

## Architecture Summary

Two independent surfaces, each gaining new sections, no existing section
removed or renumbered:

**1. `scheduler/smith-scheduler.sh` — new audits step** (FR-1..FR-7). A
second top-level `while IFS= read -r vault_path; do ... done <<<
"$PROJECT_PATHS"` loop, inserted after the existing queue loop's closing
`done` and before the final `log "=== Daily scheduler run complete..."`
line. Per project: read `scheduled_audits.enabled` from `.smith/
config.json` (skip if absent/false); read `.smith/vault/.scheduled-audits-
state.json`'s `last_run.date` (absent/corrupt → treat as never-run); call
`is_audit_due()` (new, extracted, pure function); if due and not
`SMITH_AUDIT_DISPATCH_DRY_RUN=1`, dispatch `"$CLAUDE_BIN" --model
"$CLAUDE_MODEL" --permission-mode bypassPermissions -p "/smith-audit --all
--scheduled <subsets>"` from the project root into the same
`scheduler.log`, log the outcome, continue regardless of exit code.

**2. `skills/smith-audit/SKILL.md` — `--scheduled` mode** (FR-8..FR-18).
A new "Phase 0: Scheduled Mode & Marker Bootstrap" section, inserted before
the existing "System Selection" section: parses `--scheduled` + a
comma-separated subset list, refuses `feature` and any unrecognized token
before doing anything else, refuses a `--scheduled` invocation that would
otherwise fall through to the interactive prompt, then (for BOTH
`--scheduled` and plain interactive invocations, per FR-18) bootstraps a
`maintenance` marker via `create-active-workflow.sh` with a synthetic
branch label, with clearing instructions repeated at every documented exit
point (mirroring `skills/smith-update/SKILL.md`'s own solution to the
identical multi-step-prose cleanup problem). "Report Generation" gains
scheduled-mode filename substitution, a conditional Drift block, a
conditional rolling-log append, and a `skip_pdf`-gated PDF step.

Plus the `scheduled_audits` config key (FR-19) and its three-site
non-destructive seeding (FR-20): `templates/config.default.json`, `skills/
smith/SKILL.md`'s init scaffold, and a new `skills/smith-update/SKILL.md`
§5.1f. Plus one new `skills/smith-index/templates/
.gitignore-smith-additions` line (FR-23). Plus three documentation files
(FR-24/FR-25/FR-26).

## Reuse-before-create (exact components reused, not reinvented)

- **The existing queue-dispatch block's shape**
  (`scheduler/smith-scheduler.sh` lines 215-221: subshell `cd` +
  `"$CLAUDE_BIN" --model ... --permission-mode bypassPermissions -p "..."`
  routed into `$LOG_FILE`) — reused verbatim in structure for the audits
  step's own dispatch (FR-5), including reusing the SAME already-resolved
  `$CLAUDE_BIN`/`$CLAUDE_MODEL` values from earlier in the same script run,
  not a second resolution pass.
- **`resolve_claude_bin()`** (`smith-scheduler.sh` lines 57-76) — called
  exactly once per script run, before either loop; the audits step does
  not duplicate this function or call it a second time.
- **The `SMITH_SCHEDULER_DRY_RUN` contract** (`smith-scheduler.sh` lines
  203-207) — reused in shape (log-without-dispatching) for
  `SMITH_AUDIT_DISPATCH_DRY_RUN`, as a distinct variable so either step's
  dry-run mode toggles independently.
- **`scripts/create-active-workflow.sh`'s `maintenance` workflow type**
  (line 115, already in the allowlist) — reused unchanged; no new enum
  value added to that script (`questions.md` Q3).
- **`skills/smith-update/SKILL.md`'s Phase 0 marker-bootstrap pattern**
  (lines 49-75: create via the shipped helper before any file write, clear
  via `clear-active-workflow.sh` at the end) AND its per-early-return
  "cleanup marker, exit cleanly" comment pattern (Phase 1/Phase 2, e.g.
  lines 90-91, 123-125) — reused verbatim as the mechanism for `/smith-
  audit`'s own marker lifecycle (FR-11/FR-12), since `/smith-audit`'s
  SKILL.md has the exact same multi-bash-block, no-single-OS-process
  structure that makes a single `trap ... EXIT` insufficient across the
  whole flow.
- **The three-site config-seeding idiom** (`templates/config.default.json`
  + `skills/smith/SKILL.md` init scaffold + `skills/smith-update/
  SKILL.md` lettered `§5.1x` step, most recently `§5.1e` for `quality`,
  feature 57's own FR-22) — reused verbatim, retargeted at
  `scheduled_audits` as `§5.1f` (FR-20).
- **The sentinel-bounded `.gitignore-smith-additions` template merge**
  (already-shipped `/smith` init + `/smith-update` §5.5 idempotent
  replace-or-append logic) — no new merge mechanism; FR-23 only adds a
  line to the existing template file's `IGNORED` section, which the
  existing merge logic already picks up unchanged.
- **`skills/smith-audit/SKILL.md`'s existing System Selection branching**
  (`--all` vs. a system identifier vs. empty-args prompt) — reused,
  extended (not replaced) by FR-13's filename-stem substitution, which
  only changes WHICH stem is used, not the directory-placement branching
  itself.
- **The existing `## Executive Summary` table shape** (Category | Critical
  | Warning | Info | Score rows, `smith-audit/SKILL.md`'s "Report
  Generation" section) — parsed as-is for the Drift block (FR-14); no
  change to how that table itself is produced or scored.

## File Size Policy

No new source file crosses the 300-line soft ceiling this repo's prior
features already apply absent a hard constitution gate:

- `scheduler/smith-scheduler.sh` net new prose (second loop + `
  is_audit_due()` + dispatch block + dry-run branch) targets roughly
  70-100 lines, appended after the existing script's final `done` —
  smaller than the file's own existing queue loop (~150 lines), since the
  audits step has no dependency graph, no priority sort, and no
  history-directory verification to replicate.
- `skills/smith-audit/SKILL.md`'s net new prose (Phase 0 section +
  Report Generation additions) targets roughly 110-150 lines — comparable
  to feature 57's own ~90-130-line estimate for `smith-build`'s
  section-level additions, appropriate given this feature adds one new
  named phase plus targeted edits to one existing section, not a
  ground-up rewrite.
- The new test file(s) under `tests/scheduler/` (Test Strategy below)
  target ≤150 lines each, sized against the smallest existing `tests/
  skills/*.sh` harness rather than the largest.

## Contracts

### `scheduled_audits` config schema (`.smith/config.json`, `templates/config.default.json`)

```json
"scheduled_audits": {
  "enabled": false,
  "cadence_days": 7,
  "subsets": ["requirements", "codequality", "security", "dependencies", "workflow"],
  "systems": "--all",
  "skip_pdf": true
}
```
- `enabled`: boolean, MANDATORY default `false` (FR-19, `questions.md` Q5).
- `cadence_days`: integer, default `7`. Compared calendar-day-granular
  against the state file's `last_run.date` (FR-3, FR-21).
- `subsets`: array of sub-audit category strings, default the five
  headless-safe categories. Validated against the 11-category vocabulary
  at dispatch-read time (scheduler) and again at parse time
  (`/smith-audit`, FR-9) — double-validated deliberately, since a stale
  config value written before a future category rename should fail loudly
  at the `/smith-audit` end even if the scheduler's own copy is untouched.
- `systems`: string, default `"--all"`. Passed straight through as
  `/smith-audit`'s own system-selection argument — `"--all"` or a system
  identifier, exactly the grammar `/smith-audit`'s existing "System
  Selection" section already accepts.
- `skip_pdf`: boolean, default `true` (FR-17).

### State file schema (`.smith/vault/.scheduled-audits-state.json`)

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
Write-after-success only (FR-21). Absent, unreadable, or malformed JSON →
treated identically as "never run" by both the scheduler's due-check
(FR-4) and `/smith-audit`'s drift lookup (FR-14/FR-15) — never an error
(FR-22).

### `is_audit_due()` contract (`scheduler/smith-scheduler.sh`, new function)

```bash
# is_audit_due <now_date YYYY-MM-DD> <last_run_date-or-empty> <cadence_days>
# Prints "1" (due) or "0" (not due) to stdout. Pure function — no file I/O,
# no globals read/written — so tests/scheduler/ can exercise every branch
# without a filesystem fixture.
is_audit_due() {
    local now="$1" last="$2" cadence="$3"
    [ -z "$last" ] && { echo 1; return; }   # never run → due
    local now_epoch last_epoch
    now_epoch=$(date -j -f "%Y-%m-%d" "$now" +%s 2>/dev/null || date -d "$now" +%s)
    last_epoch=$(date -j -f "%Y-%m-%d" "$last" +%s 2>/dev/null || date -d "$last" +%s)
    local days=$(( (now_epoch - last_epoch) / 86400 ))
    [ "$days" -ge "$cadence" ] && echo 1 || echo 0
}
```
The `date -j -f ... || date -d ...` fallback pair matches this repo's
existing cross-platform (macOS BSD `date` / Linux GNU `date`) convention
already used elsewhere in the hooks/scripts layer (e.g. `mtime_of()` in
`hooks/active-workflow-janitor.sh`, same `stat -f ... || stat -c ...`
fallback shape) — reused, not invented fresh.

### `--scheduled` dispatch grammar (`skills/smith-audit/SKILL.md`)

```
/smith-audit --all --scheduled requirements,codequality,security,dependencies,workflow
```
- `--all` (or a system identifier) MUST be present; `--scheduled` alone
  falling through to the interactive prompt is a refused invocation
  (FR-8), never a hang.
- `--scheduled` is followed by a bare comma-separated subset list (no
  further flag). Each token validated against the 11-category vocabulary;
  `feature` and any unrecognized token are unconditionally refused before
  marker creation (FR-9/FR-10).

### Report filename substitution (`skills/smith-audit/SKILL.md`, "Report Generation")

| Systems scope | Interactive stem (today) | `--scheduled` stem (this feature) |
|---|---|---|
| `--all` | `<date>-full-spectrum` | `<date>-scheduled-<name>` |
| single system | `<date>-full` | `<date>-scheduled-<name>` |

`<name>` = validated subset list, hyphen-joined, configured order (FR-13).
Directory placement is UNCHANGED in both branches (`specs/audits/` for
`--all`, `specs/system-XX-<name>/audits/` for a single system) — only the
filename stem changes.

### Drift block format (`## Drift Since Last Scheduled Audit`, FR-14/FR-15)

```
## Drift Since Last Scheduled Audit
**Previous scheduled report:** specs/audits/2026-09-07-scheduled-requirements-codequality-security-dependencies-workflow.md (2026-09-07)

| Category | Critical Δ | Warning Δ | Info Δ |
|---|---|---|---|
| Requirements | +0 | +2 (new) | -1 (resolved) |
| Security | -2 (resolved) | +2 (new) | +0 |
| Accessibility | not compared — subset not run in both audits | | |
| **Overall** | -2 (resolved) | +4 (new) | -1 (resolved) |
```
Positioned immediately after the report's header block (Date/System/
Auditor) and before `## Executive Summary`. Omitted entirely (not rendered
empty) when no prior scheduled report resolves (FR-15).

### Rolling log line format (`.smith/vault/reports/audits-log.md`, FR-16)

```
2026-09-14T02:00:03Z | scheduled | subsets=requirements,codequality,security,dependencies,workflow | report=specs/audits/2026-09-14-scheduled-requirements-codequality-security-dependencies-workflow.md | critical=1 warning=12 info=30
```
One line per successful scheduled run, appended (never rewritten). File
created fresh with no header if absent.

### Dispatch invocation string (`scheduler/smith-scheduler.sh` → `/smith-audit`)

```bash
(
  cd "$PROJECT_DIR" && \
  "$CLAUDE_BIN" \
      --model "$CLAUDE_MODEL" \
      --permission-mode bypassPermissions \
      -p "/smith-audit --all --scheduled $SUBSETS_JOINED"
) >> "$LOG_FILE" 2>&1
```
Identical contract shape to the existing queue-step dispatch block
(`smith-scheduler.sh` lines 215-221) — same subshell-`cd`, same
`$CLAUDE_BIN`/`$CLAUDE_MODEL`/`bypassPermissions`, same `$LOG_FILE`
redirection.

### Marker bootstrap invocation (`skills/smith-audit/SKILL.md`, FR-11)

```bash
TS=$(date -u +"%Y-%m-%dT%H-%M-%SZ")
LABEL="scheduled-audit-${TS}"   # or "audit-${TS}" for an interactive run (FR-18)
PROJECT_DIR=$(pwd)
if [ -d "$PROJECT_DIR/.smith" ]; then
    ~/.smith/scripts/create-active-workflow.sh \
      --branch "$LABEL" --workflow maintenance --slug "$LABEL" \
      --worktree "$PROJECT_DIR"
    MARKER_PATH="$PROJECT_DIR/.smith/vault/active-workflows/${LABEL}.yaml"
fi
```
Cleared via `"$PROJECT_DIR/.specify/scripts/bash/clear-active-workflow.sh"
"$LABEL"` at every documented exit point — normal completion, each
pre-marker validation refusal needs no clearing (marker doesn't exist
yet), but every POST-marker-creation failure path does.

### No-terminate contract

Identical in spirit to features 56/57's own: no finding this feature's
scheduled mode surfaces, from any sub-audit at any severity, blocks,
delays, or terminates anything — `/smith-audit` has never had a pass/fail
gate and this feature does not add one (NFR-1). The only failures are the
pre-marker argument-validation refusals (FR-8/FR-9/FR-10), which are
argument-shape errors caught before any work begins, not findings-based
gates.

## Exact file-by-file change list

### MODIFIED

| File | Change |
|---|---|
| `scheduler/smith-scheduler.sh` | **(1)** NEW `is_audit_due()` function, defined alongside the existing `resolve_claude_bin()` (before either loop). **(2)** NEW second top-level loop over `$PROJECT_PATHS`, after the existing queue loop's closing `done`, before the final summary `log` line — reads `scheduled_audits.enabled`/`cadence_days`/`subsets` via `python3 -c "import json..."` (matching this repo's existing convention for structured-field reads elsewhere in the hooks/scripts layer), reads `.scheduled-audits-state.json`'s `last_run.date`, calls `is_audit_due()`, dispatches or skips, honors `SMITH_AUDIT_DISPATCH_DRY_RUN`. **(3)** Final summary log line extended to include an audits-step tally (dispatched/failed/skipped), mirroring the existing `TOTAL_DISPATCHED`/`TOTAL_FAILED`/`TOTAL_SKIPPED` counters pattern with a second, distinct counter set. |
| `skills/smith-audit/SKILL.md` | **(1)** NEW "Phase 0: Scheduled Mode & Marker Bootstrap" section, inserted before the existing "System Selection" section — argument parsing (`--scheduled` + subset list), refusal checks (FR-8/FR-9/FR-10), marker bootstrap for BOTH invocation modes (FR-11/FR-18), with clearing instructions repeated at each documented exit point (FR-12). **(2)** "System Selection" section gains one cross-reference note: a `--scheduled` invocation without `--all`/a system identifier is refused by Phase 0, never reaches the empty-args prompt branch. **(3)** "Report Generation" section gains: filename-stem substitution for `--scheduled` (FR-13), a conditional Drift block (FR-14/FR-15), a conditional `audits-log.md` append (FR-16), and a `skip_pdf`-gated PDF Report Generation step (FR-17). **(4)** "Key Rules" section gains one new bullet stating the marker-clear-on-every-exit-path contract, mirroring `skills/smith-update/SKILL.md`'s own "Active-workflow marker must be created BEFORE any file write" Key Rule. |
| `templates/config.default.json` | New top-level `scheduled_audits` key (§Contracts) inserted after `quality`'s closing `}` and before `context_budget`, matching the file's existing insertion-order convention. |
| `skills/smith/SKILL.md` | New unlettered paragraph + python3 heredoc, mirroring the existing `quality` seed block exactly, retargeted at `scheduled_audits`, placed immediately after that block's closing `fi`. |
| `skills/smith-update/SKILL.md` | New `### 5.1f Seed \`scheduled_audits\` in \`.smith/config.json\`` inserted immediately after the existing `### 5.1e` step and before `### 5.2`, same three-line decision rule and python3 heredoc shape as `5.1e`, retargeted. |
| `skills/smith-index/templates/.gitignore-smith-additions` | ONE new line in the `IGNORED` section: `.smith/vault/.scheduled-audits-state.json`, grouped with the existing `.current-session`/`.active-workflow` dotfile entries (FR-23). |
| `docs/scheduler.md` | New section describing the audits step (what it scans, what it dispatches, ordering relative to the queue step, `SMITH_AUDIT_DISPATCH_DRY_RUN`, Linux manual-cron note) (FR-24). |
| `docs/security-model.md` | New paragraph under "Scheduler Security" describing the audits step's security posture; in the same edit, corrects the stale `` `"mode": "autonomous"` `` bullet to `` `complexity: autonomous` `` (FR-25). |
| `CHANGELOG.md` | New `[Unreleased]` → `### Added` entry, written LAST after every other file's changes are final (FR-26). |

### NEW

| File | Purpose |
|---|---|
| `tests/scheduler/test_is_audit_due.sh` | Pure-function test for `is_audit_due()` — never-run (empty `last`), exactly-at-cadence-boundary, one-day-under, one-day-over, and a `cadence_days` override, all via direct sourcing of the function (no filesystem fixture needed, per FR-3's testability requirement). |
| `tests/scheduler/test_smith_scheduler_audits_step.sh` | Integration-style test for the audits step's project-scan logic — a `mktemp -d` fixture project with `.smith/config.json` (enabled/disabled variants) and `.smith/vault/.scheduled-audits-state.json` (present/absent/corrupt variants), run with `SMITH_AUDIT_DISPATCH_DRY_RUN=1` so no real `claude` invocation occurs, asserting on the logged dispatch/skip decisions in `scheduler.log`. Sibling in shape to the existing `tests/skills/test_smith_build_coverage_flag.sh` pattern (a throwaway fixture + assertions on a produced artifact), adapted to this repo's one existing scheduler-adjacent test directory naming gap — `tests -name '*sched*'` returned zero matches before this feature, so `tests/scheduler/` is a NEW directory, not an extension of an existing one. |

No `scripts/security/*`, `scripts/parsers/*`, or `skills/smith-queue/*`
file is created or modified by this feature (OOS-2, NFR-3).

## Phased ordering

1. **`scheduled_audits` config schema + three-site seeding, first.**
   `templates/config.default.json`, `skills/smith/SKILL.md`'s new seed
   paragraph, and `skills/smith-update/SKILL.md`'s new §5.1f ship together
   — before either `/smith-audit` or the scheduler references the
   `scheduled_audits` key, mirroring feature 57's own "config before the
   prose that reads it" sequencing.
2. **`skills/smith-index/templates/.gitignore-smith-additions`.**
   Independent one-line addition; sequenced early since nothing else
   depends on it, but nothing else needs to wait for it either — grouped
   here for phase-numbering convenience only.
3. **`skills/smith-audit/SKILL.md`, as one unit.** Phase 0 (parsing +
   refusals + marker bootstrap/clear for both modes) + the Report
   Generation additions (filename substitution + Drift block + rolling
   log + `skip_pdf` gate) ship together — a scheduler dispatch is useless
   until `/smith-audit` can interpret `--scheduled` end-to-end, so this
   MUST land before phase 4's scheduler changes are exercised against a
   real project (though the scheduler script itself can be written in
   parallel; it is SEQUENCED after only in the sense that phase 4's
   dispatch string is not meaningfully testable end-to-end until this
   phase is done).
4. **`scheduler/smith-scheduler.sh`.** `is_audit_due()` + the new audits
   loop + dry-run branch + summary-line tally extension, as one unit
   (the loop's dispatch call and the summary line's new counters are
   written together to avoid an internally inconsistent half-shipped
   script).
5. **`docs/scheduler.md` + `docs/security-model.md`.** Sequenced after
   phases 3-4 so both docs describe the FINAL dispatch string and FINAL
   marker/report behavior, not an interim draft — same reasoning feature
   57's plan gave for writing its own docs/config-seeding last relative to
   the behavior they describe. The `security-model.md` field-name
   correction (FR-25) rides along in this same phase since it's a one-line
   edit to a file already being touched.
6. **`tests/scheduler/test_is_audit_due.sh` + `test_smith_scheduler_audits_step.sh`.**
   Written against the FINAL `is_audit_due()`/audits-loop implementation
   from phase 4, not an interim draft — mirrors feature 57's own
   "test file written after the final algorithm text" sequencing for its
   function-length scan test.
7. **`CHANGELOG.md`.** Written last, after phases 1-6 are final.

## Test strategy

- **`tests/scheduler/test_is_audit_due.sh` (primary new test, pure
  function).** `is_audit_due()` is deliberately extracted as a pure
  function taking `now`/`last`/`cadence` with no file I/O (§Contracts),
  specifically so this test needs no fixture project, no `mktemp -d`, and
  no `.smith/` scaffolding — it sources the function directly (via a
  small `source`-able extraction, or by `grep`-extracting the function
  body from `smith-scheduler.sh` into a subshell, matching whichever
  approach `tests/skills/test_smith_build_coverage_flag.sh` already
  established for testing an inline script algorithm without invoking the
  whole script). Cases: `last=""` → due (never run); `last` exactly
  `cadence_days` ago → due (`>=`, not `>`); `last` one day short of
  cadence → not due; `last` one day past cadence → due; a
  `cadence_days=1` override correctly shortens the window; a `cadence_days`
  override of `0` is due immediately regardless of `last` (edge case worth
  asserting explicitly since a project might legitimately want "every scheduler
  run" cadence for a fast-moving repo).
- **`tests/scheduler/test_smith_scheduler_audits_step.sh` (integration,
  dry-run only).** A `mktemp -d` fixture with a minimal `.smith/config.json`
  (varying `scheduled_audits.enabled` true/false and `cadence_days`) and a
  `.smith/vault/.scheduled-audits-state.json` (varying present-and-due,
  present-and-not-due, absent, and deliberately corrupt/unparseable JSON),
  invoked with `SMITH_SCHEDULER_ENABLED=1 SMITH_AUDIT_DISPATCH_DRY_RUN=1
  bash scheduler/smith-scheduler.sh`, asserting on the resulting
  `scheduler.log` dispatch/skip lines — never invoking a real `claude`
  process (no live network calls, no billing, matching this repo's
  existing no-live-invocation test convention for scheduler-adjacent and
  quality-check tests alike).
- **`skills/smith-audit/SKILL.md`'s Phase 0 additions are prose-only, no
  new standalone script** — consistent with this repo's precedent for
  SKILL.md-level prose changes (feature 57's own §3.1/§3.1b/§3.1c), these
  are verified via **prose-consistency greps** run after the prose lands,
  not a dedicated bash test: `grep -n "^## Phase 0: Scheduled Mode"
  skills/smith-audit/SKILL.md` (confirms the new section exists),
  `grep -c "\-\-scheduled" skills/smith-audit/SKILL.md` (expect multiple —
  parsing, refusal checks, and the Report Generation filename-substitution
  reference all name it), `grep -n "create-active-workflow.sh" skills/
  smith-audit/SKILL.md` (confirms the marker bootstrap call exists),
  `grep -c "clear-active-workflow.sh" skills/smith-audit/SKILL.md` (expect
  ≥1 per documented exit point named in FR-12's prose), `grep -n "Drift
  Since Last Scheduled Audit\|audits-log.md" skills/smith-audit/SKILL.md`
  (confirms both Report Generation additions exist).
- **Config-seeding regression** — `tests/hooks/test_config_default_seed.sh`
  (existing, if present — confirm during implementation; if this exact
  file doesn't exist under that name, the nearest existing config-seed
  regression test is extended instead, following whatever this repo's
  actual current test-file name is) is expected to keep passing UNMODIFIED
  apart from one new assertion that a fresh-project copy now includes
  `scheduled_audits`.
- **Full-suite regression** — run the complete `tests/` directory after
  all phases land, confirming zero regressions in unrelated scripts this
  feature does not touch (`skills/smith-queue/*`, every hook not named
  above, every parser).
- **Shell portability** — both new `tests/scheduler/*.sh` files, and the
  `smith-scheduler.sh`/`SKILL.md` shell snippets they test, are run under
  both `bash` and `zsh` during implementation review (NFR-2), matching
  this repo's existing dual-shell convention.

## Rollout notes

- No `scripts/install.sh` change is needed — this feature ships no new
  top-level `.sh`/`.py` file under `scripts/` (the two new test files live
  under `tests/`, not `scripts/`), so there is nothing for that stanza to
  newly copy.
- The scheduler's audits step and `/smith-audit`'s `--scheduled` mode are
  both live for every project from the moment this ships, but
  `scheduled_audits.enabled` defaults to `false` — a project sees ZERO new
  behavior (no dispatch, no marker bootstrap in scheduled mode, no new
  report naming) until it opts in. The ONE exception is FR-18's
  interactive-marker-bootstrap fix, which is unconditional (not gated by
  `scheduled_audits.enabled`) — every interactive `/smith-audit` run,
  starting from this feature's release, creates and clears an `audit-<TS>`
  marker even for a project that never touches the `scheduled_audits`
  config key at all. This is called out explicitly since it is the one
  piece of this feature's behavior that is NOT opt-in.
- Distributed via the standard `/smith-update` path — `scheduler/
  smith-scheduler.sh` and `skills/smith-audit/SKILL.md` are both
  Smith-owned files already refreshed by `/smith-update`'s existing global
  update (`~/.smith/scheduler/`, `~/.claude/skills/`); §5.1f (new) handles
  the config-seeding half for already-initialized projects.

## Spec-plan tensions — RESOLVED, folded into the sections above

1. **Two-surface phased ordering (SKILL.md before scheduler script).**
   Resolved: phase 3 (`/smith-audit`) before phase 4 (scheduler) — folded
   into "Phased ordering" above, with the explicit caveat that the two
   files can be DRAFTED in parallel but the scheduler's dispatch isn't
   meaningfully testable end-to-end until `/smith-audit` can interpret
   `--scheduled`.
2. **`is_audit_due()` extraction as a pure function vs. inline
   date-arithmetic in the loop.** Resolved: extracted, per the task's
   explicit testability instruction ("design for testability: cadence
   check as a small function taking now/state/config") — folded into
   §Contracts and the Test Strategy's first bullet.
3. **New `tests/scheduler/` directory vs. extending `tests/skills/`.**
   Resolved: a new `tests/scheduler/` directory — `find tests -name
   '*sched*'` returned zero existing matches, and the audits step is
   scheduler-owned logic (not a SKILL.md-embedded algorithm like
   `tests/skills/`'s existing contents), so it gets its own top-level test
   directory rather than being shoehorned into `tests/skills/`. Folded
   into the "NEW" file-by-file table and its own footnote.
4. **Report filename `<name>` construction (hyphen-joined subsets vs. a
   short fixed literal like "scheduled").** Resolved: hyphen-joined
   subsets — self-describing and collision-resistant across projects
   configuring different subset lists, at the cost of a longer filename;
   folded into §Contracts' filename-substitution table and `questions.md`'s
   "Plan-level mechanical resolutions" note.
