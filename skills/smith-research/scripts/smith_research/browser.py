"""browser.py — shared warmed Playwright context (net-new, N3 DRY helper).

Consolidates the ONE warm-up-then-fetch flow used by:
  - extractor.py render fallback (JS-heavy pages)
  - serp_scraper.py (Google/Bing)
  - reddit_collector.py (Reddit search/listings)

Preserves armory's Cloudflare-evasion technique (R4): connect to a real-Chrome
Playwright server (genuine TLS fingerprint), visit a warm-up origin first so the
JS/Cloudflare challenge sets the clearance cookie, THEN fetch the target in the
same warmed context. Real Chrome UA + en-US locale.

Connects to a persistent `playwright run-server` via WS (default ws://localhost:9224/,
started by start-playwright-server.sh) so Chromium isn't launched per-call.
"""

import os
from contextlib import contextmanager

# Real Chrome UA — matches armory reddit_collector to present a consistent
# fingerprint (R4).
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


def ws_url(explicit: str | None = None) -> str:
    return (
        explicit
        or os.environ.get("SMITH_RESEARCH_PLAYWRIGHT_WS")
        or "ws://localhost:9224/"
    )


@contextmanager
def browser_context(playwright_ws: str | None = None, timeout_ms: int = 20000):
    """Yield a fresh browser context connected to the WS server.

    Falls back to a local headless launch if no WS server is reachable (weaker
    fingerprint, but keeps the pipeline working — logged by callers).
    """
    from playwright.sync_api import sync_playwright

    target_ws = ws_url(playwright_ws)
    with sync_playwright() as p:
        browser = None
        try:
            browser = p.chromium.connect(target_ws, timeout=timeout_ms)
        except Exception:  # noqa: BLE001 — fall back to local launch
            browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT, locale="en-US")
        try:
            yield context
        finally:
            context.close()
            browser.close()


def warmed_fetch(
    url: str,
    *,
    warmup_origin: str | None = None,
    playwright_ws: str | None = None,
    timeout_ms: int = 20000,
    warmup_wait_ms: int = 3000,
    return_html: bool = True,
) -> dict:
    """Warm-up-then-fetch in one warmed context (the R4 evasion flow).

    If warmup_origin is given (e.g. https://www.reddit.com/), visit it first and
    wait warmup_wait_ms so the challenge cookie is set, THEN goto(url).

    Returns {status, url, html?, text} — text is page.inner_text('body') for
    parsing convenience; html is the full content when return_html.
    """
    with browser_context(playwright_ws, timeout_ms) as context:
        page = context.new_page()
        if warmup_origin:
            try:
                page.goto(
                    warmup_origin, wait_until="domcontentloaded", timeout=timeout_ms
                )
                page.wait_for_timeout(warmup_wait_ms)
            except Exception:  # noqa: BLE001 — warm-up best effort
                pass
        resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        status = resp.status if resp else None
        html = page.content() if return_html else None
        try:
            text = page.inner_text("body")
        except Exception:  # noqa: BLE001
            text = ""
        return {"status": status, "url": url, "html": html, "text": text}


def render_html(
    url: str, *, playwright_ws: str | None = None, timeout_ms: int = 20000
) -> str | None:
    """Simple render (no warm-up) for the extractor's JS fallback."""
    try:
        result = warmed_fetch(
            url, playwright_ws=playwright_ws, timeout_ms=timeout_ms, return_html=True
        )
        return result.get("html")
    except Exception:  # noqa: BLE001
        return None
