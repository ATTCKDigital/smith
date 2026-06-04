#!/usr/bin/env python3
"""
run.py — /smith-index implementation.

Builds the project manifest under .smith/index/ by walking source files,
invoking the per-language parsers (parse-python.py, parse-js.js), and
emitting:

  .smith/index/manifest.md             (top-level, <=50 lines)
  .smith/index/systems/<sys>.md        (per-system, <=80 lines)
  .smith/index/files/<mirror>.meta     (per-file detail)
  .smith/index/.smith-index-checkpoint.json (resume state)
  ~/.smith/logs/smith-index-<ISO>.jsonl     (Rule 4 structured log)

Supports flags:
  --check               hash-only staleness scan, no rebuild
  --system <name>       partial rebuild for one system
  --migrate-templates   patch constitution.md and CLAUDE.md non-destructively
  --incremental         re-parse only `git diff` changed files
  --init-system-paths   write a default system-paths.json
  --resume              resume from checkpoint
  --root <path>         override project root (default: cwd)
  --from <ref> --to <ref>   incremental git refs

Stdlib only. Calls parsers via subprocess.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# --- Constants --------------------------------------------------------------

ALLOWED_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".css",
    ".html",
    ".sh",
    ".liquid",
    ".json",
}
PYTHON_EXTS = {".py"}
JS_EXTS = {".js", ".jsx", ".ts", ".tsx"}
# Extensions we touch but have no parser for (just count lines + hash).
PASSIVE_EXTS = {".css", ".html", ".sh", ".liquid", ".json"}

EXCLUDED_DIR_NAMES = {
    "node_modules",
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    "vendor",
    ".specify",
    ".smith",
    ".pytest_cache",
    ".tox",
    ".idea",
    ".vscode",
    "target",
    "coverage",
    ".coverage",
    "htmlcov",
}

MANIFEST_MAX_LINES = 50
SYSTEM_MAX_LINES = 80
SYSTEM_MAX_FILES_LISTED = 60  # Truncate beyond this; data-model section 3 (>65).

HASH_BYTES = 4096  # SHA-256 of first 4KB.
THRESHOLD_300 = 300
THRESHOLD_500 = 500
THRESHOLD_200 = 200

# --- Path helpers ----------------------------------------------------------

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent.parent  # smith-manifest-system root
PARSER_DIR_REPO = REPO_ROOT / "scripts" / "parsers"
PARSER_DIR_GLOBAL = Path.home() / ".smith" / "scripts"

# Add parser locations to sys.path so we can `import path_resolver` etc.
# Prefer the dev-tree layout (PARSER_DIR_REPO) for in-tree runs, then fall
# back to the production install layout (PARSER_DIR_GLOBAL = ~/.smith/scripts/,
# flat — that's how install-parsers.sh stages them). This dual-layout matters
# because when run.py is installed to ~/.smith/scripts/smith-index/run.py,
# REPO_ROOT computes to ~/.smith/ and PARSER_DIR_REPO points at
# ~/.smith/scripts/parsers/ — which doesn't exist in the flat install layout.
sys.path.insert(0, str(PARSER_DIR_REPO))
sys.path.insert(0, str(PARSER_DIR_GLOBAL))


def _resolve_parser_module_path(filename: str) -> Path | None:
    """Return the first existing path for a parser-layer module file.

    Tries PARSER_DIR_REPO (dev-tree, scripts/parsers/<name>) first,
    falls back to PARSER_DIR_GLOBAL (production install, ~/.smith/scripts/<name>).
    Returns None if neither exists — callers degrade gracefully.
    """
    for candidate in (PARSER_DIR_REPO / filename, PARSER_DIR_GLOBAL / filename):
        if candidate.is_file():
            return candidate
    return None


try:
    import importlib.util as _ilu

    _pr_path = _resolve_parser_module_path("path-resolver.py")
    if _pr_path:
        _spec = _ilu.spec_from_file_location("path_resolver", _pr_path)
        if _spec and _spec.loader:
            path_resolver = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(path_resolver)  # type: ignore[attr-defined]
        else:
            path_resolver = None  # type: ignore[assignment]
    else:
        path_resolver = None  # type: ignore[assignment]
except Exception:
    path_resolver = None  # type: ignore[assignment]

# meta_describe (v2 description layer). Optional — modes that don't touch
# descriptions never call it. `parse_existing_descriptions` is re-exported
# here so the save hook can import a single name from run.py.
try:
    _md_path = _resolve_parser_module_path("meta_describe.py")
    if _md_path:
        _md_spec = _ilu.spec_from_file_location("meta_describe", _md_path)
        if _md_spec and _md_spec.loader:
            _meta_describe = _ilu.module_from_spec(_md_spec)
            # Python 3.14 dataclass needs the module in sys.modules during exec.
            sys.modules["meta_describe"] = _meta_describe
            _md_spec.loader.exec_module(_meta_describe)  # type: ignore[attr-defined]
        else:
            _meta_describe = None  # type: ignore[assignment]
    else:
        _meta_describe = None  # type: ignore[assignment]
except Exception:
    _meta_describe = None  # type: ignore[assignment]


def parse_existing_descriptions(meta_text: str) -> dict | None:
    """Re-export of meta_describe.parse_meta_descriptions() in dict form.

    Returns the dict shape consumed by render_meta(...
    existing_descriptions=). Returns None when no description layer is
    present in `meta_text` (v1 .meta or empty input).
    """
    if _meta_describe is None:
        return None
    desc = _meta_describe.parse_meta_descriptions(meta_text)
    if desc is None:
        return None
    return _meta_describe.render_description_block(desc)


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_now_ms() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def iso_now_for_filename() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# --- Parser resolution ------------------------------------------------------


def resolve_parser(ext: str, project_root: Path) -> tuple[str, Path] | None:
    """Return (language, parser_path) or None.

    Resolution order:
      1. <project_root>/.smith/scripts/parse-<lang>
      2. ~/.smith/scripts/parse-<lang>
      3. <repo>/scripts/parsers/parse-<lang>
    """
    if ext in PYTHON_EXTS:
        lang = "python"
        name = "parse-python.py"
    elif ext in JS_EXTS:
        lang = "js"
        name = "parse-js.js"
    else:
        return None

    for base in (
        project_root / ".smith" / "scripts",
        PARSER_DIR_GLOBAL,
        PARSER_DIR_REPO,
    ):
        candidate = base / name
        if candidate.is_file():
            return lang, candidate
    return None


# --- File discovery ---------------------------------------------------------


def walk_source_files(root: Path) -> list[Path]:
    """Return list of source files under root, honoring .gitignore via git.

    Falls back to a manual exclusion list if git is unavailable.
    """
    use_git = (root / ".git").exists() and shutil.which("git")
    if use_git:
        try:
            # ls-files: tracked. -o --exclude-standard: untracked but not ignored.
            cmd = [
                "git",
                "-C",
                str(root),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if proc.returncode == 0:
                files: list[Path] = []
                for line in proc.stdout.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    p = root / line
                    if not p.is_file():
                        continue
                    if p.suffix not in ALLOWED_EXTENSIONS:
                        continue
                    # Filter excluded dirs even if git tracks them.
                    rel_parts = Path(line).parts
                    if any(part in EXCLUDED_DIR_NAMES for part in rel_parts):
                        continue
                    files.append(p)
                return sorted(files)
        except (subprocess.TimeoutExpired, OSError):
            pass

    # Fallback: manual walk.
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune excluded dirs in-place.
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIR_NAMES]
        for fn in filenames:
            ext = "." + fn.rsplit(".", 1)[-1] if "." in fn else ""
            if ext in ALLOWED_EXTENSIONS:
                files.append(Path(dirpath) / fn)
    return sorted(files)


# --- Hashing ----------------------------------------------------------------


def sha256_first_4kb(path: Path) -> str:
    try:
        with open(path, "rb") as f:
            chunk = f.read(HASH_BYTES)
        return hashlib.sha256(chunk).hexdigest()
    except OSError:
        return ""


# --- Parser invocation ------------------------------------------------------


def run_parser(
    parser_path: Path, lang: str, file_path: Path, timeout_s: float = 5.0
) -> dict:
    """Run parser, return parsed JSON dict, or partial dict on failure."""
    if lang == "python":
        cmd = ["python3", str(parser_path), str(file_path)]
    elif lang == "js":
        cmd = ["node", str(parser_path), str(file_path)]
    else:
        return _empty_parser_output(file_path, lang)

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
        if proc.stdout:
            try:
                return json.loads(proc.stdout)
            except json.JSONDecodeError as e:
                return _empty_parser_output(
                    file_path,
                    lang,
                    errors=[{"message": f"parser stdout not JSON: {e}"}],
                )
        return _empty_parser_output(
            file_path,
            lang,
            errors=[
                {"message": f"parser exited {proc.returncode}: {proc.stderr[:200]}"}
            ],
        )
    except subprocess.TimeoutExpired:
        return _empty_parser_output(
            file_path,
            lang,
            errors=[{"message": "parser timed out"}],
        )
    except (OSError, FileNotFoundError) as e:
        return _empty_parser_output(
            file_path,
            lang,
            errors=[{"message": f"parser launch failed: {e}"}],
        )


def passive_parse(file_path: Path) -> dict:
    """For .sh/.css/.html/.liquid/.json — just count lines, no AST."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        lines = len(text.splitlines()) + (0 if text.endswith("\n") or not text else 1)
    except OSError:
        lines = 0
    ext = file_path.suffix
    lang = {
        "sh": "shell",
        "css": "css",
        "html": "html",
        "liquid": "liquid",
        "json": "json",
    }.get(ext.lstrip("."), "other")
    return {
        "path": str(file_path),
        "language": lang,
        "lines": lines,
        "functions": [],
        "classes": [],
        "imports": [],
        "routes": [],
        "exports": [],
        "errors": [],
    }


def _empty_parser_output(
    file_path: Path, lang: str, errors: list | None = None
) -> dict:
    """Safe minimal output when parser fails — never crashes calling code."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        lines = len(text.splitlines()) + (0 if text.endswith("\n") or not text else 1)
    except OSError:
        lines = 0
    return {
        "path": str(file_path),
        "language": lang,
        "lines": lines,
        "functions": [],
        "classes": [],
        "imports": [],
        "routes": [],
        "exports": [],
        "errors": errors or [],
    }


# --- Meta file rendering ----------------------------------------------------


def render_meta(
    rel_path: str,
    parsed: dict,
    hash_hex: str,
    existing_descriptions: dict | None = None,
) -> str:
    """Render markdown .meta per data-model.md §2.

    `existing_descriptions` (optional) carries the description layer to
    splice in:
      {
        "module_description": str | None,
        "described_against_hash": str | None,
        "described_at": str | None,
        "method_descriptions": {<id>: <description>, ...},
      }
    When None, the description-layer lines are omitted entirely (v1
    layout). When present, three header lines are inserted after `Hash:`
    and per-method `Id:`/`Description:` entries are rendered inline inside
    `## Functions` and `## Classes`.
    """
    lines_count = parsed.get("lines", 0)
    language = parsed.get("language", "unknown")
    out: list[str] = []
    out.append(f"# {rel_path}")
    out.append(f"Last Updated: {iso_now()}")
    out.append(f"Language: {language}")
    out.append(f"Lines: {lines_count}")
    out.append(f"Hash: {hash_hex}")

    # v2 description layer (additive). Per data-model.md §2.1, lines are
    # emitted only when present in `existing_descriptions`.
    ed = existing_descriptions or {}
    module_desc = ed.get("module_description")
    against_hash = ed.get("described_against_hash")
    described_at = ed.get("described_at")
    method_descs = ed.get("method_descriptions") or {}
    if module_desc:
        out.append(f"**Description:** {module_desc}")
    if against_hash:
        out.append(f"Described-Against-Hash: {against_hash}")
    if described_at:
        out.append(f"Described-At: {described_at}")
    out.append("")
    if lines_count > THRESHOLD_300:
        out.append(
            f"⚠️ Exceeds 300-line threshold ({lines_count} lines). "
            "Consider decomposition."
        )
        out.append("")

    # Imports
    imports = parsed.get("imports") or []
    out.append("## Imports")
    if imports:
        for imp in imports[:60]:  # cap to avoid runaway .meta
            line = imp.get("line", 0)
            name = imp.get("name", "")
            kind = imp.get("kind", "import")
            imported = imp.get("imported") or []
            if kind == "from" and imported:
                joined = ", ".join(imported[:8])
                if len(imported) > 8:
                    joined += ", …"
                out.append(f"- `{name}` → {joined} (line {line})")
            else:
                out.append(f"- `{name}` (line {line}, {kind})")
        if len(imports) > 60:
            out.append(f"_…and {len(imports) - 60} more imports._")
    else:
        out.append("_None._")
    out.append("")

    # Routes
    routes = parsed.get("routes") or []
    out.append("## Routes")
    if routes:
        out.append("| Method | Path | Line | Handler |")
        out.append("|--------|------|------|---------|")
        for r in routes[:60]:
            out.append(
                f"| {r.get('method', '')} | {r.get('path', '')} | "
                f"{r.get('line', '')} | {r.get('function', '')} |"
            )
    else:
        out.append("_None._")
    out.append("")

    # Classes
    classes = parsed.get("classes") or []
    out.append("## Classes")
    if classes:
        for c in classes:
            out.append(f"- `{c.get('name', '')}` (line {c.get('line', '')})")
            for m in (c.get("methods") or [])[:30]:
                out.append(f"  - `{m.get('name', '')}` (line {m.get('line', '')})")
                mid = m.get("id")
                if mid:
                    out.append(f"    Id: {mid}")
                    desc = method_descs.get(mid)
                    if desc:
                        out.append(f"    Description: {desc}")
    else:
        out.append("_None._")
    out.append("")

    # Functions
    functions = parsed.get("functions") or []
    out.append("## Functions")
    if functions:
        for fn in functions:
            params = fn.get("params") or []
            param_strs = []
            for p in params:
                s = p.get("name", "")
                if p.get("type"):
                    s += f": {p['type']}"
                param_strs.append(s)
            sig = ", ".join(param_strs)
            ret = fn.get("return_type")
            ret_s = f" -> {ret}" if ret else ""
            out.append(
                f"- `{fn.get('name', '')}({sig}){ret_s}` (line {fn.get('line', '')})"
            )
            fid = fn.get("id")
            if fid:
                out.append(f"  Id: {fid}")
                desc = method_descs.get(fid)
                if desc:
                    out.append(f"  Description: {desc}")
            # v2 drops parser-derived docstring emission (parser is structure-only).
    else:
        out.append("_None._")
    out.append("")

    # Exports
    exports = parsed.get("exports") or []
    out.append("## Exports")
    if exports:
        for ex in exports[:40]:
            out.append(
                f"- `{ex.get('name', '')}` ({ex.get('kind', 'named')}, "
                f"line {ex.get('line', '')})"
            )
    else:
        out.append("_None._")
    out.append("")

    # Errors
    errors = parsed.get("errors") or []
    out.append("## Parse Errors")
    if errors:
        for e in errors[:10]:
            ln = e.get("line", "?")
            col = e.get("col", "?")
            msg = e.get("message", "")
            out.append(f"- line {ln}, col {col}: {msg}")
    else:
        out.append("_None._")
    out.append("")
    return "\n".join(out)


# --- System manifest rendering ---------------------------------------------


def _exports_summary(parsed: dict) -> str:
    """One-line comma-joined exports column for system manifest."""
    bits: list[str] = []
    for ex in parsed.get("exports") or []:
        n = ex.get("name", "")
        if n:
            bits.append(n)
    if not bits:
        # Python: use module-level functions + classes as proxy.
        for fn in parsed.get("functions") or []:
            bits.append(fn.get("name", ""))
        for c in parsed.get("classes") or []:
            bits.append(c.get("name", ""))
    bits = [b for b in bits if b]
    joined = ", ".join(bits[:20])
    if len(", ".join(bits)) > 80:
        joined = joined[:77] + "…"
    return joined or "(none)"


def render_system_manifest(
    system_name: str, entries: list[dict], description: str = ""
) -> str:
    """entries: list of {path, lines, exports, exceeds}."""
    out: list[str] = []
    out.append(f"# System: {system_name}")
    out.append(f"Last Updated: {iso_now()}")
    out.append("")
    out.append("## Description")
    if description:
        out.append(description.strip())
    else:
        out.append(f"Files mapped to `{system_name}` by the path resolver.")
    out.append("")
    out.append("## Files")
    out.append("")
    out.append("| File | Lines | Description | Exports |")
    out.append("|------|-------|-------------|---------|")

    # Sort by lines desc.
    sorted_entries = sorted(entries, key=lambda e: e.get("lines", 0), reverse=True)
    listed = sorted_entries[:SYSTEM_MAX_FILES_LISTED]
    for e in listed:
        lines = e.get("lines", 0)
        warn = " ⚠️" if lines > THRESHOLD_300 else ""
        # v2: per-module description column (empty when not yet generated).
        desc = (e.get("module_description") or "").replace("|", "\\|")
        out.append(f"| {e['path']} | {lines}{warn} | {desc} | {e['exports']} |")
    remaining = len(sorted_entries) - len(listed)
    if remaining > 0:
        out.append("")
        out.append(f"_…and {remaining} more files (see .meta for full inventory)._")
    return "\n".join(out)


# --- Top-level manifest rendering ------------------------------------------


def render_top_manifest(
    systems: dict[str, list[dict]],
    stats: dict,
    last_full_index: dict | None = None,
    system_descriptions: dict[str, str] | None = None,
) -> str:
    out: list[str] = []
    out.append("# Project Manifest")
    out.append(f"Last Updated: {iso_now()}")
    out.append("")
    out.append("## Systems")
    out.append("")
    out.append("| System | Files | Description |")
    out.append("|--------|-------|-------------|")
    # Sort: system-* alphabetical, then 'unassigned' last.
    sorted_systems = sorted(
        systems.keys(),
        key=lambda n: (n == "unassigned", n == "excluded", n),
    )
    # Cap to 25 rows to respect 50-line budget.
    for name in sorted_systems[:25]:
        count = len(systems[name])
        desc = _system_description(name, system_descriptions)
        out.append(f"| {name} | {count} | {desc} |")
    out.append("")
    out.append("## Stats")
    out.append(f"- Total source files: {stats.get('total', 0)}")
    out.append(f"- Files over 200 lines: {stats.get('over_200', 0)}")
    out.append(f"- Files over 300 lines: {stats.get('over_300', 0)}")
    out.append(f"- Files over 500 lines: {stats.get('over_500', 0)}")
    if last_full_index:
        dur = last_full_index.get("duration_s", 0)
        ts = last_full_index.get("timestamp", iso_now())
        out.append(f"- Last full index: {dur:.1f}s ({ts})")
    return "\n".join(out)


def _system_description(
    name: str, system_descriptions: dict[str, str] | None = None
) -> str:
    # Prefer the spec.md frontmatter `description:` field when present.
    if system_descriptions:
        declared = system_descriptions.get(name)
        if declared:
            # Collapse newlines and escape table-breaking pipes; cap at
            # one line so the 25-row top-manifest stays readable.
            one_line = declared.strip().replace("\n", " ").replace("|", "\\|")
            if len(one_line) > 120:
                one_line = one_line[:117] + "…"
            return one_line
    if name == "unassigned":
        return "Files not assigned to any system"
    if name == "excluded":
        return "Excluded from indexing"
    if name.startswith("system-backend-"):
        return f"Backend: {name[len('system-backend-') :]}"
    if name.startswith("system-frontend-"):
        return f"Frontend: {name[len('system-frontend-') :]}"
    if name.startswith("system-"):
        return name[len("system-") :].replace("-", " ").title()
    return name


# --- Checkpoint + JSONL logging --------------------------------------------


class JsonlLogger:
    def __init__(self, log_path: Path):
        self.path = log_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a", buffering=1)  # line buffered

    def log(
        self, item_id: str, stage: str, status: str = "ok", error: str | None = None
    ) -> None:
        rec = {
            "timestamp": iso_now_ms(),
            "item_id": item_id,
            "stage": stage,
            "status": status,
            "error": error,
        }
        try:
            self._fh.write(json.dumps(rec) + "\n")
        except OSError:
            pass

    def close(self) -> None:
        try:
            self._fh.close()
        except OSError:
            pass


def load_checkpoint(checkpoint_path: Path) -> dict | None:
    if not checkpoint_path.exists():
        return None
    try:
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def save_checkpoint(checkpoint_path: Path, data: dict) -> None:
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


def resume_completed_files(jsonl_path: Path | None) -> set[str]:
    """Return set of paths where stage=system-update + status=ok exists."""
    completed: set[str] = set()
    if not jsonl_path or not jsonl_path.exists():
        return completed
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("stage") == "system-update" and rec.get("status") == "ok":
                    completed.add(rec.get("item_id", ""))
    except OSError:
        pass
    return completed


# --- Core indexing ----------------------------------------------------------


class IndexRun:
    def __init__(
        self,
        project_root: Path,
        log_path: Path,
        system_filter: str | None = None,
        resume: bool = False,
        system_paths_json: Path | None = None,
    ):
        self.project_root = project_root.resolve()
        self.index_dir = self.project_root / ".smith" / "index"
        self.files_dir = self.index_dir / "files"
        self.systems_dir = self.index_dir / "systems"
        self.config_dir = self.index_dir / "config"
        self.checkpoint_path = self.index_dir / ".smith-index-checkpoint.json"
        self.log_path = log_path
        self.logger = JsonlLogger(log_path)
        self.system_filter = system_filter
        self.resume = resume
        self.system_paths_path = system_paths_json or (
            self.config_dir / "system-paths.json"
        )
        self._overrides_dict = self._load_overrides()
        # Aggregations
        self.systems: dict[str, list[dict]] = {}
        self.stats = {"total": 0, "over_200": 0, "over_300": 0, "over_500": 0}
        self.succeeded = 0
        self.failed = 0
        self.skipped = 0
        # spec.md `description:` frontmatter per system id, loaded once.
        # Empty dict if .specify/systems/ is missing or has no usable specs.
        self.system_descriptions: dict[str, str] = self._load_system_descriptions()

    def _load_overrides(self) -> dict | None:
        if not self.system_paths_path.exists():
            return None
        try:
            with open(self.system_paths_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    def _load_system_descriptions(self) -> dict[str, str]:
        """Map system id -> spec.md frontmatter `description:` field.

        Reads `<project_root>/.specify/systems/<id>/spec.md`, falling back
        to `<project_root>/specs/<id>/spec.md` if the canonical location
        is missing. Returns an empty dict on any failure (missing dir,
        unreadable file, malformed frontmatter) — the renderers degrade
        to the legacy title-cased-slug behavior in that case.

        Reuses `path_resolver._parse_yaml_frontmatter` to stay consistent
        with Tier 1 frontmatter semantics.
        """
        out: dict[str, str] = {}
        if path_resolver is None or not hasattr(
            path_resolver, "_parse_yaml_frontmatter"
        ):
            return out
        parse_fm = path_resolver._parse_yaml_frontmatter  # type: ignore[attr-defined]
        for base in (
            self.project_root / ".specify" / "systems",
            self.project_root / "specs",
        ):
            if not base.is_dir():
                continue
            try:
                entries = sorted(p for p in base.iterdir() if p.is_dir())
            except OSError:
                continue
            for system_dir in entries:
                spec_path = system_dir / "spec.md"
                if not spec_path.is_file():
                    continue
                try:
                    fm = parse_fm(str(spec_path))
                except Exception:
                    continue
                if not fm:
                    continue
                # `system:` frontmatter overrides the directory name.
                system_id = fm.get("system") or system_dir.name
                if not isinstance(system_id, str) or not system_id:
                    system_id = system_dir.name
                desc = fm.get("description")
                if isinstance(desc, str) and desc.strip():
                    # First spec wins for a given id; .specify/systems/
                    # is consulted before specs/ so canonical specs are
                    # preferred over legacy ones.
                    out.setdefault(system_id, desc.strip())
        return out

    def setup_dirs(self) -> None:
        for d in (self.index_dir, self.files_dir, self.systems_dir, self.config_dir):
            d.mkdir(parents=True, exist_ok=True)
        # Bootstrap context-manifest.json (Tier 4) from the shipped default
        # if missing. Per T050. Do NOT auto-copy system-paths.json (per Q7).
        target_cm = self.config_dir / "context-manifest.json"
        if not target_cm.exists():
            for candidate in (
                REPO_ROOT
                / "skills"
                / "smith-index"
                / "templates"
                / "context-manifest.default.json",
                REPO_ROOT / "templates" / "context-manifest.default.json",
                Path.home() / ".smith" / "templates" / "context-manifest.default.json",
            ):
                if candidate.exists():
                    try:
                        target_cm.write_text(
                            candidate.read_text(encoding="utf-8"), encoding="utf-8"
                        )
                    except OSError:
                        pass
                    break

    def resolve_system(self, file_path: Path) -> str:
        rel = str(file_path.relative_to(self.project_root))
        if path_resolver is not None:
            try:
                # Pass the real project_root so Tier 1 can find
                # .specify/systems/<id>/spec.md frontmatter. Empty string
                # here used to silently break Tier 1 — see PR (this one):
                # files mapped to "system-<top_dir>" instead of their
                # declared systems on Shopify themes (snippets/, sections/,
                # templates/ became system-snippets etc.) and any other
                # project where the heuristic-fallback bucket didn't match
                # the declared system name.
                return path_resolver.resolve(  # type: ignore[union-attr]
                    rel,
                    project_root=str(self.project_root),
                    overrides_dict=self._overrides_dict,
                )
            except Exception:
                pass
        # Fallback: naive top-dir mapping.
        parts = rel.split("/")
        if len(parts) <= 1:
            return "unassigned"
        top = parts[0]
        if top in EXCLUDED_DIR_NAMES:
            return "excluded"
        return f"system-{top}"

    def process_file(self, file_path: Path) -> dict | None:
        """Parse one file, write .meta, register with system bucket.

        Returns the parsed dict on success (with extra 'system' / 'hash' /
        'rel_path' keys), or None if skipped/failed.
        """
        rel = str(file_path.relative_to(self.project_root))
        ext = file_path.suffix
        try:
            # Determine system.
            system = self.resolve_system(file_path)
            if system == "excluded":
                self.logger.log(rel, "parse", "skipped", error="excluded directory")
                self.skipped += 1
                return None

            # Parse.
            if ext in PASSIVE_EXTS:
                parsed = passive_parse(file_path)
                self.logger.log(rel, "parse", "ok")
            else:
                resolution = resolve_parser(ext, self.project_root)
                if not resolution:
                    self.logger.log(
                        rel, "parse", "skipped", error="no parser available"
                    )
                    self.skipped += 1
                    return None
                lang, parser_path = resolution
                parsed = run_parser(parser_path, lang, file_path)
                if parsed.get("errors"):
                    self.logger.log(
                        rel,
                        "parse",
                        "ok",
                        error=f"partial: {len(parsed['errors'])} errors",
                    )
                else:
                    self.logger.log(rel, "parse", "ok")

            hash_hex = sha256_first_4kb(file_path)
            meta_path = self.files_dir / (rel + ".meta")

            # Read the existing .meta description layer BEFORE overwriting,
            # so render_meta can splice it back into the new render and
            # descriptions survive the structural rebuild. Without this,
            # every full /smith-index call destroys the v2 description
            # layer — see specs/32-preserve-meta-descriptions.
            existing_descriptions = None
            if meta_path.exists():
                try:
                    existing_text = meta_path.read_text(encoding="utf-8")
                    existing_descriptions = parse_existing_descriptions(existing_text)
                except OSError:
                    existing_descriptions = None

            # Write .meta with descriptions spliced in (if any existed).
            meta_text = render_meta(
                rel,
                parsed,
                hash_hex,
                existing_descriptions=existing_descriptions,
            )
            meta_path.parent.mkdir(parents=True, exist_ok=True)
            meta_path.write_text(meta_text, encoding="utf-8")
            self.logger.log(rel, "meta", "ok")

            # Update aggregations.
            lines_count = parsed.get("lines", 0)
            self.stats["total"] += 1
            if lines_count > THRESHOLD_200:
                self.stats["over_200"] += 1
            if lines_count > THRESHOLD_300:
                self.stats["over_300"] += 1
            if lines_count > THRESHOLD_500:
                self.stats["over_500"] += 1

            # Module description for the per-system manifest's Description
            # column. Comes from the same existing_descriptions we already
            # parsed — no need to re-read the file we just wrote.
            module_desc = ""
            if existing_descriptions:
                module_desc = existing_descriptions.get("module_description") or ""

            entry = {
                "path": rel,
                "lines": lines_count,
                "exports": _exports_summary(parsed),
                "exceeds": lines_count > THRESHOLD_300,
                "module_description": module_desc,
            }
            self.systems.setdefault(system, []).append(entry)
            self.succeeded += 1
            return {"rel": rel, "system": system, "parsed": parsed, "hash": hash_hex}
        except Exception as e:
            self.logger.log(rel, "parse", "error", error=f"{type(e).__name__}: {e}")
            self.failed += 1
            return None

    def write_system_manifests(self) -> None:
        for system, entries in self.systems.items():
            description = self.system_descriptions.get(system, "")
            text = render_system_manifest(system, entries, description=description)
            target = self.systems_dir / f"{system}.md"
            target.write_text(text, encoding="utf-8")
            self.logger.log(system, "system-update", "ok")
            # Per-file system-update entries (one per file) for --resume lookup.
            for e in entries:
                self.logger.log(e["path"], "system-update", "ok")

    def write_top_manifest(self, duration_s: float) -> None:
        last_full = {"duration_s": duration_s, "timestamp": iso_now()}
        text = render_top_manifest(
            self.systems,
            self.stats,
            last_full_index=last_full,
            system_descriptions=self.system_descriptions,
        )
        target = self.index_dir / "manifest.md"
        target.write_text(text, encoding="utf-8")
        self.logger.log("manifest.md", "top-update", "ok")

    def write_schema_version_marker(self) -> None:
        """Step 8 of skills/smith-index/SKILL.md: write the manifest's
        schema-version marker so /smith-update can detect projects whose
        manifest was generated against an older .meta schema.

        Source of truth: meta_schema_version.txt shipped by
        scripts/install-parsers.sh (per PR #29) into ~/.smith/scripts/.
        In the smith-repo dev tree the same file lives at
        scripts/parsers/meta_schema_version.txt.

        Silent skip if the source file isn't installed — keeps /smith-index
        usable even on partial installs. The marker is overwritten on
        every full rebuild; never removed by /smith-index itself.
        """
        # Resolve source. Prefer global install (PARSER_DIR_GLOBAL =
        # ~/.smith/scripts/); fall back to repo-dev tree (PARSER_DIR_REPO =
        # <repo>/scripts/parsers/).
        candidates = [
            PARSER_DIR_GLOBAL / "meta_schema_version.txt",
            PARSER_DIR_REPO / "meta_schema_version.txt",
        ]
        source_value: str | None = None
        for candidate in candidates:
            if candidate.is_file():
                try:
                    source_value = candidate.read_text(encoding="utf-8").strip()
                    break
                except OSError:
                    continue
        if not source_value:
            # Partial install — log and skip. Don't fail the run.
            self.logger.log(
                ".schema-version",
                "schema-version",
                "skipped",
                error="meta_schema_version.txt not installed",
            )
            return

        marker = self.index_dir / ".schema-version"
        try:
            marker.write_text(source_value + "\n", encoding="utf-8")
            self.logger.log(".schema-version", "schema-version", "ok")
        except OSError as e:
            self.logger.log(
                ".schema-version",
                "schema-version",
                "failed",
                error=str(e),
            )

    def cleanup(self) -> None:
        # Remove checkpoint on clean exit.
        try:
            if self.checkpoint_path.exists():
                self.checkpoint_path.unlink()
        except OSError:
            pass
        self.logger.close()


# --- Modes ------------------------------------------------------------------


def mode_full(
    project_root: Path,
    log_path: Path,
    system_filter: str | None = None,
    resume: bool = False,
    system_paths: Path | None = None,
) -> int:
    start = time.monotonic()
    run = IndexRun(
        project_root,
        log_path,
        system_filter=system_filter,
        resume=resume,
        system_paths_json=system_paths,
    )
    run.setup_dirs()

    completed: set[str] = set()
    if resume:
        # Find latest JSONL and read completed file set.
        log_dir = log_path.parent
        candidates = sorted(log_dir.glob("smith-index-*.jsonl"))
        if candidates:
            completed = resume_completed_files(candidates[-1])

    files = walk_source_files(project_root)
    if system_filter:
        # Filter to one system; need to resolve system per file.
        files = [f for f in files if run.resolve_system(f) == system_filter]

    for i, fp in enumerate(files):
        rel = str(fp.relative_to(project_root))
        if rel in completed:
            run.skipped += 1
            continue
        run.process_file(fp)
        # Checkpoint every 25 files.
        if i % 25 == 0:
            save_checkpoint(
                run.checkpoint_path,
                {
                    "started_at": iso_now(),
                    "processed_files": i + 1,
                    "last_file": rel,
                    "systems_seen": list(run.systems.keys()),
                },
            )

    # Final manifests.
    run.write_system_manifests()
    duration = time.monotonic() - start
    run.write_top_manifest(duration)
    run.write_schema_version_marker()
    run.cleanup()

    summary = (
        f"/smith-index: {run.stats['total']} files indexed "
        f"({run.succeeded} succeeded, {run.failed} failed, "
        f"{run.skipped} skipped) in {duration:.1f}s"
    )
    print(summary)
    if run.stats.get("over_300", 0):
        print(f"  Files over 300 lines: {run.stats['over_300']}")
    return 0


def mode_check(project_root: Path) -> int:
    """Hash-only staleness scan against existing .meta files."""
    index_dir = project_root / ".smith" / "index"
    files_dir = index_dir / "files"
    if not files_dir.exists():
        print("smith-index --check: no .smith/index/ found. Run /smith-index first.")
        return 0

    stale: list[str] = []
    missing: list[str] = []
    fresh = 0

    for meta_path in files_dir.rglob("*.meta"):
        # Reconstruct source path: strip files_dir prefix and .meta suffix.
        rel_meta = meta_path.relative_to(files_dir)
        # Last component ends in .meta — strip it.
        source_rel = str(rel_meta)
        if source_rel.endswith(".meta"):
            source_rel = source_rel[: -len(".meta")]
        source_path = project_root / source_rel
        if not source_path.exists():
            missing.append(source_rel)
            continue
        # Extract hash from .meta.
        try:
            text = meta_path.read_text(encoding="utf-8")
        except OSError:
            continue
        stored_hash = None
        for line in text.splitlines():
            if line.startswith("Hash: "):
                stored_hash = line[len("Hash: ") :].strip()
                break
        if not stored_hash:
            stale.append(source_rel)
            continue
        live_hash = sha256_first_4kb(source_path)
        if live_hash != stored_hash:
            stale.append(source_rel)
        else:
            fresh += 1

    print(
        f"/smith-index --check: {fresh} fresh, {len(stale)} stale, "
        f"{len(missing)} missing-source"
    )
    if stale:
        print("Stale (.meta hash mismatch):")
        for p in stale[:50]:
            print(f"  - {p}")
        if len(stale) > 50:
            print(f"  …and {len(stale) - 50} more")
    if missing:
        print("Missing source (orphaned .meta):")
        for p in missing[:50]:
            print(f"  - {p}")
        if len(missing) > 50:
            print(f"  …and {len(missing) - 50} more")
    if stale or missing:
        print("\nRun /smith-index (full rebuild) to refresh.")
    return 0


def mode_incremental(
    project_root: Path, log_path: Path, from_ref: str | None, to_ref: str | None
) -> int:
    """Re-parse files changed between two git refs."""
    if not shutil.which("git") or not (project_root / ".git").exists():
        print("/smith-index --incremental: git unavailable, no-op.")
        return 0

    from_r = from_ref or "ORIG_HEAD"
    to_r = to_ref or "HEAD"
    try:
        proc = subprocess.run(
            ["git", "-C", str(project_root), "diff", "--name-only", from_r, to_r],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            print(f"/smith-index --incremental: git diff failed: {proc.stderr[:200]}")
            return 0
        changed_files = [
            line.strip() for line in proc.stdout.splitlines() if line.strip()
        ]
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"/smith-index --incremental: error: {e}")
        return 0

    # Filter to allowed extensions and existing files.
    targets: list[Path] = []
    for rel in changed_files:
        p = project_root / rel
        if not p.exists():
            continue
        if p.suffix not in ALLOWED_EXTENSIONS:
            continue
        if any(part in EXCLUDED_DIR_NAMES for part in p.parts):
            continue
        targets.append(p)

    if not targets:
        print(f"/smith-index --incremental: no source changes from {from_r} to {to_r}.")
        return 0

    run = IndexRun(project_root, log_path)
    run.setup_dirs()
    start = time.monotonic()
    for fp in targets:
        run.process_file(fp)
    # Re-aggregate full systems list by reading .meta files (so unchanged
    # systems still appear in updated manifests).
    _refresh_full_aggregations(run)
    run.write_system_manifests()
    duration = time.monotonic() - start
    run.write_top_manifest(duration)
    run.write_schema_version_marker()
    run.cleanup()
    print(
        f"/smith-index --incremental: {len(targets)} files re-indexed "
        f"in {duration:.1f}s"
    )
    return 0


def mode_rebuild_manifests(project_root: Path, log_path: Path) -> int:
    """Re-render manifest.md + systems/*.md from existing .meta files.

    Use case: after `/smith-index --describe` has updated `.meta` files
    with newly-generated module descriptions, the manifest tables still
    reflect the pre-describe state (process_file's per-system entries
    are populated DURING the source walk, before --describe runs). This
    mode lets the describe skill propagate those descriptions to the
    manifests without re-parsing every source file.

    Behavior:
    - Reads .smith/index/files/*.meta only; never re-runs language parsers.
    - Rebuilds run.systems + run.stats via _refresh_full_aggregations,
      which salvages module_description from each .meta's description layer.
    - Writes systems/<id>.md and manifest.md with the refreshed aggregations.
    - Does NOT touch .meta files or .schema-version (those are owned by
      mode_full / mode_incremental).
    - No-op (exit 0 with a message) if .smith/index/files/ doesn't exist —
      the project hasn't been indexed at all.
    """
    start = time.monotonic()
    run = IndexRun(project_root, log_path)
    if not run.files_dir.exists():
        print(
            "/smith-index --rebuild-manifests: no .smith/index/files/ found. "
            "Run /smith-index first."
        )
        return 0
    run.setup_dirs()
    _refresh_full_aggregations(run)
    run.write_system_manifests()
    duration = time.monotonic() - start
    run.write_top_manifest(duration)
    run.cleanup()
    print(
        f"/smith-index --rebuild-manifests: {run.stats['total']} files "
        f"aggregated from .meta in {duration:.1f}s"
    )
    return 0


def _refresh_full_aggregations(run: IndexRun) -> None:
    """After incremental update, re-scan .meta files to rebuild full
    `run.systems` and `run.stats` so the regenerated system / top manifests
    reflect the entire project, not just the incremental subset."""
    # Reset and walk all .meta entries.
    run.systems = {}
    run.stats = {"total": 0, "over_200": 0, "over_300": 0, "over_500": 0}
    if not run.files_dir.exists():
        return
    for meta_path in run.files_dir.rglob("*.meta"):
        try:
            text = meta_path.read_text(encoding="utf-8")
        except OSError:
            continue
        lines_count = 0
        for line in text.splitlines():
            if line.startswith("Lines: "):
                try:
                    lines_count = int(line[len("Lines: ") :].strip())
                except ValueError:
                    pass
                break
        rel_meta = meta_path.relative_to(run.files_dir)
        source_rel = str(rel_meta)
        if source_rel.endswith(".meta"):
            source_rel = source_rel[: -len(".meta")]
        source_path = run.project_root / source_rel
        if not source_path.exists():
            continue
        system = run.resolve_system(source_path)
        if system == "excluded":
            continue
        # Salvage module description from .meta (if present) for the
        # system manifest's Description column.
        module_desc = ""
        if _meta_describe is not None:
            md = _meta_describe.parse_meta_descriptions(text)
            if md and md.module_description:
                module_desc = md.module_description
        entry = {
            "path": source_rel,
            "lines": lines_count,
            "exports": "(see .meta)",
            "exceeds": lines_count > THRESHOLD_300,
            "module_description": module_desc,
        }
        run.systems.setdefault(system, []).append(entry)
        run.stats["total"] += 1
        if lines_count > THRESHOLD_200:
            run.stats["over_200"] += 1
        if lines_count > THRESHOLD_300:
            run.stats["over_300"] += 1
        if lines_count > THRESHOLD_500:
            run.stats["over_500"] += 1


# --- Template migration ----------------------------------------------------

CONSTITUTION_SECTIONS = [
    "## File Size Policy",
    "## Project Manifest",
]
CLAUDE_SECTIONS = [
    "## Smith Context System",
    "## File Size Awareness",
]


def _read_template_addition(name: str) -> str:
    """Read a template addition. Search:
    1. <project>/.smith/templates/<name>
    2. <repo>/templates/<name>
    3. fallback: built-in string
    """
    repo_template = REPO_ROOT / "templates" / name
    if repo_template.exists():
        return repo_template.read_text(encoding="utf-8")
    home_template = Path.home() / ".smith" / "templates" / name
    if home_template.exists():
        return home_template.read_text(encoding="utf-8")
    return BUILT_IN_TEMPLATES.get(name, "")


BUILT_IN_TEMPLATES: dict[str, str] = {
    "constitution-additions.md": """\
## File Size Policy

Source files should stay under 300 lines as a soft target. Files between
300 and 500 lines warrant a decomposition review; files over 500 lines
SHOULD be decomposed unless they are:

- Auto-generated (schemas, migrations, vendored libraries)
- Single-purpose data files (lookup tables, fixtures)
- Test files where decomposition harms readability

`/smith-audit` and `/smith-build` surface 300/500-line files as advisories
in audit reports and PR descriptions respectively. None of these checks
block — they inform.

## Project Manifest

The project manifest under `.smith/index/` is auto-maintained by the
`manifest-updater.sh` Claude Code hook and refreshed in bulk by the
`/smith-index` skill.

Source files NEVER contain Smith metadata — all generated state lives in
`.smith/index/` only. Run `/smith-index` after major refactors to refresh
the full manifest. The `.smith/index/files/` and `.smith/index/systems/`
subdirectories are gitignored by default; `manifest.md` and `config/` are
committed for team sharing.
""",
    "claude-md-additions.md": """\
## Smith Context System

When the `context-loader.sh` UserPromptSubmit hook is active, Smith-aware
prompts (e.g. `/smith-bugfix`, `/smith-new`, or natural-language triggers
like "let's smith this") will arrive with an `additionalContext` block
already attached. The block contains:

- **Vault sections** — recent sessions, ledger, queue, bank, agents per
  the per-skill `context-manifest.json` config.
- **Manifest Navigator output** — `Must Read`, `Should Read`, and
  `Reference Only` file lists scoped to the task.

**Use the injected context first.** Read the Must Read files in their
entirety, focusing on the `[primary: <range>, <label>]` annotation. Treat
Should Read as supporting context. Reference Only files are for context,
not modification.

If the injection is absent (no Smith trigger detected) or carries the
"Manifest not initialized" sentinel, fall back to normal exploration:
grep, read by hypothesis, and consider running `/smith-index` to enable
structured retrieval.

## File Size Awareness

Before reading any source file over 300 lines, check its `.meta` sidecar
under `.smith/index/files/`. The sidecar lists exports, classes,
functions, and routes — enough to locate your target without a full read.
Reserve full reads of large files for the cases where the navigator's
primary annotation points there.
""",
}


def mode_migrate_templates(project_root: Path) -> int:
    """Detect missing template sections in constitution.md / CLAUDE.md
    and append them non-destructively. Idempotent."""
    candidates: list[tuple[Path, list[str], str]] = []
    # constitution.md locations
    for c in (
        project_root / ".specify" / "memory" / "constitution.md",
        project_root / "constitution.md",
    ):
        if c.exists():
            candidates.append((c, CONSTITUTION_SECTIONS, "constitution-additions.md"))
    # CLAUDE.md locations
    for c in (
        project_root / "CLAUDE.md",
        project_root / ".specify" / "memory" / "CLAUDE.md",
    ):
        if c.exists():
            candidates.append((c, CLAUDE_SECTIONS, "claude-md-additions.md"))

    if not candidates:
        print(
            "/smith-index --migrate-templates: no constitution.md or "
            "CLAUDE.md found in project. No-op."
        )
        return 0

    changed = 0
    for target_path, required_headers, template_name in candidates:
        try:
            existing = target_path.read_text(encoding="utf-8")
        except OSError as e:
            print(f"  skip {target_path}: {e}")
            continue
        missing = [h for h in required_headers if h not in existing]
        if not missing:
            print(f"  {target_path}: all sections present, no change")
            continue
        addition = _read_template_addition(template_name)
        if not addition:
            print(f"  skip {target_path}: no template content for {template_name}")
            continue
        # Filter addition: only append blocks for missing sections.
        blocks = _split_template_sections(addition)
        to_append: list[str] = []
        for header in missing:
            block = blocks.get(header)
            if block:
                to_append.append(block)
        if not to_append:
            continue
        # Backup
        backup_path = target_path.with_suffix(
            target_path.suffix + f".bak.{iso_now_for_filename()}"
        )
        backup_path.write_text(existing, encoding="utf-8")
        # Append
        appendix = "\n\n" + "\n\n".join(to_append).rstrip() + "\n"
        target_path.write_text(existing.rstrip() + appendix, encoding="utf-8")
        changed += 1
        print(
            f"  {target_path}: appended {len(to_append)} section(s); "
            f"backup at {backup_path.name}"
        )
    print(f"/smith-index --migrate-templates: {changed} file(s) updated")
    return 0


def _split_template_sections(text: str) -> dict[str, str]:
    """Split markdown into {header_line: full_block} dict keyed by `## ...`."""
    blocks: dict[str, str] = {}
    current_header: str | None = None
    buf: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current_header and buf:
                blocks[current_header] = "\n".join(buf).rstrip()
            current_header = line.rstrip()
            buf = [line]
        else:
            if current_header:
                buf.append(line)
    if current_header and buf:
        blocks[current_header] = "\n".join(buf).rstrip()
    return blocks


# --- init-system-paths -----------------------------------------------------


def mode_init_system_paths(project_root: Path) -> int:
    """Generate a stub system-paths.json from the project's top-level dirs."""
    target = project_root / ".smith" / "index" / "config" / "system-paths.json"
    if target.exists():
        print(
            f"/smith-index --init-system-paths: {target} already exists. "
            "Not overwriting."
        )
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    rules: list[dict] = []
    for entry in sorted(project_root.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name
        if name.startswith(".") or name in EXCLUDED_DIR_NAMES:
            continue
        if name in {"tests", "test", "docs", "doc"}:
            continue
        rules.append(
            {
                "_comment": f"Auto-generated stub for {name}/",
                "prefix": name + "/",
                "system": f"system-{name}",
            }
        )
    payload = {
        "_comment": (
            "Optional path -> system overrides. Longest prefix wins. "
            "If empty/missing, heuristic in path-resolver.py applies."
        ),
        "rules": rules,
        "default": "unassigned",
    }
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        f"/smith-index --init-system-paths: wrote {target} with "
        f"{len(rules)} stub rule(s)"
    )
    return 0


# --- Main -------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="smith-index",
        description="Smith manifest indexer",
    )
    parser.add_argument(
        "--check", action="store_true", help="Hash-only staleness scan, no rebuild"
    )
    parser.add_argument("--system", help="Partial rebuild for one system")
    parser.add_argument(
        "--migrate-templates",
        action="store_true",
        help="Append missing template sections to constitution.md / CLAUDE.md",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Re-parse only files changed in git diff <from>..<to>",
    )
    parser.add_argument(
        "--init-system-paths",
        action="store_true",
        help="Generate stub system-paths.json from top-level dirs",
    )
    parser.add_argument(
        "--rebuild-manifests",
        action="store_true",
        help=(
            "Re-render manifest.md and systems/*.md from existing .meta "
            "files without re-parsing source. Used by /smith-index "
            "--describe to propagate newly-generated descriptions."
        ),
    )
    parser.add_argument(
        "--resume", action="store_true", help="Resume from existing checkpoint"
    )
    parser.add_argument("--from", dest="from_ref", help="Incremental from-ref")
    parser.add_argument("--to", dest="to_ref", help="Incremental to-ref")
    parser.add_argument("--root", default=".", help="Project root (default: cwd)")
    parser.add_argument("--system-paths", help="Path to system-paths.json")
    # NOTE: --describe / --batch-size / --llm-batch-size / --threshold /
    # --model / --no-interactive were removed in v3 (PR #23). The
    # /smith-index --describe entrypoint now lives in skill prose
    # (skills/smith-index/SKILL.md) which orchestrates Task sub-agents
    # for subscription billing. See specs/23-task-llm-backend/.
    args = parser.parse_args(argv)

    project_root = Path(args.root).resolve()
    log_dir = Path.home() / ".smith" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"smith-index-{iso_now_for_filename()}.jsonl"

    if args.check:
        return mode_check(project_root)
    if args.migrate_templates:
        return mode_migrate_templates(project_root)
    if args.incremental:
        return mode_incremental(project_root, log_path, args.from_ref, args.to_ref)
    if args.init_system_paths:
        return mode_init_system_paths(project_root)
    if args.rebuild_manifests:
        return mode_rebuild_manifests(project_root, log_path)

    # Default: full rebuild (optionally filtered).
    system_paths = Path(args.system_paths) if args.system_paths else None
    return mode_full(
        project_root,
        log_path,
        system_filter=args.system,
        resume=args.resume,
        system_paths=system_paths,
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
