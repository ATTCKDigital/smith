---
feature: 56-supply-chain-gate
primary_system: cross-system
also_affects: []
branch: 56-supply-chain-gate
created: 2026-09-13
status: in-progress
answers_applied: 2026-09-13
---

# Supply-Chain & License Review Pass for smith-build

## Overview

Feature 54 added a post-hoc **Clean Code Review Pass** (`smith-build` Phase
3.5), and feature 55 added an inline **Security Review Pass** (Phase 3.6)
covering secrets, SAST, and LLM-judged security issues in the *code* a
build produces. Neither touches the *dependencies* that code pulls in:
`smith-build` ships whatever versions a project's manifests declare with
zero vulnerability scanning, and Smith has no mechanism to enumerate — let
alone police — the licenses those dependencies carry. This feature adds a
new **Supply-Chain Review Pass**, `smith-build` Phase 3.7, running after
Phase 3.6 and before Phase 4, plus a config-driven (flag-only) reporting
surface and a conditional "Supply-Chain Review" PR-body section. It also
upgrades `smith-audit`'s existing one-line "Dependencies" sub-audit item to
invoke the same scripts this feature introduces, so scanning logic has one
implementation and two consumers.

It is informed by a pre-feature exploration
(`.smith/vault/explore/explore-2026-09-13-supply-chain-gate.md`, status:
clear, 8 findings, no blocking conflicts) whose findings are binding design
constraints encoded throughout this spec (traced in this feature's
requirements checklist).

**Terminology used throughout this spec:**
- **Sub-layer** — one of the two independent mechanisms this feature adds:
  **Sub-layer D** (dependency CVE scan) and **Sub-layer L** (license
  inventory). Both run within the same phase; neither is presence-gated on
  the other.
- **Supply-Chain Review Pass** — the new `smith-build` Phase 3.7 subagent
  step that runs both sub-layers against the repository's currently
  discovered dependency manifests, strictly after Phase 3.6 (Security
  Review Pass) has completed and strictly before Phase 4 (Spec Updates)
  begins. Unlike Phase 3.5/3.6, this pass is a **full-project scan, not a
  diff scan** — see FR-3.
- **Manifest** — a dependency-declaration file this feature's discovery
  step recognizes: `package.json` + a matching lockfile, `pyproject.toml`/
  `poetry.lock`, `requirements.txt`, `go.mod`, or `Cargo.toml`. A
  repository may contain zero, one, or many manifests, of the same or
  different ecosystems.
- **Finding** — one CVE or license-policy violation identified by either
  sub-layer, carrying: severity, package name + version, source manifest
  path, ecosystem, the sub-layer that found it, a category label, and a
  rationale.
- **Skip-with-disclosure** — this feature's behavior for every absence or
  failure case it defines (zero manifests repo-wide, a scanner tool
  absent, an npm manifest missing its lockfile, `node_modules/` absent for
  Sub-layer L, a scan call timing out or running offline): the pass
  proceeds with no error, no warning noise, and no impact on the build,
  while recording exactly what was skipped and why — at the vault
  session-log level always, and additionally in the PR-body section
  whenever that section is otherwise included (FR-22/FR-24).
- **Enforcement** — this feature ships **flag-only** in v1: no finding, at
  any severity, from either sub-layer, can block, delay, or terminate the
  workflow. There is no config-driven tier and no terminate path, unlike
  Phase 3.6's `enforcement_tier` (FR-19/FR-20).

## Problem Statement

`smith-build` and `smith-audit` both have a supply-chain-shaped gap the
exploration pass confirmed is unaddressed today:

1. **No dependency CVE visibility.** Feature 55 closed the gap for secrets,
   SAST, and LLM-judged issues *in the code a build produces* — but nothing
   in the pipeline inspects the dependency graph a project pulls in.
   `smith-build` commits and pushes a diff with zero knowledge of whether
   the manifests it ships declare a package with a known vulnerability.
2. **No license visibility or policy.** Smith has no mechanism today to
   enumerate what licenses a project's dependencies carry, let alone flag
   one that conflicts with a project's own policy. This is a distinct
   concern from CVE scanning — a perfectly secure package can still carry
   a license a project cannot legally ship — and needs its own inventory,
   not a byproduct of the CVE scan.
3. **`smith-audit`'s Dependencies sub-audit is a one-line placeholder.**
   `skills/smith-audit/SKILL.md` item 7 reads "**Dependencies**
   (`smith-audit dependencies`) — outdated packages, CVEs, unused deps"
   with no script behind it. Feature 55's NFR-4 explicitly designed its
   scanner-presence-detection helper for reuse "by the future
   dependency-CVE/SCA feature (F2, out of scope here)" — this feature is
   that F2, and closing that named intent is part of its scope, not an
   afterthought.

The exploration pass ahead of this feature
(`.smith/vault/explore/explore-2026-09-13-supply-chain-gate.md`) confirmed
two concrete, contrasting manifest realities that this design must handle
without erroring: this repository itself currently has **zero** dependency
manifests (the silent-skip case), while `goldcanna-inventory` — a real
consuming project — is **multi-manifest** (2 npm manifests + 1 poetry
manifest). The exploration found no blocking conflicts; its 8 findings are
design constraints resolved by encoding them into this spec, not open risks
requiring rework.

## User Scenarios

### US-1 — Multi-manifest repo produces merged per-manifest CVE results (primary flow)
```gherkin
Given a repository containing 2 npm manifests (each with package.json + a
    matching lockfile) and 1 poetry manifest (pyproject.toml + poetry.lock)
    — the goldcanna-inventory-shaped fixture
Given supply_chain.cve_scan is true (the shipped default)
When the Supply-Chain Review Pass (Phase 3.7) runs
Then manifest discovery finds all 3 manifests via the bounded-depth walk
And Sub-layer D scans each of the 3 manifests independently
And the 3 manifests' results are merged into a single build-level output,
    each finding still traceable to its source manifest path
And the workflow proceeds to Phase 4 with no termination — no finding, at
    any severity, can block this version's pipeline (FR-19/FR-20)
```

### US-2 — npm audit fallback parses severity correctly, exit code ignored
```gherkin
Given osv-scanner and trivy are both absent from the machine
Given an npm manifest with a lockfile is discovered
When Sub-layer D falls back to `npm audit --json` for that manifest
Then the scan parses the metadata.vulnerabilities severity buckets from the
    JSON output, mapping "moderate" to this feature's Medium severity and
    "info" into the same folded low-severity count as "low"
And the scan's interpretation of findings-present is NEVER derived from
    npm audit's process exit code — it is empirically non-zero on real
    projects even with only unrelated/low-severity advisories present
```

### US-3 — Manifest-less repo silent-skips (this repository's current baseline)
```gherkin
Given the repository under scan contains zero dependency manifests of any
    kind (this repository's current state)
When the Supply-Chain Review Pass runs
Then both Sub-layer D and Sub-layer L no-op with no error and no warning
    noise
And the zero-manifest outcome is recorded in the vault session log
And the PR body carries no "Supply-Chain Review" section
And the workflow proceeds to Phase 4 exactly as if the phase were absent
```

### US-4 — npm manifest missing its lockfile is skipped without failing the pass
```gherkin
Given a repository contains one npm manifest with a package.json but no
    matching lockfile, alongside one other manifest that does have its
    lockfile present
When Sub-layer D runs
Then the lockfile-less manifest's CVE scan is skipped-with-disclosure,
    recorded as ENOLOCK / no-lockfile
And the sibling manifest's scan still runs and completes normally
And the pass does not fail or terminate because of the skipped manifest
```

### US-5 — Offline/timeout never hangs or fails the build
```gherkin
Given a scanner invocation for one discovered manifest would exceed its
    configured timeout, or the machine currently has no network access
When Sub-layer D attempts that scan
Then the invocation is bounded by its hard timeout (default 60 seconds per
    manifest, config-overridable via supply_chain.timeout_seconds)
And on timeout or offline failure, that manifest/tool is recorded as
    skipped-with-disclosure rather than causing an error
And the Supply-Chain Review Pass completes without hanging and without
    failing the build
```

### US-6 — License inventory is dependency-free and gated on node_modules presence
```gherkin
Given an npm manifest has package.json and a lockfile, but node_modules/
    has not been installed at that manifest's location
When Sub-layer L runs
Then that manifest's license inventory is skipped-with-disclosure, even
    though Sub-layer D may still be able to scan the same manifest for
    CVEs — FR-7's lockfile precondition being satisfied is not sufficient
    for Sub-layer L
Given a sibling manifest DOES have node_modules/ present
Then that sibling manifest's license inventory runs via the dependency-free
    node_modules/*/package.json walk, requiring no newly installed tooling
```

### US-7 — License deny-list hit is flagged, never blocking
```gherkin
Given supply_chain.license_policy.deny contains one license identifier
Given the license inventory finds one package whose license matches that
    deny entry
When Sub-layer L evaluates the inventory against the configured policy
Then a Finding is produced at High severity, category license-policy
And the finding is recorded to the PR-body "Supply-Chain Review" section
And the workflow is NOT terminated and no phase is blocked, regardless of
    this finding's severity — no terminate path exists in this version
    (FR-19/FR-20)
```

### US-8 — smith-audit's Dependencies sub-audit invokes the same scripts
```gherkin
Given a user runs smith-audit against a system whose codebase includes a
    repository with dependency manifests
When the Dependencies sub-audit (skills/smith-audit/SKILL.md item 7) runs
Then it invokes the same extended detect-scanners.sh and the same
    Sub-layer D/L scripts Phase 3.7 uses, scanning the whole project rather
    than a diff
And no separate or duplicated CVE-scanning or license-inventory
    implementation exists for smith-audit's own use
```

## Functional Requirements

### Insertion point & invocation (smith-build)

- **FR-1**: `smith-build` MUST run a new **Supply-Chain Review Pass** as
  Phase 3.7, strictly after Phase 3.6 (Security Review Pass) has completed
  and strictly before Phase 4 (Spec Updates) begins — reusing the same
  insertion-point pattern features 54 and 55 established (a new phase
  slotted between the prior phase's close and Phase 4). Both sub-layers (D
  and L) execute within this single phase.
- **FR-2**: Phase 3.7 MUST run exactly once per build; it is gated on Phase
  3.6 having completed as an ordering precondition only (independent of
  Phase 3.6's outcome on runs where 3.6 does not itself hard-stop the
  build), never re-entered regardless of how many findings either
  sub-layer produces.
- **FR-3**: Unlike Phase 3.5/3.6, Phase 3.7 does NOT diff against
  `$BASE_BRANCH` — it performs a full-project scan of the repository as
  currently checked out (whole-repo manifest discovery, whole-repo license
  inventory), because dependency CVEs and license obligations are
  properties of the currently-declared dependency set, not of this
  branch's diff. `WORKTREE_PATH` context threading is still reused to
  locate the repository root, but `BASE_BRANCH` is not used to scope what
  gets scanned. This divergence from the diff-scoped precedent Phase
  3.5/3.6 set MUST be disclosed explicitly wherever this pass's findings
  are reported (FR-24).

### Manifest discovery

- **FR-4**: Phase 3.7 MUST discover dependency manifests via a
  bounded-depth walk of the repository, excluding the same path families
  the existing §5.3/§5.3.1 scans exclude (`vendor/`, `node_modules/`,
  `.venv/`, `dist/`, `build/`, `.smith/`), searching for: `package.json`
  paired with a matching lockfile, `pyproject.toml` paired with
  `poetry.lock`, `requirements.txt`, `go.mod`, and `Cargo.toml`.
- **FR-5**: A repository MAY contain multiple manifests, of the same or
  different ecosystems (e.g., 2 npm manifests + 1 poetry manifest). Phase
  3.7 MUST scan each discovered manifest independently and merge every
  manifest's results into the single findings/disclosure output produced
  for that build.
- **FR-6**: When manifest discovery finds zero manifests repo-wide (this
  repository's own current state), both Sub-layer D and Sub-layer L MUST
  no-op with no error. This outcome is disclosed via Phase 3.7's standard
  vault session-log entry recording "0 manifests found" — satisfying
  skip-with-disclosure at the log level. Per FR-22, the zero-manifest case
  does NOT by itself produce a "Supply-Chain Review" PR-body section, since
  a manifest-less repository has no dependency surface for a PR reader to
  be informed about — mirroring the existing omit-when-nothing-to-report
  convention §5.3, §5.3.1, Phase 3.5, and Phase 3.6 already use.
- **FR-7**: For an npm-ecosystem manifest, Sub-layer D's `npm audit`
  fallback requires the matching lockfile to be present. When a
  `package.json` is discovered with no lockfile alongside it, that
  specific manifest's CVE scan is skipped-with-disclosure (recorded as
  `<path>: skipped (no lockfile / ENOLOCK)`) rather than failing the whole
  pass; sibling manifests are unaffected.

### Sub-layer D — dependency CVE scan

- **FR-8**: When `osv-scanner` or `trivy` is present on the machine
  (presence-detected via the shared helper, NFR-4), Sub-layer D MUST
  prefer it as a single multi-ecosystem scan covering all discovered
  manifests in one pass — `osv-scanner` first, `trivy` second, when both
  are present.
- **FR-9**: When neither `osv-scanner` nor `trivy` is present, Sub-layer D
  MUST fall back to per-manifest scanning: `npm audit --json` for each npm
  manifest that has its lockfile (FR-7), and `pip-audit` for each Python
  manifest, only when `pip-audit` is itself present (presence-detected the
  same way). A Python manifest with `pip-audit` absent is
  skipped-with-disclosure for that manifest. `npm audit`, even when
  invoked with `--package-lock-only` to avoid touching `node_modules/`,
  still requires network access to query its advisory database — it is
  therefore subject to the same offline/timeout handling as every other
  scanner in this sub-layer (FR-12), with no local-only exemption.
- **FR-10**: When neither the multi-ecosystem scanners (FR-8) nor the
  applicable per-manifest fallback tool (FR-9) is available for a given
  manifest, that manifest's CVE scan is skipped-with-disclosure. This MUST
  NOT fail the build or block the scanning of other manifests.
- **FR-11**: Parsing `npm audit --json` output MUST read the
  `metadata.vulnerabilities` severity buckets from the JSON body; the scan
  MUST NEVER branch on `npm audit`'s process exit code to determine
  pass/fail or findings-present/absent — the exit code is empirically
  non-zero on real-world projects essentially always, even with only
  unrelated or low-severity advisories present, making it useless as a
  signal. `npm audit`'s `moderate` bucket maps to this feature's `Medium`
  severity; its `info` bucket folds into the same low-severity count as
  `low` (FR-23).
- **FR-12**: Every scanner or tool invocation in Sub-layer D (`osv-scanner`,
  `trivy`, `npm audit`, `pip-audit`) MUST be wrapped in a hard timeout,
  default 60 seconds per manifest (per-manifest, not per-build),
  configurable via `.smith/config.json`'s `supply_chain.timeout_seconds`
  (FR-28). A timeout, or a network-unreachable/offline condition, MUST
  result in skip-with-disclosure for that manifest/tool — never a hang,
  and never a build failure.

### Sub-layer L — license inventory

- **FR-13**: Phase 3.7 MUST ship a new, dependency-free license-inventory
  script, separate from any CVE scanner. For the npm ecosystem, it walks
  `node_modules/*/package.json` plus scoped packages under
  `node_modules/@*/*/package.json`, reading each package's `license`
  field.
- **FR-14**: The npm-ecosystem license inventory is gated on the presence
  of a `node_modules/` directory at the manifest's location — a STRICTER
  precondition than Sub-layer D's lockfile requirement (FR-7): a
  `package.json` + lockfile with no installed `node_modules/` still skips
  Sub-layer L's inventory for that manifest (skipped-with-disclosure), even
  when Sub-layer D can still scan that same manifest for CVEs.
- **FR-15**: For the Python ecosystem, the license inventory MUST use
  `importlib.metadata`, invoked through the PROJECT's own
  interpreter/environment — `poetry run python3` when a `poetry.lock` is
  present alongside the manifest — never the system/global Python, so
  installed package metadata actually resolves. A package whose license
  metadata is absent or unparseable is bucketed under an explicit
  `UNKNOWN` license label rather than omitted or treated as an error.
- **FR-16**: Sub-layer L's output shape is: license identifier → { count,
  package list }, aggregated per manifest and then merged across all
  manifests into one repo-wide inventory for the build. `UNKNOWN` is a
  first-class bucket in this output, never swallowed or hidden.

### Findings handling & enforcement

- **FR-17**: Every finding, from either sub-layer, MUST carry exactly one
  severity (Critical/High/Medium/Low), the affected package name and
  version, the source manifest path, the ecosystem, the originating
  sub-layer (D or L), a category label (the CVE identifier for Sub-layer
  D; `license-policy` for a Sub-layer L deny-list hit), and a 1-2 sentence
  rationale.
- **FR-18**: A new `supply_chain.license_policy` config object (FR-28)
  carries `allow` and `deny` string arrays, both EMPTY by default — this
  feature ships with no opinion on which licenses are acceptable. A
  package whose inventoried license matches an entry in `deny` MUST
  produce a Finding at High severity, category `license-policy`, reported
  through the same findings pipeline as Sub-layer D's CVE findings. `allow`
  has no enforcement effect in this version — its entries are not
  additionally checked against anything beyond `deny` in v1; it exists as
  a documented config surface reserved for a future default-deny-unless-
  allowed mode, which this version does not implement.
- **FR-19**: Phase 3.7 MUST NOT auto-fix any finding, from either
  sub-layer, under any configuration, in this version — no dependency
  version bump, no license-triggered edit, no Write/Edit call to the
  working tree for any finding this phase produces. This mirrors Phase
  3.6's no-auto-fix invariant for the same reason: a CVE remediation or a
  license swap is a judgment call this pass does not make unsupervised.
- **FR-20**: Phase 3.7 ships with NO enforcement-tier config and NO
  block/terminate path of any kind, for any finding, at any severity, from
  either sub-layer, in this version. Unlike Phase 3.6's config-driven
  `enforcement_tier`, Phase 3.7 is unconditionally flag-only;
  `.smith/config.json`'s `supply_chain` key (FR-28) carries no
  tier-equivalent field, by design, so a future terminate mode cannot be
  silently implied by this version's schema.

### PR-body reporting

- **FR-21**: Every finding Phase 3.7 produces (all of them survive to
  reporting, since no termination path exists — FR-20) is written to a
  dedicated scratch file, `/tmp/smith-build-supply-chain-findings.txt`,
  following the same scan → `/tmp` file → conditionally-included pattern
  already used by §5.3, §5.3.1, Phase 3.5, and Phase 3.6 — a file distinct
  from those phases' own scratch files. A companion file,
  `/tmp/smith-build-supply-chain-scan-status.txt`, records per-manifest
  which scan path ran and which were skipped-with-disclosure and why.
- **FR-22**: When `/tmp/smith-build-supply-chain-findings.txt` is
  non-empty, the PR body template (§5.4) MUST gain a "Supply-Chain Review"
  section, using the same include-if-non-empty pattern as every preceding
  §5.3/§5.3.1/3.5/3.6 section. When that file is empty — including the
  zero-manifest case (FR-6) and the case where every discovered manifest
  scanned clean with full tool coverage — the section is omitted entirely.
- **FR-23**: Within an included "Supply-Chain Review" section: Critical,
  High, and Medium severity findings are each listed individually
  (severity, package, version, manifest, category, sub-layer, rationale);
  Low-severity findings, plus any finding mapped from `npm audit`'s `info`
  bucket (FR-11), are NOT listed individually — they are folded into a
  single trailing "+ N low-severity notes" line (omitted when N=0),
  mirroring feature 54/55's threshold convention.
- **FR-24**: Whenever the "Supply-Chain Review" section is included, it
  MUST also state, per manifest, which scan path ran (the multi-ecosystem
  scanner name, or the per-manifest fallback tool name) and which
  manifests/tools were skipped and why (absence, ENOLOCK/no-lockfile,
  offline, timeout, node_modules-absent for Sub-layer L) — derived from
  `/tmp/smith-build-supply-chain-scan-status.txt` (FR-21) — mirroring Phase
  3.6's layer-disclosure line so the section never states or implies full
  scanner coverage when a tool was actually skipped. It MUST additionally
  include, verbatim, the line: **"full-project scan, not diff-scoped;
  findings may predate this change"** — since, unlike every other PR-body
  section in this pipeline, this section's findings are not scoped to the
  current branch's diff (FR-3).

### smith-audit wiring

- **FR-25**: `smith-audit`'s existing Dependencies sub-audit
  (`skills/smith-audit/SKILL.md` item 7, today a one-line brief) MUST be
  upgraded to invoke this feature's own scripts — the extended
  detect-scanners.sh (FR-27) plus Sub-layer D's and Sub-layer L's scan/
  inventory scripts — run whole-project, consistent with `smith-audit`'s
  existing on-demand, whole-system model (and with this phase's own
  non-diff-scoped design, FR-3).
- **FR-26**: `smith-audit`'s invocation MUST NOT fork or duplicate this
  logic — it calls the identical scripts `smith-build`'s Phase 3.7 calls,
  with no `smith-audit`-specific parsing or branching duplicated. One
  implementation, two consumers, closing feature 55's NFR-4 intent, which
  explicitly named this future feature as detect-scanners.sh's second
  consumer.

### detect-scanners.sh extension

- **FR-27**: `detect-scanners.sh` (established by feature 55) MUST be
  extended, not replaced or forked: `osv-scanner`, `grype`, `trivy`,
  `pip-audit`, `licensee`, and `syft` are added to its detection loop,
  preserving the exact same output contract already established for
  `gitleaks`/`semgrep`/`bandit` (same output shape, always exit 0).

### Configuration

- **FR-28**: A NEW top-level `supply_chain` key MUST be added to
  `.smith/config.json`: `{ cve_scan: true, license_inventory: true,
  license_policy: { allow: [], deny: [] }, timeout_seconds: 60, excludes:
  [] }` — a sibling to feature 55's `security_review` key, not nested
  under it: `security_review`'s schema is closed per its own FR-24, and
  nesting would falsely imply this pass shares that schema's tier
  semantics, which it does not (FR-20).
- **FR-29**: Config seeding MUST follow the same non-destructive mechanism
  established for `security_review`: `templates/config.default.json`
  gains the `supply_chain` block, and `/smith-update`'s section sequence
  gains a new `5.1d` seed-if-absent step (the same idiom as the existing
  `5.1c` step for `security_review`), alongside `/smith` init's own
  scaffold step for brand-new projects.

## Non-Functional Requirements

- **NFR-1**: The Supply-Chain Review Pass, including every
  skip-with-disclosure path, MUST run without any user interaction of any
  kind — no prompts, confirmations, or pauses — consistent with
  `smith-build`'s "ALL phases run without user interaction" rule.
- **NFR-2**: All shell snippets added or modified in
  `skills/smith-build/SKILL.md` for this feature, the new Sub-layer L
  license-inventory script, and any wrapper scripts introduced, MUST run
  correctly under both `bash` and `zsh`, matching the repo's existing
  shell-content convention; Python-based components use `python3`.
- **NFR-3**: The Supply-Chain Review Pass MUST run at most once per build.
  No sub-layer, and no finding count, introduces a retry, re-scan, or
  re-review loop.
- **NFR-4**: Presence detection for every external, optional tool this
  feature adds (`osv-scanner`, `grype`, `trivy`, `pip-audit`, `licensee`,
  `syft`) MUST reuse the SAME shared helper feature 55 established
  (`detect-scanners.sh`, extended per FR-27) — not a second, duplicated
  presence-detection implementation.
- **NFR-5**: This feature MUST NOT modify Phase 3.5's or Phase 3.6's own
  scripts, `skills/smith-clean-code/SKILL.md`, the three
  `security-guard-*.sh` hooks, or `smith-audit`'s SKILL.md/sub-audit logic
  beyond the explicitly named Dependencies sub-audit item (FR-25) and
  `detect-scanners.sh` (FR-27).
- **NFR-6**: Every scanner/tool invocation in Sub-layer D and every
  filesystem walk in manifest discovery and Sub-layer L MUST be bounded —
  a hard timeout for scanners (FR-12), a bounded depth plus the standard
  excludes for walks (FR-4) — so Phase 3.7 cannot hang or run unbounded
  regardless of repository size or network condition.

## Out of Scope

- **OOS-1 — smith-bugfix inclusion.** `smith-bugfix`'s commit pipeline
  gains no part of this feature. Unlike secrets (feature 55's parity
  extension, where a leaked credential is irreversible the moment it's
  pushed), a CVE in an already-declared dependency is not introduced by a
  bugfix's diff — there is no time-sensitive reason to run a whole-project
  scan inside the lightweight bugfix pipeline.
- **OOS-2 — Diff-scoped CVE attribution.** Attributing a finding
  specifically to changes made on this branch (as opposed to a
  pre-existing dependency) is out of scope for v1 — it would require
  lockfile-diffing complexity. This version's findings are whole-project
  and explicitly disclosed as such (FR-24); diff-scoped attribution is a
  v2 candidate.
- **OOS-3 — Terminate/block semantics for any finding.** No finding, from
  either sub-layer, at any severity, can block, delay, or terminate the
  workflow in this version — flag-only v1, no tier-equivalent config
  exists (FR-20).
- **OOS-4 — SBOM generation.** Neither sub-layer produces a software bill
  of materials in any format.
- **OOS-5 — Modifying Phase 3.5 or Phase 3.6.** Both phases, and their own
  scripts, are unmodified by this feature beyond the explicitly named
  `detect-scanners.sh` extension (FR-27).

## Assumptions

- **A-1**: The pre-feature exploration
  (`.smith/vault/explore/explore-2026-09-13-supply-chain-gate.md`) found no
  blocking conflicts; its 8 findings are design constraints resolved by
  encoding them into this spec, confirmed by this feature's requirements
  checklist.
- **A-2**: This feature reuses feature 55's scanner-presence-detection
  helper and `detect-scanners.sh` contract rather than introducing a
  second implementation (NFR-4); it extends that script rather than
  forking it (FR-27).
- **A-3**: Unlike Phase 3.5/3.6, this phase does not thread `BASE_BRANCH`
  into its scan scope — `WORKTREE_PATH` is still used to locate the
  repository root, but scanning is whole-project (FR-3). This is a
  deliberate divergence from the diff-scoped precedent those two phases
  set, and is disclosed explicitly in the PR body (FR-24) so it is never
  mistaken for diff-scoped coverage.
- **A-4**: `license_policy.allow`'s lack of a v1 enforcement effect (FR-18)
  is a deliberate, documented scope limitation, not an oversight — its
  presence in the schema reserves room for a future default-deny-unless-
  allowed mode without committing to one now.
- **A-5**: `goldcanna-inventory`'s actual dependency layout (2 npm
  manifests + 1 poetry manifest — `pyproject.toml`/`poetry.lock`, not
  `requirements.txt`) and this repository's own zero-manifest state are
  this feature's two primary validation fixtures, covering multi-manifest
  merge behavior and true silent-skip behavior respectively. The
  exploration additionally verified Sub-layer L's approach live against
  `goldcanna-inventory`'s actual `node_modules/` tree (508/508 packages
  resolved a license field) and confirmed `trivy` — while absent on this
  development machine — is `goldcanna-inventory`'s actual CI scanner
  (`.github/workflows/publish.yml` + `.trivyignore`), grounding FR-8/FR-27
  in a real, already-adjacent tool rather than a speculative choice.
- **A-6 — RESOLVED at questions gate (delegation).** The feature
  description named six gate decisions the exploration pass
  evidence-backed with a recommendation each. Per this workflow's
  delegation, the user accepted every recommendation as-is
  (`questions.md`, generated 2026-09-13, status ANSWERED — the gate
  surfaced no reason to reconsider any of the six). No FR above
  contradicts these outcomes; each holds as follows:
  1. **Q1 — Phase placement.** New, dedicated Phase 3.7 for supply-chain/
     license concerns, rather than extending Phase 3.6. **Outcome:** new
     Phase 3.7 (accepted) — Phase 3.6's decision table and terminate rule
     are deliberately secret-specific and closed (feature 55 FR-24); this
     feature instead reuses the 54→55 insertion-point pattern, slotted
     between 3.6's close and Phase 4 (exploration finding 1).
  2. **Q2 — Config home.** A NEW top-level `supply_chain` key in
     `.smith/config.json`, rather than nesting under `security_review`.
     **Outcome:** new top-level key (accepted) — `security_review`'s
     schema is closed per its own FR-24, and nesting would falsely imply
     this pass shares its tier semantics (exploration finding 3).
  3. **Q3 — Enforcement posture.** Flag-only v1, no terminate/block path
     for any finding at any severity. **Outcome:** flag-only (accepted) —
     CVEs are not diff-introduced the way secrets are, so Layer 1's
     unconditional-hard-stop precedent does not transfer here; a
     config-driven block tier is deferred until this pass has field
     mileage (exploration finding 8).
  4. **Q4 — License policy default.** The license inventory ships with a
     config-only allow/deny policy, both EMPTY by default. **Outcome:**
     inventory-only, no default policy (accepted) — every project's
     license tolerance differs, and shipping a default deny list would
     bake an unreviewed legal opinion into the tool (exploration
     finding 6).
  5. **Q5 — smith-bugfix inclusion.** `smith-bugfix`'s commit pipeline does
     NOT gain any part of this feature. **Outcome:** excluded (accepted) —
     unlike secrets (feature 55's own Q5, which added a cheap pre-commit
     scan to `smith-bugfix` because a leaked secret is irreversible once
     pushed), a CVE in an already-declared dependency is not introduced by
     a bugfix's diff (this feature's OOS-1).
  6. **Q6 — smith-audit wiring.** The existing Dependencies sub-audit
     one-liner is upgraded to invoke this feature's own scripts.
     **Outcome:** included (accepted) — this closes feature 55's NFR-4
     intent, which explicitly named this future feature as
     `detect-scanners.sh`'s second consumer: one implementation, two
     consumers, rather than two dependency-scanning code paths drifting
     apart (exploration finding 7).

## Success Criteria

- **SC-1**: On a `goldcanna-inventory`-shaped fixture repository (2 npm
  manifests + 1 poetry manifest), Phase 3.7 produces per-manifest CVE scan
  results merged into a single build-level output, with each finding still
  traceable to its source manifest path.
- **SC-2**: On a manifest-less repository (this repository's current
  state), Phase 3.7 completes with zero manifests found, no error, no
  PR-body "Supply-Chain Review" section, and a vault session-log entry
  recording the zero-manifest outcome (FR-6).
- **SC-3**: When `npm audit --json` is the active scan path for an npm
  manifest, its severity buckets are parsed correctly from
  `metadata.vulnerabilities` — including the `moderate`→Medium and
  `info`→folded-low mappings — regardless of the command's process exit
  code (FR-11).
- **SC-4**: Sub-layer L's license inventory runs with zero newly installed
  dependencies — the npm-ecosystem walk and the Python
  `importlib.metadata` read both use only what a normal `npm install`/
  `poetry install` already produces on disk (FR-13/FR-15).
- **SC-5**: When a scanner call is offline or exceeds its configured
  timeout, Phase 3.7 never hangs and never fails the build — the affected
  manifest/tool is recorded as skipped-with-disclosure and the pass
  completes (FR-12).
- **SC-6**: `smith-audit`'s Dependencies sub-audit, when run, invokes the
  same extended `detect-scanners.sh` and the same Sub-layer D/L scripts
  Phase 3.7 uses, whole-project, with no separate or duplicated scanning
  implementation (FR-25/FR-26).
