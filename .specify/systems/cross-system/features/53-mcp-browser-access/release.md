# Release: MCP-First Browser Verification

**Date**: 2026-09-13
**Branch**: 53-mcp-browser-access
**PR**: #TBD (filled at PR creation)
**Spec**: [spec.md](spec.md)

## Summary

Smith agents can now verify auth-gated staging/production screens through the user's already-logged-in Chrome via a Playwright MCP bridge (`--extension` mode) instead of launching a headed browser that requires re-login — gated by a new security guard hook that closes the previously-unguarded `mcp__playwright__*` surface. Fallback to pre-existing behavior is silent and immediate whenever the tools are absent, the mode isn't `extension`, the session is non-interactive, or the bridge connect stalls (fail-fast, no retry).

## Changes

### Files Created
| File | Purpose |
|------|---------|
| hooks/security-guard-mcp-browser.sh | PreToolUse guard for `mcp__playwright__*` (274 lines): read-only tools pass; interaction tools (incl. `browser_evaluate`) policy-gated via `.smith/security-config.json` `browser_verification`; unknown targets fail-safe to production; localhost/127.0.0.1/::1 always staging; production interactions require explicit operator confirmation, NON-bypassable by `warn_only_mode`; `allow_interactions: false` master kill-switch; silent no-op on missing/malformed config |
| tests/hooks/test_security_guard_mcp_browser.sh | 18-assertion suite on the shared hook-test harness; run under bash AND zsh with byte-identical output (harness self-detects interpreter so the zsh run genuinely drives the hook under zsh) |

### Files Modified
| File | Change |
|------|--------|
| settings/smith-settings-fragment.json | New PreToolUse entry, matcher `mcp__playwright__` (bare substring per repo regex-matcher convention — a literal `*` glob would never match); dedupe-key verified to survive repeated installs exactly once |
| skills/smith/SKILL.md | Init-time non-destructive seeding of `browser_verification.urls` (empty staging/production lists) in `.smith/security-config.json`; Q19 CLAUDE.md generation now references the new convention section |
| skills/smith-update/SKILL.md | New §5.1b: per-project non-destructive merge of the `browser_verification.urls` key on update |
| templates/claude-md-additions.md | New top-level "## MCP-First Browser Verification" section: tool-presence detection; `browser_verification.mcp_mode` (`extension`\|`sandbox`\|`off`, read from `.smith/config.json`, never inferred — bridge and sandbox servers expose identical tool names); silent-skip fallback; non-interactive/scheduler hard-skip; staging/production URL table (human view of the security-config machine source); full decision chain; fail-fast on stalled bridge connect |
| skills/smith-index/SKILL.md | migrate-templates missing-header detection list gains the new section |
| scripts/smith-index/run.py | `CLAUDE_SECTIONS` constant gains the new header — the actual code path for migrate-templates (out-of-plan fix; the SKILL.md list alone was non-functional) |
| skills/smith/agents/product-manager.md | E2E approach gains MCP-first-with-fallback step; Test URLs table gains staging/production rows |
| skills/smith/agents/senior-qa.md | MCP-first-with-fallback contract before E2E functional testing |
| skills/smith/agents/staff-frontend.md | Key Responsibilities item 4 gains the contract clause |
| skills/smith/agents/staff-fullstack.md | Defect Handling step 1 gains the contract clause |
| skills/smith-audit/SKILL.md | UX + SEO sub-audits get MCP-first-with-fallback (SEO cross-references UX) |
| docs/security-model.md | Two guards → three, per-guard subsection for the new hook, 4th "What to Audit Before Enabling" item, knock-on count fixes |
| docs/hooks.md | Hook Summary row + Detailed Reference entry for the new guard |
| CHANGELOG.md | `[Unreleased] > Added` entry for the feature |

### System Specs Updated
| Spec | Changes Recorded |
|------|-----------------|
| (none) | No system spec exists for cross-system in this repo; the feature folder (spec/plan/research/data-model/questions/quickstart/tasks) is the permanent record |

## Testing

### Unit / Hook Tests
- [PASS] tests/hooks/test_security_guard_mcp_browser.sh — 18/18 under bash, 18/18 under zsh, byte-identical output
- [PASS] Full hook regression — 12 suites under bash all green (test_config_default_seed 16/16, test_context_budget_guard 14/14, test_context_loader 8/8, test_create_active_workflow 25/25, test_git_hooks 7/7, test_hook_chain_order 6/6, test_manifest_updater 7/7, test_save_preserves_descriptions 12/12, test_user_prompt_logger 17/17, test_workflow_gate_exemption 12/12, plus the new suite); 5 suites re-run under zsh where the harness supports it, all green
- [PASS] tests/get-base-branch.test.sh 8/8, tests/workflow-gate-redirect.test.sh 14/14, tests/workflow-summary-session.test.sh 5/5
- [PASS] settings fragment: valid JSON; dedupe-settings.sh keeps the new entry exactly once across simulated repeated installs
- [PASS] migrate-templates idempotency (real runner, scratch dir): run 1 appends the section once with one backup; run 2 no-op, byte-identical
- [SKIP] Python suites (cover workflow_summary_lib only, untouched; pytest unavailable in env)
- [N/A] Playwright E2E — no frontend files in this repo

### Known Issues
- None attributable to this feature. Five hook-test harnesses are bash-only by design (pre-existing, untouched).

## Deviations from Spec

- Unlisted `mcp__playwright__*` tool names (outside the 7 read-only + 8 interaction names in data-model §4) fall through the guard unclassified to the normal permission flow — matches the sibling guards' "no pattern matched → exit 0" convention; data-model is authoritative over broader early drafts.
- `scripts/smith-index/run.py` was modified although absent from plan.md's file list: its hardcoded `CLAUDE_SECTIONS` constant is the real migrate-templates code path, and without the addition FR-14/SC-5 could not be met. Flagged in tasks.md Coverage Notes.
- research.md §13's `browser_evaluate` heuristic was superseded by answered Q4 (always interaction-class); implemented per Q4.

## Infrastructure

- Docker services rebuilt: none (no services in this repo)
- Health check: N/A
- File-size advisory: `scripts/smith-index/run.py` — 1,664 lines (pre-existing size; this PR adds one constant entry)
