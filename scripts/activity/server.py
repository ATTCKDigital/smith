#!/usr/bin/env python3
"""The daemon's HTTP surface: bind, route, gate, stream
(T087-T093, ``contracts/http-surface.md``, ``contracts/sse-frames.md``).

ONE ``http.server.ThreadingHTTPServer`` bound to ``127.0.0.1``. There is no
second listener, no IPv6 socket, and no configuration path that changes the
bind address — ``BIND_ADDRESS`` is a module constant and is never read from a
flag, an environment variable or a request (FR-4).

**No outbound connections of any kind** (FR-49). This module imports
``http.server``, ``socketserver``, ``json``, ``hmac`` and ``os``, and nothing
that can originate a request. ``urllib.parse`` is deliberately NOT imported
either: T098's guard is a crude grep for ``urllib`` over
``scripts/activity/*.py``, and a guard with an exception carved into it is a
guard nobody trusts. The 18-line percent-decoder below exists to keep that
grep exception-free — do not "simplify" it back to ``urllib.parse.unquote``.

Responsibilities are split for the 300-line soft policy:
``daemon.py`` owns runtime files and ingest, ``refresh.py`` the projection,
``api.py`` the ``/api/*`` payloads, and this file the wire.

Python 3.8, stdlib only.
"""

import hmac
import json
import os
import queue
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import api  # noqa: E402
import daemon as daemon_mod  # noqa: E402
import ingest  # noqa: E402
import state as state_mod  # noqa: E402

#: FR-4. Hardcoded, never a parameter. Never 0.0.0.0, never a hostname, never
#: an IPv6 non-loopback, under any flag.
BIND_ADDRESS = "127.0.0.1"

#: contracts/sse-frames.md §1 — an idle stream survives any intermediary and a
#: dead browser is detected.
KEEPALIVE_S = 20.0

FORBIDDEN_BODY = b'{"error":"forbidden"}'

_DAEMON = None  # type: ignore


# ---------------------------------------------------------------------------
# Query parsing, hand-rolled on purpose (see the module docstring)
# ---------------------------------------------------------------------------


def unquote(text: str) -> str:
    """Percent-decode one query value. ``+`` is a space, bad escapes pass through."""
    text = text.replace("+", " ")
    if "%" not in text:
        return text
    raw = text.encode("utf-8", "replace")
    out = bytearray()
    index = 0
    length = len(raw)
    while index < length:
        if raw[index] == 0x25 and index + 3 <= length:
            try:
                out.append(int(raw[index + 1 : index + 3], 16))
                index += 3
                continue
            except ValueError:
                pass
        out.append(raw[index])
        index += 1
    return out.decode("utf-8", "replace")


def split_path(target: str):
    """``"/events?token=x&project=y"`` -> ``("/events", {"token": "x", ...})``."""
    path, _, query = target.partition("?")
    params = {}
    for pair in query.split("&"):
        if not pair:
            continue
        key, _, value = pair.partition("=")
        params[unquote(key)] = unquote(value)
    return path, params


class ActivityHandler(BaseHTTPRequestHandler):
    """Routing, the FR-47 token gate, and the SSE stream."""

    protocol_version = "HTTP/1.1"
    server_version = "smith-activity/1"
    sys_version = ""

    # Quiet by default, matching every other Smith surface. A daemon that sees
    # every PostToolUse would otherwise write an access line per tool call.
    def log_message(self, fmt, *args):  # noqa: A003
        return

    # --- the token gate (FR-47) -------------------------------------------

    def _token_ok(self, params, header_auth: bool) -> bool:
        """``hmac.compare_digest``, never ``==``.

        ``secrets.compare_digest`` is the same function; the contract names the
        ``hmac`` spelling, so that is the one used.

        `/events` and `/api/*` carry the token as a query parameter because a
        browser ``EventSource`` cannot set headers. `/ingest` and `/statusline`
        carry it as ``Authorization: Bearer`` because a native ``"type":
        "http"`` hook entry supplies headers but cannot template a query
        parameter.
        """
        expected = _DAEMON.token
        if header_auth:
            supplied = self.headers.get("Authorization") or ""
            prefix = "Bearer "
            supplied = supplied[len(prefix) :] if supplied.startswith(prefix) else ""
        else:
            supplied = params.get("token") or ""
        # An absent token compares against the same expected value a wrong one
        # does, so the endpoint is not an oracle for "is there a token at all".
        return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))

    def _forbidden(self) -> None:
        self.send_response(403)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(FORBIDDEN_BODY)))
        self.end_headers()
        self._write(FORBIDDEN_BODY)

    # --- primitives --------------------------------------------------------

    def _write(self, blob: bytes) -> bool:
        """A closed tab is not an error (``contracts/sse-frames.md`` §1)."""
        try:
            self.wfile.write(blob)
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False

    def _json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self._write(body)

    def _bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self._write(body)

    def _empty(self, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # --- GET ---------------------------------------------------------------

    def do_GET(self):  # noqa: N802
        path, params = split_path(self.path)
        if path == "/health":
            return self._json(api.health(_DAEMON))  # un-gated by design
        if path == "/":
            body, content_type = api.index_document()
            return self._bytes(body, content_type)
        if path.startswith("/static/"):
            found = api.static_document(path[len("/static/") :])
            if found is None:
                return self._empty(404)
            return self._bytes(found[0], found[1])
        if path == "/events":
            if not self._token_ok(params, header_auth=False):
                return self._forbidden()
            return self._stream(params.get("project") or None)
        if path in api.READ_ROUTES:
            if not self._token_ok(params, header_auth=False):
                return self._forbidden()
            return self._json(
                api.READ_ROUTES[path](_DAEMON, params.get("project") or None)
            )
        return self._empty(404)

    # --- POST --------------------------------------------------------------

    def do_POST(self):  # noqa: N802
        path, params = split_path(self.path)
        if path in ("/ingest", "/statusline"):
            if not self._token_ok(params, header_auth=True):
                return self._forbidden()
            body, reason = self._read_body()
            # Accepted, malformed, oversize and "the daemon threw" are ALL 204.
            # A 4xx would be a failure signal the emitter might act on, and
            # FR-40's contract is that it acts on nothing.
            self._empty(204)
            if reason == "oversize":
                _DAEMON.state.bump_counter("oversize")
                _DAEMON.state.bump_counter("dropped")
                _DAEMON.log("ingest-oversize path=%s" % path)
                return
            try:
                if path == "/ingest":
                    _DAEMON.handle_ingest(body)
                else:
                    _DAEMON.handle_statusline(body)
            except Exception as exc:
                _DAEMON.state.bump_counter("dropped")
                _DAEMON.log("ingest-error path=%s type=%s" % (path, type(exc).__name__))
            return
        if path == "/api/register":
            if not self._token_ok(params, header_auth=False):
                return self._forbidden()
            body, _reason = self._read_body()
            return self._json(
                api.api_register(_DAEMON, params.get("project") or None, body)
            )
        return self._empty(404)

    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None, "malformed"
        return ingest.read_body(self.rfile, length)

    # --- SSE (contracts/sse-frames.md) -------------------------------------

    def _stream(self, project):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        # No Content-Length, so HTTP/1.1 would imply chunked framing; an
        # EventSource wants the raw body, so the connection is explicitly
        # close-delimited.
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        sub = _DAEMON.broadcaster.subscribe(project=project)
        try:
            if not self._frame("hello", _DAEMON.state.hello()):
                return
            last_seen = self.headers.get("Last-Event-ID")
            if last_seen and _resync_needed(last_seen, _DAEMON.state.generation):
                self._frame(
                    "resync",
                    {
                        "generation": _DAEMON.state.generation,
                        "reason": state_mod.RESYNC_DAEMON_RESTART,
                    },
                )
            if not self._frame("state", _DAEMON.state.snapshot(project=project)):
                return
            while True:
                try:
                    event, payload = sub.queue.get(timeout=KEEPALIVE_S)
                except queue.Empty:
                    if not self._write(b": keepalive\n\n"):
                        return
                    try:
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        return
                    continue
                if not self._frame(event, payload):
                    return
        finally:
            _DAEMON.broadcaster.unsubscribe(sub)

    def _frame(self, event: str, payload) -> bool:
        """``id:`` / ``event:`` / ``data:`` — exactly one line of JSON.

        ``separators=(",", ":")`` guarantees no raw newline in the payload, so
        the multi-line ``data:`` continuation rules never come into play.
        """
        generation = payload.get("generation", 0) if isinstance(payload, dict) else 0
        blob = "id: %s\nevent: %s\ndata: %s\n\n" % (
            generation,
            event,
            json.dumps(payload, separators=(",", ":"), default=str),
        )
        if not self._write(blob.encode("utf-8")):
            return False
        try:
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False
        return True


def _resync_needed(last_event_id: str, generation: int) -> bool:
    """A reconnecting tab ahead of the daemon means the daemon restarted.

    Retention is ephemeral (OOS-3), so there is no replay to offer — the UI
    renders the "history reset at daemon restart" banner instead of a silently
    truncated timeline.
    """
    try:
        return int(last_event_id) > generation
    except (TypeError, ValueError):
        return False


def serve(instance, port: int):
    """Bind 127.0.0.1 only and serve until shutdown."""
    global _DAEMON
    _DAEMON = instance
    httpd = ThreadingHTTPServer((BIND_ADDRESS, port), ActivityHandler)
    httpd.daemon_threads = True
    return httpd


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    port = daemon_mod.DEFAULT_PORT
    while argv:
        arg = argv.pop(0)
        if arg == "--port" and argv:
            port = int(argv.pop(0))
        elif arg.startswith("--port="):
            port = int(arg.split("=", 1)[1])
        elif arg in ("--foreground", "--no-open"):
            pass  # honoured by the shell wrapper; accepted here so it can pass through

    instance = daemon_mod.Daemon(port=port)
    try:
        httpd = serve(instance, port)
    except OSError as exc:
        sys.stderr.write(
            "smith-activity: cannot bind %s:%d (%s)\n" % (BIND_ADDRESS, port, exc)
        )
        return 1

    instance.port = httpd.server_address[1]
    instance.write_runtime_files()
    instance.restore_projects()
    instance.start()
    instance.log(
        "start pid=%d port=%d capture_prompts=%s"
        % (os.getpid(), instance.port, instance.capture_prompts)
    )

    def _shutdown(_signum, _frame):
        # shutdown() blocks until serve_forever() returns, so it can never be
        # called from the thread running it.
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    try:
        httpd.serve_forever(poll_interval=0.2)
    finally:
        instance.log("stop pid=%d" % os.getpid())
        instance.stop()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
