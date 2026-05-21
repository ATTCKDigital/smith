"""Unit tests for scripts/parsers/parse-python.py.

Runs the parser as a black-box subprocess and asserts JSON output shape.

    python3 -m unittest tests.parsers.test_parse_python
or:
    python3 tests/parsers/test_parse_python.py
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
PARSER = os.path.join(REPO, "scripts", "parsers", "parse-python.py")
FIXTURES = os.path.join(HERE, "fixtures", "python")


def run_parser(path: str) -> dict:
    """Invoke parse-python.py against `path` and return the parsed JSON."""
    result = subprocess.run(
        ["python3", PARSER, path],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"parser exited {result.returncode}: stderr={result.stderr!r}"
        )
    return json.loads(result.stdout)


class ParsePythonTests(unittest.TestCase):
    def test_vanilla(self):
        out = run_parser(os.path.join(FIXTURES, "vanilla.py"))
        self.assertEqual(out["language"], "python")
        self.assertEqual(out["errors"], [])
        names = {f["name"] for f in out["functions"]}
        self.assertEqual(names, {"add", "greet", "_private"})
        add = next(f for f in out["functions"] if f["name"] == "add")
        self.assertEqual(add["docstring"], "Add two numbers.")
        # Greet should grab only first line.
        greet = next(f for f in out["functions"] if f["name"] == "greet")
        self.assertEqual(greet["docstring"], "Say hello.")
        # Import detection.
        modules = {i["name"] for i in out["imports"]}
        self.assertIn("os", modules)
        self.assertIn("sys", modules)
        # Exports must be present and empty for Python.
        self.assertEqual(out["exports"], [])

    def test_async(self):
        out = run_parser(os.path.join(FIXTURES, "async_funcs.py"))
        self.assertEqual(out["errors"], [])
        fetch = next(f for f in out["functions"] if f["name"] == "fetch")
        self.assertTrue(fetch["is_async"])
        self.assertEqual(fetch["return_type"], "str")
        # Default param value preserved as source text.
        stream = next(f for f in out["functions"] if f["name"] == "stream")
        self.assertEqual(stream["params"][0]["name"], "n")
        self.assertEqual(stream["params"][0]["default"], "10")

    def test_classes(self):
        out = run_parser(os.path.join(FIXTURES, "class_with_methods.py"))
        names = {c["name"] for c in out["classes"]}
        self.assertEqual(names, {"Animal", "Dog", "Empty"})
        dog = next(c for c in out["classes"] if c["name"] == "Dog")
        method_names = {m["name"] for m in dog["methods"]}
        self.assertEqual(method_names, {"speak", "fetch"})
        # bases included when present.
        self.assertIn("Animal", dog.get("bases", []))

    def test_fastapi_routes(self):
        out = run_parser(os.path.join(FIXTURES, "fastapi_routes.py"))
        self.assertEqual(out["errors"], [])
        routes = out["routes"]
        # Collect (method, path, function) tuples.
        triples = {(r["method"], r["path"], r["function"]) for r in routes}
        self.assertIn(("GET", "/", "root"), triples)
        self.assertIn(("POST", "/items", "create_item"), triples)
        self.assertIn(("GET", "/users/{id}", "get_user"), triples)
        self.assertIn(("PATCH", "/users/{id}", "update_user"), triples)
        self.assertIn(("DELETE", "/users/{id}", "delete_user"), triples)
        for r in routes:
            self.assertEqual(r["framework"], "fastapi")

    def test_flask_routes(self):
        out = run_parser(os.path.join(FIXTURES, "flask_routes.py"))
        triples = {(r["method"], r["path"], r["function"]) for r in out["routes"]}
        self.assertIn(("GET", "/", "index"), triples)
        self.assertIn(("POST", "/items", "create_item"), triples)
        # Multi-method route — first method wins.
        self.assertIn(("PUT", "/items/<id>", "update_item"), triples)

    def test_type_hints(self):
        out = run_parser(os.path.join(FIXTURES, "type_hints.py"))
        self.assertEqual(out["errors"], [])
        find = next(f for f in out["functions"] if f["name"] == "find")
        self.assertEqual(find["return_type"], "Optional[int]")
        params = {p["name"]: p for p in find["params"]}
        self.assertEqual(params["haystack"]["type"], "list[str]")
        group = next(f for f in out["functions"] if f["name"] == "group")
        params = {p["name"]: p for p in group["params"]}
        self.assertEqual(params["values"]["type"], "dict[str, list[int]]")

    def test_docstrings(self):
        out = run_parser(os.path.join(FIXTURES, "docstrings.py"))
        documented = next(f for f in out["functions"] if f["name"] == "documented")
        self.assertEqual(documented["docstring"], "First line of docstring.")
        undocumented = next(f for f in out["functions"] if f["name"] == "undocumented")
        self.assertIsNone(undocumented["docstring"])

    def test_empty(self):
        out = run_parser(os.path.join(FIXTURES, "empty.py"))
        self.assertEqual(out["errors"], [])
        self.assertEqual(out["functions"], [])
        self.assertEqual(out["classes"], [])
        # Has 1 line (comment).
        self.assertGreaterEqual(out["lines"], 1)

    def test_syntax_error_partial(self):
        """SyntaxError → partial output, never crash, errors populated."""
        out = run_parser(os.path.join(FIXTURES, "syntax_error.py"))
        self.assertGreater(len(out["errors"]), 0)
        self.assertIn("Syntax", out["errors"][0]["message"])
        # Import regex fallback still finds the imports.
        modules = {i["name"] for i in out["imports"]}
        self.assertIn("os", modules)
        self.assertIn("collections", modules)

    def test_missing_file(self):
        out = run_parser("/nonexistent/path/no-such-file.py")
        self.assertGreater(len(out["errors"]), 0)
        # Schema still satisfied.
        for key in (
            "path",
            "language",
            "lines",
            "functions",
            "classes",
            "imports",
            "routes",
            "exports",
            "errors",
        ):
            self.assertIn(key, out)

    def test_required_fields_present(self):
        """Every fixture output must have all required schema keys."""
        for name in os.listdir(FIXTURES):
            if not name.endswith(".py"):
                continue
            out = run_parser(os.path.join(FIXTURES, name))
            for key in (
                "path",
                "language",
                "lines",
                "functions",
                "classes",
                "imports",
                "routes",
                "exports",
                "errors",
            ):
                self.assertIn(key, out, f"missing {key} in {name}")

    def test_performance_budget(self):
        """p95 < 200ms target — sanity check single invocation under 500ms."""
        path = os.path.join(FIXTURES, "fastapi_routes.py")
        start = time.perf_counter()
        for _ in range(3):
            run_parser(path)
        elapsed_ms = (time.perf_counter() - start) / 3 * 1000
        self.assertLess(
            elapsed_ms,
            500,
            f"parser too slow: {elapsed_ms:.1f}ms (target <200ms typical, 500ms hard fail)",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
