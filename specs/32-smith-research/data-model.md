---
feature: 32-smith-research
created: 2026-07-06
---

# Data Model — smith-research

Two persistence layers: (1) a portable **SQLite ledger** + on-disk archive under
`~/Documents` (the durable record), and (2) **Qdrant** collections (the query
index, rebuildable from the archive).

## Run workspace layout

```
~/Documents/smith-research/<domain>/<YYYYMMDD-HHMMSS>/
├── run.json                 # run metadata (domain, ts, flags, collection names, versions)
├── urls.jsonl               # discovered frontier (one {url, source} per line)
├── ledger.sqlite            # crawl-state ledger (resume source of truth)
├── pages/<sha1>.md          # cleaned markdown per page
├── raw_html/<sha1>.html     # verbatim HTML per page
├── screenshots/<sha1>.png   # full-page screenshot per page
├── background/
│   ├── serp/<engine>-<qhash>.json   # raw SERP capture
│   ├── reddit/<qhash>.json          # raw Reddit search/results
│   └── fetched/<sha1>.md            # deep-fetched background pages
├── logs/<stage>-<ts>.jsonl  # Rule-4 structured logs (discover/crawl/index/bg/synth/verify)
├── checkpoint.json          # crawl resume checkpoint
├── evidence.jsonl           # claim → source URL + chunk id (audit trail)
└── report.md                # final unified cited report (progressive)
```

`<sha1>` = SHA-1 of the URL (stable filename, dedup-friendly).

## SQLite ledger schema (`ledger.sqlite`)

```sql
CREATE TABLE pages (
    url            TEXT PRIMARY KEY,
    source         TEXT,              -- sitemap | robots | bfs | seed
    status         TEXT NOT NULL,     -- pending|ok|low_content|error|blocked|failed_terminal|skipped
    http_status    INTEGER,
    content_sha256 TEXT,              -- change-detection for re-runs
    content_type   TEXT,              -- classifier output
    title          TEXT,
    word_count     INTEGER,
    retry_count    INTEGER NOT NULL DEFAULT 0,  -- B3: promote error->failed_terminal at cap; block->blocked
    point_ids      TEXT,              -- JSON array of qdrant point ids for this url
    md_path        TEXT,
    html_path      TEXT,
    screenshot_path TEXT,
    error          TEXT,
    first_seen_at  TEXT NOT NULL,
    last_seen_at   TEXT NOT NULL
);
CREATE INDEX ix_pages_status ON pages(status);

-- Resume semantics (B3):
--   done (skip on resume)        = {ok, low_content}
--   terminal-unsuccessful (skip) = {blocked, failed_terminal, skipped}
--   retryable (re-attempt)       = {pending, error}  until retry_count >= cap,
--                                  then promoted to failed_terminal (or blocked
--                                  if the last error was an anti-bot block).
-- A run always terminates: no status oscillates forever. SC-1/SC-6 depend on this.

CREATE TABLE background_sources (
    id            TEXT PRIMARY KEY,   -- uuid5(engine|query|url)
    engine        TEXT NOT NULL,      -- google|bing|reddit
    topic         TEXT NOT NULL,      -- demographic|marketing|pr|funding|leadership|competitors|sentiment
    query         TEXT NOT NULL,
    url           TEXT,
    source_tier   TEXT NOT NULL,      -- first_party|reputable_secondary|social_unverified (B2/G8)
    fetched_path  TEXT,
    point_id      TEXT,
    fetched_at    TEXT NOT NULL
);
CREATE INDEX ix_bg_topic ON background_sources(topic);

-- source_tier assignment (deterministic, at capture time):
--   first_party          = URL host == target registrable domain
--   social_unverified    = reddit.com and known forum/social hosts
--   reputable_secondary  = everything else (news/press/other sites)
-- The tier is a heuristic default; it never asserts truth, only provenance
-- authority so synthesis can hedge social claims (FR-16). Corroboration across
-- tiers is computed at synthesis time, not stored here.

CREATE TABLE claims (
    id            TEXT PRIMARY KEY,   -- uuid5(section|claim_text)  — ATOMIC claim
    section       TEXT NOT NULL,
    claim_text    TEXT NOT NULL,      -- one atomic assertion (post-decomposition)
    source_urls   TEXT NOT NULL,      -- JSON array
    chunk_ids     TEXT NOT NULL,      -- JSON array (qdrant point ids)
    chunk_texts   TEXT NOT NULL,      -- JSON array of the actual supporting chunk text (S1: self-contained audit)
    source_tier   TEXT NOT NULL,      -- highest-authority tier among supporting sources
    verdict       TEXT NOT NULL,      -- supported|unverified|contradicted|removed
    verifier_note TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE run_state (
    phase              TEXT NOT NULL,  -- discover|crawl|index|background|synthesize|verify|done
    section_status     TEXT,           -- JSON: {section: draft|verified|...} for mid-synthesis resume (S3)
    updated_at         TEXT NOT NULL
);
```

`run_state` (mirrored into `run.json`) lets a run that dies mid-synthesis resume
at the next unfinished section instead of restarting expensive LLM work (S3).

Done statuses for resume = {ok, low_content}; error/pending are re-attempted.
Content-hash mismatch on re-run marks a page dirty → re-crawl + re-embed.

## Qdrant collections (per run)

Two collections, both `size=768, distance=COSINE`, deterministic UUID5 point IDs:

**`research_<domain>_<ts>_site`** — page chunks. Payload:
```
url, title, content_type, section_anchor, chunk_index,
text, crawled_at, word_count, truncated, low_content
```

**`research_<domain>_<ts>_background`** — background source chunks. Payload:
```
engine, topic, query, url, title, section_anchor, chunk_index,
text, source_tier, fetched_at
```

`_site` chunks carry `source_tier=first_party` implicitly (the crawled site is
authoritative about itself). `source_tier` is a KEYWORD payload index on
`_background` so synthesis/verify can weight or hedge by authority.

Point ID = `uuid5(NAMESPACE_URL, f"{url}#{chunk_index}")` → idempotent re-index.
`content_type`, `topic`, `engine` are KEYWORD payload indexes for filtered
retrieval during synthesis (e.g. retrieve only `topic=funding` for the Funding
section).

## Report sections (fixed order)

1. Company (what it is, legal/brand identity)
2. Offerings (products/services)
3. Pricing
4. ICP / Target Audience
5. Marketing Angle & Positioning
6. Background — News / PR / Announcements
7. Funding History
8. Leadership Team & History

Each section: retrieval → grounded synthesis (cited) → adversarial verify.
Sections 1–5 draw primarily from `_site`; 4–8 draw from `_background` (with
cross-retrieval allowed). Section retrieval uses payload filters where the topic
maps cleanly (funding/leadership/PR → `_background` by `topic`).

## evidence.jsonl (one object per atomic claim — self-contained, S1)

Includes the actual supporting chunk text so the audit survives loss of the
(ephemeral, per-run) Qdrant collection.

```json
{"claim_id":"...","section":"Funding History","claim_text":"Raised $12M Series A in 2023",
 "source_urls":["https://…"],"chunk_ids":["…"],
 "chunk_texts":["…the verbatim supporting sentence(s) from the source…"],
 "source_tier":"reputable_secondary","verdict":"supported","verifier_note":null}
```

## Report hedging by tier (FR-16 / G8)

- `first_party` → state plainly ("The company offers …").
- `reputable_secondary` → state with attribution ("According to <source>, …").
- `social_unverified` → hedge, never bare fact ("Per a Reddit thread, some users
  report …"). A claim supported ONLY by `social_unverified` may never be stated
  as established fact; if corroborated by a higher tier, it inherits that tier.
