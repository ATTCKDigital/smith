# Requirements Checklist — 23-task-llm-backend

Quality gate for the v3 Task-based LLM backend spec. Each item is a binary
yes/no. Strike-through with a leading `~~` when intentionally waived; add a
one-line waiver justification on the next line.

## Architectural inversion is unambiguous

- [ ] Spec explicitly names "the orchestrating LLM in the session" as the
      new driver and "Python helpers" as the toolkit.
- [ ] Spec explains WHY a Python subprocess cannot use the Task tool (no
      session-auth callback channel).
- [ ] Spec cites the v2 file:line locations being replaced or removed —
      at minimum `run.py:1209` (`mode_describe`), `run.py:1124`
      (`_describe_one_file`), `meta_describe.py:290`
      (`_default_haiku_call`), `meta_describe.py:452` (`describe_file`),
      `meta_describe.py:482` (`update_touched`), and `meta_describe.py:666`
      (`_cli_update_touched`).
- [ ] Spec confirms `.meta` format and the contract schema are byte-stable
      and the per-method threshold from PR #21 is unchanged.

## Track A — `/smith-index --describe` skill-ification

- [ ] Spec keeps `--describe` as a flag of `/smith-index` (no new skill).
- [ ] Spec specifies the four Python helpers (NEW: `describe_discover.py`,
      `describe_write.py`, `describe_checkpoint.py`,
      `describe_headless.py`; MODIFY: `meta_describe.py`, `run.py`).
- [ ] Spec enumerates EXACTLY which symbols stay in `meta_describe.py`
      (MetaDescription, MethodDescription, parse_meta_descriptions,
      render_description_block, _qualifying_methods, prompt builders).
- [ ] Spec defines the cli path: batch size N (default 10), parallel Task
      spawning in one tool-use block, per-file Task with `subagent_type:
      general` and model `claude-haiku-4-5`.
- [ ] Spec defines the prompt contract: source + parser output +
      qualifying-method ids + instruction to return MetaDescription JSON
      matching the existing schema.
- [ ] Spec defines the headless trigger: `CLAUDE_HEADLESS=1` env var OR
      `--llm-backend api` flag → shells out to `describe_headless.py`.

## Track B — Workflow incremental path

- [ ] Spec names all three workflow SKILL.md files and the exact line
      numbers of the v2 shell-out being replaced
      (`smith-new/SKILL.md:447`, `smith-bugfix/SKILL.md:208`,
      `smith-debug/SKILL.md:290`).
- [ ] Spec specifies inline Task spawning (single Task per modified file
      with touched method bodies) for interactive sessions.
- [ ] Spec specifies the headless fallback for workflows via
      `describe_headless.py update-touched ...` when `CLAUDE_HEADLESS=1`.
- [ ] Spec retains the v2 `purpose_shifted` heuristic semantics.

## Track C — Tests, migration, docs

- [ ] Spec specifies a `SMITH_TASK_STUB=1` env-var sentinel and a fixture
      file path for canned MetaDescription JSON keyed by method id.
- [ ] Spec specifies a headless-regression test that monkey-patches the
      HTTPS layer or uses `SMITH_ANTHROPIC_API_URL` to redirect.
- [ ] Spec specifies a hash-cache skip test that verifies zero `.meta`
      writes on a cache-hit file.
- [ ] Spec confirms no data migration: v2 `.meta` files are forward-
      compatible.
- [ ] Spec lists `docs/manifest-system.md` and `CHANGELOG.md` as docs to
      update.

## Hard constraints / non-goals stated

- [ ] Source files never modified — restated as a v3 invariant inherited
      from v2.
- [ ] `python3` only.
- [ ] The contract schema at
      `scripts/parsers/contracts/meta-description-layer.schema.json` is
      explicitly unchanged.
- [ ] Other `/smith-index` modes are explicitly out of scope.
- [ ] Per-method threshold + description soft/hard caps from PR #21 are
      explicitly out of scope.
- [ ] The `.specify/systems/` path-resolver tier is explicitly out of
      scope.

## Acceptance criteria are testable

- [ ] Each functional criterion names a concrete invocation
      (interactive `--describe`, `--llm-backend api`, `CLAUDE_HEADLESS=1`,
      `/smith-new`/`-bugfix`/`-debug` touched-method update, hash-cache,
      `--resume`, v2 forward-compat).
- [ ] Performance targets are numeric (<30s per-file Task latency, <10%
      orchestration overhead, 5–10s headless per-call).
- [ ] Quality criteria reference test names and the `meta_describe.py`
      shrinkage.

## Open questions surface real ambiguity

- [ ] At least 6 open questions are listed.
- [ ] Every open question is genuinely ambiguous — the spec does NOT
      already answer it elsewhere.
- [ ] No `[NEEDS CLARIFICATION]` markers appear in the spec body.
- [ ] The headless-fate, env-var-naming, rate-limit, parallelism,
      per-method-spawning, and pre-flight-cost questions from the brief
      are all captured.

## Spec hygiene

- [ ] Frontmatter is complete and accurate (feature, branch, created,
      status, builds_on).
- [ ] Spec length is between 400 and 600 lines.
- [ ] No code (no SKILL.md edits, no `.py` files written, no `.meta`
      files written).
- [ ] No files modified outside `specs/23-task-llm-backend/`.
- [ ] References section names the v2 PRs, the v2 files being changed,
      and the contract schema.
