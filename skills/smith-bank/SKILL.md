---
name: smith-bank
description: Captures ideas mid-conversation and stores them in the vault for later processing. Use when the user wants to save an idea, park a thought, or come back to something later. Supports listing, processing, editing, and prioritizing banked ideas.
argument-hint: [list|process|edit|remove|prioritize] [<id>] [--priority <level>] [--system <id>]
---

# Smith Idea Bank

Capture ideas mid-conversation and store them in the vault for later processing. The bank is a section of the vault where ideas get deposited for safekeeping until you're ready to withdraw them.

**Arguments:** $ARGUMENTS

## Vault Logging

Log significant events to the vault session log. Read the session log path from `.smith/vault/.current-session`. If missing, skip logging silently.

Append entries using this format:

```
### [HH:MM:SS] /smith-bank <event>

**User Request:**
> <verbatim user message or idea description that triggered this action>

**Action:** <banked|listed|processed|edited|removed|prioritized>
**Bank ID:** <BANK-NNN>
**Title:** <idea title>
**Outcome:** <what happened>
**Systems affected:** <system IDs>
```

## Behavior

### No Arguments — Bank an Idea

When invoked with no arguments (or via natural language trigger), capture the current conversation's idea:

1. **Analyze the conversation** to understand the idea being banked — what it is, how it came up, what problem it solves, and any initial requirements discussed
2. **Auto-detect systems** the idea would likely impact by scanning `.specify/systems/system-*/spec.md` descriptions against the idea content. Set `primary_system` and `also_affects`.
3. **Determine next bank ID** by scanning `.smith/vault/bank/` for existing files. Extract the highest `BANK-NNN` from frontmatter `id:` fields, then increment. Start at BANK-001 if none exist.
4. **Generate the bank file** at `.smith/vault/bank/YYYY-MM-DD_HHMMSS-<slug>.md` with this format:

```yaml
---
id: BANK-NNN
title: "<concise title>"
created: "YYYY-MM-DDTHH:MM:SS"
source_session: "<current session log filename>"
primary_system: "<detected system or 'unassigned'>"
also_affects: []
status: banked
priority: medium
---

# <Title>

## Origin

<2-3 sentences describing the conversation context that led to this idea — what were we working on, what triggered the thought, why it seemed worth saving>

## Idea

<Clear description of the feature or improvement, written with enough detail that someone reading this cold could understand what to build>

## Requirements (Draft)

<Bullet points capturing any requirements that were discussed, even loosely. Include edge cases or constraints mentioned>

## Systems Affected

- **Primary:** <system name and why>
- **Also affects:** <other systems and why, or "none identified">

## Open Questions

<Any obvious questions that would need answering before this could be built. Pre-populate with the most important unknowns based on the conversation>

## Conversation Reference

Session: <link to vault session log>
Approximate timestamp: <when in the session this idea came up>
```

5. **Confirm** to the user: "Banked as BANK-NNN: <title>. Resume anytime with `/smith-bank process BANK-NNN`."
6. **Return** to the original conversation without disruption — do NOT start any follow-up workflow.

### `list` — Show All Banked Ideas

Display all banked ideas sorted by date descending. Read each `.md` file in `.smith/vault/bank/` (exclude `archive/` subdirectory), extract frontmatter fields.

Format:

```
Bank Vault — N ideas deposited

  BANK-001  [medium]  Trends article recommendation engine      2026-04-03
  BANK-002  [high]    Auto-generate component Storybook stories  2026-04-04
  BANK-003  [medium]  Email thread summarization endpoint        2026-04-05
```

**Filters:**
- `list --priority <level>` — filter by priority (critical, high, medium, low)
- `list --system <system-id>` — filter by primary_system or also_affects containing the system ID

If no ideas exist: "Bank vault is empty. Use `/smith-bank` to deposit your first idea."

### `process <id>` — Withdraw and Build

Withdraws an idea from the bank and starts a `/smith-new` workflow:

1. **Read** the banked spec file matching the given ID (e.g., `BANK-001`)
2. **Update** the bank entry: set `status: in-progress`, add `processing_started: <timestamp>` and `feature_branch: <TBD>` to frontmatter
3. **Invoke `/smith-new`** with the idea description, draft requirements, systems affected, and open questions pre-loaded as the initial feature context. The user should NOT have to re-explain the idea.
4. When the `/smith-new` workflow completes:
   - If built and merged: update bank entry `status: completed`, add `completed: <timestamp>` and `feature_branch: <branch-name>`
   - If queued: update bank entry `status: queued`

### `edit <id>` — Edit a Banked Idea

Open the banked idea file for the given ID. Read and display its current contents, then ask the user what they'd like to change. Support updating:
- Title
- Priority
- Requirements
- Open questions
- Systems affected
- Any free-form notes

Write the updated file back after changes.

### `remove <id>` — Archive a Banked Idea

1. Find the bank file matching the given ID
2. **Ask for confirmation**: "Remove BANK-NNN: <title>? This moves it to the archive. (y/n)"
3. If confirmed: move the file to `.smith/vault/bank/archive/` (create directory if needed)
4. Confirm: "BANK-NNN archived."

### `prioritize <id> --priority <level>` — Change Priority

Quick shorthand to change priority without the full edit flow.

1. Find the bank file matching the given ID
2. Update the `priority:` field in frontmatter to the new level
3. Valid levels: `critical`, `high`, `medium`, `low`
4. Confirm: "BANK-NNN priority updated to <level>."

## Implementation Notes

- Bank files live in `.smith/vault/bank/`, archived files in `.smith/vault/bank/archive/`
- Create `.smith/vault/bank/` if it doesn't exist on first use
- ID matching: scan all `.md` files in `bank/` for frontmatter `id:` field matching the requested ID
- Slug generation: lowercase the title, replace spaces with hyphens, remove special chars, truncate to 50 chars
- This skill should be handled directly in the main session — never delegate to a sub-agent
