# Release: Inline Security Review Pass

**Date**: 2026-09-13
**Branch**: 55-security-review-pass
**PR**: #TBD
**Spec**: [spec.md](spec.md)

## Summary

Every smith-build diff now gets a three-layer security review before commit, and both committing pipelines gain a non-bypassable pre-commit secret gate. Layer 1 is a new dependency-free secret scanner (redacted output, allow-marker escape hatch) that ALWAYS terminates the workflow on Critical secret findings — the system's second non-bypassable denial; Layers 2 (presence-detected SAST) and 3 (LLM review, Opus default with `review_model` override) flag by default into a "Security Review" PR-body section that always discloses which layers actually ran.

## Changes

### Files Created
| File | Purpose |
|------|---------|
| scripts/security/secret_scan.py | Pattern engine (296 lines): AWS/GCP/PEM/GitHub/Slack/entropy/conn-string catalogue; masked excerpts — raw secret bytes never printed; binary skip; same-line `# smith-secret-scan: allow` marker; gitleaks-JSON normalization through the same redaction |
| scripts/security/secret-scan.sh | bash+zsh wrapper (~100 lines): --diff-base (diff ∪ untracked, deduped) / --files / --config / --with-gitleaks; exit 0 clean / 1 findings / 2 error; config via argv (no string interpolation) |
| scripts/security/detect-scanners.sh | Shared presence-detect (gitleaks/semgrep/bandit), reusable by F2 + smith-audit |
| tests/security/test_secret_scan.sh | 40 assertions incl. --diff-base + untracked-file regression case, redaction sweeps, allowlist-vs-deterministic semantics, both shells |
| tests/security/test_detect_scanners.sh | 5 assertions via PATH stubs |

### Files Modified
| File | Change |
|------|--------|
| skills/smith-build/SKILL.md | New "## Phase 3.6: Security Review Pass" (97 lines, self-contained): three layers; findings contract w/ layer attribution; Layer-1 Critical secrets → non-bypassable terminate (no commit/push, hard-stop marker, worktree preserved); tier-governed L2/L3 (default flag); conditional "## Security Review" PR section with layer disclosure; Key Rules disambiguation |
| skills/smith-bugfix/SKILL.md | §7.1 pre-commit Layer-1 secret gate (~21 lines), same terminate semantics; deliberately Layer-1-only |
| templates/config.default.json | `security_review` key (enforcement_tier flag, review_model opus, layers, excludes, allowlist_globs) |
| skills/smith/SKILL.md | Init-time non-destructive seeding (with existence + isinstance guards — hardened after review) |
| skills/smith-update/SKILL.md | New §5.1c per-project merge of the key |
| scripts/install.sh | New scripts/security/* copy stanza (task-gen caught its absence — scanner would never have shipped) |
| docs/security-model.md | New "Code-Content Security Review" section; "sole non-bypassable" rescoped (now two); audit list 4→7 files |
| CHANGELOG.md | [Unreleased] Added entry |
| tests/hooks/test_config_default_seed.sh | +1 assertion for the new key |

## Testing

- [PASS] tests/security/test_secret_scan.sh — 40/40 under bash AND zsh
- [PASS] tests/security/test_detect_scanners.sh — 5/5 both shells
- [PASS] Full regression: all hook + top-level suites green under bash; 7 pre-existing zsh-only harness failures traced to untouched files (unguarded BASH_SOURCE under set -u), logged not fixed
- [PASS] End-to-end planted-secret matrix 21/21 (detection, redaction, allowlist-gates-entropy-only, install-to-scratch-HOME)
- [PASS] Dogfood: `secret-scan.sh --diff-base main` on this very branch → initially 28 findings, all on the feature's own fake fixtures (redaction verified in every line); resolved via allow-markers with two heredoc restructures keeping planted fixture bytes identical → final exit 0

### Known Issues
- None. Three portability bugs (two zsh, one bash-3.2) found and fixed during development.

## Clean Code Review (Phase 3.5 — first real execution)

The new-in-#59 review pass proved itself on its first run: it empirically reproduced a **Critical scope bug in this feature's own scanner** (`--diff-base` omitted untracked files — new files were invisible to Layer 1 in exactly the smith-build/bugfix invocation mode), plus a High config-clobber bug in the init seeding, a config-path injection footgun, and the test gap that hid the Critical. All four fixed with regression coverage before commit; 2 low-severity notes remain (PR body).

## Deviations from Spec

- The 3-subprocess config read was consolidated to one argv-based python call (resolves a Low note; behavior-preserving).
- Dogfood-driven addition: allow-markers on the repo's own fixtures + the heredoc-restructure pattern (markers stay script-side, planted bytes unchanged) — now the reference example for consumer repos with fake canaries.

## Infrastructure

- Docker: none. Health check: N/A.
