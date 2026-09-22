"""worktrees.py — FR-29 enumeration and cross-reference (T072).

Real git repos with real linked worktrees in temp dirs, because the whole
behavior under test is about what git reports and where git puts things.

Scope note: the six-row classification table (FR-30) and FR-31's git debounce
are T073-T075 and are NOT asserted here. This file covers enumeration, the
per-worktree fields, and the two ways a marker claims a worktree.

The recurring assertion shape is ``None is not 0``. Every git-derived field is
optional, and the difference between "no comparison was possible" and "zero
commits apart" is the difference between an honest blank and a claim that a
worktree is in sync with a branch that does not exist.

Reached from CI through the flat tests/smith-activity.test.sh wrapper.
"""

import os
import shutil
import subprocess
import tempfile
import unittest

from tests._harness import *  # noqa: F401,F403 — puts scripts/activity on sys.path

import worktrees as WT


def git(cwd, *args):
    return subprocess.run(
        ["git"] + list(args), cwd=cwd, capture_output=True, text=True, timeout=30
    )


class WorktreeBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="smith-worktrees-")
        self.primary = os.path.join(self.tmp, "primary")
        os.makedirs(self.primary)
        git(self.primary, "init", "-q", "-b", "main")
        git(self.primary, "config", "user.email", "t@example.com")
        git(self.primary, "config", "user.name", "T")
        self._commit("base.txt", "base\n", "base")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _commit(self, name, body, message, cwd=None):
        cwd = cwd or self.primary
        with open(os.path.join(cwd, name), "w", encoding="utf-8") as fh:
            fh.write(body)
        git(cwd, "add", "-A")
        git(cwd, "commit", "-qm", message)

    def _worktree(self, name, branch):
        # Deliberately OUTSIDE the primary tree, as /tmp/smith-<slug> is.
        path = os.path.join(self.tmp, "worktrees", name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        git(self.primary, "worktree", "add", "-q", "-b", branch, path)
        return path

    def _by_path(self, records, path):
        real = os.path.realpath(path)
        for record in records:
            if os.path.realpath(record["path"]) == real:
                return record
        raise AssertionError("no record for %s" % path)


class EnumerationTest(WorktreeBase):
    def test_primary_is_included_and_marked_distinctly(self):
        wt = self._worktree("feature", "60-feature")
        records = WT.describe(self.primary)
        self.assertEqual(len(records), 2)
        primary = self._by_path(records, self.primary)
        linked = self._by_path(records, wt)
        self.assertTrue(primary["is_primary"])
        self.assertFalse(linked["is_primary"])
        # The primary shows its OWN branch, not the worktree's.
        self.assertEqual(primary["branch"], "main")
        self.assertEqual(linked["branch"], "60-feature")

    def test_enumeration_is_identical_from_inside_the_worktree(self):
        """FR-28: a worktree is never a second project, so asking from either
        position must return the same set."""
        wt = self._worktree("feature", "60-feature")
        from_primary = {os.path.realpath(r["path"]) for r in WT.describe(self.primary)}
        from_worktree = {os.path.realpath(r["path"]) for r in WT.describe(wt)}
        self.assertEqual(from_primary, from_worktree)

    def test_non_repo_path_is_an_empty_list_not_an_exception(self):
        self.assertEqual(WT.describe(self.tmp), [])
        self.assertEqual(WT.describe("/nonexistent/path"), [])

    def test_detached_head_has_a_none_branch(self):
        head = git(self.primary, "rev-parse", "HEAD").stdout.strip()
        path = os.path.join(self.tmp, "worktrees", "detached")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        git(self.primary, "worktree", "add", "-q", "--detach", path, head)
        record = self._by_path(WT.describe(self.primary), path)
        self.assertIsNone(record["branch"])
        self.assertTrue(record["detached"])

    def test_short_path_collapses_home_only_when_it_matches(self):
        self.assertEqual(WT.short_path("/home/u/p", home="/home/u"), "~/p")
        self.assertEqual(WT.short_path("/home/u", home="/home/u"), "~")
        # A string prefix that is not a PATH prefix must not collapse.
        self.assertEqual(
            WT.short_path("/home/user2/p", home="/home/u"), "/home/user2/p"
        )
        self.assertEqual(WT.short_path("/tmp/x", home="/home/u"), "/tmp/x")


class GitFieldsTest(WorktreeBase):
    def test_ahead_behind_is_none_without_a_remote(self):
        """None, NOT (0, 0). There is nothing to be in sync with."""
        record = self._by_path(WT.describe(self.primary), self.primary)
        self.assertIsNone(record["ahead"])
        self.assertIsNone(record["behind"])

    def test_ahead_behind_counts_against_origin_base(self):
        remote = os.path.join(self.tmp, "remote.git")
        git(self.tmp, "init", "-q", "--bare", remote)
        git(self.primary, "remote", "add", "origin", remote)
        git(self.primary, "push", "-q", "origin", "main")
        wt = self._worktree("feature", "60-feature")
        # Two commits ahead on the worktree branch...
        self._commit("a.txt", "a\n", "a", cwd=wt)
        self._commit("b.txt", "b\n", "b", cwd=wt)
        # ...and one commit on main that the worktree has not got.
        self._commit("c.txt", "c\n", "c")
        git(self.primary, "push", "-q", "origin", "main")

        record = self._by_path(WT.describe(self.primary), wt)
        self.assertEqual(record["base_branch"], "main")
        self.assertEqual(record["ahead"], 2)
        self.assertEqual(record["behind"], 1)

    def test_dirty_count_counts_paths(self):
        wt = self._worktree("feature", "60-feature")
        clean = self._by_path(WT.describe(self.primary), wt)
        self.assertEqual(clean["dirty_count"], 0)
        for name in ("one.txt", "two.txt"):
            with open(os.path.join(wt, name), "w", encoding="utf-8") as fh:
                fh.write("x\n")
        dirty = self._by_path(WT.describe(self.primary), wt)
        self.assertEqual(dirty["dirty_count"], 2)

    def test_base_branch_comes_from_the_shipped_script(self):
        record = self._by_path(WT.describe(self.primary), self.primary)
        # No constitution in the fixture, so the script's own documented
        # fallback applies — and the SOURCE says it was the script, not a
        # guess made here.
        self.assertEqual(record["base_branch"], "main")
        self.assertEqual(record["base_branch_source"], "get-base-branch.sh")

    def test_base_branch_honours_the_constitution_frontmatter(self):
        memory = os.path.join(self.primary, ".specify", "memory")
        os.makedirs(memory)
        with open(os.path.join(memory, "constitution.md"), "w", encoding="utf-8") as fh:
            fh.write("---\nbase_branch: develop\n---\n\n# C\n")
        self._commit(
            os.path.join(".specify", "memory", "constitution.md"),
            "---\nbase_branch: develop\n---\n\n# C\n",
            "constitution",
        )
        record = self._by_path(WT.describe(self.primary), self.primary)
        self.assertEqual(record["base_branch"], "develop")
        # No origin/develop exists, so ahead/behind stay unknown rather than 0.
        self.assertIsNone(record["ahead"])

    def test_unresolvable_base_branch_is_none_not_main(self):
        """An honest blank beats a guessed `main`: a wrong base silently
        produces ahead/behind counts against the wrong branch."""
        original = WT.base_branch_script
        WT.base_branch_script = lambda _primary: None
        try:
            branch, source = WT.base_branch(self.primary, self.primary)
            self.assertIsNone(branch)
            self.assertEqual(source, "unresolved")
            self.assertEqual(WT.ahead_behind(self.primary, None), (None, None))
        finally:
            WT.base_branch_script = original


class MarkerCrossReferenceTest(WorktreeBase):
    def _marker(self, key, branch=None, worktree=None):
        return {"key": key, "branch": branch, "worktree": worktree}

    def test_marker_matches_by_worktree_path(self):
        wt = self._worktree("feature", "60-feature")
        markers = [self._marker("m-wt", branch="other", worktree=wt)]
        record = self._by_path(WT.describe(self.primary, markers=markers), wt)
        self.assertEqual(record["owning_marker"], "m-wt")

    def test_marker_matches_by_branch_when_it_carries_no_worktree(self):
        """The smith-finish marker variant has NO `worktree:` field at all, so
        a path-only cross-reference would lose it entirely."""
        wt = self._worktree("feature", "60-feature")
        markers = [self._marker("m-finish", branch="60-feature", worktree=None)]
        record = self._by_path(WT.describe(self.primary, markers=markers), wt)
        self.assertEqual(record["owning_marker"], "m-finish")

    def test_two_markers_for_one_branch_are_both_kept(self):
        """Binding constraint 10: smith-new in the primary vault and
        smith-build in the worktree's vault exist simultaneously."""
        wt = self._worktree("feature", "60-feature")
        markers = [
            self._marker("m-new", branch="60-feature", worktree=wt),
            self._marker("m-build", branch="60-feature", worktree=wt),
        ]
        record = self._by_path(WT.describe(self.primary, markers=markers), wt)
        self.assertEqual(sorted(record["owning_markers"]), ["m-build", "m-new"])

    def test_path_match_wins_over_branch_match(self):
        wt = self._worktree("feature", "60-feature")
        markers = [
            self._marker("m-branch", branch="60-feature", worktree=None),
            self._marker("m-path", branch="unrelated", worktree=wt),
        ]
        record = self._by_path(WT.describe(self.primary, markers=markers), wt)
        self.assertEqual(record["owning_markers"], ["m-path"])

    def test_unclaimed_worktree_has_no_owning_marker(self):
        wt = self._worktree("feature", "60-feature")
        record = self._by_path(WT.describe(self.primary, markers=[]), wt)
        self.assertIsNone(record["owning_marker"])
        self.assertEqual(record["owning_markers"], [])

    def test_occupying_session_matches_on_resolved_cwd(self):
        wt = self._worktree("feature", "60-feature")
        sessions = [
            {"session_id": "s-here", "cwd": wt},
            {"session_id": "s-elsewhere", "cwd": self.primary},
            {"session_id": "s-nocwd", "cwd": None},
        ]
        records = WT.describe(self.primary, sessions=sessions)
        self.assertEqual(self._by_path(records, wt)["occupying_session"], "s-here")
        self.assertEqual(
            self._by_path(records, self.primary)["occupying_session"], "s-elsewhere"
        )


class MissingWorktreeTest(WorktreeBase):
    def test_a_worktree_git_still_lists_but_disk_has_lost(self):
        """Every git-derived field becomes unknowable, and says so.

        T073 classifies this as MISSING; here the point is only that it does
        not crash and does not report 0 for things it cannot measure.
        """
        wt = self._worktree("feature", "60-feature")
        shutil.rmtree(wt)
        record = self._by_path(WT.describe(self.primary), wt)
        self.assertFalse(record["exists"])
        self.assertIsNone(record["dirty_count"])
        self.assertIsNone(record["ahead"])
        self.assertIsNone(record["behind"])
        self.assertIsNone(record["base_branch"])
        self.assertEqual(record["base_branch_source"], "unresolved")
        # The branch is still known — git's own record survives the directory.
        self.assertEqual(record["branch"], "60-feature")


if __name__ == "__main__":
    unittest.main()
