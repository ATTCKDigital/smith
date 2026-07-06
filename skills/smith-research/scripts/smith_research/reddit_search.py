"""reddit_search.py — Reddit SEARCH via the warmed-context evasion (net-new).

Extends the armory reddit_collector's Cloudflare-evasion technique (homepage
warm-up → clearance cookie → .json fetch, see browser.warmed_fetch / R4) from
the `/rising/` listing to Reddit SEARCH (`/search.json?q=...`), which is what
company research needs.

All Reddit results are source_tier = social_unverified (B2/G8) — hedge, never
state as bare fact.
"""

import json
from urllib.parse import quote_plus

from smith_research import browser

REDDIT_HOMEPAGE = "https://old.reddit.com/"


def _search_url(query: str, limit: int, sort: str = "relevance") -> str:
    # old.reddit.com/search.json returns real results for unauthenticated
    # queries; www.reddit.com/search.json gates them and returns empty
    # (verified 2026-07-06). raw_json=1 disables HTML entity escaping.
    q = quote_plus(query)
    return (
        f"https://old.reddit.com/search.json?q={q}&limit={limit}"
        f"&sort={sort}&raw_json=1&include_over_18=off"
    )


def search(
    query: str,
    *,
    limit: int = 15,
    playwright_ws: str | None = None,
    timeout_ms: int = 30000,
) -> list[dict]:
    """Search Reddit for `query`. Returns normalized result dicts.

    Uses the warmed context (homepage warm-up) so Cloudflare returns real JSON
    rather than a block page. NSFW (over_18) posts are filtered out.
    """
    url = _search_url(query, limit)
    result = browser.warmed_fetch(
        url,
        warmup_origin=REDDIT_HOMEPAGE,
        playwright_ws=playwright_ws,
        timeout_ms=timeout_ms,
        return_html=False,
    )
    body_text = result.get("text") or ""
    try:
        body = json.loads(body_text)
    except json.JSONDecodeError:
        return []  # blocked or non-JSON — caller logs the gap, never fabricates

    children = body.get("data", {}).get("children", [])
    out: list[dict] = []
    for c in children:
        if c.get("kind") != "t3":
            continue
        raw = c.get("data", {})
        if raw.get("over_18"):
            continue
        permalink = raw.get("permalink", "")
        out.append(
            {
                "title": raw.get("title", ""),
                "selftext": (raw.get("selftext") or "")[:5000],
                "subreddit": raw.get("subreddit", ""),
                "score": int(raw.get("score", 0)),
                "num_comments": int(raw.get("num_comments", 0)),
                "url": f"https://www.reddit.com{permalink}"
                if permalink
                else raw.get("url", ""),
                "permalink": permalink,
            }
        )
    return out
