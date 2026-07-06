# Adapted (copied, not imported) from armory services/website-indexer/website_indexer/extractor.py.
# Vendored into smith-research per user instruction: no runtime coupling to armory.
# DECOUPLED from armory's IndexerConfig: __init__ now takes explicit params with
# smith-research config.py defaults instead of a config object. The Playwright
# fallback reads the ws endpoint from the playwright_ws param, then env
# SMITH_RESEARCH_PLAYWRIGHT_WS, then the ws://localhost:9224/ default.
"""PageExtractor — fetch and extract text content from a single URL.

Extraction strategy:
  1. httpx GET with a bot User-Agent
  2. trafilatura.extract() on the response HTML
  3. If result is shorter than js_render_threshold chars, fall back to
     Playwright headless Chromium
  4. Truncate full_text to max_text_chars; set truncated flag
  5. Derive word_count from pre-truncation text
  6. Set low_content flag when word_count < low_content_min_words

Playwright import is conditional — the service can run without Playwright
installed.
"""

import re
import uuid
from datetime import UTC, datetime

import httpx
import trafilatura

from smith_research.models import CrawlResult, WebPage

_TITLE_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.IGNORECASE | re.DOTALL)
_H1_RE = re.compile(r"<h1[^>]*>([^<]+)</h1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")

# Default Playwright WebSocket endpoint (native localhost, non-Docker).
_DEFAULT_PLAYWRIGHT_WS = "ws://localhost:9224/"


def _page_point_id(url: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, url))


class PageExtractor:
    """Fetches and extracts readable text content from a web page."""

    def __init__(
        self,
        request_timeout: float = 15.0,
        playwright_timeout: float = 20.0,
        js_render_threshold: int = 200,
        max_text_chars: int = 20000,
        low_content_min_words: int = 50,
        playwright_ws: str | None = None,
    ) -> None:
        self._request_timeout = request_timeout
        self._playwright_timeout = playwright_timeout
        self._js_render_threshold = js_render_threshold
        self._max_text_chars = max_text_chars
        self._low_content_min_words = low_content_min_words
        self._playwright_ws = playwright_ws
        self._http = httpx.Client(
            timeout=request_timeout,
            follow_redirects=True,
            headers={"User-Agent": "SmithResearchBot/1.0"},
        )

    def fetch(self, url: str) -> CrawlResult:
        """Fetch and extract a page, returning a CrawlResult.

        On HTTP non-200 or network error, returns a CrawlResult with
        status="error". On success, returns status="ok" (or "low_content").

        Args:
            url: Absolute URL to fetch.

        Returns:
            CrawlResult with page populated on success; error set on failure.
        """
        # --- 1. HTTP fetch ---
        try:
            response = self._http.get(url)
        except httpx.TimeoutException as exc:
            return CrawlResult(
                url=url, success=False, status="error", error=f"Timeout: {exc}"
            )
        except httpx.HTTPError as exc:
            return CrawlResult(
                url=url, success=False, status="error", error=f"HTTP error: {exc}"
            )

        if response.status_code != 200:
            return CrawlResult(
                url=url,
                success=False,
                status="error",
                error=f"HTTP {response.status_code}",
            )

        html = response.text
        http_status = response.status_code

        # --- 2. trafilatura extraction ---
        extracted: str | None = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=False,
        )
        text = extracted or ""

        # --- 3. Playwright fallback if text is too short ---
        if len(text) < self._js_render_threshold:
            playwright_text = self._fetch_playwright(url)
            if playwright_text:
                text = playwright_text

        # --- 4. Title extraction ---
        title = self._extract_title(html, url)

        # --- 5. Word count (pre-truncation) ---
        word_count = len(text.split()) if text else 0

        # --- 6. Truncation ---
        truncated = False
        if len(text) > self._max_text_chars:
            text = text[: self._max_text_chars]
            truncated = True

        # --- 7. Snippet ---
        text_snippet = text[:500]

        # --- 8. Flags ---
        low_content = word_count < self._low_content_min_words

        point_id = _page_point_id(url)

        page = WebPage(
            url=url,
            title=title,
            content_type="",  # Populated by classifier in crawler loop
            full_text=text,
            text_snippet=text_snippet,
            word_count=word_count,
            crawled_at=datetime.now(tz=UTC),
            http_status=http_status,
            truncated=truncated,
            low_content=low_content,
            point_id=point_id,
        )

        status = "low_content" if low_content else "ok"
        cr = CrawlResult(url=url, success=True, status=status, page=page)
        # Attach raw HTML + http_status without mutating the pristine WebPage
        # model (FR-7 raw-HTML capture; provenance-honest, N5).
        cr.raw_html = html
        cr.http_status = http_status
        return cr

    def _fetch_playwright(self, url: str) -> str | None:
        """Render a JS-heavy page and extract its text.

        Delegates the render to the shared browser.render_html() helper (N3 DRY)
        so serp/reddit/extractor all use ONE warmed-context path, which also
        carries a local-launch fallback if the WS server is unreachable. This
        method keeps the trafilatura extraction step.

        Returns extracted text, or None on failure.
        """
        try:
            from smith_research import browser
        except ImportError:
            return None
        try:
            html = browser.render_html(
                url,
                playwright_ws=self._playwright_ws,
                timeout_ms=int(self._playwright_timeout * 1000),
            )
            if not html:
                return None
            extracted: str | None = trafilatura.extract(
                html, include_comments=False, include_tables=False
            )
            return extracted or None
        except Exception as exc:  # noqa: BLE001
            print(f"  [WARN] Playwright fallback failed for {url}: {exc}")
            return None

    def _extract_title(self, html: str, url: str) -> str:
        """Extract a human-readable title from HTML.

        Tries in order:
          1. <title> tag text
          2. <h1> tag text
          3. Last path segment of the URL as a fallback slug

        Args:
            html: Raw HTML string.
            url: Page URL (used as last-resort fallback).

        Returns:
            Non-empty title string.
        """
        # <title> tag
        m = _TITLE_RE.search(html)
        if m:
            title = _TAG_RE.sub("", m.group(1)).strip()
            if title:
                return title

        # <h1> tag
        m = _H1_RE.search(html)
        if m:
            title = _TAG_RE.sub("", m.group(1)).strip()
            if title:
                return title

        # URL slug fallback — last non-empty path segment
        from urllib.parse import urlparse

        segments = [s for s in urlparse(url).path.split("/") if s]
        if segments:
            return segments[-1].replace("-", " ").replace("_", " ").title()

        return url

    def close(self) -> None:
        """Close the underlying httpx client."""
        self._http.close()
