---
feature: 60-activity-dashboard
primary_system: cross-system
branch: 60-activity-dashboard
status: planned
---

# Implementation Plan: `/smith-activity` — Local Real-Time Smith Activity Audit Dashboard

## Questions Gate Outcomes

The Phase 5 questions gate is **ANSWERED**. Nine decisions, recorded in full
with their reasoning in [`questions.md`](./questions.md), bind this plan. They
are summarized here so a build reader does not have to open another file; where
this summary and `questions.md` differ, **`questions.md` is the authority**.

| # | Decision | Effect on this plan |
|---|---|---|
| **Q1** | **C — both sources.** `PermissionRequest` / `PermissionDenied` are the PRIMARY signal for "waiting on a permission prompt"; `claude agents --json` `status` is corroboration **where present**; their disagreement is a divergence finding. `waitingFor`, `state` and `id` are present in **zero** of 23 live records; `status` in only 6. | **FR-18 and FR-26 rewritten**, **FR-57 added**. `sessions.py` codes against `{pid, cwd, kind, name, sessionId, startedAt, status?}` only. `findings.py` gains a `permission_disagreement` classification. The poll is scoped to **liveness reconciliation**. |
| **Q2** | **A — fix both.** `scripts/install.sh` must copy `hooks/*.json` (it globs only `*.sh` at `:195` and `*.py` at `:203`), and `hooks/pricing.json` must gain current families including `claude-opus-5*`. | **FR-62 added.** Also repairs the pre-existing `Stop`-hook summary, which has been silently omitting USD for the same reason. **Rates must not be invented** — see the constraint block below. |
| **Q3** | **A — build live subagent token parsing in v1.** Parse `subagents/agent-<id>.jsonl` for sidechain usage; read the `agent-<id>.meta.json` sidecar for `agentType` / `description` / `parentAgentId` / `spawnDepth` / `toolUseId`. | **FR-36 and FR-27 amended.** Implemented in `scripts/activity/usage.py`; **`hooks/workflow_summary_lib.py` is NOT modified**. Deferral rejected: the parent transcript has zero `isSidechain` rows, so a deferred FR-36 reads `0` for every running subagent. |
| **Q4** | **A — accept the four-file static split.** The constraint is **no build step**, not **one file**. | **D-5 amended.** `static/{index.html ~120, app.css ~220, app.js ~180, panels.js ~260}`. Install **and uninstall** handle all four. `stepper.js` is the pre-decided next split. |
| **Q5** | **A — 90 s, TWO-SIDED, ordered on session-log append offset, findings retractable.** | **FR-11 amended** (the `PreToolUse` Task event does **not** reliably precede the log block — all four SKILLs write the block first), **FR-22 amended** with the window, **FR-58 added** (parsed timestamps must never order anything: the log mixes UTC and local clocks, 4-hour skew observed), **FR-59 added** (a retracted finding must visibly resolve, never silently vanish). |
| **Q6** | **A — expectation comes from the INSTALLED `~/.claude/settings.json`**, refreshed on `ConfigChange`, intersected with the applicability table; **disabled with a visible UI notice** if unreadable. | **FR-60 added**; ratifies `research.md` §Q3. **FR-61 added** for the corollary class: "Smith ships this hook, your settings don't wire it" — distinct from "wired but never fired". Live instance: `hooks/pricing.json` is in the repo and never installed. |
| **Q7** | **A — complete `SMITH_HOOKS`.** `scripts/uninstall.sh` lists 11 of 20 shipped hooks. | **FR-63 added.** The list is **derived from the actual contents of `hooks/` at build time**, never transcribed from a count. A flat `tests/*.test.sh` assertion locks it. `scripts/install.sh:138`'s `"Copy 9 hooks"` is fixed in the same change. |
| **Q8** | **A — file separately.** Do **not** edit `skills/smith-bugfix/SKILL.md` or any workflow skill. | **OOS-8 added.** Banked as **BANK-030**, alongside the Q5 UTC-normalization item. The boundary is structural, not budgetary: this feature *observes* those skills, so editing them changes the behavior being measured. |
| **Q9** | **A — run `/smith-index` after this feature merges.** Not on the critical path. | Recorded as a post-merge follow-up in §Rollout notes, with the verified `.gitignore` condition and one observed contradiction. |

**Constraint carried forward from Q2, binding at build time:** the pricing
rates **must NOT be invented**. Consult the authoritative Claude pricing
reference — **the `claude-api` skill is the designated source and it
explicitly forbids answering from memory** — and set `last_verified` to the
date checked. If authoritative rates cannot be obtained, add the family entry
with the correct match pattern and leave its rates **unavailable** rather than
guessed: FR-34's "never `$0.00`" applies to fabricated rates exactly as it
applies to missing ones. And **`pricing.json` entry ORDER is load-bearing** —
`match_family()` returns the first array-order regex match, so a more specific
family must precede any wildcard that would also match it.

## Technical Context

- **Repo**: Smith skills distribution. No application runtime. Deliverables
  are one new skill, one new hook, a fourteen-module Python 3.8 stdlib daemon
  under `scripts/activity/`, a four-file static front end, one data file
  (`phases.json`), one flat CI test plus a Python unit-test package, and
  targeted edits to `install.sh`, `uninstall.sh`, the settings fragment, three
  docs, the README and `CHANGELOG.md`.
- **This is the largest feature in this repo to date** — 63 FRs, 21 SCs, 10
  user stories, and the first HTTP server, first SSE stream, first
  network-calling hook, first `timeout` field and first `statusLine` key the
  repo has ever had. `research.md` §R establishes that **zero** HTTP-server,
  SSE or socket code exists anywhere in the tree today.
- **Primary references**: `research.md` (the eight resolved decisions, every
  measurement, and the reuse inventory), `data-model.md` (state tree,
  `phases.json` schema, the read-only external formats), and `contracts/`
  (HTTP surface, SSE frames, `phases.json` sync contract, hook envelope).
  Nothing in those four is restated here.
- **`setup-plan.sh` was NOT run.** It is broken for this repo in three
  independent ways and has been for every recent feature — see
  §"Repo-dev deviations". Paths were computed directly.
- **No `constitution.md` exists in this repo** — matching every prior
  feature's plan in this worktree (54-59).
- **Endpoint — CLOSED.** This feature's questions gate (Phase 5) has run and
  is **ANSWERED** — nine decisions, summarized in §Questions Gate Outcomes
  above and recorded in full in `questions.md`. Nothing in this plan is left
  conditional on the gate. §"Questions gate (Phase 5) — resolved" at the end
  records the disposition of the four items this plan originally deferred to
  it.

## Constitution Gates

**N/A — no `constitution.md` or `.specify/memory/constitution.md` exists in
this repo**, so there are no constitution-derived gates to check. The
substitute conventions have a real on-disk source,
`templates/constitution-additions.md:1-36`:

- **File Size Policy** (`:1-13`) — 300-line soft target, 300-500 warrants a
  decomposition review, over 500 SHOULD be decomposed unless auto-generated,
  a single-purpose data file, or a test where decomposition harms readability.
  Enforced by this plan's §File Size Policy.
- **Clean Architecture Policy** (`:15-36`) — names `/smith-clean-code` as the
  canonical rubric. `skills/smith-clean-code/SKILL.md` (539 lines) is
  referenced, not restated; only the feature-specific structural decisions are
  recorded here.

`skills/smith-new/SKILL.md:269-274` is what actually binds this plan:
*"Flag any planned file expected to exceed 300 lines and split it up front."*
§File Size Policy answers it file by file.

## Repo-dev deviations (recorded, not fixed)

| Deviation | Evidence | Handling |
|---|---|---|
| `setup-plan.sh` rejects two-digit branches | `skills/smith/scripts/common.sh:75` — `=~ ^[0-9]{3}-`; executed, fails on `60-activity-dashboard` | Paths computed directly |
| `setup-plan.sh` copies from a path that does not exist | `setup-plan.sh:40` reads `$REPO_ROOT/.specify/templates/plan-template.md`; templates live at `skills/smith/templates/` | Template read from its real location |
| `setup-plan.sh` targets the wrong layout | `common.sh:85` — `get_feature_dir() { echo "$1/specs/$2"; }`; this repo uses `.specify/systems/<system>/features/<n>-<slug>/` | Feature dir used directly |
| `update-agent-context.sh` fails for the same reason | Executed: `ERROR: No plan.md found at …/specs/60-activity-dashboard/plan.md` | Tried as instructed; noted; moved on |
| `.smith/index/` absent, so `/smith-navigate` is unavailable | `ls .smith/` → no such directory | Reuse detection done by grepping affected paths directly (§Reuse-before-create). **Running `/smith-index` would make this cheaper for feature 61** |

Fixing the scaffolding scripts is deliberately **out of scope**: it is a shared
change across features 54-60 with its own blast radius, and bundling it into a
feature whose highest-risk surface is already a `PreToolUse` hook would mix two
unrelated regression risks.

## Architecture Summary

Five boundaries, in dependency order. Nothing above depends on anything below
it in the same column, and the two pure layers have no I/O at all.

**1. The emitter — `hooks/activity-emitter.sh` (~60 lines).**
Forwards stdin byte-for-byte to `POST /ingest` via a detached, bounded `curl`.
Parses nothing, exits 0 unconditionally, writes nothing to stdout. Preferred
path is a native `"type": "http"` settings entry with no process spawn at all
(FR-42). This is the highest-risk surface in the feature and is built and
tested **first** (§Phased ordering). Contract: `contracts/hook-envelope.md`.

**2. The pure core — `phases.py` + `findings.py` (~460 lines, no I/O).**
`phases.py` is a state machine over an ordered event stream keyed by workflow
type (FR-10), with the FR-11 signal precedence, the FR-14 attribution rule,
FR-17 nesting and FR-20's honest `phase unknown`. `findings.py` derives
divergence and absence from the same resolved structures.

Both take plain dicts and lists in and return plain dicts out. **No file
reads, no git, no network, no clock except an injected `now`.** That is what
makes SC-1/SC-2/SC-5/SC-6 replayable against fixtures with no live daemon, and
it is the single most important structural decision in the plan.

**3. The readers — `markers.py`, `sessionlog.py`, `worktrees.py`, `usage.py`,
`vault.py`, `sessions.py`, `paths.py` (~1180 lines).**
One module per external contract, each doing I/O and returning the plain
structures layer 2 consumes. `usage.py` imports `hooks/workflow_summary_lib.py`
and calls it; it reimplements nothing.

**4. The daemon — `server.py`, `ingest.py`, `state.py` (~580 lines).**
`server.py` is routing and SSE transport only. `ingest.py` is envelope
validation and redaction — redaction happens here, before the state tree, so
no downstream layer can leak (FR-48). `state.py` owns the single locked state
tree and the coalescing broadcaster (FR-41).

**5. The surfaces — `smith-activity.sh`, `statusline-tee.sh`,
`static/*` (~1040 lines).**
The lifecycle CLI mirrors `start-playwright-server.sh`'s discipline; the tee
wraps rather than clobbers (FR-45); the front end is four local files served
from `static/`, with no external origin of any kind (FR-49).

**The inversion that matters.** Hook events are the ground-truth spine and
vault content is annotation (FR-21). Structurally: `ingest.py` writes spine
events into `state.py` with no interpretation, while every reader in layer 3
writes *annotations* tagged with their source. `phases.py` resolves by the
FR-11 precedence and **keeps both values** when they disagree, because the
disagreement is the product (`data-model.md` §2.10). No layer is permitted to
"reconcile" a conflict by discarding one side.

## Reuse-before-create (exact components reused, not reinvented)

Full derivation in `research.md` §R. The operative list:

- **`hooks/workflow_summary_lib.py` (939 lines) — imported and called, never
  copied.** `usage.py` consumes `load_pricing`, `match_family`, `normalize`,
  `cost_usd`, `parse_parent_jsonl`, `resolve_parent_jsonl`,
  `resolve_workflow_window`, `parse_subagent_blocks`, and the three
  `format_*` renderers. **The contract trap is honored absolutely**:
  `match_family` reads a `_compiled_patterns` key that only `load_pricing`
  injects (`:122` writes it, `:134` reads it with `.get(…) or []`), so a raw
  `json.load` of `pricing.json` makes every model resolve to `None` with no
  exception and no log line. `usage.py` obtains the table **only** via
  `load_pricing()`, and the test suite greps `scripts/activity/` for any
  independent `pricing.json` parse. Import mechanism reused verbatim from
  `hooks/workflow-summary.sh:198-214` (`PYTHONPATH="$HOOK_DIR"`, three-candidate
  `HOOK_DIR` ladder). Safe for a long-lived daemon — verified: no import-time
  side effects, no global mutable state, no caching, no open handles, env reads
  confined to `main()` at `:843-845`. **But it caches nothing**, so the daemon
  throttles: `load_pricing()` once at startup, mtime-gated refresh at most once
  per 60 s; `parse_parent_jsonl` at most once per session per ~2 s from a
  remembered byte offset. *Otherwise duplicated: ~250 lines of
  normalize/cost/pricing/JSONL, plus a from-scratch re-creation of the trap.*
- **`skills/smith-research/scripts/start-playwright-server.sh` (92 lines) — the
  only real daemon-lifecycle precedent in the repo.** `smith-activity.sh`
  mirrors its already-up short-circuit (`:48-52`), stale-PID detection via
  `kill -0` (`:54-61`), `nohup … &` + `echo $! > pidfile` (`:72-80`), bounded
  readiness poll (`:82-92`), `set -euo pipefail`, documented exit codes, and
  last-stdout-line-is-the-URL. **Two deviations, both justified:** the pidfile
  lives under `~/.smith/activity/` not `$TMPDIR` (FR-7 — `$TMPDIR` is swept on
  macOS, and a dashboard expected to be up tomorrow cannot have its pidfile
  garbage-collected); and the port probe never uses `/dev/tcp`, which does not
  exist under `zsh` (measured — `research.md` §Q7). *Otherwise duplicated:
  ~60 lines and its accumulated edge cases.*
- **`scripts/lib/dedupehooks.jq` + `scripts/install.sh:284-318` — reused as-is;
  no second merge path is invented.** The dedupe key is the individual
  `(matcher, serialized-hook-object)` pair (`dedupehooks.jq:21`), so a
  `timeout` field participates in identity; chain order is preserved by
  construction. The write guard (`install.sh:309-318` — tempfile, `jq empty`,
  `mv` only on success) is reused unchanged. **The hazard, and how this plan
  avoids it:** `scripts/install-hooks.sh:6-7,149-183` enforces that
  `manifest-updater.sh` stays LAST in the `PostToolUse` `Write|Edit` chain, and
  `tests/hooks/test_hook_chain_order.sh` is a regression test for it. **The
  emitter is therefore never appended to an existing chain** — it gets its own
  entry with matcher `*`, exactly like `hooks/metrics-tracker.sh`
  (`settings/smith-settings-fragment.json:48-53`), which is also the only
  existing hook that already sees every tool call. *Otherwise duplicated: an
  idempotent settings merge — the most dangerous thing in this repo to have two
  of. `scripts/dedupe-settings.sh:48-52` already shares this module precisely
  so "the two can never drift apart" (its `:11`).*
- **`scheduler/` — layout and logging conventions ONLY.** Borrowed: the
  `~/.smith/<component>/` shape and the UTC bracketed append-only log line
  (`smith-scheduler.sh:43-45`). **NOT borrowed: `smith-scheduler.sh:36`,
  `SMITH_DIR="$HOME/.smith"`** — it hardcodes the path and does not honor
  `SMITH_HOME`, even though `install.sh:254` copies it into
  `"$SMITH_HOME/scheduler/"`. That is a latent bug, not a pattern. **The
  canonical form is the installer's**, `"${SMITH_HOME:-$HOME/.smith}"`
  (`install.sh:20`, `uninstall.sh:15`), and this feature uses it everywhere.
  Also not borrowed: `scheduler/` is a launchd batch job that exits, not a
  daemon (A-5 is correct). **There is no log rotation anywhere in this repo**,
  so `activity.log` ships its own single 5 MB rollover — a daemon seeing every
  `PostToolUse` would otherwise grow unbounded.
- **Existing hook idioms.** Reused: `set -uo pipefail` (never `-e` — the
  guard/loader hooks avoid it deliberately);
  `INPUT=$(cat 2>/dev/null || echo '{}')`; the early-bail ladder where each
  branch logs a `reason=` and exits 0; the shared
  `LOG_FILE="${HOME}/.smith/logs/hooks.log"` with every write suffixed
  `2>/dev/null || true`; a trailing unconditional `exit 0`. **NOT reused: the
  `TIMEOUT_BIN` idiom** (`context-loader.sh:117-122`,
  `manifest-updater.sh:122-127`) — neither `timeout` nor `gtimeout` exists on a
  stock macOS, verified on this machine, so those hooks' documented 5 s and 2 s
  budgets impose **no bound at all** there. The emitter's bound comes from
  `curl --max-time`, which is built in and was measured to hold exactly.
- **`create-active-workflow.sh --workflow maintenance` with a synthetic
  `--branch` label** for FR-8, exactly as `/smith-audit --scheduled` already
  does — a precedent `docs/security-model.md:165` documents in so many words.
  `maintenance` is in the allowlist (`create-active-workflow.sh:115`,
  confirming A-6). Cleared via `.specify/scripts/bash/clear-active-workflow.sh`
  — note it lives at `skills/smith/scripts/`, **not** `scripts/`, and
  `install.sh:225-226` stages only `create-active-workflow.sh` into
  `~/.smith/scripts/`.
- **Session-log discovery precedence** reused verbatim from
  `hooks/workflow-summary.sh:84-135`: explicit path → marker `session_log:`
  (disambiguated by `branch:` when several carry one) → `.current-session`.
  Plus `metrics-tracker.sh:23-32`'s double existence check.
  *Otherwise duplicated: a three-tier discovery heuristic with a known rollover
  hazard.*
- **Test harness** reused verbatim in shape from
  `tests/settings-dedupe.test.sh:10-27` (`set -uo pipefail` header,
  `SCRIPT_DIR`/`REPO_ROOT`, `PASS`/`FAIL` counters, one `assert` helper,
  `mktemp -d -t` + `trap … EXIT`, `# --- Test N ---` banners, summary line) and
  `tests/get-base-branch.test.sh:24-40`'s `make_repo`. **No existing test uses
  `git worktree`**, so the SC-8 fixtures extend `make_repo` with a
  `git worktree add` step — a documented extension, not a new harness.
  `tests/_harness.py` already puts `hooks/` on `sys.path`, which is exactly
  what `usage.py`'s tests need.

**Three pre-existing defects this feature fixes** — the first two because it
is the second consumer of the affected file and would otherwise reproduce the
same silent failure, the third because the questions gate widened the scope to
it (Q2, Q7):

1. **`hooks/pricing.json` is never installed.** `install.sh:195` globs
   `hooks/*.sh` and `:203` globs `hooks/*.py`; nothing copies `*.json`. The
   copy at `~/.claude/hooks/pricing.json` on this machine is dated 2026-04-14,
   left by an older installer and never refreshed since. A clean install gets
   no pricing file at all, `load_pricing()` returns `None`, and every USD
   figure in `workflow-summary.sh` is *already* silently unavailable. **Fixed
   by adding a `hooks/*.json` glob to the copy loop (FR-62).**
2. **`hooks/pricing.json`'s newest family is `claude-opus-4-6*`.** The running
   model is `claude-opus-5`, so even an installed file resolves to `None`.
   **Fixed by adding the current families (FR-62)** — under the
   never-invent-rates constraint in §Questions Gate Outcomes, and respecting
   the order-sensitivity of `match_family()`'s first-match-wins scan.
3. **`uninstall.sh:85-91`'s `SMITH_HOOKS` array is hand-maintained and
   stale** — it lists 11 of the 20 `.sh` files that ship, orphaning nine on
   uninstall. **Q7 resolved this to option A: complete the array**, not just
   append `activity-emitter.sh`. The list is derived from `ls hooks/*.sh` at
   implementation time rather than transcribed from any count stated in a spec
   or a question, and a flat `tests/*.test.sh` assertion locks it so the drift
   cannot silently return (FR-63/SC-18). `install.sh:138`'s hardcoded
   `"Copy 9 hooks"` preview string — a third stale count in the same pair of
   files — is corrected in the same change.

## File Size Policy

300-line soft target, 500-line decomposition threshold
(`templates/constitution-additions.md:1-13`). **Three files the task framing
correctly flagged as at-risk are split up front, before a line is written.**

### `server.py` — would have been ~600. Split into three.

A single `server.py` holding routing, SSE, ingest parsing, redaction and the
state tree is the default shape for a stdlib HTTP daemon and it lands around
600 lines. Split by responsibility, not by line count:

| File | Est. | Responsibility |
|---|---|---|
| `server.py` | **~200** | `ThreadingHTTPServer`, the handler, the route table, SSE framing/keepalive/backpressure. Knows nothing about what an event means |
| `ingest.py` | **~150** | envelope validation, size cap, **redaction** (FR-48), spine-event construction. The redaction boundary is a *file* boundary so "did redaction run before storage?" is answerable by reading one import |
| `state.py` | **~230** | the locked state tree, the 200 ms coalescing broadcaster, `generation`, projections for `/api/*` and SSE |

### `phases.py` — would have been ~450. Split into two.

Phase resolution and finding derivation are both pure and both naturally live
in one file; together they exceed the target.

| File | Est. | Responsibility |
|---|---|---|
| `phases.py` | **~280** | `phases.json` loading, `normalize_phase_title()`, the FR-11 signal precedence state machine, FR-14 attribution, FR-17 nesting, FR-20 unknown. **Zero I/O except reading `phases.json` once** |
| `findings.py` | **~200** | divergence (FR-22/FR-57/FR-61) and absence (FR-23) derivation from resolved structures. **Zero I/O.** `RECONCILE_WINDOW_S = 90` lives here, applied **two-sided** and keyed on append offset, never on a parsed timestamp (FR-58); so does retraction, which resolves a finding to a visible settled state rather than deleting it (FR-59) |

`findings.py` also carries the expected-hook applicability table
(`research.md` §Q3) as a ~10-line module constant — data, greppable, unit
testable without a settings file, and too small to warrant its own JSON file
the way `phases.json` does.

### `static/index.html` — the single-file/no-build-step tension, addressed

The spec's D-5 names `scripts/activity/static/index.html` as a single file.
A dashboard with a stepper, five panels, a findings list and an SSE client
lands around **800 lines** as one file. That is above the *decomposition*
threshold, not merely the soft target.

**The constraint is "no build step", not "one file".** `<link rel=stylesheet>`
and `<script src>` are not a build step — they are two more HTTP GETs against
a loopback server that is already serving the page. Nothing is bundled,
transpiled, minified or npm-installed; D-1 and G9 are untouched. FR-49 is
satisfied because all four files are served from
`scripts/activity/static/` with no external origin.

| File | Est. | Responsibility |
|---|---|---|
| `static/index.html` | **~120** | document shell, panel containers, `<template>` elements. No logic |
| `static/app.css` | **~220** | all styling, incl. the four phase states and the two finding kinds. Light/dark via `prefers-color-scheme` |
| `static/app.js` | **~180** | `EventSource` client, `hello`/`state`/`delta`/`resync`/`quota`/`finding` dispatch, generation tracking, reconnect, project filter |
| `static/panels.js` | **~260** | one render function per panel: stepper, sessions, subagents, worktrees, tokens+quota, vault, findings |

**Ratified at the questions gate (Q4, answer A).** `scripts/install.sh` and
`scripts/uninstall.sh` must therefore copy and remove **all four** static
files, not just `index.html` — see the MODIFIED table below.

`panels.js` at ~260 is the one file with the least headroom. If the stepper's
four-state rendering plus the nested-handoff case pushes it past 300 during
implementation, the split is already decided: **`panels.js` sheds the stepper
into `static/stepper.js`**, because the stepper is the one panel with its own
state vocabulary (`completed`/`current`/`remaining`/`skipped`) and the one most
likely to keep growing.

### Everything else

| File | Est. | Note |
|---|---|---|
| `skills/smith-activity/SKILL.md` | ~220 | prose; references `contracts/` rather than restating |
| `scripts/activity/smith-activity.sh` | ~190 | `start\|stop\|restart\|status\|open` + `--port`/`--no-open`/`--foreground` |
| `scripts/activity/statusline-tee.sh` | ~70 | read stdin once, fork a copy, delegate |
| `scripts/activity/phases.json` | ~230 | **single-purpose data file — explicitly exempt** per the policy's own carve-out |
| `scripts/activity/paths.py` | ~90 | `SMITH_HOME`, `primary_repo()`, project slug, `~/.claude/projects` layout |
| `scripts/activity/markers.py` | ~120 | marker discovery + tolerant YAML read (incl. the `smith-finish` variant) |
| `scripts/activity/sessionlog.py` | ~200 | the four block formats + the three-tier discovery |
| `scripts/activity/worktrees.py` | ~200 | `git worktree list --porcelain`, 3 s debounce cache, the 6-row classification table |
| `scripts/activity/usage.py` | ~220 | rollups, sidecar discovery, incremental JSONL tail, `load_pricing()` |
| `scripts/activity/vault.py` | ~190 | `stat`-based vault polling (FR-38) |
| `scripts/activity/sessions.py` | ~160 | `claude agents --json` reconciler + the reaper |
| `hooks/activity-emitter.sh` | ~60 | see `contracts/hook-envelope.md` |
| `tests/smith-activity.test.sh` | ~280 | the flat CI gate |
| `tests/activity/test_phases.py` | ~260 | |
| `tests/activity/test_usage.py` | ~200 | |
| `tests/activity/test_findings.py` | ~180 | |
| `tests/activity/test_worktrees.py` | ~150 | |

Fourteen Python modules averaging ~185 lines. **No planned file exceeds 300
lines except `phases.json`, which is data.**

Two further clean-architecture decisions worth recording, per
`skills/smith-clean-code/SKILL.md`'s dependency-direction and testability
sections (referenced, not restated):

- **Dependency direction is strictly inward.** `server.py` → `state.py` →
  `phases.py`/`findings.py`. The pure core imports nothing from the daemon or
  the readers. A reader may be swapped for a fixture with no change above it,
  which is what makes SC-1/SC-2/SC-5/SC-6 replayable.
- **Side effects are isolated to layer 3 and layer 4.** Layers 1 and 2 have
  none. `findings.py` takes `now` as a parameter rather than calling
  `datetime.now()`, so the 90 s reconciliation window is testable without
  sleeping.

## Contracts

Four files under `contracts/`, each the authority for its surface:

| File | Covers |
|---|---|
| `contracts/http-surface.md` | bind/token/route table, `POST /ingest`, `GET /health`, `GET /api/state`, and the explicit "what the daemon MUST NOT do" list |
| `contracts/sse-frames.md` | stream mechanics, the coalescing rule, the six event names, all six payloads, the redaction boundary |
| `contracts/phases-json.md` | the seeded content for all five chains with SKILL.md line numbers, the `match`-pattern conventions, the five title-normalization rules, and the FR-16 extraction contract |
| `contracts/hook-envelope.md` | the envelope, the wired event set and chain-placement rule, why `SubagentStart` is an optimization, the redaction field list, why the emitter parses nothing, and the measured costs |

`data-model.md` §3 holds the `phases.json` schema and invariants; §2 holds the
state tree; §4 holds the read-only external formats.

## Exact file-by-file change list

### NEW

| File | Purpose |
|---|---|
| `skills/smith-activity/SKILL.md` | The skill. Frontmatter `name` + `description` + `argument-hint` (the repo's only frontmatter vocabulary — **`allowed-tools` does not exist anywhere in this repo**; `tools:` is the single precedent, at `smith-taskstoissues`). Documents `[start\|stop\|restart\|status\|open]`, `--port`/`--no-open`/`--foreground`, and the FR-8 marker discipline. |
| `hooks/activity-emitter.sh` | FR-40's fallback emitter. Full script in `research.md` §Q7. |
| `scripts/activity/smith-activity.sh` | Lifecycle CLI (FR-1/2/5/6/7). Mirrors `start-playwright-server.sh`'s discipline with the two documented deviations. |
| `scripts/activity/statusline-tee.sh` | FR-45. Reads stdin once, forwards a copy in the background, delegates to the stored command; minimal default line when none existed. |
| `scripts/activity/server.py` | HTTP routing + SSE transport (`contracts/http-surface.md`, `contracts/sse-frames.md`). |
| `scripts/activity/ingest.py` | Envelope validation, 256 KiB cap, **redaction before storage** (FR-48). |
| `scripts/activity/state.py` | The locked state tree + 200 ms coalescing broadcaster (FR-41). |
| `scripts/activity/phases.py` | **Pure.** FR-9/10/11/12/13/14/17/19/20. `normalize_phase_title()` lives here and the sync test imports it. |
| `scripts/activity/findings.py` | **Pure.** FR-22/23/24 + the three questions-gate additions FR-57 (permission-state disagreement), FR-59 (retraction resolves visibly) and FR-61 (shipped-but-not-wired) + `RECONCILE_WINDOW_S = 90`, two-sided and offset-keyed (FR-58) + the expected-hook applicability table (FR-60). |
| `scripts/activity/markers.py` | Marker discovery under the primary repo **and** every live worktree (`data-model.md` §1 — `create-active-workflow.sh:139` uses `--show-toplevel`, so markers for a `/tmp` worktree land in the worktree's vault, not the primary's), plus the tolerant read. |
| `scripts/activity/sessionlog.py` | The four block formats + `workflow-summary.sh:84-135`'s discovery precedence. |
| `scripts/activity/worktrees.py` | FR-29/30/31. The 6-row classification table from `data-model.md` §2.6. |
| `scripts/activity/usage.py` | FR-32/33/34/36. `load_pricing()`-only pricing; `agent-<id>.meta.json` sidecar discovery (`agentType` / `description` / `parentAgentId` / `spawnDepth` / `toolUseId`, feeding FR-27); incremental sidechain JSONL tail. **Q3 confirms this ships in v1 and that `hooks/workflow_summary_lib.py` is NOT modified to do it.** |
| `scripts/activity/vault.py` | FR-37/38. Read-only. |
| `scripts/activity/sessions.py` | FR-25/26 + the liveness reaper, against the **observed** `claude agents --json` record shape `{pid, cwd, kind, name, sessionId, startedAt, status?}` — **`waitingFor` / `state` / `id` are never read** (Q1). Also emits the FR-57 corroboration comparison; the permission indicator itself is derived in `phases.py`/`findings.py` from `PermissionRequest` / `PermissionDenied`. |
| `scripts/activity/paths.py` | `SMITH_HOME`, `primary_repo()` (FR-28, with `--path-format=absolute`), project slug, transcript layout. |
| `scripts/activity/phases.json` | FR-15. Seeded content in `contracts/phases-json.md` §1. |
| `scripts/activity/static/{index.html,app.css,app.js,panels.js}` | The dashboard. Four local files, no external origin (FR-49). |
| `tests/smith-activity.test.sh` | **The CI gate** (FR-54). Flat, top-level. Covers the shell surfaces directly and wraps the Python suite. |
| `tests/uninstall-hook-coverage.test.sh` | **Flat, top-level (FR-63/SC-18).** Asserts every `hooks/*.sh` in the repo appears in `scripts/uninstall.sh`'s `SMITH_HOOKS` array, and that `install.sh`'s hook-count preview is derived rather than hardcoded. Its own file rather than a case inside `smith-activity.test.sh`, because it guards a repo-wide invariant that outlives this feature and must keep failing for hooks that have nothing to do with the dashboard. |
| `tests/activity-pricing.test.sh` | **Flat, top-level (FR-62/SC-17).** Asserts `install.sh` copies `hooks/*.json`; that `load_pricing()` + `match_family()` resolve `claude-opus-5*` to a non-`None` entry; that every family carries `last_verified`; and that no family carries a numeric rate without one. |
| `tests/activity/{__init__.py,test_phases.py,test_usage.py,test_findings.py,test_worktrees.py,test_markers.py,test_sessions.py,test_vault.py}` | FR-55/56. Reuses `tests/_harness.py` (extended additively to put `scripts/activity` on `sys.path`). `test_markers.py` was added after the FR-17 correction: the dual-vault enumeration and the empty-`session_log:` fallback are the most load-bearing new reader contract in the feature and had no covering test. `test_sessions.py` and `test_vault.py` cover `sessions.py` and `vault.py`, which the original table also left untested. |
| `tests/activity/fixtures/` | Fixture session logs (incl. the two-interleaved-workflows case), marker sets, a known-usage JSONL, and a `.meta.json` sidecar. |

### MODIFIED

| File | Change |
|---|---|
| `settings/smith-settings-fragment.json` | New hook entries, each its **own** `{matcher, hooks}` object — never appended to an existing chain, because `install-hooks.sh:149-183` and `tests/hooks/test_hook_chain_order.sh` require `manifest-updater.sh` to stay last in the `PostToolUse` `Write\|Edit` chain. Wired set in `contracts/hook-envelope.md` §2. **This is the first `timeout` field and the first `"type": "http"` entry in the file** — both verified absent today. |
| `scripts/install.sh` | **(1)** New staging block copying `scripts/activity/` → `$SMITH_HOME/scripts/activity/` **recursively**, mirroring the existing `scripts/smith-index` block (`:217`) — `cp -R` is required because `phases.json` and `static/*` are neither `.sh` nor `.py`. **(2)** A `hooks/*.json` glob added to the hook copy loop (alongside the existing `*.sh` at `:195` and `*.py` at `:203`), so `pricing.json` is installed and refreshed — closing a gap that silently disables USD in `workflow-summary.sh` today (FR-62, Q2). A glob, not a single `cp`, so the next `hooks/*.json` is not a fourth stale enumeration. **(3)** Statusline capture: read the current `statusLine` value, write `{"had_statusline":bool,"previous":…}` to `~/.smith/activity/wrapped-statusline`, then set `statusLine` to the tee — a **new top-level settings key**, so it goes through `$existing * $fragment` rather than the `.hooks` rebuild. **(4)** Install-time `"type": "http"` support detection (FR-42), defaulting to the emitter on any doubt — the fallback costs ~1.8 ms of foreground time, measured, so conservative detection is free. **(5)** `install.sh:138`'s hardcoded `"Copy 9 hooks"` preview line corrected — derived from `ls hooks/*.sh | wc -l` rather than re-hardcoded (FR-63, Q7). **(6)** Stages the shipped-hook manifest FR-61 compares against into `$SMITH_HOME/activity/`, because FR-60 forbids the daemon from reading the repo fragment and the daemon has no reason to know where a checkout lives. |
| `hooks/pricing.json` | Current model families added, **including `claude-opus-5*`** (FR-62, Q2). Rates come from the authoritative Claude pricing reference via the **`claude-api` skill — never from memory** — and each entry carries `last_verified`. A family whose rates cannot be authoritatively obtained ships with its match pattern and **unavailable** rates, never a guess (FR-34). **Insertion position matters**: `match_family()` returns the first array-order match, so a specific family goes ahead of any wildcard that would also match it. |
| `scripts/uninstall.sh` | **(1)** The `SMITH_HOOKS` array (`:85-91`) **completed to every hook the repo ships** — derived from `ls hooks/*.sh` at implementation time, not transcribed from a count, and locked by a flat test (FR-63/SC-18, Q7). `activity-emitter.sh` is one entry among them. **(1b)** Removal covers all four `static/*` files, not just `index.html` (Q4). **(2)** New block at `:124`, before the wholesale `.bak-` restore: stop the daemon (the LaunchAgent teardown at `:59-66` is the shape precedent), surgically restore or delete `statusLine` from the sidecar via a guarded `jq` (FR-46, `research.md` §Q5), then `rm -rf "$SMITH_HOME/activity"`. The restore is idempotent and order-independent, so it is safe before **or** after the `.bak-` restore, and it survives the operator declining that prompt (`:129`) and the keep-3 backup pruning (`install.sh:155`). `skills/smith-activity/` needs no edit — it matches the existing `smith-*` glob at `:76`. |
| `docs/hooks.md` | One row in the `## Hook Summary` table and one `### activity-emitter.sh` section under `## Detailed Reference`, using the existing per-hook template verbatim (`**Event:**` / `**Matcher:**` / `**What it does:**` / `**Files touched:**` / `**To disable:**`, `:62-70`). Adds a `**Privacy note:**` line, following `user-prompt-logger.sh`'s precedent, covering the redaction default. `:3`'s "Smith installs 10 hooks" is corrected. |
| `docs/architecture.md` | New `## Activity Daemon` section after `## Scheduler Model` (`:82`) — the two background-process sections then sit together. Covers the one-daemon-many-projects model, the SSE transport, ephemeral retention (OOS-3), and the trust hierarchy that makes it an audit rather than a monitor. |
| `docs/security-model.md` | **(1)** `## Local-Only Execution` (`:7`) amended: it currently says *"Smith runs entirely on your machine… no external API calls"*, which stays true, but a **listening loopback socket** is new and must be stated. **(2)** New section after `## Scheduler Security` (`:148`) — the closest precedent for documenting a background process — covering the four additions FR-50 names: a loopback-bound local HTTP surface, a token-gated SSE stream, a hook-originated local POST (a first for this repo), and the redaction default. |
| `README.md` | Skill table row + **four** hardcoded counts corrected, not one: `:2` (the badge), `:18`, `:56` (`### Skills (33)`) and `:192`. All four currently read `33` against **34** actual directories, so this feature both adds one and fixes a pre-existing off-by-one — final value **35**. `install.sh:131-134` already computes the count dynamically; only the README hardcodes it. |
| `CHANGELOG.md` | New `[Unreleased]` → `### Added` entry, written **LAST**, after every other file is final — features 54-59's consistent ordering rule. |

`.claude-plugin/plugin.json` needs **no** edit: `"skills": "skills/"` and
`"hooks": "hooks/"` are directory pointers, not enumerated lists.

## Phased ordering

Dependency-ordered. **The emitter leads because it is the highest-risk surface;
`phases.py` follows because it is the highest-value one. The dashboard HTML is
last.** The two adjacent-cleanup items the questions gate added (Q2's installer
`*.json` glob + pricing families, and Q7's `SMITH_HOOKS` completion + its
regression test) are sequenced as steps 6a and 13a — after the emitter and the
pure core, before the surfaces that consume them — so neither displaces the
emitter-safety-first ordering.

1. **`hooks/activity-emitter.sh` + its tests in `tests/smith-activity.test.sh`.
   FIRST, before any daemon exists.** On `PreToolUse` a bad exit blocks the
   tool call, and a non-blocking non-zero exit still puts a visible error in
   the operator's transcript — US-4 forbids both. Building it against *no*
   daemon is not a limitation, it is the point: the daemon-down path is the one
   the operator will live in most of the time, and it is testable on day one.
   SC-4 is green before anything else is written. Re-measure the
   `research.md` §Q7 figures here and record them in `quickstart.md`.
2. **`paths.py`.** `primary_repo()` (FR-28) is depended on by every reader, and
   SC-7 is a two-line test. Small, pure, no dependencies.
3. **`phases.json` + `phases.py` + `tests/activity/test_phases.py` + the FR-16
   sync test.** The highest-value piece, and pure, so it is fully testable with
   zero infrastructure. `normalize_phase_title()` and the extractor are written
   together because the sync test must import the same normalizer the resolver
   uses — if they could drift, the test would be testing the wrong thing.
   SC-1, SC-2 and SC-3 all land here, against fixtures, with no daemon.
   Sequenced before `findings.py` because findings are derived from resolved
   phase state and would otherwise have nothing to consume.
4. **`findings.py` + `tests/activity/test_findings.py`.** Also pure. SC-5 and
   SC-6. `RECONCILE_WINDOW_S` and the injected `now` make the 90 s window
   testable without sleeping.
5. **`markers.py` + `sessionlog.py`.** The two readers layers 3/4 need before
   anything can be resolved from real data. Sequenced together because
   `sessionlog.py`'s discovery precedence consumes marker `session_log:` fields
   (`workflow-summary.sh:84-135`), and landing one without the other leaves a
   reader with no source.
6. **`usage.py` + `tests/activity/test_usage.py`.** SC-11. Sequenced here
   because it is the only reader that imports `workflow_summary_lib`, and its
   contract-trap discipline should be established and tested before three more
   modules exist that might be tempted to re-parse `pricing.json`. FR-56's
   added tests for the zero-coverage functions land with it. Q3's live
   subagent sidechain parse and the `agent-<id>.meta.json` sidecar reader land
   here too — **in `usage.py`, with `hooks/workflow_summary_lib.py`
   untouched** (FR-36).
6a. **`hooks/pricing.json` families + the `install.sh` `hooks/*.json` glob +
   `tests/activity-pricing.test.sh`.** SC-17, FR-62 (Q2). Sequenced
   **immediately after step 6** and well before the installer work at step 12,
   for one reason: `usage.py`'s tests assert real USD figures, and until
   `load_pricing()` can resolve `claude-opus-5*` every one of those assertions
   is written against `None`. Doing this later means writing SC-11's
   expectations twice. **This step's first action is consulting the
   authoritative pricing source via the `claude-api` skill** — not editing the
   file. If that source cannot be reached, the family entries still land, with
   rates marked unavailable, and the step is not considered blocked.
7. **`worktrees.py` + `tests/activity/test_worktrees.py`.** SC-8. Independent
   of 5/6; sequenced after them only because its fixtures need the
   `make_repo` + `git worktree add` harness extension, which is cheaper to
   write once the flat test file already exists from step 1.
8. **`vault.py` + `sessions.py`.** The two remaining readers. Lowest-risk:
   `vault.py` is read-only counting, `sessions.py` is a subprocess parse
   against the record shape verified in `research.md` §Q8.
9. **`state.py` + `ingest.py`.** The state tree and the redaction boundary.
   `ingest.py` is sequenced with `state.py` rather than with `server.py`
   because SC-14's guarantee is "redaction happened **before** storage" — the
   two must be reviewed as one change or the guarantee is unverifiable.
10. **`server.py` + `smith-activity.sh`.** The daemon becomes real.
    SC-9, SC-10, SC-15. Sequenced after 9 so the first `curl` against
    `/api/state` returns something true rather than a stub.
11. **`statusline-tee.sh`.** SC-12, SC-13. Independent of the panels, and
    sequenced before them so the quota panel has a live feed to render.
12. **`settings/smith-settings-fragment.json` + `scripts/install.sh`.** Wire
    it up. Only now is there something to install. The `pricing.json` fix and
    the statusline capture land here.
13. **`scripts/uninstall.sh`.** Immediately after install — the two are
    reviewed as a pair, which is the only way the surgical statusline restore
    is verifiable end to end. Removal of all four `static/*` files lands here
    (Q4).
13a. **`SMITH_HOOKS` completion + `tests/uninstall-hook-coverage.test.sh` +
    the `install.sh:138` count fix.** SC-18, FR-63 (Q7). Sequenced
    immediately after step 13 because it edits the same array the previous
    step just touched, and reviewing both in one pass is the only way to see
    that `activity-emitter.sh` landed in a *complete* list rather than a
    twelfth entry in a stale one. **The array is generated from
    `ls hooks/*.sh` at this step**, never transcribed — the count stated in
    `questions.md` is context, not input. The test is written **before** the
    array is completed, so it is observed failing against the stale array
    first; a coverage test that has never been red proves nothing.
14. **`static/index.html` + `app.css` + `app.js` + `panels.js`. LAST.** Every
    datum it renders is already reachable via `/api/*` and already
    fixture-tested. Writing it against a live daemon serving real state is
    strictly faster than writing it against a moving contract, and a
    front end written first would have been rewritten three times by step 10.
15. **`docs/hooks.md` + `docs/architecture.md` + `docs/security-model.md` +
    `README.md`.** After the behavior is final, so the docs describe it rather
    than an interim draft — features 58 and 59's stated reasoning for the same
    ordering.
16. **`CHANGELOG.md`.** Last.

## Test strategy

### The CI constraint, and the pattern this feature establishes

`.github/workflows/test-install.yml:55-63`:

```yaml
      - name: Run shell tests
        run: |
          fail=0
          for t in tests/*.test.sh; do
            [ -f "$t" ] || continue
            echo "=== $t ==="
            bash "$t" || fail=1
          done
          [ "$fail" -eq 0 ] || { echo "FAIL: one or more shell tests failed"; exit 1; }
```

Flat `tests/*.test.sh` **only**. No recursion, no `find`. Today that means 40
subdirectory test files and 28 `test_*.py` files run in CI **never** —
including `tests/hooks/test_hook_chain_order.sh`, the very test this feature
must not break. `tests/install.smoke.sh` does not run either (wrong suffix).

**No existing flat test wraps a Python unit-test run.** The only
`python3 -m unittest` strings in the repo are docstrings telling a human how to
run them. So this feature **establishes** the wrapper pattern rather than
following it (FR-54), and `tests/smith-activity.test.sh` is the sole gate:

```bash
# --- Test N: Python unit suite (phases, usage, findings, worktrees) ---
if PYTHONPATH="$REPO_ROOT" python3 -m unittest discover -s "$REPO_ROOT/tests/activity" -t "$REPO_ROOT" -q >"$TMP/py.out" 2>&1; then
    assert "python unit suite" true
else
    assert "python unit suite" false
    sed -n '1,60p' "$TMP/py.out"
fi
```

`python3` is already an unconditional dependency of the flat suite
(`tests/stamp-response.test.sh:29,46,53` and `workflow-gate-redirect.test.sh:45`
all shell out to it), so this adds no new CI requirement. `-t "$REPO_ROOT"`
sets the top-level import dir so `tests/_harness.py` resolves and puts
`hooks/` on `sys.path` — reusing the mechanism `tests/test_normalized.py` and
its four siblings already use.

CI also asserts a **skill count `-ge 25`** (`:30-32`) and, after uninstall, a
`smith*` skill count of **exactly 0** (`:51-52`). `smith-activity` matches both
globs, so neither needs a CI change — satisfying SC-16's "with no CI
configuration change required".

`lint-skills.yml:45` fails the build on any `/Users/…` literal in
`skills/ hooks/ scheduler/ settings/ scripts/`. Everything this feature ships
uses `$HOME` or `"${SMITH_HOME:-$HOME/.smith}"`.

### Coverage map — every SC to its test

| SC | Where |
|---|---|
| SC-1 phase resolution across a full `smith-new` → `smith-build` fixture, incl. nested handoff and the questions gate | `test_phases.py` |
| SC-2 two interleaved concurrent workflows → exactly two records, zero cross-attribution | `test_phases.py` |
| SC-3 `phases.json` ↔ SKILL.md sync, failing on add/rename/renumber/remove | `smith-activity.test.sh` (shells to `test_phases.py`) |
| SC-4 emitter exit-0 / zero stdout / bounded, for `PreToolUse` **and** `PostToolUse` | `smith-activity.test.sh` — shell-native, no daemon |
| SC-5 one divergence finding, classified, naming workflow+phase+timestamp | `test_findings.py` |
| SC-6 skipped phase renders SKIPPED + exactly one absence finding | `test_findings.py` |
| SC-7 primary-repo resolution from inside a `/tmp` worktree | `smith-activity.test.sh` (`make_repo` + `git worktree add`) |
| SC-8 HELD / MISSING / ORPHANED, ORPHANED never an active workflow | `test_worktrees.py` + the shell fixture |
| SC-9 one daemon, two projects, two URLs | `smith-activity.test.sh` |
| SC-10 stale pidfile — absent pid **and** foreign pid — both exit 0 | `smith-activity.test.sh` |
| SC-11 token rollup exact, pricing via `load_pricing()` | `test_usage.py` |
| SC-12 no `rate_limits` → explicit unavailable, nothing else degrades | `smith-activity.test.sh` |
| SC-13 statusline wrap byte-identical; minimal default when none | `smith-activity.test.sh` |
| SC-14 no prompt/tool-input anywhere with capture unset | `smith-activity.test.sh` (canary grep) |
| SC-15 loopback-only bind; zero outbound | `smith-activity.test.sh` (socket inspection + source-level import assertion) |
| SC-16 every new test is a flat `*.test.sh` running in CI unchanged | structural |
| SC-17 `hooks/*.json` installed; `claude-opus-5*` resolves; `last_verified` present; no rate without one | `activity-pricing.test.sh` |
| SC-18 every `hooks/*.sh` appears in `SMITH_HOOKS` | `uninstall-hook-coverage.test.sh` |
| SC-19 `status` disagreement → exactly one finding; `status` absent → zero | `test_findings.py` |
| SC-20 retracted finding resolves to a visible settled state, never removed silently | `test_findings.py` + `smith-activity.test.sh` (served-HTML/JS assertion) |
| SC-21 unreadable `settings.json` → absence detection off + notice; unwired shipped hook → one divergence finding | `test_findings.py` |

### Test-design notes that are not obvious

- **SC-4 runs first and needs nothing.** No daemon, no fixtures, no git. It is
  the cheapest and most important test in the suite.
- **SC-15's "zero outbound" is asserted at the source level, not with a network
  sandbox.** The test greps `scripts/activity/*.py` for `urllib`, `http.client`,
  `ftplib`, `smtplib` and `socket.create_connection` outside `paths.py`'s probe,
  and greps the served HTML for `src`/`href` values beginning `http` or `//`.
  Deterministic, fast, and it cannot be defeated by a test environment with no
  network.
- **SC-2's fixture is the real one.** The session log fixture is built from the
  actual interleaved log observed in this repository, with both markers naming
  the same `session_log:` path. That is the case the feature exists to get
  right, and a synthetic fixture would not have the mixed-clock property
  (`research.md` §Q2) that makes it hard.
- **The `pricing.json` test asserts the trap, not just the math.**
  `test_usage.py` includes a case that passes a raw `json.load` dict to
  `match_family` and asserts it returns `None`, documenting the trap in
  executable form, plus a grep asserting no file under `scripts/activity/`
  parses `pricing.json` independently.
- **FR-56's added coverage.** `parse_parent_jsonl`, `resolve_parent_jsonl`,
  `resolve_workflow_window`, `git_files_changed` and the renderers have **zero**
  tests today, so "preserve existing behavior" has nothing to verify against.
  `test_usage.py` adds characterization tests for each **before** `usage.py`
  depends on them.
- **The `SMITH_HOOKS` test is written red first.** `uninstall-hook-coverage.
  test.sh` is authored and run against the *stale* 11-entry array before the
  array is completed, so its failure mode is observed rather than assumed. A
  coverage test that was only ever green cannot be trusted to catch the next
  hook.
- **The pricing test asserts provenance, not just resolution.** Beyond
  `match_family("claude-opus-5…") is not None`, it asserts every family
  carries `last_verified` and that no family carries a numeric rate without
  one. That is the executable form of Q2's never-invent-rates constraint: a
  fabricated rate is indistinguishable from a real one at runtime, so the
  guard has to be on the metadata.
- **Retraction is tested as a transition, not a deletion.** `test_findings.py`
  asserts the retracted finding is still present in the returned structure
  with a settled state, and `smith-activity.test.sh` greps the served
  `panels.js` for the settled-state class — because FR-59's whole content is
  that it must not be removed (§Contract drift below).
- **Dual-shell.** `smith-activity.test.sh`, `activity-emitter.sh`,
  `smith-activity.sh` and `statusline-tee.sh` are each run under **both** `bash`
  and `zsh` during implementation review, per this repo's existing convention.
  This is not ceremonial here: `/dev/tcp` does not exist under `zsh`
  (measured), which is precisely why the port probe uses `nc`/`python3`.
- **Full-suite regression.** The complete `tests/` directory is run once after
  all phases land, explicitly including a check that the two pre-existing
  failing `--describe` tests (`tests/skills/test_smith_index_describe.sh`)
  still fail in the **same** way — a changed failure signature there would
  indicate an unintended interaction. And `tests/hooks/test_hook_chain_order.sh`
  is run **manually** (CI does not reach it) to confirm the settings-fragment
  additions did not disturb the `manifest-updater.sh`-last invariant.

## Rollout notes

- **Nothing activates until the operator runs `/smith-activity`.** The hook
  entries install immediately, but every emitter path exits 0 as a silent
  no-op when `activity.port`/`activity.token` are absent — which is the state
  on every machine until the command is first run. Measured cost of that
  no-op: **~6 ms** (`research.md` §Q7). There is no launchd agent (OOS-2), no
  auto-start, and no `SessionStart` auto-open (OOS-4).
- **Two behaviors change for every existing install the moment this ships**,
  both called out because unlike the rest of the feature they are not opt-in:
  1. **The hook chain grows.** Two new `PostToolUse`-class entries with
     matcher `*`. Bounded and measured, but it is a per-tool-call cost every
     project pays whether or not it ever opens the dashboard.
  2. **`hooks/pricing.json` starts being installed and refreshed, with new
     model families.** A machine whose copy is stale (this one's is dated
     2026-04-14) or absent gets a current one. Net-positive and invisible, but
     it changes `workflow-summary.sh`'s USD output on machines where it was
     silently unavailable — USD figures will start appearing where there were
     none, which is the intended repair (Q2) and should be called out in the
     CHANGELOG entry so it does not read as a regression.
- **The statusline is the one destructive-capable surface**, and it is the
  reason FR-45/FR-46 are written as absolutes. This machine has a pre-existing
  `statusLine` (`bash ~/.claude/statusline.sh`) and Smith owns none, so the
  risk is entirely the operator's own configuration. SC-13's byte-for-byte
  assertion and §Q5's surgical restore are both non-negotiable.
- **Distributed via the standard `/smith-update` path.** `~/.claude/hooks/`,
  `~/.claude/skills/` and `~/.smith/scripts/` are all refreshed by the existing
  mechanism. **One new `/smith-update` step is needed** — a running daemon
  holds an older `server.py` in memory, so `/smith-update` must stop it and
  tell the operator to re-run `/smith-activity`. Restarting it automatically
  would be exactly the kind of surprise OOS-4 rules out.
- **Retention is ephemeral and the UI says so** (OOS-3). A daemon restart is a
  blank slate; the `hello` frame carries `retention: "ephemeral"` and the page
  renders a banner rather than a silently truncated timeline. The storage layer
  sits behind `state.py`'s boundary so a retained two-tier scheme later is a
  configuration change, not a redesign.
- **A documentation defect found while tracing FR-17, deliberately NOT fixed
  here — settled at the gate (Q8, answer A).** `skills/smith-bugfix/
  SKILL.md:101` is the only place the `create-active-workflow.sh` exit-3
  collision is documented, and its advice — *"pick a new slug (e.g., append
  `-2`) and retry"* — is wrong: the marker is keyed on **branch**, not slug
  (`create-active-workflow.sh:147`). `smith-new`, `smith-build` and
  `smith-debug` document no exit-3 handling at all. **OOS-8 now bars workflow-
  skill edits of every kind in this feature, documentation included**, because
  this feature observes those skills and editing them changes the behavior
  being measured. **Banked as BANK-030** for its own bugfix, alongside the
  Q5 UTC-normalization item (making the four workflow SKILLs write `date -u`
  in their `Subagent invoked:` blocks, which is the root-cause fix for the
  mixed-clock problem FR-58 works around).
- **`/smith-index` runs on this repo AFTER this feature merges** (Q9, answer
  A) — a post-merge follow-up, deliberately off the critical path. The user's
  condition was that the index must not reach the public repo, and that is
  **satisfied structurally**: `.gitignore:2` blanket-ignores `.smith/` and the
  file contains **zero negation (`!`) lines**, confirmed empirically by
  `git ls-files .smith/` returning 0 tracked files. `ATTCKDigital/smith` is
  public; the index stays local regardless. Value to the next feature: this
  plan's research needed four parallel passes over ~25 files for facts a
  manifest answers in one lookup, and the dashboard's own vault panel reports
  index freshness, which has nothing to show on this repo until the index
  exists.
- **An observed condition, recorded and deliberately NOT fixed.**
  `.gitignore:41-66` carries a `smith-gitignore-policy` block declaring
  `.smith/index/manifest.md`, the `.meta` describe layer, `vault/ledger/`,
  `vault/bank/`, `vault/agents/` and `vault/sessions/*.md` as "COMMITTED
  (shared with the team)". With no negation lines anywhere in the file, the
  blanket ignore at line 2 silently overrides all of it. **Consequence:
  `/smith-sync` is a permanent no-op in this repo** — it runs automatically at
  the end of every `/smith-new`, `/smith-bugfix` and `/smith-debug`, runs
  `git add .smith/`, stages nothing, and reports nothing to sync. Most likely
  deliberate (the policy block is the template for consumer projects; this
  public source repo opts out), but the override is undocumented. Out of scope
  here; recorded so the next reader does not diagnose it twice.

## Spec-plan tensions — RESOLVED, folded into the sections above

1. **"`smith-finish` cannot be keyed off a marker" (FR-15's own caveat).**
   Resolved: the premise is right and the conclusion is wrong. `smith-finish`
   does not call the helper at all — it hand-writes
   `finish-<safe-branch>.yaml` with `workflow: smith-finish`
   (`skills/smith-finish/SKILL.md:76-84`), so it **is** marker-resolvable.
   Kept in `phases.json` and in the FR-16 test. The four marker-shape
   differences are folded into `data-model.md` §4.1 and `research.md` §Q1.
2. **FR-11 signal 2 says the live `Task` event arrives BEFORE the log block;
   all four SKILL.md files say the block is written BEFORE the Agent call.**
   Resolved: the reconciliation window is **two-sided** and ordered on append
   offset, not on parsed timestamps — because the session log mixes UTC (every
   hook) with model-local wall time (every model-authored block), a 4-hour skew
   observed in this repository's own log. `research.md` §Q2. **Ratified at the
   gate (Q5, answer A), and now spec text**: FR-11 amended, FR-22 carries the
   90 s two-sided window, FR-58 bars parsed timestamps from any ordering
   decision, FR-59 requires a retracted finding to resolve visibly.
3. **FR-16's "match exactly" vs. real heading text.** Resolved: the contract is
   the **normalized** title, five rules, one shared function
   (`normalize_phase_title()`) imported by both the resolver and the test.
   `contracts/phases-json.md` §3.
4. **FR-17's nesting vs. `create-active-workflow.sh`'s collision. CORRECTED
   2026-09-22 — `research.md` §Q6's conclusion was measured and is false.**
   §Q6 concluded that `smith-build` calling the helper on the branch
   `smith-new` already registered is a "guaranteed exit 3 every time" and that
   "two concurrent markers never exist". Verified live on this branch: the call
   exits **0**, and a **second marker is written into the worktree's own
   vault** — `/private/tmp/smith-activity-dashboard/.smith/vault/
   active-workflows/60-activity-dashboard.yaml` with `workflow: smith-build`,
   while the primary repo's marker still reads `workflow: smith-new`. Root
   cause: Smith resolves "project root" two incompatible ways —
   `scripts/create-active-workflow.sh:139` uses `git rev-parse --show-toplevel`
   (the **worktree**) while `hooks/workflow-gate.sh:60` uses
   `${CLAUDE_PROJECT_DIR:-$(pwd)}` (the **primary repo**), so the collision
   check at `:158-165` examines a marker path that does not exist yet.
   **Resolved, and simpler than §Q6 proposed:** nesting is read directly from
   two real markers, correlated by `branch:` — parent in the primary vault,
   child in the worktree vault — which is exactly the dual-vault enumeration
   `data-model.md` §1 and the `markers.py` row of the NEW table already
   require. Cross-chain phase-title matching is **retained only as the
   fallback** for when a child marker is absent. A cross-chain signal at a
   phase with no declared `handoff` remains a `marker_contradiction` finding;
   the now-normal two-marker `smith-new` → `smith-build` handoff must NOT
   raise one. Two consequences bind the build: a worktree marker's
   `session_log:` is **empty** (`.smith/vault/.current-session` does not exist
   in a worktree), so every reader must tolerate it and fall back to the
   primary vault's `.current-session`; and `hooks/workflow-gate.sh` never
   reads the worktree marker at all — it is write-only state. That last item
   is **not fixed here** (OOS-8 bars workflow-skill edits and this is
   script/hook behavior with its own blast radius); it is recorded in
   `docs/architecture.md` and banked alongside BANK-030.
   `research.md` §Q6 carries an appended correction note.
5. **FR-36 "the largest new-code surface".** Resolved: it is ~65 lines,
   because the `agent-<id>.meta.json` sidecar supplies the dispatch metadata and
   the sidechain `message.usage` shape is identical to the parent's. Built now,
   not deferred — the parent transcript contains **zero** sidechain rows, so a
   deferred FR-36 means the tokens panel reads `0` for every running subagent.
   `research.md` §Q4. **Ratified at the gate (Q3, answer A)**, with one
   constraint made explicit in FR-36: it lands in `scripts/activity/usage.py`
   and `hooks/workflow_summary_lib.py` is **not** modified.
6. **A-1's "`SubagentStart` is load-bearing".** Resolved: it is not. All
   fifteen desired events are confirmed documented, and the sidecar supersedes
   `SubagentStart` regardless, demoting it to a ~1 s latency optimization.
   `research.md` §Q8, `contracts/hook-envelope.md` §3.
7. **A-2's unmeasured latency budget.** Resolved by measurement: ~10 ms live,
   ~6 ms refused, ~2 ms foreground when backgrounded against a hang. The budget
   is met by ~50×. The bound comes from `curl --max-time`, **not** from the
   repo's `TIMEOUT_BIN` idiom, which is a no-op on stock macOS.
   `research.md` §Q7.
8. **D-5's single `static/index.html` vs. the 300-line policy.** Resolved: the
   constraint is "no build step", not "one file". Four local files, three extra
   loopback GETs, zero tooling. §File Size Policy. **Ratified at the gate (Q4,
   answer A)**; D-5 amended, and install/uninstall carry all four files.
9. **`server.py` and `phases.py` would both have exceeded 300 lines.** Resolved
   by splitting both up front — `server.py` → `server`/`ingest`/`state`,
   `phases.py` → `phases`/`findings` — along responsibility boundaries, with
   `panels.js`'s next split already decided in advance. §File Size Policy.

## Questions gate (Phase 5) — resolved

The four items this plan originally deferred to the gate, and what the gate
decided. Full reasoning is in [`questions.md`](./questions.md); the nine-row
summary is in §Questions Gate Outcomes at the top of this file.

**G1 — FR-18 and FR-26 name `claude agents --json` fields that do not exist.**
Executed against the installed Claude Code v2.1.269 across 23 live records, the
union of keys is `{pid, cwd, kind, name, sessionId, startedAt, status}`.
`waitingFor`, `state` and `id` are present in **zero** records; `status`
(values `idle`/`busy`) in only 6 of 23. → **Q1, answer C.** Not the plan's
recommended A. `PermissionRequest` / `PermissionDenied` become the PRIMARY
signal, `status` is kept as **corroboration where present**, and their
disagreement is surfaced as a divergence finding rather than reconciled away.
The user's reasoning: the dual-source-plus-disagreement shape is the feature's
own audit thesis applied to itself, and the reconciler has to read both sources
anyway for liveness. **Spec effect:** FR-18 and FR-26 rewritten, **FR-57
added**. `sessions.py` never reads `waitingFor`, `state` or `id`; the poll is
scoped to liveness reconciliation; a record with no `status` produces no
finding, because absence of corroboration is not disagreement.

**G2 — the `smith-bugfix` exit-3 documentation bug.** → **Q8, answer A: file
separately.** The plan's assumption was correct. The boundary is held
deliberately and has been widened into **OOS-8**, which now bars workflow-skill
edits of *every* kind in this feature, documentation included, on the ground
that this feature observes those skills. Banked as **BANK-030**, together with
the Q5 UTC-normalization item.

**G3 — scope of the pre-existing defects this feature would inherit.** →
**Q2 answer A and Q7 answer A: fix all of them.** Wider than the plan
proposed on both counts. The installer gains a `hooks/*.json` glob (not a
single `cp`), `hooks/pricing.json` gains current model families including
`claude-opus-5*` **under the never-invent-rates constraint**, and
`SMITH_HOOKS` is completed to every shipped hook — derived from `hooks/` at
build time, locked by a flat regression test, with `install.sh:138`'s
`"Copy 9 hooks"` fixed alongside. **Spec effect:** FR-62 and FR-63 added,
SC-17 and SC-18 added. Sequenced at steps 6a and 13a so neither displaces
emitter-safety-first ordering.

**G4 — whether `/smith-index` runs on this repo.** → **Q9, answer A: after
this feature merges**, off the critical path, with the "must not reach the
public repo" condition verified structurally (`.gitignore:2` blanket-ignores
`.smith/`, zero negation lines, `git ls-files .smith/` returns 0). Recorded as
a post-merge follow-up in §Rollout notes, along with the observed
`/smith-sync`-is-a-no-op contradiction at `.gitignore:41-66`, which is
recorded and **not** fixed.

### Two further decisions the gate settled that this section did not anticipate

- **Q5** reversed FR-11's ordering assumption (the log block may precede the
  `PreToolUse` Task event, because all four SKILLs instruct it) and hardened
  the window: 90 s, **two-sided**, offset-ordered, retractable, with FR-58
  barring parsed timestamps from ordering anywhere and FR-59 requiring a
  retracted finding to resolve visibly.
- **Q6** ratified `research.md` §Q3's installed-`settings.json` expectation
  source as **FR-60**, and added its corollary as **FR-61**: a hook the repo
  fragment ships that the installed settings do not wire is its own divergence
  class, distinct from "wired but never fired". The live instance that proves
  the class is worth having is this feature's own `hooks/pricing.json` finding.

## Contract drift closed at the gate

Three statements elsewhere in this feature's artifacts contradicted the gate's
answers and have been corrected, listed here so a reviewer can confirm nothing
was left half-amended:

| Artifact | Was | Now |
|---|---|---|
| `contracts/sse-frames.md` §4.3 | *"`findings.remove` is how a retracted finding disappears… a finding that is visibly present but struck through is worse than one that is gone"* | FR-59 inverts this: retraction is an **upsert to a settled state**, never a `remove`. |
| `contracts/hook-envelope.md` §2, `contracts/sse-frames.md` §4.1 | `status` framed as absent and unused; `PermissionRequest` framed as a straight substitute | `status` is **corroboration** and its disagreement is FR-57's finding. |
| `checklists/requirements.md` | FR-18 described as *"paired with `waitingFor`"* | Rewritten to the event-derived primary + corroboration shape. |
