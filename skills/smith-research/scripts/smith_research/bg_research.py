"""bg_research.py — background research orchestrator (net-new, FR-12..14).

For each research topic, generates depth-scaled query angles, runs them across
Google + Bing + Reddit (via the warmed-context scrapers), assigns a source_tier
per result host (B2/G8), deep-fetches the top results, and embeds everything into
the per-run `_background` Qdrant collection with tier-aware payloads.

Deterministic — no LLM. Query angles are templated, not model-generated.
"""

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import tldextract

from smith_research import reddit_search, serp_scraper
from smith_research.chunker import chunk_markdown
from smith_research.embedder import OllamaEmbedder
from smith_research.extractor import PageExtractor
from smith_research.ledger import Ledger
from smith_research.models_research import SourceTier
from smith_research.qdrant_store import WebsiteQdrantStore

# Research topics → query-angle templates ({domain} substituted).
TOPIC_ANGLES: dict[str, list[str]] = {
    "demographic": [
        "{domain} target audience",
        "{domain} customers who uses",
        "{domain} reviews customer",
        "who is {domain} for",
    ],
    "marketing": [
        "{domain} marketing positioning",
        "{domain} value proposition",
        "{domain} vs competitors",
        "{domain} brand",
    ],
    "pr": [
        "{domain} news",
        "{domain} announcement press release",
        "{domain} launch",
        "{domain} 2025 2026 news",
    ],
    "funding": [
        "{domain} funding round",
        "{domain} raised investment series",
        "{domain} valuation investors",
        "{domain} venture capital",
    ],
    "leadership": [
        "{domain} founder CEO",
        "{domain} leadership team executives",
        "{domain} founded by history",
        "{domain} management team",
    ],
    "competitors": [
        "{domain} competitors alternatives",
        "{domain} vs",
        "companies like {domain}",
        "{domain} market",
    ],
    "sentiment": [
        "{domain} reviews",
        "{domain} complaints reddit",
        "{domain} is it good",
        "{domain} experience",
    ],
}

# Hosts that are inherently social/unverified (B2/G8).
_SOCIAL_HOSTS = {
    "reddit.com",
    "twitter.com",
    "x.com",
    "quora.com",
    "medium.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "youtube.com",
    "ycombinator.com",  # HN threads
}


def _registrable(url: str) -> str:
    host = urlparse(url).hostname or ""
    ext = tldextract.extract(host)
    return f"{ext.domain}.{ext.suffix}".lower() if ext.suffix else host.lower()


def classify_tier(url: str, target_registrable: str) -> SourceTier:
    """Deterministic source-tier assignment (data-model.md B2)."""
    reg = _registrable(url)
    if reg == target_registrable:
        return SourceTier.FIRST_PARTY
    if reg in _SOCIAL_HOSTS:
        return SourceTier.SOCIAL_UNVERIFIED
    return SourceTier.REPUTABLE_SECONDARY


def _bg_id(engine: str, query: str, url: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{engine}|{query}|{url}"))


class BackgroundResearcher:
    def __init__(self, cfg, ledger: Ledger, collection: str, ws, log):
        self.cfg = cfg
        self.ledger = ledger
        self.ws = ws
        self.log = log
        self.target_reg = _registrable(
            cfg.domain if cfg.domain.startswith("http") else f"https://{cfg.domain}"
        )
        self.embedder = OllamaEmbedder(cfg.ollama_url, cfg.embedding_model)
        self.store = WebsiteQdrantStore(cfg.qdrant_url, collection, cfg.embedding_dim)
        self.store.ensure_collection()
        self.extractor = PageExtractor(
            request_timeout=cfg.request_timeout,
            playwright_timeout=cfg.playwright_timeout,
            js_render_threshold=cfg.js_render_threshold,
            max_text_chars=cfg.max_text_chars,
            low_content_min_words=cfg.low_content_min_words,
            playwright_ws=cfg.playwright_ws,
        )

    def close(self):
        self.embedder.close()
        self.extractor.close()

    def _domain_name(self) -> str:
        # Human-facing name used in query templates (strip scheme).
        d = self.cfg.domain
        return d.split("//")[-1].split("/")[0]

    def _embed_source(self, *, engine, topic, query, url, tier, title, text):
        """Chunk + embed a background source's text into _background."""
        if not text or not text.strip():
            return None, 0
        bid = _bg_id(engine, query, url or title)
        # store raw
        raw_path = None
        try:
            fname = hashlib.sha1((url or bid).encode()).hexdigest()
            raw_path = self.ws.run_dir / "background" / "fetched" / f"{fname}.md"
            raw_path.write_text(f"# {title}\n\n{text}", encoding="utf-8")
        except OSError:
            pass
        first_point = None
        n = 0
        for ch in chunk_markdown(
            text, self.cfg.chunk_target_chars, self.cfg.chunk_overlap_chars
        ):
            vec = self.embedder.embed(ch.text)
            payload = {
                "engine": engine,
                "topic": topic,
                "query": query,
                "url": url or "",
                "title": title,
                "section_anchor": ch.section_anchor,
                "chunk_index": ch.chunk_index,
                "text": ch.text,
                "source_tier": tier.value,
                "fetched_at": datetime.now(tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            }
            pid = self.store.upsert_point(
                f"{engine}|{query}|{url}#{ch.chunk_index}", vec, payload
            )
            first_point = first_point or pid
            n += 1
        self.ledger.record_background(
            id=bid,
            engine=engine,
            topic=topic,
            query=query,
            url=url,
            source_tier=tier.value,
            fetched_path=str(raw_path) if raw_path else None,
            point_id=first_point,
        )
        return first_point, n

    def run_topic(self, topic: str, angles: int, fetch_top: int) -> dict:
        dom = self._domain_name()
        templates = TOPIC_ANGLES.get(topic, [f"{{domain}} {topic}"])[:angles]
        queries = [t.format(domain=dom) for t in templates]
        captured = 0
        chunks = 0
        for query in queries:
            # --- SERP: Bing + DuckDuckGo are reliable through the warmed
            # context; Google CAPTCHAs headless traffic so it's best-effort
            # only and omitted from the default rotation (verified 2026-07-06).
            for engine in ("bing", "ddg"):
                try:
                    hits = serp_scraper.search(
                        query, engine, playwright_ws=self.cfg.playwright_ws
                    )
                except Exception as exc:  # noqa: BLE001
                    self.log(
                        {
                            "stage": "background",
                            "engine": engine,
                            "query": query,
                            "status": "error",
                            "error": str(exc),
                        }
                    )
                    continue
                if not hits:
                    self.log(
                        {
                            "stage": "background",
                            "engine": engine,
                            "query": query,
                            "status": "empty",
                        }
                    )
                for hit in hits[:fetch_top]:
                    url = hit["url"]
                    tier = classify_tier(url, self.target_reg)
                    # deep-fetch the page content
                    text = hit.get("snippet", "")
                    try:
                        res = self.extractor.fetch(url)
                        if res.success and res.page and res.page.full_text:
                            text = res.page.full_text
                    except Exception:  # noqa: BLE001
                        pass
                    _, n = self._embed_source(
                        engine=engine,
                        topic=topic,
                        query=query,
                        url=url,
                        tier=tier,
                        title=hit.get("title", url),
                        text=text,
                    )
                    captured += 1
                    chunks += n
                    self.log(
                        {
                            "stage": "background",
                            "engine": engine,
                            "query": query,
                            "url": url,
                            "tier": tier.value,
                            "status": "ok",
                            "chunks": n,
                        }
                    )
                    time.sleep(self.cfg.request_delay)

            # --- Reddit search ---
            try:
                posts = reddit_search.search(
                    query, limit=fetch_top, playwright_ws=self.cfg.playwright_ws
                )
            except Exception as exc:  # noqa: BLE001
                posts = []
                self.log(
                    {
                        "stage": "background",
                        "engine": "reddit",
                        "query": query,
                        "status": "error",
                        "error": str(exc),
                    }
                )
            for post in posts:
                text = f"{post['title']}\n\n{post.get('selftext', '')}".strip()
                _, n = self._embed_source(
                    engine="reddit",
                    topic=topic,
                    query=query,
                    url=post["url"],
                    tier=SourceTier.SOCIAL_UNVERIFIED,
                    title=post["title"],
                    text=text,
                )
                captured += 1
                chunks += n
                self.log(
                    {
                        "stage": "background",
                        "engine": "reddit",
                        "query": query,
                        "url": post["url"],
                        "tier": "social_unverified",
                        "status": "ok",
                        "chunks": n,
                    }
                )
            time.sleep(self.cfg.request_delay)
        return {"queries": queries, "captured": captured, "chunks": chunks}


def run_cli(args) -> int:
    from smith_research.config import ResearchConfig
    from smith_research.workspace import Workspace, slug_domain
    from smith_research.indexer import background_collection

    cfg = ResearchConfig.from_env(
        domain=args.domain,
        depth=getattr(args, "depth", None),
        politeness=getattr(args, "politeness", None),
        qdrant_url=getattr(args, "qdrant_url", None),
        ollama_url=getattr(args, "ollama_url", None),
        playwright_ws=getattr(args, "playwright_ws", None),
        output_root=(args.output_root and Path(args.output_root).expanduser()),
    )
    ws = (
        Workspace(Path(args.run_dir))
        if getattr(args, "run_dir", None)
        else Workspace.latest(cfg.output_root, args.domain)
    )
    if ws is None or not ws.ledger_path.exists():
        print(json.dumps({"error": "no run — discover first"}))
        return 1

    topics = getattr(args, "topics", None) or list(TOPIC_ANGLES.keys())
    angles = cfg.depth_angles.get(cfg.depth, 4)
    fetch_top = cfg.depth_fetch_top.get(cfg.depth, 10)

    ledger = Ledger(ws.ledger_path)
    ledger.set_phase("background")
    collection = background_collection(ws.run_dir.name, slug_domain(args.domain))

    log_path = (
        ws.logs_dir()
        / f"background-{datetime.now(tz=timezone.utc).strftime('%Y%m%d-%H%M%S')}.jsonl"
    )
    log_fh = log_path.open("a", encoding="utf-8")

    def log(rec: dict):
        rec["timestamp"] = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        log_fh.write(json.dumps(rec) + "\n")
        log_fh.flush()

    researcher = BackgroundResearcher(cfg, ledger, collection, ws, log)
    per_topic = {}
    try:
        for topic in topics:
            per_topic[topic] = researcher.run_topic(topic, angles, fetch_top)
    finally:
        researcher.close()
        log_fh.close()

    summary = ledger.background_summary()
    ledger.close()
    payload = {
        "run_dir": str(ws.run_dir),
        "collection": collection,
        "depth": cfg.depth,
        "per_topic": per_topic,
        "per_tier": summary["by_tier"],
        "log": str(log_path),
    }
    print(json.dumps(payload, default=str))
    return 0
