"""discover.py — build the URL frontier (FR-1..4). Deterministic, no LLM.

Order of discovery:
  1. robots.txt  → Sitemap: directives (+ disallow capture for politeness)
  2. sitemap.xml → recursive <sitemapindex>/<urlset> walk
  3. BFS link-crawl fallback if no sitemap yielded URLs

The sitemap XML walk (namespaced + bare tags) follows the pattern from armory
website-indexer/crawler.py (_find_locs); reimplemented here standalone.

Same-registrable-domain filtering uses tldextract so subdomains of the target
count, but off-domain links are dropped.
"""

import json
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

import httpx
import tldextract

_SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def _registrable(host: str) -> str:
    ext = tldextract.extract(host)
    return f"{ext.domain}.{ext.suffix}".lower() if ext.suffix else ext.domain.lower()


def _same_site(url: str, target_registrable: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return False
    return _registrable(host) == target_registrable


def _normalize_url(url: str) -> str:
    """Drop fragments, normalize trailing state for dedup."""
    p = urlparse(url)
    if not p.scheme:
        return ""
    # strip fragment; keep query (can be meaningful for content pages)
    clean = p._replace(fragment="").geturl()
    return clean


def _find_locs(root: ET.Element, parent_tag: str, child_tag: str = "loc") -> list[str]:
    """Extract <loc> values under <parent_tag>, namespaced or bare."""
    locs: list[str] = []
    for parent_variant in (f"{{{_SITEMAP_NS}}}{parent_tag}", parent_tag):
        for elem in root.findall(parent_variant):
            for child_variant in (f"{{{_SITEMAP_NS}}}{child_tag}", child_tag):
                loc = elem.find(child_variant)
                if loc is not None and loc.text:
                    locs.append(loc.text.strip())
                    break
        if locs:
            break
    return locs


class Discoverer:
    def __init__(
        self, domain: str, timeout: float = 15.0, ua: str = "smith-research/0.1"
    ):
        self.domain = domain
        self.timeout = timeout
        self.ua = ua
        self.base = self._base_url(domain)
        self.target_registrable = _registrable(urlparse(self.base).hostname or domain)
        self._http = httpx.Client(
            timeout=timeout, follow_redirects=True, headers={"User-Agent": ua}
        )
        self.disallows: list[str] = []

    @staticmethod
    def _base_url(domain: str) -> str:
        if domain.startswith(("http://", "https://")):
            p = urlparse(domain)
            return f"{p.scheme}://{p.netloc}"
        return f"https://{domain.strip('/')}"

    def close(self):
        self._http.close()

    # ---- robots.txt ----

    def robots_sitemaps(self) -> list[str]:
        """Return Sitemap: URLs from robots.txt; capture Disallow rules."""
        sitemaps: list[str] = []
        try:
            r = self._http.get(urljoin(self.base + "/", "robots.txt"))
            if r.status_code != 200:
                return sitemaps
            for line in r.text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                key, _, val = line.partition(":")
                key = key.strip().lower()
                val = val.strip()
                if key == "sitemap" and val:
                    sitemaps.append(val)
                elif key == "disallow" and val:
                    self.disallows.append(val)
        except httpx.HTTPError:
            pass
        return sitemaps

    # ---- sitemap recursion ----

    def _fetch_sitemap(
        self, url: str, seen: set[str], out: set[str], depth: int = 0
    ) -> None:
        if depth > 8 or url in seen:
            return
        seen.add(url)
        try:
            r = self._http.get(url)
            if r.status_code != 200 or not r.content:
                return
            root = ET.fromstring(r.content)
        except (httpx.HTTPError, ET.ParseError):
            return
        tag = root.tag.split("}")[-1]
        if tag == "sitemapindex":
            for sub in _find_locs(root, "sitemap"):
                self._fetch_sitemap(sub, seen, out, depth + 1)
        else:  # urlset (or unknown but has <url><loc>)
            for loc in _find_locs(root, "url"):
                out.add(loc)

    def sitemap_urls(self, sitemap_urls: list[str]) -> set[str]:
        out: set[str] = set()
        seen: set[str] = set()
        candidates = list(sitemap_urls) or [urljoin(self.base + "/", "sitemap.xml")]
        for sm in candidates:
            self._fetch_sitemap(sm, seen, out)
        return out

    # ---- BFS fallback ----

    def bfs(self, max_pages: int = 500) -> set[str]:
        """Bounded breadth-first link crawl from the homepage."""
        from collections import deque
        from bs4 import BeautifulSoup

        found: set[str] = set()
        queue = deque([self.base])
        visited: set[str] = set()
        while queue and len(found) < max_pages:
            url = queue.popleft()
            if url in visited:
                continue
            visited.add(url)
            try:
                r = self._http.get(url)
                if r.status_code != 200 or "html" not in r.headers.get(
                    "content-type", ""
                ):
                    continue
            except httpx.HTTPError:
                continue
            found.add(url)
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                nxt = _normalize_url(urljoin(url, a["href"]))
                if (
                    nxt
                    and _same_site(nxt, self.target_registrable)
                    and nxt not in visited
                ):
                    queue.append(nxt)
        return found

    # ---- orchestration ----

    def discover(self) -> dict:
        """Full discovery. Returns {urls: set, sources: {...}}."""
        robots_sm = self.robots_sitemaps()
        sm_urls = self.sitemap_urls(robots_sm)

        source_map: dict[str, str] = {}
        for u in sm_urls:
            n = _normalize_url(u)
            if n and _same_site(n, self.target_registrable):
                source_map.setdefault(n, "robots" if robots_sm else "sitemap")

        used_bfs = False
        if not source_map:
            used_bfs = True
            for u in self.bfs():
                n = _normalize_url(u)
                if n and _same_site(n, self.target_registrable):
                    source_map.setdefault(n, "bfs")

        # Always include the homepage.
        source_map.setdefault(self.base, "seed")

        return {
            "urls": source_map,
            "sources": {
                "robots_sitemaps": len(robots_sm),
                "sitemap_urls": len(sm_urls),
                "used_bfs": used_bfs,
                "disallows": len(self.disallows),
            },
        }


# ---- CLI entrypoint (called by run.py dispatch) ----


def run_cli(args) -> int:
    from smith_research.config import ResearchConfig
    from smith_research.workspace import Workspace, now_ts
    from smith_research.ledger import Ledger

    cfg = ResearchConfig.from_env(
        domain=args.domain,
        output_root=(
            args.output_root
            and __import__("pathlib").Path(args.output_root).expanduser()
        ),
    )
    ws = (
        Workspace(__import__("pathlib").Path(args.run_dir))
        if getattr(args, "run_dir", None)
        else Workspace.create(cfg.output_root, args.domain, now_ts())
    )
    if not ws.probe_write():
        print(
            json.dumps(
                {
                    "error": "cannot write to output dir (macOS TCC?)",
                    "run_dir": str(ws.run_dir),
                }
            )
        )
        return 1

    disc = Discoverer(args.domain, timeout=cfg.request_timeout)
    try:
        result = disc.discover()
    finally:
        disc.close()

    urls = result["urls"]
    if not urls:
        print(
            json.dumps(
                {
                    "run_dir": str(ws.run_dir),
                    "discovered": 0,
                    "sources": result["sources"],
                }
            )
        )
        return 3  # EXIT_NO_URLS

    # persist frontier: urls.jsonl + ledger
    ledger = Ledger(ws.ledger_path)
    with ws.urls_path.open("w", encoding="utf-8") as fh:
        for url, source in sorted(urls.items()):
            fh.write(json.dumps({"url": url, "source": source}) + "\n")
    inserted = ledger.add_urls([(u, s) for u, s in urls.items()])
    ledger.set_phase("discover")
    ledger.close()

    ws.write_run_json(
        {
            "domain": args.domain,
            "phase": "discover",
            "collection_site": f"research_{Workspace(ws.run_dir).run_dir.name}",
            "discovered": len(urls),
        }
    )

    payload = {
        "run_dir": str(ws.run_dir),
        "discovered": len(urls),
        "inserted": inserted,
        "sources": result["sources"],
    }
    print(json.dumps(payload, default=str))
    return 0
