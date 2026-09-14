# Research: Inline Security Review Pass for smith-build

All findings below are grounded in direct reads of this worktree's files
(paths/line numbers cited throughout) plus the read-only pre-feature
exploration report
(`/Users/dennisplucinik/Projects/smith-repo/.smith/vault/explore/explore-2026-09-13-security-review-pass.md`,
status: clear, 8 findings, no blocking conflicts). Section numbers below
(§1-§9) are **local to this document only** — see the numbering caution in
§4's closing note before any future SKILL.md prose cites `research.md §N`.

## §1 — Phase 3.5 structure to mirror for Phase 3.6; Phase 4/5.1 boundaries

`skills/smith-build/SKILL.md` currently reads, in order:

- `## Phase 3.5: Clean Code Review Pass` — **lines 252-326** (327 is a
  blank line before the next heading).
- `## Phase 4: Spec Updates (Subagent)` — **line 328**, running through
  the `### 4.5 System Spec Updates via .specify/systems/` sub-section to
  **line 373** (blank line 374).
- `## Phase 5: Commit, Push & Merge` — **line 375**.
  - `### 5.1 Commit` — **lines 377-386**.
  - `### 5.2 Push` — **lines 388-391**.
  - `### 5.3 Pre-PR File-Size Scan` — **lines 393-427**.
  - `### 5.3.1 Pre-PR Description Coverage Scan` — **lines 429-604**
    (includes the embedded-Python block, 472-583, plus the Clean Code
    Review PR-section trigger at 595-603).
  - `### 5.4 Create PR & Merge` — **lines 605-657** (PR body template).

FR-1 requires Phase 3.6 to run "strictly after Phase 3.5 ... strictly
before Phase 4," so the insertion point is the currently-blank line 327,
between Phase 3.5's closing content (326) and the `## Phase 4:` heading
(328) — no renumbering of Phase 4 through 7 or any of their internal
cross-references is needed, exactly as feature 54 did when it inserted
Phase 3.5 itself between the old Phase 3 and Phase 4. This also matches
feature 54's own plan.md precedent for the "N.5 inserted phase" naming
convention (`.specify/systems/cross-system/features/54-clean-code-review-pass/plan.md:128-133`).

Phase 3.5's own internal shape (252-326) is the direct structural
template for Phase 3.6: an **Invocation** sub-section establishing
`BASE_BRANCH=$(.specify/scripts/bash/get-base-branch.sh)` threading and a
pinned model (260-267), a **rubric delivery** sub-section describing how
the subagent locates its rubric by heading, never by line number (269-276),
a **findings contract** paragraph (278-286), a **bounded re-test /
no-loop** guarantee paragraph (306-313), and an **unresolved findings →
scratch file** closing paragraph with the exact markdown line-format the
`/tmp` file uses (315-326). Phase 3.6 should mirror this same five-part
shape, adapted for three layers instead of one review pass, and for
FR-15's hard-stop branch (which Phase 3.5 has no equivalent of — Phase 3.5
is flag-never-block per feature 54's NFR-3, whereas this feature's tier can
legitimately terminate the build; see §9 item 1 and item 2 below).

## §2 — 5.3-family scan script style + PR-body conditional template

Two established patterns exist for "scan → scratch file → conditionally
include in PR body," both already used twice (5.3/5.3.1) and imitated once
more by Phase 3.5's own findings file (§2 of `data-model.md` in feature 54,
which is NOT this feature's `data-model.md` — see the numbering caution in
feature 54's own `data-model.md:9-16`, and the reminder in §4 below):

1. **Deterministic scan → flat `/tmp` file → conditional section**
   (5.3, 393-427): a shell loop over `git diff $BASE_BRANCH --name-only`
   writes matches to a `/tmp/smith-build-*.txt` scratch file; the PR
   template (5.4) embeds that file's raw contents behind a
   `[ -s <file> ] && include || omit` check.
2. **Subagent-authored scan → flat `/tmp` file → conditional section**
   (Phase 3.5, 315-326): the reviewing subagent itself writes its own
   findings, in a fixed one-line-per-finding format, to the scratch file —
   no shell scan step exists because "is this a god function" isn't
   scriptable.

This feature needs BOTH patterns simultaneously, because it has three
layers with two different natures: Layer 1's deterministic scan and
Layer 2's presence-detected external tools are pattern (1)-style output
(a script or CLI tool emits lines); Layer 3's LLM review is pattern
(2)-style (a subagent authoring its own findings). Phase 3.6's design
should merge all three layers' findings into **one** shared `/tmp` file
(FR-18 says "a scratch file," singular) before the PR template step reads
it, rather than three separate files feeding three separate sections —
this keeps the 5.4 template edit to one new conditional block, matching
FR-19/FR-20's framing of a single "Security Review" section.

The PR-body template itself (605-657) is a `gh pr create --body "$(cat
<<'EOF' ... EOF)"` heredoc with each optional section preceded by an
HTML-comment-free `<include this section only when ...>` instruction line
and a concrete worked example directly beneath it (see the "Clean Code
Review" block at 638-649 for the closest existing precedent — same
severity-bracket-then-backtick-path-then-em-dash-description line shape
this feature's new section should reuse verbatim for its individually-
listed Medium/High/Critical findings).

## §3 — Key Rules autonomy line

`skills/smith-build/SKILL.md`'s closing `## Key Rules` section
(842-851) opens with: **"ALL phases run without user interaction"**
(line 844). This is the line NFR-1/FR-15 anchor to when they require the
hard-stop to be logged-only, never a synchronous prompt. If the gate
resolves any enforcement tier to "block," `plan.md`'s file-by-file list
should add exactly one clause to this existing bullet (not a new bullet)
noting that a Phase 3.6 hard-stop is a full, prompt-free termination —
consistent with the bullet's existing wording rather than contradicting
it. No other Key Rules bullet needs touching; "If a subagent fails, retry
once before logging the error and continuing" (846) does NOT apply to a
Phase 3.6 hard-stop — a hard-stop is an intentional termination decision,
not a subagent failure, so it must not be swept into that retry-then-
continue bullet by an implementer skimming Key Rules in isolation. This is
worth an explicit one-clause disambiguation in the actual SKILL.md edit
(flagged for `plan.md`, not decided here).

## §4 — Inline-Python-in-SKILL vs. separate-script+tests style

Two precedents exist in this repo for "a piece of real logic that needs to
run during a workflow phase," and they differ sharply in weight:

**5.3.1's embedded-Python style** (`smith-build/SKILL.md:429-604`): ~150
lines of Python, inlined via a `python3 - "$f" "$CUR_JSON" <<'PY' ... PY`
heredoc, living entirely inside the SKILL.md prose. It has **no companion
test file** — nothing in `tests/` exercises this parser-diffing logic in
isolation; its only verification is the manual "Description Coverage
Warnings" section appearing/not-appearing during a real build. It is also
explicitly called out by this feature's own exploration and by feature
54's `research.md` as a known heaviness (a large, untested, hard-to-review
blob embedded in a markdown file that only a full `smith-build` run
exercises end-to-end).

**Feature 53's separate-script + tests style**
(`hooks/security-guard-mcp-browser.sh` + `tests/hooks/test_security_guard_mcp_browser.sh`):
a real, standalone, directly-invokable script (275 lines) with its own
shebang, header comment block documenting Event/Matcher/Scope, and a
companion test file (292 lines, 15 numbered cases) that drives the script
directly via `bash "$GUARD"`/`zsh "$GUARD"` with synthesized stdin JSON,
asserting on stdout — runnable in complete isolation from any live
`smith-build`/hook-triggered invocation, in both shells, with a PASS/FAIL
summary line and non-zero exit on any failure.

**Recommendation for Layer 1 (the secret scanner): the separate-script
style.** A regex-based secret scanner is real code with real correctness
requirements (false negatives are a security miss; false positives erode
trust in the pass) — it is exactly the kind of logic FR-6 already asks to
ship "with a companion test file... consistent with
`tests/get-base-branch.test.sh`" and exactly the kind of logic the
exploration's Finding 3 called "real script + tests." Concretely:
`scripts/security/secret-scan.sh` (thin bash CLI wrapper: arg-parsing,
exclude-path filtering, exit-code contract) invoking
`scripts/security/secret_scan.py` (the actual regex/entropy engine) or
folding the Python into one `.py` entry point invoked directly — either
way, a file on disk with its own path, independently `python3
scripts/security/secret_scan.py <path>`-runnable, is what makes FR-6's
test file possible at all. Embedding ~150 lines of regex/entropy Python
inline in `smith-build/SKILL.md` (5.3.1's style) would repeat the exact
heaviness this repo's own prior feature already flagged, AND would make
FR-6's test file describe logic that lives nowhere the test can import or
invoke directly — the test would have to re-implement or shell out to a
heredoc extracted from markdown, which is fragile and not what
`get-base-branch.test.sh` or `test_security_guard_mcp_browser.sh` do.

**Both styles documented for completeness** (not a decision either
way is being made past this recommendation — `plan.md` adopts it, but the
gate/build phase could still override):

| | 5.3.1 inline-in-SKILL | Feature 53 separate-script+tests |
|---|---|---|
| Discoverability | Buried in a 850-line markdown file | Own path under `scripts/`, greppable, directly runnable |
| Testability | None (no companion test exists) | Full companion test file, both shells |
| Reuse by other phases/skills | Copy-paste only (heredoc can't be `source`d) | Directly callable by `smith-audit`, F2, or any future consumer (ties into NFR-4) |
| SKILL.md weight | Adds ~150 lines to an already-851-line file | Adds a handful of invocation lines only |
| Precedent age/quality signal | This repo's own exploration flags it as heaviness to avoid repeating | Most recent (`feature 53`, same review cycle as this spec) established pattern |

**Numbering caution** (mirrors feature 54's own `data-model.md:9-16`
disclaimer): this feature's `data-model.md` uses its own local `§1-§5`
numbering. `smith-build/SKILL.md` and `smith-bugfix/SKILL.md` already cite
an EARLIER, unrelated `data-model.md` by section number (the pre-54,
`.meta` touched-methods feature — "data-model.md §9," "§4," etc.), and
feature 54 added its OWN local `§1-§5` on top of that. When Phase 3.6's
eventual SKILL.md prose cites this feature's `data-model.md`, it MUST
qualify it (e.g. "this feature's `data-model.md` §2") rather than a bare
"`data-model.md` §2" — there are now three same-named files in flight
across different feature folders and a bare section citation is
ambiguous to a cold-context reader of the shipped SKILL.md prose.

## §5 — tests/ harness patterns for the new script's tests

Two harness styles are available; the task asks which is closest for a
script test:

- **`tests/get-base-branch.test.sh`** (116 lines): builds a fresh
  `mktemp -d` git repo per case via a `make_repo()` helper, writes a
  fixture file (or omits it), invokes the helper script directly by path,
  compares stdout to an expected string via a `run_case()` wrapper, tracks
  `PASS`/`FAIL` counters, and ends with a `SUMMARY:` line plus a
  `[ "$FAIL" -eq 0 ]` exit-status gate. Simple, linear, one assertion per
  case, no JSON-stdin protocol.
- **`tests/hooks/test_security_guard_mcp_browser.sh`** (292 lines): also
  `mktemp -d`-per-case via `setup_repo()`, but drives the target script
  through a **stdin JSON payload** (`guard_output()`/`guard_verdict()`),
  asserts against parsed JSON fields (`assert_verdict`, `assert_contains`),
  and explicitly re-runs the **entire suite under both interpreters**
  (`DEFAULT_INTERPRETER` resolved from `$ZSH_VERSION`/`$BASH_VERSION`) to
  prove bash/zsh parity by diffing full runs, not just by claiming
  portability.

**Recommendation: `get-base-branch.test.sh`'s overall shape is the closer
fit** — a secret scanner's contract is "run against a directory/diff,
produce lines of output," not "consume a PreToolUse JSON envelope and
return an allow/deny verdict," so there is no JSON-protocol machinery to
reuse from the hook-test style. But the **mktemp-scaffold-per-case idiom**
from `test_security_guard_mcp_browser.sh`'s `setup_repo()` (a throwaway
git repo, planted fixture files, then `rm -rf` cleanup per case) is the
right way to plant fake secrets for FR-4's test cases without touching any
real file in this repo — `get-base-branch.test.sh`'s own `make_repo()` is
actually already exactly this idiom, just scoped to one fixture file
(`.specify/memory/constitution.md`) instead of an arbitrary tree. **Net
recommendation**: use `get-base-branch.test.sh` as the structural template
(`make_repo`/`run_case`/`PASS`/`FAIL`/summary-line/exit-status), extended
with planted multi-file fixtures the way `test_security_guard_mcp_browser.sh`'s
`write_config()` plants a config file per case — no new harness idiom
needs inventing.

## §6 — `.smith/config.json` + `templates/config.default.json`: exact seeding shape and a real gap

`templates/config.default.json` (this worktree; committed, unlike
`.smith/` itself which is entirely gitignored per `.gitignore:1-2`,
"`# Smith runtime state (never commit)` / `.smith/`") currently has four
top-level keys: `_comment`, `security` (the orphaned block BANK-027
tracks), `context_budget`, `ledger`. FR-23 adds a fifth, `security_review`.

**How `.smith/config.json` actually gets created** —
`hooks/session-start-logger.sh:25-40`: on every `SessionStart`, if
`$CLAUDE_PROJECT_DIR/.smith/config.json` does **not exist at all**, the
hook copies (whole-file, byte-for-byte per
`tests/hooks/test_config_default_seed.sh`'s case 3) the first template it
finds across three candidate paths
(`$HOME/.smith/templates/config.default.json`, `$HOME/.claude/skills/smith/templates/config.default.json`,
`$CLAUDE_PROJECT_DIR/templates/config.default.json`). If `.smith/config.json`
**already exists** — any shape, even a stale/older one — it is left
**byte-for-byte untouched** (`test_config_default_seed.sh` case 4,
"existing config preserved verbatim"). There is no merge, no key-diffing,
no re-seed-on-update path for this file anywhere in the repo today.

**This is a real gap for this feature, not just for BANK-027's orphaned
block.** Every developer machine that has ever run `/smith` init or had a
single Claude Code session in a Smith project already has a
`.smith/config.json` on disk (this worktree's own absence of one, verified
by `cat .smith/config.json` → "No such file or directory" during this
research pass, is itself an artifact of being a fresh git worktree with no
prior `SessionStart` — a real, previously-initialized project would not be
in this state). Editing `templates/config.default.json` to add
`security_review` only benefits **brand-new** projects seeded from that
point forward; every pre-existing `.smith/config.json` on a real machine
will never receive the new key via `session-start-logger.sh`, because that
hook's whole-file-copy-if-absent logic explicitly does not touch a file
that already exists (by design, per its own comment: "Users who want to
reset can delete the file and let the next SessionStart re-seed it").

**Feature 53's actual precedent for this exact problem, cited exactly**
(the task's framing: "same mechanism, cite lines"):

- `skills/smith/SKILL.md:274-298` — at `/smith` init time, non-
  destructively seeds `browser_verification.urls` into
  `.smith/security-config.json` via a `python3 - "$PWD/.smith/security-config.json"
  << 'PYEOF'` heredoc: load-if-exists (tolerate missing/malformed → `{}`),
  `bv.setdefault("urls", {"staging": [], "production": []})` **only if the
  key isn't already present**, re-dump with `indent=2`. Every other
  existing key in the file is left untouched.
- `skills/smith-update/SKILL.md:274-305` (`### 5.1b`) — the identical
  idiom, applied to **already-initialized** projects being refreshed by
  `/smith-update`, with the three-line decision rule spelled out
  explicitly (276-280): file exists + key present → no-op; file exists +
  key absent → merge just that key; file absent entirely → leave absent
  (don't invent a file a project never opted into).

**Note the target file differs**: feature 53's precedent seeds
`.smith/security-config.json` (guard-hook-read config, never touched by
`session-start-logger.sh` at all), whereas this feature's key lives in
`.smith/config.json` (`session-start-logger.sh`-seeded config). The
**mechanism** — non-destructive python3 read-modify-write heredoc, applied
identically at `/smith` init AND at `/smith-update` refresh, merging in
only the missing key/subtree while preserving everything else — is the
piece to reuse, retargeted at `.smith/config.json`. Without an equivalent
step added to `skills/smith/SKILL.md` and `skills/smith-update/SKILL.md`
for this feature's `security_review` key, `session-start-logger.sh` alone
leaves every already-initialized project permanently without the new key
until its owner manually deletes and re-seeds `.smith/config.json` (losing
any of their own customizations in the process, since the reset is a full
file delete, not a merge). This is surfaced as a spec-plan tension in
`plan.md`, not resolved here.

**BANK-027 cross-reference** (`.smith/vault/bank/2026-09-13_120000-unify-security-config-seeding.md`,
read from the primary repo, read-only): tracks the pre-existing, unrelated
split where the orphaned `security` block in `.smith/config.json` is
seeded but never read by any guard, while `.smith/security-config.json`
is read by all three guards but seeded only by the two mechanisms cited
above. FR-23/A-3 require this feature's new `security_review` key to be a
**third**, deliberately distinct location that neither worsens nor
resolves that split. Confirmed: this feature's proposed seeding fix (a
merge step for `.smith/config.json`, not `.smith/security-config.json`)
does not touch either side of BANK-027's split — it is additive machinery
for a brand-new key in the already-correctly-seeded-for-new-projects file,
so it does not deepen or reduce BANK-027's scope.

## §7 — `hooks/security-guard-mcp-browser.sh`: presence-detect + defensive-parse idioms to reuse

Concrete conventions worth lifting verbatim for NFR-4's shared
presence-detection helper and for Layer 1/2's own config/tool-presence
reads:

- **Header comment block** (1-18): `#!/usr/bin/env bash` shebang, then a
  structured comment block naming the Event/Matcher/Scope the hook fires
  under and a one-paragraph behavior summary with inline cross-references
  to `data-model.md`/`questions.md` decisions. `scripts/security/detect-scanners.sh`
  should open the same way, minus the Event/Matcher/Scope lines (it's a
  plain script, not a hook) but keeping the "what this does, what it
  cross-references" paragraph.
- **`set -uo pipefail`** (19) — NOT `set -euo pipefail`; the guard
  deliberately omits `-e` so that individual `python3 ... || echo
  "fallback"` fallback chains can run to completion without an early
  script exit on the first non-zero. Layer 1/2/NFR-4's scripts should
  follow the same convention if they use the same `cmd || echo default`
  idiom.
- **Read-stdin-once-at-top** (`INPUT=$(cat)`, line 21) — not applicable
  verbatim to a script invoked with file-path args (as Layer 1 will be),
  but the general principle ("capture untrusted/variable input into one
  named variable immediately, never re-read it") carries over to how
  Layer 1 should capture `git diff` output once rather than re-invoking
  git per check.
- **Defensive python3 one-liners with a bash-side fallback** (24-28,
  238-239, 249-256): every `python3 -c "..."` call is wrapped
  `$(python3 -c "..." 2>/dev/null || echo "<safe-default>")` — malformed
  input, missing python3, or a raised exception all degrade to the safe
  default rather than crashing the caller. This is the exact idiom NFR-4's
  helper needs for "is `gitleaks`/`semgrep`/`bandit` on `$PATH`":
  `command -v gitleaks >/dev/null 2>&1 && echo true || echo false` (or the
  Python equivalent) — never let a presence check itself error out the
  build.
- **Config-validity gate before trusting any field** (225-236): before
  reading `WARN_ONLY`/`ALLOW_INTERACTIONS` from `$CONFIG_FILE`, the guard
  first proves the file both exists AND parses as JSON
  (`CONFIG_VALID="false"` unless a `json.load()` inside a try/except
  succeeds), and short-circuits to a silent no-op/allow (`exit 0`) if
  either the vault directory or a valid config is missing. Layer 1/2's
  config reads of the new `security_review` key should use the identical
  two-step gate (file exists AND parses) before trusting any sub-key,
  never assuming a bare `[ -f "$CONFIG_FILE" ]` implies well-formed JSON.
- **Silent-skip is the universal fallback, never a warning/error** —
  confirmed by `docs/security-model.md:79`'s own description of this
  guard ("No-ops silently — never blocks, never errors — when the vault or
  the config file is absent"), and this is exactly presence-detected/
  silent-skip's spec definition (spec.md Overview, "Presence-detected /
  silent-skip"). NFR-4's helper must return a clean boolean/status with no
  side-channel stderr noise on the "absent" path — `is_interaction()`/
  `is_read_only()`'s plain `case ... esac` pattern (48-60) is the model for
  a dependency-free classification helper generally, useful if
  Layer 2 needs to classify which SAST tool(s) it found.

## §8 — Secret-detection pattern catalogue v1 (concrete, for FR-4)

A concrete v1 regex/heuristic set — offered as a starting catalogue for
the actual implementation to refine, not a frozen spec:

| Category | Pattern (illustrative, Python `re` syntax) | Notes |
|---|---|---|
| AWS access key ID | `AKIA[0-9A-Z]{16}` | Long-lived IAM key prefix |
| AWS temporary/STS key ID | `ASIA[0-9A-Z]{16}` | STS-issued temporary credential prefix |
| AWS secret access key | context-gated: a 40-char base64-alphabet string (`[A-Za-z0-9/+=]{40}`) on a line whose key name matches `(?i)aws.*secret` | Raw 40-char base64 alone is too high-FP; require the key-name context per FR-4's "token-shaped variable assignments" language |
| GCP service-account JSON | `"type"\s*:\s*"service_account"` co-occurring with `"private_key_id"` in the same file | Marks an exported GCP SA key file, not a single-line pattern |
| PEM private key header | `-----BEGIN (RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----` | Matches FR-4's "private-key PEM headers" verbatim; zero legitimate reason for this string in application source |
| GitHub token | `gh[pousr]_[A-Za-z0-9]{36,255}` | Covers `ghp_`/`gho_`/`ghu_`/`ghs_`/`ghr_` prefixes |
| Slack token | `xox[baprs]-[0-9A-Za-z-]{10,72}` | Covers bot/app/legacy/refresh/session token classes |
| Generic token-shaped assignment | `(?i)\b\w*(api[_-]?key\|secret\|token\|password\|passwd\|pwd)\w*\s*[:=]\s*['"]?[^\s'"]{16,}['"]?` combined with a Shannon-entropy check (≥ ~3.5 bits/char over the captured value, length ≥ 20) | This is FR-4's "high-entropy strings" requirement; the entropy gate is what keeps `password = "changeme"` or `token = "test"` from firing while `token = "sk_live_9f2a..."` does |
| Connection string with embedded credentials | `(?:postgres(?:ql)?\|mysql\|mongodb(?:\+srv)?\|redis\|amqp)://[^:\s]+:[^@\s]+@` | Catches DB/broker URIs with inline `user:pass@host` |

**Exclusions (FR-5)**: the identical exclude-path family 5.3/5.3.1 already
use — `vendor/`, `node_modules/`, `.venv/`, `dist/`, `build/`, `.smith/`
(`smith-build/SKILL.md:424-425`) — plus a glob allowlist for
`package-lock.json`/`yarn.lock` specifically named by FR-5 to bound
high-entropy false positives from dependency hashes.

**False-positive strategy** (per the exploration's own INFO note, "False-
positive management for entropy-based detection: exclude-path list
mirroring :424-425 conventions ... + glob allowlist"): two independent
layers of suppression — (1) the path/glob exclusions above, applied
before any regex runs, and (2) a **per-line allowlist marker** for
legitimate matches that survive exclusion (test fixtures, documented
example credentials, this feature's own planted-canary quickstart
fixtures): a trailing or same-line comment token, e.g.
`# smith-secret-scan: allow` (or the file's native comment syntax), that
the scanner recognizes and skips. This is the mechanism the quickstart
scenario "allowlist marker suppresses a fixture hit" (see `quickstart.md`)
exercises directly, and it is what lets FR-6's test suite plant real
canary values in `tests/` without those planted fixtures becoming
permanent false positives every time the scanner runs on its own test
directory. The exploration's second INFO note — "Scanner nondeterminism
across machines: PR section must name which layers ran" — is FR-20's
requirement, not a scanning-logic concern; it's satisfied entirely by the
PR-body template design in `data-model.md` §5, not by anything in the
scanner itself.

## §9 — Gate-deferred items (A-7): options + evidence, no decision

Per spec.md Assumptions A-7, these six items are intentionally left open.
Each is presented here as options with supporting evidence only — this
research pass does not resolve any of them.

**1. Default enforcement tier — flag-only vs. block-on-Critical (FR-14).**
- *Option A — flag-only default.* Matches feature 54's Phase 3.5 precedent
  (flag-never-block, `feature 54 spec.md` NFR-3) and is the lower-risk
  rollout choice for a brand-new, unbattle-tested scanner — a false
  positive on day one would otherwise hard-stop every build.
- *Option B — block-on-Critical default.* Matches this feature's own
  Problem Statement rationale (a secret reaching `git commit` today is
  already a real, demonstrated gap; A-2 confirms zero scanners exist on
  this dev machine today, so Layer 1's built-in scanner is the only thing
  standing between a leaked secret and `origin`) and SC-1's framing that a
  planted secret finding "always" surfaces "regardless of ... tier," which
  only matters if blocking is at least sometimes the outcome.
- *Evidence:* exploration Finding 6 recommends "block-on-Critical must
  mean terminate-before-commit/push" as the SEMANTICS if chosen, but does
  not recommend a default; spec.md defers the default explicitly (FR-14,
  A-7.1).

**2. Whether Layer 1 (secret) Critical findings ALWAYS hard-stop regardless
of configured tier (FR-16).**
- *Option A — no override; the general tier setting governs Layer 1 like
  every other layer.* Simpler mental model, one tier setting to reason
  about.
- *Option B — a stricter, Layer-1-specific override that always hard-stops
  on a Critical secret finding, independent of the general tier.* Matches
  the Problem Statement's emphasis that a leaked secret is categorically
  worse than a code-quality/SAST finding (the harm is external and
  effectively irreversible once pushed), and mirrors how
  `security-guard-mcp-browser.sh`'s production confirm-gate is the ONE
  denial `warn_only_mode` can never downgrade (`docs/security-model.md:78`)
  — an established repo precedent for "one narrow category of finding gets
  a non-downgradable rule even when a general downgrade knob exists."
- *Evidence:* FR-16 explicitly frames this as "stricter than the general
  tier setting"; FR-15's terminate-semantics contract applies unchanged
  either way (FR-16 introduces no second termination mechanism).

**3. Whether Layer 3 additionally invokes Smith's built-in
`/security-review` as a further input (FR-11).**
- *Option A — Layer 3 uses only this spec's from-scratch rubric (FR-11's
  10 areas).* Self-contained, no dependency on an unmaterialized
  capability.
- *Option B — Layer 3 ALSO invokes the built-in `/security-review` skill
  as an additional input, merged with the from-scratch rubric.*
- *Evidence:* exploration Finding 4 states plainly: "Built-in
  `/security-review` is not citable: not materialized anywhere on disk —
  the spec must define its own LLM rubric ... from scratch; optionally
  invoking the built-in as a layer is a fresh design decision (gate
  question)." This repo's own skill listing does show a `security-review`
  skill entry (system-level, "Complete a security review of the pending
  changes on the current branch") — but per the exploration and per FR-11,
  nothing in THIS repository's file tree materializes it as an invocable
  asset (no `skills/security-review/` directory, no SKILL.md), so Option B
  would depend on a capability outside this repo's own distribution.

**4. The Layer 3 review-subagent model choice — Sonnet vs. Haiku.**
- *Option A — Sonnet.* Matches Phase 3.5's own precedent exactly
  (`smith-build/SKILL.md:266-267`: "Pin the subagent to `model: sonnet`
  (not Haiku — this pass makes auto-fix judgment calls, not narrow
  classification/lookup)"). A security review across 10 rubric areas
  (FR-11) plausibly requires similar judgment quality, arguably more so
  since Layer 3 findings are never auto-fixed (no safety net) and this
  feature can hard-stop on them.
- *Option B — Haiku.* Cheaper/faster; used elsewhere in this repo for
  narrower classification tasks (`smith-navigate`'s "3-second budget"
  sub-agent; the Ledger's `reflection_model`/`reconcile_model` defaults,
  both Haiku, per `templates/config.default.json`).
- *Evidence:* Phase 3.5's own stated rationale for Sonnet ("makes auto-fix
  judgment calls, not narrow classification/lookup") does not transfer
  cleanly, since Layer 3 makes NO auto-fix calls at all (FR-13/OOS-4) —
  its judgment call is "assess severity and category of a security
  concern," which is arguably closer to classification than Phase 3.5's
  "should I safely rewrite this code" judgment. This cuts against a naive
  "just copy Phase 3.5's choice" default and is exactly why the spec left
  it open rather than defaulting to Sonnet by analogy.

**5. Whether smith-bugfix's Phase 7.1 gains this feature's pre-commit
secret-scan gate (FR-17).**
- *Option A — no change to smith-bugfix (as feature 54 did for its own
  bugfix-parity question, resolving "checklist parity only, no automated
  pass").* Keeps this feature's blast radius to `smith-build` only, lowest
  risk.
- *Option B — extend Layer 1's secret scan (not the full three-layer pass)
  to `smith-bugfix` Phase 7.1, before its existing commit step.* Closes
  the asymmetry the spec's Problem Statement itself names ("A smaller,
  related gap exists in `smith-bugfix`: its Phase 7.1 ... and 7.2 ...
  commit and push with zero scanning of any kind today").
- *Evidence:* US-8 and FR-17 both explicitly scope this spec's
  requirements to `smith-build` only "until answered" — no FR asserts
  smith-bugfix behavior either way, so either option is a clean,
  unconstrained extension if chosen.

**6. The exact schema depth of `security_review` beyond the enforcement
tier itself (FR-24).**
- *Option A — minimal: just `{"enforcement_tier": "<value>"}`.* Simplest
  possible schema; matches FR-24's literal floor requirement ("This spec
  requires only that the key exists ... and is the sole documented config
  home").
- *Option B — richer: per-layer enable flags (e.g.
  `{"enforcement_tier": ..., "layers": {"secret_scan": true, "sast": true,
  "llm_review": true}}`), an `excludes`/`allowlist_globs` override list,
  and/or a `layer1_secret_always_blocks` boolean tied to item 2 above.*
  Gives a project an escape hatch to disable a noisy layer without editing
  SKILL.md itself.
- *Evidence:* `data-model.md` §1's config schema table documents BOTH
  shapes as a superset design (fields present regardless of which the
  gate picks, with the narrower Option A simply being "every optional
  field omitted/defaulted") so this research pass does not need to commit
  either way — the schema is additive-safe under either resolution.
