# Data Model: Clean Code Review Pass for Generated Code

This document specifies the SHAPES this feature introduces — a review
subagent's required output contract, a `/tmp` handoff file format, an
auto-fix eligibility decision table, and the bounded-loop state contract.
All are prose-level (markdown/table) specifications for `plan.md` and the
eventual `smith-build/SKILL.md` prose to encode — **no code is prescribed
here**, matching this feature's scope (SKILL.md prose + `.meta` reuse only,
per spec.md's Success Criteria SC-5 boundary).

**Note on section numbering**: `smith-build/SKILL.md` and
`smith-bugfix/SKILL.md` already cite an EARLIER, unrelated `data-model.md`
by section number (e.g. "data-model.md §9", "§4", "§1.1", "§3.2" — the
`.meta` touched-methods feature, PR #23-era). Those citations point to that
prior feature's own `data-model.md`, not this one. The sections below
(§1-§4) are local to THIS document only; do not renumber or merge with
those citations.

## §1 — Review subagent REQUIRED output contract

The review subagent MUST return one entry per finding, in this markdown
shape (a JSON-per-finding array is an acceptable internal working format
for the subagent, but what it hands back to the orchestrating phase — and
what ultimately reaches `data-model.md` §2's `/tmp` file for any finding
NOT resolved — must be reducible to this same field set without loss):

```
### Finding <N>
- **Severity:** Critical | High | Medium | Low
- **Location:** <path>:<line> (or <path>:<start>-<end> for a range)
- **Tenet violated:** <short label, drawn from smith-clean-code's own
  vocabulary — e.g. "Deep nesting", "Duplicated logic", "God
  function/file", "Unclear naming", "Mixed responsibilities" — see
  research.md §5 for the terminology to align with>
- **Behavior-preserving fix available:** true | false
- **Fix-safety:** clear | unclear   (per Decision Rules' "if the answer is
  unclear, prefer the smaller and safer change" — smith-clean-code/
  SKILL.md:500)
- **Auto-fix eligible:** true | false   (derived — see §3 Decision Table;
  never true when Severity=Critical AND Behavior-preserving=false, per
  FR-8, regardless of any other field)
- **Fix applied:** true | false   (set only after the auto-fix edit is
  actually made; an eligible finding whose fix errors out during
  application is NOT "applied" and must fall through to flagged)
- **Rationale:** <1-2 sentences — what's wrong and why the eligibility
  verdict above follows from it>
```

Every field is required for every finding — a finding missing any field
cannot be routed by §3's decision table and must be treated as
"fix-safety: unclear" (flag, never fix) as the fail-safe default, mirroring
smith-research's "default to UNVERIFIED" posture (research.md §9).

## §2 — `/tmp` handoff file format (mirrors `/tmp/smith-build-oversized.txt`)

Only findings where `Fix applied: false` are written to
`/tmp/smith-build-clean-code-findings.txt` — an auto-fixed finding
contributes nothing to this file (it already resolved; see FR-15, "every
finding that is neither auto-fixed nor otherwise resolved").

One line per finding, in the same "flat bullet, no nested detail" style
`/tmp/smith-build-oversized.txt` and `/tmp/smith-build-coverage-misses.txt`
already use (research.md §4):

```
- **[<Severity>]** `<path>:<line>` — <one-line description> (tenet: <Tenet violated>)
```

Example, mirroring the existing files' own example rows:

```
- **[High]** `services/billing/webhook.py:142` — God function mixes request
  validation, HTTP retry logic, and dead-letter persistence in one 80-line
  method (tenet: Mixed responsibilities)
- **[Medium]** `frontend/src/lib/api/products.ts:58` — Near-duplicate of
  `fetchOrderBundle`'s pagination-assembly logic (tenet: Duplicated logic)
```

This is a strict reduction of §1's full per-finding contract to exactly the
fields the PR-body template (`plan.md`'s Phase 5.4 edit) needs to render —
Severity, Location, and a description that folds in the Tenet. The richer
fields (Behavior-preserving, Fix-safety, Rationale) stay internal to the
review pass's own reasoning and are not surfaced in the PR body, consistent
with §5.3/§5.3.1's own terse one-liner-per-finding style (no rationale
column in either existing scan's output).

**Severity threshold — resolved (Q3): Medium and above are written to this
file as individual lines** in the format above; **Low-severity findings are
NOT written as individual lines.** Instead, if one or more Low-severity
findings were not auto-fixed, the file gains exactly one additional
trailing line, written after all Medium+ lines:

```
+ N low-severity notes
```

— where N is the count of not-auto-fixed Low-severity findings. This line
is omitted (not written with N=0) when there are no such findings. A
Low-severity finding is still fully specified internally per §1's contract
(nothing is dropped from the review subagent's output); it simply is not
expanded to its own line in this scratch file or the PR body — §5 embeds
this file's contents in the PR body unchanged, so the file itself is the
single source of truth for both the Medium+ lines and the low-severity
count line.

## §3 — Auto-fix eligibility decision table

Two independent boolean dimensions determine the outcome; **severity is
NOT an independent third dimension** — it only interacts via the FR-8
special case (which is itself already implied by the general rule, stated
twice for emphasis exactly as spec.md's own FR-8/OOS-4 redundancy already
does):

| Behavior-preserving? | Fix-safety | Outcome | FR/Rule |
|---|---|---|---|
| No | (any) | **FLAG** — never auto-fix | FR-7(b), and FR-8 when Severity=Critical |
| Yes | unclear | **FLAG** — never auto-fix | FR-7(a) |
| Yes | clear | **AUTO-FIX** | FR-7 (both conditions satisfied) |

Read as: a finding is auto-fix eligible **if and only if** it is
behavior-preserving AND its fix-safety is clear/unambiguous. Severity
plays no role in this table except as the trigger for FR-8's
"regardless of configuration" reinforcement of row 1 — a Critical finding
that happens to ALSO be behavior-preserving-and-clear is eligible exactly
like any other row-3 finding (FR-8 only ever removes eligibility, it never
grants it).

Worked examples:
- Critical, not behavior-preserving, (fix-safety moot) → FLAG (FR-8,
  always, no override).
- Critical, behavior-preserving, clear → AUTO-FIX (e.g., extracting a
  well-isolated helper function from a Critical-rated god-function, where
  the extraction provably changes nothing about runtime behavior).
- High, behavior-preserving, unclear → FLAG (FR-7(a)).
- Low, behavior-preserving, clear → AUTO-FIX (e.g., renaming a local `tmp`
  variable to an intention-revealing name, in a scope with no external
  callers, no serialization, no reflection — genuinely can't affect
  behavior).

## §4 — Bounded-loop state contract (prose-level, no code)

Three flags track the pass's progress through its single, non-repeating
cycle (FR-13/NFR-4). These are tracked internally by the workflow across
Phase 3.5's steps — no file format is prescribed for persisting them (this
is a within-single-build-invocation contract, not a resumable/checkpointed
state machine); logging their final values to the vault session log via
the existing Vault Logging convention (both SKILL.md files' "log
significant events" pattern) is RECOMMENDED for auditability but not
separately required by any FR.

| State | Type | Set when | Constraint |
|---|---|---|---|
| `reviewed` | bool | The review subagent has returned its findings (§1) | Set exactly once per build; the review subagent is invoked exactly once (FR-13) — never re-invoked after fixes, never re-invoked on re-test failure (FR-14) |
| `fixes_applied` | int (count) | After the auto-fix batch (§3's AUTO-FIX rows) is applied | 0 if no finding was auto-fix eligible (US-2) or the batch made zero successful edits; >0 otherwise. This count, not a bool, is what gates `retest_done` below |
| `retest_done` | bool | Set to `true` iff `fixes_applied > 0`, immediately after running exactly one full Phase 3 re-run (3.1 → 3.2 → 3.3) | FR-11/FR-12: `fixes_applied == 0` ⟹ `retest_done` MUST stay `false` and Phase 3 MUST NOT run again. `fixes_applied > 0` ⟹ `retest_done` becomes `true` after exactly one re-run, regardless of that re-run's PASS/FAIL outcome (FR-14) — a failing re-test still sets `retest_done = true`, it does not leave the flag `false` pending another attempt |

Transition diagram (textual, since this is a linear bound, not a real state
machine with branches worth diagramming):

```
reviewed=false, fixes_applied=0, retest_done=false   (Phase 3.5 starts)
  → review subagent runs once → reviewed=true
    → auto-fix batch runs (0 or more edits) → fixes_applied = N
      → if N == 0: retest_done stays false; Phase 3.5 ends here (US-2)
      → if N  > 0: exactly one Phase 3 re-run happens → retest_done=true
                    (re-run's own PASS/FAIL is handled entirely by Phase
                    3.3's existing bounded-attempts behavior — FR-14; it
                    does NOT feed back into reviewed/fixes_applied/
                    retest_done, none of which ever reset within this
                    build)
```

No path in this diagram loops back to an earlier state — the diagram has
no back-edges, which is the prose equivalent of NFR-4's "deterministic and
bounded independent of how many findings are found."

## §5 — PR-body "Clean Code Review" section — contract tying §1/§2 to the template

When `/tmp/smith-build-clean-code-findings.txt` (§2) is non-empty, the PR
body (`plan.md`'s Phase 5.4 template edit) gains:

```
## Clean Code Review
<contents of /tmp/smith-build-clean-code-findings.txt>

This is a FLAG, never a blocker. Always proceed with PR creation.
```

— unchanged from the original embed-the-file-contents-verbatim mechanics;
§2's severity threshold (Q3, resolved: Medium+ findings listed
individually, Low findings folded into one trailing "+ N low-severity
notes" line) is what shapes those contents, not a second filtering step
here. Wording mirrored verbatim in spirit from §5.3's own closing line
(FR-17), placed immediately after the existing Description Coverage
Warnings section and before `## Release notes` (research.md §4). The file
is empty only when there are zero remaining Medium+ findings AND zero
remaining Low-severity findings (N=0, so §2's trailing line is itself
omitted) — whether because there were zero findings at all or every
finding was auto-fixed; in that case the section is omitted entirely,
identical to §5.3/§5.3.1's own omit-when-empty behavior (FR-16). If only
Low-severity findings remain (N>0, zero Medium+ lines), the file is still
non-empty and the section renders with just the one-line count.
