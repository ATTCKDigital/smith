---
feature: 23-task-llm-backend
artifact: data-model.md
created: 2026-06-03
revised: 2026-06-03 (Q6 simplification — single backend, no headless)
---

# Data Model — Task-based LLM Backend

This document specifies every JSON/text contract exchanged among the
v3 components. The on-disk `.meta` description layer format is
**unchanged from PR #21** (see
`scripts/parsers/contracts/meta-description-layer.schema.json` for
that contract).

**v3 has a single backend — Task spawning. No `api` / `headless`
backend exists in v3.** All references to a `backend` discriminator
below have exactly two valid values: `task` (live runs) and `stub`
(test runs).

## §1 — discover → orchestrator (one file walk)

`describe_discover.py` writes to stdout a JSON array. Each entry:

```json
{
  "rel_path": "scripts/parsers/meta_describe.py",
  "source_hash": "9f3a…64hex",
  "parser_output": { /* parser-output-v2.schema.json shape */ },
  "qualifying_method_ids": ["abc1234567890def", "0123456789abcdef"],
  "existing_description": {
    "module_description": "…" | null,
    "method_descriptions": {
      "abc1234567890def": "…",
      "0123456789abcdef": "…"
    },
    "described_against_hash": "…" | null,
    "described_at": "2026-05-22T03:14:22Z" | null
  } | null,
  "cache_hit": false,
  "system": "system-manifest" | null,
  "discovery_error": null | "parser timeout"
}
```

### Field semantics

- `rel_path` — project-relative POSIX path, no leading `./`. Matches
  the `path` field in `parser-output-v2.schema.json`.
- `source_hash` — SHA-256 of the first 4KB of source content (parity
  with v2's `sha256_first_4kb` at `run.py` and the `.meta` `Hash:`
  field). 64 hex chars.
- `parser_output` — the full JSON the language parser emitted for the
  file. v3 helpers may transmit the whole thing (kilobytes-scale) or
  a reduced view; the orchestrator does not require the full thing
  for the Task prompt — only the imports/functions/classes summary
  produced by `summarize_for_module_prompt` is needed. The discover
  output INCLUDES the full parser output so the writer can reuse it
  for splice rendering without re-parsing.
- `qualifying_method_ids` — the subset of method ids passing the
  threshold check (`qualifying_methods`, formerly
  `_qualifying_methods` at `meta_describe.py:220`). The orchestrator
  uses `len(qualifying_method_ids)` to decide per-file vs per-method
  Task split (Q3 — default split threshold 15).
- `existing_description` — populated when a `.meta` description layer
  already exists for this file. Used by the orchestrator for two
  purposes: (a) cache_hit calculation, (b) module-description
  preservation when `purpose_shifted=false` on the incremental path.
- `cache_hit` — `true` iff
  `existing_description.described_against_hash == source_hash` AND
  (`existing_description.module_description` is non-empty OR
  `existing_description.method_descriptions` is non-empty). Mirrors
  the v2 hash-cache check at `run.py:1178-1183`.
- `system` — resolved system name (per `path-resolver.py`) or null.
- `discovery_error` — non-null when the parser failed for this file;
  the orchestrator records a `failed` JSONL entry and skips.

### Single-file mode

Used by the workflow incremental path. Same shape, array length 1,
plus `qualifying_method_ids` is filtered to the `--touched-ids` set.

## §2 — Task prompt template + expected Task output

### Prompt template (assembled by `describe_write.py build-prompt`)

The orchestrating LLM, when spawning a Task, passes a `prompt` string
of this shape:

```
You are generating descriptions for the Smith manifest .meta layer.

Return ONLY a JSON object (no preamble, no code fences, no
commentary) matching this schema:

{
  "status": "ok" | "error",
  "module_description": "<single line, ≤200 chars>",
  "method_descriptions": [
    {"method_id": "<16hex>", "description": "<≤400 chars>"},
    ...
  ],
  "errors": []
}

File: <rel_path>
Language: <parser_output.language>
Lines: <parser_output.lines>

<PARSER SUMMARY (summarize_for_module_prompt output):>
Imports:
  - <imp1>
  ...
Top-level functions:
  - <fn1>
  ...
Classes:
  - <cls1>  (methods: <m1>, <m2>, ...)
  ...

First 30 lines of source:
```
<head>
```

Methods to describe (only describe these ids; other methods may
appear in source but ignore them):
- Id: <method_id>
  Name: <scope>::<name>
  Signature: (<params>) -> <ret>
  Body lines: <start>-<end>
...

Full source (for context):
```
<source>
```

Soft caps: module ≤120 chars, method ≤200 chars. Concise,
informational, no marketing voice.
```

### Per-method-split prompt variant

When the orchestrator splits a file into per-method Tasks (qualifying
method count > 15), each Task receives a prompt with `method_ids`
filtered to ONE id. The module-description ask is dropped from
per-method Tasks; the module description for that file is generated
by a single additional Task (file-level, methods omitted) at the end
of the per-file group OR carried forward from `existing_description`
if `purpose_shifted=false`.

### Expected Task output

The Task returns a single text payload that, when stripped of code
fences (resilience), parses as JSON matching
`contracts/task-llm-output.schema.json`:

```json
{
  "status": "ok",
  "module_description": "Shared LLM description layer for Smith Manifest v2 — sole module crossing structural↔description boundary.",
  "method_descriptions": [
    {
      "method_id": "abc1234567890def",
      "description": "Parses a .meta text and returns its description layer; tolerant of v1 .meta missing the description layer."
    },
    ...
  ],
  "errors": []
}
```

### Error cases

When the Task encountered a problem it couldn't complete (e.g.
unparseable source), it returns:

```json
{
  "status": "error",
  "module_description": null,
  "method_descriptions": [],
  "errors": [
    {"code": "TOO_LARGE", "detail": "Source exceeds 200KB"}
  ]
}
```

The orchestrator records this as a `failed` JSONL entry; the `.meta`
is not touched. The orchestrator then retries with exponential
backoff (Q1) up to 3 attempts; after 3, the failure is final for that
run (a future `--describe` invocation will retry without `--resume`
because the file is not in the completed set).

## §3 — Orchestrator → `describe_write.py`

### Bulk mode (apply)

Stdin (or `--input <path>`):

```json
{
  "module_description": "…",
  "method_descriptions": [
    {"method_id": "…", "description": "…"},
    ...
  ]
}
```

Note this is the Task output payload minus the envelope keys
(`status`, `errors`). The writer accepts both forms (full envelope
or just the description fields) for robustness.

CLI:
```
python3 describe_write.py apply
  --rel-path <p>
  --root <project-root>
  --hash <source-hash>
  [--input <json-file>]
```

### Incremental (update-touched) mode

Stdin:

```json
{
  "module_description": "…" | null,
  "method_descriptions": [
    {"method_id": "abc1234567890def", "description": "…"}
  ]
}
```

CLI:
```
python3 describe_write.py apply --update-touched
  --rel-path <p>
  --root <project-root>
  --purpose-shifted true|false
  [--input <json-file>]
```

Semantics:

- If `purpose_shifted=false` AND `module_description` is null/empty:
  preserve the existing module description from the file's current
  `.meta`. If `purpose_shifted=true`: overwrite with the new module
  description.
- For each `method_descriptions[i]`: overwrite the entry for that
  `method_id` in the existing layer. Untouched ids are preserved
  verbatim.
- Drop stale ids (present in existing layer, absent from current
  parser output) — mirrors v2 `_describe` at `meta_describe.py:584-588`.
- Recompute `Described-Against-Hash` to the current source hash and
  `Described-At` to now (ISO 8601 UTC).

### Prompt-assembly mode (build-prompt)

CLI:
```
python3 describe_write.py build-prompt
  --rel-path <p>
  --root <project-root>
  [--method-ids <id1,id2,...>]
  [--module]
  [--purpose-shifted true|false]
```

Behavior: assembles the prompt-template body (§2) by calling the
public `summarize_for_module_prompt` + `build_method_prompt` from
`meta_describe`. Writes the assembled prompt to stdout. The
orchestrator embeds the result in a Task call.

### From-stub mode (test only)

CLI:
```
python3 describe_write.py apply --from-stub <fixture-path>
  --rel-path <p>
  --root <project-root>
  --hash <source-hash>
```

Behavior: read the entry for `rel_path` from the fixture, then run
the same write path as bulk mode. **Fail-loud** semantics:

- Missing `rel_path` key in fixture → exit 4 with message
  `"stub fixture missing entry for rel_path: <p>"`.
- Missing required `method_id` in the fixture's `method_descriptions`
  (where "required" = the orchestrator's `qualifying_method_ids` set
  for this file) → exit 4 with message
  `"stub fixture missing method_id <hex> for rel_path: <p>. Update tests/fixtures/task-stub-responses.json or regenerate the fixture."`

(Q5 answer A: brittleness is the feature — surfaces parser/fixture
drift.)

## §4 — JSONL log line format

One line per processed file, written via
`describe_checkpoint.py append`:

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

### Field semantics

- `timestamp` — ISO 8601 UTC with millisecond precision (parity with
  v2 `iso_now_ms` at `run.py`).
- `item_id` — the project-relative path. Same as `rel_path` elsewhere.
- `stage` — one of `describe` (success), `skipped`, `failed`.
- `status` — duplicates `stage` for back-compat with v2 readers
  (v2 wrote both fields).
- `error` — error reason for `failed`/`skipped` entries; null for
  `ok`. Examples: `"resume"`, `"operator-reject"`,
  `"task-tool-timeout"`, `"json-parse-error"`, `"cache-hit"`,
  `"task-tool-rate-limit"`.
- `method_count` — number of method descriptions written (0 for
  skipped/failed).
- `module_chars` — length of module description written (0 for
  skipped/failed).
- `batch_index` — 1-based batch counter. Useful for retry
  granularity.
- `retry_count` — **v3 addition.** Number of exponential-backoff
  retries attempted for this file. 0 for first-try success. Helps
  operators identify flaky files for follow-up.
- `backend` — **v3 addition.** Identifies which path produced this
  record. Valid values: `task` (live), `stub` (test). v2 readers
  ignore unknown keys (forward-compatible).

## §5 — Checkpoint state file

Path: `.smith/index/.smith-index-describe-checkpoint.json`

```json
{
  "version": 3,
  "started_at": "2026-06-03T14:00:00Z",
  "last_batch_index": 12,
  "backend": "task",
  "processed_files": [
    "scripts/parsers/meta_describe.py",
    "scripts/parsers/parse-python.py",
    ...
  ]
}
```

### Field semantics

- `version` — `3` for v3 (v2 used `1`, original v3 draft used `2`).
  v3 reader accepts `1`, `2`, and `3` for backward compat.
- `started_at` — ISO 8601 UTC of the run start. Used for log file
  correlation.
- `last_batch_index` — last batch that completed any work. Used to
  resume mid-batch (the orchestrator re-emits the batch starting
  from the first un-processed file in it).
- `backend` — v3 addition. Valid values: `task`, `stub`. Helps the
  operator confirm the right backend was used on a resume.
- `processed_files` — append-only list of completed rel_paths.
  `--resume` unions this with the JSONL log's `ok` records.

### Lifecycle

- Created on first batch completion.
- Updated after every per-file success (one save call per file —
  cheap; the file is small).
- **Deleted on clean exit** (parity with v2 `mode_describe` final
  `run.cleanup()` semantics).
- **Retained on abort / Ctrl-C / fatal error** so `--resume` works.

## §6 — Stub responses fixture file

Path: `tests/fixtures/task-stub-responses.json`

```json
{
  "scripts/parsers/meta_describe.py": {
    "module_description": "Shared LLM description layer for Smith Manifest v2.",
    "method_descriptions": [
      {
        "method_id": "abc1234567890def",
        "description": "Parses a .meta text and returns its description layer; tolerant of v1 .meta missing the layer."
      },
      {
        "method_id": "0123456789abcdef",
        "description": "Returns the dict shape consumed by render_meta's existing_descriptions parameter."
      }
    ]
  },
  "scripts/parsers/parse-python.py": {
    "module_description": "…",
    "method_descriptions": [...]
  }
}
```

### Semantics

- Top-level keyed by `rel_path` (POSIX, no leading `./`).
- Each value is a MetaDescription payload (no envelope) matching the
  Bulk-mode writer input shape (§3).
- Inside each value, `method_descriptions[*].method_id` provides the
  per-method lookup keys.
- **Fail-loud at two levels (Q5):**
  - Missing `rel_path` key → exit 4 with descriptive error.
  - Missing required `method_id` in the keyed entry's
    `method_descriptions` array → exit 4 with descriptive error
    naming both the rel_path AND the missing method_id.
- Test maintainers regenerate the fixture by running `/smith-index
  --describe` on the fixture project with the live backend and
  capturing the output.

## §7 — Pre-flight estimate output

Before the bulk loop starts, the skill prose prints (Q4):

```
/smith-index --describe pre-flight summary
─────────────────────────────────────────────
  Files needing description: N
  Qualifying methods total: M
  Per-method-split threshold: 15 (configurable via --per-method-threshold)
  Per-method-split files: K (qualifying > 15)
  Estimated Tasks to spawn: T
  Estimated wall time: ~W minutes (5s/Task sequential)

Proceed? (y/N):
```

`--yes` bypasses the gate. The scheduler invocation MUST pass `--yes`.

This is a text payload printed to stderr (so the summary doesn't
pollute any stdout-captured output). Not a parseable structure;
intended for human consumption.

## §8 — Model probe payload (Q7)

Before the bulk loop, one Task is spawned with:

```yaml
subagent_type: general
model: claude-haiku-4-5
prompt: "Respond with exactly: MODEL_OK"
```

### Expected response shape

A Haiku model honoring the override will respond:

```
MODEL_OK
```

(Possibly with trailing whitespace or a period — the orchestrator
accepts any response whose trimmed text equals `MODEL_OK`.)

### Failure heuristic

If the response is:
- empty
- contains substantive content beyond `MODEL_OK` (e.g. a multi-line
  explanation, a refusal, a re-formatted answer)
- formatted differently (e.g. wrapped in JSON, Markdown)

the orchestrator interprets this as "the model override was NOT
honored — the response shape doesn't match what a Haiku would emit
for this prompt" and aborts the run.

### Override

`--skip-model-probe` bypasses the probe. Documented in the SKILL.md
prose as "use at your own risk; this is a guard against silent
~30× quota burn."

## §9 — Field-by-field comparison vs PR #21

| Field | PR #21 (v2) | PR #23 (v3) | Change |
|---|---|---|---|
| `.meta` Description: | present | present | unchanged |
| `.meta` Described-Against-Hash: | present | present | unchanged |
| `.meta` Described-At: | present | present | unchanged |
| `.meta` per-method `Id:`/`Description:` | present | present | unchanged |
| JSONL `timestamp` | iso8601-ms | iso8601-ms | unchanged |
| JSONL `item_id` | rel_path | rel_path | unchanged |
| JSONL `stage` | describe/skipped/failed | describe/skipped/failed | unchanged |
| JSONL `status` | ok/skipped/failed | ok/skipped/failed | unchanged |
| JSONL `method_count` | int | int | unchanged |
| JSONL `module_chars` | int | int | unchanged |
| JSONL `batch_index` | int | int | unchanged |
| JSONL `retry_count` | (absent) | int (0+) | **NEW** |
| JSONL `backend` | (absent) | task/stub | **NEW** (2 values, not 3 — no `api`) |
| Checkpoint `version` | 1 | 3 | bumped; v3 reads 1/2/3 |
| Checkpoint `backend` | (absent) | task/stub | **NEW** |
| Checkpoint `processed_files` | list[str] | list[str] | unchanged |

All v2 readers (PR #21's logs and checkpoint state) are
forward-readable by v3 — v3 readers accept missing optional fields.
v2 producers wrote no `backend` field; v3 default-fills with `task`
when reading old data.

## §10 — References

- `scripts/parsers/contracts/meta-description-layer.schema.json` (PR
  #21) — unchanged contract for the on-disk description layer.
- `specs/19-manifest-system/contracts/parser-output.schema.json` (PR
  #19) — parser output shape consumed by discover.
- `contracts/task-llm-output.schema.json` (this feature) — Task
  sub-agent return envelope.
- `questions.md` (this feature) — answered design questions Q1-Q8;
  Q6 in particular drives the no-headless-backend simplification.
