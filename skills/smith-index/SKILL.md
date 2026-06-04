---
name: smith-index
description: Build and maintain the project manifest under .smith/index/. Full rebuild scans every source file, runs language parsers, and writes per-file .meta, per-system manifests, and a top-level summary. Supports --check (hash-only staleness), --system (partial rebuild), --incremental (git-diff scope), --describe (per-file LLM descriptions via Task sub-agents — subscription billing), --migrate-templates (constitution.md / CLAUDE.md), --init-system-paths, and --resume.
argument-hint: [--check | --system <name> | --incremental | --describe | --migrate-templates | --init-system-paths | --resume] [--from <ref> --to <ref>] [--batch-size <n>] [--per-method-threshold <n>] [--yes] [--skip-model-probe] [--root <path>] [--system-paths <path>]
---

# Smith Index

Generate the deterministic project manifest at `.smith/index/`. The
manifest replaces soft natural-language guidance with structured, indexed
context — every Smith skill (`/smith-new`, `/smith-bugfix`, `/smith-debug`,
`/smith-explore`, …) consults it through the same retrieval path
(`/smith-navigate` + `context-loader.sh`).

**Arguments:** $ARGUMENTS

## Manifest is a map, not a fence

`.smith/index/` is a navigation aid, not a hard boundary. Skills like
`/smith-explore` still grep the whole codebase when initial signals
suggest broader impact. A stale or imprecise manifest must never block
the calling session — it should degrade gracefully to vault-only context
plus a soft warning.

## Behavior

This skill is **imperative** — running it modifies `.smith/index/` and
(with `--migrate-templates`) `constitution.md` / `CLAUDE.md`. It does NOT
modify any source file in the project. All generated state is confined to
`.smith/index/` plus optional `.bak.<timestamp>` files on template
migration.

The actual work runs in `~/.smith/scripts/smith-index/run.py` (called
via `~/.smith/scripts/smith-index/run.sh`), installed by
`scripts/install.sh` from this repo. In the smith-repo dev tree these
same files live at `scripts/smith-index/run.py` / `run.sh` — invoking
either works. The skill markdown is the entry point that parses
`$ARGUMENTS`, decides the mode, and shells out.

## Modes (flags)

### `/smith-index` — full rebuild (default)

1. Walk the project from the current directory.
2. Honor `.gitignore` (uses `git ls-files` when available; falls back to a
   manual exclusion list of `node_modules/`, `.git/`, `.venv/`, etc.).
3. For each source file (`.py`, `.js`, `.jsx`, `.ts`, `.tsx`, `.css`,
   `.html`, `.sh`):
   - Resolve the parser via `parser-lib.sh resolve_parser <ext>` (prefers
     `.smith/scripts/` over `~/.smith/scripts/` over the in-repo
     fallback).
   - Run the parser; capture JSON.
   - Compute SHA-256 of the first 4KB of source content (Q6 — hash field
     in `.meta`).
   - Render the `.meta` file at `.smith/index/files/<mirrored>/<file>.meta`.
   - Resolve the file's system via `path-resolver.py` (longest-prefix
     `system-paths.json` override → heuristic per spec Requirement 14).
4. Per system: rewrite `systems/<sys>.md` once with all files bucketed in
   that system (sorted by lines desc; truncated at 60 entries with
   `…and N more files` per data-model.md section 3). Cap ≤80 lines.
5. Rewrite top-level `manifest.md` (systems table + Stats). Cap ≤50 lines.
6. Write checkpoint state to `.smith/index/.smith-index-checkpoint.json`
   every 25 files; delete on clean exit.
7. Append one JSONL log line per stage per file to
   `~/.smith/logs/smith-index-<ISO8601>.jsonl` per Rule 4.
8. **Write the schema-version marker** at `.smith/index/.schema-version`
   containing the current schema version (read from
   `~/.smith/scripts/meta_schema_version.txt`, falls back to
   `scripts/parsers/meta_schema_version.txt` in the smith-repo dev tree
   if the global install is missing). This file lets `/smith-update`
   detect projects whose manifest was generated against an older `.meta`
   schema and offer to regenerate. The marker is overwritten on every
   full rebuild (and on `--incremental` runs that write a fresh
   manifest); silently skipped if neither source file is found.
9. Print a summary line:
   `/smith-index: N files indexed (N succeeded, N failed, N skipped) in T.Ts`.

**Performance budget:** <60s p95 for a 100-file project (acceptance
criterion from spec).

### `/smith-index --check`

Hash-only staleness scan. **No rebuild.** For each existing `.meta`,
compute SHA-256 of the first 4KB of the corresponding source file and
compare against the `Hash:` line in the `.meta`. Reports:

- Fresh count (hashes match)
- Stale list (hash mismatch — file edited externally; manifest hook
  missed it; git checkout changed content; etc.)
- Missing-source list (`.meta` exists but source was deleted/renamed)

No mtime comparison — Q6 is hash-only. Estimated ~5-10s for a 400-file
project; acceptable for a maintenance command.

### `/smith-index --system <name>`

Partial rebuild restricted to files mapped to one system. Useful after
adding a single feature: refreshes that system's `.meta` files and
`systems/<name>.md` without re-walking the entire tree. Top-level
`manifest.md` Stats section is also updated.

### `/smith-index --describe`

Generate per-file LLM descriptions in the `.meta` description layer.
Unlike all other modes, `--describe` is orchestrated BY this skill
prose itself — not by `run.py`. The skill drives a discovery →
batched-spawn → write loop, spawning one Task sub-agent per file (or
per method on dense files) that returns a MetaDescription JSON. Each
spawned Task inherits the session's Claude Code auth → **subscription
billing**, not API-key billing.

**Single backend.** v3 (PR #23) removed the v2 direct-HTTPS path. The
2am scheduler invokes `claude --print -p "/smith-queue process ..."`
which IS a Claude Code session — Task spawning works there too. No
`--llm-backend` flag, no `CLAUDE_HEADLESS` env var.

#### Step 0 — Runtime model probe

Before any bulk work, spawn ONE small Task with:

```yaml
subagent_type: general
model: claude-haiku-4-5
prompt: "Respond with exactly: MODEL_OK"
```

If the response doesn't arrive cleanly OR the trimmed response text
is not exactly `MODEL_OK` (heuristic: a Haiku model honoring the
override responds crisply; an Opus/Sonnet primary will be more
verbose), abort with:

> ERROR: Could not verify Haiku model override. Running the bulk
> loop on the session's primary model would inflate subscription
> cost ~30×. Verify your Task tool subagent type supports the model
> parameter. Pass `--skip-model-probe` to override at your own risk.

`--skip-model-probe` bypasses this check.

#### Step 1 — Discovery

```bash
python3 ~/.smith/scripts/describe_discover.py \
  --root "$ROOT" \
  ${SYSTEM:+--system "$SYSTEM"} \
  --threshold "${THRESHOLD:-5}"
```

(Use the repo-relative path `scripts/parsers/describe_discover.py`
if `~/.smith/scripts/` does not resolve.)

Parse the JSON output. Each entry has `rel_path`, `source_hash`,
`parser_output`, `qualifying_method_ids`, `existing_description`,
`cache_hit`, `system`. Drop entries with `cache_hit=true` — these
are no-ops (their `.meta` already matches the current source hash).

#### Step 2 — Resume filter

If `--resume` was passed:

```bash
python3 ~/.smith/scripts/describe_checkpoint.py load-completed \
  --log-dir ~/.smith/logs \
  --state .smith/index/.smith-index-describe-checkpoint.json
```

Filter the remaining files to exclude completed `rel_path` values.

#### Step 3 — Pre-flight estimate + confirmation gate

After filtering, count files needing description (N) and sum their
`qualifying_method_ids` counts (M). Identify files where
`len(qualifying_method_ids) > 15` (the per-method-split threshold);
each such file contributes that many Tasks instead of 1. Let T be the
total Task count.

Print to stderr:

```
/smith-index --describe pre-flight summary
─────────────────────────────────────────────
  Files needing description: N
  Qualifying methods total: M
  Per-method-split threshold: 15 (configurable via --per-method-threshold)
  Per-method-split files: K
  Estimated Tasks to spawn: T
  Estimated wall time: ~W minutes (5s/Task sequential)
```

Then ask: `Proceed? (y/N):`. Read one line from stdin. Accept
`y`/`yes` (case-insensitive). `--yes` bypasses the gate (required for
the scheduler).

#### Step 4 — Sequential Task spawning loop

Batch the remaining files in groups of 10 (default; override with
`--batch-size`). For each batch, process files **sequentially**
(one at a time — no parallel tool-use block — simpler per-Task error
handling, visible progress logging).

For each file in the batch:

1. **Per-method-split decision.** If
   `len(qualifying_method_ids) > 15` (default; override with
   `--per-method-threshold`), spawn one Task PER METHOD. Otherwise
   one Task for the whole file.

2. **Build the prompt body.** Assemble via the helper (single source
   of truth for prompt template):
   ```bash
   PROMPT=$(python3 ~/.smith/scripts/describe_write.py build-prompt \
     --rel-path "$REL" --root "$ROOT" \
     --method-ids "<comma-separated-ids>" --module)
   ```

3. **Spawn the Task.**
   ```yaml
   subagent_type: general
   model: claude-haiku-4-5
   prompt: |
     <PROMPT body from step 2>
   ```

4. **Retry on failure (exponential backoff).** If the Task call
   fails or returns malformed JSON or `status="error"`, retry with
   backoff 5s → 10s → 20s. Max 3 attempts. After 3, log a `failed`
   JSONL record and move to the next file. Do NOT abort the run.

5. **STUB MODE.** If `SMITH_TASK_STUB=1` is set in the env, skip
   the Task spawn entirely. Pipe the canned fixture into the writer:
   ```bash
   python3 ~/.smith/scripts/describe_write.py apply --from-stub \
     tests/fixtures/task-stub-responses.json \
     --rel-path "$REL" --root "$ROOT" --hash "$HASH"
   ```
   The stub fails loud (exit 4) if any qualifying method id is not
   in the fixture. Tests set `SMITH_TASK_STUB=1`; users never do.

6. **Apply the result.** Pipe the Task's JSON output into the writer:
   ```bash
   echo "$TASK_OUTPUT" | \
     python3 ~/.smith/scripts/describe_write.py apply \
       --rel-path "$REL" --root "$ROOT" --hash "$HASH"
   ```

7. **Append a checkpoint record.** One JSONL line per file:
   ```bash
   python3 ~/.smith/scripts/describe_checkpoint.py append \
     --log "$LOG_PATH" \
     --record "$(printf '{"item_id":"%s","stage":"describe",
                          "status":"ok","backend":"task",
                          "method_count":%d,"module_chars":%d,
                          "batch_index":%d,"retry_count":%d}' \
                "$REL" "$N" "$M" "$BATCH_IDX" "$RETRIES")"
   ```

   Then persist checkpoint state:
   ```bash
   python3 ~/.smith/scripts/describe_checkpoint.py save \
     --path .smith/index/.smith-index-describe-checkpoint.json \
     --processed "$REL"
   ```

#### Step 5 — Propagate descriptions to manifest tables

`/smith-index` (full rebuild) populates per-file rows in
`systems/<id>.md` and the top-level `manifest.md` during its source
walk — well before `--describe` writes the description layer into each
`.meta`. The manifest tables therefore reflect the pre-describe state.

After all batches complete, refresh the manifest tables from the
just-updated `.meta` files:

```bash
python3 ~/.smith/scripts/smith-index/run.py --rebuild-manifests \
  --root "$ROOT"
```

(Falls back to `scripts/smith-index/run.py` in repo-dev layouts.)

This mode re-reads `.smith/index/files/*.meta`, salvages the module
descriptions from each file's description layer, and re-renders
`manifest.md` + every `systems/<id>.md`. It does NOT re-parse source
or touch `.meta` files. Skipped if `--describe` aborted before any
descriptions were written.

#### Step 6 — Summary

After all batches complete (or on abort):

```bash
python3 ~/.smith/scripts/describe_checkpoint.py summary \
  --log "$LOG_PATH" --start-iso "$START_ISO"
```

Format: `/smith-index --describe: N files described
(succeeded=S failed=F skipped=K) in T.Ts`.

On clean completion, remove the checkpoint state file. On Ctrl-C or
fatal error, leave it in place so `--resume` works.

#### Failure handling

- **Per-Task failure.** Exponential backoff retry (5s → 10s → 20s,
  max 3). After 3, log `failed`, continue. No run-level abort.
- **Helper script failure (non-zero exit).** Surface stderr; record
  a `failed` JSONL entry; continue.
- **Model probe failure.** Hard abort before any bulk work, with the
  clear-error message above. `--skip-model-probe` overrides.
- **Missing helper at install location.** If
  `~/.smith/scripts/describe_discover.py` is not found, fall through
  to the repo-relative path `scripts/parsers/describe_discover.py`.
  If neither resolves, exit 78 (`EX_CONFIG`) with: "Smith helpers not
  installed. Run `npx skills add ATTCKDigital/smith` to install."

### `/smith-index --migrate-templates`

Non-destructive template migration for existing projects (Q2). For each
of `constitution.md` (or `.specify/memory/constitution.md`) and
`CLAUDE.md`:

1. Detect missing top-level headers from the template additions:
   - `## File Size Policy`
   - `## Project Manifest`
   - `## Smith Context System`
   - `## File Size Awareness`
2. If any are missing, write a `.bak.<ISO8601>` backup of the original.
3. Append the missing sections (sourced from
   `templates/constitution-additions.md` and
   `templates/claude-md-additions.md`).
4. **Backfill the `base_branch:` frontmatter field on the constitution**
   (idempotent). If `.specify/memory/constitution.md` (or `constitution.md`)
   lacks a `base_branch:` key in its YAML frontmatter, add `base_branch: main`
   (the backwards-compatible default — older constitutions implicitly meant
   `main`). Handle both shapes:
   - **Frontmatter block present** (file starts with a `---` fence): insert
     `base_branch: main` as a new line inside the first `---`/`---` block,
     after the opening fence.
   - **No frontmatter block** (file starts with `# ... Constitution`): prepend
     a new block:
     ```markdown
     ---
     base_branch: main
     ---

     ```
   If a `base_branch:` key is already present (any value, including a
   user-customized one), do NOTHING — never overwrite an existing value. This
   step shares the backup taken in step 2 (take one if not already taken).
5. Skip silently if all sections AND the `base_branch:` field are already
   present (idempotent).

Never overwrites existing user content. Never modifies sections that are
already there, even if the template's wording has changed since the
section was first added.

### `/smith-index --incremental`

Re-parse only files changed in `git diff <from>..<to>`. Designed for
the `post-merge` and `post-checkout` git hooks (per Design Decision 8).

- Default refs: `ORIG_HEAD..HEAD`.
- Override with `--from <ref> --to <ref>`.
- Filters changed files to allowed source extensions; runs the same
  parse + .meta + per-system + top-level update pipeline as a single
  PostToolUse hit.
- After re-parsing the diffed subset, rebuilds the full per-system and
  top-level manifests from the existing `.meta` files (so unchanged
  systems still appear correctly in the regenerated tables).
- Exits 0 silently if `git` is unavailable or the project has no `.git/`.

Typical runtime: <2s for normal pulls (5-20 file changes).

### `/smith-index --init-system-paths`

Optional bootstrap helper. Writes a stub
`.smith/index/config/system-paths.json` derived from the project's
top-level directories. Per Q7, `system-paths.json` is OPTIONAL — the
heuristic engine handles missing config — so this flag exists only for
users who want explicit overrides as a starting point. Does NOT
overwrite an existing file.

### `/smith-index --resume`

Continue an interrupted run. Reads the latest
`smith-index-<ISO>.jsonl` log under `~/.smith/logs/`, computes the set
of files that completed all stages through `system-update`, and skips
them on the resumed run. The checkpoint at
`.smith/index/.smith-index-checkpoint.json` is consulted to recover the
in-progress system context.

Per Rule 4: `--resume` is a no-op if no checkpoint or recent JSONL log
exists; it falls back to a fresh run with a warning.

## Auto-invocation

`/smith init` calls `/smith-index` as its final setup step (per spec
Requirement 5). On a fresh project this:

1. Creates `.smith/index/` and subdirectories.
2. Copies `templates/context-manifest.default.json` into
   `.smith/index/config/context-manifest.json` if absent.
3. Does NOT copy `system-paths.json` (per Q7 — only on
   `--init-system-paths`).
4. Runs the full rebuild.

## Outputs

| Path | Capped at | Purpose |
|------|-----------|---------|
| `.smith/index/manifest.md` | 50 lines | Top-level overview |
| `.smith/index/systems/<sys>.md` | 80 lines each | Per-system file lists |
| `.smith/index/files/<mirror>/<file>.meta` | unlimited | Per-file detail |
| `.smith/index/.smith-index-checkpoint.json` | — | Resume state (removed on clean exit) |
| `~/.smith/logs/smith-index-<ISO>.jsonl` | — | Per-stage Rule-4 log |

## Configuration files (NOT regenerated)

| Path | Origin | Notes |
|------|--------|-------|
| `.smith/index/config/context-manifest.json` | Copied from `templates/context-manifest.default.json` on first init | Tier 4 in the 4-tier resolution chain |
| `.smith/index/config/system-paths.json` | Optional; user-authored or `--init-system-paths` stub | If absent, path-resolver heuristic runs |

## Logging

- One JSONL line per file per stage (`parse`, `meta`, `system-update`,
  `top-update`) to `~/.smith/logs/smith-index-<ISO>.jsonl`.
- Summary line to stdout on completion (NOT to JSONL).

## Error handling

- Per-file failures are counted, never abort the run.
- Parser timeouts emit a partial `.meta` with `## Parse Errors` populated.
- Missing optional config (`system-paths.json`) falls back to the
  heuristic resolver.
- Missing `git` short-circuits `--incremental` to a no-op.

## Examples

```
/smith-index                          # full rebuild
/smith-index --check                  # staleness scan, no rebuild
/smith-index --system system-backend  # rebuild one system
/smith-index --incremental            # re-parse `git diff ORIG_HEAD..HEAD`
/smith-index --incremental --from HEAD~1 --to HEAD
/smith-index --describe               # generate LLM descriptions (Task-spawned)
/smith-index --describe --yes         # skip the pre-flight confirm gate
/smith-index --describe --system foo  # describe one system only
/smith-index --describe --resume      # resume an interrupted describe run
/smith-index --migrate-templates      # patch constitution.md / CLAUDE.md
/smith-index --init-system-paths      # write stub system-paths.json
/smith-index --resume                 # continue interrupted run
```

## Where this skill is invoked from

- **`/smith init`** — calls `/smith-index` as the final setup step.
- **`post-merge` git hook** — calls `/smith-index --incremental`.
- **`post-checkout` git hook** — calls `/smith-index --incremental
  --from $prev_head --to $new_head`.
- **`context-loader.sh`** — does NOT auto-invoke; surfaces a soft
  warning when `.smith/index/manifest.md` is absent.
- **User, manually** — for any of the above modes plus `--check` and
  `--system`.

## Implementation reference

- Entry (all modes except `--describe`): `scripts/smith-index/run.sh` →
  `scripts/smith-index/run.py`
- Entry (`--describe` only): this skill's prose drives the loop directly,
  using the helpers below.
- Parsers: `scripts/parsers/parse-python.py`, `scripts/parsers/parse-js.js`
- Path resolver: `scripts/parsers/path-resolver.py`
- Parser-lib helper: `scripts/parsers/parser-lib.sh`
- v3 description helpers:
  `scripts/parsers/describe_discover.py`,
  `scripts/parsers/describe_write.py`,
  `scripts/parsers/describe_checkpoint.py`,
  `scripts/parsers/index_common.py` (shared utilities),
  `scripts/parsers/meta_describe.py` (structural; LLM-call-free).
- Templates: `templates/constitution-additions.md`,
  `templates/claude-md-additions.md`
