---
feature: 20-manifest-fixes
branch: 20-manifest-fixes
created: 2026-05-28
status: in-progress
builds_on: 19-manifest-system (PR #19, merged)
note: Reconstructed 2026-06-02 after /tmp/ clearance; canonical source for v2 design is committed questions.md
---

# Feature: Manifest System v2 Fixes

## Summary

The v1 manifest system (feature 19, PR #19) shipped a deterministic context-retrieval layer built on heuristic system detection and structure-only `.meta` files. When `/smith-index` was run against the armory project — the first realistic-sized consumer — two correctness problems and one design problem surfaced at the same time. First, the heuristic resolver invented eight bucket-named systems by scanning top-level source directories, ignoring the eighteen systems already declared under `.specify/systems/<name>/spec.md`. Second, the resulting `.meta` files were semantically anemic: function signatures and import lists, no human-language summary of what a module or method actually does, which forced `/smith-navigate` to fall back on filenames and routes as proxies for intent. Third, an initial proposal to fix the second problem by having the save hook synthesize summaries on the fly via an LLM was rejected — it would blow the <500ms `manifest-updater.sh` budget and would silently drift on every edit.

v2 resolves all three with a single coherent design pivot: **descriptions are LLM-generated, but they live only in `.meta`, never in source code, and the save hook never generates them.** The rationale has two halves. Source files stay lean so whole-file LLM reads carry no Smith metadata weight; `.meta` files become a richer pre-read filter so Claude can decide which files to open without reading them first. Parsers stay structural-only and fast. A separate, opt-in `/smith-index --describe` pass generates the description layer in batched Haiku calls with checkpoint/resume. Smith workflows that edit code update the touched-method descriptions in-context (cheap — Claude already has the code in working memory). Out-of-workflow edits (`git pull`, rebase, hand edits in VS Code) trip a hash-mismatch staleness flag the navigator can surface; bulk regeneration remains an explicit operator action.

v2 also closes the system-detection loop by giving `.specify/systems/<name>/spec.md` a YAML frontmatter `paths:` field, and making the resolver consult it as tier 1. Track A introduces the new system-spec template, scaffolds it during `/smith init`, and provides a one-shot `/smith-migrate-system-paths` skill for projects (like armory) that already have hand-authored system specs without frontmatter. v1's heuristic stays in place as the tier 3 fallback — projects without `.specify/systems/` see no behavior change.

## Background

Three findings drove v2:

1. **System detection ignored declarations.** v1's resolver, per spec 19 Component 14, reads `system-paths.json` then falls back to a top-level-directory heuristic. armory has eighteen systems declared under `.specify/systems/system-01-*`/`system-02-*`/... but the heuristic produced eight (`backend`, `frontend`, `scripts`, etc.) — collapsing eighteen logical systems into eight directory buckets. The declarations existed; the resolver just didn't read them.

2. **`.meta` files were function signatures with no human meaning.** The v1 `.meta` schema captures `functions` (name/line/params/return), `classes`, `imports`, `routes`, `lines`, `hash`. Useful structure, but `/smith-navigate` needs to answer "which of these forty files is about webhook retries?" and signatures alone don't carry that signal. The navigator was opening files just to find out what they were for.

3. **The "dynamic LLM summary at save time" proposal was rejected.** The initial fix for finding 2 was to have `manifest-updater.sh` call an LLM to write a one-line file summary on every save. Two problems: (a) it blows v1's <500ms-per-edit budget on every Write/Edit, even for trivial changes; (b) summaries drift on every keystroke and produce noise rather than signal. The pivot — generate descriptions occasionally, store them in `.meta`, preserve across saves — is what v2 implements.

## Goals

- Make `.specify/systems/<name>/spec.md` the authoritative source of truth for system membership when present, without disturbing v1's heuristic fallback for projects that don't have it.
- Add an LLM-generated description layer to `.meta` (per-module + per-method) that survives saves, regenerates on demand, and never touches source code.
- Keep the `manifest-updater.sh` save hook structural-only and <500ms p95, exactly as v1.
- Keep `/smith-index` (without `--describe`) structure-only and <60s for 400 files, exactly as v1.
- Surface staleness of the description layer (hash mismatch between `Hash:` and `Described-Against-Hash:`) so the navigator and the user know when a description might not reflect current code.
- Generate descriptions cheaply during smith workflows that already have the code in context (`/smith-new`, `/smith-bugfix`, `/smith-debug`) — touched methods only.
- Provide an explicit, opt-in bulk-generation path (`/smith-index --describe`) with Rule 4 checkpoint/resume, JSONL logging, and per-batch user approval for existing codebases.
- Surface description coverage as a non-blocking flag in `/smith-build` PR descriptions, listing methods in the diff that lack a `.meta` description.

## Non-Goals / Out of Scope

- **Source code modification.** Descriptions never get backfilled as docstrings, JSDoc, comments, or any other in-source artifact. The manifest system writes only into `.smith/index/`.
- **Dynamic LLM summarization at save time.** The save hook never calls an LLM. It updates structure and `Hash:`, and sets the staleness marker — that is all.
- **Tight-range mode for `/smith-navigate`.** Still deferred to v3, same as v1.
- **Filesystem-watcher daemon.** Still out of scope from v1.
- **Windows support.** Still out of scope from v1.
- **Glob support in `paths:` frontmatter.** v1 ships literal prefixes only (Q6/A). Deferred to v3.
- **Auto-queue regeneration on staleness.** Q9 option C — surface staleness only; do not auto-enqueue files for re-description. Deferred to v3.
- **Larger model than Haiku for descriptions.** Q10 option C — rejected for v1; Haiku 4.5 covers the quality bar at the cost target.
- **Whole-file description refresh during smith workflows.** Q11 option B — rejected. Whole-file refresh is `/smith-index --describe`'s job; workflows touch only what they edit.

## Users / Stakeholders

- **Existing Smith projects with `.specify/systems/` declarations (primary).** armory is the canonical case — eighteen systems hand-authored, expecting Smith to honor them. v2 makes that work via Track A + `/smith-migrate-system-paths`.
- **New Smith projects bootstrapped with `/smith init`.** Get the new system-spec template and `paths:` frontmatter from day one (A1/A2).
- **Projects without `.specify/systems/` (e.g. small repos, the smith-repo itself).** Continue to use the v1 heuristic resolver — zero behavior change from v2.
- **Smith maintainers.** Get a description layer that's regeneration-controllable, hash-traceable, and decoupled from the hot-path save hook.
- **`/smith-navigate` consumers (all skills + the context-loader hook).** Get materially richer routing signal from per-module descriptions in the system manifest and from per-method descriptions surfaced through the navigator.

## Requirements

### Track A — `.specify/systems/` Integration

#### A1. New `system-spec-template.md` with `paths:` Frontmatter

A NEW template at `templates/system-spec-template.md` (distinct from the existing feature `spec-template.md` — that one is not modified). The template defines the canonical layout for `.specify/systems/<name>/spec.md` files with YAML frontmatter declaring:

```yaml
---
system: system-<name>
status: active | deprecated | proposed
paths:
  - <literal-path-prefix>
  - <another-prefix>
---
```

`paths:` is a list of literal path prefixes (project-relative). No globs in v1 (Q6/A). The body below the frontmatter is unconstrained markdown so authors can describe purpose, interfaces, owners, etc. The template is NOT applied retroactively — existing hand-authored system specs continue to render correctly because the body is free-form.

#### A2. `/smith init` Sub-Step: Scaffold System Specs

`/smith init` gains a new sub-step that, for each declared system, scaffolds a `.specify/systems/<name>/spec.md` from the A1 template. The user is prompted per system for `paths:` entries. Empty `paths:` is permitted (system can exist without path coverage yet) — the resolver treats an absent or empty `paths:` list as "no claim" and falls through to tier 2/3.

This is a NEW sub-step. Per the Assumptions section, `/smith init` does not currently scaffold system specs at all; system specs are introduced manually after init.

#### A3. New Skill: `/smith-migrate-system-paths`

A new top-level skill at `~/.claude/skills/smith-migrate-system-paths/SKILL.md`. Walks the project's `.specify/systems/<name>/spec.md` files and proposes `paths:` frontmatter for each.

Behavior:

- Read each existing `.specify/systems/<name>/spec.md`.
- If the file already has YAML frontmatter with a `paths:` field, skip (idempotent).
- Otherwise, scan the prose for path hints using literal-string regex patterns (e.g. `services/<name>/`, `backend/<name>/`, `frontend/<name>/`, `apps/<name>/`, code-fence file references, the heading bullet "Files:" lists if present). Propose a deduplicated list of literal prefixes.
- Present each proposed block to the user with the system name, the matched prose locations, and the proposed `paths:` list. The user can accept, edit, or skip per system.
- Write accepted frontmatter to the top of the file, preserving the existing body verbatim. If frontmatter already exists but lacks `paths:`, inject only the `paths:` field; do not rewrite the rest.
- Produce a summary report listing systems migrated, systems skipped, and a count of proposed-vs-accepted path entries.

Distinct from `/smith-migrate-specs`, which is explicitly file-flat-spec-folder migration and does NOT touch system specs (per the Assumptions section).

#### A4. Path Resolver — `.specify/systems/` Tier 1

The path resolver (v1 Component 14) gains a new TOP-priority tier that consults `.specify/systems/<name>/spec.md` frontmatter `paths:` lists.

Resolution algorithm (top-to-bottom):

1. **Tier 1 (NEW).** For each `.specify/systems/<name>/spec.md` with `paths:` frontmatter, try each literal prefix against the file's project-relative path. **Longest-prefix wins** (Q6/A) when multiple systems share overlapping prefixes (e.g. `services/auth/` vs `services/auth/oauth/` — the latter wins for files under `services/auth/oauth/`). Literal prefixes only — globs explicitly deferred to v3. On match, return `<system-name>`.
2. **Tier 2 (existing).** Try `system-paths.json` explicit overrides (longest-prefix wins, as v1).
3. **Tier 3 (existing).** Fall through to v1's built-in directory heuristic.

If `.specify/systems/` is absent OR no spec.md has a `paths:` field, tier 1 is a no-op and the resolver behaves identically to v1. This makes v2's tier 1 strictly additive: zero regression for projects that don't opt in.

### Track B — LLM-Generated Descriptions Stored in `.meta`

#### B1. Python Parser — Stable Method ID

`parse-python.py` (v1) is extended: each entry in the `functions` list gains a stable `id` field. The id is a deterministic hash of `<module-path>::<class-or-module>::<method-name>::<param-signature>`. Stable across edits to the method body or signature: renaming a method changes the id (correct — it's a different method), reordering methods in the file does not, editing the body does not.

The id is used as the key under which B3's per-method descriptions are stored. The parser remains STRUCTURAL-ONLY — no module_docstring extraction, no LLM calls, no descriptions of any kind written by the parser itself.

#### B2. JS/TS Parser — Stable Method ID

`parse-js.js` (v1) gains the same `id` field for each exported function, React component, and route handler. Same hash recipe, same stability properties. Same constraint: structural-only, no descriptions.

#### B3. `.meta` Description Layer

A new logical layer in `.meta` files, generated by an LLM and stored alongside (but distinct from) the structural data:

- **Per-module description** — one entry per `.meta` file. ~120-character soft cap, one line (Q8/B). Always generated when descriptions run.
- **Per-method description** — keyed to the stable method `id` from B1/B2. ~200-character soft cap, one-to-two sentences (Q8/B). Generated only for methods above a configurable size threshold (Q7/C); skipped for trivial accessors and data-config files. Threshold default is non-zero (e.g. 5 lines); `threshold=0` yields full per-method coverage.

Descriptions are generated ONLY by:

- `/smith-index --describe` (bulk path, see C2)
- `/smith-new`, `/smith-bugfix`, `/smith-debug` (in-context path, see C1)

Descriptions are NEVER generated by:

- `manifest-updater.sh` (the save hook stays LLM-free)
- The structural pass of `/smith-index` (without `--describe`)
- The parsers

#### B4. System Manifest "Description" Column

Per-system manifests at `.smith/index/systems/<name>.md` gain a Description column in the file-listing table. The Description value for each row is the per-module description from that file's `.meta`. If the file has no description yet, the cell is empty (NOT a placeholder, NOT a parser-derived fallback). This is how `/smith-navigate` answers "which file is about webhook retries" without opening each file.

The ≤80-line per-system-manifest cap (from v1) is preserved.

#### B5. `.meta` File Schema Additions

`.meta` files gain four new fields:

- `**Description:**` — per-module description (single line, ~120 chars).
- Per-function `Description:` field attached to each entry in the existing `Functions:` block, keyed by the new `Id:` field on that entry.
- `Described-Against-Hash:` — the value of `Hash:` at the moment the descriptions were generated. Updated by description generators (`/smith-index --describe`, smith workflows); NOT updated by the save hook.
- `Described-At:` — ISO 8601 timestamp of the most recent description generation pass that touched this file.

If a `.meta` has no descriptions yet, the `**Description:**` field is absent (NOT empty-string). `Described-Against-Hash:` and `Described-At:` are absent until the first description pass.

v1's `Last Updated:`, `Language:`, `Lines:`, and `Hash:` header fields are unchanged.

#### B6. Full-Rebuild vs Save-Hook Parity

Both `/smith-index` (full rebuild, structural pass) and `manifest-updater.sh` (single-file save hook) produce identical `.meta` and system-manifest **structural** output shapes.

Critically: when `manifest-updater.sh` regenerates a `.meta` after a save, it PRESERVES the LLM description layer (`**Description:**`, per-function `Description:` values, `Described-Against-Hash:`, `Described-At:`). It updates only structural fields and the file's `Hash:`. It never overwrites a description. It never generates a description.

Structurally-identical output between the two paths means: same field ordering, same Function entry shape, same handling of missing values, same hash recipe.

### Track C — Description Lifecycle (No Source Modification)

#### C1. Smith Workflows Update `.meta` Descriptions In-Context

`/smith-new`, `/smith-bugfix`, and `/smith-debug` gain a new in-flow step after writing or editing a source file: update the touched file's `.meta` description layer in-context.

Scope (Q11/A):

- **Per-method descriptions:** regenerate only for methods the diff added or edited. Other methods' descriptions in the same file are left untouched.
- **Per-module description:** regenerate only when the file's purpose has materially shifted (e.g. a service file gains a new public interface, a module's primary responsibility changes). Routine internal refactors do not regenerate the per-module description.

The generation is cheap because Claude already has the file's full content in working context — no extra reads, no extra LLM round trips beyond a small structured response. The save hook still runs (structurally) after each Write/Edit and preserves the description layer the workflow just wrote.

Whole-file refresh remains `/smith-index --describe`'s job, not the workflow's.

#### C1.5. `/smith-build` PR Description Coverage Flag

`/smith-build` adds a coverage flag to its generated PR description (Q4/C — both soft guidance in the smith-new/bugfix/debug workflows AND a hard flag in `/smith-build`). The flag lists methods in the PR's diff that lack a `.meta` description, alongside the existing v1 >300-line file-size warning.

Format (illustrative):

```markdown
### Manifest Coverage
- 3 methods in this diff lack `.meta` descriptions:
  - backend/src/services/webhook.py::WebhookRetryHandler::backoff
  - backend/src/services/webhook.py::WebhookRetryHandler::dead_letter
  - frontend/src/lib/api/products.ts::fetchProductBundle
- Run `/smith-index --describe --system <name>` to backfill before merge.
```

The flag is **never blocking** — the PR opens regardless. It exists to give reviewers visibility and prompt the operator to backfill when appropriate.

#### C2. `/smith-index --describe` — Bulk Description Generation

A new flag on `/smith-index` (existing v1 skill) that bulk-generates the description layer for an existing codebase. This replaces what was originally proposed as a standalone backfill skill.

Behavior (Q10/A):

- **Model:** Haiku 4.5 (matches the v1 navigator model choice).
- **Batching:** N=10 files per batch, parallel where the API tier allows. Batch size is a config knob, not a hard constant.
- **Opt-in:** `/smith-index` without `--describe` runs the structural pass only and stays <60s for 400 files. `--describe` is the explicit, occasional path.
- **Approval (Q5/B):** per-batch (~20 files, configurable separately from the LLM batch size) approval prompt with per-file reject. Operator can reject a single file's proposed descriptions inside a batch without aborting the batch.
- **Rule 4 compliance:** per-file checkpoint, JSONL log at `logs/smith-index-describe-<timestamp>.jsonl` with one entry per processed file (`{"timestamp", "file", "stage", "status", "error"}`), `--resume` flag that reads the last checkpoint and continues. Final summary on completion or failure (total processed, succeeded, failed, skipped).
- **Hash caching:** on re-run, files whose `Hash:` equals their `Described-Against-Hash:` AND have descriptions present are skipped. Files with hash mismatch (stale) or no descriptions are processed.
- **Source code is never written.** Descriptions land in `.meta` only.

#### C3. Out-of-Workflow Staleness Flag

When a file is edited outside any smith workflow (hand edit, `git pull`, rebase, branch switch, IDE save), the save hook updates `Hash:` to the new content hash. Because the save hook never touches descriptions, `Described-Against-Hash:` retains its prior value. The hash mismatch IS the staleness signal — no separate flag file, no extra metadata.

`/smith-navigate` consults the mismatch when routing: if a file's description is stale (hash mismatch), the navigator surfaces this to the caller so the description is treated as a hint, not authoritative. Bulk reconciliation is via `/smith-index --describe`, which the hash cache makes cheap (only stale or missing files are re-described).

No LLM call from the save hook. No auto-queue (Q9 option C, deferred to v3).

## Design Decisions

### Decision: Descriptions Live in `.meta`, Never in Source

**Decision:** All LLM-generated descriptions (per-module + per-method) are stored exclusively in `.smith/index/files/<path>/<file>.meta`. Source code is never modified.

**Rationale:**

1. **Lean source for whole-file LLM reads.** When Claude reads a source file (during navigation, exploration, or implementation), the file should carry only its own code — no Smith metadata, no auto-generated comments, no JSDoc bloat. v1 established this principle; v2 reinforces it because the description layer is the most-tempting candidate for in-source storage.
2. **`.meta` as a pre-read filter.** `.meta` files exist precisely so Claude can decide which files to open. Putting descriptions in `.meta` makes that filtering meaningfully smarter (the navigator can now reason about purpose, not just signatures). Putting them in source would defeat the purpose: Claude would have to open the file to read its own description.

**Alternatives considered:**

- Docstring backfill into source. Rejected — violates the v1 principle and (1) above.
- Sidecar `.desc` files alongside source. Rejected — splits Smith state across two paths and doubles gitignore complexity. `.meta` already covers this role.
- Inline `.meta` description as a header comment in source. Rejected — same problem as docstrings, plus harder to keep in sync.

### Decision: LLM Confined to `/smith-index --describe` and Smith Workflows

**Decision:** LLM calls for description generation happen in exactly two paths: (a) the explicit, opt-in `/smith-index --describe` bulk pass, (b) the in-context updates inside `/smith-new`/`/smith-bugfix`/`/smith-debug`. The save hook (`manifest-updater.sh`) never calls an LLM.

**Rationale:** The save hook's <500ms p95 budget is the hot path of the entire manifest system — it fires on every Write and Edit, including sub-agent fan-out during heavy builds. Adding even a single LLM call there would blow the budget and inject latency at the worst possible moment. Confining LLM work to the explicit, occasional bulk path and the in-context workflow path keeps the hot path deterministic and fast, and keeps LLM cost auditable (one bulk run is one operator action; workflow generations are scoped to the current edit).

**Alternatives considered:**

- LLM in the save hook (the original proposal). Rejected — blows budget, produces noise on every keystroke.
- LLM in a separate post-save async queue. Rejected — adds a long-running process the v1 spec deliberately avoided (filesystem-watcher daemon is already deferred).

### Decision: Parser Is Structure-Only; Descriptions Are a Separate Layer Keyed by Stable Method IDs

**Decision:** `parse-python.py` and `parse-js.js` stay structural-only — they emit functions, classes, imports, routes, line count, hash, plus a new stable `id` per method. The description layer is generated separately by description-aware paths (C1, C2) and stored in `.meta` keyed by `id`.

**Rationale:** Parsing must be fast (<200ms p95) and dependency-free (stdlib only, no `@anthropic-ai/sdk` in `parse-python.py`). Mixing parsing and description generation would couple two different lifecycles (every save vs. occasional regeneration) and two different runtime profiles (sync structural vs. async LLM). Stable method ids let descriptions survive edits to surrounding code: a method's description stays attached as long as the method's identifying tuple (path, scope, name, signature) is unchanged.

**Alternatives considered:**

- Parser extracts docstrings as descriptions. Rejected — docstrings rarely exist on the methods that most need descriptions, and harvesting them couples description quality to source-code coverage Smith cannot control.
- Store descriptions by line number instead of stable id. Rejected — every save shifts line numbers and would orphan descriptions.

### Decision: `.specify/systems/` `paths:` Frontmatter as Resolver Tier 1

**Decision:** Add a new top-priority tier to the path resolver that reads `paths:` frontmatter from `.specify/systems/<name>/spec.md`. Tier 1 is additive — when absent, the resolver behaves identically to v1.

**Rationale:** The armory rollout proved that hand-authored `.specify/systems/` declarations are the user's actual statement of intent about system membership. The v1 resolver ignored them because v1 was designed first for smith-repo (which has no `.specify/systems/` of its own) and the heuristic was meant as a default, not a constraint. Tier 1 makes the declarations authoritative when present without forcing every project to author them. Longest-prefix resolution handles natural prefix overlap (a sub-system inside a parent system).

**Alternatives considered:**

- Replace the heuristic entirely. Rejected — breaks projects without `.specify/systems/`.
- Use a separate `system-paths.json` only. Rejected — duplicates information the user already encoded in `.specify/systems/<name>/spec.md` and creates two sources of truth.
- Glob support in `paths:` from day one. Rejected — Q6/A explicitly deferred to v3; literal prefixes cover the cases armory needs and keep the resolver predictable.

### Decision: One Bundled PR for All Three Tracks (Q1)

**Decision:** Tracks A, B, and C ship as one bundled PR, not three sequential PRs.

**Rationale:** The three tracks share intertwined data structures (`.meta` schema gains fields used by all three) and share migration semantics (a project running `/smith-migrate-system-paths` then `/smith-index --describe` is the canonical existing-project onramp). Splitting the PR would either ship Track B without the system-detection fix (so the rich descriptions land in the wrong systems) or ship Track A without the description layer (so the eighteen systems Smith now correctly identifies still have anemic `.meta` files). Bundling lets reviewers evaluate the end-to-end behavior change against a single working example (armory).

**Alternatives considered:**

- Three PRs sequenced A → B → C. Rejected per Q1 — review surface fragmentation, partial-state regressions during the rollout window.

### Decision: Longest-Prefix Resolution, Literal Prefixes Only (Q6/A)

**Decision:** When multiple systems' `paths:` lists overlap, the longest matching literal prefix wins. Globs (e.g. `services/*/api/`) are deferred to v3.

**Rationale:** Literal prefixes are deterministic, fast to evaluate, and trivially documented. The realistic ambiguity case is parent/child system nesting (e.g. `services/auth/` vs `services/auth/oauth/`), and longest-prefix resolves it correctly without needing operator decision rules. Globs introduce ambiguity (which glob wins when two match?) and require either a precedence rule the operator can't easily predict or per-rule priority annotations that bloat the frontmatter. Deferring globs to v3 lets v1 ship with predictable semantics.

**Alternatives considered:**

- First-match (declaration order). Rejected — implicit semantics, easy to get wrong on reorder.
- Globs with explicit precedence. Rejected — see above.

### Decision: Hash-Mismatch Staleness Flag (Q9/B)

**Decision:** Description staleness is signaled exclusively by the mismatch between a `.meta`'s `Hash:` (always current, updated by the save hook) and its `Described-Against-Hash:` (updated only by description-generation paths). No separate "stale" boolean, no auto-queue, no extra metadata.

**Rationale:** The hash mismatch is a free signal — it falls out of structures the save hook already maintains. Surfacing it through `/smith-navigate` lets the navigator decide how to treat a stale description (e.g. downrank, annotate, request reconciliation) without bolting on staleness-management infrastructure. Auto-queue (Q9 option C) is a reasonable v3 enhancement once the staleness marker has demonstrated value and once we have evidence about how often `git pull`-induced staleness floods need handling.

**Alternatives considered:**

- Accept silently (Q9 option A). Rejected — leaves the navigator routing on stale data with no signal.
- Auto-queue on mismatch (Q9 option C). Rejected for v1 — adds queue dependency and risks unbounded growth after a large `git pull`. Reserved for v3.

### Decision: Haiku 4.5 + N=10 Batching + Opt-In `--describe` Flag (Q10/A)

**Decision:** Bulk description generation uses Haiku 4.5, batches of N=10 files, an explicit `--describe` flag (default `/smith-index` stays structural-only), per-file checkpoint with `--resume`, JSONL log, and hash-cached skip-unchanged on re-run.

**Rationale:** Haiku 4.5 is already the navigator model (v1) and is the right cost/quality point for one-sentence-per-method summaries. N=10 keeps the batch small enough for per-file checkpoint granularity (Rule 4) and small enough that a transient API failure doesn't lose hours of work. Opt-in flag preserves the fast structural rebuild as the default — operators who don't need descriptions today pay nothing for the description path. Hash caching makes re-runs near-free, which makes the staleness reconciliation story practical.

**Alternatives considered:**

- Always-on description generation (Q10 option B). Rejected — every `/smith-index` would incur LLM cost, no fast structural rebuild.
- Sonnet for higher-quality descriptions (Q10 option C). Rejected — overkill for one-line summaries; materially higher cost and time.

### Decision: Touched-Methods-Only Workflow Updates (Q11/A)

**Decision:** Smith workflows that edit code update `.meta` descriptions only for the methods the diff added or edited. The per-module description is updated only when the file's purpose has materially shifted. Other methods' descriptions stay as-is.

**Rationale:** In-context regeneration is cheap because Claude already has the file open, but blanket regeneration is wasteful (more tokens) and risky (overwrites descriptions the user previously accepted via `/smith-index --describe` or a prior workflow). Touched-only is the minimal-disturbance default; whole-file refresh remains explicitly the bulk-pass's job. Drift in untouched methods is acceptable because the staleness flag (decision above) catches the case where it matters.

**Alternatives considered:**

- Whole-file refresh in workflows (Q11 option B). Rejected — overwrites accepted descriptions, more tokens.
- Touched-methods always + whole-file when stale (Q11 option C). Reserved as a possible enhancement if empty/stale files prove common; not needed for v1.

## Hard Constraints

- **Source code is never modified** by parsers, hooks, skills, install scripts, or any v2 component. All description data lives in `.smith/index/files/<path>/<file>.meta`.
- **LLM calls are confined** to `/smith-index --describe` and the three smith workflows (`/smith-new`, `/smith-bugfix`, `/smith-debug`). The save hook (`manifest-updater.sh`) is LLM-free.
- **Save hook performance** unchanged from v1: <500ms p95 per file edit. No regression.
- **Structural `/smith-index` performance** unchanged from v1: <60s for a 400-file project, structural pass only. The `--describe` pass is a separate, slower operation with its own (LLM-bounded) budget.
- **`/smith-index --describe` per-batch throughput target:** ~30-60s per 20-file approval batch on a typical codebase, gated by Haiku latency.
- **v1 behavior preserved when `.specify/systems/` is absent.** Tier 1 of the resolver is additive; tier 2 (`system-paths.json`) and tier 3 (heuristic) are unchanged.
- **Parsers handle malformed source gracefully** — return partial JSON, never crash the calling hook.
- **Manifest size caps preserved:** top-level `.smith/index/manifest.md` ≤50 lines; per-system `.smith/index/systems/<name>.md` ≤80 lines.
- **`.meta` schema is backward-compatible:** existing v1 fields (`Last Updated:`, `Language:`, `Lines:`, `Hash:`, `Functions:`, `Classes:`, `Imports:`, `Routes:`) are unchanged. New fields (`**Description:**`, per-function `Id:`, per-function `Description:`, `Described-Against-Hash:`, `Described-At:`) are additive.

## Acceptance Criteria

### Functional

- [ ] `/smith-index` on a project with `paths:` frontmatter in `.specify/systems/<name>/spec.md` produces systems matching the declarations (e.g. armory → 18 systems, not 8).
- [ ] `/smith-index` on a project without `.specify/systems/` declarations falls back to v1 behavior (tier 2 + tier 3 only), zero regression.
- [ ] `/smith-index --describe` LLM-generates per-module and per-method descriptions and writes them to `.meta` only; source files unchanged after the run.
- [ ] `/smith-index --describe` writes a JSONL log to `logs/smith-index-describe-<timestamp>.jsonl` and supports `--resume`.
- [ ] `/smith-index --describe` re-runs skip files whose `Hash:` equals `Described-Against-Hash:` and have descriptions present.
- [ ] `/smith-new`, `/smith-bugfix`, `/smith-debug` update `.meta` descriptions for methods they edit (per-method) and the per-module description when the file's purpose has shifted; untouched methods' descriptions are unchanged.
- [ ] `/smith-build` PR description includes a Manifest Coverage block listing methods in the diff lacking a `.meta` description (never blocks the PR).
- [ ] `/smith init` on a fresh project scaffolds `.specify/systems/<name>/spec.md` files from the new `templates/system-spec-template.md` and prompts for `paths:` per system.
- [ ] `/smith-migrate-system-paths` on an existing project proposes `paths:` frontmatter for each existing system spec, accepts per-system confirmation, and writes accepted frontmatter without disturbing the body.
- [ ] `manifest-updater.sh` preserves the `.meta` description layer on save — `**Description:**`, per-function `Description:`, `Described-Against-Hash:`, `Described-At:` survive a Write/Edit.
- [ ] `manifest-updater.sh` updates `Hash:` on every save but never updates `Described-Against-Hash:`.
- [ ] `/smith-navigate` surfaces description staleness (hash mismatch) when routing on a stale `.meta`.
- [ ] Path resolver tier 1 honors longest-prefix-wins across overlapping `paths:` lists. Literal prefixes only; globs are rejected (or warned and ignored) with a clear message.
- [ ] System manifests at `.smith/index/systems/<name>.md` include a Description column populated from each file's per-module description; empty when no description exists yet.
- [ ] Stable method `id` survives body edits and method reordering; changes only on rename or signature change.

### Performance

- [ ] `manifest-updater.sh` <500ms p95 per file edit (unchanged from v1, no LLM additions).
- [ ] `/smith-index` (structural pass, no `--describe`) <60s for 400 files (unchanged from v1).
- [ ] `/smith-index --describe` ~30-60s per 20-file approval batch on a typical codebase.
- [ ] `/smith-navigate` <3s p95 per invocation (unchanged from v1).

### Quality

- [ ] All v1 tests pass after v2 merges.
- [ ] New tests cover: resolver tier 1 (`.specify/systems/` frontmatter), `.meta` description layer parse/write, save-hook description preservation, `/smith-build` coverage flag generation, `/smith-migrate-system-paths` end-to-end, `/smith init` system-spec scaffolding, stable method `id` stability across edits.
- [ ] No source-code modification by any v2 component — verified by scanning a sample edit run for any non-`.smith/index/` writes.
- [ ] `/smith-index --describe` JSONL log includes one entry per processed file with `{"timestamp", "file", "stage", "status", "error"}` fields (Rule 4 compliance).
- [ ] Final summary on `/smith-index --describe` completion or failure includes total processed / succeeded / failed / skipped counts (Rule 4 compliance).

## Open Questions

All resolved — see `./questions.md`.

## Assumptions

These are CRITICAL findings from prior plan-phase investigation. They constrain the v2 implementation and must be honored by the implementation tasks:

- **`/smith init` does not currently scaffold system specs.** The existing `/smith init` workflow stops at constitution + CLAUDE.md + vault scaffolding; system specs are introduced manually afterward (or not at all, as in smith-repo itself). A2 is therefore a NEW sub-step, not an extension of existing scaffolding logic.
- **System specs today are hand-authored bold-field markdown, not YAML-frontmatter files.** Existing `.specify/systems/<name>/spec.md` files use prose with conventions like `**Owners:**`, `**Files:**`, `**Status:**` rather than YAML frontmatter. A1's template and A3's migration must produce frontmatter that coexists with this prose body — frontmatter goes ABOVE the body, the body is preserved verbatim.
- **`/smith-migrate-specs` explicitly excludes system specs.** The existing migration skill handles flat `specs/<feature>/` directories moving into system-based hierarchies. It does NOT touch `.specify/systems/<name>/spec.md` files. A3 (`/smith-migrate-system-paths`) is a new, separately-invoked skill that operates only on system specs.
- **v1 `.meta` files use a fixed header schema** with `Last Updated:`, `Language:`, `Lines:`, `Hash:` as bold-field lines, followed by `Functions:`, `Classes:`, `Imports:`, `Routes:` blocks. B5's new fields (`**Description:**`, `Described-Against-Hash:`, `Described-At:`) integrate into the same bold-field header pattern; the new per-function `Id:` and `Description:` lines integrate into the existing `Functions:` block.
- **smith-repo itself does not run `/smith-index` on itself** (per v1 Q1 resolution). v2 does not change this — the manifest system is for consumer projects.
- **v1's parsers (`parse-python.py`, `parse-js.js`) live at `~/.smith/scripts/` globally with per-project overrides allowed** (per v1 Design Decision 5). B1/B2 changes update the global scripts; per-project overrides retain the escape hatch.

## References

- **PR #19** — `feat: manifest system and structured context retrieval` (merged 2026-05-21). The v1 implementation v2 builds on.
- **v1 spec** — `specs/19-manifest-system/spec.md`. Authoritative v1 design; v2 references its component numbering throughout.
- **armory rollout findings** — internal observation that `/smith-index` produced 8 systems instead of the declared 18, and that `.meta` files lacked human-language summaries. The two findings that triggered v2.
- **Questions gate** — `./questions.md`. All 11 v2 design questions and their resolutions.

2026-06-02 — 20-manifest-fixes
