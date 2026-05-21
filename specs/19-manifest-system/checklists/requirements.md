# Quality Checklist — spec.md for 19-manifest-system

Specific quality bar for THIS spec. Each item is binary: the spec either satisfies it or it doesn't.

## Structure & Frontmatter

- [ ] YAML frontmatter present with `feature`, `branch`, `created`, `status` fields
- [ ] Feature title matches the brief: "Manifest System & Structured Context Retrieval"
- [ ] All required sections present in order: Summary, Goals, Non-Goals, Users/Stakeholders, Requirements, Design Decisions, Hard Constraints, Acceptance Criteria, Open Questions, Assumptions, References
- [ ] Datetime + branch footer present on last line: `YYYY-MM-DD HH:MM:SS — 19-manifest-system`

## Summary Quality

- [ ] Summary frames the problem (soft natural-language navigation is unreliable, wastes tokens, misses files) in plain language
- [ ] Summary frames the solution (precomputed hierarchical manifest + Haiku navigator + UserPromptSubmit injection) before going into mechanics
- [ ] Summary explicitly states "manifest is a map, not a fence"
- [ ] Summary mentions public distribution via `npx skills add attck/smith`

## Requirements Coverage (all 12 components)

- [ ] Component 1: `.smith/index/` directory structure documented (manifest.md, systems/, files/, config/)
- [ ] Component 2: `parse-python.py` documented with JSON shape, stdlib-only, <200ms budget, graceful malformed handling
- [ ] Component 3: `parse-js.js` documented with same JSON shape adapted for JS, <200ms budget, graceful malformed handling
- [ ] Component 4: `manifest-updater.sh` documented with all 10 workflow steps, <500ms budget, last-in-chain registration
- [ ] Component 5: `/smith-index` skill documented with `--check` and `--system <name>` flags + auto-invocation from `/smith init`
- [ ] Component 6: `/smith-navigate` skill documented with Haiku 4.5, 3s budget, standalone + sub-agent usage modes
- [ ] Component 7: `/smith-explore` Phase 1 refactor documented (navigate → grep candidates → grep whole codebase when warranted)
- [ ] Component 8: `context-loader.sh` documented with all 9 workflow steps including soft-warning fallback
- [ ] Component 9: `templates/context-manifest.default.json` documented with all 9 skill blocks (smith-new, smith-bugfix, smith-debug, smith-build, smith-audit, smith-vault, smith-help, smith-bank, _default)
- [ ] Component 10: `templates/system-paths.json.example` documented
- [ ] Component 11: 300-line enforcement documented across all 5 touchpoints (PostToolUse, smith-build, smith-audit, constitution template, CLAUDE template)
- [ ] Component 12: Memory/template updates documented (constitution.template.md + CLAUDE.template.md sections)

## Design Decisions Captured

- [ ] All 7 design decisions captured as `### Decision:` sub-sections
- [ ] Each decision has `**Decision:**`, `**Rationale:**`, `**Alternatives considered:**` blocks
- [ ] Decision 1 (skill naming) explicitly states `/smith-explore` is NOT renamed/repurposed and a NEW `/smith-navigate` is created
- [ ] Decision 2 (navigator output) explicitly chooses whole-file reads with primary-section annotations over tight ranges, with rationale about silent correctness failure
- [ ] Decision 2 includes the example output format with `[primary: 230-380, POST endpoint]` syntax
- [ ] Decision 3 (migration) documents all 3 behaviors: `/smith init` auto-invoke, manual on-demand, soft warning on missing manifest
- [ ] Decision 3 explicitly states NO auto-rebuild on first use, with the 30-60s wait rationale
- [ ] Decision 4 (4-tier config) lists all 4 tiers in correct precedence order (built-in → repo-shipped → user global → project)
- [ ] Decision 4 explicitly documents field-level merging with an override example
- [ ] Decision 5 (parser location) states global `~/.smith/scripts/` placement with per-project escape hatch at `.smith/scripts/`
- [ ] Decision 6 (distribution) explicitly states this is PUBLIC, not agency-package-only
- [ ] Decision 7 (hook order) explicitly states `manifest-updater.sh` registers LAST, after `file-change-logger.sh` and `lint-on-save.sh`, with rationale tied to lint reformatting

## Hard Constraints

- [ ] Hard constraints section lists all 8 measurable thresholds: source-file purity, <500ms manifest-updater, <5s context-loader, <200ms parsers, ≤50 lines top manifest, ≤80 lines per-system manifest, structured logs, gitignored
- [ ] Performance thresholds use explicit "p95" qualifiers where appropriate

## Acceptance Criteria Quality

- [ ] Acceptance criteria split into 3 categories: Functional, Performance, Quality
- [ ] Functional criteria include at least 14 distinct testable items
- [ ] Performance criteria include p95 budgets for `manifest-updater.sh`, `context-loader.sh`, parsers, `/smith-navigate`, `/smith-index`
- [ ] Quality criteria include logging structure, parser malformed-input handling, manifest line limits, hook order, 4-tier observability

## Open Questions

- [ ] At least 6 open questions surfaced (target: 8)
- [ ] All 8 open questions from the brief are present: smith-repo own manifest, migration helper, sub-agent fan-out kill switch, JS parser strategy, install hook registration, gitignore default, staleness detection, system auto-detection
- [ ] Each question is phrased as a decision pending, not as a vague concern
- [ ] No `[NEEDS CLARIFICATION]` markers appear anywhere in the spec body — all ambiguity is in this section

## Assumptions

- [ ] At least 4 assumptions stated explicitly
- [ ] Includes: smith-repo has no `.specify/systems/`, existing hooks are well-behaved, macOS/Linux only, Haiku 4.5 is the navigator model

## References

- [ ] Source requirements document referenced by absolute path: `~/Downloads/manifest-system (1).md`
- [ ] Source spec section numbers cited where the spec implements them verbatim (sections 1-8)
- [ ] References section notes whether a prior smith-debug session log was produced or not

## Cross-Cutting Quality

- [ ] No `[NEEDS CLARIFICATION]` markers anywhere in the spec body
- [ ] Decisions are stated as decisions, not as options
- [ ] WHAT and WHY are emphasized; HOW is deferred to plan.md (no implementation code in spec)
- [ ] Spec is comprehensive — 400-700 line target range hit
- [ ] No invented requirements outside the brief and source document
- [ ] All file paths are absolute or unambiguously rooted (no relative paths that depend on cwd)
