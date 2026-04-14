"""
workflow_summary_lib.py

Computes normalized token usage, estimated USD cost, and active duration for a
Smith primary workflow (smith-new, smith-bugfix, smith-debug). Called from
hooks/workflow-summary.sh — the bash wrapper handles stdin, gates, and
environment, then hands off to main() here.

Public functions are pure where possible and covered by tests in tests/.

Public contract (see specs/003-accurate-workflow-summary/):
  spec.md              — functional requirements
  data-model.md        — file formats and in-memory data structures
  contracts/workflow-summary-cli.md — CLI surface

Compatibility: Python 3.8+, stdlib only.
"""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Formula constants (FR-6, FR-10). Fixed weights — do not couple to pricing.
# ---------------------------------------------------------------------------

NORMALIZED_WEIGHTS = {
    "input": 1.0,
    "output": 5.0,
    "cache_create": 1.25,
    "cache_read": 0.1,
}

DEFAULT_IDLE_THRESHOLD_S = 120
DEFAULT_BASH_GAP_CAP_S = 600


# ---------------------------------------------------------------------------
# Core pure formulas
# ---------------------------------------------------------------------------


def normalize(usage: Optional[Dict[str, int]]) -> int:
    """Fixed-weight normalized-token count. Returns 0 for None/empty usage."""
    if not usage:
        return 0
    w = NORMALIZED_WEIGHTS
    n = (
        (usage.get("input_tokens") or 0) * w["input"]
        + (usage.get("output_tokens") or 0) * w["output"]
        + (usage.get("cache_creation_input_tokens") or 0) * w["cache_create"]
        + (usage.get("cache_read_input_tokens") or 0) * w["cache_read"]
    )
    return int(round(n))


def cost_usd(
    usage: Optional[Dict[str, int]], rates: Optional[Dict[str, float]]
) -> Optional[float]:
    """Per-session USD. Returns None if usage or rates is missing."""
    if not usage or not rates:
        return None
    inp = usage.get("input_tokens") or 0
    out = usage.get("output_tokens") or 0
    cw = usage.get("cache_creation_input_tokens") or 0
    cr = usage.get("cache_read_input_tokens") or 0
    return (
        inp * rates["input_per_mtok"]
        + out * rates["output_per_mtok"]
        + cw * rates["cache_write_5m_per_mtok"]
        + cr * rates["cache_read_per_mtok"]
    ) / 1_000_000.0


# ---------------------------------------------------------------------------
# Pricing table + fuzzy family match (FR-8, FR-8.1, FR-11)
# ---------------------------------------------------------------------------


def load_pricing(path: str) -> Optional[Dict[str, Any]]:
    """Load pricing.json. Returns None on any parse/IO failure (graceful degrade)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        return None
    # Pre-compile regex per entry for speed.
    compiled: List[Tuple[re.Pattern, Dict[str, float]]] = []
    for entry in data["models"]:
        if not isinstance(entry, dict):
            continue
        family = entry.get("family")
        if not isinstance(family, str):
            continue
        # Validate required rate fields.
        try:
            rates = {
                "input_per_mtok": float(entry["input_per_mtok"]),
                "output_per_mtok": float(entry["output_per_mtok"]),
                "cache_write_5m_per_mtok": float(entry["cache_write_5m_per_mtok"]),
                "cache_read_per_mtok": float(entry["cache_read_per_mtok"]),
            }
        except (KeyError, TypeError, ValueError):
            continue
        if any(v < 0 for v in rates.values()):
            continue  # Reject negative rates.
        # Convert pattern (with * wildcard) into anchored regex.
        pattern = "^" + re.escape(family).replace(r"\*", ".*") + "$"
        try:
            compiled.append((re.compile(pattern), rates))
        except re.error:
            continue
    data["_compiled_patterns"] = compiled
    return data


def match_family(
    model: Optional[str], pricing: Optional[Dict[str, Any]]
) -> Optional[Dict[str, float]]:
    """Return rates dict for the first pattern that matches `model`. None if no match."""
    if not model or not pricing:
        return None
    patterns = pricing.get("_compiled_patterns") or []
    for regex, rates in patterns:
        if regex.match(model):
            return rates
    return None


# ---------------------------------------------------------------------------
# Parent JSONL parsing (FR-1, FR-2)
# ---------------------------------------------------------------------------


def parse_ts(iso: str) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp. Returns None on failure."""
    if not iso:
        return None
    # Handle trailing Z (Zulu) which Python 3.11+ parses but 3.8+ needs help with.
    s = iso.replace("Z", "+00:00") if isinstance(iso, str) else ""
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def parse_parent_jsonl(
    path: str,
    start_utc: Optional[datetime],
    end_utc: Optional[datetime],
) -> Tuple[Optional[Dict[str, int]], Optional[str]]:
    """
    Stream parent JSONL line-by-line. Accumulate usage for assistant turns whose
    timestamp falls inside the [start_utc, end_utc] window. Returns
    (usage_dict_or_None, model_or_None).
    """
    if not path or not os.path.isfile(path):
        return None, None
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    model: Optional[str] = None
    saw_any = False
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") != "assistant":
                    continue
                if entry.get("isSidechain"):
                    continue
                ts = parse_ts(entry.get("timestamp"))
                if ts is None:
                    continue
                # Ensure tz-aware for comparison.
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if start_utc and ts < start_utc:
                    continue
                if end_utc and ts > end_utc:
                    continue
                msg = entry.get("message") or {}
                if msg.get("model"):
                    model = msg["model"]
                usage = msg.get("usage") or {}
                for k in totals:
                    totals[k] += usage.get(k) or 0
                saw_any = True
    except OSError:
        return None, None
    if not saw_any:
        return None, model
    return totals, model


def resolve_parent_jsonl(project_root: str, session_log_text: str) -> Optional[str]:
    """
    Locate the parent JSONL for the current workflow. Tries, in order:
      1. Any subagent sidechain path referenced in the session log — embeds
         the parent's sessionId in its directory name.
      2. Newest *.jsonl in ~/.claude/projects/<slug>/ whose first user turn's
         cwd matches project_root.
    Returns absolute path or None.
    """
    # Slug = project_root with '/' → '-', as used by Claude Code.
    slug = project_root.replace("/", "-")
    # The slug typically has a leading '-' because the path starts with '/'.
    home = os.path.expanduser("~")
    projects_dir = os.path.join(home, ".claude", "projects", slug)
    if not os.path.isdir(projects_dir):
        return None

    # Path 1: try to recover sessionId from a subagent sidechain path referenced
    # anywhere in the session log. Format:
    #   ~/.claude/projects/<slug>/<session-id>/subagents/agent-<id>.jsonl
    # We look for '<slug>/<uuid>/subagents'.
    if session_log_text:
        m = re.search(
            r"/\.claude/projects/[^/]+/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/subagents/",
            session_log_text,
        )
        if m:
            session_id = m.group(1)
            candidate = os.path.join(projects_dir, f"{session_id}.jsonl")
            if os.path.isfile(candidate):
                return candidate

    # Path 2: newest *.jsonl in the project slug dir.
    candidates = glob.glob(os.path.join(projects_dir, "*.jsonl"))
    if not candidates:
        return None
    candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    # Prefer one whose first user turn's cwd matches project_root.
    for candidate in candidates:
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("type") == "user" and entry.get("cwd") == project_root:
                        return candidate
                    # Only check the first few entries, then break.
                    break
        except OSError:
            continue
    # Fall back to newest regardless.
    return candidates[0]


# ---------------------------------------------------------------------------
# Session log parsing
# ---------------------------------------------------------------------------


_INVOKE_RE = re.compile(
    r"### \[(\d{2}:\d{2}:\d{2})\] /smith-(new|bugfix|debug) (invoked|invocation)"
)

# V2 subagent block: has all 8 fields starting with model.
_SUBAGENT_V2_RE = re.compile(
    r"### \[(\d{2}:\d{2}:\d{2})\] Subagent completed\n\n"
    r"\*\*Metrics:\*\*\n"
    r"- model: ([^\n]+)\n"
    r"- input_tokens: (\d+)\n"
    r"- output_tokens: (\d+)\n"
    r"- cache_creation_input_tokens: (\d+)\n"
    r"- cache_read_input_tokens: (\d+)\n"
    r"- tool_uses: (\d+)\n"
    r"- duration_ms: (\d+)\n"
    r"- total_tokens: (\d+)"
)

# V1 subagent block: legacy 3-field format.
_SUBAGENT_V1_RE = re.compile(
    r"### \[(\d{2}:\d{2}:\d{2})\] Subagent completed\n\n"
    r"\*\*Metrics:\*\*\n"
    r"- total_tokens: (\d+)\n"
    r"- tool_uses: (\d+)\n"
    r"- duration_ms: (\d+)"
)

# Metrics line: tool name + timestamp. Captures the tool and time for gap detection.
_METRICS_LINE_RE = re.compile(
    r"^- `\[(\d{2}:\d{2}:\d{2})\]` \*\*(\w+)\*\*", re.MULTILINE
)


def find_invocation(content: str) -> Optional[Tuple[str, str]]:
    """Return (HH:MM:SS, workflow_type) for the first smith invocation in the log, or None."""
    m = _INVOKE_RE.search(content)
    if not m:
        return None
    return m.group(1), m.group(2)


def parse_subagent_blocks(content: str) -> List[Dict[str, Any]]:
    """
    Extract all subagent-completion blocks. v2 blocks get full fields;
    v1 blocks get (index, model='unknown', usage=None, tool_uses, duration_ms, raw_total).
    Returns list in order of appearance.
    """
    rows: List[Dict[str, Any]] = []

    # We walk the content linearly and dispatch to v2 or v1 depending on what matches.
    # To avoid counting a v2 block twice (once as v2, once as v1 since v2's tail looks
    # like a v1 block), we first find all v2 matches with their spans, then find v1
    # matches whose span does not overlap any v2 match.
    v2_matches = list(_SUBAGENT_V2_RE.finditer(content))
    v2_spans = [(m.start(), m.end()) for m in v2_matches]

    for m in v2_matches:
        (_, model, inp, out, cw, cr, tu, dur, tot) = m.groups()
        usage = {
            "input_tokens": int(inp),
            "output_tokens": int(out),
            "cache_creation_input_tokens": int(cw),
            "cache_read_input_tokens": int(cr),
        }
        rows.append(
            {
                "span": (m.start(), m.end()),
                "model": (model or "unknown").strip(),
                "usage": usage,
                "tool_uses": int(tu),
                "duration_ms": int(dur),
                "raw_total": int(tot),
            }
        )

    for m in _SUBAGENT_V1_RE.finditer(content):
        # Skip if this v1 match is contained within a v2 match (v2's tail).
        if any(s <= m.start() and m.end() <= e for s, e in v2_spans):
            continue
        (_, tot, tu, dur) = m.groups()
        rows.append(
            {
                "span": (m.start(), m.end()),
                "model": "unknown",
                "usage": None,
                "tool_uses": int(tu),
                "duration_ms": int(dur),
                "raw_total": int(tot),
            }
        )

    # Sort by position in the log so the index reflects order of appearance.
    rows.sort(key=lambda r: r["span"][0])
    for i, r in enumerate(rows, start=1):
        r["index"] = i
        r.pop("span", None)
    return rows


def parse_tool_timestamps(content: str) -> List[Tuple[str, str]]:
    """Return [(HH:MM:SS, tool_name), ...] for every metrics-tracker line."""
    return [(m.group(1), m.group(2)) for m in _METRICS_LINE_RE.finditer(content)]


# ---------------------------------------------------------------------------
# Active duration (FR-12)
# ---------------------------------------------------------------------------


def _hms_to_seconds(hms: str) -> int:
    parts = hms.split(":")
    if len(parts) != 3:
        return 0
    try:
        h, m, s = (int(x) for x in parts)
    except ValueError:
        return 0
    return h * 3600 + m * 60 + s


def compute_active_duration(
    entries: List[Tuple[str, str]],
    idle: int = DEFAULT_IDLE_THRESHOLD_S,
    bash_cap: int = DEFAULT_BASH_GAP_CAP_S,
) -> int:
    """
    Sum gaps between consecutive metrics-tracker entries, excluding idle gaps.

    Algorithm:
      - For each pair (prev, curr), compute the wall-clock delta in seconds.
        The tool on curr (the 'current' entry) determines whether we apply
        the Bash cap to this gap, because curr is the tool that just
        finished — its execution caused the gap.
      - If curr is Bash: allow up to bash_cap seconds; anything above is treated
        as idle (user pause) and excluded.
      - For any other tool: if the delta > idle, exclude it entirely.
      - Sum the included deltas. Handle HH:MM:SS wrap-over-midnight by adding
        86400 when curr < prev.
    """
    if len(entries) < 2:
        return 0
    total = 0
    for i in range(1, len(entries)):
        prev_hms, _ = entries[i - 1]
        curr_hms, curr_tool = entries[i]
        delta = _hms_to_seconds(curr_hms) - _hms_to_seconds(prev_hms)
        if delta < 0:
            delta += 86400  # crossed midnight
        if delta <= 0:
            continue
        if curr_tool == "Bash":
            if delta <= bash_cap:
                total += delta
            else:
                # Gap exceeds the cap: include only the cap's worth (execution
                # time) and drop the excess (idle).
                total += bash_cap
        else:
            if delta <= idle:
                total += delta
            # else: gap treated as idle / user input wait; excluded entirely
    return total


# ---------------------------------------------------------------------------
# Formatting helpers (FR-15)
# ---------------------------------------------------------------------------


def format_tokens(n: int) -> str:
    """3.2M / 842.1K / 1,248."""
    if n < 0:
        n = 0
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 10_000:
        return f"{n / 1_000:.1f}K"
    return f"{n:,}"


def format_usd(dollars: float) -> str:
    return f"${dollars:,.2f} USD"


def format_duration(seconds: int) -> str:
    """1h5m35s / 12m04s / 42s."""
    if seconds < 0:
        seconds = 0
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m}m{s}s"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _unknown_suffix(n_priced: int, n_total: int, unknown_ids: List[str]) -> str:
    if not unknown_ids and n_priced == n_total:
        return ""
    models_part = ", ".join(unknown_ids) if unknown_ids else "unknown"
    return f" (priced: {n_priced} of {n_total} subagents — unknown: {models_part})"


def render_chat_block(totals: Dict[str, Any]) -> str:
    """Three-line chat block (FR-15)."""
    tok = format_tokens(totals["combined_normalized"])
    cost = format_usd(totals["combined_usd"])
    suffix = _unknown_suffix(
        totals["n_priced_sessions"],
        totals["n_total_sessions"],
        totals["unknown_model_ids"],
    )
    # FR-6 degenerate: if pricing.json missing entirely, say so explicitly.
    if totals.get("pricing_missing"):
        cost_line = "Est. cost: unavailable (pricing config missing)"
    else:
        cost_line = f"Est. cost: {cost}{suffix}"
    active = format_duration(totals["active_duration_s"])
    elapsed = format_duration(totals["total_elapsed_s"])
    return (
        f"Token Usage: {tok} normalized\n"
        f"{cost_line}\n"
        f"Active duration: {active} (total elapsed {elapsed})\n"
    )


def render_audit_block(
    totals: Dict[str, Any],
    files_changed: List[str],
    workflow_type: str,
    started_hms: str,
) -> str:
    """Full audit block appended to session log (FR-16)."""
    active = format_duration(totals["active_duration_s"])
    elapsed = format_duration(totals["total_elapsed_s"])
    tok = format_tokens(totals["combined_normalized"])
    cost_line = (
        "Est. cost: unavailable (pricing config missing)"
        if totals.get("pricing_missing")
        else "Est. cost: "
        + format_usd(totals["combined_usd"])
        + _unknown_suffix(
            totals["n_priced_sessions"],
            totals["n_total_sessions"],
            totals["unknown_model_ids"],
        )
    )

    raw = totals["combined_raw_components"]
    raw_total = totals["combined_raw_total"]

    lines: List[str] = []
    lines.append("")
    lines.append("")
    lines.append("=== Workflow Summary ===")
    lines.append("")
    lines.append(f"Workflow: /smith-{workflow_type}")
    lines.append(f"Started: {started_hms}")
    lines.append(f"Active duration: {active} (total elapsed {elapsed})")
    lines.append("")
    lines.append(f"Token Usage: {totals['combined_normalized']:,} normalized")
    lines.append(cost_line)
    lines.append("")
    lines.append("Raw Components (main + subagents combined):")
    lines.append(f"- input_tokens:                {raw['input_tokens']:>14,}")
    lines.append(f"- output_tokens:               {raw['output_tokens']:>14,}")
    lines.append(
        f"- cache_creation_input_tokens: {raw['cache_creation_input_tokens']:>14,}"
    )
    lines.append(
        f"- cache_read_input_tokens:     {raw['cache_read_input_tokens']:>14,}"
    )
    lines.append(f"- raw total:                   {raw_total:>14,}")
    lines.append("")

    # Main session block
    if totals["parent_usage"] is None:
        lines.append(
            "Main Session: (parent JSONL not found — main-session tokens not captured)"
        )
    else:
        pu = totals["parent_usage"]
        parent_raw = (
            pu["input_tokens"]
            + pu["output_tokens"]
            + pu["cache_creation_input_tokens"]
            + pu["cache_read_input_tokens"]
        )
        lines.append("Main Session:")
        lines.append(f"- Model:             {totals['parent_model'] or 'unknown'}")
        lines.append(f"- Tool calls:        {totals['parent_tool_calls']}")
        lines.append(f"- Raw tokens:        {parent_raw:,}")
        lines.append(f"- Normalized tokens: {totals['parent_normalized']:,}")
        parent_usd_fmt = (
            format_usd(totals["parent_usd"])
            if totals["parent_usd"] is not None
            else "—"
        )
        lines.append(f"- Est. cost:         {parent_usd_fmt}")
        lines.append(
            f"- Active duration:   {format_duration(totals['parent_active_duration_s'])}"
        )
    lines.append("")

    # Subagents table
    rows = totals["subagent_rows"]
    if rows:
        lines.append(f"Subagents ({len(rows)}):")
        header = (
            "  #  model                     tool_uses   input    output  "
            "cache_write  cache_read   raw_total  normalized  est_cost   duration"
        )
        lines.append(header)
        for r in rows:
            model_str = (r["model"] or "unknown")[:25].ljust(25)
            u = r["usage"]
            if u is None:
                inp_s = out_s = cw_s = cr_s = norm_s = cost_s = "—"
            else:
                inp_s = f"{u['input_tokens']:,}"
                out_s = f"{u['output_tokens']:,}"
                cw_s = f"{u['cache_creation_input_tokens']:,}"
                cr_s = f"{u['cache_read_input_tokens']:,}"
                norm_s = (
                    f"{r['normalized']:,}" if r.get("normalized") is not None else "—"
                )
                cost_s = (
                    format_usd(r["est_cost_usd"])
                    if r.get("est_cost_usd") is not None
                    else "—"
                )
            dur_s = format_duration(r["duration_ms"] // 1000)
            lines.append(
                f"  {r['index']:<2} {model_str} "
                f"{r['tool_uses']:>9} {inp_s:>8} {out_s:>9} "
                f"{cw_s:>12} {cr_s:>11} {r['raw_total']:>11,} {norm_s:>11} {cost_s:>10} {dur_s:>10}"
            )
        lines.append("")

    # Files changed
    lines.append("Files Changed:")
    if files_changed:
        display = files_changed[:30]
        for f in display:
            lines.append(f"  - {f}")
        if len(files_changed) > 30:
            lines.append(f"  - ... ({len(files_changed) - 30} more)")
    else:
        lines.append("  (none detected — may already be merged or no diff)")

    lines.append("")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Totals assembly
# ---------------------------------------------------------------------------


def assemble_totals(
    parent_usage: Optional[Dict[str, int]],
    parent_model: Optional[str],
    parent_tool_calls: int,
    parent_active_duration_s: int,
    subagent_rows: List[Dict[str, Any]],
    pricing: Optional[Dict[str, Any]],
    total_elapsed_s: int,
) -> Dict[str, Any]:
    """Compute every field needed by render_chat_block / render_audit_block."""
    # Main-session cost and normalized
    parent_rates = match_family(parent_model, pricing) if pricing else None
    parent_normalized = normalize(parent_usage)
    parent_usd = cost_usd(parent_usage, parent_rates)

    # Per-subagent enrichment
    enriched_rows: List[Dict[str, Any]] = []
    for r in subagent_rows:
        usage = r.get("usage")
        rates = match_family(r.get("model"), pricing) if pricing else None
        norm = normalize(usage) if usage is not None else None
        usd = cost_usd(usage, rates) if usage is not None else None
        enriched_rows.append(
            {
                **r,
                "normalized": norm,
                "est_cost_usd": usd,
            }
        )

    # Combined raw components
    combined = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    if parent_usage:
        for k in combined:
            combined[k] += parent_usage[k]
    for r in enriched_rows:
        if r["usage"]:
            for k in combined:
                combined[k] += r["usage"][k]
    combined_raw_total = sum(combined.values())

    # For subagents without a usage dict, their raw_total still contributes to
    # the combined raw number — fold it in.
    combined_raw_total += sum(
        r["raw_total"] for r in enriched_rows if r["usage"] is None
    )

    # Combined normalized
    combined_normalized = parent_normalized + sum(
        (r["normalized"] or 0) for r in enriched_rows
    )

    # Combined USD (sum priced sessions only)
    combined_usd = (parent_usd or 0.0) + sum(
        (r["est_cost_usd"] or 0.0) for r in enriched_rows
    )

    # Priced / unpriced accounting
    # A "session" = parent + each subagent. The parent counts only if we found its
    # JSONL (parent_usage != None).
    n_total = (1 if parent_usage is not None else 0) + len(enriched_rows)
    n_priced = 0
    unknown_ids_set: List[str] = []
    if parent_usage is not None:
        if parent_rates is not None:
            n_priced += 1
        else:
            unknown_ids_set.append(parent_model or "unknown")
    for r in enriched_rows:
        if r["est_cost_usd"] is not None:
            n_priced += 1
        else:
            unknown_ids_set.append(r["model"] or "unknown")
    unknown_ids = sorted(set(unknown_ids_set))

    # Active duration total = main active + sum of subagent durations (FR-12)
    subagent_durations_s = sum(r["duration_ms"] // 1000 for r in enriched_rows)
    active_total_s = parent_active_duration_s + subagent_durations_s

    return {
        "parent_usage": parent_usage,
        "parent_model": parent_model,
        "parent_tool_calls": parent_tool_calls,
        "parent_active_duration_s": parent_active_duration_s,
        "parent_normalized": parent_normalized,
        "parent_usd": parent_usd,
        "subagent_rows": enriched_rows,
        "combined_raw_components": combined,
        "combined_raw_total": combined_raw_total,
        "combined_normalized": combined_normalized,
        "combined_usd": combined_usd,
        "n_total_sessions": n_total,
        "n_priced_sessions": n_priced,
        "unknown_model_ids": unknown_ids,
        "total_elapsed_s": total_elapsed_s,
        "active_duration_s": active_total_s,
        "pricing_missing": pricing is None,
    }


# ---------------------------------------------------------------------------
# Git files-changed
# ---------------------------------------------------------------------------


def git_files_changed(project_root: str) -> List[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "main..HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass
    return []


# ---------------------------------------------------------------------------
# Window resolver
# ---------------------------------------------------------------------------


def resolve_workflow_window(
    session_log_path: str, session_log_text: str
) -> Tuple[Optional[datetime], datetime]:
    """
    Return (start_utc, end_utc) for the current workflow.
      start: invocation HH:MM:SS from the session log, promoted to UTC using
             the session-file date (YYYY-MM-DD_HHMMSS.md).
      end:   datetime.now(timezone.utc)
    """
    end_utc = datetime.now(timezone.utc)
    invoke = find_invocation(session_log_text)
    if invoke is None:
        return None, end_utc
    hms, _ = invoke
    fn = os.path.basename(session_log_path).replace(".md", "")
    try:
        date_part = fn.split("_")[0]  # YYYY-MM-DD
    except IndexError:
        return None, end_utc
    try:
        # Combine date + HH:MM:SS as UTC (matches how session logs are written).
        start_utc = datetime.strptime(
            f"{date_part} {hms}", "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        return None, end_utc
    return start_utc, end_utc


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def main() -> int:
    """
    Called by the bash wrapper. Reads env vars:
      SESSION_FILE   — absolute path to session log
      PROJECT_ROOT   — absolute path to project directory
      TOTALS_ONLY    — "1" for chat-block mode, else Stop-hook mode
    Writes to stdout and (in Stop-hook mode) appends to the session log.
    """
    session_file = os.environ.get("SESSION_FILE") or ""
    project_root = os.environ.get("PROJECT_ROOT") or os.getcwd()
    totals_only = os.environ.get("TOTALS_ONLY") == "1"

    if not session_file or not os.path.isfile(session_file):
        return 0

    content = _read(session_file)

    # Resolve the workflow window.
    start_utc, end_utc = resolve_workflow_window(session_file, content)
    invoke = find_invocation(content)
    if invoke is None:
        # Without an invocation we can't produce a meaningful summary.
        if totals_only:
            # Still emit the 3-line block in the degenerate form.
            degenerate = {
                "combined_normalized": 0,
                "combined_usd": 0.0,
                "combined_raw_components": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
                "combined_raw_total": 0,
                "parent_usage": None,
                "parent_model": None,
                "parent_tool_calls": 0,
                "parent_active_duration_s": 0,
                "parent_normalized": 0,
                "parent_usd": None,
                "subagent_rows": [],
                "total_elapsed_s": 0,
                "active_duration_s": 0,
                "n_total_sessions": 0,
                "n_priced_sessions": 0,
                "unknown_model_ids": [],
                "pricing_missing": False,
            }
            sys.stdout.write(render_chat_block(degenerate))
        return 0
    started_hms, workflow_type = invoke

    # Parse session-log components.
    subagent_rows = parse_subagent_blocks(content)
    tool_entries = parse_tool_timestamps(content)
    parent_tool_calls = len(tool_entries)
    parent_active_duration_s = compute_active_duration(tool_entries)

    # Elapsed = session file's timestamp → now.
    fn = os.path.basename(session_file).replace(".md", "")
    total_elapsed_s = 0
    try:
        start_dt = datetime.strptime(fn, "%Y-%m-%d_%H%M%S").replace(tzinfo=timezone.utc)
        total_elapsed_s = int((end_utc - start_dt).total_seconds())
    except ValueError:
        pass

    # Pricing table.
    pricing_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "pricing.json"
    )
    pricing = load_pricing(pricing_path)

    # Parent JSONL.
    parent_path = resolve_parent_jsonl(project_root, content)
    parent_usage: Optional[Dict[str, int]] = None
    parent_model: Optional[str] = None
    if parent_path:
        parent_usage, parent_model = parse_parent_jsonl(parent_path, start_utc, end_utc)

    totals = assemble_totals(
        parent_usage=parent_usage,
        parent_model=parent_model,
        parent_tool_calls=parent_tool_calls,
        parent_active_duration_s=parent_active_duration_s,
        subagent_rows=subagent_rows,
        pricing=pricing,
        total_elapsed_s=total_elapsed_s,
    )

    if totals_only:
        sys.stdout.write(render_chat_block(totals))
        return 0

    # Stop-hook mode: append full audit block to session log and echo to stdout.
    files_changed = git_files_changed(project_root)
    block = render_audit_block(totals, files_changed, workflow_type, started_hms)

    try:
        with open(session_file, "a", encoding="utf-8") as f:
            f.write(block)
    except OSError:
        pass
    sys.stdout.write(block)
    return 0


if __name__ == "__main__":
    sys.exit(main())
