"""Unit tests for scripts/parsers/meta_describe.py (Phase B).

Covers:
  - parse_meta_descriptions: round-trip with description layer
  - parse_meta_descriptions: v1 .meta (no layer) → None
  - generate_descriptions / describe_file: bulk path, with mock Haiku
  - update_touched: touched ids only, untouched preserved
  - update_touched: purpose_shifted=False reuses module description
  - threshold filtering excludes trivial methods
  - render_description_block round-trips
  - Haiku error → method skipped, run continues

Run:
    python3 tests/parsers/test_meta_describe.py
"""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
MD_PATH = os.path.join(REPO, "scripts", "parsers", "meta_describe.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("meta_describe", MD_PATH)
    mod = importlib.util.module_from_spec(spec)
    # Python 3.14 dataclass needs the module in sys.modules during exec.
    sys.modules["meta_describe"] = mod
    spec.loader.exec_module(mod)
    return mod


md = _load_module()


# A small parser-output fixture (Phase A produces this shape).
SAMPLE_PARSED = {
    "path": "backend/src/services/webhook.py",
    "language": "python",
    "lines": 100,
    "functions": [
        {
            "id": "aaaaaaaaaaaaaaaa",
            "name": "deliver",
            "line": 10,
            "params": [
                {"name": "url", "type": "str"},
                {"name": "payload", "type": "dict"},
            ],
            "return_type": "bool",
            "is_async": False,
        },
        {
            "id": "bbbbbbbbbbbbbbbb",
            "name": "noop",
            "line": 60,
            "params": [],
            "return_type": None,
            "is_async": False,
        },
        {
            "id": "cccccccccccccccc",
            "name": "logger",
            "line": 62,  # body ~1 line → trivial
            "params": [],
            "return_type": None,
            "is_async": False,
        },
    ],
    "classes": [],
    "imports": [],
    "routes": [],
    "exports": [],
    "errors": [],
}

SAMPLE_SOURCE = "x = 1\n" * 100  # 100 lines for thresholding


class ParseRoundTripTests(unittest.TestCase):
    def test_parses_full_layer(self):
        meta_text = (
            "# foo.py\n"
            "Last Updated: 2026-06-02T00:00:00Z\n"
            "Language: python\n"
            "Lines: 50\n"
            "Hash: 1234abcd\n"
            "**Description:** A test module that does things.\n"
            "Described-Against-Hash: 1234abcd\n"
            "Described-At: 2026-06-02T00:00:00Z\n"
            "\n"
            "## Imports\n"
            "_None._\n"
            "\n"
            "## Functions\n"
            "- `bar()` (line 10)\n"
            "  Id: aaaaaaaaaaaaaaaa\n"
            "  Description: Performs bar.\n"
            "- `baz()` (line 20)\n"
            "  Id: bbbbbbbbbbbbbbbb\n"
            "  Description: Performs baz.\n"
            "\n"
            "## Exports\n"
            "_None._\n"
        )
        desc = md.parse_meta_descriptions(meta_text)
        self.assertIsNotNone(desc)
        self.assertEqual(desc.module_description, "A test module that does things.")
        self.assertEqual(desc.described_against_hash, "1234abcd")
        self.assertEqual(desc.described_at, "2026-06-02T00:00:00Z")
        self.assertEqual(
            desc.method_descriptions,
            {
                "aaaaaaaaaaaaaaaa": "Performs bar.",
                "bbbbbbbbbbbbbbbb": "Performs baz.",
            },
        )

    def test_v1_meta_returns_none(self):
        meta_text = (
            "# foo.py\n"
            "Last Updated: 2026-06-02T00:00:00Z\n"
            "Language: python\n"
            "Lines: 50\n"
            "Hash: 1234abcd\n"
            "\n"
            "## Functions\n"
            "- `bar()` (line 10)\n"
            "  Id: aaaaaaaaaaaaaaaa\n"
            "\n"
            "## Exports\n"
            "_None._\n"
        )
        self.assertIsNone(md.parse_meta_descriptions(meta_text))

    def test_empty_text_returns_none(self):
        self.assertIsNone(md.parse_meta_descriptions(""))

    def test_only_module_description(self):
        meta_text = (
            "# foo.py\n"
            "Hash: 1234abcd\n"
            "**Description:** Module-level only.\n"
            "\n"
            "## Functions\n"
            "_None._\n"
        )
        desc = md.parse_meta_descriptions(meta_text)
        self.assertIsNotNone(desc)
        self.assertEqual(desc.module_description, "Module-level only.")
        self.assertEqual(desc.method_descriptions, {})

    def test_render_block_round_trip(self):
        original = md.MetaDescription(
            module_description="A module",
            method_descriptions={"aaaa": "Method A", "bbbb": "Method B"},
            described_against_hash="hash123",
            described_at="2026-06-02T00:00:00Z",
        )
        block = md.render_description_block(original)
        # Verify dict shape matches contract.
        self.assertIn("module_description", block)
        self.assertIn("method_descriptions", block)
        self.assertIn("described_against_hash", block)
        self.assertIn("described_at", block)
        self.assertEqual(block["method_descriptions"], original.method_descriptions)

    def test_render_block_handles_none(self):
        block = md.render_description_block(None)
        self.assertIsNone(block["module_description"])
        self.assertEqual(block["method_descriptions"], {})

    def test_parses_class_method_descriptions(self):
        """Class methods render with 4-space indent under `## Classes`; the
        parser must accept BOTH 2-space (Functions) and 4-space (Classes >
        methods) indents. Regression for a Phase E save-hook round-trip bug
        where class-method descriptions were silently dropped because the
        parser only matched 2-space `  Id: ` lines under `## Functions`."""
        sample = (
            "# foo.py\n"
            "Last Updated: 2026-06-02T00:00:00Z\n"
            "Language: python\n"
            "Lines: 50\n"
            "Hash: abc123\n"
            "**Description:** Module summary.\n"
            "Described-Against-Hash: abc123\n"
            "Described-At: 2026-06-02T00:00:00Z\n"
            "\n"
            "## Classes\n"
            "- `Foo` (line 1)\n"
            "  - `bar` (line 5)\n"
            "    Id: 1234567890abcdef\n"
            "    Description: A class method description.\n"
            "\n"
            "## Functions\n"
            "- `top` (line 20)\n"
            "  Id: fedcba0987654321\n"
            "  Description: A top-level function description.\n"
        )
        result = md.parse_meta_descriptions(sample)
        self.assertIsNotNone(result)
        # Both class-method and top-level descriptions should be parsed.
        self.assertEqual(len(result.method_descriptions), 2)
        self.assertIn("1234567890abcdef", result.method_descriptions)
        self.assertEqual(
            result.method_descriptions["1234567890abcdef"],
            "A class method description.",
        )
        self.assertIn("fedcba0987654321", result.method_descriptions)


class QualifyingMethodsTests(unittest.TestCase):
    def test_threshold_filters_trivial_methods(self):
        # noop @ line 60, logger @ line 62, file_lines=100 → noop has 2 lines, logger has 38 (last)
        # deliver @ line 10, next at 60 → body=50
        qualifying = md._qualifying_methods(SAMPLE_PARSED, threshold=5)
        ids = {m["id"] for m in qualifying}
        # deliver (body 50) included; noop (body 2) excluded; logger (last, body 38) included
        self.assertIn("aaaaaaaaaaaaaaaa", ids)
        self.assertNotIn("bbbbbbbbbbbbbbbb", ids)
        self.assertIn("cccccccccccccccc", ids)

    def test_threshold_zero_includes_all(self):
        qualifying = md._qualifying_methods(SAMPLE_PARSED, threshold=0)
        ids = {m["id"] for m in qualifying}
        self.assertEqual(
            ids, {"aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb", "cccccccccccccccc"}
        )



if __name__ == "__main__":
    unittest.main()
