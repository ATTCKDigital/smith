"""markers.py — dual-vault enumeration and the tolerant marker read.

The load-bearing contract here is the one research.md §Q6 got wrong and
plan.md / spec.md FR-17 corrected: for a single branch a ``smith-new`` marker
lives in the primary repo's vault while a ``smith-build`` marker lives in the
worktree's vault, simultaneously, and the worktree one's ``session_log:`` is
empty.

Every fixture below is a real git repo with a real linked worktree, built in a
temp dir, because the whole behavior under test is about where git puts things.

Reached from CI through the flat tests/smith-activity.test.sh wrapper.
"""

import os
import shutil
import subprocess
import tempfile
import unittest

from tests._harness import *  # noqa: F401,F403 — puts scripts/activity on sys.path

import markers as M

PRIMARY_MARKER = """\
workflow: smith-new
feature: activity-dashboard
branch: 60-activity-dashboard
worktree: /tmp/smith-activity-dashboard
session_log: {session_log}
started: 2026-09-22T15:18:00Z
"""

# `session_log:` carries a TRAILING SPACE and nothing after it. That is not a
# typo: it is the exact shape create-active-workflow.sh:170-174 writes from
# inside a worktree, where .smith/vault/.current-session does not exist. The
# space is spelled \x20 so no formatter can quietly strip the thing under test.
WORKTREE_MARKER = (
    "workflow: smith-build\n"
    "feature: activity-dashboard\n"
    "branch: 60-activity-dashboard\n"
    "worktree: {worktree}\n"
    "session_log:\x20\n"
    "started: 2026-09-22T16:29:58Z\n"
)

# skills/smith-finish/SKILL.md:76-84 hand-writes this: four fields, no
# worktree:, no session_log:, and no trailing Z on started:.
FINISH_MARKER = """\
workflow: smith-finish
feature: session-finish
branch: 60-activity-dashboard
started: 2026-09-22T17:02:11
"""

QUOTED_MARKER = """\
workflow: "smith-bugfix"
feature: 'log-quoting'
branch: "fix/log"
worktree: "/tmp/smith-fix-log"
session_log: "/tmp/does-not-exist/session.md"
started: "2026-09-22T18:00:00Z"
phase: "smith-bugfix:3"
"""


def _git(cwd, *args):
    subprocess.run(
        ["git", "-C", cwd] + list(args),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class MarkerParseTests(unittest.TestCase):
    """data-model.md §4.1 — the shapes a marker actually takes."""

    def test_plain_six_field_marker(self):
        fields = M.parse_marker_text(PRIMARY_MARKER.format(session_log="/a/b.md"))
        self.assertEqual(fields["workflow"], "smith-new")
        self.assertEqual(fields["feature"], "activity-dashboard")
        self.assertEqual(fields["branch"], "60-activity-dashboard")
        self.assertEqual(fields["session_log"], "/a/b.md")
        # started: carries three more colons; splitting on the first is the
        # only thing that keeps it intact.
        self.assertEqual(fields["started"], "2026-09-22T15:18:00Z")

    def test_quoted_values_are_unquoted(self):
        fields = M.parse_marker_text(QUOTED_MARKER)
        self.assertEqual(fields["workflow"], "smith-bugfix")
        self.assertEqual(fields["feature"], "log-quoting")
        self.assertEqual(fields["branch"], "fix/log")
        self.assertEqual(fields["worktree"], "/tmp/smith-fix-log")
        self.assertEqual(fields["started"], "2026-09-22T18:00:00Z")

    def test_empty_session_log_is_present_but_empty(self):
        text = WORKTREE_MARKER.format(worktree="/tmp/wt")
        # Guard the fixture itself: the trailing space is the shape under test.
        self.assertIn("session_log: \n", text)
        fields = M.parse_marker_text(text)
        # Present-but-empty and absent are different facts.
        self.assertIn("session_log", fields)
        self.assertEqual(fields["session_log"], "")

    def test_finish_variant_has_four_fields(self):
        fields = M.parse_marker_text(FINISH_MARKER)
        self.assertEqual(fields["workflow"], "smith-finish")
        self.assertNotIn("worktree", fields)
        self.assertNotIn("session_log", fields)

    def test_started_tolerates_missing_trailing_z(self):
        self.assertEqual(
            M.normalize_started("2026-09-22T17:02:11"), "2026-09-22T17:02:11Z"
        )
        self.assertEqual(
            M.normalize_started("2026-09-22T17:02:11Z"), "2026-09-22T17:02:11Z"
        )
        self.assertIsNone(M.normalize_started(""))
        self.assertIsNone(M.normalize_started(None))

    def test_filename_mapping(self):
        # [^A-Za-z0-9._-] → '-'
        self.assertEqual(M.marker_filename_for_branch("fix/log"), "fix-log.yaml")
        self.assertEqual(
            M.marker_filename_for_branch("60-activity-dashboard"),
            "60-activity-dashboard.yaml",
        )
        self.assertEqual(M.marker_filename_for_branch("feat/a b"), "feat-a-b.yaml")

    def test_branch_need_not_name_a_real_ref(self):
        # debug-<slug> (smith-debug/SKILL.md:96-104) and /smith-audit's
        # synthetic labels never exist as git refs.
        fields = M.parse_marker_text(
            "workflow: smith-debug\nbranch: debug-flaky-hook\n"
        )
        self.assertEqual(fields["branch"], "debug-flaky-hook")


class DualVaultEnumerationTests(unittest.TestCase):
    """Binding constraint 10 — two concurrent markers, two vaults, one branch."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="smith-activity-markers.")
        cls.primary = os.path.join(cls.tmp, "primary")
        # Deliberately OUTSIDE the primary tree, as /smith-new places it.
        cls.worktree = os.path.join(cls.tmp, "wt", "smith-activity-dashboard")
        os.makedirs(cls.primary)
        _git(cls.primary, "init", "-q")
        _git(cls.primary, "config", "user.email", "test@example.com")
        _git(cls.primary, "config", "user.name", "test")
        _git(cls.primary, "config", "commit.gpgsign", "false")
        _write(os.path.join(cls.primary, "README.md"), "seed\n")
        _git(cls.primary, "add", "-A")
        _git(cls.primary, "commit", "-qm", "seed")
        os.makedirs(os.path.dirname(cls.worktree), exist_ok=True)
        _git(
            cls.primary,
            "worktree",
            "add",
            "-q",
            "-b",
            "60-activity-dashboard",
            cls.worktree,
        )

        # The primary vault: a real session log plus the .current-session
        # pointer the worktree marker will have to fall back to.
        cls.session_log = os.path.join(
            cls.primary,
            ".smith",
            "vault",
            "sessions",
            "dennis-plucinik_ad8161_2026-09-22_145028.md",
        )
        _write(cls.session_log, "# session\n")
        _write(
            os.path.join(cls.primary, ".smith", "vault", ".current-session"),
            cls.session_log + "\n",
        )

        # Marker 1 — primary vault, workflow: smith-new.
        _write(
            os.path.join(
                cls.primary,
                ".smith",
                "vault",
                "active-workflows",
                "60-activity-dashboard.yaml",
            ),
            PRIMARY_MARKER.format(session_log=cls.session_log),
        )
        # Marker 2 — worktree vault, workflow: smith-build, SAME branch,
        # EMPTY session_log. This is the one a single-vault enumeration misses.
        _write(
            os.path.join(
                cls.worktree,
                ".smith",
                "vault",
                "active-workflows",
                "60-activity-dashboard.yaml",
            ),
            WORKTREE_MARKER.format(worktree=cls.worktree),
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_vault_roots_include_primary_and_worktree(self):
        for start in (self.primary, self.worktree):
            roots = {os.path.realpath(r) for r in M.vault_roots(start)}
            self.assertIn(os.path.realpath(self.primary), roots)
            self.assertIn(os.path.realpath(self.worktree), roots)

    def test_enumeration_finds_both_markers_from_either_position(self):
        for start in (self.primary, self.worktree):
            records = M.enumerate_markers(start)
            workflows = sorted(r["workflow_type"] for r in records)
            self.assertEqual(
                workflows,
                ["smith-build", "smith-new"],
                "enumerating from %s missed a vault" % start,
            )

    def test_both_markers_key_to_the_one_primary_repo(self):
        records = M.enumerate_markers(self.worktree)
        projects = {os.path.realpath(r["project"]) for r in records}
        # A worktree never registers as a second project (FR-28/SC-7).
        self.assertEqual(projects, {os.path.realpath(self.primary)})

    def test_records_are_keyed_by_project_and_filename(self):
        records = M.enumerate_markers(self.primary)
        # Same branch, same filename, two vaults — so the key alone cannot
        # separate them, which is why vault_root is carried on the record.
        self.assertEqual(
            {r["marker_filename"] for r in records}, {"60-activity-dashboard.yaml"}
        )
        self.assertEqual(len({r["vault_root"] for r in records}), 2)
        for record in records:
            self.assertTrue(record["key"].endswith("|60-activity-dashboard.yaml"))
        # ...so the key must carry the vault too, or the two markers of one
        # nest collide. data-model.md §2.4's (project, filename) is one
        # component short; see markers.read_marker.
        self.assertEqual(len({r["key"] for r in records}), len(records))

    def test_correlate_by_branch_groups_the_nest(self):
        grouped = M.correlate_by_branch(M.enumerate_markers(self.primary))
        self.assertEqual(sorted(grouped), ["60-activity-dashboard"])
        pair = grouped["60-activity-dashboard"]
        self.assertEqual(len(pair), 2)
        # Different workflow types on one branch is the legitimate
        # smith-new → smith-build nest, not a contradiction.
        self.assertEqual(
            {r["workflow_type"] for r in pair}, {"smith-new", "smith-build"}
        )

    def test_primary_vault_marker_is_flagged_and_sorted_first(self):
        records = M.enumerate_markers(self.worktree)
        self.assertTrue(records[0]["is_primary_vault"])
        self.assertEqual(records[0]["workflow_type"], "smith-new")
        self.assertFalse(records[1]["is_primary_vault"])
        self.assertEqual(records[1]["workflow_type"], "smith-build")

    def test_empty_session_log_falls_back_to_the_primary_current_session(self):
        records = M.enumerate_markers(self.worktree)
        child = [r for r in records if r["workflow_type"] == "smith-build"][0]
        # Neither None nor a crash: the primary vault's pointer resolves it.
        self.assertIsNotNone(child["session_log"])
        self.assertEqual(
            os.path.realpath(child["session_log"]), os.path.realpath(self.session_log)
        )
        self.assertEqual(child["session_log_source"], "current-session")

    def test_marker_supplied_session_log_is_not_overridden(self):
        records = M.enumerate_markers(self.primary)
        parent = [r for r in records if r["workflow_type"] == "smith-new"][0]
        self.assertEqual(parent["session_log_source"], "marker")
        self.assertEqual(
            os.path.realpath(parent["session_log"]), os.path.realpath(self.session_log)
        )

    def test_finish_variant_parses_alongside_the_branch_marker(self):
        # smith-finish writes finish-<safe>.yaml next to a possible
        # <safe>.yaml, so one branch legitimately carries two markers in ONE
        # vault — the reason the map key is (project, filename), not
        # (project, branch).
        finish_path = os.path.join(
            self.primary,
            ".smith",
            "vault",
            "active-workflows",
            "finish-60-activity-dashboard.yaml",
        )
        _write(finish_path, FINISH_MARKER)
        try:
            records = M.enumerate_markers(self.primary)
            finish = [r for r in records if r["workflow_type"] == "smith-finish"][0]
            self.assertIsNone(finish["worktree"])
            self.assertEqual(finish["started"], "2026-09-22T17:02:11Z")
            # Its session_log: is absent entirely, so the same fallback runs.
            self.assertEqual(finish["session_log_source"], "current-session")
            filenames = sorted(
                r["marker_filename"] for r in records if r["is_primary_vault"]
            )
            self.assertEqual(
                filenames,
                ["60-activity-dashboard.yaml", "finish-60-activity-dashboard.yaml"],
            )
            keys = [r["key"] for r in records]
            self.assertEqual(len(set(keys)), len(keys))
        finally:
            os.remove(finish_path)

    def test_declared_phase_is_read_when_present(self):
        # FR-13. Nothing writes one today; accepting it now makes OOS-1's
        # later stamping purely additive.
        path = os.path.join(
            self.primary, ".smith", "vault", "active-workflows", "fix-log.yaml"
        )
        _write(path, QUOTED_MARKER)
        try:
            record = M.read_marker(
                path, primary_repo_path=self.primary, vault_root=self.primary
            )
            self.assertEqual(record["declared_phase"], "smith-bugfix:3")
            self.assertEqual(record["branch"], "fix/log")
            self.assertEqual(record["workflow_type"], "smith-bugfix")
        finally:
            os.remove(path)

    def test_session_log_pointing_at_a_missing_file_is_not_substituted(self):
        # The double existence check (metrics-tracker.sh:23-32): a pointer
        # whose target is gone resolves to nothing rather than to a lie.
        path = os.path.join(
            self.primary, ".smith", "vault", "active-workflows", "gone.yaml"
        )
        _write(path, PRIMARY_MARKER.format(session_log="/nonexistent/session.md"))
        try:
            record = M.read_marker(
                path, primary_repo_path=self.primary, vault_root=self.primary
            )
            # An explicit marker value is reported as given; it is the empty
            # case that falls back.
            self.assertEqual(record["session_log"], "/nonexistent/session.md")
            self.assertEqual(record["session_log_source"], "marker")
        finally:
            os.remove(path)

    def test_unreadable_marker_returns_none_rather_than_raising(self):
        self.assertIsNone(M.read_marker(os.path.join(self.tmp, "no-such-marker.yaml")))


if __name__ == "__main__":
    unittest.main()
