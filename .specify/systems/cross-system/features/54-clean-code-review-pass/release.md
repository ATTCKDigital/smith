# Release: Clean Code Review Pass

**Date**: 2026-09-13
**Branch**: 54-clean-code-review-pass
**PR**: #TBD (filled at PR creation)
**Spec**: [spec.md](spec.md)

## Summary

Generated code is now *verified* against the smith-clean-code tenets, not just steered by them. smith-build gains a bounded post-testing review pass — a Sonnet subagent reviews the branch diff against the rubric (read heading-anchored from the skill file itself), auto-applies only safe behavior-preserving fixes with exactly one full test re-run when any fix lands, and surfaces the rest in a flag-never-block "Clean Code Review" PR-body section. smith-bugfix and smith-implement gain generation-time checklist parity so every code-writing workflow carries the same tenets.

## Changes

### Files Created
| File | Purpose |
|------|---------|
| (none) | prose-only feature |

### Files Modified
| File | Change |
|------|--------|
| skills/smith-build/SKILL.md | New "## Phase 3.5: Clean Code Review Pass" (75 lines, self-contained) between Phase 3 and Phase 4: Sonnet subagent (`model: sonnet` alias per smith-explore/debug convention); rubric via heading-anchored Read of skills/smith-clean-code/SKILL.md ("## Review Process", "## Decision Rules", "## What You Should Avoid"; worktree copy → installed fallback; never line numbers); findings contract (severity, file:line, tenet, safe-to-autofix, rationale); auto-fix only safe + behavior-preserving, Critical behavior-level never auto-fixed, unclear → flag; ANY fix ⇒ exactly ONE full Phase 3 re-run; hard bound one review → one fix batch → one re-test, no re-review; findings handoff /tmp/smith-build-clean-code-findings.txt. Plus: conditional "## Clean Code Review" PR-body section (Medium+ individually, Low as "+ N low-severity notes"; flag-never-block wording mirroring §5.3) and a §5.3 note that scans operate on the post-fix diff |
| skills/smith-bugfix/SKILL.md | Phase 3 step 2: constitution-pointer replaced with the compact six-bullet checklist (bullets 2-6 byte-identical to smith-implement's); no-refactoring-untouched-code constraint retained |
| skills/smith-implement/SKILL.md | Single-line clean-architecture reference replaced with the same six-bullet checklist; bullet 1 folds in the File Size Policy content from the original line (documented deliberate divergence) |
| CHANGELOG.md | `[Unreleased] → Added` entry |

### System Specs Updated
| Spec | Changes Recorded |
|------|-----------------|
| (none) | No system spec exists for cross-system; this feature folder is the permanent record |

## Testing

- [PASS] Full regression: 14 suites, 178/178 cases under bash (markdown-only diff — everything unchanged, as expected)
- [PASS] Dual-shell suite (test_security_guard_mcp_browser.sh) green under bash AND zsh; 6 other suites are bash-only harnesses by design (pre-existing, untouched by this diff)
- [PASS] T009 smoke matrix: the `[ -s /tmp/smith-build-clean-code-findings.txt ]` gate behaves identically under bash and zsh for missing/empty/non-empty files
- [PASS] T007 consistency greps: single Phase 3.5 heading (bugfix's distinct pre-existing Phase 3.5 untouched); findings filename identical at all 5 sites; zero hardcoded rubric line numbers; six-bullet parity verified byte-identical for bullets 2-6
- [N/A] Unit/E2E/Docker — no services in this repo

### Known Issues
- None.

## Deviations from Spec

- **Self-containment over reference**: plan/tasks said "reference data-model.md, don't restate," but a distributed SKILL.md cannot depend on the feature folder (not shipped to consumer installs). The Phase 3.5 section inlines the minimal operative rules (~75 lines vs the 40-70 target). Rationale recorded in tasks.md and here.
- **Model pin wording**: spec'd "Sonnet" was initially written as the superseded id `claude-sonnet-4-5`; corrected to the evergreen `model: sonnet` alias, matching smith-explore/smith-debug's existing agent-spec convention.
- quickstart.md Scenario 1 step 2 was corrected mid-build to match resolved Q6 (layered `.meta` coverage, no new machinery).

## Infrastructure

- Docker services rebuilt: none
- Health check: N/A
