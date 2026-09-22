# Contract: SSE frame schema

The wire format of `GET /events`. Server-Sent Events (`text/event-stream`),
not WebSockets (D-2, FR-41) — SSE is one-directional, which is exactly the
shape of a read-only audit surface, and it needs no dependency beyond
`http.server`.

---

## §1 — Stream mechanics

```http
GET /events?token=<activity.token>&project=<primary-repo-path> HTTP/1.1

HTTP/1.1 200 OK
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-store
Connection: keep-alive
X-Accel-Buffering: no
```

- `token` is REQUIRED (FR-47). Absent or wrong → `403` with
  `{"error":"forbidden"}`, identical in both cases.
- `project` is optional. It filters `state`/`delta` payloads; it **never**
  filters the `quota` block, which is account-wide (FR-3).
- One thread per connection, served by `ThreadingHTTPServer`. Each connection
  owns a bounded `queue.Queue(maxsize=64)`. A consumer that falls behind has
  its queue drained and receives one `resync` frame rather than a backlog —
  a slow tab must never apply back-pressure to the ingest path.
- A `: keepalive` comment line every 20 s so an idle stream survives any
  intermediary and a dead browser is detected.
- The daemon writes to the socket inside a `try/except (BrokenPipeError,
  ConnectionResetError)` and drops the connection silently. A closed tab is
  not an error.

**Framing.** Every frame is:

```
id: <generation>
event: <event-name>
data: <single-line JSON>

```

`data` is exactly one line — the payload is serialized with
`json.dumps(..., separators=(",", ":"))` and contains no raw newline, so the
multi-line `data:` continuation rules never come into play. The blank line
terminates the frame.

`id:` carries the state `generation`, so a browser reconnect sends
`Last-Event-ID` and the daemon can answer with `resync` rather than a replay
it cannot produce (retention is ephemeral — OOS-3).

---

## §2 — Coalescing (FR-41)

**One SSE frame per tool call is explicitly forbidden.** `PostToolUse` matcher
`*` fires on every tool; an unthrottled bridge would emit hundreds of frames a
minute.

The broadcaster is a single daemon thread:

1. Ingest handlers mutate the state tree and set a dirty flag. They never
   write to a socket.
2. The broadcaster wakes on the flag, waits `BROADCAST_DEBOUNCE_MS = 200`
   (FR-41's 150-250 ms band), bumps `generation`, builds ONE `delta` payload
   from everything that changed in that window, and fans it out.
3. If the flag is set again during the wait, the wait is **not** extended —
   the debounce is a fixed-interval leaky bucket, not a reset-on-every-event
   timer. That bounds worst-case latency at 200 ms regardless of event rate,
   where a resetting debounce under a sustained `PostToolUse` storm would
   starve the stream indefinitely.

Ceiling: **5 frames/second per connection**, whatever the tool-call rate.

---

## §3 — Event names

| `event:` | When | Payload |
|---|---|---|
| `hello` | first frame on every connection | §4.1 |
| `state` | full snapshot: after `hello`, and on `resync` | §4.2 |
| `delta` | the coalesced steady-state frame | §4.3 |
| `resync` | the daemon cannot express the change as a delta | §4.4 |
| `quota` | statusline payload ingested | §4.5 |
| `finding` | a finding is raised or retracted | §4.6 |

Six names, fixed. A client that receives an unknown `event:` ignores it — the
page is versioned with the daemon, but a stale cached tab must degrade to
"shows less" rather than to a JS exception.

---

## §4 — Payloads

### §4.1 — `hello`

```json
{
  "service": "smith-activity",
  "protocol": 1,
  "generation": 417,
  "daemon_started_at": "2026-09-22T15:18:00Z",
  "retention": "ephemeral",
  "capture_prompts": false,
  "degraded": ["claude-agents-json:no-waitingFor"]
}
```

`degraded` is a list of machine-readable capability gaps the UI must **state
rather than hide** (A-9). Known values:

| Token | Meaning |
|---|---|
| `claude-agents-json:absent` | the command is unavailable; the sessions panel is hook-derived only, and the dead-session reaper is off |
| `claude-agents-json:no-waitingFor` | the installed Claude Code returns no `waitingFor`; "waiting on permission" is derived from `PermissionRequest` / `PermissionDenied` instead (FR-18, `questions.md` Q1) |
| `claude-agents-json:no-status` | the polled records carry no `status` for this session (17 of 23 observed); FR-26's corroboration is unavailable, so no FR-57 disagreement can be computed. The indicator itself is **unaffected** — it is event-derived |
| `pricing:missing` | `load_pricing()` returned `None`; every USD figure is unavailable |
| `expected-hooks:unknown` | `~/.claude/settings.json` was unreadable; absence detection is **disabled** |

`retention: "ephemeral"` is what the UI renders as "history resets when the
daemon restarts" (OOS-3) — stated, not silently truncated.

### §4.2 — `state`

The complete state tree from `data-model.md` §2, serialized, filtered by
`?project=` except for `quota`. Identical in shape to `GET /api/state`, so the
page has exactly one renderer for both the cold-start fetch and the stream.

```json
{
  "generation": 417,
  "projects": [ … ], "sessions": [ … ], "subagents": [ … ],
  "workflows": [ … ], "worktrees": [ … ], "findings": [ … ],
  "quota": { … } | null,
  "unattributed_events": 0
}
```

`unattributed_events` is the count from `data-model.md` §2.4 rule 4 — events
the resolver declined to assign rather than guess. It is surfaced because a
rising count is itself an audit signal.

### §4.3 — `delta`

Only the collections that changed in the debounce window. Absent keys mean
"unchanged" — **not** "empty".

```json
{
  "generation": 418,
  "sessions":  {"upsert": [ … ], "remove": ["<session_id>"]},
  "subagents": {"upsert": [ … ], "remove": ["<agent_id>"]},
  "workflows": {"upsert": [ … ], "remove": ["<workflow_key>"]},
  "worktrees": {"upsert": [ … ], "remove": ["<path>"]},
  "findings":  {"upsert": [ … ], "remove": ["<finding_id>"]},
  "unattributed_events": 3
}
```

Every `upsert` entry is the **whole** entity, never a partial patch. The
client replaces by key. This costs bandwidth on loopback — where it is free —
and buys the absence of a patch-merge algorithm on both sides, which is the
kind of thing that produces a dashboard that is confidently wrong after an
hour.

A `workflows.upsert` entry carries its full `phases` array, so the stepper
re-renders atomically and a phase can never be observed half-advanced.

**Retraction is an `upsert`, never a `remove`** (FR-59, `questions.md` Q5).
When the matching block or event arrives late inside `research.md` §Q2's
90-second two-sided window, the daemon re-upserts the finding with
`retracted: true` and a settled `severity`; the client re-renders it in an
explicit resolved state. `findings.remove` is reserved for a finding whose
*subject* is gone entirely — a workflow record that no longer exists — and
MUST NOT be used to express retraction. A finding that appears and then
silently vanishes reads as a rendering glitch and destroys trust in the
divergence panel, which is the feature's primary product.

### §4.4 — `resync`

```json
{"generation": 500, "reason": "queue-overflow"}
```

`reason` ∈ `queue-overflow` | `daemon-restart` | `protocol-mismatch`. The
client responds by re-fetching `GET /api/state`. The daemon then sends a
`state` frame on the same connection; the client takes whichever arrives
first and discards the other by `generation`.

### §4.5 — `quota`

```json
{
  "generation": 419,
  "available": true,
  "five_hour":   {"used_percentage": 23.5, "resets_at": 1738425600},
  "seven_day":   {"used_percentage": 41.2, "resets_at": 1738857600},
  "spend_limit": {"used_percentage": 62.8, "resets_at": 1740787200},
  "received_at": "2026-09-22T15:40:11Z"
}
```

`resets_at` is Unix epoch **seconds**; the UI formats it. When the statusline
payload has no `rate_limits` key at all:

```json
{"generation": 419, "available": false, "received_at": "2026-09-22T15:40:11Z"}
```

The quota panel then renders an explicit "quota unavailable" state and nothing
else on the dashboard degrades (FR-35/SC-12). Sent on its own event name
because it is the one payload that ignores `?project=` entirely, and giving it
a separate name makes that impossible to get wrong in the client.

### §4.6 — `finding`

```json
{
  "generation": 420,
  "op": "raise",
  "finding": {
    "finding_id": "d3f1…",
    "kind": "divergence",
    "classification": "skill_logging_bug",
    "severity": "warn",
    "retracted": false,
    "workflow_key": "/Users/x/proj|60-activity-dashboard.yaml",
    "phase_id": "smith-new:4",
    "observed": "PreToolUse Task agent_type=general-purpose toolUseId=toolu_01Xcn…",
    "self_reported": null,
    "timestamp": "2026-09-22T15:34:20Z",
    "evidence": "no `Subagent invoked:` block within 90s in …/sessions/dennis-plucinik_ad8161_2026-09-22_145028.md"
  }
}
```

`op` ∈ `raise` | `retract`. A `retract` carries the **whole finding** with
`retracted: true` and its settled severity — it is the same entity, resolved,
not a tombstone (FR-59). Findings also appear in `state`/`delta`; the
dedicated event exists so the UI can animate a newly-raised finding, and a
newly-settled one, without diffing two snapshots.

Two further classifications the questions gate added, carried on the same
payload shape: `permission_disagreement` (FR-57 — `observed` is the
event-derived state, `self_reported` is `claude agents --json`'s `status`) and
`shipped_not_wired` (FR-61 — `observed` is the installer-staged shipped-hook
manifest entry, `self_reported` is `null`, meaning the installed
`~/.claude/settings.json` wires nothing for it).

`observed` and `self_reported` are both present because FR-21 requires the
hook-derived value to be **displayed** with the self-reported value **beside
it** — the divergence is the product, so the panel shows both sides, and a
`null` on either side is itself the point.

---

## §5 — Redaction (FR-48 / SC-14)

**Redaction happens at ingest, before the state tree — not at frame-build
time.** The unredacted value never exists anywhere the frame builder could
reach it. See `contracts/hook-envelope.md` §4 for the field list and the
replacement token.

With `SMITH_ACTIVITY_CAPTURE_PROMPTS` unset, no prompt text and no tool input
appears in any SSE frame, any `/api/*` response, the UI, or `activity.log`.
With it set to `1`, `hello.capture_prompts` is `true` and the UI shows a
persistent "prompt capture is ACTIVE" indicator.

The test for SC-14 is deliberately crude and therefore trustworthy: drive a
canary string through a `UserPromptSubmit` and a `PreToolUse` payload, then
`grep -c "<canary>"` across every `/api/*` response body, a captured `/events`
transcript, and `activity.log`. Expect `0`.
