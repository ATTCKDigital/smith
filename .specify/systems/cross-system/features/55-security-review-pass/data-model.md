# Data Model: Inline Security Review Pass for smith-build

This document specifies the SHAPES this feature introduces: the
`security_review` config schema, the scanner output line format
(redaction requirement included), the Layer 3 LLM findings contract, the
`/tmp` handoff file(s), and the enforcement decision table with its
terminate-semantics contract. All are prose/table-level specifications for
`plan.md` and the eventual `smith-build/SKILL.md` prose to encode — no
code is prescribed here, matching `research.md`'s finding (§4) that the
scanner script itself is a separate, testable artifact, not inline
markdown prose.

**Section numbering**: `§1-§5` below are local to THIS document. Do not
conflate with the pre-existing, unrelated `data-model.md §9`/`§4`/etc.
citations already in `smith-build/SKILL.md`/`smith-bugfix/SKILL.md` (an
earlier, different feature's file), nor with feature 54's own local
`§1-§5` in `.specify/systems/cross-system/features/54-clean-code-review-pass/data-model.md`.
Any SKILL.md prose this feature adds must qualify citations as "this
feature's `data-model.md` §N" per `research.md` §4's closing note.

## §1 — `security_review` config schema (`.smith/config.json`)

Resolved at the questions gate (`questions.md`, Q1/Q2/Q4/Q6, 2026-09-13) —
every field below is either always-required or explicitly
optional-with-a-stated-default; the schema ships exactly as originally
proposed (Q6) plus the new `review_model` key (Q4). There is no
`secret_findings_always_block` field: Q2 resolved Layer 1 Critical
termination to be unconditional and non-bypassable, so there is nothing
left to toggle — see §5's decision table.

```jsonc
{
  "security_review": {
    "enforcement_tier": "flag",   // REQUIRED. "flag" (shipped default, Q1) | "block_on_critical" (opt-in). Governs Layer 2 (SAST) and Layer 3 (LLM) Critical findings ONLY — Layer 1 (secret) Critical findings terminate unconditionally regardless of this value (FR-16, Q2); there is no config field for that override since it is non-bypassable by design
    "review_model": "opus",       // OPTIONAL, default "opus" (Q4). One of "haiku" | "sonnet" | "opus" | "fable". Governs ONLY Layer 3's LLM review subagent model — a bounded, once-per-build pass where miss-cost asymmetry favors strong reasoning by default; "fable" is not universally available on every account tier, so it is never the shipped default, only an opt-in override
    "layers": {                                            // OPTIONAL sub-object (shipped as proposed, Q6); every sub-key defaults to true (all layers on) when the object or a given key is absent, so {} or an omitted "layers" key is a strict subset of this shape, not a different one
      "secret_scan": true,
      "sast": true,
      "llm_review": true
    },
    "excludes": [],           // OPTIONAL additional path globs, layered ON TOP OF the fixed built-in exclude set (vendor/, node_modules/, .venv/, dist/, build/, .smith/ — FR-5, research.md §8); never removes a built-in exclusion, only adds more
    "allowlist_globs": [      // OPTIONAL glob list for known-noisy files exempted from Layer 1's high-entropy heuristic specifically (FR-5); does NOT exempt the deterministic pattern matches (AWS/GCP/PEM/GitHub/Slack signatures still apply even to an allowlisted glob)
      "package-lock.json",
      "yarn.lock"
    ]
  }
}
```

**Allow/deny semantics for `layers`**: this is an allow-list of ENABLED
layers, not a deny-list — an absent `layers` object means all three run
(matching FR-1's "All three layers ... execute within this single phase"
as the unconfigured default); an explicit `false` for any sub-key disables
just that layer for this project. FR-10 requires Layer 3 (`llm_review`)
to "always run, regardless of Layer 1/Layer 2 scanner presence or
findings" — that FR governs PRESENCE-vs-ABSENCE of external tools, not
this config-driven enable/disable, so setting `llm_review: false` here (an
explicit project opt-out) does not contradict FR-10; it is a different axis
(config choice vs. environment capability) and is called out as a
schema-design note for the gate, not asserted as required by any FR in
spec.md.

**File identity (FR-23, restated for `data-model.md` completeness)**: this
key lives in `.smith/config.json` ONLY. It is never read from or written
to `.smith/security-config.json` (guard-hook config) or from the orphaned
`security` block already present in the same file (BANK-027). See
`research.md` §6 for the exact seeding-path evidence and the gap this
feature must additionally close (a non-destructive merge step in
`skills/smith/SKILL.md`/`skills/smith-update/SKILL.md`, mirroring feature
53's cited mechanism) so already-initialized projects actually receive
this key, not just brand-new ones.

## §2 — Scanner output format (Layer 1 built-in + gitleaks; Layer 2 SAST)

One finding per line, pipe-delimited, written to stdout by
`scripts/security/secret-scan.sh` (and normalized into the same shape for
any Layer 2 tool's native output before merging):

```
severity|file|line|pattern-id|excerpt-redacted
```

- **`severity`** — one of `critical|high|medium|low` (lowercase, matching
  this line format's machine-parseable intent; the human-facing PR-body
  rendering in §5.4's template capitalizes it, per Phase 3.5's own
  `[<Severity>]` convention at `smith-build/SKILL.md:641`).
- **`file`** — repo-relative path, forward-slash-separated regardless of
  OS (matches every existing `/tmp/smith-build-*.txt` file's path
  convention).
- **`line`** — 1-indexed line number within `file`.
- **`pattern-id`** — a short stable identifier for which rule fired (e.g.
  `aws-akia`, `aws-asia`, `gcp-sa-json`, `pem-private-key`, `github-token`,
  `slack-token`, `generic-high-entropy-assignment`, `conn-string-creds`, or
  `gitleaks:<gitleaks's own rule id>` when the finding came from the
  layered gitleaks pass per FR-7 — the `gitleaks:` prefix is what lets a
  downstream reader distinguish built-in-scanner findings from
  gitleaks-sourced ones without a separate column).
- **`excerpt-redacted`** — **REDACTION REQUIREMENT: the scanner MUST NEVER
  print the secret value itself, in whole or in any substring long enough
  to be independently exploitable.** The excerpt is a masked rendering:
  show at most the first 4 and last 4 characters of the matched span, with
  everything between replaced by a fixed run of `*` characters regardless
  of the actual matched length (so the mask itself does not leak length
  information beyond "short/medium/long" buckets) — e.g. `AKIA********WXYZ`
  for an AWS key, or `post********@db` for a connection-string excerpt.
  For a PEM block or a GCP service-account JSON marker (matches that carry
  no useful "first/last characters" shape), the excerpt is instead a fixed
  literal describing what matched, never a slice of the file content —
  e.g. `[PEM PRIVATE KEY HEADER]` or `[GCP SERVICE ACCOUNT JSON MARKERS]`.
  This applies uniformly whether the finding is flagged (PR body) or
  causes a hard-stop (session log / release notes, §5) — a hard-stop's
  session-log entry is exactly as redaction-bound as a flagged PR-body
  line; there is no "internal-only, so unredacted is fine" exception
  anywhere in this contract, since the vault session log is itself
  git-tracked/team-shared per this repo's existing sync conventions.

Example line:
```
critical|services/billing/webhook.py|142|aws-akia|AKIA********Z9Q1
```

**Merge order (FR-7)**: gitleaks findings (when present) are appended
after the built-in scanner's own findings for the same file, never
deduplicated against each other automatically (a genuine double-detection
of the same literal secret by both the built-in regex and a gitleaks rule
is treated as two independent lines — reporting both is strictly safer
than attempting fuzzy dedup logic that could accidentally drop a real
finding). Layer 2 (SAST) findings use the SAME five-field line format for
internal consistency, with `pattern-id` populated from the tool's own rule
id (e.g. `semgrep:<rule-id>`, `bandit:<check-id>`) — Layer 2 findings are
never secrets, so their `excerpt-redacted` field is a short natural-
language snippet of the flagged code construct (not a secret-shaped
value), still capped to avoid reproducing large code blocks verbatim in
the PR body.

## §3 — Layer 3 (LLM review) findings contract

Mirrors feature 54's Phase 3.5 findings contract exactly
(`.specify/systems/cross-system/features/54-clean-code-review-pass/data-model.md` §1),
with exactly one field added: **`Layer`** — needed here, and not in
feature 54, because three independent detection mechanisms (vs. one
review pass) can each produce findings that land in the same merged
scratch file (§4 below), and a reader of the PR body needs to know which
layer is asserting each claim (FR-12).

```
### Finding <N>
- **Severity:** Critical | High | Medium | Low
- **Location:** <path>:<line> (or <path>:<start>-<end> for a range)
- **Category:** <short label from FR-11's rubric areas — e.g. "Injection
  (SQL)", "Auth/authz flaw", "Secrets/credential handling", "Unsafe
  deserialization", "Path traversal", "SSRF/unvalidated redirect",
  "Cryptographic misuse", "Sensitive-data logging/exposure",
  "Dependency-adjacent code smell (non-CVE)", "Race condition/TOCTOU">
- **Rationale:** <1-2 sentences — what's wrong and why it matters>
- **Layer:** 1 (secret scan) | 2 (SAST) | 3 (LLM review)
```

Every field is required for every finding, mirroring feature 54's own
fail-safe default (a finding missing a field cannot be routed and defaults
to the most conservative treatment — here, that means it is never dropped
silently; an incomplete finding is still written to the scratch file with
`Category: unspecified` or `Layer: unspecified` rather than being omitted,
since OOS-4/FR-13 already guarantee no finding is ever auto-resolved away).

**No `Auto-fix eligible`/`Fix applied`/`Behavior-preserving` fields exist
in this contract** — unlike feature 54's Phase 3.5 contract, THIS
feature's FR-13/OOS-4 make auto-fix categorically inapplicable to every
layer, so those fields would always be `false`/`N/A` and are omitted
entirely rather than carried as dead weight.

**Layer 1/Layer 2 findings normalize into this SAME contract** for
PR-body purposes: §2's pipe-delimited line is the storage/interchange
format for scanner output, but when composing the merged scratch file
(§4), each pipe-delimited line is rendered into a one-line summary
consistent with this contract's Severity/Location/Category/Layer fields
(Rationale for a scanner-sourced finding is generated from `pattern-id`,
e.g. "Matches AWS access-key-id pattern `aws-akia`.") — see §4's exact
line format, which is deliberately terser than this full per-finding
markdown block (mirroring feature 54's own §1-vs-§2 reduction).

## §4 — `/tmp` handoff file(s)

**One shared scratch file for all three layers**
(`research.md` §2's recommendation): `/tmp/smith-build-security-findings.txt`,
populated by Phase 3.6 after merging Layer 1 (built-in + gitleaks), Layer
2 (SAST, when present), and Layer 3 (LLM review) findings. Only findings
that do NOT cause a hard-stop are written here (FR-18) — anything that
triggers termination is instead handled by §5's hard-stop artifact and
never reaches this file (there is no "some findings hard-stop, others from
the same run still get flagged in a partial PR" state; NFR-6 forbids
partial execution, so if ANY finding triggers a hard-stop, Phase 4 never
begins and no PR body is ever composed at all this run).

Line format (mirrors `/tmp/smith-build-clean-code-findings.txt`'s own
flat-bullet style, `smith-build/SKILL.md:320-322`, extended with the
`layer` field FR-12 requires):

```
- **[<Severity>]** `<path>:<line>` — <one-line description> (category: <Category>, layer: <Layer>)
```

Example:
```
- **[Critical]** `services/billing/webhook.py:142` — Matches AWS access-key-id pattern `aws-akia` (excerpt: AKIA********Z9Q1) (category: Secrets/credential handling, layer: 1)
- **[High]** `services/api/auth.py:58` — SSRF: user-controlled URL passed to outbound request with no allowlist check (category: SSRF/unvalidated redirect, layer: 3)
- **[Medium]** `services/api/db.py:12` — Query built via string concatenation from a request parameter (category: Injection (SQL), layer: 2)
+ 3 low-severity notes
```

**Severity threshold (mirrors FR-19/feature 54's own convention
exactly)**: Medium, High, and Critical findings are each listed
individually; Low-severity findings are folded into exactly one trailing
`+ N low-severity notes` line (omitted when N=0). This is the SAME
threshold rule feature 54 used (its own FR-16), applied here per this
feature's FR-19.

**Empty-file semantics (FR-21)**: when zero non-terminating findings exist
across all three layers, `/tmp/smith-build-security-findings.txt` is
either empty or never created — either way, §5.4's PR template omits the
"Security Review" section entirely, matching §5.3/§5.3.1/Phase 3.5's own
omit-when-empty behavior.

**Layer-disclosure companion file**: because FR-20 requires the section to
always state which layers ran vs. were skipped for absence — REGARDLESS
of whether any layer produced a finding — a second, always-written scratch
file records this independently of whether findings exist:
`/tmp/smith-build-security-layers-ran.txt`, one line per layer:

```
layer1_builtin=ran
layer1_gitleaks=ran|skipped_absent
layer2_sast=ran:<tool-name>|skipped_absent
layer3_llm=ran
```

This file is always written (never conditionally), since FR-20's
disclosure requirement applies "whenever the 'Security Review' section is
included" — i.e. it is read and rendered into the section ONLY when
`/tmp/smith-build-security-findings.txt` is non-empty (FR-21 still governs
whether the section appears at all), but its own existence does not depend
on findings existing, since it must be computed once regardless.

## §5 — Enforcement decision table + terminate-semantics contract

**Decision table** — tier × severity × layer → outcome. Resolved at the
questions gate (Q1: default tier; Q2: secrets row is tier-independent).

| `enforcement_tier` | Severity | Layer | Outcome |
|---|---|---|---|
| any (`flag` or `block_on_critical`) | Critical | 1 (secret) | **terminate** — unconditional, non-bypassable by `enforcement_tier` (FR-16, Q2). This is the system's second non-bypassable denial, after the browser-production confirm-gate; unlike that gate it has no runtime-confirmation escape hatch — the allowlist marker (a per-line comment; `research.md` §8) is the sole false-positive remedy, applied before the scan runs. |
| any | High/Medium/Low | 1 (secret) | **flag** — only Critical Layer 1 findings trigger the unconditional override; non-Critical secret-pattern findings follow the general tier like any other finding. |
| `flag` (shipped default, Q1) | any | 2 (SAST) or 3 (LLM) | **flag** |
| `block_on_critical` (opt-in, Q1) | Critical | 2 (SAST) or 3 (LLM) | **terminate** |
| `block_on_critical` (opt-in, Q1) | High/Medium/Low | any | **flag** (US-5: "none of them terminate the workflow, regardless of the configured enforcement tier") |

Every "flag" row's finding is written per §4's format; every "terminate"
row skips §4 entirely and instead produces this section's hard-stop
artifact.

**Terminate-semantics contract (FR-15/FR-16/NFR-1/NFR-6)** — what happens,
in order, the instant ANY finding resolves to "terminate":

1. **No further Phase 3.6 work occurs for this run** — evaluation of
   remaining findings from other layers MAY still complete (so the
   eventual hard-stop record can list everything found, not just the one
   triggering finding), but no finding from this run is ever written to
   §4's flag-only scratch file; the entire run's outcome collapses to
   "terminated," not a partial flag+terminate mix (NFR-6, all-or-nothing).
2. **Phase 4 (Spec Updates) never begins.** Consequently Phase 5.1
   (Commit) and Phase 5.2 (Push) never execute — the finding that
   triggered termination (a secret, in the primary case) never reaches
   `git commit`, let alone `git push` (US-2's explicit requirement).
3. **A hard-stop marker is written to the vault session log** — following
   the existing "Vault Logging" convention already established at the top
   of `smith-build/SKILL.md` (the `### [HH:MM:SS] /smith-build <event>`
   block format), with `**Outcome:**` stating the terminating finding(s)
   (severity, `path:line`, category, layer — reusing §3's contract fields,
   with the excerpt still redacted per §2's requirement, since the session
   log is git-tracked/team-shared), and an explicit line such as
   `**Hard-stop:** Security Review Pass (Phase 3.6) terminated this build
   before Phase 4.` This is the marker FR-15/US-2 require; it is a LOG
   ENTRY, never a prompt (NFR-1) — the workflow does not pause to wait for
   an acknowledgment of this entry.
4. **The eventual release notes/final summary record the stop.** Per
   `smith-build/SKILL.md`'s existing Recovery Mode and Phase 7 conventions,
   a terminated run has no `release.md` in the normal sense (Phase 7 is
   never reached) — the record is instead the session log entry from step
   3, surfaced to the user via the SAME "Display Summary" mechanism
   Phase 7.5 uses for a normal completion (`smith-build/SKILL.md:814-822`),
   adapted to report "build terminated at Phase 3.6" instead of "PR link +
   release notes summary."
5. **Worktree preserved, exactly like any other build failure** — this
   feature introduces no new worktree-handling branch. `smith-build/SKILL.md`'s
   existing Phase 7.3 "On failure: Preserve the worktree for debugging...
   Log the worktree path to the vault session log" convention (776-778)
   applies verbatim to a Phase 3.6 hard-stop; a hard-stop is a build
   failure for worktree-lifecycle purposes even though it is a deliberate,
   successfully-detected stop rather than an exception. The active-workflow
   marker (Phase 0 step 0) is also left in place rather than cleared,
   matching how the marker is only cleared "at the end of Phase 7 ... or on
   unrecoverable failure" (`smith-build/SKILL.md:70`) — a Phase 3.6
   hard-stop is exactly this "unrecoverable failure" case for marker-
   clearing purposes, since recovery would require re-running from Phase 0
   after the underlying finding is addressed, not resuming mid-pipeline.
6. **Exit path**: the workflow's Agent/Task invocation for Phase 3.6
   returns its findings/hard-stop decision to the orchestrating
   `smith-build` skill run, which then stops issuing further phase
   subagent invocations for this run — there is no separate "kill switch"
   tool call; the orchestrating skill simply does not proceed to Phase 4,
   consistent with `smith-build` having "no mid-stream pause mechanism"
   (exploration Finding 6) and every phase already being subagent-
   delegated rather than a single monolithic process that would need an
   explicit abort signal.

**Never a prompt (NFR-1, restated for this contract)**: no step above
presents a confirmation, question, or pause of any kind. This is
categorically different from `security-guard-mcp-browser.sh`'s production
confirm-gate (`docs/security-model.md:77-78`), which is a real-time,
per-tool-call PreToolUse denial that CAN be satisfied by a recorded human
confirmation artifact appearing later in the same session — that mechanism
has no analog here. A Phase 3.6 hard-stop is terminal for the run; there
is no equivalent to `.smith/vault/.mcp-browser-confirmed` that would let a
later action "unblock" an already-terminated build. Re-running requires a
fresh `/smith-build` invocation after the underlying finding is fixed.
