"""FR-5 / FR-17: subagent-block parsing — v2 and v1 legacy fallback."""

import unittest

from tests._harness import *  # noqa: F401,F403
import workflow_summary_lib as L


V2_BLOCK = """\
### [12:17:05] Subagent completed

**Metrics:**
- model: claude-sonnet-4-6
- input_tokens: 1823
- output_tokens: 9214
- cache_creation_input_tokens: 41203
- cache_read_input_tokens: 368891
- tool_uses: 36
- duration_ms: 104202
- total_tokens: 421131
"""

V1_BLOCK = """\
### [12:17:12] Subagent completed

**Metrics:**
- total_tokens: 421131
- tool_uses: 14
- duration_ms: 102981
"""


class LegacyParseTests(unittest.TestCase):
    def test_v2_block_fully_parsed(self):
        rows = L.parse_subagent_blocks(V2_BLOCK)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["model"], "claude-sonnet-4-6")
        self.assertEqual(r["usage"]["input_tokens"], 1823)
        self.assertEqual(r["usage"]["output_tokens"], 9214)
        self.assertEqual(r["usage"]["cache_creation_input_tokens"], 41203)
        self.assertEqual(r["usage"]["cache_read_input_tokens"], 368891)
        self.assertEqual(r["tool_uses"], 36)
        self.assertEqual(r["duration_ms"], 104202)
        self.assertEqual(r["raw_total"], 421131)
        self.assertEqual(r["index"], 1)

    def test_v1_block_legacy_fallback(self):
        rows = L.parse_subagent_blocks(V1_BLOCK)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["model"], "unknown")
        self.assertIsNone(r["usage"])
        self.assertEqual(r["tool_uses"], 14)
        self.assertEqual(r["duration_ms"], 102981)
        self.assertEqual(r["raw_total"], 421131)
        self.assertEqual(r["index"], 1)

    def test_mixed_v2_and_v1_in_one_log(self):
        content = V2_BLOCK + "\n" + V1_BLOCK
        rows = L.parse_subagent_blocks(content)
        self.assertEqual(len(rows), 2)
        # The v2 block appeared first in the log.
        self.assertEqual(rows[0]["model"], "claude-sonnet-4-6")
        self.assertIsNotNone(rows[0]["usage"])
        self.assertEqual(rows[0]["index"], 1)
        # The v1 block second.
        self.assertEqual(rows[1]["model"], "unknown")
        self.assertIsNone(rows[1]["usage"])
        self.assertEqual(rows[1]["index"], 2)

    def test_no_blocks_returns_empty_list(self):
        self.assertEqual(L.parse_subagent_blocks(""), [])
        self.assertEqual(L.parse_subagent_blocks("some unrelated content"), [])

    def test_v2_tail_not_double_counted_as_v1(self):
        # The v2 block's last three lines (total_tokens / tool_uses / duration_ms)
        # look identical to a v1 block's fields. Ensure the parser doesn't match
        # them a second time. This is the critical de-dup case.
        rows = L.parse_subagent_blocks(V2_BLOCK)
        self.assertEqual(len(rows), 1)

    def test_assembly_for_v1_sets_none_components(self):
        # Ensure normalized / est_cost_usd come out None for v1 blocks.
        rows = L.parse_subagent_blocks(V1_BLOCK)
        totals = L.assemble_totals(
            parent_usage=None,
            parent_model=None,
            parent_tool_calls=0,
            parent_active_duration_s=0,
            subagent_rows=rows,
            pricing=None,
            total_elapsed_s=0,
        )
        r = totals["subagent_rows"][0]
        self.assertIsNone(r["normalized"])
        self.assertIsNone(r["est_cost_usd"])
        # Raw total is still captured (useful for the per-subagent row).
        self.assertEqual(r["raw_total"], 421131)
        # Combined raw fold-in for v1: raw_total contributes via the v1 path.
        self.assertEqual(totals["combined_raw_total"], 421131)


class InvocationParseTests(unittest.TestCase):
    def test_find_invocation(self):
        content = "### [06:35:00] /smith-new invocation\n\nblah"
        inv = L.find_invocation(content)
        self.assertEqual(inv, ("06:35:00", "new"))

    def test_find_invocation_bugfix(self):
        content = "### [06:35:00] /smith-bugfix invoked\n"
        inv = L.find_invocation(content)
        self.assertEqual(inv, ("06:35:00", "bugfix"))

    def test_find_invocation_none(self):
        self.assertIsNone(L.find_invocation("no invocation here"))

    def test_malformed_timestamp_not_matched(self):
        # The literal `$(date +%H:%M:%S)` bug from smith-new's vault log —
        # regex should NOT match this. See debug-2026-04-14-smith-new-missing-totals.md.
        content = "### [$(date +%H:%M:%S)] /smith-new invocation"
        self.assertIsNone(L.find_invocation(content))


if __name__ == "__main__":
    unittest.main()
