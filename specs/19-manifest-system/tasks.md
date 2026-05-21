---
feature: 19-manifest-system
branch: 19-manifest-system
created: 2026-05-21
spec: ./spec.md
plan: ./plan.md
---

# Tasks: Manifest System & Structured Context Retrieval

Dependency-ordered task breakdown. Tasks within a phase that share files run
sequentially; tasks tagged `[P]` are safe to parallelize against their
neighbors (no file conflicts). Paths are absolute relative to the worktree
root `/tmp/smith-manifest-system/`.

Each task references its spec component (e.g. `[parsers]`, `[smith-index]`)
and, where applicable, the acceptance criterion or design decision it satisfies.

---

## Phase 1: Setup (Foundation)

- [X] T001 [setup] Create directory `/tmp/smith-manifest-system/scripts/parsers/` with `.gitkeep`
- [X] T002 [P] [setup] Create directory `/tmp/smith-manifest-system/scripts/parsers/vendor/` with `.gitkeep`
- [X] T003 [P] [setup] Create directory `/tmp/smith-manifest-system/scripts/smith-index/` with `.gitkeep`
- [X] T004 [P] [setup] Create directory `/tmp/smith-manifest-system/skills/smith-index/` with `.gitkeep`
- [X] T005 [P] [setup] Create directory `/tmp/smith-manifest-system/skills/smith-navigate/` with `.gitkeep`
- [X] T006 [P] [setup] Create directory `/tmp/smith-manifest-system/templates/git-hooks/` with `.gitkeep`
- [X] T007 [P] [setup] Create directory `/tmp/smith-manifest-system/tests/parsers/fixtures/python/` with `.gitkeep`
- [X] T008 [P] [setup] Create directory `/tmp/smith-manifest-system/tests/parsers/fixtures/js/` with `.gitkeep`
- [X] T009 [P] [setup] Create directory `/tmp/smith-manifest-system/tests/hooks/` with `.gitkeep`
- [X] T010 [P] [setup] Create directory `/tmp/smith-manifest-system/tests/skills/` with `.gitkeep`
- [X] T011 [P] [setup] Create directory `/tmp/smith-manifest-system/tests/contracts/` with `.gitkeep`
- [X] T012 [P] [setup] Create directory `/tmp/smith-manifest-system/tests/fixtures/sample-project/` with `.gitkeep`
- [X] T013 [setup] Create `/tmp/smith-manifest-system/.gitattributes` (or append to existing) with `scripts/parsers/vendor/acorn.min.js linguist-vendored=true` and `scripts/parsers/vendor/acorn.min.js linguist-generated=true` per Risk R7
- [X] T014 [setup] Create `/tmp/smith-manifest-system/scripts/parsers/vendor/README.md` documenting acorn origin, version (8.x), license (MIT), and regen procedure (`npx esbuild ... --bundle --minify`)

---

## Phase 2: Parsers (Foundation — must complete first)

### Python parser

- [X] T015 [parsers] Implement `/tmp/smith-manifest-system/scripts/parsers/parse-python.py` per Component 2 — stdlib `ast` only, shebang `#!/usr/bin/env python3`, accepts single path arg, emits JSON to stdout. Conforms to `contracts/parser-output.schema.json`. Handles `SyntaxError` with regex fallback for imports per research.md section 1.
- [X] T016 [parsers] Implement `_extract_functions(tree)` in parse-python.py — walks `ast.FunctionDef` and `ast.AsyncFunctionDef`, captures name, line, params (with type hints via `ast.unparse`), return_type, docstring first line.
- [X] T017 [parsers] Implement `_extract_classes(tree)` in parse-python.py — recursive method collection with name/line per method.
- [X] T018 [parsers] Implement `_extract_imports(tree)` in parse-python.py — handles `ast.Import` and `ast.ImportFrom`; emits `kind` field (`import`|`from`).
- [X] T019 [parsers] Implement `_extract_routes(tree)` in parse-python.py — matches FastAPI/Flask decorator patterns (`@app.get`, `@router.post`, `@app.route`); emits `{method, path, line, function, framework}`.
- [X] T020 [parsers] Verify parse-python.py p95 <200ms per file against fixtures up to 2000 lines (acceptance: spec Performance criteria).

### JS parser — acorn vendoring + implementation

- [X] T021 [parsers] Bootstrap vendored acorn — run `npx esbuild --bundle --minify --platform=node --format=cjs --target=node18 <entry>` to produce `/tmp/smith-manifest-system/scripts/parsers/vendor/acorn.min.js` (~150KB, single file bundling acorn@8.x + acorn-jsx + acorn-typescript per Q8). Pin version in `vendor/VERSION` file.
- [X] T022 [parsers] Implement `/tmp/smith-manifest-system/scripts/parsers/parse-js.js` per Component 3 — node script, shebang `#!/usr/bin/env node`, requires vendored acorn, accepts single path arg, emits JSON conforming to `contracts/parser-output.schema.json`.
- [X] T023 [parsers] Implement `_extractExports(ast)` in parse-js.js — walks `ExportNamedDeclaration`, `ExportDefaultDeclaration`, function declarations; detects React components by PascalCase + JSX return heuristic; emits `{name, line, kind}`.
- [X] T024 [parsers] Implement `_extractImports(ast)` in parse-js.js — walks `ImportDeclaration`, `CallExpression` for `require(...)` and dynamic `import(...)`; emits `kind: "import"|"require"|"dynamic"`.
- [X] T025 [parsers] Implement `_extractRoutes(ast)` in parse-js.js — walks `CallExpression` matching `app.{get|post|put|patch|delete}` and `router.{verb}` (Express); emits `{method, path, line, function, framework: "express"}`.
- [X] T026 [parsers] Implement regex fallback in parse-js.js — on acorn `SyntaxError`, extract `export`/`import` via regex and return partial JSON with `errors[]` populated. Never crashes (spec Hard Constraint).
- [X] T027 [parsers] Verify parse-js.js p95 <200ms per file against fixtures up to 2000 lines (target: 135ms per research.md section 2).

### Path resolver

- [X] T028 [parsers] Implement `/tmp/smith-manifest-system/scripts/parsers/path-resolver.py` per Component 14 — exposes `resolve(file_path, project_root, system_paths_json) -> str`. Algorithm: try explicit longest-prefix rules first, fall back to heuristic per spec Requirement 14. Stdlib `json`/`os.path` only.
- [X] T029 [parsers] Implement CLI entrypoint in path-resolver.py — invokable as `python3 path-resolver.py <file_path> <project_root>` for shell callers (manifest-updater.sh uses this).
- [X] T030 [parsers] Verify path-resolver heuristic covers all spec Requirement 14 cases: `services/`, `backend/`, `frontend/`, generic top-level dirs, excluded dirs (`tests/`, `docs/`, `node_modules/`, `.venv/`, `vendor/`, `dist/`, `build/`, `.git/`), root-level files.

### Parser shared helper

- [X] T031 [parsers] Implement `/tmp/smith-manifest-system/scripts/parsers/parser-lib.sh` per File Structure table — exposes `resolve_parser <ext>` bash function returning absolute parser path; prefers `.smith/scripts/parse-X` over `~/.smith/scripts/parse-X` per Design Decision 5.

### Parser tests

- [X] T032 [P] [parsers] Create Python fixtures at `/tmp/smith-manifest-system/tests/parsers/fixtures/python/` — `vanilla.py`, `async_funcs.py`, `class_with_methods.py`, `fastapi_routes.py`, `flask_routes.py`, `type_hints.py`, `docstrings.py`, `empty.py`, `syntax_error.py` (deliberately broken).
- [X] T033 [P] [parsers] Create JS fixtures at `/tmp/smith-manifest-system/tests/parsers/fixtures/js/` — `esm_named.js`, `default_export.js`, `react_component.jsx`, `imports_dedup.js`, `express_routes.js`, `ts_interface.ts`, `malformed.jsx` (unclosed tag), `tsx_component.tsx`.
- [X] T034 [parsers] Implement `/tmp/smith-manifest-system/tests/parsers/test_parse_python.py` — pytest covering: well-formed file, syntax error (partial output expected), empty file, FastAPI routes, type hints with `Optional`/`dict[str, list[int]]`, docstring extraction.
- [X] T035 [parsers] Implement `/tmp/smith-manifest-system/tests/parsers/test_parse_js.sh` — bash integration tests invoking `node parse-js.js <fixture>` directly; asserts JSON shape for each fixture; asserts graceful degradation on malformed.jsx.
- [X] T036 [contracts] [parsers] Implement `/tmp/smith-manifest-system/tests/contracts/test_parser_output_schema.py` — validates parser output JSON against `contracts/parser-output.schema.json` using `jsonschema` (test-only dep) for every fixture in both Python and JS test fixture sets.
- [X] T037 [contracts] [parsers] Implement `/tmp/smith-manifest-system/tests/contracts/test_path_resolver.py` — covers explicit-rule precedence (longest-prefix), heuristic for each pattern (services/, backend/, frontend/, other), exclusion of tests/docs/vendor, root-level files, overlapping rules.

### Parser install script

- [X] T038 [parsers] Implement `/tmp/smith-manifest-system/scripts/install-parsers.sh` per Implementation Discovery #3 — idempotent installer copying `scripts/parsers/parse-python.py`, `parse-js.js`, `vendor/acorn.min.js`, `path-resolver.py` to `~/.smith/scripts/`. Backs up existing files with `.bak.<ISO8601>` suffix. Verifies `python3` and `node` are on PATH; warns if missing.

---

## Phase 3: Skills — `/smith-index`

- [X] T039 [smith-index] Write `/tmp/smith-manifest-system/skills/smith-index/SKILL.md` per Component 5 — frontmatter with skill metadata, describes flags `--check`, `--system <name>`, `--resume`, `--system-paths <path>`, `--migrate-templates`, `--incremental`, `--init-system-paths`. Includes "Manifest is a map, not a fence" framing.
- [X] T040 [smith-index] Implement `/tmp/smith-manifest-system/scripts/smith-index/run.sh` — bash entrypoint, argument parsing for all flags listed in T039, dispatches to mode-specific subroutines.
- [X] T041 [smith-index] Implement full-rebuild mode in run.sh — discovery via `find <root> -type f \( -name '*.py' -o -name '*.js' -o ... \)`, filtered by `.gitignore` if `git` available. Per-file: invoke parser via `parser-lib.sh`, write `.meta`, defer system-manifest update to per-system batch.
- [X] T042 [smith-index] Implement per-system batched manifest rewrite in run.sh — rewrites `systems/<sys>.md` once per system after all files in that system are parsed (avoids O(N²) rewrites). Files sorted by lines desc; truncates >65 files with `…and N more files (see .meta for full inventory)` per data-model.md section 3.
- [X] T043 [smith-index] Implement top-level `manifest.md` rewrite in run.sh — systems table (≤25 rows), Stats section (total source files, files >200/300/500 lines, last full index duration+timestamp), ≤50 line cap per data-model.md section 4.
- [X] T044 [smith-index] Implement `--check` mode in run.sh per Q6 — for each `.meta`, compute SHA-256 of first 4KB of source file, compare against `hash` field in `.meta`. Report stale + missing. No mtime field read. Estimated ~5-10s for 400 files.
- [X] T045 [smith-index] Implement `--system <name>` mode in run.sh — partial rebuild restricted to files mapped to one system.
- [X] T046 [smith-index] Implement `--incremental` mode in run.sh per Decision 8 — reads `--from <ref> --to <ref>` (or defaults to `ORIG_HEAD..HEAD`); `git diff --name-only` to enumerate changed files; filter to allowed extensions; run parse+meta+system patch per file. Falls back to no-op with log entry if git unavailable.
- [X] T047 [smith-index] Implement `--migrate-templates` mode in run.sh per Q2 — scans for `constitution.md` and `CLAUDE.md` in project root and `.specify/memory/`; detects missing headers (`## File Size Policy`, `## Project Manifest`, `## Smith Context System`, `## File Size Awareness`); appends missing sections from templates with `.bak.<ISO8601>` backup. Idempotent.
- [X] T048 [smith-index] Implement `--resume` checkpoint/log per Rule 4 + research.md section 8 — writes `.smith/index/.smith-index-checkpoint.json` per-system (not per-file) with `{started_at, last_system, processed_files, systems_completed}`; writes JSONL log line per file/stage to `~/.smith/logs/smith-index-<ISO8601>.jsonl`; on resume, skips files where `stage="system-update" AND status="ok"`. Deletes checkpoint on clean exit.
- [X] T049 [smith-index] Implement final summary line per Rule 4 — `/smith-index: N files indexed (N succeeded, N failed, N skipped) in T.Ts`. Printed to stdout, NOT written to JSONL.
- [X] T050 [smith-index] Implement config bootstrap in run.sh — if `.smith/index/config/context-manifest.json` is missing, copy from `templates/context-manifest.default.json` (skill install path resolved relative to SKILL.md). `system-paths.json` NOT auto-copied per Q7 unless `--init-system-paths` passed.
- [X] T051 [smith-index] Implement `.meta` hash field in run.sh — every `.meta` write includes `hash: <sha256-of-first-4KB>` and `updated: <ISO8601>` per Q6 schema. NO `mtime` field.
- [X] T052 [P] [smith-index] Create `/tmp/smith-manifest-system/skills/smith-index/templates/context-manifest.default.json` per Requirement 9 and data-model.md section 5 — Tier 2 default with all 8 skill blocks (`smith-new`, `-bugfix`, `-debug`, `-build`, `-audit`, `-vault`, `-help`, `-bank`) + `_default` block + `_meta: {version: 1, tier_label: "repo-default"}`.
- [X] T053 [P] [smith-index] Create `/tmp/smith-manifest-system/skills/smith-index/templates/system-paths.json.example` per Requirement 10 and data-model.md section 6 — example with `_comment` keys per research.md section 10. Marks file as OPTIONAL in inline comments.
- [X] T054 [P] [smith-index] Create `/tmp/smith-manifest-system/skills/smith-index/templates/.gitignore-smith-additions` per Q5 — ships `.smith/index/files/` and `.smith/index/systems/` as ignored; documents `# NOT gitignored: .smith/index/manifest.md, .smith/index/config/`.
- [X] T055 [smith-index] Implement `/tmp/smith-manifest-system/tests/skills/test_smith_index.sh` — end-to-end test against `tests/fixtures/sample-project/`: (a) first run produces all expected artifacts; (b) `--check` reports no staleness; (c) touch a file, `--check` reports it stale; (d) SIGINT mid-run + `--resume` continues without reprocessing; (e) total <60s for 100+ files.

---

## Phase 4: Skills — `/smith-navigate`

- [X] T056 [smith-navigate] Write `/tmp/smith-manifest-system/skills/smith-navigate/SKILL.md` per Component 6 — frontmatter declaring Haiku 4.5 as model, 3s budget; instructs the sub-agent to read `.smith/index/manifest.md`, optionally selected `systems/<name>.md` files, and `.meta` files for large/relevant files only; emits markdown matching `contracts/navigator-output.md`.
- [X] T057 [smith-navigate] In SKILL.md, document the exact output format from `contracts/navigator-output.md` — four required headings (`## Relevant Files`, `### Must Read`, `### Should Read`, `### Reference Only`, `### Systems Affected`), primary-section annotation format `[primary: <start>-<end>, <label>]` per Design Decision 2.
- [X] T058 [smith-navigate] In SKILL.md, document sentinel responses — "Manifest not initialized" sentinel emitted exactly when `.smith/index/manifest.md` is missing; "No matching system" sentinel for empty results.
- [X] T059 [smith-navigate] Implement `/tmp/smith-manifest-system/tests/skills/test_smith_navigate.sh` — mocks Haiku response; asserts output matches `contracts/navigator-output.md` regex `^- (?P<path>\S+)(?: \[primary: (?P<start>\d+)-(?P<end>\d+), (?P<label>[^\]]+)\])?$`; asserts sentinel detection works.

---

## Phase 5: Hooks

### `manifest-updater.sh`

- [X] T060 [hooks] Implement `/tmp/smith-manifest-system/hooks/manifest-updater.sh` per Component 4 — PostToolUse `Write|Edit` matcher; reads stdin JSON; extracts `tool_input.file_path` via existing grep+sed pattern (research.md section 3).
- [X] T061 [hooks] Implement extension filter in manifest-updater.sh — allowlist `.py .js .jsx .ts .tsx .css .html .sh`; exit 0 silently for anything else.
- [X] T062 [hooks] Implement parser invocation in manifest-updater.sh — sources `scripts/parsers/parser-lib.sh`; calls `resolve_parser <ext>`; runs parser with `timeout 1s` if available; captures JSON.
- [X] T063 [hooks] Implement `.meta` rendering in manifest-updater.sh — Python helper (`python3 -c "..."`) templates JSON into markdown matching data-model.md section 2; writes to `.smith/index/files/<mirrored-path>/<file>.meta`. Includes hash (SHA-256 of first 4KB) and Last Updated timestamp; NO mtime field.
- [X] T064 [hooks] Implement system-mapping invocation in manifest-updater.sh — calls `path-resolver.py` (per Q7) with file path + project root + optional `system-paths.json`; assigns file to returned system name.
- [X] T065 [hooks] Implement per-system manifest patch in manifest-updater.sh — atomic rewrite of `systems/<sys>.md` (one row for this file); crude mutex via `mkdir -p .smith/index/.lock-<sys>` released on exit-trap.
- [X] T066 [hooks] Implement top-level `manifest.md` stats update in manifest-updater.sh — atomic rewrite of totals, files-over-threshold counters, Last Updated timestamp. Last full index timestamp untouched (only updated by full `/smith-index` runs).
- [X] T067 [hooks] Implement 300-line threshold warning in manifest-updater.sh — when `lines > 300`, write `⚠️ Exceeds 300-line threshold` line to `.meta` AND emit `additionalContext` JSON per research.md section 3: `{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"⚠️ <path> is <N> lines (>300)..."}}`. Touchpoint A per Requirement 11.
- [X] T068 [hooks] Implement structured logging in manifest-updater.sh — log line per invocation to `~/.smith/logs/hooks.log` matching data-model.md section 10 format: `<ISO> manifest-updater file=<path> ext=<ext> parser=<lang> lines=<N> system=<name> ms=<elapsed> warnings=<flags>`.
- [X] T069 [hooks] Implement defensive error handling in manifest-updater.sh — every external call wrapped in `|| true`; on any failure logs `status=skipped` to hooks.log and exits 0. Never blocks Claude per spec Hard Constraint.
- [X] T070 [hooks] Verify manifest-updater.sh p95 <500ms per file edit (acceptance: spec Performance criteria, Requirement 4).

### `context-loader.sh` + lib

- [X] T071 [hooks] Implement `/tmp/smith-manifest-system/hooks/context-loader.sh` per Component 8 — UserPromptSubmit hook; reads stdin JSON `{prompt, session_id, cwd, ...}`; thin bash wrapper delegating to `context-loader-lib.py`.
- [X] T072 [hooks] Implement skill detection in context-loader.sh — regex `\/smith-(new|bugfix|debug|build|audit|vault|help|bank|explore|navigate|index|todo|queue|reflect|...)\b`; NL trigger lookup table mirroring `~/.claude/CLAUDE.md` Rule 2 phrases ("let's smith this", "fix this", "debug this", "bank this for later", etc.); if neither matches, exit 0 with no output (zero overhead per acceptance criterion).
- [X] T073 [hooks] Implement `/tmp/smith-manifest-system/hooks/context-loader-lib.py` per Component 8 + Implementation Discovery #5 — Python helper exposing CLI subcommands: `resolve-config <skill>`, `load-vault <skill>`, `compose-injection`.
- [X] T074 [hooks] Implement 4-tier config resolution in context-loader-lib.py per Decision 4 + data-model.md section 5 — order: built-in fallback → repo `templates/context-manifest.default.json` → `~/.smith/config/context-manifest.json` → `.smith/index/config/context-manifest.json`. Field-level merge per skill block (objects merge per-key; scalars replace). Logs which tier provided which field.
- [X] T075 [hooks] Implement vault section loading in context-loader.sh — reads `.smith/vault/sessions/*.md`, `.smith/vault/ledger/`, `.smith/vault/bank/`, `.smith/vault/queue/`, `.smith/vault/agents/` with counts and modes per resolved config (`sessions: N|"all"|"none"`, `ledger: "top-N"|"all"|"none"`, etc.).
- [X] T076 [hooks] Implement navigator spawn in context-loader.sh — when `config.navigator == true` AND `.smith/index/manifest.md` exists: invoke `claude --print --model claude-haiku-4-5 --skill smith-navigate --max-turns 1 "<prompt>"` wrapped in `timeout 3`. On timeout/error, log fallback and continue with vault-only.
- [X] T077 [hooks] Implement soft-warning for missing manifest in context-loader-lib.py per Q10 + Decision 3 — when `.smith/index/manifest.md` absent: check per-session marker `.smith/vault/.warned-manifest-missing-<session-id>`; if absent, emit soft warning `"⚠️ Manifest not initialized — run /smith-index to enable structured context retrieval. Proceeding with vault context only."` into `additionalContext` and touch the marker. If marker present, skip warning silently. NO escalation logic.
- [X] T078 [hooks] Implement `additionalContext` injection composition in context-loader-lib.py — produces JSON `{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"<markdown>"}}` with HTML comment header `<!-- smith-context-injection v1; skill=<X>; tier=<T>; ts=<ISO>; [flags] -->` per data-model.md section 8.
- [X] T079 [hooks] Implement structured logging in context-loader.sh per data-model.md section 10 — `<ISO> context-loader skill=<X> tiers=<list> vault_chars=<N> navigator_ms=<N> navigator_status=<ok|timeout|error|skipped> total_ms=<N>`.
- [X] T080 [hooks] Verify context-loader.sh p95 <5s total including sub-agent spawn (acceptance: spec Performance criteria, Requirement 8). Sub-budget breakdown: 50ms detect, 100ms config-resolve, 500ms vault read, 3000ms navigator with hard timeout, 100ms assembly, 250ms slack.

### Hook tests

- [X] T081 [hooks] Implement `/tmp/smith-manifest-system/tests/hooks/test_manifest_updater.sh` — simulates hook stdin JSON; asserts `.meta` written; asserts system manifest row updated; asserts p95 <500ms over 50 runs; asserts 300-line file emits `additionalContext` warning; asserts non-source extension is skipped silently.
- [X] T082 [hooks] Implement `/tmp/smith-manifest-system/tests/hooks/test_context_loader.sh` — feeds 5 prompts: `/smith-new "add endpoint"`, NL trigger `"let's smith this"`, `/smith-help`, plain question `"What is 2+2?"`, malformed JSON. Asserts injection occurs only on first two; asserts soft-warning when manifest absent; asserts 4-tier resolution observable in logs.

### Git hooks

- [X] T083 [P] [hooks] Implement `/tmp/smith-manifest-system/templates/git-hooks/post-merge` per Component 13 — bash script, exits 0 silently if `.smith/index/` absent; otherwise execs `claude --print "/smith-index --incremental"`. Triggered by `git pull` / `git merge`.
- [X] T084 [P] [hooks] Implement `/tmp/smith-manifest-system/templates/git-hooks/post-checkout` per Component 13 — bash script, reads `$1` (prior HEAD) and `$2` (new HEAD) from git args, execs `claude --print "/smith-index --incremental --from $1 --to $2"`. Exits 0 silently if `.smith/index/` absent.
- [X] T085 [hooks] Implement `/tmp/smith-manifest-system/tests/hooks/test_git_hooks.sh` — simulates `git pull` (touch ORIG_HEAD, run post-merge) and `git checkout` (run post-checkout with prior/new HEAD args); asserts `/smith-index --incremental` is invoked; asserts silent exit when `.smith/index/` absent.

### Hook registration via install

- [X] T086 [hooks] Implement `/tmp/smith-manifest-system/scripts/install-hooks.sh` per Q4 + Implementation Discovery #9 — parses existing `~/.claude/settings.json`; adds `manifest-updater.sh` to PostToolUse `Write|Edit` array IF not already present, ensuring it is LAST per Decision 7; adds `context-loader.sh` to UserPromptSubmit array IF not already present; idempotent; honors `--no-hooks` flag (skips registration).
- [X] T087 [hooks] Implement `/tmp/smith-manifest-system/settings/smith-settings-fragment.json` update (MOD) — append `manifest-updater.sh` to PostToolUse `Write|Edit` chain after `lint-on-save.sh`; add `context-loader.sh` under new `UserPromptSubmit` block.
- [X] T088 [hooks] Implement hook-ordering assertion test — `tests/hooks/test_hook_chain_order.sh`: parses `~/.claude/settings.json` after install run; asserts `manifest-updater.sh` is LAST in PostToolUse `Write|Edit` chain per Decision 7 and Risk R2 mitigation.

---

## Phase 6: Integration with existing skills

- [X] T089 [integration] Refactor `/tmp/smith-manifest-system/skills/smith-explore/SKILL.md` Phase 1 per Component 7 + Requirement 7 — prepend step 1 (`/smith-navigate` lookup), step 2 (grep candidate locations + immediate neighborhoods), step 3 (escalate to whole-codebase grep when manifest doesn't cover or signals suggest broader impact). Manifest-as-map-not-fence framing. Phases 2+ unchanged.
- [X] T090 [integration] Update `/tmp/smith-manifest-system/skills/smith-build/SKILL.md` per Component 11.B + Requirement 11 — add "Pre-PR file-size check" step that scans `.smith/index/files/` for modified files, lists any with `⚠️ Exceeds 300-line threshold` marker under "File-size advisories" section in PR description. Never blocks PR.
- [X] T091 [integration] Update `/tmp/smith-manifest-system/skills/smith-audit/SKILL.md` per Component 11.C + Requirement 11 — add "File-size hygiene" section to audit report template: counts at 300/500 thresholds, top 10 largest files with decomposition pointers (sourced from `.meta` if present, else live `wc -l`).
- [X] T092 [integration] Update `/tmp/smith-manifest-system/settings/claude-md-template.md` per Q9 + Component 12 — append two new sections AFTER the existing Rules 1-7 rubric block (NOT new graded rules):
  - `## Smith Context System` (advisory: how to use injected `additionalContext`, Must Read / Should Read / Reference Only semantics, fallback when injection absent)
  - `## File Size Awareness` (advisory: check `.meta` before reading large files, warn against full reads of >300-line files)
- [X] T093 [integration] Create `/tmp/smith-manifest-system/templates/constitution.template.md` per Component 12 + Implementation Discovery #2 — minimal preamble + "## File Size Policy" section (300-line guideline, 500-line decomposition threshold, exemption rules for schemas/auto-generated) + "## Project Manifest" section (auto-maintained by hooks, no source-file metadata, run `/smith-index` after refactors, gitignored per selective rules).
- [X] T094 [integration] Update `/tmp/smith-manifest-system/skills/smith/SKILL.md` — `/smith init` auto-runs `/smith-index` as its last setup step per Requirement 5; copies `templates/constitution.template.md` if absent; uses `settings/claude-md-template.md` as source for project-level CLAUDE.md; merges `templates/.gitignore-smith-additions` into project `.gitignore` per Q5; copies `templates/git-hooks/post-merge` and `templates/git-hooks/post-checkout` into `.git/hooks/` and `chmod +x` (per Decision 8); honors `--no-hooks` and `--no-git-hooks` flags.

---

## Phase 7: Install + Uninstall

- [X] T095 [install] Update `/tmp/smith-manifest-system/scripts/install.sh` — add `--install-parsers` and `--install-hooks` dispatch; call `scripts/install-parsers.sh` and `scripts/install-hooks.sh` by default; honor `--no-hooks` per Q4; print summary at end ("Added 2 hooks to ~/.claude/settings.json").
- [X] T096 [install] Update `/tmp/smith-manifest-system/scripts/uninstall.sh` — remove `~/.smith/scripts/parse-python.py`, `parse-js.js`, `vendor/acorn.min.js`, `path-resolver.py`; remove `manifest-updater.sh` and `context-loader.sh` entries from `~/.claude/settings.json`.

---

## Phase 8: Documentation

- [X] T097 [P] [docs] Create `/tmp/smith-manifest-system/docs/manifest-system.md` — user-facing reference covering: what the manifest is, directory structure (`.smith/index/`), how to invoke `/smith-index` (all flags), how 4-tier config resolution works, how heuristic path resolver works, customization (overriding via `system-paths.json`, project parser overrides at `.smith/scripts/`), gitignore policy, fan-out behavior + Q3 note (no kill switch in v1).
- [X] T098 [P] [docs] Update `/tmp/smith-manifest-system/README.md` — add "Manifest System" top-level section linking to `docs/manifest-system.md`; brief explainer of `/smith-index` and `/smith-navigate`.
- [X] T099 [P] [docs] Update `/tmp/smith-manifest-system/CONTRIBUTING.md` — add: (a) hook chain order matters (`manifest-updater.sh` runs LAST per Decision 7); (b) acorn regen procedure per Q8 (`npx esbuild ... --bundle --minify` command line, target node18, single-file CJS output); (c) parser development notes.
- [X] T100 [P] [docs] Update `/tmp/smith-manifest-system/CHANGELOG.md` — feature entry under next release covering all 14 requirements + 8 design decisions + 10 resolved questions.

---

## Phase 9: Final Integration & E2E

- [X] T101 [e2e] End-to-end `/smith-index` full rebuild against `tests/fixtures/sample-project/` — verifies: manifest.md ≤50 lines; per-system manifests ≤80 lines; `.meta` files present for every source file; `.meta` contains `hash`/`lines`/sections (Imports/Functions/Classes/Routes/Exports); system mapping correct via heuristic (services/billing → system-billing, backend/src → system-backend-src, frontend/src → system-frontend-src); total runtime <60s. Implemented in `tests/e2e/test_full_index_rebuild.sh`.
- [X] T102 [e2e] End-to-end `--check` test — verifies hash-only staleness detection: fresh index → "0 stale"; modify one file → flagged stale; rebuild → "0 stale" again. Implemented in `tests/e2e/test_check_staleness.sh`.
- [X] T103 [e2e] End-to-end manifest-updater hook test — simulates PostToolUse stdin JSON, asserts `.meta` written, hooks.log entry, exit 0, small file has no warning, big file (>300 lines) emits valid `additionalContext` JSON, perf <500ms. Implemented in `tests/e2e/test_manifest_updater_hook.sh`.
- [X] T104 [e2e] End-to-end context-loader hook test — simulates UserPromptSubmit input for `/smith-new`, NL trigger "let's smith this", and a plain question. Asserts injection only for Smith triggers; manifest snapshot included for navigator-enabled skills; performance <5s. Implemented in `tests/e2e/test_context_loader_hook.sh`.
- [X] T105 [e2e] End-to-end soft-warning test — verifies that the manifest-missing warning fires on first Smith prompt of a session, `.warned-manifest-missing-<session-id>` marker is written, subsequent prompts with same session ID suppress the warning, and a different session ID re-emits it. Implemented in `tests/e2e/test_soft_warning.sh`.
- [X] T106 [e2e] End-to-end 4-tier config resolution test — sandboxed HOME + tier-3 user-global + tier-4 project override; asserts all 4 tiers contribute, project tier wins for declared keys, field-level merge preserves sibling keys from lower tiers, scalar replace works. Implemented in `tests/e2e/test_4tier_resolution.sh`.
- [X] T107 [e2e] End-to-end path-resolver test — verifies heuristic-only behavior on a fresh project, longest-prefix wins among rules, override beats heuristic for matching paths, heuristic fallback for non-matching paths (when no explicit default), and explicit `default` short-circuits the heuristic. Implemented in `tests/e2e/test_path_resolution.sh`.
- [X] T108 [e2e] End-to-end Quickstart Scenarios A/B/C walk-through — Scenario A (new project bootstrap), Scenario B (existing-project adoption with soft warning → /smith-index → full injection), Scenario C (daily edit flow producing .meta, system manifest patch, >300-line warning, and incremented top-manifest stat). Implemented in `tests/e2e/test_quickstart_scenarios.sh`. Test driver at `tests/e2e/run-all.sh` (exit 0 iff all 8 tests pass).

---

## Notes on Parallelism

- Phase 1 setup tasks T002-T012 are all `[P]` — directory stubs don't conflict.
- Phase 2 parser internals (T015-T020 Python; T021-T027 JS; T028-T031 resolver/lib) are sequential within each parser file but the two parser families are independent — Python (T015-T020) can run in parallel with JS bootstrap (T021), but T022 depends on T021.
- Phase 2 fixtures (T032, T033) and contract tests (T036, T037) are `[P]` — distinct files.
- Phase 3 template files T052, T053, T054 are `[P]` — distinct JSON/text files.
- Phase 5 git hooks T083, T084 are `[P]` — distinct files.
- Phase 8 documentation tasks T097-T100 are all `[P]` — distinct docs.
- Phase 6 integration tasks T089-T094 each touch distinct existing SKILL.md files and can run in parallel EXCEPT T094 which depends on T093 (skill-md edits reference the constitution template).

---

## Acceptance Mapping

| Spec Acceptance Criterion | Tasks |
|---|---|
| `/smith-index` rebuilds 100+ file project in <60s | T039-T051, T055, T102 |
| Edit triggers manifest-updater within 500ms | T060-T070, T081, T103 |
| `/smith-navigate` returns categorized list <3s | T056-T059, T076 |
| `/smith-new` triggers context-loader <5s | T071-T080, T082, T104 |
| Regular conversation has zero overhead | T072, T082 |
| `/smith-help` and `/smith-vault` zero context | T052, T072 |
| Missing manifest → soft warning + vault-only | T077, T106 |
| Source files NEVER contain Smith metadata | Hard constraint — enforced by T015-T027, T060-T070 (no Write to source files) |
| `/smith-explore` Phase 1 calls `/smith-navigate` first | T089 |
| `/smith-build` PR lists >300-line files | T090 |
| `/smith-audit` reports file-size findings | T091 |
| Parser scripts in ~/.smith/scripts/ default; per-project override | T031, T038, T060 |
| 4-tier precedence with field-level merge | T074, T104 |
| `/smith init` auto-invokes `/smith-index` | T094 |
| `--migrate-templates` detects + appends non-destructively | T047 |
| `--check` uses hash-only (SHA-256 first 4KB) | T044, T051 |
| New directory auto-assigned via heuristic | T028-T030, T037, T102 |
| Soft-warning once per session | T077, T104 |
| `git pull` triggers `--incremental` | T046, T083, T085 |
| `git checkout` triggers `--incremental` | T046, T084, T085 |
| `--incremental` re-parses only diffed files | T046, T085 |
| Auto-register hooks; `--no-hooks` skips | T086, T087, T095 |
| `manifest-updater.sh` LAST in chain | T087, T088, T107 |

2026-05-21 — 19-manifest-system
