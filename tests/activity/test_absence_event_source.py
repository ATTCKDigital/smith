"""Absence detection must know whether it has an event source at all.

The regression these pin was live. Started against a real project with no
/smith-activity emitter wired, the daemon produced NINE ``hook_never_fired``
warnings -- active-workflow-janitor, grade-response, metrics-tracker,
session-end-review, session-start-logger, stamp-response,
subagent-vault-writeback, user-prompt-logger, workflow-summary -- all of them
technically true and all of them noise. With no transport installed the daemon
was not observing an absence of hook activity; it was observing nothing, and
reporting its own blindness in the grammar of nine accusations about somebody
else's workflow.

FR-23 already says absence detection is disabled with a visible notice, never
guessed, when the SETTINGS cannot be read. These tests hold the same line one
layer down, where the TRANSPORT is what is missing.

The integration cases at the bottom are the ones that go red if the suppression
in ``refresh.refresh_project`` is deleted -- the unit cases above would all
still pass, because each half would still be individually correct.

Run: ``PYTHONPATH=. python3 tests/activity/test_absence_event_source.py``
"""

import json
import os
import shutil
import tempfile
import time
import unittest

from tests._harness import *  # noqa: F401,F403 -- puts scripts/activity on sys.path

import absence as A
import findings as F
import hookset as H
import refresh as R
import state as state_mod

EMITTER_ENTRY = {
    "type": "command",
    "command": "bash ~/.claude/hooks/activity-emitter.sh",
}
NATIVE_ENTRY = {
    "type": "http",
    "url": "http://127.0.0.1:8787/ingest",
    "headers": {"Authorization": "Bearer $SMITH_ACTIVITY_TOKEN"},
}

# Five Stop hooks and a SessionStart hook, none of them the emitter. Every one
# has an empty applicability tuple in absence.HOOK_APPLICABILITY, so all six are
# "expected" in any session -- which is exactly why an unguarded run reports
# them all as never-fired.
ALWAYS_EXPECTED = [
    "session-start-logger.sh",
    "session-end-review.sh",
    "active-workflow-janitor.sh",
    "workflow-summary.sh",
    "stamp-response.sh",
    "grade-response.sh",
]


def settings_with(hook_entries, include_emitter):
    chain = [
        {"type": "command", "command": "bash ~/.claude/hooks/%s" % name}
        for name in hook_entries
    ]
    if include_emitter:
        chain = chain + [dict(EMITTER_ENTRY)]
    return {"hooks": {"Stop": [{"matcher": "*", "hooks": chain}]}}


# ===========================================================================
# hookset.emitter_wired -- both transport spellings
# ===========================================================================


class EmitterWiredTests(unittest.TestCase):
    def test_shell_emitter_is_an_event_source(self):
        settings = {"hooks": {"Stop": [{"matcher": "*", "hooks": [EMITTER_ENTRY]}]}}
        self.assertTrue(H.emitter_wired(settings))

    def test_native_http_entry_is_an_event_source(self):
        """The transport UPGRADE must not read as the transport being gone.

        install-activity-transport.sh rewrites the emitter into a native http
        entry, which carries no `command` and is therefore invisible to
        `wired_hooks()`. Keying the check on the command basename alone would
        declare "no event source" on precisely the machines running the faster
        one.
        """
        settings = {
            "hooks": {"PostToolUse": [{"matcher": "*", "hooks": [NATIVE_ENTRY]}]}
        }
        self.assertTrue(H.emitter_wired(settings))

    def test_other_hooks_are_not_an_event_source(self):
        self.assertFalse(H.emitter_wired(settings_with(ALWAYS_EXPECTED, False)))

    def test_unreadable_settings_are_unknown_not_false(self):
        self.assertIsNone(H.emitter_wired(None))

    def test_unrelated_http_hook_is_not_our_transport(self):
        settings = {
            "hooks": {
                "Stop": [
                    {
                        "matcher": "*",
                        "hooks": [
                            {"type": "http", "url": "https://example.com/webhook"}
                        ],
                    }
                ]
            }
        }
        self.assertFalse(H.emitter_wired(settings))


# ===========================================================================
# absence.event_source_missing -- the truth table
# ===========================================================================


class EventSourceMissingTests(unittest.TestCase):
    def test_no_emitter_and_no_events_is_blind(self):
        self.assertTrue(A.event_source_missing(False, 0))

    def test_events_prove_a_source_exists_whatever_it_is(self):
        """An operator's own forwarder, or a future entry shape we cannot
        recognise, still delivers events. Arrived events outrank our guess."""
        self.assertFalse(A.event_source_missing(False, 1))

    def test_emitter_present_but_quiet_keeps_detection_on(self):
        """The first second of every install. Suppressing here would hide real
        findings for as long as a session happened to be quiet."""
        self.assertFalse(A.event_source_missing(True, 0))

    def test_unreadable_settings_defer_to_fr60(self):
        """FR-60 already disables detection with its own notice. Claiming this
        reason too would put two notices on screen for one cause."""
        self.assertFalse(A.event_source_missing(None, 0))


# ===========================================================================
# The integration cases -- these are the ones that go red if the suppression
# is removed from refresh.refresh_project.
# ===========================================================================


class _StubDaemon(object):
    """The slice of Daemon that refresh_project actually touches."""

    def __init__(self, state, ingested=0):
        self.state = state
        self.state.counters["ingested"] = ingested
        self.log_offsets = {}
        self.log_records = {}
        self.worktree_cache = {}
        self.hooks_log_offset = None
        self._seq = 0

    def events_for(self, project):
        return []

    def next_seq(self, count=1):
        self._seq += count
        return self._seq


class RefreshSuppressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="smith-absence-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

        self.home = os.path.join(self.tmp, "home")
        self.smith_home = os.path.join(self.home, ".smith")
        os.makedirs(os.path.join(self.home, ".claude"))
        os.makedirs(os.path.join(self.smith_home, "logs"))
        os.makedirs(os.path.join(self.smith_home, "activity"))

        # A readable, EMPTY hooks.log: `fired` is an empty set, not None, so
        # the FR-60 "log unreadable" branch is not what is under test here.
        open(os.path.join(self.smith_home, "logs", "hooks.log"), "w").close()

        # A staged shipped-hook manifest listing exactly what the settings
        # wire, so `shipped_not_wired` is empty and the manifest notice is
        # absent -- leaving the notice count a clean measurement.
        with open(
            os.path.join(self.smith_home, "activity", "shipped-hooks.json"),
            "w",
            encoding="utf-8",
        ) as fh:
            json.dump({"hooks": sorted(ALWAYS_EXPECTED)}, fh)

        self.project = os.path.join(self.tmp, "project")
        os.makedirs(self.project)

        self._env = {k: os.environ.get(k) for k in ("HOME", "SMITH_HOME")}
        os.environ["HOME"] = self.home
        os.environ["SMITH_HOME"] = self.smith_home
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _write_settings(self, include_emitter):
        path = os.path.join(self.home, ".claude", "settings.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(settings_with(ALWAYS_EXPECTED, include_emitter), fh)

    def _run(self, include_emitter, ingested=0):
        self._write_settings(include_emitter)
        st = state_mod.ActivityState()
        daemon = _StubDaemon(st, ingested=ingested)
        # Pre-warm the worktree cache so describe() never shells out to git:
        # this test is about findings, not about the git plumbing.
        daemon.worktree_cache[self.project] = (time.time() + 3600, [])
        R.refresh_project(daemon, self.project)
        never_fired = [
            entity
            for _key, entity in st.items("findings")
            if entity.get("classification") == F.CLASS_HOOK_NEVER_FIRED
        ]
        return never_fired, list(st.notices)

    def test_no_event_source_emits_no_findings_and_one_notice(self):
        never_fired, notices = self._run(include_emitter=False)
        self.assertEqual(
            never_fired,
            [],
            "hook_never_fired must be suppressed entirely when the daemon has "
            "no event source; got %d finding(s)" % len(never_fired),
        )
        self.assertEqual(
            len(notices),
            1,
            "exactly one notice should explain the blindness, got: %r" % (notices,),
        )
        self.assertIn("event source", notices[0])

    def test_wiring_an_emitter_brings_the_findings_back(self):
        """The suppression is scoped to blindness, not a blanket mute.

        With a transport installed the daemon can see, so silence from a wired
        and applicable hook is once again a real observation about that hook.
        """
        never_fired, _notices = self._run(include_emitter=True)
        self.assertEqual(
            sorted(f["subject"] for f in never_fired),
            sorted(ALWAYS_EXPECTED),
            "with an event source wired, every wired-and-applicable hook that "
            "did not fire must still be reported",
        )

    def test_events_arriving_without_a_recognised_emitter_keep_detection_on(self):
        never_fired, _notices = self._run(include_emitter=False, ingested=7)
        self.assertEqual(
            sorted(f["subject"] for f in never_fired), sorted(ALWAYS_EXPECTED)
        )

    def test_blindness_does_not_corrupt_shipped_not_wired(self):
        """The guard must not commit the error it exists to prevent.

        Suppressing hook_never_fired by nulling `wired` on the way INTO
        derive_findings also nulls it for shipped_not_wired, where `None` means
        "nothing is wired" instead of "we are not asking" -- turning one honest
        silence into a false accusation against every hook the settings
        demonstrably do wire. Only the hook Smith ships and the settings really
        do not wire may be reported here.
        """
        self._write_settings(include_emitter=False)
        # Manifest lists the emitter too, so it is the one genuine answer.
        with open(
            os.path.join(self.smith_home, "activity", "shipped-hooks.json"),
            "w",
            encoding="utf-8",
        ) as fh:
            json.dump({"hooks": sorted(ALWAYS_EXPECTED + ["activity-emitter.sh"])}, fh)

        st = state_mod.ActivityState()
        daemon = _StubDaemon(st, ingested=0)
        daemon.worktree_cache[self.project] = (time.time() + 3600, [])
        R.refresh_project(daemon, self.project)

        not_wired = sorted(
            entity["subject"]
            for _key, entity in st.items("findings")
            if entity.get("classification") == F.CLASS_SHIPPED_NOT_WIRED
        )
        self.assertEqual(
            not_wired,
            ["activity-emitter.sh"],
            "only the genuinely unwired hook may be reported; the other %d are "
            "wired in the fixture settings" % len(ALWAYS_EXPECTED),
        )


if __name__ == "__main__":
    unittest.main()
