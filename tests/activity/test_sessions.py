"""sessions.py — the US-6 acceptance set (T083).

A synthetic hook stream plus a canned ``claude agents --json`` payload, which
is the only honest way to test this module: the poll is a subprocess against a
binary that may not be installed, and the three behaviours that matter
(reaping, corroborating, degrading) are all about what happens when the poll
says less than you wish it did.

The payload here is the REAL observed shape,
``{pid, cwd, kind, name, sessionId, startedAt, status?}``. It deliberately
does not carry ``waitingFor``, ``state`` or ``id``, because those appear in
zero of 23 live records — and ``test_the_module_never_reads_the_fields_that_
do_not_exist`` fails if anyone adds a read of them later. A fixture that
supplied them would let such a read pass its own test forever while being
wrong on every real machine.

Reached from CI through the flat tests/smith-activity.test.sh wrapper.
"""

import json
import os
import shutil
import tempfile
import time
import unittest

from tests._harness import *  # noqa: F401,F403 — puts scripts/activity on sys.path

import findings as F
import paths
import sessions as S

NOW = 1_800_000_000.0


def stamp(offset_s=0.0):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW + offset_s))


def event(session_id, name, **extra):
    record = {
        "session_id": session_id,
        "hook_event_name": name,
        "timestamp": stamp(-1),
        "cwd": "/tmp/project",
        "kind": "hook_event",
    }
    record.update(extra)
    return record


def agent(session_id, **extra):
    """One polled record in the observed shape. No waitingFor/state/id."""
    record = {
        "pid": 4242,
        "cwd": "/tmp/project",
        "kind": "interactive",
        "name": "claude",
        "sessionId": session_id,
        "startedAt": int((NOW - 300) * 1000),
    }
    record.update(extra)
    return record


def snapshot(records, available=True):
    """Build a poll snapshot without running a subprocess."""
    S.reset_cache()
    return S.poll(now=NOW, runner=lambda: {"available": available, "records": records})


class PollShapeTest(unittest.TestCase):
    def setUp(self):
        S.reset_cache()

    def tearDown(self):
        S.reset_cache()

    def test_the_module_never_reads_the_fields_that_do_not_exist(self):
        """`waitingFor`, `state` and `id` are absent from every observed
        record. A read of them is not a harmless defensive default — it is a
        panel built on a field that is never there, which renders blank on
        every real machine while passing any test that invents one."""
        with open(os.path.join(ACTIVITY_DIR, "sessions.py"), encoding="utf-8") as fh:
            source = fh.read()
        for banned in ('"waitingFor"', "'waitingFor'"):
            self.assertNotIn(banned, source)
        self.assertEqual(
            S.POLLED_FIELDS,
            ("pid", "cwd", "kind", "name", "sessionId", "startedAt", "status"),
        )

    def test_only_the_observed_fields_survive_the_poll(self):
        """A record carrying an unexpected key is not passed through whole."""
        snap = snapshot([agent("s1", waitingFor="a-tool", state="blocked", id="x")])
        kept = snap["by_session"]["s1"]
        self.assertEqual(
            sorted(kept), ["cwd", "kind", "name", "pid", "sessionId", "startedAt"]
        )

    def test_an_unavailable_poll_is_not_an_empty_poll(self):
        snap = snapshot([], available=False)
        self.assertFalse(snap["available"])
        self.assertIn(S.DEGRADED_ABSENT, S.degraded_tokens())

    def test_records_without_status_raise_the_no_status_token(self):
        snapshot([agent("s1"), agent("s2")])
        self.assertIn(S.DEGRADED_NO_STATUS, S.degraded_tokens())
        self.assertNotIn(S.DEGRADED_ABSENT, S.degraded_tokens())

    def test_an_empty_but_working_poll_is_not_degraded(self):
        """Zero records carry no status because they carry nothing. Calling
        that a capability gap would put a permanent warning on an idle
        machine."""
        snapshot([])
        self.assertEqual(S.degraded_tokens(), [])

    def test_a_status_bearing_record_clears_the_no_status_token(self):
        snapshot([agent("s1", status="busy")])
        self.assertEqual(S.degraded_tokens(), [])

    def test_the_poll_is_debounced(self):
        calls = []

        def runner():
            calls.append(1)
            return {"available": True, "records": []}

        S.reset_cache()
        S.poll(now=NOW, runner=runner)
        S.poll(now=NOW + S.POLL_INTERVAL_S / 2, runner=runner)
        self.assertEqual(len(calls), 1)
        S.poll(now=NOW + S.POLL_INTERVAL_S + 1, runner=runner)
        self.assertEqual(len(calls), 2)

    def test_a_missing_claude_binary_is_reported_not_raised(self):
        """The real subprocess, against a command that does not exist."""
        S.reset_cache()
        result = S.poll(now=NOW, runner=lambda: S._run_agents_json())
        # `claude` may or may not be installed on the machine running this.
        # Either answer is fine; raising is not, and an "available" answer
        # must still be well-formed.
        self.assertIn(result["available"], (True, False))
        self.assertIsInstance(result["by_session"], dict)


class SessionStateTest(unittest.TestCase):
    """US-6: three sessions, one of them blocked on a permission prompt."""

    def setUp(self):
        S.reset_cache()
        self.project = tempfile.mkdtemp(prefix="smith-sessions-")

    def tearDown(self):
        shutil.rmtree(self.project, ignore_errors=True)
        S.reset_cache()

    def _events(self):
        return [
            event("s-working", "PostToolUse", tool_name="Bash"),
            event("s-idle", "PostToolUse", tool_name="Read", timestamp=stamp(-600)),
            event(
                "s-blocked",
                "PermissionRequest",
                tool_name="Bash",
                tool_use_id="toolu_1",
            ),
        ]

    def _run(self, records=(), available=True):
        snap = snapshot(list(records), available=available)
        return {
            s["session_id"]: s
            for s in S.sessions_for(
                self.project, self._events(), now=NOW, snapshot=snap
            )
        }

    def test_three_sessions_with_one_blocked_on_permission(self):
        found = self._run([agent("s-working"), agent("s-idle"), agent("s-blocked")])
        self.assertEqual(sorted(found), ["s-blocked", "s-idle", "s-working"])
        self.assertEqual(found["s-blocked"]["state"], S.STATE_WAITING_PERMISSION)
        self.assertEqual(found["s-working"]["state"], S.STATE_WORKING)
        self.assertEqual(found["s-idle"]["state"], S.STATE_IDLE)

    def test_the_blocked_state_is_event_derived_not_polled(self):
        """FR-21/questions.md Q1-C. The hook stream decides; the poll does
        not get a vote, even when it has an opinion."""
        found = self._run([agent("s-blocked", status="busy")])
        self.assertEqual(found["s-blocked"]["state"], S.STATE_WAITING_PERMISSION)
        self.assertTrue(found["s-blocked"]["permission"]["waiting"])

    def test_a_resolved_permission_request_is_no_longer_waiting(self):
        events = [
            event("s1", "PermissionRequest", tool_name="Bash", tool_use_id="t1"),
            event("s1", "PostToolUse", tool_name="Bash", tool_use_id="t1"),
        ]
        snap = snapshot([agent("s1")])
        found = S.sessions_for(self.project, events, now=NOW, snapshot=snap)
        self.assertEqual(found[0]["state"], S.STATE_WORKING)

    def test_status_busy_beats_the_recency_fallback(self):
        """data-model.md §2.2 row 2: `status == "busy"`, ELSE recency."""
        events = [event("s1", "PostToolUse", timestamp=stamp(-600))]
        snap = snapshot([agent("s1", status="busy")])
        found = S.sessions_for(self.project, events, now=NOW, snapshot=snap)
        self.assertEqual(found[0]["state"], S.STATE_WORKING)

    def test_started_at_uses_the_polled_epoch_milliseconds(self):
        found = self._run([agent("s-working")])
        self.assertEqual(found["s-working"]["started_at"], stamp(-300))

    def test_a_nonsense_started_at_does_not_become_1970(self):
        found = self._run([agent("s-working", startedAt="not-a-number")])
        self.assertEqual(found["s-working"]["started_at"], stamp(-1))

    def test_a_session_that_fired_session_end_is_dropped(self):
        events = [
            event("s1", "PostToolUse"),
            event("s1", "SessionEnd"),
        ]
        snap = snapshot([agent("s1")])
        self.assertEqual(
            S.sessions_for(self.project, events, now=NOW, snapshot=snap), []
        )


class ReaperTest(unittest.TestCase):
    """T080 / US-6 scenario 4: a session that died without saying so."""

    def setUp(self):
        S.reset_cache()
        self.project = tempfile.mkdtemp(prefix="smith-reaper-")
        self.events = [
            event("s-alive", "PostToolUse"),
            event("s-dead", "PostToolUse"),
        ]

    def tearDown(self):
        shutil.rmtree(self.project, ignore_errors=True)
        S.reset_cache()

    def _ids(self, snap):
        return sorted(
            s["session_id"]
            for s in S.sessions_for(self.project, self.events, now=NOW, snapshot=snap)
        )

    def test_a_session_absent_from_the_poll_is_reaped(self):
        """No SessionEnd was ever fired. The absence of an event is not an
        event, so only the poll can notice — which is the entire reason the
        poll exists."""
        self.assertEqual(self._ids(snapshot([agent("s-alive")])), ["s-alive"])

    def test_a_session_still_in_the_poll_survives(self):
        both = snapshot([agent("s-alive"), agent("s-dead")])
        self.assertEqual(self._ids(both), ["s-alive", "s-dead"])

    def test_a_failed_poll_disables_the_reaper_entirely(self):
        """**The red-check that matters.** "We could not ask" and "nothing is
        running" have the same shape. Reaping on the first empties the whole
        panel every time `claude` is not on PATH — turning a missing binary
        into "you have no sessions"."""
        self.assertEqual(
            self._ids(snapshot([], available=False)), ["s-alive", "s-dead"]
        )

    def test_a_session_newer_than_the_poll_is_not_reaped(self):
        """A session that started after the snapshot was taken has not been
        looked for yet. Reaping it would make every brand-new session flicker
        out for one poll interval."""
        snap = snapshot([])
        snap = dict(snap, at=NOW - 3600)  # the poll is an hour stale
        self.assertEqual(self._ids(snap), ["s-alive", "s-dead"])


class CorroborationTest(unittest.TestCase):
    """T081 / FR-57 — the comparison, and the silence when there is nothing
    to compare."""

    def setUp(self):
        S.reset_cache()
        self.project = tempfile.mkdtemp(prefix="smith-fr57-")

    def tearDown(self):
        shutil.rmtree(self.project, ignore_errors=True)
        S.reset_cache()

    def _sessions(self, records):
        events = [
            event("s1", "PermissionRequest", tool_name="Bash", tool_use_id="t1"),
        ]
        snap = snapshot(list(records))
        return S.sessions_for(self.project, events, now=NOW, snapshot=snap)

    def test_a_disagreeing_status_produces_exactly_one_finding(self):
        """Events say waiting; the poll says busy. That is the divergence
        FR-57 is for, and it is surfaced rather than silently resolved in
        either direction."""
        sessions = self._sessions([agent("s1", status="busy")])
        self.assertEqual(sessions[0]["status"], "busy")
        self.assertTrue(sessions[0]["corroborated"])
        found = F.permission_disagreement_findings(sessions)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["classification"], F.CLASS_PERMISSION_DISAGREEMENT)
        # BOTH sides are carried, and the hook-derived one is the observation.
        self.assertIn("waiting on permission", found[0]["observed"])
        self.assertIn("busy", found[0]["self_reported"])

    def test_a_record_with_no_status_produces_no_comparison(self):
        """Absence of corroboration is not disagreement. 17 of 23 observed
        records carry no `status`; manufacturing a finding for each would
        bury the six that mean something."""
        sessions = self._sessions([agent("s1")])
        self.assertIsNone(sessions[0]["status"])
        self.assertFalse(sessions[0]["corroborated"])
        self.assertEqual(F.permission_disagreement_findings(sessions), [])

    def test_an_agreeing_status_produces_no_finding(self):
        sessions = self._sessions([agent("s1", status="blocked")])
        self.assertEqual(F.permission_disagreement_findings(sessions), [])

    def test_an_unrecognised_status_produces_no_finding(self):
        """A value whose meaning is unknown cannot disagree with anything."""
        sessions = self._sessions([agent("s1", status="wobbling")])
        self.assertEqual(F.permission_disagreement_findings(sessions), [])


class SubagentAssemblyTest(unittest.TestCase):
    """T082 / FR-27 — two running subagents, each with type, description and
    elapsed time."""

    def setUp(self):
        S.reset_cache()
        self.tmp = tempfile.mkdtemp(prefix="smith-subagents-")
        self.project = os.path.join(self.tmp, "project")
        os.makedirs(self.project)
        self._real_home = paths.claude_home
        paths.claude_home = lambda: os.path.join(self.tmp, "claude")
        self.session_id = "s1"
        self.dir = paths.subagents_dir(self.project, self.session_id)
        os.makedirs(self.dir)

    def tearDown(self):
        paths.claude_home = self._real_home
        shutil.rmtree(self.tmp, ignore_errors=True)
        S.reset_cache()

    def _sidecar(self, agent_id, agent_type, description, tool_use_id):
        path = os.path.join(self.dir, "agent-%s.meta.json" % agent_id)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "agentType": agent_type,
                    "description": description,
                    "toolUseId": tool_use_id,
                    "parentAgentId": "parent",
                    "spawnDepth": 2,
                    "requestShape": "background",
                },
                fh,
            )
        return path

    def test_two_running_subagents_carry_type_description_and_elapsed(self):
        self._sidecar("a1", "Explore", "Investigate markers", "toolu_1")
        self._sidecar("a2", "general-purpose", "Write the tests", "toolu_2")
        events = [
            event("s1", "PreToolUse", tool_name="Task", tool_use_id="toolu_1"),
            event("s1", "PreToolUse", tool_name="Task", tool_use_id="toolu_2"),
        ]
        records = S.subagents_for(
            self.project, events, [{"session_id": "s1"}], now=time.time()
        )
        by_type = {r["agent_type"]: r for r in records}
        self.assertEqual(sorted(by_type), ["Explore", "general-purpose"])
        for record in records:
            self.assertTrue(record["description"])
            self.assertIsNotNone(record["elapsed_s"])
            self.assertGreaterEqual(record["elapsed_s"], 0.0)
            self.assertEqual(record["source"], "sidecar")
            self.assertTrue(record["dispatch_seen"])

    def test_a_dispatch_with_no_sidecar_yet_still_appears(self):
        """The third tier. The sidecar is written at dispatch, but "at
        dispatch" and "before the next poll" are not the same instant, and a
        subagent invisible for its first second is a panel that flickers."""
        events = [
            event("s1", "PreToolUse", tool_name="Task", tool_use_id="toolu_9"),
        ]
        records = S.subagents_for(self.project, events, [{"session_id": "s1"}], now=NOW)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["source"], "dispatch")
        self.assertEqual(records[0]["tool_use_id"], "toolu_9")
        self.assertIsNone(records[0]["agent_id"])
        self.assertIsNotNone(records[0]["elapsed_s"])

    def test_a_sidecar_is_not_double_counted_with_its_dispatch(self):
        """Correlation is on `toolUseId`. Positional pairing is the
        alternative and it is wrong the moment two agents are in flight."""
        self._sidecar("a1", "Explore", "Investigate", "toolu_1")
        events = [
            event("s1", "PreToolUse", tool_name="Task", tool_use_id="toolu_1"),
        ]
        records = S.subagents_for(
            self.project, events, [{"session_id": "s1"}], now=time.time()
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["source"], "sidecar")

    def test_a_redacted_tool_input_yields_no_invented_description(self):
        """With FR-48 capture off — the default — ingest has already replaced
        tool_input with a length placeholder. None is the honest answer."""
        events = [
            event(
                "s1",
                "PreToolUse",
                tool_name="Task",
                tool_use_id="toolu_9",
                tool_input={"<redacted>": 412},
            ),
        ]
        records = S.subagents_for(self.project, events, [{"session_id": "s1"}], now=NOW)
        self.assertIsNone(records[0]["description"])

    def test_non_task_tool_calls_are_not_subagents(self):
        events = [
            event("s1", "PreToolUse", tool_name="Bash", tool_use_id="toolu_b"),
            event("s1", "PostToolUse", tool_name="Task", tool_use_id="toolu_p"),
        ]
        self.assertEqual(
            S.subagents_for(self.project, events, [{"session_id": "s1"}], now=NOW), []
        )


if __name__ == "__main__":
    unittest.main()
