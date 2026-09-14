# Implementation Questions: Supply-Chain & License Gate

**Generated**: 2026-09-13
**Feature**: [spec.md](./spec.md)
**Plan**: [plan.md](./plan.md)
**Status**: ANSWERED

> All six answers accepted via the user's standing delegation ("continue all the way through all of them with as little feedback from me as possible" — auto-accept recommended answers, recorded here for the audit trail). Each recommendation is evidence-backed in research.md §9 / the exploration report.

---

## Q1: Extend Phase 3.6 or add Phase 3.7?
**Options**: A) new Phase 3.7 — 3.6's decision table + terminate rule are deliberately secret-specific/closed; insertion-point precedent (54→3.5, 55→3.6) reuses cleanly. B) extend 3.6 — fewer sections but forces reopening a closed, tested contract.
**Recommended**: A.
**Answer**: A (accepted via delegation).

## Q2: Config home?
**Options**: A) new top-level `supply_chain` key — security_review is schema-closed (its FR-24); nesting non-tiered CVE/license settings inside a tier-driven layers object implies false semantics. B) nest under security_review.
**Recommended**: A.
**Answer**: A (accepted via delegation).

## Q3: Enforcement for CVE/license findings?
**Options**: A) flag-only v1, no terminate path — CVEs aren't diff-introduced (unlike secrets); npm audit exit code empirically useless (real projects exit 1 essentially always); full-project scan with explicit not-diff-scoped rationale in the PR section. B) block_on_critical parity with L2/L3 — punishes builds for pre-existing transitive advisories.
**Recommended**: A.
**Answer**: A (accepted via delegation).

## Q4: License scope v1?
**Options**: A) inventory-only + config-only policy (empty allow/deny defaults; deny hits = High, still flag) — dependency-free implementation verified live; no shipped licensing opinion. B) shipped default deny list — Smith opining on licensing without being asked.
**Recommended**: A.
**Answer**: A (accepted via delegation).

## Q5: smith-bugfix inclusion?
**Options**: A) No — bugfix stays light (its own stated rationale for Layer-1-only), and a small patch essentially never introduces dependencies. B) Yes — cost without matching risk.
**Recommended**: A.
**Answer**: A (accepted via delegation).

## Q6: smith-audit Dependencies wiring in this feature?
**Options**: A) Yes — the sub-audit is a one-line brief with zero implementation today; wiring the same scripts is purely additive and closes F1 NFR-4's named intent. B) Defer — leaves a second implementation to drift later.
**Recommended**: A.
**Answer**: A (accepted via delegation).

---

Plan-level mechanical resolutions (not gate matters, recorded): python3 subprocess timeouts (no timeout/gtimeout on macOS); per-file install.sh copy lines for the three new scripts; shared `_manifest_discovery.py` module; yarn/pnpm lockfiles satisfy discovery but not the npm-audit fallback (disclosed as skipped); license field fallback chains (license → licenses[] → License-Expression → classifiers → UNKNOWN).
