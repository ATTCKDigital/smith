# Research: MCP-First Browser Verification with Safety Guard

Each item below was resolved by reading the actual file cited, not by
assumption. File:line references are against the worktree at
`/tmp/smith-mcp-browser-access` (branch `53-mcp-browser-access`).

---

## 1. Guard hook skeleton (from `hooks/security-guard-bash.sh`)

**Decision:** `hooks/security-guard-mcp-browser.sh` follows the exact
five-part skeleton both existing `PreToolUse` guards use:

1. `set -uo pipefail`; `INPUT=$(cat)` — read the whole stdin payload once.
2. Extract fields via a `python3 -c` heredoc-style one-liner piped the
   input, e.g. (`hooks/security-guard-bash.sh:16-21`):
   ```bash
   COMMAND=$(echo "$INPUT" | python3 -c "
   import sys, json
   data = json.load(sys.stdin)
   ti = data.get('tool_input', {})
   print(ti.get('command', ''))
   " 2>/dev/null || echo "")
   ```
   Every extraction is defensive: `2>/dev/null || echo ""` so malformed
   JSON never crashes the hook. `workflow-gate.sh:31-38` shows the same
   idiom used for `tool_name` at the top level (`data.get('tool_name', '')`).
   The new guard needs **both**: `tool_name` (to route read-only vs.
   interaction classification) and `tool_input` (to pull the element/URL
   context for `browser_navigate`).
3. Load optional JSON config with one `python3 -c "import json; d=json.load(open('$CONFIG_FILE')); print(...)"` call per field, guarded by
   `if [ -f "$CONFIG_FILE" ]` (`security-guard-bash.sh:36-40`).
4. `deny()` / `warn()` / `approve()` helper functions that both print a
   `hookSpecificOutput` JSON block to stdout and `exit` with the matching
   code — `deny` exits 2, `warn`/`approve` exit 0
   (`security-guard-bash.sh:57-110`).
5. Fall through to `exit 0` (bare pass-through to normal permission flow)
   when nothing matched (`security-guard-bash.sh:306`).

**Alternatives considered:** a Python-only hook (no bash wrapper). Rejected
— every existing hook is bash-with-embedded-python3, and `NFR-4` explicitly
scopes acceptable overhead to "the `python3` JSON parsing already used by
the sibling guards," i.e. it assumes the same bash+python3 shape.

**Deny/warn response format (verbatim, reused as-is):**
```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "SMITH SECURITY: <reason>"
  }
}
```
exit 2 for deny; the `warn_only_mode` branch instead emits an
`additionalContext` field and exits 0 (`security-guard-bash.sh:61-96`).

---

## 2. Silent-no-op idiom (from `hooks/user-prompt-logger.sh`)

**Decision:** every optional-dependency check in the new guard (vault
absent, `.smith/security-config.json` absent, `.smith/config.json`
absent) uses the same short-circuit chain `user-prompt-logger.sh:32-35`
uses:
```bash
[ -f "$CURRENT_SESSION_FILE" ] || exit 0
SESSION_FILE=$(cat "$CURRENT_SESSION_FILE" 2>/dev/null || echo "")
[ -n "$SESSION_FILE" ] && [ -f "$SESSION_FILE" ] || exit 0
```
i.e. check-then-exit-0, never `set -e`-driven failure, never a printed
error. This directly satisfies NFR-1 ("absence of `.smith/security-config.json`... MUST always resolve to a silent no-op"). No new idiom needed —
this one already exists twice in the codebase (`security-guard-bash.sh`'s
`[ -f "$CONFIG_FILE" ]` guard is the same pattern applied to config
instead of vault state).

---

## 3. Settings-fragment matcher syntax — concrete risk found

**Read:** `settings/smith-settings-fragment.json:64-85`, `docs/hooks.md`
Hook Summary table, `scripts/dedupe-settings.sh:38-49`.

**Finding (verbatim matcher values currently in use):**
| Hook | Matcher string, verbatim |
|---|---|
| security-guard-bash | `"Bash"` |
| security-guard-files | `"Write\|Edit\|NotebookEdit"` |
| task-router | `"Task"` |
| everything else | `"*"` |

Every non-wildcard matcher in this repo is either a **bare literal tool
name** or a **pipe-alternated list of bare literal names**. There is
**zero precedent anywhere in the repo** for a wildcard/prefix matcher —
no `.*`, no shell glob, no regex anchor of any kind is used today.

**Concrete risk this surfaces:** FR-1 says the new hook must match tool
names "`mcp__playwright__*`" — but that is shell-glob notation, not what
the `matcher` field actually is. Claude Code's hook `matcher` is matched
as a **regex** against the tool name (unanchored substring, same as how
`"Write|Edit|NotebookEdit"` already works as unanchored alternation
against exact tool-name strings). Taken as regex, a literal `*` means
"zero or more of the preceding character" — so the string
`mcp__playwright__*` as a regex only matches `mcp__playwright_` repeated
zero-or-more trailing underscores, and **would never match**
`mcp__playwright__browser_click` or any real tool name. Using FR-1's
notation verbatim in `settings/smith-settings-fragment.json` would ship a
guard that silently never fires — the exact opposite of closing the
blocking finding.

**Decision:** register the matcher as the bare substring
`"mcp__playwright__"` (no regex metacharacters at all), matching the
repo's existing zero-metacharacter convention and relying on the same
unanchored-substring semantics that already makes `"Bash"` and
`"Write|Edit|NotebookEdit"` work. `"mcp__playwright__.*"` (proper regex
wildcard) is an equally-correct alternative if an anchored/explicit form
is preferred; either is called out in `plan.md` — **not** the literal
`mcp__playwright__*` from the spec's illustrative prose.

**Dedupe compatibility:** `dedupe-settings.sh:38-49`'s uniqueness key is
`.matcher + "|" + (.hooks | tostring)` — a new matcher string is
automatically treated as a new, unique entry with zero code changes to
`dedupe-settings.sh` or `scripts/install.sh` (same conclusion the
`stamp-response.sh` PR already reached per `CHANGELOG.md`'s "Wiring"
note).

---

## 4. Agent frontmatter + E2E prose slot points

**Read:** `skills/smith/agents/product-manager.md` (full),
`senior-qa.md:1-110`, `staff-frontend.md:1-40`, `staff-fullstack.md`
(grep pass).

All four already grant the full `mcp__playwright__*` tool set individually
by name in their `tools:` frontmatter line (line 4 in each file) — FR-15
does **not** require touching `tools:` (the grants already exist; the
feature only changes when/how those tools are used, not whether they're
granted). Confirmed no agent uses a tool-name wildcard in `tools:` either
— another data point that this repo's tooling doesn't support wildcards
in tool-reference contexts generically.

**Slot points found:**
- `product-manager.md:60-81` — `## Test URLs` table (lines 60-68) and
  `## E2E Testing Approach` (70-81) are the two sections FR-16 names
  explicitly. The `## E2E Testing Approach` numbered list (step 2:
  "Navigate the running `app` using Playwright") is where the MCP-first
  conditional gets inserted as a new step 2, renumbering the rest.
- `senior-qa.md:47-97` — `## Testing Strategy` → `### E2E Functional
  Testing (`app`)` (49-54) is the FR-15 slot; `## Test URLs` (79-87) is
  the same table shape as product-manager's, duplicated verbatim (not
  shared/included — the repo has no markdown-include mechanism).
- `staff-frontend.md:24-29` — `## Key Responsibilities` item 4
  ("Testing: ... E2E validation with Playwright MCP") is the slot; the
  file has no dedicated E2E section, so the contract sentence attaches
  to this bullet.
- `staff-fullstack.md` — `## Development Discipline` → `### Defect
  Handling` step 1 ("Write a failing test ... at the appropriate layer —
  unit, integration, or E2E") is the closest existing hook; same
  bullet-attachment pattern as staff-frontend.

**Decision:** rather than a large new section per agent, attach a short
"MCP-First Browser Verification" paragraph (2-4 sentences, referencing
`templates/claude-md-additions.md`'s section instead of restating it) at
each identified slot. Avoids four divergent copies of the same fallback
logic prose (a duplication smell the `/clean-code` rubric flags).

---

## 5. `templates/claude-md-additions.md` structure + migrate-templates detection

**Read:** `templates/claude-md-additions.md` (full, 29 lines — only 2
top-level `##` headers: `## Smith Context System`, `## File Size
Awareness`), `skills/smith-index/SKILL.md:315-329`.

**Finding:** the migrate-templates detection list is **hard-coded** as a
4-item bullet list inside `skills/smith-index/SKILL.md` step 1
(lines 321-325):
```
- `## File Size Policy`
- `## Project Manifest`
- `## Smith Context System`
- `## File Size Awareness`
```
(First two come from `templates/constitution-additions.md`, the latter
two from `templates/claude-md-additions.md` — confirmed by grepping both
headers exist only in `claude-md-additions.md`.) This is a flat text
list, not a generated/derived one — adding the new header means literally
adding a fifth bullet line to this list in `skills/smith-index/SKILL.md`,
**and** appending the new `## MCP-First Browser Verification` top-level
section to `templates/claude-md-additions.md` itself. Both edits are
required; either alone leaves migrate-templates unable to detect/append
the new section (FR-14).

**Backup mechanism (reused, not reinvented):** step 2 of the same section
("If any are missing, write a `.bak.<ISO8601>` backup of the original")
is a single backup taken once per file per run, shared across however
many of the 4 (soon 5) headers are missing — NFR-6 requires the new
header ride this same shared backup rather than adding a second backup
mechanism. No code change needed here beyond the count growing from 4 to
5 candidates checked against the one backup step.

---

## 6. `skills/smith-audit/SKILL.md` UX/SEO sub-audit slot

**Read:** `skills/smith-audit/SKILL.md:105-119`.

Sub-Audit Orchestration is a flat numbered list (11 items); UX is item 6
(`smith-audit ux`, "Playwright-driven UI testing, latency,
responsiveness"), SEO is item 10 (`smith-audit seo`, "Playwright-driven
technical SEO audit via sitemap crawling"). FR-17's edit is a short
clause appended to each of these two list-item descriptions (not a new
subsection) — e.g. "...responsiveness (MCP-first with fallback per
`templates/claude-md-additions.md`)". Minimal, single-line diffs.

---

## 7. `skills/smith/SKILL.md` Q19 / `## E2E Testing with Playwright MCP`

**Read:** `skills/smith/SKILL.md:418-476` (grep-located via `Playwright
MCP`).

Line 439-441:
```
## E2E Testing with Playwright MCP
[Generated only if Playwright MCP selected in Q19]
```
This is a **template placeholder inside the CLAUDE.md-generation
template**, not prose Claude executes directly — `/smith` (the `smith`
skill) fills this block in when scaffolding a new project's `CLAUDE.md`.
FR-18 requires the generated content behind this placeholder to either
inline the MCP-First convention or explicitly reference
`templates/claude-md-additions.md`'s section. Given the file already
documents a strong anti-duplication rule two paragraphs down (lines
448-456, the "Do NOT add a `## Recent Changes`... keep CLAUDE.md small"
rule), the **reference-not-restate** option is the one consistent with
this file's own stated philosophy — resolved in `data-model.md`/`plan.md`
as "reference `templates/claude-md-additions.md`'s section by name,
do not duplicate its body into the Q19 generation block."

---

## 8. `docs/security-model.md` + `docs/hooks.md` registration/doc pattern

**Read:** both files in full.

`docs/security-model.md`'s "What to Audit Before Enabling" (lines 90-98)
is a **numbered 3-item list**, each item bolding a file path then a
one-sentence description of what to review in it. FR-7 requires this
list grow to 4 items — append, using the identical
`**`~/.claude/hooks/<file>`** -- <what to review>` shape as items 1-2.

`docs/hooks.md` has two things per hook: (a) one row in the "Hook
Summary" table (`Hook | Event | Matcher | Purpose`, lines 9-23), and (b) a
"### <hookname>.sh" subsection under "## Detailed Reference" with fixed
sub-bullets: **Event**, **Matcher**, **What it does**, **Files touched**,
**To disable** (see `security-guard-bash.sh` doc block, lines 92-98, as
the closest sibling — same event, same "no files touched, inspection
only" pattern). FR-8's new subsection mirrors that block exactly,
substituting the new guard's matcher string and interaction/production
policy description in "What it does," and reusing "Files touched: None
(inspection only)" since the guard purely inspects/decides (though it
does write a new small state-cache file — see §11 — that field's wording
needs updating to name that file, since "None" would be inaccurate).

---

## 9. `tests/hooks/` harness pattern

**Read:** `tests/hooks/test_workflow_gate_exemption.sh` in full (193
lines).

Reusable harness shape:
- Resolve `$HERE`/`$REPO` via `cd "$(dirname "${BASH_SOURCE[0]}")"`.
- A `gate_verdict()` (rename `guard_verdict()`) helper that pipes a JSON
  payload string into the hook via stdin with `env
  CLAUDE_PROJECT_DIR="$repo" bash "$GATE"`, then greps stdout for
  `"permissionDecision":\s*"deny"` (both a tight and a loose quoting
  variant are grepped for, lines 34-37) to normalize to `allow`/`deny`.
- A `setup_repo()` helper that `mktemp -d`, `git init --quiet`, sets a
  throwaway git identity, commits an empty root, and creates whatever
  `.smith/...` scaffolding the test needs (line 57-70 makes only
  `.smith/`; our tests additionally need `.smith/vault/` +
  `.smith/security-config.json` fixtures per case).
- `assert_verdict(name, expected, actual)` incrementing `PASS`/`FAIL`
  counters and collecting failed names.
- A closing summary block: total/passed/failed counts, non-zero exit if
  any failed (lines 184-192).

**Decision:** `tests/hooks/test_security_guard_mcp_browser.sh` reuses this
exact structure verbatim (rename `GATE` → `GUARD`, `gate_verdict` →
`guard_verdict`), adding cases for: read-only tool always-allow (any
mode/target incl. production), interaction tool allowed on
non-production, interaction tool denied on production without
confirmation, interaction tool allowed on production **with** a
confirmation fixture present, `warn_only_mode` behavior on a
non-production interaction warning path, absent-config no-op, malformed
JSON no-op, and the bash-vs-zsh identical-output check required by SC-4
(run the same payload through both `bash "$GUARD"` and `zsh "$GUARD"` and
diff the JSON).

---

## 10. Config-file split — pre-existing repo inconsistency found

**Read:** `templates/config.default.json` (full), `hooks/session-start-logger.sh:19-34`, `hooks/security-guard-bash.sh:30`, `hooks/security-guard-files.sh:30`.

**Finding:** two *different* files exist in this area and they are **not
the same file**:
- `templates/config.default.json` is seeded by `session-start-logger.sh`
  into **`.smith/config.json`**, and its `security` key already contains
  `allowed_commands`, `allowed_files`, `production_domains`,
  `warn_only_mode`.
- `security-guard-bash.sh`/`security-guard-files.sh` read those same
  field names, but from **`.smith/security-config.json`** — a
  completely different path that is never seeded, has no template, and
  has no example anywhere in this repo (`find -iname security-config*`
  returns nothing but the two guard scripts referencing it).

So today, a project's seeded `.smith/config.json` "security" section is
inert — the guards never read it. This is a pre-existing gap, not
introduced by this feature, and out of scope to fix here. FR-6 tells the
new guard to match "the existing guards' optional-config-load pattern" —
which means the new guard should also read `.smith/security-config.json`
(for consistency with its two siblings), **not** `.smith/config.json`,
even though the latter is the one that's actually seeded. This
inconsistency is called out explicitly as a spec-plan tension (see final
report) rather than silently perpetuated without comment.

---

## 11. "Current navigation target" and confirmation-record state — new mechanism required

No existing hook needs to remember anything *across* PreToolUse
invocations — every existing guard is stateless per-call (grep confirms
no hook reads a `session_id` field from the payload at all;
`security-guard-bash.sh` only ever reads `.current-session` to get a
*log destination*, not a state key). This feature is the first guard that
structurally needs cross-call memory:

- **Interaction tools carry no URL.** `browser_click`/`browser_type`/etc.
  operate on element refs from the last `browser_snapshot`, not a URL —
  so the guard cannot classify "production-labeled target" from the
  interaction call's own `tool_input`. It must already know what page is
  loaded.
- **`browser_navigate`'s `tool_input.url` is the only point the target is
  ever named.** The guard must capture it there, as a side effect of
  allowing that (read-only) call, and persist it for later interaction
  calls to check.
- **"recorded for that target/session" (FR-4) needs a durable record**,
  written only after a human confirms — the PreToolUse hook itself cannot
  prompt a human (see §12).

**Decision:** follow the existing **singleton current-state file**
convention already used for sessions (`security-guard-bash.sh:29`:
`CURRENT_SESSION_FILE="$VAULT_DIR/.current-session"` — one pointer file,
not a session-id-keyed map, because Smith's existing model is
"one active session per project worktree," never concurrent multi-session
state in a single vault). Add two sibling singleton files under
`.smith/vault/`:
- `.smith/vault/.mcp-browser-target` — last-navigated URL + resolved
  classification (`staging`/`production`/`unclassified`), overwritten on
  every allowed `browser_navigate` call.
- `.smith/vault/.mcp-browser-confirmed` — present only when a human has
  confirmed interaction against the *current* target; content is the
  confirmed target string, so a later navigate to a *different* target
  invalidates the earlier confirmation implicitly (the guard compares
  current target to the confirmed-file's content, not just presence).

**Alternatives considered:** (a) a session-id-keyed JSON map — rejected,
no existing hook has ever needed multi-session state and Smith's `.current-session` precedent is explicitly singleton; (b) encoding target state
into `.smith/security-config.json` itself — rejected, that file is
operator-authored policy, not hook-written runtime state, and writing to
it would conflate config with cache. Full schema in `data-model.md`.

---

## 12. Confirmation-gate mechanism — hooks cannot prompt

Confirmed architecturally (not just by convention): a `PreToolUse` hook
is a synchronous bash process fed one JSON payload on stdin and must
finish by printing a JSON decision and exiting — there is no channel back
to pause and collect a human's typed answer mid-hook. This matches the
spec's own framing (US-7/US-8 describe confirmation as something that
must already be "recorded" *before* the interaction call happens, not
elicited by the guard in the moment).

**Decision:** the guard's deny path for FR-4 is a **deny-with-instructions**
contract: on the first interaction-tool attempt against a
production-labeled target with no matching `.mcp-browser-confirmed`
record, `permissionDecisionReason` explicitly tells the agent to stop and
ask the human, in the conversation, for explicit confirmation before
retrying — mirroring how `create-active-workflow.sh` is "the SOLE
auditable entrypoint" for a different kind of gated state
(`CHANGELOG.md`'s workflow-gate-bootstrap entry). Once the human answers
affirmatively in chat, the agent (not the guard) writes the confirmation
record — a single, narrow, auditable write, analogous to
`create-active-workflow.sh`'s role, not a new interactive protocol.
Exact deny-message wording is in `data-model.md`'s "guard deny-message
contract" section.

---

## 13. `browser_evaluate` classification gap

The Overview's "Read-only tools" bullet includes "calls to
`browser_evaluate` whose JavaScript only reads page state" — but the
"Interaction tools" bullet list (`browser_click`, `browser_type`,
`browser_fill_form`, `browser_select_option`, `browser_press_key`,
`browser_drag`, `browser_hover`) never mentions `browser_evaluate` at
all. A mutating `browser_evaluate` call (e.g. `document.querySelector('form').submit()` or a `localStorage`/DOM write) is therefore **named by
neither list** — FR-2 (read-only always passes) and FR-3/FR-4
(interaction tools gated) both fail to cover it by their literal text.

**Decision (heuristic, documented as such):** the guard treats
`browser_evaluate` as interaction-class (subject to FR-3/FR-4 gating) by
default, and only classifies it read-only when its `tool_input.function`
source matches a narrow read-only allowlist of patterns (e.g. begins with
`return`/`() => (` and contains no assignment operators, no
`.click(`/`.submit(`/`.value =`/`fetch(`/`XMLHttpRequest`/`localStorage.set`/`sessionStorage.set` tokens). This defaults to the safer branch
(gated) rather than the permissive one on any ambiguous script. This is
flagged as a genuine spec gap, not a confident spec-derived rule — see
final report's spec-plan tensions.
