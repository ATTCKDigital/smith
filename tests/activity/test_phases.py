"""FR-16 / SC-3: phases.json stays in sync with the five SKILL.md files.

Adding, renaming, renumbering, reordering or removing a phase in any mapped
workflow fails here rather than silently rendering a stale stepper.

Plus the four structural invariants from data-model.md §3.

Reached from CI through the flat tests/smith-activity.test.sh wrapper — a
test_*.py file gates nothing on its own (.github/workflows/test-install.yml:58
globs tests/*.test.sh and nothing else).
"""

import json
import os
import unittest

from tests._harness import *  # noqa: F401,F403 — puts scripts/activity on sys.path

import phases as P

# Counts recorded in contracts/phases-json.md §1, pinned so a chain cannot grow
# or shrink unnoticed even if both sides are edited together.
EXPECTED_COUNTS = {
    "smith-new": 7,
    "smith-bugfix": 9,
    "smith-debug": 8,
    "smith-build": 11,
    "smith-finish": 9,
}


class PhaseMapSyncTests(unittest.TestCase):
    """SC-3 — extracted (number, title) pairs equal phases.json exactly."""

    @classmethod
    def setUpClass(cls):
        cls.phase_map = P.load_phase_map()
        cls.workflows = cls.phase_map["workflows"]

    def _source_path(self, workflow):
        return os.path.join(REPO_ROOT, P.workflow_source(self.phase_map, workflow))

    def test_the_five_mapped_workflows_are_present(self):
        self.assertEqual(set(self.workflows), set(EXPECTED_COUNTS))

    def test_every_source_file_exists_and_is_readable(self):
        # Fails when a SKILL.md is moved or renamed.
        for workflow in self.workflows:
            path = self._source_path(workflow)
            self.assertTrue(
                os.path.isfile(path), "%s: missing source %s" % (workflow, path)
            )
            with open(path, "r", encoding="utf-8") as fh:
                self.assertTrue(fh.read(), "%s: empty source %s" % (workflow, path))

    def test_phase_counts(self):
        for workflow, expected in EXPECTED_COUNTS.items():
            self.assertEqual(
                len(P.phases_for(self.phase_map, workflow)),
                expected,
                "%s: phases.json count changed" % workflow,
            )

    def test_extracted_pairs_equal_phases_json_same_order(self):
        for workflow in self.workflows:
            level, keyword = P.workflow_heading_dialect(self.phase_map, workflow)
            rows = P.extract_headings_from_file(
                self._source_path(workflow), level, keyword
            )
            extracted = [(number, title) for number, title, _ in rows]
            declared = [
                (phase["number"], phase["title"])
                for phase in P.phases_for(self.phase_map, workflow)
            ]
            # Same set, same order, same numbers — one assertion, because an
            # add, a rename, a renumber and a reorder are all the same defect:
            # the stepper would render something that is not in the SKILL.md.
            self.assertEqual(
                extracted,
                declared,
                "%s: phases.json is out of sync with %s"
                % (workflow, P.workflow_source(self.phase_map, workflow)),
            )

    def test_extraction_count_matches_expected(self):
        for workflow, expected in EXPECTED_COUNTS.items():
            level, keyword = P.workflow_heading_dialect(self.phase_map, workflow)
            rows = P.extract_headings_from_file(
                self._source_path(workflow), level, keyword
            )
            self.assertEqual(
                len(rows),
                expected,
                "%s: extracted %d headings, expected %d"
                % (workflow, len(rows), expected),
            )

    def test_smith_finish_uses_the_step_dialect(self):
        # The one chain with heading_level 3 and keyword Step. Anchoring to
        # `^## ` would miss all nine of its steps.
        self.assertEqual(
            P.workflow_heading_dialect(self.phase_map, "smith-finish"), (3, "Step")
        )
        for workflow in ("smith-new", "smith-bugfix", "smith-debug", "smith-build"):
            self.assertEqual(
                P.workflow_heading_dialect(self.phase_map, workflow), (2, "Phase")
            )


class PhaseMapInvariantTests(unittest.TestCase):
    """The four structural invariants of data-model.md §3."""

    @classmethod
    def setUpClass(cls):
        cls.phase_map = P.load_phase_map()
        cls.workflows = cls.phase_map["workflows"]

    def test_invariant_1_ids_are_globally_unique(self):
        ids = [
            phase["id"]
            for workflow in self.workflows
            for phase in P.phases_for(self.phase_map, workflow)
        ]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        self.assertEqual(duplicates, [], "duplicate phase ids: %s" % duplicates)
        self.assertEqual(len(ids), sum(EXPECTED_COUNTS.values()))

    def test_invariant_1b_id_matches_workflow_and_number(self):
        for workflow in self.workflows:
            for phase in P.phases_for(self.phase_map, workflow):
                self.assertEqual(phase["id"], "%s:%s" % (workflow, phase["number"]))

    def test_invariant_2_numbers_strictly_increasing_as_decimals(self):
        for workflow in self.workflows:
            numbers = [
                phase["number"] for phase in P.phases_for(self.phase_map, workflow)
            ]
            keys = [P.phase_sort_key(n) for n in numbers]
            self.assertEqual(keys, sorted(keys), "%s: numbers out of order" % workflow)
            self.assertEqual(
                len(set(keys)), len(keys), "%s: duplicate numbers" % workflow
            )
            for number in numbers:
                self.assertIsInstance(
                    number,
                    str,
                    "%s: number must be a string, not %r" % (workflow, type(number)),
                )

    def test_invariant_3_no_match_pattern_shared_across_chains(self):
        # The real collision this guards: smith-bugfix 3.5 and smith-debug 5.5
        # share the title "Update `.meta` Descriptions for Touched Methods"
        # exactly, so at least one match entry of each must be
        # workflow-qualified. Compared case-insensitively because match
        # patterns are applied case-insensitively.
        owner = {}
        collisions = []
        for workflow in self.workflows:
            for phase in P.phases_for(self.phase_map, workflow):
                self.assertTrue(
                    phase.get("match"), "%s has no match patterns" % phase["id"]
                )
                for pattern in phase["match"]:
                    key = pattern.lower()
                    previous = owner.get(key)
                    if previous and previous[0] != workflow:
                        collisions.append((pattern, previous[1], phase["id"]))
                    owner.setdefault(key, (workflow, phase["id"]))
        self.assertEqual(
            collisions, [], "match patterns shared across chains: %s" % collisions
        )

    def test_invariant_3b_the_meta_collision_is_qualified(self):
        bugfix = {p["id"]: p for p in P.phases_for(self.phase_map, "smith-bugfix")}
        debug = {p["id"]: p for p in P.phases_for(self.phase_map, "smith-debug")}
        self.assertEqual(
            bugfix["smith-bugfix:3.5"]["title"], debug["smith-debug:5.5"]["title"]
        )
        self.assertEqual(
            set(p.lower() for p in bugfix["smith-bugfix:3.5"]["match"])
            & set(p.lower() for p in debug["smith-debug:5.5"]["match"]),
            set(),
        )

    def test_invariant_4_handoff_targets_exist(self):
        for workflow in self.workflows:
            for phase in P.phases_for(self.phase_map, workflow):
                for target in P.handoff_targets(phase):
                    self.assertIn(
                        target,
                        self.workflows,
                        "%s: handoff to unmapped workflow %r" % (phase["id"], target),
                    )

    def test_declared_handoffs_and_mandatory_stops(self):
        # FR-18: exactly two mandatory stops today. FR-17/data-model §2.10:
        # the handoff key is the difference between "a known handoff" and "an
        # undesigned path" — without it every /smith-new run would emit a
        # false marker_contradiction.
        stops = sorted(
            phase["id"]
            for workflow in self.workflows
            for phase in P.phases_for(self.phase_map, workflow)
            if phase.get("mandatory_stop")
        )
        self.assertEqual(stops, ["smith-debug:6", "smith-new:5"])
        handoffs = {
            phase["id"]: P.handoff_targets(phase)
            for workflow in self.workflows
            for phase in P.phases_for(self.phase_map, workflow)
            if P.handoff_targets(phase)
        }
        self.assertEqual(
            handoffs,
            {"smith-new:6": ["smith-build"], "smith-debug:6": ["smith-bugfix"]},
        )

    def test_mandatory_stop_is_declared_on_every_phase(self):
        for workflow in self.workflows:
            for phase in P.phases_for(self.phase_map, workflow):
                self.assertIn(
                    "mandatory_stop", phase, "%s: missing mandatory_stop" % phase["id"]
                )
                self.assertIsInstance(phase["mandatory_stop"], bool)

    def test_phases_json_is_valid_json_with_a_version(self):
        with open(P.PHASES_JSON, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        self.assertEqual(raw.get("version"), 1)


if __name__ == "__main__":
    unittest.main()
