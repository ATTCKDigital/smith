---
feature: 54-clean-code-review-pass
branch: 54-clean-code-review-pass
status: ready-for-build
generated: 2026-09-13
inputs: spec.md (FR-1..FR-21, NFR-1..NFR-5, answers_applied), plan.md, data-model.md (§1-§5), research.md, questions.md (6/6 ANSWERED), quickstart.md
---

# Tasks: Clean Code Review Pass for Generated Code

9 tasks across 3 phases. Phases are sequential, matching `plan.md`'s Phased
task ordering (each phase's own rationale is in its heading below). Within
a phase, tasks marked `[P]` touch independent files and may run in any
order/in parallel; tasks touching the SAME file are listed in required
sequential order and are never marked `[P]` (mirrors `smith-implement`'s
own "file-based coordination" rule). Every task is scoped to exactly one
file, except the two pure-verification tasks (T007, T008, T009), which are
grep/test sweeps across the files the earlier tasks touched.

This is a prose-only feature (`plan.md`'s Technical Context: no application
runtime, no new files) — no NEW/Setup/Foundational/Polish phase shape
applies here the way it would for a code feature; the three phases below
instead mirror `plan.md`'s own "Phased task ordering" section exactly.

---

## Phase 1 — `smith-build` review-pass section + PR template (closes the spec's Problem Statement gap; independent of Phase 2/3 below)

All three tasks edit `skills/smith-build/SKILL.md`, so they run in the
listed order, not in parallel. Together they implement `plan.md`'s
file-by-file list item (1)'s three sub-changes.

- [X] [T001] Edit `skills/smith-build/SKILL.md`. Insert a new `## Phase 3.5: Clean Code Review Pass` section between the current line 250 (last bullet of `### 3.3 Test Failure Handling`) and line 252 (`## Phase 4: Spec Updates (Subagent)`), following the "N.5 inserted phase" naming convention already established by `smith-bugfix/SKILL.md:179` (research.md §2) — this does NOT renumber Phase 4 through 7 or any existing cross-reference to them ("Phase 5.4", "7.4.1", etc.). Per `plan.md`'s File Size Policy, keep this new section's own prose to roughly 40-70 lines, referencing `data-model.md`'s contracts by section number rather than restating them field-by-field. The section must specify, in this order:
  1. **Invocation.** Launch exactly ONE subagent (Task tool) using the same `WORKTREE_PATH`/`BASE_BRANCH` threading Phase 4/Phase 5 already use — `BASE_BRANCH=$(.specify/scripts/bash/get-base-branch.sh)`, mirrored verbatim from the pattern at `smith-build/SKILL.md:258,325,516` (FR-3) — diffing against `$BASE_BRANCH` only, never a hardcoded or inferred ref. Pin the subagent to `model: claude-sonnet-4-5`, matching the `model: claude-haiku-4-5` pin syntax already used at `smith-bugfix/SKILL.md:232` / `smith-index/SKILL.md:123,218` / `smith-navigate/SKILL.md:5`. Sonnet, not Haiku, is deliberate (questions.md Q2, resolved A): this pass makes auto-fix judgment calls ("is this fix behavior-preserving?"), not narrow classification/lookup like the repo's existing Haiku precedents.
  2. **Rubric delivery.** The subagent Reads `skills/smith-clean-code/SKILL.md` (worktree copy first), falling back to `~/.claude/skills/smith-clean-code/SKILL.md` (installed copy) only when the worktree copy is unavailable (FR-5, questions.md Q1, resolved A). It targets the `## Review Process`, `## Decision Rules`, and `## What You Should Avoid` sections by HEADING, not by line number: instruct it to `grep -n '^## Review Process'` (and the same for the other two headings) first to locate each heading's CURRENT line, then Read from that line to the next `^## ` heading — never hardcode a line range (e.g. do not write "398-430" or "487-501" or "363-382" anywhere in this new section's own shipped prose), since `skills/smith-clean-code/SKILL.md` is edited independently of this feature and any such range would silently drift out of date (research.md D1's line-range-fragility finding; NFR-5 — this pass consumes that file read-only and must never need a matching edit here when it changes).
  3. **Findings contract.** Each finding the subagent returns conforms to `data-model.md` §1's required output contract — reference this by section number only; do not restate the field list here, the source file is large. Each finding carries exactly one severity (Critical/High/Medium/Low) per the Review Process's own classification (FR-6).
  4. **Auto-fix eligibility.** Apply `data-model.md` §3's decision table (reference by section number; do not restate the table) to decide, per finding, whether to apply a direct edit. State the one row worth naming explicitly, since it is the one FR-8 reinforces "regardless of configuration": a Critical finding whose only available fix would change program behavior is NEVER auto-fixed, always flagged (FR-7, FR-8).
  5. **`.meta` coverage — explicitly NO new step here.** State plainly that this section does NOT add a proactive `.meta`-write step of its own (FR-9, resolved via questions.md Q6 Option A — reject Option B). For builds launched via `smith-new`, that workflow's existing per-edit `.meta` instruction (`smith-new/SKILL.md:465-474`) already covers every Write/Edit the build subagent makes, auto-fix edits included, with no separate carve-out needed. For standalone `smith-build` runs, auto-fix edits fall back to the existing passive §5.3.1 Description Coverage Warnings scan, exactly like ordinary Phase 2 implementation edits already do. Do NOT invoke or reference `smith-bugfix/SKILL.md:189-259`'s proactive Task-spawn `.meta` procedure from this section — that was the explicitly-rejected Option B.
  6. **No `tasks.md` coupling.** One sentence: auto-fix edits from this pass are treated as polish, not tracked tasks, and require no corresponding `tasks.md` change (FR-10).
  7. **Bounded re-test.** If one or more auto-fixes were applied (`fixes_applied > 0`, any count — not gated on how many), run exactly one full re-run of Phase 3 in its entirety (3.1 Unit Tests → 3.2 Playwright E2E → 3.3 Test Failure Handling) (FR-11). If zero auto-fixes were applied, Phase 3 MUST NOT be re-run (FR-12, US-2). A failing re-run resolves entirely via Phase 3.3's OWN existing bounded-attempts behavior (`smith-build/SKILL.md:246-250` — up to 3 attempts per failing test, then log-and-continue, flagged in release notes) — this section adds no second retry loop, no second fix batch, and does NOT re-review the diff, regardless of the re-run's PASS/FAIL outcome (FR-13, FR-14). State the bound explicitly in the shipped prose: one review → at most one fix-application batch → at most one Phase 3 re-run, no step repeats (NFR-4).
  8. **Unresolved findings → scratch file.** Findings where `Fix applied: false` are written by the REVIEW SUBAGENT ITSELF (its own output/Write call — there is no deterministic bash+python scan block to write here, unlike §5.3/§5.3.1, since "is this a god function" is a judgment call a script cannot make; research.md §4) to `/tmp/smith-build-clean-code-findings.txt` (FR-15). Format per `data-model.md` §2 (reference the section for the exact line syntax rather than retyping it): Medium/High/Critical findings each get one line; Low-severity findings are never listed individually — if any remain unfixed, exactly one trailing `+ N low-severity notes` line is appended instead (questions.md Q3, resolved A). An auto-fixed finding contributes nothing to this file.
  9. **Ordering.** This whole section runs strictly after Phase 3 has reached a passing state and strictly before Phase 4 begins (FR-1); it is gated on Phase 3's success as an ordering precondition only, never as a block on Phase 4 — flag-never-block still governs the PR outcome via T002 below, not this pass's own invocation (FR-2).

  Note: the blanket "ALL phases run without user interaction" Key Rule already at `smith-build/SKILL.md:740` covers this new phase automatically (NFR-1) — no separate no-prompts sentence needs to be added.

- [X] [T002] Edit `skills/smith-build/SKILL.md` §5.4 (`### 5.4 Create PR & Merge`, the PR-body heredoc currently at lines 514-552). Add a new conditional `## Clean Code Review` section to the PR-body template, positioned immediately after the existing `## Description Coverage Warnings` block (currently lines 534-545) and before `## Release notes` (currently line 547) — the third section in the same scan → `/tmp` file → conditional-section family as `## File Size Warnings` (§5.3) and `## Description Coverage Warnings` (§5.3.1) (research.md §4; plan.md's Reuse-before-create list). Per `data-model.md` §5 (reference by section number for the full contract):
  - Include the section only when `/tmp/smith-build-clean-code-findings.txt` (T001 step 8) is non-empty — `[ -s /tmp/smith-build-clean-code-findings.txt ]` or equivalent, matching §5.3/§5.3.1's own non-empty-check pattern; omit the section entirely when empty (FR-16). This is the ONE new shell fragment this feature adds anywhere (research.md §4's "barely any new bash surface" finding) — keep it to this single conditional check, do not add a parser.
  - Embed the file's contents verbatim in the section body — Medium/High/Critical findings already appear individually and the "+ N low-severity notes" line (if any) already appears last, per T001 step 8's file format; no second filtering step happens here.
  - Close the section with wording mirrored verbatim in spirit from §5.3's own closing line: "This is a FLAG, never a blocker. Always proceed with PR creation." (FR-17) — the PR MUST always open regardless of remaining-finding count or severity (NFR-3, SC-6).
  - Match the include-if-non-empty comment phrasing already used by the two existing sections (e.g. line 525's `<contents of /tmp/... if non-empty; otherwise omit this section>` pattern) for internal consistency.

  Depends on T001 (references the file T001's subagent writes).

- [X] [T003] Edit `skills/smith-build/SKILL.md` §5.3 (`### 5.3 Pre-PR File-Size Scan`, currently starting at line 317). Add ONE sentence near the top of this section — after its existing intro paragraph, before the bash block — noting that the Clean Code Review Pass (§3.5) already ran, with any auto-fixes already applied, before Phase 4; so this scan's (and §5.3.1's) `git diff $BASE_BRANCH` snapshot naturally reflects the post-fix diff, and no separate re-scan or staleness-avoidance step exists or is needed (FR-18; research.md §1's "same-commit payoff" finding — auto-fix edits land in the same commit as the rest of Phase 2/4's work, since Phase 5.1 Commit runs after both Phase 3.5 and Phase 4). This is a documentation/consistency note only — §5.3/§5.3.1's own scan logic (bash/python blocks) is otherwise untouched, per `plan.md`'s file-by-file list item (3): "No change to §5.3/§5.3.1 themselves."

  Depends on T001 (the note references Phase 3.5 by name, which must already exist).

---

## Phase 2 — `smith-bugfix` and `smith-implement` checklist parity (independent files; sequenced second per `plan.md`'s own phased-ordering instruction)

- [X] [T004] [P] Edit `skills/smith-bugfix/SKILL.md` Phase 3 (`## Phase 3: Implement the Fix`, currently lines 165-177), step 2 (currently lines 168-172 — the single sentence "Implement the fix — keep changes minimal and focused. When the fix adds or changes code, keep that code clean per the constitution's Clean Architecture Policy (small single-responsibility units, reuse existing components instead of duplicating). This does NOT license refactoring untouched surrounding code — see the constraints below."). Replace the Clean-Architecture-Policy clause with this exact inline six-bullet checklist (FR-19), keeping the "keep changes minimal and focused... This does NOT license refactoring untouched surrounding code" framing sentences around it:
  - Small, single-responsibility functions and files; one clear reason to change.
  - Intention-revealing names (avoid `data`, `temp`, `handler`, `util` when a meaningful name exists).
  - Guard clauses over deep nesting; keep control flow shallow.
  - Separation of concerns — keep I/O, business rules, and persistence in distinct units.
  - No dead code, commented-out blocks, or duplicated logic.
  - Reuse existing components over recreating them — check for an existing module/service/utility that already does it before writing something new.

  Bullets 1-5 are `smith-build/SKILL.md:205-211`'s own inline-bullet text, reused verbatim (research.md §5's "reuse this SAME vocabulary" instruction). Bullet 6 is a condensed, one-line version of `smith-build/SKILL.md:214-218`'s separate "Reuse over duplication" paragraph, phrased to match FR-19's own parenthetical ("reuse existing components over recreating them") — this is a DELIBERATE substitution: `smith-build/SKILL.md`'s Phase 2 inline list's OWN 6th bullet ("Honor the file structure `plan.md` prescribed...", lines 212-213) is NOT ported here, since FR-19's explicit six-bullet parenthetical names "reuse existing components," not "honor the file structure." (See this file's Coverage & Consistency Notes, gap #1, for the full reasoning — this resolves a real textual tension between FR-19's parenthetical and Phase 2's current bullet-6 text.)

  Do NOT add `smith-build`'s separate standalone "Reuse over duplication" (`smith-build/SKILL.md:214-218`) or "Keep files small" (`:219-222`) paragraphs in full — FR-20 explicitly excludes duplicating those PARAGRAPHS (the condensed one-line bullet 6 above is the only reuse-related content permitted here). Do NOT touch step 3's "Do NOT" list (currently lines 173-177: refactor surrounding code / add features beyond the fix / modify unrelated files / add unnecessary abstractions) — it must remain byte-for-byte unchanged (FR-20; quickstart.md Scenario 7 step 3). Do NOT add any automated review-and-auto-fix subagent invocation anywhere in this file as part of this feature (FR-20; questions.md Q4, resolved No) — this task is a text-only expansion of step 2, nothing else in `skills/smith-bugfix/SKILL.md` changes.

- [X] [T005] [P] Edit `skills/smith-implement/SKILL.md` line 180 (the "Clean architecture" bullet inside step 7 "Implementation execution rules": "follow the constitution's Clean Architecture Policy — small single-responsibility units, reuse existing components over duplicating, and keep files within the File Size Policy (split large ones rather than growing monolithic files). Honor the file structure defined in plan.md."). Replace it with the SAME six-bullet checklist as T004 (FR-21; questions.md Q5, resolved Yes), with ONE deliberate difference on bullet 1 only — folding in the original line's File Size Policy and file-structure content rather than dropping it (per `plan.md`'s explicit instruction for this file: "preserved, folded into the checklist's file-structure bullet rather than dropped"):
  - Small, single-responsibility functions and files; one clear reason to change. Keep files within the File Size Policy (300-line soft target, 500-line decomposition threshold) and honor the file structure `plan.md` prescribes — split large files rather than growing monolithic ones.
  - Intention-revealing names (avoid `data`, `temp`, `handler`, `util` when a meaningful name exists).
  - Guard clauses over deep nesting; keep control flow shallow.
  - Separation of concerns — keep I/O, business rules, and persistence in distinct units.
  - No dead code, commented-out blocks, or duplicated logic.
  - Reuse existing components over recreating them — check for an existing module/service/utility that already does it before writing something new.

  Bullets 2-6 are byte-for-byte identical to T004's bullets 2-6. Bullet 1 is the one place this file's block intentionally diverges from `smith-bugfix`'s (see Coverage & Consistency Notes, gap #1) — `smith-bugfix`'s original step-2 sentence never mentioned File Size Policy, so there was nothing to preserve there; `smith-implement`'s original line 180 did, so it is folded into bullet 1 here per `plan.md`'s explicit instruction rather than silently dropped.

---

## Phase 3 — `CHANGELOG.md`, cross-refs, and final verification (written/run last, after Phases 1-2 are final)

- [X] [T006] Edit `CHANGELOG.md`. Add a new entry under `[Unreleased]` → `### Added` (top of the existing list, after line 10), matching the existing entries' bold-summary + sub-bullets style (see the `stamp-response.sh` / `user-prompt-logger.sh` / workflow-gate-bootstrap entries for tone/structure precedent). Summarize: (a) the new `smith-build` `## Phase 3.5: Clean Code Review Pass` (Sonnet-run subagent, heading-anchored rubric Read of `skills/smith-clean-code/SKILL.md`, bounded one-review/one-fix-batch/one-retest cycle, flag-never-block `## Clean Code Review` PR-body section with Medium+ findings listed individually and Low findings folded into a one-line count); and (b) the `smith-bugfix`/`smith-implement` inline six-bullet clean-code checklist parity (closing the "Phase 2 has the checklist, everyone else has a pointer" gap named in this feature's Problem Statement). Cite the feature by number (`#54`, `54-clean-code-review-pass`), matching the existing entries' citation style (e.g. `(feature #53, 53-mcp-browser-access)`).

  Write this task LAST, only after T001-T005 have landed, so the entry accurately describes what shipped rather than what was planned (`plan.md`'s Phased task ordering item 3, mirroring feature 53's own "changelog close-out written last" rule at `.specify/systems/cross-system/features/53-mcp-browser-access/plan.md:195-197`).

  Depends on T001, T002, T003, T004, T005.

- [X] [T007] Cross-reference consistency verification (no file edit — a grep sweep across `skills/smith-build/SKILL.md`, `skills/smith-bugfix/SKILL.md`, `skills/smith-implement/SKILL.md`, and `CHANGELOG.md`, per `plan.md`'s Test Strategy and Phased task ordering item 3's "cross-refs" step). Confirm all of the following; fix the offending file in-place and re-check if any fail:
  - `grep -n "Phase 3.5" skills/smith-build/SKILL.md` — the new heading exists exactly once, and no pre-existing "3.4"/"3.5"/"3.6" heading was already in this file before T001 (research.md §2).
  - `grep -n "## Phase 4:" skills/smith-build/SKILL.md` — Phase 4 still immediately follows the new section; nothing was accidentally swallowed between them.
  - `grep -c "Clean Code Review" skills/smith-build/SKILL.md` — at least 2 matches (the Phase 3.5 heading/prose from T001, and the §5.4 template section name from T002).
  - `grep -n "smith-build-clean-code-findings.txt" skills/smith-build/SKILL.md` — the filename appears both where it's written (T001 step 8) and where it's read (T002's template), confirming no typo between the two spots.
  - Every new mention of the rubric skill across all four files spells it `/smith-clean-code` or `skills/smith-clean-code/SKILL.md` — never `/clean-code`, `smith-clean-code-review`, or any other variant (`smith-clean-code` is confirmed as the actual installed skill directory in this worktree).
  - T001's new Phase 3.5 prose contains ZERO hardcoded line-number citations of `skills/smith-clean-code/SKILL.md`'s rubric sections (no "398", "430", "487", "501", "363", "382", or any other line-range digits referencing that file) — heading anchors only (FR-5's drift concern; research.md D1).
  - `grep -n "^### Added" -A 3 CHANGELOG.md | head` — T006's new entry landed under `[Unreleased]` → `### Added`.
  - `git diff "$(.specify/scripts/bash/get-base-branch.sh)" --name-only` (run from the worktree) returns exactly `skills/smith-build/SKILL.md`, `skills/smith-bugfix/SKILL.md`, `skills/smith-implement/SKILL.md`, and `CHANGELOG.md` — confirming by construction that `skills/smith-clean-code/SKILL.md` (NFR-5/OOS-3), `skills/smith-debug/SKILL.md` (OOS-1), and `skills/smith-new/SKILL.md` (OOS-2) are untouched.
  - `grep -n "Phase 3.5" skills/smith-bugfix/SKILL.md` — confirms exactly the ONE pre-existing "Phase 3.5: Update `.meta` Descriptions for Touched Methods" heading (line 179, untouched by this feature) and zero NEW "Clean Code Review"/automated-pass headings were added to this file (FR-20; quickstart.md Scenario 7 step 2).
  - SC-4's literal check: extract T004's six-bullet block and T005's six-bullet block and diff them. Bullets 2-6 must be byte-for-byte identical between the two files. Bullet 1 is EXPECTED to differ (`smith-implement`'s carries the folded-in File Size Policy clause per T005's own instruction) — this is a deliberate, documented divergence, not a paraphrase failure; do not "fix" it to match `smith-bugfix`'s shorter bullet 1.

  Depends on T001-T006.

- [X] [T008] Run the full pre-existing automated test suite once, in a clean scratch checkout, after all prior tasks have landed, and confirm zero regressions (SC-5) — this feature changes only markdown prose (plus T002's one-line non-empty-file check), so every one of these is expected to pass UNMODIFIED:
  - `tests/get-base-branch.test.sh`
  - `tests/workflow-gate-redirect.test.sh`
  - `tests/workflow-summary-session.test.sh`
  - The full `tests/hooks/` suite (unaffected by this feature; run for regression confidence only, mirroring feature 53's own T020 single-pre-merge-gate precedent).

  None of the four changed files (`skills/smith-build/SKILL.md`, `skills/smith-bugfix/SKILL.md`, `skills/smith-implement/SKILL.md`, `CHANGELOG.md`) are scripts any of these tests exercise — a failure here would mean this feature accidentally broke something outside its own stated scope, not an expected outcome.

  Depends on T001-T007.

- [X] [T009] Bash+zsh smoke test (NFR-2) for the one shell fragment this feature adds — T002's `[ -s /tmp/smith-build-clean-code-findings.txt ]`-style non-empty check (research.md §4: this feature adds "a single non-empty-file check, not a new parser," so there is no other new shell surface to test). Run the check under both interpreters against a scratch empty file and a scratch non-empty file, confirming identical branch behavior in both shells, per `plan.md`'s Test Strategy:
  ```bash
  bash -c '[ -s /tmp/nonexistent-scratch-file ] && echo yes || echo no'
  zsh  -c '[ -s /tmp/nonexistent-scratch-file ] && echo yes || echo no'
  ```
  then repeat against a scratch file containing one line of content, confirming both shells print `yes`. No markerless-snippet constraint applies here — Phase 3.5 runs before the active-workflow marker is cleared in Phase 7, so ordinary `>`/`>>` redirection is fine, exactly like §5.3/§5.3.1's own snippets (`plan.md`'s Test Strategy, "No markerless constraint applies here").

  Depends on T002.

---

## Coverage & Consistency Notes (smith-analyze pass)

**Spec ↔ Plan ↔ Tasks alignment: PASS, with 1 critical gap found and fixed in-place, 1 pre-existing artifact inconsistency noted (not fixed, out of scope for this file).**

### FR / NFR / SC → task traceability

| Requirement | Task(s) |
|---|---|
| FR-1 (ordering: after Phase 3, before Phase 4) | T001 (step 9) |
| FR-2 (gates on Phase 3 success, not a block on Phase 4) | T001 (step 9) |
| FR-3 (`WORKTREE_PATH`/`BASE_BRANCH` threading, diff vs `$BASE_BRANCH`) | T001 (step 1) |
| FR-4 (evaluate diff vs Review Process + Decision Rules) | T001 (steps 1-4) |
| FR-5 (rubric delivery: heading-anchored Read, worktree-first/installed-fallback) | T001 (step 2); verified T007 |
| FR-6 (exactly one severity per finding) | T001 (step 3) |
| FR-7 (auto-fix only if safe+unambiguous+behavior-preserving; unclear → flag) | T001 (step 4) |
| FR-8 (Critical + behavior-change → never auto-fix, no override) | T001 (step 4) |
| FR-9 (`.meta` coverage via existing layered mechanisms, no new machinery) | T001 (step 5) |
| FR-10 (no `tasks.md` coupling for auto-fix edits) | T001 (step 6) |
| FR-11 (exactly one full Phase 3 re-run if fixes applied) | T001 (step 7) |
| FR-12 (zero auto-fixes → no Phase 3 re-run) | T001 (step 7) |
| FR-13 (pass runs at most once per build; no re-review) | T001 (step 7) |
| FR-14 (failing re-test uses existing 3.3 behavior only) | T001 (step 7) |
| FR-15 (unresolved findings → scratch file) | T001 (step 8) |
| FR-16 (PR-body section: Medium+ individually, Low folded, omit-when-empty) | T002 |
| FR-17 (flag-never-block wording) | T002 |
| FR-18 (post-fix diff visible to §5.3/§5.3.1, no re-scan mechanism) | T003 |
| FR-19 (smith-bugfix six-bullet checklist) | T004 |
| FR-20 (bugfix stays parity-only; Do NOT list unchanged) | T004 |
| FR-21 (smith-implement six-bullet checklist) | T005 |
| NFR-1 (no user interaction) | Satisfied by the existing `smith-build/SKILL.md:740` Key Rule; no dedicated task needed |
| NFR-2 (bash+zsh portability) | T009; authorship constraint on T002 |
| NFR-3 (flag-never-block invariant, every configuration) | T002 (wording); T001 step 9 (non-blocking gate) |
| NFR-4 (deterministic, bounded loop) | T001 (step 7) |
| NFR-5 (`smith-clean-code/SKILL.md` untouched, read-only input) | T001 (step 2, Read-only); verified T007 |
| SC-1 / SC-2 (exactly one of two shipped states; clean diff short-circuits) | T001 + T002 jointly, by construction; manually verified via `quickstart.md` Scenarios 1-2 (no dedicated automated task — this feature has no application test suite per `plan.md`'s Test Strategy) |
| SC-3 (zero prompts across every execution) | Same existing Key Rule as NFR-1 |
| SC-4 (bugfix Phase 3 text bullet-matches build Phase 2) | Produced by T004/T005; verified T007 |
| SC-5 (existing tests pass unmodified) | T008 |
| SC-6 (never blocked/delayed/failed due to findings) | T002 (wording); NFR-3 |

Every `plan.md` "Exact file-by-file change list" entry has at least one
task: `skills/smith-build/SKILL.md`'s three sub-changes → T001/T002/T003;
`skills/smith-bugfix/SKILL.md` → T004; `skills/smith-implement/SKILL.md`
→ T005; `CHANGELOG.md` → T006. No file outside that list is touched by any
task (T007's `git diff --name-only` check verifies this by construction).

### Gaps found and fixed in-place

1. **CRITICAL — FR-19/FR-21's six-bullet parenthetical does not literally
   match `smith-build/SKILL.md` Phase 2's CURRENT six inline bullets, and
   naively copying Phase 2's list verbatim would have silently dropped a
   requirement.** Phase 2's own inline checklist (`smith-build/SKILL.md:205-213`)
   ends in "Honor the file structure `plan.md` prescribed..." as its 6th
   bullet, with "reuse existing components" living instead in a SEPARATE
   standalone paragraph (`:214-218`, "Reuse over duplication") — not in the
   inline list at all. But FR-19 and FR-21 each independently and
   identically enumerate SIX bullets whose 6th item is "reuse existing
   components over recreating them," not "honor the file structure." Left
   unresolved, an implementer following "copy Phase 2's inline list
   verbatim" (the literal reading of "the same inline...bullets smith-build
   Phase 2 uses") would have produced a bugfix/implement checklist missing
   the reuse bullet FR-19/FR-21 explicitly require, while `plan.md`'s Test
   Strategy separately assumes "the SHARED six bullets are
   verbatim-identical" between the files — a claim that can only hold if
   both new files are authored from the SAME six-bullet source text, not
   from Phase 2's literal current list. **Fixed**: T004 and T005 now spell
   out the exact six-bullet text to use — bullets 1-5 reused verbatim from
   Phase 2's inline list (research.md §5's "same vocabulary" instruction),
   bullet 6 a condensed one-line version of Phase 2's separate "Reuse over
   duplication" paragraph matching FR-19/FR-21's literal wording — so T004
   and T005 are guaranteed to produce identical six-bullet blocks (SC-4)
   while staying faithful to FR-19/FR-21's explicit text and FR-20's
   non-duplication instruction simultaneously. T005 additionally documents
   its one deliberate divergence (bullet 1 folds in File Size Policy content
   per `plan.md`'s explicit instruction for that file only), and T007's
   SC-4 check is written to expect that specific, documented divergence
   rather than flag it as a paraphrase failure.

### Noted, not fixed (pre-existing artifact drift, out of scope for `tasks.md`)

2. **`quickstart.md` Scenario 1, step 2** still describes auto-fix `.meta`
   coverage as happening "via the same mechanism as `smith-bugfix`'s Phase
   3.5" — i.e., a proactive `.meta`-write step inside the new Phase 3.5.
   This directly contradicts the RESOLVED `FR-9` (questions.md Q6, Option
   A: rely on existing layered coverage, no new `.meta`-write machinery in
   `smith-build`'s Phase 3.5), which `spec.md`, `plan.md`, and
   `data-model.md` all correctly reflect. This reads as a stale line left
   over from before Q6 closed the gate (`plan.md`'s own "Spec-plan tensions
   surfaced" §3 documents the same premise gap and its resolution, but
   `quickstart.md` was not updated to match). T001 (step 5) is written from
   the CORRECT, resolved FR-9/Q6 text, not from `quickstart.md`'s stale
   wording — so no task in this file inherits the contradiction. Not fixed
   here because this task's mandate is to write `tasks.md` only; flagging
   for a follow-up correction to `quickstart.md` Scenario 1 step 2.

### Answered-question non-contradiction check

- **Q1 (heading-anchored Read, worktree-first)**: T001 step 2 implements
  grep-then-Read by heading, worktree copy first, installed fallback second
  — no task hardcodes a line range or skips the fallback.
- **Q2 (Sonnet, not Haiku)**: T001 step 1 pins `claude-sonnet-4-5`; no task
  reverts to a Haiku pin or omits the pin (which would default ambiguously).
- **Q3 (Medium+ individually, Low as a count)**: T001 step 8 and T002 both
  encode this threshold identically; no task lists Low findings individually
  or drops the low-severity count line.
- **Q4 (bugfix: checklist parity only, no automated pass)**: T004 explicitly
  forbids adding an automated review-and-auto-fix subagent to
  `smith-bugfix/SKILL.md`; T007 greps to confirm zero new
  "Clean Code Review"/automated-pass headings landed there.
- **Q5 (smith-implement gets the same parity treatment)**: T005 exists and
  is scoped identically to T004 (bullets 2-6); no task treats
  `smith-implement` as out of scope.
- **Q6 (FR-9: existing layered coverage, no new `.meta` machinery)**: T001
  step 5 states this explicitly and forbids importing
  `smith-bugfix/SKILL.md:189-259`'s procedure; see also gap #2 above
  regarding `quickstart.md`'s stale wording, which no task in this file
  repeats.

No task in this file contradicts any of the 6 answered questions, the
bounded-loop contract (`data-model.md` §4), or the auto-fix decision table
(`data-model.md` §3).
