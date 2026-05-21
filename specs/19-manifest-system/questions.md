---
feature: 19-manifest-system
branch: 19-manifest-system
generated: 2026-05-21
status: ANSWERED
spec: ./spec.md
plan: ./plan.md
---

# Implementation Questions: Manifest System & Structured Context Retrieval

These questions resolve ambiguities identified in `spec.md` (Open Questions section) and `plan.md` (Implementation Discoveries section) that need user input before autonomous build can proceed.

---

## Q1: Does `smith-repo` itself get a `.smith/index/` manifest?

**Context** (spec.md Open Questions #1): `smith-repo` is the Smith distribution repo — not a typical Smith-consumer project. Its contents are skills, hooks, and scripts that are *deployed to other projects*, not application code in the conventional sense. The manifest system is designed primarily for projects containing application code (FastAPI endpoints, React components, etc.). The question is whether to dogfood it on smith-repo itself.

**Question:** Should `/smith-index` produce a manifest for `smith-repo`, treating dirs like `skills/`, `hooks/`, `scheduler/`, `scripts/` as systems?

**Options**

| Option | Description | Implications |
|--------|-------------|--------------|
| A      | Yes — dogfood on smith-repo with custom system map: `skills/` → system-01-skills, `hooks/` → system-02-hooks, `scheduler/` → system-03-scheduler, `scripts/` → system-04-installation, `tests/` → system-05-tests, `docs/` → system-06-docs | Forces the parsers to work on shell scripts (parse-bash dir) which the current scope doesn't include. Validates the system end-to-end on a real repo. Adds bootstrap overhead. |
| B      | No — smith-repo skips its own manifest. The system is for consumer projects only. | Simplest. No edge case for "what about repos with no application code." Trade-off: smith-repo can't use its own structured-context retrieval during development. |
| C      | Yes, but minimal — only index the parser scripts themselves (`scripts/parsers/parse-python.py`, `parse-js.js`) so they can self-describe. Don't index skills/hooks/scheduler. | Compromise. Validates the parsers without the full bootstrap cost. Slightly weird semantics. |

**Recommended:** **B** — skip smith-repo's own manifest. Reasoning: smith-repo's content is heterogeneous (Python parsers, bash hooks, markdown SKILL.md files, JSON settings, JS scheduler bits) — the parsers cover the source-file extensions, but the *meaningful* content of smith-repo is the SKILL.md and hook scripts, which aren't application code. Dogfooding here would force us to extend parser scope (bash, markdown) just for self-indexing, which is mission creep. The end-to-end validation we want is via the user's *consumer* projects (armory, goldcanna-inventory). Keep smith-repo's role focused: it ships the tool, it doesn't use the tool on itself.

**Answer:** B — skip smith-repo's own manifest. System is for consumer projects only.

---

## Q2: Migration helper for existing Smith projects?

**Context** (spec.md Open Questions #2): The spec defines three migration behaviors for the manifest *itself* (auto-on-init, manual, soft-warning fallback). But the spec also updates `constitution.template.md` and `CLAUDE.md` templates with new sections (File Size Policy, Smith Context System, Manifest Maintenance). Existing Smith projects (armory, goldcanna-inventory) have already-deployed `constitution.md` and `CLAUDE.md` files that won't get those updates automatically.

**Question:** How should existing Smith projects pick up the new constitution/CLAUDE.md template sections?

**Options**

| Option | Description | Implications |
|--------|-------------|--------------|
| A      | Build a new `/smith-migrate-manifest` skill that detects missing sections in existing `constitution.md` and `CLAUDE.md`, prompts user, and appends them non-destructively | Smooth UX for existing projects. Adds another skill to the distribution. Risk: incorrect detection if sections were customized. ~150 LOC + a skill markdown. |
| B      | Add a `--migrate-templates` flag to `/smith-index` that does the same detect-and-append work | Reuses existing skill. Cleaner namespace. Slightly less discoverable. Same LOC + flag. |
| C      | Manual diff approach: ship a `docs/MIGRATION-MANIFEST-SYSTEM.md` with the new sections and instructions for users to paste them into their existing files | Zero code. Forces users to do the work. Realistic given there are currently only 2-3 existing Smith projects. |
| D      | Both manual diff (always) AND `--migrate-templates` flag on `/smith-index` | Belt-and-suspenders. Most LOC; most coverage. |

**Recommended:** **B** — `/smith-index --migrate-templates`. Reasoning: keeps the namespace tight (don't add `/smith-migrate-manifest` skill that only does one thing), is discoverable to anyone running `/smith-index --help`, and is non-destructive (only appends sections if not already present, with a backup). The manual-diff doc (C) can be added later if users want a paper trail.

**Answer:** B — `/smith-index --migrate-templates` flag for existing projects.

---

## Q3: Sub-agent fan-out — kill switch for `manifest-updater.sh`?

**Context** (spec.md Open Questions #3): `manifest-updater.sh` fires on every `Write|Edit` in both the main session AND sub-agents. During a heavy `/smith-build` that spawns 4-6 parallel sub-agents each writing 5+ files, that's potentially 30+ parse invocations in a short window. The 500ms-per-file budget is tight; concurrent invocations may queue or starve.

**Question:** Should there be a kill switch to disable `manifest-updater.sh` during specific contexts (heavy builds, sub-agent storms)?

**Options**

| Option | Description | Implications |
|--------|-------------|--------------|
| A      | Add env var `SMITH_DISABLE_MANIFEST_UPDATER=1` that the hook respects (no-op when set). `/smith-build` sets it during multi-file sub-agent fan-outs, unsets after, then runs `/smith-index --incremental` to catch up. | Most flexible. Adds coordination logic to `/smith-build`. Risk: forgotten unset → manifest goes stale silently. |
| B      | No kill switch. Trust the <500ms budget. If builds are slow, optimize parser performance instead. | Simplest. Keeps the system invariant ("manifest is always current after a Write/Edit"). If parsers actually meet 200ms target and bash overhead is ~50ms, 500ms gives 2x headroom — should be fine. |
| C      | Add a debouncer at the hook level: queue writes, batch-process every 1 second. Drops the "always current" invariant in exchange for throughput. | Most complex. Best throughput. Manifest can be stale by up to 1s, which matters for context-loader behavior. |

**Recommended:** **B** — no kill switch initially. Reasoning: premature optimization without data. Acorn-based JS parsing measured at 135ms in research.md, Python ast is faster. Stay <500ms with comfortable margin. If real-world heavy builds show stalls, add option A as a follow-up — but design it such that the "unset on exit" is reliable (trap-based, not manual). YAGNI for v1.

**Answer:** B — no kill switch. Trust the <500ms budget; revisit if real builds show stalls.

---

## Q4: Hook registration during install — auto-register or prompt?

**Context** (spec.md Open Questions #5): When `npx skills add attck/smith` runs, the user's `~/.claude/settings.json` already has many hooks registered. Adding `manifest-updater.sh` (PostToolUse Write|Edit, register LAST) and `context-loader.sh` (UserPromptSubmit, first of its kind) modifies the user's settings. Auto-registration is convenient but invasive; a prompt adds friction but respects user control.

**Question:** Should the installer auto-register the new hooks, or prompt the user?

**Options**

| Option | Description | Implications |
|--------|-------------|--------------|
| A      | Auto-register both hooks during `npx skills add attck/smith`. Print a clear summary at the end: "Added 2 hooks to ~/.claude/settings.json". Provide `--no-hooks` flag to opt out. | Smoothest UX. Most users get the feature for free. Risk: surprise modifications. |
| B      | Prompt during install: "Smith ships with two new hooks (manifest-updater, context-loader). Register now? [Y/n]" | Explicit consent. Adds one interactive step to an otherwise non-interactive install. |
| C      | Don't register during install. Document a separate `/smith-install-hooks` skill that registers on demand. | Most respectful of user settings. Requires explicit action — many users will skip. |
| D      | Register `manifest-updater.sh` automatically (it's safe — just generates manifest files), prompt for `context-loader.sh` (it intercepts every prompt — more invasive). | Split-the-difference. Users get the indexing for free; the intercepting hook needs explicit consent. |

**Recommended:** **A** — auto-register with summary + `--no-hooks` flag. Reasoning: the install command itself is opt-in (user typed `npx skills add attck/smith`). Inside that opt-in, registering the hooks is the obvious next step — otherwise the user gets a manifest system that doesn't actually run. Friction-free is the right call. The `--no-hooks` flag covers advanced users who want manual control.

**Answer:** A — auto-register both hooks during install, print summary, support `--no-hooks` flag.

---

## Q5: Default `.smith/index/` gitignore policy?

**Context** (spec.md Open Questions #6): The spec says `.smith/index/` is regenerated from the codebase and should be gitignored. But Smith installs `.gitignore` patterns differently across projects — some users gitignore `.smith/` entirely, others only `.smith/vault/`. There's also a discoverability concern: teammates pulling a Smith project without running `/smith-index` see no manifest at all, so any context-loader warnings won't surface for them either (no install hooks → no context-loader fires).

**Question:** What default `.gitignore` entry should the installer add for `.smith/index/`?

**Options**

| Option | Description | Implications |
|--------|-------------|--------------|
| A      | Gitignore `.smith/index/` entirely. Each developer regenerates their own manifest. | Clean repos. Pure DX choice. Teammates without hooks installed get nothing — but they shouldn't be running Smith skills anyway. |
| B      | Commit `.smith/index/` to git. Manifest stays in sync across team. | Bigger diffs on every code change. Manifest churn pollutes git history. Bad. |
| C      | Gitignore `.smith/index/files/` and `.smith/index/systems/` (the auto-generated content) but commit `.smith/index/manifest.md` and `.smith/index/config/*.json` (the team-shared config + the top-level overview) | Middle ground. Top manifest gives teammates an at-a-glance project map without churn. Config files (especially custom `system-paths.json`) become shared/versioned, which is what you'd want. |
| D      | Gitignore `.smith/index/` entirely but ALSO commit `templates/manifest-readme.md` instructing teammates how to bootstrap their own. | Lowest friction + zero pollution. Requires users to run a setup step. |

**Recommended:** **C** — gitignore the auto-generated bits (files/, systems/) but commit the top-level `manifest.md` + `config/*.json`. Reasoning: this matches how teams treat similar generated assets (e.g., commit schema, gitignore the generated client). The top-level manifest is a project overview document — useful even for teammates not running Smith. The `system-paths.json` is shared configuration that should be versioned (a custom path mapping is a team decision, not a personal one). The per-file `.meta` and per-system manifests change on every commit and would pollute history.

**Answer:** C — gitignore `.smith/index/files/` and `.smith/index/systems/`; commit `manifest.md` and `config/*.json`.

---

## Q6: Manifest staleness detection — mtime or hash?

**Context** (spec.md Open Questions #7): `/smith-index --check` reports stale or missing `.meta` files. The detection mechanism affects correctness and performance:
- **mtime**: cheap (stat call), but unreliable in git worktree scenarios where checkout changes mtime without changing content
- **Hash**: reliable but expensive (full file read + SHA-256 per file)

In a worktree-heavy workflow (which is exactly how Smith operates), mtime gives false positives.

**Question:** Which mechanism should `--check` use?

**Options**

| Option | Description | Implications |
|--------|-------------|--------------|
| A      | mtime only. Fast (~1s for 400 files). Wrong in worktrees. | Wrong answers in the most common Smith workflow. Bad. |
| B      | Hash only (SHA-256 first 4KB of file). Slower (~5-10s for 400 files). Always correct. | Reliable. Adds noticeable latency to `--check`. Trade-off worth it for correctness. |
| C      | Hybrid — mtime first as a fast filter, hash to confirm any that look stale. | Best perf + correctness. Slightly more complex. Edge case: file with same mtime but different content (very rare) still misses, since mtime filter rules it out first. |
| D      | Store both mtime AND hash in the `.meta` file. Use mtime as a "definitely fresh if mtime matches" fast path; fall through to hash check otherwise. | Most robust. Largest `.meta` files. Adds 64 bytes per .meta — at 400 files that's 25KB total, negligible. |

**Recommended (revised after discussion):** **B** — hash-only. Reasoning: the manifest-updater.sh hook is the primary truth source — sidecars are fresh by construction in steady state. `/smith-index --check` is a maintenance/diagnostic command for edge cases (git pull/merge/checkout, external edits via VS Code, hook failures), not the hot path. Since it's rarely invoked, the ~5-10s hash scan latency is acceptable, and the mtime+hash hybrid (original D) is over-engineering. Hash-only gives correct results in all worktree scenarios without the storage and code complexity of dual fingerprints.

**Answer:** B — hash-only (SHA-256 of first 4KB). --check is a maintenance command, not hot path. Hook is primary truth source.

---

## Q7: System auto-detection when `system-paths.json` is missing?

**Context** (spec.md Open Questions #8): The spec says path-to-system mapping is configured in `.smith/index/config/system-paths.json`. But on a fresh project run (`/smith-index` with no config yet), there's no mapping. The spec doesn't say whether to fail, default, or auto-detect.

**Question:** What should `/smith-index` do when `system-paths.json` is missing?

**Options**

| Option | Description | Implications |
|--------|-------------|--------------|
| A      | Fail with a clear error: "No system-paths.json found. Run `/smith-index --init` to bootstrap a default, or create the file manually." | Explicit. Requires users to think about their system structure before indexing. Higher friction. |
| B      | Auto-generate a default `system-paths.json` by inspecting top-level dirs: `backend/` → `system-backend`, `frontend/` → `system-frontend`, `services/<name>/` → `system-<name>`, etc. Save the file. Print "Auto-generated config; edit to customize." | Lowest friction. Risk: generated mapping is wrong and silently used. |
| C      | Skip system mapping entirely if config is absent. All files get `system: unassigned`. Top-level manifest still works. | Most graceful. Loses much of the system-routing value but doesn't fail. Best as "phase 1 mode" before the user customizes. |
| D      | Hybrid: auto-generate to `system-paths.json.suggested`, ask user to rename + edit, fall back to "everything is unassigned" until they do. | Explicit + suggested defaults. Most polite. Probably overkill. |

**Recommended (refined after discussion):** **Path 2** — heuristic-as-engine, system-paths.json-as-overrides. The resolver tries explicit rules first (longest-prefix wins), falls back to a built-in heuristic for any path not matched. `system-paths.json` is optional; only contains the rules where users want to override the heuristic's guess. New directories auto-map without any user action. This collapses the original "what happens when system-paths.json is missing" question — there's nothing to do, the heuristic runs.

Heuristic logic:
- `services/<name>/` → `system-<name>`
- `backend/<name>/` → `system-backend-<name>`
- `frontend/<name>/` → `system-frontend-<name>`
- Top-level source dirs not matching above → `system-<dirname>`
- Tests, docs, config dirs → `unassigned` (or their own respective systems)

**Answer:** Path 2 — heuristic + explicit overrides. system-paths.json is optional and only contains corrections to the heuristic's defaults. New directories Just Work.

---

## Q8: Vendored `acorn` parser dependency — concerning?

**Context** (plan.md Risks R1, Implementation Discoveries): The plan commits to vendoring `acorn` 8.x + `acorn-jsx` + `acorn-typescript` under `scripts/parsers/vendor/acorn/` (~500KB), marked `linguist-vendored=true` in `.gitattributes`, with a regen procedure in CONTRIBUTING.md. Alternative would be regex-only parsing (zero deps, 70% accuracy) which fails the "graceful degradation" hard constraint.

**Question:** Is vendoring acorn the right approach, or should we reconsider?

**Options**

| Option | Description | Implications |
|--------|-------------|--------------|
| A      | Yes — vendor acorn as planned. ~500KB in repo, no install-time npm step, deterministic. Update via documented regen procedure. | Plan's recommendation. Adds repo weight but eliminates network/install fragility. |
| B      | Don't vendor — require `npm install` to pull acorn at smith-install time. Smaller repo, requires node toolchain on user's machine. | Smaller smith-repo. Forces node + npm dependency for every Smith user (most have node already, but not universal). Install-time failures possible. |
| C      | Vendor acorn but commit just the minified single-file build (one ~150KB file, not the full node_modules tree). | Compromise. Cleaner repo footprint. Still self-contained. Slightly more careful regen procedure (minifier step). |
| D      | Drop JS parser support entirely for v1. Python-only manifest. Add JS in a follow-up. | Defers complexity. Loses immediate value for frontend-heavy projects (where the manifest matters most for navigation). Bad. |

**Recommended:** **C** — vendor the minified single-file acorn build. Reasoning: same self-contained property as A, but ~150KB vs ~500KB is a meaningful diff for a distribution repo. Regen procedure is one line (`npx esbuild ... --minify --bundle`). Best of both worlds for the cost of one extra step in CONTRIBUTING.md.

**Answer:** C — vendor minified single-file bundle (~150KB) via esbuild. Regen procedure documented in CONTRIBUTING.md.

---

## Q9: CLAUDE.md template — new file or modify existing `settings/claude-md-template.md`?

**Context** (plan.md Implementation Discoveries #1): smith-repo already has `settings/claude-md-template.md` which IS the global rubric — it's the file that was the source of the user's current `~/.claude/CLAUDE.md` content. The new "Smith Context System" and "File Size Awareness" sections need to go *somewhere*. Adding them to the existing template would change the rubric weights/structure; creating a new file separates concerns but creates two templates for one logical file.

**Question:** Where do the new CLAUDE.md sections live?

**Options**

| Option | Description | Implications |
|--------|-------------|--------------|
| A      | Modify `settings/claude-md-template.md` — add "Smith Context System" and "File Size Awareness" as new top-level sections AFTER the rubric (Rules 1-7), not as new rules. | Single source of truth. The new sections are advisory (how to use context), not graded rules. Doesn't alter the rubric structure. |
| B      | Create `templates/CLAUDE-context-system.template.md` as a separate fragment. `/smith init` concatenates fragments. | Modular. More files. Future-proof if more fragments come along. Premature now. |
| C      | Treat the new sections as Rule 8 + Rule 9 in the rubric — graded by the Haiku critic. | Forces consistent use via grading. Risks: noise (file-size warnings on graders), wrong-tool (the rubric is for response quality, not feature adoption). Probably bad. |

**Recommended:** **A** — modify the existing template, add as advisory sections after the rubric. Reasoning: the new content is operational guidance ("when you see injected context, use it") not behavioral rules to be graded. Keeping it in one file is simpler. The existing template already has non-rule sections (the preamble); this just extends that.

**Answer:** A — modify `settings/claude-md-template.md` directly, append the new sections AFTER the rubric, not as new graded rules.

---

## Q10: Soft-warning frequency for missing-manifest projects?

**Context** (plan.md Risk R6): The soft warning fires when `context-loader.sh` runs but `.smith/index/manifest.md` is absent. Showing it on every single user prompt would be noise. The plan suggests `.smith/vault/.warned-manifest-missing` to track shown state, "fire at most once per session; escalate after 3 sessions."

**Question:** What's the right frequency for the soft warning?

**Options**

| Option | Description | Implications |
|--------|-------------|--------------|
| A      | Once per session (file `.warned-manifest-missing-<session-id>`). Escalate (more prominent banner) after 3 sessions with no manifest built. | Plan's suggestion. Balanced. Adds escalation logic. |
| B      | Once per session, no escalation. The user knows how to run `/smith-index`; nagging is rude. | Simpler. Lower-pressure UX. |
| C      | Every prompt for the first session, then once per session afterwards. Maximum visibility on first encounter. | High discoverability. Annoying after a few prompts on day 1. |
| D      | Once per project lifetime (`.warned-manifest-missing` is committed/persistent). User dismisses once, never sees it again unless they manually `rm` the marker. | Most respectful. Risk: user forgets the manifest exists at all. |

**Recommended:** **B** — once per session, no escalation. Reasoning: the warning's job is informational, not coercive. If the user wants to use Smith without the manifest, that's their choice. One reminder per session is plenty. Escalation logic (A) is over-engineered for a v1 — wait for actual complaints about people forgetting.

**Answer:** B — once per session, no escalation logic.

---

## Question Quality Notes

- Q4 (JS parser implementation) from spec.md Open Questions was resolved in plan.md (acorn). Not included here.
- Q8 (vendoring concern) is a follow-up to that resolution — confirms the storage strategy.
- Q9 and Q10 are new — surfaced by plan.md's Implementation Discoveries.
- 7 questions are from spec.md Open Questions; 3 are new from plan.md.
- All 10 have a recommended answer with reasoning, multiple options with clear tradeoffs, and context that quotes the source artifact.
