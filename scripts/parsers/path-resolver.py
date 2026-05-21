#!/usr/bin/env python3
"""
path-resolver.py — resolve a source file path to its Smith system name.

Implements the Path 2 model from questions.md Q7 — heuristic is the engine,
`system-paths.json` provides explicit overrides via a longest-prefix match.

Two interfaces:

1. Importable function:
       from path_resolver import resolve
       resolve(file_path, project_root="/repo", system_paths_json=None) -> str

2. CLI entrypoint (for shell callers like manifest-updater.sh):
       python3 path-resolver.py <file_path> <project_root> [<system-paths.json>]

Output (CLI): the resolved system name on stdout, newline-terminated.

Both interfaces are pure — no side effects, no filesystem writes.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

# Directories whose content is uniformly excluded from system indexing.
EXCLUDED_TOP_LEVEL = {
    "node_modules",
    "vendor",
    "dist",
    "build",
    ".git",
    ".venv",
    "venv",
    "__pycache__",
}

# Top-level directories that are intentionally not assigned to a system.
# They still get parsed but their files are bucketed under "unassigned".
UNASSIGNED_TOP_LEVEL = {
    "tests",
    "test",
    "docs",
    "doc",
}


def _normalise(file_path: str, project_root: str) -> str:
    """Return the project-relative POSIX path.

    Strips a leading `./` and any leading project_root prefix. Uses
    forward slashes regardless of OS.
    """
    fp = file_path.replace(os.sep, "/")
    if project_root:
        root = project_root.replace(os.sep, "/").rstrip("/") + "/"
        if fp.startswith(root):
            fp = fp[len(root) :]
    if fp.startswith("./"):
        fp = fp[2:]
    return fp


def _apply_overrides(
    rel_path: str, overrides: list[dict[str, Any]], default: str
) -> str | None:
    """Apply explicit override rules from system-paths.json.

    Returns the matched system name, or None if no rule applied.
    """
    if not overrides:
        return None
    # Sort by prefix length descending; longest match wins.
    sorted_rules = sorted(
        overrides, key=lambda r: len(r.get("prefix", "")), reverse=True
    )
    for rule in sorted_rules:
        prefix = rule.get("prefix", "")
        if not prefix:
            continue
        if rel_path.startswith(prefix):
            return rule.get("system", default)
    return None


def _apply_heuristic(rel_path: str) -> str:
    """Fall-through heuristic per spec Requirement 14.

    Algorithm:
      services/<name>/...   -> system-<name>
      backend/<name>/...    -> system-backend-<name>
      frontend/<name>/...   -> system-frontend-<name>
      tests/ docs/          -> unassigned
      node_modules/ etc.    -> excluded
      <other-top>/...       -> system-<other-top>
      root-level file       -> unassigned
    """
    if "/" not in rel_path:
        return "unassigned"

    parts = rel_path.split("/")
    top = parts[0]

    if top in EXCLUDED_TOP_LEVEL:
        return "excluded"

    if top in UNASSIGNED_TOP_LEVEL:
        return "unassigned"

    # services/<name>/...
    if top == "services" and len(parts) >= 2 and parts[1]:
        return f"system-{parts[1]}"

    # backend/<name>/...
    if top == "backend" and len(parts) >= 2 and parts[1]:
        return f"system-backend-{parts[1]}"

    # frontend/<name>/...
    if top == "frontend" and len(parts) >= 2 and parts[1]:
        return f"system-frontend-{parts[1]}"

    # Generic top-level directory.
    return f"system-{top}"


def resolve(
    file_path: str,
    project_root: str = "",
    system_paths_json: str | None = None,
    overrides_dict: dict[str, Any] | None = None,
) -> str:
    """Resolve `file_path` to a Smith system name.

    Args:
        file_path: Source file path. May be absolute or relative.
        project_root: Optional. If given, used to strip the prefix from
            absolute file_paths.
        system_paths_json: Optional. Path to a `system-paths.json` file
            with explicit `rules` list. Missing/unreadable file falls
            through to heuristic.
        overrides_dict: Optional. Already-parsed override dict; if both
            this and system_paths_json are provided, this wins.

    Returns:
        The resolved system name. Special values:
          - "unassigned" — no match, e.g. for tests/docs or root files
          - "excluded" — caller should skip indexing entirely
          - otherwise: "system-<something>"
    """
    rel = _normalise(file_path, project_root)

    overrides_data: dict[str, Any] | None = overrides_dict
    if overrides_data is None and system_paths_json:
        try:
            with open(system_paths_json, "r", encoding="utf-8") as f:
                overrides_data = json.load(f)
        except (OSError, json.JSONDecodeError):
            overrides_data = None

    rules: list[dict[str, Any]] = []
    has_explicit_default = False
    explicit_default = "unassigned"
    if isinstance(overrides_data, dict):
        rules = overrides_data.get("rules", []) or []
        if isinstance(overrides_data.get("default"), str):
            has_explicit_default = True
            explicit_default = overrides_data["default"]

    explicit = _apply_overrides(rel, rules, explicit_default)
    if explicit is not None:
        return explicit

    # If the overrides file declares an explicit default, honor it (per
    # data-model.md section 6: "If none match, return `default`.").
    if has_explicit_default:
        return explicit_default

    return _apply_heuristic(rel)


def resolve_system(
    file_path: str,
    overrides_dict: dict[str, Any] | None = None,
    project_root: str = "",
) -> str:
    """Convenience alias kept for Phase B integration callers.

    Mirrors `resolve()` but accepts only an already-parsed overrides
    dict (no file I/O).
    """
    return resolve(
        file_path,
        project_root=project_root,
        overrides_dict=overrides_dict,
    )


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        sys.stderr.write(
            "usage: path-resolver.py <file_path> <project_root> [<system-paths.json>]\n"
        )
        return 2
    file_path = argv[1]
    project_root = argv[2]
    system_paths = argv[3] if len(argv) > 3 else None
    try:
        sys.stdout.write(
            resolve(
                file_path, project_root=project_root, system_paths_json=system_paths
            )
        )
        sys.stdout.write("\n")
    except Exception as e:
        # Never crash callers; emit "unassigned" + log to stderr.
        sys.stderr.write(f"path-resolver: {type(e).__name__}: {e}\n")
        sys.stdout.write("unassigned\n")
    return 0


# ----------------------------------------------------------------------------
# Built-in self-test (runnable: `python3 path-resolver.py --selftest`)
# ----------------------------------------------------------------------------
def _selftest() -> int:
    cases = [
        # (file_path, overrides_dict, expected)
        ("backend/src/api/products.py", None, "system-backend-src"),
        ("services/billing/main.py", None, "system-billing"),
        ("frontend/src/App.tsx", None, "system-frontend-src"),
        ("tests/test_x.py", None, "unassigned"),
        ("docs/intro.md", None, "unassigned"),
        ("node_modules/foo/index.js", None, "excluded"),
        (".venv/lib/x.py", None, "excluded"),
        ("vendor/whatever.js", None, "excluded"),
        ("README.md", None, "unassigned"),
        ("scripts/install.sh", None, "system-scripts"),
        # Explicit override beats heuristic.
        (
            "backend/src/api/v1/products.py",
            {
                "rules": [
                    {
                        "prefix": "backend/src/api/v1/products",
                        "system": "system-15-command-center",
                    }
                ]
            },
            "system-15-command-center",
        ),
        # Longest-prefix wins.
        (
            "backend/src/api/v1/products.py",
            {
                "rules": [
                    {"prefix": "backend/src/api", "system": "system-01-api"},
                    {
                        "prefix": "backend/src/api/v1/products",
                        "system": "system-15-command-center",
                    },
                ]
            },
            "system-15-command-center",
        ),
        # Non-matching override falls through to heuristic.
        (
            "frontend/src/App.tsx",
            {"rules": [{"prefix": "backend/", "system": "system-01-api"}]},
            "system-frontend-src",
        ),
        # Default override.
        (
            "README.md",
            {"rules": [], "default": "system-misc"},
            "system-misc",
        ),
    ]
    failures: list[str] = []
    for fp, ov, expected in cases:
        got = resolve(fp, overrides_dict=ov)
        if got != expected:
            failures.append(
                f"  {fp!r} (overrides={ov!r}): expected {expected!r}, got {got!r}"
            )
    if failures:
        sys.stderr.write("path-resolver selftest FAILED:\n")
        for f in failures:
            sys.stderr.write(f + "\n")
        return 1
    sys.stdout.write(f"path-resolver selftest OK ({len(cases)} cases)\n")
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--selftest":
        sys.exit(_selftest())
    sys.exit(main(sys.argv))
