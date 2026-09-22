---
feature: 60-activity-dashboard
primary_system: cross-system
also_affects: []
branch: 60-activity-dashboard
created: 2026-09-22
status: in-progress
---

# `/smith-activity` — Local Real-Time Smith Activity Audit Dashboard

## Summary

A new Smith skill, `/smith-activity`, that starts a local, on-demand daemon
and opens a browser dashboard giving the operator **x-ray vision into Smith's
own plumbing** — which Claude Code sessions are alive, which subagents are
dispatched, which numbered phase of which Smith workflow is executing right
now, in which worktree on which branch, at what token cost, against which
rolling quota window, backed by which vault state.

The framing that drives every tradeoff in this spec is the user's own:

> "I want to know how Smith is being used — x-ray vision into the
> behind-the-scenes plumbing and activity that is happening so I can verify
> that it is behaving the way I intended. It is basically a Smith activity
> audit for me."

This is an **audit tool, not a status monitor**. A status monitor answers
"is it working?". An audit answers "is it doing what I designed it to do,
and where is it not?". The difference is load-bearing and produces two
first-class capabilities that a status monitor would not have:

1. **A trust hierarchy between data sources.** Hook events are emitted by the
   Claude Code harness and are independent of whether Smith's skill prose is
   correct. Session-log and vault content is Smith **self-reporting**. An
   audit cannot rely solely on a system's own self-reports. Hook events are
   therefore the ground-truth spine; vault content is annotation on that
   spine. Where the two disagree, the disagreement is not noise to be
   smoothed over — **the divergence IS the audit signal**, and the dashboard
   surfaces it as a finding.
2. **Absence detection.** The dashboard must show what *didn't* happen — a
   phase skipped, a gate never reached, a hook that never fired, a subagent
   the harness dispatched that never wrote its log block. Absence is harder
   to render than presence and is specified explicitly rather than left to
   fall out of the presence rendering.

Everything runs locally. One daemon serves every project on the machine. The
transport is Server-Sent Events. No new dependencies: bash, git, jq, and
Python 3 stdlib only.

**Terminology used throughout this spec:**

- **Daemon** — the single long-lived Python 3 process started by
  `/smith-activity`, bound to `127.0.0.1` only, serving the dashboard, the
  SSE stream, the JSON API, and the hook ingest endpoint. One daemon per
  machine, serving all registered projects.
- **Emitter** — the hook-side path that delivers a Claude Code hook event to
  the daemon's ingest endpoint. Either a native `"type": "http"` settings
  entry (no process spawn) or `hooks/activity-emitter.sh` as the fallback.
- **Ground-truth spine** — the ordered stream of harness-emitted hook events
  for a session. Authoritative about what the harness *did*.
- **Self-report** — anything Smith wrote about itself: session-log blocks,
  active-workflow markers, ledger entries, queue state, vault artifacts.
  Authoritative about what a skill *claims* it did.
- **Divergence finding** — a surfaced, named disagreement between the spine
  and a self-report (or between a self-report and the artifacts it implies).
  Examples: a `Task` dispatch the harness observed with no matching
  "Subagent invoked" log block (a logging bug in a skill); a `spec.md` that
  appeared with no preceding dispatch (an undesigned path through the
  workflow).
- **Absence finding** — a surfaced expectation that was never met: a phase in
  the workflow's ordered chain that was passed over, a gate that was never
  reached, a configured hook that never fired for a session that should have
  triggered it.
- **Phase resolution** — deriving "which numbered step of which workflow
  chain is executing right now" from the observed event stream plus the
  active-workflow marker set. Inference, never a claim of certainty.
- **Phase map** — `scripts/activity/phases.json`: per workflow, an ordered
  list of `{ id, number, title, match: [...] }` entries. Data, not code.
- **Primary repo** — the main checkout a worktree belongs to, resolved via
  `git -C <path> rev-parse --git-common-dir`. All project state keys off the
  primary repo, never off a worktree path.
- **Registered project** — a primary repo the daemon knows about, added by
  running `/smith-activity` from anywhere inside it (including from one of
  its worktrees).
- **Quota window** — the account-wide 5-hour or 7-day rolling rate-limit
  window reported by Claude Code to the statusline command as
  `rate_limits.five_hour` / `rate_limits.seven_day`.

## Problem & Motivation

Smith is a large, mostly invisible system. Its workflows are prose in
`SKILL.md` files, executed by a model, instrumented by hooks, and recorded in
a vault. When the operator asks "did `/smith-new` actually run its Phase 5
questions gate, or did it skip straight to build?", or "why did this workflow
burn 400k tokens?", or "is that `/tmp` worktree from three days ago still
holding an unmerged bugfix?", there is no way to answer except by reading
files after the fact — and the files are exactly the self-reports whose
accuracy is in question.

1. **There is no live view of anything.** Nothing shows how many Claude Code
   sessions are running, which subagents are dispatched right now, or what
   any of them are doing. The operator's only signal is the terminal they
   happen to be looking at.
2. **Workflow phase is completely opaque.** "A workflow is running" is
   already hard to determine; "which numbered phase of that workflow is
   executing" is currently unknowable without reading the transcript. This is
   the single highest-value missing signal and the reason this feature
   exists.
3. **Self-reports cannot audit themselves.** Every existing observability
   surface in Smith (session logs, `workflow-summary.sh`, the ledger) is
   written by the same skill prose whose correctness is in doubt. A skill
   that forgets to write its "Subagent invoked" block produces a session log
   that looks *clean*, not broken. Today nothing notices.
4. **Absence is invisible.** A skipped phase, an un-hit gate, and a
   never-fired hook all render identically to "nothing happened yet".
5. **Token and quota cost is retrospective at best.** `workflow-summary.sh`
   reports at `Stop`. There is no live number, and the account-wide 5h/7d
   rolling windows — the limits that actually stop work — are visible only in
   the statusline, if the operator has one.
6. **Worktrees drift silently.** `/smith-new` and `/smith-bugfix` create
   `/tmp/smith-<slug>` worktrees. Some are abandoned mid-workflow (a bugfix
   deliberately *preserves* the worktree when a phase fails pre-merge), some
   are deleted out from under their markers, some outlive their merged
   branch waiting on the janitor sweep. There is no inventory.
7. **A newly-discovered correctness gap: concurrent workflows share a
   session log.** Two concurrent `/smith-new` runs in the same repo write to
   the **same** session log file. This was observed live while this very
   feature was being specified — markers `60-activity-dashboard` and
   `67-deterministic-questions` both pointed at the same `session_log:`
   path, with their subagent-invocation blocks interleaved in one file. Any
   consumer that treats a session log as a single undifferentiated stream of
   one workflow's events will attribute phases and tokens to the wrong
   workflow. `workflow-summary.sh`'s existing token attribution has the same
   exposure. This feature must not repeat that mistake.

## Goals

- **G1 — Answer "which numbered phase of which workflow is running right
  now?"** for every active Smith workflow on the machine, as a stepper with
  completed / current / remaining steps, with honest provenance and an
  explicit `phase unknown` state rather than a guess.
- **G2 — Make divergence between the harness spine and Smith's self-reports
  a first-class, surfaced finding**, because that divergence is the audit's
  core product.
- **G3 — Render absence** — skipped phases, un-hit gates, hooks that never
  fired — as explicitly as presence.
- **G4 — Attribute every event, phase, and token to the correct workflow**
  even when multiple workflows share one session log, one repo, and one
  operator.
- **G5 — Show the real execution geography**: which session, in which
  worktree, on which branch, how that branch differs from the primary
  checkout, and which marker owns it — including the degraded states (held,
  missing, orphaned).
- **G6 — Show live cost and remaining headroom**: per-session and
  per-workflow token breakdown with estimated USD, plus the account-wide 5h
  and 7d quota windows with reset times.
- **G7 — Be incapable of harming a session.** No emitter path may ever fail a
  tool call, block a `PreToolUse`, write to stdout, or hang. When the daemon
  is down, every emitter is a silent no-op.
- **G8 — Stay entirely local and private by default.** `127.0.0.1` only, a
  required token, no outbound requests of any kind, and prompt text and tool
  inputs redacted unless explicitly opted in.
- **G9 — Add zero dependencies.** bash, git, jq, Python 3 stdlib (floor
  3.8). No Node, no npm, no pip, no WebSockets.
- **G10 — Keep the phase chain as data, not code**, so adding a phase to a
  workflow means editing `phases.json`, and a forgotten edit fails the test
  suite rather than silently rendering a stale stepper.

## Non-Goals

- Not a status monitor, uptime dashboard, or alerting system. It never pages
  anyone and has no notion of "healthy".
- Not a controller. It is strictly read-only with respect to Smith state: it
  never starts, stops, advances, approves, or cancels a workflow, and it
  never writes into `.smith/vault/`.
- Not a multi-user or remote service. There is no auth model beyond a local
  token, no TLS, no non-loopback bind, and no intent to ever add one.
- Not a historical analytics product. See OOS-3 (ephemeral retention).
- Not a replacement for `workflow-summary.sh`, the ledger, or
  `/smith-vault`. It observes the same material live; it does not supersede
  the after-the-fact artifacts.
- Does not modify any of the four workflow skills — not to stamp their own
  phase (OOS-1), and not for documentation fixes either (OOS-8). This feature
  observes those skills; editing them changes the behavior being measured.

## User Scenarios & Testing

### US-1 — The phase stepper answers "where is this workflow right now?" (Priority: P1)

The operator opens the dashboard mid-workflow and sees, for each active
workflow, the exact numbered step of that workflow's chain that is executing,
rendered as a stepper, with nesting when one workflow has handed off to
another.

**Why P1**: This is the headline capability and the single most valuable
missing signal. Shipped alone, it already delivers the audit's primary
question.

**Independent Test**: Replay a recorded fixture session log plus its hook
event stream for a full `/smith-new` → `/smith-build` run through the
resolver and assert the resolved phase at each checkpoint, with no live
daemon required.

```gherkin
Given an active-workflow marker declares workflow `smith-new`, branch
    `60-activity-dashboard`, worktree `/tmp/smith-activity-dashboard`
And the session log's most recent attributable subagent-invocation block for
    that workflow reads "Subagent invoked: Phase 4 Plan Generation"
When the dashboard renders that workflow's stepper
Then it shows "smith-new · Phase 4 of 6 · Plan Generation"
And Phases 0-3 render as completed, Phase 4 as current, Phases 5-6 as
    remaining
And the provenance badge reads "subagent block"

Given that same workflow has handed off to `/smith-build`
And a second marker or a resolved skill-invocation event places `smith-build`
    at its Testing phase
When the dashboard renders
Then it shows the nested chain "smith-new › 6/6 Update Plan, Then Build or
    Queue → smith-build › 3/11 Testing"
And the parent workflow's stepper remains visible rather than being replaced

Given the resolver's signals are exhausted and no phase can be attributed
When the dashboard renders that workflow
Then it displays "phase unknown", the last known phase, and the timestamp of
    that last known phase
And it NEVER displays a guessed or interpolated phase name
```

### US-2 — Divergence and absence are surfaced as findings (Priority: P1)

The operator sees, alongside the live view, a list of named findings where
the harness's ground truth and Smith's self-reports disagree, and where an
expected thing never happened.

**Why P1**: This is what makes the tool an audit rather than a monitor. It is
the capability that catches the exact class of bug — a skill that silently
fails to log — that the operator built this tool to find.

**Independent Test**: Feed the resolver a fixture pair (hook event stream +
session log) constructed with a deliberate omission and assert that exactly
the expected finding is produced, with the expected severity and text.

```gherkin
Given the hook event stream contains a `PreToolUse` event with
    `tool_name = Task` and `agent_type = general-purpose`
And no "Subagent invoked" block matching that dispatch appears in the
    attributed session log within the reconciliation window
When the dashboard renders findings
Then a divergence finding is shown naming the dispatch, its timestamp, and
    the workflow and phase it was attributed to
And the finding is classified as a skill logging bug, not a daemon error

Given a `spec.md` artifact appears under the feature directory
And no subagent dispatch and no skill-invocation event preceded it in the
    attributed stream
When the dashboard renders findings
Then a divergence finding is shown stating that an artifact appeared without
    its expected events, classified as an undesigned path through the
    workflow

Given a `smith-new` workflow's stream advances from Phase 4 to Phase 6
And the phase map declares Phase 5 (Questions Gate) between them
When the dashboard renders that workflow
Then Phase 5 renders as SKIPPED — visually distinct from both completed and
    remaining — and an absence finding names the skipped phase

Given a session produced tool calls but never produced a `SessionStart`
    ingest event
And the installed `~/.claude/settings.json` wires `SessionStart`
When the dashboard renders that session
Then an absence finding states that the expected hook never fired for that
    session

Given `~/.claude/settings.json` cannot be read or parsed
When the dashboard renders findings
Then absence detection is DISABLED and the UI says so explicitly
And no absence finding is produced from a guessed or shipped default set

Given a hook that Smith ships is absent from the installed
    `~/.claude/settings.json`
When the dashboard renders findings
Then a divergence finding states "Smith ships this, your settings don't wire
    it", distinct from a "wired but never fired" absence finding

Given a divergence finding was raised for a `Task` dispatch with no matching
    log block
And the matching block is appended 40 seconds later, inside the 90-second
    two-sided window
When the dashboard re-renders
Then the finding visibly transitions to a settled, resolved state
And it does NOT silently disappear from the findings panel
```

### US-3 — Two concurrent workflows in one repo are never confused (Priority: P1)

Two `/smith-new` runs proceed concurrently in the same repository, writing
interleaved blocks into the same session log file. The dashboard shows two
independent workflows, each at its own phase, with its own token total.

**Why P1**: Observed live in this repository during this feature's own
exploration. Without this, the headline feature is not merely incomplete —
it is confidently wrong, which is worse than absent for an audit tool.

**Independent Test**: Replay a single fixture session log containing
interleaved blocks from two markers and assert two distinct resolved
workflows with correct, non-crossed phase and token attribution.

```gherkin
Given two active-workflow markers exist: `60-activity-dashboard`
    (workflow `smith-new`, worktree `/tmp/smith-activity-dashboard`) and
    `67-deterministic-questions` (workflow `smith-new`, worktree
    `/tmp/smith-deterministic-questions`)
And both markers name the SAME `session_log:` path
And that session log contains subagent-invocation blocks from both workflows,
    interleaved in time order
When the resolver runs
Then it produces exactly two workflow records, one per marker
And each block is attributed to exactly one workflow via the marker's
    branch / workflow / worktree correspondence
And neither workflow's stepper advances on the other's events
And each workflow's token rollup counts only its own attributed usage
```

### US-4 — A hook can never break a session (Priority: P1)

The operator works normally with the daemon stopped, crashed, or mid-restart.
Nothing in their session changes: no error, no blocked tool call, no delay, no
stray stdout.

**Why P1**: `PreToolUse` is the highest-risk surface in this feature — a
non-zero exit there BLOCKS the tool call. A dashboard that can wedge the
operator's actual work is not shippable at any level of usefulness.

**Independent Test**: Run each emitter path directly with no daemon
listening, and assert exit status, stdout, and wall-clock bound.

```gherkin
Given no daemon is listening on the configured port
When a `PreToolUse` event fires and the emitter runs
Then the emitter exits 0
And writes nothing whatsoever to stdout
And returns within its hard timeout
And the tool call proceeds exactly as if the emitter were not installed

Given the daemon is listening but hangs without responding
When any emitter path runs
Then it is bounded by its own hard timeout, exits 0, and writes nothing to
    stdout

Given the daemon is down and a `PostToolUse` event fires
When the emitter runs
Then it exits 0 silently, matching the unconditional exit-0 convention every
    existing `PostToolUse` hook in this repo already follows
```

### US-5 — One daemon, many projects, fully idempotent (Priority: P2)

The operator runs `/smith-activity` in project A, then later in project B.
Both open tabs against the same daemon; the dashboard shows global totals
with a per-project filter.

**Why P2**: Necessary plumbing for everything above, but the audit value
lives in US-1..US-4.

**Independent Test**: Invoke the command twice from two different repos and
assert one process, two registered projects, two working URLs.

```gherkin
Given no daemon is running
When the operator runs `/smith-activity` from project A
Then a daemon starts bound to 127.0.0.1 only
And project A is registered by its primary repo path
And the browser opens `http://127.0.0.1:<port>/?project=<token>`

Given that daemon is already running
When the operator runs `/smith-activity` from project B
Then NO second daemon starts
And project B is registered
And a new tab opens against the same daemon, filtered to project B

Given a pidfile exists but its pid is gone, or the recorded port is occupied
    by an unrelated process
When the operator runs `/smith-activity`
Then the stale state is cleaned up and a daemon is started
And the command does NOT fail with a "already running" error

Given the operator runs `/smith-activity` from inside `/tmp/smith-<slug>`, a
    worktree of project A living outside project A's tree
Then project A — the primary repo — is the registered project
And NO second project appears for the worktree path
```

### US-6 — Live sessions and subagents (Priority: P2)

The operator sees how many Claude Code sessions are alive, which are working
versus waiting on a permission prompt versus idle, and which Task subagents
are running right now.

**Independent Test**: Assert panel contents against a synthetic event stream
plus a canned `claude agents --json` payload.

```gherkin
Given three Claude Code sessions are alive, one of which is blocked on a
    permission prompt
When the dashboard renders the sessions panel
Then it shows three sessions with model, uptime, cwd, git branch, and
    worktree
And the blocked session is marked "waiting on permission", sourced from the
    `PermissionRequest` hook event, visually distinct from "working"
And the indicator does NOT depend on `claude agents --json`, which exposes no
    `waitingFor` field at all

Given `claude agents --json` returns a record carrying `status` for that
    session
And that `status` disagrees with the event-derived permission state
When the dashboard renders
Then the hook-derived value is the one displayed, the polled value is shown
    beside it, and a divergence finding names both values and their sources

Given `claude agents --json` returns a record with no `status` key — the
    majority case
Then no divergence finding is raised for that session, because absence of
    corroboration is not disagreement

Given a session dies without ever firing a `SessionEnd` event
When the next `claude agents --json` liveness reconciliation poll runs
Then that session is removed from the live list rather than lingering
    forever

Given two Task subagents are dispatched and running
When the dashboard renders the subagents panel
Then each shows its `agent_type`, its dispatch description, and elapsed time
```

### US-7 — Worktree and branch reality, including the degraded states (Priority: P2)

For every active session the operator sees the primary project, the worktree
it is executing in, that worktree's branch, and how it differs from the
primary checkout — plus an inventory of worktrees that are in a degraded
state.

**Independent Test**: Construct each degraded state in a scratch repository
and assert the rendered classification.

```gherkin
Given a session is executing in `/tmp/smith-<slug>` while
    `CLAUDE_PROJECT_DIR` remains pinned to the primary repo
When the dashboard renders that session
Then the primary project, the worktree path, and the worktree's branch are
    all shown
And the worktree does NOT register as a second project

Given a worktree whose marker exists and whose branch is unmerged, from a
    bugfix that failed a phase before merge
When the dashboard renders the worktree inventory
Then it is classified HELD, showing its age and the phase it died in

Given a marker points at a `/tmp` worktree that no longer exists on disk
Then it is classified MISSING, and the UI states that `git worktree prune`
    clears it

Given a worktree whose branch has been merged and deleted but whose marker
    has not yet been swept
Then it is classified ORPHANED and labeled as pending the janitor sweep —
    NOT rendered as a phantom active workflow

Given the primary checkout itself
Then it is marked distinctly from the worktrees and shows its own branch
```

### US-8 — Live tokens, cost, and quota headroom (Priority: P2)

The operator sees live token usage for the current session and workflow, and
the account-wide rolling quota windows.

**Independent Test**: Roll up a known JSONL fixture and assert exact
input/output/cache-write/cache-read/normalized/USD figures; feed a canned
statusline payload and assert the rendered percentages and reset times.

```gherkin
Given a session's transcript JSONL with known per-message usage
When the dashboard renders the tokens panel
Then it shows input, output, cache-write, and cache-read counts, a
    normalized total, and an estimated USD cost
And the figures match the fixture's computed values exactly

Given Claude Code passes the statusline a payload containing `rate_limits`
    with `five_hour` and `seven_day`, each carrying `used_percentage` and
    `resets_at`
When the dashboard renders the quota panel
Then both windows render as percentages with their reset times
And the figures are global (account-wide), not per-project, regardless of
    which project filter is active

Given the statusline payload contains no `rate_limits` key at all
Then the quota panel renders an explicit "quota unavailable" state
And nothing else on the dashboard degrades
```

### US-9 — The vault audit panel (Priority: P3)

The operator reviews recent Smith self-reported state in one place: session
log entries, ledger counts, queue depth, bank items, subagent findings, index
freshness, and the counts that indicate friction — workflow-gate denials,
security-guard blocks, and grade-response retries.

**Independent Test**: Point the daemon at a fixture vault tree and assert the
rendered counts.

```gherkin
Given a project vault with a populated ledger, queue, bank, and agents tree
When the dashboard renders the vault panel for that project
Then it shows recent session-log entries, ledger counts by category, queue
    depth with the last scheduler run, bank items, subagent findings, and
    index freshness
And it shows counts of workflow-gate denials, security-guard blocks, and
    grade-response retries

Given the daemon renders any vault content
Then it performs ONLY reads — the dashboard writes nothing into
    `.smith/vault/` at any time
```

### US-10 — The statusline is wrapped, never clobbered; prompts are redacted (Priority: P3)

Installing the quota feed does not destroy an existing statusline, and no
prompt text or tool input leaves the operator's own process boundary without
an explicit opt-in.

**Independent Test**: Install over a pre-existing statusline command and over
none, and assert delegation in both cases; assert redaction with and without
the opt-in env var.

```gherkin
Given the operator already has a statusline command configured
When `/smith-activity` installs the statusline tee
Then the prior command is stored, and the tee reads stdin once, forwards a
    copy, and delegates to the stored command
And the operator's statusline output is byte-for-byte what it was before

Given the operator had NO statusline configured
When the tee runs
Then it prints a minimal default line rather than nothing or an error

Given `SMITH_ACTIVITY_CAPTURE_PROMPTS` is unset
When a `UserPromptSubmit` or tool-input-bearing event is ingested
Then prompt text and tool inputs are redacted before storage and before any
    SSE frame, and never appear in the UI or the daemon log

Given `SMITH_ACTIVITY_CAPTURE_PROMPTS=1`
Then the content is captured, and the UI indicates that capture is active
```

### Edge Cases

- **Daemon down when a hook fires** — emitter is a silent no-op, exit 0
  (FR-40). No retry queue, no buffering, no error surface.
- **Configured port already taken** — by another daemon instance: reuse it
  after verifying it is a Smith activity daemon. By an unrelated process:
  pick another port, record it, and open the new one (FR-5).
- **Stale pidfile** — pid gone, or pid alive but not our daemon: clean up and
  restart rather than failing (FR-6).
- **No `rate_limits` in the statusline payload** — e.g. before the first API
  response, or non-subscription auth. Quota panel renders "unavailable";
  nothing else degrades (FR-35).
- **Unknown model id in a transcript** — pricing resolves to no match; the
  token counts still render and the USD estimate renders as unavailable for
  that slice rather than as `$0.00` (FR-34).
- **Malformed JSONL line in a transcript** — skipped, consistent with
  `parse_parent_jsonl`'s existing tolerance; the rollup continues (FR-33).
- **Two concurrent workflows in one session log** — attributed via the marker
  set, never merged (FR-14, US-3).
- **Worktree deleted under a live marker** — classified MISSING with the
  `git worktree prune` remedy stated, not an error (FR-29).
- **Session dies without `SessionEnd`** — reaped by the `claude agents
  --json` liveness reconciler within one poll interval (FR-26).
- **`claude agents --json` record carries no `status`** — 17 of 23 observed
  records. The permission indicator is unaffected because it is
  event-derived (FR-18), and no corroboration divergence is raised (FR-57).
- **`~/.claude/settings.json` unreadable or unparseable** — absence detection
  is disabled with a visible UI notice; no guessed expectation set is
  substituted (FR-60).
- **A divergence finding is retracted** — the finding transitions to a
  visible settled state rather than vanishing from the panel (FR-59).
- **Session-log lines whose timestamps run backwards** — expected, not a
  corruption: the log mixes UTC and local clocks. Ordering keys on append
  offset, so nothing in the resolver notices (FR-58).
- **Marker exists for a workflow the phase map does not know** — the workflow
  renders with `phase unknown` and an explicit "no phase map entry" note;
  the resolver never invents a chain.
- **A skill-invocation event fires for a skill that is only being *read* as a
  rubric** — e.g. `smith-build` Phase 3.5 reads `skills/smith-clean-code/
  SKILL.md` as a file. A file read produces no skill-invocation event, so no
  phase advance may be inferred from it (FR-12).
- **`PostToolUse *` event storm** — coalesced, never one SSE frame per tool
  call (FR-41).
- **Browser tab open while the daemon restarts** — the SSE stream reconnects
  and the page re-renders from the daemon's current state; because retention
  is ephemeral (OOS-3), the pre-restart history is gone and the UI says so
  rather than showing a silently truncated timeline.

## Functional Requirements

### Command surface and daemon lifecycle

- **FR-1**: A new skill `/smith-activity` MUST accept
  `[start|stop|restart|status|open]` with `--port N`, `--no-open`, and
  `--foreground`. With no subcommand it MUST behave as: ensure the daemon is
  running, register the invoking project, and open the dashboard.
- **FR-2**: Invocation MUST be fully idempotent. A second invocation from any
  project MUST NOT start a second daemon; it registers that project (if new)
  and opens a tab against the existing daemon.
- **FR-3**: Exactly ONE daemon MUST serve ALL registered projects. Because the
  5h and 7d quota windows are account-wide, the dashboard MUST present global
  totals with a per-project filter, never a per-project silo that would
  misrepresent shared quota as project-local.
- **FR-4**: The daemon MUST bind `127.0.0.1` only. It MUST NOT bind `0.0.0.0`,
  any LAN address, or any IPv6 non-loopback address under any flag or
  configuration.
- **FR-5**: When the requested or recorded port is occupied, the command MUST
  distinguish "occupied by an existing Smith activity daemon" (reuse it) from
  "occupied by an unrelated process" (select another port, record it, and open
  that one). Neither case may abort the command.
- **FR-6**: A stale pidfile — the recorded pid no longer exists, or exists but
  is not this daemon — MUST be cleaned up and the daemon restarted. A stale
  pidfile MUST NEVER cause the command to fail.
- **FR-7**: All runtime state MUST live under `"${SMITH_HOME:-$HOME/.smith}"/
  activity/` (`activity.pid`, `activity.port`, `activity.token`,
  `activity.log`, `wrapped-statusline`), honoring `SMITH_HOME` via that exact
  canonical expansion. No runtime state may be written inside any project's
  `.smith/vault/`.
- **FR-8**: Because `/smith-activity` installs files, it MUST register its own
  active-workflow marker via `create-active-workflow.sh --workflow
  maintenance` before writing anything, and clear it via
  `clear-active-workflow.sh` when finished — the same discipline every other
  file-writing Smith surface follows.

### Phase resolution (the headline)

- **FR-9**: For each active workflow the dashboard MUST resolve and display
  the specific numbered step of that workflow's ordered chain that is
  executing — e.g. "smith-new · Phase 4 of 6 · Plan Generation" — rendered as
  a stepper with completed, current, and remaining steps distinguished. "A
  workflow is running" is not an acceptable resolution when a phase is
  derivable.
- **FR-10**: Phase resolution MUST be implemented as a state machine over an
  ordered event stream, keyed by workflow type taken from the active-workflow
  marker. It MUST NOT assume that phases correspond to skill invocations,
  because for the four workflow skills they overwhelmingly do not:
  `/smith-new` produces a visible skill invocation at only 2 of its 7 phases
  (Phase 0 `/smith-explore`, which is itself conditional, and Phase 6
  `/smith-build`); `/smith-bugfix` produces one at ZERO of nine phases;
  `/smith-debug` at ZERO of eight.
- **FR-11**: The resolver MUST consume these signals, in this priority order:
  1. **Subagent invocation blocks** in the session log — `### [HH:MM:SS]
     Subagent invoked: <description>` with `**Type:**` and `**Model:**` —
     appended immediately before every Agent call; the description carries the
     phase name. Strongest live signal. Ordered by **append offset in the
     session log**, never by the parsed `[HH:MM:SS]` stamp (FR-58).
  2. **Live `PreToolUse` `Task` hook events**, which carry the same
     information. **Their order relative to the log block is NOT
     guaranteed**: all four workflow SKILLs instruct the `Subagent invoked:`
     block to be written *before* the Agent call, so the block may precede
     the event as easily as follow it. The resolver MUST advance
     optimistically on the event and reconcile against the block using the
     **two-sided** window defined in FR-22, and MUST NOT assume either side
     arrives first.
  3. **Skill event entries** — `### [HH:MM:SS] /smith-<skill> <event>` with
     `**Outcome:**` / `**Artifacts:**`.
  4. **The `workflow-start` stamp** written by `create-active-workflow.sh`.
  5. **Subagent completion blocks** written by
     `subagent-vault-writeback.sh` — a phase whose subagent has returned is
     DONE, not running.
  6. **Artifact presence**, as corroboration and as the cold-start fallback
     when a dashboard is opened mid-workflow with no prior event stream.
- **FR-12**: Artifact-presence corroboration MUST cover BOTH layouts —
  `specs/<n>-<slug>/` and `.specify/systems/<system>/features/<n>-<slug>/` —
  with these mappings: `spec.md` present → Phase 3 complete; `questions.md`
  present → Phase 4 complete; `questions.md` with unanswered items → sitting
  at the Phase 5 gate; `tasks.md` with n of N boxes checked →
  mid-implementation at n/N. A file READ (as opposed to an invocation) MUST
  NEVER advance a phase — notably `smith-build` Phase 3.5, whose subagent
  reads `skills/smith-clean-code/SKILL.md` as a rubric file and produces no
  invocation event.
- **FR-13**: The resolver MUST prefer a `phase:` field in the active-workflow
  marker over every inferred signal if such a field is ever present, even
  though nothing writes one today. This makes authoritative phase stamping a
  purely additive later change with zero resolver rework (OOS-1).
- **FR-14**: **Concurrent-workflow attribution.** The resolver MUST NOT assume
  one workflow per session log. Two concurrent workflows in the same
  repository write to the SAME session log file, interleaving their
  subagent-invocation blocks. Every event MUST be attributed to a specific
  workflow via the active-workflow **marker set** — the (branch, workflow,
  worktree) correspondence — rather than by consuming a single
  undifferentiated stream. Acceptance: given one session log containing
  interleaved blocks from two markers, the resolver produces exactly two
  workflow records; no block is attributed to more than one; neither
  workflow's stepper advances on the other's events; and each workflow's
  token rollup counts only its own attributed usage.
- **FR-15**: The ordered phase chain per workflow MUST be supplied as data in
  `scripts/activity/phases.json` — per workflow, an ordered list of
  `{ id, number, title, match: [...] }`. Phase lists MUST NOT be hardcoded in
  Python. The seeded chains are exactly the real headings:
  - `smith-new` (7): 0 Pre-Change Exploration · 1 Worktree Creation & Setup ·
    2 Requirements Conversation · 3 Spec Generation · 4 Plan Generation ·
    5 Questions Gate · 6 Update Plan, Then Build or Queue
  - `smith-bugfix` (9): 1 Worktree Setup · 2 Spec Cross-Reference ·
    3 Implement the Fix · 3.5 Update .meta Descriptions · 4 Docker Rebuild ·
    5 Run Tests · 6 Update Specs & Changelog · 7 Commit, Push & Merge ·
    8 Post-Merge Rebuild & Summary
  - `smith-debug` (8): 0 Activate Workflow Tracking · 1 Symptom Capture ·
    2 System Detection · 3 Automated Triage · 4 Diagnosis Synthesis · 5 Write
    Debug Report · 5.5 Update .meta Descriptions · 6 Decision Gate
  - `smith-build` (11): 0 Context Discovery · 1 Task Generation ·
    2 Implementation · 3 Testing · 3.5 Clean Code Review · 3.6 Security
    Review · 3.7 Supply-Chain Review · 4 Spec Updates · 5 Commit, Push &
    Merge · 6 Service Rebuild · 7 Release Notes & Summary
  - `smith-finish` (9): 1 Inventory · 1.5 Activate Workflow Tracking ·
    2 Commit · 3 Push · 4 Spec Updates · 5 PR & Merge · 6 Verify Clean State ·
    6.5 Clear Workflow Tracking · 7 Final Report

  `smith-finish` is mapped even though it is NOT an accepted `--workflow`
  value for `create-active-workflow.sh` (the accepted set is `smith-new`,
  `smith-bugfix`, `smith-debug`, `smith-build`, `smith-index`,
  `smith-update`, `smith-queue`, `maintenance`). It is therefore the one
  mapped chain that cannot be keyed off a marker's workflow type; it is
  resolved from its own skill-invocation event (FR-11 signal 3) instead,
  and it is included in the map so FR-16's sync test covers it.
- **FR-16**: A test MUST parse `## Phase N:` / `### Step N:` headings out of
  each workflow `SKILL.md` and assert they match `phases.json` exactly — same
  set, same order, same numbers. Adding or renaming a phase without updating
  the map MUST fail the suite rather than silently rendering a stale stepper.
- **FR-17**: When one workflow hands off to another, the dashboard MUST show
  the NESTED chain rather than replacing the parent — e.g. "smith-new › 6/6
  Update Plan, Then Build or Queue → smith-build › 3/11 Testing".

  **Derivation — corrected 2026-09-22 against measured behavior, superseding
  `research.md` §Q6.** Nesting MUST be derived FIRST from the real marker
  set, because two concurrent markers DO exist. `scripts/create-active-
  workflow.sh:139` resolves the project root with `git rev-parse
  --show-toplevel` — the **worktree** — while `hooks/workflow-gate.sh:60`
  uses `${CLAUDE_PROJECT_DIR:-$(pwd)}` — the **primary repo**. A
  `/smith-build` launched by `/smith-new` on the same branch therefore does
  NOT collide: it exits **0** and writes a second marker into the worktree's
  own vault. Verified live on this branch: the primary vault holds
  `workflow: smith-new` and `<worktree>/.smith/vault/active-workflows/
  60-activity-dashboard.yaml` holds `workflow: smith-build`. The resolver
  MUST therefore enumerate active-workflow markers across BOTH the primary
  repo vault AND every linked worktree's vault, and correlate them by
  `branch:` to open the parent/child pair. Cross-chain phase-title matching
  (the derivation `research.md` §Q6 proposed) is RETAINED only as the
  fallback for when a child marker is absent. Two consequences bind the
  implementation: a worktree marker's `session_log:` field is EMPTY, because
  `.smith/vault/.current-session` does not exist in a worktree, so any reader
  MUST tolerate an empty value and fall back to the primary vault's
  `.current-session`; and the normal two-marker handoff MUST NOT raise
  FR-22(c) `marker_contradiction`, which is reserved for a cross-chain signal
  at a phase with no declared `handoff`.
- **FR-18**: Phases that are MANDATORY STOP gates — `smith-new` Phase 5
  (Questions Gate) and `smith-debug` Phase 6 (Decision Gate) — MUST render
  distinctly from working phases. "Waiting on you" MUST NOT be rendered as
  "working". The "waiting on a permission prompt" state MUST be derived
  **primarily from the `PermissionRequest` / `PermissionDenied` hook
  events** — a `PermissionRequest` with no `PermissionDenied` and no
  `PostToolUse` for the same `prompt_id` means waiting. Hook events are the
  primary source because they are hook-sourced and therefore win under
  FR-21's trust hierarchy, and because they arrive on the event stream
  rather than on a 5-10 s poll. `claude agents --json`'s `status` field MUST
  be used only as **corroboration where present** (FR-26); it MUST NOT be
  the primary source, and its absence — it is absent on most records — MUST
  NOT blank the indicator. Disagreement between the two sources is itself a
  finding (FR-57). The `waitingFor` field named in earlier drafts of this
  requirement does not exist and MUST NOT be read (FR-26).
- **FR-19**: Every resolved phase MUST carry a visible provenance label
  naming the signal that produced it (e.g. "subagent block", "live Task
  event", "inferred from artifacts").
- **FR-20**: When no signal resolves a phase, the dashboard MUST display
  `phase unknown` together with the last known phase and its timestamp. It
  MUST NEVER display a guessed, interpolated, or nearest-match phase name.
- **FR-58**: **Parsed session-log timestamps MUST NOT be used for ordering
  anywhere in the resolver, the reconciler, or the findings derivation.**
  The session log mixes two clocks: hooks write UTC (`date -u`) while
  model-authored `Subagent invoked:` blocks write local wall time. A 4-hour
  skew was observed between adjacent lines in this repository's own session
  log. All ordering MUST therefore key on **append offset within the session
  log** (and on daemon-side ingest sequence for hook events). Parsed
  timestamps MAY still be DISPLAYED as received, labeled with their source,
  but MUST NOT participate in any comparison that decides sequence,
  window membership, or phase advance.

### Divergence and absence (the audit product)

- **FR-21**: The daemon MUST treat hook events as the ground-truth spine and
  vault/session-log content as annotation. Where a conflict exists, the
  hook-derived value MUST be the one displayed, with the self-reported value
  shown beside it as the divergence.
- **FR-22**: The dashboard MUST surface a **divergence finding** for at least:
  (a) a `Task` dispatch the harness observed with no matching "Subagent
  invoked" log block within the reconciliation window — classified as a skill
  logging bug; (b) an artifact that appeared with no preceding expected
  events — classified as an undesigned path through the workflow; (c) a
  marker whose declared workflow contradicts the observed event sequence.
  Each finding names the workflow, the phase it was attributed to, and the
  timestamp.

  **The reconciliation window is 90 seconds, TWO-SIDED, and ordered on
  session-log append offset — never on parsed timestamps (FR-58).** It is
  two-sided because FR-11 signal 2's ordering is not guaranteed in either
  direction: the block may land before or after the `PreToolUse` `Task`
  event. Findings raised inside the window MUST be **retractable** when the
  matching block or event arrives late, and a retracted finding MUST resolve
  visibly rather than silently disappearing (FR-59).
- **FR-23**: The dashboard MUST surface an **absence finding** for at least:
  (a) a phase in the workflow's ordered chain that was passed over — rendered
  as SKIPPED, visually distinct from both completed and remaining; (b) a
  MANDATORY STOP gate that was never reached; (c) a configured hook that
  never fired for a session where it was expected. Absence MUST be rendered
  explicitly, not merely as the absence of a presence indicator.
- **FR-24**: Findings MUST be non-blocking and advisory in every case. The
  dashboard never modifies, pauses, or interferes with the workflow it is
  auditing.
- **FR-57**: **Permission-state disagreement is a third divergence class.**
  When `claude agents --json` reports a `status` for a session AND the
  event-derived permission state (FR-18) disagrees with it — the events say
  waiting while `status` reads `idle`/`busy`, or `status` implies activity
  while a `PermissionRequest` is outstanding — the dashboard MUST surface a
  divergence finding naming both values, their sources, and the session. The
  hook-derived value remains the one displayed (FR-21); the polled value is
  shown beside it as the divergence. A session for which `status` is absent
  (17 of 23 observed records) MUST NOT produce this finding — absence of
  corroboration is not disagreement.
- **FR-59**: **A retracted finding MUST visibly resolve.** When a finding
  raised inside the FR-22 window is retracted because the matching block or
  event arrived late, the UI MUST transition it to an explicit settled state
  that the operator can see. It MUST NOT be removed from the panel with no
  trace. A finding that appears and then silently vanishes reads as a
  rendering glitch and destroys trust in the divergence panel, which is the
  feature's primary product.
- **FR-60**: **The expected-hook set for absence detection MUST be derived
  from the INSTALLED `~/.claude/settings.json`**, parsed at daemon start and
  refreshed on `ConfigChange`, then intersected with a small shipped
  applicability table (e.g. `lint-on-save` is only expected after a
  `Write`/`Edit`; `security-guard-bash` only on `Bash`). It MUST NOT be
  derived from a static shipped list, and it MUST NOT be derived from the
  repo's `settings/smith-settings-fragment.json` — `docs/hooks.md:5` tells
  operators to disable a hook by removing its settings entry, so either
  source would fire "this hook never fired" at a hook the operator
  deliberately removed, and a repo-derived source would compare Smith against
  its own intentions rather than against reality. **When
  `~/.claude/settings.json` is unreadable or unparseable, absence detection
  MUST be DISABLED with a visible notice in the UI** — never silently
  degraded, never guessed.
- **FR-61**: **"Smith ships this hook, your settings don't wire it" is a
  fourth divergence class**, distinct from FR-23(c)'s "wired but never
  fired". The dashboard MUST surface a divergence finding for each hook
  Smith ships that the installed `~/.claude/settings.json` does not wire.
  Because FR-60 forbids the daemon from treating the repo fragment as the
  expectation — and because the daemon has no reason to know where a repo
  checkout lives — the "what Smith ships" side MUST be supplied as a
  manifest staged by `scripts/install.sh` under
  `"${SMITH_HOME:-$HOME/.smith}"/activity/`, not read from the repo at
  runtime. This class exists because this feature's own planning produced a
  live instance of it: `hooks/pricing.json` is present in the repo and has
  never been installed (FR-62), and a repo-derived expectation would have
  reported everything healthy.

### Sessions and subagents

- **FR-25**: The dashboard MUST show every live Claude Code session, per
  project and globally, each classified as working, waiting on a permission
  prompt, or idle, with model, uptime, cwd, git branch, and worktree.
- **FR-26**: The daemon MUST poll `claude agents --json` every 5-10 seconds
  as a **liveness reconciler**. It MUST code against the record shape
  verified against the installed Claude Code across 23 live records —
  `{pid, cwd, kind, name, sessionId, startedAt}` always present, `status`
  (values `idle` / `busy`) present in only 6 of 23. **`waitingFor`, `state`
  and `id` are present in ZERO records** and MUST NOT be read, defaulted to,
  or depended on anywhere in the implementation. The poll's purpose is
  liveness reconciliation: self-healing the live-session list when a session
  dies without ever firing `SessionEnd`. It MUST NOT be the primary source
  of the "waiting on permission" indicator (FR-18). Where `status` IS
  present it MAY be used as corroboration, and its disagreement with the
  event-derived permission state MUST be surfaced as a divergence finding
  (FR-57).
- **FR-27**: The dashboard MUST show every Task subagent currently running,
  with its `agent_type`, its dispatch description, and elapsed time. These
  MUST be populated from the `~/.claude/projects/<slug>/<session-id>/
  subagents/agent-<id>.meta.json` sidecar — which carries `agentType`,
  `description`, `parentAgentId`, `spawnDepth` and `toolUseId` — with the
  `PreToolUse` `Task` event as the corroborating spine record. `toolUseId`
  is what ties a sidecar to the dispatch that created it.

### Project identity, worktrees, and branches

- **FR-28**: Any path MUST be resolved to its **primary repo** via
  `git -C <path> rev-parse --git-common-dir`, and ALL project state MUST be
  keyed off that primary repo. This is required because `CLAUDE_PROJECT_DIR`
  stays pinned to the primary repo (which is why hooks keep writing to the
  primary vault while later phases execute elsewhere) while hook-payload
  `cwd` and `claude agents --json` `cwd` are the WORKTREE. A worktree MUST
  NEVER register as a second project. This MUST hold for `/tmp/smith-<slug>`
  worktrees living entirely outside the primary tree.
- **FR-29**: The daemon MUST enumerate worktrees via `git worktree list
  --porcelain` and cross-reference the `branch:` and `worktree:` fields of
  each active-workflow marker. Per worktree it MUST show: short path, branch,
  base branch, ahead/behind counts versus `origin/<base>`, dirty-file count,
  which session is working in it, and which marker owns it. The primary
  checkout MUST be marked distinctly and show its own branch.
- **FR-30**: The three degraded worktree states MUST be first-class,
  separately classified, and separately rendered:
  - **HELD** — a bugfix preserved the worktree when a phase failed pre-merge.
    Show its age and the phase it died in.
  - **MISSING** — a marker points at a worktree that no longer exists on
    disk. Surface that `git worktree prune` clears it.
  - **ORPHANED** — the branch is merged or gone and the marker is pending an
    `active-workflow-janitor.sh` sweep. Render as pending sweep, NOT as a
    phantom active workflow.
- **FR-31**: Git results MUST be cached per worktree and refreshed on a
  debounce of approximately 3 seconds. Git MUST NEVER be invoked per SSE
  frame.

### Tokens, cost, and quota

- **FR-32**: The dashboard MUST show live token usage for the current session
  and the current workflow, broken out as input, output, cache-write, and
  cache-read, plus a normalized total and an estimated USD cost.
- **FR-33**: Token and cost computation MUST REUSE `hooks/
  workflow_summary_lib.py` rather than reimplementing it. **Contract trap
  that MUST be honored:** `match_family()` reads a `_compiled_patterns` key
  that ONLY `load_pricing()` injects — re-parsing `pricing.json`
  independently makes pricing resolve silently to `None`. Any reuse path MUST
  go through `load_pricing()`.
- **FR-34**: When a model id matches no pricing family, token counts MUST
  still render and the USD estimate for that slice MUST render as
  unavailable — never as `$0.00`, which would understate cost silently.
- **FR-35**: Quota MUST be sourced from the statusline payload, which is the
  ONLY authoritative source for the 5-hour and 7-day rolling windows. When
  `rate_limits` is present, both windows MUST render as `used_percentage`
  with `resets_at`. When it is absent, the quota panel MUST render an explicit
  "unavailable" state and nothing else on the dashboard may degrade.
- **FR-36**: **Live subagent token usage ships in v1.** It requires reading
  `~/.claude/projects/<slug>/<session-id>/subagents/agent-<id>.jsonl` for
  sidechain `message.usage`, which `parse_parent_jsonl` does NOT parse today
  (it deliberately skips `isSidechain` entries). This is NEW code and MUST
  ship with its own tests. It MUST be implemented in
  `scripts/activity/usage.py` — the accumulation loop of `parse_parent_jsonl`
  with the `isSidechain` guard inverted — and **MUST NOT modify
  `hooks/workflow_summary_lib.py`**, which stays imported and called, never
  edited. Deferral is explicitly rejected: the parent transcript contains
  ZERO `isSidechain` rows, so a deferred FR-36 would render `0` tokens for
  every running subagent until `SubagentStop` — failing at exactly the
  moment the live-subagent panel is being watched. Malformed JSONL lines
  MUST be skipped, matching the existing tolerance, and MUST NOT abort a
  rollup.

### Vault state panel

- **FR-37**: The dashboard MUST show, per project: recent session-log
  entries, ledger counts by category, queue depth with the last scheduler
  run, bank items, subagent findings, and index freshness — plus counts of
  workflow-gate denials, security-guard blocks, and grade-response retries.
- **FR-38**: Vault sources MUST be polled by `stat`-based change detection at
  approximately 1-second granularity (Python stdlib has no inotify). Sources:
  `active-workflows/*.yaml`, `.current-session*`, `sessions/*.md` (the
  `## Metrics` block from `metrics-tracker.sh` and the `- [HH:MM:SS]
  **Tool** path` lines from `file-change-logger.sh`), `ledger/*.md` +
  `meta.yaml`, `queue/` + `queue/history/`, `bank/`, `agents/<type>/*.md`,
  `.smith/index/`, `~/.smith/projects.json`, and
  `~/.smith/scheduler/scheduler.log`.

### Hook ingest and emitter safety

- **FR-39**: The daemon MUST accept hook events at a local ingest endpoint.
  The envelope carries `session_id`, `prompt_id`, `transcript_path`, `cwd`,
  `permission_mode`, `hook_event_name`, and — inside a subagent — `agent_id`
  and `agent_type`. Every hook event name and payload field MUST be verified
  against the installed Claude Code's `/hooks` output before the
  implementation relies on it.
- **FR-40**: **Every emitter path MUST exit 0 unconditionally, write nothing
  to stdout, and be bounded by a hard timeout.** When the daemon is down,
  unreachable, or hanging, the emitter MUST be a silent no-op. This is
  absolute: on `PreToolUse` a non-zero exit BLOCKS the tool call, making this
  the highest-risk surface in the feature. Acceptance: with no daemon
  listening, the emitter exits 0, produces zero bytes on stdout, returns
  within its timeout, and the tool call proceeds unchanged — asserted
  explicitly for `PreToolUse` as well as `PostToolUse`.
- **FR-41**: Transport MUST be Server-Sent Events (`text/event-stream`), not
  WebSockets. Because `PostToolUse *` is high-volume, broadcasts MUST be
  coalesced on a debounce of roughly 150-250 ms. One SSE frame per tool call
  is explicitly forbidden.
- **FR-42**: The installer MUST prefer native `"type": "http"` hook entries
  pointing at the daemon's ingest endpoint (zero process spawn per tool call),
  detecting support at install time, and MUST fall back to
  `hooks/activity-emitter.sh` backgrounding a short, timeout-bounded local
  POST otherwise. The emitter is the first hook in this repo to make a network
  call of any kind and the first to declare a timeout field in
  `settings/smith-settings-fragment.json`.
- **FR-43**: The desired event set is `SessionStart`, `SessionEnd`,
  `UserPromptSubmit`, `PreToolUse *`, `PostToolUse *`, `SubagentStart`,
  `SubagentStop`, `TaskCreated`, `TaskCompleted`, `Stop`, `PreCompact`,
  `PostCompact`, `Notification`, `PermissionRequest`, `PermissionDenied`.
  `settings/smith-settings-fragment.json` today wires only `SessionStart`,
  `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `SubagentStop`, and
  `Stop`. For any event whose availability is not confirmed against `/hooks`,
  the implementation MUST degrade rather than assume. Specifically:
  `SubagentStart` is load-bearing for the live-subagent panel, and if it does
  not exist the panel MUST fall back to `PreToolUse` on `Task` plus sidechain
  detection.

### Marker integrity

- **FR-44**: **Nothing in this feature — no hook, no emitter, and not the
  daemon — may write to `.smith/vault/active-workflows/` under any
  circumstance.** `hooks/workflow-gate.sh` deliberately omits
  `active-workflows` from `SAFE_VAULT_DIRS` (`sessions bank ledger queue
  agents todo reports index audits`) precisely so that a write cannot forge
  its own marker. The daemon is a detached process outside the hook system
  entirely, so the gate would not stop it — the prohibition is therefore a
  design requirement, not something enforcement can be relied upon to
  provide. Markers are READ-ONLY inputs to this feature. The sole exception
  is `/smith-activity`'s own marker, created and cleared exclusively through
  `create-active-workflow.sh` / `clear-active-workflow.sh` (FR-8).

### Statusline

- **FR-45**: **The statusline tee MUST NEVER clobber an existing statusline.**
  At install time the previously configured command MUST be stored at
  `"${SMITH_HOME:-$HOME/.smith}"/activity/wrapped-statusline`. At runtime the
  tee MUST read stdin exactly once, forward a copy to the daemon in the
  background, and then delegate to the stored command, passing the payload
  through unchanged. When no prior command existed, it MUST print a minimal
  default line. Smith owns no statusline today, so the risk this requirement
  addresses is entirely the operator's own pre-existing configuration.
- **FR-46**: Uninstall MUST restore the wrapped statusline through an explicit
  code path. `scripts/uninstall.sh` today restores `settings.json` WHOLESALE
  from the newest `.bak-` file and performs no surgical entry removal, so
  statusline restoration cannot be assumed to fall out of the existing
  behavior.

### Security and privacy

- **FR-47**: A random token MUST be generated at first daemon start, stored
  under `"${SMITH_HOME:-$HOME/.smith}"/activity/activity.token`, REQUIRED as a
  query parameter on `/events` and every `/api/*` route, and included in the
  URL the skill opens.
- **FR-48**: **User prompt text and tool inputs MUST be redacted by default**,
  behind an explicit `SMITH_ACTIVITY_CAPTURE_PROMPTS=1` opt-in, because
  prompts and diffs contain source code. Redaction MUST occur before storage,
  before any SSE frame, and before anything is written to `activity.log`. When
  capture is enabled, the UI MUST indicate that it is active.
- **FR-49**: The daemon MUST make NO outbound network requests of any kind —
  no telemetry, no analytics, no update check, no font or script CDN fetch
  from the served page. The dashboard's assets MUST be served entirely from
  `scripts/activity/static/`.
- **FR-50**: `docs/security-model.md` MUST be extended with this feature's
  threat-model addition: a loopback-bound local HTTP surface, a token-gated
  SSE stream, a hook-originated local POST (a new pattern for this repo), and
  the redaction default.

### Install, uninstall, and documentation

- **FR-51**: `scripts/install.sh` MUST install the skill, the emitter, the
  daemon and its static assets, `phases.json`, and the statusline tee, and
  MUST merge the new hook entries idempotently at the (matcher, command)
  level via the existing `scripts/lib/dedupehooks.jq` mechanism, preserving
  hook chain order within an entry — including the documented
  `file-change-logger` → `lint-on-save` → `manifest-updater` ordering.
- **FR-52**: `scripts/uninstall.sh` MUST stop the daemon, remove the installed
  files, and restore the wrapped statusline (FR-46).
- **FR-53**: `docs/hooks.md`, `docs/architecture.md`, `docs/security-model.md`,
  the README skill table, and `CHANGELOG.md` MUST all be updated. The README
  skill-count badge MUST be corrected to 35 — it currently reads 33 against 34
  actual skill directories, so this feature both adds one and fixes the
  pre-existing drift.
- **FR-62**: **`scripts/install.sh` MUST copy `hooks/*.json` into
  `$CLAUDE_HOOKS_DIR`, and `hooks/pricing.json` MUST gain the current model
  families including `claude-opus-5*`.** The installer globs only `hooks/*.sh`
  (`:195`) and `hooks/*.py` (`:203`) today, so `pricing.json` has never been
  installed by it; combined with the newest shipped family being
  `claude-opus-4-6*`, `match_family()` returns `None` and `cost_usd()` returns
  `None` for the running model. FR-34's "unavailable, never `$0.00`" is
  therefore the PRIMARY path today rather than an edge case, and the same
  defect silently omits USD from the existing `Stop`-hook workflow summary.
  Three constraints bind the fix:
  1. **Rates MUST NOT be invented.** The build MUST consult the
     authoritative Claude pricing reference — the `claude-api` skill is the
     designated source and explicitly forbids answering from memory — and set
     `last_verified` to the date checked.
  2. **If authoritative rates cannot be obtained**, the family entry MUST
     still be added with the correct match pattern, with its rates surfaced
     as unavailable rather than guessed. FR-34's prohibition applies to
     fabricated rates exactly as it applies to missing ones.
  3. **Entry ORDER in `pricing.json` is load-bearing.** `match_family()`
     returns the first array-order regex match, so a more specific family
     MUST precede any wildcard that would also match it.
- **FR-63**: **`scripts/uninstall.sh`'s `SMITH_HOOKS` array MUST list every
  hook the repo ships**, not the 11 of 20 it lists today, which orphans nine
  hooks on uninstall. The list MUST be derived from the actual contents of
  `hooks/` at implementation time rather than transcribed from any count
  stated in this spec or in `questions.md`. A flat `tests/*.test.sh`
  assertion MUST verify that every `hooks/*.sh` the repo ships appears in
  `SMITH_HOOKS`, so the drift cannot silently return the next time a hook is
  added. `scripts/install.sh:138`'s hardcoded `"Copy 9 hooks"` preview string
  MUST be corrected in the same change — it is a third stale count in the
  same pair of files.

### Testing

- **FR-54**: New tests MUST be flat, top-level `tests/*.test.sh` files,
  because `.github/workflows/test-install.yml` runs ONLY `tests/*.test.sh`
  and no Python test or subdirectory shell test executes in CI today. A test
  that does not run in CI gates nothing.
- **FR-55**: The suite MUST cover, at minimum: phase resolution replayed
  against fixture session logs for a full `smith-new` → `smith-build` run and
  for a `smith-bugfix` run, including nested-handoff and questions-gate
  states; **phase resolution with TWO interleaved concurrent workflows in one
  session log**; the `phases.json` ↔ `SKILL.md` heading sync check (FR-16);
  primary-repo resolution from inside a `/tmp` worktree; the HELD, MISSING,
  and ORPHANED worktree classifications; emitter no-op and exit-0 behavior
  when the daemon is down, asserted for `PreToolUse` as well as
  `PostToolUse`; the statusline wrapper delegating correctly both to a
  pre-existing command and to none; token rollup math against a known JSONL
  fixture; and stale-pidfile recovery.
- **FR-56**: Any extraction from or reuse of `hooks/workflow_summary_lib.py`
  MUST ADD tests, not merely preserve behavior. The specific functions this
  feature depends on — `parse_parent_jsonl`, `resolve_parent_jsonl`,
  `resolve_workflow_window`, `git_files_changed`, and the renderers — have
  ZERO test coverage today, so "preserve existing behavior" has nothing to
  verify against.

## Key Entities

- **Project** — a primary repo, identified by its `git-common-dir`-resolved
  path. Owns a vault, an index, zero or more worktrees, and zero or more
  markers. Never identified by a worktree path.
- **Session** — one live Claude Code session: `session_id`, model, start time,
  cwd, resolved worktree and branch, state (working / waiting on permission /
  idle), and pid. Reconciled against `claude agents --json`.
- **Subagent** — one dispatched Task: `agent_id`, `agent_type`, dispatch
  description, parent session, start time, and completion state. May have its
  own `subagents/agent-<id>.jsonl` token stream.
- **Workflow** — one active-workflow marker: workflow type, slug, branch,
  worktree, session log path, start time, and (if ever present) `phase`. The
  unit of attribution — NOT the session log, which may carry several.
- **Phase** — one entry in a workflow's ordered chain from `phases.json`:
  `id`, `number`, `title`, `match` patterns, plus derived state (completed /
  current / remaining / skipped), provenance, and mandatory-stop flag.
- **Worktree** — a git worktree: path, branch, base branch, ahead/behind,
  dirty count, owning marker, occupying session, and classification
  (primary / active / held / missing / orphaned).
- **Quota window** — an account-wide rolling window: kind (`five_hour` /
  `seven_day` / `spend_limit`), `used_percentage`, `resets_at`. Global; never
  scoped to a project.
- **Token rollup** — input, output, cache-write, cache-read, normalized total,
  and estimated USD, scoped to a session, a workflow, or a subagent.
- **Divergence finding** — a named disagreement between the spine and a
  self-report: kind, workflow, attributed phase, timestamp, the observed
  value, the self-reported value, a retraction state, and a classification
  (skill logging bug / undesigned path / marker contradiction /
  permission-state disagreement (FR-57) / shipped-but-not-wired (FR-61)).
- **Absence finding** — a named unmet expectation: kind (skipped phase /
  un-hit gate / hook never fired), the workflow and phase it concerns, and
  the evidence that establishes the absence.

## Success Criteria

- **SC-1**: For a recorded full `smith-new` → `smith-build` fixture run, the
  resolver returns the correct numbered phase at every checkpoint, including
  the nested handoff and the questions-gate stop (FR-9/FR-11/FR-17/FR-18).
- **SC-2**: For a fixture session log containing two interleaved concurrent
  workflows, the resolver produces exactly two workflow records with zero
  cross-attributed events and zero cross-attributed tokens (FR-14).
- **SC-3**: The `phases.json` ↔ `SKILL.md` sync test fails when a phase
  heading is added, renamed, renumbered, or removed in any of the five mapped
  workflow skills without a corresponding map edit (FR-16).
- **SC-4**: With no daemon listening, every emitter path exits 0, emits zero
  bytes on stdout, and returns within its declared timeout — verified for
  `PreToolUse` and `PostToolUse` explicitly (FR-40).
- **SC-5**: A fixture pair with a `Task` dispatch and no matching "Subagent
  invoked" block produces exactly one divergence finding, classified as a
  skill logging bug and naming the workflow, phase, and timestamp (FR-22).
- **SC-6**: A fixture run that advances past a mapped phase without any
  signal for it renders that phase as SKIPPED and produces exactly one
  absence finding (FR-23).
- **SC-7**: Running `/smith-activity` from inside a `/tmp/smith-<slug>`
  worktree registers the primary repo and exactly one project — never two
  (FR-28).
- **SC-8**: Each of the HELD, MISSING, and ORPHANED worktree states,
  constructed in a scratch repository, is classified and labeled correctly,
  with ORPHANED never rendered as an active workflow (FR-30).
- **SC-9**: A second `/smith-activity` invocation from a different project
  results in exactly one daemon process, two registered projects, and two
  working URLs (FR-2/FR-3).
- **SC-10**: A stale pidfile — pid absent, and pid present but foreign — is
  cleaned up and the daemon restarted, with a zero exit status in both cases
  (FR-6).
- **SC-11**: Token rollup over a known JSONL fixture matches the expected
  input / output / cache-write / cache-read / normalized / USD values
  exactly, with pricing resolved through `load_pricing()` (FR-32/FR-33).
- **SC-12**: A statusline payload lacking `rate_limits` renders an explicit
  "unavailable" quota panel with every other panel unaffected (FR-35).
- **SC-13**: Installing over a pre-existing statusline leaves that
  statusline's output byte-for-byte unchanged, and installing over none
  produces a minimal default line (FR-45).
- **SC-14**: With `SMITH_ACTIVITY_CAPTURE_PROMPTS` unset, no prompt text and
  no tool input appears in any SSE frame, any API response, the UI, or
  `activity.log` (FR-48).
- **SC-15**: The daemon listens on `127.0.0.1` only (verified by socket
  inspection) and makes zero outbound connections during a full session
  (FR-4/FR-49).
- **SC-16**: Every new test is a flat `tests/*.test.sh` file and executes in
  CI under the existing workflow with no CI configuration change required
  (FR-54).
- **SC-17**: After `scripts/install.sh` runs against a clean
  `$CLAUDE_HOOKS_DIR`, `hooks/pricing.json` is present there, and
  `load_pricing()` + `match_family()` resolve the running model family
  (including `claude-opus-5*`) to a non-`None` entry carrying a
  `last_verified` date. A family whose authoritative rates could not be
  obtained resolves to an explicit unavailable rather than to a numeric rate
  (FR-62/FR-34).
- **SC-18**: A flat `tests/*.test.sh` assertion fails when any `hooks/*.sh`
  shipped by the repo is absent from `scripts/uninstall.sh`'s `SMITH_HOOKS`
  array, and passes on the completed array. Adding a new hook without
  updating the array fails the suite (FR-63).
- **SC-19**: Given a session with an outstanding `PermissionRequest` and a
  `claude agents --json` record whose `status` disagrees, exactly one
  divergence finding is produced naming both values and both sources; given
  the same session with `status` absent, zero findings are produced
  (FR-57).
- **SC-20**: A divergence finding raised for a `Task` dispatch and then
  retracted when the matching log block lands inside the 90-second two-sided
  window resolves to a visible settled state and is never removed from the
  panel without a trace (FR-59/FR-22).
- **SC-21**: With `~/.claude/settings.json` unreadable, absence detection is
  off and the UI carries an explicit notice, and zero absence findings are
  emitted; with it readable and a shipped hook unwired, exactly one
  shipped-but-not-wired divergence finding is emitted, distinct in
  classification from any never-fired absence finding (FR-60/FR-61).

## Assumptions

- **A-1 — Hook event availability is UNVERIFIED for most of the desired set.**
  `settings/smith-settings-fragment.json` wires only `SessionStart`,
  `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `SubagentStop`, and
  `Stop`. `SessionEnd`, `SubagentStart`, `TaskCreated`, `TaskCompleted`,
  `PreCompact`, `PostCompact`, `Notification`, `PermissionRequest`, and
  `PermissionDenied` are assumed to exist but MUST be verified against the
  installed Claude Code's `/hooks` output before the implementation depends
  on them. Since the questions gate, `PermissionRequest` / `PermissionDenied`
  are the load-bearing pair — FR-18's indicator is derived from them — and
  `ConfigChange` is load-bearing for FR-60's expected-hook refresh.
  `SubagentStart` is demoted to a latency optimization, because the
  `agent-<id>.meta.json` sidecar supplies the same dispatch metadata
  (FR-27); its documented fallback remains `PreToolUse` on `Task` plus
  sidechain detection (FR-43). Should `PermissionRequest` prove not to fire
  on the installed Claude Code, FR-18 degrades to `status`-only with the gap
  stated in the UI — it does not silently blank.
- **A-2 — The sub-500 ms emitter latency budget is a target to MEASURE, not
  an assumption to rely on.** No hook in this repo makes a network call
  today; the existing self-imposed timeouts are `context-loader.sh` at 5 s
  and `manifest-updater.sh` at 2 s, and the settings fragment declares no
  timeout field anywhere. The emitter would be the first on both counts. The
  budget must be validated by measurement during implementation, and FR-40's
  exit-0 guarantee holds regardless of whether the budget is met.
- **A-3 — Native `"type": "http"` hook entries are preferred but not
  assumed.** If detection at install time finds them unsupported, the
  `hooks/activity-emitter.sh` subprocess fallback is the shipped path, at a
  known cost of one process spawn per tool call.
- **A-4 — `hooks/workflow_summary_lib.py` is clean to import**: no
  import-time side effects, no global mutable state, no caching, no open
  handles, and env reads confined to `main()`. Its Python floor of 3.8 is
  documented at line 16 but is not enforced by any installer check, so the
  daemon targets the same 3.8 floor.
- **A-5 — Daemon lifecycle precedent.** `skills/smith-research/scripts/
  start-playwright-server.sh` is the closest existing pattern (port probe,
  `$TMPDIR` pidfile, stale-PID detection via `kill -0`, `nohup &`, readiness
  polling) and is assumed to be the model to follow. `scheduler/` is NOT a
  precedent — it is a launchd batch job that exits.
- **A-6 — `maintenance` is an accepted `--workflow` value** for
  `create-active-workflow.sh`, alongside `smith-new`, `smith-bugfix`,
  `smith-debug`, `smith-build`, `smith-index`, `smith-update`, and
  `smith-queue` (verified against the script's own validation list).
- **A-7 — Reads are never gated.** `hooks/workflow-gate.sh` gates writes
  only, and a detached daemon lives outside the hook system entirely, so the
  gate provides no enforcement against the daemon. Runtime state therefore
  lives under `~/.smith/activity/` — outside the gate's jurisdiction and
  outside every project vault — by design rather than by necessity (FR-7,
  FR-44).
- **A-8 — The browser is opened via the platform's default handler.** No
  browser is bundled, required, or detected; `--no-open` exists for
  headless use.
- **A-9 — `claude agents --json` is available, and its record shape is the
  OBSERVED one, not the documented one.** Verified against the installed
  Claude Code across 23 live records: `{pid, cwd, kind, name, sessionId,
  startedAt}` always, `status` in 6 of 23, and `waitingFor` / `state` / `id`
  in none. FR-18 and FR-26 were amended to that shape at the questions gate
  (`questions.md` Q1). If the command is unavailable entirely, the sessions
  panel degrades to hook-derived data only, losing the dead-session reaper
  and the FR-57 corroboration — but NOT the "waiting on permission"
  indicator, which is event-derived and independent of it. Any such
  degradation the UI must state rather than hide.

## Out of Scope

- **OOS-1 — Authoritative phase stamping.** A `set-workflow-stage.sh` plus
  edits to the four workflow skills so each stamps its own phase is
  explicitly OUT OF SCOPE; inference ships first. The rationale is worth
  recording because it is the crux of the audit framing: **stamping depends
  on each skill correctly calling the stamper.** If a skill misbehaves in
  exactly the way this audit exists to catch, the stamp is missing or wrong —
  and confidently wrong, which is the worst possible failure mode for an
  audit tool. Hook-derived observation has no such failure mode, because the
  harness emits the event regardless of what the skill prose says. Stamping
  remains a purely additive follow-up: FR-13 requires the resolver to prefer a
  marker `phase:` field if one ever appears, so adding stamping later costs
  zero resolver rework.
- **OOS-2 — No `launchd` agent.** The daemon is on-demand only and need not
  survive a reboot. No plist, no login item, no auto-start.
- **OOS-3 — Retention is EPHEMERAL.** There is no persistent event history
  across daemon restarts; a restart is a blank slate, and the UI says so
  rather than showing a silently truncated timeline. The storage layer MUST
  sit behind a clean boundary so that switching to a retained two-tier scheme
  later is a configuration change rather than a redesign. The SQLite file
  from the original sketch is therefore optional or in-memory for v1.
- **OOS-4 — No auto-open on `SessionStart`.** The dashboard opens only on an
  explicit `/smith-activity` invocation. A hook that opens a browser tab is
  exactly the kind of surprise this feature must not introduce.
- **OOS-5 — No changes to `workflow-summary.sh`'s own token attribution.**
  This spec documents that it shares FR-14's concurrent-workflow exposure,
  but fixing it is a separate change with its own blast radius.
- **OOS-6 — No changes to `hooks/workflow-gate.sh`'s `SAFE_VAULT_DIRS`.**
  `active-workflows` stays excluded, deliberately. This feature adapts to the
  gate; it does not negotiate with it.
- **OOS-7 — No remote, multi-machine, or shared-instance mode.** One machine,
  one loopback daemon, one operator.
- **OOS-8 — NO EDITS TO ANY WORKFLOW SKILL, of any kind, including
  documentation-only ones.** `skills/smith-new/`, `skills/smith-bugfix/`,
  `skills/smith-debug/`, `skills/smith-build/` and `skills/smith-finish/` are
  read-only inputs to this feature. The reason is structural rather than
  budgetary: **this feature observes those skills, so editing them changes
  the behavior being measured.** Two concrete edits were identified during
  planning and are explicitly barred here and banked instead:
  1. **`skills/smith-bugfix/SKILL.md:101`** is the only documentation of
     `create-active-workflow.sh`'s exit-3 marker collision, and its advice —
     pick a new slug — is wrong, because the marker is keyed on **branch**
     (`<safe-branch>.yaml`), not slug, so a new slug does not avoid the
     collision. Banked as **BANK-030**; to be filed as its own bugfix.
  2. **Normalizing the four workflow skills to write UTC** in their
     `Subagent invoked:` blocks is the real root-cause fix for the mixed-clock
     problem FR-58 works around. Also barred here, also banked, for the same
     reason. FR-58's append-offset ordering is the correct behavior for an
     observer regardless of whether the skills are ever normalized.

## Dependencies & Constraints

- **D-1 — Runtime**: bash, git, jq, and Python 3 stdlib only. The daemon is
  **Python 3 stdlib exclusively**, floor 3.8 (matching
  `hooks/workflow_summary_lib.py:16`). No Node, no npm, no pip, no virtualenv,
  no vendored wheels.
- **D-2 — Transport**: Server-Sent Events (`text/event-stream`). WebSockets
  are explicitly excluded.
- **D-3 — Network posture**: `127.0.0.1` bind only; zero outbound requests
  from the daemon or the served page.
- **D-4 — Reused code**: `hooks/workflow_summary_lib.py` (via
  `load_pricing()`, per FR-33's contract trap),
  `scripts/create-active-workflow.sh` / `clear-active-workflow.sh`,
  `scripts/lib/dedupehooks.jq`, and the vault layout produced by
  `metrics-tracker.sh`, `file-change-logger.sh`, and
  `subagent-vault-writeback.sh`.
- **D-5 — New artifacts**: `skills/smith-activity/SKILL.md`,
  `hooks/activity-emitter.sh`, `scripts/activity/{server,state,phases,
  worktrees,usage}.py`, `scripts/activity/phases.json`,
  `scripts/activity/statusline-tee.sh`, and
  `scripts/activity/static/{index.html,app.css,app.js,panels.js}` — **four**
  static files, not one. The brief's "single-file dashboard, no CDN, no build
  step" constraint is honored as **no build step**, not as **one file**: no
  bundler, no npm, no transpile, no minification, no CDN — plain `<link>` and
  `<script src>` against the already-running loopback server. This keeps every
  static file under the 300-line soft target that one ~800-line `index.html`
  would have broken. Install and uninstall MUST copy and remove all four
  (FR-51/FR-52). If `panels.js` later approaches the threshold, the
  pre-decided next split is to shed the phase stepper into
  `scripts/activity/static/stepper.js`.
- **D-6 — Modified artifacts**: `scripts/install.sh` (recursive
  `scripts/activity/` staging, the `hooks/*.json` glob, the pricing families,
  the statusline capture, and the stale `"Copy 9 hooks"` string —
  FR-51/FR-62/FR-63), `scripts/uninstall.sh` (the completed `SMITH_HOOKS`
  array and the surgical statusline restore — FR-52/FR-46/FR-63),
  **`hooks/pricing.json`** (current model families incl. `claude-opus-5*`,
  with `last_verified`, order-sensitive — FR-62),
  `settings/smith-settings-fragment.json`, `docs/hooks.md`,
  `docs/architecture.md`, `docs/security-model.md`, the README skill table
  and badge, and `CHANGELOG.md`. **`hooks/workflow_summary_lib.py` is NOT on
  this list and MUST NOT be** — it is imported and called, never edited
  (FR-33/FR-36).
- **D-7 — Runtime state**: `"${SMITH_HOME:-$HOME/.smith}"/activity/` holding
  `activity.pid`, `activity.port`, `activity.token`, `activity.log`, and
  `wrapped-statusline`.
- **D-8 — CI constraint**: `.github/workflows/test-install.yml` runs ONLY
  flat `tests/*.test.sh`. Python tests and subdirectory shell tests do not
  execute in CI today, so every gating test this feature adds must be a flat
  `tests/*.test.sh` file (FR-54).
- **D-9 — Install-merge constraint**: hook merging is idempotent at the
  (matcher, command) level and preserves chain order within an entry; the
  documented `file-change-logger` → `lint-on-save` → `manifest-updater`
  ordering must survive this feature's additions.
- **D-10 — Uninstall constraint**: `scripts/uninstall.sh` restores
  `settings.json` wholesale from the newest `.bak-` file and performs no
  surgical removal, so statusline restoration requires an explicit new code
  path (FR-46).
