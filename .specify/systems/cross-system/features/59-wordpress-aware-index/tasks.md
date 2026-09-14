---
feature: 59-wordpress-aware-index
branch: 59-wordpress-aware-index
created: 2026-09-14
status: ready-to-build
spec: ./spec.md
plan: ./plan.md
questions: ./questions.md
checklist: ./checklists/requirements.md
---

# Tasks: WordPress-Aware Index Defaults

Task IDs are sequential. `[P]` marks tasks that share no files with their
phase neighbors and can be executed in parallel. Tags map to plan.md's
surfaces: `[wpdefaults]` (new module), `[run]` (`scripts/smith-index/
run.py`), `[install]` (`scripts/install.sh`), `[docs]`, `[tests]`,
`[verify]`. Every path is relative to the smith-repo project root unless
noted.

Hard constraints (carried from spec.md / plan.md, apply to every task
below):
- **FR-2 / no-bare-`wp-`-prefix**: `wp_exclusion_rules()` must never emit
  an entry using a bare `"wp-"` prefix — it would also swallow
  `wp-content/`. This is `BANK-028`'s explicit, load-bearing gotcha.
- **FR-9 / full-rebuild-only pruning, four named exclusions**:
  `prune_stale_index()` runs if and only if `system_filter is None and
  resume is False`. `--incremental` never reaches `mode_full()` at all;
  `--check` never instantiates a rebuild `IndexRun`; `--system <name>`
  reaches `mode_full()` but `run.systems` only ever contains the ONE
  filtered system that run; `--resume` reaches `mode_full()` with
  `system_filter` unset but has no `_refresh_full_aggregations()`-style
  rehydration, so `run.systems` reflects only the resumed segment — each
  reason is distinct, do not collapse them into one comment.
- **FR-13 / confinement**: `prune_stale_index()` must never read or write
  `self.config_dir` (`system-paths.json`, `context-manifest.json`) or
  `self.index_dir / ".schema-version"` under any input.
- **FR-15 / no behavior change beyond the warning**: `_load_overrides()`
  must still return the parsed dict exactly as `json.load()` produced it,
  on every input, warning or not.
- **NFR-2 / no new block/terminate path**: `--init-system-paths` still
  exits 0 whether or not WordPress is detected; `mode_full()` still exits
  0 whether or not anything was pruned; the new warning never raises.
- **NFR-4 / interpreter + shell convention**: every new Python snippet
  invoked with `python3` (Rule 6, `~/.claude/CLAUDE.md`); the new e2e
  shell test and the one new `install.sh` line are both verified under
  `bash` AND `zsh`.
- **OOS-1**: no change to `scripts/parsers/path-resolver.py` — not
  `_apply_overrides()`, not `resolve()`'s tier-2 lookup, not the `"rules"`
  key name itself.
- **OOS-5**: no change to `skills/smith/SKILL.md`'s init flow beyond the
  one FR-19 cross-reference note — do NOT add a new `/smith-index` (or
  `--init-system-paths`) invocation anywhere in that file. The
  `skills/smith-index/SKILL.md` "Auto-invocation" section's claim that
  `/smith init` calls `/smith-index` is a pre-existing, independently
  re-confirmed documentation/behavior drift (zero matches for
  `/smith-index` in `skills/smith/SKILL.md`'s actual flow) — out of scope
  to fix here, do not "helpfully" close it.
- **SC-6**: the full-suite regression at the end of Phase 5 must show
  *zero* newly-introduced failures, and the two pre-existing failing
  `--describe`-family tests (identified below) must fail in the SAME way
  they did before this feature, not a new/different way.

**On-disk verification performed before writing this file** (every
plan.md citation below was independently re-confirmed against the actual
worktree, not taken on the plan's word alone; one inaccuracy found and
corrected in `plan.md` itself, noted at the end of this block):

- `scripts/smith-index/run.py`: 1664 lines (matches plan.md's Technical
  Context exactly). `def mode_init_system_paths(project_root: Path) ->
  int:` at line 1544 (exact match). `def _load_overrides(self) -> dict |
  None:` at line 778, called from `__init__` at line 767 (exact match).
  `def mode_full(` at line 1076 (exact match). `def _refresh_full_
  aggregations(run: IndexRun) -> None:` at line 1309; its stale predicate
  — `if not source_path.exists(): continue` / `system =
  run.resolve_system(source_path)` / `if system == "excluded": continue`
  — sits at lines 1336-1340 (exact match to plan.md's citation). The
  identical `.meta`-path-to-source-path reconstruction (`rel_meta =
  meta_path.relative_to(files_dir)`, strip trailing `.meta`) appears at
  `mode_check` lines ~1154-1161 and `_refresh_full_aggregations` lines
  1331-1335 — third call site will be `prune_stale_index()`. `def
  resolve_system(self, file_path: Path) -> str:` at line 862; when it
  returns `"excluded"`, `process_file()` (line 889) skips the file
  entirely at line 900-902 — confirms Gotcha 3's data-hygiene claim (an
  excluded file is never parsed, not merely excluded from a listing).
  `class JsonlLogger` `def log(` at line 679, signature `(self, item_id:
  str, stage: str, status: str = "ok", error: str | None = None) ->
  None:` at lines 679-681 (exact match). `def resume_completed_files
  (jsonl_path: Path | None) -> set[str]:` at line 720, filters `rec.get
  ("stage") == "system-update"` — confirmed the new `"prune"`/
  `"prune-system"` stages this feature adds cannot collide with it.
  `IndexRun.__init__` sets `self.project_root`/`self.index_dir`/
  `self.files_dir`/`self.systems_dir`/`self.config_dir` at lines 754-758.
  `def write_schema_version_marker(self) -> None:` at line 1012, body
  ends at line 1062 immediately before `def cleanup(self) -> None:` at
  line 1063 — confirms `prune_stale_index()`'s insertion point (between
  the two) and `mode_full()`'s call-site insertion point (between the
  `run.write_schema_version_marker()` call and `run.cleanup()` call,
  currently adjacent lines inside `mode_full()`). `EXCLUDED_DIR_NAMES`
  (line 60) and the separate `mode_init_system_paths()`-local `{"tests",
  "test", "docs", "doc"}` skip (line 1561) are two distinct skip lists —
  the new `wp_dir_names` skip (FR-3) is a THIRD, additive check inside the
  same loop, not a merge into either existing set. The import block for
  `path_resolver`/`meta_describe` (graceful-degrade
  `importlib.util.spec_from_file_location` in `try/except Exception`)
  spans lines 92-154; `wp_defaults`'s new block is inserted directly
  after it, resolved from `THIS_DIR` only (line 92) per FR-5.
- `scripts/smith-index/run.py`'s CLI (`main()`, argparse block ~line
  1589) carries an explicit comment: "`--describe` / `--batch-size` /
  `--llm-batch-size` / `--threshold` / `--model` / `--no-interactive` were
  removed in v3 (PR #23)" — the `/smith-index --describe` entrypoint now
  lives entirely in `skills/smith-index/SKILL.md` prose (Task sub-agent
  orchestration). This is WHY the two pre-existing failing tests below
  fail, and confirms neither failure is related to this feature.
- **The two pre-existing FAILING `--describe`-family tests (SC-6),
  identified by direct run against this worktree** (both invoke the
  removed CLI flags directly, or exercise code paths this feature does
  not touch):
  - `tests/skills/test_smith_index_describe.sh` — `bash
    tests/skills/test_smith_index_describe.sh` exits 1 ("FAIL (1
    issue(s))"); its Test 1/2/3/4 all call `run.py ... --describe
    --no-interactive --batch-size N --threshold 0`, which now fails
    argparse with "unrecognized arguments."
  - `tests/e2e/test_full_describe_flow.sh` — `bash
    tests/e2e/test_full_describe_flow.sh` exits 1 ("13 passed, 8
    failed"); failures include a missing `meta_describe.update_touched`
    attribute and several description-layer assertions unrelated to
    WordPress detection, pruning, or `_load_overrides`.
  Neither file is touched by this feature (no task below modifies
  `--describe`, `meta_describe.py`, or either test file) — Phase 5's
  regression task (T018) asserts both still fail in exactly this same
  shape, not a new one.
- `scripts/install.sh`'s existing smith-index staging block: `mkdir -p
  "$SMITH_HOME/scripts/smith-index"` (line 208), `cp ... run.py ...`
  (line 209), `cp ... run.sh ...` (line 210), `chmod +x
  "$SMITH_HOME/scripts/smith-index/"*.sh` (line 211) — exact match to
  plan.md's citation. The new `wp_defaults.py` `cp` line goes between 210
  and 211 (no `chmod` needed — it is imported, never executed directly,
  same as `run.py`/`meta_describe.py`/`path-resolver.py` themselves).
- `skills/smith-index/SKILL.md` (482 lines): `### /smith-index — full
  rebuild (default)` spans lines 42-79, its 9 numbered steps end at line
  76 ("9. Print a summary line..."), `**Performance budget:**` follows at
  line 78 — the new prune-step paragraph becomes step 10, inserted
  between them. `### /smith-index --init-system-paths` spans lines
  374-381 (exact match to spec.md FR-18's citation). `## Auto-invocation`
  (lines 395-405) contains the literal claim `` `/smith init` calls
  `/smith-index` as its final setup step `` — independently re-confirmed
  as the OOS-5 drift spec.md documents (this feature does not edit this
  section).
- `skills/smith/SKILL.md`: `#### 4.8 Optionally Scaffold System Specs`
  spans lines 838-876, immediately followed by `#### 4.10 Clear Bootstrap
  Marker` at line 878 (there is no `4.9` in this file — confirmed, not a
  gap this feature needs to fill) — FR-19's cross-reference note is
  appended at the end of 4.8's content, before 4.10 begins. `grep -c
  "smith-index" skills/smith/SKILL.md` confirms zero invocation-shaped
  matches in the actual init flow (OOS-5 pre-existing drift, re-confirmed
  independently of spec.md's own claim).
- `CHANGELOG.md` (374 lines): `## [Unreleased]` at line 8, `### Added` at
  line 10, first existing bullet (feature #58) at line 12 — the new
  feature #59 entry is inserted as the NEW first bullet at line 12,
  pushing #58 down, matching this file's newest-first-under-`### Added`
  ordering.
- `docs/manifest-system.md` line 182: "explicit path → system **mapping**
  overrides" — confirms the plan.md Contracts rationale for including
  `"mappings"`/`"map"` in `_PLAUSIBLE_RULES_KEY_ALIASES` (this repo's own
  prose already uses "mapping" informally for the same concept).
- `tests/parsers/test_run_resolve_system.py` (128 lines) and
  `tests/parsers/test_schema_version_marker.py` (161 lines) — both use
  the `importlib.util.spec_from_file_location` + `unittest.TestCase` +
  `tempfile.mkdtemp()` harness plan.md cites as this feature's precedent
  (A-5). `tests/e2e/test_full_index_rebuild.sh` (168 lines) — the
  `pass`/`fail`/`assert` helper trio + `trap ... EXIT` cleanup + isolated
  tmpdir fixture shape cited as the Part B e2e test's precedent (A-5).
- **Correction made to `plan.md` while drafting this file**: `plan.md`
  cited the hand-authored override-mechanism example file as
  `templates/system-paths.json.example` in two places (its
  `wp_defaults.py` Contracts code-comment, and its "Spec-plan tensions"
  §4). On-disk, the file actually lives at `skills/smith-index/templates/
  system-paths.json.example` (confirmed via `find`; `docs/manifest-
  system.md` line 349 cites the same correct path). Left uncorrected,
  this would have shipped a wrong path inside `wp_defaults.py`'s own
  source comment (T001 below copies that Contracts block near-verbatim).
  Both `plan.md` citations have been fixed in place to the correct path;
  no spec.md/questions.md change was needed (neither file names this
  path). T001 below uses the corrected path.

---

## Phase 1: `scripts/smith-index/wp_defaults.py` (new module)

- [X] T001 [wpdefaults] Create `scripts/smith-index/wp_defaults.py` per
  plan.md's Contracts section (module docstring citing `BANK-028`;
  `from __future__ import annotations`; `from pathlib import Path`;
  module-level `WP_CORE_DIRS: tuple[str, ...] = ("wp-admin/",
  "wp-includes/")`; module-level `WP_CORE_ROOT_FILES: tuple[str, ...]`
  with the 15 named root files; `detect_wordpress(project_root: Path) ->
  bool` returning `(project_root / "wp-load.php").is_file() and
  (project_root / "wp-includes").is_dir()`; `wp_exclusion_rules() ->
  list[dict]` building 17 `{"_comment": ..., "prefix": ..., "system":
  "excluded"}` entries, 2 from `WP_CORE_DIRS` + 15 from
  `WP_CORE_ROOT_FILES`, never a bare `"wp-"` prefix). Use the CORRECTED
  path in the `WP_CORE_DIRS` code comment: `skills/smith-index/templates/
  system-paths.json.example` (see the on-disk-verification correction
  note above — do not copy plan.md's original wrong path). No imports
  beyond `pathlib.Path`; no CLI entrypoint; no filesystem writes. Targets
  45-65 lines (File Size Policy). FR-1, FR-2, NFR-1.

- [X] T002 [P] [tests] Create `tests/parsers/test_run_wordpress_detection.py`
  using the `importlib.util.spec_from_file_location` + `unittest.TestCase`
  + `tempfile.mkdtemp()` harness `test_run_resolve_system.py` (128 lines,
  confirmed on disk) already establishes. Cases against `wp_defaults.py`
  directly (no `run.py` dependency, can pass the moment T001 lands):
  `detect_wordpress()` with (both present → `True`), (only `wp-load.php`
  → `False`), (only `wp-includes/` → `False`), (neither → `False`);
  `wp_exclusion_rules()` returns exactly 17 entries, and every entry's
  `prefix` is checked against the invariant "no entry is a bare `wp-`
  prefix disguising itself as something else" (i.e. every `prefix` is
  exactly one of `WP_CORE_DIRS` or `WP_CORE_ROOT_FILES`, nothing else).
  Cases against `run.py`'s `mode_init_system_paths()` (these assertions
  depend on Phase 2/T004 landing — write them now per this repo's
  test-first convention, expect them to fail until T004 lands, do not
  skip or stub them): a WP-shaped `tempfile.mkdtemp()` fixture
  (`wp-load.php` + empty `wp-admin/` + empty `wp-includes/`, no other
  top-level dirs) produces a `system-paths.json` whose `rules` array has
  length 17 with no `"system-wp-admin"`/`"system-wp-includes"` entries; a
  non-WP fixture produces a rules list identical to `mode_init_system_
  paths()` run with `wp_defaults` monkeypatched to `None` (SC-2's
  byte-identical assertion). Target ≤120 lines. FR-1, FR-2, SC-1, SC-2,
  A-5.

**Checkpoint**: `wp_defaults.py` exists, is pure/stdlib-only, and its two
functions are independently unit-tested. `test_run_wordpress_detection.py`'s
`mode_init_system_paths()`-dependent cases are expected RED until Phase 2
lands — this is by design (test-first), not a defect at this checkpoint.

---

## Phase 2: `scripts/smith-index/run.py` wiring

- [X] T003 [run] Add the `wp_defaults` graceful-degrade import block to
  `run.py`, placed directly after the existing `meta_describe` import
  block (which ends ~line 154). Mirror the `path_resolver`/`meta_describe`
  shape (`importlib.util.spec_from_file_location` in `try/except
  Exception`, resulting in `wp_defaults = None` on any failure) but
  resolve ONLY from `THIS_DIR / "wp_defaults.py"` (no
  `PARSER_DIR_REPO`/`PARSER_DIR_GLOBAL` dual search — `wp_defaults.py` is
  smith-index-specific, always ships beside `run.py`). Per plan.md's
  Contracts block verbatim. FR-5.
  - Depends on: T001 (file must exist for the happy path; the
    graceful-degrade `None` fallback is exercised either way).

- [X] T004 [run] Modify `mode_init_system_paths()` (line 1544): compute
  `is_wp = wp_defaults is not None and wp_defaults.detect_wordpress
  (project_root)`, `wp_rules = wp_defaults.wp_exclusion_rules() if is_wp
  else []`, `wp_dir_names = {d.rstrip("/") for d in wp_defaults.
  WP_CORE_DIRS} if is_wp else set()`. Inside the existing
  per-top-level-directory loop, add ONE new skip line — `if name in
  wp_dir_names: continue` — positioned alongside (not replacing) the
  existing `.startswith(".")`/`EXCLUDED_DIR_NAMES` and
  `{"tests","test","docs","doc"}` skips (both confirmed as separate,
  pre-existing checks — this is a third, additive one). Prepend `wp_rules`
  to the generated `rules` list (`rules = wp_rules + rules`) before
  building `payload`. Print an extra line when `is_wp` — "WordPress
  project detected (wp-load.php + wp-includes/) — added N WordPress-core
  exclusion rule(s)" — before the existing "wrote `<target>` with N stub
  rule(s)" print. When `wp_defaults is None` or `detect_wordpress()`
  returns `False`, every new line above is a no-op and output is
  byte-for-byte identical to today's. FR-3, FR-4, US-1, US-2, US-3.
  - Depends on: T003.

- [X] T005 [run] Add the Part C hardening to `_load_overrides()` (line
  778): a new module-level constant `_PLAUSIBLE_RULES_KEY_ALIASES =
  ("overrides", "override", "mappings", "map")` placed near
  `EXCLUDED_DIR_NAMES` (line 60), independently unit-testable/greppable.
  Inside `_load_overrides()`'s existing `try` block, after the successful
  `json.load()` and before `return data`: when `isinstance(data, dict)
  and "rules" not in data`, iterate `_PLAUSIBLE_RULES_KEY_ALIASES` and, on
  the first match, write exactly one line to `sys.stderr` naming BOTH the
  alias found and `"rules"` as the correct key, then `break` (first-match
  wins — at most one line ever). The function's return value is
  UNCHANGED in every case — `data` is returned exactly as parsed, warning
  emitted or not. A dict that already has `"rules"`, a non-dict top-level
  JSON value, or a JSON parse failure must NOT trigger this check — it is
  the existing `except (OSError, json.JSONDecodeError): return None`
  branch and the `isinstance(data, dict) and "rules" not in data` guard
  together that scope it exactly. FR-14, FR-15, FR-16, FR-17, US-6.

- [X] T006 [run] Add `IndexRun.prune_stale_index(self) -> dict` to the
  `IndexRun` class, placed between `write_schema_version_marker()` (ends
  line 1062) and `cleanup()` (starts line 1063). Files-pass: if
  `self.files_dir.is_dir()`, `rglob("*.meta")`; for each, reconstruct
  `source_rel` via the SAME strip-`.meta`-suffix logic already used at
  `mode_check` (~lines 1154-1161) and `_refresh_full_aggregations` (lines
  1331-1335); a file is stale when `not source_path.is_file()` OR
  `self.resolve_system(source_path) == "excluded"` — this is the EXACT
  predicate `_refresh_full_aggregations` (lines 1336-1340) already
  established, reused not reinvented, now wired to an actual `unlink()`
  instead of an aggregation-skip. Each deletion wrapped in its own
  `try/except OSError`, logging `self.logger.log(source_rel, "prune",
  "ok")` on success or `self.logger.log(source_rel, "prune", "failed",
  error=str(e))` on failure — a single `OSError` never aborts the walk.
  Systems-pass: if `self.systems_dir.is_dir()`, `glob("*.md")`; delete
  any manifest whose `.stem` is absent from `self.systems` or maps to a
  falsy/empty list, same try/except-and-log discipline with
  `"prune-system"` as the stage name. MUST NEVER read or touch
  `self.config_dir` or `self.index_dir / ".schema-version"` under any
  input (FR-13). Returns `{"files_pruned": int, "systems_pruned": int}`.
  FR-7, FR-8, FR-12, FR-13, NFR-3, US-4.

- [X] T007 [run] Wire `prune_stale_index()` into `mode_full()` (line
  1076): between the existing `run.write_schema_version_marker()` call
  and `run.cleanup()` call, add `gc_result = None` then `if
  system_filter is None and not resume: gc_result =
  run.prune_stale_index()` — placed BEFORE `run.cleanup()` specifically
  because `prune_stale_index()`'s FR-12 logging needs `self.logger` still
  open (cleanup() closes it). Directly above this gate, add an inline
  comment giving the four-mode rationale from spec.md FR-9 verbatim in
  spirit (not copy-pasted boilerplate) — in particular the `--resume`
  case's OWN distinct reason: `--resume` reaches `mode_full()` with
  `system_filter` unset, but unlike `mode_incremental` there is no
  `_refresh_full_aggregations()`-style re-hydration call for the resumed
  path, so `run.systems` after a resumed run reflects only the
  CURRENTLY-resumed segment, not the full project — pruning from that
  partial view would wrongly delete a still-valid system's manifest.
  Extend the summary string: when `gc_result is not None`, append a
  clause containing the literal substring `<N> pruned` where `N =
  gc_result["files_pruned"] + gc_result["systems_pruned"]` (present even
  when `N == 0`, i.e. `0 pruned` — always grep-able on every applicable
  run); when `gc_result is None` (any of the four excluded modes), the
  summary is completely unchanged, no `pruned` substring anywhere. Add
  one additional conditional print line, mirroring the existing `if
  run.stats.get("over_300", 0): print(...)` pattern directly below it —
  `"  Pruned: <files_pruned> stale .meta file(s), <systems_pruned> empty
  system manifest(s)"` — only when `gc_result is not None and
  (files_pruned or systems_pruned)`. FR-9, FR-10, FR-11, US-5.
  - Depends on: T006.

**Checkpoint**: `/smith-index --init-system-paths` on a WordPress-shaped
root generates the 17-rule stub with `wp-content/` still indexed
normally; a `{"overrides": [...]}` `system-paths.json` produces exactly
one stderr warning with an unchanged return value; a full rebuild prunes
stale `.meta`/manifest entries and prints `<N> pruned`; `--incremental`/
`--check`/`--system`/`--resume` all leave stale state untouched. Phase
1's `test_run_wordpress_detection.py` cases that were RED at the Phase 1
checkpoint should now be GREEN (verified in Phase 5, not re-run here).

---

## Phase 3: `scripts/install.sh`

- [X] T008 [P] [install] Add one new `cp` line to `scripts/install.sh`'s
  existing smith-index staging block, between the current `run.sh` line
  (210) and the `chmod +x` line (211): `cp
  "$REPO_ROOT/scripts/smith-index/wp_defaults.py"
  "$SMITH_HOME/scripts/smith-index/wp_defaults.py" 2>/dev/null || true`
  — same shape, same `|| true` swallow-and-continue convention as its two
  siblings. No `chmod` needed (imported, never executed directly). FR-6,
  A-4.
  - Depends on: T001 (the source file this line copies must exist —
    no functional runtime dependency on Phase 2).

**Checkpoint**: a fresh `~/.smith/scripts/smith-index/` install (or the
next `/smith-update`) stages `wp_defaults.py` alongside `run.py`/`run.sh`
— FR-5's graceful-degrade path stops being the PERMANENT behavior for
installed (non-dev-tree) projects.

---

## Phase 4: Documentation

- [X] T009 [docs] Add a paragraph to `skills/smith-index/SKILL.md`'s
  existing `### /smith-index --init-system-paths` section (lines
  374-381): describe the two-signal WordPress-core-checkout predicate
  (`wp-load.php` file AND `wp-includes/` directory, both required), the
  17 generated rules (2 directory + 15 exact root-file, each
  `"excluded"`), and the explicit "never a bare `wp-` prefix — it would
  swallow `wp-content/`, which stays indexed as `system-wp-content`"
  rationale. FR-18.

- [X] T010 [docs] Add a new numbered step 10 to `skills/smith-index/
  SKILL.md`'s `### /smith-index — full rebuild (default)` section (its 9
  existing steps end at line 76, `**Performance budget:**` follows at
  line 78 — insert between them): describe the new prune step — runs
  only when `system_filter is None and resume is False`; removes
  `.smith/index/files/**/*.meta` whose source is gone or now resolves
  `"excluded"`, and `.smith/index/systems/<id>.md` for any system left
  with zero files that run; the `<N> pruned` summary-line substring
  (always present on an applicable run, including `0 pruned`); and that
  `--system`/`--resume`/`--check`/`--incremental` never prune — with a
  one-clause pointer to this feature's `plan.md` (`.specify/systems/
  cross-system/features/59-wordpress-aware-index/plan.md`) Contracts
  section for the full per-mode rationale, rather than restating FR-9's
  four bullets verbatim in skill prose. FR-18.
  - Same file as T009 — sequential with it, not `[P]`.

- [X] T011 [P] [docs] Add ONE short cross-reference note to `skills/smith/
  SKILL.md`, appended at the end of the existing `#### 4.8 Optionally
  Scaffold System Specs` section's content (lines 838-876), before
  `#### 4.10 Clear Bootstrap Marker` (line 878) begins. Word it to
  describe what `/smith-index --init-system-paths` now does for a
  WordPress-shaped project WHEN invoked (17 auto-generated exclusion
  rules) — explicitly do NOT claim or imply `/smith init` itself now
  triggers `/smith-index` (it doesn't — see OOS-5's independently
  re-confirmed drift note above; this feature does not change that).
  FR-19, OOS-5.
  - Depends on: nothing structurally, but should describe FINAL behavior
    — land after T004 for accuracy (not a hard file dependency).

- [X] T012 [docs] Add a new `[Unreleased]` → `### Added` entry to
  `CHANGELOG.md`, inserted as the NEW FIRST bullet directly under the
  `### Added` heading (line 10), ahead of the existing feature #58 entry
  (currently line 12) — matching the file's newest-first-under-`###
  Added` ordering and the existing per-feature bullet-list style (bold
  title + parenthetical `(feature #59, 59-wordpress-aware-index)`, then
  nested bullets per surface, per the feature #57/#58 entries'
  formatting precedent). Cover: `wp_defaults.py`'s WordPress-core
  detection + 17-rule generation, `mode_init_system_paths()`'s WP branch
  (with the `wp-content/` untouched guarantee), `prune_stale_index()`'s
  full-rebuild-only garbage collection with its four named exclusions
  and the `<N> pruned` summary line, `_load_overrides()`'s stderr
  warning (no behavior change), and the `install.sh` staging line.
  Written LAST, only after every other task in this file is final. FR-20.
  - Depends on: T001-T011 (written last).

**Checkpoint**: both SKILL.md files and `CHANGELOG.md` describe the FINAL
behavior from Phases 1-3, not an interim draft.

---

## Phase 5: Verification

- [X] T013 [P] [tests] Create `tests/parsers/test_run_load_overrides_
  warning.py` (Part C unit tests, same harness style as T002). Build an
  `IndexRun` against a `tempfile.mkdtemp()` fixture with a hand-written
  `.smith/index/config/system-paths.json`, capturing `sys.stderr` via
  `contextlib.redirect_stderr` around the `IndexRun(...)` constructor
  call (it invokes `_load_overrides()` in `__init__` at line 767). Cases:
  `{"overrides": [...]}` → exactly one stderr line containing both
  `"overrides"` and `"rules"`, `_overrides_dict` equals the parsed dict
  unchanged; `{"rules": [...]}` → zero stderr output; `{"unrelated_key":
  1}` → zero stderr output (no plausible alias present); a top-level JSON
  array `[1, 2, 3]` → zero stderr output, no exception; invalid JSON text
  → zero stderr output, `_overrides_dict` is `None` (pre-existing
  behavior, unchanged). Target ≤120 lines. FR-14, FR-15, FR-16, FR-17,
  SC-5, A-5.
  - Depends on: T005.

- [X] T014 [P] [tests] Create `tests/e2e/test_full_index_rebuild_gc.sh`
  (Part B fixture test), reusing `test_full_index_rebuild.sh`'s (168
  lines) `pass`/`fail`/`assert` helper trio + `trap ... EXIT` cleanup +
  isolated `mktemp`-style fixture project shape, as a NEW sibling file.
  Phase 1 (seed): a 3-file fixture project — one file that will be
  deleted, one file under a directory that will become newly-excluded,
  one file that stays valid — `git init` it (needed for the Phase-3
  `--incremental` case below), run a full `/smith-index`, confirm all
  three `.meta` files and their systems' manifests exist. Phase 2 (GC):
  delete the first file, add a `system-paths.json` `"rules"` entry
  excluding the second file's directory, re-run a full `/smith-index`;
  assert the deleted file's stale `.meta` is gone, the newly-excluded
  file's stale `.meta` is gone, the now-empty system's manifest is gone,
  the still-valid third file's `.meta`/manifest are UNCHANGED, and the
  printed summary line contains `pruned` with the correct total count.
  Phase 3 (no-prune negatives): reset to the Phase-2 stale state fresh
  before each sub-case, then run `--incremental --from <ref> --to <ref>`,
  `--check`, `--system <name>`, and `--resume` (via a deliberately
  truncated checkpoint) in turn; assert after EACH that the stale
  `.meta`/manifest files are still present and no `pruned` substring
  appears anywhere in that run's output. Target ≤180 lines. FR-7, FR-8,
  FR-9, FR-10, SC-3, SC-4, A-5.
  - Depends on: T006, T007 (and T005, since Phase 2's newly-excluded
    directory rule exercises the standard `"rules"` key path).

- [X] T015 [verify] Run `python3 tests/parsers/test_run_wordpress_
  detection.py` and `python3 tests/parsers/test_run_load_overrides_
  warning.py` — all cases green, including the `mode_init_system_paths()`
  -dependent cases in the first file that were expected RED at the Phase
  1 checkpoint. SC-1, SC-2, SC-5.
  - Depends on: T002, T004, T005, T013.

- [X] T016 [verify] Run `tests/e2e/test_full_index_rebuild_gc.sh` under
  BOTH `bash` and `zsh` (NFR-4 dual-shell convention) — all three phases
  green, including all four Phase-3 no-prune negative cases. SC-3, SC-4.
  - Depends on: T014.

- [X] T017 [verify] Run the pre-existing `tests/skills/test_smith_
  index.sh` harness (98 lines) — confirm its four existing checks (full
  rebuild artifacts, `--check` staleness on a fresh build, `--check`
  detecting a touched file, `--migrate-templates` idempotency) remain
  green, unmodified by anything this feature touches (`mode_check` and
  `mode_migrate_templates` are both untouched by Parts A/B/C).

- [X] T018 [verify] Run the complete `tests/` directory once
  (full-suite regression). Confirm zero regressions in any file this
  feature does not itself modify. EXPLICITLY re-run and confirm, in the
  SAME failure shape as the on-disk-verification block above (not a new
  or different failure): `bash tests/skills/test_smith_index_describe.sh`
  still fails via "unrecognized arguments: --describe ..." and `bash
  tests/e2e/test_full_describe_flow.sh` still fails its same ~8
  assertions. SC-6.
  - Depends on: T001-T014 all landed.

- [X] T019 [verify] Targeted greps confirming FR/NFR invariants hold
  against the final diff: `grep -n '"wp-"' scripts/smith-index/
  wp_defaults.py` returns no matches (no bare `wp-` prefix literal
  anywhere — only the two full `"wp-admin/"`/`"wp-includes/"` entries
  and the 15 named exact filenames, per FR-2); a count of `"excluded"`
  occurrences inside `wp_exclusion_rules()`'s returned entries equals 17
  (cross-checked against T002's own length assertion, not re-derived
  here); `grep -n "def prune_stale_index" scripts/smith-index/run.py`
  and `grep -n "prune_stale_index()" scripts/smith-index/run.py` show
  exactly one definition and exactly one call site (inside `mode_full()`
  only — FR-9); isolate `prune_stale_index()`'s own line range and
  confirm it contains no reference to `self.config_dir` or
  `".schema-version"` (FR-13); `git diff --stat main --
  scripts/smith-index/run.py` shows only insertions/additions to
  existing function bodies plus the two wholly-new pieces
  (`prune_stale_index()`, the `_load_overrides()`/`mode_full()`/
  `mode_init_system_paths()` additions) — confirming plan.md's "no
  existing function is restructured or moved" claim.

**Checkpoint**: every FR/NFR/US/SC this feature specifies has either an
automated assertion (T002/T013/T014/T015/T016/T017/T018/T019) or is a
documented, deliberate non-automated scope boundary (none exist for this
feature — unlike feature #58, every surface here is a script/module, not
Claude-orchestrated SKILL.md prose requiring manual verification, so
nothing is silently unverified).

---

## Dependencies & Execution Order

### Task-level dependencies

- T001 has no dependencies (pure new module).
- T002's `wp_defaults`-only cases depend on T001; its `mode_init_system_
  paths()`-dependent cases additionally depend on T004 to go green
  (written now per test-first convention, expected RED until then).
- T003 depends on T001 (imports it).
- T004 depends on T003 (uses the `wp_defaults` name the import block
  binds).
- T005 is independent of T001/T003/T004 (Part C touches a different
  method, `_load_overrides()`) — can be authored in parallel with Phase
  1/the T003-T004 pair, sequenced here per plan.md's own "smallest,
  most self-contained, easiest to verify in isolation before Part B
  lands" rationale.
- T006 is independent of T003/T004/T005 in principle (Part B touches
  `prune_stale_index()`, a new method reading only pre-existing `self.*`
  state) but is sequenced after Part A/C per plan.md's Phased Ordering
  since its own fixture test (T014) exercises a WP-shaped
  newly-excluded scenario that depends on Part A already working.
- T007 depends on T006 (calls the method it defines).
- T008 depends on T001 (copies the file T001 creates) — no dependency on
  T003-T007.
- T009, T010 depend on T004 (WP-detection paragraph) and T006/T007
  (prune-step paragraph) respectively being FINAL before being described
  — land after Phase 2, not before.
- T011 depends on T004 for accuracy (describes `--init-system-paths`'s
  final WP behavior) — no file-level dependency (different file from
  T009/T010).
- T012 (CHANGELOG) depends on T001-T011 ALL being final — written last,
  per FR-20 and plan.md's Phased Ordering step 8.
- T013 depends on T005.
- T014 depends on T005, T006, T007.
- T015 depends on T002, T004, T005, T013.
- T016 depends on T014.
- T017 has no feature-added dependency (pre-existing test, run as-is) —
  sequenced here for convenience alongside the rest of Phase 5.
- T018 depends on every prior task (full regression, last).
- T019 depends on T001-T012 (greps the finished diff).

### Parallel opportunities

- T002 [P] can be drafted alongside Phase 2 (different file from
  `run.py`), though its second half won't go green until T004 lands.
- T008 [P] (install.sh) has no file overlap with T003-T007 (run.py) or
  T009-T012 (docs) — can land any time after T001.
- T011 [P] (skills/smith/SKILL.md) has no file overlap with T009/T010
  (skills/smith-index/SKILL.md).
- T013 [P] and T014 [P] touch different new files — can be authored in
  parallel once their respective `run.py` dependencies (T005; T006+T007)
  land.

### No-op confirmations (verified, not tasks)

- `scripts/parsers/path-resolver.py` needs NO change (OOS-1) — no task
  above touches it; `resolve()`'s tier-2 `overrides_data.get("rules",
  [])` lookup and the glob-prefix-dropping behavior both stay exactly as
  they are today.
- `skills/smith/SKILL.md`'s init flow needs NO new `/smith-index`
  invocation (OOS-5) — T011 is a documentation cross-reference only.
- `templates/config.default.json` needs NO change — this feature adds no
  new config key and no three-site seeding step (unlike features 56-58).
- `skills/smith-index/templates/system-paths.json.example` needs NO
  change — it documents the override MECHANISM generally, not this
  feature's auto-generated stub output (plan.md's "Spec-plan tensions"
  §4, path corrected per the on-disk-verification note above).
- `scripts/install-parsers.sh` is NOT involved (A-4) — `wp_defaults.py`
  is smith-index-specific, staged only via the one `install.sh` line
  (T008), not the general parser-layer installer.

---

No FR/NFR/SC is contradicted by any task above. No task instructs work
`spec.md`'s Out of Scope section (OOS-1..OOS-5) excludes — in particular,
no task touches `path-resolver.py` (OOS-1), no task adds a Drupal/other-
CMS detector (OOS-2), no task reaches into an already-indexed consumer
project outside its own next rebuild (OOS-3), no task modifies
`attck2026` or any project other than this repo (OOS-4), and no task
wires `/smith init` into `/smith-index` (OOS-5). Every one of Q1-Q4's
recorded answers in `questions.md` is reflected unconditionally: WP
detection lives in `mode_init_system_paths()` only (T003/T004, Q1), the
prune fix is general-not-WP-specific (T006, Q2), the `_load_overrides`
fix is a warning not a silent alias (T005, Q3), and `/smith init`'s call
path to `/smith-index` is left untouched with a documentation-only note
(T011, Q4).
