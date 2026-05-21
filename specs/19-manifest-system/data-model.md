---
feature: 19-manifest-system
branch: 19-manifest-system
created: 2026-05-21
spec: ./spec.md
plan: ./plan.md
---

# Data Model: Manifest System

This document defines every persistent shape introduced by this feature.
Schemas are normative for the implementation phase. Examples are
illustrative.

The JSON Schema for parser output is split out into
`contracts/parser-output.schema.json`. The markdown contract for
`/smith-navigate` output is in `contracts/navigator-output.md`.

---

## 1. Parser Output JSON (parse-python.py / parse-js.js)

Both parsers emit identical JSON shape (with language-specific
field semantics). Authoritative schema:
`contracts/parser-output.schema.json`.

### Shape

```json
{
  "path": "backend/src/api/v1/products.py",
  "language": "python",
  "lines": 387,
  "functions": [
    {
      "name": "create_product",
      "line": 230,
      "params": [
        {"name": "request", "type": "ProductCreateRequest"},
        {"name": "db", "type": "Session", "default": "Depends(get_db)"}
      ],
      "return_type": "ProductResponse",
      "docstring": "Create a new product and sync to Shopify."
    }
  ],
  "classes": [
    {
      "name": "ProductService",
      "line": 45,
      "methods": [
        {"name": "__init__", "line": 47},
        {"name": "sync", "line": 89}
      ]
    }
  ],
  "imports": [
    {"line": 1, "name": "fastapi", "kind": "from", "imported": ["APIRouter", "Depends"]},
    {"line": 5, "name": "backend.src.models", "kind": "from", "imported": ["Product"]}
  ],
  "routes": [
    {"method": "POST", "path": "/products", "line": 230, "function": "create_product"},
    {"method": "GET",  "path": "/products/{id}", "line": 285, "function": "get_product"}
  ],
  "exports": [
    {"name": "router", "line": 12, "kind": "module-level"}
  ],
  "errors": []
}
```

### Field reference

| Field | Type | Required | Notes |
|---|---|---|---|
| `path` | string | yes | Path as passed to parser (may be absolute or project-relative). |
| `language` | string | yes | `"python"` \| `"javascript"` \| `"typescript"`. JSX/TSX collapse to JS/TS. |
| `lines` | integer | yes | Total line count including blank lines. |
| `functions[]` | array | yes | May be empty. |
| `functions[].name` | string | yes | |
| `functions[].line` | integer | yes | 1-based. |
| `functions[].params[]` | array | yes | May be empty. |
| `functions[].params[].name` | string | yes | |
| `functions[].params[].type` | string \| null | no | Type hint as source text. |
| `functions[].params[].default` | string | no | Default value as source text. |
| `functions[].return_type` | string \| null | no | |
| `functions[].docstring` | string \| null | no | First line only, stripped. |
| `classes[]` | array | yes | |
| `classes[].name` | string | yes | |
| `classes[].line` | integer | yes | |
| `classes[].methods[]` | array | yes | |
| `classes[].methods[].name` | string | yes | |
| `classes[].methods[].line` | integer | yes | |
| `imports[]` | array | yes | |
| `imports[].line` | integer | yes | |
| `imports[].name` | string | yes | Module path. |
| `imports[].kind` | string | yes | `"import"` \| `"from"` \| `"require"`. |
| `imports[].imported` | array of string | no | For `from X import a, b` style. |
| `routes[]` | array | yes | May be empty. Populated when decorator matches FastAPI/Express patterns. |
| `routes[].method` | string | yes | Uppercase HTTP verb. |
| `routes[].path` | string | yes | |
| `routes[].line` | integer | yes | |
| `routes[].function` | string | yes | Handler function name. |
| `exports[]` | array | yes | JS only — empty array for Python. |
| `exports[].name` | string | yes | |
| `exports[].line` | integer | yes | |
| `exports[].kind` | string | yes | `"named"` \| `"default"` \| `"module-level"` \| `"react-component"`. |
| `errors[]` | array | yes | May be empty. Populated on parse failures. |
| `errors[].line` | integer | no | |
| `errors[].col` | integer | no | |
| `errors[].message` | string | yes | |

---

## 2. `.meta` File (per-file markdown)

Path: `.smith/index/files/<mirrored-path>/<file>.meta` (note: the
`.meta` is the literal extension; `<file>` retains its full filename
including original extension).

Example: `backend/src/api/v1/products.py` →
`.smith/index/files/backend/src/api/v1/products.py.meta`

### Template

```markdown
# backend/src/api/v1/products.py
Last Updated: 2026-05-21T12:01:00Z
Language: python
Lines: 387

⚠️ Exceeds 300-line threshold (387 lines). Consider decomposition.

## Imports
- `fastapi` → APIRouter, Depends (line 1)
- `sqlalchemy.orm` → Session (line 3)
- `backend.src.models` → Product (line 5)

## Routes
| Method | Path                | Line | Handler          |
|--------|---------------------|------|------------------|
| POST   | /products           | 230  | create_product   |
| GET    | /products/{id}      | 285  | get_product      |
| PATCH  | /products/{id}      | 312  | update_product   |
| DELETE | /products/{id}      | 350  | delete_product   |

## Classes
- `ProductService` (line 45)
  - `__init__` (line 47)
  - `sync` (line 89)
  - `validate` (line 134)

## Functions
- `create_product(request: ProductCreateRequest, db: Session) -> ProductResponse` (line 230)
  Create a new product and sync to Shopify.
- `get_product(id: int, db: Session) -> ProductResponse` (line 285)
  Fetch a product by ID.

## Parse Errors
_None._
```

### Rules

- The `⚠️ Exceeds 300-line threshold` line is present **if and only if**
  `lines > 300`. The renderer omits it otherwise.
- Sections with no content render as `_None._` or `_Empty._` — never
  omitted, so diffing two `.meta` files for the same file is structurally stable.
- The "Last Updated" timestamp uses ISO 8601 UTC.
- `.meta` files are NOT line-capped. They scale with file complexity.

---

## 3. System Manifest (`systems/<system>.md`)

Path: `.smith/index/systems/<system-name>.md`.

### Template (≤80 lines)

```markdown
# System: system-15-command-center
Last Updated: 2026-05-21T12:01:00Z

## Description
Backend + frontend implementation of the Command Center feature.
Handles product CRUD, Shopify sync, and admin UI.

## Files

| File | Lines | Exports |
|------|-------|---------|
| backend/src/api/v1/products.py | 387 ⚠️ | create_product, get_product, update_product, delete_product, router |
| backend/src/models/product.py | 142 | Product, ProductCreate, ProductResponse |
| backend/src/services/shopify_sync.py | 256 | ShopifySyncService, sync_product |
| frontend/src/lib/api/products.ts | 89 | createProduct, getProduct, updateProduct, deleteProduct |
| frontend/src/components/ProductList.tsx | 178 | ProductList |
| frontend/src/components/ProductForm.tsx | 234 | ProductForm |
| backend/tests/test_products.py | 412 ⚠️ | (test module) |

_If a system has >65 files, only the largest 60 are listed; the
balance appears as `…and N more files (see .meta for full inventory)`._
```

### Rules

- `⚠️` appended to the line count if file >300 lines.
- `Exports` column is comma-joined; truncates with `…` after 80 chars.
- Files sorted by lines desc — largest first.
- Truncation rule (>65 files) per research.md section 6.

---

## 4. Top-Level Manifest (`manifest.md`)

Path: `.smith/index/manifest.md`.

### Template (≤50 lines)

```markdown
# Project Manifest
Last Updated: 2026-05-21T12:01:00Z

## Systems

| System | Files | Description |
|--------|-------|-------------|
| system-01-api | 24 | Backend HTTP layer |
| system-02-models | 18 | SQLAlchemy models + Pydantic schemas |
| system-03-frontend | 47 | React UI |
| system-04-shopify-sync | 12 | Shopify integration |
| system-15-command-center | 8 | Command Center feature (in progress) |
| unassigned | 3 | Files not matched by system-paths.json |

## Stats

- Total source files: 112
- Files over 200 lines: 31
- Files over 300 lines: 9
- Files over 500 lines: 2
- Last full index: 47.3s (2026-05-21T11:58:00Z)
```

### Rules

- "Stats" section is the canonical place to read aggregates from.
- "Last full index" is updated only by `/smith-index` (full rebuild),
  never by `manifest-updater.sh` (which only updates the
  `Last Updated:` timestamp and individual file/threshold counters).

---

## 5. `context-manifest.json` Schema

### Per-skill block

```json
{
  "vault": {
    "sessions": 5,
    "ledger": "top-20",
    "bank": "all",
    "queue": "pending",
    "agents": "all"
  },
  "navigator": true,
  "navigator_scope": "task_specific",
  "system_specs": "affected_systems_only"
}
```

### Field reference

| Field | Type | Allowed values | Default if missing |
|---|---|---|---|
| `vault.sessions` | integer \| "all" \| "none" | 0..50 \| "all" \| "none" | 3 |
| `vault.ledger` | string \| integer | "all" \| "none" \| "top-N" (1≤N≤100) | "top-20" |
| `vault.bank` | string | "all" \| "none" \| "recent" | "recent" |
| `vault.queue` | string | "all" \| "pending" \| "none" | "pending" |
| `vault.agents` | string | "all" \| "none" \| "recent" | "recent" |
| `navigator` | boolean | true \| false | false |
| `navigator_scope` | string | "full_project" \| "changed_files_context" \| "error_context" \| "task_specific" | "task_specific" |
| `system_specs` | string | "none" \| "frontmatter_only" \| "affected_systems_only" \| "all_frontmatter" | "none" |

### Top-level shape (the file)

```json
{
  "_meta": {
    "version": 1,
    "tier_label": "repo-default"
  },
  "_default": { "vault": {...}, "navigator": false, ... },
  "smith-new":    { "vault": {...}, "navigator": true,  ... },
  "smith-bugfix": { "vault": {...}, "navigator": true,  ... },
  "smith-debug":  { "vault": {...}, "navigator": true,  ... },
  "smith-build":  { "vault": {...}, "navigator": false, ... },
  "smith-audit":  { "vault": {...}, "navigator": false, ... },
  "smith-vault":  { "vault": {"sessions": 0, "ledger": "none", ...}, "navigator": false },
  "smith-help":   { "vault": {"sessions": 0, "ledger": "none", ...}, "navigator": false },
  "smith-bank":   { "vault": {...}, "navigator": false }
}
```

### 4-tier resolution rule (Decision 4)

For a given skill (e.g. `smith-bugfix`), the effective config is built by:

1. Start with `_default` from the built-in fallback (Tier 1).
2. Field-merge `_default` then `<skill>` from Tier 2 (repo-shipped).
3. Field-merge `_default` then `<skill>` from Tier 3 (user-global).
4. Field-merge `_default` then `<skill>` from Tier 4 (project override).

Merge semantics:
- For scalar fields (`navigator`, `navigator_scope`, `system_specs`,
  `vault.sessions`, etc.): later tier replaces earlier.
- For object fields (`vault`): merge per-key. The user can override
  `vault.sessions` without restating `vault.ledger`.
- For `_meta`: the LAST tier seen wins; used in logs to identify
  source.

### Field-level merge example

Tier 2 (repo) for `smith-build`:
```json
{ "vault": {"sessions": 3, "ledger": "top-20"}, "navigator": false }
```

Tier 4 (project) for `smith-build`:
```json
{ "navigator": true, "navigator_scope": "changed_files_context" }
```

Effective:
```json
{
  "vault": {"sessions": 3, "ledger": "top-20", "bank": "recent",
            "queue": "pending", "agents": "recent"},
  "navigator": true,
  "navigator_scope": "changed_files_context",
  "system_specs": "none"
}
```

(Missing `vault.bank`/`queue`/`agents` and `system_specs` filled from
Tier 1 `_default`.)

---

## 6. `system-paths.json` Schema

```json
{
  "_comment": "Customize for your project. Longest-prefix match.",
  "rules": [
    {
      "prefix": "backend/src/api/v1/products",
      "system": "system-15-command-center"
    },
    {
      "prefix": "backend/src/api",
      "system": "system-01-api"
    },
    {
      "prefix": "frontend/src",
      "system": "system-03-frontend",
      "_comment": "All frontend code"
    }
  ],
  "default": "unassigned"
}
```

### Field reference

| Field | Type | Required | Notes |
|---|---|---|---|
| `rules[]` | array | yes | May be empty. |
| `rules[].prefix` | string | yes | Path prefix relative to project root. No globs. |
| `rules[].system` | string | yes | System name. |
| `rules[]._comment` | string | no | Free-form comment; ignored. |
| `default` | string | no | Fallback system name. Default `"unassigned"`. |

### Matching rule

Sort `rules` by `len(prefix)` descending. For a given file path, iterate
and return the first rule where `path.startswith(prefix)`. If none
match, return `default`.

---

## 7. `/smith-navigate` Output Schema (Markdown)

Authoritative contract: `contracts/navigator-output.md`. Summary:

### Required structure

```markdown
## Relevant Files

### Must Read (directly impacted)
- <path>[ [primary: <line-range>, <label>]]

### Should Read (likely affected)
- <path>[ [primary: <line-range>, <label>]]

### Reference Only (context, don't modify)
- <path>

### Systems Affected
- Primary: <system-name>
- Also affects: <system-name>[, <system-name>...]
```

### Annotation format

`[primary: <start>-<end>, <label>]` where:
- `<start>` and `<end>` are 1-based line numbers
- `<label>` is a short noun phrase (≤6 words, e.g. "POST endpoint",
  "ProductCreate", "sync interface")
- Annotation is **optional** — files with no clear primary section
  appear as just `- <path>` with no brackets

### Per-bucket semantics

| Bucket | Meaning | Reading guidance |
|---|---|---|
| Must Read | Files the task likely modifies or whose behavior it depends on | Read whole file; focus on primary range |
| Should Read | Files that border the task — callers, callees, fixtures | Read whole file; primary range optional |
| Reference Only | Files providing context but NOT modified | Read primary range only OR scan headings; do not edit |

### Special case — manifest missing

If `.smith/index/manifest.md` is missing, the navigator returns:

```markdown
## Relevant Files
_Manifest not initialized — run `/smith-index` first._
```

Calling code detects this exact sentinel string and falls back to
vault-only injection.

---

## 8. `additionalContext` Injection Block

Inserted by `context-loader.sh` as the `additionalContext` value of
the UserPromptSubmit response.

### Full example (skill = `smith-bugfix`, manifest present)

````markdown
<!-- smith-context-injection v1; skill=smith-bugfix; tier=project; ts=2026-05-21T12:01:00Z -->

## Smith Context

### Vault — Recent Sessions (3)
- **2026-05-20** — Refactored Shopify sync to retry on 429. [vault/sessions/2026-05-20-shopify-retry.md]
- **2026-05-19** — Added `/products` POST endpoint scaffolding. [vault/sessions/2026-05-19-products-post.md]
- **2026-05-18** — Discussed system-15 command-center scoping. [vault/sessions/2026-05-18-command-center.md]

### Vault — Ledger (top-20)
- Patterns: 14 entries — see `.smith/vault/ledger/patterns.md`
- Antipatterns: 8 entries — see `.smith/vault/ledger/antipatterns.md`
- Tool preferences: 6 entries
- Edge cases: 4 entries

### Vault — Queue (pending: 2)
- [Q-019] Investigate flaky test_products_create
- [Q-021] Document the new context-loader hook

### Manifest Navigator

## Relevant Files

### Must Read (directly impacted)
- backend/src/api/v1/products.py [primary: 230-380, POST endpoint]
- backend/src/models/schemas.py [primary: 200-280, ProductCreate]

### Should Read (likely affected)
- backend/src/services/shopify_sync_service.py [primary: 1-50, sync interface]
- frontend/src/lib/api/products.ts

### Reference Only (context, don't modify)
- backend/tests/test_products.py

### Systems Affected
- Primary: system-15-command-center
- Also affects: system-01-api, system-04-shopify-sync
````

### Skeleton variant — manifest missing

````markdown
<!-- smith-context-injection v1; skill=smith-bugfix; tier=project; ts=2026-05-21T12:01:00Z; manifest=missing -->

## Smith Context

> ⚠️ Manifest not initialized — run `/smith-index` to enable structured context retrieval. Proceeding with vault context only.

### Vault — Recent Sessions (3)
- ...
````

### Skeleton variant — Smith skill with no navigator (e.g. `/smith-help`)

````markdown
<!-- smith-context-injection v1; skill=smith-help; tier=repo-default; ts=2026-05-21T12:01:00Z -->

## Smith Context

_Navigator disabled for this skill. No vault sections requested._
````

(In practice, for `smith-help` and `smith-vault` the resolved config
has all vault sections set to `"none"` and `navigator: false`, so this
empty block is the expected output. The injection happens but is
trivially small — meeting spec's "zero context overhead" criterion in
spirit while still providing the comment marker for observability.)

### HTML comment header

Every injection begins with the comment:

```html
<!-- smith-context-injection v1; skill=<skill>; tier=<tier>; ts=<iso>; [flags] -->
```

Flags:
- `manifest=missing` — soft-warning was used.
- `navigator=timeout` — navigator timed out, vault-only fallback used.
- `navigator=error` — navigator returned an error, vault-only used.

Used by tests to assert correct behavior.

---

## 9. JSONL Log Line Format (Rule 4 — `/smith-index`)

Path: `~/.smith/logs/smith-index-<ISO8601>.jsonl`.

### Schema

```json
{
  "timestamp": "2026-05-21T12:01:00.123Z",
  "item_id": "backend/src/api/v1/products.py",
  "stage": "parse",
  "status": "ok",
  "error": null
}
```

### Fields

| Field | Type | Required | Allowed values |
|---|---|---|---|
| `timestamp` | string (ISO 8601 with ms) | yes | UTC; `Z` suffix. |
| `item_id` | string | yes | Project-relative source path. |
| `stage` | string | yes | `"parse"` \| `"meta"` \| `"system-update"` \| `"top-update"` \| `"checkpoint"` |
| `status` | string | yes | `"ok"` \| `"error"` \| `"skipped"` |
| `error` | string \| null | yes | Free-text on error; `null` otherwise. |

### Resume semantics

A file is considered "complete" (and skipped on `--resume`) iff there
exists at least one JSONL line for it with `stage="system-update"` AND
`status="ok"`. Earlier stages without `system-update` mean the file
was partially processed and should be retried.

### Run summary line

After the JSONL stream, the run prints a human-readable summary to
stdout (not JSONL):

```
/smith-index: 142 files indexed (138 succeeded, 4 failed, 0 skipped) in 47.3s
```

The summary is NOT written to the JSONL log.

---

## 10. Hook Activity Log Line Format (`~/.smith/logs/hooks.log`)

Existing convention extended for the two new hooks. One line per event:

```
2026-05-21T12:01:00Z manifest-updater file=backend/src/api/v1/products.py ext=.py parser=python lines=387 system=system-15-command-center ms=287 warnings=over-300
2026-05-21T12:01:05Z context-loader skill=smith-bugfix tiers=1,2,4 vault_chars=2143 navigator_ms=1850 navigator_status=ok total_ms=3712
2026-05-21T12:01:10Z context-loader skill=null reason=no-trigger ms=14
```

Format: `<ISO timestamp> <hook-name> key=value [key=value ...]`. Same
convention as existing hooks; greppable; no escaping needed for
typical values.

2026-05-21 12:03:00 — 19-manifest-system
