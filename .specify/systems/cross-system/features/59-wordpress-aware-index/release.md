# Release Notes — Feature 59: WordPress-Aware Index Defaults

**Date:** 2026-09-14
**Branch:** `59-wordpress-aware-index` (worktree `/tmp/smith-wordpress-aware-index`, from main @ 1ea2c35)
**Origin:** attck2026 rollout — a WordPress project indexed 1795 files (81s) because
`/smith-index` walked all of WP core; hand-writing `system-paths.json` exclusions cut it
to 567 files (37s). This feature makes that behavior automatic (BANK-028).

## What shipped

1. **`scripts/smith-index/wp_defaults.py` (new, 83 lines)** — `detect_wordpress(root)`
   (wp-load.php file AND wp-includes/ directory, both required) and
   `WP_CORE_EXCLUSION_PREFIXES`: 17 tier-2 rules mapping `wp-admin/`, `wp-includes/`,
   and 15 root-level WP core files (incl. wp-config.php) to the `"excluded"` system.
   Deliberately no bare `wp-` prefix — it would swallow `wp-content/` (the project's
   actual code). `wp-content/` is never excluded.

2. **`run.py` — WP-aware `--init-system-paths`** — when initializing
   `system-paths.json` in a detected WordPress root, the seeded file carries the 17
   exclusion rules plus an explanatory `_comment`. Non-WP projects seed exactly as
   before. Import is graceful-degrade: if `wp_defaults.py` is missing (partial
   install), init falls back to the generic seed with a stderr note.

3. **`run.py` — plausible-key warning in `_load_overrides()`** — a
   `system-paths.json` whose top-level key is `overrides` / `override` / `mappings` /
   `map` instead of `rules` now emits a stderr warning naming the correct key. This
   encodes the silent no-op we hit live on attck2026 (the loader reads only `rules`).

4. **`run.py` — `prune_stale_index()` GC** — full rebuilds (`mode_full()` only) now
   prune index entries whose source file is gone or now resolves to `"excluded"`:
   removes `files/**.meta`, then system manifests with no surviving files, then reports
   "N pruned" in the summary. Explicitly gated OFF for `--incremental`, `--check`,
   `--system`, and `--resume` (each has a partial view of the project; pruning from a
   partial view would delete valid entries — rationale recorded in spec FR-9).

5. **`scripts/install.sh`** — ships `wp_defaults.py` alongside the other
   smith-index scripts.

6. **Docs** — `skills/smith-index/SKILL.md` (WP detection + exclusion behavior,
   `rules`-key warning), `skills/smith/SKILL.md` (init-time note), `CHANGELOG.md`.

## Tests

- `tests/parsers/test_run_wordpress_detection.py` — 9 cases (detection positives/
  negatives, seeded-rules content, non-WP unchanged, missing-module degrade).
- `tests/parsers/test_run_load_overrides_warning.py` — 5 cases (each alias warns,
  `rules` doesn't; + logger-handle cleanup fix from the review pass).
- `tests/e2e/test_full_index_rebuild_gc.sh` — 25 assertions, bash+zsh: full-rebuild
  prune of deleted + newly-excluded files, empty-system manifest removal, incremental/
  check/system/resume leave stale entries untouched, summary count.
- Full regression: hooks, security, scheduler, skills, parsers suites green under
  bash and zsh; re-run green after review-pass auto-fixes.
- Pre-commit secret scan (`secret-scan.sh --diff-base main`): clean, exit 0.

## Clean Code Review Pass (Phase 3.5)

- **1 Medium — UNRESOLVED (flagged, not fixed):** `prune_stale_index()`'s
  system-manifest deletion keys off `self.systems`, which only records files that
  parsed successfully *this run*. A system whose files all fail parsing transiently
  (parser subprocess crash, unsupported-extension drift) keeps its `.meta` files but
  has its `systems/<id>.md` silently deleted — a transient failure masquerading as
  staleness. Spec FR-9 reasons through this exact risk class for `--resume` but the
  same structural gap is reachable via a plain full run. Fix direction (not applied —
  behavior change): derive system-level emptiness from surviving `.meta` files after
  the file-level pass, not from this run's parse successes. Full analysis:
  Phase 3.5 findings (Clean Code Review section of the PR body). Candidate follow-up
  bugfix.
- **2 Low — both auto-fixed:** stale line-number docstring cross-reference in
  `prune_stale_index()`; unclosed JsonlLogger handles in the new warning tests
  (ResourceWarning ×5). Bounded re-run of Phase 3 after fixes: green.

## Deviations / folded-in fix

- **`tests/security/test_secret_scan.sh` case 10 test-isolation fix (pre-existing,
  folded in with disclosure):** discovered during this feature's regression run, not
  caused by it. The "unreadable engine → exit 2" case chmod-000s the scratch copy of
  `secret_scan.py`, but the wrapper prefers the *installed* engine at
  `$HOME/.smith/scripts/security/`, which rescued the broken scratch engine on any
  machine with Smith installed. Fixed by running case 10 under an isolated `HOME`
  (`mktemp -d`). 40/40 both shells.
- Q1–Q4 at the questions gate were answered under the user's standing delegation
  (recommended answers auto-accepted; recorded in questions.md).

## Known gaps noted (pre-existing, out of scope)

- `/smith` init docs claim index bootstrap but never invoke `/smith-index` (OOS-5).
- `--resume` doesn't rehydrate `run.systems` from the checkpoint (why FR-9 excludes
  it from pruning).
