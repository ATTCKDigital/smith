---
name: smith-reflect
description: Analyzes a completed Smith workflow (build, bugfix, audit) and extracts lessons about what worked and what didn't. Updates the Ledger with new patterns and antipatterns. Use after a workflow completes or fails, or manually to review recent work.
---

# Smith Reflect -- Ledger Learning Extraction

Analyzes completed Smith workflows and extracts lessons into the project's Ledger.

**Arguments:** $ARGUMENTS

## Vault Logging

Throughout this action, log significant events to the vault session log. Read the session log path from `.smith/vault/.current-session`. If the file is missing or the vault is not initialized, skip all logging silently.

Append entries using this format:

```
### [HH:MM:SS] /smith-reflect <event>

**User Request:**
> <verbatim user message that triggered this action>

**Synthesized Input:** <brief summary>
**Outcome:** <what happened>
**Artifacts:** <files created/modified>
**Systems affected:** <system IDs>
```

Log at these points:
1. **On invocation** -- which sessions are being analyzed, mode (recent/specific/failure)
2. **After session analysis** -- how many candidate lessons extracted per session
3. **After deduplication** -- how many new vs reinforced entries
4. **After pruning** -- how many entries pruned or demoted
5. **On completion** -- full reflection summary

## Phase 0: Guard -- Ensure Ledger Exists

If `.smith/vault/ledger/` is missing, create the full directory scaffold before proceeding.

Create these files with initial content:

**patterns.md:**
```markdown
# Ledger: Patterns

Approaches that worked well, extracted from completed workflows.

<!-- Entries are sorted: high confidence first, then medium, then low. Within same confidence, most recent first. -->
```

**antipatterns.md:**
```markdown
# Ledger: Antipatterns

Approaches that failed or caused problems, extracted from completed workflows.

<!-- Entries are sorted: high confidence first, then medium, then low. Within same confidence, most recent first. -->
```

**tool-preferences.md:**
```markdown
# Ledger: Tool Preferences

Which tools were effective in which context, extracted from completed workflows.

<!-- Entries are sorted: high confidence first, then medium, then low. Within same confidence, most recent first. -->
```

**edge-cases.md:**
```markdown
# Ledger: Edge Cases

Rare or unexpected scenarios encountered during workflows.

<!-- Entries are sorted: high confidence first, then medium, then low. Within same confidence, most recent first. -->
```

**project-quirks.md:**
```markdown
# Ledger: Project Quirks

Project-specific surprises and behaviors that affect workflow execution.

<!-- Entries are sorted: high confidence first, then medium, then low. Within same confidence, most recent first. -->
```

**meta.yaml:**
```yaml
last_updated: <today's date YYYY-MM-DD>
total_reflections: 0
entries:
  patterns: 0
  antipatterns: 0
  tool_preferences: 0
  edge_cases: 0
  project_quirks: 0
confidence_distribution:
  high: 0
  medium: 0
  low: 0
```

This lazy-creation guard ensures reflection works even if `/smith` init was never run.

## Phase 1: Configuration Check

1. Read `.smith/config.json` -- look for the `ledger` namespace
2. If config is missing or `ledger.enabled` is not explicitly `false`, proceed (defaults to enabled)
3. For automatic invocation (called by another smith command, not the user directly): also check `ledger.auto_reflect` -- if `false`, skip silently and log "Auto-reflect disabled, skipping"
4. Read `ledger.reflection_model` to determine which model to use for semantic comparison (default: haiku)

Config schema (all fields optional):
```json
{
  "ledger": {
    "enabled": true,
    "auto_reflect": true,
    "reflection_model": "haiku",
    "pruning": {
      "low_max_age_days": 30,
      "medium_max_age_days": 90
    }
  }
}
```

## Phase 2: Session Selection

Determine which sessions to analyze based on arguments:

- `/smith-reflect` (no args) -- analyze the most recent completed workflow session
- `/smith-reflect --last N` -- analyze the last N sessions
- `/smith-reflect --session <id>` -- analyze a specific session by filename (e.g., `2026-04-08_151158`)
- `/smith-reflect --failure` -- analyze only sessions that contain failed workflows

**Finding sessions:** List `.smith/vault/sessions/` sorted by date descending. Each session file is named with a timestamp prefix (e.g., `2026-04-08_151158.md`).

**Detecting completed workflows:** Grep session logs for invocation markers:
- `/smith-build` -- full build workflows
- `/smith-bugfix` -- bugfix workflows
- `/smith-audit` -- audit workflows
- `/smith-implement` -- implementation workflows

Only analyze sessions that contain at least one of these workflow markers. Sessions that are purely Q&A, planning, or specification work are skipped (no execution to learn from).

**Detecting failures:** Grep for `ERROR`, `FAILED`, `failed`, `error`, `exception`, `traceback` in session logs, OR look for workflows that have an invocation marker but no corresponding completion marker (e.g., `/smith-build` started but no "Build complete" or "PR merged" entry).

If no qualifying sessions are found, output "No completed workflow sessions found to analyze." and exit.

## Phase 3: Session Analysis

For each selected session:

1. Read the full session log from `.smith/vault/sessions/<session-file>`
2. Extract the execution trace by scanning for these signals:

   **Success indicators:**
   - Tasks completed without retries
   - Tests passing on first run
   - Docker rebuilds succeeding
   - PR created and merged cleanly
   - Specs updated without conflicts

   **Failure/retry indicators:**
   - Commands that were run multiple times
   - Error messages followed by different approaches
   - Test failures followed by code changes
   - Docker build failures
   - Merge conflicts
   - Spec drift (plan said X, implementation did Y)
   - Rollbacks or reverts

   **Tool usage patterns:**
   - Which tools (Read, Write, Edit, Grep, Glob, Bash) were used most
   - Which tools produced errors or unexpected results
   - Effective tool chains (e.g., Grep then Read for targeted investigation)

3. Identify 0-5 candidate lessons per session. Not every session produces a lesson -- if everything went smoothly with no surprises, that is fine. Do not manufacture lessons.

   A good candidate lesson meets at least one criterion:
   - Something failed and the resolution was non-obvious
   - An approach worked significantly better than expected
   - A tool was used in an effective way that should be repeated
   - A project-specific constraint was discovered
   - A workaround was needed for an edge case

### Lesson Categories

Map each candidate lesson to the appropriate Ledger file:

| File | What goes here | Example |
|------|---------------|---------|
| **patterns.md** | Approaches that worked well | "Running `pnpm build` before Docker rebuild catches TS errors earlier" |
| **antipatterns.md** | Approaches that failed or caused problems | "Editing migration files without checking existing data caused constraint violations" |
| **tool-preferences.md** | Effective tool usage in context | "Use Grep with `output_mode: content` and `-C 3` for understanding error context, not just finding files" |
| **edge-cases.md** | Rare/unexpected scenarios | "Qdrant returns 400 if payload filter references a field that was never indexed" |
| **project-quirks.md** | Project-specific surprises | "Neo4j Cypher queries fail silently on missing properties -- always use COALESCE" |

Each lesson also gets a **category** tag:
- `implementation` -- code writing, architecture decisions
- `testing` -- test strategy, test failures, coverage gaps
- `debugging` -- error investigation, root cause analysis
- `specification` -- spec accuracy, plan-to-implementation drift
- `audit` -- review findings, compliance checks

## Phase 4: Deduplication (LLM Semantic Comparison)

For each candidate lesson:

1. Read the target Ledger file (e.g., `patterns.md`)
2. Parse all existing entries (split on `---` separator between entries)
3. Compare the candidate against ALL existing entries using semantic judgment:
   - Do NOT rely on exact string matching
   - Ask: "Does any existing entry cover the same core lesson, even if worded differently or applied to a different specific case?"
   - Consider: same root cause, same resolution strategy, same tool insight, same project constraint
4. Decision:

   **If duplicate found** -- Reinforce the existing entry:
   - Increment `Source reflections` count by 1
   - Add a new evidence line with today's date and session reference
   - Upgrade confidence if threshold crossed:
     - 1 reflection = `low`
     - 2-5 reflections = `medium`
     - 6+ reflections = `high`
   - Do NOT change the Title, Context, or Pattern text unless the new evidence reveals a meaningfully broader scope

   **If no duplicate** -- Mark as new entry (will be written in Phase 5)

## Phase 5: Write Entries

For each lesson (new or reinforced), write to the appropriate Ledger file.

### New Entry Format

Append to the appropriate file, separated from previous entries by `---`:

```markdown
---

**Title:** <concise descriptive name -- 5-10 words>
**Date:** <YYYY-MM-DD>
**Category:** <implementation | testing | debugging | specification | audit>
**Confidence:** low
**Source reflections:** 1

**Context:** <1-2 sentences describing when this pattern/antipattern applies -- what kind of task, what conditions, what service/layer>

**Pattern:** <2-4 sentences describing the actual approach that worked (for patterns) or the thing that failed and why (for antipatterns). Be specific enough to act on. Include the "instead, do X" for antipatterns.>

**Evidence:**
- <YYYY-MM-DD> -- session <session-filename>: <brief outcome description, 1 line>

**Related:** <links to related entries in other Ledger files (e.g., "See antipatterns.md: 'Title'"), or "None">
```

### Reinforcement

Update existing entry in-place:
- Increment `Source reflections` count
- Add new evidence line at the end of the Evidence list
- Update `Confidence` if threshold crossed (2 = medium, 6 = high)
- Update `Date` to today (date of most recent reinforcement)
- Do NOT change Title, Context, or Pattern unless scope has meaningfully broadened

### Ordering

After all writes are complete, re-sort entries within each modified file:
1. High confidence first, then medium, then low
2. Within same confidence level, most recent `Date` first

## Phase 6: Pruning Pass

Run automatic pruning on ALL Ledger files (not just the ones modified in this reflection):

1. Read pruning thresholds from `.smith/config.json`:
   - `ledger.pruning.low_max_age_days` (default: 30)
   - `ledger.pruning.medium_max_age_days` (default: 90)
2. For each entry in each Ledger file:

   | Confidence | Age threshold | Action |
   |-----------|--------------|--------|
   | `low` | Older than `low_max_age_days` | **REMOVE** the entry entirely |
   | `medium` | Older than `medium_max_age_days` | **DEMOTE** to `low`, set Date to today (resets the clock) |
   | `high` | N/A | **NEVER** touch, regardless of age |

3. "Age" is calculated from the entry's `Date` field (which is updated on reinforcement), not the original creation date.
4. Track pruning actions for the summary:
   - Count of removed entries
   - Count of demoted entries
   - Log each removal/demotion: "Pruned low-confidence '{Title}' from {file} (age: {N} days)" or "Demoted '{Title}' in {file} from medium to low (age: {N} days)"

## Phase 7: Update Metadata

Update `.smith/vault/ledger/meta.yaml` with current counts:

```yaml
last_updated: <today's date YYYY-MM-DD>
total_reflections: <previous total + number of sessions analyzed in this run>
entries:
  patterns: <count entries in patterns.md>
  antipatterns: <count entries in antipatterns.md>
  tool_preferences: <count entries in tool-preferences.md>
  edge_cases: <count entries in edge-cases.md>
  project_quirks: <count entries in project-quirks.md>
confidence_distribution:
  high: <count across all files>
  medium: <count across all files>
  low: <count across all files>
```

Count entries by counting `**Title:**` lines in each file.

## Phase 7.5: Update Reconciliation Signals

After updating `meta.yaml`, also update `.smith/vault/ledger/.meta.json` to track reconciliation trigger signals:

1. If `.smith/vault/ledger/.meta.json` does not exist, create it with defaults:
   ```json
   {
     "schema_version": 1,
     "last_reconcile": null,
     "estimated_tokens": 0,
     "total_patterns": 0,
     "total_reinforcements": 0,
     "context_budget_violations": 0,
     "reinforcements_since_reconcile": 0,
     "lock": null
   }
   ```
2. Update the following fields:
   - `estimated_tokens`: compute word count × 1.3 across all Ledger .md files (patterns.md, antipatterns.md, tool-preferences.md, edge-cases.md, project-quirks.md)
   - `total_patterns`: count of `**Title:**` lines across all Ledger .md files
   - `total_reinforcements`: increment by the number of reinforcements performed in this reflection run
   - `reinforcements_since_reconcile`: increment by the number of reinforcements performed in this reflection run
3. Do NOT touch `lock`, `last_reconcile`, or `context_budget_violations` — those are owned by other skills

## Phase 8: Summary

Output a reflection summary to the user:

```
Reflection complete.
- Sessions analyzed: N
- New patterns: N (files: patterns.md, tool-preferences.md, ...)
- Reinforced: N existing entries
- Pruned: N stale entries
- Demoted: N entries (medium -> low)
- Ledger health: X total entries (H high, M medium, L low)
```

Log the full summary to the vault session log.

If zero lessons were extracted across all analyzed sessions, output:
```
Reflection complete.
- Sessions analyzed: N
- No new lessons extracted -- workflows executed cleanly.
- Pruned: N stale entries
- Ledger health: X total entries (H high, M medium, L low)
```

## Automatic Invocation

Other smith commands (`/smith-build`, `/smith-bugfix`, `/smith-audit`) may call `/smith-reflect` automatically at the end of their execution. When invoked automatically:

1. Check `ledger.auto_reflect` in config -- if `false`, skip silently
2. Analyze only the current session (the one that just completed)
3. Use the configured `reflection_model` (default: haiku) to keep cost and latency low
4. Do NOT prompt the user -- this runs silently in the background
5. Append reflection results to the existing session log, not a new one

## Edge Cases

- **Empty session log**: Skip with message "Session log is empty, nothing to analyze"
- **Session with no workflow markers**: Skip with message "No completed workflows found in session"
- **Ledger file is malformed**: Log a warning, attempt to parse what is readable, append new entries at the end
- **Config file missing**: Use all defaults, proceed normally
- **Multiple workflows in one session**: Extract lessons from each workflow independently, but write to the same Ledger files
- **Very long session logs** (>500 lines): Focus analysis on error sections, retry sequences, and completion markers rather than reading every line
