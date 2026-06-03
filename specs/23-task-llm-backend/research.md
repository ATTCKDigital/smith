---
feature: 23-task-llm-backend
artifact: research.md
created: 2026-06-03
---

# Research — Task-based LLM Backend

This file gathers the open technical questions identified during the
spec phase and resolves each one with enough specificity that the
implementation can proceed without re-investigation. Cross-references
to v2 code use absolute paths in the smith-repo working tree.

## §1 — Task tool semantics

### What the Task tool is

Claude Code exposes a `Task` tool to the orchestrating LLM in any
interactive session. Invoking it spawns a sub-agent process that
inherits the session's authentication context. From a billing
perspective, every Task call counts against the user's subscription
(or, in API-keyed sessions, the session's API key) — there is no way
for a Task call to be billed against a separate identity. This is the
property the v3 design depends on.

### Parameters

The tool accepts (at minimum):

- `subagent_type` — a string identifying the sub-agent profile. The
  generic profile `"general"` is always available and is the right
  choice for v3 (one-shot description prompts; no need for a
  specialised profile).
- `prompt` — the user-message body sent to the sub-agent. The
  orchestrating LLM is responsible for assembling this string.
- `model` (optional override) — when present, the sub-agent uses the
  specified model instead of the session's primary. v3 always sets
  this to `claude-haiku-4-5` (parity with v2's
  `DEFAULT_MODEL` at `meta_describe.py:48`).

Other parameters (timeouts, max-tokens, system prompts) exist but are
not used in v3 — Haiku's default budget is sufficient for the
description prompt size.

### Parallelism — fan-out within one tool-use block

The Claude Code runtime supports parallel sub-agent fan-out: when the
orchestrating LLM emits multiple `Task` tool calls inside a single
tool-use block (i.e. one model turn's output contains N parallel tool
invocations), the runtime runs them concurrently up to a platform cap
of `min(16, cpu - 2)`. This is the mechanism v3 uses to parallelise
per-file description generation within a batch.

If the orchestrating LLM emits N Task calls across multiple turns,
they run sequentially — only the single-tool-use-block form triggers
fan-out. The skill prose in `plan.md` §Component Design 5 calls out
this constraint explicitly so the LLM doesn't accidentally spread
Task calls across multiple turns.

### Output shape

Each Task returns a single text payload (an LLM response). The v3
prompt instructs the sub-agent to return strictly JSON matching
`contracts/task-llm-output.schema.json`. The orchestrator parses the
text payload as JSON. If parsing fails, the file is recorded as
`failed` and processing continues.

### Failure modes

- **Sub-agent error.** The Task call itself returns an error
  payload (e.g. model timeout, rate limit). The orchestrating LLM
  catches this and records a failed JSONL entry.
- **Malformed JSON.** The sub-agent returned text that did not parse
  as JSON. Same handling — failed entry, continue. v2 has a
  brace-bounded fallback parser (`_safe_json_object` at
  `meta_describe.py:625-656`) that the v3 writer SHOULD reuse for
  resilience; `describe_write.py` carries this helper over.
- **Schema-valid but wrong content.** e.g. the sub-agent returned
  `{"status": "ok", …}` but with method ids that don't appear in the
  parser output. The writer discards unknown ids (mirrors v2 stale-id
  drop at `meta_describe.py:584-588`).

## §2 — Skill prose orchestration patterns

### The "loop until done" pattern

Claude Code skill markdown is read once at skill invocation and the
LLM follows it as natural-language instructions. There is no
imperative `while` loop primitive — the prose tells the LLM the
termination condition and the LLM decides when to stop. Three patterns
are in use across the smith-repo:

1. **Bounded-batch pattern.** Skill prose says "for each batch of
   N items, do X". The LLM iterates by emitting one tool-use block
   per batch. Termination: when the discovery output is exhausted
   OR a `q` operator input was seen.
2. **Checkpoint-pull pattern.** Skill prose says "load the resume
   set, filter the work list, then proceed". The LLM filters BEFORE
   iterating, not during — avoids re-reading the checkpoint per item.
3. **Failure-bounded pattern.** "If more than N consecutive batches
   fail, abort and surface the error". Used to prevent runaway cost
   on a broken backend.

v3 uses all three.

### Infinite-recursion risk

A naive prose-driven loop can loop forever if the termination check
is wrong. v3 mitigates by:

- Always loading the full work list upfront (discovery returns the
  complete array, not a paginated cursor).
- Recording each processed file in the checkpoint state BEFORE
  attempting the next batch — so a re-entry after Ctrl-C never
  reprocesses.
- Bounding the loop by `len(work_list) / batch_size` iterations
  with a `+5` safety margin documented in the prose.

### Subagent vs main-agent state

The Task sub-agent does NOT share the orchestrator's working memory.
Each Task gets exactly the prompt string passed in `prompt`. This
means the full file source, parser output, and method-id list must
be passed in every Task — no "by reference" pattern. This drives the
prompt-size estimate in §6 below.

## §3 — `CLAUDE_HEADLESS` detection convention

### Naming choice

Spec Open Question 2 asks whether the env var should be
`CLAUDE_HEADLESS`, `SMITH_HEADLESS`, or `CLAUDE_CODE_HEADLESS`.
Resolution (plan-time): use `CLAUDE_HEADLESS` (matches the spec text
and the existing convention in `claude -p` invocations where Claude
Code is running non-interactively). Naming consistency with the
broader Claude Code ecosystem is more important than a smith-prefixed
custom name.

### Where it should be set

- **The 2am scheduler** (`scheduler/smith-scheduler.sh`) is the
  canonical headless caller. As of this plan, the scheduler does
  NOT set `CLAUDE_HEADLESS=1` — the per-task subshell at line 215
  inherits the parent env only. Plan recommends adding
  `CLAUDE_HEADLESS=1` to the env block of the subshell invocation:
  ```bash
  (
      cd "$PROJECT_DIR" && \
      CLAUDE_HEADLESS=1 "$CLAUDE_BIN" \
          --model "$CLAUDE_MODEL" \
          --permission-mode bypassPermissions \
          -p "/smith-queue process $FILENAME"
  )
  ```
  This edit is deferred to a follow-up per plan §Migration.
- **Manual CI invocations.** Users running `/smith-index --describe`
  in CI without a session should `export CLAUDE_HEADLESS=1` in their
  CI config.
- **Interactive sessions.** Never set; the cli backend is the default.

### Alternative — auto-detect

A more invasive approach is to detect headlessness automatically (no
tty + no Task tool available). v3 does NOT do this — the env var is
explicit and overridable. Auto-detection is left as a v3.1 candidate.

## §4 — Task spawning concurrency caps

The Claude Code runtime caps parallel sub-agents at `min(16, cpu - 2)`
per the documented platform behavior. On an 8-core machine, that's 6
concurrent Tasks; on a 14-core machine, 12. The v3 default
`--batch-size 10` is calibrated for the 8-core common case — at most
6 of 10 Tasks run concurrently and the remaining 4 queue.

A future tuning pass might read `os.cpu_count()` at runtime and set
the batch size to `min(16, cpu - 2)` automatically. v3 leaves it
fixed at 10 for predictability.

### Backpressure

When the cap is reached, the runtime queues additional Task calls in
the same tool-use block. The orchestrating LLM does not see the
queueing — it just waits for all N Task results before continuing.
This means batch latency is dominated by `ceil(N / cap) * per-task`.

## §5 — Prompt design for description Tasks

### Structured-output discipline

v2 prompts ask Haiku to return either a plain string (module) or a
JSON object (methods). v3 unifies — every Task returns a single JSON
envelope matching `task-llm-output.schema.json`:

```json
{
  "status": "ok",
  "module_description": "…",
  "method_descriptions": [
    {"method_id": "…", "description": "…"},
    …
  ],
  "errors": []
}
```

This simplifies the orchestrator: one parse path, one error
classification.

### Prompt size estimate

The discover output for one file carries:

- File source (variable; typical 5–50KB for parsable files).
- Parser output JSON (typical 1–5KB).
- Qualifying method id list (≤ 30 entries for typical files).
- Existing module description (incremental path only; ≤ 240 bytes).

Total prompt body: typically 10–60KB. Haiku's 200K context handles
this trivially. Large files (> 200KB source) MAY exceed; spec Open
Question 5 raises the per-method-split escape hatch — v3 defers and
fails-loud (a TooLargeForBatch error code reported as a `failed`
entry).

### Fallback parsing if JSON malformed

The writer carries forward v2's `_safe_json_object` helper
(`meta_describe.py:625-656`) — strip code fences, try `json.loads`,
fall back to brace-bounded slice. If still unparseable, record
`failed` and continue.

## §6 — Headless fallback parity

### Byte-equivalence requirement

The headless path MUST produce byte-equivalent `.meta` output to v2
for the same input. This is verified by `test_describe_headless.py`
against committed golden files.

Sources of potential drift:

- Soft-cap truncation logic (`_truncate` at
  `meta_describe.py:431-446`) — port verbatim.
- ISO timestamp format (`_iso_now` at `meta_describe.py:89-90`) —
  port verbatim.
- SHA-256 hex computation — port verbatim.
- JSONL log record keys — port verbatim PLUS the new `backend`
  field (data-model.md §4). v2 readers ignore unknown keys, so the
  addition is backward-compatible.

### Tests

`test_describe_headless.py` uses `SMITH_ANTHROPIC_API_URL` to
redirect HTTP to a local fixture (parity with v2 mechanism at
`meta_describe.py:309`). The fixture server returns canned Anthropic
Messages API responses (one per prompt template). Golden `.meta`
files committed at `tests/fixtures/headless-fixture-project/
golden/.meta` are compared with `filecmp.cmp(shallow=False)`.

## §7 — Test stub mechanism

### Why a stub is needed

Real Task spawning requires a Claude Code interactive session. CI
runs without one. To test the orchestration prose without a session,
v3 introduces a sentinel env var `SMITH_TASK_STUB=1`.

### Sentinel-driven branch

The skill prose includes:

```
If SMITH_TASK_STUB=1 is set, instead of spawning Task calls,
invoke `python3 describe_write.py --from-stub <fixture-path> …`.
```

The `--from-stub` subcommand reads a fixture file mapping `rel_path`
→ MetaDescription JSON and writes the `.meta` the same way as the
live path. The orchestrator's batching, JSONL logging, and checkpoint
logic all run normally — only the LLM call is replaced.

### Fixture format

`tests/fixtures/task-stub-responses.json`:

```json
{
  "scripts/parsers/meta_describe.py": {
    "module_description": "Shared LLM description layer for Smith Manifest v2.",
    "method_descriptions": [
      {"method_id": "abc1234567890def", "description": "Parses .meta description blocks; tolerant of v1 .meta missing the description layer."},
      ...
    ]
  },
  ...
}
```

### Missing-key behavior

Spec Open Question 7 asks: missing id → fail loud, synthetic, or
skip? Resolution: **fail loud** (`describe_write.py --from-stub`
exits 4 with a message naming the missing rel_path). This keeps
golden tests honest — a source change that adds a method ALSO
requires a fixture update.

## §8 — Concurrent-session safety

The plan's risk R7 (concurrent describe runs) is mitigated via the
existing `.smith/vault/active-workflows/` mechanism. The skill prose
checks for an active `describe` entry before starting:

```bash
if [ -f .smith/vault/active-workflows/describe ]; then
  echo "Another describe run is in progress. Use --resume to continue."
  exit 1
fi
mkdir -p .smith/vault/active-workflows
touch .smith/vault/active-workflows/describe
trap "rm -f .smith/vault/active-workflows/describe" EXIT
```

This is consistent with the global rule the user's `MEMORY.md` notes
about concurrent sessions.

## §9 — Why `--describe` stays on `/smith-index`

Spec Decision 1 lists this. Research note: the alternative ("new
`/smith-describe` skill") was reviewed during plan and rejected for
the same reasons — discoverability and docs/muscle-memory cost. No
new evidence emerged.

## §10 — Open Questions reconciliation

The seven open questions from spec.md are addressed as follows in
this plan:

| OQ | Topic | Plan resolution |
|---|---|---|
| 1 | Long-term fate of headless paths | Keep indefinitely in v3; revisit in v3.1. Documented in CHANGELOG. |
| 2 | `CLAUDE_HEADLESS` ownership and naming | Use `CLAUDE_HEADLESS=1`; scheduler edit deferred to follow-up PR. Documented in plan §Migration. |
| 3 | Rate-limit retry strategy | Per-file retry once with 5s sleep, then mark failed. Re-queue is the user's job via `--resume`. |
| 4 | Parallel vs sequential within a batch | Default parallel (per spec text). Failure mode = "lose K, succeed N-K" with per-file failed records. |
| 5 | Per-method split escape hatch | Deferred to v3.1. v3 fails loud on TooLargeForBatch. |
| 6 | Pre-flight cost estimate | Print file count + batch count BEFORE starting (no dollar figure). Documented in skill prose Step 1. |
| 7 | Test stub missing-key behavior | Fail loud (exit 4). Documented in §7 above. |

## §11 — References

- `scripts/parsers/meta_describe.py` (PR #21).
- `scripts/smith-index/run.py:1100-1450` (PR #21).
- `scripts/parsers/contracts/meta-description-layer.schema.json` (PR #21).
- `specs/19-manifest-system/contracts/parser-output.schema.json` (PR #19).
- `scheduler/smith-scheduler.sh:215` — the per-task subshell where
  `CLAUDE_HEADLESS=1` should be added in a follow-up PR.
- Global CLAUDE.md Rule 4 — drives the checkpoint/log/resume design.
