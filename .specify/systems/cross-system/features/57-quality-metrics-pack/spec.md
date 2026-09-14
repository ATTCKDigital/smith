---
feature: 57-quality-metrics-pack
primary_system: cross-system
also_affects: []
branch: 57-quality-metrics-pack
created: 2026-09-14
status: in-progress
answers_applied: 2026-09-14
---

# Quality Metrics Pack for `smith-build` & `smith-bugfix`

## Overview

`smith-build`'s §3.1 "Unit Tests" and `smith-bugfix`'s §5.3 "Lint" hardcode
one past client project's directory shape (`services/command-center`,
`services/<service>`) directly into otherwise-generic skill prose. Neither
skill has any notion of a per-project lint or typecheck step, code-coverage
visibility, or oversized-function visibility (`smith-build` already flags
oversized *files* via §5.3, but nothing flags an oversized *function* inside
an otherwise reasonably-sized file). This feature adds a config-driven
**Quality Metrics Pack**: a generalized, `.smith/config.json`-driven test/
lint/typecheck command surface for both skills, a coverage-percent advisory
check for `smith-build`, and a function-length advisory scan for
`smith-build`, plus the config seeding these need. Every new check is
advisory only — flag, never block — matching the posture features 54, 55,
and 56 already established for this pipeline's non-secret findings.

It is informed by a pre-feature exploration
(`.smith/vault/explore/explore-2026-09-14-quality-metrics-pack.md`, status:
clear, 7 findings, no blocking conflicts) whose findings are binding design
constraints encoded throughout this spec (traced in this feature's
requirements checklist).

**Terminology used throughout this spec:**
- **Quality command** — one shell command string configured under
  `.smith/config.json`'s `quality.test`, `quality.lint`, or
  `quality.typecheck` array. Each array may hold zero or more commands; each
  configured command is run independently, bounded by
  `quality.timeout_seconds` (default 120).
- **Legacy fallback** — the CURRENT hardcoded bullet-list behavior of
  `smith-build` §3.1 (`quality.test`) and `smith-bugfix` §5.3
  (`quality.lint`) — the only two places this feature touches that already
  had hardcoded commands before this feature shipped. When the
  corresponding config array is absent, that legacy fallback runs verbatim,
  unchanged, byte-for-byte — this feature's generalize-in-place rule
  produces zero behavior change for a project relying on the pre-existing
  hardcoded text.
- **Coverage check** — the new, optional `smith-build`-only step that runs
  `quality.coverage.command` (when configured), parses a percentage from its
  output via the built-in regex catalogue or a configured override, and
  compares it to `quality.coverage.minimum_percent`.
- **Function-Length Scan** — the new, `smith-build`-only §5.3.2 pre-PR scan,
  sibling to the existing §5.3 (File-Size) and §5.3.1 (Description Coverage)
  scans, that flags functions/methods whose body exceeds
  `quality.function_length`'s soft (default 50 lines) or decompose (default
  100 lines) threshold, reusing `scripts/parsers/meta_describe.py`'s
  `qualifying_methods()` for body-length derivation rather than adding any
  new parser fields.
- **Advisory** — every finding this feature produces (a lint/typecheck
  command result, a coverage-below-minimum result, a function-length
  finding) is flag-only: it is written to a `/tmp` handoff file and
  surfaces in the PR body when non-empty, and it never blocks, delays, or
  terminates a build or a bugfix — this feature introduces NO new
  block/terminate path of any kind, consistent with the flag-only precedent
  Phase 3.7 (feature 56) already established, and stricter than Phase 3.6's
  own config-driven terminate path (this feature has no
  `enforcement_tier`-shaped field at all).
- **Trust domain** — every quality command (`quality.test`/`lint`/
  `typecheck`/`coverage.command`) is a shell string a project owner placed
  in their own `.smith/config.json`, executed with the same trust level as
  an npm/pnpm `package.json` "scripts" entry — code the project already
  runs routinely, not third-party or untrusted input. This feature
  documents that trust domain explicitly; it does not add a sandboxing or
  approval gate around it (exploration finding 7).

## Problem Statement

1. **Hardcoded, project-specific test/lint commands baked into generic skill
   prose.** `smith-build` §3.1 and `smith-bugfix` §5.3 both hardcode
   `services/command-center`/`services/<service>` path shapes — a leftover
   from one past client project (Armory), not a general mechanism. A
   consuming project whose layout doesn't match those exact paths gets no
   test or lint execution from these steps at all, silently.
2. **No lint or typecheck step in `smith-build` at all.** Unlike
   `smith-bugfix` (which has a §5.3 Lint step, itself hardcoded per problem
   1), `smith-build`'s Phase 3 runs only unit tests — there is no
   config-driven or hardcoded lint/typecheck execution anywhere in the
   build pipeline.
3. **No code-coverage visibility anywhere in the pipeline.** Neither skill
   surfaces a coverage percentage or compares it against any minimum — a
   build can silently ship a coverage regression with no PR-visible signal.
4. **No function-length visibility.** `smith-build` §5.3 already flags
   oversized *files*; nothing flags an oversized *function* living inside
   an otherwise reasonably-sized file, even though `scripts/parsers/
   meta_describe.py` already derives exactly the body-length data
   (`qualifying_methods()`'s next-entry-start `body_lines` field) this
   check needs, with zero parser changes required.

The exploration pass ahead of this feature
(`.smith/vault/explore/explore-2026-09-14-quality-metrics-pack.md`)
confirmed all four gaps are unaddressed today, found no parser-schema
change is needed for the function-length signal (finding 1), and confirmed
the §3.1/§5.3 hardcoded commands are the same category of Armory-shaped
leftover a prior PR (#57 predecessor, cited in the exploration) already
generalized elsewhere in this pipeline (finding 2).

## User Scenarios

### US-1 — Configured `quality.test` commands run instead of the legacy fallback
```gherkin
Given `.smith/config.json` declares `quality.test: ["pytest -q", "npm run test:ci"]`
When `smith-build`'s §3.1 Testing step runs
Then each configured command runs independently, each bounded by
    `quality.timeout_seconds` (default 120)
And the legacy `services/command-center`/`services/<service>` fallback
    bullets do NOT run
```

### US-2 — Absent `quality` key preserves current behavior exactly
```gherkin
Given `.smith/config.json` has no `quality` key at all (or `quality.test` is
    absent/empty)
When `smith-build`'s §3.1 Testing step runs
Then the verbatim legacy fallback runs unchanged: `cd services/command-center
    && pnpm test` if frontend code changed, `cd services/<service> && poetry
    run pytest` if Python service code changed
And this is byte-for-byte the pre-feature behavior — zero behavior change
```

### US-3 — `smith-bugfix` §5.3 Lint generalizes the same way
```gherkin
Given `.smith/config.json` declares `quality.lint: ["ruff check src/"]`
When `smith-bugfix`'s §5.3 Lint step runs
Then the configured command runs, bounded by `quality.timeout_seconds`
And the legacy `pnpm lint`/`poetry run ruff check .` fallback does NOT run
Given `quality.lint` is instead absent
Then the legacy fallback runs verbatim, unchanged
```

### US-4 — Coverage below minimum produces a High finding, never blocks
```gherkin
Given `quality.coverage.command` is configured as `"pytest --cov=app
    --cov-report=term"` and `quality.coverage.minimum_percent` is `80`
Given the command's output contains a pytest-cov `TOTAL` line reporting 62%
When `smith-build`'s Coverage Check step runs
Then the built-in pytest-cov regex extracts `62` from the TOTAL line
And 62 < 80 produces exactly one High-severity finding, written to the
    Coverage Check's `/tmp` handoff file
And the build proceeds to Phase 3.5 exactly as if no finding existed — no
    block, no delay, no retry
```

### US-5 — Unparseable coverage output is disclosed as unparsed, never fails
```gherkin
Given `quality.coverage.command` is configured, but its output matches
    neither the built-in regex catalogue nor a configured
    `quality.coverage.regex` override
When the Coverage Check step runs
Then no percentage is extracted and no minimum-comparison finding is
    produced
And the "Quality Metrics" PR section (when otherwise non-empty for another
    reason) or a dedicated disclosure line states the output was unparsed
And this NEVER fails the build or raises an error
```

### US-6 — Function-length findings split into individual decompose-tier listings and a folded soft-tier count
```gherkin
Given a file changed on this branch contains one function with a 120-line
    body (>= the 100-line decompose threshold) and three functions each with
    a 60-70-line body (>= the 50-line soft threshold, < 100)
When `smith-build`'s §5.3.2 Function-Length Scan runs
Then the 120-line function is listed individually with its `path:line` and
    body-line count in `/tmp/smith-build-function-length-findings.txt`
And the three soft-tier functions are folded into a single trailing "+ 3
    soft-tier warnings" line, never listed individually
And when this file is non-empty, the PR body gains a "Function Length
    Warnings" section; when empty, the section is omitted entirely
```

## Functional Requirements

### Testing generalization (`smith-build` §3.1)

- **FR-1**: `smith-build`'s existing §3.1 "Unit Tests" MUST be generalized
  in place to §3.1 "Testing": when `.smith/config.json`'s `quality.test`
  array is present and non-empty, each listed command MUST run
  independently, each bounded by `quality.timeout_seconds` (default 120,
  per-command, via the same `python3 subprocess.run(..., timeout=N)`
  mechanism feature 56 established for Sub-layer D — reused here, not
  reinvented, since a shell `timeout`/`gtimeout` wrapper is confirmed
  absent on the reference dev machine).
- **FR-2**: When `quality.test` is absent, empty, or `.smith/config.json`
  itself is absent/malformed, §3.1 MUST run the verbatim legacy fallback —
  `cd services/command-center && pnpm test` if frontend code changed,
  `cd services/<service> && poetry run pytest` if Python service code
  changed — unchanged from this feature's pre-existing text. This is a
  zero-behavior-change guarantee for any project not yet configuring
  `quality.test`.
- **FR-3**: A NEW §3.1b "Lint" step MUST run each `quality.lint` command
  (same per-command timeout as FR-1) when configured. `smith-build` has no
  pre-existing hardcoded lint step, so when `quality.lint` is absent or
  empty, this step is skipped entirely — there is no legacy fallback to run
  here, unlike FR-2.
- **FR-4**: A NEW §3.1c "Typecheck" step MUST run each `quality.typecheck`
  command (same per-command timeout as FR-1) when configured, skipped
  entirely when absent or empty — no legacy fallback exists for
  `smith-build` typecheck either (FR-3's reasoning applies identically).
- **FR-5**: §3.3 "Test Failure Handling"'s existing bounded-retry/
  log-and-continue behavior (up to 3 attempts, then log the failure and
  continue) MUST extend to cover §3.1b/§3.1c command failures and any
  per-command timeout (FR-1/FR-3/FR-4) identically to how it already
  covers §3.1/§3.2 failures — a timeout is treated as a failed attempt for
  this purpose, not a new, separate blocking condition.

### Lint generalization (`smith-bugfix` §5.3)

- **FR-6**: `smith-bugfix`'s existing §5.3 "Lint" MUST be generalized in
  place: when `quality.lint` is present and non-empty, each listed command
  runs (same per-command timeout as FR-1). This is the ONLY step
  `smith-bugfix` gains from this feature — its §5.1 "Unit Tests" step is
  unmodified and out of scope (OOS-1's sibling reasoning: `smith-bugfix`
  stays intentionally lightweight, matching features 55/56's own
  bugfix-exclusion precedent for their heavier passes).
- **FR-7**: When `quality.lint` is absent, empty, or config is
  absent/malformed, `smith-bugfix` §5.3 MUST run the verbatim legacy
  fallback — `cd services/command-center && pnpm lint` if frontend,
  `cd services/<service> && poetry run ruff check .` if Python — unchanged
  from this feature's pre-existing text (zero behavior change, mirroring
  FR-2).
- **FR-8**: `smith-bugfix` gains NO coverage check and NO function-length
  scan in this version — both are `smith-build`-only (FR-9..FR-16 below);
  `smith-bugfix` has no equivalent pre-PR scan slot and no PR-body
  advisory-section mechanism to attach either to without growing its own,
  separate reporting surface, which this feature does not introduce.

### Coverage check (`smith-build`-only)

- **FR-9**: A NEW `smith-build` step, §3.4 "Coverage Check", positioned
  after §3.3 (Test Failure Handling) and before Phase 3.5, MUST run
  `quality.coverage.command` exactly once, only when that key is
  configured (non-empty string) — when absent, this step is skipped
  entirely, no `/tmp` handoff file is written, and no PR section can ever
  appear for it on that build.
- **FR-10**: The command's combined stdout+stderr MUST be matched against a
  built-in regex catalogue, tried in this fixed order until one matches: a
  pytest-cov `TOTAL` line (`TOTAL\s+\d+\s+\d+\s+(\d+(?:\.\d+)?)%`), a
  jest/istanbul `text-summary` `Lines` line (`Lines\s*:\s*(\d+(?:\.\d+)?)%`),
  and a `go test -cover` line (`coverage:\s*(\d+(?:\.\d+)?)%\s+of
  statements`). When `quality.coverage.regex` is configured, it MUST be
  tried FIRST, before the built-in catalogue, and must supply exactly one
  capture group for the percentage.
- **FR-11**: When a percentage is successfully extracted and
  `quality.coverage.minimum_percent` is configured, and the extracted
  percentage is below that minimum, exactly one High-severity finding MUST
  be produced (`<percent>% < <minimum>%`, command excerpt, no `path:line`
  — this finding is coverage-run-scoped, not file-scoped), written to
  `/tmp/smith-build-coverage-findings.txt`.
- **FR-12**: When a percentage is successfully extracted but
  `quality.coverage.minimum_percent` is absent, the percentage MUST still
  be reported informationally in the "Quality Metrics" PR section (FR-17)
  when that section is otherwise included for another reason, or via its
  own minimal disclosure — no finding is produced in this case, since there
  is no configured threshold to violate.
- **FR-13**: When no regex (override or catalogue) matches the command's
  output, this MUST be disclosed as "coverage output unparsed" — never
  treated as a failure, never blocks or retries, and never silently
  omitted from disclosure when the "Quality Metrics" section is otherwise
  rendered.
- **FR-14**: `quality.coverage.command`'s invocation MUST use the same
  `quality.timeout_seconds`-bounded `subprocess.run(..., timeout=N)`
  mechanism as FR-1; a timeout is treated identically to unparseable
  output (FR-13) — disclosed, never a build failure.

### Function-Length Scan (`smith-build`-only, §5.3.2)

- **FR-15**: A NEW `smith-build` §5.3.2 "Pre-PR Function-Length Scan",
  sibling to and positioned immediately after §5.3.1 (Description Coverage
  Scan), MUST reuse `/tmp/smith-build-changed.txt` (populated by §5.3),
  the same source-extension filter (`.py`/`.js`/`.jsx`/`.ts`/`.tsx`) and
  the same exclude list (`vendor/`, `node_modules/`, `.venv/`, `dist/`,
  `build/`, `.smith/`) §5.3/§5.3.1 already use, and the same
  installed-path-preferred/repo-dev-fallback parser resolution (`parse-
  python.py`/`parse-js.js`) §5.3.1 already uses.
- **FR-16**: For each changed, in-scope file, the scan MUST parse it and
  call `scripts/parsers/meta_describe.py`'s `qualifying_methods(parsed,
  threshold=quality.function_length.soft)` (default soft threshold 50)
  UNCHANGED — no new parser fields, no forked copy of the body-length
  derivation logic (exploration finding 1: the existing next-entry-start
  `body_lines` field is reused as-is). Every returned entry with
  `body_lines >= quality.function_length.decompose` (default 100) is a
  decompose-tier finding; every entry with `body_lines` between the soft
  and decompose thresholds (inclusive of soft, exclusive of decompose) is a
  soft-tier finding.
- **FR-17**: Decompose-tier findings MUST each be listed individually in
  `/tmp/smith-build-function-length-findings.txt` (`path:line`, function/
  method name, body-line count). Soft-tier findings MUST NOT be listed
  individually — they are folded into exactly one trailing "+ N soft-tier
  warnings" line, omitted when N=0, mirroring this pipeline's existing
  Low-severity-folding convention (§3.5/§3.6/§3.7's own findings files).
- **FR-18**: When `/tmp/smith-build-function-length-findings.txt` is
  non-empty, the PR body (§5.4) MUST gain a "Function Length Warnings"
  section, positioned immediately after "Description Coverage Warnings"
  and before "Clean Code Review" — mirroring §5.3/§5.3.1's own positional
  pairing. When empty, the section is omitted entirely.

### PR-body reporting

- **FR-19**: The PR body template (§5.4) MUST gain a "Quality Metrics"
  section, appended after "Supply-Chain Review" and before "Release
  notes" (the append-after-the-newest-existing-section convention every
  prior feature in this file used), non-empty whenever §3.4 produced a
  coverage finding (FR-11) or an unparsed-output disclosure (FR-13) worth
  surfacing; omitted entirely when §3.4 did not run at all (FR-9) or ran
  and found nothing to report (coverage at or above minimum, no minimum
  configured and nothing else to disclose).
- **FR-20**: The "Function Length Warnings" section (FR-18) and "Quality
  Metrics" section (FR-19) MUST both be appended together, in that
  relative order (Function Length Warnings, then Quality Metrics), after
  "Supply-Chain Review" and before "Release notes" — both are this
  feature's own additions, ordered by which of their two producing steps
  runs closer to §5.4 in the pipeline (§5.3.2 immediately precedes §5.4;
  §3.4's data is carried forward from earlier in the same build).

### Configuration

- **FR-21**: A NEW top-level `quality` key MUST be added to
  `.smith/config.json`: `{ test: [], lint: [], typecheck: [], coverage: {
  command: null, minimum_percent: null, regex: null }, function_length: {
  soft: 50, decompose: 100 }, timeout_seconds: 120, excludes: [] }` — a
  sibling to `security_review`/`supply_chain`, ships with every array
  empty and every numeric threshold at its stated default, consistent with
  this pipeline's existing "ship no opinion beyond the stated defaults"
  precedent (`supply_chain.license_policy`'s own empty-by-default arrays).
- **FR-22**: Config seeding MUST follow the exact three-site,
  non-destructive mechanism `security_review`/`supply_chain` already
  established: `templates/config.default.json` gains the `quality` block;
  `skills/smith/SKILL.md`'s init scaffold step gains a new unlettered
  paragraph + python3 heredoc seeding `quality` the same way it seeds
  `supply_chain`; `/smith-update` gains a new `### 5.1e Seed \`quality\` in
  \`.smith/config.json\`` step, immediately after the existing `5.1d`
  step, using the identical read-modify-write idiom (key present → no-op;
  file exists, key absent → merge; file absent → leave absent).

## Non-Functional Requirements

- **NFR-1**: Every new or modified shell snippet in `skills/smith-build/
  SKILL.md` and `skills/smith-bugfix/SKILL.md` for this feature MUST run
  correctly under both `bash` and `zsh`, matching this repo's existing
  shell-content convention; every Python snippet uses `python3`.
- **NFR-2**: No check this feature adds (§3.1b Lint, §3.1c Typecheck, §3.4
  Coverage Check, §5.3.2 Function-Length Scan) introduces any new
  block/terminate path — flag-only, in every configuration, at every
  severity, with no `enforcement_tier`-shaped config field anywhere in the
  `quality` schema (FR-21). §3.1/§3.1b/§3.1c command failures continue to
  be handled exclusively by §3.3's existing bounded-retry/log-and-continue
  behavior (FR-5) — that existing behavior is extended in scope, not
  replaced or made stricter.
- **NFR-3**: Every quality-command and coverage-command invocation MUST be
  wrapped in `quality.timeout_seconds`'s hard timeout (FR-1/FR-14) so no
  step introduced by this feature can hang regardless of the configured
  command's own behavior.
- **NFR-4**: This feature MUST NOT modify `smith-implement`,
  `scripts/parsers/parse-python.py`, `scripts/parsers/parse-js.js`, or
  `scripts/parsers/meta_describe.py` — the Function-Length Scan (FR-15..
  FR-18) calls `qualifying_methods()` exactly as it exists today, with no
  new parameters, fields, or return-shape changes.
- **NFR-5**: All of this feature's checks run without any user
  interaction of any kind — no prompts, confirmations, or pauses —
  consistent with `smith-build`'s "ALL phases run without user
  interaction" rule and `smith-bugfix`'s equivalent non-interactive
  convention.

## Out of Scope

- **OOS-1 — `smith-implement` inclusion.** `smith-implement` gains no part
  of this feature. It has no independent PR/commit step of its own to
  attach an advisory section to — it runs only inside an active top-level
  workflow (`smith-new`/`smith-bugfix`/`smith-debug`/`smith-build`,
  workflow-gate enforced), and whichever of those invoked it is the one
  whose own pipeline (this feature's `smith-build`/`smith-bugfix` changes,
  or none) actually runs these checks.
- **OOS-2 — Parser schema changes.** `scripts/parsers/parse-python.py`,
  `scripts/parsers/parse-js.js`, and `scripts/parsers/meta_describe.py`'s
  `qualifying_methods()` are all used exactly as they exist today; no new
  field (e.g., an explicit `end_line` beyond what `qualifying_methods()`
  already derives) is added for this feature (exploration finding 1).
- **OOS-3 — Blocking gates.** No check this feature adds can block, delay,
  or terminate a build or bugfix, under any configuration, at any
  severity — flag-only in every case (NFR-2), with no config surface that
  could imply otherwise.
- **OOS-4 — Complexity metrics beyond length.** Cyclomatic complexity,
  cognitive complexity, or any non-length function-quality metric is out
  of scope; the Function-Length Scan measures line count only (a future
  feature candidate, not attempted here).

## Assumptions

- **A-1**: The pre-feature exploration
  (`.smith/vault/explore/explore-2026-09-14-quality-metrics-pack.md`)
  found no blocking conflicts; its 7 findings are design constraints
  resolved by encoding them into this spec, confirmed by this feature's
  requirements checklist.
- **A-2**: `scripts/parsers/meta_describe.py`'s `qualifying_methods()` is
  reused unchanged for function-length derivation (its `body_lines` field,
  computed from the next entry's start line) rather than adding a new
  parser field — the same battle-tested primitive `.meta` description
  generation already depends on (exploration finding 1).
- **A-3**: `quality.timeout_seconds`'s default of 120 (vs.
  `supply_chain.timeout_seconds`'s 60) reflects that test/lint/typecheck/
  coverage commands routinely run longer than a single dependency-scanner
  invocation; both reuse the identical `python3 subprocess.run(...,
  timeout=N)` mechanism (no shell `timeout`/`gtimeout`, both confirmed
  absent on the reference dev machine — feature 56's own resolved finding,
  reused here rather than re-litigated).
- **A-4**: Every `quality.*` command string is a project-owner-authored
  shell command in `.smith/config.json`, trusted at the same level as a
  `package.json` "scripts" entry the project already runs routinely — this
  feature documents that trust domain (exploration finding 7) rather than
  adding a sandbox, approval gate, or allowlist around it.
- **A-5 — RESOLVED at questions gate (delegation).** The feature
  description named five gate decisions the exploration pass
  evidence-backed with a recommendation each. Per this workflow's
  standing delegation, the user accepted every recommendation as-is
  (`questions.md`, generated 2026-09-14, status ANSWERED). No FR above
  contradicts these outcomes; each holds as follows:
  1. **Q1 — Generalize in place vs. a new parallel step.** Generalize
     §3.1/§5.3 IN PLACE, config-driven with a verbatim hardcoded fallback.
     **Outcome:** generalize-in-place (accepted) — the hardcoded commands
     are Armory-project leftovers baked into otherwise-generic prose;
     generalizing removes tech debt instead of adding a second code path
     beside it (exploration finding 2).
  2. **Q2 — `quality` config key shape.** A new top-level `quality` key,
     sibling to `security_review`/`supply_chain`, with the exact shape
     stated in FR-21. **Outcome:** accepted — quality metrics are not
     security-review-shaped, and nesting would misrepresent that (exploration
     finding 3).
  3. **Q3 — Function-length two-tier thresholds.** 50 soft / 100 decompose,
     config-overridable via `quality.function_length`. **Outcome:**
     accepted — mirrors the File Size Policy's soft/decompose shape at
     function-body granularity, and folds near-threshold noise the same
     way this pipeline already folds low-severity findings (exploration
     finding 4).
  4. **Q4 — Coverage percent parsing.** A built-in regex catalogue
     (pytest-cov/jest-istanbul/go), tried in order, with
     `quality.coverage.regex` as a full override; unparseable output is
     disclosed, never fails. **Outcome:** accepted — covers this
     ecosystem's three most common stacks without raising the adoption bar
     for every other stack, which can still supply its own regex
     (exploration finding 5).
  5. **Q5 — Workflow scope.** `smith-build` gets the full pack;
     `smith-bugfix` gets only the §5.3 Lint generalization;
     `smith-implement` gets none. **Outcome:** accepted — `smith-bugfix`
     stays intentionally lightweight (mirroring features 55/56's own
     bugfix-exclusion rationale for their heavier passes), and
     `smith-implement` has no independent PR-assembly step of its own to
     attach an advisory section to (exploration finding 6, OOS-1).

## Success Criteria

- **SC-1**: With `quality.test`/`quality.lint`/`quality.typecheck`
  configured, `smith-build`'s §3.1/§3.1b/§3.1c each run every configured
  command, each bounded by `quality.timeout_seconds`, with no legacy
  fallback text executed (FR-1/FR-3/FR-4).
- **SC-2**: With `.smith/config.json` absent, or present without a
  `quality` key, `smith-build` §3.1 and `smith-bugfix` §5.3 both run their
  respective legacy fallback commands byte-for-byte unchanged from this
  feature's pre-existing text (FR-2/FR-7) — zero behavior change.
- **SC-3**: A configured `quality.coverage.command` whose output matches
  one of the three built-in regex patterns (pytest-cov/jest-istanbul/go)
  produces a correctly-extracted percentage; when below
  `minimum_percent`, exactly one High finding is produced; the build
  proceeds to Phase 3.5 regardless (FR-10/FR-11).
- **SC-4**: A configured `quality.coverage.command` whose output matches
  neither the catalogue nor a configured override is disclosed as
  unparsed, with zero findings produced and zero build impact (FR-13).
- **SC-5**: On a diff containing one function at or above the 100-line
  decompose threshold and several functions in the 50-99 soft-tier range,
  the decompose-tier function is listed individually with `path:line` and
  its body-line count, and the soft-tier functions fold into exactly one
  "+ N soft-tier warnings" line (FR-16/FR-17).
- **SC-6**: Neither "Function Length Warnings" nor "Quality Metrics"
  appears in the PR body when their respective producing step found
  nothing to report or did not run at all (FR-18/FR-19).
