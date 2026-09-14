# Release: Scheduled Audit Subsets

**Date**: 2026-09-14
**Branch**: 58-scheduled-audits
**PR**: #TBD
**Spec**: [spec.md](spec.md)

## Summary

The Smith scheduler gains a second, narrow responsibility: when a project opts in (`scheduled_audits.enabled: true` — false by default), a cadence-gated step dispatches `claude -p "/smith-audit --all --scheduled <subsets>"` directly (the queue's merge-shaped pipeline deliberately bypassed). smith-audit gains a scheduled mode: headless-safe subset validation (feature sub-audit refused), a maintenance-marker bootstrap fixing the pre-existing gate gap for BOTH scheduled and interactive runs, `<date>-scheduled-<name>.md` reports topped with a Drift block (severity-count deltas vs the previous scheduled run), a rolling `.smith/vault/reports/audits-log.md` (gate-exempt, team-synced), and write-after-success state.

## Changes
scheduler/smith-scheduler.sh (+134: is_audit_due() + audits step + DRY_RUN hook + counters; queue-loop body byte-identical); smith-audit SKILL (Phase 0 scheduled mode/marker, drift, log, skip_pdf, state contract); config scheduled_audits key + init/update §5.1f seeding + ONE gitignore-template line for the state file; docs/scheduler.md audits-step section; docs/security-model.md paragraph + stale "mode: autonomous"→complexity fix; CHANGELOG; NEW tests/scheduler/ (18 assertions) + seed-test assertion.

## Testing
- tests/scheduler: 8/8 + 10/10 under bash AND zsh (dry-run proves no claude spawn via PATH-stub sentinel); seed test 20/20; full 43-file regression green except 3 pre-existing failures in untouched files (--describe drift family); dry-run e2e exact dispatch-line assertion; NFR greps clean.
- Phase 3.5 review: 1 Low auto-fixed (test fixture-path helper extraction), 0 Medium+; 2 Low notes.
- Dogfood: secret scan clean.

## Deviations
- FR-18 scope-widening: marker bootstrap covers interactive audits too (same code path; fixes a pre-existing gate gap smith-audit always had).

## Infrastructure
None (LaunchAgent unchanged; Linux remains manual cron, documented).
