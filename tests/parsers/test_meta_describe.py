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


def make_mock_client(plan: dict):
    """Build a HaikuClient stub. `plan` maps a prompt-substring → response."""
    calls: list[tuple[list[dict], str, str]] = []

    def stub(messages, system_prompt, model):
        calls.append((messages, system_prompt, model))
        user_msg = messages[0]["content"] if messages else ""
        for needle, response in plan.items():
            if needle in user_msg or needle in system_prompt:
                return response
        return ""

    stub.calls = calls  # type: ignore[attr-defined]
    return stub


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


class DescribeFileTests(unittest.TestCase):
    def test_bulk_describe_with_mock(self):
        plan = {
            # System prompt content triggers module vs method routing.
            "concise one-line summaries": "Handles webhook delivery.",
            "JSON object": (
                '{"aaaaaaaaaaaaaaaa": "Delivers a webhook payload.",'
                '"cccccccccccccccc": "Logger helper."}'
            ),
        }
        client = make_mock_client(plan)
        desc = md.describe_file(
            rel_path="backend/src/services/webhook.py",
            source=SAMPLE_SOURCE,
            parsed=SAMPLE_PARSED,
            threshold=5,
            client=client,
        )
        self.assertEqual(desc.module_description, "Handles webhook delivery.")
        self.assertIn("aaaaaaaaaaaaaaaa", desc.method_descriptions)
        # noop excluded by threshold; logger included.
        self.assertNotIn("bbbbbbbbbbbbbbbb", desc.method_descriptions)
        self.assertIn("cccccccccccccccc", desc.method_descriptions)
        # Provenance fields populated.
        self.assertIsNotNone(desc.described_against_hash)
        self.assertEqual(len(desc.described_against_hash), 64)  # SHA-256 hex
        self.assertTrue(desc.described_at.endswith("Z"))


class UpdateTouchedTests(unittest.TestCase):
    def test_only_touched_ids_regenerate(self):
        existing = md.MetaDescription(
            module_description="OLD module description",
            method_descriptions={
                "aaaaaaaaaaaaaaaa": "OLD deliver description",
                "cccccccccccccccc": "OLD logger description",
            },
            described_against_hash="oldhash",
            described_at="2026-05-01T00:00:00Z",
        )
        # Only touch aaaa.
        plan = {
            "JSON object": '{"aaaaaaaaaaaaaaaa": "NEW deliver description"}',
        }
        client = make_mock_client(plan)
        desc = md.update_touched(
            rel_path="backend/src/services/webhook.py",
            source=SAMPLE_SOURCE,
            parsed=SAMPLE_PARSED,
            existing=existing,
            touched_method_ids={"aaaaaaaaaaaaaaaa"},
            purpose_shifted=False,
            threshold=5,
            client=client,
        )
        # Touched id has new description.
        self.assertEqual(
            desc.method_descriptions["aaaaaaaaaaaaaaaa"], "NEW deliver description"
        )
        # Untouched id passthrough.
        self.assertEqual(
            desc.method_descriptions["cccccccccccccccc"], "OLD logger description"
        )
        # Module description preserved (purpose_shifted=False).
        self.assertEqual(desc.module_description, "OLD module description")
        # Provenance fields refreshed.
        self.assertNotEqual(desc.described_against_hash, "oldhash")

    def test_purpose_shifted_regenerates_module(self):
        existing = md.MetaDescription(
            module_description="OLD module description",
            method_descriptions={},
            described_against_hash="oldhash",
            described_at="2026-05-01T00:00:00Z",
        )
        plan = {
            "concise one-line summaries": "NEW module description",
            "JSON object": "{}",
        }
        client = make_mock_client(plan)
        desc = md.update_touched(
            rel_path="backend/src/services/webhook.py",
            source=SAMPLE_SOURCE,
            parsed=SAMPLE_PARSED,
            existing=existing,
            touched_method_ids=set(),
            purpose_shifted=True,
            threshold=5,
            client=client,
        )
        self.assertEqual(desc.module_description, "NEW module description")

    def test_dropped_method_ids_pruned(self):
        """An id in `existing` that no longer appears in parsed output is removed."""
        existing = md.MetaDescription(
            module_description="Module",
            method_descriptions={
                "aaaaaaaaaaaaaaaa": "Live method",
                "ddddddddddddddddd"[:16]: "Removed method id",
                "deadbeefdeadbeef": "Another dead id",
            },
            described_against_hash="oldhash",
            described_at="2026-05-01T00:00:00Z",
        )
        plan = {"JSON object": "{}"}
        client = make_mock_client(plan)
        desc = md.update_touched(
            rel_path="backend/src/services/webhook.py",
            source=SAMPLE_SOURCE,
            parsed=SAMPLE_PARSED,
            existing=existing,
            touched_method_ids=set(),
            purpose_shifted=False,
            threshold=5,
            client=client,
        )
        # aaaa is in parsed (live), so kept.
        self.assertIn("aaaaaaaaaaaaaaaa", desc.method_descriptions)
        # dead ids dropped.
        self.assertNotIn("deadbeefdeadbeef", desc.method_descriptions)


class TruncateTests(unittest.TestCase):
    def test_truncates_at_soft_cap_on_sentence_break(self):
        long = "This is a sentence. " * 20
        out = md._truncate(long, 50, 100)
        self.assertLessEqual(len(out), 100)
        self.assertTrue("This is a sentence" in out)

    def test_preserves_single_line(self):
        s = "Already short text."
        self.assertEqual(md._truncate(s, 50, 100), s)


class HaikuErrorTests(unittest.TestCase):
    def test_haiku_error_skips_method_but_continues(self):
        def failing_client(messages, system_prompt, model):
            raise md.HaikuUnavailable("Simulated network error")

        # Run shouldn't raise; descriptions just empty.
        desc = md.describe_file(
            rel_path="backend/src/services/webhook.py",
            source=SAMPLE_SOURCE,
            parsed=SAMPLE_PARSED,
            threshold=5,
            client=failing_client,
        )
        self.assertIsNone(desc.module_description)
        self.assertEqual(desc.method_descriptions, {})
        # Provenance still set.
        self.assertIsNotNone(desc.described_against_hash)


if __name__ == "__main__":
    unittest.main()
