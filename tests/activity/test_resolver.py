"""Phase-resolution replay: SC-1, FR-20 and SC-2 (T032/T033/T050).

The state machine driven over recorded fixtures with **no daemon, no network
and no clock** -- which is the whole reason ``phases.py``, ``stepper.py``,
``resolver.py``, ``nesting.py``, ``attribution.py``, ``findings.py`` and
``absence.py`` are pure. Every expectation lives here rather than in the
fixture, so a fixture cannot assert itself true.

tasks.md T032/T033/T050 name ``tests/activity/test_phases.py``. Appending there
took that file to 615 lines, past this repo's 500-line decompose threshold, and
buried a second concern inside the FR-16 sync suite. The split is by subject:
``test_phases.py`` pins the phase MAP against the SKILL.md files,
``test_resolver.py`` pins the RESOLVER against recorded runs. Both are
collected by the same ``unittest discover`` the flat
``tests/smith-activity.test.sh`` wrapper runs, so CI coverage is identical.

Run: ``PYTHONPATH=. python3 tests/activity/test_resolver.py``
"""

import os
import unittest

from tests._harness import *  # noqa: F401,F403 -- puts scripts/activity on sys.path

import attribution as ATTR
import findings as F
import phases as P
import resolver as R
import stepper as S
from tests.activity._fixtures import Fixture



class _ReplayCase(unittest.TestCase):
    FIXTURE = None
    ARTIFACTS = None

    def setUp(self):
        self.phase_map = P.load_phase_map()
        self.fx = Fixture(self.FIXTURE, artifacts=self.ARTIFACTS)
        self.addCleanup(self.fx.cleanup)

    def resolve(self, markers, needle=None, snapshots=None):
        records, events = self.fx.upto(needle)
        return R.resolve_project(
            markers,
            records=records,
            events=events,
            snapshots=snapshots,
            phase_map=self.phase_map,
        )


class SC1PhaseResolutionTests(_ReplayCase):
    """SC-1 -- the correct numbered phase at every checkpoint of a recorded
    ``/smith-new`` to ``/smith-build`` run, with the expected provenance."""

    FIXTURE = "sc1-new-to-build"
    ARTIFACTS = "build"

    def test_the_fixture_carries_two_real_markers_in_two_vaults(self):
        parent = self.fx.marker("smith-new")
        child = self.fx.marker("smith-build")
        self.assertTrue(parent["is_primary_vault"])
        self.assertFalse(child["is_primary_vault"])
        self.assertEqual(parent["branch"], child["branch"])
        # The worktree marker's session_log: is EMPTY and resolves through the
        # primary vault's .current-session -- binding constraint 10.
        self.assertEqual(parent["session_log_source"], "marker")
        self.assertEqual(child["session_log_source"], "current-session")
        self.assertEqual(parent["session_log"], child["session_log"])
        self.assertNotEqual(parent["key"], child["key"])

    def test_checkpoint_spec_generation(self):
        workflow = self.resolve(
            [self.fx.marker("smith-new")], "Phase 3 Spec Generation"
        )["workflows"][0]
        self.assertEqual(workflow["current_phase_id"], "smith-new:3")
        self.assertEqual(workflow["current_number"], "3")
        self.assertEqual(workflow["provenance"], P.PROV_LIVE_TASK_EVENT)
        self.assertEqual(workflow["activity"], P.ACTIVITY_WORKING)

    def test_checkpoint_explore_is_resolved_from_a_skill_event(self):
        workflow = self.resolve([self.fx.marker("smith-new")], "smith-explore")[
            "workflows"
        ][0]
        self.assertEqual(workflow["current_phase_id"], "smith-new:0")
        self.assertEqual(workflow["provenance"], P.PROV_SKILL_EVENT)

    def test_checkpoint_questions_gate_is_waiting_not_working(self):
        """FR-18 / T027 -- a MANDATORY STOP never renders as working."""
        workflow = self.resolve(
            [self.fx.marker("smith-new")], "Phase 5 Questions Gate"
        )["workflows"][0]
        self.assertEqual(workflow["current_phase_id"], "smith-new:5")
        self.assertTrue(workflow["mandatory_stop"])
        self.assertEqual(workflow["activity"], P.ACTIVITY_WAITING_USER)
        self.assertNotEqual(workflow["activity"], P.ACTIVITY_WORKING)
        self.assertEqual(workflow["provenance"], P.PROV_SUBAGENT_BLOCK)

    def test_nested_handoff_pins_the_parent_and_renders_the_child(self):
        """FR-17 -- smith-new 6/7 Update Plan, then smith-build 3/11 Testing."""
        out = self.resolve(
            [self.fx.marker("smith-new"), self.fx.marker("smith-build")],
            "Phase 3: Testing",
        )
        parent = [w for w in out["workflows"] if w["workflow_type"] == "smith-new"][0]
        child = [w for w in out["workflows"] if w["workflow_type"] == "smith-build"][0]

        self.assertEqual(parent["current_phase_id"], "smith-new:6")
        self.assertEqual(parent["current_number"], "6")
        self.assertEqual(len(parent["phases"]), 7)
        self.assertTrue(parent["pinned_at_handoff"])
        self.assertEqual(parent["provenance"], P.PROV_CHILD_MARKER)
        self.assertEqual(parent["child_keys"], [child["key"]])

        self.assertEqual(child["current_phase_id"], "smith-build:3")
        self.assertEqual(child["current_title"], "Testing")
        self.assertEqual(len(child["phases"]), 11)
        self.assertEqual(child["parent_key"], parent["key"])
        # Never replaced: the parent is still its own record.
        self.assertNotEqual(parent["key"], child["key"])

    def test_the_normal_two_marker_handoff_raises_no_marker_contradiction(self):
        """Binding constraint 10 -- the nest is legitimate, not a contradiction.

        The injected `cross_chain` entry is load-bearing. Mutation testing
        caught this assertion holding VACUOUSLY: in this fixture the parent's
        own attributed stream carries no cross-chain signal (the
        `/smith-build invocation` line is ambiguous between the two markers and
        is dropped), so deleting the guard in `marker_contradiction_findings`
        entirely left the test green. The handoff signal is therefore supplied
        explicitly, and a negative control asserts the guard still fires when
        neither a declared handoff nor a child marker is present.
        """
        out = self.resolve(
            [self.fx.marker("smith-new"), self.fx.marker("smith-build")],
            "Phase 3: Testing",
        )
        parent = [w for w in out["workflows"] if w["workflow_type"] == "smith-new"][0]
        child = [w for w in out["workflows"] if w["workflow_type"] == "smith-build"][0]
        self.assertEqual(parent["child_keys"], [child["key"]])

        handoff_signal = {
            "workflow": "smith-build",
            "evidence": "skill event /smith-build invocation",
            "at": None,
        }
        parent["cross_chain"] = [handoff_signal]
        found = F.marker_contradiction_findings(out["workflows"], self.phase_map)
        self.assertEqual(found, [], "a normal smith-new nest fired %r" % found)

        # Negative control: same signal, a chain that declares no handoff to it
        # and no child marker. This MUST fire, or the assertion above is empty.
        orphan = dict(
            parent, workflow_type="smith-bugfix", child_keys=[], key="orphan"
        )
        self.assertEqual(
            len(F.marker_contradiction_findings([orphan], self.phase_map)), 1
        )

    def test_fr17_fallback_when_no_child_marker_exists(self):
        workflow = self.resolve([self.fx.marker("smith-new")], "Phase 3: Testing")[
            "workflows"
        ][0]
        inferred = workflow["child_inferred"]
        self.assertIsNotNone(inferred)
        self.assertEqual(inferred["workflow_type"], "smith-build")
        # Only ever opened at a phase declaring a handoff for that workflow.
        self.assertEqual(inferred["handoff_phase_id"], "smith-new:6")
        self.assertIn("smith-build", [c["workflow"] for c in workflow["cross_chain"]])

    def test_fr12_artifact_corroboration_on_a_cold_start(self):
        """No event stream at all -- artifacts alone, both layouts, worktree first."""
        import artifacts as AR

        parent = self.fx.marker("smith-new")
        child = self.fx.marker("smith-build")
        roots = AR.roots_for_marker(parent)
        # Worktree before primary repo -- the order is the requirement.
        self.assertEqual(roots[0], parent["worktree"])
        self.assertEqual(roots[-1], parent["project"])
        snapshot = AR.scan_artifacts(parent["slug"], roots)
        self.assertIsNotNone(snapshot)
        self.assertTrue(snapshot["dir"].startswith(parent["worktree"]))
        self.assertEqual(snapshot["layout"], "systems")
        self.assertEqual(snapshot["tasks"], {"checked": 2, "total": 4})

        out = R.resolve_project(
            [parent, child],
            records=[],
            events=[],
            snapshots={parent["key"]: snapshot, child["key"]: snapshot},
            phase_map=self.phase_map,
        )
        by_type = {w["workflow_type"]: w for w in out["workflows"]}
        states = {s["id"]: s for s in by_type["smith-new"]["phases"]}
        self.assertEqual(states["smith-new:3"]["state"], P.STATE_COMPLETED)
        self.assertEqual(states["smith-new:3"]["provenance"], P.PROV_ARTIFACT)
        self.assertEqual(states["smith-new:4"]["state"], P.STATE_COMPLETED)
        build = {s["id"]: s for s in by_type["smith-build"]["phases"]}
        self.assertEqual(build["smith-build:1"]["state"], P.STATE_COMPLETED)
        self.assertEqual(by_type["smith-build"]["current_phase_id"], "smith-build:2")
        self.assertEqual(by_type["smith-build"]["provenance"], P.PROV_ARTIFACT)

    def test_a_file_read_never_advances_a_phase(self):
        """FR-12 -- the smith-build Phase 3.5 clean-code rubric case.

        A Read produces a `file_change`-shaped record and nothing else. It must
        yield zero signals, so it cannot move the stepper even though the path
        it names matches a phase title.
        """
        read_record = {
            "kind": "file_change",
            "offset": 10,
            "seq": 10,
            "tool": "Read",
            "path": "skills/smith-clean-code/SKILL.md",
            "timestamp_text": "12:00:00",
            "clock": "hook",
        }
        signals, cross = S.log_signals([read_record], "smith-build", self.phase_map)
        self.assertEqual(signals, [])
        self.assertEqual(cross, [])
        self.assertEqual(ATTR.evidence_records([read_record]), [])

    def test_fr13_marker_phase_beats_every_inferred_signal(self):
        marker = dict(self.fx.marker("smith-new"))
        marker["declared_phase"] = "2"
        records, events = self.fx.upto("Phase 5 Questions Gate")
        workflow = R.resolve_project(
            [marker], records=records, events=events, phase_map=self.phase_map
        )["workflows"][0]
        self.assertEqual(workflow["current_phase_id"], "smith-new:2")
        self.assertEqual(workflow["provenance"], P.PROV_MARKER_PHASE)

    def test_fr58_ordering_is_append_order_not_the_parsed_stamp(self):
        """The fixture's clocks disagree by four hours, as the real log's do.

        Sorting on the parsed stamp would put the very first record -- the
        `workflow-start` a hook wrote in UTC -- after every model-authored
        block. Append order keeps it first.
        """
        records, _ = self.fx.upto()
        evidence = ATTR.evidence_records(records)
        stamps = [r["timestamp_text"] for r in evidence]
        self.assertNotEqual(
            stamps, sorted(stamps), "fixture lost its mixed-clock property"
        )
        by_append = evidence[0]
        by_stamp = sorted(evidence, key=lambda r: r["timestamp_text"])[0]
        self.assertEqual(by_append["kind"], "workflow_start")
        self.assertNotEqual(by_append["offset"], by_stamp["offset"])

    def test_no_resolver_module_orders_on_a_parsed_timestamp(self):
        """FR-58 enforced structurally: no sort key mentions a timestamp."""
        modules = (
            "phases.py", "stepper.py", "resolver.py", "nesting.py",
            "attribution.py", "findings.py", "absence.py",
        )
        for name in modules:
            with open(os.path.join(ACTIVITY_DIR, name), "r", encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, 1):
                    if "sort(" not in line and "sorted(" not in line:
                        continue
                    self.assertNotIn(
                        "timestamp",
                        line,
                        "%s:%d orders on a timestamp: %s"
                        % (name, lineno, line.strip()),
                    )


class HonestUnknownTests(_ReplayCase):
    """FR-20 / T033 -- exhausted signals resolve to `phase unknown`."""

    FIXTURE = "fr20-exhausted"

    def test_exhausted_signals_yield_no_current_phase(self):
        workflow = self.resolve(self.fx.markers)["workflows"][0]
        self.assertIsNone(workflow["current_phase_id"])
        self.assertIsNone(workflow["current_title"])
        self.assertIn(P.NOTE_PHASE_UNKNOWN, workflow["notes"])
        self.assertEqual(workflow["activity"], P.ACTIVITY_UNKNOWN)

    def test_the_last_known_phase_and_its_timestamp_survive(self):
        workflow = self.resolve(self.fx.markers)["workflows"][0]
        last = workflow["last_known_phase"]
        self.assertIsNotNone(last)
        self.assertEqual(last["id"], "smith-bugfix:3")
        self.assertEqual(last["title"], "Implement the Fix")
        self.assertTrue(last["at"])
        self.assertEqual(last["provenance"], P.PROV_SUBAGENT_COMPLETION)
        # The display stamp comes back labelled with the clock that wrote it.
        self.assertIn(last["clock"], ("hook", "model"))

    def test_no_phase_is_guessed_interpolated_or_nearest_matched(self):
        workflow = self.resolve(self.fx.markers)["workflows"][0]
        currents = [s for s in workflow["phases"] if s["state"] == P.STATE_CURRENT]
        self.assertEqual(currents, [])

    def test_an_unmapped_workflow_type_yields_an_empty_chain(self):
        """T030 -- the resolver never invents a chain."""
        marker = {
            "key": "p|v|x.yaml",
            "workflow_type": "smith-nonexistent",
            "branch": "b",
            "worktree": None,
            "slug": "x",
        }
        workflow = R.resolve_project(
            [marker], records=[], events=[], phase_map=self.phase_map
        )["workflows"][0]
        self.assertEqual(workflow["phases"], [])
        self.assertIsNone(workflow["current_phase_id"])
        self.assertEqual(workflow["notes"], [P.NOTE_NO_PHASE_MAP])


class SC2ConcurrentAttributionTests(_ReplayCase):
    """SC-2 / T050 -- two workflows, one session log, zero cross-attribution."""

    FIXTURE = "sc2-concurrent"

    def setUp(self):
        super(SC2ConcurrentAttributionTests, self).setUp()
        self.out = self.resolve(self.fx.markers)
        self.by_branch = {w["branch"]: w for w in self.out["workflows"]}

    def test_exactly_two_workflow_records(self):
        self.assertEqual(len(self.out["workflows"]), 2)
        self.assertEqual(
            sorted(self.by_branch),
            ["60-activity-dashboard", "67-deterministic-questions"],
        )

    def test_the_two_markers_name_the_same_session_log(self):
        logs = {m["session_log"] for m in self.fx.markers}
        self.assertEqual(len(logs), 1)

    def test_no_item_is_attributed_to_more_than_one_workflow(self):
        split = self.out["attribution"]
        for stream in ("records", "events"):
            seen = []
            for items in split[stream].values():
                seen.extend(id(item) for item in items)
            self.assertEqual(
                len(seen), len(set(seen)), "%s duplicated across workflows" % stream
            )
        # Single assignment: one decision per item, and never two keys.
        self.assertEqual(
            len(split["decisions"]),
            sum(len(v) for v in split["records"].values())
            + sum(len(v) for v in split["events"].values())
            + self.out["unattributed_events"],
        )

    def test_neither_stepper_advances_on_the_others_events(self):
        a = self.by_branch["60-activity-dashboard"]
        b = self.by_branch["67-deterministic-questions"]
        self.assertEqual(a["current_phase_id"], "smith-new:4")
        self.assertEqual(b["current_phase_id"], "smith-new:3")
        # A single undifferentiated stream would put both at the last event's
        # phase. That they differ IS the acceptance criterion.
        self.assertNotEqual(a["current_phase_id"], b["current_phase_id"])

    def test_ambiguous_blocks_are_dropped_and_counted_never_duplicated(self):
        split = self.out["attribution"]
        self.assertGreater(self.out["unattributed_events"], 0)
        dropped = [d for d in split["decisions"] if d["key"] is None]
        self.assertEqual(len(dropped), self.out["unattributed_events"])
        # Both markers are `smith-new`, so a block naming a smith-new phase
        # matches BOTH chains and must be dropped rather than duplicated.
        reasons = " ".join(d["reason"] for d in dropped)
        self.assertIn("dropped rather than duplicated", reasons)

    def test_the_workflow_start_stamps_attribute_by_branch(self):
        split = self.out["attribution"]
        by_branch_rule = [d for d in split["decisions"] if d["rule"] == ATTR.RULE_BRANCH]
        self.assertEqual(len(by_branch_rule), 2)
        self.assertEqual(len({d["key"] for d in by_branch_rule}), 2)

    def test_hook_events_attribute_by_worktree_prefix(self):
        split = self.out["attribution"]
        by_worktree = [d for d in split["decisions"] if d["rule"] == ATTR.RULE_WORKTREE]
        self.assertEqual(len(by_worktree), 4)
        self.assertEqual(len({d["key"] for d in by_worktree}), 2)


class PermissionStateTests(unittest.TestCase):
    """T028 / FR-18 -- the PRIMARY waiting signal is the event stream."""

    def test_an_outstanding_request_means_waiting(self):
        state = R.permission_state(
            [
                {
                    "hook_event_name": "PermissionRequest",
                    "prompt_id": "p1",
                    "tool_use_id": "t1",
                    "timestamp": "2026-09-22T16:00:00Z",
                }
            ]
        )
        self.assertTrue(state["waiting"])
        self.assertEqual(state["since"], "2026-09-22T16:00:00Z")

    def test_a_post_tool_use_resolves_it(self):
        events = [
            {"hook_event_name": "PermissionRequest", "prompt_id": "p1", "tool_use_id": "t1"},
            {"hook_event_name": "PostToolUse", "prompt_id": "p1", "tool_use_id": "t1"},
        ]
        self.assertFalse(R.permission_state(events)["waiting"])

    def test_a_permission_denied_resolves_it(self):
        events = [
            {"hook_event_name": "PermissionRequest", "prompt_id": "p1", "tool_use_id": "t1"},
            {"hook_event_name": "PermissionDenied", "prompt_id": "p1", "tool_use_id": "t1"},
        ]
        self.assertFalse(R.permission_state(events)["waiting"])

    def test_a_different_tool_call_in_the_same_turn_does_not_resolve_it(self):
        events = [
            {"hook_event_name": "PermissionRequest", "prompt_id": "p1", "tool_use_id": "t1"},
            {"hook_event_name": "PostToolUse", "prompt_id": "p1", "tool_use_id": "t2"},
        ]
        self.assertTrue(R.permission_state(events)["waiting"])

    def test_no_events_is_not_waiting_and_says_so(self):
        state = R.permission_state([])
        self.assertFalse(state["waiting"])
        self.assertTrue(state["evidence"])


if __name__ == "__main__":
    unittest.main()
