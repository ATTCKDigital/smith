# Specification Quality Checklist: 58-scheduled-audits

**Purpose**: Validate specification completeness before planning/implementation
**Created**: 2026-09-14
**Feature**: [spec.md](../spec.md)

## Content Quality
- [x] Focused on user value and business need (projects get unattended,
      recurring `/smith-audit` health checks with a real cadence, a
      workflow-gate hole closed, and cross-run drift visibility) rather
      than implementation mechanics
- [x] All mandatory sections completed (Overview, Problem Statement, User
      Scenarios, Functional Requirements, Non-Functional Requirements, Out
      of Scope, Assumptions, Success Criteria)
- [x] Written for reviewers, not just implementers — Overview defines
      "Scheduled audit run", "Subset", "Headless-safe subset", "Cadence",
      and "Maintenance marker" before they're used in requirements
- [x] Artifacts named (files/paths, phase/section numbers) only where the
      feature is inherently about specific integration points
      (`scheduler/smith-scheduler.sh`, `skills/smith-audit/SKILL.md`,
      `scripts/create-active-workflow.sh`'s `maintenance` type, `.smith/
      config.json`'s `scheduled_audits` key, `.smith/vault/.scheduled-
      audits-state.json`) — no HOW (exact bash internals beyond the named
      contracts, script line-by-line logic) leaks in beyond what the
      feature description itself specified

## Requirement Completeness
- [x] Zero `[NEEDS CLARIFICATION]` markers remain anywhere in spec.md
      (verified: `grep -c "NEEDS CLARIFICATION" spec.md` → 0)
- [x] Every FR (FR-1..FR-26) is independently testable — each names a
      concrete condition and an observable pass/fail outcome (a dispatch
      sent/skipped, a marker created/cleared, an invocation refused/
      accepted, a report section present/omitted, a config key present/
      absent, a file line present/absent)
- [x] No FR depends on a vague qualifier without a concrete rule attached
      (verified: `grep -niE "appropriately|as needed|reasonable|properly|
      sufficiently" spec.md` → no matches)
- [x] Success criteria (SC-1..SC-7) are measurable and technology-agnostic
      outcomes, each traceable to at least one FR: SC-1→FR-1/FR-5,
      SC-2→FR-2/FR-3, SC-3→FR-10, SC-4→FR-11/FR-12, SC-5→FR-14,
      SC-6→FR-15/FR-21/FR-22, SC-7→FR-18
- [x] All 6 user scenarios (US-1..US-6) are Gherkin Given/When/Then and
      cover: cadence-due dispatch, disabled/not-due skip, marker bootstrap
      with clearing on failure, `feature`-subset refusal, drift-block
      comparison against a prior report, and the first-ever-run
      no-drift-but-still-logged case
- [x] Edge cases identified: `scheduled_audits` key wholly absent (FR-2,
      same skip path as `enabled: false`), state file corrupt vs. absent
      (FR-4/FR-22, both treated identically), `--scheduled` without
      `--all`/a system identifier (FR-8, refused rather than falling
      through to the interactive prompt), a category present in only one
      of two compared reports (FR-14, "not compared" disclosure rather
      than a false 0), a dispatch failure mid-run (FR-6, logged and
      continues to the next project)
- [x] Scope is explicitly bounded — Out of Scope names all four excluded
      areas (OOS-1..OOS-4) with the structural reason each is excluded,
      plus an explicit "NOT out of scope" callout correcting a reader's
      likely assumption (the interactive-marker gap) inherited from the
      exploration report's own initial framing
- [x] Dependencies and assumptions identified (A-1..A-4), including the
      exploration's no-blocking-conflicts finding with independent
      re-verification (A-1), the `maintenance` catch-all reuse (A-2), the
      delegation-vs-scope-decision split for FR-18 (A-3), and the
      SAFE_VAULT_DIRS/gitignore-template discrimination between
      `audits-log.md` (no template change) and the state file (needs one)
      (A-4)

## Exploration Findings Traceability

Every finding from the pre-feature exploration
(`.smith/vault/explore/explore-2026-09-14-scheduled-audits.md`) is a
binding design constraint. Each is traced below to the FR(s)/NFR(s)/
Assumption(s) that encode it, AND to the specific on-disk evidence
independently re-verified while drafting this spec (none of the 6 required
correction) — none are left as unencoded narrative.

- [x] **Finding 1** (direct-dispatch mechanism, not `/smith-queue` — the
      queue pipeline is merge-oriented and wrong-shaped for a read-only
      audit) → **FR-1** (second, structurally separate scheduler loop),
      **FR-5** (direct `claude -p "/smith-audit..."` dispatch, no queue
      entry synthesized), **OOS-2** (`/smith-queue` explicitly untouched),
      **A-3**/`questions.md` Q1 (recommendation named and accepted).
      Re-verified: `skills/smith-queue/SKILL.md`'s "Scheduler invocation
      contract" table (worktree/build/PR/merge steps, skill-owned) vs.
      `skills/smith-audit/SKILL.md`'s "Key Rules" ("Never modify code
      during an audit — audits are read-only and produce reports only")
      — the shape mismatch is real, not asserted.
- [x] **Finding 2** (headless-safe default subset: five fixed categories +
      opt-ins; `--all` avoids the only prompt branch; `feature` always
      excluded) → **FR-8** (refuses rather than falling through to the
      prompt), **FR-9/FR-10** (subset validation + unconditional `feature`
      refusal), **FR-19** (five-item default `subsets` array), **A-3**/
      `questions.md` Q2. Re-verified: `skills/smith-audit/SKILL.md`'s
      "System Selection" section — empty `$ARGUMENTS` is the ONLY branch
      that prompts; `--all` and a system identifier both skip it, exactly
      as the finding claims.
- [x] **Finding 3** (gate gap: `workflow-gate.sh` denies without a marker;
      `/smith-audit` has zero marker handling; `create-active-workflow.sh`'s
      enum lacks `smith-audit` but has `maintenance`) → **FR-11/FR-12**
      (bootstrap via `maintenance`, cleared on every exit path), **FR-18**
      (scope widened to cover interactive invocations too — this feature's
      own decision, not the exploration's original framing), **A-2**
      (`maintenance` catch-all reused unchanged, no new enum value),
      **A-3**/`questions.md` Q3. Re-verified directly: `scripts/
      create-active-workflow.sh` lines 114-120 (the `case "$WORKFLOW" in`
      allowlist — confirmed no `smith-audit` entry, confirmed `maintenance`
      present), `skills/smith-audit/SKILL.md` read in full (confirmed zero
      Phase-0/marker-bootstrap content anywhere in the file).
- [x] **Finding 4** (report naming `<date>-scheduled-<name>.md`; drift
      block atop the report; rolling append to `audits-log.md`, already
      gate-exempt/committable, no template change needed for THAT file) →
      **FR-13** (filename-stem substitution), **FR-14/FR-15** (drift block,
      present/absent cases), **FR-16** (rolling log line format), **A-4**
      (the `audits-log.md` vs. state-file gitignore-template
      discrimination stated explicitly), **A-3**/`questions.md` Q4.
      Re-verified: `hooks/workflow-gate.sh` line 97
      (`SAFE_VAULT_DIRS=(sessions bank ledger queue agents todo reports
      index audits)` — `reports` present) AND `skills/smith-index/
      templates/.gitignore-smith-additions` (no `.smith/vault/reports/`
      line anywhere in its `IGNORED` section) — both confirm the finding's
      "no template change" claim for this specific file.
- [x] **Finding 5** (config `scheduled_audits` key with `enabled: false`
      MANDATORY; mutable state in a gitignored `.scheduled-audits-
      state.json`; ONE new gitignore-template line required for THAT
      file) → **FR-19** (exact config shape, `enabled: false` called out
      as mandatory), **FR-20** (three-site seeding), **FR-21/FR-22** (state
      file write-after-success + never-run treatment), **FR-23** (the one
      new gitignore-template line), **A-3**/`questions.md` Q5 and Q6 (the
      finding bundles two gate items — config default posture and
      state-storage shape — both traced separately in `questions.md`).
      Re-verified: current `.gitignore-smith-additions` `IGNORED` section
      lists `.current-session`/`.current-session-*`/
      `.warned-manifest-missing-*`/`.active-workflow`/`queue/`/`todo/`/
      `timesheets/`/`.smith/config/` — no existing line would already
      cover `.scheduled-audits-state.json`, confirming a new line really
      is required, not redundant.
- [x] **Finding 6** (doc drift: `docs/security-model.md` says the queue
      marker field is `"mode": "autonomous"`; the real field is
      `complexity:`, agreed by both the scheduler code and `docs/
      scheduler.md`) → **FR-25** (in-passing correction, bundled into the
      same edit as the new scheduled-audits security paragraph). Re-verified
      directly: `docs/security-model.md`'s "Scheduler Security" section
      (`` `"mode": "autonomous"` ``, confirmed stale) vs. `scheduler/
      smith-scheduler.sh` lines 125/128 (`COMPLEXITY=$(grep
      '^complexity:' ...)`, `if [ "$COMPLEXITY" != "autonomous" ]`) vs.
      `docs/scheduler.md` line 64 (already says `complexity: autonomous`
      correctly) vs. `skills/smith-queue/SKILL.md`'s "Scheduler invocation
      contract" table (`complexity: autonomous`, agrees with the code) —
      the finding's claim is accurate exactly as stated; no correction to
      the exploration's own wording was needed.

## Deferred-Decisions Traceability
- [x] Assumptions §A-3 lists all six items the exploration's own "Gate
      recommendations" line named (direct-dispatch mechanism, five-subset
      default, maintenance-marker bootstrap, report+rolling-log
      surfacing, `enabled: false`, state-file+gitignore line) as a
      "RESOLVED at questions gate (delegation)" reference into
      `questions.md`, each carrying its recommended-and-accepted
      resolution and the exploration finding backing it
- [x] The SEVENTH decision (FR-18, marker bootstrap covering interactive
      invocations) is explicitly NOT folded into the delegation trail —
      both `spec.md` and `questions.md` state plainly that this was a
      scope call this feature's task framing asked to be evaluated and
      decided directly, distinct from the six exploration-recommended
      items. This distinction is deliberate and checked here so a future
      reader doesn't mistake FR-18 for an eighth delegated answer with no
      corresponding `questions.md` entry.
- [x] Every one of the six delegated items has a corresponding FR/OOS that
      states the requirement concretely: FR-1/FR-5 (Q1), FR-8/FR-9/FR-10/
      FR-19 (Q2), FR-11/FR-12/A-2 (Q3), FR-13/FR-14/FR-15/FR-16/A-4 (Q4),
      FR-19 (Q5), FR-21/FR-22/FR-23 (Q6) — each traces back to `questions.md`'s
      named recommendation
- [x] No FR, NFR, or success criterion contradicts a resolved item's
      accepted status (verified: every `questions.md` item is phrased
      "Recommended: A" / "Answer: A (accepted via delegation)" with its
      rationale, and every corresponding FR states that exact outcome as
      unconditional, not conditional language)

## Out-of-Scope Explicitness
- [x] The `/smith-queue` exclusion names the structural reason (merge-
      oriented pipeline shape mismatch, not a bare "not doing this")
      (OOS-2)
- [x] The Linux-automation exclusion is stated as both a firm scope
      boundary (OOS-1) and cross-referenced to FR-24's actual
      documentation-only deliverable, so a reader doesn't expect a new
      cron installer that doesn't exist
- [x] The UX/SEO/feature-default exclusion is stated as both a firm FR
      (FR-10's unconditional `feature` refusal, OOS-3's restatement) and
      cross-referenced to the Overview's own "Headless-safe subset"
      definition, so a reader encountering either section independently
      gets the same rule
- [x] Notification infrastructure is named as explicitly excluded with the
      actual surfacing mechanisms named in its place (the rolling log and
      the report file itself), not merely absent from the FRs (OOS-4)
- [x] The "NOT out of scope" callout for the interactive-marker gap is
      itself a deliberate scope-explicitness device — most features' Out
      of Scope sections only list exclusions; this one additionally
      documents a scope WIDENING relative to the source exploration
      report, specifically so a reviewer comparing the two documents isn't
      confused into thinking the widening was an oversight

## Feature Readiness
- [x] Each of the six delivery areas maps to its own FR group: scheduler
      audits step → FR-1..FR-7; `/smith-audit` `--scheduled` mode →
      FR-8..FR-17; the interactive-marker scope decision → FR-18;
      configuration → FR-19..FR-20; state file → FR-21..FR-23;
      documentation → FR-24..FR-26
- [x] No FR, scenario, or success criterion contradicts another (verified:
      FR-2's "skip when disabled" and FR-3's "due when never-run" don't
      conflict, since FR-2's gate is checked strictly before FR-3's cadence
      math ever runs for a given project; FR-9's "unrecognized token
      refused" and FR-19's "subsets default to five known-good names"
      don't contradict, since FR-19 only constrains the SHIPPED DEFAULT
      value, not what a project may configure; FR-15's "omit drift section
      entirely" and FR-14's "always include when a prior report resolves"
      are the two complementary halves of one behavior, not a conflict)
- [x] Constraints supplied by the feature description (direct-dispatch
      mechanism, five-subset default, gate-gap marker fix, report+drift+
      log surfacing, `enabled: false`, state-file+gitignore line, the
      "evaluate and decide" instruction for the interactive-marker scope)
      are each present as FR-1/FR-5, FR-19, FR-11/FR-12, FR-13..FR-16,
      FR-19, FR-21..FR-23, and FR-18 respectively — none were dropped, and
      the one instruction that was explicitly a DECISION request (not a
      pre-answered gate item) is traceable to its own dedicated FR-18
      section with stated rationale, not buried inside another FR
- [x] Ready for planning: every FR is specific enough to size and
      sequence, and every FR has a corresponding user scenario or success
      criterion to verify against in `plan.md`

## Notes
- Verified against this feature's own `spec.md` in 1 iteration. The
  `[NEEDS CLARIFICATION]`-marker and vague-qualifier greps were run
  directly against the written file (not asserted from memory), and the
  FR/NFR/OOS/SC numbering was independently counted to confirm no gaps or
  duplicates before this checklist could be marked complete: 26 FRs
  (FR-1..FR-26, no gaps — FR-18 is a named scope-decision FR, not a
  renumbering artifact), 5 NFRs, 4 OOS items plus 1 explicit
  "NOT out of scope" callout, 7 SC items, 6 user scenarios.
- Unlike features 54-57, this feature's six delegated gate answers do NOT
  cover every non-trivial decision in the spec — FR-18 is a seventh,
  separately-sourced decision this feature's own task framing asked to be
  resolved directly rather than through the standing delegation. This
  checklist treats that as a feature of this spec's traceability (checked
  above under Deferred-Decisions Traceability), not a gap, since it is
  fully documented with its own rationale in both `spec.md` and
  `questions.md` rather than silently folded into the six-item trail.
- This feature spans two files that must change together (`scheduler/
  smith-scheduler.sh` and `skills/smith-audit/SKILL.md`) more tightly than
  any single-skill feature in this worktree so far — `plan.md`'s Phased
  Ordering section explicitly sequences `/smith-audit`'s changes before
  the scheduler's dispatch code for exactly this reason, and this
  checklist's Content Quality pass confirmed `spec.md` itself states that
  dependency in its own Technical-Context-adjacent Overview language
  rather than leaving it implicit until `plan.md`.
