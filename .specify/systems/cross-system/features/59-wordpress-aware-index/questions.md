# Implementation Questions: WordPress-Aware Index Defaults

**Generated**: 2026-09-14
**Feature**: [spec.md](./spec.md)
**Plan**: [plan.md](./plan.md)
**Status**: ANSWERED

> Q1-Q3 are the three decisions this feature's own task framing named
> explicitly, each with a recommendation, to be resolved via this
> workflow's standing delegation (auto-accept recommended answers,
> recorded here for the audit trail). Q4 is a FOURTH decision, discovered
> independently while drafting `spec.md` (the `/smith init` call-path
> gap — see `spec.md` OOS-5/A-3) — it was NOT one of the three named gate
> items, so it is recorded separately here rather than folded into the
> Q1-Q3 delegation trail, mirroring feature 58's own precedent for a
> decision its task framing asked to be evaluated and made directly
> (there, FR-18; here, the opposite scope direction — deliberately NOT
> widening this feature to also fix `/smith init`'s flow).

---

## Q1: Where does WordPress detection live — stub-generation time, or a new resolver tier?

**Options**: A) Detection (`detect_wordpress()`) and the 17-rule generator
(`wp_exclusion_rules()`) live in `scripts/smith-index/run.py` (new sibling
module `wp_defaults.py`), invoked once, at `--init-system-paths` time, to
produce a static `system-paths.json` stub — same mechanism, same file
format, same "optional, heuristic-is-the-engine" contract every other
override already uses. B) Add a new "tier 0" (or similar) to
`path-resolver.py`'s `resolve()` that re-checks `wp-load.php`/
`wp-includes/` on every single file resolution, independent of
`system-paths.json` entirely.

**Recommended**: A — `path-resolver.py`'s own docstring states "Both
interfaces are pure — no side effects, no filesystem writes"; a live
WordPress-detection check inside `resolve()` would mean a filesystem
`stat()` (or two) on every one of potentially thousands of file
resolutions per rebuild, re-checking a condition about the PROJECT ROOT
that cannot change mid-run. `system-paths.json` already IS the "explicit,
generated-once, editable-by-hand" mechanism for exactly this shape of
rule (per the resolver's own module docstring: "the engine, `system-
paths.json` provides explicit overrides via a longest-prefix match") —
reusing it means zero resolver changes, zero new tier, and a project owner
can freely edit or remove the auto-generated WP rules afterward the same
way they'd edit any other stub-generated rule. `BANK-028`'s own Idea
section names this exact tradeoff ("Either extend the path-resolver
heuristic's EXCLUDED handling with a WP detection tier, or have
`/smith init` and `--init-system-paths` generate the exclusion rules
automatically") and this spec's Out of Scope (OOS-1) makes the resolver
non-negotiably off-limits regardless.
**Answer**: A (accepted via delegation).

## Q2: How broad is the garbage-collection fix — WordPress-specific, or general?

**Options**: A) A general (non-WordPress-aware) `prune_stale_index()` on
`IndexRun`, run once after a full (unfiltered, non-resumed) rebuild's walk
completes, deleting any `.meta` whose source is gone or now resolves
`"excluded"` for ANY reason, and any system manifest left with zero files
— reusing the exact stale-predicate `_refresh_full_aggregations()`
already established for incremental mode's aggregation-skip (Problem
Statement item 3), now wired to an actual deletion and run for full
rebuilds. B) A narrower fix scoped only to WordPress: prune only `.meta`
entries whose path starts with `wp-admin/` or `wp-includes/`, or matches
one of the 15 WP-core root files.

**Recommended**: A — `BANK-028`'s second gotcha is phrased generally
("Rebuild does NOT prune stale .meta files/system manifests for
newly-excluded paths... broader than WP") and its own Open Questions
section asks "Should full rebuild garbage-collect .meta for excluded/
deleted sources generally?" — the bank entry itself already frames this as
the broader question. A WordPress-only prune (B) would also fail to clean
up the FAR more common case this feature's own fixture testing needs
anyway — a plain deleted source file, unrelated to WordPress entirely —
and would need to be rewritten (not just extended) the moment OOS-2's
future CMS detections ship, since each would otherwise need its own
copy-pasted prune variant. A single general predicate, reused verbatim
from code that already exists for a different mode, is both less code and
strictly more useful.
**Answer**: A (accepted via delegation).

## Q3: How is the `rules`-vs-`overrides` key gotcha fixed — a warning, or a silent alias?

**Options**: A) `_load_overrides()` emits a one-line `stderr` warning when
the parsed dict has no `"rules"` key but does have a plausible-but-wrong
sibling key (`"overrides"`, `"override"`, `"mappings"`, `"map"`), naming
the correct key — the dict is still returned completely unchanged; no
behavior change beyond the diagnostic. B) `_load_overrides()` (or
`path-resolver.py`'s tier-2 lookup) silently treats `"overrides"` as an
alias for `"rules"` when `"rules"` is absent, so a mistyped-key file
"just works" without any warning.

**Recommended**: A — the feature description's own framing is explicit:
"Still returns the dict unchanged (no behavior change beyond the
warning)." Silently aliasing (B) would mean two different top-level key
names now BOTH silently succeed with no diagnostic either way, which
doesn't fix the actual problem `BANK-028` reports (a config author
getting no signal that anything is wrong) — it just adds a second
magic key nobody but the resolver's own source code would ever discover,
and does so inside `path-resolver.py`, which this spec's Out of Scope
(OOS-1) keeps off-limits regardless of which option is chosen. A loud (but
non-fatal) warning gives the config author the exact signal `BANK-028`'s
Gotcha 1 says was missing when this cost a rebuild on `attck2026` — they'd
have caught the typo immediately instead of discovering it by re-reading
`path-resolver.py`'s source.
**Answer**: A (accepted via delegation).

---

## Q4 — evaluated directly, not delegated: does this feature also wire `/smith init` into `/smith-index`?

**Discovered independently while drafting `spec.md`** (not one of the
three named gate items above): `skills/smith-index/SKILL.md`'s own
"Auto-invocation" section states "`/smith init` calls `/smith-index` as
its final setup step (per spec Requirement 5)." Re-reading `skills/smith/
SKILL.md` in full while drafting this spec, and re-running `grep -ni
"index" skills/smith/SKILL.md` directly against the file on disk, found
**zero** invocation of `/smith-index` anywhere in that file's actual init
flow — Phase 4 ends at `#### 4.10 Clear Bootstrap Marker` and Phase 5 is a
verification/report step that generates no new files and calls no
external skill. The feature description's Part A framing ("when
`--init-system-paths` runs (and via `/smith init`'s call path)") assumes
this call path exists; independently, on THIS worktree's actual files, it
does not.

**Options**: A) Treat this as a pre-existing, separately-scoped
documentation/behavior drift and do NOT add a new `/smith-index` (or
`--init-system-paths`) invocation to `/smith init`'s flow — WordPress
detection lives entirely inside `mode_init_system_paths()` (FR-3), so it
activates automatically the moment ANY future fix wires `/smith init`
into `--init-system-paths`, with zero further change needed here; add a
one-line documentation cross-reference (FR-19) and an explicit Out of
Scope callout (OOS-5) so a reader comparing this spec against the two
SKILL.md files isn't left thinking the gap was silently missed. B) Fix
the gap as part of this feature — add a new step to `skills/smith/
SKILL.md`'s Phase 4 (or Phase 5) that invokes `/smith-index
--init-system-paths` followed by a full rebuild, closing
`smith-index/SKILL.md`'s "Auto-invocation" claim for real.

**Recommended**: A — this feature's task framing describes itself as
"small, WordPress-focused" and its Out of Scope explicitly rules out
"resolver changes" and other adjacent widening; option B is a materially
larger, separately-motivated change (deciding WHERE in `/smith init`'s
existing 10-step Phase 4 a new `/smith-index` invocation belongs, whether
it should run interactively or silently, and how it interacts with
`#### 4.8`'s own optional system-spec-scaffolding step, which explicitly
exists to help `/smith-index` "route files correctly from day one" — i.e.
B's natural placement is AFTER 4.8, a sequencing decision with its own
blast radius) that stands on its own merits independent of WordPress
detection entirely. Because FR-3 places all WP-detection logic inside
`mode_init_system_paths()` itself rather than at any call site, choosing A
costs nothing when B is eventually tackled as its own feature — no
WP-specific code would need to move or be duplicated.
**Answer**: A (evaluated directly, per this feature's own task framing
asking this exact question — "note as future" — recorded here rather than
silently deferred; `spec.md` OOS-5/FR-19/A-3 carry the concrete decision).

---

Plan-level mechanical resolutions (not gate matters, recorded): the 17
WP-core rules are PREPENDED to the generated stub's `rules` list (ahead of
the generic per-top-level-directory rules), purely for stub readability —
`path-resolver.py`'s longest-prefix-wins matching makes list order
irrelevant to correctness; `wp_defaults.py`'s two constant tuples
(`WP_CORE_DIRS`, `WP_CORE_ROOT_FILES`) are named exactly as such so a
future CMS-detection module (OOS-2) can follow the identical naming
convention; the `_load_overrides` plausible-key list (`"overrides"`,
`"override"`, `"mappings"`, `"map"`) is a small, named, easily-extended
constant, not a fuzzy-match heuristic — see `plan.md` Contracts for the
exact list and per-entry rationale.
