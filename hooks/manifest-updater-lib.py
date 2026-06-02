#!/usr/bin/env python3
"""
manifest-updater-lib.py — heavy lifting for the manifest-updater.sh hook.

Invoked as: python3 manifest-updater-lib.py <abs-file-path> [<project-root>]

Reads a single source file, runs the appropriate parser, writes the .meta
markdown sidecar under .smith/index/files/<rel>.meta, patches the system
manifest, updates the top-level manifest stats, and (if file > 300 lines)
emits an additionalContext JSON warning to stdout for Claude Code to inject.

Stdout: either empty (no warning) or a single JSON line with
        {"hookSpecificOutput": {"hookEventName": "PostToolUse",
         "additionalContext": "..."}}.

Stderr: structured log lines for hooks.log capture (the bash wrapper
        appends them to ~/.smith/logs/hooks.log).

Exits 0 on success or any soft failure. Exit 1 only on argument error
(parent process should still exit 0 — never block Claude).

Performance target: <500ms p95 per invocation. The bulk of time is parser
subprocess startup.

This module re-uses `render_meta`, `sha256_first_4kb`, `run_parser`,
`passive_parse`, `render_system_manifest`, `render_top_manifest`,
`_exports_summary`, and `THRESHOLD_*` constants from scripts/smith-index/run.py
so the .meta format stays in lock-step with full-rebuild output.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ----------------------------------------------------------------------------
# Locate the project root and load scripts/smith-index/run.py once so we can
# reuse its renderers. The hook runs from the user's project cwd, but our
# script lives in the smith-repo install (or ~/.claude/hooks/ after install).
# We resolve the run.py location by walking up from this script's dir.
# ----------------------------------------------------------------------------

THIS_FILE = Path(__file__).resolve()
HOOK_DIR = THIS_FILE.parent
# Search order for run.py:
#   1. <hook_dir>/../scripts/smith-index/run.py  (repo dev layout)
#   2. ~/.smith/scripts/smith-index/run.py       (post-install layout)
#   3. ~/.claude/scripts/smith-index/run.py      (legacy install layout)
RUN_PY_CANDIDATES = [
    HOOK_DIR.parent / "scripts" / "smith-index" / "run.py",
    Path.home() / ".smith" / "scripts" / "smith-index" / "run.py",
    Path.home() / ".claude" / "scripts" / "smith-index" / "run.py",
]

# Also locate path-resolver.py.
PATH_RESOLVER_CANDIDATES = [
    HOOK_DIR.parent / "scripts" / "parsers" / "path-resolver.py",
    Path.home() / ".smith" / "scripts" / "path-resolver.py",
]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        return None
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    except Exception:
        return None
    return mod


def _find_run_module():
    for cand in RUN_PY_CANDIDATES:
        if cand.is_file():
            mod = _load_module("smith_index_run", cand)
            if mod:
                return mod
    return None


def _find_path_resolver():
    for cand in PATH_RESOLVER_CANDIDATES:
        if cand.is_file():
            mod = _load_module("path_resolver", cand)
            if mod:
                return mod
    return None


run_mod = _find_run_module()
path_resolver = _find_path_resolver()


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

ALLOWED_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".css", ".html", ".sh"}
PARSER_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx"}
PASSIVE_EXTS = {".css", ".html", ".sh"}

EXCLUDED_DIR_PARTS = {
    ".smith",
    "node_modules",
    ".venv",
    "venv",
    "vendor",
    "dist",
    "build",
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".tox",
    "target",
    "coverage",
    ".specify",
}

THRESHOLD_200 = 200
THRESHOLD_300 = 300
THRESHOLD_500 = 500


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def find_project_root(file_path: Path, hint: Path | None = None) -> Path:
    """Walk up from file_path looking for .smith/ or .git/. Fall back to hint
    or cwd."""
    if hint and hint.is_dir():
        return hint
    d = file_path.parent.resolve()
    while d != d.parent:
        if (d / ".smith").is_dir() or (d / ".git").is_dir():
            return d
        d = d.parent
    return Path.cwd().resolve()


def is_excluded(rel_path: str) -> bool:
    parts = rel_path.split("/")
    return any(p in EXCLUDED_DIR_PARTS for p in parts)


def log_line(payload: dict) -> None:
    """Emit one hooks.log structured line to stderr; the bash wrapper appends
    it to ~/.smith/logs/hooks.log."""
    bits = [f"{iso_now()} manifest-updater"]
    for k, v in payload.items():
        sval = str(v).replace(" ", "_").replace("\n", " ")
        bits.append(f"{k}={sval}")
    print(" ".join(bits), file=sys.stderr, flush=True)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "usage: manifest-updater-lib.py <file_path> [<project_root>]",
            file=sys.stderr,
        )
        return 1

    started = time.monotonic()
    file_arg = argv[1]
    root_hint = Path(argv[2]).resolve() if len(argv) > 2 else None

    fp = Path(file_arg).resolve()
    if not fp.is_file():
        log_line({"file": file_arg, "status": "skipped", "reason": "not-a-file"})
        return 0

    ext = fp.suffix
    if ext not in ALLOWED_EXTENSIONS:
        log_line(
            {
                "file": str(fp),
                "ext": ext,
                "status": "skipped",
                "reason": "ext-not-allowed",
            }
        )
        return 0

    project_root = find_project_root(fp, root_hint)
    try:
        rel = str(fp.relative_to(project_root))
    except ValueError:
        # File outside the project; nothing to do.
        log_line(
            {"file": str(fp), "status": "skipped", "reason": "outside-project-root"}
        )
        return 0

    if is_excluded(rel):
        log_line({"file": rel, "status": "skipped", "reason": "excluded-dir"})
        return 0

    if run_mod is None:
        log_line({"file": rel, "status": "skipped", "reason": "no-run-module"})
        return 0

    # Resolve parser (project override > ~/.smith > repo).
    resolution = run_mod.resolve_parser(ext, project_root)  # type: ignore[attr-defined]
    parsed: dict
    parser_label = "passive"
    if ext in PASSIVE_EXTS or resolution is None:
        parsed = run_mod.passive_parse(fp)  # type: ignore[attr-defined]
    else:
        lang, parser_path = resolution
        parser_label = lang
        parsed = run_mod.run_parser(parser_path, lang, fp, timeout_s=1.5)  # type: ignore[attr-defined]

    # Hash + meta paths.
    hash_hex = run_mod.sha256_first_4kb(fp)  # type: ignore[attr-defined]
    index_dir = project_root / ".smith" / "index"
    files_dir = index_dir / "files"
    systems_dir = index_dir / "systems"
    meta_target = files_dir / (rel + ".meta")

    # v2: preserve any existing .meta description layer. The save hook NEVER
    # generates descriptions (LLM-free, <500ms p95 budget). It only carries
    # the existing description block forward into the regenerated .meta.
    # Hash is recomputed; Described-Against-Hash is preserved verbatim, so
    # the mismatch (Hash != Described-Against-Hash) is the implicit
    # staleness signal — no extra marker needed. Per data-model.md §3.2.
    existing_descriptions = None
    if meta_target.exists():
        try:
            existing_text = meta_target.read_text(encoding="utf-8")
            existing_descriptions = run_mod.parse_existing_descriptions(  # type: ignore[attr-defined]
                existing_text
            )
        except OSError:
            existing_descriptions = None

    meta_text = run_mod.render_meta(  # type: ignore[attr-defined]
        rel, parsed, hash_hex, existing_descriptions=existing_descriptions
    )

    # Resolve target system.
    overrides_dict = _load_overrides(project_root)
    if path_resolver is not None:
        try:
            system = path_resolver.resolve(  # type: ignore[union-attr]
                rel, project_root="", overrides_dict=overrides_dict
            )
        except Exception:
            system = "unassigned"
    else:
        system = "unassigned"

    if system == "excluded":
        log_line({"file": rel, "status": "skipped", "reason": "system-excluded"})
        return 0

    # Write .meta atomically.
    index_dir.mkdir(parents=True, exist_ok=True)
    files_dir.mkdir(parents=True, exist_ok=True)
    systems_dir.mkdir(parents=True, exist_ok=True)
    meta_target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(meta_target, meta_text)

    # Update system manifest (read-modify-write: re-walk all .meta entries in
    # that system bucket and re-emit). For very large systems this is the
    # dominant cost; we cap it by reading only .meta files (no source re-parse).
    try:
        _rewrite_system_manifest(
            project_root, system, files_dir, systems_dir, overrides_dict
        )
    except Exception as e:
        log_line(
            {
                "file": rel,
                "system": system,
                "status": "system-write-error",
                "error": type(e).__name__,
            }
        )

    # Update top-level manifest stats.
    try:
        _rewrite_top_manifest(project_root, index_dir, files_dir, overrides_dict)
    except Exception as e:
        log_line({"file": rel, "status": "top-write-error", "error": type(e).__name__})

    lines_count = parsed.get("lines", 0)
    elapsed_ms = int((time.monotonic() - started) * 1000)
    warnings = []
    if lines_count > THRESHOLD_300:
        warnings.append("over-300")
    if lines_count > THRESHOLD_500:
        warnings.append("over-500")

    log_line(
        {
            "file": rel,
            "ext": ext,
            "parser": parser_label,
            "lines": lines_count,
            "system": system,
            "ms": elapsed_ms,
            "warnings": ",".join(warnings) or "none",
            "status": "ok",
        }
    )

    # Emit additionalContext warning on stdout if file is > 300 lines.
    if lines_count > THRESHOLD_300:
        warning = (
            f"⚠️ {rel} is {lines_count} lines (>300). Consider decomposition. "
            f"See .smith/index/files/{rel}.meta."
        )
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": warning,
            }
        }
        print(json.dumps(out), flush=True)

    return 0


# ----------------------------------------------------------------------------
# System / top manifest rewriters
# ----------------------------------------------------------------------------


def _load_overrides(project_root: Path) -> dict | None:
    sp = project_root / ".smith" / "index" / "config" / "system-paths.json"
    if not sp.exists():
        return None
    try:
        with open(sp, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_meta_entry(meta_path: Path, files_dir: Path) -> dict | None:
    """Extract path/lines/exports from a .meta file. Returns
    {path, lines, exports, exceeds} or None on error."""
    try:
        text = meta_path.read_text(encoding="utf-8")
    except OSError:
        return None
    rel_meta = meta_path.relative_to(files_dir)
    source_rel = str(rel_meta)
    if source_rel.endswith(".meta"):
        source_rel = source_rel[: -len(".meta")]
    lines_count = 0
    exports_list: list[str] = []
    in_exports = False
    for line in text.splitlines():
        if line.startswith("Lines: "):
            try:
                lines_count = int(line[len("Lines: ") :].strip())
            except ValueError:
                lines_count = 0
        if line.startswith("## Exports"):
            in_exports = True
            continue
        if in_exports:
            if line.startswith("## "):
                in_exports = False
                continue
            if line.startswith("- `"):
                # `name` (kind, line N)
                try:
                    name = line.split("`")[1]
                    if name:
                        exports_list.append(name)
                except IndexError:
                    pass
    exports_str = ", ".join(exports_list[:20])
    if not exports_str:
        exports_str = "(see .meta)"
    return {
        "path": source_rel,
        "lines": lines_count,
        "exports": exports_str,
        "exceeds": lines_count > THRESHOLD_300,
    }


def _rewrite_system_manifest(
    project_root: Path,
    system_name: str,
    files_dir: Path,
    systems_dir: Path,
    overrides_dict: dict | None,
) -> None:
    """Re-walk all .meta entries and re-emit systems/<system_name>.md."""
    entries: list[dict] = []
    if not files_dir.exists():
        return
    for meta_path in files_dir.rglob("*.meta"):
        entry = _parse_meta_entry(meta_path, files_dir)
        if not entry:
            continue
        # Resolve system for this entry. We only care about entries belonging
        # to system_name.
        if path_resolver is not None:
            try:
                entry_system = path_resolver.resolve(  # type: ignore[union-attr]
                    entry["path"],
                    project_root="",
                    overrides_dict=overrides_dict,
                )
            except Exception:
                entry_system = "unassigned"
        else:
            entry_system = "unassigned"
        if entry_system == system_name:
            entries.append(entry)
    if not entries:
        # Nothing in this system anymore; remove stale system manifest.
        target = systems_dir / f"{system_name}.md"
        if target.exists():
            try:
                target.unlink()
            except OSError:
                pass
        return
    text = run_mod.render_system_manifest(system_name, entries)  # type: ignore[union-attr]
    target = systems_dir / f"{system_name}.md"
    _atomic_write(target, text)


def _rewrite_top_manifest(
    project_root: Path,
    index_dir: Path,
    files_dir: Path,
    overrides_dict: dict | None,
) -> None:
    systems: dict[str, list[dict]] = {}
    stats = {"total": 0, "over_200": 0, "over_300": 0, "over_500": 0}
    if files_dir.exists():
        for meta_path in files_dir.rglob("*.meta"):
            entry = _parse_meta_entry(meta_path, files_dir)
            if not entry:
                continue
            lines = entry["lines"]
            stats["total"] += 1
            if lines > THRESHOLD_200:
                stats["over_200"] += 1
            if lines > THRESHOLD_300:
                stats["over_300"] += 1
            if lines > THRESHOLD_500:
                stats["over_500"] += 1
            if path_resolver is not None:
                try:
                    system = path_resolver.resolve(  # type: ignore[union-attr]
                        entry["path"],
                        project_root="",
                        overrides_dict=overrides_dict,
                    )
                except Exception:
                    system = "unassigned"
            else:
                system = "unassigned"
            if system == "excluded":
                continue
            systems.setdefault(system, []).append(entry)

    # Preserve existing "Last full index" line from the current manifest, if any.
    existing_last_full = _extract_last_full_index(index_dir / "manifest.md")
    text = run_mod.render_top_manifest(  # type: ignore[union-attr]
        systems, stats, last_full_index=existing_last_full
    )
    _atomic_write(index_dir / "manifest.md", text)


def _extract_last_full_index(manifest_md: Path) -> dict | None:
    if not manifest_md.exists():
        return None
    try:
        for line in manifest_md.read_text(encoding="utf-8").splitlines():
            if line.startswith("- Last full index:"):
                # Format: "- Last full index: 47.3s (2026-05-21T11:58:00Z)"
                # Best-effort parse.
                rest = line[len("- Last full index:") :].strip()
                # Try to split "47.3s (timestamp)".
                if "(" in rest and rest.endswith(")"):
                    dur_s, ts = rest.split("(", 1)
                    dur_s = dur_s.strip().rstrip("s")
                    ts = ts.rstrip(")").strip()
                    try:
                        return {"duration_s": float(dur_s), "timestamp": ts}
                    except ValueError:
                        pass
    except OSError:
        pass
    return None


def _atomic_write(path: Path, text: str) -> None:
    """Best-effort atomic write via tempfile + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        # Fallback to direct write.
        try:
            path.write_text(text, encoding="utf-8")
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass


if __name__ == "__main__":
    try:
        rc = main(sys.argv)
    except KeyboardInterrupt:
        rc = 0
    except Exception as e:
        # Never crash the calling hook.
        print(
            f"{iso_now()} manifest-updater status=crash error={type(e).__name__}",
            file=sys.stderr,
            flush=True,
        )
        rc = 0
    sys.exit(rc)
