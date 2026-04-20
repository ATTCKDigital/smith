---
name: smith-explore
description: Pre-change exploration — audits codebase for system-wide impacts, identifies touch points, and surfaces conflicts before proceeding with smith-new or other workflows.
argument-hint: "[<feature-description>] [--scope skills|hooks|configs|all] [--deep]"
---

# Smith Explore — Pre-Change Impact Analysis

A diagnostic workflow that audits the codebase for system-wide impacts BEFORE making changes. Identifies all touch points, surfaces conflicts and redundancies, and produces a structured exploration report. Use as the first phase of smith-new or manually before significant changes.

**Arguments:** $ARGUMENTS

## Vault Logging

Throughout this action, log significant events to the vault session log. Read the session log path from `.smith/vault/.current-session`. If the file is missing or the vault is not initialized, skip all logging silently.

Append entries using this format:

```
### [HH:MM:SS] /smith-explore <event>

**User Request:**
> <verbatim user message or feature description that triggered this exploration>

**Synthesized Input:** <brief summary of what's being explored>
**Outcome:** <what was discovered>
**Artifacts:** <files read, patterns found>
**Systems affected:** <system IDs>
```

Log at these points:
1. **On invocation** — capture the verbatim exploration request AND the scope
2. **After each sub-agent completes** — findings summary
3. **After conflict detection** — conflicts found with severity
4. **On completion** — total touch points, conflicts requiring resolution

## When to Use This

Use `/smith-explore` when:
- Starting a new feature that may have cross-system impacts
- Making changes to core infrastructure (skills, hooks, config files)
- Uncertain about the blast radius of a proposed change
- Want to understand existing patterns before adding new ones

This skill is automatically invoked as Phase 0 of `/smith-new` when `--explore` is passed or when the feature touches core Smith infrastructure.

## Phase 1: Scope Detection

Parse `$ARGUMENTS` to determine exploration scope:

| Flag | Scope | What to scan |
|------|-------|--------------|
| `--scope skills` | Smith skills only | `~/.claude/skills/smith-*/**/*.md` |
| `--scope hooks` | Hooks and plugins | `~/.claude/plugins/**/*`, `settings.json` hooks |
| `--scope configs` | Config files only | `constitution.md`, `CLAUDE.md`, `MEMORY.md` |
| `--scope all` | Everything | All of the above |
| (no flag) | Auto-detect | Infer from feature description |

**Auto-detection rules:**
- If description mentions "skill", "workflow", "smith" → scan skills
- If description mentions "hook", "automation", "trigger" → scan hooks
- If description mentions "config", "constitution", "memory", "claude.md" → scan configs
- If description mentions "policy", "rule", "standard" → scan constitution.md
- If unclear → scan all

## Phase 2: Parallel Sub-Agent Investigation

Launch diagnostic sub-agents based on scope. Each sub-agent is **read-only**.

### 2.1 Skills Pattern Agent
**Model:** haiku
**Task:** Scan all Smith skills for patterns related to the exploration target.
```
- Find all skills that write to the target files/systems
- Identify shared patterns (vault logging, workflow phases, etc.)
- Note any skills that might conflict with the proposed change
- Report: skills affected, patterns found, potential conflicts
```

### 2.2 Configuration Files Agent
**Model:** haiku
**Task:** Check configuration files for redundancies and conflicts per File Purpose Policy.
```
- Read constitution.md, CLAUDE.md, MEMORY.md
- Check for existing content that overlaps with proposed change
- Identify redundancies that violate the File Purpose Policy (constitution.md §VI)
- Check for spec drift between files
- Report: redundancies, misplaced content, conflicts with policy
```

### 2.3 Hooks & Automation Agent
**Model:** haiku
**Task:** Identify hooks that might be triggered by or conflict with the change.
```
- Scan ~/.claude/settings.json for relevant hooks
- Check ~/.claude/plugins/ for automation that touches target systems
- Identify any pre/post tool use hooks that might interfere
- Report: hooks affected, automation conflicts, triggering conditions
```

### 2.4 Cross-Reference Agent
**Model:** sonnet
**Task:** Deep analysis of how proposed change interacts with existing systems.
```
- Map the proposed change to affected systems via .specify/systems/*/spec.md
- Check for existing features that overlap or conflict
- Identify architectural implications
- Search for prior debug reports or decisions related to this area
- Report: systems affected, architectural concerns, prior art
```

### Sub-Agent Selection

Not all agents are always needed:

| Exploration type | Agents to launch |
|-----------------|------------------|
| New skill | 2.1 (skills) + 2.3 (hooks) |
| Config file change | 2.2 (config) + 2.4 (cross-ref) |
| Policy change | 2.1 (skills) + 2.2 (config) + 2.4 (cross-ref) |
| New feature | 2.4 (cross-ref) only |
| Full audit | All 4 |

If `--deep` flag is passed, always launch all 4 agents.

## Phase 3: Conflict Detection & Synthesis

After sub-agents return, synthesize findings into a conflict analysis:

1. **Categorize findings by severity:**
   - **BLOCKING**: Must be resolved before proceeding (e.g., policy violation, breaking change)
   - **WARNING**: Should be addressed but can proceed (e.g., redundancy, minor inconsistency)
   - **INFO**: Useful context, no action required (e.g., related features, prior decisions)

2. **Check against File Purpose Policy** (constitution.md §VI):
   - Is the proposed change writing to the correct file?
   - Would it create redundancy with existing content?
   - Does it conflict with the mutually exclusive file purposes?

3. **Apply smith-debug cognitive guards:**
   - Actively seek evidence that contradicts the initial plan
   - Match recommendations to actual findings, not assumed severity
   - Consider cheapest resolution first

## Phase 4: Exploration Report

Write the report to `.smith/vault/explore/explore-YYYY-MM-DD-<slug>.md`:

```markdown
---
explored: YYYY-MM-DD
status: clear | conflicts-found | blocking-issues
scope: skills | hooks | configs | all
feature: <proposed feature or change>
---

# Exploration: <short description>

## Proposed Change
<Description of what's being explored/proposed>

## Scope
<What was scanned and why>

## Findings

### Skills Patterns
<Agent 2.1 findings — affected skills, shared patterns, conflicts>

### Configuration Files
<Agent 2.2 findings — redundancies, policy violations, misplaced content>

### Hooks & Automation
<Agent 2.3 findings — affected hooks, automation conflicts>

### Cross-System Analysis
<Agent 2.4 findings — systems affected, architectural concerns>

## Conflicts

### BLOCKING
- [ ] <conflict description> — **Resolution required before proceeding**

### WARNING
- [ ] <issue description> — **Recommended to address**

### INFO
- <context or related information>

## Recommendations

<Suggested approach based on findings>

## Proceed?

Based on this exploration:
- [ ] **Clear to proceed** — no blocking issues
- [ ] **Proceed with caution** — warnings to address
- [ ] **Do not proceed** — blocking issues require resolution first
```

## Phase 5: Decision Gate

Present the exploration summary to the user:

```
## Exploration Complete

**Proposed:** <one-sentence summary>
**Status:** <clear | warnings | blocking>
**Report saved:** .smith/vault/explore/explore-YYYY-MM-DD-<slug>.md

### Findings Summary
- Skills affected: N
- Config conflicts: N
- Hooks impacted: N
- Systems touched: N

### Issues Found
- BLOCKING: N (must resolve)
- WARNING: N (should address)
- INFO: N (context only)

Would you like to:
[1] Proceed — continue to smith-new with this context
[2] Resolve conflicts — address blocking/warning issues first
[3] Explore deeper — run additional analysis on specific areas
[4] Abort — stop and review findings manually
```

### If invoked from smith-new:
- If status is `clear`: return findings and continue workflow
- If status is `conflicts-found` (warnings only): present summary, ask to proceed or resolve
- If status is `blocking-issues`: STOP, present issues, require resolution before continuing

### If invoked standalone:
- Always present decision gate
- Allow user to choose next action

## Key Rules

- **Read-only**: This workflow NEVER modifies code, configs, or skills
- **Policy-aware**: Always check findings against constitution.md §VI (File Purpose Policy)
- **Parallel investigation**: Launch sub-agents concurrently to minimize wall-clock time
- **Cognitive guards**: Fight confirmation bias — actively look for reasons NOT to proceed
- **Preserve context**: Log all findings for later reference, even if user proceeds
- **Smith-debug framing**: Present conflicts clearly with severity, not just a pass/fail
