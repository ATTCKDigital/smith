#!/usr/bin/env python3
"""
index_common.py — Shared utilities for /smith-index and the v3 describe helpers.

Extracted from scripts/smith-index/run.py per spec/23-task-llm-backend Plan Decision 3
to avoid a circular import when describe_discover.py / describe_write.py /
describe_checkpoint.py need access to:

  - file discovery (walk_source_files)
  - source hashing (sha256_first_4kb)
  - parser invocation (resolve_parser, run_parser, passive_parse)
  - ISO timestamps (iso_now, iso_now_ms, iso_now_for_filename)
  - checkpoint state I/O (load_checkpoint, save_checkpoint)
  - JSONL logging (JsonlLogger)
  - atomic file writes (atomic_write_text)
  - .meta path resolution (meta_path_for)

Behavior is byte-equivalent to v2 — this is a relocation, not a rewrite.
All v3 callers depend on this module being present in the parser install
location (either repo dev tree or ~/.smith/scripts/).

Stdlib only.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# --- Constants --------------------------------------------------------------

ALLOWED_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".css", ".html", ".sh"}
PYTHON_EXTS = {".py"}
JS_EXTS = {".js", ".jsx", ".ts", ".tsx"}
PASSIVE_EXTS = {".css", ".html", ".sh"}

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

HASH_BYTES = 4096  # SHA-256 of first 4KB.

THRESHOLD_300 = 300  # Line count over which render_meta emits a decomp warning.

# Parser-install layout discovery. Resolved at import time. Callers can
# override PARSER_DIRS by mutating the list before calling resolve_parser.
THIS_DIR = Path(__file__).resolve().parent

# Standard locations checked in order:
#  1. Repo dev tree:        <repo>/scripts/parsers/parse-<lang>
#  2. Global install:       ~/.smith/scripts/parse-<lang>
#  3. Project local:        <project>/.smith/scripts/parse-<lang>
PARSER_DIR_REPO = THIS_DIR  # this file lives next to parse-python.py / parse-js.js
PARSER_DIR_GLOBAL = Path.home() / ".smith" / "scripts"


# --- ISO helpers ------------------------------------------------------------


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_now_ms() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def iso_now_for_filename() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# --- Parser resolution ------------------------------------------------------


def resolve_parser(ext: str, project_root: Path) -> Optional[tuple[str, Path]]:
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
    """For .sh/.css/.html — just count lines, no AST."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        lines = len(text.splitlines()) + (0 if text.endswith("\n") or not text else 1)
    except OSError:
        lines = 0
    ext = file_path.suffix
    lang = {"sh": "shell", "css": "css", "html": "html"}.get(ext.lstrip("."), "other")
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


# --- File discovery ---------------------------------------------------------


def walk_source_files(root: Path) -> list[Path]:
    """Return list of source files under root, honoring .gitignore via git.

    Falls back to a manual exclusion list if git is unavailable.
    """
    use_git = (root / ".git").exists() and shutil.which("git")
    if use_git:
        try:
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


# --- .meta path resolution --------------------------------------------------


def meta_path_for(project_root: Path, rel_path: str) -> Path:
    """Return the .meta path for a given project-relative source path.

    Mirrors the layout in .smith/index/files/<rel_path>.meta — POSIX
    separators in rel_path are translated to native by Path joins.
    """
    return project_root / ".smith" / "index" / "files" / f"{rel_path}.meta"


# --- Atomic writes ----------------------------------------------------------


def atomic_write_text(path: Path, content: str) -> None:
    """Write content to path atomically via tempfile + rename.

    Creates the parent directory if missing. On Windows the rename may
    raise if the target exists — we'd accept that limitation since the
    smith install targets POSIX.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# --- Checkpoint state I/O ---------------------------------------------------


def load_checkpoint(checkpoint_path: Path) -> Optional[dict]:
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


def resume_completed_files(
    jsonl_path: Path | None, stage: str = "system-update"
) -> set[str]:
    """Return the set of item_ids with stage=<stage>+status=ok in the JSONL log."""
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
                if rec.get("stage") == stage and rec.get("status") == "ok":
                    completed.add(rec.get("item_id", ""))
    except OSError:
        pass
    return completed


# --- JSONL log -------------------------------------------------------------


class JsonlLogger:
    def __init__(self, log_path: Path):
        self.path = log_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a", buffering=1)  # line buffered

    def log(
        self,
        item_id: str,
        stage: str,
        status: str = "ok",
        error: str | None = None,
        **extra,
    ) -> None:
        rec = {
            "timestamp": iso_now_ms(),
            "item_id": item_id,
            "stage": stage,
            "status": status,
            "error": error,
        }
        rec.update(extra)
        try:
            self._fh.write(json.dumps(rec) + "\n")
        except OSError:
            pass

    def close(self) -> None:
        try:
            self._fh.close()
        except OSError:
            pass


# --- .meta rendering -------------------------------------------------------


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

    imports = parsed.get("imports") or []
    out.append("## Imports")
    if imports:
        for imp in imports[:60]:
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
    else:
        out.append("_None._")
    out.append("")

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
