"""FR-60 / FR-61 inputs -- the I/O half of hook absence detection.

``findings.py`` is required to be PURE, and both of these sources are files, so
reading them lives here and the judging lives there.

**FR-60: expectation comes from the INSTALLED settings, never the repo.**
``docs/hooks.md:5`` tells operators to disable a hook by removing its settings
entry. Deriving expectation from ``settings/smith-settings-fragment.json``
would therefore fire "this hook never fired" at a hook the operator
deliberately removed, and would compare Smith against its own intentions
instead of against reality. When the installed file cannot be read, the caller
disables absence detection with a visible notice -- it never guesses.

**FR-61: "Smith ships this, your settings don't wire it" comes from a
MANIFEST the installer stages**, not from a repo checkout the daemon has no
reason to be able to find. That staging task belongs to a later phase, so
every reader here treats the manifest as optional and returns ``None`` when it
is absent -- ``None`` meaning "unknown", never "nothing is shipped".

Python 3.8, stdlib only.
"""

import json
import os
from typing import Any, Dict, Optional, Set, Tuple

import paths

SHIPPED_MANIFEST_NAMES = ("shipped-hooks.json", "shipped-hooks.txt")


def installed_settings_path():
    return os.path.join(paths.claude_home(), "settings.json")


def read_installed_settings(path=None):
    """``(settings_obj, error)``. ``error`` is a string when unreadable.

    Both halves are returned because FR-60 needs the REASON on screen, not just
    a degraded mode: "absence detection off" with no explanation reads as a
    missing feature rather than as a deliberate refusal to guess.
    """
    path = path or installed_settings_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh), None
    except OSError as exc:
        return None, "%s is unreadable (%s)" % (path, exc.strerror or exc)
    except ValueError as exc:
        return None, "%s is not valid JSON (%s)" % (path, exc)


def wired_hooks(settings_obj):
    """``{hook_basename: {(event, matcher), ...}}`` from a settings object.

    Keyed on basename because that is the only stable identifier across the
    several command spellings the repo uses
    (``bash ~/.claude/hooks/x.sh``, ``"$CLAUDE_HOOKS_DIR"/x.sh``, an absolute
    path). Returns ``{}`` for a settings object with no ``hooks`` key, which is
    a legitimate state -- an operator who wired nothing -- and is distinct from
    the ``None`` that means "could not read".
    """
    wired: Dict[str, Set[Tuple[str, str]]] = {}
    for event, entries in ((settings_obj or {}).get("hooks") or {}).items():
        for entry in entries or []:
            matcher = (entry or {}).get("matcher") or "*"
            for hook in (entry or {}).get("hooks") or []:
                command = (hook or {}).get("command") or ""
                if not command:
                    continue
                basename = os.path.basename(command.strip().split()[-1])
                if basename:
                    wired.setdefault(basename, set()).add((event, matcher))
    return wired


def shipped_manifest_path(smith_home=None):
    """The first staged manifest that exists, or None."""
    root = os.path.join(smith_home or paths.smith_home(), "activity")
    for name in SHIPPED_MANIFEST_NAMES:
        candidate = os.path.join(root, name)
        if os.path.isfile(candidate):
            return candidate
    return None


def read_shipped_manifest(path=None, smith_home=None):
    """The set of hook basenames Smith ships, or ``None`` when unknown.

    ``None`` is the important return: with no manifest staged, FR-61 has no
    "what Smith ships" side and must emit nothing rather than diff against an
    empty set and declare every hook unwired.

    Two formats are accepted because the installer task that writes this has
    not landed yet: a JSON list or ``{"hooks": [...]}``, and a newline-delimited
    text file. Anything else reads as unknown.
    """
    path = path or shipped_manifest_path(smith_home)
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except OSError:
        return None
    text = raw.strip()
    if not text:
        return None
    if text[0] in "[{":
        try:
            parsed = json.loads(text)
        except ValueError:
            return None
        if isinstance(parsed, dict):
            parsed = parsed.get("hooks") or parsed.get("shipped") or []
        if not isinstance(parsed, list):
            return None
        return {os.path.basename(str(item)) for item in parsed if str(item).strip()}
    return {
        os.path.basename(line.strip())
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
