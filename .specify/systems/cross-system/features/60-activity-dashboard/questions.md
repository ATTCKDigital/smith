# Implementation Questions: smith-activity — Local Real-Time Smith Activity Audit Dashboard

**Generated**: 2026-09-22
**Feature**: [spec.md](./spec.md)
**Plan**: [plan.md](./plan.md)
**Research**: [research.md](./research.md)
**Status**: ANSWERED

Nine questions, ordered by impact. Q1-Q2 arise from live findings verified against the
installed toolchain and contradict the spec as written. Q3-Q6 are scope and design
decisions. Q7-Q9 are adjacent-cleanup judgment calls.

Four decisions were settled with the user before the gate and are NOT re-asked here:
authoritative phase stamping is out of scope (inference first, resolver prefers `phase:`
if present); no launchd; retention is ephemeral behind a swappable boundary; no auto-open
on SessionStart.

---

## Q1: `claude agents --json` does not expose the fields FR-18 and FR-26 require

**Context**: spec.md FR-26 specifies the session reconciler polls `claude agents --json`
for `{id, sessionId, cwd, kind, state, status, pid, waitingFor, startedAt}`. FR-18 requires
pairing MANDATORY STOP phases with the session's `waitingFor` so "waiting on you" is
visually distinct from "working" — called out in the original brief as "exactly the thing
I want to see at a glance."

Verified against the installed Claude Code across 23 live records: `waitingFor`, `state`
and `id` are present in **zero** records. `status` appears in only 6 of 23. The actual
shape is `{pid, cwd, kind, name, sessionId, startedAt, status?}`.

**Question**: How should "waiting on a permission prompt" be determined?

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | Derive from the `PermissionRequest` / `PermissionDenied` hook events; keep `claude agents --json` only for liveness reconciliation (pid, cwd, startedAt) | Amends FR-18 and FR-26. Event-driven rather than 5-10s polled, so the indicator is near-instant. Consistent with FR-21's own trust hierarchy — hook events over derived state. Requires those events to exist, which the planner reports as documented-confirmed but which has not been observed firing on this machine. |
| B | Keep polling `claude agents --json` and degrade — show "waiting" only when `status` happens to be present | No spec amendment. But `status` is absent in 17 of 23 records, so the panel is blank most of the time, and a headline feature silently under-delivers. |
| C | Both — `PermissionRequest` as primary, `status` as corroboration, and surface disagreement as a divergence finding | Most faithful to the audit framing: two independent sources, and their disagreement is itself the product. Costs more code in the reconciler and more UI surface. |

**Recommended**: **A**, with C as a fast follow. The field simply does not exist, so B
under-delivers the feature's most-requested glance-value. A is the honest fix and is
better on the feature's own stated principle. C is attractive but should not gate v1.

**Answer**: **C** — Both. `PermissionRequest` / `PermissionDenied` hook events are the primary signal for "waiting on a permission prompt"; `claude agents --json` `status` is kept as corroboration where present; disagreement between the two is surfaced as a divergence finding. Amends FR-18 and FR-26. Rationale: the dual-source-plus-disagreement shape is the feature's own audit thesis applied to itself, and the reconciler has to read both sources anyway for liveness.

---

## Q2: USD cost is already silently unavailable, before this feature ships

**Context**: spec.md FR-33/FR-34 require live token cost in USD. Two independently
verified defects mean this renders "unavailable" on every session today:

1. `scripts/install.sh:195,203` copies `hooks/*.sh` and `hooks/*.py` to `~/.claude/hooks/`.
   It never copies `*.json`, so **`pricing.json` is never installed**. The copy on this
   machine is dated 2026-04-14 and has never been refreshed by an install.
2. The newest family in `hooks/pricing.json` is `claude-opus-4-6*`. The running model is
   `claude-opus-5`. `match_family()` returns `None`, so `cost_usd()` returns `None`.

So FR-34's "unknown model renders unavailable, never `$0.00`" is the **primary** path
right now, not an edge case.

**Question**: How much of this does this feature fix?

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | Fix both — add `*.json` to the installer copy loop and add `claude-opus-5*` / current families to `pricing.json` | The USD panel actually works on delivery. Both fixes are small and land in files this feature already touches. Also silently repairs the existing Stop-hook workflow summary, which has the same defect. |
| B | Fix the installer glob only; leave pricing data alone | Installer is correctly fixed, but USD still reads "unavailable" until someone updates pricing, so the panel ships visibly broken. |
| C | Fix neither; file a separate bugfix | Keeps this feature's diff tight. But the tokens panel ships with its headline number permanently blank, and the user discovers a known-broken feature. |

**Recommended**: **A**. Both are a handful of lines in files already in scope, and the
feature's own USD requirement is unmeetable without them. Fixing the installer without
the pricing data ships a panel that is still blank.

**Answer**: **A** — Fix both. Add `*.json` to the `scripts/install.sh` hook copy loop so `pricing.json` is actually installed, and add the current model families (including `claude-opus-5*`) to `hooks/pricing.json`. Also repairs the pre-existing Stop-hook workflow summary, which has been silently omitting USD for the same reason.

> **Build-phase note:** rates must NOT be invented. During implementation, consult the authoritative Claude pricing reference (the `claude-api` skill is the designated source and explicitly forbids answering from memory) and set `last_verified` to the date checked. If authoritative rates cannot be obtained, add the family entry with the correct match pattern but surface the rates as unavailable rather than guessing — FR-34's "never `$0.00`" applies to fabricated rates as much as to missing ones.

---

## Q3: Live subagent token usage (FR-36) — build now or defer?

**Context**: FR-36 requires live token usage for *running* subagents.
`hooks/workflow_summary_lib.py` does not parse subagent transcripts at all — it derives
subagent totals from completed session-log markdown blocks. The planner found that Claude
Code writes an `agent-<id>.meta.json` sidecar carrying `agentType`, `description`,
`parentAgentId`, `spawnDepth`, `toolUseId`, and that sidechain `message.usage` is
byte-identical in shape to the parent's — so this is `parse_parent_jsonl`'s loop with the
`isSidechain` guard inverted, estimated ~65 lines.

Critically: the parent transcript contains **zero** `isSidechain` rows (verified over 360
lines), so a deferred FR-36 shows `0` tokens for every running subagent until `SubagentStop`.

**Question**: Build live subagent token parsing in v1?

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | Build it now | ~65 lines against a confirmed file shape. The live-subagent panel shows real numbers. Adds the only genuinely new parsing code in the usage path. |
| B | Defer; show completed-subagent totals only, and render running subagents with an explicit "pending" rather than `0` | Smaller v1. But the live-subagent panel is a named headline item and would show nothing useful while a subagent runs — which is exactly when you are looking at it. |

**Recommended**: **A**. The cost is small and well-understood, and B's failure mode lands
precisely on the moment the panel exists to serve. B is only right if v1 scope is under
real pressure.

**Answer**: **A** — Build it now. Parse `~/.claude/projects/<slug>/<session-id>/subagents/agent-<id>.jsonl` for live sidechain usage, and read the `agent-<id>.meta.json` sidecar for `agentType` / `description` / `parentAgentId` / `spawnDepth` / `toolUseId` to populate the live-subagent panel (FR-27). Implemented as `parse_parent_jsonl`'s accumulation loop with the `isSidechain` guard inverted, kept in `scripts/activity/usage.py` alongside the existing `workflow_summary_lib` import rather than modifying that lib. Deferral was rejected because the parent transcript carries zero `isSidechain` rows, so a deferred FR-36 renders `0` for every running subagent until `SubagentStop` — failing exactly when the panel is being watched.

---

## Q4: "No build step" — does that also mean "one file"?

**Context**: The brief specified `scripts/activity/static/index.html` as a "single-file
dashboard, no CDN, no build step". Honest estimate for the full UI in one file is ~800
lines, well over the repo's 300-line soft target / 500-line decomposition threshold.

The planner's reading: the constraint is *no build step*, not *one file*. Serving
`app.css`, `app.js` and `panels.js` alongside `index.html` costs three more loopback GETs
from a server already running — no bundler, no npm, no transpile. Proposed split:
`index.html` 120 / `app.css` 220 / `app.js` 180 / `panels.js` 260.

**Question**: Accept the multi-file split?

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | Accept the split — four static files, still zero build step | Honors the size policy. Panels become independently readable and diffable. Slightly more install/uninstall surface (four files instead of one). |
| B | Keep a literal single `index.html` | Matches the brief word-for-word and keeps the install trivially simple. Produces one ~800-line file that violates the repo's own decomposition threshold. |

**Recommended**: **A**. "No build step" is the constraint that carries the actual intent —
no toolchain, no dependencies, readable source. Four files served from loopback satisfies
that while respecting the size policy the constitution-less repo still encodes in its skills.

**Answer**: **A** — Accept the split. `scripts/activity/static/` ships `index.html` (~120), `app.css` (~220), `app.js` (~180) and `panels.js` (~260), served directly by the daemon over loopback. The constraint is reinterpreted as **no build step**, not **one file**: no bundler, no npm, no transpile, no CDN, no minification — plain `<link>` and `<script src>` against the already-running server. This keeps every file under the 300-line soft target. If `panels.js` later approaches the threshold, the pre-decided next split is to shed the phase stepper into `stepper.js`. Install and uninstall must copy and remove all four files, not just `index.html`.

---

## Q5: Divergence reconciliation window, and a clock-skew problem underneath it

**Context**: Divergence detection (FR-22) reports a `Task` dispatch that the harness
observed but which produced no matching session-log block. It needs a window — too tight
and every live dispatch is a false positive.

The planner found something underneath: **the session log mixes two clocks.** Hooks write
UTC (`date -u`); model-authored `Subagent invoked:` blocks use local wall time. This repo's
own log shows lines seconds apart reading `[11:34:20]` and `[15:37:34]` — a 4-hour skew.
Ordering on parsed timestamps is therefore unsafe.

Proposal: a **90-second, two-sided** window, ordered on **session-log append offset**
rather than parsed timestamps, with findings **retractable** when the matching block
arrives late. Two-sided because FR-11 assumed the Task event precedes the block, but all
four workflow SKILLs instruct the block to be written *before* the Agent call.

**Question**: Accept the 90s two-sided offset-ordered window with retractable findings?

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | Accept as proposed | Robust against the skew. Retraction means a finding can appear then vanish, which needs clear UI treatment so it doesn't read as a glitch. |
| B | Accept the mechanism, tune the window shorter (e.g. 30s) | Faster detection, more transient false positives on slow subagent dispatches. |
| C | Accept the mechanism, tune longer (e.g. 300s) | Near-zero false positives; a genuinely missing log block takes 5 minutes to surface. |
| D | Also fix the clock inconsistency at its source — make the skills write UTC | Removes the root cause permanently. But editing the four workflow skills is out of scope per the settled stamping decision, and changes the behavior being observed. |

**Recommended**: **A**. 90s is comfortably longer than any observed dispatch-to-block gap
while still surfacing a real miss quickly. D is the right eventual fix but collides with
the settled decision to leave the workflow skills untouched — worth filing separately.

**Answer**: **A** (recommendation accepted) — 90-second, **two-sided**, ordered on **session-log append offset** rather than parsed timestamps, with **retractable** findings.

Two-sided because FR-11's assumption is wrong: all four workflow SKILLs instruct the `Subagent invoked:` block to be written *before* the Agent call, so the block may precede or follow the `PreToolUse` Task event. Offset-ordered because the session log mixes two clocks — hooks write UTC (`date -u`) while model-authored blocks write local wall time, observed as a 4-hour skew between adjacent lines in this repo's own log. Parsed timestamps are therefore unusable for ordering and must not be used for it anywhere in the resolver.

> **UI requirement:** a retracted finding must visibly resolve (e.g. transition to a settled state) rather than silently disappearing, or retraction reads as a rendering glitch and undermines trust in the divergence panel.

> **Filed separately:** normalizing the workflow skills to write UTC is the real root-cause fix, but it edits the four workflow skills — barred by the settled stamping boundary, and it would change the behavior being observed. Track as its own bugfix.

---

## Q6: Where does the "expected hook set" come from for absence detection?

**Context**: FR-23 requires reporting "a hook that never fired". That needs a set of hooks
expected to fire. `docs/hooks.md:5` tells operators they may disable a hook by removing its
settings entry — so a static shipped list would report "lint-on-save never fired" at
someone who deliberately removed it, which is a false positive by design.

Proposal: parse the installed `~/.claude/settings.json`, refresh on `ConfigChange`,
intersect with a small applicability table (e.g. `lint-on-save` only applies after a
Write/Edit). If settings are unreadable, absence detection is **disabled and says so** in
the UI rather than guessing.

**Question**: Accept parsing installed settings as the source of expectation?

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | Parse installed `settings.json`, refresh on `ConfigChange`, disable with a visible notice if unreadable | Correct against user customization. Adds a settings parser and a dependency on `ConfigChange`. Honest failure mode. |
| B | Ship a static list of Smith's own hooks | Simpler, no parsing. Produces false positives for anyone who customized their hooks — including you, if you ever disable one. |
| C | Derive from `settings/smith-settings-fragment.json` in the repo | Knows Smith's intended set exactly. Wrong whenever installed state has drifted from the repo — which is the very drift this dashboard exists to detect, so it would be blind to its own best signal. |

**Recommended**: **A**. C is self-defeating for an audit tool: it would compare Smith
against its own intentions rather than against reality.

**Answer**: **A** (recommendation accepted) — parse the **installed** `~/.claude/settings.json` as the source of expectation, refresh on `ConfigChange`, and intersect with a small applicability table (e.g. `lint-on-save` is only expected after a Write/Edit; `security-guard-bash` only on Bash). If settings are unreadable or unparseable, absence detection is **disabled with a visible notice in the UI** — never silently degraded and never guessed.

Option C (derive from the repo's `settings/smith-settings-fragment.json`) was rejected as self-defeating: it compares Smith against its own intentions rather than against reality, making the tool blind to exactly the drift it exists to detect. This session produced a live instance — `hooks/pricing.json` is present in the repo but never installed (see Q2) — where a repo-derived expectation would have reported everything healthy.

> **Corollary:** the gap between the repo fragment and installed settings is itself a first-class divergence class worth surfacing ("Smith ships this hook, your settings don't wire it"), distinct from "wired but never fired".

---

## Q7: `scripts/uninstall.sh` lists 11 of 20 hooks — un-orphan the rest?

**Context**: `uninstall.sh`'s `SMITH_HOOKS` array names 11 hooks; the repo ships 20. The
other nine are left behind on uninstall. This feature adds `activity-emitter.sh`, so it
must touch that array regardless.

**Question**: Fix the other nine while in the file?

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | Add all missing hooks while editing the array | Uninstall becomes correct. A few lines, in a file already being modified. Slightly widens the diff beyond the feature's remit. |
| B | Add only `activity-emitter.sh` | Minimal diff, strictly scoped. Leaves a known bug in a file this feature demonstrably had open. |

**Recommended**: **A**. It is a one-line-per-hook fix in a file already in the diff, and
leaving nine orphans behind after editing the array next to them is hard to justify.

**Answer**: **A** (recommendation accepted) — populate `SMITH_HOOKS` in `scripts/uninstall.sh` with the full set of hooks the repo ships, not just `activity-emitter.sh`. The array currently names 11 of 20, orphaning nine on uninstall.

> **Build-phase requirement:** derive the list from the actual contents of `hooks/` at implementation time rather than transcribing the count stated here, and add a flat `tests/*.test.sh` assertion that every `hooks/*.sh` shipped by the repo appears in `SMITH_HOOKS` — otherwise this same drift silently returns the next time a hook is added. Note `scripts/install.sh:138` also hardcodes the string "Copy 9 hooks", which is a third stale count in the same pair of files; fix it while there.

---

## Q8: `smith-bugfix/SKILL.md:101` documents the marker-collision rule incorrectly

**Context**: That line is the only documentation of `create-active-workflow.sh`'s exit-3
collision, and its advice — pick a new slug — is wrong: the marker is keyed on **branch**,
not slug, so changing the slug does not avoid the collision. The planner relied on this
behavior for the nesting design (Q6 of research) and found the doc misleading.

**Question**: Fix the doc in this feature, or file separately?

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | File separately as a bugfix | Keeps this feature's diff free of workflow-skill edits, consistent with the settled decision to leave those skills alone. The wrong advice stays live in the meantime. |
| B | Fix the one line here | Trivially small and factually correct. But it edits a workflow skill, which the settled stamping decision deliberately ruled out — even though this is a comment, not behavior. |

**Recommended**: **A**. The settled boundary is worth holding precisely because this
feature observes those skills; editing them muddies what is being measured. A one-line
doc bugfix is cheap to file.

**Answer**: **A** (recommendation accepted) — file separately; do **not** edit `skills/smith-bugfix/SKILL.md` in this feature. The settled boundary against touching the four workflow skills is held deliberately: this feature *observes* those skills, so editing them changes the behavior being measured.

The defect to file: `skills/smith-bugfix/SKILL.md:101` advises picking a new slug on an exit-3 marker collision, but `create-active-workflow.sh` keys the marker on **branch** (`<safe-branch>.yaml`), not slug — so changing the slug does not avoid the collision. It is the only documentation of the exit-3 path.

> **Action:** capture via `/smith-bank` during this workflow so it is not lost, alongside the UTC clock-normalization item filed from Q5.

---

## Q9: Run `/smith-index` on this repo?

**Context**: `.smith/index/` does not exist here. `/smith-navigate` returned the
"Manifest not initialized" sentinel during Phase 0, so exploration fell back to
whole-codebase grep, and the planner ran four parallel passes over ~25 files for facts a
manifest would have answered in one lookup.

It is also directly relevant to the feature: the dashboard's vault panel reports **index
freshness**, and with no index that panel has nothing to show on its own primary project.

**Question**: Build the manifest?

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | Run `/smith-index` separately, after this feature merges | Keeps this workflow focused. Future features get cheap reuse detection. The index-freshness panel has real data to display. |
| B | Run it now, before build | The build phase gets manifest-assisted reuse detection immediately. Adds an indexing run to the critical path. |
| C | Skip it | Nothing changes. Reuse detection stays grep-based and the index panel renders empty on this repo. |

**Recommended**: **A**. It is genuinely useful but unrelated to this feature's correctness,
and it should not sit on the critical path.

**Answer**: **A** — run `/smith-index` on this repo **after the build merges**, not on the critical path. User condition: only if the index is not pushed to the public repo.

**Condition verified — satisfied structurally, not by care.** `.gitignore:2` is a blanket `.smith/` ("Smith runtime state (never commit)") and the file contains **zero negation (`!`) lines**, so nothing under `.smith/` can be staged. Confirmed empirically: `git ls-files .smith/` returns 0 tracked files. `ATTCKDigital/smith` is PUBLIC, and the index stays local regardless.

> **Contradiction noted for follow-up (not fixed here):** `.gitignore` lines 41-66 contain a `smith-gitignore-policy` block declaring `.smith/index/manifest.md`, the `.meta` describe layer, `vault/ledger/`, `vault/bank/`, `vault/agents/` and `vault/sessions/*.md` as "COMMITTED (shared with the team)". With no negations, the blanket ignore at line 2 silently wins. Consequence: **`/smith-sync` is a permanent no-op in this repo** — it runs automatically at the end of every smith-new / smith-bugfix / smith-debug, runs `git add .smith/`, stages nothing, and reports nothing to sync. Most likely deliberate (the policy block is the template for consumer projects; this public source repo opts out), but the override is undocumented in the file. Worth an explanatory comment at line 2 at minimum.

> **Related:** `specs/` is likewise ignored at `.gitignore:5` as "Internal decision logs", which is why features 53-59 migrated from `specs/<n>-<slug>/` to `.specify/systems/<system>/features/<n>-<slug>/`. This feature follows the current convention.
