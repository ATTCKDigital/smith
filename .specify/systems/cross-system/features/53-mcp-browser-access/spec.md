---
feature: 53-mcp-browser-access
primary_system: cross-system
also_affects: []
branch: 53-mcp-browser-access
created: 2026-09-12
status: in-progress
answers_applied: 2026-09-13
---

# MCP-First Browser Verification with Safety Guard

## Overview

Playwright MCP can run in two modes that expose the **identical**
`mcp__playwright__*` tool namespace: `--extension` (bridge) mode, which drives
a tab in the operator's own already-logged-in Chrome, and sandbox mode, which
drives an isolated, unauthenticated browser context. Smith's agents and
skills already receive Playwright MCP tools (via `tools:` grants in agent
frontmatter), but nothing in Smith today distinguishes which mode is active,
and nothing gates what those tools are allowed to do once the target is a
staging or production environment.

This feature makes Smith **mode-aware**: when the user's registered
Playwright MCP server is in bridge mode and the session is interactive,
agent-driven browser verification (E2E testing, UX/SEO audits, CLAUDE.md
generation guidance) can drive the operator's authenticated browser instead
of an unauthenticated one — closing auth-gated staging/production screens
without a throwaway headed-login window. In every other condition (tools
absent, sandbox mode, non-interactive/scheduler context, or a bridge connect
that doesn't succeed immediately) it falls back, silently and without
hanging, to exactly the behavior Smith has today. Alongside the new
capability, this feature closes a standing safety gap: MCP browser
interaction tools currently pass through Claude Code with no `PreToolUse`
guard at all, unlike `Bash` (`security-guard-bash.sh`) and
`Write`/`Edit`/`NotebookEdit` (`security-guard-files.sh`).

**Terminology used throughout this spec:**
- **Read-only tools** — `mcp__playwright__browser_navigate`, `browser_snapshot`,
  `browser_take_screenshot`, `browser_console_messages`,
  `browser_network_requests`, `browser_wait_for`, `browser_tabs`.
- **Interaction tools** — `browser_click`, `browser_type`, `browser_fill_form`,
  `browser_select_option`, `browser_press_key`, `browser_drag`, `browser_hover`,
  and `browser_evaluate` (always interaction-class regardless of what its
  JavaScript does — resolved per `questions.md` Q4: a security hook must not
  parse arbitrary JS to infer read-vs-mutate intent).
- **`mcp_mode`** — the project-declared value of
  `browser_verification.mcp_mode`: `extension` (bridge mode, operator's real
  browser), `sandbox` (isolated unauthenticated browser), or `off`.
- **Production-labeled target** — a URL/environment listed as production in
  the staging/production URL table (see FR-13) or equivalent project config.

## Problem Statement

Smith verifies screens on staging, production, and other auth-gated apps
using Playwright MCP browser tools. Today this either runs unauthenticated
(the agent never gets past the login screen) or requires a headed browser
window the operator must log into by hand — a window that Claude Code closes
before the operator finishes, because nothing in Smith knows to wait for or
reuse the operator's already-authenticated session. Separately, the user now
has Playwright MCP registered at user scope in `--extension` (bridge) mode,
with the bridge browser extension installed in Chrome, which makes driving
the operator's real, logged-in browser session possible for the first time —
but only if Smith can (a) tell, explicitly, whether the registered server is
in bridge mode or sandbox mode (the tool names alone cannot say), (b) never
attempt a bridge connection in a context where nobody can approve a browser
tab (a non-interactive scheduler run), and (c) never let an agent perform a
mutating action against a production target without a human saying so.

An exploration pass ahead of this feature surfaced a **blocking** finding
that must be resolved regardless of the MCP-first capability: Smith ships
`PreToolUse` security guards for `Bash` and for
`Write`/`Edit`/`NotebookEdit`, but has none for `mcp__playwright__*` tools.
Any agent holding a Playwright MCP grant (four bundled agents already do) can
today click, type, and submit forms against any target, staging or
production, with zero guard-hook oversight. This feature cannot ship the new
capability without closing that gap first.

## User Scenarios

### US-1 — Authenticated staging verification via bridge mode (primary flow)
```gherkin
Given the user's Playwright MCP server is registered in --extension (bridge)
    mode, the bridge extension is installed and connected in Chrome
Given the current project's browser_verification.mcp_mode is "extension"
Given the current Claude Code session is interactive
When an agent (e.g. senior-qa) is asked to verify an auth-gated staging screen
Then the agent drives the operator's already-logged-in Chrome tab via the
    mcp__playwright__* tools
And it reaches the auth-gated screen with zero manual re-login
And any interaction tool it uses against the staging target is evaluated by
    the safety guard before executing
```

### US-2 — Fallback: tools absent
```gherkin
Given the current session has no mcp__playwright__* tools available
When an agent that would otherwise attempt MCP-first browser verification runs
Then it silently falls back to its pre-existing E2E/verification approach
And no error, warning, or extra prompt is surfaced solely due to the absence
    of the tools
```

### US-3 — Fallback: sandbox mode
```gherkin
Given mcp__playwright__* tools ARE present in the session
Given the project's browser_verification.mcp_mode is "sandbox"
When an agent attempts browser verification
Then it does NOT treat the session as authenticated-bridge-capable
And it falls back to its pre-existing (unauthenticated) verification behavior,
    identical to how it behaved before this feature existed
```

### US-4 — Hard-skip in non-interactive/scheduler context
```gherkin
Given a run is invoked non-interactively (e.g. `claude -p`, or the Smith
    scheduler's autonomous worktree run)
Given mcp_mode resolves to "extension" and tools are present
When browser verification would otherwise attempt a bridge connection
Then the fallback path is used unconditionally, without attempting the
    bridge connection at all
And the run never pauses or hangs waiting for a human to approve a browser
    tab that no one is present to approve
```

### US-5 — Fast-fail on a bridge connect that doesn't succeed immediately
```gherkin
Given mcp_mode is "extension", tools are present, and the session is
    interactive
When the agent attempts to use the bridge-mode browser and the connection
    does not succeed immediately (extension not connected, tab not
    available)
Then the attempt is treated as failed for this call
And the agent falls back silently to current behavior rather than waiting or
    retrying indefinitely
```

### US-6 — Read-only tools always pass
```gherkin
Given any mcp_mode and any target, including a production-labeled one
When an agent calls a read-only tool (navigate, snapshot, screenshot,
    console_messages, network_requests, wait_for, tabs)
Then the safety guard allows the call without requiring confirmation
```

### US-7 — Interaction tool blocked on production without confirmation
```gherkin
Given the current navigation target matches an entry labeled "production" in
    the staging/production URL table
When an agent calls any interaction tool (click, type, fill_form,
    select_option, press_key, drag, hover) without a prior recorded human
    confirmation for that target/session
Then the safety guard denies the call
And the denial reason names the production target and states that explicit
    confirmation is required before any interaction tool may run against it
```

### US-8 — Interaction tool allowed on production after explicit confirmation
```gherkin
Given the same production-labeled target as US-7
Given the human has explicitly confirmed interaction is authorized for this
    target/session
When the agent calls an interaction tool
Then the safety guard allows the call
```

### US-9 — Convention migrates into consumer projects idempotently
```gherkin
Given a consumer project's CLAUDE.md predates this feature
When the operator runs /smith-index --migrate-templates
Then the "MCP-First Browser Verification" section is appended from
    templates/claude-md-additions.md, with a backup taken first
When /smith-index --migrate-templates is run again afterward
Then the section is detected as already present and nothing is appended or
    duplicated
```

## Functional Requirements

### Safety guard hook (closes the blocking exploration finding)

- **FR-1**: The system MUST add a new `PreToolUse` hook,
  `hooks/security-guard-mcp-browser.sh`, matching tool names
  `mcp__playwright__*`.
- **FR-2**: The guard MUST allow all read-only tools (as defined in
  Overview) to pass through without requiring confirmation, on any target
  including production.
- **FR-3**: The guard MUST gate all interaction tools (as defined in
  Overview) by policy before they execute, following the existing guard
  convention: deny-by-default reasoning surfaced via
  `permissionDecisionReason`, with an optional project `warn_only_mode`
  config respected the same way `security-guard-bash.sh` and
  `security-guard-files.sh` already do — downgrading a denial to a
  warning — for every guard denial **except** the production
  confirm-gate denial defined in FR-4, which `warn_only_mode` MUST NOT
  downgrade or bypass under any configuration (resolved per
  `questions.md` Q1: warn-only mode is for tuning noise, not for
  disarming the one gate protecting real-cookie destructive actions).
- **FR-4**: The guard MUST deny any interaction tool call whose current
  navigation target is a production-labeled target (FR-13) unless an
  explicit human confirmation has already been recorded for that
  target/session — no interaction tool may execute against a
  production-labeled target on the strength of an agent's own judgment
  alone. This denial is non-bypassable: it is the sole exception to
  FR-3's `warn_only_mode` downgrade behavior and MUST fire regardless of
  `warn_only_mode`'s value (Q1).
- **FR-5**: The guard MUST be registered in
  `settings/smith-settings-fragment.json` under `PreToolUse`, alongside the
  existing `security-guard-bash.sh` (matcher `Bash`) and
  `security-guard-files.sh` (matcher `Write|Edit|NotebookEdit`) entries,
  closing the gap in which `mcp__playwright__*` tool calls currently pass
  through with no `PreToolUse` guard of any kind. This requirement directly
  resolves the exploration's BLOCKING finding.
- **FR-6**: The guard MUST log every block/warn decision to the active
  vault session log when one exists, and MUST no-op (allow the call through,
  never error, never hang) when the vault or its optional
  `.smith/security-config.json` is absent — matching the existing guards'
  optional-config-load pattern.
- **FR-7**: `docs/security-model.md`'s "What to Audit Before Enabling" list
  MUST gain a fourth item covering
  `~/.claude/hooks/security-guard-mcp-browser.sh` (interaction-tool policy
  and the production-confirmation requirement).
- **FR-8**: `docs/hooks.md` MUST gain a table row and a "Detailed Reference"
  subsection for `security-guard-mcp-browser.sh`, in the same format used
  for the existing ten documented hooks.
- **FR-21** *(added — resolved per `questions.md` Q5)*: The system MUST
  support a project config key `browser_verification.allow_interactions`
  (boolean, default `true`) in `.smith/security-config.json`. When
  `false`, the guard MUST deny every interaction tool call (as defined in
  Overview) regardless of target classification — staging included —
  until an operator sets it back to `true`. When `true` (the default),
  interaction tools are governed solely by the FR-2..FR-4/FR-13 decision
  table; this switch never affects the FR-4 production confirm-gate's
  own behavior when it is `true`.

### Shared convention (`templates/claude-md-additions.md`)

- **FR-9**: `templates/claude-md-additions.md` MUST gain a new top-level
  section titled "MCP-First Browser Verification" that documents: (a) how a
  skill/agent detects at runtime whether `mcp__playwright__*` tools are
  present in the current tool list; (b) the required project config key
  `browser_verification.mcp_mode` with allowed values
  `extension | sandbox | off`; (c) the silent-skip fallback idiom (FR-11);
  (d) the non-interactive hard-skip rule (FR-12); (e) the staging/production
  URL table schema (FR-13).
- **FR-10**: `mcp_mode` MUST always be read from explicit project
  configuration and MUST NOT be inferred from tool presence or any other
  runtime signal, because a bridge-mode and a sandbox-mode Playwright MCP
  server expose the identical `mcp__playwright__*` tool namespace and are
  otherwise indistinguishable to the calling agent.
- **FR-11**: The documented fallback idiom MUST mirror the existing
  "check, then skip silently" precedent used for optional Ledger context
  (check whether the source exists/is readable; if not, skip without
  erroring or warning, and never block the calling workflow).
- **FR-12**: The convention MUST require that any non-interactive or
  scheduler-driven invocation (e.g. `claude -p`, an autonomous scheduler
  worktree run) hard-skip the MCP-first path unconditionally and use the
  fallback — a bridge connection can require a human to approve a browser
  tab, which a non-interactive session cannot provide, so the attempt itself
  must never be made in that context.
- **FR-13**: The convention MUST define a staging/production URL table
  schema (environment name, URL, label) so that staging and production
  environments are always explicitly named in project configuration, and
  never inferred by the guard or any agent via hostname heuristics.
  `.smith/security-config.json`'s `browser_verification.urls` key
  (`urls.staging` / `urls.production`, each an array of
  `{name, url, label}` entries) is the machine-readable source of truth
  that the guard reads directly; `/smith` init and `/smith-update` MUST
  seed this key with empty `staging`/`production` lists so the schema
  always exists immediately after install or update, even before an
  operator has named any environment (resolved per `questions.md` Q2 —
  closes the "guard installed, zero enforcement" gap). CLAUDE.md's
  "MCP-First Browser Verification" table (FR-9) is the human-readable
  documentation view of the same environments, not itself read by any
  hook. Any navigated target matching neither list MUST be classified as
  **production** by default (fail-safe), with the sole exception of
  `localhost`, `127.0.0.1`, and `::1`, which are always classified as
  **staging** regardless of list contents (resolved per `questions.md`
  Q3).
- **FR-14**: `/smith-index --migrate-templates` MUST detect the new
  `## MCP-First Browser Verification` header using the same
  missing-header-detection mechanism it already applies to its four existing
  tracked headers, back up the target file before writing (or reuse an
  already-taken backup in the same run), and append the section from
  `templates/claude-md-additions.md` only when the header is absent. A
  second run against a file that already has the section MUST make no
  changes.

### Agent definitions

- **FR-15**: Each of the four bundled agents that already grant
  `mcp__playwright__*` tools —
  `skills/smith/agents/product-manager.md`, `senior-qa.md`,
  `staff-frontend.md`, and `staff-fullstack.md` — MUST have its E2E/browser
  instruction section updated to state the MCP-first-with-fallback contract:
  attempt MCP-driven, authenticated browser verification only when tools are
  present, `mcp_mode` resolves to `extension`, and the session is
  interactive; in every other case, continue with the agent's pre-existing
  verification approach, unchanged.
- **FR-16**: `product-manager.md`'s "E2E Testing Approach" and "Test URLs"
  content MUST be updated to reference the staging/production URL table
  schema (FR-13) as the source of environment URLs, so that any target the
  agent navigates to is identifiable by the safety guard as staging or
  production.

### smith-audit UX/SEO sub-audits

- **FR-17**: The UX (`smith-audit ux`) and SEO (`smith-audit seo`) entries
  in `skills/smith-audit/SKILL.md`'s Sub-Audit Orchestration list MUST be
  updated to state the same MCP-first-with-fallback contract for their
  Playwright-driven checks (attempt authenticated bridge-mode verification
  under the same three conditions; otherwise fall back to the sub-audit's
  current unauthenticated approach, unchanged).

### `smith` SKILL.md Q19-gated CLAUDE.md generation

- **FR-18**: The `## E2E Testing with Playwright MCP` block that
  `skills/smith/SKILL.md` §4.3 generates when Playwright MCP is selected in
  Q19 MUST emit the "MCP-First Browser Verification" convention content (or
  an explicit reference to the shipped `templates/claude-md-additions.md`
  section) into the generated project `CLAUDE.md`.

### Fallback chain (core cross-cutting behavior)

- **FR-19**: Every MCP-first browser-verification attempt, in every
  consuming surface (agents, smith-audit sub-audits, generated CLAUDE.md
  guidance), MUST evaluate the same decision chain: IF
  `mcp__playwright__*` tools are present in the current tool list AND the
  resolved `browser_verification.mcp_mode` is `extension` AND the current
  session is interactive, THEN proceed to drive the operator's authenticated
  browser via those tools (subject to the FR-2..FR-4 guard policy);
  OTHERWISE (any one condition false) fall back silently to the exact
  behavior that existed before this feature.
- **FR-20**: A fallback triggered by a bridge connection that does not
  succeed immediately (extension not connected, no approved tab available)
  MUST occur without waiting or polling for human approval — the attempt is
  treated as failed for that call and the fallback path is taken at once.

## Non-Functional Requirements

- **NFR-1**: Every hook this feature adds or that consumes its config MUST
  never block on missing configuration — absence of
  `.smith/security-config.json`, `browser_verification.mcp_mode`, or the
  vault MUST always resolve to a silent no-op/fallback, matching the
  existing `user-prompt-logger.sh` precedent (check for the file, exit 0 if
  absent).
- **NFR-2**: All new or modified shell content — `hooks/security-guard-mcp-browser.sh`
  and any shell snippets added to `skills/smith/SKILL.md` — MUST run
  correctly under both `bash` and `zsh` (no bash-only array syntax, no bare
  unquoted globs) and MUST be smoke-tested in a scratch repo under both
  shells before merge.
- **NFR-3**: `mcp__playwright__*` tools are session-scoped to the
  interactive Claude Code agent session and are never callable from a
  shelled-out script or subprocess. Nothing added by this feature may assume
  otherwise; this boundary is documented, not worked around (see Out of
  Scope).
- **NFR-4**: The guard hook MUST add negligible latency per gated call:
  synchronous pattern-matching only, no network calls, no external process
  spawns beyond the `python3` JSON parsing already used by the sibling
  guards.
- **NFR-5**: Documentation changes to `docs/security-model.md` and
  `docs/hooks.md` MUST match the existing structure and tone (tables,
  numbered lists, "Detailed Reference" subsections) so the new hook reads as
  a natural continuation of the existing ten, not a bolt-on.
- **NFR-6**: The `/smith-index --migrate-templates` change MUST remain
  non-destructive: it must never overwrite existing user content in a
  target `CLAUDE.md`, and it must share the migration's existing
  backup-before-write step rather than introducing a second, separate
  backup mechanism.

## Out of Scope

- **OOS-1 — smith-build / smith-bugfix test-suite phases.** These drive
  project-owned Playwright *library* code running as a subprocess/test
  runner, not an interactive Claude Code agent session, and structurally
  cannot call `mcp__playwright__*` tools (NFR-3). Unaffected by this
  feature.
- **OOS-2 — smith-research's stealth crawler scripts.** A separate,
  fully scripted Playwright pipeline with its own warmed-browser-context
  model for anti-bot-resilient crawling; not modified by this feature.
- **OOS-3 — Agency-package skills** (`smith-design`,
  `smith-extract-functionality`, `smith-timesheet`). These are private,
  agency-only distribution and are not bundled into the public smith-repo,
  so this feature does not modify them. The convention added in Deliverable
  2 is written generically enough that these skills could adopt it later;
  doing so is a separate, future change.
- **OOS-4 — Changing the Playwright MCP server configuration itself.**
  This feature only detects and reacts to whatever `mcp_mode` a project
  declares; it does not register, reconfigure, or change the scope of the
  Playwright MCP server, nor does it install or manage the bridge browser
  extension.

## Assumptions

- **A-1**: The user's Playwright MCP server is registered at user scope in
  `--extension` (bridge) mode, with the bridge browser extension installed
  and working in Chrome. This is the reference configuration the
  fallback chain's `extension` branch is built to drive.
- **A-2**: Per-project overrides of `browser_verification.mcp_mode` are
  expected and MUST be honored — a consumer project may declare
  `mcp_mode: sandbox` (or `off`) even while the user's own global default
  server registration is bridge-mode; the project-level value always wins
  for that project's agents/audits.
- **A-3**: A known, separate documentation gap exists in the File Purpose
  Policy template (a "section VI" is missing from a different template).
  This feature's Deliverable 2 section is independent of that gap and MUST
  NOT be blocked by, or bundled into, closing it.
- **A-4**: "Production-labeled" is determined solely by the staging/production
  URL table (FR-13) or equivalent explicit project config — the guard never
  applies its own heuristic (e.g., hostname sniffing for "prod"/"www") to
  decide production-ness.
- **A-5**: Bridge-mode and sandbox-mode Playwright MCP servers expose an
  identical `mcp__playwright__*` tool surface; consequently `mcp_mode` can
  only ever be known from explicit configuration, never introspected from
  the tool list at runtime (restates FR-10 as a design assumption other
  work in this area should not violate).

## Success Criteria

- **SC-1**: With `mcp_mode: extension`, the bridge extension connected, and
  an interactive session, an agent-driven verification reaches an
  auth-gated staging screen with zero manual re-login steps.
- **SC-2**: With `mcp__playwright__*` tools absent, OR `mcp_mode` resolved
  to `sandbox`/`off`, OR the session non-interactive, the observed behavior
  (prompts shown, tool calls made, pass/fail outcome) is byte-identical to
  the pre-feature behavior — zero new prompts and zero new failures are
  introduced solely by this feature's presence.
- **SC-3**: Across all interaction-tool call attempts
  (click/type/fill_form/select_option/press_key/drag/hover) directed at a
  production-labeled target, zero execute without a prior recorded explicit
  human confirmation for that target/session.
- **SC-4**: `hooks/security-guard-mcp-browser.sh` produces identical exit
  codes and JSON output for equivalent input under both `bash` and `zsh`.
- **SC-5**: Running `/smith-index --migrate-templates` twice in succession
  against a project missing the "MCP-First Browser Verification" section
  adds the section exactly once; the second run is a no-op (no diff).
