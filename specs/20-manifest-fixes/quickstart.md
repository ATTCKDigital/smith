---
feature: 20-manifest-fixes
artifact: quickstart
created: 2026-06-02
---

# Quickstart — Manifest System v2

Three integration scenarios that exercise the v2 changes end-to-end. Each scenario starts from a recognizable state, runs the v2 commands, and verifies the resulting `.smith/index/` and `.specify/systems/` artifacts.

---

## Scenario A — Existing Project Migration (armory)

**Starting state:** armory has eighteen hand-authored `.specify/systems/system-<NN>-<name>/spec.md` files. None have YAML frontmatter. A previous `/smith-index` run produced eight heuristic-derived buckets in `.smith/index/systems/` that do not match the eighteen declared systems. `.meta` files exist but lack descriptions.

**Goal:** Bring system membership into agreement with the declarations and populate the description layer.

### Step 1 — Migrate System Specs to `paths:` Frontmatter

```bash
/smith-migrate-system-paths
```

The skill walks `.specify/systems/system-<NN>-<name>/spec.md` files. For each, it scans the prose body for path hints (literal occurrences of `services/X/`, `backend/X/`, `frontend/X/`, code-fence file references, `**Files:**` bullet lists) and proposes a `paths:` block.

For each system, the operator sees:

```
system-04-webhooks
  Prose mentions: backend/webhooks/, services/webhook_dispatcher/
  Proposed paths:
    - backend/webhooks/
    - services/webhook_dispatcher/
  [a]ccept / [e]dit / [s]kip ?
```

Accepted entries are written as YAML frontmatter at the TOP of each system's `spec.md`. The existing prose body is preserved verbatim below the frontmatter. Already-migrated files (with a `paths:` field present) are skipped — the skill is idempotent.

**Verify after step 1:**

```bash
head -10 .specify/systems/system-04-webhooks/spec.md
```

Expected output (illustrative):

```yaml
---
system: system-04-webhooks
status: active
paths:
  - backend/webhooks/
  - services/webhook_dispatcher/
---

# system-04-webhooks

(original prose body unchanged below this point)
```

The skill prints a summary: systems migrated, systems skipped, total prefixes accepted vs proposed.

### Step 2 — Rebuild the Manifest (Structural Only)

```bash
/smith-index
```

The structural pass runs at v1 speed (<60s for 400 files). The path resolver now consults `paths:` frontmatter first (tier 1), so files under `backend/webhooks/` map to `system-04-webhooks` instead of the heuristic's `system-backend` bucket.

**Verify after step 2:**

```bash
ls .smith/index/systems/ | wc -l
```

Expected: 18 (or 18 plus an `unassigned.md` for files not covered by any system's `paths:`). NOT 8.

```bash
head -20 .smith/index/manifest.md
```

The systems table now lists eighteen system rows. Each row shows the file count and a one-line description placeholder (empty until step 3).

### Step 3 — Bulk-Generate Descriptions

```bash
/smith-index --describe
```

This is the opt-in LLM pass. Haiku 4.5 generates per-module + per-method descriptions in batches of N=10 files. Approval is per-batch (~20 files, configurable) with per-file reject:

```
Batch 3/22 (20 files):
  1. backend/webhooks/dispatcher.py — Dispatches webhook payloads with retry and backoff semantics.
  2. backend/webhooks/retry.py — Backoff strategies for transient webhook failures (exponential, jittered).
  ...
  20. backend/webhooks/dead_letter.py — Records permanently-failed webhook deliveries for operator review.
  [a]ccept batch / [r]eject file <n> / [s]kip batch / [q]uit ?
```

The Rule 4 contract applies: per-file checkpoint, JSONL log at `logs/smith-index-describe-<timestamp>.jsonl`, `--resume` works if the run is interrupted. Re-runs skip files whose `Hash:` matches `Described-Against-Hash:` (the hash cache).

**Verify after step 3:**

```bash
cat .smith/index/files/backend/webhooks/dispatcher.py.meta
```

Expected fields (illustrative):

```
**Description:** Dispatches webhook payloads with retry and backoff semantics.
Last Updated: 2026-06-02T14:21:00Z
Language: python
Lines: 184
Hash: 9f2c...
Described-Against-Hash: 9f2c...
Described-At: 2026-06-02T14:21:00Z

Functions:
  - Name: dispatch
    Id: 7a8b...
    Line: 42
    Params: (payload: WebhookPayload, retry_policy: RetryPolicy) -> DispatchResult
    Description: Sends a webhook payload through the configured retry policy, returning a DispatchResult capturing attempt history.
```

```bash
head -20 .smith/index/systems/system-04-webhooks.md
```

Expected: file-listing table now includes a Description column populated from per-module descriptions.

**Final state:** eighteen systems matching the declarations, every `.meta` file carries a description layer, the manifest is ready for `/smith-navigate` to route on intent rather than signatures.

---

## Scenario B — New Project Bootstrap

**Starting state:** an empty (or near-empty) project. No `.smith/`, no `.specify/`, no `CLAUDE.md`, no `constitution.md`.

**Goal:** Bootstrap the project through `/smith init` so the manifest is correct from day one, then populate descriptions on a first `/smith-index --describe` run.

### Step 1 — Initialize Smith

```bash
/smith init
```

The init workflow runs its usual sub-steps (constitution, CLAUDE.md, vault scaffolding), then runs the NEW v2 sub-step: scaffold system specs from `templates/system-spec-template.md` (A1).

For each system the operator declares, the workflow scaffolds `.specify/systems/<name>/spec.md` with frontmatter pre-populated and prompts for `paths:`:

```
Declare system: system-01-api
  paths: (one per line, blank to finish):
  > backend/api/
  > backend/middleware/
  >
  Wrote .specify/systems/system-01-api/spec.md
```

Empty `paths:` is permitted (the system can exist before any code lands).

After all systems are declared, `/smith init` runs its existing final sub-step: `/smith-index` (structural pass).

**Verify after step 1:**

```bash
ls .specify/systems/
ls .smith/index/systems/
cat .specify/systems/system-01-api/spec.md
```

Each declared system has a spec file with `paths:` frontmatter, and the corresponding `.smith/index/systems/<name>.md` exists with the correct file count.

### Step 2 — First Description Pass

```bash
/smith-index --describe
```

On a brand-new project the codebase is small. The bulk-describe run typically finishes in one or two approval batches. Rule 4 contract applies the same as Scenario A.

**Verify after step 2:**

```bash
grep -l "Description:" .smith/index/files/**/*.meta | head -5
```

Every indexed file's `.meta` carries a `**Description:**` line. The system manifest's Description column is populated for every file.

**Final state:** the project is fully Smith-enabled with structurally correct system membership, descriptions present from day one, and no manual migration required.

---

## Scenario C — Daily Edit Flow

**Starting state:** Scenario A's end state — armory after migration, with 18 systems and a populated description layer.

**Goal:** Demonstrate the v2 lifecycle: smith workflows update descriptions in-context; the save hook preserves them; `/smith-build` flags coverage gaps; an out-of-workflow edit trips the staleness signal.

### Step 1 — Fix a Bug via `/smith-bugfix`

User asks Claude to fix a backoff bug in `backend/webhooks/retry.py`:

```
> /smith-bugfix retry never escalates to dead-letter after max attempts
```

`/smith-bugfix` runs through its workflow (diagnose, plan, implement, test, commit). At the end of the implementation step, after the Edit/Write that fixed the bug, the workflow's new C1 sub-step updates the touched file's `.meta` description layer in-context:

- The bug was in `retry.py::RetryHandler::next_attempt`. The workflow regenerates the per-method `Description:` for `next_attempt` only.
- The file's purpose (backoff strategies for transient webhook failures) has not materially changed. The per-module `**Description:**` is left alone.
- Other methods' descriptions (e.g. `_jitter`, `_backoff_seconds`) are NOT touched.

The save hook (`manifest-updater.sh`) runs after the Edit. It re-parses the structural data, updates `Hash:`, and **preserves** the description layer the workflow just wrote, including `Described-Against-Hash:` (now equal to the new `Hash:`).

**Verify after step 1:**

```bash
grep -A2 "Id:" .smith/index/files/backend/webhooks/retry.py.meta | grep -A1 next_attempt
```

The `next_attempt` entry's `Description:` reflects the new behavior. Other methods' descriptions are unchanged from Scenario A.

### Step 2 — Build and Open PR

```bash
/smith-build
```

`/smith-build` runs through its workflow (tasks, implement, tests, commit, push, PR). When generating the PR description, the new v2 sub-step (C1.5) scans the diff for methods lacking a `.meta` description.

Because `/smith-bugfix` updated the touched method's description in step 1, the PR description shows:

```markdown
### Manifest Coverage
All methods in this diff have `.meta` descriptions. No backfill needed.
```

If the operator had bypassed the workflow (see step 3 below) and edited the file directly without a description update, the coverage block would list the affected method. The flag never blocks the PR; it surfaces the gap for the reviewer.

### Step 3 — Out-of-Workflow Edit (Staleness)

A teammate's `git pull` lands a refactor that touches `backend/webhooks/dispatcher.py`. The PostToolUse hook does not fire on `git pull`, but the post-merge git hook from v1 runs `/smith-index --incremental`. That re-parses the changed file structurally:

- `Hash:` is updated to the new content hash.
- `Described-Against-Hash:` is NOT touched (description-generation paths only).
- Result: `Hash:` != `Described-Against-Hash:` — the description is now stale.

When Claude next runs `/smith-navigate`:

```bash
/smith-navigate "where is the webhook dispatcher logic?"
```

The navigator detects the hash mismatch on `backend/webhooks/dispatcher.py.meta` and surfaces the staleness in its routing output:

```markdown
### Must Read (directly impacted)
- backend/webhooks/dispatcher.py [primary: 42-128, dispatch loop]
  ⚠️ Description stale (file modified since last description pass) — verify against current code
```

The navigator returns the file, but flags the description as potentially out-of-date. The operator can:

- Read the file and trust the structural data (always current).
- Run `/smith-index --describe` (the hash cache means only stale files get re-described — cheap).
- Touch the file via a smith workflow, which would update the description in-context as in step 1.

**Final state:** the v2 lifecycle keeps descriptions current for everything that goes through a smith workflow, surfaces staleness for everything that doesn't, and confines LLM cost to the explicit bulk path and the in-context workflow path. The save hook stays fast and LLM-free.

---

## Quick Reference

| Command | What it does | LLM? | Budget |
|---------|--------------|------|--------|
| `/smith init` | Bootstrap project (constitution, CLAUDE.md, vault, system specs, first `/smith-index`) | No | Setup-time |
| `/smith-migrate-system-paths` | Add `paths:` frontmatter to existing system specs | No | One-shot, interactive |
| `/smith-index` | Structural pass — parses, builds manifest | No | <60s / 400 files |
| `/smith-index --describe` | LLM-generate description layer | Haiku 4.5 | ~30-60s / 20-file batch |
| `/smith-index --resume` | Continue interrupted `--describe` run | Haiku 4.5 | Resumes at last checkpoint |
| `manifest-updater.sh` (auto) | Save-hook structural update; preserves descriptions | No | <500ms p95 |
| `/smith-new`, `/smith-bugfix`, `/smith-debug` | Update touched-method descriptions in-context | Inline (workflow LLM) | In-context, cheap |
| `/smith-build` | Includes coverage flag in PR description | No (post-process) | Build-time |
| `/smith-navigate` | Routes on manifest; surfaces staleness | Haiku 4.5 | <3s p95 |

2026-06-02 — 20-manifest-fixes
