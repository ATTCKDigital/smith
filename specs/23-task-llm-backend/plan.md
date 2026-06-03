---
feature: 23-task-llm-backend
branch: 23-task-llm-backend
created: 2026-06-03
revised: 2026-06-03 (Q6 simplification — single Task-spawning backend, no headless fallback)
status: planning
builds_on: 19-manifest-system (PR #19) + 20-manifest-fixes (PR #21) + install-path-fallback (PR #22)
---

# Implementation Plan — Task-based LLM Backend for the Description Layer

## Technical Context

- **Language / runtime.** Python 3 stdlib only for all new helpers. Node
  (vendored `acorn`) is invoked transitively by `parse-js.js` but no new
  Node dependencies are introduced. No `anthropic` SDK. v3 strips out
  every direct-HTTPS LLM call — there is no `urllib.request` import in
  the v3 LLM-call path because v3 has no direct-HTTPS LLM-call path.
- **LLM call mechanism.** The orchestrating LLM in the user's Claude
  Code session spawns one Task tool sub-agent per file
  (`subagent_type: "general"`, model `claude-haiku-4-5`). Task calls
  inherit session auth → subscription billing. **There is no fallback
  backend** — the 2am scheduler uses `claude --print` which IS a Claude
  Code session with Task tool access, so the same code path serves both
  interactive and scheduled runs.
- **Model.** `claude-haiku-4-5` (matches PR #21
  `meta_describe.py:48` constant `DEFAULT_MODEL`). Configurable via the
  existing `--model` CLI flag.
- **Concurrency strategy.** Sequential within each batch (Q2 answer B).
  The skill prose spawns Tasks one-at-a-time within a batch — not as a
  parallel tool-use block. Simpler per-Task error handling, visible
  progress logging. Across batches, the runtime cap is irrelevant
  because batches themselves run sequentially.
- **Batch size.** Default 10 (Plan Decision 1). v2's two-tier batching
  (`--batch-size 20` operator-approval + `--llm-batch-size 10` LLM
  sub-batch) collapses to a single `--batch-size 10`.
- **Per-method split.** Default per-file granularity. If a file has > 15
  qualifying methods (Q3 answer B), split into per-method Tasks.
  Configurable via `--per-method-threshold` (default 15).
- **Test harness.** Skill prose detects `SMITH_TASK_STUB=1`. In stub
  mode, instead of spawning a Task, the prose invokes
  `python3 scripts/parsers/describe_write.py apply --from-stub
  <fixture-path> --rel-path <p>` which reads a canned MetaDescription
  JSON keyed by `method_id` and writes the `.meta` the same way as the
  live path. Missing-id behavior is **fail loud** (Q5 answer A).
- **Threshold.** Unchanged from v2 (`DEFAULT_THRESHOLD_LINES = 5` at
  `meta_describe.py:47`).
- **Soft caps.** Unchanged from v2 (`MODULE_DESC_SOFT_CAP = 120`,
  `METHOD_DESC_SOFT_CAP = 200`).

## Constitution Check

- **Rule 1 (Questions ≠ Actions).** Not applicable — this is an
  implementation plan, not a user question.
- **Rule 2 (SpecKit triggers + skill compliance).** N/A at plan stage;
  but plan respects the sub-step order under `/smith-plan`.
- **Rule 3 (Question file before complex changes).** Eight questions
  were generated and answered in `questions.md`. Q6 in particular
  triggered a major simplification (drop the headless backend
  entirely) which this revision reflects.
- **Rule 4 (Checkpoint/Resume).** Preserved.
  `scripts/parsers/describe_checkpoint.py` (NEW) writes:
  - JSONL log at `~/.smith/logs/smith-index-describe-<ISO>.jsonl` (one
    record per processed file, shape matches v2 at
    `run.py:1291-1300`).
  - Checkpoint state at
    `.smith/index/.smith-index-describe-checkpoint.json` after every
    batch.
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

v3 (single backend — Task spawning):
  User → /smith-index --describe → SKILL.md prose [LLM orchestrator IN session]
            ├─ Step 0: runtime model probe (1 Task call, verify Haiku honored)
            ├─ python3 describe_discover.py → JSON[]:
            │     [{rel_path, source_hash, parsed, existing_desc,
            │       qualifying_method_ids, cache_hit, system}, …]
            ├─ Filter cache_hit=true entries
            ├─ Apply --resume skip set via describe_checkpoint.py load-completed
            ├─ Pre-flight estimate + confirmation gate (skip with --yes)
            ├─ Loop batches (default 10 files / batch):
            │     For each file in batch (sequential):
            │       ├─ If qualifying_method_ids count > 15: split to
            │       │  per-method Tasks; else one Task per file.
            │       ├─ Build prompt body via describe_write.py build-prompt
            │       ├─ Spawn Task (subagent_type: general,
            │       │  model: claude-haiku-4-5).
            │       │  On failure: exponential backoff retry 5s→10s→20s,
            │       │  max 3 attempts. After 3: log failed, continue.
            │       ├─ Pipe Task JSON output into describe_write.py apply
            │       │  → splices into .meta atomically
            │       ├─ describe_checkpoint.py append (JSONL)
            │     describe_checkpoint.py save (state) at batch end
            └─ describe_checkpoint.py summary

Scheduled run (2am scheduler):
  launchd → claude --print -p "/smith-queue process <task>"
            (this IS a Claude Code session; Task tool available)
            → /smith-queue process …
            → eventually invokes /smith-index --describe --yes
            → SAME code path as interactive (no env-var branching).
```

## File Structure

All paths absolute under `/Users/dennisplucinik/Projects/smith-repo`.

### NEW

| Path | Approx LOC | Purpose |
|---|---|---|
| `scripts/parsers/index_common.py` | ~120 | Shared helpers extracted from run.py: `walk_source_files`, `sha256_first_4kb`, `iso_now_for_filename`, `iso_now_ms`, `load_checkpoint`, `save_checkpoint`, `meta_path_for`, `atomic_write_text`. Importable only. |
| `scripts/parsers/describe_discover.py` | ~200 | File discovery, hash, existing-meta scan, cache-hit determination, qualifying-method-id enumeration. Stdout JSON. Importable. |
| `scripts/parsers/describe_write.py` | ~260 | TWO subcommands: `build-prompt` (assembles a complete prompt body) and `apply` (splices MetaDescription JSON into `.meta` atomically). Supports `--update-touched` and `--from-stub` modes. |
| `scripts/parsers/describe_checkpoint.py` | ~140 | JSONL log writer + checkpoint state reader/writer + `--resume` loader + summary printer. |
| `tests/parsers/test_task_backend_stub.py` | ~220 | Task-stub fixture + bulk/incremental/purpose_shifted/per-method-split coverage. Fail-loud on missing id (Q5). |
| `tests/parsers/test_hash_cache_skip.py` | ~110 | Re-run-on-unchanged-source → zero `.meta` writes. |
| `tests/parsers/test_workflow_incremental_task.sh` | ~80 | End-to-end integration of the workflow incremental path via stub. |
| `tests/fixtures/task-stub-responses.json` | ~80 | Canned MetaDescription JSON keyed by `method_id`. |
| `specs/23-task-llm-backend/contracts/task-llm-output.schema.json` | ~70 | JSON Schema for the Task sub-agent's return envelope. (Already committed.) |

### MODIFY

| Path | Net LOC Delta | Change |
|---|---|---|
| `scripts/parsers/meta_describe.py` | −340 / +0 (~426 → ~280 net after strip + drop CLI) | STRIP `_default_haiku_call` (`:290-345`), `HaikuUnavailable` (`:286-287`), `describe_file` (`:452-479`), `update_touched` (`:482-521`), `_describe` private (`:524-622`), `_safe_json_object` (`:625-656`), `_cli_update_touched` (`:666-731`), `_build_argparser` + `main` + `__main__` block (`:734-766`), all `urllib.request` imports, all `ANTHROPIC_API_KEY` / `SMITH_ANTHROPIC_API_URL` / `anthropic-version` references. KEEP `MethodDescription`, `MetaDescription`, soft-cap constants, `_iso_now`, `_sha256`, `parse_meta_descriptions`, `render_description_block`, `_qualifying_methods`, `_summarize_for_module_prompt`, `_build_method_prompt`, `_truncate`, `_MODULE_SYSTEM`, `_METHOD_SYSTEM`. Rename to drop leading underscore where now public: `qualifying_methods`, `summarize_for_module_prompt`, `build_method_prompt`, `truncate`, `MODULE_SYSTEM`, `METHOD_SYSTEM`. Module becomes purely structural — zero LLM call code, zero env-var reads. |
| `scripts/smith-index/run.py` | −370 / +0 | DELETE `_read_meta_text` (`:1106-1110`), `_extract_hash_from_meta` (`:1113-1121`), `_describe_one_file` (`:1124-1206`), `mode_describe` (`:1209-1450`+) and all argparse pieces for `--describe`, `--batch-size`, `--llm-batch-size`, `--threshold`, `--model`, `--no-interactive` (`:1755-1788`) and dispatcher (`:1804-1814`). KEEP the `_meta_describe` import block (`:126-153`) and the `:861` callsite that uses `parse_meta_descriptions` / `render_description_block` for non-describe modes. ALSO MODIFY: replace the local definitions of `walk_source_files`, `sha256_first_4kb`, `iso_now_*`, `load_checkpoint`, `save_checkpoint` with imports from the new `index_common.py`. |
| `skills/smith-index/SKILL.md` | +220 / −0 | ADD a new `### /smith-index --describe` section (no such section exists today — flag is currently only parsed in run.py). Section contains the full v3 orchestration prose (see Component Design §5 below). |
| `skills/smith-new/SKILL.md` | +40 / −8 | REPLACE the `python3 ~/.smith/scripts/meta_describe.py update-touched …` shell-out at line 447 with inline Task spawning prose. No headless fallback path. |
| `skills/smith-bugfix/SKILL.md` | +40 / −12 | Same replacement at line 208. |
| `skills/smith-debug/SKILL.md` | +40 / −6 | Same replacement at line 290. |
| `docs/manifest-system.md` | +60 / −20 | Replace any v2 "ANTHROPIC_API_KEY required" prose with a "Task-based LLM backend" subsection explaining the inversion. Remove direct-HTTPS references. |
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
- `scheduler/smith-scheduler.sh` — Q6 investigation confirmed this
  script already invokes `claude --print` which is a Claude Code
  session. No edits needed for v3.

## Component Design

### 1. `index_common.py` (NEW — shared utilities)

**Purpose.** Avoid the circular `describe_discover.py → run.py` import
that would otherwise be required. Surface-level only; no behavior
change.

**Exports.**

```python
def walk_source_files(root: Path, *, system_filter: Optional[str] = None) -> Iterator[Path]: ...
def sha256_first_4kb(path: Path) -> str: ...
def iso_now_for_filename() -> str: ...
def iso_now_ms() -> str: ...
def load_checkpoint(path: Path) -> Optional[dict]: ...
def save_checkpoint(path: Path, state: dict) -> None: ...
def meta_path_for(root: Path, rel_path: str) -> Path: ...
def atomic_write_text(path: Path, content: str) -> None: ...
```

Imported by `run.py` (replacing local definitions), `describe_discover.py`,
`describe_write.py`, `describe_checkpoint.py`.

### 2. `describe_discover.py`

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

**Internals.** Imports `walk_source_files`, `sha256_first_4kb` from
`index_common`. Imports `parse_meta_descriptions`, `qualifying_methods`
(now public) from `meta_describe`. Imports the parser-lib invocation
helpers (`resolve_parser`, `run_parser`, `passive_parse`) — these
either move to `index_common.py` too OR stay in `run.py` and get
imported with `sys.path` munging. **Plan: move them to `index_common.py`**
to keep the parser-lib invocation single-source.

**Error handling.** On parser failure for one file, emit the entry with
`parser_output: null, cache_hit: false` and a `discovery_error` string
field. The orchestrator decides to skip; the helper never aborts the
whole walk.

**Performance budget.** < 30s for a 1,200-file repo (matches v2
discovery cost — parser invocations dominate).

### 3. `describe_write.py`

**Purpose.** Two responsibilities: (1) assemble prompt bodies from
existing parser output + soft-cap rules (`build-prompt` subcommand);
(2) splice MetaDescription JSON into `.meta` atomically (`apply`
subcommand).

Owning prompt assembly here (Plan Decision 2) means the skill prose
NEVER duplicates the template — one source of truth for both v3 paths
(bulk `/smith-index --describe` and the three workflow incremental
SKILL.md files).

**CLI subcommands.**

```
# Prompt assembly — returns the prompt body (no instructions about
# Task spawning; the caller embeds this in their Task call):
python3 describe_write.py build-prompt
  --rel-path <p>
  --root <project-root>
  [--method-ids <id1,id2,...>]     # incremental — only describe these
  [--module]                        # include module-description ask
  [--purpose-shifted true|false]   # for incremental

# Apply mode (one file, MetaDescription on stdin):
python3 describe_write.py apply
  --rel-path <p>
  --root <project-root>
  --hash <sha256-first-4kb>
  [--input <json-file>]            # else read stdin

# Apply incremental (workflow incremental path):
python3 describe_write.py apply --update-touched
  --rel-path <p>
  --root <project-root>
  --purpose-shifted true|false
  [--input <json-file>]

# Test stub mode (skip the LLM entirely, replay from fixture):
python3 describe_write.py apply --from-stub <fixture-path>
  --rel-path <p>
  --root <project-root>
  --hash <sha256-first-4kb>
```

**Behavior.**

- `build-prompt` invokes `summarize_for_module_prompt` +
  `build_method_prompt` from `meta_describe` and prints the assembled
  prompt body to stdout.
- `apply` reads the existing `.meta` via `parse_meta_descriptions`.
  Merges incoming MetaDescription:
  - Bulk: overwrite module + all method descriptions for the file.
  - update-touched: replace only the supplied method ids; regenerate
    module iff `purpose_shifted=true`; drop stale ids absent from the
    current parser output (mirrors `_describe` at
    `meta_describe.py:584-588`).
- Applies `truncate` for soft/hard caps (same numbers as v2).
- Renders via `render_description_block` → splices into the full
  `.meta` via the `render_meta` callable (moved alongside the other
  splice helpers).
- Atomic write: tempfile in the same dir + `os.rename`.
- Stub mode: reads the canned response from the fixture, runs the
  same write path. The stub fixture maps `method_id` → description
  string (data-model.md §6). **Fail loud on missing id** — exit code
  4 with clear error message.

**Error handling.** Exit codes:
- 0 success
- 2 input validation error (bad JSON, missing rel-path, etc.)
- 3 disk write error (write to a `.meta.tmp` failed)
- 4 stub fixture missing required method id (test-only, fail-loud)

### 4. `describe_checkpoint.py`

**Purpose.** Centralise Rule-4 plumbing.

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
  "retry_count": 0,
  "backend": "task" | "stub"
}
```

The `backend` field has two valid values in v3 (`"task"` for live
runs, `"stub"` for tests). The v2 `"api"` value is no longer produced.

**Checkpoint state file.**

```json
{
  "version": 3,
  "processed_files": ["a.py", "b.js", ...],
  "started_at": "2026-06-03T14:00:00Z",
  "last_batch_index": 12,
  "backend": "task"
}
```

**Performance.** Append-only writes; flush after every record (matches
v2 line-buffered `open(..., buffering=1)` at `run.py:1278`).

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

Single backend — no `--llm-backend` flag, no `CLAUDE_HEADLESS` env
var. The 2am scheduler uses `claude --print` (a Claude Code session)
so this same code path serves scheduled runs unchanged.

#### Step 0 — Runtime model probe

Before any bulk work, spawn ONE small Task to verify the Haiku model
override is honored:

```yaml
subagent_type: general
model: claude-haiku-4-5
prompt: "Respond with exactly: MODEL_OK"
```

If the response doesn't arrive cleanly OR the response is suspiciously
long/verbose for a "MODEL_OK" answer (heuristic — Haiku would respond
crisply), abort with:

> ERROR: Could not verify Haiku model override. Running the bulk
> loop on the session's primary model would inflate subscription
> cost ~30×. Verify your Task tool subagent type supports the model
> parameter. Pass `--skip-model-probe` to override at your own risk.

Pass `--skip-model-probe` skips this check.

#### Step 1 — Discovery

```bash
python3 scripts/parsers/describe_discover.py \
  --root "$ROOT" \
  ${SYSTEM:+--system "$SYSTEM"} \
  --threshold "${THRESHOLD:-5}"
```

Parse the JSON output. Drop entries with `cache_hit=true` — these
are no-ops (their `.meta` already matches the current source hash).

#### Step 2 — Resume filter

If `--resume` was passed:

```bash
python3 scripts/parsers/describe_checkpoint.py load-completed \
  --log-dir .smith/index/logs \
  --state .smith/index/.smith-index-describe-checkpoint.json
```

Filter the remaining files to exclude completed `rel_path` values.

#### Step 3 — Pre-flight estimate + confirmation gate

After filtering, count files needing description and sum their
`qualifying_method_ids` counts. Print:

```
Will spawn N Tasks covering M qualifying methods total.
Estimated wall time: ~T minutes at 5s/Task sequential.
Proceed? (y/N):
```

Calculate T as `N * 5s / 60` (one Task per file unless per-method
split applies; over-split files add to N).

If `--yes` was passed (or stdin is not a tty), bypass the confirm
gate. The scheduler MUST pass `--yes`.

#### Step 4 — Sequential Task spawning loop

Batch the remaining files in groups of 10 (default; override with
`--batch-size`). For each batch, process files **sequentially**:

For each file in the batch:

1. **Per-method-split decision.** If
   `len(qualifying_method_ids) > 15` (default; override with
   `--per-method-threshold`), spawn one Task PER METHOD instead of
   one Task per file. The loop body below is the same; the prompt
   asks for only one method's description per Task.

2. **Build the prompt.** Invoke the prompt-assembly helper:
   ```bash
   PROMPT=$(python3 scripts/parsers/describe_write.py build-prompt \
     --rel-path "$REL" --root "$ROOT" \
     --method-ids "<ids>" --module)
   ```

3. **Spawn the Task.** ONE Task call:
   ```yaml
   subagent_type: general
   model: claude-haiku-4-5
   prompt: |
     <PROMPT body from step 2>

     Return ONLY a JSON object matching the schema below (no
     preamble, no fences):

     {
       "status": "ok" | "error",
       "module_description": "<≤200 chars, single line>" | null,
       "method_descriptions": [
         {"method_id": "<16hex>", "description": "<≤400 chars>"},
         ...
       ],
       "errors": []
     }
   ```

4. **Retry on failure (exponential backoff).** If the Task call
   fails or returns malformed JSON or `status="error"`, retry with
   backoff 5s → 10s → 20s. Max 3 attempts. After 3, log a `failed`
   JSONL record and move to the next file. Do NOT abort the run.

5. **STUB MODE.** If `SMITH_TASK_STUB=1` is set, skip the Task spawn
   entirely. Pipe the canned fixture entry into the writer:
   ```bash
   python3 scripts/parsers/describe_write.py apply --from-stub \
     tests/fixtures/task-stub-responses.json \
     --rel-path "$REL" --root "$ROOT" --hash "$HASH"
   ```
   The stub fails loud (exit 4) if any qualifying method id is not
   in the fixture. Tests set `SMITH_TASK_STUB=1`; users never do.

6. **Apply the result.** Pipe the Task's JSON output into the writer:
   ```bash
   echo "$TASK_OUTPUT" | \
     python3 scripts/parsers/describe_write.py apply \
       --rel-path "$REL" --root "$ROOT" --hash "$HASH"
   ```

7. **Append checkpoint records.** One JSONL line per file:
   ```bash
   python3 scripts/parsers/describe_checkpoint.py append \
     --log "$LOG_PATH" \
     --record '{"item_id":"<rel>","status":"ok",
                "stage":"describe","backend":"task",
                "method_count":<n>,"module_chars":<m>,
                "batch_index":<i>,"retry_count":<r>,
                "timestamp":"<iso>"}'
   ```

After all files in the batch complete, persist checkpoint state:
```bash
python3 scripts/parsers/describe_checkpoint.py save \
  --path .smith/index/.smith-index-describe-checkpoint.json \
  --processed "<rel_path>"
```
(One save call per processed file.)

#### Step 5 — Summary

After all batches complete (or on abort):

```bash
python3 scripts/parsers/describe_checkpoint.py summary \
  --log "$LOG_PATH" --start-iso "$START_ISO"
```

Format: `/smith-index --describe: N files described
(succeeded=S failed=F skipped=K) in T.Ts`.

On clean completion, remove the checkpoint state file. On Ctrl-C or
fatal error, leave it in place so `--resume` works.

#### Failure handling summary

- **Per-Task failure.** Exponential backoff retry (5s → 10s → 20s,
  max 3). After 3, log `failed`, continue. No run-level abort.
- **Per-batch checkpoint failure.** Log a critical warning but keep
  going — Rule 4 says checkpoint is best-effort.
- **Model probe failure.** Hard abort before any bulk work, with
  clear message. `--skip-model-probe` to override.
- **No-LLM-call surprise.** If `meta_describe.py` somehow imports
  `urllib`, a CI check fails the build. `grep -r ANTHROPIC_API_KEY
  scripts/parsers/` must return zero matches.
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
3. **Update the `.meta` description layer.** Inline-spawn ONE Task
   tool call for this file.

   First, gather inputs:
   ```bash
   DISCOVERY=$(python3 ~/.smith/scripts/describe_discover.py \
     --rel-path <project-relative-path> \
     --touched-only \
     --touched-ids <comma-separated-16hex-ids>)
   ```

   This emits a single-element JSON array; extract the entry.

   Then build the prompt body:
   ```bash
   PROMPT=$(python3 ~/.smith/scripts/describe_write.py build-prompt \
     --rel-path <project-relative-path> \
     --method-ids <comma-separated-16hex-ids> \
     --purpose-shifted <true|false> \
     $( [ "<purpose_shifted>" = "true" ] && echo --module ))
   ```

   Spawn the Task:
   ```yaml
   subagent_type: general
   model: claude-haiku-4-5
   prompt: |
     <PROMPT body>

     Return ONLY a JSON object matching task-llm-output.schema.json
     with `method_descriptions` for ONLY the touched ids, and a
     `module_description` iff purpose-shifted=true.
   ```

   When the Task returns, pipe its JSON output into the writer:
   ```bash
   echo "$TASK_OUTPUT" | \
     python3 ~/.smith/scripts/describe_write.py apply --update-touched \
       --rel-path <project-relative-path> \
       --purpose-shifted <true|false>
   ```

   **Test stub.** If `SMITH_TASK_STUB=1` is set, skip the Task spawn
   and use `apply --from-stub` instead.

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

1. **Extract `index_common.py`.** Mechanical refactor: move
   `walk_source_files`, `sha256_first_4kb`, `iso_now_*`,
   `load_checkpoint`, `save_checkpoint`, parser-lib invocation
   helpers from `run.py` into `index_common.py`. Update `run.py` to
   import. Run PR #21's existing `run.py` tests — must still pass.
2. **Strip `meta_describe.py`.** Remove the LLM-call bits; tighten the
   structural keepers' public API (rename `_summarize_for_module_prompt`
   → `summarize_for_module_prompt` etc.). Re-run PR #21's existing
   tests for `parse_meta_descriptions` / `render_description_block` /
   `qualifying_methods` — these must still pass byte-for-byte.
3. **Build the new helpers.** `describe_discover.py`,
   `describe_write.py`, `describe_checkpoint.py` in that order. Each
   is unit-tested in isolation.
4. **Delete v2 orchestrator code from `run.py`.** Remove
   `mode_describe`, `_describe_one_file`, helpers, and CLI flags
   (`--describe`, `--batch-size`, `--llm-batch-size`, `--threshold`,
   `--model`, `--no-interactive`). Re-run PR #21's `run.py` tests for
   the OTHER modes — they must still pass.
5. **Add `/smith-index --describe` prose to `skills/smith-index/SKILL.md`.**
   This is the v3 entrypoint for the flag now that `run.py` no longer
   handles it. Update the modes table.
6. **Update workflow skills.** smith-new, smith-bugfix, smith-debug —
   replace shell-outs with the inline Task prose.
7. **Tests.** Wire up `test_task_backend_stub.py` (bulk + incremental
   + purpose_shifted + per-method-split cases), `test_hash_cache_skip.py`,
   and the workflow-incremental integration shell test.
8. **Docs.** `CHANGELOG.md` v3.0.0 entry + `docs/manifest-system.md`
   "Task-based LLM backend" section (replacing v2 HTTPS prose).
9. **Acceptance run.** Run `/smith-index --describe` on the
   smith-repo itself with `SMITH_TASK_STUB=1` end-to-end. Verify all
   acceptance criteria from spec.md §Acceptance Criteria.

## Testing Strategy

### Test 1 — Task-backend stub (`tests/parsers/test_task_backend_stub.py`)

- Setup: `SMITH_TASK_STUB=1`, fixture file at
  `tests/fixtures/task-stub-responses.json` mapping `method_id` →
  description.
- Cases:
  1. Bulk path, single Python file with 3 qualifying methods +
     module description.
  2. Incremental path, one touched method id, `purpose_shifted=false`
     (module preserved).
  3. Incremental path, one touched method id, `purpose_shifted=true`
     (module regenerated).
  4. Stale-id cleanup: existing `.meta` has a method id absent from
     the current parser output; v3 drops it.
  5. Per-method-split: file with 20 qualifying methods; assert the
     stub is invoked once per method (or once with all in single
     entry, depending on writer mode).
  6. **Missing-id fail-loud:** fixture omits a required method id;
     assert `describe_write.py apply --from-stub` exits 4 with the
     expected error message.
- Assertions:
  - Resulting `.meta` matches a golden fixture byte-for-byte.
  - JSONL log contains one record per file with `backend: "stub"`.
  - Checkpoint state lists the processed `rel_path`.

### Test 2 — Hash-cache skip (`tests/parsers/test_hash_cache_skip.py`)

- Setup: pre-seed a `.meta` with a complete description layer whose
  `described_against_hash` matches the current source.
- Run the discovery helper; assert `cache_hit=true` for that entry.
- Run the full orchestrator (stub mode); assert zero new `.meta`
  bytes written (mtime + content unchanged).

### Test 3 — Workflow incremental integration (`tests/parsers/test_workflow_incremental_task.sh`)

- Setup: `SMITH_TASK_STUB=1` + fixture with one touched method.
- Drive the smith-bugfix Phase 3.5 path manually: discover, build
  prompt, splice stub output via `describe_write.py apply
  --update-touched`.
- Assert: existing untouched method descriptions are preserved
  verbatim; only the touched id was overwritten.

### Test 4 — PR #21 regression suite

- Re-run all PR #21 tests for `parse_meta_descriptions`,
  `render_description_block`, `qualifying_methods`,
  `summarize_for_module_prompt`, `build_method_prompt`,
  `truncate`. These tests live in PR #21's
  `tests/parsers/test_meta_describe.py`. Tests for the deleted CLI
  (`update-touched`) must be removed alongside the CLI itself.

### Test 5 — No-direct-HTTPS sanity check

- A shell test: `grep -rn 'ANTHROPIC_API_KEY\|api.anthropic.com\|urllib.request' scripts/parsers/`
  must return ZERO matches in the v3 tree.

## Risks & Mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | The Task tool `subagent_type: general` does not accept a `model` override at v3 ship time → Tasks run on the session's primary model (Sonnet/Opus), inflating subscription token cost per call. | Medium | High | **Runtime model probe (Q7).** Skill prose Step 0 spawns one trivial Task to verify Haiku honors the override. On failure, hard abort with clear error. `--skip-model-probe` for users who accept the risk. |
| R2 | Sequential Task spawning within a batch is slower than parallel — a 1,214-file repo at 5s/Task is ~100 minutes vs ~10 minutes parallel. | High | Low | **Accepted trade-off (Q2).** Sequential keeps per-Task error handling simple and progress visible. Re-evaluate after real runs; can switch to parallel-with-fallback if pain materializes. |
| R3 | Stub fixture drift — golden `.meta` files diverge from what the live Task path would produce as the prompt template evolves. | Medium | Low | Keep the stub fixture keyed by `method_id` (not by prompt hash), so prompt changes don't invalidate the fixture. **Fail-loud on missing id (Q5)** surfaces drift immediately. |
| R4 | Pre-flight estimate is inaccurate (the 5s/Task assumption is too optimistic on dense methods). | Low | Low | Display the estimate as `~T minutes (estimate based on 5s/Task)`. Users can override the gate with `--yes`. Estimate accuracy is a quality-of-life issue, not a correctness one. |
| R5 | Removing `meta_describe.py update-touched` CLI breaks third-party callers (none known, but the docs/shipped scheduler could regress). | Low | Medium | The CLI was internal-only. All in-repo callers (3 SKILL.md files) are updated in this PR. CHANGELOG calls out the removal. |
| R6 | Helper scripts import private internals from `run.py` (parser-lib, `walk_source_files`, `sha256_first_4kb`) — these were not designed as a public API. | Medium | Low | **Plan Decision 3:** extract these into `scripts/parsers/index_common.py`. Mechanical refactor; no behavior change. |
| R7 | Resume race: two `/smith-index --describe` invocations on the same project mid-run corrupt the checkpoint file. | Low | Medium | Reuse the existing `.smith/vault/active-workflows/` check (global rule, MEMORY.md note re: concurrent sessions). The describe prose checks this before starting and refuses to run if another describe is in flight. |
| R8 | The 2am scheduler's `claude --print` invocation has different Task-tool semantics than interactive sessions (e.g. concurrency cap differs). | Low | Medium | Documented as an assumption. Sequential batching means concurrency cap is irrelevant. First scheduled run is the live verification. |

## Plan Decisions (beyond the seven in spec.md)

### Plan Decision 1 — Single `--batch-size` (default 10)

- **Decision.** v3 has a single `--batch-size` (default 10). v2's
  separate `--batch-size 20` (operator approval) and
  `--llm-batch-size 10` (LLM sub-batch) collapse — one batch is one
  unit of checkpoint persistence and one progress group.
- **Rationale.** With sequential within-batch (Q2 B), there's no
  reason for two batch tiers. One source of truth for batch size.
- **Migration.** `--llm-batch-size` is removed. `--batch-size` default
  drops from 20 to 10. Document in CHANGELOG.

### Plan Decision 2 — `describe_write.py` owns prompt assembly

- **Decision.** The skill prose does NOT inline the prompt template;
  it delegates assembly to `describe_write.py build-prompt`
  (a subcommand) which calls the public `summarize_for_module_prompt`
  + `build_method_prompt` from `meta_describe`. The skill receives the
  fully-assembled prompt string and embeds it in the Task call.
- **Rationale.** One source of truth for prompt construction across
  the bulk path (SKILL.md) and the three workflow incremental paths
  (smith-new/smith-bugfix/smith-debug SKILL.md). Unit-testable.
- **Alternative considered.** Skill prose templates the prompt in
  markdown. Rejected — markdown templating is harder to keep in sync
  with Python format changes and impossible to unit-test.

### Plan Decision 3 — Extract `scripts/parsers/index_common.py`

- **Decision.** Move `walk_source_files`, `sha256_first_4kb`,
  `iso_now_for_filename`, `iso_now_ms`, `load_checkpoint`,
  `save_checkpoint`, and the parser-lib invocation helpers from
  `scripts/smith-index/run.py` into a new thin module
  `scripts/parsers/index_common.py`. Both `run.py` and the new
  `describe_*.py` helpers import from there.
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
- **Existing scripts / cron using `ANTHROPIC_API_KEY`** — break in v3.
  The env var is no longer read anywhere in the v3 code paths.
  Existing callers must either: (a) migrate to invoking
  `/smith-index --describe --yes` via `claude --print`, or
  (b) pin to v2 and stop upgrading. CHANGELOG documents this loud and
  clear under "Breaking changes."
- **No data migration script required.**
- **Scheduler** — `scheduler/smith-scheduler.sh` already invokes
  `claude --print -p "/smith-queue process …"` (verified in Q6
  investigation). The scheduler does NOT need any v3 edits because:
  (a) it doesn't currently call `--describe` directly,
  (b) when `/smith-queue` eventually adds a `--describe` task, it
      will route through the SAME `/smith-index --describe` skill
      code path, getting Task spawning for free.

## References

- `scripts/parsers/meta_describe.py` (PR #21) — the v2 LLM module
  that v3 strips down.
- `scripts/smith-index/run.py:1100-1450` (PR #21) — the v2
  orchestrator removed in v3.
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
- `scheduler/smith-scheduler.sh` — Q6 confirmed this is a Claude
  Code session via `claude --print`; no scheduler edits in v3.
