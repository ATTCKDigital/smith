---
feature: 20-manifest-fixes
branch: 20-manifest-fixes
created: 2026-05-28
status: in-progress
spec: ./spec.md
plan: ./plan.md
note: Reconstructed 2026-06-02 after /tmp/ clearance
---

# Research: Manifest System v2 Fixes

Technical research grounding `plan.md`. Eight focus areas — stable
method id, resolver tier 1, system-spec frontmatter, A3 prose
heuristic, `.meta` description schema, Haiku prompt design, JSONL
checkpoint format, save-hook description preservation.

---

## 1. Stable Method ID Recipe

### Goal

Each function/method in `.meta` must have an identifier that:

- Stays the same when the method body is edited.
- Stays the same when methods are reordered within their file.
- Changes when the method is renamed.
- Changes when the method signature changes (param list / return type /
  default values).
- Changes when the file is moved (different module path = different
  semantic identity).
- Is identical between the Python and JS implementations (so test
  harnesses can use one schema across languages).

### Formula

```
canonical_signature =
  ",".join(f"{p.name}:{p.type or '_'}={p.default or '_'}" for p in params)
  + "->" + (return_type or "_")

input = f"{module_path}::{scope_chain}::{name}::{canonical_signature}"

id = sha256(input.encode("utf-8")).hexdigest()[:16]
```

- `module_path`: project-relative POSIX path
  (`backend/src/services/webhook.py`). Absolute paths are normalized via
  the same routine `path_resolver._normalise()` already uses.
- `scope_chain`: empty string for module-level functions; class name
  for direct methods. Nested cases are flattened to the innermost class
  name (v1 already flattens; see `_extract_classes` at
  `scripts/parsers/parse-python.py:149`).
- `name`: identifier as written.
- `canonical_signature`: built from the parser's already-extracted
  `params` (with `type`/`default` fields) and `return_type`. Missing
  fields are normalized to a single underscore so a Python-typed and
  an untyped JS function with the same param NAMES still produce
  different ids (the type field differs: `int` vs `_`).

### Why SHA-256 truncated to 16 hex chars (64 bits)

- 64 bits gives `2^32` birthday-collision distance.
- Per-file scope: only same-file collisions cause description mix-ups.
  A file with 256 functions has `256² / 2 ≈ 32_768` pairings — collision
  probability ~`2^-49`. Negligible.
- 16 hex chars is short enough to render legibly in `.meta` next to a
  function signature without bloating the file.

### Why this recipe resists body edits but breaks under rename

The input tuple deliberately excludes the function body. Renaming a
method changes `name`; the id rebuilds. Re-importing or reformatting
the body leaves `name`, `scope_chain`, `module_path`, and
`canonical_signature` untouched.

Edge: changing a default value (e.g. `retries=3` → `retries=5`)
changes the id. This is intentional — a default-value change is a
behavior-level edit worth re-describing.

### Validation tests (`tests/parsers/test_stable_id_python.py`)

| Test | Expect |
|---|---|
| Rename `deliver` → `dispatch` | id changes |
| Reorder methods within class | id stable |
| Change body (no signature change) | id stable |
| Add param | id changes |
| Remove param | id changes |
| Change return annotation | id changes |
| Move file `webhook.py` → `delivery.py` | id changes |
| Two files with identically-named function | distinct ids (path differs) |

---

## 2. Path Resolver Tier 1 Algorithm

### Data flow

```
At resolver instance creation:
  1. Locate <project_root>/.specify/systems/
  2. Iterate <name>/spec.md files
  3. For each file:
     - Read top-of-file YAML frontmatter (--- ... ---)
     - Extract `system` (default to <name> if missing)
     - Extract `paths: [str, ...]` (default to [])
     - For each prefix, append (prefix, system_id) to a list
  4. Sort by len(prefix) descending  (longest-prefix-wins)

At resolve(file_path):
  1. rel = normalize(file_path)
  2. For each (prefix, system_id) in pre-sorted list:
     - if rel.startswith(prefix): return system_id
  3. Fall through to tier 2 (system-paths.json)
  4. Fall through to tier 3 (_apply_heuristic)
```

### Caching

`_load_declared_paths(project_root)` is called once per resolver
instance and memoized with `functools.lru_cache(maxsize=8)` keyed by
`project_root`. The full-index run (`scripts/smith-index/run.py`) calls
`resolve()` per file (hundreds to thousands of times); the save hook
calls it once per invocation. Per-invocation cache hit rates approach
100% during a full index.

### YAML parsing (stdlib only)

We do NOT add PyYAML. Tiny inline parser handles the small field set:

```python
def _parse_yaml_frontmatter(path: Path) -> dict[str, object]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}
    body = text[4:end]
    out: dict[str, object] = {}
    current_list_key: str | None = None
    current_list: list[str] = []
    for line in body.splitlines():
        if not line.strip():
            current_list_key = None
            continue
        if line.startswith("  - ") and current_list_key:
            current_list.append(line[4:].strip().strip('"').strip("'"))
            out[current_list_key] = current_list
            continue
        if ":" in line and not line.startswith(" "):
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if val == "":
                current_list_key = key
                current_list = []
                out[key] = current_list
            else:
                current_list_key = None
                out[key] = val.strip('"').strip("'")
    return out
```

Recognized keys: `system`, `status`, `paths`, `also_affects`. Everything
else is ignored. Malformed input returns `{}`.

### Precedence proof

When two systems declare overlapping prefixes (e.g.
`services/auth/` and `services/auth/oauth/`), `len("services/auth/oauth/")
> len("services/auth/")`, so the sort puts oauth first. The first
match wins. For files under `services/auth/oauth/...`, oauth is
returned; for files under `services/auth/...` but not under oauth,
auth is returned. This matches the Q6/A "longest-prefix wins" decision.

---

## 3. System Spec Frontmatter Format

### Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "System Spec Frontmatter",
  "type": "object",
  "required": ["system"],
  "properties": {
    "system": {"type": "string", "pattern": "^system-[a-z0-9-]+$"},
    "status": {"type": "string", "enum": ["active", "deprecated", "proposed", "draft", "in-progress", "complete"]},
    "paths": {
      "type": "array",
      "items": {"type": "string", "minLength": 1}
    },
    "also_affects": {
      "type": "array",
      "items": {"type": "string"}
    }
  },
  "additionalProperties": true
}
```

`additionalProperties: true` so authors can extend (owners, deps,
links) without breaking the resolver.

`status` enum includes both spec terms (`active/deprecated/proposed`)
and the broader `draft/in-progress/complete` terms used elsewhere in
the Smith ecosystem — both are accepted.

### Example

```yaml
---
system: system-05-communication-triage
status: active
paths:
  - backend/src/services/triage/
  - frontend/src/lib/triage/
  - frontend/src/components/triage/
also_affects:
  - system-02-inbox
---

# System 05: Communication Triage

(prose body, hand-authored, untouched by A4)
```

### Validation

Validation is defensive (best-effort). On malformed input the resolver
silently treats the file as having no `paths:` claim. A3 validates
proposed frontmatter against the schema before writing.

---

## 4. A3 Prose-Parsing Heuristic

### Input

Existing `.specify/systems/<name>/spec.md` files written in prose like:

```
# System 05: Communication Triage

This system handles triage of inbound communications. Implementation lives in
`backend/src/services/triage/` with frontend bindings in
`frontend/src/lib/triage/`.

**Files:**
- backend/src/services/triage/router.py
- backend/src/services/triage/processor.py
- frontend/src/components/triage/TriageBoard.tsx
```

### Matchers

Regex matchers run in order; each produces (prefix, score) candidates.

| Matcher | Pattern | Source |
|---|---|---|
| Backticked dir | `` `([a-z0-9_\-/]+/)` `` | Inline code referencing a directory |
| Backticked file | `` `([a-z0-9_\-/]+/[a-z0-9_\-.]+)` `` | Inline code referencing a file; collapse to parent dir |
| Code fence file | `^[a-z0-9_\-/]+/[a-z0-9_\-.]+$` inside ``` blocks | Listed files in a fenced block |
| Bullet path | `^[\*\-] +([a-z0-9_\-/]+/[a-z0-9_\-.]+)$` | Listed in a markdown bullet under `**Files:**` etc |
| `services/<X>/` | `(services/[a-z0-9_\-]+/)` | Convention |
| `backend/<X>/` | `(backend/[a-z0-9_\-]+/)` | Convention |
| `frontend/<X>/` | `(frontend/[a-z0-9_\-]+/)` | Convention |
| `apps/<X>/` | `(apps/[a-z0-9_\-]+/)` | Convention |
| `packages/<X>/` | `(packages/[a-z0-9_\-]+/)` | Convention |

### Scoring

For each candidate prefix, score = `Σ (occurrence_position_weight)`
where `position_weight = max(0.3, 1.0 - (line_index / total_lines))`.
Prose near the top counts ~1.0; trailing detail counts ~0.3. Total
score per prefix is then ranked.

### Output

Top-N (default 5) prefixes per system spec, sorted by score
descending. Each presented to the operator with:

- The prefix string.
- The number of matches and aggregate score.
- Up to 3 line-quoted excerpts from the prose where the prefix
  appeared.

Operator can accept, edit (free-text replacement), or skip per
candidate.

### Why this is intentionally weak

A3's heuristic doesn't need to be smart — it needs to be transparent.
The operator confirms every system spec; the cost of a missed prefix
is "user adds it manually before accepting", not "wrong system in the
manifest". This trades algorithm sophistication for operator
auditability.

---

## 5. `.meta` Description Layer Schema

### File-level layout

```markdown
# <rel_path>                            ← v1
Last Updated: <iso>                     ← v1
Language: <lang>                        ← v1
Lines: <n>                              ← v1
Hash: <sha256-first-4kb>                ← v1
**Description:** <single-line ~120c>    ← v2 NEW
Described-Against-Hash: <hash>          ← v2 NEW
Described-At: <iso>                     ← v2 NEW
                                        ← blank line separating header from sections (v1)

## Imports                              ← v1, unchanged
...
## Routes                               ← v1, unchanged
...
## Classes                              ← v1, unchanged
...
## Functions                            ← v1, MODIFIED entry shape
- `name(sig) -> ret` (line N)           ← v1
  Id: <hex>                             ← v2 NEW (indented under bullet)
  Description: <one-to-two sentences>   ← v2 NEW (indented under bullet)
...
## Exports                              ← v1, unchanged
## Parse Errors                         ← v1, unchanged
```

### Field positions and parser reading

The save-hook description preservation reads existing `.meta` line by
line and harvests:

```python
def parse_existing_descriptions(meta_text: str) -> dict:
    out = {"module_description": None,
           "described_against_hash": None,
           "described_at": None,
           "method_descriptions": {}}
    in_functions = False
    current_id = None
    for line in meta_text.splitlines():
        if line.startswith("**Description:** "):
            out["module_description"] = line[len("**Description:** "):]
        elif line.startswith("Described-Against-Hash: "):
            out["described_against_hash"] = line[len("Described-Against-Hash: "):]
        elif line.startswith("Described-At: "):
            out["described_at"] = line[len("Described-At: "):]
        elif line.startswith("## Functions"):
            in_functions = True
        elif line.startswith("## ") and in_functions:
            in_functions = False
        elif in_functions and line.startswith("  Id: "):
            current_id = line[len("  Id: "):].strip()
        elif in_functions and line.startswith("  Description: ") and current_id:
            out["method_descriptions"][current_id] = line[len("  Description: "):]
            current_id = None
    return out
```

### Why bold for module, plain for per-method

`**Description:**` (module) uses bold so it visually anchors at the
top of the file when cat'ing the `.meta`. Per-method `Description:`
lives indented under each function bullet and stays plain to match
existing v1 indented-line conventions (the v1 docstring line, now
removed, used the same plain indented form).

---

## 6. Haiku Prompt Design

### Per-module prompt

```
SYSTEM: You produce concise one-line summaries of source modules.
Output ONLY a single line, no preamble, no markdown. Target ~120
characters. Focus on the module's primary responsibility.

USER:
File: backend/src/services/webhook.py
Language: python
Lines: 184
Imports:
  - requests
  - smith.config
Top-level functions:
  - deliver(url, payload, retries=3) -> bool
  - dead_letter(payload) -> None
Classes:
  - WebhookRetryHandler (methods: backoff, dead_letter, retry)

Source:
```
<full source>
```
```

Expected response: one line, ≤200 chars. We truncate to ~120 if longer
(soft cap).

### Per-method prompt (batch)

```
SYSTEM: For each method below, produce a one-to-two-sentence
description (~200 chars). Output JSON only:
{"<id>": "<description>", ...}

USER:
File: backend/src/services/webhook.py

Methods to describe:
- Id: 7f2a9c1e3d8b5f0a
  Name: deliver
  Signature: (url: str, payload: dict, retries: int = 3) -> bool
  Body lines: 24-58

- Id: 4b8d6e2a9f1c0e7d
  Name: dead_letter
  Signature: (payload: dict) -> None
  Body lines: 81-95

Full source for reference:
```
<full source>
```
```

JSON output is parsed (`json.loads`); ids not in the response are
left as missing in `.meta` (the JSONL log records `method_count` as
the number actually returned).

### Threshold gating

Before adding a method to the per-method prompt, check:

- `body_lines = end_line - start_line`. If `body_lines < threshold`
  (default 5), skip.
- Skip getter/setter/property patterns: heuristic — a single-line body
  matching `return self\.\w+` or `self\.\w+ = value` is treated as
  trivial.
- Skip if file extension is in `{".json", ".yaml", ".yml", ".toml"}` —
  not parsed as source anyway.

Threshold is a config knob; `threshold=0` yields full coverage.

### Cost / latency estimate

- Per-module call: ~500 input tokens (full source up to ~200 lines),
  ~50 output tokens.
- Per-method call (batched, 10 methods per call): ~2k input tokens,
  ~500 output tokens.
- Haiku 4.5 list-price (illustrative): $0.80/MTok input,
  $4.00/MTok output. Per file: ~$0.005 average. 400-file project:
  ~$2.00 total. Operator-visible in the final summary line.

---

## 7. JSONL Checkpoint Log Format

### Path

`.smith/index/logs/smith-index-describe-<YYYYMMDDTHHMMSSZ>.jsonl`

Per-run filename includes timestamp; `--resume` selects the most recent
file matching the pattern.

### Record schema

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
| timestamp | ISO 8601 ms | UTC |
| item_id | str | project-relative path |
| stage | str | `describe` / `skipped` / `failed` |
| status | str | `ok` / `error` / `skipped` |
| error | str/null | error class + message on failure |
| method_count | int | number of per-method descriptions written |
| module_chars | int | length of module description (post-truncate) |
| batch_index | int | approval batch number for traceability |

### Resume logic

```python
def find_completed(jsonl_path: Path) -> set[str]:
    completed = set()
    if not jsonl_path.exists():
        return completed
    with open(jsonl_path) as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("status") == "ok" and rec.get("stage") == "describe":
                completed.add(rec.get("item_id"))
    return completed
```

`mode_describe()` filters discovered files through `completed` before
the hash-cache filter. Triple-protection (operator-skip → resume-skip
→ hash-cache) ensures no double-billing under any restart scenario.

### Final summary

Printed to stdout on completion (clean or aborted):

```
/smith-index --describe: 187 files (174 succeeded, 2 failed, 11 skipped) in 14m32s
  Failed:
    - frontend/src/legacy/very-old.js (parser timeout)
    - backend/src/migrations/0042_add_column.py (file too large)
  Log: .smith/index/logs/smith-index-describe-20260602T123400Z.jsonl
```

---

## 8. Save-Hook Description Preservation Approach

### Goal

`manifest-updater.sh` fires on every `Write` / `Edit`. v1 path:

1. Parse file (structural).
2. Render `.meta` from parsed output.
3. Atomic-write to `.smith/index/files/<rel>.meta`.

v2 path inserts a "read + extract + preserve" step:

1. Parse file (structural). (unchanged)
2. Read existing `.meta` if present.
3. Extract description layer from existing `.meta` (per §5 reader).
4. Render `.meta` with `existing_descriptions=<extracted dict>`.
5. Atomic-write.

### Code path

In `hooks/manifest-updater-lib.py`, replace:

```python
meta_text = run_mod.render_meta(rel, parsed, hash_hex)
```

with:

```python
meta_target = files_dir / (rel + ".meta")
existing_descriptions = None
if meta_target.exists():
    try:
        existing_descriptions = run_mod.parse_existing_descriptions(
            meta_target.read_text(encoding="utf-8"))
    except OSError:
        existing_descriptions = None
meta_text = run_mod.render_meta(
    rel, parsed, hash_hex,
    existing_descriptions=existing_descriptions)
```

The `parse_existing_descriptions()` function lives in `run.py` (single
source of truth for both reader and writer of the description layer).

### Staleness signal

The save hook never updates `Described-Against-Hash`. After a save, if
`Hash != Described-Against-Hash`, the description is stale relative
to the current code. The signal is:

- Read by `/smith-navigate`: when listing files for routing, the
  navigator includes a `(stale description)` annotation next to any
  file with hash mismatch.
- Read by `/smith-index --describe`: hash mismatch is one of the two
  triggers (the other is missing description) that cause the file to be
  re-described. Hash-equal + description-present is the skip condition.

### Performance impact

- Reading the existing `.meta` adds one file read per save (≤4KB
  typically). On NVMe, <1ms.
- Parsing the description layer is a single line-by-line pass —
  linear in `.meta` size, O(few-thousand-chars) per file. <2ms.
- Net additional latency: ≤3ms per save. Well within the v1 <500ms
  p95 budget.

### Atomicity

The atomic-write pattern in `manifest-updater-lib.py` (`_atomic_write`,
lines 492-508) is unchanged. The description-layer fields land in the
tempfile and are renamed-in once the full render is complete. No
partial-write window where a save hook could observe a `.meta` missing
its descriptions.

---

2026-06-02 — 20-manifest-fixes
