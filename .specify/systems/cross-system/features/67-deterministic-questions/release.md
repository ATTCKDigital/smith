# Release: Deterministic Question-Asking Mechanism

**Date**: 2026-09-22
**Branch**: 67-deterministic-questions
**PR**: [#67](https://github.com/ATTCKDigital/smith/pull/67)
**Spec**: [spec.md](spec.md)

## Summary

Makes Smith's markdown Q&A contract (Context → Options with pros/cons →
Recommended + reasoning, one question at a time) the single source of truth and
suppresses the interactive `AskUserQuestion` popup via a config-gated PreToolUse
hook plus a graded backstop. The popup was previously forbidden nowhere; the Q&A
format was quadruplicated and drift-prone.

## Changes

### Files Created
| File | Purpose |
|------|---------|
| `skills/smith-question/SKILL.md` | Canonical Q&A contract, response grammar, questions.md shape |
| `hooks/question-gate-guard.sh` | PreToolUse guard (matcher `AskUserQuestion`), 4 modes, fail-open |
| `tests/hooks/test_question_gate_guard.sh` | 15-case unit test (bash + zsh) |
| `.specify/systems/cross-system/features/67-deterministic-questions/` | spec, plan, research, questions, tasks, checklist |

### Files Modified
| File | Change |
|------|--------|
| `settings/smith-settings-fragment.json` | Additive `AskUserQuestion` PreToolUse matcher |
| `templates/config.default.json` | New `question_gate: {mode: deny}` key |
| `skills/smith/SKILL.md` | init interview → smith-question; `question_gate` seeding |
| `skills/smith-update/SKILL.md` | New §5.1g `question_gate` seeding step |
| `settings/claude-md-template.md` | Rule 2 sub-criterion (no reweight); Rule 3 → smith-question |
| `skills/smith-new/SKILL.md` | Phase 5 → smith-question (de-dup, behavior-preserving) |
| `skills/smith-clarify/SKILL.md` | Answer collection + sequential loop → smith-question |
| `scripts/install.sh` | Hardcoded "9 hooks" preview → dynamic count |
| `docs/hooks.md` | Summary row + detailed `question-gate-guard.sh` section |
| `CHANGELOG.md` | `[Unreleased] → Added` entry |

### System Specs Updated
None — this repo keeps only per-feature specs; no system-level `spec.md` exists
for `cross-system` / `system-config-memory`.

## Testing

### Unit Tests
- **PASS** `tests/hooks/test_question_gate_guard.sh` — 15/15 under bash **and** zsh
  (each mode; workflow-gated ±marker; absent/malformed config + absent/unknown key
  fail-open; non-`AskUserQuestion` inert; malformed stdin no-crash; deny-is-global).
- **PASS** `tests/settings-dedupe.test.sh` (11), `tests/hooks/test_hook_chain_order.sh`
  (6), `tests/hooks/test_config_default_seed.sh` (20) — regression on touched files.
- JSON validity of edited settings fragment + config default confirmed.

### CI
- **PASS** install-test, lint (GitHub Actions on PR #67).

### Known Issues
None.

## Deviations from Spec

- Q5 changed the hook filename from the spec's placeholder
  `deny-interactive-questions.sh` to the mode-neutral `question-gate-guard.sh`
  (spec/plan updated before build).
- The Rule 2 graded backstop scores only when a skill/trigger is active (Rule 2's
  existing "applies when" clause was not widened). The always-on enforcement layer
  is the hook (`deny` default, global); the graded rule catches the in-workflow
  decay case. Consistent with the layered design.

## Rollout

Edits the shipped template/hook/settings only. A user's live `~/.claude/CLAUDE.md`
and `~/.claude/settings.json` update by running `/smith-update` per project, which
also seeds `question_gate: {mode: deny}` there. Until re-seeded, existing projects
resolve the absent key as `off` (fail-open) — no silent behavior change.

## Infrastructure

- Docker services rebuilt: none (no runtime services touched).
- Health check: n/a.
