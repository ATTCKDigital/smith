---
feature: 23-task-llm-backend
artifact: quickstart.md
created: 2026-06-03
---

# Quickstart — v3 Description Backend

Three end-to-end scenarios exercise the v3 Task-based LLM backend.
Each scenario lists the user-visible commands, the internal control
flow, and the expected outcome.

A fourth section covers the local test stub for hermetic CI runs.

## Scenario A — Interactive `/smith-index --describe`

**Persona.** A repo owner working on the `armory` project in an
active Claude Code session.

**Trigger.**

```
/smith-index --describe
```

**Expected control flow.**

1. Skill prose detects `CLAUDE_HEADLESS` is unset and
   `--llm-backend api` was not passed → cli backend chosen.
2. Prose runs:
   ```bash
   python3 scripts/parsers/describe_discover.py --root . --threshold 5
   ```
   Output: a JSON array of 1,214 entries (the full repo). Of these,
   903 carry `cache_hit=true` (existing valid descriptions). 311
   remain.
3. Prose prints a pre-flight estimate:
   ```
   /smith-index --describe: backend=cli (default)
   311 files to describe in 32 batches of 10. Estimated runtime ~16 min.
   ```
4. Operator approval prompt (interactive):
   ```
   Batch 1: 10 files (of 311 total)
     Approve batch? [Y/n/q/list]:
   ```
   User presses Enter → batch approved.
5. Prose emits a single tool-use block with 10 parallel `Task` tool
   calls — `subagent_type: general`, `model: claude-haiku-4-5`,
   per-file prompts assembled via
   `describe_write.py build-prompt`.
6. Each Task returns a JSON envelope matching
   `task-llm-output.schema.json`. Prose pipes each into:
   ```bash
   python3 scripts/parsers/describe_write.py \
     --rel-path <p> --root . --hash <h>
   ```
7. Per-file JSONL records appended via
   `describe_checkpoint.py append`. Checkpoint state saved per file.
8. Loop continues for 31 more batches.
9. Final summary (Rule 4):
   ```
   /smith-index --describe: 311 files described
   (succeeded=308 failed=2 skipped=1) in 14m22.1s
   ```
   `.smith/index/.smith-index-describe-checkpoint.json` is deleted
   on clean exit.

**Billing outcome.** Every Task call billed against the user's
Claude Code subscription. The `ANTHROPIC_API_KEY` env var was NOT
consulted (and need not be set).

**Verification.**

- `~/.smith/logs/smith-index-describe-<run-ts>.jsonl` exists; each
  record has `backend: "task"`.
- 308 `.meta` files under `.smith/index/files/` were modified; their
  `Described-At:` timestamp falls within the run window; their
  `Described-Against-Hash:` matches the current `sha256_first_4kb`
  of the corresponding source file.
- The 2 `failed` records carry an `error` field with the Task's
  error text.

## Scenario B — Scheduler-triggered headless run

**Persona.** The 2am macOS launchd agent invoking
`scheduler/smith-scheduler.sh`. There is no interactive Claude Code
session; the scheduler launches a fresh `claude -p` per task.

**Trigger.** The scheduler's per-task subshell runs (with the
follow-up edit recommended in plan §Migration applied):

```bash
(
    cd "$PROJECT_DIR" && \
    CLAUDE_HEADLESS=1 "$CLAUDE_BIN" \
        --model "$CLAUDE_MODEL" \
        --permission-mode bypassPermissions \
        -p "/smith-index --describe"
)
```

**Expected control flow.**

1. The freshly-launched `claude -p` session loads the
   `/smith-index` skill.
2. Skill prose checks `CLAUDE_HEADLESS=1` → matches → shells out:
   ```bash
   python3 ~/.smith/scripts/describe_headless.py
   ```
   (Or `scripts/parsers/describe_headless.py` in a repo-dev layout.)
3. `describe_headless.py` runs the v2-equivalent loop:
   - `describe_discover.py` for the file walk.
   - For each batch, calls `_default_haiku_call` (ported from v2)
     with `ANTHROPIC_API_KEY` from env.
   - `describe_write.py` for each result.
   - `describe_checkpoint.py append` per file; records carry
     `backend: "api"`.
4. Exit code propagated back through the skill prose.

**Billing outcome.** Every HTTPS request to
`api.anthropic.com/v1/messages` billed against
`ANTHROPIC_API_KEY`'s account. No subscription cost.

**Verification.**

- `~/.smith/logs/smith-index-describe-<run-ts>.jsonl` exists; each
  record has `backend: "api"`.
- The on-disk `.meta` output is byte-equivalent to what v2's
  `mode_describe` would have produced for the same inputs
  (verified by `test_describe_headless.py`).
- The scheduler's log shows the task as `completed` and the
  per-task subshell exited 0.

## Scenario C — Workflow incremental during a fix

**Persona.** A developer in an active Claude Code session asks
`/smith-bugfix` to fix a method in `services/api/payments.py`.

**Trigger.**

```
/smith-bugfix
> Fix the rounding bug in apply_discount that drops cents on
> three-decimal inputs.
```

**Expected control flow (Phase 3.5 only — earlier phases unchanged).**

1. `/smith-bugfix` Phase 3 fixes the source. The save hook updates
   the `Hash:` line in `.meta` but the description layer (per PR
   #21) still bears the OLD `Described-Against-Hash:`. The fix
   touched the `apply_discount` method id (`abc1234567890def`)
   and added a new helper method `_round_half_even`
   (`f1e2d3c4b5a69870`).
2. Phase 3.5 prose checks `CLAUDE_HEADLESS` (unset) → cli path.
3. Prose computes:
   - Touched ids: `abc1234567890def,f1e2d3c4b5a69870`.
   - `purpose_shifted`: false (no new public exports; method count
     unchanged > 50% threshold).
4. Prose runs:
   ```bash
   python3 ~/.smith/scripts/describe_discover.py \
     --rel-path services/api/payments.py \
     --touched-only \
     --touched-ids abc1234567890def,f1e2d3c4b5a69870
   ```
   Output: a single-entry JSON array with the file's parser output,
   qualifying methods, and the existing description layer.
5. Prose spawns ONE Task — `subagent_type: general`,
   `model: claude-haiku-4-5`, prompt built from the discover output
   restricted to the touched ids + the existing module description
   (for preservation if `purpose_shifted=false`).
6. Task returns:
   ```json
   {
     "status": "ok",
     "module_description": null,
     "method_descriptions": [
       {"method_id": "abc1234567890def",
        "description": "Applies the discount percentage to the line total, rounding half-even to cents to avoid sub-cent drift on three-decimal inputs."},
       {"method_id": "f1e2d3c4b5a69870",
        "description": "Helper that performs IEEE 754 round-half-to-even on a Decimal value to a target precision."}
     ],
     "errors": []
   }
   ```
7. Prose pipes into:
   ```bash
   echo '<task-output-json>' | \
     python3 ~/.smith/scripts/describe_write.py update-touched \
       --rel-path services/api/payments.py \
       --purpose-shifted false
   ```
8. The writer:
   - Reads the existing `.meta` description layer.
   - Preserves the module description (purpose_shifted=false).
   - Overwrites the two touched method ids.
   - Preserves all other method descriptions verbatim.
   - Recomputes `Described-Against-Hash:` to the current source hash.
   - Updates `Described-At:` to now.
   - Atomically writes the new `.meta`.

**Billing outcome.** The Task call billed against the developer's
subscription.

**Verification.**

- `.smith/index/files/services/api/payments.py.meta` shows the
  new `Described-Against-Hash:` matching the current source.
- The two touched method descriptions reflect the fix's intent.
- All untouched method descriptions are byte-identical to before.
- The session log contains one line acknowledging the description
  update.

## Scenario D — Local test stub

**Persona.** A maintainer running the v3 test suite locally or in
CI. No Claude Code session, no API key.

**Trigger.**

```bash
export SMITH_TASK_STUB=1
cd /path/to/smith-repo
python3 -m pytest tests/parsers/test_task_backend_stub.py -v
```

**Expected control flow.**

1. The test sets up a small fixture project under
   `tests/fixtures/headless-fixture-project/` with one parsable
   Python file containing three qualifying methods.
2. The test invokes the orchestrator's helper sequence directly
   (bypassing the skill prose, since prose can't be tested in
   pytest):
   ```python
   discover_output = subprocess.check_output([
       "python3", "scripts/parsers/describe_discover.py",
       "--root", str(fixture_dir)
   ])
   entries = json.loads(discover_output)
   for entry in entries:
       if entry["cache_hit"]:
           continue
       subprocess.run([
           "python3", "scripts/parsers/describe_write.py",
           "--from-stub", "tests/fixtures/task-stub-responses.json",
           "--rel-path", entry["rel_path"],
           "--root", str(fixture_dir),
           "--hash", entry["source_hash"]
       ], check=True)
   ```
3. Each `describe_write.py --from-stub` invocation reads the
   pre-canned MetaDescription from the fixture and writes the
   `.meta`.
4. Test compares the resulting `.meta` to a committed golden file
   via `filecmp.cmp(shallow=False)`.

**Acceptance.**

- Test passes deterministically (no network, no LLM).
- No API key required.
- The same fixture file (`tests/fixtures/task-stub-responses.json`)
  feeds both the bulk test and the incremental test (the
  incremental test uses a single key, the bulk test uses multiple).

**Refreshing fixtures.** When source files in the fixture project
change, the maintainer re-runs the live cli backend once (in an
interactive session) and copies the resulting `.meta` JSON layer
into `task-stub-responses.json` keyed by the new `rel_path`. The
test then re-passes.

## Common troubleshooting

- **"ANTHROPIC_API_KEY not set" in an interactive session.**
  The cli backend doesn't need the key. This error means the
  skill incorrectly routed to the headless backend. Check that
  `CLAUDE_HEADLESS` is unset and `--llm-backend api` was not
  passed. If both are clear and you still see the error, the
  Task tool was not available (e.g. running under a stripped-down
  CLI launch) — confirm `claude --help` lists `Task` among the
  built-in tools.
- **All files show `cache_hit=true` but you expected new
  descriptions.** The hash matches because no source changed since
  the last run. Use `--no-cache` (NOT IMPLEMENTED in v3 — open a
  follow-up issue) or delete the affected `.meta` files to force
  regeneration.
- **Resume isn't skipping the right files.** The checkpoint state
  file is at `.smith/index/.smith-index-describe-checkpoint.json`;
  the most-recent JSONL log is at
  `~/.smith/logs/smith-index-describe-*.jsonl`. The union of
  `processed_files` and `ok`-status JSONL records is what
  `--resume` skips. If you've manually edited `.meta` files
  since the run, the checkpoint will not detect that and you may
  need to remove the checkpoint file before resuming.
