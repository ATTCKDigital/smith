---
feature: 57-quality-metrics-pack
branch: 57-quality-metrics-pack
status: ready-for-build
generated: 2026-09-14
inputs: spec.md (FR-1..FR-22, NFR-1..NFR-5, OOS-1..OOS-4, answers_applied 2026-09-14), plan.md (file-by-file + Phased ordering + Contracts + Test strategy), questions.md (5/5 ANSWERED via delegation)
---

# Tasks: Quality Metrics Pack for `smith-build` & `smith-bugfix`

15 tasks across 6 phases, matching this task-generation prompt's own phase
grouping (config+seeding; smith-build SKILL edits; bugfix edit; scan test;
CHANGELOG; verification) — a relabeling of `plan.md`'s six-step Phased
ordering, not a defect (see Coverage & Consistency Notes). Within a phase,
`[P]` tasks touch independent files and may run in any order/in parallel;
tasks touching the SAME file are listed in required sequential order and
are never marked `[P]` (feature 55/56's own convention, reused here).

This feature is prose-only — no new orchestrator script, one new test file
— matching `plan.md`'s own "smaller than 54/55/56" framing.

**Every plan.md claim this task-generation pass could verify against disk
was accurate — no false-precedent correction was required.** Two real
plan-level GAPS (underspecified, not wrong) were found and resolved below,
and one absent-but-explainable citation was confirmed benign. Full detail
in Coverage & Consistency Notes → "Verification & Corrections (ledger
discipline)".

---

## Phase 1 — Config + seeding (plan.md Phased ordering item 1: ships before any smith-build/smith-bugfix prose references `quality`)

- [X] [T001] [P] Edit `templates/config.default.json`. Add a new top-level
  `quality` key (spec FR-21, plan §Contracts) positioned after
  `supply_chain`'s closing `}` (confirmed line 35 this worktree) and before
  `context_budget` (confirmed line 36) — verified top-level key order this
  worktree: `_comment, security, security_review, supply_chain,
  context_budget, ledger`:
  ```json
  "quality": {
    "test": [],
    "lint": [],
    "typecheck": [],
    "coverage": {
      "command": null,
      "minimum_percent": null,
      "regex": null
    },
    "function_length": {
      "soft": 50,
      "decompose": 100
    },
    "timeout_seconds": 120,
    "excludes": []
  }
  ```
  A SIBLING of `security_review`/`supply_chain`, never nested under either
  (Q2, accepted). No `enforcement_tier`-shaped field anywhere in this
  schema (NFR-2) — this feature has no terminate path to gate.

- [X] [T002] [P] Edit `skills/smith/SKILL.md`. Add a new unlettered
  paragraph + python3 read-modify-write heredoc, mirroring the existing
  `supply_chain` seed block EXACTLY (confirmed lines 333-363 this
  worktree), retargeted at `quality` with T001's full default shape, placed
  immediately after that block's closing `fi` (line 363) and before "Copy
  from `~/.claude/skills/smith/`:" (line 365). Same three-line decision
  rule as the existing block: key present (any shape) → no-op; file
  exists, key absent → merge only `quality` with T001's defaults,
  preserving every other key; file absent entirely → leave absent (the
  whole-file template copy, now including `quality` via T001, already
  handles a brand-new project). Name `/smith-update`'s new `§5.1e` sibling
  (T003) in the prose, mirroring how the existing `supply_chain` paragraph
  names `§5.1d`. bash+zsh-safe.

- [X] [T003] [P] Edit `skills/smith-update/SKILL.md`. Add a new
  `### 5.1e Seed \`quality\` in \`.smith/config.json\`` section immediately
  after the existing `### 5.1d Seed \`supply_chain\`...` step (confirmed
  ending line 382 this worktree) and before `### 5.2 Run
  \`/smith-index --migrate-templates\`` (confirmed line 384). Same
  three-line decision rule and python3 heredoc shape as `5.1d` (confirmed
  lines 346-382), retargeted at `quality`/T001's defaults.

- [X] [T004] Phase 1 verification gate (no file edit) closing config
  seeding before any `smith-build`/`smith-bugfix` prose (T005+) may
  reference the `quality` key, per `plan.md`'s Phased ordering item 1.
  Depends on T001-T003.
  - `python3 -c "import json; d=json.load(open('templates/config.default.json')); assert d['quality']=={'test':[],'lint':[],'typecheck':[],'coverage':{'command':None,'minimum_percent':None,'regex':None},'function_length':{'soft':50,'decompose':100},'timeout_seconds':120,'excludes':[]}"`
    — confirms T001's exact shape, no drift.
  - Confirm T002's and T003's heredocs construct the IDENTICAL dict
    literal as T001 (byte-diff the three `config["quality"] = {...}`
    blocks after normalizing whitespace) — a schema mismatch between the
    three seed sites would silently produce a different `quality` shape
    depending on which path seeded a given project.
  - `grep -n "enforcement_tier" templates/config.default.json` scoped to
    the new `quality` block — zero matches inside it (NFR-2); confirm
    `security_review`'s own `enforcement_tier` field elsewhere in the same
    file is untouched.
  - `git diff main --name-only` — confirms ONLY `templates/config.default.json`,
    `skills/smith/SKILL.md`, `skills/smith-update/SKILL.md` are modified
    so far; no `smith-build`/`smith-bugfix` prose has changed yet.

---

## Phase 2 — `smith-build` SKILL edits (plan.md Phased ordering items 2-4: Phase-3 unit, then §5.3.2, then §5.4 template — all same file, sequenced, never `[P]`)

- [X] [T005] Edit `skills/smith-build/SKILL.md` §3.1/NEW §3.1b/NEW
  §3.1c/§3.3-extension, as ONE ship-together unit (`plan.md`'s own
  explicit rule: "§3.3's extended text references §3.1b/§3.1c by name, so
  drafting them separately would leave an internally inconsistent
  half-shipped file"). Depends on T001-T004. Confirmed current text this
  worktree:
  ```
  ### 3.1 Unit Tests
  - **If frontend code changed**: `cd services/command-center && pnpm test`
  - **If Python service changed**: `cd services/<service> && poetry run pytest`
  - Run existing test suites — do NOT skip tests

  ### 3.2 Playwright E2E Tests (MANDATORY for UI changes)
  ...
  ### 3.3 Test Failure Handling
  - If tests fail: fix the code and re-run (up to 3 attempts per failure)
  - If a test is flaky (passes on retry without code changes): note in release notes
  - If tests cannot be fixed after 3 attempts: log the failure and continue
    - The release notes will flag this as requiring manual attention
  ```
  a. **§3.1 "Unit Tests" → "Testing" (FR-1/FR-2).** When `.smith/config.json`'s
     `quality.test` array is present and non-empty: run each command
     independently via `python3 subprocess.run(..., timeout=quality.timeout_seconds)`
     (feature 56's Sub-layer D mechanism, reused verbatim — no shell
     `timeout`/`gtimeout` wrapper). No legacy fallback bullets execute in
     this case. When `quality.test` is absent, empty, or `.smith/config.json`
     itself is absent/malformed: run the CURRENT two bullets verbatim,
     unchanged, byte-for-byte (`cd services/command-center && pnpm test` /
     `cd services/<service> && poetry run pytest`) — zero behavior change.
  b. **NEW §3.1b "Lint" (FR-3) — GAP RESOLVED HERE, see Coverage & Consistency
     Notes.** Inserted immediately after §3.1's content and BEFORE the
     existing `### 3.2 Playwright E2E Tests` heading (confirmed line 234
     this worktree) — `plan.md` never states this position explicitly;
     resolved per this repo's own established lettered-insertion
     convention (`§5.1b`/`§5.1c`/`§5.1d` each insert between two adjacent
     existing numbered items without renumbering). Reads `quality.lint`;
     when absent or empty, this step is skipped ENTIRELY (no run, no PR
     mention) — no legacy fallback exists here (unlike §3.1).
  c. **NEW §3.1c "Typecheck" (FR-4).** Inserted immediately after §3.1b,
     still before §3.2. Reads `quality.typecheck`; same skip-when-absent
     behavior as §3.1b, same reasoning.
  d. **§3.3 "Test Failure Handling" extended (FR-5).** Add one explicit
     sentence to the existing bounded-retry/log-and-continue text (current
     3 bullets, confirmed lines 247-250) naming §3.1b/§3.1c command
     failures AND any per-command `quality.timeout_seconds` timeout
     (§3.1/§3.1b/§3.1c alike) as covered by the SAME existing bound (up to
     3 attempts, then log and continue) — no new retry loop, no
     heading/number change.

- [X] [T006] Edit `skills/smith-build/SKILL.md` — NEW `### 3.4 Coverage
  Check` (FR-9..FR-14). Depends on T005 (same file, sequenced after).
  Inserted after (extended) §3.3's content and before the existing
  `## Phase 3.5: Clean Code Review Pass` heading (confirmed line 252 this
  worktree) — a plain new number, not a lettered insertion, per
  `plan.md`'s own "Spec-plan tensions" item 1 (coverage is not a sibling of
  the §3.1/§3.1b/§3.1c command-running triad; nothing sits after §3.3 to
  renumber).
  - Runs `quality.coverage.command` exactly once via the SAME
    `subprocess.run(..., timeout=quality.timeout_seconds)` mechanism as
    T005a, only when configured (non-empty string) — absent → step
    skipped entirely, no `/tmp` file written, no PR section can ever
    appear for this build.
  - Match combined stdout+stderr against `quality.coverage.regex` FIRST
    when configured (exactly one capture group), else the built-in
    catalogue in this fixed order:
    | Tool shape | Pattern |
    |---|---|
    | pytest-cov `TOTAL` line | `TOTAL\s+\d+\s+\d+\s+(\d+(?:\.\d+)?)%` |
    | jest/istanbul `text-summary` `Lines` line | `Lines\s*:\s*(\d+(?:\.\d+)?)%` |
    | `go test -cover` | `coverage:\s*(\d+(?:\.\d+)?)%\s+of statements` |
  - Percent extracted AND `quality.coverage.minimum_percent` configured AND
    percent < minimum → exactly one High finding
    (`<percent>% < <minimum>%`, command excerpt, no `path:line` —
    coverage-run-scoped, not file-scoped) written to
    `/tmp/smith-build-coverage-findings.txt` (FR-11).
  - Percent extracted but no minimum configured → informational report
    only (FR-12), zero findings produced.
  - No regex (override or catalogue) matches → "coverage output unparsed"
    disclosure, NEVER a failure, never blocks or retries, never silently
    omitted from disclosure (FR-13).
  - A command timeout is treated IDENTICALLY to unparsed output — disclosed,
    never a build failure (FR-14) — distinct from §3.1/§3.1b/§3.1c, whose
    timeouts DO route through §3.3's retry; §3.4 never retries, ever.

- [X] [T007] Edit `skills/smith-build/SKILL.md` — NEW `### 5.3.2 Pre-PR
  Function-Length Scan` (FR-15..FR-18). Depends on T006 (same file,
  sequenced after; independent content, but same-file ordering rule
  applies). Inserted immediately after the existing §5.3.1 content ends
  (confirmed: right after the "Per data-model.md §9.3." sentence, line 780
  this worktree) and BEFORE the "Include a **Clean Code Review** section..."
  paragraph (confirmed line 782) — i.e., between lines 780 and 782.
  - Reuses `/tmp/smith-build-changed.txt` (from §5.3), the same extension
    filter (`.py`/`.js`/`.jsx`/`.ts`/`.tsx`) and exclude list (`vendor/`,
    `node_modules/`, `.venv/`, `dist/`, `build/`, `.smith/`) §5.3/§5.3.1
    already use, and the same installed-path-preferred (`.smith/scripts/`
    → `~/.smith/scripts/` → repo-dev-fallback `scripts/parsers/`) parser
    resolution §5.3.1 already uses (confirmed lines 641-650 pattern).
  - For each changed, in-scope file: parse it, then call
    `scripts/parsers/meta_describe.py`'s
    `qualifying_methods(parsed, threshold=quality.function_length.soft)`
    (default 50) UNCHANGED — **verified signature this worktree**:
    `qualifying_methods(parsed: dict, threshold: int = DEFAULT_THRESHOLD_LINES) -> list[dict]`
    (`scripts/parsers/meta_describe.py:199`), returning
    `{id, name, scope, line, end_line, body_lines, params, return_type}`
    per entry — the exact shape needed, no parser change required (OOS-2).
  - **Import mechanics — verified, not assumed.** `meta_describe.py` has
    NO CLI entrypoint (confirmed: zero matches for `__main__`/`argparse`/
    `sys.argv` in the file), so it cannot be invoked as a subprocess
    directly — it MUST be imported. Use
    `sys.path.insert(0, "scripts/parsers"); import meta_describe as md`,
    the EXACT pattern two real production consumers already use:
    `scripts/parsers/describe_write.py:31,34` and
    `scripts/parsers/describe_discover.py:65,68`
    (`sys.path.insert(0, str(THIS_DIR)); import meta_describe`, then
    `meta_describe.qualifying_methods(parsed, threshold)`) — this is
    stronger, already-battle-tested precedent beyond what `plan.md` itself
    cited.
  - Bucket each returned entry by `body_lines`: `>= quality.function_length.decompose`
    (100) → decompose-tier, listed INDIVIDUALLY (`path:line`, name,
    body-line count) in `/tmp/smith-build-function-length-findings.txt`;
    `>= soft` (50) and `< decompose` → soft-tier, folded into exactly ONE
    trailing `+ N soft-tier warnings` line, omitted when N=0, never listed
    individually (FR-17, mirrors this pipeline's existing
    low-severity-folding convention).
  - Non-empty findings file → PR body gains a "Function Length Warnings"
    section (§5.4, T008); empty → section omitted entirely (FR-18).

- [X] [T008] Edit `skills/smith-build/SKILL.md` §5.4 PR-body heredoc.
  Depends on T006, T007 (needs their exact `/tmp` file paths). Confirmed
  this worktree: the existing `## Supply-Chain Review` section ends line
  885, `## Release notes` begins line 887. Insert TWO new conditional
  sections between those lines, in this order — "Function Length
  Warnings" then "Quality Metrics" (FR-20, both appended after the newest
  existing section, per this pipeline's own convention):
  ```
  ## Function Length Warnings
  <include this section only when /tmp/smith-build-function-length-findings.txt is non-empty>

  <contents verbatim, e.g.:>
  - `services/billing/webhook.py:88` — `process_refund_batch` (118 lines, exceeds 100 — decompose)
  + 3 soft-tier warnings

  This is a FLAG, never a blocker. Always proceed with PR creation.

  ## Quality Metrics
  <include this section only when /tmp/smith-build-coverage-findings.txt is non-empty>

  <contents verbatim, e.g.:>
  - **[High]** Coverage 62% < configured minimum 80% (command: `pytest --cov=app --cov-report=term`)

  This is a FLAG, never a blocker. Always proceed with PR creation.
  ```
  Quality Metrics is non-empty whenever T006 produced a coverage finding
  or an unparsed-output disclosure worth surfacing; omitted entirely when
  §3.4 did not run (T006's absent-config skip) or ran and found nothing to
  report (FR-19).

---

## Phase 3 — `smith-bugfix` edit (independent of Phase 2's smith-build-only content; sequenced after Phase 1 since it reads `quality` — plan.md Phased ordering item 5)

- [X] [T009] Edit `skills/smith-bugfix/SKILL.md` §5.3 "Lint" (FR-6/FR-7).
  Depends on T001-T004. Confirmed current text this worktree:
  ```
  ### 5.3 Lint
  - **If frontend**: `cd services/command-center && pnpm lint`
  - **If Python**: `cd services/<service> && poetry run ruff check .`
  ```
  Generalize in place: when `quality.lint` is present and non-empty, run
  each listed command (same per-command `quality.timeout_seconds`
  mechanism as T005a/T006). When absent, empty, or config
  absent/malformed, run the CURRENT two bullets verbatim, unchanged,
  byte-for-byte — zero behavior change. This is the ONLY change to
  `smith-bugfix` from this feature (FR-6) — §5.1 "Unit Tests" (confirmed
  lines 289-291), §5.2 "Playwright E2E Tests" (293-296), §5.4 "Test
  Failure Handling" (302-305), and the §7.3 PR-body template (confirmed
  starting line 358) are all untouched (FR-8): `smith-bugfix` gains no
  coverage check, no function-length scan, and no new PR-body section of
  its own from this feature.

---

## Phase 4 — Scan test (plan.md Phased ordering item 3: written against the FINAL §5.3.2 text, so sequenced after T007, not before/parallel to it)

- [X] [T010] Create `tests/skills/test_smith_build_function_length_scan.sh`.
  Depends on T007. **Verified precedent, not assumed**: direct sibling of
  `tests/skills/test_smith_build_coverage_flag.sh` — confirmed this file
  EXISTS (279 lines, matching `plan.md`'s "~280 lines" estimate) and
  PASSES today (5/5, re-run during this verification pass). Its "coverage"
  in the filename is §5.3.1's DOCUMENTATION-coverage flag (whether a
  touched method has a `.meta` description) — a different "coverage" than
  this feature's NEW §3.4 code-coverage-PERCENT check; `plan.md`'s own
  text already draws this distinction correctly ("tests §5.3.1's inline
  algorithm"), so no correction is needed there — only the harness SHAPE
  is reused: `mktemp -d`+`trap cleanup` throwaway git repo, `PASS=0`/
  `FAIL=0`/`assert()` helper, a reusable `run_*` bash function, a final
  `PASS`/`FAIL`/summary line, `exit 1` on any failure. Do NOT reuse its
  git-diff-based touched-method comparison logic — this scan evaluates the
  CURRENT file content only, no prior-commit comparison, so fixture setup
  is simpler (no `git commit` on a baseline branch needed, just planted
  fixture files).
  - Target ≤180 lines (`plan.md`'s File Size Policy).
  - A `run_function_length_scan` bash function reproducing §5.3.2's
    algorithm (T007), calling the REAL `qualifying_methods()` via
    `python3 -c "import sys; sys.path.insert(0, 'scripts/parsers'); import meta_describe as md; ..."`
    — verified viable and correct (T007's import-mechanics note) — never
    re-deriving body-length logic itself.
  - Required cases (from `plan.md`'s Test Strategy, reproduced here):
    1. One function ≥100 lines listed individually with correct
       `path:line`/body-line count.
    2. Three functions in the 50-99 range folded into exactly one
       `+ 3 soft-tier warnings` line, never listed individually.
    3. One function <50 lines absent from the output entirely.
    4. An excluded-path file (e.g. under `node_modules/`) produces NO
       findings even with an oversized function inside it.
    5. A `quality.function_length` override (e.g. `soft=30`/`decompose=60`)
       correctly shifts which functions land in which tier.
  - Do NOT modify `tests/parsers/test_meta_describe.py` — `qualifying_methods()`
    itself is already covered there (confirmed: its `QualifyingMethodsTests`
    class calls `md._qualifying_methods`, a verified alias —
    `scripts/parsers/meta_describe.py:358`: `_qualifying_methods = qualifying_methods`
    — both names resolve to the same function; this file currently passes
    9/9, re-run during this verification pass). This new test exercises
    ONLY this feature's OWN new logic — threshold bucketing and
    fold/list-individually rendering — never re-testing the parser
    primitive.

---

## Phase 5 — CHANGELOG (plan.md Phased ordering item 6: written last, after every other file's changes are final)

- [X] [T011] Edit `CHANGELOG.md`. Depends on T001-T010. New `[Unreleased]`
  → `### Added` entry, matching the existing `#56`/`#55`/`#54` entries'
  bold-summary + sub-bullets style (confirmed this file's current head).
  Summarize: (a) `smith-build` §3.1 "Unit Tests" → "Testing" generalized
  in place + NEW §3.1b Lint/§3.1c Typecheck, all config-driven via
  `quality.test`/`.lint`/`.typecheck`, each command timeout-bounded via
  the same `python3 subprocess.run(..., timeout=N)` mechanism feature 56
  established — zero-behavior-change fallback preserved verbatim when
  `quality.test` is absent; (b) NEW `smith-build` §3.4 "Coverage Check" —
  built-in pytest-cov/jest-istanbul/go regex catalogue + configurable
  override, `minimum_percent` comparison produces a High finding, never
  blocks; unparseable output disclosed, never fails; (c) NEW `smith-build`
  §5.3.2 "Pre-PR Function-Length Scan" — soft/decompose two-tier
  (default 50/100), reuses `scripts/parsers/meta_describe.py`'s
  `qualifying_methods()` completely unchanged, decompose-tier findings
  listed individually, soft-tier folded into one `+ N soft-tier warnings`
  line; (d) `smith-bugfix` §5.3 "Lint" generalized the same way — the ONLY
  `smith-bugfix` change this feature makes; (e) new top-level `quality`
  config key (sibling of `security_review`/`supply_chain`) + its
  three-site non-destructive seeding (`templates/config.default.json` +
  `skills/smith/SKILL.md` init scaffold + `/smith-update`'s new §5.1e);
  (f) explicit flag-only, no-terminate posture for every new check —
  consistent with features 54/55/56's own flag-only precedent for their
  non-secret findings. Cite the feature by number (`#57`,
  `57-quality-metrics-pack`).

---

## Phase 6 — Verification (consistency greps, config-seed regression, full regression, fixture run)

- [X] [T012] Consistency verification sweep (no file edit unless a check
  below fails — then fix the offending file in place and re-check).
  Depends on T001-T011.
  - `grep -n "^### 3.1 Testing" skills/smith-build/SKILL.md` — confirms
    the rename landed (no lingering `### 3.1 Unit Tests` heading).
  - `grep -n "^### 3.1b\|^### 3.1c\|^### 3.4 Coverage Check\|^### 3.2 Playwright" skills/smith-build/SKILL.md`
    — confirms all three new sections exist AND, by comparing the printed
    line numbers, that §3.1b and §3.1c both sit BEFORE §3.2 (verifies the
    T005b gap-resolution actually landed in the intended position, not
    just that the headings exist somewhere).
  - `grep -n "^### 5\.3\.2" skills/smith-build/SKILL.md` — confirms it
    sits between §5.3.1 and the "Include a Clean Code Review" paragraph
    (compare line numbers against `grep -n "Clean Code Review\" section"`).
  - `grep -c "quality\.test\|quality\.lint\|quality\.typecheck" skills/smith-build/SKILL.md`
    — expect ≥3 (one config-key reference per new/generalized step).
  - `grep -n "quality\." skills/smith-bugfix/SKILL.md` — expect every
    match to be `quality.lint`; zero matches for `quality.test`,
    `quality.typecheck`, `quality.coverage`, or `quality.function_length`
    anywhere in this file (FR-8's exclusion boundary — `smith-bugfix`
    gains ONLY the Lint generalization).
  - `grep -c "Function Length Warnings\|Quality Metrics" skills/smith-build/SKILL.md`
    — expect ≥4 (each section name appears once as a producing-step
    reference and once as a PR-template heading).
  - `grep -n "enforcement_tier" templates/config.default.json` scoped to
    the `quality` block — zero matches (re-confirms T004 after all
    subsequent edits).
  - `git diff main --name-only` — confirms ONLY the expected files
    changed: `templates/config.default.json`, `skills/smith/SKILL.md`,
    `skills/smith-update/SKILL.md`, `skills/smith-build/SKILL.md`,
    `skills/smith-bugfix/SKILL.md`, `CHANGELOG.md`,
    `tests/skills/test_smith_build_function_length_scan.sh` (new),
    `tests/hooks/test_config_default_seed.sh` (T013) — and specifically
    that `skills/smith-implement/SKILL.md`, `scripts/parsers/parse-python.py`,
    `scripts/parsers/parse-js.js`, `scripts/parsers/meta_describe.py`, and
    every `hooks/*` file are ALL untouched (NFR-4, OOS-1, OOS-2).

- [X] [T013] Add ONE new regression case to `tests/hooks/test_config_default_seed.sh`.
  Depends on T001, T012. Confirmed existing pattern this worktree (inside
  the "fresh project gets seeded" test block, lines 117-143):
  `assert_file_contains "fresh project: contains security_review section" "$project/.smith/config.json" '"security_review"'`
  and the sibling `supply_chain` assertion immediately after it. Add:
  `assert_file_contains "fresh project: contains quality section" "$project/.smith/config.json" '"quality"'`
  in the SAME block, immediately after the `supply_chain` assertion. Every
  existing case in this file (8 numbered blocks, confirmed) must keep
  passing UNMODIFIED — pure regression addition, mirroring features 55/56's
  own identical precedent addition to this same file.

- [X] [T014] Full regression suite run. Depends on T001-T013.
  **Correction to plan.md's phrasing** (verified during this pass, see
  Coverage & Consistency Notes): this repo has NO single "run the whole
  `tests/` tree" command — no root `Makefile`/test-runner script exists,
  and `python3 -m pytest` is UNAVAILABLE in this environment
  (`ModuleNotFoundError: No module named pytest`, confirmed). The only
  "run-all" script, `tests/e2e/run-all.sh`, is scoped to `tests/e2e/`
  only. Per `CONTRIBUTING.md`'s own documented convention (confirmed lines
  260-268), every `.py` test is stdlib `unittest`, run via `python3 <file>`
  directly — never `pytest` — and every `.sh` test runs via `bash <file>`
  (dual-shell files also re-run under `zsh <file>`). Run explicitly,
  individually, confirming zero regressions in every file this feature
  does not touch:
  - `tests/hooks/*.sh` (all 11, including T013's updated
    `test_config_default_seed.sh`) — `bash <file>` each.
  - `tests/skills/*.sh` and `test_smith_index_global_install_layout.py`
    (including T010's new file and the pre-existing
    `test_smith_build_coverage_flag.sh`) — `bash`/`python3` per extension.
  - `tests/parsers/*.py` (via `python3 <file>`, including
    `test_meta_describe.py`, re-confirming 9/9) and `tests/parsers/*.sh`
    (via `bash <file>`).
  - `tests/security/*.sh` (4 files) — `bash <file>` each.
  - `tests/contracts/*.py` (2 files) — `python3 <file>` each.
  - `tests/e2e/run-all.sh` — the one existing aggregate runner, scoped to
    its own suite.
  - Top-level `tests/*.py`/`tests/*.sh` (get-base-branch, workflow-gate-
    redirect, workflow-summary-session, install.smoke, test_fuzzy_match,
    test_normalized, test_usd, test_active_duration, test_legacy_parse).

- [X] [T015] Fixture run of the §5.3.2 snippet (manual/scripted,
  exercising the ACTUAL shipped SKILL.md algorithm end-to-end against a
  real fixture, independent of T010's own dedicated unit test). Depends on
  T007, T014. Build (or reuse T010's) a throwaway `mktemp -d` git repo
  with one function ≥100 lines, three functions in the 50-99 range, and
  one function <50 lines. Copy-paste the EXACT bash+python snippet as it
  now reads in `skills/smith-build/SKILL.md` §5.3.2 (not the test file's
  own reproduction) and run it against that fixture. Assert:
  - `/tmp/smith-build-function-length-findings.txt` lists the ≥100-line
    function individually with correct `path:line`/name/body-line count,
    and folds the three 50-99 functions into exactly one
    `+ 3 soft-tier warnings` trailing line (SC-5).
  - The <50-line function appears nowhere in the output.
  - Re-run against an all-under-50-lines fixture → the findings file is
    empty/absent, confirming the PR-body "Function Length Warnings"
    section (T008) would be correctly OMITTED for that build (SC-6).

---

## Coverage & Consistency Notes (smith-analyze pass)

**Spec ↔ Plan ↔ Tasks alignment: PASS.** Every FR-1..FR-22/NFR-1..NFR-5 is
tasked; every row in `plan.md`'s "Exact file-by-file change list" has at
least one task; no task contradicts any of the 5 gate answers
(`questions.md`, 5/5 ANSWERED); no task instructs work `spec.md`'s Out of
Scope (OOS-1..OOS-4) excludes.

### Verification & Corrections (ledger discipline)

This pass verified every anchor `plan.md` cites against the actual
worktree on disk before tasking, per the standing "verify plan claims,
don't just transcribe them" discipline. Results:

**Confirmed accurate (no correction needed):**
- `tests/skills/test_smith_build_coverage_flag.sh` EXISTS (279 lines,
  matches `plan.md`'s "~280 lines" estimate) and PASSES today (5/5,
  re-run live during this pass). `tests/skills/` exists with 7 sibling
  files. The file's own header says it tests "§5.3.1... coverage flag
  algorithm" — this is DOCUMENTATION coverage (touched methods lacking a
  `.meta` description), a different "coverage" than this feature's NEW
  §3.4 code-coverage-PERCENT check. `plan.md`'s own prose already states
  this correctly ("tests §5.3.1's inline algorithm") — the plan does not
  conflate the two; only the test HARNESS SHAPE (mktemp-d fixture,
  `run_*` function, `assert()`/PASS/FAIL/summary) is reused for T010, not
  its git-diff touched-method comparison, exactly as `plan.md` states.
- Every `skills/smith-build/SKILL.md` line-number anchor `plan.md` cites
  (§3.1 line 229, §3.2 line 234, §3.3 line 246, §3.5/§3.6/§3.7 at
  252/328/426, §5.3 line 580, §5.3.1 lines 616-780, the "Include a Clean
  Code Review" paragraph at line 782, §5.4 at line 801, "Supply-Chain
  Review" ending line 885, "Release notes" at line 887) — all confirmed
  byte-exact this worktree.
- Every `skills/smith-bugfix/SKILL.md` anchor (§5.1 lines 289-291, §5.2
  293-296, §5.3 298-301, §5.4 302-305) confirmed exact, including the
  hardcoded fallback text matching FR-7's claimed byte-for-byte wording.
- `templates/config.default.json` key order, `skills/smith/SKILL.md`'s
  `supply_chain` seed block position (lines 333-363, immediately followed
  by "Copy from `~/.claude/skills/smith/`:" at 365), and
  `skills/smith-update/SKILL.md`'s `§5.1c`/`§5.1d`/`§5.2` positions (307,
  346-382, 384) — all confirmed exact.
- `scripts/parsers/meta_describe.py`'s `qualifying_methods()` signature
  and return shape match spec/plan exactly; it has NO CLI entrypoint
  (confirmed zero `__main__`/`argparse` matches), so `sys.path.insert()` +
  `import` is not merely viable but the ONLY correct mechanism — and it
  is the EXACT pattern two real production files already use
  (`describe_write.py:31,34`, `describe_discover.py:65,68`), stronger
  precedent than `plan.md` itself cited. Folded into T007/T010.
- `tests/hooks/test_config_default_seed.sh` exists with the exact
  `security_review`/`supply_chain` assertion pattern `plan.md` describes,
  giving T013 an exact insertion template.
- `tests/parsers/test_meta_describe.py` already covers `qualifying_methods()`
  (via its `_qualifying_methods` alias — confirmed
  `meta_describe.py:358`), confirming OOS-2's "already covered, no
  redundant test needed" claim; currently passes 9/9.

**Gaps found and resolved (plan.md underspecified, not wrong):**
1. **§3.1b/§3.1c position relative to the untouched §3.2 "Playwright E2E
   Tests."** `plan.md`'s Architecture Summary and file-by-file list never
   state where the two new lettered sections land relative to the
   EXISTING §3.2, which sits between the current §3.1 and §3.3. Resolved
   in T005b using this repo's own established lettered-insertion
   convention (`§5.1b`/`§5.1c`/`§5.1d` each insert between two adjacent
   existing numbered items without renumbering): final order is §3.1
   (Testing) → §3.1b (Lint) → §3.1c (Typecheck) → §3.2 (Playwright,
   untouched) → §3.3 (extended) → §3.4 (new). T012 greps verify this
   ordering landed, not just that the headings exist.
2. **No single "run the whole `tests/` tree" command exists.** `plan.md`'s
   Test strategy says "run the complete `tests/` directory after all
   phases land" without naming a command. Verified: no root
   `Makefile`/test-runner exists; `python3 -m pytest` is unavailable
   (`ModuleNotFoundError`, confirmed); the only aggregate runner
   (`tests/e2e/run-all.sh`) is scoped to `tests/e2e/` only. T014 resolves
   this by enumerating every test file with its correct per-extension
   invocation (`bash` for `.sh`, `python3` directly for `.py`, dual-shell
   re-run where NFR requires it), matching `CONTRIBUTING.md`'s own
   documented convention rather than assuming a runner that doesn't exist.

**Noted caveat (not a correction, does not block tasking):**
- `.smith/vault/explore/explore-2026-09-14-quality-metrics-pack.md`, cited
  repeatedly in `spec.md`/`plan.md` as the pre-feature exploration report
  whose 7 findings are binding constraints, does NOT exist in this
  worktree. Explained, not alarming: `.smith/` is gitignored local
  runtime state (confirmed `.gitignore:2`), and this worktree
  (`/tmp/smith-quality-metrics-pack`, confirmed a real git worktree of
  `smith-repo` via its `.git` gitlink file, branch `57-quality-metrics-pack`
  tracking `origin/main` at `87decda` — feature #56 already merged,
  matching `plan.md`'s own claim) carries only tracked files — a fresh
  worktree never inherits another session's local gitignored vault state.
  The 5 gate decisions the exploration informed are independently
  preserved and auditable in `questions.md` (status ANSWERED), so this
  absence does not undermine any FR/task above.

### FR / NFR → task traceability

| Requirement | Task(s) |
|---|---|
| FR-1/FR-2 (§3.1 Testing, config-driven + verbatim fallback) | T005a |
| FR-3 (NEW §3.1b Lint, skip when absent) | T005b |
| FR-4 (NEW §3.1c Typecheck, skip when absent) | T005c |
| FR-5 (§3.3 extended to cover §3.1b/§3.1c + timeouts) | T005d |
| FR-6/FR-7 (`smith-bugfix` §5.3 Lint generalized + fallback) | T009 |
| FR-8 (`smith-bugfix` gains ONLY Lint; no coverage/function-length) | T009; verified T012 |
| FR-9..FR-14 (NEW §3.4 Coverage Check, regex catalogue, timeout) | T006 |
| FR-15..FR-18 (NEW §5.3.2 Function-Length Scan, two-tier) | T007; tested T010; verified T015 |
| FR-19/FR-20 (§5.4 PR sections, ordering) | T008 |
| FR-21/FR-22 (`quality` config key + three-site seeding) | T001, T002, T003; verified T004 |
| NFR-1 (bash+zsh, python3-only) | T005-T010 |
| NFR-2 (no new block/terminate path anywhere) | T001, T006, T007; verified T012 |
| NFR-3 (every invocation timeout-wrapped) | T005a, T006, T009 |
| NFR-4 (no smith-implement/parser changes) | verified T012 |
| NFR-5 (fully non-interactive) | T005-T009 |

### Plan file-by-file → task coverage

Every file in `plan.md`'s "Exact file-by-file change list" has at least
one task: `skills/smith-build/SKILL.md` (T005-T008), `skills/smith-bugfix/SKILL.md`
(T009), `templates/config.default.json` (T001), `skills/smith/SKILL.md`
(T002), `skills/smith-update/SKILL.md` (T003), `CHANGELOG.md` (T011),
`tests/skills/test_smith_build_function_length_scan.sh` (T010). One
additional file beyond `plan.md`'s own list is touched, justified above as
a regression-coverage addition: `tests/hooks/test_config_default_seed.sh`
(T013, mirroring features 55/56's own identical precedent).

### Gate-answer (questions.md, 5/5 ANSWERED via delegation) non-contradiction check

- **Q1 (generalize §3.1/§5.3 in place, verbatim fallback):** T005a/T009
  both implement config-driven-with-verbatim-fallback, not a parallel
  second code path.
- **Q2 (`quality` sibling key, not nested):** T001 adds it as a top-level
  sibling; T004/T012 grep-confirm no `enforcement_tier` leak.
- **Q3 (50/100 soft/decompose, config-overridable):** T007/T010 implement
  and test the exact two-tier default with override support.
- **Q4 (built-in regex catalogue + override, unparsed never fails):** T006
  implements the fixed-order catalogue with override-first + disclosure.
- **Q5 (smith-build full pack; smith-bugfix Lint-only; smith-implement
  none):** T005-T008 give `smith-build` the full pack; T009 gives
  `smith-bugfix` ONLY Lint; no task in any phase touches
  `skills/smith-implement/SKILL.md` (re-confirmed absent from
  `git diff --name-only` in T012).
