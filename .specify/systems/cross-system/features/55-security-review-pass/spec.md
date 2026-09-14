---
feature: 55-security-review-pass
primary_system: cross-system
also_affects: []
branch: 55-security-review-pass
created: 2026-09-13
status: in-progress
answers_applied: 2026-09-13
---

# Inline Security Review Pass for smith-build

## Overview

Feature 54 added a post-hoc **Clean Code Review Pass** (`smith-build` Phase
3.5) that re-checks a finished diff against smith-clean-code's rubric,
auto-fixing what it safely can. Nothing in Smith today performs the
equivalent check for security: `smith-build` generates and ships code with
no deterministic secret scan, no static analysis security testing (SAST),
and no LLM-driven security review of the diff it produces. Meanwhile,
`smith-build`'s existing pipeline order — commit (§5.1) → push (§5.2) →
file-size/coverage scans (§5.3/§5.3.1) — means that even if a scan were
added at §5.3, it would run *after* the branch has already been pushed to
origin. A secret reaching that point is already leaked.

This feature adds a three-layer **Security Review Pass** to `smith-build`,
run entirely before `git commit`, plus a config-driven enforcement tier and
a conditional "Security Review" PR-body section. It is informed by a
pre-feature exploration
(`.smith/vault/explore/explore-2026-09-13-security-review-pass.md`, status:
clear, 8 findings, no blocking conflicts) whose findings are binding design
constraints encoded throughout this spec (traced in this feature's
requirements checklist).

**Terminology used throughout this spec:**
- **Layer** — one of the three independent detection mechanisms this
  feature adds: **Layer 1** (deterministic secret scan), **Layer 2** (SAST),
  **Layer 3** (LLM security review).
- **Security Review Pass** — the new `smith-build` Phase 3.6 subagent step
  that runs all three layers against `git diff $BASE_BRANCH`, strictly after
  Phase 3.5 (Clean Code Review Pass) and strictly before Phase 4 (Spec
  Updates) — and therefore strictly before Phase 5.1's `git commit`.
- **Finding** — one rubric or scan violation identified by any layer,
  tagged Critical, High, Medium, or Low, carrying: severity, `path:line`,
  category, rationale, and the layer that found it.
- **Presence-detected / silent-skip** — a layer (gitleaks for Layer 1;
  semgrep/bandit for Layer 2) that runs only when already installed on the
  machine, and is skipped with no error, no warning noise, and no
  degraded-mode message when absent — it is simply omitted from the
  "ran" list in the PR-body section.
- **Enforcement tier** — the config-driven policy, read from the new
  `security_review` key in `.smith/config.json`, that determines whether a
  qualifying finding only gets flagged (recorded for the PR body) or blocks
  (terminates the workflow). Two values: `flag` (the shipped default) and
  `block_on_critical` (opt-in). The tier governs Layer 2 (SAST) and Layer 3
  (LLM review) Critical findings only — Layer 1 (deterministic secret)
  Critical findings terminate unconditionally, independent of this tier
  (see FR-16).
- **Hard-stop** — the termination behavior when "block" applies: the
  workflow stops before Phase 4 ever begins (so Phase 5.1/5.2 — commit and
  push — never execute), a marker is written to the vault session log, and
  the eventual release notes/final summary record the stop. A hard-stop is
  never a synchronous prompt — `smith-build` runs with no user interaction
  of any kind, autonomy that this feature preserves even when it blocks.

## Problem Statement

`smith-build` ships every generated diff with zero security-specific
verification. This gap has three independent dimensions the exploration
pass confirmed are unaddressed today:

1. **No pre-commit secret scan.** `smith-build`'s existing pipeline commits
   (§5.1) and pushes (§5.2) before any scan runs (§5.3/§5.3.1 are
   post-push). A hardcoded credential introduced during implementation
   reaches `origin` with nothing in the pipeline having looked for it.
2. **No SAST, no LLM security review.** Deterministic security tooling
   (semgrep, bandit) is presence-detected-or-nothing on any given
   contributor's machine — the exploration confirmed this repo's own
   development machine currently has zero security scanners installed
   (gitleaks, trufflehog, semgrep, bandit, osv-scanner, pip-audit, and
   grype are all absent) — so a scanner-only design would ship with no
   security coverage at all on a machine exactly like this one. Nothing
   fills that gap today; Smith's built-in `/security-review` capability is
   not materialized anywhere on disk in this repository and cannot be
   cited or invoked as-is.
3. **No config home, and an existing config split (BANK-027).** Smith
   already has one unresolved security-config fragmentation:
   `templates/config.default.json` seeds a `security` block into
   `.smith/config.json` that no guard hook reads, while the three
   `security-guard-*.sh` hooks actually read a separate, unseeded
   `.smith/security-config.json` (tracked as
   `.smith/vault/bank/2026-09-13_120000-unify-security-config-seeding.md`,
   BANK-027, status: banked). This feature must add its own config surface
   without deepening that split.

A smaller, related gap exists in `smith-bugfix`: its Phase 7.1 (Commit) and
7.2 (Push) commit and push with zero scanning of any kind today. This
feature closes that asymmetry: `smith-bugfix` gains Layer 1's deterministic
secret scan ahead of its existing Phase 7.1 commit step, using FR-16's
unconditional terminate semantics for any Critical finding; Layer 2 (SAST)
and Layer 3 (LLM review) remain `smith-build`-only, preserving
`smith-bugfix`'s lightweight pipeline (FR-17).

The exploration pass ahead of this feature
(`.smith/vault/explore/explore-2026-09-13-security-review-pass.md`) found no
blocking conflicts — its 8 findings are design constraints resolved by
encoding them into this spec, not open risks requiring rework.

## User Scenarios

### US-1 — SAST/LLM finding is caught pre-commit; default tier flags (primary flow, non-blocking)
```gherkin
Given a smith-build run has just passed Phase 3.5 (Clean Code Review Pass)
Given the branch diff vs $BASE_BRANCH contains a Critical-severity finding
    from Layer 2 (SAST) or Layer 3 (LLM review) — not a Layer 1 secret
Given security_review.enforcement_tier is at its default value, `flag`
When the Security Review Pass (Phase 3.6) runs
Then the finding is flagged as Critical severity before Phase 4 begins
And the workflow is NOT terminated
And the finding is recorded for the "Security Review" PR-body section
And the finding has already surfaced pre-commit — before Phase 5.1's
    `git commit` ever executes
```

### US-2 — Planted secret is caught pre-commit; always hard-stops (unconditional flow)
```gherkin
Given a smith-build run has just passed Phase 3.5 (Clean Code Review Pass)
Given the branch diff vs $BASE_BRANCH contains a planted test-pattern secret
    matching Layer 1's (deterministic scan) detection patterns
Given security_review.enforcement_tier is set to ANY value — `flag` or
    `block_on_critical` — since Layer 1 Critical secret findings terminate
    unconditionally, independent of the configured tier (FR-16; the
    system's second non-bypassable denial, after the browser-production
    confirm-gate)
When the Security Review Pass (Phase 3.6) runs
Then the workflow terminates immediately, before Phase 4 (Spec Updates)
    begins
And Phase 5.1 (Commit) never executes — the secret never reaches
    `git commit`, let alone `git push`
And a hard-stop marker is written to the vault session log and is reflected
    in the eventual release notes/final summary
And no synchronous prompt or confirmation is presented at any point
```

### US-3 — Clean diff on a fully scanner-equipped machine
```gherkin
Given the branch diff vs $BASE_BRANCH contains zero findings across all
    three layers
Given gitleaks and a SAST tool (semgrep or bandit) are both present on the
    machine
When the Security Review Pass runs
Then all three layers execute, including the presence-detected ones
And the PR body carries no "Security Review" section
And the workflow proceeds to Phase 4 with no termination
```

### US-4 — Clean diff on a scanner-less machine (this repo's current baseline)
```gherkin
Given the branch diff vs $BASE_BRANCH contains zero findings
Given gitleaks and every SAST tool are absent from the machine
When the Security Review Pass runs
Then the built-in deterministic scan (Layer 1) and the LLM security review
    (Layer 3) still execute in full
And gitleaks and SAST are silently skipped, with no error and no warning
    noise
And the PR body carries no "Security Review" section
```

### US-5 — Non-Critical findings surface without blocking
```gherkin
Given the branch diff contains one or more Medium or High severity findings
    from Layer 2 or Layer 3, and zero Critical findings
When the Security Review Pass evaluates them
Then none of them terminate the workflow, regardless of the configured
    enforcement tier
And each is recorded for the "Security Review" PR-body section
And the PR opens once Phase 5.4 is reached
```

### US-6 — Scanner absence is always disclosed alongside findings
```gherkin
Given the branch diff contains at least one finding
Given gitleaks is absent from the machine, while the built-in scan, the LLM
    review, and one SAST tool are present and ran
When the "Security Review" PR-body section is composed
Then it lists the built-in scan, the LLM review, and the SAST tool as
    layers that ran
And it lists gitleaks as skipped for absence
And it never states or implies that gitleaks-equivalent coverage occurred
```

### US-7 — No auto-fix, ever
```gherkin
Given the LLM security review (Layer 3) identifies a Critical finding (for
    example, an unvalidated SSRF redirect) with an available code-level fix
When the Security Review Pass processes this finding
Then it does NOT apply any edit to the working tree for this finding, under
    any configuration
And the finding is recorded as a flagged finding for the PR body, exactly
    like every other unresolved finding
```

### US-8 — smith-bugfix gains the deterministic secret scan pre-commit
```gherkin
Given a smith-bugfix run reaches Phase 7.1 (Commit)
Given the branch diff to be committed contains a planted test-pattern
    secret matching Layer 1's detection patterns
When Phase 7.1 runs
Then Layer 1's deterministic secret scan runs immediately before the
    commit step, using FR-16's unconditional terminate semantics for any
    Critical finding — mapped onto smith-bugfix's existing
    STOP-on-test-failure/scope-creep terminate convention, not a new
    mechanism
And Layer 2 (SAST) and Layer 3 (LLM review) do NOT run as part of
    smith-bugfix — they remain smith-build-only (FR-17)
And when the diff is clean, smith-bugfix's existing commit/push behavior
    (Phase 7.1/7.2) is otherwise unchanged
```

## Functional Requirements

### Insertion point & invocation (smith-build)

- **FR-1**: `smith-build` MUST run a new **Security Review Pass** as Phase
  3.6, strictly after Phase 3.5 (Clean Code Review Pass) has completed and
  strictly before Phase 4 (Spec Updates) begins — and therefore strictly
  before Phase 5.1's `git commit`. All three layers (deterministic secret
  scan, SAST, LLM security review) execute within this single phase.
- **FR-2**: Phase 3.6 MUST run exactly once per build, regardless of
  findings from Phase 3.5's own auto-fix/re-test cycle; it is gated on
  Phase 3.5 having completed as an ordering precondition, not a re-entrant
  loop.
- **FR-3**: The Security Review Pass MUST be invoked with the same
  `WORKTREE_PATH`/`BASE_BRANCH` context threading already used by Phase 3.5
  and later phases (the `BASE_BRANCH=$(.specify/scripts/bash/get-base-branch.sh)`
  pattern), and MUST diff against `$BASE_BRANCH` — never a hardcoded or
  inferred ref.

### Layer 1 — Deterministic secret scan

- **FR-4**: Layer 1 MUST ship as a new, dependency-free Smith script in the
  `scripts/` family, runnable under both bash and zsh, using `python3` for
  its regex engine. It MUST detect, at minimum: AWS/GCP-style access-key
  patterns, private-key PEM headers, token-shaped variable assignments
  (e.g. `*_key`, `*_token`, `*_secret` assigned a literal value), and
  high-entropy strings.
- **FR-5**: Layer 1 MUST exclude the same path families the existing
  §5.3/§5.3.1 scans exclude (`vendor/`, `node_modules/`, `.venv/`, `dist/`,
  `build/`, `.smith/`), plus a glob allowlist for known-noisy files
  (`package-lock.json`, `yarn.lock`) to bound false positives from
  high-entropy detection.
- **FR-6**: Layer 1 MUST ship with a companion test file under `tests/`
  mirroring the existing harness pattern used by scripts in this family
  (per-case PASS/FAIL output, a summary line, and a non-zero exit code if
  any case fails — consistent with `tests/get-base-branch.test.sh`).
- **FR-7**: When gitleaks is present on the machine (presence-detected via
  the shared helper, NFR-4), Layer 1 MUST also run it and merge its
  findings with the built-in scanner's; when gitleaks is absent, Layer 1
  MUST silently skip it and rely on the built-in scanner alone — gitleaks
  is additive defense-in-depth, never a replacement for the built-in
  scanner.
- **FR-8**: The Security Review Pass MUST function correctly with zero
  external scanners present (the exploration's confirmed current state of
  this development machine) — in that state, the built-in Layer 1 scanner
  and Layer 3's LLM review together constitute this feature's full
  coverage, and their absence-of-error is itself a requirement, not merely
  a fallback.

### Layer 2 — SAST (presence-detected)

- **FR-9**: Layer 2 (semgrep and/or bandit) MUST be presence-detected via
  the same shared helper as Layer 1's gitleaks check (NFR-4); it MUST run
  when found and MUST be silently skipped when absent. Neither tool may be
  added as an installed dependency of Smith or of any consuming project as
  part of this feature.

### Layer 3 — LLM security review

- **FR-10**: Layer 3 MUST always run, regardless of Layer 1/Layer 2
  scanner presence or findings — it is the only layer with guaranteed
  coverage on every machine.
- **FR-11**: Because Smith's built-in `/security-review` capability is not
  materialized on disk in this repository and cannot be cited or invoked
  as-is, this spec itself defines Layer 3's rubric, and Layer 3 does NOT
  additionally invoke the built-in `/security-review` capability in v1 (no
  built-in layer — this spec's own rubric is authoritative; may be
  revisited once this pass has mileage). The review subagent
  MUST evaluate the diff against, at minimum, these areas: injection
  (SQL/command/template), authentication/authorization flaws,
  secrets/credential handling, unsafe deserialization or `eval`-family use,
  path traversal, SSRF and unvalidated redirects, cryptographic misuse,
  sensitive-data logging or exposure, dependency-adjacent code smells
  (explicitly NOT dependency CVE/SCA scanning — see OOS-1), and
  race conditions/TOCTOU in security-relevant paths. The review subagent
  MUST run with `model: opus` by default; an optional `review_model` key
  in the `security_review` config schema (`data-model.md` §1) allows
  per-project override to `haiku`, `sonnet`, or `fable` (default `opus`) —
  rationale: Layer 3 is a bounded, once-per-build classification pass where
  miss-cost asymmetry favors strong reasoning by default, while `fable` is
  not universally available on every account tier, so it is opt-in only,
  never the shipped default.
- **FR-12**: Every finding, from any of the three layers, MUST carry
  exactly one severity (Critical/High/Medium/Low), `path:line`, a category
  label, a 1–2 sentence rationale, and the layer that found it — mirroring
  feature 54's findings contract with the addition of the layer field,
  needed here because three independent layers (vs. one) can produce
  findings.

### Findings handling & auto-fix policy

- **FR-13**: The Security Review Pass MUST NOT auto-fix any finding, from
  any layer, under any configuration, in this version. Rationale: unlike
  feature 54's clean-code polish fixes, a security fix is behavior-adjacent
  by nature (patching an injection point, tightening an authz check,
  rotating a credential reference) — auto-applying it risks shipping an
  incomplete or subtly wrong fix with no human or reviewing-agent
  confirmation that the vulnerability is actually closed. Every finding
  from every layer is therefore a flagged finding.

### Enforcement tier & termination semantics

- **FR-14**: A config-driven enforcement tier, read from the new
  `security_review` key in `.smith/config.json` (see FR-23), MUST govern
  whether a qualifying finding from Layer 2 (SAST) or Layer 3 (LLM review)
  is flag-only or blocking. `enforcement_tier` accepts exactly two values:
  `flag` (the shipped default — SAST/LLM findings are advisory) and
  `block_on_critical` (opt-in — a Critical SAST/LLM finding terminates the
  workflow). This tier does NOT govern Layer 1 (secret) findings, which
  are subject to FR-16's separate, unconditional rule regardless of this
  setting.
- **FR-15**: Wherever "block" applies to a finding, `smith-build` MUST
  implement it as: terminate the workflow before Phase 4 (Spec Updates)
  begins — meaning Phase 5.1 (Commit) and Phase 5.2 (Push) never execute
  for this run — write a hard-stop marker to the vault session log, and
  ensure the eventual release notes/final summary record the stop. A
  hard-stop MUST NEVER be implemented as a synchronous prompt or
  confirmation of any kind; `smith-build` has no mid-stream pause
  mechanism and this feature introduces none. This mirrors smith-bugfix's
  existing STOP-on-test-failure/scope-creep terminate semantics (a full
  stop, not a pause) — not smith-build Phase 2's interactive-pause style —
  and is distinct from the browser-verification production confirm-gate,
  which is an action-level gate, not a pipeline-level one.
- **FR-16**: Layer 1 (secret) Critical findings ALWAYS hard-stop, regardless
  of the configured `enforcement_tier` — an unconditional override with no
  config-driven opt-out or bypass. This is the system's second
  non-bypassable denial (the first is the browser-production confirm-gate,
  FR-15); unlike that gate, this override has no runtime-confirmation
  escape hatch — the allowlist marker (a per-line `# smith-secret-scan:
  allow` comment; `research.md` §8) is the sole false-positive remedy,
  applied before the scan runs, not after a finding is produced. This
  override MUST use the exact same terminate semantics defined in FR-15;
  this feature introduces no second termination mechanism.
- **FR-17**: `smith-bugfix`'s Phase 7.1 (Commit) MUST run Layer 1's
  deterministic secret scan immediately before its existing commit step,
  applying FR-16's exact terminate semantics to any Critical finding —
  mapped onto `smith-bugfix`'s existing STOP-on-test-failure/scope-creep
  terminate convention rather than introducing a second termination
  mechanism. Layer 2 (SAST) and Layer 3 (LLM review) do NOT run as part of
  `smith-bugfix`; both remain `smith-build`-only, preserving
  `smith-bugfix`'s lightweight pipeline.

### PR-body reporting

- **FR-18**: Every finding that does not cause termination (FR-15) MUST be
  recorded to a scratch file, following the same
  scan → `/tmp` file → conditionally-included pattern already used by
  Phase 3.5 and the §5.3/§5.3.1 scans.
- **FR-19**: When that scratch file is non-empty, the PR body template
  (§5.4) MUST gain a "Security Review" section. Medium, High, and Critical
  findings are each listed individually (severity, `path:line`, category,
  rationale, layer); Low-severity findings are NOT listed individually —
  they are folded into a single one-line count ("+ N low-severity notes")
  appended after the individually-listed findings, mirroring feature 54's
  FR-16 threshold convention exactly.
- **FR-20**: Whenever the "Security Review" section is included, it MUST
  explicitly state which of the three layers executed and which were
  skipped for absence (Layer 1's gitleaks sub-check, Layer 2 entirely, or
  neither) — regardless of which layer(s) actually produced the listed
  findings — so the section never states or implies full-coverage scanning
  when a presence-detected layer was actually absent.
- **FR-21**: When the scratch file is empty (zero non-terminating findings
  across all three layers), the "Security Review" section MUST be omitted
  entirely from the PR body — matching the existing omit-when-empty
  behavior of §5.3, §5.3.1, and Phase 3.5's "Clean Code Review" section.
- **FR-22**: Once Phase 3.6 completes without triggering a hard-stop (FR-15),
  no finding recorded to the PR body may subsequently block, delay, or gate
  PR creation at Phase 5.4 — the only point at which this feature's
  findings can halt the workflow is the hard-stop decision made in Phase
  3.6 itself.

### Configuration

- **FR-23**: A NEW top-level `security_review` key MUST be added to
  `.smith/config.json` (the file `templates/config.default.json` actually
  seeds, and the one Smith's existing config-consuming code reads at
  runtime). This key is explicitly NOT the pre-existing `security` block
  already present in the same file (which the exploration confirmed no
  guard hook reads) and NOT `.smith/security-config.json` (which the three
  `security-guard-*.sh` hooks do read) — see BANK-027
  (`.smith/vault/bank/2026-09-13_120000-unify-security-config-seeding.md`).
  This feature MUST NOT deepen that existing three-location split by
  introducing a fourth config file or by repurposing the orphaned
  `security` block.
- **FR-24**: The `security_review` schema ships exactly as proposed in
  `data-model.md` §1 — `enforcement_tier`, `layers` (per-layer enable
  flags, all default `true`), `excludes`, `allowlist_globs` — plus the new
  `review_model` key (FR-11). No further schema depth (e.g. separate
  per-layer enforcement tiers) ships in v1. The key exists at the top level
  of `.smith/config.json` and is the sole documented config home for this
  feature's settings.

## Non-Functional Requirements

- **NFR-1**: The Security Review Pass, including every hard-stop path,
  MUST run without any user interaction of any kind — no prompts,
  confirmations, or pauses — consistent with `smith-build`'s "ALL phases
  run without user interaction" rule. A hard-stop is communicated via the
  session log and release notes/final summary, never via a prompt.
- **NFR-2**: All shell snippets added or modified in
  `skills/smith-build/SKILL.md` for this feature, and the new Layer 1
  script itself, MUST run correctly under both `bash` and `zsh` (no
  bash-only array syntax, no bare unquoted globs), matching the repo's
  existing shell-content convention.
- **NFR-3**: The Security Review Pass MUST run at most once per build.
  No layer, and no enforcement-tier decision, introduces a retry,
  re-scan, or re-review loop — the step count is deterministic and bounded
  independent of how many findings are found (one review, per layer, per
  build; a hard-stop ends the build rather than looping).
- **NFR-4**: Presence detection for external, optional tools (gitleaks for
  Layer 1, semgrep/bandit for Layer 2) MUST be implemented as a single
  reusable helper, not duplicated ad hoc per caller. This helper MUST be
  designed for reuse beyond this feature — specifically by the future
  dependency-CVE/SCA feature (F2, out of scope here — OOS-1) and by
  `smith-audit`'s existing Security sub-audit — so scanner-presence
  detection has exactly one implementation and multiple consumers.
- **NFR-5**: This feature MUST NOT modify `skills/smith-clean-code/SKILL.md`,
  the three existing `security-guard-*.sh` hooks
  (`security-guard-bash.sh`, `security-guard-files.sh`,
  `security-guard-mcp-browser.sh`), or `smith-audit`'s SKILL.md/sub-audit
  logic. All three are read-only inputs or unaffected neighbors, not
  targets of this feature's changes.
- **NFR-6**: A hard-stop (FR-15) MUST be an all-or-nothing full workflow
  stop — it MUST NOT leave the workflow in a partial state where some
  later phases run and others are silently skipped; once triggered, no
  further `smith-build` phase for this run executes.

## Out of Scope

- **OOS-1 — Dependency CVE/SCA and license scanning.** Tools like
  osv-scanner, pip-audit, and grype, and license-compliance checking, are
  entirely out of scope for this feature — they belong to a future F2
  feature. Layer 3's rubric explicitly excludes CVE scanning from its
  "dependency-adjacent code smells" area (FR-11) to keep this boundary
  unambiguous.
- **OOS-2 — The three existing security-guard hooks.**
  `security-guard-bash.sh`, `security-guard-files.sh`, and
  `security-guard-mcp-browser.sh` are unmodified by this feature (NFR-5).
  They read a separate config file (`.smith/security-config.json`) from
  this feature's `security_review` key (FR-23) and operate at a different
  layer (PreToolUse guards vs. a build-pipeline review pass).
- **OOS-3 — `smith-audit` itself, including its Security sub-audit.**
  Unmodified by this feature (NFR-5). It remains complementary — whole-
  system and on-demand, versus this feature's diff-scoped, every-build
  scope — sharing only the scanner-presence-detection helper (NFR-4).
- **OOS-4 — Auto-fixing any security finding, under any configuration, in
  this version.** Every finding from every layer is flagged, never
  auto-applied (FR-13).
- **OOS-5 — Modifying the Clean Code Review Pass (Phase 3.5) itself.**
  This feature only runs after it completes (FR-1/FR-2); Phase 3.5's own
  rubric, auto-fix policy, and re-test loop are untouched.

## Assumptions

- **A-1**: The pre-feature exploration
  (`.smith/vault/explore/explore-2026-09-13-security-review-pass.md`)
  found no blocking conflicts; its 8 findings are design constraints
  resolved by encoding them into this spec, confirmed by this feature's
  requirements checklist.
- **A-2**: This repository's current development machine has zero security
  scanners installed (gitleaks, trufflehog, semgrep, bandit, osv-scanner,
  pip-audit, and grype are all absent; only `npm` is present). This is
  treated as the expected common case, not an edge case — presence
  detection with silent-skip and explicit layer disclosure (FR-7, FR-9,
  FR-20) is this feature's primary design response, not a fallback path.
- **A-3**: BANK-027
  (`.smith/vault/bank/2026-09-13_120000-unify-security-config-seeding.md`)
  already tracks an unresolved split between `.smith/config.json`'s
  orphaned `security` block and the guard-hooks-read
  `.smith/security-config.json`. This feature's new `security_review` key
  (FR-23) is a third, deliberately distinct location; unifying the
  pre-existing split remains BANK-027's own, separately scheduled scope —
  this feature must not worsen it, but is not the vehicle for fixing it.
- **A-4**: `smith-audit`'s existing Security sub-audit already establishes
  that whole-system security scanning has a home in Smith; this feature is
  a narrower, diff-scoped, every-build complement, not a replacement or a
  duplication (NFR-4, OOS-3).
- **A-5**: `WORKTREE_PATH`/`BASE_BRANCH` threading and the
  `get-base-branch.sh` resolution helper are already established
  conventions available to any `smith-build` phase (used by Phase 3.5,
  Phase 4, and Phase 5 today); this feature reuses that convention rather
  than introducing new context-threading machinery (FR-3).
- **A-6 — Endpoint.** Per this feature's `/smith-new` workflow, feature 55
  was QUEUED after its questions gate; the gate has since been answered
  (`questions.md`, ANSWERED, 2026-09-13) — this feature is not yet built in
  this session, but every decision below is now resolved, not deferred.
- **A-7 — RESOLVED at the questions gate (`questions.md`, 2026-09-13).**
  The following decisions were intentionally left open by this spec's
  first draft; all six are now resolved with these outcomes:
  1. **RESOLVED (Q1):** Default enforcement tier is `flag` for Layer 2/3
     (SAST/LLM) findings; `block_on_critical` is opt-in via config (FR-14).
  2. **RESOLVED (Q2):** Layer 1 (secret) Critical findings ALWAYS hard-stop,
     regardless of the configured tier — a stricter, non-bypassable
     override; the allowlist marker is the sole false-positive escape
     hatch (FR-16).
  3. **RESOLVED (Q3):** Layer 3 does NOT additionally invoke Smith's
     built-in `/security-review` in v1; this spec's own rubric (FR-11) is
     authoritative, no built-in layer this version.
  4. **RESOLVED (Q4):** The Layer 3 review-subagent model defaults to
     `opus`; an optional `review_model` config key (haiku|sonnet|opus|
     fable, default `opus`) allows per-project override (FR-11).
  5. **RESOLVED (Q5):** smith-bugfix's Phase 7.1 gains this feature's
     pre-commit deterministic secret-scan gate (Layer 1 only, FR-16
     semantics); Layer 2/3 remain `smith-build`-only (FR-17).
  6. **RESOLVED (Q6):** The `security_review` config schema ships exactly
     as originally proposed (`data-model.md` §1: `enforcement_tier`,
     `layers`, `excludes`, `allowlist_globs`), plus the new `review_model`
     key from Q4 (FR-24).

## Success Criteria

- **SC-1**: A branch diff containing a planted test-pattern secret always
  has that finding surface, as Critical severity, before Phase 4 begins —
  in every build, and always terminates the workflow (FR-16); this outcome
  is unconditional, not tier-dependent. A branch diff containing a
  Critical-severity Layer 2/3 (SAST/LLM) finding instead surfaces the same
  way but only terminates when `enforcement_tier` is `block_on_critical`
  (FR-14's opt-in, default-`flag` posture); at the default `flag` tier it
  is recorded for the PR body without terminating.
- **SC-2**: A branch diff with zero findings across all three layers
  produces no "Security Review" PR-body section, and triggers no
  hard-stop.
- **SC-3**: On a machine with zero external scanners installed (this
  repository's confirmed current state), the Security Review Pass still
  provides full coverage from Layer 1's built-in scanner and Layer 3's LLM
  review; any populated "Security Review" section on such a machine
  explicitly lists gitleaks and SAST as skipped for absence and never
  implies their coverage occurred.
- **SC-4**: Every Security Review Pass execution, across all three layers
  and both enforcement outcomes (flag or hard-stop), presents zero
  prompts, confirmations, or pauses to the user — a hard-stop is always
  logged, never asked.
- **SC-5**: Across all Security Review Pass executions, each layer runs at
  most once per build; no configuration or finding count causes a second
  review, re-scan, or retry.
- **SC-6**: The `security_review` key is the only new config surface this
  feature introduces to `.smith/config.json`; the pre-existing orphaned
  `security` block and the separate `.smith/security-config.json` are left
  exactly as BANK-027 found them — neither worsened nor silently
  repurposed by this feature.
