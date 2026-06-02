---
feature: 20-manifest-fixes
branch: 20-manifest-fixes
generated: 2026-05-28
status: ANSWERED
spec: ./spec.md
plan: ./plan.md
note: Reconstructed 2026-06-02 from conversation after /tmp/ was cleared. Q1-Q8 answered; Q9-Q11 open. Other artifacts (spec, plan, data-model, contracts) regenerate via subagent after gate completes.
---

# Implementation Questions: Manifest System v2 Fixes

11 questions. Q1-Q5 carried forward from the first gate. Q6-Q11 emerged after the design pivot to `.meta`-resident LLM-generated descriptions (Tracks B/C redefined; source files never modified).

---

## Q1: Track sequencing — one PR or three?

**Answer:** A — one bundled PR for all three tracks.

## Q2: A3 migration skill — new skill or extend `/smith-migrate-specs`?

**Answer:** A — new skill `/smith-migrate-system-paths`.

## Q3: A1/A2 scope — create a NEW system-spec template + init sub-step?

**Answer:** A — full scope: new system-spec-template.md + new `/smith init` sub-step.

## Q4: `.meta` description-coverage enforcement — hard or soft?

**Reframed from original:** the enforcement target is `.meta` description coverage of the diff (Track C's `.meta`-resident-descriptions model), not source docstrings.

**Answer:** C — both: soft guidance in smith-new/bugfix/debug + hard `.meta`-coverage flag in `/smith-build` PR description (never blocks the PR).

## Q5: `/smith-index` bulk `.meta` description generation — approval granularity?

**Reframed from original:** `/smith-index` bulk-generates `.meta` descriptions for an existing codebase (per-method + per-module, LLM-driven, writes to `.meta` only — never source). How does the user approve?

**Answer:** B — per-batch (~20 files, configurable) with per-file reject + Rule 4 checkpoint/resume.

## Q6: A4 resolver — multi-system path tie + glob support?

**Answer:** A — longest-prefix wins for ties; literal prefixes only (no globs in v1; globs deferred to v3).

## Q7: Description granularity — per-method, per-module, or both?

**Answer:** C — both, with a configurable per-method threshold (skip trivial accessors / data-config files); always per-module. Threshold=0 yields full per-method coverage.

## Q8: `.meta` description length — per-module and per-method?

**Answer:** B — per-module ~one line (~120-char soft cap); per-method one-to-two sentences (~200-char soft cap).

---

## Q9: Staleness handling for out-of-workflow edits?

**Context:** A file edited outside any smith workflow (hand edit, `git pull`, rebase) gets fresh structure from the save hook (LLM-free) but stale or empty descriptions, because the save hook never generates descriptions. The lag persists until the next `/smith-index` or smith-workflow touch. The spec accepts the lag; this question is how visibly to surface it.

**Options:**
| Option | Description | Implications |
|--------|-------------|--------------|
| A | Accept silently — descriptions just lag; no flagging. `/smith-index` reconciles on next run. | Zero added hook work. Stale descriptions can silently mislead the navigator. |
| B | Flag via hash mismatch — `manifest-updater.sh` records a `Described-Against-Hash` and marks `.meta` description stale when structure changes since generation; `/smith-navigate` warns when routing on stale data | LLM-free staleness signal. Navigator can downrank/disclose stale descriptions. Slightly more save-hook bookkeeping (still structural-only). |
| C | Auto-queue — on hash mismatch, enqueue the file for re-description (smith queue) so the next `/smith-index --resume` or scheduled run refills it | Self-healing. Adds queue dependency + regeneration trigger; risk of unbounded queue growth on a big `git pull`. |

**Recommended:** **B** — flag via hash mismatch. Keeps the hook structural-only, gives the navigator a real "this description may be stale" signal, leaves bulk regeneration where it belongs (explicit `/smith-index`). Auto-queue (C) is a reasonable v3 follow-on once the staleness marker exists.

**Answer:** B — flag via hash mismatch (`Described-Against-Hash` in `.meta`; navigator surfaces staleness). Auto-queue deferred to v3.

---

## Q10: Bulk `/smith-index` LLM cost/time — model, batching, mode, checkpoint?

**Context:** On a large codebase (e.g. armory ~400 files × many methods) bulk description generation is thousands of LLM calls. This bundles the operational controls: model choice, batching/concurrency, whether generation is always-on or behind a `--describe` flag, and the checkpoint/resume + logging contract required by Rule 4.

**Options:**
| Option | Description | Implications |
|--------|-------------|--------------|
| A | Haiku 4.5; batched (N=10); `--describe` flag (structure-only index by default, descriptions on demand); Rule 4 per-file checkpoint + JSONL log + `--resume`; hash-cached re-runs skip unchanged already-described files | Fast structural rebuild stays default; LLM cost explicit + opt-in; large runs resume cleanly. |
| B | Haiku 4.5; batched; **always-on** (every `/smith-index` regenerates/fills missing descriptions); same checkpoint/resume + logging | Manifest always maximally rich; every index incurs LLM cost; no fast structure-only rebuild. |
| C | Larger model (Sonnet) for higher-quality descriptions; `--describe` flag; checkpoint/resume | Better descriptions; materially higher cost/time; likely overkill for per-method summaries. |

**Recommended:** **A** — Haiku 4.5, batched (N=10), behind a `--describe` flag, with Rule 4 checkpoint/resume (per-file granularity), JSONL log at `logs/smith-index-describe-<timestamp>.jsonl`, and hash-caching so re-runs skip unchanged already-described files. Keeps fast structure-only rebuild as default, makes LLM cost explicit, satisfies Rule 4, matches v1's Haiku choice for `/smith-navigate`.

**Answer:** A — Haiku 4.5, batched N=10, `--describe` flag (opt-in), Rule 4 per-file checkpoint + JSONL log + `--resume`, hash-cached skip-unchanged on re-runs.

---

## Q11: Workflow `.meta` update scope — touched method only, or whole file?

**Context:** When a smith workflow (`/smith-new`, `/smith-bugfix`, `/smith-debug`) edits code and updates the file's `.meta` descriptions (C1), does it regenerate the per-method description for only the added/edited method, or for all methods in the touched file? In-context regeneration is cheap (Claude just read/wrote the code), but blanket regeneration costs more tokens and could churn descriptions the user already accepted.

**Options:**
| Option | Description | Implications |
|--------|-------------|--------------|
| A | Touched methods only — add/update the description for each method the diff added or edited; leave others' descriptions untouched; refresh per-module description if file purpose materially changed | Minimal churn, cheapest, respects accepted descriptions. Other methods can drift. |
| B | Whole file — regenerate per-method descriptions for every method in the touched file plus per-module description | Consistent + fresh in one pass; more tokens; overwrites possibly hand-tuned descriptions. |
| C | Touched methods always; whole file only when per-module description is empty/stale (hash mismatch from Q9) | Targeted by default, opportunistically backfills never-described / stale files while they're already open. |

**Recommended:** **A** — touched methods only (plus per-module description when file purpose shifts). Matches the "cheap because in-context" rationale, minimizes churn, respects already-reviewed descriptions. Whole-file refresh belongs to `/smith-index --describe` (C2). Option C is a reasonable enhancement if empty/stale files prove common.

**Answer:** A — touched methods only (plus per-module description when the file's purpose shifts). Whole-file refresh remains the job of `/smith-index --describe`.
