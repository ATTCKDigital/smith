"""prereqs — verify external services are reachable before a run (FR-21).

Returns structured results so run.py can exit 2 with a clear remediation message
when a prerequisite is down. No LLM, no side effects beyond a health GET.
"""

from dataclasses import dataclass

import httpx


@dataclass
class PrereqResult:
    name: str
    ok: bool
    detail: str
    remedy: str = ""


def check_qdrant(url: str) -> PrereqResult:
    try:
        r = httpx.get(f"{url.rstrip('/')}/collections", timeout=5.0)
        r.raise_for_status()
        return PrereqResult("qdrant", True, f"reachable at {url}")
    except Exception as exc:  # noqa: BLE001 — health check reports, never raises
        return PrereqResult(
            "qdrant",
            False,
            f"unreachable at {url}: {exc}",
            remedy="docker run -d -p 6333:6333 -p 6334:6334 "
            "-v qdrant_storage:/qdrant/storage qdrant/qdrant",
        )


def check_ollama(url: str, model: str) -> PrereqResult:
    try:
        r = httpx.get(f"{url.rstrip('/')}/api/tags", timeout=5.0)
        r.raise_for_status()
        names = [m.get("name", "") for m in r.json().get("models", [])]
        if any(model in n for n in names):
            return PrereqResult("ollama", True, f"{model} present at {url}")
        return PrereqResult(
            "ollama",
            False,
            f"reachable but model '{model}' not loaded (have: {', '.join(names) or 'none'})",
            remedy=f"ollama pull {model}",
        )
    except Exception as exc:  # noqa: BLE001
        return PrereqResult(
            "ollama",
            False,
            f"unreachable at {url}: {exc}",
            remedy="start Ollama (https://ollama.com) then: ollama pull " + model,
        )


def check_playwright_ws(ws_url: str) -> PrereqResult:
    """Best-effort TCP reachability of the Playwright server port."""
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(ws_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 9224
    try:
        with socket.create_connection((host, port), timeout=3.0):
            return PrereqResult("playwright", True, f"listening at {ws_url}")
    except OSError as exc:
        return PrereqResult(
            "playwright",
            False,
            f"no server at {ws_url}: {exc}",
            remedy="bash skills/smith-research/scripts/start-playwright-server.sh",
        )


def check_all(config, require_playwright: bool = True) -> list[PrereqResult]:
    results = [
        check_qdrant(config.qdrant_url),
        check_ollama(config.ollama_url, config.embedding_model),
    ]
    if require_playwright:
        results.append(check_playwright_ws(config.playwright_ws))
    return results
