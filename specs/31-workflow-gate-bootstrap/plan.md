---
feature: 31-workflow-gate-bootstrap
branch: 31-workflow-gate-bootstrap
created: 2026-06-04
status: planning
---

# Implementation Plan — Workflow-Gate Bootstrap Exemption

## Technical Context

- **Language / runtime.** Bash 4+ for the helper script (already required by the rest of the install tree). No new Node dependencies.
- **Helper location** — see Q1; default plan is `~/.smith/scripts/create-active-workflow.sh` (global, single source of truth, installed by install-parsers.sh).
- **Gate exemption mechanism** — see Q3; default plan is by basename match (`create-active-workflow.sh`) at the start of the Bash command, so the gate matches `bash ~/.smith/scripts/create-active-workflow.sh ...` and `~/.smith/scripts/create-active-workflow.sh ...` invocations alike but rejects `cat > create-active-workflow.sh` or other lookalikes.
- **Marker format** — unchanged from current (YAML with workflow / feature / branch / worktree / session_log / started fields). The helper writes the same shape so existing parsers don't break.
- **Atomic write** — tempfile + `mv` (atomic on POSIX). The helper writes to `<safe-branch>.yaml.tmp.$$` then renames.
- **Idempotency** — re-running the helper with the same branch updates the `started` timestamp but is otherwise a no-op. Collisions (different workflow type on the same branch) surface as exit code 3 with a clear error.

## Constitution Check

- **Rule 1 (Questions ≠ Actions).** N/A at plan stage.
- **Rule 2 (Skill compliance).** This plan respects the smith-new phase order; sub-step pacing preserved.
- **Rule 3 (Question files).** Eight Open Questions surfaced in spec.md, formalized in questions.md.
- **Rule 4 (Checkpoint/Resume).** N/A — this is a small infrastructure change, not a long-running process.
- **Rule 5 (Session logging).** Handled by vault hooks.
- **Rule 6 (General preferences).** `python3` everywhere, `.sh` for the helper.
- **Rule 7 (Directory setup).** Helper creates `.smith/vault/active-workflows/` if missing (current skills already do `mkdir -p`).

## Architecture Overview

```
Today (broken):
  /smith-bugfix [skill] →
    Phase 1 step: cat > marker.yaml << EOF
      → workflow-gate.sh denies (regex hits `>`)
      → Claude falls back to Python Path.write_text() workaround
      → marker created via undocumented hack

Target:
  /smith-bugfix [skill] →
    Phase 1 step: ~/.smith/scripts/create-active-workflow.sh \
      --branch "$BRANCH" --workflow smith-bugfix --slug "$SLUG" \
      --worktree "$WORKTREE_PATH"
      → workflow-gate.sh recognizes the exempt helper basename
      → helper runs, atomic-writes marker, exits 0
      → Phase 2+ proceed normally
```

For `/smith-index --describe`:

```
Today (broken):
  /smith-index --describe [skill] →
    skill prose writes via describe_write.py to .smith/index/files/*.meta
      → workflow-gate.sh denies (no marker, .smith/index/ not in SAFE_VAULT_DIRS for top-level)
      → user picks option 1 from in-session prompt: drop temp marker

Target:
  /smith-index --describe [skill] →
    .smith/index/ added to safe-paths exemption list
      → workflow-gate.sh allows .meta writes regardless of marker presence
      → describe loop proceeds without temp-marker dance
```

## File Structure

All paths absolute under `/Users/dennisplucinik/Projects/smith-repo`.

### NEW

| Path | Approx LOC | Purpose |
|---|---|---|
| `scripts/create-active-workflow.sh` | ~80 | The marker-creation helper. Atomic write, idempotent, input validation. |
| `tests/hooks/test_workflow_gate_exemption.sh` | ~120 | Integration test: gate allows helper invocation, blocks lookalikes / direct heredocs. |
| `tests/hooks/test_create_active_workflow.sh` | ~80 | Unit-ish test for the helper itself: marker shape, atomicity, idempotency, validation. |

### MODIFY

| Path | Change |
|---|---|
| `hooks/workflow-gate.sh` | Add helper-basename exemption in the Bash branch (before the redirection check). Add `.smith/index/` to a new SAFE_TOP_LEVEL_DIRS list (or extend the existing SAFE_VAULT_DIRS logic). |
| `skills/smith-new/SKILL.md` | Replace Phase 1 step 0 heredoc with helper invocation. |
| `skills/smith-bugfix/SKILL.md` | Replace Phase 1 step 2 heredoc with helper invocation. |
| `skills/smith-debug/SKILL.md` | Replace Phase 1 step N heredoc with helper invocation (exact step varies). |
| `skills/smith-build/SKILL.md` | Same. |
| `scripts/install-parsers.sh` | Add `install_file` line for `create-active-workflow.sh` (mode 755). Same shape as recent PR #27 / #29 additions. |
| `scripts/install.sh` | Pass-through — no change unless we decide to copy the helper from install.sh too. Most likely install-parsers.sh handles it. |
| `CHANGELOG.md` | Entry under [Unreleased] documenting the helper, the gate exemption, the `.smith/index/` widening, and the migration story. |
| `docs/manifest-system.md` (or a new docs file) | Brief note: "If your skill creates an active-workflow marker, invoke `~/.smith/scripts/create-active-workflow.sh` rather than writing the YAML inline. The gate exempts this exact helper." |

### KEEP

- The existing `clear-active-workflow.sh` (already shipped). The new create- helper is its mirror.
- `hooks/active-workflow-janitor.sh` (PR #16) — sweeps stale markers; still useful regardless of how markers are created.
- The YAML marker schema (unchanged).

## Component Design

### 1. `create-active-workflow.sh` (the helper)

**Public CLI:**
```
Usage: create-active-workflow.sh --branch <BRANCH> --workflow <WORKFLOW> \
       --slug <SLUG> --worktree <WORKTREE_PATH> [--session-log <PATH>]

Creates an active-workflow marker at
.smith/vault/active-workflows/<safe-branch>.yaml in the current project.

Exit codes:
  0 — marker created (or updated idempotently)
  2 — input validation error (bad branch name, missing required flag)
  3 — collision (different workflow already holds this branch)
  4 — write error (filesystem full, permissions, etc.)
```

**Behavior:**
1. Validate inputs:
   - `--branch` required, must match `[A-Za-z0-9/_.-]+`
   - `--workflow` required, must be one of smith-new, smith-bugfix, smith-debug, smith-build (configurable allowlist)
   - `--slug` required
   - `--worktree` required, must be an absolute path
2. Resolve project root via `git rev-parse --show-toplevel` (works from any subdir of the repo).
3. Compute SAFE_BRANCH by replacing non-`[A-Za-z0-9._-]` with `-`.
4. Compute marker path: `<PROJECT_ROOT>/.smith/vault/active-workflows/<SAFE_BRANCH>.yaml`.
5. Read existing marker if present:
   - If existing.workflow == requested.workflow → idempotent update of `started` timestamp.
   - If different workflow → exit 3 (collision).
6. Read session-log path from `--session-log` OR `.smith/vault/.current-session`.
7. Compose YAML body.
8. Atomic write: write to `<marker>.tmp.$$`, then `mv` to final path.
9. Echo marker path to stdout (callers can capture with `$(...)`).

**Why bash (not Python):** Already required by every other shipped script. No Python dependency for the bootstrap helper itself — it's invoked by skill prose that needs to be runnable in headless / cron contexts.

### 2. `hooks/workflow-gate.sh` changes

Two surgical edits:

**a. Exempt the helper invocation.** Before the existing Bash-subcommand check, add:
```bash
# Exempt the active-workflow marker helper. This is the one auditable
# entrypoint for marker creation; no other shell pattern can forge a
# marker.
HELPER_BASENAME="create-active-workflow.sh"
if printf '%s' "$COMMAND" | grep -qE "(^|[[:space:]/])${HELPER_BASENAME}([[:space:]]|$)"; then
    # Allow the helper to run regardless of marker presence.
    exit 0
fi
```

Position: before the `for cmd in rm rmdir mv cp ...` loop.

**b. Add `.smith/index/` to safe-paths for Write/Edit.** The existing `is_safe_vault_path` only checks under `.smith/vault/`. Add a parallel `is_safe_index_path`:
```bash
SAFE_INDEX_DIRS=(files systems config logs)

is_safe_index_path() {
    local file_path="$1"
    case "$file_path" in
        /*) ;;
        *) file_path="$PROJECT_DIR/$file_path" ;;
    esac
    local index_prefix="$PROJECT_DIR/.smith/index/"
    case "$file_path" in
        "$index_prefix"*)
            local rest="${file_path#$index_prefix}"
            local first_seg="${rest%%/*}"
            for safe in "${SAFE_INDEX_DIRS[@]}"; do
                if [ "$first_seg" = "$safe" ]; then
                    return 0
                fi
            done
            ;;
    esac
    return 1
}
```

Call it alongside `is_safe_vault_path` in the Write/Edit branch.

### 3. The four SKILL.md edits

Surgical replacement of the Phase 1 step's heredoc with a helper invocation. Each rewrite is ~10 LOC; total ~40 LOC across the four files. The replacement is mechanical — search for the `cat > .smith/vault/active-workflows/${SAFE_BRANCH}.yaml << EOF` pattern, replace with helper call.

## Phase-by-phase Build Order

1. **Helper script + tests** — build `create-active-workflow.sh`, write unit tests for marker shape, idempotency, atomicity, collision detection, input validation. Tests pass standalone (no gate involvement).
2. **Gate edits + tests** — add exemption + index-path widening to `workflow-gate.sh`. Write integration test that feeds the hook synthesized PreToolUse JSON for: helper invocation (allow), `cat > marker.yaml` (still deny), `cat > forged.yaml` (still deny), Write to `.smith/index/files/foo.meta` (allow), Write to `.smith/vault/active-workflows/forged.yaml` (still deny).
3. **install-parsers.sh** — add the helper to the install list. Same shape as PR #27 / #29. Verify by running install-parsers.sh against a fresh `~/.smith/scripts/` and confirming the helper lands.
4. **SKILL.md edits** — four surgical replacements. Run each skill's Phase 1 logic in isolation (via shell) to confirm the helper invocation works.
5. **End-to-end test** — invoke `/smith-bugfix` from a fresh Claude session in smith-repo to confirm bootstrap works without Python workaround.
6. **Docs** — CHANGELOG entry, optional docs/manifest-system.md note.
7. **Validation against tonight's PRs** — re-run the smith-bugfix workflow for a trivial fix and confirm it works end-to-end without the Python tricks.

## Testing Strategy

### Test 1 — Helper unit test (`tests/hooks/test_create_active_workflow.sh`)

- Marker file shape (YAML keys match expected).
- Idempotent re-run updates `started` timestamp, preserves other fields.
- Collision: re-running with a different `--workflow` exits 3.
- Atomicity: kill the helper mid-write, confirm no half-written marker exists.
- Input validation: missing flags exit 2 with helpful errors; branch name with shell metachars rejected.

### Test 2 — Gate exemption integration (`tests/hooks/test_workflow_gate_exemption.sh`)

- Feed the gate synthesized PreToolUse JSON for the helper command → expects allow.
- Feed `cat > .smith/vault/active-workflows/forged.yaml << EOF` → expects deny.
- Feed `~/.smith/scripts/create-active-workflow.sh --branch x --workflow smith-bugfix ...` from a subagent context (`PROJECT_DIR` from sub-agent worktree) → expects allow.
- Feed `Write` tool call to `.smith/index/files/foo.meta` without marker → expects allow.
- Feed `Write` tool call to `.smith/vault/active-workflows/forged.yaml` without marker → expects deny.

### Test 3 — End-to-end (manual checklist, optionally automated)

- Fresh checkout of smith-repo, fresh session in Claude Code, run `/smith-bugfix` with a trivial argument, confirm bootstrap works without the workaround.
- Same in a downstream project (armory or gold-canna-theme).

## Risks & Mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Helper basename exemption is too broad — someone names a malicious script `create-active-workflow.sh` and gets gate-bypass for free | Low | Medium | Tighten exemption to match full path OR add a sentinel env var (`SMITH_GATE_BYPASS=create-active-workflow`) the helper sets internally. |
| R2 | Widening `.smith/index/` blanket exemption opens a new write surface that wasn't intended | Low | Low | The SAFE_INDEX_DIRS list scopes to files/systems/config/logs only; matches what the indexer actually writes. |
| R3 | One of the 4 SKILL.md edits is wrong and that workflow's bootstrap silently breaks | Medium | Medium | Test each skill's Phase 1 in isolation before merge. Add a smoke test that asserts the helper invocation pattern is present in each SKILL.md. |
| R4 | Install drift bites again — install-parsers.sh adds the line but install.sh forgets to copy it | Medium | Medium | Run install.sh in a tempdir at PR review time; confirm helper lands at `~/.smith/scripts/create-active-workflow.sh`. |
| R5 | The exemption pattern lets sub-agents bypass the gate via spoofed commands | Low | Low | Per spec §"Why the workaround works but isn't acceptable": sub-agents are already trusted. This isn't a security boundary. |

## Plan Decisions (beyond the eight in questions.md)

### Decision: Helper location is `~/.smith/scripts/` (global)

- Per Q1, plan default is global. Single source of truth, easier to exempt by absolute path if needed.
- Trade-off: each skill needs to know the absolute path. Resolved by hardcoding `~/.smith/scripts/create-active-workflow.sh` in the SKILL.md prose, with a fallback to `scripts/create-active-workflow.sh` for repo-dev layouts.

### Decision: Gate exemption is by basename (not absolute path)

- Per Q3, basename is the simpler match. Absolute-path match would tie the gate to the install location, breaking repo-dev runs.
- Mitigation for R1: the exemption regex requires whitespace or `/` before the basename, so it doesn't match e.g. `cat > create-active-workflow.sh` (which would be `... > create-active-workflow.sh`, not matching our regex).

### Decision: Phase 5 questions gate proceeds even though spec already documents preferred paths

- The user explicitly wants to drive the questions phase. Open Questions in spec.md become questions.md. Plan defaults are the "Recommended" answers.

## Migration

- **Existing markers from tonight's runs:** still recognized. The 5 PRs from this session created markers via Python workaround; their YAML shape matches what the helper writes, so post-merge re-validation finds them unchanged.
- **Existing skills that have already used the heredoc pattern:** the 4 SKILL.md updates in this PR migrate them. Any third-party skill that copy-pasted the bootstrap pattern needs manual migration — CHANGELOG documents this.
- **install.sh / install-parsers.sh:** drift fix lands as part of this PR (Q7 answer permitting).
- **scheduler/smith-scheduler.sh:** unchanged. The scheduler invokes `claude --print -p "/smith-queue process ..."`; the slash command resolves to the updated skill which uses the helper. No scheduler edits needed.

## References

- `hooks/workflow-gate.sh` (PR #20) — the gate.
- `.specify/scripts/bash/clear-active-workflow.sh` — existing teardown helper, structural twin of what this PR ships.
- `hooks/active-workflow-janitor.sh` (PR #16) — sweeps stale markers; unaffected.
- `scripts/install.sh`, `scripts/install-parsers.sh` — install drift pattern.
- The 5 PRs that demonstrated the bug: #25, #27, #28, #29, #30.
- BANK-004 — the prior write-up.
