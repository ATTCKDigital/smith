# Quickstart: Inline Security Review Pass for smith-build

Verification walkthroughs for each user scenario (US-1..US-8). These are
manual/observational checks against a real `/smith-build` run (per
`plan.md`'s Test Strategy, this feature's own automated coverage lives in
`tests/security/test_secret_scan.sh` / `test_detect_scanners.sh` — these
scenarios verify the FULL pipeline integration those unit tests cannot
exercise in isolation). Each scenario reflects the questions-gate answers
now recorded in `questions.md` (Q1-Q6, 2026-09-13); none of the behavior
below is still gate-dependent.

## Prerequisites

- A feature branch with `spec.md`/`plan.md`/`tasks.md`/answered
  `questions.md` ready for `/smith-build`, where implementation (Phase 2)
  is complete and Phase 3 (Testing) has just passed, and Phase 3.5 (Clean
  Code Review Pass) has completed.
- `security_review.enforcement_tier` set in `.smith/config.json` per
  whichever scenario is being verified; the shipped default is `flag`
  (Q1). Note that Layer 1 (secret) Critical findings terminate
  unconditionally regardless of this setting (Q2) — `enforcement_tier`
  only affects Layer 2 (SAST) and Layer 3 (LLM review) findings.

## Scenario 1 — Planted secret is caught pre-commit; unconditional hard-stop (US-2 / SC-1)

**Given** a smith-build run has just passed Phase 3.5, the branch diff vs
`$BASE_BRANCH` contains one planted, clearly-fake canary secret matching
Layer 1's built-in pattern catalogue (`research.md` §8 — e.g. a
structurally-valid-but-never-issued `AKIA`-prefixed string), and
`security_review.enforcement_tier` is set to ANY value (`flag` — the
default — or `block_on_critical`). Layer 1 Critical secret findings
terminate unconditionally regardless of this setting (Q2, `data-model.md`
§5) — there is no config path to make this scenario resolve to "flag."

**When** Phase 3.6 runs.

**Then**:
1. Layer 1 (built-in scanner) detects the finding as Critical severity
   (`data-model.md` §2's line format), BEFORE Phase 4 begins.
2. The workflow terminates immediately, before Phase 4 (Spec Updates)
   begins.
3. Phase 5.1 (Commit) never executes — verify via `git log` on the
   worktree branch: no new commit exists beyond whatever Phase 3
   testing may have already committed (none, per this pipeline's design).
   The secret never reaches `git commit`, let alone `git push`.
4. A hard-stop marker is written to the vault session log
   (`data-model.md` §5's terminate-semantics contract, step 3) — verify:
   `grep -n "Hard-stop" .smith/vault/sessions/<current-session>.md` finds
   the entry, with the finding's severity/`path:line`/category/layer
   present and the excerpt REDACTED (verify: grep the log text for the
   canary's full literal value and confirm zero matches; only the masked
   excerpt appears — this is the system's second non-bypassable denial,
   after the browser-production confirm-gate, and it is exactly as
   redaction-bound as that gate's own artifacts).
5. No synchronous prompt or confirmation is presented at any point —
   observe the run end-to-end; the workflow simply stops and reports via
   the session log / final summary, never via a paused question.
6. The worktree is PRESERVED (not removed) — verify
   `git worktree list` from the primary repo still shows the feature's
   worktree path, exactly like any other build-failure preservation
   (Phase 7.3's existing convention, `data-model.md` §5 step 5) — and the
   active-workflow marker file
   (`.smith/vault/active-workflows/<branch>.yaml`, Phase 0 step 0) is
   still present, not cleared.

**Gate dependency**: none — this outcome is unconditional (Q2). The only
escape hatch for a false positive is the allowlist marker (Scenario 7),
never a tier setting.

## Scenario 2 — SAST/LLM Critical finding; default tier flags (non-blocking) (US-1)

**Given** a smith-build run has just passed Phase 3.5, the branch diff vs
`$BASE_BRANCH` contains a Critical-severity finding from Layer 2 (SAST) or
Layer 3 (LLM review) — NOT a Layer 1 secret finding, which is covered by
Scenario 1's unconditional path instead — and
`security_review.enforcement_tier` is at its shipped default, `flag` (Q1).

**When** Phase 3.6 runs.

**Then**:
1. The finding is flagged as Critical severity (`data-model.md` §3's
   findings contract), BEFORE Phase 4 begins.
2. The workflow is NOT terminated — Phase 4, then Phase 5.1 (Commit) and
   5.2 (Push), all proceed normally.
3. The finding is written to `/tmp/smith-build-security-findings.txt`
   (`data-model.md` §4) and appears in the PR body's "Security Review"
   section — Critical severity, `path:line`, category, layer (2 or 3).
4. Re-running the same scenario with `security_review.enforcement_tier`
   set to `block_on_critical` (opt-in) instead produces the OPPOSITE
   outcome for this same finding — a hard-stop, per `data-model.md` §5's
   table — demonstrating that (unlike Layer 1 secrets) Layer 2/3 Critical
   findings genuinely are tier-controlled.

**Gate dependency**: none — `flag` is the shipped default (Q1);
`block_on_critical` is available as an explicit opt-in per-project
override for teams that want Layer 2/3 Critical findings to hard-stop too.

## Scenario 3 — Clean diff on a fully scanner-equipped machine (US-3 / SC-2)

**Given** the branch diff contains zero findings across all three layers,
and `gitleaks` plus at least one SAST tool (`semgrep` or `bandit`) are
both on `$PATH`.

**When** Phase 3.6 runs.

**Then**:
1. All three layers execute, including gitleaks (Layer 1's additive
   check) and the detected SAST tool (Layer 2) — verify via
   `/tmp/smith-build-security-layers-ran.txt` (`data-model.md` §4):
   `layer1_gitleaks=ran`, `layer2_sast=ran:<tool-name>`.
2. `/tmp/smith-build-security-findings.txt` is empty or absent.
3. The PR body carries NO "Security Review" section at all (FR-21's
   omit-when-empty rule).
4. The workflow proceeds to Phase 4 with no termination.

## Scenario 4 — Clean diff on a scanner-less machine, this repo's current baseline (US-4 / SC-3)

**Given** the branch diff contains zero findings, and `gitleaks` and every
SAST tool are absent from `$PATH` — this repo's own confirmed current
development-machine state (A-2: gitleaks/trufflehog/semgrep/bandit/
osv-scanner/pip-audit/grype all absent, only `npm` present, per this
plan's own research pass re-confirming the exploration's finding).

**When** Phase 3.6 runs.

**Then**:
1. `scripts/security/detect-scanners.sh` reports all three optional tools
   absent — no error, no warning noise anywhere in the run's output or
   session log.
2. Layer 1's built-in scanner (not gitleaks) and Layer 3 (LLM review)
   still execute in full — verify
   `/tmp/smith-build-security-layers-ran.txt` shows
   `layer1_builtin=ran`, `layer1_gitleaks=skipped_absent`,
   `layer2_sast=skipped_absent`, `layer3_llm=ran`.
3. The PR body carries no "Security Review" section (findings file is
   empty, same as Scenario 3 — the layer-disclosure file's existence
   alone does not force the section to render; FR-21 still governs).
4. This scenario is directly executable in THIS repository today without
   installing anything, since it matches the dev machine's actual current
   state — it should be the FIRST scenario exercised once the feature is
   built, as the cheapest real-environment check available.

## Scenario 5 — Scanner-less machine with a real finding: layers still disclosed correctly (US-6 / SC-3, extending Scenario 4's scanner-less environment with a non-terminating finding)

**Given** the same zero-external-scanner machine as Scenario 4, but the
diff contains at least one NON-terminating finding — a High/Medium/Low
severity finding from Layer 1's built-in scanner (a Critical Layer 1
finding would instead hard-stop per Scenario 1/Q2 and never reach this PR
body), or a finding of any severity from Layer 3 (LLM review, governed by
the `enforcement_tier` setting per Scenario 2, not by Q2's unconditional
override).

**When** the "Security Review" PR-body section is composed.

**Then**:
1. It lists the built-in scanner and the LLM review as layers that ran.
2. It lists gitleaks AND both SAST tools as skipped for absence.
3. It never states or implies that gitleaks-equivalent or SAST-equivalent
   coverage occurred — verify by reading the section's exact wording, not
   just its presence: it should read as "ran: built-in secret scan, LLM
   security review; skipped (absent): gitleaks, semgrep, bandit" or
   equivalent, never a bare "security review passed" claim with no
   layer breakdown.

## Scenario 6 — Gitleaks-present machine (US-1 combined with a real gitleaks install)

**Given** `gitleaks` is installed and on `$PATH` (a machine set up
specifically to exercise this branch, since it is absent by default per
A-2), and the branch diff contains a High-severity secret gitleaks' own
ruleset detects but the built-in scanner's catalogue does NOT (a genuine
gap-filling case — e.g. a provider-specific token format not yet in
`research.md` §8's v1 catalogue). High, not Critical, severity is used
deliberately so this scenario demonstrates the flag path; a Critical
gitleaks-sourced finding is still a Layer 1 finding and would instead
hard-stop unconditionally per Scenario 1/Q2 (FR-16 makes no distinction
between the built-in scanner and a merged gitleaks finding).

**When** Phase 3.6 runs.

**Then**:
1. The built-in scanner runs and finds nothing for this specific secret.
2. Gitleaks runs additionally (FR-7: "additive defense-in-depth, never a
   replacement") and DOES find it — its finding is merged into the same
   `/tmp/smith-build-security-findings.txt`, tagged `layer: 1` with
   `pattern-id` prefixed `gitleaks:` (`data-model.md` §2).
3. The PR body's "Security Review" section lists this finding like any
   other, with gitleaks named as a layer that RAN (not skipped) in the
   disclosure preamble.
4. This demonstrates FR-7's "additive, never a replacement" property
   concretely: the built-in scanner alone would have MISSED this finding,
   and gitleaks alone is what caught it — proving the built-in scanner is
   not being treated as sufficient in isolation on a scanner-equipped
   machine, and that its gaps are genuinely covered when gitleaks is
   available.

## Scenario 7 — Allowlist marker suppresses a fixture hit (research.md §8's false-positive mechanism)

**Given** a file in the diff contains a string that matches Layer 1's
generic high-entropy-assignment pattern (e.g. a test fixture's
intentionally-realistic-looking-but-fake API key, needed for a test to
exercise real parsing logic) with a trailing `# smith-secret-scan: allow`
comment marker on the same line (or the file's native comment syntax).

**When** Layer 1 runs.

**Then**:
1. This specific line produces NO finding — verify it is absent from
   `/tmp/smith-build-security-findings.txt` even though the same pattern,
   without the marker, on a different line in the same diff, DOES produce
   a finding (a same-run contrast case, to prove the marker — not some
   broader file-level exemption — is what suppressed it).
2. The deterministic pattern matches (AWS/GCP/PEM/GitHub/Slack signatures)
   are suppressible by the SAME marker mechanism — verify with a second
   sub-case using a planted PEM header instead of a generic assignment,
   confirming the marker is not scoped only to the entropy heuristic.
3. This is the exact mechanism `tests/security/test_secret_scan.sh`'s
   "allowlist-marker suppression" unit case exercises in isolation
   (`plan.md`'s NEW files table) — this quickstart scenario re-verifies it
   at the full-pipeline level, confirming the marker survives the
   `git diff`-scoping step and Phase 3.6's merge-into-scratch-file step,
   not just the scanner script's own direct-invocation output.

## Scenario 8 — Enforcement terminate path: worktree preserved, hard-stop marker present (US-2, expanded verification of Scenario 1's artifacts)

**Given** Scenario 1 has just run and terminated the build.

**When** a human (or the next `/smith-build` recovery invocation) inspects
the aftermath.

**Then**:
1. `git worktree list` (from the primary repo) still lists the
   feature's worktree path — NOT removed, exactly per Phase 7.3's
   existing "on failure: preserve" convention (`data-model.md` §5 step 5).
2. The vault session log's hard-stop entry (Scenario 1, step 4) is present
   and readable — this is the durable record of WHY the build stopped;
   there is no separate `release.md` for a terminated run (Phase 7 was
   never reached).
3. The active-workflow marker
   (`.smith/vault/active-workflows/<branch>.yaml`) is still present —
   confirming NFR-6's all-or-nothing stop left no phase partially
   executed and no cleanup step ran prematurely.
4. Manually re-running `/smith-build` on this same branch after fixing
   the underlying finding (e.g. removing the planted secret) is expected
   to enter Recovery Mode (`smith-build/SKILL.md`'s existing "Recovery
   Mode" section) and re-attempt from an appropriate phase — this
   feature introduces no NEW recovery-mode branch beyond what a Phase 3.6
   hard-stop implies (uncommitted changes exist, tasks.md is presumably
   complete, so Recovery Mode's existing "All tasks complete, uncommitted
   → start from Phase 5" rule would fire, which correctly re-runs Phase
   3.6 as part of the normal pipeline path toward Phase 5, since Phase 5
   is never reached without Phase 3.6/Phase 4 completing first in this
   feature's design — flagged here as a verification point, not a new
   mechanism this feature must build).

## Post-run cleanup

`/tmp/smith-build-security-findings.txt` and
`/tmp/smith-build-security-layers-ran.txt` are ephemeral scratch output,
matching `/tmp/smith-build-oversized.txt`,
`/tmp/smith-build-coverage-misses.txt`, and
`/tmp/smith-build-clean-code-findings.txt`'s own (lack of) cleanup
handling — no new cleanup step is introduced by this feature. A
terminated run (Scenarios 1/8) leaves the worktree and active-workflow
marker in place by design (not cleanup debt) until the underlying finding
is resolved and the build is re-run to completion.
