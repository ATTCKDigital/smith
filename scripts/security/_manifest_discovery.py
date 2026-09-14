#!/usr/bin/env python3
"""_manifest_discovery.py — shared bounded-depth manifest-discovery module.

Feature 56-supply-chain-gate. Pure library shared by dependency-scan.py
(Sub-layer D) and license-inventory.py (Sub-layer L) so both agree on what
a "manifest" is (data-model.md §2, research.md §7/§8).

    from _manifest_discovery import discover_manifests
    records = discover_manifests(repo_root, extra_excludes=[])

Record fields: manifest_path (repo-relative, forward-slash), ecosystem
("npm"|"poetry"|"pip"|"go"|"cargo"), lockfile_path/lockfile_kind (npm
only: "npm"|"yarn"|"pnpm"|None), node_modules_present (npm only,
bool|None), venv_path (poetry only, str|None). Sorted by manifest_path.

Recognizes package.json, pyproject.toml (only when paired with a sibling
poetry.lock — see boundary below), requirements.txt, go.mod, Cargo.toml.
Bounded to 6 levels of depth from repo_root, excluding the fixed built-in
set (vendor/, node_modules/, .venv/, dist/, build/, .smith/ — the same
family secret-scan.sh:22's BUILTIN_EXCLUDES uses) plus caller-supplied
extra_excludes (additive only, never removes a built-in exclusion).

Documented v1 boundaries (not oversights): go.mod/Cargo.toml records get
lockfile_path/lockfile_kind/node_modules_present/venv_path all None (no
ecosystem-specific handling beyond the FR-8 multi-ecosystem scanners is
defined for these). venv_path is resolved ONLY when pyproject.toml +
poetry.lock are BOTH present in the same directory — None in every other
case, including a bare requirements.txt (system/global python3 is never
substituted, FR-15; None means Sub-layer L skips with "no_venv"). A lone
pyproject.toml with no co-located poetry.lock is NOT recognized as a
manifest in v1 — this feature's only defined Python paths are
poetry-managed or a bare requirements.txt, so an unlocked pyproject.toml
has no defined ecosystem/venv/fallback-tool behavior in either sub-layer.
"""

import fnmatch
import os
import subprocess

MAX_DEPTH = 6
BUILTIN_EXCLUDE_DIRS = {"vendor", "node_modules", ".venv", "dist", "build", ".smith"}
POETRY_ENV_TIMEOUT_SECONDS = 10

# (filename, lockfile_kind), preference order — first match at a
# manifest's directory wins.
NPM_LOCKFILES = (
    ("package-lock.json", "npm"),
    ("npm-shrinkwrap.json", "npm"),
    ("yarn.lock", "yarn"),
    ("pnpm-lock.yaml", "pnpm"),
)


def _rel(path, repo_root):
    return os.path.relpath(path, repo_root).replace(os.sep, "/")


def _join(rel_dir, name):
    return name if rel_dir == "." else f"{rel_dir}/{name}"


def _sibling(manifest_path, filename):
    directory = manifest_path.rsplit("/", 1)[0] if "/" in manifest_path else ""
    return f"{directory}/{filename}" if directory else filename


def _manifest_dir(repo_root, manifest_path):
    """Directory containing `manifest_path`, relative to `repo_root`. Shared
    by dependency-scan.py and license-inventory.py (both already depend on
    this module) so the mapping is defined in exactly one place."""
    rel_dir = manifest_path.rsplit("/", 1)[0] if "/" in manifest_path else ""
    return os.path.join(repo_root, rel_dir) if rel_dir else repo_root


def _is_excluded(rel_path, extra_excludes):
    """Tried directly and with a leading '*/' so 'foo/*' also matches a
    nested 'a/foo/x' (mirrors secret_scan.py's is_excluded)."""
    return any(
        fnmatch.fnmatch(rel_path, g) or fnmatch.fnmatch(rel_path, "*/" + g)
        for g in extra_excludes
    )


def _resolve_poetry_venv(manifest_dir):
    """Best-effort `poetry env info -p`. None on ANY failure — never
    raises (poetry absent, no env, timeout, non-zero exit)."""
    try:
        result = subprocess.run(
            ["poetry", "env", "info", "-p"],
            cwd=manifest_dir,
            capture_output=True,
            text=True,
            timeout=POETRY_ENV_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() or None if result.returncode == 0 else None


def _npm_record(manifest_dir, manifest_path):
    lockfile_path = lockfile_kind = None
    for filename, kind in NPM_LOCKFILES:
        if os.path.isfile(os.path.join(manifest_dir, filename)):
            lockfile_path, lockfile_kind = _sibling(manifest_path, filename), kind
            break
    return {
        "manifest_path": manifest_path,
        "ecosystem": "npm",
        "lockfile_path": lockfile_path,
        "lockfile_kind": lockfile_kind,
        "node_modules_present": os.path.isdir(
            os.path.join(manifest_dir, "node_modules")
        ),
        "venv_path": None,
    }


def _record(manifest_path, ecosystem, venv_path=None):
    return {
        "manifest_path": manifest_path,
        "ecosystem": ecosystem,
        "lockfile_path": None,
        "lockfile_kind": None,
        "node_modules_present": None,
        "venv_path": venv_path,
    }


def discover_manifests(repo_root, extra_excludes=None):
    """Walk `repo_root` (bounded to MAX_DEPTH levels), returning one
    record per recognized manifest, sorted by manifest_path."""
    extra_excludes = extra_excludes or []
    repo_root = os.path.abspath(repo_root)
    records = []

    for dirpath, dirnames, filenames in os.walk(repo_root, topdown=True):
        rel_dir = _rel(dirpath, repo_root)
        depth = 0 if rel_dir == "." else rel_dir.count("/") + 1
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in BUILTIN_EXCLUDE_DIRS
            and depth < MAX_DEPTH
            and not _is_excluded(_join(rel_dir, name), extra_excludes)
        )

        names = set(filenames)

        def keep(filename):
            path = _join(rel_dir, filename)
            return path if not _is_excluded(path, extra_excludes) else None

        if "package.json" in names and (path := keep("package.json")):
            records.append(_npm_record(dirpath, path))
        if (
            "pyproject.toml" in names
            and "poetry.lock" in names
            and (path := keep("pyproject.toml"))
        ):
            records.append(_record(path, "poetry", _resolve_poetry_venv(dirpath)))
        if "requirements.txt" in names and (path := keep("requirements.txt")):
            records.append(_record(path, "pip"))
        if "go.mod" in names and (path := keep("go.mod")):
            records.append(_record(path, "go"))
        if "Cargo.toml" in names and (path := keep("Cargo.toml")):
            records.append(_record(path, "cargo"))

    records.sort(key=lambda r: r["manifest_path"])
    return records


if __name__ == "__main__":
    import sys

    for _rec in discover_manifests(sys.argv[1] if len(sys.argv) > 1 else "."):
        print(_rec)
