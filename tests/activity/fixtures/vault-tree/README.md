# `vault-tree` — the T103 fixture vault

A realistic `.smith/` for `scripts/activity/vault.py` to read.

**Why the directories are not named `.smith/`.** The repo's `.gitignore`
ignores `.smith/` at line 2, globally and unanchored, so a fixture stored at
its real path would exist on the author's disk, be invisible to git, and fail
in CI with "no vault snapshot" — the fixture would be the only thing missing
and nothing would say so. `tests/activity/test_vault.py` therefore stages
`vault/` → `<tmp>/.smith/vault/` and `index/` → `<tmp>/.smith/index/` before
each test, which is the same staging shape `_fixtures.py` already uses for
markers.

Contents are chosen so every section of `data-model.md` §2.8 has something
non-empty to report, and so the counts are all *different numbers* — a
snapshot where every count is 1 cannot distinguish a working reader from one
that returns the wrong section.

| Source | Fixture | Expected |
|---|---|---|
| `sessions/*.md` | 2 logs, one `active`, one `completed` | newest first by mtime |
| `ledger/meta.yaml` | authoritative tally | `patterns: 4`, `antipatterns: 2` |
| `bank/` | 2 ideas with frontmatter | `count: 2` |
| `agents/<type>/` | `general: 3`, `Explore: 1` | per-type counts |
| `queue/` + `queue/history/` | 1 pending, 2 history | `depth: 1`, `history_count: 2` |
| `index/` | manifest + config | `schema_version: 1`, `file_count: 42` |
