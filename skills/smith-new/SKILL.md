---
name: smith-new
description: Start a new feature from scratch or from conversation context. Conversational requirements gathering, planning, questions gate, then fully autonomous build.
---

# SpecKit New Feature Workflow

This is the primary entry point for all new features. It combines requirements gathering, planning, and a questions gate into a single conversational flow, then hands off to autonomous execution.

**Arguments:** $ARGUMENTS

## Vault Logging

Throughout this action, log significant events to the vault session log. Read the session log path from `.smith/vault/.current-session`. If the file is missing or the vault is not initialized, skip all logging silently.

Append entries to the session log using this format:

```
### [HH:MM:SS] /smith-new <event>

**User Request:**
> <verbatim user message that triggered this action — capture the exact words the user typed, including any conversation context that led to the request. For natural language triggers, capture the trigger message. For explicit /smith-new invocations, capture $ARGUMENTS.>

**Synthesized Input:** <brief summary of what's being built>
**Outcome:** <what happened>
**Artifacts:** <files created/modified>
**Systems affected:** <system IDs>
```

Log at these points:
1. **On invocation** — capture the verbatim user request AND the synthesized feature description
2. **After system detection** — which primary system was identified, which other systems are affected
3. **After spec creation** — path to created spec folder and spec.md
4. **After questions generated** — how many questions, path to questions file
5. **After questions answered** — summary of each answer (topic + decision, not full text)
6. **On handoff to build** — note that `/smith-build` autonomous phase was triggered

## Natural Language Triggers

If the user says any of the following (or similar phrases) during a conversation, treat it as invoking this command using the full conversation context as the feature description:
- "start a smith workflow"
- "let's smith this"
- "kick off a new feature for this"
- "let's build this"
- "start a new workflow for this"
- "can you smith this"

When triggered by natural language, synthesize the entire conversation history into a comprehensive feature description and proceed as if that description was passed as `$ARGUMENTS`.

## Phase 0: Pre-Change Exploration (Conditional)

Before creating a worktree, check if the proposed feature warrants impact analysis.

### When to Run Exploration

Run `/smith-explore` automatically if ANY of these conditions are met:
- `$ARGUMENTS` or conversation context mentions: "skill", "hook", "constitution", "CLAUDE.md", "MEMORY.md", "config", "policy"
- The feature touches core Smith infrastructure (`.claude/skills/`, `.smith/`, `.specify/`)
- `--explore` flag is passed explicitly

### Exploration Flow

1. **Run `/smith-explore`** with the feature description and scope auto-detected from context
2. **Wait for the exploration report** — this produces a structured analysis of:
   - Skills affected
   - Configuration file conflicts (per File Purpose Policy in constitution.md §VI)
   - Hooks that might be impacted
   - Cross-system architectural concerns
3. **Evaluate exploration status:**
   - **`clear`**: Continue to Phase 1 (worktree creation)
   - **`conflicts-found`** (warnings only): Present summary to user, ask to proceed or resolve first
   - **`blocking-issues`**: STOP. Present blocking issues and require resolution before continuing

### Skip Exploration

If none of the trigger conditions are met, skip directly to Phase 1. Exploration adds overhead and is only valuable for changes that may have system-wide impacts.

---

## Phase 1: Worktree Creation & Setup

The worktree is created after exploration passes (or is skipped). This ensures the user's current working directory and branch are never touched — the entire workflow is isolated from the start.

0. **Activate workflow tracking** — create a per-branch file in `.smith/vault/active-workflows/` in the **main repo**:
   ```bash
   # After determining branch name in step 4:
   SAFE_BRANCH=$(echo "$BRANCH" | sed 's/[^a-zA-Z0-9._-]/-/g')
   mkdir -p .smith/vault/active-workflows
   cat > .smith/vault/active-workflows/${SAFE_BRANCH}.yaml << EOF
   workflow: smith-new
   feature: <feature-name>
   branch: $BRANCH
   worktree: $WORKTREE_PATH
   started: $(date -u +"%Y-%m-%dT%H:%M:%S")
   EOF
   ```
   Clear this file at the end of Phase 6 (after merge) or if the workflow is abandoned:
   ```bash
   rm -f .smith/vault/active-workflows/${SAFE_BRANCH}.yaml
   ```

1. **Fetch latest main** (does NOT change the user's current branch):
   ```bash
   git fetch origin main
   ```

2. **Generate branch short-name** (2-4 words) from `$ARGUMENTS` or conversation context. If no feature description is available yet (empty args, no context), use a placeholder like `new-feature` and rename the branch later after Phase 2.

3. **Find next feature number** by checking all three sources:
   - Remote branches: `git ls-remote --heads origin | grep -oP '(?<=refs/heads/)\d+' | sort -n | tail -1`
   - Local branches: `git branch | grep -oP '^\s*\d+' | sort -n | tail -1`
   - Specs directories: `ls -d .specify/systems/*/features/[0-9]*-* 2>/dev/null | grep -oP '\d+(?=-)' | sort -n | tail -1`
   - GitHub issues: `gh issue list --limit 1 --json number --jq '.[0].number'`
   Take the maximum across all sources and add 1.

4. **Create worktree with feature branch from `origin/main`**:
   ```bash
   git worktree add /tmp/smith-<slug> -b <number>-<short-name> origin/main
   ```
   Store the worktree path (`/tmp/smith-<slug>`) as `WORKTREE_PATH`. The active-workflow file was already created in step 0 with the branch and worktree info.

   **Note**: The user's current branch is completely unaffected. They can be on any branch — `main`, a feature branch, even a detached HEAD — and this workflow will not interfere.

## Ledger Context (Optional)

If `.smith/vault/ledger/` exists and contains non-empty files, load relevant Ledger sections to inform this workflow. If the directory is missing, empty, or unreadable, skip silently — the Ledger is purely additive and never required.

1. Check: `ls .smith/vault/ledger/*.md 2>/dev/null`
2. If files exist, read the following sections (higher-confidence entries first, truncate at ~2000 tokens per file):
   - `.smith/vault/ledger/patterns.md`
   - `.smith/vault/ledger/project-quirks.md`
3. Use loaded patterns as additional context when gathering requirements and generating specs. The Ledger informs judgment, it does not override spec/plan/constitution.
4. **Budget violation tracking**: If any Ledger file was truncated (entries were dropped to fit within the ~2000 token budget per file), increment `context_budget_violations` in `.smith/vault/ledger/.meta.json` by 1. If `.meta.json` does not exist, create it from the default template first. This signal tells the reconciliation system that the Ledger is too large for the configured budget.

## Phase 2: Requirements Conversation

**Goal**: Arrive at a clear, detailed feature description through conversation. This phase is purely conversational — no file operations needed. The worktree already exists from Phase 1.

### If `$ARGUMENTS` is empty AND no prior conversation context:
- Prompt the user: "What would you like to build?"
- Enter a conversational loop:
  - Ask clarifying questions about scope, user flows, constraints
  - Reflect back your understanding
  - Let the user refine and add detail
  - Continue until the user indicates they're satisfied (e.g., "that's it", "looks good", "let's go")

### If `$ARGUMENTS` is provided:
- Use the provided description as the starting point
- Reflect back your understanding and ask if anything is missing
- Allow one round of refinement if the user wants to adjust

### If triggered mid-conversation (natural language trigger):
- Synthesize the conversation history into a comprehensive feature description
- Present it to the user: "Based on our conversation, here's what I understand you want to build: [summary]. Anything to add or change?"
- Allow refinement

### Output of Phase 2:
A complete feature description string that will be passed to the spec generation step.

## Phase 3: Spec Generation (Subagent — in Worktree)

Once requirements are finalized, launch a subagent to handle spec generation. The worktree (`WORKTREE_PATH`) was already created in Phase 1. All file operations happen there.

If the branch was created with a placeholder name in Phase 1 (because `$ARGUMENTS` was empty), rename it now:
```bash
cd $WORKTREE_PATH && git branch -m <old-placeholder-name> <number>-<short-name>
```
Rename the active-workflow file if the branch name changed:
   ```bash
   OLD_SAFE=$(echo "$OLD_BRANCH" | sed 's/[^a-zA-Z0-9._-]/-/g')
   NEW_SAFE=$(echo "$NEW_BRANCH" | sed 's/[^a-zA-Z0-9._-]/-/g')
   mv .smith/vault/active-workflows/${OLD_SAFE}.yaml .smith/vault/active-workflows/${NEW_SAFE}.yaml
   ```

1. **Auto-detect primary system** (reading from worktree):
   - Read all system spec files at `$WORKTREE_PATH/.specify/systems/system-*/spec.md`
   - Analyze the feature requirements against each system's scope, services, endpoints, and data models
   - Determine `primary_system` (the system most directly impacted) and `also_affects` (other systems touched)
   - Set the feature spec folder path to `.specify/systems/<primary-system>/features/<NNN-short-name>/`
   - If no single system is clearly primary (genuinely cross-cutting), use `.specify/systems/cross-system/features/<NNN-short-name>/`
   - Do NOT ask the user which system to use — determine this automatically
2. **Create feature folder in worktree**:
   ```bash
   mkdir -p $WORKTREE_PATH/.specify/systems/<primary-system>/features/<NNN-short-name>/checklists
   ```
   Note: Do NOT run `create-new-feature.sh` — the worktree creation in Phase 1 already created the branch.
3. **Load spec template**: Read `$WORKTREE_PATH/.specify/templates/spec-template.md`
4. **Write spec.md** to the system-routed feature folder in the worktree with frontmatter:
   ```yaml
   ---
   feature: <NNN-short-name>
   primary_system: <system-folder-name>
   also_affects:
     - <other-system-folder-name>
   branch: <branch-name>
   created: <YYYY-MM-DD>
   status: in-progress
   ---
   ```
   Fill all sections from the requirements conversation:
   - Focus on WHAT and WHY, not HOW
   - Make informed guesses for unspecified details (document in Assumptions)
   - Maximum 0 [NEEDS CLARIFICATION] markers — all ambiguities should have been resolved in conversation
5. **Write quality checklist** at `$WORKTREE_PATH/<feature-folder>/checklists/requirements.md`
6. **Validate spec** against quality criteria (up to 3 iterations)

## Phase 4: Plan Generation (Subagent — in Worktree)

Launch a separate subagent to generate the implementation plan. This preserves context window for the questions phase. **All work happens in `WORKTREE_PATH`.**

The subagent should:

1. **Run setup script** (from worktree):
   ```bash
   cd $WORKTREE_PATH && .specify/scripts/bash/setup-plan.sh --json
   ```
   Parse JSON for FEATURE_SPEC, IMPL_PLAN, SPECS_DIR, BRANCH.

2. **Load context** (from worktree):
   - Read FEATURE_SPEC (spec.md)
   - Read `$WORKTREE_PATH/.specify/memory/constitution.md`
   - Read IMPL_PLAN template

3. **Execute plan workflow**:
   - Fill Technical Context
   - Evaluate constitution gates
   - **Phase 0**: Generate `research.md` (resolve unknowns, research dependencies)
   - **Phase 1**: Generate `data-model.md`, `contracts/`, `quickstart.md`
   - Run `cd $WORKTREE_PATH && .specify/scripts/bash/update-agent-context.sh claude`

4. **Return**: Confirm plan artifacts are written to SPECS_DIR.

## Phase 5: Questions Gate (MANDATORY STOP — in Worktree)

After the plan subagent completes, read ALL plan artifacts from `WORKTREE_PATH` and generate a comprehensive questions file. All file reads/writes in this phase use the worktree.

1. **Read plan artifacts**:
   - `plan.md` — architecture, file structure, tech decisions
   - `research.md` — decisions and alternatives
   - `data-model.md` — entities and relationships (if exists)
   - `contracts/` — API specifications (if exists)
   - `quickstart.md` — integration scenarios (if exists)

2. **Generate `<feature-folder>/questions.md`** (inside the feature's spec folder under `.specify/systems/`) with this structure:

   ```markdown
   # Implementation Questions: [Feature Name]

   **Generated**: [DATE]
   **Feature**: [Link to spec.md]
   **Plan**: [Link to plan.md]
   **Status**: AWAITING ANSWERS

   ---

   ## Q1: [Topic]

   **Context**: [Quote relevant section from plan/spec/research that raises this question]

   **Question**: [Specific question about an implementation decision]

   **Options**:

   | Option | Description | Implications |
   |--------|-------------|--------------|
   | A      | [First option] | [Tradeoffs, effort, risk] |
   | B      | [Second option] | [Tradeoffs, effort, risk] |
   | C      | [Third option] | [Tradeoffs, effort, risk] |

   **Recommended**: [A/B/C] — [Reasoning for recommendation]

   **Answer**: ___

   ---

   [Repeat for all questions]
   ```

3. **Question quality rules**:
   - Questions should be informed by the plan artifacts — technical decisions, not basic requirements
   - Each question must have at least 2 options with clear tradeoffs
   - Every question must have a recommended answer with reasoning
   - Questions should be ordered by impact (highest impact first)
   - Aim for 5-10 questions. Fewer if the feature is straightforward.
   - Do NOT ask about things that have clear best practices or obvious defaults

4. **Walk through questions interactively, one at a time.**

   For each question in the generated questions.md:

   a. **Present** the question with its full context, all options with pros/cons, and the recommended answer with clear reasoning:
      ```
      ## Question [N] of [Total]: [Topic]

      **Context:** [Quote from plan/spec that raises this question]

      **Question:** [Specific implementation decision]

      **Options:**
      | Option | Description | Implications |
      |--------|-------------|--------------|
      | A | [description] | [pros: ..., cons: ...] |
      | B | [description] | [pros: ..., cons: ...] |
      | C | [description] | [pros: ..., cons: ...] |

      **Recommended:** [Option letter] — [Reasoning]

      Reply with an option letter, "yes" to accept the recommendation,
      "skip" to defer, or type a custom answer.
      ```

   b. **Wait for the user's response**, then:
      - `"yes"` / `"recommended"` → use the recommended answer
      - Option letter (`"A"`, `"B"`, etc.) → use that option
      - `"skip"` → mark as `**Answer:** SKIPPED — needs follow-up`
      - Anything else → accept as custom answer

   c. **Immediately update questions.md** — fill in the `**Answer:**` field for that question

   d. **Confirm** and move to the next question: `"Saved: Q[N] → [answer]. ([remaining] remaining)"`

   e. If the user says "done" before all questions, mark remaining as SKIPPED

5. **After all questions answered:**

   a. Display a summary table of all answers
   b. Ask: "Would you like to change any answers? Reply with a question number or 'looks good'."
   c. If changes requested, re-present that question and collect a new answer
   d. Update **Status** in questions.md from "AWAITING ANSWERS" to "ANSWERED"

## Phase 6: Update Plan, Then Build or Queue (in Worktree)

After answers are confirmed. All work continues in `WORKTREE_PATH`. The user's main working directory is never touched.

1. **Update `plan.md`** if any answers change the planned approach:
   - Launch a subagent to read answered questions and update plan.md accordingly
   - This is a targeted update, not a full rewrite

2. **Copy `.env`** from main repo to worktree if Docker-touching (scan plan.md for `docker-compose.yml`, `Dockerfile` references):
   ```bash
   cp <main-repo-path>/.env $WORKTREE_PATH/.env
   ```
   If Docker-touching, display warning:
   > "This feature modifies Docker configuration. The worktree isolates git only — Docker operations will affect running containers."

3. **Build or Queue decision point.** Ask the user:

   > All questions answered and spec is ready. Would you like to:
   > 1. **Build now** — launch `/smith-build` in the worktree for autonomous implementation
   > 2. **Queue for later** — commit spec artifacts, push, and add to the Smith queue for batch processing

   ---

   **If "Queue for later"** (or "2", "queue", "later"):

   a. Ask: "Priority? (critical / high / medium / low)" — default to `medium` if the user just says "queue" without specifying
   b. **Commit spec artifacts** in the worktree — stage and commit all files in the feature spec folder (spec.md, plan.md, questions.md, research.md, data-model.md, contracts/, checklists/):
      ```bash
      cd $WORKTREE_PATH && git add <feature-spec-folder>/
      cd $WORKTREE_PATH && git commit -m "docs: spec artifacts for <feature-name> — ready for queued build

      Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
      ```
   c. **Push the feature branch from the worktree:**
      ```bash
      cd $WORKTREE_PATH && git push -u origin <branch-name>
      ```
   d. **Create the queue entry** in the **main repo** at `.smith/vault/queue/<NNN-short-name>.md` with this format:
      ```yaml
      ---
      task: "Build feature: <feature-name>"
      branch: "<feature-branch-name>"
      spec_path: "<path to the feature spec folder on the feature branch>"
      primary_system: "<system ID from spec frontmatter>"
      created: "<ISO timestamp>"
      complexity: autonomous
      priority: <user's choice or medium>
      status: pending
      depends_on: []
      ---

      ## Context

      <brief description of the feature and key decisions from the questions phase>

      ## Artifacts on branch

      - spec.md — feature specification
      - plan.md — implementation plan
      - questions.md — clarification questions (all answered)
      - <list any other artifacts: research.md, data-model.md, contracts/, etc.>

      ## Execution Instructions

      Run `/smith-build` from the `<branch-name>` branch with feature dir `<spec_path>`.
      ```
   e. **Clean up worktree:**
      ```bash
      git worktree remove $WORKTREE_PATH
      ```
   f. **Clear active-workflow file** in the main repo:
      ```bash
      SAFE_BRANCH=$(echo "$BRANCH" | sed 's/[^a-zA-Z0-9._-]/-/g')
      rm -f .smith/vault/active-workflows/${SAFE_BRANCH}.yaml
      ```
   g. Confirm: "Queued: `<filename>` (priority: `<level>`, complexity: autonomous). Feature branch `<branch-name>` pushed with all spec artifacts. Run `/smith-queue list` to see pending tasks, or the 2am scheduler will pick it up automatically."
   h. **STOP here.** Do NOT launch `/smith-build`.

   ---

   **If "Build now"** (or "1", "build now", "yes", "go"):

4. **Launch `/smith-build`** in the worktree to execute the entire autonomous phase:
   - Pass `WORKTREE_PATH` and the feature directory path as context
   - This runs as a subagent chain (see smith-build skill)
   - Wait for completion

5. **Display final summary** to the user:
   - Feature name and branch
   - Files created/modified
   - PR link
   - Release notes summary
   - Link to `specs/<feature>/release.md`

6. **Merge PR** from the **main repo directory** (not the worktree — avoids "main already checked out" errors):
   **IMPORTANT**: Always run `gh pr merge` from the **primary repo directory**.
   ```bash
   cd <main-repo-path> && gh pr merge <PR_NUMBER> --squash --delete-branch
   cd <main-repo-path> && git pull origin main
   ```
   - Squash-merge the PR to keep history clean
   - Delete the remote feature branch
   - Pull latest main so the local copy is up to date

7. **Display workflow summary** with aggregated metrics:

   Read the session log and aggregate all metrics entries and subagent completion entries:

   ```
   === Workflow Summary ===

   Feature: <feature-name>
   Branch: <branch-name>
   Duration: <end_time - started timestamp from active-workflow>
   PR: <PR number>

   Main Session:
   - Estimated tokens: ~<sum of all Metrics entry totals / 4>
   - Tool calls: <count of Metrics entries>

   Subagents:
   - Count: <number of "Subagent completed" entries>
   - Total tokens: <sum of subagent total_tokens>
   - Total tool uses: <sum of subagent tool_uses>
   - Total duration: <sum of subagent duration_ms>ms

   Files Changed:
   <list from git diff --name-only main..HEAD>
   ```

   Log this summary to the session log as well.

8. **Clean up worktree:**
   ```bash
   git worktree remove $WORKTREE_PATH
   ```

9. **Clear workflow tracking** — remove the active-workflow file:
   ```bash
   SAFE_BRANCH=$(echo "$BRANCH" | sed 's/[^a-zA-Z0-9._-]/-/g')
   rm -f .smith/vault/active-workflows/${SAFE_BRANCH}.yaml
   ```

### Post-Workflow Reflection

After workflow completion (success or failure), trigger a Ledger reflection if enabled:

1. Read `.smith/config.json` — if `ledger.auto_reflect` is `true` (default), proceed
2. Launch a **non-blocking** background sub-agent using the configured reflection model (default: Haiku):
   - Pass: current session log path, `.smith/vault/ledger/` path
   - The sub-agent runs the `smith-reflect` workflow
   - Do NOT wait for the sub-agent to complete
3. If `.smith/config.json` is missing or `ledger.auto_reflect` is `false`, skip silently

### Post-Reflection Reconciliation Check

After reflection completes (or is skipped):

1. Read `.smith/config.json` — if `ledger.reconcile.auto_reconcile` is `false`, skip
2. Read `.smith/vault/ledger/.meta.json` — check signals against thresholds:
   - `estimated_tokens > thresholds.total_tokens_max` (default 30000)
   - `context_budget_violations > thresholds.context_violations_threshold` (default 3)
   - `reinforcements_since_reconcile > thresholds.reinforcements_threshold` (default 50)
3. Check minimum interval: if `last_reconcile` is less than `minimum_hours_between_reconciles` (default 6) hours ago, skip
4. If any threshold exceeded AND minimum interval has passed:
   - Launch a **non-blocking** background sub-agent using the configured `reconcile_model` (default: Haiku)
   - Pass: "Run /smith-ledger reconcile on this project"
   - Do NOT wait for the sub-agent to complete
5. If no threshold exceeded, `.meta.json` is missing, or config is missing, skip silently

## Key Rules

- All paths must be absolute
- For single quotes in args, use escape syntax: `'I'\''m Groot'`
- **Worktree isolation**: The worktree is created in Phase 1, before any other work. ALL file operations from Phase 3 onward happen in the worktree (`WORKTREE_PATH`). Never checkout the feature branch or write files in the user's main working directory. The only files written to the main repo are vault entries (`.smith/vault/queue/`, `.smith/vault/.active-workflow`). The user's current branch is never changed or checked.
- The questions gate is MANDATORY — never skip it
- If context window is getting large after the conversation phase, summarize requirements before launching subagents
