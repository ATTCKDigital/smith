---
feature: 58-scheduled-audits
branch: 58-scheduled-audits
created: 2026-09-14
status: ready-to-build
spec: ./spec.md
plan: ./plan.md
questions: ./questions.md
checklist: ./checklists/requirements.md
---

# Tasks: Scheduled Audit Subsets

Task IDs are sequential. `[P]` marks tasks that share no files with their
phase neighbors and can be executed in parallel. Tags map to the plan's
two-surface split (`[scheduler]`, `[audit]`) plus `[config]`, `[docs]`,
`[tests]`, `[verify]`. Every path is relative to the smith-repo project
root unless noted.

Hard constraints (carried from spec.md / plan.md, apply to every task
below):
- **NFR-1 / no-terminate**: nothing this feature adds may introduce a new
  block/terminate path. The ONLY failures are the pre-marker argument
  refusals (FR-8/FR-9/FR-10) — argument-shape errors, not finding-severity
  gates.
- **NFR-2**: every new shell snippet runs correctly under both `bash` and
  `zsh`; every Python snippet uses `python3` (also Rule 6 of
  `~/.claude/CLAUDE.md`).
- **NFR-3**: the audits step never mutates a `/smith-queue` queue file or
  `history/` entry.
- **NFR-4**: `/smith-audit`'s marker bootstrap never creates a git
  worktree, branch, or filesystem artifact beyond the marker YAML itself.
- **NFR-5**: no prompts, confirmations, or pauses anywhere in scheduled-mode
  logic.
- `scheduled_audits.enabled: false` is the MANDATORY shipped default
  (FR-19) — no task may ship it `true`.
- FR-18 (marker bootstrap covers BOTH `--scheduled` and plain interactive
  `/smith-audit` invocations) is unconditional — do not gate T011/T012
  behind `--scheduled` presence.

**On-disk verification performed before writing this file** (all plan.md
citations re-confirmed against the actual worktree, not taken on the
plan's word alone):
- `scheduler/smith-scheduler.sh` (252 lines): queue loop closes at line
  249 (`done <<< "$PROJECT_PATHS"`), final summary `log` line at 251,
  `resolve_claude_bin()` at lines 57-76, dry-run branch at lines 203-207,
  dispatch block at lines 215-221 — all exactly as plan.md cites.
- `find tests -name '*sched*'` → zero matches, confirmed: `tests/scheduler/`
  is a genuinely new directory.
- `scripts/create-active-workflow.sh` line 115: `maintenance` already in
  the `--workflow` allowlist (`smith-new|smith-bugfix|smith-debug|
  smith-build|smith-index|smith-update|smith-queue|maintenance`) — no enum
  change needed (A-2).
- `skills/smith-audit/SKILL.md` (281 lines): confirmed zero existing
  marker/Phase-0 content; "System Selection" at line 36; "Sub-Audit
  Orchestration" 11-item list at lines 105-119; "Report Generation" at
  line 121; "Key Rules" at lines 273-280.
- `hooks/workflow-gate.sh` line 97: `SAFE_VAULT_DIRS=(sessions bank ledger
  queue agents todo reports index audits)` — `reports` present, confirming
  FR-16 needs no gate change.
- `skills/smith-index/templates/.gitignore-smith-additions`: IGNORED
  section (lines 12-25) has no `.scheduled-audits-state.json` line and no
  `.smith/vault/reports/` line — confirms FR-23 needs exactly one new line,
  FR-16 needs none.
- `templates/config.default.json` (85 lines): `quality` closes at line 51,
  `context_budget` opens at line 52 — confirms T020's insertion point.
- `skills/smith/SKILL.md`: `quality` seed block spans lines 365-401 (closes
  with `fi` / ```` ``` ```` at lines 400-401); `### 5.1e Seed \`quality\``
  in `skills/smith-update/SKILL.md` spans lines 384-427, `### 5.2` starts
  at line 428 — confirms T021/T022 insertion points.
- `tests/hooks/test_config_default_seed.sh` exists (250 lines) with a
  `setup_project()` fake-`$HOME` fixture pattern (lines 73-81) and an
  existing `"quality"` assertion at line 131 — this is the precedent T009
  and T044 below reuse for isolating the scheduler's `$HOME/.smith/`
  reads from the developer's real home directory.
- `docs/security-model.md` line 153 (` `"mode": "autonomous"` ` inside
  "Only processes autonomous tasks") confirmed stale against
  `scheduler/smith-scheduler.sh` lines 125/128 (`COMPLEXITY=$(grep
  '^complexity:' ...)`) and `docs/scheduler.md` line 64 (already correct)
  — FR-25's correction target confirmed exact.

---

## Phase 1: Scheduler — audits step (`scheduler/smith-scheduler.sh`)

- [X] T001 [scheduler] Add `is_audit_due(now_date, last_run_date, cadence_days)` pure function to `scheduler/smith-scheduler.sh`, defined alongside `resolve_claude_bin()` (after the `SAFETY GUARD` exit block, before `log "=== Daily scheduler run started..."`) per plan.md §Contracts' exact bash body — `date -j -f "%Y-%m-%d" ... || date -d ...` fallback pair matching this repo's cross-platform convention (`hooks/active-workflow-janitor.sh`'s `mtime_of()`, lines 76-77, `stat -f ... || stat -c ...`). No file I/O, no globals read or written. FR-3.
- [X] T002 [scheduler] Add a second top-level `while IFS= read -r vault_path; do ... done <<< "$PROJECT_PATHS"` loop to `scheduler/smith-scheduler.sh`, inserted after the existing queue loop's closing `done` (currently line 249) and before the final summary `log` line (currently line 251) — reuses the SAME already-parsed `$PROJECT_PATHS` variable, no second `projects.json` read. Per iteration: derive `PROJECT_DIR="${vault_path%/.smith/vault}"` (same idiom the queue loop already uses) and `PROJECT_NAME=$(basename "$PROJECT_DIR")`; read `$PROJECT_DIR/.smith/config.json`'s `scheduled_audits.enabled`/`cadence_days`/`subsets` via `python3 -c "import json..."`; skip silently (one logged skip line, no dispatch, no state-file write) when the config file is absent, the `scheduled_audits` key is absent, or `enabled` is `false`. FR-1, FR-2, SC-2.
- [X] T003 [scheduler] Within the new loop, read `$vault_path/.scheduled-audits-state.json`'s `last_run.date` — treat an absent file, an unreadable file, or JSON that fails to parse identically as "never run" (empty `last_run_date` fed into T001's function), never as an error that skips or crashes that project's check. Call `is_audit_due()` to get the due/not-due decision; log a one-line skip reason ("disabled" vs. "not yet due, last run <date>") for a not-due project, matching US-2's "no state-file write occurs for a skipped project" contract. FR-4, FR-22, US-2, US-6, SC-2.
- [X] T004 [scheduler] Add the dispatch block for a due project: `"$CLAUDE_BIN" --model "$CLAUDE_MODEL" --permission-mode bypassPermissions -p "/smith-audit --all --scheduled <subsets>"` (subsets = `scheduled_audits.subsets` comma-joined in configured order) run from `$PROJECT_DIR` in a subshell, stdout/stderr routed into the SAME `$LOG_FILE`, reusing the already-resolved `$CLAUDE_BIN`/`$CLAUDE_MODEL` from earlier in the script run (no second `resolve_claude_bin()` call) — identical contract shape to the existing queue dispatch block (lines 215-221). FR-5, US-1.
- [X] T005 [scheduler] Add the `SMITH_AUDIT_DISPATCH_DRY_RUN=1` branch — a variable DISTINCT from `SMITH_SCHEDULER_DRY_RUN` (the two steps' dry-run modes toggle independently) — that logs the planned dispatch (project name, resolved subsets, computed due/not-due) without invoking `$CLAUDE_BIN` at all, mirroring the queue step's existing dry-run branch shape (lines 203-207). FR-7.
- [X] T006 [scheduler] Add "log and continue" failure handling: a non-zero dispatch exit code, or a report-path/severity read-back that doesn't confirm success (per T019/FR-18's write-after-success contract), is logged with the project name and reason and does NOT `exit`/`raise`/otherwise stop the audits step from continuing to the next registered project — identical in spirit to the queue step's own per-task failure contract. FR-6.
- [X] T007 [scheduler] Extend the final summary `log` line (currently line 251) to report a SECOND, distinct counter set for the audits step (e.g. `AUDITS_DISPATCHED`/`AUDITS_FAILED`/`AUDITS_SKIPPED`), incremented at each branch added in T002-T006, alongside the existing `TOTAL_DISPATCHED`/`TOTAL_FAILED`/`TOTAL_SKIPPED` queue counters — written together with T002-T006 as one commit/unit so the script is never left in an internally inconsistent half-shipped state.
- [X] T008 [P] [tests] Create `tests/scheduler/test_is_audit_due.sh` (new directory — confirmed via `find tests -name '*sched*'` → zero prior matches). **Do not `source scheduler/smith-scheduler.sh` directly** — the script performs real top-level work before any function is reachable (creates `$HOME/.smith/scheduler/scheduler.log`, and would run BOTH loops against the real `~/.smith/projects.json` once past the `SMITH_SCHEDULER_ENABLED` gate). Instead extract just the function body, e.g. `sed -n '/^is_audit_due() {/,/^}/p' scheduler/smith-scheduler.sh > "$TMPFILE" && source "$TMPFILE"`, then exercise it directly. Cases: `last=""` → due (never run); `last` exactly `cadence_days` ago → due (`>=`, not `>`); `last` one day short of cadence → not due; `last` one day past cadence → due; a `cadence_days=1` override correctly shortens the window; `cadence_days=0` → due immediately regardless of `last`. FR-3.
- [X] T009 [P] [tests] Create `tests/scheduler/test_smith_scheduler_audits_step.sh` — integration-style, dry-run only. Reuse `tests/hooks/test_config_default_seed.sh`'s `setup_project()` fake-`$HOME`/fake-project fixture pattern (that file's lines 73-81): a `mktemp -d` project root with `.smith/config.json` (varying `scheduled_audits.enabled` true/false and `cadence_days`) and `.smith/vault/.scheduled-audits-state.json` (present-and-due, present-and-not-due, absent, and deliberately corrupt/unparseable JSON variants), PLUS a `mktemp -d` fake `$HOME` whose `$HOME/.smith/projects.json` contains a `"path": "<project>/.smith/vault"` entry pointing at the fixture (the scheduler hardcodes `SMITH_DIR="$HOME/.smith"` — without overriding `$HOME` this test would read/write the developer's real `~/.smith/`). Invoke `SMITH_SCHEDULER_ENABLED=1 SMITH_AUDIT_DISPATCH_DRY_RUN=1 HOME="$FAKE_HOME" bash scheduler/smith-scheduler.sh`; assert on the resulting `$FAKE_HOME/.smith/scheduler/scheduler.log` dispatch/skip lines. Never invokes a real `claude` process. FR-7, US-1, US-2, US-6.

**Checkpoint**: `scheduler/smith-scheduler.sh` dispatches/skips correctly under dry-run against a fixture registry; both new scheduler tests pass. The dispatch string it builds cannot be exercised against a real `/smith-audit` end-to-end until Phase 2 lands (plan.md's Phased Ordering) — that is expected at this checkpoint, not a defect.

---

## Phase 2: `/smith-audit` — `--scheduled` mode (`skills/smith-audit/SKILL.md`)

- [X] T010 [audit] Insert a new `## Phase 0: Scheduled Mode & Marker Bootstrap` section into `skills/smith-audit/SKILL.md`, positioned before the existing `## System Selection` section (currently line 36). Parse `--scheduled` and the comma-separated subset list immediately following it out of `$ARGUMENTS` (grammar: `--scheduled requirements,codequality,...`, comma-separated, no further flag). Validate each token against the 11-category vocabulary already enumerated in "Sub-Audit Orchestration" (lines 105-119); an unrecognized token OR `feature` anywhere in the list is a refused invocation — logged failure, no marker created, no report written — validated BEFORE any marker creation or sub-audit dispatch. Refuse (same no-marker/no-report contract) a `--scheduled` invocation that lacks `--all` or a resolvable system identifier, rather than falling through to the interactive empty-args prompt. FR-8, FR-9, FR-10, US-4, SC-3.
- [X] T011 [audit] In the same Phase 0 section, add the marker bootstrap block for BOTH invocation modes (per FR-18, unconditional — not gated behind `--scheduled`): `TS=$(date -u +"%Y-%m-%dT%H-%M-%SZ")`; `LABEL="scheduled-audit-${TS}"` for `--scheduled`, `LABEL="audit-${TS}"` for plain interactive; call `~/.smith/scripts/create-active-workflow.sh --branch "$LABEL" --workflow maintenance --slug "$LABEL" --worktree "$PROJECT_DIR"` BEFORE any report file is written — mirrors `skills/smith-update/SKILL.md`'s Phase 0 pattern (lines 49-68) verbatim, reusing the `maintenance` allowlist entry (`scripts/create-active-workflow.sh` line 115) unchanged, no new enum value. The `--branch` value is a synthetic label naming no real git ref — `/smith-audit` never creates a worktree or branch (NFR-4). FR-11, FR-18, A-2.
- [X] T012 [audit] Add `"$PROJECT_DIR/.specify/scripts/bash/clear-active-workflow.sh" "$LABEL"` cleanup instructions at every documented exit point in Phase 0 / the rest of the SKILL.md's prose — normal completion, a post-marker-creation validation failure, a sub-audit crash, a report/drift/log-write failure — mirroring `skills/smith-update/SKILL.md`'s per-early-return "cleanup marker, exit cleanly" comment pattern (since `/smith-audit` spans multiple separately-invoked bash blocks and Claude tool calls, not one OS process, a single `trap ... EXIT` cannot span the whole flow). FR-9/FR-10 refusals need NO clearing instruction (they occur before marker creation). FR-12, US-3.
- [X] T013 [audit] Add a one-sentence cross-reference note to the existing `## System Selection` section (line 47's "If `$ARGUMENTS` is empty" branch): a `--scheduled` invocation without `--all`/a system identifier is refused by Phase 0 per T010 and never reaches this prompt branch.
- [X] T014 [audit] Modify `## Report Generation`'s filename-stem resolution (both the per-system `<date>-full.md` branch, line 126, and the full-spectrum `<date>-full-spectrum.md` branch, line 239) in `skills/smith-audit/SKILL.md`: whenever `--scheduled` is present, substitute the stem `<YYYY-MM-DD>-scheduled-<name>` (`<name>` = the validated subset list from T010, hyphen-joined, configured order — e.g. `requirements-codequality-security-dependencies-workflow`). Directory placement is UNCHANGED in both branches — only the filename stem changes. FR-13.
- [X] T015 [audit] Add a conditional `## Drift Since Last Scheduled Audit` block to Report Generation, positioned immediately after the report's header block (Date/System/Auditor) and before `## Executive Summary`. When `--scheduled` is present AND `.smith/vault/.scheduled-audits-state.json`'s `last_run.report_path` resolves to a readable file (absent state file, corrupt JSON, or an unreadable/missing `report_path` are all "no prior report" — omit the section entirely, never rendered empty or with placeholder text), parse the prior report's `## Executive Summary` table and emit one row per category present in EITHER report: Critical/Warning/Info deltas annotated `(new)` when increased, `(resolved)` when decreased; a category present in only one side is disclosed as `"not compared — subset not run in both audits"`, never a false 0. FR-14, FR-15, FR-22, US-5, US-6.
- [X] T016 [audit] Add a conditional rolling-log append to Report Generation: on successful `--scheduled` completion (after the report — and drift block, when present — is fully written), append exactly one line to `.smith/vault/reports/audits-log.md` (create fresh with no header if absent) in the format `<UTC-timestamp> | scheduled | subsets=<comma-list> | report=<report path> | critical=<N> warning=<N> info=<N>`, sourced from the new report's own Overall row. No gate-marker or gitignore-template change applies to this specific file — confirmed on disk: `.smith/vault/reports/` is already in `hooks/workflow-gate.sh`'s `SAFE_VAULT_DIRS` (line 97) and absent from `.gitignore-smith-additions`'s IGNORED section. FR-16.
- [X] T017 [audit] Add a `skip_pdf` gate immediately before the existing `## PDF Report Generation` section (line 244): when `--scheduled` is present, read `scheduled_audits.skip_pdf` (default `true`) from `.smith/config.json` and skip the entire PDF section when `true`; when `false`, PDF generation runs best-effort exactly as it does today for an interactive run (a PDF-generation failure was already non-fatal before this feature — unchanged). FR-17.
- [X] T018 [audit] Add one new bullet to the existing `## Key Rules` section (currently lines 273-280) stating the marker-clear-on-every-exit-path contract from T012, mirroring `skills/smith-update/SKILL.md`'s own "Active-workflow marker must be created BEFORE any file write" Key Rule.
- [X] T019 [audit] Add the write-after-success contract for `.smith/vault/.scheduled-audits-state.json` to Report Generation: written ONLY after the report (and drift block, when applicable per T015) and the rolling-log append (T016) have both succeeded — never write-before-dispatch, never write-on-failure. Shape exactly per plan.md §Contracts' State file schema (`last_run.date`/`.timestamp`/`.subsets`/`.report_path`/`.severity_totals`). FR-21.

**Checkpoint**: `/smith-audit` can interpret `--scheduled` end-to-end (parse → refuse-or-bootstrap → run → name → diff → log → write-state → clear). Phase 1's dispatch string is now meaningfully testable against a real `/smith-audit` invocation (not exercised by this feature's own automated tests — see the Verification Scope note at the bottom of this file).

---

## Phase 3: Configuration (`templates/config.default.json`, init seed, `/smith-update` §5.1f, gitignore template)

- [X] T020 [config] Add the `scheduled_audits` key to `templates/config.default.json`, inserted after `quality`'s closing `}` (currently line 51) and before `context_budget` (currently line 52), continuing the file's existing feature-append insertion order. Exact shape (plan.md §Contracts): `{"enabled": false, "cadence_days": 7, "subsets": ["requirements", "codequality", "security", "dependencies", "workflow"], "systems": "--all", "skip_pdf": true}` — `enabled: false` MANDATORY. FR-19.
- [X] T021 [config] Add a new unlettered seed paragraph + `python3` heredoc to `skills/smith/SKILL.md`'s init scaffold (Phase 4: Generate Files), mirroring the existing `quality` seed block (lines 365-401) exactly, retargeted at `scheduled_audits` with T020's shape, placed immediately after that block's closing `fi` / ```` ``` ```` (line 401) and before the "Copy from `~/.claude/skills/smith/`:" step (line 403). Same non-destructive rule: merge only when `.smith/config.json` exists and lacks `scheduled_audits` entirely; leave absent if the file itself doesn't exist. FR-20.
- [X] T022 [config] Add a new `### 5.1f Seed \`scheduled_audits\` in \`.smith/config.json\`` section to `skills/smith-update/SKILL.md`, inserted immediately after the existing `### 5.1e Seed \`quality\`...` section (lines 384-427) and before `### 5.2 Run \`/smith-index --migrate-templates\`` (line 428) — identical three-line decision rule (key present → no-op; file exists, key absent → merge; file absent → leave absent) and `python3` heredoc shape as §5.1e, retargeted at T020's shape. FR-20.
- [X] T023 [config] Add exactly ONE new line, `.smith/vault/.scheduled-audits-state.json`, to the `IGNORED` section of `skills/smith-index/templates/.gitignore-smith-additions`, grouped with the existing per-machine dotfile entries `.smith/vault/.current-session` / `.smith/vault/.active-workflow` (lines 15/19) — NOT the file's `COMMITTED` (shared) category. FR-23.
- [X] T024 [P] [tests] Add one new assertion to `tests/hooks/test_config_default_seed.sh`'s existing "fresh project gets seeded" case (§3, around line 131, sibling of the existing `"quality"`/`"security_review"`/`"supply_chain"` assertions): `assert_file_contains "fresh project: contains scheduled_audits section" "$project/.smith/config.json" '"scheduled_audits"'`. Depends on T020 landing first (or is written first as a deliberately-failing assertion, then closes green once T020 lands). Every other assertion in this file stays UNMODIFIED per plan.md's regression contract.

**Checkpoint**: A fresh `/smith` init and an existing-project `/smith-update` both produce a `.smith/config.json` carrying `scheduled_audits` with `enabled: false`; `.scheduled-audits-state.json` is gitignored by the managed template.

---

## Phase 4: Documentation

- [X] T030 [docs] Add a new section to `docs/scheduler.md`, sibling to the existing `## How Task Processing Works` section (line 58), describing the audits step: what it scans (`scheduled_audits.enabled` + cadence via `.scheduled-audits-state.json`), the exact `/smith-audit --all --scheduled <subsets>` dispatch string, that it runs strictly after the queue loop finishes for every project, `SMITH_AUDIT_DISPATCH_DRY_RUN`'s contract, and a short "Linux: not automated, run manually" note pointing at the same manual-cron pattern the queue step already documents (OOS-1 — doc note only, no new automation). FR-24.
- [X] T031 [docs] Add a new paragraph under `docs/security-model.md`'s existing `## Scheduler Security` section (line 19) describing the audits step's security posture: read-only sub-audits, `enabled: false` default, git-worktree-free (never creates or checks out a branch, unlike the queue step's per-task worktree isolation). IN THE SAME EDIT, correct the stale `` `"mode": "autonomous"` `` bullet inside "Only processes autonomous tasks" (confirmed on disk at line 153) to `` `complexity: autonomous` `` — the field the code actually reads (`scheduler/smith-scheduler.sh` lines 125/128: `COMPLEXITY=$(grep '^complexity:' ...)`), already stated correctly in `docs/scheduler.md` line 64. FR-25.
- [X] T032 [docs] Add a new `[Unreleased]` → `### Added` entry to `CHANGELOG.md` (top of file, after line 8), written LAST — only after every other task in this file is final. Match the existing per-feature bullet-list style (see the feature #57 entry, lines 12-22, as the formatting precedent: bold feature title + parenthetical `(feature #NN, NN-slug)`, then nested bullets per surface changed). Cover: the scheduler's new audits step, `/smith-audit`'s `--scheduled` mode, the workflow-gate marker fix for BOTH invocation modes (FR-18, called out explicitly as the one non-opt-in behavior change per plan.md's Rollout notes), the `scheduled_audits` config key, the drift block, and the rolling `audits-log.md` log. FR-26.

**Checkpoint**: All three docs describe the FINAL dispatch string and FINAL marker/report behavior from Phases 1-2, not an interim draft.

---

## Phase 5: Verification

- [X] T040 [verify] Run prose-consistency greps against `skills/smith-audit/SKILL.md` (plan.md's Test Strategy — this file's Phase 0 additions are prose-only, no dedicated bash test): `grep -n "^## Phase 0: Scheduled Mode" skills/smith-audit/SKILL.md` (section exists, exactly once); `grep -c -- "--scheduled" skills/smith-audit/SKILL.md` (expect multiple hits — parsing, refusal checks, System Selection cross-reference, filename substitution); `grep -n "create-active-workflow.sh" skills/smith-audit/SKILL.md` (bootstrap call present); `grep -c "clear-active-workflow.sh" skills/smith-audit/SKILL.md` (expect ≥1 per documented exit point named in T012); `grep -n "Drift Since Last Scheduled Audit\|audits-log.md" skills/smith-audit/SKILL.md` (both Report Generation additions present).
- [X] T041 [verify] Run `bash tests/scheduler/test_is_audit_due.sh` and `bash tests/scheduler/test_smith_scheduler_audits_step.sh` (T008/T009) under BOTH `bash` and `zsh` (NFR-2) — all cases pass; confirm the integration test never spawns a real `claude` process (`ps`/log inspection, or simply: no network activity and the fixture `$FAKE_HOME` is untouched by any non-dry-run artifact).
- [X] T042 [verify] Run `bash tests/hooks/test_config_default_seed.sh` — confirm T024's new `scheduled_audits` assertion passes and every pre-existing assertion (security/ledger/reconcile/quality/security_review/supply_chain, idempotency, all three fallback paths) remains green.
- [X] T043 [verify] Run the complete `tests/` directory (full-suite regression) — confirm zero regressions in files this feature does not touch: `skills/smith-queue/*`, every hook not named in Phases 1-4, every parser under `scripts/parsers/`.
- [X] T044 [verify] Dry-run end-to-end smoke test, distinct from T009's per-case unit coverage: build a fresh `mktemp -d` fake project + fake `$HOME`/`projects.json` registry (same pattern as T009, standalone fixture — not a reuse of T009's exact fixture instance) with `.smith/config.json` (`scheduled_audits.enabled: true`, a due `cadence_days`) and `.smith/vault/.scheduled-audits-state.json` (`last_run.date` ≥ `cadence_days` in the past). Run `SMITH_SCHEDULER_ENABLED=1 SMITH_AUDIT_DISPATCH_DRY_RUN=1 HOME="$FAKE_HOME" bash scheduler/smith-scheduler.sh`. Assert the exact planned-dispatch line (project name, resolved subsets, due=true) is printed to `$FAKE_HOME/.smith/scheduler/scheduler.log` WITHOUT invoking `$CLAUDE_BIN`/`claude` at all — no subprocess spawned, no network call. SC-1, FR-7.
- [X] T045 [verify] Targeted greps confirming NFR-1/NFR-3/NFR-4/NFR-5 hold: `git diff --stat main -- skills/smith-queue/ scheduler/smith-scheduler.sh` shows the queue loop (lines 1-249 pre-feature) byte-unchanged apart from the new loop appended after it (NFR-3); `grep -n "git worktree\|git checkout -b\|git branch" skills/smith-audit/SKILL.md` returns no new matches introduced by Phase 2 (NFR-4); `grep -n "read -r REPLY\|read -p\|confirm\b" skills/smith-audit/SKILL.md`'s new Phase 0 content returns nothing (NFR-5); confirm no new `exit 1`-on-finding-severity path exists anywhere in the Phase 0 prose beyond the three named argument-validation refusals (FR-8/FR-9/FR-10) (NFR-1).

**Checkpoint**: Every FR/NFR/US/SC this feature specifies has either an automated assertion (T008/T009/T024/T040/T041/T042/T044/T045) or an explicit, named manual-verification note (see below) — nothing is silently unverified.

---

## Dependencies & Execution Order

### Phase-numbering vs. build order — read before starting

This file's phase numbers (1 = scheduler, 2 = audit skill, 3 = config, 4 =
docs, 5 = verify) match the task framing this file was generated against.
**plan.md's own "Phased ordering" section recommends a DIFFERENT build
sequence** (config schema first, then the gitignore line, then
`/smith-audit`, then the scheduler, then docs, then tests, then
CHANGELOG) — reasoning: `scheduled_audits.enabled`/`cadence_days`/
`subsets` are config keys Phase 1's scheduler code and Phase 2's
`/smith-audit` prose both NAME, and a scheduler dispatch is not
meaningfully exercisable end-to-end against a real `/smith-audit` until
Phase 2 can interpret `--scheduled`. Concretely, for an implementer:
- T001-T007 (scheduler) and T010-T019 (audit skill) reference the
  `scheduled_audits`/`.scheduled-audits-state.json` shapes as plain JSON
  keys — this has NO file-level dependency on T020-T022 (the JSON/prose
  that seeds those keys into a real project), so Phases 1-2 CAN be
  implemented before Phase 3 exactly as numbered here.
- T009, T024, T041, T042, T044 (anything that runs `/smith-audit` or the
  scheduler against a REAL seeded `.smith/config.json`) DO need Phase 3's
  `scheduled_audits` shape to exist first — Phase 3 must land before Phase
  5's verification tasks, and T024 specifically depends on T020.
- Per plan.md: `/smith-audit`'s `--scheduled` handling (Phase 2) should
  land before the scheduler's dispatch call (Phase 1) is exercised against
  a real project, though the two can be DRAFTED in parallel. This file's
  Phase-1-then-Phase-2 numbering does not contradict that — draft/commit
  order and verification order are different axes; T040/T041 (Phase 5)
  are what actually require Phase 2 complete.

### Task-level dependencies

- T001 has no dependencies (pure function, new code).
- T002-T007 depend on T001 (the loop calls `is_audit_due()`) and must land
  together as one unit (plan.md: "written together to avoid an internally
  inconsistent half-shipped script").
- T008 depends only on T001.
- T009 depends on T002-T007 (exercises the full audits loop) and on the
  fake-`$HOME` fixture pattern already established in
  `tests/hooks/test_config_default_seed.sh`.
- T010 has no dependencies (new section, new prose).
- T011 depends on T010 (refusal checks must run before marker creation —
  ordering within the same section).
- T012 depends on T011 (clears the marker T011 creates).
- T013 depends on T010.
- T014-T019 depend on T010-T012 (Phase 0 must exist before Report
  Generation can branch on `--scheduled`'s parsed state) and on each other
  in the stated order (T019's write-after-success gate references T016's
  rolling-log append as one of its two preconditions).
- T020 has no dependencies.
- T021, T022 depend only on T020's shape existing to copy (not on T020's
  file having landed first — all three can be authored in the same
  change).
- T023 is independent of T020-T022.
- T024 depends on T020.
- T030, T031 depend on Phases 1-2 being FINAL (plan.md: docs describe the
  final behavior, not an interim draft).
- T032 (CHANGELOG) depends on T001-T031 all being final — written last.
- T040 depends on T010-T019 (Phase 2) being complete.
- T041 depends on T008, T009.
- T042 depends on T024 (and transitively T020).
- T043 depends on every prior phase.
- T044 depends on T001-T007 (Phase 1) and T020 (needs a real
  `scheduled_audits` shape to seed the fixture's `.smith/config.json`).
- T045 depends on T002-T012 being complete (greps the finished diff).

### Verification scope — what is NOT covered by an automated test

Matching this repo's own precedent for SKILL.md-level prose changes
(feature #57's `smith-build`/`smith-bugfix` sections, verified via grep
only, no dedicated harness): SC-4 (marker cleared across three real
paths — normal completion, mid-run sub-audit crash, report-write failure)
and SC-5/SC-6 (drift-block correctness against real prior/corrupt state)
and SC-7 (interactive `audit-<TS>` marker lifecycle) are NOT exercised by
a bash test harness in this task list, because `/smith-audit` is a
Claude-orchestrated SKILL.md flow, not a standalone script `tests/` can
invoke headlessly. T040/T045's greps confirm the PROSE contains the
required calls/sections/counts; confirming their RUNTIME behavior (a real
`/smith-audit --scheduled` invocation actually clearing its marker after a
forced crash, for instance) is a manual/implementation-review step,
exactly as it was for every prior SKILL.md-only feature in this worktree.
This is a known, deliberate scope boundary — not an oversight — and is
called out here so it isn't mistaken for missing coverage.

### No-op confirmations (verified, not tasks)

- `scripts/install.sh` needs NO change — this feature ships no new
  top-level `.sh`/`.py` file under `scripts/` (the new tests live under
  `tests/`, already covered by whatever mechanism runs `tests/`).
- `skills/smith-queue/*` and `smith-scheduler.sh`'s existing queue-scan
  loop are untouched by every task above (OOS-2, NFR-3) — confirmed by
  T045's `git diff --stat`.
- No `constitution.md` exists in this repo — no constitution gate applies
  (plan.md's own Constitution Gates section, re-confirmed: still absent).

---

2026-09-14 — 58-scheduled-audits
