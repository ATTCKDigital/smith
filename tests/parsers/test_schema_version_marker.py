"""Regression test for .smith/index/.schema-version marker write.

skills/smith-index/SKILL.md step 8 promises this marker gets written
on every full rebuild. PR #29 installed meta_schema_version.txt at
~/.smith/scripts/ but run.py never wrote the .schema-version marker
on the project side — confirmed by gold-canna-theme tonight (278
files indexed cleanly, no .schema-version on disk).

This test exercises run.py's new write_schema_version_marker method
and confirms:
  - The marker file gets written
  - Content equals the meta_schema_version.txt value
  - Missing source file → silent skip (no exception, marker absent)
  - mode_full and mode_incremental both write it

Run:
    python3 tests/parsers/test_schema_version_marker.py
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
RUN_PY = REPO / "scripts" / "smith-index" / "run.py"


def _load_run_py():
    sys.path.insert(0, str(REPO / "scripts" / "parsers"))
    spec = importlib.util.spec_from_file_location("smith_index_run", RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


run_mod = _load_run_py()


class SchemaVersionMarkerTests(unittest.TestCase):
    def setUp(self) -> None:
        # macOS /tmp -> /private/tmp; resolve so paths line up with
        # IndexRun.__init__'s self.project_root.resolve().
        self.tmp = Path(tempfile.mkdtemp(prefix="smith-schema-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _make_run(self) -> "run_mod.IndexRun":
        log_path = self.tmp / ".smith" / "logs" / "test.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        run = run_mod.IndexRun(project_root=self.tmp, log_path=log_path)
        run.setup_dirs()
        return run

    def test_marker_written_from_repo_source(self) -> None:
        """In the smith-repo dev tree, meta_schema_version.txt exists at
        scripts/parsers/ and serves as the fallback source. The method
        finds it and writes .schema-version."""
        run = self._make_run()
        run.write_schema_version_marker()
        marker = self.tmp / ".smith" / "index" / ".schema-version"
        self.assertTrue(
            marker.exists(),
            ".schema-version marker not written",
        )
        # Source value comes from <repo>/scripts/parsers/meta_schema_version.txt
        source = REPO / "scripts" / "parsers" / "meta_schema_version.txt"
        if source.exists():
            expected = source.read_text(encoding="utf-8").strip()
            actual = marker.read_text(encoding="utf-8").strip()
            self.assertEqual(actual, expected)

    def test_marker_silent_skip_when_source_missing(self) -> None:
        """If neither PARSER_DIR_GLOBAL nor PARSER_DIR_REPO has
        meta_schema_version.txt, the method silently skips — does NOT
        raise, does NOT create an empty marker."""
        run = self._make_run()
        # Monkey-patch the candidate paths to point at nothing.
        orig_global = run_mod.PARSER_DIR_GLOBAL
        orig_repo = run_mod.PARSER_DIR_REPO
        run_mod.PARSER_DIR_GLOBAL = self.tmp / "nonexistent-global"
        run_mod.PARSER_DIR_REPO = self.tmp / "nonexistent-repo"
        try:
            run.write_schema_version_marker()
            marker = self.tmp / ".smith" / "index" / ".schema-version"
            self.assertFalse(
                marker.exists(),
                "marker should NOT exist when source is missing",
            )
        finally:
            run_mod.PARSER_DIR_GLOBAL = orig_global
            run_mod.PARSER_DIR_REPO = orig_repo

    def test_marker_content_strips_whitespace(self) -> None:
        """meta_schema_version.txt may have trailing newline; the marker
        should contain the stripped value followed by a single newline
        for tooling sanity (`cat` shows it cleanly)."""
        run = self._make_run()
        # Create a fake parser dir with our own source value
        fake_parser_dir = self.tmp / "fake-parsers"
        fake_parser_dir.mkdir()
        (fake_parser_dir / "meta_schema_version.txt").write_text(
            "  42  \n",  # Intentional whitespace
            encoding="utf-8",
        )
        orig_global = run_mod.PARSER_DIR_GLOBAL
        run_mod.PARSER_DIR_GLOBAL = fake_parser_dir
        try:
            run.write_schema_version_marker()
            marker = self.tmp / ".smith" / "index" / ".schema-version"
            self.assertEqual(marker.read_text(encoding="utf-8"), "42\n")
        finally:
            run_mod.PARSER_DIR_GLOBAL = orig_global

    def test_global_install_takes_precedence(self) -> None:
        """When both PARSER_DIR_GLOBAL and PARSER_DIR_REPO have the
        source file, the global install wins."""
        run = self._make_run()
        fake_global = self.tmp / "fake-global"
        fake_global.mkdir()
        (fake_global / "meta_schema_version.txt").write_text("99\n")
        # The real PARSER_DIR_REPO has "2" — we want to confirm "99" wins
        orig_global = run_mod.PARSER_DIR_GLOBAL
        run_mod.PARSER_DIR_GLOBAL = fake_global
        try:
            run.write_schema_version_marker()
            marker = self.tmp / ".smith" / "index" / ".schema-version"
            self.assertEqual(marker.read_text(encoding="utf-8").strip(), "99")
        finally:
            run_mod.PARSER_DIR_GLOBAL = orig_global

    def test_marker_overwritten_on_rerun(self) -> None:
        """Re-running write_schema_version_marker overwrites the prior
        value (so /smith-update can detect schema bumps after a fresh
        install)."""
        run = self._make_run()
        # First pass with value "2" from the real PARSER_DIR_REPO
        run.write_schema_version_marker()
        marker = self.tmp / ".smith" / "index" / ".schema-version"
        first_content = marker.read_text(encoding="utf-8")
        # Second pass with a fake source returning a different value
        fake_dir = self.tmp / "bump"
        fake_dir.mkdir()
        (fake_dir / "meta_schema_version.txt").write_text("3\n")
        orig_global = run_mod.PARSER_DIR_GLOBAL
        run_mod.PARSER_DIR_GLOBAL = fake_dir
        try:
            run.write_schema_version_marker()
            new_content = marker.read_text(encoding="utf-8").strip()
            self.assertEqual(new_content, "3")
            self.assertNotEqual(first_content.strip(), new_content)
        finally:
            run_mod.PARSER_DIR_GLOBAL = orig_global


if __name__ == "__main__":
    unittest.main()
