# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Weighted-rubric compliance system** — Smith now ships a global `~/.claude/CLAUDE.md` template (`settings/claude-md-template.md`) with 7 rules totaling 100 points, each with binary all-or-nothing sub-criteria a Haiku critic can grade against. Weights reflect frequency and impact: Rules 1 & 2 (questions-are-not-actions, SpecKit triggers + skill-process compliance) carry 25 each as they evaluate every turn; Rules 3 & 4 (question files, checkpoint/resume) carry 15 each as per-task rules; Rule 5 (session logging) carries 10; Rules 6 & 7 (general preferences, directory setup) carry 8 and 2 as stylistic/environmental checks. Inapplicable rules auto-pass full credit.
- **New hook: `grade-response.sh`** — Stop hook that grades each response against the rubric in `~/.claude/CLAUDE.md` via `claude --model haiku -p`. Exits 2 to block the stop and force a retry when score < 100, capped at 3 retries per turn (via `/tmp/claude-grade-retry-<session-id>`) to prevent infinite loops. Fails open on any error (missing transcript, bad JSON, unreachable critic). Anti-recursion via `stop_hook_active` JSON field check. Registered as a separate Stop entry from `session-end-review` and `workflow-summary` so it can be toggled independently in `settings.json`.
- Installer now writes the global rubric to `~/.claude/CLAUDE.md` (backing up any existing file as `CLAUDE.md.bak-<timestamp>`, matching the settings.json backup pattern). Uninstaller offers to restore from the most recent backup, or to remove the Smith rubric outright if no backup exists.
- Install via `npx skills add ATTCKDigital/smith` — new distribution path that copies all 26 skills into `~/.claude/skills/` without requiring the curl installer. Skills-only; hooks and scheduler still require the bundled installer.
- New skill in the public distribution: `/smith-audit` — cross-system audit orchestrator. Previously only in the agency-internal skill set; now shipped with the public Smith distribution.
- New skill: `/smith-explore` — pre-change impact analysis for features touching core infrastructure
- New hook: `metrics-tracker.sh` — PostToolUse hook that captures character counts for token estimation
- Workflow metrics summary — primary workflows (smith-new, smith-bugfix, smith-debug) now display aggregated metrics at completion: estimated tokens, tool calls, subagent stats, duration
- Subagent metrics logging — SubagentStop hook now captures `total_tokens`, `tool_uses`, `duration_ms` and logs to session files
- `workflow-summary.sh --totals-only` — lightweight mode that prints just `Total tokens used` and `Total duration` to stdout for skills to include inline in the final chat message (Stop-hook stdout doesn't reach the preceding assistant bubble, so the two-line totals are now emitted by the skill before Stop fires)
- **Accurate workflow summary (normalized tokens + USD + active duration).** The completion summary now displays three defensible numbers: (a) normalized token usage via fixed-weight formula `input + 5×output + 1.25×cache_create + 0.1×cache_read`, (b) estimated USD cost looked up from a new `hooks/pricing.json` table with per-model-family rates and `last_verified` metadata, (c) active duration excluding idle user-input waits (gap detection on main-session tool timestamps with a 120s idle threshold and 600s cap for legitimate long Bash runs, plus sum of subagent `duration_ms`). Real main-session tokens are now parsed from the parent JSONL at `~/.claude/projects/<slug>/<session-id>.jsonl` instead of estimated from tool-I/O character counts. Fuzzy model matching uses longest-prefix-first ordering so `claude-opus-4-6` correctly resolves to the $5/$25 tier rather than sharing rates with `claude-opus-4-0` ($15/$75). Unknown model IDs are transparently annotated in the cost line. See `specs/003-accurate-workflow-summary/` for the full design.
- `hooks/pricing.json` — checked-in pricing table verified against platform.claude.com/docs/en/docs/about-claude/pricing on 2026-04-14. Each entry carries `source_url` and `last_verified` metadata for staleness visibility.
- `hooks/workflow_summary_lib.py` — Python library factored out of `workflow-summary.sh`'s heredoc so formulas are unit-testable.
- `tests/` directory (new at repo root) with a stdlib-only `unittest` suite. Run with `python3 -m unittest discover tests`. 49 tests covering normalized formula, USD formula, active-duration gap detection, fuzzy model matching, and v1/v2 subagent-block parsing.
- Subagent completion blocks in session logs now include the full usage breakdown: `model`, `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens` alongside the existing `tool_uses`, `duration_ms`, and `total_tokens` (kept as a legacy alias).

### Fixed

- 7 skills (`smith-bank`, `smith-explore`, `smith-ledger`, `smith-migrate-specs`, `smith-report`, `smith-todo`, `smith-vault`) were silently skipped by `npx skills add . --list` because their `argument-hint:` frontmatter value started with `[` followed by multiple space-separated bracketed groups — a YAML flow-sequence construct the `skills` CLI parser rejects. Wrapped all affected values in double quotes so YAML treats them as plain string scalars. Claude Code's own parser already tolerated the unquoted form, so local invocation was never affected; only the external CLI was. See [specs/013-distribution-readiness/research.md](specs/013-distribution-readiness/research.md) for the diagnosis.
- `Total tokens used` and `Total duration` now appear in the user-facing "Feature/Bugfix/Debug complete" chat message. Previously these only landed in the session log file because the Stop hook's stdout doesn't flow into the assistant message that already shipped. Skills (`/smith-new`, `/smith-bugfix`, `/smith-debug`) now invoke `workflow-summary.sh --totals-only` and paste the two lines into their final summary before Stop fires. The full `=== Workflow Summary ===` audit block continues to be appended to the session log file by the Stop hook
- Workflow token count was previously a raw sum of `input + output + cache_create + cache_read` at 1× weights across all models, which inflated the number 3–10× vs. what Anthropic actually bills (cache reads are 0.1× and cost varies by model tier). The summary now displays normalized tokens (fixed-weight formula) and estimated USD cost (per-model pricing lookup), with the raw breakdown relegated to the session-log audit block. Addresses the observation that a single smith-new workflow could show 30M+ tokens — a figure that was technically correct per the formula but misleadingly high for a public repo

### Changed

- **Renamed skill:** `/smith.init` → `/smith`. The `skills/smith/SKILL.md` frontmatter now declares `name: smith` (previously `name: smith.init`), matching the folder name. Invocations of `/smith.init` no longer match; use `/smith` instead. This aligns with the `skills` CLI's expected folder/name convention.
- `hooks/workflow-summary.sh` now resolves `workflow_summary_lib.py` via a priority chain (`$CLAUDE_HOOKS_DIR` → `~/.claude/hooks` → sibling of `$0`) instead of only the sibling directory. This allows a single installed copy at `~/.claude/hooks/workflow-summary.sh` to serve as a Stop hook across all projects without each project vendoring its own copy of the Python lib and `pricing.json`. If none of the candidates contain the lib, the wrapper prints a stderr note and exits 0 (consistent with existing degrade-gracefully behavior).
- The chars/4 character-count estimate is no longer displayed as "Estimated tokens" in the workflow summary. The per-tool `metrics-tracker.sh` log lines remain unchanged (useful for spotting heavy tool uses), but the summary block now uses real Anthropic-reported token counts from the parent-session JSONL instead.
- Active workflow tracking now uses per-branch files (`.smith/vault/active-workflows/<branch>.yaml`) to support concurrent workflows in different worktrees
- `subagent-vault-writeback.sh` enhanced to capture and log subagent metrics
- `/smith-bugfix` Phase 1 rewritten to always run in an isolated worktree branched from `origin/main`. No more "switch to main / stash / cancel" prompt when the user is on a non-main branch — the user's working tree and branch are never touched, and concurrent Smith sessions can't collide on the shared working tree. Matches the worktree-always model already used by `/smith-new`.

- `/smith-new` now includes Phase 0 exploration when features touch `.claude/skills/`, `.smith/`, or `.specify/`
- `/smith-bugfix` no longer updates CHANGELOG.md (vault session logs handle this)
- All skills now capture verbatim user requests in vault logs with `**User Request:**` field
- File Purpose Policy added to constitution.md §VI (constitution.md / CLAUDE.md / MEMORY.md scopes)

## [0.1.0] - 2026-04-11

### Added

- Initial release with 25 Smith skills for spec-driven development
- 8 hooks for session logging, security guards, and workflow routing
- macOS scheduler (LaunchAgent) for overnight queue processing
- Install and uninstall scripts with settings.json merge via jq
- Settings fragment for Claude Code hook configuration
- Documentation: getting started, security model, hooks reference, scheduler guide, architecture overview
- GitHub CI: skill linting and install smoke test
- Issue templates: bug report, feature request, skill proposal
- MIT license

[Unreleased]: https://github.com/ATTCKDigital/smith/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ATTCKDigital/smith/releases/tag/v0.1.0
