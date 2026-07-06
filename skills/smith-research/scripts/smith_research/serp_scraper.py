"""serp_scraper.py — Google/Bing SERP scraping via warmed context (net-new).

Reuses browser.warmed_fetch (real-Chrome fingerprint + pacing). Parses result
links DEFENSIVELY: SERP HTML drifts constantly, so we extract organic result
anchors + titles + snippets with tolerant heuristics and LOG gaps rather than
fabricate. If a SERP is blocked/empty, we return [] — the caller records the gap
(FR: never drop silently, never invent).

NOTE (S4): scraping Google/Bing may conflict with their ToS. This is the
consciously-accepted third-party-discovery tier, documented in the skill README.
"""

import base64
import binascii
from urllib.parse import parse_qs, quote_plus, urlparse

from bs4 import BeautifulSoup

from smith_research import browser


def _unwrap_bing(href: str) -> str | None:
    """Bing wraps results in /ck/a?...&u=a1<base64url(real_url)>. Decode it.

    Returns the real destination URL, or None if it can't be recovered (so the
    caller drops it rather than storing a bing.com redirect — real URLs are
    required for tier classification + deep-fetch).
    """
    if "/ck/a" not in href:
        return href if href.startswith("http") else None
    u = parse_qs(urlparse(href).query).get("u", [""])[0]
    if u.startswith("a1"):
        b64 = u[2:]
        b64 += "=" * (-len(b64) % 4)  # pad
        try:
            decoded = base64.urlsafe_b64decode(b64).decode("utf-8", "ignore")
            if decoded.startswith("http"):
                return decoded
        except (binascii.Error, ValueError):
            return None
    return None


def _google_url(query: str) -> str:
    return f"https://www.google.com/search?q={quote_plus(query)}&num=20&hl=en"


def _bing_url(query: str) -> str:
    return f"https://www.bing.com/search?q={quote_plus(query)}&count=20&setlang=en"


def _ddg_url(query: str) -> str:
    # DuckDuckGo's HTML endpoint is scraping-tolerant and a reliable stand-in
    # for Google, which CAPTCHAs headless traffic (verified 2026-07-06).
    return f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"


def _parse_ddg(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []
    seen: set[str] = set()
    for res in soup.select("div.result, div.web-result"):
        link = res.select_one("a.result__a")
        if not link or not link.get("href"):
            continue
        href = link["href"]
        # DDG wraps in /l/?uddg=<encoded> sometimes
        if href.startswith("/l/") or "uddg=" in href:
            qs = parse_qs(urlparse(href).query)
            href = qs.get("uddg", [href])[0]
        if not href.startswith("http") or href in seen:
            continue
        seen.add(href)
        snip = res.select_one(".result__snippet")
        results.append(
            {
                "title": link.get_text(strip=True),
                "url": href,
                "snippet": snip.get_text(" ", strip=True)[:500] if snip else "",
            }
        )
    return results


def _clean_google_href(href: str) -> str | None:
    """Google wraps results in /url?q=<real>&... — unwrap; skip non-http."""
    if href.startswith("/url?"):
        qs = parse_qs(urlparse(href).query)
        target = qs.get("q", [None])[0]
        href = target or ""
    if href.startswith("http") and "google.com" not in urlparse(href).netloc:
        return href
    return None


def _parse_google(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []
    seen: set[str] = set()
    # Organic results: anchors containing an <h3>. Tolerant to class churn.
    for a in soup.find_all("a", href=True):
        h3 = a.find("h3")
        if not h3:
            continue
        url = _clean_google_href(a["href"])
        if not url or url in seen:
            continue
        seen.add(url)
        # snippet: nearest following text block
        snippet = ""
        parent = a.find_parent()
        if parent:
            txt = parent.get_text(" ", strip=True)
            snippet = txt[:500]
        results.append(
            {"title": h3.get_text(strip=True), "url": url, "snippet": snippet}
        )
    return results


def _parse_bing(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []
    seen: set[str] = set()
    for li in soup.select("li.b_algo"):
        a = li.find("h2")
        link = a.find("a", href=True) if a else None
        if not link:
            continue
        url = _unwrap_bing(link["href"])
        if not url:
            # last resort: the visible cite/display URL
            cite = li.find("cite")
            url = cite.get_text(strip=True) if cite else None
            if url and not url.startswith("http"):
                url = "https://" + url
        if not url or url in seen:
            continue
        seen.add(url)
        p = li.find("p")
        results.append(
            {
                "title": link.get_text(strip=True),
                "url": url,
                "snippet": p.get_text(" ", strip=True)[:500] if p else "",
            }
        )
    # Fallback if the b_algo selector drifted: any h2>a
    if not results:
        for h2 in soup.find_all("h2"):
            link = h2.find("a", href=True)
            if link and link["href"].startswith("http") and link["href"] not in seen:
                seen.add(link["href"])
                results.append(
                    {
                        "title": link.get_text(strip=True),
                        "url": link["href"],
                        "snippet": "",
                    }
                )
    return results


def search(
    query: str,
    engine: str = "google",
    *,
    playwright_ws: str | None = None,
    timeout_ms: int = 30000,
    warmup: bool = True,
) -> list[dict]:
    """Scrape one SERP. Returns [] on block/empty (caller logs the gap)."""
    if engine == "google":
        # Best-effort only — Google CAPTCHAs headless traffic (verified 2026-07-06).
        url, warm, parse = _google_url(query), "https://www.google.com/", _parse_google
    elif engine == "bing":
        url, warm, parse = _bing_url(query), "https://www.bing.com/", _parse_bing
    elif engine in ("ddg", "duckduckgo"):
        url, warm, parse = _ddg_url(query), "https://duckduckgo.com/", _parse_ddg
    else:
        raise ValueError(f"unknown engine: {engine}")
    try:
        result = browser.warmed_fetch(
            url,
            warmup_origin=warm if warmup else None,
            playwright_ws=playwright_ws,
            timeout_ms=timeout_ms,
            return_html=True,
        )
    except Exception:  # noqa: BLE001
        return []
    html = result.get("html") or ""
    if not html:
        return []
    return parse(html)
