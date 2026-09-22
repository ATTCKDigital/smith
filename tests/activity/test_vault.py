"""vault.py — the VaultSnapshot and its read-only guarantee (T103).

The fixture at ``tests/activity/fixtures/vault-tree/`` is staged into a temp
directory as a real ``.smith/`` before each test. It is stored WITHOUT the
leading dot because the repo's ``.gitignore`` ignores ``.smith/`` globally,
so a fixture at its real path would be invisible to git and absent in CI —
present on one laptop, missing everywhere else, with nothing saying why.

Every fixture count is a DIFFERENT number on purpose. A vault where sessions,
bank items and queue entries all number 1 cannot tell a reader that returns
the right section from one that returns the wrong one.

The last class is the one that matters most. US-9 and FR-44 promise the
daemon never writes to a project's vault, and the only way to assert a
negative like that is to fingerprint the whole tree, run a full snapshot pass
and fingerprint again. The source-level guard in
``tests/smith-activity.test.sh`` catches a write path by inspection; this
catches one by behaviour, which is what actually matters to the operator
whose vault it is.

Reached from CI through the flat tests/smith-activity.test.sh wrapper.
"""

import os
import shutil
import tempfile
import unittest

from tests._harness import *  # noqa: F401,F403 — puts scripts/activity on sys.path

import vault as V
import vault_friction as VF

FIXTURE = os.path.join(ACTIVITY_FIXTURES_DIR, "vault-tree")


def fingerprint_tree(root):
    """Every path under ``root`` with its mtime, size and inode.

    The inode is included deliberately: a write-then-restore that happened to
    reproduce the original mtime and size would still allocate a new inode,
    and a guard that could be fooled by an atomic replace is not a guard.
    """
    out = {}
    for base, dirs, files in os.walk(root):
        dirs.sort()
        for name in sorted(dirs) + sorted(files):
            path = os.path.join(base, name)
            try:
                info = os.stat(path)
            except OSError:
                out[path] = None
                continue
            out[path] = (info.st_mtime_ns, info.st_size, info.st_ino)
    return out


class VaultFixtureBase(unittest.TestCase):
    def setUp(self):
        V.reset_cache()
        self.tmp = tempfile.mkdtemp(prefix="smith-vault-")
        self.project = os.path.join(self.tmp, "project")
        smith = os.path.join(self.project, ".smith")
        os.makedirs(smith)
        shutil.copytree(os.path.join(FIXTURE, "vault"), os.path.join(smith, "vault"))
        shutil.copytree(os.path.join(FIXTURE, "index"), os.path.join(smith, "index"))
        # `.current-session` is stored undotted for the same gitignore reason
        # the tree is; move it into place and substitute the staged root.
        staged = os.path.join(smith, "vault", "current-session.txt")
        with open(staged, encoding="utf-8") as fh:
            pointer = fh.read().replace("@FIXTURE@", self.project)
        os.remove(staged)
        with open(
            os.path.join(smith, "vault", ".current-session"), "w", encoding="utf-8"
        ) as fh:
            fh.write(pointer)
        marker = os.path.join(smith, "vault", "active-workflows", "fix-a-thing.yaml")
        with open(marker, encoding="utf-8") as fh:
            body = fh.read().replace("@FIXTURE@", self.project)
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write(body)
        # The sessions must have distinct mtimes for the "newest first"
        # assertion to mean anything; a copytree gives them whatever the
        # checkout did.
        self._touch("beta_ab1234_2026-09-21_090000.md", 2_000_000_000)
        self._touch("alpha_ab1234_2026-09-20_120000.md", 1_000_000_000)
        self.vault = os.path.join(smith, "vault")

    def _touch(self, name, when):
        path = os.path.join(self.project, ".smith", "vault", "sessions", name)
        os.utime(path, (when, when))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        V.reset_cache()


class SnapshotSectionsTest(VaultFixtureBase):
    def test_every_section_of_the_data_model_is_present(self):
        snap = V.snapshot(self.project)
        for key in (
            "recent_sessions",
            "ledger",
            "queue",
            "bank",
            "agents",
            "index",
            "friction",
        ):
            self.assertIn(key, snap, key)
        self.assertTrue(snap["exists"])

    def test_sessions_are_newest_first_by_mtime(self):
        """By mtime, never by the date in the filename or a stamp inside the
        file: FR-58's whole point is that the log's own clocks are not
        comparable."""
        rows = V.snapshot(self.project)["recent_sessions"]
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0]["name"].startswith("beta_"))
        self.assertEqual(rows[0]["status"], "active")
        self.assertEqual(rows[0]["branch"], "60-activity-dashboard")
        self.assertEqual(rows[0]["started"], "2026-09-21T09:00:00")

    def test_an_active_session_has_no_end_time(self):
        """There is no `session_end` field in the format. Reporting the file's
        mtime as an end time for a session that is still running would claim
        it finished at its last keystroke."""
        rows = V.snapshot(self.project)["recent_sessions"]
        active = [r for r in rows if r["status"] == "active"][0]
        completed = [r for r in rows if r["status"] == "completed"][0]
        self.assertIsNone(active["ended"])
        self.assertIsNotNone(completed["ended"])

    def test_ledger_counts_come_from_meta_yaml(self):
        ledger = V.snapshot(self.project)["ledger"]
        self.assertEqual(ledger["source"], "meta.yaml")
        self.assertEqual(ledger["counts"]["patterns"], 4)
        self.assertEqual(ledger["counts"]["antipatterns"], 2)
        self.assertEqual(ledger["total_reflections"], 7)
        self.assertIsInstance(ledger["total_reflections"], int)

    def test_ledger_falls_back_to_entry_counting_and_says_so(self):
        """Two ways of counting that disagree silently would be worse than
        one that is occasionally absent, so the fallback is LABELLED."""
        os.remove(os.path.join(self.vault, "ledger", "meta.yaml"))
        V.reset_cache()
        ledger = V.snapshot(self.project)["ledger"]
        self.assertEqual(ledger["source"], "entry-count")
        self.assertIn("patterns", ledger["counts"])

    def test_queue_depth_and_history_are_counted_separately(self):
        queue = V.snapshot(self.project)["queue"]
        self.assertEqual(queue["depth"], 1)
        self.assertEqual(queue["history_count"], 2)

    def test_bank_items_carry_their_frontmatter(self):
        bank = V.snapshot(self.project)["bank"]
        self.assertEqual(bank["count"], 2)
        ids = {item["id"] for item in bank["recent"]}
        self.assertEqual(ids, {"BANK-001", "BANK-002"})
        first = [i for i in bank["recent"] if i["id"] == "BANK-001"][0]
        self.assertEqual(first["title"], "A first banked idea")
        self.assertEqual(first["status"], "banked")

    def test_agents_are_counted_per_type(self):
        agents = V.snapshot(self.project)["agents"]
        self.assertEqual(agents, {"Explore": 1, "general": 3})

    def test_index_freshness_is_read_from_the_manifest(self):
        index = V.snapshot(self.project)["index"]
        self.assertTrue(index["exists"])
        self.assertEqual(index["schema_version"], 1)
        self.assertEqual(index["file_count"], 42)
        self.assertEqual(index["last_built"], "2026-09-21T09:30:00Z")

    def test_a_missing_index_is_a_state_not_an_error(self):
        shutil.rmtree(os.path.join(self.project, ".smith", "index"))
        V.reset_cache()
        index = V.snapshot(self.project)["index"]
        self.assertFalse(index["exists"])
        self.assertIsNone(index["file_count"])

    def test_a_project_with_no_vault_still_answers(self):
        empty = os.path.join(self.tmp, "no-vault")
        os.makedirs(empty)
        snap = V.snapshot(empty)
        self.assertFalse(snap["exists"])
        self.assertIn("friction", snap)


class ChangeDetectionTest(VaultFixtureBase):
    """T101/FR-38 — the stat sweep, which is what keeps a 1 Hz poll cheap."""

    def test_the_watched_set_is_the_one_fr38_lists(self):
        watched = V.watched_paths(self.project)
        for needle in (
            os.path.join("vault", "sessions"),
            os.path.join("vault", "ledger"),
            os.path.join("vault", "queue", "history"),
            os.path.join("vault", "bank"),
            os.path.join("vault", "agents"),
            os.path.join(".smith", "index"),
            ".current-session",
        ):
            self.assertTrue(
                any(needle in p for p in watched), "%s is not watched" % needle
            )
        home = paths_smith_home()
        self.assertIn(os.path.join(home, "projects.json"), watched)
        self.assertIn(os.path.join(home, "scheduler", "scheduler.log"), watched)

    def test_individual_files_are_watched_not_just_their_directory(self):
        """A directory's mtime moves when an entry is added or removed, but
        NOT when an existing file's contents change. Watching only the
        directory would miss every edit to an existing session log — which is
        the single most common change in a live vault."""
        watched = V.watched_paths(self.project)
        self.assertIn(
            os.path.join(self.vault, "sessions", "beta_ab1234_2026-09-21_090000.md"),
            watched,
        )

    def test_an_unchanged_vault_returns_the_identical_snapshot_object(self):
        state = {}
        first = V.snapshot(self.project, poll_state=state)
        second = V.snapshot(self.project, poll_state=state)
        self.assertIs(first, second)
        self.assertTrue(state)

    def test_a_changed_file_produces_a_new_snapshot(self):
        state = {}
        first = V.snapshot(self.project, poll_state=state)
        path = os.path.join(self.vault, "bank", "2026-09-09_120000-third.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('---\nid: BANK-003\ntitle: "Third"\nstatus: banked\n---\n')
        second = V.snapshot(self.project, poll_state=state)
        self.assertIsNot(first, second)
        self.assertEqual(second["bank"]["count"], 3)

    def test_the_fingerprint_reads_no_file_contents(self):
        """`stat` only. The parse behind the sweep is the expensive part and
        the entire reason the sweep exists."""
        before = fingerprint_tree(os.path.join(self.project, ".smith"))
        V.fingerprint(self.project)
        self.assertEqual(before, fingerprint_tree(os.path.join(self.project, ".smith")))


class FrictionTest(VaultFixtureBase):
    """T102/FR-37 — and the two counters that structurally cannot work."""

    def setUp(self):
        VaultFixtureBase.setUp(self)
        self.home = os.path.join(self.tmp, "smith-home")
        os.makedirs(os.path.join(self.home, "logs"))
        self._old_home = os.environ.get("SMITH_HOME")
        os.environ["SMITH_HOME"] = self.home
        VF.reset_cache()

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("SMITH_HOME", None)
        else:
            os.environ["SMITH_HOME"] = self._old_home
        VF.reset_cache()
        VaultFixtureBase.tearDown(self)

    def _log(self, lines):
        with open(
            os.path.join(self.home, "logs", "hooks.log"), "w", encoding="utf-8"
        ) as fh:
            fh.write("\n".join(lines) + "\n")

    def test_gate_denials_are_counted_from_the_bracketed_line_shape(self):
        """`workflow-gate.sh:174` writes `[<stamp>] workflow-gate DENY ...`,
        NOT the bare `<stamp> <hook> key=val` shape data-model.md §2.8
        documents. A parser that knew only the documented shape would report
        zero denials with the log sitting there full of them."""
        self._log(
            [
                "[2026-09-22T20:48:39Z] workflow-gate DENY tool=Bash project=/p appendix=x",
                "[2026-09-22T20:48:40Z] workflow-gate DENY tool=Write project=/p appendix=y",
                "2026-09-22T20:48:41Z manifest-updater file=a.py status=ok",
            ]
        )
        result = VF.friction()
        self.assertEqual(result["gate_denials"], 2)
        self.assertIn("gate_denials", result["observable"])

    def test_the_bare_line_shape_is_counted_too(self):
        self._log(
            [
                "2026-09-22T20:48:41Z workflow-gate denied=1",
                "2026-09-22T20:48:42Z context-loader skill=null reason=no-trigger",
            ]
        )
        self.assertEqual(VF.friction()["gate_denials"], 1)

    def test_uninstrumented_counters_are_marked_unobservable(self):
        """**The honesty requirement.** security-guard-*.sh and
        grade-response.sh never write to hooks.log, so their counts can only
        ever be 0 — and a 0 that means "not instrumented" must not render the
        same as a 0 that means "nothing was blocked"."""
        self._log(["[2026-09-22T20:48:39Z] workflow-gate DENY tool=Bash project=/p"])
        result = VF.friction()
        self.assertEqual(result["security_blocks"], 0)
        self.assertEqual(result["grade_retries"], 0)
        self.assertEqual(
            sorted(result["unobservable"]), ["grade_retries", "security_blocks"]
        )
        self.assertIn("not measured", result["note"])

    def test_a_counter_becomes_observable_once_its_hook_reports(self):
        """The observability probe is empirical, not a hardcoded list — so if
        someone ever wires security-guard-bash.sh to the log, the counter
        starts being trusted without this module being edited."""
        self._log(
            [
                "2026-09-22T20:48:41Z security-guard-bash blocked=rm",
                "2026-09-22T20:48:42Z security-guard-bash blocked=curl",
            ]
        )
        result = VF.friction()
        self.assertEqual(result["security_blocks"], 2)
        self.assertIn("security_blocks", result["observable"])

    def test_an_unreadable_log_makes_everything_unobservable_not_zero(self):
        VF.reset_cache()
        result = VF.friction()
        self.assertFalse(result["readable"])
        self.assertEqual(
            sorted(result["unobservable"]),
            ["gate_denials", "grade_retries", "security_blocks"],
        )

    def test_the_session_window_starts_at_the_recorded_offset(self):
        self._log(["[2026-09-22T20:00:00Z] workflow-gate DENY tool=Bash project=/p"])
        offset = os.path.getsize(os.path.join(self.home, "logs", "hooks.log"))
        with open(
            os.path.join(self.home, "logs", "hooks.log"), "a", encoding="utf-8"
        ) as fh:
            fh.write("[2026-09-22T21:00:00Z] workflow-gate DENY tool=Edit project=/p\n")
        VF.reset_cache()
        self.assertEqual(VF.friction()["gate_denials"], 2)
        VF.reset_cache()
        self.assertEqual(VF.friction(start_offset=offset)["gate_denials"], 1)


class ReadOnlyTest(VaultFixtureBase):
    """US-9/FR-44 — asserted behaviourally, not by inspection."""

    def test_a_full_snapshot_pass_modifies_and_creates_nothing(self):
        root = os.path.join(self.project, ".smith")
        before = fingerprint_tree(root)
        state = {}
        for _ in range(3):
            V.reset_cache()
            V.snapshot(self.project, poll_state=state)
        after = fingerprint_tree(root)
        self.assertEqual(
            sorted(before), sorted(after), "a snapshot pass created or removed a path"
        )
        self.assertEqual(before, after, "a snapshot pass modified a file")

    def test_the_active_workflows_directory_is_not_even_opened_for_append(self):
        """The one directory nothing in this feature may ever write to. The
        source guard in tests/smith-activity.test.sh proves no write path
        names it; this proves the running reader leaves it alone."""
        active = os.path.join(self.vault, "active-workflows")
        before = fingerprint_tree(active)
        V.snapshot(self.project)
        self.assertEqual(before, fingerprint_tree(active))


def paths_smith_home():
    import paths

    return paths.smith_home()


if __name__ == "__main__":
    unittest.main()
