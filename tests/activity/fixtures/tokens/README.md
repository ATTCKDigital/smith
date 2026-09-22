# `tokens/` — SC-11 token-rollup fixtures (T068)

Consumed by `tests/activity/test_usage.py`. Nothing here is staged through
`_fixtures.Fixture`: these are raw transcript files read by path, because what
is under test is the *reader*, not the replay harness.

## `parent-session.jsonl` — the SC-11 parent transcript

Seven lines, four of which must be ignored:

| Line | Shape | Must |
|---|---|---|
| 1 | `type: "user"` | be skipped |
| 2 | assistant, `isSidechain: false` | **count** |
| 3 | assistant, no `usage` key | be skipped, not crash |
| 4 | assistant, **`isSidechain: true`** | be skipped — 999999s make a leak loud |
| 5 | assistant, `isSidechain: false` | **count** |
| 6 | **torn JSON** (no closing brace) | be skipped, not abort the rollup |
| 7 | `type: "summary"` | be skipped |

Counted totals: `input 10`, `output 2000`, `cache_write 14000`,
`cache_read 75000`. The 999999 sentinel on line 4 is deliberate — if the
parent-side guard ever inverts, no assertion has to be subtle about it.

Line 6 is a **torn** line, not merely invalid: it is what a transcript being
appended to while it is read actually looks like, and it is the reason
`usage.tail_lines()` never advances its offset past the last `\n`.

## `agent-a4e8cbb1161fec729.jsonl` — the FR-36 sidechain transcript

The same file shape from the other side. `isSidechain: true` rows **count**;
the `isSidechain: false` row (888888 sentinel) must NOT, because the inverted
guard has to be a guard and not an absence of one. Counted totals:
`input 5`, `output 258`, `cache_write 13855`, `cache_read 24155`.

The first counted row is transcribed verbatim from `data-model.md` §4.3,
including its wrong `gitBranch: "main"` — that worktree was on
`60-activity-dashboard`. Nothing may read `gitBranch`.

## `agent-a4e8cbb1161fec729.meta.json` — the FR-27 sidecar

Verbatim from `contracts/hook-envelope.md` §3. `toolUseId` is what ties the
sidecar to the `PreToolUse` `Task` dispatch that created it.

## `workflow-a.jsonl` / `workflow-b.jsonl` — the SC-2 token half

One assistant row each, **different models on purpose** (`claude-opus-5` vs
`claude-sonnet-5`) so a rollup that merged the two workflows would be visible
in the `model` field and not only in the arithmetic. `@FIXTURE@` is substituted
with the staging root, matching the convention in `_fixtures.py`.
