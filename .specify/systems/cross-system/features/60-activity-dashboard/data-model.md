# Data Model: `/smith-activity`

This feature has no database. Its "data model" is three things, and each is a
contract that some other component already owns or that this feature newly
defines:

1. **§2 — the daemon's in-memory state tree** — the single mutable structure
   `server.py` owns and every `/api/*` route and SSE frame projects from.
2. **§3 — `phases.json`** — the phase-chain data file (FR-15). Schema and
   invariants; the seeded content and its sync contract live in
   `contracts/phases-json.md`.
3. **§4 — the READ-ONLY external formats** this feature parses but does not
   own: marker YAML, session-log blocks, transcript JSONL and its `.meta.json`
   sidecar, and the statusline payload.

The SSE frame schema is in `contracts/sse-frames.md`; the hook envelope is in
`contracts/hook-envelope.md`. Both are referenced here rather than restated.

Every entity in the spec's Key Entities section appears below with its fields,
its lifecycle, and its home in the state tree.

---

## §1 — Identity, and the one rule everything else depends on

**A project is its primary repo, resolved once, and every other key hangs off
it.**

```python
def primary_repo(path: str) -> str | None:
    """FR-28. Absolute path to the primary checkout, or None if not a repo."""
    out = git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return os.path.dirname(out) if out else None
```

`--path-format=absolute` is load-bearing: from inside a worktree,
`--git-common-dir` returns an absolute path to the primary `.git`, but from
inside the primary repo it returns the relative string `.git`. Verified from
both positions. Without the flag, `dirname` of `.git` is `""`.

Why this is the root rule (FR-28):

| Source | What it reports | Trustworthy for identity? |
|---|---|---|
| `CLAUDE_PROJECT_DIR` | stays pinned to the **primary** repo | yes, but not always set |
| hook payload `cwd` | the **worktree** | no |
| `claude agents --json` `cwd` | the **worktree** | no |
| transcript `cwd` | the **worktree** | no |
| transcript `gitBranch` | captured at session start; **does not follow cwd** | no — see `research.md` §R.10 |
| `git rev-parse --show-toplevel` | the **worktree** | no |
| `git rev-parse --git-common-dir` | the **primary** repo | **yes** |

Note the repo itself is inconsistent about this: `workflow-gate.sh:61-70` uses
`--git-common-dir` (primary) while `create-active-workflow.sh:139` uses
`--show-toplevel` (worktree). **Markers are therefore written into the
worktree's `.smith/vault/`, which for a `/tmp/smith-<slug>` worktree is a
different tree from the primary vault the hooks write to.** The daemon must
enumerate markers under **both** the primary repo and every live worktree, and
key the resulting records by primary repo. This is stated here so a reader does
not assume one marker directory per project.

Consequences enforced everywhere below: a worktree never becomes a second
project (SC-7); branch is always derived by a debounced
`git -C <cwd> rev-parse --abbrev-ref HEAD`, never read from a transcript.

---

## §2 — The daemon state tree

One `ActivityState` object, owned by `state.py`, guarded by a single
`threading.RLock`. Everything else — SSE frames, `/api/*` responses, findings —
is a pure projection of it. **Retention is ephemeral** (OOS-3): this tree is
the whole history, it lives only in memory, and a daemon restart is a blank
slate the UI announces rather than hides.

```
ActivityState
├── generation: int                      # monotone; bumped per coalesced broadcast
├── started_at: str                      # ISO-8601 Z, daemon start
├── capture_prompts: bool                # SMITH_ACTIVITY_CAPTURE_PROMPTS == "1"
├── expected_hooks: {event: [command]}   # FR-60 / research.md §Q3; parsed from the
│                                        #   INSTALLED ~/.claude/settings.json, refreshed
│                                        #   on ConfigChange. None when undeterminable —
│                                        #   absence detection is then DISABLED with a
│                                        #   visible UI notice, never guessed
├── shipped_hooks: [command] | None     # FR-61; the manifest install.sh stages under
│                                        #   ~/.smith/activity/. Diffed against
│                                        #   expected_hooks to raise shipped_not_wired
├── quota: QuotaWindows | None           # account-wide, never project-scoped
├── projects:  {primary_repo_path: Project}
├── sessions:  {session_id: Session}
├── subagents: {agent_id: Subagent}
├── workflows: {workflow_key: Workflow}
└── findings:  {finding_id: Finding}
```

Four of the five maps are keyed by an identifier the harness supplies;
`workflows` is keyed by a composite this feature defines (§2.4).

### §2.1 — `Project`

| Field | Type | Source | Notes |
|---|---|---|---|
| `path` | str | §1 | the map key; absolute primary-repo path |
| `name` | str | `os.path.basename(path)` | display only |
| `registered_at` | str | daemon | ISO-8601 Z |
| `vault_dir` | str \| None | `<path>/.smith/vault` | `None` when absent — a valid state |
| `index_dir` | str \| None | `<path>/.smith/index` | drives "index freshness" (FR-37) |
| `worktrees` | [Worktree] | `git worktree list --porcelain` | §2.6 |
| `vault` | VaultSnapshot | §2.8 | |
| `poll_state` | dict | internal | per-file `(mtime, size, offset)` for stat-based change detection (FR-38) |

**Lifecycle.** Created by `POST /api/register` (from `/smith-activity` run
anywhere inside the repo, including a worktree — FR-2/SC-7) or implicitly on
the first ingested event whose `cwd` resolves to a new primary repo. Persisted
across restarts only as a path list in
`~/.smith/activity/projects.json`; all derived content is rebuilt. Never
deleted while the daemon runs.

### §2.2 — `Session`

| Field | Type | Source |
|---|---|---|
| `session_id` | str | envelope `session_id` (map key) |
| `pid` | int \| None | `claude agents --json` `pid` |
| `name` | str \| None | `claude agents --json` `name` |
| `kind` | str \| None | `claude agents --json` `kind` (only `interactive` observed) |
| `model` | str \| None | transcript `message.model` |
| `started_at` | str | `startedAt` (epoch **ms**) or first ingest |
| `last_event_at` | str | any ingest |
| `cwd` | str | envelope `cwd` — the **worktree** |
| `project` | str | §1 of `cwd` |
| `branch` | str \| None | `git -C cwd rev-parse --abbrev-ref HEAD`, debounced 3 s |
| `worktree` | str \| None | matched against `git worktree list` |
| `transcript_path` | str \| None | envelope `transcript_path` |
| `permission_mode` | str \| None | envelope `permission_mode` |
| `state` | enum | see below |
| `pending_permission` | dict \| None | `{prompt_id, tool_name, since}` |
| `usage` | TokenRollup | §2.7 |
| `jsonl_offset` | int | remembered byte offset for incremental tail |

**`state` — three values, and how each is actually derived.**
`research.md` §Q8 establishes that `claude agents --json` on the installed
v2.1.269 returns only `{pid, cwd, kind, name, sessionId, startedAt, status?}`.
There is **no `waitingFor`**, no `state`, no `id`. So:

| Value | Derivation | Precedence |
|---|---|---|
| `waiting_permission` | `PermissionRequest` ingested with no `PermissionDenied` / `PostToolUse` for the same `prompt_id` | 1 — hook-sourced, so it wins under FR-21 |
| `working` | `status == "busy"`, else an ingest within the last 30 s | 2 |
| `idle` | `status == "idle"`, else no ingest for 30 s | 3 |

`status` is present on only ~26% of records (6 of 23 observed), so the
ingest-recency fallback is the common path, not the exception.

**Lifecycle.** Created on first ingest or first appearance in a poll. Removed
when `SessionEnd`/`Stop` is ingested **or** when it is absent from a
`claude agents --json` poll — the FR-24 reaper, which is the only thing that
catches a session that died without firing anything.

### §2.3 — `Subagent`

Primary source is the **`.meta.json` sidecar**, not a hook (`research.md` §Q4).

| Field | Type | Source |
|---|---|---|
| `agent_id` | str | sidecar filename `agent-<id>.meta.json` (map key) |
| `agent_type` | str | sidecar `agentType` |
| `description` | str | sidecar `description` |
| `parent_agent_id` | str \| None | sidecar `parentAgentId` |
| `spawn_depth` | int | sidecar `spawnDepth` |
| `request_shape` | str | sidecar `requestShape` — `foreground` \| `background` |
| `tool_use_id` | str | sidecar `toolUseId` — correlates to the `PreToolUse Task` event |
| `model` | str \| None | sidecar `model`, else transcript `message.model` |
| `session_id` | str | parent directory name |
| `started_at` | str | sidecar file ctime, or `SubagentStart` ingest when earlier |
| `ended_at` | str \| None | `SubagentStop` ingest |
| `usage` | TokenRollup | incremental tail of `agent-<id>.jsonl` (§2.7) |
| `jsonl_offset` | int | remembered byte offset |

Real sidecar, read verbatim from this session:

```json
{"agentType":"Explore","description":"Investigate markers and workflows",
 "toolUseId":"toolu_01XcnzT6yNkhxPNPE6E5EqFk","parentAgentId":"a15f48d273d84cb99",
 "spawnDepth":2,"requestShape":"background","requestNonInteractive":true}
```

`tool_use_id` is the key that makes FR-22(a) precise: it ties the sidecar
back to the exact `PreToolUse Task` event, so "this dispatch has no log block"
names a specific dispatch rather than a time range.

**Lifecycle.** Discovered on the ~1 s sidecar poll, or earlier via a
`SubagentStart` ingest. Marked complete on `SubagentStop` or when its `.jsonl`
stops growing for 60 s. Retained after completion so the workflow rollup and
the findings that reference it stay coherent.

### §2.4 — `Workflow` — the unit of attribution

**Not** the session, and **not** the session log. Two concurrent workflows
share one session log file — observed live in this repository while this
feature was being specified:

```
.smith/vault/active-workflows/60-activity-dashboard.yaml
  workflow: smith-new   branch: 60-activity-dashboard
  worktree: /tmp/smith-activity-dashboard
  session_log: …/sessions/dennis-plucinik_ad8161_2026-09-22_145028.md

.smith/vault/active-workflows/67-deterministic-questions.yaml
  workflow: smith-new   branch: 67-deterministic-questions
  worktree: /tmp/smith-deterministic-questions
  session_log: …/sessions/dennis-plucinik_ad8161_2026-09-22_145028.md   ← SAME FILE
```

| Field | Type | Source |
|---|---|---|
| `key` | str | `f"{project}\|{marker_filename}"` — the map key |
| `workflow_type` | str | marker `workflow:` |
| `slug` | str | marker `feature:` |
| `branch` | str | marker `branch:` — may name no real git ref (`debug-*`, audit labels) |
| `worktree` | str \| None | marker `worktree:` — **absent in `smith-finish` markers** |
| `session_log` | str \| None | marker `session_log:` — **absent in `smith-finish` markers** |
| `started` | str | marker `started:` — tolerate with and without trailing `Z` |
| `declared_phase` | str \| None | marker `phase:` — **nothing writes one today** (FR-13) |
| `marker_path` | str | absolute |
| `phases` | [PhaseState] | §2.5 |
| `current_phase_id` | str \| None | `None` renders `phase unknown` (FR-20) |
| `last_known_phase` | (id, ts) \| None | required alongside `phase unknown` |
| `provenance` | enum | which signal resolved the phase (FR-19) |
| `parent_key` / `child_keys` | str / [str] | nesting (FR-17) |
| `usage` | TokenRollup | only its own attributed usage (FR-14) |
| `attributed_events` | [event_id] | append-only |

**The map key is `(project, marker_filename)`, not `(project, branch).**
`smith-finish` writes `finish-<safe-branch>.yaml` alongside a possible
`<safe-branch>.yaml`, so two markers can legitimately exist for one branch.

**Attribution rule (FR-14 / SC-2).** Every event is assigned to at most one
workflow, by this precedence:

1. `event.cwd` (or the subagent's `cwd`) is inside the marker's `worktree:` →
   that workflow. Exact string prefix on realpathed absolute paths.
2. The resolved branch of `event.cwd` equals the marker's `branch:` → that
   workflow.
3. A session-log block textually names a mapped phase whose chain matches
   exactly one candidate marker's `workflow:` → that workflow.
4. Otherwise **unattributed** — counted, surfaced in the findings panel as
   "N events could not be attributed", and assigned to **no** workflow.

Rule 4 is the one that makes SC-2 achievable: an ambiguous event is dropped
rather than duplicated. "No block is attributed to more than one" is a
structural property of a single-assignment pass, not a heuristic.

**Lifecycle.** Created when a marker file appears. Updated on marker mtime
change. Marked `ended` when the marker is removed — by
`clear-active-workflow.sh` or by `active-workflow-janitor.sh`'s sweep — and
retained for the daemon's lifetime so its findings remain readable.

### §2.5 — `PhaseState`

One per entry in the workflow's `phases.json` chain, plus derived state.

| Field | Type | Notes |
|---|---|---|
| `id` / `number` / `title` | str / str / str | from `phases.json` |
| `mandatory_stop` | bool | from `phases.json` |
| `state` | enum | `completed` \| `current` \| `remaining` \| `skipped` |
| `provenance` | enum \| None | `marker_phase` \| `subagent_block` \| `live_task_event` \| `skill_event` \| `workflow_start` \| `subagent_completion` \| `artifact` |
| `entered_at` / `exited_at` | str \| None | ISO-8601 Z |
| `evidence` | str | one line naming the exact signal — the finding's citation |

`number` is a **string** (`"3.5"`, `"5.5"`, `"6.5"`), compared as a decimal.
Four of the five chains contain fractional phases.

**`skipped` is a first-class value, not the absence of `completed`** (FR-23a /
SC-6): a phase is `skipped` when a *later* phase in the same chain reached
`current` or `completed` while this one never did. It renders distinctly from
both `completed` and `remaining` and emits exactly one absence finding.

**Signal precedence — FR-11's order, with the FR-13 override on top:**

| # | Signal | Provenance |
|---|---|---|
| 0 | marker `phase:` field | `marker_phase` — **beats everything**, even though nothing writes it today (FR-13) |
| 1 | `### [HH:MM:SS] Subagent invoked: <desc>` block | `subagent_block` |
| 2 | live `PreToolUse` `Task` event | `live_task_event` — advance optimistically, reconcile within the window |
| 3 | `### [HH:MM:SS] /smith-<skill> <event>` entry | `skill_event` |
| 4 | `workflow-start` stamp | `workflow_start` |
| 5 | `Subagent completed` block | `subagent_completion` — the phase is **DONE**, not running |
| 6 | artifact presence | `artifact` — corroboration and cold-start fallback |

**A file READ never advances a phase** (FR-12). The concrete case:
`smith-build` Phase 3.5 reads `skills/smith-clean-code/SKILL.md` as a rubric.
A Read produces no skill-invocation event, so there is nothing to mistake — the
rule is enforced by *only* consuming the seven signals above, none of which a
Read produces.

**Artifact corroboration covers both layouts** (FR-12):

| Artifact | Implies |
|---|---|
| `spec.md` | Phase 3 complete |
| `plan.md` | Phase 4 complete |
| `questions.md` | Phase 4 complete |
| `questions.md` with unanswered items | sitting at the Phase 5 gate |
| `tasks.md`, n of N boxes checked | mid-implementation at n/N |

Searched under **both** `specs/<n>-<slug>/` and
`.specify/systems/<system>/features/<n>-<slug>/`, in the **worktree** first
(where the workflow is executing) then the primary repo.

**Unknown workflow type.** A marker whose `workflow:` has no `phases.json`
entry yields a workflow with an **empty** `phases` list, `current_phase_id`
`None`, and the note `no phase map entry`. The resolver never invents a chain.

### §2.6 — `Worktree`

| Field | Type | Source |
|---|---|---|
| `path` | str | `git worktree list --porcelain` |
| `branch` | str \| None | same (detached HEAD → `None`) |
| `head` | str | same |
| `is_primary` | bool | `path == project.path` |
| `base_branch` | str \| None | `skills/smith/scripts/get-base-branch.sh` |
| `ahead` / `behind` | int \| None | `git rev-list --left-right --count origin/<base>...HEAD`; `None` when no remote ref |
| `dirty_count` | int | `git status --porcelain \| wc -l` |
| `owning_marker` | str \| None | marker whose `worktree:` matches |
| `occupying_session` | str \| None | session whose resolved worktree matches |
| `classification` | enum | `primary` \| `active` \| `held` \| `missing` \| `orphaned` |
| `age_s` | int | from the owning marker's `started` |
| `died_in_phase` | str \| None | last `current` phase of the owning workflow |

**Classification decision table (FR-30 / SC-8). Evaluated top to bottom; first
match wins.**

| # | Condition | Class | UI says |
|---|---|---|---|
| 1 | `path == project.path` | `primary` | marked distinctly; shows its own branch |
| 2 | marker exists, path **not on disk** | `missing` | "`git worktree prune` clears it" |
| 3 | marker exists, path on disk, branch merged into base **or** branch gone | `orphaned` | "pending `active-workflow-janitor.sh` sweep" — **never** an active workflow |
| 4 | marker exists, path on disk, branch unmerged, owning workflow not advancing | `held` | age + the phase it died in |
| 5 | marker exists, otherwise | `active` | normal |
| 6 | no marker | `active` | no owning marker |

Row 3 before row 4 is deliberate: a merged-and-deleted branch whose marker
survives is the janitor's backlog, not a stalled bugfix, and rendering it as
an active workflow is the exact phantom FR-30 forbids.

Row 4's "not advancing" is the workflow having no signal newer than its
`current` phase's `entered_at` for longer than the HELD threshold (10 minutes,
a named constant). The `held` case exists because `/smith-bugfix` deliberately
*preserves* the worktree when a phase fails pre-merge.

`git` is invoked per worktree on a ~3 s debounce and cached (FR-31); **never
per SSE frame.**

### §2.7 — `TokenRollup`

| Field | Type |
|---|---|
| `input` / `output` / `cache_write` / `cache_read` | int |
| `normalized` | int — `workflow_summary_lib.normalize()` |
| `usd` | float \| **None** |
| `model` | str \| None |
| `unknown_models` | [str] |
| `scope` | `session` \| `workflow` \| `subagent` |

`usd is None` means **unavailable**, and the UI renders it as such —
**never `$0.00`** (FR-34). This is the primary path today, not an edge case:
the live model id is `claude-opus-5` and `hooks/pricing.json`'s newest family
is `claude-opus-4-6*`, so `match_family()` returns `None` for every current
session (`research.md` §Q4).

Rates are obtained **only** via `workflow_summary_lib.load_pricing()` (FR-33's
contract trap: `match_family` reads a `_compiled_patterns` key that only
`load_pricing` injects, and `.get(…) or []` makes a raw dict degrade silently
to "no match").

Sources by scope:

| Scope | Source |
|---|---|
| `session` | `parse_parent_jsonl` over the parent transcript |
| `subagent` | incremental tail of `subagents/agent-<id>.jsonl`, assistant rows only — **new code** (FR-36), because the parent transcript contains zero `isSidechain` rows |
| `workflow` | sum of attributed sessions + attributed subagents, plus `parse_subagent_blocks` for agents that finished before the daemon started |

Malformed JSONL lines are skipped and never abort a rollup, matching
`parse_parent_jsonl`'s existing tolerance (FR-33/FR-36).

### §2.8 — `VaultSnapshot` (FR-37/FR-38) — READ-ONLY

```
VaultSnapshot
├── recent_sessions: [{path, mtime, started, ended, size}]
├── ledger: {category: count, meta: {...}}
├── queue: {depth: int, last_scheduler_run: str|None, history_count: int}
├── bank: {count: int, recent: [{id, title, status}]}
├── agents: {agent_type: finding_count}
├── index: {exists, schema_version, last_built, file_count, stale: bool}
└── friction: {gate_denials, security_blocks, grade_retries}
```

Polled by `stat`-based change detection at ~1 s (FR-38) — Python stdlib has no
inotify. Sources exactly as FR-38 lists: `active-workflows/*.yaml`,
`.current-session*`, `sessions/*.md` (the `## Metrics` block and the
file-change lines), `ledger/*.md` + `meta.yaml`, `queue/` + `queue/history/`,
`bank/`, `agents/<type>/*.md`, `.smith/index/`, `~/.smith/projects.json`,
`~/.smith/scheduler/scheduler.log`.

The three `friction` counters come from `~/.smith/logs/hooks.log`, the shared
log every hook writes with the `<ISO8601Z> <hookname> key=val` line shape —
counted by hook name, filtered to the session window.

**This snapshot is produced by reads only.** The daemon opens no file under
any project's `.smith/vault/` for writing, ever (US-9, FR-44).

### §2.9 — `QuotaWindows` — global, never project-scoped

| Field | Type |
|---|---|
| `five_hour` | `{used_percentage: float, resets_at: int}` \| None |
| `seven_day` | same \| None |
| `spend_limit` | same \| None |
| `received_at` | str |
| `available` | bool |

`resets_at` is **Unix epoch seconds**, not ISO-8601 — the UI formats it.
Sourced solely from the statusline payload, which is the only authoritative
source for the 5h/7d rolling windows. Absent `rate_limits` → `available:
false`, the quota panel renders an explicit "unavailable" state, and nothing
else degrades (FR-35/SC-12). Returned unchanged under every project filter,
because the windows are account-wide (FR-3).

### §2.10 — `Finding` — divergence and absence

One type, two kinds, so the panel renders one ordered list.

| Field | Type |
|---|---|
| `finding_id` | str — deterministic hash of `(kind, classification, subject)` so a finding is stable across broadcasts |
| `kind` | `divergence` \| `absence` |
| `classification` | see below |
| `severity` | `info` \| `warn` |
| `workflow_key` / `phase_id` | str \| None |
| `observed` / `self_reported` | str \| None — FR-21 requires **both** shown |
| `timestamp` | str |
| `evidence` | str — the file:line or event id that establishes it |
| `retracted` | bool — set when a late block or event lands inside the **90 s two-sided** window (`research.md` §Q2, FR-22). **Retraction is a state transition, not a deletion**: the finding stays in the list, re-rendered in an explicit settled state, because FR-59 forbids it from silently disappearing. The daemon therefore re-`upsert`s it; `findings.remove` is reserved for a finding whose subject no longer exists |

**Divergence classifications (FR-22):**

| Classification | Trigger |
|---|---|
| `skill_logging_bug` | a `Task` dispatch the harness observed with no matching `Subagent invoked:` block within the 90 s reconciliation window |
| `undesigned_path` | an artifact appeared with no preceding dispatch or skill-invocation event in the attributed stream |
| `marker_contradiction` | the marker's `workflow:` contradicts the observed event sequence — e.g. a signal matching another chain while the parent is not at a declared handoff phase |
| `permission_disagreement` | **FR-57** — `claude agents --json` reports a `status` for the session AND it disagrees with the event-derived permission state (FR-18). `observed` = the event-derived state, `self_reported` = the polled `status`. A record with **no** `status` produces nothing: absence of corroboration is not disagreement |
| `shipped_not_wired` | **FR-61** — a hook Smith ships that the installed `~/.claude/settings.json` does not wire ("Smith ships this, your settings don't wire it"). Distinct from `hook_never_fired`, which is "wired but never fired". The shipped side comes from the manifest `install.sh` stages under `~/.smith/activity/`, never from the repo checkout |

**Absence classifications (FR-23):**

| Classification | Trigger |
|---|---|
| `phase_skipped` | a chain entry passed over; the phase renders `skipped` |
| `gate_never_reached` | a `mandatory_stop` phase the workflow advanced past or ended before |
| `hook_never_fired` | a hook **wired in the installed `~/.claude/settings.json`** that never fired for a session where the §Q3 applicability table says it should have (FR-60). When that file is unreadable, absence detection is **disabled** with a visible UI notice and this classification is never emitted — it is never guessed from a shipped default set |

**Every finding is advisory. Nothing in this feature modifies, pauses, or
interferes with the workflow it is auditing** (FR-24).

`marker_contradiction` is the classification the `smith-new → smith-build`
handoff would trip *if* the handoff were undesigned. It is not, so the
handoff phases carry an explicit `handoff` key in `phases.json` (§3) — which
is precisely why that key exists: it is the difference between "a known
handoff" and "an undesigned path", and without it every single `/smith-new`
run would emit a false `marker_contradiction`.

---

## §3 — `phases.json` schema (FR-15)

**Data, not code. Phase lists MUST NOT be hardcoded in Python.** Ships at
`scripts/activity/phases.json`; installed to
`~/.smith/scripts/activity/phases.json`.

```json
{
  "$comment": "Ordered phase chains per Smith workflow. Data, not code. Kept in sync with each SKILL.md by tests/smith-activity.test.sh (FR-16).",
  "version": 1,
  "workflows": {
    "<workflow-type>": {
      "source": "skills/<workflow-type>/SKILL.md",
      "heading_level": 2,
      "heading_keyword": "Phase",
      "phases": [
        {
          "id":    "<workflow-type>:<number>",
          "number": "0",
          "title": "Pre-Change Exploration",
          "match": ["Pre-Change Exploration", "smith-explore"],
          "mandatory_stop": false,
          "handoff": []
        }
      ]
    }
  }
}
```

### Per-phase fields

| Field | Type | Required | Meaning |
|---|---|---|---|
| `id` | str | yes | globally unique; `<workflow>:<number>` |
| `number` | str | yes | **string**, compared as a decimal — `"3.5"`, `"5.5"`, `"6.5"` all occur |
| `title` | str | yes | normalized heading title; see the sync contract |
| `match` | [str] | yes | case-insensitive substrings tried against signal text, in order |
| `mandatory_stop` | bool | yes | FR-18 — renders distinctly, never as "working" |
| `handoff` | [str] | no | workflow types this phase may legitimately hand off to (FR-17); absent ⇒ `[]` |

### Per-workflow fields

`source`, `heading_level` (2 for the four `## Phase` skills, **3** for
`smith-finish`'s `### Step`) and `heading_keyword` (`Phase` / `Step`) exist so
the FR-16 sync test is driven by the same data file rather than by a hardcoded
extractor. They are the only reason the test can cover five files with two
different heading dialects without branching.

### Invariants, all asserted by `tests/smith-activity.test.sh`

1. Every `id` is unique across all workflows.
2. `number` values within a chain are strictly increasing as decimals.
3. No two phases in **different** chains share an identical `match` pattern.
   (The real collision this guards: `smith-bugfix` 3.5 and `smith-debug` 5.5
   share the title *"Update `.meta` Descriptions for Touched Methods"*, so at
   least one of their `match` entries must be workflow-qualified.)
4. Every `handoff` value names a workflow present in the file.
5. The extracted `(number, title)` pairs match each `source` SKILL.md exactly —
   same set, same order, same numbers (FR-16/SC-3).

The seeded content and the title-normalization rules are in
`contracts/phases-json.md`.

---

## §4 — READ-ONLY external formats

Formats this feature parses but does not own. Reproduced exactly so the parser
is written against reality rather than against the spec's paraphrase.

### §4.1 — Active-workflow marker

Six plain, unquoted `key: value` lines, written to a tempfile then `mv -f`
(`create-active-workflow.sh:181-187`):

```yaml
workflow: smith-new
feature: activity-dashboard
branch: 60-activity-dashboard
worktree: /tmp/smith-activity-dashboard
session_log: /Users/x/proj/.smith/vault/sessions/dennis-plucinik_ad8161_2026-09-22_145028.md
started: 2026-09-22T15:18:00Z
```

Parser requirements:

- **Tolerate optional surrounding quotes** on values, per
  `active-workflow-janitor.sh:118`'s own precedent (the collision check at
  `create-active-workflow.sh:159` does not, which is a latent false-collide).
- **`session_log:` may be empty** — a trailing space and nothing after it is a
  valid, occurring shape (`create-active-workflow.sh:170-174` falls back to
  empty when neither `--session-log` nor `.current-session` resolves).
- **`branch:` may name no real git ref** — `debug-<slug>`
  (`smith-debug/SKILL.md:96-104`) and `/smith-audit`'s synthetic labels.
- **`smith-finish`'s variant has 4 fields and no trailing `Z`** (`research.md`
  §Q1): no `worktree:`, no `session_log:`, filename `finish-<safe>.yaml`.
- **`phase:`** — accepted if ever present, preferred over everything (FR-13).
  Nothing writes one today.
- Filename: `<branch with [^A-Za-z0-9._-] → ->.yaml`, so `fix/log` →
  `fix-log.yaml`.

### §4.2 — Session-log blocks

**Written by skill prose (model-authored), best-effort:**

```markdown
### [HH:MM:SS] Subagent invoked: <description>

**Type:** <subagent_type or "general">
**Model:** <model override, or "inherited">
```

```markdown
### [HH:MM:SS] /smith-<skill> <event>

**User Request:**
> <verbatim user message>

**Synthesized Input:** <...>
**Outcome:** <...>
**Artifacts:** <...>
**Systems affected:** <...>
```

**Written by hooks (reliable):**

```markdown
### [HH:MM:SS] Subagent completed

**Metrics:**
- model: claude-sonnet-4-5
- input_tokens: 1204
- output_tokens: 3311
- cache_creation_input_tokens: 0
- cache_read_input_tokens: 88210
- tool_uses: 17
- duration_ms: 42180
- total_tokens: 92725
```

```markdown
### [HH:MM:SS] workflow-start <BRANCH>

**Workflow:** smith-new
**Feature:** activity-dashboard
**Worktree:** /tmp/smith-activity-dashboard
**Marker:** /Users/x/proj/.smith/vault/active-workflows/60-activity-dashboard.yaml
```

Line formats, which must be told apart:

```
- `[15:36:26]` **Bash** in:184 out:1475 total:1659 (grep -rn "Subagent invoked"…)   ← metrics-tracker.sh
- `[14:16:03]` **Edit** `skills/smith-new/SKILL.md`                                  ← file-change-logger.sh
```

Both backtick the timestamp; only `file-change-logger.sh` backticks the path,
while `metrics-tracker.sh` wraps its identifier in bare parens and truncates a
Bash command at 60 chars with a `…` (U+2026). Entries with `total < 10` are
skipped by `metrics-tracker.sh` entirely.

**Four parser facts that are easy to get wrong:**

1. **`## Metrics` is created once and appended to forever**
   (`metrics-tracker.sh`), so later `###` event blocks land *physically after*
   it. The file is append-ordered, never section-ordered. Do not assume
   `## Metrics` is a trailing section.
2. **The `Subagent completed` block carries no description and no type** —
   the heading is the bare literal. Pairing an invocation to its completion is
   positional/temporal only. `subagent-vault-writeback.sh`'s own header
   (`:13-19`) documents that for parallel fan-outs "per-invocation pairing may
   shift" because the `SubagentStop` payload has no `agent_id` and the hook
   picks the most-recently-modified `agent-*.jsonl`. **The `.meta.json`
   sidecar's `toolUseId` (§2.3) is strictly better and is what this feature
   pairs on.**
3. **Two clocks in one file.** Every hook writes UTC (`date -u`,
   `datetime.now(timezone.utc)`). Model-authored blocks use whatever the model
   types — observed local, a 4-hour skew, in this repository's own log
   (`research.md` §Q2). Correlate on append order, not on parsed time.
4. **`.current-session` can be repointed mid-workflow** by a `SessionStart`
   rollover. Reuse `workflow-summary.sh:84-135`'s three-tier recovery
   verbatim: explicit path → marker `session_log:` (disambiguated by
   `branch:`) → `.current-session`.

Session-log path is a single line in `.smith/vault/.current-session`; the
canonical per-user pointer is `.current-session-<name-slug>`, and every one of
~29 existing consumers reads the legacy alias. Read idiom
(`metrics-tracker.sh:23-32`) checks **both** the pointer and its target for
existence.

### §4.3 — Transcript JSONL and sidecar

```
~/.claude/projects/<slug>/<session-id>.jsonl                      ← parent
~/.claude/projects/<slug>/<session-id>/subagents/
    agent-<agent-id>.jsonl                                        ← sidechain turns
    agent-<agent-id>.meta.json                                    ← dispatch metadata
```

`<slug>` is the project path with `/` → `-`
(`-Users-dennisplucinik-Projects-smith-repo`), and it is keyed on the **primary
repo**, confirming §1's rule from a second direction.

Assistant row, verbatim:

```json
{"agentId":"a4e8cbb1161fec729","isSidechain":true,"type":"assistant",
 "sessionId":"046b6482-…","cwd":"/private/tmp/smith-activity-dashboard",
 "gitBranch":"main","timestamp":"2026-09-22T15:06:30.738Z",
 "message":{"model":"claude-opus-5","usage":{"input_tokens":2,
   "cache_creation_input_tokens":13755,"cache_read_input_tokens":4155,
   "output_tokens":8,"service_tier":"standard"}}}
```

- The `message.usage` shape is **identical** parent-side and sidechain-side, so
  the same summation works for both.
- **`gitBranch` is wrong here** — that worktree is on `60-activity-dashboard`,
  not `main`. Never trust it (§1, `research.md` §R.10).
- The parent transcript contains **zero** `isSidechain: true` rows
  (`grep -c` → 0 over 360 lines), which is why FR-36 is not optional.
- Rows are large; files reach hundreds of KB. Tail incrementally from a
  remembered byte offset, never re-read.

### §4.4 — Statusline payload (FR-35)

Delivered on stdin to the `statusLine` command. Relevant subset:

```json
{
  "session_id": "…", "prompt_id": "…", "transcript_path": "…", "cwd": "…",
  "model": {"id": "claude-opus-5", "display_name": "Opus"},
  "workspace": {"current_dir": "…", "project_dir": "…", "git_worktree": "…"},
  "context_window": {"used_percentage": 8, "context_window_size": 200000, "…": "…"},
  "cost": {"total_cost_usd": 0.01234, "…": "…"},
  "rate_limits": {
    "five_hour":   {"used_percentage": 23.5, "resets_at": 1738425600},
    "seven_day":   {"used_percentage": 41.2, "resets_at": 1738857600},
    "spend_limit": {"used_percentage": 62.8, "resets_at": 1740787200}
  }
}
```

`rate_limits` may be **absent entirely** — before the first API response, or on
non-subscription auth (FR-35/SC-12). `resets_at` is epoch **seconds**.

`workspace.project_dir` is the primary repo and `workspace.current_dir` is the
worktree, so the payload independently confirms §1's distinction. `cost` and
`context_window` give a free cross-check against §2.7's own rollup — a
material disagreement between them is itself a divergence finding, and it is
the only cross-check in this feature that does not depend on Smith's own
self-reports at all.
