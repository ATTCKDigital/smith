---
feature: 56-supply-chain-gate
primary_system: cross-system
branch: 56-supply-chain-gate
status: planned
---

# Implementation Plan: Supply-Chain & License Review Pass for smith-build

## Technical Context

- **Repo**: Smith skills distribution (this repo). No application
  runtime — deliverables are two new dependency-free Python orchestrators
  plus thin `.sh` entry-point shims, their companion tests, markdown skill
  prose (`skills/smith-build/SKILL.md`, `skills/smith-audit/SKILL.md`,
  config-seeding steps in `skills/smith/SKILL.md` and
  `skills/smith-update/SKILL.md`), one extended script
  (`scripts/security/detect-scanners.sh`), one extended installer stanza
  (`scripts/install.sh`), one new config key
  (`templates/config.default.json`), a new `docs/security-model.md`
  section, and a `CHANGELOG.md` entry.
- **Feature 55 (`55-security-review-pass`) is already shipped and merged**
  in this worktree — Phase 3.6, its PR-body section, its scripts
  (`secret-scan.sh`/`secret_scan.py`/`detect-scanners.sh`), its tests, and
  its config key all exist exactly as described. This plan reuses that
  feature's real, on-disk conventions throughout, not a projected design.
- **No `constitution.md` exists in this repo** — matching features 53/54/55's
  own plan.md files' identical observation.
- **Primary references**: `research.md` (all resolved anchors, cited
  file:line, plus live empirical verification against `goldcanna-inventory`)
  and `data-model.md` (config schema, manifest-discovery record, scanner
  normalization contract, license-inventory record, `/tmp` handoff files,
  PR-body section format, explicit no-terminate contract) in this same
  feature folder.
- **Endpoint (A-6) — RESOLVED**: the questions gate closed 2026-09-13
  (`questions.md`, status ANSWERED) with all six named gate decisions
  accepted exactly as recommended, and spec.md's own Assumptions
  (A-6) now record each as an outcome, not a recommendation. This plan's
  content was already written as concrete and unconditional, using each
  recommendation as the working default (mirroring how feature 55's own
  `plan.md` looked once ITS gate was answered) — the gate's closure
  confirms that default with no overrides, so nothing below changes as a
  result. `research.md` §9 still preserves the original options+evidence
  framing for audit-trail purposes only; it is no longer a live decision
  point.

## Constitution Gates

**N/A — no `constitution.md` or `.specify/memory/constitution.md` exists in
this repo, so there are no constitution-derived gates to check.** Clean-
architecture and file-size discipline are enforced via this plan's own
File Size Policy section instead, the same substitution features 53, 54,
and 55 already used.

## Architecture Summary

One new phase in `skills/smith-build/SKILL.md` (`## Phase 3.7: Supply-Chain
Review Pass`, inserted at the currently-blank line 425, between Phase
3.6's closing content and the `## Phase 4:` heading — `research.md` §1),
plus a new "Supply-Chain Review" PR-body block in the same file's §5.4
(after the existing "Security Review" block, before "## Release notes" —
`data-model.md` §6), plus two new Python orchestrators under
`scripts/security/` with thin `.sh` pass-through entry shims and
companion tests, plus an extended `scripts/security/detect-scanners.sh`,
plus an extended `scripts/install.sh` security-copy stanza, plus a new
`supply_chain` key in `templates/config.default.json` with non-destructive
seeding steps in `skills/smith/SKILL.md` and `skills/smith-update/SKILL.md`,
plus an upgraded `skills/smith-audit/SKILL.md` item 7, plus a new
`docs/security-model.md` section, plus a `CHANGELOG.md` entry.

Phase 3.7's internal shape (spec FR-1..FR-29, `data-model.md` §1-§7):

1. **Manifest discovery** — a bounded-depth (6 levels from repo root)
   walk of the repository, excluding `vendor/`, `node_modules/`, `.venv/`,
   `dist/`, `build/`, `.smith/` plus any `supply_chain.excludes` globs
   (the SAME family `secret-scan.sh:22`'s `BUILTIN_EXCLUDES` already
   uses), producing one `data-model.md` §2 record per discovered
   manifest. Zero manifests found → both sub-layers no-op; the vault
   session log records "0 manifests found" (FR-6) and Phase 4 begins
   immediately — no PR-body section, no scan-status file content beyond
   the sentinel line (`data-model.md` §5).
2. **Sub-layer D — presence-detect, then scan.** Invoke the extended
   `detect-scanners.sh` once (reusing Phase 3.6's own candidate-path
   resolution idiom — `research.md` §1 item 2). If `osv-scanner` or
   `trivy` is present, run the FIRST one found (`osv-scanner` preferred)
   ONCE against the whole repo, covering every manifest in one pass
   (FR-8). Otherwise, per manifest: `npm audit --json --package-lock-only`
   for each npm manifest with an `npm`-readable lockfile
   (`lockfile_kind == "npm"` — `data-model.md` §2's own surfaced
   distinction), `pip-audit -f json` (via `poetry run python3 -m pip_audit`
   when a poetry env resolves, else the manifest's own resolvable
   interpreter) for each Python manifest when `pip-audit` is present
   (FR-9). Every invocation runs through `python3 subprocess.run(...,
   timeout=supply_chain.timeout_seconds)` (`research.md` §7.4's decided,
   justified mechanism — NOT a shell `timeout`/`gtimeout` wrapper, both
   confirmed absent on the reference dev machine) — a timeout or a caught
   network-error exception resolves to skip-with-disclosure for that
   manifest/tool (FR-12), never a hang, never a build failure. Every
   result normalizes into `data-model.md` §3's shape, including the
   `moderate`→Medium / `info`→folded-low mapping for `npm audit`
   specifically (empirically re-verified this session against
   `goldcanna-inventory/frontend` — `research.md` §7.1), and the exit code
   of any tool is NEVER used to decide pass/fail (FR-11) — only parsed
   JSON content is.
3. **Sub-layer L — dependency-free license inventory.** For each npm
   manifest with `node_modules_present: true` (FR-14's STRICTER
   precondition than Sub-layer D's lockfile check — independent of
   whether Sub-layer D could scan the same manifest): walk
   `node_modules/*/package.json` + `node_modules/@*/*/package.json`,
   reading `license`, falling back to `licenses[0].type` when `license`
   is absent (the real, live-verified `xmlhttprequest-ssl` case —
   `data-model.md` §4). For each Python manifest with a resolved
   `venv_path` (poetry-managed, via `poetry run python3`, never system
   python3 — FR-15): `importlib.metadata`, resolving each distribution's
   license via `License-Expression` → `License` → the last `License ::`
   `Classifier` → else `UNKNOWN` (the live-verified 3-tier fallback this
   research pass found necessary — without it, 26/95 real packages in
   `goldcanna-inventory`'s own poetry env would wrongly bucket UNKNOWN).
   Merge into one repo-wide inventory (`data-model.md` §4), then evaluate
   every entry's `license_id` against `supply_chain.license_policy.deny`
   — a match produces a High-severity `license-policy` Finding (FR-18);
   `allow` is read but produces no findings in this version (A-4).
4. **Merge + write, never decide, never terminate.** Every Finding from
   both sub-layers (there is no filtering step — FR-19/FR-20/OOS-3: no
   finding is ever withheld from the flag-only output for enforcement
   reasons) is written to `/tmp/smith-build-supply-chain-findings.txt`
   (`data-model.md` §5, Critical/High/Medium individual, Low+`info`
   folded). The scan-status file
   (`/tmp/smith-build-supply-chain-scan-status.txt`) is always written,
   independent of whether any finding exists. Phase 4 ALWAYS begins next
   — there is no decision table to evaluate and no branch where it does
   not (`data-model.md` §7's explicit no-terminate contract).
5. **No auto-fix, ever** (FR-19) — zero Write/Edit calls to the working
   tree, for any finding, from either sub-layer, under any configuration.

## Reuse-before-create (exact components reused, not reinvented)

- **`detect-scanners.sh`'s extension point** (`scripts/security/detect-scanners.sh:20`,
  `research.md` §2) — the ENTIRE change to this file is appending six
  tool names to one `for tool in ...` line
  (`gitleaks semgrep bandit` → `gitleaks semgrep bandit osv-scanner grype
  trivy pip-audit licensee syft`); zero other lines change (FR-27, NFR-4).
- **`scripts/install.sh`'s security-copy stanza** (`scripts/install.sh:220-231`,
  `research.md` §3) — a REAL, concrete extension point: this stanza names
  each file with its own `cp` line, it does NOT glob the directory, so
  this feature's new files (§"file-by-file" below) each need an explicit
  new `cp` line added, following the exact `cp "$REPO_ROOT/scripts/security/<file>"
  "$SMITH_HOME/scripts/security/<file>" 2>/dev/null || true` shape, plus a
  one-line provenance comment naming `56-supply-chain-gate` (mirroring the
  existing `221-224` comment's own "which feature, why unconditional"
  shape). Without this, `/smith-update` would silently keep serving the
  OLD script set to every already-installed project.
- **The `§5.1b`/`§5.1c` → `§5.1d` non-destructive config-seeding idiom**
  (`skills/smith/SKILL.md:300-331`, `skills/smith-update/SKILL.md:307-344`,
  `research.md` §4) — the exact python3 read-modify-write heredoc
  (load-if-exists-else-`None`, merge only if the top-level key is
  entirely absent, preserve every other key, re-dump with `indent=2` +
  trailing newline), retargeted from `security_review` to `supply_chain`.
- **Phase 3.6's insertion-point pattern** (`skills/smith-build/SKILL.md:328-424`,
  `research.md` §1) — insert at the currently-blank line 425, zero
  renumbering, same candidate-path-resolution idiom for locating each new
  script (installed-path-preferred, repo-dev fallback).
- **`tests/security/test_detect_scanners.sh` + `test_secret_scan.sh`'s
  harness shape** (`research.md` §6) — `make_path_with`/`run_case`/
  `PASS`/`FAIL`/summary-line/exit-status for the detect-scanners
  extension's new cases; `make_repo`/`scan`/`scan_exit`/`assert_*` plus
  the self-detected-interpreter dual-shell idiom for the two new
  orchestrators' tests — no new harness idiom needs inventing for either.
- **`scripts/smith-index/run.sh`'s minimal pass-through wrapper shape**
  (`research.md` §8, decided over `secret-scan.sh`'s heavier bash-logic
  wrapper) — resolve-own-directory + verify-python3-and-engine-exist +
  `exec python3 "$ENGINE" "$@"`, full flag parsing left entirely to each
  `.py` file's own `argparse`, since neither orchestrator needs bash-side
  git-diff-scope resolution the way `secret-scan.sh` does (FR-3: whole-repo,
  not diff-scoped).
- **`python3 subprocess.run(..., timeout=N)`** (`research.md` §7.4, decided
  and justified) — the timeout mechanism for every Sub-layer D scanner
  invocation, chosen over a shell `timeout`/`gtimeout` wrapper because
  BOTH are confirmed absent on the reference dev machine and python3 is
  already a hard dependency of this feature's own orchestrator.
- **`skills/smith-audit/SKILL.md` items 6/10's "upgrade a one-line bullet
  into a fuller description naming the concrete mechanism" style**
  (`research.md` §5) — reused verbatim for item 7's own upgrade (FR-25/26).

## File Size Policy

Every new file targets the 300-line soft ceiling this repo's prior
features already apply absent a hard constitution gate:

- `scripts/security/dependency-scan.py` — the Sub-layer D orchestrator:
  manifest walk (delegating to a shared discovery helper — see next bullet),
  scanner-hierarchy selection, per-tool invocation + timeout wrapper,
  JSON normalization (`data-model.md` §3). Target ≤280 lines; if the
  scanner-hierarchy/normalization logic alone would exceed this once all
  four tool-specific parsers (`osv-scanner`/`trivy`/`npm audit`/`pip-audit`)
  are written, split per-tool parsing into `scripts/security/_scan_parsers.py`
  rather than growing one file monolithically (mirrors feature 55's own
  `secret_scan.py`-vs-`secret_patterns.py` splitting contingency).
- `scripts/security/license-inventory.py` — the Sub-layer L orchestrator:
  npm walk (with the `licenses[]` fallback), Python `importlib.metadata`
  walk (with the `License-Expression`/`Classifier` fallback chain),
  merge, deny-list policy evaluation (`data-model.md` §4). Target ≤220
  lines.
- **A small shared manifest-discovery module**,
  `scripts/security/_manifest_discovery.py` (`data-model.md` §2's record
  shape) — used by BOTH orchestrators (dependency-scan.py needs it to
  know what to scan; license-inventory.py needs the SAME manifest list so
  the two sub-layers never disagree about what a "manifest" is), and
  reusable by `smith-audit`'s own invocation (FR-26: one implementation,
  not two). Target ≤120 lines. This is a genuine THIRD new Python file
  beyond the two named in the task description — flagged explicitly here
  (not one of the six gate items; a plan-level file-count refinement,
  same category as feature 55's own `secret_patterns.py` contingency)
  because FR-5's "each manifest scanned independently, results merged"
  and FR-14's "node_modules presence is a stricter precondition than
  lockfile" both require the SAME discovery pass to feed both sub-layers
  identically — duplicating manifest-walk logic inside each orchestrator
  would risk the two sub-layers silently disagreeing about which
  manifests exist, which this shared module forecloses by construction.
- `scripts/security/dependency-scan.sh` / `scripts/security/license-inventory.sh`
  — minimal pass-through shims (`research.md` §8, `scripts/smith-index/run.sh`
  style) — target ≤20 lines each.
- `scripts/security/detect-scanners.sh` — stays at 28 lines (one line
  changed: the tool-name list).
- `skills/smith-build/SKILL.md`'s new Phase 3.7 section — reference
  `data-model.md`'s contracts (§1-§7) rather than restating field-by-field
  detail, matching Phase 3.6's own ~95-line precedent; target 60-90 lines
  of new prose given this phase has NO terminate branch to describe
  (structurally simpler than Phase 3.6 despite covering two sub-layers),
  plus a ~15-line PR-body template addition.

## Exact file-by-file change list

### NEW

| File | Purpose |
|---|---|
| `scripts/security/_manifest_discovery.py` | Shared bounded-depth manifest walk (`data-model.md` §2's record shape), used by both orchestrators AND by `smith-audit`'s own invocation (FR-26) — the single source of truth for "what counts as a manifest," so the two sub-layers and `smith-audit` never diverge. |
| `scripts/security/dependency-scan.py` | Sub-layer D orchestrator: calls `_manifest_discovery`, resolves the scanner hierarchy (`osv-scanner`/`trivy` preferred whole-repo pass, else per-manifest `npm audit`/`pip-audit` fallback — FR-8/FR-9; `grype` is presence-detected by `detect-scanners.sh` and disclosed but is NEVER invoked by this orchestrator's own hierarchy logic in v1 — FR-8's tool list is read as exhaustive, not illustrative), wraps every invocation in `subprocess.run(..., timeout=supply_chain.timeout_seconds)`, normalizes every result into `data-model.md` §3's shape (including the `enolock` vs. `enolock_wrong_format` skip-reason distinction for a yarn.lock/pnpm-lock.yaml-only npm manifest — `data-model.md` §5, `lockfile_kind`), emits `data-model.md` §5's two `/tmp` files' CVE-half content on stdout for the caller to redirect. |
| `scripts/security/dependency-scan.sh` | Minimal pass-through shim (`run.sh` style) — resolve own directory, verify python3 + the engine exist, `exec python3 dependency-scan.py "$@"`. |
| `scripts/security/license-inventory.py` | Sub-layer L orchestrator: calls `_manifest_discovery`, npm walk (`license` → `licenses[]` fallback), Python `importlib.metadata` walk via the manifest's own resolved `venv_path` (`License-Expression` → `License` → `Classifier` → `UNKNOWN` fallback), merges into one repo-wide inventory, evaluates `supply_chain.license_policy.deny`, emits `data-model.md` §4's records + policy findings. |
| `scripts/security/license-inventory.sh` | Minimal pass-through shim, identical shape to `dependency-scan.sh`. |
| `tests/security/test_dependency_scan.sh` | Companion test, `test_secret_scan.sh`-style harness (`make_repo`, self-detected dual-shell interpreter, `assert_*` helpers). Stubs every external scanner via a scratch `$PATH` (a fake `npm` shim printing FIXED, planted `--json` output for the `audit` subcommand — NEVER a live network call in tests, per the task's explicit "no live network in tests" requirement; a fake `osv-scanner`/`trivy`/`pip-audit` shim for their own presence/absence branches). Fixture manifests include a `goldcanna-inventory`-shaped multi-manifest layout (2 npm dirs + 1 poetry dir, planted under the test's own `mktemp -d` repo, mirroring the REAL layout this research pass confirmed: `frontend/`, `menu-generator/`, `backend/`). Cases: multi-manifest merge (FR-5), ENOLOCK skip (FR-7) alongside a working sibling manifest, ENOLOCK-wrong-format skip (`research.md` §7.1's yarn.lock-only case), `npm audit` severity-bucket mapping via the stub (`moderate`→Medium, `info`→folded-low, exit-code-1-with-findings never treated as failure — FR-11), timeout simulation (a stub that sleeps past `timeout_seconds`, asserting skip-with-disclosure not a hang — FR-12), offline simulation (a stub exiting non-zero with a connection-error-shaped stderr), zero-manifest silent-skip (FR-6), and osv-scanner/trivy-preferred-over-fallback branch selection (FR-8) via presence-stubbed scanners. |
| `tests/security/test_license_inventory.sh` | Companion test, same harness style. Fixture `node_modules/` trees include a planted package using the LEGACY `licenses: [{type, url}]` array with no `license` field (the real `xmlhttprequest-ssl` shape this research pass found) to assert the fallback fires; a Python fixture environment (a stub `importlib.metadata`-readable package set, or a real throwaway `venv`) includes a planted distribution exposing ONLY `License-Expression` (the real `click`-shaped case) to assert THAT fallback fires; a genuinely license-less planted package to assert `UNKNOWN` bucketing still occurs when all three fields are truly absent; `node_modules`-absent-but-lockfile-present skip (FR-14, distinct from Sub-layer D's own lockfile-only precondition); deny-list match producing a High `license-policy` Finding (FR-18); `allow`-list producing zero findings either way (A-4). |

### MODIFIED

| File | Change |
|---|---|
| `scripts/security/detect-scanners.sh` | One-line change: `for tool in gitleaks semgrep bandit; do` → `for tool in gitleaks semgrep bandit osv-scanner grype trivy pip-audit licensee syft; do` (FR-27). Nothing else in the file changes — same output contract, same unconditional `exit 0`. |
| `scripts/install.sh` | Extend the security-copy stanza (220-231) with new `cp` lines for `_manifest_discovery.py`, `dependency-scan.py`, `dependency-scan.sh`, `license-inventory.py`, `license-inventory.sh`, plus extending the trailing `chmod +x "..."*.sh` glob's coverage automatically (it already globs `*.sh`, so the two new shims need no extra chmod line — only the `.py` files' own `cp` lines are new). A one-line provenance comment naming `56-supply-chain-gate` follows the existing `221-224` comment's shape (`research.md` §3's own concrete finding — this stanza does NOT glob its source directory). |
| `skills/smith-build/SKILL.md` | **(1)** New `## Phase 3.7: Supply-Chain Review Pass` inserted at line 425 (between Phase 3.6's close at 424 and `## Phase 4:` at 426) — Architecture Summary's 5-step shape above, explicitly stating the `WORKTREE_PATH`-not-`BASE_BRANCH` divergence (FR-3/A-3) and the explicit no-terminate-path contrast with Phase 3.6 (`data-model.md` §7) up front, so a reader moving top-to-bottom isn't left assuming either property by default. **(2)** §5.4 PR-body template gains a new "Supply-Chain Review" conditional section (`data-model.md` §6), positioned after the existing "Security Review" section and before "## Release notes" — same append-after-the-newest-existing-section convention every prior feature used. **(3)** Key Rules (currently 969-980): NO new clause needed — unlike Phase 3.6 (which added a hard-stop disambiguation because a terminate path exists), Phase 3.7 introduces no new autonomy/interaction behavior beyond what "ALL phases run without user interaction" (970) already covers, since this phase can never pause, block, or terminate. |
| `templates/config.default.json` | New top-level `supply_chain` key (`data-model.md` §1) inserted after `security_review`'s closing `}` (line 25) and before `context_budget` (line 26). |
| `skills/smith/SKILL.md` | New unlettered paragraph + python3 heredoc, mirroring the existing `security_review` seed block (300-331) exactly, retargeted at `supply_chain`, placed immediately after that block's closing `fi` (331) and before "Copy from `~/.claude/skills/smith/`:" (333). |
| `skills/smith-update/SKILL.md` | New `### 5.1d Seed \`supply_chain\` in \`.smith/config.json\`` inserted at the currently-blank line 345, between `### 5.1c` (ending 344) and `### 5.2` (346) — same three-line decision rule (key present → no-op; file exists, key absent → merge; file absent → leave absent) and the same python3 heredoc shape as `5.1c`, retargeted. |
| `skills/smith-audit/SKILL.md` | Item 7 (line 115) upgraded from a bare one-liner to a fuller description naming `_manifest_discovery.py` + the extended `detect-scanners.sh` + `dependency-scan.py`/`license-inventory.py`, run whole-project (consistent with `smith-audit`'s existing on-demand model), explicitly stating no separate/duplicated implementation exists (FR-26) — following items 6/10's own "upgrade the bullet, name the mechanism, state the fallback" style (`research.md` §5) rather than adding a new numbered item. |
| `docs/security-model.md` | New `## Supply-Chain & License Review` section, inserted after the existing `## Code-Content Security Review` section's closing `---` separator (currently before `## Scheduler Security` at line 119) — naming both sub-layers, the redaction-equivalent (N/A here — Sub-layer D/L findings are never secret-shaped, so no masking requirement applies, worth one explicit sentence so a reader doesn't wonder why this section has no redaction rule where Code-Content Security Review does), the explicit no-terminate contract (`data-model.md` §7), and the config home (`supply_chain`, distinct from `security_review`). Also extends "## What to Audit Before Enabling" (currently 7 files, 131-148) with 2 new items for `dependency-scan.py`/`license-inventory.py` (mirroring feature 55's own 4→7 extension), and updates item 7's existing `detect-scanners.sh` bullet to name the six new tools. |
| `CHANGELOG.md` | New `[Unreleased]` → `### Added` entry, written LAST after every other file's changes are final, describing the two sub-layers, the `supply_chain` config key, the flag-only/no-terminate posture (contrasted explicitly with Phase 3.6's own terminate rule so a changelog reader understands why this feature behaves differently from its immediate predecessor), the `smith-audit` Dependencies upgrade, and the `install.sh` stanza extension. |

## Phased ordering

1. **Shared discovery module + both orchestrators + their shims + both
   companion tests, first.** `scripts/security/_manifest_discovery.py`,
   `dependency-scan.py`/`.sh`, `license-inventory.py`/`.sh`, and both test
   files ship together and pass in isolation (stubbed scanners, no live
   network — see Test Strategy) BEFORE any SKILL.md wiring references
   them, mirroring feature 55's own "real code lands before markdown
   references it" rule.
2. **`detect-scanners.sh`'s one-line extension + its test-case additions.**
   Small, independent of phase 1's internals (a pure presence-detect
   list), but sequenced second because Phase 3's SKILL.md prose (next)
   needs the FULL nine-tool detection list to already exist before
   describing Sub-layer D's scanner-hierarchy selection against it.
3. **`smith-build` Phase 3.7 + §5.4 PR template.** Depends on phases 1-2
   (the scripts and the extended detection list must exist for the prose
   to correctly describe their invocation and output) — ships as one unit
   for the same "internally inconsistent half-shipped file" reason
   features 54/55 both gave for their own single-unit phase+template
   changes.
4. **`smith-audit` item 7 upgrade + `scripts/install.sh` stanza
   extension.** Both consume the exact same scripts phase 1 already
   shipped (FR-26's "no duplicated implementation" requirement is only
   checkable once both the scripts AND this wiring exist); the installer
   extension is sequenced here (not earlier) so it copies the FINAL set
   of files, not an interim one.
5. **Config + seeding + docs.** `templates/config.default.json`'s new
   key, the `skills/smith/SKILL.md` / `skills/smith-update/SKILL.md §5.1d`
   seeding additions, and `docs/security-model.md`'s new section —
   sequenced after phase 3 so the config/docs description matches the
   SCHEMA the shipped Phase 3.7 prose actually reads, avoiding two
   divergent schema descriptions drafted in parallel (mirrors feature
   55's own phase-3 rationale for its equivalent step).
6. **`CHANGELOG.md`.** Written last, after phases 1-5 are final.

## Test strategy

- **Script unit tests (primary surface)** —
  `tests/security/test_dependency_scan.sh`,
  `tests/security/test_license_inventory.sh`, plus
  `tests/security/test_detect_scanners.sh`'s extended cases. All run under
  BOTH bash and zsh (NFR-2), each producing a PASS/FAIL summary and
  non-zero exit on failure.
- **NO live network calls in any test, ever** (the task's own explicit
  requirement, and this research pass's own §7.1-§7.3 findings make clear
  why: `npm audit`/`pip-audit` both require real advisory-database
  reachability, which a CI runner or an offline dev machine cannot
  guarantee). Every scanner this feature invokes is STUBBED via a scratch
  `$PATH` populated with fake executables that print FIXED, planted JSON
  matching each real tool's actual output shape (the `npm audit`
  stub's fixture is modeled on THIS research pass's own live-captured
  `goldcanna-inventory/frontend` output —
  `{'info': 0, 'low': 1, 'moderate': 5, 'high': 19, 'critical': 3, 'total': 28}`,
  exit code 1 — so the test asserts against a REAL, previously-observed
  shape, not an invented one).
- **`goldcanna-inventory`-shaped fixture manifests** — planted under each
  test's own `mktemp -d` throwaway repo, mirroring the REAL layout this
  research pass confirmed live (`frontend/package.json`+`package-lock.json`,
  `menu-generator/package.json`+`package-lock.json`,
  `backend/pyproject.toml`+`poetry.lock`) — not an invented layout, so
  SC-1's multi-manifest success criterion is tested against the shape of
  a real consuming project, not a synthetic approximation.
  `xmlhttprequest-ssl`'s real legacy-`licenses[]` shape and `click`'s real
  `License-Expression`-only shape are both planted verbatim (values, not
  just structure) as fixture data, since both were empirically confirmed
  this session (`data-model.md` §4).
- **Offline/timeout simulation** — a stub scanner that `sleep`s past
  `supply_chain.timeout_seconds` (asserting the manifest is recorded
  skipped-with-disclosure, `timeout` reason, and the test itself completes
  quickly rather than actually waiting out a long real timeout — use a
  short configured `timeout_seconds` value, e.g. 2, for this specific
  case) and a stub that exits non-zero with connection-error-shaped
  stderr (asserting the `offline` skip reason) — both per FR-12/US-5.
- **Redaction is NOT a concern here** (unlike Phase 3.6) — CVE/license
  findings carry no secret-shaped content, so no masking assertion is
  needed; worth noting explicitly so a build phase doesn't import Phase
  3.6's redaction test pattern where it doesn't apply.
- **Prose consistency greps** (run after Phase 3.7/§5.4 prose lands):
  `grep -n "Phase 3.7" skills/smith-build/SKILL.md`,
  `grep -n "## Phase 4:" skills/smith-build/SKILL.md` (confirms it still
  immediately follows), `grep -c "Supply-Chain Review"
  skills/smith-build/SKILL.md` (expect ≥2 — phase heading + PR template
  section name), `grep -n "smith-build-supply-chain-findings.txt"
  skills/smith-build/SKILL.md` (expect matches where written AND where
  read).
- **Config-seeding regression** —
  `tests/hooks/test_config_default_seed.sh` (existing) is expected to
  keep passing UNMODIFIED; a new case is added verifying the fresh-project
  byte-for-byte-copy path now includes `supply_chain`.
- **Full-suite regression** — run the complete `tests/` directory after
  all phases land, confirming zero regressions in unrelated scripts this
  feature does not touch (NFR-5-equivalent discipline, even though this
  feature's own NFR-5-numbered requirement doesn't exist — the same
  "read-only neighbors" principle feature 55's NFR-5 established still
  applies in spirit: `skills/smith-clean-code/SKILL.md`, the
  `security-guard-*.sh` hooks, and Phase 3.5/3.6's own scripts are
  untouched by this feature).

## Rollout notes

- Distributed via the standard `/smith-update` path — `scripts/install.sh`'s
  extended stanza (see file-by-file above) is the ONLY reason the new
  scripts reach an already-installed project's `~/.smith/scripts/security/`;
  this was a real gap this research pass caught (`research.md` §3), not an
  automatic consequence of adding files to the repo tree.
- The pass runs on EVERY `smith-build` invocation from the moment this
  ships — `supply_chain.cve_scan`/`license_inventory` are the only
  per-sub-layer opt-outs; there is no way to disable Phase 3.7 as a whole
  short of setting both to `false`, mirroring Phase 3.6's own equivalent
  limitation (no whole-phase disable, only per-layer toggles) and
  therefore not a NEW limitation this feature introduces — consistent
  with the existing precedent, not a regression from it.

## Spec-plan tensions — RESOLVED, folded into the file-by-file list above

None of these were ever contradictions within spec.md itself — they were
gaps this plan's file-level research surfaced that spec.md's prose didn't
anticipate, or plan-level implementation decisions made here because they
are not among the six named A-6 items. None required a gate answer, and
the questions gate closing (`questions.md`, ANSWERED, 2026-09-13) did not
change any of them; each resolution below is now also reflected directly
in the "Exact file-by-file change list" section so a reader of that
section alone sees the full, definitive picture without needing this
section as a cross-reference.

1. **The `scripts/install.sh` security-copy stanza is a REAL gap, not one
   of the six named A-6 items — resolved outright in this plan, not
   deferred, and already folded into the file-by-file list's `scripts/install.sh`
   MODIFIED row.** `research.md` §3: the stanza names each file with its own
   `cp` line and does not glob its source directory. Without the new
   lines this plan adds, every already-installed project would silently
   keep the OLD script set after `/smith-update`. A mechanical reuse of
   existing precedent, not a product tradeoff.
2. **A third new Python file, `_manifest_discovery.py`, beyond the two
   named in the task description — resolved outright, not deferred, and
   already folded into the file-by-file list's own NEW-file row.**
   FR-5 (per-manifest independent scan, merged results) and FR-14
   (node_modules presence stricter than lockfile presence) both require
   Sub-layer D and Sub-layer L to agree, byte-for-byte, on what a
   "manifest" is and what its `lockfile_path`/`node_modules_present`/
   `venv_path` resolve to. Two independent manifest-walk
   implementations (one per orchestrator) risk exactly the kind of silent
   drift FR-26 explicitly forbids for `smith-audit` ("no duplicated
   implementation") — this plan applies the identical discipline one
   level earlier, between the two sub-layers themselves, not just between
   `smith-build` and `smith-audit`.
3. **The wrapper-shape question (`research.md` §8) is decided here, in
   this plan** — it is an implementation-shape choice (minimal
   pass-through shim, `run.sh`-style, not `secret-scan.sh`-style), not one
   of spec.md's six named A-6 items; already folded into the file-by-file
   list's `dependency-scan.sh`/`license-inventory.sh` NEW rows.
4. **The `osv-scanner`/`trivy`/`grype` three-way role question
   (`research.md` §7.2) — resolved outright, now folded into the
   file-by-file list's `dependency-scan.py` NEW row.** FR-8 names only
   `osv-scanner`/`trivy` as the preferred multi-ecosystem pair; `grype` is
   added to `detect-scanners.sh`'s detection list (FR-27, NFR-4) but has
   no defined invocation role in the FR text. This plan resolves it
   explicitly: `grype`'s presence is detected and disclosed (so
   `smith-audit`/future consumers can read it) but Sub-layer D's OWN
   scanner-hierarchy selection logic (`dependency-scan.py`) never invokes
   it in v1 — FR-8's literal "`osv-scanner` first, `trivy` second, when
   both are present" wording is read as exhaustive, not illustrative. A
   plan-level reading of already-written FR text, not a new product
   decision.
5. **`npm audit`'s lockfile-FORMAT edge case (`research.md` §7.1) —
   resolved outright, now folded into the file-by-file list's
   `dependency-scan.py` NEW row.** A `yarn.lock`/`pnpm-lock.yaml`-only npm
   manifest satisfies FR-4's broad "has a lockfile" definition but not
   FR-7's `npm-audit`-fallback precondition specifically. This plan's
   `enolock_wrong_format` skip reason (`data-model.md` §5) resolves the
   gap outright — a mechanical refinement of FR-7's stated `ENOLOCK` skip
   reason into two distinct, more precise reasons, not a contradiction of
   FR-7's own text.
