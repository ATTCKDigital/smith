"""Unit tests for sitemap parsing + domain filtering (P1). No network."""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from smith_research.discover import _find_locs, _registrable, _same_site, _normalize_url

NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def test_find_locs_namespaced_urlset():
    xml = f"""<urlset xmlns="{NS}">
      <url><loc>https://ex.com/a</loc></url>
      <url><loc>https://ex.com/b</loc></url>
    </urlset>"""
    root = ET.fromstring(xml)
    locs = _find_locs(root, "url")
    assert locs == ["https://ex.com/a", "https://ex.com/b"]


def test_find_locs_bare_sitemapindex():
    xml = """<sitemapindex>
      <sitemap><loc>https://ex.com/sm1.xml</loc></sitemap>
      <sitemap><loc>https://ex.com/sm2.xml</loc></sitemap>
    </sitemapindex>"""
    root = ET.fromstring(xml)
    locs = _find_locs(root, "sitemap")
    assert locs == ["https://ex.com/sm1.xml", "https://ex.com/sm2.xml"]


def test_registrable_handles_subdomains():
    assert _registrable("blog.example.com") == "example.com"
    assert _registrable("www.example.co.uk") == "example.co.uk"


def test_same_site_accepts_subdomain_rejects_offsite():
    assert _same_site("https://blog.example.com/x", "example.com")
    assert _same_site("https://example.com/x", "example.com")
    assert not _same_site("https://evil.com/x", "example.com")
    assert not _same_site("not a url", "example.com")


def test_normalize_strips_fragment():
    assert _normalize_url("https://ex.com/a#section") == "https://ex.com/a"
    assert _normalize_url("relative/path") == ""
