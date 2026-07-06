"""Unit tests for background research deterministic parts (P5). No network."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from smith_research.bg_research import classify_tier, TOPIC_ANGLES
from smith_research.models_research import SourceTier
from smith_research import serp_scraper


def test_tier_first_party():
    assert classify_tier("https://acme.com/about", "acme.com") == SourceTier.FIRST_PARTY
    assert (
        classify_tier("https://blog.acme.com/x", "acme.com") == SourceTier.FIRST_PARTY
    )


def test_tier_social():
    assert (
        classify_tier("https://www.reddit.com/r/x/comments/1", "acme.com")
        == SourceTier.SOCIAL_UNVERIFIED
    )
    assert (
        classify_tier("https://twitter.com/acme", "acme.com")
        == SourceTier.SOCIAL_UNVERIFIED
    )


def test_tier_secondary():
    assert (
        classify_tier("https://techcrunch.com/acme-raises", "acme.com")
        == SourceTier.REPUTABLE_SECONDARY
    )


def test_topics_cover_required_areas():
    for required in (
        "demographic",
        "marketing",
        "pr",
        "funding",
        "leadership",
        "competitors",
        "sentiment",
    ):
        assert required in TOPIC_ANGLES
        assert len(TOPIC_ANGLES[required]) >= 1


def test_bing_parser_tolerant():
    html = """<html><body>
      <li class="b_algo"><h2><a href="https://ex.com/a">Result A</a></h2><p>snippet a</p></li>
      <li class="b_algo"><h2><a href="https://ex.com/b">Result B</a></h2><p>snippet b</p></li>
    </body></html>"""
    out = serp_scraper._parse_bing(html)
    assert len(out) == 2
    assert out[0]["url"] == "https://ex.com/a"
    assert out[0]["title"] == "Result A"


def test_bing_unwraps_ck_redirect():
    import base64

    real = "https://www.anthropic.com/company"
    u = "a1" + base64.urlsafe_b64encode(real.encode()).decode().rstrip("=")
    href = f"https://www.bing.com/ck/a?!&&p=abc&u={u}"
    assert serp_scraper._unwrap_bing(href) == real
    # plain http passes through; unrecoverable ck/a → None
    assert serp_scraper._unwrap_bing("https://ex.com/x") == "https://ex.com/x"
    assert serp_scraper._unwrap_bing("https://www.bing.com/ck/a?u=garbage") is None


def test_bing_parser_uses_real_urls():
    import base64

    real = "https://acme.com/about"
    u = "a1" + base64.urlsafe_b64encode(real.encode()).decode().rstrip("=")
    html = f"""<html><body>
      <li class="b_algo"><h2><a href="https://www.bing.com/ck/a?u={u}">Acme</a></h2>
        <cite>acme.com</cite><p>snip</p></li>
    </body></html>"""
    out = serp_scraper._parse_bing(html)
    assert out and out[0]["url"] == real


def test_google_parser_unwraps_and_skips_self():
    html = """<html><body>
      <a href="/url?q=https://ex.com/real&sa=U"><h3>Real Result</h3></a>
      <a href="https://www.google.com/preferences"><h3>Google Nav</h3></a>
    </body></html>"""
    out = serp_scraper._parse_google(html)
    urls = [r["url"] for r in out]
    assert "https://ex.com/real" in urls
    assert not any("google.com" in u for u in urls)
