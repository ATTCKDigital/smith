"""Stable method id tests for scripts/parsers/parse-python.py (v2).

Exercises the id stability matrix from research.md §1:
  - Rename changes id
  - Body edit preserves id
  - Reorder preserves id
  - Param add/remove changes id
  - Return-type change changes id
  - File move changes id
  - Two files with same fn name produce distinct ids
  - Class method scope_chain reflects class name

    python3 tests/parsers/test_stable_id_python.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
PARSER = os.path.join(REPO, "scripts", "parsers", "parse-python.py")

ID_RE = re.compile(r"^[0-9a-f]{16}$")


def run_parser(path: str, cwd: str | None = None) -> dict:
    result = subprocess.run(
        ["python3", PARSER, path],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=cwd,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"parser exited {result.returncode}: stderr={result.stderr!r}"
        )
    return json.loads(result.stdout)


def write(tmpdir: str, rel: str, content: str) -> str:
    full = os.path.join(tmpdir, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    return full


def fn(out: dict, name: str) -> dict:
    return next(f for f in out["functions"] if f["name"] == name)


def method(out: dict, cls: str, name: str) -> dict:
    c = next(c for c in out["classes"] if c["name"] == cls)
    return next(m for m in c["methods"] if m["name"] == name)


class StableIdShapeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="smith-stable-id-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_id_is_16char_hex_for_every_function_and_method(self):
        write(
            self.tmp,
            "mod.py",
            (
                "def alpha(x: int) -> int:\n"
                "    return x + 1\n"
                "\n"
                "class C:\n"
                "    def m(self, y: int) -> int:\n"
                "        return y\n"
            ),
        )
        out = run_parser("mod.py", cwd=self.tmp)
        for f in out["functions"]:
            self.assertIn("id", f)
            self.assertRegex(f["id"], ID_RE)
        for c in out["classes"]:
            for m in c["methods"]:
                self.assertIn("id", m)
                self.assertRegex(m["id"], ID_RE)


class StableIdMatrixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="smith-stable-id-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _parse_src(self, rel: str, src: str) -> dict:
        write(self.tmp, rel, src)
        return run_parser(rel, cwd=self.tmp)

    def test_body_edit_preserves_id(self):
        v1 = "def deliver(url: str, payload: dict) -> bool:\n    return True\n"
        v2 = (
            "def deliver(url: str, payload: dict) -> bool:\n"
            "    # totally different body\n"
            "    x = 1\n"
            "    y = 2\n"
            "    return False\n"
        )
        a = self._parse_src("a.py", v1)
        b = self._parse_src("a.py", v2)
        self.assertEqual(fn(a, "deliver")["id"], fn(b, "deliver")["id"])

    def test_rename_changes_id(self):
        v1 = "def deliver(url: str) -> bool:\n    return True\n"
        v2 = "def dispatch(url: str) -> bool:\n    return True\n"
        a = self._parse_src("a.py", v1)
        b = self._parse_src("a.py", v2)
        self.assertNotEqual(fn(a, "deliver")["id"], fn(b, "dispatch")["id"])

    def test_reorder_preserves_id(self):
        v1 = (
            "def a(x: int) -> int:\n    return x\n"
            "\n"
            "def b(y: int) -> int:\n    return y\n"
        )
        v2 = (
            "def b(y: int) -> int:\n    return y\n"
            "\n"
            "def a(x: int) -> int:\n    return x\n"
        )
        out1 = self._parse_src("m.py", v1)
        out2 = self._parse_src("m.py", v2)
        self.assertEqual(fn(out1, "a")["id"], fn(out2, "a")["id"])
        self.assertEqual(fn(out1, "b")["id"], fn(out2, "b")["id"])

    def test_param_add_changes_id(self):
        v1 = "def f(x: int) -> int:\n    return x\n"
        v2 = "def f(x: int, y: int) -> int:\n    return x\n"
        a = self._parse_src("a.py", v1)
        b = self._parse_src("a.py", v2)
        self.assertNotEqual(fn(a, "f")["id"], fn(b, "f")["id"])

    def test_param_remove_changes_id(self):
        v1 = "def f(x: int, y: int) -> int:\n    return x\n"
        v2 = "def f(x: int) -> int:\n    return x\n"
        a = self._parse_src("a.py", v1)
        b = self._parse_src("a.py", v2)
        self.assertNotEqual(fn(a, "f")["id"], fn(b, "f")["id"])

    def test_return_type_change_changes_id(self):
        v1 = "def f(x: int) -> int:\n    return x\n"
        v2 = "def f(x: int) -> str:\n    return str(x)\n"
        a = self._parse_src("a.py", v1)
        b = self._parse_src("a.py", v2)
        self.assertNotEqual(fn(a, "f")["id"], fn(b, "f")["id"])

    def test_default_value_change_changes_id(self):
        v1 = "def f(x: int = 3) -> int:\n    return x\n"
        v2 = "def f(x: int = 5) -> int:\n    return x\n"
        a = self._parse_src("a.py", v1)
        b = self._parse_src("a.py", v2)
        self.assertNotEqual(fn(a, "f")["id"], fn(b, "f")["id"])

    def test_file_move_changes_id(self):
        src = "def f(x: int) -> int:\n    return x\n"
        a = self._parse_src("a.py", src)
        b = self._parse_src("sub/b.py", src)
        self.assertNotEqual(fn(a, "f")["id"], fn(b, "f")["id"])

    def test_same_fn_name_distinct_files_distinct_ids(self):
        src = "def shared(x: int) -> int:\n    return x\n"
        a = self._parse_src("a/one.py", src)
        b = self._parse_src("b/two.py", src)
        self.assertNotEqual(fn(a, "shared")["id"], fn(b, "shared")["id"])

    def test_class_method_scope_chain_reflects_class_name(self):
        src = (
            "class A:\n"
            "    def m(self, x: int) -> int:\n"
            "        return x\n"
            "\n"
            "class B:\n"
            "    def m(self, x: int) -> int:\n"
            "        return x\n"
        )
        out = self._parse_src("c.py", src)
        a_m = method(out, "A", "m")
        b_m = method(out, "B", "m")
        # Same name + same signature but different scope_chain -> distinct ids.
        self.assertNotEqual(a_m["id"], b_m["id"])

    def test_async_function_gets_id(self):
        src = "async def f(x: int) -> int:\n    return x\n"
        out = self._parse_src("a.py", src)
        self.assertRegex(fn(out, "f")["id"], ID_RE)

    def test_python_js_recipe_compatibility(self):
        """Same input recipe should produce a stable known-hash."""
        import hashlib

        # Recipe: f"{module}::{scope}::{name}::{params}->{ret}"
        canon = "a.py::::f::x:int=_->int"
        expected = hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]
        src = "def f(x: int) -> int:\n    return x\n"
        out = self._parse_src("a.py", src)
        self.assertEqual(fn(out, "f")["id"], expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
