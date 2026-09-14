---
feature: 59-wordpress-aware-index
primary_system: cross-system
branch: 59-wordpress-aware-index
status: planned
---

# Implementation Plan: WordPress-Aware Index Defaults

## Technical Context

- **Repo**: Smith skills distribution (this repo). No application runtime
  — deliverables are one new Python module (`scripts/smith-index/
  wp_defaults.py`), targeted additions to `scripts/smith-index/run.py`,
  one new `cp` line in `scripts/install.sh`, two SKILL.md doc touches,
  one `CHANGELOG.md` entry, and three new test files.
- **`run.py` is already large** (1664 lines going in). Every addition in
  this plan is either (a) a small, pure, independently-testable function
  lifted OUT into a new sibling module (`wp_defaults.py`, Part A), or (b)
  a small method added to the existing `IndexRun` class right next to the
  state it needs (`prune_stale_index()`, Part B — placed immediately after
  `write_schema_version_marker()`/`cleanup()`, the same class-methods
  region it needs to read `self.files_dir`/`self.systems_dir`/`self.
  systems`/`self.logger` from), or (c) a ~10-line addition inside an
  existing method (`_load_overrides()`, Part C). No existing function is
  restructured or moved; net new lines in `run.py` itself are the smallest
  of the three parts (Part B + Part C only — Part A's substance lives in
  the new module).
- **No `constitution.md` exists in this repo** — matching every prior
  feature's plan.md in this worktree (54-58).
- **`BANK-028` is binding** for origin and both gotchas (per this
  feature's task framing) — `.smith/vault/bank/2026-09-14_144500-
  wordpress-aware-index-defaults.md`. Its `feature_branch:
  "59-wordpress-aware-index"` and `status: in-progress` frontmatter match
  this feature exactly; no re-derivation of intent was needed.
- **Endpoint — RESOLVED**: the questions gate closed 2026-09-14
  (`questions.md`, status ANSWERED) with the three named gate decisions
  (Q1-Q3) accepted exactly as recommended, plus one additional
  directly-evaluated decision (Q4: do NOT wire `/smith init` into
  `/smith-index` as part of this feature). `spec.md`'s own Assumptions
  (A-2/A-3) record both outcomes; this plan's content is written as
  concrete and unconditional.

## Constitution Gates

**N/A — no `constitution.md` or `.specify/memory/constitution.md` exists in
this repo**, so there are no constitution-derived gates to check. File-size
discipline is enforced via this plan's own File Size Policy section
instead, the same substitution every prior feature in this worktree
already used.

## Architecture Summary

Three independent, additive surfaces inside one file family:

**1. `scripts/smith-index/wp_defaults.py` — NEW module** (FR-1/FR-2).
Two module-level constant tuples (`WP_CORE_DIRS`, `WP_CORE_ROOT_FILES`)
and two pure functions (`detect_wordpress(project_root)`,
`wp_exclusion_rules()`). No imports beyond `pathlib.Path` and
`__future__.annotations`. No CLI entrypoint needed — it is imported, never
run standalone (unlike `path-resolver.py`, which supports both).

**2. `scripts/smith-index/run.py` — three additions**:
- A new graceful-degrade import block for `wp_defaults` (mirroring the
  existing `path_resolver`/`meta_describe` pattern, resolved from
  `THIS_DIR` — FR-5), placed directly after the existing `meta_describe`
  import block (~line 155).
- `mode_init_system_paths()` (line 1544) gains the WP-detection branch
  (FR-3/FR-4) — roughly 12 new lines inside the existing function, no
  restructuring of its existing per-top-level-directory loop beyond one
  new `if name in wp_dir_names: continue` skip line.
- `IndexRun` gains a new method `prune_stale_index()` (FR-7/FR-8/FR-12/
  FR-13), placed after `write_schema_version_marker()` and before
  `cleanup()` (its natural place in the existing "final manifests /
  cleanup" method cluster). `mode_full()` (line 1076) gains a 4-line call
  site (FR-9/FR-10/FR-11) between `write_schema_version_marker()` and
  `cleanup()`.
- `_load_overrides()` (line 778) gains ~10 lines (FR-14/FR-15/FR-16/
  FR-17) inside its existing `try` block, after the successful
  `json.load()` and before `return`.

**3. `scripts/install.sh`** gains one new `cp` line (FR-6) in the existing
smith-index staging block.

Plus two SKILL.md documentation touches (FR-18/FR-19) and one
`CHANGELOG.md` entry (FR-20).

## Reuse-before-create (exact components reused, not reinvented)

- **The stale-`.meta` predicate** (`_refresh_full_aggregations()`, `run.py`
  lines 1336-1340: `if not source_path.exists(): continue` /
  `if system == "excluded": continue`) — `prune_stale_index()` reuses this
  EXACT condition (source missing OR resolves excluded), just inverted
  into a deletion trigger instead of an aggregation-skip, and run for full
  rebuilds instead of only incremental's re-aggregation pass. This is the
  single most direct piece of reuse in this feature — Part B does not
  invent a new staleness definition, it operationalizes one that already
  exists in this exact file for a narrower purpose.
- **The `.meta`-path-to-source-path reconstruction** (`mode_check`, `run.py`
  lines ~1155-1160, and `_refresh_full_aggregations`, lines 1331-1335 —
  both do `rel_meta = meta_path.relative_to(files_dir); source_rel =
  str(rel_meta)[:-len(".meta")] if ...endswith(".meta")`) — reused
  verbatim in `prune_stale_index()`'s files-pass, a third call site for
  an already-twice-duplicated reconstruction.
- **The graceful-degrade optional-module import shape** (`run.py` lines
  121-154, `path_resolver`/`meta_describe` via `importlib.util.
  spec_from_file_location` in `try/except Exception`) — reused for
  `wp_defaults`, adapted to resolve from `THIS_DIR` alone (see Contracts)
  since it is smith-index-specific, not a `scripts/parsers/` module.
- **`JsonlLogger.log(item_id, stage, status, error=...)`**'s existing
  4-argument signature (`run.py` lines 679-681) — reused unchanged for the
  new `"prune"`/`"prune-system"` stages; no logger change of any kind.
  `resume_completed_files()`'s existing `stage == "system-update"` filter
  (line 735) is also reused unchanged — the new stages are simply
  different strings it was never going to match, by construction, not by
  a new exclusion added to that function.
- **The existing conditional-second-print-line pattern**
  (`mode_full()`'s `if run.stats.get("over_300", 0): print(...)`,
  line 1137-1138) — reused verbatim in shape for the new `Pruned: ...`
  breakdown line (FR-11), directly below it.
- **`mode_init_system_paths()`'s existing per-top-level-directory loop and
  payload-write tail** (`run.py` lines 1554-1583) — unchanged in structure;
  FR-3 only adds a WP-rules prepend and a `wp-admin`/`wp-includes` skip
  inside the loop already there.
- **`scripts/install.sh`'s existing two-line smith-index `cp` block**
  (lines 208-210) — reused in shape for the new `wp_defaults.py` line
  (FR-6), no new staging mechanism.
- **`tests/parsers/test_run_<topic>.py`'s existing `importlib`-load-`run.py`
  + `unittest.TestCase` + `tempfile.mkdtemp` harness** (`test_run_resolve_
  system.py`, confirmed on disk) — reused verbatim in shape for this
  feature's new Part A/Part C unit tests.
- **`tests/e2e/test_full_index_rebuild.sh`'s existing `pass`/`fail`/
  `assert` helper trio + `trap ... EXIT` cleanup + isolated tmpdir fixture
  project shape** (confirmed on disk, 168 lines) — reused verbatim in
  shape for this feature's new Part B prune fixture test, as a NEW sibling
  file (see Test Strategy — a same-file extension would need its own new
  fixture project shape mid-file, since Part B's fixture needs
  DELETED/newly-excluded files a fresh full-rebuild-from-scratch fixture
  can't represent without an explicit two-pass setup, which is cleaner as
  its own file than interleaved into T101's existing single-pass flow).

## File Size Policy

No new or modified source file crosses the 300-line soft ceiling this
repo's prior features already apply absent a hard constitution gate:

- `scripts/smith-index/wp_defaults.py` (new): two constant tuples + two
  short pure functions + module docstring — targets 45-65 lines total,
  comparable in shape to `path-resolver.py`'s own smallest self-contained
  section (its Tier 3 heuristic, `_apply_heuristic()`, ~35 lines).
- `scripts/smith-index/run.py` net new/changed lines across all three
  parts: import block (~15 lines) + `mode_init_system_paths()` additions
  (~12 lines) + `prune_stale_index()` (~35 lines) + `mode_full()` call
  site (~6 lines) + `_load_overrides()` additions (~10 lines) ≈ 78 lines
  total, pushing the file to roughly 1742 lines — still a straight
  addition with zero restructuring, and smaller than feature 58's own
  ~150-line single-file estimate for a comparably-scoped SKILL.md change.
- `scripts/install.sh`: one new line.
- New test files: `tests/parsers/test_run_wordpress_detection.py` and
  `tests/parsers/test_run_load_overrides_warning.py` each target
  ≤120 lines (sized against `test_schema_version_marker.py`'s 161 lines,
  the smallest existing sibling in that directory, with headroom to
  spare since these two have fewer branch cases); `tests/e2e/
  test_full_index_rebuild_gc.sh` targets ≤180 lines, sized against
  `test_full_index_rebuild.sh`'s own 168 lines since it needs a comparable
  two-phase (seed, then re-run) fixture rather than a smaller single-pass
  one.

## Contracts

### `detect_wordpress()` / `wp_exclusion_rules()` (`scripts/smith-index/wp_defaults.py`)

```python
"""WordPress-core detection and default exclusion rules, consumed by
`/smith-index --init-system-paths` (scripts/smith-index/run.py). Pure,
stdlib-only, no filesystem writes — callers own all I/O. See BANK-028
for origin: WP-core files (wp-admin/, wp-includes/) dominate a stub
generated by the plain per-top-level-directory heuristic with zero
signal for the project's own site code.
"""

from __future__ import annotations
from pathlib import Path

# Directory-shaped WP-core exclusions. Trailing "/" matches this
# codebase's existing `system-paths.json` `prefix` convention for a
# directory rule (see e.g. skills/smith-index/templates/
# system-paths.json.example).
WP_CORE_DIRS: tuple[str, ...] = ("wp-admin/", "wp-includes/")

# Root-level WP-core files. Each is its OWN exact-match prefix — NEVER
# collapse these into a bare "wp-" prefix, which would also match
# wp-content/ (themes/plugins/uploads — the actual site code a
# WordPress project's owner cares about indexing). This is BANK-028's
# explicit, load-bearing gotcha.
WP_CORE_ROOT_FILES: tuple[str, ...] = (
    "index.php",
    "wp-activate.php",
    "wp-blog-header.php",
    "wp-comments-post.php",
    "wp-config-sample.php",
    "wp-config.php",
    "wp-cron.php",
    "wp-links-opml.php",
    "wp-load.php",
    "wp-login.php",
    "wp-mail.php",
    "wp-settings.php",
    "wp-signup.php",
    "wp-trackback.php",
    "xmlrpc.php",
)


def detect_wordpress(project_root: Path) -> bool:
    """True iff `project_root` looks like a WordPress-core checkout.

    Both `wp-load.php` (file) AND `wp-includes/` (directory) must be
    present — either alone is too weak a signal (a project vendoring one
    WP-flavored file, or an unrelated directory happening to be named
    `wp-includes`, must not trip auto-exclusion).
    """
    return (project_root / "wp-load.php").is_file() and (
        project_root / "wp-includes"
    ).is_dir()


def wp_exclusion_rules() -> list[dict]:
    """Return the 17 stub `rules` entries covering WordPress core.

    2 directory prefixes + 15 exact root-file prefixes, each mapped to
    "excluded" with a `_comment`. Caller (mode_init_system_paths) is
    responsible for NOT also emitting a generic per-directory rule for
    wp-admin/wp-includes (would collide on an identical-length prefix).
    """
    rules: list[dict] = []
    for d in WP_CORE_DIRS:
        rules.append(
            {
                "_comment": (
                    "WordPress core (auto-detected) — never a bare "
                    "'wp-' prefix, it would also swallow wp-content/"
                ),
                "prefix": d,
                "system": "excluded",
            }
        )
    for f in WP_CORE_ROOT_FILES:
        rules.append(
            {
                "_comment": "WordPress core root file (auto-detected)",
                "prefix": f,
                "system": "excluded",
            }
        )
    return rules
```

### `wp_defaults` import block (`scripts/smith-index/run.py`, after the existing `meta_describe` block)

```python
# wp_defaults (Part A: WordPress-core detection/exclusion rules for
# --init-system-paths). Lives beside run.py itself (not scripts/parsers/)
# since it is smith-index-specific, not a general parser-layer module —
# resolved from THIS_DIR only, no dual dev-tree/global-install search.
# Optional/graceful-degrade like path_resolver/meta_describe above: a
# mid-/smith-update upgrade window (run.py refreshed, wp_defaults.py not
# yet staged) must not crash --init-system-paths — it just skips WP
# detection for that one invocation (see FR-5/FR-6).
try:
    _wpd_path = THIS_DIR / "wp_defaults.py"
    if _wpd_path.is_file():
        _wpd_spec = _ilu.spec_from_file_location("wp_defaults", _wpd_path)
        if _wpd_spec and _wpd_spec.loader:
            wp_defaults = _ilu.module_from_spec(_wpd_spec)
            _wpd_spec.loader.exec_module(wp_defaults)  # type: ignore[attr-defined]
        else:
            wp_defaults = None  # type: ignore[assignment]
    else:
        wp_defaults = None  # type: ignore[assignment]
except Exception:
    wp_defaults = None  # type: ignore[assignment]
```

### `mode_init_system_paths()` additions (`scripts/smith-index/run.py`, FR-3/FR-4)

```python
def mode_init_system_paths(project_root: Path) -> int:
    target = project_root / ".smith" / "index" / "config" / "system-paths.json"
    if target.exists():
        print(f"/smith-index --init-system-paths: {target} already exists. "
              "Not overwriting.")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)

    is_wp = wp_defaults is not None and wp_defaults.detect_wordpress(project_root)
    wp_rules = wp_defaults.wp_exclusion_rules() if is_wp else []
    wp_dir_names = (
        {d.rstrip("/") for d in wp_defaults.WP_CORE_DIRS} if is_wp else set()
    )

    rules: list[dict] = []
    for entry in sorted(project_root.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name
        if name.startswith(".") or name in EXCLUDED_DIR_NAMES:
            continue
        if name in {"tests", "test", "docs", "doc"}:
            continue
        if name in wp_dir_names:
            continue  # already covered by an explicit WP exclusion rule
        rules.append({
            "_comment": f"Auto-generated stub for {name}/",
            "prefix": name + "/",
            "system": f"system-{name}",
        })

    rules = wp_rules + rules
    payload = {
        "_comment": (
            "Optional path -> system overrides. Longest prefix wins. "
            "If empty/missing, heuristic in path-resolver.py applies."
        ),
        "rules": rules,
        "default": "unassigned",
    }
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if is_wp:
        print(
            f"/smith-index --init-system-paths: WordPress project detected "
            f"(wp-load.php + wp-includes/) — added {len(wp_rules)} "
            "WordPress-core exclusion rule(s)"
        )
    print(f"/smith-index --init-system-paths: wrote {target} with "
          f"{len(rules)} stub rule(s)")
    return 0
```

### `prune_stale_index()` (`scripts/smith-index/run.py`, new `IndexRun` method, FR-7/FR-8/FR-12/FR-13)

```python
def prune_stale_index(self) -> dict:
    """Full-rebuild-only garbage collection (see mode_full's gating —
    never called from --check/--incremental/--system/--resume; see
    spec.md FR-9 for why each is structurally unsafe to prune from).

    Removes:
      (a) .smith/index/files/**/*.meta whose source no longer exists OR
          now resolves to "excluded" — same predicate
          _refresh_full_aggregations() already established for
          incremental mode's aggregation-skip (run.py ~line 1336-1340),
          reused here as an actual deletion trigger.
      (b) .smith/index/systems/<id>.md for any system with zero entries
          in self.systems after this run's walk + write_system_manifests().

    Confined to self.files_dir / self.systems_dir — NEVER self.config_dir
    or the .schema-version marker. A per-file OSError is logged and does
    not abort the walk (matches this file's existing per-file try/except
    discipline elsewhere).

    Returns {"files_pruned": int, "systems_pruned": int}.
    """
    files_pruned = 0
    if self.files_dir.is_dir():
        for meta_path in self.files_dir.rglob("*.meta"):
            rel_meta = meta_path.relative_to(self.files_dir)
            source_rel = str(rel_meta)
            if source_rel.endswith(".meta"):
                source_rel = source_rel[: -len(".meta")]
            source_path = self.project_root / source_rel
            stale = (not source_path.is_file()) or (
                self.resolve_system(source_path) == "excluded"
            )
            if not stale:
                continue
            try:
                meta_path.unlink()
                files_pruned += 1
                self.logger.log(source_rel, "prune", "ok")
            except OSError as e:
                self.logger.log(source_rel, "prune", "failed", error=str(e))

    systems_pruned = 0
    if self.systems_dir.is_dir():
        for manifest_path in self.systems_dir.glob("*.md"):
            system_id = manifest_path.stem
            if self.systems.get(system_id):
                continue
            try:
                manifest_path.unlink()
                systems_pruned += 1
                self.logger.log(system_id, "prune-system", "ok")
            except OSError as e:
                self.logger.log(system_id, "prune-system", "failed", error=str(e))

    return {"files_pruned": files_pruned, "systems_pruned": systems_pruned}
```

### `mode_full()` call site (FR-9/FR-10/FR-11)

```python
    run.write_system_manifests()
    duration = time.monotonic() - start
    run.write_top_manifest(duration)
    run.write_schema_version_marker()

    gc_result = None
    if system_filter is None and not resume:
        gc_result = run.prune_stale_index()

    run.cleanup()

    summary = (
        f"/smith-index: {run.stats['total']} files indexed "
        f"({run.succeeded} succeeded, {run.failed} failed, "
        f"{run.skipped} skipped) in {duration:.1f}s"
    )
    if gc_result is not None:
        total_pruned = gc_result["files_pruned"] + gc_result["systems_pruned"]
        summary += f" · {total_pruned} pruned"
    print(summary)
    if run.stats.get("over_300", 0):
        print(f"  Files over 300 lines: {run.stats['over_300']}")
    if gc_result is not None and (gc_result["files_pruned"] or gc_result["systems_pruned"]):
        print(
            f"  Pruned: {gc_result['files_pruned']} stale .meta file(s), "
            f"{gc_result['systems_pruned']} empty system manifest(s)"
        )
    return 0
```
`· <N> pruned` uses the same `·` separator style already used nowhere
else in this file's summary line today (a plain space-joined clause is
equally acceptable — implementation may simplify to a trailing `, <N>
pruned` if that reads more consistently against the existing `({N}
succeeded, ...)` clause; either satisfies FR-10's "literal substring `<N>
pruned`" requirement).

### `_load_overrides()` additions (`scripts/smith-index/run.py`, FR-14/FR-15/FR-16/FR-17)

```python
# Sibling keys a config author plausibly typed instead of "rules" — see
# BANK-028 Gotcha 1 ("system-paths.json top-level key is `rules` (NOT
# `overrides`)"). Small, named, non-fuzzy: "overrides" is the literal
# gotcha reported; "override" is its singular; "mappings"/"map" are the
# two other names this repo's own docs use informally for the same
# concept ("path -> system overrides", "explicit path -> system mapping"
# — see docs/manifest-system.md and this file's own stub `_comment`).
_PLAUSIBLE_RULES_KEY_ALIASES = ("overrides", "override", "mappings", "map")

def _load_overrides(self) -> dict | None:
    if not self.system_paths_path.exists():
        return None
    try:
        with open(self.system_paths_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(data, dict) and "rules" not in data:
        for alias in _PLAUSIBLE_RULES_KEY_ALIASES:
            if alias in data:
                sys.stderr.write(
                    f"/smith-index: {self.system_paths_path} has "
                    f"{alias!r} but no \"rules\" key — system-paths.json "
                    "overrides must be under \"rules\"; "
                    f"{alias!r} is ignored (no override applied from it).\n"
                )
                break
    return data
```
`_PLAUSIBLE_RULES_KEY_ALIASES` is a module-level constant (near
`EXCLUDED_DIR_NAMES`), not a method-local list, so it is independently
unit-testable and greppable.

### `scripts/install.sh` addition (FR-6)

```bash
mkdir -p "$SMITH_HOME/scripts/smith-index"
cp "$REPO_ROOT/scripts/smith-index/run.py" "$SMITH_HOME/scripts/smith-index/run.py" 2>/dev/null || true
cp "$REPO_ROOT/scripts/smith-index/run.sh" "$SMITH_HOME/scripts/smith-index/run.sh" 2>/dev/null || true
cp "$REPO_ROOT/scripts/smith-index/wp_defaults.py" "$SMITH_HOME/scripts/smith-index/wp_defaults.py" 2>/dev/null || true
chmod +x "$SMITH_HOME/scripts/smith-index/"*.sh 2>/dev/null || true
```

### Prune report shape (return value of `prune_stale_index()`, consumed by `mode_full()`)

```python
{"files_pruned": <int>, "systems_pruned": <int>}
```
Summary-line substring: `<files_pruned + systems_pruned> pruned` (FR-10),
present on every full-rebuild run (including `0 pruned`), absent entirely
on every `--incremental`/`--check`/`--system`/`--resume` run.

### Warning text (FR-14, exact wording not contractually fixed beyond content)

```
/smith-index: <path-to-system-paths.json> has 'overrides' but no "rules" key — system-paths.json overrides must be under "rules"; 'overrides' is ignored (no override applied from it).
```
Contractually fixed: (1) written to `stderr`, never `stdout`; (2) names
BOTH the key found and `"rules"` as the correct key; (3) exactly one line
per `_load_overrides()` call (first-alias-match wins, per the `break`).

## Exact file-by-file change list

### MODIFIED

| File | Change |
|---|---|
| `scripts/smith-index/run.py` | **(1)** New `wp_defaults` graceful-degrade import block, after the existing `meta_describe` block. **(2)** `mode_init_system_paths()` gains the WP-detection branch (FR-3/FR-4). **(3)** New `IndexRun.prune_stale_index()` method (FR-7/FR-8/FR-12/FR-13), placed after `write_schema_version_marker()`. **(4)** `mode_full()` gains the `prune_stale_index()` call site + summary-line extension (FR-9/FR-10/FR-11). **(5)** `_load_overrides()` gains the plausible-key warning check (FR-14/FR-15/FR-16/FR-17) + new module-level `_PLAUSIBLE_RULES_KEY_ALIASES` constant near `EXCLUDED_DIR_NAMES`. |
| `scripts/install.sh` | One new `cp` line for `wp_defaults.py` in the existing smith-index staging block (FR-6). |
| `skills/smith-index/SKILL.md` | **(1)** `### /smith-index --init-system-paths` section gains a paragraph on WordPress auto-detection (FR-18). **(2)** `### /smith-index` (full rebuild) section gains a paragraph on the prune step, its `<N> pruned` summary line, and the four modes that never prune (FR-18). |
| `skills/smith/SKILL.md` | One short cross-reference note near `#### 4.8 Optionally Scaffold System Specs` (FR-19) — documents what `--init-system-paths` now does for a WordPress project WHEN invoked; explicitly does not claim `/smith init` invokes it (per `questions.md` Q4 / `spec.md` OOS-5). |
| `CHANGELOG.md` | New `[Unreleased]` → `### Added` entry, written LAST after every other file's changes are final (FR-20). |

### NEW

| File | Purpose |
|---|---|
| `scripts/smith-index/wp_defaults.py` | `detect_wordpress()`, `wp_exclusion_rules()`, `WP_CORE_DIRS`, `WP_CORE_ROOT_FILES` (FR-1/FR-2). |
| `tests/parsers/test_run_wordpress_detection.py` | Unit tests for Part A: `detect_wordpress()`'s four presence/absence combinations; `wp_exclusion_rules()`'s exact 17-entry count and no-bare-`wp-`-prefix invariant; `mode_init_system_paths()` end-to-end against a WP-shaped tmpdir fixture (17 rules, no duplicate wp-admin/wp-includes entries) and a non-WP fixture (byte-identical to pre-feature output — SC-1/SC-2). |
| `tests/parsers/test_run_load_overrides_warning.py` | Unit tests for Part C: a dict with `"overrides"` (warns, returns unchanged), a dict with `"rules"` present (no warning), a dict with neither `"rules"` nor any alias (no warning), a non-dict top-level JSON value (no warning, no crash), malformed JSON (existing `None`-return behavior unchanged) — asserting on captured `stderr` and on `_load_overrides()`'s return value (SC-5). |
| `tests/e2e/test_full_index_rebuild_gc.sh` | Fixture-level test for Part B: seed a small project, run a full rebuild, delete one source file, change `system-paths.json` to newly-exclude another source's directory, re-run a full rebuild and assert both stale `.meta` files and the now-empty system's manifest are gone and the summary line contains `pruned`; then re-seed the identical stale state and assert `--incremental`, `--check`, `--system <name>`, and `--resume` each leave it untouched (SC-3/SC-4). |

No `scripts/parsers/path-resolver.py`, `skills/smith-audit/*`, or
`skills/smith-queue/*` file is created or modified by this feature
(OOS-1).

## Phased ordering

1. **`scripts/smith-index/wp_defaults.py`, first.** Self-contained, no
   dependency on anything else in this feature; `run.py`'s import block
   needs the file to exist to be meaningfully tested end-to-end (the
   graceful-degrade `None` fallback works either way, but the feature's
   actual behavior needs the module present).
2. **`run.py`'s `wp_defaults` import block + `mode_init_system_paths()`
   additions (Part A), together.** The import and its one call site are
   inseparable — landing one without the other is either dead code (import
   with no caller) or a `NameError` (caller with no import).
3. **`run.py`'s `_load_overrides()` additions (Part C).** Independent of
   Parts A/B — sequenced here only because it is the smallest, most
   self-contained change, so it is easiest to verify in isolation before
   Part B's larger `prune_stale_index()` addition lands in the same file.
4. **`run.py`'s `prune_stale_index()` + `mode_full()` call site (Part B).**
   Sequenced last among the `run.py` changes since it is the largest
   single addition and benefits from Parts A/C already being stable
   (Part B's own fixture test exercises a WP-shaped newly-excluded
   scenario that depends on Part A's stub generator already working, per
   the shared US-4 scenario in `spec.md`).
5. **`scripts/install.sh`.** One-line addition, sequenced after
   `wp_defaults.py` exists (nothing else depends on install.sh; it could
   equally be done in phase 1, grouped here for phase-numbering
   convenience since it logically completes Part A's "always ships
   alongside run.py" guarantee).
6. **`skills/smith-index/SKILL.md` + `skills/smith/SKILL.md`.** Sequenced
   after phases 1-5 so both docs describe the FINAL behavior (exact rule
   count, exact summary-line format), not an interim draft — same
   reasoning feature 58's plan gave for writing its own docs last relative
   to the behavior they describe.
7. **`tests/parsers/test_run_wordpress_detection.py` + `tests/parsers/
   test_run_load_overrides_warning.py` + `tests/e2e/
   test_full_index_rebuild_gc.sh`.** Written against the FINAL
   implementation from phases 1-4, not an interim draft — mirrors feature
   58's own "test file written after the final algorithm text" sequencing.
8. **`CHANGELOG.md`.** Written last, after phases 1-7 are final.

## Test strategy

- **`tests/parsers/test_run_wordpress_detection.py` (primary Part A test,
  `unittest`/`importlib`-load-`run.py`).** Cases: `detect_wordpress()`
  with (both present → `True`), (only `wp-load.php` → `False`), (only
  `wp-includes/` → `False`), (neither → `False`); `wp_exclusion_rules()`
  returns exactly 17 entries, every `prefix` value is checked against
  `startswith("wp-") and prefix not in {"wp-admin/", "wp-includes/", ...
  the 15 named root files}` to assert NO entry is a bare `"wp-"` prefix
  masquerading as something else; `mode_init_system_paths()` run against a
  `tempfile.mkdtemp()` fixture containing only `wp-load.php` + empty
  `wp-admin/` + empty `wp-includes/` directories asserts the written
  `system-paths.json`'s `rules` array has length 17 and contains no
  `"system-wp-admin"`/`"system-wp-includes"` entries; the same harness run
  against a fixture with no WP markers asserts the rules list matches
  exactly what `mode_init_system_paths()` produces with `wp_defaults`
  monkeypatched to `None` (the byte-identical pre-feature-output
  assertion, SC-2).
- **`tests/parsers/test_run_load_overrides_warning.py` (primary Part C
  test).** Builds an `IndexRun` against a `tempfile.mkdtemp()` fixture with
  a hand-written `.smith/index/config/system-paths.json`, capturing
  `sys.stderr` via `contextlib.redirect_stderr` around the `IndexRun(...)`
  constructor call (which invokes `_load_overrides()` in `__init__`).
  Cases: `{"overrides": [...]}` → exactly one stderr line containing both
  `"overrides"` and `"rules"`, `_overrides_dict` equals the parsed dict
  unchanged; `{"rules": [...]}` → zero stderr output; `{"unrelated_key":
  1}` → zero stderr output (no plausible alias present); a JSON array
  `[1, 2, 3]` at the top level → zero stderr output, no exception; invalid
  JSON text → zero stderr output, `_overrides_dict` is `None` (existing
  behavior, unchanged).
- **`tests/e2e/test_full_index_rebuild_gc.sh` (Part B, fixture-level,
  bash+zsh both, mirroring `test_full_index_rebuild.sh`'s own portability
  precedent).** Phase 1: seed a 3-file fixture project (one file that will
  be deleted, one file under a directory that will become excluded, one
  file that stays), run a full `/smith-index`, confirm all three `.meta`
  files + their systems' manifests exist. Phase 2: delete the first file,
  add a `system-paths.json` rule excluding the second file's directory,
  re-run a full `/smith-index`, assert: the deleted file's stale `.meta`
  is gone, the newly-excluded file's stale `.meta` is gone, the
  now-empty system's manifest is gone, the still-valid third file's
  `.meta`/manifest are UNCHANGED (not accidentally pruned), and the
  printed summary line matches `grep -q " pruned"` / contains the correct
  total count. Phase 3 (no-prune negative cases): reset to the Phase-2
  stale state fresh each time, then run `--incremental --from <ref> --to
  <ref>` (git repo required — `git init` the fixture in setup), `--check`,
  `--system <name>`, and `--resume` (via a deliberately-truncated
  checkpoint) in turn, asserting after EACH that the stale `.meta`/
  manifest files from Phase 2's setup are still present and no `pruned`
  substring appears in that run's output.
- **Full-suite regression** — run the complete `tests/` directory once
  after all phases land, confirming zero regressions in any file this
  feature does not itself modify — EXPLICITLY including a check that the
  two pre-existing FAILING tests in the `--describe` family
  (`tests/skills/test_smith_index_describe.sh`) still fail in the SAME
  way, not a new/different way, and that this feature adds no new failure
  anywhere else (SC-6). This feature does not touch `--describe` in any
  form, so a changed failure signature there would indicate an
  unintended interaction, not an accepted pre-existing condition.
- **Shell portability** — `tests/e2e/test_full_index_rebuild_gc.sh` and
  `scripts/install.sh`'s one new line are both run under both `bash` and
  `zsh` during implementation review, matching this repo's existing
  dual-shell convention (NFR-4).

## Rollout notes

- No `.smith/config.json` / `templates/config.default.json` change of any
  kind — this feature adds no new config key and no new three-site seeding
  step, unlike features 56-58. Every behavior change this feature ships is
  either (a) automatic and unconditional the moment a project re-runs
  `--init-system-paths` on a WordPress-shaped root (Part A — no opt-in
  flag; the stub is generated fresh only when none exists, so an EXISTING
  hand-authored `system-paths.json` is never touched or retroactively
  rewritten), or (b) automatic and unconditional on every full rebuild
  going forward (Part B — no opt-in flag; a project sees pruning start
  happening the moment it next runs `/smith-index` with no `--system`/
  `--resume` flag after updating), or (c) a warning-only diagnostic with
  zero behavior change (Part C).
- Distributed via the standard `/smith-update` path — `scripts/smith-index/
  run.py` and the new `wp_defaults.py` are both Smith-owned files
  refreshed by `/smith-update`'s existing global update mechanism
  (`~/.smith/scripts/`), once FR-6's `install.sh` line ships; no new
  `/smith-update` step is needed since this feature adds no config key to
  seed (contrast with features 56-58's own `§5.1x` steps, none of which
  apply here).
- **The one behavior every existing indexed project sees automatically,
  with no opt-in**: the very next full (unfiltered, non-resumed)
  `/smith-index` run on ANY project — WordPress or not — starts pruning
  stale `.meta`/manifest entries for already-deleted or already-excluded
  sources that a pre-feature rebuild would have silently left in place.
  This is Part B's entire purpose (`BANK-028` Gotcha 2) and is called out
  explicitly here since, unlike Part A (which only activates for a
  WordPress-shaped root generating a FRESH stub) and Part C (diagnostic
  only), it changes existing full-rebuild output for every project the
  moment this feature ships — always net-positive (removing dead state
  the project already didn't want indexed), never destructive to a
  currently-valid file's own `.meta`.

## Spec-plan tensions — RESOLVED, folded into the sections above

1. **New module vs. inline functions in `run.py`.** Resolved per this
   task's own instruction (a separate `wp_defaults.py` module for
   WordPress data/detection; prune inline in `run.py` near the walk since
   it needs run state) — folded into "Architecture Summary" and the
   File Size Policy's per-file line-count breakdown. `wp_defaults.py`
   keeps `run.py`'s own net-new line count to Parts B+C only (~78 lines),
   not Part A's constant-tuple/data content (which would have added
   another ~50 lines directly into an already-1664-line file).
2. **Warning message wording / exact alias list for Part C.** Resolved:
   a small NAMED constant (`_PLAUSIBLE_RULES_KEY_ALIASES = ("overrides",
   "override", "mappings", "map")`), not a fuzzy-match heuristic — folded
   into §Contracts with per-entry rationale (the literal reported gotcha,
   its singular, and this repo's own two informal names for the same
   concept in existing prose/docstrings).
3. **Where exactly `prune_stale_index()`'s call site sits relative to
   `run.cleanup()` (which closes the logger).** Resolved: BEFORE
   `cleanup()`, since `prune_stale_index()`'s own FR-12 logging
   requirement needs `self.logger` still open — folded into §Contracts'
   `mode_full()` call-site snippet (`gc_result = ...` sits directly above
   `run.cleanup()`, not below it).
4. **`system-paths.json` config-example file
   (`skills/smith-index/templates/system-paths.json.example` — corrected
   here from an earlier draft's `templates/system-paths.json.example`;
   re-verified on disk, the file lives under `skills/smith-index/
   templates/`, not the repo-root `templates/` directory) — does it need
   a WP-aware update too?** Resolved: no — it is a distinct, hand-authored
   example
   artifact documenting the override MECHANISM generally, not the
   auto-generated stub's output; this feature changes what
   `--init-system-paths` generates, not what the static hand-maintained
   example teaches. Left untouched, noted here so a reviewer doesn't
   read its absence from the file-by-file list as an oversight.
