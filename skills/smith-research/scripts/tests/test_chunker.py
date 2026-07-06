"""Unit tests for heading-aware chunking (P4)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from smith_research.chunker import chunk_markdown, _split_sections


def test_sections_split_on_headings():
    md = "# Title\n\nintro\n\n## A\n\nbody a\n\n## B\n\nbody b"
    secs = _split_sections(md)
    headings = [h for h, _ in secs]
    assert "Title" in headings and "A" in headings and "B" in headings


def test_preamble_captured():
    md = "loose text before any heading\n\n# H\n\nbody"
    secs = _split_sections(md)
    assert secs[0][0] == ""  # preamble anchor is empty
    assert "loose text" in secs[0][1]


def test_chunks_carry_anchor():
    md = "# Doc\n\n## Pricing\n\nPlans start at $10/mo."
    chunks = chunk_markdown(md, target_chars=3000)
    anchors = {c.section_anchor for c in chunks}
    assert "Pricing" in anchors
    assert all(c.chunk_index == i for i, c in enumerate(chunks))


def test_oversize_section_splits():
    big = "para. " * 2000  # ~12k chars, one section
    md = f"## Big\n\n{big}"
    chunks = chunk_markdown(md, target_chars=3000, overlap_chars=200)
    assert len(chunks) > 1
    assert all(len(c.text) <= 3200 for c in chunks)  # target + small slack


def test_empty_sections_dropped():
    md = "# A\n\n## B\n\n## C\n\nreal content"
    chunks = chunk_markdown(md)
    assert all(c.text.strip() for c in chunks)
    assert any("real content" in c.text for c in chunks)
