"""FR-12: active duration via gap detection with Bash-tool cap."""

import unittest

from tests._harness import *  # noqa: F401,F403
import workflow_summary_lib as L


class ActiveDurationTests(unittest.TestCase):
    def test_empty_returns_zero(self):
        self.assertEqual(L.compute_active_duration([]), 0)

    def test_single_entry_returns_zero(self):
        self.assertEqual(L.compute_active_duration([("12:00:00", "Bash")]), 0)

    def test_no_gaps_above_threshold_returns_full_elapsed(self):
        # Three 10-second gaps, all under the 120s idle threshold.
        entries = [
            ("12:00:00", "Read"),
            ("12:00:10", "Read"),
            ("12:00:20", "Read"),
            ("12:00:30", "Read"),
        ]
        self.assertEqual(L.compute_active_duration(entries), 30)

    def test_single_large_non_bash_gap_excluded(self):
        # 10s + 300s idle + 10s. 300 > 120 threshold so it's excluded.
        entries = [
            ("12:00:00", "Read"),
            ("12:00:10", "Read"),
            ("12:05:10", "Read"),  # 300s gap — idle
            ("12:05:20", "Read"),
        ]
        # Included deltas: 10 + 10 = 20s
        self.assertEqual(L.compute_active_duration(entries), 20)

    def test_bash_gap_within_cap_is_included(self):
        # 500s Bash gap is under the 600s cap — include the full 500s.
        entries = [
            ("12:00:00", "Read"),
            ("12:08:20", "Bash"),  # 500s gap, tool is Bash
        ]
        self.assertEqual(L.compute_active_duration(entries), 500)

    def test_bash_gap_above_cap_counts_cap_only(self):
        # 800s Bash gap. Cap is 600s. We count 600s (execution) and drop
        # 200s (treated as idle beyond execution).
        entries = [
            ("12:00:00", "Read"),
            ("12:13:20", "Bash"),  # 800s gap
        ]
        self.assertEqual(L.compute_active_duration(entries), 600)

    def test_non_bash_gap_above_threshold_excluded_entirely(self):
        # 300s gap with a Read tool — exceeds 120s threshold — excluded (zero
        # contribution from this gap; we do NOT clamp to 120s for non-Bash).
        entries = [
            ("12:00:00", "Read"),
            ("12:05:00", "Read"),  # 300s gap
        ]
        self.assertEqual(L.compute_active_duration(entries), 0)

    def test_mixed_sequence(self):
        # 10s Read + 500s Bash (within cap) + 200s Grep (over threshold, excluded)
        # + 30s Edit = 10 + 500 + 0 + 30 = 540s
        entries = [
            ("12:00:00", "Read"),
            ("12:00:10", "Read"),
            ("12:08:30", "Bash"),  # 500s, Bash, within cap
            ("12:11:50", "Grep"),  # 200s, Grep, excluded
            ("12:12:20", "Edit"),  # 30s, Edit, included
        ]
        self.assertEqual(L.compute_active_duration(entries), 540)

    def test_crosses_midnight(self):
        # Wrap from 23:59:55 to 00:00:10 = 15s gap.
        entries = [
            ("23:59:55", "Read"),
            ("00:00:10", "Read"),
        ]
        self.assertEqual(L.compute_active_duration(entries), 15)

    def test_custom_thresholds(self):
        entries = [
            ("12:00:00", "Read"),
            ("12:01:00", "Read"),  # 60s
        ]
        # Default idle=120 includes it.
        self.assertEqual(L.compute_active_duration(entries), 60)
        # Idle=30 excludes it.
        self.assertEqual(L.compute_active_duration(entries, idle=30), 0)


if __name__ == "__main__":
    unittest.main()
