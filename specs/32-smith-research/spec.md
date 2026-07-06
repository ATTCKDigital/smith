---
feature: 32-smith-research
branch: smith-research
created: 2026-07-06
status: implemented
---

# smith-research — Fact-Based Website & Company Deep-Research Skill

## Summary

A new Smith skill (`/smith-research <domain>`) that produces a thorough,
**fact-based, hallucination-free** research dossier on a target website and the
company behind it. It crawls the entire site, indexes the content into a local
vector store, runs deep background research across search engines and Reddit,
then synthesizes a single cited report where **every factual claim is grounded
in stored, retrievable source text and independently verified**.

The design principle is a hard separation between **extraction** (deterministic
scripts, zero LLM) and **interpretation** (LLM subagents that see only
already-stored, cited chunks). Correctness is the explicit priority over speed.

## Problem & Motivation

The user needs to research companies/websites thoroughly and trust the output
completely — no invented facts, no unsourced claims. Existing LLM "research"
tools hallucinate because they interleave retrieval and generation. This skill
inverts that: it first captures a durable, auditable evidence base (crawled
pages + background sources, all stored verbatim), and only then lets an LLM
write over that evidence, with a second LLM pass that refuses any claim the
evidence base cannot support.

## Goals

- **G1** — Enumerate and capture *every* reachable page on a target domain.
- **G2** — Store all captured content so it is durably queryable later (vector
  DB + on-disk archive), independent of any LLM.
- **G3** — Produce a progressive, sectioned report covering: what the company
  is, who they are, what they offer, to whom, at what price, plus deep
  background (target demographic, marketing angle, PR/news, funding, leadership).
- **G4** — Perform deep background research across Google, Bing, and Reddit.
- **G5** — Guarantee **traceability, not omniscience**: every published sentence
  is citation-gated and adversarially entailment-checked against stored evidence,
  with a full per-claim audit trail. Zero *uncited* claims is enforced
  deterministically (an LLM-free closing gate); hallucination-resistance
  (entailment + non-contradiction) is a strong verification layer on top. The
  system guarantees "faithfully traceable to a stored source," and distinguishes
  source authority so unverified social claims are never stated as bare fact
  (see G8).
- **G8** — Distinguish source authority: first-party (the crawled site about
  itself), reputable-secondary, and social-unverified (Reddit/forums). The report
  states first-party facts plainly, hedges social claims, and never presents an
  unverified social claim as established fact.
- **G6** — Be resumable, checkpointed, and observable (per Smith Rule 4).
- **G7** — Ship as a self-contained Smith skill; all run artifacts in
  `~/Documents/smith-research/`.

## Non-Goals

- Not a general-purpose scraper for arbitrary authenticated/paywalled content.
- Not a real-time monitor — each run is a point-in-time snapshot.
- Does not write anything back to the target site or to external services.
- No proxy/residential-IP evasion by default (available as an opt-in tier only).
- Does not assert facts as *true* — only as *faithfully traced to a stored
  source of a known authority tier*. Truth-arbitration beyond source-tiering and
  corroboration is out of scope (B2 acceptance).

## User Scenarios & Testing

### US-1 — Full research run (primary flow)
**As** the operator, **I want** to point the skill at a domain and get a
complete, cited dossier, **so that** I can understand a company end-to-end
without manually visiting pages or trusting an LLM's memory.

```gherkin
Given a target domain "example.com"
When I run /smith-research example.com
Then the skill discovers all sitemap + crawlable URLs
And crawls and stores every reachable page under ~/Documents/smith-research/example.com/<ts>/
And indexes page content into a per-run Qdrant collection
And performs background research across Google, Bing, and Reddit
And produces report.md with sections for Company, Offerings, Pricing, ICP,
    Marketing Angle, News/PR, Funding, and Leadership
And every factual claim in report.md carries an inline citation to a stored source
And an evidence.jsonl maps each claim to its source URL + retrieved chunk
```

### US-2 — Resume after interruption
```gherkin
Given a research run was interrupted mid-crawl
When I re-run /smith-research example.com --resume
Then already-crawled URLs (status ok/low_content) are skipped
And only unfinished or errored URLs are re-attempted
And no duplicate vector points are created (deterministic point IDs)
```

### US-3 — Ask questions of the stored corpus later
```gherkin
Given a completed research run with a populated Qdrant collection
When I query the corpus (via the skill's query mode) about a topic
Then answers are retrieved from stored chunks with source URLs
And no answer is produced from a topic absent in the stored evidence
```

### US-4 — Hallucination guard (the core guarantee)
```gherkin
Given a synthesized draft report
When the adversarial verifier runs
Then every declarative sentence is decomposed into atomic claims
And each atomic claim is re-retrieved against the stored collections
And each claim is checked for entailment AND non-contradiction by the verifier
And a claim a stored chunk does not entail is flagged [UNVERIFIED]
And a claim a stored chunk contradicts is flagged [CONTRADICTED] and removed
Then the deterministic verify-report gate parses the FINAL report.md
And asserts every sentence carries a citation resolving to a verdict=supported claim row
And the run fails (exit 4) if any published sentence is uncited or unsupported
And so the shipped report contains zero uncited claims (deterministically enforced)
```

### US-7 — Source-authority hedging (B2 guard)
```gherkin
Given a report claim whose only support is a social_unverified source (e.g. Reddit)
When the section is synthesized
Then the claim is attributed and hedged ("per a Reddit thread…"), never stated as bare fact
Given a claim corroborated across a first_party and a reputable_secondary source
Then it may be stated plainly
```

### US-5 — Depth control
```gherkin
Given a run invoked with --depth quick
Then background research runs one query per topic and fetches only top results
Given a run invoked with --depth thorough (default)
Then background research runs multiple query angles per topic across all engines
```

### US-6 — Bot-detection resilience
```gherkin
Given a target or search engine that challenges automated clients
When the skill fetches via the shared warmed Playwright browser context
Then it presents a real-Chrome TLS fingerprint and warmed cookies
And requests are human-paced with backoff on 429/403
And a blocked fetch is logged and retried per the politeness policy, never silently dropped
```

## Functional Requirements

### Discovery
- **FR-1** The system MUST discover URLs from `sitemap.xml`, recursively
  following `<sitemapindex>` sub-sitemaps (namespaced and non-namespaced XML).
- **FR-2** The system MUST read `robots.txt` and honor its `Sitemap:` directives
  and (in strict/normal politeness) its disallow rules.
- **FR-3** If no sitemap exists, the system MUST fall back to a bounded
  breadth-first link crawl from the homepage.
- **FR-4** The system MUST filter the frontier to the same registrable domain
  and deduplicate URLs.

### Crawl & Extract
- **FR-5** The system MUST fetch each URL, preferring a fast static fetch and
  falling back to a rendered (JS-executing) fetch when static extraction yields
  too little content.
- **FR-6** The system MUST extract main body text plus metadata: title, meta
  description, JSON-LD, and OpenGraph.
- **FR-7** The system MUST persist per page: cleaned markdown, raw HTML, and a
  screenshot, under the run workspace.
- **FR-8** The system MUST checkpoint crawl progress and support `--resume`,
  writing a JSONL log with one record per processed URL
  (`timestamp, url, stage, status, error`).
- **FR-8a** A URL repeatedly blocked by anti-bot after a bounded retry budget
  MUST reach a **terminal** `blocked` status (tracked via a `retry_count` cap),
  distinct from transient `error` (which resume re-attempts). Resume MUST treat
  `blocked`/`failed_terminal` as done-but-unsuccessful so a run always
  terminates with an honest partial result (B3, enables SC-1/SC-6).

### Index & Store
- **FR-9** The system MUST chunk page content in a heading-aware manner and
  embed each chunk with a **local** embedding model.
- **FR-10** The system MUST upsert chunks into a per-run vector collection with
  deterministic IDs so re-crawls are idempotent, and payloads that carry at
  minimum: source URL, title, section anchor, crawl timestamp, and content type.
- **FR-11** The system MUST maintain a crawl-state ledger (URL → status, http
  code, content hash, timestamps) that is the source of truth for resume.

### Background Research
- **FR-12** The system MUST perform background research across Google, Bing, and
  Reddit for these topics: target demographic, marketing angle, recent
  PR/news/announcements, funding history, leadership team + history,
  competitors, and public sentiment/reviews.
- **FR-13** Background research MUST support `--depth {quick,standard,thorough}`
  (default `thorough`), where thorough issues multiple query angles per topic.
- **FR-14** Background sources MUST be stored (raw archive + a second vector
  collection) with their origin (engine/query/URL) AND a `source_tier`
  (`first_party | reputable_secondary | social_unverified`) so they are
  independently citable and their authority is known at synthesis time (B2/G8).

### Synthesis & Verification
- **FR-15** The system MUST synthesize a single unified `report.md`, written
  progressively section-by-section, covering Company, Offerings, Pricing,
  ICP/Audience, Marketing Angle, News/PR, Funding, and Leadership.
- **FR-16** Each synthesis unit MUST be produced from **only** retrieved,
  stored chunks — never from model memory — and MUST carry inline citations to
  source URLs. Synthesis MUST hedge/attribute `social_unverified` claims and
  MUST NOT state them as bare fact (G8).
- **FR-17** The system MUST emit `evidence.jsonl` mapping each atomic claim to
  its supporting source URL(s) AND the **inline chunk text** (self-contained —
  the audit trail MUST NOT depend on the ephemeral vector store; S1).
- **FR-18** Verification MUST (a) decompose each synthesized sentence into
  **atomic claims**, (b) for each claim re-retrieve with a generous k across
  **both** collections unfiltered, (c) check **entailment AND non-contradiction**
  — a claim not entailed → `[UNVERIFIED]`, a claim contradicted by a chunk →
  `[CONTRADICTED]` and removed.
- **FR-18a** A **deterministic, LLM-free** `verify-report` gate MUST parse the
  final `report.md`, extract every sentence + inline citation, and assert each
  maps to a `claims` row with `verdict=supported` and a resolvable chunk. The run
  MUST fail (exit 4) on any orphan/uncited sentence. This is the mechanical
  backstop that keeps the guarantee in the LLM-free layer.
- **FR-18b** Retrieval parameters chosen by the orchestrator MUST NOT be able to
  falsely fail a true claim: `evidence-check` defaults to generous k over both
  collections unfiltered (S2).

### Skill, Artifacts & Environment
- **FR-19** The skill MUST be invocable as `/smith-research <domain> [flags]`.
- **FR-20** All run artifacts MUST be written under
  `~/Documents/smith-research/<domain>/<YYYYMMDD-HHMMSS>/` (overridable via
  `SMITH_RESEARCH_OUTPUT_DIR`).
- **FR-21** Phase 0 of the skill MUST verify/bootstrap prerequisites (Python
  venv, vector DB reachable, local embedding model present, Playwright browser
  server up) and fail fast with a clear message if any is missing.
- **FR-22** The skill MUST manage the lifecycle of its browser server (start
  idempotently, tear down at run end) without colliding with other local
  Playwright servers.
- **FR-23** Anti-bot handling MUST default to polite (sitemap/robots first,
  human-paced, backoff); aggressive/proxy tiers MUST be explicit opt-in.

## Success Criteria

- **SC-1** For a site with a valid sitemap, ≥99% of sitemap URLs are captured
  or explicitly logged with a terminal status (none silently dropped).
- **SC-2** A completed run's report can be fully audited: 100% of published
  sentences resolve via `evidence.jsonl` to a self-contained record (inline
  chunk text + source URL). The audit trail does NOT depend on the vector store
  still existing (S1).
- **SC-3** The shipped report contains **zero uncited claims** — enforced
  deterministically by the LLM-free `verify-report` gate (FR-18a); the run fails
  rather than ship an uncited sentence. (This is the honest, enforceable
  guarantee; entailment-level hallucination-resistance is provided by FR-18 as a
  strong layer on top, not an absolute.)
- **SC-3a** No `social_unverified` claim appears in the report as bare fact; all
  are attributed/hedged (G8).
- **SC-4** An interrupted run resumes without re-crawling completed URLs and
  without creating duplicate vector points.
- **SC-5** The stored corpus remains queryable after the run completes (the
  vector collection + on-disk archive answer topic queries with source URLs).
- **SC-6** A blocked/failed fetch is always recorded (status + error) and
  retried per policy; it is never dropped without a log entry.
- **SC-7** A fresh operator can run the skill on a new machine after Phase 0
  bootstrap, with no manual setup beyond the documented prerequisites.

## Key Entities

- **Run** — one research invocation; owns a workspace dir + two vector
  collections (`research_<domain>_<ts>_site`, `..._background`).
- **Page** — a crawled URL: url, title, content_type, cleaned text, raw HTML
  path, screenshot path, http status, content hash, crawl timestamp, point IDs.
- **Chunk** — a heading-aware slice of a page: text, section anchor, embedding,
  source URL, payload metadata.
- **BackgroundSource** — a SERP/Reddit result: engine, query, url, fetched
  content, timestamp, point ID.
- **Claim** — an **atomic** factual assertion in the report: text, section,
  cited source URL(s), supporting chunk ID(s) + inline chunk text, source_tier,
  verification verdict (`supported | unverified | contradicted | removed`).
- **LedgerEntry** — crawl state per URL: status, http code, content hash,
  first/last seen timestamps.

## Assumptions

- The operator runs locally on macOS with Docker (for the vector DB) and a
  local model runtime already available (verified: vector DB image present,
  local embedding model present).
- Targets are public sites; no auth/paywall bypass is in scope.
- Search-engine and Reddit HTML structures are scraped via a resilient,
  warmed browser context; parsers tolerate layout drift and log gaps rather
  than fabricate.
- The correctness guarantee is enforced structurally: extraction≠interpretation,
  a **deterministic LLM-free closing gate** (report ⊆ supported-claims), atomic
  claim decomposition, and adversarial entailment+contradiction verification — not
  by trusting model behavior.

## Policy & Risk Notes

- **Robots vs. stealth (S4):** robots.txt is honored for the **first-party
  target-domain crawl**. Google/Bing/Reddit are **third-party discovery** reached
  via a warmed real-Chrome context; scraping them may conflict with those
  services' ToS. This is a documented, consciously-accepted operational risk of
  the aggressive tier, surfaced in the skill README — not an omission.
- **Artifact location (S5):** `~/Documents` syncs to iCloud by default on macOS.
  Crawled pages / SERP captures may contain PII or sensitive content that would
  therefore leave the machine. The README warns operators; a retention/pruning
  note (`--keep-raw`, manual GC) is provided since per-run raw HTML + screenshots
  + vector collections grow unbounded.

## Dependencies & Deviations

- **Reuse (copied, not imported):** crawl/extract/embed/store engine and the
  Reddit collector are copied and adapted from the armory project into the
  skill's own tree with provenance headers — zero runtime coupling. (See
  `questions.md` Q8 and `research.md`.)
- **Deviation D1 (venv):** unlike stdlib-only Smith skills, this skill ships a
  skill-owned virtualenv + pinned requirements — the pipeline genuinely
  requires browser automation, a vector-DB client, an HTTP client, and content
  extraction libraries. (questions.md Q6)
- **Deviation D2 (artifact location):** artifacts go to `~/Documents` per
  explicit user instruction, not to project-scoped Smith paths. (questions.md Q7)
- **Deviation D3 (ledger store):** crawl ledger uses SQLite (portable,
  self-contained) instead of the armory Postgres store. (questions.md Q5)

All binding design decisions are recorded in
[questions.md](./questions.md) (status: ANSWERED).
