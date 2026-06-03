#!/usr/bin/env python3
"""
describe_write.py — Prompt assembly + .meta description-layer writer
for /smith-index --describe (v3 spec/23-task-llm-backend §A3 / Plan
Decision 2).

Two responsibilities, two subcommands:

  build-prompt   Assemble the prompt body for a Task sub-agent. One
                 source of truth for prompt construction across the
                 bulk path (smith-index SKILL.md) and the workflow
                 incremental paths (smith-new/bugfix/debug SKILL.md).

  apply          Splice a MetaDescription JSON into the file's .meta
                 atomically. Supports bulk, update-touched, and
                 from-stub modes.

Stdlib only. Importable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional


THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

import index_common  # noqa: E402
import meta_describe  # noqa: E402


# --- Source/parse helpers -------------------------------------------------


def _read_source(project_root: Path, rel_path: str) -> Optional[str]:
    src = (project_root / rel_path).resolve()
    if not src.is_file():
        return None
    try:
        return src.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _parse_source(project_root: Path, rel_path: str) -> Optional[dict]:
    """Re-parse one source file and return parser output (or None)."""
    src = (project_root / rel_path).resolve()
    if not src.is_file():
        return None
    ext = src.suffix
    if ext in index_common.PASSIVE_EXTS:
        return index_common.passive_parse(src)
    res = index_common.resolve_parser(ext, project_root)
    if res is None:
        return None
    lang, parser_path = res
    return index_common.run_parser(parser_path, lang, src)


# --- build-prompt --------------------------------------------------------


def build_prompt(
    project_root: Path,
    rel_path: str,
    *,
    method_ids: Optional[list[str]] = None,
    include_module: bool = True,
    purpose_shifted: Optional[bool] = None,
) -> str:
    """Return the prompt body for a Task call covering rel_path.

    When method_ids is None or empty AND include_module is False, the
    prompt asks only for the module description (no method block).

    When method_ids is provided, only those ids appear in the methods
    block; the prompt instructs the Task to describe only those.

    purpose_shifted controls phrasing for incremental: when False,
    asks the Task to PRESERVE the existing module description.
    """
    source = _read_source(project_root, rel_path)
    if source is None:
        raise FileNotFoundError(f"source not found: {rel_path}")
    parsed = _parse_source(project_root, rel_path)
    if parsed is None:
        raise RuntimeError(f"no parser available for: {rel_path}")

    # If method_ids given, filter qualifying methods to those ids.
    qualifying = meta_describe.qualifying_methods(
        parsed, meta_describe.DEFAULT_THRESHOLD_LINES
    )
    if method_ids:
        wanted = set(method_ids)
        target_methods = [m for m in qualifying if m.get("id") in wanted]
    else:
        target_methods = qualifying

    # Existing module description (used when purpose_shifted=False).
    existing_module: Optional[str] = None
    meta_path = index_common.meta_path_for(project_root, rel_path)
    if meta_path.exists():
        try:
            meta_text = meta_path.read_text(encoding="utf-8")
            existing = meta_describe.parse_meta_descriptions(meta_text)
            if existing is not None:
                existing_module = existing.module_description
        except OSError:
            pass

    bits: list[str] = []
    bits.append("You are generating descriptions for the Smith manifest .meta layer.")
    bits.append("")
    bits.append(
        "Return ONLY a JSON object (no preamble, no code fences, no commentary) "
        "matching this schema:"
    )
    bits.append("")
    bits.append("{")
    bits.append('  "status": "ok" | "error",')
    bits.append('  "module_description": "<single line, ≤200 chars>" | null,')
    bits.append('  "method_descriptions": [')
    bits.append('    {"method_id": "<16hex>", "description": "<≤400 chars>"},')
    bits.append("    ...")
    bits.append("  ],")
    bits.append('  "errors": []')
    bits.append("}")
    bits.append("")
    bits.append(meta_describe.summarize_for_module_prompt(parsed, source))
    bits.append("")

    if include_module and purpose_shifted is False and existing_module:
        bits.append(
            "Preserve the existing module description verbatim — purpose "
            "has NOT shifted:"
        )
        bits.append(f'  "{existing_module}"')
        bits.append(
            "Echo it as `module_description` in the JSON output (do not regenerate)."
        )
        bits.append("")
    elif include_module:
        bits.append(
            f"Soft cap: module ≤{meta_describe.MODULE_DESC_SOFT_CAP} chars, "
            "single line, informational tone."
        )
        bits.append("")
    else:
        bits.append('Set "module_description" to null. Method descriptions only.')
        bits.append("")

    if target_methods:
        bits.append(
            "Methods to describe (only describe these ids; other methods may "
            "appear in source but ignore them):"
        )
        bits.append(meta_describe.build_method_prompt(parsed, source, target_methods))
        bits.append("")
        bits.append(
            f"Soft cap: each method description ≤{meta_describe.METHOD_DESC_SOFT_CAP} "
            "chars, concise, informational."
        )
    else:
        bits.append("No method-level descriptions requested.")

    return "\n".join(bits)


def _cmd_build_prompt(args: argparse.Namespace) -> int:
    project_root = Path(args.root).resolve()
    method_ids: Optional[list[str]] = None
    if args.method_ids:
        method_ids = [s.strip() for s in args.method_ids.split(",") if s.strip()]
    purpose_shifted: Optional[bool] = None
    if args.purpose_shifted:
        purpose_shifted = args.purpose_shifted.lower() in ("true", "1", "yes")
    try:
        prompt = build_prompt(
            project_root,
            args.rel_path,
            method_ids=method_ids,
            include_module=args.module,
            purpose_shifted=purpose_shifted,
        )
    except FileNotFoundError as e:
        print(f"describe_write: {e}", file=sys.stderr)
        return 2
    except RuntimeError as e:
        print(f"describe_write: {e}", file=sys.stderr)
        return 2
    sys.stdout.write(prompt)
    return 0


# --- apply: input parsing ------------------------------------------------


def _safe_json_object(text: str) -> dict:
    """Parse a JSON object from a possibly-noisy LLM response.

    Strips common fence patterns and falls back to a brace-bounded slice.
    """
    if not text:
        return {}
    t = text.strip()
    if t.startswith("```"):
        first_nl = t.find("\n")
        if first_nl != -1:
            t = t[first_nl + 1 :]
        if t.endswith("```"):
            t = t[:-3]
        t = t.strip()
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        pass
    start = t.find("{")
    end = t.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(t[start : end + 1])
            return obj if isinstance(obj, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _normalize_description_payload(obj: dict) -> dict:
    """Accept either the full Task envelope or just the description
    fields. Returns:
      {
        "module_description": str | None,
        "method_descriptions": {<id>: <desc>, ...},
        "status": "ok" | "error",
      }
    """
    status = obj.get("status", "ok")
    module = obj.get("module_description")
    if module is not None and not isinstance(module, str):
        module = None
    method_descs: dict[str, str] = {}
    raw_methods = obj.get("method_descriptions")
    if isinstance(raw_methods, list):
        for entry in raw_methods:
            if not isinstance(entry, dict):
                continue
            mid = entry.get("method_id") or entry.get("id")
            desc = entry.get("description")
            if isinstance(mid, str) and isinstance(desc, str) and mid and desc:
                method_descs[mid] = desc
    elif isinstance(raw_methods, dict):
        # tolerate {id: desc} shape
        for mid, desc in raw_methods.items():
            if isinstance(mid, str) and isinstance(desc, str) and mid and desc:
                method_descs[mid] = desc
    return {
        "status": status,
        "module_description": module,
        "method_descriptions": method_descs,
    }


# --- apply: merge logic --------------------------------------------------


def _merge_descriptions(
    *,
    existing: Optional[meta_describe.MetaDescription],
    incoming_module: Optional[str],
    incoming_methods: dict[str, str],
    qualifying_ids: set[str],
    purpose_shifted: bool,
    update_touched: bool,
    source_hash: str,
) -> meta_describe.MetaDescription:
    """Produce the merged MetaDescription per data-model.md §3."""
    base_module = existing.module_description if existing else None
    base_methods = dict(existing.method_descriptions) if existing else {}

    # Module description.
    if update_touched:
        if purpose_shifted and incoming_module:
            new_module = meta_describe.truncate(
                incoming_module,
                meta_describe.MODULE_DESC_SOFT_CAP,
                meta_describe.MODULE_DESC_SOFT_CAP * 2,
            )
        else:
            new_module = base_module
    else:
        if incoming_module:
            new_module = meta_describe.truncate(
                incoming_module,
                meta_describe.MODULE_DESC_SOFT_CAP,
                meta_describe.MODULE_DESC_SOFT_CAP * 2,
            )
        else:
            new_module = base_module

    # Method descriptions.
    if update_touched:
        new_methods = dict(base_methods)
        for mid, desc in incoming_methods.items():
            new_methods[mid] = meta_describe.truncate(
                desc,
                meta_describe.METHOD_DESC_SOFT_CAP,
                meta_describe.METHOD_DESC_SOFT_CAP * 2,
            )
    else:
        new_methods = {
            mid: meta_describe.truncate(
                desc,
                meta_describe.METHOD_DESC_SOFT_CAP,
                meta_describe.METHOD_DESC_SOFT_CAP * 2,
            )
            for mid, desc in incoming_methods.items()
        }
        # Bulk: also preserve pre-existing descriptions for methods that
        # exist but weren't in the incoming set (Task may have failed for
        # one method; don't drop the old one).
        for mid, desc in base_methods.items():
            if mid not in new_methods:
                new_methods[mid] = desc

    # Drop stale ids (no longer in parser output).
    for stale in [mid for mid in new_methods if mid not in qualifying_ids]:
        new_methods.pop(stale, None)

    return meta_describe.MetaDescription(
        module_description=new_module,
        method_descriptions=new_methods,
        described_against_hash=source_hash,
        described_at=meta_describe.iso_now(),
    )


# --- apply: I/O ----------------------------------------------------------


def _read_input(args: argparse.Namespace) -> dict:
    if args.input:
        path = Path(args.input)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            raise SystemExit(f"describe_write: cannot read --input {path}: {e}")
        return _safe_json_object(text)
    return _safe_json_object(sys.stdin.read())


def _read_stub(fixture_path: Path, rel_path: str) -> tuple[dict, list[str]]:
    """Read the stub fixture entry for rel_path. Returns (entry, missing_ids).

    missing_ids is the list of method ids that the caller requested but
    the fixture lacks — used for the Q5 fail-loud behavior.
    """
    if not fixture_path.exists():
        raise SystemExit(f"describe_write: stub fixture not found: {fixture_path}")
    try:
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SystemExit(f"describe_write: stub fixture invalid: {e}")
    entry = data.get(rel_path)
    if entry is None:
        raise SystemExit(
            f"describe_write: stub fixture missing entry for rel_path: {rel_path}. "
            f"Update {fixture_path} or regenerate the fixture."
        )
    return entry, []


# --- apply: subcommand ---------------------------------------------------


def _cmd_apply(args: argparse.Namespace) -> int:
    project_root = Path(args.root).resolve()
    rel_path = args.rel_path

    # Resolve qualifying ids (current parser state).
    parsed = _parse_source(project_root, rel_path)
    if parsed is None:
        print(f"describe_write: cannot parse source: {rel_path}", file=sys.stderr)
        return 2
    qualifying = meta_describe.qualifying_methods(
        parsed, meta_describe.DEFAULT_THRESHOLD_LINES
    )
    qualifying_ids = {m["id"] for m in qualifying if m.get("id")}

    # Existing description layer (if present).
    existing_meta: Optional[str] = None
    meta_path = index_common.meta_path_for(project_root, rel_path)
    if meta_path.exists():
        try:
            existing_meta = meta_path.read_text(encoding="utf-8")
        except OSError:
            existing_meta = None
    existing = (
        meta_describe.parse_meta_descriptions(existing_meta) if existing_meta else None
    )

    # Source hash.
    source_path = (project_root / rel_path).resolve()
    source_hash = index_common.sha256_first_4kb(source_path)
    if args.hash:
        # Caller override — use the orchestrator's hash if provided.
        source_hash = args.hash

    # Description payload.
    if args.from_stub:
        fixture_path = Path(args.from_stub)
        stub_entry, _ = _read_stub(fixture_path, rel_path)
        payload = _normalize_description_payload(stub_entry)

        # Q5 fail-loud: every qualifying id must be present in stub.
        # For update-touched, only the touched ids are required (caller
        # filtered them via --touched-ids on discover).
        required_ids = qualifying_ids
        if args.update_touched and args.touched_ids:
            required_ids = {s.strip() for s in args.touched_ids.split(",") if s.strip()}
        missing = [
            mid
            for mid in sorted(required_ids)
            if mid not in payload["method_descriptions"]
        ]
        if missing:
            print(
                f"describe_write: stub fixture missing method_id(s) for "
                f"rel_path {rel_path}: {', '.join(missing)}. "
                f"Update {fixture_path} or regenerate the fixture.",
                file=sys.stderr,
            )
            return 4
    else:
        raw_obj = _read_input(args)
        payload = _normalize_description_payload(raw_obj)
        if payload["status"] == "error":
            print(
                f"describe_write: input payload has status=error for {rel_path}; "
                f"refusing to write .meta",
                file=sys.stderr,
            )
            return 2

    purpose_shifted = False
    if args.purpose_shifted:
        purpose_shifted = args.purpose_shifted.lower() in ("true", "1", "yes")

    merged = _merge_descriptions(
        existing=existing,
        incoming_module=payload["module_description"],
        incoming_methods=payload["method_descriptions"],
        qualifying_ids=qualifying_ids,
        purpose_shifted=purpose_shifted,
        update_touched=args.update_touched,
        source_hash=source_hash,
    )

    # Render fresh .meta with the merged description layer.
    block = meta_describe.render_description_block(merged)
    meta_text = index_common.render_meta(
        rel_path, parsed, source_hash, existing_descriptions=block
    )

    try:
        index_common.atomic_write_text(meta_path, meta_text)
    except OSError as e:
        print(f"describe_write: write failed for {meta_path}: {e}", file=sys.stderr)
        return 3

    return 0


# --- CLI plumbing --------------------------------------------------------


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="describe_write",
        description="Prompt assembly + .meta description writer for v3.",
    )
    sub = parser.add_subparsers(dest="cmd")

    bp = sub.add_parser("build-prompt", help="Assemble a Task prompt body")
    bp.add_argument("--rel-path", required=True)
    bp.add_argument("--root", default=".")
    bp.add_argument(
        "--method-ids",
        default="",
        help="Comma-separated 16-hex method ids to describe",
    )
    bp.add_argument(
        "--module",
        action="store_true",
        default=True,
        help="Include a module-description ask in the prompt (default: on)",
    )
    bp.add_argument(
        "--no-module",
        action="store_false",
        dest="module",
        help="Omit the module-description ask",
    )
    bp.add_argument("--purpose-shifted", default=None)
    bp.set_defaults(func=_cmd_build_prompt)

    ap = sub.add_parser("apply", help="Apply a MetaDescription JSON to a .meta")
    ap.add_argument("--rel-path", required=True)
    ap.add_argument("--root", default=".")
    ap.add_argument(
        "--hash",
        default=None,
        help="Source hash (sha256_first_4kb); recomputed if absent",
    )
    ap.add_argument(
        "--update-touched",
        action="store_true",
        help="Merge incoming descriptions into existing layer (incremental path)",
    )
    ap.add_argument(
        "--purpose-shifted",
        default=None,
        help="(update-touched) Whether the file's module purpose has shifted",
    )
    ap.add_argument(
        "--input",
        default=None,
        help="Read JSON payload from this file (else read stdin)",
    )
    ap.add_argument(
        "--from-stub",
        default=None,
        help="Read the description payload from a stub fixture instead of stdin",
    )
    ap.add_argument(
        "--touched-ids",
        default="",
        help="(stub mode + update-touched) The method ids required to be in the fixture",
    )
    ap.set_defaults(func=_cmd_apply)

    return parser


def main(argv: list[str]) -> int:
    parser = _build_argparser()
    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
