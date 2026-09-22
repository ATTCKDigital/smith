# Research: `/smith-activity` — Local Real-Time Smith Activity Audit Dashboard

Phase 0 output. Every anchor below was established by direct file read,
direct execution against the installed Claude Code (v2.1.269), or direct
measurement on this machine — never by inference from the spec. `/smith-navigate`
was unavailable (see §0.2), so reuse detection was done by grepping the
affected paths directly.

The spec's Phase 3 author flagged eight items as judgment calls needing a
planner's decision. All eight are resolved in §Q1-§Q8 with a recommendation,
its reasoning, and the alternatives rejected. §R is the reuse inventory that
constrains the file structure in `plan.md`.

---

## §0 — Repo conditions, stated rather than rediscovered

### §0.1 — No `constitution.md` exists anywhere in this repo

Verified: no `constitution.md`, no `.specify/memory/constitution.md`. Every
prior feature's plan (54, 55, 56, 57, 58, 59) records the same absence. The
substitute conventions are the ones the skills themselves encode, and they
have a real on-disk source — `templates/constitution-additions.md:1-36`:

- **File Size Policy** (lines 1-13): 300-line soft target; 300-500 warrants a
  decomposition review; over 500 SHOULD be decomposed unless auto-generated,
  a single-purpose data file, or a test where decomposition harms readability.
- **Clean Architecture Policy** (lines 15-36): `/smith-clean-code` is named as
  "the canonical rubric". Reuse-over-duplication, single responsibility,
  intention-revealing names, guard clauses, isolated side effects.

`skills/smith-new/SKILL.md:269-274` binds the planner to it directly: *"Flag
any planned file expected to exceed 300 lines and split it up front."* That
instruction, not a constitution gate, is what `plan.md`'s File Size Policy
section answers.

### §0.2 — `.smith/index/` does not exist, so `/smith-navigate` is unavailable

`ls .smith/` in this worktree: no such directory (`.gitignore:2` excludes
`.smith/`, and the worktree has no untracked copy). Reuse detection for this
plan was therefore done by grepping `hooks/`, `scripts/`, `skills/`,
`settings/`, `tests/` and `docs/` directly.

**Running `/smith-index` on this repo would make future reuse detection
materially cheaper.** This plan's own research needed four parallel
investigation passes over ~25 files to establish facts a manifest would have
answered in one lookup — and the same cost will be paid again by feature 61.
Recommended as a follow-on chore, not as part of this feature.

### §0.3 — `setup-plan.sh` is broken for this repo, three ways

Not run. Paths were computed directly. Verified by execution:

```
$ bash skills/smith/scripts/setup-plan.sh --json
ERROR: Not on a feature branch. Current branch: 60-activity-dashboard
Feature branches should be named like: 001-feature-name
```

Three independent breakages, each sufficient on its own:

1. **`check_feature_branch` requires three digits.**
   `skills/smith/scripts/common.sh:75` — `if [[ ! "$branch" =~ ^[0-9]{3}- ]]`.
   This repo's branches are two-digit (`59-wordpress-aware-index`,
   `60-activity-dashboard`), so the guard has rejected every recent feature.
2. **The template path it copies from does not exist.**
   `setup-plan.sh:40` reads `$REPO_ROOT/.specify/templates/plan-template.md`.
   There is no `.specify/templates/` directory in this repo; templates live at
   `skills/smith/templates/plan-template.md`.
3. **It writes to the wrong layout.** `common.sh:85` —
   `get_feature_dir() { echo "$1/specs/$2"; }` — targets flat `specs/<branch>/`.
   This repo's features live under
   `.specify/systems/<system>/features/<n>-<slug>/`.

`update-agent-context.sh` was tried, as instructed, and also fails — for
reason (3), which it inherits from the same `get_feature_paths`:

```
$ bash skills/smith/scripts/update-agent-context.sh claude
ERROR: No plan.md found at /private/tmp/smith-activity-dashboard/specs/60-activity-dashboard/plan.md
```

Both are recorded in `plan.md` as a known repo-dev deviation, the way plan 59
records the missing constitution. **Fixing them is explicitly out of scope for
this feature** — it is a shared-scaffolding change with its own blast radius
across features 54-60, and bundling it here would mix an unrelated regression
risk into a feature whose highest-risk surface is already a `PreToolUse` hook.

---

## §Q1 — `smith-finish` cannot be keyed off a marker: TRUE PREMISE, WRONG CONCLUSION

**Decision: KEEP `smith-finish` in `phases.json` and in the FR-16 heading-sync
test, and resolve it from a marker after all — just not the marker the spec
assumed.**

### What it actually does

`smith-finish` **never invokes `create-active-workflow.sh`.** Step 1.5
(`skills/smith-finish/SKILL.md:76-84`) hand-writes the marker with a heredoc:

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD)
SAFE_BRANCH=$(echo "$BRANCH" | sed 's/[^a-zA-Z0-9._-]/-/g')
mkdir -p .smith/vault/active-workflows
cat > .smith/vault/active-workflows/finish-${SAFE_BRANCH}.yaml << EOF
workflow: smith-finish
feature: session-finish
branch: ${BRANCH}
started: $(date -u +"%Y-%m-%dT%H:%M:%S")
EOF
```

So the allowlist at `create-active-workflow.sh:115` is irrelevant to it — it
sidesteps the helper entirely. `workflow: smith-finish` **does** appear in a
real marker file on disk. The spec's premise ("there is no `smith-finish` in
the allowlist") is correct; its conclusion ("therefore it cannot be keyed off
a marker") does not follow.

### The four shape differences the resolver must absorb

| Property | `create-active-workflow.sh` marker | `smith-finish` marker |
|---|---|---|
| Filename | `<safe-branch>.yaml` | **`finish-<safe-branch>.yaml`** |
| Fields | 6 (`workflow, feature, branch, worktree, session_log, started`) | **4** — no `worktree:`, no `session_log:` |
| `started` format | `%Y-%m-%dT%H:%M:%SZ` (trailing `Z`) | `%Y-%m-%dT%H:%M:%S` (**no `Z`**) |
| `workflow-start` log stamp | written (`create-active-workflow.sh:209-214`) | **none** |

Consequences, all of which the resolver must handle and the plan must
prescribe:

- **Two markers can coexist for one branch** — `60-activity-dashboard.yaml`
  and `finish-60-activity-dashboard.yaml`. Marker enumeration must not assume
  one marker per branch.
- **No `worktree:` field** → the worktree cross-reference (FR-29) must treat
  the field as optional and fall back to "unknown worktree", not crash or
  classify MISSING. A missing field is not a missing worktree.
- **No `session_log:` field** → this marker contributes nothing to the
  session-log recovery precedence that `hooks/workflow-summary.sh:84-91`
  already documents. It must be *skipped* in that precedence, not treated as
  an empty-string match.
- **Timestamp parsing must tolerate both** the `Z`-suffixed and bare forms.
  `hooks/active-workflow-janitor.sh:118` already sets the tolerance
  precedent — *"Values in smith yamls are plain (no quotes), but tolerate
  wrapped"* — and the resolver should extend it to the timestamp.

### The heading-sync wrinkle (FR-16 / SC-3)

`smith-finish` is also the one mapped skill whose headings differ in **both**
level and keyword:

- `smith-new` / `smith-bugfix` / `smith-debug` / `smith-build`: `## Phase N: …`
- `smith-finish`: `### Step N: …`

The sync test's extractor must therefore be `^#{2,3} *(Phase|Step) ` — not
`^## Phase `. Two further parser requirements, both verified on disk:

1. **Fence-awareness is mandatory.** `skills/smith-finish/SKILL.md:174` and
   `:177` are `## Summary` and `## Test plan` *inside a fenced bash block*,
   inside a `gh pr create --body` heredoc. The `(Phase|Step)` filter happens
   to exclude those two, but a parser that drops the filter will pick them up.
   Track fence state.
2. **Titles must be normalized before comparison.** The real headings carry
   trailing parenthetical qualifiers and inline backticks that FR-15's seeded
   titles omit — e.g. `## Phase 0: Pre-Change Exploration (Conditional)` vs
   FR-15's `0 Pre-Change Exploration`, and
   `## Phase 3.5: Update `.meta` Descriptions for Touched Methods` vs
   `3.5 Update .meta Descriptions`. The contract is defined in
   `contracts/phases-json.md` §3: strip backticks, strip one trailing
   `(...)` group, collapse whitespace, then compare case-sensitively.

**Alternatives rejected.**

- *Drop `smith-finish` from `phases.json`.* Rejected: it is the workflow that
  performs the commit/push/merge an operator most wants to see mid-flight, and
  the marker exists. Dropping it also drops the sync test's coverage of the
  `### Step N:` heading dialect, which is exactly the dialect most likely to
  drift unnoticed.
- *Resolve it from its skill-invocation event only (FR-11 signal 3).* Rejected
  as the *primary* signal because skill-event entries are model-authored prose
  (see §Q2) and `smith-finish` has no documented "log at these points" list at
  all — unlike the four workflow skills, which each enumerate 6 logging
  points. The marker is the stronger signal. The skill-invocation event is
  retained as a **secondary** signal for the case where Step 1.5 was skipped
  (the SKILL explicitly permits skipping it when nothing will be written —
  `skills/smith-finish/SKILL.md:73`).

---

## §Q2 — Reconciliation window

**Decision: 90 seconds, measured on *append order within the session log
file*, with the parsed `[HH:MM:SS]` used only as a tiebreak and never as a
cross-source clock.**

### The finding that drives this: the session log mixes two clocks

Every **hook** writes UTC:

| Writer | Clock |
|---|---|
| `hooks/file-change-logger.sh:39` | `date -u +"%H:%M:%S"` |
| `hooks/metrics-tracker.sh:98` | `datetime.now(timezone.utc)` |
| `hooks/session-start-logger.sh:43-46` | `date -u` |
| `hooks/subagent-vault-writeback.sh:174` | `datetime.now(timezone.utc)` |
| `scripts/create-active-workflow.sh:209` | `date -u +"%H:%M:%S"` |

Every **model-authored** block writes whatever the model types. Observed live
in this repository's own session log during this workflow
(`.smith/vault/sessions/dennis-plucinik_ad8161_2026-09-22_145028.md`):

```
### [11:34:20] Subagent invoked: Phase 4 Plan Generation — smith-activity audit dashboard
...
- `[15:37:34]` **Bash** in:268 out:165 total:433 (...)
```

Those two lines are **seconds apart in real time**. `11:34:20` is local (EDT,
UTC-4); `15:37:34` is UTC. A four-hour apparent skew, in one file, between two
lines the resolver must correlate. A reconciliation window that subtracts one
parsed `[HH:MM:SS]` from another across these two sources is not merely
imprecise — it is wrong by the operator's UTC offset, which varies by machine
and by daylight saving.

### The second finding: the block is written BEFORE the dispatch, not after

FR-11 signal 2 states that live `PreToolUse Task` events "arrive BEFORE the
skill writes its log block". The skill prose says the opposite. All four
workflow skills carry the identical instruction
(`skills/smith-new/SKILL.md:43`, `smith-bugfix:43`, `smith-debug:42`,
`smith-build:43`):

> **Immediately before every Agent tool call in this workflow, append a block
> to the session log.**

So the intended order is: `cat >>` the block (a Bash tool call) → *then* the
Agent tool call → *then* `PreToolUse` on `Task` fires. The divergence FR-22(a)
detects is therefore "a `Task` dispatch with no block **preceding** it", not
"no block following it". The window must be **two-sided**, because the
instruction is prose and a model may append after the fact.

### The recommendation

- **Ordering basis: byte offset in the session log**, paired with the ingest
  sequence number of the hook event. Both are monotone within their own
  source; the resolver correlates on (workflow attribution, ordinal) rather
  than on wall-clock arithmetic.
- **Window: 90 seconds of daemon wall-clock**, applied from the moment the
  `PreToolUse Task` event is ingested. If no unmatched `Subagent invoked:`
  block has appeared in that workflow's attributed slice of the session log
  within 90 s — either before the dispatch or after it — the dispatch is
  reported as a divergence finding (FR-22a).
- **Findings are retractable.** If the block lands at 95 s, the finding is
  withdrawn on the next broadcast and the stepper reconciles. FR-24 makes
  findings advisory, so a retracted finding costs the operator nothing; a
  false positive that *cannot* be retracted would poison the panel.

### Why 90 s and not less

Measured against this very session: the gap between a `Subagent invoked:`
block landing and the dispatched agent's first transcript line is under a
second when the skill behaves. The window is not sized for the happy path — it
is sized for the **unhappy-but-innocent** path:

- The session log is append-target for ~19 hook invocations plus every
  model-authored block; a busy `PostToolUse *` stretch can interleave hundreds
  of lines between the block and the dispatch.
- A `SessionStart` rollover can repoint `.current-session` at a fresh file
  mid-workflow (`hooks/workflow-summary.sh:84-91` documents the three-tier
  recovery this forces). The resolver must re-resolve the log and re-scan
  before it can honestly say a block is absent.
- `stat`-based polling is ~1 s granular (FR-38), and git refresh is debounced
  at ~3 s (FR-31).

30 s would fire on every long-running dispatch during a rollover. 5 minutes
would make the finding useless — the operator would have moved on. 90 s is
roughly 30× the slowest polling interval in the system and comfortably
survives a rollover.

**It is a named constant, not a literal**, and lives in `phases.py` as
`RECONCILE_WINDOW_S = 90` so the fixture tests can shorten it without
sleeping.

**Alternatives rejected.** *Normalize the model-written local time to UTC by
detecting the machine's offset.* Rejected: the offset that matters is the one
in effect **when the model wrote the line**, which is unrecoverable, and a
session spanning a DST boundary would be silently wrong. *Compare only
same-source timestamps.* This is in fact what the recommendation does — it is
rejected only as a *complete* answer, because FR-22(a) is inherently
cross-source.

---

## §Q3 — Source of the "expected hook set" for absence detection

**Decision: parse the INSTALLED `~/.claude/settings.json` at daemon start and
on `ConfigChange`, intersected with a small shipped applicability table.**

### Why the installed settings, and not the fragment

`settings/smith-settings-fragment.json` describes what Smith *ships*. The
operator's `~/.claude/settings.json` describes what is actually *wired*. They
differ in practice and are *supposed* to — `docs/hooks.md:5` tells the
operator outright: *"To disable any hook, remove its entry from
`~/.claude/settings.json`."*

An absence finding sourced from the fragment would therefore fire
"`lint-on-save` never fired" at an operator who deliberately removed
`lint-on-save`. That is a false positive generated by the audit tool's own
configuration drift — the single worst failure mode for a tool whose product
is findings.

Verified on this machine: `~/.claude/settings.json` wires 6 events / 13
entries / 19 commands, and every entry is `"type": "command"` with **no
`timeout` field anywhere**. That matches the fragment today, which is exactly
why a static list would look correct in testing and be wrong in the field.

### The applicability table

Presence in settings is necessary but not sufficient: "`SubagentStop` never
fired" is only a finding for a session that actually dispatched a subagent.
The daemon therefore ships a small table keyed by event name giving the
precondition that makes absence meaningful:

| Event | Absence is a finding when… |
|---|---|
| `SessionStart` | the session produced any other ingested event |
| `UserPromptSubmit` | the session produced any `PreToolUse` |
| `PreToolUse` | a `PostToolUse` was seen for the same `tool_name` |
| `PostToolUse` | a `PreToolUse` was seen and the tool did not error |
| `SubagentStop` | a `PreToolUse` on `Task` was seen for that session |
| `Stop` | the session is no longer in `claude agents --json` |

This table lives in `phases.py` as a module-level constant — data, not
branching logic — so it is unit-testable without a settings file and greppable
in one place. It is roughly 10 lines; it does not warrant its own JSON file
the way `phases.json` does, because unlike the phase chains it is not expected
to change when a SKILL.md is edited.

### Mechanism

`server.py` reads `~/.claude/settings.json` (and `.claude/settings.json` /
`.claude/settings.local.json` under each registered project, if present) with
`json.load` inside a `try/except`, extracts `{event: [commands]}`, and caches
it. `ConfigChange` is a confirmed hook event (§Q8) carrying `source` and
`file_path`, so the cache invalidates on a real signal rather than on a poll.
When the file is unreadable or unparseable, absence detection is **disabled
entirely** and the findings panel says so — it does not fall back to a guess.

**Alternatives rejected.** *A static list shipped with the daemon.* Rejected
above — drifts against the operator's own config and produces
un-actionable findings. *Derive from `settings/smith-settings-fragment.json`.*
Same defect, plus it requires the daemon to locate the repo checkout, which it
has no reason to know about at runtime (it is installed to `~/.claude/` and
`~/.smith/`). *Ask Claude Code via `/hooks`.* `/hooks` is an interactive TUI
browser (§Q8), not a machine-readable command; there is no `--json`.

---

## §Q4 — Live subagent token usage (FR-36)

**Decision: BUILD IT NOW. It is far smaller than the spec assumed, because
Claude Code ships a per-agent metadata sidecar nobody in this repo is using.**

### The discovery

`~/.claude/projects/<slug>/<session-id>/subagents/` contains **two** files per
dispatched agent, not one:

```
agent-a4e8cbb1161fec729.jsonl        345988 bytes
agent-a4e8cbb1161fec729.meta.json       226 bytes
```

The `.meta.json` sidecar, read verbatim from this session:

```json
{"agentType":"Explore","description":"Investigate markers and workflows",
 "toolUseId":"toolu_01XcnzT6yNkhxPNPE6E5EqFk","parentAgentId":"a15f48d273d84cb99",
 "spawnDepth":2,"requestShape":"background","requestNonInteractive":true}
```

and a second, with a `model` key present:

```json
{"agentType":"Explore","description":"Hook chain and gate audit",
 "toolUseId":"toolu_01Eqh9eWY8a3VAaH5dmgqLRa","spawnDepth":1,
 "requestShape":"foreground","requestNonInteractive":true,"model":"haiku"}
```

That is a ~200-byte file carrying **exactly** what FR-27 requires — `agentType`
(FR-27's `agent_type`), `description` (FR-27's dispatch description), and via
the file's own mtime/ctime the start time for elapsed — plus `parentAgentId`
and `spawnDepth`, which give the nesting FR-17 needs for the *subagent* tree
for free.

### Why the token half is also cheap

An assistant line inside `agent-<id>.jsonl`, read verbatim:

```json
{"agentId":"a4e8cbb1161fec729","isSidechain":true,"type":"assistant",
 "cwd":"/private/tmp/smith-activity-dashboard","gitBranch":"main",
 "message":{"model":"claude-opus-5","usage":{"input_tokens":2,
 "cache_creation_input_tokens":13755,"cache_read_input_tokens":4155,
 "output_tokens":8,...}}}
```

The `message.usage` shape is **identical** to the parent transcript's.
`parse_parent_jsonl` (`hooks/workflow_summary_lib.py:157`) already sums exactly
these four keys; it skips these rows only because of an explicit two-line
guard at `:185-188`:

```python
if entry.get("type") != "assistant":
    continue
if entry.get("isSidechain"):
    continue
```

So FR-36's "largest new-code surface" is, concretely: **the same loop with the
`isSidechain` guard inverted, over a different file.** Not a new parser.

### Why it cannot be deferred

The parent transcript contains **zero** sidechain rows —
`grep -c '"isSidechain":true' <parent>.jsonl` → `0` over 360 lines. Claude Code
writes subagent turns *only* to the sidecar files. And
`workflow_summary_lib.parse_subagent_blocks` (`:320`) derives subagent usage
from **session-log markdown blocks** written by `subagent-vault-writeback.sh`
at `SubagentStop` — i.e. only after the agent finishes.

Therefore: with FR-36 deferred, the tokens panel shows **zero** for every
running subagent and only catches up at `SubagentStop`. For a `/smith-build`
run whose Phase 2 subagent runs for twenty minutes, the panel would read `0`
for twenty minutes and then jump. That is not a degraded live view — it is a
wrong one, in a tool whose entire premise (spec Summary) is that confidently
wrong is worse than absent.

### Shape

A new `scripts/activity/usage.py` with:

- `iter_agent_meta(session_dir) -> list[AgentMeta]` — glob `*.meta.json`,
  `json.load` each in a `try/except`, skip unreadable. ~25 lines.
- `sum_agent_usage(jsonl_path, since_offset) -> (usage, model, new_offset)` —
  incremental tail from a remembered byte offset so a 500 KB file is not
  re-read every second. Malformed lines skipped, matching
  `parse_parent_jsonl`'s existing tolerance (FR-33/FR-36). ~40 lines.
- Pricing resolved **only** through `load_pricing()` (FR-33's contract trap).

Its tests are FR-56's required additions: `parse_parent_jsonl`,
`resolve_parent_jsonl`, `resolve_workflow_window`, `git_files_changed` and the
renderers have **zero** coverage today, so "preserve existing behavior" has
nothing to verify against.

### A live pricing finding that lands on FR-34

The model id in this session's transcripts is **`claude-opus-5`**.
`hooks/pricing.json` contains nine families, the newest being
`claude-opus-4-6*`. There is **no `claude-opus-5*` entry**, so
`match_family("claude-opus-5", pricing)` returns `None` right now, on this
machine, for every session.

FR-34's "unknown model id" edge case is therefore not an edge case — it is the
**current default path**. The "counts render, USD renders unavailable, never
`$0.00`" behavior is the primary rendering, and its test is a
must-pass, not a corner case.

Related, and worth one line in `install.sh`: **`hooks/pricing.json` is not
installed.** `scripts/install.sh:195` globs `hooks/*.sh` and `:203` globs
`hooks/*.py`; nothing copies `*.json`. The copy at
`~/.claude/hooks/pricing.json` on this machine is dated 2026-04-14 — left by
an older installer and never refreshed by `/smith-update` since. A clean
install on a new machine gets **no** pricing file at all, `load_pricing()`
returns `None`, and every USD figure in `workflow-summary.sh` is already
silently unavailable. Fixing it is one `cp` line and is folded into this
feature's `install.sh` change, since this feature is the second consumer of
that file and would otherwise inherit the same silent failure.

---

## §Q5 — Uninstall statusline restore (FR-46)

**Decision: a surgical, jq-based, idempotent restore keyed off the sidecar file
the installer writes — `"${SMITH_HOME:-$HOME/.smith}"/activity/wrapped-statusline`
— run BEFORE the existing wholesale `.bak-` restore, and tolerant of that
restore also firing.**

### Why the existing mechanism cannot be relied on

`scripts/uninstall.sh:126-137` is the entire settings cleanup:

```bash
LATEST_BACKUP=$(ls -1t "$CLAUDE_SETTINGS".bak-* 2>/dev/null | head -1 || true)
if [ -n "$LATEST_BACKUP" ]; then
    if prompt_yn "Restore settings.json from $LATEST_BACKUP?" y; then
        cp "$LATEST_BACKUP" "$CLAUDE_SETTINGS"
```

Three reasons it is insufficient:

1. **It is prompt-gated and declinable** (line 129). On "no", the statusline
   tee stays wired and the operator's own statusline stays clobbered.
2. **Backups are pruned to 3** (`install.sh:155`,
   `BACKUP_KEEP="${SMITH_BACKUP_KEEP:-3}"`, and the retention bound landed in
   commit ed4b113). Three `/smith-update` runs after installing this feature,
   the pre-feature backup is gone.
3. **It is wholesale**, so it also reverts every unrelated settings edit the
   operator made after install. Relying on it to fix *our* key means
   destroying *their* keys.

### Mechanism

**At install**, `install.sh` reads the current `statusLine` value and writes it
verbatim as JSON to `~/.smith/activity/wrapped-statusline`, then sets
`statusLine` to the tee. Two cases, both recorded explicitly so uninstall can
tell them apart:

```json
{"had_statusline": true,  "previous": {"type":"command","command":"bash /Users/x/.claude/statusline.sh"}}
{"had_statusline": false, "previous": null}
```

Live confirmation that case 1 is the real case on this machine:
`~/.claude/settings.json` already has
`"statusLine": {"type":"command","command":"bash /Users/dennisplucinik/.claude/statusline.sh"}`.
FR-45's risk is not hypothetical — the operator has a statusline today, and
Smith owns none.

**At uninstall**, a new block inserted at `uninstall.sh:124` (before the
`.bak-` block at 126):

- `had_statusline: true` → `jq '.statusLine = $prev'` writes the stored object
  back. Same write-guard shape as `install.sh:309-318`: write to a tempfile,
  `jq empty` it, `mv` only on success.
- `had_statusline: false` → `jq 'del(.statusLine)'`.
- Sidecar missing or unparseable → leave `statusLine` untouched and `warn`,
  matching `uninstall.sh:136`'s existing "no backup found" posture. Never
  guess.

The restore is **idempotent and order-independent**: it compares the current
`statusLine.command` against the tee's path first and no-ops if the tee is not
installed, so running it before *or* after the wholesale `.bak-` restore is
safe.

### Two adjacent uninstall gaps this feature must also close

- **`uninstall.sh:85-91`'s `SMITH_HOOKS` array is hand-maintained and already
  stale** — it lists 11 of the 20 `.sh` files that ship. `activity-emitter.sh`
  must be added, or it is orphaned in `~/.claude/hooks/` after uninstall.
  (The eight already-orphaned hooks are noted here as a pre-existing defect;
  fixing them is not this feature's job, but adding a ninth would be.)
- **There is no `rm -rf "$SMITH_HOME/activity"`.** `uninstall.sh` removes
  `$SMITH_HOME/scripts/smith-index` (117) and `$SMITH_HOME/scheduler` (122)
  by name; there is no blanket sweep. A new block is needed, and it must stop
  the daemon first — the LaunchAgent teardown at `uninstall.sh:59-66` is the
  closest precedent for "stop the long-running thing before deleting its
  files".

**Alternatives rejected.** *Store the previous command inside settings.json
under a Smith-owned key.* Rejected: it pollutes the operator's settings with
Smith bookkeeping, and the wholesale `.bak-` restore would delete the
bookkeeping and the tee together in the one case where they must be handled
separately. *Refuse to install the tee when a statusline already exists.*
Rejected: on this machine that means FR-35 never works for the operator who
asked for the feature.

---

## §Q6 — Nesting derivation (FR-17)

**Decision: nesting is derived from ONE marker plus the observed event stream.
It CANNOT be derived from two concurrent markers, because the second marker is
never created.**

### The collision, traced end to end

`skills/smith-build/SKILL.md:60-70`, Phase 0 step 0:

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD)
SLUG=$(echo "$BRANCH" | sed 's/^[0-9]*-//')
~/.smith/scripts/create-active-workflow.sh \
  --branch "$BRANCH" --workflow smith-build --slug "$SLUG" --worktree "$(pwd)"
```

`skills/smith-new/SKILL.md:102-106` already registered `--workflow smith-new`
on that **same** branch in its Phase 1. The marker path is keyed on the branch
(`create-active-workflow.sh:147-149`), so both resolve to the same file. The
collision check, `create-active-workflow.sh:158-165`:

```bash
if [ -f "$MARKER_PATH" ]; then
    existing_workflow=$(grep -E '^workflow: ' "$MARKER_PATH" | head -1 | sed 's/^workflow: //')
    if [ -n "$existing_workflow" ] && [ "$existing_workflow" != "$WORKFLOW" ]; then
        err "collision: ..."
        exit 3
    fi
fi
```

`smith-new` ≠ `smith-build` → **exit 3, guaranteed**, every single time
`/smith-build` runs under `/smith-new`. And `smith-new` does not clear its
marker before handing off — `skills/smith-new/SKILL.md:108` says *"Clear this
marker at the end of Phase 6 (after merge)"*, and the clear is step 9, after
the build returns.

**Net effect: for the entire eleven-phase `smith-build` run, the only marker on
disk reads `workflow: smith-new`.** No second `workflow-start` stamp is
written either (`create-active-workflow.sh:207` is past the `exit 3`).

Only a standalone `/smith-build` — invoked directly on a branch whose marker
was already cleared, i.e. the manual-recovery path — ever writes
`workflow: smith-build`.

### The second problem: the handoff may produce no event at all

`skills/smith-new/SKILL.md:462-465` is the entire handoff:

> 4. **Launch `/smith-build`** in the worktree to execute the entire
>    autonomous phase:
>    - Pass `WORKTREE_PATH` and the feature directory path as context
>    - This runs as a subagent chain (see smith-build skill)

There is no Skill-tool call and no Agent-tool call written out — no
`subagent_type`, no model, no prompt template. The text is self-contradictory:
"Launch `/smith-build`" reads as a skill invocation; "runs as a subagent chain"
reads as an Agent spawn. **Whether a skill-invocation event or a
`PreToolUse Task` event appears at this boundary is model-dependent.**

### The derivation that actually works

Child-workflow detection is **phase-title matching against the event stream**,
scoped by the parent marker:

1. The marker gives the parent workflow type and the branch/worktree that
   scopes attribution (FR-14).
2. Every attributed signal — `Subagent invoked:` description, skill-event
   heading, artifact appearance — is matched against `phases.json` **for all
   mapped workflows**, not only the marker's.
3. A signal that matches a *different* workflow's chain, at a point where the
   parent is at a phase declared as a **handoff phase** in `phases.json`,
   opens a nested child record. `smith-new` Phase 6 and `smith-debug` Phase 6
   carry `"handoff": ["smith-build"]` and `"handoff": ["smith-bugfix"]`
   respectively.
4. The parent stepper stays visible and pinned at its handoff phase (FR-17's
   explicit "rather than being replaced"). The child renders beneath it.
5. **A signal matching another workflow's chain while the parent is NOT at a
   declared handoff phase is a divergence finding**, not a silent nest —
   FR-22(c), "a marker whose declared workflow contradicts the observed event
   sequence". This is the audit product working as designed, and it is
   precisely the class of bug (a workflow entering an undesigned path) the
   operator built this tool to find.

Disambiguation is tractable because the five chains' phase titles are
near-disjoint. The one genuine collision is `smith-bugfix` 3.5 and
`smith-debug` 5.5, which share the title *"Update `.meta` Descriptions for
Touched Methods"*. `phases.json` therefore carries per-phase `match` patterns
(FR-15) that include the workflow name for ambiguous titles, and
`tests/smith-activity.test.sh` asserts that no two phases in different chains
share an identical `match` pattern.

### A documentation defect found while tracing this

`skills/smith-bugfix/SKILL.md:101` is the **only** place the exit-3 path is
documented, and its advice is wrong:

> The helper exits 3 if a marker already exists for this branch under a
> different workflow type — pick a new slug (e.g., append `-2`) and retry.

The marker is keyed on **branch**, not slug (`create-active-workflow.sh:147`).
Changing the slug changes nothing. `smith-new`, `smith-build` and `smith-debug`
document no exit-3 handling at all. This is a real, separate bug in the
workflow skills. **It is NOT fixed by this feature** — OOS-1 keeps this
feature out of the workflow skills entirely, and changing marker semantics
mid-flight would alter the very behavior the dashboard exists to observe. It
is recorded here, surfaced in `plan.md`'s Rollout notes, and belongs in the
questions gate as a follow-on.

For contrast, `smith-debug` sidesteps the collision correctly by registering a
**synthetic branch** (`skills/smith-debug/SKILL.md:96-104`,
`--branch "debug-${SLUG}"`), and `/smith-audit` does the same
(`skills/smith-audit/SKILL.md:107`: *"a synthetic label naming no real git
ref"*). That is the precedent `/smith-activity`'s own `maintenance` marker
(FR-8) follows.

### CORRECTION NOTE — appended 2026-09-22, after empirical verification

> **Everything above this heading is the original analysis and is left
> unedited on purpose.** It is a findings record; rewriting it would destroy
> the evidence of how the mistake was made, which is the more useful half of
> the record. This note states what turned out to be false, and why.

**The headline conclusion is wrong.** §Q6 concluded that the marker collision
"guarantees exit 3 every single time" and that, in consequence, "two
concurrent markers never exist". Both were verified false on 2026-09-22, by
running `/smith-build` under `/smith-new` on branch `60-activity-dashboard`
and then looking at the disk:

| §Q6 predicted | What actually happened |
|---|---|
| `create-active-workflow.sh` exits **3** | It exited **0** |
| One marker exists, reading `workflow: smith-new` | **Two** markers exist |
| No `workflow-start` stamp is written for the build | One was written, into the worktree's vault |

Both markers name the same `branch: 60-activity-dashboard`. The one in the
**primary repo's** vault reads `workflow: smith-new`; the one in the
**worktree's** vault reads `workflow: smith-build`.

**Root cause: the writer and the readers disagree about where the project
root is.**

- `scripts/create-active-workflow.sh:139` resolves it with
  `git rev-parse --show-toplevel`, which inside a worktree returns **the
  worktree**.
- `hooks/workflow-gate.sh:60` resolves it with `${CLAUDE_PROJECT_DIR:-$(pwd)}`
  → `git rev-parse --git-common-dir` → `dirname`, which returns **the primary
  repo**. `hooks/active-workflow-janitor.sh:42` does the same.

So the collision check at `create-active-workflow.sh:158-165` — which §Q6
quotes correctly, and which does behave exactly as quoted — never fires,
because it stats `$MARKER_PATH` under a directory the first marker was never
written to. The check is right. The path it checks is not the path the other
marker is on.

**Three consequences, all observed rather than reasoned:**

1. **Two concurrent markers are the normal state, not an error state.** The
   FR-17 nesting derivation therefore has a *better* primary signal than §Q6
   believed was available: a marker in a linked worktree's vault naming the
   same `branch:` as a marker in the primary vault, with a different
   `workflow:`, is a nested workflow, directly. Phase-title matching against
   the event stream — §Q6's "derivation that actually works" — is still
   correct and still implemented, but it is now the **fallback**, used only
   when no child marker exists. See the amended FR-17 in
   [`spec.md`](./spec.md), which records the dual-vault enumeration as primary
   and this section's derivation as the demoted second tier. `plan.md`
   §Spec-plan tensions item 4 and `quickstart.md` Scenario 6 were corrected in
   place for the same reason.
2. **The worktree marker's `session_log:` field is empty** — written with a
   trailing space and nothing after it, because `.smith/vault/.current-session`
   does not exist in a worktree. This is a valid, occurring shape, not
   corruption, and every marker parser must tolerate it and fall back to the
   primary vault's `.current-session`.
3. **The worktree marker is write-only state.** The gate resolves to the
   primary repo and reads only that vault, so nothing in Smith ever consumes
   the marker `smith-build` just wrote. A fourth consequence followed from
   that during this very build: `active-workflow-janitor.sh` runs on every
   `Stop` and sweeps markers whose branch tip is reachable from `main` — which
   is trivially true before a branch's first commit. Its one-hour grace window
   (`SMITH_JANITOR_GRACE_SECONDS`, default 3600) bounds this to short runs
   only, and a multi-hour build with no commits yet sails past it. The janitor
   swept the **primary** marker mid-build and silently revoked the build's
   write authorization, while the worktree marker nothing reads sat untouched.

**On the method, as distinct from the answer.** The reasoning above is sound
and worth keeping: it read the real scripts, quoted the real collision check at
the real line numbers, traced the real call sites in
`skills/smith-build/SKILL.md` and `skills/smith-new/SKILL.md`, and drew the
only conclusion those facts support. It was not sloppy and it was not a guess.
What it lacked was a single observation — that `--show-toplevel` and
`--git-common-dir` disagree inside a worktree — which no amount of further
reading of those same files would have produced, because the disagreement
lives *between* two files that never reference each other. It surfaced the
moment the thing was run. That is the transferable lesson: static tracing
across a boundary that neither side names is exactly where a run beats a read,
and the resulting confidence ("guaranteed", "every single time", "never") was
the part that should have been hedged, not the analysis.

**Not fixed here.** The fix is a behavior change to one script and two hooks,
with a blast radius across every workflow that registers a marker. It is
documented in [`docs/architecture.md`](../../../../../docs/architecture.md)
§Activity Daemon and banked as a separate bugfix alongside BANK-030.

---

## §Q7 — Emitter latency budget

**Decision: `curl --max-time 2 --connect-timeout 1`, backgrounded, as the
fallback path; a native `"type": "http"` entry with `"timeout": 5` as the
preferred path. Measured, not assumed. The budget is met with ~50× headroom.**

### Measurements taken on this machine

Against a stdlib `ThreadingHTTPServer`-shaped listener on `127.0.0.1:8899`,
using the actual hook payload shape:

| Scenario | Result |
|---|---|
| `curl` POST, daemon **UP**, 20 iterations | **0.133 s total → ~6.6 ms/call** |
| `curl` POST, single call, `/usr/bin/time -p` | **`real 0.01`** (×3 runs, identical) |
| `curl` POST, port **CLOSED**, 20 iterations | **0.128 s total → ~6.4 ms/call** |
| `curl` POST, daemon **HANGING**, `--max-time 1`, ×5 | 5.079 s total, `rc=28` each — bounded exactly as declared |
| `curl` POST, daemon **HANGING**, backgrounded, ×5 | **0.009 s total → ~1.8 ms/call foreground cost** |

The sub-500 ms target (A-2) is met by roughly **50×** on the live path and
**75×** on the refused path. Connection-refused on loopback is immediate; there
is no SYN retry to wait out.

### The finding that makes `--max-time` mandatory rather than stylistic

**This machine has neither `timeout` nor `gtimeout`:**

```
$ command -v timeout gtimeout
(no output)
```

Both ship with GNU coreutils, which macOS does not include. That means
`hooks/context-loader.sh:117-122` and `hooks/manifest-updater.sh:122-127`,
which both do:

```bash
TIMEOUT_BIN=""
if command -v timeout >/dev/null 2>&1; then TIMEOUT_BIN="timeout 5s"
elif command -v gtimeout >/dev/null 2>&1; then TIMEOUT_BIN="gtimeout 5s"; fi
...
printf '%s' "$INPUT" | $TIMEOUT_BIN python3 "$HELPER" compose-injection
```

**impose no timeout at all on a stock macOS.** `TIMEOUT_BIN` is empty and the
helper runs unbounded. The repo's documented 5 s and 2 s budgets are
aspirational on the platform this repo is developed on. There is no
background-and-kill fallback anywhere in `hooks/` to copy.

Consequence for FR-40, whose exit-0-within-a-hard-timeout guarantee is
absolute: **the emitter must not borrow the `TIMEOUT_BIN` idiom.** Its bound
must come from the transport itself. `curl` is present on every macOS and
every GitHub `ubuntu-latest` runner, and `--max-time` / `--connect-timeout`
are built in — no coreutils, no shell tricks, and (measured above) they hold
precisely.

### The other portability finding: `/dev/tcp` is bash-only

`skills/smith-research/scripts/start-playwright-server.sh:39-46` falls back to
`(exec 3<>"/dev/tcp/localhost/$PORT")` when `nc` is missing. Under `zsh`:

```
$ zsh -c 'exec 3<>/dev/tcp/127.0.0.1/8901'
zsh:1: no such file or directory: /dev/tcp/127.0.0.1/8901
```

Under `bash` the same line succeeds. `/dev/tcp` is a bash-only virtual path.
This repo runs its shell surfaces under **both** shells (features 55 and 59
both mandate dual-shell verification), so:

- `smith-activity.sh`'s port probe uses `nc -z` when present and **`python3 -c
  'socket.create_connection(...)'`** otherwise — never `/dev/tcp`. `python3`
  is already an unconditional dependency of the flat test suite
  (`tests/stamp-response.test.sh:29,46,53`).
- The emitter never opens a socket itself; it delegates entirely to `curl`.

### Preferred path: native `"type": "http"`

Confirmed against the official hooks reference: Claude Code supports
`"type": "http"` with `url`, optional `headers` (supporting `$VAR`
interpolation gated by `allowedEnvVars`), and the same JSON envelope on the
POST body. Zero process spawn per tool call — a real win given that
`PostToolUse` matcher `*` fires on **every** tool.

Also confirmed: **`timeout` is a real hook-entry field, in seconds, and the
default for `command` and `http` hooks is 600 s (10 minutes).** That default
is the argument for declaring one explicitly: an undeclared emitter inherits a
ten-minute ceiling. This feature will be the first entry in
`settings/smith-settings-fragment.json` to carry a `timeout` field — verified
absent across the whole `settings/` directory today.

**Install-time detection** (FR-42): read Claude Code's version via
`claude --version` and compare against the floor at which `type: "http"` is
documented; on any parse failure, fall back. The fallback is not a degraded
mode — it is measured at ~1.8 ms of foreground cost — so the detection is
allowed to be conservative and wrong in the safe direction.

**The emitter's exit-0 discipline, independent of both paths**, mirroring
`hooks/metrics-tracker.sh`'s structure (its own `PostToolUse` entry, matcher
`*` — the closest existing precedent for a see-everything hook):

```bash
#!/usr/bin/env bash
set -uo pipefail                 # NOT -e: a failing curl must not abort
INPUT=$(cat 2>/dev/null || echo '{}')
PORTFILE="${SMITH_HOME:-$HOME/.smith}/activity/activity.port"
TOKFILE="${SMITH_HOME:-$HOME/.smith}/activity/activity.token"
[ -f "$PORTFILE" ] && [ -f "$TOKFILE" ] || exit 0
command -v curl >/dev/null 2>&1 || exit 0
PORT=$(cat "$PORTFILE" 2>/dev/null) || exit 0
TOKEN=$(cat "$TOKFILE" 2>/dev/null) || exit 0
case "$PORT" in ''|*[!0-9]*) exit 0 ;; esac
(
  printf '%s' "$INPUT" | curl -s -o /dev/null \
    --max-time 2 --connect-timeout 1 \
    -X POST -H 'Content-Type: application/json' \
    -H "Authorization: Bearer $TOKEN" \
    --data-binary @- "http://127.0.0.1:$PORT/ingest" >/dev/null 2>&1 &
) >/dev/null 2>&1
exit 0
```

Every line is a silent `exit 0` on failure; the subshell-plus-`&` detaches so
the hook does not wait even for the 2 s ceiling; `>/dev/null 2>&1` on the
subshell guarantees zero bytes on stdout, which on `UserPromptSubmit` and
`SessionStart` would otherwise be **injected into Claude's context** rather
than merely being noise. Exit code 2 is the block signal, and there is no path
here that reaches it.

---

## §Q8 — Hook event availability

**Decision: every event in FR-43's desired set is CONFIRMED against the
official reference. `SubagentStart` is no longer load-bearing regardless,
because §Q4's `.meta.json` sidecar supersedes it. The genuine gap is
elsewhere — in `claude agents --json`.**

### Confirmed

All fifteen names in FR-43 are documented hook events:
`SessionStart`, `SessionEnd`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`,
`SubagentStart`, `SubagentStop`, `TaskCreated`, `TaskCompleted`, `Stop`,
`PreCompact`, `PostCompact`, `Notification`, `PermissionRequest`,
`PermissionDenied`.

The documented set is in fact larger, and four of the extras are directly
useful here:

| Extra event | Use in this feature |
|---|---|
| `PostToolUseFailure` | `PostToolUse` fires only on **success**. A failed tool call is invisible without this — and "the tool errored" is exactly the kind of absence FR-23 exists to render |
| `ConfigChange` (carries `source`, `file_path`) | invalidates §Q3's settings cache on a real signal instead of a poll |
| `StopFailure` (carries `error_type`, incl. `rate_limit`) | correlates a stalled session with the quota panel |
| `CwdChanged` | a session moving into a worktree mid-run, which FR-28/FR-29 must re-resolve |

`PostToolUseFailure` and `ConfigChange` are folded into the wired set.
`StopFailure` and `CwdChanged` are listed in `contracts/hook-envelope.md` as
"wire if trivial" — neither is load-bearing.

**Envelope fields**, confirmed: `session_id`, `prompt_id`, `transcript_path`,
`cwd`, `permission_mode`, `hook_event_name` are common to every event;
`agent_id` and `agent_type` are real fields available inside a subagent;
`tool_name` / `tool_input` / `tool_response` are event-specific.

**Exit codes**, confirmed: exit **2** is the block signal (stderr is fed back
to Claude on `PreToolUse`/`PostToolUse`/`PermissionDenied`); other non-zero
codes are non-blocking errors that surface a `<hook name> hook error` notice.
This refines the spec's "a non-zero exit BLOCKS the tool call" — the emitter's
exit-0 guarantee is unchanged and remains correct as stated, because a
non-zero-but-not-2 exit still surfaces a visible error notice to the operator,
which US-4 forbids just as firmly.

### `SubagentStart` is no longer load-bearing

A-1 named it "the load-bearing one", with `PreToolUse` on `Task` plus sidechain
detection as the documented fallback. §Q4 supersedes both: the
`agent-<id>.meta.json` sidecar appears at spawn and carries `agentType`,
`description`, `parentAgentId` and `spawnDepth` directly. The live-subagent
panel is therefore built on **sidecar discovery as primary**, with
`SubagentStart` as a latency optimization (it arrives via the emitter in
~7 ms; the sidecar is found on the next ~1 s poll). If `SubagentStart` were
withdrawn from Claude Code tomorrow, the panel would lose up to one second of
responsiveness and nothing else. That is the right dependency posture for a
tool whose premise is not trusting self-reports.

### The real gap: `claude agents --json` has no `waitingFor`

Executed against the installed Claude Code **v2.1.269**, across 23 live
records, the union of keys is:

```
['cwd', 'kind', 'name', 'pid', 'sessionId', 'startedAt', 'status']
```

- `status` is present on **6 of 23** records, values `idle` / `busy`.
- `state` — present in **0** records.
- `waitingFor` — present in **0** records.
- `id` — present in **0** records. (The identifier is `sessionId`.)
- `kind` — only ever `interactive` in this sample.

`claude agents --help` documents `--json` as *"Print active sessions
(interactive and background) as a JSON array and exit"* and `--all` as
*"also include completed background sessions"*. There is no flag that adds
richer state.

**This breaks two requirements as written:**

- **FR-26** specifies using `id`, `state` and `waitingFor`. Three of the nine
  named fields do not exist; `status` (optional, two values) is the closest
  available substitute for `state`.
- **FR-18** requires MANDATORY STOP gates to render "paired with `waitingFor`
  from `claude agents --json` where available" and forbids rendering
  "waiting on you" as "working". **There is no `waitingFor` to pair with.**

What still works, unchanged: FR-24's dead-session reaper (a session absent
from the array is gone — `sessionId` and `pid` are both present), and the
three-state classification degraded to two-and-a-half:

| Rendered state | Source |
|---|---|
| working | `status == "busy"`, else recent ingested activity |
| idle | `status == "idle"` |
| waiting on permission | **`PermissionRequest` ingest with no subsequent `PermissionDenied` or `PostToolUse` for the same `prompt_id`** |

That third row is the recommended substitute: `PermissionRequest` is a
confirmed hook event (this section), it is hook-sourced rather than
self-reported — which is *better* under the spec's own trust hierarchy
(FR-21) — and it arrives in ~7 ms rather than on a 5-10 s poll. FR-18's
MANDATORY STOP gates (`smith-new` Phase 5, `smith-debug` Phase 6) are not
permission prompts at all; they are the model waiting on a user reply, which
is observable as "`Stop` fired, no `UserPromptSubmit` since" — a cleaner
signal than `waitingFor` would have been.

**Recommendation: amend FR-18 and FR-26 to the observed record shape and the
`PermissionRequest`-derived indicator.** This is a spec correction, not a plan
decision, and it goes to the Phase 5 questions gate — see `plan.md`
§"For the questions gate".

### The statusline payload is confirmed in full

`rate_limits` is real and carries `five_hour`, `seven_day` and `spend_limit`,
each with `used_percentage` (0-100) and `resets_at` (**Unix epoch seconds**,
not ISO-8601 — the UI must format it). It is documented as present for Pro/Max
subscribers and may be absent entirely, which is exactly FR-35's
"unavailable" path. `context_window`, `cost` and `model` are also present and
give the tokens panel a free cross-check against §Q4's own rollup — a
divergence between them is itself a finding.

---

## §R — Reuse inventory (what this feature imports, and what it must NOT reimplement)

### §R.1 — `hooks/workflow_summary_lib.py` (939 lines, stdlib only, Python 3.8+)

**Imported and called. Never copied, never re-implemented, never forked.**

Consumed functions:

| Function | Line | Used for |
|---|---|---|
| `load_pricing(path)` | 88 | **the only sanctioned way to obtain the pricing table** |
| `match_family(model, pricing)` | 127 | model id → rates |
| `normalize(usage)` | 51 | normalized total (FR-32) |
| `cost_usd(usage, rates)` | 65 | USD estimate (FR-32) |
| `parse_parent_jsonl(path, start, end)` | 157 | parent-session rollup |
| `resolve_parent_jsonl(root, log_text)` | 215 | transcript discovery |
| `resolve_workflow_window(path, text)` | 793 | per-workflow time window |
| `parse_subagent_blocks(content)` | 320 | completed-subagent usage from the log |
| `format_tokens` / `format_usd` / `format_duration` | 448/459/463 | display formatting |

**THE CONTRACT TRAP, verbatim.** `load_pricing` injects a key at `:122`:

```python
    data["_compiled_patterns"] = compiled
    return data
```

and `match_family` reads only that key, `:134`:

```python
    patterns = pricing.get("_compiled_patterns") or []
```

`.get(...) or []` means a raw `json.load(open("pricing.json"))` dict degrades
to "no match" **with no exception and no log line** — every model resolves to
`None`, every USD figure silently becomes unavailable. `usage.py` therefore
obtains the table **only** via `load_pricing()`, and
`tests/smith-activity.test.sh` asserts that `scripts/activity/` contains no
independent `pricing.json` parse (`grep -L 'load_pricing' `on any file
mentioning `pricing`).

**Safe to import into a long-lived daemon** — verified, not assumed: no
import-time side effects (module level is imports, `NORMALIZED_WEIGHTS`, two
int constants, four compiled regexes, and the `__main__` guard); no `global`
statements; no `lru_cache`/`@cache`; no open handles; env reads confined to
`main()` at `:843-845` (`SESSION_FILE`, `PROJECT_ROOT`, `TOTALS_ONLY`). Its
only subprocess is `git_files_changed` → `git diff --name-only main..HEAD`,
`timeout=5`, exceptions swallowed.

**But it caches nothing**, so `load_pricing()` re-reads and re-compiles
`pricing.json` on every call. The daemon therefore **throttles itself**:
`load_pricing()` is called once at startup and refreshed at most once per
60 s (mtime-gated); `parse_parent_jsonl` runs at most once per session per
~2 s, from a remembered byte offset. Git is debounced at ~3 s (FR-31) and
never invoked per SSE frame.

Import mechanism reused verbatim from `hooks/workflow-summary.sh:198-214` —
`PYTHONPATH="$HOOK_DIR"` plus `import workflow_summary_lib as L`, with
`HOOK_DIR` resolved from `$CLAUDE_HOOKS_DIR`, then `~/.claude/hooks`, then
`$SCRIPT_DIR`. The daemon uses the same three-candidate ladder.

**Would otherwise be duplicated:** the entire normalize/cost/pricing/JSONL
stack — ~250 lines, plus the `_compiled_patterns` trap re-created from
scratch. This is the single largest piece of reuse in the feature.

### §R.2 — `skills/smith-research/scripts/start-playwright-server.sh` (92 lines)

**The only real daemon-lifecycle precedent in the repo.** Mirrored
structurally, with two documented deviations.

Reused verbatim in shape:
- **Already-up short-circuit** (`:48-52`) — probe the port, print the URL,
  `exit 0`. This is what makes FR-2's idempotence free.
- **Stale-PID detection** (`:54-61`) — `kill -0 "$OLD_PID"`, kill if alive but
  not listening, `rm -f` the pidfile unconditionally. Directly satisfies FR-6.
- **`nohup … &` then `echo $! > "$PID_FILE"`** (`:72-80`).
- **Bounded readiness poll** (`:82-92`) — `for _ in 1..10; do … sleep 1; done`,
  then a diagnostic to stderr. Adopted at 15 iterations for a Python daemon
  that must also bind, read the token and warm its first state pass.
- **Last stdout line is the URL**, so callers can `$(… | tail -1)`.
- `set -euo pipefail`; documented exit codes in the header; unknown arg → 2.

Deviations, both justified:
1. **Pidfile under `~/.smith/activity/`, not `$TMPDIR`** (FR-7). `$TMPDIR` is
   per-user-per-boot on macOS and is periodically swept; a dashboard the
   operator expects to still be up tomorrow cannot have its pidfile
   garbage-collected. `~/.smith/<component>/` is the established layout for
   durable component state (`install.sh:149,217,236,263`).
2. **Port probe never uses `/dev/tcp`** — §Q7: it does not exist under `zsh`.
   `nc -z` when present, `python3 -c socket.create_connection` otherwise.

**Would otherwise be duplicated:** the whole start/probe/stale/readiness
sequence, ~60 lines, and its accumulated edge cases.

### §R.3 — `scripts/lib/dedupehooks.jq` + `scripts/install.sh:284-318`

**Reused as-is. No second merge path is invented.**

The dedupe key is the individual **(matcher, serialized-hook-object)** pair —
`dedupehooks.jq:21`, `($matcher + "|" + ($hook | tostring)) as $key` — so a
`timeout` field participates in identity, and chain order is preserved by
construction (`reduce` walks entries and hooks in order and appends). The
module's own header (`:9-13`) promises the ordering guarantee explicitly.

The existing merge invocation (`install.sh:289-308`) puts `$existing` entries
first and appends `$fragment`, so this feature's new entries land at the end
of their event's array. The write guard (`:309-318`) — tempfile, `jq empty`,
`mv` only on success, otherwise `err` and leave the file untouched — is reused
unchanged.

**The one real hazard, and how the plan avoids it.**
`scripts/install-hooks.sh:6-7` and `:149-183` enforce that
`manifest-updater.sh` stays LAST in the `PostToolUse` `Write|Edit` chain, and
`tests/hooks/test_hook_chain_order.sh` is a regression test for it. **The
emitter must therefore NOT be appended to an existing chain.** It gets its own
entry with matcher `*`, exactly like `hooks/metrics-tracker.sh`
(`settings/smith-settings-fragment.json:48-53`) — which is also the only
existing hook that already sees every tool call, and therefore the precedent
in both structure and intent.

**Would otherwise be duplicated:** an idempotent settings merge — the most
dangerous thing in this repo to have two of, since a divergent second merger
would silently corrupt the operator's `~/.claude/settings.json`.
`scripts/dedupe-settings.sh:48-52` already shares this jq module precisely so
"the two can never drift apart" (its `:11`); a third path would break that.

### §R.4 — `scheduler/` — layout and logging conventions ONLY

Borrowed: the `~/.smith/<component>/` shape (executables and logs together),
and the log line format (`smith-scheduler.sh:43-45`):

```bash
log() { echo "[$(date -u +"%Y-%m-%d %H:%M:%S")] $1" >> "$LOG_FILE"; }
```

— UTC, bracketed, append-only, with `mkdir -p "$(dirname "$LOG_FILE")"` +
`touch` bootstrap. Also borrowed: the opt-in kill switch shape
(`:53-56`, silent `exit 0` when disabled).

**NOT borrowed: `scheduler/smith-scheduler.sh:36`.**

```bash
SMITH_DIR="$HOME/.smith"
```

`grep -n SMITH_HOME scheduler/smith-scheduler.sh` → no matches. The script
hardcodes `$HOME/.smith` and does not honor `SMITH_HOME`, even though
`install.sh:254` copies it to `"$SMITH_HOME/scheduler/"` and templates
`__SMITH_HOME__` into the plist. A custom-`SMITH_HOME` install therefore
produces a scheduler that logs to the wrong tree. That is a latent bug, not a
pattern.

**The canonical form is the installer's**, and this feature follows it
everywhere (FR-7):

```bash
SMITH_HOME="${SMITH_HOME:-$HOME/.smith}"     # install.sh:20, uninstall.sh:15
```

`scheduler/` is also **not** a daemon precedent — it is a launchd batch job
that exits (A-5 says so, and it is correct). There is **no log rotation
anywhere in this repo**; `activity.log` therefore ships its own size-capped
rotation (single rollover at 5 MB to `activity.log.1`), because a daemon
seeing every `PostToolUse` would otherwise grow without bound.

### §R.5 — Existing hook scripts: exit-0 and timeout idioms

Reused: `set -uo pipefail` (never `-e` — the guard/loader hooks avoid it
deliberately); `INPUT=$(cat 2>/dev/null || echo '{}')`; the early-bail ladder
where each branch logs a `reason=` and `exit 0`; the shared
`LOG_FILE="${HOME}/.smith/logs/hooks.log"` with every write suffixed
`2>/dev/null || true`; the three-candidate helper-resolution loop; a trailing
unconditional `exit 0`. 16 of 19 hooks end that way; the three that do not
(`grade-response.sh:109`, the two security guards' `deny()` helpers) all use
**exit 2**, the block signal, deliberately.

Field extraction uses `grep -o`/`sed`, not `jq` — `manifest-updater.sh:29-31`
states the reason: *"Avoids a jq dependency on the hot path."* The emitter
goes further and does **not parse the payload at all**: it forwards stdin
verbatim to `/ingest` and lets the daemon parse. That is strictly faster,
strictly safer, and sidesteps `file-change-logger.sh`'s known mis-parse on an
escaped quote in `file_path`.

**NOT reused: the `TIMEOUT_BIN` idiom** — §Q7 proves it is a no-op on stock
macOS. The emitter's bound comes from `curl --max-time`.

**No hook in this repo makes a network call today.** The only `curl`/`wget`
mentions are the *detection pattern* at `hooks/security-guard-bash.sh:253-254`,
which denies pipe-to-shell (`curl … | bash`) and does not match a plain
`curl` POST. `grep -n 'urllib\|requests\|socket\|http' hooks/*.py` → zero.
The emitter is a genuine first for this codebase and is sequenced first in
`plan.md` for exactly that reason.

### §R.6 — Marker and session-log readers

Reused as **read-only** input contracts, never re-derived:

- **Marker schema** — `create-active-workflow.sh:181-187`, six plain unquoted
  `key: value` lines. Parsing tolerates optional surrounding quotes, per
  `hooks/active-workflow-janitor.sh:118`'s own precedent, and tolerates
  `smith-finish`'s 4-field variant (§Q1).
- **Session-log discovery precedence** — reused verbatim from
  `hooks/workflow-summary.sh:84-135`: (a) explicit path, (b) the `session_log:`
  field of an active-workflow marker, disambiguated by `branch:` when several
  carry one, (c) `.smith/vault/.current-session`. This is the exact rollover
  hazard the spec's FR-14 concurrency case sits on top of.
- **`.current-session` read idiom** — `metrics-tracker.sh:23-32`'s
  double existence check (pointer file, then target file).
- **Block formats** — `Subagent invoked:` (model-authored, 4 lines, `**Type:**`
  / `**Model:**`), `Subagent completed` (`subagent-vault-writeback.sh:192-202`,
  8 metric lines, **carries no description and no type** so pairing is
  positional only), the metrics line
  (`` - `[HH:MM:SS]` **Tool** in:N out:N total:N (ident) ``), and the
  file-change line (`` - `[HH:MM:SS]` **Tool** `rel/path` `` — backticked path
  is what distinguishes it from the metrics line). All documented field-by-field
  in `data-model.md` §4.

**Would otherwise be duplicated:** four bespoke markdown parsers and a
three-tier log-discovery heuristic with a known rollover hazard.

### §R.7 — Test harness

Reused verbatim in shape from `tests/settings-dedupe.test.sh:10-27`: the
`set -uo pipefail` (no `-e`) header, `SCRIPT_DIR`/`REPO_ROOT` resolution,
`PASS`/`FAIL` counters, the single `assert` helper, `mktemp -d -t <tag>.XXXXXX`
plus `trap 'rm -rf "$TMP"' EXIT`, `# --- Test N: … ---` banners, and the
`PASS x / FAIL y` summary with non-zero exit.

Scratch git repos reuse `tests/get-base-branch.test.sh:24-40`'s `make_repo`
(`mktemp -d`, `git init -q`, `git config user.email/user.name` in a subshell).
**No existing test uses `git worktree`**, so the HELD/MISSING/ORPHANED fixtures
(SC-8) extend `make_repo` with a `git worktree add` step — a small, documented
extension rather than a new harness.

**Would otherwise be duplicated:** the assert/fixture/cleanup trio, five
times over.

### §R.8 — `/smith-activity`'s own marker (FR-8)

Reused directly: `create-active-workflow.sh --workflow maintenance` with a
**synthetic `--branch` label naming no real git ref**, exactly as
`/smith-audit --scheduled` already does. `docs/security-model.md:165` documents
that precedent in so many words: *"a `maintenance`-type active-workflow marker
… carries a synthetic `--branch` label that names no real git ref — it exists
only to satisfy the marker file's required fields."*

`maintenance` is in the allowlist (`create-active-workflow.sh:115`, confirming
A-6). Cleared via `clear-active-workflow.sh` — which lives at
`skills/smith/scripts/clear-active-workflow.sh`, **not** `scripts/`, and is
reached in projects as `.specify/scripts/bash/clear-active-workflow.sh`.
Note `install.sh:225-226` stages `create-active-workflow.sh` into
`~/.smith/scripts/` but does **not** stage `clear-active-workflow.sh`; the
SKILL must use the `.specify/scripts/bash/` path for the clear, as every other
skill does.

### §R.9 — A gate interaction the plan must state, not discover

`hooks/workflow-gate.sh:78-94` short-circuits: if **any** `*.yaml` exists in
`active-workflows/`, the gate `exit 0`s for **every** tool call — including
writes into `active-workflows/` itself. `SAFE_VAULT_DIRS` (`:97`, nine dirs,
`active-workflows` deliberately absent) and the
`create-active-workflow.sh` basename exemption (`:252`) are dead code whenever
a marker is present.

Two consequences:

1. **The gate provides no enforcement against FR-44.** The spec already says
   so (A-7: the daemon is detached and outside the hook system). The
   short-circuit means it provides no enforcement *even against the emitter*,
   which runs inside the hook system. FR-44 is therefore a pure design
   requirement, tested by asserting that no file under `scripts/activity/` or
   `hooks/activity-emitter.sh` contains the string `active-workflows` outside
   a read path.
2. `workflow-gate.sh:61-70` resolves `PROJECT_DIR` via
   `git rev-parse --git-common-dir` + `dirname` — the **primary** repo —
   while `create-active-workflow.sh:139` uses `--show-toplevel` — the
   **worktree**. The two disagree inside a worktree. The daemon follows the
   gate's convention (FR-28), and `data-model.md` §1 records the divergence so
   a reader does not assume the markers live where `--show-toplevel` points.

### §R.10 — Two transcript fields that must NOT be trusted

Observed in this session's own subagent transcript:

```json
{"cwd":"/private/tmp/smith-activity-dashboard","gitBranch":"main", ...}
```

The worktree at that path is on branch `60-activity-dashboard`
(`git rev-parse --abbrev-ref HEAD` confirms), not `main`. **`gitBranch` in the
transcript is captured at session start and does not follow the cwd.** The
daemon therefore derives branch from
`git -C <cwd> rev-parse --abbrev-ref HEAD` (debounced per FR-31) and never
from the transcript field.

Similarly, `git rev-parse --git-common-dir` returns an **absolute** path from
inside a worktree but a **relative** `.git` from inside the primary repo.
FR-28's resolution uses `git -C <path> rev-parse --path-format=absolute
--git-common-dir` and then `dirname`, which is correct in both positions —
verified from both.
