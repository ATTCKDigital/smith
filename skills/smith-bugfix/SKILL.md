---
name: smith-bugfix
description: Lightweight fix workflow for bugs and small changes. Autonomous from invocation through merged PR — no questions gate, no spec generation, no planning phase.
---

# SpecKit Bugfix Workflow

A streamlined alternative to `/smith-new` for bugs, small changes, and trivial fixes that don't require requirements gathering, planning, or a questions gate. Runs fully autonomously from invocation to merged PR.

**Arguments:** $ARGUMENTS

## Vault Logging

Throughout this action, log significant events to the vault session log. Read the session log path from `.smith/vault/.current-session`. If the file is missing or the vault is not initialized, skip all logging silently.

Append entries using this format:

```
### [HH:MM:SS] /smith-bugfix <event>

**User Request:**
> <verbatim user message that triggered this action — capture the exact words the user typed describing the bug or fix needed. For natural language triggers like "fix this", include the preceding context that describes what's broken.>

**Synthesized Input:** <brief summary of the fix being applied>
**Outcome:** <what happened>
**Artifacts:** <files created/modified>
**Systems affected:** <system IDs>
```

Log at these points:
1. **On invocation** — capture the verbatim user request AND the synthesized bug description
2. **After branch created** — branch name
3. **After fix applied** — files modified, brief description of the fix
4. **After tests** — pass/fail summary
5. **After specs updated** — which specs were updated
6. **On completion** — PR number, merge status, success/failure

## When to Use This (vs `/smith-new`)

Use `/smith-bugfix` when:
- Fixing a bug or broken behavior
- Making a small, well-defined change (rename, restyle, config tweak)
- The change is scoped to 1-3 files with no design ambiguity

Upgrade to `/smith-new` if during implementation you discover:
- Multiple systems need coordinated changes
- Design decisions require user input
- The scope is larger than initially thought

**If upgrading**: STOP, tell the user, and offer to switch to `/smith-new` with the context gathered so far.

## Natural Language Triggers

If the user says any of the following (or similar phrases), treat it as invoking this command:
- "fix this"
- "bugfix this"
- "quick fix for..."
- "patch this"
- "just fix..."

When triggered by natural language, synthesize the conversation history into a concise bug/fix description and proceed as if that description was passed as `$ARGUMENTS`.

## Phase 1: Branch Safety & Setup

0. **Activate workflow tracking** — create `.smith/vault/.active-workflow`:
   ```
   workflow: smith-bugfix
   feature: <bug description slug>
   branch: <to be determined>
   started: <ISO timestamp>
   ```
   Update `branch` once the fix branch is created. Clear this file at the end after merge or if abandoned.

1. **Check current branch**:
   ```bash
   git rev-parse --abbrev-ref HEAD
   ```
   - If **on `main`**: Proceed.
   - If **NOT on `main`**: Ask the user how to proceed:
     > You're currently on branch `<branch-name>`. Options:
     > 1. **Switch to main** — stash changes and switch (default)
     > 2. **Run fix in worktree** — create an isolated worktree from main, run the fix there
     > 3. **Cancel** — abort the bugfix

     **If "Switch to main"** (or "1", "switch", default):
     ```bash
     git stash --include-untracked
     git checkout main
     git pull origin main
     ```
     Note: If stash captured changes, warn the user in the final summary.

     **If "Run fix in worktree"** (or "2", "worktree"):
     - Set `WORKTREE_MODE=true` and `ORIGINAL_BRANCH=<current-branch>`
     - Create worktree from main:
       ```bash
       git worktree add /tmp/smith-bugfix-<slug> main
       ```
     - Copy `.env` to worktree:
       ```bash
       cp .env /tmp/smith-bugfix-<slug>/.env
       ```
     - All subsequent phases (2-7) run inside the worktree directory.
     - After Phase 7 merge: clean up worktree from the primary repo:
       ```bash
       cd <PRIMARY_REPO> && git worktree remove /tmp/smith-bugfix-<slug>
       ```
     - On failure: preserve worktree for debugging, log the path.
     - User remains on `<original-branch>` throughout.

     **If "Cancel"** (or "3", "cancel"): STOP.

     **IMPORTANT**: When in worktree mode, always run `gh pr merge` from the **primary repo directory**, not from the worktree (avoids "main already checked out" errors).

2. **Ensure main is up to date**:
   ```bash
   git pull origin main
   ```

3. **Create fix branch**:
   - Generate a short slug (2-4 words) from the fix description
   - Create and switch to the branch:
     ```bash
     git checkout -b fix/<slug>
     ```

## Ledger Context (Optional)

If `.smith/vault/ledger/` exists and contains non-empty files, load relevant Ledger sections to inform this bugfix. If the directory is missing, empty, or unreadable, skip silently — the Ledger is purely additive and never required.

1. Check: `ls .smith/vault/ledger/*.md 2>/dev/null`
2. If files exist, read the following sections (higher-confidence entries first, truncate at ~2000 tokens per file):
   - `.smith/vault/ledger/antipatterns.md`
   - `.smith/vault/ledger/edge-cases.md`
3. Use loaded antipatterns and edge cases as additional context to avoid known failure modes. The Ledger informs judgment, it does not override spec/plan/constitution.
4. **Budget violation tracking**: If any Ledger file was truncated (entries were dropped to fit within the ~2000 token budget per file), increment `context_budget_violations` in `.smith/vault/ledger/.meta.json` by 1. If `.meta.json` does not exist, create it from the default template first. This signal tells the reconciliation system that the Ledger is too large for the configured budget.

## Phase 2: Spec Cross-Reference

Before writing any code, check existing specs for context and conflicts.

1. **Identify affected systems** from the fix description and map to spec directories:
   - `services/command-center/` → `specs/system-15-command-center/spec.md`
   - `services/email-pipeline/` → `specs/system-03-email-archive-contact-graph/spec.md`
   - `services/sentiment-engine/` → `specs/sentiment-engine/spec.md`
   - `services/communication-triage/` → `specs/system-05-communication-triage/spec.md`
   - `services/voice-training/` → `specs/system-04-personal-voice/spec.md`
   - `docker-compose.yml` → `specs/system-01-core-infrastructure/spec.md`
   - Other mappings as discovered from `specs/*/spec.md` content

2. **Read relevant spec.md files** and check:
   - Is the "broken" behavior actually intentional per the spec?
   - Are there related requirements that could be affected by this fix?
   - Are there any conflicting specs?

3. **If a conflict is found**: STOP the workflow and alert the user. Explain the conflict and ask how to proceed. This is the ONLY point where the workflow may pause.

4. **If no conflicts**: Continue silently.

## Ledger-Informed Auto-Retry

If the bugfix execution fails, check config for auto-retry:

1. Read `.smith/config.json` — check `ledger.auto_retry` and `ledger.max_retries`
2. If `auto_retry` is `false` (default) or config is missing, do NOT retry — fail normally
3. If `auto_retry` is `true`:
   a. Re-read `.smith/vault/ledger/antipatterns.md` to get the latest failure patterns
   b. Analyze the failure against known antipatterns to adjust the approach
   c. Retry the fix with the adjusted approach
   d. Repeat up to `max_retries` times (default: 2), re-reading antipatterns before each attempt
   e. If all retries exhausted, fail with a summary of all attempts
4. Each retry attempt is logged to the session log with attempt number and adjusted approach

## Phase 3: Implement the Fix

1. **Read the affected files** to understand current behavior
2. **Implement the fix** — keep changes minimal and focused
3. **Do NOT**:
   - Refactor surrounding code
   - Add features beyond the fix
   - Modify unrelated files
   - Add unnecessary abstractions

## Phase 4: Docker Rebuild (if applicable)

If any files changed belong to a Docker service:

1. **Identify affected services** from modified file paths
2. **Rebuild**:
   ```bash
   docker compose up -d --build <service-name>
   ```
3. **Verify health**:
   ```bash
   bash scripts/health-check.sh
   ```
4. If unhealthy: attempt one restart, log the issue

**Skip this phase** if changes are limited to specs, docs, or config files that don't affect running services.

## Phase 5: Run Tests

### 5.1 Unit Tests
- **If frontend code changed**: `cd services/command-center && pnpm test`
- **If Python service changed**: `cd services/<service> && poetry run pytest`

### 5.2 Playwright E2E Tests (if frontend files were modified)
- Check if any files matching `services/command-center/src/**` were modified
- **If YES**: `cd services/command-center && pnpm exec playwright test`
- **If NO**: Skip Playwright

### 5.3 Lint
- **If frontend**: `cd services/command-center && pnpm lint`
- **If Python**: `cd services/<service> && poetry run ruff check .`

### 5.4 Test Failure Handling
- If tests fail due to the fix: fix the code and re-run (up to 3 attempts)
- If tests fail for unrelated reasons: note in the commit message body, continue
- If the fix itself causes tests to fail after 3 attempts: STOP and alert the user

## Phase 6: Update Specs & Changelog

### 6.1 Update System Spec

For each affected system spec.md:
1. Read the current spec
2. Add or append to an "Implementation History" section
3. Add a dated entry describing the fix
4. Keep it concise and factual

### 6.2 Update STATUS.md
If the fix is relevant to project status tracking, update `STATUS.md`.

## Phase 7: Commit, Push & Merge

### 7.1 Commit
```bash
git add <all modified files — list explicitly, never git add -A>
git commit -m "fix: <description>

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

- Use `fix:` conventional commit prefix
- Stage files explicitly (never `git add -A` or `git add .`)
- Do NOT stage `.env` files or credentials

### 7.2 Push
```bash
git push -u origin fix/<slug>
```

### 7.3 Create PR & Merge
```bash
gh pr create --title "fix: <short title>" --body "$(cat <<'EOF'
## Summary
<1-3 bullet points describing the fix>

## What was broken
<Brief description of the bug/issue>

## What changed
<List of files and what changed in each>

## Test plan
- [ ] Unit tests pass
- [ ] E2E tests pass (if applicable)
- [ ] Docker health check passes (if applicable)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Then merge:
```bash
gh pr merge <pr-number> --squash --delete-branch
```

### 7.4 Return to main
```bash
git checkout main
git pull origin main
```

## Phase 8: Post-Merge Rebuild & Summary

### 8.1 Rebuild affected services (on main)
```bash
docker compose up -d --build <service-name>
bash scripts/health-check.sh
```

### 8.2 Display Summary

Output to the user:
- Fix description
- PR link (merged)
- Files modified
- Test results
- Any warnings (stashed changes, unrelated test failures)
- Confirmation that we're back on `main` with services healthy

## Workflow Cleanup

After the bugfix is merged (or abandoned), clear `.smith/vault/.active-workflow` to deactivate model routing.

## Post-Workflow Reflection

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

- ALL phases run without user interaction (except spec conflict in Phase 2)
- Never use `git add -A` or `git add .` — always stage specific files
- Never commit `.env` files or credentials
- Keep changes minimal — this is a fix, not a feature
- Always rebuild Docker after code changes
- If scope creep is detected, STOP and suggest upgrading to `/smith-new`
- No questions.md, no plan.md, no tasks.md, no release.md — these are for features
