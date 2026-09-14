---
feature: 55-security-review-pass
primary_system: cross-system
branch: 55-security-review-pass
status: planned
---

# Implementation Plan: Inline Security Review Pass for smith-build

## Technical Context

- **Repo**: Smith skills distribution (this repo). No application
  runtime — deliverables are two new dependency-free scripts (bash+zsh
  entry point, python3 engine), their companion tests, markdown skill
  prose (`skills/smith-build/SKILL.md`, plus config-seeding steps in
  `skills/smith/SKILL.md` and `skills/smith-update/SKILL.md`), one new
  config key (`templates/config.default.json`), a new `docs/security-model.md`
  section, and a `CHANGELOG.md` entry.
- **No `.specify/scripts/setup-plan.sh`, no `constitution.md`, no
  `.smith/index/` manifest exist in this repo** — this plan was produced by
  direct file reads (cited throughout `research.md`), not by a scaffolding
  script or manifest navigator, matching the same observation already
  recorded in features 53 and 54's own `plan.md` files.
- **Primary references**: `research.md` (all resolved anchors, cited
  file:line) and `data-model.md` (config schema, scanner output format,
  findings contract, `/tmp` handoff files, enforcement decision table) in
  this same feature folder.
- **Endpoint (A-6)**: this feature was QUEUED after its questions gate; the
  gate has since been answered (`questions.md`, ANSWERED, 2026-09-13) — it
  is not yet built in this session, but every previously gate-deferred item
  from `research.md` §9 is now resolved (Q1-Q6) and carried into this plan
  as concrete, unconditional content rather than conditional rows.

## Constitution Gates

**N/A — no `constitution.md` or `.specify/memory/constitution.md` exists in
this repo, so there are no constitution-derived gates to check.**
(Clean-architecture and file-size discipline are instead enforced via this
plan's own File Size Policy section below, exactly the substitution
features 53 and 54's plan.md files already used.)

## Architecture Summary

One new phase in `smith-build/SKILL.md` (`## Phase 3.6: Security Review
Pass`, inserted at the currently-blank line 327, between Phase 3.5's
closing content and the `## Phase 4:` heading — `research.md` §1), plus a
new "Security Review" PR-body template block in the same file's existing
§5.4, plus a Key Rules clause addition (`research.md` §3) — now definite,
not conditional, since Layer 1 (secret) Critical findings always terminate
unconditionally (Q2) even under the default `flag` tier — plus two new
scripts under `scripts/security/` with companion tests, plus a new
`security_review` key in `templates/config.default.json` with
non-destructive seeding steps added to `skills/smith/SKILL.md` and
`skills/smith-update/SKILL.md` (`research.md` §6), plus a new
`docs/security-model.md` section, plus a `CHANGELOG.md` entry, plus one
additional row for `skills/smith-bugfix/SKILL.md` (Q5).

Phase 3.6's internal shape (spec FR-1..FR-24, `data-model.md` §1-§5):

1. **Presence-detect optional scanners** — invoke
   `scripts/security/detect-scanners.sh` once, before running any layer,
   to determine whether `gitleaks` (Layer 1 additive) and `semgrep`/
   `bandit` (Layer 2) are on `$PATH`. Output feeds §4's
   `/tmp/smith-build-security-layers-ran.txt` layer-disclosure file
   directly.
2. **Run Layer 1** — `scripts/security/secret-scan.sh` against
   `git diff $BASE_BRANCH` (same `BASE_BRANCH=$(.specify/scripts/bash/get-base-branch.sh)`
   threading Phase 3.5/Phase 4/Phase 5 already use, per FR-3), merging in
   gitleaks output when step 1 detected it (FR-7). Runs unconditionally
   (FR-8) — this is the feature's only guaranteed-coverage deterministic
   layer.
3. **Run Layer 2 IF detected in step 1** — invoke `semgrep`/`bandit`
   against the same diff scope; silently skip entirely if neither was
   detected (FR-9). Neither tool is added as an installed dependency of
   Smith or of any consuming project (FR-9's explicit constraint).
4. **Run Layer 3 unconditionally** — launch exactly ONE subagent (Task
   tool), `model: opus` by default (overridable via the optional
   `review_model` config key, Q4), to evaluate the full branch diff against
   FR-11's 10-area rubric (`data-model.md` §3's findings contract). Layer 3
   does NOT additionally invoke the built-in `/security-review` capability
   in v1 (Q3) — this spec's own rubric is the sole methodology.
5. **Merge findings, evaluate the enforcement decision table**
   (`data-model.md` §5) against the config-driven tier and per-finding
   severity/layer. If ANY finding resolves to "terminate": execute the
   terminate-semantics contract (`data-model.md` §5) in full — no further
   Phase 3.6 work, Phase 4 never begins, hard-stop marker written to the
   session log, worktree preserved per the existing Phase 7.3 failure
   convention, active-workflow marker left uncleared. Otherwise: write all
   non-terminating findings to `/tmp/smith-build-security-findings.txt`
   (`data-model.md` §4) and proceed to Phase 4 exactly like Phase 3.5 does
   today.
6. **No auto-fix, ever** (FR-13/OOS-4) — every finding from every layer
   that isn't a hard-stop is a flagged finding; Phase 3.6 makes zero
   Write/Edit calls to the working tree.

## Reuse-before-create (exact components reused, not reinvented)

- **Phase 3.5's five-part section shape** (`smith-build/SKILL.md:252-326`,
  `research.md` §1) — Invocation/rubric-delivery/findings-contract/
  bounded-execution/scratch-file-write — reused as the structural template
  for Phase 3.6's own prose, adapted for three layers and the terminate
  branch Phase 3.5 has no equivalent of.
- **§5.3/§5.3.1's scan → `/tmp` file → conditional-PR-section mechanics**
  (`smith-build/SKILL.md:393-604`, `research.md` §2) — reused for the
  file-handoff and PR-template mechanics; the `[ -s <file> ] && include ||
  omit` check and the "flag, never a blocker" closing sentence pattern
  (605-657) are reused verbatim for the new "Security Review" section
  (adapted to also cover the terminate branch, where the section itself
  is never rendered because Phase 4/5.4 are never reached).
- **`BASE_BRANCH=$(.specify/scripts/bash/get-base-branch.sh)` threading**
  (`smith-build/SKILL.md:263,334,406`, FR-3) — reused verbatim for Phase
  3.6's own diff; never a hardcoded or inferred ref.
- **`security-guard-mcp-browser.sh`'s presence-detect + defensive-parse
  idioms** (`hooks/security-guard-mcp-browser.sh:19-28,225-256`,
  `research.md` §7) — `set -uo pipefail`, `python3 -c "..." 2>/dev/null ||
  echo "<default>"` fallback chains, and the two-step
  file-exists-AND-parses config-validity gate before trusting any field —
  reused for `scripts/security/detect-scanners.sh`'s tool-presence checks
  and for both new scripts' `security_review` config reads.
- **Feature 53's non-destructive config-merge idiom**
  (`skills/smith/SKILL.md:274-298`, `skills/smith-update/SKILL.md:274-305`,
  `research.md` §6) — the exact python3 read-modify-write heredoc pattern
  (load-if-exists-else-`{}`, merge only the key that's actually missing,
  preserve every other key, re-dump with `indent=2`), retargeted from
  `.smith/security-config.json`'s `browser_verification.urls` key to
  `.smith/config.json`'s new `security_review` key. This closes the gap
  `research.md` §6 identifies: `session-start-logger.sh`'s whole-file-
  copy-if-absent seeding (25-40) never touches an already-existing
  `.smith/config.json`, so every already-initialized project needs this
  explicit merge step to ever receive the new key.
- **`get-base-branch.test.sh`'s test harness shape**
  (`tests/get-base-branch.test.sh`, `research.md` §5) —
  `make_repo`/`run_case`/`PASS`/`FAIL`/summary-line/exit-status structure,
  extended with `test_security_guard_mcp_browser.sh`'s mktemp-scaffold-
  per-case idiom for planting multi-file fixtures (fake secrets, fake
  gitleaks output) — reused as the closest-fit harness for the new
  `tests/security/test_secret_scan.sh` file, rather than the JSON-stdin
  protocol style (`research.md` §5's explicit "no JSON-protocol machinery
  to reuse" finding).
- **A presence-detect helper designed for reuse beyond this feature**
  (NFR-4) — `scripts/security/detect-scanners.sh` is written as a
  standalone, directly-invokable script (not inlined into
  `smith-build/SKILL.md`) specifically so `smith-audit`'s existing
  Security sub-audit (`skills/smith-audit/SKILL.md:112`, currently a
  one-line bullet reference with no scanner-presence implementation of its
  own) and the future F2 dependency-CVE feature can invoke it directly
  without depending on `smith-build`'s pipeline at all.
- **Phase 54's "Clean Code Review" PR-body block** as the literal
  wording/structure template (`smith-build/SKILL.md:638-649`) for this
  feature's "Security Review" block — severity-bracket, backtick path,
  em-dash description line shape reused verbatim; only the trailing
  sentence and the layer-disclosure preamble (FR-20) are new content.

## File Size Policy

Both new scripts stay under the 300-line soft target
(`smith-build/SKILL.md:219-220`'s constitution-substitute convention, per
feature 54's own precedent of applying this numeric discipline to new
Smith-repo files even absent a hard constitution gate):
- `scripts/security/secret-scan.sh` — thin bash CLI wrapper (arg parsing,
  exclude-path filtering, exit-code contract, gitleaks merge) delegating
  the actual regex/entropy engine to a `.py` module it invokes; target
  ≤120 lines for the bash wrapper.
- `scripts/security/secret_scan.py` (or equivalent inline-but-separate
  Python module invoked by the wrapper) — the regex catalogue
  (`research.md` §8), entropy check, and per-line redaction/masking logic
  (`data-model.md` §2); target ≤250 lines. If this module would exceed
  300 lines once the full pattern catalogue and redaction logic are
  written, split the pattern table into its own small data file
  (`scripts/security/secret_patterns.py`) rather than growing one file
  monolithically, per this repo's own File Size Policy discipline.
- `scripts/security/detect-scanners.sh` — target ≤60 lines; a single
  `command -v <tool>` check per tool, no state beyond stdout output.
- `skills/smith-build/SKILL.md`'s new Phase 3.6 section — compact per
  feature 54's own precedent (`.specify/systems/cross-system/features/54-clean-code-review-pass/plan.md:138-153`):
  reference `data-model.md`'s contracts (§1-§5) rather than restating
  field-by-field detail; target roughly 60-90 lines of new prose (larger
  than Phase 3.5's 40-70 line target since this phase covers three layers
  plus a terminate branch Phase 3.5 doesn't have), plus a ~15-20 line
  PR-body template addition.

## Exact file-by-file change list

### NEW

| File | Purpose |
|---|---|
| `scripts/security/secret-scan.sh` | Layer 1 entry point: bash CLI wrapper around the regex/entropy engine; exclude-path filtering (FR-5); merges gitleaks output when `detect-scanners.sh` reports it present (FR-7); emits `data-model.md` §2's pipe-delimited line format on stdout, one finding per line, redacted excerpts only. |
| `scripts/security/secret_scan.py` (or `secret_scan_engine.py`) | The actual pattern catalogue (`research.md` §8: AWS AKIA/ASIA, GCP SA JSON markers, PEM headers, GitHub `ghp_`/`gho_`/etc., Slack `xox*`, generic KEY/SECRET/TOKEN/PASSWORD assignments gated by Shannon entropy, connection-string credentials) plus the redaction/masking function (`data-model.md` §2's first-4/last-4-chars-else-fixed-literal rule) plus the per-line allowlist-marker suppression (`# smith-secret-scan: allow`, `research.md` §8). |
| `scripts/security/detect-scanners.sh` | NFR-4's single reusable presence-detection helper: `command -v gitleaks/semgrep/bandit`-style checks, one line of machine-parseable output per tool (`<tool>=present|absent`). Designed for direct invocation by `smith-audit`'s Security sub-audit and the future F2 feature, not just by `smith-build`. |
| `tests/security/test_secret_scan.sh` | FR-6's companion test file. `get-base-branch.test.sh`-style harness (`research.md` §5): `mktemp -d` throwaway repos, planted fixture files (clearly-fake canary secrets per each pattern-catalogue row — never a real-looking production-style credential), PASS/FAIL per case, summary line, non-zero exit on any failure. Explicit dual-shell run (`bash tests/security/test_secret_scan.sh` and `zsh tests/security/test_secret_scan.sh`, NFR-2). Cases: one per catalogue pattern (positive), exclude-path suppression, glob-allowlist suppression, entropy-threshold negative case (`password="changeme"` does NOT fire), allowlist-marker suppression, redaction (assert the ACTUAL secret value never appears verbatim anywhere in stdout), gitleaks-merge behavior (via a stubbed fake `gitleaks` executable on `$PATH` for the test, since the real tool isn't installed on this dev machine per A-2), and empty-diff (zero findings, clean exit). |
| `tests/security/test_detect_scanners.sh` | Small companion test for the presence-detection helper: stub executables placed on a scratch `$PATH` for the present case, an empty scratch `$PATH` for the absent case, asserting exact `<tool>=present|absent` output for each of gitleaks/semgrep/bandit. |

### MODIFIED

| File | Change |
|---|---|
| `skills/smith-build/SKILL.md` | **(1)** New `## Phase 3.6: Security Review Pass` section inserted at line 327 (between Phase 3.5's close at 326 and `## Phase 4:` at 328) — Architecture Summary's 6-step shape above. RESOLVED: the enforcement-tier read is written against `data-model.md` §5's table with `enforcement_tier` defaulting to `flag` (Q1) and the Layer 1 secrets-always-terminate override written as unconditional, non-bypassable prose (Q2) — no per-project opt-out exists for it. Layer 3 is pinned to `model: opus` by default, overridable via the optional `review_model` config key (Q4); Layer 3 does NOT invoke the built-in `/security-review` capability (Q3) — this spec's own rubric (FR-11) is the sole methodology, stated plainly rather than as a placeholder. **(2)** §5.4 PR-body template gains a new "Security Review" conditional section (`data-model.md` §4, layer-disclosure text per FR-20), positioned after the existing "Clean Code Review" section and before `## Release notes` — ordering choice: security findings are the newest/most-recently-added flag category, consistent with each prior feature appending its own section after the existing ones rather than reordering. **(3)** Key Rules (842-851): now DEFINITE, not conditional — since Layer 1 Critical secret findings always terminate regardless of tier (Q2), a "terminate" enforcement path exists unconditionally in every build. Add one clause to the existing "ALL phases run without user interaction" bullet (844) disambiguating that a Phase 3.6 hard-stop is itself prompt-free (`research.md` §3) and does NOT fall under the "retry once ... continuing" bullet (846). |
| `templates/config.default.json` | New top-level `security_review` key added per `data-model.md` §1's schema, positioned after the existing `security` block (visually grouping the two security-adjacent keys) and before `context_budget`. RESOLVED: `enforcement_tier: "flag"` (Q1 default), `review_model: "opus"` (Q4 default); `layers`/`excludes`/`allowlist_globs` sub-keys shipped as proposed (Q6). No `secret_findings_always_block` key — Q2 resolved Layer 1 Critical termination to be unconditional and non-bypassable, so there is no toggle to seed. |
| `skills/smith/SKILL.md` | New seeding step, same section grouping as the existing `browser_verification.urls` seed step (274-298) — a python3 non-destructive merge heredoc that creates `.smith/config.json`'s `security_review` key with the gate-resolved defaults if the key is entirely absent, leaving every other key untouched, mirroring the exact idiom at 277-297 but retargeted at `.smith/config.json`. This is a NEW step distinct from `.smith/config.json`'s existing whole-file seeding (which `session-start-logger.sh` already does for brand-new projects) — it exists specifically to cover the case `research.md` §6 identifies: a project whose `.smith/config.json` already exists from before this feature shipped. |
| `skills/smith-update/SKILL.md` | New `### 5.1c` (or next free letter after the existing `5.1b` at 274) mirroring `skills/smith/SKILL.md`'s new step above, applied at update-refresh time — same three-line decision rule as the existing 5.1b (278-280): key present → no-op; key absent, file exists → merge; file doesn't exist at all → leave absent (session-start-logger.sh's own seeding path is what creates it from scratch, not this step). |
| `skills/smith-bugfix/SKILL.md` | RESOLVED (Q5): Phase 7.1 (Commit) gains a Layer-1-only secret-scan gate — NOT the full three-layer pass (FR-17 scopes this narrowly) — immediately before its existing commit step, invoking the same `scripts/security/secret-scan.sh` this feature already ships. Its terminate semantics map onto `smith-bugfix`'s EXISTING STOP-on-test-failure/scope-creep terminate convention (exploration Finding 6) rather than inventing a second termination mechanism — consistent with FR-16's "no second termination mechanism" rule. Layer 2 (SAST) and Layer 3 (LLM review) do NOT run here; both remain `smith-build`-only. |
| `docs/security-model.md` | New section (after the existing "## Security Guards" section, 46-87, before "## Scheduler Security", 89) documenting the Security Review Pass as a build-pipeline review layer that inspects DIFF CONTENT (what code says), explicitly distinguished from the three existing guard hooks which inspect ACTION INTENT (what a tool call is about to do) — the same complementary framing spec.md's own Overview/A-4 already establish for the `smith-audit` relationship, extended here to the guard-hook relationship too since this doc is where a reader would otherwise expect (and not find) any mention of diff-content scanning. Names the three layers, the config key, the redaction guarantee (§2), and cross-references `data-model.md`/`research.md` §8 for the pattern catalogue without restating it verbatim (avoiding a second, driftable copy of the regex list in prose). |
| `CHANGELOG.md` | New `[Unreleased]` → `### Added` entry, written LAST after every other file's changes are final (mirrors features 53/54's own phased-ordering rule for their CHANGELOG entries), describing the three-layer pass, the config key, the redaction guarantee, the resolved default enforcement tier (`flag`, Q1) with the unconditional Layer 1 secrets-terminate behavior (Q2) called out explicitly, and the smith-bugfix secret-scan extension (Q5). |

### Gate answers applied (summary, cross-referenced above)

All six previously-deferred items are now resolved (`questions.md`,
2026-09-13):

- **Q1 (default tier)** — RESOLVED: `flag` default, `block_on_critical`
  opt-in. Affects: Phase 3.6 prose, `templates/config.default.json`
  defaults, `docs/security-model.md`'s description of default behavior.
- **Q2 (secrets-always-terminate override)** — RESOLVED: unconditional,
  non-bypassable by tier — no config field exists for it. Affects: Phase
  3.6 prose, the Key Rules clause (now definite, not conditional, since a
  "terminate" path exists in every build), `docs/security-model.md`.
- **Q3 (built-in `/security-review` invocation)** — RESOLVED: no, v1 uses
  only this spec's own rubric. Affects: Phase 3.6's Layer 3 invocation
  prose only.
- **Q4 (Layer 3 model)** — RESOLVED: `model: opus` default, optional
  `review_model` config override (haiku|sonnet|opus|fable). Affects: Phase
  3.6's Layer 3 invocation prose, `templates/config.default.json`,
  `data-model.md` §1.
- **Q5 (smith-bugfix extension)** — RESOLVED: yes. This plan gains the
  `skills/smith-bugfix/SKILL.md` row above (Layer-1-only secret-scan gate
  before Phase 7.1's commit step; Layer 2/3 stay `smith-build`-only).
- **Q6 (config schema depth)** — RESOLVED: shipped as originally proposed,
  plus `review_model` (Q4). Affects: `templates/config.default.json`'s
  exact key set, `data-model.md` §1.

No other files are touched. `skills/smith-clean-code/SKILL.md`, the three
`security-guard-*.sh` hooks, and `smith-audit`'s SKILL.md/sub-audit logic
are explicitly NOT edited (NFR-5) — read-only inputs or unaffected
neighbors, consistent with OOS-2/OOS-3.

## Phased ordering

1. **Scripts + tests first.** `scripts/security/detect-scanners.sh`,
   `scripts/security/secret-scan.sh` (+ its Python engine), and both
   companion test files ship together and pass in isolation BEFORE any
   SKILL.md wiring references them — a `smith-build` phase that invokes a
   script which doesn't exist yet (or exists but is untested) would be a
   half-shipped, unverifiable feature, mirroring feature 54's own
   "review-pass section + PR template ship together, first" rule applied
   one level earlier here since this feature (unlike 54) has real
   standalone code to land before any markdown references it.
2. **`smith-build` Phase 3.6 + §5.4 PR template + Key Rules clause
   (now definite, not conditional — Q2), plus `smith-bugfix`'s Phase 7.1
   secret-scan gate (Q5).** Depends on phase 1 (the scripts must exist for
   the prose to correctly describe their invocation and output). Both
   SKILL.md changes consume the same `scripts/security/secret-scan.sh`
   entry point and ship together for the same "internally inconsistent
   half-shipped file" reason feature 54's plan.md gives for its own
   single-unit Phase 3.5 + template change.
3. **Config + seeding + docs.** `templates/config.default.json`'s new key,
   the two seeding-step additions (`skills/smith/SKILL.md`,
   `skills/smith-update/SKILL.md`), and `docs/security-model.md`'s new
   section — independent of phases 1-2's internal correctness (different
   files, no shared runtime state) but sequenced third because Phase 3.6's
   prose (phase 2) needs to already name the exact config key/schema it
   reads before the config/docs phase writes the authoritative schema
   description, avoiding two divergent schema descriptions being drafted
   in parallel.
4. **`CHANGELOG.md`.** Written last, after phases 1-3 are final, so the
   entry accurately describes what shipped rather than what was planned
   (mirrors features 53 and 54's identical phased-ordering rule for their
   own CHANGELOG entries).

## Test strategy

- **Script unit tests (new, this feature's primary test surface)** —
  `tests/security/test_secret_scan.sh` and
  `tests/security/test_detect_scanners.sh` (see NEW files above for case
  lists). Both run under bash AND zsh (NFR-2), each producing a PASS/FAIL
  summary and non-zero exit on failure, mirroring
  `tests/get-base-branch.test.sh`'s exact convention.
- **Planted-secret fixtures, clearly-fake canary values** — every positive
  test case uses an obviously-synthetic value (e.g. an AKIA-prefixed
  string that is structurally valid per the regex but is never a real
  issued AWS key — the same "test-pattern secret" framing spec.md's own
  US-1/SC-1 use) — never a real credential, and never a string that could
  be mistaken for one if it leaked into a public log.
- **Redaction verification is a first-class assertion, not an
  afterthought** — `data-model.md` §2's redaction requirement is testable
  directly: assert the planted canary's full value string does NOT appear
  anywhere in the scanner's stdout, only the masked excerpt does.
- **Prose consistency greps** (run after Phase 3.6/§5.4 prose lands):
  - `grep -n "Phase 3.6" skills/smith-build/SKILL.md` — confirms the new
    heading exists exactly once.
  - `grep -n "## Phase 4:" skills/smith-build/SKILL.md` — confirms Phase 4
    still immediately follows.
  - `grep -c "Security Review" skills/smith-build/SKILL.md` — expect ≥2
    matches (Phase 3.6 heading/prose and the §5.4 template section name).
  - `grep -n "smith-build-security-findings.txt"
    skills/smith-build/SKILL.md` — expect the filename to appear both
    where written (Phase 3.6) and where read (§5.4 template).
- **Config-seeding regression** — `tests/hooks/test_config_default_seed.sh`
  (existing) is expected to keep passing UNMODIFIED (this feature adds a
  key to the template, it does not change `session-start-logger.sh`'s own
  seeding logic); a NEW case is added to it (or a new sibling test file,
  whichever the build phase judges keeps that file under its own size
  discipline) verifying the fresh-project byte-for-byte-copy path now
  includes `security_review` in the copied template.
- **Full-suite regression** — run the complete `tests/` directory
  (`tests/hooks/*.sh`, `tests/get-base-branch.test.sh`,
  `tests/skills/test_smith_build_coverage_flag.sh`, etc.) after all
  phases land, confirming zero regressions in unrelated scripts this
  feature does not touch (NFR-5's read-only-neighbors guarantee extended
  to test coverage, not just source files).
- **No markerless-redirection constraint applies inside Phase 3.6** — same
  reasoning feature 54's plan.md already gives (its own Test Strategy
  section): Phase 3.6 runs between Phase 3 and Phase 4, while the
  Phase-0-created active-workflow marker is still present, so ordinary
  `>`/`>>` redirection into the `/tmp` scratch files is unrestricted.

## Rollout notes

- Distributed via the standard `/smith-update` path — no bespoke install
  machinery; `install.sh`'s existing `scripts/*` and `hooks/*.sh` globbing
  picks up the two new `scripts/security/*` files automatically (verify
  during the build phase that `scripts/security/` doesn't need a
  dedicated glob entry — `research.md`/this plan did not find one needed
  since `install.sh:227-232`'s existing per-project-file loop is keyed to
  `templates/*.default.json`, not `scripts/`, so confirm the SEPARATE
  scripts-copy mechanism `skills/smith/SKILL.md:300-307` already uses
  (`cp -r skills/smith/scripts/* .specify/scripts/bash/`) is NOT the
  relevant path for `scripts/security/` — these are repo-root `scripts/`,
  distributed as part of the Smith skills package itself, not per-project
  `.specify/scripts/bash/` scaffolding; this distinction is worth an
  explicit check during the build phase, flagged here rather than
  asserted, since this plan's research pass did not find an existing
  precedent for a repo-root `scripts/` subdirectory being consumed FROM
  a SKILL.md the way `.specify/scripts/bash/` helpers are).
- The pass runs on EVERY `smith-build` invocation from the moment this
  ships — there is no opt-in/opt-out flag for the Security Review Pass
  ITSELF (only per-layer enable flags under `security_review.layers`,
  shipped per Q6). Teams that want zero security review overhead have no
  documented way to disable Phase 3.6 entirely under the current spec —
  this was surfaced to the gate as an awareness note, not one of the six
  named questions, and remains an accepted v1 limitation (no gate item
  addressed it).

## Spec-plan tensions surfaced (feed the questions gate)

None of these are contradictions within spec.md itself (its own
requirements checklist already verified internal consistency) — they are
either gaps this plan's file-level research surfaced that spec.md's prose
didn't anticipate, or explicit restatements of the six items spec.md
itself already named as deferred.

1. **The `.smith/config.json` seeding gap is real and is NOT one of the
   six named A-7 items — it is a plan-level mechanism gap, not a
   product-level decision, so this plan resolves it outright rather than
   deferring it.** `research.md` §6: `session-start-logger.sh`'s
   whole-file-copy-if-absent seeding of `.smith/config.json` never touches
   an already-existing file. Every developer machine that has ever run a
   single Claude Code session in a Smith project already has a
   `.smith/config.json`, so without an explicit merge step (added to this
   plan's file-by-file list, mirroring feature 53's exact
   `skills/smith/SKILL.md`/`skills/smith-update/SKILL.md` mechanism), the
   new `security_review` key would silently never reach any pre-existing
   project. This is flagged prominently for the gate's awareness (it
   changes the file-by-file change list from "1 file: templates/config.default.json"
   to "3 files"), but is not itself a question requiring a gate ANSWER —
   the mechanism is a straightforward reuse of existing precedent, not a
   product tradeoff.
2. **Phase numbering: spec names phases functionally, not numerically —
   resolved here by evidence, matching feature 54's own precedent for the
   identical situation.** spec.md's FR-1 says "strictly after Phase 3.5
   ... strictly before Phase 4" without naming a section number. This plan
   resolves it to `## Phase 3.6: Security Review Pass`, following the
   task's own placeholder naming AND the "N.5/N.6" sequential convention
   Phase 3.5 itself established as the next available slot before Phase
   4 — not a spec ambiguity, not one of the six named A-7 items.
3. **RESOLVED (Q1/Q2): the Key Rules autonomy-clause edit is definite, not
   conditional.** The gate resolved `enforcement_tier` to default `flag`
   (Q1) but ALSO resolved Layer 1 secret Critical findings to terminate
   unconditionally regardless of tier (Q2) — so a "terminate" path exists
   in every build from day one, not only for projects that opt into
   `block_on_critical`. The Key Rules clause is therefore warranted in the
   initial ship, not aspirational documentation for a path most projects
   won't hit.
4. **RESOLVED (Q3): no built-in `/security-review` layer in v1.** This
   session's own available-skills listing shows a `security-review` skill
   entry ("Complete a security review of the pending changes on the
   current branch"), but `research.md` §9 item 3 confirms — per the
   exploration's Finding 4 and a direct check of this repo's file tree —
   that no `skills/security-review/` directory or SKILL.md exists IN THIS
   DISTRIBUTION REPO. The gate resolved Option A: Layer 3 uses only this
   spec's own rubric (FR-11); the open question of whether the built-in
   skill is a Claude-Code-native capability or something this feature
   would need to materialize on disk first does not need resolving for
   v1, and is deferred to a future revisit "once this pass has mileage"
   (Q3's recommendation).
5. **RESOLVED: spec.md's own A-7 items (Q1-Q6) are now all answered**,
   matching feature 54's equivalent plan.md where all five of ITS deferred
   items were already answered by this stage. This plan's file-by-file
   list no longer carries `PENDING GATE` markers — every point A-7's
   answers change concrete content (tier defaults, override behavior,
   Layer 3 model/rubric-source sentence, config schema depth, and the
   `smith-bugfix` file, now unconditional) is filled in above. No FR/NFR
   was contradicted by these answers; `data-model.md` §1's schema and §5's
   decision table were both written to be additive-safe/
   structurally-complete under either resolution, so the answers filled in
   values without requiring any restructuring of this plan.
