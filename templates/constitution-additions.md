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

## Project Manifest

The project manifest under `.smith/index/` is auto-maintained by the
`manifest-updater.sh` Claude Code hook and refreshed in bulk by the
`/smith-index` skill.

Source files NEVER contain Smith metadata — all generated state lives in
`.smith/index/` only. Run `/smith-index` after major refactors to refresh
the full manifest. The `.smith/index/files/` and `.smith/index/systems/`
subdirectories are gitignored by default; `manifest.md` and `config/` are
committed for team sharing.
