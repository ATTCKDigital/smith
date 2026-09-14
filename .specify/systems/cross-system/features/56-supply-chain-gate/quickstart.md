# Quickstart: Supply-Chain & License Review Pass for smith-build

Verification walkthroughs for each user scenario (US-1..US-8). These are
manual/observational checks against a real `/smith-build` run or a direct
`smith-audit dependencies` invocation (per `plan.md`'s Test Strategy, this
feature's own automated coverage lives in
`tests/security/test_dependency_scan.sh` /
`test_license_inventory.sh` — these scenarios verify the FULL pipeline
integration those stubbed-scanner unit tests cannot exercise in
isolation). Each scenario reflects spec.md's A-6 outcomes, accepted at the
questions gate (`questions.md`, ANSWERED, 2026-09-13) exactly as
recommended — none of the behavior below is written as still-open.

## Prerequisites

- A feature branch with `spec.md`/`plan.md`/`tasks.md` ready for
  `/smith-build`, where Phase 3.6 (Security Review Pass) has just
  completed (flagged or clean — either way, Phase 3.7 runs regardless of
  Phase 3.6's own findings, per its own ordering-precondition-only gate,
  FR-2).
- `supply_chain.cve_scan` / `supply_chain.license_inventory` both `true`
  in `.smith/config.json` (the shipped default) unless a scenario states
  otherwise. `supply_chain.license_policy.deny` populated only for
  Scenario 5.
- This repository's own worktree (zero manifests) and
  `/Users/dennisplucinik/Projects/goldcanna-inventory` (real 2×npm + 1×poetry
  multi-manifest layout: `frontend/`, `menu-generator/`, `backend/`) are
  this feature's two primary validation targets, exactly as A-5 states —
  scenarios below name which one each exercises.

## Scenario 1 — Multi-manifest repo produces merged per-manifest CVE results (US-1 / SC-1)

**Given** `goldcanna-inventory` (or an equivalent 2×npm + 1×poetry
fixture) as the repository under scan — `frontend/package.json`+
`package-lock.json`, `menu-generator/package.json`+`package-lock.json`,
`backend/pyproject.toml`+`poetry.lock` — and `supply_chain.cve_scan` is
`true`.

**When** Phase 3.7 runs (or `smith-audit dependencies` is invoked
directly against this repo, per Scenario 6's own equivalence).

**Then**:
1. Manifest discovery finds all 3 manifests via the bounded-depth walk —
   verify `/tmp/smith-build-supply-chain-scan-status.txt` lists exactly 3
   `manifest_path` entries, each with both a `cve_scan=` and a
   `license_inventory=` line (`data-model.md` §5).
2. Sub-layer D scans each of the 3 manifests independently: if
   `osv-scanner`/`trivy` is present, a single whole-repo invocation covers
   all 3 (`scan-status.txt` shows the SAME `source_scanner` for all three
   `cve_scan=ran:<tool>` lines); if neither is present, each npm manifest
   is scanned via `npm audit --json --package-lock-only` independently and
   `backend/pyproject.toml` via `pip-audit` if present, else
   `skipped:absent`.
3. Findings from all 3 manifests merge into the SAME
   `/tmp/smith-build-supply-chain-findings.txt`, each line still carrying
   its own `manifest_path` in backticks (`data-model.md` §5) — verify no
   finding is missing its source manifest.
4. **US-4 sub-case (ENOLOCK, sibling unaffected)**: repeat with
   `menu-generator/package.json`'s `package-lock.json` temporarily
   removed. Verify `scan-status.txt` records
   `menu-generator/package.json: cve_scan=skipped:enolock` while
   `frontend/package.json`'s own `cve_scan=ran:...` line is UNCHANGED —
   the sibling manifest's scan completes normally, the pass does not fail
   or terminate because of the skipped one.
5. The workflow proceeds to Phase 4 with no termination — no finding, at
   any severity, blocks this run (FR-19/FR-20; `data-model.md` §7's
   explicit no-terminate contract).

## Scenario 2 — Manifest-less repo silent-skips (US-3 / SC-2, this repository's current baseline)

**Given** this repository's own current worktree state — zero dependency
manifests of any kind (confirmed via this feature's own `research.md` §7
tool-presence check incidentally also confirming no `package.json`/
`pyproject.toml`/`requirements.txt`/`go.mod`/`Cargo.toml` exists at this
worktree's root).

**When** Phase 3.7 runs.

**Then**:
1. Both Sub-layer D and Sub-layer L no-op with no error and no warning
   noise — verify the run's own stdout/logs contain nothing alarming.
2. `/tmp/smith-build-supply-chain-scan-status.txt` contains exactly the
   sentinel line `0 manifests found` (`data-model.md` §5) — the SAME
   wording recorded to the vault session log (FR-6).
3. `/tmp/smith-build-supply-chain-findings.txt` is empty or never
   created.
4. The PR body carries NO "Supply-Chain Review" section (FR-6/FR-22).
5. The workflow proceeds to Phase 4 exactly as if Phase 3.7 were absent —
   this scenario is directly executable in THIS repository today without
   any setup, since it matches the worktree's actual current state; it
   should be the FIRST scenario exercised once the feature is built, as
   the cheapest real-environment check available (mirroring feature 55's
   own quickstart's identical framing for ITS scanner-less-machine
   scenario).

## Scenario 3 — npm-audit JSON severity mapping via stub, exit code ignored (US-2 / SC-3)

**Given** `osv-scanner` and `trivy` are both absent (this dev machine's
own confirmed state — `research.md` §7), a fake `npm` shim is placed
FIRST on `$PATH` (matching `tests/security/test_dependency_scan.sh`'s own
stub approach — never a live network call for this specific verification
step) printing this EXACT, previously-observed-live JSON body for `npm
audit --json --package-lock-only` and exiting `1`:
```json
{"metadata": {"vulnerabilities": {"info": 0, "low": 1, "moderate": 5, "high": 19, "critical": 3, "total": 28}}}
```
(this is the REAL shape this research pass captured live against
`goldcanna-inventory/frontend` — `research.md` §7.1 — reused here verbatim
so the stub is grounded in an actually-observed tool output, not an
invented one).

**When** Sub-layer D falls back to `npm audit --json --package-lock-only`
for the npm manifest under this stub.

**Then**:
1. The scan parses `metadata.vulnerabilities` directly from the JSON
   body — verify the resulting findings/counts reflect `moderate: 5` →
   **5 Medium-severity findings** (or an equivalent Medium count if the
   stub's JSON also carries per-advisory detail — the bucket-count
   mapping is what's under test) and `info: 0` folding into the SAME
   low-severity bucket as `low: 1` (→ **1** low-severity note, not 2
   separate categories).
2. The scan's interpretation of findings-present is verified to be
   INDEPENDENT of the shim's exit code: re-run the same stub but patched
   to exit `0` instead of `1` with the IDENTICAL JSON body — the parsed
   severity counts and resulting findings must be BYTE-IDENTICAL to the
   exit-`1` run, proving the exit code was never consulted (FR-11's
   explicit, empirically-motivated requirement).
3. `scan-status.txt` records `cve_scan=ran:npm-audit` for this manifest,
   never `skipped:*` — the non-zero exit code must not be misread as a
   tool failure.

## Scenario 4 — Offline/timeout never hangs or fails the build (US-5 / SC-5)

**Given** two sub-cases, each exercised independently:
- **(a) Timeout**: a stub scanner (or a stub `npm`) that `sleep`s longer
  than `supply_chain.timeout_seconds` (set to a short value, e.g. `2`,
  for this verification — not the shipped default `60` — so the check
  completes quickly).
- **(b) Offline**: a stub scanner that exits non-zero immediately with
  connection-error-shaped stderr (simulating no network reachability,
  since `npm audit`/`pip-audit` both genuinely require it — `research.md`
  §7.1/§7.3 — even with `--package-lock-only`, per FR-9's own explicit
  no-local-only-exemption statement).

**When** Sub-layer D attempts the scan for the affected manifest in each
sub-case.

**Then**:
1. **(a)**: the invocation is bounded by
   `python3 subprocess.run(..., timeout=supply_chain.timeout_seconds)`
   (`research.md` §7.4's decided mechanism — NOT a shell `timeout`/
   `gtimeout` wrapper, both confirmed absent on the reference dev
   machine); `scan-status.txt` records `cve_scan=skipped:timeout` for
   that manifest, and the OVERALL Phase 3.7 run completes within a bounded
   time (does not hang) — verify by timing the run against the configured
   `timeout_seconds` × manifest count, not an unbounded wait.
2. **(b)**: `scan-status.txt` records `cve_scan=skipped:offline` for that
   manifest.
3. In both sub-cases: no error surfaces to the build, the build does NOT
   fail, and the Supply-Chain Review Pass completes and proceeds to Phase
   4 exactly as normal (`data-model.md` §7 — there is no terminate path
   for ANY outcome here, including a timeout/offline condition, unlike how
   a different kind of unrecoverable condition might be handled elsewhere
   in this pipeline).
4. A sibling manifest scanned successfully in the SAME run (a
   multi-manifest fixture, Scenario 1-style) is UNAFFECTED — its own
   `cve_scan=ran:...` line is present and its findings, if any, still
   appear in `/tmp/smith-build-supply-chain-findings.txt`.

## Scenario 5 — License UNKNOWN bucketing + deny-list hit (US-6 / US-7)

**Given** two sub-cases against `goldcanna-inventory`'s real environment:
- **(a) node_modules-absent gate**: `frontend/node_modules/` temporarily
  renamed/removed while `frontend/package.json`+`package-lock.json` remain
  present.
- **(b) Deny-list hit**: `supply_chain.license_policy.deny` set to
  `["GPL-3.0"]` (or any license identifier confirmed present in the
  live-inventoried `goldcanna-inventory/backend` poetry environment via
  this feature's own `importlib.metadata` walk — substitute the actual
  identifier found during implementation verification).

**When** Sub-layer L runs.

**Then**:
1. **(a)**: `frontend/package.json`'s license inventory is
   skipped-with-disclosure (`scan-status.txt`:
   `license_inventory=skipped:no_node_modules`) — EVEN THOUGH Sub-layer D
   may still scan the SAME manifest for CVEs successfully in the same run
   (FR-14's stricter-than-Sub-layer-D precondition, verified by checking
   BOTH lines for the same `manifest_path` show DIFFERENT outcomes). A
   sibling manifest with `node_modules/` present (e.g.
   `menu-generator/`) still resolves via the dependency-free walk —
   verify its license records appear normally, requiring no newly
   installed tooling (SC-4).
2. **UNKNOWN bucketing, live-grounded**: verify the merged inventory
   includes an `UNKNOWN` bucket entry ONLY for a package that genuinely
   exposes none of `License-Expression`/`License`/a `License ::`
   classifier (Python) or neither `license` nor `licenses[]` (npm) — NOT
   for `click`-shaped packages (real `License-Expression`-only case,
   `data-model.md` §4) or `xmlhttprequest-ssl`-shaped packages (real
   legacy `licenses[]`-only case) — both of which must resolve via their
   respective fallback and NEVER land in `UNKNOWN` once the fallback chain
   is correctly implemented (this research pass's own live-verified
   0/95-true-UNKNOWN and 508/508-resolved counts, `data-model.md` §4, are
   the exact regression bar this check re-verifies against the real
   environment).
3. **(b)**: a Finding is produced at High severity, category
   `license-policy`, for every package whose inventoried license matches
   the configured `deny` entry — verify it appears in
   `/tmp/smith-build-supply-chain-findings.txt` with `sub-layer: L`.
4. The workflow is NOT terminated by the deny-list hit, regardless of how
   many packages match or how central the flagged package is — no
   severity, from either sub-layer, blocks any phase in this version
   (`data-model.md` §7).

## Scenario 6 — smith-audit whole-project invocation (US-8 / SC-6)

**Given** a user runs `smith-audit dependencies` (item 7,
`skills/smith-audit/SKILL.md:115`) against a system whose codebase
includes a repository with dependency manifests — `goldcanna-inventory`
itself, or this repo once a manifest is temporarily added for the check.

**When** the Dependencies sub-audit runs.

**Then**:
1. It invokes the SAME `scripts/security/_manifest_discovery.py`, the
   SAME extended `detect-scanners.sh`, and the SAME
   `dependency-scan.py`/`license-inventory.py` Phase 3.7 uses — verify by
   confirming the script PATHS referenced are byte-identical to Phase
   3.7's own resolution (installed-path-preferred, repo-dev fallback,
   `research.md` §1's own idiom), not a second copy or a
   `smith-audit`-specific reimplementation.
2. It scans the WHOLE project, not a diff — no `BASE_BRANCH` threading of
   any kind, consistent with `smith-audit`'s existing on-demand model
   (FR-25) AND with Phase 3.7's own non-diff-scoped design (FR-3) — these
   two properties are NOT a coincidence, they're the same underlying
   design choice reused in two invocation contexts.
3. No separate or duplicated CVE-scanning or license-inventory
   implementation exists anywhere in `smith-audit`'s own SKILL.md prose or
   any dedicated `smith-audit`-only script (FR-26) — verify via
   `grep -rn "dependency-scan\|license-inventory" skills/smith-audit/SKILL.md`
   resolving to invocation references only, never a re-implementation.
4. The sub-audit's own report output reflects the SAME finding shapes
   (`data-model.md` §3/§4) Phase 3.7's PR-body section uses, closing
   feature 55's own NFR-4 intent — which explicitly named this feature as
   `detect-scanners.sh`'s second consumer — concretely, not just in
   principle.

## Post-run cleanup

`/tmp/smith-build-supply-chain-findings.txt` and
`/tmp/smith-build-supply-chain-scan-status.txt` are ephemeral scratch
output, matching every other `/tmp/smith-build-*` file this pipeline
already produces (Phase 3.5's, Phase 3.6's, §5.3's, §5.3.1's) — no new
cleanup step is introduced by this feature. Unlike a Phase 3.6 hard-stop,
Phase 3.7 never leaves a worktree in a special "terminated" state to clean
up after — every run of this phase ends the same way, proceeding to Phase
4, regardless of what either sub-layer found.
