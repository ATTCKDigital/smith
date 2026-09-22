"""usage.py — token rollups and the inverted sidechain guard.

SC-11's arithmetic, FR-34's "unavailable, never $0.00", FR-36's inverted
``isSidechain`` guard, T063's workflow scope, and SC-2's token half.

Two sibling suites cover the rest of the module's surface, split off on the
500-line decompose rule: ``test_pricing.py`` (the pricing TABLE and FR-33's
contract trap) and ``test_sidecars_quota.py`` (FR-27 sidecars, FR-35 quota).

Every failure mode asserted here renders a plausible number rather than an
error — a subagent reporting 0 tokens, a session priced at $0.00, a rollup
that quietly merged two workflows — which is why each gets its own assertion
instead of riding on an end-to-end smoke check.

Reached from CI through the flat tests/smith-activity.test.sh wrapper.
"""

import os
import shutil
import tempfile
import time
import unittest

from tests._harness import *  # noqa: F401,F403 — puts scripts/activity on sys.path

import attribution as A
import phases as P
import usage as U
from tests.activity._fixtures import Fixture

TOKENS_DIR = os.path.join(ACTIVITY_FIXTURES_DIR, "tokens")
PRICING = os.path.join(REPO_ROOT, "hooks", "pricing.json")

PARENT = os.path.join(TOKENS_DIR, "parent-session.jsonl")
AGENT_ID = "a4e8cbb1161fec729"
AGENT_JSONL = os.path.join(TOKENS_DIR, "agent-%s.jsonl" % AGENT_ID)


def clean_state():
    """Every memo in usage.py, cleared.

    These caches are process-global by design — the daemon is one long-lived
    process — so a test that forgot this would inherit another test's byte
    offsets and pass for the wrong reason.
    """
    U.reset_pricing_cache()
    U.reset_session_cache()
    U.reset_subagent_cache()
    U.reset_offsets()


def zero_usage(**kwargs):
    usage = U.new_usage()
    usage.update(kwargs)
    return usage


class SessionRollupTest(unittest.TestCase):
    """SC-11 — exact arithmetic over a known transcript."""

    # Counted rows only; fixtures/tokens/README.md has the per-line table.
    EXPECT = {"input": 10, "output": 2000, "cache_write": 14000, "cache_read": 75000}
    # normalize(): 10*1.0 + 2000*5.0 + 14000*1.25 + 75000*0.1
    NORMALIZED = 35010
    # claude-opus-5*: 5 / 25 / 6.25 / 0.5 per Mtok. Tied to that entry on
    # purpose — a rate edit MUST break this test rather than pass quietly.
    USD = (10 * 5.0 + 2000 * 25.0 + 14000 * 6.25 + 75000 * 0.5) / 1_000_000.0

    def setUp(self):
        clean_state()
        self.table = U.load_pricing(PRICING)

    def test_rollup_matches_exactly(self):
        rollup = U.session_rollup(PARENT, self.table)
        for key, expected in self.EXPECT.items():
            self.assertEqual(rollup[key], expected, key)
        self.assertEqual(rollup["normalized"], self.NORMALIZED)
        self.assertAlmostEqual(rollup["usd"], self.USD, places=9)
        self.assertAlmostEqual(rollup["usd"], 0.17505, places=9)
        self.assertEqual(rollup["scope"], "session")
        self.assertEqual(rollup["model"], "claude-opus-5")
        self.assertEqual(rollup["unknown_models"], [])
        self.assertTrue(rollup["usd_complete"])

    def test_sidechain_and_malformed_rows_are_excluded(self):
        # The fixture's skipped rows carry 999999 sentinels, so a leak is
        # arithmetically obvious rather than a rounding-sized doubt.
        rollup = U.session_rollup(PARENT, self.table)
        self.assertLess(rollup["input"], 1000)
        self.assertLess(rollup["output"], 999999)

    def test_incremental_tail_equals_a_single_full_read(self):
        """The property that makes the ~2 s refresh safe (FR-32)."""
        whole = U.session_rollup(PARENT, self.table)
        clean_state()
        tmp = tempfile.mkdtemp(prefix="smith-usage-")
        try:
            partial = os.path.join(tmp, "live.jsonl")
            with open(PARENT, "rb") as fh:
                data = fh.read()
            cut = data.index(b"\n", data.index(b"\n") + 1) + 1  # after 2 lines
            with open(partial, "wb") as fh:
                fh.write(data[:cut])
            first = U.session_rollup(partial, self.table)
            self.assertGreater(first["output"], 0)
            with open(partial, "ab") as fh:
                fh.write(data[cut:])
            # now=+10 s so the 2 s throttle does not serve the stale answer.
            final = U.session_rollup(partial, self.table, now=time.time() + 10)
            for key in ("input", "output", "cache_write", "cache_read", "normalized"):
                self.assertEqual(final[key], whole[key], key)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_throttle_serves_the_memo_inside_the_window(self):
        base = time.time()
        first = U.session_rollup(PARENT, self.table, now=base)
        second = U.session_rollup(PARENT, self.table, now=base + 0.1)
        self.assertEqual(first["normalized"], second["normalized"])

    def test_torn_final_line_is_not_consumed(self):
        """A half-written row must be re-read whole, never dropped.

        The tail never looks back, so consuming a torn line would lose that
        row permanently — and a live transcript is appended to while this
        reads it, which makes a torn line the normal case, not the exception.
        """
        tmp = tempfile.mkdtemp(prefix="smith-usage-")
        try:
            path = os.path.join(tmp, "live.jsonl")
            row = (
                '{"type":"assistant","isSidechain":false,"message":{"model":'
                '"claude-opus-5","usage":{"input_tokens":50,"output_tokens":7,'
                '"cache_creation_input_tokens":0,"cache_read_input_tokens":0}}}'
            )
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(row[:40])  # torn: no newline, no closing brace
            lines, offset = U.tail_lines(path)
            self.assertEqual(lines, [])
            self.assertEqual(offset, 0)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(row + "\n")
            lines, offset = U.tail_lines(path)
            self.assertEqual(len(lines), 1)
            per_model = U._accumulate_rows(lines, want_sidechain=False)
            self.assertEqual(per_model["claude-opus-5"]["input_tokens"], 50)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_truncated_file_resets_the_offset(self):
        tmp = tempfile.mkdtemp(prefix="smith-usage-")
        try:
            path = os.path.join(tmp, "live.jsonl")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("a\nb\nc\n")
            self.assertEqual(len(U.tail_lines(path)[0]), 3)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("z\n")
            lines, offset = U.tail_lines(path)
            self.assertEqual(lines, ["z"])
            self.assertEqual(offset, 2)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_missing_transcript_is_an_empty_rollup(self):
        rollup = U.session_rollup("/nonexistent/session.jsonl", self.table)
        self.assertEqual(rollup["normalized"], 0)
        self.assertIsNone(rollup["usd"])


class UnpricedModelTest(unittest.TestCase):
    """FR-34 — unavailable, never $0.00."""

    def setUp(self):
        clean_state()
        self.table = U.load_pricing(PRICING)

    def test_unmatched_model_yields_none_usd_but_keeps_tokens(self):
        rollup = U.make_rollup(
            {"claude-notashipped-7": zero_usage(input_tokens=1000, output_tokens=2000)},
            "session",
            self.table,
        )
        self.assertIsNone(rollup["usd"])
        self.assertNotEqual(rollup["usd"], 0.0)
        self.assertEqual(rollup["input"], 1000)
        self.assertEqual(rollup["output"], 2000)
        self.assertEqual(rollup["normalized"], 11000)
        self.assertEqual(rollup["unknown_models"], ["claude-notashipped-7"])
        self.assertFalse(rollup["usd_complete"])

    def test_partial_pricing_is_a_floor_not_a_total(self):
        rollup = U.make_rollup(
            {
                "claude-opus-5": zero_usage(input_tokens=1_000_000),
                "claude-notashipped-7": zero_usage(input_tokens=1_000_000),
            },
            "session",
            self.table,
        )
        self.assertAlmostEqual(rollup["usd"], 5.0)
        self.assertFalse(rollup["usd_complete"])
        self.assertEqual(rollup["unknown_models"], ["claude-notashipped-7"])

    def test_missing_pricing_file_is_not_zero(self):
        """An explicitly-None table must NOT fall back to the global one.

        ``load_pricing()`` returns None for a missing file, so a ``table=None``
        default would swap the degraded answer for the healthy one — the same
        class of silent substitution as the ``_compiled_patterns`` trap.
        """
        rollup = U.make_rollup(
            {"claude-opus-5": zero_usage(input_tokens=10, output_tokens=10)},
            "session",
            U.load_pricing("/nonexistent/pricing.json"),
        )
        self.assertIsNone(rollup["usd"])
        self.assertFalse(rollup["pricing_available"])
        self.assertEqual(rollup["normalized"], 60)

    def test_priced_model_with_zero_usage_is_zero_not_none(self):
        """$0.00 is only ever correct when the rate IS known and usage IS 0."""
        rollup = U.make_rollup({"claude-opus-5": U.new_usage()}, "session", self.table)
        self.assertEqual(rollup["usd"], 0.0)
        self.assertTrue(rollup["usd_complete"])


class SidechainTest(unittest.TestCase):
    """FR-36 — the inverted guard, the ONLY source of live subagent tokens."""

    EXPECT = {"input": 5, "output": 258, "cache_write": 13855, "cache_read": 24155}
    NORMALIZED = 21029  # 5 + 258*5 + 13855*1.25 + 24155*0.1, rounded

    def setUp(self):
        clean_state()
        self.table = U.load_pricing(PRICING)

    def test_subagent_rollup_counts_only_sidechain_rows(self):
        rollup = U.subagent_rollup(AGENT_JSONL, self.table)
        for key, expected in self.EXPECT.items():
            self.assertEqual(rollup[key], expected, key)
        self.assertEqual(rollup["normalized"], self.NORMALIZED)
        self.assertEqual(rollup["scope"], "subagent")
        self.assertIsNotNone(rollup["usd"])

    def test_the_uninverted_guard_finds_none_of_it(self):
        """Why FR-36 could not be deferred.

        The parent-side reader over the SAME file sees only the one
        non-sidechain row (the 888888 sentinel) and none of the real usage —
        which is what a deferred FR-36 would have rendered for every running
        subagent: a number, and the wrong one.
        """
        usage, _model = U.W.parse_parent_jsonl(AGENT_JSONL, None, None)
        self.assertIsNotNone(usage)
        self.assertEqual(usage["output_tokens"], 888888)
        self.assertNotEqual(usage["output_tokens"], self.EXPECT["output"])

    def test_malformed_line_does_not_abort_the_rollup(self):
        # Line 3 of the fixture is torn. The well-formed sidechain rows on
        # either side of it must both still be counted.
        rollup = U.subagent_rollup(AGENT_JSONL, self.table)
        self.assertEqual(rollup["output"], 258)

    def test_missing_file_is_an_empty_rollup_not_an_exception(self):
        rollup = U.subagent_rollup(
            os.path.join(TOKENS_DIR, "agent-nope.jsonl"), self.table
        )
        self.assertEqual(rollup["normalized"], 0)
        self.assertIsNone(rollup["usd"])

    def test_totals_accumulate_across_incremental_reads(self):
        tmp = tempfile.mkdtemp(prefix="smith-usage-")
        try:
            path = os.path.join(tmp, "agent-x.jsonl")
            with open(AGENT_JSONL, "rb") as fh:
                data = fh.read()
            cut = data.index(b"\n", data.index(b"\n") + 1) + 1
            with open(path, "wb") as fh:
                fh.write(data[:cut])
            self.assertEqual(U.subagent_rollup(path, self.table)["output"], 8)
            with open(path, "ab") as fh:
                fh.write(data[cut:])
            # A rising total, not just the newest chunk.
            self.assertEqual(U.subagent_rollup(path, self.table)["output"], 258)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ConcurrentAttributionTest(unittest.TestCase):
    """SC-2's token half — two workflows in one repo never borrow each other's.

    ``attribute_streams`` is called DIRECTLY rather than through
    ``resolver.resolve_project()``: that path filters records through
    ``attribution.evidence_records()``, and ``tool_metrics`` is deliberately
    not an evidence kind, so a rollup routed through the resolver would
    silently see zero metrics records.
    """

    def setUp(self):
        clean_state()
        self.table = U.load_pricing(PRICING)
        self.fx = Fixture("sc2-concurrent")
        self.phase_map = P.load_phase_map()
        self.a = self.fx.marker_by_branch("60-activity-dashboard")
        self.b = self.fx.marker_by_branch("67-deterministic-questions")

    def tearDown(self):
        self.fx.cleanup()

    def _metric(self, cwd, total):
        return {
            "kind": "tool_metrics",
            "clock": "hook",
            "tool": "Bash",
            "total_chars": total,
            "cwd": cwd,
            "session_log": self.fx.session_log,
        }

    def test_metrics_records_land_in_exactly_one_bucket(self):
        records = [
            self._metric(self.a["worktree"], 100),
            self._metric(self.b["worktree"], 250),
            self._metric(os.path.join(self.a["worktree"], "scripts"), 40),
        ]
        result = A.attribute_streams(
            records=records, markers=self.fx.markers, phase_map=self.phase_map
        )
        a_total = sum(r["total_chars"] for r in result["records"][self.a["key"]])
        b_total = sum(r["total_chars"] for r in result["records"][self.b["key"]])
        self.assertEqual(a_total, 140)
        self.assertEqual(b_total, 250)
        self.assertEqual(result["unattributed_events"], 0)
        # Single assignment is structural: the buckets sum to the input exactly.
        self.assertEqual(a_total + b_total, 390)

    def test_an_unplaceable_metric_is_dropped_never_split(self):
        result = A.attribute_streams(
            records=[self._metric(None, 999)],
            markers=self.fx.markers,
            phase_map=self.phase_map,
        )
        self.assertEqual(result["records"][self.a["key"]], [])
        self.assertEqual(result["records"][self.b["key"]], [])
        self.assertEqual(result["unattributed_events"], 1)

    def test_each_workflow_prices_only_its_own_transcript(self):
        transcripts = {}
        for branch, name in (
            ("60-activity-dashboard", "workflow-a.jsonl"),
            ("67-deterministic-questions", "workflow-b.jsonl"),
        ):
            with open(os.path.join(TOKENS_DIR, name), "r", encoding="utf-8") as fh:
                text = fh.read().replace("@FIXTURE@", self.fx.root)
            path = os.path.join(self.fx.root, name)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            transcripts[branch] = path

        roll_a = U.workflow_rollup(
            transcripts=[transcripts["60-activity-dashboard"]], table=self.table
        )
        roll_b = U.workflow_rollup(
            transcripts=[transcripts["67-deterministic-questions"]], table=self.table
        )
        self.assertEqual(roll_a["input"], 100)
        self.assertEqual(roll_a["output"], 200)
        self.assertEqual(roll_a["model"], "claude-opus-5")
        self.assertAlmostEqual(roll_a["usd"], (100 * 5.0 + 200 * 25.0) / 1e6)
        self.assertEqual(roll_b["input"], 1000)
        self.assertEqual(roll_b["output"], 3000)
        self.assertEqual(roll_b["model"], "claude-sonnet-5")
        self.assertAlmostEqual(roll_b["usd"], (1000 * 2.0 + 3000 * 10.0) / 1e6)
        # Different models on purpose: a merged rollup would show up in
        # `model`, not only in the arithmetic.
        self.assertNotEqual(roll_a["model"], roll_b["model"])
        self.assertEqual(roll_a["scope"], "workflow")


class WorkflowScopeTest(unittest.TestCase):
    """T063 — sessions + live subagents + agents that finished before us."""

    HISTORICAL = """\
### [15:10:00] Subagent completed

**Metrics:**
- model: claude-opus-5
- input_tokens: 10
- output_tokens: 20
- cache_creation_input_tokens: 0
- cache_read_input_tokens: 0
- tool_uses: 3
- duration_ms: 1000
- total_tokens: 30

### [15:40:00] Subagent completed

**Metrics:**
- model: claude-opus-5
- input_tokens: 7000
- output_tokens: 9000
- cache_creation_input_tokens: 0
- cache_read_input_tokens: 0
- tool_uses: 3
- duration_ms: 1000
- total_tokens: 16000
"""

    def setUp(self):
        clean_state()
        self.table = U.load_pricing(PRICING)

    def test_historical_blocks_are_cut_at_the_daemon_start_offset(self):
        """Only agents that finished BEFORE the daemon started are counted.

        The live tail owns everything after that offset, so counting a block
        from after it would double-count the same agent.
        """
        cut = self.HISTORICAL.index("### [15:40:00]")
        before = U.historical_subagent_usage(self.HISTORICAL, cut)
        self.assertEqual(before["claude-opus-5"]["input_tokens"], 10)
        self.assertEqual(before["claude-opus-5"]["output_tokens"], 20)
        everything = U.historical_subagent_usage(self.HISTORICAL, None)
        self.assertEqual(everything["claude-opus-5"]["input_tokens"], 7010)

    def test_workflow_scope_sums_all_three_sources(self):
        rollup = U.workflow_rollup(
            transcripts=[PARENT],
            subagent_jsonls=[AGENT_JSONL],
            session_log_text=self.HISTORICAL,
            table=self.table,
        )
        # 10 (session) + 5 (subagent) + 7010 (historical)
        self.assertEqual(rollup["input"], 7025)
        # 2000 + 258 + 9020
        self.assertEqual(rollup["output"], 11278)
        self.assertEqual(rollup["scope"], "workflow")
        self.assertTrue(rollup["usd_complete"])
        self.assertIsNotNone(rollup["usd"])

    def test_empty_workflow_is_zero_tokens_and_no_usd(self):
        rollup = U.workflow_rollup(table=self.table)
        self.assertEqual(rollup["normalized"], 0)
        self.assertIsNone(rollup["usd"])
        self.assertIsNone(rollup["model"])

    def test_merge_keeps_usd_none_only_when_no_part_was_priced(self):
        priced = U.make_rollup(
            {"claude-opus-5": zero_usage(input_tokens=1_000_000)}, "session", self.table
        )
        unpriced = U.make_rollup(
            {"claude-notashipped-7": zero_usage(input_tokens=5)}, "subagent", self.table
        )
        merged = U.merge_rollups([priced, unpriced], "workflow")
        self.assertAlmostEqual(merged["usd"], 5.0)
        self.assertFalse(merged["usd_complete"])
        self.assertEqual(merged["unknown_models"], ["claude-notashipped-7"])
        self.assertIsNone(U.merge_rollups([unpriced], "workflow")["usd"])


if __name__ == "__main__":
    unittest.main()
