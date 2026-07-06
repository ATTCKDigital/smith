---
feature: 32-smith-research
created: 2026-07-06
---

# CLI Contract — smith_research

The deterministic engine is a Python package invoked by the SKILL.md orchestrator.
All subcommands are pure/mechanical (no LLM). LLM synthesis + verification are
driven by the SKILL.md via Task subagents, NOT by this CLI.

Invocation: `python3 skills/smith-research/scripts/run.py <subcommand> [flags]`
(the skill activates its venv first).

## Global flags
```
--domain <domain>                 target (required for run/discover/crawl/index/background)
--run-dir <path>                  explicit workspace (default: derived under $SMITH_RESEARCH_OUTPUT_DIR)
--output-root <path>              default ~/Documents/smith-research (env: SMITH_RESEARCH_OUTPUT_DIR)
--qdrant-url <url>                default http://localhost:6333
--ollama-url <url>                default http://localhost:11434
--embedding-model <name>          default nomic-embed-text
--playwright-ws <url>             default ws://localhost:9224/
--politeness {strict,normal,aggressive}   default normal
--json                            emit machine-readable result to stdout
```

## Subcommands

### `discover --domain D`
Build the URL frontier (sitemap recursion → robots Sitemap: → BFS fallback),
same-domain filter + dedup. Writes `urls.jsonl`, seeds `ledger.pages` as pending.
→ JSON: `{run_dir, discovered, sources: {sitemap, robots, bfs}}`

### `crawl --domain D [--resume] [--limit N] [--concurrency N] [--delay S]`
Fetch every pending/errored URL (static→render fallback), extract content+meta,
write pages/raw_html/screenshots, update ledger + checkpoint + JSONL log.
Idempotent; `--resume` skips {ok,low_content}.
→ JSON: `CrawlSummary {discovered, succeeded, failed, skipped, low_content}`

### `index --domain D [--resume]`
Heading-aware chunk of crawled pages, embed via Ollama, upsert to
`..._site` collection with deterministic point IDs. Records point_ids in ledger.
→ JSON: `{pages_indexed, chunks_upserted, collection}`

### `background --domain D [--depth {quick,standard,thorough}] [--topics ...]`
Per topic × engine (google,bing,reddit): run queries via warmed Playwright
context, capture SERP + deep-fetch top results, assign `source_tier` at capture
(first_party / social_unverified / reputable_secondary by host), store raw +
embed into `..._background`. Depth controls query-angle count + fetch depth.
→ JSON: `{sources_captured, chunks_upserted, per_topic: {...}, per_tier: {...}}`

### `retrieve --domain D --query Q [--collection {site,background,both}] [--topic T] [--k N]`
Read-only semantic retrieval over a run's collections. Returns chunks + source
URLs. Powers both the synthesis subagents (via the skill) and ad-hoc later
questioning (US-3).
→ JSON: `{results: [{score, text, url, section_anchor, ...}]}`

### `evidence-check --domain D --claim "..." [--k N]`
Read-only: retrieve **candidate** supporting chunks for a single atomic claim.
Defaults to a GENEROUS k over **both** collections **unfiltered** (FR-18b/S2) so
retrieval choice can never falsely fail a true claim. Returns candidate chunks +
their `source_tier` + text + best_score. NOTE: this returns *candidates only* —
the entailment/contradiction decision is made by the verifier subagent, not by a
similarity threshold (best_score is advisory, never an auto-pass; B1).
→ JSON: `{candidates: [{text, url, source_tier, score, chunk_id}], best_score}`

### `record-claim --domain D --section S --claim "..." --verdict V --source-urls ... --chunk-ids ... --chunk-texts ... --source-tier T`
Append a verified ATOMIC claim to `claims` table + `evidence.jsonl`. Persists the
inline `chunk_texts` (self-contained audit, S1). `V ∈ {supported, unverified,
contradicted, removed}`. Write-only bookkeeping.

### `verify-report --domain D`  ← DETERMINISTIC GATE (no LLM), B1
Parse the FINAL `report.md`: extract every declarative sentence + its inline
citation(s). Assert each maps to a `claims` row with `verdict=supported` AND a
resolvable chunk (present in `chunk_texts`). List every orphan/uncited/unsupported
sentence. This is the mechanical backstop that makes SC-3 real independent of
subagent behavior. Exit 4 if any violation.
→ JSON: `{sentences, cited, supported, violations: [{sentence, reason}]}`

### `status --domain D`
Summarize ledger + collections + `run_state.phase` + per-section synthesis/verify
status (for resume decisions, incl. mid-synthesis resume — S3).

## Exit codes
`0` success · `2` prerequisite missing (qdrant/ollama/playwright down) ·
`3` discovery found zero URLs · `4` verification/partial failure
(`verify-report` found uncited/unsupported sentences, or some URLs reached a
terminal-unsuccessful status — see log) · `1` unexpected error.

## Determinism guarantees
- No subcommand calls an LLM.
- Re-running any subcommand is idempotent (deterministic point IDs, ledger
  dedup, content-hash change detection).
- Every processed item emits exactly one JSONL log record; nothing is dropped
  without a terminal ledger status.
