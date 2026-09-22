# `/smith-activity` replay fixtures

Every fixture here is **data only**. Expectations live in
`tests/activity/test_phases.py` and `tests/activity/test_findings.py`, so a
fixture can never assert itself true.

`@FIXTURE@` is substituted by `tests/activity/_fixtures.py` with the absolute
path of the staging directory it unpacks into. Markers therefore carry real
absolute `worktree:` and `session_log:` paths at replay time, exactly as
`create-active-workflow.sh` writes them, and `markers.read_marker` is used
unmodified rather than a test-local imitation.

## Ordering (FR-58)

Session-log records are stamped with an ingest `seq` of `10 * (index + 1)` by
the loader — that is what the daemon's tailer does, in append-offset order.
Hook events in `events.json` name the log record they follow with `"after"`,
and the loader gives them `seq + 1`, `seq + 2`, … So the two streams merge into
one monotonic sequence without any fixture hard-coding a number, and **no
parsed `[HH:MM:SS]` stamp participates in ordering anywhere.**

The `[HH:MM:SS]` stamps are deliberately inconsistent: hook-written lines carry
UTC and model-authored blocks carry local wall time, four hours apart. That
skew is copied from this repository's own
`sessions/dennis-plucinik_ad8161_2026-09-22_145028.md` and is the property that
makes these fixtures worth having.

`at` is the daemon's own ingest timestamp, synthesized by the loader from
`seq`. It is the only timestamp the resolver is allowed to read.

## Fixtures

| Directory | Owns | Proves |
|---|---|---|
| `sc1-new-to-build/` | T031 | SC-1 — a full `smith-new` → `smith-build` run, two real markers, the nested handoff, the questions gate |
| `fr20-exhausted/` | T033 | FR-20 — signals exhausted resolves to `phase unknown` with a last known phase |
| `sc2-concurrent/` | T049 | SC-2 — one session log, two workflows, mixed clocks, zero cross-attribution |
| `us2-findings/` | T043 | FR-22 / FR-23 / FR-57 / FR-60 / FR-61 divergence and absence inputs |
