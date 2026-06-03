---
feature: 23-task-llm-backend
branch: 23-task-llm-backend
created: 2026-06-03
status: in-progress
builds_on: 19-manifest-system (PR #19) + 20-manifest-fixes (PR #21) + install-path-fallback (PR #22)
---

# Task-based LLM Backend — Skill-ify the Description-Generation Layer

## Summary

Invert the orchestration of the `.meta` description layer so that LLM calls
inherit the user's Claude Code session auth (subscription billing) instead
of the separately-billed `ANTHROPIC_API_KEY` HTTPS path. The `.meta` storage
format and per-method threshold semantics from PR #21 are unchanged. The
direct-HTTPS path is retained as a `--llm-backend api` fallback for
headless/cron contexts where no Claude Code session exists.

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
  writes.
- The skill **spawns Task sub-agents inline** (one per file, `subagent_type:
  general`, model `claude-haiku-4-5`) and collects each Task's
  MetaDescription JSON output. Task spawning inherits session auth →
  subscription billing.

The `.meta` on-disk format (Description / Described-Against-Hash /
Described-At + per-method `Id:` / `Description:` blocks under `## Functions`
and `## Classes`) is unchanged from PR #21. The contract at
`scripts/parsers/contracts/meta-description-layer.schema.json` is unchanged.
v2-produced `.meta` files are forward-compatible: re-running `/smith-index
--describe` on an unchanged file is a hash-cache hit (no-op).

## Goals

1. Default backend for `/smith-index --describe` and the workflow incremental
   path is **cli** — inline Task spawning, subscription-billed.
2. Headless fallback (`--llm-backend api`, or `CLAUDE_HEADLESS=1` env var)
   preserves the v2 direct-HTTPS path so the 2am scheduler keeps working.
3. The `.meta` format, the per-method threshold default, and the
   description soft/hard caps from PR #21 are NOT changed.
4. Rule 4 checkpoint/resume continues to work end-to-end.
5. v2 tests pass; v3 adds tests for the Task-stub path, the headless
   regression, the workflow incremental path, and the hash-cache skip.

## Non-Goals / Out of Scope

- Changing the `.meta` description layout or contract schema.
- Removing the direct-API path entirely. (A future v3.1 may deprecate it;
  not in this release.)
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
- **The 2am scheduler** (`scheduler/smith-scheduler.sh`) — runs autonomous
  workflows without an interactive session; relies on the headless
  fallback.
- **Smith workflow operators** (`/smith-new`, `/smith-bugfix`,
  `/smith-debug`) — touched-method `.meta` updates now route through Task
  spawning when interactive.
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
(`run.py:1124`). Delete `--describe` CLI dispatch in
`run.py` (and any associated argparser branch). The skill prose, not
`run.py`, is the entrypoint for the `--describe` route in v3.

#### A2. Skill prose contract

The skill prose, when invoked with `--describe`, MUST:

1. Detect the backend. If `CLAUDE_HEADLESS=1` is set OR `--llm-backend api`
   is passed, shell out to the headless fallback (A4) and return its exit
   code. Otherwise proceed with the cli (Task-spawning) path.
2. Invoke the helper `scripts/parsers/describe_discover.py` (NEW — A3) to
   get a JSON list of files needing description: each entry carries
   `rel_path`, `source_hash`, `parsed` (parser output), the existing
   `.meta` description state (if any), and a `cache_hit` boolean (true
   when `described_against_hash == source_hash` and at least a module or
   one method description already exists).
3. Filter out `cache_hit` entries. Apply the `--resume` skip set from the
   most recent describe JSONL log + checkpoint (same recovery shape as
   PR #21's `run.py:1252`).
4. Batch remaining files in groups of N (default 10, configurable via
   `--batch-size`). For each batch:
   - Spawn N parallel Task tool calls in a single tool-use block, one per
     file. Each Task gets `subagent_type: "general"`, model override
     `claude-haiku-4-5`, and a prompt whose body contains:
     - The file's source.
     - The parser output (functions, classes, methods with stable ids).
     - The list of qualifying method ids (≥ threshold lines per
       `_qualifying_methods` at `meta_describe.py:220`).
     - The instruction to return a strict JSON object matching the
       MetaDescription contract at
       `scripts/parsers/contracts/meta-description-layer.schema.json`.
     - The existing module description (if `purpose_shifted=false` is
       implied by the bulk path's "preserve module if hash matched"
       rule — N/A in bulk; bulk regenerates module unconditionally,
       per `_describe` at `meta_describe.py:524`).
   - Collect each Task's JSON output. For each result, invoke
     `scripts/parsers/describe_write.py` (NEW — A3) with the
     MetaDescription JSON + `rel_path`; the helper splices into the
     `.meta` file atomically.
   - Append a Rule-4 JSONL record per file via
     `scripts/parsers/describe_checkpoint.py` (NEW — A3).
5. After every batch, persist checkpoint state (already-processed
   `rel_path` list) so `--resume` works.
6. At completion (or on Ctrl-C / Task failure), print the Rule-4 summary:
   `/smith-index --describe: N files described (N succeeded, N failed,
   N skipped) in T.Ts`.

#### A3. Python helper split

Four files; three new, two modified.

- **NEW** `scripts/parsers/describe_discover.py` — file walk (honoring
  gitignore, mirroring `walk_source_files` in `run.py`), per-file source
  hash, parser invocation, existing `.meta` description parse, `cache_hit`
  determination. CLI: `python3 describe_discover.py --root <dir> [--system
  <name>] [--threshold <n>]` → stdout JSON list. Importable as
  `discover(...)` for tests.
- **NEW** `scripts/parsers/describe_write.py` — accepts MetaDescription
  JSON on stdin (or `--input <path>`) + `--rel-path <p>` and writes the
  description block into the `.meta` (preserving non-description fields).
  Supports `--update-touched` mode: takes a subset of method ids +
  `--purpose-shifted true|false` and merges into the existing layer.
  Atomic write via temp + rename.
- **NEW** `scripts/parsers/describe_checkpoint.py` — JSONL log + checkpoint
  state. CLI: `python3 describe_checkpoint.py append --log <path>
  --record <json>` and `python3 describe_checkpoint.py save --path <path>
  --processed <rel_path>`. `python3 describe_checkpoint.py load
  --path <path>` for `--resume` callers.
- **MODIFY** `scripts/parsers/meta_describe.py` — strip the LLM call
  path. Remove `_default_haiku_call` (`:290`), the `HaikuClient`
  dependency-injection plumbing in `_describe` (`:524`),
  `describe_file` (`:452`), `update_touched` (`:482`), and the
  `update-touched` CLI entrypoint (`:666` and argparser at `:734`).
  Keep ONLY structural pieces: `MethodDescription` (`:61`),
  `MetaDescription` (`:73`), `parse_meta_descriptions` (`:102`),
  `render_description_block` (`:185`), `_qualifying_methods` (`:220`),
  and the prompt-template builders `_summarize_for_module_prompt`,
  `_build_method_prompt`, plus the `_MODULE_SYSTEM` / `_METHOD_SYSTEM`
  prompt constants (`:351` / `:358`). The prompt builders become public
  (drop the leading underscore where they are called by the new
  helpers).
- **MODIFY** `scripts/smith-index/run.py` — delete `mode_describe`
  (`:1209`), `_describe_one_file` (`:1124`), `_read_meta_text`
  (`:1106`), `_extract_hash_from_meta` (`:1113`), the `--describe` CLI
  flag and its dispatcher. The `_meta_describe` import block stays
  (other modes still use `parse_meta_descriptions` /
  `render_description_block` — see `run.py:861`).

#### A4. Headless fallback

- **NEW** `scripts/parsers/describe_headless.py` — wholesale port of the
  v2 direct-HTTPS path. Reads `ANTHROPIC_API_KEY`, posts to
  `https://api.anthropic.com/v1/messages`, writes the same `.meta`
  layout as the cli path. CLI mirrors what `mode_describe` accepts:
  `--root`, `--batch-size`, `--threshold`, `--model`, `--system`,
  `--resume`. Reuses the new helpers (`describe_discover`,
  `describe_write`, `describe_checkpoint`).
- Skill prose in `skills/smith-index/SKILL.md` shells out to this script
  when (a) `CLAUDE_HEADLESS=1` in env, OR (b) `--llm-backend api` was
  passed by the user.
- `scheduler/smith-scheduler.sh` sets `CLAUDE_HEADLESS=1` before each
  per-task dispatch. (Open question 2 — see §Open Questions.)

### Track B — Smith workflow incremental path

#### B1. Inline Task spawning in workflow skills

Modify three skill files to replace the existing CLI shell-out:

- `skills/smith-new/SKILL.md:447` — the Phase 4.5 mid-conversation
  `.meta` update step.
- `skills/smith-bugfix/SKILL.md:208` — the Phase 3.5 update step.
- `skills/smith-debug/SKILL.md:290` — the post-fix `.meta` update step.

New prose for each: "For each modified source file (`.py`, `.js`,
`.jsx`, `.ts`, `.tsx`), identify touched method ids via the helper
(`python3 scripts/parsers/describe_discover.py --rel-path <p>
--touched-only`), then spawn ONE Task call (subagent_type `general`,
model `claude-haiku-4-5`) with the touched method bodies + file
context + the instruction to return a MetaDescription JSON with ONLY
those method ids (plus a module description iff `purpose_shifted` is
true). Pipe the Task output into `python3 scripts/parsers/
describe_write.py --update-touched --rel-path <p> --purpose-shifted
<true|false>`." Each SKILL.md ships the exact prompt skeleton so the
orchestrating LLM doesn't author it from scratch.

#### B2. Headless fallback for workflows

Each workflow skill checks `CLAUDE_HEADLESS=1` first. If set, it shells
out to a thin v3 CLI wrapper that internally invokes
`describe_headless.py update-touched ...` — kept as a deprecated path
for autonomous chains started outside an interactive session (e.g., the
scheduler invoking `/smith-build` on an unattended box). This wrapper
lives at `scripts/parsers/describe_headless.py` as a subcommand
(`update-touched`), replacing the v2 `meta_describe.py update-touched`
CLI surface (`meta_describe.py:666`).

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
- Test coverage: bulk path (a full file), incremental path (single
  touched id), `purpose_shifted=true` triggers module re-description,
  `purpose_shifted=false` preserves module.

#### C2. Headless regression

- **NEW** `tests/parsers/test_describe_headless.py` — runs
  `describe_headless.py` against a fixture file with a mocked HTTP
  layer (monkey-patch `urllib.request.urlopen` or use the
  `SMITH_ANTHROPIC_API_URL` env var from `meta_describe.py:309` to
  point at a local fixture server). Verifies the written `.meta`
  matches the v2-produced golden output byte-for-byte.

#### C3. Hash-cache skip test

- **NEW** `tests/parsers/test_hash_cache_skip.py` — pre-seeds a `.meta`
  with a valid description layer matching the source hash, runs
  discovery, asserts `cache_hit=true` for that file, and asserts the
  full pipeline writes zero new bytes to that `.meta`.

#### C4. Migration

No data migration. v2 `.meta` files are forward-compatible: their
`Described-Against-Hash:` field is what enables the v3 hash-cache. The
first v3 `--describe` run on a v2 repo is a series of cache-hits — no
LLM calls, no `.meta` writes — unless source files have changed since
the v2 run.

#### C5. Documentation

- Update `docs/manifest-system.md` with a v3 architecture section
  ("Backend selection: cli vs api") explaining the inversion and the
  fallback rule. Cite skill prose as the orchestrator. Insert near the
  existing v2 `.meta` description-layer section.
- Update `CHANGELOG.md` with a v3.0.0 entry summarizing the
  architectural inversion, the helper split, and the headless
  fallback.

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
  - Hide `--describe` behind a new top-level skill while keeping the
    flag as an alias: too many surfaces for one feature.

### Decision: Skill prose is the orchestrator; Python is a toolkit

- **Decision.** The LLM driving the user's Claude Code session is the
  loop driver. Python helpers do file discovery, parser invocation,
  `.meta` I/O, and JSONL log/checkpoint — they no longer make LLM
  calls (in the cli backend path).
- **Rationale.** The Task tool is the ONLY entrypoint that inherits
  session auth → subscription billing. The Task tool is only callable
  by the orchestrating LLM. So the orchestrator MUST be the
  orchestrating LLM, not a subprocess.
- **Alternatives considered.**
  - Reverse proxy: have Python ask the orchestrator to make Task calls
    on its behalf. Not feasible — there is no Python-to-session
    callback channel.
  - SDK wrapper that pretends to be subscription-billed: doesn't
    exist; the only subscription-auth surface is the session itself.

### Decision: Retain the direct-API path as a headless fallback

- **Decision.** Ship `describe_headless.py` as a wholesale port of the
  v2 HTTPS path. The skill prose detects headless context
  (`CLAUDE_HEADLESS=1` or `--llm-backend api`) and shells out.
- **Rationale.** The 2am scheduler runs without a session (no
  interactive Claude Code) and CANNOT use Task spawning. Removing the
  API path would break autonomous workflows for repos that depend on
  the scheduler.
- **Alternatives considered.**
  - Drop the API path entirely: blocks the scheduler use case.
  - Make the scheduler launch an interactive session: launchd → claude
    `--permission-mode bypassPermissions -p` already runs Claude Code,
    but each invocation is a fresh session; Task tool semantics under
    `-p` are unverified at v3 ship time. Defer this exploration.
  - Bundle the API path into `meta_describe.py` rather than a separate
    file: muddies the structural module that the skill imports from.

### Decision: One Task per file (parallel within a batch)

- **Decision.** Default to one Task tool call per file, spawning all
  files in a batch as parallel tool-use entries in a single tool-use
  block. Batch size default 10.
- **Rationale.** Per-file granularity preserves the v2 per-file unit
  of work (one `.meta` write per success); parallel spawning leverages
  the Task tool's built-in concurrency cap (`min(16, cpu - 2)` per
  current Claude Code runtime). Per-batch retries become simpler — a
  rate-limited file can be re-queued without re-running the whole
  batch.
- **Alternatives considered.**
  - Per-method Task spawning: too granular for typical files (most
    have <20 qualifying methods); explodes Task count.
  - One Task per batch (all 10 files in one prompt): defeats the
    parallelism win; large prompts hit token caps on dense files.
  - Sequential within batch: throughput cost too high for 1000+ file
    repos.

### Decision: Trust Task runtime concurrency caps; no extra throttling

- **Decision.** Do not add per-skill rate-limit or concurrency
  throttling. Rely on the Task tool runtime's built-in cap (`min(16,
  cpu - 2)` per platform).
- **Rationale.** Adding a second throttle layer is duplicate logic and
  diverges from a future Task runtime change. Subscription rate limits
  are per-account and not currently published as constants, so any
  hand-tuned throttle would be either too aggressive (slow) or too
  loose (no help).
- **Alternatives considered.**
  - Token-bucket per minute: needs subscription-rate-limit constants
    that don't exist publicly.
  - Adaptive backoff on first 429: deferred (see Open Question 3).

### Decision: Test stub via env-var sentinel

- **Decision.** Skill prose, when `SMITH_TASK_STUB=1` is set in the
  environment, redirects Task spawning to a fixture-replay path. The
  fixture maps method ids to canned MetaDescription JSON.
- **Rationale.** Real Task spawning requires a Claude Code session,
  which CI does not have. Without a stub, the skill is untestable.
  The sentinel keeps the production prose unchanged for users — only
  tests set the env var.
- **Alternatives considered.**
  - Mock the Task tool itself (impossible — runtime is closed).
  - Skip skill-level tests and rely on helper unit tests:
    inadequate — the prose-driven loop IS the integration surface,
    and v2 already taught us prose bugs slip through helper-only
    tests.

## Hard Constraints

- The `.meta` description layer format from PR #21 is **byte-stable** in
  v3 for cache-hit cases (re-running `--describe` on unchanged source
  produces zero `.meta` writes).
- Source files are NEVER modified by any v3 path (inherits v2 invariant).
- `python3` everywhere, never `python`.
- Task spawning happens ONLY from the cli backend path; the headless
  path makes direct HTTPS calls only.
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
2. `/smith-index --describe --llm-backend api` invoked in the same session
   shells out to `describe_headless.py` and uses `ANTHROPIC_API_KEY`.
3. `/smith-index --describe` invoked with `CLAUDE_HEADLESS=1` in env
   (without `--llm-backend api`) shells out to `describe_headless.py`.
4. `/smith-new`, `/smith-bugfix`, `/smith-debug` touched-method `.meta`
   updates in an interactive session spawn one Task per modified file;
   in `CLAUDE_HEADLESS=1` context, shell out to
   `describe_headless.py update-touched`.
5. Hash-cache hit: re-running `--describe` on a file whose source hash
   matches `described_against_hash` writes zero bytes to its `.meta`.
6. Rule 4 checkpoint/resume: interrupting `--describe` mid-run and
   re-invoking with `--resume` skips already-completed files and resumes
   from the checkpoint.
7. v2-produced `.meta` files are read correctly by v3
   (`parse_meta_descriptions` round-trips identically — no schema bump).

### Performance

- Per-file Task latency target: < 30 seconds wall clock (Haiku is fast;
  spawn overhead is < 1s in current runtimes).
- Headless fallback retains v2 performance: 5–10s per Haiku call.
- Skill orchestration overhead (prose-driven loop bookkeeping): < 10% of
  total wall-clock time on a 100-file run.

### Quality

- All PR #21 tests still pass unchanged.
- New tests pass: Task-backend stub (C1), headless regression (C2),
  hash-cache skip (C3).
- `meta_describe.py` byte size shrinks substantially (LLM-call code +
  the `update-touched` CLI are removed; only structural code remains).
- No clarification-pending markers in any v3 spec, plan, or task; all
  ambiguity is surfaced in §Open Questions.

## Open Questions

1. **Long-term fate of the headless paths.** Should `describe_headless.py`
   and the workflow-shell-out via `describe_headless.py update-touched`
   be removed in some future v3.1, or kept indefinitely? Keeping them
   permanently means anyone with `ANTHROPIC_API_KEY` can opt out of
   subscription billing forever; removing them forces all use to
   interactive sessions and breaks the scheduler unless the scheduler
   acquires session-launching capability.
2. **`CLAUDE_HEADLESS` ownership.** Should
   `scheduler/smith-scheduler.sh` set `CLAUDE_HEADLESS=1` automatically
   for every scheduled task, OR should the user set it explicitly in
   the launchd plist / shell profile? Should the env var name follow
   an existing convention (e.g., `SMITH_HEADLESS=1`,
   `CLAUDE_CODE_HEADLESS=1`)? Naming choice affects future skills and
   the published contract.
3. **Rate-limit retry strategy.** When a Task call fails with a
   subscription rate-limit error (semantically distinct from API 429),
   should the skill (a) retry with exponential backoff in-place, (b)
   re-queue the file for the next batch, or (c) abort with a clear
   error and surface a "try again in N minutes" message? Subscription
   rate limits reset on different cadences than API limits, so the
   right behavior is non-obvious.
4. **Parallel vs sequential within a batch.** The brief says spawn 10
   Tasks per batch as parallel tool-use entries in one block. Parallel
   is faster but a single failed Task in the middle of a batch is
   harder to retry surgically. Should the skill prose default to
   parallel (and accept "lose 1 file, succeed 9" as the failure mode)
   OR sequential within a batch (slower but per-file error handling is
   trivial)?
5. **Per-method Task spawning escape hatch.** "One Task per file"
   works for typical files but a file with 100+ qualifying methods
   produces a prompt large enough to risk token-cap truncation. Should
   the skill split into per-method Tasks above some threshold (e.g.,
   > 30 qualifying methods)? What's the default?
6. **Pre-flight cost estimate.** Should the skill display a pre-flight
   cost estimate before running (e.g., "About to describe 1,214 files
   in 122 batches; estimated runtime 35 min, estimated subscription
   token cost ~X")? Subscription cost is opaque — but file count +
   batch count is meaningful even without a dollar figure. Include or
   omit?
7. **Test stub fidelity.** The Task-stub fixture replays canned JSON
   keyed by method id. If a method id is missing from the fixture,
   should the stub (a) fail loudly, (b) return a synthetic
   description, or (c) skip the method? Choice affects how brittle
   test golden files are to source changes.

## Assumptions

- The Task tool's `subagent_type: general` accepts a `model` override
  parameter and accepts `claude-haiku-4-5` as a valid value. (If the
  override isn't supported, the spawned sub-agent defaults to whatever
  the session's primary model is — still subscription-billed, but
  potentially more expensive per call.)
- Parallel Task spawning within a single tool-use block is supported by
  the current Claude Code runtime (the `task-router.sh` and
  `context-loader.sh` hooks don't interfere with parallel sub-agent
  fan-out).
- `CLAUDE_HEADLESS` is not currently used by any other Claude Code
  surface. (To be verified during plan phase — naming conflict would
  require renaming.)
- The Anthropic Messages API contract used by the v2 path
  (`https://api.anthropic.com/v1/messages`, `anthropic-version`
  header from `meta_describe.py:46`) remains valid at v3 ship time.
- The current `_qualifying_methods` threshold (5 lines, per
  `meta_describe.py:220`) is still the right gate — not revisited.

## References

- PR #19 — `19-manifest-system` — initial manifest scaffolding (merged
  2026-05-21).
- PR #21 — `20-manifest-fixes` — the v2 description layer; spec at
  `specs/20-manifest-fixes/spec.md`.
- PR #22 — install-path-fallback — install-script bugfix; unrelated to
  billing but landed in the same window.
- `scripts/parsers/meta_describe.py` (PR #21) — the file v3 strips down.
- `scripts/smith-index/run.py` (PR #21) — the file v3 removes
  `mode_describe`/`_describe_one_file` from.
- `scripts/parsers/contracts/meta-description-layer.schema.json` — the
  contract unchanged in v3.
- `skills/smith-index/SKILL.md`, `skills/smith-new/SKILL.md`,
  `skills/smith-bugfix/SKILL.md`, `skills/smith-debug/SKILL.md` — the
  four skill files modified in v3.
- `scheduler/smith-scheduler.sh` — the headless invoker.
- Global rule: Rule 4 (Checkpoint/Resume for Long-Running Processes) —
  drives the JSONL log + checkpoint requirement in A2 and the new
  `describe_checkpoint.py` helper.
