# Implementation Questions: Clean Code Review Pass

**Generated**: 2026-09-13
**Feature**: [spec.md](./spec.md)
**Plan**: [plan.md](./plan.md)
**Status**: ANSWERED

> Note: the core design decision (auto-fix allowed; post-testing placement; one full re-test when fixes land; bounded single pass) was resolved pre-spec by the user and is NOT re-opened here.

---

## Q1: How does the review subagent receive the rubric?

**Context**: Workflow subagents cannot load skills. research.md D1 documents two delivery options for smith-clean-code's Review Process / Decision Rules / What You Should Avoid sections.

**Question**: Inline the rubric text into the review-pass prompt block, or have the subagent Read the skill file?

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | Subagent Reads `skills/smith-clean-code/SKILL.md` (worktree copy; installed `~/.claude/skills/` fallback), targeting the named sections by HEADING (not line numbers — fragile) | Single source of truth — rubric edits propagate automatically; zero duplication; mirrors the repo's read-the-actual-file discipline. Costs one file read per pass. |
| B | Inline a compact rubric copy into the smith-build SKILL.md prompt block (like Phase 2's checklist) | Self-contained prompt; but creates a THIRD copy of the tenets that can drift — the exact "doc claims vs reality" antipattern this session's Ledger reinforces twice. |

**Recommended**: A — heading-anchored file Read; the drift risk of B is the antipattern this repo keeps re-learning.

**Answer**: A (recommendation accepted) — subagent Reads the skill file by section headings; worktree copy first, installed fallback.

---

## Q2: Which model runs the review subagent?

**Context**: research.md D2 — repo precedent uses Haiku for narrow/structured/non-blocking passes (reflection, navigate, questions-piping) and Sonnet-class for generative/architectural work. No LLM diff-review precedent exists.

**Question**: Haiku or Sonnet for the review-pass subagent?

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | Sonnet | This pass EDITS CODE on its own judgment (auto-fix) — closer to generative work than classification by the repo's own precedent split; better judgment on "behavior-preserving?" calls, where a mistake ships a broken fix. Costlier per build. |
| B | Haiku | Matches the rubric-classification precedent and is cheap — but the auto-fix half exceeds classification, and a wrong safe/unsafe call has real blast radius. |

**Recommended**: A — the auto-fix authority is what disqualifies Haiku; if cost bites later, a follow-up can split review (Haiku) from fixing (Sonnet).

**Answer**: A (recommendation accepted) — Sonnet for the review-pass subagent.

---

## Q3: Severity threshold for the "Clean Code Review" PR-body section?

**Context**: research.md D3. smith-clean-code's Low severity = minor formatting/consistency — listing every Low finding risks PR-body noise that trains readers to ignore the section.

**Question**: Which unresolved findings appear in the PR-body section?

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | Medium and above listed individually; Low findings as a one-line count ("+ N low-severity notes") | Signal stays high; nothing is hidden (count preserves visibility); mirrors how File Size Warnings stays terse. |
| B | All findings listed individually | Full transparency; noise risk on style-heavy diffs. |
| C | High and above only | Quietest; Medium issues (duplication, naming) vanish from reviewer view. |

**Recommended**: A — individual listing from Medium up, Low as a count.

**Answer**: A (recommendation accepted) — Medium+ listed individually; Low findings as a one-line count.

---

## Q4: Does smith-bugfix get a lightweight review pass too?

**Context**: research.md D4. The spec's core gives bugfix inline-checklist parity (generation-time). PR #49 precedent deliberately kept bugfix "lighter" (4-line pointer vs 22-line checklist). Bugfix is the streamlined low-latency workflow.

**Question**: Checklist parity only, or also an automated pass over the fix's diff?

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | Checklist parity only now; light pass considered later if build-side proves valuable | Preserves bugfix's speed; generation-time guidance still upgraded; smallest change; promotion path stays open. |
| B | Add a review-only (no auto-fix, no re-test) diff-scoped light pass with the same PR-body section | Verification coverage for bugfix diffs at moderate cost; no re-test complexity since nothing is edited. |
| C | Full build-equivalent pass (auto-fix + re-test) | Maximum conformance; heaviest addition to the workflow explicitly designed to be light. |

**Recommended**: A — parity now, evaluate promotion after the build-side pass has real mileage.

**Answer**: A (recommendation accepted) — smith-bugfix gets checklist parity only; automated pass deferred pending build-side experience.

---

## Q5: Does smith-implement get inline-checklist parity?

**Context**: research.md D5. smith-implement executes tasks.md and writes code; today it carries a single-line clean-architecture reference (PR #49).

**Question**: Extend the same checklist parity to smith-implement?

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | Yes — add the compact checklist block (same text as bugfix parity) | Consistent tenets across every code-writing skill; one small addition to an already-in-scope pattern. |
| B | No — out of scope; keep the single-line reference | Smaller diff; leaves one code-writing skill on the weakest guidance tier. |

**Recommended**: A — cheap and closes the last gap in generation-time coverage.

**Answer**: A (recommendation accepted) — smith-implement gets the same compact checklist block.

---

## Q6: How are auto-fix edits handled by the `.meta` description layer?

**Context**: plan.md flagged a spec premise gap (FR-9): smith-build has never proactively written `.meta` descriptions — its only mechanism is the passive 5.3.1 scan that FLAGS missing descriptions in the PR body. Auto-fixes that rename/extract methods create new method ids lacking descriptions.

**Question**: Proactive `.meta` update for auto-fix edits, or rely on the existing passive net?

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | Rely on 5.3.1's existing passive flag (reword FR-9 accordingly) | Consistent with smith-build's current design; zero new machinery in the review pass; misses surface as the already-established PR warning. |
| B | Review pass proactively runs the touched-methods `.meta` flow for its own edits (bugfix Phase 3.5 pattern) | Descriptions stay current without PR warnings; but imports the Task-spawn machinery into the pass — the first proactive `.meta` write in smith-build, scoped narrowly. |

**Recommended**: A — the passive net exists precisely for this; keep the pass lean.

**Answer**: A — rely on existing layered coverage: smith-new-launched builds already instruct .meta updates for every source edit (covers review-pass edits too); standalone builds fall back to the passive 5.3.1 flag. FR-9 reworded accordingly. (Clarified during gate: this is a narrow standalone-build gap, not a general ".meta not updated in workflows" issue.)
