# Manifest System & Structured Context Retrieval

> User guide for Smith's precomputed project index and Haiku-powered navigator.

Last reviewed: 2026-05-21

---

## Overview

### What it is

The Manifest System is a deterministic retrieval layer for Smith. It replaces
soft natural-language guidance ("read the system specs", "navigate to the
relevant files", "check the vault") with a precomputed, hierarchical index of
your project — described in five places:

- **`.smith/index/manifest.md`** — top-level overview. Systems table, aggregate
  stats. Capped at ≤50 lines.
- **`.smith/index/systems/<name>.md`** — one file per system. Per-file rows
  with exports + line count, grouped by directory. Capped at ≤80 lines each.
- **`.smith/index/files/<mirrored-path>/<file>.meta`** — per-file metadata:
  functions, classes, imports, routes, total lines, optional 300-line warning.
- **`.smith/index/config/context-manifest.json`** — per-skill context-loading
  config (vault sections, navigator on/off, system spec scope).
- **`.smith/index/config/system-paths.json`** *(optional)* — explicit path →
  system mapping overrides. The path resolver runs heuristic-as-engine; this
  file only overrides the heuristic for specific paths.

### Why it matters

Soft guidance is interpreted by the LLM at runtime. The same skill on the same
codebase can produce materially different file selections from one run to the
next — sometimes thorough, sometimes missing a cross-referenced helper that
matters. The manifest system eliminates this variance:

- **Haiku navigator** reads the manifest and returns a categorized file list
  (Must Read / Should Read / Reference Only / Systems Affected) with
  primary-section annotations.
- **Context-loader hook** injects that list as `additionalContext` *before*
  the main session's LLM starts reasoning. Claude sees the right files on
  turn one.
- **Manifest-updater hook** keeps the index current after every edit — no
  manual rebuild required during normal work.

Outcomes:

- Fewer "Claude read the wrong files" silent failures.
- Lower token usage from speculative reads (annotated whole-file > grep
  everything).
- Faster `/smith-explore` — manifest lookup before broad grep.
- File-size hygiene visible throughout the workflow (300/500-line thresholds
  in `.meta`, PR descriptions, audit reports).
- **Zero overhead for regular conversation** — the context-loader
  short-circuits when no Smith trigger is present.

### What it is NOT

- Not a fence. `/smith-explore` and friends retain full grep-everywhere
  capability when the manifest doesn't cover the query or when initial
  signals suggest broader impact than the navigator surfaced.
- Not a source-of-truth. The manifest is regenerated from the codebase; it
  never modifies source files. All Smith metadata lives in `.smith/index/`.
- Not committed (mostly). `.smith/index/files/` and `.smith/index/systems/`
  are gitignored. The top-level `manifest.md` and `config/` ARE committed
  (team-shared overview + config).
- Not Windows-supported (yet). macOS and Linux only for the initial release.
- Not a filesystem watcher. v1 catches in-session edits via a hook and
  cross-session drift via git hooks (`post-merge`, `post-checkout`). A
  filesystem-watcher daemon is deferred to v2.

---

## Architecture

```
                                ┌────────────────────────────────────────┐
                                │   User edits a file via Claude Code    │
                                └──────────────────┬─────────────────────┘
                                                   │ Write | Edit
                                                   ▼
                  ┌──────────────── PostToolUse chain ────────────────┐
                  │ 1. file-change-logger.sh                          │
                  │ 2. lint-on-save.sh   (may reformat the file)      │
                  │ 3. manifest-updater.sh  ◄── LAST so it sees       │
                  │       │                     post-lint state       │
                  └───────┼───────────────────────────────────────────┘
                          │
              extension allowed?  ──No──▶ silent exit 0
                          │ Yes
                          ▼
              ┌─────── parser-lib.sh ───────┐
              │ resolve_parser <.ext>       │
              │   - prefer .smith/scripts/  │
              │   - fall back to ~/.smith/  │
              └─────────────┬───────────────┘
                            ▼
                  ┌── parse-python.py ──┐   ┌── parse-js.js ───┐
                  │ stdlib ast only     │   │ vendored acorn   │
                  │ <200ms p95          │   │ <200ms p95       │
                  └──────────┬──────────┘   └──────────┬───────┘
                             │ JSON                    │
                             └────────────┬────────────┘
                                          ▼
                            ┌─── path-resolver.py ───┐
                            │ heuristic + optional   │
                            │ system-paths.json      │
                            │ overrides              │
                            └─────────┬──────────────┘
                                      ▼
              ┌────────────── manifest-updater.sh ──────────────┐
              │  Writes:                                        │
              │   • .smith/index/files/<mirrored>/<file>.meta   │
              │   • .smith/index/systems/<sys>.md  (atomic)     │
              │   • .smith/index/manifest.md  (stats)           │
              │  If lines > 300:                                │
              │   • emits additionalContext warning             │
              └─────────────────────────────────────────────────┘


                                ┌────────────────────────────────────────┐
                                │   User submits a prompt                │
                                │   (e.g. "/smith-bugfix products")      │
                                └──────────────────┬─────────────────────┘
                                                   │ UserPromptSubmit
                                                   ▼
                            ┌────── context-loader.sh ──────┐
                            │  Smith trigger detected?      │
                            │   - /smith-* command          │
                            │   - NL trigger phrase         │
                            └───────────────┬───────────────┘
                                            │
                              No ◄──────────┴──────────▶ Yes
                              │                          │
                              ▼                          ▼
                          exit 0                  context-loader-lib.py
                          (zero overhead)         ┌──────────────────┐
                                                  │ Resolve 4-tier   │
                                                  │ context-manifest │
                                                  └────────┬─────────┘
                                                           ▼
                                                  Load vault sections
                                                  (sessions, ledger,
                                                   bank, agents, queue)
                                                           │
                                              navigator: true ?
                                                           │
                                                 Yes ◄─────┴─────▶ No
                                                 │                  │
                                                 ▼                  ▼
                                       Spawn /smith-navigate  Vault only
                                       (Haiku 4.5, 3s budget)
                                                 │
                                                 ▼
                                       Categorized file list
                                       (Must Read / Should Read /
                                        Reference Only / Systems)
                                                 │
                                                 ▼
                                       Compose additionalContext
                                       (markdown + HTML comment header
                                        identifying skill + tier + flags)
                                                 │
                                                 ▼
                                       Claude's next turn starts
                                       with the file list already
                                       in context
```

---

## Components

| Path | Role |
|---|---|
| `scripts/parsers/parse-python.py` | Python AST parser (stdlib `ast` only). Emits JSON per the parser schema. |
| `scripts/parsers/parse-js.js` | JS/TS/JSX/TSX parser. Uses vendored acorn 8.x + acorn-jsx + acorn-typescript. |
| `scripts/parsers/vendor/acorn.min.js` | Single-file CJS bundle (~150KB) of acorn + plugins. Built via esbuild. |
| `scripts/parsers/path-resolver.py` | Heuristic + optional-overrides path → system mapper. |
| `scripts/parsers/parser-lib.sh` | Bash helper. `resolve_parser <ext>` returns absolute parser path, preferring per-project override. |
| `scripts/smith-index/run.sh` | Bash entrypoint for `/smith-index` with all its flags. |
| `skills/smith-index/SKILL.md` | Skill manifest for `/smith-index`. |
| `skills/smith-navigate/SKILL.md` | Skill manifest for `/smith-navigate` (Haiku 4.5 sub-agent). |
| `hooks/manifest-updater.sh` | PostToolUse `Write\|Edit` hook. Updates `.smith/index/` incrementally. |
| `hooks/context-loader.sh` | UserPromptSubmit hook. Thin wrapper around `context-loader-lib.py`. |
| `hooks/context-loader-lib.py` | Config resolution + vault loading + injection composition logic. |
| `templates/git-hooks/post-merge` | Per-project git hook. Runs `/smith-index --incremental` after `git pull`/`git merge`. |
| `templates/git-hooks/post-checkout` | Per-project git hook. Runs `/smith-index --incremental --from <prev> --to <new>` after branch switches. |
| `templates/context-manifest.default.json` | Tier 2 shipped default for per-skill context config. |
| `templates/system-paths.json.example` | Optional example for explicit overrides (heuristic is the default engine). |
| `templates/.gitignore-smith-additions` | Merged into a project's `.gitignore` by `/smith init`. |
| `templates/constitution.template.md` | New-project constitution template with "File Size Policy" + "Project Manifest" sections. |
| `settings/claude-md-template.md` | Global rubric template — now appends "Smith Context System" + "File Size Awareness" advisory sections. |
| `scripts/install-parsers.sh` | Copies parsers to `~/.smith/scripts/`. Idempotent; backs up existing files. |
| `scripts/install-hooks.sh` | Registers `manifest-updater.sh` and `context-loader.sh` in `~/.claude/settings.json`. Enforces LAST invariant. |
| `scripts/install-git-hooks.sh` | Installs `.git/hooks/post-merge` and `post-checkout` per-project. |

---

## Setup

### New project (recommended path)

```sh
# One-time global install (skills + hooks + parsers)
npx skills add ATTCKDigital/smith
# or for the full installer (skills + hooks + scheduler):
curl -fsSL https://raw.githubusercontent.com/ATTCKDigital/smith/main/scripts/install.sh | bash

# Per-project bootstrap
cd ~/Projects/my-new-project
git init
```

In Claude Code:

```
/smith init
```

`/smith init` runs the standard interview (project type, languages, framework),
generates `CLAUDE.md` and `.specify/memory/constitution.md` with the new
sections, creates `.smith/vault/`, merges `templates/.gitignore-smith-additions`
into `.gitignore`, installs per-project git hooks, and **invokes `/smith-index`
as its final step** so the manifest is ready before any other Smith workflow
runs. Expected output:

```
/smith init: Running initial manifest build (/smith-index)…
/smith-index: Found 47 source files across 5 candidate systems.
/smith-index: Bootstrapping config/context-manifest.json from defaults.
/smith-index: Indexed 47 files in 12.8s.
/smith-index: 47 succeeded, 0 failed, 0 skipped.
```

### Existing project (adoption path)

Two-step migration:

```
/smith-index --migrate-templates
/smith-index
```

The `--migrate-templates` step detects missing sections in any existing
`constitution.md`/`CLAUDE.md` (e.g. "File Size Policy", "Project Manifest",
"Smith Context System", "File Size Awareness") and appends them
non-destructively, writing a `.bak.<ISO8601>` backup of each modified file.
The second step performs the full index build.

If you skip the explicit steps, Smith degrades gracefully: the first
`/smith-*` invocation injects a soft warning ("Manifest not initialized — run
`/smith-index` to enable structured context retrieval. Proceeding with vault
context only.") and continues with vault-only context. The warning fires at
most once per session.

### Per-project git hooks

`/smith init` installs them automatically. To install them in a project that
already has Smith without re-running init:

```sh
./scripts/install-git-hooks.sh
```

The hooks (`post-merge`, `post-checkout`) run `/smith-index --incremental` to
catch up the manifest after `git pull`, `git merge`, and `git checkout`. They
exit 0 silently if `.smith/index/` is absent (so non-Smith teammates on the
same repo aren't affected).

To opt out, delete the hook files manually or pass `--no-git-hooks` to
`/smith init`.

---

## Daily Use

### What happens automatically

You don't need to think about the manifest day-to-day. The two hooks handle
maintenance:

1. **Every Write/Edit fires `manifest-updater.sh`.** It runs LAST in the
   PostToolUse chain (after `file-change-logger.sh` and `lint-on-save.sh`)
   so it sees the post-lint final file state. It updates the `.meta` file,
   the relevant `systems/<sys>.md`, and the top-level stats. Typical
   duration: ~100ms.

2. **Every UserPromptSubmit fires `context-loader.sh`.** It detects Smith
   triggers — `/smith-*` commands and the natural-language trigger phrases
   from `~/.claude/CLAUDE.md` Rule 2 ("let's smith this", "fix this", "debug
   this", "bank this for later", etc.). If no trigger matches, it exits
   silently within ~20ms. If a trigger matches, it resolves the 4-tier
   config, loads vault sections, optionally spawns `/smith-navigate`, and
   injects `additionalContext`. Typical duration: ~3.7s with navigator,
   ~50ms vault-only.

3. **Every `git pull` / `git checkout`** runs `/smith-index --incremental`
   via the per-project git hook.

### Manual commands

```sh
# Full rebuild
/smith-index

# Freshness check (does NOT rebuild)
/smith-index --check

# Partial rebuild for one system
/smith-index --system system-15-command-center

# Migrate template sections into an existing project
/smith-index --migrate-templates

# Incremental between two refs (used by git hooks; runnable manually)
/smith-index --incremental --from HEAD~5 --to HEAD

# Bootstrap an explicit system-paths.json (heuristic alone usually suffices)
/smith-index --init-system-paths

# Resume after a SIGINT mid-run
/smith-index --resume
```

### Ad-hoc navigation

```
/smith-navigate "fix the products POST endpoint validation"
```

Returns a Must Read / Should Read / Reference Only / Systems Affected list in
under 3 seconds. Useful before manual edits, before running `/smith-bugfix`
yourself, or just to orient on an unfamiliar codebase.

### When to manually rebuild

- After a large refactor (renamed many files, moved many directories, large
  generated-code churn).
- After updating `system-paths.json` (to reassign files to new system names).
- When `/smith-index --check` reports staleness you don't want to ignore.
- Quarterly maintenance, if the project is high-churn.

For everyday work, you should never need to think about rebuilding.

---

## Configuration

### 4-tier `context-manifest.json` resolution

The per-skill config is resolved through four precedence tiers, most-specific
wins, **merged field-by-field per skill** (so a project can override one
field without restating the whole skill block):

| Tier | Location | Role |
|---|---|---|
| 1 (lowest) | Built-in fallback in `context-loader-lib.py` | Last-resort safety net. Ensures Smith always has a usable config even if all other tiers are missing/malformed. |
| 2 | `templates/context-manifest.default.json` (in `smith-repo`) | Shipped default. Copied into the project on `/smith-index` first run if no project-level config exists. |
| 3 | `~/.smith/config/context-manifest.json` | User global. Optional. Applies across all of the user's projects. |
| 4 (highest) | `.smith/index/config/context-manifest.json` | Project override. Gitignored by default; commit it if the team wants shared config. |

#### Concrete example

Suppose Tier 2 (shipped default) declares:

```jsonc
{
  "smith-build": {
    "vault": { "sessions": 3, "ledger": "top-5", "bank": "none", "agents": 2 },
    "navigator": true,
    "navigator_scope": "changed_files_context",
    "system_specs": "affected_systems_only"
  }
}
```

Your user-global (Tier 3) declares:

```jsonc
{
  "smith-build": {
    "vault": { "ledger": "all" }
  }
}
```

Your project (Tier 4) declares:

```jsonc
{
  "smith-build": {
    "navigator_scope": "task_specific"
  }
}
```

The effective config for `/smith-build` is:

```jsonc
{
  "vault": { "sessions": 3, "ledger": "all", "bank": "none", "agents": 2 },
  "navigator": true,
  "navigator_scope": "task_specific",
  "system_specs": "affected_systems_only"
}
```

The HTML comment header in the injection records which tier provided which
field, so you can verify resolution from `~/.smith/logs/hooks.log` and from
the injected markdown itself.

### `system-paths.json` overrides (heuristic-as-engine)

The path resolver runs as follows:

1. If `.smith/index/config/system-paths.json` exists, try each rule by
   **longest-prefix match** against the file's path relative to project
   root. First match wins.
2. Otherwise fall through to the heuristic:
   - `services/<name>/...` → `system-<name>`
   - `backend/<name>/...` → `system-backend-<name>`
   - `frontend/<name>/...` → `system-frontend-<name>`
   - Any other top-level source directory (not `tests/`, `docs/`,
     `node_modules/`, `.venv/`, `vendor/`, `dist/`, `build/`, `.git/`) →
     `system-<dirname>`
   - `tests/`, `docs/`, `node_modules/`, `.venv/`, `vendor/`, `dist/`,
     `build/` → `unassigned` (excluded from system-membership; still
     indexed if the extension is allowed).
   - Root-level files (no enclosing directory) → `unassigned`.

A newly-created directory containing source files is automatically assigned
to a system on first edit, without requiring any user action. `system-paths.json`
exists only as an escape hatch for projects whose layout the heuristic
doesn't guess correctly.

To bootstrap an explicit overrides file:

```sh
/smith-index --init-system-paths
```

This copies `templates/system-paths.json.example` to
`.smith/index/config/system-paths.json` with inline comments documenting the
override syntax.

### `.gitignore` policy (selective)

`templates/.gitignore-smith-additions` (merged into your `.gitignore` by
`/smith init`) ships:

```
.smith/index/files/
.smith/index/systems/
# NOT gitignored (commit these): .smith/index/manifest.md, .smith/index/config/
```

Rationale: the top-level `manifest.md` and `config/` are team-shared assets
(systems table, custom `system-paths.json`). The per-file `.meta` and
per-system manifests churn on every commit and are excluded.

### Per-project parser override

If a project ships `.smith/scripts/parse-python.py` (or `parse-js.js`),
`manifest-updater.sh` uses that instead of the global
`~/.smith/scripts/parse-X` copy. This enables projects with unusual
codegen, custom DSLs, or domain-specific filtering to fork parsing behavior
without forking smith-repo.

---

## Troubleshooting

### Manifest looks stale

```sh
/smith-index --check
```

Reports stale and missing `.meta` files. Staleness is detected via SHA-256
hash of the first 4KB of source content compared to the `hash` field in
each `.meta` (no mtime field exists in the schema). If `--check` shows
staleness you want to fix:

```sh
/smith-index
```

Full rebuild. Takes ~8s for 400 files in our reference fixture; ~38s for a
real 300-file project. Use `--system <name>` to limit to one system if only
a subset has drifted.

### Hook didn't fire

Check `~/.smith/logs/hooks.log`:

```sh
tail -40 ~/.smith/logs/hooks.log
```

Each invocation writes one structured line:

```
2026-05-21T14:23:11Z manifest-updater file=backend/src/api/v1/products.py ext=.py parser=python lines=357 system=system-15-command-center ms=292 warnings=oversized
2026-05-21T14:23:11Z context-loader skill=smith-bugfix tiers=2,4 vault_chars=4287 navigator_ms=1842 navigator_status=ok total_ms=3104
```

Common causes of "hook didn't fire":

- The hook isn't registered. Check `~/.claude/settings.json` and re-run
  `./scripts/install-hooks.sh` if needed.
- The file extension isn't in the allowlist. Only `.py .js .jsx .ts .tsx
  .css .html .sh` trigger the manifest updater. Markdown edits, bash
  scripts edits (yes, `.sh` IS covered but the parser is minimal),
  JSON/YAML edits, and edits to anything else are silent no-ops.
- The edit happened outside Claude Code (e.g. directly in VS Code or via
  ChatGPT or via `vim`). The Claude Code PostToolUse hook fires only on
  edits Claude itself performs. Use `git pull` / `git checkout` (which
  trigger the git hooks) or run `/smith-index` manually to catch up.

### Parser errors

Parser failures don't crash the hook. The parser returns partial JSON with
an `errors[]` array; `manifest-updater.sh` writes that into the `.meta`
file. Check `.meta` for the file in question:

```sh
cat .smith/index/files/path/to/your/file.py.meta
# Look for a "## Parse Errors" section
```

To debug a parser directly:

```sh
python3 ~/.smith/scripts/parse-python.py path/to/file.py
# Look at stderr; stdout will be partial JSON
node ~/.smith/scripts/parse-js.js path/to/file.js
```

### `/smith-navigate` returns nothing

Most likely cause: the manifest isn't initialized yet. The navigator emits a
"Manifest not initialized" sentinel response when `.smith/index/manifest.md`
is missing.

```sh
ls .smith/index/manifest.md
# if missing:
/smith-index
```

If the manifest exists but `/smith-navigate` returns "No matching system",
your task description didn't match any of the indexed systems. Two
possibilities:

- The relevant code lives in `unassigned` (e.g. root-level scripts or
  excluded directories). Edit `system-paths.json` to claim those paths.
- The task description is too abstract. Try referencing specific
  functions, endpoints, or file paths.

### Soft-warning keeps appearing

The "Manifest not initialized" warning is throttled per-session via
`.smith/vault/.warned-manifest-missing-<session-id>`. If you see it on
every prompt within a single session, the marker file isn't being written
— check `.smith/vault/` permissions. If you see it once per new session
indefinitely, run `/smith-index` to initialize the manifest and the
warning will stop entirely.

---

## Performance

Budgets and measured typicals (your mileage may vary based on file sizes
and project layout):

| Operation | Budget (p95) | Measured typical |
|---|---|---|
| `parse-python.py` per file | <200ms | ~80ms |
| `parse-js.js` per file | <200ms | ~135ms |
| `manifest-updater.sh` per edit | <500ms | ~102ms |
| `context-loader.sh` (no trigger) | — | ~13-20ms |
| `context-loader.sh` (trigger, vault only) | — | ~40-50ms |
| `context-loader.sh` (trigger + navigator) | <5s | ~3.7s |
| `/smith-navigate` standalone | <3s | ~1.8s |
| `/smith-index` (100 files, cold) | <60s | ~8-12s |
| `/smith-index` (300 files, cold) | <60s | ~38s |
| `/smith-index --check` (400 files) | — | ~5-10s |

The dominant cost in `context-loader.sh` is the Haiku navigator spawn
(~3s including model latency). The hard timeout is 3s on the navigator
itself plus 250ms slack; on timeout, the hook falls back to vault-only
context and continues without blocking.

The dominant cost in `/smith-index` is parser invocation. Both parsers
run as separate processes (one fork per file) to keep them robust against
bad input. Future optimization: parser daemons / shared interpreters.

---

## Known Limitations

These are deliberate v1 trade-offs, not bugs:

- **`.sh` files** are in the extension allowlist but the bash parser is
  minimal — line counts and the 300-line warning work, but symbol
  extraction is shallow. Don't expect rich function-level data for
  bash scripts.
- **Markdown-only edits don't trigger the hook.** `.md` is not in the
  allowlist (the manifest is about source code, not docs).
- **External edits don't trigger the hook.** Edits made outside Claude
  Code (VS Code, ChatGPT in a browser, `vim`, IDE refactors not invoked
  through Claude) don't fire `manifest-updater.sh`. The catch-up paths
  are `git pull` / `git checkout` (which fire the per-project git
  hooks) and manual `/smith-index` runs.
- **No filesystem watcher.** Deferred to v2. The git-hooks layer covers
  ~95% of remaining drift cases (teammate pulls, branch switches).
- **No kill switch for `manifest-updater.sh`** in v1. If sub-agent
  fan-out (20+ parallel writes in a heavy build) causes stalls, you can
  remove the hook entry from `~/.claude/settings.json` manually. Will
  revisit in v2 if real-world fan-out shows problems.
- **Windows not supported.** macOS and Linux only.
- **Tight line-range mode** for the navigator (`--tight-ranges`) is not
  in v1. Whole-file reads with primary-section annotations only. Tight
  ranges are a future opt-in once the manifest has demonstrated
  reliability.

---

## References

- Spec: [`specs/19-manifest-system/spec.md`](../specs/19-manifest-system/spec.md)
- Plan: [`specs/19-manifest-system/plan.md`](../specs/19-manifest-system/plan.md)
- Tasks: [`specs/19-manifest-system/tasks.md`](../specs/19-manifest-system/tasks.md)
- Quickstart walkthroughs: [`specs/19-manifest-system/quickstart.md`](../specs/19-manifest-system/quickstart.md)
- Contracts:
  - Parser output schema: [`specs/19-manifest-system/contracts/parser-output.schema.json`](../specs/19-manifest-system/contracts/parser-output.schema.json)
  - Navigator output format: [`specs/19-manifest-system/contracts/navigator-output.md`](../specs/19-manifest-system/contracts/navigator-output.md)
- Hook reference: [`docs/hooks.md`](hooks.md)
- Architecture: [`docs/architecture.md`](architecture.md)
- Acorn upstream: [github.com/acornjs/acorn](https://github.com/acornjs/acorn)

---

2026-05-21 — 19-manifest-system
