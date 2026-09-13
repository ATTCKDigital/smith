---
name: smith-sync
description: Sweep team-shareable .smith/ artifacts (manifest, .meta describe layer, ledger, bank, agents, sessions) AND debug reports (.specify/systems/*/debug/, .specify/debug/) into a single chore commit and push directly to the default branch. Runs automatically at the end of smith-new / smith-bugfix / smith-debug, and can be run manually anytime. No-ops when nothing committable has accumulated.
---

# Smith — Sync Vault, Index & Debug-Report Artifacts

## Skill Purpose

Smith workflows stage only the files they explicitly touch (every workflow
enforces "never `git add -A`"). So the team-shareable `.smith/` artifacts made
committable by the gitignore policy — `index/manifest.md`, the
`index/files/` + `index/systems/` `.meta` describe layer, `vault/ledger/`,
`vault/bank/`, `vault/agents/`, `vault/sessions/*.md` — accumulate **unstaged in
the primary repo** and never reach teammates. The same is true of the debug
reports `/smith-debug` writes to `.specify/systems/<system>/debug/` (or
`.specify/debug/` in un-systematized projects): the debug workflow is read-only
and never commits, so its reports would otherwise sit untracked forever.

`/smith-sync` closes that loop: it sweeps the committable `.smith/` artifacts
and any debug reports into one `chore` commit and pushes it directly to the
default branch, giving the repo owner full, reliable transparency into activity
without anyone needing to remember a manual command.

This skill operates in the **primary repo on the default branch** — NOT a
worktree. The artifacts live in the primary repo's `.smith/` (vault logging,
index rebuilds, reflection writes), outside the `/tmp` worktree a workflow's PR
is built from. That is why the sync runs as a terminal step *after* worktree
cleanup, and why it cannot be part of a worktree's PR.

## When This Runs

- **Automatically** as the final step of `/smith-new`, `/smith-bugfix`, and
  `/smith-debug` (chained in those skills).
- **Manually** anytime via `/smith-sync`. It is idempotent and safe to re-run.

## How It Works

`git add .smith/` relies on `.gitignore` as the filter: git natively skips the
ignored paths (`.current-session*`, `queue/`, `todo/`, `active-workflows/`,
`timesheets/`, checkpoints, `config/`) and stages only the committable ones.
There is **no sentinel-block parsing** — the gitignore policy is the single
source of truth, so when the policy changes (via `/smith-update`) the sweep
automatically follows.

The sweep has a second, narrowly-scoped staging surface: the debug-report
directories `.specify/systems/*/debug/` and `.specify/debug/`. These are the
only `.specify/` paths ever staged — feature specs, plans, and other `.specify/`
content remain the responsibility of the workflows that author them.

## Procedure

Run all steps from the **primary repo root**.

### 1. Guard — `.smith/` exists

```bash
if [ ! -d .smith ]; then
    echo "/smith-sync: no .smith/ directory — nothing to sync."
    exit 0
fi
```

### 2. Resolve the default branch and confirm we're on it

Per Q2-A, never switch the user's checkout. If not on the default branch, skip
with a clear report.

```bash
BASE_BRANCH=$(.specify/scripts/bash/get-base-branch.sh 2>/dev/null || echo main)
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
if [ "$CURRENT_BRANCH" != "$BASE_BRANCH" ]; then
    echo "/smith-sync: on '$CURRENT_BRANCH', not the default branch '$BASE_BRANCH' — skipping."
    echo "  (Re-run /smith-sync once you are on '$BASE_BRANCH'; nothing was changed.)"
    exit 0
fi
```

### 3. Stage `.smith/` and the debug-report directories — nothing else

```bash
git add .smith/
[ -d .specify/debug ] && git add .specify/debug
[ -d .specify/systems ] && find .specify/systems -mindepth 2 -maxdepth 2 -type d -name debug -exec git add {} +
```

The existence checks and glob-free `find` keep this a clean no-op in projects
with no debug reports, in both bash and zsh (a bare `.specify/systems/*/debug`
glob would abort zsh with "no matches found" when the directories don't exist).

NEVER `git add -A` or `git add .` — staging is scoped to `.smith/` plus the
debug-report directories so unrelated dirty work is never swept in.

### 4. Nothing-staged guard — nothing staged means nothing to sync

Covers repos where neither surface stages anything (e.g. `.gitignore` ignores
`.smith/` wholesale and no debug reports exist): we no-op.

```bash
if git diff --cached --quiet; then
    echo "/smith-sync: nothing to sync (no committable .smith/ or debug-report changes)."
    exit 0
fi
```

### 5. Staging-discipline assertion — staged set ⊆ `.smith/` ∪ debug reports

Defense against a misconfigured `.gitignore` letting something unexpected in.
If anything outside `.smith/` or the debug-report directories is staged, ABORT
(unstage) rather than commit.

```bash
OUTSIDE=$(git diff --cached --name-only | grep -Ev '^\.smith/|^\.specify/(systems/[^/]+/)?debug/' || true)
if [ -n "$OUTSIDE" ]; then
    echo "/smith-sync: ABORT — staged paths outside .smith/ and debug-report dirs detected:"
    printf '  %s\n' $OUTSIDE
    git reset -- $OUTSIDE >/dev/null 2>&1 || true
    echo "  Unstaged the offending paths. Investigate the project's .gitignore; nothing committed."
    exit 1
fi
```

### 6. Build a count summary for the commit body

```bash
N_SESSIONS=$(git diff --cached --name-only -- '.smith/vault/sessions/' | wc -l | tr -d ' ')
N_META=$(git diff --cached --name-only -- '.smith/index/files/' | grep -c '\.meta$' || true)
N_LEDGER=$(git diff --cached --name-only -- '.smith/vault/ledger/' | wc -l | tr -d ' ')
N_BANK=$(git diff --cached --name-only -- '.smith/vault/bank/' | wc -l | tr -d ' ')
N_AGENTS=$(git diff --cached --name-only -- '.smith/vault/agents/' | wc -l | tr -d ' ')
N_DEBUG=$(git diff --cached --name-only | grep -Ec '^\.specify/(systems/[^/]+/)?debug/' || true)
N_TOTAL=$(git diff --cached --name-only | wc -l | tr -d ' ')
```

### 7. Commit — `chore` with `[skip ci]`

The `[skip ci]` token is REQUIRED so artifact-only syncs don't trigger GitHub
Actions / deploys.

```bash
git commit -m "chore(smith): sync vault & index artifacts [skip ci]

Sweep team-shareable .smith/ artifacts and debug reports to the default branch
so teammates receive accumulated index + vault context. Artifact-only; no
source changes.

Files: ${N_TOTAL} total — ${N_SESSIONS} sessions, ${N_META} .meta,
${N_LEDGER} ledger, ${N_BANK} bank, ${N_AGENTS} agents, ${N_DEBUG} debug reports."
```

### 8. Push — direct to the default branch, NO PR

```bash
if git push origin "$BASE_BRANCH"; then
    echo "/smith-sync: pushed ${N_TOTAL} artifact files (${N_DEBUG} debug reports) to origin/${BASE_BRANCH}."
else
    echo "/smith-sync: PUSH FAILED (non-fast-forward, branch protection, or remote moved ahead)."
    echo "  The sync commit is kept locally on '$BASE_BRANCH'. NOT force-pushing."
    echo "  Resolve manually: git pull --rebase origin $BASE_BRANCH && git push origin $BASE_BRANCH"
    exit 1
fi
```

Per the decision, **never force-push**. On failure the local commit is kept and
the user resolves manually.

## Key Rules

- Runs in the **primary repo on the default branch** — never a worktree, never
  switches the user's branch.
- Only ever `git add .smith/` plus the debug-report directories
  (`.specify/systems/*/debug/`, `.specify/debug/`) — never `git add -A` /
  `git add .`. No other `.specify/` path is ever staged.
- `[skip ci]` is mandatory in the commit message.
- Never force-push. Push failure → keep local commit, report, exit non-zero.
- No PR — direct push (a PR that sits un-merged defeats the transparency goal).
- No-op cleanly when there is nothing committable to sync (dev repo / no changes).
- Idempotent — safe to run repeatedly and standalone.
- **Markerless-safe snippets**: this skill runs AFTER workflows clear their
  active-workflow marker (and standalone with no marker at all), so every
  bash snippet above must use only stderr-only (`2>`, `2>>`) and `/dev/null`
  redirections — the workflow-gate denies any other redirection when no
  marker exists. Keep it that way when editing this file.
