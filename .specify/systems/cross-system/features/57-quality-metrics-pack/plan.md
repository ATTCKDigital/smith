---
feature: 57-quality-metrics-pack
primary_system: cross-system
branch: 57-quality-metrics-pack
status: planned
---

# Implementation Plan: Quality Metrics Pack for `smith-build` & `smith-bugfix`

## Technical Context

- **Repo**: Smith skills distribution (this repo). No application
  runtime — every deliverable is markdown skill prose (`skills/
  smith-build/SKILL.md`, `skills/smith-bugfix/SKILL.md`, config-seeding
  steps in `skills/smith/SKILL.md` and `skills/smith-update/SKILL.md`),
  one config key (`templates/config.default.json`), a new test file, and a
  `CHANGELOG.md` entry. No new Python orchestrator script is introduced —
  the Function-Length Scan calls `scripts/parsers/meta_describe.py`'s
  `qualifying_methods()` inline, exactly the way §5.3.1's existing
  Description Coverage Scan already imports that same module's parsing
  helpers inline.
- **Features 54/55/56 are already shipped and merged** in this worktree —
  `smith-build`'s Phase 3.5/3.6/3.7, its §5.3/§5.3.1 pre-PR scans, its
  `security_review`/`supply_chain` config keys, and their three-site
  seeding (`templates/config.default.json` + `skills/smith/SKILL.md` +
  `skills/smith-update/SKILL.md` §5.1c/§5.1d) all exist exactly as
  described below. This plan reuses those real, on-disk conventions
  throughout, not a projected design.
- **No `constitution.md` exists in this repo** — matching features
  53/54/55/56's own plan.md files' identical observation.
- **This is a smaller feature than 54/55/56**: it adds no new top-level
  `## Phase N:` to `smith-build`'s sequence (every change is a new or
  generalized section inside the EXISTING Phase 3 and Phase 5) and
  introduces no new Python file. This plan folds the contracts a sibling
  feature would put in a separate `data-model.md` into this plan's own
  §Contracts section below, per the task's explicit small-feature framing.
- **Endpoint — RESOLVED**: the questions gate closed 2026-09-14
  (`questions.md`, status ANSWERED) with all five named gate decisions
  accepted exactly as recommended, and `spec.md`'s own Assumptions (A-5)
  record each as an outcome, not a recommendation. This plan's content is
  written as concrete and unconditional, using each recommendation as the
  working default — nothing below is conditional on a re-opened gate.

## Constitution Gates

**N/A — no `constitution.md` or `.specify/memory/constitution.md` exists in
this repo, so there are no constitution-derived gates to check.** File-size
discipline is enforced via this plan's own File Size Policy section
instead, the same substitution features 53-56 already used.

## Architecture Summary

Six section-level changes inside `skills/smith-build/SKILL.md`'s existing
Phase 3 and Phase 5 (no new `## Phase N:` heading — spec FR-1..FR-20):

1. **§3.1 "Unit Tests" → §3.1 "Testing"** (generalized in place, FR-1/
   FR-2) — reads `quality.test`; each command runs via `python3
   subprocess.run(..., timeout=quality.timeout_seconds)` (the identical
   mechanism `dependency-scan.py`'s Sub-layer D established, feature 56);
   absent/empty → the verbatim two-bullet legacy fallback runs unchanged.
2. **NEW §3.1b "Lint"** (FR-3) — reads `quality.lint`; skipped entirely
   when absent (no legacy fallback exists here).
3. **NEW §3.1c "Typecheck"** (FR-4) — reads `quality.typecheck`; skipped
   entirely when absent (same reasoning as §3.1b).
4. **§3.3 "Test Failure Handling" extended** (FR-5) — its existing
   bounded-retry/log-and-continue text now explicitly names §3.1b/§3.1c
   failures and any per-command timeout as covered by the same bound, no
   new retry loop introduced.
5. **NEW §3.4 "Coverage Check"** (FR-9..FR-14), positioned after §3.3 and
   before Phase 3.5 — runs `quality.coverage.command` once (skipped
   entirely when absent), matches its output against
   `quality.coverage.regex` (tried first, when configured) or the
   built-in three-pattern catalogue (§Contracts below), compares the
   result to `quality.coverage.minimum_percent` when configured, and
   writes `/tmp/smith-build-coverage-findings.txt`.
6. **NEW §5.3.2 "Pre-PR Function-Length Scan"** (FR-15..FR-18),
   immediately after the existing §5.3.1 — reuses `/tmp/smith-build-
   changed.txt` (from §5.3), the same extension filter and excludes
   §5.3/§5.3.1 already use, and the same parser-resolution idiom §5.3.1
   already uses, calling `qualifying_methods(parsed,
   threshold=quality.function_length.soft)` unchanged and bucketing each
   returned entry by `body_lines` against `quality.function_length.soft`/
   `.decompose`. Writes `/tmp/smith-build-function-length-findings.txt`.

Plus §5.4 PR template gains two new conditional sections, "Function Length
Warnings" and "Quality Metrics" (FR-18..FR-20, §Contracts below), appended
after the existing "Supply-Chain Review" section and before "Release
notes" — the same append-after-the-newest-existing-section convention
features 54/55/56 each used for their own sections.

One section-level change inside `skills/smith-bugfix/SKILL.md`'s existing
Phase 5:

7. **§5.3 "Lint" → generalized in place** (FR-6/FR-7) — reads
   `quality.lint`; absent/empty → the verbatim two-bullet legacy fallback
   runs unchanged. `smith-bugfix`'s §5.1 "Unit Tests" is untouched; no
   coverage check or function-length scan is added to `smith-bugfix`
   (FR-8) — it gains no PR-body advisory sections of its own from this
   feature.

Plus the `quality` config key (FR-21) and its three-site non-destructive
seeding (FR-22): `templates/config.default.json`, `skills/smith/SKILL.md`'s
init scaffold, and a new `skills/smith-update/SKILL.md` §5.1e.

## Reuse-before-create (exact components reused, not reinvented)

- **`python3 subprocess.run(..., timeout=N)`** (feature 56's `research.md`
  §7.4, already decided and justified there) — reused verbatim as the
  timeout mechanism for every `quality.*` command and
  `quality.coverage.command` invocation (FR-1/FR-3/FR-4/FR-14), because a
  shell `timeout`/`gtimeout` wrapper is confirmed absent on the reference
  dev machine and `python3` is already a hard dependency of this
  pipeline's own scripts.
- **§3.3's existing bounded-retry/log-and-continue text** (`skills/
  smith-build/SKILL.md`, current §3.3) — extended in scope (FR-5) rather
  than duplicated with a second, parallel retry mechanism for §3.1b/§3.1c.
- **§5.3.1's inline-python parser-resolution idiom** (`skills/smith-build/
  SKILL.md`, current §5.3.1: installed-path-preferred → `~/.smith/scripts`
  → repo-dev-fallback `scripts/parsers/`) — reused verbatim for §5.3.2's
  own parser resolution, not a second copy of the same candidate-path
  logic.
- **`scripts/parsers/meta_describe.py`'s `qualifying_methods(parsed,
  threshold)`** — called directly and unchanged (FR-16); the function
  already returns exactly the shape this scan needs (`id`, `name`,
  `scope`, `line`, `end_line`, `body_lines`), derived from the next
  entry's start line, sorted by `line` — no new parser field, no forked
  copy of this derivation logic (exploration finding 1, OOS-2).
- **The low-severity-folding convention** (`skills/smith-build/SKILL.md`'s
  existing "+ N low-severity notes" pattern, §3.5/§3.6/§3.7) — reused
  verbatim in shape (not name) for soft-tier function-length findings:
  "+ N soft-tier warnings" (FR-17).
- **The `§5.1c`/`§5.1d` → `§5.1e` non-destructive config-seeding idiom**
  (`skills/smith/SKILL.md`, `skills/smith-update/SKILL.md`) — the exact
  python3 read-modify-write heredoc (load-if-exists-else-`None`, merge
  only if the top-level key is entirely absent, preserve every other key,
  re-dump with `indent=2` + trailing newline), retargeted from
  `supply_chain` to `quality` (FR-22).
- **The append-after-the-newest-existing-PR-section convention** (§5.4,
  every prior feature 54/55/56 used it for its own section) — reused for
  both of this feature's two new sections (FR-19/FR-20).
- **`tests/skills/test_smith_build_coverage_flag.sh`'s harness shape**
  (existing, tests §5.3.1's inline algorithm) — this is the DIRECT
  precedent this plan's own new test file follows; see Test Strategy
  below.

## File Size Policy

No new source file crosses the 300-line soft ceiling this repo's prior
features already apply absent a hard constitution gate:

- `skills/smith-build/SKILL.md`'s net new prose across §3.1b, §3.1c, §3.4,
  §5.3.2, and the two §5.4 template additions targets roughly 90-130 lines
  total — smaller than Phase 3.6's own ~95-line precedent for a single new
  phase, appropriate given this feature adds section-level content inside
  existing phases rather than a new phase with its own decision table.
- `skills/smith-bugfix/SKILL.md`'s §5.3 generalization is a small, local
  edit (~15-20 lines net) to one existing section.
- The new test file (`tests/skills/test_smith_build_function_length_scan.sh`,
  see Test Strategy) targets ≤180 lines, sized against its direct sibling
  `tests/skills/test_smith_build_coverage_flag.sh` (~280 lines, but that
  file exercises a git-diff-based touched-method comparison this scan does
  NOT need — function-length findings are evaluated against the CURRENT
  file content only, no prior-commit comparison, so the new test's fixture
  setup is simpler).

## Contracts

### `quality` config schema (`.smith/config.json`, `templates/config.default.json`)

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
- `test`/`lint`/`typecheck`: arrays of shell command strings. Empty/absent
  → skip (typecheck, lint in `smith-build`) or legacy fallback (test in
  `smith-build`, lint in `smith-bugfix` — the only two arrays with a
  pre-existing hardcoded fallback, FR-2/FR-7).
- `coverage.command`: a single shell command string, or `null`
  (skip the Coverage Check step entirely — FR-9).
- `coverage.minimum_percent`: a number, or `null` (no threshold — FR-12,
  informational-only when a percent still parses).
- `coverage.regex`: a single regex string with exactly one capture group
  for the percentage, or `null` (fall through to the built-in catalogue —
  FR-10).
- `function_length.soft`/`.decompose`: integers, default 50/100 (FR-16).
- `timeout_seconds`: integer seconds, default 120, applied per-command
  (FR-1/FR-14) — distinct from and independent of
  `supply_chain.timeout_seconds` (60, per-scanner-per-manifest).
- `excludes`: glob array, merged with the built-in exclude list
  (`vendor/`, `node_modules/`, `.venv/`, `dist/`, `build/`, `.smith/`)
  §5.3.2 already inherits from §5.3/§5.3.1 — present for schema symmetry
  with `security_review.excludes`/`supply_chain.excludes`; a plan-level
  mechanical addition, not one of the five named gate items
  (`questions.md`'s own "Plan-level mechanical resolutions" note).

### Coverage regex catalogue (tried in this fixed order; `coverage.regex` tried first when set)

| Tool shape | Pattern | Capture |
|---|---|---|
| pytest-cov `TOTAL` line | `TOTAL\s+\d+\s+\d+\s+(\d+(?:\.\d+)?)%` | percent |
| jest/istanbul `text-summary` `Lines` line | `Lines\s*:\s*(\d+(?:\.\d+)?)%` | percent |
| `go test -cover` | `coverage:\s*(\d+(?:\.\d+)?)%\s+of statements` | percent |

No match from any of the four (override + 3 built-in) → "coverage output
unparsed" disclosure (FR-13), never a failure.

### `/tmp` handoff files (this feature's own, distinct from 54/55/56's)

- `/tmp/smith-build-coverage-findings.txt` — written by §3.4. Empty/absent
  when the step didn't run (FR-9) or ran and found nothing to report
  (at/above minimum, or no minimum configured with nothing else to
  disclose). One line per finding: `<percent>% < <minimum>% (command:
  <excerpt>)`; an unparsed-output disclosure line when applicable (FR-13).
- `/tmp/smith-build-function-length-findings.txt` — written by §5.3.2.
  Decompose-tier lines: `- <path>:<line> — <name> (<body_lines> lines,
  exceeds <decompose> — decompose)`. Exactly one trailing `+ N soft-tier
  warnings` line when N>0, omitted when N=0 (FR-17).

### PR-body section formats (§5.4, both appended after "Supply-Chain
Review", before "Release notes" — FR-19/FR-20, in this relative order)

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

### No-terminate contract

Identical in shape to Phase 3.7's own (feature 56): no finding this
feature produces, from §3.1b/§3.1c/§3.4/§5.3.2, at any severity, blocks,
delays, or terminates a build or bugfix. §3.1/§3.1b/§3.1c command
failures/timeouts are the one exception folded into EXISTING behavior —
they route through §3.3's pre-existing bounded-retry/log-and-continue
handling (FR-5), which itself never hard-stops a build; it logs and
continues after 3 attempts, exactly as it already does for §3.1/§3.2
today.

## Exact file-by-file change list

### MODIFIED

| File | Change |
|---|---|
| `skills/smith-build/SKILL.md` | **(1)** §3.1 "Unit Tests" → "Testing", generalized in place (FR-1/FR-2). **(2)** NEW §3.1b "Lint" (FR-3). **(3)** NEW §3.1c "Typecheck" (FR-4). **(4)** §3.3 "Test Failure Handling" text extended to name §3.1b/§3.1c (FR-5) — no heading/number change. **(5)** NEW §3.4 "Coverage Check", after §3.3, before `## Phase 3.5:` (FR-9..FR-14). **(6)** NEW §5.3.2 "Pre-PR Function-Length Scan", immediately after the existing §5.3.1, before the "Include a **Clean Code Review** section..." paragraph (FR-15..FR-18). **(7)** §5.4 PR body template gains "Function Length Warnings" and "Quality Metrics" sections, appended after "Supply-Chain Review", before "Release notes" (FR-19/FR-20). No existing `## Phase N:` heading is added, renumbered, or removed. |
| `skills/smith-bugfix/SKILL.md` | §5.3 "Lint" generalized in place (FR-6/FR-7). §5.1 "Unit Tests", §5.4 "Test Failure Handling", and the PR body template (§7.3) are untouched — `smith-bugfix` gains no new PR-body section from this feature (FR-8). |
| `templates/config.default.json` | New top-level `quality` key (§Contracts) inserted after `supply_chain`'s closing `}` and before `context_budget`, matching the file's existing insertion-order convention (each feature's key appended after the prior feature's). |
| `skills/smith/SKILL.md` | New unlettered paragraph + python3 heredoc, mirroring the existing `supply_chain` seed block exactly, retargeted at `quality`, placed immediately after that block's closing `fi` and before "Copy from `~/.claude/skills/smith/`:". |
| `skills/smith-update/SKILL.md` | New `### 5.1e Seed \`quality\` in \`.smith/config.json\`` inserted immediately after the existing `### 5.1d` step and before `### 5.2`, same three-line decision rule (key present → no-op; file exists, key absent → merge; file absent → leave absent) and the same python3 heredoc shape as `5.1d`, retargeted. |
| `CHANGELOG.md` | New `[Unreleased]` → `### Added` entry, written LAST after every other file's changes are final, describing the two generalized command surfaces (test/lint fallback preservation), the new lint/typecheck/coverage/function-length checks, the `quality` config key, and the explicit flag-only posture. |

### NEW

| File | Purpose |
|---|---|
| `tests/skills/test_smith_build_function_length_scan.sh` | Companion test for §5.3.2's algorithm (see Test Strategy) — direct sibling of `tests/skills/test_smith_build_coverage_flag.sh`, following its exact structural pattern: a `mktemp -d` throwaway git repo, the scan algorithm reproduced as a reusable `run_function_length_scan` bash function calling `qualifying_methods()` from the REAL `scripts/parsers/meta_describe.py` (imported via `python3 -c`, not re-derived), fixture Python files carrying one function at/above 100 lines, several in the 50-99 range, and one under 50 (should not appear at all), `PASS`/`FAIL`/summary-line assertions. |

No `scripts/security/*`, `scripts/parsers/*`, or `hooks/*` file is created
or modified by this feature (NFR-4).

## Phased ordering

1. **`quality` config schema + three-site seeding, first.**
   `templates/config.default.json`, `skills/smith/SKILL.md`'s new seed
   paragraph, and `skills/smith-update/SKILL.md`'s new §5.1e ship together
   — before any `smith-build`/`smith-bugfix` prose references the
   `quality` key, mirroring feature 56's own "config before the prose that
   reads it" sequencing (its own phase 5, reversed here because this
   feature's config surface is simpler and has no orchestrator scripts
   gating it).
2. **`skills/smith-build/SKILL.md` §3.1/§3.1b/§3.1c/§3.3-extension +
   §3.4, as one unit.** All four Phase-3 changes ship together — §3.3's
   extended text references §3.1b/§3.1c by name, so drafting them
   separately would leave an internally inconsistent half-shipped file
   for the same reason features 54/55/56 each gave for shipping their own
   phase+template changes as one unit.
3. **`skills/smith-build/SKILL.md` §5.3.2 + the new test file, together.**
   The test file is written against the FINAL §5.3.2 algorithm text, not
   an interim draft, so it is sequenced immediately after (not before or
   parallel to) §5.3.2's prose — inverse of feature 56's own "scripts
   before prose" ordering, appropriate here because §5.3.2's "script" IS
   its SKILL.md prose (no separate `.py` file exists to write first).
4. **`skills/smith-build/SKILL.md` §5.4 PR template additions.**
   Sequenced after phases 2-3 so both new sections' "include-if-non-empty"
   conditions correctly name the exact `/tmp` file paths §3.4 and §5.3.2
   actually write.
5. **`skills/smith-bugfix/SKILL.md` §5.3 generalization.** Independent of
   phases 2-4 (bugfix's lint generalization doesn't touch anything
   `smith-build`-specific) but sequenced after phase 1 (the `quality` key
   it reads must already be seedable) and before `CHANGELOG.md` so the
   changelog entry can describe both skills' changes as final.
6. **`CHANGELOG.md`.** Written last, after phases 1-5 are final.

## Test strategy

- **`tests/skills/test_smith_build_function_length_scan.sh` (primary new
  test, decided over an e2e-grep-only approach).** Justification: this
  repo has a DIRECT, already-established precedent for testing an inline
  SKILL.md bash+python algorithm exactly this shape —
  `tests/skills/test_smith_build_coverage_flag.sh` reproduces §5.3.1's
  algorithm inside the test file itself (a `run_coverage` bash function)
  and exercises it against a real `mktemp -d` git-repo fixture, asserting
  on the resulting `/tmp` scratch file. §5.3.2 is explicitly this
  feature's own §5.3.1 sibling (spec Overview, exploration finding 4), so
  the consistent, already-proven choice is the SAME pattern, in the SAME
  `tests/skills/` directory, NOT a `tests/parsers/` unit test (which would
  test `qualifying_methods()` itself — already covered by the EXISTING
  `tests/parsers/test_meta_describe.py`, so re-testing that function's
  correctness here would be redundant) and NOT deferred to grep-only
  verification (which is what §5.3.1's OWN test file already proves this
  repo does NOT settle for, once a §5.3-family scan exists). The new
  test's `run_function_length_scan` function calls the REAL
  `qualifying_methods()` via `python3 -c "import sys;
  sys.path.insert(0, 'scripts/parsers'); import meta_describe as md; ..."`
  rather than re-deriving body-length logic, so the only logic actually
  under test is this feature's OWN new code — threshold bucketing
  (soft/decompose) and the file:line + fold-soft-tier rendering — not a
  duplicate of `qualifying_methods()`'s own already-tested behavior.
  Cases: one function ≥100 lines listed individually with correct
  `path:line`/length; three functions in the 50-99 range folded into one
  "+ 3 soft-tier warnings" line; one function <50 lines absent from output
  entirely; an excluded-path file (e.g. under `node_modules/`) produces no
  findings even with an oversized function inside it; a
  `quality.function_length` override (e.g. soft=30/decompose=60) correctly
  shifts which functions land in which tier.
- **`skills/smith-build/SKILL.md` §3.1/§3.1b/§3.1c/§3.4 and `skills/
  smith-bugfix/SKILL.md` §5.3 are prose-only changes with no new standalone
  script** — consistent with §5.3.1's own precedent (no dedicated unit
  test exists for §5.3.1's shell orchestration itself, only for the
  underlying parser it calls), these are verified via **prose-consistency
  greps** (run after the prose lands), not a dedicated bash test:
  `grep -n "^### 3.1" skills/smith-build/SKILL.md` (confirms the rename),
  `grep -n "^### 3.1b\|^### 3.1c\|^### 3.4" skills/smith-build/SKILL.md`
  (confirms all three new sections exist), `grep -c "quality\.test\|
  quality\.lint\|quality\.typecheck" skills/smith-build/SKILL.md` (expect
  ≥3 — one config-key reference per new/generalized step),
  `grep -n "quality\.lint" skills/smith-bugfix/SKILL.md` (confirms §5.3's
  generalization), `grep -c "Function Length Warnings\|Quality Metrics"
  skills/smith-build/SKILL.md` (expect ≥4 — each section name appears once
  as a producing-step reference and once as a PR-template heading).
- **Config-seeding regression** — `tests/hooks/test_config_default_seed.sh`
  (existing) is expected to keep passing UNMODIFIED; a new case is added
  verifying the fresh-project byte-for-byte-copy path now includes
  `quality`.
- **Full-suite regression** — run the complete `tests/` directory after
  all phases land, confirming zero regressions in unrelated scripts this
  feature does not touch (`scripts/security/*`, `scripts/parsers/parse-
  python.py`/`parse-js.js`, every hook, `smith-implement`'s own SKILL.md —
  NFR-4's "read-only neighbors" discipline).
- **No live network calls, no Docker, no real `pytest`/`npm`/`go`
  invocation in any test** — the Coverage Check step (§3.4) is NOT
  covered by a dedicated new test file in this plan (unlike the
  Function-Length Scan): its only new LOGIC is regex matching against
  FIXED, already-known-shape sample output strings (§Contracts' three
  patterns) and a numeric comparison — both trivially verified by the
  prose-consistency greps above plus a manual dry-run against the three
  sample strings during implementation review, not warranting a fourth new
  test file for a feature whose own task framing is "small,
  prose-level." If a future feature grows the coverage catalogue further,
  a dedicated `tests/skills/test_smith_build_coverage_check.sh` (same
  `run_*`-function pattern) is the natural next step — flagged here as a
  deliberate v1 scope call, not an oversight.

## Rollout notes

- No `scripts/install.sh` change is needed — this feature ships no new
  `.sh`/`.py` files under `scripts/`, so there is nothing for that
  stanza to newly copy (unlike feature 56, which had a real gap there).
- The `quality` checks run on every `smith-build`/`smith-bugfix`
  invocation from the moment this ships, but every array/threshold
  defaults to empty/`null`/its stated default — a project sees ZERO new
  command executions until it opts in by populating `quality.test`/
  `lint`/`typecheck`/`coverage.command`, except for the two legacy-fallback
  paths (FR-2/FR-7), which run exactly what they already ran before this
  feature shipped.
- Distributed via the standard `/smith-update` path — since no `scripts/`
  file changes, `/smith-update`'s existing `§5.1`-family refresh of
  `skills/`/`templates/` is the only distribution mechanism this feature
  needs; §5.1e (new) handles the config-seeding half.

## Spec-plan tensions — RESOLVED, folded into the sections above

None of these were contradictions within spec.md itself — they were
plan-level implementation-shape decisions this feature's own task framing
explicitly asked this plan to make and justify (not gate matters — none of
the five `questions.md` items cover them):

1. **Coverage step placement (§3.4 vs. a lettered §3.1d).** Resolved: a
   new numbered §3.4, not a lettered insertion between §3.1 and §3.2 —
   folded into "Architecture Summary" item 5 and the file-by-file list.
   Rationale: the coverage check is not a sibling of the §3.1/§3.1b/§3.1c
   command-running triad (it runs a DIFFERENT command with different
   semantics — parse-and-compare, not run-and-retry), and letters are
   reserved in this repo's convention for inserting BETWEEN two existing,
   adjacent numbered items without renumbering (`§5.1b`/`§5.1c`/`§5.1d`);
   §3.4 sits AFTER the existing §3.1-§3.3 sequence with nothing after it
   to renumber, so a plain new number is both correct and simpler.
2. **Function-length scan test file choice.** Resolved: a dedicated
   `tests/skills/test_smith_build_function_length_scan.sh`, not a
   `tests/parsers/` unit test and not grep-only verification — folded into
   Test Strategy above with its full justification (the direct
   `test_smith_build_coverage_flag.sh` precedent).
3. **`quality.excludes` schema field.** Resolved: added for schema
   symmetry with `security_review`/`supply_chain`, defaulting to `[]` —
   already folded into §Contracts and noted as a plan-level mechanical
   resolution in `questions.md`, not a sixth gate item.
4. **PR-section relative order (Function Length Warnings vs. Quality
   Metrics).** Resolved: Function Length Warnings first, Quality Metrics
   second, both after Supply-Chain Review — folded into FR-20 and
   §Contracts, ordered by which producing step runs closer to §5.4 in the
   pipeline.
