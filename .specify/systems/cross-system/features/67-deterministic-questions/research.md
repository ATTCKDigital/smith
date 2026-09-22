# Research: Deterministic Question-Asking Mechanism

## R-1: How PreToolUse hooks deny a tool call in this repo

**Decision:** Reuse the existing deny JSON contract.

**Evidence:**
- `hooks/security-guard-bash.sh` deny branch emits
  `{"hookSpecificOutput":{"permissionDecision":"deny","permissionDecisionReason":"SMITH SECURITY: …"}}`
  and `exit 2`. It also has a **warn-only** branch emitting
  `{"hookSpecificOutput":{"additionalContext":"SMITH SECURITY WARNING …"}}` then `exit 0`.
- `hooks/workflow-gate.sh` `deny()` emits the same `permissionDecision: deny`
  JSON via a python3 heredoc (falling back to a static heredoc) and `exit 0`.

**Conclusion:** A new hook can deny `AskUserQuestion` with the identical shape.
The `permissionDecisionReason` is surfaced to the model (per existing usage),
so the deny doubles as a redirect. Warn mode reuses the `additionalContext`
shape. No new harness capability required.

## R-2: How a hook detects the active tool + reads config/state

**Decision:** Parse stdin JSON with `python3`; locate `.smith/config.json`
relative to CWD like sibling hooks.

**Evidence:** `security-guard-bash.sh` reads `json.load(sys.stdin)` to get the
tool input; `workflow-gate.sh` extracts `TOOL_NAME` via python3 from stdin and
checks `.smith/vault/active-workflows/` for markers. The tool name for the
popup is `AskUserQuestion`.

**Conclusion:** Hook flow: read stdin → if `tool_name != "AskUserQuestion"` exit 0
→ read `question_gate.mode` from `.smith/config.json` → branch on mode.

## R-3: Config seeding pattern (three-site, non-destructive)

**Decision:** Follow feature 58 FR-20 verbatim as a pattern.

**Evidence:** `templates/config.default.json` holds shipped defaults;
`skills/smith/SKILL.md` seeds keys via python3 heredoc at init;
`skills/smith-update/SKILL.md` seeds keys into existing projects with a
present→no-op / absent→merge / file-absent→leave idiom.

**Conclusion:** Add `question_gate` at all three sites.

## R-4: Skill invocation from within a skill (just-in-time load)

**Decision:** The three gates call the `Skill` tool with `smith-question` at the
presentation step; `smith-question` is a context-loading (inline) skill.

**Rationale:** Presenting questions and collecting answers is interactive
main-thread work. A subagent/background skill cannot drive the user dialogue.
`smith-clarify` and `smith-new` already run inline, so pulling in a shared
inline skill is consistent. Loading it at the gate refreshes the contract in
context precisely when needed (counters instruction decay).

## R-5: Absent-key default — fail-open vs fail-closed

**Decision (recommended, pending Q1):** shipped default `deny`; **absent key on
an existing (un-migrated) project → `off`** (fail-open).

**Rationale:** The hook installs globally to `~/.claude/settings.json` and fires
in every project. If an absent key meant `deny`, installing this feature would
silently start blocking the popup in every pre-existing project before the user
opted in. Fail-open on absent key keeps installed projects stable until they
re-seed (via `/smith-update`), while new projects get `deny` from
`config.default.json`. This is the W1 (enforcement-scope) resolution.

## R-6: Does the critic read rule criteria dynamically? (affects FR-18/OOS-3)

**Open (Q3):** `hooks/grade-response.sh` is the Haiku critic. Need to confirm
during build whether it grades against the rule text in the loaded CLAUDE.md
(so a new sub-criterion is picked up automatically) or against a hardcoded
rubric (which would also need editing). Spec treats the grading engine as
unchanged (OOS-3); if the rubric is hardcoded, add the sub-criterion there too —
a small, localized addition, not an engine change.

## R-7: Placement of the graded sub-criterion (Q2)

**Options:**
- Extend **Rule 1** (Questions ≠ Actions) — but Rule 1 is about not *acting* on
  questions, a different axis than *how we ask*. Weak fit.
- Extend **Rule 2** (skill compliance) — already covers "no batching of
  interactive steps" and pacing; a "present questions via the Q&A contract, never
  AskUserQuestion" criterion fits its "follow the documented interactive process"
  theme. No reweight needed.
- **New dedicated rule** — cleanest semantics but forces reweighting the 100-point
  total across all rules.

**Recommended:** extend **Rule 2** with one binary sub-criterion (no reweight).
Confirm at gate.
