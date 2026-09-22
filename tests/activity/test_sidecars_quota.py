"""Subagent sidecars (FR-27 / T066) and quota windows (FR-35 / T067).

Split from ``test_usage.py`` on the 500-line decompose rule; both suites cover
``usage.py``'s re-exported surface (``scripts/activity/subagents.py`` and
``scripts/activity/quota.py``) and are asserted through ``usage`` so the
re-export itself stays covered.

Both modules exist to make an ABSENCE legible rather than convenient:
an agent with no readable start time is ``None``, not "just started"; a
payload with no ``rate_limits`` is ``available: false``, not 0%.

Reached from CI through the flat tests/smith-activity.test.sh wrapper.
"""

import os
import shutil
import tempfile
import unittest

from tests._harness import *  # noqa: F401,F403 — puts scripts/activity on sys.path

import paths
import usage as U

TOKENS_DIR = os.path.join(ACTIVITY_FIXTURES_DIR, "tokens")
AGENT_ID = "a4e8cbb1161fec729"
AGENT_JSONL = os.path.join(TOKENS_DIR, "agent-%s.jsonl" % AGENT_ID)
AGENT_META = os.path.join(TOKENS_DIR, "agent-%s.meta.json" % AGENT_ID)


class SidecarTest(unittest.TestCase):
    """FR-27 — sidecar discovery is PRIMARY; SubagentStart is only latency.

    The sidecar is written at dispatch and carries every field FR-27 needs, so
    if the event were withdrawn tomorrow the panel would lose up to one poll
    of responsiveness and nothing else.
    """

    def test_reads_every_field_fr27_requires(self):
        record = U.read_sidecar(AGENT_META)
        self.assertEqual(record["agent_type"], "Explore")
        self.assertEqual(record["description"], "Investigate markers and workflows")
        self.assertEqual(record["parent_agent_id"], "a15f48d273d84cb99")
        self.assertEqual(record["spawn_depth"], 2)
        # toolUseId is what ties this sidecar to the PreToolUse Task dispatch
        # that created it; positional pairing is wrong with two agents in flight.
        self.assertEqual(record["tool_use_id"], "toolu_01XcnzT6yNkhxPNPE6E5EqFk")
        self.assertEqual(record["agent_id"], AGENT_ID)
        self.assertIsNotNone(record["started"])

    def test_elapsed_is_none_not_zero_when_start_is_unknown(self):
        self.assertIsNone(U.elapsed_s({"started": None}))
        self.assertIsNone(U.elapsed_s({}))
        self.assertAlmostEqual(U.elapsed_s({"started": 100.0}, now=142.5), 42.5)

    def test_unreadable_sidecar_returns_none(self):
        self.assertIsNone(
            U.read_sidecar(os.path.join(TOKENS_DIR, "agent-nope.meta.json"))
        )

    def test_malformed_sidecar_returns_none(self):
        tmp = tempfile.mkdtemp(prefix="smith-sidecar-")
        try:
            path = os.path.join(tmp, "agent-x.meta.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write('{"agentType": "Explore",')  # torn at dispatch time
            self.assertIsNone(U.read_sidecar(path))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_list_sidecars_pairs_each_with_its_transcript(self):
        tmp = tempfile.mkdtemp(prefix="smith-sidecar-")
        try:
            session = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            directory = paths.subagents_dir(tmp, session)
            os.makedirs(directory)
            shutil.copy(
                AGENT_META, os.path.join(directory, "agent-%s.meta.json" % AGENT_ID)
            )
            shutil.copy(
                AGENT_JSONL, os.path.join(directory, "agent-%s.jsonl" % AGENT_ID)
            )
            with open(os.path.join(directory, "agent-torn.meta.json"), "w") as fh:
                fh.write("{not json")
            records = U.list_sidecars(tmp, session)
            self.assertEqual(len(records), 1, "the torn sidecar must be skipped")
            self.assertEqual(records[0]["agent_id"], AGENT_ID)
            self.assertTrue(os.path.isfile(records[0]["jsonl_path"]))
            # The transcript may not exist yet — a sidecar lands at dispatch,
            # the transcript only once the agent produces a turn.
            self.assertTrue(records[0]["jsonl_path"].endswith(".jsonl"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_missing_subagents_dir_is_an_empty_list(self):
        self.assertEqual(U.list_sidecars("/nonexistent/repo", "no-session"), [])


class QuotaTest(unittest.TestCase):
    """FR-35 / SC-12 — absence is a state, not a zero."""

    PAYLOAD = {
        "rate_limits": {
            "five_hour": {"used_percentage": 23.5, "resets_at": 1738425600},
            "seven_day": {"used_percentage": 41.2, "resets_at": 1738857600},
            "spend_limit": {"used_percentage": 62.8, "resets_at": 1740787200},
        }
    }

    def test_all_three_windows_parse(self):
        quota = U.quota_windows(self.PAYLOAD, received_at="2026-09-22T16:00:00Z")
        self.assertTrue(quota["available"])
        self.assertEqual(quota["five_hour"]["used_percentage"], 23.5)
        # Epoch SECONDS, not ISO-8601 — an int, and the UI formats it.
        self.assertEqual(quota["seven_day"]["resets_at"], 1738857600)
        self.assertIsInstance(quota["spend_limit"]["resets_at"], int)
        self.assertEqual(quota["received_at"], "2026-09-22T16:00:00Z")

    def test_absent_rate_limits_is_unavailable_not_zero(self):
        for payload in ({}, {"model": {"id": "claude-opus-5"}}, None, "nonsense", []):
            quota = U.quota_windows(payload)
            self.assertFalse(quota["available"], repr(payload))
            for window in U.QUOTA_WINDOWS:
                self.assertIsNone(quota[window], repr(payload))

    def test_window_missing_resets_at_still_renders_its_percentage(self):
        quota = U.quota_windows({"rate_limits": {"five_hour": {"used_percentage": 9}}})
        self.assertTrue(quota["available"])
        self.assertEqual(quota["five_hour"]["used_percentage"], 9.0)
        self.assertIsNone(quota["five_hour"]["resets_at"])

    def test_window_missing_used_percentage_is_dropped(self):
        quota = U.quota_windows({"rate_limits": {"five_hour": {"resets_at": 1}}})
        self.assertIsNone(quota["five_hour"])
        self.assertFalse(quota["available"])

    def test_one_present_window_does_not_invent_the_others(self):
        quota = U.quota_windows(
            {"rate_limits": {"seven_day": {"used_percentage": 41.2, "resets_at": 1}}}
        )
        self.assertTrue(quota["available"])
        self.assertIsNone(quota["five_hour"])
        self.assertIsNone(quota["spend_limit"])


if __name__ == "__main__":
    unittest.main()
