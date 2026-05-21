---
feature: 19-manifest-system
branch: 19-manifest-system
created: 2026-05-21
status: in-progress
---

# Feature: Manifest System & Structured Context Retrieval

## Summary

Smith skills currently rely on soft, natural-language guidance ("read the system specs," "check the vault," "navigate to the relevant files") to point Claude at the right code before it begins reasoning. This guidance is interpreted by the LLM at runtime, which means it can be followed well, poorly, partially, or not at all. The practical consequence is wasted token budget on speculative reads, missed cross-referenced helpers, and inconsistent skill behavior between sessions — the same `/smith-new` invocation against the same codebase can produce materially different file selections from one run to the next.

This feature replaces soft guidance with a deterministic retrieval system. A precomputed hierarchical manifest (`.smith/index/`) describes every source file in the project — its system membership, line count, exports, imports, and notable structural elements (FastAPI routes, React components, exported functions). A Haiku-powered sub-agent (`/smith-navigate`) reads the manifest, matches the user's task to candidate files, and returns a categorized list (Must Read / Should Read / Reference Only) with primary-section annotations. A `UserPromptSubmit` hook (`context-loader.sh`) detects Smith skill invocations, resolves a per-skill config through a 4-tier precedence chain, spawns the navigator when warranted, and injects the assembled context as `additionalContext` before the main session's LLM ever starts reasoning. A `PostToolUse` hook (`manifest-updater.sh`) keeps the manifest current incrementally as files are written or edited.

The manifest is a map, not a fence. Skills like `/smith-explore` continue to grep the broader codebase when the manifest doesn't cover the query or when initial signals suggest impact beyond the navigator's candidate list. Source files are never modified — all generated metadata lives exclusively in `.smith/index/`, which is gitignored and regenerated from the codebase. The system is distributed publicly via `npx skills add attck/smith` and ships with sensible defaults that any consumer project can override at the user-global or per-project level.

## Goals

- Replace soft natural-language navigation with a deterministic, precomputed manifest that every Smith skill consults through the same retrieval path.
- Inject the relevant file list into Claude's context *before* reasoning begins — eliminating speculative reads and missed-file silent failures.
- Keep regular (non-Smith) conversation at zero overhead — the context-loader hook short-circuits if no `/smith-*` command or natural-language trigger is detected.
- Keep source files pristine — all manifest data lives in `.smith/index/`; no comments, no frontmatter, no JSDoc annotations are ever added to application code.
- Make the system robust to manifest staleness — missing or stale manifests trigger soft warnings and graceful degradation to vault-only context, never hard failures.
- Make the system configurable through a 4-tier precedence chain so individual projects, individual users, and the shipped defaults can each contribute pieces of the per-skill config.
- Make existing-project adoption non-disruptive — a soft warning on first use guides the user to run `/smith-index`, but Smith continues to function (with reduced context) until they do.
- Surface file-size hygiene throughout the workflow — 300/500-line thresholds appear in `.meta` warnings, build-time PR notes, audit reports, and constitution/CLAUDE.md template updates.
- Distribute the feature publicly through the existing `smith-repo` install path (`npx skills add attck/smith`) — this is not agency-package-only.

## Non-Goals / Out of Scope

- Migration scripts for existing Smith projects beyond the soft-warning + `/smith-index --migrate-templates` flow (resolved per Q2 — see Resolved Decisions).
- Replacing or modifying `/smith-explore`'s impact-analysis or conflict-detection behavior. Only its Phase 1 discovery step changes.
- Indexing files outside the listed source-file extensions in the initial release. Supported: `.py`, `.js`, `.jsx`, `.ts`, `.tsx`, `.css`, `.html`, `.sh`. All other extensions are skipped.
- Real-time manifest updates outside of `Write|Edit` events. No file-watcher daemon, no inotify integration, no polling. Filesystem-watcher daemon deferred to v2.
- Tight line-range mode for the navigator (`--tight-ranges`). The initial release uses whole-file reads with primary-section annotations only. A tight-range opt-in mode is reserved for a future iteration once the manifest has demonstrated reliability.
- Windows support. macOS and Linux only for the initial release.
- Version-controlling the manifest in full. Per Q5, the auto-generated bits (`.smith/index/files/`, `.smith/index/systems/`) are gitignored; `.smith/index/manifest.md` and `.smith/index/config/` ARE committed (team-shared overview + config).
- Kill switch / disable mechanism for `manifest-updater.sh` in v1. May be added in v2 if real-world fan-out shows stalls (resolved per Q3).

## Users / Stakeholders

- **Smith CLI users (primary)** — developers using Smith skills (`/smith-new`, `/smith-bugfix`, `/smith-debug`, `/smith-build`, `/smith-audit`, etc.) on their own projects. They benefit from more reliable context, fewer missed files, and lower token waste.
- **Smith maintainers** — the attck team owning `smith-repo`. They benefit from a deterministic retrieval layer that makes skill behavior more testable and skill bugs more reproducible.
- **ATTCK Digital agency team** — internal users running Smith across many client codebases. They benefit from per-project overrides (each client's manifest is custom) layered on user-global defaults (their personal preferences) layered on shipped defaults (Smith's curated baseline).
- **New project bootstrappers** — anyone running `/smith init` on a fresh project. They benefit from auto-invocation of `/smith-index` as the last setup step so the manifest exists before any other Smith skill runs.

## Requirements

### 1. Manifest Directory Structure (`.smith/index/`)

A per-project hierarchical manifest lives at `.smith/index/`. The directory is gitignored by default and regenerated from the codebase — it is never version-controlled and never the source of truth for anything in the project.

The structure follows source spec section 1:

- `manifest.md` — top-level overview document. Target ≤50 lines. Contains a systems table (system name, file count, one-line description) and aggregate stats (total source files, files over 200 lines, files over 300 lines, last full index timestamp).
- `systems/<system-name>.md` — one file per system. Target ≤80 lines each. Lists every file in the system with exports and line count, grouped by directory or sub-feature.
- `files/<mirrored-path>/<file>.meta` — per-file metadata mirroring the project's directory tree under `.smith/index/files/`. Contains function-level detail: functions (name, line, params with type hints, return type, docstring first line), classes (name, methods, line), imports, FastAPI/Express route decorators, total line count, and a `⚠️ Exceeds 300-line threshold` marker if applicable.
- `config/context-manifest.json` — per-skill context-loading config. Resolves through the 4-tier precedence chain described in section 4 of Design Decisions below.
- `config/system-paths.json` — path → system mapping rules used by `manifest-updater.sh` and `/smith-index` to assign files to systems.

Behaviors:

- `.smith/index/` is created on first run of `/smith-index` (whether via `/smith init` or manual invocation).
- Every regenerated artifact carries a `Last Updated:` timestamp so staleness can be detected.
- Gitignore strategy (resolved per Q5 → C — selective): `/smith init` merges `templates/.gitignore-smith-additions` into the project's `.gitignore`. That fragment ships these lines:

  ```
  .smith/index/files/
  .smith/index/systems/
  # NOT gitignored (commit these): .smith/index/manifest.md, .smith/index/config/
  ```

  Rationale: the top-level manifest and config files (especially custom `system-paths.json`) are team-shared assets; the per-file `.meta` and per-system manifests churn on every commit and are excluded.

### 2. Python Parser Script (`~/.smith/scripts/parse-python.py`)

A general-purpose Python AST parser used by `manifest-updater.sh` and `/smith-index` to extract metadata from `.py` files. Shipped at the user-global location `~/.smith/scripts/` rather than per-project (see Design Decision 5).

Behaviors:

- Accepts a single file path as argument; emits JSON to stdout.
- JSON shape (per source spec section 2): `functions` (name, line, params with type hints, return type, docstring first line), `classes` (name, methods, line), `imports`, `routes` (method, path, line, function — for FastAPI `@app.get`/`@router.post` style decorators), `lines` (total).
- Uses Python's stdlib `ast` module — no third-party dependencies.
- Completes in <200ms p95 per file.
- Handles malformed input gracefully: on `SyntaxError` or partial parse, returns whatever fields are extractable plus an `errors` array. Never raises an uncaught exception. Never crashes the calling hook.
- Per-project override: if `.smith/scripts/parse-python.py` exists in the active project, `manifest-updater.sh` prefers that over the global script.

### 3. JavaScript/TypeScript Parser Script (`~/.smith/scripts/parse-js.js`)

A general-purpose JS/TS/JSX/TSX parser. Same role as `parse-python.py`, adapted for JS semantics. Shipped at `~/.smith/scripts/`.

Behaviors:

- Accepts a single file path as argument; emits JSON to stdout.
- JSON shape mirrors `parse-python.py` but adapted for JS: exported functions and React components (name, line, params), all imports, route definitions (Express `app.get(...)`, route files), total line count.
- Implementation strategy is an open question (zero-dep regex vs. `@babel/parser`/`acorn`) — see Open Questions section.
- Completes in <200ms p95 per file.
- Handles malformed input gracefully — partial JSON return, never crashes.
- Per-project override: if `.smith/scripts/parse-js.js` exists in the active project, `manifest-updater.sh` prefers that over the global script.

### 4. Manifest Updater Hook (`manifest-updater.sh`)

A `PostToolUse` hook with matcher `Write|Edit` that incrementally updates `.smith/index/` after every file mutation. Fires in both the main session and sub-agents so manifest stays current during heavy parallel builds.

Behaviors (per source spec section 2):

1. Read file path from stdin JSON.
2. Skip non-source files. Only process: `.py`, `.js`, `.jsx`, `.ts`, `.tsx`, `.css`, `.html`, `.sh`.
3. Resolve which parser to invoke. Prefer per-project override (`.smith/scripts/parse-*`) when present; otherwise use global (`~/.smith/scripts/parse-*`).
4. Run the parser; capture JSON output.
5. Generate or update the `.meta` file at `.smith/index/files/<mirrored-path>/<file>.meta`.
6. Map the file to a system using rules in `.smith/index/config/system-paths.json`. If no rule matches, assign to `unassigned`.
7. Update the corresponding system manifest (`.smith/index/systems/<system>.md`) — update the line count and exports for this file's entry.
8. Update `.smith/index/manifest.md` stats (total files, files over threshold, last-updated timestamp).
9. If the file is >300 lines, write the `⚠️ Exceeds 300-line threshold` marker to its `.meta` AND emit an `additionalContext` warning to the calling session (per source spec section 7).
10. Log activity to `~/.smith/logs/hooks.log` with structured entries (timestamp, file, parser invoked, system mapped, ms elapsed, warnings emitted).

Hook registration:

- Registered LAST in the `Write|Edit` PostToolUse hook chain — after `file-change-logger.sh` and `lint-on-save.sh` — so it sees the final post-lint file state (per Design Decision 7).
- Auto-registered during install (resolved per Q4): `npx skills add attck/smith` writes the hook entry into `~/.claude/settings.json` automatically. The installer parses the existing settings.json, adds the hook to the PostToolUse `Write|Edit` array IF not already present, and ensures `manifest-updater.sh` is the LAST entry in that chain. Users can opt out with `npx skills add attck/smith --no-hooks`.

Performance:

- Must complete in <500ms p95 per file edit.
- Sub-agent fan-out (e.g. 20 parallel writes in a heavy build) is bounded by the per-file budget. No kill switch in v1 (resolved per Q3). May be revisited in v2 if real-world heavy builds exhibit stalls.

### 5. `/smith-index` Skill — Full Project Index Rebuild

A new skill at `~/.claude/skills/smith-index/SKILL.md` that performs a full project manifest rebuild. Auto-invoked as the final step of `/smith init`, and callable manually at any time.

Behaviors (per source spec section 3):

- `/smith-index` — full rebuild. Scans every source-file extension, runs parsers, regenerates all `.meta` files, regenerates all system manifests, regenerates the top-level `manifest.md`.
- `/smith-index --check` — reports stale or missing `.meta` files without rebuilding. Staleness is detected via **hash-only** comparison (SHA-256 of the first 4KB of source content) against the `hash` field in each `.meta` (resolved per Q6). Estimated ~5-10s for a 400-file project; acceptable for a maintenance command not on the hot path.
- `/smith-index --system <name>` — partial rebuild restricted to files mapped to one system.
- `/smith-index --migrate-templates` (resolved per Q2) — detects missing template sections in existing `constitution.md` and `CLAUDE.md` files (e.g. "File Size Policy", "Smith Context System", "File Size Awareness", "Project Manifest") and appends them non-destructively. Approach: detect-by-section-header, append-if-missing, write a `.bak` backup of each modified file before applying changes. Idempotent: re-running is a no-op once sections are present.
- `/smith-index --incremental` (added per New Decision #8) — re-parses only the files reported as changed by `git diff` between the prior HEAD and the current HEAD. Used by the `post-merge` and `post-checkout` git hooks (see Component 13) for fast drift catch-up after `git pull` / `git checkout`. Falls back to no-op if `git` is unavailable or the repo has no prior HEAD.
- On first run in a project, copies `templates/context-manifest.default.json` from the Smith install into `.smith/index/config/context-manifest.json` if no project-level config exists yet.
- On first run, copies `templates/system-paths.json.example` to `.smith/index/config/system-paths.json` ONLY if the user wants explicit overrides (per Q7 this file is OPTIONAL — the path resolver now runs heuristic-as-engine; see Component 14 below).
- Reports on completion: total files indexed, files per system, files over 300/500 thresholds, time taken.
- Auto-invoked by `/smith init` as its last setup step.
- Must complete a 100+ file project rebuild in <60 seconds.

### 6. `/smith-navigate` Skill — Manifest Navigator (Haiku Sub-Agent)

A new skill at `~/.claude/skills/smith-navigate/SKILL.md` that serves as the manifest navigator. Runs as a Haiku 4.5 sub-agent spawned by `context-loader.sh`, and also runs standalone when invoked by the user.

Behaviors (adapted from source spec section 4 + Design Decision 1 + Design Decision 2):

- Receives: the user's task description or feature request, the top-level `manifest.md`, optionally specific system manifests if the caller pre-selects likely systems.
- Reads the top-level manifest to identify likely-relevant systems.
- Reads relevant system manifests to identify specific files.
- Reads `.meta` files for large files to identify primary sections relevant to the task.
- Returns a categorized file list with **whole-file reads + primary-section annotations** (NOT tight line ranges — per Design Decision 2).

Output format:

```markdown
## Relevant Files

### Must Read (directly impacted)
- backend/src/api/v1/products.py [primary: 230-380, POST endpoint]
- backend/src/models/schemas.py [primary: 200-280, ProductCreate]

### Should Read (likely affected)
- backend/src/services/shopify_sync_service.py [primary: 1-50, sync interface]
- frontend/src/lib/api/products.ts

### Reference Only (context, don't modify)
- backend/tests/test_products.py
- .specify/systems/system-15-command-center/spec.md

### Systems Affected
- Primary: system-15-command-center
- Also affects: system-03-email-contact
```

Behaviors:

- Standalone usage: `/smith-navigate "where is auth middleware?"` returns the categorized list to the user in chat.
- Sub-agent usage: result is consumed by `context-loader.sh` and injected via `additionalContext`.
- Must complete within 3 seconds.
- Returns a non-fatal "no manifest found" structured response if `.smith/index/manifest.md` is missing — never crashes.

### 7. `/smith-explore` Refactor — Phase 1 Discovery

The existing `/smith-explore` skill is NOT renamed and NOT repurposed (per Design Decision 1). Only its Phase 1 (scope detection / discovery) changes.

Behaviors:

- Phase 1 step 1: call `/smith-navigate` to obtain a candidate file list and affected-systems list from the manifest.
- Phase 1 step 2: grep the candidate locations and their immediate neighborhoods.
- Phase 1 step 3: expand to whole-codebase grep when warranted — either because the manifest didn't cover the query, or because initial grep signals suggest broader impact than the navigator surfaced.
- The manifest is a map, not a fence — `/smith-explore` retains full grep-everywhere capability.
- Phases 2+ (conflict detection, impact analysis, exploration report, decision gate) are unchanged.

### 8. Context Loader Hook (`context-loader.sh`)

A `UserPromptSubmit` hook, main session only, that detects Smith skill invocations and injects assembled context via `additionalContext`.

Behaviors (per source spec section 5, adapted with Design Decisions 2, 3, 4):

1. Parse the incoming user message for `/smith-*` commands or natural-language triggers. If no Smith skill detected, exit 0 immediately — zero overhead for regular conversation.
2. Resolve the effective context-manifest config via 4-tier precedence (see Design Decision 4): built-in fallback → repo-shipped default → user global → project override. Merge field-by-field per skill.
3. Load vault context per resolved config (sessions, ledger, bank, agents, queue — fields and quantities as specified).
4. If the resolved config has `navigator: true`, spawn `/smith-navigate` as a Haiku sub-agent with a 3-second timeout. On timeout, fall back to vault-only context (no hard failure).
5. Assemble the consolidated context block as structured markdown (sample format in source spec section 5, adapted to use the navigator output format from Design Decision 2).
6. Inject via the hook's `additionalContext` JSON response.
7. **Missing-manifest soft warning** (per Design Decision 3): if `.smith/index/manifest.md` does not exist, log a warning to `~/.smith/logs/hooks.log` AND inject the soft warning into `additionalContext`: *"Manifest not initialized — run `/smith-index` to enable structured context retrieval. Proceeding with vault context only."* Then continue with vault-only context. Do NOT auto-rebuild.
8. Log everything to `~/.smith/logs/hooks.log`: skill triggered, config resolution path, vault sections loaded, chars injected, navigator duration, fallback flags.
9. Must complete in <5s p95 total including sub-agent spawn.

Hook registration:

- Auto-registered during install (resolved per Q4): `npx skills add attck/smith` adds `context-loader.sh` to the `UserPromptSubmit` array in `~/.claude/settings.json` IF not already present. Users can opt out with `--no-hooks`.

### 9. `templates/context-manifest.default.json`

Shipped in `smith-repo` at `templates/context-manifest.default.json`. Contains the complete per-skill config block from source spec section 6, covering: `smith-new`, `smith-bugfix`, `smith-debug`, `smith-build`, `smith-audit`, `smith-vault`, `smith-help`, `smith-bank`, and `_default`.

Behaviors:

- Copied into a project as `.smith/index/config/context-manifest.json` by `/smith-index` on first run, if no project-level config exists.
- Acts as Tier 2 in the 4-tier resolution chain (see Design Decision 4).
- Per-skill fields supported: `vault` (with sub-fields `sessions`, `ledger`, `bank`, `queue`, `agents`), `navigator` (bool), `navigator_scope` (`full_project` | `changed_files_context` | `error_context` | `task_specific`), `system_specs` (`none` | `frontmatter_only` | `affected_systems_only` | `all_frontmatter`).

### 10. `templates/system-paths.json.example` — Optional Overrides Only

Shipped in `smith-repo` at `templates/system-paths.json.example`. An example path → system mapping. Projects copy or customize it as `.smith/index/config/system-paths.json` ONLY when they want to override the built-in heuristic (resolved per Q7).

Behaviors (heuristic-as-engine, system-paths.json-as-overrides):

- **`system-paths.json` is OPTIONAL.** The path resolver runs as follows:
  1. Try explicit rules from `.smith/index/config/system-paths.json` first (longest-prefix match wins).
  2. For any path not matched by explicit rules, fall back to a built-in heuristic (see Component 14).
- New directories auto-map without any user action — users only edit `system-paths.json` when they want to correct or override the heuristic's guess for a particular path.
- The shipped example file documents the override syntax (with comments via `_comment` keys) and serves as a starting point for users who want explicit control.
- The original "what if `system-paths.json` is missing" question is collapsed: there is nothing to fall back to — the heuristic IS the engine.

### 13. Git Hooks for Drift Prevention (New Decision #8)

Two git hooks installed per-project during `/smith init` to keep the manifest in sync with external mutation sources (git pull, branch switches, merges).

- `.git/hooks/post-merge` — runs `/smith-index --incremental` to catch up the manifest with merged file changes.
- `.git/hooks/post-checkout` — runs `/smith-index --incremental` to catch up after branch switches.
- `--incremental` is the new `/smith-index` flag documented in Component 5 above: re-parses only files reported as changed by `git diff` between the prior HEAD and the new HEAD.
- Hooks are `.sh` files copied from `templates/git-hooks/post-merge` and `templates/git-hooks/post-checkout`.
- Hooks check if `.smith/index/` exists in the project; if not, they exit 0 silently. This avoids error spam for non-Smith-using developers on the same repo.
- User opt-out: delete the hook files manually, or pass `--no-git-hooks` to `/smith init`.

### 14. Path Resolver — Heuristic Engine with Optional Overrides

Per Q7, path → system mapping is performed by a small resolver function (in `~/.smith/scripts/path-resolver.py` or inlined in `manifest-updater.sh`). The resolver is the engine; `system-paths.json` is an optional overrides layer.

Resolution algorithm (top-to-bottom):

1. If `.smith/index/config/system-paths.json` exists, try each rule by longest-prefix match against the file's path relative to project root. First match wins. Return.
2. Otherwise fall through to the heuristic:
   - `services/<name>/...` → `system-<name>`
   - `backend/<name>/...` → `system-backend-<name>`
   - `frontend/<name>/...` → `system-frontend-<name>`
   - Any other top-level source directory (not `tests/`, `docs/`, `node_modules/`, `.venv/`, `vendor/`, `dist/`, `build/`, `.git/`) → `system-<dirname>`
   - `tests/`, `docs/`, `node_modules/`, `.venv/`, `vendor/`, `dist/`, `build/` → `unassigned` (excluded from system-membership; still indexed if extension is allowed).
3. If a file is in the project root (no enclosing directory) → `unassigned`.

Behaviors:

- The heuristic is fully deterministic and documented in `docs/manifest-system.md`.
- A newly-created directory containing source files is automatically assigned to a system on first edit, without requiring `system-paths.json` updates.
- Users who want different rules add explicit overrides to `system-paths.json` (longest-prefix wins over heuristic).

### 11. 300-Line File Size Enforcement (Five Touchpoints)

Per source spec section 7, file-size hygiene surfaces in five places. None of them block — all are advisory.

- **PostToolUse warning** — `manifest-updater.sh` writes the `⚠️ Exceeds 300-line threshold` marker to `.meta` and injects an `additionalContext` warning when a file crosses 300 lines.
- **`/smith-build` PR description** — at build time, before opening the PR, all modified files are checked. Files over 300 lines are listed in the PR description with a warning. Never blocks the PR.
- **`/smith-audit` report** — includes a file-size section: count of files >300 lines, count of files >500 lines, top 10 largest files with decomposition recommendations.
- **`templates/constitution.template.md`** — gets the "File Size Policy" section verbatim from source spec section 7.
- **`settings/claude-md-template.md` (the existing global rubric template — per Q9, NOT a new `templates/CLAUDE.template.md`)** — gets the "File Size Awareness" section appended after the rubric block.

### 12. Memory & Template Updates

Updates to the files that `/smith init` writes for NEW projects (per source spec section 8):

- **`templates/constitution.template.md`** — adds two new sections:
  - "File Size Policy" (300-line guideline, 500-line decomposition threshold, exemption rules for schemas/auto-generated files).
  - "Project Manifest" (manifest maintained automatically by hooks; source files must not contain Smith metadata; run `/smith-index` after major refactors; manifest is gitignored per the selective rules in Component 1).
- **`settings/claude-md-template.md`** (the EXISTING global rubric template — resolved per Q9; NOT a new `templates/CLAUDE.template.md` file) — append two new advisory sections AFTER the existing Rules 1-7 rubric block. These are advisory sections, not new graded rules:
  - "Smith Context System" (instructs Claude to use injected context first; describes Must Read / Should Read / Reference Only categories; describes fallback behavior when injection is absent).
  - "File Size Awareness" (instructs Claude to check `.meta` files before reading large files; warns against full reads of files over 300 lines).

These are TEMPLATE updates — they go into NEW projects via `/smith init`. Existing projects pick them up via `/smith-index --migrate-templates` (resolved per Q2).

## Design Decisions

### Decision 1: Skill Naming and Architecture — New `/smith-navigate`, Refactor `/smith-explore`

**Decision:** Create a NEW skill `/smith-navigate` as the manifest navigator (Haiku sub-agent). Do NOT rename or repurpose the existing `/smith-explore`. Refactor only `/smith-explore`'s Phase 1 (scope detection) to call `/smith-navigate` first, then grep candidate locations + neighborhoods, with the option to expand to whole-codebase grep when the manifest doesn't cover the query.

**Rationale:** `/smith-explore` already has well-established semantics (pre-change exploration, conflict detection, impact analysis, decision gate). Renaming or repurposing it would silently change behavior for existing users and conflate two distinct concerns: cheap manifest lookup (the new navigator's job) vs. expensive pre-change reconnaissance (`/smith-explore`'s job). Keeping them separate also keeps the navigator small and fast (Haiku, 3-second budget) — embedding navigator logic inside `/smith-explore` would couple two budgets and make the navigator harder to reuse from `context-loader.sh`. The manifest is treated as a map, not a fence: `/smith-explore` retains the ability to grep the whole codebase when initial signals suggest broader impact.

**Alternatives considered:**
- Rename `/smith-explore` → `/smith-navigate` (source spec section 4 mentions this as a fallback). Rejected because it silently breaks existing user muscle memory and conflates concerns.
- Embed navigator logic inside `/smith-explore` and skip the new skill entirely. Rejected because the navigator needs to be cheap and fast (Haiku sub-agent), reusable from hooks, and independently invokable by users for ad-hoc lookups.

### Decision 2: Navigator Output Format — Correctness Over Efficiency

**Decision:** `/smith-navigate` returns **whole-file reads with primary-section annotations**, NOT tight line ranges. Example format:

```markdown
### Must Read
- backend/src/api/v1/products.py [primary: 230-380, POST endpoint]
- backend/src/models/schemas.py [primary: 200-280, ProductCreate]
```

Tight line-range mode is reserved as a future opt-in (`--tight-ranges`) once the manifest has demonstrated reliability.

**Rationale:** A stale or imprecise `.meta` file is a silent correctness failure if it causes Claude to miss a cross-referenced helper or imported symbol the task actually depends on. The cost of that failure (wrong fix, missed bug, broken refactor) is much higher than the cost of reading slightly more tokens. Whole-file reads with primary-section annotations give Claude both the precise focus (the annotation tells it where to start) and the safety net (full file context if the annotation is wrong or incomplete). Tight ranges optimize for a token-budget concern that is real but secondary, and they introduce a failure mode that's hard to detect — Claude won't know what it doesn't know.

**Alternatives considered:**
- Tight line ranges from the start (source spec section 4 mentions line ranges in the example output). Rejected for the silent-correctness-failure reason above.
- Whole-file reads with no annotations. Rejected because the annotation provides meaningful navigation guidance for free, and removing it would force Claude to scan the entire file every time.

### Decision 3: Existing-Project Migration — Three Coexisting Behaviors

**Decision:** Three behaviors must coexist for existing projects:

1. **`/smith init` step:** when bootstrapping Smith on a fresh project, `/smith init` runs `/smith-index` automatically as its last setup step.
2. **Manual on-demand:** `/smith-index` is always callable for full rebuild (with `--check` and `--system <name>` flags).
3. **Soft warning on missing manifest:** if `context-loader.sh` fires for a `/smith-*` skill and `.smith/index/manifest.md` is missing, it logs a warning to `~/.smith/logs/hooks.log` and injects a soft-warning note ("Manifest not initialized — run `/smith-index` to enable structured context retrieval. Proceeding with vault context only.") into `additionalContext`. Then continues with vault-only context loading.

There is NO auto-rebuild on first use.

**Rationale:** Indexing is heavy (30-60s for ~400 files) and should never surprise the user mid-task. Auto-rebuilding when a skill is invoked would inject a long, unexpected wait into the very workflow the user is trying to start. The soft-warning + manual-rebuild path keeps Smith functional (vault context still loads) while making the user aware that better context is available with one explicit command. The `/smith init` auto-invocation handles fresh projects cleanly because that's already a deliberate setup moment where heavy work is expected.

**Alternatives considered:**
- Auto-rebuild on first detected miss. Rejected — surprises the user with a 30-60s wait at exactly the wrong moment.
- Hard-fail on missing manifest. Rejected — too aggressive; Smith should degrade gracefully.
- Silent fallback with no warning. Rejected — the user needs to know they're getting reduced context.

### Decision 4: `context-manifest.json` 4-Tier Resolution with Field-Level Merge

**Decision:** Resolve `context-manifest.json` through four precedence tiers, most-specific wins, merged field-by-field per skill:

1. **Built-in fallback** — compiled into `/smith-index` skill (the `_default` block from source spec section 6). Last-resort safety net.
2. **Repo-shipped default** — `smith-repo` ships `templates/context-manifest.default.json` with the full per-skill config. Copied into the project on `/smith-index` first run.
3. **User global** — optional `~/.smith/config/context-manifest.json`. Applies across all of the user's projects.
4. **Project override** — `.smith/index/config/context-manifest.json`. Per-project. Gitignored by default but committable if the team wants shared config.

`context-loader.sh` resolves the effective config per-skill, merging field-by-field. Example: a project can override `navigator_scope` for `/smith-build` without restating the entire `smith-build` block — the missing fields fall through to user-global, then to repo-shipped default, then to built-in.

**Rationale:** The 4-tier chain mirrors well-understood precedence patterns (`.env`, `git config`, `npm config`) and gives every constituency a clean place to express preferences. Field-level merge is essential because forcing users to restate full skill blocks to override a single field is high-friction and brittle (drift between the user's version and the shipped default becomes invisible). The built-in fallback ensures Smith always has a usable config even if all four files are missing or malformed.

**Alternatives considered:**
- 2-tier (shipped default + project override) — simpler but doesn't accommodate user-wide preferences. Rejected.
- Whole-skill-block override (no field merge) — simpler to implement but high-friction for users. Rejected.

### Decision 5: Parser Scripts Live Globally at `~/.smith/scripts/`

**Decision:** `parse-python.py` and `parse-js.js` ship at the user-global location `~/.smith/scripts/`, installed by `npx skills add attck/smith`. They are NOT placed at `.smith/scripts/` per-project (which is where source spec section 2 originally put them). A per-project escape hatch exists: if `.smith/scripts/parse-python.py` (or `parse-js.js`) is present in the active project, `manifest-updater.sh` prefers that over the global one.

**Rationale:** Parser scripts are general-purpose utilities — they extract Python ASTs and JS exports the same way regardless of project. Placing them per-project would duplicate identical files across every Smith-using project and create a maintenance nightmare: a bug fix in the parser would require regenerating every project's local copy. Global placement mirrors how `~/.smith/logs/hooks.log` already works in the source spec (user-global, not per-project). The per-project escape hatch preserves the ability for advanced users to fork parsing behavior for a specific project without forking `smith-repo`.

**Alternatives considered:**
- Per-project as in source spec section 2. Rejected — duplication and maintenance burden.
- Global only, no escape hatch. Rejected — power users need to override parsing for unusual projects.

### Decision 6: Public Distribution via `smith-repo`

**Decision:** All components — parsers, hooks, `/smith-index`, `/smith-navigate`, templates, constitution/CLAUDE.md edits — ship in `smith-repo` for public distribution via `npx skills add attck/smith`. This is NOT an agency-package-only feature.

**Rationale:** The manifest system addresses a fundamental Smith-distribution-level concern (reliable context retrieval) that affects every public user of Smith, not just the agency. Restricting it to the agency package would mean public users continue to suffer the soft-navigation reliability problems this feature is designed to solve. The infrastructure (parsers, hooks, skills) is also general-purpose — there's no agency-specific logic that would need to be partitioned off.

**Alternatives considered:**
- Agency-package-only initial release. Rejected — the problem this solves is universal to Smith users.

### Decision 7: Hook Registration Order — `manifest-updater.sh` Runs LAST

**Decision:** `manifest-updater.sh` (PostToolUse, `Write|Edit`) registers LAST in the hook chain — after the existing `file-change-logger.sh` and `lint-on-save.sh` — so it captures the final file state after any lint reformatting.

**Rationale:** Lint hooks (`lint-on-save.sh`) reformat files after Write/Edit. If `manifest-updater.sh` ran before the linter, the parsed metadata would reflect the pre-format file (wrong line numbers for exports, possibly different structure). Running last ensures the `.meta` file matches what's actually on disk after all post-write transformations complete. This also aligns with the principle that observability hooks (like `file-change-logger.sh`) should fire early to capture intent, while derivation hooks (like `manifest-updater.sh`) should fire late to capture final state.

**Alternatives considered:**
- Register first (capture intent). Rejected — produces wrong line numbers after lint.
- Register in the middle. Rejected — no benefit, just makes ordering brittle.

### Decision 8: Sync Mechanism for Drift Prevention — Claude Code Hooks + Git Hooks

**Decision:** The manifest is kept in sync via **two layers of hooks installed per-project**:

1. **Claude Code hooks** — `manifest-updater.sh` (PostToolUse Write|Edit) catches every Smith-mediated file mutation in real time.
2. **Git hooks** — `.git/hooks/post-merge` and `.git/hooks/post-checkout` (installed by `/smith init`) call `/smith-index --incremental` to catch up after `git pull`, `git merge`, and `git checkout`. These re-parse only files reported as changed by `git diff` between the prior HEAD and the new HEAD.

A filesystem-watcher daemon is explicitly **skipped for v1** and deferred to v2.

**Rationale:** Once Claude Code hooks cover in-session mutations, the dominant remaining drift source is git operations (`git pull` after a teammate's commit, `git checkout` between branches, `git merge`). Adding two git hooks at install time closes ~95% of remaining drift cases at a tenth of daemon complexity — no long-running process, no inotify/FSEvents platform divergence, no permission prompts, no resource overhead between sessions. Users editing files in a non-Claude-Code tool (e.g. VS Code directly) without ever running git are the last 5%, and they can run `/smith-index --check` then `/smith-index` manually when they notice — which is the exact maintenance command-line use case `--check` was designed for (Q6).

**Alternatives considered:**
- **Pure Claude Code hook only.** Rejected — leaves teammate-pulled changes and branch switches silently stale until next Smith invocation in the affected files.
- **Daemon + hooks.** Rejected — scope expansion. A daemon means a launchd plist / systemd unit, restart logic, log rotation, kill semantics, and platform-specific FSEvents/inotify glue. Not worth the cost for the marginal 5% drift coverage.
- **Daemon-only (no Claude Code hooks).** Rejected — daemon is paused/stopped during many sessions (laptop sleep, manual stop, install error); the manifest would be stale during the moments it matters most.

## Hard Constraints

- Source files NEVER contain Smith metadata. No `SMITH:AUTO-GENERATED` comments, no frontmatter, no JSDoc additions, no inline annotations. All metadata lives exclusively in `.smith/index/`.
- `manifest-updater.sh` must complete in <500ms p95 per file edit.
- `context-loader.sh` must complete in <5s p95 total, including sub-agent spawn.
- Parser scripts (`parse-python.py`, `parse-js.js`) must complete in <200ms p95 per file and handle malformed input gracefully (partial JSON return, no uncaught exceptions).
- Top-level `manifest.md` must stay ≤50 lines.
- Per-system manifests (`systems/<name>.md`) must stay ≤80 lines.
- All hook activity is logged to `~/.smith/logs/hooks.log` with structured entries.
- All manifest files are gitignored by default. The manifest is regenerated from the codebase and never version-controlled.

## Acceptance Criteria

### Functional

- [ ] `/smith-index` rebuilds the full manifest for a 100+ file project in <60 seconds.
- [ ] Editing a `.py` file triggers `manifest-updater.sh` and updates the `.meta` + system manifest within 500ms.
- [ ] `/smith-navigate "where is X?"` returns a categorized file list with primary-section annotations in <3 seconds.
- [ ] Invoking `/smith-new` triggers `context-loader.sh`, which injects vault + navigator context within 5 seconds total.
- [ ] Regular conversation (no `/smith-*` command and no natural-language trigger) does NOT trigger any context injection.
- [ ] `/smith-help` and `/smith-vault` receive zero context overhead.
- [ ] When `.smith/index/manifest.md` is missing, `context-loader.sh` injects the soft warning and falls back to vault-only context.
- [ ] Source files have NO Smith metadata added anywhere — verified by scanning sample edits across `.py`, `.js`, `.ts`, `.tsx` files.
- [ ] `/smith-explore` Phase 1 calls `/smith-navigate` first, then expands with grep as needed (including whole-codebase grep when warranted).
- [ ] `/smith-build` PR descriptions list files over 300 lines with a warning (never blocks).
- [ ] `/smith-audit` reports file-size findings (counts at 300/500 thresholds, top 10 largest with decomposition recommendations).
- [ ] Parser scripts in `~/.smith/scripts/` are used by default; per-project overrides at `.smith/scripts/` take precedence when present.
- [ ] `context-manifest.json` resolution honors the 4-tier precedence chain with field-level merging.
- [ ] `/smith init` auto-invokes `/smith-index` as its last setup step on fresh projects.
- [ ] `/smith-index --migrate-templates` detects missing template sections in existing `constitution.md` / `CLAUDE.md` and appends them non-destructively (with `.bak` backups).
- [ ] `/smith-index --check` uses hash-only (SHA-256 of first 4KB) comparison for staleness detection — no mtime field in `.meta` schema.
- [ ] A newly-created directory containing source files is automatically assigned to a system on first edit, via the built-in heuristic, without requiring `system-paths.json` updates.
- [ ] Soft-warning (manifest missing) fires at most once per session; no escalation logic in v1.
- [ ] `git pull` triggers manifest catch-up via the `post-merge` hook running `/smith-index --incremental`.
- [ ] `git checkout` triggers manifest catch-up via the `post-checkout` hook running `/smith-index --incremental`.
- [ ] `/smith-index --incremental` re-parses only files changed between two refs (verified by diffing the prior HEAD against the new HEAD).
- [ ] `npx skills add attck/smith` auto-registers `manifest-updater.sh` and `context-loader.sh` in `~/.claude/settings.json`; `--no-hooks` skips registration.

### Performance

- [ ] `manifest-updater.sh` <500ms p95 per file edit.
- [ ] `context-loader.sh` <5s p95 including sub-agent spawn.
- [ ] Parsers <200ms p95 per file.
- [ ] `/smith-navigate` <3s p95 per invocation.
- [ ] `/smith-index` full rebuild <60s for 100+ file project.

### Quality

- [ ] All hooks log to `~/.smith/logs/hooks.log` with structured entries (timestamp, hook, ms elapsed, outcome, warnings).
- [ ] Parser scripts handle malformed source gracefully — verified by feeding deliberately broken `.py` and `.js` samples; both return partial JSON, neither throws.
- [ ] Top-level manifest ≤50 lines; per-system manifests ≤80 lines.
- [ ] `manifest-updater.sh` is registered LAST in the `Write|Edit` PostToolUse hook chain (after `file-change-logger.sh` and `lint-on-save.sh`).
- [ ] `context-manifest.json` 4-tier resolution is observable in logs (which tier provided which field).

## Resolved Decisions (from Questions Gate)

The 8 open questions originally listed here, plus 2 new questions surfaced from plan.md's Implementation Discoveries, were resolved at the questions gate. Full reasoning lives in `./questions.md`. Summary of answers (10 questions + 1 new architectural decision = 11 changes total):

1. **Smith-repo's own manifest** — **RESOLVED → B** (skip). The system is for consumer projects only; smith-repo does not run `/smith-index` on itself. Reflected in Non-Goals and in plan.md Phase 4 (removed).

2. **Migration helper for existing Smith projects** — **RESOLVED → B** (`/smith-index --migrate-templates` flag). See Requirement 5 (skill component) and the new acceptance criterion.

3. **Sub-agent fan-out cost / kill switch** — **RESOLVED → B** (no kill switch in v1). Reflected in Non-Goals and Requirement 4 performance notes.

4. **JS parser implementation strategy** — **RESOLVED** (in plan.md research.md) → `acorn`. Storage refinement in Q8 below.

5. **Hook registration during install** — **RESOLVED → A** (auto-register, `--no-hooks` opt-out). Reflected in Requirement 4 and Requirement 8 hook-registration sub-sections.

6. **`.smith/index/` gitignore default** — **RESOLVED → C** (selective). Ship `templates/.gitignore-smith-additions` excluding `files/` and `systems/`; commit `manifest.md` and `config/`. Reflected in Requirement 1 behaviors.

7. **Manifest staleness detection mechanism** — **RESOLVED → B** (hash-only). SHA-256 of first 4KB. No mtime field in `.meta` schema. Reflected in Requirement 5 (`--check` description), data-model, and acceptance criteria.

8. **System auto-detection without `system-paths.json`** — **RESOLVED → Path 2** (heuristic-as-engine, system-paths.json-as-optional-overrides). `system-paths.json` is now optional. See new Requirement 14 (Path Resolver) for the full algorithm.

9. **CLAUDE.md template — new file or modify existing?** — **RESOLVED → A** (modify existing `settings/claude-md-template.md`; append "Smith Context System" and "File Size Awareness" sections AFTER the rubric block; NOT new graded rules). Reflected in Requirement 12. Invalidates plan.md Implementation Discovery #1 (`templates/CLAUDE.template.md` is NOT a new file).

10. **Soft-warning frequency** — **RESOLVED → B** (once per session, no escalation). Reflected in acceptance criteria and plan.md Risk R6.

**New Decision #8 (architectural — emerged during questions gate):** Sync mechanism for drift prevention uses Claude Code hooks + git hooks layer; filesystem-watcher daemon deferred to v2. See Design Decision 8 above and Requirements 13 and 14.

## Assumptions

- `smith-repo` currently has no `.specify/systems/` structure. (Verified — it's the distribution itself, not a consumer project, so this spec uses the flat `specs/19-manifest-system/` layout.)
- Existing PostToolUse hooks (`file-change-logger.sh`, `lint-on-save.sh`) are well-behaved and do not depend on running last — i.e. they don't read or depend on artifacts produced by hooks that haven't yet run.
- Users are running macOS or Linux. Windows support is out of scope for the initial release.
- Haiku 4.5 is the navigator model. The cost-per-invocation and 3-second budget are calibrated against Haiku 4.5's latency profile.
- The Claude Code hook interface (`PostToolUse`, `UserPromptSubmit`, `additionalContext` JSON injection) is stable for the duration of this feature's implementation and rollout.
- `~/.smith/` already exists as a user-global Smith state directory (used today for `logs/hooks.log`), so adding `~/.smith/scripts/` and `~/.smith/config/` does not require new bootstrap infrastructure.

## References

- **Source requirements document:** `~/Downloads/manifest-system (1).md` (615 lines, dated 2026-05-19). Primary source spec.
- **Source spec section 1** — Manifest Directory Structure → implemented in Requirements section 1.
- **Source spec section 2** — Meta File Generation Hook + Parser Scripts → implemented in Requirements sections 2, 3, 4.
- **Source spec section 3** — Full Index Rebuild → implemented in Requirements section 5.
- **Source spec section 4** — Manifest Explorer Skill → implemented in Requirements sections 6 and 7 (split into new `/smith-navigate` + refactored `/smith-explore`, per Design Decision 1).
- **Source spec section 5** — Context Injection Hook → implemented in Requirements section 8.
- **Source spec section 6** — Context Manifest Configuration → implemented in Requirements section 9 (with 4-tier resolution layered on top, per Design Decision 4).
- **Source spec section 7** — File Size Enforcement → implemented in Requirements section 11.
- **Source spec section 8** — Memory File Updates → implemented in Requirements section 12.
- **Smith vault sessions** — prior conversations refining the design decisions in this spec. Captured in this brief; no standalone debug session log was produced.

2026-05-21 11:53:00 — 19-manifest-system
2026-05-21 14:32:00 — 19-manifest-system (post-questions-gate update; 10 answers + 1 new decision applied)
