---
name: smith-debug
description: Diagnostic workflow that systematically gathers evidence, identifies root causes, and produces a structured debug report. Read-only — does not modify code. Output feeds into /smith-bugfix if a fix is needed.
---

# SpecKit Debug Workflow

A diagnostic-only workflow that systematically investigates errors, failures, and unexpected behavior across Armory's services. Produces a structured debug report stored in the relevant system's `.specify/` folder. Does NOT modify code — the report becomes input to `/smith-bugfix` if a fix is warranted.

**Arguments:** $ARGUMENTS

## Vault Logging

Throughout this action, log significant events to the vault session log. Read the session log path from `.smith/vault/.current-session`. If the file is missing or the vault is not initialized, skip all logging silently.

Append entries using this format:

```
### [HH:MM:SS] /smith-debug <event>

**User Request:**
> <verbatim user message that triggered this action — capture the exact error description, symptoms, or question the user asked. Include any error messages they pasted.>

**Synthesized Input:** <brief summary of what's being investigated>
**Outcome:** <what happened>
**Artifacts:** <files created/modified>
**Systems affected:** <system IDs>
```

Log at these points:
1. **On invocation** — capture the verbatim user request AND the structured symptom description
2. **After symptom capture** — structured fields extracted
3. **After triage** — sub-agent findings summary
4. **After diagnosis** — root cause identified or hypotheses ranked
5. **On completion** — report path, user decision (bugfix/investigate/close)

## Subagent Invocation Logging

Immediately before every Agent tool call in this workflow (especially the 4 triage agents in Phase 3), append a block to the session log. The Agent tool's return value does not expose `subagent_type` or `model` to the parent, so this is the only place that information can be captured.

```
### [HH:MM:SS] Subagent invoked: <description>

**Type:** <subagent_type or "general">
**Model:** <model override passed to Agent, or "inherited" if none>
```

After the Agent tool returns, the `subagent-vault-writeback.sh` hook automatically appends a matching "Subagent completed" block with metrics read from the sidechain transcript — do not duplicate that logging in the skill.

## When to Use This

Use `/smith-debug` when:
- An error message or unexpected behavior needs investigation
- You're not sure what's broken or why
- Multiple services could be involved
- You want evidence before committing to a fix

Do NOT use when:
- The cause is already known and the fix is obvious — use `/smith-bugfix` directly
- You're building a new feature — use `/smith-new`

## Natural Language Triggers

If the user says any of the following (or similar phrases), treat it as invoking this command:
- "debug this"
- "help me debug..."
- "can you investigate..."
- "I'm getting this error..."
- "why is X failing"
- "something is broken"
- "help me figure out why..."

When triggered by natural language, synthesize the conversation history into the symptom description and proceed as if that was passed as `$ARGUMENTS`.

## Phase 1: Symptom Capture (Interactive if needed)

Extract or ask for these structured fields from the user's description:

| Field | Description | Example |
|-------|-------------|---------|
| **Error message** | Exact text of error or unexpected output | `[Errno 111] Connection refused` |
| **Trigger** | What the user was doing when it happened | Running background reports |
| **Conditions** | What else was running, recent changes, environment state | Sentiment analysis running concurrently |
| **Frequency** | Always, sometimes, new, intermittent | Every time background reports run |
| **Affected service(s)** | Best guess from the symptom | content-engine, sentiment-engine |

### Interactive prompting

If the user's initial description is missing 2+ of these fields, ask a focused set of clarifying questions BEFORE proceeding. Present them as a numbered list the user can answer quickly:

```
To investigate this efficiently, I need a few more details:

[1] What exactly were you doing when this happened? (e.g., which button, command, or workflow)
[2] Does this happen every time, or only sometimes?
[3] Were any other operations running at the same time?
[4] When did this start? (always been this way, or recent change?)
```

Only ask for what's actually missing. If the description already covers 3+ fields, proceed directly — don't slow the user down with unnecessary questions.

**If ALL fields are present** in the initial description or `$ARGUMENTS`: skip prompting entirely and proceed to Phase 2.

## Phase 2: System Detection

Determine which Armory system(s) this debug session relates to.

1. **Map the symptom to systems** using service-to-system mapping:
   - `command-center` / port 8080 → `system-15-command-center`
   - `sentiment-engine` / port 8081 → `system-15-command-center` (scoring subsystem)
   - `content-strategy` / port 8082 → `system-12-content-social-engine`
   - `email-pipeline` → `system-03-email-archive-contact-graph`
   - `communication-triage` → `system-05-communication-triage`
   - `voice-training` → `system-04-personal-voice`
   - `openclaw` / Jason / port 18789 → cross-system (agent layer)
   - `social-listening` → `system-10-social-listening`
   - `trend-intelligence` → `system-13-trend-intelligence`
   - `n8n` / port 5678 → `system-01-infrastructure`
   - `postgres` / `neo4j` / `qdrant` / `redis` → `system-01-infrastructure`
   - Docker / Colima / networking → `system-01-infrastructure`
   - Ollama / model loading → `system-02-ai-models-layer`

2. **If ambiguous**: pick the most likely primary system and note secondary systems.

3. **Set the report path**:
   ```
   .specify/systems/<primary-system>/debug/debug-YYYY-MM-DD-<slug>.md
   ```
   Create the `debug/` directory if it doesn't exist.

## Phase 3: Automated Triage (Parallel Sub-agents)

Launch up to 4 diagnostic sub-agents in parallel. Each is **read-only** — no code modifications.

### 3.1 Infrastructure Health Agent
**Model:** haiku
**Task:** Check the health of all services and resource usage.
```
- Run: docker compose ps
- Run: bash scripts/health-check.sh
- Run: docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}"
- Check if affected service(s) are running and healthy
- Check port availability for affected services
- Check Colima resource allocation: colima status
- Report: which services are up/down, resource pressure, port conflicts
```

### 3.2 Log Analysis Agent
**Model:** haiku
**Task:** Search service logs for the error and surrounding context.
```
- Run: docker compose logs <affected-service> --tail 200 --timestamps
- Run: docker compose logs <upstream-dependencies> --tail 100 --timestamps
- Grep logs for the exact error message
- Grep for related patterns (connection refused, timeout, OOM, restart)
- Look for temporal correlation with other service errors
- Report: relevant log excerpts, error frequency, first occurrence timestamp
```

### 3.3 Dependency Trace Agent
**Model:** sonnet
**Task:** Map the request path and check each hop.
```
- Identify the full request chain for the failing operation
  (e.g., UI → Express → FastAPI → Ollama → Qdrant)
- For each hop:
  - Is the upstream service reachable? (curl health endpoints)
  - Is the connection using the right host/port?
  - Are there resource contention issues? (shared Ollama, shared PG connections)
- Check docker-compose.yml for network configuration
- Check environment variables for correct service URLs
- Report: which hop fails, why, and what the expected vs actual behavior is
```

### 3.4 Spec & History Cross-Reference Agent
**Model:** haiku
**Task:** Check if this is a known issue or related to recent changes.
```
- Read the primary system spec.md for known limitations or caveats
- Search specs/debug/ and .specify/systems/*/debug/ for prior debug reports with similar symptoms
- Run: git log --oneline -20 -- <affected-service-paths>
- Check if recent commits could have introduced the issue
- Search GitHub issues: gh issue list --search "<error keywords>" --limit 5
- Report: prior occurrences, related changes, known issues
```

### Sub-agent Selection

Not all 4 agents are always needed. Select based on symptom:

| Symptom type | Agents to launch |
|-------------|-----------------|
| Connection refused / timeout | All 4 |
| Wrong data / unexpected output | 3.2 (logs) + 3.3 (trace) + 3.4 (history) |
| Slow performance | 3.1 (health) + 3.2 (logs) + 3.3 (trace) |
| Service won't start | 3.1 (health) + 3.2 (logs) |
| Intermittent failure | All 4 |
| UI rendering issue | 3.2 (logs) + 3.4 (history) |

## Phase 4: Diagnosis Synthesis

After sub-agents return, synthesize findings into a root cause analysis:

1. **Correlate evidence** across agents — look for consistent signals
2. **Rank hypotheses** by evidence strength:
   - **Confirmed**: Direct evidence from logs + reproduction
   - **Probable**: Strong circumstantial evidence (e.g., resource contention + timing)
   - **Possible**: Consistent with symptoms but lacking direct proof
3. **Apply cognitive guards** (from debugging principles):
   - Actively seek evidence that contradicts the leading theory
   - Match the fix to the cause, not to how scary the error looks
   - If you haven't checked "is the service running?", don't recommend code changes

## Phase 5: Write Debug Report

Write the report to the path determined in Phase 2:

```markdown
---
reported: YYYY-MM-DD
status: diagnosed | needs-investigation | cannot-reproduce
severity: blocking | degraded | cosmetic
primary_system: <system-folder-name>
also_affects:
  - <other-system-folder-name>
trigger: <what the user was doing>
error: <exact error text>
---

# Debug: <short description>

## Symptom
<Structured description from Phase 1>

## Evidence

### Infrastructure Health
<Agent 3.1 findings — service status, resource usage, port checks>

### Log Analysis
<Agent 3.2 findings — relevant log excerpts, error patterns>

### Dependency Trace
<Agent 3.3 findings — request path analysis, failing hop>

### Spec & History
<Agent 3.4 findings — prior occurrences, recent changes>

## Root Cause
<Identified cause OR ranked hypotheses with evidence for each>

### Confidence: <confirmed | probable | possible>
<Reasoning for the confidence level>

## Recommended Action
- [ ] **Fix via `/smith-bugfix`** — <one-liner description of the fix>
- [ ] **Config change** — <what to change and where>
- [ ] **Known limitation** — <document and accept>
- [ ] **Needs deeper investigation** — <what to investigate next>

## Related
- <links to relevant specs, issues, prior debug reports>
```

## Phase 6: Decision Gate

Present the diagnosis summary to the user and ask:

```
## Diagnosis Complete

**Root cause:** <one-sentence summary>
**Confidence:** <confirmed/probable/possible>
**Report saved:** .specify/systems/<system>/debug/debug-YYYY-MM-DD-<slug>.md

Would you like me to:
[1] Fix it — kick off /smith-bugfix with this diagnosis as context
[2] Investigate deeper — drill into <specific hypothesis or area>
[3] Close — the report is enough for now
```

### If user selects [1] (Fix it):
- Invoke `/smith-bugfix` with the diagnosis context:
  - Pass the root cause, affected files, and recommended fix from the debug report
  - The bugfix workflow will reference the debug report in its spec cross-reference phase
  - The debug report's status updates to `fix-in-progress`

### If user selects [2] (Investigate deeper):
- Ask what specific area to investigate
- Re-run the relevant sub-agent(s) with a more targeted scope
- Append findings to the existing debug report under a new `## Follow-up Investigation` section
- Return to the decision gate

### If user selects [3] (Close):
- Update the debug report status to `closed` or `documented`
- Log the diagnosis summary (root cause and confidence level) as a regular event entry in the session log
- The general workflow summary (duration, tokens, tool calls, subagent totals, files changed) is emitted automatically by the `workflow-summary.sh` Stop hook once the active-workflow file is cleaned up — do not duplicate it
- Log completion to vault

## Key Rules

- **Read-only**: This workflow NEVER modifies application code, configs, or Docker services
- **No premature fixes**: Gather evidence first, diagnose second, fix third (via bugfix handoff)
- **Cheapest test first**: Check if the service is running before analyzing code paths
- **Parallel where possible**: Launch sub-agents concurrently to minimize wall-clock time
- **Preserve evidence**: Log excerpts and findings go in the report, not just conclusions
- **Cognitive guards**: Actively fight anchoring bias — the first theory isn't always right
- **System-scoped storage**: Debug reports live alongside their system's specs, not in a global folder
