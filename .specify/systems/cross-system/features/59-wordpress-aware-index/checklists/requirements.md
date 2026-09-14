# Specification Quality Checklist: 59-wordpress-aware-index

**Purpose**: Validate specification completeness before planning/implementation
**Created**: 2026-09-14
**Feature**: [spec.md](../spec.md)

## Content Quality
- [x] Focused on user value and business need (a project's `/smith-index`
      stub and rebuild output stop being actively wrong or silently stale
      for a WordPress-shaped project, and stop silently no-opping on a
      config-key typo) rather than implementation mechanics
- [x] All mandatory sections completed (Overview, Problem Statement, User
      Scenarios, Functional Requirements, Non-Functional Requirements, Out
      of Scope, Assumptions, Success Criteria)
- [x] Written for reviewers, not just implementers — Overview defines
      "WordPress-core checkout", "Stub", "Full rebuild", "Stale `.meta`",
      and "Empty system" before they're used in requirements
- [x] Artifacts named (files/paths, function names) only where the feature
      is inherently about specific integration points
      (`scripts/smith-index/run.py`'s `mode_init_system_paths()`/
      `_load_overrides()`/`IndexRun`, the new `wp_defaults.py`,
      `system-paths.json`'s `rules` key) — no HOW beyond what the feature
      description itself specified leaks into requirement wording

## Requirement Completeness
- [x] Zero `[NEEDS CLARIFICATION]` markers remain anywhere in spec.md
      (verified: `grep -c "NEEDS CLARIFICATION" spec.md` → 0)
- [x] Every FR (FR-1..FR-20, no gaps) is independently testable — each
      names a concrete condition and an observable pass/fail outcome (a
      rule count, a byte-identical stub, a file present/absent after a
      rebuild, a summary-line substring, a stderr line present/absent, a
      return value unchanged)
- [x] No FR depends on a vague qualifier without a concrete rule attached
      (verified: `grep -niE "appropriately|as needed|reasonable|properly|
      sufficiently" spec.md` → no matches)
- [x] Success criteria (SC-1..SC-6) are measurable and technology-agnostic
      outcomes, each traceable to at least one FR: SC-1→FR-1/FR-2/FR-3,
      SC-2→FR-4, SC-3→FR-7/FR-8/FR-10, SC-4→FR-9/FR-10, SC-5→FR-14/FR-15/
      FR-16, SC-6→(regression, not a single FR — traced to the Test
      Strategy in plan.md instead, same pattern feature 57 used for its
      own full-suite-regression success criterion)
- [x] All 6 user scenarios (US-1..US-6) are Gherkin Given/When/Then and
      cover: WordPress-shaped stub generation (17 rules, no duplicate
      wp-admin/wp-includes), wp-content/ staying indexed, a non-WP
      project's byte-identical stub, full-rebuild pruning of a deleted
      source + a newly-excluded source + an emptied system manifest, all
      four no-prune modes in one scenario, and the `_load_overrides`
      warning
- [x] Edge cases identified: a project with only ONE of the two WP
      signals (US-3, explicitly enumerated as three distinct sub-cases —
      file-only, dir-only, neither), a WordPress project WITH additional
      top-level directories that must stay indexed (US-2, `wp-content/`),
      the `--resume` no-prune case's own distinct root cause (FR-9's
      fourth bullet, independently different from the other three
      exclusions — not a copy-pasted rationale), a dict with `"rules"`
      already present or a non-dict JSON value never triggering the new
      warning (FR-17)
- [x] Scope is explicitly bounded — Out of Scope names all five excluded
      areas (OOS-1..OOS-5) with the structural or deliberate-scope-call
      reason each is excluded, including a detailed, independently
      re-verified callout (OOS-5) for a drift finding discovered while
      drafting this spec rather than assumed from the task framing
- [x] Dependencies and assumptions identified (A-1..A-5), including
      `BANK-028`'s binding status (A-1), the three-item delegation outcome
      (A-2), the fourth directly-evaluated decision (A-3), the
      `install.sh` staging-block location (A-4), and the `tests/parsers/`
      precedent for where new unit tests belong (A-5)

## Bank Entry Gotchas Traceability

`BANK-028` (`.smith/vault/bank/2026-09-14_144500-wordpress-aware-index-
defaults.md`) is this feature's origin and, per its own task framing, is
binding for both gotchas it names. Each is traced below to the FR(s) that
encode it, AND to the specific on-disk evidence independently re-verified
while drafting this spec — neither is left as unencoded narrative.

- [x] **Gotcha 1** ("system-paths.json top-level key is `rules` (NOT
      `overrides`) — [{"prefix","system"}], "excluded" skips indexing
      entirely; glob prefixes are dropped") → **FR-14/FR-15/FR-16/FR-17**
      (the `_load_overrides` warning, scoped exactly to this exact
      key-name confusion) AND **FR-2** ("excluded" is the literal value
      every WP-core rule uses, matching the gotcha's own stated semantics
      verbatim) AND **OOS-1** (the glob-prefix-dropping behavior itself,
      and the `"rules"` key name itself, both live in `path-resolver.py`
      and are explicitly NOT touched). Re-verified directly:
      `scripts/parsers/path-resolver.py` line 322
      (`rules = overrides_data.get("rules", []) or []`) confirms the
      gotcha's claim exactly — a `{"overrides": [...]}` file really does
      silently resolve to an empty rules list with zero diagnostic
      anywhere before this feature.
- [x] **Gotcha 2** ("Rebuild does NOT prune stale .meta files/system
      manifests for newly-excluded paths — an exclusion change needs a
      prune step (candidate: run.py cleans index/files entries whose
      source resolves to excluded)") → **FR-7/FR-8/FR-9/FR-10/FR-11/
      FR-12/FR-13** (the entire Part B `prune_stale_index()` design,
      including the EXACT candidate mechanism the gotcha names — "run.py
      cleans index/files entries whose source resolves to excluded" —
      implemented essentially verbatim, reusing
      `_refresh_full_aggregations()`'s already-established predicate
      rather than inventing a new one). Re-verified directly: `run.py`
      lines 1106-1122 (`mode_full()`'s per-file loop) confirm a file that
      newly resolves `"excluded"` is simply never touched again, and
      lines 1336-1340 (`_refresh_full_aggregations`) confirm the identical
      stale-check already exists for incremental mode's aggregation-skip
      but never deletes anything — both claims independently confirmed
      against the file on disk, not taken on the bank entry's word alone.
- [x] **Gotcha 3** ("wp-config.php exclusion is also a data-hygiene win
      (DB creds/salts should never enter the .meta layer)") → **FR-2**
      (`wp-config.php` is one of the 15 named `WP_CORE_ROOT_FILES` — a
      data-hygiene side effect of the same rule, not a separately-encoded
      requirement, since excluding it from indexing is a strict subset of
      excluding it from parsing entirely, which `"excluded"` already
      guarantees per `process_file()`'s existing excluded-skip check).

## Deferred-Decisions Traceability
- [x] Assumption A-2 lists all three items the task framing named with a
      recommendation each (detection location, GC scope, warning-vs-alias)
      as "RESOLVED via delegation," each carrying its recommended-and-
      accepted resolution in `questions.md` Q1-Q3
- [x] The FOURTH decision (Q4 in `questions.md` — whether this feature
      also wires `/smith init` into `/smith-index`) is explicitly NOT
      folded into the delegation trail — both `spec.md` (OOS-5/A-3) and
      `questions.md` state plainly this was discovered independently
      while drafting the spec and evaluated directly per this feature's
      own "note as future" framing for adjacent scope, distinct from the
      three named gate items. Checked here so a future reader doesn't
      mistake Q4 for an unlisted fourth delegated answer.
- [x] Every one of the three delegated items has a corresponding FR/OOS
      that states the requirement concretely: FR-1/FR-3 + OOS-1 (Q1),
      FR-7/FR-9 (Q2), FR-14/FR-15/FR-16 + OOS-1 (Q3) — each traces back to
      `questions.md`'s named recommendation
- [x] No FR, NFR, or success criterion contradicts a resolved item's
      accepted status (verified: every `questions.md` Q1-Q3 item is
      phrased "Recommended: A" / "Answer: A (accepted via delegation)" and
      every corresponding FR states that exact outcome as unconditional)

## Out-of-Scope Explicitness
- [x] The resolver-changes exclusion (OOS-1) names the structural reason
      (purity/no-filesystem-writes precedent in `path-resolver.py`'s own
      docstring, re-verified) rather than a bare "not doing this," and is
      cross-referenced from three separate FRs (FR-2 rule-count rationale,
      Q1's evidence, Q3's evidence) so a reader hitting any of them
      independently gets the same boundary
- [x] The other-CMS-detection exclusion (OOS-2) is stated as deliberate
      future work with a concrete reuse path named (Part B's general,
      non-WordPress-specific prune machinery), not merely absent from the
      FRs
- [x] The consumer-project auto-pruning exclusion (OOS-3) and the
      `attck2026`-itself exclusion (OOS-4) are each stated with the
      specific reason a reader might otherwise assume the opposite (a
      project only gets Part B's cleanup on ITS OWN next full rebuild; the
      hand-fixed reference config is a citation source, not a target)
- [x] The `/smith init` call-path-gap exclusion (OOS-5) is the most
      detailed callout in this spec's Out of Scope section by a wide
      margin — deliberately so, since it documents a drift DISCOVERED
      during spec drafting (not merely inherited from a prior document)
      between two SKILL.md files' claims about each other, independently
      re-verified with an exact `grep` command re-run against the file on
      disk, with the concrete reason (FR-3's detection-lives-in-the-mode-
      function design) that closing this gap later costs zero rework of
      anything this feature ships

## Feature Readiness
- [x] Each of the three named parts maps to its own FR group: WordPress
      detection → FR-1..FR-6; rebuild garbage collection → FR-7..FR-13;
      `_load_overrides` hardening → FR-14..FR-17; documentation →
      FR-18..FR-20
- [x] No FR, scenario, or success criterion contradicts another (verified:
      FR-3's "skip wp-admin/wp-includes from the generic loop" and the
      generic loop's own pre-existing behavior for every other directory
      don't conflict, since FR-3 only adds ONE new conditional inside an
      otherwise-untouched loop; FR-9's four-mode exclusion list and FR-7/
      FR-8's "after a full rebuild's walk completes" don't conflict, since
      FR-9 gates WHETHER `prune_stale_index()` is ever called, not what it
      does once called; FR-15's "no behavior change beyond the warning"
      and FR-14's "emit exactly one stderr line" are the two complementary
      halves of one behavior, not a conflict)
- [x] Constraints supplied by the feature description (stub-generation-
      time detection not resolver-magic, 17-rule count, never-a-bare-
      "wp-"-prefix, general not WP-specific GC scoped to full-rebuild-
      only, warning not alias for the key gotcha, the three named
      out-of-scope items) are each present as FR-1/FR-3, FR-2, FR-2,
      FR-7/FR-9, FR-14/FR-15, and OOS-1/OOS-2/OOS-3 respectively — none
      were dropped, and the feature description's own "(and via `/smith
      init`'s call path)" clause is traceable to its own dedicated OOS-5/
      Q4 treatment, not silently ignored or silently assumed satisfied
- [x] Ready for planning: every FR is specific enough to size and
      sequence, and every FR has a corresponding user scenario or success
      criterion to verify against in `plan.md`

## Notes
- Verified against this feature's own `spec.md` in 1 iteration. The
  `[NEEDS CLARIFICATION]`-marker and vague-qualifier greps were run
  directly against the written file (not asserted from memory), and the
  FR/NFR/OOS/SC/US numbering was independently counted to confirm no gaps
  or duplicates before this checklist could be marked complete: 20 FRs
  (FR-1..FR-20, no gaps — grouped 6/7/4/3 across the three parts plus
  documentation), 4 NFRs, 5 OOS items, 5 assumptions, 6 SC items, 6 user
  scenarios.
- Unlike feature 58's six-item delegation trail, this feature's task
  framing named exactly three decisions for delegation (Q1-Q3); a fourth
  decision (Q4) was discovered independently during spec drafting, not
  pre-named by the task framing, and is treated as a feature of this
  spec's traceability (checked above under Deferred-Decisions
  Traceability) rather than an inconsistency with the "three delegated
  decisions" framing this feature's own task description used.
- This is the smallest-footprint feature in this worktree's 54-59 run in
  terms of files touched (one new module, one file with four incremental
  method/function-level additions, one install-script line, two doc
  touches, one changelog entry, three new test files — no config-schema
  change, no three-site seeding, no new scheduler/audit surface) — this
  checklist's Content Quality pass confirmed `spec.md` itself states this
  explicitly in its Overview rather than leaving the scope's modest size
  implicit until `plan.md`.
