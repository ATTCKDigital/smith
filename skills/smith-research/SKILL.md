---
name: smith-research
description: Thorough, fact-based, hallucination-resistant research on a target website and the company behind it. Crawls the whole site, indexes it into a local vector store, runs deep background research (Bing/Reddit via stealth Playwright), then synthesizes a single fully-cited report where every published sentence is citation-gated and adversarially verified against stored evidence. Correctness over speed. All artifacts land in ~/Documents/smith-research/.
argument-hint: "<domain> [--depth quick|standard|thorough] [--politeness strict|normal|aggressive] [--resume]"
---

# Smith Research — Website & Company Deep Research

Produce an auditable research dossier on a target site + company. The design
separates **extraction** (deterministic scripts, zero LLM) from **interpretation**
(LLM subagents that see ONLY already-stored, cited chunks). The guarantee is
traceability, not omniscience: every published sentence is citation-gated and
adversarially entailment-checked, and a **deterministic LLM-free gate** fails the
run rather than ship an uncited claim.

**Arguments:** $ARGUMENTS  (first positional token is the target domain)

## When to use

- You need a complete, source-backed picture of a company: what it is, what it
  offers, pricing, target audience, marketing angle, plus background — PR/news,
  funding, and leadership.
- You want the underlying corpus stored so you can ask follow-up questions later.

## When NOT to use

- Quick one-off lookups (use a direct web search).
- Authenticated/paywalled content (out of scope).

## Vault Logging

Throughout, log significant events to the vault session log. Read the path from
`.smith/vault/.current-session`. If missing or the vault is not initialized, skip
logging silently. Immediately before every Agent tool call, append a block naming
the phase, `subagent_type`, and model (the Agent return value does not expose
these to the parent, so this is the only capture point).

## Prerequisites (checked in Phase 0)

- Docker running with a Qdrant container on :6333.
- Ollama running with `nomic-embed-text` pulled.
- The skill-owned venv + Playwright browser + Playwright WS server (Phase 0
  bootstraps these).

## Engine (deterministic CLI — no LLM)

All crawling/extraction/indexing/retrieval/verification bookkeeping is done by:

```bash
python3 skills/smith-research/scripts/run.py <subcommand> [flags]
```

Subcommands: `check`, `discover`, `crawl`, `index`, `background`, `retrieve`,
`evidence-check`, `record-claim`, `verify-report`, `status`. See
`skills/smith-research/scripts/README.md` and `specs/32-smith-research/contracts/cli.md`.

The LLM only ever runs in Phases 5–6 below, over retrieved+cited chunks.

---

## Phase 0: Bootstrap & prerequisites

```bash
SR=skills/smith-research/scripts
# 1. venv (idempotent)
[ -d "$SR/.venv" ] || python3 -m venv "$SR/.venv"
source "$SR/.venv/bin/activate"
pip install -q -r "$SR/requirements.txt"
# 2. Playwright browser (required for screenshots + render fallback + WS server)
python -m playwright install chromium >/dev/null 2>&1
# 3. host-side Playwright WS server on :9224 (idempotent; uses venv python)
bash "$SR/start-playwright-server.sh"
# 4. verify Qdrant + Ollama + Playwright are all reachable
python "$SR/run.py" check --domain "$DOMAIN" --json
```

If `check` exits non-zero (2), STOP and surface the remediation lines it printed
(start Qdrant / `ollama pull nomic-embed-text` / start the WS server). Do not
proceed — correctness depends on all three being up.

> **macOS note (S5):** artifacts write to `~/Documents/smith-research/`, which may
> trigger a one-time "allow Terminal to access Documents" TCC prompt, and syncs to
> iCloud by default — crawled pages/SERP captures may contain PII. Warn the user
> once. Set `SMITH_RESEARCH_OUTPUT_DIR` to override the location.

## Phase 1: Discover

```bash
python "$SR/run.py" discover --domain "$DOMAIN" --json
```

Builds the URL frontier (sitemap recursion → robots → BFS fallback). Note the
`run_dir` it prints — every later phase resolves the latest run automatically.
If `discovered` is 0, STOP (exit 3): the domain has no reachable pages.

## Phase 2: Crawl

```bash
python "$SR/run.py" crawl --domain "$DOMAIN" ${RESUME:+--resume} --json
```

Fetches every URL (static → render fallback), saves markdown + raw HTML +
screenshot, checkpoints, and enforces terminal statuses so the run always
completes. A non-zero exit (4) means some URLs reached a terminal-unsuccessful
state (blocked/failed) — that is an honest partial, NOT a hard failure; note the
counts and continue.

## Phase 3: Index

```bash
python "$SR/run.py" index --domain "$DOMAIN" ${RESUME:+--resume} --json
```

Chunks + embeds crawled pages into the per-run `_site` Qdrant collection
(idempotent — safe to re-run).

## Phase 4: Background research

```bash
python "$SR/run.py" background --domain "$DOMAIN" --depth "${DEPTH:-thorough}" --json
```

Runs Bing-primary SERP + Reddit across the research topics (demographic,
marketing, pr, funding, leadership, competitors, sentiment), assigns a
`source_tier` per source, deep-fetches and embeds into the `_background`
collection. Blocked/empty engines are logged as gaps, never fabricated. Note
`per_tier` — social_unverified sources must be hedged in synthesis.

## Phase 5: Synthesize (LLM — grounded, cited)

Write `report.md` progressively, ONE section at a time, each by a subagent that
sees ONLY retrieved chunks. Report sections (fixed order): **Company · Offerings ·
Pricing · ICP/Audience · Marketing Angle · News/PR · Funding · Leadership**.

For each section:

1. Retrieve evidence (site for 1–5, background for 4–8; both allowed):
   ```bash
   python "$SR/run.py" retrieve --domain "$DOMAIN" --query "<section-focused query>" --collection both --k 10 --json
   ```
2. Spawn ONE `general-purpose` subagent (log the Agent call per Vault Logging).
   Pass it ONLY the retrieved chunks (text + url + source_tier). Prompt contract:
   > "Write the **<Section>** section using ONLY the provided sources. If a fact
   > is not in the sources, do NOT state it. Cite every factual sentence inline
   > as `[<url>]`. For any source marked `social_unverified`, attribute and hedge
   > ('Per a Reddit thread, …') — never state it as bare fact. Return markdown."
3. Append the returned section to `report.md`.

Run sections in parallel where practical (they are independent). Update
`run.json`/`run_state` phase to `synthesize` with per-section status so a died
run resumes at the next unfinished section (S3).

## Phase 6: Verify (LLM per-claim) + DETERMINISTIC gate

**6a — Adversarial per-claim verification.** For each section's draft:

1. Decompose it into ATOMIC claims (one assertion each — split compound
   sentences so no fact rides along uncounted).
2. For each atomic claim, gather candidate evidence:
   ```bash
   python "$SR/run.py" evidence-check --domain "$DOMAIN" --claim "<atomic claim>" --json
   ```
3. Spawn a verifier `general-purpose` subagent (adversarial prompt):
   > "Default to UNVERIFIED. Mark **supported** ONLY if a provided chunk directly
   > ENTAILS the claim. Mark **contradicted** if a chunk refutes it. Topical
   > similarity is NOT support. Return the verdict + which chunk_id(s) support it."
4. Record every claim's outcome:
   ```bash
   python "$SR/run.py" record-claim --domain "$DOMAIN" --section "<S>" --claim "<c>" \
     --verdict supported --source-urls <urls...> --chunk-ids <ids...> \
     --chunk-texts "<supporting chunk text...>" --source-tier <tier>
   ```
5. In `report.md`, strip any claim that came back `contradicted`, and mark any
   `unverified` claim with a trailing `[UNVERIFIED]` or remove it.

**6b — Deterministic closing gate (LLM-FREE — the actual enforcement):**

```bash
python "$SR/run.py" verify-report --domain "$DOMAIN" --json
```

This parses the FINAL `report.md` and asserts every declarative sentence maps to
a `verdict=supported` claim with a resolvable chunk. If it exits 4, it prints the
offending sentences (`uncited` / `cited-but-not-supported`). You MUST fix each
(add a real citation from evidence, or remove the sentence) and re-run until it
exits 0. **Do not present the report to the user until this gate passes.** This is
the guarantee: the shipped report contains zero uncited claims.

## Phase 7: Finalize

- Confirm `verify-report` exited 0.
- Report to the user: the `run_dir` path, `report.md`, `evidence.jsonl`, the
  crawl/background counts, and any honest gaps (blocked engines, terminal URLs,
  `[UNVERIFIED]` items).
- Tear down the Playwright WS server if this run started it:
  ```bash
  kill "$(cat "${TMPDIR:-/tmp}"/smith-research-playwright-9224.pid 2>/dev/null)" 2>/dev/null || true
  ```

## Later: ask questions of the stored corpus (US-3)

The vector collections persist. To answer follow-ups from stored evidence:

```bash
python "$SR/run.py" retrieve --domain "$DOMAIN" --query "<question>" --collection both --k 8 --json
```

Answer ONLY from returned chunks + their URLs; if a topic is absent, say so —
never fill the gap from model memory.

## Key rules

- **Extraction is never done by an LLM.** Phases 1–4 and all bookkeeping are the
  deterministic CLI.
- **Synthesis sees only retrieved, cited chunks.** No model memory, ever.
- **The deterministic gate is the guarantee.** A run that can't pass
  `verify-report` is not finished — fix or cut the offending claims.
- **social_unverified is never bare fact.** Hedge and attribute.
- **Never fabricate around a blocked source.** Log the gap; report it honestly.
