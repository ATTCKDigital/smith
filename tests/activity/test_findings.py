"""Divergence and absence findings: SC-5, SC-6, SC-19, SC-20, SC-21.

T044/T045/T046. Every function under test is pure -- ``now`` is passed in, so
the 90-second window is exercised without sleeping and the suite runs in
milliseconds.

Reached from CI through the flat ``tests/smith-activity.test.sh`` wrapper,
which runs ``unittest discover`` over ``tests/activity``.

Run: ``PYTHONPATH=. python3 tests/activity/test_findings.py``
"""

import json
import os
import unittest

from tests._harness import *  # noqa: F401,F403 -- puts scripts/activity on sys.path

import absence as A
import findings as F
import hookset as H
import phases as P
import resolver as R
from tests.activity._fixtures import Fixture

US2 = os.path.join(ACTIVITY_FIXTURES_DIR, "us2-findings")


def _load(name):
    with open(os.path.join(US2, name), "r", encoding="utf-8") as fh:
        return json.load(fh)


class _FindingsCase(unittest.TestCase):
    FIXTURE = None

    def setUp(self):
        self.phase_map = P.load_phase_map()
        if self.FIXTURE:
            self.fx = Fixture(self.FIXTURE)
            self.addCleanup(self.fx.cleanup)

    def workflow(self):
        records, events = self.fx.upto()
        return R.resolve_project(
            self.fx.markers, records=records, events=events, phase_map=self.phase_map
        )["workflows"][0]


class SC5SkillLoggingBugTests(_FindingsCase):
    """SC-5 / FR-22(a) -- a Task dispatch with no matching log block."""

    FIXTURE = "us2-findings/a-missing-block"

    def setUp(self):
        super(SC5SkillLoggingBugTests, self).setUp()
        self.wf = self.workflow()
        self.dispatches = F.dispatches_from_workflow(self.wf)
        self.blocks = F.blocks_from_workflow(self.wf)

    def test_the_fixture_has_two_dispatches_and_one_matching_block(self):
        self.assertEqual(len(self.dispatches), 2)
        phases_with_blocks = {b["phase_id"] for b in self.blocks}
        self.assertIn("smith-new:3", phases_with_blocks)
        self.assertNotIn("smith-new:4", phases_with_blocks)

    def test_exactly_one_divergence_finding(self):
        found = F.skill_logging_bug_findings(
            self.dispatches, self.blocks, now="2026-09-22T16:10:00Z"
        )
        self.assertEqual(len(found), 1)
        finding = found[0]
        self.assertEqual(finding["kind"], F.KIND_DIVERGENCE)
        self.assertEqual(finding["classification"], F.CLASS_SKILL_LOGGING_BUG)
        self.assertEqual(finding["severity"], F.SEVERITY_WARN)
        self.assertFalse(finding["retracted"])

    def test_the_finding_names_the_workflow_the_phase_and_the_timestamp(self):
        finding = F.skill_logging_bug_findings(
            self.dispatches, self.blocks, now="2026-09-22T16:10:00Z"
        )[0]
        self.assertEqual(finding["workflow_key"], self.wf["key"])
        self.assertEqual(finding["phase_id"], "smith-new:4")
        self.assertTrue(finding["timestamp"])
        self.assertIn("toolu_unlogged", finding["evidence"])

    def test_the_window_is_two_sided(self):
        """FR-22 -- the SKILLs write the block BEFORE the Agent call.

        A block one second EARLIER than its dispatch must reconcile. A
        one-directional comparison would classify every correctly-logged
        dispatch in the repository as a logging bug.
        """
        dispatch = {
            "id": "d1", "workflow_key": "wk", "phase_id": "smith-new:3",
            "observed_at": 1000.0, "description": "Phase 3 Spec Generation",
        }
        earlier = dict(dispatch, id="b-early", observed_at=999.0)
        later = dict(dispatch, id="b-late", observed_at=1001.0)
        self.assertTrue(F.paired(dispatch, earlier))
        self.assertTrue(F.paired(dispatch, later))
        # ... and 91 seconds either way does NOT.
        self.assertFalse(F.paired(dispatch, dict(dispatch, observed_at=909.0)))
        self.assertFalse(F.paired(dispatch, dict(dispatch, observed_at=1091.0)))

    def test_a_dispatch_whose_block_was_always_there_raises_nothing(self):
        found = F.skill_logging_bug_findings(
            [self.dispatches[0]], self.blocks, now="2026-09-22T16:10:00Z"
        )
        self.assertEqual(found, [])


class SC20RetractionTests(_FindingsCase):
    """SC-20 / FR-59 -- a retracted finding RESOLVES; it is never removed."""

    FIXTURE = "us2-findings/a-missing-block"

    def setUp(self):
        super(SC20RetractionTests, self).setUp()
        self.wf = self.workflow()
        self.dispatches = F.dispatches_from_workflow(self.wf)
        self.blocks = F.blocks_from_workflow(self.wf)
        # Raise first, with no blocks visible yet: the daemon's state at the
        # instant a dispatch arrives ahead of its block.
        self.raised = F.skill_logging_bug_findings(
            self.dispatches, [], now="2026-09-22T16:00:35Z"
        )
        self.raised_ids = {f["finding_id"] for f in self.raised}

    def test_the_raise_produces_a_warn_for_every_unreconciled_dispatch(self):
        self.assertEqual(len(self.raised), 2)
        for finding in self.raised:
            self.assertFalse(finding["retracted"])
            self.assertEqual(finding["severity"], F.SEVERITY_WARN)

    def test_the_late_block_settles_the_finding_rather_than_removing_it(self):
        settled = F.skill_logging_bug_findings(
            self.dispatches, self.blocks, now="2026-09-22T16:10:00Z",
            raised=self.raised_ids,
        )
        # STILL PRESENT. A finding that vanishes reads as a rendering glitch.
        self.assertEqual(len(settled), len(self.raised))
        by_id = {f["finding_id"]: f for f in settled}
        self.assertEqual(set(by_id), self.raised_ids)

        reconciled = [f for f in settled if f["retracted"]]
        self.assertEqual(len(reconciled), 1)
        self.assertEqual(reconciled[0]["phase_id"], "smith-new:3")
        self.assertEqual(reconciled[0]["severity"], F.SEVERITY_INFO)
        self.assertIn("reconciled", reconciled[0]["evidence"])

    def test_the_finding_id_is_stable_across_the_transition(self):
        """Retraction is an UPSERT: the same id, or the client renders two."""
        settled = F.skill_logging_bug_findings(
            self.dispatches, self.blocks, now="2026-09-22T16:10:00Z",
            raised=self.raised_ids,
        )
        raised_three = [f for f in self.raised if f["phase_id"] == "smith-new:3"][0]
        settled_three = [f for f in settled if f["phase_id"] == "smith-new:3"][0]
        self.assertEqual(raised_three["finding_id"], settled_three["finding_id"])
        self.assertNotEqual(raised_three["retracted"], settled_three["retracted"])

    def test_the_unreconciled_one_stays_raised(self):
        settled = F.skill_logging_bug_findings(
            self.dispatches, self.blocks, now="2026-09-22T16:10:00Z",
            raised=self.raised_ids,
        )
        still = [f for f in settled if not f["retracted"]]
        self.assertEqual(len(still), 1)
        self.assertEqual(still[0]["phase_id"], "smith-new:4")


class SC6AbsenceTests(_FindingsCase):
    """SC-6 / FR-23 -- a passed-over phase renders SKIPPED and is reported."""

    FIXTURE = "us2-findings/c-skipped-phase"

    def test_the_phase_renders_skipped_not_merely_not_completed(self):
        workflow = self.workflow()
        states = {s["id"]: s for s in workflow["phases"]}
        self.assertEqual(states["smith-new:2"]["state"], P.STATE_SKIPPED)
        self.assertNotEqual(states["smith-new:2"]["state"], P.STATE_REMAINING)
        self.assertNotEqual(states["smith-new:2"]["state"], P.STATE_COMPLETED)
        self.assertTrue(states["smith-new:2"]["evidence"])

    def test_exactly_one_phase_skipped_absence_finding(self):
        workflow = self.workflow()
        found = A.phase_absence_findings(workflow)
        self.assertEqual(len(found), 1)
        finding = found[0]
        self.assertEqual(finding["kind"], F.KIND_ABSENCE)
        self.assertEqual(finding["classification"], F.CLASS_PHASE_SKIPPED)
        self.assertEqual(finding["phase_id"], "smith-new:2")
        self.assertEqual(finding["workflow_key"], workflow["key"])

    def test_absence_is_rendered_explicitly_not_as_a_missing_indicator(self):
        finding = A.phase_absence_findings(self.workflow())[0]
        self.assertTrue(finding["observed"])
        self.assertTrue(finding["evidence"])


class GateNeverReachedTests(_FindingsCase):
    """FR-23(b) -- a MANDATORY STOP the workflow advanced past."""

    FIXTURE = "us2-findings/c-skipped-gate"

    def test_the_gate_is_reported_as_never_reached(self):
        workflow = self.workflow()
        states = {s["id"]: s for s in workflow["phases"]}
        self.assertTrue(states["smith-new:5"]["mandatory_stop"])
        self.assertEqual(states["smith-new:5"]["state"], P.STATE_SKIPPED)
        found = A.phase_absence_findings(workflow)
        classes = [f["classification"] for f in found]
        self.assertIn(F.CLASS_GATE_NEVER_REACHED, classes)
        gate = [f for f in found if f["classification"] == F.CLASS_GATE_NEVER_REACHED]
        self.assertEqual(len(gate), 1)
        self.assertEqual(gate[0]["phase_id"], "smith-new:5")
        self.assertEqual(gate[0]["severity"], F.SEVERITY_WARN)

    def test_a_remaining_gate_is_only_reported_once_the_workflow_ended(self):
        workflow = self.workflow()
        # Phase 6 is `current`, so nothing after it is reportable while live.
        live = {f["phase_id"] for f in A.phase_absence_findings(workflow, ended=False)}
        ended = {f["phase_id"] for f in A.phase_absence_findings(workflow, ended=True)}
        self.assertEqual(live, {"smith-new:5"})
        self.assertEqual(ended, {"smith-new:5"})


class SC19PermissionDisagreementTests(unittest.TestCase):
    """SC-19 / FR-57 -- disagreement is a finding; absence of one is not."""

    def setUp(self):
        self.agents = _load("d-agents.json")
        self.waiting = {
            "waiting": True,
            "evidence": "PermissionRequest toolu_01 with no PermissionDenied",
        }

    def _session(self, key):
        record = self.agents[key]
        return {
            "session_id": record["sessionId"],
            "status": record.get("status"),
            "permission": self.waiting,
            "workflow_key": "proj|vault|60-activity-dashboard.yaml",
            "timestamp": record["startedAt"],
        }

    def test_a_disagreeing_status_produces_exactly_one_finding(self):
        found = F.permission_disagreement_findings([self._session("disagrees")])
        self.assertEqual(len(found), 1)
        finding = found[0]
        self.assertEqual(finding["classification"], F.CLASS_PERMISSION_DISAGREEMENT)
        # FR-21: BOTH values, both sources, side by side.
        self.assertIn("waiting on permission", finding["observed"])
        self.assertIn("idle", finding["self_reported"])
        self.assertIn("claude agents --json", finding["self_reported"])
        self.assertIn(self.agents["disagrees"]["sessionId"], finding["evidence"])

    def test_an_agreeing_status_produces_nothing(self):
        self.assertEqual(
            F.permission_disagreement_findings([self._session("agrees")]), []
        )

    def test_an_absent_status_produces_nothing(self):
        """17 of 23 real records have no `status`. That is not disagreement."""
        session = self._session("no_status")
        self.assertIsNone(session["status"])
        self.assertEqual(F.permission_disagreement_findings([session]), [])

    def test_the_fixture_records_carry_none_of_the_fields_that_do_not_exist(self):
        for record in self.agents.values():
            if not isinstance(record, dict):
                continue
            for absent in ("waitingFor", "state", "id"):
                self.assertNotIn(absent, record)


class SC21HookExpectationTests(unittest.TestCase):
    """SC-21 / FR-60 / FR-61 -- expectation comes from the INSTALLED settings."""

    def setUp(self):
        self.readable, err = H.read_installed_settings(
            os.path.join(US2, "e-settings-readable.json")
        )
        self.assertIsNone(err)
        self.wired = H.wired_hooks(self.readable)
        self.shipped = H.read_shipped_manifest(
            os.path.join(US2, "e-shipped-hooks.json")
        )

    def test_unreadable_settings_disable_absence_detection_with_a_notice(self):
        obj, err = H.read_installed_settings(
            os.path.join(US2, "e-settings-unreadable.json")
        )
        self.assertIsNone(obj)
        self.assertTrue(err)
        self.assertIsNone(A.expected_hook_set(None))

        result = F.derive_findings(
            workflows=(), wired=None, settings_error=err, shipped=self.shipped
        )
        self.assertFalse(result["absence_enabled"])
        self.assertIn(F.DEGRADED_EXPECTED_HOOKS, result["degraded"])
        self.assertTrue(any("Absence detection is OFF" in n for n in result["notices"]))
        absence_findings = [
            f for f in result["findings"] if f["kind"] == F.KIND_ABSENCE
        ]
        self.assertEqual(absence_findings, [])

    def test_expectation_is_never_an_empty_set_standing_in_for_unknown(self):
        self.assertIsNone(A.expected_hook_set(None))
        self.assertEqual(A.expected_hook_set({}), set())

    def test_a_shipped_but_unwired_hook_produces_exactly_one_finding(self):
        found = A.shipped_not_wired_findings(self.shipped, self.wired)
        self.assertEqual(len(found), 1)
        finding = found[0]
        self.assertEqual(finding["classification"], F.CLASS_SHIPPED_NOT_WIRED)
        self.assertEqual(finding["subject"], "subagent-vault-writeback.sh")
        self.assertEqual(finding["kind"], F.KIND_DIVERGENCE)
        # FR-61: the shipped side is `observed`, the settings side is null.
        self.assertIsNone(finding["self_reported"])

    def test_shipped_not_wired_is_distinct_from_hook_never_fired(self):
        shipped = A.shipped_not_wired_findings(self.shipped, self.wired)
        expected = A.expected_hook_set(self.wired, tools_used=["Bash", "Write"])
        never = A.hook_never_fired_findings(
            expected, fired=["security-guard-bash.sh", "session-start-logger.sh"]
        )
        self.assertEqual(len(never), 1)
        self.assertEqual(never[0]["subject"], "lint-on-save.sh")
        self.assertNotEqual(
            shipped[0]["classification"], never[0]["classification"]
        )
        self.assertNotEqual(shipped[0]["finding_id"], never[0]["finding_id"])
        self.assertEqual(never[0]["kind"], F.KIND_ABSENCE)

    def test_a_hook_is_not_expected_in_a_session_that_could_not_trigger_it(self):
        """FR-60's applicability table -- lint-on-save needs a Write or Edit."""
        expected = A.expected_hook_set(self.wired, tools_used=["Bash"])
        self.assertNotIn("lint-on-save.sh", expected)
        self.assertIn("security-guard-bash.sh", expected)
        self.assertEqual(A.hook_never_fired_findings(expected, fired=list(expected)), [])

    def test_no_manifest_means_no_shipped_not_wired_findings(self):
        self.assertEqual(A.shipped_not_wired_findings(None, self.wired), [])
        result = F.derive_findings(workflows=(), wired=self.wired, shipped=None)
        self.assertTrue(
            any("shipped-hook manifest" in n for n in result["notices"])
        )


class UndesignedPathTests(unittest.TestCase):
    """FR-22(b) -- an artifact with no preceding dispatch or skill event."""

    def setUp(self):
        self.artifacts = _load("b-artifacts.json")
        self.workflow = {
            "key": "wk",
            "workflow_type": "smith-new",
            "signals": [
                {
                    "provenance": P.PROV_SUBAGENT_BLOCK,
                    "order": (0, 500, 0),
                    "phase_id": "smith-new:3",
                }
            ],
        }

    def _seen(self, key):
        row = dict(self.artifacts[key])
        row["order"] = tuple(row["order"])
        row["workflow_key"] = "wk"
        return row

    def test_an_artifact_ahead_of_every_signal_is_an_undesigned_path(self):
        found = F.undesigned_path_findings([self._seen("undesigned")], [self.workflow])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["classification"], F.CLASS_UNDESIGNED_PATH)
        self.assertEqual(found[0]["kind"], F.KIND_DIVERGENCE)

    def test_a_corroborated_artifact_fires_nothing(self):
        found = F.undesigned_path_findings(
            [self._seen("corroborated")], [self.workflow]
        )
        self.assertEqual(found, [])


class MarkerContradictionTests(unittest.TestCase):
    """FR-22(c) -- only a cross-chain signal with NO declared handoff."""

    def setUp(self):
        self.phase_map = P.load_phase_map()

    def _workflow(self, workflow_type, target, child_keys=()):
        return {
            "key": "wk-%s" % workflow_type,
            "workflow_type": workflow_type,
            "current_phase_id": "%s:3" % workflow_type,
            "child_keys": list(child_keys),
            "cross_chain": [
                {"workflow": target, "evidence": "a %s signal" % target, "at": None}
            ],
        }

    def test_an_undeclared_cross_chain_signal_fires(self):
        # smith-bugfix declares no handoff to anything.
        found = F.marker_contradiction_findings(
            [self._workflow("smith-bugfix", "smith-build")], self.phase_map
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["classification"], F.CLASS_MARKER_CONTRADICTION)
        self.assertIn("smith-bugfix", found[0]["self_reported"])

    def test_a_declared_handoff_never_fires(self):
        # smith-new:6 declares handoff to smith-build.
        found = F.marker_contradiction_findings(
            [self._workflow("smith-new", "smith-build")], self.phase_map
        )
        self.assertEqual(found, [])

    def test_a_real_child_marker_never_fires(self):
        parent = self._workflow("smith-bugfix", "smith-build", child_keys=["wk-child"])
        child = {"key": "wk-child", "workflow_type": "smith-build"}
        self.assertEqual(
            F.marker_contradiction_findings([parent, child], self.phase_map), []
        )


class FindingShapeTests(unittest.TestCase):
    """FR-21 / FR-24 / T042 -- both sides always, advisory always."""

    def test_both_sides_are_always_present_even_when_null(self):
        finding = F.make_finding(
            F.KIND_DIVERGENCE, F.CLASS_SHIPPED_NOT_WIRED, "x.sh", F.SEVERITY_WARN
        )
        self.assertIn("observed", finding)
        self.assertIn("self_reported", finding)
        self.assertIsNone(finding["self_reported"])

    def test_every_finding_is_advisory(self):
        finding = F.make_finding(
            F.KIND_ABSENCE, F.CLASS_PHASE_SKIPPED, "y", F.SEVERITY_INFO
        )
        self.assertTrue(finding["advisory"])

    def test_the_id_is_a_deterministic_hash_of_kind_class_and_subject(self):
        first = F.finding_id("divergence", "skill_logging_bug", "toolu_1")
        second = F.finding_id("divergence", "skill_logging_bug", "toolu_1")
        third = F.finding_id("divergence", "skill_logging_bug", "toolu_2")
        self.assertEqual(first, second)
        self.assertNotEqual(first, third)
        self.assertEqual(len(first), 16)

    def test_the_reconciliation_window_is_ninety_seconds(self):
        self.assertEqual(F.RECONCILE_WINDOW_S, 90)

    def test_epoch_conversion_rejects_a_bare_clock_time(self):
        """FR-58 -- a `[HH:MM:SS]` stamp can never become an ordering key."""
        self.assertIsNone(F.epoch_of("15:18:22"))
        self.assertIsNone(F.epoch_of(None))
        self.assertIsNotNone(F.epoch_of("2026-09-22T15:18:22Z"))


if __name__ == "__main__":
    unittest.main()
