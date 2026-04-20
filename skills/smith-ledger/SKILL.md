---
name: smith-ledger
description: Browse, search, and manage the Smith Ledger — the accumulated patterns, antipatterns, tool preferences, and edge cases learned from past workflows. Use to review what Smith has learned, search for relevant patterns, prune outdated entries, or inspect the Ledger's evolution over time.
argument-hint: "[list|show|search|prune|promote|demote|export|reset] [<title-or-query>] [--category <cat>] [--confidence <level>] [--file <filename>] [--auto]"
---

# Smith Ledger — Knowledge Base Management

Browse, search, and manage the Smith Ledger. The Ledger is the persistent knowledge base that captures patterns, antipatterns, tool preferences, edge cases, and project quirks learned from past Smith workflows. It lives at `.smith/vault/ledger/`.

**Arguments:** $ARGUMENTS

## Vault Logging

Throughout this action, log significant events to the vault session log. Read the session log path from `.smith/vault/.current-session`. If the file is missing or the vault is not initialized, skip all logging silently.

Append entries using this format:

```
### [HH:MM:SS] /smith-ledger <event>

**User Request:**
> <verbatim user message that triggered this action>

**Subcommand:** <dashboard|list|show|search|prune|promote|demote|export|reset>
**Synthesized Input:** <brief summary of args/filters>
**Outcome:** <what happened — counts, changes made, results found>
**Artifacts:** <files read/modified>
**Systems affected:** <system IDs>
```

Log at these points:
1. **On invocation** — which subcommand was used and with what arguments
2. **After any mutation** — prune, promote, demote, or reset operations that modify Ledger files

## Ledger Directory Structure

The Ledger lives at `.smith/vault/ledger/` with the following files:

```
.smith/vault/ledger/
  meta.yaml             # Overview stats — last reflection date, total counts, config
  patterns.md           # Validated approaches that work well
  antipatterns.md       # Approaches that failed or caused problems
  tool-preferences.md   # Tool/library/API usage preferences and gotchas
  edge-cases.md         # Non-obvious behaviors, boundary conditions, quirks in tools/APIs
  project-quirks.md     # Project-specific conventions, workarounds, and constraints
  archive/              # Archived Ledger snapshots from resets
```

## Ledger Entry Format

Each Ledger file (patterns.md, antipatterns.md, etc.) contains entries in this format:

```markdown
## <Title>

- **Date:** YYYY-MM-DD
- **Category:** implementation | testing | debugging | specification | audit
- **Confidence:** low | medium | high
- **Observations:** N
- **Source reflections:** <comma-separated list of reflection session dates or spec IDs>

### Context

<When and why this pattern/antipattern/preference/edge-case applies>

### Pattern

<The actual pattern, antipattern, tool preference, edge case, or project quirk — what to do or what to avoid>

### Evidence

<Specific examples from past workflows that support this entry>

### Related

<Links to related entries, specs, or code files>

---
```

## meta.yaml Format

```yaml
last_reflection: "YYYY-MM-DD"
total_reflections: N
total_entries: N
config:
  low_confidence_prune_days: 30
  medium_confidence_demote_days: 90
entries_by_file:
  patterns: N
  antipatterns: N
  tool-preferences: N
  edge-cases: N
  project-quirks: N
```

## Subcommands

### `/smith-ledger` (no args) — Dashboard

Display a summary dashboard:

1. **Check if `.smith/vault/ledger/` exists.** If not, display the following and stop:
   ```
   No Ledger found.
   Run `/smith-reflect` after a workflow to start building the Ledger,
   or run `/smith` to initialize the vault structure.
   ```

2. **Read `meta.yaml`** for overview stats (last reflection date, total reflections, total entries, config).

3. **Read each Ledger file** and count entries by confidence level. An entry boundary is a line starting with `## ` (heading level 2). Extract the `**Confidence:**` value from each entry.

4. **Display the dashboard:**

```
SMITH LEDGER — Dashboard
========================

Last reflection: YYYY-MM-DD
Total reflections: N
Total entries: N

| File                | Entries | High | Medium | Low |
|---------------------|---------|------|--------|-----|
| patterns.md         |    N    |  N   |   N    |  N  |
| antipatterns.md     |    N    |  N   |   N    |  N  |
| tool-preferences.md |    N    |  N   |   N    |  N  |
| edge-cases.md       |    N    |  N   |   N    |  N  |
| project-quirks.md   |    N    |  N   |   N    |  N  |

Top High-Confidence Patterns:
1. [Title] — [Category] ([N] observations)
2. [Title] — [Category] ([N] observations)
3. [Title] — [Category] ([N] observations)
```

If there are no high-confidence entries, show "No high-confidence entries yet." instead of the Top Patterns section.

Show up to 5 high-confidence entries, sorted by observation count descending. Draw from all Ledger files, not just patterns.md.

---

### `/smith-ledger list` — List Entries

List all entries, optionally filtered by category, confidence, or file.

**Flags:**
- `--category <cat>` — Filter by category. Valid values: `implementation`, `testing`, `debugging`, `specification`, `audit`
- `--confidence <level>` — Filter by confidence. Valid values: `low`, `medium`, `high`
- `--file <filename>` — Show only entries from a specific file. Valid values: `patterns`, `antipatterns`, `tools` (alias for `tool-preferences`), `edge-cases`, `quirks` (alias for `project-quirks`)

Flags can be combined. When multiple flags are provided, apply all filters (AND logic).

**No flags:** List all entries across all files, grouped by file.

**Display format per entry:**
```
[confidence] Title — Category (N observations, last: YYYY-MM-DD)
```

Group entries under their file heading:
```
--- patterns.md ---
[high] Always rebuild Docker after code changes — implementation (4 observations, last: 2026-04-01)
[medium] Use processing_ledger for pipeline stages — implementation (2 observations, last: 2026-03-28)

--- antipatterns.md ---
[high] Don't mock the database in integration tests — testing (3 observations, last: 2026-04-05)
```

If no entries match the filters, display: "No entries match the given filters."

---

### `/smith-ledger show <title>` — Show Full Entry

Search across all Ledger files for an entry whose `## <Title>` heading matches the given title. Matching is **case-insensitive** and supports **partial matches** (the query is a substring of the title).

**Single match:** Display the full entry including all fields (title, date, category, confidence, observations, source reflections, context, pattern, evidence, related). Also display the source file name.

**Multiple matches:** List them with index numbers and ask which one to display:
```
Multiple entries match "docker":

1. [high] Always rebuild Docker after code changes — patterns.md
2. [medium] Docker Compose ordering matters for healthchecks — edge-cases.md
3. [low] Docker layer caching invalidation — tool-preferences.md

Which entry would you like to see? (1-3)
```

**No matches:** Display: `No entries found matching "<title>".`

---

### `/smith-ledger search <query>` — Search

Search across all Ledger files for the query string using case-insensitive matching.

For each match:
1. Identify which entry the match belongs to (find the nearest preceding `## ` heading)
2. Display the entry title, file, and confidence
3. Show the matching line with surrounding context (2 lines before and after)

**Display format:**
```
--- patterns.md: "Always rebuild Docker after code changes" [high] ---
  ...
  Docker containers cache the build artifacts. When you change source code,
> the running container still has the old code unless you rebuild.
  Always run `docker compose up -d --build <service>` after changes.
  ...

--- edge-cases.md: "Qdrant WAL recovery on unclean shutdown" [medium] ---
  ...
  If Colima is stopped without first running `docker compose down`,
> Qdrant will perform WAL recovery on next start, which can take hours
  with large collections (935K+ entries).
  ...
```

If no matches found, display: `No results for "<query>".`

---

### `/smith-ledger prune` — Interactive Pruning

Scan all Ledger files for prune candidates based on age and confidence:

1. **Identify candidates:**
   - **Remove candidates:** Low-confidence entries where the `**Date:**` is older than `config.low_confidence_prune_days` days (default: 30)
   - **Demote candidates:** Medium-confidence entries where the `**Date:**` is older than `config.medium_confidence_demote_days` days (default: 90). These will be demoted to low confidence, not removed.

2. **Read config values** from `meta.yaml` under `config:`. If `meta.yaml` is missing or config values are absent, use defaults (30 days for low, 90 days for medium).

3. **Display candidates grouped by action:**

```
SMITH LEDGER — Prune Candidates
================================

Entries to REMOVE (low confidence, older than 30 days):
  1. "Ruff format before commit" — tool-preferences.md (dated 2026-02-15)
  2. "Check Neo4j constraints on startup" — patterns.md (dated 2026-02-20)

Entries to DEMOTE to low (medium confidence, older than 90 days):
  3. "Qdrant batch size limit" — edge-cases.md (dated 2026-01-10)

Total: 2 removals, 1 demotion
```

4. **Prompt for confirmation:** `Remove 2 entries and demote 1 entry? (yes/no)`

5. **If confirmed:**
   - Remove the identified entries from their respective files (delete the entire entry block from `## ` to the next `---` separator or end of file)
   - Demote identified entries by changing their `**Confidence:**` value from `medium` to `low`
   - Update `meta.yaml` counts accordingly
   - Report: `Pruned: 2 removed, 1 demoted. Total entries: N`

6. **If declined:** Display: `Prune cancelled. No changes made.`

If no candidates are found, display: `No prune candidates found. Ledger is clean.`

---

### `/smith-ledger prune --auto` — Automatic Pruning

Same logic as interactive prune but **without confirmation**. Execute immediately and report results.

Display:
```
Auto-prune complete: N removed, M demoted. Total entries: N
```

---

### `/smith-ledger promote <title>` — Promote Confidence

1. **Find the entry** by title using the same case-insensitive partial match logic as `show`.
2. **If multiple matches,** list them and ask which one to promote.
3. **Raise confidence one level:**
   - `low` -> `medium`
   - `medium` -> `high`
   - `high` -> Display: `"<Title>" is already at high confidence. No change.`
4. **Update the entry in place** in its Ledger file — change the `**Confidence:**` line.
5. **Report:** `Promoted "<Title>" from <old> to <new> confidence.`

---

### `/smith-ledger demote <title>` — Demote Confidence

1. **Find the entry** by title using the same case-insensitive partial match logic as `show`.
2. **If multiple matches,** list them and ask which one to demote.
3. **Lower confidence one level:**
   - `high` -> `medium`
   - `medium` -> `low`
   - `low` -> Display: `"<Title>" is already at low confidence. No change.`
4. **Update the entry in place** in its Ledger file — change the `**Confidence:**` line.
5. **Report:** `Demoted "<Title>" from <old> to <new> confidence.`

---

### `/smith-ledger export` — Export Full Ledger

Concatenate all Ledger files into a single markdown document and output it to chat.

**Format:**
1. Start with the contents of `meta.yaml` wrapped in a YAML code block
2. For each Ledger file (in order: patterns, antipatterns, tool-preferences, edge-cases, project-quirks):
   - Add a level-1 heading: `# <filename>`
   - Include the full file contents

Output the entire document to chat. Do not write it to a file unless the user explicitly asks.

---

### `/smith-ledger reset` — Reset Ledger

1. **Prompt for confirmation:**
   ```
   This will archive the current Ledger and start fresh.
   All existing entries will be preserved in the archive.
   Are you sure? (yes/no)
   ```

2. **If confirmed:**
   - Create archive directory: `.smith/vault/ledger/archive/YYYY-MM-DD-HHMMSS/`
   - Move all current Ledger files (`meta.yaml`, `patterns.md`, `antipatterns.md`, `tool-preferences.md`, `edge-cases.md`, `project-quirks.md`) to the archive directory
   - Create fresh empty templates for each file:

   **meta.yaml:**
   ```yaml
   last_reflection: null
   total_reflections: 0
   total_entries: 0
   config:
     low_confidence_prune_days: 30
     medium_confidence_demote_days: 90
   entries_by_file:
     patterns: 0
     antipatterns: 0
     tool-preferences: 0
     edge-cases: 0
     project-quirks: 0
   ```

   **Each .md file (patterns.md, antipatterns.md, tool-preferences.md, edge-cases.md, project-quirks.md):**
   ```markdown
   # <File Title>

   <!-- Entries are added by /smith-reflect. Each entry starts with ## heading. -->
   ```

   File titles: "Patterns", "Antipatterns", "Tool Preferences", "Edge Cases", "Project Quirks"

   - Report:
   ```
   Ledger archived to .smith/vault/ledger/archive/YYYY-MM-DD-HHMMSS/
   Fresh Ledger initialized with empty templates.
   ```

3. **If declined:** Display: `Reset cancelled. Ledger unchanged.`

---

### `/smith-ledger reconcile` — Ledger Self-Maintenance

Merges duplicate entries, prunes stale patterns, enforces token budgets, and creates timestamped backups. Runs automatically via inline trigger after workflow reflection, or manually on demand.

**Subcommands:**
- `/smith-ledger reconcile` — Full reconciliation (checks thresholds first)
- `/smith-ledger reconcile --dry-run` — Preview what would change without modifying files
- `/smith-ledger reconcile --force` — Bypass lock and threshold checks for emergency maintenance
- `/smith-ledger reconcile --status` — Show current .meta.json signals and whether reconciliation is needed
- `/smith-ledger reconcile --category <name>` — Reconcile only one Ledger file (patterns, antipatterns, tools, edge-cases, quirks)

#### 7 Non-Negotiable Safeguards

1. **Timestamped backup** before any modifications — copies all Ledger .md files and meta.yaml to `.backups/reconcile-YYYY-MM-DD-HHMMSS/`
2. **Lock file** with 10-minute expiry — prevents concurrent reconciliation; stored as `lock` field in `.meta.json`
3. **Haiku-only merge decisions** — merge candidates evaluated by configured `reconcile_model` (default: Haiku); merges require LLM to confirm "these entries cover the same core lesson"
4. **Backup-before-write** — every modified Ledger file is backed up before being overwritten
5. **Failure logging without auto-retry** — all failures logged to `reconcile-log.md`; never auto-retried
6. **Manual override** — `--force` flag bypasses lock and threshold checks
7. **Conservative merge threshold** — only merges when LLM gives high confidence of semantic equivalence; ambiguous cases left as-is

#### Phase 0: Guard and Lock

1. Read `.smith/config.json` — check `ledger.reconcile.enabled`; if `false`, exit silently
2. If not `--force`: check `.meta.json` lock field
   - If lock exists and `acquired` is < 10 minutes ago, exit with "Reconciliation already in progress"
   - If lock exists and `acquired` is >= 10 minutes ago, treat as stale lock, proceed
3. Acquire lock: write `{"pid": "<session-id>", "acquired": "<ISO-8601>"}` to `.meta.json` `lock` field
4. If `.smith/vault/ledger/` does not exist, create it (same scaffold as smith-reflect Phase 0)

#### Phase 1: Threshold Check

Unless `--force` or manual invocation:

1. Read `.meta.json` current values
2. Read `.smith/config.json` thresholds (or use defaults: 30K total tokens, 8K single-file, 50/category, 50 reinforcements, 3 violations)
3. Check each threshold:
   - `estimated_tokens > thresholds.total_tokens_max` (default 30000)
   - Any single file estimated tokens > `thresholds.single_file_tokens_max` (default 8000)
   - Any category pattern count > `thresholds.patterns_per_category_max` (default 50)
   - `reinforcements_since_reconcile > thresholds.reinforcements_threshold` (default 50)
   - `context_budget_violations > thresholds.context_violations_threshold` (default 3)
4. Check minimum interval: if `last_reconcile` is less than `minimum_hours_between_reconciles` (default 6) hours ago, skip
5. If NO threshold exceeded, release lock and exit with "No reconciliation needed"
6. Record which threshold(s) triggered for the reconcile-log entry

**Fallback**: If `.meta.json` is missing or stale, compute signals directly from Ledger files:
- Count `**Title:**` lines for pattern count
- Estimate tokens via word count × 1.3 on each .md file
- Set violations and reinforcements to 0

#### Phase 2: Backup

1. Create directory `.smith/vault/ledger/.backups/reconcile-YYYY-MM-DD-HHMMSS/`
2. Copy all files: `patterns.md`, `antipatterns.md`, `tool-preferences.md`, `edge-cases.md`, `project-quirks.md`, `meta.yaml`, `.meta.json`
3. Verify backup file count matches source
4. If backup verification fails, release lock and abort entirely
5. Prune old backups:
   - List all `reconcile-*` directories in `.backups/`
   - Sort by timestamp descending
   - Remove directories beyond `backup.max_count` (default 5) OR older than `backup.max_age_days` (default 30 days)

#### Phase 3: Merge Duplicates

For each Ledger .md file:

1. Parse entries (split on `---` separator, extract `**Title:**`, `**Context:**`, `**Pattern:**` fields)
2. Generate candidate pairs: compare each entry against every other entry in the same file
3. For each candidate pair, ask the configured `reconcile_model` (default: Haiku):
   - "Do these two Ledger entries cover the same core lesson? Entry A: [title + context + pattern]. Entry B: [title + context + pattern]. Answer YES with a merged title, or NO."
   - If YES: merge the entries
     - Keep the higher-confidence entry as the base
     - Combine evidence lists (deduplicate by date)
     - Sum source reflection counts
     - Use the merged title from the LLM
     - Recalculate confidence (1=low, 2-5=medium, 6+=high)
     - Add merge note: `- YYYY-MM-DD — reconcile merge: absorbed "<other title>"`
   - If NO: leave both as-is
4. Write merged results back, maintaining sort order (high first, then medium, then low; most recent first within same confidence)

**Complexity bound**: If N > 100 entries in a file, skip merge phase and log warning.

#### Phase 4: Prune Stale Entries

Same rules as smith-reflect Phase 6:

1. Read pruning thresholds from config: `ledger.pruning.low_max_age_days` (default 30), `ledger.pruning.medium_max_age_days` (default 90)
2. For each entry:
   - Low confidence + older than `low_max_age_days` → REMOVE
   - Medium confidence + older than `medium_max_age_days` → DEMOTE to low, set Date to today
   - High confidence → NEVER touch
3. Track all prune/demote actions for the reconcile-log

#### Phase 5: Budget Enforcement

1. Recalculate total estimated tokens (word count × 1.3 across all .md files)
2. If any single file exceeds `single_file_tokens_max` (default 8000):
   - Drop lowest-confidence entries from that file until under budget
3. If total exceeds `total_tokens_max` (default 30000):
   - Drop lowest-confidence entries across all files until under budget
   - Prefer dropping from largest files first
4. If any category exceeds `patterns_per_category_max` (default 50):
   - Drop lowest-confidence entries from that category
5. Write updated files

#### Post-Reconciliation: Update Metadata and Log

1. Update `.meta.json`:
   - `last_reconcile`: current ISO 8601 timestamp
   - `estimated_tokens`: fresh word count × 1.3
   - `total_patterns`: fresh count of `**Title:**` lines
   - `context_budget_violations`: reset to 0
   - `reinforcements_since_reconcile`: reset to 0
   - `lock`: null (release lock)
2. Update `meta.yaml` entry counts
3. Append reconcile-log entry to `reconcile-log.md` (newest first, below header):

```
---

## Reconcile: YYYY-MM-DD HH:MM:SS

**Trigger**: <threshold that fired>
**Signal values**: tokens=NNNN, patterns=NN, violations=NN, reinforcements_since=NN

**Backup**: `.backups/reconcile-YYYY-MM-DD-HHMMSS/`

**Actions**:
- Merged N entries
- Pruned N stale entries
- Dropped N lowest-confidence entries for budget
- Budget result: NNNN → NNNN estimated tokens

**Merges**: (if any)
- file.md: "Title A" + "Title B" → "Merged Title"

**Prunes**: (if any)
- file.md: "Title" (low confidence, age: N days)

**Budget drops**: (if any)
- file.md: "Title" (low confidence, N reflections)

**Result**: OK | PARTIAL | FAILED
```

4. Output summary (if manual invocation):
```
Ledger reconciliation complete.
- Trigger: <threshold(s)>
- Merged: N entries
- Pruned: N stale entries
- Budget drops: N entries
- Token reduction: NNNN → NNNN
- Backup: .backups/reconcile-YYYY-MM-DD-HHMMSS/
```

#### `--dry-run` Mode

When `--dry-run` is specified:
- Execute Phases 0-1 normally (guard, lock, threshold check)
- Execute Phases 3-5 analysis only — identify merge candidates, prune candidates, budget drops
- Output what WOULD happen without modifying any files
- Release lock without writing changes

#### `--status` Mode

When `--status` is specified:
- Read `.meta.json` and display current signal values
- Read thresholds from config
- Show which thresholds are exceeded (if any)
- Show time since last reconcile
- Output whether reconciliation would trigger

## Error Handling

- **Ledger directory missing:** For all subcommands except `reset`, if `.smith/vault/ledger/` does not exist, display the "No Ledger found" message from the dashboard section and stop.
- **Individual file missing:** If a specific Ledger file is missing but the directory exists, skip it with a note: `(missing: <filename>)` in any listings. Do not error out.
- **Malformed entries:** If an entry is missing required fields (Date, Category, Confidence), display it with `[???]` placeholders and continue. Do not skip it entirely.
- **No matches for show/promote/demote:** Display a clear "not found" message and suggest running `/smith-ledger list` to see available entries.
