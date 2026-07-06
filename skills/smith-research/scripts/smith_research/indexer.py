"""indexer.py — chunk + embed + upsert crawled pages to Qdrant (FR-9,10).

Deterministic. Reads crawled pages from the ledger, chunks each heading-aware,
embeds via Ollama (nomic-embed-text), and upserts into the per-run `_site`
collection with deterministic UUID5 point IDs (idempotent re-index — SC-4).
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from smith_research.chunker import chunk_markdown
from smith_research.embedder import OllamaEmbedder
from smith_research.ledger import Ledger
from smith_research.qdrant_store import WebsiteQdrantStore


def site_collection(run_dir_name: str, domain_slug: str) -> str:
    return f"research_{domain_slug}_{run_dir_name}_site"


def background_collection(run_dir_name: str, domain_slug: str) -> str:
    return f"research_{domain_slug}_{run_dir_name}_background"


class Indexer:
    def __init__(self, cfg, collection: str):
        self.cfg = cfg
        self.embedder = OllamaEmbedder(cfg.ollama_url, cfg.embedding_model)
        self.store = WebsiteQdrantStore(
            url=cfg.qdrant_url, collection=collection, vector_dim=cfg.embedding_dim
        )
        self.store.ensure_collection()

    def close(self):
        self.embedder.close()

    def index_page(self, page_row: dict) -> list[str]:
        """Chunk + embed + upsert one crawled page. Returns point IDs."""
        md_path = page_row.get("md_path")
        if not md_path or not Path(md_path).exists():
            return []
        text = Path(md_path).read_text(encoding="utf-8")
        if not text.strip():
            return []
        url = page_row["url"]
        chunks = chunk_markdown(
            text, self.cfg.chunk_target_chars, self.cfg.chunk_overlap_chars
        )
        point_ids: list[str] = []
        for ch in chunks:
            vector = self.embedder.embed(ch.text)
            payload = {
                "url": url,
                "title": page_row.get("title") or "",
                "content_type": page_row.get("content_type") or "",
                "section_anchor": ch.section_anchor,
                "chunk_index": ch.chunk_index,
                "text": ch.text,
                "source_tier": "first_party",  # crawled site = authoritative about itself
                "crawled_at": page_row.get("last_seen_at"),
                "word_count": page_row.get("word_count"),
            }
            pid = self.store.upsert_point(f"{url}#{ch.chunk_index}", vector, payload)
            point_ids.append(pid)
        return point_ids


def run_cli(args) -> int:
    from smith_research.config import ResearchConfig
    from smith_research.workspace import Workspace, slug_domain

    cfg = ResearchConfig.from_env(
        domain=args.domain,
        qdrant_url=getattr(args, "qdrant_url", None),
        ollama_url=getattr(args, "ollama_url", None),
        output_root=(args.output_root and Path(args.output_root).expanduser()),
    )
    ws = (
        Workspace(Path(args.run_dir))
        if getattr(args, "run_dir", None)
        else Workspace.latest(cfg.output_root, args.domain)
    )
    if ws is None or not ws.ledger_path.exists():
        print(json.dumps({"error": "no run to index — crawl first"}))
        return 1

    ledger = Ledger(ws.ledger_path)
    ledger.set_phase("index")
    collection = site_collection(ws.run_dir.name, slug_domain(args.domain))

    log_path = (
        ws.logs_dir()
        / f"index-{datetime.now(tz=timezone.utc).strftime('%Y%m%d-%H%M%S')}.jsonl"
    )
    log_fh = log_path.open("a", encoding="utf-8")

    indexer = Indexer(cfg, collection)
    pages_indexed = 0
    chunks_total = 0
    try:
        for page_row in ledger.crawled_pages():
            if args.resume and page_row.get("point_ids"):
                continue  # already indexed
            pids = indexer.index_page(page_row)
            if pids:
                ledger.record_page(page_row["url"], page_row["status"], point_ids=pids)
                pages_indexed += 1
                chunks_total += len(pids)
            rec = {
                "url": page_row["url"],
                "stage": "index",
                "status": "ok" if pids else "empty",
                "chunks": len(pids),
                "timestamp": datetime.now(tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            }
            log_fh.write(json.dumps(rec) + "\n")
            log_fh.flush()
    finally:
        indexer.close()
        log_fh.close()
        ledger.close()

    payload = {
        "run_dir": str(ws.run_dir),
        "collection": collection,
        "pages_indexed": pages_indexed,
        "chunks_upserted": chunks_total,
        "log": str(log_path),
    }
    print(json.dumps(payload, default=str))
    return 0
