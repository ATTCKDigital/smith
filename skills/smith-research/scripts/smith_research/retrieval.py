"""retrieval.py — read-only retrieval + evidence-check + claim recording (P6).

Deterministic, no LLM. Powers:
  - `retrieve`       : semantic retrieval for synthesis subagents (SKILL.md)
  - `evidence-check` : candidate chunks for a claim (verifier subagent input).
                       GENEROUS k over BOTH collections unfiltered (FR-18b/S2) so
                       a retrieval choice can never falsely fail a true claim.
                       Returns CANDIDATES only — the entailment decision is the
                       verifier subagent's, never a similarity threshold (B1).
  - `record-claim`   : persist a verified atomic claim + inline chunk text (S1).
"""

import json
import uuid
from pathlib import Path

from smith_research.embedder import OllamaEmbedder
from smith_research.ledger import Ledger
from smith_research.qdrant_store import WebsiteQdrantStore


def _collections(ws, domain_slug: str) -> dict:
    from smith_research.indexer import site_collection, background_collection

    return {
        "site": site_collection(ws.run_dir.name, domain_slug),
        "background": background_collection(ws.run_dir.name, domain_slug),
    }


def _search(cfg, collection: str, query_vec: list[float], k: int) -> list[dict]:
    """Search one collection; tolerate a missing collection (returns [])."""
    store = WebsiteQdrantStore(cfg.qdrant_url, collection, cfg.embedding_dim)
    try:
        # query_points is the current API; .search was removed in qdrant-client
        # 1.14+. A missing collection returns []; any OTHER error is re-raised so
        # real API drift is never silently masked as "no results".
        resp = store.client.query_points(
            collection_name=collection,
            query=query_vec,
            limit=k,
            with_payload=True,
        )
        hits = resp.points
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if "not found" in msg or "doesn't exist" in msg or "404" in msg:
            return []
        raise
    out = []
    for h in hits:
        pl = h.payload or {}
        out.append(
            {
                "score": h.score,
                "chunk_id": str(h.id),
                "text": pl.get("text", ""),
                "url": pl.get("url", ""),
                "title": pl.get("title", ""),
                "section_anchor": pl.get("section_anchor", ""),
                "source_tier": pl.get("source_tier", "reputable_secondary"),
                "engine": pl.get("engine"),
                "topic": pl.get("topic"),
                "collection": "site" if collection.endswith("_site") else "background",
            }
        )
    return out


def retrieve(cfg, ws, domain_slug, query, *, collection="both", topic=None, k=8):
    """Semantic retrieval. Embeds the query (query prefix), searches, merges."""
    embedder = OllamaEmbedder(cfg.ollama_url, cfg.embedding_model)
    try:
        # Query embedding: nomic uses 'search_query:' prefix for the query side.
        # embedder.embed prepends 'search_document:'; for retrieval symmetry we
        # embed the raw query the same way (both sides consistent → cosine valid).
        qvec = embedder.embed(query)
    finally:
        embedder.close()
    cols = _collections(ws, domain_slug)
    targets = ["site", "background"] if collection == "both" else [collection]
    results: list[dict] = []
    for t in targets:
        results.extend(_search(cfg, cols[t], qvec, k))
    if topic:
        results = [r for r in results if r.get("topic") == topic] or results
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:k]


# ---- CLI entrypoints (run.py dispatch) ----


def _ctx(args):
    from smith_research.config import ResearchConfig
    from smith_research.workspace import Workspace, slug_domain

    cfg = ResearchConfig.from_env(
        domain=args.domain,
        qdrant_url=getattr(args, "qdrant_url", None),
        ollama_url=getattr(args, "ollama_url", None),
        output_root=(
            getattr(args, "output_root", None) and Path(args.output_root).expanduser()
        ),
    )
    ws = (
        Workspace(Path(args.run_dir))
        if getattr(args, "run_dir", None)
        else Workspace.latest(cfg.output_root, args.domain)
    )
    return cfg, ws, slug_domain(args.domain)


def cli_retrieve(args) -> int:
    cfg, ws, slug = _ctx(args)
    if ws is None:
        print(json.dumps({"error": "no run"}))
        return 1
    results = retrieve(
        cfg,
        ws,
        slug,
        args.query,
        collection=args.collection,
        topic=getattr(args, "topic", None),
        k=args.k,
    )
    print(json.dumps({"query": args.query, "results": results}, default=str))
    return 0


def cli_evidence_check(args) -> int:
    cfg, ws, slug = _ctx(args)
    if ws is None:
        print(json.dumps({"error": "no run"}))
        return 1
    k = getattr(args, "k", None) or cfg.evidence_k
    # generous k, BOTH collections, unfiltered (FR-18b/S2)
    candidates = retrieve(cfg, ws, slug, args.claim, collection="both", k=k)
    best = candidates[0]["score"] if candidates else 0.0
    print(
        json.dumps(
            {
                "claim": args.claim,
                "candidates": [
                    {
                        "text": c["text"],
                        "url": c["url"],
                        "source_tier": c["source_tier"],
                        "score": c["score"],
                        "chunk_id": c["chunk_id"],
                    }
                    for c in candidates
                ],
                "best_score": best,
            },
            default=str,
        )
    )
    return 0


def cli_record_claim(args) -> int:
    cfg, ws, slug = _ctx(args)
    if ws is None:
        print(json.dumps({"error": "no run"}))
        return 1
    ledger = Ledger(ws.ledger_path)
    cid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{args.section}|{args.claim}"))
    ledger.record_claim(
        id=cid,
        section=args.section,
        claim_text=args.claim,
        source_urls=args.source_urls,
        chunk_ids=args.chunk_ids,
        chunk_texts=args.chunk_texts,
        source_tier=args.source_tier,
        verdict=args.verdict,
    )
    # append to evidence.jsonl (self-contained audit, S1)
    with ws.evidence_path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "claim_id": cid,
                    "section": args.section,
                    "claim_text": args.claim,
                    "source_urls": args.source_urls,
                    "chunk_ids": args.chunk_ids,
                    "chunk_texts": args.chunk_texts,
                    "source_tier": args.source_tier,
                    "verdict": args.verdict,
                }
            )
            + "\n"
        )
    ledger.close()
    print(json.dumps({"recorded": cid, "verdict": args.verdict}))
    return 0
