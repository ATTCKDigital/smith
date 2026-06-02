---
feature: 20-manifest-fixes
branch: 20-manifest-fixes
created: 2026-05-28
status: in-progress
spec: ./spec.md
artifacts:
  - ./research.md
  - ./questions.md
builds_on: 19-manifest-system (PR #19, merged 2026-05-21)
note: Reconstructed 2026-06-02 after /tmp/ clearance from committed spec.md + questions.md
---

# Plan: Manifest System v2 Fixes

This plan operationalizes [`spec.md`](./spec.md). All 11 design questions
are resolved in [`questions.md`](./questions.md). The plan does not restate
spec content — it commits to the files, languages, sequencing, and
component contracts that satisfy Tracks A, B, and C as a single bundled PR
(per Q1/A).

---

## Technical Context

| Concern | Choice | Notes |
|---|---|---|
| Languages — parsers | Python 3 stdlib (`parse-python.py`, `path-resolver.py`, `meta_describe.py`) + Node.js with vendored `acorn` (`parse-js.js`) | No new external deps. v1 already vendors acorn at `scripts/parsers/vendor/acorn.min.js`; v2 reuses without adding modules. |
| Languages — orchestration | Python 3 stdlib (`scripts/smith-index/run.py`, `hooks/manifest-updater-lib.py`) | Stdlib only — `urllib.request` for the Haiku call in `meta_describe.py`. No `anthropic` SDK. |
| LLM model | Haiku 4.5 (Anthropic SDK) | Matches v1's `/smith-navigate` choice (Q10/A). Called via stdlib `urllib` against the Anthropic Messages API; key from `ANTHROPIC_API_KEY` env. |
| Test infra | Existing `unittest` + bash test scripts inherited from v1 | New tests live under `tests/parsers/` and `tests/skills/`. |
| Hook runtime | Bash 3.2+ (unchanged) | macOS default; no Bash 4 features. |
| Per-project state | `.smith/index/` (unchanged) | New: per-file `.meta` gains description-layer lines. |
| Per-run state | `.smith/index/logs/smith-index-describe-<ts>.jsonl` | New, Rule 4 compliant. |
| OS target | macOS 14+, Linux glibc 2.31+ (unchanged from v1) | No Windows. |
| Constitution context | This project has no `.specify/memory/constitution.md`; the binding rubric is `~/.claude/CLAUDE.md` (Rules 1-7). | See Constitution Check below. |

No new external runtime dependencies are added. Acorn (vendored) is the
only third-party JS dependency; it is already shipped in v1 and is NOT
used by the description path — descriptions never run through the JS
parser. Python stdlib `urllib.request` carries the Anthropic API calls.

---

## Constitution Check

`smith-repo` has no `.specify/memory/constitution.md`. The rubric is
`~/.claude/CLAUDE.md`. Per-rule compliance:

### Rule 1 — Questions Are NOT Action Requests [W: 25]
> "When the user asks a question, respond with words only. Do not act."

**Compliance:** Implementation-level only. `/smith-index --describe`,
`/smith-migrate-system-paths`, and the in-workflow `.meta` updates are
imperative invocations (skills explicitly invoked or workflow steps
explicitly running); none are triggered by questions. `/smith-navigate`
remains read-only (returns a file list, never writes).

### Rule 3 — Question Files Before Complex Changes [W: 15]
> "Before implementing any complex change ... generate a structured question file."

**Compliance:** This feature has `questions.md` with 11 answered
questions covering track sequencing, A3 skill ownership, A1/A2 scope,
coverage enforcement, approval granularity, resolver tie-breaking,
description granularity/length, staleness, model/cost, and workflow
update scope. All 11 answers are encoded into spec.md as Decisions or
Hard Constraints. Build can proceed.

### Rule 4 — Checkpoint/Resume for Long-Running Processes [W: 15]
> "Any script or pipeline that processes large datasets must implement
> checkpointing, structured logs, resume capability, and status summaries."

**Compliance — central to this feature.** `/smith-index --describe` is
explicitly a long-running batch script. The implementation:

- Writes a JSONL log at `.smith/index/logs/smith-index-describe-<ts>.jsonl`
  with one record per file: `{"timestamp", "item_id", "stage", "status",
  "error", "method_count", "module_chars"}`.
- Writes checkpoint state at `.smith/index/.smith-index-describe-checkpoint.json`
  every batch (every ~10 files, configurable).
- Supports `--resume` which reads the most recent JSONL log, computes the
  set of file paths with `status=ok` for `stage=describe`, and resumes
  from the first not-yet-completed file.
- Prints a final summary line: `total processed / succeeded / failed /
  skipped`, plus per-batch progress during the run.

The save-hook path is structural-only and finishes in <500ms (no LLM); it
inherits Rule 4 compliance from v1 (no change).

### Rule 6 — General Preferences [W: 8]
> "Python commands use `python3`, not `python`."

**Compliance:** All new Python scripts have `#!/usr/bin/env python3`
shebangs and are invoked as `python3 <script>` from bash. Existing v1
parsers already comply; `meta_describe.py` follows the same pattern.

### Rule 5 / 7 — Session Logging / Directory Setup [W: 10 / 2]

These apply at the session level and are satisfied by the smith-repo
session vault structure already in place.

---

## CRITICAL FINDINGS

Five findings from prior plan-phase investigation drive the implementation
shape. These are NON-NEGOTIABLE — implementation tasks must honor them.

### F1. `/smith init` does NOT scaffold system specs today

The existing `skills/smith/SKILL.md` (`Phase 4: Generate Files`, lines
220-243) creates `.specify/memory`, `.specify/templates/*` (5 files),
`.specify/scripts/bash/`, `docs/sessions/`, `specs/questions/`, and the
full `.smith/vault/` tree — but never touches `.specify/systems/`. The
templates directory at `skills/smith/templates/` contains exactly:

```
agent-file-template.md
checklist-template.md
plan-template.md
spec-template.md       ← FEATURE spec, not system spec
tasks-template.md
```

There is no `system-spec-template.md`. Implication for A1+A2:

- **A1 is NEW:** create `skills/smith/templates/system-spec-template.md`.
- **A2 is a NEW sub-step** in `skills/smith/SKILL.md` Phase 4, NOT an
  extension of an existing one. The existing FEATURE spec-template is
  not touched.

### F2. Real system specs are hand-authored bold-field markdown, no YAML frontmatter

Existing `.specify/systems/<name>/spec.md` files (as seen in the armory
rollout) use prose conventions like:

```markdown
# System 05: Communication Triage

**Owners**: Foo, Bar
**Status**: active
**Files**: backend/src/services/triage/
```

No YAML frontmatter. The resolver tier 1 (A4) reads frontmatter
exclusively, so v2 adds frontmatter ABOVE the existing body (preserved
verbatim). A3's migration skill is the bridge: it inspects prose
conventions, proposes equivalent frontmatter, and writes only after
per-system user confirmation.

### F3. `/smith-migrate-specs` overlap is essentially nil

`skills/smith-migrate-specs/SKILL.md` (140 lines total) migrates flat
*feature* folders from `specs/<NNN-feature>/` into the system-based
hierarchy at `.specify/systems/<system>/features/<NNN-feature>/`. It
treats system specs at `.specify/systems/system-*/spec.md` as **source
of truth**, NOT as migration targets (line 23: "system specs — these
are the source of truth"). It writes `primary_system:` into FEATURE
specs after migration; it does not touch system specs.

Implication: A3 is unambiguously a new, separate skill
(`/smith-migrate-system-paths`). Q2/A confirmed.

### F4. v1 `.meta` field names are byte-stable; v2 extends additively

v1 renders `.meta` via `render_meta()` in `scripts/smith-index/run.py`
(lines 308-425). The header fields are:

```
# <rel_path>
Last Updated: <iso>
Language: <lang>
Lines: <n>
Hash: <sha256-first-4kb>
```

v2 must keep these EXACTLY (same labels, same order, same blank line
before sections). v2 adds, after `Hash:` and before the blank line:

```
**Description:** <single-line ~120 char>      # absent if not yet generated
Described-Against-Hash: <hash-at-generation>  # absent if not yet generated
Described-At: <iso8601>                       # absent if not yet generated
```

Per-method descriptions attach inside the existing `## Functions`
section. v1 emits each function as:

```
- `<name>(<sig>) -> <ret>` (line N)
  <docstring-first-line>     ← only when parser-derived docstring exists
```

v2 changes the parsers to ALSO emit a stable `id` field (B1/B2; see F5)
and changes `render_meta()` to:

- emit `Id: <hash>` on the indented line after the signature when the id is present;
- emit `Description: <desc>` on the next indented line when the description is present;
- skip the v1 parser-docstring line (parsers no longer populate `docstring` per Q8 + Decision "Parser is structure-only").

### F5. Vendored acorn captures comments but v2 does NOT use them

`scripts/parsers/vendor/acorn.min.js` exposes `onComment` (16 references
in the minified bundle); v1 does not wire it. The original "parsers
extract docstrings/descriptions" proposal would have wired it. **v2
rejects that path entirely** (per Decision "Parser is structure-only").
Parsers emit structural data plus a new `id` field — no descriptions.

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│  IN-WORKFLOW EDIT (Claude inside /smith-new, /smith-bugfix, debug)   │
│                                                                       │
│  Claude Write/Edit src.py                                            │
│         │                                                             │
│         ├─► PostToolUse Write|Edit hook chain                        │
│         │      └─► hooks/manifest-updater.sh                         │
│         │             └─► manifest-updater-lib.py                    │
│         │                    │                                       │
│         │                    ├─ run parser (structural)              │
│         │                    ├─ read existing .meta if any           │
│         │                    ├─ PRESERVE description layer:          │
│         │                    │    **Description:** line              │
│         │                    │    Described-Against-Hash:            │
│         │                    │    Described-At:                      │
│         │                    │    per-function Description: lines    │
│         │                    │    keyed by Id:                       │
│         │                    ├─ refresh structural fields            │
│         │                    ├─ update Hash:                         │
│         │                    └─ (staleness signal = Hash ≠           │
│         │                       Described-Against-Hash)              │
│         │                                                             │
│         └─► Workflow step: meta_describe.update_touched(file, diff)  │
│                  ├─ parse to get method ids                          │
│                  ├─ identify added/edited methods from diff          │
│                  ├─ Haiku call (small): per-method descriptions      │
│                  ├─ if file_purpose_shifted: regen per-module        │
│                  ├─ merge into existing .meta (preserve untouched)   │
│                  └─ set Described-Against-Hash = current Hash        │
│                                                                       │
│  Net: save hook fired first (~300ms), then workflow re-wrote .meta   │
│  with description deltas. Final .meta has fresh structure + fresh    │
│  descriptions on touched methods only.                               │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│  OUT-OF-WORKFLOW EDIT (git pull, rebase, hand edit, IDE save)        │
│                                                                       │
│  Editor Write src.py                                                 │
│         │                                                             │
│         └─► manifest-updater.sh (same path)                          │
│                ├─ structural refresh                                 │
│                ├─ PRESERVE description layer                         │
│                ├─ Hash: updated                                      │
│                ├─ Described-Against-Hash: UNCHANGED                  │
│                └─ Hash ≠ Described-Against-Hash → STALE signal       │
│                                                                       │
│  /smith-navigate consumes .meta, detects mismatch, surfaces          │
│  "(stale description)" annotation alongside the file in its output.  │
│  Bulk reconcile via /smith-index --describe (hash-cached, cheap).    │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│  BULK DESCRIBE (explicit operator action)                            │
│                                                                       │
│  /smith-index --describe [--resume] [--system <name>]                │
│         │                                                             │
│         ├─ discover source files (walk_source_files, v1)             │
│         ├─ filter: skip where Hash == Described-Against-Hash AND     │
│         │          description present (hash cache)                  │
│         ├─ chunk into approval batches (default 20 files)            │
│         ├─ per batch:                                                │
│         │     ├─ prompt operator: accept | per-file reject | abort   │
│         │     ├─ sub-batch into LLM batches (default N=10)           │
│         │     ├─ for each LLM batch:                                 │
│         │     │     ├─ build prompts (per-module + per-method)       │
│         │     │     ├─ Haiku 4.5 call (one per file in batch)        │
│         │     │     └─ merge into .meta, set                         │
│         │     │        Described-Against-Hash = Hash                 │
│         │     └─ write JSONL log line per file                       │
│         ├─ checkpoint after each LLM batch                           │
│         └─ final summary: total / succeeded / failed / skipped       │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│  PATH RESOLVER — tier precedence                                     │
│                                                                       │
│  resolve(file_path):                                                 │
│    rel = normalize(file_path)                                        │
│                                                                       │
│    # Tier 1 (NEW) — .specify/systems/<name>/spec.md paths:           │
│    for each (system_id, prefix) in declared_paths, sorted by         │
│        len(prefix) desc:                                             │
│      if rel.startswith(prefix): return system_id                     │
│                                                                       │
│    # Tier 2 (existing) — system-paths.json rules                     │
│    for each rule in overrides, sorted by len(prefix) desc:           │
│      if rel.startswith(rule.prefix): return rule.system              │
│                                                                       │
│    # Tier 3 (existing) — directory heuristic                         │
│    return _apply_heuristic(rel)                                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## File Structure

All paths absolute against `/Users/dennisplucinik/Projects/smith-repo`.
Tracks (A/B/C) annotate spec sections. Numbers in parentheses are
approximate LOC.

### Track A — `.specify/systems/` Integration

| Action | Path | LOC | Lang | Purpose |
|---|---|---|---|---|
| NEW | `skills/smith/templates/system-spec-template.md` | ~80 | Markdown | A1. Canonical system-spec template with YAML frontmatter (system/status/paths/also_affects). Free-form body below. |
| MODIFY | `skills/smith/SKILL.md` | +~70 | Markdown | A2. Phase 4 sub-step "4.X Scaffold System Specs (Optional)". Reads list of declared systems from interview answers; for each, prompts for `paths:` entries; writes `.specify/systems/<name>/spec.md` from the new template. |
| NEW | `skills/smith-migrate-system-paths/SKILL.md` | ~250 | Markdown | A3. Top-level skill: scans `.specify/systems/<name>/spec.md`, proposes `paths:` frontmatter from prose hints (services/X/, backend/X/, etc.), prompts per-system, writes accepted frontmatter above body. |
| NEW | `skills/smith-migrate-system-paths/scripts/propose_paths.py` | ~150 | Python | Heuristic prose → path-prefix proposer (regex matchers + frequency × position scoring). Called from the skill. |
| MODIFY | `scripts/parsers/path-resolver.py` | +~80 | Python | A4. Add `_load_declared_paths(project_root)` that scans `.specify/systems/*/spec.md` for YAML frontmatter `paths:` lists. Add `_apply_declared_paths()` as the new tier 1. Update `resolve()` to call tier 1 → tier 2 → tier 3 in order. |
| NEW | `scripts/parsers/contracts/system-spec-frontmatter.schema.json` | ~40 | JSON Schema | Validates frontmatter shape (system, status, paths, optional also_affects). Used by A3 + resolver for defensive parsing. |

### Track B — LLM-Generated Descriptions in `.meta`

| Action | Path | LOC | Lang | Purpose |
|---|---|---|---|---|
| MODIFY | `scripts/parsers/parse-python.py` | +~30 | Python | B1. Add `_stable_method_id(module_path, scope, name, params, return_type)` returning SHA-256 hex of canonical tuple. Inject `"id": <hex>` into each entry of `result["functions"]` and into each `method` entry under classes. Remove `docstring` field (per Q8 + structure-only mandate) or leave it but ignore in render. |
| MODIFY | `scripts/parsers/parse-js.js` | +~30 | JS | B2. Add `stableMethodId(modulePath, scope, name, params, returnType)` (SHA-256 via `crypto.createHash`). Inject `id` into entries of `result.functions`, `result.exports`, and `methods[]` inside each class. Remove `docstring: null` field if present. |
| MODIFY | `scripts/smith-index/run.py` | +~150 | Python | C2 + B5 + B6. Add `--describe` flag + `mode_describe()`. Update `render_meta()` to emit new description-layer fields and to read+preserve existing description fields (B6 — same renderer used by save hook). Update `render_system_manifest()` to include Description column (B4) pulled from per-module description fields parsed out of each .meta. |
| NEW | `scripts/parsers/meta_describe.py` | ~250 | Python | THE SHARED HELPER. Called by both `/smith-index --describe` and the three workflow skills. Three entrypoints: `describe_file(rel_path, source, parsed, existing_meta)` → full module+method descriptions; `update_touched(rel_path, source, parsed, existing_meta, touched_method_ids, purpose_shifted)` → partial update; `merge(existing_meta_text, new_descriptions)` → splice into markdown. Owns the Haiku call (stdlib `urllib.request` to Anthropic Messages API). |
| MODIFY | `hooks/manifest-updater-lib.py` | +~50 | Python | B6 hot path. Before writing new .meta, read existing .meta if present and extract description layer (`**Description:**`, per-function `Description:` lines keyed by `Id:`, `Described-Against-Hash:`, `Described-At:`). Pass extracted layer into the same `render_meta()` so it survives. Always update `Hash:`; never update `Described-Against-Hash:`. |

### Track C — Description Lifecycle

| Action | Path | LOC | Lang | Purpose |
|---|---|---|---|---|
| MODIFY | `skills/smith-new/SKILL.md` | +~40 | Markdown | C1. Add Phase 4.X step after Write/Edit: "Update touched-method descriptions via `meta_describe.py`". Pseudocode: parse diff → identify added/edited methods → call `meta_describe.update_touched(...)`. |
| MODIFY | `skills/smith-bugfix/SKILL.md` | +~40 | Markdown | C1. Same hook step as smith-new. |
| MODIFY | `skills/smith-debug/SKILL.md` | +~40 | Markdown | C1. Same hook step (debug edits source rarely, but when it does, same behavior). |
| MODIFY | `skills/smith-build/SKILL.md` | +~60 | Markdown | C1.5. In Phase 7.1 (Release Notes / PR description generation), add a "Manifest Coverage" section that runs `git diff main --name-only`, parses functions added/edited in each file, and for each touched method id checks `.meta` for a Description. Methods missing descriptions are listed under "Description Coverage Warnings" alongside the existing file-size warnings. Never blocks the PR. |
| MODIFY | `scripts/parsers/path-resolver.py` (C3) | (already counted in A4) | Python | C3 is implicit: the hash mismatch is the staleness signal, handled by save hook (already counted in manifest-updater-lib.py) and surfaced by `/smith-navigate` (already reads .meta — no new code; navigator simply checks `Described-Against-Hash` vs `Hash` and annotates). |

### Tests

| Action | Path | LOC | Lang | Purpose |
|---|---|---|---|---|
| NEW | `tests/parsers/test_meta_describe.py` | ~200 | Python | Unit: id stability across body edits, breaking on rename/signature change; merge() splicing; per-module / per-method threshold gating. |
| NEW | `tests/parsers/test_path_resolver_tier1.py` | ~120 | Python | Unit: `.specify/systems/` frontmatter parsing; longest-prefix; absent-systems-dir fallback; malformed frontmatter graceful degradation. |
| NEW | `tests/parsers/test_stable_id_python.py` | ~80 | Python | id changes on rename, id stable on body edit, id stable on reorder. |
| NEW | `tests/parsers/test_stable_id_js.js` | ~80 | JS | Same as test_stable_id_python.py for JS/TS. |
| NEW | `tests/hooks/test_description_preservation.py` | ~100 | Python | Integration: write existing .meta with description layer, run manifest-updater-lib.py, assert layer preserved + Hash updated + Described-Against-Hash unchanged. |
| NEW | `tests/skills/test_smith_migrate_system_paths.sh` | ~80 | Bash | End-to-end on a fixture project with hand-authored prose system specs. |
| NEW | `tests/skills/test_smith_index_describe.sh` | ~120 | Bash | --describe + --resume against `tests/fixtures/sample-project/`; assert JSONL log + checkpoint behavior. |
| NEW | `tests/skills/test_smith_build_coverage_flag.sh` | ~80 | Bash | Synthetic diff → PR description includes Manifest Coverage block listing methods without descriptions. |

### Docs

| Action | Path | LOC | Lang | Purpose |
|---|---|---|---|---|
| MODIFY | `CHANGELOG.md` | +~40 | Markdown | v2 entry under "Unreleased": tracks, breaking-change notes (none — additive), migration steps (`/smith-migrate-system-paths` then `/smith-index --describe`). |
| MODIFY | `docs/manifest-system.md` | +~150 | Markdown | Expand the v1 doc to cover tier 1, description layer, `/smith-index --describe`, staleness, coverage flag. (If the file doesn't exist, create with the v1+v2 doc in one place.) |

---

## Component Design

### A1 — `system-spec-template.md`

Located at `skills/smith/templates/system-spec-template.md`. Sample content:

```markdown
---
system: system-<name>
status: active   # active | deprecated | proposed
paths:
  - <literal-prefix-relative-to-project-root>/
also_affects: []  # optional cross-system pointer list
---

# System: <Human Name>

## Purpose

<one-paragraph summary>

## Owners

<names>

## Files & Components

<bulleted list of significant entry points>

## Interfaces

<APIs, public modules, IPC>

## Dependencies

<systems this one consumes>
```

Body is unconstrained — authors can drop the recommended sections. Only
the YAML frontmatter is machine-read.

### A2 — `/smith init` Sub-Step

Inserted in `skills/smith/SKILL.md` as a new "Phase 4.X Scaffold System
Specs". Pseudocode (in skill prose, not literal code):

1. After existing scaffolding (4.1-4.7), ask the operator: "Do you want
   to scaffold system specs now?" with options Yes / Skip (skip is
   appropriate for new projects that don't yet have system boundaries
   drawn).
2. If Yes, prompt for a comma-separated list of system identifiers
   (e.g. `system-01-auth, system-02-billing`).
3. For each system id, prompt for `paths:` entries one at a time
   (terminating empty entry).
4. For each system, copy `skills/smith/templates/system-spec-template.md`
   to `.specify/systems/<id>/spec.md`, substituting `<name>` placeholders
   and writing the user-supplied `paths:` list into the frontmatter.

Empty paths is allowed (file is still scaffolded; resolver tier 1 treats
empty `paths:` as no claim).

### A3 — `/smith-migrate-system-paths`

`skills/smith-migrate-system-paths/SKILL.md` walks the operator through:

1. Enumerate `.specify/systems/*/spec.md`.
2. For each file:
   - If YAML frontmatter exists AND has a non-empty `paths:` list → skip
     (idempotent).
   - Else read the prose body and run `propose_paths.py` (the helper)
     against it.
3. Present a per-system table to the operator:

   ```
   system-05-communication-triage
     proposed paths:
       - backend/src/services/triage/    (matched 7×)
       - frontend/src/lib/triage/        (matched 3×)
     accept / edit / skip ?
   ```

4. On accept, splice the frontmatter into the file (above any existing
   prose, preserving body verbatim). If the file already has a
   frontmatter block but no `paths:` field, insert only that field
   inside the existing `---` ... `---` block.
5. After all systems processed, print a summary report:
   `migrated: N | skipped (already has paths): M | skipped (user) : P`.

`propose_paths.py` algorithm: regex-match each of `services/<X>/`,
`backend/<X>/`, `frontend/<X>/`, `apps/<X>/`, fenced code-block file
references (` ```...path/file.ext ` patterns), and bulleted file paths
in `## Files` or `## Files & Components` sections. Aggregate matches per
candidate prefix. Score each candidate by `(match_count × position_weight)`
where `position_weight` decays with line offset from the top of the file
(prose near the top is usually scope-defining; later prose is detail).
Return the top-N (default 5) prefixes. Never auto-write — always
operator-confirm.

### A4 — Path Resolver Tier 1

In `scripts/parsers/path-resolver.py`, add:

```python
def _load_declared_paths(project_root: str) -> list[tuple[str, str]]:
    """Read .specify/systems/<name>/spec.md frontmatter, return list of
    (prefix, system_id) tuples sorted by len(prefix) descending."""
    systems_dir = Path(project_root or ".") / ".specify" / "systems"
    if not systems_dir.exists():
        return []
    out: list[tuple[str, str]] = []
    for spec in systems_dir.glob("*/spec.md"):
        fm = _parse_yaml_frontmatter(spec)
        if not fm:
            continue
        system_id = fm.get("system") or spec.parent.name
        for prefix in (fm.get("paths") or []):
            if isinstance(prefix, str) and prefix:
                out.append((prefix, system_id))
    out.sort(key=lambda t: len(t[0]), reverse=True)
    return out
```

`_parse_yaml_frontmatter()` is a tiny stdlib parser (no PyYAML
dependency): reads lines, captures the block between leading `---` and
the next `---`, then key:value + simple list parsing for the small
field set we accept. Malformed frontmatter returns `{}` (silently
ignored — tier 2/3 still apply).

`resolve()` adds a call before the existing overrides path:

```python
declared = _load_declared_paths(project_root)
for prefix, system_id in declared:   # already sorted longest-first
    if rel.startswith(prefix):
        return system_id
# fall through to tier 2 (system-paths.json) then tier 3 (heuristic)
```

The function is cached per resolver instance to avoid re-reading
`.specify/systems/` on every file lookup during a full index pass. Cache
is keyed by `project_root`.

### B1 / B2 — Stable Method ID

Recipe (identical across Python and JS implementations):

```
canonical_signature = (
    sorted_param_names_with_types
    + ":" + return_type_or_empty
)
input = f"{module_path}::{scope_chain}::{name}::{canonical_signature}"
id = sha256(input.encode("utf-8")).hexdigest()[:16]
```

Where:
- `module_path` is project-relative POSIX path (e.g. `backend/src/api.py`).
- `scope_chain` is `""` for module-level functions, `"ClassName"` for
  direct class methods. (Nested classes/methods are not in v1 scope —
  if encountered, fall through using the immediate-parent class name.)
- `name` is the function/method name as written.
- `canonical_signature` strips whitespace and normalizes default values
  to `=…` (so `x=1` and `x = 1` produce identical ids; default-value
  edits change id only if the literal token differs after whitespace
  strip).

Properties (validated by tests):
- Body edits → same id (signature unchanged).
- Method reorder within the file → same id.
- Method rename → different id (semantically a new method; description
  rebuilds rather than transfers).
- Parameter add/remove → different id.
- Module file move → different id (path changed).

The truncated 16-char SHA-256 is sufficient: per-file id collisions are
astronomically improbable (≤256 functions per file, 64-bit hash).

### B3 / B4 / B5 — `.meta` Layer & System Manifest Column

`.meta` markdown after v2 (showing only the new pieces):

```markdown
# backend/src/services/webhook.py
Last Updated: 2026-06-02T12:34:56Z
Language: python
Lines: 184
Hash: a1b2c3d4...
**Description:** Handles outbound webhook delivery with retry/backoff and dead-letter queue routing.
Described-Against-Hash: a1b2c3d4...
Described-At: 2026-06-02T12:34:56Z

## Functions
- `deliver(url: str, payload: dict, retries: int = 3) -> bool` (line 24)
  Id: 7f2a9c1e3d8b5f0a
  Description: Posts payload to url, retrying with exponential backoff. Returns False on persistent 5xx.
- `dead_letter(payload: dict) -> None` (line 81)
  Id: 4b8d6e2a9f1c0e7d
  Description: Persists the undeliverable payload to the dead-letter Redis stream.
```

Notes:
- `**Description:**` uses bold-field markdown to match v1 conventions
  (other v1 header lines like `Last Updated:` are plain; bold is used
  for the descriptive line so it stands out in `cat .meta`).
- Per-function `Id:` and `Description:` are indented two spaces under
  the function bullet to keep them visually nested.
- All v1 fields (Last Updated, Language, Lines, Hash, Imports, Routes,
  Classes, Functions, Exports, Parse Errors) keep their exact v1
  positions and labels.

System manifest at `.smith/index/systems/<system>.md` gains a Description
column:

```markdown
## Files

| File | Lines | Description | Exports |
|------|-------|-------------|---------|
| backend/src/services/webhook.py | 184 | Handles outbound webhook delivery with retry/backoff. | deliver, dead_letter |
```

Empty description → empty cell (no placeholder text). 80-line cap on
the manifest preserved by the existing 60-file truncation logic.

### B6 — Render Parity (Save Hook Preserves Descriptions)

`render_meta()` in `scripts/smith-index/run.py` gains an
`existing_descriptions` argument (default `None`):

```python
def render_meta(rel_path, parsed, hash_hex,
                existing_descriptions=None):
    """
    existing_descriptions: optional dict with keys:
        module_description: str | None
        described_against_hash: str | None
        described_at: str | None
        method_descriptions: dict[id, str]
    When None, the description layer is omitted entirely (new file).
    When present, it is spliced in verbatim.
    """
```

The save-hook path (`manifest-updater-lib.py`) reads the existing
`.meta` (if present), parses out the four description-layer values via
a tiny line-by-line markdown reader (no markdown parser dep), and
passes them through:

```python
existing = _parse_existing_descriptions(meta_target)
meta_text = run_mod.render_meta(rel, parsed, hash_hex,
                                 existing_descriptions=existing)
```

Result: every save preserves descriptions verbatim; only `Hash:` (and
structural fields) change. `Described-Against-Hash:` carries forward
its prior value — if it now differs from `Hash:`, the file is stale.

The `/smith-index --describe` and `meta_describe.update_touched()`
paths construct a NEW `existing_descriptions` dict with fresh
descriptions and the updated `described_against_hash = hash_hex`, then
call `render_meta()` the same way. Single source of truth for
rendering.

### C1 — Shared `meta_describe.py` Helper

Module signature:

```python
# scripts/parsers/meta_describe.py

def describe_file(rel_path: str, source: str, parsed: dict,
                  *, threshold: int = 5, model: str = "claude-haiku-4-5",
                  api_key: str | None = None) -> dict:
    """Full description pass for one file.
    Returns dict suitable for render_meta()'s existing_descriptions arg."""

def update_touched(rel_path: str, source: str, parsed: dict,
                   existing: dict, touched_method_ids: set[str],
                   purpose_shifted: bool, *, threshold: int = 5,
                   model: str = "claude-haiku-4-5",
                   api_key: str | None = None) -> dict:
    """Touched-methods-only update (C1 / Q11/A).
    - For each id in touched_method_ids: regen description.
    - Other ids in existing['method_descriptions']: passthrough.
    - If purpose_shifted: regen module description; else passthrough.
    Returns merged dict for render_meta()."""

def parse_meta_descriptions(meta_text: str) -> dict:
    """Reverse of render_meta()'s description layer — extract dict."""
```

Workflow integration (in `skills/smith-new/SKILL.md`,
`smith-bugfix/SKILL.md`, `smith-debug/SKILL.md`):

```
After Write/Edit on a source file:
1. Parse the diff to determine touched method ids.
   - Re-parse the file via parse-python.py / parse-js.js to get
     current ids and signatures.
   - Compare against existing .meta's Id: list: method ids that are
     NEW (not in existing) or whose signature changed → touched.
2. Determine purpose_shifted (heuristic): true iff
   - file gained an export the existing .meta did not have, OR
   - file gained a class the existing .meta did not have, OR
   - >50% of methods are new since last description run.
   Otherwise false.
3. Call meta_describe.update_touched(...) with these inputs.
4. Render and write the new .meta via render_meta(..., existing_descriptions=result).
```

This is documented in each skill as a numbered sub-step. The skill does
not implement parsing or Haiku calls itself — it shells out to
`python3 -c "from meta_describe import update_touched; ..."` or to a
small helper script.

Per-method threshold (Q7/C): in `update_touched`, skip ids whose
function spans <`threshold` lines (default 5). Data-config files
(extensions `.json`, `.yaml` — already not parsed) and files whose
`parsed["functions"]` is empty get per-module-only treatment. The
threshold is a config knob in `.smith/config.json` under
`manifest.describe.method_threshold_lines`; absent → 5.

### C1.5 — `/smith-build` Coverage Flag

In `skills/smith-build/SKILL.md` Phase 7.1, after Files Modified table,
add:

```
1. Run: git diff main --name-only
2. Filter to source files (.py / .js / .jsx / .ts / .tsx)
3. For each file, parse via project parser to get current method ids
4. For each method id present in the diff (added or modified lines),
   read .smith/index/files/<rel>.meta and look up the Id:'s Description:.
5. Collect (file, method_signature, method_id) tuples where description is missing or empty.
6. If non-empty, append a "Description Coverage Warnings" section to the PR description with the bullet list plus the helpful CTA: "Run `/smith-index --describe --system <name>` to backfill before merge."
```

The flag is non-blocking — the PR opens regardless. It surfaces
visibility, nothing more.

### C2 — `/smith-index --describe`

In `scripts/smith-index/run.py`:

```
argparse: parser.add_argument("--describe", action="store_true", ...)
argparse: parser.add_argument("--batch-size", type=int, default=20, ...)
argparse: parser.add_argument("--llm-batch-size", type=int, default=10, ...)
argparse: parser.add_argument("--threshold", type=int, default=5, ...)

if args.describe: return mode_describe(project_root, log_path, ...)
```

`mode_describe()` flow:

1. Walk source files (reuse `walk_source_files`).
2. Optional `--system <name>` filter.
3. For each file, read its existing `.meta`. If `Hash ==
   Described-Against-Hash` AND a `**Description:**` line is present,
   skip (hash cache).
4. Group remaining files into approval batches of size `--batch-size`
   (default 20).
5. For each approval batch:
   a. Prompt operator: `Approve batch 3/12 (20 files)? [Y/n/q/list]`.
      - `list` prints the file paths so the operator can reject some.
      - `n` skips this batch.
      - `q` aborts (checkpoint persists, --resume picks up).
   b. Sub-batch into LLM batches of `--llm-batch-size` (default 10).
   c. For each LLM batch:
      - Build per-file prompts (see research.md).
      - Call Haiku 4.5 (parallel via `concurrent.futures` up to N).
      - Merge into each file's existing description layer (preserve
        method descriptions whose ids are NOT in the parsed output —
        defensive: parser may have skipped a method due to syntax).
      - Render and write `.meta`.
      - Append JSONL log entry per file.
      - Update checkpoint.
6. After all batches: print summary (total / succeeded / failed /
   skipped).

`--resume`: read the most recent
`.smith/index/logs/smith-index-describe-*.jsonl`, build a set of
`item_id` where `status=ok` and `stage=describe`, skip those files in
discovery. Combined with hash-cache skip, double-protection against
re-describing already-described files.

JSONL record schema:

```json
{"timestamp": "2026-06-02T12:34:56.789Z", "item_id": "backend/src/api.py", "stage": "describe", "status": "ok", "error": null, "method_count": 7, "module_chars": 118}
```

`stage` values: `describe` (LLM call done, .meta written), `skipped`
(hash-cache or operator-reject), `failed`.

Checkpoint file:
`.smith/index/.smith-index-describe-checkpoint.json`:

```json
{
  "started_at": "...",
  "files_processed": 87,
  "last_batch_completed": 4,
  "approval_batch_size": 20,
  "llm_batch_size": 10,
  "system_filter": null,
  "log_path": ".smith/index/logs/smith-index-describe-20260602T123400Z.jsonl"
}
```

---

## Phase-by-Phase Build Order

1. **Parsers — stable method id** (B1, B2). Foundation; everything
   downstream keys descriptions on this id. Cannot defer.
2. **Path resolver — tier 1** (A4). Independent; can land before A1/A2
   so that any existing-project users running v2 immediately see correct
   buckets if they hand-write frontmatter.
3. **`meta_describe.py` shared helper** (C1 core). Pure Python module
   with mocked Haiku call for tests.
4. **`/smith-index --describe` wiring** (C2). Consumes (1) and (3).
5. **Save hook description-layer preservation** (B6 hot path). Modify
   `manifest-updater-lib.py` + `render_meta()`. Tested against the
   .meta layout produced by (4).
6. **Three workflow skills update step** (C1 integration). Modify
   `smith-new/SKILL.md`, `smith-bugfix/SKILL.md`, `smith-debug/SKILL.md`
   to call `meta_describe.update_touched()`.
7. **`/smith-build` coverage flag** (C1.5). Modify
   `smith-build/SKILL.md`. Independent.
8. **`system-spec-template.md` + `/smith init` sub-step** (A1, A2).
   Pure scaffolding; no runtime coupling.
9. **`/smith-migrate-system-paths` skill + propose_paths.py** (A3).
   Independent skill; safe to land last because it operates on existing
   projects and is operator-driven.
10. **Tests** for each component as it lands; final integration test
    run after step 9.
11. **Docs**: update `CHANGELOG.md` + `docs/manifest-system.md`.

Steps 1, 2, 7, 8, 9 can be parallelized once the foundation (1, 3) lands.
Steps 4, 5, 6 are sequential because 5 + 6 depend on the rendering and
helper shape established by 3 + 4.

---

## Testing Strategy

### Unit

- `test_stable_id_python.py` — id matrix (rename / body edit / reorder
  / param change / module path change).
- `test_stable_id_js.js` — same matrix for JS/TS.
- `test_path_resolver_tier1.py` — tier 1 frontmatter scan; longest
  prefix; tier 1 absent → tier 2 → tier 3 unchanged; malformed
  frontmatter ignored; cache invalidation across project roots.
- `test_meta_describe.py` — `update_touched` with mocked Haiku;
  threshold gating; passthrough of untouched method descriptions;
  module-description-only when purpose shifts; `parse_meta_descriptions`
  round-trip.

### Integration

- `test_smith_index_describe.sh` — end-to-end `--describe` against
  `tests/fixtures/sample-project/`; assert JSONL log shape (Rule 4),
  --resume continues from checkpoint, hash cache skips re-runs.
- `test_description_preservation.py` — write a `.meta` with a known
  description layer, run `manifest-updater-lib.py` against the source
  file, assert layer is verbatim and Hash updated.
- `test_smith_build_coverage_flag.sh` — fixture diff with one method
  having a description and one without; assert PR description includes
  only the missing-description method.
- `test_smith_migrate_system_paths.sh` — fixture `.specify/systems/`
  tree with hand-authored prose; assert proposal table + accepted
  frontmatter written above body without disturbing prose.

### Regression

- All v1 tests under `tests/parsers/`, `tests/hooks/`,
  `tests/skills/` pass unchanged.
- Path resolver behavior on a project without `.specify/systems/` is
  byte-identical to v1 (verified by snapshot test on `smith-repo`
  itself).
- `manifest-updater.sh` p95 latency stays <500ms (existing benchmark
  in `tests/perf/`).

---

## Risks & Mitigations

| ID | Risk | Likelihood | Mitigation |
|---|---|---|---|
| R1 | Haiku rate limit / cost spike on bulk runs | Medium | LLM batch N=10, per-file checkpoint with `--resume`, opt-in `--describe` flag, hash cache so re-runs skip stable files. Cost cap is operator-visible from the summary line. |
| R2 | Save hook overwrites the description layer | High if not tested | Explicit `test_description_preservation.py`; assertion in `render_meta()` that when `existing_descriptions` is passed, the rendered text contains every key from it. |
| R3 | Stable method id changes under refactor (rename, signature edit), dropping description | Medium | Expected behavior (rename = new method semantically). JSONL log records `status: rebuilt` (variant of `ok`) when a method id replaces a prior one in the same file, giving operators visibility. Documented in `docs/manifest-system.md`. |
| R4 | A3 prose-parsing proposes wrong paths | Medium | Mandatory per-system operator confirmation; A3 never auto-writes. Heuristic is scoring + top-N + edit affordance, not best-match. |
| R5 | v1 users with `system-paths.json` see precedence surprise | Low | Tier 1 only fires when `.specify/systems/<name>/spec.md` has frontmatter — projects that don't add frontmatter see zero behavior change. CHANGELOG documents tier order explicitly. |
| R6 | Smith workflows forget to call `meta_describe.update_touched()` | Low | `/smith-build` C1.5 PR coverage flag catches this at the gate — methods edited in the diff that lack descriptions appear in the PR description. |
| R7 | Hash recipe collision on real codebases | Negligible | SHA-256 truncated to 64 bits gives 2^32 collision distance per file; per-file scopes mean only same-file collisions matter (≤256 functions per file → 2^-24 probability). |
| R8 | Frontmatter parser fragility on malformed YAML | Medium | Tiny stdlib parser accepts the known field set only (system, status, paths, also_affects); malformed → silently fall through to tier 2/3. Validation via `system-spec-frontmatter.schema.json` is best-effort. |

---

## Migration / Compat Notes

### Projects on v1 with `.specify/systems/` declarations (e.g. armory)

1. Pull v2.
2. Run `/smith-migrate-system-paths` once. Walks 18 system specs (in
   armory's case), proposes path frontmatter from prose, operator
   confirms per-system, writes accepted frontmatter ABOVE existing
   prose body.
3. Run `/smith-index` (structural rebuild). Manifest now shows 18
   systems instead of 8.
4. Optionally run `/smith-index --describe` to backfill the description
   layer for the entire codebase. JSONL log + checkpoint allows
   pause/resume across multiple sessions for very large projects.

### Projects on v1 without `.specify/systems/`

Zero migration required. Tier 1 of the resolver no-ops (no
`.specify/systems/` to scan), tier 2 + tier 3 behave identically to v1.
`/smith-index --describe` is opt-in; not running it means `.meta`
files lack the description layer (which they did in v1 too — additive,
no regression).

### `.meta` schema compat

The new fields (`**Description:**`, per-function `Id:` +
`Description:`, `Described-Against-Hash:`, `Described-At:`) are all
additive. Old `.meta` files just lack them; the save hook and
`/smith-index` populate them naturally on next touch. v2's
`render_meta()` reads existing `.meta` defensively — if the file is in
v1 format, missing fields are treated as absent (not errors).

---

## Implementation Discoveries

Empty at plan time. Will be filled during build if surprises emerge.

---

2026-06-02 — 20-manifest-fixes
