"""The ingest boundary: envelope validation, the 256 KiB cap, and FR-48
redaction (T086, ``contracts/hook-envelope.md`` §1 and §4).

**This module is the redaction boundary, and it is the only one.**

Redaction happens HERE, at ingest, before the payload reaches the state tree.
It does not happen at frame-build time. The distinction is the whole of SC-14:
a frame-build-time redactor passes every unit test and still writes prompt text
to ``~/.smith/activity/activity.log`` and into ``/api/*`` responses built from
a different projection. The unredacted value must never exist anywhere a frame
builder, an ``/api/*`` handler or the logger could reach it, and the only way
to guarantee that is to destroy it at the door.

Nothing downstream of ``parse()`` may assume it is holding raw content.

The emitter forwards stdin byte-for-byte and parses nothing
(``contracts/hook-envelope.md`` §5), so the daemon is the sole parser and it
parses defensively: every field is optional, a missing ``session_id`` is
counted and dropped rather than raised, and a body that is not JSON or exceeds
the cap is discarded with a ``204``.

Python 3.8, stdlib only.
"""

import json
import os
import re
from typing import Any, Dict, Optional, Tuple

#: `contracts/http-surface.md` §3. A larger Content-Length is read and
#: DISCARDED in full before replying, so the connection is not left
#: half-drained and the emitter still sees its 204.
MAX_INGEST_BYTES = 256 * 1024

_READ_CHUNK = 64 * 1024

CAPTURE_ENV = "SMITH_ACTIVITY_CAPTURE_PROMPTS"

REDACTED = "<redacted>"

#: `contracts/hook-envelope.md` §4. Matched against KEY NAMES at any depth.
SECRETISH_KEY = re.compile(r"(?i)(secret|token|password|api_?key|authorization)")

#: The three content fields, replaced by a length-bearing placeholder. Matched
#: at any depth, not just top level: a nested `tool_input` inside a batched
#: tool payload is the same content by another route.
PROMPT_FIELD = "prompt"
TOOL_INPUT_FIELD = "tool_input"
TOOL_RESPONSE_FIELD = "tool_response"

#: Retained ALWAYS, because none of it is content (`hook-envelope.md` §4).
#: `tool_use_id` is included because `resolver.permission_state()` correlates a
#: PermissionRequest to its resolution on it, which is strictly more precise
#: than `prompt_id` — one turn can hold several tool calls.
RETAINED_FIELDS = (
    "session_id",
    "prompt_id",
    "cwd",
    "transcript_path",
    "permission_mode",
    "hook_event_name",
    "tool_name",
    "tool_use_id",
    "agent_id",
    "agent_type",
    "source",
    "error_type",
)


def capture_enabled(env: Optional[Dict[str, str]] = None) -> bool:
    """FR-48's opt-in. Anything other than exactly ``"1"`` is off."""
    source = os.environ if env is None else env
    return source.get(CAPTURE_ENV) == "1"


def _byte_len(value: Any) -> int:
    """Serialized byte length — the audit signal the placeholders retain.

    A ``tool_input`` of 40 KB versus 40 bytes is a real signal and the length
    leaks nothing, so it is kept deliberately.
    """
    if isinstance(value, bytes):
        return len(value)
    if isinstance(value, str):
        return len(value.encode("utf-8", "replace"))
    try:
        return len(json.dumps(value, separators=(",", ":")).encode("utf-8", "replace"))
    except (TypeError, ValueError):
        return len(repr(value).encode("utf-8", "replace"))


def redact_prompt(value: Any) -> str:
    """``prompt`` → ``"<redacted:N chars>"`` — N in CHARACTERS, per the table."""
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return "<redacted:%d chars>" % len(text)


def redact_tool_input(value: Any) -> Dict[str, int]:
    """``tool_input`` → ``{"<redacted>": N}`` with N the serialized byte length."""
    return {REDACTED: _byte_len(value)}


def redact_tool_response(value: Any) -> str:
    """``tool_response`` → ``"<redacted:N bytes>"``."""
    return "<redacted:%d bytes>" % _byte_len(value)


def _walk(node: Any, capture_prompts: bool) -> Any:
    """Recursive redaction pass. Returns a NEW structure; input is untouched."""
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            # Secret-shaped keys are redacted UNCONDITIONALLY, capture or not.
            # SMITH_ACTIVITY_CAPTURE_PROMPTS opts in to seeing your own prompts;
            # it is not an opt-in to persisting a bearer token to a log file.
            if isinstance(key, str) and SECRETISH_KEY.search(key):
                out[key] = REDACTED
                continue
            if not capture_prompts and isinstance(key, str):
                if key == PROMPT_FIELD:
                    out[key] = redact_prompt(value)
                    continue
                if key == TOOL_INPUT_FIELD:
                    out[key] = redact_tool_input(value)
                    continue
                if key == TOOL_RESPONSE_FIELD:
                    out[key] = redact_tool_response(value)
                    continue
            out[key] = _walk(value, capture_prompts)
        return out
    if isinstance(node, list):
        return [_walk(item, capture_prompts) for item in node]
    return node


def redact(payload: Any, capture_prompts: bool = False) -> Any:
    """Apply FR-48 to a parsed envelope. The only redaction entry point."""
    return _walk(payload, capture_prompts)


def read_body(rfile, content_length: int) -> Tuple[Optional[bytes], str]:
    """Read exactly ``content_length`` bytes. Returns ``(body, reason)``.

    ``body`` is ``None`` when the request is over the cap or unreadable, and
    ``reason`` is the counter name to bump. Oversize bodies are read and
    DISCARDED in full rather than ignored, so the socket is drained and the
    emitter's ``204`` still lands (``contracts/http-surface.md`` §3).
    """
    if content_length <= 0:
        return b"", "ok"
    if content_length > MAX_INGEST_BYTES:
        remaining = content_length
        while remaining > 0:
            chunk = rfile.read(min(_READ_CHUNK, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
        return None, "oversize"
    try:
        body = rfile.read(content_length)
    except (OSError, ValueError):
        return None, "malformed"
    return body, "ok"


def parse(
    raw: Optional[bytes], capture_prompts: bool = False
) -> Optional[Dict[str, Any]]:
    """Bytes in, a redacted envelope dict out, or ``None`` to drop and count.

    ``None`` covers a non-JSON body and a JSON body that is not an object. Both
    are counted and discarded; neither is ever an error the emitter can see.
    """
    if not raw:
        return None
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return redact(payload, capture_prompts=capture_prompts)


def envelope(
    payload: Dict[str, Any], seq: int, received_at: str
) -> Optional[Dict[str, Any]]:
    """Shape a REDACTED payload into the event record the resolvers consume.

    Returns ``None`` when there is no ``session_id``: an event that cannot be
    placed is counted and dropped, not an error
    (``contracts/hook-envelope.md`` §1).

    ``seq`` is the daemon's single monotone counter, shared with the
    session-log tailer. It — never a parsed timestamp — is the ordering key
    (FR-58): the session log mixes UTC hook writes with local model writes and
    a 4-hour skew is pinned in ``tests/activity/test_sessionlog.py``.
    ``received_at`` is display-only.
    """
    session_id = payload.get("session_id")
    if not session_id:
        return None
    record = {"seq": seq, "timestamp": received_at, "kind": "hook_event"}
    for field in RETAINED_FIELDS:
        if field in payload:
            record[field] = payload[field]
    # Already redacted (or deliberately captured) by `parse()`. Carried through
    # so the resolver's FR-11 signal 2 sees the shape it expects; with capture
    # off it sees `{"<redacted>": N}` and degrades to the session-log and
    # sidecar spines, which is the designed posture.
    for field in (TOOL_INPUT_FIELD, TOOL_RESPONSE_FIELD, PROMPT_FIELD):
        if field in payload:
            record[field] = payload[field]
    return record
