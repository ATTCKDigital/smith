# Implementation Questions: MCP-First Browser Verification

**Generated**: 2026-09-12
**Feature**: [spec.md](./spec.md)
**Plan**: [plan.md](./plan.md)
**Status**: ANSWERED

---

## Q1: Does warn-only mode bypass the production confirm-gate?

**Context**: FR-3 says the new guard respects `warn_only_mode` "the same way" as the sibling guards (blanket downgrade of denials to warnings), but FR-4 and the requirements checklist say production confirmation is "mandatory and non-bypassable via warn-only mode". Direct conflict on one decision-table cell.

**Question**: When `warn_only_mode: true`, should interaction tools against a production-labeled target still require explicit human confirmation?

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | Confirm-gate is non-bypassable — warn-only downgrades everything EXCEPT production interactions | Safest; warn-only stays useful for rollout tuning without ever disarming the one gate protecting real-cookie destructive actions. Slightly inconsistent with sibling guards. |
| B | Warn-only downgrades uniformly, like the sibling guards | Perfectly consistent with existing guard semantics; but a single config flag silently disarms production protection — the exact failure mode the exploration flagged as BLOCKING. |

**Recommended**: A — the production confirm-gate is the resolution of a blocking safety finding; a mode intended for tuning noise must not be able to disarm it.

**Answer**: A — production confirm-gate is non-bypassable; warn-only downgrades everything else.

---

## Q2: Where does the guard read the staging/production URL table from?

**Context**: The guard is a `PreToolUse` hook that parses JSON via `python3` (NFR-4); it structurally cannot parse a markdown table in CLAUDE.md. FR-13 currently allows the table to exist only as prose — meaning a clean install could ship a guard with zero actual production enforcement until someone hand-mirrors the table into JSON.

**Question**: What is the machine-readable source of truth for environment URLs, and how is it seeded?

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | `.smith/security-config.json` `browser_verification.urls` is the source of truth; `/smith` init and `/smith-update` seed the key (empty lists) so the file/schema always exists; CLAUDE.md table is human-readable documentation generated from/alongside it | Guard always has a well-formed config to read; enforcement gap closes at install time; matches existing guard precedent for which file guards read. |
| B | CLAUDE.md table is the source; a helper script parses the markdown table into JSON on demand | No second file, but adds fragile markdown parsing to a security hook — the opposite of the defensive-parsing idiom the guards use. |
| C | Leave as spec'd (JSON optional, prose acceptable) | Ships the known enforcement gap; guard silently unenforced on fresh installs. |

**Recommended**: A — seed the JSON schema at install/update time; keep CLAUDE.md as the human view.

**Answer**: A — `.smith/security-config.json` `browser_verification.urls` is the machine-readable source of truth, seeded (empty lists) by /smith init and /smith-update; CLAUDE.md table is the human view.

---

## Q3: How is a target classified when the URL table doesn't match it?

**Context**: Even with seeding, `urls.staging`/`urls.production` may be empty or incomplete. The guard must classify every navigated/interacted target.

**Question**: What is the default classification for a URL matching neither list?

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | Unknown ⇒ treated as production (fail-safe) | Interactions on unlisted targets require confirmation until the operator lists their staging URLs. Slightly annoying at first; maximally safe against real-cookie mistakes. Localhost/127.0.0.1 can be carved out as always-staging to keep local dev frictionless. |
| B | Unknown ⇒ treated as staging (fail-open) | Frictionless out of the box, but an unlisted production URL gets zero protection — recreates the blocking finding. |
| C | Unknown ⇒ deny all interaction tools until the table is populated | Strongest forcing function; risks users disabling the guard entirely out of frustration. |

**Recommended**: A (with the localhost carve-out) — fail-safe by default, cheap to configure away.

**Answer**: A — unknown targets are treated as production (fail-safe); localhost/127.0.0.1 always classified as staging.

---

## Q4: How is `browser_evaluate` classified?

**Context**: `browser_evaluate` executes arbitrary JS in the page — it can read (harmless) or mutate (as dangerous as any click). The spec's tool lists name it in neither class; the plan currently proposes a heuristic source-pattern check, flagged as inference.

**Question**: Which class does `browser_evaluate` fall into?

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | Always interaction-class | Simple, safe, unbypassable; costs a confirmation when an agent wants evaluate-for-reading on production (rare — snapshot/console cover most read cases). |
| B | Heuristic: read-only unless the JS matches mutating patterns | Keeps read-evaluate frictionless, but regex-classifying arbitrary JS in a security hook is bypassable cleverness — false confidence. |
| C | Read-only class | Fastest, but hands production-mutation capability to an ungated tool. |

**Recommended**: A — a security hook should not parse JavaScript to guess intent.

**Answer**: A (recommendation accepted) — `browser_evaluate` is always interaction-class; no JS heuristics in the guard.

---

## Q5: Keep the `allow_interactions` master switch?

**Context**: The data-model includes `browser_verification.allow_interactions` (hard off-switch for all interaction tools), but no FR in spec.md grounds it — it's a stricter-than-spec addition.

**Question**: Keep, or drop for spec-minimalism?

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | Keep, default `true` — spec.md gains a matching FR | One-line kill-switch for operators who want MCP browsing to be strictly look-don't-touch; negligible implementation cost; spec updated so it's grounded. |
| B | Drop — decision table + confirm-gate suffice | Smaller config surface; an operator wanting read-only-everywhere must instead set every target as production. |

**Recommended**: A — cheap and genuinely useful for cautious operators.

**Answer**: A (recommendation accepted) — keep `allow_interactions`, default `true`; spec.md gains a matching FR grounding it.

---

## Q6: Follow the existing guards' config-file precedent despite the known seeding inconsistency?

**Context**: Pre-existing repo inconsistency (not caused by this feature): `templates/config.default.json` seeds `.smith/config.json`'s `security` section, but the existing guards actually read a different, unseeded `.smith/security-config.json`. Q2-A puts our URL table in `.smith/security-config.json` for guard-precedent consistency — which perpetuates the odd split.

**Question**: How should this feature relate to that inconsistency?

**Options**:

| Option | Description | Implications |
|--------|-------------|--------------|
| A | Follow guard precedent (`.smith/security-config.json`), and file the config-unification as a separate banked idea / queue item | Feature stays scoped; the inconsistency gets tracked instead of silently spreading further unexamined. |
| B | Fold config unification into this feature (migrate guards to `.smith/config.json`) | Fixes the root inconsistency now, but expands a security-sensitive feature's blast radius considerably — touching every existing guard. |

**Recommended**: A — scope discipline; unification deserves its own reviewed change.

**Answer**: A (recommendation accepted) — follow guard precedent (`.smith/security-config.json`); config unification filed separately via /smith-bank.
