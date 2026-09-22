"""The three FR-37 friction counters, and the honesty that has to ship with
them.

Split out of ``vault.py`` on the repo's 500-line decompose rule; ``vault``
re-exports ``friction`` so the import surface is unchanged.

**Two of the three counters cannot work, and that is the most important thing
in this file.** FR-37 asks for workflow-gate denials, security-guard blocks
and grade-response retries, all counted from the shared
``~/.smith/logs/hooks.log``. But only THREE of the repo's twenty hooks write
to that log at all — ``context-loader.sh``, ``manifest-updater.sh`` and
``workflow-gate.sh`` (verified: those are the only files under ``hooks/``
containing the string ``hooks.log``). So:

* ``gate_denials`` is real. ``workflow-gate.sh:174`` logs every DENY.
* ``security_blocks`` is structurally 0. ``security-guard-bash.sh`` and
  ``security-guard-files.sh`` never write to the log.
* ``grade_retries`` is structurally 0. ``grade-response.sh`` never writes to
  the log.

A counter that reads 0 because nothing happened and a counter that reads 0
because nothing is instrumented look identical on a dashboard and mean
opposite things — and this dashboard's entire premise is not reporting the
second as the first. So the counts ship with ``observable`` and
``unobservable`` lists, derived EMPIRICALLY from which hook names the log has
actually carried, and a ``note`` naming the difference in words.

Fixing it properly means either making every hook log a line, or inferring
firing from the event stream plus the settings wiring. Both are design
decisions beyond this module; what is not acceptable is shipping the zero
silently.

Python 3.8, stdlib only.
"""

import os
import re
import threading
from typing import Any, Dict, Optional

import paths

#: The friction hooks by the basename they log under — no ``.sh``, because
#: that is the shape ``hooks.log`` uses.
FRICTION_HOOKS = {
    "gate_denials": ("workflow-gate",),
    "security_blocks": ("security-guard-bash", "security-guard-files"),
    "grade_retries": ("grade-response",),
}

#: Bound on the backward scan that decides which hooks have EVER reported.
#: The operator's log is ~26k lines; the tail is enough to answer "does this
#: hook write here at all" and stays bounded however far the log grows.
OBSERVABILITY_TAIL_BYTES = 1 << 20

#: ``<ISO8601Z> <hookname> ...`` **and** ``[<ISO8601Z>] <hookname> ...``.
#: ``data-model.md`` §2.8 documents only the first shape; ``workflow-gate.sh``
#: writes the second, with the stamp in brackets. A parser that knew only the
#: documented shape would report zero gate denials with the log sitting there
#: full of them — which is exactly the failure this whole feature is about,
#: committed by the feature itself.
LOG_LINE = re.compile(r"^\[?(\d{4}-\d{2}-\d{2}T[0-9:]+Z)\]?\s+([A-Za-z0-9._-]+)\b")

_LOCK = threading.RLock()
_observable = None  # type: Optional[set]


def reset_cache() -> None:
    global _observable
    with _LOCK:
        _observable = None


def hooks_log_path() -> str:
    return os.path.join(paths.smith_home(), "logs", "hooks.log")


def observable_hooks() -> Optional[set]:
    """Hook names that have ever appeared in ``hooks.log``, or ``None``.

    Empirical on purpose. The question is not "does this hook exist" — they
    all do — but "does it report", and the only honest way to answer that is
    to look at whether it ever has.

    ``None`` means the log could not be read at all, which makes EVERY
    counter unobservable rather than zero. An empty set is a different
    answer: the log is readable and has carried nothing.
    """
    global _observable
    with _LOCK:
        if _observable is not None:
            return _observable
    path = hooks_log_path()
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            fh.seek(max(0, size - OBSERVABILITY_TAIL_BYTES))
            raw = fh.read()
    except OSError:
        return None
    seen = set()
    for line in raw.decode("utf-8", "replace").splitlines():
        match = LOG_LINE.match(line)
        if match:
            seen.add(match.group(2))
    with _LOCK:
        _observable = seen
    return seen


def friction(start_offset: Optional[int] = None) -> Dict[str, Any]:
    """The three counters over the session window, plus what they mean.

    ``start_offset`` is the byte offset the daemon recorded at start. Without
    one the whole log is counted, which is right for a one-shot read and
    wrong for a live panel, so the daemon always passes it.
    """
    path = hooks_log_path()
    try:
        with open(path, "rb") as fh:
            if start_offset:
                fh.seek(start_offset)
            raw = fh.read()
    except OSError:
        raw, readable = b"", False
    else:
        readable = True

    per_hook = {}  # type: Dict[str, int]
    for line in raw.decode("utf-8", "replace").splitlines():
        match = LOG_LINE.match(line)
        if match:
            per_hook[match.group(2)] = per_hook.get(match.group(2), 0) + 1

    ever = observable_hooks()
    result = {}  # type: Dict[str, Any]
    observable, unobservable = [], []
    for counter, names in sorted(FRICTION_HOOKS.items()):
        result[counter] = sum(per_hook.get(name, 0) for name in names)
        if ever is None or not any(name in ever for name in names):
            unobservable.append(counter)
        else:
            observable.append(counter)

    result["readable"] = readable
    result["observable"] = observable
    result["unobservable"] = unobservable
    if unobservable:
        result["note"] = (
            "%s never write to %s, so those counts mean 'not measured', not "
            "'none happened'." % (", ".join(unobservable), path)
        )
    return result
