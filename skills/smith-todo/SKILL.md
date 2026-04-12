---
name: smith-todo
description: Manage daily todo lists stored in the vault. Supports listing, adding, completing, deferring, editing, removing items, reviewing past days, weekly overview, and completion stats.
argument-hint: [list|add|done|defer|remove|edit|review|week|stats] [<id-or-title>] [--date YYYY-MM-DD] [--to YYYY-MM-DD]
---

# Smith Todo

Manage daily todo lists stored in `.smith/vault/todo/`. Each day has one file (`todo-YYYY-MM-DD.md`) containing that day's items. Items are simple: title, status, and created date. The daily briefing N8N workflow auto-generates today's file each weekday morning at 7am EST; this skill lets you manage items manually at any time.

**Arguments:** $ARGUMENTS

## Vault Logging

Log significant events to the vault session log. Read the session log path from `.smith/vault/.current-session`. If missing, skip logging silently.

Append entries using this format:

```
### [HH:MM:SS] /smith-todo <event>

**Action:** <list|add|done|defer|remove|edit|review|week|stats>
**Date:** <YYYY-MM-DD>
**Outcome:** <what happened>
```

## Todo File Format

Each daily file lives at `.smith/vault/todo/todo-YYYY-MM-DD.md`:

```markdown
---
date: "YYYY-MM-DD"
generated: "YYYY-MM-DDTHH:MM:SS"
source: auto|manual
---

# Daily Todo — YYYY-MM-DD

## Summary

<Brief overview of the day: calendar highlights, email activity, key priorities>

## Items

- [ ] `TODO-001` Item title here
- [ ] `TODO-002` Another item
- [x] `TODO-003` Completed item
- [~] `TODO-004` Deferred item → YYYY-MM-DD

## Email Activity (Last 24h)

| Sender | Subject | Status | Intent |
|--------|---------|--------|--------|
| jane@example.com | Re: Project update | replied | question |
| bob@example.com | Contract review | pending | request |
| noreply@service.com | Newsletter | skipped | spam |

## Calendar — Remainder of Week

| Date | Time | Event |
|------|------|-------|
| Mon 04/07 | 10:00 AM | Team standup |
| Tue 04/08 | 2:00 PM | Client review |

## Completion Review (Previous Day)

| Item | Status | Confidence | Evidence |
|------|--------|------------|----------|
| Review PR #168 | done | high | Merged commit da17f19 |
| Reply to Jane | unverified | medium | No email exchange found |
```

### Item ID Convention

Item IDs are sequential within each day's file: `TODO-001`, `TODO-002`, etc. When adding items, scan existing items to find the next available number.

## Subcommands

### No Arguments / `list` — Show Today's Items

Display today's todo items. If no file exists for today, say "No todo list for today. Use `/smith-todo add <title>` to create one, or wait for the morning briefing."

**Format:**

```
Daily Todo — 2026-04-07 (Mon)

  [ ] TODO-001  Reply to Jane about contract review
  [ ] TODO-002  Review PR #171
  [x] TODO-003  Team standup at 10am
  [~] TODO-004  Update spec for System 12 → deferred to 04/08

  3 pending · 1 done · 1 deferred
```

**Optional flag:** `list --date YYYY-MM-DD` — show a different day's list.

### `add <title>` — Add a Todo Item

1. **Determine target date** — defaults to today. Use `--date YYYY-MM-DD` to target a different day.
2. **Find or create the day's file**:
   - If the file exists, read it and determine the next item ID.
   - If no file exists, create one with `source: manual` in frontmatter, an empty Summary, and no Email Activity / Calendar / Completion Review sections.
3. **Append** the new item to the `## Items` section: `- [ ] \`TODO-NNN\` <title>`
4. **Confirm:** "Added TODO-NNN: <title> to <date>."
5. **Show full list** — immediately display the full todo list for the target date using the same format as the `list` subcommand (all items with pending/done/deferred counts).

### `done <id>` — Mark Item Complete

1. **Find** the item by ID in today's file (or use `--date` to target another day).
2. **Update** the checkbox from `- [ ]` to `- [x]`.
3. **Confirm:** "TODO-NNN marked done."

If the item is already done: "TODO-NNN is already complete."
If the item doesn't exist: "TODO-NNN not found in <date>'s list."

### `defer <id>` — Defer Item to Another Day

1. **Find** the item by ID in today's file.
2. **Update** the checkbox from `- [ ]` to `- [~]` and append ` → <target-date>`.
   - Default target: next business day (skip weekends).
   - Use `--to YYYY-MM-DD` to specify a different date.
3. **Copy** the item (as `- [ ]` with a new ID) into the target date's file. Create the target file if needed.
4. **Confirm:** "TODO-NNN deferred to <target-date> as TODO-MMM."

### `remove <id>` — Remove an Item

1. **Find** the item by ID in today's file.
2. **Remove** the line entirely.
3. **Confirm:** "TODO-NNN removed."

Do NOT ask for confirmation — this is a lightweight action on a daily list.

### `edit <id>` — Edit an Item

1. **Find** the item by ID in today's file.
2. **Display** the current text and ask the user what they'd like to change (title only, since metadata is minimal).
3. **Update** the line in place.
4. **Confirm:** "TODO-NNN updated."

### `review [YYYY-MM-DD]` — Review a Past Day's Briefing

1. **Read** the specified day's file (defaults to yesterday if no date given).
2. **Display** the full file contents including Summary, Items, Email Activity, Calendar, and Completion Review sections.
3. If no file exists: "No todo file found for <date>."

### `week` — Weekly Overview

1. **Scan** `.smith/vault/todo/` for all files in the current week (Monday through Friday).
2. **For each day**, extract the item counts (pending, done, deferred).
3. **Display:**

```
Weekly Overview — Week of 2026-04-07

  Mon 04/07    3 pending · 2 done · 1 deferred
  Tue 04/08    5 pending · 0 done · 0 deferred
  Wed 04/09    (no file)
  Thu 04/10    (no file)
  Fri 04/11    (no file)

  Week total: 8 pending · 2 done · 1 deferred
```

### `stats` — Completion Statistics

1. **Scan** all files in `.smith/vault/todo/`.
2. **Calculate:**
   - Total items across all days
   - Completion rate (done / total)
   - Average items per day
   - Most common deferred-to pattern (same day? next day? end of week?)
   - Longest streak of 100% completion days
   - Items carried forward most often (if any pattern emerges from deferred items with similar titles)
3. **Display** as a compact summary.

## Implementation Notes

- Todo files live in `.smith/vault/todo/`. Create the directory if it doesn't exist on first use.
- File naming: `todo-YYYY-MM-DD.md` — always use this exact format.
- Checkbox states: `[ ]` = pending, `[x]` = done, `[~]` = deferred.
- "Next business day" means skip Saturday and Sunday.
- This skill should be handled directly in the main session — never delegate to a sub-agent.
- When creating a file manually (no auto-briefing), omit the auto-generated sections (Email Activity, Calendar, Completion Review) and set `source: manual`.
- When the morning briefing creates the file, it sets `source: auto` and populates all sections.
