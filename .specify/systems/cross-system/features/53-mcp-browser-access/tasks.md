---
feature: 53-mcp-browser-access
branch: 53-mcp-browser-access
status: ready-for-build
generated: 2026-09-13
inputs: spec.md (FR-1..FR-21, NFR-1..NFR-6), plan.md, data-model.md, research.md, questions.md (6/6 ANSWERED)
---

# Tasks: MCP-First Browser Verification with Safety Guard

20 tasks across 5 phases. Phases are sequential (each depends on prior
phases per `plan.md`'s dependency notes); tasks marked `[P]` within a
phase touch independent files and may be done in any order/in parallel.
Every task is scoped to exactly one file (or one file-plus-shell-invocation
for the verification tasks).

---

## Phase 1 — Guard hook + tests (closes the blocking exploration finding)

- [X] [T001] [P] Create `hooks/security-guard-mcp-browser.sh` (NEW). Follow the exact five-part skeleton of `hooks/security-guard-bash.sh` (stdin read → python3 `tool_name`/`tool_input` extraction, defensive `2>/dev/null || echo ""` throughout → optional `.smith/security-config.json` load → `deny()`/`warn()`/`approve()` helpers emitting the `hookSpecificOutput`/`permissionDecision` JSON contract → fall-through `exit 0`). Classify `tool_name`: read-only = `browser_navigate`, `browser_snapshot`, `browser_take_screenshot`, `browser_console_messages`, `browser_network_requests`, `browser_wait_for`, `browser_tabs`; interaction = `browser_click`, `browser_type`, `browser_fill_form`, `browser_select_option`, `browser_press_key`, `browser_drag`, `browser_hover`, and `browser_evaluate` — **`browser_evaluate` is ALWAYS interaction-class, unconditionally, with no JS/source-pattern heuristic of any kind** (this supersedes the heuristic sketched in `research.md` §13, which was superseded by the answered `questions.md` Q4 — do not implement that heuristic). Read-only tools always `approve()` regardless of target, including production (FR-2). On every **allowed** `browser_navigate` call, write `.smith/vault/.mcp-browser-target` (`{url, classification, updated_at}` per `data-model.md` §3.1): `localhost`/`127.0.0.1`/`::1` → always `staging`; URL matches `browser_verification.urls.staging[].url` → `staging`; URL matches `urls.production[].url`, OR matches neither list → `production` (fail-safe default, Q3). For interaction tools: (1) if `.smith/vault/` or `.smith/security-config.json` is absent, no-op/allow through — never error, never hang (FR-6/NFR-1); (2) otherwise read the existing top-level `warn_only_mode` key (reused, not reinvented) plus the new `browser_verification.allow_interactions` (default `true` when the key is absent) and `browser_verification.urls` keys; (3) if `allow_interactions` is `false`, deny with the master-kill-switch message (`data-model.md` §5) — **this specific denial MAY be downgraded to a warning by `warn_only_mode`**, same as every sibling-guard denial; (4) otherwise resolve the current target's classification from `.mcp-browser-target` (absent/malformed → `unclassified`, treated as production per Q3); if staging, `approve()`; (5) if production, read `.smith/vault/.mcp-browser-confirmed` (`data-model.md` §3.2) — if present and its `url` matches the current target, `approve()` (FR-4/US-8); otherwise `deny()` with the production deny-message naming the target URL and stating confirmation is required (US-7, verbatim requirement) — **this production-confirm-gate denial MUST NOT be downgraded or bypassed by `warn_only_mode` under any configuration; it is the sole non-bypassable denial in the guard (Q1)**. Log every block/warn to the vault session log via `.smith/vault/.current-session`, matching `security-guard-bash.sh`'s `log_security()` pattern, when a session log exists (FR-6). Synchronous pattern-matching + `python3` JSON parsing only — no network calls, no extra subprocess spawns (NFR-4). No bash-only array syntax, no bare unquoted globs — must run correctly under both `bash` and `zsh` (NFR-2). Target ~180-220 lines per `plan.md`'s estimate.

- [X] [T002] [P] Create `tests/hooks/test_security_guard_mcp_browser.sh` (NEW). Reuse `tests/hooks/test_workflow_gate_exemption.sh`'s harness verbatim: `HERE`/`REPO` resolution, rename `GATE`→`GUARD` (pointed at `hooks/security-guard-mcp-browser.sh`), `gate_verdict()`→`guard_verdict()` (same dual tight/loose `permissionDecision` grep), `setup_repo()` (add `.smith/vault/` creation and a per-case `.smith/security-config.json` fixture), `assert_verdict()`, and the closing PASS/FAIL summary block with non-zero exit on any failure. Required cases: (1) every read-only tool allowed on any target incl. production, no config present; (2) interaction tool allowed on a `urls.staging`-listed target; (3) interaction tool allowed on `localhost`/`127.0.0.1`/`::1` even with empty `urls` lists (Q3 carve-out); (4) interaction tool denied on a `urls.production`-listed target with no `.mcp-browser-confirmed` fixture — reason text contains the target URL and the word "confirmation" (US-7 verbatim requirement); (5) interaction tool denied on a target matching neither list (fail-safe default, Q3); (6) interaction tool allowed on a production target once a matching `.mcp-browser-confirmed` fixture is present (US-8); (7) confirmation fixture present but for a *different* URL than the current target → still denied (stale-confirmation invalidation, `data-model.md` §3.2); (8) **production denial persists even with `warn_only_mode: true`** — must still be `deny`, never downgraded (Q1 — the single most important assertion in this file); (9) `allow_interactions: false` denies an interaction call on a *staging* target, and contrast: the same case **is** downgraded to warn/allow-with-context under `warn_only_mode: true` (proves only the FR-4 gate is non-bypassable, not the kill-switch — Q1/Q5 distinction); (10) `browser_evaluate` gated identically to `browser_click` even with a read-only-looking script (e.g. `() => document.title`) — proves no JS heuristic exists (Q4); (11) `.smith/security-config.json` absent → interaction tool call allowed through (no-op, FR-6/NFR-1); (12) malformed JSON in the config file → no-op, never a crash. Target ~220-260 lines per `plan.md`'s estimate; split into a `_shells.sh` companion if bash/zsh parity cases push it past 300.

- [X] [T003] Run `bash tests/hooks/test_security_guard_mcp_browser.sh` (T002's file) in a scratch checkout and confirm all 12 cases pass with zero failures — the bash half of NFR-2/SC-4's shell-portability requirement. Depends on T001 and T002.

- [X] [T004] Run `zsh tests/hooks/test_security_guard_mcp_browser.sh` (T002's file) against the identical fixtures and diff its stdout against T003's bash run (`bash ... > out.bash`, `zsh ... > out.zsh`, `diff out.bash out.zsh`) — confirm byte-identical `permissionDecision`/`permissionDecisionReason` JSON for every case (SC-4's literal requirement; NFR-2's mandated pre-merge smoke test in a scratch repo under both shells). Depends on T003.

---

## Phase 2 — Registration + seeding

- [X] [T005] [P] Edit `settings/smith-settings-fragment.json`. Add a new object to the `PreToolUse` array (~lines 64-85), alongside the existing `"Bash"` and `"Write|Edit|NotebookEdit"` entries: `{"matcher": "mcp__playwright__", "hooks": [{"type": "command", "command": "bash ~/.claude/hooks/security-guard-mcp-browser.sh"}]}`. Use the bare substring `mcp__playwright__` — **not** the spec's illustrative `mcp__playwright__*`, which, read as the regex the `matcher` field actually is, would never match a real tool name (`research.md` §3) — matching the repo's existing zero-metacharacter matcher convention. No change needed to `scripts/dedupe-settings.sh`; its `.matcher + "|" + (.hooks|tostring)` uniqueness key already treats a new matcher string as a new, unique entry (FR-5).

  **Evidence:** entry added between `Write|Edit|NotebookEdit` and `Task`. `python3 -c "import json; json.load(open('settings/smith-settings-fragment.json'))"` → valid JSON. Confirmed `scripts/dedupe-settings.sh`'s key is `.matcher + "|" + (.hooks|tostring)` (read in full) — `mcp__playwright__` is a distinct matcher string from `Bash`/`Write|Edit|NotebookEdit`/`Task`, so it dedupes as its own unique entry with zero code changes needed.

- [X] [T006] [P] Edit `skills/smith/SKILL.md`. In the `.smith/` scaffold step (~line 251, the `mkdir -p .smith/vault/...` block), add a seeding sub-step immediately after it: if `.smith/security-config.json` doesn't yet declare a `browser_verification.urls` key, write/merge it in as `{"staging": [], "production": []}` via a python3 read-modify-write — create the file containing just this key if it doesn't exist yet; if it exists, merge non-destructively, preserving any existing `warn_only_mode`/`allowed_commands`/`production_domains`/etc. content (FR-13, resolved per `questions.md` Q2). This closes the "guard installed, zero enforcement" gap for every freshly-initialized project.

  **Note:** `data-model.md` §1.2 is explicit that `browser_verification.mcp_mode` lives in `.smith/config.json` (seeded by `session-start-logger.sh`), never in `.smith/security-config.json` — the guard itself never reads `mcp_mode` (confirmed against `hooks/security-guard-mcp-browser.sh`'s actual field reads: `warn_only_mode`, `browser_verification.allow_interactions`, `browser_verification.urls` only). So this seeding step writes only `browser_verification.urls`, not `mcp_mode`, matching both the data model and the shipped guard's real config surface.

- [X] [T007] [P] Edit `skills/smith-update/SKILL.md`. In the per-project refresh phase (~line 204/264, "Refresh Smith-owned files; never touch user files"), add the same seeding sub-step for existing projects: if `.smith/security-config.json` **exists** and lacks `browser_verification.urls`, merge it in as empty `staging`/`production` lists (idempotent — no-op if already present). If `.smith/security-config.json` does **not** exist at all, leave it absent — do not invent a security-config file for a project that never opted into one (the guard already no-ops on a missing file per FR-6/NFR-1). This is Smith-owned config, not vault *data*, so it is in scope for the update flow's "NEVER touch `.smith/vault/`" boundary, which protects vault data specifically (FR-13, Q2).

  **Evidence:** new `### 5.1b` subsection inserted between `### 5.1 Refresh ...` and `### 5.2 Run /smith-index --migrate-templates`, same python3 read-merge-write idiom as T006, gated on file-exists-but-key-absent; absent-file case explicitly left untouched.

---

## Phase 3 — Convention template

- [X] [T008] Edit `templates/claude-md-additions.md`. Append a new top-level `## MCP-First Browser Verification` section (after the existing `## File Size Awareness` section, line 29), documenting: (a) how a skill/agent detects at runtime whether `mcp__playwright__*` tools are present in the current tool list; (b) the required project config key `browser_verification.mcp_mode` (lives in `.smith/config.json`), allowed values `extension | sandbox | off`, and FR-10's rule that it is always read from explicit config, never inferred from tool presence (bridge- and sandbox-mode servers expose an identical tool namespace, A-5); (c) the silent-skip fallback idiom (FR-11 — check, then skip silently, no error/warning, never blocks the calling workflow); (d) the non-interactive hard-skip rule (FR-12 — `claude -p` / scheduler runs never attempt a bridge connection at all); (e) the staging/production URL table schema (name/url/label columns, FR-13), noting explicitly that `.smith/security-config.json`'s `browser_verification.urls` (seeded by `/smith` init and `/smith-update`, T006/T007) is the machine-readable source of truth the guard actually reads, and this CLAUDE.md table is the human-readable view of the same data, not itself read by any hook; **(f) the full FR-19 decision chain stated as one explicit IF/THEN (tools present AND `mcp_mode: extension` AND interactive ⇒ attempt the bridge browser subject to the guard's policy; any one condition false ⇒ fall back silently to pre-existing behavior), and FR-20's fast-fail rule (a bridge connect that doesn't succeed immediately is treated as failed for that single call — no waiting, no retry/poll loop — fall back at once)**. This is the one canonical place the four agent files, two sub-audits, and the Q19 block (Phase 4) all reference rather than each restating the chain differently.

  **Evidence:** section appended after `## File Size Awareness`, covering (a)-(f) in full, including the IF/THEN decision-chain code block and the fast-fail paragraph. Tone/format matches the file's two existing sections (short prose + bullet/table blocks, no new heading levels introduced).

- [X] [T009] [P] Edit `skills/smith-index/SKILL.md`. In the `/smith-index --migrate-templates` missing-header-detection list (lines 321-325), grow the 4-bullet list to 5 by adding `` `## MCP-First Browser Verification` `` (matching T008's new header). No other change to the migrate-templates mechanism — it reuses the existing single-backup-per-run step (NFR-6) and the existing "append only if absent" logic unchanged (FR-14).

  **Evidence:** bullet added to `skills/smith-index/SKILL.md`'s doc-facing detection list (now 5 items). **Correction to this task's "no other change" scope, found during T010 verification:** the doc-facing list in `SKILL.md` is prose for an LLM walking through the steps manually; the actual code-enforced detection list is a separate hardcoded `CLAUDE_SECTIONS` Python constant in `scripts/smith-index/run.py` (~line 1371), read by `mode_migrate_templates()`. Neither `tasks.md` nor `plan.md`'s file-by-file list named this file, but leaving it unpatched means the real `/smith-index --migrate-templates` runner would never detect or append the new section — a functional break of FR-14/SC-5 despite this task's file being "done." Fixed in-place as part of T010 (see below); recorded here per the antipattern of documenting an artifact flow without verifying the code path that actually reads it.

- [X] [T010] Verify `/smith-index --migrate-templates` idempotency for the new section (SC-5) against a scratch `CLAUDE.md` missing `## MCP-First Browser Verification`: run once, confirm the section is appended exactly once and exactly one `.bak.<ISO8601>` backup is created; run a second time, confirm zero diff (no duplicate section, no new backup) — per `quickstart.md`'s "Migrate-templates check" commands. Depends on T008 and T009.

  **Evidence.** `~/.smith/scripts/smith-index/run.sh` exists but is a stale global install (pre-dates this feature; its `REPO_ROOT` resolves to `~/.smith`, so it would read `~/.smith/templates/claude-md-additions.md` or its own built-in fallback, not this branch's edited template — using it would not exercise this feature's actual change). This repo's own `scripts/smith-index/run.sh` / `run.py` (which `REPO_ROOT`-resolves into *this* worktree's `templates/`) is the faithful "real runner" and supports `--root <path>`, so it was used directly, against a scratch dir under `/private/tmp` (outside the repo):

  1. **Discovered blocker:** `run.py`'s `mode_migrate_templates()` doesn't consult `skills/smith-index/SKILL.md`'s prose list at all — it checks file content against the hardcoded `CLAUDE_SECTIONS` Python constant (~line 1371). Before any fix, that constant was `["## Smith Context System", "## File Size Awareness"]` — it did not include the new header, so a real `--migrate-templates` run would silently never detect/append the T008 section, regardless of T009's doc edit. Fixed in-place: appended `"## MCP-First Browser Verification"` to `CLAUDE_SECTIONS` in `scripts/smith-index/run.py`. This file is outside `plan.md`'s stated file-by-file list ("No other files are touched") but the fix was necessary for FR-14/SC-5 to hold for the actual shipped tool, not just its prose description — same "fix in-place, don't just document" precedent this file's own Coverage Notes section already established for the FR-20 gap.
  2. **Run 1** (`python3 scripts/smith-index/run.py --migrate-templates --root "$SCRATCH"` against a minimal scratch `CLAUDE.md` with none of the three tracked headers): output `appended 3 section(s); backup at CLAUDE.md.bak.20260913T161314Z`; `grep -c '## MCP-First Browser Verification' CLAUDE.md` → `1`.
  3. **Run 2** (identical command, same scratch dir, no other changes): output `all sections present, no change` / `0 file(s) updated`; `diff` of the post-run-1 and post-run-2 `CLAUDE.md` was empty (byte-identical); no second `.bak.*` file was created (directory listing showed exactly one backup, from run 1); each of the three tracked headers (`## Smith Context System`, `## File Size Awareness`, `## MCP-First Browser Verification`) occurred exactly once in the final file (`grep -c` = 1 for each, confirming no duplication).
  4. Scratch dir was created under `/private/tmp` (not the repo) and removed after verification.

---

## Phase 4 — Agent & skill prose (all independent of each other; each depends on T008's section existing)

- [X] [T011] [P] Edit `skills/smith/agents/product-manager.md`. Update `## Test URLs` (line 60) to reference the staging/production URL table schema (FR-13/FR-16) as the source of environment URLs, so any target the agent navigates to is identifiable by the guard as staging or production. Insert a new step into `## E2E Testing Approach`'s numbered list (line 70, before the current step 2 "Navigate the running `app` using Playwright" at line 75) stating the MCP-first-with-fallback contract — attempt MCP-driven authenticated browser verification only when tools are present, `mcp_mode` resolves to `extension`, and the session is interactive (reference `templates/claude-md-additions.md`'s section by name, don't restate it); otherwise continue with the existing approach unchanged — renumbering the remaining steps (FR-15/FR-16).

- [X] [T012] [P] Edit `skills/smith/agents/senior-qa.md`. In `### E2E Functional Testing (\`app\`)` (line 49), add the same 2-4 sentence MCP-first-with-fallback contract statement used in T011, referencing `templates/claude-md-additions.md`'s section rather than restating it (FR-15).

- [X] [T013] [P] Edit `skills/smith/agents/staff-frontend.md`. In `## Key Responsibilities` item 4 ("Testing: ... E2E validation with Playwright MCP", line 29), append a clause referencing the MCP-first-with-fallback convention (FR-15).

- [X] [T014] [P] Edit `skills/smith/agents/staff-fullstack.md`. In `### Defect Handling` step 1 ("Write a failing test...", line 55), append the same clause referencing the convention (FR-15).

- [X] [T015] [P] Edit `skills/smith-audit/SKILL.md`. Append a short clause to Sub-Audit Orchestration item 6 (UX, line 114) and item 10 (SEO, line 118), each stating the same MCP-first-with-fallback contract for their Playwright-driven checks — attempt authenticated bridge-mode verification under the same three conditions; otherwise fall back to the sub-audit's current unauthenticated approach, unchanged (FR-17).

- [X] [T016] [P] Edit `skills/smith/SKILL.md`. Update the `## E2E Testing with Playwright MCP` CLAUDE.md-generation placeholder block (lines 439-440, generated when Playwright MCP is selected in Q19) so the content it instructs Claude to emit references `templates/claude-md-additions.md`'s "MCP-First Browser Verification" section by name rather than restating its body — consistent with this same file's own "Do NOT... restate" anti-duplication rule two paragraphs below (lines 448-456) (FR-18).

---

## Phase 5 — Docs & polish

- [X] [T017] [P] Edit `docs/security-model.md`. (1) In `## Security Guards` (line 48), change "Smith ships two security guard hooks" to "three"; (2) add a new `### security-guard-mcp-browser.sh (PreToolUse, mcp__playwright__)` subsection immediately after `### security-guard-files.sh` (after line 70), matching the existing two guards' shape (one short paragraph + bullet list) describing the read-only-always-allow / interaction-gated / non-bypassable-production-confirm-gate policy; (3) update the "Hook event types" table's PreToolUse row (line 38) to add `security-guard-mcp-browser`; (4) add a 4th numbered item to "What to Audit Before Enabling" (lines 90-98) for `~/.claude/hooks/security-guard-mcp-browser.sh`, covering the interaction-tool policy and the production-confirmation requirement, matching items 1-2's `**path** -- description` shape (FR-7). *(Sub-items (1)-(3) go beyond FR-7's literal text, which names only the 4th audit item — added here because leaving "two guards" and no per-guard subsection stale would violate NFR-5's "reads as a natural continuation, not a bolt-on" requirement and leave the doc internally inconsistent the moment this guard ships; see Coverage Notes below.)*

- [X] [T018] [P] Edit `docs/hooks.md`. Add a new row to the "Hook Summary" table (lines 11-23): `| security-guard-mcp-browser | PreToolUse | mcp__playwright__ | Gate Playwright MCP browser interaction tools; block production actions without confirmation |`. Add a new `### security-guard-mcp-browser.sh` subsection under "Detailed Reference" (after `### security-guard-files.sh`, lines 102-111) with the same **Event** / **Matcher** / **What it does** / **Files touched** / **To disable** sub-bullets used by the sibling guards. **Files touched** must name `.smith/vault/.mcp-browser-target` and `.smith/vault/.mcp-browser-confirmed` — not "None (inspection only)" like its siblings, since this guard does write two small state-cache files (`research.md` §8's flagged wording correction) (FR-8/NFR-5).

- [X] [T019] [P] Edit `CHANGELOG.md`. Add a new `[Unreleased]` → `### Added` entry following the existing entry style/tone (bold one-line summary, then sub-bullets for Mechanism/Wiring/Tests, as used by the `stamp-response.sh` and `user-prompt-logger.sh` entries): summarize the new `security-guard-mcp-browser.sh` guard (closes the blocking Bash/Write-Edit-NotebookEdit-guard-parity gap for `mcp__playwright__*` tools per the exploration finding), the `browser_verification` config schema and its install/update-time seeding, the `templates/claude-md-additions.md` MCP-First convention and its four-agent/two-sub-audit/Q19 adoption, and the `/smith-index --migrate-templates` detection-list extension — citing feature #53.

- [X] [T020] Run the complete `tests/hooks/` suite — including `test_security_guard_mcp_browser.sh` (T002) and every pre-existing hook test — under both `bash` and `zsh` one final time in a clean scratch checkout, after every prior phase has landed, confirming zero regressions and byte-identical guard JSON output across shells (NFR-2/SC-4). This is the single pre-merge gate for the whole feature. Depends on all prior tasks.

  **Evidence.** Materialized the full working-tree state (`git ls-files` + `git ls-files --others --exclude-standard`, i.e. tracked+modified+untracked-not-ignored) into a standalone scratch checkout at `/private/tmp/claude-501-t020-scratch`, independent of this worktree's path, and ran the gate there.
  - **All 11 `tests/hooks/*.sh` under bash:** 0 failures (exit 0 each) — `test_security_guard_mcp_browser.sh` 18/18, `test_config_default_seed.sh` 16/16, `test_context_budget_guard.sh` 14/14, `test_context_loader.sh` 8/8, `test_create_active_workflow.sh` 25/25, `test_git_hooks.sh` 7/7, `test_hook_chain_order.sh` 6/6, `test_manifest_updater.sh` 7/7, `test_save_preserves_descriptions.sh` 12/12, `test_user_prompt_logger.sh` 17/17, `test_workflow_gate_exemption.sh` 12/12.
  - **zsh, of the 6 harnesses that support it** (documented `Run:` header and/or `${BASH_SOURCE[0]:-$0}`-style nounset-safe path resolution — `test_security_guard_mcp_browser.sh`, `test_context_loader.sh`, `test_git_hooks.sh`, `test_hook_chain_order.sh`, `test_manifest_updater.sh`, `test_save_preserves_descriptions.sh`): all 6 pass identically to their bash run (same counts, exit 0). `test_security_guard_mcp_browser.sh`'s bash and zsh stdout are byte-for-byte identical (`diff` clean) — the literal SC-4/NFR-2 guard-JSON-parity assertion. `test_manifest_updater.sh` and `test_save_preserves_descriptions.sh` differ only in embedded wall-clock perf-sample numbers (e.g. "runs (ms): 208 209 213…" vs "199 207 207…"), both still under their p95 threshold and PASS in both shells — not a JSON/behavior divergence.
  - **The other 5 `tests/hooks/*.sh`** (`test_config_default_seed.sh`, `test_context_budget_guard.sh`, `test_create_active_workflow.sh`, `test_user_prompt_logger.sh`, `test_workflow_gate_exemption.sh`) are bash-only harnesses by their own documented convention (header says `Run: bash tests/hooks/<name>.sh` only, no zsh) and use raw `${BASH_SOURCE[0]}` under `set -u`, which is unset in native zsh — not forced under zsh per this task's own bash-only-harness carve-out. None of these files, nor the hooks/scripts they cover, appear in `git diff origin/main --name-only`, confirming they are unrelated to this feature.
  - **Top-level scripts** (`tests/get-base-branch.test.sh`, `tests/workflow-gate-redirect.test.sh`, `tests/workflow-summary-session.test.sh`) also re-run clean under bash in the same scratch checkout: 8/8, 14/14, 5/5.
  - Zero fixes were needed for T020 itself — the two Coverage Notes gaps (FR-20 doc content, `CLAUDE_SECTIONS` in `run.py`) were already fixed in-place by T008/T010 prior to this run.

---

## Coverage & Consistency Notes (smith-analyze pass)

**Spec ↔ Plan ↔ Tasks alignment: PASS, with 2 gaps found and fixed in-place, 1 pre-existing item noted (not fixed, out of scope).**

### FR / NFR → task traceability

| Requirement | Task(s) |
|---|---|
| FR-1 (new guard, matcher) | T001 |
| FR-2 (read-only always allow) | T001; tested T002#1 |
| FR-3 (interaction gating + warn_only_mode) | T001; tested T002#9 |
| FR-4 (production confirm-gate, non-bypassable) | T001; tested T002#4,6,7,8 |
| FR-5 (settings-fragment registration) | T005 |
| FR-6 (no-op on absent vault/config) | T001; tested T002#11,12 |
| FR-7 (security-model.md audit item) | T017 |
| FR-8 (hooks.md table + reference) | T018 |
| FR-9 (claude-md-additions.md section) | T008 |
| FR-10 (mcp_mode never inferred) | T008(b) |
| FR-11 (silent-skip idiom) | T008(c) |
| FR-12 (non-interactive hard-skip) | T008(d) |
| FR-13 (URL table schema + seeding) | T008(e), T001, T006, T007 |
| FR-14 (migrate-templates detection) | T009; tested T010 |
| FR-15 (4 agent files contract) | T011, T012, T013, T014 |
| FR-16 (product-manager URL table refs) | T011 |
| FR-17 (smith-audit UX/SEO clauses) | T015 |
| FR-18 (Q19 block reference) | T016 |
| FR-19 (fallback decision chain) | T008(f) *(gap fixed — see below)*; echoed T011-T015 |
| FR-20 (fast-fail, no retry) | T008(f) *(gap fixed — see below)* |
| FR-21 (allow_interactions kill switch) | T001; tested T002#9 |
| NFR-1 (never block on missing config) | T001; tested T002#11,12 |
| NFR-2 (bash+zsh portability) | T001, T003, T004, T020 |
| NFR-3 (MCP tools session-scoped only) | Satisfied by spec.md's own OOS-1 text; no task needed |
| NFR-4 (negligible latency, python3-only) | T001 |
| NFR-5 (docs match existing structure/tone) | T017, T018 |
| NFR-6 (single shared backup, non-destructive) | T009 |
| SC-1 / SC-2 (behavioral parity) | End-to-end via T008 + T011-T016 prose contract; no isolated unit test exists per `plan.md`'s Test Strategy ("no new application test suite") |
| SC-3 / SC-4 (production zero-bypass / bash-zsh parity) | T002, T003, T004, T020 |
| SC-5 (migrate-templates twice-run idempotent) | T010 |

Every `plan.md` "Exact file-by-file change list" entry (2 NEW + 12 MODIFIED) has at least one task; `skills/smith/SKILL.md`'s two distinct changes (Q19 reference, init seeding) are correctly split across T016 and T006 per the phase brief. No file outside plan.md's list is touched by any task.

### Gaps found and fixed in-place

1. **CRITICAL — FR-20 had no task coverage.** `FR-9`'s literal five sub-items (a)-(e) for the `claude-md-additions.md` section don't name FR-20's fast-fail-no-retry rule or FR-19's full decision chain as required content, even though four agent files and two sub-audits (Phase 4) all depend on this section as their single source of truth for "the MCP-first-with-fallback contract." Without it, an implementer could ship a template section that never documents *how* the fast-fail behavior from US-5 is supposed to work, and Phase 4's agent edits would have nothing correct to reference. **Fixed**: added explicit sub-item (f) to T008 requiring the full FR-19 IF/THEN chain and FR-20's fast-fail rule.

2. **Non-critical but consistency-relevant — `browser_evaluate` classification.** `research.md` §13 documents an outdated heuristic (read-only unless the JS source matches mutating patterns) that was explicitly rejected by the answered `questions.md` Q4 (`browser_evaluate` is unconditionally interaction-class). `data-model.md` §4 and `spec.md`'s own Overview already reflect the correct, current answer — only `research.md` (a dated research log, expected to go stale post-answers) still shows the old idea. **Fixed**: T001 and T002 both explicitly call out that the heuristic is superseded and must not be implemented, so an implementer skimming `research.md` doesn't build the wrong thing.

3. **Noted, not fixed (non-critical, doc-completeness only) — `docs/security-model.md` scope.** `plan.md`'s file-by-file list and FR-7 both name only the "What to Audit Before Enabling" 4th item. But that file also says "Smith ships two security guard hooks" (line 48) and has per-guard descriptive subsections (lines 50-70) and a "Hook event types" table (line 38) that would all go stale/incomplete the moment a third guard ships — directly conflicting with NFR-5's "reads as a natural continuation... not a bolt-on" requirement. T017 was written to cover the full, NFR-5-consistent update (all within the one file `plan.md` already scoped) rather than leaving the doc internally inconsistent.

4. **Noted, not fixed, out of scope — `README.md` "Copies all 9 hooks to `~/.claude/hooks/`" (line 193).** This count is already stale today (pre-dates this feature; the repo currently ships 11+ hooks per `docs/hooks.md`). `plan.md` does not list `README.md`, and neither this feature's FRs nor `questions.md` address it. Left untouched, consistent with `plan.md`'s explicit "No other files are touched" boundary and A-3's precedent for not bundling unrelated pre-existing doc-drift into this feature.

### Answered-question non-contradiction check

- **Q1 (non-bypassable production gate)**: T001 implements the FR-4 denial as the sole non-downgradable case; T002#8 asserts it survives `warn_only_mode: true`; T002#9 asserts the *different* `allow_interactions` kill-switch denial (Q5) *is* downgradable — no task collapses this distinction.
- **Q3 (fail-safe default + localhost carve-out)**: T001's classification logic and T002#3/#5 both encode "unmatched ⇒ production, localhost/127.0.0.1/::1 ⇒ always staging" — no task defaults unmatched targets to staging.
- **Q4 (`browser_evaluate` always interaction-class)**: T001/T002#10 explicitly forbid the superseded JS-heuristic approach.
- **Q5 / FR-21 (`allow_interactions`, default `true`)**: T001 implements default-`true`-when-absent; no task requires an operator to opt in before getting FR-2..FR-4's normal decision table.

No task in this file contradicts any of the 6 answered questions.
