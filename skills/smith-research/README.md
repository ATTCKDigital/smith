# smith-research

A Smith skill that produces a thorough, **fact-based, hallucination-resistant**
research dossier on a target website and the company behind it.

It crawls the whole site, indexes it into a local vector store, runs deep
background research (Bing + Reddit via stealth Playwright), then synthesizes a
single fully-cited report where **every published sentence is citation-gated and
adversarially verified** against stored evidence. A deterministic, LLM-free gate
fails the run rather than ship an uncited claim.

## The guarantee (and its honest limits)

- **What it guarantees:** every sentence in the report is traceable to a stored
  source, and the run **cannot complete** unless a deterministic (LLM-free) gate
  confirms every declarative sentence maps to a `verdict=supported` claim with a
  resolvable chunk. Zero *uncited* claims is mechanically enforced.
- **What it does NOT guarantee:** that cited facts are *true*. Sources have
  authority tiers (`first_party` / `reputable_secondary` / `social_unverified`);
  social/unverified claims (e.g. Reddit) are hedged and never stated as bare
  fact, but the tool traces provenance — it does not arbitrate truth.

## Architecture

Extraction (deterministic, zero LLM) is strictly separated from interpretation
(LLM subagents that see ONLY already-stored, cited chunks):

```
skills/smith-research/
├── SKILL.md                       # orchestrator (phases, subagents, gate)
└── scripts/
    ├── requirements.txt           # skill-owned venv deps
    ├── start-playwright-server.sh # host-side playwright run-server :9224
    ├── run.py                     # deterministic CLI (no LLM)
    └── smith_research/            # the engine
```

Some engine modules are **copied (not imported)** from the armory project with
provenance headers — there is zero runtime coupling to armory.

## Prerequisites

- **Docker** with a **Qdrant** container on `:6333`
  (`docker run -d -p 6333:6333 -p 6334:6334 -v qdrant_storage:/qdrant/storage qdrant/qdrant`)
- **Ollama** running with **`nomic-embed-text`** pulled (`ollama pull nomic-embed-text`)
- **Python 3.12+** and **Node** (for `playwright run-server`)

Phase 0 of the skill bootstraps the venv, installs the Playwright browser, starts
the WS server, and verifies all three services — failing fast with remediation if
any is down.

## Usage

```
/smith-research <domain> [--depth quick|standard|thorough] [--politeness strict|normal|aggressive] [--resume]
```

The engine can also be driven directly:

```bash
source skills/smith-research/scripts/.venv/bin/activate
python skills/smith-research/scripts/run.py check --domain acme.com
python skills/smith-research/scripts/run.py discover --domain acme.com
python skills/smith-research/scripts/run.py crawl    --domain acme.com
python skills/smith-research/scripts/run.py index    --domain acme.com
python skills/smith-research/scripts/run.py background --domain acme.com --depth thorough
# synthesis + verification are driven by the SKILL.md orchestrator (LLM);
# the deterministic closing gate:
python skills/smith-research/scripts/run.py verify-report --domain acme.com
```

## Artifacts

All run artifacts land under **`~/Documents/smith-research/<domain>/<timestamp>/`**
(override with `SMITH_RESEARCH_OUTPUT_DIR`):

```
report.md          # the final, gated, fully-cited report
evidence.jsonl     # self-contained audit: each claim → source URL + inline chunk text
ledger.sqlite      # crawl state (resume source of truth)
urls.jsonl  pages/  raw_html/  screenshots/  background/  logs/  run.json
```

The Qdrant vector collections (`research_<domain>_<ts>_site` / `_background`)
persist so you can ask follow-up questions of the stored corpus later.

## Known limits & risks

- **Background-research coverage varies.** Bing works reliably; Google CAPTCHAs
  headless traffic, DuckDuckGo often 403s, and Reddit rate-limits an IP quickly.
  The pipeline is Bing-primary and degrades gracefully — blocked engines are
  logged as gaps and **never fabricated around**. Coverage is honest, not total.
  (A future optional API-backed path — Brave Search / Reddit API — would improve
  robustness.)
- **ToS (S4):** scraping search engines / Reddit may conflict with their terms.
  robots.txt is honored for the **first-party target crawl**; SERP/Reddit are
  third-party discovery via a warmed browser context — a consciously-accepted
  operational risk.
- **macOS `~/Documents` (S5):** may trigger a one-time "allow access to
  Documents" TCC prompt, and syncs to iCloud by default, so crawled pages / SERP
  captures (possibly containing PII) may leave the machine. Set
  `SMITH_RESEARCH_OUTPUT_DIR` to a non-synced path to avoid this. Per-run raw
  HTML + screenshots grow unbounded; prune old runs manually.

## Convention deviations (documented)

This skill deviates from two Smith conventions, by design and with justification:

- **Skill-owned venv + external deps** (not stdlib-only): the pipeline genuinely
  needs browser automation, a vector-DB client, an HTTP client, and content
  extraction. See `requirements.txt`.
- **Artifacts to `~/Documents`** (not project-scoped): per explicit user
  instruction.

Full design + decisions: `specs/32-smith-research/` (spec, plan, data-model,
contracts, questions).
