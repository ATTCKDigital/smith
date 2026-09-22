# Requirements Quality Checklist: Deterministic Question-Asking Mechanism

Traces spec.md against the pre-feature exploration and house quality bar.

## Coverage of exploration findings

- [x] Enforcement gap (zero `AskUserQuestion` refs) → addressed by FR-10–FR-14 (hook) + FR-18 (graded rule)
- [x] Format quadruplication (smith-new, smith-clarify, smith, claude-md-template) → FR-1/FR-2 (canonical skill) + FR-6/FR-7/FR-8/FR-19 (dedupe)
- [x] W1 enforcement scope → FR-11 (modes) + FR-17 (absent-key = off) [Q1 confirms default]
- [x] W2 personal-vs-shipped config → FR-21 + OOS-1 (template only; /smith-update propagates)
- [x] W3 extraction-vs-graded-rule → FR-18 (compact inline criterion + pointer), FR-19 (Rule 3 reconcile)

## Requirement quality

- [x] Every FR is testable / observable
- [x] Config default stated explicitly (`deny`), with all four modes enumerated
- [x] Fail-safe behavior specified (FR-12/FR-17/NFR-5 — hook never crashes/blocks unrelated calls)
- [x] Behavior-preservation for existing gates asserted (FR-9/NFR-4)
- [x] Rollout/propagation path documented (FR-20/FR-21) — self-hosting repo
- [x] Success criteria map back to user scenarios (SC-1..SC-7 ↔ US-1..US-7)

## Open items (deferred to questions.md — NOT gaps)

- [ ] Q1: enforcement default mode confirmation (recommended `deny`; absent-key `off`)
- [ ] Q2: graded-rule placement (extend Rule 1 / extend Rule 2 / new dedicated rule)
- [ ] Q3: does the critic read rule criteria from the template (OOS-3 assumption)
- [ ] Q4: smith init interview — fold presentation into smith-question vs keep intake-specific
- [ ] Q5: config key/schema name (`question_gate.mode`) and hook filename
- [ ] Q6: whether to ship warn-only for a release cycle before flipping default to deny

## Constitution alignment

- [x] File Size Policy — new skill + hook expected < 300 lines each
- [x] Reuse over duplication — the feature's core purpose IS de-duplication; hook reuses existing deny/marker patterns
- [x] Rule 6 (`python3`) — all embedded parsing uses python3
