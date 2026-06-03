#!/usr/bin/env python3
"""
meta_describe.py — Structural helpers for the Smith Manifest .meta
description layer.

v3 (spec/23-task-llm-backend) stripped this module of every LLM-call
code path. The bulk and incremental description loops now live in
skill prose (skills/smith-index/SKILL.md and the three workflow
SKILL.md files), spawning Task sub-agents that inherit Claude Code
session auth → subscription billing. This module is purely structural
— no HTTP client, no API key reads, no CLI entrypoint.

Public API (consumed by run.py, describe_discover.py, describe_write.py,
and hooks/manifest-updater-lib.py):

  Datatypes:
    MethodDescription, MetaDescription, MODULE_DESC_SOFT_CAP,
    METHOD_DESC_SOFT_CAP, DEFAULT_THRESHOLD_LINES

  Parsing the on-disk .meta description layer:
    parse_meta_descriptions(meta_text) -> MetaDescription | None
    render_description_block(desc) -> dict

  Prompt assembly (used by describe_write.py build-prompt):
    qualifying_methods(parsed, threshold) -> list[dict]
    summarize_for_module_prompt(parsed, source) -> str
    build_method_prompt(parsed, source, methods) -> str
    truncate(text, soft_cap, hard_cap) -> str
    MODULE_SYSTEM, METHOD_SYSTEM (system-prompt constants)

Per data-model.md §4 (LLM-layer contract) and research.md §6 (prompt
design). Per spec/23-task-llm-backend Q6: there is NO direct-HTTPS
fallback. All LLM calls in v3 go through Task spawning by the
orchestrating skill prose.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone


# --- Soft caps (per data-model.md §2.2) ------------------------------------

MODULE_DESC_SOFT_CAP = 120
METHOD_DESC_SOFT_CAP = 200
DEFAULT_THRESHOLD_LINES = 5


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


# --- ISO + hash helpers ----------------------------------------------------


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- Parser of existing .meta description layer ----------------------------


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

    in_method_section = False
    current_id: str | None = None

    for raw in meta_text.splitlines():
        line = raw

        if line.startswith("**Description:** "):
            module_description = line[len("**Description:** ") :]
            continue
        if line.startswith("Described-Against-Hash: "):
            described_against_hash = line[len("Described-Against-Hash: ") :].strip()
            continue
        if line.startswith("Described-At: "):
            described_at = line[len("Described-At: ") :].strip()
            continue

        if line.startswith("## Functions") or line.startswith("## Classes"):
            in_method_section = True
            current_id = None
            continue
        if line.startswith("## ") and in_method_section:
            in_method_section = False
            current_id = None
            continue

        if in_method_section:
            stripped = line.lstrip()
            indent_len = len(line) - len(stripped)
            if indent_len >= 2:
                if stripped.startswith("Id: "):
                    current_id = stripped[len("Id: ") :].strip()
                    continue
                if stripped.startswith("Description: ") and current_id:
                    method_descriptions[current_id] = stripped[len("Description: ") :]
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
      - method_descriptions: dict[id, str]
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


def qualifying_methods(
    parsed: dict, threshold: int = DEFAULT_THRESHOLD_LINES
) -> list[dict]:
    """Return a list of method-bearing entries that meet `threshold`.

    Each entry: {"id": hex, "name": str, "scope": "" or class_name,
                 "line": int, "end_line": int, "params": [...],
                 "return_type": str|None, "body_lines": int}.
    """
    file_lines = int(parsed.get("lines", 0) or 0)

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


# --- Prompt construction (system prompts + body builders) ------------------


MODULE_SYSTEM = (
    "You produce concise one-line summaries of source modules. "
    "Output ONLY a single line, no preamble, no markdown, no quotes. "
    f"Target ~{MODULE_DESC_SOFT_CAP} characters. Focus on the module's "
    "primary responsibility — what it does and when you'd open it."
)

METHOD_SYSTEM = (
    "For each method below, produce a concise one-to-two-sentence "
    f"description (~{METHOD_DESC_SOFT_CAP} characters). Output ONLY a "
    "JSON object mapping the method id to the description string. No "
    "preamble, no markdown fences, no commentary."
)


def summarize_for_module_prompt(parsed: dict, source: str) -> str:
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


def build_method_prompt(parsed: dict, source: str, methods: list[dict]) -> str:
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


def truncate(text: str, soft_cap: int, hard_cap: int) -> str:
    """Trim to a soft cap on natural breaks; hard-clip at the hard cap."""
    if not text:
        return ""
    one_line = " ".join(text.split())
    if len(one_line) <= soft_cap:
        return one_line
    cut = one_line[:soft_cap]
    for sep in (". ", "; ", ", ", " "):
        idx = cut.rfind(sep)
        if idx > soft_cap // 2:
            return cut[:idx].rstrip(",.; ").strip()
    if len(one_line) > hard_cap:
        return one_line[: hard_cap - 1] + "…"
    return one_line


# Backward-compatibility aliases — preserve PR #21 test imports + any
# in-repo callers that referenced the previously-private names. Marked
# DEPRECATED in docstring; remove in v3.1.

_qualifying_methods = qualifying_methods
_summarize_for_module_prompt = summarize_for_module_prompt
_build_method_prompt = build_method_prompt
_truncate = truncate
_MODULE_SYSTEM = MODULE_SYSTEM
_METHOD_SYSTEM = METHOD_SYSTEM
_iso_now = iso_now
_sha256 = sha256
