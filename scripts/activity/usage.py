"""Tokens, cost and quota (FR-32..FR-36) — the one module that touches pricing.

Three things here are traps rather than features, and each is guarded by a test
rather than by a comment alone:

1. **`match_family()` reads a key only `load_pricing()` writes.**
   `workflow_summary_lib:122` injects ``_compiled_patterns`` and ``:134`` reads
   it back as ``.get(…) or []``. A plain ``json.load()`` of ``pricing.json``
   therefore produces a dict that *looks* complete, matches nothing, raises
   nothing, and logs nothing — every model resolves to ``None`` and USD just
   stops appearing. Nothing in this package may parse ``pricing.json``
   directly; ``tests/activity/test_usage.py`` greps for it.

2. **Cache-read rates are not derivable.** Most families price cache reads at
   0.1x base input; Fable 5.1 and Mythos 5.1 are 0.025x and Opus 5.5 is 0.05x.
   That is why rates are transcribed from the published table and carry
   ``last_verified``, and why this module never computes a rate.

3. **An unmatched model must cost ``None``, never ``0.0``** (FR-34). Zero is
   indistinguishable from "free" at the render layer, so a missing family would
   silently understate spend instead of declaring itself. ``usd=None`` renders
   as *unavailable*; ``usd_complete=False`` marks a total that is priced but
   incomplete.

**`hooks/workflow_summary_lib.py` is imported and called, never edited**
(FR-33/FR-36, D-6) — five existing ``tests/test_*.py`` pin its behavior.

Python 3.8, stdlib only.
"""

import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import paths

# ---------------------------------------------------------------------------
# workflow_summary_lib import ladder (T058)
# ---------------------------------------------------------------------------
# The same three candidates, in the same order, as hooks/workflow-summary.sh:
# 198-214 — $CLAUDE_HOOKS_DIR, ~/.claude/hooks, then the repo checkout. A single
# copy of this module works from either an install or a worktree.

_REPO_HOOKS = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "hooks")
)


def hook_dir() -> Optional[str]:
    """The first directory on the ladder that actually holds the lib."""
    for candidate in (
        os.environ.get("CLAUDE_HOOKS_DIR") or "",
        os.path.join(paths.claude_home(), "hooks"),
        _REPO_HOOKS,
    ):
        if candidate and os.path.isfile(
            os.path.join(candidate, "workflow_summary_lib.py")
        ):
            return candidate
    return None


def _import_lib():
    directory = hook_dir()
    if directory and directory not in sys.path:
        sys.path.insert(0, directory)
    import workflow_summary_lib  # noqa: E402  (deliberately late — needs the path)

    return workflow_summary_lib


W = _import_lib()

USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)

# ---------------------------------------------------------------------------
# Pricing (T059)
# ---------------------------------------------------------------------------

PRICING_REFRESH_S = 60.0

_pricing = {"path": None, "table": None, "mtime": None, "checked": 0.0}


def pricing_path() -> str:
    """``<hook dir>/pricing.json`` — installed beside the lib that reads it."""
    directory = hook_dir() or _REPO_HOOKS
    return os.path.join(directory, "pricing.json")


def load_pricing(path: Optional[str] = None, now: Optional[float] = None):
    """The ONLY way this package obtains rates (FR-33).

    Loaded once, then re-stat'ed at most once per ``PRICING_REFRESH_S`` and
    re-read only when the mtime actually moved. The throttle is on the *stat*,
    not on the parse: a dashboard frame must never pay for either.

    Returns ``None`` when the file is missing or unparseable, which the
    renderers already distinguish from "priced at zero".
    """
    path = path or pricing_path()
    now = time.time() if now is None else now
    if _pricing["path"] == path and _pricing["table"] is not None:
        if now - _pricing["checked"] < PRICING_REFRESH_S:
            return _pricing["table"]
    _pricing["checked"] = now
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = None
    if _pricing["path"] == path and _pricing["mtime"] == mtime and mtime is not None:
        return _pricing["table"]
    _pricing.update({"path": path, "mtime": mtime, "table": W.load_pricing(path)})
    return _pricing["table"]


def reset_pricing_cache() -> None:
    """Drop the memo. For tests and for a `ConfigChange`-driven invalidation."""
    _pricing.update({"path": None, "table": None, "mtime": None, "checked": 0.0})


# "Caller did not supply a table" — distinct from "caller supplied None".
# ``load_pricing()`` returns None for a missing or unparseable file, and a
# plain ``table=None`` default would quietly swap that answer for the global
# table: a caller testing the degraded path would silently get the healthy
# one. That substitution is the same class of bug as the _compiled_patterns
# trap above, so it gets a sentinel rather than a convention.
_UNSET = object()


def rates_for(model: Optional[str], table=_UNSET) -> Optional[Dict[str, float]]:
    """Rates for one model id, or ``None``. Always via ``match_family``."""
    return W.match_family(model, load_pricing() if table is _UNSET else table)


# ---------------------------------------------------------------------------
# Usage accumulation
# ---------------------------------------------------------------------------


def new_usage() -> Dict[str, int]:
    return {key: 0 for key in USAGE_KEYS}


def add_usage(dst: Dict[str, int], src: Optional[Dict[str, Any]]) -> Dict[str, int]:
    for key in USAGE_KEYS:
        dst[key] += (src or {}).get(key) or 0
    return dst


def _accumulate_rows(lines, want_sidechain: bool) -> Dict[str, Dict[str, int]]:
    """Per-model usage over assistant rows. The core of FR-36.

    This is ``parse_parent_jsonl``'s accumulation loop with the ``isSidechain``
    guard parameterised: ``want_sidechain=False`` reproduces the parent-side
    behavior exactly (that equivalence is asserted in ``test_usage.py``), and
    ``want_sidechain=True`` is the inversion FR-36 requires — the parent
    transcript contains ZERO sidechain rows, so without it a running subagent
    reports 0 tokens until ``SubagentStop``.

    Keyed by model because a rollup routinely spans several: a total priced at
    one model's rate would be wrong, and a single ``model`` field cannot say so.

    Malformed lines are skipped, never fatal. That is not politeness — a live
    transcript is being appended to while this reads it, so a torn final line
    is the normal case, not the exceptional one.
    """
    per_model: Dict[str, Dict[str, int]] = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(entry, dict) or entry.get("type") != "assistant":
            continue
        if bool(entry.get("isSidechain")) != want_sidechain:
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        usage = message.get("usage")
        if not isinstance(usage, dict):
            continue
        model = message.get("model") or "unknown"
        add_usage(per_model.setdefault(model, new_usage()), usage)
    return per_model


# ---------------------------------------------------------------------------
# Incremental tailing (FR-32/FR-36)
# ---------------------------------------------------------------------------

_offsets: Dict[str, int] = {}


def reset_offsets() -> None:
    _offsets.clear()


def tail_lines(path: str, key: Optional[str] = None) -> Tuple[List[str], int]:
    """New COMPLETE lines since the remembered offset, plus the new offset.

    Rows reach hundreds of KB and files hundreds of rows, so nothing re-reads
    from byte zero. Two properties make that safe:

    * **A torn final line is never consumed.** The offset only ever advances to
      the end of the last line that ended in a newline, so the next call sees
      that line whole. Consuming it would lose the row permanently — the tail
      never looks back.
    * **Truncation resets.** If the file is now shorter than the remembered
      offset it was rotated or rewritten, so the offset drops to 0 rather than
      seeking past EOF and reporting silence forever.
    """
    key = key or path
    start = _offsets.get(key, 0)
    try:
        size = os.path.getsize(path)
    except OSError:
        return [], start
    if size < start:
        start = 0
    try:
        with open(path, "rb") as handle:
            handle.seek(start)
            chunk = handle.read()
    except OSError:
        return [], start
    if not chunk:
        _offsets[key] = start
        return [], start
    cut = chunk.rfind(b"\n")
    if cut < 0:
        _offsets[key] = start  # nothing complete yet
        return [], start
    complete = chunk[: cut + 1]
    end = start + len(complete)
    _offsets[key] = end
    return complete.decode("utf-8", "replace").splitlines(), end


# ---------------------------------------------------------------------------
# TokenRollup (T060 / T061, data-model.md §2.7)
# ---------------------------------------------------------------------------


def make_rollup(per_model, scope: str, table=_UNSET) -> Dict[str, Any]:
    """Build a ``TokenRollup`` from ``{model: usage}``.

    ``usd`` is ``None`` when NOTHING in the rollup could be priced — never
    ``0.0`` (FR-34). When some models priced and others did not, ``usd`` is the
    partial sum and ``usd_complete`` is ``False``: a floor is more useful than a
    blank, provided the renderer is told it is a floor. ``unknown_models``
    names every id that went unpriced.
    """
    table = load_pricing() if table is _UNSET else table
    totals = new_usage()
    unknown: List[str] = []
    priced_usd = 0.0
    n_priced = 0
    for model, usage in (per_model or {}).items():
        add_usage(totals, usage)
        rates = W.match_family(model, table)
        if rates is None:
            unknown.append(model)
            continue
        value = W.cost_usd(usage, rates)
        if value is not None:
            priced_usd += value
            n_priced += 1
    # The model a single-model rollup is "of"; for a mixed rollup, the one that
    # contributed the most normalized tokens, so the label names the dominant
    # cost rather than whichever row happened to be parsed last.
    model_label = None
    if per_model:
        model_label = max(per_model, key=lambda m: W.normalize(per_model[m]))
    return {
        "scope": scope,
        "input": totals["input_tokens"],
        "output": totals["output_tokens"],
        "cache_write": totals["cache_creation_input_tokens"],
        "cache_read": totals["cache_read_input_tokens"],
        "normalized": W.normalize(totals),
        "usd": priced_usd if n_priced else None,
        "usd_complete": not unknown,
        "model": model_label,
        "models": sorted(per_model or {}),
        "unknown_models": sorted(set(unknown)),
        "pricing_available": table is not None,
    }


def merge_rollups(rollups, scope: str) -> Dict[str, Any]:
    """Sum rollups WITHOUT re-pricing — used by the ``workflow`` scope.

    ``usd`` stays ``None`` only if every part was ``None``; otherwise it is the
    sum of the parts that had one, and ``usd_complete`` is the AND of the parts.
    Re-deriving USD from the merged token totals would be wrong the moment two
    parts used different models.
    """
    out = {
        "scope": scope,
        "input": 0,
        "output": 0,
        "cache_write": 0,
        "cache_read": 0,
        "normalized": 0,
        "usd": None,
        "usd_complete": True,
        "model": None,
        "models": [],
        "unknown_models": [],
        "pricing_available": True,
    }
    models: Dict[str, int] = {}
    for part in rollups or []:
        if not part:
            continue
        for key in ("input", "output", "cache_write", "cache_read", "normalized"):
            out[key] += part.get(key) or 0
        if part.get("usd") is not None:
            out["usd"] = (out["usd"] or 0.0) + part["usd"]
        if not part.get("usd_complete", True):
            out["usd_complete"] = False
        if not part.get("pricing_available", True):
            out["pricing_available"] = False
        out["unknown_models"].extend(part.get("unknown_models") or [])
        for model in part.get("models") or []:
            models[model] = models.get(model, 0) + (part.get("normalized") or 0)
    if out["unknown_models"]:
        out["usd_complete"] = False
    out["unknown_models"] = sorted(set(out["unknown_models"]))
    out["models"] = sorted(models)
    out["model"] = max(models, key=lambda m: models[m]) if models else None
    return out


# ---------------------------------------------------------------------------
# session scope (T060)
# ---------------------------------------------------------------------------

_session_cache: Dict[str, Tuple[float, Dict[str, Dict[str, int]]]] = {}
SESSION_REFRESH_S = 2.0


def reset_session_cache() -> None:
    _session_cache.clear()


def session_usage(
    transcript: str,
    now: Optional[float] = None,
    min_interval: float = SESSION_REFRESH_S,
) -> Dict[str, Dict[str, int]]:
    """Per-model parent-transcript usage, accumulated incrementally.

    The FIRST read of a transcript goes through ``parse_parent_jsonl`` — the
    reused, characterization-tested path (FR-33/T070) — over the whole file with
    a ``None`` window. Subsequent reads add only the bytes that arrived since,
    which is what keeps a 1 s dashboard tick off a hundreds-of-KB file.

    **No window is applied and no timestamp is compared** (FR-58). Session scope
    is "everything this session has spent"; a window would reintroduce clock
    comparison, and the session log this feature reads elsewhere mixes UTC hook
    writes with model-local wall time.
    """
    now = time.time() if now is None else now
    cached = _session_cache.get(transcript)
    if cached and now - cached[0] < min_interval:
        return cached[1]
    per_model = dict(cached[1]) if cached else {}
    if not cached:
        # Prime from the reused lib function, then remember where it stopped.
        usage, model = W.parse_parent_jsonl(transcript, None, None)
        try:
            _offsets[transcript] = os.path.getsize(transcript)
        except OSError:
            _offsets[transcript] = 0
        if usage:
            per_model[model or "unknown"] = dict(usage)
    else:
        lines, _ = tail_lines(transcript)
        for model, usage in _accumulate_rows(lines, want_sidechain=False).items():
            add_usage(per_model.setdefault(model, new_usage()), usage)
    _session_cache[transcript] = (now, per_model)
    return per_model


def session_rollup(transcript: str, table=_UNSET, now: Optional[float] = None):
    return make_rollup(session_usage(transcript, now=now), "session", table)


# ---------------------------------------------------------------------------
# subagent scope — FR-36, the inverted guard (T062)
# ---------------------------------------------------------------------------

_subagent_totals: Dict[str, Dict[str, Dict[str, int]]] = {}


def reset_subagent_cache() -> None:
    _subagent_totals.clear()


def subagent_usage(jsonl_path: str) -> Dict[str, Dict[str, int]]:
    """Per-model sidechain usage for one ``agent-<id>.jsonl``, incrementally.

    Unlike the parent transcript there is no lib function to prime from:
    ``parse_parent_jsonl`` skips exactly these rows. Totals accumulate across
    calls in ``_subagent_totals`` so a file that is still being written reports
    a rising number rather than only its newest chunk.
    """
    per_model = _subagent_totals.setdefault(jsonl_path, {})
    lines, _ = tail_lines(jsonl_path)
    for model, usage in _accumulate_rows(lines, want_sidechain=True).items():
        add_usage(per_model.setdefault(model, new_usage()), usage)
    return per_model


def subagent_rollup(jsonl_path: str, table=_UNSET) -> Dict[str, Any]:
    return make_rollup(subagent_usage(jsonl_path), "subagent", table)


# ---------------------------------------------------------------------------
# workflow scope (T063)
# ---------------------------------------------------------------------------


def historical_subagent_usage(
    session_log_text: str, before_offset: Optional[int] = None
) -> Dict[str, Dict[str, int]]:
    """Per-model usage from ``Subagent completed`` blocks already in the log.

    These are agents that finished before the daemon started, so no live
    transcript tail will ever see them. Slicing the text at ``before_offset``
    — the daemon's own start position in the log — is what keeps them from
    being counted a second time by the live tail; ``parse_subagent_blocks`` is
    then called unmodified on the prefix (FR-33: reuse, do not reimplement).

    v1 blocks carry only ``total_tokens`` and no per-field usage, so they
    contribute nothing here and are reported by the caller as unpriceable
    rather than folded in at a guessed split.
    """
    text = session_log_text or ""
    if before_offset is not None:
        text = text[:before_offset]
    per_model: Dict[str, Dict[str, int]] = {}
    for block in W.parse_subagent_blocks(text):
        usage = block.get("usage")
        if not usage:
            continue
        model = block.get("model") or "unknown"
        add_usage(per_model.setdefault(model, new_usage()), usage)
    return per_model


def workflow_rollup(
    transcripts=(),
    subagent_jsonls=(),
    session_log_text: str = "",
    before_offset: Optional[int] = None,
    table=_UNSET,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """FR-14-attributed sessions + attributed subagents + finished-before-us.

    The caller passes only what T047's attribution assigned to THIS workflow;
    this function never decides attribution. That separation is what makes
    SC-2 hold — two concurrent workflows in one repo share a session log and a
    transcript directory, and the only thing keeping their numbers apart is
    which paths each one is handed.
    """
    table = load_pricing() if table is _UNSET else table
    parts = [session_rollup(path, table, now=now) for path in transcripts or []]
    parts += [subagent_rollup(path, table) for path in subagent_jsonls or []]
    historical = historical_subagent_usage(session_log_text, before_offset)
    if historical:
        parts.append(make_rollup(historical, "subagent", table))
    return merge_rollups(parts, "workflow")


# Re-exports. FR-27's sidecar reader (T066) and FR-35's quota model (T067)
# belong to this module's API — tasks.md places them here — but the file hit
# the 500-line decompose threshold, so the bodies live in subagents.py and
# quota.py. Imported at the BOTTOM so the split is invisible to callers.
from quota import QUOTA_WINDOWS, quota_windows  # noqa: E402,F401
from subagents import elapsed_s, list_sidecars, read_sidecar  # noqa: E402,F401
