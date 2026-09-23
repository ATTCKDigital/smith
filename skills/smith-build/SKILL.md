---
name: smith-build
description: Autonomous build phase — generates tasks, implements, tests, commits, pushes, merges, and produces release notes. Runs without user interaction.
---

# SpecKit Autonomous Build

Executes the full build pipeline from answered questions through to merged PR and release notes. This command runs entirely without user interaction, using subagents to manage context.

**Arguments:** $ARGUMENTS

## Vault Logging

Throughout this action, log significant events to the vault session log. Read the session log path from `.smith/vault/.current-session`. If the file is missing or the vault is not initialized, skip all logging silently.

**Marker before first append**: the workflow-gate denies markerless Bash redirection, so `cat >> "$SESSION"` appends are blocked until the active-workflow marker exists. Create the marker (Phase 0 step 0 helper) FIRST, then write the invocation entry immediately after — do not log before the marker.

**Timestamps are UTC.** `HH:MM:SS` comes from `date -u +%H:%M:%S` — never a local clock, never a time from memory. The append already runs through a shell, so read the clock in that same command (`TS=$(date -u +%H:%M:%S)`) and spend no extra tool call. Substitute the resulting value: an unexpanded `$(...)` reaching the log is a known regression and will not parse. Every hook-written stamp in this log is `date -u`, so a local-clock entry lands hours away from its neighbours and skews the workflow window `hooks/workflow_summary_lib.py` derives from them.

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

`HH:MM:SS` here is UTC as well — `date -u +%H:%M:%S`, same rule as above. The `subagent-vault-writeback.sh` block that lands beside this one is hook-written and therefore already UTC; a local-clock invocation stamp would make a subagent appear to finish hours before it started.

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
- **Clean-code architecture** — apply this checklist directly (it implements
  the constitution's **Clean Architecture Policy** and mirrors the `/smith-clean-code`
  skill; do NOT rely on being able to load that skill, as build subagents may
  not have skill access):
  - Small, single-responsibility functions and files; one clear reason to change.
  - Intention-revealing names (avoid `data`, `temp`, `handler`, `util` when a
    meaningful name exists).
  - Guard clauses over deep nesting; keep control flow shallow.
  - Separation of concerns — keep I/O, business rules, and persistence in
    distinct units.
  - No dead code, commented-out blocks, or duplicated logic.
  - Honor the file structure `plan.md` prescribed; do not collapse it back into
    large monolithic files.
- **Reuse over duplication**: before writing new code, check for an existing
  component that already does it — extend or import it rather than recreating
  it. Use the reuse list in `plan.md` (and `/smith-navigate` / `.smith/index/`
  when available) to locate existing modules, services, and utilities. Do not
  copy-paste near-identical logic; factor shared logic into a common helper.
- **Keep files small**: follow the constitution **File Size Policy** (300-line
  soft target, 500-line decomposition threshold). When a file you are editing
  approaches the threshold, split it proactively during the build rather than
  leaving it for the post-hoc File Size Warnings flag in the PR body (§5.3).
- **After any code changes to a Docker service**: run `docker compose up -d --build <service>` immediately

## Phase 3: Testing (Subagent)

Launch a testing subagent after all implementation is complete.

### 3.1 Testing
Read `.smith/config.json`'s `quality.test` array (spec FR-1/FR-2). When
present and non-empty, run each listed command independently via `python3
subprocess.run(cmd, shell=True, timeout=quality.timeout_seconds)` — feature
56's Sub-layer D `_run_tool` mechanism (`scripts/security/dependency-scan.py`),
reused verbatim: catch `subprocess.TimeoutExpired`, never a shell
`timeout`/`gtimeout` wrapper. No legacy fallback bullets execute in this case.

```bash
python3 - << 'PYEOF'
import json, subprocess

try:
    with open(".smith/config.json") as f:
        config = json.load(f)
except Exception:
    config = None

quality = config.get("quality") if isinstance(config, dict) else None
commands = quality.get("test") if isinstance(quality, dict) else None
timeout_seconds = (quality or {}).get("timeout_seconds", 120)

if isinstance(commands, list) and commands:
    for cmd in commands:
        print(f"--- quality.test: {cmd} ---")
        try:
            result = subprocess.run(cmd, shell=True, timeout=timeout_seconds)
            if result.returncode != 0:
                print(f"FAILED (exit {result.returncode}): {cmd}")
        except subprocess.TimeoutExpired:
            print(f"TIMEOUT after {timeout_seconds}s: {cmd}")
else:
    print("__LEGACY_FALLBACK__")
PYEOF
```

When the script prints `__LEGACY_FALLBACK__` (`quality.test` is absent,
empty, or `.smith/config.json` itself is absent/malformed), run the CURRENT
two bullets verbatim, unchanged, byte-for-byte — zero behavior change:
- **If frontend code changed**: `cd services/command-center && pnpm test`
- **If Python service changed**: `cd services/<service> && poetry run pytest`
- Run existing test suites — do NOT skip tests

### 3.1b Lint
Read `.smith/config.json`'s `quality.lint` array (spec FR-3). Same
per-command `subprocess.run(cmd, shell=True, timeout=quality.timeout_seconds)`
mechanism as §3.1. When absent or empty, this step is skipped ENTIRELY — no
run, no PR mention. No legacy fallback exists here (unlike §3.1).

```bash
python3 - << 'PYEOF'
import json, subprocess

try:
    with open(".smith/config.json") as f:
        config = json.load(f)
except Exception:
    config = None

quality = config.get("quality") if isinstance(config, dict) else None
commands = quality.get("lint") if isinstance(quality, dict) else None
timeout_seconds = (quality or {}).get("timeout_seconds", 120)

if isinstance(commands, list) and commands:
    for cmd in commands:
        print(f"--- quality.lint: {cmd} ---")
        try:
            result = subprocess.run(cmd, shell=True, timeout=timeout_seconds)
            if result.returncode != 0:
                print(f"FAILED (exit {result.returncode}): {cmd}")
        except subprocess.TimeoutExpired:
            print(f"TIMEOUT after {timeout_seconds}s: {cmd}")
else:
    print("__SKIP__")
PYEOF
```

### 3.1c Typecheck
Read `.smith/config.json`'s `quality.typecheck` array (spec FR-4). Same
mechanism and same skip-when-absent behavior as §3.1b, same reasoning.

```bash
python3 - << 'PYEOF'
import json, subprocess

try:
    with open(".smith/config.json") as f:
        config = json.load(f)
except Exception:
    config = None

quality = config.get("quality") if isinstance(config, dict) else None
commands = quality.get("typecheck") if isinstance(quality, dict) else None
timeout_seconds = (quality or {}).get("timeout_seconds", 120)

if isinstance(commands, list) and commands:
    for cmd in commands:
        print(f"--- quality.typecheck: {cmd} ---")
        try:
            result = subprocess.run(cmd, shell=True, timeout=timeout_seconds)
            if result.returncode != 0:
                print(f"FAILED (exit {result.returncode}): {cmd}")
        except subprocess.TimeoutExpired:
            print(f"TIMEOUT after {timeout_seconds}s: {cmd}")
else:
    print("__SKIP__")
PYEOF
```

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
- §3.1b/§3.1c command failures, and any per-command `quality.timeout_seconds`
  timeout across §3.1/§3.1b/§3.1c alike, are covered by this SAME bound — up
  to 3 attempts, then log and continue — no new retry loop.

### 3.4 Coverage Check
Read `.smith/config.json`'s `quality.coverage.command` (spec FR-9..FR-14).
When absent or empty, this step is skipped entirely — no `/tmp` file
written, no PR section can ever appear for this build. When configured, run
it EXACTLY ONCE via the SAME `subprocess.run(cmd, shell=True,
timeout=quality.timeout_seconds)` mechanism as §3.1 — this step never
retries, regardless of outcome (distinct from §3.1/§3.1b/§3.1c, whose
failures/timeouts DO route through §3.3's bounded retry).

Match the command's combined stdout+stderr against `quality.coverage.regex`
FIRST when configured (exactly one capture group), else the built-in
catalogue in this fixed order:

| Tool shape | Pattern |
|---|---|
| pytest-cov `TOTAL` line | `TOTAL\s+\d+\s+\d+\s+(\d+(?:\.\d+)?)%` |
| jest/istanbul `text-summary` `Lines` line | `Lines\s*:\s*(\d+(?:\.\d+)?)%` |
| `go test -cover` | `coverage:\s*(\d+(?:\.\d+)?)%\s+of statements` |

```bash
python3 - << 'PYEOF'
import json, re, subprocess

try:
    with open(".smith/config.json") as f:
        config = json.load(f)
except Exception:
    config = None

quality = config.get("quality") if isinstance(config, dict) else None
coverage = quality.get("coverage") if isinstance(quality, dict) else None
command = coverage.get("command") if isinstance(coverage, dict) else None

if not command:
    raise SystemExit(0)

timeout_seconds = (quality or {}).get("timeout_seconds", 120)
override = (coverage or {}).get("regex")
minimum_percent = (coverage or {}).get("minimum_percent")

CATALOGUE = [
    r"TOTAL\s+\d+\s+\d+\s+(\d+(?:\.\d+)?)%",
    r"Lines\s*:\s*(\d+(?:\.\d+)?)%",
    r"coverage:\s*(\d+(?:\.\d+)?)%\s+of statements",
]
patterns = ([override] if override else []) + CATALOGUE

lines = []
try:
    result = subprocess.run(
        command, shell=True, capture_output=True, text=True,
        timeout=timeout_seconds,
    )
    output = (result.stdout or "") + (result.stderr or "")

    percent = None
    for pat in patterns:
        m = re.search(pat, output)
        if m:
            percent = float(m.group(1))
            break

    if percent is None:
        lines.append(f"- Coverage: output unparsed, could not verify against configured minimum (command: `{command}`)")
    elif minimum_percent is not None and percent < float(minimum_percent):
        lines.append(f"- **[High]** Coverage {percent:g}% < configured minimum {float(minimum_percent):g}% (command: `{command}`)")
    # percent extracted, no minimum configured, or percent >= minimum: no finding.
except subprocess.TimeoutExpired:
    lines.append(f"- Coverage: command timed out after {timeout_seconds}s, output unparsed (command: `{command}`)")

with open("/tmp/smith-build-coverage-findings.txt", "w") as f:
    for line in lines:
        f.write(line + "\n")
PYEOF
```

- Percent extracted AND `quality.coverage.minimum_percent` configured AND
  percent < minimum → exactly one High finding (`<percent>% < <minimum>%`,
  command excerpt, no `path:line` — coverage-run-scoped, not file-scoped)
  written to `/tmp/smith-build-coverage-findings.txt` (FR-11).
- Percent extracted but no minimum configured → informational report only
  (FR-12), zero findings produced.
- No regex (override or catalogue) matches → "coverage output unparsed"
  disclosure, NEVER a failure, never blocks or retries, never silently
  omitted from disclosure (FR-13).
- A command timeout is treated IDENTICALLY to unparsed output — disclosed,
  never a build failure (FR-14) — distinct from §3.1/§3.1b/§3.1c, whose
  timeouts DO route through §3.3's retry; §3.4 never retries, ever.

Non-empty findings file → PR body gains a "Quality Metrics" section
(§5.4); empty → section omitted entirely (FR-19).

## Phase 3.5: Clean Code Review Pass

Launch exactly ONE subagent (Task tool) to evaluate the full branch diff vs
`$BASE_BRANCH` against `smith-clean-code`'s rubric, strictly after Phase 3
has reached a passing state and strictly before Phase 4 begins. This is an
ordering precondition only — flag-never-block still governs the PR outcome
(§5.4), never this pass's own invocation.

**Invocation.** Thread the same `WORKTREE_PATH`/`BASE_BRANCH` context
Phase 4/Phase 5 already use:
```bash
BASE_BRANCH=$(.specify/scripts/bash/get-base-branch.sh)
```
Diff against `$BASE_BRANCH` only — never a hardcoded or inferred ref. Pin
the subagent to `model: sonnet` (not Haiku — this pass makes
auto-fix judgment calls, not narrow classification/lookup).

**Rubric delivery.** The subagent Reads `skills/smith-clean-code/SKILL.md`
(worktree copy first), falling back to `~/.claude/skills/smith-clean-code/SKILL.md`
(installed copy) only when the worktree copy is unavailable. It locates the
`## Review Process`, `## Decision Rules`, and `## What You Should Avoid`
sections by HEADING — e.g. `grep -n '^## Review Process'`, then Read from
that line to the next `^## ` heading — never by hardcoded line number,
since that file is edited independently of this feature and any cited
range would drift out of date.

**Findings contract.** Each finding carries exactly one severity
(Critical/High/Medium/Low) plus: Location (`path:line`), Tenet violated
(short label — e.g. "Deep nesting", "Duplicated logic", "God
function/file", "Unclear naming", "Mixed responsibilities"),
Behavior-preserving fix available (true/false), Fix-safety
(clear/unclear), Auto-fix eligible (derived, see below), Fix applied
(true/false — set only once the edit is actually made), and a 1-2
sentence Rationale. A finding missing any field defaults to Fix-safety:
unclear (flag, never fix).

**Auto-fix eligibility.** A finding is auto-fix eligible if and only if
it is behavior-preserving AND its fix-safety is clear. Not
behavior-preserving, or fix-safety unclear → always FLAG, never auto-fix.
State explicitly: a Critical finding whose only available fix would
change program behavior is NEVER auto-fixed, always flagged, regardless
of configuration — no override may relax this.

**`.meta` coverage.** This pass does NOT add its own proactive
`.meta`-write step. For builds launched via `smith-new`, that workflow's
existing per-edit `.meta` instruction already covers every edit the build
subagent makes, auto-fix edits included. For standalone `smith-build`
runs, auto-fix edits fall back to the existing passive §5.3.1 Description
Coverage Warnings scan, exactly like ordinary Phase 2 implementation
edits already do.

**No `tasks.md` coupling.** Auto-fix edits from this pass are polish, not
tracked tasks — they require no corresponding `tasks.md` change.

**Bounded re-test.** If one or more auto-fixes were applied (any count),
run exactly one full re-run of Phase 3 in its entirety (3.1 → 3.2 → 3.3).
If zero auto-fixes were applied, Phase 3 MUST NOT be re-run. A failing
re-run resolves entirely via Phase 3.3's own existing bounded-attempts
behavior — this pass adds no second retry loop, no second fix batch, and
does NOT re-review the diff, regardless of the re-run's outcome. The
bound is exactly: one review → at most one fix-application batch → at
most one Phase 3 re-run. No step repeats.

**Unresolved findings → scratch file.** Findings where `Fix applied:
false` are written by the review subagent itself (its own output — there
is no deterministic scan block to write here, unlike §5.3/§5.3.1, since
judging "is this a god function" is not something a script can do) to
`/tmp/smith-build-clean-code-findings.txt`:
```
- **[<Severity>]** `<path>:<line>` — <one-line description> (tenet: <Tenet violated>)
```
Medium, High, and Critical findings each get one line. Low-severity
findings are never listed individually — if any remain unfixed, append
exactly one trailing `+ N low-severity notes` line instead (omitted when
N=0). An auto-fixed finding contributes nothing to this file.

## Phase 3.6: Security Review Pass

Runs exactly once per build, strictly after Phase 3.5 completes (an ordering
precondition only, independent of its outcome) and strictly before Phase 4 begins
(FR-2). Never re-entered.

**Invocation.**
```bash
BASE_BRANCH=$(.specify/scripts/bash/get-base-branch.sh)
```
Diff against `$BASE_BRANCH` only.

**Step 1 — presence-detect.** Resolve `detect-scanners.sh` (installed-path-preferred,
repo-dev fallback — the convention `scripts/install.sh` stages this script family
under) and run it once, before any layer:
```bash
for cand in "$HOME/.smith/scripts/security/detect-scanners.sh" scripts/security/detect-scanners.sh; do
  [ -f "$cand" ] && DETECT_SCANNERS="$cand" && break
done
SCANNERS=$(bash "$DETECT_SCANNERS")   # gitleaks/semgrep/bandit=present|absent, one line each
```
Write `/tmp/smith-build-security-layers-ran.txt` (this feature's `data-model.md` §4)
unconditionally, derived from `$SCANNERS`: `layer1_builtin=ran`,
`layer1_gitleaks=ran|skipped_absent`, `layer2_sast=ran:<tool-name>|skipped_absent`,
`layer3_llm=ran`.

**Step 2 — Layer 1, unconditional (FR-8).** Resolve `secret-scan.sh` the same way and
invoke it, adding `--with-gitleaks` only if `gitleaks=present`:
```bash
for cand in "$HOME/.smith/scripts/security/secret-scan.sh" scripts/security/secret-scan.sh; do
  [ -f "$cand" ] && SECRET_SCAN="$cand" && break
done
echo "$SCANNERS" | grep -q '^gitleaks=present$' && GL="--with-gitleaks" || GL=""
bash "$SECRET_SCAN" --diff-base "$BASE_BRANCH" $GL
```
Exit `0` clean, `1` findings on stdout (parse, not a failure), `2` internal error
(log, treat this layer as skipped — not fatal). This is the only guaranteed-coverage
deterministic layer; must work correctly with zero external scanners installed
(FR-8).

**Step 3 — Layer 2, conditional.** If Step 1 reported `semgrep=present` and/or
`bandit=present`, run each against the same `git diff "$BASE_BRANCH" --name-only`
file list, normalized into this feature's `data-model.md` §2 five-field format
(`pattern-id` = `semgrep:<rule-id>` / `bandit:<check-id>`). Silently skip entirely if
neither is present (FR-9) — no error, no install attempt; neither tool is ever added
as an installed dependency of Smith or the project.

**Step 4 — Layer 3, unconditional.** Launch exactly ONE subagent (Task tool) to
review the full `git diff "$BASE_BRANCH"` against this rubric, stated verbatim:
injection (SQL/command/template), authentication/authorization flaws,
secrets/credential handling, unsafe deserialization or `eval`-family use, path
traversal, SSRF and unvalidated redirects, cryptographic misuse, sensitive-data
logging or exposure, dependency-adjacent code smells (not CVE/SCA scanning), and race
conditions/TOCTOU in security-relevant paths. Do NOT invoke Smith's built-in
`/security-review` capability — this rubric is the sole methodology. Pin `model:
opus`; read `.smith/config.json`'s `security_review.review_model`
(haiku|sonnet|opus|fable) to override, using the same file-exists-and-parses validity
gate as every other config read in this pipeline — missing/malformed config or key
defaults to `opus`.

**Findings contract.** Every finding carries exactly one Severity
(Critical/High/Medium/Low), `path:line` Location, Category, a 1-2 sentence Rationale,
and the originating Layer (1/2/3) — this feature's `data-model.md` §3.

**No auto-fix, ever (FR-13).** This phase makes ZERO Write/Edit calls to the working
tree, for any finding, any layer, any configuration — unlike Phase 3.5, there is no
eligibility test, because none exists.

**Step 5 — merge + decide.** Merge all layers' findings; evaluate this feature's
`data-model.md` §5 tier × severity × layer decision table against
`.smith/config.json`'s `security_review.enforcement_tier` (default `flag` if
absent/malformed, same defensive read as `review_model` above). One row applies in
every build regardless of tier: **any Critical Layer 1 (secret) finding ALWAYS
terminates** — non-bypassable, independent of `enforcement_tier`. The per-line
`# smith-secret-scan: allow` marker (applied before the scan runs) is the sole
false-positive remedy — no runtime-confirmation escape hatch, unlike the
browser-production confirm-gate (this is the system's second non-bypassable denial).

**Terminate branch.** Other layers may still finish evaluating so the eventual record
lists everything found, but nothing from this run reaches the flag-only scratch file
— the outcome is terminated, not a partial flag+terminate mix (NFR-6). Phase 4 never
begins, so Phase 5.1 (Commit)/5.2 (Push) never execute. Write a hard-stop marker to
the vault session log using this file's own `### [HH:MM:SS] /smith-build <event>`
format, `**Outcome:**` naming the terminating finding(s) (severity, `path:line`,
category, layer — excerpt REDACTED per this feature's `data-model.md` §2, no
internal-only exception), plus an explicit `**Hard-stop:** Security Review Pass
(Phase 3.6) terminated this build before Phase 4.` line. Surface the stop via Phase
7.5's Display Summary mechanism ("build terminated at Phase 3.6" instead of a PR
link). Preserve the worktree exactly like Phase 7.3's "on failure" convention; leave
the active-workflow marker uncleared. NEVER a prompt — this is a log entry, not a
pause (NFR-1).

**Flag branch.** If nothing resolves to "terminate," write every non-terminating
finding to `/tmp/smith-build-security-findings.txt` per this feature's
`data-model.md` §4 line format (Medium/High/Critical listed individually, Low folded
into one trailing `+ N low-severity notes` line, omitted when N=0) and proceed to
Phase 4 exactly like Phase 3.5 does today.

## Phase 3.7: Supply-Chain Review Pass

Runs exactly once per build, sequenced strictly after Phase 3.6 completes — an
ordering precondition only, independent of Phase 3.6's own outcome on runs
where 3.6 does not itself hard-stop (FR-2, this feature's `data-model.md`
§1-§7 is `56-supply-chain-gate`'s own local numbering). If Phase 3.6 DID
hard-stop and terminate the build, Phase 3.7 is never reached at all — the
pipeline never resumes past a Phase 3.6 termination; this is a consequence of
Phase 3.6's own existing contract, not something Phase 3.7 itself gates.
Never re-entered.

**Invocation — the divergence, stated up front.** Thread `WORKTREE_PATH` to
locate the repository root. Do **NOT** resolve or thread the base-branch diff
variable every phase before it in this file resolves via
`.specify/scripts/bash/get-base-branch.sh` (phases 3, 3.5, 3.6, 4, §5.3,
§5.3.1) — this phase performs a full-project scan, never a diff scan
(FR-3/A-3): every manifest in the repository is evaluated regardless of
whether this branch touched it.

**Step 1 — run Sub-layer D.** Resolve `dependency-scan.sh` the SAME
installed-path-preferred/repo-dev-fallback way Phase 3.6 resolves its own
scripts, and invoke it:
```bash
for cand in "$HOME/.smith/scripts/security/dependency-scan.sh" scripts/security/dependency-scan.sh; do
  [ -f "$cand" ] && DEPENDENCY_SCAN="$cand" && break
done
D_OUT=$(bash "$DEPENDENCY_SCAN" --repo-root "$WORKTREE_PATH")
```
Unlike Phase 3.6, this step does **not** separately invoke `detect-scanners.sh`
first — `dependency-scan.py`'s own Step 1 performs its own internal
tool-presence detection (`shutil.which()` over `osv-scanner`/`trivy`/`npm`/
`pip-audit`/`poetry`), so there is nothing left for Phase 3.7 itself to
orchestrate here. The extended nine-tool `detect-scanners.sh` still exists and
is still the presence-detection mechanism `smith-audit`'s Dependencies
sub-audit reads directly for its own disclosure output — it is simply not a
dependency of THIS phase's own control flow.

Parse `$D_OUT`'s first line as `MANIFEST_COUNT: <n>`. **If `n == 0`:** write
only the sentinel line `0 manifests found` to
`/tmp/smith-build-supply-chain-scan-status.txt`; leave
`/tmp/smith-build-supply-chain-findings.txt` empty/absent; record the SAME
`0 manifests found` text, verbatim, as this phase's vault session-log entry
(FR-6 — reused verbatim, never a second phrasing of the same outcome); do
**not** invoke `license-inventory.sh` at all (both scripts share the identical
discovery module, so a second invocation would deterministically rediscover
the same empty result); proceed straight to Step 3. **If `n > 0`:** split the
remainder of `$D_OUT` by line shape into (a) finding-bullet lines, (b)
`cve_scan=` status lines, (c) the trailing `LOW_COUNT: <n_d>` line — hold all
three for the merge in Step 3.

**Step 2 — run Sub-layer L (only reached when Sub-layer D's own
`MANIFEST_COUNT` was `> 0`).** Resolve `license-inventory.sh` identically:
```bash
for cand in "$HOME/.smith/scripts/security/license-inventory.sh" scripts/security/license-inventory.sh; do
  [ -f "$cand" ] && LICENSE_INVENTORY="$cand" && break
done
L_OUT=$(bash "$LICENSE_INVENTORY" --repo-root "$WORKTREE_PATH")
```
Split `$L_OUT` identically into finding lines, `license_inventory=` status
lines, and its own trailing `LOW_COUNT: <n_l>` line.

**Step 3 — merge + write (the ONLY place either sub-layer's output reaches
disk; never a decision, never a terminate check here).** Concatenate: Sub-layer
D's finding lines, then Sub-layer L's finding lines, then — only when
`n_d + n_l > 0` — exactly one trailing `+ <n_d + n_l> low-severity notes` line
(the two scripts' own `LOW_COUNT` values summed into a single merged line) →
write to `/tmp/smith-build-supply-chain-findings.txt`. Concatenate Sub-layer
D's status lines then Sub-layer L's status lines (per-manifest, so a given
`manifest_path` naturally gets both a `cve_scan=` and a `license_inventory=`
line, matching this feature's `data-model.md` §5 worked example) → write to
`/tmp/smith-build-supply-chain-scan-status.txt`.

**No auto-fix, ever (FR-19).** Zero `Write`/`Edit` calls to the working tree
for any finding, from either sub-layer, under any configuration — identical
invariant to Phase 3.6, for a categorically different reason: a dependency
bump or a license swap is an even larger judgment call than a security
remediation.

**Unlike Phase 3.6: no decision table, no terminate branch, ever (FR-20/OOS-3,
this feature's `data-model.md` §7).** This is a deliberate v1 boundary, not an
oversight — Phase 3.6 sits directly upstream and a reader who just
internalized ITS terminate semantics could otherwise wrongly assume Phase 3.7
inherits them. Phase 4 **always** begins next, unconditionally, regardless of
what either sub-layer found — even a Critical CVE with a known exploit, even a
deny-listed license on a production package.

**NEVER a prompt or pause of any kind (NFR-1)** — every branch above,
including the zero-manifest path, is silent and autonomous.

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

By this point, Phase 3.5 (Clean Code Review Pass) has already run and any
auto-fixes it applied are already in the working tree, so this scan's (and
§5.3.1's) `git diff $BASE_BRANCH` snapshot naturally reflects the post-fix
diff — no separate re-scan or staleness-avoidance step exists or is needed.

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

### 5.3.2 Pre-PR Function-Length Scan

Scan the diff for functions/methods whose body exceeds
`quality.function_length.soft` (default 50) or `.decompose` (default 100)
lines (spec FR-15..FR-18). Reuses `/tmp/smith-build-changed.txt` (from
§5.3), the same extension filter (`.py`/`.js`/`.jsx`/`.ts`/`.tsx`) and
exclude list (`vendor/`, `node_modules/`, `.venv/`, `dist/`, `build/`,
`.smith/`) §5.3/§5.3.1 already use, and the same installed-path-preferred
(`.smith/scripts/` → `~/.smith/scripts/` → repo-dev-fallback
`scripts/parsers/`) parser resolution §5.3.1 already uses.

**Import mechanics.** `scripts/parsers/meta_describe.py` has no CLI
entrypoint, so it cannot be invoked as a subprocess — it MUST be imported.
Resolve its containing directory the same installed-path-preferred way,
then `sys.path.insert(0, dir); import meta_describe as md` — the EXACT
pattern `scripts/parsers/describe_write.py:31,34` and
`scripts/parsers/describe_discover.py:65,68` already use in production.
Call `md.qualifying_methods(parsed, threshold=quality.function_length.soft)`
UNCHANGED, returning `{id, name, scope, line, end_line, body_lines, params,
return_type}` per entry — the exact shape needed, no parser change required
(OOS-2).

```bash
> /tmp/smith-build-function-length-findings.txt

for cand in .smith/scripts/meta_describe.py "$HOME/.smith/scripts/meta_describe.py" scripts/parsers/meta_describe.py; do
  [ -f "$cand" ] && META_DESCRIBE_DIR="$(dirname "$cand")" && break
done

while IFS= read -r f; do
  case "$f" in
    *.py|*.js|*.jsx|*.ts|*.tsx) ;;
    *) continue ;;
  esac
  [ -f "$f" ] || continue

  case "$f" in
    vendor/*|*/vendor/*|node_modules/*|*/node_modules/*|.venv/*|*/.venv/*|dist/*|*/dist/*|build/*|*/build/*|.smith/*|*/.smith/*) continue ;;
  esac

  PARSER=""
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

  CUR_JSON=$($PARSER "$f" 2>/dev/null || true)
  [ -z "$CUR_JSON" ] && continue
  [ -z "${META_DESCRIBE_DIR:-}" ] && continue

  python3 - "$f" "$CUR_JSON" "$META_DESCRIBE_DIR" >> /tmp/smith-build-function-length-findings.txt <<'PY' || true
import json, sys

rel, cur_json, md_dir = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, md_dir)
import meta_describe as md

try:
    with open(".smith/config.json") as f:
        config = json.load(f)
except Exception:
    config = None

quality = config.get("quality") if isinstance(config, dict) else None
fl = quality.get("function_length") if isinstance(quality, dict) else None
soft = int((fl or {}).get("soft", 50))
decompose = int((fl or {}).get("decompose", 100))

parsed = json.loads(cur_json)
entries = md.qualifying_methods(parsed, threshold=soft)

soft_count = 0
for e in entries:
    body = e["body_lines"]
    if body >= decompose:
        print(f"- `{rel}:{e['line']}` — `{e['name']}` ({body} lines, exceeds {decompose} — decompose)")
    else:
        soft_count += 1

if soft_count:
    print(f"__SOFT_COUNT__:{soft_count}")
PY
done < /tmp/smith-build-changed.txt

# Fold every file's soft-tier count into exactly one trailing line.
python3 - /tmp/smith-build-function-length-findings.txt << 'PY'
import sys

path = sys.argv[1]
with open(path) as f:
    lines = f.readlines()

total_soft = 0
kept = []
for line in lines:
    if line.startswith("__SOFT_COUNT__:"):
        total_soft += int(line.strip().split(":", 1)[1])
    else:
        kept.append(line)

if total_soft:
    kept.append(f"+ {total_soft} soft-tier warnings\n")

with open(path, "w") as f:
    f.writelines(kept)
PY
```

Bucket each returned entry by `body_lines`: `>= quality.function_length.decompose`
(100) → decompose-tier, listed INDIVIDUALLY (`path:line`, name, body-line
count) in `/tmp/smith-build-function-length-findings.txt`; `>= soft` (50)
and `< decompose` → soft-tier, folded into exactly ONE trailing `+ N
soft-tier warnings` line, omitted when N=0, never listed individually
(FR-17, mirrors this pipeline's existing low-severity-folding convention).

Non-empty findings file → PR body gains a "Function Length Warnings"
section (§5.4); empty → section omitted entirely (FR-18).

Include a **"Clean Code Review"** section in the PR body when
`/tmp/smith-build-clean-code-findings.txt` (written by Phase 3.5) is
non-empty:
```bash
[ -s /tmp/smith-build-clean-code-findings.txt ] && echo "include section" || echo "omit section"
```
If empty, omit the section entirely — matching the same include-if-non-empty
pattern as the two scans above. This is a FLAG, never a blocker. Always
proceed with PR creation.

Include a **"Security Review"** section in the PR body when
`/tmp/smith-build-security-findings.txt` (written by Phase 3.6, which already ran
pre-commit — before Phase 4 or Phase 5 began) is non-empty:
```bash
[ -s /tmp/smith-build-security-findings.txt ] && echo "include section" || echo "omit section"
```
If empty, omit the section entirely — same include-if-non-empty pattern as the
scans above. This is a FLAG, never a blocker. Always proceed with PR creation.

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

## Clean Code Review
<include this section only when /tmp/smith-build-clean-code-findings.txt is non-empty>

<contents of /tmp/smith-build-clean-code-findings.txt verbatim, e.g.:>
- **[High]** `services/billing/webhook.py:142` — God function mixes request
  validation, HTTP retry logic, and dead-letter persistence in one 80-line
  method (tenet: Mixed responsibilities)
- **[Medium]** `frontend/src/lib/api/products.ts:58` — Near-duplicate of
  `fetchOrderBundle`'s pagination-assembly logic (tenet: Duplicated logic)
+ 2 low-severity notes

This is a FLAG, never a blocker. Always proceed with PR creation.

## Security Review
<include this section only when /tmp/smith-build-security-findings.txt is non-empty>

<layer-disclosure line derived from /tmp/smith-build-security-layers-ran.txt — MUST
name every layer ran vs skipped-absent, never imply full coverage when a tool was
absent, e.g.:>
Layers: built-in secret scan ✓, gitleaks (absent), semgrep (absent), bandit (absent),
LLM review ✓.

<contents of /tmp/smith-build-security-findings.txt verbatim, e.g.:>
- **[High]** `services/billing/webhook.py:142` — Matches AWS access-key-id pattern
  `aws-akia` (excerpt: AKIA********Z9Q1) (category: Secrets/credential handling,
  layer: 1)
- **[Medium]** `services/api/db.py:12` — Query built via string concatenation from a
  request parameter (category: Injection (SQL), layer: 2)
+ 3 low-severity notes

This is a FLAG, never a blocker for a non-terminating finding. Always proceed with PR
creation.

## Supply-Chain Review
<include this section only when /tmp/smith-build-supply-chain-findings.txt is non-empty>

**full-project scan, not diff-scoped; findings may predate this change**

<per-manifest scan-path disclosure derived from /tmp/smith-build-supply-chain-scan-status.txt, e.g.:>
Scanned: `frontend/package.json` (npm-audit, license inventory), `backend/pyproject.toml`
(license inventory only — CVE scan absent). Skipped: `menu-generator/package.json` (no
lockfile; node_modules absent).

<contents of /tmp/smith-build-supply-chain-findings.txt verbatim, e.g.:>
- **[High]** `lodash@4.17.15` (`frontend/package.json`) — Prototype pollution in
  zipObjectDeep (category: GHSA-p6mc-m468-83gw, sub-layer: D)
- **[High]** `some-gpl-package@2.1.0` (`backend/pyproject.toml`) — License 'GPL-3.0'
  matches a configured deny-list entry (category: license-policy, sub-layer: L)
+ 4 low-severity notes

This is a FLAG, never a blocker — no finding from either sub-layer, at any severity,
blocks or delays this PR (FR-19/FR-20).

## Function Length Warnings
<include this section only when /tmp/smith-build-function-length-findings.txt is non-empty>

<contents verbatim, e.g.:>
- `services/billing/webhook.py:88` — `process_refund_batch` (118 lines, exceeds 100 — decompose)
+ 3 soft-tier warnings

This is a FLAG, never a blocker. Always proceed with PR creation.

## Quality Metrics
<include this section only when /tmp/smith-build-coverage-findings.txt is non-empty>

<contents verbatim, e.g.:>
- **[High]** Coverage 62% < configured minimum 80% (command: `pytest --cov=app --cov-report=term`)

This is a FLAG, never a blocker. Always proceed with PR creation.

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

- ALL phases run without user interaction — a Phase 3.6 security hard-stop is itself
  prompt-free (a logged, autonomous termination decision), never a subagent failure,
  and must not be swept into the "retry once" bullet below
- Use subagents for each major phase to manage context
- If a subagent fails, retry once before logging the error and continuing
- Always rebuild Docker after code changes — never skip this
- Never use `git add -A` or `git add .` — always stage specific files
- Never commit `.env` files or credentials
- Playwright tests are MANDATORY when frontend files are modified
- The release.md file is the permanent record of what was built
