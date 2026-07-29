"""Tests for the DETERMINISTIC verify-report gate (P6, B1, SC-3).

This is the test that proves the core promise: the gate FAILS a report with an
invented/uncited sentence and PASSES one where every assertion is a cited,
supported claim. No LLM involved.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from smith_research.ledger import Ledger
from smith_research.verify_report import verify, _is_assertive, _citations


def _ledger_with_supported(tmp_path, claim_text, url):
    lg = Ledger(tmp_path / "l.sqlite")
    lg.record_claim(
        id="c1",
        section="Company",
        claim_text=claim_text,
        source_urls=[url],
        chunk_ids=["k1"],
        chunk_texts=["the verbatim supporting sentence"],
        source_tier="first_party",
        verdict="supported",
    )
    return lg


def test_gate_passes_fully_cited_supported_report(tmp_path):
    url = "https://acme.com/about"
    claim = "Acme builds developer tools for startups"
    lg = _ledger_with_supported(tmp_path, claim, url)
    report = tmp_path / "report.md"
    report.write_text(f"# Company\n\n{claim} [{url}].\n", encoding="utf-8")
    result = verify(report, lg)
    lg.close()
    assert result["ok"] is True, result["violations"]
    assert result["supported"] >= 1


def test_gate_fails_uncited_invented_sentence(tmp_path):
    url = "https://acme.com/about"
    claim = "Acme builds developer tools for startups"
    lg = _ledger_with_supported(tmp_path, claim, url)
    report = tmp_path / "report.md"
    # second sentence is an INVENTED fact with no citation → must fail
    report.write_text(
        f"# Company\n\n{claim} [{url}].\n\n"
        "Acme raised a secret $900 million round from aliens in 2027.\n",
        encoding="utf-8",
    )
    result = verify(report, lg)
    lg.close()
    assert result["ok"] is False
    assert any(v["reason"] == "uncited" for v in result["violations"])


def test_gate_fails_cited_but_not_supported(tmp_path):
    lg = _ledger_with_supported(tmp_path, "Acme is a SaaS company", "https://acme.com/")
    report = tmp_path / "report.md"
    # cites a URL that is NOT among any supported claim's sources
    report.write_text(
        "Acme secretly owns a rival firm [https://rumor.example/x].\n",
        encoding="utf-8",
    )
    result = verify(report, lg)
    lg.close()
    assert result["ok"] is False
    assert any(v["reason"] == "cited-but-not-supported" for v in result["violations"])


def test_hedged_social_claim_allowed_without_hard_citation(tmp_path):
    lg = _ledger_with_supported(tmp_path, "x", "https://acme.com/")
    report = tmp_path / "report.md"
    report.write_text(
        "Per a Reddit thread, some users report slow support response times.\n",
        encoding="utf-8",
    )
    result = verify(report, lg)
    lg.close()
    assert result["ok"] is True  # hedged/attributed → exempt from hard citation


def test_structural_lines_exempt(tmp_path):
    lg = _ledger_with_supported(tmp_path, "x", "https://acme.com/")
    report = tmp_path / "report.md"
    report.write_text(
        "# Heading\n\n## Subheading\n\n- \n\n| a | b |\n\nOfferings:\n",
        encoding="utf-8",
    )
    result = verify(report, lg)
    lg.close()
    assert result["ok"] is True  # no assertive sentences → nothing to violate


def test_is_assertive_heuristics():
    assert _is_assertive("Acme was founded in 2019 by Jane Doe and John Smith.")
    assert not _is_assertive("# Company")
    assert not _is_assertive("Pricing:")
    assert not _is_assertive("- ")


def test_absence_statements_exempt_from_citation():
    # Honest "we found no evidence" disclosures must not require a citation —
    # they assert a GAP, not a fact about the company (the opposite of a
    # fabrication risk).
    assert not _is_assertive(
        "No specific funding rounds were found in the retrieved sources."
    )
    assert not _is_assertive(
        "No founder, CEO, or executive names were found in the retrieved sources."
    )
    assert not _is_assertive(
        "The retrieved evidence contains no dollar figures or investor names."
    )
    # but a positive factual assertion still requires citation
    assert _is_assertive("Acme raised a $12 million Series A led by Sequoia.")


def test_gate_passes_report_with_absence_statements(tmp_path):
    lg = _ledger_with_supported(
        tmp_path, "Acme is an ecommerce platform", "https://acme.com/"
    )
    report = tmp_path / "report.md"
    report.write_text(
        "# Company\n\nAcme is an ecommerce platform [https://acme.com/].\n\n"
        "## Funding History\n\nNo specific funding rounds were found in the "
        "retrieved sources.\n",
        encoding="utf-8",
    )
    result = verify(report, lg)
    lg.close()
    assert result["ok"] is True, result["violations"]


def test_citation_extraction_forms():
    assert _citations("text [https://a.com/x].") == ["https://a.com/x"]
    assert _citations("text ([label](https://b.com/y))") == ["https://b.com/y"]
    assert _citations("no cite here") == []
