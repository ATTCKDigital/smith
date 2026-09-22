# Specification Quality Checklist: 60-activity-dashboard

**Purpose**: Validate specification completeness before planning/implementation
**Created**: 2026-09-22
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] Focused on user value, not implementation mechanics (the Summary and
      Problem & Motivation both lead with the operator's own framing — "x-ray
      vision into the behind-the-scenes plumbing… a Smith activity audit for
      me" — and every tradeoff in the spec is justified against *audit*
      rather than *monitor*, including the two capabilities that framing
      forces: the trust hierarchy and absence detection)
- [x] All mandatory sections completed (Summary, Problem & Motivation, Goals,
      Non-Goals, User Scenarios & Testing with Edge Cases, Functional
      Requirements, Key Entities, Success Criteria, Assumptions, Out of
      Scope, Dependencies & Constraints — matching the recent cross-system
      house style of features 57 and 59 plus the Goals/Non-Goals/Key Entities
      structure of `specs/32-smith-research`)
- [x] Written for reviewers, not just implementers (a Terminology block in the
      Summary defines Daemon, Emitter, Ground-truth spine, Self-report,
      Divergence finding, Absence finding, Phase resolution, Phase map,
      Primary repo, Registered project, and Quota window BEFORE any of them
      is used in a requirement)
- [x] Named artifacts (file paths, function names, hook event names) appear
      only where the feature is inherently about those exact integration
      points — `hooks/workflow_summary_lib.py`'s `load_pricing()` /
      `match_family()` contract, `hooks/workflow-gate.sh`'s
      `SAFE_VAULT_DIRS`, `scripts/create-active-workflow.sh`,
      `scripts/lib/dedupehooks.jq`, `phases.json` — never as a substitute for
      stating the behavior
- [x] HOW decisions are confined to the constraints the feature description
      itself fixed (SSE not WebSockets, stdlib-only Python, loopback bind,
      `phases.json` as data); no algorithm, schema, or module decomposition
      is prescribed that `plan.md` should own

## Requirement Completeness

- [x] Zero `[NEEDS CLARIFICATION]` markers remain (verified: `grep -c "NEEDS
      CLARIFICATION" spec.md` → 0). Every ambiguity is either settled as a
      decision (OOS-1..OOS-7), recorded as an explicit assumption (A-1..A-9),
      or deferred to the Phase 4 questions file — none is left as a marker
- [x] Every FR is independently testable (FR-1..FR-56, no gaps — verified by
      extracting and sorting the numbers). Each names a concrete condition
      and an observable pass/fail outcome: an exit status, a byte count on
      stdout, a process count, a classification label, a rendered string, a
      finding count, a socket binding
- [x] No FR leans on a vague qualifier (verified: `grep -niE
      "appropriately|as needed|reasonable|properly|sufficiently" spec.md` →
      no matches). Where a number is genuinely approximate it is stated as
      such with its unit and its reason — the ~3 s git debounce (FR-31), the
      ~150-250 ms SSE coalescing window (FR-41), the 5-10 s **liveness**
      reconciler poll (FR-26 — rescoped at the questions gate from "drives the
      waiting-on-permission indicator" to "self-heals the live-session list",
      because the fields that drove the indicator do not exist), the ~1 s
      vault stat poll (FR-38), and the 90 s two-sided reconciliation window
      (FR-22)
- [x] Success criteria (SC-1..SC-21, no gaps) are measurable and each traces
      to at least one FR: SC-1→FR-9/11/17/18, SC-2→FR-14, SC-3→FR-16,
      SC-4→FR-40, SC-5→FR-22, SC-6→FR-23, SC-7→FR-28, SC-8→FR-30,
      SC-9→FR-2/FR-3, SC-10→FR-6, SC-11→FR-32/FR-33, SC-12→FR-35,
      SC-13→FR-45, SC-14→FR-48, SC-15→FR-4/FR-49, SC-16→FR-54,
      SC-17→FR-62/FR-34, SC-18→FR-63, SC-19→FR-57, SC-20→FR-59/FR-22,
      SC-21→FR-60/FR-61 — the last five added at the questions gate
- [x] All 10 user scenarios (US-1..US-10) are Gherkin Given/When/Then and are
      prioritized as independently testable slices: P1 covers the four
      properties without which the feature is not worth shipping — the phase
      stepper (US-1), divergence + absence findings (US-2), concurrent-workflow
      attribution (US-3), and the can-never-break-a-session guarantee (US-4);
      P2 covers daemon lifecycle (US-5), live sessions/subagents (US-6),
      worktree reality (US-7), and tokens/quota (US-8); P3 covers the vault
      panel (US-9) and the statusline/redaction pair (US-10)
- [x] Each user story carries an **Independent Test** statement describing how
      it can be verified in isolation — notably US-1, US-2, and US-3 are all
      verifiable by replaying fixtures through the resolver with no live
      daemon, which is what makes the headline capability testable at all
- [x] Edge cases identified and enumerated as their own section, each traced
      to the FR that governs it: daemon down, port taken (both sub-cases),
      stale pidfile (both sub-cases), missing `rate_limits`, unknown model id,
      malformed JSONL line, concurrent workflows, worktree deleted under a
      live marker, session dying without `SessionEnd`, a marker naming an
      unmapped workflow, the rubric-file-read-is-not-an-invocation trap, the
      `PostToolUse *` event storm, and a browser tab open across a daemon
      restart
- [x] Scope explicitly bounded — Non-Goals states what the product is not, and
      Out of Scope names seven excluded areas (OOS-1..OOS-7) each with the
      reason it is excluded rather than a bare "not doing this"
- [x] Dependencies and assumptions identified (A-1..A-9, D-1..D-10),
      separating what is *verified* (the phase headings, the
      `SAFE_VAULT_DIRS` list, the `maintenance` workflow value, the CI test
      glob) from what is *assumed* (hook event availability, the latency
      budget, `claude agents --json` availability)

## Audit-Framing Traceability

The feature's primary framing — audit, not status monitor — is not left as
narrative. Each of its two forced consequences is traced to requirements.

- [x] **Trust hierarchy** (hook events are ground truth; vault content is
      Smith self-reporting) → **FR-21** states the hierarchy as a rule
      ("where a conflict exists, the hook-derived value is displayed, with
      the self-reported value shown beside it as the divergence"), **FR-22**
      enumerates the three divergence classes that must be surfaced, and the
      Terminology block defines "ground-truth spine" and "self-report" so the
      distinction is unambiguous everywhere it is invoked. The rationale is
      restated independently in OOS-1 as the reason phase *stamping* is
      deferred — a stamper inherits the failure mode of the skill it lives
      in, which is precisely the failure mode the audit exists to catch
- [x] **Absence detection** → **FR-23** requires absence findings for a
      skipped phase, an un-hit mandatory gate, and a hook that never fired,
      and states explicitly that absence must be rendered *as absence*, not
      as the absence of a presence indicator. **FR-60** names the source of
      the expectation — the **installed** `~/.claude/settings.json`, refreshed
      on `ConfigChange`, disabled with a visible notice when unreadable — so
      the detector cannot fire at a hook the operator deliberately removed.
      **FR-61** adds the corollary class, "Smith ships this, your settings
      don't wire it", distinct from "wired but never fired". **US-2** carries
      the Gherkin scenarios and **SC-6** / **SC-21** make them measurable
- [x] The audit's read-only posture is stated in Non-Goals ("never starts,
      stops, advances, approves, or cancels a workflow") and enforced by
      **FR-24** (findings are advisory, never blocking) and **FR-44**
      (nothing in this feature writes to `active-workflows/`)

## Named Hard-Constraint Coverage

Every hard constraint the feature description named has its own numbered FR
so it can be verified rather than assumed.

- [x] **Concurrent-workflow attribution** → **FR-14**, with acceptance
      criteria stated inline (two workflow records, no double-attributed
      block, no cross-advanced stepper, no cross-counted tokens), a dedicated
      P1 user story (**US-3**), a success criterion (**SC-2**), and a
      required test (**FR-55**). The spec records that this was observed live
      in this repository — markers `60-activity-dashboard` and
      `67-deterministic-questions` sharing one `session_log:` — rather than
      hypothesized, and notes the same exposure in `workflow-summary.sh`
      while explicitly excluding a fix for it (**OOS-5**)
- [x] **Emitter always exits 0** → **FR-40**, which states the
      `PreToolUse`-blocks-the-tool-call reasoning that makes it the highest-
      risk surface, with **US-4** (P1) and **SC-4** requiring the assertion
      for `PreToolUse` specifically, not just `PostToolUse`
- [x] **Never forge a marker** → **FR-44**, which records that
      `SAFE_VAULT_DIRS` (`sessions bank ledger queue agents todo reports
      index audits`) deliberately omits `active-workflows`, AND that the gate
      cannot enforce anything against a detached daemon — so the prohibition
      is a design requirement rather than something enforcement provides.
      The single permitted exception (this skill's own marker via
      `create-active-workflow.sh`) is carved out in **FR-8** and cross-
      referenced. **OOS-6** forecloses changing the gate instead
- [x] **Never clobber an existing statusline** → **FR-45** (store the prior
      command, read stdin once, forward a copy, delegate; minimal default
      when none existed) plus **FR-46** for the uninstall restore path, which
      exists because `scripts/uninstall.sh` restores `settings.json`
      wholesale from a `.bak-` file and performs no surgical removal.
      **US-10** and **SC-13** cover both the pre-existing-command and
      no-command cases
- [x] **Redact by default** → **FR-48** (redaction before storage, before any
      SSE frame, and before `activity.log`, behind a
      `SMITH_ACTIVITY_CAPTURE_PROMPTS=1` opt-in, with a UI indicator when
      capture is active), with **SC-14** naming all four surfaces that must
      stay clean
- [x] **Local only / no dependencies / SSE** → **FR-4** (127.0.0.1 only,
      under any flag), **FR-49** (zero outbound requests, assets served
      locally), **FR-41** (SSE, not WebSockets), **D-1** (bash/git/jq/Python
      3.8 stdlib), **SC-15** (socket inspection + zero outbound connections)
- [x] **One daemon, all projects, idempotent** → **FR-2**/**FR-3**, with the
      account-wide-quota rationale for global-totals-plus-filter stated in
      FR-3 itself rather than left implicit, and **FR-5**/**FR-6** covering
      the port-taken and stale-pidfile recoveries that make "idempotent"
      true in practice

## Phase-Resolution Completeness

- [x] The resolver is specified as a state machine over an ordered event
      stream keyed by marker workflow type (**FR-10**), with the evidence
      that forces that design stated as verified fact: `/smith-new` produces
      a skill invocation at only 2 of 7 phases (one of them conditional),
      `/smith-bugfix` at 0 of 9, `/smith-debug` at 0 of 8
- [x] All six signals are enumerated in explicit priority order (**FR-11**),
      including the optimistic-advance-then-reconcile rule for live
      `PreToolUse` `Task` events arriving before the log block lands, and the
      completion-block rule that a returned subagent means DONE, not running
- [x] Artifact-presence fallback covers BOTH layouts — `specs/<n>-<slug>/`
      and `.specify/systems/<system>/features/<n>-<slug>/` — with the four
      concrete mappings (**FR-12**), and the same FR encodes the rubric-read
      trap: `smith-build` Phase 3.5 READS `skills/smith-clean-code/SKILL.md`
      as a file and must never advance a phase
- [x] The phase map is data, not code (**FR-15**), seeded with the real,
      verified headings for all five workflows — 7 / 9 / 8 / 11 / 9 entries
      respectively — re-verified directly against the SKILL.md files while
      drafting (`grep -nE '^#{2,3} (Phase|Step) ' skills/<w>/SKILL.md`), not
      taken from the task framing on trust. FR-15 also records the one
      asymmetry found while verifying: `smith-finish` is NOT an accepted
      `--workflow` value for `create-active-workflow.sh`, so it is the only
      mapped chain that cannot be keyed off a marker and must resolve from
      its own skill-invocation event — stated in the spec rather than left
      as a latent contradiction with FR-10's marker-keyed framing
- [x] A sync test between `phases.json` and the SKILL.md headings is a
      requirement (**FR-16**) with its own success criterion (**SC-3**), so a
      forgotten map entry fails the suite instead of silently rendering a
      stale stepper
- [x] Honesty requirements are separately numbered rather than folded into
      the rendering requirement: nesting rather than replacement (**FR-17**),
      mandatory-stop gates rendered distinctly with "waiting on a permission
      prompt" derived **primarily from the `PermissionRequest` /
      `PermissionDenied` hook events** and `claude agents --json`'s `status`
      used only as corroboration where present (**FR-18**, amended at the
      questions gate — the `waitingFor` field the original draft named is
      present in **zero** of 23 live records), visible provenance (**FR-19**),
      `phase unknown` plus last-known-phase-and-timestamp with an explicit
      prohibition on guessing (**FR-20**), and an outright ban on ordering
      anything by a parsed session-log timestamp, because the log mixes UTC
      and local clocks (**FR-58**)
- [x] The forward-compatibility hook for the deferred stamping work is a
      requirement, not a note: **FR-13** requires the resolver to prefer a
      marker `phase:` field if one ever exists, which is what makes OOS-1's
      deferral additive-with-zero-rework rather than a decision to relitigate

## Settled-Decisions Traceability

The four decisions the feature description marked as settled are stated as
decided, with their rationale recorded so a future reader does not re-open
them — and none is phrased as an open option anywhere in spec.md.

- [x] **Phase stamping deferred** → **OOS-1**, carrying the full rationale
      (a stamper shares the failure mode of the skill it lives in; a
      confidently-wrong stamp is the worst outcome for an audit tool; hook
      observation has no such mode) plus the FR-13 forward-compatibility
      guarantee
- [x] **No `launchd` agent** → **OOS-2** (on-demand only; no plist, no login
      item, no auto-start)
- [x] **Ephemeral retention** → **OOS-3**, including the storage-boundary
      requirement that makes a later two-tier retained scheme a config change
      rather than a redesign, and the corresponding UI honesty requirement
      (the post-restart blank slate is stated, not shown as a silently
      truncated timeline — also covered in Edge Cases)
- [x] **No auto-open on `SessionStart`** → **OOS-4**, with the reason stated
      (a hook that opens a browser tab is exactly the surprise this feature
      must not introduce)

## Exploration-Findings Traceability

Each exploration finding is encoded as a requirement, an assumption, or a
constraint — none is left as unencoded narrative.

- [x] `SAFE_VAULT_DIRS` excludes `active-workflows`; reads are never gated; a
      detached daemon is outside the hook system → **FR-44**, **A-7**,
      **OOS-6**, and the `~/.smith/activity/` state location in **FR-7** /
      **D-7**. Re-verified directly against `hooks/workflow-gate.sh` while
      drafting: the `SAFE_VAULT_DIRS` array and the basename exemption for
      `create-active-workflow.sh` both confirm the claim exactly
- [x] Smith owns no statusline today; the risk is the operator's own →
      stated in **FR-45** itself so the requirement carries its own threat
- [x] The settings fragment declares no timeout field anywhere, and no hook
      makes a network call today → **A-2** (the sub-500 ms budget is a target
      to MEASURE, not an assumption), reinforced by FR-40's guarantee holding
      regardless of whether the budget is met, and by **FR-42** naming the
      emitter as the first on both counts
- [x] Install merge is idempotent at (matcher, command) via
      `dedupehooks.jq`, and chain order within an entry is pinned →
      **FR-51**, **D-9**
- [x] Uninstall restores `settings.json` wholesale and never removes entries
      surgically → **FR-46**, **D-10** (an explicit new code path is
      required, not assumed)
- [x] Every `PostToolUse` hook in the repo exits 0 unconditionally →
      **FR-40** and the third US-4 scenario name this as the convention being
      followed rather than invented
- [x] `start-playwright-server.sh` is the daemon precedent; `scheduler/` is
      NOT (it is a launchd batch job that exits) → **A-5**, which states both
      halves so the wrong precedent is not reached for
- [x] CI runs ONLY flat `tests/*.test.sh` → **FR-54**, **D-8**, **SC-16** —
      with the consequence stated plainly ("a test that does not run in CI
      gates nothing")
- [x] README badge reads 33 against 34 actual skill directories → **FR-53**
      requires 35, noting the feature both adds one and fixes pre-existing
      drift
- [x] `workflow_summary_lib.py`'s `match_family()` / `load_pricing()`
      `_compiled_patterns` trap → **FR-33** states it as a contract that MUST
      be honored; the zero-test-coverage consequence is its own requirement
      (**FR-56**: any extraction must ADD tests, because "preserve existing
      behavior" has nothing to verify against); the `isSidechain` skip
      meaning live subagent tokens are new code is **FR-36**; the
      clean-to-import property and 3.8 floor are **A-4**
- [x] `hooks/pricing.json` is never installed (`install.sh` globs only
      `hooks/*.sh` and `hooks/*.py`) and its newest family predates the
      running model → **FR-62** requires the `hooks/*.json` glob **and** the
      current families, under an explicit never-invent-rates constraint
      (authoritative source, `last_verified`, unavailable-rather-than-guessed)
      and an explicit note that entry ORDER is load-bearing for
      `match_family()`'s first-match-wins scan. **SC-17** makes it measurable
- [x] `uninstall.sh`'s `SMITH_HOOKS` lists 11 of 20 shipped hooks → **FR-63**
      requires the full set, **derived from `hooks/` at build time rather than
      transcribed from a count**, plus a flat `tests/*.test.sh` assertion so
      the drift cannot silently return, plus the `install.sh:138` "Copy 9
      hooks" fix. **SC-18** makes it measurable
- [x] `hooks/workflow_summary_lib.py` is explicitly NOT on **D-6**'s modified
      list → **FR-36** requires the live-subagent sidechain parse to land in
      `scripts/activity/usage.py` instead, so reuse never becomes an edit

## Feature Readiness

- [x] Every FR group maps to a deliverable surface named in Dependencies &
      Constraints (**D-5** new, **D-6** modified), and every named deliverable
      is covered by at least one FR — no orphan file and no unimplementable
      requirement
- [x] Key Entities covers all ten data concepts the feature reasons about
      (project, session, subagent, workflow, phase, worktree, quota window,
      token rollup, divergence finding, absence finding) — the eight the
      feature description named plus token rollup and absence finding, which
      FR-32/FR-36 and FR-23 respectively make first-class — each with the
      attributes the requirements actually reference — notably that a
      *workflow*, not a session log, is the unit of attribution (the FR-14
      concern, restated at the data-model level so a planner cannot design
      around a single-stream assumption)
- [x] No FR contradicts another (checked against the pairs most likely to
      conflict: FR-13's "prefer a marker `phase:` field" and OOS-1's "no
      stamping" are complementary, not contradictory — FR-13 governs what the
      resolver does IF a field appears, OOS-1 governs whether this feature
      writes one; FR-8's marker creation and FR-44's marker prohibition are
      reconciled by FR-44's explicit carve-out naming
      `create-active-workflow.sh` as the sole path; FR-3's global totals and
      the per-project filter are one behavior, not two, because the quota
      windows being account-wide is stated as the reason)
- [x] Measurable outcomes present and non-tautological (SC-1..SC-16 each
      state a threshold, a count, an exit status, or an exact-match
      condition — none restates an FR in different words)
- [x] Ready for planning: every FR is specific enough to size and sequence,
      and the riskiest three (FR-14 concurrent attribution, FR-40 emitter
      safety, FR-11/FR-15 phase resolution) each have a dedicated P1 user
      story, a success criterion, AND a named required test in FR-55

## Notes

- Validated against the written `spec.md` in 1 iteration. The
  `[NEEDS CLARIFICATION]`-marker grep and the vague-qualifier grep were both
  run directly against the file on disk (0 matches each), and the FR / SC /
  US / G / A / OOS / D numbering was extracted and counted to confirm no gaps
  or duplicates before this checklist could be marked complete: **56 FRs
  (FR-1..FR-56)**, **16 SCs (SC-1..SC-16)**, **10 user scenarios
  (US-1..US-10, four at P1)**, 10 goals, 9 assumptions, 7 out-of-scope items,
  10 dependencies/constraints, 13 enumerated edge cases.
- The five phase chains in FR-15 were re-verified against the SKILL.md files
  in this worktree rather than copied from the task framing: `smith-new` 7,
  `smith-bugfix` 9, `smith-debug` 8, `smith-build` 11, `smith-finish` 9 — all
  matched the framing exactly, including `smith-build`'s three fractional
  phases (3.5 / 3.6 / 3.7) and `smith-finish`'s two (1.5 / 6.5).
- `maintenance` was confirmed as an accepted `--workflow` value in
  `scripts/create-active-workflow.sh`'s own validation list before FR-8
  depended on it (**A-6**).
- This spec's unusual weighting toward *negative* requirements — what must
  never happen (FR-40 exit 0, FR-44 no marker writes, FR-45 no statusline
  clobber, FR-48 no prompt leakage, FR-49 no outbound requests, FR-20 no
  guessed phase name) — is deliberate and is the direct consequence of the
  audit framing: an observability tool that can alter, block, or misreport
  the thing it observes is worse than none, so each of those is numbered and
  separately testable rather than folded into a general "be safe" NFR.
