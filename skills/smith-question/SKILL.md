---
name: smith-question
description: The canonical contract for asking the user a decision question — the markdown Q&A format (Context → Options with pros/cons → Recommended + reasoning → one at a time), the response grammar, and the persisted questions.md shape. Invoked just-in-time by any Smith gate that presents questions (smith-new, smith-clarify, smith init). Never uses the interactive AskUserQuestion popup.
---

# Smith Question Contract

This skill is the **single source of truth** for how Smith asks the user a
decision question and processes the answer. Any Smith workflow that reaches a
point where it must ask the user to choose between options invokes this skill at
that moment so the contract is fresh in context, then follows it verbatim.

It does **not** generate questions — the calling workflow supplies the questions
(from plan artifacts, spec ambiguities, an intake template, etc.). This skill
defines only the **presentation, pacing, and answer-handling** contract.

## Hard rule: never use the interactive popup

**Do NOT use the `AskUserQuestion` tool (the interactive multiple-choice popup)
to present these questions.** Questions are presented as **markdown text** per
the contract below. This is enforced by the `question-gate-guard.sh` PreToolUse
hook (config `question_gate.mode`) and by a graded rule in the CLAUDE.md rule
set; this skill states it so the contract is self-reinforcing in context.

Rationale: the markdown contract shows the full Context, every option's
tradeoffs, and the recommendation with its reasoning — and leaves a durable,
reviewable record. The popup hides that reasoning and leaves nothing behind.

## Presentation contract

Present **exactly one question at a time**. For each question, render:

```
## Question [N] of [Total]: [Short topic]

**Context:** [Quote or summarize the spec/plan/code that raises this question —
why it is being asked and what it affects.]

**Question:** [The specific decision, phrased so an option letter answers it.]

**Options:**

| Option | Description | Implications |
|--------|-------------|--------------|
| A | [first option] | [pros: … / cons: … — effort, risk, tradeoffs] |
| B | [second option] | [pros: … / cons: …] |
| C | [third option] | [pros: … / cons: …] |

**Recommended:** [Option letter] — [Clear reasoning for why this is the best
choice given the context.]

Reply with an option letter (e.g. "A"), "yes" to accept the recommendation,
"skip" to defer, or type your own answer.
```

Rules:
- Every question has **at least two options**, each with real tradeoffs.
- Every question has a **Recommended** option **with reasoning** — never a bare
  letter.
- Order questions by impact (highest-impact first).
- Do **not** ask about matters with an obvious default or a clear best practice.
- After presenting a question, **stop and wait** for the user's reply. Do not
  present the next question, and do not begin implementation, until the current
  question is answered.

## Response grammar

When the user replies, interpret it as:

| Reply | Meaning |
|-------|---------|
| `yes` / `recommended` / `rec` | Use the recommended option. |
| An option letter (`A`, `B`, `C`, …) | Use that option. |
| `skip` | Defer — record `SKIPPED — needs follow-up`. |
| `done` | Stop asking; mark all remaining questions `SKIPPED`. |
| Anything else | Accept it verbatim as a custom answer. |

If a reply is ambiguous, ask one brief disambiguation before advancing (it still
belongs to the same question — do not count it as a new question).

## After each answer

1. **Record the answer immediately** — if the gate persists answers, write the
   chosen answer into the question's `**Answer:**` field in `questions.md` (see
   format below) before moving on. This makes the flow resumable: an interrupted
   session leaves answered questions filled in and unanswered ones blank.
2. **Confirm and advance** — e.g. `Saved: Q[N] → [brief answer]. ([remaining] remaining)`.
3. Present the next unanswered question.

## After all questions

1. Display an answers **summary table** (`# | Topic | Answer`).
2. Ask: *"Would you like to change any answers? Reply with a question number to
   revise, or 'looks good' to continue."* Revise on request.
3. Update the persisted file's status header from `AWAITING ANSWERS` to
   `ANSWERED` (or `PARTIALLY ANSWERED` if any were skipped).

## Persisted `questions.md` format

Gates that persist answers (smith-new, smith-clarify) use this file shape. This
is the canonical definition — other skills reference it rather than restating it.

```markdown
# Implementation Questions: [Feature Name]

**Generated**: [DATE]
**Feature**: [link to spec.md]
**Plan**: [link to plan.md]
**Status**: AWAITING ANSWERS

---

## Q1: [Topic]

**Context**: [Quote the spec/plan/research section that raises this question]

**Question**: [Specific decision]

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | [first option] | [tradeoffs, effort, risk] |
| B | [second option] | [tradeoffs, effort, risk] |

**Recommended**: [A/B] — [reasoning]

**Answer**: ___

---

[repeat for all questions]
```

- `**Answer**: ___` is the blank field, filled in as each question is answered.
- The `Status` header moves `AWAITING ANSWERS` → `ANSWERED` when complete.

## Invocation

- **From a workflow**: invoke `smith-question` at the step where the gate begins
  presenting questions, then follow the contract above. Keep only your
  gate-specific concerns in your own SKILL.md (e.g. where `questions.md` lives,
  how questions are generated, the ≤5-question budget, an intake template's
  navigation) — do not restate this contract.
- **Standalone (`/smith-question`)**: prints this contract as a reference. It
  does not generate questions on its own.

## Consumers

- `smith-new` — Phase 5 Questions Gate (persists `questions.md` in the feature
  folder).
- `smith-clarify` — Interactive Answer Collection + sequential ≤5-question loop.
- `smith` — init interview (29-question intake walk; keeps its own
  `ok`/`skip`/`back` navigation and `specs/init-intake.md` persistence, uses this
  contract for presentation).
