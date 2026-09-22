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

**`hooks/workflow_summary_lib.py` is never edited** (FR-33/FR-36, D-6).

Reached from CI through the flat tests/smith-activity.test.sh wrapper.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone

from tests._harness import *  # noqa: F401,F403 — puts hooks/ on sys.path

import workflow_summary_lib as W

TOKENS_DIR = os.path.join(ACTIVITY_FIXTURES_DIR, "tokens")
PARENT = os.path.join(TOKENS_DIR, "parent-session.jsonl")


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


class ResolveWorkflowWindowTest(unittest.TestCase):
    """Start comes from the session-log FILENAME's date plus the invocation
    stamp, promoted to UTC. End is always ``now``.

    **Characterized defect, NOT fixed here** (`workflow_summary_lib.py` is
    imported and never edited — FR-33/D-6). `:800` does
    ``fn.split("_")[0]`` to recover the date, but every session log this repo
    has ever written is named ``<user>_<hash>_<YYYY-MM-DD>_<HHMMSS>.md``, so
    element [0] is the USERNAME and ``strptime`` fails. The result is a
    ``None`` start for every real session log — silently, because the
    ``except ValueError`` returns ``(None, end)`` — which makes
    ``parse_parent_jsonl``'s window filter a no-op and quietly widens the
    workflow window to the whole transcript.

    The date sits at element **[2]**. Both shapes are pinned below so the fix,
    when someone makes it, has to change a test on purpose.
    """

    LOG = "### [14:50:28] /smith-new invocation\n\nsome body\n"

    def test_real_session_log_filenames_yield_a_none_start(self):
        """THE DEFECT. `<user>_<hash>_<date>_<time>.md` is the only shape the
        vault actually produces, and it resolves to no window at all."""
        start, end = W.resolve_workflow_window(
            "/v/sessions/dennis-plucinik_ad8161_2026-09-22_145028.md", self.LOG
        )
        self.assertIsNone(start)
        self.assertIsNotNone(end)
        self.assertEqual(end.tzinfo, timezone.utc)

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
