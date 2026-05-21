---
feature: 19-manifest-system
branch: 19-manifest-system
purpose: Pre-push manual validation instructions
audience: Dennis (you)
---

# Manual Testing Instructions

The build is complete on branch `19-manifest-system` (local-only, NOT pushed). Before pushing the branch and triggering the public deploy, validate the manifest system end-to-end on real Smith-using projects on this machine.

## Test Targets

You have at least two existing Smith-installed projects to test against:
- `/Users/dennisplucinik/Projects/armory`
- `/Users/dennisplucinik/Projects/goldcanna-inventory`

Test on **one project first** (recommend goldcanna-inventory since it's smaller — faster iteration). Then re-run on the second to confirm.

## Pre-Test Setup (one-time)

The build is in a worktree at `/tmp/smith-manifest-system/`. The parsers, hooks, and skills need to be installed from there to your global `~/.claude/` and `~/.smith/` locations to be active.

### Step 1: Snapshot your current settings

```bash
# Back up your settings before the install modifies them
cp ~/.claude/settings.json ~/.claude/settings.json.pre-manifest-system
ls -la ~/.claude/settings.json*
# Should show the original + the backup
```

### Step 2: Install the parsers globally

```bash
cd /tmp/smith-manifest-system
./scripts/install-parsers.sh --dry-run    # verify what would be installed
./scripts/install-parsers.sh              # actually install
ls -la ~/.smith/scripts/
# Expected: parse-python.py, parse-js.js, path-resolver.py, parser-lib.sh, vendor/acorn.min.js
```

### Step 3: Install the hooks globally

```bash
cd /tmp/smith-manifest-system
./scripts/install-hooks.sh                # registers in ~/.claude/settings.json
cat ~/.claude/settings.json | python3 -m json.tool | grep -E "manifest-updater|context-loader" -A 2
# Expected: both hooks registered. manifest-updater LAST in PostToolUse Write|Edit chain.
```

### Step 4: Verify the hooks fire

In a SCRATCH directory (NOT a real project yet):

```bash
mkdir -p /tmp/manifest-smoke && cd /tmp/manifest-smoke
git init -q
mkdir -p .smith/index .smith/vault
echo "print('hello')" > test.py
# Now manually trigger the hook to verify it works:
echo '{"tool": "Write", "tool_input": {"file_path": "'$(pwd)'/test.py"}}' | bash /tmp/smith-manifest-system/hooks/manifest-updater.sh
ls -la .smith/index/files/test.py.meta
# Expected: .meta file exists with parsed content
cat .smith/index/files/test.py.meta
# Expected: markdown with hash, lines, functions sections
```

## Phase 1: Validation on goldcanna-inventory (or armory)

### Step 1.1: Bootstrap the manifest

```bash
cd ~/Projects/goldcanna-inventory
# Install the per-project git hooks (optional but recommended)
/tmp/smith-manifest-system/scripts/install-git-hooks.sh

# Run the full index
bash /tmp/smith-manifest-system/scripts/smith-index/run.sh
# Expected output:
# - "Phase 1: Discovering source files"
# - "Phase 2: Parsing N files"
# - "Phase 3: Writing system manifests"
# - Summary: total files, files per system, files >300 lines, total time

ls -la .smith/index/
# Expected: manifest.md, systems/, files/, config/ (with system-paths.json IF you ran --init-system-paths)

cat .smith/index/manifest.md
# Expected: ≤50 lines. Systems table, stats block, last-index timestamp.

ls .smith/index/systems/
# Expected: one .md per system

ls -R .smith/index/files/ | head -30
# Expected: mirror of project source tree, .meta files
```

### Step 1.2: Verify a single .meta file

Pick a non-trivial source file (a substantial Python or TS/JSX file in the project) and inspect its .meta:

```bash
# Find a likely candidate
find . -name "*.py" -not -path "./node_modules/*" -not -path "./.venv/*" -size +5k | head -3
# Pick one, say: backend/src/api/orders.py
cat .smith/index/files/backend/src/api/orders.py.meta
# Expected fields: System, Lines, Updated, Hash, Functions table, Classes table, Imports, Routes
# If file >300 lines: should have "⚠️ Exceeds 300-line threshold" marker
```

### Step 1.3: Test manual /smith-navigate

In a Claude Code session in this project, ask:

```
/smith-navigate "where is the order creation endpoint?"
```

**Expected:** Returns a categorized list:
- **Must Read**: 1-3 files relevant to order creation, each with `[primary: <line-range>, <label>]` annotation
- **Should Read**: 1-3 supporting files (schemas, services)
- **Reference Only**: tests, related contracts
- **Systems Affected**: list of systems

**Validate:**
- ✅ The files returned actually exist
- ✅ The "primary" line ranges roughly match where the endpoint is defined
- ✅ The system labels look reasonable (heuristic-derived or matching your `system-paths.json` overrides)
- ⚠️ If anything looks wildly wrong, this is a real bug — copy the output verbatim and abort

### Step 1.4: Test --check (hash-based staleness)

```bash
bash /tmp/smith-manifest-system/scripts/smith-index/run.sh --check
# Expected: "all fresh" or similar — no stale files
```

Now modify a source file (real edit, not just touch):

```bash
echo "" >> backend/src/api/orders.py  # add a blank line
bash /tmp/smith-manifest-system/scripts/smith-index/run.sh --check
# Expected: reports backend/src/api/orders.py as stale (because hash mismatch)
```

Revert the change to leave the project clean:

```bash
git checkout backend/src/api/orders.py
bash /tmp/smith-manifest-system/scripts/smith-index/run.sh --check
# Expected: "all fresh" again
```

### Step 1.5: Test the context-loader hook (the trickiest one)

Open a Claude Code session in this project. Start with a regular conversational message:

```
What's 2 + 2?
```

**Expected:** Normal answer. No "Smith Context Injection" block. Check `~/.smith/logs/hooks.log` — the entry should show `skill=none, action=skip`.

Now try a Smith-skill message:

```
/smith-new add a new feature for order analytics
```

(or any Smith natural-language trigger from your CLAUDE.md)

**Expected:**
- Claude's response should reference files from your project that are actually relevant
- The injection should be visible in the hooks.log: `skill=smith-new, vault=loaded, manifest=loaded, injected=N chars`
- Claude should NOT manually go grepping for relevant files — the manifest already gave it the list

### Step 1.6: Test the manifest-updater hook fires on Write/Edit

In the same Claude Code session, ask Claude to make a small edit to a source file:

```
edit src/utils/format.ts to add a comment at the top saying "// updated 2026-05-21"
```

**Expected after the edit:**
- `~/.smith/logs/hooks.log` should have a `manifest-updater` entry for `src/utils/format.ts`
- `.smith/index/files/src/utils/format.ts.meta` should have an updated `Updated:` timestamp
- The `lines` field in the .meta should reflect the new file size (one more line than before)
- If the file is now >300 lines, you should see `⚠️ Exceeds 300-line threshold` in the .meta

Verify:

```bash
tail -5 ~/.smith/logs/hooks.log
# Look for: [manifest-updater ...] processed: src/utils/format.ts
cat .smith/index/files/src/utils/format.ts.meta | grep -E "Updated|Lines"
```

### Step 1.7: Test the soft warning (delete the manifest, then trigger a Smith skill)

```bash
mv .smith/index .smith/index.backup-for-test
```

In a fresh Claude Code session, invoke a Smith skill:

```
/smith-help
```

**Expected:**
- The injection includes a note: *"Manifest not initialized — run `/smith-index` to enable structured context retrieval. Proceeding with vault context only."*
- The skill still works (vault-only context)
- `~/.smith/logs/hooks.log` shows `warned_manifest_missing=true`
- A marker file appears: `.smith/vault/.warned-manifest-missing-<session-id>`

In the SAME session, invoke another Smith skill:

```
/smith-vault
```

**Expected:**
- The soft warning does NOT appear again (once-per-session — Q10)

Restore the manifest:

```bash
rm -rf .smith/index
mv .smith/index.backup-for-test .smith/index
```

### Step 1.8: Test the git hook (post-merge / post-checkout)

```bash
# Make sure the git hooks are installed
ls -la .git/hooks/post-merge .git/hooks/post-checkout

# Switch to a different branch (any existing branch you have locally)
git checkout main   # or whichever branch you're not on
# Watch for hook output:
# Expected: "[smith git-hook] running /smith-index --incremental for branch switch"
# Then: the manifest catches up to the new branch's state in the background
```

If you don't have multiple branches checked out locally:

```bash
# Make a no-op commit + pull-from-origin to trigger post-merge
git pull origin main
# Same expected behavior
```

## Phase 2: Repeat on the Second Project

Run the same Steps 1.1 through 1.8 on the OTHER project (armory if you started with goldcanna; goldcanna otherwise).

If both projects pass, you have high confidence in the implementation.

## Phase 3: Performance Spot-Check

In the larger of the two projects (presumably armory):

```bash
cd ~/Projects/armory
# Time a full rebuild:
time bash /tmp/smith-manifest-system/scripts/smith-index/run.sh
# Expected: well under 60 seconds for a ~400-file project

# Inspect the manifest sizes:
wc -l .smith/index/manifest.md
# Expected: ≤50

wc -l .smith/index/systems/*.md
# Expected: all ≤80
```

If anything exceeds the budget by more than 2x, dig in before pushing.

## Phase 4: Rollback Test (just in case)

Verify you can cleanly undo the install:

```bash
/tmp/smith-manifest-system/scripts/install-parsers.sh --uninstall
/tmp/smith-manifest-system/scripts/install-hooks.sh --uninstall   # if this flag exists; otherwise restore the .pre-manifest-system backup
cp ~/.claude/settings.json.pre-manifest-system ~/.claude/settings.json
ls ~/.smith/scripts/
# Expected: parsers gone
cat ~/.claude/settings.json | grep -E "manifest-updater|context-loader"
# Expected: no matches
```

Then re-install for actual use:

```bash
/tmp/smith-manifest-system/scripts/install-parsers.sh
/tmp/smith-manifest-system/scripts/install-hooks.sh
```

## Phase 5: Sign-Off Checklist

Before pushing the branch, confirm all of these:

- [ ] Parsers installed at `~/.smith/scripts/`
- [ ] Hooks registered in `~/.claude/settings.json` with `manifest-updater.sh` LAST in PostToolUse Write|Edit chain
- [ ] `~/.smith/logs/hooks.log` populated with sensible entries from real usage
- [ ] Full `/smith-index` rebuild succeeds on goldcanna-inventory
- [ ] Full `/smith-index` rebuild succeeds on armory
- [ ] Top-level `manifest.md` ≤50 lines for both projects
- [ ] Per-system manifests ≤80 lines for both projects
- [ ] `/smith-navigate` returns reasonable file lists on both projects
- [ ] `--check` correctly flags modified files
- [ ] `manifest-updater.sh` fires on Claude-driven Write/Edit (verified via hooks.log + .meta timestamps)
- [ ] `context-loader.sh` injects appropriate context for Smith skills and skips for regular conversation
- [ ] Soft warning fires once-per-session when manifest is missing
- [ ] Performance: `/smith-index` <60s on the largest project; hook latency <500ms in casual feel
- [ ] No errors in stderr during real Claude Code usage
- [ ] Rollback works (parsers/hooks can be uninstalled cleanly)

If everything checks out, you're ready to:

```bash
cd /tmp/smith-manifest-system
git push -u origin 19-manifest-system
gh pr create --title "feat: manifest system and structured context retrieval" --body-file specs/19-manifest-system/release.md
# After review:
gh pr merge --squash --delete-branch
# GitHub deploy action fires; smith-repo public distribution updated
```

## If Something Goes Wrong

The branch is local-only in the worktree at `/tmp/smith-manifest-system`. You can:
- Make fixes directly in the worktree (`cd /tmp/smith-manifest-system && <edits>`)
- Commit additional fixes to the same branch
- Re-test
- Push only when satisfied

If you want to abandon entirely:

```bash
# Restore original settings
cp ~/.claude/settings.json.pre-manifest-system ~/.claude/settings.json
# Uninstall parsers
/tmp/smith-manifest-system/scripts/install-parsers.sh --uninstall
# Remove the worktree
cd /Users/dennisplucinik/Projects/smith-repo
git worktree remove /tmp/smith-manifest-system --force
git branch -D 19-manifest-system
# Clean up active-workflow marker
.specify/scripts/bash/clear-active-workflow.sh "19-manifest-system" 2>/dev/null || rm -f .smith/vault/active-workflows/19-manifest-system.yaml
```

## Quick Reference

| Command | Purpose |
|---------|---------|
| `bash /tmp/smith-manifest-system/scripts/smith-index/run.sh` | Full manifest rebuild for current project |
| `... --check` | Hash-only staleness check |
| `... --incremental` | Catch up changed files only (since HEAD~) |
| `... --migrate-templates` | Append new template sections to project's constitution.md / CLAUDE.md |
| `... --init-system-paths` | Generate a `system-paths.json` stub from heuristics |
| `tail -f ~/.smith/logs/hooks.log` | Watch hook activity in real time |
| `tail -f ~/.smith/logs/smith-index-*.jsonl` | Watch index progress in real time |
