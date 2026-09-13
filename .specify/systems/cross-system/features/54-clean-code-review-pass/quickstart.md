# Quickstart: Clean Code Review Pass for Generated Code

Verification walkthroughs for each user scenario (US-1..US-8). These are
manual/observational checks against a real `/smith-build` run (this
feature has no application test suite to run instead — see `plan.md`'s
Test Strategy). Each scenario names the spec item(s) it verifies and notes
where its exact observed behavior depends on a still-open gate answer
(D1-D5, `research.md`).

## Prerequisites

- A feature branch with `spec.md`/`plan.md`/`tasks.md`/answered
  `questions.md` ready for `/smith-build`, where the implementation
  (Phase 2) is complete and Phase 3 (Testing) has just passed.
- The branch diff vs `$BASE_BRANCH` contains at least one clean-code rubric
  violation for Scenarios 1, 3, 4, 5, 6 below; zero violations for Scenario
  2.

## Scenario 1 — Dirty diff, some findings auto-fixed, one re-test, PR section lists the rest (US-1 + US-5 / SC-1)

**Given** a smith-build run has just passed Phase 3, and the diff contains
a mix of findings — some AUTO-FIX eligible per `data-model.md` §3 (e.g., a
guard-clause opportunity that's unambiguously behavior-preserving) and some
that are not (e.g., a Medium-severity duplication finding whose safest fix
is unclear).

**When** Phase 3.5 runs.

**Then**:
1. The eligible findings are applied directly to the working tree as edits.
2. `.meta` touched-methods coverage for every `.py`/`.js`/`.jsx`/`.ts`/`.tsx`
   file touched by an auto-fix is handled entirely by the existing layered
   mechanisms, not by a new proactive write inside Phase 3.5 itself (FR-9,
   resolved via questions.md Q6, Option A — reject Option B): for builds
   launched via `smith-new`, that workflow's existing per-edit `.meta`
   instruction (`smith-new/SKILL.md:465-474`) already covers auto-fix edits
   like any other Write/Edit; for standalone `smith-build` runs, auto-fix
   edits fall back to the existing passive §5.3.1 Description Coverage
   Warnings scan, exactly like ordinary Phase 2 implementation edits already
   do. Verify via `.smith/index/files/<file>.meta` gaining/updating entries
   for the auto-fixed method ids through whichever of those two paths
   applies — not via `smith-bugfix`'s unrelated Phase 3.5 procedure, which
   this pass explicitly does not import.
3. Exactly one full Phase 3 re-run (3.1→3.2→3.3) executes (FR-11) — check
   the vault session log for exactly one "Subagent invoked" block for this
   re-run, not zero, not two.
4. `/tmp/smith-build-clean-code-findings.txt` contains one line per
   NON-auto-fixed finding (`data-model.md` §2 format) — the auto-fixed
   ones do not appear.
5. The PR body's `## Clean Code Review` section lists exactly the
   remaining (non-auto-fixed) findings, with the flag-never-block sentence
   (FR-17), and the PR opens regardless.
6. Phase 4 (Spec Updates) starts only after all of the above completes
   (FR-1's ordering — verify via session-log timestamps: the Phase 3.5
   "completed" entries precede the first Phase 4 subagent invocation).

**Gate answers now resolved**: rubric delivery (Q1: heading-anchored Read
of `skills/smith-clean-code/SKILL.md`) and review model (Q2: Sonnet) don't
change the decision table in step 1 itself, but do shape review
QUALITY/consistency; which findings appear individually in step 4/5's list
is governed by Q3 — Medium and above are listed individually, Low findings
are folded into a single "+ N low-severity notes" line instead.

## Scenario 2 — Clean diff short-circuits the pass (US-2 / SC-2)

**Given** a smith-build run has just passed Phase 3, and the diff vs
`$BASE_BRANCH` contains zero rubric violations.

**When** Phase 3.5 runs.

**Then**:
1. No auto-fix is applied — the working tree is unchanged by Phase 3.5.
2. Phase 3 is NOT re-run (verify: zero additional "Subagent invoked" Phase
   3 entries in the session log beyond the original Phase 3 run).
3. `/tmp/smith-build-clean-code-findings.txt` is empty or absent.
4. The PR body carries no `## Clean Code Review` section at all (FR-16's
   omit-when-empty branch).
5. The workflow proceeds to Phase 4 with no added latency beyond the
   single review-subagent call itself (US-2's literal wording) — there is
   no additional network/tool round-trip beyond the one review invocation.

## Scenario 3 — Fix-safety unclear: flag, never fix (US-3 / FR-7)

**Given** the diff contains a finding — e.g., a large function that could
plausibly be split several different ways with no single obviously-correct
decomposition — where `data-model.md` §1's `Fix-safety` field would read
`unclear`.

**When** Phase 3.5 evaluates it.

**Then**:
1. No edit is made for this finding (`Fix applied: false` in the internal
   contract).
2. The finding appears in `/tmp/smith-build-clean-code-findings.txt` and
   therefore in the PR body's `## Clean Code Review` section — listed
   individually if it is Medium severity or above, or folded into the
   one-line "+ N low-severity notes" count if it is Low severity (Q3,
   resolved).
3. `Auto-fix eligible: false` per `data-model.md` §3's decision table
   (Behavior-preserving may be true or unknown here — Fix-safety=unclear
   alone is sufficient to force FLAG, per FR-7(a)).

## Scenario 4 — Critical finding requiring a behavior change: always flagged (US-4 / FR-8)

**Given** the diff contains a Critical-severity finding (e.g., a
broken-behavior bug the review subagent notices as a side effect of
reviewing the diff) whose only available fix would change program
behavior.

**When** Phase 3.5 evaluates it.

**Then**:
1. It is NEVER auto-fixed, under any configuration — `data-model.md` §3's
   decision table row 1 applies unconditionally (Behavior-preserving=false
   ⟹ FLAG, and FR-8 reinforces this specifically for the Critical case so
   there is no ambiguity even if some future config toggle loosened the
   general rule).
2. It is recorded in the PR body's `## Clean Code Review` section labeled
   with Critical severity, listed individually — Q3's resolved Medium+
   threshold always includes Critical findings, so this scenario's
   PR-body visibility was never in doubt regardless of how Q3 resolved,
   unlike Scenario 1/3's Medium/Low findings.
3. The PR still opens (NFR-3/OOS-5 — no severity, including Critical, ever
   blocks or delays PR creation).

## Scenario 5 — Auto-fix applied but the single re-test fails (US-6 / FR-14)

**Given** Phase 3.5 applied one or more auto-fixes, and the resulting
single full Phase 3 re-run fails even after Phase 3.3's own existing
3-attempts-per-failure budget is exhausted.

**When** this happens.

**Then**:
1. The workflow applies Phase 3.3's EXISTING failure-handling behavior
   verbatim: log the failure, continue, flag for manual attention in the
   release notes (`data-model.md` §4 — `retest_done` becomes `true`
   regardless of PASS/FAIL).
2. Phase 3.5 does NOT re-review the diff a second time.
3. Phase 3.5 does NOT apply a second batch of fixes.
4. The PR still opens (verify: `## Clean Code Review` section, if any
   findings remain unfixed, still renders; a separate release-notes flag
   for the failed re-test is independent of that section and does not
   suppress it).

## Scenario 6 — §5.3/§5.3.1 scans see the post-fix diff, never stale (US-7 / FR-18)

**Given** Phase 3.5 ran (with or without auto-fixes) before Phase 5.

**When** §5.3 (File-Size Scan) and §5.3.1 (Description Coverage Scan) run
later in Phase 5.

**Then**:
1. Their `git diff $BASE_BRANCH`-derived snapshots reflect any auto-fix
   edits already applied by Phase 3.5 (verify: a file whose line count
   crossed the 300-line threshold BECAUSE of an auto-fix edit — e.g., an
   extracted-helper auto-fix that split one file into a larger one plus a
   new import — is correctly flagged or not flagged by §5.3 based on its
   POST-fix line count, not its pre-fix one).
2. No separate re-scan or staleness-avoidance step exists anywhere in the
   diff (`plan.md`'s Architecture Summary step 5 — this is true by
   construction of the phase ordering, not by an added cache-invalidation
   mechanism, which FR-18 explicitly forbids adding).

## Scenario 7 — Bugfix checklist visibility, no automated pass (US-8 / SC-4)

**Given** a `smith-bugfix` run reaches Phase 3 ("Implement the Fix").

**When** the implementer (or a reader diffing the two SKILL.md files) reads
the Phase 3 instructions.

**Then**:
1. The same six inline clean-code checklist bullets `smith-build`'s Phase
   2 shows appear here too (not only the prior constitution-pointer
   sentence) — verify via the direct bullet-for-bullet comparison in
   `plan.md`'s Test Strategy section.
2. No automated review-and-auto-fix subagent is invoked anywhere in
   `smith-bugfix/SKILL.md` as part of THIS feature (FR-20) — grep
   `smith-bugfix/SKILL.md` for "Clean Code Review Pass" / "Phase 3.5:
   Clean Code" and confirm zero matches (its OWN, unrelated, pre-existing
   "Phase 3.5: Update `.meta` Descriptions" heading is expected and
   untouched).
3. The existing "Do NOT: refactor surrounding code / add features beyond
   the fix / modify unrelated files / add unnecessary abstractions"
   constraints (lines 173-177, research.md §6) are byte-for-byte unchanged
   — diff the pre- and post-feature versions of that specific block and
   confirm zero delta.

**Gate answer now resolved**: Q4 resolved No — smith-bugfix gets checklist
parity only; no automated review-and-auto-fix pass is added by this
feature (deferred, not planned; a promotion path stays open once the
`smith-build`-side Phase 3.5 pass has real mileage). Step 2's check
therefore holds as spec'd (FR-20) — there is no conditional shape to
resolve.

## Post-run cleanup

No new scratch state persists beyond a normal `smith-build`/`smith-bugfix`
run's existing cleanup (Phase 7 worktree removal, marker clearing) —
`/tmp/smith-build-clean-code-findings.txt` is ephemeral scratch output like
its two siblings (`/tmp/smith-build-oversized.txt`,
`/tmp/smith-build-coverage-misses.txt`) and is not itself cleaned up by any
existing step, matching those two files' own (lack of) cleanup handling.
