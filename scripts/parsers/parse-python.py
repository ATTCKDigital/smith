#!/usr/bin/env python3
"""
parse-python.py — Smith Python source parser.

Reads a single Python source file and emits JSON to stdout matching the
shape declared in contracts/parser-output.schema.json.

Hard constraints (per spec):
  - Stdlib only (no external deps).
  - Never crash. On SyntaxError, emit partial JSON with `errors` populated.
  - p95 latency < 200ms for files up to ~2000 lines.
  - JSON output is the ONLY thing on stdout. Diagnostics go to stderr.

Usage:
    python3 parse-python.py <path>

Exit codes:
  0  Successful parse OR partial parse (always — never block the caller).
  2  Argv error (missing path).
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import sys
from typing import Any


# --- Stable method id (v2) -------------------------------------------------
def _canonical_param(p: dict[str, Any]) -> str:
    name = p.get("name", "")
    typ = p.get("type")
    if typ is None or typ == "":
        typ = "_"
    default = p.get("default")
    if default is None or default == "":
        default = "_"
    return f"{name}:{typ}={default}"


def _canonical_signature(params: list[dict[str, Any]], return_type: str | None) -> str:
    body = ",".join(_canonical_param(p) for p in params)
    rt = return_type if (return_type is not None and return_type != "") else "_"
    return f"{body}->{rt}"


def _normalize_module_path(path: str) -> str:
    """Project-relative POSIX path. Uses CWD as project root if `path` is
    absolute and rooted there; otherwise strips a leading `./`.
    """
    p = path.replace(os.sep, "/")
    cwd = os.getcwd().replace(os.sep, "/").rstrip("/") + "/"
    if p.startswith(cwd):
        p = p[len(cwd) :]
    if p.startswith("./"):
        p = p[2:]
    return p


def _stable_method_id(
    module_path: str,
    scope_chain: str,
    name: str,
    params: list[dict[str, Any]],
    return_type: str | None,
) -> str:
    """Stable 16-char hex id per research.md §1."""
    sig = _canonical_signature(params, return_type)
    canon = f"{module_path}::{scope_chain}::{name}::{sig}"
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


# --- Route decorator detection ---------------------------------------------
# Matches:
#   @app.get("/x"), @router.post(...), @app.route("/x", methods=["POST"])
# Method captured from attribute name (get/post/put/...) or from
# methods=[...] keyword when the attribute is "route".
_ROUTE_VERBS = {"get", "post", "put", "patch", "delete", "head", "options"}
_FASTAPI_TARGETS = {"app", "router"}
# Compile regex used for SyntaxError-fallback import extraction.
_IMPORT_RE = re.compile(r"^\s*(?:from\s+([\w\.]+)\s+import\s+(.+)|import\s+(.+))")


def _count_lines(source: str) -> int:
    """Total line count including the trailing line if not newline-terminated."""
    if not source:
        return 0
    n = source.count("\n")
    if not source.endswith("\n"):
        n += 1
    return n


def _safe_unparse(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:
        return None


def _first_docstring_line(node: ast.AST) -> str | None:
    """Return the first line of the docstring, stripped, or None."""
    try:
        doc = ast.get_docstring(node, clean=False)
    except Exception:
        return None
    if not doc:
        return None
    first = doc.strip().splitlines()[0].strip() if doc.strip() else ""
    return first or None


def _extract_params(args: ast.arguments) -> list[dict[str, Any]]:
    """Extract function params with type annotations + defaults as strings."""
    params: list[dict[str, Any]] = []

    # Positional + keyword-or-positional args.
    pos_args = list(args.posonlyargs) + list(args.args)
    defaults = list(args.defaults)  # tail-aligned with pos_args
    default_offset = len(pos_args) - len(defaults)

    for i, a in enumerate(pos_args):
        entry: dict[str, Any] = {"name": a.arg}
        ann = _safe_unparse(a.annotation)
        if ann is not None:
            entry["type"] = ann
        else:
            entry["type"] = None
        di = i - default_offset
        if di >= 0 and di < len(defaults):
            d = _safe_unparse(defaults[di])
            if d is not None:
                entry["default"] = d
        params.append(entry)

    # *args
    if args.vararg is not None:
        entry = {"name": "*" + args.vararg.arg}
        ann = _safe_unparse(args.vararg.annotation)
        entry["type"] = ann
        params.append(entry)

    # Keyword-only args.
    for i, a in enumerate(args.kwonlyargs):
        entry = {"name": a.arg}
        ann = _safe_unparse(a.annotation)
        entry["type"] = ann
        kd = args.kw_defaults[i] if i < len(args.kw_defaults) else None
        if kd is not None:
            d = _safe_unparse(kd)
            if d is not None:
                entry["default"] = d
        params.append(entry)

    # **kwargs
    if args.kwarg is not None:
        entry = {"name": "**" + args.kwarg.arg}
        ann = _safe_unparse(args.kwarg.annotation)
        entry["type"] = ann
        params.append(entry)

    return params


def _is_function_def(node: ast.AST) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))


def _extract_functions(tree: ast.AST, module_path: str = "") -> list[dict[str, Any]]:
    """Module-level functions only (methods are captured under classes)."""
    out: list[dict[str, Any]] = []
    if not isinstance(tree, ast.Module):
        return out
    for node in tree.body:
        if not _is_function_def(node):
            continue
        params = _extract_params(node.args)
        ret = _safe_unparse(node.returns)
        entry: dict[str, Any] = {
            "id": _stable_method_id(module_path, "", node.name, params, ret),
            "name": node.name,
            "line": node.lineno,
            "params": params,
            "return_type": ret,
            "docstring": _first_docstring_line(node),
            "is_async": isinstance(node, ast.AsyncFunctionDef),
        }
        out.append(entry)
    return out


def _extract_classes(tree: ast.AST, module_path: str = "") -> list[dict[str, Any]]:
    """Top-level classes; methods are flattened one level."""
    out: list[dict[str, Any]] = []
    if not isinstance(tree, ast.Module):
        return out
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        methods: list[dict[str, Any]] = []
        for child in node.body:
            if _is_function_def(child):
                m_params = _extract_params(child.args)
                m_ret = _safe_unparse(child.returns)
                mid = _stable_method_id(
                    module_path, node.name, child.name, m_params, m_ret
                )
                methods.append({"id": mid, "name": child.name, "line": child.lineno})
        bases: list[str] = []
        for b in node.bases:
            text = _safe_unparse(b)
            if text:
                bases.append(text)
        entry: dict[str, Any] = {
            "name": node.name,
            "line": node.lineno,
            "methods": methods,
        }
        if bases:
            entry["bases"] = bases
        out.append(entry)
    return out


def _extract_imports(tree: ast.AST) -> list[dict[str, Any]]:
    """`import x` and `from x import a, b` — produces a row per statement."""
    out: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                entry: dict[str, Any] = {
                    "line": node.lineno,
                    "name": alias.name,
                    "kind": "import",
                }
                if alias.asname:
                    entry["alias"] = alias.asname
                out.append(entry)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            # Relative import dots prefix.
            if node.level:
                module = "." * node.level + module
            imported = [a.name for a in node.names]
            entry = {
                "line": node.lineno,
                "name": module or ".",
                "kind": "from",
                "imported": imported,
            }
            out.append(entry)
    return out


def _imports_from_regex(source: str) -> list[dict[str, Any]]:
    """Fallback import extractor used when ast.parse fails outright."""
    out: list[dict[str, Any]] = []
    for i, line in enumerate(source.splitlines(), start=1):
        m = _IMPORT_RE.match(line)
        if not m:
            continue
        if m.group(1) is not None:
            module = m.group(1)
            rest = m.group(2)
            imported = [
                p.strip().split(" as ")[0].rstrip(",")
                for p in rest.split(",")
                if p.strip()
            ]
            out.append(
                {"line": i, "name": module, "kind": "from", "imported": imported}
            )
        else:
            rest = m.group(3)
            for name in rest.split(","):
                name = name.strip()
                if not name:
                    continue
                alias = None
                if " as " in name:
                    name, alias = (s.strip() for s in name.split(" as ", 1))
                entry = {"line": i, "name": name, "kind": "import"}
                if alias:
                    entry["alias"] = alias
                out.append(entry)
    return out


def _decorator_route_info(dec: ast.AST) -> tuple[str, str, str] | None:
    """
    Return (method, path, framework) if the decorator looks like a route
    decorator; otherwise None.

    Patterns recognised:
      @app.get("/x")            -> ("GET",  "/x", "fastapi")
      @router.post("/x")        -> ("POST", "/x", "fastapi")
      @app.route("/x")          -> ("GET",  "/x", "flask")   (default GET)
      @app.route("/x", methods=["POST"])
                                -> ("POST", "/x", "flask")
      @router.route("/x")       -> ("GET",  "/x", "flask")
    """
    if not isinstance(dec, ast.Call):
        return None
    func = dec.func
    if not isinstance(func, ast.Attribute):
        return None
    if not isinstance(func.value, ast.Name):
        return None
    target = func.value.id
    if target not in _FASTAPI_TARGETS:
        return None
    attr = func.attr.lower()

    # Resolve path arg.
    path = None
    if dec.args:
        first = dec.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            path = first.value
    if path is None:
        return None

    if attr in _ROUTE_VERBS:
        return (attr.upper(), path, "fastapi")

    if attr == "route":
        method = "GET"
        for kw in dec.keywords:
            if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                methods = []
                for elt in kw.value.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        methods.append(elt.value.upper())
                if methods:
                    method = methods[0]
        return (method, path, "flask")

    return None


def _extract_routes(tree: ast.AST) -> list[dict[str, Any]]:
    """Walk decorated function defs and emit one route per matching decorator."""
    out: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not _is_function_def(node):
            continue
        for dec in node.decorator_list:
            info = _decorator_route_info(dec)
            if info is None:
                continue
            method, path, framework = info
            if method not in {
                "GET",
                "POST",
                "PUT",
                "PATCH",
                "DELETE",
                "HEAD",
                "OPTIONS",
                "ANY",
            }:
                method = "ANY"
            out.append(
                {
                    "method": method,
                    "path": path,
                    "line": node.lineno,
                    "function": node.name,
                    "framework": framework,
                }
            )
    return out


def parse(path: str) -> dict[str, Any]:
    """Top-level entrypoint. Always returns a dict matching the schema."""
    result: dict[str, Any] = {
        "path": path,
        "language": "python",
        "lines": 0,
        "functions": [],
        "classes": [],
        "imports": [],
        "routes": [],
        "exports": [],
        "errors": [],
    }

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
    except FileNotFoundError as e:
        result["errors"].append({"message": f"file not found: {e}"})
        return result
    except OSError as e:
        result["errors"].append({"message": f"read error: {e}"})
        return result

    result["lines"] = _count_lines(source)
    module_path = _normalize_module_path(path)

    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as e:
        # Best-effort partial extraction via regex.
        result["errors"].append(
            {
                "line": e.lineno or 0,
                "col": (e.offset - 1) if e.offset else 0,
                "message": f"SyntaxError: {e.msg}",
            }
        )
        result["imports"] = _imports_from_regex(source)
        return result
    except ValueError as e:
        result["errors"].append({"message": f"ValueError: {e}"})
        result["imports"] = _imports_from_regex(source)
        return result
    except Exception as e:  # never crash
        result["errors"].append({"message": f"parse error: {type(e).__name__}: {e}"})
        return result

    try:
        result["functions"] = _extract_functions(tree, module_path)
    except Exception as e:
        result["errors"].append({"message": f"functions extract: {e}"})
    try:
        result["classes"] = _extract_classes(tree, module_path)
    except Exception as e:
        result["errors"].append({"message": f"classes extract: {e}"})
    try:
        result["imports"] = _extract_imports(tree)
    except Exception as e:
        result["errors"].append({"message": f"imports extract: {e}"})
    try:
        result["routes"] = _extract_routes(tree)
    except Exception as e:
        result["errors"].append({"message": f"routes extract: {e}"})

    return result


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        sys.stderr.write("usage: parse-python.py <path>\n")
        return 2
    path = argv[1]
    try:
        result = parse(path)
    except Exception as e:  # belt + suspenders
        result = {
            "path": path,
            "language": "python",
            "lines": 0,
            "functions": [],
            "classes": [],
            "imports": [],
            "routes": [],
            "exports": [],
            "errors": [{"message": f"unhandled: {type(e).__name__}: {e}"}],
        }
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
