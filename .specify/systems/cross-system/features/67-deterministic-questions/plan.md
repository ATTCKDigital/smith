# Implementation Plan: Deterministic Question-Asking Mechanism

**Feature:** [spec.md](./spec.md) · **Research:** [research.md](./research.md)
**Primary system:** cross-system · **Also affects:** system-config-memory

## Technical Context

- **Language/format:** Markdown skills (`SKILL.md`), Bash+python3 hooks, JSON
  config/settings fragments. No application runtime.
- **Enforcement surface:** Claude Code PreToolUse hooks (installed via
  `~/.claude/settings.json`) + the Haiku critic (`hooks/grade-response.sh`).
- **Distribution:** self-hosting — changes ship to all projects via
  `/smith-update` (global install of skills/hooks + per-project template/config
  refresh).

## Constitution Gates

- **File Size Policy (300 soft / 500 decompose):** the new skill and hook are
  each expected < 300 lines. PASS (target).
- **Clean Architecture — Reuse over duplication:** this feature's *purpose* is
  de-duplication (one canonical Q&A contract). The hook reuses the existing
  deny/warn/marker patterns rather than inventing new ones. PASS.
- **Rule 6 (`python3`):** all embedded parsing uses `python3`. PASS.
- **Context Budget Policy:** no new `@`-referenced always-loaded file is added;
  `smith-question` loads on-demand only. PASS.

## Reuse Map (existing components extended, not recreated)

| Need | Reused from | How |
|------|-------------|-----|
| PreToolUse deny JSON | `hooks/security-guard-bash.sh`, `hooks/workflow-gate.sh` | Same `permissionDecision:deny` + `permissionDecisionReason` shape |
| Warn-only nudge | `hooks/security-guard-bash.sh` warn branch | Same `additionalContext` shape |
| Marker-presence check (workflow-gated mode) | `hooks/workflow-gate.sh` | Same `.smith/vault/active-workflows/` scan |
| stdin tool-name parse | `hooks/workflow-gate.sh`, `security-guard-bash.sh` | python3 `json.load(sys.stdin)` |
| Config three-site seeding | feature 58 FR-20 (`config.default.json` + smith init + smith-update) | Identical read-modify-write idiom |
| Q&A contract source text | `skills/smith-new` Phase 5 / `smith-clarify` (existing prose) | Lifted into `smith-question`, then referenced |

## File Structure (decomposed, single-responsibility)

### Create
- `skills/smith-question/SKILL.md` — canonical Q&A contract + response grammar +
  questions.md format (FR-1/FR-2/FR-3/FR-4/FR-5). Single responsibility: *define
  how questions are asked and answered*. It does NOT generate questions.
- `hooks/question-gate-guard.sh` — PreToolUse enforcement (FR-10–FR-13).
  Single responsibility: *react to an `AskUserQuestion` call per config mode*.

### Modify
- `settings/smith-settings-fragment.json` — add `AskUserQuestion` PreToolUse
  matcher (FR-14). Additive only.
- `settings/claude-md-template.md` — add compact graded sub-criterion (FR-18);
  reconcile Rule 3 to point at `smith-question` for questions.md shape (FR-19).
- `templates/config.default.json` — add `question_gate` block (FR-15).
- `skills/smith-new/SKILL.md` — Phase 5 invokes `smith-question`; inline format
  restatement → pointer; keep questions.md-generation/persistence specifics (FR-6).
- `skills/smith-clarify/SKILL.md` — invoke `smith-question`; inline restatement →
  pointer; keep ≤5-budget + spec-encoding specifics (FR-7).
- `skills/smith/SKILL.md` — init interview invokes `smith-question`; keep 29-question
  intake generation + `specs/init-intake.md` persistence + ok/skip/back nav (FR-8);
  add `question_gate` seeding paragraph (FR-16).
- `skills/smith-update/SKILL.md` — add a `question_gate` seeding step (FR-16).
- `docs/` — document `question_gate` modes + global-install caveat + absent-key
  behavior + `/smith-update` propagation (FR-20/FR-21). Target file confirmed at
  build (likely a new `docs/question-gate.md` or a section in an existing config doc).
- `CHANGELOG.md` — `[Unreleased] → Added` entry, written last (FR-22).

## Build Order (dependency-ordered)

1. `skills/smith-question/SKILL.md` (source of truth; everything else references it).
2. `hooks/question-gate-guard.sh` (self-contained; unit-testable via stdin fixtures).
3. `settings/smith-settings-fragment.json` wiring.
4. `templates/config.default.json` + seeding in `skills/smith/SKILL.md` + `skills/smith-update/SKILL.md`.
5. `settings/claude-md-template.md` graded criterion + Rule 3 reconcile.
6. Integrate `smith-question` into smith-new / smith-clarify / smith (dedupe inline format).
7. `docs/` + `CHANGELOG.md`.

## Testing Strategy

- **Hook unit tests** (`tests/hooks/`): feed the hook JSON stdin fixtures for
  each mode (`deny`/`warn`/`workflow-gated` with & without a marker/`off`) and a
  non-`AskUserQuestion` tool; assert the emitted decision + exit code. Include a
  corrupt/absent `.smith/config.json` fixture (asserts fail-open = allow, FR-12/FR-17).
- **Behavior-preservation check** (NFR-4): diff the questions each gate asks
  before/after extraction — must be identical.
- **Seeding idempotence**: run the smith-update seeding idiom twice; second run is
  a no-op.
- Follow existing `tests/` conventions (bats or shell harness — confirmed at build).

## Open Decisions (resolved at the questions gate → questions.md)

Q1 enforcement default · Q2 graded-rule placement · Q3 critic reads rules
dynamically? · Q4 smith init fold vs keep · Q5 config key/hook filenames · Q6
warn-first rollout vs deny immediately.
