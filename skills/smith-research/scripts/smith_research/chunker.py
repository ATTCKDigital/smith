"""chunker.py — heading-aware text chunking (net-new, FR-9). Deterministic.

Splits cleaned markdown into retrieval-sized chunks that respect heading
boundaries, so each chunk carries a meaningful section anchor for citation.
Falls back to paragraph/size splitting when a section exceeds the target size.
"""

import re
from dataclasses import dataclass

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)


@dataclass
class Chunk:
    text: str
    section_anchor: str  # nearest heading (or "" for preamble)
    chunk_index: int


def _split_sections(markdown: str) -> list[tuple[str, str]]:
    """Return [(heading, body), ...] preserving order. Preamble heading = ''."""
    sections: list[tuple[str, str]] = []
    matches = list(_HEADING_RE.finditer(markdown))
    if not matches:
        return [("", markdown.strip())]
    # preamble before the first heading
    if matches[0].start() > 0:
        pre = markdown[: matches[0].start()].strip()
        if pre:
            sections.append(("", pre))
    for i, m in enumerate(matches):
        heading = m.group(2).strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        body = markdown[body_start:body_end].strip()
        sections.append((heading, body))
    return sections


def _split_oversize(text: str, target: int, overlap: int) -> list[str]:
    """Paragraph-greedy split of a too-large section, with char overlap."""
    if len(text) <= target:
        return [text] if text.strip() else []
    paras = re.split(r"\n\s*\n", text)
    out: list[str] = []
    buf = ""
    for para in paras:
        if not buf:
            buf = para
        elif len(buf) + len(para) + 2 <= target:
            buf += "\n\n" + para
        else:
            out.append(buf)
            # carry overlap tail into the next buffer
            tail = buf[-overlap:] if overlap and len(buf) > overlap else ""
            buf = (tail + "\n\n" + para) if tail else para
    if buf.strip():
        out.append(buf)
    # hard-split any paragraph still over target
    final: list[str] = []
    for c in out:
        if len(c) <= target:
            final.append(c)
        else:
            for i in range(0, len(c), target - overlap if target > overlap else target):
                final.append(c[i : i + target])
    return final


def chunk_markdown(
    markdown: str, target_chars: int = 3000, overlap_chars: int = 200
) -> list[Chunk]:
    """Chunk markdown heading-aware. Returns ordered Chunks with anchors."""
    chunks: list[Chunk] = []
    idx = 0
    for heading, body in _split_sections(markdown):
        if not body.strip():
            continue
        for piece in _split_oversize(body, target_chars, overlap_chars):
            piece = piece.strip()
            if piece:
                chunks.append(
                    Chunk(text=piece, section_anchor=heading, chunk_index=idx)
                )
                idx += 1
    return chunks
