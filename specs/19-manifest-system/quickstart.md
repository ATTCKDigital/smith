---
feature: 19-manifest-system
branch: 19-manifest-system
created: 2026-05-21
spec: ./spec.md
plan: ./plan.md
---

# Quickstart: Manifest System Walkthroughs

Three end-to-end walkthroughs covering the three primary deployment
flows. Use this document as the integration test plan and as user-
facing reference once docs/manifest-system.md is authored.

---

## Scenario A — New Project Bootstrap via `/smith init`

**Persona:** A developer starting a brand-new project. Has Smith
installed globally (`~/.claude/skills/`, `~/.smith/scripts/`). Has
just run `git init` and has no `.smith/` directory yet.

**Goal:** End up with a fully-indexed project ready for any Smith
workflow.

### Steps

1. **Install Smith** (one-time, already done):

   ```sh
   npx skills add attck/smith
   ```

   This places `parse-python.py` and `parse-js.js` at
   `~/.smith/scripts/`, registers `manifest-updater.sh` and
   `context-loader.sh` in `~/.claude/settings.json`, and installs all
   the Smith skills.

2. **Run `/smith init` in the project root:**

   ```
   You: /smith init
   ```

3. **Observe `/smith init` standard flow** (existing behavior):
   - Asks about project type, languages, framework.
   - Generates `CLAUDE.md` (now includes the "Smith Context System"
     and "File Size Awareness" sections — Requirement 12).
   - Generates `.specify/memory/constitution.md` if applicable (now
     includes "File Size Policy" and "Project Manifest" sections).
   - Creates `.smith/vault/` directory tree.

4. **`/smith init` invokes `/smith-index` as its final step** (new behavior — Requirement 5):

   ```
   /smith init: Running initial manifest build (/smith-index)…
   /smith-index: Found 47 source files across 5 candidate systems.
   /smith-index: Bootstrapping config/context-manifest.json from defaults.
   /smith-index: Bootstrapping config/system-paths.json from example.
   /smith-index: Indexed 47 files in 12.8s.
   /smith-index: 47 succeeded, 0 failed, 0 skipped.
   ```

5. **Verify the resulting tree:**

   ```sh
   $ tree .smith/
   .smith/
   ├── index/
   │   ├── manifest.md
   │   ├── systems/
   │   │   ├── system-01-api.md
   │   │   ├── system-02-frontend.md
   │   │   └── unassigned.md
   │   ├── files/
   │   │   ├── backend/
   │   │   │   └── src/
   │   │   │       └── …(mirrors source tree)
   │   │   └── frontend/
   │   │       └── …
   │   └── config/
   │       ├── context-manifest.json
   │       └── system-paths.json
   └── vault/
       ├── sessions/
       ├── agents/
       ├── queue/
       └── bank/
   ```

6. **Verify `.gitignore`:**

   ```sh
   $ grep '^\.smith/' .gitignore
   .smith/
   ```

7. **Customize `system-paths.json`** (recommended before first heavy use):

   ```sh
   $ $EDITOR .smith/index/config/system-paths.json
   ```

   Replace the example rules with your actual directory layout. Re-run
   `/smith-index` to reflect any changes to system assignments.

### Acceptance

- [ ] All `.smith/index/` directories present.
- [ ] `.smith/index/manifest.md` ≤50 lines.
- [ ] All system manifests ≤80 lines.
- [ ] `~/.claude/settings.json` shows `manifest-updater.sh` registered
      AFTER `lint-on-save.sh` in the PostToolUse `Write|Edit` chain.
- [ ] `~/.claude/settings.json` shows `context-loader.sh` registered
      as a `UserPromptSubmit` hook.
- [ ] `~/.smith/logs/smith-index-<ts>.jsonl` exists with one line per file.
- [ ] Total elapsed for 47-file index ≤60s.

---

## Scenario B — Existing Project Adopting the Manifest System

**Persona:** A developer who has been using Smith on a project for
months. Their project predates the manifest system, so
`.smith/index/` does not exist.

**Goal:** Adopt the manifest system without disrupting in-flight work.

### Steps

1. **Upgrade Smith** (in their global install):

   ```sh
   npx skills add attck/smith
   ```

   This refreshes skills, hooks, and parser scripts. Existing project
   state (`.smith/vault/`) is untouched.

2. **Open the project and invoke any Smith skill, e.g.:**

   ```
   You: /smith-bugfix something is broken in the products endpoint
   ```

3. **`context-loader.sh` fires:**
   - Detects `/smith-bugfix`.
   - Resolves 4-tier config; `navigator: true` for `smith-bugfix`.
   - Checks for `.smith/index/manifest.md` — NOT FOUND.
   - Logs warning to `~/.smith/logs/hooks.log`.
   - Injects this `additionalContext`:

     ```markdown
     <!-- smith-context-injection v1; skill=smith-bugfix; manifest=missing -->

     ## Smith Context

     > ⚠️ Manifest not initialized — run `/smith-index` to enable structured context retrieval. Proceeding with vault context only.

     ### Vault — Recent Sessions (3)
     - …
     ```

4. **Claude proceeds with vault-only context.** The bugfix workflow
   runs normally but without the navigator's curated file list. Claude
   may take more turns or read more speculatively than it otherwise
   would.

5. **The user notices the warning and runs `/smith-index` at a
   convenient pause:**

   ```
   You: /smith-index
   ```

   ```
   /smith-index: Found 312 source files across 0 known systems.
   /smith-index: No config/system-paths.json — bootstrapping from example.
   /smith-index: Indexed 312 files in 41.2s.
   /smith-index: 308 succeeded, 4 failed (see ~/.smith/logs/smith-index-2026-05-21T120100Z.jsonl), 0 skipped.
   ```

6. **User edits `system-paths.json`** to map their actual directory
   structure to system names, then re-runs `/smith-index` to reassign
   files (or runs `/smith-index --system unassigned` to redo just the
   bucket of unassigned files — once they've added rules to claim
   them).

7. **Next `/smith-bugfix` invocation:** `context-loader.sh` finds
   `.smith/index/manifest.md`, spawns `/smith-navigate`, injects full
   context block. The "manifest=missing" header flag is replaced by
   the normal injection format.

### Acceptance

- [ ] Existing Smith workflows continue functioning during the
      missing-manifest period (vault-only context, no hard failures).
- [ ] The soft warning is logged and injected exactly once per session
      (R6 mitigation — `.smith/vault/.warned-manifest-missing` marker).
- [ ] After `/smith-index` runs, the next skill invocation gets full
      context injection within 5s.
- [ ] `/smith-index --check` (post-bootstrap) reports no staleness.

---

## Scenario C — Daily Edit Flow

**Persona:** A developer in a normal editing session on a fully-
indexed project. They are about to edit a moderately-large file.

**Goal:** See how the manifest stays current during edits and how the
300-line warning surfaces in the workflow.

### Steps

1. **Developer asks Claude to make a change:**

   ```
   You: add an internal-notes field to ProductCreate
   ```

2. **Claude reads `backend/src/api/v1/products.py`** (350 lines —
   already over the 300-line threshold but indexed). It then performs
   an `Edit` adding a few lines, bringing the file to 358 lines.

3. **PostToolUse hook chain fires (per Decision 7):**
   - `file-change-logger.sh` (existing) — logs the edit to session.
   - `lint-on-save.sh` (existing) — runs `ruff format` on the file.
     Final line count after format: 357.
   - `manifest-updater.sh` (NEW, runs LAST):
     - Reads `tool_input.file_path` from stdin.
     - Extension `.py` → invokes `~/.smith/scripts/parse-python.py`
       (no `.smith/scripts/parse-python.py` override in this project).
     - Parser returns JSON in ~80ms.
     - Renders new `.meta` to `.smith/index/files/backend/src/api/v1/products.py.meta`.
     - Maps file to `system-15-command-center` per `system-paths.json`.
     - Atomically rewrites `.smith/index/systems/system-15-command-center.md` with the updated line count `357 ⚠️`.
     - Updates `.smith/index/manifest.md` "Last Updated" timestamp and recounts the "Files over 300 lines" stat.
     - File is >300 lines: emits `additionalContext` JSON:

       ```json
       {
         "hookSpecificOutput": {
           "hookEventName": "PostToolUse",
           "additionalContext": "⚠️ backend/src/api/v1/products.py is 357 lines (>300). Consider decomposition. See .smith/index/files/backend/src/api/v1/products.py.meta."
         }
       }
       ```

     - Total hook duration: ~290ms. Under budget.
     - Logs structured line to `~/.smith/logs/hooks.log`.

4. **Claude sees the additional context in its next turn** and may
   surface the warning to the user (e.g. "I added the field. Note
   that this file is now 357 lines, past the 300-line threshold —
   want me to suggest decomposition?").

5. **Later, developer kicks off a build:**

   ```
   You: /smith-build
   ```

6. **`/smith-build` runs its pre-PR file-size check** (Requirement 11.b):
   - Scans `.smith/index/files/` for files touched in this branch.
   - Finds the threshold marker in `products.py.meta`.
   - Includes a "File-size advisories" section in the PR description:

     ```markdown
     ### File-size advisories
     The following files in this PR exceed the 300-line guideline. Consider decomposition in a follow-up:
     - `backend/src/api/v1/products.py` (357 lines)
     ```

   - Build is NOT blocked. PR opens normally.

7. **Developer wants to navigate the codebase. They invoke
   `/smith-navigate` standalone:**

   ```
   You: /smith-navigate "fix the products POST endpoint validation"
   ```

8. **Navigator returns within 3s:**

   ```markdown
   ## Relevant Files

   ### Must Read (directly impacted)
   - backend/src/api/v1/products.py [primary: 230-380, POST endpoint]
   - backend/src/models/schemas.py [primary: 200-280, ProductCreate]

   ### Should Read (likely affected)
   - backend/src/services/shopify_sync_service.py [primary: 1-50, sync interface]
   - frontend/src/lib/api/products.ts

   ### Reference Only (context, don't modify)
   - backend/tests/test_products.py

   ### Systems Affected
   - Primary: system-15-command-center
   - Also affects: system-04-shopify-sync
   ```

### Acceptance

- [ ] `manifest-updater.sh` completed in <500ms (verified via
      `~/.smith/logs/hooks.log` `ms=` field).
- [ ] `.meta` file updated with new line count and ⚠️ marker.
- [ ] System manifest line for products.py shows `357 ⚠️`.
- [ ] Top-level manifest.md "Files over 300 lines" counter incremented appropriately.
- [ ] Next turn's user-visible Claude response references the threshold warning.
- [ ] `/smith-build` PR description includes "File-size advisories".
- [ ] `/smith-navigate` returns within 3s and matches the contract format from `contracts/navigator-output.md`.

---

## Failure-Mode Quickstarts

### F1 — Parser crashes on malformed source

User edits a Python file and accidentally introduces a `SyntaxError`
before saving. `manifest-updater.sh` invokes the parser; parser
catches the `SyntaxError`, returns partial JSON with an `errors[]`
entry. `.meta` file is updated to:

```markdown
# backend/src/api/v1/broken.py
Last Updated: …
Language: python
Lines: 142

## Parse Errors
- Line 47, col 8: invalid syntax

## Imports
- `fastapi` → APIRouter (line 1)
... (whatever was extractable)
```

Hook exits 0. No warning surfaced to session (parse errors are
common during refactors). Visible only via `.meta` inspection.

### F2 — Navigator times out

User invokes `/smith-bugfix`. `context-loader.sh` spawns
`/smith-navigate`. Haiku is slow (network blip). Hits 3s timeout.

`context-loader.sh`:
- Kills sub-agent.
- Logs `navigator_status=timeout` to `~/.smith/logs/hooks.log`.
- Injects vault-only context with header flag `navigator=timeout`:

  ```html
  <!-- smith-context-injection v1; skill=smith-bugfix; navigator=timeout -->
  ```

- Bugfix workflow proceeds without curated file list.

### F3 — `node` not on PATH

User edits a `.ts` file. `manifest-updater.sh` tries to invoke
`node ~/.smith/scripts/parse-js.js`. `node` not found.

- Hook logs `parser=js status=error reason=node-not-found`.
- `.meta` file is NOT updated.
- Hook exits 0 (fail-open).
- System manifest is NOT updated (stale until next `/smith-index --system <sys>` run).
- User gets no immediate warning but `/smith-index --check` will flag this file as stale.

---

## Performance Snapshot (expected)

| Operation | Budget | Typical |
|---|---|---|
| Single file edit → manifest updated | <500ms p95 | ~290ms |
| `/smith-bugfix` prompt → context injected | <5s p95 | ~3.7s |
| `/smith-navigate` standalone | <3s p95 | ~1.8s |
| `/smith-index` (100 files, cold) | <60s p95 | ~38s |
| Plain question (no Smith trigger) → injection | 0s | <20ms hook overhead, no injection |

---

## Quickstart Index

- Scenario A — full bootstrap on a fresh project. The expected steady-state for new Smith users.
- Scenario B — gradual adoption on an existing project. The expected upgrade path.
- Scenario C — observable behavior during a normal day's editing. The expected steady-state behavior.

Failure modes F1-F3 document the graceful-degradation contract that
spec.md hard constraints require.

2026-05-21 12:05:00 — 19-manifest-system
