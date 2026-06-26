## File Size Policy

Source files should stay under 300 lines as a soft target. Files between
300 and 500 lines warrant a decomposition review; files over 500 lines
SHOULD be decomposed unless they are:

- Auto-generated (schemas, migrations, vendored libraries)
- Single-purpose data files (lookup tables, fixtures)
- Test files where decomposition harms readability

`/smith-audit` and `/smith-build` surface 300/500-line files as advisories
in audit reports and PR descriptions respectively. None of these checks
block — they inform.

## Context Budget Policy (`@`-Referenced Files)

Files `@`-referenced from `CLAUDE.md` (or any always-loaded memory file) are read
**in full into every session's context**. They MUST stay small and structurally
stable — overview, tech stack, ERD, entity tables, enums, durable notes only.

- Do NOT `@`-reference a doc that any workflow or rule then appends per-change
  prose to (a growing "Last Updated" / "Recent Changes" changelog header is the
  classic offender — it silently grows to hundreds of KB and causes merge
  conflicts on every branch).
- The durable per-change record lives in `.smith/vault/sessions/` + the Ledger +
  git history — **those ARE the changelog.** Do not hand-roll a
  `feedback_changelog.md`-style rule that re-introduces per-change appends into a
  context-loaded file.
- As a soft target, keep any single `@`-referenced file under ~50 KB. `/dream`
  (or the project's config-health auditor) REPORTS oversized `@`-referenced files
  in its health summary — it never edits them.

## Project Manifest

The project manifest under `.smith/index/` is auto-maintained by the
`manifest-updater.sh` Claude Code hook and refreshed in bulk by the
`/smith-index` skill.

Source files NEVER contain Smith metadata — all generated state lives in
`.smith/index/` only. Run `/smith-index` after major refactors to refresh
the full manifest. The `.smith/index/files/` and `.smith/index/systems/`
subdirectories are gitignored by default; `manifest.md` and `config/` are
committed for team sharing.
