---
feature: 20-manifest-fixes
branch: 20-manifest-fixes
created: 2026-06-02
status: ready-to-build
spec: ./spec.md
plan: ./plan.md
data_model: ./data-model.md
research: ./research.md
questions: ./questions.md
builds_on: 19-manifest-system (PR #19, merged 2026-05-21)
---

# Tasks: Manifest System v2 Fixes

Task IDs are sequential. `[P]` marks tasks that share no files with their
phase neighbors and can be executed in parallel. Track tags map to the
spec's Tracks A/B/C and the plan's component groupings. Every path is
relative to the smith-repo project root.

Hard constraints (carried from spec):
- Source code is NEVER modified by any task. All description data lives
  under `.smith/index/` only.
- LLM calls are confined to `scripts/parsers/meta_describe.py` (consumed
  by `/smith-index --describe` and the three smith workflows). Save hook
  stays LLM-free.
- Python invocations use `python3`, not `python`.
- v1 byte-stable: existing `.meta` header fields and parser output fields
  are unchanged; v2 additions are additive only.

---

## Phase 1: Setup (Foundation)

- [X] T001 [setup] Verify v1 test directories `tests/parsers/`, `tests/hooks/`, `tests/skills/`, `tests/e2e/`, `tests/contracts/` exist and contain the v1 baseline tests at tests/
- [X] T002 [P] [setup] Create new skill directory at skills/smith-migrate-system-paths/
- [X] T003 [P] [setup] Create helper script directory at skills/smith-migrate-system-paths/scripts/
- [X] T004 [P] [setup] Copy contract `parser-output-v2.schema.json` from specs/20-manifest-fixes/contracts/ into the consumed location at scripts/parsers/contracts/parser-output-v2.schema.json
- [X] T005 [P] [setup] Copy contract `meta-description-layer.schema.json` from specs/20-manifest-fixes/contracts/ into scripts/parsers/contracts/meta-description-layer.schema.json
- [X] T006 [P] [setup] Copy contract `system-spec-frontmatter.schema.json` from specs/20-manifest-fixes/contracts/ into scripts/parsers/contracts/system-spec-frontmatter.schema.json
- [X] T007 [setup] Confirm `.smith/index/logs/` directory creation is handled at runtime by `mode_describe()` (no on-disk seed needed); add an `os.makedirs(..., exist_ok=True)` requirement to T030 acceptance

---

## Phase 2: Parsers — Stable Method ID (B1, B2)

- [X] T010 [parsers] Add `_stable_method_id(module_path, scope_chain, name, params, return_type)` helper to scripts/parsers/parse-python.py implementing the recipe from research.md §1 (`sha256(f"{module_path}::{scope_chain}::{name}::{canonical_signature}".encode()).hexdigest()[:16]`); canonical_signature joins `params` as `name:type=default` (underscore for missing) and appends `->return_type`
- [X] T011 [parsers] Inject `"id": <hex>` into each entry of `result["functions"]` and into each method under `result["classes"][*]["methods"]` in scripts/parsers/parse-python.py; preserve all existing structural fields including `docstring` if currently emitted (render layer ignores it)
- [X] T012 [P] [parsers] Add `stableMethodId(modulePath, scopeChain, name, params, returnType)` helper to scripts/parsers/parse-js.js using `crypto.createHash('sha256')`; same canonical-signature recipe as T010
- [X] T013 [P] [parsers] Inject `id` field into each entry of `result.functions`, each method under `result.classes[*].methods`, and each exported function in `result.exports` in scripts/parsers/parse-js.js
- [X] T014 [parsers] Update scripts/parsers/contracts/parser-output-v2.schema.json validation rules in the parser-output-v2 contract to require `id` (16-char lowercase hex) on every function/method entry
- [X] T015 [P] [tests] Create tests/parsers/test_stable_id_python.py exercising the id stability matrix from research.md §1 (rename changes id, body edit preserves id, reorder preserves id, param add/remove changes id, return-type change changes id, file move changes id, two files with same fn name produce distinct ids)
- [X] T016 [P] [tests] Create tests/parsers/test_stable_id_js.sh covering the same id stability matrix for JS/TS via scripts/parsers/parse-js.js
- [X] T017 [P] [tests] Add contract test in tests/contracts/test_parser_output_schema.py asserting parser output conforms to scripts/parsers/contracts/parser-output-v2.schema.json (`id` present and well-formed on every function/method)

---

## Phase 3: Resolver — `.specify/systems/` Tier 1 (A4)

- [X] T020 [resolver] Add `_parse_yaml_frontmatter(path)` stdlib helper to scripts/parsers/path-resolver.py per research.md §2; recognized keys: `system`, `status`, `paths`, `also_affects`; malformed → return `{}`
- [X] T021 [resolver] Add `_load_declared_paths(project_root)` function to scripts/parsers/path-resolver.py that scans `<project_root>/.specify/systems/*/spec.md`, parses frontmatter, returns `list[tuple[prefix, system_id]]` sorted by `len(prefix)` descending
- [X] T022 [resolver] Wrap `_load_declared_paths` in `functools.lru_cache(maxsize=8)` keyed by `(project_root, os.stat(systems_dir).st_mtime_ns)` per data-model.md §6.3
- [X] T023 [resolver] Modify `resolve()` in scripts/parsers/path-resolver.py to call tier 1 (declared paths) before existing tier 2 (`system-paths.json`) and tier 3 (heuristic); on tier-1 match return the matched `system_id`
- [X] T024 [resolver] Add defensive filter in `_load_declared_paths` that drops any `paths:` entry containing glob characters (`*?[]{}!`) per data-model.md §8.1 — silent drop with optional `SMITH_DEBUG=1` stderr log
- [X] T025 [P] [tests] Create tests/parsers/test_path_resolver_tier1.py covering: (a) matching prefix returns correct system, (b) `.specify/systems/` absent → falls through to tier 2/3 unchanged from v1, (c) tier-1 hit beats tier-2 + tier-3, (d) longest-prefix wins for `services/auth/` vs `services/auth/oauth/`, (e) entries with glob characters rejected, (f) malformed frontmatter silently ignored
- [X] T026 [P] [tests] Snapshot regression test in tests/e2e/test_resolver_with_specify_systems.sh confirming a fixture project with `.specify/systems/<name>/spec.md` frontmatter produces the expected system bucketing

---

## Phase 4: Shared meta_describe.py Helper (B3, C1, C2 backbone)

- [ ] T030 [meta-describe] Create scripts/parsers/meta_describe.py with module-level `MetaDescription` dataclass per data-model.md §4.2 (fields: `module_description: str | None`, `method_descriptions: dict[str, str]`, `described_against_hash: str`, `described_at: str`)
- [ ] T031 [meta-describe] Add `parse_meta_descriptions(meta_text: str) -> MetaDescription | None` in scripts/parsers/meta_describe.py implementing the line-by-line reader from research.md §5 (harvests `**Description:**`, `Described-Against-Hash:`, `Described-At:`, and per-method `Id:`/`Description:` pairs inside `## Functions`)
- [ ] T032 [meta-describe] Add `_haiku_call(prompt_messages, model, api_key)` private helper in scripts/parsers/meta_describe.py using stdlib `urllib.request` to POST to Anthropic Messages API; reads `ANTHROPIC_API_KEY` from env if `api_key` is None; returns text response; raises on non-2xx
- [ ] T033 [meta-describe] Add `_threshold_filter(parsed, threshold)` private helper returning the subset of method ids that meet `body_lines >= threshold`; also skips single-line getter/setter heuristics per research.md §6 ("Threshold gating")
- [ ] T034 [meta-describe] Add `describe_file(rel_path, source, parsed, *, threshold=5, model="claude-haiku-4-5", api_key=None)` to scripts/parsers/meta_describe.py — bulk path entrypoint; builds per-module prompt (research.md §6) + per-method batch prompt; calls Haiku; returns populated `MetaDescription` with `described_against_hash=sha256(source)` and `described_at=now_iso()`
- [ ] T035 [meta-describe] Add `update_touched(rel_path, source, parsed, existing, touched_method_ids, purpose_shifted, *, threshold=5, model="claude-haiku-4-5", api_key=None)` to scripts/parsers/meta_describe.py per data-model.md §4.1; regenerates only touched ids, passes through untouched `existing.method_descriptions`, regenerates module description only when `purpose_shifted` is True
- [ ] T036 [meta-describe] Add `render_description_block(desc: MetaDescription) -> dict` to scripts/parsers/meta_describe.py returning the `existing_descriptions` dict shape consumed by `render_meta(...)` (keys: `module_description`, `described_against_hash`, `described_at`, `method_descriptions`)
- [ ] T037 [P] [tests] Create tests/parsers/test_meta_describe.py covering: parse round-trip (parse → render → parse identity), threshold filtering excludes <5-line methods, `update_touched` passes through untouched descriptions, `update_touched` regenerates module description only when `purpose_shifted=True`, mocked Haiku call asserted with expected prompt shape

---

## Phase 5: /smith-index --describe Mode (C2)

- [ ] T040 [smith-index] Add CLI args to scripts/smith-index/run.py: `--describe` (store_true), `--batch-size` (int, default 20), `--llm-batch-size` (int, default 10), `--threshold` (int, default 5), `--system` (str, optional), `--resume` (store_true)
- [ ] T041 [smith-index] Modify `render_meta(rel_path, parsed, hash_hex, existing_descriptions=None)` in scripts/smith-index/run.py per data-model.md §2.1 and plan.md "B6 Render Parity": when `existing_descriptions` is None, omit description-layer lines; when present, emit `**Description:**`, `Described-Against-Hash:`, `Described-At:` after `Hash:` and before the blank section separator
- [ ] T042 [smith-index] Modify `render_meta` per-function rendering in scripts/smith-index/run.py to emit `Id: <hex>` and (when present in `existing_descriptions.method_descriptions`) `Description: <text>` as two indented lines under each function bullet; drop emission of any v1 parser-derived docstring line
- [ ] T043 [smith-index] Modify `render_system_manifest()` in scripts/smith-index/run.py to add a Description column to the file-listing table per data-model.md §B4; cell value is per-module description from each file's `.meta` or empty string when absent; preserve the existing ≤80-line manifest cap
- [ ] T044 [smith-index] Implement `mode_describe(project_root, args)` in scripts/smith-index/run.py per plan.md "C2 — /smith-index --describe" and data-model.md §7: walk source files, optional `--system` filter, hash-cache skip (Hash == Described-Against-Hash AND description present), group into approval batches of `--batch-size`, per-batch operator prompt (Y/n/q/list with per-file reject)
- [ ] T045 [smith-index] Inside `mode_describe`, sub-batch each approved batch into LLM batches of `--llm-batch-size`; call `meta_describe.describe_file(...)` per file (or parallel via `concurrent.futures.ThreadPoolExecutor`); merge result into existing `.meta`'s description layer, call `render_meta(..., existing_descriptions=...)`, atomic-write
- [ ] T046 [smith-index] Add JSONL logging to `mode_describe`: open log at `.smith/index/logs/smith-index-describe-<YYYYMMDDTHHMMSSZ>.jsonl`; append one record per processed file with schema from data-model.md §7.2 (`timestamp`, `item_id`, `stage`, `status`, `error`, `method_count`, `module_chars`, `batch_index`)
- [ ] T047 [smith-index] Add checkpoint write in `mode_describe` after each LLM batch to `.smith/index/.smith-index-describe-checkpoint.json` per data-model.md §7.1 (overwrite-each-batch semantics)
- [ ] T048 [smith-index] Implement `--resume` in `mode_describe`: locate the most recent `smith-index-describe-*.jsonl` log; build set of `item_id` where `status=="ok"` AND `stage=="describe"`; union with checkpoint's `processed_files`; apply as skip set before hash-cache filter (triple-protection per data-model.md §7.3)
- [ ] T049 [smith-index] Add final-summary stdout block in `mode_describe` per data-model.md §7.4 (total, succeeded, failed, skipped, elapsed, failure list, log path); print on completion or on `KeyboardInterrupt`/abort
- [ ] T050 [P] [tests] Create tests/skills/test_smith_index_describe.sh exercising: fresh `--describe` run on tests/fixtures/sample-project/, `--resume` continues from a partial checkpoint, hash-cache skips unchanged files, batch-size flag honored, JSONL log shape matches schema

---

## Phase 6: Save-Hook Description Preservation (B6)

- [ ] T060 [hooks] Modify hooks/manifest-updater-lib.py to read existing `.meta` (if present) before writing; call `run_mod.parse_existing_descriptions(meta_text)` (re-exported from scripts/smith-index/run.py or imported from scripts/parsers/meta_describe.py) to extract the description layer
- [ ] T061 [hooks] Update the `render_meta(...)` call site in hooks/manifest-updater-lib.py to pass `existing_descriptions=<extracted>` so the description layer is spliced verbatim into the new `.meta`; structural fields and `Hash:` are recomputed; `Described-Against-Hash:` is preserved (never overwritten by the save hook)
- [ ] T062 [hooks] Verify `_atomic_write()` in hooks/manifest-updater-lib.py is unchanged and that the tempfile→rename window does not expose a partial-write state per research.md §8
- [ ] T063 [P] [tests] Create tests/hooks/test_save_preserves_descriptions.sh: seed a `.meta` with a known description layer, simulate a file Write, run hooks/manifest-updater.sh, assert `**Description:**`/per-function `Description:`/`Described-Against-Hash:`/`Described-At:` are byte-identical and `Hash:` was updated
- [ ] T064 [P] [tests] Add staleness-detection assertion to tests/hooks/test_save_preserves_descriptions.sh that confirms after a body edit, `Hash != Described-Against-Hash` (the stale signal is detectable without any extra marker)

---

## Phase 7: Three Smith Workflows — In-Context .meta Description Update (C1)

- [ ] T070 [workflows] Modify skills/smith-new/SKILL.md to add a new sub-step after the Write/Edit phase that (a) re-parses the touched file via parse-python.py or parse-js.js, (b) diffs current method ids against existing `.meta`'s `Id:` list to compute touched ids, (c) computes the `purpose_shifted` heuristic (new export added OR new class added OR >50% of methods are new), (d) shells out to `python3 scripts/parsers/meta_describe.py update-touched ...` or invokes the helper inline, (e) writes the updated `.meta` via render_meta
- [ ] T071 [workflows] Apply the same workflow sub-step to skills/smith-bugfix/SKILL.md
- [ ] T072 [workflows] Apply the same workflow sub-step to skills/smith-debug/SKILL.md
- [ ] T073 [meta-describe] Add a CLI entrypoint to scripts/parsers/meta_describe.py supporting `python3 scripts/parsers/meta_describe.py update-touched --rel-path <p> --touched-ids <comma-list> --purpose-shifted <true|false>` so the workflow skills can invoke it without writing a wrapper script

---

## Phase 8: /smith-build Coverage Flag (C1.5)

- [ ] T080 [smith-build] Modify skills/smith-build/SKILL.md PR-description generation step to add a "Description Coverage Warnings" block per data-model.md §9.2; algorithm: `git diff main --name-only` → filter to source extensions → for each file, parse, intersect diff hunks with each function's line range to compute touched ids, look up Id in `.meta`'s `## Functions` section, collect ids missing descriptions
- [ ] T081 [smith-build] Format the warning section in skills/smith-build/SKILL.md per data-model.md §9.2 example output: header line with count, bullet per missing method (`<file>::<class>::<method>` or `<file>::<function>`), trailing CTA suggesting `/smith-index --describe --system <name>`
- [ ] T082 [smith-build] Confirm in skills/smith-build/SKILL.md that the coverage flag is NEVER blocking — PR opens regardless; if `git diff main` returns nothing, the section is a no-op (data-model.md §9.3)
- [ ] T083 [P] [tests] Create tests/skills/test_smith_build_coverage_flag.sh with a synthetic diff containing one method with a description and one without; assert PR body lists only the missing-description method

---

## Phase 9: A1 + A2 — system-spec-template + /smith init Wiring

- [ ] T090 [init] Create skills/smith/templates/system-spec-template.md per plan.md "A1 — system-spec-template.md" with YAML frontmatter (`system`, `status`, `paths`, `also_affects`) and prose body sections (Purpose, Owners, Files & Components, Interfaces, Dependencies); body is free-form
- [ ] T091 [init] Modify skills/smith/SKILL.md to add Phase 4.X "Scaffold System Specs (Optional)" sub-step per plan.md "A2 — /smith init Sub-Step": prompt operator yes/skip, on yes prompt for comma-separated system ids, for each id prompt for `paths:` entries one-at-a-time terminating on empty input, copy template to `.specify/systems/<id>/spec.md` with substitutions
- [ ] T092 [init] Add validation in the A2 sub-step prose to reject `paths:` entries containing glob characters (`*?[]{}!`) with re-prompt and to auto-append trailing `/` per data-model.md §5.3
- [ ] T093 [P] [tests] Create tests/skills/test_smith_init_system_specs.sh exercising the scaffold sub-step end-to-end: simulated operator input creates two system specs with frontmatter, files written under `.specify/systems/<name>/spec.md`, frontmatter conforms to system-spec-frontmatter.schema.json

---

## Phase 10: A3 — /smith-migrate-system-paths Skill

- [ ] T100 [A3] Create skills/smith-migrate-system-paths/SKILL.md (full skill — frontmatter + prose instructions) per plan.md "A3 — /smith-migrate-system-paths"; flow: enumerate `.specify/systems/*/spec.md`, skip files already having non-empty `paths:` frontmatter, run propose_paths.py, present per-system proposal, on accept inject frontmatter ABOVE existing body preserving body verbatim
- [ ] T101 [A3] Create skills/smith-migrate-system-paths/scripts/propose_paths.py implementing the heuristic from research.md §4: regex matchers (backticked dir, backticked file, code-fence file, bullet path, `services/<X>/`, `backend/<X>/`, `frontend/<X>/`, `apps/<X>/`, `packages/<X>/`), score = `Σ position_weight` where `position_weight = max(0.3, 1.0 - line_index/total_lines)`, return top-N (default 5)
- [ ] T102 [A3] Add validation step in propose_paths.py output: drop any candidate prefix containing glob characters before presenting; auto-append trailing `/` to candidates lacking it
- [ ] T103 [A3] Add frontmatter-injection routine in skills/smith-migrate-system-paths/SKILL.md prose: if file already has `---` ... `---` frontmatter block but no `paths:`, insert only the `paths:` field inside the existing block; if no frontmatter, prepend a fresh block before any prose, preserving the body verbatim including blank lines
- [ ] T104 [A3] Add summary-report step at end of A3 skill prose per spec.md A3: lines listing migrated count, skipped-already-has-paths count, skipped-by-user count
- [ ] T105 [P] [tests] Create tests/skills/test_smith_migrate_system_paths.sh with a fixture project containing hand-authored prose system specs (no YAML frontmatter): run A3, assert per-system proposal table is generated, simulated accept-all writes frontmatter above body, body bytes are unchanged

---

## Phase 11: Integration + E2E Tests

- [ ] T110 [P] [tests] Create tests/e2e/test_full_describe_flow.sh: use a sample-project fixture, run `python3 scripts/smith-index/run.py --describe`, assert descriptions populated in `.meta`, then simulate a smith-bugfix edit on one file via a stub workflow invocation, assert only touched method descriptions updated and untouched stay byte-identical
- [ ] T111 [P] [tests] Create tests/e2e/test_save_hook_preservation.sh: seed descriptions, run a sequence of file edits through hooks/manifest-updater.sh, assert description layer preserved across each save and `Hash != Described-Against-Hash` after each edit
- [ ] T112 [P] [tests] Create tests/e2e/test_migration_paths.sh: synthetic project mimicking armory's prose system specs, run `/smith-migrate-system-paths` end-to-end (simulated operator input via heredoc), assert frontmatter written correctly, then run path-resolver against fixture files and confirm correct system bucketing
- [ ] T113 [tests] Update tests/e2e/run-all.sh to include all new tests from Phases 2-11 in the run order

---

## Phase 12: Docs

- [ ] T120 [docs] Update CHANGELOG.md with a v2 "Unreleased" entry covering: Track A (`.specify/systems/` tier 1 + system-spec template + `/smith-migrate-system-paths`), Track B (LLM description layer in `.meta` + stable method id), Track C (in-context updates + `/smith-index --describe` + coverage flag); call out additive-only `.meta` schema and the operator migration path (`/smith-migrate-system-paths` → `/smith-index` → optional `/smith-index --describe`)
- [ ] T121 [docs] Update docs/manifest-system.md to document: (a) `.meta` description layer fields and absence semantics per data-model.md §2, (b) `/smith-index --describe` CLI + Rule 4 checkpoint/JSONL/resume per data-model.md §7, (c) staleness detection via hash mismatch per data-model.md §2.4, (d) resolver tier order with new tier 1 per plan.md Architecture Overview, (e) `/smith-migrate-system-paths` operator workflow
- [ ] T122 [P] [docs] Update README.md only if needed (likely a single bullet under "What's new in v2"); skip if README does not currently reference manifest internals

---

## Dependencies Summary

- Phase 1 (T001-T007) must complete before any subsequent phase.
- Phase 2 (parsers + stable id) is a hard prerequisite for Phase 4 (meta_describe consumes id), Phase 5 (smith-index --describe consumes id), Phase 6 (save hook renders id), Phase 7 (workflows diff touched ids), and Phase 8 (build coverage looks up ids).
- Phase 3 (resolver tier 1) is independent of Phases 4-8; can land in parallel.
- Phase 4 (meta_describe.py) is a hard prerequisite for Phase 5, Phase 6 (parser harvests via shared helper), and Phase 7.
- Phase 5 (smith-index --describe) depends on Phase 4.
- Phase 6 (save hook) depends on Phase 4 (parse_existing_descriptions) and Phase 5's render_meta updates.
- Phase 7 (workflows) depends on Phase 4 and Phase 6 (preserve-on-save invariant must hold before workflows rely on it).
- Phase 8 (build coverage) depends on Phase 2 (touched-id computation).
- Phase 9 (A1/A2) depends only on Phase 1; can run in parallel with Phases 2-8.
- Phase 10 (A3) depends only on Phase 1 + system-spec-frontmatter contract from Phase 1; can run in parallel.
- Phase 11 (integration) depends on Phases 2-10.
- Phase 12 (docs) is last.

---

2026-06-02 — 20-manifest-fixes
