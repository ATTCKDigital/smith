---
feature: 19-manifest-system
branch: 19-manifest-system
created: 2026-05-21
status: BUILT — awaiting manual validation before push
spec: ./spec.md
plan: ./plan.md
questions: ./questions.md
tasks: ./tasks.md
---

# Release: Manifest System & Structured Context Retrieval

**Date:** 2026-05-21
**Branch:** `19-manifest-system` (local-only — NOT pushed)
**Commits:** 7
**Files changed:** 105 (+13,878 / -10)
**Tasks:** 108/108 complete
**Tests:** 69 passing (12 Python parser + 24 JS parser + 22 path resolver + 3 schema contract + 28 hook + 10 skill + 8 E2E)

---

## Summary

Replaces Smith's soft natural-language "go read the system specs" guidance with a deterministic, precomputed hierarchical manifest plus a Haiku-powered navigator that injects relevant file lists into context before reasoning starts. The manifest is automatically maintained by Claude Code hooks (in-session) and git hooks (post-merge/post-checkout). Source files are never modified with metadata — everything lives in `.smith/index/`.

The system ships **public** in smith-repo. Auto-installed by `npx skills add attck/smith` (use `--no-hooks` to opt out).

---

## What Was Built

### New skills
| Skill | Purpose |
|-------|---------|
| `/smith-index` | Full manifest rebuild, with `--check`, `--system <name>`, `--migrate-templates`, `--incremental`, `--resume`, `--init-system-paths` |
| `/smith-navigate` | Haiku-driven manifest navigator. Returns must-read / should-read / reference file lists with whole-file primary-section annotations |

### New hooks
| Hook | Event | Purpose |
|------|-------|---------|
| `manifest-updater.sh` | PostToolUse `Write|Edit` | Updates `.meta` + system manifest after every file edit in any Claude session. Registers LAST in the chain. p95: 102ms (Python), 105-127ms (JS) — well under 500ms budget. |
| `context-loader.sh` | UserPromptSubmit | Detects `/smith-*` commands + natural-language triggers; loads vault + manifest snapshot; injects via `additionalContext`. 13ms (no-trigger), 39-48ms (skill detected) — >100x headroom under 5s budget. |
| `templates/git-hooks/post-merge` | git post-merge | Runs `/smith-index --incremental` to catch up after pulls/merges |
| `templates/git-hooks/post-checkout` | git post-checkout | Same, for branch switches |

### Refactored skills
- **`/smith-explore`** — Phase 1 (Scope Detection) now starts with `/smith-navigate` for manifest-driven candidates, then focused grep on those locations + neighborhoods, escalating to whole-codebase grep only when the manifest doesn't cover the query. Manifest is a **map, not a fence**. Graceful fallback to legacy behavior when `.smith/index/` absent.
- **`/smith-build`** — Pre-PR file-size scan (new step 5.3). Lists files >300 lines in the PR description under "File Size Warnings". Non-blocking advisory.
- **`/smith-audit`** — New "File Size Audit" subsection in the per-system report. 300/500-line threshold counts, top-10 largest files with decomposition suggestions.

### New install scripts
| Script | Purpose |
|--------|---------|
| `scripts/install-parsers.sh` | Copies parsers to `~/.smith/scripts/` (idempotent, `--dry-run`, `--force`, `--uninstall`, `.bak` backups) |
| `scripts/install-hooks.sh` | Auto-registers `manifest-updater.sh` + `context-loader.sh` in `~/.claude/settings.json`. Re-orders manifest-updater LAST in the Write|Edit chain. `--no-hooks` opt-out. |
| `scripts/install-git-hooks.sh` | Per-project git hook installer with `.smith` fallback for existing hooks |

### Parsers + utilities (Phase A foundation)
- `scripts/parsers/parse-python.py` (stdlib ast only, <50ms typical)
- `scripts/parsers/parse-js.js` (vendored acorn 8.x + acorn-jsx + acorn-typescript, ~135ms p95, regex fallback on parse failure)
- `scripts/parsers/vendor/acorn.min.js` (~238KB minified bundle via esbuild; `linguist-vendored=true`)
- `scripts/parsers/path-resolver.py` (heuristic-as-engine + override resolver — **Path 2 model**)
- `scripts/parsers/parser-lib.sh` (per-project override resolver)

### Templates
- `templates/context-manifest.default.json` — Tier-2 default for 4-tier config resolution (8 skill blocks + `_default`)
- `templates/system-paths.json.example` — annotated optional overrides example
- `templates/.gitignore-smith-additions` — selective gitignore fragment
- `templates/constitution-additions.md`, `templates/claude-md-additions.md` — `--migrate-templates` source content
- `templates/git-hooks/post-merge`, `templates/git-hooks/post-checkout`

### Memory file updates
- `settings/claude-md-template.md`: appended "Smith Context System" and "File Size Awareness" sections AFTER the existing rubric. Both marked "Advisory guidance — not a graded rule" per Q9. **Rules 1-7 byte-identical to original.**

### Documentation
- `README.md`: new "Manifest System" section + updated skills/hooks tables
- `CONTRIBUTING.md`: "Vendored Dependencies", "Parser Development", "Hook Chain Ordering"
- `CHANGELOG.md`: comprehensive `[Unreleased]` entry
- `docs/manifest-system.md` (645 LOC): comprehensive user guide

---

## Design Decisions (8 total)

1. **`/smith-navigate` as new skill** (not rename of `/smith-explore`). `/smith-explore` Phase 1 refactored to call navigate first, then expand grep.
2. **Whole-file reads with `[primary: range, label]` annotations** (correctness over efficiency; tight-range mode reserved for future)
3. **3-mode migration**: `/smith init` auto-runs `/smith-index`; manual on-demand; soft warning on missing manifest
4. **4-tier context-manifest resolution**: built-in < repo default < user global < project, with field-level merge
5. **Parser scripts at `~/.smith/scripts/`** (global), with `.smith/scripts/` per-project override capability
6. **Public distribution** via smith-repo
7. **manifest-updater registers LAST** in PostToolUse Write|Edit chain
8. **Sync via Claude hooks + git hooks** (post-merge, post-checkout) — no filesystem-watcher daemon for v1

---

## Resolved Questions (10 total)

| Q | Decision |
|---|----------|
| Q1 | Skip smith-repo's own manifest (system is for consumer projects) |
| Q2 | `/smith-index --migrate-templates` flag for existing projects |
| Q3 | No kill switch for manifest-updater (trust <500ms budget) |
| Q4 | Auto-register hooks during install, `--no-hooks` opt-out |
| Q5 | Selective gitignore: commit `manifest.md` + `config/`, ignore `files/` + `systems/` |
| Q6 | `/smith-index --check` uses hash-only (SHA-256 first 4KB) |
| Q7 | Heuristic-as-engine + explicit overrides (Path 2 — `system-paths.json` is optional) |
| Q8 | Vendor acorn as minified single-file bundle (~238KB actual; ~150KB target) |
| Q9 | Modify existing `settings/claude-md-template.md` (advisory sections after rubric, not new graded rules) |
| Q10 | Soft warning fires once per session, no escalation |

---

## Performance Results (measured)

| Operation | Budget | Measured | Headroom |
|-----------|--------|----------|----------|
| `parse-python.py` | <200ms | ~21ms (509-line file) | ~10x |
| `parse-js.js` | <200ms | ~38ms avg | ~5x |
| `manifest-updater.sh` (Python file) | <500ms | 102ms p95 | ~5x |
| `manifest-updater.sh` (JS file) | <500ms | 105-127ms | ~4x |
| `context-loader.sh` (no skill detected) | <5000ms | 13ms | >100x |
| `context-loader.sh` (skill detected) | <5000ms | 39-48ms | >100x |
| `/smith-index` (8-file fixture) | n/a | 259ms | n/a |
| `/smith-index` (smith-repo's 66 files) | n/a | 1.3s | n/a |
| `/smith-index` (projected 400 files) | <60s | ~8s | ~8x |

---

## Test Results

| Suite | Tests | Status |
|-------|-------|--------|
| Python parser unit tests | 12 | ✅ PASS |
| JS parser integration tests | 24 | ✅ PASS |
| Path resolver tests | 22 | ✅ PASS |
| Parser output schema contract | 3 | ✅ PASS |
| Hook tests (manifest-updater, context-loader, git hooks, chain order) | 28 | ✅ PASS |
| Skill tests (smith-index, smith-navigate) | 10 | ✅ PASS |
| E2E integration tests | 8 | ✅ PASS (3.3s) |
| **Total** | **107** | **✅ PASS** |

---

## Known Limitations (v1)

Documented in `docs/manifest-system.md`:
- Bash-only minimal parsing (full bash function extraction deferred)
- Markdown-only edits don't trigger manifest update (not source files)
- External edits (VS Code, terminal, etc.) don't trigger Claude Code hooks — closed by git hooks for git-based mutations; remaining gap is IDE-only edits
- No filesystem-watcher daemon (deferred to v2)
- No kill switch for manifest-updater (revisit if real builds show stalls)
- No Windows support (FSEvents/inotify abstraction not in scope)
- No tight-range mode (`--tight-ranges` reserved for future iteration after manifest accuracy is validated)

## Implementation Polish Item (Future)

`/smith-index` full-rebuild does NOT prune stale `systems/<name>.md` when overrides reassign their contents. The incremental hook path DOES prune. Worth fixing in a follow-up.

---

## Deviations from Spec

None significant. The plan committed to a v1 simplification for the `context-loader.sh` sub-agent spawn (option **b**: direct manifest read instead of nested `claude --print` invocation). `/smith-navigate` remains fully usable interactively and from skill contexts; only the hook-context spawn is deferred. Documented in `context-loader.sh` header comments.

---

## What Happens Next

This branch is **local-only** — not pushed. Per user direction, the next steps are:

1. **Manual validation on real Smith-using projects** (armory, goldcanna-inventory) — see `MANUAL-TESTING.md` (next file) for step-by-step instructions
2. After manual testing passes → user pushes branch, opens PR, merges → GitHub deploy action publishes to public smith-repo distribution

If manual testing surfaces issues, the branch can be amended in the worktree before push.
