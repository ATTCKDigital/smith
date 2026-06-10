---
name: smith-build
description: Autonomous build phase — generates tasks, implements, tests, commits, pushes, merges, and produces release notes. Runs without user interaction.
---

# SpecKit Autonomous Build

Executes the full build pipeline from answered questions through to merged PR and release notes. This command runs entirely without user interaction, using subagents to manage context.

**Arguments:** $ARGUMENTS

## Vault Logging

Throughout this action, log significant events to the vault session log. Read the session log path from `.smith/vault/.current-session`. If the file is missing or the vault is not initialized, skip all logging silently.

Append entries using this format:

```
### [HH:MM:SS] /smith-build <event>

**User Request:**
> <verbatim user message that triggered this action — if invoked via /smith-new, reference the original request logged there. If invoked manually for recovery, capture the recovery command.>

**Synthesized Input:** <brief summary of what's being built>
**Outcome:** <what happened>
**Artifacts:** <files created/modified>
**Systems affected:** <system IDs>
```

Log at these points:
1. **On invocation** — which feature is being built, fresh run or recovery, reference to original user request
2. **After each phase completes** — phase name, tasks completed count, key artifacts produced
3. **After system spec updates** — which system specs were updated and what changed
4. **After PR created** — PR number, title
5. **After merge** — success/failure, branch cleanup status
6. **On completion** — brief release notes summary, total files created/modified, services rebuilt

## Subagent Invocation Logging

Immediately before every Agent tool call in this workflow (including each phase subagent, testing subagent, and spec-update subagent), append a block to the session log. The Agent tool's return value does not expose `subagent_type` or `model` to the parent, so this is the only place that information can be captured.

```
### [HH:MM:SS] Subagent invoked: <description>

**Type:** <subagent_type or "general">
**Model:** <model override passed to Agent, or "inherited" if none>
```

After the Agent tool returns, the `subagent-vault-writeback.sh` hook automatically appends a matching "Subagent completed" block with metrics read from the sidechain transcript — do not duplicate that logging in the skill.

This command can be invoked in two ways:
1. **Automatically by `/smith-new`** after questions are answered (normal flow)
2. **Manually by the user** via `/smith-build` for recovery if a previous build failed partway

## Phase 0: Context Discovery

0. **Activate workflow tracking** — invoke the shipped helper to create the per-branch marker. The workflow-gate hook (PR #20) exempts this exact helper by basename so the bootstrap runs even when no marker exists yet (per spec/31-workflow-gate-bootstrap). The helper also stamps the current session log with a `workflow-start` line so `workflow-summary.sh --totals-only` can attribute tokens correctly:
   ```bash
   BRANCH=$(git rev-parse --abbrev-ref HEAD)
   # Derive a slug from the branch (drop number prefix if numbered):
   SLUG=$(echo "$BRANCH" | sed 's/^[0-9]*-//')
   ~/.smith/scripts/create-active-workflow.sh \
     --branch "$BRANCH" \
     --workflow smith-build \
     --slug "$SLUG" \
     --worktree "$(pwd)"
   ```
   (Falls back to `scripts/create-active-workflow.sh` in repo-dev layouts.) Clear this marker at the end of Phase 7 (after release notes) or on unrecoverable failure. Use the shipped helper so this works even on projects that deny `Bash(rm:*)`:
   ```bash
   .specify/scripts/bash/clear-active-workflow.sh "$BRANCH"
   ```

1. **Detect worktree context**:
   ```bash
   COMMON_DIR=$(git rev-parse --git-common-dir)
   GIT_DIR=$(git rev-parse --git-dir)
   ```
   - If `COMMON_DIR` ≠ `GIT_DIR`: we are in a worktree. Set `WORKTREE_MODE=true` and `WORKTREE_PATH=$(pwd)`.
   - Detect the primary repo path: `PRIMARY_REPO=$(git rev-parse --git-common-dir | sed 's|/\.git$||')`
   - Log worktree status to vault session log.

2. **Run prerequisites check**:
   ```bash
   .specify/scripts/bash/check-prerequisites.sh --json --paths-only
   ```
   Parse JSON for `FEATURE_DIR` and `AVAILABLE_DOCS`.

   If the script fails (e.g., not on a feature branch), check:
   - Is there a feature branch that matches `$ARGUMENTS`?
   - Are there incomplete tasks in any `specs/*/tasks.md`?
   - If recovery is possible, switch to the correct branch and retry.
   - If not, ERROR with guidance.

3. **Load feature context** from FEATURE_DIR:
   - `spec.md` (REQUIRED)
   - `plan.md` (REQUIRED)
   - `questions.md` (REQUIRED — verify Status is "ANSWERED")
   - `tasks.md` (OPTIONAL — may not exist yet if this is first run)
   - `data-model.md` (IF EXISTS)
   - `contracts/` (IF EXISTS)
   - `research.md` (IF EXISTS)
   - `quickstart.md` (IF EXISTS)

## Ledger Context (Optional)

If `.smith/vault/ledger/` exists and contains non-empty files, load relevant Ledger sections to inform this workflow. If the directory is missing, empty, or unreadable, skip silently — the Ledger is purely additive and never required.

1. Check: `ls .smith/vault/ledger/*.md 2>/dev/null`
2. If files exist, read the following sections (higher-confidence entries first, truncate at ~2000 tokens per file):
   - `.smith/vault/ledger/patterns.md`
   - `.smith/vault/ledger/antipatterns.md`
   - `.smith/vault/ledger/tool-preferences.md`
   - `.smith/vault/ledger/edge-cases.md`
   - `.smith/vault/ledger/project-quirks.md`
3. Use loaded patterns as additional context — not as hard rules. The Ledger informs judgment, it does not override spec/plan/constitution.
4. **Budget violation tracking**: If any Ledger file was truncated (entries were dropped to fit within the ~2000 token budget per file), increment `context_budget_violations` in `.smith/vault/ledger/.meta.json` by 1. If `.meta.json` does not exist, create it from the default template first. This signal tells the reconciliation system that the Ledger is too large for the configured budget.

4. **Determine build state** (for recovery):
   - If `tasks.md` exists, check for completed tasks `[X]` vs incomplete `[ ]`
   - If some tasks are complete, this is a **recovery run** — skip to Phase 2 (implementation)
   - If no tasks.md exists, this is a **fresh run** — start from Phase 1

## Phase 1: Task Generation (Subagent)

Launch a subagent to generate the task breakdown.

The subagent should:

1. **Read artifacts**: spec.md, plan.md, data-model.md, contracts/, research.md, quickstart.md
2. **Generate `tasks.md`** following the strict format:
   ```
   - [ ] [TaskID] [P?] [Story?] Description with file path
   ```
   - Phase 1: Setup (project initialization)
   - Phase 2: Foundational (blocking prerequisites)
   - Phase 3+: User Stories in priority order
   - Final Phase: Polish & Cross-Cutting Concerns
3. **Run consistency analysis** (`smith-analyze` logic):
   - Check spec ↔ plan ↔ tasks alignment
   - Check for missing coverage, contradictions
   - If CRITICAL issues found: fix them in-place (do not halt)
   - Log any issues found for the release notes

## Ledger-Informed Auto-Retry

If the build execution fails, check config for auto-retry:

1. Read `.smith/config.json` — check `ledger.auto_retry` and `ledger.max_retries`
2. If `auto_retry` is `false` (default) or config is missing, do NOT retry — fail normally
3. If `auto_retry` is `true`:
   a. Re-read `.smith/vault/ledger/antipatterns.md` to get the latest failure patterns
   b. Analyze the failure against known antipatterns to adjust the approach
   c. Retry the execution with the adjusted approach
   d. Repeat up to `max_retries` times (default: 2), re-reading antipatterns before each attempt
   e. If all retries exhausted, fail with a summary of all attempts
4. Each retry attempt is logged to the session log with attempt number and adjusted approach

Note: Auto-retry applies to the Phase 2 implementation loop. If a phase's subagent fails after 3 internal attempts AND auto-retry is enabled, the entire phase is retried with updated Ledger context.

## Phase 2: Implementation (Subagent per Phase)

Execute tasks phase-by-phase, each phase in its own subagent to manage context.

### Pre-implementation checks:

1. **Verify/create ignore files** based on plan.md tech stack:
   - `.gitignore`, `.dockerignore`, `.eslintignore`, `.prettierignore` as applicable
   - Only append missing patterns to existing files

2. **Parse tasks.md** to extract phases and their tasks.

### Execute each phase:

For each phase in tasks.md:

1. **Launch a subagent** with:
   - The phase's tasks (incomplete ones only)
   - Relevant context: plan.md tech stack, data-model.md, contracts/
   - File paths from task descriptions
   - Instructions to mark each task `[X]` in tasks.md upon completion

2. **Phase execution rules**:
   - Sequential tasks: execute in order
   - Parallel tasks [P]: can run together (but subagent decides based on file conflicts)
   - If a task fails: attempt fix up to 3 times, then log error and continue with remaining tasks
   - After each task completion, update tasks.md with `[X]` marker

3. **Phase completion check**:
   - Verify all tasks in the phase are marked `[X]`
   - If any failed permanently, log them for the summary
   - Proceed to next phase

### Implementation rules:
- Follow the plan.md architecture and file structure
- Respect data-model.md entity definitions
- Match contracts/ API specifications
- Use existing project patterns (read surrounding code before writing)
- Follow constitution.md principles
- **After any code changes to a Docker service**: run `docker compose up -d --build <service>` immediately

## Phase 3: Testing (Subagent)

Launch a testing subagent after all implementation is complete.

### 3.1 Unit Tests
- **If frontend code changed**: `cd services/command-center && pnpm test`
- **If Python service changed**: `cd services/<service> && poetry run pytest`
- Run existing test suites — do NOT skip tests

### 3.2 Playwright E2E Tests (MANDATORY for UI changes)
- **Check if any frontend files were modified** in this feature:
  - Files matching `services/command-center/src/components/**`
  - Files matching `services/command-center/src/pages/**`
  - Files matching `services/command-center/src/hooks/**`
  - Files matching `services/command-center/src/App.tsx`
- **If YES**:
  1. Run existing Playwright suite for regression: `cd services/command-center && pnpm exec playwright test`
  2. Write NEW Playwright tests for the changed/added UI flows
  3. Run the new tests
- **If NO frontend changes**: Skip Playwright

### 3.3 Test Failure Handling
- If tests fail: fix the code and re-run (up to 3 attempts per failure)
- If a test is flaky (passes on retry without code changes): note in release notes
- If tests cannot be fixed after 3 attempts: log the failure and continue
  - The release notes will flag this as requiring manual attention

## Phase 4: Spec Updates (Subagent)

Launch a subagent to update related system spec files.

1. **Identify modified files** from git diff against the configured base branch:
   ```bash
   BASE_BRANCH=$(.specify/scripts/bash/get-base-branch.sh)
   git diff "$BASE_BRANCH" --name-only
   ```

2. **Map modified files to system specs**:
   - `services/command-center/` → `specs/system-15-command-center/spec.md`
   - `services/email-pipeline/` → `specs/system-03-email-archive-contact-graph/spec.md`
   - `services/sentiment-engine/` → `specs/sentiment-engine/spec.md`
   - `services/communication-triage/` → `specs/system-05-communication-triage/spec.md`
   - `services/voice-training/` → `specs/system-04-personal-voice/spec.md`
   - `docker-compose.yml` → `specs/system-01-core-infrastructure/spec.md`
   - Other mappings as discovered from `specs/*/spec.md` content

3. **For each affected spec.md**:
   - Read the current spec
   - Add an "Implementation History" section (or append to existing)
   - Add a dated entry describing changes relevant to that system
   - Keep entries concise and factual

4. **Update STATUS.md** at project root with current progress.

### 4.5 System Spec Updates via `.specify/systems/`

After updating the legacy `specs/system-*/spec.md` files above, also update the canonical system specs in `.specify/systems/`:

1. **Read the feature spec frontmatter** — extract `primary_system` and `also_affects` fields. If the feature spec has no frontmatter (legacy spec in `specs/`), fall back to the file-path mapping in step 2 above.

2. **Update primary system spec** — Read `.specify/systems/<primary-system>/spec.md` and update any sections affected by the feature:
   - New API endpoints or modified routes
   - New or changed data models / database tables
   - Changed behavior or configuration
   - New dependencies or service interactions

3. **Update affected system specs** — For each system in `also_affects`, read its `.specify/systems/<system>/spec.md` and update relevant sections.

4. **Log updates to vault** — If `.smith/vault/.current-session` exists, append an entry to the session log noting which system specs were updated and what changed.

5. **Commit system spec updates** as part of the same feature branch before creating the PR.

If the build cannot determine what to update in a system spec (ambiguous changes), flag this in the vault session log for the user to review rather than making incorrect updates.

## Phase 5: Commit, Push & Merge

### 5.1 Commit
```bash
git add <all modified files — list explicitly, not git add -A>
git commit -m "<conventional commit message>"
```

- Use conventional commits format
- Reference the feature spec in the commit message
- Stage files explicitly (never `git add -A` or `git add .`)
- Do NOT stage `.env` files or credentials

### 5.2 Push
```bash
git push -u origin <branch-name>
```

### 5.3 Pre-PR File-Size Scan

Before composing the PR body, scan all files modified on this branch for
oversized source files. This is a non-blocking advisory — always proceed
with the PR.

```bash
# Enumerate files changed vs the configured base branch
BASE_BRANCH=$(.specify/scripts/bash/get-base-branch.sh)
git diff "$BASE_BRANCH" --name-only > /tmp/smith-build-changed.txt

# For each modified file that exists on disk, count lines
while IFS= read -r f; do
  [ -f "$f" ] || continue
  lines=$(wc -l < "$f" | tr -d ' ')
  if [ "$lines" -gt 300 ]; then
    printf -- "- \`%s\` — %s lines (exceeds 300)\n" "$f" "$lines"
  fi
done < /tmp/smith-build-changed.txt > /tmp/smith-build-oversized.txt
```

If `/tmp/smith-build-oversized.txt` is non-empty, include a **"File Size
Warnings"** section in the PR body (see Step 5.4 template). If empty, omit
the section entirely.

Source extensions in scope: `.py`, `.js`, `.jsx`, `.ts`, `.tsx`, `.css`,
`.html`, `.sh`. Exclude paths matching `vendor/`, `node_modules/`, `.venv/`,
`dist/`, `build/`, `.smith/`.

This is a FLAG, never a blocker. Always proceed with PR creation.

### 5.3.1 Pre-PR Description Coverage Scan

In addition to the file-size flag, scan the diff for methods that were
ADDED or EDITED in this PR but lack a `.meta` description. This is the
v2 description-coverage check from data-model.md §9. Like the file-size
flag, it is informational — the PR opens unconditionally.

```bash
# Reuse /tmp/smith-build-changed.txt from Step 5.3 above.
> /tmp/smith-build-coverage-misses.txt

while IFS= read -r f; do
  case "$f" in
    *.py|*.js|*.jsx|*.ts|*.tsx) ;;
    *) continue ;;
  esac
  [ -f "$f" ] || continue

  # Skip files inside excluded directories.
  case "$f" in
    vendor/*|*/vendor/*|node_modules/*|*/node_modules/*|.venv/*|*/.venv/*|dist/*|*/dist/*|build/*|*/build/*|.smith/*|*/.smith/*) continue ;;
  esac

  # Resolve parser path: prefer per-project override, then ~/.smith,
  # then repo-shipped parsers.
  case "$f" in
    *.py)
      for cand in .smith/scripts/parse-python.py "$HOME/.smith/scripts/parse-python.py" scripts/parsers/parse-python.py; do
        [ -f "$cand" ] && PARSER="python3 $cand" && break
      done ;;
    *)
      for cand in .smith/scripts/parse-js.js "$HOME/.smith/scripts/parse-js.js" scripts/parsers/parse-js.js; do
        [ -f "$cand" ] && PARSER="node $cand" && break
      done ;;
  esac
  [ -z "${PARSER:-}" ] && continue

  # Parse the file at HEAD (current branch). Capture the (id, name, scope)
  # triples plus class scope.
  CUR_JSON=$($PARSER "$f" 2>/dev/null || true)
  [ -z "$CUR_JSON" ] && continue

  # Build a list of HEAD method ids and their qualified names.
  python3 - "$f" "$CUR_JSON" >> /tmp/smith-build-coverage-misses.txt <<'PY' || true
import json, os, sys, subprocess, re

rel = sys.argv[1]
cur = json.loads(sys.argv[2])

# Collect (id, qualified_name) for HEAD.
head_methods = []
for fn in cur.get("functions") or []:
    fid = fn.get("id")
    name = fn.get("name", "")
    if fid:
        head_methods.append((fid, f"{rel}::{name}"))
for cls in cur.get("classes") or []:
    cname = cls.get("name", "")
    for m in cls.get("methods") or []:
        mid = m.get("id")
        mname = m.get("name", "")
        if mid:
            head_methods.append((mid, f"{rel}::{cname}::{mname}"))

# Compare against `git show main:<file>` parse to find added/changed ids.
try:
    main_src = subprocess.check_output(
        ["git", "show", f"main:{rel}"], stderr=subprocess.DEVNULL
    ).decode("utf-8", errors="replace")
except subprocess.CalledProcessError:
    main_src = None

prev_ids = set()
if main_src is not None:
    # Re-parse main:<file>. The stable method id incorporates the
    # project-relative module_path, so we MUST stage the bytes at the
    # same relative path inside a scratch directory and run the parser
    # with that directory as CWD. Otherwise the temp-file path leaks
    # into the id hash and every method looks "added".
    import tempfile, pathlib
    suffix = pathlib.Path(rel).suffix
    parser_cmd = os.environ.get("SMITH_PARSER_CMD", "")
    if not parser_cmd:
        if suffix == ".py":
            for cand in (".smith/scripts/parse-python.py",
                         os.path.expanduser("~/.smith/scripts/parse-python.py"),
                         "scripts/parsers/parse-python.py"):
                if os.path.isfile(cand):
                    parser_cmd = f"python3 {os.path.abspath(cand)}"
                    break
        else:
            for cand in (".smith/scripts/parse-js.js",
                         os.path.expanduser("~/.smith/scripts/parse-js.js"),
                         "scripts/parsers/parse-js.js"):
                if os.path.isfile(cand):
                    parser_cmd = f"node {os.path.abspath(cand)}"
                    break
    if parser_cmd:
        with tempfile.TemporaryDirectory() as scratch:
            staged = os.path.join(scratch, rel)
            os.makedirs(os.path.dirname(staged), exist_ok=True)
            with open(staged, "w", encoding="utf-8") as fh:
                fh.write(main_src)
            try:
                out = subprocess.check_output(
                    parser_cmd.split() + [rel],
                    stderr=subprocess.DEVNULL,
                    cwd=scratch,
                )
                prev = json.loads(out.decode("utf-8", errors="replace"))
                for fn in prev.get("functions") or []:
                    if fn.get("id"):
                        prev_ids.add(fn["id"])
                for cls in prev.get("classes") or []:
                    for m in cls.get("methods") or []:
                        if m.get("id"):
                            prev_ids.add(m["id"])
            except (subprocess.CalledProcessError, json.JSONDecodeError):
                pass

# Touched = HEAD ids not in main (added) OR signature changed (id differs).
touched = [(fid, qname) for (fid, qname) in head_methods if fid not in prev_ids]

# Load .meta description layer to check which touched ids have descriptions.
meta_path = os.path.join(".smith", "index", "files", rel + ".meta")
desc_ids = set()
if os.path.isfile(meta_path):
    in_funcs = False
    current_id = None
    with open(meta_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith("## Functions") or line.startswith("## Classes"):
                in_funcs = True
                current_id = None
                continue
            if line.startswith("## ") and in_funcs:
                in_funcs = False
                current_id = None
                continue
            if in_funcs:
                m = re.match(r"^\s*Id:\s+(\S+)", line)
                if m:
                    current_id = m.group(1)
                    continue
                m = re.match(r"^\s*Description:\s+(.+)$", line)
                if m and current_id:
                    if m.group(1).strip():
                        desc_ids.add(current_id)
                    current_id = None

for fid, qname in touched:
    if fid not in desc_ids:
        print(f"- {qname} (id: {fid})")
PY
done < /tmp/smith-build-changed.txt
```

If `/tmp/smith-build-coverage-misses.txt` is non-empty, include a
**"Description Coverage Warnings"** section in the PR body (see Step 5.4
template). If empty, omit the section entirely.

This is a FLAG, never a blocker. Always proceed with PR creation. If
`git diff "$BASE_BRANCH"` returns no files (clean tree, target branch ahead), the
section is a no-op. Per data-model.md §9.3.

### 5.4 Create PR & Merge
```bash
BASE_BRANCH=$(.specify/scripts/bash/get-base-branch.sh)
gh pr create --base "$BASE_BRANCH" --title "<short title>" --body "$(cat <<'EOF'
## Summary
<bullet points from release notes>

## Test plan
<from test results>

## File Size Warnings
<contents of /tmp/smith-build-oversized.txt if non-empty; otherwise omit this section>

The following files exceed the 300-line threshold and should be considered
for decomposition in follow-up work:

<oversized file list, e.g.:>
- `backend/src/api/v1/products.py` — 1,250 lines (exceeds 300)
- `services/billing/main.py` — 487 lines (exceeds 300)

## Description Coverage Warnings
<include this section only when /tmp/smith-build-coverage-misses.txt is non-empty>

<N> methods in this diff lack `.meta` descriptions:
<bullet list from /tmp/smith-build-coverage-misses.txt, e.g.:>
- backend/src/services/webhook.py::WebhookRetryHandler::backoff (id: 4b8d6e2a9f1c0e7d)
- backend/src/services/webhook.py::WebhookRetryHandler::dead_letter (id: a3f0c8d2e7b14955)
- frontend/src/lib/api/products.ts::fetchProductBundle (id: 9c1d4e0a8f2b5c63)

Run `/smith-index --describe --system <name>` to backfill before merge,
or rely on the next `/smith-bugfix`/`/smith-new` workflow to update
descriptions for touched methods in-context.

## Release notes
See specs/<feature>/release.md

Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Then merge the PR. **IMPORTANT**: Always run `gh pr merge` from the **primary repo directory**, not from a worktree. Running from a worktree causes "fatal: 'main' is already checked out" errors.
```bash
# If in worktree mode:
cd <PRIMARY_REPO> && gh pr merge <pr-number> --squash --delete-branch
# If in normal mode:
gh pr merge <pr-number> --squash --delete-branch
```

### 5.5 Return to the base branch

**Normal mode:**
```bash
BASE_BRANCH=$(.specify/scripts/bash/get-base-branch.sh)
git checkout "$BASE_BRANCH"
git pull origin "$BASE_BRANCH"
```

**Worktree mode:** Do NOT run `git checkout "$BASE_BRANCH"` — the base branch is already checked out in the primary repo. Instead, proceed directly to Phase 6. The worktree cleanup in Phase 7 handles branch deletion.

## Phase 6: Service Rebuild

After merging to the base branch:

1. **Identify affected services** from the changed files
2. **Docker-touching detection** (worktree mode only):
   - Check if changes include `docker-compose.yml`, `Dockerfile`, or service build contexts
   - If Docker-touching: display warning:
     > "This feature modifies Docker configuration. Worktree isolates git only — Docker operations will affect running containers."
   - Proceed with Docker operations after warning.
3. **Rebuild each affected service** — always run from the **primary repo directory** (not the worktree), since Docker Compose resolves paths relative to the compose file and Colima cannot mount `/tmp`:
   ```bash
   # If in worktree mode: pull changes to primary repo first
   cd <PRIMARY_REPO> && git pull origin "$(.specify/scripts/bash/get-base-branch.sh)"
   docker compose up -d --build <service-name>
   ```
   ```bash
   # Normal mode:
   docker compose up -d --build <service-name>
   ```
4. **Copy `.env`**: If in worktree mode and Docker operations are needed, ensure `.env` exists in the primary repo (it always should — this is a safety check).
5. **Run health check**:
   ```bash
   bash scripts/health-check.sh
   ```
6. If any service is unhealthy: attempt restart, log issue

## Phase 7: Release Notes & Summary

### 7.1 Generate Release Notes

Write `specs/<feature>/release.md`:

```markdown
# Release: [Feature Name]

**Date**: [YYYY-MM-DD]
**Branch**: [branch-name]
**PR**: [#number](link)
**Spec**: [spec.md](spec.md)

## Summary

[2-3 sentence description of what was built]

## Changes

### Files Created
| File | Purpose |
|------|---------|
| path/to/file.tsx | Description |

### Files Modified
| File | Change |
|------|--------|
| path/to/file.tsx | What changed |

### System Specs Updated
| Spec | Changes Recorded |
|------|-----------------|
| system-15-command-center/spec.md | Description |

## Testing

### Unit Tests
- [PASS/FAIL] pnpm test — X tests passed
- [PASS/FAIL] poetry run pytest — X tests passed

### E2E Tests (if applicable)
- [PASS/FAIL] Existing Playwright suite — X tests passed
- [PASS/FAIL] New Playwright tests — X tests for [flows tested]

### Known Issues
- [Any test failures that couldn't be resolved]

## Deviations from Spec

[Any differences between what was spec'd and what was implemented, with reasoning]

## Infrastructure

- Docker services rebuilt: [list]
- Health check: [PASS/FAIL]
```

### 7.2 Commit Release Notes
```bash
git add specs/<feature>/release.md
git commit -m "docs: add release notes for <feature>"
git push origin main
```

### 7.3 Worktree Cleanup (if applicable)

If `WORKTREE_MODE=true`:
1. **On success**: Remove the worktree from the **primary repo directory**:
   ```bash
   cd <PRIMARY_REPO> && git worktree remove <WORKTREE_PATH>
   ```
2. **On failure**: Preserve the worktree for debugging. Log the worktree path to the vault session log:
   > "Worktree preserved at <WORKTREE_PATH> for debugging. Clean up with: `git worktree remove <WORKTREE_PATH>`"

### 7.4 Clear Workflow Tracking

Remove the active-workflow file to signal the workflow is complete. Use the shipped helper, which coexists with a broad `Bash(rm:*)` deny rule:
```bash
.specify/scripts/bash/clear-active-workflow.sh "$BRANCH"
```

### 7.4.1 Post-Workflow Reflection

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

### 7.5 Display Summary

Output to the user:
- Feature name
- PR link
- Release notes summary (inline, not just a file link)
- Any issues requiring manual attention
- Link to full release notes file
- Confirmation that we're back on `main` with services healthy

## Recovery Mode

If `/smith-build` is run manually (not from `/smith-new`):

1. Detect current state by checking:
   - Which branch we're on
   - Whether tasks.md exists and has incomplete tasks
   - Whether code changes exist but aren't committed
   - Whether a PR exists but isn't merged

2. Resume from the appropriate phase:
   - No tasks.md → start from Phase 1
   - Tasks partially complete → resume Phase 2 from first incomplete task
   - All tasks complete, uncommitted → start from Phase 5
   - PR exists, not merged → start from Phase 5.4
   - PR merged, services not rebuilt → start from Phase 6
   - Everything done → just generate release notes (Phase 7)

## Key Rules

- ALL phases run without user interaction
- Use subagents for each major phase to manage context
- If a subagent fails, retry once before logging the error and continuing
- Always rebuild Docker after code changes — never skip this
- Never use `git add -A` or `git add .` — always stage specific files
- Never commit `.env` files or credentials
- Playwright tests are MANDATORY when frontend files are modified
- The release.md file is the permanent record of what was built
