# Specification Quality Checklist: 57-quality-metrics-pack

**Purpose**: Validate specification completeness before planning/implementation
**Created**: 2026-09-14
**Feature**: [spec.md](../spec.md)

## Content Quality
- [x] Focused on user value and business need (generated builds get
      config-driven test/lint/typecheck execution, coverage visibility, and
      function-length visibility, with zero behavior change for any project
      not yet configuring `quality`) rather than implementation mechanics
- [x] All mandatory sections completed (Overview, Problem Statement, User
      Scenarios, Functional Requirements, Non-Functional Requirements, Out
      of Scope, Assumptions, Success Criteria)
- [x] Written for reviewers, not just implementers — Overview defines
      "Quality command", "Legacy fallback", "Coverage check",
      "Function-Length Scan", "Advisory", and "Trust domain" before they're
      used in requirements
- [x] Artifacts named (files/paths, phase/section numbers) only where the
      feature is inherently about specific integration points
      (`smith-build` §3.1/§3.1b/§3.1c/§3.4/§5.3.2/§5.4, `smith-bugfix` §5.3,
      `.smith/config.json`'s `quality` key vs. `security_review`/
      `supply_chain`, `scripts/parsers/meta_describe.py`'s
      `qualifying_methods()`) — no HOW (exact regex internals beyond the
      three named patterns, script internals) leaks in beyond what the
      feature description itself specified

## Requirement Completeness
- [x] Zero `[NEEDS CLARIFICATION]` markers remain anywhere in spec.md
      (verified: `grep -c "NEEDS CLARIFICATION" spec.md` → 0)
- [x] Every FR (FR-1..FR-22) is independently testable — each names a
      concrete condition and an observable pass/fail outcome (a command
      run/skipped, a fallback used/not used, a finding produced/folded/
      omitted, a PR section present/omitted, a config key present/absent)
- [x] No FR depends on a vague qualifier without a concrete rule attached
      (verified: `grep -niE "appropriately|as needed|reasonable|properly|
      sufficiently" spec.md` → no matches)
- [x] Success criteria (SC-1..SC-6) are measurable and technology-agnostic
      outcomes, each traceable to at least one FR: SC-1→FR-1/FR-3/FR-4,
      SC-2→FR-2/FR-7, SC-3→FR-10/FR-11, SC-4→FR-13, SC-5→FR-16/FR-17,
      SC-6→FR-18/FR-19
- [x] All 6 user scenarios (US-1..US-6) are Gherkin Given/When/Then and
      cover: configured `quality.test` commands running instead of the
      fallback, the absent-key zero-behavior-change case, the
      `smith-bugfix` Lint parity generalization, a coverage-below-minimum
      finding, unparseable coverage output disclosed without failing, and
      the decompose-vs-soft-tier function-length split
- [x] Edge cases identified: `quality` key wholly absent (US-2/FR-2/FR-7),
      `quality.lint`/`quality.typecheck` absent in `smith-build` with no
      legacy fallback to fall back to (FR-3/FR-4), coverage configured but
      `minimum_percent` absent — informational only, no finding (FR-12),
      coverage output matching neither the catalogue nor an override
      (US-5/FR-13), a command exceeding `quality.timeout_seconds` (FR-1/
      FR-14)
- [x] Scope is explicitly bounded — Out of Scope names all four excluded
      areas (OOS-1..OOS-4) with the structural reason each is excluded, not
      just a bare "not doing this"
- [x] Dependencies and assumptions identified (A-1..A-5), including the
      exploration's no-blocking-conflicts finding (A-1), the
      `qualifying_methods()` reuse-without-parser-changes decision (A-2),
      the `timeout_seconds` default rationale (A-3), and the trust-domain
      documentation stance (A-4)

## Exploration Findings Traceability

Every finding from the pre-feature exploration
(`.smith/vault/explore/explore-2026-09-14-quality-metrics-pack.md`) is a
binding design constraint. Each is traced below to the FR(s)/NFR(s)/
Assumption(s) that encode it — none are left as unencoded narrative.

- [x] **Finding 1** (function-length data: no parser/schema change needed
      — reuse `meta_describe.py`'s `qualifying_methods()` next-entry-start
      derivation; a parser `end_line` addition would force schema v3,
      rejected for v1) → **FR-16** (calls `qualifying_methods()` unchanged,
      no new parser fields), **NFR-4** (parsers explicitly unmodified),
      **OOS-2** (parser schema changes named out of scope), **A-2**
      (reuse-without-forking rationale stated)
- [x] **Finding 2** (§3.1/§5.3 hardcoded commands are Armory leftovers,
      same category a prior generalization already addressed elsewhere in
      this pipeline: generalize IN PLACE, config-driven with verbatim
      hardcoded fallback when absent — zero behavior change) → **FR-1**
      (§3.1 generalized in place), **FR-2** (absent-key verbatim fallback),
      **FR-6** (§5.3 generalized in place), **FR-7** (absent-key verbatim
      fallback), **A-5 item 1** (Q1, recommendation named and
      evidence-backed)
- [x] **Finding 3** (config: new top-level `quality` key with the stated
      shape; three-site seeding — template + init + update §5.1e) →
      **FR-21** (states the key, its shape, and the
      not-nested-under-`security_review` decision), **FR-22** (three-site
      seeding mechanism, `§5.1e` explicitly named), **A-5 item 2** (Q2,
      recommendation named)
- [x] **Finding 4** (Function-length scan = §5.3.2 sibling to §5.3/§5.3.1;
      inline-python per §5.3.1 precedent importing `qualifying_methods`;
      two-tier thresholds 50 soft/100 decompose mirroring the File Size
      Policy shape, config-overridable; "Function Length Warnings" PR
      section) → **FR-15** (§5.3.2 positioned as §5.3.1's sibling, reusing
      its scan infrastructure), **FR-16** (two-tier bucketing against
      `quality.function_length`), **FR-17** (individual decompose listings,
      folded soft-tier count), **FR-18** (conditional PR section),
      **A-5 item 3** (Q3, recommendation named)
- [x] **Finding 5** (coverage: built-in regex catalogue — pytest-cov/
      jest-istanbul/go — plus config override; absent config → skip step
      entirely) → **FR-9** (skip entirely when `coverage.command` absent),
      **FR-10** (the three named regexes, override-tried-first), **A-5
      item 4** (Q4, recommendation named)
- [x] **Finding 6** (scope: build + bugfix only; `smith-implement` defers
      to caller, workflow-gate enforced invocation context) → **FR-6**
      (only §5.3 Lint reaches `smith-bugfix`), **FR-8** (`smith-bugfix`
      explicitly gains no coverage/function-length pieces), **OOS-1**
      (`smith-implement` named out of scope with its own structural
      reason), **A-5 item 5** (Q5, recommendation named)
- [x] **Finding 7** (risk posture: config-declared commands are the same
      trust domain as `package.json` scripts already executed — document,
      don't gate; reuse the subprocess timeout pattern, default 120s) →
      **A-4** (trust-domain documentation, no sandbox/approval gate
      added), **FR-1/FR-14** (the reused `subprocess.run(...,
      timeout=N)` mechanism), **NFR-3** (every invocation timeout-bounded)

## Deferred-Decisions Traceability
- [x] Assumptions §A-5 lists all five items the exploration's own "Gate
      recommendations" line named (Q1 generalize-in-place, Q2 `quality` key
      shape, Q3 50/100 two-tier, Q4 regex catalogue+override, Q5
      build+bugfix scope) as a "RESOLVED at questions gate (delegation)"
      list, each carrying its recommended-and-accepted resolution and the
      exploration finding backing it
- [x] Every resolved item has a corresponding FR/OOS that states the
      requirement concretely: FR-1/FR-2 (Q1), FR-21/FR-22 (Q2), FR-16/FR-17
      (Q3), FR-9/FR-10 (Q4), FR-6/FR-8/OOS-1 (Q5) — each traces back to
      A-5's named recommendation
- [x] No FR, NFR, or success criterion contradicts a resolved item's
      accepted status (verified: every A-5 sub-item is phrased "Outcome:
      <X> (accepted)" with its rationale, matching `questions.md`'s own
      ANSWERED status and this workflow's delegation model)

## Out-of-Scope Explicitness
- [x] The `smith-implement` exclusion names the structural reason (no
      independent PR/commit step of its own; workflow-gate enforced
      invocation context routes it through whichever caller's own pipeline
      applies) rather than a bare "not doing this" (OOS-1)
- [x] Parser-schema-change exclusion is stated as both a firm FR (FR-16's
      "unchanged" language, NFR-4) and restated in Out of Scope (OOS-2), so
      a reader encountering either section independently gets the same rule
- [x] The flag-only/no-blocking-gate scope is stated as both a firm NFR
      (NFR-2) and restated in Out of Scope (OOS-3)
- [x] Complexity metrics beyond length are named as explicitly excluded
      (a stated future candidate) rather than merely absent from the FRs
      (OOS-4)

## Feature Readiness
- [x] Each of the six delivery areas maps to its own FR group: `smith-build`
      testing generalization → FR-1..FR-5; `smith-bugfix` lint
      generalization → FR-6..FR-8; coverage check → FR-9..FR-14;
      function-length scan → FR-15..FR-18; PR-body reporting → FR-19..FR-20;
      configuration → FR-21..FR-22
- [x] No FR, scenario, or success criterion contradicts another (verified:
      the absent-key-preserves-fallback claim in FR-2/FR-7 is consistent
      with US-2; the no-fallback-for-lint/typecheck-in-smith-build claim in
      FR-3/FR-4 does not contradict FR-2's fallback claim, since FR-2
      scopes the fallback to `quality.test` specifically; the
      never-blocks claim in NFR-2/OOS-3 is consistent with US-4/US-5)
- [x] Constraints supplied by the feature description (generalize §3.1/
      §5.3 in place with a verbatim fallback, the `quality` config shape,
      the coverage regex-catalogue-plus-override approach, the two-tier
      50/100 function-length thresholds, the §5.3.2 placement, the
      flag-never-block posture, the three-site config seeding, the
      trust-domain documentation note) are each present as FR-1/FR-2,
      FR-21, FR-10, FR-16, FR-15, NFR-2, FR-22, and A-4 respectively — none
      were dropped
- [x] Ready for planning: every FR is specific enough to size and
      sequence, and every FR has a corresponding user scenario or success
      criterion to verify against in plan.md

## Notes
- Verified against this feature's own spec.md in 1 iteration. The
  `[NEEDS CLARIFICATION]`-marker and vague-qualifier greps were run
  directly against the written file (not asserted from memory), and the
  FR/NFR/OOS/SC numbering was independently counted to confirm no gaps or
  duplicates before this checklist could be marked complete: 22 FRs
  (FR-1..FR-22, no gaps), 5 NFRs, 4 OOS items, 6 SC items, 6 user
  scenarios.
- This feature's spec.md is written in its POST-questions-gate, RESOLVED
  shape (mirroring feature 56's own post-gate spec.md, `answers_applied`
  set), since this workflow's standing delegation had already accepted all
  five gate recommendations before this artifact pass began — there is no
  separate pre-gate draft for this feature.
- This feature is deliberately narrower than 54/55/56: no new phase is
  inserted into `smith-build`'s top-level `## Phase N:` sequence (every
  change is a new or generalized SECTION inside the existing Phase 3 and
  Phase 5, `§3.1b`/`§3.1c`/`§3.4`/`§5.3.2`, mirroring the `§5.1b`/`§5.1c`/
  `§5.1d` lettered-insertion idiom `skills/smith-update/SKILL.md` already
  uses rather than adding a numbered `## Phase 3.8:`), and no new Python
  orchestrator script is introduced — the Function-Length Scan reuses
  `meta_describe.py` in place exactly as §5.3.1 already imports it inline.
