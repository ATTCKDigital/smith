---
feature: 59-wordpress-aware-index
primary_system: cross-system
also_affects: []
branch: 59-wordpress-aware-index
created: 2026-09-14
status: in-progress
answers_applied: 2026-09-14
---

# WordPress-Aware Index Defaults

## Overview

`/smith-index --init-system-paths` writes a stub `system-paths.json` by
listing every top-level directory of the project and mapping it to
`system-<name>`. On a WordPress project this stub is actively wrong: it
buckets `wp-admin/` and `wp-includes/` as if they were the project's own
code, when in fact they are ~1,228 files of vendored WordPress core that
dominate the manifest and the file-size flags with zero signal for the
project's actual work. This was discovered hand-fixing `attck2026`
(`.smith/index/config/system-paths.json` rules → `"excluded"` for WP core,
by hand, after a first index run buried the real systems under WP-core
noise) and is the origin of `BANK-028`
(`.smith/vault/bank/2026-09-14_144500-wordpress-aware-index-defaults.md`,
binding for this spec's origin and gotchas per this feature's own task
framing).

This feature has three independent parts, unified by one theme —
`/smith-index`'s generated defaults and its rebuild step should not leave
stale or actively-wrong state lying around silently:

- **Part A — WordPress detection + auto-exclusion at stub-generation
  time.** `--init-system-paths` (`mode_init_system_paths()`,
  `scripts/smith-index/run.py`) detects a WordPress-core checkout
  (`wp-load.php` + `wp-includes/` both present at the project root) and,
  when detected, folds 17 WP-core exclusion rules into the generated stub
  — 2 directory rules (`wp-admin/`, `wp-includes/`) + 15 exact root-file
  rules (`index.php`, `wp-config.php`, `xmlrpc.php`, …) — each mapped to
  `"excluded"`, each carrying a `_comment` explaining why. `wp-content/`
  (themes, plugins, uploads — the actual site code a WP project's owner
  cares about indexing) is deliberately NOT excluded and keeps getting its
  normal `system-wp-content` bucket from the stub generator's existing
  per-top-level-dir loop; a bare `"wp-"` prefix rule would silently
  swallow it, which is exactly the gotcha `BANK-028` calls out and this
  spec treats as a hard constraint (FR-2). Non-WordPress projects see zero
  change in the generated stub.
- **Part B — Rebuild garbage collection (general, not WordPress-specific).**
  A full (unfiltered, non-resumed) `/smith-index` rebuild now prunes
  `.smith/index/files/**/*.meta` entries whose source file either no
  longer exists or now resolves to `"excluded"` (for ANY reason — a
  WordPress exclusion from Part A, a hand-authored `system-paths.json`
  rule, or a future CMS's auto-detected rules alike), and prunes
  `.smith/index/systems/<id>.md` manifests for systems that ended this run
  with zero files. `BANK-028`'s second gotcha names this directly: "Rebuild
  does NOT prune stale .meta files/system manifests for newly-excluded
  paths." `--incremental`, `--check`, `--system` (partial), and `--resume`
  all leave existing `.meta`/manifest state untouched — see FR-9 for the
  precise, independently-verified reason each one is structurally unsafe
  to prune from.
- **Part C — `_load_overrides` hardening.** `IndexRun._load_overrides()`
  (`scripts/smith-index/run.py` ~line 778) silently returns whatever
  `system-paths.json` contains, even when the file is a dict with no
  `"rules"` key at all — the exact silent-no-op that cost a rebuild on
  `attck2026` (`BANK-028`: "system-paths.json top-level key is `rules`
  (NOT `overrides`)"). This feature adds a one-line `stderr` warning when
  the parsed dict lacks `"rules"` but contains a plausible-but-wrong
  sibling key, naming the correct key — a warning only, never a behavior
  change: the dict is still returned exactly as parsed, and
  `path_resolver.resolve()`'s own tier-2 lookup (`overrides_data.get(
  "rules", []) or []`) is untouched (`scripts/parsers/path-resolver.py`
  line 322 — explicitly out of scope, see Out of Scope below).

**Terminology used throughout this spec:**
- **WordPress-core checkout** — a project root where `wp-load.php` (a
  file) AND `wp-includes/` (a directory) are BOTH present. Either signal
  alone is too weak (a project vendoring one WP-flavored file, or an
  unrelated directory that happens to be named `wp-includes`, must not
  trip auto-exclusion) — this is the exact two-signal predicate
  `BANK-028`'s Idea section names.
- **Stub** — the generated `.smith/index/config/system-paths.json` file
  `--init-system-paths` writes when none exists yet (it never overwrites
  an existing file — unchanged by this feature).
- **Full rebuild** — a `/smith-index` invocation that reaches `mode_full()`
  with `system_filter` unset (i.e., NOT `--system <name>`) — the only mode
  this feature's Part B prunes from, regardless of whether `--resume` was
  also passed (see FR-9 for why `--resume` is excluded too, despite also
  reaching `mode_full()`).
- **Stale `.meta`** — a `.smith/index/files/<mirror>.meta` entry whose
  corresponding source file, checked at prune time, either does not exist
  on disk OR resolves via `IndexRun.resolve_system()` to `"excluded"`.
- **Empty system** — a system id with zero entries in `IndexRun.systems`
  at the point pruning runs (after `write_system_manifests()` has already
  written every NON-empty system's manifest for this run).

## Problem Statement

1. **The stub generator treats WordPress core as project code.** `attck2026`'s
   first `/smith-index` run bucketed 1,228 WP-core files (985 in
   `wp-admin/`, 243 in `wp-includes/`, per `BANK-028`'s Origin) as fake
   systems `system-wp-admin` / `system-wp-includes`, dominating the
   manifest and every file-size-over-300-lines flag with files nobody
   working on that project's actual site code will ever touch.
2. **A `rules`-vs-`overrides` key typo silently no-ops.** `_load_overrides()`
   (`scripts/smith-index/run.py` line 778) does `json.load(f)` and returns
   the parsed dict verbatim; `IndexRun.resolve_system()` →
   `path_resolver.resolve()`'s tier-2 lookup reads `overrides_data.get(
   "rules", [])` — a dict with `{"overrides": [...]}` instead of
   `{"rules": [...]}` parses fine, returns an empty rules list, and every
   override the file's author intended is silently dropped with zero
   diagnostic anywhere. This is precisely what happened authoring
   `attck2026`'s hand-fixed config before the correct key was found by
   re-reading `path-resolver.py`'s source (`BANK-028`, Gotcha 1).
3. **An exclusion (or a deletion) never garbage-collects prior state.**
   Independently re-verified against the current worktree while drafting
   this spec: `mode_full()`'s per-file loop (`run.py` lines 1106-1122)
   only ever WRITES a fresh `.meta` for a file that is walked and resolves
   to a real (non-`"excluded"`) system; a file that used to resolve to a
   real system and NOW resolves to `"excluded"` (because a
   `system-paths.json` rule changed — this feature's own Part A included)
   simply stops being touched, leaving its stale `.meta` and its
   `system-<id>.md` manifest entry sitting on disk indefinitely. The
   closest existing machinery, `_refresh_full_aggregations()` (`run.py`
   lines 1309-1362, used only by `mode_incremental`), already implements
   the identical "source missing OR resolves excluded → treat as gone"
   predicate (lines 1336-1340) but only to SKIP such entries when
   re-deriving `run.systems` for manifest rendering — it never deletes the
   underlying `.meta` file or an emptied system's `.md` manifest. `BANK-028`
   Gotcha 2 names this directly as a candidate: "run.py cleans index/files
   entries whose source resolves to excluded."
4. **Part A would make problem 3 worse, not better, if shipped alone.**
   Any project that already ran `/smith-index` once, THEN adopts this
   feature's WP-core auto-exclusion (by re-running `--init-system-paths`
   after deleting a stale stub, or a fresh project's first
   `--init-system-paths` followed by its first full rebuild) needs the
   newly-`"excluded"` WP-core `.meta`/manifest entries actually removed,
   not just newly-absent from future rebuilds' input — otherwise Part A
   ships a detector that correctly stops RE-writing WP-core noise but
   never cleans up noise a project already has. Part B is this feature's
   answer; the two parts are additive but Part B alone (general GC, no WP
   awareness) is independently useful for the identical class of problem
   under a hand-authored exclusion rule, a deleted directory, or any
   future CMS-detection feature reusing the same shape (Out of Scope).

## User Scenarios

### US-1 — WordPress-shaped project: `--init-system-paths` auto-excludes core
```gherkin
Given a project root containing `wp-load.php` (a file) and `wp-includes/`
    (a directory), plus `wp-admin/` (a directory) and no other top-level
    directories
Given `.smith/index/config/system-paths.json` does not yet exist
When `/smith-index --init-system-paths` runs
Then the written stub's `rules` array contains exactly 17 entries: one
    each for `wp-admin/` and `wp-includes/` (both `"system": "excluded"`,
    each carrying a `_comment`), and one exact-match entry per WP-core
    root file (`index.php`, `wp-activate.php`, `wp-blog-header.php`,
    `wp-comments-post.php`, `wp-config-sample.php`, `wp-config.php`,
    `wp-cron.php`, `wp-links-opml.php`, `wp-load.php`, `wp-login.php`,
    `wp-mail.php`, `wp-settings.php`, `wp-signup.php`, `wp-trackback.php`,
    `xmlrpc.php` — also `"system": "excluded"`)
And `wp-admin/` and `wp-includes/` do NOT also appear as generic
    `system-wp-admin` / `system-wp-includes` rules from the stub
    generator's existing per-top-level-directory loop — the WP-specific
    rule is the only one for each, avoiding a same-length-prefix ambiguity
And no rule anywhere in the stub uses a bare `"wp-"` prefix
```

### US-2 — WordPress project with real site code: `wp-content/` is untouched
```gherkin
Given the same project as US-1, plus a `wp-content/` top-level directory
    (containing `themes/`, `plugins/`, `uploads/`)
When `/smith-index --init-system-paths` runs
Then the stub contains an 18th rule: `{"prefix": "wp-content/", "system":
    "system-wp-content"}` — generated by the SAME existing per-top-level-
    directory loop that generates every other project's non-WP rules,
    completely unmodified by this feature
And that rule is never `"excluded"` — a WordPress project's actual
    theme/plugin/upload code is indexed exactly as it would be for any
    other top-level directory
```

### US-3 — Non-WordPress project: stub generation is byte-for-byte unchanged
```gherkin
Given a project root with no `wp-load.php` file, OR `wp-load.php` present
    but no `wp-includes/` directory, OR `wp-includes/` present but no
    `wp-load.php` file (any single-signal-only case)
When `/smith-index --init-system-paths` runs
Then the written stub is identical in shape and content to what today's
    (pre-feature) generator would have produced — no WP-core rules are
    added, no top-level directory is skipped from the generic loop for any
    WP-related reason
```

### US-4 — Full rebuild prunes a deleted source and a newly-excluded source
```gherkin
Given `.smith/index/files/backend/legacy.py.meta` exists from a prior run,
    but `backend/legacy.py` no longer exists on disk
Given `.smith/index/files/wp-admin/menu.php.meta` and
    `.smith/index/systems/system-wp-admin.md` exist from a prior run, and
    `system-paths.json` now has a `{"prefix": "wp-admin/", "system":
    "excluded"}` rule that did not exist when that prior run happened
    (Part A's auto-generated rule, or a hand-authored one — the prune step
    doesn't care which)
When a full (`/smith-index`, no `--system`, no `--resume`) rebuild runs
Then `backend/legacy.py.meta` is deleted (source missing)
And every `.meta` file under `.smith/index/files/wp-admin/` is deleted
    (source resolves to `"excluded"`)
And `.smith/index/systems/system-wp-admin.md` is deleted (zero files this
    run for that system id)
And the run's printed summary line contains the exact substring
    `N pruned` where N is the total files-pruned + systems-pruned count
    (`0` prints as `0 pruned`, so the substring is always present and
    grep-able, not conditionally omitted)
```

### US-5 — `--incremental`, `--check`, `--system`, and `--resume` never prune
```gherkin
Given the exact same stale/newly-excluded state as US-4
When `/smith-index --incremental --from <ref> --to <ref>` runs (mode never
    reaches `mode_full()` at all — `_refresh_full_aggregations()` already
    re-derives `run.systems` from every `.meta` on disk, per Problem
    Statement item 3, but never deletes anything)
Or `/smith-index --check` runs (read-only staleness report; never
    instantiates a rebuild `IndexRun` that writes anything)
Or `/smith-index --system wp-admin` runs (reaches `mode_full()`, but with
    `system_filter` set — every OTHER system's `run.systems` entry is
    structurally absent this run for a reason having nothing to do with
    that system actually being empty)
Or `/smith-index --resume` runs with an interrupted prior run's checkpoint
    (reaches `mode_full()` with `system_filter` unset, but `run.systems`
    only contains files processed IN THIS RESUMED SEGMENT — files the
    checkpoint/log already marked complete are counted via `run.skipped`
    and never re-added to `run.systems`, independently confirmed against
    `mode_full()`'s resume branch: no `_refresh_full_aggregations()`-style
    re-hydration call exists for it, unlike `mode_incremental`)
Then in every one of these four cases, `backend/legacy.py.meta`,
    `wp-admin/menu.php.meta`, and `system-wp-admin.md` all remain exactly
    as they were before the run — zero deletions
```

### US-6 — `system-paths.json` with the wrong top-level key warns, doesn't break
```gherkin
Given `.smith/index/config/system-paths.json` contains valid JSON:
    `{"overrides": [{"prefix": "backend/", "system": "system-api"}]}`
    (no `"rules"` key)
When `/smith-index` (any mode that instantiates `IndexRun`) loads it via
    `_load_overrides()`
Then exactly one line is written to stderr naming `"rules"` as the correct
    key and `"overrides"` as the key actually present, and
    `_load_overrides()` still returns `{"overrides": [...]}` unchanged —
    every file resolves via the heuristic fallback exactly as it did
    before this feature (tier-2 override lookup finds no `"rules"` key,
    same as pre-feature behavior; only the diagnostic is new)
And nothing is written to stdout, and no exception is raised
```

## Functional Requirements

### Part A — WordPress detection (`scripts/smith-index/wp_defaults.py`, new; `scripts/smith-index/run.py`)

- **FR-1**: A new module `scripts/smith-index/wp_defaults.py` MUST expose a
  pure function `detect_wordpress(project_root: Path) -> bool` that
  returns `True` iff BOTH `(project_root / "wp-load.php").is_file()` AND
  `(project_root / "wp-includes").is_dir()` — no other filesystem check,
  no side effects, no writes (US-1/US-3).
- **FR-2**: The same module MUST expose `wp_exclusion_rules() -> list[dict]`
  returning exactly 17 entries: one per name in a `WP_CORE_DIRS` tuple
  (`"wp-admin/"`, `"wp-includes/"`) and one per name in a
  `WP_CORE_ROOT_FILES` tuple (the 15 names: `index.php`,
  `wp-activate.php`, `wp-blog-header.php`, `wp-comments-post.php`,
  `wp-config-sample.php`, `wp-config.php`, `wp-cron.php`,
  `wp-links-opml.php`, `wp-load.php`, `wp-login.php`, `wp-mail.php`,
  `wp-settings.php`, `wp-signup.php`, `wp-trackback.php`, `xmlrpc.php`),
  each entry shaped `{"_comment": <str>, "prefix": <name>, "system":
  "excluded"}`. NEVER a bare `"wp-"` prefix entry anywhere in this
  function's output — `BANK-028`'s explicit gotcha, since a bare prefix
  would also match `wp-content/` (US-1/US-2).
- **FR-3**: `mode_init_system_paths()` (`run.py`) MUST call
  `wp_defaults.detect_wordpress(project_root)` before building the
  per-top-level-directory `rules` list. When it returns `True`: (a)
  prepend `wp_defaults.wp_exclusion_rules()`'s 17 entries to the generated
  `rules` list; (b) skip `wp-admin` and `wp-includes` specifically inside
  the existing per-directory loop (derived from `wp_defaults.WP_CORE_DIRS`
  with trailing slashes stripped) so neither also receives a generic
  `system-wp-admin` / `system-wp-includes` rule — two same-length-prefix
  rules for the identical prefix, one `"excluded"` and one not, is
  never produced (US-1). Every OTHER top-level directory (`wp-content/`
  included) is completely unaffected by this branch and keeps going
  through the exact same generic loop as before this feature (US-2).
- **FR-4**: When `detect_wordpress()` returns `False`, `mode_init_system_paths()`'s
  generated stub MUST be byte-for-byte identical to what it produces
  today — no new code path is entered, no rule is skipped or added (US-3).
- **FR-5**: `wp_defaults.py` MUST be imported by `run.py` using the same
  graceful-degrade shape already used for `path_resolver`/`meta_describe`
  (`run.py` lines 121-154) — `importlib.util.spec_from_file_location` in a
  `try/except Exception`, resulting in `wp_defaults = None` on any failure
  — EXCEPT resolved from `THIS_DIR` (the same directory as `run.py`
  itself) rather than the dual `PARSER_DIR_REPO`/`PARSER_DIR_GLOBAL`
  search, since `wp_defaults.py` is smith-index-specific (not a general
  parser-layer module living in `scripts/parsers/`) and always ships
  beside `run.py` in both the dev-tree and the global-install layout. When
  `wp_defaults is None` (e.g. a mid-`/smith-update` upgrade window where
  `run.py` refreshed before `wp_defaults.py` finished staging),
  `mode_init_system_paths()` MUST degrade to FR-4's unchanged behavior for
  that one invocation — never crash, matching every other optional-module
  fallback already in this file.
- **FR-6**: `scripts/install.sh`'s existing smith-index staging block
  (the two `cp` lines for `run.py` / `run.sh`, ~lines 208-210) MUST gain a
  third `cp` line for `wp_defaults.py`, so a production `~/.smith/scripts/
  smith-index/` install always has it alongside `run.py` after
  `/smith-update` — without this, FR-5's graceful-degrade path is the
  PERMANENT behavior for every installed (non-dev-tree) project, not a
  transient upgrade-window fallback.

### Part B — Rebuild garbage collection (`scripts/smith-index/run.py`)

- **FR-7**: `IndexRun` MUST gain a method `prune_stale_index(self) -> dict`
  returning `{"files_pruned": int, "systems_pruned": int}`. It walks
  `self.files_dir.rglob("*.meta")`; for each, it reconstructs the source
  path (`self.project_root / <rel path with the trailing ".meta"
  stripped>` — the exact reconstruction `mode_check` (line ~1155) and
  `_refresh_full_aggregations` (line ~1331) already both do), and deletes
  the `.meta` file when the source path either does not exist
  (`.is_file()` is `False`) OR `self.resolve_system(source_path) ==
  "excluded"` — reusing, not reinventing, the identical stale-predicate
  `_refresh_full_aggregations` (lines 1336-1340) already established for
  incremental mode's aggregation-skip, now wired to an actual `unlink()`
  and run for full rebuilds too (US-4).
- **FR-8**: The same method MUST then walk `self.systems_dir.glob("*.md")`
  (verified: `write_system_manifests()` is the sole writer under
  `systems_dir`, always named `<system_id>.md` — no other file type or
  writer exists there) and delete any manifest whose `.stem` (the system
  id) is either absent from `self.systems` or maps to an empty list —
  i.e., zero files were bucketed into that system THIS run (US-4).
- **FR-9**: `prune_stale_index()` MUST be called from `mode_full()` if and
  only if `system_filter is None AND resume is False`. Four modes are
  therefore excluded, each for a distinct, independently-verified
  structural reason (US-5), not merely "excluded because the task says
  so":
  - `--incremental` (`mode_incremental`) never reaches `mode_full()` at
    all — it re-parses only a git-diff-scoped file list and already has
    its own narrower staleness-skip via `_refresh_full_aggregations()`
    (Problem Statement item 3); pruning from a partial-diff view risks
    deleting a `.meta` for a file simply outside this diff's ref range,
    not actually gone.
  - `--check` (`mode_check`) is a read-only report — it never instantiates
    a rebuild-capable `IndexRun` and writes nothing anywhere; there is no
    code path for it to reach `prune_stale_index()` through.
  - `--system <name>` (`system_filter` set) reaches `mode_full()`, but
    `run.systems` this run only ever contains the ONE filtered system —
    every other system's absence from `run.systems` reflects "wasn't
    walked this run," not "has zero files," so FR-8's emptiness check
    would misfire and delete every other system's manifest on every
    partial rebuild.
  - `--resume` reaches `mode_full()` with `system_filter` unset, but
    (independently confirmed reading `mode_full()`'s resume branch,
    `run.py` lines ~1093-1122) files marked complete by an earlier
    interrupted run are counted via `run.skipped` and never re-added to
    `run.systems` — unlike `mode_incremental`, no
    `_refresh_full_aggregations()`-style re-hydration call exists for the
    resume path, so `run.systems` after a resumed run reflects only the
    CURRENTLY-resumed segment. Treating that as "the full picture" for
    FR-8's emptiness check would wrongly prune a still-valid system's
    manifest whenever a resume happens to complete without touching any
    of that system's files in the resumed segment. This resume-
    completeness gap is a genuine PRE-EXISTING issue independent of this
    feature (see Out of Scope) — excluding `--resume` from pruning avoids
    this feature silently making that gap's symptom worse (an incomplete
    render becomes an incorrect deletion).
- **FR-10**: `mode_full()`'s printed summary line MUST contain the literal
  substring `<N> pruned` whenever `prune_stale_index()` ran (i.e.,
  `system_filter is None and resume is False`), where `<N>` is
  `files_pruned + systems_pruned` — including `0 pruned` when nothing was
  stale, so the substring is unconditionally present (grep-able) for
  every applicable run, not only when something was actually pruned
  (US-4). When `prune_stale_index()` did not run (FR-9's four exclusions),
  the summary line is completely unchanged from today's format — no
  `pruned` substring appears at all, ever (US-5).
- **FR-11**: When `<N> pruned` is nonzero, one additional line MUST be
  printed with the files/systems breakdown (`  Pruned: <files_pruned>
  stale .meta file(s), <systems_pruned> empty system manifest(s)`),
  mirroring the existing conditional `if run.stats.get("over_300", 0):
  print(...)` pattern already used for the over-300-lines line directly
  below the summary.
- **FR-12**: Every deletion `prune_stale_index()` performs MUST also
  write one `self.logger.log(<item_id>, "prune"|"prune-system", "ok"|
  "failed", error=...)` JSONL record (same `JsonlLogger.log()` signature
  every other stage already uses) — `"prune"` for a `.meta` file,
  `"prune-system"` for a system manifest — so a `--resume`d run's
  completed-file scan (`resume_completed_files()`, which only matches
  `stage == "system-update"`) is structurally unaffected by these new
  stages (they are never mistaken for file-completion records).
- **FR-13**: `prune_stale_index()` MUST NEVER touch any path outside
  `self.files_dir` or `self.systems_dir` — specifically, `self.config_dir`
  (including `system-paths.json` and `context-manifest.json`) and
  `self.index_dir / ".schema-version"` are never read for deletion
  candidates and never written by this method under any input.

### Part C — `_load_overrides` hardening (`scripts/smith-index/run.py`)

- **FR-14**: `IndexRun._load_overrides()` MUST, after a successful
  `json.load()` that yields a `dict` with no `"rules"` key, check for the
  presence of any of a small named set of plausible-but-wrong sibling
  keys (`"overrides"`, `"override"`, `"mappings"`, `"map"` — see
  `plan.md` Contracts for the exact constant and rationale for each) and,
  on the first match, write exactly one line to `sys.stderr` naming both
  the key actually found and `"rules"` as the correct key (US-6).
- **FR-15**: The warning MUST NOT change `_load_overrides()`'s return
  value in any way — the parsed dict (e.g. `{"overrides": [...]}`) is
  still returned exactly as `json.load()` produced it, on every input,
  matching this feature's explicit "no behavior change beyond the
  warning" constraint. `resolve_system()`'s downstream tier-2 lookup
  therefore behaves EXACTLY as it did before this feature for such a
  file — it still finds no `"rules"` key and falls through to the
  heuristic — only the diagnostic is new (US-6).
- **FR-16**: The warning MUST go to `stderr` only, never `stdout`, and
  MUST NOT raise or interrupt the load in any way — matching this file's
  existing "never crash callers" convention for malformed/unexpected
  `system-paths.json` content (the existing `except (OSError,
  json.JSONDecodeError): return None` branch immediately above it).
- **FR-17**: A dict that already has a `"rules"` key (regardless of its
  value's shape — empty list, non-list, whatever), OR is not a `dict` at
  all (a JSON array, string, number, or `null` at the top level), OR
  fails to parse, MUST NOT trigger this warning — it is scoped
  exclusively to "valid JSON dict, no `rules` key, but a plausible
  sibling key is present."

### Documentation

- **FR-18**: `skills/smith-index/SKILL.md`'s existing `### /smith-index
  --init-system-paths` section (lines 374-381) MUST gain a paragraph
  describing WordPress-core auto-detection: the two-signal predicate, the
  17 generated rules, and the explicit "never a bare `wp-` prefix, would
  swallow `wp-content/`" rationale. The `### /smith-index` (full rebuild)
  section MUST gain a short paragraph describing the new prune step
  (what triggers it, what it removes, the `<N> pruned` summary line, and
  that `--system`/`--resume`/`--check`/`--incremental` never prune, with
  a one-clause pointer to `plan.md`'s Contracts for the full per-mode
  rationale rather than restating FR-9's four bullets verbatim in skill
  prose).
- **FR-19**: `skills/smith/SKILL.md` MUST gain, at most, one short note
  near its existing `#### 4.8 Optionally Scaffold System Specs` section
  cross-referencing `/smith-index --init-system-paths`'s new WordPress
  auto-detection — see the Out of Scope "init call-path gap" item below
  for why this is a documentation cross-reference only, not a new
  invocation this feature adds to `/smith init`'s own flow.
- **FR-20**: `CHANGELOG.md` MUST gain a new `[Unreleased]` → `### Added`
  entry (written last, after every other file's changes are final)
  describing all three parts, the 17-rule WordPress detection, the prune
  step's full-rebuild-only scope with its four named exclusions, and the
  `_load_overrides` warning.

## Non-Functional Requirements

- **NFR-1**: `detect_wordpress()` and `wp_exclusion_rules()` are pure —
  the former does two `Path` existence checks and returns a `bool`; the
  latter reads no filesystem state and returns a plain `list[dict]`
  built from two module-level constant tuples. Neither writes anything,
  matching `path-resolver.py`'s own "Both interfaces are pure — no side
  effects, no filesystem writes" precedent for the parser layer.
- **NFR-2**: No finding, warning, or pruning action this feature adds
  introduces any new block/terminate path anywhere in `/smith-index`.
  `--init-system-paths` still exits 0 whether or not WordPress is
  detected; `mode_full()` still exits 0 whether or not anything was
  pruned; `_load_overrides()`'s new warning never raises or changes the
  function's return value or exit code.
- **NFR-3**: `prune_stale_index()`'s two `rglob`/`glob` walks and every
  `unlink()` call are wrapped so a single `OSError` on one file (a
  permission error, a concurrent external deletion) is logged
  (`"prune"`/`"prune-system"`, `"failed"`, `error=str(e)`) and does not
  abort the walk or the surrounding `mode_full()` run — matching every
  other per-file operation in this file's existing `try/except` discipline
  (`process_file`, `save_checkpoint`, `write_schema_version_marker`).
- **NFR-4**: Every new/modified Python function in this feature (`
  detect_wordpress`, `wp_exclusion_rules`, `mode_init_system_paths`'s
  additions, `prune_stale_index`, `_load_overrides`'s additions) is
  invoked with `python3` wherever a shell snippet in this feature's
  documentation changes shows an explicit interpreter (matching Rule 6 of
  `~/.claude/CLAUDE.md` and this repo's own existing convention).

## Out of Scope

- **OOS-1 — `path-resolver.py` / resolver changes.** No change to
  `scripts/parsers/path-resolver.py` — not `_apply_overrides()`, not
  `resolve()`'s tier-2 lookup, not the `"rules"` key name itself. Part C's
  warning lives entirely in `run.py`'s `IndexRun._load_overrides()`; the
  resolver's own behavior for a `{"overrides": [...]}`-shaped file (silent
  empty-rules fallback to heuristic) is completely unchanged.
- **OOS-2 — Other CMS detections.** Drupal core, other vendored/framework
  skeletons, and any other "detect X, auto-exclude its core" pattern are
  explicitly future work — noted here, per this feature's own task
  framing, as a natural next candidate reusing Part B's general
  (non-WordPress-specific) prune machinery unchanged.
- **OOS-3 — Auto-pruning existing consumer projects' indexes outside a
  rebuild they themselves run.** This feature does not reach into any
  already-indexed project and retroactively prune anything — a project
  gets Part B's cleanup the next time ITS OWN full rebuild runs (US-4),
  not as a side effect of this feature merging into smith-repo.
- **OOS-4 — `attck2026` itself.** Already hand-fixed (per `BANK-028`'s
  Origin) — its `.smith/index/config/system-paths.json` is the live
  reference this spec's WP-core rule list was checked against, not a
  target this feature modifies.
- **OOS-5 — Fixing `/smith init`'s call-path gap to `/smith-index`.**
  Independently re-verified while drafting this spec: `skills/smith/
  SKILL.md`'s actual init flow, as it exists in this worktree, contains
  NO invocation of `/smith-index` anywhere — not a full rebuild, not
  `--init-system-paths` — despite `skills/smith-index/SKILL.md`'s own
  "Auto-invocation" section claiming "`/smith init` calls `/smith-index`
  as its final setup step (per spec Requirement 5)." `grep -ni "index"
  skills/smith/SKILL.md` (re-run against the file on disk while writing
  this spec) confirms zero matches for any `/smith-index` invocation —
  only cross-references to `smith-index/templates/` asset paths and one
  prose mention of `/smith-index` inside a scaffold-system-specs prompt
  string. This is a genuine, pre-existing documentation/behavior drift
  between the two SKILL.md files, NOT something this feature introduces
  or is required to fix — closing it would mean adding a brand-new
  `/smith-index` (or `--init-system-paths`) invocation to `/smith init`'s
  own flow, which is a materially bigger, separately-scoped change than
  "small, WordPress-focused." This feature's WP-detection logic lives
  entirely inside `mode_init_system_paths()` itself (FR-3), not duplicated
  at any call site, specifically so that WHENEVER a future fix wires
  `/smith init` into `/smith-index --init-system-paths` (closing this
  gap), WordPress detection activates automatically with no further
  change needed here. FR-19's doc cross-reference in `skills/smith/
  SKILL.md` is worded to describe what happens WHEN `--init-system-paths`
  runs, not to imply `/smith init` already triggers it.

## Assumptions

- **A-1**: `BANK-028` (`.smith/vault/bank/2026-09-14_144500-wordpress-
  aware-index-defaults.md`) is binding for this feature's origin and both
  its gotchas, per this feature's own task framing. Its two open questions
  ("Detection heuristic vs init-time generation vs both?" and "Should
  full rebuild garbage-collect .meta for excluded/deleted sources
  generally?") are answered by this spec's Part A (init-time generation,
  not resolver-magic) and Part B (yes, generally, not WordPress-specific)
  respectively — see `questions.md` for the delegated-decision trail.
- **A-2 — RESOLVED via delegation.** This feature's task framing named
  three decisions with a recommendation each, to be resolved via this
  workflow's standing delegation (auto-accept recommended answers): (1)
  detection lives at stub-generation time inside `mode_init_system_paths()`,
  not as a new resolver tier; (2) rebuild garbage collection is scoped to
  full-rebuild-only, not incremental/check/system/resume; (3) the
  `_load_overrides` key-name gotcha is fixed with a warning, not a
  silent key alias. All three accepted exactly as recommended — see
  `questions.md` Q1-Q3 for the full options/evidence/outcome trail.
- **A-3 — A fourth, directly-evaluated decision (not delegated).** The
  `/smith init` call-path gap documented in OOS-5 was discovered
  independently while drafting this spec, not one of the three named
  gate items. Per this workflow's own precedent for a decision the task
  framing asks to be evaluated directly rather than routed through
  delegation (feature 58's FR-18 is the model followed here, in the
  opposite direction — that feature WIDENED scope to cover an adjacent
  gap; this one explicitly does NOT), the decision made and recorded here
  is: document the gap (OOS-5), keep this feature's WP-detection logic
  hookable-but-not-newly-wired (FR-3/FR-19), and do not touch `/smith
  init`'s own flow. See `questions.md` Q4 for the recorded rationale.
- **A-4**: `scripts/install.sh`'s existing two-`cp`-line smith-index
  staging block (verified on disk at lines 208-210) is the correct and
  ONLY place a third `wp_defaults.py` line needs adding (FR-6) — no
  separate parser-install script (`install-parsers.sh`) is involved, since
  `wp_defaults.py` is smith-index-specific, not a general parser-layer
  module under `scripts/parsers/`.
- **A-5**: `tests/parsers/` already hosts multiple `run.py`-internals unit
  tests despite `run.py` living under `scripts/smith-index/`, not
  `scripts/parsers/` (`test_run_resolve_system.py`,
  `test_schema_version_marker.py`, `test_run_preserve_descriptions.py`,
  `test_run_manifest_descriptions.py` — all confirmed present on disk),
  establishing `tests/parsers/test_run_<topic>.py` as the correct home for
  this feature's new Part A/Part C unit tests, following that exact
  naming and `importlib`-load-`run.py` harness style (see `plan.md`).
  `tests/e2e/test_full_index_rebuild.sh` establishes the correct home and
  harness shape (isolated `mktemp`-style fixture project, `pass`/`fail`/
  `assert` helpers, `trap ... EXIT` cleanup) for Part B's fixture-level
  prune tests.

## Success Criteria

- **SC-1**: A WordPress-shaped fixture (`wp-load.php` + `wp-includes/` +
  `wp-admin/`, no other top-level directories) produces a stub whose
  `rules` array has exactly 17 entries, none using a bare `"wp-"` prefix,
  and `wp-admin/`/`wp-includes/` appear only once each (FR-1/FR-2/FR-3).
- **SC-2**: A non-WordPress fixture (any single-signal-or-neither case)
  produces a stub byte-for-byte identical to today's pre-feature output
  (FR-4).
- **SC-3**: A full rebuild against a fixture with a deleted source's stale
  `.meta`, a newly-excluded source's stale `.meta`, and an emptied
  system's stale manifest prunes all three and prints a summary line
  containing `<N> pruned` (FR-7/FR-8/FR-10).
- **SC-4**: The identical fixture run through `--incremental`, `--check`,
  `--system <name>`, and `--resume` leaves all three stale artifacts
  completely untouched in every case, with no `pruned` substring anywhere
  in that run's output (FR-9/FR-10).
- **SC-5**: A `system-paths.json` containing `{"overrides": [...]}` (no
  `"rules"` key) produces exactly one `stderr` warning line naming
  `"rules"` as the correct key, while `_load_overrides()`'s return value
  and every downstream resolution result are provably unchanged from
  pre-feature behavior for the identical input (FR-14/FR-15/FR-16).
- **SC-6**: Every existing test under `tests/` — explicitly including the
  two pre-existing FAILING tests in the `--describe` family, which this
  feature does not touch and whose failure count must not change — stays
  at its pre-feature pass/fail status after this feature lands; the
  complete suite is run once at the end of implementation to confirm zero
  regressions in any file this feature does not itself modify.
