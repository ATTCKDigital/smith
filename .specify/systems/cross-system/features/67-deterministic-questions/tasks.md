# Tasks: Deterministic Question-Asking Mechanism

**Feature**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md)
Build order follows plan.md §Build Order. Dependency-ordered.

## Phase 1: Source of truth
- [x] T1 Create `skills/smith-question/SKILL.md` — canonical Q&A contract, response grammar, questions.md format, context-loading, forbids AskUserQuestion (FR-1..FR-5)

## Phase 2: Enforcement
- [x] T2 Create `hooks/question-gate-guard.sh` — PreToolUse guard; inert unless tool=AskUserQuestion; modes deny/warn/workflow-gated/off; fail-open (FR-10..FR-13, FR-17)
- [x] T3 Modify `settings/smith-settings-fragment.json` — add AskUserQuestion PreToolUse matcher (FR-14)

## Phase 3: Config seeding (three-site)
- [x] T4 Modify `templates/config.default.json` — add `question_gate: {mode: deny}` after `scheduled_audits` (FR-15)
- [x] T5 Modify `skills/smith/SKILL.md` — init scaffold python3 heredoc seeds `question_gate` (FR-16)
- [x] T6 Modify `skills/smith-update/SKILL.md` — add `question_gate` seeding step (FR-16)

## Phase 4: Graded backstop
- [x] T7 Modify `settings/claude-md-template.md` — Rule 2 sub-criterion (compact, no reweight) + Rule 3 reconcile to point at smith-question (FR-18/FR-19)

## Phase 5: Skill integration (dedupe + just-in-time invoke)
- [x] T8 Modify `skills/smith-new/SKILL.md` Phase 5 — invoke smith-question; inline format → pointer; keep questions.md specifics (FR-6)
- [x] T9 Modify `skills/smith-clarify/SKILL.md` — invoke smith-question; inline format → pointer; keep ≤5-budget/spec-encoding (FR-7)
- [x] T10 Modify `skills/smith/SKILL.md` init interview — invoke smith-question; keep 29-question intake/nav (FR-8)

## Phase 6: Tests + docs
- [x] T11 Create `tests/hooks/` unit tests for question-gate-guard.sh (each mode + corrupt/absent config + non-AskUserQuestion inert)
- [x] T12 Docs: document `question_gate` modes, shipped-deny-vs-absent-off, global install caveat, /smith-update propagation (FR-20/FR-21)

## Phase 7: Changelog (last)
- [x] T13 `CHANGELOG.md` [Unreleased] → Added entry (FR-22)
