# Data Model: MCP-First Browser Verification with Safety Guard

All shapes below are the operative machine-readable contracts. Prose/table
conventions meant for human authors (CLAUDE.md) are marked as such; JSON
shapes meant for hook consumption are marked as such. See `research.md`
§10-§13 for why the split exists.

---

## 1. `browser_verification` config key

### 1.1 Schema

```jsonc
{
  "browser_verification": {
    "mcp_mode": "extension",       // "extension" | "sandbox" | "off"
    "urls": {
      "staging": [
        { "name": "staging", "url": "https://staging.example.com", "label": "staging" }
      ],
      "production": [
        { "name": "production", "url": "https://app.example.com", "label": "production" }
      ]
    },
    "allow_interactions": false     // operator-set escape hatch; see §4
  }
}
```

- `mcp_mode` — **required** for the MCP-first path to ever activate
  (FR-10: never inferred). Missing/absent ⇒ treated as `"off"`
  (fail-closed to pre-existing behavior, satisfying NFR-1/FR-19's "any
  one condition false ⇒ fallback").
- `urls.staging` / `urls.production` — each entry is `{name, url, label}`
  per FR-13. `label` is redundant with the array key today (`staging`
  entries are implicitly `label: "staging"`) but is kept as an explicit
  field so a future single flat list (not nested by array key) stays
  compatible without a schema break.
- `allow_interactions` — **not** in the spec's FR text verbatim, but
  named in this task's brief as part of the config schema. Resolved
  meaning: a project-level kill-switch that, when `false`, denies *all*
  interaction tools regardless of target (staging included) — a stricter
  posture than FR-4 requires (FR-4 only mandates gating on
  production). Default `true` (interaction tools behave per the FR-2..FR-4
  decision table) so the default posture matches the spec exactly; an
  operator who wants "read-only everywhere" sets this `false`. This is an
  **addition beyond the spec's literal FRs** — flagged in `plan.md`'s
  tension list as something the questions gate should confirm before
  build, not assumed.

### 1.2 Where it lives — `.smith/security-config.json` is the source of truth; CLAUDE.md is the human view

**Decision (resolved per `questions.md` Q2, superseding the original
"CLAUDE.md primary / mirror secondary" framing below):
`.smith/security-config.json`'s `browser_verification.urls` and
`browser_verification.allow_interactions` keys (§2) are the
machine-readable source of truth the guard reads directly. `/smith` init
and `/smith-update` seed `browser_verification.urls` with empty
`staging`/`production` lists so the schema always exists immediately
after install or update. CLAUDE.md's "MCP-First Browser Verification"
table (FR-9/FR-13) is the human-authored, human-readable documentation of
the same environments — not itself read by any hook.
`browser_verification.mcp_mode` is unaffected by this decision: it stays
in `.smith/config.json` (`templates/config.default.json`, seeded by
`session-start-logger.sh`) because it is agent-read only — the guard
itself never needs `mcp_mode` to make its allow/deny decision (see §4).**

Justification:
- NFR-4 restricts the guard to `python3` JSON parsing only — it
  structurally cannot parse a markdown table, so whatever it reads must
  already be JSON, and CLAUDE.md can never be that file no matter how
  authoritative it is for humans.
- `.smith/security-config.json` is already the file
  `security-guard-bash.sh`/`security-guard-files.sh` actually read
  (`research.md` §10) — extending it, rather than `.smith/config.json`
  (which no `PreToolUse` guard reads today, despite being seeded), keeps
  this guard consistent with its siblings' real runtime behavior instead
  of their seeded-but-inert template.
- Seeding the key at install/update time (rather than leaving it to be
  hand-mirrored) closes the enforcement gap described below.

**Consequence (gap closed by seeding, not eliminated by it):** because
`browser_verification.urls` is always seeded (even empty) by `/smith`
init and `/smith-update`, a fresh install has a guard with a
well-formed config to read from day one — no project can ship a guard
with a missing/malformed schema. The remaining, expected day-one state is
"empty lists ⇒ nothing matches either list," which — per Q3's
fail-safe default (§4) — now means an unmatched target is treated as
**production**, not silently unenforced as the original framing above
assumed. Populating `urls.staging` is what an operator does to get
frictionless staging access; production-grade protection is fail-safe
from install, before any list is populated.

---

## 2. Guard's own operative config — `.smith/security-config.json`

Extends the **existing, already-consumed** file
(`security-guard-bash.sh:30`, `security-guard-files.sh:30`) with one new
optional top-level `browser_verification` key, read with the same
`if [ -f "$CONFIG_FILE" ]` / one-python3-call-per-field pattern as the
existing `warn_only_mode`/`allowed_commands`/`production_domains` keys.
**Resolved per `questions.md` Q2: this key uses the same `urls`/
`allow_interactions` shape as §1.1, not a flattened `mcp_browser_*`
naming — there is one schema, and this file is where it actually lives
for guard consumption**, seeded empty by `/smith` init / `/smith-update`
(§1.2):

```jsonc
{
  "warn_only_mode": false,
  "browser_verification": {
    "urls": {
      "staging": [
        { "name": "staging", "url": "https://staging.example.com", "label": "staging" }
      ],
      "production": [
        { "name": "production", "url": "https://app.example.com", "label": "production" }
      ]
    },
    "allow_interactions": true
  }
}
```

- `browser_verification.urls` — **the field the guard actually reads for
  FR-4/FR-13's classification test** — not the CLAUDE.md table, not
  `.smith/config.json`. Same `{name, url, label}` shape per entry as
  §1.1 (one schema, no divergent flattened copy). Seeded as
  `{"staging": [], "production": []}` at install/update time so the key
  always exists (§1.2); an unmatched target against a populated-or-empty
  list is classified per §4's fail-safe default (Q3): production, unless
  the target is `localhost`/`127.0.0.1`/`::1`, which is always staging.
- `browser_verification.allow_interactions` — the master interaction
  kill-switch (`questions.md` Q5 / spec FR-21). Default `true`. This is
  the file the guard itself reads at `PreToolUse` time
  (`.smith/config.json` is not otherwise read by any `PreToolUse` guard
  today).
- Reuses the **existing** `warn_only_mode` key rather than inventing a
  guard-specific one — same flag already governs both sibling guards
  (FR-3 explicitly requires this reuse). `warn_only_mode` downgrades
  every guard denial except the FR-4 production confirm-gate denial,
  which it can never downgrade or bypass (Q1 — see §4).

---

## 3. Guard-owned runtime state (not operator-authored)

Two singleton files under `.smith/vault/`, written by the guard itself as
a side effect of allowed calls (never operator-edited), following the
`.current-session` singleton-pointer precedent
(`security-guard-bash.sh:29`) — see `research.md` §11 for why singleton
rather than session-keyed.

### 3.1 `.smith/vault/.mcp-browser-target`

```jsonc
{
  "url": "https://app.example.com/admin/users",
  "classification": "production",   // "staging" | "production" | "unclassified"
  "updated_at": "2026-09-12T18:03:11Z"
}
```
Written on every **allowed** `mcp__playwright__browser_navigate` call
(classification computed by substring/hostname match against
`browser_verification.urls.production[].url` / `.urls.staging[].url` —
both read from §2's config). `localhost`, `127.0.0.1`, and `::1` are
always written as `classification: "staging"` regardless of list
contents (Q3, unconditional rule, not a list match). Any other target
matching neither list is written as `"unclassified"`; §4's decision table
treats `"unclassified"` as **production** for gating purposes (fail-safe
default, Q3). Read (never written) by every interaction-tool call to
answer "what's the current target."

### 3.2 `.smith/vault/.mcp-browser-confirmed`

```jsonc
{
  "url": "https://app.example.com/admin/users",
  "confirmed_at": "2026-09-12T18:04:02Z"
}
```
Absent by default. Written **only** by the agent, **only** after an
explicit affirmative human answer in the conversation (guard never writes
this file itself — see `research.md` §12). The guard's FR-4 check
compares this file's `url` against `.mcp-browser-target`'s current `url`;
a mismatch (navigated somewhere else since confirming) is treated as "not
confirmed for *this* target," forcing re-confirmation — this is the
mechanism that keeps a stale confirmation from silently covering a new
production page.

Both files: absent ⇒ guard treats as "unclassified"/"not confirmed"
respectively; malformed JSON ⇒ same treatment (never a crash, per
NFR-1's spirit even though NFR-1 is literally scoped to the fallback
chain, not the guard — the guard's own file reads mirror the identical
`2>/dev/null || echo ""` defensiveness as every other config read in this
codebase).

---

## 4. Decision table — tool class × target class × mode × interactive → verdict

This table is the guard's (`hooks/security-guard-mcp-browser.sh`) core
logic. **`mode` and `interactive` columns are informational context the
*agent* uses to decide whether to attempt the MCP-first path at all
(FR-19) — the guard itself does not need to know `mcp_mode` or
interactive-ness to make its allow/deny decision**, because by the time a
`mcp__playwright__*` call reaches `PreToolUse`, the tool call already
exists; the guard's job (FR-2/FR-3/FR-4) is purely tool-class ×
target-class × operator-policy. Including the columns here anyway because
the task brief asks for the full cross-product and because it clarifies
*why* the guard never needs to duplicate the agent-side fallback check.

| Tool class | `allow_interactions` | Target class | Confirmed for target? | Verdict |
|---|---|---|---|---|
| Read-only (navigate, snapshot, screenshot, console_messages, network_requests, wait_for, tabs) | any | any (incl. production) | n/a | **allow** (FR-2) |
| Interaction (incl. `browser_evaluate` — always interaction-class, no read-only carve-out; Q4) | `false` | any (staging, production, or unclassified) | n/a | **deny** — master kill-switch (FR-21/Q5); `warn_only_mode` MAY still downgrade this one to a warning, since it is a distinct denial from the FR-4 production confirm-gate below |
| Interaction | `true` | staging — listed in `urls.staging`, or `localhost`/`127.0.0.1`/`::1` (always staging, unconditionally; Q3) | n/a | **allow** |
| Interaction | `true` | unclassified — matches neither `urls.staging` nor `urls.production`, and is not localhost | n/a | treated as **production** by default (fail-safe; Q3) → fall through to the production rows below |
| Interaction | `true` | production — listed in `urls.production`, or unclassified per the row above | no | **deny**, and this denial is **NOT downgradable by `warn_only_mode`** even when `warn_only_mode: true` — the sole non-bypassable denial in this table (Q1) |
| Interaction | `true` | production (as above) | yes (matches current target) | **allow** (FR-4/US-8) |
| Interaction | `true` | production (as above) | yes (target changed since) | **deny** (treated as unconfirmed — §3.2); same FR-4 gate as the row above, equally non-downgradable (Q1) |

**Resolved (`questions.md` Q1):** FR-3 says the guard's deny-by-default
reasoning respects `warn_only_mode` "the same way `security-guard-bash.sh`
and `security-guard-files.sh` already do" (i.e. **every** deny is
downgradable to a warning when `warn_only_mode: true`). FR-4 says "no
interaction tool may execute against a production-labeled target **on the
strength of an agent's own judgment alone**," and the feature's own
requirements checklist (`checklists/requirements.md` Notes) states the
production-confirmation requirement was taken as "mandatory and
**non-bypassable** via warn-only mode" verbatim from the user. These were
in direct textual conflict for exactly one cell: an interaction call
against an unconfirmed production target under `warn_only_mode: true`.
The questions gate resolved this as **Option A**: the production
confirm-gate (FR-4) is the one denial `warn_only_mode` can never downgrade
or bypass; every other guard denial in this table — including the
`allow_interactions: false` kill-switch — downgrades to a warning under
`warn_only_mode` exactly like the sibling guards. This is now spec text
(FR-3/FR-4), not an open tension.

---

## 5. Guard deny-message contract

Every deny reuses the existing `SMITH SECURITY: <reason>` prefix
(`security-guard-bash.sh:77`) for grep-ability/consistency across all
three guards. Two distinct reason templates:

**Interaction denied — master kill-switch (`allow_interactions: false`,
applies regardless of target class, staging or production; FR-21/Q5):**
```
SMITH SECURITY: Interaction tool 'mcp__playwright__browser_click' blocked.
This project has browser_verification.allow_interactions set to false —
only read-only Playwright MCP tools (navigate, snapshot, screenshot,
console/network inspection) may run. Read-only verification is
unaffected.
```

**Production interaction denied, no recorded confirmation (FR-4/US-7 — must "name the production target and state that explicit confirmation is required," verbatim requirement):**
```
SMITH SECURITY: Interaction tool 'mcp__playwright__browser_click' blocked
against production target 'https://app.example.com/admin/users'. This
target is listed as production in the project's staging/production URL
table. Explicit human confirmation is required before any interaction
tool may run against it — stop and ask the user to confirm interaction is
authorized for this target before retrying.
```

Both are constructed from a single bash template with the tool name and
resolved target string interpolated — no per-tool-name hardcoding, so
adding a future interaction tool to the Overview's list requires no
guard-message changes.
