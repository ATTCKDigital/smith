# Implementation Questions: Scheduled Audit Subsets

**Generated**: 2026-09-14
**Feature**: [spec.md](./spec.md)
**Plan**: [plan.md](./plan.md)
**Status**: ANSWERED

> All six answers accepted via the user's standing delegation ("continue all
> the way through all of them with as little feedback from me as possible"
> — auto-accept recommended answers, recorded here for the audit trail).
> Each recommendation is evidence-backed in the pre-feature exploration
> report (`.smith/vault/explore/explore-2026-09-14-scheduled-audits.md`),
> whose own "Gate recommendations (delegation)" line named exactly these
> six items. A seventh decision — whether `/smith-audit`'s marker-bootstrap
> fix covers interactive invocations too, not just `--scheduled` ones — is
> NOT included here: it was not one of the exploration's six named gate
> items, and this feature's task framing explicitly instructed evaluating
> and deciding it directly rather than routing it through delegation. See
> `spec.md`'s FR-18 for that decision and its rationale.

---

## Q1: Dispatch mechanism — new direct scheduler step, or route through `/smith-queue`?
**Options**: A) Extend the scheduler with a second, narrow step that
dispatches `claude -p "/smith-audit --all --scheduled <subsets>"` DIRECTLY,
independent of the `/smith-queue` pipeline. B) Wrap each scheduled audit as
a synthetic `/smith-queue` entry so it reuses the existing queue
infrastructure (worktree, PR, merge, history archival).
**Recommended**: A — the `/smith-queue` pipeline is merge-oriented
(worktree → build → PR → merge; a task is "completed" only after a real
merge) and is the wrong shape for a read-only, report-producing audit; B
would force a no-op PR/merge around a markdown report or silently break
the pipeline's own completion semantics (exploration finding 1).
**Answer**: A (accepted via delegation).

## Q2: Default headless-safe subset — five fixed categories, or the full 11 by default?
**Options**: A) Ship a default `subsets` list of five headless-safe
categories (`requirements`, `codequality`, `security`, `dependencies`,
`workflow`), with `infrastructure`/`performance`/`accessibility` as
configurable opt-ins, `ux`/`seo` as configurable opt-ins via their existing
MCP-first-with-fallback contract, and `feature` excluded always (interview
phase, no non-interactive substitute). B) Default to running all 11
categories on every scheduled run, same as an interactive `--all` audit.
**Recommended**: A — `--all` already avoids the ONLY interactive prompt
branch (empty-args system selection), but running all 11 categories by
default would still attempt `feature`'s interview phase in a
non-interactive context, hanging or failing every default-configured
scheduled run (exploration finding 2).
**Answer**: A (accepted via delegation).

## Q3: Gate-gap remediation — bootstrap a `maintenance` marker, or something else?
**Options**: A) Bootstrap an `.smith/vault/active-workflows/*.yaml` marker
via `scripts/create-active-workflow.sh --workflow maintenance` (reusing the
existing catch-all workflow type, same pattern `skills/smith-update/
SKILL.md`'s Phase 0 already uses) at the start of every `--scheduled`
invocation, cleared on every exit path. B) Add a new `smith-audit` entry to
`create-active-workflow.sh`'s `--workflow` allowlist instead of reusing
`maintenance`. C) Leave `/smith-audit` ungated and rely on the caller
already having an active marker (today's de facto, unaudited behavior).
**Recommended**: A — `create-active-workflow.sh`'s enum already has a
`maintenance` catch-all explicitly documented for "commands that
legitimately need to register a marker for the duration of their run" when
none of the four named workflow types fit; adding a dedicated `smith-audit`
enum value (B) is unnecessary surface area for zero behavioral gain, and C
leaves the real gate gap in place — a scheduled dispatch has no
already-active marker to borrow, so it would be denied outright on every
report write (exploration finding 3).
**Answer**: A (accepted via delegation).

## Q4: Report surfacing — dedicated naming + drift block + rolling log, or reuse existing naming as-is?
**Options**: A) Scheduled reports get their own `<date>-scheduled-<name>.md`
filename (distinct from interactive `<date>-full-spectrum.md`, avoiding
same-day collisions between an interactive and a scheduled run), a `##
Drift Since Last Scheduled Audit` section comparing against the prior
scheduled report's Executive Summary, and a rolling one-line append to
`.smith/vault/reports/audits-log.md` for cross-run visibility. B) Reuse the
existing `<date>-full-spectrum.md` naming unchanged, with no drift
comparison and no rolling log — a project owner would have to manually
diff report files to see trends.
**Recommended**: A — distinct naming avoids a same-day collision between an
interactive and scheduled run of the same project, and the drift
block/rolling log are the entire point of running this unattended and
repeatedly rather than once; `audits-log.md` requires no gate-marker or
gitignore-template change since `.smith/vault/reports/` is already
exempt/committed by default (exploration finding 4).
**Answer**: A (accepted via delegation).

## Q5: Config default posture — `enabled: false`, or `enabled: true` out of the box?
**Options**: A) `scheduled_audits.enabled: false` MANDATORY as the shipped
default — a project must explicitly opt in before any unattended dispatch,
marker bootstrap, or report-writing behavior can occur. B) Ship
`enabled: true` by default so projects get scheduled audits automatically
once they update Smith.
**Recommended**: A — an unattended process that writes report files and
creates workflow markers should never activate itself without explicit
project-owner consent, matching this pipeline's existing "ship no opinion
beyond stated defaults" precedent for every other advisory-check config key
(`security_review`, `supply_chain`, `quality` all ship enabled/populated
only where the behavior is non-destructive; `scheduled_audits` writes files
autonomously on a timer, which is a materially bigger default-on risk).
**Answer**: A (accepted via delegation).

## Q6: Cadence state storage — a new gitignored state file, or fold into `.smith/config.json`?
**Options**: A) A dedicated, gitignored `.smith/vault/.scheduled-audits-
state.json` file, written write-after-success only, with ONE new line
added to the managed `.gitignore-smith-additions` template. B) Store
`last_run` directly inside `.smith/config.json`'s `scheduled_audits` key —
no new file, no template change.
**Recommended**: A — `.smith/config.json` is user-edited, version-controlled
project configuration; mixing autonomously-written, per-machine mutable
runtime state into it risks a user's manual edit racing an autonomous
write, and risks that state being accidentally committed/shared across
machines/teammates when it should stay local (mirroring the existing
`.smith/vault/.current-session`/`.active-workflow` pattern, both already
gitignored dotfiles under `.smith/vault/` for exactly this reason)
(exploration finding 5).
**Answer**: A (accepted via delegation).

---

Plan-level mechanical resolutions (not gate matters, recorded):
`scheduled_audits` config key placed after `quality`, before
`context_budget` in `templates/config.default.json`, continuing that
file's existing feature-append insertion order; `<name>` in the
`<date>-scheduled-<name>.md` filename is the validated subset list
hyphen-joined in configured order (no truncation — worst case ~10
categories is still well within filesystem path-component limits, and no
existing report filename in this repo applies a length guard either);
`--scheduled` dispatch grammar is `/smith-audit --all --scheduled
<comma-list>` (comma, not space, separating subset tokens — avoids
ambiguity with `$ARGUMENTS`' own space-delimited flag tokenization);
`is_audit_due()` is date-only (calendar days), never time-of-day, so a run
starting just after midnight UTC doesn't get a spuriously short next
interval; PDF generation is skipped by default in scheduled mode
(`skip_pdf: true`) since an unattended nightly runner may lack
`npm`/`puppeteer` and a client-facing PDF has no unattended audience
anyway.
