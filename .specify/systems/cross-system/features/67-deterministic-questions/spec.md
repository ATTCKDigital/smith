---
feature: 67-deterministic-questions
primary_system: cross-system
also_affects:
  - system-config-memory
branch: 67-deterministic-questions
created: 2026-09-22
status: in-progress
answers_applied: 2026-09-22
---

# Deterministic Question-Asking Mechanism

## Overview

Smith already mandates a specific way of asking the user a decision question:
a markdown block with **Context → Options (each with pros/cons) → a Recommended
answer with reasoning → a blank `**Answer:**` field**, presented **one question
at a time**, waiting for a reply before advancing. That contract is stated in
full in three skills — `skills/smith-new/SKILL.md` (Phase 5 Questions Gate),
`skills/smith-clarify/SKILL.md` (Interactive Answer Collection), and
`skills/smith/SKILL.md` (init interview, lines 220-233) — and a fourth time as
the question-file format in the shipped CLAUDE.md template
(`settings/claude-md-template.md`, Rule 3).

Two problems follow from this:

1. **The interactive `AskUserQuestion` popup is never forbidden anywhere.** A
   whole-repo scan (exploration `.smith/vault/explore/explore-2026-09-22-deterministic-questions.md`)
   found **zero references to `AskUserQuestion`** in `skills/`, `hooks/`,
   `settings/`, or `templates/`. When a session is not inside a Smith workflow
   (or when the in-workflow instructions decay under context pressure), the
   Claude Code harness default — the `AskUserQuestion` popup — is used instead
   of the markdown format, and nothing catches it: not the graded rules, not a
   hook.
2. **The format is quadruplicated**, so it drifts and cannot be refreshed at the
   moment a question is actually asked.

This feature adds a **layered** fix:

- **(a) A single source of truth** — a new `smith-question` skill that carries
  the canonical presentation contract and response-handling rules, invoked
  just-in-time by the three question-asking skills so the format is fresh in
  context at the gate rather than recalled from far earlier in a long session.
- **(b) Deterministic enforcement** — a new config-gated PreToolUse hook that
  intercepts `AskUserQuestion` and (by default) denies it with a redirect
  reason, plus a compact graded sub-criterion in the CLAUDE.md template. The
  hook is the hard mechanism (harness-enforced, spans every turn and every
  project); the graded rule is the soft backstop (critic-enforced, post-hoc).

Target repo is **smith-repo itself** (self-hosting): every change here ships to
all projects via `/smith-update`, so rollout and scope are first-class concerns.

**Terminology used throughout this spec:**
- **Q&A contract** — the markdown presentation format above (Context / Options
  with pros/cons / Recommended + reasoning / blank `**Answer:**`, one at a time,
  wait for reply).
- **Question gate** — a workflow step that presents Q&A-contract questions and
  blocks until they are answered (smith-new Phase 5, smith-clarify Interactive
  Answer Collection, smith init interview).
- **The popup** — the Claude Code harness-native `AskUserQuestion` interactive
  multiple-choice tool this feature exists to suppress in favor of the Q&A
  contract.
- **Enforcement mode** — the `question_gate.mode` config value selecting how the
  PreToolUse hook reacts to an `AskUserQuestion` call: `deny` (default), `warn`,
  `workflow-gated`, or `off`.

## Problem Statement

1. **The popup is uncovered.** Neither a graded CLAUDE.md rule nor any skill
   forbids `AskUserQuestion`; using it is not a rule violation today, so the
   critic never flags it and no retry is triggered. The failure is silent.
2. **Instruction decay inside workflows.** Even where a skill states the Q&A
   contract, that text may sit hundreds of lines / many turns back by the time a
   question is asked; under context pressure the model falls back to the harness
   default.
3. **No coverage outside workflows.** Freeform (non-Smith) sessions have no skill
   in context telling the model to use the Q&A contract at all.
4. **Format drift risk.** The Q&A contract is restated in four places; a change
   to one does not propagate, and there is no single artifact a skill can pull in
   at the moment it needs the format.

## User Scenarios

### US-1 — Popup suppressed and redirected in a workflow (default mode)
```gherkin
Given `.smith/config.json` has `question_gate.mode: "deny"` (the shipped default)
Given a Smith workflow reaches a decision point and the model attempts to call
    the `AskUserQuestion` tool
When the PreToolUse hook fires on that tool call
Then the hook returns a Claude Code deny decision
    (`hookSpecificOutput.permissionDecision = "deny"`) whose
    `permissionDecisionReason` instructs the model to present the question using
    the Q&A contract (Context → Options w/ pros/cons → Recommended → one at a
    time) and points at the `smith-question` skill
And the model re-presents the question as markdown instead of the popup, with no
    popup shown to the user
```

### US-2 — Popup suppressed in a freeform, non-Smith session
```gherkin
Given a session in a project that installed the Smith settings fragment, with no
    active Smith workflow and no workflow marker present
Given `question_gate.mode` is `"deny"`
When the model attempts an `AskUserQuestion` call
Then the hook denies it identically to US-1 — enforcement does NOT depend on a
    workflow marker in `deny` mode — closing the freeform-session gap
```

### US-3 — Warn-only mode nudges without blocking
```gherkin
Given `.smith/config.json` has `question_gate.mode: "warn"`
When the model attempts an `AskUserQuestion` call
Then the hook does NOT deny; it emits `hookSpecificOutput.additionalContext`
    reminding the model of the Q&A contract, and allows the call to proceed
And this mirrors the existing warn-only branch in
    `hooks/security-guard-bash.sh`
```

### US-4 — Workflow-gated mode scopes enforcement to Smith workflows
```gherkin
Given `.smith/config.json` has `question_gate.mode: "workflow-gated"`
Given an active-workflow marker exists under `.smith/vault/active-workflows/`
When the model attempts an `AskUserQuestion` call
Then the hook denies it as in US-1
Given instead NO active-workflow marker exists
When the model attempts an `AskUserQuestion` call
Then the hook allows it (freeform sessions keep the popup; only in-workflow
    gates are enforced), reusing the same marker-presence check
    `hooks/workflow-gate.sh` already performs
```

### US-5 — Off mode fully disables enforcement
```gherkin
Given `.smith/config.json` has `question_gate.mode: "off"`, or the
    `question_gate` key is absent AND the config file predates this feature
When the model attempts an `AskUserQuestion` call
Then the hook takes no action and allows the call — the hook is inert, exactly
    as if it were not installed
```

### US-6 — A question gate pulls in the canonical contract just-in-time
```gherkin
Given a Smith question gate (smith-new Phase 5 / smith-clarify / smith init) is
    about to present questions to the user
When the skill reaches its question-presentation step
Then it invokes the `smith-question` skill, loading the canonical Q&A contract
    into context at that moment, and presents questions per that contract
And the skill's own SKILL.md no longer restates the full format inline — it
    keeps a one-line pointer to `smith-question` plus any gate-specific details
    (e.g. smith-new's questions.md persistence, smith init's 29-question intake)
```

### US-7 — The graded rule backstops the hook
```gherkin
Given the shipped CLAUDE.md template's rule set
When a turn presents a decision question to the user
Then a compact graded sub-criterion requires the Q&A contract and forbids
    `AskUserQuestion`, so the critic (`hooks/grade-response.sh`) scores a popup
    use as a rule violation even in a project where the hook mode is `warn` or
    `off`
```

## Functional Requirements

### New skill: `smith-question` (`skills/smith-question/SKILL.md`)

- **FR-1**: A new skill `smith-question` MUST be created as the single canonical
  source of the Q&A contract. It MUST document, in one place: the presentation
  format (Context, an Options table with per-option pros/cons/implications, a
  Recommended answer with reasoning), the one-at-a-time / wait-for-reply pacing,
  and the response-handling grammar (`yes`/`recommended` → recommended answer; an
  option letter → that option; `skip` → deferred; anything else → custom answer;
  and, for the walk-through variant, `done` → mark remaining skipped).
- **FR-2**: `smith-question` MUST also document the persisted **questions.md**
  file format (the `## QN` block with Context / Options table / Recommended /
  blank `**Answer:**`, and the `AWAITING ANSWERS` → `ANSWERED` status header)
  used by gates that persist answers, so that format lives in exactly one place
  too.
- **FR-3**: `smith-question` MUST be a **context-loading** skill (its
  instructions load into the current turn for the calling flow to follow), NOT a
  subagent/background skill — presenting questions and collecting answers is an
  interactive main-thread activity that a subagent cannot perform.
- **FR-4**: `smith-question` MUST be directly invocable by the user
  (`/smith-question`) as a reference, and its SKILL.md description MUST make it
  discoverable, but it MUST NOT itself generate questions — it defines the
  contract; the calling skill supplies the questions.
- **FR-5**: `smith-question` MUST explicitly state that the `AskUserQuestion`
  interactive tool is NOT to be used to present these questions — the contract is
  markdown — so the skill reinforces the hook and the graded rule in-context.

### Skill integration (just-in-time invocation)

- **FR-6**: `skills/smith-new/SKILL.md` Phase 5 MUST invoke `smith-question` at
  the point it begins presenting questions, and MUST replace its inline
  restatement of the Q&A presentation format with a one-line pointer to
  `smith-question`, retaining only Phase-5-specific content (questions.md
  generation from plan artifacts, the questions.md location under the feature
  folder, and the answered-status/summary flow).
- **FR-7**: `skills/smith-clarify/SKILL.md` Interactive Answer Collection and its
  sequential questioning loop MUST invoke `smith-question` and replace their
  inline format restatement with a pointer, retaining only clarify-specific
  content (the ≤5-question budget, spec-ambiguity scanning, and encoding answers
  back into spec.md).
- **FR-8**: `skills/smith/SKILL.md` init interview MUST invoke `smith-question`
  for its interactive walk-through and reference the canonical response-handling
  grammar, retaining only init-specific content (the 29-question intake
  generation, `specs/init-intake.md` persistence, and the `ok`/`skip`/`back`
  navigation particular to the intake walk).
- **FR-9**: No behavioral change to any gate's *outcome* is introduced by FR-6
  through FR-8 — the questions asked, their persistence locations, and the
  answer semantics are unchanged. This is a source-of-truth extraction plus a
  just-in-time load, not a redesign of any gate.

### Enforcement hook (`hooks/question-gate-guard.sh`)

- **FR-10**: A new PreToolUse hook script MUST be added that reads the Claude
  Code hook JSON from stdin, acts only when the tool being called is
  `AskUserQuestion`, and for any other tool exits 0 without output (inert).
- **FR-11**: The hook MUST read `question_gate.mode` from the project's
  `.smith/config.json` (resolved relative to the current working directory,
  matching how sibling hooks locate config/session state). Resolution rules:
  - `deny` (or key/file absent but this feature's default is in force — see
    FR-17 for how absence is handled): emit
    `hookSpecificOutput.permissionDecision = "deny"` with a
    `permissionDecisionReason` that names the Q&A contract and points at
    `smith-question`. Deny is emitted using the SAME JSON contract
    `hooks/workflow-gate.sh` and `hooks/security-guard-bash.sh` already use.
  - `warn`: emit `hookSpecificOutput.additionalContext` with the same reminder
    text and allow the call (no deny), mirroring `security-guard-bash.sh`'s
    warn-only branch.
  - `workflow-gated`: deny **only if** an active-workflow marker exists under
    `.smith/vault/active-workflows/`; otherwise allow. Reuse the marker-presence
    logic pattern from `hooks/workflow-gate.sh`.
  - `off`: take no action, allow the call.
- **FR-12**: The hook MUST be resilient: a missing/unreadable/unparseable
  `.smith/config.json`, a missing `question_gate` key, or an unrecognized `mode`
  value MUST resolve to the feature's shipped default behavior (FR-17) and MUST
  NEVER crash, hang, or block an unrelated tool call. All parsing uses `python3`
  (Rule 6) and fails safe.
- **FR-13**: The `permissionDecisionReason` / `additionalContext` text MUST be a
  concise redirect (not a full copy of the contract): it states that interactive
  questions are disabled, that questions must be presented as markdown with
  Context → Options (pros/cons) → Recommended + reasoning, one at a time, and
  that `/smith-question` holds the full contract.

### Settings wiring (`settings/smith-settings-fragment.json`)

- **FR-14**: The settings fragment's `PreToolUse` array MUST gain a new entry
  with `matcher: "AskUserQuestion"` invoking
  `bash ~/.claude/hooks/question-gate-guard.sh`, placed as a sibling to
  the existing `Bash` / `Write|Edit|NotebookEdit` / `mcp__playwright__` / `Task`
  matchers. This is additive — no existing matcher entry is modified.

### Configuration seeding (`.smith/config.json` + three-site pattern)

- **FR-15**: A NEW top-level `question_gate` key MUST be added to
  `templates/config.default.json`:
  ```json
  "question_gate": {
    "mode": "deny"
  }
  ```
  `mode: "deny"` is the shipped default (the user's explicit intent: the popup
  should not appear). Valid values: `deny`, `warn`, `workflow-gated`, `off`.
- **FR-16**: Config seeding MUST follow the exact three-site, non-destructive
  mechanism established by prior features (e.g. feature 58 FR-20): the
  `templates/config.default.json` block above; a `skills/smith/SKILL.md` init
  scaffold paragraph + `python3` heredoc seeding `question_gate` the same way it
  seeds sibling keys; and a `/smith-update` seeding step using the identical
  read-modify-write idiom (key present → no-op; file exists, key absent → merge;
  file absent → leave absent).
- **FR-17**: Default-when-absent behavior MUST be explicit and consistent between
  the hook (FR-11/FR-12) and the docs: when `question_gate` is absent from an
  existing project's config (a project that predates this feature and has not yet
  been re-seeded), the hook MUST treat it as **`off`** (fail-open for
  un-migrated projects — an already-installed project does not silently change
  behavior until it opts in via re-seeding), while a freshly seeded config ships
  `deny`. This distinction (shipped-default `deny` vs absent-key `off`) MUST be
  stated in both the hook comments and `docs/`. [OPEN — see questions.md Q1: this
  is the recommended resolution of the enforcement-scope warning; confirm at the
  gate.]

### Graded rule (`settings/claude-md-template.md`)

- **FR-18**: The shipped CLAUDE.md template MUST gain a compact graded
  sub-criterion requiring the Q&A contract for decision questions and forbidding
  `AskUserQuestion`. It keeps a short normative statement of the format + the
  binary criterion inline (so the graded rule is self-contained and enforceable
  every turn) and points to `/smith-question` for the full contract — it does
  NOT restate the whole contract. Placement (extend Rule 1, extend Rule 2, or a
  new dedicated rule with reweighting) is [OPEN — see questions.md Q2].
- **FR-19**: Rule 3's existing question-file format criterion MUST be reconciled
  with `smith-question` (FR-2): Rule 3 keeps its binary criteria but points at
  `smith-question` for the canonical questions.md shape rather than being a
  fourth independent copy.

### Documentation

- **FR-20**: `docs/` MUST document the `question_gate` config key, its four
  modes, the shipped-`deny`-vs-absent-`off` distinction (FR-17), and the fact
  that the hook installs globally via `~/.claude/settings.json` (so `deny` mode
  affects every project on the machine, not only Smith ones).
- **FR-21**: The rollout note MUST state that this change edits the shipped
  template/hook/settings only, and that a user's already-installed
  `~/.claude/CLAUDE.md` and `~/.claude/settings.json` are updated by running
  `/smith-update` (migrate-templates + settings refresh) — the feature does NOT
  edit the user's live personal config files directly. [Resolves exploration
  warning W2.]
- **FR-22**: `CHANGELOG.md` MUST gain an `[Unreleased]` → `### Added` entry,
  written last, describing the `smith-question` skill, the
  `question-gate-guard.sh` hook + settings wiring, the `question_gate`
  config key, the graded rule addition, and the skill integrations.

## Non-Functional Requirements

- **NFR-1**: The enforcement hook MUST add no perceptible latency to tool calls
  it does not act on — it inspects the tool name first and exits immediately for
  anything other than `AskUserQuestion`.
- **NFR-2**: Every new shell snippet MUST run under both `bash` and `zsh`; every
  embedded Python uses `python3` (Rule 6), matching repo convention.
- **NFR-3**: The change is purely additive to enforcement infrastructure — no
  existing hook, matcher, or gate behavior is altered. Removing
  `question-gate-guard.sh` (or setting `mode: off`) restores exactly the
  prior behavior.
- **NFR-4**: `smith-question` extraction MUST be behavior-preserving for all
  three gates (FR-9) — verified by confirming the questions asked and their
  persistence are unchanged.
- **NFR-5**: The hook MUST fail open on any internal error (FR-12): a bug in the
  hook must never make a project unable to ask the user anything.

## Out of Scope

- **OOS-1 — Editing the user's personal `~/.claude/CLAUDE.md` /
  `~/.claude/settings.json`.** Those are not repo files; propagation to them is a
  `/smith-update` step the user runs (FR-21), not part of this feature's edits.
- **OOS-2 — Redesigning any question gate.** The questions asked, their order,
  and their persistence are unchanged; this feature extracts the shared contract
  and adds enforcement only (FR-9/NFR-4).
- **OOS-3 — Changing the critic's grading engine.** FR-18 adds a sub-criterion to
  the graded rules the critic already reads; it does not modify
  `hooks/grade-response.sh`'s scoring mechanism. [Confirm the critic reads rule
  criteria from the template rather than a hardcoded list — see questions.md Q3.]
- **OOS-4 — A new interactive TUI or alternative question UI.** The markdown Q&A
  contract is the only presentation this feature endorses; it does not build a
  replacement widget for the suppressed popup.

## Assumptions

- **A-1**: The pre-feature exploration
  (`.smith/vault/explore/explore-2026-09-22-deterministic-questions.md`, status
  `conflicts-found`, 0 blocking / 3 warnings) is the evidence base for this spec;
  its three warnings (W1 enforcement scope, W2 personal-vs-shipped config, W3
  extraction-vs-graded-rule delegation) were resolved pre-spec and are encoded as
  FR-11/FR-17 (W1), FR-21/OOS-1 (W2), and FR-18/FR-19 (W3).
- **A-2**: The PreToolUse deny contract used by FR-11 is the same one already
  proven in `hooks/security-guard-bash.sh` (`permissionDecision: deny`, `exit 2`)
  and `hooks/workflow-gate.sh` (JSON + `exit 0`); no new harness capability is
  assumed.
- **A-3**: The Claude Code harness surfaces `permissionDecisionReason` to the
  model on a PreToolUse deny, so the deny doubles as an in-context redirect to the
  Q&A contract. [If the harness does not surface the reason, the hook still
  suppresses the popup; the graded rule (FR-18) and the smith-question invocation
  (FR-6–FR-8) remain as the in-context guidance — verify during build.]
- **A-4**: `smith-question` being a context-loading skill (FR-3) matches how
  `smith-clarify` and `smith-new` already run inline in the main thread.

## Success Criteria

- **SC-1**: With `question_gate.mode: "deny"`, an attempted `AskUserQuestion`
  call in both an in-workflow and a freeform session is denied by the hook and no
  popup is shown; the model re-presents the question as Q&A-contract markdown
  (US-1/US-2).
- **SC-2**: With `mode: "warn"`, the same attempt is allowed but accompanied by an
  `additionalContext` reminder; with `mode: "workflow-gated"`, it is denied only
  when a workflow marker is present; with `mode: "off"` (or absent key on an
  un-migrated project), it is allowed with no hook action (US-3/US-4/US-5/FR-17).
- **SC-3**: The Q&A contract and the questions.md format each exist in exactly one
  canonical place (`skills/smith-question/SKILL.md`); smith-new, smith-clarify,
  and smith reference it and no longer restate the full format, with their
  gate-specific content preserved (FR-1/FR-2/FR-6/FR-7/FR-8).
- **SC-4**: All three gates produce the same questions and persistence they did
  before the extraction (behavior-preserving — FR-9/NFR-4).
- **SC-5**: The shipped CLAUDE.md template contains a compact graded sub-criterion
  forbidding `AskUserQuestion` and requiring the Q&A contract, self-contained
  enough for the critic to score, pointing at `/smith-question` for the full form
  (FR-18/US-7).
- **SC-6**: A fresh `/smith` init seeds `question_gate: {mode: "deny"}`; a
  `/smith-update` on an existing project seeds it non-destructively; a config
  already containing the key is left untouched (FR-15/FR-16).
- **SC-7**: Removing the hook or setting `mode: "off"` restores exactly the
  pre-feature behavior (NFR-3).
