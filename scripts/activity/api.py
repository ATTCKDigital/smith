"""The `/api/*` payload builders and the `/static/*` allowlist
(T092/T093, ``contracts/http-surface.md`` §2 and §5).

Split out of ``server.py`` on the 300-line soft policy: ``server.py`` owns
routing, the token gate and SSE framing; this module owns what each route
returns. Every function here is pure with respect to the HTTP layer — it takes
a ``Daemon`` and a query and returns a JSON-able dict — so a route can be
tested without a socket.

`?project=` filters every read route. It NEVER filters the quota block, which
is account-wide (FR-3/FR-35) and is returned unchanged under every filter.

Python 3.8, stdlib only.
"""

import json
import os
from typing import Any, Dict, Optional

import state as state_mod
import usage as usage_mod

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

#: Explicit allowlist. `/static/<name>` is `os.path.basename()`-ed and looked
#: up HERE — never joined against user input, so no spelling of `..` reaches
#: the filesystem. Unknown names 404 without a stat.
STATIC_ALLOWLIST = {
    "app.js": "application/javascript; charset=utf-8",
    "ui.js": "application/javascript; charset=utf-8",
    "panels.js": "application/javascript; charset=utf-8",
    "stepper.js": "application/javascript; charset=utf-8",
    "app.css": "text/css; charset=utf-8",
    "favicon.svg": "image/svg+xml",
}

INDEX_NAME = "index.html"

#: Served when the UI phase (T110-T115) has not landed yet. Deliberately inert:
#: no script, no external origin, and it states what is missing rather than
#: rendering a broken shell (A-9).
PLACEHOLDER_INDEX = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    "<title>smith-activity</title></head><body>"
    "<h1>smith-activity daemon</h1>"
    "<p>The daemon is running. The dashboard page is not installed yet "
    "(it lands with the UI phase).</p>"
    "<p>Data is available on <code>/api/state</code> and <code>/events</code>, "
    "both of which require <code>?token=</code>.</p>"
    "</body></html>"
).encode("utf-8")


def index_document():
    """``(body, content_type)`` for ``GET /``."""
    path = os.path.join(STATIC_DIR, INDEX_NAME)
    try:
        with open(path, "rb") as fh:
            return fh.read(), "text/html; charset=utf-8"
    except OSError:
        return PLACEHOLDER_INDEX, "text/html; charset=utf-8"


def static_document(name: str):
    """``(body, content_type)`` or ``None``. Allowlist lookup, never a join."""
    key = os.path.basename(name or "")
    content_type = STATIC_ALLOWLIST.get(key)
    if content_type is None:
        return None
    try:
        with open(os.path.join(STATIC_DIR, key), "rb") as fh:
            return fh.read(), content_type
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Read routes
# ---------------------------------------------------------------------------


def api_state(daemon, project: Optional[str]) -> Dict[str, Any]:
    """The cold-start snapshot — identical in shape to the `state` SSE frame.

    One renderer serves both, which is the point: a second shape is a second
    place for the dashboard to be confidently wrong.
    """
    return daemon.state.snapshot(project=project)


def api_projects(daemon, project: Optional[str]) -> Dict[str, Any]:
    snapshot = daemon.state.snapshot(project=project)
    return {
        "generation": snapshot["generation"],
        "projects": snapshot["projects"],
        "registered": daemon.state.count("projects"),
    }


def api_workflows(daemon, project: Optional[str]) -> Dict[str, Any]:
    snapshot = daemon.state.snapshot(project=project)
    return {
        "generation": snapshot["generation"],
        "workflows": snapshot["workflows"],
        "findings": snapshot["findings"],
        "unattributed_events": snapshot["unattributed_events"],
    }


def api_worktrees(daemon, project: Optional[str]) -> Dict[str, Any]:
    snapshot = daemon.state.snapshot(project=project)
    return {"generation": snapshot["generation"], "worktrees": snapshot["worktrees"]}


def api_usage(daemon, project: Optional[str]) -> Dict[str, Any]:
    """Token rollups plus the quota windows.

    The quota block is attached from the tree directly rather than from the
    filtered snapshot, so `?project=` cannot reach it. A per-project quota does
    not exist and rendering one would be a lie.
    """
    snapshot = daemon.state.snapshot(project=project)
    rollups = [s["usage"] for s in snapshot["sessions"] if s.get("usage")]
    return {
        "generation": snapshot["generation"],
        "sessions": [
            {"session_id": s["session_id"], "usage": s.get("usage")}
            for s in snapshot["sessions"]
        ],
        "total": usage_mod.merge_rollups(rollups, "project"),
        "quota": daemon.state.quota,
    }


def api_vault(daemon, project: Optional[str]) -> Dict[str, Any]:
    snapshot = daemon.state.snapshot(project=project)
    return {
        "generation": snapshot["generation"],
        "vault": [
            {"project": p["path"], "snapshot": p.get("vault") or {}}
            for p in snapshot["projects"]
        ],
    }


# ---------------------------------------------------------------------------
# The one write route (FR-2/FR-3/FR-7/FR-44)
# ---------------------------------------------------------------------------


def api_register(
    daemon, project: Optional[str], body: Optional[bytes]
) -> Dict[str, Any]:
    """Register a project by its PRIMARY-REPO path.

    The path comes from the JSON body's ``path``, else ``?project=``. Writes go
    only to ``~/.smith/activity/projects.json``; nothing under any project's
    ``.smith/vault/`` is opened for writing, ever.
    """
    path = project
    if body:
        try:
            parsed = json.loads(body.decode("utf-8", "replace"))
        except (ValueError, UnicodeDecodeError):
            parsed = None
        if isinstance(parsed, dict) and parsed.get("path"):
            path = parsed["path"]
    if not path:
        return {"error": "path required", "registered": False}
    return daemon.register(path)


READ_ROUTES = {
    "/api/state": api_state,
    "/api/projects": api_projects,
    "/api/workflows": api_workflows,
    "/api/worktrees": api_worktrees,
    "/api/usage": api_usage,
    "/api/vault": api_vault,
}


def health(daemon) -> Dict[str, Any]:
    """``contracts/http-surface.md`` §4 — the FR-5 identity probe.

    Un-gated by design: the shell command must be able to probe a port it may
    not hold the token for. The probe is ``service == "smith-activity"``, NOT
    the HTTP status — an unrelated program on the port refuses, returns
    non-JSON, or returns JSON without that key, and all three mean "pick
    another port".

    Discloses no project paths, no session content and no token.
    """
    return {
        "service": state_mod.SERVICE,
        "version": state_mod.VERSION,
        "pid": os.getpid(),
        "started_at": daemon.state.started_at,
        "projects": daemon.state.count("projects"),
    }
