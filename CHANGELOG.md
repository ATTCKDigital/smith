# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Task-based LLM backend (23-task-llm-backend / PR #23)** — inverts
  the orchestration of `/smith-index --describe` and the three workflow
  incremental paths (`/smith-new`, `/smith-bugfix`, `/smith-debug`) so
  LLM calls inherit the user's Claude Code session auth →
  **subscription billing**. The v2 direct-HTTPS path (urllib.request →
  api.anthropic.com using `ANTHROPIC_API_KEY`) is removed entirely;
  v3 ships a single Task-spawning backend.
  - Skill prose in `skills/smith-index/SKILL.md` now drives the
    description loop directly, spawning one Task per file
    (`subagent_type: general`, `model: claude-haiku-4-5`). The 2am
    scheduler (`scheduler/smith-scheduler.sh`) already invokes
    `claude --print` which IS a Claude Code session — same code path
    serves scheduled and interactive runs (no env-var branching).
  - Three workflow SKILL.md files replace `python3 meta_describe.py
    update-touched ...` shell-outs with inline Task spawning.
  - New helper split: `scripts/parsers/describe_discover.py` (file
    walk + cache_hit), `scripts/parsers/describe_write.py`
    (build-prompt + apply subcommands), `scripts/parsers/
    describe_checkpoint.py` (JSONL log + state),
    `scripts/parsers/index_common.py` (shared utilities extracted
    from run.py per plan.md Decision 3).
  - `scripts/parsers/meta_describe.py` becomes structural-only:
    every LLM-call code path removed (`_default_haiku_call`,
    `HaikuClient`, `HaikuUnavailable`, `describe_file`,
    `update_touched`, `_describe`, `_safe_json_object`, the
    `update-touched` CLI entrypoint, argparser, `main()`, and the
    `__main__` block). Public helpers (`qualifying_methods`,
    `summarize_for_module_prompt`, `build_method_prompt`, `truncate`,
    `MODULE_SYSTEM`, `METHOD_SYSTEM`) are renamed to drop their
    leading underscore; backward-compat aliases preserve PR #21
    test imports.
  - `scripts/smith-index/run.py` deletes `mode_describe`,
    `_describe_one_file`, `_read_meta_text`, `_extract_hash_from_meta`,
    and the CLI flags `--describe`, `--batch-size`,
    `--llm-batch-size`, `--threshold`, `--model`, `--no-interactive`.
    `--describe` is now a flag of the skill, not the script.
  - Runtime model probe (Q7) verifies the Haiku override is honored
    before the bulk loop starts; aborts with a clear error otherwise
    to prevent silent ~30× quota burn on the session's primary model.
    `--skip-model-probe` bypasses.
  - Pre-flight estimate + confirmation gate (Q4): prints
    `Will spawn N Tasks (~M methods); ~T minutes`, asks
    `Proceed? (y/N)`. `--yes` bypasses (required for the scheduler).
  - Sequential within-batch (Q2): one Task at a time per batch for
    simpler per-Task error handling and visible progress.
  - Per-method-split (Q3): files with >15 qualifying methods spawn
    one Task per method instead of one Task per file.
    `--per-method-threshold` configures the cutoff.
  - Exponential backoff retry on Task failure (Q1): 5s → 10s → 20s,
    max 3 attempts per Task. After 3, log `failed` and continue —
    no run-level abort.
  - Test stub (`SMITH_TASK_STUB=1`) bypasses Task spawn and reads
    from `tests/fixtures/task-stub-responses.json`. Q5 fail-loud
    semantics: missing `method_id` in fixture → exit 4 with an error
    naming the absent id.

### Fixed

- **Hash-cache bug from PR #21** — v2 wrote
  `Described-Against-Hash:` as `sha256(full_source)` but compared it
  against `sha256_first_4kb(file)` at the cache-check site. Cache
  never hit for files larger than 4KB. v3 standardizes on
  `sha256_first_4kb` for both, matching the `.meta` `Hash:` field.
  Re-running `/smith-index --describe` on an unchanged repo now
  actually short-circuits as designed.

### Removed

- `meta_describe.py update-touched` CLI (internal-only; all in-repo
  callers updated to the v3 helpers).
- `ANTHROPIC_API_KEY` is no longer read by any code path. Existing
  cron jobs or scripts that relied on the env var must migrate to
  invoking `/smith-index --describe --yes` via `claude --print`.

### Added

- **Configurable base branch per project (24-configurable-base-branch)** — Smith no longer hardcodes `main`/`origin/main` as the integration branch. The base branch is now a per-project value read from a new `base_branch:` field in the constitution frontmatter (`.specify/memory/constitution.md`), defaulting to `main`.
  - **New helper `skills/smith/scripts/get-base-branch.sh`** — read-only, side-effect-free script that parses `base_branch:` from the constitution's YAML frontmatter (via `awk`, fence-scoped to the first block, whitespace/quote-trimmed) and echoes it. Always exits 0 and always emits a branch name — it falls back to the literal `main` on any non-resolution (not in a git tree, no constitution file, missing/empty/whitespace-only field), so it is safe inside `$(...)` under `set -e`. Scaffolded to `.specify/scripts/bash/get-base-branch.sh` automatically via the existing `scripts/* → .specify/scripts/bash/` copy step.
  - **`/smith` interview auto-detect** — the intake now includes a base-branch question (distinct from the Q25 feature-branch *naming* question) that auto-detects the default branch via `git symbolic-ref refs/remotes/origin/HEAD | sed 's|refs/remotes/origin/||'`, presents it as the recommended value (falling back to `main` when detection fails), lets the user override it, and writes the choice to `base_branch:`. The codebase detection report gains a "Default Branch" row, and a `Bash(.specify/scripts/bash/get-base-branch.sh:*)` permissions allow-entry is added to the generated `.claude/settings.json`.
  - **All skills resolve the base branch dynamically** — `smith-new`, `smith-bugfix`, `smith-build`, `smith-finish`, and `smith-queue` now resolve `BASE_BRANCH=$(.specify/scripts/bash/get-base-branch.sh)` and use `origin/$BASE_BRANCH` for fetch/worktree/checkout/pull/merge-detection/diff operations. Every `gh pr create` now passes an explicit `--base "$BASE_BRANCH"` so PR targeting is deterministic regardless of the local checkout's upstream default.
  - **`/smith-index --migrate-templates` backfill** — gains an idempotent step that appends `base_branch: main` to an existing constitution that lacks the field (handles both an existing frontmatter block and a frontmatter-less constitution), and never overwrites a user-set value.
  - **Fully backwards-compatible** — projects with no constitution, no frontmatter, or no `base_branch:` field resolve to `main`, so existing `main`-based projects behave byte-for-byte as before. The current-HEAD bootstrap fallback in `/smith` init (`git rev-parse --abbrev-ref HEAD || echo main`) is intentionally left as-is (it captures the current branch, not the base branch). New regression test `tests/get-base-branch.test.sh` asserts the helper across all states. Closes BANK-003.

- **`/smith-update` skill** — first-class skill for keeping Smith up to date. Detects the installed commit SHA (via new `~/.smith/.installed-version` written by `install.sh` on every run) against the latest upstream main. Prompts "Smith is X commits behind. Update? (y/n)". On accept: snapshots `~/.claude/skills/`, `~/.claude/hooks/`, and `~/.claude/settings.json` to `~/.smith/.backups/<ISO-timestamp>/` (GC keeps the last 3), clones smith-repo to a temp dir, runs `./scripts/install.sh -y`, restores the snapshot on non-zero exit. When invoked inside a Smith-initialized project, also refreshes `.specify/scripts/bash/*.sh` and `.claude/commands/smith.*.md` (NEVER touches non-`smith.*` commands), runs `/smith-index --migrate-templates`, and surfaces a 3-option prompt (structural / structural+descriptions / defer) if `.smith/index/` is absent. Detects orphaned Smith-owned files (hooks, skills, project `smith.*.md`) no longer in upstream — unified detect-list-confirm prompt, default = keep. Pre-versioning installs (no `.installed-version`) get a silent baseline write — no false "X commits behind" prompts. Network failure exits cleanly with `"Unable to reach upstream — {git error verbatim}"`. `gh api compare` first, shallow-clone + `git rev-list --count` fallback when `gh` is missing. Workflow-gate compliant (PR #20): creates `update-<timestamp>.yaml` marker on entry, clears on exit. **Schema-version awareness** (Q9-B): reads `scripts/parsers/meta_schema_version.txt` from the upstream clone and compares against the project's `.smith/index/.schema-version` to detect manifests generated against an older `.meta` schema; on mismatch, prompts to regenerate via `/smith-index`.

- **`scripts/dedupe-settings.sh`** — helper invoked by `/smith-update` to collapse duplicate hook entries in `~/.claude/settings.json` accumulated from past non-idempotent installer runs. Touches only the `hooks` namespace; user-added entries are preserved. Backs up to `<settings>.predupe-<timestamp>` before mutating; aborts on invalid-JSON output.

- **`scripts/parsers/meta_schema_version.txt`** — single-line file containing the integer schema version of `.meta` files. Manifest v2 (PR #21) is version `2`. Lays groundwork for forward-compatible schema migrations.

- **`/smith-index` writes `.smith/index/.schema-version`** at the end of every full rebuild — the marker `/smith-update` reads to detect schema drift.

- **Workflow-gate hook** — new `hooks/workflow-gate.sh` PreToolUse hook on `Bash` and `Write|Edit` that denies file-modifying tool calls when no `.smith/vault/active-workflows/*.yaml` marker exists. Enforces Smith's core discipline at the tool layer: all file edits must happen inside a top-level workflow. Verbose deny message lists the three workflow commands and names the blocked file/subcommand. Exempts read-only Bash, vault-internal infrastructure writes (`sessions, bank, ledger, queue, agents, todo, reports, index, audits` — but NOT `active-workflows/` itself, to prevent forged-marker bypass), and projects without `.smith/` installed (no Smith → not our place to gate). Layers AFTER existing `security-guard-{bash,files}.sh` so security blocks take precedence. Logs every block to `~/.smith/logs/hooks.log`. Resolves project root via `git rev-parse --git-common-dir` so it works correctly from subagent worktree contexts (where `CLAUDE_PROJECT_DIR` is unset and `$PWD` is the worktree, not the primary repo where the marker lives).

- **Marker symmetry across all top-level workflows** — `/smith-debug`, `/smith-finish`, and `/smith` (init) now create their own short-lived active-workflow markers, mirroring the existing `/smith-new`, `/smith-bugfix`, `/smith-build` pattern. `/smith-debug` writes `debug-<slug>.yaml` on Phase 0; `/smith-finish` writes `finish-<branch>.yaml` in Step 1.5; `/smith` init writes `bootstrap.yaml` in Phase 4.1 and clears it in Phase 4.10. All three rely on the existing `clear-active-workflow.sh` helper for cleanup, and the `active-workflow-janitor.sh` Stop sweep for crashed-session recovery.

- **Manifest System v2 (20-manifest-fixes)** — builds on the v1 manifest system from PR #19 (merged 2026-05-21). All v1 invariants are preserved (`.meta` header fields are byte-stable for v1 readers, parser output fields unchanged, source files never modified). v2 additions are additive only. The 11 design questions in `specs/20-manifest-fixes/questions.md` are all resolved. Three tracks:
  - **Track A — Declarative system membership.** New tier 1 in the path resolver reads `paths:` YAML frontmatter from `.specify/systems/<id>/spec.md`, sorted by longest-prefix-wins, cached on `os.stat(systems_dir).st_mtime_ns`. v1's `system-paths.json` tier and heuristic tier are preserved as tier 2/3. Glob characters rejected at load time with optional `SMITH_DEBUG=1` stderr logging. New skill `/smith-migrate-system-paths` walks existing prose-only system specs, proposes path prefixes from heuristic regex matchers (`services/<X>/`, `backend/<X>/`, `frontend/<X>/`, `apps/<X>/`, `packages/<X>/`, backticked dirs/files, code-fence file paths, bullet-list paths), scores by `frequency × position_weight`, and injects accepted prefixes as YAML frontmatter above the existing body — body bytes preserved verbatim. Idempotent on re-runs. New template `skills/smith/templates/system-spec-template.md` with `system`/`status`/`paths`/`also_affects` frontmatter; `/smith init` Phase 4.X prompts the operator to declare systems upfront and scaffolds the template per declared id.
  - **Track B — LLM description layer in `.meta`.** Two new optional fields per `.meta` (`**Description:**` + `Described-Against-Hash:` + `Described-At:` at the module header, `Description:` after each per-method `Id:`). Schema is additive — v1 readers see the same fields they always did. New stable method id on parser output: 16-character hex `sha256(module_path::scope_chain::name::canonical_signature)[:16]`, emitted on every function and method by both `parse-python.py` and `parse-js.js`. The id survives body edits and reorders but changes on rename, signature change, return-type change, or file move. New shared helper `scripts/parsers/meta_describe.py` is the SOLE module that crosses the structural-↔-description boundary; it provides `parse_meta_descriptions()`, `describe_file()`, `update_touched()`, `render_description_block()`, a CLI entrypoint (`python3 scripts/parsers/meta_describe.py update-touched ...`), threshold filtering (default body_lines >= 5), and a stdlib `urllib.request`-only Haiku 4.5 client (no `anthropic` SDK dependency). Soft cap of ~120 chars for module descriptions, ~200 chars for per-method.
  - **Track C — Lifecycle integration.** Three lifecycle paths populate or preserve the description layer:
    - `/smith-index --describe` (bulk path): new CLI flag drives a batched LLM pass — operator approval per `--batch-size` files (default 20), sub-batched into `--llm-batch-size` LLM calls (default 10), threshold-gated per `--threshold` body-line cutoff (default 5). Per-batch hash-cache skip (Hash == Described-Against-Hash AND description present). Rule-4 compliant: JSONL log at `.smith/index/logs/smith-index-describe-<ISO>.jsonl` with `{timestamp, item_id, stage, status, error, method_count, module_chars, batch_index}`, checkpoint at `.smith/index/.smith-index-describe-checkpoint.json` overwritten after each LLM batch, `--resume` reads the most recent log + checkpoint and skips completed items, final summary block (total / succeeded / failed / skipped / elapsed / failure list / log path) printed on completion AND on `KeyboardInterrupt`. `--no-interactive` auto-approves all batches for CI / tests. `--system <name>` filters to one system.
    - Three smith workflows (`/smith-new`, `/smith-bugfix`, `/smith-debug`): new in-workflow sub-step re-parses the touched file, diffs current method ids against existing `.meta`'s `Id:` list to compute touched ids, computes a `purpose_shifted` heuristic (new export added OR new class added OR >50% methods new), invokes `meta_describe.update_touched(...)` to regenerate only touched ids, and rewrites `.meta`. Untouched method descriptions are passed through verbatim. Module description is regenerated only when `purpose_shifted=True`.
    - `manifest-updater.sh` (save hook): now reads the existing `.meta` before writing and splices the description layer verbatim into the new `.meta`. `Hash:` is recomputed; `Described-Against-Hash:` is NEVER touched by the save hook (preservation invariant). Stale-description detection becomes free: `Hash != Described-Against-Hash` means the file body changed since the last description-aware path ran. The save hook stays LLM-free (<500ms p95 measured, unchanged from v1). v1 `.meta` files (no description layer) round-trip without growth.
  - **`/smith-build` description coverage flag (C1.5)** — PR description gains a "Description Coverage Warnings" block when the diff contains methods lacking a `.meta` description. Algorithm: `git diff main --name-only` → filter to source extensions → per-file, parse, diff against `main:` parser output to identify touched ids, look up each id in `.meta`'s `## Functions` section, collect ids missing a `Description:`. Block lists missing methods as `<file>::<class>::<method>` (or `<file>::<function>`) with a CTA suggesting `/smith-index --describe --system <name>`. Non-blocking — PR opens regardless.
  - **New skill: `/smith-migrate-system-paths`** — `skills/smith-migrate-system-paths/SKILL.md` plus helper scripts at `skills/smith-migrate-system-paths/scripts/{migrate.py,propose_paths.py}`. Idempotent, atomic-write via `os.replace(tempfile, spec_path)`. `--dry-run` previews proposals without writing; `--auto-confirm` accepts all proposals for tests; `--non-interactive` suppresses prompts.
  - **New template: `skills/smith/templates/system-spec-template.md`** — canonical YAML frontmatter (`system`/`status`/`paths`/`also_affects`) plus prose body sections (Purpose, Owners, Files & Components, Interfaces, Dependencies). Used by `/smith init` Phase 4.X and as the schema reference for `/smith-migrate-system-paths`.
  - **`/smith init` new sub-step Phase 4.X — "Scaffold System Specs (Optional)"** — interactive prompt for system ids, per-id prompt for `paths:` entries terminating on empty input. Empty `paths:` is permitted. Glob characters in path entries are rejected with re-prompt. Trailing `/` auto-appended.
  - **Hard constraints maintained** — source files NEVER modified by any v2 path. LLM calls confined to `scripts/parsers/meta_describe.py` (called only by `/smith-index --describe` and the three workflow skills); the save hook is LLM-free. `python3` everywhere (no `python`). All v1 `.meta` header fields and parser output fields are unchanged; v2 additions are additive only.

  See `specs/20-manifest-fixes/` for the full 9-requirement spec, plan, tasks, contracts, quickstart, and the 11 resolved design questions. Build phases A-E land together in this PR.

- **Manifest System & Structured Context Retrieval ([#19](https://github.com/ATTCKDigital/smith/pull/19))** — replaces soft natural-language navigation with a deterministic, precomputed project index plus a Haiku-powered navigator that injects a curated file list into Claude's context *before* reasoning begins. Addresses the three failure modes that dominated soft-guidance Smith: Claude reading the wrong files, missing cross-referenced helpers, and silent inconsistency between runs of the same skill on the same codebase. Includes:
  - **New skill `/smith-index`** — full project index, hash-only `--check` for staleness (SHA-256 of first 4KB per file, no mtime), `--system <name>` for partial rebuilds, `--incremental --from <ref> --to <ref>` for git-hook driven catch-up, `--migrate-templates` for non-destructive append of new template sections to existing `constitution.md`/`CLAUDE.md`, `--resume` checkpoint for SIGINT-safe long runs, `--init-system-paths` to bootstrap the optional overrides file. Auto-invoked as the final step of `/smith init`.
  - **New skill `/smith-navigate`** — Haiku 4.5 sub-agent that reads `.smith/index/manifest.md` + relevant system manifests + `.meta` files and returns a categorized file list (Must Read / Should Read / Reference Only / Systems Affected) with primary-section annotations (`[primary: 230-380, POST endpoint]`). Whole-file reads, not tight ranges — correctness over efficiency. 3-second budget; sentinel responses for missing manifest and no-match.
  - **New hook `manifest-updater.sh`** — PostToolUse `Write|Edit` that incrementally updates `.smith/index/` after every file mutation. Allowlist of source extensions (`.py .js .jsx .ts .tsx .css .html .sh`); silent skip for everything else. Invokes the resolved parser (per-project override at `.smith/scripts/parse-X` preferred over global `~/.smith/scripts/parse-X`); writes `.meta`; atomically rewrites the relevant `systems/<sys>.md`; updates top-level stats. Emits `additionalContext` warning when a file crosses 300 lines. Registered LAST in the PostToolUse chain so it sees the post-lint file state.
  - **New hook `context-loader.sh`** — UserPromptSubmit hook (main session only) that detects `/smith-*` invocations and natural-language triggers (mirrors `~/.claude/CLAUDE.md` Rule 2 phrase list — "let's smith this", "fix this", "debug this", "bank this for later", etc.). Resolves a per-skill config through a 4-tier precedence chain (built-in fallback → repo-shipped default → `~/.smith/config/context-manifest.json` → `.smith/index/config/context-manifest.json`, field-level merge per skill). Loads vault sections per resolved config, optionally spawns `/smith-navigate` with a 3-second timeout, and injects the assembled markdown as `additionalContext`. **Zero overhead for regular conversation** — short-circuits when no trigger matches. Soft warning (once per session) if the manifest is missing; never auto-rebuilds.
  - **New parsers** — `scripts/parsers/parse-python.py` (stdlib `ast` only) and `scripts/parsers/parse-js.js` (vendored acorn 8.x + acorn-jsx + acorn-typescript bundled via esbuild into `scripts/parsers/vendor/acorn.min.js`). Both emit JSON conforming to `specs/19-manifest-system/contracts/parser-output.schema.json`. Both meet a <200ms p95 budget. Both handle malformed input with regex fallback + partial JSON return; neither ever throws.
  - **Path resolver** — `scripts/parsers/path-resolver.py` implements heuristic-as-engine + `system-paths.json`-as-optional-overrides. Newly-created directories auto-map to a system on first edit (`services/<name>/` → `system-<name>`, `backend/<name>/` → `system-backend-<name>`, etc.); `tests/`, `docs/`, `node_modules/`, `.venv/`, `vendor/`, `dist/`, `build/`, `.git/` are excluded. Explicit overrides at `.smith/index/config/system-paths.json` win via longest-prefix match when present.
  - **Refactored `/smith-explore`** — Phase 1 now starts with `/smith-navigate` for fast manifest lookup, then greps candidate locations + immediate neighborhoods, then escalates to whole-codebase grep when the manifest doesn't cover the query or when initial signals suggest broader impact than the navigator surfaced. The manifest is a map, not a fence. Phases 2+ (conflict detection, impact analysis, exploration report, decision gate) unchanged.
  - **New visible behavior — `/smith-build` PR descriptions list files >300 lines** in a "File-size advisories" section. Never blocks the PR; sourced from `.meta` thresholds written by `manifest-updater.sh`.
  - **New visible behavior — `/smith-audit` file-size hygiene section** — counts at 300/500 thresholds, top 10 largest files with decomposition pointers. Sourced from `.meta` if present; falls back to live `wc -l`.
  - **New global advisory sections in `settings/claude-md-template.md`** — "Smith Context System" (how to use injected `additionalContext`, Must Read / Should Read / Reference Only semantics, fallback when injection absent) and "File Size Awareness" (check `.meta` before reading large files, warn against full reads of >300-line files). Appended AFTER the existing Rules 1-7 rubric block; these are advisory, NOT new graded rules.
  - **New template `templates/constitution.template.md`** — minimal preamble + "File Size Policy" section (300/500-line guidelines, exemptions for schemas/auto-generated) + "Project Manifest" section (auto-maintained by hooks, no source-file metadata, gitignored per selective rules). Used by `/smith init` for new projects; existing projects pick up these sections via `/smith-index --migrate-templates`.
  - **New install scripts** — `scripts/install-parsers.sh` (copies parsers to `~/.smith/scripts/` with `.bak.<ISO8601>` backups, verifies `python3` and `node` on PATH), `scripts/install-hooks.sh` (registers `manifest-updater.sh` and `context-loader.sh` in `~/.claude/settings.json` idempotently; enforces `manifest-updater.sh`-LAST invariant in the `Write|Edit` chain; honors `--no-hooks`), `scripts/install-git-hooks.sh` (per-project `.git/hooks/post-merge` and `post-checkout` calling `/smith-index --incremental` to catch up after `git pull` / branch switches; silent no-op if `.smith/index/` is absent).
  - **Auto-installation** — `npx skills add ATTCKDigital/smith` (and the bundled `scripts/install.sh`) now register both hooks by default. Pass `--no-hooks` to skip hook registration; pass `--no-git-hooks` to `/smith init` to skip per-project git hooks. Uninstaller removes both hook entries from `settings.json` and deletes the parsers from `~/.smith/scripts/`.
  - **Gitignore policy (selective per Q5)** — `.smith/index/files/` and `.smith/index/systems/` are gitignored; `.smith/index/manifest.md` and `.smith/index/config/` ARE committed (team-shared overview + config). `/smith init` merges `templates/.gitignore-smith-additions` into the project's `.gitignore`.
  - **Documentation** — new `docs/manifest-system.md` user guide covering architecture, components, setup, daily use, configuration (4-tier resolution + heuristic resolver + gitignore policy), troubleshooting, and performance budgets. `CONTRIBUTING.md` gains "Vendored Dependencies" (acorn regen procedure) and "Parser Development" sections; "Hook Chain Ordering" invariant documented.
  - **Hard constraints upheld** — source files NEVER receive Smith metadata (no comments, no frontmatter, no JSDoc additions); all data lives exclusively in `.smith/index/`. Parsers <200ms p95. `manifest-updater.sh` <500ms p95 (measured 102ms typical). `context-loader.sh` <5s p95 (measured 13-48ms typical without navigator, ~3.7s with navigator). `/smith-index` <60s for 100+ files (measured ~38s typical; ~8s for 400-file fixture).

  See `specs/19-manifest-system/` for the full 13-requirement spec, 8 design decisions, 10 resolved questions, plan, tasks, contracts, and quickstart walkthroughs.

- **Weighted-rubric compliance system** — Smith now ships a global `~/.claude/CLAUDE.md` template (`settings/claude-md-template.md`) with 7 rules totaling 100 points, each with binary all-or-nothing sub-criteria a Haiku critic can grade against. Weights reflect frequency and impact: Rules 1 & 2 (questions-are-not-actions, SpecKit triggers + skill-process compliance) carry 25 each as they evaluate every turn; Rules 3 & 4 (question files, checkpoint/resume) carry 15 each as per-task rules; Rule 5 (session logging) carries 10; Rules 6 & 7 (general preferences, directory setup) carry 8 and 2 as stylistic/environmental checks. Inapplicable rules auto-pass full credit.
- **New hook: `grade-response.sh`** — Stop hook that grades each response against the rubric in `~/.claude/CLAUDE.md` via `claude --model haiku -p`. Exits 2 to block the stop and force a retry when score < 100, capped at 3 retries per turn (via `/tmp/claude-grade-retry-<session-id>`) to prevent infinite loops. Fails open on any error (missing transcript, bad JSON, unreachable critic). Anti-recursion via `stop_hook_active` JSON field check. Registered as a separate Stop entry from `session-end-review` and `workflow-summary` so it can be toggled independently in `settings.json`.
- Installer now writes the global rubric to `~/.claude/CLAUDE.md` (backing up any existing file as `CLAUDE.md.bak-<timestamp>`, matching the settings.json backup pattern). Uninstaller offers to restore from the most recent backup, or to remove the Smith rubric outright if no backup exists.
- Install via `npx skills add ATTCKDigital/smith` — new distribution path that copies all 26 skills into `~/.claude/skills/` without requiring the curl installer. Skills-only; hooks and scheduler still require the bundled installer.
- New skill in the public distribution: `/smith-audit` — cross-system audit orchestrator. Previously only in the agency-internal skill set; now shipped with the public Smith distribution.
- New skill: `/smith-explore` — pre-change impact analysis for features touching core infrastructure
- New hook: `metrics-tracker.sh` — PostToolUse hook that captures character counts for token estimation
- Workflow metrics summary — primary workflows (smith-new, smith-bugfix, smith-debug) now display aggregated metrics at completion: estimated tokens, tool calls, subagent stats, duration
- Subagent metrics logging — SubagentStop hook now captures `total_tokens`, `tool_uses`, `duration_ms` and logs to session files
- `workflow-summary.sh --totals-only` — lightweight mode that prints just `Total tokens used` and `Total duration` to stdout for skills to include inline in the final chat message (Stop-hook stdout doesn't reach the preceding assistant bubble, so the two-line totals are now emitted by the skill before Stop fires)
- **Accurate workflow summary (normalized tokens + USD + active duration).** The completion summary now displays three defensible numbers: (a) normalized token usage via fixed-weight formula `input + 5×output + 1.25×cache_create + 0.1×cache_read`, (b) estimated USD cost looked up from a new `hooks/pricing.json` table with per-model-family rates and `last_verified` metadata, (c) active duration excluding idle user-input waits (gap detection on main-session tool timestamps with a 120s idle threshold and 600s cap for legitimate long Bash runs, plus sum of subagent `duration_ms`). Real main-session tokens are now parsed from the parent JSONL at `~/.claude/projects/<slug>/<session-id>.jsonl` instead of estimated from tool-I/O character counts. Fuzzy model matching uses longest-prefix-first ordering so `claude-opus-4-6` correctly resolves to the $5/$25 tier rather than sharing rates with `claude-opus-4-0` ($15/$75). Unknown model IDs are transparently annotated in the cost line. See `specs/003-accurate-workflow-summary/` for the full design.
- `hooks/pricing.json` — checked-in pricing table verified against platform.claude.com/docs/en/docs/about-claude/pricing on 2026-04-14. Each entry carries `source_url` and `last_verified` metadata for staleness visibility.
- `hooks/workflow_summary_lib.py` — Python library factored out of `workflow-summary.sh`'s heredoc so formulas are unit-testable.
- `tests/` directory (new at repo root) with a stdlib-only `unittest` suite. Run with `python3 -m unittest discover tests`. 49 tests covering normalized formula, USD formula, active-duration gap detection, fuzzy model matching, and v1/v2 subagent-block parsing.
- Subagent completion blocks in session logs now include the full usage breakdown: `model`, `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens` alongside the existing `tool_uses`, `duration_ms`, and `total_tokens` (kept as a legacy alias).

### Fixed

- **Scheduler silently archived real work as "completed" ([#18](https://github.com/ATTCKDigital/smith/pull/18)).** `scheduler/smith-scheduler.sh` was running a one-line ad-hoc `claude -p "<task summary>"` in place of the documented 16-step `/smith-queue process` pipeline, pre-mutating the queue entry's `status: in-progress` before invoking claude, and moving the entry to `history/` on any exit 0 — but `$?` was masked by `|| true`, so even the 2026-04-23 `claude: command not found` run (launchd's minimal PATH lacked the Claude Code bundle) recorded three real queue entries as "Completed" with zero work done. The scheduler is now a thin launcher: it still owns iterating `~/.smith/projects.json`, filtering by `complexity: autonomous` / deps / `scheduled_for`, priority-sorting, resolving the `claude` binary, and capturing exit codes — but per-task dispatch now invokes `"$CLAUDE_BIN" --permission-mode bypassPermissions -p "/smith-queue process <file>"` and lets the skill own the full pipeline (status updates, worktree, `/smith-build`, Docker rebuild, tests, `gh pr create`, `gh pr merge`, spec + CHANGELOG updates, `history/` archival, worktree cleanup). Verification is now filesystem-based: the scheduler checks whether the skill archived the entry and never mutates queue files itself. Preserves the previously-landed `SMITH_SCHEDULER_ENABLED` kill switch and `resolve_claude_bin` VM-bundle fallback. Adds `SMITH_SCHEDULER_DRY_RUN=1` for dispatch-planning without invoking claude, `SMITH_SCHEDULER_MODEL` for per-run model override (default: `sonnet`). Also fixes a latent `PROJECT_DIR` bug that resolved to `.smith/` instead of the project root — the pre-delegation scheduler survived this because `git worktree` walks up to find `.git`; delegation surfaced it because the skill needs `.smith/vault/queue/<file>` to resolve from cwd. `skills/smith-queue/SKILL.md` now has an explicit "Scheduler invocation contract" section that partitions responsibilities between scheduler and skill and forbids scheduler-side pipeline reimplementation. `docs/scheduler.md` updated to match, plus stale-reference cleanup (`com.attck.smith-scheduler.plist` → `com.smith.scheduler.plist`, `~/.smith/scheduler/projects.json` → `~/.smith/projects.json`, old `mode: autonomous` → `complexity: autonomous`).
- 7 skills (`smith-bank`, `smith-explore`, `smith-ledger`, `smith-migrate-specs`, `smith-report`, `smith-todo`, `smith-vault`) were silently skipped by `npx skills add . --list` because their `argument-hint:` frontmatter value started with `[` followed by multiple space-separated bracketed groups — a YAML flow-sequence construct the `skills` CLI parser rejects. Wrapped all affected values in double quotes so YAML treats them as plain string scalars. Claude Code's own parser already tolerated the unquoted form, so local invocation was never affected; only the external CLI was. See [specs/013-distribution-readiness/research.md](specs/013-distribution-readiness/research.md) for the diagnosis.
- `Total tokens used` and `Total duration` now appear in the user-facing "Feature/Bugfix/Debug complete" chat message. Previously these only landed in the session log file because the Stop hook's stdout doesn't flow into the assistant message that already shipped. Skills (`/smith-new`, `/smith-bugfix`, `/smith-debug`) now invoke `workflow-summary.sh --totals-only` and paste the two lines into their final summary before Stop fires. The full `=== Workflow Summary ===` audit block continues to be appended to the session log file by the Stop hook
- Workflow token count was previously a raw sum of `input + output + cache_create + cache_read` at 1× weights across all models, which inflated the number 3–10× vs. what Anthropic actually bills (cache reads are 0.1× and cost varies by model tier). The summary now displays normalized tokens (fixed-weight formula) and estimated USD cost (per-model pricing lookup), with the raw breakdown relegated to the session-log audit block. Addresses the observation that a single smith-new workflow could show 30M+ tokens — a figure that was technically correct per the formula but misleadingly high for a public repo

### Changed

- **`scripts/install.sh` is now truly idempotent.** The jq merge that wires hook entries into `~/.claude/settings.json` now dedupes by (matcher + hooks-array equality) — re-running the installer no longer accumulates duplicate hook entries. Combined with `dedupe-settings.sh`'s retroactive cleanup pass via `/smith-update`, both new and historical accumulations are addressed.
- **`scripts/install.sh` records the installed commit SHA** at `~/.smith/.installed-version` at the end of every successful install. Single-line file. Falls back to `unknown` when run from a tarball (no `git rev-parse HEAD`). Read by `/smith-update` to compute commits-behind.
- **`README.md` Updating section** now points users at `/smith-update` first; the manual `cd /path/to/smith && git pull && ./scripts/install.sh -y` flow is retained as a fallback.
- **BREAKING: Eight secondary skills can no longer be invoked standalone.** The new workflow-gate hook blocks any file-modifying tool call without an active-workflow marker, and these design-phase skills don't create their own markers — they're meant to run *inside* a parent workflow. Affected: `/smith-implement`, `/smith-plan`, `/smith-specify`, `/smith-checklist`, `/smith-clarify`, `/smith-constitution`, `/smith-tasks`, `/smith-migrate-specs`. Each skill's `SKILL.md` now carries a "Workflow requirement (Smith 20+)" callout. To use any of these standalone, start `/smith-new`, `/smith-bugfix`, `/smith-debug`, or `/smith-build` first. Mitigation rationale: standalone invocation of these skills was already uncommon in practice; centralizing edits under the top-level workflows is what makes the gate enforce discipline (see `specs/020-workflow-gate-hook/questions.md` Q3 for the full decision trail).
- **Renamed skill:** `/smith.init` → `/smith`. The `skills/smith/SKILL.md` frontmatter now declares `name: smith` (previously `name: smith.init`), matching the folder name. Invocations of `/smith.init` no longer match; use `/smith` instead. This aligns with the `skills` CLI's expected folder/name convention.
- `hooks/workflow-summary.sh` now resolves `workflow_summary_lib.py` via a priority chain (`$CLAUDE_HOOKS_DIR` → `~/.claude/hooks` → sibling of `$0`) instead of only the sibling directory. This allows a single installed copy at `~/.claude/hooks/workflow-summary.sh` to serve as a Stop hook across all projects without each project vendoring its own copy of the Python lib and `pricing.json`. If none of the candidates contain the lib, the wrapper prints a stderr note and exits 0 (consistent with existing degrade-gracefully behavior).
- The chars/4 character-count estimate is no longer displayed as "Estimated tokens" in the workflow summary. The per-tool `metrics-tracker.sh` log lines remain unchanged (useful for spotting heavy tool uses), but the summary block now uses real Anthropic-reported token counts from the parent-session JSONL instead.
- Active workflow tracking now uses per-branch files (`.smith/vault/active-workflows/<branch>.yaml`) to support concurrent workflows in different worktrees
- `subagent-vault-writeback.sh` enhanced to capture and log subagent metrics
- `/smith-bugfix` Phase 1 rewritten to always run in an isolated worktree branched from `origin/main`. No more "switch to main / stash / cancel" prompt when the user is on a non-main branch — the user's working tree and branch are never touched, and concurrent Smith sessions can't collide on the shared working tree. Matches the worktree-always model already used by `/smith-new`.

- `/smith-new` now includes Phase 0 exploration when features touch `.claude/skills/`, `.smith/`, or `.specify/`
- `/smith-bugfix` no longer updates CHANGELOG.md (vault session logs handle this)
- All skills now capture verbatim user requests in vault logs with `**User Request:**` field
- File Purpose Policy added to constitution.md §VI (constitution.md / CLAUDE.md / MEMORY.md scopes)

## [0.1.0] - 2026-04-11

### Added

- Initial release with 25 Smith skills for spec-driven development
- 8 hooks for session logging, security guards, and workflow routing
- macOS scheduler (LaunchAgent) for overnight queue processing
- Install and uninstall scripts with settings.json merge via jq
- Settings fragment for Claude Code hook configuration
- Documentation: getting started, security model, hooks reference, scheduler guide, architecture overview
- GitHub CI: skill linting and install smoke test
- Issue templates: bug report, feature request, skill proposal
- MIT license

[Unreleased]: https://github.com/ATTCKDigital/smith/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ATTCKDigital/smith/releases/tag/v0.1.0
