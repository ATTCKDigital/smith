# Contract: the hook payload envelope the emitter forwards

What Claude Code hands a hook on stdin, what the emitter does to it (nothing),
what the daemon accepts, and the redaction applied before any of it reaches the
state tree.

Every event name and field below is **CONFIRMED** against the official Claude
Code hooks reference and, where noted, against the installed v2.1.269.
`research.md` §Q8 has the verification detail and the one genuine gap
(`claude agents --json` has no `waitingFor`). **Settled at the questions gate
(`questions.md` Q1, answer C):** `PermissionRequest` / `PermissionDenied` are
the PRIMARY source for "waiting on a permission prompt" (FR-18), `claude
agents --json`'s `status` is **corroboration where present** (FR-26), and a
disagreement between the two is a divergence finding (FR-57) rather than
something the daemon reconciles away.

---

## §1 — The envelope

**Common to every hook event:**

| Field | Type | Notes |
|---|---|---|
| `session_id` | str | the primary key for `Session` |
| `prompt_id` | str | UUID of the current turn; ties `PermissionRequest` to its resolution |
| `transcript_path` | str | absolute path to the parent `.jsonl` |
| `cwd` | str | the **worktree**, not the primary repo (`data-model.md` §1) |
| `permission_mode` | str | e.g. `default` |
| `hook_event_name` | str | the event name |
| `agent_id` | str | **present only inside a subagent** |
| `agent_type` | str | **present only inside a subagent** |

**Event-specific:**

| Event | Adds |
|---|---|
| `PreToolUse` | `tool_name`, `tool_input` |
| `PostToolUse` | `tool_name`, `tool_input`, `tool_response` |
| `PostToolUseFailure` | `tool_name`, `tool_input`, error detail |
| `UserPromptSubmit` | `prompt` |
| `SessionStart` | `source` ∈ `startup` \| `resume` \| `compact` \| `clear` \| `fork` |
| `SessionEnd` | `source` ∈ `clear` \| `resume` \| `logout` \| `prompt_input_exit` \| `other` |
| `SubagentStart` / `SubagentStop` | `agent_type` |
| `ConfigChange` | `source` ∈ `user_settings` \| `project_settings`, `file_path` |
| `StopFailure` | `error_type` ∈ `rate_limit` \| `authentication_failed` \| … |

The daemon treats **every** field as optional. A missing `session_id` means the
event is counted and dropped, not an error — the ingest path's only contract to
the emitter is `204`.

---

## §2 — Wired event set

### Verification against the installed Claude Code (T051 / FR-39 / FR-43 / A-1)

**Verified 2026-09-22 against Claude Code `2.1.269`**, the build installed at
`~/.nvm/versions/node/v22.17.1/lib/node_modules/@anthropic-ai/claude-code`.
`/hooks` is an interactive slash command with no machine-readable output, so
the check was made against the shipped bundle's own hook-event enum, which is
the same list `/hooks` renders. The enum extracts verbatim as:

```
PreToolUse, PostToolUse, PostToolUseFailure, PostToolBatch, Notification,
UserPromptSubmit, UserPromptExpansion, SessionStart, SessionEnd, Stop,
StopFailure, SubagentStart, SubagentStop, PreCompact, PostCompact,
PreModelSwitch, PostModelSwitch, PermissionRequest, PermissionDenied, Setup,
TeammateIdle, TaskCreated, TaskCompleted, Elicitation, ElicitationResult,
ConfigChange, WorktreeCreate, WorktreeRemove, InstructionsLoaded, CwdChanged,
FileChanged, DirectoryAdded, MessageDisplay
```

33 events. Result, against the three tables below:

| Set | Count | Outcome |
|---|---|---|
| Primary (wired unconditionally) | 15 | **all 15 CONFIRMED present** |
| Secondary (`TaskCreated`, `TaskCompleted`, `StopFailure`, `CwdChanged`) | 4 | **all 4 CONFIRMED present** |
| Not wired | 14 | all 14 confirmed to be REAL events; the decision not to wire them is a scope choice, not an availability one |

A-1's caution that "hook event availability is UNVERIFIED for most of the
desired set" is therefore **resolved**: nothing in >2 is speculative, and no
entry had to be dropped.

**`SubagentStart` exists**, so >3's fallback is not needed today. It stays
documented and stays the implementation's posture anyway: nothing in
`scripts/activity/` reads `SubagentStart`. The resolver's FR-11 signal 2 is
`PreToolUse` with `tool_name == "Task"`, and subagent discovery is the
`agent-<id>.meta.json` sidecar. If the event were withdrawn the panel would
lose up to a second of latency and nothing else.

**Payload fields.** `session_id`, `cwd`, `tool_name`, `tool_input`,
`tool_response`, `transcript_path`, `permission_mode`, `hook_event_name`,
`prompt_id`, `agent_id` and `agent_type` all appear in the bundle's envelope
shapes, as >1 records. `tool_use_id` is additionally confirmed as a
first-class key of the tool-event hook argument shape (it appears in the
bundle's own `["tool", "tool_use_id", "agentId", "consent"]` and
`["tool", "input", "tool_use_id"]` argument lists, and in the `tool.check`
event's restore list). That matters because `resolver.permission_state()`
correlates a `PermissionRequest` to its resolution on `tool_use_id` when both
sides carry one, which is strictly more precise than FR-18's stated
`prompt_id` -- a single turn can contain several tool calls under one
`prompt_id`, and clearing on the turn id alone resolves the wrong request.

**Degradation posture.** Per-event field BINDING (which event carries which
field) could not be established from the bundle with certainty, only field
presence. Every consumer therefore treats every field as optional, exactly as
>1 already requires: `resolver.permission_state()` falls back from
`tool_use_id` to `prompt_id`; `attribution.attribute_item()` SKIPS a rule whose
input is missing rather than narrowing the candidate set to nothing; and
`markers.read_marker()` tolerates an absent or empty value on every field.
Nothing asserts a field's presence.


### Primary — wired unconditionally

| Event | Why |
|---|---|
| `SessionStart` | session lifecycle; `source: "startup"` vs `"resume"` distinguishes a rollover (`data-model.md` §4.2) |
| `SessionEnd` | session lifecycle |
| `UserPromptSubmit` | turn boundary; the "waiting on you" signal for a MANDATORY STOP gate is `Stop` with no subsequent `UserPromptSubmit` |
| `PreToolUse` (matcher `*`) | **the ground-truth spine.** `tool_name == "Task"` is FR-11 signal 2 and the subject of FR-22(a) |
| `PostToolUse` (matcher `*`) | tool completion; coalesced (FR-41) |
| `PostToolUseFailure` | `PostToolUse` fires only on success — without this, a failed tool call is invisible, and "the tool errored" is exactly the absence FR-23 renders |
| `SubagentStart` | latency optimization only — see §3 |
| `SubagentStop` | subagent completion |
| `Stop` | turn end |
| `Notification` | operator-facing events |
| `PermissionRequest` | **the PRIMARY "waiting on permission" signal** (FR-18; `research.md` §Q8). `waitingFor` does not exist and is never read |
| `PermissionDenied` | resolves a pending `PermissionRequest` |
| `PreCompact` / `PostCompact` | a compaction resets the transcript's usable window; the tokens panel must say so rather than show a discontinuity |
| `ConfigChange` | invalidates the expected-hook-set cache (FR-60, `research.md` §Q3) on a real signal instead of a poll. Load-bearing: FR-60 disables absence detection outright — with a visible UI notice — when the installed `~/.claude/settings.json` cannot be read, so a stale cache is never substituted for a guess |

### Secondary — wire if trivial, never depended on

`TaskCreated`, `TaskCompleted` (the TaskCreate tool, distinct from the Agent
tool's `Task`), `StopFailure`, `CwdChanged`. Each adds one settings entry and
one handler branch; none is load-bearing.

### Not wired

`Setup`, `UserPromptExpansion`, `PostToolBatch`, `MessageDisplay`,
`TeammateIdle`, `InstructionsLoaded`, `DirectoryAdded`, `FileChanged`,
`WorktreeCreate`, `WorktreeRemove`, `PreModelSwitch`, `PostModelSwitch`,
`Elicitation`, `ElicitationResult`. Real events, no consumer in this feature.
`MessageDisplay` in particular has a 10 s harness-lowered timeout and fires per
rendered message — wiring it would be pure cost.

### Chain-placement rule

**Every new entry is its own `{matcher, hooks:[…]}` object. The emitter is
never appended to an existing chain.**

`scripts/install-hooks.sh:6-7` and `:149-183` enforce that
`manifest-updater.sh` stays LAST in the `PostToolUse` `Write|Edit` chain, and
`tests/hooks/test_hook_chain_order.sh` is a regression test for it. The
precedent to copy is `hooks/metrics-tracker.sh`
(`settings/smith-settings-fragment.json:48-53`): its own `PostToolUse` entry,
matcher `*` — the only existing hook that already sees every tool call.

---

## §3 — `SubagentStart` is an optimization, not a dependency

A-1 called `SubagentStart` "the load-bearing one" for the live-subagent panel.
It is not, because Claude Code writes a metadata sidecar at dispatch:

```
~/.claude/projects/<slug>/<session-id>/subagents/agent-<id>.meta.json
```

```json
{"agentType":"Explore","description":"Investigate markers and workflows",
 "toolUseId":"toolu_01XcnzT6yNkhxPNPE6E5EqFk","parentAgentId":"a15f48d273d84cb99",
 "spawnDepth":2,"requestShape":"background","requestNonInteractive":true}
```

That is every field FR-27 requires (`agent_type`, dispatch description, and via
ctime the start time for elapsed), plus `parentAgentId`/`spawnDepth` for
nesting and `toolUseId` for exact correlation back to the `PreToolUse Task`
event.

So: **sidecar discovery is primary; `SubagentStart` shortens the discovery
latency from one ~1 s poll to ~7 ms.** If the event were withdrawn tomorrow the
panel would lose up to a second of responsiveness and nothing else. That is
the correct dependency posture for a tool whose premise is not trusting
self-reports.

The fallback A-1 documents — `PreToolUse` on `Task` plus sidechain detection —
remains as a third tier and is what covers the window between the tool call and
the sidecar appearing on disk.

---

## §4 — Redaction (FR-48 / SC-14)

Applied **at ingest, before the payload reaches the state tree**. The
unredacted value never exists anywhere a frame builder, an `/api/*` handler, or
the logger could reach it.

Redacted by default, i.e. with `SMITH_ACTIVITY_CAPTURE_PROMPTS` unset or not
equal to `1`:

| Field | Replacement |
|---|---|
| `prompt` | `"<redacted:N chars>"` |
| `tool_input` | `{"<redacted>": N}` where N is the serialized byte length |
| `tool_response` | `"<redacted:N bytes>"` |
| any value under a key matching `(?i)(secret\|token\|password\|api_?key\|authorization)` | `"<redacted>"` |

**Retained always**, because none of it is content: `session_id`, `prompt_id`,
`cwd`, `transcript_path`, `permission_mode`, `hook_event_name`, `tool_name`,
`agent_id`, `agent_type`, `source`, `error_type`, and the byte lengths above.

The lengths are deliberately kept: a `tool_input` of 40 KB versus 40 bytes is
a real audit signal, and the length leaks nothing.

`tool_name` is retained unconditionally and is what makes FR-22(a) work at all
— the divergence finding names a `Task` dispatch, and the dispatch is
identified by `tool_name` plus `toolUseId`, never by prompt text.

With capture enabled, `hello.capture_prompts` is `true` and the UI shows a
persistent "prompt capture is ACTIVE" indicator (FR-48's final clause).

---

## §5 — What the emitter does to the payload: nothing

The emitter **forwards stdin byte-for-byte** to `POST /ingest`. It does not
parse, filter, reshape or pretty-print it.

Three reasons, in order of weight:

1. **Safety.** Parsing is the only thing in an emitter that can fail in an
   interesting way. `hooks/file-change-logger.sh` uses `grep -o` string
   scraping and is known to mis-parse a `file_path` containing an escaped
   quote. An emitter that cannot mis-parse cannot mis-parse on `PreToolUse`.
2. **Speed.** `hooks/manifest-updater.sh:29-31` states the repo's own rule —
   *"Avoids a jq dependency on the hot path."* Forwarding avoids even the
   `grep`.
3. **Fidelity.** The daemon is the only place redaction happens, so the
   redaction rules live in exactly one file and are tested in exactly one
   place.

The daemon is therefore the sole parser, and it parses defensively: a body
that is not JSON, or exceeds 256 KiB, is counted and discarded with a `204`.

### Native `"type": "http"` — the preferred path (FR-42)

```json
{
  "type": "http",
  "url": "http://127.0.0.1:8787/ingest",
  "headers": {"Authorization": "Bearer $SMITH_ACTIVITY_TOKEN"},
  "allowedEnvVars": ["SMITH_ACTIVITY_TOKEN"],
  "timeout": 5
}
```

Zero process spawn per tool call. The endpoint receives the same JSON envelope
on the POST body, which is exactly why `/ingest` accepts the raw envelope with
no wrapper — the two paths are byte-identical to the daemon.

`timeout` is a real hook-entry field in **seconds**, and the default for
`command` and `http` hooks is **600 s**. An undeclared emitter would inherit a
ten-minute ceiling. This will be the **first `timeout` field in
`settings/smith-settings-fragment.json`** — verified absent across the whole
`settings/` directory today.

The `url` carries a port that is only known at install time, which is the one
real drawback: a daemon that later picks a different port (FR-5) leaves a
stale native entry pointing at a dead port. That is harmless — a refused
loopback connection costs ~6 ms, measured (`research.md` §Q7) — but it is why
the emitter, which reads `activity.port` live, remains the shipped fallback
rather than a legacy path.

#### The SHIPPED form (T054 / `scripts/install-activity-transport.sh`)

`settings/smith-settings-fragment.json` ships **only** the `command` form, on
all 15 primary events. The native entry is never shipped in the fragment; it is
produced at install time by rewriting a merged `command` entry in place:

```json
{
  "type": "http",
  "url": "http://127.0.0.1:<activity.port>/ingest",
  "headers": {"Authorization": "Bearer $SMITH_ACTIVITY_TOKEN"},
  "allowedEnvVars": ["SMITH_ACTIVITY_TOKEN"],
  "timeout": 5
}
```

`<activity.port>` is the literal port read from
`$SMITH_HOME/activity/activity.port` at install time. The token is **not**
baked in — `$SMITH_ACTIVITY_TOKEN` is expanded by Claude Code at fire time
under `allowedEnvVars`, so rotating the token does not require re-installing,
and `settings.json` never holds the secret.

**Three preconditions, ALL required. Any doubt → the `command` form.**

| # | Precondition | Probe |
|---|---|---|
| 1 | not opted out | `SMITH_ACTIVITY_NO_NATIVE_HTTP` ≠ `1` |
| 2 | the installed Claude Code advertises the shape | `grep -aqm1 allowedEnvVars "$(realpath "$(command -v claude)")"`, bounded by `subprocess(timeout=10)` |
| 3 | the daemon is running NOW | `activity.port` numeric **and** `activity.token` non-empty |

Precondition 2's probe is a **compiled-binary** grep, not a bundle read:
2.1.269 ships `bin/claude.exe` at ~200 MB with no greppable JS. `allowedEnvVars`
is a field that exists only on an http hook entry, so its presence is positive
evidence and its absence is treated as absence of support — never as
permission. The probe costs ~0.8 s, once, at install.

Precondition 3 **fails on a normal first install**, so the `command` form is
what almost every machine gets. That is the intended outcome. It costs 9.8 ms
of foreground time per event against a live daemon and 4.4 ms with no daemon
installed (§6), so the conservative default is very nearly free — while a
native entry aimed at a port nothing is listening on is a hook that fails on
every tool call.

The rewrite is **idempotent and reversible**: it strips every existing activity
`type: "http"` entry before deciding, so a machine that once qualified and no
longer does falls back cleanly on the next install rather than keeping a dead
port forever. The `command` entries are re-supplied by the fragment merge that
runs immediately before it.

`scripts/install.sh` never rewrites a chain, only individual entries in place,
so `manifest-updater.sh` keeps its LAST position in the `PostToolUse`
`Write|Edit` chain under both forms — asserted in `tests/smith-activity.test.sh`.

### `hooks/activity-emitter.sh` — the fallback (FR-40)

Full script in `research.md` §Q7. Its guarantees:

| Guarantee | Mechanism |
|---|---|
| exits 0 unconditionally | `set -uo pipefail` (never `-e`); every early bail is `exit 0`; trailing `exit 0` |
| writes nothing to stdout | the whole network call is `( … & ) >/dev/null 2>&1` |
| bounded by a hard timeout | `curl --max-time 2 --connect-timeout 1` |
| silent no-op when the daemon is down | port/token files absent, or `curl` absent, → `exit 0` before any network attempt |

**It does not use `timeout`/`gtimeout`.** Neither exists on a stock macOS —
verified on this machine — so the `TIMEOUT_BIN` idiom at
`hooks/context-loader.sh:117-122` and `hooks/manifest-updater.sh:122-127`
imposes no bound at all there. `curl`'s own flags are built in and were
measured to hold exactly (`rc=28` at the declared limit against a hanging
listener).

It does not use `/dev/tcp` either: that path does not exist under `zsh`, and
this repo verifies shell surfaces under both shells.

### Exit-code semantics, refined

Exit **2** is the block signal; stderr on `PreToolUse`/`PostToolUse`/
`PermissionDenied` is fed back to Claude as feedback. Other non-zero codes are
non-blocking errors that surface a `<hook name> hook error` notice in the
transcript.

So FR-40's guarantee is correct as written but for a slightly wider reason
than "non-zero blocks": a non-zero-but-not-2 exit does not block the tool call,
yet it *does* put a visible error in the operator's transcript — which US-4
forbids just as firmly as a block. Exit 0 is the only acceptable outcome, and
it is unconditional.

---

## §6 — Measured cost

**RE-MEASURED at implementation time (T055, 2026-09-22).** The planning-time
figures below the rule were wrong in an instructive way and are kept for the
contrast. Method: median of 25 runs, `time.perf_counter()` around
`subprocess.run(["bash", "hooks/activity-emitter.sh"])`; `/usr/bin/time -p`
agrees but resolves only to `real 0.00`/`0.01`. Every run `rc=0`,
`stdout_bytes=0`.

| Path | Cost |
|---|---|
| native `"type": "http"`, daemon up | no process spawn; one loopback POST |
| emitter, daemon up (`204`) | **9.8 ms** |
| emitter, daemon down (refused) | **9.7 ms** |
| emitter, daemon hanging, backgrounded | **9.8 ms** |
| emitter, no port file (daemon never installed) | **4.4 ms** — early bail, no `curl` fork |
| *floor:* `bash -c 'cat >/dev/null; exit 0'` | 4.0 ms |
| emitter, daemon hanging, foreground (not shipped) | exactly `--max-time`, `rc=28` |

**The daemon's state does not show through.** Planning predicted 10 / 6.4 / 1.8
ms across up / down / hanging; the measurement says 9.8 / 9.7 / 9.8. The
`curl` is detached into a backgrounded subshell on every path, so the hook pays
one `fork`+`exec` of `curl` (~5.4 ms over the `cat`-plus-exit floor) and
nothing downstream of it — not the connect, not the refusal, not the wedge.

This is the better guarantee than the one planning assumed, and it changes the
regression test from a threshold to a shape: **if those three figures ever
diverge from one another, the detachment broke.** A uniform rise is a slower
machine.

The sub-500 ms budget (A-2) is met by roughly 50× on the worst path. The
numbers live in `quickstart.md` Scenario 4 so a future change that regresses
them is caught by a human running one command.
