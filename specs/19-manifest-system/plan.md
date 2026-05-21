---
feature: 19-manifest-system
branch: 19-manifest-system
created: 2026-05-21
status: planning
spec: ./spec.md
artifacts:
  - ./research.md
  - ./data-model.md
  - ./contracts/parser-output.schema.json
  - ./contracts/navigator-output.md
  - ./quickstart.md
---

# Plan: Manifest System & Structured Context Retrieval

This plan operationalizes [`spec.md`](./spec.md). It does not restate the
spec — it commits to the concrete files, languages, contracts, and
sequencing that satisfy spec sections **Requirements 1-14**, the **8 Design
Decisions**, the **Hard Constraints**, and the **Acceptance Criteria**.

**Top-level decisions (post-questions-gate):** All 8 open questions from the
original spec, plus 2 new questions surfaced during planning, have been
resolved at the questions gate (see `./questions.md`). One new architectural
decision (Design Decision 8 — sync mechanism via Claude Code hooks + git
hooks) emerged during the questions gate and is now captured in spec.md.
The plan below reflects all 11 changes.

---

## Technical Context

| Concern | Choice | Notes |
|---|---|---|
| Distribution repo | `smith-repo` (ATTCKDigital/smith) | Public — installed via `npx skills add attck/smith` or `scripts/install.sh`. |
| Per-project state root | `.smith/index/` | Gitignored by default (spec Requirement 1). |
| Per-user state root | `~/.smith/` | Already exists for `logs/hooks.log`; we add `scripts/` and `config/`. |
| Hooks runtime | Bash 3.2+ (macOS default) | Matches existing `hooks/*.sh`. No Bash 4 features. |
| Python parser | `python3` + stdlib `ast` only | Zero third-party deps (spec Requirement 2). |
| JS parser | `node` + **`acorn`** (vendored minified single-file ~150KB) | Committed in [research.md](./research.md). Acorn handles ESM, classes, decorators; JSX via `acorn-jsx`. Per Q8: vendored as a single minified bundle (`scripts/parsers/vendor/acorn.min.js`) via esbuild, not the full tree. Regen procedure documented in `CONTRIBUTING.md`. |
| Hooks JSON parsing | `jq` if present, `python3 -c` fallback | Matches `task-router.sh` pattern. |
| Skill model | Haiku 4.5 for `/smith-navigate` | Spec Assumptions; 3s budget. |
| Target OS | macOS 14+, Linux (glibc 2.31+) | Spec Non-Goals: no Windows. |
| Hook protocol | Claude Code stdin JSON in, JSON or exit-code out | Documented in research.md. |
| Logging | `~/.smith/logs/hooks.log` (structured, one event per line) | Existing convention. |
| Resume log | `~/.smith/logs/smith-index-<timestamp>.jsonl` | Rule 4 (CLAUDE.md). |

---

## Constitution Check

`smith-repo` has no project constitution (no `.specify/memory/constitution.md`).
The relevant rubric is the user's global `~/.claude/CLAUDE.md` (Rules 1-7).
The plan must comply with the rules that apply to features building scripts,
hooks, and skills:

### Rule 1 — Questions Are NOT Action Requests [W: 25]
> "When the user asks a question, respond with words only. Do not act."

**Compliance:** Not implementation-level. `/smith-navigate` standalone
invocation (e.g. `/smith-navigate "where is auth?"`) returns a markdown
listing — never modifies files. `context-loader.sh` is read-only by design
(it only emits `additionalContext`; it cannot Write/Edit). The skills themselves
(`/smith-index`, `/smith-navigate`) are imperative invocations, so Rule 1
does not gate their execution.

### Rule 3 — Question Files Before Complex Changes [W: 15]
> "Before implementing any complex change ... generate a structured question file."

**Compliance:** The spec deferred 8 ambiguities to a questions gate, plus
2 more surfaced during planning. `specs/19-manifest-system/questions.md`
was produced with one entry per question and **all 10 questions are now
ANSWERED** (status: ANSWERED in the frontmatter). The plan and spec have
been updated to reflect those answers, plus the new architectural Decision 8
(sync mechanism via Claude Code hooks + git hooks). Build can proceed.

### Rule 4 — Checkpoint/Resume for Long-Running Processes [W: 15]
> "Any script or pipeline that processes large datasets must implement
> checkpointing, structured logs, resume capability, and status summaries."

**Compliance:** `/smith-index` is the long-running process (target <60s
for 100+ files but easily multi-minute on larger codebases). It must:
- Write a checkpoint after each system completes to
  `.smith/index/.smith-index-checkpoint.json` containing
  `{last_file, last_system, processed_count, started_at}`.
- Write a JSONL log line per file processed to
  `~/.smith/logs/smith-index-<ISO8601>.jsonl` with shape
  `{"timestamp", "item_id", "stage", "status", "error"}` where
  `item_id` is the relative source path and `stage` is
  `parse`|`meta`|`system-update`|`top-update`.
- Accept `--resume` flag that loads checkpoint and skips already-processed
  files (intersection of JSONL log + checkpoint).
- Print summary line on exit:
  `Indexed: N total, N succeeded, N failed, N skipped, T.Ts elapsed`.

### Rule 5 — Session Logging via Smith Vault [W: 10]
> "Session logging is handled automatically by Smith vault hooks. The
> response does NOT manually create session log files."

**Compliance:** No new hook or skill writes into `.smith/vault/sessions/`.
The new `manifest-updater.sh` writes only into `.smith/index/` and
`~/.smith/logs/hooks.log`. `context-loader.sh` reads vault but does not write.

### Rule 6 — General Preferences [W: 8]
> "Python commands use `python3`, not `python`."

**Compliance:** `parse-python.py` is invoked via `python3` in
`manifest-updater.sh` and `/smith-index`. The shebang line is
`#!/usr/bin/env python3`. No shell snippet in plan or scripts uses bare
`python`.

---

## Architecture Overview

### Dataflow A — Incremental update (PostToolUse)

```
   ┌──────────────────────────────┐
   │  Claude Code: Write or Edit  │
   │  tool call completes         │
   └──────────────┬───────────────┘
                  │ stdin JSON {tool_input.file_path, ...}
                  ▼
   ┌──────────────────────────────────────────────────────┐
   │ PostToolUse hook chain (Write|Edit), in order:        │
   │  1. file-change-logger.sh   (existing)                │
   │  2. lint-on-save.sh         (existing — may rewrite)  │
   │  3. manifest-updater.sh     (NEW — runs LAST)         │
   └──────────────┬───────────────────────────────────────┘
                  │
                  ▼
   ┌─────────────────────────────┐
   │ Extension filter            │ → skip if not in
   │ (.py .js .jsx .ts .tsx      │   allowed list
   │  .css .html .sh)            │
   └──────────────┬──────────────┘
                  │
                  ▼
   ┌─────────────────────────────┐
   │ Resolve parser:             │
   │   .smith/scripts/parse-X    │ (project override)
   │   ~/.smith/scripts/parse-X  │ (global fallback)
   └──────────────┬──────────────┘
                  │ exec parser → JSON on stdout
                  ▼
   ┌─────────────────────────────┐    ┌──────────────────────┐
   │ Render .meta (markdown)     │───▶│ .smith/index/files/  │
   │ from JSON                   │    │   <mirror>/<file>.meta│
   └──────────────┬──────────────┘    └──────────────────────┘
                  │
                  ▼
   ┌─────────────────────────────┐
   │ Map file → system using     │
   │ .smith/index/config/        │
   │   system-paths.json         │
   └──────────────┬──────────────┘
                  │
                  ▼
   ┌─────────────────────────────┐    ┌──────────────────────┐
   │ Update systems/<sys>.md     │───▶│ .smith/index/systems/│
   │ (one row for this file)     │    │   <sys>.md (≤80 ln)  │
   └──────────────┬──────────────┘    └──────────────────────┘
                  │
                  ▼
   ┌─────────────────────────────┐    ┌──────────────────────┐
   │ Update manifest.md stats    │───▶│ .smith/index/        │
   │ (totals, thresholds, ts)    │    │   manifest.md (≤50 ln)│
   └──────────────┬──────────────┘    └──────────────────────┘
                  │
                  ▼ if lines>300:
   ┌─────────────────────────────┐
   │ emit additionalContext      │  → main session sees
   │   "⚠️ <path> is N lines..." │    warning before next turn
   └─────────────────────────────┘
```

### Dataflow B — Context injection (UserPromptSubmit)

```
   ┌──────────────────────────────┐
   │ User submits prompt          │
   │ "let's smith this..." OR     │
   │ "/smith-bugfix fix X"        │
   └──────────────┬───────────────┘
                  │ stdin JSON {prompt, session_id, ...}
                  ▼
   ┌──────────────────────────────────────┐
   │ context-loader.sh (NEW)              │
   │ UserPromptSubmit, main session only  │
   └──────────────┬───────────────────────┘
                  │
                  ▼
   ┌──────────────────────────────────────┐
   │ Detect skill:                        │
   │   regex /smith-(\w+)/  OR            │
   │   NL trigger phrase table            │
   │ If no match → exit 0 (zero overhead) │
   └──────────────┬───────────────────────┘
                  │ matched skill = "smith-bugfix"
                  ▼
   ┌──────────────────────────────────────┐
   │ Resolve 4-tier config (Decision 4):  │
   │   built-in fallback                  │
   │ ⨁ templates/context-manifest.default │
   │ ⨁ ~/.smith/config/context-manifest   │
   │ ⨁ .smith/index/config/context-manifest│
   │ → effective config for this skill    │
   └──────────────┬───────────────────────┘
                  │
                  ▼
   ┌──────────────────────────────────────┐
   │ Load vault per config:               │
   │  sessions, ledger, bank, queue,      │
   │  agents (counts per config)          │
   └──────────────┬───────────────────────┘
                  │
                  ▼
   ┌──────────────────────────────────────┐
   │ If config.navigator == true AND      │
   │ .smith/index/manifest.md exists:     │
   │   spawn /smith-navigate (Haiku)      │
   │   timeout 3s                         │
   │ Else if manifest missing:            │
   │   inject soft-warning + vault only   │
   └──────────────┬───────────────────────┘
                  │
                  ▼
   ┌──────────────────────────────────────┐
   │ Assemble additionalContext markdown  │
   │ (Vault section + Navigator section)  │
   └──────────────┬───────────────────────┘
                  │ JSON response: {"hookSpecificOutput":
                  │   {"hookEventName":"UserPromptSubmit",
                  │    "additionalContext":"..."}}
                  ▼
   ┌──────────────────────────────────────┐
   │ Claude Code injects into main turn   │
   │ BEFORE LLM reasoning starts          │
   └──────────────────────────────────────┘
```

---

## File Structure

All paths are relative to repo root (`/tmp/smith-manifest-system/`).
**NEW** = created by this feature. **MOD** = existing file modified.

### Parser scripts (Requirements 2, 3 — Design Decision 5)

| Path | New/Mod | LOC | Language | Purpose |
|---|---|---|---|---|
| `scripts/parsers/parse-python.py` | NEW | ~220 | python3 | Stdlib `ast`-based parser. Source of truth in repo; copied to `~/.smith/scripts/parse-python.py` by installer. |
| `scripts/parsers/parse-js.js` | NEW | ~280 | node | `acorn`-based parser with JSX/TS via plugins. Copied to `~/.smith/scripts/parse-js.js`. |
| `scripts/parsers/vendor/acorn.min.js` | NEW | ~150KB (single file) | js (vendored, minified) | Per Q8: vendored as a single minified bundle (`acorn` + `acorn-jsx` + `acorn-typescript` bundled via `npx esbuild --bundle --minify`). NOT the full tree. Regen procedure in `CONTRIBUTING.md`. |
| `scripts/parsers/path-resolver.py` | NEW | ~80 | python3 | Path → system resolver (per Q7 and spec Requirement 14): tries explicit rules from optional `system-paths.json` first (longest-prefix wins), falls back to built-in heuristic. Called by both `manifest-updater.sh` and `/smith-index`. |
| `scripts/parsers/parser-lib.sh` | NEW | ~60 | bash | Shared helper: `resolve_parser <ext>` returns project-override path or global path. |

### Hooks (Requirements 4, 8 — Design Decision 7)

| Path | New/Mod | LOC | Language | Purpose |
|---|---|---|---|---|
| `hooks/manifest-updater.sh` | NEW | ~180 | bash | PostToolUse `Write\|Edit`. Spec Requirement 4. Runs LAST in chain. |
| `hooks/context-loader.sh` | NEW | ~240 | bash | UserPromptSubmit, main session only. Spec Requirement 8. |
| `hooks/context-loader-lib.py` | NEW | ~200 | python3 | Helper: 4-tier config resolution, vault assembly, sub-agent spawn marshalling. Called by `context-loader.sh` via `python3 -m`. |
| `settings/smith-settings-fragment.json` | MOD | +2 entries | json | Append `manifest-updater.sh` to PostToolUse `Write\|Edit` chain (after `lint-on-save.sh`); add `context-loader.sh` under new `UserPromptSubmit` block. |

### Skills (Requirements 5, 6, 7)

| Path | New/Mod | LOC | Language | Purpose |
|---|---|---|---|---|
| `skills/smith-index/SKILL.md` | NEW | ~280 | markdown | Spec Requirement 5. Includes `--resume`, `--check`, `--system`, `--system-paths` flags. |
| `skills/smith-navigate/SKILL.md` | NEW | ~220 | markdown | Spec Requirement 6. Haiku sub-agent contract, output format from Decision 2. |
| `skills/smith-explore/SKILL.md` | MOD | +60 / -20 | markdown | Spec Requirement 7. Phase 1 now calls `/smith-navigate` first, then greps neighborhoods, then expands. |
| `skills/smith-build/SKILL.md` | MOD | +30 | markdown | Spec Requirement 11.b — list >300-line files in PR description. |
| `skills/smith-audit/SKILL.md` | MOD | +40 | markdown | Spec Requirement 11.c — file-size section in audit report. |
| `skills/smith/SKILL.md` | MOD | +20 | markdown | Spec Requirement 5 — auto-invoke `/smith-index` as last step of `/smith init`. |

### Templates (Requirements 9, 10, 12)

| Path | New/Mod | LOC | Language | Purpose |
|---|---|---|---|---|
| `templates/context-manifest.default.json` | NEW | ~120 | json | Spec Requirement 9. Per-skill config covering `smith-new`, `-bugfix`, `-debug`, `-build`, `-audit`, `-vault`, `-help`, `-bank`, `_default`. |
| `templates/system-paths.json.example` | NEW | ~30 | json | Spec Requirement 10 (optional overrides). Sample path → system rules with `_comment` keys. Per Q7 the file is OPTIONAL — the heuristic engine handles missing config. |
| `templates/constitution.template.md` | NEW | ~180 | markdown | Spec Requirement 12. Includes "File Size Policy" + "Project Manifest" sections. (Smith currently has no constitution template; this introduces one.) |
| `templates/.gitignore-smith-additions` | NEW | ~5 | gitignore | Per Q5: selective gitignore fragment. Ships `.smith/index/files/` and `.smith/index/systems/` as ignored; `manifest.md` and `config/*.json` are committed. Merged into the project's `.gitignore` by `/smith init`. |
| `templates/git-hooks/post-merge` | NEW | ~20 | bash | Per Design Decision 8: copied to `.git/hooks/post-merge` by `/smith init`. Calls `/smith-index --incremental`. Exits 0 silently if `.smith/index/` is absent. |
| `templates/git-hooks/post-checkout` | NEW | ~20 | bash | Per Design Decision 8: copied to `.git/hooks/post-checkout` by `/smith init`. Calls `/smith-index --incremental`. Exits 0 silently if `.smith/index/` is absent. |
| `settings/claude-md-template.md` | MOD | +90 | markdown | Per Q9: append "Smith Context System" and "File Size Awareness" sections AFTER the existing Rules 1-7 rubric block as ADVISORY sections (NOT new graded rules). This is the SAME existing global-rubric template — there is no separate `templates/CLAUDE.template.md` file. |

### Install & uninstall (Decision 5, open question 5)

| Path | New/Mod | LOC | Language | Purpose |
|---|---|---|---|---|
| `scripts/install.sh` | MOD | +80 | bash | Copy `scripts/parsers/*` (including `acorn.min.js` and `path-resolver.py`) into `~/.smith/scripts/` (with backups). Register new hooks in `~/.claude/settings.json` (merge from `settings/smith-settings-fragment.json`) — per Q4 this is **auto-registration by default**, with `--no-hooks` flag to skip. See `scripts/install-hooks.sh`. |
| `scripts/install-hooks.sh` | NEW | ~100 | bash | Per Q4: parses existing `~/.claude/settings.json`, adds `manifest-updater.sh` to PostToolUse `Write\|Edit` array IF not already present (ensures it is LAST per Decision 7), adds `context-loader.sh` to UserPromptSubmit array IF not already present. Idempotent. Honors `--no-hooks` (skip). |
| `scripts/uninstall.sh` | MOD | +30 | bash | Remove `~/.smith/scripts/parse-*` and `~/.smith/scripts/path-resolver.py`. Remove new hook entries from `settings.json`. |
| `scripts/install-parsers.sh` | NEW | ~80 | bash | Extracted parser-install logic so it can be run standalone for upgrades. Idempotent. Verifies `python3` and `node` are on PATH. |

### Tests

| Path | New/Mod | LOC | Language | Purpose |
|---|---|---|---|---|
| `tests/parsers/test_parse_python.py` | NEW | ~150 | python3 + pytest | Unit tests for `parse-python.py`: well-formed file, syntax error, empty file, FastAPI routes, type hints, docstrings. |
| `tests/parsers/test_parse_js.sh` | NEW | ~120 | bash | Integration tests for `parse-js.js`: ESM, JSX, TS, malformed. Uses `node scripts/parsers/parse-js.js` directly. |
| `tests/parsers/fixtures/` | NEW | n/a | sample files | Hand-built `.py`, `.js`, `.tsx` fixtures including a deliberately broken `.py` with `SyntaxError` and a `.jsx` with template-literal edge cases. |
| `tests/hooks/test_manifest_updater.sh` | NEW | ~140 | bash | Simulates hook stdin, asserts `.meta` written, asserts system manifest row updated, asserts performance <500ms. |
| `tests/hooks/test_context_loader.sh` | NEW | ~160 | bash | Simulates 5 prompts: `/smith-new`, NL trigger ("let's smith this"), `/smith-help`, plain question, malformed. Asserts injection only on the first two. |
| `tests/skills/test_smith_index.sh` | NEW | ~120 | bash | End-to-end: runs `/smith-index` on a fixture project, validates manifest.md ≤50 ln, system manifests ≤80 ln, `.meta` files present, `--resume` works after SIGINT. |
| `tests/skills/test_smith_navigate.sh` | NEW | ~80 | bash | Mocks Haiku response, asserts output format matches `contracts/navigator-output.md`. |
| `tests/contracts/test_parser_output_schema.py` | NEW | ~60 | python3 | Validates parser output JSON against `contracts/parser-output.schema.json` using `jsonschema` (test-only dep, not runtime). |

### Documentation

| Path | New/Mod | LOC | Language | Purpose |
|---|---|---|---|---|
| `docs/manifest-system.md` | NEW | ~250 | markdown | User-facing reference: what the manifest is, how to invoke `/smith-index`, how the 4-tier config works, how to customize. |
| `README.md` | MOD | +30 | markdown | Add "Manifest System" section linking to docs/manifest-system.md. |
| `CONTRIBUTING.md` | MOD | +20 | markdown | Note that hook chain order matters (`manifest-updater.sh` runs LAST). |
| `CHANGELOG.md` | MOD | +40 | markdown | Feature entry under next release. |

**Total estimate:** ~32 new files, ~10 modified files, ~3500 LOC including vendored minified `acorn` (~150KB single file, not LOC-counted in the source-of-truth tally).

---

## Component Design

Each subsection below maps 1:1 to a numbered Requirement in spec.md.

### Component 1 — Manifest Directory Structure (`.smith/index/`)

- **Form:** filesystem layout only; no code. Created on demand by `/smith-index`.
- **Layout (per spec Requirement 1):**
  - `manifest.md` (≤50 lines)
  - `systems/<system>.md` (≤80 lines each)
  - `files/<mirrored-path>/<file>.meta` (no line cap)
  - `config/context-manifest.json` (Tier 4 in Decision 4)
  - `config/system-paths.json`
  - `.smith-index-checkpoint.json` (created during long runs; deleted on clean exit)
- **Error handling:** if directory or any subdir missing when a hook reads it, return empty/null without raising.
- **Performance budget:** n/a (filesystem).

### Component 2 — Python Parser (`parse-python.py`)

- **Language:** python3 (stdlib `ast` + `json`).
- **Key functions:**
  - `parse_file(path: str) -> dict` — top-level entry.
  - `_extract_functions(tree) -> list[dict]` — walks `ast.FunctionDef` and `ast.AsyncFunctionDef`. Captures `name`, `line` (`node.lineno`), `params` (`arg.arg` + `arg.annotation` unparsed via `ast.unparse`), `return_type` (`tree.returns`), `docstring_first_line` (`ast.get_docstring(node, clean=True).split('\n')[0]`).
  - `_extract_classes(tree) -> list[dict]` — walks `ast.ClassDef`, recursively collects method names + lines.
  - `_extract_imports(tree) -> list[dict]` — `ast.Import` and `ast.ImportFrom`.
  - `_extract_routes(tree) -> list[dict]` — walks `ast.FunctionDef.decorator_list`, matches calls like `app.get("/path")`, `router.post(...)`, `@app.route(...)`. Returns `{method, path, line, function}`.
  - `_count_lines(source: str) -> int` — `len(source.splitlines())`.
- **I/O contract:** `python3 parse-python.py <path>` → stdout is JSON conforming to `contracts/parser-output.schema.json`. Exit 0 always on parse success or partial parse. Exit 1 only on argument errors.
- **Dependencies:** none.
- **Error handling:** wrap `ast.parse` in try/except `SyntaxError`. On failure, return JSON with empty `functions`, `classes`, `routes`, raw `imports` extracted via regex fallback, plus `errors: [{line, col, message}]`. Per spec hard constraint: never crashes.
- **Performance budget:** <200ms p95 per file. Validated against fixtures up to 2000 lines.

### Component 3 — JS/TS Parser (`parse-js.js`)

- **Language:** node (v18+). Uses vendored `acorn` + `acorn-jsx` + `acorn-typescript`.
- **Key functions:**
  - `parseFile(path)` — entry.
  - `_extractExports(ast)` — walks `ExportNamedDeclaration`, `ExportDefaultDeclaration`, `FunctionDeclaration` with named identifier. Detects React components by heuristic (PascalCase name + returns JSX).
  - `_extractImports(ast)` — `ImportDeclaration`.
  - `_extractRoutes(ast)` — walks `CallExpression` with callee `app.get|post|put|delete` or `router.{verb}`. Express style.
  - `_countLines(src)` — `src.split('\n').length`.
- **I/O contract:** `node parse-js.js <path>` → stdout JSON matching the same schema as `parse-python.py` (with JS-flavored fields).
- **Dependencies:** vendored `acorn@8.x`. Selected in research.md.
- **Error handling:** on `SyntaxError` from acorn, fall back to regex extraction for `export`/`import` and return partial JSON + `errors[]`.
- **Performance budget:** <200ms p95 per file. Cold start of node is ~70ms on macOS — acceptable.

### Component 4 — Manifest Updater Hook (`manifest-updater.sh`)

- **Language:** bash. Calls `python3` and `node` via PATH; calls `jq` if available, falls back to python.
- **Key procedures:**
  1. Read stdin JSON via `cat`.
  2. Extract `tool_input.file_path` via existing pattern (see `file-change-logger.sh`).
  3. Compute extension. If not in allowlist (`.py .js .jsx .ts .tsx .css .html .sh`), exit 0.
  4. Source `scripts/parsers/parser-lib.sh` → `resolve_parser` returns absolute path of script to run, preferring `.smith/scripts/` over `~/.smith/scripts/`.
  5. Run parser, capture JSON. Timeout 1s via `gtimeout`/`timeout` if present; else trust budget.
  6. Compute SHA-256 of first 4KB of source content (per Q6) — this is the `hash` field written into `.meta`. No `mtime` field is written.
  7. Render `.meta` via inline heredoc using `python3 -c "import json,sys; ..."` for templating (no extra deps). Include `hash` and `updated` (timestamp of generation) but NOT `mtime`.
  8. Map to system via `path-resolver.py` (per Q7 and spec Requirement 14): explicit `system-paths.json` rules first (longest-prefix), heuristic fallback for unmatched paths. Default to `unassigned` only for excluded dirs (tests, docs, vendor, etc.).
  9. Update `systems/<sys>.md` — atomic rewrite using `python3` helper (lock via `mkdir -p .smith/index/.lock-<sys>` for crude mutex; release on exit-trap).
  10. Update `manifest.md` stats — same atomic rewrite pattern.
  11. If `lines > 300`: emit `additionalContext` JSON to stdout per Claude Code hook protocol (`{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"⚠️ <path> is <N> lines (>300)..."}}`).
  12. Log structured line to `~/.smith/logs/hooks.log`.
- **Dependencies:** parser scripts, optional `config/system-paths.json`, `path-resolver.py`.
- **Error handling:** every step wrapped with `|| true`. Single goal: never block Claude. On any failure, log to `hooks.log` with `status=skipped` and exit 0.
- **Performance budget:** <500ms p95 per file edit. Budget breakdown: 70ms node cold start (or 30ms python3) + 80ms parse + 50ms file IO + 50ms manifest rewrites + 250ms slack. Per Q3, no kill switch — budget headroom is trusted.

### Component 5 — `/smith-index` Skill

- **Language:** markdown SKILL.md describing procedure; backing script
  `scripts/smith-index/run.sh` (~300 LOC) does the actual work.
- **Key procedures:**
  - Argument parsing: `--check`, `--system <name>`, `--resume`, `--system-paths <path>`, `--migrate-templates` (Q2), `--incremental` (Decision 8).
  - Discovery: `find <root> -type f \( -name '*.py' -o -name '*.js' -o ... \)`, filtered by `.gitignore` if `git` available.
  - For each file: invoke same parser-resolve + parse logic as the updater, then write `.meta`, then defer system-manifest update to a per-system batch.
  - Batch per system: rewrite `systems/<sys>.md` once per system, not once per file (avoids O(N²) rewrites).
  - Bootstrap config: if `.smith/index/config/context-manifest.json` missing, copy from `templates/context-manifest.default.json` (path resolved via skill install path).
  - Bootstrap system-paths: per Q7 the file is OPTIONAL — the path resolver runs heuristic-as-engine. The skill does NOT copy `templates/system-paths.json.example` automatically; the example is only copied if the user passes `--init-system-paths`.
  - **`--check` (hash-only per Q6):**
    - For each `.meta`, compute SHA-256 of the first 4KB of the source file, compare against the `hash` field in `.meta`. Mismatch → stale. Estimated ~5-10s for 400 files; acceptable for a maintenance command.
    - No `mtime` field is read or compared — the `.meta` schema no longer carries one (see data-model.md).
  - **`--migrate-templates` (per Q2):**
    - Scan project for `constitution.md` and `CLAUDE.md` (root and `.specify/memory/`).
    - For each, detect missing section headers ("## File Size Policy", "## Project Manifest", "## Smith Context System", "## File Size Awareness").
    - If a section is missing, write a `.bak` backup of the file (`<name>.bak.<ISO8601>`), then APPEND the section block (sourced from `templates/constitution.template.md` and `settings/claude-md-template.md`) to the file.
    - Idempotent: re-running is a no-op once all sections are present.
    - Print a summary of files modified.
  - **`--incremental` (per Decision 8):**
    - Read git refs from CLI args or env: `--from <ref> --to <ref>` (defaults: `ORIG_HEAD..HEAD` for post-merge, `$1..$2` for post-checkout).
    - `git diff --name-only <from> <to>` → list of changed files.
    - Filter to allowed extensions; for each, run parse + .meta write + system manifest patch (same code path as a single PostToolUse hit).
    - Falls back to no-op (exit 0 with a log entry) if `git` is unavailable or refs are missing.
  - Resume support per **Rule 4 CLAUDE.md**:
    - Write checkpoint JSON every system.
    - Write JSONL log line every file.
    - On `--resume`, read both, skip files marked `status=ok` in the JSONL.
  - Final summary line printed to stdout.
- **I/O contract:** invoked as `/smith-index [flags]`; produces `.smith/index/**` files and logs.
- **Dependencies:** parsers, templates, `path-resolver.py`.
- **Error handling:** per-file failures are logged and counted, never abort the run.
- **Performance budget:** <60s p95 for 100+ files (full rebuild). `--check` 5-10s for 400 files. `--incremental` typically <2s.

### Component 6 — `/smith-navigate` Skill (Haiku Sub-Agent)

- **Language:** markdown SKILL.md instructing Haiku 4.5 how to read the manifest and emit the output format.
- **Inputs (received via prompt context):**
  - User task description.
  - Contents of `.smith/index/manifest.md`.
  - Optional: pre-selected system manifests if caller (`context-loader.sh` or `/smith-explore`) narrows scope.
  - Optional: list of files the caller already considers in-scope, to bias the response.
- **Outputs:** markdown matching `contracts/navigator-output.md` — required sections: `## Relevant Files`, `### Must Read`, `### Should Read`, `### Reference Only`, `### Systems Affected`. File lines use the `[primary: <range>, <label>]` annotation form (Decision 2).
- **Dependencies:** `.smith/index/manifest.md` and `.smith/index/systems/*.md`; optionally `.meta` files for large files when narrowing primary range.
- **Error handling:** if `manifest.md` is missing, return a special structured response:
  ```markdown
  ## Relevant Files
  _Manifest not initialized — run `/smith-index` first._
  ```
  ...and exit normally so the calling hook can detect and inject the soft warning.
- **Performance budget:** 3s p95. Achieved by limiting Haiku to reading `manifest.md` + at most 3 `systems/*.md` files in a single turn.

### Component 7 — `/smith-explore` Phase 1 Refactor

- **Language:** markdown edit to existing `skills/smith-explore/SKILL.md`.
- **Changes:** prepend a step-1 paragraph to Phase 1:
  > "**Step 1: Navigator lookup.** Invoke `/smith-navigate "<feature description>"` to obtain a candidate file list and `Systems Affected` list. If the manifest is absent or returns the "manifest not initialized" sentinel, proceed directly to Step 2 (whole-codebase grep)."
- Step 2 (existing grep flow) is annotated: "grep the candidate locations and their immediate neighborhoods (sibling files in the same directory, files importing/imported by the candidate)."
- Step 3 (new): "If grep signals impact beyond navigator candidates — i.e. matches in files NOT in the candidate list — escalate to whole-codebase grep. The manifest is a map, not a fence."
- Phases 2+ are unchanged (spec Requirement 7).
- **Performance budget:** Phase 1 total ≤10s p95 (was ~7s pure grep; +3s for navigator).

### Component 8 — Context Loader Hook (`context-loader.sh`)

- **Language:** bash + python3 helper (`context-loader-lib.py`).
- **Key procedures:**
  1. Read stdin JSON `{prompt, session_id, cwd, ...}`.
  2. Detect skill:
     - Regex: `\/smith-(new|bugfix|debug|build|audit|vault|help|bank|explore|navigate|index|...)\b`.
     - NL triggers: lookup table mirroring `~/.claude/CLAUDE.md` Rule 2 phrases.
     - If neither, exit 0 with no output (zero overhead).
  3. Invoke `python3 context-loader-lib.py resolve-config <skill>` →
     resolves 4-tier config to a single JSON object printed on stdout.
  4. Load vault sections per resolved config (`sessions: last N`, `ledger: top K`, etc.). Bash reads `.smith/vault/sessions/*.md`, head/tail per config.
  5. If `config.navigator == true`:
     - If `.smith/index/manifest.md` missing → inject soft warning text into `additionalContext`, skip navigator spawn.
     - Else → invoke `claude --print --model haiku --skill smith-navigate "<prompt>"` (or equivalent SDK invocation; resolved in research.md) with `timeout 3`. On timeout/error, log fallback and continue with vault-only.
  6. Compose final markdown block (sample in data-model.md → `additionalContext` injection block).
  7. Emit JSON response per UserPromptSubmit protocol:
     `{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"<assembled markdown>"}}`.
  8. Log structured entry to `~/.smith/logs/hooks.log`: skill, tiers, vault sections, navigator ms, total ms.
- **Dependencies:** `context-loader-lib.py`, `.smith/vault/`, optional `.smith/index/`.
- **Error handling:** every external call is bounded by a timeout and has a fallback. Hook never returns non-zero in normal operation.
- **Performance budget:** <5s p95 total. Sub-budgets: 50ms detect, 100ms config-resolve, 500ms vault read, 3000ms navigator (with hard timeout), 100ms assembly, 250ms slack.

### Component 9 — `templates/context-manifest.default.json`

- Static JSON file.
- Per-skill block schema documented in data-model.md.
- Includes all 8 skill blocks named in spec Requirement 9, plus `_default` block consumed by any unrecognized skill.
- Loaded as **Tier 2** by `context-loader-lib.py`.

### Component 10 — `templates/system-paths.json.example`

- Static JSON file with comments stripped (JSON has no comments — a `_comment` field convention is used per data-model.md).
- Shipped as an example, not auto-applied; user must explicitly copy or `/smith-index` copies it on first run if missing.

### Component 11 — 300-Line File Size Enforcement (5 touchpoints)

- **Touchpoint A (manifest-updater.sh):** see Component 4 step 10.
- **Touchpoint B (/smith-build PR description):**
  - In `skills/smith-build/SKILL.md`, add a "Pre-PR file-size check" step:
    > "Before opening the PR, scan `.smith/index/files/` for all files modified in this branch. List any `.meta` containing `⚠️ Exceeds 300-line threshold` in the PR description under a 'File-size advisories' section. Never abort."
- **Touchpoint C (/smith-audit report):**
  - In `skills/smith-audit/SKILL.md`, add a "File-size hygiene" section to the audit report template: counts at 300/500 thresholds, top 10 largest files with decomposition pointers (sourced from `.meta` if present, else live `wc -l`).
- **Touchpoint D (constitution template):**
  - New `templates/constitution.template.md` includes the "File Size Policy" section verbatim per spec Requirement 12.
- **Touchpoint E (CLAUDE template — per Q9):**
  - Append the "File Size Awareness" section to the EXISTING `settings/claude-md-template.md` (AFTER the rubric block, as an advisory section — NOT as a new graded rule). No new `templates/CLAUDE.template.md` file is created.

### Component 12 — Memory & Template Updates (per Q9)

- **Files added:** `templates/constitution.template.md` ONLY. (Per Q9, `templates/CLAUDE.template.md` is NOT created — this corrects the original plan.)
- **Files modified:**
  - `settings/claude-md-template.md` — append "## Smith Context System" and "## File Size Awareness" sections AFTER the existing Rules 1-7 rubric block. These are ADVISORY sections, not new graded rules — they do not alter the rubric scoring structure.
  - `skills/smith/SKILL.md` — `/smith init` copies `templates/constitution.template.md` if absent in the target project, and uses `settings/claude-md-template.md` as the source for the project-level CLAUDE.md (existing behavior, now with the new advisory sections included).
- **Migration:** existing projects pick up the new sections via `/smith-index --migrate-templates` (per Q2). Templates also take effect automatically for `/smith init` runs going forward.

### Component 13 — Git Hooks for Drift Prevention (Design Decision 8)

- **Form:** two small bash scripts shipped under `templates/git-hooks/`, copied into `.git/hooks/` by `/smith init`.
- **Scripts:**
  - `templates/git-hooks/post-merge` — `#!/usr/bin/env bash`; check if `.smith/index/` exists, exit 0 silently if not; otherwise exec `claude --print "/smith-index --incremental"` (or equivalent CLI invocation resolved in research.md). Triggered by `git pull`, `git merge`.
  - `templates/git-hooks/post-checkout` — same pattern, but reads `$1` (prior HEAD) and `$2` (new HEAD) from git's post-checkout args and passes them to `/smith-index --incremental --from $1 --to $2`. Triggered by `git checkout`.
- **Install:**
  - `/smith init` copies these files into the project's `.git/hooks/` directory and makes them executable (`chmod +x`). If a hook already exists at the target path, the installer prints a warning and creates `.git/hooks/post-merge.smith` instead, recommending the user merge manually.
  - User opt-out: `--no-git-hooks` flag on `/smith init`.
- **Safety:** hooks exit 0 silently if `.smith/index/` is absent — non-Smith-using developers on the same repo see no error spam.
- **Performance budget:** `/smith-index --incremental` typically <2s on a normal pull (5-20 file changes); hard cap none — git operations are already user-paced.

### Component 14 — Path Resolver (`scripts/parsers/path-resolver.py`)

- **Language:** python3 (stdlib `json`, `os.path`). No third-party deps.
- **Key function:** `resolve(file_path: str, project_root: str, system_paths_json: Optional[dict]) -> str` — returns the system name (e.g. `"system-backend-products"`) or `"unassigned"`.
- **Algorithm (per Q7 and spec Requirement 14):**
  1. Compute `rel = os.path.relpath(file_path, project_root)`.
  2. If `system_paths_json` is provided AND has rules, try each rule by longest-prefix match against `rel`. First match wins. Return.
  3. Otherwise apply the built-in heuristic:
     - `services/<name>/...` → `system-<name>`
     - `backend/<name>/...` → `system-backend-<name>`
     - `frontend/<name>/...` → `system-frontend-<name>`
     - `tests/`, `docs/`, `node_modules/`, `.venv/`, `vendor/`, `dist/`, `build/`, `.git/` → `unassigned`
     - Other top-level source dirs → `system-<dirname>`
     - Root-level files → `unassigned`
- **I/O contract:** import as a module (preferred from `/smith-index`) or invoke as `python3 path-resolver.py <file_path> <project_root>` for shell callers (used by `manifest-updater.sh`).
- **Acceptance criterion (per spec):** a newly-created directory containing source files is automatically assigned to a system on first edit, without `system-paths.json` updates.
- **Tests:** `tests/contracts/test_path_resolver.py` covers: explicit-rule precedence (longest-prefix), heuristic for each pattern (services/, backend/, frontend/, other), exclusion of tests/docs/vendor/, root-level files, overlapping rules.

---

## Phase-by-phase Build Order

The autonomous build (handed off to `/smith-build` after the questions
gate) executes phases in this order. Each phase has a clear exit
criterion. Phases are not strictly serial — Phase 12 (tests) and Phase
13 (docs) can run in parallel with later phases.

### Phase 1 — Bootstrap directories & install paths
- Create `scripts/parsers/`, `scripts/parsers/vendor/`, `templates/`,
  `tests/parsers/`, `tests/hooks/`, `tests/skills/`, `tests/contracts/`.
- Add stub `templates/.gitkeep` files where needed.
- Update `scripts/install.sh` skeleton to recognize a new `--install-parsers` invocation (logic filled in Phase 11).
- **Exit:** repo tree matches "File Structure" above with empty stubs.

### Phase 2 — Parser scripts (Requirements 2, 3)
- Implement `scripts/parsers/parse-python.py` end-to-end.
- Vendor `acorn` into `scripts/parsers/vendor/acorn/`. Write
  `scripts/parsers/parse-js.js` end-to-end.
- Write `scripts/parsers/parser-lib.sh` (shared resolve helper).
- Write the unit-test fixtures and `tests/parsers/test_parse_python.py` +
  `tests/parsers/test_parse_js.sh`. Confirm tests pass.
- **Exit:** both parsers return valid JSON for fixtures and degrade
  gracefully on broken input. <200ms p95.

### Phase 3 — `/smith-index` skill (Requirement 5)
- Write `skills/smith-index/SKILL.md` + `scripts/smith-index/run.sh`.
- Implement `--resume`, `--check`, `--system`, JSONL log, checkpoint per Rule 4.
- Write `tests/skills/test_smith_index.sh`.
- **Exit:** runs on `tests/parsers/fixtures/` and bootstrap directory; resumes after SIGINT.

### Phase 4 — Parser robustness validation (no smith-repo self-indexing)
- Per Q1, smith-repo does NOT get its own `.smith/index/` manifest. This phase no longer dogfoods on smith-repo.
- Instead: run the parsers stand-alone against a representative set of files from `smith-repo` (a hand-picked subset of `skills/*/SKILL.md`, `hooks/*.sh`, `scripts/*.py`) to validate robustness, but do NOT generate or commit a full `.smith/index/` for smith-repo. Output is discarded.
- **Exit:** parsers complete on all tested files in <60s aggregate with zero uncaught exceptions. Performance budget validated.

### Phase 5 — `manifest-updater.sh` hook (Requirement 4)
- Implement hook per Component 4.
- Register LAST in `settings/smith-settings-fragment.json`
  `PostToolUse Write|Edit` chain.
- Write `tests/hooks/test_manifest_updater.sh`.
- **Exit:** hook updates `.meta` and system manifest within 500ms.
  Verified by simulated stdin tests.

### Phase 6 — `/smith-navigate` skill (Requirement 6)
- Write `skills/smith-navigate/SKILL.md` per Component 6 + contract.
- Write `tests/skills/test_smith_navigate.sh` (mocks Haiku).
- **Exit:** navigator returns the documented output shape against a
  fixture manifest.

### Phase 7 — `context-loader.sh` hook + defaults (Requirement 8, 9)
- Write `hooks/context-loader.sh` + `hooks/context-loader-lib.py`.
- Write `templates/context-manifest.default.json` per Requirement 9.
- Implement 4-tier resolution per Decision 4.
- Register hook under new `UserPromptSubmit` block in
  `settings/smith-settings-fragment.json`.
- Write `tests/hooks/test_context_loader.sh`.
- **Exit:** hook injects context for matching skills, exits 0 silently
  for non-matching prompts, p95 <5s including navigator.

### Phase 8 — `/smith-explore` Phase 1 refactor (Requirement 7)
- Edit `skills/smith-explore/SKILL.md` per Component 7.
- Update tests if any existing tests gate behavior.
- **Exit:** `/smith-explore` calls `/smith-navigate` first, then greps.

### Phase 9 — 300-line enforcement integrations (Requirement 11)
- Edit `skills/smith-build/SKILL.md` (PR description block).
- Edit `skills/smith-audit/SKILL.md` (report section).
- **Exit:** `/smith-build` PR descriptions list >300-line files;
  `/smith-audit` reports thresholds + top-10 largest.

### Phase 10 — Template updates (Requirement 12)
- Write `templates/constitution.template.md`.
- Per Q9: **do NOT create `templates/CLAUDE.template.md`**. Instead, edit `settings/claude-md-template.md` to append the "Smith Context System" and "File Size Awareness" sections AFTER the rubric.
- Write `templates/.gitignore-smith-additions` (per Q5).
- Edit `skills/smith/SKILL.md` to install templates during `/smith init`,
  merge `.gitignore-smith-additions` into the project `.gitignore`, and auto-run
  `/smith-index` as final step (also satisfies Requirement 5).
- **Exit:** fresh `/smith init` against a temp dir produces the expected
  files (constitution, CLAUDE.md, merged .gitignore).

### Phase 11 — Install script updates (Decision 5, Q4)
- Write `scripts/install-parsers.sh` (idempotent installer for
  `~/.smith/scripts/parse-*` and `~/.smith/scripts/path-resolver.py` with backup of existing files).
- Write `scripts/install-hooks.sh` (per Q4): parses existing
  `~/.claude/settings.json`, adds `manifest-updater.sh` to PostToolUse
  `Write|Edit` array IF not already present (ensures LAST position per
  Decision 7), adds `context-loader.sh` to UserPromptSubmit array IF not
  already present. Idempotent.
- Edit `scripts/install.sh` to call `install-parsers.sh` and
  `install-hooks.sh`. Default behavior is **auto-register both hooks**
  (per Q4); honor `--no-hooks` flag to skip hook registration.
- Edit `scripts/uninstall.sh` symmetrically.
- **Exit:** `bash scripts/install.sh -y` succeeds on a clean macOS/Linux
  test fixture and leaves `~/.smith/scripts/parse-*` + `path-resolver.py`
  + the two new hooks registered in `~/.claude/settings.json`. Passing
  `--no-hooks` skips the hook registration step.

### Phase 11b — Git hooks template + wiring (Decision 8)
- Write `templates/git-hooks/post-merge` and `templates/git-hooks/post-checkout`
  per Component 13.
- Edit `skills/smith/SKILL.md` so `/smith init` copies these hooks into
  the project's `.git/hooks/` and `chmod +x`. If a hook already exists,
  rename to `.smith` suffix and warn.
- Honor `--no-git-hooks` flag on `/smith init` to skip.
- Write `tests/hooks/test_git_hooks.sh`: simulate `git pull` and
  `git checkout`; assert `/smith-index --incremental` is invoked.
- **Exit:** in a fresh init, `git pull` and `git checkout` both trigger
  `/smith-index --incremental` and the manifest is updated for changed
  files.

### Phase 12 — Tests
- (Most tests authored in their respective phases; this phase wires the
  full suite into `tests/run-all.sh` or equivalent and validates CI.)
- Add performance assertions to each test that has a budget.
- **Exit:** all tests green.

### Phase 13 — Documentation
- Write `docs/manifest-system.md`.
- Update `README.md` with a top-level "Manifest System" section.
- Update `CONTRIBUTING.md` with hook-order note + acorn regen procedure
  (Q8: `npx esbuild ... --bundle --minify` → `acorn.min.js`).
- Update `CHANGELOG.md`.
- **Exit:** docs cover all 14 requirements and 8 design decisions.

---

## Testing Strategy

### Unit tests
- **`parse-python.py`** — fixtures cover: vanilla function, async function,
  class with methods, FastAPI `@app.get` and `@router.post`, type hints
  with `Optional[T]` and `dict[str, list[int]]`, docstring extraction,
  `SyntaxError`, empty file. Each fixture is a single `.py` file in
  `tests/parsers/fixtures/python/`.
- **`parse-js.js`** — fixtures cover: ESM `export`, default export,
  React component, `import` deduplication, Express `app.get`, JSX
  fragment, TS interface, deliberately malformed JSX with unclosed tag.
- **Mapper logic** — `tests/contracts/test_mapper.py` exercises
  longest-prefix matching with overlapping rules.

### Integration tests
- **`/smith-index` full run** — fixture project under
  `tests/fixtures/sample-project/` with ~30 source files across `.py`,
  `.js`, `.tsx`. Test:
  - First run produces all expected manifest artifacts.
  - Second run with `--check` reports no staleness.
  - Touching a file then running `--check` reports it stale.
  - SIGINT mid-run; rerun with `--resume` continues without
    reprocessing already-done files.
- **`context-loader.sh`** — feed 5 prompts; assert the JSON response
  structure and `additionalContext` contents match expectations.

### Performance tests
- **`manifest-updater.sh`** — measured 50 times against representative
  file sizes (50 LOC, 300 LOC, 800 LOC). Assert p95 <500ms.
- **`context-loader.sh`** — measured 20 times against a mocked Haiku
  responding in 1.5s. Assert p95 <5s.
- **Parsers** — measured 100 times each against a 1000-line file.
  Assert p95 <200ms.
- **`/smith-index`** — measured against a 120-file fixture. Assert
  total <60s.

### Negative tests
- Source file with embedded null byte → parser returns partial JSON, no crash.
- `.smith/index/config/system-paths.json` missing → updater assigns
  to `unassigned`, no crash.
- `.smith/index/manifest.md` missing → context-loader injects soft
  warning, no crash.
- Haiku sub-agent timeout at 3s → context-loader falls back to vault-only.

---

## Risks & Mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | **`node` cold-start latency** blows the parser 200ms budget on machines without warm node cache. | M | M | Vendor `acorn` directly (avoids `npm` resolution at startup); pre-compute `require.cache` path in `parse-js.js` to skip unnecessary loads. Budget verified empirically in Phase 2. |
| R2 | **Hook chain ordering** silently regresses when `settings.json` is regenerated by `/smith init` or another tool, causing `manifest-updater.sh` to run before `lint-on-save.sh` and capture pre-format state (Decision 7 violated). | M | M | (a) Document ordering in `CONTRIBUTING.md`. (b) Add a test in `tests/hooks/` that parses `~/.claude/settings.json` after install and asserts ordering. (c) Make `install.sh` deterministically re-order on merge. |
| R3 | **Sub-agent fan-out cost** during heavy parallel `/smith-build` (e.g. 20+ Writes in parallel) triggers 20+ parser invocations, blowing aggregate latency well beyond the per-file 500ms budget — Smith perceived as "slow." | M | M | Per Q3: no kill switch in v1. Trust the <500ms-per-file headroom (acorn measured at 135ms, python AST faster). If real-world heavy builds show stalls, revisit in v2 with an env-var or trap-based approach. Document in `docs/manifest-system.md` so users can report observed stalls. |
| R4 | **Acorn version drift** — a vendored `acorn` falls behind upstream and miscompiles newer JS syntax (e.g. records & tuples). | L | L | Pin vendored version with a `vendor/acorn/VERSION` file. Re-vendoring procedure documented in `CONTRIBUTING.md`. JS parser falls back to regex extraction on parse error, so newer syntax produces partial JSON instead of empty. |
| R5 | **Hook protocol drift** — Claude Code changes the stdin JSON shape or `additionalContext` injection format, breaking `manifest-updater.sh` and `context-loader.sh`. | L | H | (a) Use defensive JSON extraction (existing pattern in `file-change-logger.sh`). (b) Pin tested Claude Code version in `CONTRIBUTING.md`. (c) Tests in `tests/hooks/` use real stdin samples captured from a known-good Claude Code version. (d) Hooks fail-open: exit 0 on JSON parse failure rather than block tool use. |
| R6 | **Soft-warning fatigue** — users with `.smith/index/` missing see the same warning on every Smith invocation and learn to ignore it. (Decision 3 trade-off.) | M | L | Per Q10: show the warning at most once per session. Track shown state via per-session marker file `.smith/vault/.warned-manifest-missing-<session-id>` (per-session, NOT per-project — a stale marker can't suppress future sessions). NO escalation logic in v1. Mention `/smith-index` in the warning text once and trust the user. (Implemented in `context-loader-lib.py`.) |
| R7 | **`acorn` install footprint** — vendoring third-party code adds noise to `git log`, `git blame`, code search, and increases repo size. | L | L | Per Q8: ship a single minified bundle `scripts/parsers/vendor/acorn.min.js` (~150KB) rather than the full tree (~500KB+ as it was before). Place a `scripts/parsers/vendor/README.md` documenting origin, version, license, regen procedure (`npx esbuild ... --bundle --minify`). Add `scripts/parsers/vendor/` to `.gitattributes` as `linguist-vendored=true` so GitHub language stats stay accurate. |

---

## Implementation Discoveries

These are items discovered during planning that were NOT in `spec.md`
explicitly but are required for the feature to function correctly.
Items marked **[INVALIDATED]** were contradicted by the questions-gate
answers and no longer apply.

1. **[INVALIDATED by Q9]** ~~`templates/CLAUDE.template.md` is a NEW file distinct from
   `settings/claude-md-template.md`.~~ Per Q9, this is INCORRECT. The new
   "Smith Context System" and "File Size Awareness" sections are appended
   to the EXISTING `settings/claude-md-template.md` AFTER the Rules 1-7
   rubric block (as advisory sections, NOT new graded rules). There is no
   separate per-project CLAUDE template file.
2. **`templates/constitution.template.md` does not yet exist in the
   repo.** Spec Requirement 12 talks about adding sections to it, but
   it's a new file in this distribution. The plan introduces it from
   scratch with the spec's "File Size Policy" + "Project Manifest"
   sections plus a minimal preamble. (STILL VALID.)
3. **`scripts/install-parsers.sh`** is an internal helper not named in
   spec.md but needed so users can refresh just the parser scripts
   (e.g. after a Smith upgrade) without rerunning the full installer. (STILL VALID.)
4. **`scripts/parsers/parser-lib.sh`** — shared resolver function so
   `manifest-updater.sh` and `/smith-index` don't duplicate the
   override-resolution logic. (STILL VALID.)
5. **`context-loader-lib.py`** — extracted Python helper because the
   4-tier merge logic is too gnarly for bash. Bash hook stays a thin
   wrapper. (STILL VALID.)
6. **`.smith/index/.smith-index-checkpoint.json`** — checkpoint state
   file required by Rule 4 (CLAUDE.md) for the `--resume` flag.
   Lives under `.smith/index/` and is `.gitignore`d with the rest. (STILL VALID.)
7. **[REVISED per Q10]** Per-session warning de-duplication marker
   `.smith/vault/.warned-manifest-missing-<session-id>` (NOT the
   per-project `.warned-manifest-missing` originally suggested). This
   prevents a stale per-project marker from suppressing legitimate warnings
   in future sessions. No escalation logic — v1 fires once per session and
   stops there.
8. **`vendor/README.md` and `.gitattributes` linguist marker** — needed
   to keep the vendored `acorn` from polluting repo stats. Per Q8, the
   vendored asset is the single minified file `acorn.min.js` (not a tree).
9. **`scripts/install-hooks.sh`** (NEW per Q4) — extracted hook-registration
   logic so `npx skills add attck/smith` can auto-register the two new
   hooks idempotently. Honors `--no-hooks` opt-out.
10. **`scripts/parsers/path-resolver.py`** (NEW per Q7) — path → system
    resolver running heuristic-as-engine with `system-paths.json` as
    optional overrides. Called by both `manifest-updater.sh` and
    `/smith-index`.
11. **`templates/.gitignore-smith-additions`** (NEW per Q5) — selective
    gitignore fragment merged into the project's `.gitignore` by `/smith init`.
12. **`templates/git-hooks/post-merge` and `post-checkout`** (NEW per Decision 8)
    — per-project git hooks installed by `/smith init` to catch up the
    manifest after git operations.

---

## Spec Open Questions — RESOLVED at Questions Gate

All 8 open questions from spec.md, plus 2 new questions surfaced from
plan.md's Implementation Discoveries, were answered at the questions gate.
Full reasoning lives in `./questions.md`.

| # | Question | Resolved Answer | Where reflected |
|---|---|---|---|
| Q1 | Does smith-repo get its own `.smith/index/`? | **B — skip** (consumer projects only) | spec Non-Goals; plan Phase 4 reworked (no self-indexing) |
| Q2 | Migration helper for existing Smith projects? | **B — `/smith-index --migrate-templates` flag** | spec Requirement 5; plan Component 5 |
| Q3 | Sub-agent fan-out kill switch? | **B — no kill switch in v1** | spec Non-Goals; plan Component 4, R3 |
| Q4 | Hook auto-registration during install? | **A — auto-register, `--no-hooks` opt-out** | spec Requirements 4 + 8; plan Phase 11, `install-hooks.sh` |
| Q5 | `.smith/index/` gitignore default? | **C — selective** (files/, systems/ ignored; manifest.md + config/ committed) | spec Requirement 1; plan templates inventory + `.gitignore-smith-additions` |
| Q6 | Manifest staleness detection? | **B — hash-only** (SHA-256 of first 4KB) | spec Requirement 5; plan Component 5 `--check`, data-model `.meta` schema |
| Q7 | System auto-detection without `system-paths.json`? | **Path 2 — heuristic-as-engine, system-paths.json-as-overrides** | spec Requirement 14; plan Component 14 (`path-resolver.py`) |
| Q8 | Vendored `acorn` — concerning? | **C — vendor minified single-file (~150KB) via esbuild** | plan Technical Context + Risks R7 + Phase 13 CONTRIBUTING.md note |
| Q9 | CLAUDE.md template — new file or modify existing? | **A — modify existing `settings/claude-md-template.md`** (append AFTER rubric, advisory not graded) | spec Requirement 12; plan Component 12 + Phase 10 (no new CLAUDE.template.md) |
| Q10 | Soft-warning frequency? | **B — once per session, no escalation** (per-session marker `.warned-manifest-missing-<session-id>`) | plan R6 + Implementation Discovery #7 |

**Plus New Decision #8 (architectural):** Sync mechanism for drift
prevention uses Claude Code hooks + git hooks; filesystem-watcher daemon
deferred to v2. Captured in spec.md Design Decision 8 + Requirements 13
and Component 13 here.

**Decisions count now: 8** (was 7) — Decision 8 (sync mechanism) added.
**Requirements count now: 14** (was 12) — added Requirement 13 (git hooks)
and Requirement 14 (path resolver).

2026-05-21 12:01:00 — 19-manifest-system
2026-05-21 14:32:00 — 19-manifest-system (post-questions-gate update; 10 answers + 1 new decision applied)
