---
reported: 2026-07-30
status: fixed (PR #54, merged 2026-07-30 as 3ac9f15)
severity: degraded
primary_system: none — skills distribution / sync pipeline (un-systematized; no matching .specify/systems/ folder)
also_affects: []
trigger: Another project's development session observed that the smith-debug session log lands in .smith/vault/sessions/ (swept by smith-sync) while the debug report lands in .specify/ (never swept)
error: "Debug reports written to .specify/systems/<system>/debug/ are never committed or pushed; smith-sync's staging-discipline assertion structurally excludes them"
---

# Debug: smith-debug reports are never committed — smith-sync sweep excludes `.specify/`

## Symptom

- **Error:** Debug reports produced by `/smith-debug` (path: `.specify/systems/<system>/debug/debug-YYYY-MM-DD-<slug>.md`, or `.specify/debug/` un-systematized) accumulate as untracked files and are never committed or pushed. Teammates never receive them, despite skill documentation claiming they are shared.
- **Trigger:** End of any `/smith-debug` run in a consumer project — the mandated post-workflow `/smith-sync` sweeps session logs but not the report.
- **Conditions:** `/smith-sync` stages only `.smith/` (`git add .smith/`) and its staging-discipline assertion aborts the sync if anything outside `.smith/` is staged. No other workflow stages `.specify/**/debug/` either.
- **Frequency:** Always — the exclusion is structural, not intermittent.
- **Affected components:** `skills/smith-sync/SKILL.md`, `skills/smith-debug/SKILL.md`, `skills/smith-bugfix/SKILL.md` (documentation claim).

## Evidence

### Dependency Trace (artifact-flow analysis)

Traced every path by which a `.specify/**/debug/` report could reach a git commit. **None exists.**

- `skills/smith-sync/SKILL.md:74` — staging surface is exactly `git add .smith/`; lines 77-78: "NEVER `git add -A` or `git add .` — staging is scoped to `.smith/`".
- `skills/smith-sync/SKILL.md:98-105` — staging-discipline assertion:
  ```bash
  OUTSIDE=$(git diff --cached --name-only | grep -v '^\.smith/' || true)
  if [ -n "$OUTSIDE" ]; then
      echo "/smith-sync: ABORT — staged paths outside .smith/ detected:"
      git reset -- $OUTSIDE ...
      exit 1
  fi
  ```
  Even an accidentally-staged report is unstaged and the sync aborts. The exclusion is a guarantee, not an oversight in execution.
- `skills/smith-debug/SKILL.md` Phase 2 (line ~156) sets the report path under `.specify/`; Phase 5 (line ~245) writes it there. The workflow itself contains no `git add`/`git commit` of the report (read-only by design).
- Other skills checked — none stage debug reports:
  - `smith-finish` (lines 155-160): stages specific `spec.md` files + CHANGELOG/STATUS only.
  - `smith-build` (lines 279-280, 637-638): stages explicitly-listed modified files + `release.md`; spec-update phase touches only `spec.md`.
  - `smith-new` (lines 372-373): stages a feature-spec folder (spec/plan/questions/etc.) — different artifact family.
  - `smith-bugfix` Phase 7 (lines 309-310): stages only code files modified by the fix; nothing instructs staging the debug report it consumed.
  - `smith-implement`: no git operations touching `.specify` debug paths at all.
- Hooks and `.specify/scripts/`: nothing commits `.specify` paths.
- Installer gitignore template (`skills/smith-index/templates/.gitignore-smith-additions`): governs only `.smith/` paths; **silent on `.specify/`** — so in consumer projects reports are committable, just never staged by anything.

### Documentation contradiction (the false premise)

- `skills/smith-debug/SKILL.md:404-411` ("Post-Workflow Sync"): *"it DOES write debug reports and session history into `.smith/`, which we want shared"* — **factually wrong about its own output path**; Phase 2/5 write reports to `.specify/`, only the session log goes to `.smith/vault/sessions/`.
- `skills/smith-bugfix/SKILL.md:419-428`: sync sweep description says teammates receive "the updated context (**including any debug reports** and the session log)" — impossible given `git add .smith/` scope declared two lines earlier.

### Spec & History

- Introduced in commit `9dd94c1` (2026-06-05, PR #41) — the **same commit** created smith-sync (with correct `.smith/`-only discipline) and added the Post-Workflow Sync sections containing the false premise. The bug shipped fully-formed; it is not a regression.
- Empirical confirmation in this repo: `git log --oneline --all -- '.specify/'` → **zero commits, ever**. `git check-ignore` confirms `.specify/` is *not* gitignored here — it is simply never staged.
- Live victim: `.specify/systems/system-config-memory/debug/debug-2026-06-11-datetime-stamp.md` — a diagnosed report, 49 days old, still untracked.
- No matching GitHub issues found (`debug report commit`, `smith-sync specify`).
- `docs/bugs/` contains one unrelated entry (2026-06-02 staged-parsers dir mismatch).

## Root Cause

`/smith-sync`'s `.smith/`-only staging scope and abort-on-outside-path assertion are working as designed. The defect is the **false premise written into the workflow docs in `9dd94c1`**: the Post-Workflow Sync sections of smith-debug (and, copied from it, smith-bugfix) assert that debug reports land in `.smith/` and are therefore swept — but smith-debug's own Phase 2/5 write them to `.specify/systems/<system>/debug/`, which the sweep structurally excludes and no other workflow ever stages. Result: session logs are shared, reports are silently orphaned, and the docs tell operators the opposite.

### Confidence: confirmed

Static trace covered every skill, hook, and script with git operations (no commit path exists); empirical git history shows `.specify/` has never been committed in this repo despite holding a real report for 49 days; and the introducing commit shows both the mechanism and the false claim arriving together.

## Recommended Action

- [x] **Fix via `/smith-bugfix`** — widen the smith-sync sweep to include debug reports and correct the false doc claims:
  1. `skills/smith-sync/SKILL.md`: stage debug paths alongside `.smith/` — `git add .smith/ .specify/systems/*/debug/ .specify/debug/` (globs no-op when absent).
  2. Update the staging-discipline assertion to allow `^\.smith/` OR `^\.specify/(systems/[^/]+/)?debug/`; anything else still aborts.
  3. Add an `N_DEBUG` count to the sync commit-message summary block.
  4. Update smith-sync's title/description to "…`.smith/` artifacts and debug reports".
  5. Fix `skills/smith-debug/SKILL.md:404-411` — reports are written to `.specify/**/debug/` and are now swept by the widened sync.
  6. Fix `skills/smith-bugfix/SKILL.md:427` — same correction.
  7. Optional hardening: smith-debug Phase 6 completion output states whether the report was committed, so a skipped/failed sync is visible.
- [ ] **Config change** — n/a (no runtime config involved).
- [ ] **Known limitation** — rejected: docs claim sharing works, so silence is misleading, not accepted behavior.
- [ ] **Needs deeper investigation** — none required; root cause confirmed.

**Rejected alternative:** relocating reports into `.smith/vault/debug/` so the existing sweep covers them unchanged — breaks per-system organization, breaks smith-bugfix's cross-reference paths, and in repos that gitignore `.smith/` wholesale (like this dev repo) would make reports permanently uncommittable.

## Related

- Introducing commit: `9dd94c1` — "feat: /smith-sync skill — sweep & share .smith/ artifacts, chained into workflows" (PR #41, 2026-06-05)
- Orphaned report (live evidence): `.specify/systems/system-config-memory/debug/debug-2026-06-11-datetime-stamp.md`
- `skills/smith-sync/SKILL.md` (staging scope + assertion), `skills/smith-debug/SKILL.md` (Phases 2/5, Post-Workflow Sync), `skills/smith-bugfix/SKILL.md:419-428`
- Note: in this dev repo `.gitignore` blanket-ignores `.smith/`, so smith-sync no-ops here entirely; the symptom manifests in consumer projects where `.smith/` artifacts are committable. The fix must also decide whether the widened sweep should still run when `.smith/` stages nothing but debug reports exist (currently step 4 would no-op before reaching them — the widened `git add` resolves this since staged debug files make the diff non-empty).
