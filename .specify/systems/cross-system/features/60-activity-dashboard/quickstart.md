# Quickstart: `/smith-activity` — running the daemon and exercising every panel

Manual verification walkthroughs. These check the FULL integration that the
automated suite (`tests/smith-activity.test.sh`, see `plan.md` §Test strategy)
cannot exercise in isolation — a live daemon, a real browser, and real Smith
workflows running underneath it.

Scenarios 0-4 are the smoke path and take about five minutes. Scenarios 5-12
exercise one panel or one failure mode each and can be run individually.

---

## Prerequisites

- Smith installed (`scripts/install.sh` run at least once after this feature
  lands), so `~/.claude/skills/smith-activity/`, `~/.claude/hooks/activity-emitter.sh`,
  `~/.smith/scripts/activity/` and the merged `settings.json` hook entries all
  exist.
- `python3` (3.8+), `git`, `jq`, `curl`. All are already assumed present by the
  existing flat test suite.
- At least one Smith-initialized project (a `.smith/vault/` directory).
- A browser. `--no-open` exists for headless use (A-8).

**Two things to know before you start, because they are current reality on a
dev machine and will otherwise read as bugs:**

1. **USD shows "unavailable" until FR-62 lands, then a dollar figure.** The
   live model id is `claude-opus-5`; `hooks/pricing.json`'s newest family was
   `claude-opus-4-6*` and the installer never copied the file at all, so
   `match_family()` returned `None`. Token counts still render — that is FR-34
   working correctly (`research.md` §Q4). **Both defects are in scope**
   (`questions.md` Q2 → FR-62): once the `hooks/*.json` glob and the current
   families ship, USD resolves. If a family's authoritative rates could not be
   obtained at build time it still reads "unavailable" — deliberately, because
   a guessed rate is worse than none.
2. **"Waiting on permission" is derived PRIMARILY from `PermissionRequest` /
   `PermissionDenied`**, with `claude agents --json`'s `status` as
   corroboration **where present** (`questions.md` Q1 → FR-18/FR-26/FR-57).
   The installed Claude Code returns no `waitingFor` field at all
   (`research.md` §Q8), and `status` is present on only 6 of 23 records. The
   `degraded` badge in the header says so. When `status` IS present and
   disagrees with the event-derived state, expect a `permission_disagreement`
   divergence finding — that is FR-57 working, not a bug.
3. **A divergence finding may appear and then settle, inside 90 seconds.**
   The reconciliation window is two-sided and findings are retractable
   (`questions.md` Q5 → FR-22/FR-59). A retracted finding must transition to a
   visible settled state — if one ever silently vanishes from the panel, that
   is an FR-59 violation, not a timing artifact.
4. **Absence detection may be switched off with a notice.** Its expectation
   set comes from the installed `~/.claude/settings.json` (FR-60). If that file
   cannot be read, the findings panel says absence detection is disabled rather
   than guessing — expect the `expected-hooks:unknown` degraded token.

---

## Scenario 0 — Cold start (US-5 / SC-9)

**Given** no daemon is running — verify:

```bash
cat "${SMITH_HOME:-$HOME/.smith}/activity/activity.pid" 2>/dev/null || echo "no pidfile"
```

**When** you run, from anywhere inside a Smith project:

```
/smith-activity
```

**Then**:

1. A daemon starts. `~/.smith/activity/` now holds `activity.pid`,
   `activity.port`, `activity.token`, `activity.log`, `wrapped-statusline`.
2. It is bound to loopback **only** (FR-4/SC-15):
   ```bash
   lsof -nP -iTCP -sTCP:LISTEN -a -p "$(cat ~/.smith/activity/activity.pid)"
   ```
   Every line reads `127.0.0.1:<port>`. **Zero** lines show `*:<port>`,
   `0.0.0.0`, or a `[::]` address.
3. The token is `0600`:
   `ls -l ~/.smith/activity/activity.token` → `-rw-------`.
4. A browser opens `http://127.0.0.1:<port>/?project=<token>` and the shell
   prints that URL as its LAST stdout line, so `$(… | tail -1)` works — the
   `start-playwright-server.sh:87` convention.
5. `/smith-activity`'s own `maintenance` marker was created and then cleared
   (FR-8): `ls .smith/vault/active-workflows/` shows no leftover
   `smith-activity-*.yaml`.

**And** the identity probe answers:

```bash
curl -s "http://127.0.0.1:$(cat ~/.smith/activity/activity.port)/health" | jq .
# {"service":"smith-activity","version":"1","pid":…,"started_at":"…","projects":1}
```

Note `/health` needs no token — that is deliberate, so the shell can probe a
port it may not hold the token for (`contracts/http-surface.md` §4).

---

## Scenario 1 — Idempotence and the second project (US-5 / SC-9)

**Given** the daemon from Scenario 0 is running.

**When** you run `/smith-activity` from a **different** Smith project.

**Then**:

1. **Exactly one** daemon process:
   `pgrep -fa 'activity/server.py' | wc -l` → `1`.
2. Both projects are registered: `/api/projects` returns two entries.
3. A new tab opens against the same port, filtered to project B.
4. The project filter changes every panel **except quota**, which stays
   identical because the 5h/7d windows are account-wide (FR-3).

---

## Scenario 2 — A worktree is not a second project (US-5 / SC-7 / FR-28)

**Given** a `/tmp/smith-<slug>` worktree of project A, living entirely outside
project A's tree — e.g. this feature's own worktree.

**When** you run `/smith-activity` from **inside** that worktree.

**Then**:

1. `/api/projects` still has **one** entry for project A, keyed by its
   **primary repo** path — not the worktree path. Verify the resolution
   directly:
   ```bash
   cd /tmp/smith-<slug>
   dirname "$(git rev-parse --path-format=absolute --git-common-dir)"
   # → /Users/you/Projects/<project-a>
   ```
   `--path-format=absolute` matters: without it, the same command from inside
   the **primary** repo returns the relative string `.git`.
2. **No** second project appears for the worktree path.
3. The worktrees panel lists it, with the primary checkout marked distinctly
   and showing its own branch.

---

## Scenario 3 — Stale pidfile recovery (US-5 / SC-10 / FR-6)

Two cases, both must exit 0 and both must end with a working dashboard.

**Case A — pid absent:**

```bash
/smith-activity stop
echo 999999 > ~/.smith/activity/activity.pid   # a pid that cannot exist
/smith-activity ; echo "exit=$?"               # exit=0
```

**Case B — pid alive but foreign:**

```bash
/smith-activity stop
sleep 600 & echo $! > ~/.smith/activity/activity.pid
/smith-activity ; echo "exit=$?"               # exit=0
kill %1
```

**Then**, in both cases: the stale state is cleaned up, a daemon is running,
`/health` answers, and the command does **not** fail with "already running".

**Case C — port occupied by an unrelated process (FR-5):**

```bash
/smith-activity stop
PORT=$(cat ~/.smith/activity/activity.port)
python3 -m http.server "$PORT" --bind 127.0.0.1 & sleep 1
/smith-activity ; echo "exit=$?"               # exit=0
cat ~/.smith/activity/activity.port            # a DIFFERENT port
kill %1
```

The discriminator is `/health` returning `service == "smith-activity"`, not the
HTTP status — a plain `http.server` answers `200` on `/` and `404` on
`/health`, and both resolve to "unrelated process, pick another port".

---

## Scenario 4 — The emitter can never break a session (US-4 / SC-4 / FR-40)

**The highest-risk surface in the feature. Run this one first when reviewing.**

```bash
/smith-activity stop   # no daemon listening

PAYLOAD='{"session_id":"x","prompt_id":"p","hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"ls"},"cwd":"/tmp"}'

OUT=$(printf '%s' "$PAYLOAD" | /usr/bin/time -p bash ~/.claude/hooks/activity-emitter.sh 2>/tmp/emit.err)
echo "exit=$?"                 # 0
echo "stdout bytes=${#OUT}"    # 0
grep '^real' /tmp/emit.err     # real 0.0x
```

**Then**: `exit=0`, **zero** bytes on stdout, and a wall time far inside the
declared timeout. Repeat verbatim with `"hook_event_name":"PostToolUse"` —
SC-4 requires both to be asserted explicitly, because `PreToolUse` is the one
where a non-zero exit blocks the tool call.

**And** against a daemon that accepts the connection but never replies:

```bash
python3 - <<'PY' &
import socket
s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
s.bind(("127.0.0.1", int(open("/tmp/hangport").read()))); s.listen(64)
while True: s.accept()      # never read, never reply
PY
```

point `activity.port` at it, re-run the emitter: still `exit=0`, still zero
bytes, still bounded — because the `curl` is detached in a subshell and carries
`--max-time 2 --connect-timeout 1`.

**Reference figures RE-MEASURED on this machine during implementation (T055,
2026-09-22)**, superseding `research.md` §Q7's planning-time table. Method:
`/usr/bin/time -p` around `bash hooks/activity-emitter.sh` confirms `real 0.00`
/ `0.01` on every path (its 10 ms resolution is too coarse to separate them),
so the figures below are the median of **25 runs** timed with
`time.perf_counter()` around `subprocess.run(["bash", "hooks/activity-emitter.sh"])`.
Every run: `rc=0`, `stdout_bytes=0`.

| Path | Median foreground | Note |
|---|---|---|
| daemon up (`204`) | **9.8 ms** | |
| daemon hanging (accepts, never replies) | **9.8 ms** | |
| daemon down (connection refused) | **9.7 ms** | |
| **no port file at all** (daemon never installed) | **4.4 ms** | the early bail — no `curl` fork |
| *floor:* `bash -c 'exit 0'` | 2.7 ms | |
| *floor:* `bash -c 'cat >/dev/null; exit 0'` | 4.0 ms | |

**The three network paths are indistinguishable, and that is the result worth
reading.** `contracts/hook-envelope.md` §6 predicted 10 / 6.4 / 1.8 ms, i.e.
that the daemon's state would show through. It does not: the `curl` is
detached into a backgrounded subshell, so what the hook actually pays is one
`fork`+`exec` of `curl` and nothing downstream of it. Daemon up, daemon down
and daemon wedged all cost the same ~5.4 ms above the `cat`-plus-exit floor.

That makes the regression test a shape check, not a threshold check: **if these
three figures ever diverge from each other, the detachment broke** and the hook
has started waiting on the network. A uniform rise across all four rows is just
a slower machine.

The whole range is ~50× inside A-2's 500 ms budget, and the worst case is the
path where the daemon is *running* — the uninstalled case, which is every
machine that never runs `/smith-activity`, is the cheapest at 4.4 ms.

**Finally, the negative control that matters most:** with the daemon still
down, use Claude Code normally for a few minutes. No error notice, no blocked
tool call, no stray output, no delay. The session is indistinguishable from one
with the emitter uninstalled.

---

## Scenario 5 — The phase stepper (US-1 / SC-1 / FR-9, FR-19, FR-20)

**Given** the daemon is running and a `/smith-new` workflow is mid-flight in a
worktree.

**When** you open the dashboard.

**Then** the workflow card shows:

1. `smith-new · Phase 4 of 6 · Plan Generation`, as a stepper — **not** "a
   workflow is running".
2. Phases 0-3 `completed`, Phase 4 `current`, Phases 5-6 `remaining`, each
   visually distinct.
3. A provenance badge naming the signal (FR-19) — `subagent block`,
   `live Task event`, `inferred from artifacts`, …
4. Phase 5 (Questions Gate) rendered as a **MANDATORY STOP**, distinct from a
   working phase (FR-18).

**And** for the `phase unknown` path (FR-20/SC-1): remove or truncate the
workflow's `Subagent invoked:` blocks from the session log and restart the
daemon so it cold-starts with no event stream. The card must read
`phase unknown`, show the last known phase and its timestamp, and **never**
display a guessed or nearest-match phase name.

**And** for an unmapped workflow: hand-create a marker with
`workflow: smith-experimental`. The card renders with an empty stepper and the
note `no phase map entry`. The resolver never invents a chain.

---

## Scenario 6 — Nested handoff (US-1 / FR-17)

**Given** a `/smith-new` run has reached Phase 6 and launched `/smith-build`.

**Then** the dashboard shows the nested chain:

```
smith-new › 6/6 Update Plan, Then Build or Queue → smith-build › 3/11 Testing
```

with the **parent stepper still visible**, not replaced.

**The thing to actually verify here, because it is counter-intuitive**
(corrected 2026-09-22; `research.md` §Q6's original conclusion was measured
and is false — see its appended correction note): inspect **both** marker
directories during the build —

```bash
# the primary repo's vault
ls  <primary-repo>/.smith/vault/active-workflows/
cat <primary-repo>/.smith/vault/active-workflows/<branch>.yaml   # workflow: smith-new

# the worktree's OWN vault
ls  <worktree>/.smith/vault/active-workflows/
cat <worktree>/.smith/vault/active-workflows/<branch>.yaml       # workflow: smith-build
```

There are **exactly two** markers, one per vault. `smith-build` Phase 0 called
`create-active-workflow.sh`, which resolves its project root with
`git rev-parse --show-toplevel` (`:139`) — the **worktree** — so the collision
check looked at a path that did not exist, exited **0**, and wrote a second
marker. `hooks/workflow-gate.sh:60` meanwhile stays pinned to
`${CLAUDE_PROJECT_DIR:-$(pwd)}`, the primary repo, which is why the two vaults
diverge. **Nesting is therefore derived from the two real markers, correlated
by `branch:`**; cross-chain phase-title matching is only the fallback for when
a child marker is absent.

Note also that the worktree marker's `session_log:` line is **empty** — a
worktree has no `.smith/vault/.current-session` — so the dashboard falls back
to the primary vault's pointer. An empty `session_log:` here is correct, not a
bug.

**And** the negative case: if a signal matching another workflow's chain
appears while the parent is **not** at a phase declaring that `handoff`, a
`marker_contradiction` divergence finding is raised instead of a silent nest
(FR-22c). That is the audit product working, not a bug.

---

## Scenario 7 — Two concurrent workflows, one session log (US-3 / SC-2 / FR-14)

**This is the correctness case the whole feature is built around, and it was
observed live in this repository while the spec was being written.**

**Given** two markers naming the **same** `session_log:` path:

```bash
grep -H '^\(workflow\|branch\|worktree\|session_log\):' \
  .smith/vault/active-workflows/*.yaml
```

Real output from this repository:

```
60-activity-dashboard.yaml:workflow: smith-new
60-activity-dashboard.yaml:branch: 60-activity-dashboard
60-activity-dashboard.yaml:worktree: /tmp/smith-activity-dashboard
60-activity-dashboard.yaml:session_log: …/sessions/dennis-plucinik_ad8161_2026-09-22_145028.md
67-deterministic-questions.yaml:workflow: smith-new
67-deterministic-questions.yaml:branch: 67-deterministic-questions
67-deterministic-questions.yaml:worktree: /tmp/smith-deterministic-questions
67-deterministic-questions.yaml:session_log: …/sessions/dennis-plucinik_ad8161_2026-09-22_145028.md
```

Same file. Interleaved blocks from both workflows.

**Then** the dashboard shows **exactly two** workflow cards, and:

1. Each is at its own phase.
2. Neither stepper advances on the other's events — watch both for a full
   phase transition on one.
3. Each token rollup counts only its own attributed usage. The two totals sum
   to less than or equal to the session total; they never both contain the
   same event.
4. If the header shows a non-zero `unattributed events` count, that is by
   design — an ambiguous event is dropped, never duplicated
   (`data-model.md` §2.4 rule 4).

---

## Scenario 8 — Divergence and absence findings (US-2 / SC-5, SC-6)

**Divergence — skill logging bug (FR-22a / SC-5).** Simulate a skill that
forgot to log: dispatch a subagent via a Bash-invoked path that does **not**
append a `Subagent invoked:` block, or delete the block from the session log
within the reconciliation window.

**Then** after ~90 s exactly **one** divergence finding appears, classified
`skill logging bug`, naming the workflow, the attributed phase, and the
timestamp — with the `toolUseId` in its `observed` field so it names a specific
dispatch rather than a time range.

**And**: if the block lands late, the finding is **retracted** and disappears
(`findings.remove`), rather than remaining struck through
(`contracts/sse-frames.md` §4.3).

**Divergence — undesigned path (FR-22b).** Create a `spec.md` under a feature
directory with no preceding dispatch or skill-invocation event. A finding
appears classified `undesigned path through the workflow`.

**Absence — skipped phase (FR-23a / SC-6).** Advance a `smith-new` stream from
Phase 4 to Phase 6 with no Phase 5 signal. Phase 5 renders **SKIPPED** —
visually distinct from both `completed` and `remaining` — and exactly **one**
absence finding names it.

**Absence — hook never fired (FR-23c).** Produce tool calls in a session with
no `SessionStart` ingest (start the daemon mid-session). A finding states the
expected hook never fired. Then confirm the *negative*: remove `lint-on-save`
from `~/.claude/settings.json` entirely and verify **no** finding is raised for
it — the expected set comes from the installed settings, not from a shipped
list (`research.md` §Q3), so a deliberately-disabled hook is not a finding.

**And**: every finding is advisory. Nothing pauses, nothing is modified, the
workflow continues untouched (FR-24).

---

## Scenario 9 — Sessions and subagents (US-6 / FR-25, FR-26, FR-27)

**Then** the sessions panel shows every live session with model, uptime, cwd,
git branch, and worktree. Cross-check against the reconciler:

```bash
claude agents --json | jq -r '.[] | "\(.sessionId) \(.status // "n/a") \(.cwd)"'
```

Note what is and is not there: `pid`, `cwd`, `kind`, `name`, `sessionId`,
`startedAt`, and `status` on **some** records. No `waitingFor`, no `state`, no
`id`.

- **Dead-session reaping (FR-26):** `kill` a Claude Code process. Within one
  liveness poll (5-10 s) it disappears from the panel rather than lingering.
  This — not the permission indicator — is what the poll is for.
- **"Waiting on permission" (FR-18):** trigger a real permission prompt. The
  session flips to `waiting on permission`, sourced from `PermissionRequest`,
  visually distinct from `working`, and it flips **without waiting for the next
  poll**. If `status` happens to be present for that record and disagrees,
  check that a `permission_disagreement` finding was raised alongside
  (FR-57/SC-19).
- **Subagents (FR-27):** dispatch two Task subagents. Each shows its
  `agent_type`, its dispatch description, and elapsed time. Cross-check
  against the sidecar the panel actually reads:
  ```bash
  cat ~/.claude/projects/<slug>/<session-id>/subagents/agent-*.meta.json | jq -c .
  ```
  The `agentType` and `description` on screen must match these files exactly.

---

## Scenario 10 — Worktree inventory, including the degraded states (US-7 / SC-8)

Construct each state in a scratch repo:

```bash
R=$(mktemp -d); cd "$R"; git init -q
git config user.email t@e.com; git config user.name t
echo x > a.txt; git add -A; git commit -qm init
git worktree add -q /tmp/wt-held  -b held-branch
git worktree add -q /tmp/wt-miss  -b miss-branch
git worktree add -q /tmp/wt-orph  -b orph-branch
```

| State | Construct it by | Panel must show |
|---|---|---|
| **HELD** | a marker on `held-branch`, worktree present, branch unmerged, no signal for >10 min | `HELD`, its age, and the phase it died in |
| **MISSING** | `rm -rf /tmp/wt-miss` with its marker still present | `MISSING`, and the text that `git worktree prune` clears it |
| **ORPHANED** | merge and delete `orph-branch`, leave the marker | `ORPHANED`, labeled pending the janitor sweep — and **NOT** rendered as an active workflow |
| **primary** | the repo root itself | marked distinctly, showing its own branch |

Every worktree also shows short path, branch, base branch, ahead/behind vs
`origin/<base>`, dirty-file count, occupying session, and owning marker.

**And** confirm git is not called per frame (FR-31): watch the panel for a
minute with the process under `dtruss`/`lsof`, or simply observe that the
ahead/behind figures update on a ~3 s cadence rather than continuously.

---

## Scenario 11 — Tokens, cost, and quota (US-8 / SC-11, SC-12)

**Then** the tokens panel shows input, output, cache-write and cache-read
counts, a normalized total, and a USD estimate, for the current session and
the current workflow.

- **Live subagent usage (FR-36).** While a subagent is running, its row shows
  a **non-zero and rising** token count. This is the check that proves FR-36
  shipped: with it deferred, the row would read `0` until `SubagentStop`.
  Cross-check:
  ```bash
  wc -c ~/.claude/projects/<slug>/<session-id>/subagents/agent-<id>.jsonl
  ```
  — the file grows while the panel's number rises.
- **Unknown model (FR-34).** USD reads **"unavailable"**, never `$0.00`. On a
  current dev machine this is the *default* state, not an edge case. To see the
  other branch, temporarily add a `claude-opus-5*` family to
  `~/.claude/hooks/pricing.json` and watch USD appear.
- **Malformed JSONL (FR-33).** Append a garbage line to a transcript. The
  rollup continues; the line is skipped; nothing aborts.
- **Quota (FR-35/SC-12).** Both windows render as percentages with reset times
  (converted from epoch seconds). They are **global** — switch the project
  filter and confirm they do not change. Then simulate absence:
  ```bash
  printf '%s' '{"session_id":"x","model":{"id":"claude-opus-5"}}' \
    | curl -s -X POST --data-binary @- \
      -H "Authorization: Bearer $(cat ~/.smith/activity/activity.token)" \
      "http://127.0.0.1:$(cat ~/.smith/activity/activity.port)/statusline"
  ```
  The quota panel renders an explicit **"quota unavailable"** state and
  **nothing else on the dashboard degrades**.

---

## Scenario 12 — Statusline wrapping and redaction (US-10 / SC-13, SC-14)

**Statusline (FR-45/SC-13), over a pre-existing command.** This machine
already has one (`bash ~/.claude/statusline.sh`), so this is the real case.

```bash
jq -r '.statusLine.command' ~/.claude/settings.json   # BEFORE
# … install …
cat ~/.smith/activity/wrapped-statusline               # {"had_statusline":true,"previous":{…}}
```

Feed the same payload to the old command and to the tee and diff them:

```bash
P='{"session_id":"x","model":{"id":"claude-opus-5","display_name":"Opus"},"cwd":"/tmp"}'
diff <(printf '%s' "$P" | bash ~/.claude/statusline.sh) \
     <(printf '%s' "$P" | bash ~/.smith/scripts/activity/statusline-tee.sh)
```

**Then**: no difference — byte-for-byte identical. The tee reads stdin exactly
once, forwards a copy in the background, and delegates.

**Over no prior statusline:** with `wrapped-statusline` recording
`"had_statusline": false`, the tee prints a minimal default line — not nothing,
and not an error.

**Uninstall restore (FR-46/SC-13):** run `scripts/uninstall.sh`, **decline**
the `.bak-` restore prompt, and confirm `statusLine.command` is back to the
original. The surgical path runs before, and independently of, the wholesale
restore (`research.md` §Q5).

**Redaction (FR-48/SC-14).** With `SMITH_ACTIVITY_CAPTURE_PROMPTS` unset,
drive a canary through the ingest path and grep everywhere:

```bash
CANARY="ZZQQ-canary-$$"
printf '{"session_id":"x","prompt_id":"p","hook_event_name":"UserPromptSubmit","prompt":"%s","cwd":"/tmp"}' "$CANARY" \
  | curl -s -X POST --data-binary @- \
    -H "Authorization: Bearer $(cat ~/.smith/activity/activity.token)" \
    "http://127.0.0.1:$(cat ~/.smith/activity/activity.port)/ingest"

T=$(cat ~/.smith/activity/activity.token); P=$(cat ~/.smith/activity/activity.port)
for r in state sessions workflows usage vault; do
  curl -s "http://127.0.0.1:$P/api/$r?token=$T" | grep -c "$CANARY"
done
grep -c "$CANARY" ~/.smith/activity/activity.log
timeout 3 curl -sN "http://127.0.0.1:$P/events?token=$T" | grep -c "$CANARY"
```

**Every count must be `0`.** Then set
`SMITH_ACTIVITY_CAPTURE_PROMPTS=1`, restart, repeat: the content is captured
**and** the UI shows a persistent "prompt capture is ACTIVE" indicator.

**Network posture (FR-49/SC-15).** With a tab open and a workflow running:

```bash
lsof -nP -i -a -p "$(cat ~/.smith/activity/activity.pid)"
```

Only `127.0.0.1` LISTEN and loopback ESTABLISHED lines. **Zero** outbound
connections. And the served page references no external origin:

```bash
curl -s "http://127.0.0.1:$P/" | grep -nE '(src|href)="(https?:)?//' || echo "no external refs"
```

---

## Post-run cleanup

```bash
/smith-activity stop
rm -rf /tmp/wt-held /tmp/wt-miss /tmp/wt-orph
cd <scratch-repo> && git worktree prune
rm -rf "$R"
unset SMITH_ACTIVITY_CAPTURE_PROMPTS
```

Leave `~/.smith/activity/` in place unless you are testing uninstall — the
token is regenerated on a fresh start, which invalidates any browser tab still
holding the old one.

**Never** clean up by deleting anything under a project's `.smith/vault/`.
This feature writes nothing there (FR-44), so anything present is another
workflow's live state.
