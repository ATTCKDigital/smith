"""contracts/phases-json.md §3 and §4 — the normalizer and the extractor.

Split out of test_phases.py so that file keeps headroom for the SC-1/SC-2
resolver fixtures: these cases pin the two primitives everything else in
phases.py is built on, and they grow with the contract rather than with the
state machine.

Reached from CI through the flat tests/smith-activity.test.sh wrapper.
"""

import unittest

from tests._harness import *  # noqa: F401,F403 — puts scripts/activity on sys.path

import phases as P


class NormalizePhaseTitleTests(unittest.TestCase):
    """The five rules of contracts/phases-json.md §3.

    These exercise phases.normalize_phase_title directly. test_phases.py's
    sync assertions go through the same function — the normalizer is never
    reimplemented in a test, because a second copy could drift and the sync
    test would then be testing the wrong thing.
    """

    def test_rule1_backticks_removed(self):
        self.assertEqual(
            P.normalize_phase_title("Update `.meta` Descriptions for Touched Methods"),
            "Update .meta Descriptions for Touched Methods",
        )

    def test_rule2_one_trailing_paren_group_removed(self):
        self.assertEqual(
            P.normalize_phase_title("Pre-Change Exploration (Conditional)"),
            "Pre-Change Exploration",
        )
        self.assertEqual(
            P.normalize_phase_title("Docker Rebuild (if applicable)"),
            "Docker Rebuild",
        )

    def test_rule2_interior_parens_are_content(self):
        # Only a TRAILING group is a qualifier.
        self.assertEqual(
            P.normalize_phase_title("Triage (fast) then Report"),
            "Triage (fast) then Report",
        )

    def test_rule2_removes_only_one_group(self):
        self.assertEqual(
            P.normalize_phase_title("Thing (a) (b)"),
            "Thing (a)",
        )

    def test_rule2_nested_group_removed_whole(self):
        self.assertEqual(
            P.normalize_phase_title("Thing (a (b) c)"),
            "Thing",
        )

    def test_rule3_trailing_em_dash_clause_removed(self):
        self.assertEqual(
            P.normalize_phase_title("Inventory — Assess Current State"),
            "Inventory",
        )

    def test_rule2_runs_before_rule3(self):
        # `Questions Gate (MANDATORY STOP — in Worktree)` must normalize to
        # `Questions Gate`, not to `Questions Gate (MANDATORY STOP`.
        self.assertEqual(
            P.normalize_phase_title("Questions Gate (MANDATORY STOP — in Worktree)"),
            "Questions Gate",
        )

    def test_rule4_whitespace_collapsed_and_stripped(self):
        self.assertEqual(
            P.normalize_phase_title("  Spec   Generation  "), "Spec Generation"
        )

    def test_rule5_case_is_preserved(self):
        # Case-sensitive comparison: a case change is a real edit.
        self.assertEqual(P.normalize_phase_title("spec generation"), "spec generation")
        self.assertNotEqual(
            P.normalize_phase_title("spec generation"), "Spec Generation"
        )

    def test_punctuation_preserved(self):
        for title in (
            "Worktree Creation & Setup",
            "Commit, Push & Merge",
            "Supply-Chain Review Pass",
            "Update .meta Descriptions",
        ):
            self.assertEqual(P.normalize_phase_title(title), title)


class ExtractorTests(unittest.TestCase):
    """contracts/phases-json.md §4 — the three non-optional requirements."""

    def test_fence_aware(self):
        text = "\n".join(
            [
                "## Phase 1: Real",
                "```bash",
                "gh pr create --body \"$(cat <<'EOF'",
                "## Phase 9: Not A Phase",
                "EOF",
                ')"',
                "```",
                "## Phase 2: Also Real",
            ]
        )
        rows = P.extract_headings(text, 2, "Phase")
        self.assertEqual(
            [(n, t) for n, t, _ in rows], [("1", "Real"), ("2", "Also Real")]
        )

    def test_exact_heading_level(self):
        text = "## Phase 1: Two\n### Phase 2: Three\n"
        self.assertEqual([n for n, _, _ in P.extract_headings(text, 2, "Phase")], ["1"])
        self.assertEqual([n for n, _, _ in P.extract_headings(text, 3, "Phase")], ["2"])

    def test_decimal_numbers_survive(self):
        text = "## Phase 3: A\n## Phase 3.5: B\n## Phase 3.6: C\n## Phase 3.7: D\n## Phase 4: E\n"
        numbers = [n for n, _, _ in P.extract_headings(text, 2, "Phase")]
        self.assertEqual(numbers, ["3", "3.5", "3.6", "3.7", "4"])

    def test_phase_sort_key_orders_3_7_before_4(self):
        self.assertLess(P.phase_sort_key("3.7"), P.phase_sort_key("4"))
        self.assertLess(P.phase_sort_key("1.5"), P.phase_sort_key("2"))

    def test_line_numbers_reported(self):
        text = "intro\n\n## Phase 0: Zero\n"
        self.assertEqual(P.extract_headings(text, 2, "Phase")[0][2], 3)

if __name__ == "__main__":
    unittest.main()
