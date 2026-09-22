"""sessionlog.py — the four block formats, the two line formats, and the
three-tier discovery precedence (data-model.md §4.2, FR-58).

The fixture text below is copied from this repository's own session log rather
than invented, including the 4-hour clock skew between the hook-written
``- `[15:18:22]` **Bash** ...`` line and the model-written
``### [11:18:56] /smith-new invocation`` block that immediately follows it. A
synthetic fixture would not have that property, and it is the property that
makes offset-keyed ordering mandatory.

Reached from CI through the flat tests/smith-activity.test.sh wrapper.
"""

import os
import shutil
import tempfile
import unittest

from tests._harness import *  # noqa: F401,F403 — puts scripts/activity on sys.path

import sessionlog as S

# Append order, not clock order. Note `## Metrics` sits in the MIDDLE: it is
# created once and appended to forever, so `###` blocks follow it.
LOG = """\
# Session Log

## Started: 2026-09-22 14:50:28

### [14:55:01] User prompt

> do the thing

## Metrics

- `[14:55:09]` **Bash** in:201 out:2264 total:2465 (echo "=== does smith-new reference other /smith- skills? ===…)
- `[14:55:12]` **Edit** `skills/smith-new/SKILL.md`

### [15:07:45] Subagent completed

**Metrics:**
- model: claude-haiku-4-5-20251001
- input_tokens: 350
- output_tokens: 8354
- cache_creation_input_tokens: 237490
- cache_read_input_tokens: 1552586
- tool_uses: 29
- duration_ms: 104704
- total_tokens: 1798780

### [15:18:00] workflow-start 60-activity-dashboard

**Workflow:** smith-new
**Feature:** activity-dashboard
**Worktree:** /tmp/smith-activity-dashboard
**Marker:** /repo/.smith/vault/active-workflows/60-activity-dashboard.yaml

- `[15:18:22]` **Bash** in:408 out:1359 total:1767 (echo "=== active-workflow markers now ===")

### [11:18:56] /smith-new invocation

**User Request:**
> build the dashboard

**Synthesized Input:** New skill `/smith-activity`
**Outcome:** Phase 1 complete
**Artifacts:** .smith/vault/active-workflows/60-activity-dashboard.yaml

### [11:24:08] Subagent invoked: Phase 3 Spec Generation — smith-activity audit dashboard

**Type:** general-purpose
**Model:** inherited
"""


class BlockFormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = S.parse_session_log(LOG)
        cls.by_kind = {}
        for record in cls.records:
            cls.by_kind.setdefault(record["kind"], []).append(record)

    def test_all_four_block_formats_and_both_line_formats_are_recognised(self):
        self.assertEqual(
            sorted(self.by_kind),
            [
                "file_change",
                "section",
                "skill_event",
                "subagent_completed",
                "subagent_invoked",
                "tool_metrics",
                "user_prompt",
                "workflow_start",
            ],
        )

    def test_subagent_invoked_carries_description_type_and_model(self):
        record = self.by_kind["subagent_invoked"][0]
        self.assertEqual(
            record["description"],
            "Phase 3 Spec Generation — smith-activity audit dashboard",
        )
        self.assertEqual(record["attrs"]["Type"], "general-purpose")
        self.assertEqual(record["attrs"]["Model"], "inherited")

    def test_skill_event_carries_outcome_and_artifacts(self):
        record = self.by_kind["skill_event"][0]
        self.assertEqual(record["skill"], "smith-new")
        self.assertEqual(record["event"], "invocation")
        self.assertEqual(record["attrs"]["Outcome"], "Phase 1 complete")
        self.assertIn("60-activity-dashboard.yaml", record["attrs"]["Artifacts"])

    def test_subagent_completed_carries_the_metrics_list(self):
        record = self.by_kind["subagent_completed"][0]
        self.assertEqual(record["metrics"]["model"], "claude-haiku-4-5-20251001")
        self.assertEqual(record["metrics"]["input_tokens"], 350)
        self.assertEqual(record["metrics"]["cache_read_input_tokens"], 1552586)
        self.assertEqual(record["metrics"]["total_tokens"], 1798780)
        # The heading is the bare literal: no description, no type to pair on.
        self.assertNotIn("description", record)

    def test_workflow_start_carries_branch_and_marker(self):
        record = self.by_kind["workflow_start"][0]
        self.assertEqual(record["branch"], "60-activity-dashboard")
        self.assertEqual(record["attrs"]["Workflow"], "smith-new")
        self.assertEqual(record["attrs"]["Worktree"], "/tmp/smith-activity-dashboard")

    def test_metrics_tracker_line_format(self):
        record = self.by_kind["tool_metrics"][0]
        self.assertEqual(record["tool"], "Bash")
        self.assertEqual(
            (record["input_chars"], record["output_chars"], record["total_chars"]),
            (201, 2264, 2465),
        )
        # Bare parens, truncated at ~60 chars with U+2026.
        self.assertTrue(record["identifier"].startswith("echo "))
        self.assertTrue(record["identifier"].endswith("…"))

    def test_file_change_logger_line_format_is_not_confused_with_metrics(self):
        record = self.by_kind["file_change"][0]
        self.assertEqual(record["tool"], "Edit")
        # Only file-change-logger.sh backticks the path.
        self.assertEqual(record["path"], "skills/smith-new/SKILL.md")
        self.assertEqual(len(self.by_kind["file_change"]), 1)
        self.assertEqual(len(self.by_kind["tool_metrics"]), 2)


class OrderingTests(unittest.TestCase):
    """FR-58 — offset is the ordering key, never the parsed timestamp."""

    @classmethod
    def setUpClass(cls):
        cls.records = S.parse_session_log(LOG)

    def test_every_record_carries_an_append_offset(self):
        offsets = [r["offset"] for r in self.records]
        self.assertTrue(all(isinstance(o, int) for o in offsets))
        self.assertEqual(offsets, sorted(offsets))
        self.assertEqual(len(set(offsets)), len(offsets))

    def test_offsets_point_at_the_right_bytes(self):
        raw = LOG.encode("utf-8")
        for record in self.records:
            tail = raw[record["offset"] :]
            self.assertTrue(
                tail.startswith(b"#") or tail.startswith(b"- "),
                "offset %d does not start a record" % record["offset"],
            )

    def test_the_real_clock_skew_is_present_and_offsets_still_increase(self):
        # The hook line at 15:18:22 is IMMEDIATELY followed, in append order,
        # by a model-authored block stamped 11:18:56. Sorting on the parsed
        # timestamp would reorder them; sorting on offset does not.
        stamps = [
            (r["offset"], r["timestamp_text"], r["clock"])
            for r in self.records
            if r["timestamp_text"]
        ]
        skews = [(a, b) for a, b in zip(stamps, stamps[1:]) if a[1] > b[1]]
        self.assertTrue(skews, "fixture lost its mixed-clock property")
        offset_before, _, clock_before = skews[0][0]
        offset_after, _, clock_after = skews[0][1]
        self.assertLess(offset_before, offset_after)
        self.assertEqual((clock_before, clock_after), (S.CLOCK_HOOK, S.CLOCK_MODEL))

    def test_clock_is_labelled_per_record_source(self):
        for record in self.records:
            if record["kind"] in ("subagent_invoked", "skill_event"):
                self.assertEqual(record["clock"], S.CLOCK_MODEL)
            elif record["kind"] in (
                "subagent_completed",
                "workflow_start",
                "tool_metrics",
                "file_change",
                "user_prompt",
            ):
                self.assertEqual(record["clock"], S.CLOCK_HOOK)

    def test_metrics_section_is_not_assumed_to_be_trailing(self):
        # `## Metrics` appears before four later `###` blocks. A parser that
        # treated it as a trailing section would lose all four.
        metrics_offset = [
            r["offset"]
            for r in self.records
            if r["kind"] == "section" and r["heading"] == "Metrics"
        ][0]
        later = [
            r
            for r in self.records
            if r["offset"] > metrics_offset
            and r["kind"].startswith(("subagent", "workflow", "skill"))
        ]
        self.assertEqual(len(later), 4)

    def test_incremental_tail_yields_absolute_offsets(self):
        split = self.records[4]["offset"]
        tail = S.parse_session_log(
            LOG.encode("utf-8")[split:].decode("utf-8"), base_offset=split
        )
        self.assertEqual(tail[0]["offset"], split)
        whole = [r["offset"] for r in self.records if r["offset"] >= split]
        self.assertEqual([r["offset"] for r in tail], whole)


class DiscoveryPrecedenceTests(unittest.TestCase):
    """hooks/workflow-summary.sh:84-135, reused verbatim."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="smith-activity-sessionlog.")
        self.vault = os.path.join(self.tmp, ".smith", "vault")
        os.makedirs(os.path.join(self.vault, "sessions"))
        self.log_a = os.path.join(self.vault, "sessions", "a.md")
        self.log_b = os.path.join(self.vault, "sessions", "b.md")
        for path in (self.log_a, self.log_b):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("# log\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _pointer(self, target):
        with open(
            os.path.join(self.vault, ".current-session"), "w", encoding="utf-8"
        ) as fh:
            fh.write(target + "\n")

    @staticmethod
    def _marker(branch, session_log):
        return {"branch": branch, "raw": {"session_log": session_log}}

    def test_tier_a_explicit_wins_even_when_missing(self):
        self._pointer(self.log_a)
        self.assertEqual(
            S.resolve_session_log(
                self.tmp,
                explicit="/nope/x.md",
                marker_records=[self._marker("b", self.log_b)],
            ),
            "/nope/x.md",
        )

    def test_tier_b_single_marker_with_a_value(self):
        self._pointer(self.log_a)
        self.assertEqual(
            S.resolve_session_log(
                self.tmp, marker_records=[self._marker("b", self.log_b)]
            ),
            self.log_b,
        )

    def test_tier_b_skips_markers_with_an_empty_session_log(self):
        # The worktree-marker shape. It carries no information, so it must not
        # count toward the "exactly one marker" test.
        self._pointer(self.log_a)
        records = [self._marker("wt", ""), self._marker("b", self.log_b)]
        self.assertEqual(
            S.resolve_session_log(self.tmp, marker_records=records), self.log_b
        )

    def test_tier_b_falls_through_when_only_empty_markers_exist(self):
        self._pointer(self.log_a)
        records = [self._marker("wt", ""), self._marker("wt2", "   ")]
        self.assertEqual(
            S.resolve_session_log(self.tmp, marker_records=records), self.log_a
        )

    def test_tier_b_disambiguates_several_by_branch(self):
        self._pointer(self.log_a)
        records = [self._marker("one", self.log_a), self._marker("two", self.log_b)]
        self.assertEqual(
            S.resolve_session_log(
                self.tmp, marker_records=records, current_branch="two"
            ),
            self.log_b,
        )

    def test_tier_b_falls_through_when_no_marker_branch_matches(self):
        self._pointer(self.log_a)
        records = [self._marker("one", self.log_b), self._marker("two", self.log_b)]
        self.assertEqual(
            S.resolve_session_log(
                self.tmp, marker_records=records, current_branch="three"
            ),
            self.log_a,
        )

    def test_tier_c_pointer(self):
        self._pointer(self.log_a)
        self.assertEqual(S.resolve_session_log(self.tmp, marker_records=[]), self.log_a)

    def test_tier_c_double_existence_check(self):
        # A pointer whose target is gone resolves to nothing, not to a path
        # that does not exist (metrics-tracker.sh:23-32).
        self._pointer(os.path.join(self.vault, "sessions", "deleted.md"))
        self.assertIsNone(S.resolve_session_log(self.tmp, marker_records=[]))

    def test_no_pointer_at_all(self):
        # The worktree case: .smith/vault/.current-session does not exist.
        self.assertIsNone(S.resolve_session_log(self.tmp, marker_records=[]))

    def test_unreadable_log_yields_no_records_rather_than_raising(self):
        self.assertEqual(S.read_session_log(os.path.join(self.tmp, "nope.md")), [])


if __name__ == "__main__":
    unittest.main()
