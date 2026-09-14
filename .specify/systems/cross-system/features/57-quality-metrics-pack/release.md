# Release: Quality Metrics Pack

**Date**: 2026-09-14
**Branch**: 57-quality-metrics-pack
**PR**: #TBD
**Spec**: [spec.md](spec.md)

## Summary

smith-build's testing phase is now project-agnostic and metrics-aware: §3.1 testing plus new §3.1b lint / §3.1c typecheck run whatever commands the project declares in the new `quality` config key (verbatim Armory-shaped fallback when absent — zero behavior change); new §3.4 checks coverage against a configured minimum (built-in regex catalogue + override, unparseable disclosed); new §5.3.2 Function-Length Scan flags >100-line functions individually and folds 50-100 into a count, reusing meta_describe.py's battle-tested length derivation with zero parser/schema changes. smith-bugfix §5.3 gets the same lint generalization. Two new PR-body advisory sections. All flag-never-block.

## Changes
Modified: smith-build SKILL (3.1 generalized + 3.1b/3.1c + 3.4 + 5.3.2 + 2 PR sections), smith-bugfix SKILL (§5.3), config template `quality` key + init seed + update §5.1e, CHANGELOG, seed-test (+1). New: tests/skills/test_smith_build_function_length_scan.sh (7 assertions, bash+zsh).

## Testing
- 7/7 new scan test (both shells); 19/19 seed test; full regression green under bash — zero feature-attributable failures; census of pre-existing drift recorded (13 zsh BASH_SOURCE harness cases; 2 bash-failing --describe tests; 5 top-level .py tests need -m invocation) — none touched by this feature.
- T015 ran the literal shipped §5.3.2 snippet (byte-extracted) against fixtures: decompose/soft/clean/excluded/override all correct.
- Phase 3.5 review: 1 Medium auto-fixed (unreset PARSER — silent wrong-language parse risk), validated; 2 Medium + 2 Low flagged (PR body).
- Dogfood: secret scan + supply-chain scan both clean on this branch.

## Deviations
- SKILL sections written as fully worked runnable heredocs (repo precedent) — larger than plan's prose estimate.
- One agent used git stash mid-build against worktree rules (no harm — stack verified clean); ledger note.

## Infrastructure
None.
