# smith-research engine (`scripts/`)

The deterministic, **LLM-free** engine behind the `/smith-research` skill. Every
subcommand here does mechanical work only (crawl, extract, embed, store,
retrieve, verify-bookkeeping). All LLM interpretation lives in the parent
`SKILL.md` orchestrator.

## Setup (also done by SKILL.md Phase 0)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium          # required for render + screenshots
bash start-playwright-server.sh                # host WS server on :9224
```

The `.venv/` is intentionally git-ignored — rebuild it locally; a copied venv has
broken absolute paths.

## CLI (`run.py`)

| Subcommand | Purpose | LLM? |
|------------|---------|------|
| `check` | verify Qdrant/Ollama/Playwright reachable (exit 2 if down) | no |
| `discover` | build URL frontier (sitemap→robots→BFS), seed ledger | no |
| `crawl` | fetch+extract every URL, save md/html/png, checkpoint | no |
| `index` | chunk+embed crawled pages → `_site` collection | no (embeddings) |
| `background` | Bing/Reddit SERP by topic, tier, embed → `_background` | no |
| `retrieve` | semantic retrieval over a run's collections | no (embeddings) |
| `evidence-check` | candidate chunks for a claim (generous k, both cols) | no (embeddings) |
| `record-claim` | persist a verified atomic claim + inline chunk (S1) | no |
| `verify-report` | **deterministic gate**: report ⊆ supported-claims | no |
| `status` | summarise a run's ledger + phase | no |

Full contract: `specs/32-smith-research/contracts/cli.md`.

## Exit codes

`0` ok · `2` prereq down · `3` no URLs discovered · `4` verification/partial
failure (uncited/unsupported sentence, or terminal-unsuccessful URLs) · `1` other.

## Tests

```bash
source .venv/bin/activate
pip install pytest
python -m pytest tests/ -q
```

Covers: sitemap parsing + domain filtering, ledger resume/terminal-status,
heading-aware chunking, source-tier classification + SERP parsers (incl. Bing
`ck/a` unwrap), and — critically — the deterministic `verify-report` gate
(fails an invented uncited sentence, passes a fully-cited supported report).

## Provenance

`embedder.py`, `checkpoint.py`, `logger.py`, `models.py`, `classifier.py`,
`extractor.py`, `qdrant_store.py`, `reddit_url.py` are **copied and adapted**
(not imported) from the armory project — see per-file headers. Zero runtime
coupling to armory.
