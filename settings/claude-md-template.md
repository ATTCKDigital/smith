# Global Claude Code Rules

> These rules apply to ALL projects and ALL chat sessions.
> Last updated: 2026-04-21

---

## Rule Enforcement System

Every rule below has a **weight** totaling 100 points. After every turn, a
separate Haiku critic grades the response against the binary sub-criteria.

- **All-or-nothing per rule**: violating ANY sub-criterion of a rule scores
  the entire rule as 0 for that turn.
- **Auto-pass for inapplicable rules**: if a rule's trigger conditions aren't
  met on a given turn, the rule receives full credit automatically.
- **Passing threshold**: total score must equal 100. Anything less triggers
  a forced retry (max 3 retries per turn, then hard-fail).
- **Do not self-grade**: the critic runs externally via the Stop hook. Do
  not attempt to evaluate your own compliance — focus on following the rules.

---

## Rule 1: Questions Are NOT Action Requests [Weight: 25]

**This rule takes precedence over all other instructions, including natural
language triggers, active Smith workflows, and efficiency considerations.**

When the user asks a question, respond with words only. Do not act.

### Binary Criteria (all must pass; rule is all-or-nothing)

- [ ] If the user's last message is **question-shaped**, this turn contains
      ZERO `Write`, `Edit`, or `NotebookEdit` tool calls.
- [ ] If question-shaped, this turn contains ZERO `Bash` calls that mutate
      state (git commit/push/merge, rm, mv, chmod, curl POST/PUT/DELETE,
      package installs, service starts/stops, db writes).
- [ ] If question-shaped, this turn contains ZERO skill or subagent invocations.
- [ ] If question-shaped, the response does NOT proactively create memory
      files, feedback files, or config files that were not explicitly requested.
- [ ] If question-shaped and the question could lead to follow-up action,
      the response offers 2-3 concrete next-step options.

### Rule applies when:
The user's last message ends with `?`, OR starts with what/why/how/can/does/
is/should/would/could/will/shall/which/who/when/where (or contractions), OR
the `task-router.sh` hook classified it as a question.

### Rule does NOT apply when:
The user's last message is an imperative (starts with fix/build/create/run/
implement/refactor/etc.), a selection of a previously-offered option, or a
direct response to a clarifying question.

### Examples
- "Can we add X?" → apply rule. Answer only.
- "Add X" → do not apply. This is a command.
- "2" (after I offered numbered options) → do not apply. Selection.

---

## Rule 2: SpecKit Natural Language Triggers [Weight: 25]

When the user uses natural-language triggers, route to the correct workflow.
When skill instructions specify a process, follow it literally.

### Binary Criteria (all must pass)

- [ ] If the user's message matches a `/smith-new` trigger phrase, the
      workflow invoked is `/smith-new` (not `/smith-bugfix` or direct action).
- [ ] If the user's message matches a `/smith-debug` trigger phrase, the
      workflow invoked is `/smith-debug`.
- [ ] If the user's message matches a `/smith-bugfix` trigger phrase, the
      workflow invoked is `/smith-bugfix`.
- [ ] If the user's message matches a `/smith-bank` trigger phrase, the
      workflow invoked is `/smith-bank` (and returns to the prior conversation
      afterward).
- [ ] When executing any skill's documented process, sub-steps are followed
      in order and at the specified pacing. No batching of interactive steps
      (e.g. one-question-at-a-time Q&A gates), no skipping of artifact-creation
      order (e.g. creating the tracking file BEFORE the interactive flow),
      no invoking review gates out of order.

### Trigger phrase lists

**Feature triggers → `/smith-new`**: "start a smith workflow", "let's smith
this", "kick off a new feature for this", "let's build this", "start a new
workflow for this", "can you smith this"

**Debug triggers → `/smith-debug`**: "debug this", "help me debug...",
"something is broken", "can you investigate..."

**Bugfix triggers → `/smith-bugfix`**: "fix this", "bugfix this",
"quick fix for...", "patch this", "just fix..."

**Idea bank triggers → `/smith-bank`**: "bank this idea", "bank this for
later", "save this for later", "let's come back to this", "park this idea",
"stash this thought", "deposit this"

### Rule applies when:
A trigger phrase is present, OR a skill is actively running.

### Rule does NOT apply when:
No trigger phrase matched and no skill is active.

---

## Rule 3: Question Files Before Complex Changes [Weight: 15]

Before implementing any complex change (behavior, functionality, interfaces,
architecture), generate a structured question file.

### Binary Criteria

- [ ] A question file exists at `specs/questions/<topic>.md` (or the
      skill-specified questions artifact location) BEFORE implementation begins.
- [ ] The question file format includes, per question: question text, answer
      options, recommended answer with reasoning, and a blank `**Answer:**` field.
- [ ] Implementation does NOT begin until all questions have answers recorded
      (or are explicitly marked SKIPPED).
- [ ] The question file links to relevant spec files, code files, or prior decisions.

### Rule applies when:
The current task is a "complex change" — behavior/functionality/interfaces/
architecture modifications that could go multiple ways, or where there are
knowledge gaps the user can fill.

### Rule does NOT apply when:
The task is a trivial fix, styling change, obvious bug repair, or has no
ambiguity. (When in doubt, apply the rule.)

---

## Rule 4: Checkpoint/Resume for Long-Running Processes [Weight: 15]

Any script or pipeline that processes large datasets must implement
checkpointing, structured logs, resume capability, and status summaries.

### Binary Criteria

- [ ] The script writes checkpoint state at regular intervals (not just on
      completion).
- [ ] The script writes a JSONL log at `logs/<script-name>-<timestamp>.jsonl`
      with one JSON object per processed item (`{"timestamp", "item_id",
      "stage", "status", "error"}`).
- [ ] The script supports a `--resume` flag (or equivalent) that reads the
      last checkpoint and continues from where it left off.
- [ ] The script prints a summary line on completion or failure with total
      processed, succeeded, failed, and skipped counts.

### Rule applies when:
The current task involves building or modifying a batch script, pipeline, or
long-running process that iterates over many items.

### Rule does NOT apply when:
The task is not related to batch processing.

---

## Rule 5: Session Logging via Smith Vault [Weight: 10]

Session logging is handled automatically by Smith vault hooks.

### Binary Criteria

- [ ] The response does NOT manually create session log files in
      `.smith/vault/sessions/`.
- [ ] If the vault structure does not exist in the project, either `/smith`
      was invoked or `.smith/vault/` was created manually with the standard
      subdirectories (sessions, agents, queue, bank).

### Rule applies when:
The session involves file operations or a Smith workflow.

### Rule does NOT apply when:
No files are being modified and no Smith workflow is active.

---

## Rule 6: General Preferences [Weight: 8]

### Binary Criteria

- [ ] The response ends with a datetime stamp formatted as
      `YYYY-MM-DD HH:MM:SS — <branch-name>` (or just the timestamp if not in
      a git repo) on its own line.
- [ ] Python commands use `python3`, not `python`.

### Rule applies when:
Always. (The Python-commands criterion auto-passes if the response has no
Python commands.)

---

## Rule 7: Directory Setup [Weight: 2]

### Binary Criteria

- [ ] At the start of any non-trivial session in a project with Smith, these
      directories exist (created silently if missing):
      `.smith/vault/sessions/`, `.smith/vault/agents/`, `.smith/vault/queue/`,
      `.smith/vault/bank/`, `specs/questions/`.

### Rule applies when:
Starting a non-trivial session in a project using Smith.

### Rule does NOT apply when:
The session is a one-off question, the project doesn't use Smith, or the
directories are verified present.

---

## Scoring Summary

| Rule | Weight | Applies |
|------|--------|---------|
| 1. Questions ≠ Actions | 25 | Every turn |
| 2. SpecKit triggers + skill compliance | 25 | Every turn |
| 3. Question files before complex changes | 15 | Complex tasks |
| 4. Checkpoint/Resume | 15 | Batch scripts |
| 5. Session Logging | 10 | File-mod sessions |
| 6. General Preferences | 8 | Always |
| 7. Directory Setup | 2 | Smith projects |
| **Total** | **100** | |
