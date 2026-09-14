# Data Model: Supply-Chain & License Review Pass for smith-build

This document specifies the SHAPES this feature introduces: the
`supply_chain` config schema, the manifest-discovery record, the
scanner-result normalization contract (Sub-layer D), the license
inventory record + policy-evaluation result (Sub-layer L), the two `/tmp`
handoff files, and the "Supply-Chain Review" PR-body section format. All
are prose/table-level specifications for `plan.md` and the eventual
`skills/smith-build/SKILL.md` prose to encode — no code is prescribed
here, matching `research.md` §8's own finding that both new scripts are
separate, testable Python artifacts, not inline markdown prose.

**Section numbering**: `§1-§7` below are local to THIS document. Do not
conflate with feature 55's own local `§1-§5` in
`.specify/systems/cross-system/features/55-security-review-pass/data-model.md`,
nor with the pre-54 `data-model.md §9`/`§4` citations already present
elsewhere in this repo's SKILL.md files. Any future SKILL.md prose this
feature adds must qualify citations as "this feature's `data-model.md`
§N."

## §1 — `supply_chain` config schema (`.smith/config.json`)

A sibling of `security_review`, never nested under it (FR-28, `research.md`
§9 Q2 — `security_review`'s own schema is closed/tier-bearing and nesting
would falsely imply shared semantics). Ships with NO tier-equivalent field
of any kind, by design (FR-20) — there is no config path that can ever
make a finding from this feature block, delay, or terminate anything.

```jsonc
{
  "supply_chain": {
    "cve_scan": true,              // REQUIRED. Master on/off for Sub-layer D as a whole. true = shipped default.
    "license_inventory": true,     // REQUIRED. Master on/off for Sub-layer L as a whole. true = shipped default.
    "license_policy": {            // REQUIRED sub-object. Both arrays EMPTY by default (FR-18, Q4) — this feature ships with no opinion on which licenses are acceptable.
      "allow": [],                 // Reserved for a future default-deny-unless-allowed mode (A-4). Has NO enforcement effect in this version — not additionally checked against anything beyond `deny` in v1.
      "deny": []                   // A license identifier appearing here, matched against an inventoried package's license, produces a High-severity `license-policy` Finding (FR-18). Case-sensitive string match against the SPDX-style identifier Sub-layer L resolves (§4 below) — no glob/regex matching in v1.
    },
    "timeout_seconds": 60,         // OPTIONAL, default 60 (FR-12/FR-28). Per-manifest, per-tool hard timeout for every Sub-layer D scanner invocation. Enforced via python3 subprocess.run(..., timeout=N) — research.md §7.4's recommended, justified mechanism; NOT a shell `timeout`/`gtimeout` wrapper (confirmed absent on the reference dev machine).
    "excludes": []                 // OPTIONAL additional path globs, layered ON TOP OF the fixed built-in exclude set (vendor/, node_modules/, .venv/, dist/, build/, .smith/ — FR-4, mirroring secret-scan.sh:22's own BUILTIN_EXCLUDES shape exactly) used by BOTH manifest discovery and the license-inventory walk. Never removes a built-in exclusion, only adds more.
  }
}
```

**No `enforcement_tier`-shaped field exists anywhere in this schema** —
unlike `security_review`, there is nothing to configure toward a block/
terminate outcome (§7 below makes this explicit as its own contract).

**File identity**: this key lives in `.smith/config.json` ONLY — the
SAME file `security_review` lives in (not `.smith/security-config.json`,
the guard-hook config). Both keys are read via the identical
file-exists-AND-parses-AND-`isinstance(config, dict)` defensive gate
`secret-scan.sh:71-113` already establishes (`research.md` §2) — an
absent or malformed `.smith/config.json` means every field above falls
back to its stated default, never an error.

**Seeding**: `templates/config.default.json` gains this key positioned
immediately after `security_review`'s closing `}` (its own line 25) and
before `context_budget` (line 26) — `research.md` §4. Non-destructive
merge steps mirror `security_review`'s own exactly, retargeted at
`supply_chain`: an unlettered paragraph in `skills/smith/SKILL.md`
(within `#### 4.1 Scaffold Project Directories`, immediately after the
`security_review` block) and a new `### 5.1d Seed \`supply_chain\` in
\`.smith/config.json\`` in `skills/smith-update/SKILL.md`, immediately
after `### 5.1c` (line 344) and before `### 5.2` (346).

## §2 — Manifest-discovery record shape

One record per manifest discovered by the bounded-depth walk (FR-4),
built during Phase 3.7's first step and consumed by both sub-layers:

```jsonc
{
  "manifest_path": "frontend/package.json",     // repo-relative, forward-slash-separated
  "ecosystem": "npm",                            // "npm" | "poetry" | "pip" | "go" | "cargo"
  "lockfile_path": "frontend/package-lock.json", // repo-relative path to the matching lockfile, or null if none found at this manifest's location
  "lockfile_kind": "npm",                        // npm ecosystem only: "npm" (package-lock.json/npm-shrinkwrap.json — the ONLY format `npm audit`'s FR-9 fallback can read directly, research.md §7.1) | "yarn" | "pnpm" | null. A yarn.lock/pnpm-lock.yaml alone satisfies FR-4's broader "has a lockfile" definition but NOT FR-7's npm-audit-fallback precondition — this field is what lets Sub-layer D distinguish the two skip reasons (research.md §7.1's own surfaced edge case).
  "node_modules_present": false,                 // npm ecosystem only: whether node_modules/ exists at this manifest's directory (FR-14's STRICTER Sub-layer L precondition, independent of lockfile_path)
  "venv_path": null                              // python ecosystems only: resolved interpreter root for Sub-layer D's pip-audit / Sub-layer L's importlib.metadata read — poetry-managed .venv path when pyproject.toml+poetry.lock are both present and `poetry env info -p`-equivalent resolution succeeds (FR-15); null otherwise (system python3 is NEVER used per FR-15 — a null venv_path means this manifest's license inventory is skipped-with-disclosure, not silently run against the wrong interpreter)
}
```

Discovery walks the repository (bounded depth, `research.md` §7's own
depth-choice note — recommend 6 levels from repo root, generous headroom
over `goldcanna-inventory`'s own 1-level nesting) excluding the built-in +
config `excludes` families (§1), recognizing: `package.json` (+ optional
matching lockfile), `pyproject.toml` (+ optional `poetry.lock`),
`requirements.txt`, `go.mod`, `Cargo.toml` — one record per manifest file
found, `lockfile_path`/`node_modules_present`/`venv_path` populated by a
direct filesystem check alongside the manifest, not deferred to
scan-time. FR-5 requires each manifest scanned independently with results
merged — this record list IS the merge key: every downstream finding
(§3/§4) carries its originating `manifest_path` back to this record.

## §3 — Scanner result normalization contract (Sub-layer D)

Every CVE finding, whether sourced from a multi-ecosystem scanner
(`osv-scanner`/`trivy`, FR-8) or a per-manifest fallback tool (`npm
audit`/`pip-audit`, FR-9), is normalized into this SAME shape before
merging (FR-17):

```jsonc
{
  "sub_layer": "D",
  "source_scanner": "npm-audit",       // "osv-scanner" | "trivy" | "npm-audit" | "pip-audit" — the tool that actually produced this finding, distinct from `ecosystem` below
  "ecosystem": "npm",                  // "npm" | "poetry" | "pip" | "go" | "cargo"
  "manifest_path": "frontend/package.json",   // §2's own manifest_path — traceability to source (FR-5's explicit requirement)
  "package": "lodash",
  "version": "4.17.15",
  "advisory_id": "GHSA-p6mc-m468-83gw",  // the CVE/GHSA/advisory identifier this feature's own category label (FR-17) reuses as `category`
  "severity": "High",                   // Critical | High | Medium | Low — post-mapping (see below)
  "fix_available": "4.17.21",           // resolved fixed version string, or null if the scanner didn't report one
  "rationale": "1-2 sentence advisory summary"
}
```

**Severity mapping is scanner-specific, applied at normalization time**:

- `osv-scanner`/`trivy`/`grype` (when used) report their own native
  severity already close to this scale; map directly with no folding.
- `npm audit --json`'s `metadata.vulnerabilities` buckets (FR-11,
  empirically verified live against `goldcanna-inventory/frontend` —
  `research.md` §7.1): `critical`→Critical, `high`→High,
  `moderate`→**Medium**, `low`→Low, `info`→folded into the SAME
  low-severity bucket as `low` (never listed as its own severity tier —
  FR-11/FR-23).
- `pip-audit`'s own JSON output carries advisory records without a
  first-class severity field in every case; when absent, default to
  `Medium` (a defensible middle default — never silently dropped, never
  auto-escalated to Critical/High without an explicit upstream signal)
  and note the default was applied in the finding's `rationale`.

**`category` for Sub-layer D findings (FR-17) is the `advisory_id`
itself** (e.g. `GHSA-p6mc-m468-83gw` or a bare `CVE-2023-XXXXX`) — unlike
Sub-layer L, which uses the fixed literal `license-policy` (§4 below).

## §4 — License inventory record + policy evaluation result (Sub-layer L)

**Per-manifest inventory record**, one per discovered license identifier
within a single manifest's dependency tree:

```jsonc
{
  "license_id": "MIT",                 // resolved identifier, or the literal "UNKNOWN" bucket (FR-15/FR-16 — never omitted, never silently dropped)
  "manifest_path": "frontend/package.json",
  "ecosystem": "npm",
  "packages": [
    {"name": "lodash", "version": "4.17.21"},
    {"name": "chalk", "version": "5.3.0"}
  ],
  "count": 2
}
```

Merged repo-wide across every manifest into one build-level inventory
(FR-16: "aggregated per manifest and then merged across all manifests
into one repo-wide inventory for the build") — the merge keys on
`license_id`, unioning each license's `packages` list across manifests
while each entry retains its own `manifest_path`/`ecosystem` for
traceability (a package can appear under the same `license_id` from two
different manifests; both are kept, never deduplicated away, since they
are genuinely different install locations).

**npm-ecosystem resolution (FR-13), with a fallback chain this research
pass found necessary, not just the naive read**: walk
`node_modules/*/package.json` + `node_modules/@*/*/package.json`
(scoped packages), reading each package's `license` field. **Live-verified
against `goldcanna-inventory/frontend/node_modules`** (508 total packages,
this session): 507/508 resolve directly via the modern single `license`
string field; the 1 remaining (`xmlhttprequest-ssl`) carries NO `license`
field at all but DOES carry the legacy, npm-deprecated `licenses: [{type,
url}]` array shape (`{"type": "MIT", "url": "..."}`) — a real, currently-
shipping package in this exact validation fixture. **The npm walk MUST
fall back to `licenses[0].type` (join multiple entries with `" OR "` if
the array has more than one) when `license` is absent, before bucketing
`UNKNOWN`** — without this fallback, this feature's own primary
validation fixture would report 507/508 resolved rather than the
508/508 the exploration's A-5 claims, a discrepancy this research pass
caught and resolves as a concrete implementation requirement, not a
documentation error to silently correct. `menu-generator/node_modules`
(156 packages) resolved 156/156 via the direct field alone — the fallback
is a real but narrow-incidence case, not a dominant path.

**Python-ecosystem resolution (FR-15), also with a fallback chain this
research pass found necessary**: `importlib.metadata`, invoked via
`poetry run python3` when `poetry.lock` is present (never system python3
— FR-15). **Live-verified against `goldcanna-inventory/backend`'s actual
poetry environment** (95 distributions, this session): reading ONLY the
legacy `metadata.get("License")` field leaves **26/95 (27%) unresolved**
— including well-known packages like `click` and `pydantic` — NOT because
they lack license information, but because modern build backends
(hatchling and others, implementing PEP 639) publish it via a NEWER
`License-Expression` metadata field instead (`click`'s own metadata:
`License-Expression: 'BSD-3-Clause'`, `License` field literally absent).
**The resolution order MUST be: `License-Expression` (if present) →
`License` (if present and not empty/literal `"UNKNOWN"`) → the last
matching `Classifier` line starting `License ::` → else bucket
`UNKNOWN`.** With this 3-tier fallback applied, this research pass
confirmed **0/95 true UNKNOWN** in `goldcanna-inventory`'s real
environment — a naive single-field read would have wrongly bucketed over
a quarter of this fixture's own dependencies as UNKNOWN. `UNKNOWN` remains
a fully legitimate, first-class bucket (FR-15's own requirement) for
packages that genuinely expose none of the three fields — this fallback
chain changes what counts as "genuinely unresolvable," it does not
eliminate the bucket itself.

**Policy evaluation result** — one Finding per inventoried package whose
`license_id` matches an entry in `supply_chain.license_policy.deny`
(FR-18, case-sensitive string match against the resolved identifier):

```jsonc
{
  "sub_layer": "L",
  "severity": "High",              // FIXED at High for every deny-list hit — FR-18 does not vary this by license
  "category": "license-policy",    // FIXED literal (FR-17) — distinct from Sub-layer D's advisory-id category
  "package": "some-gpl-package",
  "version": "2.1.0",
  "manifest_path": "backend/pyproject.toml",
  "ecosystem": "poetry",
  "rationale": "License 'GPL-3.0' matches a configured deny-list entry (supply_chain.license_policy.deny)."
}
```

`allow` is read but produces NO findings of any kind in this version
(A-4) — its entries exist purely as documented schema surface for a
future default-deny-unless-allowed mode.

## §5 — `/tmp` handoff files (exact names per FR-21)

Two files, both distinct from Phase 3.6's own `/tmp/smith-build-security-*`
files (a different phase, a different findings shape):

**`/tmp/smith-build-supply-chain-findings.txt`** — populated with every
Finding from BOTH sub-layers (§3's CVE findings normalized, §4's
license-policy findings) — since no terminate path exists (FR-20), this
is the ONLY findings file this phase ever produces; there is no
hard-stop-artifact counterpart the way Phase 3.6 has one (§7 below).
Line format, mirroring `/tmp/smith-build-security-findings.txt`'s own
flat-bullet style extended with a `sub-layer` field (D/L) in place of
Phase 3.6's `layer` (1/2/3):

```
- **[<Severity>]** `<package>@<version>` (`<manifest_path>`) — <rationale> (category: <category>, sub-layer: <D|L>)
```

Example:
```
- **[High]** `lodash@4.17.15` (`frontend/package.json`) — Prototype pollution in zipObjectDeep (category: GHSA-p6mc-m468-83gw, sub-layer: D)
- **[High]** `some-gpl-package@2.1.0` (`backend/pyproject.toml`) — License 'GPL-3.0' matches a configured deny-list entry (category: license-policy, sub-layer: L)
+ 4 low-severity notes
```

Severity threshold (FR-23, mirroring feature 54/55's own convention):
Critical/High/Medium listed individually; Low findings, PLUS any finding
mapped from `npm audit`'s `info` bucket (FR-11), fold into exactly one
trailing `+ N low-severity notes` line, omitted when N=0.

**Empty-file semantics (FR-6/FR-22)**: zero manifests repo-wide, or every
discovered manifest scanning clean with full coverage, both leave this
file empty/absent — either way FR-22's PR template omits the "Supply-Chain
Review" section entirely.

**`/tmp/smith-build-supply-chain-scan-status.txt`** — always written
(never conditional on findings existing), one line per manifest × scan
attempt, recording exactly what ran vs. was skipped and why (FR-21/FR-24):

```
<manifest_path>: cve_scan=<ran:<tool-name>|skipped:<reason>>
<manifest_path>: license_inventory=<ran|skipped:<reason>>
```

Skip reasons, exact tokens (so the PR-body renderer and any future
consumer can match on them deterministically): `absent` (no applicable
scanner/tool found — FR-10), `enolock` (FR-7's no-matching-lockfile case),
`enolock_wrong_format` (`research.md` §7.1's own surfaced edge case — a
lockfile exists but isn't `npm audit`-readable), `no_node_modules`
(FR-14's Sub-layer L precondition), `no_venv` (FR-15's poetry-env
resolution failed), `timeout` (FR-12), `offline` (FR-12), `disabled`
(`supply_chain.cve_scan`/`license_inventory` is `false`). Example:

```
frontend/package.json: cve_scan=ran:npm-audit
frontend/package.json: license_inventory=ran
menu-generator/package.json: cve_scan=skipped:enolock
menu-generator/package.json: license_inventory=skipped:no_node_modules
backend/pyproject.toml: cve_scan=skipped:absent
backend/pyproject.toml: license_inventory=ran
```

When zero manifests are found repo-wide (FR-6), this file is still
written, containing a single sentinel line: `0 manifests found` — the
exact wording FR-6 itself specifies for the vault session-log entry,
reused verbatim here so the log entry and this scratch file never drift
into two different phrasings of the same outcome.

## §6 — PR-body "Supply-Chain Review" section format (FR-22/FR-23/FR-24)

Included in `skills/smith-build/SKILL.md` §5.4's template, positioned
after the existing "Security Review" block (currently ending line 776)
and before "## Release notes" (currently line 778) — the newest section
appended after every existing one, matching how "Security Review" itself
was appended after "Clean Code Review" rather than reordering prior
sections.

```
## Supply-Chain Review
<include this section only when /tmp/smith-build-supply-chain-findings.txt is non-empty>

**full-project scan, not diff-scoped; findings may predate this change**

<per-manifest scan-path disclosure derived from /tmp/smith-build-supply-chain-scan-status.txt, e.g.:>
Scanned: `frontend/package.json` (npm-audit, license inventory), `backend/pyproject.toml` (license inventory only — CVE scan absent). Skipped: `menu-generator/package.json` (no lockfile; node_modules absent).

<contents of /tmp/smith-build-supply-chain-findings.txt verbatim, e.g.:>
- **[High]** `lodash@4.17.15` (`frontend/package.json`) — Prototype pollution in zipObjectDeep (category: GHSA-p6mc-m468-83gw, sub-layer: D)
- **[High]** `some-gpl-package@2.1.0` (`backend/pyproject.toml`) — License 'GPL-3.0' matches a configured deny-list entry (category: license-policy, sub-layer: L)
+ 4 low-severity notes

This is a FLAG, never a blocker — no finding from either sub-layer, at any severity, blocks or delays this PR (FR-19/FR-20).
```

The verbatim disclosure line — **"full-project scan, not diff-scoped;
findings may predate this change"** — is FR-24's own literal requirement,
reused exactly as spec'd, distinguishing this section from EVERY other
PR-body section in this pipeline (§5.3/§5.3.1/Clean Code Review/Security
Review are all diff-scoped; this is the only whole-project one, FR-3/A-3).

## §7 — NO terminate path (explicit contract, contrasted with Phase 3.6)

**Unlike `data-model.md` §5 in feature 55 (which specifies a tier ×
severity × layer decision table with a real terminate branch), THIS
feature has no decision table and no terminate branch of any kind.**
Stated as an explicit contract, not merely an absence, because Phase 3.6
sits directly upstream in the same pipeline and a reader who has just
internalized ITS terminate semantics could otherwise wrongly assume
Phase 3.7 inherits or extends them:

- No `supply_chain` field configures a tier — §1's schema has no
  `enforcement_tier`-shaped key by design (FR-20).
- No severity, from either sub-layer — not even a Critical CVE with a
  known exploit, not even a deny-listed license on a package the
  project ships to production — can block, delay, or terminate the
  workflow (FR-19/FR-20/OOS-3). Phase 4 ALWAYS begins after Phase 3.7
  completes, unconditionally.
- There is no hard-stop artifact, no vault session-log "Hard-stop:" entry
  equivalent, no worktree-preservation-for-a-terminated-run branch, no
  Recovery Mode interaction — every one of Phase 3.6's terminate-semantics
  contract items (feature 55 `data-model.md` §5, items 1-6) has NO
  counterpart here, because the triggering condition ("any finding
  resolves to terminate") can never occur.
- Phase 3.7 makes ZERO Write/Edit calls to the working tree for any
  finding, from either sub-layer, under any configuration (FR-19) —
  identical to Phase 3.6's own no-auto-fix invariant, but for a
  categorically different reason: Phase 3.6 doesn't auto-fix because a
  security remediation is a judgment call; Phase 3.7 doesn't auto-fix
  because bumping a dependency version or swapping a license is an
  even larger judgment call this pass is not positioned to make
  unsupervised, and because FR-19 forbids it outright regardless of
  confidence.

This is a permanent v1 design boundary (OOS-3), not a temporary gap —
`research.md` §9 Q3 documents the options/evidence for why flag-only was
recommended, without deciding it there; this section is the concrete
contract that recommendation resolves to.
