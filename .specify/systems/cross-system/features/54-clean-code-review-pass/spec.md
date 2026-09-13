---
feature: 54-clean-code-review-pass
primary_system: cross-system
also_affects: []
branch: 54-clean-code-review-pass
created: 2026-09-13
status: in-progress
answers_applied: 2026-09-13
---

# Clean-Code Review Pass for Generated Code

## Overview

PR #49 taught three code-generating Smith workflows to *apply* smith-clean-code's
tenets while they generate code: `smith-new`'s Phase 4 planning block,
`smith-build`'s Phase 2 inline clean-code checklist (SKILL.md:200-223), and
`smith-bugfix`'s Phase 3 constitution pointer (SKILL.md:163-172). All three are
advisory prose consulted *during* generation — none of them verify the diff
*after* it exists. Nothing in Smith today re-checks a finished branch against
the rubric before it ships.

This feature closes that gap by adding a post-hoc **Clean Code Review Pass**
to `smith-build`: a subagent that evaluates the full branch diff against
smith-clean-code's Review Process and Decision Rules, safely auto-fixes what
it safely can, and — for everything it can't or shouldn't fix — surfaces a
"Clean Code Review" section in the PR body. It never blocks the PR.
`smith-bugfix` receives a smaller, parallel change: its Phase 3 gains the same
inline checklist `smith-build` already shows implementers, closing the
prose-parity gap without adding an automated review pass to the lighter
workflow.

**Terminology used throughout this spec:**
- **Review pass** — the new smith-build subagent step that evaluates
  `git diff $BASE_BRANCH` against smith-clean-code's Review Process (severity
  classification) and Decision Rules (auto-fix eligibility).
- **Finding** — one rubric violation identified by the review pass, tagged
  Critical, High, Medium, or Low per smith-clean-code's Review Process
  (SKILL.md:398-430).
- **Auto-fix** — a direct edit the review pass applies to resolve a finding,
  permitted only when the fix is both safe/unambiguous under smith-clean-code's
  Decision Rules (SKILL.md:487-501) and behavior-preserving.
- **Flagged finding** — a finding the review pass does NOT auto-fix (fix
  safety unclear, or a Critical finding whose only fix would change behavior),
  reported in the PR body instead.
- **Bounded loop** — this feature's fixed-length cycle: one review, at most
  one batch of auto-fixes, at most one full Phase 3 re-run. No step repeats.
- **`$BASE_BRANCH`** — the branch resolved by
  `.specify/scripts/bash/get-base-branch.sh`, already used throughout
  smith-build/smith-bugfix for diffing and PR targeting.

## Problem Statement

Smith's clean-code guidance is entirely generation-time: it shapes what an
implementing subagent writes, but nothing re-reads the diff afterward to
confirm the guidance was actually followed. A build can drift from the
rubric — deep nesting slipped past a rushed implementation, a duplicated
helper reintroduced, a god-function that should have stayed small — and
nothing in the pipeline notices before the PR opens. Smith already runs two
deterministic, non-blocking post-hoc scans in this same slot (File Size
Warnings and Description Coverage Warnings, both in smith-build's Phase 5),
proving the flag-never-block pattern works here; clean-code has no equivalent.

An exploration pass ahead of this feature
(`.smith/vault/explore/explore-2026-09-13-clean-code-review-pass.md`)
confirmed there is no prior decision to reconcile: the CHANGELOG's reference
to a PR #49 decisions file (`specs/questions/smith-new-clean-code.md`) points
to a file that was never distributed (`specs/` is gitignored), and the
recovered PR #49 commit content shows the generation-time-only scope was
never-considered-vs-rejected for post-hoc review — it simply wasn't in scope
yet. The road is clear to add it now.

`smith-bugfix` compounds the gap in a smaller way: its Phase 3 only points at
the constitution's Clean Architecture Policy by reference, while
`smith-build`'s Phase 2 spells out the same policy as an explicit inline
checklist. That asymmetry predates this feature and is closed here as a
lighter, parity-only change — `smith-bugfix` does not gain an automated
review pass, only the same checklist text `smith-build` already shows.

## User Scenarios

### US-1 — Auto-fixable findings get fixed and re-tested (primary flow)
```gherkin
Given a smith-build run has just passed Phase 3 (Testing)
Given the branch diff vs $BASE_BRANCH contains findings that are safe and
    behavior-preserving to fix per smith-clean-code's Decision Rules
When the Clean Code Review Pass runs
Then it applies those fixes directly to the working tree
And it updates the `.meta` touched-methods layer for every edited
    .py/.js/.jsx/.ts/.tsx file
And it runs exactly one full re-run of Phase 3 (3.1, 3.2, 3.3) afterward
And, if every finding was fixed, the PR body carries no "Clean Code Review"
    section
And Phase 4 (Spec Updates) proceeds only after this pass completes
```

### US-2 — Clean diff short-circuits the pass
```gherkin
Given a smith-build run has just passed Phase 3 (Testing)
Given the branch diff vs $BASE_BRANCH contains zero rubric violations
When the Clean Code Review Pass runs
Then no auto-fix is applied
And Phase 3 is NOT re-run
And the PR body carries no "Clean Code Review" section
And the workflow proceeds to Phase 4 with no added latency beyond the
    review itself
```

### US-3 — Fix-safety is unclear: flag, never fix
```gherkin
Given the branch diff contains a finding whose safe-fix status is unclear
    under smith-clean-code's Decision Rules
When the Clean Code Review Pass evaluates it
Then it does NOT attempt to auto-fix the finding
And the finding is recorded as a flagged finding for the PR body
```

### US-4 — Critical finding requiring a behavior change: always flagged
```gherkin
Given the branch diff contains a Critical-severity finding
Given the only available fix for that finding would change program behavior
When the Clean Code Review Pass evaluates it
Then it does NOT auto-fix the finding under any configuration
And the finding is recorded as a flagged finding for the PR body, labeled
    with its Critical severity
```

### US-5 — Remaining findings populate the PR body, and the PR still opens
```gherkin
Given one or more flagged findings remain after auto-fix (if any auto-fix ran)
When smith-build reaches Step 5.4 (Create PR)
Then the PR body includes a "Clean Code Review" section listing each
    remaining finding's severity, location, and description
And the section uses flag-never-block wording mirrored from the existing
    File Size Warnings section
And the PR opens unconditionally, exactly as it does today
```

### US-6 — Auto-fix applied but the single re-test fails
```gherkin
Given the Clean Code Review Pass applied one or more auto-fixes
When the resulting single full Phase 3 re-run fails, even after Phase 3's
    own existing bounded internal retry (§3.3)
Then the workflow applies Phase 3.3's existing failure-handling behavior
    (log the failure, continue, flag for manual attention)
And the Clean Code Review Pass does NOT re-review the diff
And the Clean Code Review Pass does NOT apply a second batch of fixes
And the PR still opens
```

### US-7 — 5.3/5.3.1 scans see the post-fix diff, never a stale one
```gherkin
Given the Clean Code Review Pass ran (with or without auto-fixes) before
    Phase 5
When the existing File Size Warnings (§5.3) and Description Coverage
    Warnings (§5.3.1) scans run later in Phase 5
Then their `git diff $BASE_BRANCH`-derived snapshots reflect any auto-fix
    edits already applied
And no separate re-scan or staleness-avoidance step is needed
```

### US-8 — smith-bugfix Phase 3 shows the same checklist, no automated pass
```gherkin
Given a smith-bugfix run reaches Phase 3 (Implement the Fix)
When the implementer reads the Phase 3 instructions
Then it sees the same inline clean-code checklist bullets smith-build's
    Phase 2 shows (not only a pointer to the constitution)
And smith-bugfix does NOT invoke an automated review-and-auto-fix subagent
    as part of this feature
And the existing "Do NOT: refactor surrounding code / add features beyond
    the fix / modify unrelated files / add unnecessary abstractions"
    constraints are unchanged
```

## Functional Requirements

### Insertion point & invocation (smith-build)

- **FR-1**: smith-build MUST run a new Clean Code Review Pass strictly after
  Phase 3 (Testing) has passed and strictly before Phase 4 (Spec Updates)
  begins.
- **FR-2**: The Clean Code Review Pass MUST only run once Phase 3 has reached
  a passing state; it is gated on Phase 3's success as an ordering
  precondition, not a blocking condition on Phase 4 (see NFR-3 —
  flag-never-block still governs the PR outcome, not this pass's own
  invocation).
- **FR-3**: The review subagent MUST be invoked with the same
  `WORKTREE_PATH`/`BASE_BRANCH` context threading already used by other
  smith-build phases (the `BASE_BRANCH=$(.specify/scripts/bash/get-base-branch.sh)`
  pattern used in Phase 4 and Phase 5), and MUST diff against `$BASE_BRANCH`
  — never a hardcoded or inferred ref.

### Review rubric & findings

- **FR-4**: The review subagent MUST evaluate the full branch diff vs
  `$BASE_BRANCH` against smith-clean-code's Review Process (severity
  classification: Critical/High/Medium/Low, SKILL.md:398-430) and Decision
  Rules (SKILL.md:487-501).
- **FR-5**: The review subagent MUST receive this rubric content by Reading
  the shipped `skills/smith-clean-code/SKILL.md` (worktree copy), falling
  back to `~/.claude/skills/smith-clean-code/SKILL.md` (installed copy) when
  the worktree copy is unavailable — because workflow subagents cannot load
  skills via the Skill tool. The subagent MUST target the "## Review
  Process", "## Decision Rules", and "## What You Should Avoid" sections by
  HEADING, not by line number, since line numbers drift as the skill file is
  edited. (Resolved at the questions gate, Q1 — see questions.md.)
- **FR-6**: Each finding MUST be tagged with exactly one severity
  (Critical/High/Medium/Low) per the Review Process's classification.

### Auto-fix policy

- **FR-7**: A finding MAY be auto-fixed only when the fix is both (a) safe
  and unambiguous per the Decision Rules' "if the answer is unclear, prefer
  the smaller and safer change" guidance, and (b) behavior-preserving. Any
  finding whose fix-safety is unclear MUST be flagged, never auto-fixed.
- **FR-8**: A Critical finding whose only available fix would change program
  behavior MUST NEVER be auto-fixed; it MUST always be flagged, regardless of
  configuration.
- **FR-9**: Every auto-fix edit to a `.py`, `.js`, `.jsx`, `.ts`, or `.tsx`
  file MUST have its `.meta` touched-methods description coverage handled by
  the existing layered mechanisms — no new machinery is introduced by this
  pass. For builds launched via `smith-new`, the per-edit `.meta` update
  instruction that already applies to every source edit in that workflow
  (`smith-new/SKILL.md:465-474`) covers review-pass auto-fix edits too. For
  standalone `smith-build` runs (invoked outside `smith-new`), auto-fix
  edits fall back to the existing passive §5.3.1 Description Coverage
  Warnings scan, exactly as regular Phase 2 implementation edits already do.
  (Resolved at the questions gate, Q6 — see questions.md.)
- **FR-10**: Auto-fix edits MUST NOT require any corresponding change to
  `tasks.md` — fixes produced by this pass are treated as polish, not
  tracked tasks.

### Bounded re-test loop

- **FR-11**: If one or more auto-fixes were applied, smith-build MUST run
  exactly one full re-run of Phase 3 (3.1 Unit Tests, 3.2 Playwright E2E,
  3.3 Failure Handling) in its entirety after the fixes are applied.
- **FR-12**: If zero auto-fixes were applied, Phase 3 MUST NOT be re-run.
- **FR-13**: The Clean Code Review Pass MUST run at most once per build.
  Findings MUST NOT be re-reviewed after fixes are applied, and the pass MUST
  NOT be invoked a second time regardless of the re-test's outcome. The bound
  is exactly: one review → at most one fix-application batch → at most one
  re-test, with no repetition of any of the three steps.
- **FR-14**: If the single Phase 3 re-run fails — even after Phase 3's own
  existing bounded internal retry (§3.3, up to 3 attempts per failing test) —
  the workflow MUST proceed using Phase 3.3's existing failure-handling
  behavior (log the failure, continue, flag for manual attention in the
  release notes). The Clean Code Review Pass MUST NOT introduce any
  additional retry, re-fix, or re-review loop beyond that existing behavior.

### PR-body reporting

- **FR-15**: Every finding that is neither auto-fixed nor otherwise resolved
  MUST be recorded to a scratch file, following the same
  scan → `/tmp` file → conditionally-included pattern already used by the
  File Size Warnings (§5.3) and Description Coverage Warnings (§5.3.1)
  sections.
- **FR-16**: When that scratch file is non-empty, the PR body template
  (§5.4) MUST gain a "Clean Code Review" section. Medium, High, and Critical
  findings are each listed individually (severity, location, description);
  Low-severity findings are NOT listed individually — they are folded into a
  single one-line count ("+ N low-severity notes") appended after the
  individually-listed findings. When the file is empty, the section MUST be
  omitted entirely — matching the existing two sections' omit-when-empty
  behavior. (Severity threshold resolved at the questions gate, Q3 — see
  questions.md.)
- **FR-17**: The "Clean Code Review" section MUST carry flag-never-block
  wording mirrored verbatim in spirit from the existing §5.3 text ("This is a
  FLAG, never a blocker. Always proceed with PR creation.") — the PR MUST
  always open regardless of how many findings remain or their severity.
- **FR-18**: Because the Clean Code Review Pass runs before Phase 5, the
  existing §5.3 and §5.3.1 scans' `git diff $BASE_BRANCH`-derived snapshots
  MUST always observe the diff as it stands after any auto-fix — no separate
  re-scan, cache-invalidation, or staleness-avoidance mechanism is required
  or permitted to be added for this purpose.

### smith-bugfix parity

- **FR-19**: smith-bugfix Phase 3 ("Implement the Fix") MUST be updated to
  include, written directly into the skill text, the same inline clean-code
  checklist bullets smith-build Phase 2 uses (small single-responsibility
  units; intention-revealing names; guard clauses over deep nesting;
  separation of concerns; no dead code or duplicated logic; reuse existing
  components over recreating them) — replacing the current
  constitution-pointer-only treatment (SKILL.md:163-172).
- **FR-20**: The smith-bugfix Phase 3 checklist addition MUST preserve PR
  #49's lighter-for-bugfix scope: it MUST NOT introduce an automated
  review-and-auto-fix pass into smith-bugfix, MUST NOT duplicate
  smith-build's separate "Reuse over duplication" / "Keep files small" prose
  blocks, and MUST NOT relax smith-bugfix's existing "Do NOT: refactor
  surrounding code / add features beyond the fix / modify unrelated files /
  add unnecessary abstractions" constraints.

### smith-implement parity

- **FR-21**: `skills/smith-implement/SKILL.md` MUST be updated to include,
  written directly into the skill text, the same inline six-bullet
  clean-code checklist used for smith-build Phase 2 and smith-bugfix Phase 3
  (small single-responsibility units; intention-revealing names; guard
  clauses over deep nesting; separation of concerns; no dead code or
  duplicated logic; reuse existing components over recreating them) —
  replacing the current single-line "Clean architecture" bullet that only
  points at the constitution's Clean Architecture Policy. (Resolved at the
  questions gate, Q5 — see questions.md.)

## Non-Functional Requirements

- **NFR-1**: The Clean Code Review Pass and its auto-fix/re-test cycle MUST
  run without any user interaction of any kind — no prompts, confirmations,
  or pauses — consistent with smith-build's "ALL phases run without user
  interaction" rule.
- **NFR-2**: All shell snippets added or modified in
  `skills/smith-build/SKILL.md` and `skills/smith-bugfix/SKILL.md` for this
  feature MUST run correctly under both `bash` and `zsh` (no bash-only array
  syntax, no bare unquoted globs), matching the repo's existing shell-content
  convention.
- **NFR-3**: The flag-never-block invariant MUST hold under every
  configuration — no setting, flag, finding severity, or failure mode
  introduced by this feature may cause PR creation to be withheld, delayed,
  or gated on Clean Code Review findings.
- **NFR-4**: The review-fix-retest cycle's step count MUST be deterministic
  and bounded independent of how many findings are found: exactly one
  review, at most one fix-application batch, at most one Phase 3 re-run —
  never a variable-length or unbounded loop.
- **NFR-5**: This feature MUST NOT modify `skills/smith-clean-code/SKILL.md`
  itself; the review subagent consumes its Review Process and Decision Rules
  content read-only (whether inlined or Read).

## Out of Scope

- **OOS-1 — smith-debug.** A read-only diagnostic workflow that generates no
  code diff; there is nothing for a clean-code review pass to evaluate.
  Unaffected by this feature.
- **OOS-2 — smith-new's planning-side clean-code integration.** The Phase 4
  block PR #49 already added is generation-time guidance and already exists;
  this feature addresses the post-hoc verification gap only and does not
  modify smith-new.
- **OOS-3 — Modifying `skills/smith-clean-code/SKILL.md` itself.** This
  feature only consumes its Review Process and Decision Rules content; the
  skill file is not edited by this feature (NFR-5).
- **OOS-4 — Auto-fixing Critical findings that require a behavior change.**
  These are always flagged, never auto-applied, under any configuration
  (FR-8).
- **OOS-5 — Any blocking or gating semantics.** The review pass and its
  findings can never withhold, delay, or fail a build or PR — flag-never-block
  is inviolable (NFR-3).

## Assumptions

- **A-1**: PR #49 integrated smith-clean-code tenets at generation time only
  (smith-new Phase 4, smith-build Phase 2 checklist, smith-bugfix Phase 3
  pointer); this feature adds the first post-hoc verification layer without
  altering those generation-time integrations.
- **A-2**: The exploration pass
  (`.smith/vault/explore/explore-2026-09-13-clean-code-review-pass.md`) found
  no prior evidence that a post-hoc review pass was considered and rejected —
  the CHANGELOG's reference to an undistributed decisions file
  (`specs/questions/smith-new-clean-code.md`) is a pre-existing, unrelated
  documentation gap this feature does not need to resolve or work around.
- **A-3**: All existing fix-loop conventions in the repo are bounded (e.g.,
  3 attempts per test failure, single-pass reviews elsewhere); this feature's
  one-review / one-fix-batch / one-retest bound is consistent with that
  convention, not a new pattern requiring separate justification.
- **A-4**: The `.meta` touched-methods convention (stable 16-char-hex method
  ids, diffed against `.smith/index/files/<file>.meta`) already governs how
  implementation edits update description coverage; this feature reuses that
  convention for auto-fix edits rather than introducing a parallel mechanism.
- **A-5**: `WORKTREE_PATH`/`BASE_BRANCH` threading and the
  `get-base-branch.sh` resolution helper are already established conventions
  available to any smith-build/smith-bugfix phase; this feature does not
  introduce new context-threading machinery.
- **A-6 — Resolved at questions gate.** The following decisions were
  intentionally left open by this spec and have since been resolved at this
  feature's questions gate (`questions.md`, Status: ANSWERED); recorded here
  for the reasoning trail:
  1. Rubric delivery mechanism to the review subagent — RESOLVED: the
     subagent Reads `skills/smith-clean-code/SKILL.md` (worktree copy first,
     `~/.claude/skills/smith-clean-code/SKILL.md` installed fallback),
     targeting the named sections by heading (Q1, FR-5).
  2. Review model choice — RESOLVED: Sonnet (Q2).
  3. The severity threshold governing which remaining findings are included
     in the "Clean Code Review" PR-body section — RESOLVED: Medium and above
     listed individually, Low findings folded into a one-line count (Q3,
     FR-16).
  4. Whether smith-bugfix should additionally receive a lightweight,
     diff-scoped automated review pass beyond the checklist parity required
     by FR-19/FR-20 — RESOLVED: no; checklist parity only. Deferred, not
     planned; a promotion path stays open once the build-side pass has real
     mileage (Q4).
  5. Whether smith-implement should receive the same inline-checklist parity
     treatment given to smith-bugfix — RESOLVED: yes (Q5, FR-21).

## Success Criteria

- **SC-1**: A smith-build run whose diff violates the smith-clean-code
  rubric always ships in exactly one of two states — either the violations
  are auto-fixed and Phase 3 has been re-run green, or the PR body carries a
  populated "Clean Code Review" section — never neither, never silently.
- **SC-2**: A smith-build run whose diff has zero rubric violations produces
  no "Clean Code Review" PR-body section and triggers no Phase 3 re-run.
- **SC-3**: Across all Clean Code Review Pass executions, zero prompts,
  confirmations, or pauses are presented to the user.
- **SC-4**: Every smith-bugfix run's Phase 3 text includes the same inline
  clean-code checklist bullets present in smith-build Phase 2, verifiable by
  direct comparison of the two skill files.
- **SC-5**: Existing automated tests exercising scripts these two skills
  depend on (`tests/get-base-branch.test.sh`, `tests/workflow-gate-redirect.test.sh`,
  `tests/workflow-summary-session.test.sh`) continue to pass unmodified after
  this feature ships.
- **SC-6**: No smith-build run is ever blocked, delayed, or fails PR creation
  solely due to Clean Code Review findings, across every tested
  configuration (auto-fix applied, findings flagged, mixed, or none).
