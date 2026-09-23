"""FR-56 characterization tests for hooks/workflow_summary_lib.py.

The five existing ``tests/test_*.py`` pin ``normalize``, ``cost_usd``,
``match_family``, ``compute_active_duration`` and the legacy block parser. The
functions THIS feature newly depends on have **zero** coverage, which means
"preserve existing behavior" had nothing to verify against:

``parse_parent_jsonl`` · ``resolve_parent_jsonl`` · ``resolve_workflow_window``
· ``git_files_changed`` · ``format_tokens`` / ``format_usd`` /
``format_duration``

These are CHARACTERIZATION tests: they record what the code does today,
including the parts that are arguably wrong (``resolve_parent_jsonl`` falls
back to the newest transcript even when no cwd matched; ``git_files_changed``
hardcodes ``main``). Where behavior is surprising the test says so rather than
asserting the behavior someone might prefer — changing it is a separate,
deliberate act, and these assertions are what would make that act visible.

That act has since happened once. Feature 60 declared
**`hooks/workflow_summary_lib.py` is never edited** (FR-33/FR-36, D-6) and
this file accordingly PINNED the ``resolve_workflow_window`` date-parsing
defect rather than fixing it. Defect 15 fixed it in a later bugfix, so the
``ResolveWorkflowWindowTest`` assertions below now describe correct behavior
instead of the defect, and ``ParseParentJsonlWindowEndToEndTest`` was added to
prove the window filter actually excludes rows. Everything else here remains
characterization and is still pinned as written.

Reached from CI through the flat tests/smith-activity.test.sh wrapper.

.. warning::

   **On a developer machine this file may test the INSTALLED lib, not this
   checkout.** ``tests/_harness.py`` prepends ``<repo>/hooks`` and its docstring
   claims "nothing here can shadow workflow_summary_lib" — that claim is false.
   ``scripts/activity/usage.py`` carries an import ladder
   (``CLAUDE_HOOKS_DIR`` → ``~/.claude/hooks`` → repo ``hooks/``) which
   ``sys.path.insert(0, ...)``s its winner AHEAD of the harness entry and then
   imports ``workflow_summary_lib``. Under ``unittest discover`` the modules
   that import ``usage`` sort before this one, so by the time
   ``import workflow_summary_lib`` runs here, ``sys.modules`` already holds
   whichever copy that ladder picked — normally ``~/.claude/hooks``.

   CI never notices: there is no ``~/.claude/hooks`` on a runner, so the ladder
   falls through to the repo copy. Locally, run

       CLAUDE_HOOKS_DIR="$PWD/hooks" PYTHONPATH=. python3 -m unittest discover \\
           -s tests/activity -t . -q

   or you will spend an hour debugging failures that are really your installed
   hook disagreeing with your worktree. Running this module ALONE
   (``python3 -m unittest tests.activity.test_summary_lib``) also sidesteps it,
   because nothing imports ``usage`` first.
"""

import contextlib
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from datetime import datetime, timezone

from tests._harness import *  # noqa: F401,F403 — puts hooks/ on sys.path

import workflow_summary_lib as W

TOKENS_DIR = os.path.join(ACTIVITY_FIXTURES_DIR, "tokens")
PARENT = os.path.join(TOKENS_DIR, "parent-session.jsonl")


@contextlib.contextmanager
def pinned_tz(name):
    """Pin the process timezone for the duration of the block.

    Only the FALLBACK window anchor needs this. That anchor is a MODEL-written
    ``/smith-* invocation`` stamp in an unspecified zone, so any assertion that
    touches it is timezone-dependent and has to say which zone it means — an
    assertion written on a UTC-4 laptop would otherwise fail in CI's UTC. The
    preferred ``workflow-start`` anchor is hook-written (``date -u``) and needs
    none of this, which is rather the point of preferring it.
    """
    old = os.environ.get("TZ")
    os.environ["TZ"] = name
    time.tzset()
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()


def git(cwd, *args):
    return subprocess.run(
        ["git"] + list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )


class ParseParentJsonlTest(unittest.TestCase):
    def test_sums_non_sidechain_assistant_rows_and_returns_the_model(self):
        usage, model = W.parse_parent_jsonl(PARENT, None, None)
        self.assertEqual(usage["input_tokens"], 10)
        self.assertEqual(usage["output_tokens"], 2000)
        self.assertEqual(usage["cache_creation_input_tokens"], 14000)
        self.assertEqual(usage["cache_read_input_tokens"], 75000)
        self.assertEqual(model, "claude-opus-5")

    def test_skips_sidechain_rows(self):
        """The behavior FR-36 exists to work around, pinned explicitly."""
        usage, _ = W.parse_parent_jsonl(PARENT, None, None)
        self.assertLess(usage["input_tokens"], 999999)

    def test_malformed_lines_are_skipped_not_fatal(self):
        usage, _ = W.parse_parent_jsonl(PARENT, None, None)
        self.assertIsNotNone(usage)

    def test_window_filters_on_the_row_timestamp(self):
        start = datetime(2026, 9, 22, 15, 3, 0, tzinfo=timezone.utc)
        usage, _ = W.parse_parent_jsonl(PARENT, start, None)
        # Only the 15:04 row survives.
        self.assertEqual(usage["input_tokens"], 6)
        self.assertEqual(usage["output_tokens"], 1400)

    def test_window_with_no_matching_rows_returns_none_usage_but_keeps_model(self):
        start = datetime(2030, 1, 1, tzinfo=timezone.utc)
        usage, model = W.parse_parent_jsonl(PARENT, start, None)
        self.assertIsNone(usage)
        # Surprising but current: the model is captured before the window
        # filter rejects the row, so it survives a zero-row window.
        self.assertIsNone(model)

    def test_missing_path_is_none_none(self):
        self.assertEqual(
            W.parse_parent_jsonl("/nonexistent.jsonl", None, None), (None, None)
        )
        self.assertEqual(W.parse_parent_jsonl("", None, None), (None, None))


class ResolveParentJsonlTest(unittest.TestCase):
    """Slug = project_root with '/' → '-', under ``~/.claude/projects``."""

    SESSION = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="smith-summarylib-")
        self.home = os.path.join(self.tmp, "home")
        self.project = os.path.join(self.tmp, "proj")
        os.makedirs(self.project)
        self.slug = self.project.replace("/", "-")
        self.projects = os.path.join(self.home, ".claude", "projects", self.slug)
        os.makedirs(self.projects)
        self._home = os.environ.get("HOME")
        os.environ["HOME"] = self.home

    def tearDown(self):
        if self._home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._home
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name, text):
        path = os.path.join(self.projects, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_recovers_the_session_id_from_a_sidechain_path_in_the_log(self):
        expected = self._write("%s.jsonl" % self.SESSION, "{}\n")
        log = (
            "### [15:06:00] Subagent invoked: go\n"
            "see /Users/x/.claude/projects/%s/%s/subagents/agent-abc.jsonl\n"
            % (self.slug, self.SESSION)
        )
        self.assertEqual(W.resolve_parent_jsonl(self.project, log), expected)

    def test_falls_back_to_the_transcript_whose_first_user_turn_matches_cwd(self):
        self._write("other.jsonl", '{"type":"user","cwd":"/somewhere/else"}\n')
        mine = self._write("mine.jsonl", '{"type":"user","cwd":"%s"}\n' % self.project)
        self.assertEqual(W.resolve_parent_jsonl(self.project, ""), mine)

    def test_falls_back_to_the_newest_when_no_cwd_matches(self):
        """Current behavior, and a real source of cross-project confusion:
        a non-match does NOT produce None, it produces the newest transcript."""
        old = self._write("old.jsonl", '{"type":"user","cwd":"/elsewhere"}\n')
        new = self._write("new.jsonl", '{"type":"user","cwd":"/elsewhere"}\n')
        os.utime(old, (1, 1))
        os.utime(new, (10_000_000, 10_000_000))
        self.assertEqual(W.resolve_parent_jsonl(self.project, ""), new)

    def test_no_project_dir_is_none(self):
        self.assertIsNone(W.resolve_parent_jsonl("/no/such/project", ""))

    def test_empty_project_dir_is_none(self):
        self.assertIsNone(W.resolve_parent_jsonl(self.project, ""))


class ResolveWorkflowStartTest(unittest.TestCase):
    """``find_workflow_start`` — the authoritative UTC anchor.

    ``scripts/create-active-workflow.sh:229`` writes
    ``### [HH:MM:SS] workflow-start <branch>`` with ``date -u``, so unlike the
    model-written invocation stamp it is genuinely UTC.
    """

    def test_finds_the_stamp(self):
        self.assertEqual(
            W.find_workflow_start("### [00:17:09] workflow-start fix/a\n"), "00:17:09"
        )

    def test_absent_is_none(self):
        self.assertIsNone(W.find_workflow_start("### [00:17:09] User prompt\n"))
        self.assertIsNone(W.find_workflow_start(""))

    def test_first_match_wins_to_pair_with_find_invocation(self):
        """A session log outlives a single workflow and can hold several
        stamps. ``find_invocation`` takes the FIRST ``/smith-*`` entry, so this
        must take the first ``workflow-start`` or the two anchors would
        describe different workflows."""
        log = (
            "### [00:17:09] workflow-start fix/first\n"
            "### [00:52:12] workflow-start fix/second\n"
        )
        self.assertEqual(W.find_workflow_start(log), "00:17:09")

    def test_does_not_match_a_workflow_start_lookalike(self):
        self.assertIsNone(
            W.find_workflow_start("### [00:17:09] workflow-started-early\n")
        )


class ResolveWorkflowWindowTest(unittest.TestCase):
    """Start = the workflow's UTC beginning. End is always ``now``.

    **Defect 15, FIXED, in two parts.**

    *Part one — the date.* This class previously CHARACTERIZED a defect rather
    than asserting correct behavior: the resolver recovered the date with
    ``fn.split("_")[0]``, but every session log the vault writes is named
    ``<user>_<hash>_<YYYY-MM-DD>_<HHMMSS>.md``, so element [0] was the
    USERNAME, ``strptime`` raised, and ``except ValueError`` silently returned
    a ``None`` start. ``parse_parent_jsonl`` skips its lower-bound filter on a
    falsy ``start_utc``, so token attribution was whole-transcript rather than
    workflow-scoped for every real log. The resolver now locates a
    ``YYYY-MM-DD`` token anywhere in the basename (last match wins) rather than
    indexing a fixed position.

    *Part two — the anchor.* Fixing the date parser exposed a second skew: the
    filename date is UTC (``session-start-logger.sh:46`` uses ``date -u``) but
    the ``/smith-* invocation`` stamp is written by the MODEL in local time, so
    combining them and calling the result UTC is off by the machine's offset.
    In a real log the same workflow appears as ``[00:52:12] workflow-start``
    and ``[20:52:19] /smith-bugfix invocation`` — four hours apart. West of UTC
    that made the window too WIDE (harmless overstatement); east of UTC the
    sign flips and real in-workflow tokens get dropped, which for a
    cost-reporting feature is the unacceptable direction. The resolver now
    prefers the hook-written ``workflow-start`` stamp and only falls back to
    the model stamp when there is none.
    """

    #: Reproduces the real vault log: workflow-start (UTC, written first by the
    #: marker helper) and the invocation stamp (model, local) four hours apart.
    WS_LOG = (
        "### [00:17:09] workflow-start fix/session-log-date\n\n"
        "### [20:17:17] /smith-bugfix invocation\n\nsome body\n"
    )

    def test_the_workflow_start_stamp_wins_over_the_invocation_stamp(self):
        """THE SHIP-BLOCKER. The two anchors disagree by four hours in this
        fixture, so the assertion genuinely discriminates between them."""
        start, _ = W.resolve_workflow_window(
            "/v/sessions/dennis-plucinik_ad8161_2026-09-22_203109.md", self.WS_LOG
        )
        # 00:17:09 UTC is EARLIER in the day than the file's own 20:31:09
        # creation stamp, so it belongs to the following UTC day.
        self.assertEqual(start, datetime(2026, 9, 23, 0, 17, 9, tzinfo=timezone.utc))
        # And emphatically NOT the filename-date + invocation-stamp reading.
        self.assertNotEqual(
            start, datetime(2026, 9, 22, 20, 17, 17, tzinfo=timezone.utc)
        )

    def test_a_workflow_start_after_the_file_time_stays_on_the_same_day(self):
        start, _ = W.resolve_workflow_window(
            "/v/sessions/dennis-plucinik_ad8161_2026-09-22_150000.md",
            "### [21:00:00] workflow-start fix/x\n### [17:00:00] /smith-new invocation\n",
        )
        self.assertEqual(start, datetime(2026, 9, 22, 21, 0, 0, tzinfo=timezone.utc))

    def test_the_workflow_start_anchor_is_timezone_independent(self):
        """The whole reason to prefer it: same answer in any process zone."""
        seen = []
        for zone in ("UTC", "America/New_York", "Europe/Berlin", "Pacific/Auckland"):
            with pinned_tz(zone):
                start, _ = W.resolve_workflow_window(
                    "/v/sessions/dennis-plucinik_ad8161_2026-09-22_203109.md",
                    self.WS_LOG,
                )
            seen.append(start)
        self.assertEqual(len(set(seen)), 1, seen)
        self.assertEqual(seen[0], datetime(2026, 9, 23, 0, 17, 9, tzinfo=timezone.utc))

    def test_a_workflow_start_still_needs_an_invocation_line(self):
        """Unchanged contract: no /smith-(new|bugfix|debug) entry, no window.
        ``main`` bails on a markerless log anyway."""
        start, _ = W.resolve_workflow_window(
            "/v/sessions/dennis-plucinik_ad8161_2026-09-22_203109.md",
            "### [00:17:09] workflow-start fix/x\n### [00:20:00] User prompt\n",
        )
        self.assertIsNone(start)

    def test_a_workflow_start_with_no_date_in_the_filename_yields_none(self):
        start, _ = W.resolve_workflow_window(
            "/v/sessions/scratch.md",
            "### [00:17:09] workflow-start fix/x\n### [00:20:00] /smith-new invocation\n",
        )
        self.assertIsNone(start)


class ResolveWorkflowWindowFallbackTest(unittest.TestCase):
    """The FALLBACK anchor: filename date + model-written invocation stamp.

    Used only when no ``workflow-start`` line exists. The stamp's zone is
    unknowable, so the resolver takes the EARLIER of the two readings (as-UTC
    and as-local) — deliberately widening rather than risking a window that
    starts after the real work did. Overstating spend is recoverable;
    silently understating it is not.

    Every assertion here pins a timezone, because the value under test is
    timezone-dependent by construction.
    """

    LOG = "### [14:50:28] /smith-new invocation\n\nsome body\n"

    def setUp(self):
        self._tz = pinned_tz("UTC")
        self._tz.__enter__()

    def tearDown(self):
        self._tz.__exit__(None, None, None)

    def test_west_of_utc_keeps_the_as_utc_reading_which_is_the_earlier_one(self):
        with pinned_tz("America/New_York"):  # UTC-4 in September
            start, _ = W.resolve_workflow_window(
                "/v/sessions/dennis-plucinik_ad8161_2026-09-22_145028.md", self.LOG
            )
        # as-local would be 18:50:28Z, later; the earlier as-UTC reading wins.
        self.assertEqual(start, datetime(2026, 9, 22, 14, 50, 28, tzinfo=timezone.utc))

    def test_east_of_utc_widens_instead_of_narrowing(self):
        """THE SIGN FLIP. Treating a local stamp as UTC here would start the
        window two hours LATE and drop real in-workflow tokens."""
        with pinned_tz("Europe/Berlin"):  # UTC+2 in September
            start, _ = W.resolve_workflow_window(
                "/v/sessions/dennis-plucinik_ad8161_2026-09-22_145028.md", self.LOG
            )
        self.assertEqual(start, datetime(2026, 9, 22, 12, 50, 28, tzinfo=timezone.utc))
        self.assertLess(start, datetime(2026, 9, 22, 14, 50, 28, tzinfo=timezone.utc))

    def test_the_fallback_never_starts_later_than_the_naive_reading(self):
        """The invariant that makes the widening safe, across many zones."""
        naive = datetime(2026, 9, 22, 14, 50, 28, tzinfo=timezone.utc)
        for zone in ("UTC", "America/New_York", "Europe/Berlin", "Pacific/Auckland"):
            with pinned_tz(zone):
                start, _ = W.resolve_workflow_window(
                    "/v/sessions/dennis-plucinik_ad8161_2026-09-22_145028.md", self.LOG
                )
            self.assertIsNotNone(start, zone)
            self.assertLessEqual(start, naive, zone)

    def test_real_session_log_filenames_resolve_correctly(self):
        """THE DEFECT, now fixed. `<user>_<hash>_<date>_<time>.md` is the only
        shape the vault actually produces and it must yield a real start."""
        start, end = W.resolve_workflow_window(
            "/v/sessions/dennis-plucinik_ad8161_2026-09-22_145028.md", self.LOG
        )
        self.assertEqual(start, datetime(2026, 9, 22, 14, 50, 28, tzinfo=timezone.utc))
        self.assertIsNotNone(end)
        self.assertEqual(end.tzinfo, timezone.utc)

    def test_username_containing_underscores_still_resolves(self):
        """Positional indexing is what caused the defect; a username with an
        underscore must not shift the date out from under the parser."""
        start, _ = W.resolve_workflow_window(
            "/v/sessions/dennis_p_smith_ad8161_2026-09-22_145028.md", self.LOG
        )
        self.assertEqual(start, datetime(2026, 9, 22, 14, 50, 28, tzinfo=timezone.utc))

    def test_hash_only_filename_without_a_username_resolves(self):
        start, _ = W.resolve_workflow_window(
            "/v/sessions/ad8161_2026-09-22_145028.md", self.LOG
        )
        self.assertEqual(start, datetime(2026, 9, 22, 14, 50, 28, tzinfo=timezone.utc))

    def test_filename_with_no_date_at_all_yields_a_none_start(self):
        """A genuinely date-free name must still degrade to no window rather
        than raising or inventing one."""
        for name in (
            "/v/sessions/dennis-plucinik_ad8161_nodate_145028.md",
            "/v/sessions/scratch.md",
            "/v/sessions/_.md",
        ):
            start, end = W.resolve_workflow_window(name, self.LOG)
            self.assertIsNone(start, name)
            self.assertIsNotNone(end, name)

    def test_an_impossible_calendar_date_yields_a_none_start(self):
        start, _ = W.resolve_workflow_window(
            "/v/sessions/dennis-plucinik_ad8161_2026-13-45_145028.md", self.LOG
        )
        self.assertIsNone(start)

    def test_date_first_filenames_resolve_correctly(self):
        """The shape the function was written for, which nothing writes."""
        start, end = W.resolve_workflow_window("/v/2026-09-22_145028.md", self.LOG)
        self.assertEqual(start, datetime(2026, 9, 22, 14, 50, 28, tzinfo=timezone.utc))
        self.assertIsNotNone(end)
        self.assertEqual(end.tzinfo, timezone.utc)

    def test_accepts_the_invoked_spelling_too(self):
        start, _ = W.resolve_workflow_window(
            "/v/2026-09-22_145028.md", "### [09:00:00] /smith-bugfix invoked\n"
        )
        self.assertEqual(start.hour, 9)

    def test_no_invocation_line_yields_a_none_start(self):
        start, end = W.resolve_workflow_window(
            "/v/2026-09-22_145028.md", "### [14:50:28] User prompt\n"
        )
        self.assertIsNone(start)
        self.assertIsNotNone(end)

    def test_unparseable_filename_yields_a_none_start(self):
        start, _ = W.resolve_workflow_window("/v/not-a-date.md", self.LOG)
        self.assertIsNone(start)

    def test_smith_build_is_not_an_invocation_keyword(self):
        """Only new|bugfix|debug match — pinned because the phase resolver
        must not assume an invocation line exists for every workflow."""
        start, _ = W.resolve_workflow_window(
            "/v/2026-09-22_145028.md", "### [14:50:28] /smith-build invoked\n"
        )
        self.assertIsNone(start)


class ParseParentJsonlWindowEndToEndTest(unittest.TestCase):
    """Defect 15, end to end: ``resolve_workflow_window`` → ``parse_parent_jsonl``.

    This is the assertion the characterization suite never made. A date parser
    that returns the right ``datetime`` proves nothing on its own — the defect
    mattered because a ``None`` start makes ``parse_parent_jsonl``'s lower
    bound (``if start_utc and ts < start_utc``) short-circuit on the falsy
    value, so NOTHING was ever excluded and every workflow summary attributed
    the whole transcript. These tests run a real vault-shaped filename through
    the resolver and assert the transcript rows actually get filtered.

    ``fixtures/tokens/parent-session.jsonl`` has two countable assistant rows:
    15:01 (in 4 / out 600 / cc 12000 / cr 30000) and 15:04
    (in 6 / out 1400 / cc 2000 / cr 45000). The 15:03 row is a sidechain and
    is skipped regardless of the window.
    """

    NAME = "/v/sessions/dennis-plucinik_ad8161_2026-09-22_%s.md"

    #: A decoy four hours off, matching the real skew. If the resolver ever
    #: regresses to the invocation stamp these tests see 10 input tokens
    #: instead of 6 and fail, so the anchor choice is load-bearing here too.
    DECOY_INVOCATION = "### [11:03:00] /smith-bugfix invocation\n\nbody\n"

    def _window(self, workflow_start, file_hhmmss):
        log = "### [%s] workflow-start fix/x\n\n%s" % (
            workflow_start,
            self.DECOY_INVOCATION,
        )
        return W.resolve_workflow_window(self.NAME % file_hhmmss, log)

    def test_rows_before_the_anchor_are_excluded(self):
        start, end = self._window("15:03:00", "150000")
        self.assertIsNotNone(start)  # the fix; a None start filters nothing
        self.assertEqual(start, datetime(2026, 9, 22, 15, 3, 0, tzinfo=timezone.utc))
        usage, model = W.parse_parent_jsonl(PARENT, start, end)
        self.assertEqual(usage["input_tokens"], 6)
        self.assertEqual(usage["output_tokens"], 1400)
        self.assertEqual(usage["cache_creation_input_tokens"], 2000)
        self.assertEqual(usage["cache_read_input_tokens"], 45000)
        self.assertEqual(model, "claude-opus-5")

    def test_the_window_is_narrower_than_the_whole_file(self):
        """The load-bearing comparison: windowed < unwindowed. Before the fix
        these two were identical for every real session-log filename."""
        start, end = self._window("15:03:00", "150000")
        windowed, _ = W.parse_parent_jsonl(PARENT, start, end)
        whole_file, _ = W.parse_parent_jsonl(PARENT, None, None)
        self.assertEqual(whole_file["input_tokens"], 10)
        self.assertLess(windowed["input_tokens"], whole_file["input_tokens"])
        self.assertLess(windowed["output_tokens"], whole_file["output_tokens"])

    def test_the_anchored_window_is_the_same_in_every_timezone(self):
        """End to end in four zones. The fallback anchor would give four
        different answers here; the hook-written one gives one."""
        seen = set()
        for zone in ("UTC", "America/New_York", "Europe/Berlin", "Pacific/Auckland"):
            with pinned_tz(zone):
                start, end = self._window("15:03:00", "150000")
                usage, _ = W.parse_parent_jsonl(PARENT, start, end)
            seen.add(usage["input_tokens"])
        self.assertEqual(seen, {6})

    def test_rows_at_or_after_the_anchor_are_included(self):
        start, end = self._window("15:00:00", "150000")
        usage, _ = W.parse_parent_jsonl(PARENT, start, end)
        self.assertEqual(usage["input_tokens"], 10)
        self.assertEqual(usage["output_tokens"], 2000)
        self.assertEqual(usage["cache_creation_input_tokens"], 14000)
        self.assertEqual(usage["cache_read_input_tokens"], 75000)

    def test_a_window_that_starts_after_every_row_yields_no_usage(self):
        start, end = self._window("23:59:59", "235959")
        usage, _ = W.parse_parent_jsonl(PARENT, start, end)
        self.assertIsNone(usage)

    def test_the_end_bound_excludes_later_rows(self):
        start, _ = self._window("15:00:00", "150000")
        end = datetime(2026, 9, 22, 15, 2, 0, tzinfo=timezone.utc)
        usage, _ = W.parse_parent_jsonl(PARENT, start, end)
        self.assertEqual(usage["input_tokens"], 4)
        self.assertEqual(usage["output_tokens"], 600)


class GitFilesChangedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="smith-summarylib-git-")
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "T")
        with open(os.path.join(self.repo, "base.txt"), "w") as fh:
            fh.write("base\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "base")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_lists_files_changed_against_main(self):
        git(self.repo, "checkout", "-q", "-b", "feature")
        with open(os.path.join(self.repo, "added.txt"), "w") as fh:
            fh.write("new\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "add")
        self.assertEqual(W.git_files_changed(self.repo), ["added.txt"])

    def test_on_main_itself_the_diff_is_empty(self):
        self.assertEqual(W.git_files_changed(self.repo), [])

    def test_non_repo_returns_empty_not_an_exception(self):
        self.assertEqual(W.git_files_changed(self.tmp), [])

    def test_missing_path_returns_empty(self):
        self.assertEqual(W.git_files_changed("/no/such/dir"), [])

    def test_base_branch_is_hardcoded_to_main(self):
        """Pinned deliberately: a repo whose default branch is `master`
        silently reports zero changed files rather than failing."""
        other = os.path.join(self.tmp, "master-repo")
        os.makedirs(other)
        git(other, "init", "-q", "-b", "master")
        git(other, "config", "user.email", "t@example.com")
        git(other, "config", "user.name", "T")
        with open(os.path.join(other, "f.txt"), "w") as fh:
            fh.write("x\n")
        git(other, "add", "-A")
        git(other, "commit", "-qm", "c")
        self.assertEqual(W.git_files_changed(other), [])


class FormatterTest(unittest.TestCase):
    """The three renderers, at every documented boundary."""

    def test_format_tokens(self):
        self.assertEqual(W.format_tokens(0), "0")
        self.assertEqual(W.format_tokens(1248), "1,248")
        self.assertEqual(W.format_tokens(9999), "9,999")
        self.assertEqual(W.format_tokens(10_000), "10.0K")
        self.assertEqual(W.format_tokens(842_100), "842.1K")
        self.assertEqual(W.format_tokens(999_999), "1000.0K")
        self.assertEqual(W.format_tokens(1_000_000), "1.0M")
        self.assertEqual(W.format_tokens(3_200_000), "3.2M")
        # Negatives clamp to zero rather than rendering "-1".
        self.assertEqual(W.format_tokens(-1), "0")

    def test_format_usd(self):
        self.assertEqual(W.format_usd(0), "$0.00 USD")
        self.assertEqual(W.format_usd(0.17505), "$0.18 USD")
        self.assertEqual(W.format_usd(1234.5), "$1,234.50 USD")

    def test_format_duration(self):
        self.assertEqual(W.format_duration(0), "0s")
        self.assertEqual(W.format_duration(42), "42s")
        self.assertEqual(W.format_duration(59), "59s")
        self.assertEqual(W.format_duration(60), "1m00s")
        self.assertEqual(W.format_duration(724), "12m04s")
        self.assertEqual(W.format_duration(3935), "1h5m35s")
        self.assertEqual(W.format_duration(-5), "0s")


if __name__ == "__main__":
    unittest.main()
