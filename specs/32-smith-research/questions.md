---
feature: smith-research
branch: smith-research
generated: 2026-07-06
status: ANSWERED
spec: ./SKILL.md
---

# Implementation Questions: smith-research

A new Smith skill that performs thorough, fact-based, no-hallucination research on
a target website + deep background on the company behind it. Decisions below were
settled with the user before spec authoring. Every decision is grounded in code that
actually exists (armory reuse audit + smith-repo convention audit + local env probe),
not assumptions.

---

## Q1: Playwright server management (anti-bot evasion dependency)

**Context:** The armory Reddit collector's Cloudflare evasion depends on connecting to
a host-side Playwright server via `PLAYWRIGHT_WS_URL` (real Chrome TLS fingerprint) plus
a homepage warm-up that populates the bot-clearance cookie before fetching JSON. Armory
runs this via `scripts/start-playwright-server.sh` → `npx playwright run-server --port
9223 --path /`, listening on `ws://host.docker.internal:9223/`. It bundles Chromium on
the *host* (not in Docker) to stay under Colima's memory budget. The server is currently
DOWN (stale pid).

**Options:**
| Option | Description | Implications |
|--------|-------------|--------------|
| A | Skill owns its own host-side `playwright run-server` (own port) | Self-contained, no armory coupling, strong TLS fingerprint |
| B | Reuse armory's server if up, else launch own | Less resource use, couples to armory being up |
| C | Per-fetch local `chromium.launch()` (no server) | Simpler lifecycle, weaker fingerprint, slower |

**Recommended:** A — replicate armory's proven, memory-conscious pattern with a
skill-owned script on a distinct port (9224) so it never collides with armory's 9223.
smith-research runs NATIVELY on the Mac (not in Docker), so its connect URL is
`ws://localhost:9224/`, not `host.docker.internal`.

**Answer:** A. Confirmed by reading armory's `scripts/start-playwright-server.sh`
(host-side `npx playwright run-server`, idempotent, pid+log files). smith-research ships
its own `scripts/start-playwright-server.sh` on port 9224, connect URL
`ws://localhost:9224/`, started idempotently in SKILL.md Phase 0 and torn down at run end.
pid/log live in the run's `~/Documents` workspace.

---

## Q2: Report structure (first-party site content vs third-party background)

**Context:** Output spans two evidence classes: on-site content (services, pricing, ICP —
what the company says about itself) and deep background (news, funding, leadership,
marketing angle from SERP + Reddit — what the world says).

**Options:**
| Option | Description | Implications |
|--------|-------------|--------------|
| A | One unified, sectioned report | Easiest to consume; sections delineate evidence class |
| B | Two separate reports (site / background) | Cleaner first-vs-third-party separation |
| C | Unified report + machine-readable evidence.jsonl appendix | Most auditable, most build |

**Answer:** A — one unified `report.md`, clearly sectioned (Company · Offerings ·
Pricing · ICP/Audience · Marketing Angle · Background: News/PR · Funding · Leadership).
Every claim carries an inline citation to a stored source. (We still emit an
`evidence.jsonl` internally to power verification — Q3 — but the primary deliverable is
the single unified report.)

---

## Q3: Adversarial verification rigor (the no-hallucination guarantee)

**Context:** The whole point is fact-based output with no fabrication. Verification is
the enforcement mechanism.

**Options:**
| Option | Description | Implications |
|--------|-------------|--------------|
| A | Every claim re-retrieved + independently verified | Slowest, maximally correct |
| B | Section-level verification against evidence set | Faster, may miss one embedded false detail |
| C | Citations only, no separate verifier | Fastest, weakest guarantee |

**Answer:** A — every factual claim in the draft is independently re-checked against
stored Qdrant chunks by a verifier subagent. Unsupported claims are stripped or flagged
`[UNVERIFIED]`. Matches the user's stated correctness-over-speed goal. This is the core
anti-hallucination contract: (1) deterministic scripts extract with zero LLM, (2)
synthesis subagents see ONLY stored+cited chunks, (3) verifier rejects anything a stored
chunk doesn't support.

---

## Q4: Background/SERP research depth

**Context:** Background research fans out across query angles (funding, leadership, PR,
reviews, competitors) over Google + Bing + Reddit.

**Options:**
| Option | Description | Implications |
|--------|-------------|--------------|
| A | `--depth` flag, default `thorough` | Multi-angle sweep default; fast option available |
| B | Fixed thorough always | Simplest, no fast path |
| C | Fixed standard | Lighter, shallower |

**Answer:** A — `--depth {quick,standard,thorough}`, default `thorough`. Thorough =
multiple query angles per topic across Google + Bing + Reddit, deep-fetch top results.

---

## Q5: Crawl-ledger datastore (DEVIATION from armory)

**Context:** Armory uses Postgres (`pg_store.py`) for the crawl-state ledger. The user
wants each research run self-contained and portable, with all artifacts under
`~/Documents`.

**Answer:** SQLite (a single `ledger.sqlite` file in the run workspace), NOT Postgres.
Drop/rewrite `pg_store.py`. Qdrant remains the vector store (server-side; collection
named per run `research_<domain>_<ts>`), but the durable, portable record is the
`~/Documents` workspace (report + raw captures + ledger). Rationale: portability +
"artifacts in ~/Documents" + no dependency on a running Postgres.

---

## Q6: Python dependencies (DEVIATION from Smith stdlib-only convention)

**Context:** Smith's convention (confirmed by repo audit) is stdlib-only scripts, no
per-skill venv or external deps. But this pipeline genuinely requires `playwright`,
`qdrant-client`, `httpx`, `trafilatura`, `beautifulsoup4` — impossible in stdlib.

**Answer:** Justified deviation. smith-research ships a skill-owned
`scripts/requirements.txt` (or `pyproject.toml`) and a skill-owned venv
(`scripts/.venv`), bootstrapped/verified in SKILL.md Phase 0. This skill is
categorically heavier than the stdlib text-munging skills; the deviation is documented
here and surfaced in the skill's README. No other Smith convention is broken.

---

## Q7: Artifact location (DEVIATION from Smith project-scoped output)

**Context:** Smith skills conventionally write to project-scoped paths (specs/,
.specify/, .smith/vault/). The user explicitly wants all smith-research artifacts in
`~/Documents`.

**Answer:** Per explicit user instruction, all run artifacts go to
`~/Documents/smith-research/<domain>/<YYYYMMDD-HHMMSS>/` (override via
`SMITH_RESEARCH_OUTPUT_DIR`). Note: `~/Documents` has restrictive perms on macOS and may
trigger a one-time TCC "allow access to Documents" prompt — documented in SKILL.md.

---

## Q8: Code reuse from armory (per user instruction)

**Context:** User instruction: do NOT import/reference armory code at runtime — COPY it
into the smith-repo workspace.

**Answer:** All reused armory code is physically copied + adapted into
`skills/smith-research/scripts/smith_research/`, with a provenance header
("adapted from armory/services/website-indexer/..."). Zero runtime coupling to
`~/Projects/armory`.

Reuse manifest (from audit):
- Copy verbatim: `embedder.py`, `models.py`, `checkpoint.py`, `logger.py`,
  `classifier.py`, `reddit_collector.py`, `reddit_url.py`
- Copy + decouple: `extractor.py` (strip IndexerConfig), `qdrant_store.py`
  (parameterize collection/schema), `config.py` (rename, localhost defaults)
- Rewrite: `crawler.py` orchestration, `cli.py`
- Drop: `pg_store.py` (→ SQLite ledger per Q5)

Net-new (no armory source): `serp_scraper.py` (Google/Bing stealth), Reddit *search*
(extend collector's warmed-context pattern beyond `/rising/`), `bg_research.py`
(aggregator), `report.py` (RAG synthesis), `verify.py` (adversarial), `ledger.py`
(SQLite), `cli.py`, `start-playwright-server.sh`.

---

## Q9: Architect-review resolutions (2026-07-06) — BINDING

The `architect` review gate flagged that the "zero hallucinations" promise as
first written did NOT hold (the verifier is itself an LLM). Resolutions, all
folded into spec/plan/data-model/contracts before implementation:

- **B1 — guarantee reframed + made enforceable.** Promise is now "every published
  sentence is citation-gated and adversarially entailment-checked, with a full
  per-claim audit trail; **zero uncited claims** enforced deterministically."
  Added an **LLM-free `verify-report` closing gate** (report ⊆ supported-claims,
  exit 4 on violation), explicit **atomic-claim decomposition**, and an
  **entailment + contradiction** check with a new `contradicted` verdict. Built
  in P6 (deterministic layer), before the LLM orchestration. (User chose the
  "honest, enforceable framing".)
- **B2 — source authority.** Added `source_tier`
  (`first_party|reputable_secondary|social_unverified`) to background sources +
  chunk payloads; synthesis hedges/attributes social claims and never states
  them as bare fact. (User chose "tier + hedge, never bare fact".)
- **B3 — terminal blocked status.** Added `blocked`/`failed_terminal` statuses +
  `retry_count` cap so hard-blocked URLs terminate and resume always completes.
- **S1** evidence.jsonl is self-contained (inline chunk text). **S2**
  evidence-check uses generous k over both collections. **S3** run-level phase
  state (`run_state`/`run.json`) for mid-synthesis resume. **S4** robots-honored
  (first-party) vs stealth (third-party SERP/Reddit) policy + ToS risk noted.
  **S5** iCloud-sync/PII + retention warning documented.
- **N1** thresholds pinned in config. **N3** shared `browser.warmed_fetch`
  helper. **N4** gate slotted into P6. **N5** armory `models.py` kept pristine;
  net-new models in `models_research.py`.
