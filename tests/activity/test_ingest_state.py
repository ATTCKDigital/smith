"""Executable guards for the ingest boundary and the coalescing broadcaster
(T084 / T085 / T086).

Run directly:  PYTHONPATH=. python3 tests/activity/test_ingest_state.py
Under the flat suite: tests/smith-activity.test.sh's unittest discovery.

Two of these exist because a manual red-check found the obvious version of the
check to be VACUOUS, and a test that cannot fail proves nothing:

* ``test_canary_never_reaches_the_state_tree`` asserts at the STORAGE boundary,
  not over an ``/api/*`` body. Driving a canary through ``/ingest`` and grepping
  the HTTP surfaces passes today even with redaction removed entirely, because
  no route currently projects a raw ``tool_input`` onto the wire. The invariant
  SC-14 actually cares about is "the unredacted value never reaches the state
  tree", so that is what is asserted, where it can fail.

* ``test_broadcaster_emits_a_floor_as_well_as_a_ceiling`` asserts a FLOOR.
  A ceiling-only assertion cannot tell a well-coalesced stream from a starved
  one: swapping the fixed-interval leaky bucket for a reset-on-every-event
  debounce produced ZERO frames across a 300-event storm and still satisfied
  "at most 5 frames per second". Zero is the failure FR-41 exists to prevent.
"""

import json
import os
import sys
import time
import unittest

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "scripts",
        "activity",
    ),
)

import ingest  # noqa: E402
import state as state_mod  # noqa: E402

CANARY = "ZZ-CANARY-6f2a-ZZ"


def payload(**extra):
    base = {
        "session_id": "sess-1",
        "cwd": "/tmp/project",
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "prompt": CANARY,
        "tool_input": {"command": CANARY},
        "tool_response": CANARY,
    }
    base.update(extra)
    return json.dumps(base).encode("utf-8")


class RedactionAtIngest(unittest.TestCase):
    def test_canary_never_reaches_the_state_tree(self):
        parsed = ingest.parse(payload(), capture_prompts=False)
        record = ingest.envelope(parsed, seq=1, received_at="2026-09-22T00:00:00Z")
        self.assertNotIn(CANARY, json.dumps(record))
        self.assertEqual(record["tool_input"], {"<redacted>": len(CANARY) + 14})
        self.assertEqual(record["tool_response"], "<redacted:%d bytes>" % len(CANARY))
        self.assertEqual(record["prompt"], "<redacted:%d chars>" % len(CANARY))

    def test_lengths_are_retained_because_size_is_an_audit_signal(self):
        small = ingest.parse(payload(tool_input={"c": "x"}), capture_prompts=False)
        large = ingest.parse(
            payload(tool_input={"c": "x" * 40000}), capture_prompts=False
        )
        self.assertLess(
            small["tool_input"]["<redacted>"], large["tool_input"]["<redacted>"]
        )

    def test_identity_fields_are_retained_always(self):
        record = ingest.envelope(
            ingest.parse(payload(tool_use_id="toolu_01X", prompt_id="p1")),
            seq=7,
            received_at="2026-09-22T00:00:00Z",
        )
        for field in (
            "session_id",
            "cwd",
            "hook_event_name",
            "tool_name",
            "tool_use_id",
            "prompt_id",
        ):
            self.assertIn(field, record, field)
        # FR-58: ordering is the daemon's seq, never a parsed timestamp.
        self.assertEqual(record["seq"], 7)

    def test_capture_opt_in_actually_changes_behaviour(self):
        parsed = ingest.parse(payload(), capture_prompts=True)
        self.assertIn(CANARY, json.dumps(parsed))

    def test_secret_shaped_keys_are_redacted_even_with_capture_on(self):
        # Opting in to seeing your own prompts is not opting in to persisting a
        # bearer token to a log file.
        parsed = ingest.parse(
            payload(headers={"Authorization": "Bearer abc", "api_key": "xyz"}),
            capture_prompts=True,
        )
        self.assertEqual(parsed["headers"]["Authorization"], "<redacted>")
        self.assertEqual(parsed["headers"]["api_key"], "<redacted>")

    def test_missing_session_id_is_counted_and_dropped_not_raised(self):
        parsed = ingest.parse(json.dumps({"cwd": "/tmp"}).encode())
        self.assertIsNone(ingest.envelope(parsed, 1, "2026-09-22T00:00:00Z"))

    def test_non_json_and_non_object_bodies_are_dropped(self):
        self.assertIsNone(ingest.parse(b"not json {{{"))
        self.assertIsNone(ingest.parse(b'["a list is not an envelope"]'))
        self.assertIsNone(ingest.parse(b""))


class CoalescingBroadcaster(unittest.TestCase):
    def _storm(self, events=300, gap=0.002):
        st = state_mod.ActivityState()
        bus = state_mod.Broadcaster(st, debounce_ms=state_mod.BROADCAST_DEBOUNCE_MS)
        sub = bus.subscribe()
        bus.start()
        started = time.time()
        for i in range(events):
            st.upsert(
                "sessions",
                "s%d" % (i % 4),
                {"session_id": "s%d" % (i % 4), "project": "/p", "n": i},
            )
            time.sleep(gap)
        time.sleep(0.5)
        bus.stop()
        elapsed = time.time() - started
        frames = []
        while not sub.queue.empty():
            frames.append(sub.queue.get_nowait())
        return frames, elapsed

    def test_a_tool_call_storm_does_not_produce_a_frame_per_call(self):
        frames, elapsed = self._storm()
        ceiling = state_mod.MAX_FRAMES_PER_SECOND * (elapsed + 1.0)
        self.assertLessEqual(
            len(frames),
            ceiling,
            "300 upserts produced %d frames over %.2fs; FR-41 caps this at "
            "%.0f. One SSE frame per tool call is forbidden."
            % (len(frames), elapsed, ceiling),
        )

    def test_broadcaster_emits_a_floor_as_well_as_a_ceiling(self):
        frames, elapsed = self._storm()
        self.assertGreaterEqual(
            len(frames),
            1,
            "no frame at all across a %.2fs storm: the debounce is starving the "
            "stream. A reset-on-every-event timer does exactly this and still "
            "satisfies the ceiling, which is why the floor is asserted too." % elapsed,
        )

    def test_delta_carries_whole_entities_and_absent_keys_mean_unchanged(self):
        st = state_mod.ActivityState()
        st.upsert("sessions", "a", {"session_id": "a", "project": "/p", "v": 1})
        delta = st.drain_delta()
        self.assertIn("sessions", delta)
        self.assertEqual(delta["sessions"]["upsert"][0]["v"], 1)
        # Untouched collections are ABSENT, not empty.
        for other in ("workflows", "worktrees", "findings"):
            self.assertNotIn(other, delta)
        self.assertIsNone(st.drain_delta())

    def test_project_filter_never_reaches_the_quota_block(self):
        st = state_mod.ActivityState()
        st.upsert("sessions", "a", {"session_id": "a", "project": "/p"})
        st.upsert("sessions", "b", {"session_id": "b", "project": "/other"})
        st.set_quota({"available": True, "five_hour": {"used_percentage": 1.0}})
        snap = st.snapshot(project="/p")
        self.assertEqual([s["session_id"] for s in snap["sessions"]], ["a"])
        self.assertTrue(snap["quota"]["available"])

    def test_overflowing_subscriber_gets_one_resync_not_a_backlog(self):
        """A slow tab collapses to a resync; it never accumulates a backlog.

        The queue does NOT end holding only the resync: once it has been
        drained there is room again, so frames that arrive after the overflow
        are queued normally. That is correct — the client re-fetches
        ``/api/state`` on the resync and discards whichever of the two is older
        by ``generation``. What must never happen is unbounded growth, so the
        invariant asserted is "bounded, and the backlog begins with a resync".
        """
        maxsize = 4
        sub = state_mod.Subscriber(maxsize=maxsize)
        for i in range(20):
            sub.put("delta", {"generation": i})
        drained = []
        while not sub.queue.empty():
            drained.append(sub.queue.get_nowait())
        self.assertLessEqual(len(drained), maxsize)
        self.assertEqual(drained[0][0], "resync")
        self.assertEqual(drained[0][1]["reason"], state_mod.RESYNC_QUEUE_OVERFLOW)
        self.assertEqual(sum(1 for event, _ in drained if event == "resync"), 1)
        self.assertGreaterEqual(sub.overflows, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
