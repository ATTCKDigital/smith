---
feature: 56-supply-chain-gate
branch: 56-supply-chain-gate
status: ready-for-build
generated: 2026-09-13
inputs: spec.md (FR-1..FR-29, NFR-1..NFR-6, answers_applied 2026-09-13), plan.md (file-by-file + Phased ordering + folded Spec-plan tensions), data-model.md (§1-§7), research.md (§1-§9), questions.md (6/6 ANSWERED via delegation), quickstart.md (6 scenarios covering US-1..US-8)
---

# Tasks: Supply-Chain & License Review Pass for smith-build

21 tasks across 5 phases, matching this task-generation prompt's own phase
grouping (a slight relabeling, not a defect, of `plan.md`'s six-step Phased
ordering — see Coverage & Consistency Notes). Within a phase, tasks marked
`[P]` touch independent files and may run in any order/in parallel; tasks
touching the SAME file, or depending on another task's output, are listed
in required sequential order and are never marked `[P]` (mirrors feature
55's own task-generation convention).

This feature ships real standalone code (three new Python modules + two
thin `.sh` shims + two new test files), unlike feature 54's prose-only
shape — Phase 1 ships and verifies that code in isolation BEFORE any
`SKILL.md` prose references it, exactly as `plan.md`'s Phased ordering
item 1 requires (mirroring feature 55's own identical rule for its one
script).

**Four gaps found during task generation that `plan.md`/`data-model.md`
left underspecified — resolved and fixed in place below, not deferred**
(full reasoning in Coverage & Consistency Notes):
1. **No exit-code contract for `dependency-scan.py`/`license-inventory.py`.**
   `research.md` §2 only *recommends* reusing `secret-scan.sh`'s three-way
   contract "for consistency," without deciding it. **T002/T004** define
   one explicitly.
2. **No defined mechanism for merging TWO independent scripts' output into
   the SAME two `/tmp` files without one script's writes clobbering the
   other's, and without producing TWO trailing low-severity lines where
   `data-model.md` §5's own example shows exactly one.** **T002/T004/T011**
   resolve this: both scripts are pure stdout emitters (never touch
   `/tmp` themselves); Phase 3.7's own SKILL.md-level step performs the
   merge, including summing both scripts' reported low-severity counts
   into the single trailing line FR-23 requires.
3. **No test case for `pip-audit`'s severity-default-to-Medium behavior**
   (`data-model.md` §3's own stated rule) in `plan.md`'s
   `test_dependency_scan.sh` case list. **T006** adds it.
4. **No test case for the `grype`-detected-but-never-invoked behavior**
   `plan.md`'s own Spec-plan tensions item 4 resolves in prose but never
   tasks. **T006** adds it.

---

## Phase 1 — Scripts + tests (real, standalone, independently-runnable code; ships and passes in isolation before any `SKILL.md` prose references it — `plan.md`'s Phased ordering item 1)

- [X] [T001] [P] Create `scripts/security/_manifest_discovery.py` — the shared bounded-depth manifest-discovery module (`data-model.md` §2's record shape; `plan.md`'s File Size Policy target ≤120 lines). A genuine THIRD new Python file beyond the two named in the task description, resolved outright by `plan.md`'s Spec-plan tensions item 2 (not deferred): used by BOTH `dependency-scan.py` (T002) and `license-inventory.py` (T004) so the two sub-layers never disagree about what a "manifest" is, and transitively by `smith-audit`'s own invocation (FR-26) since it calls the same two orchestrators.
  - Library only — `discover_manifests(repo_root: str, extra_excludes: list[str]) -> list[dict]`. No `argparse`, no CLI entry point (an optional `if __name__ == "__main__":` debug-print block is fine for manual inspection but is not this module's contract).
  - Walk the repository from `repo_root`, bounded to 6 levels of depth (`research.md` §7's own depth-choice recommendation — generous headroom over `goldcanna-inventory`'s own 1-level nesting), excluding the fixed built-in set — `vendor/`, `node_modules/`, `.venv/`, `dist/`, `build/`, `.smith/` (the SAME family `secret-scan.sh:22`'s `BUILTIN_EXCLUDES` already uses) — plus `extra_excludes` (additive only, never removes a built-in exclusion — FR-4/`data-model.md` §1's `excludes` note).
  - Recognize: `package.json` (paired with a matching lockfile check), `pyproject.toml` (paired with `poetry.lock`), `requirements.txt`, `go.mod`, `Cargo.toml` (FR-4) — one record per manifest file found.
  - Populate every `data-model.md` §2 field by DIRECT filesystem check alongside the manifest, never deferred to scan-time:
    - `manifest_path` (repo-relative, forward-slash-separated), `ecosystem` (`"npm"` for `package.json`; `"poetry"` when `pyproject.toml`+`poetry.lock` are BOTH present at that manifest's directory; `"pip"` for a bare `requirements.txt` with no such pairing; `"go"`/`"cargo"` for `go.mod`/`Cargo.toml`).
    - `lockfile_path`/`lockfile_kind` (npm only): `"npm"` for `package-lock.json`/`npm-shrinkwrap.json` (the ONLY format `npm audit`'s FR-9 fallback can read directly — `research.md` §7.1), `"yarn"` for `yarn.lock`, `"pnpm"` for `pnpm-lock.yaml`, `null` if none found. A yarn/pnpm-only manifest satisfies FR-4's broad "has a lockfile" definition but not FR-7's npm-audit-fallback precondition — this distinct `lockfile_kind` value is what lets `dependency-scan.py` (T002) tell `enolock` apart from `enolock_wrong_format`.
    - `node_modules_present` (npm only, `os.path.isdir` at the manifest's directory — FR-14's stricter-than-lockfile Sub-layer L precondition).
    - `venv_path` (python ecosystems only): resolve via a `poetry env info -p`-equivalent subprocess call ONLY when `pyproject.toml`+`poetry.lock` are both present at the manifest's directory; `null` in every other case, INCLUDING a bare `requirements.txt` manifest, which has no defined venv-resolution mechanism in this v1 (FR-15 — system/global python3 is NEVER substituted; a `null` `venv_path` means Sub-layer L unconditionally skips that manifest with `no_venv`, a correct v1 behavior, not an oversight — document this explicitly in the module's header docstring).
  - `go.mod`/`Cargo.toml` records get `lockfile_path`/`lockfile_kind`/`node_modules_present`/`venv_path` all `null` — neither FR-9 (fallback tool list names no go/cargo tool) nor FR-13/FR-15 (npm/python only) define ecosystem-specific handling for these two beyond the FR-8 multi-ecosystem scanners; document this plainly so `dependency-scan.py`/`license-inventory.py` don't need to special-case it beyond falling through to their existing generic `absent`/no-op paths.

- [X] [T002] Create `scripts/security/dependency-scan.py` — the Sub-layer D orchestrator (`plan.md`'s File Size Policy target ≤280 lines; split per-tool parsing into a sibling `scripts/security/_scan_parsers.py` if the four tool-specific parsers alone would exceed it, mirroring feature 55's own `secret_scan.py`/`secret_patterns.py` contingency). Depends on T001 (imports `discover_manifests` directly).
  - **CLI**: `--repo-root <path>` (default: cwd), `--config <path>` (default: `<repo-root>/.smith/config.json`), `--timeout-seconds <N>` (optional CLI override of `supply_chain.timeout_seconds`, useful for tests without needing a fixture config file). Read `.smith/config.json` via the SAME defensive file-exists-AND-parses-AND-`isinstance(config, dict)` gate `secret-scan.sh:71-113` establishes — a missing/malformed config, or an absent `supply_chain` key, means every field falls back to its `data-model.md` §1 default (`cve_scan: true`, `timeout_seconds: 60`, `excludes: []`), never an error. Path never string-interpolated into a heredoc (`research.md` §2's own discipline).
  - **Step 0**: call `discover_manifests` (T001). Print `MANIFEST_COUNT: <n>` as the FIRST stdout line, always. **If `n == 0`, print nothing else and exit 0** — this is the resolved zero-manifest short-circuit contract (gap #2 above): the SKILL.md-level caller (T011) reads this line, writes the FR-6 sentinel itself, and does NOT invoke `license-inventory.py` at all in this case (both scripts share the identical discovery logic, so a second invocation would deterministically rediscover the same zero manifests — a pure efficiency win, not a behavior change, since Sub-layer L would no-op identically anyway).
  - **Step 1 — presence-detect.** Invoke the extended `detect-scanners.sh` (T009; resolved via the SAME installed-path-preferred/repo-dev-fallback candidate loop Phase 3.6 itself uses — `research.md` §1 item 2) once. If `osv-scanner` or `trivy` is present, run the FIRST one found (`osv-scanner` preferred — FR-8) ONCE against `repo_root`, covering every discovered manifest in one pass. `grype`'s presence is read but NEVER invoked by this file's own hierarchy logic in v1 (`plan.md`'s Spec-plan tensions item 4 — FR-8's tool list is exhaustive, not illustrative).
  - **Step 2 — fallback, per manifest, only when neither `osv-scanner` nor `trivy` is present (FR-9).** For each `ecosystem == "npm"` manifest: if `lockfile_kind == "npm"`, run `npm audit --json --package-lock-only`; if `lockfile_kind` is `"yarn"`/`"pnpm"`, skip with reason `enolock_wrong_format`; if `lockfile_kind` is `null`, skip with reason `enolock` (FR-7). For each `ecosystem` in `{"poetry", "pip"}`: only when `pip-audit` is present (per `detect-scanners.sh`'s output) — `poetry run python3 -m pip_audit -f json` when `venv_path` is resolved (poetry manifests), else `pip-audit -f json -r <manifest_path>` directly against the `requirements.txt` (a bare `pip` manifest has no venv to route through, and `pip-audit` can read a requirements file without one); when `pip-audit` is absent, skip with reason `absent`. For `go`/`cargo` manifests: always `absent` in the fallback path (no fallback tool is named for either ecosystem — FR-9's list is npm/python only).
  - **Timeout (FR-12/NFR-6).** Every invocation (`osv-scanner`/`trivy`/`npm audit`/`pip-audit`) wrapped in `subprocess.run(..., timeout=timeout_seconds)` (`research.md` §7.4's decided, justified mechanism — NOT a shell `timeout`/`gtimeout` wrapper, both confirmed absent on the reference dev machine). Catch `subprocess.TimeoutExpired` → skip reason `timeout`; catch a connection-error-shaped failure (non-zero exit with network-unreachable-shaped stderr, or any `OSError` from the subprocess call itself) → skip reason `offline`. Never a hang, never an unhandled exception reaching the process's own exit path.
  - **Normalization (`data-model.md` §3, FR-17).** Every finding → `{sub_layer: "D", source_scanner, ecosystem, manifest_path, package, version, advisory_id, severity, fix_available, rationale}`. `osv-scanner`/`trivy` report native severity, mapped directly. `npm audit --json`'s `metadata.vulnerabilities` buckets (FR-11 — MUST read this JSON object directly, MUST NEVER branch on the process exit code, which is empirically non-zero on real projects essentially always — `research.md` §7.1's own live-captured `goldcanna-inventory/frontend` run: exit 1, `{'info':0,'low':1,'moderate':5,'high':19,'critical':3,'total':28}`): `critical`→Critical, `high`→High, `moderate`→**Medium**, `low`→Low, `info`→folded into the SAME low bucket as `low`, never its own tier. `pip-audit`'s own JSON output lacks a first-class severity field in every case; when absent, default `Medium` and state the default was applied in the finding's `rationale` (`data-model.md` §3 — never silently dropped, never auto-escalated).
  - **Stdout contract (resolves gap #1/#2, this task's own decision, not left to the caller to improvise):** print, in order — (1) the `MANIFEST_COUNT:` line already covered above; (2) every Critical/High/Medium finding as its own line, `data-model.md` §5's exact bullet shape with `sub-layer: D`; (3) every `<manifest_path>: cve_scan=<ran:<tool>|skipped:<reason>|disabled>` status line (one per discovered manifest, including `disabled` verbatim when `supply_chain.cve_scan` is `false` — the manifest is still discovered and still gets a status line, just an unconditional `disabled` one, no scan attempted); (4) exactly one final line `LOW_COUNT: <n>` — the count of this run's own Low + `info`-folded findings (never rendered as individual lines itself; the CALLER, T011, sums this with `license-inventory.py`'s own `LOW_COUNT` and renders the single merged `+ N low-severity notes` trailing line FR-23 requires). These three line shapes are mutually exclusive by construction (`- **[` prefix vs. `<path>: cve_scan=` pattern vs. the literal `LOW_COUNT: ` prefix vs. `MANIFEST_COUNT: `) — the caller splits stdout by pattern-match, no additional delimiter needed.
  - **Exit codes (gap #1, this task's own decision, mirroring `secret-scan.sh`'s stated three-way contract per `research.md` §2):** `0` = ran clean, zero Critical/High/Medium findings from this invocation; `1` = ran, one or more Critical/High/Medium findings produced (informational signal only — Phase 3.7 has no terminate path, FR-20, so this is NEVER branched on for control flow, only logged/asserted in tests); `2` = internal/usage error (bad CLI args, `repo_root` doesn't exist, `python3`-level crash) — distinct from any per-manifest `skipped:*` outcome, which is NOT an error and never affects the exit code.
  - **No auto-fix, ever (FR-19).** Zero `Write`/`Edit`-shaped filesystem mutation calls anywhere in this file, for any finding, under any configuration — read-only against the scanned repository (subprocess invocations of external scanners are read-only by construction; `npm audit --package-lock-only` specifically avoids touching `node_modules/`).

- [X] [T003] [P] Create `scripts/security/dependency-scan.sh` — minimal pass-through shim (`scripts/smith-index/run.sh`-style, `research.md` §8's decided precedent over `secret-scan.sh`'s heavier bash-logic shape — this orchestrator needs no bash-side git-diff-scope resolution, FR-3: whole-repo, not diff-scoped). Depends on T002 (invokes it directly — same interface, sequenced after, not `[P]`). Target ≤20 lines: resolve own directory (`cd "$(dirname "$0")" && pwd`, NOT `BASH_SOURCE` — the `#!/usr/bin/env bash` shebang already pins the interpreter regardless of the invoking shell, matching `secret-scan.sh`'s own portable dir-resolution idiom, NFR-2), verify `dependency-scan.py` and `python3` both exist (exit 2 otherwise), `exec python3 "$THIS_DIR/dependency-scan.py" "$@"` — full flag parsing lives entirely in T002's own `argparse`.

- [X] [T004] [P] Create `scripts/security/license-inventory.py` — the Sub-layer L orchestrator (`plan.md`'s File Size Policy target ≤220 lines). Depends on T001 (imports `discover_manifests` directly); independent of T002/T003 (different sub-layer, no shared runtime state — `[P]`).
  - **CLI**: `--repo-root <path>`, `--config <path>` — same defaults/defensive-read convention as T002. No `--timeout-seconds`: Sub-layer L's own walks are pure filesystem reads (bounded by T001's depth+excludes, NFR-6), not network calls; the one subprocess it does invoke (`poetry run python3` for `importlib.metadata`, below) is wrapped in a small fixed internal `subprocess.run(timeout=...)` as defensive engineering against a hung/misconfigured poetry environment — NOT a new configurable surface, since FR-12's hard-timeout requirement is scoped to Sub-layer D only.
  - **Step 0**: call `discover_manifests` (T001), print `MANIFEST_COUNT: <n>` first, same as T002. If `n == 0`, print nothing else and exit 0 (this file's own independent invocations — e.g. a future direct `smith-audit` call, or a unit test — must handle the zero-manifest case correctly on their own; T011's Phase 3.7 orchestration simply never calls this script at all when T002 already reported `n == 0`, per T002's short-circuit).
  - **npm-ecosystem walk (FR-13), gated on `node_modules_present` (FR-14's stricter precondition than Sub-layer D's lockfile check — independent of whatever T002 found for the SAME manifest):** when `false`, skip with `no_node_modules`. When `true`: walk `node_modules/*/package.json` + `node_modules/@*/*/package.json` (scoped packages), read `license`; when absent, fall back to `licenses[0].type` (join multiple entries with `" OR "`) — the real, live-verified `xmlhttprequest-ssl` legacy shape (`data-model.md` §4: 507/508 resolve via the direct field, the 1 remaining needs this fallback; without it, this feature's own primary validation fixture would under-report). Bucket `UNKNOWN` only when BOTH are absent.
  - **Python-ecosystem walk (FR-15), gated on `venv_path` being non-null (poetry-managed only in this v1 — a bare `requirements.txt` manifest's `venv_path` is always `null` per T001, so it ALWAYS skips with `no_venv`):** invoke `importlib.metadata` via `poetry run python3` (never system/global python3). Resolution order, the live-verified 3-tier fallback chain (`data-model.md` §4 — a naive single-field read left 26/95 real `goldcanna-inventory/backend` distributions wrongly `UNKNOWN`, including `click`/`pydantic`): `License-Expression` (if present) → `License` (if present and not empty/literal `"UNKNOWN"`) → the LAST matching `Classifier` line starting `License ::` → else bucket `UNKNOWN`.
  - **Merge (FR-16).** Aggregate per manifest into `{license_id, manifest_path, ecosystem, packages: [{name, version}], count}` records, then merge across all manifests into one repo-wide inventory keyed on `license_id` (unioning `packages`, never deduplicating across different manifests — a package can legitimately appear under the same license from two install locations). `UNKNOWN` is a first-class bucket, never omitted.
  - **Policy evaluation (FR-18).** For every inventoried package whose `license_id` case-sensitively matches an entry in `supply_chain.license_policy.deny`: produce a Finding `{sub_layer: "L", severity: "High" (FIXED, never varies by license), category: "license-policy" (FIXED literal), package, version, manifest_path, ecosystem, rationale}` (`data-model.md` §4's exact shape). `allow` is read from config but produces NO findings of any kind in this version (A-4) — a documented no-op, not a bug.
  - **Stdout contract, same shape/exclusivity as T002 (gap #1/#2):** `MANIFEST_COUNT:` line, then every High-severity `license-policy` finding as its own `data-model.md` §5 bullet line with `sub-layer: L` (license findings have NO Low/Medium/Critical tier — FR-18 fixes every deny-hit at High, so there is no separate low-severity fold for THIS sub-layer's own findings; its `LOW_COUNT:` line is therefore always `0` unless a future version adds non-High license findings), then every `<manifest_path>: license_inventory=<ran|skipped:<reason>>` status line, then `LOW_COUNT: 0`.
  - **Exit codes**, identical three-way contract to T002: `0` clean, `1` one-or-more High findings produced, `2` internal/usage error.
  - **No auto-fix, ever (FR-19)** — read-only against `node_modules/` and the poetry environment; zero installed-tooling side effects (SC-4).

- [X] [T005] [P] Create `scripts/security/license-inventory.sh` — minimal pass-through shim, identical shape to T003. Depends on T004 (sequenced after, not `[P]`).

- [X] [T006] [P] Create `tests/security/test_dependency_scan.sh` — companion test, `test_secret_scan.sh`-style harness (`make_repo`, self-detected dual-shell interpreter per `test_detect_scanners.sh`'s own `ZSH_VERSION` guard, `assert_*` helpers, `PASS`/`FAIL`/summary/exit-status). Depends on T001-T003. **NO live network calls, ever** — every scanner is a scratch-`$PATH` stub printing FIXED, planted output; a fake `npm` shim's `audit` subcommand prints the exact live-captured `goldcanna-inventory/frontend` shape from `research.md` §7.1 (`{"metadata": {"vulnerabilities": {"info": 0, "low": 1, "moderate": 5, "high": 19, "critical": 3, "total": 28}}}`, exit 1); fake `osv-scanner`/`trivy`/`pip-audit` stubs for their own presence/absence branches. **Fixture manifests**: a `goldcanna-inventory`-shaped multi-manifest layout planted under the test's own `mktemp -d` repo — `frontend/package.json`+`package-lock.json`, `menu-generator/package.json`+`package-lock.json`, `backend/pyproject.toml`+`poetry.lock` (real layout, `plan.md`'s Test strategy). Required cases:
  - Multi-manifest merge (FR-5): all 3 manifests discovered, findings from all 3 merged, each still carrying its own `manifest_path`.
  - ENOLOCK skip (FR-7) alongside a working sibling manifest (US-4): remove `menu-generator/package-lock.json`, assert `menu-generator/package.json: cve_scan=skipped:enolock` while `frontend/package.json`'s own `cve_scan=ran:...` line is unaffected.
  - ENOLOCK-wrong-format skip (`research.md` §7.1's own surfaced edge case): a manifest with ONLY `yarn.lock` present asserts `skipped:enolock_wrong_format`, distinct from the no-lockfile-at-all case above.
  - `npm audit` severity-bucket mapping via the stub (`moderate`→Medium ×5, `info`+`low`→folded low count of 1) AND exit-code independence: re-run the identical stub patched to exit `0` instead of `1`, assert BYTE-IDENTICAL parsed output (FR-11) and `cve_scan=ran:npm-audit`, never `skipped:*`, despite the non-zero exit code case.
  - **`pip-audit` severity-default-to-Medium (gap #3 — `data-model.md` §3's own stated rule, not previously test-listed):** a stub `pip-audit` printing a JSON advisory record with NO severity field; assert the resulting finding defaults to `Medium` and its `rationale` states the default was applied.
  - `pip-audit`-absent skip: `osv-scanner`/`trivy` both absent, `pip-audit` also absent → the poetry manifest's `cve_scan=skipped:absent`.
  - Timeout simulation (FR-12/US-5): a stub that `sleep`s past a short `--timeout-seconds` override (e.g. `2`); assert `skipped:timeout` and that the TEST ITSELF completes quickly (bounded wait, not the real 60s default).
  - Offline simulation: a stub exiting non-zero with connection-error-shaped stderr; assert `skipped:offline`.
  - Zero-manifest silent-skip (FR-6): an empty scratch repo asserts `MANIFEST_COUNT: 0` and no further output, exit 0.
  - `osv-scanner`/`trivy`-preferred-over-fallback branch selection (FR-8): both present → ONE whole-repo invocation covers all manifests (same `source_scanner` on every `cve_scan=ran:...` line); `osv-scanner` preferred over `trivy` when both present.
  - **`grype`-detected-but-never-invoked (gap #4 — `plan.md`'s Spec-plan tensions item 4):** a scratch `$PATH` with ONLY `grype` present (osv-scanner/trivy absent) asserts Sub-layer D still falls through to the FR-9 per-manifest fallback path — `grype` is never invoked by this script's own hierarchy logic in v1, confirming FR-8's tool list is read as exhaustive.
  - Run the ENTIRE suite under both `bash tests/security/test_dependency_scan.sh` and `zsh tests/security/test_dependency_scan.sh` (NFR-2), identical PASS/FAIL outcomes.

- [X] [T007] [P] Create `tests/security/test_license_inventory.sh` — same harness style. Depends on T001, T004-T005. Required cases:
  - Legacy `licenses: [{type, url}]` fallback: a planted `node_modules/xmlhttprequest-ssl/package.json`-shaped fixture with NO `license` field, asserting the fallback resolves it (not `UNKNOWN`).
  - `License-Expression`-only fallback: a planted Python fixture distribution exposing ONLY `License-Expression` (the real `click`-shaped case), asserting the 3-tier chain resolves it.
  - Genuinely license-less package (npm: neither `license` nor `licenses[]`; python: none of `License-Expression`/`License`/a `License ::` classifier) → `UNKNOWN` bucketing, confirming the bucket still fires when all fallbacks are truly exhausted.
  - `node_modules`-absent-but-lockfile-present skip (FR-14, US-6): `package.json`+lockfile present, `node_modules/` removed → `license_inventory=skipped:no_node_modules`, verified DISTINCT from Sub-layer D's own lockfile-only precondition (a sibling assertion that the SAME manifest's hypothetical `cve_scan` line would NOT be gated the same way — cross-reference only, this file doesn't invoke T002).
  - `requirements.txt`-only manifest → `license_inventory=skipped:no_venv` unconditionally (T001's documented v1 boundary).
  - Deny-list match (FR-18/US-7): `supply_chain.license_policy.deny = ["GPL-3.0"]` in a fixture config, a planted package with that license → one High `license-policy` finding, `sub-layer: L`.
  - `allow`-list produces zero findings either way (A-4): populate `allow` with an unrelated license, confirm no behavioral change vs. an empty `allow`.
  - Zero-manifest case: `MANIFEST_COUNT: 0`, nothing else, exit 0.
  - Run under both bash and zsh (NFR-2).

- [X] [T008] Phase 1 verification gate (no file edit) closing Phase 1 before any `SKILL.md` wiring (T011+) may reference these scripts, per `plan.md`'s Phased ordering item 1. Depends on T001-T007. Run `bash`/`zsh` for both `tests/security/test_dependency_scan.sh` and `tests/security/test_license_inventory.sh` — all four invocations PASS, exit 0. Confirm `dependency-scan.sh`/`license-inventory.sh` are executable and independently invokable from the repo root with no dependency on any `SKILL.md` context. Confirm every new `.py` file is under its `plan.md` File Size Policy target (or that the `_scan_parsers.py` contingency was applied if not).

---

## Phase 2 — `detect-scanners.sh` extension + `install.sh` per-file `cp` lines (small, independent of Phase 1's internals, sequenced second because Phase 3's SKILL.md prose needs the FULL nine-tool detection list — `plan.md`'s Phased ordering item 2)

- [X] [T009] [P] Edit `scripts/security/detect-scanners.sh`. **One-line change** (`research.md` §2, confirmed at line 20 this worktree): `for tool in gitleaks semgrep bandit; do` → `for tool in gitleaks semgrep bandit osv-scanner grype trivy pip-audit licensee syft; do` (FR-27). Zero other lines change — same `<tool>=present|absent` output contract, `set -uo pipefail`, unconditional `exit 0`. Also extend `tests/security/test_detect_scanners.sh` (the EXISTING file, not T006/T007's new ones) with new cases for the six added tools, following its own `make_path_with`/`run_case` idiom verbatim (`research.md` §2 — representative subsets, not the full 2⁹ combinatorial space, matching the existing 5 cases' own economy): at minimum one all-nine-present case, one all-nine-absent case, and one mixed case isolating `osv-scanner`+`trivy` present with everything else absent (the exact combination FR-8's preference logic depends on). Run under both bash and zsh (NFR-2).

- [X] [T010] [P] Edit `scripts/install.sh`. Extend the existing security-copy stanza (confirmed at lines 220-231 this worktree — `research.md` §3: this stanza names each file with its own `cp` line, it does NOT glob its source directory) with five new lines, each following the exact existing shape `cp "$REPO_ROOT/scripts/security/<file>" "$SMITH_HOME/scripts/security/<file>" 2>/dev/null || true`:
  ```bash
  # Feature 56-supply-chain-gate: _manifest_discovery.py/dependency-scan.{py,sh}/
  # license-inventory.{py,sh} — unconditional for the same reason as feature 55's
  # own scripts above (not parsers, so not gated by --no-parsers).
  cp "$REPO_ROOT/scripts/security/_manifest_discovery.py" "$SMITH_HOME/scripts/security/_manifest_discovery.py" 2>/dev/null || true
  cp "$REPO_ROOT/scripts/security/dependency-scan.py" "$SMITH_HOME/scripts/security/dependency-scan.py" 2>/dev/null || true
  cp "$REPO_ROOT/scripts/security/dependency-scan.sh" "$SMITH_HOME/scripts/security/dependency-scan.sh" 2>/dev/null || true
  cp "$REPO_ROOT/scripts/security/license-inventory.py" "$SMITH_HOME/scripts/security/license-inventory.py" 2>/dev/null || true
  cp "$REPO_ROOT/scripts/security/license-inventory.sh" "$SMITH_HOME/scripts/security/license-inventory.sh" 2>/dev/null || true
  ```
  Placed immediately before the existing `chmod +x "$SMITH_HOME/scripts/security/"*.sh 2>/dev/null || true` line so the glob's existing coverage picks up the two new `.sh` shims automatically — no new `chmod` line needed (`plan.md`'s own MODIFIED-row note). Without this task, `/smith-update` would silently keep serving the OLD script set to every already-installed project (identical class of gap to feature 55's own T006).

---

## Phase 3 — `smith-build` Phase 3.7 + §5.4 PR template (depends on Phases 1-2 — the scripts and the FULL nine-tool detection list must exist for this prose to correctly describe their invocation and output — `plan.md`'s Phased ordering item 3)

- [X] [T011] Edit `skills/smith-build/SKILL.md`. Insert a new `## Phase 3.7: Supply-Chain Review Pass` section at the currently-blank **line 425** (confirmed this worktree — between Phase 3.6's closing content ending line 424 and `## Phase 4:` at line 426, `research.md` §1 — zero renumbering of Phase 4 through 7 or any cross-reference to them). Depends on T001-T010. Per `plan.md`'s File Size Policy, target 60-90 lines of new prose (structurally SIMPLER than Phase 3.6 despite covering two sub-layers — no decision table, no terminate branch). Reference `data-model.md`'s contracts (§1-§7) by section number, qualified EXACTLY as "this feature's `data-model.md` §N" (`research.md`'s own numbering caution — three same-named `data-model.md` files now exist across feature folders 53/54/55/56). Content, mirroring Phase 3.6's five-part shape adapted for two sub-layers and NO terminate branch:
  1. **Invocation — state the divergence up front, not left implicit.** Thread `WORKTREE_PATH` to locate the repository root; explicitly do NOT thread `BASE_BRANCH` — this phase performs a full-project scan, not a diff scan (FR-3/A-3), unlike EVERY phase before it in this file (3, 3.5, 3.6, 4, §5.3, §5.3.1). State plainly this phase runs exactly once per build, gated on Phase 3.6 having completed as an ordering precondition only, independent of Phase 3.6's own outcome on runs where 3.6 does not itself hard-stop (FR-2) — and that if Phase 3.6 DID hard-stop, Phase 3.7 is simply never reached at all (the pipeline never resumes past a Phase 3.6 termination; this is a consequence of Phase 3.6's own existing contract, not something Phase 3.7 itself gates).
  2. **Step 1 — presence-detect.** Invoke `detect-scanners.sh` (T009, resolved via the SAME installed-path-preferred/repo-dev-fallback candidate loop Phase 3.6 already uses) once, now yielding nine tools' presence.
  3. **Step 2 — run Sub-layer D.** Invoke `dependency-scan.sh` (T003) with `--repo-root "$WORKTREE_PATH"`. Capture its stdout. Parse the FIRST line as `MANIFEST_COUNT: <n>`. **If `n == 0`:** write ONLY the sentinel line `0 manifests found` to `/tmp/smith-build-supply-chain-scan-status.txt`; write nothing to `/tmp/smith-build-supply-chain-findings.txt` (leave it empty/absent); record the SAME `0 manifests found` text (`data-model.md` §5's own explicit "reused verbatim... never drift into two different phrasings" requirement) as this phase's vault session-log entry (FR-6); do NOT invoke `license-inventory.sh` at all; proceed straight to step 5. **If `n > 0`:** split the remaining stdout by line shape into (a) `data-model.md` §5 finding-bullet lines, (b) `cve_scan=` status lines, (c) the trailing `LOW_COUNT: <n_d>` line; hold all three in memory for the merge step.
  4. **Step 3 — run Sub-layer L (only reached when Sub-layer D's own `MANIFEST_COUNT` was `> 0`).** Invoke `license-inventory.sh` (T005) with `--repo-root "$WORKTREE_PATH"`; split its stdout identically into finding lines, `license_inventory=` status lines, and its own `LOW_COUNT: <n_l>` line.
  5. **Step 4 — merge + write (never decide, never terminate — this is the ONLY place either sub-layer's output reaches disk).** Concatenate: Sub-layer D's finding lines, then Sub-layer L's finding lines, then — ONLY when `n_d + n_l > 0` — exactly one trailing `+ <n_d + n_l> low-severity notes` line (FR-23, `data-model.md` §5 — this single summed line is what resolves gap #2: neither script renders its own trailing line, only this merge step does) → write to `/tmp/smith-build-supply-chain-findings.txt`. Concatenate Sub-layer D's status lines then Sub-layer L's status lines (per-manifest, so a given `manifest_path` naturally gets BOTH a `cve_scan=` and a `license_inventory=` line adjacent or interleaved, matching `data-model.md` §5's own example) → write to `/tmp/smith-build-supply-chain-scan-status.txt`.
  6. **No auto-fix, ever (FR-19).** State plainly: zero `Write`/`Edit` calls to the working tree for any finding, from either sub-layer, under any configuration — identical invariant to Phase 3.6, for a categorically different reason (a dependency bump or license swap is an even larger judgment call than a security remediation).
  7. **Unlike Phase 3.6: no decision table, no terminate branch, ever (FR-20/OOS-3, `data-model.md` §7 — state this explicitly as a deliberate v1 boundary, not an oversight, since Phase 3.6 sits directly upstream and a reader who just internalized ITS terminate semantics could otherwise wrongly assume inheritance).** Phase 4 ALWAYS begins next, unconditionally, regardless of what either sub-layer found — even a Critical CVE with a known exploit, even a deny-listed license on a production package.
  8. **NEVER a prompt or pause of any kind (NFR-1)** — every branch above, including the zero-manifest path, is silent and autonomous.
  - **Key Rules (969-980): verified NO new clause needed** (`plan.md`'s own explicit statement) — unlike Phase 3.6's hard-stop disambiguation, Phase 3.7 introduces no new autonomy/interaction behavior beyond what the existing "ALL phases run without user interaction" bullet already covers, since this phase can never pause, block, or terminate. Do not add one.

- [X] [T012] Edit `skills/smith-build/SKILL.md` §5.4 (the PR-body heredoc). Depends on T011 (references the files/merge logic T011's phase produces). Add a new conditional `## Supply-Chain Review` section, positioned immediately after the existing `## Security Review` block (confirmed ending line 776 this worktree) and before `## Release notes` (confirmed line 778) — the newest section appended after every existing one, per `data-model.md` §6, matching how `## Security Review` itself was appended after `## Clean Code Review` rather than reordering. Content:
  - Include the section ONLY when `/tmp/smith-build-supply-chain-findings.txt` is non-empty (`[ -s ... ]` or equivalent) — covers BOTH the zero-manifest case (FR-6) and the case where every discovered manifest scanned clean with full tool coverage (FR-22); omit entirely otherwise.
  - **The verbatim required line, FR-24's own literal text, reused exactly**: `**full-project scan, not diff-scoped; findings may predate this change**` — since, unlike every other PR-body section in this pipeline, this section's findings are not scoped to the current branch's diff.
  - **Per-manifest scan-path disclosure**, derived from `/tmp/smith-build-supply-chain-scan-status.txt` (FR-24): state, per manifest, which scan path ran (multi-ecosystem scanner name, or the per-manifest fallback tool name) and which manifests/tools were skipped and why (`absent`, `enolock`, `enolock_wrong_format`, `no_node_modules`, `no_venv`, `timeout`, `offline`, `disabled`) — mirroring the `data-model.md` §6 worked example. The section MUST NEVER state or imply full scanner coverage when a tool was actually skipped.
  - Embed `/tmp/smith-build-supply-chain-findings.txt`'s contents verbatim (already Critical/High/Medium individual + the one merged low-count trailing line — no second filtering step here, FR-23).
  - Close with: "This is a FLAG, never a blocker — no finding from either sub-layer, at any severity, blocks or delays this PR (FR-19/FR-20)." (`data-model.md` §6's own closing line.)

---

## Phase 4 — Config + seeding + `smith-audit` wiring + docs + CHANGELOG (sequenced after Phase 3 so each artifact matches the SCHEMA/scripts the shipped Phase 3.7 prose actually reads — `plan.md`'s Phased ordering items 4-6, collapsed into one phase per this task-generation prompt's own grouping)

- [X] [T013] [P] Edit `templates/config.default.json`. Add a new top-level `supply_chain` key (`data-model.md` §1's exact RESOLVED schema, FR-28) positioned after `security_review`'s closing `}` (confirmed line 25 this worktree) and before `context_budget` (confirmed line 26):
  ```jsonc
  "supply_chain": {
    "cve_scan": true,
    "license_inventory": true,
    "license_policy": {
      "allow": [],
      "deny": []
    },
    "timeout_seconds": 60,
    "excludes": []
  }
  ```
  A SIBLING of `security_review`, never nested under it — `security_review`'s schema is closed per its own FR-24, and nesting would falsely imply shared tier semantics this feature does not have (FR-20/Q2). No `enforcement_tier`-shaped field anywhere in this schema, by design.

- [X] [T014] [P] Edit `skills/smith/SKILL.md`. Add a new unlettered paragraph + python3 read-modify-write heredoc, mirroring the existing `security_review` seed block EXACTLY (confirmed lines 300-331 this worktree), retargeted at `supply_chain` with T013's full default shape, placed immediately after that block's closing `fi` (line 331) and before "Copy from `~/.claude/skills/smith/`:" (line 333). Three-line decision rule, same as the existing block: key present (any shape) → no-op; file exists, key absent → merge just `supply_chain` with T013's defaults, preserving every other key; file absent entirely → leave absent (the whole-file template copy, now including `supply_chain` via T013, already handles a brand-new project). bash+zsh-safe.

- [X] [T015] [P] Edit `skills/smith-update/SKILL.md`. Add a new `### 5.1d Seed \`supply_chain\` in \`.smith/config.json\`` at the currently-blank **line 345** (confirmed this worktree — between `### 5.1c` ending line 344 and `### 5.2` at line 346). Same three-line decision rule and python3 heredoc shape as `5.1c`, retargeted at `supply_chain`/T013's defaults.

- [X] [T016] [P] Edit `skills/smith-audit/SKILL.md`. Upgrade item 7 (confirmed line 115 this worktree, inside `## Sub-Audit Orchestration`) from "**Dependencies** (`smith-audit dependencies`) — outdated packages, CVEs, unused deps" to name the concrete mechanism now backing it — `detect-scanners.sh` (extended, T009) plus `dependency-scan.py`/`license-inventory.py` (T002/T004, transitively `_manifest_discovery.py`, T001) — run whole-project (consistent with `smith-audit`'s existing on-demand, whole-system model AND with Phase 3.7's own non-diff-scoped design, FR-3/FR-25 — these are the same underlying design choice, not a coincidence), and state plainly that NO separate or duplicated implementation exists anywhere in `smith-audit`'s own prose (FR-26) — closing feature 55's own NFR-4 intent, which explicitly named this future feature ("F2, out of scope here") as `detect-scanners.sh`'s second consumer. Follow items 6/10's own "upgrade the bullet, name the mechanism, state the fallback" style (`research.md` §5) rather than adding a new numbered item.

- [X] [T017] [P] Edit `docs/security-model.md`. Add a new `## Supply-Chain & License Review` section, inserted after the existing `## Code-Content Security Review` section's closing `---` separator (confirmed immediately before `## Scheduler Security` at line 119 this worktree). Name both sub-layers, state explicitly that redaction does NOT apply here (unlike Code-Content Security Review — CVE/license findings carry no secret-shaped content, so no masking requirement exists; worth one sentence so a reader doesn't wonder why this section has none), the explicit no-terminate contract (`data-model.md` §7), and the config home (`supply_chain`, distinct from `security_review`, cross-referencing `data-model.md` §1 rather than restating the schema). Also extend "## What to Audit Before Enabling" (confirmed 7 items, lines 131-148) with 2 new items — `~/.smith/scripts/security/dependency-scan.py` (scanner-hierarchy selection, timeout handling) and `~/.smith/scripts/security/license-inventory.py` (the fallback chains, deny-list evaluation) — mirroring feature 55's own 4→7 extension of the same list, and update item 7's existing `detect-scanners.sh` bullet (confirmed line 147) to name all nine tools now detected, not just the original three.

- [X] [T018] Edit `CHANGELOG.md`. Depends on T001-T017 (written last, describing what actually shipped). Add a new entry under `[Unreleased]` → `### Added`, matching the existing entries' bold-summary + sub-bullets style (see the `#55`/`#54`/`#53` entries immediately below where this one lands). Summarize: (a) the new `smith-build` `## Phase 3.7: Supply-Chain Review Pass` — Sub-layer D (dependency CVE scan, `osv-scanner`/`trivy` preferred whole-repo pass else per-manifest `npm audit`/`pip-audit` fallback with exit-code-ignored JSON parsing) and Sub-layer L (dependency-free license inventory, `node_modules`-gated for npm, `poetry run python3`+`importlib.metadata` for Python) both running full-project (not diff-scoped, explicitly disclosed as such in the PR body) after Phase 3.6 and before Phase 4; (b) the flag-only, no-terminate posture — contrasted explicitly with Phase 3.6's own terminate rule so a changelog reader understands why the two features behave differently; (c) the new `supply_chain` config key (sibling of `security_review`, empty allow/deny license policy by default) with its non-destructive seeding at both `/smith` init and `/smith-update` (§5.1d); (d) the `smith-audit` Dependencies sub-audit upgrade (item 7) to invoke the identical scripts, closing feature 55's NFR-4 intent; (e) the `detect-scanners.sh` extension (`osv-scanner`, `grype`, `trivy`, `pip-audit`, `licensee`, `syft`) and the `install.sh` stanza extension. Cite the feature by number (`#56`, `56-supply-chain-gate`).

---

## Phase 5 — Verification (consistency greps, full regression, fixture e2e per `quickstart.md`)

- [X] [T019] Consistency verification sweep (no file edit unless a check below fails — then fix the offending file in place and re-check). Depends on T001-T018.
  - `grep -n "Phase 3.7" skills/smith-build/SKILL.md` — the new heading exists exactly once; `grep -n "## Phase 4:" skills/smith-build/SKILL.md` — Phase 4 still immediately follows.
  - `grep -c "Supply-Chain Review" skills/smith-build/SKILL.md` — ≥2 matches (Phase 3.7 heading/prose + T012's §5.4 section name).
  - `grep -n "smith-build-supply-chain-findings.txt" skills/smith-build/SKILL.md` — appears both where written (T011) and where read (T012). Same check for `smith-build-supply-chain-scan-status.txt`.
  - `grep -n "enforcement_tier" templates/config.default.json` under the `supply_chain` block specifically — expect ZERO matches inside that block (FR-20's own schema-closed requirement; `security_review`'s own `enforcement_tier` field must remain untouched elsewhere in the same file).
  - `python3 -c "import json; d = json.load(open('templates/config.default.json')); assert set(d['supply_chain'].keys()) == {'cve_scan','license_inventory','license_policy','timeout_seconds','excludes'}; assert d['supply_chain']['license_policy'] == {'allow': [], 'deny': []}"` — confirms T013's exact key set and empty-by-default policy match `data-model.md` §1 with no drift.
  - `grep -rn "BASE_BRANCH" skills/smith-build/SKILL.md` scoped to the new Phase 3.7 section only — expect ZERO matches (FR-3/A-3: this phase never threads `BASE_BRANCH`, unlike every phase around it).
  - `git diff "$(.specify/scripts/bash/get-base-branch.sh)" --name-only` (run from the worktree) — confirms by construction that `skills/smith-clean-code/SKILL.md`, the three `security-guard-*.sh` hooks, `skills/smith-build/SKILL.md`'s Phase 3.5/3.6 content, and `smith-audit`'s SKILL.md beyond item 7 are untouched (NFR-5).
  - Confirm T010's `install.sh` stanza and T009's `test_config_default_seed.sh`-adjacent seeding are present — then, mirroring feature 55's own T016, add ONE new regression case to `tests/hooks/test_config_default_seed.sh` (confirmed pattern at line 129: `assert_file_contains "fresh project: contains security_review section" ...`) asserting the fresh-seed path now ALSO contains `"supply_chain"` — a pure regression addition, every existing case in that file must keep passing unmodified.
  - `grep -rn "dependency-scan\|license-inventory" skills/smith-audit/SKILL.md` — resolves to invocation references only (T016), never a re-implementation (FR-26).

- [X] [T020] Full regression suite run. Depends on T001-T019. Run the complete pre-existing `tests/` directory once, confirming zero regressions in files this feature does not touch: `tests/get-base-branch.test.sh`, `tests/workflow-gate-redirect.test.sh`, `tests/workflow-summary-session.test.sh`, `tests/install.smoke.sh`, the full `tests/hooks/*.sh` suite (including T019's updated `test_config_default_seed.sh`), `tests/security/test_secret_scan.sh` + `test_detect_scanners.sh` (re-run under both bash and zsh — confirms T009's extension didn't regress feature 55's own cases), PLUS this feature's own new suites — `tests/security/test_dependency_scan.sh` and `test_license_inventory.sh` — under BOTH bash and zsh (NFR-2), re-run (not just T008's earlier isolated pass, confirming no later task broke them).

- [X] [T021] Fixture end-to-end verification per `quickstart.md`'s 6 scenarios (manual/scripted, against the shipped scripts directly and, where feasible, a live `/smith-build`/`smith-audit dependencies` run — exercises the FULL pipeline integration T006/T007's stubbed-scanner unit tests cannot). Depends on T001-T020.
  1. **Scenario 1** (`goldcanna-inventory`, US-1/SC-1): all 3 real manifests discovered; merged findings each carry their own `manifest_path`; ENOLOCK-with-unaffected-sibling sub-case (temporarily remove `menu-generator/package-lock.json`); workflow proceeds with no termination.
  2. **Scenario 2** (THIS repository's own current zero-manifest state, US-3/SC-2) — run FIRST as the cheapest real-environment check, requiring no setup: `MANIFEST_COUNT: 0`, sentinel-only status file, no findings file, no PR-body section, vault log records the zero-manifest outcome.
  3. **Scenario 3** (stubbed `npm audit`, US-2/SC-3): the exact live-captured JSON body from `research.md` §7.1, both exit 0 and exit 1 variants, byte-identical parsed output.
  4. **Scenario 4** (US-5/SC-5): timeout sub-case (short `timeout_seconds`) and offline sub-case, both never hang/fail the build, a sibling manifest in the same run unaffected.
  5. **Scenario 5** (`goldcanna-inventory`'s real environment, US-6/US-7): `node_modules`-absent gate on `frontend/` while Sub-layer D still scans it for CVEs; UNKNOWN bucketing regression bar (0/95 true UNKNOWN, 508/508 resolved, per `data-model.md` §4's live-verified counts); deny-list hit produces a High `license-policy` finding without terminating.
  6. **Scenario 6** (US-8/SC-6): `smith-audit dependencies` invokes the byte-identical script paths Phase 3.7 uses (installed-path-preferred/repo-dev-fallback), whole-project, no `BASE_BRANCH` threading, no duplicated implementation (`grep -rn "dependency-scan\|license-inventory" skills/smith-audit/SKILL.md` resolves to invocation only).

---

## Coverage & Consistency Notes (smith-analyze pass)

**Spec ↔ Plan ↔ Tasks alignment: PASS, with 2 CRITICAL implementation-contract gaps and 2 test-coverage gaps found and fixed in place (all four explained above and in T002/T004/T006). No contradiction found with any of the 6 gate answers. Every row in `plan.md`'s "Exact file-by-file change list" is tasked.**

### Critical gaps found and fixed in place

1. **No exit-code contract for `dependency-scan.py`/`license-inventory.py` or their shims (T002/T004).** `research.md` §2 only *recommends*, without deciding, that Sub-layer D/L's scripts "should adopt the identical three-way contract" `secret-scan.sh` established — neither `plan.md`'s file-by-file table nor `data-model.md` defines one. Resolved: `0` clean, `1` findings-present (never branched on for control flow — Phase 3.7 has no terminate path, FR-20), `2` internal error — identical shape to feature 55's own T002 gap-fix, for the same underlying reason (a script needs SOME machine-readable pass/fail signal for its own tests even when the caller never uses it to gate anything).
2. **No defined mechanism for two independently-invoked scripts to populate the SAME two `/tmp` files without clobbering each other, and no resolution for how `data-model.md` §5's single merged `+ N low-severity notes` trailing line is produced when each sub-layer only knows its OWN low-severity count.** `plan.md`'s own file-by-file row for `dependency-scan.py` says it "emits `data-model.md` §5's two `/tmp` files' CVE-half content on stdout for the caller to redirect" — stating stdout-only output but not resolving how a SINGLE stdout stream carrying both destination files' content gets split, nor how two scripts' independent low-counts become one merged line. Resolved (T002/T004/T011): both scripts are pure stdout emitters with three self-distinguishing line shapes (`MANIFEST_COUNT:`, finding bullets, `<path>: <sub-layer>=...` status lines, a trailing `LOW_COUNT:`) — Phase 3.7's own SKILL.md-level merge step (T011 step 4) is the ONLY place that writes to `/tmp`, concatenating both scripts' finding/status lines and summing their `LOW_COUNT` values into the one required trailing line. This also yields a clean efficiency win: when Sub-layer D's own `MANIFEST_COUNT` is `0`, `license-inventory.sh` is never even invoked (both sub-layers share the identical discovery module, T001, so a second invocation would deterministically rediscover the same empty result).

### Test-coverage gaps found and fixed in place

3. **No test case for `pip-audit`'s severity-default-to-`Medium` behavior (T006).** `data-model.md` §3 states this rule explicitly ("`pip-audit`'s own JSON output carries advisory records without a first-class severity field in every case; when absent, default to `Medium`... and note the default was applied") but `plan.md`'s own `test_dependency_scan.sh` case list never names a case for it. Added as an explicit stubbed-`pip-audit` case in T006.
4. **No test case for the `grype`-detected-but-never-invoked behavior `plan.md`'s Spec-plan tensions item 4 resolves in prose.** `research.md` §7.2 flagged the `osv-scanner`/`trivy`/`grype` three-way role question as worth flagging "for the gate/build phase"; `plan.md` resolved it (detected+disclosed, never invoked by v1's hierarchy logic) but carried no task/test for the resolution itself. Added as an explicit case in T006: a scratch `$PATH` with only `grype` present still falls through to the FR-9 fallback path.

### FR / NFR / SC → task traceability

| Requirement | Task(s) |
|---|---|
| FR-1 (Phase 3.7 ordering, after 3.6/before Phase 4) | T011 |
| FR-2 (runs exactly once; gated on 3.6 completion, not re-entrant) | T011 |
| FR-3 (`WORKTREE_PATH` not `BASE_BRANCH`; whole-project scan) | T002, T004, T011 |
| FR-4 (bounded-depth walk, standard excludes, 5 manifest types) | T001 |
| FR-5 (per-manifest independent scan + merge) | T001, T002, T011 |
| FR-6 (zero-manifest no-op, vault log, no PR section) | T001, T002, T011 |
| FR-7 (npm audit lockfile precondition, ENOLOCK skip) | T001, T002; tested T006 |
| FR-8 (osv-scanner/trivy preferred whole-repo pass) | T002; tested T006 |
| FR-9 (per-manifest fallback, pip-audit/npm-audit, network needed) | T002; tested T006 |
| FR-10 (no tool available → skip, never fails build) | T002; tested T006 |
| FR-11 (npm audit JSON parsing, exit code never used, moderate→Medium) | T002; tested T006 |
| FR-12 (hard timeout, config-overridable, timeout/offline → skip) | T002, T013; tested T006 |
| FR-13 (dependency-free npm license walk) | T004; tested T007 |
| FR-14 (node_modules gate, stricter than lockfile) | T001, T004; tested T007 |
| FR-15 (importlib.metadata via poetry run python3, UNKNOWN bucket) | T004; tested T007 |
| FR-16 (merged output shape, UNKNOWN first-class) | T004; tested T007 |
| FR-17 (finding field set, both sub-layers) | T002, T004 |
| FR-18 (deny→High finding, allow no-op) | T004, T013; tested T007 |
| FR-19 (no auto-fix, ever, either sub-layer) | T002, T004, T011 |
| FR-20 (no enforcement tier, no terminate path) | T013, T011 |
| FR-21 (two exact `/tmp` file names) | T011 |
| FR-22 (PR section only when findings non-empty) | T012 |
| FR-23 (severity threshold, single merged low-count line) | T011, T012 |
| FR-24 (scan-path disclosure + verbatim not-diff-scoped line) | T012 |
| FR-25 (smith-audit invokes same scripts, whole-project) | T016 |
| FR-26 (no forked/duplicated logic) | T016; verified T019/T021 |
| FR-27 (detect-scanners.sh +6 tools, same contract) | T009 |
| FR-28 (supply_chain config schema) | T013 |
| FR-29 (seeding: init + `/smith-update` §5.1d) | T014, T015 |
| NFR-1 (no user interaction, ever) | T011 |
| NFR-2 (bash+zsh for shell content; python3 for Python) | T003, T005, T006, T007, T009, T020 |
| NFR-3 (at most once per build, no retry loop) | T011 |
| NFR-4 (single reused presence-detect helper) | T009; reused by T002/T004 |
| NFR-5 (does not modify 3.5/3.6/clean-code/guard hooks/smith-audit beyond item 7 + detect-scanners.sh) | verified T019 |
| NFR-6 (every invocation/walk bounded) | T001 (depth+excludes), T002 (timeout) |
| SC-1 (goldcanna fixture merged CVE results) | tested T006; verified T021 Scenario 1 |
| SC-2 (manifest-less repo clean skip) | tested T006/T007; verified T021 Scenario 2 |
| SC-3 (npm audit severity mapping, exit-code-independent) | tested T006; verified T021 Scenario 3 |
| SC-4 (license inventory installs zero new deps) | T004; tested T007 |
| SC-5 (offline/timeout never hangs/fails) | tested T006; verified T021 Scenario 4 |
| SC-6 (smith-audit invokes same scripts, no dup) | T016; verified T019/T021 Scenario 6 |

### Plan file-by-file → task coverage

Every NEW/MODIFIED file in `plan.md`'s "Exact file-by-file change list" has at least one task: `_manifest_discovery.py` (T001), `dependency-scan.py` (T002), `dependency-scan.sh` (T003), `license-inventory.py` (T004), `license-inventory.sh` (T005), `test_dependency_scan.sh` (T006), `test_license_inventory.sh` (T007), `detect-scanners.sh` (T009), `scripts/install.sh` (T010), `skills/smith-build/SKILL.md` (T011/T012), `templates/config.default.json` (T013), `skills/smith/SKILL.md` (T014), `skills/smith-update/SKILL.md` (T015), `skills/smith-audit/SKILL.md` (T016), `docs/security-model.md` (T017), `CHANGELOG.md` (T018). One additional file beyond `plan.md`'s own list is touched, justified above as a coverage-gap fix: `tests/hooks/test_config_default_seed.sh` (folded into T019, mirroring feature 55's own T016 precedent for the identical class of gap).

### Gate-answer (questions.md, 6/6 ANSWERED via delegation) non-contradiction check

- **Q1 (new Phase 3.7, not extending 3.6):** T011 inserts a standalone new phase at the confirmed-blank line 425; no task modifies Phase 3.6's own decision table or terminate branch.
- **Q2 (new top-level `supply_chain` key, not nested under `security_review`):** T013 adds it as a sibling; T019 greps confirm no `enforcement_tier`-shaped field leaks into it.
- **Q3 (flag-only v1, no terminate path):** T011/T013 both implement this as a structural absence (no decision table, no tier field) rather than a config toggle set to "off" — there is no code path anywhere in T001-T021 that could produce a terminate outcome.
- **Q4 (license inventory-only, empty allow/deny by default):** T013 seeds both arrays empty; T004 implements `deny` matching and `allow` as a documented no-op; no task ships a default deny list.
- **Q5 (`smith-bugfix` excluded):** no task in any phase touches `skills/smith-bugfix/SKILL.md` — confirmed absent from every file-modifying task above, and re-confirmed by T019's `git diff --name-only` check.
- **Q6 (`smith-audit` wiring included):** T016 upgrades item 7 to invoke the identical scripts; T019/T021 Scenario 6 verify no duplicated implementation exists.

No FR/NFR/SC is contradicted by any task above. No task instructs work `spec.md`'s Out of Scope section (OOS-1..OOS-5) excludes — in particular, no task touches `smith-bugfix` (OOS-1), no task attributes a finding to this branch's own diff (OOS-2), no task adds a block/terminate path (OOS-3), no task generates an SBOM (OOS-4), and no task modifies Phase 3.5/3.6 themselves beyond the named `detect-scanners.sh` extension (OOS-5).
