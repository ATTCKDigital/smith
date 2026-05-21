# Contributing to Smith

Thank you for your interest in Smith! This document explains how to contribute
to the project effectively.

Smith is maintained by [ATTCK](https://attck.com) and released under the MIT
license. We welcome bug reports, feature requests, and ideas from everyone.
Pull requests are by invitation only (details below).

---

## Issues and Bug Reports

Anyone can open an issue. Good bug reports make fixes happen faster.

Please include:

- **Claude Code version** (`claude --version`)
- **Operating system** and version (e.g., macOS 15.3, Ubuntu 24.04)
- **Smith version** (check your installed skill files or `git log --oneline -1`)
- **Description** of the problem
- **Steps to reproduce** — the more specific, the better
- **Expected behavior** — what you thought would happen
- **Actual behavior** — what actually happened
- **Relevant logs or error output** — redact any credentials or personal information

If the issue is intermittent, note the frequency and any patterns you have
observed.

## Feature Requests

Feature requests are welcome as GitHub Issues. When describing a feature:

- **Focus on the use case**, not just the solution. Tell us what you are trying
  to accomplish and why the current behavior falls short.
- Describe the workflow or scenario where the feature would help.
- If you have a proposed approach, include it — but the use case matters more.
- Check existing issues first to avoid duplicates. Add a comment to an existing
  issue if your use case is related.

## Pull Requests — By Invitation

Pull requests are **by invitation only**. Here is how it works:

1. **Open an issue first.** Describe the bug fix, improvement, or new skill you
   have in mind.
2. **Discuss with maintainers.** We will evaluate the proposal and may ask
   clarifying questions.
3. **Receive an invitation.** If the change aligns with the project direction, a
   maintainer will invite you to submit a PR.
4. **Submit your PR.** Follow the guidelines below.

This process ensures that contributors do not invest time on changes that may
not be merged. It also keeps the project focused and maintainable.

### If You Are Invited to Submit a PR

1. **Fork the repository** and create a feature branch from `main`.
   Use a descriptive branch name (e.g., `feat/skill-name` or `fix/hook-issue`).

2. **Follow existing SKILL.md conventions.** Every skill file uses YAML
   frontmatter with the following fields:
   - `name` — short, lowercase, hyphenated
   - `description` — one-line summary
   - Any other fields used by existing skills (check a few for reference)

3. **Update CHANGELOG.md.** Add your change under the `[Unreleased]` section
   using the appropriate category (Added, Changed, Fixed, Removed).

4. **Test `install.sh` locally.** Run the installer on your machine and verify
   that your changes work end-to-end. Uninstall and reinstall to check for
   regressions.

5. **One skill per PR** unless the skills are tightly coupled and must ship
   together. Smaller PRs are easier to review and merge.

6. **Write a clear PR description.** Explain what the change does, why it is
   needed, and how you tested it. Reference the issue number.

---

## Coding Conventions

### Skills

- Skills are **Markdown files with YAML frontmatter**.
- Keep instructions clear and unambiguous. Claude Code interprets these
  literally.
- Use consistent formatting with existing skills.
- Do not assume a specific working directory structure beyond what Smith
  itself creates.

### Hooks

- Hooks are **POSIX-ish Bash scripts** (`#!/usr/bin/env bash`).
- They must run on macOS and common Linux distributions.
- Keep hooks focused — one responsibility per hook.
- Use `set -euo pipefail` at the top of each hook.

### General Rules

- **No hardcoded absolute paths.** Use `$HOME`, `$SMITH_DIR`, or other
  environment variables. Paths like `/Users/someone/...` must never appear.
- **No credentials or PII** in any file, ever. Not in examples, not in
  comments, not in test fixtures.
- **No unnecessary dependencies.** If a hook needs a tool, check for it and
  fail gracefully with a clear message.
- **Keep it simple.** Prefer clarity over cleverness.

---

## Development Setup

1. Clone your fork:
   ```bash
   git clone https://github.com/YOUR_USERNAME/smith.git
   cd smith
   ```

2. Run the installer to set up skills and hooks locally:
   ```bash
   ./install.sh
   ```

3. Make your changes and test them with Claude Code.

4. Before submitting, run a security scan:
   ```bash
   # Check for OS artifacts that shouldn't be committed
   find . -name ".DS_Store" -o -name "Thumbs.db" -o -name "*.swp"
   
   # Check for sensitive files
   find . -name ".env*" -o -name "*.pem" -o -name "*.key" -o -name "*credential*" -o -name "*secret*"
   
   # Scan for hardcoded secrets (review any matches manually)
   grep -rE "(api[_-]?key|secret[_-]?key|password|bearer|sk-|pk_live|sk_live)" --include="*.md" --include="*.sh" --include="*.json" . | grep -v "don't\|block\|guard\|protect\|expose\|leak"
   ```
   
   Remove any files or content flagged by these scans before proceeding.

5. Verify functionality:
   - The installer runs without errors
   - Your changes do not break existing skills or hooks
   - CHANGELOG.md is updated

---

## Vendored Dependencies

### `scripts/parsers/vendor/acorn.min.js`

The JS/TS/JSX/TSX parser depends on a single bundled, minified file at
`scripts/parsers/vendor/acorn.min.js`. This bundle includes:

- `acorn@8.x` — the upstream JavaScript parser
- `acorn-jsx` — JSX plugin
- `acorn-typescript` — TypeScript plugin

It is built+minified via `esbuild` into a single CommonJS file (~150KB) and
checked into the repo. Version is pinned in `scripts/parsers/vendor/VERSION`.

**Why vendored:** install-time determinism. Smith installs by copying files
from this repo into `~/.smith/scripts/` — there is no `npm install` step at
user-install time. Vendoring guarantees the parser works the moment `node`
is on PATH, regardless of what's in the user's `npm` cache or registry
availability. It also pins the exact parser version Smith was tested against,
so behavior is reproducible across machines.

**Marked as vendored in `.gitattributes`:**

```
scripts/parsers/vendor/acorn.min.js linguist-vendored=true
scripts/parsers/vendor/acorn.min.js linguist-generated=true
```

Keeps the file out of GitHub's per-language line-count statistics and out of
diff summaries by default.

**License:** acorn and its plugins are MIT-licensed. License text is preserved
in `scripts/parsers/vendor/README.md` (or `scripts/parsers/vendor/LICENSE` if
upstream included one in the bundle).

**Regen procedure (when upgrading acorn):**

```bash
# Run in a scratch directory — DO NOT pollute the smith-repo tree with node_modules
cd /tmp/build-acorn-bundle && \
  npm init -y && \
  npm install --no-save acorn@8 acorn-jsx acorn-typescript esbuild && \
  cat > entry.js << 'EOF'
const acorn = require('acorn');
const acornJsx = require('acorn-jsx');
const acornTypescript = require('acorn-typescript').default;
module.exports = { acorn, acornJsx, acornTypescript };
EOF
  npx esbuild entry.js \
    --bundle \
    --minify \
    --platform=node \
    --format=cjs \
    --target=node18 \
    --outfile=<absolute-path-to-smith-repo>/scripts/parsers/vendor/acorn.min.js
```

After regenerating:

1. Update `scripts/parsers/vendor/VERSION` with the new acorn version.
2. Re-run the parser fixture tests (`bash tests/parsers/test_parse_js.sh`).
3. Note any behavior changes in CHANGELOG.md under `### Changed`.

---

## Parser Development

Source-code parsers live in `scripts/parsers/`:

- `parse-python.py` — Python AST parser using stdlib `ast` (no third-party deps).
- `parse-js.js` — JS/TS/JSX/TSX parser using the vendored acorn bundle.
- `path-resolver.py` — heuristic path → system mapping (stdlib `json`/`os.path`).
- `parser-lib.sh` — bash helper that resolves which parser to invoke for a
  given file extension; respects per-project overrides.

### Contracts

All parsers emit JSON conforming to
`specs/19-manifest-system/contracts/parser-output.schema.json`. The shape is:

```jsonc
{
  "language": "python" | "javascript" | "typescript" | "jsx" | "tsx",
  "lines": <int>,
  "functions": [{ "name", "line", "params", "return_type", "docstring" }],
  "classes":   [{ "name", "line", "methods": [{ "name", "line" }] }],
  "imports":   [{ "module", "names", "line", "kind" }],
  "routes":    [{ "method", "path", "line", "function", "framework" }],
  "errors":    []  // populated on partial parse; never throws
}
```

### Hard rules

- **Performance budget:** <200ms p95 per file. Verify with
  `tests/parsers/fixtures/` files up to 2000 lines.
- **Never crashes.** Malformed input must return partial JSON with an
  `errors[]` entry. No uncaught exceptions, no non-zero exit on bad input.
- **No source modification.** Parsers are read-only.
- **Stdlib only for `parse-python.py`.** The Python parser must not require
  pip-installable dependencies.

### Test fixtures

- Python: `tests/parsers/fixtures/python/` — vanilla, async, classes,
  FastAPI/Flask routes, type hints, docstrings, empty, syntax errors.
- JS/TS: `tests/parsers/fixtures/js/` — ESM exports, default exports, React
  components, deduplicated imports, Express routes, TypeScript interfaces,
  malformed JSX, TSX components.

### Running parser tests

```bash
# Python parser
python3 tests/parsers/test_parse_python.py

# JS/TS parser (integration test — invokes node directly)
bash tests/parsers/test_parse_js.sh

# Contract validation (JSON Schema check across all fixtures)
python3 tests/contracts/test_parser_output_schema.py
```

### Per-project parser override

If a project ships `.smith/scripts/parse-python.py` (or `parse-js.js`),
`manifest-updater.sh` uses that instead of the global `~/.smith/scripts/`
copy. This lets a project fork parsing behavior — e.g. a project that uses an
unusual code generator and wants to filter out auto-generated functions —
without forking smith-repo. The override mechanism lives in
`scripts/parsers/parser-lib.sh::resolve_parser`.

---

## Hook Chain Ordering

Hook order matters for the PostToolUse `Write|Edit` chain. Smith's installer
guarantees the following invariant:

```
file-change-logger.sh  →  lint-on-save.sh  →  manifest-updater.sh
```

`manifest-updater.sh` MUST be LAST so it observes the final on-disk file
state after any lint reformatting. If you add a new PostToolUse hook that
should run before manifest update, register it earlier; if your hook should
react to the manifest update, switch it to a different event (e.g.
`SubagentStop`) — there is no "after manifest-updater" slot.

The ordering invariant is enforced by `tests/hooks/test_hook_chain_order.sh`.

---

## Communication

All project communication happens through **GitHub Issues**. This keeps
discussions searchable and linked to the relevant context.

For security issues, see [SECURITY.md](SECURITY.md) — do not use public issues
for vulnerability reports.

---

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md).
By participating, you agree to uphold its standards.

---

## License

By contributing to Smith, you agree that your contributions will be licensed
under the [MIT License](LICENSE) that covers the project.

---

Thank you for helping make Smith better.
