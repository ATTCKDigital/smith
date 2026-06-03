---
feature: 23-task-llm-backend
branch: 23-task-llm-backend
created: 2026-06-03
status: planning
builds_on: 19-manifest-system (PR #19) + 20-manifest-fixes (PR #21) + install-path-fallback (PR #22)
---

# Implementation Plan — Task-based LLM Backend for the Description Layer

## Technical Context

- **Language / runtime.** Python 3 stdlib only for all new helpers. Node
  (vendored `acorn`) is invoked transitively by `parse-js.js` but no new
  Node dependencies are introduced. No `anthropic` SDK — the headless
  fallback continues to use `urllib.request` (parity with v2 at
  `scripts/parsers/meta_describe.py:36-37`).
- **LLM call mechanism.**
  - **cli backend (default).** The orchestrating LLM in the user's Claude
    Code session spawns one Task tool sub-agent per file
    (`subagent_type: "general"`, model `claude-haiku-4-5`). Task calls
    inherit session auth → subscription billing.
  - **api backend (headless fallback).** Direct HTTPS POST to
    `https://api.anthropic.com/v1/messages` via `urllib.request`, using
    `ANTHROPIC_API_KEY` from env. This is a wholesale port of the v2
    code at `scripts/parsers/meta_describe.py:290-345`
    (`_default_haiku_call`).
- **Model.** `claude-haiku-4-5` (matches PR #21
  `meta_describe.py:48` constant `DEFAULT_MODEL`). Configurable via the
  existing `--model` CLI flag.
- **Concurrency.** Trust the Task tool runtime's built-in cap
  (`min(16, cpu - 2)`); the skill prose spawns parallel Tasks per batch
  inside a single tool-use block. No second throttle layer per Decision 5
  in spec.md.
- **Batch size.** Default 10 (per spec §A2.4). v2 currently defaults to
  20 for the operator-approval batch and 10 for the LLM sub-batch
  (`run.py:1212-1213`). v3 collapses these into a single batch knob of
  10 — see Plan Decision 1 below.
- **Test harness.** Skill prose detects `SMITH_TASK_STUB=1`. In stub
  mode, instead of spawning a Task, the prose invokes
  `python3 scripts/parsers/describe_write.py --from-stub <fixture-path>
  --rel-path <p>` which reads a canned MetaDescription JSON keyed by
  `rel_path` and writes the `.meta` the same way as the live path.
- **Threshold.** Unchanged from v2 (`DEFAULT_THRESHOLD_LINES = 5` at
  `meta_describe.py:47`).
- **Soft caps.** Unchanged from v2 (`MODULE_DESC_SOFT_CAP = 120`,
  `METHOD_DESC_SOFT_CAP = 200`).

## Constitution Check

- **Rule 1 (Questions ≠ Actions).** Not applicable — this is an
  implementation plan, not a user question.
- **Rule 2 (SpecKit triggers + skill compliance).** N/A at plan stage;
  but plan respects the sub-step order under `/smith-plan`.
- **Rule 3 (Question file before complex changes).** The architectural
  inversion is materially documented in spec.md §Design Decisions (six
  decisions) and §Open Questions (seven). No further pre-implementation
  question file is required — the spec already encodes the decisions
  and surfaces the residual ambiguity.
- **Rule 4 (Checkpoint/Resume).** Preserved.
  `scripts/parsers/describe_checkpoint.py` (NEW) writes:
  - JSONL log at `~/.smith/logs/smith-index-describe-<ISO>.jsonl` (one
    record per processed file, shape matches v2 at
    `run.py:1291-1300`).
  - Checkpoint state at
    `.smith/index/.smith-index-describe-checkpoint.json` after every
    batch (shape matches v2 `processed_files` list at
    `run.py:1268-1271`).
  - Summary line on exit:
    `/smith-index --describe: N files described (succeeded=S failed=F
    skipped=K) in T.Ts` (matches v2 at `run.py:1433`).
  Resume reads the most recent JSONL + the checkpoint and unions the
  completed `rel_path` set.
- **Rule 5 (Session logging).** Handled automatically by the vault
  hooks — no manual session-log writes.
- **Rule 6 (General preferences).** `python3` everywhere; helper CLIs
  use `#!/usr/bin/env python3`.
- **Rule 7 (Directory setup).** No new top-level dirs in the project.
  `.smith/index/logs/` (already created by PR #21) is reused.

## Architecture Overview

```
v2 (current, PR #21):
  User → /smith-index --describe → run.py mode_describe() [Python orchestrator]
            ├─ walk_source_files → discovered: list[Path]
            ├─ batching loop (default batch_size=20, llm_batch_size=10)
            ├─ for each file: _describe_one_file()
            │     ├─ parser invocation
            │     ├─ sha256_first_4kb
            │     ├─ parse_meta_descriptions (existing layer)
            │     ├─ hash-cache check
            │     ├─ meta_describe.describe_file()
            │     │     └─ _default_haiku_call()  ← HTTPS to api.anthropic.com
            │     │                                  with ANTHROPIC_API_KEY
            │     └─ render_meta + atomic write
            ├─ Rule-4 JSONL log + checkpoint
            └─ summary line

v3 (target, cli backend = default):
  User → /smith-index --describe → SKILL.md prose [LLM orchestrator IN session]
            ├─ Detect backend:
            │     CLAUDE_HEADLESS=1 OR --llm-backend api → shell out to
            │     describe_headless.py (and return its exit code)
            ├─ python3 describe_discover.py → JSON[]:
            │     [{rel_path, source_hash, parsed, existing_desc, cache_hit}, …]
            ├─ Apply --resume skip set via describe_checkpoint.py load
            ├─ Loop batches (default 10 files / batch):
            │     ├─ Spawn N parallel Task tool calls in ONE tool-use block
            │     │     subagent_type: "general"
            │     │     model: "claude-haiku-4-5"
            │     │     prompt: per-file (see Task prompt template below)
            │     ├─ Collect each Task's JSON output (MetaDescription)
            │     ├─ For each result: python3 describe_write.py --rel-path <p>
            │     │     splices into .meta atomically
            │     ├─ python3 describe_checkpoint.py append  (JSONL + state)
            │     └─ continue / retry / abort per failure policy
            └─ Summary line (same shape as v2)

v3 headless fallback (api backend):
  cron / scheduler → claude -p "/smith-index --describe"
        with CLAUDE_HEADLESS=1 in env
            → SKILL.md prose detects headless
            → python3 describe_headless.py [--root … --resume]
                  ├─ Same discover → batch → write → log loop as v2
                  ├─ Direct HTTPS via _default_haiku_call() (ported verbatim)
                  └─ Same .meta output bytes as v2
```

## File Structure

All paths absolute under `/Users/dennisplucinik/Projects/smith-repo`.

### NEW

| Path | Approx LOC | Purpose |
|---|---|---|
| `scripts/parsers/describe_discover.py` | ~180 | File discovery, hash, existing-meta scan, cache-hit determination. Stdout JSON. Importable. |
| `scripts/parsers/describe_write.py` | ~220 | Splice MetaDescription into `.meta` atomically. Supports `--update-touched` mode and `--from-stub` (test) mode. |
| `scripts/parsers/describe_checkpoint.py` | ~120 | JSONL log writer + checkpoint state reader/writer + `--resume` loader. |
| `scripts/parsers/describe_headless.py` | ~280 | Wholesale port of v2's mode_describe + `_describe_one_file` + `_default_haiku_call`. Self-contained CLI. Includes `update-touched` subcommand. |
| `tests/parsers/test_task_backend_stub.py` | ~210 | Task-stub fixture + bulk/incremental/purpose_shifted coverage. |
| `tests/parsers/test_describe_headless.py` | ~170 | Headless regression vs v2 golden output. |
| `tests/parsers/test_hash_cache_skip.py` | ~110 | Re-run-on-unchanged-source → zero `.meta` writes. |
| `tests/fixtures/task-stub-responses.json` | ~80 | Canned MetaDescription JSON keyed by `rel_path`. |
| `tests/fixtures/headless-fixture-project/` | n/a (data) | Small parsable Python file + expected `.meta` golden. |
| `specs/23-task-llm-backend/contracts/task-llm-output.schema.json` | ~70 | JSON Schema for the Task sub-agent's return envelope. |

### MODIFY

| Path | Net LOC Delta | Change |
|---|---|---|
| `scripts/parsers/meta_describe.py` | −340 / +0 (~426 → ~280 net after strip + drop CLI; structural keepers below) | STRIP `_default_haiku_call` (`:290-345`), `HaikuUnavailable` (`:286-287`), `describe_file` (`:452-479`), `update_touched` (`:482-521`), `_describe` private (`:524-622`), `_safe_json_object` (`:625-656`), `_cli_update_touched` (`:666-731`), `_build_argparser` + `main` + `__main__` block (`:734-766`). KEEP `MethodDescription`, `MetaDescription`, soft-cap constants, `_iso_now`, `_sha256`, `parse_meta_descriptions`, `render_description_block`, `_qualifying_methods`, `_summarize_for_module_prompt`, `_build_method_prompt`, `_truncate`, `_MODULE_SYSTEM`, `_METHOD_SYSTEM`. Make `_summarize_for_module_prompt`, `_build_method_prompt`, `_truncate`, and the system-prompt constants part of the public API (drop the leading underscore where a new helper imports them) — these are the prompt-template builders the new helpers need. |
| `scripts/smith-index/run.py` | −370 / +0 | DELETE `_read_meta_text` (`:1106-1110`), `_extract_hash_from_meta` (`:1113-1121`), `_describe_one_file` (`:1124-1206`), `mode_describe` (`:1209-1450`+) and all argparse pieces for `--describe`, `--batch-size`, `--llm-batch-size`, `--threshold`, `--model`, `--no-interactive` (`:1755-1788`) and dispatcher (`:1804-1814`). KEEP the `_meta_describe` import block (`:126-153`) and the `:861` callsite that uses `parse_meta_descriptions` / `render_description_block` for non-describe modes. |
| `skills/smith-index/SKILL.md` | +180 / −0 | ADD a new `### /smith-index --describe` section (no such section exists today — flag is currently only parsed in run.py). Section contains the full v3 orchestration prose (see Component Design §3 below). |
| `skills/smith-new/SKILL.md` | +35 / −7 | REPLACE the `python3 ~/.smith/scripts/meta_describe.py update-touched …` shell-out at line 447 with inline Task spawning prose + a fallback to `describe_headless.py update-touched`. |
| `skills/smith-bugfix/SKILL.md` | +35 / −12 | Same replacement at line 208. |
| `skills/smith-debug/SKILL.md` | +35 / −6 | Same replacement at line 290. |
| `docs/manifest-system.md` | +60 / −5 | Add a "Backend selection: cli vs api" subsection near the existing v2 `.meta` description-layer section. |
| `CHANGELOG.md` | +25 | New v3.0.0 entry. |

### KEEP (no change)

- The `.meta` on-disk layout (`Description:`, `Described-Against-Hash:`,
  `Described-At:` + per-method `Id:` / `Description:` under
  `## Functions` / `## Classes`).
- `scripts/parsers/contracts/meta-description-layer.schema.json` (the
  serialized-form contract from PR #21).
- `scripts/parsers/parse-python.py`, `parse-js.js`, `passive-parser.py`
  (parsers are untouched).
- `scripts/smith-index/run.sh` — still launches `run.py`. The script
  did not encode `--describe` separately; it forwards `$@` to Python.
- `hooks/manifest-updater-lib.py` (READ-ONLY consumer of
  `parse_meta_descriptions`).

## Component Design

### 1. `describe_discover.py`

**Purpose.** Replace the discovery + cache-hit + existing-layer-parse
half of `_describe_one_file` (`run.py:1138-1183`).

**CLI.**

```
python3 describe_discover.py
  --root <project-root>           # default: cwd
  [--system <name>]               # filter to one system
  [--threshold <n>]               # passed through, default 5
  [--rel-path <p>]                # single-file mode (used by workflows)
  [--touched-only]                # in single-file mode, also emit touched-id set
  [--touched-ids <comma-hex>]     # workflow input
  [--purpose-shifted true|false]
```

**Stdout shape.** JSON array, one entry per file (or one entry in
single-file mode):

```json
[
  {
    "rel_path": "scripts/parsers/meta_describe.py",
    "source_hash": "<sha256-first-4kb>",
    "parser_output": { /* parser-output-v2.schema.json shape */ },
    "qualifying_method_ids": ["abcdef0123456789", ...],
    "existing_description": {
      "module_description": "…" | null,
      "method_descriptions": {"abcd…": "…", …},
      "described_against_hash": "…" | null,
      "described_at": "…" | null
    } | null,
    "cache_hit": false,
    "system": "system-manifest" | null
  },
  ...
]
```

**Internals.** Imports `walk_source_files`, `resolve_parser`,
`run_parser`, `passive_parse`, `sha256_first_4kb` from
`scripts.smith_index.run` (or moves these to a small shared module —
see Plan Decision 3). Imports `parse_meta_descriptions`,
`_qualifying_methods` (made public) from `meta_describe`.

**Error handling.** On parser failure for one file, emit the entry with
`parser_output: null, cache_hit: false` and a `discovery_error` string
field. The orchestrator decides to skip; the helper never aborts the
whole walk.

**Performance budget.** < 30s for a 1,200-file repo (matches v2
discovery cost — parser invocations dominate).

### 2. `describe_write.py`

**Purpose.** Replace the splice/render/write tail of `_describe_one_file`
(`run.py:1198-1206`) AND `_cli_update_touched`
(`meta_describe.py:666-731`).

**CLI modes.**

```
# Bulk mode (one file, MetaDescription on stdin):
python3 describe_write.py
  --rel-path <p>
  --root <project-root>
  --hash <sha256-first-4kb>
  [--input <json-file>]            # else read stdin

# Incremental mode (workflow incremental path):
python3 describe_write.py update-touched
  --rel-path <p>
  --root <project-root>
  --purpose-shifted true|false
  [--input <json-file>]

# Test stub mode:
python3 describe_write.py --from-stub <fixture-path>
  --rel-path <p>
  --root <project-root>
  --hash <sha256-first-4kb>
```

**Behavior.**

- Reads the existing `.meta` via `parse_meta_descriptions`.
- Merges incoming MetaDescription:
  - Bulk: overwrite module + all method descriptions for the file.
  - update-touched: replace only the supplied method ids; regenerate
    module iff `purpose_shifted=true`; drop stale ids absent from the
    current parser output (mirrors `_describe` at
    `meta_describe.py:584-588`).
- Applies `_truncate` for soft/hard caps (same numbers as v2).
- Renders via `render_description_block` → splices into the full
  `.meta` via the same `render_meta` callable used by the index
  (imported from `scripts.smith_index.run`).
- Atomic write: tempfile in the same dir + `os.rename`.
- Stub mode: reads the canned response from the fixture, runs the
  same write path. The stub fixture maps `rel_path` → MetaDescription
  JSON (data-model.md §6).

**Error handling.** Exit codes:
- 0 success
- 2 input validation error (bad JSON, missing rel-path, etc.)
- 3 disk write error (write to a `.meta.tmp` failed)
- 4 stub fixture missing key (test-only)

### 3. `describe_checkpoint.py`

**Purpose.** Centralise Rule-4 plumbing for both backends (cli and api).

**CLI.**

```
python3 describe_checkpoint.py append --log <jsonl-path> --record '{…}'
python3 describe_checkpoint.py save --path <state-path> --processed <rel>
python3 describe_checkpoint.py load --path <state-path>        # to stdout
python3 describe_checkpoint.py load-completed
  --log-dir <dir> --state <path>     # for --resume
python3 describe_checkpoint.py summary
  --log <jsonl> --start-iso <iso>    # prints the human summary
```

**Record shape (one JSONL line per processed file).**

```json
{
  "timestamp": "2026-06-03T14:30:00.123Z",
  "item_id": "scripts/parsers/meta_describe.py",
  "stage": "describe" | "skipped" | "failed",
  "status": "ok" | "skipped" | "failed",
  "error": null | "string",
  "method_count": 7,
  "module_chars": 118,
  "batch_index": 12,
  "backend": "task" | "api" | "stub"
}
```

The `backend` field is a v3 addition (data-model.md §4). v2 records did
not have it; readers ignore unknown keys.

**Checkpoint state file.**

```json
{
  "version": 2,
  "processed_files": ["a.py", "b.js", ...],
  "started_at": "2026-06-03T14:00:00Z",
  "last_batch_index": 12,
  "backend": "task"
}
```

**Performance.** Append-only writes; flush after every record (matches
v2 line-buffered `open(..., buffering=1)` at `run.py:1278`).

### 4. `describe_headless.py`

**Purpose.** A self-contained CLI that runs the v2 path. The skill
prose shells out to this script in the two cases:
(a) `CLAUDE_HEADLESS=1` in env, OR
(b) `--llm-backend api` flag was passed.

**CLI.** Mirrors what v2's `mode_describe` accepted:

```
python3 describe_headless.py
  [--root <p>]
  [--batch-size <n>]              # default 10 — see Plan Decision 1
  [--threshold <n>]
  [--model <id>]
  [--system <name>]
  [--resume]
  [--no-interactive]

python3 describe_headless.py update-touched
  --rel-path <p>
  [--root <p>]
  --touched-ids <comma-hex>
  --purpose-shifted true|false
  [--threshold <n>] [--model <id>]
```

**Internals.**

- Imports the structural keepers from `meta_describe`
  (MetaDescription, render_description_block, _qualifying_methods,
  prompt builders, soft-cap constants).
- Carries its own `_default_haiku_call` (copied verbatim from v2
  `meta_describe.py:290-345`) so the headless path remains
  byte-equivalent to v2.
- Uses `describe_discover.py` (as a module import) for the file walk.
- Uses `describe_write.py` (as a module import) for splicing.
- Uses `describe_checkpoint.py` (as a module import) for JSONL +
  checkpoint.
- Reads `ANTHROPIC_API_KEY` from env; raises a clear error when missing.
- Respects `SMITH_ANTHROPIC_API_URL` env override for test fixtures
  (parity with v2 at `meta_describe.py:309`).

**Performance budget.** Same as v2: 5–10s per Haiku call; full repo
runtime dominated by network and Haiku latency. The v3 helper layout
adds zero measurable overhead over the v2 in-Python-process path.

### 5. `skills/smith-index/SKILL.md` — `/smith-index --describe` section

**This is the core deliverable.** The prose IS the spec for v3
behavior. Below is the exact prose template (paste-in form). It
follows the existing skill's voice and section conventions
(see `skills/smith-index/SKILL.md:39-67` for the `--full rebuild`
section as a style reference).

```markdown
### `/smith-index --describe`

Generate per-file LLM descriptions in the `.meta` description layer
(spec PR #21). v3 inverts the orchestration: this skill prose drives
the loop, spawning a Task tool sub-agent per file. Each Task inherits
the user's Claude Code session auth → subscription billing.

**Default backend: `cli` (Task tool). Fallback: `api` (direct HTTPS).**

#### Pre-flight backend detection

Before any work:

1. If the environment variable `CLAUDE_HEADLESS=1` is set, OR if
   `--llm-backend api` was passed in `$ARGUMENTS`, shell out to the
   headless fallback and return its exit code:
   ```bash
   python3 ~/.smith/scripts/describe_headless.py "$@"
   ```
   (Use repo-relative path `scripts/parsers/describe_headless.py`
   if `~/.smith/scripts/` does not resolve — same fallback the
   parser-lib uses.)
2. Otherwise proceed with the cli (Task-spawning) path below.

#### Step 1 — Discovery

Invoke the discovery helper to enumerate files needing description:

```bash
python3 scripts/parsers/describe_discover.py \
  --root "$ROOT" \
  ${SYSTEM:+--system "$SYSTEM"} \
  --threshold "${THRESHOLD:-5}"
```

Parse the JSON output. The result is a list of file entries; each
carries `rel_path`, `source_hash`, `parser_output`,
`qualifying_method_ids`, `existing_description`, `cache_hit`.

Drop entries with `cache_hit=true`. These are no-ops — their `.meta`
description layer already matches the current source hash.

#### Step 2 — Resume filter

If `--resume` was passed, load the completed-file set:

```bash
python3 scripts/parsers/describe_checkpoint.py load-completed \
  --log-dir .smith/index/logs \
  --state .smith/index/.smith-index-describe-checkpoint.json
```

Filter the remaining files to exclude `rel_path` values already in the
completed set.

#### Step 3 — Operator approval gate (interactive only)

If `stdin` is a tty AND no `--no-interactive`, group the filtered files
into approval batches of 20 (matches v2 operator-approval cadence at
`run.py:1212`). For each batch, prompt:

```
Batch <n>: <count> files (of <total> total)
  Approve batch? [Y/n/q/list]:
```

`q` aborts; `list` prints all paths then re-prompts; `n` logs each
file as `skipped` with `error="operator-reject"` and continues.

#### Step 4 — Task spawning loop

For each approved batch, sub-divide into LLM batches of 10 (default,
override via `--batch-size`). For each LLM batch:

1. **Spawn N parallel Task tool calls in a single tool-use block.**
   One Task per file, all in the same tool-use entry — this triggers
   the runtime's parallel sub-agent fan-out (`min(16, cpu-2)` cap).
   Each Task uses:
   ```yaml
   subagent_type: general
   model: claude-haiku-4-5
   prompt: |
     You are generating descriptions for the .meta description layer.
     Return ONLY a JSON object matching this schema (no preamble, no
     fences):

     {
       "status": "ok" | "error",
       "module_description": "<≤200 chars, single line>",
       "method_descriptions": [
         {"method_id": "<16hex>", "description": "<≤400 chars>"},
         ...
       ],
       "errors": []
     }

     File: <rel_path>
     Language: <parser_output.language>
     Lines: <parser_output.lines>

     <PARSER SUMMARY: imports / top-level functions / classes per
      _summarize_for_module_prompt output>

     Methods to describe (only ids listed here):
     <per-method block per _build_method_prompt output, scoped to
      qualifying_method_ids>

     Full source (for context):
     ```
     <file source>
     ```

     Soft caps: module ≤120 chars, method ≤200 chars. Concise,
     informational, no marketing voice.
   ```

   Build the prompt body via `python3 scripts/parsers/describe_write.py
   build-prompt --rel-path <p> --root "$ROOT"` (the helper exposes the
   `_summarize_for_module_prompt` + `_build_method_prompt` outputs via
   a small subcommand so the prose doesn't have to duplicate the
   prompt assembly).

2. **STUB MODE:** if `SMITH_TASK_STUB=1` is set, instead of spawning
   Task calls, invoke:
   ```bash
   for rel in <batch rel_paths>; do
     python3 scripts/parsers/describe_write.py --from-stub \
       tests/fixtures/task-stub-responses.json \
       --rel-path "$rel" --root "$ROOT" --hash "<source_hash>"
   done
   ```
   The stub bypasses Task and writes from the canned fixture. Tests
   set this env var; users never do.

3. **Collect each Task's JSON output.** Each Task returns a single
   message whose text payload is the JSON object above. Parse it.
   On parse failure or `status="error"`, record a `failed` JSONL
   entry and continue with the rest of the batch.

4. **Write each result.** For each Task that returned `status="ok"`,
   pipe its JSON into the writer:
   ```bash
   echo '<task-output-json>' | \
     python3 scripts/parsers/describe_write.py \
       --rel-path "<rel_path>" --root "$ROOT" \
       --hash "<source_hash>"
   ```
   The writer translates the Task envelope (`task-llm-output.schema.json`)
   into the on-disk form, applies soft-cap truncation, and atomically
   replaces the `.meta`.

5. **Append checkpoint records.** For each file in the batch:
   ```bash
   python3 scripts/parsers/describe_checkpoint.py append \
     --log "$LOG_PATH" \
     --record '{"item_id":"<rel>","status":"ok",
                "stage":"describe","backend":"task",
                "method_count":<n>,"module_chars":<m>,
                "batch_index":<i>,"timestamp":"<iso>"}'
   ```
   After all writes in the batch succeed, persist checkpoint state:
   ```bash
   python3 scripts/parsers/describe_checkpoint.py save \
     --path .smith/index/.smith-index-describe-checkpoint.json \
     --processed "<rel_path>"
   ```
   (One save call per processed file.)

#### Step 5 — Summary

After all batches complete (or on abort), emit the Rule-4 summary:

```bash
python3 scripts/parsers/describe_checkpoint.py summary \
  --log "$LOG_PATH" --start-iso "$START_ISO"
```

Format: `/smith-index --describe: N files described
(succeeded=S failed=F skipped=K) in T.Ts`.

On clean completion, remove the checkpoint state file. On Ctrl-C or
fatal error, leave it in place so `--resume` works.

#### Failure handling

- **Per-file Task failure.** Log a `failed` record with the Task's
  error text. Continue the batch. The file is eligible for a re-run
  on the next `--describe` invocation (no cache hit because the
  `.meta` was not updated).
- **Per-batch Task tool-block failure.** If the entire tool-use block
  errors (e.g. runtime rate-limit), record all files in that batch as
  `failed` with the shared error. Continue with the next batch.
- **Helper script failure (non-zero exit).** Surface the stderr,
  record a `failed` entry, continue.
- **No-key headless case.** If the headless fallback path is taken
  but `ANTHROPIC_API_KEY` is unset, `describe_headless.py` exits 78
  (`EX_CONFIG`) with a clear message — the user must either set the
  key or run interactively.
```

### 6. Workflow skills update (smith-new, smith-bugfix, smith-debug)

**Current shell-out (smith-bugfix:208 as the canonical example).**

```bash
python3 ~/.smith/scripts/meta_describe.py update-touched \
  --rel-path <project-relative-path> \
  --touched-ids <comma-separated-16hex-ids> \
  --purpose-shifted <true|false>
```

**v3 replacement prose (paste-in form):**

```markdown
3. **Update the `.meta` description layer.**

   **Headless fast path.** If `CLAUDE_HEADLESS=1` is set in the
   environment, shell out to the headless wrapper and skip the inline
   Task path:
   ```bash
   python3 ~/.smith/scripts/describe_headless.py update-touched \
     --rel-path <project-relative-path> \
     --touched-ids <comma-separated-16hex-ids> \
     --purpose-shifted <true|false>
   ```

   **Default (interactive) path.** Inline-spawn ONE Task tool call
   for this file. Build inputs via:
   ```bash
   python3 ~/.smith/scripts/describe_discover.py \
     --rel-path <project-relative-path> \
     --touched-only \
     --touched-ids <comma-separated-16hex-ids>
   ```
   This emits a single-element JSON array; extract the entry. Then
   spawn one Task:
   ```yaml
   subagent_type: general
   model: claude-haiku-4-5
   prompt: |
     Return ONLY a JSON object matching task-llm-output.schema.json.
     File: <rel_path>
     Touched method ids (only describe these):
     <list of touched ids>
     Purpose shifted: <true|false>
     Existing module description (preserve if purpose-shifted=false):
     <existing module description or "(none)">
     <… per-method block built from the discover output's parser_output …>
     Full source (for context):
     ```
     <file source>
     ```
   ```
   When the Task returns, pipe its JSON output into the writer:
   ```bash
   echo '<task-output-json>' | \
     python3 ~/.smith/scripts/describe_write.py update-touched \
       --rel-path <project-relative-path> \
       --purpose-shifted <true|false>
   ```

   **Test stub.** If `SMITH_TASK_STUB=1` is set, skip the Task spawn
   and pipe the canned fixture entry into the writer instead.

   **Failure handling.** If any step fails (helper not installed,
   Task tool error, write error), log one line to the session log
   and CONTINUE — the missing description is surfaced as a
   non-blocking PR-body warning by `/smith-build` (Phase 8 /
   data-model.md §9). This step never blocks the fix.
```

(The smith-new variant at line 447 is the same prose; the smith-debug
variant at line 290 is the same prose. Each skill ships the entire
block to avoid cross-file references the LLM has to chase.)

## Phase-by-phase Build Order

1. **Foundation helpers.** Build `describe_discover.py`,
   `describe_write.py`, `describe_checkpoint.py` in that order. Each
   is unit-tested in isolation (helper tests, not the full Task-stub
   integration yet).
2. **Strip `meta_describe.py`.** Remove the LLM-call bits; tighten the
   structural keepers' public API (rename `_summarize_for_module_prompt`
   → `summarize_for_module_prompt` etc.). Re-run PR #21's existing
   tests for `parse_meta_descriptions` / `render_description_block` /
   `_qualifying_methods` — these must still pass byte-for-byte.
3. **Build `describe_headless.py`.** Copy the v2 path; verify against
   the existing golden `.meta` output of a small fixture project.
   Tests: `test_describe_headless.py`.
4. **Delete v2 orchestrator code from `run.py`.** Remove
   `mode_describe`, `_describe_one_file`, helpers, and CLI flags
   (`--describe`, `--batch-size`, `--llm-batch-size`, `--threshold`,
   `--model`, `--no-interactive`). Re-run PR #21's `run.py` tests for
   the OTHER modes — they must still pass.
5. **Add `/smith-index --describe` prose to `skills/smith-index/SKILL.md`.**
   This is the v3 entrypoint for the flag now that `run.py` no longer
   handles it. Update the modes table.
6. **Update workflow skills.** smith-new, smith-bugfix, smith-debug —
   replace shell-outs with the inline Task prose + headless fast-path.
7. **Tests.** Wire up `test_task_backend_stub.py` (bulk + incremental
   + purpose_shifted cases), `test_hash_cache_skip.py`, and the
   workflow-incremental integration shell test.
8. **Docs.** `CHANGELOG.md` v3.0.0 entry + `docs/manifest-system.md`
   "Backend selection: cli vs api" section.
9. **Acceptance run.** Run `/smith-index --describe` on the
   smith-repo itself with `SMITH_TASK_STUB=1` end-to-end. Verify all
   acceptance criteria from spec.md §Acceptance Criteria.

## Testing Strategy

### Test 1 — Task-backend stub (`tests/parsers/test_task_backend_stub.py`)

- Setup: `SMITH_TASK_STUB=1`, fixture file at
  `tests/fixtures/task-stub-responses.json` mapping rel_path →
  MetaDescription JSON.
- Cases:
  1. Bulk path, single Python file with 3 qualifying methods +
     module description.
  2. Incremental path, one touched method id, `purpose_shifted=false`
     (module preserved).
  3. Incremental path, one touched method id, `purpose_shifted=true`
     (module regenerated).
  4. Stale-id cleanup: existing `.meta` has a method id absent from
     the current parser output; v3 drops it.
- Assertions:
  - Resulting `.meta` matches a golden fixture byte-for-byte.
  - JSONL log contains one record per file with
    `backend: "stub"`.
  - Checkpoint state lists the processed `rel_path`.

### Test 2 — Headless regression (`tests/parsers/test_describe_headless.py`)

- Setup: `SMITH_ANTHROPIC_API_URL` points to a local stub HTTP server
  that returns canned Anthropic Messages API responses (parity with
  v2 mechanism at `meta_describe.py:309`).
- Run `python3 describe_headless.py --root <fixture-project>
  --no-interactive --resume false`.
- Assert: resulting `.meta` matches a golden produced by v2 on the
  same fixture project (committed as the golden).

### Test 3 — Hash-cache skip (`tests/parsers/test_hash_cache_skip.py`)

- Setup: pre-seed a `.meta` with a complete description layer whose
  `described_against_hash` matches the current source.
- Run the discovery helper; assert `cache_hit=true` for that entry.
- Run the full orchestrator (stub mode); assert zero new `.meta`
  bytes written (mtime + content unchanged).

### Test 4 — Workflow incremental integration (`tests/parsers/test_workflow_incremental_task.sh`)

- Setup: `SMITH_TASK_STUB=1` + fixture with one touched method.
- Drive the smith-bugfix Phase 3.5 path manually: discover, splice
  stub output via `describe_write.py update-touched`.
- Assert: existing untouched method descriptions are preserved
  verbatim; only the touched id was overwritten.

### Test 5 — PR #21 regression suite

- Re-run all PR #21 tests for `parse_meta_descriptions`,
  `render_description_block`, `_qualifying_methods`,
  `_summarize_for_module_prompt`, `_build_method_prompt`,
  `_truncate`. These tests live in PR #21's
  `tests/parsers/test_meta_describe.py` and must pass unchanged.

## Risks & Mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | The Task tool `subagent_type: general` does not accept a `model` override at v3 ship time → Tasks run on the session's primary model (Sonnet/Opus), inflating subscription token cost per call. | Medium | Medium | Document in spec §Assumptions; add a runtime probe at `describe_headless.py`-equivalent path in the skill prose that, if the model override is rejected, falls through to api backend with a clear warning instead of silently running expensive Sonnet Tasks. |
| R2 | Parallel Task spawning inside a single tool-use block hits an undocumented platform limit (e.g. > 8 sub-agents in one block fails). | Low | Medium | Default `--batch-size 10`; if a batch fails wholesale with a tool-block error, prose retries the same batch sub-divided into 5+5. |
| R3 | Stub fixture drift — golden `.meta` files diverge from what the live Task path would produce as the prompt template evolves. | Medium | Low | Keep the stub fixture keyed by `rel_path` (not by prompt hash), so prompt changes don't invalidate the fixture. Document the fixture-refresh procedure in the test file's docstring. |
| R4 | `CLAUDE_HEADLESS` naming collides with a future Claude Code feature. | Low | Low | Open Question 2 already surfaces this; defer rename decision but document the convention prominently in `docs/manifest-system.md`. |
| R5 | Removing `meta_describe.py update-touched` CLI breaks third-party callers (none known, but the docs/shipped scheduler could regress). | Low | Medium | Keep the `update-touched` surface on `describe_headless.py` (a subcommand) so legacy callers can swap binary names with a sed. CHANGELOG documents the rename. |
| R6 | The discovery helper imports private internals from `run.py` (parser-lib, `walk_source_files`, `sha256_first_4kb`) — these were not designed as a public API. | Medium | Low | Plan Decision 3: extract these into a thin `scripts/parsers/index_common.py` module imported by both `run.py` and the new helpers. Mechanical refactor; no behavior change. |
| R7 | Resume race: two `/smith-index --describe` invocations on the same project mid-run corrupt the checkpoint file. | Low | Medium | Reuse the existing `.smith/vault/active-workflows/` check (global rule, MEMORY.md note re: concurrent sessions). The describe prose checks this before starting and refuses to run if another describe is in flight. |

## Plan Decisions (beyond the six in spec.md)

### Plan Decision 1 — Collapse the two-tier batch knob into one

- **Decision.** v3 has a single `--batch-size` (default 10). v2's
  separate `--batch-size 20` (operator approval) and
  `--llm-batch-size 10` (LLM sub-batch) collapse — one batch is one
  operator-approval unit and one Task fan-out.
- **Rationale.** The two-tier model in v2 was a workaround for the
  Python loop being unable to parallelise within a batch. With Task
  fan-out, all 10 files in a batch run concurrently anyway. A second
  tier adds operator-prompt churn without throughput benefit. The
  spec says "default 10" (§A2.4) — this aligns.
- **Migration.** `--llm-batch-size` is removed. `--batch-size` default
  drops from 20 to 10. Document in CHANGELOG.

### Plan Decision 2 — `describe_write.py` owns prompt assembly

- **Decision.** The skill prose does NOT inline the prompt template;
  it delegates assembly to `describe_write.py build-prompt`
  (a new subcommand) which calls the public `summarize_for_module_prompt`
  + `build_method_prompt` from `meta_describe`. The skill receives the
  fully-assembled prompt string and embeds it in the Task call.
- **Rationale.** Keeping the prompt template in Python keeps it
  unit-testable and prevents prompt drift between the cli backend
  (skill prose) and api backend (describe_headless.py). One source
  of truth.
- **Alternative considered.** Skill prose templates the prompt in
  markdown. Rejected — markdown templating is harder to keep in sync
  with Python format changes and impossible to unit-test.

### Plan Decision 3 — Extract `scripts/parsers/index_common.py`

- **Decision.** Move `walk_source_files`, `sha256_first_4kb`,
  `iso_now_for_filename`, `iso_now_ms`, `load_checkpoint`, and
  `save_checkpoint` from `scripts/smith-index/run.py` into a new
  thin module `scripts/parsers/index_common.py`. Both `run.py` and
  the new `describe_*.py` helpers import from there.
- **Rationale.** Avoids the circular `describe_discover.py → run.py`
  import that would otherwise be required; gives the helpers a clean
  public interface; surface-level only — no behavior change.
- **Alternative considered.** Import `run` as `scripts.smith_index.run`
  from helpers. Rejected — fragile if `run.py` is restructured;
  package-discoverability under `scripts/smith-index/` is awkward
  (hyphen in the dir name).

## Migration

- **Existing v2 `.meta` files** — format is unchanged. v3 reads them
  via the same `parse_meta_descriptions` function. First v3
  `--describe` run on a v2 repo is a series of cache-hits (no LLM
  calls) unless source changed since the v2 run.
- **Existing scripts / cron using `ANTHROPIC_API_KEY`** — keep working
  via `describe_headless.py` (set `CLAUDE_HEADLESS=1` or pass
  `--llm-backend api`).
- **No data migration script required.**
- **User `.env` files** — no changes required. `ANTHROPIC_API_KEY` is
  no longer required for the default (cli) path, but is still
  honored if set (the headless path reads it).
- **Scheduler** — `scheduler/smith-scheduler.sh` does NOT currently
  set `CLAUDE_HEADLESS=1`. Spec Open Question 2 surfaces who owns
  this. Plan recommendation: scheduler sets it inside the per-task
  subshell at line 215 of `smith-scheduler.sh`. This recommendation
  is documented but the actual scheduler edit is deferred to a
  follow-up PR — out of scope for this feature per spec §Non-Goals.

## References

- `scripts/parsers/meta_describe.py` (PR #21) — the v2 LLM module.
- `scripts/smith-index/run.py:1100-1450` (PR #21) — the v2
  orchestrator.
- `scripts/parsers/contracts/meta-description-layer.schema.json`
  (PR #21) — unchanged.
- `specs/20-manifest-fixes/contracts/meta-description-layer.schema.json`
  (PR #21) — reference for the on-disk description layer schema.
- `specs/19-manifest-system/contracts/parser-output.schema.json` —
  parser output shape consumed by the prompt builders.
- `skills/smith-new/SKILL.md:447`, `skills/smith-bugfix/SKILL.md:208`,
  `skills/smith-debug/SKILL.md:290` — the three workflow shell-out
  sites being replaced.
- `skills/smith-index/SKILL.md` — gains the new
  `### /smith-index --describe` section.
- `scheduler/smith-scheduler.sh` — the headless invoker.
