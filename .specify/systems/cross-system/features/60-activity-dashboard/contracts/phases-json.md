# Contract: `scripts/activity/phases.json` and its sync test

The phase chain is **data, not code** (FR-15/G10). Adding a phase to a workflow
means editing this file, and a forgotten edit fails the test suite rather than
silently rendering a stale stepper (FR-16/SC-3).

Schema and invariants are in `data-model.md` §3. This file is the **seeded
content**, the **title-normalization rules** the sync test applies, and the
**extraction contract** it uses.

---

## §1 — Seeded content

Every `(number, title)` pair below was extracted from the SKILL.md on disk in
this worktree at `ed4b113`, with line numbers, then normalized per §3.

### `smith-new` — 7 phases, `##`, keyword `Phase`

| # | Title | Heading, verbatim | Line |
|---|---|---|---|
| 0 | Pre-Change Exploration | `## Phase 0: Pre-Change Exploration (Conditional)` | 65 |
| 1 | Worktree Creation & Setup | `## Phase 1: Worktree Creation & Setup` | 95 |
| 2 | Requirements Conversation | `## Phase 2: Requirements Conversation` | 150 |
| 3 | Spec Generation | `## Phase 3: Spec Generation (Subagent — in Worktree)` | 175 |
| 4 | Plan Generation | `## Phase 4: Plan Generation (Subagent — in Worktree)` | 222 |
| 5 | Questions Gate | `## Phase 5: Questions Gate (MANDATORY STOP — in Worktree)` | 285 |
| 6 | Update Plan, Then Build or Queue | `## Phase 6: Update Plan, Then Build or Queue (in Worktree)` | 383 |

`mandatory_stop: true` on **5**. `handoff: ["smith-build"]` on **6**.

### `smith-bugfix` — 9 phases, `##`, keyword `Phase`. Starts at 1, no Phase 0

| # | Title | Heading, verbatim | Line |
|---|---|---|---|
| 1 | Worktree Setup | `## Phase 1: Worktree Setup` | 78 |
| 2 | Spec Cross-Reference | `## Phase 2: Spec Cross-Reference` | 129 |
| 3 | Implement the Fix | `## Phase 3: Implement the Fix` | 165 |
| 3.5 | Update .meta Descriptions for Touched Methods | ``## Phase 3.5: Update `.meta` Descriptions for Touched Methods`` | 188 |
| 4 | Docker Rebuild | `## Phase 4: Docker Rebuild (if applicable)` | 270 |
| 5 | Run Tests | `## Phase 5: Run Tests` | 287 |
| 6 | Update Specs & Changelog | `## Phase 6: Update Specs & Changelog` | 351 |
| 7 | Commit, Push & Merge | `## Phase 7: Commit, Push & Merge` | 364 |
| 8 | Post-Merge Rebuild & Summary | `## Phase 8: Post-Merge Rebuild & Summary` | 434 |

Phase 3.5's `match` MUST be workflow-qualified — see §2.

### `smith-debug` — 8 phases, `##`, keyword `Phase`

| # | Title | Heading, verbatim | Line |
|---|---|---|---|
| 0 | Activate Workflow Tracking | `## Phase 0: Activate Workflow Tracking` | 90 |
| 1 | Symptom Capture | `## Phase 1: Symptom Capture (Interactive if needed)` | 114 |
| 2 | System Detection | `## Phase 2: System Detection` | 143 |
| 3 | Automated Triage | `## Phase 3: Automated Triage (Parallel Sub-agents)` | 162 |
| 4 | Diagnosis Synthesis | `## Phase 4: Diagnosis Synthesis` | 231 |
| 5 | Write Debug Report | `## Phase 5: Write Debug Report` | 245 |
| 5.5 | Update .meta Descriptions for Touched Methods | ``## Phase 5.5: Update `.meta` Descriptions for Touched Methods (Conditional)`` | 296 |
| 6 | Decision Gate | `## Phase 6: Decision Gate` | 327 |

`mandatory_stop: true` on **6**. `handoff: ["smith-bugfix"]` on **6**.

### `smith-build` — 11 phases, `##`, keyword `Phase`

| # | Title | Heading, verbatim | Line |
|---|---|---|---|
| 0 | Context Discovery | `## Phase 0: Context Discovery` | 57 |
| 1 | Task Generation | `## Phase 1: Task Generation (Subagent)` | 125 |
| 2 | Implementation | `## Phase 2: Implementation (Subagent per Phase)` | 162 |
| 3 | Testing | `## Phase 3: Testing (Subagent)` | 225 |
| 3.5 | Clean Code Review Pass | `## Phase 3.5: Clean Code Review Pass` | 451 |
| 3.6 | Security Review Pass | `## Phase 3.6: Security Review Pass` | 527 |
| 3.7 | Supply-Chain Review Pass | `## Phase 3.7: Supply-Chain Review Pass` | 625 |
| 4 | Spec Updates | `## Phase 4: Spec Updates (Subagent)` | 714 |
| 5 | Commit, Push & Merge | `## Phase 5: Commit, Push & Merge` | 761 |
| 6 | Service Rebuild | `## Phase 6: Service Rebuild` | 1255 |
| 7 | Release Notes & Summary | `## Phase 7: Release Notes & Summary` | 1282 |

Three consecutive fractional phases. A numeric sort must treat `3.7 < 4` — the
reason `number` is a string compared as a decimal (`data-model.md` §3).

### `smith-finish` — 9 steps, `###`, keyword `Step`

| # | Title | Heading, verbatim | Line |
|---|---|---|---|
| 1 | Inventory | `### Step 1: Inventory — Assess Current State` | 22 |
| 1.5 | Activate Workflow Tracking | `### Step 1.5: Activate Workflow Tracking` | 69 |
| 2 | Commit | `### Step 2: Commit` | 91 |
| 3 | Push | `### Step 3: Push` | 116 |
| 4 | Spec Updates | `### Step 4: Spec Updates` | 124 |
| 5 | PR & Merge | `### Step 5: PR & Merge` | 168 |
| 6 | Verify Clean State | `### Step 6: Verify Clean State` | 199 |
| 6.5 | Clear Workflow Tracking | `### Step 6.5: Clear Workflow Tracking` | 228 |
| 7 | Final Report | `### Step 7: Final Report` | 240 |

`"heading_level": 3, "heading_keyword": "Step"` for this workflow only.

Included even though `smith-finish` is not an accepted `--workflow` value for
`create-active-workflow.sh` — it does not use the helper at all. It hand-writes
`finish-<safe-branch>.yaml` with `workflow: smith-finish`
(`skills/smith-finish/SKILL.md:76-84`), so it IS marker-resolvable.
`research.md` §Q1 has the full derivation and the four marker-shape
differences.

---

## §2 — `match` patterns

`match` is an ordered list of case-insensitive substrings tried against signal
text (a `Subagent invoked:` description, a skill-event heading, a
`workflow-start` stamp). First hit wins.

**The one real collision:** `smith-bugfix` 3.5 and `smith-debug` 5.5 share the
title *"Update `.meta` Descriptions for Touched Methods"* exactly. Both are
therefore workflow-qualified:

```json
{"id":"smith-bugfix:3.5","number":"3.5",
 "title":"Update .meta Descriptions for Touched Methods",
 "match":["bugfix .meta", "Phase 3.5"], "mandatory_stop":false}

{"id":"smith-debug:5.5","number":"5.5",
 "title":"Update .meta Descriptions for Touched Methods",
 "match":["debug .meta", "Phase 5.5"], "mandatory_stop":false}
```

`data-model.md` §3 invariant 3 asserts no two phases in different chains share
an identical `match` pattern, so this collision cannot silently reappear when
a sixth workflow is mapped.

Two further `match` conventions:

- **A phase whose title is a common English fragment gets a numbered
  alternative.** `smith-finish` 2 is `Commit`, which appears in
  `smith-bugfix` 7 (`Commit, Push & Merge`) and `smith-build` 5. Its `match`
  is `["Step 2", "smith-finish commit"]`, never bare `"Commit"`.
- **`smith-new` 0's `match` includes `"smith-explore"`**, because Phase 0 is
  the one phase in any chain that is itself a skill invocation
  (`/smith-explore`, and conditional at that).

---

## §3 — Title normalization (the sync contract)

FR-16 requires the extracted headings to match `phases.json` "exactly — same
set, same order, same numbers". Taken literally against the raw headings that
is impossible: `## Phase 0: Pre-Change Exploration (Conditional)` is not the
string `Pre-Change Exploration`. The contract is therefore defined as **the
normalized form**, applied identically to both sides before comparison.

Applied to the raw heading text after the `<Keyword> <number>: ` prefix:

1. Remove all backtick characters.
   `` Update `.meta` Descriptions `` → `Update .meta Descriptions`
2. Remove **one** trailing parenthesized group and any whitespace before it.
   `Docker Rebuild (if applicable)` → `Docker Rebuild`
   `Symptom Capture (Interactive if needed)` → `Symptom Capture`
   Only one, and only trailing — an interior `(...)` is content, not a
   qualifier.
3. Remove a trailing ` — <rest>` em-dash clause (U+2014, space-delimited).
   `Inventory — Assess Current State` → `Inventory`
4. Collapse runs of whitespace to one space; strip.
5. Compare **case-sensitively**. A case change in a heading is a real edit and
   should fail the test.

`&` is preserved verbatim (`Worktree Creation & Setup`). Titles legitimately
contain `&`, `.`, `,` and `-`; the normalizer removes none of them.

These five rules live in ONE function, `normalize_phase_title()`, in
`scripts/activity/phases.py`, and the test imports it rather than
reimplementing it. If normalization and comparison could drift apart, the
sync test would be testing the wrong thing.

---

## §4 — Extraction contract (FR-16 / SC-3)

The sync test reads each workflow's `source`, `heading_level` and
`heading_keyword` from `phases.json` itself and extracts with:

```
^#{<heading_level>} *<heading_keyword> +(?P<number>[0-9]+(?:\.[0-9]+)?) *: *(?P<title>.+?)\s*$
```

Three requirements that are not optional:

1. **Fence-awareness.** `skills/smith-finish/SKILL.md:174` and `:177` are
   `## Summary` and `## Test plan`, sitting **inside a fenced bash block**,
   inside a `gh pr create --body` heredoc. The `(Phase|Step)` keyword filter
   happens to exclude those two today, but the extractor tracks ```` ``` ````
   fence state and ignores everything inside a fence regardless. A future
   heredoc containing `## Phase 9: …` must not be picked up.
2. **Exact heading level.** `smith-finish` uses `###`; the other four use
   `##`. Anchoring to `^## ` misses all nine `smith-finish` steps; a loose
   `^#{2,3}` pulls in unrelated `###` subsections from the other four.
   Reading the level from the data file is what keeps both correct.
3. **Decimal numbers.** `3.5`, `3.6`, `3.7`, `5.5`, `1.5`, `6.5` all occur.
   Integer parsing loses them silently.

### What the test asserts (SC-3)

For each of the five mapped workflows:

| Assertion | Fails when a phase is… |
|---|---|
| extracted `numbers` == `phases.json` `numbers`, same order | added, removed, renumbered, reordered |
| extracted normalized `titles` == `phases.json` `titles` | renamed |
| counts match: 7 / 9 / 8 / 11 / 9 | added or removed |
| every `source` file exists and is readable | a SKILL.md is moved or renamed |

Plus the four structural invariants from `data-model.md` §3 (unique ids,
increasing numbers, no duplicate `match` across chains, valid `handoff`
targets).

The test lives in the flat `tests/smith-activity.test.sh` so it runs in CI —
`.github/workflows/test-install.yml:58` loops `for t in tests/*.test.sh` and
nothing else. A test in `tests/hooks/` or a `test_*.py` gates nothing today
(D-8/FR-54). It drives the Python assertions via
`python3 -m unittest tests.activity.test_phases` from inside that wrapper; see
`plan.md` §Test strategy for why the wrapper, not the Python file, is the
gate.
