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

## System Selection

### If `$ARGUMENTS` contains `--all`:
- Run audits across ALL systems (full-spectrum mode)
- Reports go to individual system folders + a global summary at `specs/audits/<date>-full-spectrum.md`
- Use subagents per system to manage context

### If `$ARGUMENTS` contains a system identifier (e.g., `system-15`, `command-center`, `014`):
- Match it to the correct system spec directory
- Run all sub-audits on that system only

### If `$ARGUMENTS` is empty:
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
6. **UX** (`smith-audit ux`) — Playwright-driven UI testing, latency, responsiveness
7. **Dependencies** (`smith-audit dependencies`) — outdated packages, CVEs, unused deps
8. **Infrastructure** (`smith-audit infrastructure`) — Docker, health, configs, monitoring
9. **Workflow** (`smith-audit workflow`) — open PRs, unmerged branches, incomplete tasks, stale work
10. **SEO** (`smith-audit seo`) — Playwright-driven technical SEO audit via sitemap crawling (meta tags, headings, schema, performance, crawlability)
11. **Feature** (`smith-audit feature`) — End-to-end deep audit of a single feature: data flow tracing, concurrency/race condition analysis, data integrity spot-checks, error handling gaps, and real-world output validation. Includes user interview phase.

## Report Generation

### Per-System Report
After all sub-audits complete, generate a unified report at:
```
specs/system-XX-<name>/audits/<YYYY-MM-DD>-full.md
```

Structure:
```markdown
# Audit Report: [System Name]

**Date**: YYYY-MM-DD
**System**: [system identifier]
**Auditor**: Claude Code (automated)

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

## Detailed Sub-Audit Reports

See individual reports:
- [Requirements](audits/YYYY-MM-DD-requirements.md)
- [Code Quality](audits/YYYY-MM-DD-codequality.md)
- ...
```

### Full-Spectrum Report (--all mode)
Generate a global summary at:
```
specs/audits/<YYYY-MM-DD>-full-spectrum.md
```

With per-system scores and cross-system issues (e.g., inconsistent patterns between services, shared dependency conflicts).

## PDF Report Generation

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

- Always create the `audits/` directory inside the system spec folder before writing reports
- Each sub-audit runs as a subagent to preserve context
- Sub-audits can run in parallel (they're read-only)
- Never modify code during an audit — audits are read-only and produce reports only
- Score each category 0-100 based on findings (critical = -20, warning = -5, info = -1)
- Flag any `questions.md` with unanswered questions as a documentation gap
