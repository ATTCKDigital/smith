# Quickstart: MCP-First Browser Verification with Safety Guard

End-to-end verification walkthrough. Run after implementation, before
merge, to confirm each user scenario (US-1..US-9) behaves as specified.

---

## Prerequisites

- Playwright MCP registered at user scope in `--extension` (bridge) mode,
  with the bridge browser extension installed and connected in Chrome
  (A-1). Verify: the current tool list includes
  `mcp__playwright__browser_navigate` etc.
- A consumer project (or scratch repo) with `.smith/` initialized.
- `hooks/security-guard-mcp-browser.sh` installed and registered in
  `settings.json` (via `/smith-update` or the fragment merge).

---

## Scenario 1 — Enable bridge mode, authenticated staging check, zero re-login (US-1 / SC-1)

1. In the project's `.smith/config.json`, set
   `browser_verification.mcp_mode: "extension"` (the CLAUDE.md
   MCP-First Browser Verification section documents this key but the
   functional value is read from config), and add a staging/production
   URL table entry in CLAUDE.md naming the staging auth-gated screen.
2. Mirror the same URL into `.smith/security-config.json`'s
   `mcp_browser_production_urls`/staging equivalent if the screen under
   test is production-labeled (skip for staging-only checks — FR-4 only
   gates production).
3. In an **interactive** Claude Code session, ask `senior-qa` (or
   `product-manager`) to verify the auth-gated staging screen.
4. **Expected**: the agent drives the operator's already-logged-in
   Chrome tab via `mcp__playwright__*` tools, reaches the auth-gated
   screen with **zero manual re-login prompts**, and every
   `browser_click`/`browser_type`/etc. call it makes against the staging
   target is evaluated by the guard (visible as an allow — staging is not
   production, so no confirmation is required) before executing.
5. **Pass condition**: screen reached, no login form ever shown to the
   agent, no guard denial surfaced for the staging target.

---

## Scenario 2 — Fallback: tools absent (US-2 / SC-2)

1. Run the same verification request in a session/agent configuration
   where no `mcp__playwright__*` tools are granted (e.g. temporarily
   strip them from the agent's `tools:` frontmatter, or run outside a
   Playwright-MCP-registered session).
2. **Expected**: the agent silently uses its pre-existing E2E/verification
   approach. No error, no warning, no extra prompt appears that mentions
   MCP, bridge mode, or the absence of tools.
3. **Pass condition**: observed prompts/tool calls are identical to a
   pre-feature run of the same request.

---

## Scenario 3 — Fallback: sandbox mode (US-3 / SC-2)

1. Set `browser_verification.mcp_mode: "sandbox"` in `.smith/config.json`
   (tools still present in the session — sandbox-mode Playwright MCP
   exposes the identical tool names, A-5).
2. Ask an agent to verify an auth-gated screen.
3. **Expected**: the agent does NOT treat the session as
   authenticated-bridge-capable — it falls back to the pre-existing
   unauthenticated verification path (e.g. hits the login wall exactly as
   it did before this feature existed, or uses whatever workaround it
   used pre-feature).
4. **Pass condition**: behavior is byte-identical to a `mcp_mode: off` /
   pre-feature run — confirms `mcp_mode` is read from config, never
   inferred from tool presence (FR-10), since the tools ARE present here
   and the agent still doesn't attempt bridge-mode driving.

---

## Scenario 4 — Fallback: non-interactive / scheduler context (US-4 / SC-2)

1. Set `mcp_mode: extension` (tools present, would normally activate).
2. Invoke the same verification task **non-interactively**:
   ```bash
   claude -p "verify the staging screen per spec X"
   ```
   or via the Smith scheduler's autonomous worktree run.
3. **Expected**: the fallback path is used **unconditionally** — no
   attempt to open or connect to a bridge browser tab is made at all.
4. **Pass condition**: the run completes (or fails) on its own, without
   ever pausing/hanging waiting for a human to approve a browser tab.
   Timing check: run should not show a multi-second stall consistent
   with a bridge-connect attempt before falling back.

---

## Scenario 5 — Fast-fail on a stalled bridge connect (US-5 / FR-20)

1. Set `mcp_mode: extension`, interactive session, tools present — but
   simulate the extension being disconnected/no approved tab available
   (e.g. close the bridge extension's connection in Chrome first).
2. Ask an agent to verify an auth-gated screen.
3. **Expected**: the first bridge-mode tool call fails immediately (not
   after a long timeout or retry loop); the agent treats that single call
   as failed and falls back to its pre-existing verification approach for
   the rest of the task — it does not retry the bridge connection
   repeatedly.
4. **Pass condition**: total elapsed time before fallback kicks in is
   consistent with "one failed call," not consistent with a retry/backoff
   loop.

---

## Scenario 6 — Read-only tools always pass, any target (US-6 / FR-2)

1. With `mcp_mode: extension`, navigate to the production-labeled target
   configured in Scenario 1 step 2.
2. Call each read-only tool in turn: `browser_navigate`,
   `browser_snapshot`, `browser_take_screenshot`,
   `browser_console_messages`, `browser_network_requests`,
   `browser_wait_for`, `browser_tabs`, and a `browser_evaluate` call
   whose script only reads (e.g. `() => document.title`).
3. **Expected**: every call is allowed by the guard, no confirmation
   required, including against the production target.
4. **Pass condition**: zero denials, zero `additionalContext` warnings
   for any of these calls.

---

## Scenario 7 — Production confirm-gate: denied without confirmation (US-7 / SC-3)

1. With the agent navigated to the production target from Scenario 6,
   attempt an interaction tool call (e.g. `browser_click`) **without**
   first writing a confirmation record.
2. **Expected**: the guard denies the call. The
   `permissionDecisionReason` names the specific production target URL
   and states that explicit human confirmation is required before any
   interaction tool may run against it (verbatim requirement, US-7).
3. **Pass condition**: `permissionDecision: "deny"`, reason text contains
   both the target URL and the word "confirmation."
4. Repeat with `warn_only_mode: true` set in `.smith/security-config.json`
   — **expected**: still denied (the production-confirmation gate is
   non-downgradable per `data-model.md` §4's tension resolution), unlike
   a non-production `allow_interactions: false` denial, which **would**
   downgrade to a warning under `warn_only_mode: true`. This distinction
   is the one place this quickstart deliberately exercises the
   plan's documented spec tension — confirm the implementer's resolution
   matches `data-model.md` §4 before treating this as a pass/fail
   boundary; if the resolution changes post-questions-gate, update this
   step accordingly.

---

## Scenario 8 — Production confirm-gate: allowed after confirmation (US-8 / SC-3)

1. Following Scenario 7's denial, have the human explicitly confirm in
   the conversation that interaction is authorized for this
   target/session.
2. The agent records the confirmation (writes
   `.smith/vault/.mcp-browser-confirmed` per `data-model.md` §3.2).
3. Retry the same interaction call.
4. **Expected**: the guard now allows it.
5. **Pass condition**: `permissionDecision` absent/allow on retry, with
   no change to `mcp_mode`, `warn_only_mode`, or the target itself between
   steps 1 and 3.
6. **Invalidation check**: navigate to a *different* production URL (not
   the confirmed one) and retry an interaction call there — **expected**:
   denied again (confirmation does not transfer across targets, per
   `data-model.md` §3.2's mismatch handling).

---

## Post-run cleanup

Delete `.smith/vault/.mcp-browser-target` and
`.smith/vault/.mcp-browser-confirmed` between scenario runs to avoid one
scenario's state leaking into the next:
```bash
rm -f .smith/vault/.mcp-browser-target .smith/vault/.mcp-browser-confirmed
```

## Migrate-templates check (US-9 / SC-5, not agent-driven — separate from Scenarios 1-8)

```bash
# First run: section missing, should append + backup
/smith-index --migrate-templates
grep -c '^## MCP-First Browser Verification$' CLAUDE.md   # expect 1
ls CLAUDE.md.bak.*                                         # expect exactly one new backup

# Second run: section present, should no-op
/smith-index --migrate-templates
grep -c '^## MCP-First Browser Verification$' CLAUDE.md   # still 1
diff <(git show HEAD:CLAUDE.md) CLAUDE.md                  # only the first run's diff, second run added nothing
```
