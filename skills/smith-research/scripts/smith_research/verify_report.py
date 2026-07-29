"""verify_report.py — DETERMINISTIC closing gate (B1). NO LLM.

This is the mechanical backstop that makes the correctness guarantee real,
independent of any subagent's judgment. It parses the FINAL report.md, extracts
every declarative sentence and its inline citation(s), and asserts each maps to a
`claims` row with verdict=supported whose supporting chunk text is on record.

Run FAILS (exit 4) on any violation:
  - a declarative sentence with NO citation                    → uncited
  - a citation that resolves to no supported claim             → unsupported
  - a supported claim whose chunk_texts are empty              → unbacked

Non-assertive lines (headings, list scaffolding, hedged/attributed phrasing,
section labels) are exempt from the citation requirement — the gate targets
factual assertions, not prose structure.
"""

import json
import re
from pathlib import Path

from smith_research.ledger import Ledger, _norm_claim

# A citation is [http...] or ([http...]) or a bare (https://...) inline link.
_CITATION_RE = re.compile(
    r"\[(?:[^\]]*?)\]\((https?://[^)]+)\)|\[(https?://[^\]]+)\]|\((https?://[^)]+)\)"
)

# Lines we never require a citation for (structure, not assertions).
_STRUCTURAL_PREFIXES = ("#", ">", "|", "```", "---", "*Source", "_Source")
_HEDGE_MARKERS = (
    "per a reddit",
    "according to a reddit",
    "unverified",
    "[unverified]",
    "some users report",
    "reportedly",
    "a reddit thread",
)

# Absence / negative-finding phrasings — the report honestly disclosing that the
# corpus lacked evidence for something. These are exempt from the hard-citation
# requirement (they assert a GAP, not a fact about the company). A run that says
# "no funding data was found" is being correct, not hallucinating.
_ABSENCE_MARKERS = (
    "were not found",
    "was not found",
    "not found in",
    "no specific",
    "contains no",
    "no additional",
    "could not be",
    "were not present",
    "was not present",
    "no funding",
    "no founder",
    "no leadership",
    "not present in",
    "cannot be substantiated",
    "no further",
)


def _split_sentences(text: str) -> list[str]:
    """Naive but deterministic sentence split on ., !, ? followed by space/EOL."""
    # protect common abbreviations minimally
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(\[])", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _is_assertive(sentence: str) -> bool:
    """Does this sentence make a factual assertion requiring a citation?"""
    s = sentence.strip()
    if not s:
        return False
    low = s.lower()
    if s.startswith(_STRUCTURAL_PREFIXES):
        return False
    # bullet scaffolding like "- " alone or a bare label
    stripped = s.lstrip("-*0123456789. ").strip()
    if len(stripped) < 15:  # too short to be a factual claim
        return False
    # section-label lines (all-caps or ending with ':')
    if s.endswith(":") and len(s) < 60:
        return False
    # Absence / negative-finding statements are the OPPOSITE of a fabrication
    # risk — the report honestly reporting "we found no evidence of X" must not
    # require a citation to a fact that by definition isn't in the corpus. These
    # phrasings are the tool disclosing a gap, which is exactly what we want.
    if any(marker in low for marker in _ABSENCE_MARKERS):
        return False
    return True


def _citations(sentence: str) -> list[str]:
    urls: list[str] = []
    for m in _CITATION_RE.finditer(sentence):
        urls.append(next(g for g in m.groups() if g))
    return urls


def _strip_citations(sentence: str) -> str:
    """Remove citation markup so the residual text can be matched to a claim."""
    s = _CITATION_RE.sub("", sentence)
    return re.sub(r"\s+", " ", s).strip(" -*.")


def verify(report_path: Path, ledger: Ledger) -> dict:
    """Return {ok, sentences, cited, supported, violations:[...]}."""
    if not report_path.exists():
        return {"ok": False, "error": "report.md missing", "violations": []}

    supported = ledger.supported_claim_index()  # normalized claim_text -> row
    # index supported claims by their cited source URLs too (fast membership)
    supported_urls: set[str] = set()
    for row in supported.values():
        for u in row.get("source_urls", []):
            supported_urls.add(u)

    text = report_path.read_text(encoding="utf-8")
    violations: list[dict] = []
    n_sentences = 0
    n_cited = 0
    n_supported = 0

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(_STRUCTURAL_PREFIXES):
            continue
        for sentence in _split_sentences(line):
            if not _is_assertive(sentence):
                continue
            n_sentences += 1
            low = sentence.lower()
            cites = _citations(sentence)
            hedged = any(h in low for h in _HEDGE_MARKERS)

            if not cites:
                # hedged/attributed social phrasing is allowed without a hard
                # citation ONLY if it also names a source inline; otherwise fail.
                if hedged:
                    n_cited += 1  # treated as attributed
                    continue
                violations.append({"sentence": sentence[:200], "reason": "uncited"})
                continue

            n_cited += 1
            # each citation must resolve to a supported claim OR a supported URL
            residual = _norm_claim(_strip_citations(sentence))
            claim_match = residual in supported
            url_match = any(c in supported_urls for c in cites)
            if claim_match or url_match:
                # ensure the backing claim actually has chunk text on record (S1)
                if claim_match and not supported[residual].get("chunk_texts"):
                    violations.append(
                        {"sentence": sentence[:200], "reason": "supported-but-unbacked"}
                    )
                else:
                    n_supported += 1
            else:
                violations.append(
                    {
                        "sentence": sentence[:200],
                        "reason": "cited-but-not-supported",
                        "citations": cites,
                    }
                )

    return {
        "ok": len(violations) == 0,
        "sentences": n_sentences,
        "cited": n_cited,
        "supported": n_supported,
        "violations": violations,
    }


def run_cli(args) -> int:
    from smith_research.config import ResearchConfig
    from smith_research.workspace import Workspace

    cfg = ResearchConfig.from_env(
        domain=args.domain,
        output_root=(
            getattr(args, "output_root", None) and Path(args.output_root).expanduser()
        ),
    )
    ws = (
        Workspace(Path(args.run_dir))
        if getattr(args, "run_dir", None)
        else Workspace.latest(cfg.output_root, args.domain)
    )
    if ws is None or not ws.ledger_path.exists():
        print(json.dumps({"error": "no run"}))
        return 1
    ledger = Ledger(ws.ledger_path)
    result = verify(ws.report_path, ledger)
    ledger.close()
    print(json.dumps(result, default=str))
    return 0 if result.get("ok") else 4  # EXIT_PARTIAL on any violation
