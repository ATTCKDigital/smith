#!/usr/bin/env python3
"""
describe_discover.py — File discovery for /smith-index --describe (v3
spec/23-task-llm-backend §A3).

Walks the project source files, invokes the right parser per file
(via index_common.resolve_parser + run_parser), reads any existing
.meta description layer, computes a cache_hit flag, and emits a JSON
array on stdout — one entry per file (or per-file in single-file mode).

Entry shape (data-model.md §1):

  {
    "rel_path": str,
    "source_hash": str (64 hex — sha256_first_4kb, single consistent hash
                        used for both .meta Hash: and Described-Against-Hash:),
    "parser_output": dict,
    "qualifying_method_ids": [str, ...],
    "existing_description": {
       "module_description": str | null,
       "method_descriptions": {<id>: <desc>, ...},
       "described_against_hash": str | null,
       "described_at": str | null,
    } | null,
    "cache_hit": bool,
    "system": str | null,
    "discovery_error": null | str,
  }

cache_hit is true iff existing_description.described_against_hash ==
source_hash AND at least one (module or method) description exists.

This consistency note matters: v2 had a latent bug where
described_against_hash was written as sha256(full_source) but compared
against sha256_first_4kb(file). v3 standardizes on sha256_first_4kb
for both (the same hash already used by the .meta Hash: field), so the
cache actually works for files larger than 4KB.

CLI:

  python3 describe_discover.py
    --root <project-root>           # default: cwd
    [--system <name>]               # filter to one system (Tier 1 resolver)
    [--threshold <n>]               # default DEFAULT_THRESHOLD_LINES (5)
    [--rel-path <p>]                # single-file mode (workflows)
    [--touched-only]                # in single-file mode, only describe touched ids
    [--touched-ids <comma-hex>]     # workflow input

Stdlib only. Importable as `discover(...)`.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Optional


# --- Resolve sibling helpers (index_common, meta_describe, path_resolver) -

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

import index_common  # noqa: E402
import meta_describe  # noqa: E402


def _try_load_path_resolver():
    try:
        spec = importlib.util.spec_from_file_location(
            "path_resolver", THIS_DIR / "path-resolver.py"
        )
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    except Exception:
        pass
    return None


path_resolver = _try_load_path_resolver()


# --- Core: discover one file ---------------------------------------------


def _discover_one(
    project_root: Path,
    file_path: Path,
    threshold: int,
    *,
    touched_ids: Optional[set[str]] = None,
) -> dict:
    """Return the discovery JSON entry for a single file.

    touched_ids (workflow incremental path): when provided, filters the
    qualifying_method_ids to the intersection with the touched set.
    """
    try:
        rel = str(file_path.relative_to(project_root))
    except ValueError:
        rel = str(file_path)
    entry: dict = {
        "rel_path": rel,
        "source_hash": "",
        "parser_output": None,
        "qualifying_method_ids": [],
        "existing_description": None,
        "cache_hit": False,
        "system": None,
        "discovery_error": None,
    }

    # System resolution (best-effort — never blocks discovery).
    if path_resolver is not None:
        try:
            sys_name = path_resolver.resolve_path_to_system(project_root, rel)
            entry["system"] = sys_name
        except Exception:
            entry["system"] = None

    if not file_path.is_file():
        entry["discovery_error"] = "file not found"
        return entry

    ext = file_path.suffix
    if ext in index_common.PASSIVE_EXTS:
        parsed = index_common.passive_parse(file_path)
    else:
        resolution = index_common.resolve_parser(ext, project_root)
        if resolution is None:
            entry["discovery_error"] = "no parser available"
            return entry
        lang, parser_path = resolution
        parsed = index_common.run_parser(parser_path, lang, file_path)
        if not parsed:
            entry["discovery_error"] = "parser returned empty"
            return entry

    entry["parser_output"] = parsed

    # Source hash — single consistent hash used by both .meta Hash: and
    # Described-Against-Hash: per v3 design (Q6-era cache-bug fix).
    entry["source_hash"] = index_common.sha256_first_4kb(file_path)

    # Qualifying methods (threshold filter).
    qualifying = meta_describe.qualifying_methods(parsed, threshold)
    qualifying_ids = [m["id"] for m in qualifying if m.get("id")]
    if touched_ids is not None:
        qualifying_ids = [mid for mid in qualifying_ids if mid in touched_ids]
    entry["qualifying_method_ids"] = qualifying_ids

    # Existing .meta description layer (if present).
    meta_path = index_common.meta_path_for(project_root, rel)
    if meta_path.exists():
        try:
            meta_text = meta_path.read_text(encoding="utf-8")
        except OSError:
            meta_text = ""
        existing = meta_describe.parse_meta_descriptions(meta_text)
        if existing is not None:
            entry["existing_description"] = {
                "module_description": existing.module_description,
                "method_descriptions": dict(existing.method_descriptions),
                "described_against_hash": existing.described_against_hash,
                "described_at": existing.described_at,
            }
            # Cache hit check.
            if (
                existing.described_against_hash
                and entry["source_hash"]
                and existing.described_against_hash == entry["source_hash"]
                and (existing.module_description or existing.method_descriptions)
            ):
                entry["cache_hit"] = True

    return entry


# --- Public API: discover() ----------------------------------------------


def discover(
    project_root: Path,
    *,
    system: Optional[str] = None,
    threshold: int = meta_describe.DEFAULT_THRESHOLD_LINES,
) -> list[dict]:
    """Bulk discovery — return JSON entries for all source files under
    project_root, optionally filtered to a single system.
    """
    entries: list[dict] = []
    for file_path in index_common.walk_source_files(project_root):
        entry = _discover_one(project_root, file_path, threshold)
        if system is not None and entry.get("system") != system:
            continue
        entries.append(entry)
    return entries


def discover_one(
    project_root: Path,
    rel_path: str,
    *,
    threshold: int = meta_describe.DEFAULT_THRESHOLD_LINES,
    touched_ids: Optional[set[str]] = None,
) -> list[dict]:
    """Single-file discovery — workflow incremental path."""
    file_path = (project_root / rel_path).resolve()
    return [_discover_one(project_root, file_path, threshold, touched_ids=touched_ids)]


# --- CLI -----------------------------------------------------------------


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="describe_discover",
        description="Emit JSON discovery entries for the v3 description loop.",
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--system", default=None)
    parser.add_argument(
        "--threshold",
        type=int,
        default=meta_describe.DEFAULT_THRESHOLD_LINES,
    )
    parser.add_argument("--rel-path", default=None)
    parser.add_argument("--touched-only", action="store_true")
    parser.add_argument("--touched-ids", default="")
    return parser


def main(argv: list[str]) -> int:
    args = _build_argparser().parse_args(argv)
    project_root = Path(args.root).resolve()
    if not project_root.exists():
        print(f"describe_discover: root not found: {project_root}", file=sys.stderr)
        return 2

    if args.rel_path:
        touched_ids: Optional[set[str]] = None
        if args.touched_only or args.touched_ids:
            touched_ids = {s.strip() for s in args.touched_ids.split(",") if s.strip()}
        entries = discover_one(
            project_root,
            args.rel_path,
            threshold=args.threshold,
            touched_ids=touched_ids,
        )
    else:
        entries = discover(project_root, system=args.system, threshold=args.threshold)

    print(json.dumps(entries, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
