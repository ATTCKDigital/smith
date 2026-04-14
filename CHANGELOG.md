# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- New skill: `/smith-explore` — pre-change impact analysis for features touching core infrastructure
- New hook: `metrics-tracker.sh` — PostToolUse hook that captures character counts for token estimation
- Workflow metrics summary — primary workflows (smith-new, smith-bugfix, smith-debug) now display aggregated metrics at completion: estimated tokens, tool calls, subagent stats, duration
- Subagent metrics logging — SubagentStop hook now captures `total_tokens`, `tool_uses`, `duration_ms` and logs to session files

### Changed

- Active workflow tracking now uses per-branch files (`.smith/vault/active-workflows/<branch>.yaml`) to support concurrent workflows in different worktrees
- `subagent-vault-writeback.sh` enhanced to capture and log subagent metrics

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
