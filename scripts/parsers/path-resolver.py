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

import functools
import json
import os
import sys
from typing import Any

# Glob characters not allowed in v1 `paths:` entries (per data-model.md §8.1).
_GLOB_CHARS = set("*?[]{}!")


# --- Tier 1: `.specify/systems/<name>/spec.md` frontmatter -----------------
def _parse_yaml_frontmatter(path: str) -> dict[str, object]:
    """Read top-of-file YAML frontmatter from `path`.

    Recognised keys: `system`, `status`, `paths`, `also_affects`.
    Everything else is ignored. Malformed input returns `{}`.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return {}
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end == -1:
        # Trailing `\n---` at EOF.
        end_eof = text.find("\n---", 4)
        if end_eof == -1:
            return {}
        body = text[4:end_eof]
    else:
        body = text[4:end]
    out: dict[str, object] = {}
    current_list_key: str | None = None
    current_list: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            current_list_key = None
            continue
        if (line.startswith("  - ") or line.startswith("- ")) and current_list_key:
            item = line[line.index("-") + 1 :].strip().strip('"').strip("'")
            current_list.append(item)
            out[current_list_key] = current_list
            continue
        if ":" in line and not line.startswith(" "):
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if val == "":
                current_list_key = key
                current_list = []
                out[key] = current_list
            else:
                current_list_key = None
                out[key] = val.strip('"').strip("'")
    return out


def _has_glob(s: str) -> bool:
    return any(c in _GLOB_CHARS for c in s)


def _systems_dir_mtime(project_root: str) -> int:
    systems_dir = os.path.join(project_root or ".", ".specify", "systems")
    try:
        return os.stat(systems_dir).st_mtime_ns
    except OSError:
        return 0


@functools.lru_cache(maxsize=8)
def _load_declared_paths_cached(
    project_root: str, mtime_ns: int
) -> tuple[tuple[str, str], ...]:
    """Inner cached function keyed by (project_root, mtime_ns).

    mtime_ns is the `st_mtime_ns` of `<project_root>/.specify/systems/`.
    When the systems dir is modified, the key changes and we reload.
    """
    _ = mtime_ns  # part of cache key only
    return _scan_declared_paths(project_root)


def _scan_declared_paths(project_root: str) -> tuple[tuple[str, str], ...]:
    """Walk `<project_root>/.specify/systems/*/spec.md`, parse frontmatter,
    and return a tuple of (prefix, system_id) sorted by prefix length desc.

    Defensive: drops any entry containing glob characters (logs to stderr
    when SMITH_DEBUG=1). Returns () if the directory does not exist.
    """
    systems_dir = os.path.join(project_root or ".", ".specify", "systems")
    if not os.path.isdir(systems_dir):
        return ()
    debug = os.environ.get("SMITH_DEBUG") == "1"
    pairs: list[tuple[str, str]] = []
    try:
        entries = sorted(os.listdir(systems_dir))
    except OSError:
        return ()
    for name in entries:
        spec_path = os.path.join(systems_dir, name, "spec.md")
        if not os.path.isfile(spec_path):
            continue
        fm = _parse_yaml_frontmatter(spec_path)
        if not fm:
            continue
        system_id = fm.get("system") or name
        if not isinstance(system_id, str) or not system_id:
            system_id = name
        paths = fm.get("paths") or []
        if not isinstance(paths, list):
            continue
        for prefix in paths:
            if not isinstance(prefix, str) or not prefix:
                continue
            if _has_glob(prefix):
                if debug:
                    sys.stderr.write(
                        f"path-resolver: dropping glob prefix {prefix!r} "
                        f"from {spec_path}\n"
                    )
                continue
            pairs.append((prefix, system_id))
    pairs.sort(key=lambda t: len(t[0]), reverse=True)
    return tuple(pairs)


def _load_declared_paths(project_root: str) -> tuple[tuple[str, str], ...]:
    """Public-ish wrapper that supplies the mtime cache key."""
    mt = _systems_dir_mtime(project_root)
    return _load_declared_paths_cached(project_root or "", mt)


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


# Sentinels recording which tier matched last (diagnostics only).
_LAST_TIER: dict[str, str] = {"tier": ""}


def _last_matched_tier() -> str:
    """Diagnostic: which tier produced the most recent resolve() result.

    Returns one of "", "tier1", "tier2", "tier3".
    """
    return _LAST_TIER.get("tier", "")


def resolve(
    file_path: str,
    project_root: str = "",
    system_paths_json: str | None = None,
    overrides_dict: dict[str, Any] | None = None,
) -> str:
    """Resolve `file_path` to a Smith system name.

    Tier order:
      1. `.specify/systems/<name>/spec.md` frontmatter (longest-prefix wins)
      2. Explicit `system-paths.json` overrides (longest-prefix wins)
      3. Heuristic (services/<X>/, backend/<X>/, etc.)

    Args:
        file_path: Source file path. May be absolute or relative.
        project_root: Optional. Used to strip prefix from absolute
            file_paths AND as the root to look for `.specify/systems/`.
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

    # Tier 1: `.specify/systems/<name>/spec.md` frontmatter.
    declared = _load_declared_paths(project_root or "")
    for prefix, system_id in declared:
        if rel.startswith(prefix):
            _LAST_TIER["tier"] = "tier1"
            return system_id

    # Tier 2: explicit overrides (`system-paths.json`).
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
        _LAST_TIER["tier"] = "tier2"
        return explicit

    # If the overrides file declares an explicit default, honor it (per
    # data-model.md section 6: "If none match, return `default`.").
    if has_explicit_default:
        _LAST_TIER["tier"] = "tier2"
        return explicit_default

    # Tier 3: heuristic.
    _LAST_TIER["tier"] = "tier3"
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
