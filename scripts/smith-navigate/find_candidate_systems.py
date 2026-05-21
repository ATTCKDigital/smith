#!/usr/bin/env python3
"""
find_candidate_systems.py — optional pre-filter helper for /smith-navigate.

Given a task description and the project manifest, return up to N system
names whose descriptions or file-name patterns most plausibly match.
This is a non-LLM keyword overlap heuristic; the Haiku navigator does
the real selection. Callers (context-loader.sh) may use this to narrow
the input context passed to the sub-agent.

Usage:
    python3 find_candidate_systems.py <project-root> "<task description>" [--limit N]

Output: one system name per line on stdout. Exit 0 always. No matches
prints nothing.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "but",
    "if",
    "then",
    "else",
    "for",
    "with",
    "to",
    "from",
    "of",
    "in",
    "on",
    "at",
    "by",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "this",
    "that",
    "those",
    "these",
    "i",
    "we",
    "you",
    "they",
    "it",
    "do",
    "does",
    "did",
    "have",
    "has",
    "had",
    "can",
    "could",
    "would",
    "should",
    "will",
    "shall",
    "may",
    "might",
    "must",
    "where",
    "when",
    "why",
    "how",
    "what",
    "which",
    "who",
    "whom",
    "fix",
    "add",
    "update",
    "change",
    "make",
    "create",
    "remove",
    "delete",
    "new",
    "use",
    "using",
}


def tokenize(text: str) -> set[str]:
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]+", text.lower())
    return {t for t in tokens if t not in STOPWORDS and len(t) > 2}


def score_system(
    system_name: str, manifest_text: str, system_text: str, task_tokens: set[str]
) -> float:
    """Score a system by token overlap with its name + manifest description."""
    haystack = (system_name + " " + system_text).lower()
    matches = 0
    for token in task_tokens:
        if token in haystack:
            matches += 1
    # Bonus for token-in-system-name.
    name_lower = system_name.lower()
    for token in task_tokens:
        if token in name_lower:
            matches += 2
    return matches


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("project_root")
    p.add_argument("task")
    p.add_argument("--limit", type=int, default=3)
    args = p.parse_args(argv)

    root = Path(args.project_root).resolve()
    index_dir = root / ".smith" / "index"
    if not (index_dir / "manifest.md").exists():
        return 0
    manifest_text = (index_dir / "manifest.md").read_text(
        encoding="utf-8", errors="replace"
    )

    task_tokens = tokenize(args.task)
    if not task_tokens:
        return 0

    scored: list[tuple[float, str]] = []
    systems_dir = index_dir / "systems"
    if not systems_dir.exists():
        return 0
    for sysfile in systems_dir.glob("*.md"):
        sys_name = sysfile.stem
        try:
            sys_text = sysfile.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        score = score_system(sys_name, manifest_text, sys_text, task_tokens)
        if score > 0:
            scored.append((score, sys_name))

    scored.sort(reverse=True)
    for _, name in scored[: args.limit]:
        sys.stdout.write(name + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
