---
feature: 54-clean-code-review-pass
primary_system: cross-system
branch: 54-clean-code-review-pass
status: planned
---

# Implementation Plan: Clean Code Review Pass for Generated Code

## Technical Context

- **Repo**: Smith skills distribution (this repo). No application
  runtime — deliverables are markdown skill prose
  (`skills/smith-build/SKILL.md`, `skills/smith-bugfix/SKILL.md`) plus a
  `CHANGELOG.md` entry. No build step, no package manager dependency
  changes.
- **Languages**: markdown (skill prose) with a handful of already-existing
  embedded bash snippets being extended, not new bash tooling (see Test
  Strategy — this feature adds far less shell surface than it might look
  like, per `research.md` §4's finding that the review pass's findings are
  judgment-based, not scan-based).
- **No `.specify/scripts/setup-plan.sh`, no `constitution.md`, no
  `.smith/index/` manifest exist in this repo** — this plan was produced by
  direct file reads (cited throughout `research.md`), not by a scaffolding
  script or manifest navigator. (`.specify/scripts/bash/get-base-branch.sh`
  and `.specify/scripts/bash/clear-active-workflow.sh`, referenced
  throughout `smith-build`/`smith-bugfix` SKILL.md prose, are consumer-
  project-install-time artifacts copied from `skills/smith/scripts/` by
  `/smith` init — they describe the convention a CONSUMING project has, not
  a path that exists in this distribution repo itself. This matches the
  same observation already recorded in feature 53's own `plan.md`.)
- **Primary references**: `research.md` (all resolved anchors, cited
  file:line) and `data-model.md` (findings contract, `/tmp` file format,
  decision table, bounded-loop state) in this same feature folder.

## Constitution Gates

**N/A — no `constitution.md` or `.specify/memory/constitution.md` exists in
this repo, so there are no constitution-derived gates to check.**
(Clean-architecture and file-size discipline are instead enforced via this
plan's own Clean-Architecture Requirements section below, using
`skills/smith-clean-code/SKILL.md` as rubric — the same substitution
feature 53's plan.md already used.)

## Architecture Summary

One new phase in `smith-build/SKILL.md` (`## Phase 3.5: Clean Code Review
Pass`, inserted between the existing Phase 3 and Phase 4 — see
`research.md` §1/§2 for the exact line anchor and naming justification),
plus one PR-body template addition in the same file's existing §5.4, plus
a checklist-parity text expansion in `smith-bugfix/SKILL.md`'s existing
Phase 3, plus a `CHANGELOG.md` entry. No new files. No code (this is a
prose-only feature per SC-5's scope boundary — `get-base-branch.sh`,
`workflow-gate`, and `workflow-summary` scripts are never touched, so
their existing tests have nothing to regress against).

Phase 3.5's internal shape (spec FR-1..FR-18, `data-model.md` §1-§5):

1. **Invoke the review subagent** — same `WORKTREE_PATH`/`BASE_BRANCH`
   threading Phase 4/Phase 5 already use (research.md §1;
   `smith-build/SKILL.md:256-260` for the exact `BASE_BRANCH=$(...)`
   pattern to repeat). Rubric delivery: the subagent Reads
   `skills/smith-clean-code/SKILL.md` (worktree copy first,
   `~/.claude/skills/smith-clean-code/SKILL.md` installed fallback),
   targeting "## Review Process", "## Decision Rules", and "## What You
   Should Avoid" by HEADING, not line number. Review model: **Sonnet**
   (auto-fix judgment calls exceed the repo's Haiku-classification
   precedent). Both resolved at the questions gate (Q1/Q2) — see the
   updated "Exact file-by-file change list" below.
2. **Apply eligible auto-fixes** per `data-model.md` §3's decision table.
   `.meta` coverage for these edits is NOT proactively written by Phase
   3.5 itself (Q6, resolved: rely on existing layered coverage, not new
   machinery) — see the updated Reuse-before-create bullet below for how
   coverage is actually provided.
3. **Bounded re-test**: exactly one full Phase 3 re-run (3.1→3.2→3.3) iff
   `fixes_applied > 0` (`data-model.md` §4; FR-11/FR-12); a failing
   re-test resolves via Phase 3.3's OWN existing bounded-attempts behavior
   (research.md §3; FR-14) — Phase 3.5 adds no second retry loop.
4. **Write remaining findings** to
   `/tmp/smith-build-clean-code-findings.txt` (`data-model.md` §2) —
   populated by the subagent's own judgment, not a deterministic scan
   (research.md §4's key structural difference from §5.3/§5.3.1).
5. **Phase 4 proceeds** immediately after (US-1's last line; FR-1's
   ordering), so §5.3/§5.3.1's later `git diff $BASE_BRANCH` snapshots
   always see the post-fix state — no separate re-scan needed (FR-18,
   trivially true because those scans diff against a ref, not a point-in-
   time snapshot; research.md §1 also notes the single-commit payoff of
   this ordering).

## CLEAN-ARCHITECTURE REQUIREMENTS (mandatory)

Rubric: `skills/smith-clean-code/SKILL.md` (Review Process §398-430,
Decision Rules §487-501) — referenced here as the standard the new prose
itself is held to (this plan's edits should themselves be small, clearly
scoped, and non-duplicative), not restated.

### Reuse-before-create (exact components reused, not reinvented)

- **§5.3/§5.3.1's scan→`/tmp` file→conditional-PR-section mechanics**
  (`smith-build/SKILL.md:317-512`, research.md §4) — reused for the
  file-handoff and PR-template mechanics only; the scanning step itself
  has no deterministic equivalent to reuse (research.md §4's structural
  note).
- **Phase 3.3's existing bounded-attempts test-failure handling**
  (`smith-build/SKILL.md:246-250`, research.md §3) — reused verbatim by
  reference for FR-14; Phase 3.5 introduces no new retry budget.
- **FR-9's `.meta` coverage — resolved as "rely on existing layered
  coverage," not a new proactive procedure** (Q6). No `.meta`-write step
  is added to Phase 3.5 itself. For `smith-new`-launched builds, the
  per-edit `.meta` instruction already in `smith-new/SKILL.md:465-474`
  covers the build subagent's Write/Edit calls generally — auto-fix edits
  included, with no separate carve-out needed. For standalone
  `smith-build` runs, auto-fix edits fall back to the existing passive
  §5.3.1 Description Coverage Warnings scan, same as ordinary Phase 2
  implementation edits already do — no new machinery, narrower scope than
  the Option B considered at the spec stage (which would have imported
  `smith-bugfix/SKILL.md:189-259`'s proactive Task-spawn procedure into
  Phase 3.5).
- **smith-research's Phase 6a adversarial-verification subagent shape**
  (`smith-research/SKILL.md:155-172`, research.md §9) — reused as the
  PROMPT-STRUCTURE precedent for the review subagent: decompose into
  atomic findings, default to the conservative verdict (flag) when
  unclear, record a structured verdict per item rather than free prose.
- **Phase 4/Phase 5's `BASE_BRANCH=$(.specify/scripts/bash/get-base-
  branch.sh)` pattern** (`smith-build/SKILL.md:258,325,516`) — reused
  verbatim for Phase 3.5's own diff, per FR-3 (never a hardcoded or
  inferred ref).
- **The "N.5 inserted phase" naming convention** established by
  `smith-bugfix/SKILL.md:179` and referenced by name from
  `smith-debug/SKILL.md` and `smith-new/SKILL.md` (research.md §2) — reused
  for this feature's own phase name/number, avoiding a renumber of
  smith-build's Phase 4 through 7 and every existing cross-reference to
  them.
- **Phase 2's own clean-code vocabulary** (`smith-build/SKILL.md:200-223`,
  research.md §5) — reused as the "tenet violated" terminology so a
  finding reads as verification of what Phase 2 already asked for.

### File Size Policy

`smith-build/SKILL.md` is already 747 lines — well past the 300-line soft
target this repo applies to its OWN skill files in spirit (the numeric
convention itself governs source code per `smith-build/SKILL.md:219-222`;
applying it here as a discipline check on this plan's own edit size, not a
literal gate on markdown files, which this repo does not enforce a hard
line-count ceiling on). Per this task's own instruction: **keep the new
Phase 3.5 section compact — reference `data-model.md`'s contracts (§1-§5)
rather than restating field-by-field detail in `smith-build/SKILL.md`
prose.** Target: comparable in length to §5.3.1's own outer wrapper text
(NOT its ~150-line embedded Python parser — Phase 3.5 has no equivalent
embedded parser to write, per research.md §4), i.e., roughly 40-70 lines of
new prose for the Phase 3.5 section itself, plus a short PR-body template
addition (~10 lines, matching §5.3/§5.3.1's own template blocks at
`:524-545`).

No new files are created by this feature, so there is no new-file
decomposition question to resolve.

---

## Exact file-by-file change list

### NEW

None.

### MODIFIED

| File | Change |
|---|---|
| `skills/smith-build/SKILL.md` | **(1)** New `## Phase 3.5: Clean Code Review Pass` section inserted between the current line 250 (end of §3.3) and line 252 (`## Phase 4:` heading) — see Architecture Summary above for its 5-step internal shape. Rubric-delivery (Q1: subagent Reads `skills/smith-clean-code/SKILL.md` by heading, worktree copy first / installed fallback), review-model (Q2: Sonnet), and severity-filter logic in the `/tmp`-file-writing instruction (Q3: Medium+ listed individually, Low findings folded into a one-line "+ N low-severity notes" count) are now RESOLVED — write the section text directly from these answers; no placeholders remain. **(2)** §5.4 PR-body template gains a `## Clean Code Review` conditional section (`data-model.md` §5, encoding the Q3 severity-threshold format), positioned after the existing Description Coverage Warnings block and before `## Release notes`. **(3)** No change to §5.3/§5.3.1 themselves (FR-18 is satisfied by ordering alone, research.md §1/Architecture Summary step 5 — no re-scan mechanism to add). |
| `skills/smith-bugfix/SKILL.md` | Phase 3, step 2 (lines 168-172) expands from the single constitution-pointer sentence into the inline six-bullet checklist named in FR-19 (research.md §6) — small single-responsibility units; intention-revealing names; guard clauses over deep nesting; separation of concerns; no dead code or duplicated logic; reuse existing components over recreating them. Step 3's "Do NOT" list (173-177) is untouched (FR-20). **Q4 resolved: No** — an automated review-and-auto-fix pass for smith-bugfix is deferred, not planned, as part of this feature; no further change to this file beyond the checklist expansion. Promotion path: revisit once the `smith-build`-side Phase 3.5 pass has real mileage. |
| `skills/smith-implement/SKILL.md` | Line 180's single-line "Clean architecture" bullet ("follow the constitution's **Clean Architecture Policy** — small single-responsibility units, reuse existing components over duplicating, and keep files within the File Size Policy (split large ones rather than growing monolithic files). Honor the file structure defined in plan.md.") is replaced with the same six-bullet checklist block used for `smith-bugfix` (FR-19's bullet list; FR-21) — small single-responsibility units; intention-revealing names; guard clauses over deep nesting; separation of concerns; no dead code or duplicated logic; reuse existing components over recreating them. The original line's File Size Policy and "Honor the file structure defined in plan.md" content is preserved, folded into the checklist's file-structure bullet rather than dropped. **Q5 resolved: Yes** (research.md D5, Option A) — same-cycle, not deferred. |
| `CHANGELOG.md` | New `[Unreleased]` → `### Added` entry (following the existing entry style/tone — see `research.md`'s and this plan's own citations for structure), added LAST, after the other three files' changes are final, so it accurately describes what shipped rather than what was planned (mirrors feature 53's own phased-ordering rule for its CHANGELOG entry). |

No other files are touched. `skills/smith-clean-code/SKILL.md` is
explicitly NOT edited (NFR-5/OOS-3) — it is read-only rubric input.
`skills/smith-debug/SKILL.md` is explicitly NOT touched (OOS-1).
`skills/smith-new/SKILL.md` is explicitly NOT touched (OOS-2).

---

## Phased task ordering

1. **`smith-build` review-pass section + PR template.** New Phase 3.5 and
   the §5.4 template addition ship together — a PR-body section that could
   reference a phase that doesn't exist yet (or vice versa) would be a
   half-shipped, internally inconsistent file. This phase is the one that
   actually closes the spec's Problem Statement gap (post-hoc verification
   didn't exist at all before this feature); it does not depend on
   anything in phase 2 or 3 below.
2. **`smith-bugfix` and `smith-implement` checklist parity.** Independent
   of phase 1 (different files, no shared state) — sequenced second only
   because the task's own phased-ordering instruction places it there, and
   because it's simpler to verify in isolation (SC-4's direct
   bullet-for-bullet comparison; the same comparison extends to
   `smith-implement` per Q5/FR-21) once phase 1's canonical bullet list (in
   `smith-build/SKILL.md`) is already final and won't shift under it.
3. **`CHANGELOG.md` + cross-refs.** Written last, after phases 1-2 are
   final, so the entry accurately describes what shipped (mirrors feature
   53's own "docs/changelog close-out... written last" phased-ordering
   rule, `.specify/systems/cross-system/features/53-mcp-browser-access/
   plan.md:195-197`). "Cross-refs" here means: confirm no OTHER skill file
   (smith-new, smith-debug, smith-index, etc.) references
   `smith-build`'s Phase numbering in a way this insertion would break —
   research.md §2 already found `smith-debug`/`smith-new` reference
   `smith-bugfix`'s "Phase 3.5" by name, not `smith-build`'s, so there is
   no existing cross-reference into `smith-build`'s Phase 4-7 by number
   from another file to fix; this step is a verification grep (see Test
   Strategy), not an expected-to-find-something step.

## Test strategy

This feature changes only markdown prose (plus, per research.md §4, a
near-trivial amount of shell — a single non-empty-file check, not a new
parser). Verification is therefore **prose consistency + minimal shell
smoke**, not an application test suite:

- **Prose consistency greps** (run after all three files are edited):
  - `grep -n "Phase 3.5" skills/smith-build/SKILL.md` — confirms the new
    heading exists exactly once and nothing else in the file already
    claimed "3.4"/"3.5"/"3.6" before this edit (research.md §2 confirmed
    none did, pre-edit; this re-confirms post-edit).
  - `grep -n "## Phase 4:" skills/smith-build/SKILL.md` — confirms Phase 4
    still immediately follows the new section (no accidental content
    swallowed between them).
  - `grep -c "Clean Code Review" skills/smith-build/SKILL.md` — expect 2
    matches (the Phase 3.5 heading/prose and the §5.4 template section
    name) at minimum, confirming both halves of the feature landed.
  - `grep -n "smith-build-clean-code-findings.txt" skills/smith-build/
    SKILL.md` — expect the filename to appear both where it's written
    (Phase 3.5) and where it's read (§5.4 template), confirming the
    handoff file name wasn't typo'd between the two spots.
  - **SC-4's literal check** — a direct bullet-for-bullet comparison of
    `smith-build/SKILL.md`'s Phase 2 checklist bullets (research.md §5)
    against `smith-bugfix/SKILL.md`'s new Phase 3 checklist bullets
    (research.md §6): extract each file's six-bullet block and diff them
    (allowing for the deliberate FR-20 omissions — "Reuse over
    duplication" and "Keep files small" standalone paragraphs are NOT
    expected to appear in `smith-bugfix`) to confirm the SHARED six bullets
    are verbatim-identical, not paraphrased.
  - `grep -n "^### Added" -A 3 CHANGELOG.md | head` — confirms the new
    entry landed under `[Unreleased]` → `### Added`, matching the existing
    entries' placement.
- **Bash+zsh smoke (NFR-2)** — IF any shell snippet is added (expected:
  just the `[ -s /tmp/smith-build-clean-code-findings.txt ]`-style
  non-empty check, per `data-model.md` §2/research.md §4's finding that
  there's no parser to write here): run the snippet under both
  interpreters against a scratch empty file and a scratch non-empty file
  and confirm identical branch behavior, mirroring the ledger convention
  feature 53's plan.md cites ("project ledger REQUIRES smoke-testing shell
  snippets under both shells").
  ```bash
  bash -c '[ -s /tmp/nonexistent-scratch-file ] && echo yes || echo no'
  zsh  -c '[ -s /tmp/nonexistent-scratch-file ] && echo yes || echo no'
  ```
- **No markerless constraint applies here** (worth stating explicitly,
  since the task's own framing raised it): `smith-sync`'s "markerless-safe
  snippets" rule (`smith-sync/SKILL.md:179-182`) exists because `smith-
  sync` runs AFTER a workflow's active-workflow marker is already cleared.
  Phase 3.5 runs INSIDE `smith-build`, between Phase 3 and Phase 4, while
  the marker created in Phase 0 step 0 is still active (it isn't cleared
  until Phase 7). So any snippet added here can use ordinary `>`/`>>`
  redirection exactly like §5.3/§5.3.1 already do — no
  stderr-only-redirection restriction applies.
- **No new application test suite** — this feature has no application-
  layer code; `tests/get-base-branch.test.sh`,
  `tests/workflow-gate-redirect.test.sh`, and
  `tests/workflow-summary-session.test.sh` (SC-5) are expected to pass
  UNMODIFIED, since none of the three changed files are scripts those
  tests exercise.

## Rollout notes

- Distributed via the standard `/smith-update` path (SKILL.md prose is
  refreshed the same way every other bundled skill is) — no bespoke
  install machinery, consistent with every prior prose-only PR cited in
  `CHANGELOG.md`.
- The review pass runs on EVERY `smith-build` invocation from the moment
  this ships — there is no opt-in flag in any FR/NFR. Teams that dislike
  the added latency/cost have no documented way to disable it per the
  current spec (worth the gate's awareness, though not itself one of the
  five named deferred decisions — flagged here rather than invented as a
  sixth D-item, since no FR hints at a kill-switch).
- `skills/smith-implement/SKILL.md` IS touched — Q5 resolved Yes (see
  file-by-file list above) — consistent with the user's own
  agency-package-scope memory note being a DIFFERENT, unrelated boundary
  (that note concerns `smith-design`/`smith-timesheet`, not
  `smith-implement`; mentioned only to be explicit that this plan did not
  conflate the two).

---

## Spec-plan tensions surfaced (feed the questions gate)

None of these are contradictions within spec.md itself (the spec's own
checklist already verified internal consistency) — they are gaps between
the spec's assumptions and what this research pass found in the actual
files, plus the five items spec.md itself already flagged as deferred.

1. **Phase numbering: spec names phases functionally, not numerically —
   resolved here by evidence, not deferred.** spec.md's FR-1 says "strictly
   after Phase 3... strictly before Phase 4" without naming a section
   number for the new phase. This plan resolves it to `## Phase 3.5:
   Clean Code Review Pass` based on the cross-file "N.5" convention
   (research.md §2) — flagged here only because the task instructions that
   generated this plan used "Phase 3.6" as their own placeholder example;
   this plan diverges from that placeholder with cited evidence. Not a
   spec ambiguity, and not one of the five A-6 deferred items — included
   here for the report, not for the gate to re-litigate, unless the gate
   disagrees with the naming evidence itself.

2. **Insertion-point resolution vs. the exploration report.** The
   exploration report's WARNING #1/#2 (ordering + staleness) are BOTH
   already resolved by spec.md's FR-1/FR-18 — the spec itself settled
   this before this plan was written. Noted here only as confirmation
   that no open architectural question remains on ordering (research.md
   §1) — nothing for the gate to decide on this point.

3. **FR-9's "already applied to implementation edits" premise — resolved by
   Q6, not by a new `.meta`-write step.** The premise was accurate only for
   `smith-bugfix`, not `smith-build` (research.md's "Additional finding"
   section, full detail there); this was raised as a candidate for a new
   proactive `.meta`-write step scoped to auto-fix edits (Option B). The
   questions gate instead chose Option A — rely on existing layered
   coverage (`smith-new`'s per-edit instruction for `smith-new`-launched
   builds; the passive §5.3.1 flag for standalone runs) — so
   `skills/smith-build/SKILL.md` does NOT gain a new `.meta`-write step at
   all. FR-9 is reworded accordingly (spec.md); this plan's Architecture
   Summary and Reuse-before-create sections are updated to match.

4. **D1-D5 (the spec's own named deferred decisions, A-6) — now
   ANSWERED.** All five resolved at the questions gate (`questions.md`):
   rubric delivery (Q1 = Read-by-heading), review model (Q2 = Sonnet),
   severity threshold (Q3 = Medium+ individually, Low as a count), bugfix
   lightweight pass (Q4 = No, checklist parity only), smith-implement
   parity (Q5 = Yes). This plan's file-by-file list and Phase 3.5 prose no
   longer carry `PENDING GATE` placeholders; every spot they touched is
   written directly from the answers above.
