#!/usr/bin/env python3
"""
meta_describe.py — Shared LLM description layer for Smith Manifest v2.

This is the SOLE module that crosses the structural-↔-description boundary.
It is called by:
  - /smith-index --describe        (bulk path; describe all qualifying methods)
  - skills/smith-new/SKILL.md      (workflow incremental, touched methods)
  - skills/smith-bugfix/SKILL.md   (workflow incremental, touched methods)
  - skills/smith-debug/SKILL.md    (workflow incremental, touched methods)
  - hooks/manifest-updater-lib.py  (READ ONLY — parse_meta_descriptions only)

Public API:
  parse_meta_descriptions(meta_text) -> MetaDescription | None
  describe_file(rel_path, source, parsed, ...) -> MetaDescription
  update_touched(rel_path, source, parsed, existing, touched_method_ids,
                 purpose_shifted, ...) -> MetaDescription
  render_description_block(desc) -> dict   # keys consumed by render_meta()

Haiku is reached via stdlib urllib.request — no `anthropic` SDK dependency.
ANTHROPIC_API_KEY is read from env; if absent, calls raise RuntimeError.

CLI entrypoint (T073): supports `update-touched --rel-path ... --touched-ids ...`
so workflow skills can shell out without writing a wrapper.

Per data-model.md §4 (LLM-layer contract) and research.md §6 (prompt design).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

# --- Soft caps (per data-model.md §2.2) ------------------------------------

MODULE_DESC_SOFT_CAP = 120
METHOD_DESC_SOFT_CAP = 200
DEFAULT_THRESHOLD_LINES = 5
DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
HTTP_TIMEOUT_S = 10.0

# Methods batched per per-method LLM call (amortizes round-trip).
METHODS_PER_LLM_CALL = 5


# --- Datatypes -------------------------------------------------------------


@dataclass
class MethodDescription:
    """Single per-method description entry.

    `method_id` is the stable 16-char hex id from parser output
    (parser-output-v2.schema.json).
    """

    method_id: str
    description: str


@dataclass
class MetaDescription:
    """The serialized form of the .meta description layer.

    Fields are written together by description-aware paths; never partially.
    Per data-model.md §4.2.
    """

    module_description: str | None = None
    method_descriptions: dict[str, str] = field(default_factory=dict)
    described_against_hash: str | None = None
    described_at: str | None = None


# --- ISO helpers -----------------------------------------------------------


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- Parser of existing .meta description layer ----------------------------
# This is the inverse of render_description_block() + render_meta()'s
# splice points. See research.md §5 for the line-by-line reader.


def parse_meta_descriptions(meta_text: str) -> MetaDescription | None:
    """Parse a .meta text and return its description layer, or None.

    Returns None when no description layer is present. Returns a
    MetaDescription dataclass when at least one of:
      - **Description:** <text>            (module-level)
      - Described-Against-Hash: <hash>
      - Described-At: <iso>
      - per-method `Id:`/`Description:` pairs inside `## Functions`
    is present.

    Tolerant of v1 .meta (no description layer at all) → returns None.
    """
    if not meta_text:
        return None

    module_description: str | None = None
    described_against_hash: str | None = None
    described_at: str | None = None
    method_descriptions: dict[str, str] = {}

    in_functions = False
    current_id: str | None = None

    for raw in meta_text.splitlines():
        line = raw  # preserve indentation for prefix checks

        if line.startswith("**Description:** "):
            module_description = line[len("**Description:** ") :]
            continue
        if line.startswith("Described-Against-Hash: "):
            described_against_hash = line[len("Described-Against-Hash: ") :].strip()
            continue
        if line.startswith("Described-At: "):
            described_at = line[len("Described-At: ") :].strip()
            continue

        # Section toggles
        if line.startswith("## Functions"):
            in_functions = True
            current_id = None
            continue
        if line.startswith("## ") and in_functions:
            in_functions = False
            current_id = None
            continue

        if in_functions:
            # Two indented forms accepted, per data-model.md §2.1:
            #   "  Id: <hex>"
            #   "  Description: <text>"
            if line.startswith("  Id: "):
                current_id = line[len("  Id: ") :].strip()
                continue
            if line.startswith("  Description: ") and current_id:
                method_descriptions[current_id] = line[len("  Description: ") :]
                current_id = None
                continue

    any_present = bool(
        module_description
        or described_against_hash
        or described_at
        or method_descriptions
    )
    if not any_present:
        return None

    return MetaDescription(
        module_description=module_description,
        method_descriptions=method_descriptions,
        described_against_hash=described_against_hash,
        described_at=described_at,
    )


# --- Renderer block (consumed by render_meta(...)) -------------------------


def render_description_block(desc: MetaDescription | None) -> dict:
    """Return the dict shape consumed by render_meta(... existing_descriptions=).

    Keys:
      - module_description: str | None
      - described_against_hash: str | None
      - described_at: str | None
      - method_descriptions: dict[id, str]    (alphabetical irrelevant)
    """
    if desc is None:
        return {
            "module_description": None,
            "described_against_hash": None,
            "described_at": None,
            "method_descriptions": {},
        }
    return {
        "module_description": desc.module_description,
        "described_against_hash": desc.described_against_hash,
        "described_at": desc.described_at,
        "method_descriptions": dict(desc.method_descriptions),
    }


# --- Threshold filter ------------------------------------------------------
# A method qualifies for description when:
#   - body_lines >= threshold (default 5), AND
#   - it doesn't look like a trivial getter/setter
#
# In v1 the parser does not currently emit an end_line per function. We
# approximate body_lines as `next_function.line - this_function.line`
# (or `file_lines - this_function.line` for the last one). For methods
# under a class we use `next_method.line - this_method.line`.


def _qualifying_methods(parsed: dict, threshold: int) -> list[dict]:
    """Return a list of method-bearing entries that meet `threshold`.

    Each entry: {"id": hex, "name": str, "scope": "" or class_name,
                 "line": int, "end_line": int, "params": [...],
                 "return_type": str|None, "body_lines": int}.
    """
    file_lines = int(parsed.get("lines", 0) or 0)

    # Build a flat list of (line, entry) tuples so we can sort by line
    # to derive `end_line` for each.
    flat: list[dict] = []
    for fn in parsed.get("functions") or []:
        flat.append(
            {
                "id": fn.get("id", ""),
                "name": fn.get("name", ""),
                "scope": "",
                "line": int(fn.get("line", 0) or 0),
                "params": fn.get("params") or [],
                "return_type": fn.get("return_type"),
            }
        )
    for cls in parsed.get("classes") or []:
        scope = cls.get("name", "")
        for m in cls.get("methods") or []:
            flat.append(
                {
                    "id": m.get("id", ""),
                    "name": m.get("name", ""),
                    "scope": scope,
                    "line": int(m.get("line", 0) or 0),
                    "params": m.get("params") or [],
                    "return_type": m.get("return_type"),
                }
            )
    flat.sort(key=lambda e: e["line"])

    # Derive end_line + body_lines.
    qualifying: list[dict] = []
    for idx, entry in enumerate(flat):
        if idx + 1 < len(flat):
            end = flat[idx + 1]["line"]
        else:
            end = file_lines + 1
        body = max(end - entry["line"], 0)
        entry["end_line"] = end
        entry["body_lines"] = body
        if not entry["id"]:
            continue
        if body < threshold:
            continue
        qualifying.append(entry)
    return qualifying


# --- Haiku call ------------------------------------------------------------


HaikuClient = Callable[[list[dict], str, str | None], str]
"""Type alias for the LLM call surface used in tests via dependency injection.

Signature: (messages, system_prompt, model) -> raw_text_response.
"""


class HaikuUnavailable(RuntimeError):
    pass


def _default_haiku_call(
    messages: list[dict],
    system_prompt: str,
    model: str,
    *,
    api_key: str | None = None,
    api_url: str = DEFAULT_API_URL,
    timeout: float = HTTP_TIMEOUT_S,
) -> str:
    """POST to Anthropic Messages API via stdlib urllib. Returns text."""
    key = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise HaikuUnavailable(
            "ANTHROPIC_API_KEY not set. Export it before running --describe."
        )

    # SMITH_ANTHROPIC_API_URL allows tests / proxies to redirect the endpoint
    # without monkey-patching meta_describe. Production callers leave this
    # unset.
    url = os.environ.get("SMITH_ANTHROPIC_API_URL", api_url)

    body = json.dumps(
        {
            "model": model,
            "max_tokens": 1024,
            "system": system_prompt,
            "messages": messages,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "x-api-key": key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="replace") if e.fp else str(e)
        raise HaikuUnavailable(f"Haiku HTTP {e.code}: {msg}") from e
    except urllib.error.URLError as e:
        raise HaikuUnavailable(f"Haiku connection error: {e}") from e

    # Anthropic Messages API: payload["content"] is a list of {type, text}.
    parts = payload.get("content") or []
    out: list[str] = []
    for p in parts:
        if isinstance(p, dict) and p.get("type") == "text":
            out.append(str(p.get("text", "")))
    return "".join(out).strip()


# --- Prompt construction ---------------------------------------------------
# Per research.md §6.

_MODULE_SYSTEM = (
    "You produce concise one-line summaries of source modules. "
    "Output ONLY a single line, no preamble, no markdown, no quotes. "
    f"Target ~{MODULE_DESC_SOFT_CAP} characters. Focus on the module's "
    "primary responsibility — what it does and when you'd open it."
)

_METHOD_SYSTEM = (
    "For each method below, produce a concise one-to-two-sentence "
    f"description (~{METHOD_DESC_SOFT_CAP} characters). Output ONLY a "
    "JSON object mapping the method id to the description string. No "
    "preamble, no markdown fences, no commentary."
)


def _summarize_for_module_prompt(parsed: dict, source: str) -> str:
    """Build the user-message body for the module description prompt."""
    imports = parsed.get("imports") or []
    functions = parsed.get("functions") or []
    classes = parsed.get("classes") or []

    bits: list[str] = []
    bits.append(f"File: {parsed.get('path', '')}")
    bits.append(f"Language: {parsed.get('language', '')}")
    bits.append(f"Lines: {parsed.get('lines', 0)}")
    if imports:
        bits.append("Imports:")
        for imp in imports[:12]:
            bits.append(f"  - {imp.get('name', '')}")
    if functions:
        bits.append("Top-level functions:")
        for fn in functions[:12]:
            bits.append(f"  - {fn.get('name', '')}")
    if classes:
        bits.append("Classes:")
        for c in classes[:8]:
            methods = [m.get("name", "") for m in (c.get("methods") or [])[:8]]
            joined = ", ".join(m for m in methods if m)
            bits.append(f"  - {c.get('name', '')}  (methods: {joined})")
    bits.append("")
    bits.append("First 30 lines of source:")
    head = "\n".join(source.splitlines()[:30])
    bits.append("```")
    bits.append(head)
    bits.append("```")
    return "\n".join(bits)


def _build_method_prompt(parsed: dict, source: str, methods: list[dict]) -> str:
    bits: list[str] = []
    bits.append(f"File: {parsed.get('path', '')}")
    bits.append("")
    bits.append("Methods to describe:")
    for m in methods:
        scope = m.get("scope") or ""
        signature_params = ", ".join(
            (
                f"{p.get('name', '')}"
                + (f": {p.get('type')}" if p.get("type") else "")
                + (f" = {p.get('default')}" if p.get("default") else "")
            )
            for p in (m.get("params") or [])
        )
        ret = m.get("return_type") or ""
        ret_s = f" -> {ret}" if ret else ""
        owner = f"{scope}::{m['name']}" if scope else m["name"]
        bits.append(
            f"- Id: {m['id']}\n"
            f"  Name: {owner}\n"
            f"  Signature: ({signature_params}){ret_s}\n"
            f"  Body lines: {m['line']}-{m['end_line']}"
        )
    bits.append("")
    bits.append("Full source for reference:")
    bits.append("```")
    bits.append(source)
    bits.append("```")
    return "\n".join(bits)


def _truncate(text: str, soft_cap: int, hard_cap: int) -> str:
    """Trim to a soft cap on natural breaks; hard-clip at the hard cap."""
    if not text:
        return ""
    one_line = " ".join(text.split())
    if len(one_line) <= soft_cap:
        return one_line
    # Walk back to last sentence break or space before soft_cap.
    cut = one_line[:soft_cap]
    for sep in (". ", "; ", ", ", " "):
        idx = cut.rfind(sep)
        if idx > soft_cap // 2:
            return cut[:idx].rstrip(",.; ").strip()
    if len(one_line) > hard_cap:
        return one_line[: hard_cap - 1] + "…"
    return one_line


# --- Description generation: public entrypoints ----------------------------


def describe_file(
    rel_path: str,
    source: str,
    parsed: dict,
    *,
    threshold: int = DEFAULT_THRESHOLD_LINES,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    client: HaikuClient | None = None,
) -> MetaDescription:
    """Bulk path entrypoint — describe all qualifying methods + module.

    Per data-model.md §4. Returns a populated MetaDescription. Errors
    on individual methods are logged but never crash the run; the
    affected method is omitted from `method_descriptions`.
    """
    return _describe(
        rel_path=rel_path,
        source=source,
        parsed=parsed,
        existing=None,
        touched_method_ids=None,
        purpose_shifted=True,
        threshold=threshold,
        model=model,
        api_key=api_key,
        client=client,
    )


def update_touched(
    rel_path: str,
    source: str,
    parsed: dict,
    existing: MetaDescription | None,
    touched_method_ids: set[str] | list[str] | None,
    purpose_shifted: bool,
    *,
    threshold: int = DEFAULT_THRESHOLD_LINES,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    client: HaikuClient | None = None,
) -> MetaDescription:
    """Workflow incremental path — describe only touched methods.

    Per Q11/A. Untouched method descriptions in `existing` are passed
    through verbatim. `purpose_shifted=True` triggers module description
    regeneration; False reuses existing module description.

    `touched_method_ids` may be None (treat as "no methods touched" —
    only module-level rerun if `purpose_shifted`).
    """
    touched: set[str] | None
    if touched_method_ids is None:
        touched = set()
    else:
        touched = set(touched_method_ids)

    return _describe(
        rel_path=rel_path,
        source=source,
        parsed=parsed,
        existing=existing,
        touched_method_ids=touched,
        purpose_shifted=purpose_shifted,
        threshold=threshold,
        model=model,
        api_key=api_key,
        client=client,
    )


def _describe(
    rel_path: str,
    source: str,
    parsed: dict,
    existing: MetaDescription | None,
    touched_method_ids: set[str] | None,
    purpose_shifted: bool,
    threshold: int,
    model: str,
    api_key: str | None,
    client: HaikuClient | None,
) -> MetaDescription:
    """Shared implementation for describe_file / update_touched."""
    if client is None:

        def client(messages, system_prompt, mdl):  # type: ignore[misc]
            return _default_haiku_call(messages, system_prompt, mdl, api_key=api_key)

    source_hash = _sha256(source)
    now = _iso_now()

    # Start from existing layer when present; defaults otherwise.
    base_methods: dict[str, str] = (
        dict(existing.method_descriptions) if existing else {}
    )
    base_module: str | None = existing.module_description if existing else None

    # --- Module description -------------------------------------------------
    new_module: str | None = base_module
    if purpose_shifted or base_module is None:
        try:
            prompt = _summarize_for_module_prompt(parsed, source)
            raw = client(
                [{"role": "user", "content": prompt}],
                _MODULE_SYSTEM,
                model,
            )
            if raw:
                new_module = _truncate(
                    raw, MODULE_DESC_SOFT_CAP, MODULE_DESC_SOFT_CAP * 2
                )
        except HaikuUnavailable as e:
            # Preserve existing module description on transient errors.
            print(
                f"meta_describe: module description skipped ({rel_path}): {e}",
                file=sys.stderr,
            )

    # --- Per-method descriptions -------------------------------------------
    qualifying = _qualifying_methods(parsed, threshold)
    if touched_method_ids is None:
        # Bulk: describe all qualifying methods that don't already have a
        # description hashed against the current source.
        targets = qualifying
    else:
        # Incremental: only ids in touched_method_ids, intersect with qualifying.
        targets = [m for m in qualifying if m["id"] in touched_method_ids]

    new_methods: dict[str, str] = dict(base_methods)

    # Drop stale entries for methods that no longer exist (id removed).
    live_ids = {m["id"] for m in qualifying}
    for stale_id in list(new_methods.keys()):
        if stale_id not in live_ids:
            new_methods.pop(stale_id, None)

    # Batch and call.
    for i in range(0, len(targets), METHODS_PER_LLM_CALL):
        batch = targets[i : i + METHODS_PER_LLM_CALL]
        try:
            prompt = _build_method_prompt(parsed, source, batch)
            raw = client(
                [{"role": "user", "content": prompt}],
                _METHOD_SYSTEM,
                model,
            )
            parsed_json = _safe_json_object(raw)
        except HaikuUnavailable as e:
            print(
                f"meta_describe: method batch skipped ({rel_path} batch={i}): {e}",
                file=sys.stderr,
            )
            continue

        for m in batch:
            mid = m["id"]
            desc = parsed_json.get(mid)
            if not isinstance(desc, str) or not desc.strip():
                continue
            new_methods[mid] = _truncate(
                desc, METHOD_DESC_SOFT_CAP, METHOD_DESC_SOFT_CAP * 2
            )

    return MetaDescription(
        module_description=new_module,
        method_descriptions=new_methods,
        described_against_hash=source_hash,
        described_at=now,
    )


def _safe_json_object(text: str) -> dict:
    """Parse a JSON object from a possibly-noisy LLM response.

    Strips common fence patterns and falls back to a brace-bounded slice.
    """
    if not text:
        return {}
    t = text.strip()
    # Strip code fences if present.
    if t.startswith("```"):
        # Drop first line up to newline.
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
    # Last resort: bracket-bounded.
    start = t.find("{")
    end = t.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(t[start : end + 1])
            return obj if isinstance(obj, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


# --- CLI entrypoint (T073) -------------------------------------------------


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _cli_update_touched(args: argparse.Namespace) -> int:
    """python3 meta_describe.py update-touched ..."""
    project_root = Path(args.root or ".").resolve()
    rel_path = args.rel_path
    src_path = project_root / rel_path
    if not src_path.exists():
        print(f"meta_describe: source not found: {src_path}", file=sys.stderr)
        return 2
    source = _read_text(src_path)

    # Invoke parser for this file via subprocess.
    import subprocess

    parser_dir = Path(__file__).resolve().parent
    ext = src_path.suffix
    if ext == ".py":
        cmd = ["python3", str(parser_dir / "parse-python.py"), str(src_path)]
    elif ext in (".js", ".jsx", ".ts", ".tsx"):
        cmd = ["node", str(parser_dir / "parse-js.js"), str(src_path)]
    else:
        print(f"meta_describe: unsupported extension {ext}", file=sys.stderr)
        return 2
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        print("meta_describe: parser timeout", file=sys.stderr)
        return 2
    if proc.returncode != 0:
        print(f"meta_describe: parser failed: {proc.stderr}", file=sys.stderr)
        return 2
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        print(f"meta_describe: parser JSON error: {e}", file=sys.stderr)
        return 2

    # Read existing .meta description layer if present.
    meta_path = project_root / ".smith" / "index" / "files" / f"{rel_path}.meta"
    existing: MetaDescription | None = None
    if meta_path.exists():
        existing = parse_meta_descriptions(_read_text(meta_path))

    touched = (
        set(s.strip() for s in args.touched_ids.split(",") if s.strip())
        if args.touched_ids
        else set()
    )
    purpose_shifted = (args.purpose_shifted or "false").lower() in (
        "true",
        "1",
        "yes",
    )

    desc = update_touched(
        rel_path=rel_path,
        source=source,
        parsed=parsed,
        existing=existing,
        touched_method_ids=touched,
        purpose_shifted=purpose_shifted,
        threshold=args.threshold,
        model=args.model,
        api_key=None,
    )
    print(json.dumps(render_description_block(desc), indent=2))
    return 0


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="meta_describe",
        description="Smith manifest description-layer helper",
    )
    sub = parser.add_subparsers(dest="cmd")

    upd = sub.add_parser(
        "update-touched",
        help="Regenerate descriptions for a single file's touched method ids",
    )
    upd.add_argument("--rel-path", required=True)
    upd.add_argument("--touched-ids", default="")
    upd.add_argument("--purpose-shifted", default="false")
    upd.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD_LINES)
    upd.add_argument("--model", default=DEFAULT_MODEL)
    upd.add_argument("--root", default=".")
    upd.set_defaults(func=_cli_update_touched)

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
