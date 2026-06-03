---
feature: 23-task-llm-backend
branch: 23-task-llm-backend
created: 2026-06-03
revised: 2026-06-03 (Q6 simplification — single Task-spawning backend, no headless fallback)
status: in-progress
builds_on: 19-manifest-system (PR #19) + 20-manifest-fixes (PR #21) + install-path-fallback (PR #22)
---

# Task-based LLM Backend — Skill-ify the Description-Generation Layer

## Summary

Invert the orchestration of the `.meta` description layer so that LLM calls
inherit the user's Claude Code session auth (subscription billing) instead
of the separately-billed `ANTHROPIC_API_KEY` HTTPS path. The `.meta` storage
format and per-method threshold semantics from PR #21 are unchanged.

**v3 ships a single backend — Task spawning via Claude Code session.** The
v2 direct-HTTPS path is removed wholesale. The 2am scheduler
(`scheduler/smith-scheduler.sh`) already invokes `claude --print` which IS
a Claude Code session with the Task tool available, so scheduled
`/smith-index --describe` runs work via the same Task-spawning path — no
separate headless fallback is needed.

## Background — The Architectural Inversion

PR #21 (merged 2026-05-21) shipped the description layer in v2. Today the
orchestrator is a Python subprocess:

- `scripts/smith-index/run.py:1209` — `mode_describe(...)` — discovers files,
  batches them (default 20), and for each file calls
  `_describe_one_file` (`run.py:1124`).
- `scripts/parsers/meta_describe.py:290` — `_default_haiku_call(...)` — POSTs
  directly to `https://api.anthropic.com/v1/messages` using
  `ANTHROPIC_API_KEY` from the environment.
- `scripts/parsers/meta_describe.py:452` — `describe_file(...)` — bulk path.
- `scripts/parsers/meta_describe.py:482` — `update_touched(...)` — incremental
  path, also invoked by the three smith workflow skills via the
  `python3 meta_describe.py update-touched ...` CLI (`meta_describe.py:666`).
- Workflow skills shell out to that CLI from
  `skills/smith-new/SKILL.md:447`, `skills/smith-bugfix/SKILL.md:208`, and
  `skills/smith-debug/SKILL.md:290`.

Because the LLM call originates from a Python subprocess, it cannot reach
Claude Code's Task tool. The Task tool is only available to the LLM that is
actively orchestrating a Claude Code session. A subprocess is, by definition,
outside that session. The consequence: every `--describe` run bills the
`ANTHROPIC_API_KEY` owner — separate from the user's Claude Code
subscription. On a 1,214-file repo (~120 batched calls) this is a real
recurring cost.

v3 inverts the orchestration:

- The **skill prose** (the LLM in the user's session) becomes the driver of
  the description loop.
- **Python helpers** become a structural toolkit: file discovery, parser
  invocation, `.meta` parsing/rendering, JSONL log + checkpoint, atomic
  writes, prompt assembly.
- The skill **spawns Task sub-agents inline** (one per file, `subagent_type:
  general`, model `claude-haiku-4-5`) and collects each Task's
  MetaDescription JSON output. Task spawning inherits session auth →
  subscription billing.

**The 2am scheduler works unchanged.** Investigation confirmed
`scheduler/smith-scheduler.sh` invokes `claude --print -p "/smith-queue
process <task>"`, which IS a full Claude Code session — the Task tool is
available in that session, identical to interactive runs. No separate
"headless" code path is needed.

The `.meta` on-disk format (Description / Described-Against-Hash /
Described-At + per-method `Id:` / `Description:` blocks under `## Functions`
and `## Classes`) is unchanged from PR #21. The contract at
`scripts/parsers/contracts/meta-description-layer.schema.json` is unchanged.
v2-produced `.meta` files are forward-compatible: re-running `/smith-index
--describe` on an unchanged file is a hash-cache hit (no-op).

## Goals

1. The single backend for `/smith-index --describe` and the workflow
   incremental path is inline Task spawning — subscription-billed.
2. The `.meta` format, the per-method threshold default, and the
   description soft/hard caps from PR #21 are NOT changed.
3. Rule 4 checkpoint/resume continues to work end-to-end.
4. v2 tests pass; v3 adds tests for the Task-stub path, the workflow
   incremental path, and the hash-cache skip.
5. Pre-flight estimate + confirmation gate (`--yes` bypass) so multi-hour
   runs are not started by accident.
6. Runtime model probe verifies `claude-haiku-4-5` is honored before the
   bulk loop begins; abort with a clear error if not (no silent quota
   burn on the session's primary model).

## Non-Goals / Out of Scope

- Changing the `.meta` description layout or contract schema.
- Retaining ANY direct-API HTTPS path. v3 removes
  `_default_haiku_call`, `describe_file`, `update_touched`, the
  `update-touched` CLI, and every `ANTHROPIC_API_KEY` reference from
  `meta_describe.py`. There is no `--llm-backend` flag and no
  `CLAUDE_HEADLESS` env var.
- Changing per-method threshold or description caps from PR #21.
- Modifying other `/smith-index` modes — `--check`, `--system`,
  `--migrate-templates`, `--incremental`, `--resume`,
  `--init-system-paths` — all retained as-is.
- The `.specify/systems/` path-resolver tier from PR #21 Track A. Separate
  concern.
- Introducing a new `/smith-describe` skill. `--describe` stays a flag of
  `/smith-index` for discoverability and to match v2 docs.

## Users / Stakeholders

- **Repo owners** running `/smith-index --describe` on real codebases —
  primary beneficiary; subscription billing eliminates per-run API charges.
- **The 2am scheduler** (`scheduler/smith-scheduler.sh`) — runs `claude
  --print` which is a Claude Code session; Task spawning works there
  unchanged.
- **Smith workflow operators** (`/smith-new`, `/smith-bugfix`,
  `/smith-debug`) — touched-method `.meta` updates now route through Task
  spawning.
- **Test maintainers** — need a deterministic Task-stub path to keep CI
  hermetic.

## Requirements

### Track A — `/smith-index --describe` skill-ification

#### A1. Move orchestration into SKILL.md prose

Move the description loop out of `scripts/smith-index/run.py:1209`
(`mode_describe`) and into prose in `skills/smith-index/SKILL.md` under
the existing `### /smith-index --describe` section. Do NOT create a new
skill — `--describe` remains a flag of `/smith-index`.

Delete `mode_describe()` (`run.py:1209`) and `_describe_one_file()`
(`run.py:1124`). Delete `--describe` CLI dispatch in `run.py` (and any
associated argparser branch). The skill prose, not `run.py`, is the
entrypoint for the `--describe` route in v3.

#### A2. Skill prose contract

The skill prose, when invoked with `--describe`, MUST:

1. **Runtime model probe (Q7).** Before any bulk work, spawn one small
   Task with `subagent_type: general`, `model: claude-haiku-4-5`, and a
   trivial prompt that asks the sub-agent to echo `MODEL_OK` only. If
   the response does not arrive cleanly OR the response indicates a
   different model ran (heuristic: response length / verbosity exceeds
   what a Haiku response of "MODEL_OK" should look like), abort with a
   clear error: "Could not verify Haiku model override; running the bulk
   loop on the session's primary model would inflate subscription cost.
   Please verify your Claude Code Task tool subagent type supports the
   model parameter, or run with `--skip-model-probe` if you accept that
   risk." Single Task call (~1s); acceptable overhead before a multi-hour
   run.
2. **Discovery + cache filter.** Invoke
   `scripts/parsers/describe_discover.py` (NEW — A3) to get a JSON list
   of files needing description: each entry carries `rel_path`,
   `source_hash`, `parsed` (parser output), the existing `.meta`
   description state (if any), and a `cache_hit` boolean (true when
   `described_against_hash == source_hash` and at least a module or one
   method description already exists).
3. **Resume filter.** Apply the `--resume` skip set from the most recent
   describe JSONL log + checkpoint (same recovery shape as PR #21's
   `run.py:1252`).
4. **Pre-flight estimate (Q4).** After filtering, print a summary:
   "Will spawn N Tasks (one per file), covering M qualifying methods.
   Estimated wall time: ~T minutes at ~5s/Task sequential." Then ask the
   user to confirm: "Proceed? (y/N)". `--yes` bypasses the gate for
   automation (the scheduler invocation MUST pass `--yes`).
5. **Batch + spawn (Q2, Q3).** Batch remaining files in groups of N
   (default 10, configurable via `--batch-size`). Within a batch, spawn
   Tasks **sequentially** — one at a time — for simpler per-Task error
   handling and visible progress logging. For each file:
   - **Per-method split (Q3).** If the file has > 15 qualifying methods,
     spawn ONE Task per method instead of one Task per file. Threshold
     configurable via `--per-method-threshold` (default 15).
   - Each Task gets `subagent_type: "general"`, model override
     `claude-haiku-4-5`, and a prompt assembled by
     `scripts/parsers/describe_write.py build-prompt --rel-path <p>`
     (NEW — A3). Prompt body contains the file's source, the parser
     output (functions, classes, methods with stable ids), the list of
     qualifying method ids, and the instruction to return strict JSON
     matching the MetaDescription contract.
   - **Exponential backoff retry (Q1).** On Task failure (rate-limit,
     timeout, malformed JSON), retry inline with backoff 5s → 10s → 20s.
     Max 3 attempts per Task. After 3 attempts, log the failure to the
     JSONL and continue with the next file. No run-level abort.
6. **Per-result write.** For each Task's JSON output, invoke
   `scripts/parsers/describe_write.py apply` with the MetaDescription
   JSON + `rel_path`; the helper splices into the `.meta` file
   atomically.
7. **Checkpoint per batch.** Append a Rule-4 JSONL record per file via
   `scripts/parsers/describe_checkpoint.py`. After every batch, persist
   checkpoint state (already-processed `rel_path` list) so `--resume`
   works.
8. **Summary line.** At completion (or on Ctrl-C / sustained failure),
   print the Rule-4 summary: `/smith-index --describe: N files described
   (N succeeded, N failed, N skipped) in T.Ts`.

#### A3. Python helper split

Four files; three new, one modified. Plus `index_common.py` extracted
for shared utilities.

- **NEW** `scripts/parsers/index_common.py` — shared helpers used by both
  `describe_discover.py` and `describe_write.py` (and reusable by other
  index scripts): source-file walk honoring gitignore (extracted from
  `walk_source_files` in `run.py`), `compute_source_hash`, atomic-write
  primitive (`atomic_write_text(path, content)`), `.meta` path resolver
  (`meta_path_for(rel_path) -> Path`). No CLI surface — importable only.
- **NEW** `scripts/parsers/describe_discover.py` — file walk, per-file
  source hash, parser invocation (delegates to `parse-python.py` /
  `parse-js.js`), existing `.meta` description parse, `cache_hit`
  determination, qualifying-method count for per-method-split decision.
  CLI: `python3 describe_discover.py --root <dir> [--system <name>]
  [--threshold <n>] [--rel-path <p>] [--touched-only]` → stdout JSON
  list. Importable as `discover(...)` for tests.
- **NEW** `scripts/parsers/describe_write.py` — TWO subcommands:
  - `build-prompt --rel-path <p> [--method-ids <id1,id2,...>] [--module]`
    → stdout a complete prompt body ready to pass to the Task tool.
    Owns prompt assembly so the skill prose only passes context, not
    template strings. Internally calls the prompt-template helpers
    re-exported from `meta_describe.py` (see A4).
  - `apply --rel-path <p>` (reads MetaDescription JSON on stdin or
    `--input <path>`) → writes the description block into the `.meta`
    atomically. Supports `--update-touched` mode: takes a subset of
    method ids + `--purpose-shifted true|false` and merges into the
    existing layer.
- **NEW** `scripts/parsers/describe_checkpoint.py` — JSONL log +
  checkpoint state. CLI: `python3 describe_checkpoint.py append --log
  <path> --record <json>` and `python3 describe_checkpoint.py save
  --path <path> --processed <rel_path>`. `python3
  describe_checkpoint.py load --path <path>` for `--resume` callers.

#### A4. `meta_describe.py` strip-down

- **MODIFY** `scripts/parsers/meta_describe.py` — strip the LLM call
  path entirely. Remove:
  - `_default_haiku_call` (`:290`)
  - `HaikuClient` dependency-injection plumbing in `_describe` (`:524`)
  - `describe_file` (`:452`)
  - `update_touched` (`:482`)
  - the `update-touched` CLI entrypoint (`:666`)
  - the argparser at `:734`
  - all references to `ANTHROPIC_API_KEY`, `SMITH_ANTHROPIC_API_URL`,
    `anthropic-version` header constants

  Keep ONLY structural pieces (now public — drop leading underscores
  where called by the new helpers):
  - `MethodDescription` (`:61`)
  - `MetaDescription` (`:73`)
  - `parse_meta_descriptions` (`:102`)
  - `render_description_block` (`:185`)
  - `qualifying_methods` (was `_qualifying_methods` at `:220`)
  - `summarize_for_module_prompt` (was `_summarize_for_module_prompt`)
  - `build_method_prompt` (was `_build_method_prompt`)
  - `MODULE_SYSTEM` and `METHOD_SYSTEM` prompt constants

  Module becomes purely structural — no `import urllib`, no
  `subprocess`, no env-var reads. Importable by `describe_discover.py`,
  `describe_write.py`, and any future v3.x consumer.

- **MODIFY** `scripts/smith-index/run.py` — delete `mode_describe`
  (`:1209`), `_describe_one_file` (`:1124`), `_read_meta_text`
  (`:1106`), `_extract_hash_from_meta` (`:1113`), the `--describe` CLI
  flag and its dispatcher. The `_meta_describe` import block stays
  (other modes still use `parse_meta_descriptions` /
  `render_description_block` — see `run.py:861`).

### Track B — Smith workflow incremental path

#### B1. Inline Task spawning in workflow skills

Modify three skill files to replace the existing CLI shell-out:

- `skills/smith-new/SKILL.md:447` — the Phase 4.5 mid-conversation
  `.meta` update step.
- `skills/smith-bugfix/SKILL.md:208` — the Phase 3.5 update step.
- `skills/smith-debug/SKILL.md:290` — the post-fix `.meta` update step.

New prose for each: "For each modified source file (`.py`, `.js`,
`.jsx`, `.ts`, `.tsx`), identify touched method ids via the helper
(`python3 ~/.smith/scripts/describe_discover.py --rel-path <p>
--touched-only`), then spawn ONE Task call (subagent_type `general`,
model `claude-haiku-4-5`) with the prompt assembled by `python3
~/.smith/scripts/describe_write.py build-prompt --rel-path <p>
--method-ids <ids>` (and `--module` if `purpose_shifted` is true).
Pipe the Task output into `python3 ~/.smith/scripts/describe_write.py
apply --update-touched --rel-path <p> --purpose-shifted
<true|false>`." Each SKILL.md ships the exact spawn skeleton so the
orchestrating LLM doesn't author it from scratch.

No shell-out to any LLM-calling Python script. The Task spawn IS the
LLM call.

### Track C — Tests, migration, docs

#### C1. Task-backend stub

- **NEW** `tests/parsers/test_task_backend_stub.py` — unit test that
  exercises the skill-driven path WITHOUT a Claude Code session. The
  test sets a sentinel env var `SMITH_TASK_STUB=1` and provides a
  fixture file `tests/fixtures/task-stub-responses.json` keyed by
  method id with canned MetaDescription JSON. The skill prose's
  "spawn Task" step (when `SMITH_TASK_STUB=1`) records the prompt it
  WOULD have sent and reads the canned response from the fixture
  instead. The test then verifies the written `.meta` matches the
  expected golden file.

  **Missing-id behavior (Q5): fail loud.** If a method id appears in
  the discovery output but not in the fixture, the stub aborts the test
  with a clear error: "Stub fixture missing canned response for
  method_id <hash>. Update tests/fixtures/task-stub-responses.json or
  regenerate the fixture." Brittleness here is the feature — it
  surfaces drift between the fixture and the parser output.

- Test coverage: bulk path (a full file), incremental path (single
  touched id), `purpose_shifted=true` triggers module re-description,
  `purpose_shifted=false` preserves module, per-method-split path
  (file with > 15 qualifying methods spawns per-method Tasks).

#### C2. Hash-cache skip test

- **NEW** `tests/parsers/test_hash_cache_skip.py` — pre-seeds a `.meta`
  with a valid description layer matching the source hash, runs
  discovery, asserts `cache_hit=true` for that file, and asserts the
  full pipeline writes zero new bytes to that `.meta`.

#### C3. Migration

No data migration. v2 `.meta` files are forward-compatible: their
`Described-Against-Hash:` field is what enables the v3 hash-cache. The
first v3 `--describe` run on a v2 repo is a series of cache-hits — no
LLM calls, no `.meta` writes — unless source files have changed since
the v2 run.

#### C4. Documentation

- Update `docs/manifest-system.md` with a v3 architecture section
  ("Task-based LLM backend") explaining the inversion and the
  prose-orchestration model. Cite skill prose as the orchestrator.
  Insert near the existing v2 `.meta` description-layer section.
  Remove the v2 reference to `ANTHROPIC_API_KEY` and direct HTTPS.
- Update `CHANGELOG.md` with a v3.0.0 entry summarizing the
  architectural inversion, the helper split, and the wholesale removal
  of the direct-API path.

## Design Decisions

### Decision: Keep `--describe` as a flag of `/smith-index`

- **Decision.** Do NOT introduce a new `/smith-describe` skill. The
  description loop becomes prose inside `skills/smith-index/SKILL.md`
  under the existing `### /smith-index --describe` section.
- **Rationale.** Discoverability — users already know `--describe` as a
  mode of `/smith-index`. Splitting would fragment the help surface and
  require migrating every reference in `docs/manifest-system.md` and in
  PR #21's spec.
- **Alternatives considered.**
  - New `/smith-describe` skill: cleaner separation, but a docs and
    muscle-memory churn for zero functional gain.

### Decision: Skill prose is the orchestrator; Python is a toolkit

- **Decision.** The LLM driving the user's Claude Code session is the
  loop driver. Python helpers do file discovery, parser invocation,
  `.meta` I/O, JSONL log/checkpoint, and prompt assembly — they
  never make LLM calls.
- **Rationale.** The Task tool is the ONLY entrypoint that inherits
  session auth → subscription billing. The Task tool is only callable
  by the orchestrating LLM. So the orchestrator MUST be the
  orchestrating LLM, not a subprocess.

### Decision: Single backend — no direct-API fallback (Q6)

- **Decision.** Remove the v2 direct-HTTPS path entirely.
  `meta_describe.py` becomes a structural module with zero LLM-call
  code. No `--llm-backend` flag, no `CLAUDE_HEADLESS` env var, no
  `describe_headless.py`.
- **Rationale.** Original design retained a headless fallback for the
  2am scheduler. Investigation of `scheduler/smith-scheduler.sh`
  revealed it invokes `claude --print -p "/smith-queue process <task>"`
  — which IS a full Claude Code session with Task tool access. So the
  scheduler use case is covered by the same Task-spawning path; a
  separate headless backend would duplicate ~250 LOC for no functional
  gain. Removing it also eliminates the "two-backend drift" maintenance
  burden and the per-skill env-var-aware branching prose.
- **Implications.** If a future use case truly requires LLM calls
  outside a Claude Code session (e.g., a foreign CI runner without
  Claude installed), it must be re-introduced as an external integration
  — out of scope for this release.

### Decision: Sequential within batch (Q2)

- **Decision.** Within each batch, the skill spawns Tasks one at a time
  (not parallel in a single tool-use block).
- **Rationale.** Per-Task error handling is far simpler when each
  spawn is its own tool-use turn — the skill prose can inspect each
  result, retry that specific Task, or log a single failure without
  juggling per-position error mapping for a wholesale block. Visible
  progress (`processing file 4/10 in batch 2/13`) is also clean.
- **Trade-off accepted.** Sequential is slower than parallel
  (factor ~N for batch size N). For a 1,214-file repo at 5s/Task this
  is ~100 minutes vs ~10 minutes parallel. Acceptable for v3 ship
  given the simplicity win; can revisit if real runs prove painful.

### Decision: Per-file default with per-method split above 15 (Q3)

- **Decision.** Default one Task per file. If a file has > 15
  qualifying methods, split into per-method Tasks. Threshold
  configurable via `--per-method-threshold` (default 15).
- **Rationale.** Most files have < 15 qualifying methods; per-file is
  efficient. Dense files (long modules, controllers, generated code)
  would produce prompts large enough to risk token-cap truncation or
  incoherent descriptions; per-method scopes them tightly. Threshold
  was chosen empirically — a 15-method file produces a prompt of
  roughly 6-10K tokens which fits comfortably; 30+ methods can push
  past 20K.

### Decision: Exponential backoff per Task; no run-level abort (Q1)

- **Decision.** On Task failure, retry inline with backoff 5s → 10s →
  20s, max 3 attempts. After 3, log and move on to the next file.
  Do NOT abort the whole run on sustained failures.
- **Rationale.** Subscription rate limits typically resolve within
  seconds; exponential backoff handles transient cases. For sustained
  failures, the user wants the run to keep making forward progress on
  other files rather than bail completely — the JSONL log captures
  exactly which files failed for re-run via `--resume`.

### Decision: Pre-flight estimate + confirmation gate (Q4)

- **Decision.** Before the bulk loop starts, print "Will spawn N Tasks
  (~M methods total). Estimated wall time: ~T minutes." Ask "Proceed?
  (y/N)". `--yes` bypasses the gate (required for the scheduler).
- **Rationale.** Subscription quotas and multi-hour runs deserve user
  awareness. The gate is cheap (one stdin read) and the bypass flag
  preserves automation. Matches PR #21's batch-approval pattern.

### Decision: Runtime model probe (Q7)

- **Decision.** Before the bulk loop, spawn one trivial Task with
  `model: claude-haiku-4-5` and verify the response is consistent with
  a Haiku-style answer. If not, abort with a clear error.
- **Rationale.** The Task tool's `subagent_type: general` model
  override is an assumption — if the runtime ignores it, every bulk
  Task runs on the session's primary (Sonnet/Opus) at ~30x the cost.
  One extra Task call (~1s) is cheap insurance against quietly burning
  the user's subscription quota.
- **Trade-off accepted.** The probe is heuristic (response length /
  shape), not authoritative — there's no programmatic "what model ran"
  signal. False positives (abort when Haiku actually ran but produced
  an unusual response) are recoverable via `--skip-model-probe`.

### Decision: Test stub fails loud on missing id (Q5)

- **Decision.** When `SMITH_TASK_STUB=1` and the discovery output
  contains a method id not present in the canned-responses fixture,
  the test fails with a clear error rather than auto-synthesizing or
  skipping.
- **Rationale.** Brittleness here catches real bugs — drift between
  the parser output and the fixture indicates the parser changed or
  the fixture is stale. Silent placeholders would hide both.

## Hard Constraints

- The `.meta` description layer format from PR #21 is **byte-stable** in
  v3 for cache-hit cases (re-running `--describe` on unchanged source
  produces zero `.meta` writes).
- Source files are NEVER modified by any v3 path (inherits v2 invariant).
- `python3` everywhere, never `python`.
- All LLM calls in v3 go through Task spawning. No `urllib.request`
  imports remain in `meta_describe.py` or any new file. No
  `ANTHROPIC_API_KEY` reads anywhere in the v3 code paths.
- The contract schema at
  `scripts/parsers/contracts/meta-description-layer.schema.json` is
  unchanged.
- Other `/smith-index` modes (`--check`, `--system`, `--migrate-templates`,
  `--incremental`, `--resume`, `--init-system-paths`) are NOT touched by
  this feature beyond the `_describe_one_file` / `mode_describe` removal.

## Acceptance Criteria

### Functional

1. `/smith-index --describe` invoked in an interactive Claude Code session
   spawns Task sub-agents (no direct HTTPS); each Task call inherits
   session auth and bills the user's subscription.
2. `/smith-index --describe` invoked from the 2am scheduler (via
   `claude --print -p "/smith-queue process ..."`) ALSO spawns Task
   sub-agents — same code path, no env-var-aware branching.
3. `/smith-index --describe` aborts with a clear error if the runtime
   model probe fails to confirm Haiku.
4. `/smith-index --describe` shows pre-flight estimate and waits for
   confirmation; `--yes` bypasses.
5. `/smith-new`, `/smith-bugfix`, `/smith-debug` touched-method `.meta`
   updates spawn one Task per modified file (or per-method when split
   threshold exceeded).
6. Hash-cache hit: re-running `--describe` on a file whose source hash
   matches `described_against_hash` writes zero bytes to its `.meta`.
7. Rule 4 checkpoint/resume: interrupting `--describe` mid-run and
   re-invoking with `--resume` skips already-completed files and resumes
   from the checkpoint.
8. v2-produced `.meta` files are read correctly by v3
   (`parse_meta_descriptions` round-trips identically — no schema bump).
9. `grep -r ANTHROPIC_API_KEY scripts/` in the v3 tree returns ZERO
   matches (sanity check that the direct-HTTPS path is gone).

### Performance

- Per-file Task latency target: < 30 seconds wall clock (Haiku is fast;
  spawn overhead is < 1s in current runtimes).
- Sequential batching: a 100-file run completes in roughly
  100 × 5s = ~8 minutes wall clock (conservatively).
- Skill orchestration overhead (prose-driven loop bookkeeping): < 10% of
  total wall-clock time on a 100-file run.

### Quality

- All PR #21 tests still pass unchanged (excluding the deleted
  `update-touched` CLI tests, which are removed alongside the CLI).
- New tests pass: Task-backend stub (C1), hash-cache skip (C2).
- `meta_describe.py` byte size shrinks substantially (LLM-call code +
  the `update-touched` CLI are removed; only structural code remains).
- No clarification-pending markers in any v3 spec, plan, or task.

## Assumptions

- The Task tool's `subagent_type: general` accepts a `model` override
  parameter and accepts `claude-haiku-4-5` as a valid value. (Runtime
  probe in A2.1 verifies this before the bulk loop; if it fails, the
  run aborts with a clear error rather than silently inflating cost.)
- The Anthropic Messages API is no longer relevant to v3 — all calls
  go through Task spawning. (The contract format for MetaDescription
  JSON is unchanged from v2, just no longer transmitted over HTTPS by
  smith code.)
- The current `_qualifying_methods` threshold (5 lines, per
  `meta_describe.py:220`) is still the right gate — not revisited.
- `claude --print -p "<slash-command>"` invocations behave identically
  to interactive sessions with respect to the Task tool. (Verified via
  inspection of `scheduler/smith-scheduler.sh` and Claude Code's
  headless-mode docs.)

## References

- PR #19 — `19-manifest-system` — initial manifest scaffolding (merged
  2026-05-21).
- PR #21 — `20-manifest-fixes` — the v2 description layer; spec at
  `specs/20-manifest-fixes/spec.md`.
- PR #22 — install-path-fallback — install-script bugfix; unrelated to
  billing but landed in the same window.
- `scripts/parsers/meta_describe.py` (PR #21) — the file v3 strips down
  to a structural-only module.
- `scripts/smith-index/run.py` (PR #21) — the file v3 removes
  `mode_describe` / `_describe_one_file` / `--describe` from.
- `scripts/parsers/contracts/meta-description-layer.schema.json` — the
  contract unchanged in v3.
- `skills/smith-index/SKILL.md`, `skills/smith-new/SKILL.md`,
  `skills/smith-bugfix/SKILL.md`, `skills/smith-debug/SKILL.md` — the
  four skill files modified in v3.
- `scheduler/smith-scheduler.sh` — confirmed `claude --print` session
  invocation; Task tool available in scheduled runs.
- Global rule: Rule 4 (Checkpoint/Resume for Long-Running Processes) —
  drives the JSONL log + checkpoint requirement in A2 and the new
  `describe_checkpoint.py` helper.
