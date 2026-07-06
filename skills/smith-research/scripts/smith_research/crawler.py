"""crawler.py — crawl orchestration (REWRITE of armory crawler, FR-5..8).

Drives fetch → extract → save(md/html/screenshot) → ledger → checkpoint → log
for every pending URL. Resumable, checkpointed, politeness-paced, with the B3
terminal-status contract (blocked/failed_terminal) so a run always terminates.

Deterministic — no LLM. The armory crawler coupled discovery+embed+store into one
loop; here crawl is a distinct phase (indexing is separate, indexer.py).
"""

import hashlib
import json
import time
from datetime import datetime, timezone

from smith_research.classifier import classify_content_type
from smith_research.extractor import PageExtractor
from smith_research.ledger import Ledger
from smith_research.models_research import PageStatus


def _sha1(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _is_block(http_status: int | None, error: str | None) -> bool:
    """Heuristic: did this look like an anti-bot block (vs a transient error)?"""
    if http_status in (403, 429, 503):
        return True
    if error and any(
        s in error.lower() for s in ("cloudflare", "captcha", "blocked", "403", "429")
    ):
        return True
    return False


class Crawler:
    def __init__(self, cfg, ws, ledger: Ledger, log_writer):
        self.cfg = cfg
        self.ws = ws
        self.ledger = ledger
        self.log = log_writer
        self.extractor = PageExtractor(
            request_timeout=cfg.request_timeout,
            playwright_timeout=cfg.playwright_timeout,
            js_render_threshold=cfg.js_render_threshold,
            max_text_chars=cfg.max_text_chars,
            low_content_min_words=cfg.low_content_min_words,
            playwright_ws=cfg.playwright_ws,
        )

    def close(self):
        self.extractor.close()

    def _screenshot(self, url: str, sha1: str) -> str | None:
        """Best-effort full-page screenshot via the shared warmed context."""
        try:
            from smith_research import browser

            with browser.browser_context(self.cfg.playwright_ws) as ctx:
                page = ctx.new_page()
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=int(self.cfg.playwright_timeout * 1000),
                )
                path = self.ws.screenshot(sha1)
                page.screenshot(path=str(path), full_page=True)
                return str(path)
        except Exception:  # noqa: BLE001 — screenshots are non-essential
            return None

    def crawl_one(self, url: str, screenshots: bool = True) -> str:
        sha1 = _sha1(url)
        result = self.extractor.fetch(url)

        if not result.success or result.page is None:
            err = result.error or "fetch failed"
            http = getattr(result, "http_status", None)
            blocked = _is_block(http, err)
            status = PageStatus.BLOCKED if blocked else PageStatus.ERROR
            self.ledger.record_page(
                url, status, http_status=http, error=err, bump_retry=True
            )
            self.log(
                {"url": url, "stage": "crawl", "status": status.value, "error": err}
            )
            return status.value

        page = result.page
        # save cleaned markdown + raw html
        md_path = self.ws.page_md(sha1)
        md_path.write_text(page.full_text or "", encoding="utf-8")
        html_path = None
        raw_html = getattr(result, "raw_html", None)
        if raw_html:
            html_path = self.ws.raw_html(sha1)
            html_path.write_text(raw_html, encoding="utf-8")

        shot = self._screenshot(url, sha1) if screenshots else None
        content_type = classify_content_type(url)
        status = PageStatus.LOW_CONTENT if page.low_content else PageStatus.OK

        self.ledger.record_page(
            url,
            status,
            http_status=page.http_status,
            content_sha256=_sha256(page.full_text or ""),
            content_type=content_type,
            title=page.title,
            word_count=page.word_count,
            md_path=str(md_path),
            html_path=str(html_path) if html_path else None,
            screenshot_path=shot,
        )
        self.log(
            {
                "url": url,
                "stage": "crawl",
                "status": status.value,
                "word_count": page.word_count,
                "content_type": content_type,
                "http_status": page.http_status,
            }
        )
        return status.value


def run_cli(args) -> int:
    from pathlib import Path as _P
    from smith_research.config import ResearchConfig
    from smith_research.workspace import Workspace

    cfg = ResearchConfig.from_env(
        domain=args.domain,
        politeness=getattr(args, "politeness", None),
        playwright_ws=getattr(args, "playwright_ws", None),
        output_root=(args.output_root and _P(args.output_root).expanduser()),
    )
    ws = (
        Workspace(_P(args.run_dir))
        if getattr(args, "run_dir", None)
        else Workspace.latest(cfg.output_root, args.domain)
    )
    if ws is None or not ws.ledger_path.exists():
        print(
            json.dumps(
                {"error": "no run to crawl — run discover first", "domain": args.domain}
            )
        )
        return 1

    ledger = Ledger(ws.ledger_path)
    ledger.set_phase("crawl")

    # log writer (JSONL, one record per URL — Rule 4)
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
    log_path = ws.logs_dir() / f"crawl-{ts}.jsonl"
    log_fh = log_path.open("a", encoding="utf-8")

    def log(rec: dict):
        rec["timestamp"] = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        log_fh.write(json.dumps(rec) + "\n")
        log_fh.flush()

    pending = ledger.pending_urls(
        include_errors=args.resume, max_retries=cfg.max_retries
    )
    if args.limit:
        pending = pending[: args.limit]

    crawler = Crawler(cfg, ws, ledger, log)
    counts = {"ok": 0, "low_content": 0, "error": 0, "blocked": 0}
    try:
        for i, url in enumerate(pending):
            status = crawler.crawl_one(url)
            counts[status] = counts.get(status, 0) + 1
            if i < len(pending) - 1:
                time.sleep(cfg.request_delay)
    finally:
        crawler.close()
        log_fh.close()

    # B3: promote exhausted error URLs to terminal so resume converges.
    promoted = ledger.promote_exhausted(cfg.max_retries)
    summary = ledger.status_summary()
    ledger.close()

    payload = {
        "run_dir": str(ws.run_dir),
        "attempted": len(pending),
        "counts": counts,
        "promoted_terminal": promoted,
        "ledger": summary,
        "log": str(log_path),
    }
    print(json.dumps(payload, default=str))
    # exit 4 (partial) if anything reached a non-success terminal state
    unsuccessful = summary.get("blocked", 0) + summary.get("failed_terminal", 0)
    return 4 if unsuccessful else 0
