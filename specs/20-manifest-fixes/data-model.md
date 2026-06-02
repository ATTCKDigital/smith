---
feature: 20-manifest-fixes
branch: 20-manifest-fixes
created: 2026-05-28
status: in-progress
spec: ./spec.md
plan: ./plan.md
research: ./research.md
questions: ./questions.md
contracts:
  - ./contracts/parser-output-v2.schema.json
  - ./contracts/meta-description-layer.schema.json
  - ./contracts/system-spec-frontmatter.schema.json
builds_on: 19-manifest-system (PR #19, merged 2026-05-21)
note: Reconstructed 2026-06-02 after /tmp/ clearance from committed spec.md + plan.md + research.md + questions.md
---

# Data Model: Manifest System v2 Fixes

This document defines the data shapes that flow between the v2 components.
v1 shapes (parser output, `.meta` structural fields, system manifest table)
are byte-stable; v2 layers are additive. The boundary between the
structural pass (parsers + save hook) and the description layer
(`/smith-index --describe`, smith workflows) is made explicit here so
implementation tasks can not accidentally cross it.

Reference contracts live under [`./contracts/`](./contracts/).

---

## §1. Parser Output JSON (v2)

### Diff from v1

The parser output shape (`parse-python.py`, `parse-js.js`) is structurally
identical to v1 ([`19-manifest-system/contracts/parser-output.schema.json`](../19-manifest-system/contracts/parser-output.schema.json))
with exactly ONE addition:

- **ADD** `id` field on each function entry under `functions[]` and on
  each method entry under `classes[].methods[]`. The id is a 16-char
  lowercase hex string — the stable method id from §1.1 below.

Nothing is removed. The v1 `docstring` field on `functions[]` entries
remains permitted by the schema (parsers MAY still emit it, but the
render layer ignores it — descriptions never come from parser output).
v1's `name`, `line`, `params`, `return_type`, `is_async`, `methods[]`,
`classes[].bases[]`, `imports[]`, `routes[]`, `exports[]`, `errors[]`,
`path`, `language`, `lines` are byte-stable.

### §1.1 Stable method id recipe

Identical across Python and JS parsers (the contract is by-value, not
by-implementation):

```
canonical_signature =
  ",".join(f"{p.name}:{p.type or '_'}={p.default or '_'}" for p in params)
  + "->" + (return_type or "_")

input = f"{module_path}::{scope_chain}::{name}::{canonical_signature}"

id = sha256(input.encode("utf-8")).hexdigest()[:16]
```

- `module_path` — project-relative POSIX path (e.g. `backend/src/api.py`).
- `scope_chain` — `""` for module-level functions; the parent class name
  for direct methods (nested classes flatten to the innermost class name).
- `name` — function/method identifier as written.
- `canonical_signature` — built from already-extracted `params` and
  `return_type`. Missing fields normalize to a single underscore so
  typed Python and untyped JS functions with the same param names produce
  distinct ids.
- Output: lowercase hex, exactly 16 characters (64 bits, truncated SHA-256).

### §1.2 JSON sample

```json
{
  "path": "backend/src/services/webhook.py",
  "language": "python",
  "lines": 184,
  "functions": [
    {
      "id": "7f2a9c1e3d8b5f0a",
      "name": "deliver",
      "line": 24,
      "params": [
        {"name": "url", "type": "str"},
        {"name": "payload", "type": "dict"},
        {"name": "retries", "type": "int", "default": "3"}
      ],
      "return_type": "bool",
      "is_async": false
    }
  ],
  "classes": [
    {
      "name": "WebhookRetryHandler",
      "line": 60,
      "bases": [],
      "methods": [
        {"id": "4b8d6e2a9f1c0e7d", "name": "backoff", "line": 65},
        {"id": "a3f0c8d2e7b14955", "name": "dead_letter", "line": 81}
      ]
    }
  ],
  "imports": [
    {"line": 1, "name": "requests", "kind": "import"}
  ],
  "routes": [],
  "exports": [],
  "errors": []
}
```

Note: NO `description`, `module_description`, `docstring_used`, or any
LLM-derived field appears anywhere in parser output. The parser is
STRUCTURAL ONLY.

---

## §2. `.meta` File Layout (v2)

v1 byte-stable header field names (`Last Updated:`, `Language:`,
`Lines:`, `Hash:`) are preserved. v2 inserts three new header lines
AFTER `Hash:` and BEFORE the blank line that separates the header
from sections. Per-method descriptions attach inline inside the
existing `## Functions` section under each function bullet (indented
two spaces).

### §2.1 Full template — described file

```
# <relative-path-from-project-root>
Last Updated: <ISO8601>
Language: <python|js|ts|jsx|tsx|css|html|sh>
Lines: <N>
Hash: <SHA-256 of source>
Description: <per-module summary, ≤120-char soft cap, single line>
Described-Against-Hash: <hash this description was generated against>
Described-At: <ISO8601 timestamp>

## Imports
- <name> (line N)
- ...

## Routes
- <METHOD> <path> -> <handler> (line N)
- ...

## Classes
- ClassName (line N)
  - method_name (id: <16-char id>, line N) — <per-method description, ≤200-char soft cap>
  - ...

## Functions
- func_name (id: <16-char id>, line N) — <per-method description, ≤200-char soft cap>
  Optional v1 lines: parameter and return type info
- ...

## Exports
- name (kind, line N)

## Parse Errors
- (line N, col C): <message>
```

### §2.2 Field-by-field semantics

| Field | Source | Updated by |
|---|---|---|
| `# <rel-path>` | Project-relative POSIX path | Renderer (v1 + v2) |
| `Last Updated:` | ISO8601 UTC at render time | Every render |
| `Language:` | Detected language tag | Every render |
| `Lines:` | Total line count (incl. blanks) | Every render |
| `Hash:` | SHA-256 of source (full file) | Every render — save hook, `/smith-index`, `--describe` |
| `Description:` (NEW) | Per-module description, ≤120-char soft cap | `/smith-index --describe`, smith workflows. NEVER save hook. |
| `Described-Against-Hash:` (NEW) | Value of `Hash:` at description generation time | `/smith-index --describe`, smith workflows. NEVER save hook. |
| `Described-At:` (NEW) | ISO8601 UTC of last description generation | `/smith-index --describe`, smith workflows. NEVER save hook. |
| `## Functions` entries — `id:` (NEW) | 16-char stable method id from parser | Every render |
| `## Functions` entries — inline description (NEW) | Per-method description, ≤200-char soft cap | `/smith-index --describe`, smith workflows. NEVER save hook. |

### §2.3 Absent-description state

When a file has never been described (e.g. fresh save hook on a
brand-new file, or `/smith-index` run without `--describe`), the
description-layer lines are OMITTED entirely:

```
# backend/src/services/webhook.py
Last Updated: 2026-06-02T12:34:56Z
Language: python
Lines: 184
Hash: a1b2c3d4...

## Imports
...
```

Implementations MAY render `Description: (none)` as an explicit
absence marker in tooling output, but the canonical `.meta` file on
disk OMITS the line. The reader (`parse_existing_descriptions()`)
treats absence and `(none)` as semantically equivalent (`None`).

Per-method inline descriptions are similarly omitted when not yet
generated: the function bullet renders as `- name (id: <hex>, line N)`
with no trailing ` — <desc>`.

### §2.4 Stale state

When `Described-Against-Hash:` is present but does not equal `Hash:`,
the description is considered stale. The save hook produces this
state naturally: it updates `Hash:` on every edit but never touches
`Described-Against-Hash:`. No "stale" boolean is stored — the
mismatch IS the signal.

---

## §3. Description Provenance & Freshness

### §3.1 Provenance fields

- `Described-Against-Hash:` records the source hash at the moment
  descriptions were generated. It is set ONLY by description-aware
  paths: `/smith-index --describe` (bulk) and the smith workflow
  in-context updaters (`/smith-new`, `/smith-bugfix`, `/smith-debug`).
- `Described-At:` records the ISO8601 UTC timestamp of that same
  generation event. Same writer set.

Both fields are written atomically with the description content
itself — never independently. A `.meta` file that has
`Described-Against-Hash:` MUST also have `Description:` (or per-method
descriptions in `## Functions`). The renderer enforces this by
refusing to emit provenance fields without an accompanying description.

### §3.2 Save hook behavior

`manifest-updater.sh` → `manifest-updater-lib.py` → `render_meta()`:

1. Parse source structurally.
2. Read existing `.meta` (if present).
3. Extract description layer via `parse_existing_descriptions()`.
4. Call `render_meta(rel, parsed, hash_hex, existing_descriptions=<extracted>)`.
5. Atomic-write.

The save hook NEVER updates `Described-Against-Hash:` or `Described-At:`.
It updates `Hash:` to reflect the new source content. If the new
`Hash:` differs from the preserved `Described-Against-Hash:`, the
file is stale.

### §3.3 Detection by `/smith-navigate`

The navigator (read-only) consumes `.meta` files via the system
manifest. When listing files for routing decisions, it checks:

```python
if described_against_hash and described_against_hash != current_hash:
    annotate(file, "(stale description)")
```

The annotation downranks the description as a hint rather than
authoritative signal. The navigator does NOT trigger regeneration.

### §3.4 Atomic update by description paths

`/smith-index --describe` and `meta_describe.update_touched()` always
write the description layer + provenance fields together:

```python
new_layer = {
    "module_description": "...",       # or unchanged passthrough
    "method_descriptions": {id: "..."},
    "described_against_hash": hash_hex, # CURRENT hash at write time
    "described_at": now_iso(),
}
meta_text = render_meta(rel, parsed, hash_hex,
                        existing_descriptions=new_layer)
```

This guarantees that after a successful description pass, `Hash:` ==
`Described-Against-Hash:` for that file.

---

## §4. LLM-Layer Input/Output Contract

The `meta_describe.py` helper is the sole entry point that crosses
the structural ↔ description boundary. It consumes parser-emitted
structural JSON for ONE file plus the existing `.meta` description
layer, and produces a new description layer ready for splicing.

### §4.1 Input

```python
@dataclass
class MetaDescribeInput:
    rel_path: str            # project-relative POSIX path
    source: str              # full source text (for the prompt)
    parsed: dict             # parser output (matches §1 schema)
    existing: dict | None    # MetaDescription (§4.2) or None
    touched_method_ids: set[str] | None  # None = describe all (bulk path)
    purpose_shifted: bool    # workflow heuristic; bulk passes True
    threshold: int           # min body lines for per-method (default 5)
    model: str               # e.g. "claude-haiku-4-5"
    api_key: str | None      # ANTHROPIC_API_KEY override
```

### §4.2 Output

```python
@dataclass
class MetaDescription:
    module_description: str | None  # ≤120-char soft cap, single line
    method_descriptions: dict[str, str]  # id -> ≤200-char description
    described_against_hash: str     # SHA-256 hex of source at write time
    described_at: str               # ISO8601 UTC, e.g. "2026-06-02T12:34:56Z"
```

This is what gets passed to `render_meta(..., existing_descriptions=...)`.
The dataclass is logical; the serialized JSON form is documented in
[`./contracts/meta-description-layer.schema.json`](./contracts/meta-description-layer.schema.json).

### §4.3 Boundary invariants

- The parser side NEVER reads or writes any `MetaDescription` field.
- The LLM side NEVER modifies any parser output field (it consumes
  `parsed` read-only).
- The save hook NEVER constructs a `MetaDescription` — it only
  preserves one that exists.
- Source code is NEVER modified by either side. The only output
  surface for descriptions is `.meta` files under `.smith/index/`.

---

## §5. System Spec Frontmatter

YAML block at the top of `.specify/systems/<name>/spec.md`, validated
by [`./contracts/system-spec-frontmatter.schema.json`](./contracts/system-spec-frontmatter.schema.json).

### §5.1 Schema

```yaml
---
system: system-<NN>-<short-name>
paths:
  - <relative-prefix-or-exact-path>/
  - ...
status: draft | in-progress | complete | active | deprecated | proposed
also_affects:               # optional, list of other system ids
  - system-<other-id>
---
```

### §5.2 Field semantics

| Field | Required | Notes |
|---|---|---|
| `system` | yes | MUST match the directory name (`.specify/systems/<name>/` → `<name>`). Pattern: `^system-(\d+-)?[a-z][a-z0-9-]*$`. |
| `paths` | no | List of literal directory prefixes (project-relative, ending in `/`). NO globs in v1 — any path containing `*`, `?`, `[`, `]`, `{`, `}`, `!` is rejected by A3 migration and `/smith init` scaffolding. May be omitted; system contributes nothing to tier 1 in that case (tier 2/3 still resolve files via heuristic). |
| `status` | no | Default `active`. Accepted values cover both spec terminology and broader Smith ecosystem terms (see contract). |
| `also_affects` | no | Optional cross-system pointer list. Each entry MUST match an existing `.specify/systems/<other>/` directory — validated by the resolver at load time. |

### §5.3 Validation rules

A3 (`/smith-migrate-system-paths`) and `/smith init` MUST validate:

1. `system` value equals the parent directory name. Mismatch → ERROR
   (refuse to write).
2. Each `paths:` entry ends with `/`. Missing trailing slash →
   automatic correction (append `/`) with a warning.
3. No `paths:` entry contains a glob character (`*?[]{}!`). Present →
   ERROR (refuse to write); CHANGELOG note: globs deferred to v3.
4. Each `also_affects:` entry corresponds to an existing
   `.specify/systems/<id>/` directory. Missing → WARN (write anyway;
   the dangling pointer is informational).

The resolver applies the same rules defensively at load time:
malformed frontmatter is silently skipped (tier 1 no-ops for that
spec), so an authoring error never breaks indexing — it only weakens
tier-1 coverage for that system.

### §5.4 Empty/absent paths

A spec.md with no `paths:` field, or with `paths: []`, contributes
zero entries to the resolver's tier-1 prefix list. Files in such a
project still get bucketed by tier 2 (`system-paths.json`) and tier 3
(directory heuristic, which matches the directory name when it equals
`<system>` minus the `system-NN-` prefix).

---

## §6. Path-Resolver Internal State

### §6.1 In-memory shape

```python
# Built by _load_declared_paths(project_root) at resolver init.
declared_paths: list[tuple[str, str]]
# Each entry: (prefix, system_id).
# Sorted by len(prefix) DESCENDING — longest-prefix-wins by iteration order.
```

### §6.2 Build algorithm

```
1. systems_dir = <project_root>/.specify/systems
2. if not systems_dir.exists(): return []
3. for spec in systems_dir.glob("*/spec.md"):
     fm = _parse_yaml_frontmatter(spec)         # stdlib tiny parser
     if not fm: continue
     system_id = fm.get("system") or spec.parent.name
     for prefix in (fm.get("paths") or []):
       if isinstance(prefix, str) and prefix:
         result.append((prefix, system_id))
4. result.sort(key=lambda t: len(t[0]), reverse=True)
5. return result
```

### §6.3 Cache

```python
@functools.lru_cache(maxsize=8)
def _load_declared_paths(project_root: str) -> tuple[tuple[str, str], ...]:
    ...
```

- Cache key: `(project_root, last_mtime_of_specs_dir)`. The resolver
  computes `last_mtime_of_specs_dir` once per process via
  `os.stat(systems_dir).st_mtime_ns`. When the directory tree is
  modified between full-index runs, the cache key changes and the
  function reloads.
- Within a single full-index run (`scripts/smith-index/run.py`), the
  cache hit rate approaches 100% (one call per file lookup, all keyed
  on the same project root).

### §6.4 Resolution call

```python
def resolve(self, file_path: str, project_root: str | None = None) -> str:
    rel = self._normalise(file_path, project_root)
    declared = _load_declared_paths(project_root or ".")
    for prefix, system_id in declared:
        if rel.startswith(prefix):
            return system_id
    # Fall through to tier 2 (system-paths.json) then tier 3 (heuristic).
    return self._tier2_or_tier3(rel)
```

---

## §7. `/smith-index --describe` Checkpoint + JSONL Log

Rule-4 compliance: checkpoint file + JSONL log + `--resume` + summary.

### §7.1 Checkpoint file

Path: `.smith/index/.smith-index-describe-checkpoint.json` (single
file, overwritten each batch).

Shape:

```json
{
  "started_at": "2026-06-02T12:34:00Z",
  "total_files": 187,
  "processed_files": ["backend/src/api.py", "backend/src/auth.py", "..."],
  "approval_batch_size": 20,
  "llm_batch_size": 10,
  "model": "claude-haiku-4-5",
  "system_filter": null,
  "log_path": ".smith/index/logs/smith-index-describe-20260602T123400Z.jsonl",
  "last_batch_completed": 4
}
```

Updated AFTER each LLM batch completes (not per-file). `--resume`
reads `processed_files` as the skip list, in addition to the
JSONL-derived completed set (§7.3).

### §7.2 JSONL log

Path: `.smith/index/logs/smith-index-describe-<YYYYMMDDTHHMMSSZ>.jsonl`
(one file per `--describe` invocation; timestamp at start time, UTC).

One JSON object per processed file, appended atomically:

```json
{
  "timestamp": "2026-06-02T12:34:56.789Z",
  "item_id": "backend/src/services/webhook.py",
  "stage": "describe",
  "status": "ok",
  "error": null,
  "method_count": 7,
  "module_chars": 118,
  "batch_index": 4
}
```

| Field | Type | Notes |
|---|---|---|
| `timestamp` | string (ISO8601 ms, UTC) | Time the line was appended |
| `item_id` | string | Project-relative POSIX path |
| `stage` | string | `describe` (LLM call done, `.meta` written) / `skipped` (hash-cache hit or operator reject) / `failed` (LLM error, parse failure, write failure) |
| `status` | string | `ok` / `error` / `skipped` |
| `error` | string \| null | Error class + message on failure; `null` otherwise |
| `method_count` | integer | Number of per-method descriptions written for this file |
| `module_chars` | integer | Length of the module description (post truncation) |
| `batch_index` | integer | Approval-batch number, 1-indexed, for traceability |

### §7.3 Resume logic

```
--resume:
  1. Locate the most recent log file matching
     .smith/index/logs/smith-index-describe-*.jsonl.
  2. Read line-by-line; build set of item_ids where
     status == "ok" AND stage == "describe".
  3. Also load checkpoint.json; union processed_files into the skip set.
  4. Apply skip set during discovery, BEFORE the hash-cache filter.
```

Triple protection (operator-skip → resume-skip → hash-cache) ensures
no double-billing under restart.

### §7.4 Final summary

Printed to stdout on completion (clean OR aborted):

```
/smith-index --describe: 187 files (174 succeeded, 2 failed, 11 skipped) in 14m32s
  Failed:
    - frontend/src/legacy/very-old.js (parser timeout)
    - backend/src/migrations/0042_add_column.py (file too large)
  Log: .smith/index/logs/smith-index-describe-20260602T123400Z.jsonl
```

This satisfies Rule 4's "status summary on completion or failure"
requirement.

---

## §8. Track A Schemas — `paths:` Validation

Pinned constraint for v1: `paths:` entries MUST be literal directory
prefixes ending in `/`. Globs are deferred to v3.

### §8.1 Allowed shape

- Project-relative POSIX path.
- Ends with `/`.
- Contains none of: `*`, `?`, `[`, `]`, `{`, `}`, `!`.

Pattern in the JSON Schema (see `system-spec-frontmatter.schema.json`):
`^[^*?\\[\\]{}!]+/$`.

### §8.2 Enforcement points

| Path | Enforcement | Failure mode |
|---|---|---|
| `/smith init` scaffolding (A2) | Validate user input before writing | Re-prompt with a clear message: "paths must be literal directories (no globs); v1 limitation" |
| `/smith-migrate-system-paths` (A3) | Validate proposed prefix against pattern; reject candidates with glob chars before presenting | Skip candidate; do not present to operator |
| Resolver `_load_declared_paths` | Silently drop invalid entries; log a debug message to stderr if verbose | Tier 1 weakens for the affected system; tier 2/3 still apply |

### §8.3 Forward compatibility

When v3 introduces glob support, the schema's `paths.items.pattern`
will be relaxed and the resolver will gain a glob-precedence rule.
v1's literal-only constraint is the conservative starting point: any
v1 `paths:` list is also a valid v3 `paths:` list.

---

## §9. `/smith-build` `.meta`-Description Coverage Check

Non-blocking PR flag (C1.5 / Q4-C). Produces a "Description Coverage
Warnings" section in the PR body alongside the existing v1 ">300-line
file" warnings.

### §9.1 Algorithm

```
1. files = `git diff main --name-only`
2. Filter to source files (.py, .js, .jsx, .ts, .tsx).
3. For each file in files:
     a. Run the project parser → parsed.functions, parsed.classes.
     b. Identify methods affected by the diff:
        - Parse `git diff main -- <file>` hunks.
        - For each hunk, intersect added/modified line ranges with
          each (function.line, end_line) range.
        - Collect set of touched method ids.
     c. Read .smith/index/files/<file>.meta if present.
     d. Build a dict id → description from the .meta `## Functions`
        section.
     e. For each touched id, check whether a non-empty description
        exists. If not, append to misses list.
4. If misses non-empty, render the PR body section.
```

### §9.2 Output format

```markdown
### Description Coverage Warnings

3 methods in this diff lack `.meta` descriptions:
- backend/src/services/webhook.py::WebhookRetryHandler::backoff
- backend/src/services/webhook.py::WebhookRetryHandler::dead_letter
- frontend/src/lib/api/products.ts::fetchProductBundle

Run `/smith-index --describe --system <name>` to backfill before merge.
```

The section is appended to the existing v1 "File Size Warnings" block
(or stands alone if the file-size block is empty). The PR opens
unconditionally — the flag is informational only.

### §9.3 Failure modes

- If a touched file has no `.meta` (e.g. brand-new file from the same
  PR), all touched methods count as missing — correct behavior.
- If the parser fails on a touched file, the file is skipped (no
  misses recorded for that file) and a single line is appended to
  the section: `- (skipped: parser error on <file>)`.
- If `git diff` returns nothing (clean tree, target branch ahead),
  the coverage check is a no-op.

---

## Cross-References

- v1 parser output schema: [`../19-manifest-system/contracts/parser-output.schema.json`](../19-manifest-system/contracts/parser-output.schema.json)
- v2 parser output schema (additive): [`./contracts/parser-output-v2.schema.json`](./contracts/parser-output-v2.schema.json)
- `.meta` description layer (LLM-emitted, serialized form): [`./contracts/meta-description-layer.schema.json`](./contracts/meta-description-layer.schema.json)
- System spec frontmatter: [`./contracts/system-spec-frontmatter.schema.json`](./contracts/system-spec-frontmatter.schema.json)
- Spec: [`./spec.md`](./spec.md)
- Plan: [`./plan.md`](./plan.md)
- Research: [`./research.md`](./research.md)
- Questions: [`./questions.md`](./questions.md)

---

2026-06-02 — 20-manifest-fixes
