---
name: smith-migrate-specs
description: One-time migration of existing flat spec folders into the system-based hierarchy under .specify/systems/.
argument-hint: "[--dry-run] [--all]"
---

# Smith Spec Migration

Migrate existing feature spec folders from `specs/<NNN-feature>/` into the system-based hierarchy at `.specify/systems/<system>/features/<NNN-feature>/`.

**Arguments:** $ARGUMENTS

## Prerequisites

- `.specify/systems/` must exist with system spec folders (created by Phase 1B setup or `/smith`)
- System spec files must be present at `.specify/systems/system-*/spec.md` for system detection to work

## Behavior

### Step 1: Scan for Migratable Features

Scan `specs/` for all feature spec folders. **Exclude** the following (they are not feature specs):
- `specs/system-*` (system specs — these are the source of truth)
- `specs/questions/` (global questions directory)
- `specs/screenshots/` (visual reference)
- `specs/sentiment-engine/` (legacy non-numbered spec)
- `specs/init-intake.md` (not a folder)

A valid feature folder must:
- Be a directory
- Contain at least a `spec.md` file
- Match the pattern `NNN-*` (numbered feature)

List all candidates with their folder name and a one-line summary from the first heading in their spec.md.

### Step 2: System Detection (per feature)

For each feature folder, determine the primary system:

1. **Read the feature's `spec.md`** — extract what the feature does, which services it touches, what data it modifies
2. **Read all `.specify/systems/system-*/spec.md`** — understand each system's scope
3. **Determine primary_system** — the system most directly impacted by the feature
4. **Determine also_affects** — other systems the feature touches

Use these heuristics for mapping:
- Features touching `services/command-center/` → `system-15-command-center`
- Features touching `services/email-pipeline/` → `system-03-email-archive-contact-graph`
- Features touching `services/sentiment-engine/` → `system-05-communication-triage` or system-03 depending on scope
- Features touching `services/content-strategy/` or `services/content-engine/` → `system-12-content-social-engine`
- Features touching `services/social-listening/` → `system-10-social-listening`
- Features touching `services/trend-intelligence/` → `system-13-trend-intelligence`
- Features touching `services/voice-training/` → `system-04-personal-voice`
- Features touching `services/meeting-intelligence/` → `system-09-meeting-intelligence`
- Features touching `docker-compose.yml` or infrastructure → `system-01-infrastructure`
- Features touching Neo4j/contacts/graph → `system-03-email-archive-contact-graph`
- Features touching N8N workflows → `system-01-infrastructure`
- Features that are genuinely cross-cutting → `cross-system`

Also check git history and the feature's `plan.md` (if it exists) for additional context.

### Step 3: Present & Confirm (One at a Time)

For each feature, present the proposed mapping:

```
Feature: 024-triage-review-actions
Summary: Add review actions (approve/reject/archive) to the triage log
Primary: system-05-communication-triage
Also affects: system-15-command-center
Files to move: spec.md, plan.md, tasks.md, checklists/, questions.md (5 items)

Move to: .specify/systems/system-05-communication-triage/features/024-triage-review-actions/

Confirm? [y/n/skip/quit]
```

- **y** — Move this feature
- **n** — Let the user specify a different system
- **skip** — Skip this feature, move to the next
- **quit** — Stop migration entirely

**IMPORTANT:** Process ONE feature at a time. Do NOT batch-move all features without individual confirmation.

### Step 4: Execute Migration

For each confirmed feature:

1. **Create the target directory**: `mkdir -p .specify/systems/<primary-system>/features/<feature-name>/`
2. **Copy all files** from `specs/<feature-name>/` to the new location (copy, not move — we preserve originals until verified)
3. **Add frontmatter** to the migrated `spec.md` if not already present:
   ```yaml
   ---
   feature: <feature-name>
   primary_system: <system-folder-name>
   also_affects:
     - <other-system>
   branch: <branch-name if detectable from git>
   created: <date from spec or git>
   status: complete
   ---
   ```
4. **Log the migration** to `.smith/vault/sessions/` (current session log if active)

### Step 5: Summary

After processing all features (or quitting), display:

```
## Migration Summary

Migrated: 15 features
Skipped: 3 features
Remaining: 37 features (not yet processed)

### Migrated Features
| Feature | System | Path |
|---------|--------|------|
| 024-triage-review-actions | system-05-communication-triage | .specify/systems/system-05-communication-triage/features/024-triage-review-actions/ |
| ... | ... | ... |

### Skipped Features
| Feature | Reason |
|---------|--------|
| 025-nav-label-rename | User skipped |

Note: Original folders in specs/ are preserved. Once verified, you can remove them manually.
```

## Flags

- `--dry-run` — Show proposed mappings for all features without moving anything
- `--all` — Skip individual confirmations and move all features using auto-detected systems (use with caution)

## Important Notes

- This action **copies** files rather than moving them. The originals in `specs/` remain untouched as a safety measure.
- After verifying the migration is correct, the user can manually remove the originals from `specs/`.
- Features that already exist in `.specify/systems/` are skipped automatically.
- The vault infrastructure (Phase 1A) must be in place for session logging to work.
- Do NOT modify the constitution.md or any vault hooks during migration.
