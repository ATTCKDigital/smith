"""FR-10: per-family USD cost formula."""

import unittest

from tests._harness import *  # noqa: F401,F403
import workflow_summary_lib as L


OPUS_46_RATES = {
    "input_per_mtok": 5.0,
    "output_per_mtok": 25.0,
    "cache_write_5m_per_mtok": 6.25,
    "cache_read_per_mtok": 0.5,
}

OPUS_4_RATES = {
    "input_per_mtok": 15.0,
    "output_per_mtok": 75.0,
    "cache_write_5m_per_mtok": 18.75,
    "cache_read_per_mtok": 1.5,
}

SONNET_RATES = {
    "input_per_mtok": 3.0,
    "output_per_mtok": 15.0,
    "cache_write_5m_per_mtok": 3.75,
    "cache_read_per_mtok": 0.3,
}


class CostTests(unittest.TestCase):
    def test_none_usage_returns_none(self):
        self.assertIsNone(L.cost_usd(None, OPUS_46_RATES))

    def test_none_rates_returns_none(self):
        self.assertIsNone(L.cost_usd({"input_tokens": 100}, None))

    def test_zero_usage_zero_cost(self):
        usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
        self.assertEqual(L.cost_usd(usage, OPUS_46_RATES), 0.0)

    def test_opus_46_hand_computed(self):
        # 1_000_000 of each:
        # input 1M × $5 = $5
        # output 1M × $25 = $25
        # cache_write 1M × $6.25 = $6.25
        # cache_read 1M × $0.50 = $0.50
        # total = $36.75
        usage = {
            "input_tokens": 1_000_000,
            "output_tokens": 1_000_000,
            "cache_creation_input_tokens": 1_000_000,
            "cache_read_input_tokens": 1_000_000,
        }
        self.assertAlmostEqual(L.cost_usd(usage, OPUS_46_RATES), 36.75, places=4)

    def test_opus_4_is_3x_opus_46(self):
        # Opus 4.0/4.1 rates are exactly 3× Opus 4.5/4.6 rates across the board.
        usage = {
            "input_tokens": 1_000_000,
            "output_tokens": 1_000_000,
            "cache_creation_input_tokens": 1_000_000,
            "cache_read_input_tokens": 1_000_000,
        }
        c_46 = L.cost_usd(usage, OPUS_46_RATES)
        c_4 = L.cost_usd(usage, OPUS_4_RATES)
        self.assertAlmostEqual(c_4 / c_46, 3.0, places=6)

    def test_sonnet_hand_computed(self):
        usage = {
            "input_tokens": 1_000_000,
            "output_tokens": 1_000_000,
            "cache_creation_input_tokens": 1_000_000,
            "cache_read_input_tokens": 1_000_000,
        }
        # 3 + 15 + 3.75 + 0.30 = 22.05
        self.assertAlmostEqual(L.cost_usd(usage, SONNET_RATES), 22.05, places=4)

    def test_fractional_tokens_sub_cent(self):
        # 100 input × $5/MTok = $0.0005. Small fractional value, should not round up.
        usage = {"input_tokens": 100}
        result = L.cost_usd(usage, OPUS_46_RATES)
        self.assertAlmostEqual(result, 0.0005, places=6)


if __name__ == "__main__":
    unittest.main()
