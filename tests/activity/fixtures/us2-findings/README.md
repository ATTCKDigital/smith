# US-2 divergence and absence inputs (T043)

Five pairs, one per clause of the task:

| Sub-fixture | Clause | Shape |
|---|---|---|
| `a-missing-block/` | (a) | two `PreToolUse` `Task` dispatches, only ONE of which has a matching `Subagent invoked:` block. The omission is deliberate. |
| `b-artifacts.json` | (b) | an artifact observation with `order` ahead of any dispatch in the attributed stream, plus a corroborated one that must NOT fire |
| `c-skipped-phase/` | (c) | Phase 2 never signalled while 1 and 3 were — a non-gate skip, so exactly one `phase_skipped` |
| `c-skipped-gate/` | (c) | Phase 4 → Phase 6 with the MANDATORY STOP Phase 5 never signalled |
| `d-agents.json` | (d) | three `claude agents --json` records: one whose `status` disagrees, one whose `status` agrees, one with **no** `status` at all |
| `e-settings-unreadable.json` | (e) | deliberately truncated JSON — FR-60's "absence detection is DISABLED" path |
| `e-settings-readable.json` | (e) | a valid settings object wiring three hooks |
| `e-shipped-hooks.json` | (e) | an installer-staged manifest naming one hook the readable settings do NOT wire |

`a-missing-block/` and both `c-` directories are full replay fixtures loaded by
`_fixtures.Fixture`; the `.json` files are plain inputs the test hands straight
to `findings.py` / `absence.py`, which take them as already-parsed data.
