# Contract: Daemon HTTP surface

The complete externally-visible surface of `scripts/activity/server.py`. Every
route below is served by ONE `http.server.ThreadingHTTPServer` bound to
`127.0.0.1` only (FR-4). There is no second listener, no IPv6 socket, and no
configuration path that changes the bind address.

Python floor 3.8, stdlib only (D-1). `ThreadingHTTPServer` is available from
3.7, so the floor is satisfied.

---

## §1 — Bind, transport, and token

| Property | Value | Requirement |
|---|---|---|
| Bind address | `127.0.0.1` (hardcoded constant, never a parameter) | FR-4 |
| Port | `activity.port` file contents; default 8787, `--port N` overrides | FR-5 |
| Scheme | `http` only. No TLS, ever. | Non-Goals |
| Server class | `http.server.ThreadingHTTPServer` | D-1 |
| Handler | one `BaseHTTPRequestHandler` subclass in `server.py` | — |
| Access log | suppressed (`log_message` overridden to no-op), matching every other Smith surface's quiet-by-default posture | FR-48 |

**Token.** A 32-byte `secrets.token_urlsafe(32)` value generated at first daemon
start and stored `0600` at `"${SMITH_HOME:-$HOME/.smith}"/activity/activity.token`
(FR-47). It is REQUIRED on `/events` and every `/api/*` route, supplied as the
`token` query parameter. Comparison MUST use `hmac.compare_digest`, never `==`.

Token failure response — identical for "absent" and "wrong", so the endpoint
cannot be used as an oracle:

```http
HTTP/1.1 403 Forbidden
Content-Type: application/json
Cache-Control: no-store

{"error":"forbidden"}
```

`/` and `/static/*` are NOT token-gated: the page must load in order to read the
token out of its own query string and open the SSE stream. The page itself
carries no data — every datum arrives over `/events` or `/api/*`, both gated.

---

## §2 — Route table

| Method | Path | Token | Response | Purpose |
|---|---|---|---|---|
| `GET` | `/` | no | `text/html` | `static/index.html`, the dashboard shell |
| `GET` | `/static/<name>` | no | per extension | `app.js`, `app.css`, favicon. Path is `os.path.basename()`-ed and looked up in an explicit allowlist dict — never joined against user input |
| `GET` | `/health` | no | `application/json` | Daemon identity probe. See §4 |
| `POST` | `/ingest` | header | `204 No Content` | Hook event ingest. See §3 |
| `POST` | `/statusline` | header | `204 No Content` | Statusline payload ingest (FR-35). Same envelope discipline as `/ingest` |
| `GET` | `/events` | query | `text/event-stream` | The SSE stream. See `sse-frames.md` |
| `GET` | `/api/state` | query | `application/json` | Full current state tree — the cold-start snapshot a newly-opened tab renders before its first SSE frame |
| `GET` | `/api/projects` | query | `application/json` | Registered projects |
| `GET` | `/api/workflows` | query | `application/json` | Resolved workflows with steppers and findings |
| `GET` | `/api/worktrees` | query | `application/json` | Worktree inventory incl. HELD / MISSING / ORPHANED |
| `GET` | `/api/usage` | query | `application/json` | Token rollups + quota windows |
| `GET` | `/api/vault` | query | `application/json` | Vault panel counts |
| `POST` | `/api/register` | query | `application/json` | Register a project by primary-repo path (FR-2) |

Every other method/path pair returns `404` with an empty body. There is no
route that mutates Smith state; `/api/register` writes only to
`~/.smith/activity/` (FR-7, FR-44).

All `/api/*` responses carry `Cache-Control: no-store` and
`X-Content-Type-Options: nosniff`.

`?project=<primary-repo-path>` is accepted on every `/api/*` read route as a
filter. It NEVER filters `/api/usage`'s quota block, which is account-wide
(FR-3/FR-35) and is returned unchanged under every filter.

---

## §3 — `POST /ingest`

The single endpoint both emitter paths target. Its contract is written to be
satisfiable by a native `"type": "http"` hook entry with **zero daemon-side
adaptation** — see `hook-envelope.md`.

**Request**

```http
POST /ingest HTTP/1.1
Host: 127.0.0.1:8787
Content-Type: application/json
Authorization: Bearer <activity.token>
Content-Length: <n>

<the hook payload, verbatim>
```

The token is carried in the `Authorization` header rather than the query
string because a native `"type": "http"` hook entry supplies headers (with
`$VAR` interpolation gated by `allowedEnvVars`) but has no documented way to
template a query parameter. `/events` and `/api/*` use the query parameter
because a browser `EventSource` cannot set headers. The two mechanisms are
deliberate and compared in `research.md` §Q7.

**Response**

| Condition | Status | Body |
|---|---|---|
| Accepted | `204` | empty |
| Bad/absent token | `403` | `{"error":"forbidden"}` |
| Body not JSON, or > `MAX_INGEST_BYTES` (256 KiB) | `204` | empty |
| Any daemon-side exception | `204` | empty |

`/ingest` **never returns a non-2xx status for a malformed payload.** A 4xx
would be a failure signal the emitter might act on; the emitter's contract
(FR-40) is that it acts on nothing. The daemon swallows, counts, and logs a
redacted note to `activity.log`. `403` is the sole exception and is reachable
only by a misconfiguration, not by traffic.

`Content-Length` above 256 KiB: the daemon reads and discards exactly
`Content-Length` bytes before replying, so the connection is not left
half-drained.

Redaction (FR-48) is applied **at ingest, before the frame is stored** — the
unredacted body never reaches the state tree, an SSE frame, an `/api/*`
response, or `activity.log`. See `hook-envelope.md` §4.

---

## §4 — `GET /health`

The identity probe that makes FR-5 decidable: "is the process on this port an
existing Smith activity daemon, or an unrelated program?"

```http
HTTP/1.1 200 OK
Content-Type: application/json
Cache-Control: no-store

{
  "service": "smith-activity",
  "version": "1",
  "pid": 41234,
  "started_at": "2026-09-22T15:18:00Z",
  "projects": 2
}
```

Un-gated by design: the `/smith-activity` shell command must be able to probe a
port it may not hold the token for (a daemon started under a different
`SMITH_HOME`). The response discloses no project paths, no session content, and
no token — only enough to answer the identity question.

**The probe is `service == "smith-activity"`, not the HTTP status.** Any other
program on that port either refuses the connection, returns non-JSON, or
returns JSON without that key — all three resolve to "unrelated process, pick
another port" (FR-5).

---

## §5 — `GET /api/state`

The cold-start snapshot. Shape is exactly the state tree in `data-model.md` §2,
serialized, plus:

```json
{
  "generation": 417,
  "daemon_started_at": "2026-09-22T15:18:00Z",
  "retention": "ephemeral",
  "capture_prompts": false,
  ...
}
```

`generation` is a monotone counter incremented on every coalesced broadcast. A
reconnecting `EventSource` compares its last-seen `generation` against this
one; a *lower* daemon `generation` means the daemon restarted, and the UI
renders the OOS-3 "history reset at daemon restart" banner rather than a
silently truncated timeline.

`capture_prompts` mirrors `SMITH_ACTIVITY_CAPTURE_PROMPTS` and drives the
"capture is active" indicator FR-48 requires.

---

## §6 — What the daemon MUST NOT do

- **No outbound connections of any kind** (FR-49). No telemetry, no update
  check, no CDN. Enforced structurally: `server.py` imports `http.server`,
  `socketserver` and `json`; it does NOT import `urllib.request`,
  `http.client`, `ftplib`, or `smtplib`. `tests/smith-activity.test.sh`
  asserts this by grepping the daemon's own source for that import set — a
  cheap, deterministic check that needs no network sandbox.
- **No writes to any project's `.smith/vault/`** (FR-44, US-9). All daemon
  writes are confined to `"${SMITH_HOME:-$HOME/.smith}"/activity/`.
- **No writes to `.smith/vault/active-workflows/` under any circumstance**
  (FR-44). The sole marker this feature ever creates is
  `/smith-activity`'s own, created by the SKILL's shell step via
  `create-active-workflow.sh --workflow maintenance` (FR-8) — never by the
  daemon, which is a detached process outside the hook system and outside the
  gate's jurisdiction (A-7).
- **No served asset may reference an external origin** (FR-49). `index.html`
  contains no `<script src="http...">`, no `<link href="http...">`, no
  `@import url(http...)`, and no web font. `tests/smith-activity.test.sh`
  greps the served HTML for `//` -prefixed and `http` -prefixed `src`/`href`
  attributes.
