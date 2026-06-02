---
name: smith-migrate-system-paths
description: One-time migration to add `paths:` YAML frontmatter to existing `.specify/systems/<id>/spec.md` files. Scans prose for path-like references (services/<X>/, backend/<X>/, frontend/<X>/, etc.), proposes a per-system list, and writes accepted frontmatter ABOVE the existing body. Use when a project grew system specs as prose and you want the Smith manifest v2 path-resolver tier 1 to bucket files correctly.
argument-hint: "[--dry-run] [--auto-confirm] [--top-n N]"
---

# Smith System Path Migration

Add `paths:` YAML frontmatter to existing system specs without disturbing their hand-authored prose. After migration, the Smith manifest v2 path-resolver tier 1 reads these `paths:` entries and routes source files into the correct system bucket.

**Arguments:** $ARGUMENTS

## When to use

- A project has `.specify/systems/system-*/spec.md` files written as prose (no YAML frontmatter, or frontmatter without `paths:`).
- The Smith manifest v2 resolver is now in use and you want tier 1 (declared paths) to take precedence over tier 2 (`system-paths.json`) and tier 3 (heuristic).
- You ran `/smith-index` and the per-system manifests are bucketing files into the wrong systems (because the resolver fell through to tier 3 heuristic).

## When NOT to use

- The project has no `.specify/systems/` directory at all — there's nothing to migrate. Use `/smith` Phase 4.8 (Optionally Scaffold System Specs) instead, or hand-author the first specs.
- The system specs already have `paths:` in their frontmatter — this skill skips them automatically (idempotent re-runs are a no-op), but there's no value in re-running.
- You want to migrate _features_ (numbered spec folders) into the system hierarchy — that's `/smith-migrate-specs`, a different skill.

## Behavior overview

This skill operates on `.specify/systems/system-*/spec.md` files in the current project. For each file:

1. **Skip** if it already has a non-empty `paths:` list in its YAML frontmatter (idempotency check).
2. **Scan the prose body** with a heuristic regex matcher (see `scripts/propose_paths.py`) to identify candidate path prefixes (`services/<X>/`, `backend/<X>/`, `frontend/<X>/`, `apps/<X>/`, `packages/<X>/`, backticked dirs, backticked files, bulleted paths, code-fenced file paths).
3. **Score and rank** each candidate by `frequency × position_weight` (earlier mentions in the file get higher weight — prose near the top is usually scope-defining).
4. **Present the top-N proposals** to the operator with each prefix's score, raw match count, and up to two line-quoted excerpts. The operator chooses Accept / Skip per system.
5. **On accept**, inject YAML frontmatter into the file:
    - If the file has NO frontmatter at all: prepend a fresh block (system, status, paths, also_affects) above the body, body preserved verbatim.
    - If the file has frontmatter WITHOUT `paths:`: insert only the `paths:` field inside the existing block, body preserved verbatim.
6. **On skip**, leave the file unchanged.

After processing every system, print a summary line: `migrated: N | skipped (already): M | skipped (no proposal): P | skipped (by user): Q`.

## Flags

| Flag | Default | Meaning |
|---|---|---|
| `--dry-run` | off | Show proposals, do NOT write any files. |
| `--auto-confirm` | off | Accept all proposals without prompting. **Intended for tests** — production runs should always prompt the operator per-system. |
| `--top-n N` | 5 | Maximum number of proposed prefixes per system. |
| `--non-interactive` | off | Suppress prompts entirely. Combine with `--auto-confirm` to run unattended. |
| `--project-root <path>` | cwd | Where to find `.specify/systems/`. |

## Workflow (interactive default)

When the user invokes `/smith-migrate-system-paths`, Claude:

1. **Verify** `.specify/systems/` exists in the current project. If not, abort with a friendly message pointing the user to `/smith` Phase 4.8.

2. **Enumerate** `.specify/systems/system-*/spec.md` files (sorted by directory name).

3. **For each spec file**:

   a. Read the file. Determine whether it already has YAML frontmatter and whether that frontmatter contains a non-empty `paths:` field. If it does, print a one-line "already migrated" message and continue to the next file.

   b. Strip the frontmatter (if any) and run the prose body through `scripts/propose_paths.py` to get up to `--top-n` proposed prefixes.

   c. Present the proposals to the operator:

      ```
      System `system-05-communication-triage` — proposed paths:
        - backend/src/services/triage/    (score=4.20, matches=7)
            | This system handles triage of inbound communications. Implementation lives in `backend/src/services/triage/`...
            | - backend/src/services/triage/router.py
        - frontend/src/lib/triage/        (score=1.80, matches=3)
            | with frontend bindings in `frontend/src/lib/triage/`...

      Accept these paths for `system-05-communication-triage`? [Y/n]
      ```

   d. Wait for operator input. Accepted responses:

      - `y` / `yes` / Enter — accept all proposed prefixes for this system.
      - `n` / `no` — skip this system (no changes written).
      - `edit` — present a free-text editor inviting the operator to replace the proposed list with a hand-edited one (one prefix per line). Validate each edited entry: literal prefix (no `*?[]{}!`), auto-append `/` if missing.
      - `skip` — synonym for `n`.

   e. On accept (with or without edits):

      - If the file has NO frontmatter: prepend a fresh block. The status field defaults to `in-progress` unless a `**Status:**` line is found in the prose body (then use that value if it's in the schema's enum: `draft`, `in-progress`, `complete`, `active`, `deprecated`, `proposed`).
      - If the file has a frontmatter block without `paths:`: insert only the `paths:` field, positioned just below the existing `system:` line.
      - Write via atomic temp-file rename. Body bytes are preserved exactly.

4. **After all specs processed**, print the summary report:

   ```
   ============================================================
   Migration summary
   ============================================================
     migrated:                       7
     skipped (already has paths):    3
     skipped (no prose hints):       1
     skipped (by user):              0
   ```

## Implementation

Claude runs the orchestrator via the bundled helper script:

```bash
python3 skills/smith-migrate-system-paths/scripts/migrate.py [flags]
```

For interactive workflow, run WITHOUT `--auto-confirm` so the helper prompts per-system through stdin. Claude relays each prompt to the user and feeds their answer to the script (or, in environments where stdin-piping isn't clean, Claude can read each spec, call `propose_paths.propose()` directly via a one-shot Python invocation, present the proposals in chat, await user confirmation, and then call `migrate.migrate_one(spec, auto_confirm=True)` per file after each user accept).

For an unattended dry-run preview:

```bash
python3 skills/smith-migrate-system-paths/scripts/migrate.py --dry-run --non-interactive --auto-confirm
```

This prints the proposals every spec would receive without modifying any files.

## Idempotency guarantee

Re-running `/smith-migrate-system-paths` on a previously-migrated project is a no-op. The skill detects existing non-empty `paths:` fields and skips those files. A file that was skipped by the user (or had no prose hints) on a prior run is eligible for re-proposal on subsequent runs.

## Safety notes

- The skill **never** auto-writes in production mode. Every system spec requires explicit operator confirmation. The `--auto-confirm` flag exists solely for automated tests.
- Body bytes are preserved exactly — only the frontmatter block is touched. Diff before committing if you want to verify.
- Glob characters (`*`, `?`, `[`, `]`, `{`, `}`, `!`) are rejected at the propose step; they cannot leak into written `paths:` entries.
- Atomic writes via `os.replace(tempfile, spec_path)` — a partial-write window is impossible.

## Related

- `/smith` Phase 4.8 — scaffolds new system specs from the canonical template at project bootstrap.
- `/smith-migrate-specs` — migrates _feature_ spec folders into the system hierarchy. Unrelated to this skill.
- `/smith-index` — rebuilds the manifest. Run this AFTER migration so per-system manifests pick up the new tier-1 buckets.
