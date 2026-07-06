---
feature: 32-smith-research
branch: smith-research
created: 2026-07-06
status: in-progress
---

# Implementation Plan — smith-research

## Architecture overview

Two layers, cleanly separated:

```
skills/smith-research/
├── SKILL.md                         # ORCHESTRATOR (LLM): phases, gates, subagent dispatch
└── scripts/
    ├── requirements.txt             # pinned deps (D1 deviation)
    ├── start-playwright-server.sh   # host-side pw run-server :9224 (from R3)
    ├── run.py                       # CLI entrypoint (contracts/cli.md)
    └── smith_research/              # DETERMINISTIC ENGINE (zero LLM)
        ├── __init__.py
        ├── config.py                # copy+decouple armory config; localhost defaults; thresholds (N1)
        ├── models.py                # copy VERBATIM from armory (WebPage/CrawlResult/CrawlSummary) — pristine, provenance-honest (N5)
        ├── models_research.py       # net-new: Claim (atomic), BackgroundSource, LedgerEntry, RunState
        ├── discover.py              # sitemap recursion (reuse _find_locs) + robots + BFS
        ├── extractor.py             # copy+decouple (httpx→trafilatura→Playwright fallback)
        ├── browser.py               # shared warmed Playwright context: warmed_fetch(url, warmup_origin) — ONE helper reused by extractor render-fallback, serp_scraper, reddit_collector (N3)
        ├── crawler.py               # REWRITE orchestration: fetch→extract→save(md/html/png)→ledger→ckpt
        ├── chunker.py               # heading-aware chunking (net-new)
        ├── embedder.py              # copy verbatim (Ollama nomic-embed-text)
        ├── qdrant_store.py          # copy+parameterize (collection/dim/payload; keep UUID5 ids)
        ├── ledger.py                # SQLite crawl-state store (net-new; replaces pg_store)
        ├── classifier.py            # copy+generalize URL→content_type
        ├── checkpoint.py            # copy verbatim
        ├── logger.py                # copy verbatim (Rule-4 JSONL)
        ├── reddit_collector.py      # copy verbatim + extend /search.json (warmed context)
        ├── reddit_url.py            # copy verbatim
        ├── serp_scraper.py          # net-new: Google/Bing via warmed context
        ├── bg_research.py           # net-new: topic×engine orchestrator + depth + source_tier assignment
        ├── retrieval.py             # net-new: retrieve / evidence-check (read-only, generous-k both-collection)
        ├── decompose.py             # net-new: sentence↔citation parsing for the gate (deterministic; LLM claim-decomposition dispatched by SKILL.md)
        └── verify_report.py         # net-new: DETERMINISTIC closing gate — report ⊆ supported-claims (B1, no LLM)
```

Report synthesis (`report.py`) and verification are **not** engine scripts —
they are SKILL.md phases that call `retrieve`/`evidence-check`/`record-claim`
CLI subcommands and dispatch Task subagents. This keeps every LLM interaction in
the orchestrator layer, satisfying the extraction≠interpretation guarantee.

## Phase sequence (build order)

Each phase is independently testable. Build + test bottom-up so the deterministic
core is proven before the LLM layer sits on top.

### P0 — Skeleton & bootstrap
- Create `skills/smith-research/` tree, `requirements.txt`,
  `start-playwright-server.sh` (adapt R3, port 9224).
- `config.py`, `models.py` (copy), `run.py` argparse skeleton, `status`.
- **Test:** venv installs; `run.py status` errors cleanly when prereqs down.

### P1 — Discovery (FR-1..4)
- `discover.py`: reuse armory `_find_locs`/sitemap recursion; add robots.txt
  Sitemap: parsing + disallow honoring; BFS fallback; same-registrable-domain
  filter (tldextract or public-suffix logic); dedup. Seed ledger.
- **Test:** against a fixture sitemap + a sitemapindex; BFS fallback on a
  sitemap-less fixture; domain filter rejects off-domain links.

### P2 — Ledger + storage primitives (FR-11)
- `ledger.py` (SQLite schema from data-model.md); `checkpoint.py`,
  `logger.py` (copy). Content-hash change detection.
- **Test:** insert/resume/dirty-detection; done-status filtering.

### P3 — Crawl + extract (FR-5..8)
- `browser.py`: connect to WS server, build warmed context (UA/locale), homepage
  warmup helper (from R4). `extractor.py` (copy+decouple). `crawler.py` rewrite:
  orchestrate fetch→extract→save md/html/png→ledger→checkpoint→log, concurrency
  cap + backoff + politeness.
- **Test:** crawl a small live/fixture site; resume skips done; screenshot+html+md
  written; 429 backoff path; blocked fetch logged not dropped (SC-6).

### P4 — Index (FR-9,10)
- `chunker.py` (heading-aware); `embedder.py` (copy); `qdrant_store.py`
  (copy+parameterize). `index` subcommand upserts `_site` collection.
- **Test:** deterministic point IDs (re-index = no dupes, SC-4); retrieval
  returns stored chunks with URLs (SC-5).

### P5 — Background research (FR-12..14)
- `serp_scraper.py` (Google/Bing via warmed context, parse results defensively);
  `reddit_collector.py` copy + `/search.json` extension; `bg_research.py`
  topic×engine×depth orchestrator; embed into `_background`.
- **Test:** depth flag changes query count; blocked SERP logged+retried; Reddit
  warmup returns JSON not block page; sources stored + citable.

### P6 — Retrieval + evidence API + DETERMINISTIC GATE (FR-16, FR-18, FR-18a,b)
- `retrieval.py`: `retrieve`, `evidence-check` (generous k over BOTH collections
  unfiltered — FR-18b), `record-claim` (atomic claim + inline chunk_texts +
  source_tier — S1).
- `decompose.py` + `verify_report.py`: the **LLM-free** `verify-report` gate —
  parse final report.md, assert every sentence maps to a `verdict=supported`
  claim row with resolvable inline chunk; exit 4 on any violation (B1). Built in
  P6, BEFORE the LLM orchestration, so the correctness backstop lives + is
  testable in the deterministic layer (N4).
- **Test:** evidence-check returns candidates across both collections; an absent
  claim yields no entailing chunk. `verify-report` FAILS a report with an
  invented uncited sentence and PASSES one where every sentence is a supported
  claim. Idempotent.

### P7 — SKILL.md orchestrator (FR-15..22)
- Phase 0 (bootstrap+prereqs), 1 discover, 2 crawl, 3 index, 4 background,
  5 synthesize (parallel section subagents via `retrieve`, hedging by
  source_tier), 6 verify (decompose→per-claim `evidence-check`→entailment+
  contradiction verdict via subagents→strip/flag/`record-claim`), 6b run the
  deterministic `verify-report` gate (run FAILS if it reports violations),
  7 emit + teardown pw-server.
- Query mode for US-3 (ad-hoc later questioning).
- Vault logging section; natural-language triggers; deviation notes; macOS TCC
  note; iCloud-sync/PII + retention warning (S5); robots-vs-stealth policy (S4).

### P8 — Docs + install
- `skills/smith-research/README.md` (prereqs, deviations, usage, quickstart.md).
- Verify `install.sh`/`/smith-update` picks up the new skill.

## Subagent design (SKILL.md, P7)

| Phase | Subagent | Input | Output contract |
|-------|----------|-------|-----------------|
| Synthesize | one per section (parallel) | ONLY chunks from `retrieve` for that section + source URLs + source_tier | section markdown; every sentence cited; no outside knowledge; social_unverified hedged, never bare fact (G8) |
| Decompose | one per section | section markdown | list of ATOMIC claims, each with its inline citation(s) — compound sentences split so no fact rides along uncounted (B1.2) |
| Verify | one per atomic claim (batched) | claim + `evidence-check` candidates | verdict ∈ {supported, unverified, contradicted}; checks ENTAILMENT **and** non-contradiction |
| Completeness | one final critic | full report + coverage of the 8 sections | gaps / uncited claims to re-run |

Then the **deterministic** `verify-report` gate runs (no subagent) and the run
fails on any violation — this is the actual enforcement, independent of subagent
judgment (B1).

Synthesis prompt: "Use ONLY the provided sources. If a fact is not in the
sources, do not state it. Cite every claim as [url]. For any source marked
social_unverified, attribute and hedge — never state as bare fact." Verifier
prompt (adversarial): "Default to UNVERIFIED. Mark supported ONLY if a provided
chunk directly ENTAILS the claim; mark CONTRADICTED if a chunk refutes it.
Topical similarity is NOT support."

## Determinism / no-hallucination enforcement (SC-2,3)
1. Engine scripts: no LLM, idempotent, everything logged.
2. Synthesis: retrieval-grounded, cited, no model memory.
3. Verification: every claim re-checked; `evidence.jsonl` = full audit trail.

## Risks & mitigations
- **SERP layout drift / blocking** → defensive parsers that log gaps (never
  fabricate); warmed context + pacing + backoff; politeness tiers; proxy opt-in.
- **`~/Documents` TCC prompt (macOS)** → documented; Phase 0 does a probe write.
- **Large sites** → concurrency cap + checkpoint/resume; `--limit` for smoke runs.
- **Ollama/Qdrant down** → Phase 0 fails fast with remediation message (exit 2).
- **Port 9224 in use** → idempotent server script skips/reuses; configurable.

## Testing strategy
- Engine unit tests under `skills/smith-research/scripts/tests/` (pytest, skill
  venv): discovery, ledger, chunker, qdrant idempotency, evidence-check, reddit
  URL/warmup, serp parser tolerance. Fixtures for sitemaps/HTML.
- One end-to-end smoke run against a small real domain (with `--limit`) as the
  acceptance gate, verifying SC-1..7 manually + the zero-unsupported-claims check.

## Out of scope for v1
- Proxy/residential evasion (tier stubbed, off).
- Screenshot vision-captioning (llava available; deferred).
- Scheduled/recurring runs.
