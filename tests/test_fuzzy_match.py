"""FR-8 / FR-8.1: longest-prefix-first fuzzy family matching."""

import json
import os
import tempfile
import unittest

from tests._harness import *  # noqa: F401,F403
import workflow_summary_lib as L


MINIMAL_PRICING = {
    "fallback_order": ["exact", "minor", "major", "tier"],
    "models": [
        {
            "family": "claude-opus-4-6*",
            "input_per_mtok": 5.0,
            "output_per_mtok": 25.0,
            "cache_write_5m_per_mtok": 6.25,
            "cache_read_per_mtok": 0.5,
        },
        {
            "family": "claude-opus-4-1*",
            "input_per_mtok": 15.0,
            "output_per_mtok": 75.0,
            "cache_write_5m_per_mtok": 18.75,
            "cache_read_per_mtok": 1.5,
        },
        {
            "family": "claude-opus-4*",
            "input_per_mtok": 15.0,
            "output_per_mtok": 75.0,
            "cache_write_5m_per_mtok": 18.75,
            "cache_read_per_mtok": 1.5,
        },
        {
            "family": "claude-sonnet-4*",
            "input_per_mtok": 3.0,
            "output_per_mtok": 15.0,
            "cache_write_5m_per_mtok": 3.75,
            "cache_read_per_mtok": 0.3,
        },
        {
            "family": "claude-haiku-4-5*",
            "input_per_mtok": 1.0,
            "output_per_mtok": 5.0,
            "cache_write_5m_per_mtok": 1.25,
            "cache_read_per_mtok": 0.1,
        },
    ],
}


def _load(pricing_dict):
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(pricing_dict, f)
        path = f.name
    try:
        return L.load_pricing(path)
    finally:
        os.unlink(path)


class FuzzyMatchTests(unittest.TestCase):
    def setUp(self):
        self.pricing = _load(MINIMAL_PRICING)

    def test_opus_46_with_context_suffix(self):
        r = L.match_family("claude-opus-4-6[1m]", self.pricing)
        self.assertIsNotNone(r)
        self.assertEqual(r["input_per_mtok"], 5.0)

    def test_opus_46_with_date_suffix(self):
        r = L.match_family("claude-opus-4-6-20250929", self.pricing)
        self.assertIsNotNone(r)
        self.assertEqual(r["input_per_mtok"], 5.0)

    def test_opus_46_bare(self):
        r = L.match_family("claude-opus-4-6", self.pricing)
        self.assertIsNotNone(r)
        self.assertEqual(r["input_per_mtok"], 5.0)

    def test_opus_41_is_different_tier_from_46(self):
        r46 = L.match_family("claude-opus-4-6", self.pricing)
        r41 = L.match_family("claude-opus-4-1", self.pricing)
        # The whole point of this test: Opus 4.6 and Opus 4.1 must NOT share rates.
        self.assertNotEqual(r46["input_per_mtok"], r41["input_per_mtok"])
        self.assertEqual(r46["input_per_mtok"], 5.0)
        self.assertEqual(r41["input_per_mtok"], 15.0)

    def test_opus_40_falls_back_to_family_wildcard(self):
        # There's no minor-version entry for 4.0 — it should fall back to
        # claude-opus-4* at $15.
        r = L.match_family("claude-opus-4-0", self.pricing)
        self.assertIsNotNone(r)
        self.assertEqual(r["input_per_mtok"], 15.0)

    def test_opus_5_unknown_returns_none(self):
        # Opus 5.x doesn't match claude-opus-4* (prefix differs).
        r = L.match_family("claude-opus-5-0", self.pricing)
        self.assertIsNone(r)

    def test_sonnet_family_wildcard(self):
        r = L.match_family("claude-sonnet-4-6", self.pricing)
        self.assertEqual(r["input_per_mtok"], 3.0)

    def test_empty_model_returns_none(self):
        self.assertIsNone(L.match_family("", self.pricing))
        self.assertIsNone(L.match_family(None, self.pricing))

    def test_no_pricing_returns_none(self):
        self.assertIsNone(L.match_family("claude-opus-4-6", None))

    def test_missing_file_returns_none(self):
        self.assertIsNone(L.load_pricing("/nonexistent/path/pricing.json"))

    def test_malformed_json_returns_none(self):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            f.write("{ not valid json")
            path = f.name
        try:
            self.assertIsNone(L.load_pricing(path))
        finally:
            os.unlink(path)

    def test_negative_rate_entry_is_skipped(self):
        bad = {
            "fallback_order": ["exact"],
            "models": [
                {
                    "family": "claude-opus-4-6*",
                    "input_per_mtok": -1.0,
                    "output_per_mtok": 25.0,
                    "cache_write_5m_per_mtok": 6.25,
                    "cache_read_per_mtok": 0.5,
                },
                {
                    "family": "claude-opus-4-6*",
                    "input_per_mtok": 5.0,
                    "output_per_mtok": 25.0,
                    "cache_write_5m_per_mtok": 6.25,
                    "cache_read_per_mtok": 0.5,
                },
            ],
        }
        pricing = _load(bad)
        r = L.match_family("claude-opus-4-6", pricing)
        self.assertIsNotNone(r)
        self.assertEqual(r["input_per_mtok"], 5.0)


if __name__ == "__main__":
    unittest.main()
