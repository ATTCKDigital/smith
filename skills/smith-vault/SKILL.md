---
name: smith-vault
description: Browse vault contents — session logs, sub-agent memory, and queue status.
argument-hint: [sessions|agents|queue|status|projects] [<name>]
---

# Smith Vault Browser

Browse the contents of the `.smith/vault/` persistent memory system.

**Arguments:** $ARGUMENTS

## Behavior

### No Arguments — Dashboard Summary

When invoked with no arguments, show a summary dashboard:

1. **Recent Sessions:** List the 5 most recent session logs from `.smith/vault/sessions/` with their date, status (from frontmatter), branch, and number of file change entries (count lines matching `**Edit**` or `**Write**`).

2. **Active Sub-Agents:** List any sub-agent type/ID combinations found in `.smith/vault/agents/`. For each type directory, list identifiers (filenames) with their invocation count (count `### Invocation` headings in each file).

3. **Queue Status:** Count of `.md` files in `.smith/vault/queue/`. Show "Empty" if none.

4. **Bank:** Count of `.md` files in `.smith/vault/bank/` (excluding `archive/` subdirectory). Show "Empty" if none.

5. **Vault Size:** Show total file count and disk usage of `.smith/vault/`.

### Subcommands

- **`/smith-vault sessions`** — List all session logs with date, status, branch, and file change count. Sort by date descending.

- **`/smith-vault sessions <filename>`** — Show the full contents of a specific session log file. Accept either the full filename or a partial match (e.g., `2026-04-02` matches the first session from that date).

- **`/smith-vault agents`** — List all sub-agent types (subdirectories of `agents/`) and their identifiers with invocation counts.

- **`/smith-vault agents <type>`** — List all identifiers for a given agent type with their full invocation history.

- **`/smith-vault queue`** — Show pending queue items. List each `.md` file in `queue/` with its frontmatter summary. Show "Queue is empty" if none.

- **`/smith-vault status`** — Show vault health metrics:
  - Total session count
  - Active vs completed sessions
  - Total agent entries (across all types)
  - Total queue items
  - Total banked ideas (in `.smith/vault/bank/`, excluding archive)
  - Disk usage of `.smith/vault/`
  - **Routing breakdown** (current session): Count `### Task routed` entries in the current session log, group by `**Classification:**` value, and display:
    ```
    Routing breakdown (this session):
      simple-question:  14 (handled directly)
      explore:           3 (delegated to Haiku)
      implement:         5 (delegated to Opus)
      review:            2 (delegated to Sonnet)
      debug:             1 (delegated to Opus)
      docs:              0
      plan:              1 (delegated to Opus)
    ```

- **`/smith-vault projects`** — Read `~/.smith/projects.json` and list all registered projects with their vault paths and last session dates. Highlight the current project.

## Implementation Notes

- All data is read from `.smith/vault/` using standard file reads and grep
- Session frontmatter is YAML — parse `status`, `branch`, `session_start` fields
- File change count = number of lines containing `**Edit**` or `**Write**` in a session log
- Agent invocation count = number of `### Invocation` headings in an agent file
- For partial filename matches on sessions, match against the date portion (YYYY-MM-DD)
- If the vault directory doesn't exist, show a message: "No vault found. Run `/smith` to initialize."
