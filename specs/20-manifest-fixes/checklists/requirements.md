---
feature: 20-manifest-fixes
checklist: requirements
created: 2026-06-02
---

# Requirements Quality Checklist — Manifest System v2 Fixes

Spec-quality checklist for `specs/20-manifest-fixes/spec.md`. Each item is a binary pass/fail check intended to catch underspecification, leakage of out-of-scope behavior into requirements, and drift from the resolved questions gate.

## Questions Gate Resolution

- [ ] Q1 (track sequencing) recorded as one bundled PR. Captured in spec section `Design Decisions > Decision: One Bundled PR for All Three Tracks (Q1)`.
- [ ] Q2 (A3 = new skill vs extend `/smith-migrate-specs`) resolved as new skill `/smith-migrate-system-paths`. Captured in spec section `Requirements > Track A > A3`.
- [ ] Q3 (A1/A2 scope) resolved as full scope: new system-spec template + new `/smith init` sub-step. Captured in spec sections `Requirements > Track A > A1` and `A2`.
- [ ] Q4 (`.meta` coverage enforcement) resolved as soft guidance in smith-new/bugfix/debug PLUS hard flag in `/smith-build` (never blocks). Captured in spec sections `Requirements > Track C > C1` and `C1.5`.
- [ ] Q5 (`/smith-index --describe` approval granularity) resolved as per-batch (~20 files, configurable) with per-file reject. Captured in spec section `Requirements > Track C > C2`.
- [ ] Q6 (resolver tie-break and glob support) resolved as longest-prefix-wins, literal-only, globs deferred to v3. Captured in spec section `Requirements > Track A > A4` and `Design Decisions > Decision: Longest-Prefix Resolution, Literal Prefixes Only (Q6/A)`.
- [ ] Q7 (description granularity) resolved as both per-module + per-method with configurable threshold; always per-module. Captured in spec section `Requirements > Track B > B3`.
- [ ] Q8 (description length caps) resolved as per-module ~120-char soft cap, per-method ~200-char soft cap. Captured in spec section `Requirements > Track B > B3`.
- [ ] Q9 (out-of-workflow staleness handling) resolved as hash-mismatch flag (`Described-Against-Hash` vs `Hash`); auto-queue deferred to v3. Captured in spec section `Requirements > Track C > C3` and `Design Decisions > Decision: Hash-Mismatch Staleness Flag (Q9/B)`.
- [ ] Q10 (model + batching + checkpoint contract) resolved as Haiku 4.5, N=10, `--describe` flag, Rule 4 checkpoint/resume + JSONL, hash-cached skip-unchanged. Captured in spec section `Requirements > Track C > C2` and `Design Decisions > Decision: Haiku 4.5 + N=10 Batching + Opt-In --describe Flag (Q10/A)`.
- [ ] Q11 (workflow `.meta` update scope) resolved as touched-methods-only + per-module-if-purpose-shifts. Captured in spec section `Requirements > Track C > C1` and `Design Decisions > Decision: Touched-Methods-Only Workflow Updates (Q11/A)`.

## Design Decisions Captured

- [ ] **Descriptions in `.meta`, never source** — present, with both rationales (lean source for whole-file LLM reads + `.meta` as pre-read filter).
- [ ] **LLM confined to `/smith-index --describe` + smith workflows** — present, with explicit "save hook never calls LLM" statement.
- [ ] **Parser is structure-only; descriptions are a separate layer keyed by stable method IDs** — present, with stable-id semantics (changes on rename/signature, not on body edit or reorder).
- [ ] **`.specify/systems/` `paths:` frontmatter as resolver tier 1, additive** — present, with explicit "v1 behavior preserved when `.specify/systems/` is absent" guarantee.
- [ ] **One bundled PR (Q1)** — present.
- [ ] **Longest-prefix resolution, literal prefixes only (Q6)** — present.
- [ ] **Hash-mismatch staleness flag (Q9)** — present.
- [ ] **Haiku 4.5 + N=10 batching + `--describe` flag (Q10)** — present.
- [ ] **Touched-methods-only workflow update (Q11)** — present.

Each Design Decision section follows the `Decision / Rationale / Alternatives considered` shape.

## Hard Constraints With Measurable Thresholds

- [ ] Source code never modified by any v2 component — stated as a hard constraint, not just a goal.
- [ ] `manifest-updater.sh` <500ms p95 per file edit — explicit numeric threshold; unchanged from v1.
- [ ] `/smith-index` structural pass <60s for 400 files — explicit numeric threshold; unchanged from v1.
- [ ] `/smith-index --describe` ~30-60s per 20-file batch — explicit target.
- [ ] `/smith-navigate` <3s p95 — explicit numeric threshold; unchanged from v1.
- [ ] Top-level manifest ≤50 lines, per-system manifest ≤80 lines — explicit numeric caps, unchanged from v1.
- [ ] LLM calls explicitly enumerated to two paths (`/smith-index --describe` + three smith workflows) — anything else is a violation.

## Acceptance Criteria Coverage

- [ ] Acceptance Criteria split into three groups: **Functional**, **Performance**, **Quality**.
- [ ] Each Track A requirement (A1, A2, A3, A4) has at least one functional acceptance check.
- [ ] Each Track B requirement (B1, B2, B3, B4, B5, B6) is covered by at least one functional or quality acceptance check.
- [ ] Each Track C requirement (C1, C1.5, C2, C3) is covered by at least one functional acceptance check.
- [ ] Rule 4 compliance for `/smith-index --describe` (JSONL log shape, `--resume`, summary on completion) appears in Quality acceptance checks.
- [ ] v1 regression check ("all v1 tests pass after v2 merges") present in Quality acceptance.

## v1 Compatibility Explicit

- [ ] Spec explicitly states "tier 1 is additive — when `.specify/systems/` is absent, resolver falls back to v1 (tier 2 + tier 3)" in `Requirements > Track A > A4` AND in `Hard Constraints`.
- [ ] Spec explicitly states v1 `.meta` header fields (`Last Updated:`, `Language:`, `Lines:`, `Hash:`) are unchanged — backward compatibility is documented in `Requirements > Track B > B5` and reiterated in `Hard Constraints`.
- [ ] Spec explicitly states v1's `manifest-updater.sh` <500ms p95 budget is preserved (no LLM additions to the save hook) in `Hard Constraints` AND in `Acceptance Criteria > Performance`.
- [ ] Spec explicitly states v1's `/smith-index` (without `--describe`) <60s for 400 files is preserved in `Hard Constraints` AND in `Acceptance Criteria > Performance`.

## No Source-Modification Leakage

- [ ] Search the spec text for "docstring" — every occurrence is in the context of (a) explaining what the parser does NOT do, (b) explaining the rejected alternative of in-source storage, or (c) the Non-Goals section. NO requirement, acceptance criterion, or hard constraint instructs any component to write a docstring.
- [ ] Search the spec text for "JSDoc" — same rule.
- [ ] Search the spec text for "comment" in the context of source-code modification — no requirement instructs any component to write a Smith-generated comment in source.
- [ ] All description-write paths (B3, C1, C2) explicitly land in `.meta`, never source.
- [ ] Out of Scope section explicitly lists "Source code modification (backfilling docstrings into .py/.js files)".

## Open Questions

- [ ] Open Questions section exists.
- [ ] Open Questions section explicitly states "All resolved — see questions.md." No remaining `[NEEDS CLARIFICATION]` markers, no underspecified design choices left for the implementation phase.

## Assumptions Documented

- [ ] Assumption documenting `/smith init` does NOT currently scaffold system specs (so A2 is genuinely new behavior).
- [ ] Assumption documenting that existing system specs are hand-authored bold-field markdown, not YAML, so A1/A3 must coexist with prose bodies.
- [ ] Assumption documenting that `/smith-migrate-specs` explicitly does NOT touch system specs, justifying A3 as a separate skill.
- [ ] Assumption documenting v1 `.meta` header field set, so B5's additions are clearly additive, not replacements.
- [ ] Assumption documenting that smith-repo itself does not run `/smith-index` on itself (v1 Q1 carry-over).
- [ ] Assumption documenting parsers live at `~/.smith/scripts/` globally with per-project overrides allowed (v1 Design Decision 5 carry-over).

## Structural Quality

- [ ] Spec frontmatter includes `feature`, `branch`, `created`, `status`, `builds_on`, `note` fields.
- [ ] Spec section order: Summary, Background, Goals, Non-Goals, Users/Stakeholders, Requirements (Tracks A/B/C), Design Decisions, Hard Constraints, Acceptance Criteria, Open Questions, Assumptions, References.
- [ ] Spec ends with a `YYYY-MM-DD — <branch-name>` datetime stamp (Rule 6).
- [ ] Spec length is in the 400-600 line target range.
- [ ] All Requirements sub-components (A1-A4, B1-B6, C1, C1.5, C2, C3) have H4 headings and exact behavioral descriptions.

## Cross-References

- [ ] Spec references PR #19 in the References section.
- [ ] Spec references the v1 spec path (`specs/19-manifest-system/spec.md`) in the References section.
- [ ] Spec references the questions.md file in the Open Questions section AND in the References section.
- [ ] Spec sections that derive from a specific question cite the question number (e.g. "(Q6/A)", "(Q11/A)") inline so the resolution audit trail is visible.

2026-06-02 — 20-manifest-fixes
