# Specification Quality Checklist: 56-supply-chain-gate

**Purpose**: Validate specification completeness before planning/implementation
**Created**: 2026-09-13
**Feature**: [spec.md](../spec.md)

## Content Quality
- [x] Focused on user value and business need (generated builds get their
      dependency manifests checked for known CVEs and their licenses
      inventoried against policy, with visibility for `smith-audit` too)
      rather than implementation mechanics
- [x] All mandatory sections completed (Overview, Problem Statement, User
      Scenarios, Functional Requirements, Non-Functional Requirements, Out
      of Scope, Assumptions, Success Criteria)
- [x] Written for reviewers, not just implementers — Overview defines
      "Sub-layer", "Supply-Chain Review Pass", "Manifest", "Finding",
      "Skip-with-disclosure", and "Enforcement" before they're used in
      requirements
- [x] Artifacts named (files/paths, phase numbers, line ranges) only where
      the feature is inherently about specific integration points
      (`smith-build` phase boundaries 3.6/3.7/4, `.smith/config.json`'s
      `supply_chain` key vs. `security_review`, `detect-scanners.sh`,
      `skills/smith-audit/SKILL.md` item 7, the PR-body template) — no HOW
      (exact scanner invocation flags, regex patterns, script internals)
      leaks in beyond what the feature description itself specified

## Requirement Completeness
- [x] Zero `[NEEDS CLARIFICATION]` markers remain anywhere in spec.md
      (verified: `grep -c "NEEDS CLARIFICATION" spec.md` → 0)
- [x] Every FR (FR-1..FR-29) is independently testable — each names a
      concrete condition and an observable pass/fail outcome (a phase
      running/not running, a manifest found/skipped, a scanner
      preferred/fallen-back-to, a finding produced/folded, a PR section
      present/omitted, a config key present/absent)
- [x] No FR depends on a vague qualifier without a concrete rule attached
      (verified: `grep -niE "appropriately|as needed|reasonable|properly|sufficiently"
      spec.md` → no matches)
- [x] Success criteria (SC-1..SC-6) are measurable and technology-agnostic
      outcomes, each traceable to at least one FR: SC-1→FR-4/FR-5/FR-8,
      SC-2→FR-6, SC-3→FR-11, SC-4→FR-13/FR-15, SC-5→FR-12, SC-6→FR-25/FR-26
- [x] All 8 user scenarios (US-1..US-8) are Gherkin Given/When/Then and
      cover: the multi-manifest merged-results primary flow, npm-audit
      exit-code-ignored parsing, the true zero-manifest silent-skip, an
      ENOLOCK single-manifest skip alongside a working sibling manifest,
      offline/timeout never hanging, node_modules-gated license inventory,
      a deny-list hit flagging without blocking, and smith-audit invoking
      the same scripts
- [x] Edge cases identified: a manifest present but its lockfile absent
      (US-4/FR-7), a manifest with a lockfile but no installed
      node_modules/ — CVE-scannable but not license-inventoriable (US-6/
      FR-14), a scanner call that never returns (US-5/FR-12), a deny-list
      hit that must still never terminate (US-7/FR-20), zero manifests
      repo-wide (US-3/FR-6)
- [x] Scope is explicitly bounded — Out of Scope names all five excluded
      areas (OOS-1..OOS-5) with the structural reason each is excluded,
      not just a bare "not doing this"
- [x] Dependencies and assumptions identified (A-1..A-6), including the
      exploration's no-blocking-conflicts finding (A-1), the shared
      presence-detection-helper reuse (A-2), the diff-scope divergence from
      Phase 3.5/3.6 (A-3), and the `goldcanna-inventory`/this-repository
      validation-fixture pairing (A-5)

## Exploration Findings Traceability

Every finding from the pre-feature exploration
(`.smith/vault/explore/explore-2026-09-13-supply-chain-gate.md`) is a
binding design constraint. Each is traced below to the FR(s)/NFR(s)/
Assumption(s) that encode it — none are left as unencoded narrative.

- [x] **Finding 1** (placement: new Phase 3.7, NOT extending 3.6 — its
      decision table + terminate rule are deliberately secret-specific/
      closed; reuse the 55/54 insertion-point pattern between 3.6's close
      and Phase 4) → **FR-1** (Phase 3.7 inserted after 3.6, before Phase
      4, reusing the 54/55 insertion pattern), **FR-2** (runs exactly once,
      gated on 3.6 as an ordering precondition only), **A-6 item 1** (Q1,
      recommendation named and evidence-backed)
- [x] **Finding 2** (`detect-scanners.sh` is the pre-authorized extension
      point — feature 55's NFR-4 names this feature by role: extend the
      loop with osv-scanner, grype, trivy — absent locally but
      `goldcanna-inventory`'s actual CI scanner per
      `.github/workflows/publish.yml`/`.trivyignore` — pip-audit, licensee,
      syft; same output contract, always exit 0) → **FR-27** (names all six
      tools, preserves the same contract/exit-0 convention), **NFR-4**
      (single reused presence-detection helper, no duplicated
      implementation), **A-5** (explicit `trivy`-as-goldcanna's-real-CI-
      scanner evidence cited)
- [x] **Finding 3** (config: new top-level `supply_chain` key —
      `security_review` is schema-closed per its own FR-24; nesting would
      falsely imply tier semantics; same non-destructive seeding mechanism,
      init + update §5.1d) → **FR-28** (states the key, its shape, and the
      not-nested-under-`security_review` decision with the schema-closed
      rationale), **FR-29** (seeding mechanism: `templates/config.default.json`
      + a new `/smith-update` §5.1d step, same idiom as §5.1c),
      **A-6 item 2** (Q2, recommendation named)
- [x] **Finding 4** (empirical npm audit facts: needs lockfile/ENOLOCK;
      exit code useless as a gate — real projects exit 1 essentially
      always; parse `--json` `metadata.vulnerabilities` buckets;
      moderate→Medium mapping; `--package-lock-only` still needs network)
      → **FR-7** (lockfile requirement, ENOLOCK skip-with-disclosure),
      **FR-9** (the `--package-lock-only`-still-needs-network clarification,
      routing it through the same offline/timeout handling as every other
      scanner), **FR-11** (metadata.vulnerabilities parsing, exit-code
      never branched on, moderate→Medium mapping)
- [x] **Finding 5** (manifest reality: this repository has none — the
      silent-skip home-repo case; `goldcanna-inventory` is multi-manifest —
      2× npm + 1× poetry, `pyproject.toml`/`poetry.lock` not
      `requirements.txt` — walk manifests under bounded depth with the
      standard excludes, per-manifest scans, merged results) → **FR-4**
      (bounded-depth walk, standard excludes, manifest type list including
      the poetry/`requirements.txt` distinction), **FR-5** (per-manifest
      scan + merge for multi-manifest repos), **FR-6** (zero-manifest
      silent-skip, this repository's own case), **A-5** (both fixtures
      named as this feature's primary validation cases)
- [x] **Finding 6** (license v1: dependency-free inventory verified live —
      node_modules walk resolved 508/508 packages' licenses in
      `goldcanna-inventory`; Python via `importlib.metadata` with UNKNOWN
      bucketing + the poetry-env caveat — must run via the project's own
      environment; policy is config-only with an empty deny list by
      default) → **FR-13** (dependency-free npm walk script), **FR-14**
      (node_modules-presence gate, stricter than the lockfile
      precondition), **FR-15** (`importlib.metadata` via `poetry run
      python3`, UNKNOWN bucketing), **FR-16** (merged output shape,
      UNKNOWN as a first-class bucket), **FR-18** (empty-by-default
      `allow`/`deny` policy, deny-hit → High-severity Finding), **A-5**
      (508/508 empirical validation cited), **A-6 item 4** (Q4,
      recommendation named)
- [x] **Finding 7** (`smith-audit`'s Dependencies sub-audit — a one-line
      brief today — gets wired to the same scripts: one implementation,
      two consumers, closing feature 55's NFR-4 intent) → **FR-25**
      (upgrades the named sub-audit item to invoke this feature's scripts,
      whole-project), **FR-26** (no forked/duplicated logic — identical
      scripts, explicit NFR-4-intent callback), **A-6 item 6** (Q6,
      recommendation named)
- [x] **Finding 8** (enforcement: flag-only v1, never terminate — CVEs
      aren't diff-introduced, unlike secrets; diff-scoped CVE attribution
      deferred — lockfile-diffing complexity; PR section states the
      not-diff-scoped rationale explicitly; network: hard timeouts, offline
      → skip-with-disclosure, never hang, never fail the build) → **FR-19**
      (no auto-fix), **FR-20** (no enforcement tier, no terminate path
      exists), **FR-24** (the verbatim not-diff-scoped rationale line
      required whenever the PR section appears), **FR-12** (hard timeout
      per scanner call, offline/timeout → skip-with-disclosure), **OOS-1**
      (bugfix exclusion, CVEs-aren't-diff-introduced rationale),
      **OOS-2** (diff-scoped attribution deferred to v2), **A-6 items 3
      and 5** (Q3 and Q5, recommendations named)

## Deferred-Decisions Traceability
- [x] Assumptions §A-6 lists all six items the exploration's own "Gate
      recommendations" line named (Q1 Phase 3.7, Q2 top-level
      `supply_chain` key, Q3 flag-only v1, Q4 license inventory-only/no
      default policy, Q5 bugfix NOT included, Q6 smith-audit wiring
      included) as an explicit "Deferred to questions gate (delegation)"
      list, each carrying its recommended resolution and the exploration
      finding backing it — not as `[NEEDS CLARIFICATION]` markers, and not
      pre-resolved into a binding decision the way feature 55's post-gate
      spec.md now reads
- [x] Every deferred item has a corresponding FR/OOS that states the
      requirement generically enough to remain true under its recommended
      resolution without foreclosing the alternative: FR-1/FR-2 assert
      "a new Phase 3.7 exists" (Q1) without hardcoding that Phase 3.6
      could never have been extended instead had the gate gone the other
      way; FR-28 states the top-level key (Q2) with its rationale, not as
      an unreasoned fact; FR-20/OOS-3 state "no terminate path in this
      version" (Q3) as the recommendation's outcome, not as a claim no
      other design was possible; FR-18 states the empty-by-default policy
      (Q4) with its own rationale; OOS-1 states the bugfix exclusion (Q5)
      with its own rationale; FR-25/FR-26 state the smith-audit wiring
      (Q6) with its own rationale — each traces back to A-6's named
      recommendation rather than asserting itself as beyond question
- [x] No FR, NFR, or success criterion contradicts a deferred item's
      recommended-but-not-final status (verified: every A-6 sub-item is
      phrased "Recommended: X — <reason>", matching this workflow's
      delegation model, rather than "RESOLVED", which feature 55's
      post-gate spec.md uses only after its own gate was actually answered)

## Out-of-Scope Explicitness
- [x] The smith-bugfix exclusion names the structural reason (CVEs are not
      diff/patch-introduced the way secrets are — feature 55's own parity
      precedent is explicitly distinguished, not silently ignored) rather
      than a bare "not doing this" (OOS-1)
- [x] Diff-scoped CVE attribution is named as a deferred v2 candidate with
      its blocking complexity stated (lockfile-diffing), not left as an
      implicit limitation a reader would have to infer (OOS-2)
- [x] The flag-only/no-terminate-path scope is stated as both a firm FR
      (FR-20) and restated in Out of Scope (OOS-3), so a reader encountering
      either section independently gets the same rule
- [x] SBOM generation is named as explicitly excluded rather than merely
      absent from the FRs (OOS-4)
- [x] Phase 3.5 and Phase 3.6 are named as untouched beyond the one named
      `detect-scanners.sh` extension, with NFR-5 restating the same
      boundary from the requirements side (OOS-5)

## Feature Readiness
- [x] Both stated sub-layer deliverables map to at least one FR group each:
      Sub-layer D → FR-8..FR-12; Sub-layer L → FR-13..FR-16
- [x] The manifest-discovery, findings/enforcement, PR-reporting,
      smith-audit-wiring, scanner-extension, and configuration deliverables
      each map to their own FR group: manifest discovery → FR-4..FR-7;
      findings & enforcement → FR-17..FR-20; PR-body reporting →
      FR-21..FR-24; smith-audit wiring → FR-25..FR-26; detect-scanners.sh
      extension → FR-27; configuration → FR-28..FR-29
- [x] No FR, scenario, or success criterion contradicts another (verified:
      the always-merge-never-fail-on-one-manifest's-absence claim in
      FR-5/FR-10 is consistent with US-1/US-4; the node_modules-stricter-
      than-lockfile claim in FR-14 is consistent with US-6; the
      never-terminate claim in FR-20 is consistent with US-1/US-7; the
      omit-when-nothing-to-report claim in FR-22 is consistent with
      US-3/FR-6)
- [x] Constraints supplied by the feature description (Phase 3.7 placement,
      the bounded-depth manifest walk with standard excludes, the scanner
      hierarchy with exit-code-ignored npm audit parsing, the
      dependency-free node_modules-gated license script, flag-only
      enforcement, the extended detect-scanners.sh loop, the new
      top-level `supply_chain` config key, and the smith-audit wiring) are
      each present as FR-1, FR-4, FR-8/FR-9/FR-11, FR-13/FR-14, FR-20,
      FR-27, FR-28, and FR-25 respectively — none were dropped
- [x] Ready for planning: every FR is specific enough to size and
      sequence, and every FR has a corresponding user scenario or success
      criterion to verify against in a future plan.md/tasks.md

## Notes
- Verified against this feature's own spec.md in 1 iteration. The
  `[NEEDS CLARIFICATION]`-marker and vague-qualifier greps were run
  directly against the written file (not asserted from memory), and the
  FR/NFR/OOS/SC numbering was independently counted (`grep -c` per
  prefix, plus a sorted unique listing of every `FR-N` token) to confirm
  no gaps or duplicates before this checklist could be marked complete: 29
  FRs (FR-1..FR-29, no gaps), 6 NFRs, 5 OOS items, 6 SC items, 8 user
  scenarios.
- This feature's spec.md is deliberately the PRE-questions-gate draft
  shape — mirroring what feature 55's own spec.md looked like before its
  gate was answered, not the "RESOLVED"/`answers_applied` shape 55's
  spec.md carries today. The frontmatter accordingly omits
  `answers_applied`, and Assumptions §A-6 uses "Deferred to questions gate
  (delegation)" with named recommendations rather than "RESOLVED"
  outcomes, per this feature's own instruction not to pre-empt the six
  gate decisions.
- This feature differs from feature 55 in one structural way worth
  stating explicitly: feature 55 introduced a config-driven
  `enforcement_tier` that CAN block (`block_on_critical`) alongside an
  unconditional secrets override that always blocks. This feature
  introduces neither — FR-20 and OOS-3 both assert an unconditional
  flag-only posture with no tier-equivalent config surface at all, a
  stricter and simpler invariant than 55's, consistent with exploration
  finding 8's explicit "CVEs aren't diff-introduced" rationale for why
  the two features' postures differ rather than match.
- This feature also differs from both 54 and 55 in scan scope: Phase 3.7
  is a full-project scan, not a diff scan (FR-3/A-3) — the one place this
  checklist verified the spec does not silently borrow 3.5/3.6's
  diff-scoped framing without calling out the divergence. FR-24 requires
  the PR-body section to state this explicitly every time it appears, so
  the divergence is never left for a reader to discover by inference.
