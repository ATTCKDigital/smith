# Research: Clean Code Review Pass for Generated Code

All citations below are to the live files in this worktree
(`/tmp/smith-clean-code-review-pass`) as read during this research pass. Line
numbers are exact as of this read; §"Deferred Decisions" flags where a future
edit to `skills/smith-clean-code/SKILL.md` could silently invalidate a
hardcoded range (see D1).

## 1. Phase 3 → Phase 4 insertion anchor (`skills/smith-build/SKILL.md`)

- Phase 3 ends at line 250 (`### 3.3 Test Failure Handling`'s last bullet:
  "If tests cannot be fixed after 3 attempts: log the failure and continue /
  The release notes will flag this as requiring manual attention"), followed
  by a blank line 251, then `## Phase 4: Spec Updates (Subagent)` at line 252.
- FR-1 pins the new pass "strictly after Phase 3 (Testing) has passed and
  strictly before Phase 4 (Spec Updates) begins" — the insertion point is
  exactly the 251/252 boundary: the new phase's heading is inserted there,
  pushing the existing Phase 4 heading down by the new section's line count
  (no other line in the file needs to shift, since headings are `## `/`### `
  text, not a numbered list requiring renumbering).
- **This differs from the pre-spec exploration's guess.** The exploration
  report (`.smith/vault/explore/explore-2026-09-13-clean-code-review-pass.md`,
  WARNING #1) proposed inserting "between 5.2 (Push) and 5.3 (File-Size
  Scan)" — i.e., one phase later than where the spec ultimately landed via
  FR-1/FR-18. The spec resolved that WARNING by choosing the 3→4 boundary
  instead. Practical payoff of the spec's choice: Phase 5.1 (Commit) runs
  AFTER Phase 4, so any auto-fix edits applied in the new phase land in the
  **same commit** as the rest of the implementation and spec updates — no
  separate "fix" commit or a second push is needed. Had the exploration's
  original guess been followed, auto-fix edits applied after 5.2 (Push)
  would have required a second commit + a second push after the first one
  already ran.

## 2. Phase numbering convention: "N.5" for a later-inserted top-level phase

- `skills/smith-bugfix/SKILL.md:179` — `## Phase 3.5: Update \`.meta\`
  Descriptions for Touched Methods` sits, unrenumbered, between that file's
  own `## Phase 3: Implement the Fix` (line 165) and `## Phase 4: Docker
  Rebuild` (line 261).
- This exact heading is referenced BY NAME from two other skill files —
  `skills/smith-debug/SKILL.md:305` ("Task-spawning prose from
  `/smith-bugfix` Phase 3.5 step 3"), `:320` ("See `/smith-bugfix` Phase 3.5
  for full identification...") and `skills/smith-new/SKILL.md:469,480,485`
  — proving "N.5 = a phase inserted between two integers without
  renumbering" is a stable, cross-file, cross-referenced repo convention,
  not a one-off local hack.
- `skills/smith-build/SKILL.md` itself already contains a related but
  structurally DIFFERENT pattern: `### 4.5 System Spec Updates via
  \`.specify/systems/\`` (line 279) is an H3 subsection nested *under* `##
  Phase 4`, not a standalone phase sitting between two integers — it is an
  addendum to Phase 4's own topic (system-spec updates), not a new phase.
  It does not fit this feature's case (an entirely new, distinct phase that
  happens to sit between Phase 3 and Phase 4).
- **Conclusion for plan.md:** name the new section `## Phase 3.5: Clean
  Code Review Pass` (top-level H2), matching the smith-bugfix precedent
  exactly — same numeric slot (between 3 and 4), same rationale (insert
  without renumbering Phase 4 through 7 and every existing cross-reference
  to them: "Phase 5.4", "7.4.1", the Recovery Mode phase list, etc.).
  **Note for the final report:** this diverges from the task prompt's own
  placeholder example ("Phase 3.6") — 3.5 is free inside `smith-build`
  (no existing "3.4"/"3.5"/"3.6" heading), and is the numerically- and
  conventionally-correct slot given the repo's own established pattern.

## 3. Phase 3.3 bounded-attempts precedent (cite for FR-14)

- `skills/smith-build/SKILL.md:246-250` — "### 3.3 Test Failure Handling":
  "If tests fail: fix the code and re-run (up to 3 attempts per failure)...
  If tests cannot be fixed after 3 attempts: log the failure and continue —
  The release notes will flag this as requiring manual attention."
- FR-14 explicitly reuses this exact behavior rather than adding a second
  retry mechanism on top: when the Clean Code Review Pass's own single
  re-run of Phase 3 fails, Phase 3.3's OWN internal "3 attempts per failing
  test" budget is what governs recovery inside that re-run — the review
  pass adds no additional attempts, no additional retries, and no
  additional re-review beyond invoking Phase 3 exactly as it already exists.

## 4. Phase 5.3 / 5.3.1 scan structure + PR-body conditional-section mechanics (mirror target)

- `skills/smith-build/SKILL.md:317-346` (§5.3 File-Size Scan) and `:348-512`
  (§5.3.1 Description Coverage Scan) both follow the same shape: enumerate
  files changed vs `$BASE_BRANCH` → write findings, one per line, to a
  `/tmp/smith-build-*.txt` scratch file → "If `<file>` is non-empty,
  include a '`<Section Name>`' section in the PR body... If empty, omit the
  section entirely" → "This is a FLAG, never a blocker. Always proceed with
  PR creation."
- `/tmp/smith-build-oversized.txt` line format (line 333): `` - `<path>` —
  <N> lines (exceeds 300) ``.
- `/tmp/smith-build-coverage-misses.txt` line format (line 501, Python
  `print(f"- {qname} (id: {fid})")`): `` - <file>::<Class>::<method> (id:
  <16hex>) ``.
- PR-body template, `skills/smith-build/SKILL.md:514-552` (§5.4): the two
  conditional sections appear back-to-back (File Size Warnings, then
  Description Coverage Warnings), each opening with an
  include-if-non-empty comment and closing with short guidance text,
  immediately before `## Release notes`.
- **Mirror for the new section**: a third scratch file,
  `/tmp/smith-build-clean-code-findings.txt`, same one-bullet-per-finding
  shape, same non-empty→include / empty→omit template gate, placed AFTER
  Description Coverage Warnings (third section in the same family) and
  BEFORE `## Release notes` (see `data-model.md` §2 for the exact line
  format and `plan.md`'s file-by-file list for the template edit).
- **Important structural difference from 5.3/5.3.1 that the plan must
  account for**: both existing scans are DETERMINISTIC — 5.3 is a `wc -l`
  count, 5.3.1 is a parser-diff against `.meta`. Neither requires judgment.
  The Clean Code Review Pass's findings are NOT deterministic — "is this a
  god function," "is this fix behavior-preserving" are judgment calls a
  script cannot make. So unlike 5.3/5.3.1, the `/tmp/smith-build-clean-code-
  findings.txt` scratch file is populated by the REVIEW SUBAGENT itself
  (via its own Write/Edit-equivalent output), not by a bash+python scan
  block. The "reuse the 5.3/5.3.1 pattern" applies to the *file-handoff
  mechanics* (scratch file → conditional PR section), not to the *scanning
  mechanism* (which has no deterministic equivalent here). Practically,
  this means there is very little new shell code in this feature —
  effectively just the non-empty check at template-assembly time
  (`[ -s /tmp/smith-build-clean-code-findings.txt ]` or equivalent), not a
  new parser. This directly shapes `plan.md`'s Test Strategy: there's
  barely any bash surface to smoke-test under bash+zsh (NFR-2), unlike
  5.3.1's ~150-line embedded Python block.

## 5. Phase 2 inline clean-code checklist (terminology to align with)

- `skills/smith-build/SKILL.md:200-223` — the "Clean-code architecture"
  bullet block in Phase 2 (Implementation rules): small,
  single-responsibility functions/files; intention-revealing names (calls
  out `data`, `temp`, `handler`, `util`); guard clauses over deep nesting;
  separation of concerns (I/O, business rules, persistence in distinct
  units); no dead code/commented-out blocks/duplicated logic; "Honor the
  file structure `plan.md` prescribed"; plus two adjacent standalone
  paragraphs — "Reuse over duplication" (214-218) and "Keep files small"
  (219-222, cites the File Size Policy 300/500 thresholds and explicitly
  name-checks "the post-hoc File Size Warnings flag in the PR body
  (§5.3)" — i.e., Phase 2 *already* anticipates a post-hoc flag existing
  for file size specifically; this feature adds the clean-code analog for
  everything else in the checklist).
- The new Phase 3.5's review rubric (Review Process + Decision Rules) and
  its findings' "tenet violated" field should reuse this SAME vocabulary
  (small/single-responsibility, intention-revealing names, guard clauses,
  separation of concerns, dead code, duplication) rather than inventing a
  parallel taxonomy — a finding should read as "the thing Phase 2 already
  asked for, now verified," not a second, differently-worded rubric.

## 6. smith-bugfix Phase 3 pointer text (expand into checklist parity)

- `skills/smith-bugfix/SKILL.md:165-172` — `## Phase 3: Implement the
  Fix`, step 2: "Implement the fix — keep changes minimal and focused.
  When the fix adds or changes code, keep that code clean per the
  constitution's Clean Architecture Policy (small single-responsibility
  units, reuse existing components instead of duplicating). This does NOT
  license refactoring untouched surrounding code — see the constraints
  below."
- Step 3 ("Do NOT: refactor surrounding code / add features beyond the fix
  / modify unrelated files / add unnecessary abstractions"), lines
  173-177, is explicitly preserved unchanged by FR-20 — only step 2's
  single-sentence pointer expands into an inline bullet list.
- FR-19 names the exact six bullets to inline (small single-responsibility
  units; intention-revealing names; guard clauses over deep nesting;
  separation of concerns; no dead code or duplicated logic; reuse existing
  components over recreating them) — a SUBSET of smith-build's Phase 2
  checklist (§5 above), deliberately excluding the standalone "Reuse over
  duplication" and "Keep files small" paragraphs per FR-20's explicit
  non-duplication instruction.

## 7. smith-bugfix PR-body template (no warning sections today)

- `skills/smith-bugfix/SKILL.md:331-348` (§7.3): Summary / What was broken
  / What changed / Test plan (checkbox list) / attribution footer. No
  conditional warning sections exist here at all (unlike smith-build's
  §5.4) — confirms FR-19/FR-20's scope is checklist-text-only; nothing in
  this template needs to change for this feature as currently scoped. If
  the gate approves a lightweight automated pass for smith-bugfix (D4
  below), that would be the FIRST conditional warning section ever added
  to this template — genuinely new territory, no mirror target exists in
  this file today.

## 8. smith-clean-code rubric anchors

- `skills/smith-clean-code/SKILL.md:398-430` — Review Process: Summary /
  Main Issues (severity-classified — Critical: "likely bugs, security
  risks, broken behavior, or major architecture violations"; High:
  "hard-to-maintain code, poor testability, tight coupling, or unclear
  responsibilities"; Medium: "duplication, naming, complexity, or
  readability issues"; Low: "minor formatting, cleanup, or consistency
  issues") / Recommended Refactor Plan / Suggested Code Improvements /
  Final Checklist.
- `:487-501` — Decision Rules: 8 yes/no questions (readability,
  duplication, testability, separation of responsibilities,
  behavior-preservation, worth-it, abstraction-necessity, simplicity)
  closing with "If the answer is unclear, prefer the smaller and safer
  change" (line 500) — the literal text FR-7 quotes for fix-safety
  judgment.
- `:363-382` ("What You Should Avoid"): "Change behavior unless explicitly
  requested", "Rewrite the full file unnecessarily", "Rename exported
  functions... without checking usage", "Remove code unless you are
  confident it is unused" — the most relevant guardrails for an
  AUTOMATED, non-interactive auto-fixer, since a human reviewer's judgment
  calls are exactly the class of finding FR-7 requires to be flagged
  rather than auto-fixed when unclear.
- **What a rubric-delivery mechanism actually needs** (feeds D1 below):
  NOT the full 539-line file. The review pass needs Review Process
  (398-430), Decision Rules (487-501), and arguably "What You Should
  Avoid" (363-382) for auto-fix guardrails. "What You Should Do"
  (340-360), "Cleanup Process" (384-395, interactive-editing-specific),
  "Tone" (504-522), and "Output Format After Editing" (433-461 — a
  DIFFERENT output shape than this feature's own required contract, see
  `data-model.md` §1) are not needed by an autonomous review-and-flag
  subagent and would only add noise/token cost if inlined or Read
  wholesale.

## 9. smith-research adversarial-verification subagent (review-subagent prompt-structure precedent)

- `skills/smith-research/SKILL.md:155-172` (Phase 6a): decompose into
  atomic claims → gather evidence per claim → spawn a `general-purpose`
  verifier subagent with an explicitly adversarial prompt ("Default to
  UNVERIFIED. Mark supported ONLY if a provided chunk directly ENTAILS the
  claim... Topical similarity is NOT support.") → record a verdict +
  supporting evidence ids per claim → strip/flag unresolved claims in the
  final artifact.
- Structural parallel to this feature's review pass:
  1. Decompose the diff into atomic FINDINGS (one violation each) rather
     than one holistic "review the whole diff" prompt — mirrors "decompose
     into ATOMIC claims."
  2. The subagent's prompt should bias conservatively — "default to
     UNVERIFIED" is the direct structural analog of FR-7's "if fix-safety
     is unclear, flag, never fix."
  3. Record a verdict PER finding with supporting rationale, not a prose
     paragraph — matches this feature's own structured-findings contract
     (`data-model.md` §1).
- **Difference — model choice.** No `model:` override appears anywhere in
  `smith-research/SKILL.md` for the verifier or section-writer subagents —
  it runs on whatever model the parent session is (Sonnet-class, since
  smith-research is itself a top-level generative skill). This is the
  closest FUNCTIONAL precedent for the review-model question and it does
  NOT lean Haiku — see D2 below for the full tension against the
  structural (narrow-classification) Haiku precedents.

## Deferred Decisions — options + evidence only (the questions gate decides, not this plan)

Per spec.md Assumption A-6, these five items are intentionally left open.
Each option below is evidenced from this repo; none is recommended here —
recommendation-with-reasoning is the gate's job per
`skills/smith-new/SKILL.md:322` ("Recommended: [...] — Reasoning").

### D1 — Rubric delivery mechanism (FR-5)

**Option A — Inline prompt text.** Embed a condensed version of Review
Process + Decision Rules (see §8 above for which subsections matter)
directly in the Phase 3.5 subagent-invocation prompt in
`smith-build/SKILL.md`.
- For: `smith-build/SKILL.md:201-204` already states the precedent reason
  inline text exists at all — "do NOT rely on being able to load that
  skill, as build subagents may not have skill access." `CHANGELOG.md:22`
  confirms this was a deliberate PR #49 decision ("Clean-code guidance made
  subagent-safe... inlines a compact clean-code checklist directly, since
  build subagents may not have skill-loading access"). Inline text has
  zero runtime file-path dependency — it cannot go stale relative to a
  moved/renamed file, and behaves identically from a worktree, the primary
  repo, or a consumer project with a globally-installed Smith.
- Against: Review Process + Decision Rules content (§8) would need to be
  hand-duplicated into `smith-build/SKILL.md` and kept in sync manually if
  `smith-clean-code/SKILL.md` ever changes those sections. NFR-5 forbids
  editing `smith-clean-code/SKILL.md` itself, but says nothing about a
  second, hand-maintained copy elsewhere silently drifting from the
  original over time.

**Option B — Subagent Reads the file at runtime.** Phase 3.5 instructs the
review subagent to Read `skills/smith-clean-code/SKILL.md` (repo copy),
falling back to `~/.claude/skills/smith-clean-code/SKILL.md` (installed
copy) per FR-5's own wording, optionally scoped to specific sections.
- For: single source of truth — the rubric can never drift from what
  `smith-clean-code/SKILL.md` actually says, satisfying NFR-5's spirit
  even more directly than Option A. Consuming projects that refresh via
  `/smith-update` get rubric updates automatically without a second edit
  to `smith-build/SKILL.md`.
- Against — **line-range fragility**: if the subagent is told to read only
  lines 398-430/487-501 (to avoid the token cost of the other ~490 lines
  per §8's finding), any future edit to `smith-clean-code/SKILL.md` that
  shifts line numbers (e.g., inserting a paragraph above line 398) silently
  breaks the reference — the subagent reads the wrong slice and nothing in
  the pipeline notices, since this is markdown prose consumed by an LLM,
  not code a linter would fail on. A section-heading anchor ("read from
  `## Review Process` to the next `## ` heading") is more robust to future
  edits than a hardcoded line range, but the Read tool takes offset/limit
  as line numbers, not heading text — heading-anchored reading requires
  the subagent to first grep for the heading to locate its current line
  number before re-reading the target range (exactly what this research.md
  itself had to do by hand rather than trusting the spec's own line
  citations, which is itself a small piece of evidence for how easily
  these numbers drift). If the gate picks a line-range Read, the plan
  should instruct the subagent to grep for `^## Review Process` /
  `^## Decision Rules` first rather than hardcoding "398-430" into
  `smith-build/SKILL.md` prose.
- Also against: reintroduces the exact tool-access uncertainty PR #49
  already worked around for Phase 2 — Option B only works if the review
  subagent has Read access to arbitrary repo files (very likely true, since
  Read is a base tool rather than a Skill-tool invocation, but worth the
  gate confirming explicitly, since PR #49's whole rationale was
  documented uncertainty about what tools build subagents have).

### D2 — Review model choice

**Option A — Haiku.** Repo-wide precedent for narrow, structured-output,
non-blocking classification passes: `smith-navigate` (`model:
claude-haiku-4-5`, "3-second budget", `smith-navigate/SKILL.md:5`),
`smith-index --describe` Task spawns (`smith-index/SKILL.md:123,218`),
`smith-bugfix` Phase 3.5's touched-method describer (`model:
claude-haiku-4-5`, `SKILL.md:232`), `smith-debug`'s identification Task
(`model=claude-haiku-4-5`, `SKILL.md:311`), and both workflows' own
post-workflow reflection/reconciliation sub-agents ("configured reflection
model (default: Haiku)", `smith-build/SKILL.md:688`,
`smith-bugfix/SKILL.md:403`). All share this feature's shape: bounded
input, structured/classified output, non-interactive, non-blocking.
- Latency/cost matches NFR-1 ("no prompts... no pauses") and US-2's "no
  added latency beyond the review itself" — a review pass runs on EVERY
  build regardless of whether it finds anything, so its per-call cost is
  paid unconditionally.

**Option B — Sonnet-class (inherited / no override).** The single closest
FUNCTIONAL precedent — smith-research's Phase 6a adversarial verifier (§9
above) — does NOT override to Haiku; it runs on the parent session's
(Sonnet-class) model. Judging "is this fix behavior-preserving" is closer
to that adversarial-verification judgment call (Decision Rules' own "if
the answer is unclear" framing) than to the rote classification/lookup
tasks the Haiku precedents perform (describing an already-parsed method's
purpose, navigating a manifest, retrying with known antipatterns). A wrong
"behavior-preserving" call has real consequences — FR-8's Critical/
behavior-change case exists precisely because this judgment can go wrong —
arguing for the stronger model on the one part of this pipeline that
decides whether code gets auto-edited.
- No repo precedent currently uses an EXPLICIT Sonnet override for a
  review/classification task — Option B means "no override," a slightly
  different shape than the Haiku options' explicit `model:` lines. Also
  worth the gate's attention: a hybrid (Haiku classifies/tags severity, a
  second Sonnet-class pass judges only the auto-fix-eligibility question
  for findings Haiku flagged as "maybe auto-fixable") is not spec'd
  anywhere in spec.md/FRs — mentioned here only because both precedents
  exist and point in different directions, not as a recommendation.

### D3 — Severity threshold for PR-body inclusion (FR-16 says "each remaining finding," no floor stated)

No existing precedent either way: neither File Size Warnings nor
Description Coverage Warnings has a severity dimension at all — both are
binary (over/under a line count; described/undescribed).

**Option A — All severities.** Matches FR-16's literal "each remaining
finding" wording most directly. Risk: a PR body cluttered with Low-severity
formatting nitpicks could bury Critical/High findings in the same list.

**Option B — Medium+ (exclude Low).** Matches Review Process's own Low
definition ("minor formatting, cleanup, or consistency issues") — the kind
of thing not usually worth interrupting a PR review for. Keeps the section
focused on what a reviewer should act on.

**Option C — High+ (Critical and High only).** Most conservative; reserves
the section for findings with real maintainability/architecture
consequences. Risk: a genuine Medium-severity duplication finding
(explicitly named in Review Process's own Medium definition) never
surfaces anywhere in the pipeline — silently discarded, with nothing else
recording it.

### D4 — smith-bugfix lightweight automated pass (beyond FR-19/FR-20 checklist parity)

**Option A — No (checklist parity only — this feature's current FR-19/
FR-20 scope).** Matches PR #49's own established "bugfix stays lighter"
precedent (§6/§7 above: a 4-line pointer vs. build's 22-line checklist,
even BEFORE this feature; no PR-body warning sections exist in bugfix's
template today). Zero new invocation-time cost added to the lightest,
most-frequently-run workflow.

**Option B — Yes, a diff-scoped automated pass.** smith-bugfix diffs are,
by definition (Phase 1 scoping: "1-3 files with no design ambiguity"),
much smaller than smith-build diffs — a lightweight pass could reuse
whatever Phase 3.5 mechanism smith-build ends up with, scoped to bugfix's
smaller diff. Non-zero marginal cost vs. Option A's zero. The exploration
report's own Recommendations list this as an open gate question without
leaning either way.
- No FR in the current spec describes what "lightweight" would mean
  operationally (no bounded-loop equivalent, no PR-body section spec, no
  auto-fix policy is defined for bugfix anywhere) — if the gate picks
  Option B, that is materially more design work than this plan currently
  accounts for, and would likely need its own follow-up research/plan
  pass rather than a same-cycle bolt-on, given FR-20's explicit "MUST NOT
  introduce an automated review-and-auto-fix pass" for *this* feature.

### D5 — smith-implement parity (inline-checklist treatment)

`skills/smith-implement/SKILL.md` carries a single-line reference to
clean-code guidance today (per the exploration report's INFO note) —
candidate for the same checklist-inlining treatment FR-19/FR-20 give
smith-bugfix.

**Option A — Yes, same-cycle.** Consistent completeness — if the goal is
closing the "Phase 2 has the checklist, everyone else has a pointer" gap,
`smith-implement` has the identical gap smith-bugfix had. Low incremental
cost if the same six bullets (§6 above) are reused verbatim.

**Option B — No, out of scope for this feature.** spec.md's Problem
Statement and Overview name only smith-build (review pass) and
smith-bugfix (checklist parity) as this feature's two deliverables; Out of
Scope (OOS-1..OOS-5) does not mention smith-implement at all — a silence
in the spec's own scope section, not an explicit exclusion. Option B reads
that silence as "not yet decided," not "implicitly out." Per this task's
own instruction, `plan.md`'s file-by-file list includes
`skills/smith-implement/SKILL.md` ONLY if the gate answers D5 as yes.

## Additional finding surfaced during research (feeds the report, not a numbered deferred item)

**FR-9's "already applied to implementation edits" premise is only true
for smith-bugfix, not smith-build.** FR-9 requires auto-fix edits to
update `.meta` "using the same touched-method-id convention... already
applied to implementation edits." Reading `smith-build/SKILL.md` in full
(this research pass) found NO step in Phase 2 (Implementation) that
proactively writes `.meta` descriptions — smith-build's implementation
subagents write code only; `.meta` coverage is checked PASSIVELY, after
the fact, by §5.3.1's scan, which flags gaps in the PR body and tells the
user to either run `/smith-index --describe --system <name>` or "rely on
the next `/smith-bugfix`/`smith-new` workflow to update descriptions for
touched methods in-context" (`smith-build/SKILL.md:543-545` — this line
is itself smith-build admitting it does not do this proactively). The
proactive, per-file "parse → diff ids against `.meta` → spawn a Haiku Task
to write descriptions → apply" procedure (FR-9's actual mechanism) exists
today ONLY in `smith-bugfix/SKILL.md:179-259` (Phase 3.5).

Consequence for `plan.md`: implementing FR-9 literally means the new
`smith-build` Phase 3.5's auto-fix step introduces the FIRST proactive
`.meta`-write mechanism smith-build has ever had — by invoking (not
restating) `smith-bugfix/SKILL.md:189-259`'s existing procedure, scoped
ONLY to files touched by auto-fixes. This is a deliberate, narrow
addition: it does NOT retrofit proactive `.meta` updates onto smith-build's
regular Phase 2 implementation edits (those keep using the existing
passive §5.3.1 scan, unchanged — no FR asks for that, and doing it anyway
would be scope creep beyond FR-9). `plan.md`'s reuse-before-create list
names this distinction explicitly so implementation doesn't accidentally
over-scope it.

## Scope note on FR-9's extension list vs. §5.3's

§5.3 (File Size Scan) covers `.py, .js, .jsx, .ts, .tsx, .css, .html, .sh`.
§5.3.1 (Description Coverage Scan) and FR-9 both cover only `.py, .js,
.jsx, .ts, .tsx` — the parseable-method extensions. The new Phase 3.5's
`.meta`-update sub-step should scope to the narrower §5.3.1/FR-9 list, not
§5.3's broader one, since `.meta` method-level descriptions don't apply to
CSS/HTML/shell files.
