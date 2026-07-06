---
feature: 32-smith-research
created: 2026-07-06
---

# Research — smith-research

Evidence gathered before planning. All findings are grounded in actual code /
environment probes, not assumptions.

## R1 — Environment (verified present, 2026-07-06)

| Prereq | State | Note |
|--------|-------|------|
| Qdrant | image `qdrant/qdrant:latest` pulled (284MB); port 6333 free; server DOWN | one `docker run` to start |
| Ollama | running; models: `nomic-embed-text`, `llama3.1:8b`, `llava:13b`, `dennis-voice` | embed model already present (768-dim) |
| Python | 3.14 (homebrew); `playwright 1.60`, `httpx 0.28`, `qdrant-client 1.17`, `tenacity 9.1` installed | need to add `trafilatura`, `beautifulsoup4` in skill venv |
| Node | v22.17; `npx playwright 1.61` available | used for `playwright run-server` |
| `~/Documents` | exists, writable, `drwx------` | may trigger one-time macOS TCC prompt |

## R2 — Armory reuse manifest (from read-only audit)

Source: `~/Projects/armory/services/website-indexer/website_indexer/` and
`~/Projects/armory/services/trend-intelligence/`.

### Copy verbatim (zero armory coupling)
| File | Purpose | Contract to preserve |
|------|---------|----------------------|
| `embedder.py` | Ollama `/api/embed`, `nomic-embed-text`, `search_document:` prefix, 768-dim, 3× retry backoff | default base_url → `localhost:11434` (was `host.docker.internal`) |
| `models.py` | `WebPage`, `CrawlResult`, `CrawlSummary` dataclasses | — |
| `checkpoint.py` | JSONL checkpoint; done = {ok, low_content}; errors retried | resume contract |
| `logger.py` | JSONL audit log, one record per URL | Rule-4 log shape |
| `classifier.py` | URL→content_type pure fn | re-map slugs generically (not attck.com-specific) |
| `reddit_collector.py` | Playwright warmed-context Reddit fetch + Cloudflare evasion | evasion technique (see R4) |
| `reddit_url.py` | URL validation | — |

### Copy + decouple
| File | Strip / parameterize |
|------|----------------------|
| `extractor.py` | remove `IndexerConfig` dep; pass fetch config as params. KEEP: httpx→trafilatura→Playwright fallback, title extraction, truncation, low-content flag. Already has httpx-first + Playwright-render-fallback. |
| `qdrant_store.py` | parameterize collection name + vector dim + payload schema (was hardcoded `website_content`/768/COSINE + UUID5-from-URL point IDs). KEEP deterministic UUID5 point IDs (idempotent re-crawl). |
| `config.py` | rename to skill config; `localhost` defaults; add SMITH_RESEARCH_OUTPUT_DIR, depth, politeness. |

### Rewrite (too coupled / project-specific)
- `crawler.py` orchestration — the loop couples discovery+embed+store+log+checkpoint via DI. Reuse only `discover_urls()` sitemap-recursion logic + `_find_locs()`; rewrite the loop as a clean orchestrator that also writes raw HTML + screenshots (armory didn't).
- `cli.py` — rewrite for smith-research subcommands.

### Drop
- `pg_store.py` — replaced by SQLite `ledger.py` (D3).

### Deps (from armory pyproject)
`httpx, qdrant-client, trafilatura, playwright, beautifulsoup4` (+ `tenacity`
already used). Drop `psycopg2-binary` (no Postgres).

## R3 — Playwright server pattern (from armory `scripts/start-playwright-server.sh`)

Armory runs a **host-side** `npx playwright run-server --port 9223 --path /`
(idempotent: skip if port listening; kill stale pid; wait up to 10s), listening
on `ws://host.docker.internal:9223/`. Rationale (quoted): bundling Chromium in
the Docker image would blow Colima's memory budget.

**Adaptation:** smith-research runs natively (not in Docker), so:
- own script `scripts/start-playwright-server.sh`, **port 9224** (avoid armory's
  9223 collision), connect URL `ws://localhost:9224/`.
- pid + log in the run workspace; idempotent start; teardown at run end.

## R4 — Reddit / SERP anti-bot technique (from `reddit_collector.py`)

The evasion that "successfully prevents bot-detection":
1. Connect to a **real Chrome** via the Playwright WS server (genuine TLS
   fingerprint) — not raw httpx.
2. **Homepage warm-up**: `page.goto("https://www.reddit.com/")`, wait 3s for the
   JS/Cloudflare challenge to set the clearance cookie, **then** fetch the target
   (`/…/.json`). Without warm-up, Cloudflare returns a ~143-byte block page.
3. Real Chrome User-Agent + `locale="en-US"`.
4. Uses the `.json` endpoint (structured) rather than parsing HTML.

**Extension for research:** the collector only hits `/rising/.json`. We add a
Reddit **search** path (`/search.json?q=…`) reusing the identical warmed-context
+ homepage-warmup flow. Same evasion, new endpoint. SERP scraping (Google/Bing)
reuses the same warmed real-Chrome context + human pacing + backoff.

## R5 — smith-repo conventions (from repo audit)

- Skills live in `skills/<name>/SKILL.md`; script-backed skills keep scripts in
  `skills/<name>/scripts/` and invoke `python3 skills/<name>/scripts/<x>.py`.
- Install via `scripts/install.sh` (copies `skills/smith*` → `~/.claude/skills/`)
  or `/smith-update`. A new `skills/smith-research/` is auto-picked-up.
- Specs use flat `specs/NN-name/` with spec/plan/research/data-model/
  contracts/quickstart/questions/checklists. (This feature = 32.)
- Convention is stdlib-only scripts; our venv is a documented deviation (D1).

## R6 — No-hallucination architecture (design rationale)

Three structural guarantees, none relying on model good behavior:
1. **Extraction ≠ interpretation.** All capture is deterministic Python; no LLM
   touches raw pages.
2. **Grounded synthesis.** Section subagents receive ONLY retrieved chunks +
   their source URLs; prompt forbids outside knowledge; every sentence cited.
3. **Adversarial verification.** A separate verifier re-retrieves evidence for
   each claim; unsupported → stripped/`[UNVERIFIED]`. `evidence.jsonl` makes the
   whole report auditable claim-by-claim.
