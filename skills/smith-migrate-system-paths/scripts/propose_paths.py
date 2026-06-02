#!/usr/bin/env python3
"""
propose_paths.py — prose → path-prefix proposer.

Implements the heuristic from `specs/20-manifest-fixes/research.md` §4.
Given the prose body of a `.specify/systems/<name>/spec.md` file (without
YAML frontmatter), scan for path-like references using regex matchers,
score each candidate prefix by frequency × position weight, and return
the top-N sorted by score descending.

Public API:

    propose(text: str, *, top_n: int = 5) -> list[Proposal]

Each `Proposal` is a dataclass with:
    prefix: str            (literal directory prefix, always ending in `/`)
    score: float           (sum of position-weighted occurrences)
    occurrences: int       (raw match count)
    excerpts: list[str]    (up to 3 line-quoted excerpts where matched)

No filesystem side effects. Pure function over the input text.
"""

from __future__ import annotations

import dataclasses
import re

# Glob characters not allowed in v1 `paths:` entries.
_GLOB_CHARS = set("*?[]{}!")


@dataclasses.dataclass(frozen=True)
class Proposal:
    prefix: str
    score: float
    occurrences: int
    excerpts: tuple[str, ...]


# --- Regex matchers (from research.md §4) ---------------------------------

# Backticked directory: `services/auth/` etc. — captures the trailing slash.
_BACKTICKED_DIR_RE = re.compile(r"`([a-z0-9_./\-]+/)`")

# Backticked file: `backend/src/foo.py` — collapse to parent dir.
_BACKTICKED_FILE_RE = re.compile(r"`([a-z0-9_./\-]+/[a-z0-9_.\-]+\.[a-z0-9]+)`")

# Bullet path: lines like `- backend/src/foo.py` (markdown lists).
_BULLET_PATH_RE = re.compile(r"^\s*[\*\-]\s+([a-z0-9_./\-]+/[a-z0-9_.\-]+)\s*$")

# Convention prefixes — captured WITH trailing slash so we don't have to add it.
_CONVENTION_MATCHERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("services", re.compile(r"\b(services/[a-z0-9_\-]+/)")),
    ("backend", re.compile(r"\b(backend/[a-z0-9_\-]+/)")),
    ("frontend", re.compile(r"\b(frontend/[a-z0-9_\-]+/)")),
    ("apps", re.compile(r"\b(apps/[a-z0-9_\-]+/)")),
    ("packages", re.compile(r"\b(packages/[a-z0-9_\-]+/)")),
)


def _parent_dir(path_like: str) -> str:
    """Collapse a file path to its parent directory, ensuring trailing `/`.

    `backend/src/foo.py` -> `backend/src/`.
    `backend/src/`       -> `backend/src/`.
    No-slash paths return empty string.
    """
    if "/" not in path_like:
        return ""
    if path_like.endswith("/"):
        return path_like
    return path_like.rsplit("/", 1)[0] + "/"


def _has_glob(s: str) -> bool:
    return any(c in _GLOB_CHARS for c in s)


def _position_weight(line_index: int, total_lines: int) -> float:
    """Linear decay from 1.0 at the top to 0.3 at the bottom."""
    if total_lines <= 1:
        return 1.0
    raw = 1.0 - (line_index / total_lines)
    return max(0.3, raw)


def _collect_candidates(text: str) -> dict[str, list[tuple[int, str]]]:
    """Walk the text line-by-line, return {prefix: [(line_idx, line_text), ...]}.

    Each occurrence carries the line index and the full line for excerpt purposes.
    Multiple matchers contributing the same prefix are merged.
    """
    out: dict[str, list[tuple[int, str]]] = {}
    lines = text.splitlines()
    total = len(lines) or 1

    in_fence = False
    for i, raw_line in enumerate(lines):
        line = raw_line.rstrip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue

        # Fenced-block file references — same matcher as bullet paths
        # (a path-looking line, no backticks needed inside the fence).
        if in_fence:
            m = re.match(r"^\s*([a-z0-9_./\-]+/[a-z0-9_.\-]+)\s*$", line)
            if m:
                prefix = _parent_dir(m.group(1))
                if prefix and not _has_glob(prefix):
                    out.setdefault(prefix, []).append((i, line))
            continue

        # Convention matchers (preserve the longest hit; backtick still counts).
        for _name, pat in _CONVENTION_MATCHERS:
            for m in pat.finditer(line):
                prefix = m.group(1)
                if not _has_glob(prefix):
                    out.setdefault(prefix, []).append((i, line))

        # Backticked dir.
        for m in _BACKTICKED_DIR_RE.finditer(line):
            prefix = m.group(1)
            if not _has_glob(prefix):
                out.setdefault(prefix, []).append((i, line))

        # Backticked file → collapse to parent dir.
        for m in _BACKTICKED_FILE_RE.finditer(line):
            prefix = _parent_dir(m.group(1))
            if prefix and not _has_glob(prefix):
                out.setdefault(prefix, []).append((i, line))

        # Bullet path.
        bm = _BULLET_PATH_RE.match(raw_line)
        if bm:
            prefix = _parent_dir(bm.group(1))
            if prefix and not _has_glob(prefix):
                out.setdefault(prefix, []).append((i, line))

    return out


def propose(text: str, *, top_n: int = 5) -> list[Proposal]:
    """Return the top-N proposed path prefixes for a prose system-spec body.

    Scoring: Σ position_weight(line_idx) for each occurrence.
    Ties are broken by raw occurrence count descending, then prefix length
    descending (more specific first).
    """
    if not text.strip():
        return []
    candidates = _collect_candidates(text)
    if not candidates:
        return []
    total = len(text.splitlines()) or 1

    proposals: list[Proposal] = []
    for prefix, hits in candidates.items():
        score = sum(_position_weight(idx, total) for idx, _ in hits)
        # Excerpts: first 3 unique line texts.
        seen: set[str] = set()
        excerpts: list[str] = []
        for _, line in hits:
            stripped = line.strip()
            if stripped not in seen:
                seen.add(stripped)
                excerpts.append(stripped)
            if len(excerpts) >= 3:
                break
        proposals.append(
            Proposal(
                prefix=prefix,
                score=round(score, 3),
                occurrences=len(hits),
                excerpts=tuple(excerpts),
            )
        )

    proposals.sort(key=lambda p: (-p.score, -p.occurrences, -len(p.prefix)))
    return proposals[:top_n]


# --- CLI -----------------------------------------------------------------


def _main(argv: list[str]) -> int:
    import argparse
    import json
    import pathlib

    ap = argparse.ArgumentParser(
        description="Propose path prefixes from spec.md prose."
    )
    ap.add_argument("spec_path", help="Path to a .specify/systems/<id>/spec.md file")
    ap.add_argument("--top-n", type=int, default=5)
    ap.add_argument(
        "--json", action="store_true", help="Emit JSON instead of human text"
    )
    args = ap.parse_args(argv)

    text = pathlib.Path(args.spec_path).read_text(encoding="utf-8")

    # Strip frontmatter if present — we propose against PROSE body only.
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            text = text[end + len("\n---\n") :]

    proposals = propose(text, top_n=args.top_n)
    if args.json:
        print(json.dumps([dataclasses.asdict(p) for p in proposals], indent=2))
    else:
        if not proposals:
            print("(no path candidates found)")
            return 0
        for p in proposals:
            print(f"  - {p.prefix}    score={p.score} matches={p.occurrences}")
            for ex in p.excerpts:
                print(f"      | {ex[:120]}")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv[1:]))
