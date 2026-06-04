---
feature: 31-workflow-gate-bootstrap
branch: 31-workflow-gate-bootstrap
created: 2026-06-04
status: in-progress
processes_bank_entry: BANK-004
builds_on: 20-workflow-gate (PR #20), PRs #25/#27/#28/#29/#30 (each used the Python workaround)
---

# Workflow-Gate Bootstrap Exemption

## Summary

Fix the workflow-gate hook's chicken-and-egg: skills that should bootstrap their own active-workflow markers can't, because the gate's shell-redirection regex (`(^|[^0-9&])>>?[^&|]`) denies the very `cat > marker.yaml << EOF` pattern documented in their Phase 1 step. Tonight five PRs (#25, #27, #28, #29, #30) all hit this and worked around it via Python's `Path.write_text()` — a hack that surfaces every time someone runs a workflow skill inside a smith-installed project.

Also fix the adjacent gap that bit `/smith-index --describe`: the gate's exemption list (`SAFE_VAULT_DIRS`) covers paths under `.smith/vault/` only, so legitimate maintenance writes to `.smith/index/files/*.meta` are blocked without a marker — even though `/smith-index` is not a workflow command in the smith-new / smith-bugfix sense.

## Background — Why The Gate Exists

PR #20 introduced `hooks/workflow-gate.sh` as a PreToolUse hook on Bash/Write/Edit. The design rationale (from the hook's header comment): "Hard, tool-layer enforcement of Smith's workflow discipline. Denies any file-modifying tool call unless a Smith workflow marker exists at `<project>/.smith/vault/active-workflows/*.yaml`."

The gate's value-add: prevent code edits outside a tracked workflow, so every change has a spec, a branch, and a PR trail. This worked fine in tests where the marker pre-existed. It hadn't been stress-tested against bootstrap.

## Problem Statement

### Problem 1: Marker bootstrap deadlock

Every workflow skill (smith-new, smith-bugfix, smith-debug, smith-build) has a Phase 1 step that creates its own marker:

```bash
mkdir -p .smith/vault/active-workflows
cat > .smith/vault/active-workflows/${SAFE_BRANCH}.yaml << EOF
workflow: smith-bugfix
...
EOF
```

The gate sees `cat > file` → matches redirection regex → denies.

Result: the documented bootstrap path doesn't work. Tonight's 5 PRs were only possible because Claude can invoke Python via the Bash tool, and Python's internal `Path.write_text()` doesn't surface as a shell redirection. Users without that escape valve (e.g., a manual shell script invocation, a sub-agent that doesn't know the workaround, a cron job running `claude --print`) would silently fail at marker creation.

### Problem 2: Maintenance command writes blocked

`/smith-index --describe` writes to `.smith/index/files/*.meta` as part of its normal operation. `.smith/index/` is a top-level directory under `.smith/`, NOT under `.smith/vault/`. The gate's exemption list:

```bash
SAFE_VAULT_DIRS=(sessions bank ledger queue agents todo reports index audits)
# Must be under .smith/vault/
```

The literal "index" in the list refers to `.smith/vault/index/` (which doesn't exist), not `.smith/index/`. So `/smith-index --describe` running in gold-canna-theme hit the gate, with no obvious solution short of dropping a temp marker. Same workaround pattern.

### Why the workaround works but isn't acceptable

`python3 -c "Path('marker.yaml').write_text(...)"` doesn't trigger the gate's redirection regex because the `>` isn't visible at the shell-command level. But:
- It's not documented anywhere
- It depends on Claude knowing the trick
- It defeats the gate's anti-forgery property as completely as adding `active-workflows/` to `SAFE_VAULT_DIRS` would, because any sub-agent can do the same
- It's brittle: someone refactoring a skill could revert to the heredoc and silently break bootstrap

## Goals

1. **Skills self-bootstrap reliably.** A fresh `/smith-bugfix` invocation in any smith-installed project creates its marker via a documented, auditable path — without Python tricks.
2. **The gate retains its anti-forgery rationale** by exempting only one specific, named entry point rather than the entire `active-workflows/` directory.
3. **`/smith-index --describe` works without a temp-marker dance** — either by recognizing it as a maintenance command, or by giving it a real workflow marker pattern.
4. **Backward compatibility.** Existing markers (yaml files in `active-workflows/` from prior runs) continue to be recognized. The 5 PRs tonight shipped successfully; their behavior shouldn't change.
5. **No regression in the gate's existing tests** (any) and no regression in the 54 parser tests shipped this session.

## Non-Goals / Out of Scope

- Replacing the gate's anti-forgery design with something stronger. Sub-agents are trusted; this isn't a security boundary, and tonight's Python workaround already proves that. We're picking the right ergonomic, not hardening security.
- Refactoring all install.sh + install-parsers.sh hardcoded copy lists into a glob-based copy. The drift bugs (PRs #27, #29) are real but a separate concern.
- Documenting the gate's behavior in user-facing docs (CLAUDE.md additions, README updates). Worth doing but separate.
- Loosening the gate's redirection regex generally. The regex has known false-positives (e.g., `->` in echo strings, `2>&1` followed by other content), but each false-positive is its own diagnosis. Worth a follow-up bank entry, out of scope here.

## Users / Stakeholders

- **Smith workflow users** running `/smith-new`, `/smith-bugfix`, `/smith-debug`, `/smith-build` in installed projects — primary beneficiary; their workflow invocations "just work" again.
- **`/smith-index` users** running `--describe` or any other mode that writes to `.smith/index/` — secondary beneficiary if Problem 2 is addressed.
- **Sub-agent authors** invoking workflow skills from within larger orchestrations (e.g., `/smith-build` spawning sub-agents) — beneficiary if the helper is callable from sub-agent contexts.
- **The 2am scheduler** (`scheduler/smith-scheduler.sh`) running `claude --print -p "/smith-queue process ..."` — beneficiary; scheduled runs hit the gate too.
- **Future skill maintainers** who shouldn't need to know the Python workaround.

## Requirements

### Track A — Bootstrap helper

A1. **Ship a marker-creation helper.** A single script that, given branch + workflow name + slug + worktree path, atomically creates the active-workflow yaml at `.smith/vault/active-workflows/<safe-branch>.yaml`. Atomic via tempfile + rename. Returns the path on stdout. Idempotent (re-running with the same branch produces the same marker; collisions detected and surfaced).

A2. **Exempt the helper from the gate.** The gate recognizes invocations of this exact helper (by basename and/or absolute path) and allows them through. The exemption is narrow: it doesn't exempt arbitrary shell scripts under the same directory, only this one.

A3. **Update all four workflow SKILL.md files** to invoke the helper instead of inline `cat > marker.yaml << EOF`. Each skill's Phase 1 bootstrap rewrites from:
```bash
cat > .smith/vault/active-workflows/${SAFE_BRANCH}.yaml << EOF
workflow: smith-bugfix
...
EOF
```
to:
```bash
<helper-path> --branch "$BRANCH" --workflow smith-bugfix --slug "$SLUG" --worktree "$WORKTREE_PATH"
```

A4. **Ship the helper via install.** Adding the helper to install-parsers.sh + install.sh copy lists. Same pattern as PR #27 / #29 — and a reminder of the glob-based copy refactor we still owe (separate concern).

### Track B — `/smith-index` exemption

B1. **Allow `.smith/index/` writes without a marker.** Either by adding it to SAFE_VAULT_DIRS (modifying the "Must be under .smith/vault/" comment too), or by creating a separate `SAFE_INDEX_DIRS` list. `/smith-index --describe` running in a fresh session should write its `.meta` files without needing a temp marker.

B2. **Preserve the anti-forgery rationale** for `active-workflows/` markers — that's the whole point of Track A. We're widening write access to `.smith/index/`, not to `.smith/vault/active-workflows/`.

### Track C — Tests + Documentation

C1. **Unit/integration test for the helper.** Verifies marker creation, idempotency, atomic-write behavior, input validation.

C2. **Integration test for the gate exemption.** Verifies the gate allows the helper invocation but still blocks `cat > marker.yaml`. Probably a shell-level test that feeds the gate hook a synthesized PreToolUse JSON.

C3. **End-to-end test.** Invoke `/smith-bugfix` from a fresh shell (no Claude session — just bash) and verify it can self-bootstrap. Skipping if Claude isn't installed in CI.

C4. **CHANGELOG entry** documenting the new helper, the gate exemption, and the migration path for any third-party skill that wants to use the bootstrap pattern.

## Hard Constraints

- The gate continues to block edits when no marker is present AND the command isn't the exempted helper. (No "drop the anti-forgery property" trade-off.)
- The helper is the SINGLE chokepoint for marker creation. No skill ever uses `cat > marker.yaml` inline again.
- Existing markers are recognized unchanged.
- `python3` everywhere, never `python`. Helper is bash + shipped as `chmod 755`.
- No new Node dependencies.

## Acceptance Criteria

### Functional

1. Running `/smith-bugfix` in a fresh smith-installed project creates a marker via the helper, and the workflow proceeds normally.
2. Running the helper directly from a shell (without any Claude session) creates a valid marker.
3. Attempting to write a forged marker via `cat > active-workflows/foo.yaml` still gets blocked by the gate.
4. `/smith-index --describe` in a fresh session writes `.smith/index/files/*.meta` without needing a marker.
5. Pre-existing markers from prior runs are still recognized by the gate.
6. The 5 PRs from tonight — running their post-merge state — pass their existing tests.

### Quality

- All existing tests pass.
- New tests for the helper, gate exemption, and `.smith/index/` write coverage all pass.
- No new lint warnings on changed files.

## Open Questions

(Promoted to Phase 5 questions gate — see questions.md.)

1. Where should the helper live: `.specify/scripts/bash/` (per-project) or `~/.smith/scripts/` (global)?
2. Should the helper also write a session-log start marker?
3. How should the gate recognize the helper? By absolute path, by basename, or by a sentinel env var?
4. For Problem 2: add `.smith/index/` to SAFE_VAULT_DIRS, or create a separate maintenance-paths list?
5. Should the helper validate inputs?
6. Should we ship a complementary teardown helper or use the existing `clear-active-workflow.sh`?
7. Should the migration of the four SKILL.md files happen in this PR, or sequenced as four follow-ups?

## References

- PR #20 — `hooks/workflow-gate.sh` introduction.
- BANK-004 — `.smith/vault/bank/2026-06-04_035645-workflow-gate-bootstrap-exemption.md`.
- `hooks/workflow-gate.sh` — current gate implementation (the file this feature modifies).
- `skills/smith-new/SKILL.md`, `skills/smith-bugfix/SKILL.md`, `skills/smith-debug/SKILL.md`, `skills/smith-build/SKILL.md` — the four Phase 1 sites updated.
- `scripts/install.sh`, `scripts/install-parsers.sh` — install lists getting a new entry.
- PRs #25, #27, #28, #29, #30 — each used the Python workaround tonight. Confirm none regress after this feature lands.
- `scheduler/smith-scheduler.sh` — uses `claude --print` which is also affected by this issue when running scheduled workflows.
- `.specify/scripts/bash/clear-active-workflow.sh` — existing teardown helper; this feature ships its counterpart.
