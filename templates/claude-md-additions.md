## Smith Context System

When the `context-loader.sh` UserPromptSubmit hook is active, Smith-aware
prompts (e.g. `/smith-bugfix`, `/smith-new`, or natural-language triggers
like "let's smith this") will arrive with an `additionalContext` block
already attached. The block contains:

- **Vault sections** — recent sessions, ledger, queue, bank, agents per
  the per-skill `context-manifest.json` config.
- **Manifest Navigator output** — `Must Read`, `Should Read`, and
  `Reference Only` file lists scoped to the task.

**Use the injected context first.** Read the Must Read files in their
entirety, focusing on the `[primary: <range>, <label>]` annotation. Treat
Should Read as supporting context. Reference Only files are for context,
not modification.

If the injection is absent (no Smith trigger detected) or carries the
"Manifest not initialized" sentinel, fall back to normal exploration:
grep, read by hypothesis, and consider running `/smith-index` to enable
structured retrieval.

## File Size Awareness

Before reading any source file over 300 lines, check its `.meta` sidecar
under `.smith/index/files/`. The sidecar lists exports, classes,
functions, and routes — enough to locate your target without a full read.
Reserve full reads of large files for the cases where the navigator's
primary annotation points there.

## MCP-First Browser Verification

When an agent or skill would otherwise drive an unauthenticated headless
browser for E2E/UX/SEO verification, prefer the operator's own
already-logged-in browser via Playwright MCP bridge mode — closing
auth-gated staging/production screens without a throwaway headed-login
window. This only applies when every condition below holds; otherwise
fall back silently to the pre-existing (unauthenticated) approach.

**Detecting tool presence.** Check whether `mcp__playwright__*` tools
(e.g. `mcp__playwright__browser_navigate`) are present in the current
tool list. Absence means Playwright MCP isn't registered for this
session at all — fall back immediately (see "Fallback idiom" below).

**`mcp_mode` — always explicit config, never inferred.** A bridge-mode
and a sandbox-mode Playwright MCP server expose the **identical**
`mcp__playwright__*` tool namespace, so tool presence alone can never
tell you which one you have. The project config key
`browser_verification.mcp_mode` (in `.smith/config.json`) resolves this
explicitly:

| Value | Meaning |
|---|---|
| `extension` | Bridge mode — drives the operator's own already-logged-in Chrome tab. |
| `sandbox` | Isolated, unauthenticated browser context. |
| `off` | Do not attempt MCP-driven browser verification at all. |

Missing/absent `mcp_mode` is treated as `off`. Never infer `mcp_mode`
from whether the tools are present, from tool names, or from any other
runtime signal.

**Fallback idiom (silent-skip).** Mirrors the existing "check, then skip
silently" precedent used for optional Ledger context: check whether the
condition holds; if not, skip without erroring, warning, or blocking the
calling workflow. No new prompt, log line, or failure is surfaced solely
because the MCP-first path wasn't attempted.

**Non-interactive / scheduler hard-skip.** Any non-interactive or
scheduler-driven invocation (`claude -p`, an autonomous scheduler
worktree run) MUST hard-skip the MCP-first path unconditionally, even
when tools are present and `mcp_mode` resolves to `extension` — a bridge
connection can require a human to approve a browser tab, and a
non-interactive session has nobody present to do that. Use the fallback
without attempting a bridge connection at all.

**Staging/production URL table.** Name every environment explicitly —
never infer staging/production via hostname heuristics. Schema:

| Name | URL | Label |
|---|---|---|
| staging | `https://staging.example.com` | staging |
| production | `https://app.example.com` | production |

This table is the **human-readable view** of the same data. The
**machine-readable source of truth** — the one `security-guard-mcp-browser.sh`
actually reads to classify a navigation target and gate interaction
tools — is `.smith/security-config.json`'s `browser_verification.urls`
key (`urls.staging[]` / `urls.production[]`, each entry
`{name, url, label}`), seeded with empty `staging`/`production` lists by
`/smith` init and `/smith-update`. This CLAUDE.md table is not itself
read by any hook; keep it in sync with the config by hand.

**Decision chain.** Every MCP-first browser-verification attempt, in
every consuming surface (agents, smith-audit sub-audits, generated
CLAUDE.md guidance), evaluates the same chain:

```
IF   mcp__playwright__* tools are present in the current tool list
AND  the resolved browser_verification.mcp_mode is "extension"
AND  the current session is interactive
THEN attempt to drive the operator's authenticated browser via those
     tools, subject to security-guard-mcp-browser.sh's read-only /
     interaction / production-confirm-gate policy
ELSE (any one condition false) fall back silently to the exact
     pre-existing (unauthenticated) behavior — no error, no warning,
     no extra prompt
```

**Fast-fail on a stalled bridge connect.** If the bridge connection does
not succeed immediately — extension not connected, no approved tab
available — treat that single call as failed and fall back at once.
Never wait, poll, or retry for the connection to come up; a hang here
would block the calling workflow on a human who may not be present.
