"""Hook firing — the only observable "this hook ran" source, and its limits.

Split out of ``refresh.py`` on the repo's 500-line decompose rule; ``refresh``
re-exports every name here, so its call sites are unchanged.

The split is worth more than the line count. What this module does is
**inference about the daemon's own instrumentation**, not projection of the
operator's workflows, and the difference matters: a wrong answer here does
not mis-render a workflow, it invents a finding ABOUT a workflow out of the
daemon's own blindness. Keeping that reasoning in one file, with the size of
its blind spot written at the top of it, is the point.

The blind spot, stated once: **3 of the repo's 20 hooks write to
``~/.smith/logs/hooks.log``.** Everything below is built on that log, so
everything below can see 3 hooks fire and 17 not-fire-as-far-as-it-knows.
``fired_hooks`` carries the full note.

Read-only. Nothing here opens a file for writing.

Python 3.8, stdlib only.
"""

import os
from typing import Optional

def hooks_log_path() -> str:
    import paths

    return os.path.join(paths.smith_home(), "logs", "hooks.log")


def events_ingested(daemon) -> int:
    """How many hook events have reached this daemon since it started.

    The `ingested` counter is bumped before project attribution, so an event
    from an unregistered repo still counts: the question is whether the
    TRANSPORT works, not whether we could place what it delivered. Read
    defensively because the counter is daemon-owned state and this module is
    only its guest.
    """
    try:
        return int(daemon.state.counters.get("ingested") or 0)
    except (AttributeError, TypeError, ValueError):
        return 0


def fired_hooks(daemon) -> Optional[set]:
    """Basenames seen in ``~/.smith/logs/hooks.log`` since the daemon started.

    ``None`` when the log cannot be read. That ``None`` DISABLES the
    ``hook_never_fired`` classification rather than substituting an empty set:
    "nothing fired" and "we cannot see what fired" have the same shape and
    opposite meanings, and manufacturing a finding out of the second is exactly
    what ``absence.expected_hook_set``'s contract forbids.

    **KNOWN LIMITATION — this inference is PARTIAL, and it is partial in a
    way that produces false findings rather than missing ones.**

    Only **3 of the repo's 20 hooks write to this log at all**:
    ``context-loader.sh``, ``manifest-updater.sh`` and ``workflow-gate.sh``
    (they are the only files under ``hooks/`` containing the string
    ``hooks.log``). For the other ~17 there is no line to see, ever. So
    "``foo.sh`` is wired, is always applicable, and does not appear here"
    resolves to ``hook_never_fired`` for roughly ten hooks that are in fact
    firing normally — a confidently wrong finding of exactly the kind this
    whole feature exists to expose.

    **Wiring an emitter does not fix it.** The emitter reports the EVENT
    (``PreToolUse``, ``SessionStart``, …); it cannot report which of that
    event's several registered sibling hooks actually ran. Event arrival and
    hook firing are different facts and only the first is observable here.

    Fixing it properly is a design decision with two candidate shapes, and
    both are out of scope for the task that wrote this note:

      a. infer firing from ``event observed`` + ``hook wired for that event``,
         which is an inference about the settings rather than an observation;
      b. make every hook write a line, which is 17 hook edits and a
         performance question on the hot ``PreToolUse`` path.

    Until one is chosen, ``hook_observability_notice`` below puts the
    partiality on screen, so the panel does not imply a completeness it does
    not have. The classification itself is deliberately left ALONE — changing
    which findings are emitted is the design decision, not the disclosure.
    """
    path = hooks_log_path()
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    if daemon.hooks_log_offset is None:
        # `hooks_log_start` is pinned here and never moves again: it is the
        # SESSION WINDOW FR-37's friction counters are filtered to, whereas
        # `hooks_log_offset` advances with every read. Deriving the window
        # from the moving offset would make each poll count only what
        # arrived since the previous poll.
        daemon.hooks_log_offset = size
        daemon.hooks_log_start = size
        return set()
    if size < daemon.hooks_log_offset:  # rotated under us
        daemon.hooks_log_offset = 0
    try:
        with open(path, "rb") as fh:
            fh.seek(daemon.hooks_log_offset)
            raw = fh.read()
    except OSError:
        return None
    seen = set(getattr(daemon, "_fired_hooks", set()))
    for line in raw.decode("utf-8", "replace").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            seen.add(parts[1] if parts[1].endswith(".sh") else parts[1] + ".sh")
    daemon.hooks_log_offset = size
    daemon._fired_hooks = seen
    return seen


def hook_observability_notice(expected) -> Optional[str]:
    """Say, in the operator's own words, that hook-firing sight is partial.

    See ``fired_hooks`` for why it is partial. This does not change a single
    finding — it states that the absence half of the panel can only see the
    handful of hooks that write to ``hooks.log``, so a reader is not left to
    infer completeness from silence.

    ``None`` when there is nothing to disclose: no expectation set, or every
    expected hook is one that genuinely reports.
    """
    if not expected:
        return None
    import vault_friction

    ever = vault_friction.observable_hooks()
    if ever is None:
        return None
    # `hooks.log` names hooks WITHOUT the `.sh` the expectation set uses.
    reporting = {name + ".sh" for name in ever}
    blind = sorted(name for name in expected if name not in reporting)
    if not blind:
        return None
    return (
        "Hook-firing observation is PARTIAL: %d of %d expected hooks never "
        "write to %s, so 'this hook never fired' cannot be established for "
        "them and any such finding about them is unreliable (%s)."
        % (
            len(blind),
            len(expected),
            hooks_log_path(),
            ", ".join(blind[:6]) + ("…" if len(blind) > 6 else ""),
        )
    )

