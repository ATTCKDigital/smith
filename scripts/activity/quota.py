"""`QuotaWindows` — FR-35 / data-model.md §2.9.

Split out of ``usage.py`` on the 500-line decompose rule; ``usage`` re-exports
``quota_windows`` so the module that owns tokens and cost still owns the
import surface the rest of the feature was written against.

The statusline payload is the ONLY authoritative source for the 5-hour and
7-day rolling windows — there is no API, no file and no CLI that reports them.
That single-sourcing is the whole design constraint here: this module cannot
fall back to anything, so its absent case has to be a real, rendered state
rather than a zero.

Python 3.8, stdlib only.
"""

from typing import Any, Dict, Optional

QUOTA_WINDOWS = ("five_hour", "seven_day", "spend_limit")


def _window(raw) -> Optional[Dict[str, Any]]:
    """One ``{used_percentage, resets_at}`` window, or ``None``.

    A window missing ``used_percentage`` is ``None`` outright — it carries no
    usable signal. A window missing only ``resets_at`` still renders its
    percentage with an unknown reset, because the percentage is the number the
    operator is actually watching.
    """
    if not isinstance(raw, dict):
        return None
    try:
        used = float(raw["used_percentage"])
    except (KeyError, TypeError, ValueError):
        return None
    try:
        # Epoch SECONDS, not ISO-8601 — the UI formats it, this does not.
        resets_at = int(raw["resets_at"])
    except (KeyError, TypeError, ValueError):
        resets_at = None
    return {"used_percentage": used, "resets_at": resets_at}


def quota_windows(payload, received_at: Optional[str] = None) -> Dict[str, Any]:
    """Parse ``rate_limits`` out of a statusline payload (data-model.md §4.4).

    ``rate_limits`` is absent before the first API response and on
    non-subscription auth, and that absence is a first-class state:
    ``available: false``, the quota panel says so explicitly, and **nothing
    else on the dashboard degrades** (FR-35/SC-12). An "unavailable" quota
    panel beside eight working ones is the correct picture; a quota panel
    reading 0% beside them is a lie.

    These windows are ACCOUNT-WIDE. The daemon returns this object unchanged
    under every ``?project=`` filter (FR-3) — scoping it to a project would
    imply a per-project quota that does not exist.
    """
    rate_limits = payload.get("rate_limits") if isinstance(payload, dict) else None
    windows = {name: _window((rate_limits or {}).get(name)) for name in QUOTA_WINDOWS}
    result = dict(windows)
    result["available"] = any(value is not None for value in windows.values())
    result["received_at"] = received_at
    return result
