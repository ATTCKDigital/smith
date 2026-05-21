---
contract: smith-navigate output
version: 1
spec: ../spec.md
data-model: ../data-model.md
---

# Contract: `/smith-navigate` Output Format

This document is the normative contract for the markdown returned by the
`/smith-navigate` Haiku sub-agent. The skill's prompt template in
`skills/smith-navigate/SKILL.md` must instruct Haiku 4.5 to produce
exactly this shape. Consumers (`context-loader.sh`, `/smith-explore`
Phase 1) parse based on the headings below.

This contract implements **Design Decision 2** from `spec.md`:
*whole-file reads with primary-section annotations, NOT tight line
ranges*.

---

## Required Structure

Every successful response is a single Markdown block beginning with the
exact heading `## Relevant Files` and containing the four subsections
below in this order:

```markdown
## Relevant Files

### Must Read (directly impacted)
- <path-1>[ [primary: <start>-<end>, <label>]]
- <path-2>[ [primary: <start>-<end>, <label>]]

### Should Read (likely affected)
- <path-3>[ [primary: <start>-<end>, <label>]]
- <path-4>

### Reference Only (context, don't modify)
- <path-5>
- <path-6>

### Systems Affected
- Primary: <system-name>
- Also affects: <system-name>[, <system-name>...]
```

### Required headings (verbatim)

| Heading | Level | Required |
|---|---|---|
| `## Relevant Files` | H2 | yes (exactly once) |
| `### Must Read (directly impacted)` | H3 | yes |
| `### Should Read (likely affected)` | H3 | yes |
| `### Reference Only (context, don't modify)` | H3 | yes |
| `### Systems Affected` | H3 | yes |

All four buckets MUST be present even if empty. An empty bucket renders as:

```markdown
### Should Read (likely affected)
_None._
```

### Path entries

- Each path is on its own line, prefixed by `- ` (dash-space).
- Paths are project-relative, using `/` separators on all platforms.
- No trailing whitespace, no trailing punctuation.
- Paths may optionally be followed by a space and a primary-section annotation in square brackets.

---

## Primary-Section Annotation

The annotation indicates the most relevant lines within an otherwise
whole-file read. Format:

```
[primary: <start>-<end>, <label>]
```

| Token | Rule |
|---|---|
| `primary:` | Lowercase keyword, literal. |
| `<start>` | 1-based integer. |
| `<end>` | 1-based integer, ≥ start. |
| `<label>` | Short noun phrase, ≤6 words, no commas inside. |

### Allowed variations

- Annotation may be **omitted entirely** when no single section dominates.
  In that case the line is just `- <path>`.
- Annotation may use a single-line range (`[primary: 230-230, ...]`).
- Annotation may target a top-of-file region (`[primary: 1-50, ...]`)
  for interface/header sections.

### Disallowed

- Multiple annotations per file (e.g. `[primary: 10-30, x] [primary: 50-70, y]`) — pick the dominant one.
- Tight-range mode (selecting only the annotated range to read) — this is reserved for a future `--tight-ranges` opt-in per spec Non-Goals.
- Negative or zero line numbers.
- Labels containing newlines, commas, or square brackets.

---

## Bucket Semantics (Operational)

The buckets are NOT advisory categories — they have concrete operational meaning for the consuming session.

### Must Read (directly impacted)

**Definition:** Files that the task likely modifies, OR files whose
behavior the task directly depends on. If Claude misses one of these,
the task is at risk of producing wrong code.

**Reading guidance:** Read the WHOLE file. Use the primary annotation
as the focus point (start reading there, expand outward).

**Editing guidance:** These are the most likely Edit/Write targets.

**Typical count:** 1-5 files.

### Should Read (likely affected)

**Definition:** Files that border the task — direct callers of Must
Read files, files imported by Must Read files, fixtures/schemas the
task interacts with.

**Reading guidance:** Read the WHOLE file. Primary annotation is
optional and may be absent.

**Editing guidance:** Usually NOT edited, but might be touched for
cross-cutting changes (e.g. adding a new field to a schema).

**Typical count:** 2-8 files.

### Reference Only (context, don't modify)

**Definition:** Files that provide context without being edited —
tests covering the affected code, related specs in `.specify/systems/`,
documentation, fixture data.

**Reading guidance:** Read the primary range (if annotated) OR scan
section headings. Do not necessarily read the whole file.

**Editing guidance:** DO NOT edit. If a change here is needed,
reclassify mentally to Should Read and flag to the user.

**Typical count:** 1-6 files.

### Systems Affected

**Definition:** The systems (per `system-paths.json` mapping) whose
files appear in any of the three above buckets.

**Format:**
- `- Primary: <system-name>` — the system containing the most Must Read files.
- `- Also affects: <name>[, <name>...]` — comma-separated list of other systems represented. Omit the "Also affects" line if only one system is affected.

---

## Reserved / Sentinel Responses

### "Manifest not initialized"

When `.smith/index/manifest.md` does not exist, the navigator returns
exactly:

```markdown
## Relevant Files
_Manifest not initialized — run `/smith-index` first._
```

No other content. Consumers detect this sentinel by:
1. Checking that `## Relevant Files` is followed immediately by the
   italicized `_Manifest not initialized_` line.
2. Falling back to vault-only context if matched.

### "No relevant files found"

When the manifest exists but the navigator cannot match the user's
task to any system, all four buckets render as `_None._`, and Systems
Affected reads:

```markdown
### Systems Affected
_No matching system. Recommend `/smith-explore` for broader analysis._
```

Consumers may surface this back to the user verbatim.

---

## Examples

### Example 1: Simple backend task

User task: *"Add a DELETE endpoint to products."*

```markdown
## Relevant Files

### Must Read (directly impacted)
- backend/src/api/v1/products.py [primary: 230-380, existing CRUD endpoints]
- backend/src/services/shopify_sync_service.py [primary: 120-180, delete sync]

### Should Read (likely affected)
- backend/src/models/product.py [primary: 1-80, Product model]
- backend/tests/test_products.py

### Reference Only (context, don't modify)
- .specify/systems/system-15-command-center/spec.md

### Systems Affected
- Primary: system-15-command-center
- Also affects: system-04-shopify-sync
```

### Example 2: Frontend-only task

User task: *"Fix the product list pagination."*

```markdown
## Relevant Files

### Must Read (directly impacted)
- frontend/src/components/ProductList.tsx [primary: 80-150, pagination logic]
- frontend/src/lib/api/products.ts [primary: 30-60, list endpoint client]

### Should Read (likely affected)
- frontend/src/hooks/usePagination.ts

### Reference Only (context, don't modify)
- frontend/src/__tests__/ProductList.test.tsx

### Systems Affected
- Primary: system-03-frontend
```

### Example 3: Empty buckets

User task: *"Where is the email-sending logic?"* — exploratory only.

```markdown
## Relevant Files

### Must Read (directly impacted)
_None._

### Should Read (likely affected)
- backend/src/services/email_service.py [primary: 1-100, send_email interface]
- backend/src/services/templates/email_templates.py

### Reference Only (context, don't modify)
- backend/tests/test_email_service.py

### Systems Affected
- Primary: system-03-email-contact
```

---

## Parser Compatibility

`context-loader.sh` and `/smith-explore` parse the navigator output by:

1. Locating the literal `## Relevant Files` heading.
2. Splitting on the four `### ` headings within that section.
3. For each bucket, extracting lines beginning with `- `.
4. For each entry, applying the regex
   `^- (?P<path>\S+)(?: \[primary: (?P<start>\d+)-(?P<end>\d+), (?P<label>[^\]]+)\])?$`
   to extract path and (optional) annotation.

If the regex fails to match a line, the line is skipped and a warning
is logged to `~/.smith/logs/hooks.log`. Malformed entries do not block
the consuming session.

The HTML comment header pattern from data-model.md section 8 wraps
this contract output when injected via `additionalContext`; the
navigator itself does not emit the HTML comment — the caller adds it.

2026-05-21 12:04:00 — 19-manifest-system
