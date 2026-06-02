"""Tier-1 (.specify/systems/<name>/spec.md frontmatter) resolver tests.

Per research.md §2 and data-model.md §6:
  - Matching prefix returns correct system.
  - .specify/systems/ absent → falls through to tier 2/3 unchanged.
  - tier-1 hit beats tier-2 (system-paths.json) and tier-3 (heuristic).
  - Longest-prefix wins on multi-system tie.
  - Glob characters in `paths:` are silently dropped.
  - Malformed frontmatter is silently ignored.

    python3 tests/parsers/test_path_resolver_tier1.py
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
RESOLVER = os.path.join(REPO, "scripts", "parsers", "path-resolver.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("path_resolver", RESOLVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pr = _load_module()


def write_spec(root: str, system_name: str, frontmatter: str, body: str = "") -> str:
    spec_dir = os.path.join(root, ".specify", "systems", system_name)
    os.makedirs(spec_dir, exist_ok=True)
    spec_path = os.path.join(spec_dir, "spec.md")
    with open(spec_path, "w", encoding="utf-8") as f:
        f.write("---\n")
        f.write(frontmatter)
        if not frontmatter.endswith("\n"):
            f.write("\n")
        f.write("---\n")
        f.write(body)
    return spec_path


class Tier1MatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="smith-resolver-tier1-")
        # Force a fresh cache each test to avoid stale state across tempdirs.
        pr._load_declared_paths_cached.cache_clear()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        pr._load_declared_paths_cached.cache_clear()

    def test_matching_prefix_returns_correct_system(self):
        write_spec(
            self.tmp,
            "system-05-triage",
            textwrap.dedent(
                """\
                system: system-05-triage
                paths:
                  - backend/src/services/triage/
                  - frontend/src/lib/triage/
                """
            ),
        )
        got = pr.resolve("backend/src/services/triage/router.py", project_root=self.tmp)
        self.assertEqual(got, "system-05-triage")
        self.assertEqual(pr._last_matched_tier(), "tier1")

    def test_absent_specify_falls_through_to_heuristic(self):
        # No .specify/systems/ in tmp at all.
        got = pr.resolve("backend/src/api/x.py", project_root=self.tmp)
        # v1 heuristic for backend/src/ is "system-backend-src".
        self.assertEqual(got, "system-backend-src")
        self.assertEqual(pr._last_matched_tier(), "tier3")

    def test_tier1_beats_tier2_overrides(self):
        write_spec(
            self.tmp,
            "system-orders",
            "system: system-orders\npaths:\n  - backend/src/orders/\n",
        )
        ov = {
            "rules": [
                {"prefix": "backend/src/orders/", "system": "system-tier2-orders"}
            ]
        }
        got = pr.resolve(
            "backend/src/orders/handler.py",
            project_root=self.tmp,
            overrides_dict=ov,
        )
        self.assertEqual(got, "system-orders")
        self.assertEqual(pr._last_matched_tier(), "tier1")

    def test_tier1_beats_tier3_heuristic(self):
        write_spec(
            self.tmp,
            "system-custom",
            "system: system-custom\npaths:\n  - services/billing/\n",
        )
        # Without tier 1 this would resolve to "system-billing" via heuristic.
        got = pr.resolve("services/billing/main.py", project_root=self.tmp)
        self.assertEqual(got, "system-custom")
        self.assertEqual(pr._last_matched_tier(), "tier1")

    def test_longest_prefix_wins_across_systems(self):
        write_spec(
            self.tmp,
            "system-auth",
            "system: system-auth\npaths:\n  - services/auth/\n",
        )
        write_spec(
            self.tmp,
            "system-oauth",
            "system: system-oauth\npaths:\n  - services/auth/oauth/\n",
        )
        # File under services/auth/oauth/ → longer prefix wins.
        got_oauth = pr.resolve("services/auth/oauth/callback.py", project_root=self.tmp)
        self.assertEqual(got_oauth, "system-oauth")
        # File under services/auth/ but not oauth → shorter prefix wins.
        got_auth = pr.resolve("services/auth/session.py", project_root=self.tmp)
        self.assertEqual(got_auth, "system-auth")

    def test_glob_paths_are_rejected_silently(self):
        write_spec(
            self.tmp,
            "system-glob",
            textwrap.dedent(
                """\
                system: system-glob
                paths:
                  - services/*/handlers/
                  - services/safe/
                """
            ),
        )
        # Glob entry is dropped; safe literal still matches.
        got = pr.resolve("services/safe/api.py", project_root=self.tmp)
        self.assertEqual(got, "system-glob")
        # Glob entry's path falls back to heuristic.
        got_glob = pr.resolve("services/billing/handlers/x.py", project_root=self.tmp)
        self.assertEqual(got_glob, "system-billing")  # heuristic
        self.assertEqual(pr._last_matched_tier(), "tier3")

    def test_malformed_frontmatter_is_ignored(self):
        # Spec exists but has no frontmatter delimiters at all.
        spec_dir = os.path.join(self.tmp, ".specify", "systems", "system-broken")
        os.makedirs(spec_dir, exist_ok=True)
        with open(os.path.join(spec_dir, "spec.md"), "w", encoding="utf-8") as f:
            f.write("# Just a prose system spec, no frontmatter.\n")
        # Should fall through to heuristic without raising.
        got = pr.resolve("backend/src/x.py", project_root=self.tmp)
        self.assertEqual(got, "system-backend-src")

    def test_missing_system_field_defaults_to_directory_name(self):
        write_spec(
            self.tmp,
            "system-09-named-by-dir",
            "paths:\n  - backend/src/foo/\n",
        )
        got = pr.resolve("backend/src/foo/bar.py", project_root=self.tmp)
        self.assertEqual(got, "system-09-named-by-dir")

    def test_empty_paths_list_falls_through(self):
        write_spec(
            self.tmp,
            "system-no-paths",
            "system: system-no-paths\npaths:\n",
        )
        got = pr.resolve("backend/src/x.py", project_root=self.tmp)
        # No tier-1 contribution, falls to heuristic.
        self.assertEqual(got, "system-backend-src")

    def test_cache_invalidates_when_systems_dir_mtime_changes(self):
        write_spec(
            self.tmp,
            "system-a",
            "system: system-a\npaths:\n  - app/a/\n",
        )
        got1 = pr.resolve("app/a/x.py", project_root=self.tmp)
        self.assertEqual(got1, "system-a")
        # Add a new system. mtime of systems dir changes → cache key changes.
        import time

        time.sleep(0.01)
        write_spec(
            self.tmp,
            "system-b",
            "system: system-b\npaths:\n  - app/b/\n",
        )
        got2 = pr.resolve("app/b/y.py", project_root=self.tmp)
        self.assertEqual(got2, "system-b")


class CliTier1Tests(unittest.TestCase):
    """Confirm tier 1 still works via the CLI surface."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="smith-resolver-tier1-cli-")
        write_spec(
            self.tmp,
            "system-cli-test",
            "system: system-cli-test\npaths:\n  - backend/cli/\n",
        )
        pr._load_declared_paths_cached.cache_clear()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        pr._load_declared_paths_cached.cache_clear()

    def test_cli_uses_tier1(self):
        r = subprocess.run(
            ["python3", RESOLVER, "backend/cli/foo.py", self.tmp],
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "system-cli-test")


if __name__ == "__main__":
    unittest.main(verbosity=2)
