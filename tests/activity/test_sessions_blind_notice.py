"""The sessions panel must not go silent when the daemon is blind.

Same defect shape as ``test_absence_event_source.py``, one panel over, and it
was equally live. ``sessions.sessions_for`` builds Session records from hook
events, because FR-21's trust hierarchy makes the harness-observed stream the
primary source. Run against a project with no /smith-activity emitter wired
there are ZERO events, therefore ZERO Session records -- and the panel rendered
empty with no notice at all, while ``claude agents --json`` sat there holding
22 live records the whole time.

An empty panel is a lie with the same shape as the truth: it reads as "nothing
is running", which is the one thing it demonstrably does not mean when the poll
can see sessions.

The fix is NOT to fabricate Session records from the poll. A polled record is
``{pid, cwd, kind, name, sessionId, startedAt, status?}`` -- no resolved
worktree, no branch, no permission state, no phase attribution, no usage -- and
promoting a liveness reconciler to a data source is precisely the inversion
FR-21 exists to forbid. ``test_no_sessions_are_fabricated_from_the_poll`` pins
that half.

``RefreshNoticeTests`` is the pair that goes red if the notice is deleted from
``refresh.refresh_project``; the unit cases above it would all still pass,
because each condition would still be individually correct.

Run: ``PYTHONPATH=. python3 tests/activity/test_sessions_blind_notice.py``
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest

from tests._harness import *  # noqa: F401,F403 -- puts scripts/activity on sys.path

import absence as A
import refresh as R
import sessions as S
import state as state_mod

EMITTER_ENTRY = {
    "type": "command",
    "command": "bash ~/.claude/hooks/activity-emitter.sh",
}


def settings_with(include_emitter):
    chain = [
        {"type": "command", "command": "bash ~/.claude/hooks/session-end-review.sh"}
    ]
    if include_emitter:
        chain = chain + [dict(EMITTER_ENTRY)]
    return {"hooks": {"Stop": [{"matcher": "*", "hooks": chain}]}}


# ===========================================================================
# absence.sessions_blind -- the truth table
# ===========================================================================


class SessionsBlindTests(unittest.TestCase):
    def test_no_sessions_no_source_but_poll_sees_them_is_blindness(self):
        self.assertEqual(A.sessions_blind([], 22, True), 22)

    def test_sessions_present_means_the_panel_works(self):
        """Nothing to explain. The notice would be noise over a working panel."""
        self.assertEqual(A.sessions_blind([{"session_id": "s1"}], 22, True), 0)

    def test_quiet_machine_is_not_blindness(self):
        """An empty panel with an empty poll is simply CORRECT.

        Saying "sessions cannot be reported" when there are also no sessions to
        report would manufacture a problem out of a quiet machine -- the same
        confidently-wrong move this whole guard exists to stop.
        """
        self.assertEqual(A.sessions_blind([], 0, True), 0)

    def test_event_source_present_means_empty_is_a_real_observation(self):
        """With a transport wired, an empty panel is a fact about the project.

        The poll's records then belong to other projects, or to sessions the
        T080 reaper legitimately removed. Claiming blindness here would be
        false.
        """
        self.assertEqual(A.sessions_blind([], 22, False), 0)


# ===========================================================================
# The integration cases -- these go red if the notice is removed from
# refresh.refresh_project.
# ===========================================================================


class _StubDaemon(object):
    """The slice of Daemon that refresh_project actually touches."""

    def __init__(self, state, ingested=0):
        self.state = state
        self.state.counters["ingested"] = ingested
        self.log_offsets = {}
        self.log_records = {}
        self.hooks_log_offset = None
        self._seq = 0

    def events_for(self, project):
        return []

    def next_seq(self, count=1):
        self._seq += count
        return self._seq


class RefreshNoticeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="smith-sessions-blind-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

        self.home = os.path.join(self.tmp, "home")
        self.smith_home = os.path.join(self.home, ".smith")
        os.makedirs(os.path.join(self.home, ".claude"))
        os.makedirs(os.path.join(self.smith_home, "logs"))
        os.makedirs(os.path.join(self.smith_home, "activity"))
        open(os.path.join(self.smith_home, "logs", "hooks.log"), "w").close()
        with open(
            os.path.join(self.smith_home, "activity", "shipped-hooks.json"),
            "w",
            encoding="utf-8",
        ) as fh:
            json.dump({"hooks": ["session-end-review.sh"]}, fh)

        # A REAL git repo, because the per-project attribution in
        # refresh_project runs `git worktree list` against it: a polled record
        # is only counted when its cwd sits inside this project's tree. A bare
        # temp directory would make every case count zero and quietly pass.
        self.project = os.path.join(self.tmp, "project")
        os.makedirs(self.project)
        self._git("init", "-q")
        self._git("config", "user.email", "t@example.com")
        self._git("config", "user.name", "T")

        self._env = {k: os.environ.get(k) for k in ("HOME", "SMITH_HOME")}
        os.environ["HOME"] = self.home
        os.environ["SMITH_HOME"] = self.smith_home
        self.addCleanup(self._restore_env)
        self.addCleanup(S.reset_cache)

    def _git(self, *args):
        subprocess.run(
            ["git", "-C", self.project] + list(args),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    def _restore_env(self):
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _write_settings(self, include_emitter):
        path = os.path.join(self.home, ".claude", "settings.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(settings_with(include_emitter), fh)

    def _stub_poll(self, records):
        """Replace `sessions.poll` outright for the duration of one case.

        Seeding `_poll_cache` and relying on the POLL_INTERVAL_S debounce was
        the first version of this, and it is exactly the kind of assertion that
        passes on a quiet machine and fails on a loaded one: if `refresh_project`
        happens to take longer than the debounce, `poll()` re-asks for real,
        shells out to `claude agents --json`, and the test silently starts
        measuring the machine's own live sessions instead of its fixture. A
        stub has no clock in it.
        """
        snapshot = {
            "available": True,
            "by_session": {r["sessionId"]: dict(r) for r in records},
            "any_status": False,
            "at": time.time(),
            "error": None,
        }
        real = S.poll
        S.poll = lambda now=None, runner=None: snapshot
        self.addCleanup(setattr, S, "poll", real)

    def _run(self, include_emitter, records, ingested=0):
        self._write_settings(include_emitter)
        self._stub_poll(records)
        st = state_mod.ActivityState()
        daemon = _StubDaemon(st, ingested=ingested)
        R.refresh_project(daemon, self.project)
        sessions = [entity for _key, entity in st.items("sessions")]
        return sessions, list(st.notices)

    def _in_project(self, count):
        return [
            {"sessionId": "sess-%d" % i, "cwd": self.project, "pid": 1000 + i}
            for i in range(count)
        ]

    def test_blind_panel_names_the_sessions_it_cannot_report(self):
        sessions, notices = self._run(
            include_emitter=False, records=self._in_project(3)
        )
        self.assertEqual(sessions, [], "no events means no Session records")
        blind = [n for n in notices if "Sessions cannot be reported" in n]
        self.assertEqual(
            len(blind),
            1,
            "an empty sessions panel with live polled sessions and no event "
            "source must carry exactly one explanatory notice, got: %r" % (notices,),
        )
        self.assertIn(
            "3 live session(s)",
            blind[0],
            "the notice must name the count the operator can go and verify",
        )

    def test_no_sessions_are_fabricated_from_the_poll(self):
        """The other half of the fix, and the more important one.

        Filling the panel from the poll would make this test's notice
        unnecessary and the dashboard wrong: it would promote a liveness
        reconciler to a primary data source, against FR-21.
        """
        sessions, _notices = self._run(
            include_emitter=False, records=self._in_project(3)
        )
        self.assertEqual(len(sessions), 0)

    def test_wiring_an_event_source_removes_the_notice(self):
        """Scoped to blindness, not a blanket banner.

        With a transport installed, an empty panel is a real observation about
        the project rather than a statement about our own instrumentation.
        """
        _sessions, notices = self._run(
            include_emitter=True, records=self._in_project(3)
        )
        self.assertEqual(
            [n for n in notices if "Sessions cannot be reported" in n],
            [],
            "notice must not fire when an event source is wired",
        )

    def test_quiet_machine_gets_no_notice(self):
        _sessions, notices = self._run(include_emitter=False, records=[])
        self.assertEqual(
            [n for n in notices if "Sessions cannot be reported" in n],
            [],
            "an empty poll means the empty panel is simply correct",
        )

    def test_other_projects_sessions_are_not_claimed_as_ours(self):
        """The poll is machine-wide; this panel is not.

        A record whose cwd is some other repository must not be counted, or
        every project's panel would claim every session on the box.
        """
        elsewhere = [{"sessionId": "other", "cwd": self.tmp, "pid": 999}]
        _sessions, notices = self._run(include_emitter=False, records=elsewhere)
        self.assertEqual(
            [n for n in notices if "Sessions cannot be reported" in n],
            [],
            "a session in another tree is not a session this panel is hiding",
        )


if __name__ == "__main__":
    unittest.main()
