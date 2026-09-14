---
name: smith-audit
description: Run a comprehensive audit on a specific system or all systems. Prompts for system selection, then runs all sub-audits and produces a unified report.
---

# SpecKit Audit — Umbrella Command

Run a full-spectrum audit on a specific system or across all systems. This command orchestrates all sub-audits and produces a unified report.

**Arguments:** $ARGUMENTS

## Vault Logging

Throughout this action, log significant events to the vault session log. Read the session log path from `.smith/vault/.current-session`. If the file is missing or the vault is not initialized, skip all logging silently.

Append entries using this format:

```
### [HH:MM:SS] /smith-audit <event>

**User Request:**
> <verbatim user message that triggered this action>

**Synthesized Input:** <brief summary>
**Outcome:** <what happened>
**Findings:** <summary>
**Systems affected:** <system IDs>
```

Log at these points:
1. **On invocation** — which system(s) selected, full audit or specific sub-audit
2. **After each sub-audit completes** — sub-audit name, finding count by severity (critical/high/medium/low)
3. **After unified report generated** — path to report, total findings across all sub-audits
4. **If action plan generated** — count of remediation items by priority

## Phase 0: Scheduled Mode & Marker Bootstrap

`/smith-audit` writes report files (`specs/audits/*.md`, per-system `specs/system-XX-*/audits/*.md`) but has no workflow-gate marker handling of its own — `hooks/workflow-gate.sh` denies any file-modifying tool call without an active-workflow marker present. This phase closes that gap for BOTH invocation modes: a non-interactive `--scheduled` dispatch from the scheduler, and a plain interactive `/smith-audit` run.

### Parse `--scheduled` and its subset list

If `$ARGUMENTS` contains `--scheduled`, this is a scheduled-mode invocation. `--scheduled` is followed immediately by a bare comma-separated subset list, no further flag — e.g.:

```
/smith-audit --all --scheduled requirements,codequality,security,dependencies,workflow
```

```bash
SCHEDULED_MODE=""
SCHEDULED_SUBSETS=""
case "$ARGUMENTS" in
    *--scheduled*)
        SCHEDULED_MODE=1
        SCHEDULED_SUBSETS=$(echo "$ARGUMENTS" | sed -n 's/.*--scheduled[[:space:]]*\([^ ]*\).*/\1/p')
        ;;
esac
```

Extract the comma-separated list and validate each token against the 11 named sub-audit categories already enumerated in "Sub-Audit Orchestration" below. Reuses the same unquoted-`tr`-split idiom `scheduler/smith-scheduler.sh` already uses for its own comma-separated `depends_on` field, not a new parsing convention:

```bash
VALID_SUBSETS="requirements codequality performance security accessibility ux dependencies infrastructure workflow seo feature"
REFUSE_REASON=""
for tok in $(echo "$SCHEDULED_SUBSETS" | tr ',' '\n' | tr -d ' '); do
    [ -z "$tok" ] && continue
    case " $VALID_SUBSETS " in
        *" $tok "*) ;;
        *) REFUSE_REASON="unrecognized subset: $tok" ;;
    esac
    if [ "$tok" = "feature" ]; then
        REFUSE_REASON="feature sub-audit is not permitted in --scheduled mode (requires interactive interview)"
    fi
done
```

### Refusal checks — BEFORE any marker creation or sub-audit dispatch

Three refusal conditions, checked in this order, all before the marker bootstrap below runs:

1. **Unrecognized token.** Any subset token not in the 11-category vocabulary above is a refused invocation. FR-9.
2. **`feature` anywhere in the list.** `feature` is NEVER permitted in `--scheduled` mode, regardless of configuration — it has a user interview phase with no non-interactive substitute. This is unconditional; no `scheduled_audits` config field can permit it. FR-10, US-4.
3. **Missing `--all` / system identifier.** A `--scheduled` invocation whose `$ARGUMENTS`, once `--scheduled` and its subset list are set aside, resolves to neither `--all` nor a system identifier (see "System Selection" below) is refused rather than falling through to the empty-args interactive prompt — this is the one prompt branch a non-interactive `claude -p` invocation could otherwise hang on indefinitely. FR-8.

Any of these three refusals is a logged failure (to the vault session log per "Vault Logging" above, and to stdout/stderr so the scheduler's own dispatch capture sees it) with a clear reason — no active-workflow marker is created, no report file is written, and `/smith-audit` returns without further action. All three checks run before marker bootstrap, so none of them requires a `clear-active-workflow.sh` call — there is nothing yet to clear.

### Marker bootstrap — BOTH `--scheduled` and plain interactive invocations

Once the refusal checks above pass (or don't apply — a plain interactive invocation triggers none of them), bootstrap a `maintenance` active-workflow marker before writing any report file. This applies unconditionally to every `/smith-audit` invocation, not only `--scheduled` ones — the exact same `create-active-workflow.sh`/`clear-active-workflow.sh` code path already has to exist for `--scheduled`, so gating it behind `--scheduled` would leave interactive runs relying on whatever marker happens to already be active from an unrelated workflow, or failing closed with no marker at all, for zero additional implementation cost. This mirrors `skills/smith-update/SKILL.md`'s own Phase 0 pattern verbatim:

```bash
TS=$(date -u +"%Y-%m-%dT%H-%M-%SZ")
if [ -n "$SCHEDULED_MODE" ]; then
    LABEL="scheduled-audit-${TS}"
else
    LABEL="audit-${TS}"
fi
PROJECT_DIR=$(pwd)
if [ -d "$PROJECT_DIR/.smith" ]; then
    ~/.smith/scripts/create-active-workflow.sh \
      --branch "$LABEL" --workflow maintenance --slug "$LABEL" \
      --worktree "$PROJECT_DIR"
    # (Falls back to scripts/create-active-workflow.sh in repo-dev layouts.)
    MARKER_PATH="$PROJECT_DIR/.smith/vault/active-workflows/${LABEL}.yaml"
fi
```

`maintenance` is the existing `--workflow` allowlist entry on `scripts/create-active-workflow.sh` — reused unchanged, no new enum value added. The `--branch "$LABEL"` value is a **synthetic label naming no real git ref** — `/smith-audit` never creates a worktree or branch; it exists solely to satisfy `create-active-workflow.sh`'s required `--branch` argument and to give the marker file a unique, sortable name. FR-11, FR-18, A-2.

### Clearing the marker — EVERY exit path

Because `/smith-audit`'s orchestration spans multiple separately-invoked bash blocks and Claude tool calls (subagent dispatch, report writes), not one OS process, a single shell `trap ... EXIT` cannot span the whole flow — the same constraint `skills/smith-update/SKILL.md` already solves the identical way. Clear the marker via the shipped helper at every documented exit point below, mirroring `smith-update`'s own per-early-return "cleanup marker, exit cleanly" comment pattern:

```bash
[ -n "${MARKER_PATH:-}" ] && [ -f "$MARKER_PATH" ] && \
    "$PROJECT_DIR/.specify/scripts/bash/clear-active-workflow.sh" "$LABEL" 2>/dev/null || true
```

Documented exit points requiring this call:
- **Normal completion** — call `clear-active-workflow.sh "$LABEL"` after the report (and, for `--scheduled`, the Drift block, rolling-log append, and state-file write — see "Report Generation" below) is fully written.
- **A sub-audit crash** — call `clear-active-workflow.sh "$LABEL"` immediately, log the failure, and return without a partial or incomplete report.
- **A report/drift/log-write failure** — call `clear-active-workflow.sh "$LABEL"` immediately, log the failure, and return.
- **Pre-marker refusals need no clearing** — the three refusal checks above occur before marker creation, so there is nothing to clear on that path.

A lingering marker is never an acceptable outcome — leaving one active silently disables the workflow-gate for every other file-modifying tool call in that project until `hooks/active-workflow-janitor.sh`'s 1-hour-minimum-grace-period sweep eventually removes it. FR-9, FR-10, FR-12, US-3.

## System Selection

### If `$ARGUMENTS` contains `--all`:
- Run audits across ALL systems (full-spectrum mode)
- Reports go to individual system folders + a global summary at `specs/audits/<date>-full-spectrum.md`
- Use subagents per system to manage context

### If `$ARGUMENTS` contains a system identifier (e.g., `system-15`, `command-center`, `014`):
- Match it to the correct system spec directory
- Run all sub-audits on that system only

### If `$ARGUMENTS` is empty:
- **Note:** a `--scheduled` invocation with no `--all`/system identifier never reaches this branch — Phase 0 above refuses it before System Selection runs, so this interactive prompt only ever fires for a plain interactive invocation.
- Scan for all system spec directories:
  ```bash
  ls -d specs/system-*/spec.md specs/[0-9]*/spec.md 2>/dev/null
  ```
- Present a numbered list to the user:
  ```
  Which system would you like to audit?

  1. system-00-config-isolation
  2. system-01-core-infrastructure
  3. system-03-email-archive-contact-graph
  ...
  15. system-15-command-center

  Or type --all for a full-spectrum audit across all systems.
  ```
- Wait for user selection before proceeding.

## System-to-Code Mapping

Each system audit needs to know which code directories and files belong to it. Determine this by:

1. **Reading the system's `spec.md`** — look for file paths, service names, directory references
2. **Known mappings** (from CLAUDE.md Architecture section):
   - `system-00-config-isolation` → `docker-compose.yml`, `.env`, `scripts/`
   - `system-01-core-infrastructure` → `docker-compose.yml`, `scripts/`, infrastructure configs
   - `system-02-ai-models-layer` → Ollama configs, model files
   - `system-03-email-archive-contact-graph` → `services/email-pipeline/`, Qdrant collections, Neo4j schemas
   - `system-04-personal-voice` → `services/voice-training/`
   - `system-05-communication-triage` → `services/communication-triage/`, `services/command-center/routes/triage.js`
   - `system-06-communication-learning-loop` → N8N workflows, training pipeline
   - `system-09-meeting-intelligence` → meeting-related services
   - `system-10-social-listening` → social signal services
   - `system-13-trend-intelligence` → trend analysis services
   - `system-15-command-center` → `services/command-center/` (full frontend + Express backend)
3. **Fallback**: Grep the codebase for references to the system name/number

## Documentation Sources

Every sub-audit MUST also review these documentation sources for the target system:

1. **Session logs**: `docs/sessions/*.md` — filter for sessions tagged with the system name/number. Check if decisions made in sessions are reflected in the current code.
2. **System questions**: `specs/system-XX-*/questions.md` — check for unanswered questions (blank `**Answer:**` fields). Flag as unresolved decisions.
3. **Pre-implementation questions**: `specs/questions/*.md` — check for questions related to the target system. Verify answered questions were implemented.
4. **Feature specs**: `specs/[0-9]*-*/spec.md` — check for feature specs that reference the target system. Verify those features are implemented.

## Ledger Context (Optional)

If `.smith/vault/ledger/` exists and contains non-empty files, load relevant Ledger sections to inform this audit. If the directory is missing, empty, or unreadable, skip silently — the Ledger is purely additive and never required.

1. Check: `ls .smith/vault/ledger/*.md 2>/dev/null`
2. If files exist, read the following sections (higher-confidence entries first, truncate at ~2000 tokens per file):
   - `.smith/vault/ledger/patterns.md` (audit-category entries)
   - `.smith/vault/ledger/antipatterns.md`
3. Use loaded patterns as additional context — look for known issues and successful approaches from past audits. The Ledger informs judgment, it does not override spec/plan/constitution.
4. **Budget violation tracking**: If any Ledger file was truncated (entries were dropped to fit within the ~2000 token budget per file), increment `context_budget_violations` in `.smith/vault/ledger/.meta.json` by 1. If `.meta.json` does not exist, create it from the default template first. This signal tells the reconciliation system that the Ledger is too large for the configured budget.

## Sub-Audit Orchestration

For the selected system(s), launch sub-audits as subagents. Each sub-audit can run in parallel since they examine different aspects:

1. **Requirements** (`smith-audit requirements`) — spec ↔ code ↔ UI alignment
2. **Code Quality** (`smith-audit codequality`) — style, structure, complexity, duplication
3. **Performance** (`smith-audit performance`) — API efficiency, query optimization, rendering
4. **Security** (`smith-audit security`) — OWASP top 10, secrets, auth, dependencies
5. **Accessibility** (`smith-audit accessibility`) — WCAG, keyboard nav, screen readers
6. **UX** (`smith-audit ux`) — Playwright-driven UI testing, latency, responsiveness. Attempts MCP-first authenticated bridge-mode verification when tools are present, `mcp_mode` resolves to `extension`, and the session is interactive (see CLAUDE.md's "MCP-First Browser Verification" section); otherwise falls back silently to the unauthenticated approach below, unchanged
7. **Dependencies** (`smith-audit dependencies`) — outdated packages, CVEs, unused deps, and license-policy violations. Runs whole-project, not diff-scoped — the same underlying design choice as `smith-build`'s Phase 3.7 Supply-Chain Review Pass, not a coincidence, since this sub-audit's own on-demand model was always whole-system; MCP-independent (no browser/bridge-mode dependency, unlike items 6/10 above). Invokes the identical `detect-scanners.sh` (presence-detection, nine tools), `dependency-scan.py` (Sub-layer D: CVE scan — `osv-scanner`/`trivy` preferred whole-repo, else per-manifest `npm audit`/`pip-audit` fallback), and `license-inventory.py` (Sub-layer L: license inventory + `supply_chain.license_policy.deny` evaluation) — transitively `_manifest_discovery.py` — that Phase 3.7 uses; no separate or duplicated implementation exists here
8. **Infrastructure** (`smith-audit infrastructure`) — Docker, health, configs, monitoring
9. **Workflow** (`smith-audit workflow`) — open PRs, unmerged branches, incomplete tasks, stale work
10. **SEO** (`smith-audit seo`) — Playwright-driven technical SEO audit via sitemap crawling (meta tags, headings, schema, performance, crawlability). Same MCP-first-with-fallback contract as the UX sub-audit above (item 6): attempt authenticated bridge-mode verification under the same three conditions, otherwise fall back to the unauthenticated crawl unchanged
11. **Feature** (`smith-audit feature`) — End-to-end deep audit of a single feature: data flow tracing, concurrency/race condition analysis, data integrity spot-checks, error handling gaps, and real-world output validation. Includes user interview phase.

## Report Generation

### Per-System Report
After all sub-audits complete, generate a unified report at:
```
specs/system-XX-<name>/audits/<YYYY-MM-DD>-full.md
```

When `--scheduled` is present, substitute the stem `<YYYY-MM-DD>-scheduled-<name>` for `<YYYY-MM-DD>-full` — `<name>` here is the validated subset list from Phase 0, hyphen-joined in configured order (e.g. `requirements-codequality-security-dependencies-workflow`), not the system name. Directory placement is unchanged (`specs/system-XX-<name>/audits/` either way) — only the filename stem changes. FR-13.

Structure:
```markdown
# Audit Report: [System Name]

**Date**: YYYY-MM-DD
**System**: [system identifier]
**Auditor**: Claude Code (automated)

<!-- --scheduled only: when a prior scheduled report resolves, the "Drift Since Last Scheduled Audit" section (see below) is inserted here, before Executive Summary. Omitted entirely otherwise — never rendered empty. -->

## Executive Summary

| Category | Critical | Warning | Info | Score |
|----------|----------|---------|------|-------|
| Requirements | 0 | 2 | 5 | 85/100 |
| Code Quality | 1 | 3 | 8 | 72/100 |
| Performance | 0 | 1 | 3 | 90/100 |
| Security | 0 | 0 | 2 | 95/100 |
| Accessibility | 2 | 4 | 1 | 60/100 |
| UX | 0 | 1 | 2 | 88/100 |
| Dependencies | 0 | 5 | 3 | 78/100 |
| Infrastructure | 0 | 0 | 1 | 98/100 |
| Workflow | 0 | 3 | 5 | 80/100 |
| SEO | 0 | 4 | 6 | 82/100 |
| **Overall** | **3** | **23** | **36** | **80/100** |

## Unresolved Questions

[List any questions.md entries with blank Answer fields for this system]

## Critical Issues (Must Fix)

[Ranked by severity]

## Warnings (Should Fix)

[Ranked by impact]

## Informational (Nice to Have)

[Lower priority improvements]

## Documentation Gaps

[Specs that don't match code, undocumented features, stale session decisions]

## File Size Audit

Hygiene check for oversized source files in scope for this system. Counts
sourced from `.smith/index/files/` `.meta` files when available, otherwise
computed live via `wc -l`.

**Source extensions in scope:** `.py`, `.js`, `.jsx`, `.ts`, `.tsx`, `.css`,
`.html`, `.sh`. Excludes paths matching `vendor/`, `node_modules/`, `.venv/`,
`dist/`, `build/`, `.smith/`.

### Thresholds

| Threshold | Count |
|-----------|-------|
| Files over 300 lines | N |
| Files over 500 lines | N |

### Top 10 Largest Files

| Rank | File | Lines | Note |
|------|------|-------|------|
| 1 | `path/to/file.py` | 1,250 | Consider decomposing — exceeds 500-line threshold |
| 2 | `path/to/other.js` | 870 | Consider decomposing — exceeds 500-line threshold |
| 3 | `path/to/third.ts` | 412 | — |
| ... | | | |

For each file >500 lines, include a one-line decomposition suggestion in the
Note column (e.g., "Split route handlers into separate module" or "Extract
data-access layer"). Files between 300 and 500 lines are listed without a
decomposition suggestion — they are a flag, not a directive.

### Detection Procedure

```bash
# Prefer manifest metadata if available
if [ -d .smith/index/files ]; then
  # Extract lines from .meta files (format: "lines: <N>")
  ...
else
  # Fallback: live scan
  find . -type f \
    \( -name '*.py' -o -name '*.js' -o -name '*.jsx' -o -name '*.ts' \
       -o -name '*.tsx' -o -name '*.css' -o -name '*.html' -o -name '*.sh' \) \
    -not -path '*/vendor/*' \
    -not -path '*/node_modules/*' \
    -not -path '*/.venv/*' \
    -not -path '*/dist/*' \
    -not -path '*/build/*' \
    -not -path '*/.smith/*' \
    -exec wc -l {} + | sort -rn | head -10
fi
```

This subsection is advisory — it never blocks an audit pass/fail score.

## Detailed Sub-Audit Reports

See individual reports:
- [Requirements](audits/YYYY-MM-DD-requirements.md)
- [Code Quality](audits/YYYY-MM-DD-codequality.md)
- ...
```

### Drift Since Last Scheduled Audit (`--scheduled` only)

When `--scheduled` is present, before writing the Executive Summary, check whether a prior scheduled report is resolvable:

1. Read `.smith/vault/.scheduled-audits-state.json`'s `last_run.report_path`. An absent state file, a state file that fails to parse as JSON, or a `report_path` that does not point at a readable file are all treated identically as "no prior report" — never as an error. FR-22.
2. When no prior report resolves, omit the `## Drift Since Last Scheduled Audit` section entirely from the new report — never rendered empty, never with placeholder text. This is the expected, non-error path for a project's first-ever scheduled run, or when the previously recorded report has since been moved or deleted. FR-15, US-6.
3. When a prior report DOES resolve, parse its `## Executive Summary` table (`Category | Critical | Warning | Info | Score` rows) and write a `## Drift Since Last Scheduled Audit` section into the new report, positioned immediately after the report's header block (Date/System/Auditor) and before `## Executive Summary` (see the placeholder comment in the Structure template above):

```markdown
## Drift Since Last Scheduled Audit
**Previous scheduled report:** specs/audits/2026-09-07-scheduled-requirements-codequality-security-dependencies-workflow.md (2026-09-07)

| Category | Critical Δ | Warning Δ | Info Δ |
|---|---|---|---|
| Requirements | +0 | +2 (new) | -1 (resolved) |
| Security | -2 (resolved) | +2 (new) | +0 |
| Accessibility | not compared — subset not run in both audits | | |
| **Overall** | -2 (resolved) | +4 (new) | -1 (resolved) |
```

One row per category present in EITHER report. A delta is annotated `(new)` when the count increased and `(resolved)` when it decreased; an unchanged (`+0`) delta carries no annotation. A category present in only one of the two reports (a subset that wasn't run this time, or wasn't run last time) is disclosed as `not compared — subset not run in both audits` — never rendered as a false `0`, which would misleadingly imply the category was checked and found clean. FR-14, US-5.

### Full-Spectrum Report (--all mode)
Generate a global summary at:
```
specs/audits/<YYYY-MM-DD>-full-spectrum.md
```

When `--scheduled` is present, substitute the stem `<YYYY-MM-DD>-scheduled-<name>` for `<YYYY-MM-DD>-full-spectrum` — `<name>` is the validated subset list from Phase 0, hyphen-joined in configured order (e.g. `requirements-codequality-security-dependencies-workflow`). Directory placement is unchanged (`specs/audits/` either way) — only the filename stem changes. The Drift block above applies identically to this report shape when `--scheduled` is present. FR-13.

With per-system scores and cross-system issues (e.g., inconsistent patterns between services, shared dependency conflicts).

### Rolling Log Append (`--scheduled` only)

On successful completion of a `--scheduled` run — after the report (and the Drift block above, when present) is fully written — append exactly one line to `.smith/vault/reports/audits-log.md` (create the file fresh with no header if it doesn't exist yet; never rewrite or truncate existing lines):

```
2026-09-14T02:00:03Z | scheduled | subsets=requirements,codequality,security,dependencies,workflow | report=specs/audits/2026-09-14-scheduled-requirements-codequality-security-dependencies-workflow.md | critical=1 warning=12 info=30
```

Sourced from the new report's own Executive Summary `**Overall**` row: the UTC timestamp of completion, the comma-joined subset list, the report's own path, and its critical/warning/info totals. No gate-marker or gitignore-template change applies to this specific file — `.smith/vault/reports/` is already in `hooks/workflow-gate.sh`'s `SAFE_VAULT_DIRS` exemption list and is already outside the `IGNORED` section of the managed `.gitignore-smith-additions` template, both re-confirmed on disk while planning this feature. FR-16.

### State File Write (`--scheduled` only, write-after-success)

Only after BOTH the report (and Drift block, when applicable) and the Rolling Log Append above have succeeded, write `.smith/vault/.scheduled-audits-state.json` fresh (overwriting whatever was there before):

```json
{
  "last_run": {
    "date": "2026-09-14",
    "timestamp": "2026-09-14T02:00:03Z",
    "subsets": ["requirements", "codequality", "security", "dependencies", "workflow"],
    "report_path": "specs/audits/2026-09-14-scheduled-requirements-codequality-security-dependencies-workflow.md",
    "severity_totals": {"critical": 1, "warning": 12, "info": 30}
  }
}
```

`date` (not `timestamp`) is the field the scheduler's `is_audit_due()` compares against — cadence is calendar-day-granular, never time-of-day-granular. This is a write-after-success contract: never write this file before dispatch, and never write it when the run failed partway — a report-write failure, a Rolling Log Append failure, or a sub-audit crash all leave the PRIOR state file untouched, so the next scheduled run still compares against the last genuinely successful run rather than a half-written one. The scheduler's own audits step confirms success by reading this file back after dispatch — a fresh `timestamp` different from the one recorded before dispatch, a non-empty `report_path`, and a `severity_totals` object all present — never by trusting the dispatched process's exit code alone. FR-21.

**Clearing on completion:** once all of the above (report, Drift block, Rolling Log Append, state-file write) succeeds for a `--scheduled` run — or once the report is written for a plain interactive run — call `clear-active-workflow.sh "$LABEL"` (Phase 0 above) before `/smith-audit` returns control. A failure at any step in Report Generation is logged and ALSO calls `clear-active-workflow.sh "$LABEL"` before returning (Phase 0's documented exit-point list) — never left lingering.

## PDF Report Generation

When `--scheduled` is present, read `scheduled_audits.skip_pdf` from `.smith/config.json` (default `true` when the key or file is absent — matching this pipeline's precedent of not assuming `puppeteer`/`npm` are available or wanted on an unattended nightly run) and skip this entire section when `true`. When `false`, or for a plain interactive run (this gate never applies outside `--scheduled`), PDF generation runs best-effort exactly as it already does — a PDF-generation failure was already non-fatal to report delivery before this feature, and that is unchanged. FR-17.

```bash
SKIP_PDF="true"
if [ -n "$SCHEDULED_MODE" ] && [ -f "$PROJECT_DIR/.smith/config.json" ]; then
    SKIP_PDF=$(python3 -c "import json; d=json.load(open('$PROJECT_DIR/.smith/config.json')); print(str(bool((d.get('scheduled_audits') or {}).get('skip_pdf', True))).lower())" 2>/dev/null || echo "true")
fi
```

After the markdown report is written, generate a professional PDF version for client delivery.

### Setup

1. Copy the canonical PDF generator into the audit output directory:
   ```bash
   cp ~/.claude/skills/smith/scripts/audit-pdf-generator.mjs specs/audits/audit-pdf-generator.mjs
   ```
2. Ensure puppeteer is installed:
   ```bash
   cd specs/audits && ls node_modules/puppeteer 2>/dev/null || (npm init -y --quiet 2>/dev/null && npm install puppeteer --save --quiet)
   ```

### Execution

```bash
cd specs/audits && node audit-pdf-generator.mjs <YYYY-MM-DD>-full-spectrum.md
```

The script auto-detects the report type (full-spectrum, SEO, or sub-audit) from the H1 heading and generates appropriate cover page styling.

### Output

The PDF is written alongside the markdown file (e.g., `specs/audits/2026-03-30-full-spectrum.pdf`). Mention both the `.md` and `.pdf` paths in the final output to the user.

---

## Key Rules

- Active-workflow marker must be created BEFORE any report file is written, for BOTH `--scheduled` and plain interactive invocations, and must be cleared via `clear-active-workflow.sh` at every exit path (normal completion, a sub-audit crash, or a report/drift/log-write failure) — a lingering marker is never an acceptable outcome (see "Phase 0: Scheduled Mode & Marker Bootstrap")
- Always create the `audits/` directory inside the system spec folder before writing reports
- Each sub-audit runs as a subagent to preserve context
- Sub-audits can run in parallel (they're read-only)
- Never modify code during an audit — audits are read-only and produce reports only
- Score each category 0-100 based on findings (critical = -20, warning = -5, info = -1)
- Flag any `questions.md` with unanswered questions as a documentation gap
