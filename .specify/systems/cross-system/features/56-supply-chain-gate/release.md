# Release: Supply-Chain & License Gate

**Date**: 2026-09-14
**Branch**: 56-supply-chain-gate
**PR**: #TBD
**Spec**: [spec.md](spec.md)

## Summary

smith-build gains Phase 3.7 (Supply-Chain Review Pass): per-manifest dependency CVE scanning (osv-scanner/trivy when present → npm audit / pip-audit fallbacks → skip-with-disclosure) and a dependency-free license inventory with config-only policy — flag-only by design (CVEs aren't diff-introduced; the PR section states the not-diff-scoped rationale explicitly). smith-audit's Dependencies sub-audit now invokes the same scripts — one implementation, two consumers, closing feature 55's NFR-4 intent.

## Changes

Created: scripts/security/{_manifest_discovery.py, _scan_parsers.py, dependency-scan.py+.sh, license-inventory.py+.sh}; tests/security/{test_dependency_scan.sh (30), test_license_inventory.sh (18)}.
Modified: detect-scanners.sh (9-tool loop) + its test (6); install.sh (+6 cp lines incl. the _scan_parsers.py line verification caught — installed copies would have crashed); smith-build SKILL (Phase 3.7, 89 lines + PR section); config template supply_chain key + init/update §5.1d seeding; smith-audit item 7 wired; docs/security-model.md new section + audit list 7→9; CHANGELOG; seed-test assertion.

## Testing

- 94 security-suite assertions green under bash AND zsh; full regression green (bash); known 7 pre-existing zsh-only harness cases logged.
- Fixture e2e 41/41 across all six quickstart scenarios (goldcanna-shaped multi-manifest, ENOLOCK, severity mapping with exit-code independence, timeout/offline disclosure, UNKNOWN + deny-list, audit-mode equivalence). No live network in any test (PATH stubs).
- Phase 3.5 review: 3 auto-fixes applied+validated (shared _manifest_dir, dead OFFLINE_PATTERN, stale 3-tool comment); 2 defensible Medium duplication flags remain (PR body).
- Dogfood: Layer-1 secret scan clean after marking AWS's documented example key in research notes; supply-chain scan on this near-manifest-less repo correctly discovered the one incidental requirements.txt and disclosed skipped:absent.

## Deviations from Spec

- Orchestrator does internal shutil.which() detection rather than shelling to detect-scanners.sh (documented; detect-scanners.sh remains the disclosure/audit-facing helper).
- poetry run pip-audit console-script form (PATH-stubbable) over python -m form.
- License field fallback chains extended from live findings (legacy licenses[], License-Expression).

## Infrastructure
- Docker: none. Health: N/A.
