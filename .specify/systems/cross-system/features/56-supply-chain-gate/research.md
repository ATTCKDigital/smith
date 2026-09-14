# Research: Supply-Chain & License Review Pass for smith-build

All findings below are grounded in direct reads of this worktree's files
(paths/line numbers cited throughout), live commands run against this
worktree and against `/Users/dennisplucinik/Projects/goldcanna-inventory`
(this feature's real multi-manifest validation fixture, read-only, an
additional working directory available to this session), plus the
read-only pre-feature exploration report
(`.smith/vault/explore/explore-2026-09-13-supply-chain-gate.md`, status:
clear, 8 findings, no blocking conflicts). Feature 55
(`55-security-review-pass`) is **already shipped and merged** in this
worktree (its Phase 3.6, PR-body section, scripts, tests, and config key
all exist on disk exactly as its own `research.md`/`data-model.md`/
`plan.md` describe) — this is a live, current-state research pass, not a
forward projection. Section numbers below (§1-§9) are **local to this
document only**; qualify any future SKILL.md citation as "this feature's
`research.md` §N," per the numbering caution feature 55's own docs
established.

## §1 — Phase 3.6 boundaries; the exact Phase 3.7 insertion point

`skills/smith-build/SKILL.md` currently reads, in order (confirmed via
`grep -n "^## Phase" skills/smith-build/SKILL.md`):

- `## Phase 3.6: Security Review Pass` — **line 328**, content running
  through **line 424** (its closing sentence: "...proceed to Phase 4
  exactly like Phase 3.5 does today."). **Line 425 is currently blank.**
- `## Phase 4: Spec Updates (Subagent)` — **line 426**.

FR-1/FR-2 require Phase 3.7 to run "strictly after Phase 3.6 ... strictly
before Phase 4," so the insertion point is the currently-blank **line
425**, between Phase 3.6's closing content and the `## Phase 4:` heading —
the identical mechanic features 54 and 55 both used for their own
insertions (54 between the old Phase 3 and Phase 4; 55 between 3.5 and 4).
No renumbering of Phase 4 through 7 or any of their internal
cross-references is needed.

Phase 3.6's own internal shape (328-424) is a five-part structure worth
mirroring, adapted for two independent sub-layers instead of three
layers, and critically, with **no terminate branch at all** (Phase 3.7 has
none — FR-19/FR-20/OOS-3):

1. **Invocation** (330-338) — `BASE_BRANCH=$(.specify/scripts/bash/get-base-branch.sh)`
   threading. **Phase 3.7 diverges here**: FR-3/A-3 require
   `WORKTREE_PATH` (repo-root location) but explicitly NOT `BASE_BRANCH`
   as a scan-scope input — this phase's manifest discovery and license
   inventory are whole-repo, not diff-scoped. This divergence must be
   stated plainly in the new phase's own Invocation paragraph, not left
   implicit, since every phase before it (3, 3.5, 3.6, 4, 5.3, 5.3.1) is
   diff-scoped and a reader skimming SKILL.md top-to-bottom would
   otherwise default-assume the same pattern applies here.
2. **Step 1 — presence-detect** (340-352) — resolves `detect-scanners.sh`
   via the installed-path-preferred/repo-dev-fallback candidate loop, runs
   it once, writes a layer-disclosure scratch file unconditionally. Phase
   3.7 reuses this exact resolution idiom for the SAME script (extended
   per FR-27, §2 below), plus resolves the two NEW scripts this feature
   ships the identical way.
3. **Steps 2-4 — run each layer** (354-386) — each layer's own invocation,
   exit-code contract, and skip/degrade behavior stated explicitly. Phase
   3.7's Sub-layer D/L invocations are new content mirroring this shape,
   NOT this content itself (different scripts, different scope).
4. **Findings contract** (388-390) — one paragraph naming the shared
   field set. Phase 3.7 has its own contract (`data-model.md` §3, adapted
   per FR-17 — no `Layer: 1/2/3` field, a `sub-layer: D|L` field instead).
5. **Step 5 — merge + decide** (396-424) — Phase 3.6 has a real decision
   table and a terminate branch (406-418) alongside a flag branch
   (420-424). **Phase 3.7 has ONLY the flag-branch equivalent** — there is
   no decision table to evaluate and no terminate branch to write, because
   no config-driven tier exists (FR-20) and no finding of any severity, from
   either sub-layer, can terminate (OOS-3). This is the single largest
   structural simplification versus Phase 3.6, and is worth stating as an
   explicit "unlike Phase 3.6" sentence in the new phase's own prose so a
   future reader doesn't assume a missing terminate branch is an oversight
   rather than a deliberate v1 scope boundary (`data-model.md` §7 makes
   this explicit too).

## §2 — `secret-scan.sh` + `detect-scanners.sh`: style, arg conventions, exit codes, the exact loop line to extend

**`scripts/security/detect-scanners.sh`** (28 lines total) is exactly the
"pre-authorized extension point" the exploration and NFR-4 name. Its
entire detection logic is one loop:

```bash
for tool in gitleaks semgrep bandit; do
    if command -v "$tool" >/dev/null 2>&1; then
        printf '%s=present\n' "$tool"
    else
        printf '%s=absent\n' "$tool"
    fi
done
```

FR-27 requires extending — not forking — this exact loop. The **one-line
change** is the `for tool in gitleaks semgrep bandit; do` header:
appending the six new tool names to the SAME iterable (`for tool in
gitleaks semgrep bandit osv-scanner grype trivy pip-audit licensee syft;
do`) preserves the output contract byte-for-byte (`<tool>=present|absent`,
one line per tool, always exit 0, `set -uo pipefail`, no `-e`) with zero
other changes to the file. `tests/security/test_detect_scanners.sh`'s
existing 5 cases (all-absent, all-present, per-tool-subset combinations)
need new cases added for the six new tools, following its own
`make_path_with`/`run_case` idiom verbatim (§6 below) — the file stays
well under 300 lines even with 9 tools' worth of new case combinations if
cases are chosen to cover representative subsets rather than the full 2^9
combinatorial space (the existing 5 cases already demonstrate this
economy: they don't enumerate all 8 combinations of 3 tools either).

**`scripts/security/secret-scan.sh`** (138 lines) establishes the bash
CLI wrapper conventions worth reusing for Sub-layer D/L's own entry
points, where applicable:

- `set -uo pipefail` (not `-e`) — line 14, so defensive
  `cmd || fallback` chains can run to completion.
- **Engine resolution**: `SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)` then
  `ENGINE="$SCRIPT_DIR/secret_scan.py"`, overridden to
  `$HOME/.smith/scripts/security/secret_scan.py` if that installed path
  exists (lines 16-20) — installed-path-preferred, repo-dev fallback,
  the SAME direction as Phase 3.6's own SKILL.md-level candidate loop
  (§1 above) but implemented inside the wrapper script itself here rather
  than in the caller.
- **Exit-code contract, stated in the header comment** (line 12): `0`
  clean; `1` findings present (stdout, not a failure — the caller parses,
  never branches on exit code alone for pass/fail); `2` internal/usage
  error. Phase 3.7's own scripts should adopt the identical three-way
  contract for consistency across every `scripts/security/*` entry point,
  even though Sub-layer D/L never "fail the build" on any outcome (FR-10 /
  no terminate path) — the exit code is still a clean machine-readable
  signal for the SKILL.md-level caller to log, distinct from "did this
  layer find anything."
- **Defensive config reads**: a single `python3 -` heredoc invocation
  (78-96) reads `.smith/config.json`, gated by a two-step
  file-exists-AND-valid-JSON-AND-`isinstance(config, dict)` check, printing
  nothing and exiting 1 on any failure so the bash side's
  `CONFIG_EXCLUDES`/`CONFIG_ALLOWLIST` arrays simply stay empty — the
  identical "silent-skip is the universal fallback" convention
  `security-guard-mcp-browser.sh` established (feature 55's own
  `research.md` §7), reused here for `supply_chain.excludes`/
  `supply_chain.timeout_seconds`/`supply_chain.license_policy` reads.
- **Path-not-string-interpolated into Python source** (73-74's own
  comment): the config path is passed via `sys.argv[1]`, never f-string'd
  into the heredoc body — the same discipline this feature's own config
  reads (and manifest-path handling generally, since manifest paths are
  attacker-influenceable file-tree content in a way `.smith/config.json`'s
  own path is not) must preserve.
- **`secret_scan.py`'s own header docstring convention** (lines 1-23): a
  one-line summary, a "Usage:" block, an "Output:" paragraph stating the
  exact machine-parseable line format, and an "Exit codes" line mirroring
  the wrapper's own contract — worth reusing verbatim as the doctring
  shape for `dependency-scan.py`/`license-inventory.py`.

## §3 — `scripts/install.sh`'s security stanza: NAMES FILES, does not glob the directory (concrete finding)

`scripts/install.sh:220-231`:

```bash
# ---------- copy security scripts ----------
# Feature 55-security-review-pass: secret-scan.sh/secret_scan.py/
# detect-scanners.sh are not parsers, so this stanza is unconditional
# (not gated by --no-parsers) — mirrors the smith-index/
# create-active-workflow.sh staging precedent just above.
info "Copying security scripts"
mkdir -p "$SMITH_HOME/scripts/security"
cp "$REPO_ROOT/scripts/security/secret-scan.sh" "$SMITH_HOME/scripts/security/secret-scan.sh" 2>/dev/null || true
cp "$REPO_ROOT/scripts/security/secret_scan.py" "$SMITH_HOME/scripts/security/secret_scan.py" 2>/dev/null || true
cp "$REPO_ROOT/scripts/security/detect-scanners.sh" "$SMITH_HOME/scripts/security/detect-scanners.sh" 2>/dev/null || true
chmod +x "$SMITH_HOME/scripts/security/"*.sh 2>/dev/null || true
```

**This resolves the task's explicit question decisively: the stanza names
each file with its own individual `cp` line — it does NOT `cp -r` or glob
the source directory.** Only the trailing `chmod +x "..."*.sh` line uses a
glob, and only for making `.sh` files executable, not for discovering
which files to copy. Consequence for this feature: **every new file this
feature adds under `scripts/security/` needs its own explicit `cp` line
added to this stanza** — `dependency-scan.py`, `license-inventory.py`, and
any thin `.sh` wrapper(s) (`plan.md` §"file-by-file" resolves the wrapper
question, §7 below documents the options) will NOT be installed to
`$SMITH_HOME/scripts/security/` merely by existing in the repo tree; a
project running `/smith-update` after this feature ships would silently
keep using the OLD `~/.smith/scripts/security/` (missing the new
scripts) unless this stanza is extended. This is a real, concrete
plan-level gap this research pass surfaces (mirroring feature 55's own
`.smith/config.json` seeding-gap finding in its `research.md` §6) — it is
not one of spec.md's six named gate items, it is a mechanical consequence
of how `install.sh` is actually written, discovered only by reading the
file directly rather than assuming a directory-glob convention.

The comment block (221-224) is itself a second reusable precedent: it
names which feature introduced the stanza and why it's unconditional
(not gated by `--no-parsers`) — Phase 3.7's own new `cp` lines should get
an analogous one-line comment naming `56-supply-chain-gate` so a future
reader can trace provenance without archaeology.

## §4 — Config seeding precedents: `templates/config.default.json` + the `§5.1b`/`§5.1c` → `§5.1d` idiom

`templates/config.default.json` (10 lines shorter than security_review's
own addition made it) currently has five top-level keys in this exact
order: `_comment`, `security` (the orphaned BANK-027 block), `security_review`
(feature 55, lines 12-25), `context_budget` (26-29), `ledger` (30-58).
FR-28 adds a sixth, `supply_chain` — a SIBLING of `security_review`, not
nested (Q2/FR-28 both state this explicitly; nesting under
`security_review` would incorrectly imply this pass shares that key's
closed, tier-bearing schema). The natural insertion point, grouping the
two security-adjacent keys together exactly as `security_review` itself
was grouped after `security`, is: **after `security_review`'s closing
`}` (line 25), before `context_budget` (line 26)**.

Two live, already-shipped precedents exist for non-destructively seeding
a NEW top-level `.smith/config.json` key into every project — not just
brand-new ones — because `hooks/session-start-logger.sh`'s whole-file
copy-if-absent seeding (the mechanism that makes brand-new projects get
`templates/config.default.json` verbatim) never touches a `.smith/config.json`
that already exists:

- **`skills/smith/SKILL.md:300-331`** (inside `#### 4.1 Scaffold Project
  Directories`, no separate lettered heading of its own in THIS file —
  `/smith` init's Phase 4 isn't lettered `5.1x` the way `/smith-update`'s
  Phase 5 is) — a `[ -f "$PWD/.smith/config.json" ]` bash gate wrapping a
  `python3 - "$PWD/.smith/config.json" << 'PYEOF'` heredoc: load-if-exists
  (`except Exception: config = None`), `if isinstance(config, dict) and
  "security_review" not in config:` merge the full default shape, re-dump
  with `indent=2` plus a trailing newline. Absent file → left absent
  entirely (the whole-file template copy already handles brand-new
  projects).
- **`skills/smith-update/SKILL.md:307-344`**, headed **`### 5.1c Seed
  \`security_review\` in \`.smith/config.json\`**` — the identical
  python3 read-modify-write body, applied at `/smith-update` refresh time,
  with an explicit three-line decision rule stated in prose immediately
  above the code block (311-313): key present (any shape) → no-op; file
  exists, key absent → merge; file absent entirely → leave absent.
  Immediately preceded by **`### 5.1b Seed \`browser_verification.urls\`
  in \`.smith/security-config.json\`** (274-305, feature 53's own
  precedent, seeding a DIFFERENT file) and immediately followed by
  **`### 5.2 Run \`/smith-index --migrate-templates\`** (346).

**The task's framing cites these as "§5.1b/§5.1c precedents for a
§5.1d"** — confirmed exactly: `§5.1b` is feature 53's
`.smith/security-config.json` seed, `§5.1c` is feature 55's
`.smith/config.json` `security_review` seed, and **`§5.1d` is the next
free letter**, immediately following `§5.1c` (ending at line 344) and
before `§5.2` (346) — insertion point is the currently-blank line 345.
`skills/smith/SKILL.md` needs the mirrored, unlettered addition in the
same place its own `security_review` paragraph landed (immediately after
line 331's closing `fi`, before "Copy from `~/.claude/skills/smith/`:" at
333) — `/smith` init's Phase 4 doesn't use `5.1x` lettering itself, so no
new heading/letter is needed there, only the same paragraph+heredoc
pattern repeated for `supply_chain`.

## §5 — `smith-audit`'s Dependencies item (exact line) + the item-upgrade style precedent

`skills/smith-audit/SKILL.md:115`, inside `## Sub-Audit Orchestration`
(105), item 7 of an 11-item numbered list (109-119):

```
7. **Dependencies** (`smith-audit dependencies`) — outdated packages, CVEs, unused deps
```

A one-line bullet with zero implementation behind it today — exactly the
"one-line placeholder" the Problem Statement (item 3) and FR-25 describe.
Two items in the SAME list already demonstrate the exact "upgrade a
one-liner into a fuller description naming the concrete mechanism it now
invokes" pattern this feature's FR-25 needs to replicate for item 7:

- **Item 6 (UX)**, extended by feature 53 to state precisely: "Attempts
  MCP-first authenticated bridge-mode verification when tools are
  present, `mcp_mode` resolves to `extension`, and the session is
  interactive ...; otherwise falls back silently to the unauthenticated
  approach below, unchanged."
- **Item 10 (SEO)**, extended the same session with: "Same MCP-first-with-
  fallback contract as the UX sub-audit above (item 6): attempt
  authenticated bridge-mode verification under the same three conditions,
  otherwise fall back to the unauthenticated crawl unchanged."

Both extensions follow the same shape: name the concrete script/mechanism
now backing the bullet, state the fallback/skip condition explicitly, and
cross-reference a sibling item by number rather than restating shared
logic. Item 7's own upgrade (FR-25/FR-26) should follow this exact shape:
name `detect-scanners.sh` (extended) plus the two new
Sub-layer D/L scripts by path, state that it runs whole-project (not
diff-scoped, consistent with `smith-audit`'s existing on-demand model —
FR-3/FR-25's own framing), and state plainly that no separate
implementation exists (FR-26) — closing feature 55's NFR-4 intent, which
named this exact future feature ("F2, out of scope here") as
`detect-scanners.sh`'s second consumer.

## §6 — `tests/security/*` harness patterns to reuse

Both existing files are DIRECTLY reusable structural templates — no new
harness idiom needs inventing:

- **`tests/security/test_detect_scanners.sh`** (104 lines): `mktemp -d`
  scratch-`$PATH` construction per case (`make_path_with`, stub
  executables that `exit 0`), `run_case()` asserting exact stdout against
  an expected multi-line string AND exit code 0, `PASS`/`FAIL` counters, a
  `SUMMARY:` line, `[ "$FAIL" -eq 0 ]` exit-status gate. **Self-detects
  which shell is running the TEST script itself**
  (`[ -n "${ZSH_VERSION:-}" ]`) and resolves that interpreter's absolute
  path BEFORE narrowing `$PATH` for a case (so the interpreter binary
  itself is still resolvable under the scratch `$PATH`) — this exact
  guard is needed again for any new dual-shell test this feature adds.
  Extending this file's own cases for the six new
  `osv-scanner`/`grype`/`trivy`/`pip-audit`/`licensee`/`syft` tools is a
  direct, mechanical extension of `make_path_with`/`run_case` — no new
  helper needed.
- **`tests/security/test_secret_scan.sh`** (367 lines): adds
  `make_repo()` (a throwaway `git init`-ed repo per case, matching
  `tests/get-base-branch.test.sh`'s own idiom) and `scan()`/`scan_exit()`
  wrappers that `cd` into the repo and invoke the wrapper script under the
  same self-detected interpreter, plus `assert_eq`/`assert_contains`/
  `assert_not_contains` helpers. **Every planted secret is a documented,
  structurally-valid-but-never-issued canary** (e.g. AWS's own published
  example key `AKIAIOSFODNN7EXAMPLE`), each with an inline  <!-- smith-secret-scan: allow -->
  `# smith-secret-scan: allow` comment on the SAME line the canary lives
  on in the test's own source — so the test file doesn't trip Phase 3.6's
  own secret scan when it scans itself. **The identical
  self-allowlisting discipline applies to any planted CVE-shaped or
  license-shaped fixture this feature's own tests plant** (a fake
  `package-lock.json` naming a real-looking vulnerable version string is
  not secret-shaped, so no marker is needed there — but a planted fixture
  should still never resemble a real credential or a real unpatched
  production dependency string, mirroring the same "never something that
  could be mistaken for the real thing" discipline).

Neither file drives its target through a JSON-stdin protocol (that's the
`tests/hooks/test_security_guard_mcp_browser.sh` PreToolUse-hook style,
not applicable here — neither script this feature adds is a hook).

## §7 — Per-ecosystem scan invocations: empirically verified against `goldcanna-inventory`

**Tool presence on this dev machine, verified live** (`command -v <tool>`
for each): `osv-scanner`, `trivy`, `grype`, `pip-audit`, `licensee`,
`syft`, `gitleaks`, `semgrep`, `bandit` are **all absent**. Only `npm` and
`python3` are present. **`timeout` and `gtimeout` are BOTH absent too** —
confirmed directly, not inferred (§7.4 below). This matches (and, for the
six new tools, extends) the exploration's own A-2-equivalent finding for
feature 55 and this feature's own A-5 note that `trivy` is absent
locally despite being `goldcanna-inventory`'s actual CI scanner.

### §7.1 — `npm audit --json --package-lock-only`: live-verified output shape

Run directly against `goldcanna-inventory/frontend` (real manifest,
`package-lock.json` present, this session, 2026-09-13):

```
$ npm audit --json --package-lock-only   # from goldcanna-inventory/frontend
exit code: 1
metadata.vulnerabilities = {'info': 0, 'low': 1, 'moderate': 5, 'high': 19, 'critical': 3, 'total': 28}
```

This is a direct, live confirmation of FR-11/US-2/SC-3's exact claims: a
real project with only pre-existing (not maliciously planted) advisories
produces **exit code 1** — non-zero — while `metadata.vulnerabilities` is
valid, well-formed JSON with exactly the bucket keys FR-11 names
(`info`/`low`/`moderate`/`high`/`critical`/`total`). Parsing MUST read
this object directly and MUST NOT branch on the exit code for
pass/fail — confirmed empirically, not just per the exploration's
prior claim. `moderate` → this feature's `Medium` (5 findings in this
real run); `info` → folded into the same low-severity count as `low`
(0 + 1 = 1 in this run). `--package-lock-only` avoids touching
`node_modules/` (none of `goldcanna-inventory/frontend`'s installed
packages were modified by this call) but the call **did reach npm's
remote advisory database** — this session's sandboxed environment
happened to have outbound network access, so the "needs network" claim
(FR-9) was exercised for real, not merely asserted.

**A real edge case this pass surfaced, not previously named**: `npm
audit`'s advisory-lookup, and therefore FR-7's "matching lockfile"
requirement, is specific to **`package-lock.json` (or
`npm-shrinkwrap.json`)** — npm's own lockfile format. A `package.json`
whose ONLY lockfile is `yarn.lock` or `pnpm-lock.yaml` has "a lockfile"
under FR-4's broader manifest-discovery definition, but does **not**
satisfy FR-7's precondition for the `npm audit` FALLBACK path
specifically (`npm audit` cannot read those formats directly, and
converting one would require an `npm install`-style write this feature
must never perform). Manifest discovery should record which lockfile
format(s) are present per npm manifest so Sub-layer D can distinguish
"ENOLOCK, no lockfile at all" (FR-7's stated skip reason) from "lockfile
present, but not in a format `npm audit` can read" — a second,
worth-disclosing skip reason the current FR text doesn't name explicitly
but this research pass's live testing surfaces as real. Both
`goldcanna-inventory` npm manifests (`frontend/`, `menu-generator/`) use
`package-lock.json` (confirmed via direct `find`), so this edge case
doesn't block the primary validation fixture, but a future consuming
project using Yarn/pnpm would hit it. When `osv-scanner`/`trivy` ARE
present (FR-8), this gap doesn't apply — both tools natively read
`yarn.lock`/`pnpm-lock.yaml` — so this is specifically a fallback-path
(FR-9) limitation, not a Sub-layer D limitation overall.

### §7.2 — `osv-scanner`/`trivy`/`grype`: invocation shapes (documented, not locally testable)

None of the three are installed on this machine (§7, confirmed via
`command -v`), so their JSON output can't be empirically re-verified the
way `npm audit`'s was — documented here from their own published CLI
contracts for the orchestrator's implementation to target, flagged
explicitly as not machine-verified in this research pass (the SAME
caveat feature 55's own `research.md` applied to `trivy`):

- **`osv-scanner --format json <path>`** (a directory or a specific
  lockfile) — scans every recognized manifest under `<path>` in one pass,
  multi-ecosystem (npm, PyPI, Go, Cargo, and more) — this is exactly why
  FR-8 prefers it FIRST when present: one invocation covers every
  discovered manifest regardless of ecosystem, unlike the FR-9 fallback's
  per-manifest, per-ecosystem-tool loop.
- **`trivy fs --format json --scanners vuln <path>`** — filesystem-mode
  scan, also multi-ecosystem, also one invocation for the whole repo tree.
  `goldcanna-inventory`'s own CI (`.github/workflows/publish.yml:158-178,235-241`,
  confirmed via direct read) uses `trivy-action` with SARIF output
  (`--format sarif` equivalent) for GitHub code-scanning integration, NOT
  the JSON format this feature needs — Sub-layer D should invoke `trivy`
  directly with `--format json`, independent of how `goldcanna-inventory`'s
  own CI happens to invoke it; the SARIF-vs-JSON distinction is worth a
  one-line implementation note so a future maintainer doesn't assume the
  CI invocation shape is what this feature should copy verbatim.
- **`grype <path> -o json`** — FR-27 adds `grype` to `detect-scanners.sh`'s
  detection list per NFR-4, but FR-8 only names `osv-scanner`/`trivy` as
  the preferred multi-ecosystem pair ("`osv-scanner` first, `trivy`
  second, when both are present") — `grype` has no defined invocation
  role in the FR text beyond presence-detection. This is worth flagging
  for the gate/build phase as a minor spec-plan gap (not one of the six
  named A-6 items): either `grype` is detected but genuinely unused by
  v1's invocation logic (matching FR-8's literal wording), or it's a
  documented THIRD fallback tier the FR text simply didn't spell out.
  `plan.md`'s Architecture Summary resolves this explicitly rather than
  silently picking one reading.

### §7.3 — `pip-audit -f json`: invocation shape (documented, not locally testable)

Also absent locally. `pip-audit -f json` (or `--format json`) against a
`requirements.txt`, or `pip-audit -f json` run through the project's own
`poetry run` wrapper for a `pyproject.toml`/`poetry.lock` manifest so
locked versions resolve correctly (the SAME "use the project's own
environment, never system/global" principle FR-15 states for the license
inventory applies equally here, though FR-9's text only states it
explicitly for licenses — worth carrying the same discipline into
Sub-layer D's `pip-audit` invocation for consistency, flagged for
`plan.md`). `pip-audit` requires network access identically to `npm
audit` (it queries the PyPI Advisory Database / OSV by default) — no
offline exemption, same FR-12 timeout/offline handling applies uniformly.

### §7.4 — Timeout wrapper: `timeout`/`gtimeout` are BOTH absent on this dev machine (empirically confirmed) — recommend the python3 subprocess approach

Directly confirmed via `command -v timeout gtimeout` on this development
machine (Darwin/macOS): **neither is on `$PATH`**. This is not a
theoretical macOS gap — GNU coreutils' `timeout` ships on Linux by
default but NOT on macOS, and `gtimeout` (the Homebrew-`coreutils`-prefixed
equivalent) is only present if a user has explicitly `brew install
coreutils`, which this actual development machine has not done. A bash
script that unconditionally calls `timeout 60 npm audit ...` would fail
with "command not found" on THIS machine — an immediate, guaranteed
regression on the exact platform this feature is being developed on.

**Three options considered:**

1. **`command -v timeout || command -v gtimeout` with a bash fallback**
   (e.g. a `( cmd & pid=$!; ( sleep N; kill $pid ) & wait $pid )`
   background-and-kill pattern when neither exists) — portable in
   principle, but the background+kill pattern is notoriously fragile
   across bash versions for correctly reaping the child AND the watcher
   subshell, doesn't cleanly capture the child's stdout/exit code in every
   shell, and would need its OWN bash+zsh dual-shell test coverage
   (NFR-2) independent of anything else this feature ships — real
   implementation risk for marginal benefit given option 3 below.
2. **Always `brew install coreutils` as a build prerequisite** — rejected
   outright: this feature must never add an installed dependency
   requirement (the same non-negotiable constraint FR-9 states for
   `semgrep`/`bandit`/every optional tool: "never added as an installed
   dependency of Smith or of any consuming project").
3. **`python3 subprocess.run(..., timeout=N)`** — Python's own standard
   library `subprocess.run` accepts a `timeout` keyword directly,
   raising `subprocess.TimeoutExpired` on expiry (catchable, clean,
   already the exact mechanism CPython uses across Linux/macOS/Windows
   with NO platform-specific binary dependency) and killing the child
   process tree on timeout without any bash-level process-group
   bookkeeping.

**Recommendation: option 3, the `python3 subprocess.run(..., timeout=N)`
approach — decided and justified here, not deferred, since this is an
implementation-technique choice, not one of spec.md's six named gate
items.** Justification: (a) `python3` is a REQUIRED dependency of this
feature regardless — the orchestrator (`dependency-scan.py`) is written
in Python per the task's own framing and per FR-15's `importlib.metadata`
requirement for Sub-layer L, so no new interpreter dependency is
introduced by choosing this path; (b) it is empirically the ONLY
zero-additional-dependency option that reliably works on THIS actual
development machine today, confirmed by direct `command -v` checks rather
than assumed; (c) it sidesteps bash/zsh dual-shell timeout-semantics
parity entirely (NFR-2 still applies to any `.sh` WRAPPER this feature
ships, but the actual timeout enforcement lives in the Python engine
where it behaves identically regardless of which shell invoked the
wrapper); (d) `subprocess.run(..., timeout=N)` cleanly captures stdout/
stderr/returncode even on the timeout path (via the exception's own
`.stdout`/`.stderr` attributes on partial output, or simply by treating a
`TimeoutExpired` catch as "no usable output, mark this manifest/tool
skipped-with-disclosure" per FR-12), which is a strictly cleaner contract
than parsing a background-and-kill pattern's partial output.

## §8 — Thin `.sh` wrapper question: two competing precedents, `plan.md`'s job to decide

The task's framing ("thin `.sh` wrappers IF consistent with F1 style —
evaluate: F1 used sh wrapper + py engine; mirror") asks this research
pass to surface the evidence; `plan.md` makes the call (this is an
implementation-shape decision, not one of the six gate items).

**Two DIFFERENT existing wrapper shapes exist in this repo, not one:**

1. **`secret-scan.sh` (138 lines) — a HEAVY wrapper.** Real bash-side
   logic: diff-scope resolution (`git diff`/`git ls-files`), config
   reads, exclude/allowlist glob assembly, gitleaks-JSON merge — the
   Python engine (`secret_scan.py`) is invoked only once scope and flags
   are fully resolved. This shape earns its weight because bash is
   naturally good at git-plumbing and PATH-family logic, and because a
   SEPARATE, later gitleaks-merge step needs shell-level JSON
   concatenation the wrapper itself performs.
2. **`scripts/smith-index/run.sh` (30 lines) — a MINIMAL pass-through
   shim.** Its own header comment states its entire purpose plainly:
   "This script exists so callers ... can invoke the indexer without
   knowing about the underlying Python module. All flag parsing happens
   inside `run.py`." Concretely: resolve its own directory, verify
   `run.py` exists (exit 2 if not), verify `python3` is on `$PATH` (exit 2
   if not), then `exec python3 "$PY_RUN" "$@"` — literally nothing else.
   Every flag (`--check`, `--system`, `--migrate-templates`, `--incremental`,
   etc.) is parsed entirely inside `run.py`'s own `argparse`.

**Sub-layer D/L's orchestrators are structurally closer to case 2, not
case 1**: neither `dependency-scan.py` nor `license-inventory.py` needs
ANY bash-side pre-processing before invoking Python — there is no
`git diff` scope to resolve (FR-3: whole-repo, not diff-scoped), no
shell-level JSON-merge step comparable to gitleaks' (each sub-layer's own
scanner-hierarchy/normalization logic is naturally a Python concern
already, since it needs `subprocess.run(timeout=...)`, JSON parsing, and
structured data merging — all things Python does natively and bash does
awkwardly). The ONE thing a wrapper still usefully provides — matching
BOTH existing precedents — is a **stable, `chmod +x`-executable entry
path independent of exactly how the caller invokes it**, so
`skills/smith-build/SKILL.md`'s candidate-path-resolution loop (§1
above, mirroring Phase 3.6's own `for cand in ...` idiom) and
`smith-audit`'s own invocation (FR-26, "no forked/duplicated logic") can
both resolve and call the SAME script path without either needing to know
it's a Python file versus a shell script.

**This research pass's finding, for `plan.md` to adopt or override**: a
`run.sh`-style minimal pass-through wrapper (not a `secret-scan.sh`-style
heavy wrapper) is the better-fit precedent for both `dependency-scan.py`
and `license-inventory.py` — each gets its own ~15-20 line `.sh` shim
(`dependency-scan.sh`, `license-inventory.sh`) doing ONLY: resolve its own
directory, verify the `.py` file and `python3` both exist (exit 2
otherwise, matching `secret-scan.sh`'s own exit-2-on-setup-failure
convention), then `exec python3 "$THIS_DIR/<engine>.py" "$@"` — full flag
parsing (`--config`, `--timeout-seconds`, any future flag) lives entirely
in each `.py` file's own `argparse`, exactly like `run.py`. This keeps
the "F1 style: sh wrapper + py engine" naming convention intact (so
`detect-scanners.sh`'s extension, `secret-scan.sh`, `dependency-scan.sh`,
and `license-inventory.sh` all present the SAME `.sh`-entry-point shape to
every caller) while avoiding inventing bash-side logic these two scripts
don't actually need.

## §9 — The six A-6 gate items: options + evidence + recommendation (not decided here)

Unlike feature 55's own `research.md` §9 (whose six items were genuinely
open at research time, resolved later by a dedicated `questions.md`
gate), **spec.md's own A-6 already states a recommendation for each of
these six items AND states the FRs above are written to "hold under
[the] recommended resolution."** This section restates each item in the
options+evidence+recommendation shape the task requests, cross-checked
against this research pass's own file reads — every recommendation below
is corroborated by direct evidence found during this pass, not merely
carried forward from the exploration unchecked. `data-model.md`/`plan.md`
write their concrete content using each recommended resolution as the
working default (since spec.md's own FRs already encode it), while this
section preserves the options+evidence framing per the task's explicit
instruction not to decide here.

**Q1 — Phase placement: new Phase 3.7, vs. extending Phase 3.6.**
- *Option A (recommended, per spec A-6.1).* A new, dedicated Phase 3.7.
- *Option B.* Extend Phase 3.6 itself with a fourth "layer."
- *Evidence, corroborated this pass*: Phase 3.6's own decision table
  (`data-model.md` §5 in feature 55, confirmed still exactly as shipped
  by reading `skills/smith-build/SKILL.md:396-418` directly) is
  secret-specific and closed — its terminate branch is keyed to "any
  Critical Layer 1 (secret) finding," a concept that doesn't generalize
  to a CVE or a license-policy hit without either overloading that
  table's semantics or requiring a parallel, confusing second decision
  path bolted onto the same phase. §1 above independently confirms line
  425 is a clean, already-blank insertion point requiring zero
  renumbering — the mechanical cost of Option A is genuinely zero.

**Q2 — Config home: new top-level `supply_chain` key, vs. nesting under `security_review`.**
- *Option A (recommended, per spec A-6.2).* New top-level `supply_chain` key.
- *Option B.* Nest under `security_review.supply_chain` (or similar).
- *Evidence, corroborated this pass*: `templates/config.default.json:12-25`
  (read directly, §4 above) shows `security_review`'s actual shipped
  shape — `enforcement_tier`, `review_model`, `layers`, `excludes`,
  `allowlist_globs` — every field either tier-bearing or scanner-layer-
  toggle-shaped. Nesting `supply_chain` (which FR-20 requires to carry NO
  tier-equivalent field at all) inside this schema would either force an
  awkward `security_review.supply_chain.enforcement_tier`-shaped
  non-field, or silently imply supply_chain inherits `enforcement_tier`
  semantics it explicitly does not have.

**Q3 — Enforcement posture: flag-only v1, vs. a config-driven terminate tier.**
- *Option A (recommended, per spec A-6.3).* Flag-only, no terminate path
  of any kind.
- *Option B.* A `block_on_critical`-equivalent tier, mirroring Phase
  3.6's own.
- *Evidence, corroborated this pass*: Phase 3.6's terminate branch exists
  BECAUSE a secret reaching `git commit` is a one-way, irreversible harm
  the instant it's pushed (feature 55's own Problem Statement). A CVE in
  an already-declared dependency is qualitatively different — it was
  already present before this build, is not newly introduced by this
  diff (OOS-1/OOS-2's own framing), and §7.1-§7.3 above independently
  confirm this pass's own scanners require live network reachability and
  external advisory-database freshness in a way Phase 3.6's regex-based
  Layer 1 scan does not — a transient network hiccup or an unpublished
  CVE at scan time would make a terminate-on-Critical tier's "coverage"
  meaningfully less trustworthy than Layer 1's own unconditional secret
  gate, undermining the analogy Option B would rest on.

**Q4 — License policy default: inventory-only (empty allow/deny), vs. a shipped default deny list.**
- *Option A (recommended, per spec A-6.4).* Empty `allow`/`deny` by default.
- *Option B.* Ship a default deny list (e.g. common copyleft licenses).
- *Evidence, corroborated this pass*: the live `goldcanna-inventory`
  license-inventory run (§10 note: see `data-model.md` §4 for the
  exact counts) surfaces a genuinely wide license spread even in one
  real project's `node_modules/` tree — a default deny list authored by
  this feature would encode a specific legal opinion (e.g. "GPL is never
  acceptable") that varies by project, by jurisdiction, and by
  organization; shipping one unreviewed would misrepresent this feature's
  own scope (an inventory tool, not a legal-policy tool).

**Q5 — `smith-bugfix` inclusion: excluded (per spec A-6.5/OOS-1), vs. a lightweight pre-commit CVE check.**
- *Option A (recommended, per spec A-6.5).* No part of this feature runs
  in `smith-bugfix`.
- *Option B.* A cheap, Layer-1-secret-scan-style pre-commit gate, mirroring
  how feature 55 DID extend `smith-bugfix` for secrets specifically
  (`skills/smith-bugfix/SKILL.md`, confirmed via `docs/security-model.md:107`,
  "`smith-bugfix` runs Layer 1 only ... immediately before its commit
  step").
- *Evidence, corroborated this pass*: feature 55's own `smith-bugfix`
  extension exists BECAUSE a leaked secret is time-sensitive and
  irreversible the moment it's pushed — the exact asymmetry OOS-1 already
  names. A dependency CVE is not introduced by a bugfix's diff at all (the
  vulnerable package was already declared in the manifest before this
  bugfix); running a whole-project scanner-hierarchy pass (§7.1-§7.3's own
  network/timeout dependencies) inside `smith-bugfix`'s deliberately
  lightweight, fast pipeline would reintroduce exactly the "why does a
  one-line bugfix take 60+ seconds and need network access" friction this
  feature's own FR-12/NFR-6 work hard to bound for `smith-build`, for a
  pipeline where the harm-timing argument doesn't hold in the first place.

**Q6 — `smith-audit` wiring: upgrade the Dependencies sub-audit to call this feature's scripts, vs. leave it a placeholder.**
- *Option A (recommended, per spec A-6.6).* Upgrade item 7 to invoke the
  same scripts.
- *Option B.* Leave `smith-audit`'s Dependencies item as-is; this feature
  ships `smith-build`-only.
- *Evidence, corroborated this pass*: §5 above confirms item 7
  (`skills/smith-audit/SKILL.md:115`) is TODAY a genuine one-line
  placeholder with zero backing implementation, and that feature 55's own
  NFR-4 explicitly named "the future dependency-CVE/SCA feature (F2, out
  of scope here)" as `detect-scanners.sh`'s SECOND intended consumer —
  this repo's own prior feature already pre-committed to this outcome in
  writing. Items 6 and 10 in the SAME sub-audit list (§5 above) already
  demonstrate the "upgrade a placeholder bullet into a real invocation,
  reusing an existing mechanism, in the same session that mechanism
  shipped" pattern — Option A is the well-precedented default, not a
  novel extension.
