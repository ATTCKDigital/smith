# Implementation Questions: Deterministic Question-Asking Mechanism

**Generated**: 2026-09-22
**Feature**: [spec.md](./spec.md)
**Plan**: [plan.md](./plan.md)
**Status**: ANSWERED

---

## Q1: Shipped default enforcement mode

**Context**: FR-11/FR-15 define four `question_gate.mode` values (`deny`, `warn`,
`workflow-gated`, `off`). The hook installs globally via `~/.claude/settings.json`,
so the shipped default fires in every project on the machine. Your stated pain
includes freeform sessions in *other* (non-Smith-workflow) projects, which argues
for a global default.

**Question**: What should `templates/config.default.json` ship as the default mode?

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | `deny` (global) | Pros: matches your explicit "don't show the popup anywhere" intent; covers freeform + in-workflow uniformly; reversible via config. Cons: also blocks the popup in non-Smith projects on your machine; a blunt, machine-wide stance. |
| B | `workflow-gated` | Pros: enforces only inside Smith workflows (marker present); leaves non-Smith/freeform sessions untouched. Cons: under-covers your stated freeform-session pain; the popup still appears outside Smith work. |
| C | `warn` (nudge first) | Pros: no hard block during a bake-in period; low blast radius. Cons: doesn't actually stop the popup — relies on the model heeding the nudge, which is the exact failure you're fixing. |

**Recommended**: A — it's the only option that fully closes the gap you
described, it's config-overridable per project, and it's trivially reversible.
The machine-wide scope is a real tradeoff but is what "never show me the popup"
implies.

**Answer**: A — `deny` (global) is the shipped default.

---

## Q2: Behavior when `question_gate` key is absent (un-migrated projects)

**Context**: FR-17. Existing projects that predate this feature won't have the
`question_gate` key until they re-seed via `/smith-update`. The hook needs a rule
for "key absent."

**Question**: When the key is absent, should the hook fail-open or fail-closed?

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | Absent → `off` (fail-open); fresh installs ship `deny` | Pros: installing this feature never silently changes behavior in already-existing projects until they opt in; new projects still get `deny`. Cons: existing projects keep showing the popup until you run `/smith-update` there. |
| B | Absent → `deny` (fail-closed) | Pros: enforcement everywhere immediately, no re-seed needed. Cons: the moment the global hook installs, every existing project starts blocking the popup with no explicit opt-in — surprising, and inconsistent with "config drives behavior." |

**Recommended**: A — fail-open on absent key is the conventional, least-surprising
choice for a globally-installed hook; `deny` still ships as the default for any
freshly-seeded config, and `/smith-update` propagates it to existing projects
deliberately.

**Answer**: A — absent key → `off` (fail-open); fresh installs ship `deny`.
Rollout note: the team will run `/smith-update` on all active projects once this
work merges, to seed `question_gate` (and thus activate `deny`) everywhere
deliberately. This is the intended propagation path (FR-21).

---

## Q3: Where does the graded sub-criterion live in the CLAUDE.md template?

**Context**: FR-18. The 100-point rule set is all-or-nothing per rule. A new
criterion forbidding `AskUserQuestion` needs a home.

**Question**: Which rule hosts the "use the Q&A contract, never AskUserQuestion"
criterion?

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | Extend **Rule 2** (skill compliance) | Pros: Rule 2 already governs interactive pacing ("no batching of interactive steps"); natural fit; no reweighting of the 100-point total. Cons: slightly broadens Rule 2's scope. |
| B | New dedicated rule (e.g. Rule 8) | Pros: cleanest semantics, isolated scoring. Cons: forces reweighting every rule so the total stays 100 — touches the whole rubric. |
| C | Extend **Rule 1** (Questions ≠ Actions) | Pros: also question-related. Cons: Rule 1 is about not *acting* on questions — a different axis from *how we ask*; conceptually muddled. |

**Recommended**: A — fits Rule 2's existing "follow the documented interactive
process" theme and avoids reweighting. Keep the criterion compact (one binary
line + a pointer to `/smith-question`).

**Answer**: A (recommended) — extend Rule 2 with one compact binary sub-criterion
forbidding `AskUserQuestion` + requiring the Q&A contract; no reweighting.

---

## Q4: smith init interview integration depth

**Context**: FR-8. The `smith` init interview (29 questions → `specs/init-intake.md`)
uses the same presentation contract but has intake-specific generation and
`ok`/`skip`/`back` navigation.

**Question**: How much of the init interview moves into `smith-question`?

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | `smith-question` owns the *presentation contract*; init keeps intake generation + its nav | Pros: dedupes the shared format while preserving init's unique 29-question intake + `back` navigation; low risk. Cons: init still has some question-handling prose (the intake-specific bits). |
| B | Fully merge init's walk into `smith-question` | Pros: maximal dedup. Cons: `smith-question` absorbs intake-specific concerns (pre-generated intake file, `back` nav) that the other two gates don't use — bloats the shared skill, couples it to init. |
| C | Leave `smith` init untouched (out of scope) | Pros: smallest change. Cons: leaves the format triplicated (init stays a 4th copy); misses the dedup win the exploration identified. |

**Recommended**: A — extract only the shared presentation contract; let init keep
its intake-specific mechanics. Same principle applies to smith-new/smith-clarify.

**Answer**: A (recommended) — `smith-question` owns the shared presentation
contract; smith init keeps its 29-question intake generation, `init-intake.md`
persistence, and `ok`/`skip`/`back` navigation.

---

## Q5: Config key and hook file names (public surface)

**Context**: FR-10/FR-15. These names ship to every project and are awkward to
rename later.

**Question**: Accept the proposed names, or adjust?

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | `question_gate.mode` config key + `hooks/deny-interactive-questions.sh` | Pros: `question_gate` matches existing snake_case config keys (`scheduled_audits`, `supply_chain`); hook name is descriptive. Cons: "deny" in the filename is slightly mode-specific for a hook that also warns/allows. |
| B | `question_gate.mode` + `hooks/question-gate-guard.sh` | Pros: hook filename is mode-neutral (guards, doesn't only deny), matching `security-guard-*.sh` naming. Cons: one more "guard" among several. |

**Recommended**: B — the hook does more than deny (warn/gated/off), so a
mode-neutral `question-gate-guard.sh` reads better and matches the `*-guard.sh`
family already in `hooks/`. Keep `question_gate.mode` as the config key.

**Answer**: B (recommended) — config key `question_gate.mode`; hook file
`hooks/question-gate-guard.sh`.
