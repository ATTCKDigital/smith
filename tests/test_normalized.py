"""FR-6: normalized-token fixed-weight formula."""

import unittest

from tests._harness import *  # noqa: F401,F403 — puts hooks/ on sys.path
import workflow_summary_lib as L


class NormalizeTests(unittest.TestCase):
    def test_none_usage_returns_zero(self):
        self.assertEqual(L.normalize(None), 0)

    def test_empty_dict_returns_zero(self):
        self.assertEqual(L.normalize({}), 0)

    def test_all_zero_usage_returns_zero(self):
        self.assertEqual(
            L.normalize(
                {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                }
            ),
            0,
        )

    def test_input_only(self):
        # 1000 input × 1.0 = 1000
        self.assertEqual(L.normalize({"input_tokens": 1000}), 1000)

    def test_output_only(self):
        # 1000 output × 5.0 = 5000
        self.assertEqual(L.normalize({"output_tokens": 1000}), 5000)

    def test_cache_create_only(self):
        # 1000 cache_create × 1.25 = 1250
        self.assertEqual(L.normalize({"cache_creation_input_tokens": 1000}), 1250)

    def test_cache_read_only(self):
        # 1000 cache_read × 0.1 = 100
        self.assertEqual(L.normalize({"cache_read_input_tokens": 1000}), 100)

    def test_realistic_claude_code_shape(self):
        # Mostly cache-read-heavy, characteristic of Claude Code long agents.
        usage = {
            "input_tokens": 180,
            "output_tokens": 9_214,
            "cache_creation_input_tokens": 41_203,
            "cache_read_input_tokens": 368_891,
        }
        # 180 + 46070 + 51503.75 + 36889.1 = 134642.85 → 134643
        self.assertEqual(L.normalize(usage), 134_643)

    def test_missing_field_treated_as_zero(self):
        # Only input present — other three treated as 0.
        self.assertEqual(L.normalize({"input_tokens": 500}), 500)

    def test_large_integers(self):
        # No overflow concern in Python int; ensure formula scales.
        usage = {
            "input_tokens": 10_000_000,
            "output_tokens": 10_000_000,
            "cache_creation_input_tokens": 10_000_000,
            "cache_read_input_tokens": 10_000_000,
        }
        # 10M × (1 + 5 + 1.25 + 0.1) = 73.5M
        self.assertEqual(L.normalize(usage), 73_500_000)


if __name__ == "__main__":
    unittest.main()
