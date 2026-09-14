# Specification Quality Checklist: 55-security-review-pass

**Purpose**: Validate specification completeness before planning/implementation
**Created**: 2026-09-13
**Feature**: [spec.md](../spec.md)

## Content Quality
- [x] Focused on user value and business need (generated diffs get scanned
      for security issues before they ship — and before a secret can even
      reach `git commit` — rather than shipping with no security-specific
      verification at all) rather than implementation mechanics
- [x] All mandatory sections completed (Overview, Problem Statement, User
      Scenarios, Functional Requirements, Non-Functional Requirements, Out
      of Scope, Assumptions, Success Criteria)
- [x] Written for reviewers, not just implementers — Overview defines
      "Layer", "Security Review Pass", "Finding",
      "Presence-detected/silent-skip", "Enforcement tier", and "Hard-stop"
      before they're used in requirements
- [x] Artifacts named (files/paths, phase numbers, line ranges) only where
      the feature is inherently about specific integration points
      (`smith-build` phase boundaries 3.5/3.6/4/5.1/5.2, `.smith/config.json`
      vs. `.smith/security-config.json`, the PR-body template) — no HOW
      (regex patterns, entropy-detection algorithm, subagent prompt text)
      leaks in

## Requirement Completeness
- [x] Zero `[NEEDS CLARIFICATION]` markers remain anywhere in spec.md
      (verified: `grep -c "NEEDS CLARIFICATION" spec.md` → 0)
- [x] Every FR (FR-1..FR-24) is independently testable — each names a
      concrete condition and an observable pass/fail outcome (a phase
      running/not running, a layer running/skipped, a finding
      flagged/blocking, a PR section present/omitted, a config key
      present/absent)
- [x] No FR depends on a vague qualifier without a concrete rule attached
      (verified: `grep -niE "appropriately|as needed|reasonable|properly|sufficiently"
      spec.md` → no matches)
- [x] Success criteria (SC-1..SC-6) are measurable and technology-agnostic
      outcomes, each traceable to at least one FR: SC-1→FR-1/FR-14/FR-15
      (surfacing is unconditional; blocking is gate-decided, phrased so
      the criterion is verifiable under either resolution), SC-2→FR-21,
      SC-3→FR-8/FR-20, SC-4→FR-15/NFR-1, SC-5→NFR-3, SC-6→FR-23
- [x] All 8 user scenarios (US-1..US-8) are Gherkin Given/When/Then and
      cover: the flag-outcome primary flow, the block-outcome hard-stop
      flow, a clean diff with scanners present, a clean diff with scanners
      absent, non-Critical findings proceeding, scanner-absence disclosure
      alongside real findings, the no-auto-fix invariant, and smith-bugfix
      being explicitly unaffected pending the gate
- [x] Edge cases identified: tier resolves to block mid-pipeline (US-2/
      FR-15/FR-16), zero-scanner machine (US-4/FR-8), presence-detected
      layer absent while others found something (US-6/FR-20), a
      Critical/fixable LLM finding that must still never be auto-applied
      (US-7/FR-13)
- [x] Scope is explicitly bounded — Out of Scope names all five excluded
      areas (OOS-1..OOS-5) with the structural reason each is excluded,
      not just a bare "not doing this"
- [x] Dependencies and assumptions identified (A-1..A-7), including the
      exploration's no-blocking-conflicts finding (A-1), the zero-scanner
      baseline machine state (A-2), and the BANK-027 cross-reference (A-3)

## Exploration Findings Traceability

Every finding from the pre-feature exploration
(`.smith/vault/explore/explore-2026-09-13-security-review-pass.md`) is a
binding design constraint. Each is traced below to the FR(s)/NFR(s) that
encode it — none are left as unencoded narrative.

- [x] **Finding 1** (secret scan MUST run pre-commit; SAST/LLM findings may
      use post-scan-style PR formatting) → **FR-1** (Phase 3.6 runs before
      Phase 4, therefore before Phase 5.1's `git commit`, for all three
      layers including Layer 1), **FR-15** (hard-stop happens before Phase
      4/5.1/5.2 ever execute), **FR-18/FR-19** (non-terminating findings —
      including advisory SAST/LLM findings — use the same
      scratch-file → conditional-PR-section pattern as §5.3/§5.3.1)
- [x] **Finding 2** (this machine has zero scanners; external scanners are
      presence-detected/silent-skip; PR section must name which layers
      ran) → **FR-7** (gitleaks presence-detected), **FR-9** (SAST
      presence-detected), **FR-8** (pipeline must function correctly with
      zero external scanners), **FR-20** (section always lists ran vs.
      skipped-absent layers), **A-2** (zero-scanner baseline stated as the
      expected common case)
- [x] **Finding 3** (minimal built-in regex secret scan + tests
      recommended; gitleaks layered on top; LLM is the weakest layer for
      secrets specifically) → **FR-4** (new dependency-free `scripts/`
      family script, bash+zsh-safe, python3 regex engine, named detection
      patterns), **FR-5** (exclude-path list + noisy-file allowlist),
      **FR-6** (companion `tests/` file mirroring the existing harness
      pattern), **FR-7** (gitleaks layered on top when present, never a
      replacement for the built-in scanner)
- [x] **Finding 4** (built-in `/security-review` is not citable; spec must
      define its own rubric; optionally invoking the built-in is a fresh
      gate decision) → **FR-11** (this spec enumerates the full 10-area
      Layer 3 rubric from scratch), **A-7 item 3** (whether to additionally
      invoke the built-in `/security-review` is deferred to the gate,
      explicitly not pre-empted by FR-11's wording)
- [x] **Finding 5** (config home: new `security_review` key in
      `.smith/config.json`; NOT the orphaned `security` block, NOT
      `.smith/security-config.json`; cross-reference BANK-027) →
      **FR-23** (states the key, its file, and both exclusions by name),
      **FR-24** (schema depth deferred without reopening the file/key
      decision itself), **A-3** (explicit BANK-027 cross-reference and
      non-worsening commitment)
- [x] **Finding 6** (enforcement-tier autonomous semantics: no mid-stream
      pause exists; block-on-Critical means terminate-before-commit/push +
      hard-stop marker in session log/release notes; never a synchronous
      prompt; distinguish from bugfix's STOP semantics and from the
      browser action-gate precedent) → **FR-14** (tier mechanism and its
      config home), **FR-15** (full terminate-before-Phase-4 semantics,
      hard-stop marker, never a prompt, explicit precedent comparison),
      **FR-16** (secrets-specific override uses the same mechanism, no
      second one introduced), **NFR-1** (zero user interaction including
      during a hard-stop), **NFR-6** (all-or-nothing stop, no partial
      execution)
- [x] **Finding 7** (smith-audit's Security sub-audit is complementary,
      whole-system/on-demand vs. this feature's diff-scoped/every-build;
      share one scanner-presence-detection implementation with it and
      future F2) → **NFR-4** (single reusable presence-detection helper,
      explicitly named for reuse by F2 and smith-audit), **OOS-3**
      (smith-audit itself unmodified by this feature), **A-4** (states the
      complementary relationship explicitly)
- [x] **Finding 8** (dependency CVE/SCA and license scanning are out of
      scope — F2's territory) → **OOS-1** (explicit exclusion, structural
      reason given), **FR-11** (Layer 3's rubric explicitly carves
      "dependency-adjacent code smells" apart from CVE scanning so the
      boundary can't be blurred by an implementer)

## Deferred-Decisions Traceability
- [x] Assumptions §A-7 lists all six items the feature description
      explicitly named as open (default enforcement tier, secrets-always-
      hard-stop override, built-in `/security-review` invocation, Layer 3
      model choice, smith-bugfix parity, `security_review` schema depth)
      as an explicit "Deferred to questions gate" list, not as
      `[NEEDS CLARIFICATION]` markers
- [x] Every deferred item has a corresponding FR that states the
      requirement generically enough to remain true under either
      resolution (FR-14/FR-16 for the tier and its secrets override;
      FR-11 for the built-in-invocation question; no FR asserts a specific
      Layer 3 model, a specific bugfix-inclusion answer, or a specific
      config sub-schema — each is left open until the gate)
- [x] No FR, NFR, or success criterion contradicts a deferred item's
      openness (verified: FR-14 requires "a mechanism exists," not a
      specific default; FR-17 explicitly scopes this spec's requirements
      to smith-build only pending the smith-bugfix gate answer, consistent
      with not pre-empting it; SC-1 is phrased so it holds whether the
      gate resolves to flag or to block)

## Out-of-Scope Explicitness
- [x] The dependency-CVE/SCA/license exclusion states the structural
      reason (belongs to a distinct future feature, F2) and is reinforced
      by FR-11's rubric carve-out, not just "not doing this" (OOS-1)
- [x] The three existing security-guard hooks are named individually by
      filename and distinguished by config file and hook layer (PreToolUse
      guard vs. build-pipeline review pass) from this feature's scope
      (OOS-2)
- [x] `smith-audit` and its Security sub-audit are named as unmodified and
      complementary, with the one shared surface (the presence-detection
      helper) called out explicitly rather than left ambiguous (OOS-3,
      reinforced by NFR-4/A-4)
- [x] The no-auto-fix rule is stated both as a firm FR with rationale
      (FR-13) and restated in Out of Scope (OOS-4), so a reader encountering
      either section independently gets the same rule
- [x] Phase 3.5 (Clean Code Review Pass) is named as untouched, with the
      ordering relationship (this feature runs after it) stated as the
      reason it doesn't need modification (OOS-5)

## Feature Readiness
- [x] All three stated deliverables (pre-commit secret scan, presence-
      detected SAST, always-on LLM review) map to at least one FR group
      each: Layer 1 → FR-4..FR-8; Layer 2 → FR-9; Layer 3 → FR-10..FR-12
- [x] The enforcement-tier and config deliverables each map to their own
      FR group: enforcement tier → FR-14..FR-17; configuration →
      FR-23..FR-24; PR-body reporting → FR-18..FR-22
- [x] No FR, scenario, or success criterion contradicts another (verified:
      the flag/block split in FR-15/FR-16 is consistent across US-1/US-2;
      the always-runs-Layer-3 claim in FR-10 is consistent with US-4; the
      omit-when-empty rule in FR-21 is consistent with US-3/US-4; the
      no-auto-fix rule in FR-13 is consistent with US-7)
- [x] Constraints supplied by the user (pre-commit placement as a hard
      requirement, dependency-free bash+zsh script + tests, presence-
      detection for external scanners, the specific Layer 3 rubric areas,
      the 5.3-family PR formatting threshold, the BANK-027 config
      cross-reference, no auto-fix in v1) are each present as FR-1, FR-4/
      FR-6, FR-7/FR-9, FR-11, FR-19, FR-23, and FR-13 respectively — none
      were dropped
- [x] Ready for planning: every FR is specific enough to size and
      sequence, and every FR has a corresponding user scenario or success
      criterion to verify against in plan.md/tasks.md

## Notes
- Verified against this feature's own spec.md in 1 iteration. The
  `[NEEDS CLARIFICATION]`-marker and vague-qualifier greps were run
  directly against the written file (not asserted from memory) and both
  returned zero matches, so no revision cycle was needed before this
  checklist could be marked complete.
- This feature differs from feature 54 in one structural way this
  checklist verifies deliberately: feature 54's NFR-3 asserted
  flag-never-block as an absolute invariant, but this feature's
  enforcement tier can legitimately block (FR-15). The equivalent
  invariant here is autonomy-preservation, not never-blocking: NFR-1 and
  FR-15 together require that blocking, when it happens, is a full
  workflow stop logged to the session log/release notes — never a
  synchronous prompt — so the "no user interaction" property from feature
  54 is preserved even though "never blocks" is not. Confirmed no FR/NFR
  in this spec accidentally asserts flag-never-block language that would
  contradict FR-14/FR-15's tiered design.
- The six deferred decisions were deliberately kept out of the FRs rather
  than defaulted, per the feature description's explicit instruction not
  to pre-empt them; this checklist's "Deferred-Decisions Traceability"
  section confirms that restraint was honored in the written requirements,
  and the "Exploration Findings Traceability" section confirms all 8
  exploration findings are encoded rather than merely acknowledged.
