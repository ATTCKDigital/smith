"""worktree_states.py — the six-row decision table, SC-8 / FR-30 (T077).

Split from ``test_worktrees.py`` on the repo's 500-line decompose rule, and
split along the same seam as the source: ``test_worktrees.py`` covers
enumeration and the git-derived fields, this covers what those fields are
then MADE to mean.

The fixtures are real repositories, because none of the three degraded states
can be faked:

* **MISSING** is precisely "``rm -rf`` without ``git worktree prune``". A
  pruned worktree is not missing, it is absent, and git reports them
  differently.
* **ORPHANED by a gone branch** is only reachable by detaching the worktree
  first — git refuses to delete a branch that is checked out — so a fixture
  that merely deletes the branch silently builds an ordinary ACTIVE worktree
  and asserts nothing.
* **HELD** needs a real unmerged branch on disk; only the stalled half (a
  phase ``entered_at`` older than the threshold) is synthesized.

Two assertions here exist because they FAILED first and the classifier was
wrong: ``test_a_brand_new_worktree_is_not_orphaned`` (a fresh branch still
points at base, so "no commits base lacks" is trivially true) and
``test_orphaned_beats_held_because_row_3_precedes_row_4``.

Reached from CI through the flat tests/smith-activity.test.sh wrapper.
"""

import shutil
import time
import unittest

from tests._harness import *  # noqa: F401,F403 — puts scripts/activity on sys.path
from tests.activity.test_worktrees import WorktreeBase, git

import worktrees as WT


def _stamp(offset_s=0.0):
    """An ISO-8601 Z daemon stamp ``offset_s`` seconds from now."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + offset_s))


class ClassificationBase(WorktreeBase):
    """Adds marker/workflow synthesis on top of the real-git fixtures.

    Markers are dicts rather than files because ``markers.read_marker`` is
    pinned by its own suite; what is under test here is the table, and
    re-staging YAML would be testing the parser a second time. The GIT facts
    every row branches on — on-disk-ness, merged-ness, branch existence — stay
    real, which is the half that cannot be faked.
    """

    def _marker(self, key, branch=None, worktree=None, started=None):
        return {
            "key": key,
            "branch": branch,
            "worktree": worktree,
            "started": _stamp(-3600) if started is None else started,
        }

    def _workflow(self, key, entered_at, title="Implementation"):
        return {
            "key": key,
            "current_phase_id": "smith-bugfix:2",
            "current_title": title,
            "phases": [{"id": "smith-bugfix:2", "entered_at": entered_at}],
            "signals": [{"at": entered_at}],
        }

    def _classify(self, path, markers=(), workflows=(), now=None):
        WT.reset_cache()
        records = WT.describe(
            self.primary, markers=markers, workflows=workflows, now=now
        )
        return self._by_path(records, path)


class MissingStateTest(ClassificationBase):
    def test_missing_is_a_marker_pointing_at_a_path_that_is_gone(self):
        """Row 2. `rm -rf` WITHOUT a prune — git still lists it."""
        wt = self._worktree("gone", "60-gone")
        shutil.rmtree(wt)
        markers = [self._marker("m", branch="60-gone", worktree=wt)]
        record = self._classify(wt, markers=markers)
        self.assertEqual(record["classification"], WT.CLASS_MISSING)
        self.assertEqual(record["remedy"], WT.REMEDY_MISSING)
        self.assertIn("worktree prune", record["remedy"])

    def test_a_missing_worktree_with_no_marker_is_not_missing(self):
        """Row 2 requires a MARKER. An unclaimed dead worktree is git's
        housekeeping, not a stalled Smith workflow, and rows 2-5 all start
        with "marker exists" for that reason."""
        wt = self._worktree("gone", "60-gone")
        shutil.rmtree(wt)
        record = self._classify(wt, markers=[])
        self.assertEqual(record["classification"], WT.CLASS_ACTIVE)
        self.assertIsNone(record["remedy"])


class OrphanedStateTest(ClassificationBase):
    def test_orphaned_when_the_branch_is_merged_into_base(self):
        """Row 3, the merged variant."""
        wt = self._worktree("merged", "60-merged")
        self._commit("done.txt", "done\n", "done", cwd=wt)
        git(self.primary, "merge", "-q", "--no-ff", "-m", "merge", "60-merged")
        markers = [self._marker("m", branch="60-merged", worktree=wt)]
        record = self._classify(wt, markers=markers)
        self.assertTrue(record["branch_merged"])
        self.assertEqual(record["classification"], WT.CLASS_ORPHANED)
        self.assertEqual(record["remedy"], WT.REMEDY_ORPHANED)
        self.assertIn("janitor", record["remedy"])

    def test_orphaned_when_the_branch_is_gone(self):
        """Row 3, the gone variant.

        The detach is load-bearing: `git branch -D` refuses a branch that is
        checked out in a worktree, so a fixture that skipped it would build an
        ordinary ACTIVE worktree and assert nothing.
        """
        wt = self._worktree("gone", "60-gone")
        git(wt, "checkout", "-q", "--detach")
        deleted = git(self.primary, "branch", "-q", "-D", "60-gone")
        self.assertEqual(deleted.returncode, 0, deleted.stderr)
        markers = [self._marker("m", branch="60-gone", worktree=wt)]
        record = self._classify(wt, markers=markers)
        self.assertTrue(record["branch_gone"])
        self.assertEqual(record["classification"], WT.CLASS_ORPHANED)

    def test_orphaned_beats_held_because_row_3_precedes_row_4(self):
        """**The ordering pin.** A merged branch whose owning workflow is also
        long stalled satisfies BOTH rows. FR-30 says it is janitor backlog,
        not a stalled bugfix, so row 3 must win. Swap the two rows in
        worktree_states.classify and only this assertion notices."""
        wt = self._worktree("merged", "60-merged")
        self._commit("done.txt", "done\n", "done", cwd=wt)
        git(self.primary, "merge", "-q", "--no-ff", "-m", "merge", "60-merged")
        markers = [self._marker("m", branch="60-merged", worktree=wt)]
        stalled = [self._workflow("m", _stamp(-WT.HELD_THRESHOLD_S * 10))]
        record = self._classify(wt, markers=markers, workflows=stalled)
        self.assertEqual(record["classification"], WT.CLASS_ORPHANED)
        self.assertNotEqual(record["classification"], WT.CLASS_HELD)

    def test_an_orphan_is_never_rendered_as_an_active_workflow(self):
        """FR-30's prohibition, stated as a prohibition."""
        wt = self._worktree("merged", "60-merged")
        self._commit("done.txt", "done\n", "done", cwd=wt)
        git(self.primary, "merge", "-q", "--no-ff", "-m", "merge", "60-merged")
        markers = [self._marker("m", branch="60-merged", worktree=wt)]
        for workflows in ([], [self._workflow("m", _stamp())]):
            record = self._classify(wt, markers=markers, workflows=workflows)
            self.assertNotEqual(record["classification"], WT.CLASS_ACTIVE)

    def test_an_unknown_merge_state_never_orphans(self):
        """Three-valued logic. `None` means the git call did not run, and
        convicting a live worktree on a question nobody asked is the exact
        failure this feature exists to report rather than commit."""
        wt = self._worktree("feature", "60-feature")
        markers = [self._marker("m", branch="60-feature", worktree=wt)]
        record = self._classify(wt, markers=markers)
        self.assertIsNot(record["branch_merged"], True)
        self.assertIsNot(record["branch_gone"], True)
        self.assertEqual(record["classification"], WT.CLASS_ACTIVE)

    def test_a_brand_new_worktree_is_not_orphaned(self):
        """**Regression pin, found by this suite.** A worktree created
        seconds ago has committed nothing, so its branch still points at base
        and `rev-list --count base..branch` is 0 — trivially "merged". The
        first version of the classifier returned True there and labelled
        every fresh /smith-new worktree as janitor backlog. The tips being
        equal is UNKNOWN, not merged."""
        wt = self._worktree("fresh", "60-fresh")
        markers = [self._marker("m", branch="60-fresh", worktree=wt)]
        record = self._classify(wt, markers=markers, workflows=[])
        self.assertIsNone(record["branch_merged"])
        self.assertNotEqual(record["classification"], WT.CLASS_ORPHANED)
        self.assertEqual(record["classification"], WT.CLASS_ACTIVE)

    def test_an_unmerged_branch_with_commits_is_a_definite_false(self):
        """The other end of the three values: committed work that base does
        not contain is a confident "not merged", not an unknown."""
        wt = self._worktree("busy", "60-busy")
        self._commit("wip.txt", "wip\n", "wip", cwd=wt)
        markers = [self._marker("m", branch="60-busy", worktree=wt)]
        record = self._classify(wt, markers=markers)
        self.assertIs(record["branch_merged"], False)


class HeldStateTest(ClassificationBase):
    def test_held_when_the_owning_workflow_stops_advancing(self):
        """Row 4: on disk, unmerged, no signal for longer than the threshold."""
        wt = self._worktree("stalled", "60-stalled")
        self._commit("wip.txt", "wip\n", "wip", cwd=wt)
        markers = [self._marker("m", branch="60-stalled", worktree=wt)]
        stalled = [
            self._workflow("m", _stamp(-WT.HELD_THRESHOLD_S - 60), title="Phase 4 QA")
        ]
        record = self._classify(wt, markers=markers, workflows=stalled)
        self.assertEqual(record["classification"], WT.CLASS_HELD)
        self.assertEqual(record["died_in_phase"], "Phase 4 QA")
        self.assertIsNotNone(record["age_s"])
        self.assertGreaterEqual(record["age_s"], 3500)

    def test_just_under_the_threshold_is_still_active(self):
        """The threshold is a threshold, not a formality."""
        wt = self._worktree("busy", "60-busy")
        self._commit("wip.txt", "wip\n", "wip", cwd=wt)
        markers = [self._marker("m", branch="60-busy", worktree=wt)]
        fresh = [self._workflow("m", _stamp(-WT.HELD_THRESHOLD_S + 60))]
        record = self._classify(wt, markers=markers, workflows=fresh)
        self.assertEqual(record["classification"], WT.CLASS_ACTIVE)
        self.assertIsNone(record["died_in_phase"])

    def test_held_is_not_claimed_without_a_workflow_to_judge(self):
        """No phase timeline means "not advancing" is unanswerable, so row 4
        does not match. Inferring a stall from the marker's age alone would
        mark every long-running workflow held — the marker below is an hour
        old and must still read active."""
        wt = self._worktree("stalled", "60-stalled")
        self._commit("wip.txt", "wip\n", "wip", cwd=wt)
        markers = [self._marker("m", branch="60-stalled", worktree=wt)]
        record = self._classify(wt, markers=markers, workflows=[])
        self.assertEqual(record["classification"], WT.CLASS_ACTIVE)
        self.assertGreaterEqual(record["age_s"], 3500)


class PrimaryAndUnownedTest(ClassificationBase):
    def test_the_primary_checkout_is_marked_distinctly(self):
        """Row 1, evaluated FIRST. create-active-workflow.sh writes most
        markers into the primary vault, so a table that checked ownership
        before primacy would render the operator's own repo as somebody's
        abandoned worktree."""
        self._worktree("feature", "60-feature")
        markers = [self._marker("m", branch="main", worktree=self.primary)]
        record = self._classify(self.primary, markers=markers)
        self.assertEqual(record["classification"], WT.CLASS_PRIMARY)
        self.assertTrue(record["is_primary"])
        self.assertIsNone(record["remedy"])

    def test_a_worktree_with_no_marker_is_active_and_says_why(self):
        """Rows 5 and 6 share a class and are told apart by the reason."""
        wt = self._worktree("feature", "60-feature")
        unowned = self._classify(wt, markers=[])
        self.assertEqual(unowned["classification"], WT.CLASS_ACTIVE)
        self.assertEqual(unowned["classification_reason"], "no owning marker")

        markers = [self._marker("m", branch="60-feature", worktree=wt)]
        owned = self._classify(wt, markers=markers, workflows=[])
        self.assertEqual(owned["classification"], WT.CLASS_ACTIVE)
        self.assertNotEqual(owned["classification_reason"], "no owning marker")

    def test_age_is_none_rather_than_zero_when_started_is_unparseable(self):
        wt = self._worktree("feature", "60-feature")
        markers = [self._marker("m", branch="60-feature", worktree=wt, started="")]
        record = self._classify(wt, markers=markers)
        self.assertIsNone(record["age_s"])

    def test_marker_dicts_never_leak_into_the_record(self):
        """`_markers` is scratch for the classifier. It holds whole marker
        records, and the records go into the SSE state tree — so leaving it
        in would put marker_path and every raw field on the wire."""
        wt = self._worktree("feature", "60-feature")
        markers = [self._marker("m", branch="60-feature", worktree=wt)]
        record = self._classify(wt, markers=markers)
        self.assertNotIn("_markers", record)


class GitCacheTest(ClassificationBase):
    """FR-31/T075. `git` must never be invoked per SSE frame."""

    def test_git_does_not_run_again_inside_the_debounce_window(self):
        """The window is WIDENED for the duration of this test, deliberately.

        Asserting that 10 `describe()` calls fit inside the real 3 s window
        makes the result depend on how loaded the machine is, and a suite
        that fails under load teaches people to re-run rather than read —
        the same lesson as the `daemon_count` fix. What is under test is the
        cache MECHANISM, not the host's throughput, so the window is pinned
        far above any plausible runtime and expiry gets its own test below.
        """
        self._worktree("feature", "60-feature")
        original = WT.GIT_CACHE_S
        WT.GIT_CACHE_S = 3600.0
        try:
            WT.reset_cache()
            WT.describe(self.primary)
            first = WT.git_passes()
            self.assertEqual(first, 2)  # the primary and the one linked worktree
            for _ in range(10):
                WT.describe(self.primary)
            self.assertEqual(
                WT.git_passes(),
                first,
                "git re-ran inside the debounce — at 5 SSE frames a second "
                "that is a git fan-out per frame, which is exactly what FR-31 "
                "forbids",
            )
        finally:
            WT.GIT_CACHE_S = original

    def test_the_cache_expires_rather_than_pinning_the_answer_forever(self):
        """A cache that never expires is not a debounce, it is a freeze."""
        self._worktree("feature", "60-feature")
        original = WT.GIT_CACHE_S
        WT.GIT_CACHE_S = 0.0
        try:
            WT.reset_cache()
            WT.describe(self.primary)
            before = WT.git_passes()
            WT.describe(self.primary)
            self.assertGreater(WT.git_passes(), before)
        finally:
            WT.GIT_CACHE_S = original

    def test_markers_are_re_read_even_while_git_is_cached(self):
        """The cache covers git, NOT the cross-reference. Caching the whole
        result — which is what refresh.py used to do — would have made a
        marker that appeared mid-window invisible for 3 s for no reason.

        Window widened for the same load-independence reason as above.
        """
        wt = self._worktree("feature", "60-feature")
        original = WT.GIT_CACHE_S
        WT.GIT_CACHE_S = 3600.0
        try:
            WT.reset_cache()
            before = self._by_path(WT.describe(self.primary), wt)
            self.assertIsNone(before["owning_marker"])
            markers = [self._marker("m-new", branch="60-feature", worktree=wt)]
            passes = WT.git_passes()
            after = self._by_path(WT.describe(self.primary, markers=markers), wt)
            self.assertEqual(after["owning_marker"], "m-new")
            self.assertEqual(
                WT.git_passes(), passes, "git ran again; it should not have"
            )
        finally:
            WT.GIT_CACHE_S = original


if __name__ == "__main__":
    unittest.main()
