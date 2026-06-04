---
feature: 31-workflow-gate-bootstrap
branch: 31-workflow-gate-bootstrap
generated: 2026-06-04
status: AWAITING ANSWERS
spec: ./spec.md
plan: ./plan.md
---

# Implementation Questions: Workflow-Gate Bootstrap Exemption

8 questions surfaced from the spec + plan. Recommendations carry rationale you can override.

---

## Q1: Where should the helper script live?

**Context:** The helper needs to be invocable from any project's skill prose. Two natural locations.

**Options:**
| Option | Description | Implications |
|--------|-------------|--------------|
| A | `~/.smith/scripts/create-active-workflow.sh` — global, installed by install-parsers.sh | Single source of truth. Same place as parser helpers. Easier gate exemption (one absolute path). Same install-drift risk as PR #27/#29. |
| B | `.specify/scripts/bash/create-active-workflow.sh` — per-project, installed by install.sh | Mirrors `clear-active-workflow.sh` (already per-project). No global state. Each project gets its own copy. Gate exemption needs to match either basename or use a relative path. |
| C | Both — global as primary, per-project as a vendored copy | Maximum compatibility. Doubles the install drift surface. Probably overkill. |

**Recommended:** **A** — global. The teardown helper at `.specify/scripts/bash/clear-active-workflow.sh` is conceptually paired with create- but they don't have to live in the same place; "where the parser-lib helpers live" feels like the cleanest home for create-. Basename exemption in the gate sidesteps the absolute-path coupling problem.

**Answer:** ___

---

## Q2: Should the helper also write a session-log start marker?

**Context:** Tonight's PRs hit a downstream issue where `workflow-summary.sh --totals-only` couldn't find the workflow's session log because the threading of `$SESSION` from Phase 1's marker creation to Phase 8's totals printout was inconsistent. The helper has a natural opportunity to also stamp the session log with a workflow-start entry.

**Options:**
| Option | Description | Implications |
|--------|-------------|--------------|
| A | Yes — helper appends a `[HH:MM:SS] workflow-start <branch>` line to `.smith/vault/sessions/<current>.md` | One-shot solution for the totals threading. Adds modest write. |
| B | No — keep helper single-responsibility (marker only); fix the totals threading separately | Smaller PR. Risks the totals issue staying unsolved (it bit us 5 times tonight). |
| C | Yes but optional — helper accepts `--no-session-log` to skip | Compromise. More CLI surface. |

**Recommended:** **A** — yes, write it. The bootstrap helper IS where the workflow becomes "real"; the session log is the natural anchor. The totals problem is then trivially solved by reading the workflow-start line, which is more robust than threading `$SESSION` through every skill phase.

**Answer:** ___

---

## Q3: How should the gate recognize the helper?

**Context:** The exemption rule needs a matching pattern. Options trade off security against fragility.

**Options:**
| Option | Description | Implications |
|--------|-------------|--------------|
| A | Match by basename: `create-active-workflow.sh` appearing at a word boundary in the command | Simple. Works regardless of where the helper is installed. Slight spoofing risk (a script with the same name elsewhere is exempt too) — mitigated by basename being unique. |
| B | Match by absolute path: `~/.smith/scripts/create-active-workflow.sh` (or expanded `$HOME`) | Tighter. Breaks if the install location changes (e.g. SMITH_HOME env override). |
| C | Helper sets a sentinel env var (`SMITH_GATE_BYPASS=1`) before its `exec` work; gate looks for the env var | Cleanest in principle. But Bash hooks see commands, not env vars set by the command itself. Wouldn't work for the standard PreToolUse JSON shape. |

**Recommended:** **A** — by basename, anchored to whitespace/`/`. The exemption is narrow because the basename is specific. R1 (in plan.md) tracks the mitigation: the regex `(^|[[:space:]/])create-active-workflow\.sh([[:space:]]|$)` matches the helper invocation but NOT `cat > create-active-workflow.sh` (the `>` puts a space before, the basename is followed by EOF/quote not space).

**Answer:** ___

---

## Q4: How should `.smith/index/` writes be allowed?

**Context:** `/smith-index --describe` writes to `.smith/index/files/*.meta` and gets blocked because `.smith/index/` is top-level under `.smith/` (not under `.smith/vault/` like the rest of the exemption list).

**Options:**
| Option | Description | Implications |
|--------|-------------|--------------|
| A | Add `.smith/index/` as a parallel safe-paths root (new SAFE_INDEX_DIRS list scoped to files/systems/config/logs) | Surgical. Mirrors the existing SAFE_VAULT_DIRS pattern. Easy to test. |
| B | Add `.smith/index/` to SAFE_VAULT_DIRS and update the comment to drop "Must be under .smith/vault/" | One-line change. But conflates two semantically-different exemptions and might confuse future readers. |
| C | Require `/smith-index` to drop its own marker (mirror the workflow skills' bootstrap) | Architecturally consistent — "if you're going to write files, you're a workflow". But `/smith-index --check` is read-only and shouldn't need a marker. Risks confusing the user experience. |

**Recommended:** **A** — separate SAFE_INDEX_DIRS list. Keeps the two semantic categories distinct (vault is workflow state, index is structural metadata). Easy to extend if more `.smith/<top-level>/` directories need similar treatment.

**Answer:** ___

---

## Q5: Should the helper validate inputs?

**Context:** Branch names with shell metacharacters could cause issues downstream (yaml escape, path injection). The helper is the natural validation point.

**Options:**
| Option | Description | Implications |
|--------|-------------|--------------|
| A | Yes — branch matches `[A-Za-z0-9/_.-]+`, workflow is one of an allowlist, worktree must be absolute | Defensive. Catches user error early. ~10 LOC of validation. |
| B | No — trust the caller (skills are vetted) | Smaller helper. Risk surfaces later if a third-party skill calls the helper with garbage. |
| C | Yes, but only for branch and workflow; trust paths | Middle ground. |

**Recommended:** **A** — validate. The cost is small (regex + allowlist check), the value is real (early failure beats mysterious YAML corruption later).

**Answer:** ___

---

## Q6: Should this PR also ship a complementary update to `clear-active-workflow.sh`?

**Context:** The existing `clear-active-workflow.sh` is in `.specify/scripts/bash/`. The new create- helper is going to `~/.smith/scripts/` (per Q1 default). Inconsistent locations might confuse maintainers.

**Options:**
| Option | Description | Implications |
|--------|-------------|--------------|
| A | Leave clear- where it is. They serve different lifecycles (create at start in any project, clear at end of any specific workflow). | Smaller PR. Inconsistency noted but accepted. |
| B | Move clear- to `~/.smith/scripts/` alongside create-. Both helpers, both global, both exempt from the gate. | Symmetry. But touches an established helper with existing call sites. |
| C | Move create- to `.specify/scripts/bash/` alongside clear-. Per-project for both. | Symmetry the other direction. Per Q1, less ideal. |

**Recommended:** **A** — leave it. Cross-helper symmetry is nice-to-have; not worth the regression risk of moving clear-. A future PR can dedup if it becomes painful.

**Answer:** ___

---

## Q7: Should the four SKILL.md migrations land in this PR, or as four follow-ups?

**Context:** Each skill's Phase 1 needs updating. Four files, mostly mechanical, but four risk surfaces.

**Options:**
| Option | Description | Implications |
|--------|-------------|--------------|
| A | All four in this PR — atomic migration. Either all skills use the new helper or none do. | Single PR review burden. But no intermediate broken state. |
| B | Helper + gate in PR-A; the four SKILL.md migrations in PR-B (or four separate PRs). | Each PR smaller. But there's a window where the helper is shipped but not used, and the gate's heredoc denial is still blocking legitimate bootstrap. |
| C | Helper + gate + SKILL.md-1 (smith-bugfix only as the smallest skill) in this PR; smith-new/debug/build follow as PR-B. | Phased rollout. Lets us validate one before doing the rest. |

**Recommended:** **A** — all four together. The gate denial is still happening today; partial migration means the unmigrated skills keep hitting the bug. The 4 SKILL.md edits are mechanical enough that the risk is low.

**Answer:** ___

---

## Q8: What about the gate's redirection regex false-positives?

**Context:** The regex `(^|[^0-9&])>>?[^&|]` false-positives on legitimate commands: `echo "-> something"`, `printf "a > b"`, even some `2>&1` patterns inside `$(...)` capture (which the gate tries to strip but the stripping logic has edge cases). Tonight I hit at least 3 of these.

**Options:**
| Option | Description | Implications |
|--------|-------------|--------------|
| A | Out of scope for this PR — bank as a follow-up. This PR is about bootstrap and `.smith/index/` only. | Smaller PR. False-positives keep biting until the follow-up. |
| B | Quote-aware regex — strip quoted strings before applying the redirection check. Solves the `echo "-> x"` and `printf "a > b"` cases. Doesn't solve all 2>&1 edge cases. | Real value-add. Moderate code change in the gate. |
| C | Bigger rewrite: use a real shell-command tokenizer to find redirection. | Most robust. Significantly bigger change; new dependency or significant bash logic. |

**Recommended:** **A** — out of scope. The bootstrap fix is the priority; false-positives are diagnosable case-by-case and BANK-005 (this PR can create the entry) tracks them. Keeps this PR focused.

**Answer:** ___

---

## Summary

Plan defaults match the recommended answers; if you accept all eight, the build proceeds with the plan as written. Override any answer with your preferred option (A/B/C) or a custom answer.
