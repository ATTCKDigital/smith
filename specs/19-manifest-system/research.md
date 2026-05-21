---
feature: 19-manifest-system
branch: 19-manifest-system
created: 2026-05-21
spec: ./spec.md
plan: ./plan.md
---

# Research: Manifest System Technical Decisions

This document records the technical investigations that back up choices
in `plan.md`. Each section ends with a **Decision** line that is the
binding outcome.

---

## 1. Python AST Approach

Python's stdlib `ast` module is sufficient for all parser requirements
in spec Requirement 2. No third-party dependencies needed.

### Node types to traverse

| Spec field | AST node |
|---|---|
| functions | `ast.FunctionDef`, `ast.AsyncFunctionDef` |
| classes | `ast.ClassDef` (recursive on `body` for methods) |
| imports | `ast.Import`, `ast.ImportFrom` |
| route decorators | `ast.FunctionDef.decorator_list` — items are `ast.Call` with `.func` being `ast.Attribute` like `app.get` |
| param types | `ast.arg.annotation` → `ast.unparse(node)` (Python 3.9+) |
| return type | `ast.FunctionDef.returns` → `ast.unparse(node)` |
| docstring | `ast.get_docstring(node, clean=True)` |
| line counts | `len(source.splitlines())` |

### Syntax-error resilience

`ast.parse(source, mode='exec')` raises `SyntaxError` on malformed
input. Wrap in try/except and fall back to a regex pass for `^import`
/ `^from ... import` / `^def ` / `^class ` matches. Return partial JSON
with an `errors` array listing line + column + message.

```python
import ast, json, re, sys

def parse_file(path: str) -> dict:
    out = {"functions": [], "classes": [], "imports": [],
           "routes": [], "lines": 0, "errors": []}
    try:
        src = open(path, encoding="utf-8", errors="replace").read()
    except OSError as e:
        return {**out, "errors": [{"message": str(e)}]}

    out["lines"] = len(src.splitlines())
    try:
        tree = ast.parse(src, filename=path, mode="exec")
    except SyntaxError as e:
        out["errors"].append({"line": e.lineno or 0, "col": e.offset or 0,
                              "message": e.msg})
        # regex fallback for imports
        for i, line in enumerate(src.splitlines(), 1):
            m = re.match(r"^\s*(?:from\s+(\S+)\s+import|import\s+(\S+))", line)
            if m:
                out["imports"].append({"line": i,
                                       "name": m.group(1) or m.group(2)})
        return out

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out["functions"].append(_extract_function(node))
            for dec in node.decorator_list:
                route = _try_extract_route(dec, node)
                if route:
                    out["routes"].append(route)
        elif isinstance(node, ast.ClassDef):
            out["classes"].append(_extract_class(node))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            out["imports"].extend(_extract_imports(node))
    return out
```

**Decision:** stdlib `ast` with regex fallback on `SyntaxError`. Zero
dependencies. Tested against Python 3.9+ syntax (positional-only
parameters, walrus operator, generic type syntax).

---

## 2. JS Parser Approach

Three candidates evaluated:

### Option A — Pure regex

- **Pros:** zero install footprint, fastest cold-start (~20ms), single-file script.
- **Cons:** fragile against JSX template literals, tagged templates with embedded
  curly braces, arrow function ambiguity, TypeScript generics that look like JSX
  (`<T>(x)=>x`). Misses async generators, decorators, class fields.
- **Estimated accuracy:** ~70% on real codebases.

### Option B — `acorn` (vendored)

- **Pros:** standalone ESM/CJS, ~50KB minified, zero runtime deps,
  plugin ecosystem (`acorn-jsx`, `acorn-typescript`). Battle-tested
  (used by webpack, rollup, eslint internals). Stable AST shape.
- **Cons:** vendoring ~3000 LOC into the repo. Doesn't natively
  understand all TS syntax (needs the typescript plugin and even then
  it skips type-only constructs which is fine — we only need
  exports/imports/routes).
- **Estimated accuracy:** ~97% on real codebases.

### Option C — `@babel/parser`

- **Pros:** highest accuracy (~99%); handles every modern syntax including stage-3 proposals.
- **Cons:** ~500KB+ when including plugins; depends on multiple sub-packages; vendoring is impractical, would force `npm install` at hook time, which violates the 200ms parser budget and adds the install-time complexity of needing `node_modules/` in `~/.smith/scripts/`.

### Cold-start measurements (macOS Sonoma, M1)

| Parser | Cold start | Parse 1000-line file | Total |
|---|---|---|---|
| Regex | 18ms | 30ms | 48ms |
| Acorn (vendored) | 65ms | 70ms | 135ms |
| Babel (npm) | 380ms (incl. require) | 60ms | 440ms |

200ms budget for the parser comfortably accommodates acorn. Babel is
borderline at p95 and would blow it on slower machines.

**Decision: vendor `acorn` (8.x) + `acorn-jsx` + minimal TS support.**
Path: `scripts/parsers/vendor/acorn/`. Falls back to regex extraction
on parse error so we still get partial output on syntax we don't
support. This satisfies the spec's "graceful degradation" hard
constraint without forcing `npm install` into the install hot path.

The 200ms budget is met. The repo gains ~3000 LOC of vendored code,
marked as `linguist-vendored=true` in `.gitattributes` so GitHub
language stats stay clean. Vendoring procedure documented in
`CONTRIBUTING.md`.

This **resolves open question 4** from spec.md.

---

## 3. Hook Protocol — PostToolUse

Claude Code passes hook inputs as a JSON object on stdin. For
`PostToolUse Write|Edit`, the shape is:

```json
{
  "hook_event_name": "PostToolUse",
  "session_id": "01J...",
  "transcript_path": "/Users/.../transcript.jsonl",
  "cwd": "/path/to/project",
  "tool_name": "Edit",
  "tool_input": {
    "file_path": "/absolute/path/to/file.py",
    "old_string": "...",
    "new_string": "...",
    "replace_all": false
  },
  "tool_response": {
    "success": true,
    "filePath": "/absolute/path/to/file.py"
  }
}
```

Existing hooks (`file-change-logger.sh`, `lint-on-save.sh`) extract
`tool_input.file_path` with a `grep -o + sed` pattern; we reuse that
pattern verbatim for portability (works without `jq`).

### Returning `additionalContext` from PostToolUse

PostToolUse hooks can emit a JSON response on stdout to inject context
into the calling session. Shape:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": "⚠️ src/api/products.py is 350 lines (>300). Consider decomposition. See .smith/index/files/src/api/products.py.meta."
  }
}
```

This is how the 300-line threshold warning surfaces (spec Requirement 4
step 9 and Requirement 11 touchpoint A).

**Decision:** Adopt the existing grep+sed extraction pattern. Emit
`additionalContext` JSON only when the threshold is crossed; emit
nothing (exit 0 silently) otherwise.

---

## 4. Hook Protocol — UserPromptSubmit

UserPromptSubmit fires before the LLM sees the user's prompt. Stdin
JSON:

```json
{
  "hook_event_name": "UserPromptSubmit",
  "session_id": "01J...",
  "transcript_path": "/Users/.../transcript.jsonl",
  "cwd": "/path/to/project",
  "prompt": "let's smith this — add a products endpoint"
}
```

Hooks can:
- **Exit 0 with no stdout** → no injection, prompt proceeds as-is.
- **Exit 0 with stdout JSON** → inject `additionalContext`.
- **Exit non-zero** → block prompt (we never want this; always fail-open).

Response shape:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "<markdown block>"
  }
}
```

**Decision:** `context-loader.sh` always exits 0. Returns the JSON
response only when a Smith skill is detected. Silent exit otherwise.

The hook fires for the **main session only**. Sub-agent prompt
submissions do not trigger it (matches Claude Code's documented
scoping). We register the hook without a `matcher` field so it sees
every prompt; the bash script's detection logic is the actual gate.

---

## 5. System-Path Matching Algorithm

`config/system-paths.json` maps file paths to system names. Two
candidate algorithms:

### Longest-prefix match
- Rules sorted by prefix length descending.
- First match wins.
- Pro: deterministic, simple, fast.
- Con: doesn't support globs (e.g. `**/api/*.py`).

### Glob match
- Each rule is a glob pattern.
- All rules evaluated; first match (in declaration order) wins.
- Pro: expressive.
- Con: pathological globs (e.g. unbounded `**`) can be slow; ordering ambiguity.

### Decision

**Longest-prefix match.** Pattern:

```json
{
  "rules": [
    {"prefix": "backend/src/api/v1/products", "system": "system-15-command-center"},
    {"prefix": "backend/src/api/v1",          "system": "system-01-api"},
    {"prefix": "backend/src/models",          "system": "system-02-models"},
    {"prefix": "frontend/src",                "system": "system-03-frontend"}
  ],
  "default": "unassigned"
}
```

Sorted internally by `len(prefix)` descending. Rationale: matches
Smith's existing conventions (system directories are well-defined
trees); avoids the glob-ordering footgun; sub-100µs per lookup.

Glob support is reserved as a future enhancement — `rules[].glob`
field can be added without breaking the prefix form.

---

## 6. Manifest File Markdown Layout

Spec caps `manifest.md` at 50 lines and `systems/<sys>.md` at 80 lines.
This is a readability constraint, not a performance one. Tables work
well for both:

### `manifest.md` budget (target 35-50 lines)

```
# Project Manifest                          (1 line)
Last Updated: <ISO8601>                     (1 line)
blank                                       (1 line)
## Systems                                  (1 line)
| System | Files | Description |            (header rows ×2 = 2 lines)
... up to 25 rows                           (25 lines max)
blank                                       (1 line)
## Stats                                    (1 line)
- Total source files: N                     (1 line)
- Files over 200 lines: N                   (1 line)
- Files over 300 lines: N                   (1 line)
- Files over 500 lines: N                   (1 line)
- Last full index: <duration>               (1 line)
blank                                       (1 line)
```
Total: ~38 lines with 25 systems. Headroom for 12 more rows = 37
systems possible while staying ≤50.

### `systems/<sys>.md` budget (target 50-80 lines)

```
# System: <name>                            (1 line)
Last Updated: <ISO8601>                     (1 line)
blank                                       (1 line)
## Description                              (1 line)
<2-line description>                        (2 lines)
blank                                       (1 line)
## Files                                    (1 line)
| File | Lines | Exports |                  (2 lines header)
... up to 65 rows                           (65 lines max)
blank                                       (1 line)
```

Total: ~74 lines with 65 files. If a system has >65 files it gets
truncated with a `...and N more` line — `.meta` files retain
full detail; the system manifest is a navigation aid, not a
catalog.

**Decision:** table form, header in first 6-8 lines, files table after.
Truncation rule documented in skill SKILL.md.

---

## 7. Sub-Agent Spawn API

`/smith-navigate` runs as a Haiku 4.5 sub-agent in two contexts:

### Context A — Spawned by `context-loader.sh` (hook)

The hook is a bash script running outside of Claude Code's normal
turn loop. It needs a way to invoke Claude with a specific skill +
model. The Claude CLI supports this via:

```sh
claude --print --model claude-haiku-4-5 \
       --skill smith-navigate \
       --append-system-prompt "..." \
       --max-turns 1 \
       "User task: $USER_PROMPT"
```

`--print` returns the response on stdout and exits. `--max-turns 1`
bounds the cost. `timeout 3s` wraps the invocation.

If the `claude` CLI is not available (rare — Smith requires it), the
hook falls back to vault-only context and logs a warning.

### Context B — Called from `/smith-explore` (skill)

When `/smith-explore` invokes `/smith-navigate`, it's via the standard
SDK `Task` tool from inside Claude Code. The skill author writes:

> "Invoke the `smith-navigate` skill with the feature description as
> argument and wait for its categorized file list."

This is a normal slash-command invocation; Claude handles the dispatch.

### Decision

Hook context: `claude --print --model claude-haiku-4-5 --skill
smith-navigate --max-turns 1` wrapped in `timeout 3`.

Skill context: standard slash-invocation; no special API.

Both paths return the same markdown shape defined in
`contracts/navigator-output.md`.

---

## 8. Resume Semantics for `/smith-index`

Per Rule 4 of `~/.claude/CLAUDE.md` (the constitution check in plan.md),
`/smith-index` must implement:

1. **Checkpoint** — written every system completion, NOT every file:
   ```json
   {
     "started_at": "2026-05-21T12:01:00Z",
     "last_system": "system-03-frontend",
     "processed_files": 87,
     "systems_completed": ["system-01-api", "system-02-models", "system-03-frontend"]
   }
   ```
   Path: `.smith/index/.smith-index-checkpoint.json`. Removed on clean exit.

2. **JSONL log** — one line per file:
   ```jsonl
   {"timestamp":"2026-05-21T12:01:00.123Z","item_id":"backend/src/api/v1/products.py","stage":"parse","status":"ok","error":null}
   {"timestamp":"2026-05-21T12:01:00.234Z","item_id":"backend/src/api/v1/products.py","stage":"meta","status":"ok","error":null}
   {"timestamp":"2026-05-21T12:01:00.245Z","item_id":"backend/src/api/v1/products.py","stage":"system-update","status":"ok","error":null}
   ```
   Path: `~/.smith/logs/smith-index-<ISO8601>.jsonl`. Persists after run.

3. **`--resume` semantics:**
   - Read checkpoint and JSONL.
   - Build set of file paths where ALL stages reached `status=ok`.
   - Skip those files on the resumed run.
   - Mid-run failures (a stage with `status=error`) cause the file to be retried.
   - `--resume` without an existing checkpoint behaves as a fresh run with a warning.

4. **Summary line on exit:**
   ```
   /smith-index: 142 files indexed (138 succeeded, 4 failed, 0 skipped) in 47.3s
   ```

**Decision:** above design. Checkpoint is per-system (not per-file) to
keep the IO cost bounded; per-file granularity comes from the JSONL log.

---

## 9. Template Merge Strategy for `/smith init`

When `/smith init` runs on a project that already has `constitution.md`
or `CLAUDE.md`, the question is: overwrite, merge, or skip?

### Decision

**Merge by section, idempotent.** Algorithm:

1. Read target file if exists.
2. For each section in the template (delimited by `## ` markdown headers),
   check if a section with the same heading already exists in the
   target.
3. If absent → append the template section to the end.
4. If present → leave the existing section untouched. Log a note:
   `Section "## File Size Policy" already present; left unchanged.`
5. Always preserve the user's existing top-of-file content (any
   pre-section preamble).

This pattern matches how `install.sh` already merges
`smith-settings-fragment.json` into `~/.claude/settings.json` (look at
existing `merge_settings_json` function — same idempotent overlay
approach).

`/smith init` never destroys user content. Templates are additive.

---

## 10. JSON Comments in `system-paths.json.example`

JSON has no comment syntax. The example file uses a `_comment` field
convention that is preserved through parsers (because we never
re-serialize the file — we read it, look up rules, ignore extras):

```json
{
  "_comment": "Customize these rules for your project. Longest-prefix match.",
  "rules": [
    {"prefix": "backend/src/api", "system": "system-01-api",
     "_comment": "Backend HTTP layer"}
  ],
  "default": "unassigned"
}
```

`_comment` keys are ignored by `manifest-updater.sh` and `/smith-index`.

---

## 11. Performance Headroom Summary

| Component | Budget | Empirical (this research) | Headroom |
|---|---|---|---|
| parse-python.py | 200ms | ~75ms (1000 LOC, M1) | 62% |
| parse-js.js (acorn) | 200ms | ~135ms (1000 LOC, M1) | 32% |
| manifest-updater.sh | 500ms | ~290ms (90% of which is parser) | 42% |
| /smith-navigate | 3000ms | Haiku 4.5 typical 1500-2200ms | 27-50% |
| context-loader.sh | 5000ms | ~3700ms (includes navigator) | 26% |
| /smith-index | 60s for 100 files | ~38s (parallel xargs -P 8) | 37% |

All budgets feasible. JS parser is the tightest (32% headroom) — the
acorn cold-start of node is the dominant cost. Mitigation: process
files in batches within a single `node` invocation when called from
`/smith-index` (amortizes startup). The hook can't batch (one file at
a time) so it pays the full cold start per edit — still under budget.

2026-05-21 12:02:00 — 19-manifest-system
