---
feature: 53-mcp-browser-access
primary_system: cross-system
branch: 53-mcp-browser-access
status: planned
---

# Implementation Plan: MCP-First Browser Verification with Safety Guard

## Technical Context

- **Repo**: Smith skills distribution (this repo). No application
  runtime — deliverables are bash hooks, JSON config fragments, and
  markdown (agent/skill/doc) prose. No build step, no package manager
  dependency changes.
- **Languages**: bash (hooks, tests) with embedded `python3` for JSON
  parsing (repo-wide convention, not introduced by this feature),
  markdown (agents, skills, docs, templates).
- **No `.specify/scripts/setup-plan.sh`, no `constitution.md`, no
  `.smith/index/` manifest exist in this repo** — this plan was produced
  by direct file reads (cited throughout `research.md`), not by a
  scaffolding script or manifest navigator.
- **Primary references**: `research.md` (all resolved unknowns, cited
  file:line) and `data-model.md` (config/state shapes, decision table,
  deny-message contract) in this same feature folder.

## Constitution Gates

**N/A — no `constitution.md` or `.specify/memory/constitution.md` exists
in this repo, so there are no constitution-derived gates to check.**
(Clean-architecture and file-size discipline are instead enforced via
this plan's own "Clean-Architecture Requirements" section below and the
`/clean-code` skill as rubric.)

## Architecture Summary

Two independent halves, sequenced so the safety-critical half ships
first regardless of the capability half's readiness:

1. **Safety guard (closes the blocking exploration finding).** One new
   stateless-per-call bash+python3 `PreToolUse` hook,
   `hooks/security-guard-mcp-browser.sh`, registered in
   `settings/smith-settings-fragment.json` against a `mcp__playwright__`
   substring matcher (see `research.md` §3 for why the spec's
   `mcp__playwright__*` literal is a shell-glob false-friend for the
   actual regex `matcher` field). It reads two small pieces of
   guard-owned runtime state under `.smith/vault/` (current navigated
   target, recorded confirmation — `data-model.md` §3) and one operator
   config file, `.smith/security-config.json` (extended, not replaced —
   `data-model.md` §2), to implement the read-only/interaction/production
   decision table in `data-model.md` §4.
2. **MCP-first convention + fallback chain (the new capability).** A
   documented, config-driven convention
   (`templates/claude-md-additions.md`) that four bundled agents, two
   smith-audit sub-audits, and the `/smith` Q19 CLAUDE.md generator all
   reference identically: attempt the operator's authenticated bridge
   browser only when tools are present AND `mcp_mode: extension` AND the
   session is interactive (FR-19); otherwise silently use pre-existing
   behavior, unchanged. `/smith-index --migrate-templates` carries this
   convention into existing consumer projects idempotently (FR-14).

The guard and the convention are **decoupled**: the guard enforces policy
on any `mcp__playwright__*` call regardless of which code path (MCP-first
or a project's own scripted use) issued it; the convention governs
*when agents choose to issue* those calls in the first place. Shipping
the guard alone (without the convention) still closes the blocking
finding — this ordering choice is reflected in the phased task ordering
below.

---

## CLEAN-ARCHITECTURE REQUIREMENTS (mandatory)

Rubric: `/clean-code` skill (Uncle Bob Clean Code / Clean Architecture
principles) — referenced here as the standard to hold every new/changed
file to, not restated.

### Reuse-before-create (exact components reused, not reinvented)

- **Guard parsing/denial pattern** — `hooks/security-guard-bash.sh`'s
  stdin-read → python3-extract → config-load → deny/warn/approve-helper
  skeleton (`research.md` §1), reused verbatim structurally.
- **Silent-no-op idiom** — `hooks/user-prompt-logger.sh`'s
  check-then-`exit 0` chain (`research.md` §2), reused for every optional
  file this feature reads.
- **Settings-fragment registration + dedupe key** —
  `scripts/dedupe-settings.sh`'s `.matcher + "|" + (.hooks | tostring)`
  uniqueness key already handles a new matcher value with zero code
  changes (`research.md` §3); no new dedupe logic written.
- **Existing `warn_only_mode` / `production_domains` fields in
  `.smith/security-config.json`** — extended with one new
  `browser_verification` key (`data-model.md` §2, shape resolved per
  `questions.md` Q2), kept in this single existing file rather than a new
  config file.
- **`.current-session` singleton-pointer convention** — reused as the
  precedent for the two new guard-owned state files rather than
  inventing session-id-keyed state (`research.md` §11).
- **`tests/hooks/test_workflow_gate_exemption.sh`'s test harness** —
  `setup_repo()`/`assert_verdict()`/summary-block shape reused verbatim
  for the new guard's test file (`research.md` §9).
- **`skills/smith-index/SKILL.md`'s existing 4-header
  missing-header-detection list** — extended to 5 headers in place, not
  replaced with a new detection mechanism (FR-14, `research.md` §5).
- **`create-active-workflow.sh`-style "single auditable entrypoint"
  precedent** — informs (not literally reused as code) the
  confirmation-recording design: a narrow, deliberate write instead of an
  ad hoc heredoc (`research.md` §12).

### Decomposed file structure

Every new file is small and single-purpose:
- `hooks/security-guard-mcp-browser.sh` — one guard, one responsibility
  (classify + gate `mcp__playwright__*` calls). Estimated **~180-220
  lines** based on `security-guard-bash.sh` (307 lines, but covers ~15
  distinct command-pattern categories vs. this guard's 2 tool classes ×
  1 policy dimension) — comfortably under the 300-line soft target.
- `tests/hooks/test_security_guard_mcp_browser.sh` — test file, no shared
  logic with the guard's own source (mirrors
  `test_workflow_gate_exemption.sh`'s standalone-script pattern).
  Estimated **~220-260 lines** (more assertion cases than
  `test_workflow_gate_exemption.sh`'s 12, since bash+zsh parity (SC-4)
  doubles the read-only/interaction/production matrix) — still under the
  300-line soft target; if bash/zsh parity cases push it over 300, split
  into `test_security_guard_mcp_browser.sh` (decision-table cases) +
  `test_security_guard_mcp_browser_shells.sh` (bash/zsh parity only),
  per the 500-line decomposition threshold.
- No new file in this feature is expected to approach the 500-line
  decomposition threshold. **Flag:** none.

### File Size Policy

300-line soft target, 500-line decomposition threshold (repo convention,
`docs/hooks.md`/`CHANGELOG.md` File Size Policy references — no
`constitution.md` exists here to cite directly, so this is carried
forward as the same numeric convention already applied elsewhere in this
repo's own tooling, e.g. `context-budget-guard.sh`'s file-size
philosophy). Every file in the change list below is either markdown prose
(no size gate applies the same way) or the two new shell files sized
above.

---

## Exact file-by-file change list

### NEW

| File | Purpose |
|---|---|
| `hooks/security-guard-mcp-browser.sh` | The guard (§ above). |
| `tests/hooks/test_security_guard_mcp_browser.sh` | Guard test suite, bash+zsh parity (SC-4). |

### MODIFIED

| File | Change |
|---|---|
| `settings/smith-settings-fragment.json` | New `PreToolUse` entry, matcher `mcp__playwright__`, alongside the existing `Bash` and `Write\|Edit\|NotebookEdit` entries (FR-5). |
| `templates/claude-md-additions.md` | New top-level `## MCP-First Browser Verification` section: tool-presence detection, `browser_verification.mcp_mode` config key, fallback idiom, non-interactive hard-skip rule, staging/production URL table schema (FR-9). |
| `skills/smith-index/SKILL.md` | Missing-header-detection bullet list (line ~321-325) grows from 4 to 5 entries, adding `## MCP-First Browser Verification` (FR-14). |
| `skills/smith/agents/product-manager.md` | `## Test URLs` references the URL-table schema; `## E2E Testing Approach` gains the MCP-first-with-fallback step (FR-15/FR-16). |
| `skills/smith/agents/senior-qa.md` | `### E2E Functional Testing (\`app\`)` gains the same contract sentence (FR-15). |
| `skills/smith/agents/staff-frontend.md` | `## Key Responsibilities` item 4 gains a clause referencing the convention (FR-15). |
| `skills/smith/agents/staff-fullstack.md` | `### Defect Handling` step 1 gains the same clause (FR-15). |
| `skills/smith-audit/SKILL.md` | Sub-Audit Orchestration items 6 (UX) and 10 (SEO) each gain a short clause (FR-17). |
| `skills/smith/SKILL.md` | `## E2E Testing with Playwright MCP` (Q19 generation block, line ~439) references `templates/claude-md-additions.md`'s section rather than restating it (FR-18). **Also (resolved per `questions.md` Q2):** the `.smith/` scaffold step already present (`mkdir -p .smith/vault/...`, line ~251) gains a seeding sub-step — if `.smith/security-config.json` doesn't yet declare a `browser_verification.urls` key, write/merge it in as `{"staging": [], "production": []}` (python3 read-modify-write, non-destructive of any existing `warn_only_mode`/`production_domains`/etc. content), so a freshly-initialized project's guard always has a well-formed schema to read (FR-13). |
| `skills/smith-update/SKILL.md` | **New (resolved per `questions.md` Q2):** the per-project refresh phase (~line 204, "Refresh Smith-owned files; never touch user files") gains the same seeding sub-step as above, applied to existing projects: if `.smith/security-config.json` exists and lacks `browser_verification.urls`, merge it in as empty `staging`/`production` lists (idempotent — a project that already has the key is a no-op); if the file doesn't exist at all, it is left absent (the guard already no-ops on a missing file per FR-6/NFR-1 — update does not invent a security-config file for a project that never opted into one). `.smith/security-config.json` is Smith-owned config, not vault *data*, so this is in scope for the update flow's existing "NEVER touch `.smith/vault/`" boundary (FR-13). |
| `docs/security-model.md` | "What to Audit Before Enabling" gains a 4th numbered item (FR-7). |
| `docs/hooks.md` | New Hook Summary table row + "Detailed Reference" subsection (FR-8). |
| `CHANGELOG.md` | New `[Unreleased]` entry under `### Added`, following the existing entry style (see `research.md`'s citations of prior entries for tone/structure). |

No other files are touched. `skills/smith-design`, `skills/smith-extract-functionality`, `skills/smith-timesheet` are explicitly untouched (OOS-3).

---

## Phased task ordering

1. **Guard + tests first** (closes the blocking finding independent of
   everything else): `hooks/security-guard-mcp-browser.sh`,
   `tests/hooks/test_security_guard_mcp_browser.sh`, the
   `settings/smith-settings-fragment.json` registration, and the
   `docs/security-model.md` / `docs/hooks.md` doc updates (documentation
   for a shipped guard belongs in the same phase as the guard, not
   deferred to the docs phase — prevents an undocumented gap window).
   The `skills/smith/SKILL.md` and `skills/smith-update/SKILL.md` seeding
   sub-steps (resolved per `questions.md` Q2) belong in this phase too,
   not phase 3 — a guard that ships without its schema being seeded
   reopens the exact enforcement gap this phase exists to close.
2. **Convention + template**: `templates/claude-md-additions.md`'s new
   section, `skills/smith-index/SKILL.md`'s detection-list edit, tested
   together (a migrate-templates dry run against a scratch CLAUDE.md
   before/after, per SC-5's twice-run-idempotent requirement).
3. **Agent/skill prose**: the four agent files, `skills/smith-audit/SKILL.md`, `skills/smith/SKILL.md` Q19 block — all depend on phase 2's
   section existing (so the "reference, don't restate" links resolve to
   real content) but are otherwise independent of each other and can be
   done in any order within the phase.
4. **Docs/changelog close-out**: `CHANGELOG.md` entry summarizing all
   three prior phases (written last so it accurately describes what
   shipped, not what was planned).

## Test strategy

- **Hook unit/integration tests**: `tests/hooks/test_security_guard_mcp_browser.sh`, run under both `bash` and `zsh` per NFR-2/SC-4. Per
  NFR-2, this is not satisfied by CI alone — the ledger convention
  ("project ledger REQUIRES smoke-testing shell snippets under both
  shells") means the implementer manually runs both interpreters in a
  scratch repo before merge, in addition to whatever automated test
  invocation exists:
  ```bash
  bash tests/hooks/test_security_guard_mcp_browser.sh
  zsh  tests/hooks/test_security_guard_mcp_browser.sh
  ```
  and diffs the two runs' stdout for byte-identical JSON per equivalent
  input (SC-4's literal requirement).
- **migrate-templates idempotency**: manual/scripted twice-run against a
  scratch CLAUDE.md missing the new section — first run appends + backs
  up, second run no-ops with zero diff (SC-5).
- **No new application test suite** — this feature has no
  application-layer code (OOS-1 explicitly excludes smith-build/bugfix
  test phases from any of this).

## Rollout notes

- **Consumer projects** receive this feature via `/smith-update`
  (upstream-SHA-driven refresh of `~/.claude/hooks`, `~/.claude/skills`,
  and per-project `/smith-index --migrate-templates` per the existing
  `smith-update` skill's documented flow) — no bespoke install machinery,
  consistent with every prior hook-adding PR cited in `CHANGELOG.md`
  (`stamp-response.sh`, `user-prompt-logger.sh`, `context-budget-guard.sh`
  entries all state "no bespoke install machinery required").
- **Agency-package skills** (`smith-design`, `smith-extract-functionality`,
  `smith-timesheet`) are explicitly out of scope (OOS-3) and do not
  receive this convention automatically; adopting it there is a
  separate, later change against the private agency-package
  distribution, per the user's global memory note on agency-package
  scope.
- **The guard applies globally the moment it's installed** — unlike the
  convention (which is opt-in per project via `browser_verification.mcp_mode`), the guard fires on every `mcp__playwright__*` call in every
  project the moment `/smith-update` lands it, including projects that
  never adopt the MCP-first convention at all. This is intentional (FR-5
  closes a gap that exists regardless of whether a project uses the new
  capability) but is called out here as a behavior change users will see
  immediately on update, before any project-level URL list is populated.
  **Updated (resolved per `questions.md` Q2/Q3):** because `/smith-update`
  itself seeds `browser_verification.urls` as empty `staging`/`production`
  lists (this plan's seeding sub-step above), day-one behavior is no
  longer "nothing classified as production" — it is data-model.md §4's
  fail-safe default: any interaction-tool target that isn't `localhost`/
  `127.0.0.1`/`::1` is treated as **production** and gated behind the
  confirm-gate until the operator lists their actual staging URLs. This is
  the behavior change users see immediately on update, not a
  fully-unenforced day-one state.
- **Config-file precedent (resolved per `questions.md` Q6):** the guard
  keeps reading `.smith/security-config.json`, per the existing sibling
  guards' precedent, even though this perpetuates the pre-existing split
  from `.smith/config.json` (`research.md` §10). Unifying the two config
  files is explicitly out of scope for this feature and is tracked
  separately via a `/smith-bank` entry created by the parent workflow, not
  folded into this change's blast radius.

---

## Spec-plan tensions surfaced (see final report — feed the questions gate)

**All four tensions below were resolved by the questions gate
(`questions.md`, ANSWERED 2026-09-13) and are now reflected as spec text
(`spec.md`) and updated contracts (`data-model.md`). Left in place for
the historical record of what was ambiguous pre-answers; each is no
longer open.**

1. **Resolved — Q1 (Option A).** FR-3's blanket `warn_only_mode`
   downgrade vs. FR-4/checklist Notes' "non-bypassable"
   production-confirmation requirement — direct textual conflict.
   Resolution: FR-3 now states the exception explicitly (`spec.md`
   FR-3/FR-4); `data-model.md` §4 carries the non-downgradable cell as
   confirmed spec behavior, not a plan-level judgment call.
2. **Resolved — Q2 (Option A) + Q3 (Option A).** FR-4's protection was
   contingent on an operator populating a JSON-mirrored production-URL
   list that no FR required to exist. Resolution: `.smith/security-config.json`'s `browser_verification.urls` is now the FR-13-grounded
   machine-readable source of truth, seeded with empty `staging`/
   `production` lists by `/smith` init and `/smith-update` (this plan's
   file-by-file change list, above) so the schema always exists; and any
   target matching neither list defaults to **production** (fail-safe,
   Q3), not "zero enforcement" — closing the gap this tension described
   rather than just documenting it.
3. **Resolved — Q5 (Option A).** `allow_interactions` had no
   corresponding FR. Resolution: kept, default `true`, now grounded by
   `spec.md` FR-21.
4. **Resolved — Q4 (Option A).** `browser_evaluate`'s mutating case was
   named by neither the "read-only" nor "interaction" tool lists in the
   Overview, and this plan previously defaulted it to interaction-class
   via a heuristic source-pattern check. Resolution: the heuristic is
   removed entirely — `browser_evaluate` is unconditionally
   interaction-class (`spec.md` Overview, `data-model.md` §4), on the
   rationale that a security hook must not parse arbitrary JavaScript to
   infer intent; no source-pattern matching of any kind remains in the
   guard's design for this tool.
