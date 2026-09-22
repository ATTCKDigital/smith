---
feature: 60-activity-dashboard
primary_system: cross-system
branch: 60-activity-dashboard
status: tasks-generated
generated: 2026-09-22
---

# Tasks: `/smith-activity` — Local Real-Time Smith Activity Audit Dashboard

Source artifacts: [`spec.md`](./spec.md) (FR-1..FR-63, SC-1..SC-21, US-1..US-10,
OOS-1..OOS-8) · [`plan.md`](./plan.md) (§Phased ordering is the dependency
authority) · [`data-model.md`](./data-model.md) ·
[`quickstart.md`](./quickstart.md) · [`contracts/`](./contracts/) ·
[`questions.md`](./questions.md) (authoritative where it differs from
`research.md`).

**All file paths are relative to the worktree root
`/private/tmp/smith-activity-dashboard`.** Work exclusively in that worktree.

---

## Binding constraints every task inherits

Read these once; they are not repeated per task.

1. **OOS-8 — no workflow-skill edits of any kind.** `skills/smith-new/`,
   `skills/smith-bugfix/`, `skills/smith-debug/`, `skills/smith-build/`,
   `skills/smith-finish/` are READ-ONLY inputs, documentation fixes included.
2. **`hooks/workflow_summary_lib.py` is imported and called, NEVER edited**
   (FR-33/FR-36, D-6).
3. **`.smith/vault/active-workflows/` is never written by anything this
   feature ships** except `/smith-activity`'s own marker, and that only
   through `create-active-workflow.sh` / `clear-active-workflow.sh` (FR-8,
   FR-44).
4. **No `timeout` / `gtimeout`.** Neither exists on this machine. Bounds come
   from `curl --max-time` / `--connect-timeout`, or `subprocess(timeout=…)`.
   Never shell out to `timeout`.
5. **No `/dev/tcp`.** Unavailable under `zsh` here. Port probing uses `nc` or
   `python3`.
6. **Python 3.8 stdlib only.** No pip, no npm, no Node, no virtualenv.
7. **CI runs flat `tests/*.test.sh` ONLY**
   (`.github/workflows/test-install.yml:58`). No `find`, no recursion. Every
   Python unit test must be reachable from a flat `*.test.sh` wrapper or it
   gates nothing (FR-54/D-8/SC-16).
8. **No `.smith/config.json` exists in this worktree**, so `quality.test` /
   `lint` / `typecheck` / `coverage` are all absent. The build's Phase 3 uses
   the legacy fallback; the real test commands are `bash tests/<name>.test.sh`
   and `PYTHONPATH=. python3 -m unittest …`.
9. **Every new `settings/smith-settings-fragment.json` entry is its own
   `{matcher, hooks:[…]}` object**, never appended to an existing chain —
   `scripts/install-hooks.sh:6-7,149-183` and
   `tests/hooks/test_hook_chain_order.sh` require `manifest-updater.sh` to
   stay LAST in the `PostToolUse` `Write|Edit` chain.
10. **Marker reality (verified empirically 2026-09-22, supersedes
    `research.md` §Q6).** `scripts/create-active-workflow.sh:139` resolves the
    project root with `git rev-parse --show-toplevel` (the **worktree**) while
    `hooks/workflow-gate.sh:60` uses `${CLAUDE_PROJECT_DIR:-$(pwd)}` (the
    **primary repo**). Consequence: `smith-build` called on the same branch
    `smith-new` registered exits **0**, not 3, and a **second marker is
    created in the worktree's own vault**. Two concurrent markers DO exist —
    `workflow: smith-new` in the primary vault, `workflow: smith-build` in
    `<worktree>/.smith/vault/active-workflows/`. The worktree marker's
    `session_log:` is **empty** (`.smith/vault/.current-session` does not
    exist in a worktree). Every marker consumer must enumerate BOTH vaults and
    tolerate an empty `session_log:`.

---

## Phase 1: Setup

- [X] T001 [P] Create `tests/activity/__init__.py` (empty package marker) so `python3 -m unittest discover -s tests/activity -t <repo root>` resolves the suite as `tests.activity.*`.
- [X] T002 [P] Create `tests/activity/fixtures/.gitkeep` so the fixture directory is tracked before any fixture lands.
- [X] T003 [P] Create `tests/smith-activity.test.sh` as an empty-but-running harness skeleton — `set -uo pipefail` header, `SCRIPT_DIR`/`REPO_ROOT`, `PASS`/`FAIL` counters, one `assert` helper, `mktemp -d -t` + `trap … EXIT`, `# --- Test N ---` banners, summary line — copied in shape from `tests/settings-dedupe.test.sh:10-27`; `chmod +x`. It must exit 0 with zero tests so CI stays green from the first commit.

---

## Phase 2: Foundational (blocking prerequisites)

Per `plan.md` §Phased ordering: **the emitter leads because it is the
highest-risk surface**, then `paths.py`, then the `phases.json` data file and
the shared normalizer that both the resolver and the sync test import.

### Emitter safety (plan step 1 — SC-4 green before anything else exists)

- [X] T004 [US4] Create `hooks/activity-emitter.sh` per `contracts/hook-envelope.md` §5: `set -uo pipefail` (never `-e`), `INPUT=$(cat 2>/dev/null || echo '{}')`, early-bail ladder exiting 0 when `~/.smith/activity/activity.port` or `activity.token` or `curl` is absent, the whole network call wrapped as `( curl --max-time 2 --connect-timeout 1 … & ) >/dev/null 2>&1`, stdin forwarded **byte-for-byte** with no parsing, trailing unconditional `exit 0`. No `timeout`/`gtimeout`, no `/dev/tcp`. `chmod +x`.
- [X] T005 [US4] Add the SC-4 daemon-down assertions to `tests/smith-activity.test.sh`: run `hooks/activity-emitter.sh` with a `PreToolUse` payload and again with a `PostToolUse` payload on stdin, with no daemon listening; assert exit status 0, **zero bytes** on stdout, and wall-clock bound measured with `python3 -c` (never shell `timeout`).
- [X] T006 [US4] Add the hanging-listener case to `tests/smith-activity.test.sh`: start a `python3 -c` `socketserver` on an ephemeral 127.0.0.1 port that accepts and never responds, point `~/.smith/activity/activity.port` at it via a scratch `SMITH_HOME`, and assert the emitter still exits 0, writes nothing to stdout, and returns within its bound (FR-40, US-4 scenario 2).
- [X] T007 [US4] Add the dual-shell assertion to `tests/smith-activity.test.sh`: re-run the T005/T006 emitter cases under `bash` **and** `zsh`, so the no-`/dev/tcp` and no-`timeout` constraints are enforced by the suite rather than by review.

### Identity and the shared data/normalizer core

- [X] T008 Create `scripts/activity/paths.py`: `SMITH_HOME` via the canonical `"${SMITH_HOME:-$HOME/.smith}"` expansion (FR-7), `primary_repo(path)` via `git -C <path> rev-parse --path-format=absolute --git-common-dir` + `dirname` (FR-28, `data-model.md` §1 — `--path-format=absolute` is load-bearing), `project_slug()` for `~/.claude/projects/<slug>`, and the transcript + `subagents/agent-<id>.{jsonl,meta.json}` path layout (`data-model.md` §4.3).
- [X] T009 Add a `make_repo` + `git worktree add` helper to `tests/smith-activity.test.sh` and assert SC-7 with it: from inside a worktree created **outside** the primary tree, `paths.primary_repo()` returns the primary checkout, and the worktree path resolves to the same project — never a second one (FR-28).
- [X] T010 Extend `tests/_harness.py` (additively — existing tests must keep passing) to put `scripts/activity` on `sys.path` and export `ACTIVITY_FIXTURES_DIR` pointing at `tests/activity/fixtures`, mirroring the existing `HOOKS_DIR` / `FIXTURES_DIR` pattern.
- [X] T011 Create `scripts/activity/phases.json` with the seeded content for all five chains **exactly** as `contracts/phases-json.md` §1 records it: `smith-new` (7), `smith-bugfix` (9), `smith-debug` (8), `smith-build` (11), `smith-finish` (9). Per workflow: `source`, `heading_level` (2, except **3** for `smith-finish`), `heading_keyword` (`Phase`, except `Step` for `smith-finish`). Per phase: `id`, `number` **as a string** (`"3.5"`, `"5.5"`, `"6.5"`), normalized `title`, ordered `match`, `mandatory_stop` (true on `smith-new` 5 and `smith-debug` 6), `handoff` (`["smith-build"]` on `smith-new` 6, `["smith-bugfix"]` on `smith-debug` 6). Workflow-qualify the `smith-bugfix` 3.5 / `smith-debug` 5.5 `match` collision and give `smith-finish` 2 the `["Step 2","smith-finish commit"]` form (FR-15, `contracts/phases-json.md` §2).
- [X] T012 Create `scripts/activity/phases.py` with `normalize_phase_title()` implementing the five rules in `contracts/phases-json.md` §3 (strip backticks; remove exactly one trailing parenthesized group; remove a trailing ` — <rest>` em-dash clause; collapse whitespace; compare case-sensitively; preserve `& . , -`) and a **fence-aware** heading extractor that reads `heading_level` / `heading_keyword` from `phases.json` and parses decimal phase numbers (FR-16, `contracts/phases-json.md` §4). No other resolver logic yet — this file grows in Phase 3.
- [X] T013 Create `tests/activity/test_phases.py` with the FR-16 sync assertions: for each of the five mapped workflows, extracted `(number, title)` pairs equal `phases.json` exactly — same set, same order, same numbers — plus counts 7/9/8/11/9, plus every `source` file exists and is readable (SC-3). The test **imports `normalize_phase_title` from `phases.py`**; it must never reimplement it.
- [X] T014 Add the four structural `phases.json` invariants from `data-model.md` §3 to `tests/activity/test_phases.py`: unique `id` across all workflows; `number` strictly increasing as decimals within a chain; no two phases in **different** chains sharing an identical `match` pattern; every `handoff` value naming a workflow present in the file.
- [X] T015 Wire the Python unit suite into `tests/smith-activity.test.sh` as a single assertion — `PYTHONPATH="$REPO_ROOT" python3 -m unittest discover -s "$REPO_ROOT/tests/activity" -t "$REPO_ROOT" -q` — printing the first 60 lines of output on failure. This is the pattern that makes every `tests/activity/test_*.py` gate in CI (FR-54/SC-16); no existing flat test wraps a Python run, so this **establishes** it.
- [X] T016 Create `scripts/activity/markers.py`: enumerate active-workflow markers under **the primary repo vault AND every linked worktree's vault** (`git worktree list --porcelain` → `<wt>/.smith/vault/active-workflows/*.yaml`), correlate by `branch:`, and key records by `(primary_repo, marker_filename)` per `data-model.md` §2.4. This dual-vault enumeration is mandatory — see binding constraint 10.
- [X] T017 Add the tolerant marker parser to `scripts/activity/markers.py` per `data-model.md` §4.1: optional surrounding quotes on values; **`session_log:` may be empty** (trailing space and nothing after it is a valid, occurring shape) with fallback to the primary vault's `.current-session`; `branch:` may name no real git ref; the `smith-finish` 4-field variant (`finish-<safe>.yaml`, no `worktree:`, no `session_log:`, no trailing `Z`); optional `phase:` accepted and preferred (FR-13); filename mapping `[^A-Za-z0-9._-] → -`.
- [X] T018 Create `tests/activity/test_markers.py` covering `markers.py`: dual-vault enumeration finds the primary `workflow: smith-new` marker **and** the worktree `workflow: smith-build` marker for one branch; quoted values parse; the `smith-finish` variant parses; and an **empty `session_log:` falls back to the primary vault's `.current-session`** rather than yielding `None` or crashing (binding constraint 10, consequence 2).
- [X] T019 Create `scripts/activity/sessionlog.py` parsing the four block formats in `data-model.md` §4.2 — `Subagent invoked:` (+ `**Type:**` / `**Model:**`), `/smith-<skill> <event>` (+ `**Outcome:**` / `**Artifacts:**`), `Subagent completed` (+ the `**Metrics:**` list), `workflow-start <BRANCH>` — plus the two line formats from `metrics-tracker.sh` and `file-change-logger.sh`. Every record carries its **append offset**; `## Metrics` is created once and appended to forever, so never assume section order.
- [X] T020 Add the three-tier session-log discovery precedence to `scripts/activity/sessionlog.py`, reused verbatim from `hooks/workflow-summary.sh:84-135`: explicit path → marker `session_log:` (disambiguated by `branch:` when several carry one, and **skipped when empty**) → `.current-session`, with `metrics-tracker.sh:23-32`'s double existence check on both the pointer and its target.

---

## Phase 3: US-1 — The phase stepper answers "where is this workflow right now?" (P1)

Every task in this phase edits `scripts/activity/phases.py`, so none are `[P]`
with each other. **Pure: no file reads except `phases.json`, no git, no
network, no clock except an injected `now`** — that is what makes SC-1/SC-2
replayable against fixtures with no daemon (`plan.md` §Architecture Summary).

- [X] T021 [US1] Implement the FR-11 signal-precedence state machine in `scripts/activity/phases.py`, keyed by workflow type from the marker, over an ordered event stream: (1) `Subagent invoked:` block, (2) live `PreToolUse` `Task` event, (3) skill event entry, (4) `workflow-start` stamp, (5) `Subagent completed` block → phase DONE not running, (6) artifact presence. It MUST NOT assume phases correspond to skill invocations (FR-10 — `/smith-bugfix` and `/smith-debug` produce zero skill invocations across all their phases).
- [X] T022 [US1] Enforce FR-58 in `scripts/activity/phases.py`: **all ordering keys on append offset within the session log** (and daemon-side ingest sequence for hook events), never on parsed `[HH:MM:SS]` timestamps. The log mixes UTC (hooks) with model-local wall time (`Subagent invoked:` blocks); a 4-hour skew was observed in this repository. Parsed timestamps may be carried for display, labeled with their source, but must not participate in any sequence, window-membership, or phase-advance comparison.
- [X] T023 [US1] Implement FR-13 in `scripts/activity/phases.py`: a marker `phase:` field, if ever present, beats every inferred signal and sets provenance `marker_phase`. Nothing writes one today; this makes OOS-1's later stamping purely additive.
- [X] T024 [US1] Implement FR-12 artifact corroboration in `scripts/activity/phases.py` covering **both** layouts — `specs/<n>-<slug>/` and `.specify/systems/<system>/features/<n>-<slug>/` — searched in the **worktree first**, then the primary repo: `spec.md` → Phase 3 complete; `plan.md`/`questions.md` → Phase 4 complete; `questions.md` with unanswered items → sitting at the Phase 5 gate; `tasks.md` with n of N boxes checked → mid-implementation at n/N. A file **READ** must never advance a phase (the `smith-build` Phase 3.5 clean-code rubric case).
- [X] T025 [US1] Implement `PhaseState` derivation in `scripts/activity/phases.py` per `data-model.md` §2.5: `state ∈ completed|current|remaining|skipped`, `provenance`, `entered_at`/`exited_at`, and a one-line `evidence` string naming the exact signal. **`skipped` is a first-class value** — a phase is skipped when a *later* phase in the same chain reached `current`/`completed` while this one never did (feeds FR-23a).
- [X] T026 [US1] Implement FR-19 provenance labelling and FR-20 honest unknown in `scripts/activity/phases.py`: when no signal resolves a phase, emit `current_phase_id: None` plus `last_known_phase: (id, ts)`. **Never** a guessed, interpolated, or nearest-match phase name.
- [X] T027 [US1] Implement FR-18's mandatory-stop handling in `scripts/activity/phases.py`: `smith-new` Phase 5 and `smith-debug` Phase 6 carry `mandatory_stop: true` and must be projected distinctly from working phases — "waiting on you" is never rendered as "working".
- [X] T028 [US1] Implement the event-derived permission state in `scripts/activity/phases.py`: a `PermissionRequest` with no matching `PermissionDenied` and no `PostToolUse` for the same `prompt_id` means **waiting on permission** (FR-18 PRIMARY source, `questions.md` Q1). `claude agents --json`'s `status` is corroboration only (consumed in Phase 9) and its absence must never blank the indicator. `waitingFor`, `state` and `id` do not exist and must never be read.
- [X] T029 [US1] Implement FR-17 nesting in `scripts/activity/phases.py` **from the two real markers first**: a child workflow is detected when a marker in a linked worktree's vault names the same `branch:` as a parent marker in the primary vault with a different `workflow:` (e.g. parent `smith-new` in the primary vault, child `smith-build` in `<worktree>/.smith/vault/`). Correlate by branch, pin the parent stepper at its handoff phase, render the child beneath it — never replace the parent. **Fallback only when no child marker exists:** cross-chain phase-title matching against all mapped chains, opening a nested child only at a phase carrying a `handoff` entry for that workflow (`research.md` §Q6's original derivation, demoted to the fallback path).
- [X] T030 [US1] Implement the unknown-workflow case in `scripts/activity/phases.py`: a marker whose `workflow:` has no `phases.json` entry yields an **empty** `phases` list, `current_phase_id: None`, and the note `no phase map entry`. The resolver never invents a chain.
- [X] T031 [US1] Build the SC-1 fixture set under `tests/activity/fixtures/`: a recorded full `/smith-new` → `/smith-build` run — session log with `Subagent invoked:` blocks for each phase, the matching `PreToolUse` `Task` event stream, the **two markers** (primary-vault `smith-new`, worktree-vault `smith-build`), and the artifact tree for the FR-12 corroboration checkpoints.
- [X] T032 [US1] Add SC-1 to `tests/activity/test_phases.py`: replay the T031 fixture and assert the resolved numbered phase at every checkpoint, including the nested handoff ("smith-new › 6/6 … → smith-build › 3/11 Testing") and the questions-gate stop, with the expected provenance label on each.
- [X] T033 [US1] Add the FR-20 negative case to `tests/activity/test_phases.py`: a fixture whose signals are exhausted resolves to `phase unknown` carrying the last known phase and its timestamp, and the resolver returns no phase name for the current step.

---

## Phase 4: US-2 — Divergence and absence are surfaced as findings (P1)

All of `scripts/activity/findings.py` is **pure** — `now` is a parameter, never
`datetime.now()`, so the 90 s window is testable without sleeping.

- [X] T034 [US2] Create `scripts/activity/findings.py` with the `Finding` shape from `data-model.md` §2.10 (`finding_id` = deterministic hash of `(kind, classification, subject)`, `kind`, `classification`, `severity`, `workflow_key`, `phase_id`, `observed`, `self_reported`, `timestamp`, `evidence`, `retracted`) and `RECONCILE_WINDOW_S = 90` as a module constant.
- [X] T035 [US2] Implement FR-22(a) `skill_logging_bug` in `scripts/activity/findings.py`: a `Task` dispatch the harness observed with no matching `Subagent invoked:` block inside the **two-sided**, append-offset-keyed 90 s window. The window is two-sided because all four workflow SKILLs write the block *before* the Agent call, so the block may precede or follow the event (FR-11 signal 2, `questions.md` Q5).
- [X] T036 [US2] Implement FR-22(b) `undesigned_path` and FR-22(c) `marker_contradiction` in `scripts/activity/findings.py`. `marker_contradiction` fires on a cross-chain signal at a phase with no declared `handoff` — it must NOT fire on the now-normal two-marker `smith-new` → `smith-build` handoff (binding constraint 10), which is a legitimate nest.
- [X] T037 [US2] Implement FR-23 absence derivation in `scripts/activity/findings.py`: `phase_skipped` (one finding per `skipped` PhaseState), `gate_never_reached` (a `mandatory_stop` phase the workflow advanced past or ended before), `hook_never_fired` (a hook wired in the installed settings that never fired for a session the applicability table says it should have).
- [X] T038 [US2] Implement FR-60 in `scripts/activity/findings.py`: derive the expected-hook set from the **installed `~/.claude/settings.json`**, parsed at daemon start and refreshed on `ConfigChange`, intersected with a ~10-line module-constant applicability table (`lint-on-save` only after `Write`/`Edit`; `security-guard-bash` only on `Bash`; …). Never from a static shipped list and never from `settings/smith-settings-fragment.json`. **When that file is unreadable or unparseable, absence detection is DISABLED** with the `expected-hooks:unknown` degraded token surfaced — never guessed, never silently degraded.
- [X] T039 [US2] Implement FR-61 `shipped_not_wired` in `scripts/activity/findings.py`: diff the installer-staged shipped-hook manifest at `"${SMITH_HOME:-$HOME/.smith}"/activity/` against the installed settings' wired set. `observed` = the manifest entry, `self_reported` = `null`. Distinct in classification from `hook_never_fired`.
- [X] T040 [US2] Implement FR-57 `permission_disagreement` in `scripts/activity/findings.py`: raise exactly one finding when `claude agents --json` reports a `status` for a session AND it disagrees with the event-derived permission state (T028). A record with **no** `status` (17 of 23 observed) produces **zero** findings — absence of corroboration is not disagreement.
- [X] T041 [US2] Implement FR-59 retraction in `scripts/activity/findings.py`: when the matching block or event lands late inside the two-sided window, re-emit the **whole finding** with `retracted: true` and a settled `severity`. Retraction is an **upsert, never a remove**; `findings.remove` is reserved for a finding whose subject no longer exists (`contracts/sse-frames.md` §4.3).
- [X] T042 [US2] Enforce FR-21 and FR-24 across `scripts/activity/findings.py`: every finding carries **both** `observed` (hook-derived, the displayed value) and `self_reported` side by side — no layer may "reconcile" a conflict by discarding one side — and every finding is advisory and non-blocking; nothing modifies, pauses, or interferes with the audited workflow.
- [X] T043 [US2] Build the US-2 fixture pairs under `tests/activity/fixtures/`: (a) a `Task` dispatch with a deliberately omitted `Subagent invoked:` block; (b) a `spec.md` artifact with no preceding dispatch; (c) a run advancing Phase 4 → Phase 6 with Phase 5 never signalled; (d) a session with an outstanding `PermissionRequest` plus a disagreeing `claude agents --json` record and a second with `status` absent; (e) an unreadable `~/.claude/settings.json` stand-in and a shipped-but-unwired hook manifest.
- [X] T044 [US2] Create `tests/activity/test_findings.py` asserting SC-5 (exactly one `skill_logging_bug` finding naming workflow, phase and timestamp) and SC-6 (the passed-over phase renders `skipped` **and** exactly one `phase_skipped` absence finding).
- [X] T045 [US2] Add SC-19 and SC-21 to `tests/activity/test_findings.py`: `status` disagreement → exactly one `permission_disagreement`; `status` absent → zero. Unreadable settings → absence detection off, zero absence findings, notice present; readable settings with an unwired shipped hook → exactly one `shipped_not_wired`, distinct in classification from any `hook_never_fired`.
- [X] T046 [US2] Add SC-20's model-side half to `tests/activity/test_findings.py`: a finding raised then retracted inside the 90 s window is **still present** in the returned structure with `retracted: true` and a settled severity — asserted as a transition, never as a deletion.

---

## Phase 5: US-3 — Two concurrent workflows in one repo are never confused (P1)

- [X] T047 [US3] Implement the FR-14 attribution pass in `scripts/activity/phases.py` per `data-model.md` §2.4: for each event, in order — (1) `event.cwd` inside the marker's `worktree:` by exact prefix on realpathed absolute paths; (2) resolved branch of `event.cwd` equals the marker's `branch:`; (3) a session-log block textually naming a mapped phase whose chain matches exactly one candidate marker's `workflow:`; (4) otherwise **unattributed**. Single assignment — an ambiguous event is dropped, never duplicated.
- [X] T048 [US3] Add the `unattributed_events` counter to the `scripts/activity/phases.py` resolver output, surfaced as its own number because a rising count is itself an audit signal (`contracts/sse-frames.md` §4.2).
- [X] T049 [US3] Build the SC-2 fixture under `tests/activity/fixtures/` from the **real** interleaved log observed in this repository: one session log carrying `Subagent invoked:` blocks from two workflows in append order, plus two markers (`60-activity-dashboard.yaml` and `67-deterministic-questions.yaml`) naming the **same** `session_log:` path with different `branch:`/`worktree:`. A synthetic fixture would lack the mixed-clock property that makes this hard.
- [X] T050 [US3] Add SC-2 to `tests/activity/test_phases.py`: the resolver produces **exactly two** workflow records; no block is attributed to more than one; neither stepper advances on the other's events; each token rollup counts only its own attributed usage (asserted once `usage.py` lands — see T068).

---

## Phase 6: US-4 — A hook can never break a session (P1) — wiring and verification

The emitter itself landed in Phase 2. This phase wires it and proves the
budget.

- [X] T051 [US4] Verify every hook event name and payload field this feature relies on against the **installed** Claude Code's `/hooks` output before wiring anything, and record the result in `contracts/hook-envelope.md` §2 (FR-39/FR-43/A-1). For any event whose availability is not confirmed, the implementation degrades rather than assumes — `SubagentStart` in particular falls back to `PreToolUse` on `Task` plus sidechain detection.
- [X] T052 [US4] Add the emitter's hook entries to `settings/smith-settings-fragment.json` for the confirmed primary set in `contracts/hook-envelope.md` §2 (`SessionStart`, `SessionEnd`, `UserPromptSubmit`, `PreToolUse *`, `PostToolUse *`, `PostToolUseFailure`, `SubagentStart`, `SubagentStop`, `Stop`, `Notification`, `PermissionRequest`, `PermissionDenied`, `PreCompact`, `PostCompact`, `ConfigChange`). **Each is its own `{matcher, hooks:[…]}` object** — the `hooks/metrics-tracker.sh` precedent at `:48-53` — and each declares a `timeout`, the **first** `timeout` field anywhere in `settings/`.
- [X] T053 [US4] Add a flat assertion to `tests/smith-activity.test.sh` that `settings/smith-settings-fragment.json`'s `PostToolUse` `Write|Edit` chain still ends with `manifest-updater.sh` and that no activity entry was appended into an existing chain. CI never reaches `tests/hooks/test_hook_chain_order.sh`, so this is the only gate on that invariant for this change.
- [X] T054 [US4] Add the native `"type": "http"` entry template to `contracts/hook-envelope.md` §5's shipped form and implement install-time support detection in `scripts/install.sh` (FR-42): prefer `{"type":"http","url":"http://127.0.0.1:<port>/ingest","headers":{"Authorization":"Bearer $SMITH_ACTIVITY_TOKEN"},"allowedEnvVars":["SMITH_ACTIVITY_TOKEN"],"timeout":5}`, **default to `hooks/activity-emitter.sh` on any doubt** — the fallback costs ~1.8 ms of foreground time, so conservative detection is free.
- [X] T055 [US4] Re-measure the emitter latency with `/usr/bin/time -p` against (a) a live daemon, (b) a closed port, (c) a hanging listener backgrounded, and record the figures in `quickstart.md` Scenario 4, replacing `contracts/hook-envelope.md` §6's planning-time numbers if they have moved (A-2 — the budget is a target to MEASURE).
- [X] T056 [US4] Add a `hooks/activity-emitter.sh` source-level assertion to `tests/smith-activity.test.sh`: grep the script for `timeout `/`gtimeout`/`/dev/tcp` and assert zero hits, and assert the presence of `--max-time` and a trailing unconditional `exit 0`.
- [X] T057 [US4] Add `docs/hooks.md`-shaped inline documentation to `hooks/activity-emitter.sh`'s header block matching the repo's existing hook-header convention (purpose, event, exit contract, privacy note) so `docs/hooks.md` (T124) can be written from it without re-deriving behavior.

---

## Phase 7: US-8 — Live tokens, cost, and quota headroom (P2)

Sequenced before the daemon because `server.py` projects these rollups, and
before the remaining readers because the `load_pricing()` contract trap must be
established once, up front (`plan.md` steps 6 and 6a).

> One task in this phase (**T066**) is tagged `[US6]`: FR-27's subagent sidecar
> reader physically lives in `usage.py`, so it lands with this module.

- [X] T058 [US8] Create `scripts/activity/usage.py` importing `hooks/workflow_summary_lib.py` via the three-candidate `HOOK_DIR` ladder reused verbatim from `hooks/workflow-summary.sh:198-214`. **`hooks/workflow_summary_lib.py` is not modified** (FR-33/FR-36, D-6).
- [X] T059 [US8] Implement the FR-33 contract trap discipline in `scripts/activity/usage.py`: the pricing table is obtained **only** via `load_pricing()`, never a raw `json.load` of `pricing.json` — `match_family()` reads a `_compiled_patterns` key that only `load_pricing()` injects (`:122` writes it, `:134` reads it with `.get(…) or []`), so a raw parse resolves every model to `None` with no exception and no log line. Throttle: `load_pricing()` once at startup with an mtime-gated refresh at most once per 60 s.
- [X] T060 [US8] Implement the `TokenRollup` shape from `data-model.md` §2.7 in `scripts/activity/usage.py` — `input`/`output`/`cache_write`/`cache_read`/`normalized`/`usd`/`model`/`unknown_models`/`scope` — with `session` scope from `parse_parent_jsonl` over the parent transcript, read incrementally from a remembered byte offset at most once per session per ~2 s (FR-32).
- [X] T061 [US8] Implement FR-34 in `scripts/activity/usage.py`: an unmatched model id yields `usd = None`, which the projection renders as **unavailable** — never `$0.00`. Token counts still render for that slice. Collect the unmatched ids into `unknown_models`.
- [X] T062 [US8] Implement FR-36 in `scripts/activity/usage.py`: incremental tail of `~/.claude/projects/<slug>/<session-id>/subagents/agent-<id>.jsonl` for sidechain `message.usage`, i.e. `parse_parent_jsonl`'s accumulation loop with the `isSidechain` guard **inverted**. Malformed JSONL lines are skipped and never abort a rollup. The parent transcript contains zero `isSidechain` rows, so this is the only source of live subagent tokens.
- [X] T063 [US8] Implement `workflow` scope in `scripts/activity/usage.py`: sum of attributed sessions + attributed subagents (FR-14 attribution from T047), plus `parse_subagent_blocks` for agents that finished before the daemon started.
- [X] T064 [US8] Update `hooks/pricing.json` with the current model families **including `claude-opus-5*`** (FR-62). **First action is consulting the authoritative Claude pricing reference via the `claude-api` skill, which explicitly forbids answering from memory — not editing the file.** Set `last_verified` to the date checked on every family touched. If authoritative rates cannot be obtained, the family entry still lands with its correct match pattern and its rates marked **unavailable** — never guessed. **Entry ORDER is load-bearing**: `match_family()` returns the first array-order regex match, so each specific family must precede any wildcard that would also match it.
- [X] T065 [US8] Add a `hooks/*.json` glob to the hook copy loop in `scripts/install.sh` alongside the existing `hooks/*.sh` at `:195` and `hooks/*.py` at `:203`, so `pricing.json` is installed and refreshed (FR-62). A **glob**, not a single `cp`, so the next `hooks/*.json` is not a fourth stale enumeration.
- [X] T066 [US6] Implement the FR-27 subagent sidecar reader in `scripts/activity/usage.py`: discover `~/.claude/projects/<slug>/<session-id>/subagents/agent-<id>.meta.json` and read `agentType`, `description`, `parentAgentId`, `spawnDepth`, `toolUseId`, with ctime as the start time for elapsed. `toolUseId` is what ties a sidecar to the `PreToolUse` `Task` dispatch that created it — sidecar discovery is **primary**, `SubagentStart` only shortens latency (`contracts/hook-envelope.md` §3).
- [X] T067 [US8] Implement the `QuotaWindows` model in `scripts/activity/usage.py` per `data-model.md` §2.9: parse `rate_limits.five_hour` / `seven_day` / `spend_limit` (`used_percentage` + epoch-seconds `resets_at`) from the statusline payload; absent `rate_limits` → `available: false`. Account-wide — returned unchanged under every `?project=` filter (FR-35/FR-3).
- [X] T068 [US8] Create `tests/activity/test_usage.py` asserting SC-11: token rollup over a known JSONL fixture matches expected input/output/cache-write/cache-read/normalized/USD **exactly**, with pricing resolved through `load_pricing()`. Add the SC-2 token half from T050 here — each of the two concurrent workflows counts only its own attributed usage.
- [X] T069 [US8] Add the trap case to `tests/activity/test_usage.py`: pass a raw `json.load` dict of `hooks/pricing.json` to `match_family()` and assert it returns `None`, documenting FR-33's trap in executable form. Add a grep assertion that no file under `scripts/activity/` parses `pricing.json` independently.
- [X] T070 [US8] Add FR-56's characterization tests to `tests/activity/test_usage.py` for the zero-coverage `workflow_summary_lib` functions this feature depends on — `parse_parent_jsonl`, `resolve_parent_jsonl`, `resolve_workflow_window`, `git_files_changed`, and the three `format_*` renderers — written **before** `usage.py` depends on them, because "preserve existing behavior" has nothing to verify against today.
- [X] T071 [US8] Create the flat `tests/activity-pricing.test.sh` (FR-62/SC-17) asserting: `scripts/install.sh` copies `hooks/*.json`; after install against a clean `$CLAUDE_HOOKS_DIR`, `hooks/pricing.json` is present there; `load_pricing()` + `match_family()` resolve `claude-opus-5` to a non-`None` entry; **every** family carries `last_verified`; and **no** family carries a numeric rate without one. The last two assertions are the executable form of the never-invent-rates constraint — a fabricated rate is indistinguishable from a real one at runtime, so the guard sits on the metadata.

---

## Phase 8: US-7 — Worktree and branch reality, including the degraded states (P2)

- [X] T072 [US7] Create `scripts/activity/worktrees.py` enumerating worktrees via `git worktree list --porcelain` and cross-referencing each active-workflow marker's `branch:` and `worktree:` fields (FR-29). Per worktree: short path, branch, base branch via `skills/smith/scripts/get-base-branch.sh`, ahead/behind versus `origin/<base>`, dirty-file count, occupying session, owning marker. The primary checkout is marked distinctly and shows its own branch.
- [ ] T073 [US7] Implement the six-row classification decision table from `data-model.md` §2.6 in `scripts/activity/worktrees.py`, evaluated top to bottom, first match wins: `primary` → `missing` → `orphaned` → `held` → `active` (marker) → `active` (no marker). **Row 3 before row 4 is deliberate** — a merged-and-deleted branch whose marker survives is janitor backlog, not a stalled bugfix, and must never render as an active workflow (FR-30).
- [ ] T074 [US7] Implement the HELD threshold in `scripts/activity/worktrees.py` as a named constant (10 minutes): "not advancing" is the owning workflow having no signal newer than its `current` phase's `entered_at` for longer than the threshold. Carry `age_s` and `died_in_phase` for the HELD render, and the `git worktree prune` remedy string for MISSING.
- [ ] T075 [US7] Implement the FR-31 per-worktree git cache in `scripts/activity/worktrees.py` with a ~3 s debounce. **Git must never be invoked per SSE frame.**
- [ ] T076 [US7] Extend `tests/smith-activity.test.sh`'s `make_repo` helper (from T009) with a `git worktree add` step and construct each degraded state in a scratch repository: HELD (marker, unmerged branch, stale signal), MISSING (marker pointing at a deleted path), ORPHANED (merged-and-deleted branch with a surviving marker). No existing test in the repo uses `git worktree`, so this is a documented harness extension.
- [ ] T077 [US7] Create `tests/activity/test_worktrees.py` asserting SC-8: each of HELD, MISSING and ORPHANED is classified and labelled correctly against the T076 fixtures, ORPHANED is never rendered as an active workflow, and the primary checkout is marked distinctly.

---

## Phase 9: US-6 — Live sessions and subagents (P2)

- [ ] T078 [US6] Create `scripts/activity/sessions.py` producing the `Session` records FR-25 requires — `session_id`, model, start time, cwd, resolved worktree and branch (via a debounced `git -C <cwd> rev-parse --abbrev-ref HEAD`, **never** from the transcript's `gitBranch`, which is captured at session start and does not follow cwd), state, and pid — per project and globally.
- [ ] T079 [US6] Implement the FR-26 `claude agents --json` poll in `scripts/activity/sessions.py` at 5-10 s as a **liveness reconciler only**. Code against the observed record shape `{pid, cwd, kind, name, sessionId, startedAt, status?}` — **`waitingFor`, `state` and `id` are present in ZERO records and must never be read, defaulted to, or depended on.** Use `subprocess` with a `timeout=` kwarg, never shell `timeout`.
- [ ] T080 [US6] Implement the dead-session reaper in `scripts/activity/sessions.py`: a session that died without ever firing `SessionEnd` is removed from the live list within one poll interval rather than lingering forever (FR-26, US-6 scenario 4).
- [ ] T081 [US6] Emit the FR-57 corroboration comparison from `scripts/activity/sessions.py`: where `status` IS present, hand both it and the event-derived permission state to `findings.py` (T040). Where it is absent, emit the `claude-agents-json:no-status` degraded token for that session and no comparison. If the command is unavailable entirely, emit `claude-agents-json:absent`, degrade the sessions panel to hook-derived data only, and **state the degradation rather than hide it** (A-9).
- [ ] T082 [US6] Assemble the live-subagent records in `scripts/activity/sessions.py` from the T066 sidecar reader plus the `PreToolUse` `Task` event as the corroborating spine record, correlated on `toolUseId`, carrying `agent_type`, dispatch description and elapsed time (FR-27). Third-tier fallback — `PreToolUse` on `Task` plus sidechain detection — covers the window between the tool call and the sidecar appearing on disk.
- [ ] T083 [US6] Create `tests/activity/test_sessions.py` asserting the US-6 acceptance set against a synthetic event stream plus a canned `claude agents --json` payload: three sessions with one blocked on permission (event-derived, visually distinct); a `status`-bearing record that disagrees produces the FR-57 comparison; a record with no `status` produces none; a session that dies without `SessionEnd` is reaped; two running subagents each show `agent_type`, description and elapsed.

---

## Phase 10: US-5 — One daemon, many projects, fully idempotent (P2)

> **T086 is tagged `[US10]`**: FR-48's redaction must happen *at ingest,
> before the state tree*, so it is implemented inside `ingest.py` here even
> though the story it serves is US-10. Its verification lives in Phase 12.

- [X] T084 [US5] Create `scripts/activity/state.py`: the single `ActivityState` tree from `data-model.md` §2 guarded by one `threading.RLock`, with `generation`, `started_at`, `capture_prompts`, `expected_hooks`, `shipped_hooks`, `quota`, and the five keyed maps (`projects`, `sessions`, `subagents`, `workflows`, `findings`). The storage layer sits behind this boundary so a retained two-tier scheme later is a configuration change, not a redesign (OOS-3).
- [X] T085 [US5] Implement the FR-41 coalescing broadcaster in `scripts/activity/state.py`: ingest handlers mutate and set a dirty flag, never touching a socket; one broadcaster thread wakes on the flag, waits `BROADCAST_DEBOUNCE_MS = 200`, bumps `generation`, and fans out ONE `delta`. The wait is a **fixed-interval leaky bucket, not reset-on-every-event** — that bounds worst-case latency at 200 ms under a `PostToolUse *` storm. Ceiling 5 frames/second per connection. One SSE frame per tool call is forbidden.
- [X] T086 [US10] Create `scripts/activity/ingest.py`: envelope validation against `contracts/hook-envelope.md` §1 (every field optional; a missing `session_id` is counted and dropped, not an error), a 256 KiB `MAX_INGEST_BYTES` cap that reads and discards exactly `Content-Length` bytes before replying, and **FR-48 redaction applied before the payload reaches the state tree** — `prompt` → `"<redacted:N chars>"`, `tool_input` → `{"<redacted>": N}`, `tool_response` → `"<redacted:N bytes>"`, any value under a key matching `(?i)(secret|token|password|api_?key|authorization)` → `"<redacted>"`, gated by `SMITH_ACTIVITY_CAPTURE_PROMPTS=1`. Byte lengths are retained deliberately; `tool_name`, `session_id`, `prompt_id`, `cwd`, `transcript_path`, `permission_mode`, `hook_event_name`, `agent_id`, `agent_type`, `source`, `error_type` are retained always.
- [X] T087 [US5] Create `scripts/activity/server.py`: one `http.server.ThreadingHTTPServer` bound to the hardcoded constant `127.0.0.1` — never `0.0.0.0`, never a LAN address, never an IPv6 non-loopback, under any flag (FR-4) — with `log_message` overridden to a no-op and the full route table from `contracts/http-surface.md` §2.
- [X] T088 [US5] Implement the FR-47 token gate in `scripts/activity/server.py`: `secrets.token_urlsafe(32)` generated at first daemon start, stored `0600` at `"${SMITH_HOME:-$HOME/.smith}"/activity/activity.token`, REQUIRED as the `token` query parameter on `/events` and every `/api/*` route and as `Authorization: Bearer` on `/ingest` and `/statusline`. Comparison uses `hmac.compare_digest`, never `==`. Absent and wrong produce an **identical** `403 {"error":"forbidden"}` so the endpoint is not an oracle. `/` and `/static/*` are un-gated.
- [X] T089 [US5] Implement `POST /ingest` and `POST /statusline` in `scripts/activity/server.py` per `contracts/http-surface.md` §3: accepted → `204`; non-JSON body, oversize body, or any daemon-side exception → **`204`**, counted and logged as a redacted note. `/ingest` never returns a non-2xx for a malformed payload — a 4xx would be a failure signal the emitter might act on, and FR-40's contract is that it acts on nothing.
- [X] T090 [US5] Implement `GET /health` in `scripts/activity/server.py` per `contracts/http-surface.md` §4, un-gated, returning `{"service":"smith-activity","version","pid","started_at","projects"}`. **The FR-5 probe is `service == "smith-activity"`, not the HTTP status.**
- [X] T091 [US5] Implement `GET /events` in `scripts/activity/server.py` per `contracts/sse-frames.md` §1-§4: `text/event-stream`, `id:`/`event:`/`data:` framing with single-line `json.dumps(separators=(",",":"))`, the six fixed event names (`hello`, `state`, `delta`, `resync`, `quota`, `finding`), a bounded `queue.Queue(maxsize=64)` per connection draining to one `resync` on overflow, a `: keepalive` comment every 20 s, and `try/except (BrokenPipeError, ConnectionResetError)` dropping a closed tab silently. `?project=` filters `state`/`delta` but **never** the `quota` block.
- [X] T092 [US5] Implement the `/api/*` read routes in `scripts/activity/server.py` — `/api/state`, `/api/projects`, `/api/workflows`, `/api/worktrees`, `/api/usage`, `/api/vault` — each returning `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`, with `/api/state` carrying `generation`, `daemon_started_at`, `retention: "ephemeral"` and `capture_prompts`. `/static/<name>` is `os.path.basename()`-ed and looked up in an explicit allowlist dict, never joined against user input.
- [X] T093 [US5] Implement `POST /api/register` in `scripts/activity/server.py` (FR-2/FR-3): register a project **by its primary-repo path** (T008), so a worktree never becomes a second project; present global totals with a per-project filter, never a per-project silo. Writes go only to `~/.smith/activity/projects.json` (FR-7/FR-44).
- [X] T094 [US5] Create `scripts/activity/smith-activity.sh` — the lifecycle CLI, mirroring `skills/smith-research/scripts/start-playwright-server.sh`'s discipline: `[start|stop|restart|status|open]` with `--port N`, `--no-open`, `--foreground`; no subcommand ⇒ ensure running, register, open (FR-1). Idempotent second invocation starts no second daemon (FR-2). Port occupancy resolved by the `/health` identity probe — reuse a Smith daemon, pick and record another port for an unrelated process, never abort (FR-5). Stale pidfile (`kill -0` absent, or alive but foreign) is cleaned up and the daemon restarted, never a failure (FR-6). All runtime state under `"${SMITH_HOME:-$HOME/.smith}"/activity/` — `activity.pid`, `activity.port`, `activity.token`, `activity.log`, `wrapped-statusline` — never inside any project vault (FR-7). **Port probe uses `nc` or `python3`, never `/dev/tcp`; pidfile lives under `~/.smith/activity/`, not `$TMPDIR`.** Last stdout line is the URL.
- [X] T095 [US5] Add a single 5 MB log rollover to `scripts/activity/smith-activity.sh`/`scripts/activity/server.py` for `~/.smith/activity/activity.log`. There is no log rotation anywhere in this repo, and a daemon seeing every `PostToolUse` grows unbounded otherwise.
- [X] T096 [US5] Create `skills/smith-activity/SKILL.md` with frontmatter `name` + `description` + `argument-hint` (the repo's only frontmatter vocabulary — `allowed-tools` does not exist anywhere in this repo). Document `[start|stop|restart|status|open]`, `--port`/`--no-open`/`--foreground`, and the **FR-8 marker discipline**: register `create-active-workflow.sh --workflow maintenance` with a synthetic `--branch` label **before** writing anything, clear it via `skills/smith/scripts/clear-active-workflow.sh` when finished. Reference `contracts/` rather than restating it.
- [X] T097 [US5] Add SC-9 and SC-10 to `tests/smith-activity.test.sh`: a second invocation from a different project yields exactly one daemon process, two registered projects and two working URLs; a stale pidfile with an **absent** pid and one with a **foreign** pid are each cleaned up and the daemon restarted, with exit status 0 in both cases.
- [X] T098 [US5] Add SC-15 to `tests/smith-activity.test.sh` as two source-level assertions plus one socket inspection: the daemon listens on `127.0.0.1` only; `grep` `scripts/activity/*.py` for `urllib`, `http.client`, `ftplib`, `smtplib` and `socket.create_connection` outside `paths.py`'s probe and assert zero hits (FR-49). Deterministic, fast, and not defeatable by a network-less test environment.
- [X] T099 [US5] Add an FR-44 guard assertion to `tests/smith-activity.test.sh`: grep `scripts/activity/` and `hooks/activity-emitter.sh` for any write path containing `active-workflows` and assert zero hits, and assert that a running daemon leaves a fixture project's `.smith/vault/` mtime set unchanged. The gate cannot enforce this — a detached daemon lives outside the hook system (A-7) — so the prohibition needs its own test.

---

## Phase 11: US-9 — The vault audit panel (P3)

- [ ] T100 [US9] Create `scripts/activity/vault.py` producing the `VaultSnapshot` from `data-model.md` §2.8 — `recent_sessions`, `ledger` counts by category, `queue` depth + last scheduler run + history count, `bank` items, `agents` findings by type, `index` freshness — **reads only**, never opening any file under a project's `.smith/vault/` for writing (FR-37/FR-44/US-9).
- [ ] T101 [US9] Implement FR-38 `stat`-based change detection at ~1 s granularity in `scripts/activity/vault.py` (Python stdlib has no inotify), over exactly the listed sources: `active-workflows/*.yaml`, `.current-session*`, `sessions/*.md`, `ledger/*.md` + `meta.yaml`, `queue/` + `queue/history/`, `bank/`, `agents/<type>/*.md`, `.smith/index/`, `~/.smith/projects.json`, `~/.smith/scheduler/scheduler.log`. Keep per-file `(mtime, size, offset)` in `Project.poll_state`.
- [ ] T102 [US9] Implement the three `friction` counters in `scripts/activity/vault.py` — workflow-gate denials, security-guard blocks, grade-response retries — counted by hook name from `~/.smith/logs/hooks.log`'s shared `<ISO8601Z> <hookname> key=val` line shape, filtered to the session window (FR-37).
- [ ] T103 [US9] Create `tests/activity/test_vault.py` pointing `vault.py` at a fixture vault tree under `tests/activity/fixtures/` and asserting the rendered counts, plus a read-only assertion that no file under the fixture vault is modified or created by a full snapshot pass.

---

## Phase 12: US-10 — The statusline is wrapped, never clobbered; prompts are redacted (P3)

- [X] T104 [US10] Create `scripts/activity/statusline-tee.sh` (FR-45): read stdin **exactly once**, forward a copy to `POST /statusline` in the background (bounded `curl --max-time`, output discarded), then delegate to the stored command from `"${SMITH_HOME:-$HOME/.smith}"/activity/wrapped-statusline`, passing the payload through unchanged. When no prior command existed, print a minimal default line rather than nothing or an error.
- [X] T105 [US10] Add statusline capture to `scripts/install.sh`: read the current `statusLine` value, write `{"had_statusline":bool,"previous":…}` to `~/.smith/activity/wrapped-statusline`, then set `statusLine` to the tee. This is a **new top-level settings key**, so it goes through `$existing * $fragment` rather than the `.hooks` rebuild (FR-45).
- [X] T106 [US10] Add SC-13 to `tests/smith-activity.test.sh`: installing over a pre-existing statusline leaves that statusline's output **byte-for-byte** unchanged (diff the captured stdout), and installing over none produces a minimal default line. This machine has a pre-existing `statusLine`, so the destructive risk is entirely the operator's own configuration.
- [X] T107 [US10] Add SC-12 to `tests/smith-activity.test.sh`: feed the tee a canned statusline payload **with** `rate_limits` and assert both windows render as percentages with reset times; feed one **without** and assert an explicit "quota unavailable" state with every other panel unaffected.
- [X] T108 [US10] Add SC-14 to `tests/smith-activity.test.sh` as the deliberately crude canary test: with `SMITH_ACTIVITY_CAPTURE_PROMPTS` unset, drive a unique canary string through a `UserPromptSubmit` payload and a `PreToolUse` `tool_input`, then `grep -c "<canary>"` across every `/api/*` response body, a captured `/events` transcript, and `~/.smith/activity/activity.log`. Expect **0** in all of them.
- [X] T109 [US10] Add the capture-enabled case to `tests/smith-activity.test.sh`: with `SMITH_ACTIVITY_CAPTURE_PROMPTS=1`, `hello.capture_prompts` is `true` and the content is present — so the opt-in is proven to actually change behavior and the default is proven to be the safe one.

---

## Phase 13: The dashboard UI (cross-cutting; serves US-1..US-9)

Written **LAST** (`plan.md` step 14): every datum it renders is already
reachable via `/api/*` and already fixture-tested. All four files are served
from `scripts/activity/static/` with **no external origin of any kind**
(FR-49).

- [X] T110 [P] Create `scripts/activity/static/index.html` (~120 lines): document shell, the panel containers, and `<template>` elements. No logic. No `<script src="http…">`, no `<link href="http…">`, no `@import url(http…)`, no web font.
- [X] T111 [P] Create `scripts/activity/static/app.css` (~220 lines): all styling, including the **four** phase states (`completed`/`current`/`remaining`/`skipped`), the two finding kinds, the settled-retraction state, and light/dark via `prefers-color-scheme`.
- [X] T112 [P] Create `scripts/activity/static/app.js` (~180 lines): the `EventSource` client, dispatch for the six event names, `generation` tracking (a **lower** daemon generation means a restart → render the OOS-3 "history reset at daemon restart" banner, never a silently truncated timeline), reconnect with `Last-Event-ID`, cold-start fetch of `GET /api/state`, and the project filter. A client that receives an unknown `event:` ignores it.
- [X] T113 Create `scripts/activity/static/panels.js` (~260 lines): one render function per panel — stepper, sessions, subagents, worktrees, tokens+quota, vault, findings. **If the stepper's four-state rendering plus the nested-handoff case pushes this past 300 lines, shed the stepper into `scripts/activity/static/stepper.js`** — the split is pre-decided (D-5/Q4).
- [X] T114 Implement the honesty surfaces in `scripts/activity/static/panels.js` and `app.js`: `phase unknown` with the last known phase and its timestamp (FR-20); the provenance badge per resolved phase (FR-19); mandatory-stop phases visually distinct from working (FR-18); SKIPPED distinct from both completed and remaining (FR-23a); a retracted finding re-rendered in an explicit **settled** state, never removed (FR-59); `usd: null` rendered as unavailable, never `$0.00` (FR-34); the `degraded[]` tokens from `hello` stated rather than hidden (A-9); the `unattributed_events` count; and the "prompt capture is ACTIVE" indicator when `capture_prompts` is true (FR-48).
- [X] T115 Add the served-asset assertions to `tests/smith-activity.test.sh`: grep the served HTML for `src`/`href` values beginning `http` or `//` and assert zero hits (FR-49/SC-15); and grep the served `panels.js` for the settled-retraction class, completing SC-20's UI half — FR-59's whole content is that a retracted finding must not be removed.

---

## Phase 14: Polish & Cross-Cutting

### Install and uninstall

- [ ] T116 Add a recursive staging block to `scripts/install.sh` copying `scripts/activity/` → `$SMITH_HOME/scripts/activity/`, mirroring the existing `scripts/smith-index` block at `:217`. **`cp -R` is required** because `phases.json` and `static/*` are neither `.sh` nor `.py` (FR-51). This must cover **all four** `scripts/activity/static/` files, not just `index.html` (D-5/Q4).
- [ ] T117 Merge the new hook entries in `scripts/install.sh` idempotently at the `(matcher, command)` level through the existing `scripts/lib/dedupehooks.jq` mechanism and the `install.sh:309-318` write guard (tempfile → `jq empty` → `mv` on success), reused unchanged. No second merge path is invented. Chain order within an entry is preserved, including the documented `file-change-logger` → `lint-on-save` → `manifest-updater` ordering (FR-51/D-9).
- [ ] T118 Stage the FR-61 shipped-hook manifest from `scripts/install.sh` into `"${SMITH_HOME:-$HOME/.smith}"/activity/`, derived from the repo's actual `hooks/` contents at install time. FR-60 forbids the daemon from reading the repo fragment, and the daemon has no reason to know where a checkout lives.
- [ ] T119 Replace `scripts/install.sh:138`'s hardcoded `"Copy 9 hooks"` preview string with a derived count (`ls hooks/*.sh | wc -l`), matching the dynamic `SKILL_TOTAL` at `:131-134`. Do not re-hardcode a number (FR-63).
- [ ] T120 Create the flat `tests/uninstall-hook-coverage.test.sh` (FR-63/SC-18) asserting that every `hooks/*.sh` the repo ships appears in `scripts/uninstall.sh`'s `SMITH_HOOKS` array, and that `scripts/install.sh`'s hook-count preview is derived rather than hardcoded. **Write and run this BEFORE T121, and observe it failing against the stale array** — a coverage test that has never been red proves nothing. Its own file, not a case inside `tests/smith-activity.test.sh`, because it guards a repo-wide invariant that outlives this feature.
- [ ] T121 Complete `scripts/uninstall.sh`'s `SMITH_HOOKS` array (`:85-91`) to **every hook the repo ships**, derived from `ls hooks/*.sh` at implementation time — **never transcribed from any count stated in `spec.md`, `plan.md` or `questions.md`** (FR-63). `activity-emitter.sh` is one entry among them, not a twelfth entry in a stale list. Verify T120 goes green.
- [ ] T122 Add the daemon-teardown and statusline-restore block to `scripts/uninstall.sh` at `:124`, **before** the wholesale `.bak-` restore, using the LaunchAgent teardown at `:59-66` as the shape precedent: stop the daemon, surgically restore or delete the `statusLine` key from the `~/.smith/activity/wrapped-statusline` sidecar via a guarded `jq`, then `rm -rf "$SMITH_HOME/activity"` (FR-52/FR-46). The restore must be idempotent and order-independent so it is safe before **or** after the `.bak-` restore, and must survive the operator declining that prompt (`:129`) and the keep-3 backup pruning (`install.sh:155`).
- [ ] T123 Ensure `scripts/uninstall.sh` removes **all four** `scripts/activity/static/` files and the whole `$SMITH_HOME/scripts/activity/` tree, not just `index.html` (FR-52/D-5/Q4). `skills/smith-activity/` needs no edit — it matches the existing `smith-*` glob at `:76`.

### Documentation

- [ ] T124 Add one row to `docs/hooks.md`'s `## Hook Summary` table and one `### activity-emitter.sh` section under `## Detailed Reference`, using the existing per-hook template verbatim (`**Event:**` / `**Matcher:**` / `**What it does:**` / `**Files touched:**` / `**To disable:**`, `:62-70`), plus a `**Privacy note:**` line following `user-prompt-logger.sh`'s precedent covering the redaction default. Correct `:3`'s stale "Smith installs 10 hooks" count, derived from `hooks/` rather than re-hardcoded (FR-53).
- [ ] T125 Add a `## Activity Daemon` section to `docs/architecture.md` after `## Scheduler Model` (`:82`), so the two background-process sections sit together. Cover the one-daemon-many-projects model, the SSE transport, ephemeral retention (OOS-3), and the trust hierarchy that makes this an audit rather than a monitor (FR-53).
- [ ] T126 Record the two-project-roots finding in `docs/architecture.md`'s new section: `scripts/create-active-workflow.sh:139` uses `git rev-parse --show-toplevel` (the **worktree**) while `hooks/workflow-gate.sh:60` uses `${CLAUDE_PROJECT_DIR:-$(pwd)}` (the **primary repo**), so a worktree's active-workflow marker is **write-only state the gate never reads**. Document the consequence for marker consumers (enumerate both vaults; tolerate an empty `session_log:`). **Do not attempt to fix it here** — OOS-8 bars workflow-skill edits and this is script/hook behavior with its own blast radius; bank it as a separate bugfix alongside BANK-030.
- [ ] T127 Extend `docs/security-model.md` (FR-50): amend `## Local-Only Execution` (`:7`) — *"no external API calls"* stays true, but a **listening loopback socket** is new and must be stated — and add a new section after `## Scheduler Security` (`:148`) covering the four additions: a loopback-bound local HTTP surface, a token-gated SSE stream, a hook-originated local POST (a first for this repo), and the redaction default.
- [X] T128 Update `README.md`: add the `/smith-activity` skill-table row and correct **all four** hardcoded counts — `:2` (the badge), `:18`, `:56` (`### Skills (33)`) and `:192` — from `33` to **35**. All four currently read 33 against 34 actual skill directories, so this feature both adds one and fixes a pre-existing off-by-one (FR-53). `install.sh:131-134` already computes the count dynamically; only the README hardcodes it.
- [ ] T129 Add a `/smith-update` step to `skills/smith-update/SKILL.md`: stop a running activity daemon before refreshing `~/.smith/scripts/activity/`, and tell the operator to re-run `/smith-activity`. A running daemon holds an older `server.py` in memory. **Do not restart it automatically** — OOS-4 rules out exactly that kind of surprise. (`smith-update` is not one of the five workflow skills OOS-8 protects.)
- [ ] T130 Append a **correction note** to `research.md` §Q6 — appended, not a rewrite of the original analysis — recording that the "guaranteed exit 3" conclusion is **false**, verified empirically on 2026-09-22: the call exited 0 and a second marker was created in the worktree's own vault (`workflow: smith-build`) while the primary repo's marker still read `workflow: smith-new`. Give the root cause (`create-active-workflow.sh:139` `--show-toplevel` vs `workflow-gate.sh:60` `${CLAUDE_PROJECT_DIR:-$(pwd)}`), the three consequences, and a pointer to the amended FR-17 derivation in `spec.md`.
- [ ] T131 Add the `[Unreleased]` → `### Added` entry to `CHANGELOG.md`, written **LAST**, after every other file is final (features 54-59's consistent ordering rule). Call out explicitly that `hooks/pricing.json` now installs and refreshes with current families, so **USD figures will start appearing in `workflow-summary.sh` output where there were none** — that is the intended repair (Q2), not a regression.

### Final verification

- [ ] T132 Run the full `tests/` directory once after every phase lands, explicitly including a check that the two pre-existing failing `--describe` tests (`tests/skills/test_smith_index_describe.sh`) still fail in the **same** way — a changed failure signature there indicates an unintended interaction. Run `tests/hooks/test_hook_chain_order.sh` **manually** (CI does not reach it) to confirm the settings-fragment additions did not disturb the `manifest-updater.sh`-last invariant.
- [ ] T133 Verify SC-16 structurally: every test file this feature adds at the top level is a flat `tests/*.test.sh` (`smith-activity.test.sh`, `uninstall-hook-coverage.test.sh`, `activity-pricing.test.sh`), every `tests/activity/test_*.py` is reachable only through T015's wrapper, and `.github/workflows/test-install.yml` needs **no** change. Confirm CI's `-ge 25` skill count and post-uninstall `smith*` count of exactly 0 both still hold with `smith-activity` added.
- [ ] T134 Run `scripts/activity/smith-activity.sh`, `scripts/activity/statusline-tee.sh`, `hooks/activity-emitter.sh` and `tests/smith-activity.test.sh` under **both `bash` and `zsh`**, per this repo's convention. Not ceremonial: `/dev/tcp` does not exist under `zsh`, which is why the port probe uses `nc`/`python3`.
- [ ] T135 Verify `lint-skills.yml:45` passes: no `/Users/…` literal anywhere in `skills/`, `hooks/`, `scheduler/`, `settings/`, `scripts/`. Everything this feature ships uses `$HOME` or `"${SMITH_HOME:-$HOME/.smith}"`.

---

## Dependencies & parallelism

| Phase | Depends on | Notes |
|---|---|---|
| 1 Setup | — | T001-T003 fully parallel |
| 2 Foundational | 1 | Emitter (T004-T007) is independent of everything else and can run in parallel with T008-T020. Within the identity core: T008 → T009; T011 → T012 → T013/T014; T016 → T017 → T018 |
| 3 US-1 | 2 (T011, T012, T016, T017, T019, T020) | All tasks edit `phases.py`; none parallel with each other |
| 4 US-2 | 3 (T025 `PhaseState`) | All edit `findings.py`; T043 fixtures can be built in parallel with T034-T042 |
| 5 US-3 | 3 | T047 edits `phases.py`; T049 fixtures parallel |
| 6 US-4 | 2 (emitter) | T051 must precede T052. T054 edits `install.sh` — never `[P]` with any other `install.sh` task |
| 7 US-8 | 2 (T008), 5 (T047 for workflow scope) | T064 blocks T068's USD assertions — do not write SC-11 expectations against `None` and then rewrite them |
| 8 US-7 | 2 (T008, T016), 3 (T025 for `died_in_phase`) | T076 extends the T009 harness |
| 9 US-6 | 3 (T028), 4 (T040), 7 (T066) | |
| 10 US-5 | 3, 4, 7, 8, 9 | `server.py` projects all of them; the first `curl /api/state` must return something true, not a stub |
| 11 US-9 | 2 (T008) | Independent of 10; sequenced here as lowest-risk |
| 12 US-10 | 10 (T086, T089) | T105 edits `install.sh` |
| 13 UI | 10, 11, 12 | T110-T112 parallel (different files); T113/T114 both edit `panels.js` |
| 14 Polish | all | T120 **before** T121 (red first). All `install.sh` tasks strictly sequential |

**`scripts/install.sh` is edited by T054, T065, T105, T116, T117, T118, T119** —
seven tasks across five phases. **None of them may carry `[P]`**, and each
should re-read the file before editing.

**`tests/smith-activity.test.sh` is edited by T003, T005, T006, T007, T009,
T015, T053, T056, T076, T097, T098, T099, T106, T107, T108, T109, T115** —
likewise never `[P]` with each other.

---

## Requirements coverage

### FR → task

| FR | Tasks |
|---|---|
| FR-1 | T094 |
| FR-2 | T093, T094, T097 |
| FR-3 | T067, T093 |
| FR-4 | T087, T098 |
| FR-5 | T090, T094 |
| FR-6 | T094, T097 |
| FR-7 | T008, T094 |
| FR-8 | T096 |
| FR-9 | T021, T025, T032 |
| FR-10 | T021 |
| FR-11 | T021, T022 |
| FR-12 | T024 |
| FR-13 | T017, T023 |
| FR-14 | T047, T048, T050 |
| FR-15 | T011 |
| FR-16 | T012, T013, T014 |
| FR-17 | T029, T032 |
| FR-18 | T027, T028 |
| FR-19 | T026, T114 |
| FR-20 | T026, T033, T114 |
| FR-21 | T042 |
| FR-22 | T035, T036, T041, T044 |
| FR-23 | T025, T037, T044, T114 |
| FR-24 | T042 |
| FR-25 | T078 |
| FR-26 | T079, T080, T081 |
| FR-27 | T066, T082 |
| FR-28 | T008, T009, T093 |
| FR-29 | T072 |
| FR-30 | T073, T074, T077 |
| FR-31 | T075 |
| FR-32 | T060 |
| FR-33 | T058, T059, T069 |
| FR-34 | T061, T114 |
| FR-35 | T067, T107 |
| FR-36 | T062 |
| FR-37 | T100, T102 |
| FR-38 | T101 |
| FR-39 | T051, T086, T089 |
| FR-40 | T004, T005, T006, T007, T056, T089 |
| FR-41 | T085, T091 |
| FR-42 | T004, T054 |
| FR-43 | T051, T052 |
| FR-44 | T016, T093, T099 |
| FR-45 | T104, T105, T106 |
| FR-46 | T122 |
| FR-47 | T088 |
| FR-48 | T086, T108, T109, T114 |
| FR-49 | T098, T110, T115 |
| FR-50 | T127 |
| FR-51 | T116, T117 |
| FR-52 | T122, T123 |
| FR-53 | T124, T125, T127, T128, T131 |
| FR-54 | T003, T015, T133 |
| FR-55 | T005-T007, T013, T032, T050, T068, T077, T097, T106 |
| FR-56 | T070 |
| FR-57 | T040, T045, T081 |
| FR-58 | T019, T022, T035 |
| FR-59 | T041, T046, T114, T115 |
| FR-60 | T038, T045 |
| FR-61 | T039, T045, T118 |
| FR-62 | T064, T065, T071 |
| FR-63 | T119, T120, T121 |

### SC → verifying task

| SC | Task |
|---|---|
| SC-1 | T031, T032 |
| SC-2 | T049, T050, T068 |
| SC-3 | T013, T014 |
| SC-4 | T005, T006, T007 |
| SC-5 | T043, T044 |
| SC-6 | T043, T044 |
| SC-7 | T009 |
| SC-8 | T076, T077 |
| SC-9 | T097 |
| SC-10 | T097 |
| SC-11 | T068 |
| SC-12 | T107 |
| SC-13 | T106 |
| SC-14 | T108, T109 |
| SC-15 | T098, T115 |
| SC-16 | T133 |
| SC-17 | T071 |
| SC-18 | T120, T121 |
| SC-19 | T045 |
| SC-20 | T046, T115 |
| SC-21 | T045 |

### Requirements with no task

**None.** Every FR-1..FR-63 maps to at least one task above, and every
SC-1..SC-21 has a task that makes it verifiable.

Two notes on the shape of that coverage rather than gaps in it:

- **SC-16 is structural, not behavioral.** T133 verifies it by inspection —
  file placement plus an unchanged `.github/workflows/test-install.yml` — since
  there is no runtime assertion that a test "runs in CI".
- **FR-55 is a meta-requirement** enumerating the suite's minimum coverage. It
  is satisfied by the union of the listed test tasks rather than by one task of
  its own.

---

## Consistency analysis (spec ↔ plan ↔ contracts ↔ tasks)

Findings, with the disposition of each. **Issues 1-3 were fixed in place**
(targeted edits, no rewrites, no renumbering); the rest are recorded.

| # | Severity | Issue | Disposition |
|---|---|---|---|
| 1 | **CRITICAL** | `plan.md` §Spec-plan tensions item 4 asserted *"one marker plus the event stream, never two markers — `smith-build` Phase 0 hits a guaranteed exit-3 on the same branch, so the marker reads `workflow: smith-new` for the entire build."* **Empirically false** — the call exits 0 and writes a second marker into the worktree's own vault. | **Fixed in `plan.md`**: item 4 rewritten to the two-marker derivation, with the root cause and the demoted phase-title fallback. |
| 2 | **CRITICAL** | `spec.md` FR-17 stated the nesting requirement with no derivation, leaving `research.md` §Q6's now-invalid single-marker inference as the only stated mechanism. | **Fixed in `spec.md`**: a derivation clause added to FR-17 naming the dual-vault marker enumeration as primary and phase-title matching as the fallback. No renumbering; no other FR touched. |
| 3 | **CRITICAL** | `quickstart.md` Scenario 6 instructed the verifier to assert *"There is **exactly one** marker and it still reads `workflow: smith-new`"* — an assertion that now fails against correct behavior, which would read as a bug in the implementation. | **Fixed in `quickstart.md`**: Scenario 6's verification step rewritten to inspect both vaults and expect two markers. |
| 4 | High | `research.md` §Q6's whole analysis is superseded. Left untouched per instruction (it is a findings record). | **Task T130** appends a correction note without rewriting the original. |
| 5 | High | `data-model.md` §1 and `plan.md`'s `markers.py` row **already** state the dual-vault reality correctly, contradicting `research.md` §Q6 and the old `plan.md` item 4 within the same artifact set. | Resolved by fixes 1-3; `data-model.md` needed no edit and got none. |
| 6 | High | `plan.md`'s NEW-files table listed four `tests/activity/test_*.py` files with no `test_markers.py`, yet the corrected marker behavior (dual-vault, empty `session_log:` fallback) is the single most load-bearing new reader contract. `sessions.py` and `vault.py` were likewise shipped with no test file. | **Fixed in `plan.md`**: `tests/activity/test_markers.py`, `test_sessions.py` and `test_vault.py` added to the NEW table, with the reason recorded inline. Tasks T018, T083 and T103. |
| 7 | Medium | `spec.md` FR-11 signal 1 and FR-58 require append-offset ordering, but `data-model.md` §2.5's `PhaseState` carries only `entered_at`/`exited_at` timestamps with no offset field. | Recorded, not fixed. T022 makes the ordering key an internal resolver concern; the timestamps stay display-only per FR-58. No artifact edit needed. |
| 8 | Medium | `spec.md` FR-43 lists a desired event set that omits `PostToolUseFailure` and `ConfigChange`, while `contracts/hook-envelope.md` §2 wires both **unconditionally** and calls `ConfigChange` load-bearing for FR-60. | Recorded. The contract is the wider and correct set; T052 wires the contract's set. Not fixed in `spec.md` because FR-43's own text already says "for any event whose availability is not confirmed … degrade rather than assume", so the contract legitimately supersedes it. |
| 9 | Medium | `spec.md` FR-63 and `plan.md` both say `SMITH_HOOKS` lists "11 of 20" hooks. The repo actually ships **19** `hooks/*.sh` plus 3 `.py` helpers and `pricing.json`. | Recorded, deliberately not "corrected": FR-63 itself forbids transcribing a count and requires derivation from `hooks/` at build time. T121 derives; T120 locks. Editing the number would invite the next reader to transcribe it. |
| 10 | Low | `plan.md` §Test strategy says the FR-16 sync test "drives the Python assertions via `python3 -m unittest tests.activity.test_phases`", while `contracts/phases-json.md` §4 says the test "lives in the flat `tests/smith-activity.test.sh`". | Recorded. Not a contradiction in substance — the flat file is the CI gate, the Python file holds the assertions. T013 + T015 implement exactly that. |
| 11 | Low | `plan.md` §File Size Policy estimates fourteen Python modules; the NEW table lists thirteen `scripts/activity/*.py` plus `phases.json`. | Recorded, cosmetic. No edit. |
| 12 | Low | `spec.md` D-5 names `scripts/activity/{server,state,phases,worktrees,usage}.py` — five modules — while `plan.md` §File Size Policy splits into thirteen. | Recorded. `plan.md` §File Size Policy explicitly supersedes D-5's sketch and `questions.md` Q4 ratified the split; tasks follow `plan.md`. |
| 13 | Low | `README.md` badge drift: `spec.md` FR-53 says the badge "currently reads 33 against 34 actual skill directories". Verified — `ls -d skills/*/` returns **34**, the badge reads 33, and four separate lines hardcode it. | No edit; T128 fixes all four to 35. |

### Tasks with no originating requirement

Three tasks exist without a direct FR, each traceable to a plan or contract
constraint rather than to spec text:

- **T010** (`tests/_harness.py` sys.path extension) — mechanical prerequisite
  for `plan.md` §Test strategy's reuse of the existing harness.
- **T095** (5 MB `activity.log` rollover) — `plan.md` §Reuse-before-create:
  *"There is no log rotation anywhere in this repo"*, and a daemon seeing every
  `PostToolUse` grows unbounded.
- **T126/T129** (architecture note + `/smith-update` daemon stop) —
  `plan.md` §Rollout notes, plus the FR-17 correction's third consequence.
