# Smith — Session Finish

## Skill Purpose
End-of-session workflow that ensures all work is committed, pushed, merged to main, specs are updated, and the workspace is clean. Prevents losing work when closing a development session.

## When to Use
- User is done working and wants to wrap up
- User wants to ensure nothing is lost before ending a session
- Triggered by `/smith-finish`

## How to Execute

Run all steps autonomously. Only stop to ask the user if a decision is genuinely ambiguous (e.g., unrelated uncommitted changes that may need separate branches).

---

### Step 1: Inventory — Assess Current State

Gather all of the following in parallel:

```bash
# What branch are we on?
git rev-parse --abbrev-ref HEAD

# Any uncommitted changes?
git status

# Any unpushed commits? (only if on a branch other than main)
git log origin/$(git rev-parse --abbrev-ref HEAD)..HEAD --oneline 2>/dev/null

# What files changed vs main?
git diff main --name-only 2>/dev/null

# Any open PRs for this branch?
gh pr list --head $(git rev-parse --abbrev-ref HEAD) --state open --json number,title,url 2>/dev/null
```

Present a brief status summary to the user:
```
Session Status:
- Branch: <branch-name>
- Uncommitted changes: <count> files
- Unpushed commits: <count>
- Open PRs: <count>
- Files changed vs main: <count>
```

**Decision tree based on state:**

| State | Action |
|-------|--------|
| On `main`, no changes | Nothing to do. Report "workspace is clean" and exit. |
| On `main`, uncommitted changes | Create a feature branch (`fix/<slug>` or `feat/<slug>` based on changes), then continue to Step 2. Ask the user for a brief description to name the branch. |
| On feature branch, uncommitted changes | Continue to Step 2. |
| On feature branch, all committed + pushed + PR merged | Skip to Step 6 (verify clean state). |
| On feature branch, all committed + pushed + PR open | Skip to Step 4 (spec updates, then merge). |
| On feature branch, all committed + not pushed | Skip to Step 3 (push). |

---

### Step 2: Commit

```bash
# Show what will be committed
git diff --stat
git diff --cached --stat
```

- Stage changed files **explicitly by name** (never `git add -A` or `git add .`)
- Exclude `.env`, credentials, secrets, and large binary files
- If there are untracked files, check if they should be included (new source files: yes, temp files: no)

Write a conventional commit message:
```bash
git commit -m "$(cat <<'EOF'
<type>: <concise description>

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

If there are changes across unrelated areas that clearly belong to different features, ask the user:
> "I see changes to both [area A] and [area B]. Should I bundle these into one commit, or split them?"

---

### Step 3: Push

```bash
git push -u origin <branch-name>
```

---

### Step 4: Spec Updates

Before creating/merging the PR, update documentation:

1. **Identify changed files** relative to main:
   ```bash
   git diff main --name-only
   ```

2. **Map files to system specs** using these rules:
   - `services/command-center/` -> `specs/system-15-command-center/spec.md`
   - `services/email-pipeline/` -> `specs/system-03-email-archive-contact-graph/spec.md`
   - `services/sentiment-engine/` -> `specs/sentiment-engine/spec.md`
   - `services/communication-triage/` -> `specs/system-05-communication-triage/spec.md`
   - `services/content-strategy/` -> `specs/system-12-content-social-engine/spec.md`
   - `services/meeting-intelligence/` -> `specs/system-09-meeting-intelligence/spec.md`
   - `services/trend-intelligence/` -> `specs/system-13-trend-intelligence/spec.md`
   - `services/social-listening/` -> `specs/system-10-social-listening/spec.md`
   - `docker-compose.yml` -> `specs/system-01-core-infrastructure/spec.md`
   - `db/` -> relevant system spec based on table names

3. **For each affected spec.md**: Read it, then append a dated implementation history entry describing what changed and why. Keep it concise and factual.

4. **Update CHANGELOG.md** with a dated entry including:
   - The original prompt/intent
   - Files created and modified
   - Before/after details sufficient to revert

5. **Update STATUS.md** if system progress percentages changed.

6. **Commit spec updates** on the same branch:
   ```bash
   git add <spec files> CHANGELOG.md STATUS.md
   git commit -m "docs: update specs and changelog for <feature/fix description>

   Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
   git push
   ```

**Skip conditions:**
- If only spec/doc files changed (no code), skip spec updates
- If changes are trivial (typo fixes, comment changes), skip spec updates

---

### Step 5: PR & Merge

**If no open PR exists**, create one:
```bash
gh pr create --title "<type>: <short title>" --body "$(cat <<'EOF'
## Summary
<bullet points of changes>

## Test plan
<what was tested or needs testing>

Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

**Merge the PR:**
```bash
gh pr merge <pr-number> --squash --delete-branch
```

**Return to main:**
```bash
git checkout main
git pull origin main
```

---

### Step 6: Verify Clean State

Run these checks and report results:

```bash
# On main?
git rev-parse --abbrev-ref HEAD

# Clean working tree?
git status --porcelain

# Any stale local branches?
git branch --merged main | grep -v main

# Up to date with remote?
git log origin/main..HEAD --oneline
```

**If Docker services were affected** (code changes to any service directory):
```bash
docker compose up -d --build <affected-services>
```

Wait for healthy status, then report.

---

### Step 7: Final Report

Output a summary:

```
Session Complete:
- Committed: <commit hash> — <message>
- PR: #<number> (merged)
- Specs updated: <list of spec files>
- Services rebuilt: <list> (or "none needed")
- Branch: main (clean)
```

If there were any issues (failed merges, unhealthy services, skipped steps), flag them clearly:
```
Requires attention:
- <issue description>
```

---

## Edge Cases

### Multiple feature branches with uncommitted work
If the user has been switching branches and has stashed changes:
```bash
git stash list
```
Alert the user if stashes exist — they may contain work from this session.

### Merge conflicts
If `gh pr merge` fails due to conflicts:
1. Report the conflict to the user
2. Do NOT force merge or auto-resolve
3. Suggest: "There are merge conflicts. Want me to resolve them, or would you prefer to handle it?"

### Nothing to do
If the workspace is already clean (on main, no changes, no open PRs):
```
Workspace is clean. Nothing to commit, push, or merge.
```
