# Implementation Questions: Inline Security Review Pass

**Generated**: 2026-09-13
**Feature**: [spec.md](./spec.md)
**Plan**: [plan.md](./plan.md)
**Status**: ANSWERED

> Pre-decided (not re-opened): three-layer design; pre-commit placement for all layers (Phase 3.6); built-in regex secret scanner as real script + tests; presence-detected gitleaks/SAST; no auto-fix in v1; `security_review` key in .smith/config.json; terminate-semantics for any blocking behavior; feature is QUEUED after this gate.

---

## Q1: Default enforcement tier for SAST/LLM findings?

**Context**: The enforcement decision table (data-model) supports `flag` and `block_on_critical` tiers per layer. Repo convention for the 5.3-family and feature 54 is flag-never-block; this feature deliberately may block — the question is the shipped DEFAULT for non-secret findings (secrets are Q2).

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | Default `flag` — SAST/LLM findings advisory; operators opt into block_on_critical via config | Consistent with every existing advisory surface; no surprise terminated builds on LLM judgment calls (false-positive Critical would kill a build); cautious rollout for a brand-new judgment-based pass. |
| B | Default `block_on_critical` — Critical SAST/LLM findings terminate pre-commit | Strongest posture out of the box; but a hallucinated/false-positive Critical from the LLM layer hard-stops an autonomous build — high blast radius for an unproven layer. |

**Recommended**: A — ship advisory, let confidence build, opt into blocking per project.

**Answer**: A (recommendation accepted) — default `flag` for SAST/LLM findings; `block_on_critical` opt-in via config.

---

## Q2: Do pre-commit SECRET findings always hard-stop, regardless of tier?

**Context**: The entire pre-commit placement exists because a pushed secret is irreversibly leaked. A flag-only secret finding that then proceeds to commit+push is self-defeating — the flag would document the leak it just permitted. Deterministic regex findings have far lower false-positive risk than LLM judgment (and the allowlist marker + lockfile excludes handle the known noise).

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | Yes — deterministic-layer secret findings ALWAYS terminate before commit, regardless of configured tier (the "sole non-bypassable" precedent, mirrored from the browser prod confirm-gate) | The one guarantee that makes the feature's core promise real; false positives are handled by the allowlist marker, not by weakening the stop; workflow terminates cleanly with worktree preserved + hard-stop marker. |
| B | No — secrets follow the configured tier like everything else | Config simplicity; but `flag` tier would knowingly push detected secrets — arguably worse than no scanner (false assurance). |

**Recommended**: A — non-bypassable, matching the one existing precedent for absolute denials.

**Answer**: A (recommendation accepted) — deterministic secret findings always terminate pre-commit, non-bypassable by tier; allowlist marker is the false-positive escape hatch.

---

## Q3: Invoke the built-in /security-review skill as an additional layer?

**Context**: Claude Code ships a `/security-review` built-in, but it is not materialized on disk — its methodology is opaque and can't be cited or version-pinned; there is no repo precedent for invoking a built-in skill from inside a build workflow's subagent context (skill loading in subagents is exactly the limitation features 54/55 design around).

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | No for v1 — the spec's own rubric is the LLM layer; revisit once the pass has mileage | Deterministic, self-contained, version-controlled methodology; avoids depending on an opaque, subagent-unreachable mechanism. |
| B | Yes — parent session invokes /security-review as an extra pass when available | Extra defense-in-depth; but runs only in interactive parent contexts (not scheduler/queued builds — exactly where this feature will usually run), adding machine-dependent nondeterminism. |

**Recommended**: A — especially given this feature's builds will run from the QUEUE, where a parent-session-only layer would silently never fire.

**Answer**: A (recommendation accepted) — no built-in /security-review layer in v1; own rubric only.

---

## Q4: Which model runs the LLM security review?

**Context**: Feature 54 pinned its review subagent to `sonnet` because it edits code. This pass does NOT auto-fix (v1) — pure classification — which by repo precedent leans Haiku; but security misses are costlier than style misses.

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | Sonnet | Stronger judgment on subtle issues (authz logic, injection reachability); consistency with 3.5's pin; costlier per build. |
| B | Haiku | Cheap, matches classification precedent; weaker on subtle security reasoning — the category where a miss matters most. |

**Recommended**: A — security review is the wrong place to economize; revisit if cost data argues otherwise.

**Answer**: C (option set expanded during gate to include opus/fable aliases) — **Opus default** with an optional `review_model` config key in the `security_review` schema (accepts haiku|sonnet|opus|fable) so Mythos-tier accounts can opt into Fable and cost-sensitive projects can downshift. Fable rejected as shipped default (not universally available — queued/scheduler builds on non-Mythos accounts would fail); Sonnet/Haiku rejected as defaults (task profile: once-per-build, bounded diff, miss-cost asymmetry favors stronger reasoning).

---

## Q5: Does smith-bugfix get the pre-commit secret scan too?

**Context**: smith-bugfix Phase 7.1-7.2 commits and pushes with zero scanning today — identical leak risk, and the deterministic scanner is cheap (no LLM, no latency concern for the "streamlined" workflow). The LLM/SAST layers would NOT come along (bugfix stays light, per the feature-54 parity precedent).

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | Yes — deterministic secret scan (with Q2's semantics) before bugfix's 7.1 commit; LLM/SAST layers stay build-only | Closes the identical leak path in the second-most-used commit pipeline for one cheap script invocation. |
| B | No — build-only for v1 | Smaller diff; leaves a known uncovered commit+push path. |

**Recommended**: A — the scanner exists either way; not wiring it into the other pipeline that pushes code is hard to justify.

**Answer**: A (recommendation accepted) — smith-bugfix gets the deterministic secret scan pre-commit with Q2 semantics; LLM/SAST layers remain build-only.

---

## Q6: Config schema — ship the proposed minimal shape as-is?

**Context**: data-model proposes `security_review: { enforcement_tier: "flag" | "block_on_critical", scanners: { gitleaks: "auto" | "off", semgrep: "auto" | "off", bandit: "auto" | "off" }, exclude_paths: [...defaults], allowlist_globs: [...] }` — minimal v1, extensible later.

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | Ship as proposed | Small, covers every gate decision's knob, defaults encode the answers above; extension is additive later. |
| B | Add per-layer tier overrides now (e.g. separate tiers for SAST vs LLM) | More control, more surface to document/seed/test for a v1 with zero field feedback. |

**Recommended**: A — minimal now, extend on evidence.

**Answer**: A (recommendation accepted) — minimal schema shipped as proposed, plus `review_model` (default "opus") per Q4.
