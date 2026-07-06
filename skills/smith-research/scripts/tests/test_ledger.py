"""Unit tests for the SQLite ledger — resume + terminal-status semantics (P2)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from smith_research.ledger import Ledger
from smith_research.models_research import PageStatus


def test_add_and_dedup(tmp_path):
    lg = Ledger(tmp_path / "l.sqlite")
    assert lg.add_url("https://ex.com/a", "sitemap") is True
    assert lg.add_url("https://ex.com/a", "sitemap") is False  # dup
    assert lg.status_summary() == {"pending": 1}
    lg.close()


def test_pending_excludes_done(tmp_path):
    lg = Ledger(tmp_path / "l.sqlite")
    lg.add_urls([("https://ex.com/a", "s"), ("https://ex.com/b", "s")])
    lg.record_page("https://ex.com/a", PageStatus.OK, word_count=100)
    pend = lg.pending_urls()
    assert pend == ["https://ex.com/b"]  # 'a' is done
    lg.close()


def test_error_retried_until_cap_then_terminal(tmp_path):
    lg = Ledger(tmp_path / "l.sqlite")
    lg.add_url("https://ex.com/a", "s")
    # simulate 3 failed attempts
    for _ in range(3):
        lg.record_page(
            "https://ex.com/a", PageStatus.ERROR, error="boom", bump_retry=True
        )
    # under cap of 5 → still retryable
    assert "https://ex.com/a" in lg.pending_urls(max_retries=5)
    # at cap of 3 → not retryable, and promote_exhausted makes it terminal
    assert "https://ex.com/a" not in lg.pending_urls(max_retries=3)
    promoted = lg.promote_exhausted(max_retries=3)
    assert promoted == 1
    assert lg.get_page("https://ex.com/a")["status"] == PageStatus.FAILED_TERMINAL.value
    lg.close()


def test_blocked_is_terminal(tmp_path):
    lg = Ledger(tmp_path / "l.sqlite")
    lg.add_url("https://ex.com/a", "s")
    lg.record_page("https://ex.com/a", PageStatus.BLOCKED, error="cloudflare")
    assert lg.pending_urls() == []  # blocked never re-attempted
    lg.close()


def test_claims_and_supported_index(tmp_path):
    lg = Ledger(tmp_path / "l.sqlite")
    lg.record_claim(
        id="c1",
        section="Funding",
        claim_text="Raised $5M",
        source_urls=["u"],
        chunk_ids=["k"],
        chunk_texts=["raised $5m in 2022"],
        source_tier="reputable_secondary",
        verdict="supported",
    )
    lg.record_claim(
        id="c2",
        section="Funding",
        claim_text="Raised $9B",
        source_urls=[],
        chunk_ids=[],
        chunk_texts=[],
        source_tier="social_unverified",
        verdict="unverified",
    )
    idx = lg.supported_claim_index()
    assert "raised $5m" in idx  # normalized
    assert "raised $9b" not in idx  # unverified excluded
    lg.close()


def test_phase_roundtrip(tmp_path):
    lg = Ledger(tmp_path / "l.sqlite")
    lg.set_phase("crawl", {"Company": "draft"})
    got = lg.get_phase()
    assert got["phase"] == "crawl"
    assert got["section_status"] == {"Company": "draft"}
    lg.close()
