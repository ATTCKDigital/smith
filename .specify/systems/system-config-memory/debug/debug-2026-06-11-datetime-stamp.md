---
reported: 2026-06-11
status: diagnosed
severity: cosmetic
primary_system: system-config-memory
also_affects: []
trigger: Comparing per-response datetime+branch stamp behavior across two projects
error: "Stamp appears on goldcanna-inventory but not gold-canna-theme-uk"
---

# Debug: datetime + branch stamp appears on one project but not another

## Symptom
On `~/Projects/goldcanna-inventory`, every assistant response ends with a stamp
like `2026-06-11 17:48:30 — main`. On `~/Projects/gold-canna-theme-uk`, the same
stamp does not reliably appear. User asked which **memory file** holds the
instruction and how the two projects' memory files differ.

## Root Cause

**The stamp is NOT defined in any per-project memory file.** It is a *global*
rule enforced by a *global* hook:

1. **Source of the instruction** — `~/.claude/CLAUDE.md`, **Rule 6: General
   Preferences [Weight: 8]**, line 183:
   > "The response ends with a datetime stamp formatted as
   > `YYYY-MM-DD HH:MM:SS — <branch-name>`"

2. **Enforcement mechanism** — `~/.claude/settings.json` registers a global
   `Stop` hook → `~/.claude/hooks/grade-response.sh`. That hook feeds the
   entire `~/.claude/CLAUDE.md` rubric to a Haiku critic; if the turn scores
   < 100 (e.g. stamp missing) it exits 2 and forces a regeneration, up to 3
   retries. This is what makes the stamp "stick."

Both of these are **global and identical for every project** — neither
project has a CLAUDE.md, settings.json, or memory file that mentions the stamp
(`grep` for datetime/stamp/branch in both project CLAUDE.md files = no match).

## Evidence

### Config comparison
| | goldcanna-inventory | gold-canna-theme-uk |
|---|---|---|
| Project `CLAUDE.md` | 38 KB, no stamp ref | 10 KB, no stamp ref |
| `.claude/settings.json` hooks | **full block** (UserPromptSubmit, PreToolUse, SessionStart, PostToolUse, SubagentStop, **Stop→session-end-review.sh**) | **none** (permissions only) |
| `.claude/hooks/` dir | present (8 scripts) | absent |
| `.claude/agent-memory/` | present (5 agent MEMORY.md files) | **absent** |
| `settings.local.json` | none | none |
| git branch | `main` | `develop` |

### Global (shared by both)
- `~/.claude/CLAUDE.md` Rule 6 — the stamp instruction. ✅ present.
- `~/.claude/settings.json` `Stop` hooks include `grade-response.sh`. ✅ present.
- `grade-response.sh` is executable; `claude` CLI is on PATH. ✅ functional.
- No leftover `/tmp/claude-grade-retry-*` state. ✅ clean.

## Why the observed difference

Claude Code **merges** project `settings.json` hooks with global hooks — it
does not replace them. So `grade-response.sh` is wired to fire in *both*
projects. The stamp instruction and its enforcer are global and would apply
to both.

The real differentiators are environmental, not a "missing memory file":

1. **`grade-response.sh` is best-effort, not deterministic.** It calls a Haiku
   critic and, on any parse failure or timeout, defaults to `total=100`
   (pass) and lets the turn through *without* a stamp. The hook also caps at
   3 retries then passes regardless. So a turn can legitimately end with no
   stamp on either project — it is enforced probabilistically.

2. **goldcanna-inventory's local `.claude` ecosystem reinforces the behavior.**
   It carries the full Smith hook suite and `.claude/agent-memory/`; that rich
   project scaffolding (and its larger, rule-laden CLAUDE.md) keeps the model
   in "compliance" framing. gold-canna-theme-uk is a bare Shopify-theme
   project with a permissions-only settings.json, no hooks dir, no agent-memory
   — nothing locally reinforces Rule 6, so when the global critic misses
   (timeout / non-100 parse / retry-exhaustion) the stamp silently drops.

3. **Not a memory-file difference at all.** The only memory-shaped artifacts
   that differ are `.claude/agent-memory/*/MEMORY.md` (present in goldcanna,
   absent in theme-uk), and none of those mention the stamp.

### Confidence: confirmed (source) / probable (frequency mechanism)
The *location* of the instruction (global Rule 6 + global grade-response.sh)
is confirmed by direct file inspection. The *reason it appears less often* on
theme-uk is probable: it rests on the best-effort/fail-open nature of the
critic hook plus the absence of local reinforcement, rather than any config
that actively disables the stamp.

## Recommended Action
- [ ] **Known limitation** — The stamp is globally enforced but fail-open;
      expect occasional misses on any project, more visibly on minimal
      projects with no local hook scaffolding.
- [ ] **Config change (optional)** — If a deterministic stamp is wanted, add a
      dedicated `Stop` hook that *appends* the stamp directly (string
      manipulation) instead of relying on the Haiku critic to force a retry.
      That removes the fail-open gap entirely and is project-portable.

## Related
- `~/.claude/CLAUDE.md` Rule 6 (line 183)
- `~/.claude/settings.json` Stop hooks
- `~/.claude/hooks/grade-response.sh`
