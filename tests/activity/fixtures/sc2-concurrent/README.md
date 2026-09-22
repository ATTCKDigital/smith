# SC-2 — two concurrent workflows, one session log

Transcribed from this repository's own
`.smith/vault/sessions/dennis-plucinik_ad8161_2026-09-22_145028.md`, which
carried `workflow-start 67-deterministic-questions` at line 287 and
`workflow-start 60-activity-dashboard` at line 310 — two `/smith-new` runs, two
worktrees, one log file.

Three properties a synthetic fixture would not have:

1. **Both markers are the same `workflow:` type.** Rule 3's chain match cannot
   separate them, so every `Subagent invoked:` block here is genuinely
   ambiguous and must be DROPPED. That is the case the design is judged on.
2. **The clocks disagree by four hours.** `[15:18:00]` (hook, UTC) is followed
   by `[11:18:56]` (model, local). Any resolver that sorted on the parsed stamp
   would reorder the stream; ordering is on ingest `seq` alone (FR-58).
3. **Only the `workflow-start` records name their branch**, which is why they
   attribute cleanly by rule 2 while the blocks around them do not.

The steppers still advance, on the hook events — each carries the `cwd` of its
own worktree, so rule 1 separates them. That is FR-21's trust hierarchy doing
the work: hook events are the spine, model-authored blocks are annotation.
