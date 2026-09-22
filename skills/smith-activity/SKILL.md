---
name: smith-activity
description: Open the local Smith activity dashboard — one loopback daemon serving every registered project, showing live workflow phases, sessions, subagents, worktrees, token usage and divergence findings. Start, stop, restart or check the daemon, or open a new tab for the current project.
argument-hint: "[start|stop|restart|status|open] [--port N] [--no-open] [--foreground]"
---

# Smith Activity Dashboard

**Arguments:** $ARGUMENTS

A read-only audit surface over what Smith is actually doing, right now, across
every project on this machine. One daemon. Loopback only. No outbound network
of any kind.

The daemon's externally visible behaviour is specified, not described here.
Read the contracts rather than this file when you need the detail:

| Contract | Covers |
|---|---|
| `contracts/http-surface.md` | every route, the token gate, `/health`'s identity probe |
| `contracts/sse-frames.md` | the six SSE event names, coalescing, the frame schema |
| `contracts/hook-envelope.md` | what the emitter forwards, and the redaction applied at ingest |
| `data-model.md` | the `ActivityState` tree |

All four live under
`.specify/systems/cross-system/features/60-activity-dashboard/`.

---

## What it does

| Invocation | Behaviour |
|---|---|
| `/smith-activity` | Ensure a daemon is running, register **this** project, open the dashboard. The default. |
| `/smith-activity start` | Same, without implying the open step is the point. |
| `/smith-activity stop` | Stop the daemon and remove its pid/port files. |
| `/smith-activity restart` | Stop, then start. |
| `/smith-activity status` | Report running/not-running, pid, port, and the `/health` payload. |
| `/smith-activity open` | Ensure running, register, open a tab. |

| Flag | Effect |
|---|---|
| `--port N` | Preferred port. If an **unrelated** program holds it, the next free port is used — never an abort. If a **Smith daemon** holds it, that daemon is reused. |
| `--no-open` | Do everything except launch a browser. |
| `--foreground` | Run the daemon in this terminal instead of detaching. For debugging; `Ctrl-C` stops it. |

**Idempotent by construction.** A second invocation from a different project
starts no second daemon: it registers that project against the running one and
opens a new tab. One daemon serves all projects, and the dashboard presents
global totals with a per-project filter rather than a per-project silo.

**Worktrees are never a second project.** Run from inside a worktree, the
registration resolves to the primary repository, so a feature worktree and its
primary checkout share one project row.

**History is ephemeral.** The daemon's state tree lives in memory only. A
restart is a blank slate, which the dashboard announces rather than hides.

---

## Runtime state

Everything the daemon writes lives under `"${SMITH_HOME:-$HOME/.smith}"/activity/`:

| File | Purpose |
|---|---|
| `activity.pid` / `activity.port` | written **after** the socket binds, so a hook never sees a port that is not listening |
| `activity.token` | `0600`. Required on `/events` and every `/api/*` |
| `activity.log` | daemon notes, rolled over once at 5 MB |
| `projects.json` | the registered project paths, and nothing else |
| `wrapped-statusline` | the statusline command the tee delegates to |

It writes nothing inside any project. In particular it **never** writes to
`.smith/vault/active-workflows/` — a detached daemon lives outside the hook
system and outside the workflow gate's jurisdiction, so that prohibition is
enforced by its own test rather than by the gate.

---

## Privacy

Prompt text and tool inputs are **redacted at ingest, before anything is
stored**. With `SMITH_ACTIVITY_CAPTURE_PROMPTS` unset you get byte lengths and
nothing else:

```
prompt        -> "<redacted:412 chars>"
tool_input    -> {"<redacted>": 1180}
tool_response -> "<redacted:64 bytes>"
```

Values under keys matching `secret|token|password|api_key|authorization` are
replaced unconditionally, capture or no capture.

Set `SMITH_ACTIVITY_CAPTURE_PROMPTS=1` to opt in. The dashboard then shows a
persistent "prompt capture is ACTIVE" indicator — the opt-in is never silent.

---

## Marker discipline (FR-8)

This skill installs and starts things, so it holds a `maintenance`
active-workflow marker for the duration. Create it **before writing
anything**, and clear it on **every** exit path.

```bash
TS=$(date -u +"%Y-%m-%dT%H-%M-%SZ")
LABEL="activity-${TS}"
PROJECT_DIR=$(pwd)
if [ -d "$PROJECT_DIR/.smith" ]; then
    ~/.smith/scripts/create-active-workflow.sh \
      --branch "$LABEL" --workflow maintenance --slug "$LABEL" \
      --worktree "$PROJECT_DIR"
    # (Falls back to scripts/create-active-workflow.sh in repo-dev layouts.)
    MARKER_PATH="$PROJECT_DIR/.smith/vault/active-workflows/${LABEL}.yaml"
fi
```

`maintenance` is an existing `--workflow` allowlist value, reused unchanged.
`--branch "$LABEL"` is a **synthetic label naming no real git ref** —
`/smith-activity` creates no branch and no worktree; the argument exists to
satisfy the helper's required `--branch` and to give the marker a unique,
sortable filename.

Clearing, at every exit path:

```bash
CLEAR=""
for candidate in \
    "$HOME/.smith/scripts/clear-active-workflow.sh" \
    "$HOME/.claude/skills/smith/scripts/clear-active-workflow.sh" \
    "$PROJECT_DIR/.specify/scripts/bash/clear-active-workflow.sh" \
    "$PROJECT_DIR/skills/smith/scripts/clear-active-workflow.sh"; do
    [ -x "$candidate" ] && { CLEAR="$candidate"; break; }
done
[ -n "${MARKER_PATH:-}" ] && [ -f "$MARKER_PATH" ] && [ -n "$CLEAR" ] && \
    "$CLEAR" "$LABEL" 2>/dev/null || true
```

The installed location is tried first. The fallbacks matter: this repository's
own checkout has **no** `.specify/scripts/bash/`, and ships the helper at
`skills/smith/scripts/clear-active-workflow.sh` instead — so the single path
every other skill hardcodes does not resolve here.

Exit paths that must clear the marker:

- **Normal completion** — after the URL is printed.
- **The daemon failed to become ready** — report the log path and clear.
- **Any error before the URL** — clear, then report.
- **`stop` / `status`** — these write nothing, so they need no marker at all;
  if one was taken anyway, clear it.

A lingering marker is never acceptable: it silently disables the workflow gate
for every other file-modifying tool call in that project until the janitor
sweep removes it.

---

## Steps

1. **Take the marker** (above) when the invocation will write — `start`,
   `restart`, `open`, or the default. `stop` and `status` write nothing.
2. **Run the lifecycle script**, forwarding `$ARGUMENTS` unchanged. Try the
   installed copy first, then the repo-dev checkout:

   ```bash
   CLI=""
   for candidate in \
       "$HOME/.claude/skills/smith-activity/scripts/smith-activity.sh" \
       "$HOME/.smith/scripts/smith-activity.sh" \
       "$PROJECT_DIR/scripts/activity/smith-activity.sh"; do
       [ -x "$candidate" ] && { CLI="$candidate"; break; }
   done
   [ -n "$CLI" ] || { echo "smith-activity: lifecycle script not found" >&2; exit 1; }
   "$CLI" $ARGUMENTS
   ```

   It handles the port probe, the stale-pidfile recovery, the readiness wait
   and the project registration. Its **last line of stdout is the URL**.

   The repo-dev fallback is the one that resolves in this repository today:
   the script ships at `scripts/activity/smith-activity.sh` and the installer
   step that stages it under `~/.claude/skills/` has not landed yet.
3. **Report the URL** to the operator, plus the port and whether an existing
   daemon was reused.
4. **Clear the marker** (above).

---

## Degraded states are stated, never hidden

The dashboard names what it cannot see rather than rendering a zero:

| Token | Meaning |
|---|---|
| `expected-hooks:unknown` | the installed `~/.claude/settings.json` could not be read, so absence detection is **off** — never guessed |
| `pricing:missing` | no pricing table resolved, so every USD figure is unavailable rather than `$0.00` |
| `claude-agents-json:absent` | the sessions panel is hook-derived only |
| `claude-agents-json:no-status` | no corroboration for the permission indicator, which is event-derived and unaffected |

Quota windows come from the statusline payload and nothing else. When it
carries no `rate_limits`, the quota panel says "unavailable" explicitly and no
other panel degrades.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Nothing appears on the dashboard | hooks not wired to the emitter | re-run the installer; check `~/.claude/settings.json` |
| `daemon did not become ready` | bind failure or a startup exception | read `"${SMITH_HOME:-$HOME/.smith}"/activity/activity.log` |
| The port keeps moving | an unrelated program holds the preferred one | pass `--port N`, or leave it — the recorded port is reused next time |
| `403 forbidden` on `/api/*` | wrong or missing token | open the URL the command printed; it carries the token |
| A stale `activity.pid` after a crash | expected | `start` cleans it up by itself; it is never an error |
