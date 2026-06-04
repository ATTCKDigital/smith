"""Smoke tests for index_common.passive_parse with Liquid + JSON.

Verifies that .liquid and .json files (added in fix/liquid-json-passive):
  - are recognized via ALLOWED_EXTENSIONS / PASSIVE_EXTS
  - resolve to language="liquid" / "json" in passive_parse output
  - get their line counts reported
  - return empty functions/classes/imports (passive parse — no AST)

Run:
    python3 tests/parsers/test_passive_parse.py
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "scripts" / "parsers"))

import index_common  # noqa: E402


LIQUID_SAMPLE = """{% comment %}
Cart line item rendering.
{% endcomment %}
<div class="cart-item">
  <span>{{ item.title }}</span>
  <input type="number" value="{{ item.quantity }}" />
</div>
"""

JSON_SAMPLE = """{
  "name": "gold-canna-theme",
  "version": "1.2.3",
  "settings": {
    "currency": "USD"
  }
}
"""


class ExtensionListTests(unittest.TestCase):
    def test_liquid_in_allowed_extensions(self) -> None:
        self.assertIn(".liquid", index_common.ALLOWED_EXTENSIONS)
        self.assertIn(".liquid", index_common.PASSIVE_EXTS)

    def test_json_in_allowed_extensions(self) -> None:
        self.assertIn(".json", index_common.ALLOWED_EXTENSIONS)
        self.assertIn(".json", index_common.PASSIVE_EXTS)

    def test_existing_passive_exts_preserved(self) -> None:
        for ext in (".css", ".html", ".sh"):
            self.assertIn(ext, index_common.PASSIVE_EXTS)
            self.assertIn(ext, index_common.ALLOWED_EXTENSIONS)


class PassiveParseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="smith-passive-"))
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name: str, content: str) -> Path:
        p = self.tmp / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_passive_parse_liquid_file(self) -> None:
        path = self._write("cart-item.liquid", LIQUID_SAMPLE)
        result = index_common.passive_parse(path)
        self.assertEqual(result["language"], "liquid")
        self.assertEqual(result["lines"], LIQUID_SAMPLE.count("\n"))
        self.assertEqual(result["functions"], [])
        self.assertEqual(result["classes"], [])
        self.assertEqual(result["imports"], [])
        self.assertEqual(result["errors"], [])

    def test_passive_parse_json_file(self) -> None:
        path = self._write("settings.json", JSON_SAMPLE)
        result = index_common.passive_parse(path)
        self.assertEqual(result["language"], "json")
        self.assertEqual(result["lines"], JSON_SAMPLE.count("\n"))
        self.assertEqual(result["functions"], [])
        self.assertEqual(result["classes"], [])

    def test_passive_parse_sh_regression(self) -> None:
        path = self._write("script.sh", "#!/bin/bash\necho hello\n")
        result = index_common.passive_parse(path)
        self.assertEqual(result["language"], "shell")
        self.assertEqual(result["lines"], 2)

    def test_passive_parse_unknown_ext_falls_through_to_other(self) -> None:
        path = self._write("file.unknown", "content\n")
        result = index_common.passive_parse(path)
        self.assertEqual(result["language"], "other")


class WalkSourceFilesTests(unittest.TestCase):
    """End-to-end: walk a tempdir with mixed extensions, confirm liquid +
    json files land in the result."""

    def test_walk_includes_liquid_and_json(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="smith-walk-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        (tmp / "snippets").mkdir()
        (tmp / "snippets" / "cart-item.liquid").write_text(LIQUID_SAMPLE)
        (tmp / "config").mkdir()
        (tmp / "config" / "settings.json").write_text(JSON_SAMPLE)
        (tmp / "script.sh").write_text("#!/bin/sh\necho hi\n")
        (tmp / "ignored.txt").write_text("not a source ext\n")

        files = index_common.walk_source_files(tmp)
        names = {f.name for f in files}
        self.assertIn("cart-item.liquid", names)
        self.assertIn("settings.json", names)
        self.assertIn("script.sh", names)
        self.assertNotIn("ignored.txt", names)


if __name__ == "__main__":
    unittest.main()
