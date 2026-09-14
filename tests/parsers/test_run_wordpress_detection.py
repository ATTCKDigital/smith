"""Unit tests for scripts/smith-index/wp_defaults.py (Part A) and its
wiring into run.py's mode_init_system_paths() (FR-1..FR-4, SC-1, SC-2).

Run: python3 tests/parsers/test_run_wordpress_detection.py
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SMITH_INDEX_DIR = REPO / "scripts" / "smith-index"
RUN_PY = SMITH_INDEX_DIR / "run.py"
WP_DEFAULTS_PY = SMITH_INDEX_DIR / "wp_defaults.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_run_py():
    # run.py needs the parsers dir on sys.path at import time (precedent).
    sys.path.insert(0, str(REPO / "scripts" / "parsers"))
    return _load_module("smith_index_run_wpdetect", RUN_PY)


wp_defaults = _load_module("wp_defaults", WP_DEFAULTS_PY)
run_mod = _load_run_py()

ALL_WP_PREFIXES = set(wp_defaults.WP_CORE_DIRS) | set(wp_defaults.WP_CORE_ROOT_FILES)


class DetectWordpressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="smith-wp-detect-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_both_present_true(self) -> None:
        (self.tmp / "wp-load.php").write_text("<?php\n", encoding="utf-8")
        (self.tmp / "wp-includes").mkdir()
        self.assertTrue(wp_defaults.detect_wordpress(self.tmp))

    def test_only_wp_load_php_false(self) -> None:
        (self.tmp / "wp-load.php").write_text("<?php\n", encoding="utf-8")
        self.assertFalse(wp_defaults.detect_wordpress(self.tmp))

    def test_only_wp_includes_dir_false(self) -> None:
        (self.tmp / "wp-includes").mkdir()
        self.assertFalse(wp_defaults.detect_wordpress(self.tmp))

    def test_neither_false(self) -> None:
        self.assertFalse(wp_defaults.detect_wordpress(self.tmp))


class WpExclusionRulesTests(unittest.TestCase):
    def test_exactly_17_entries(self) -> None:
        self.assertEqual(len(wp_defaults.wp_exclusion_rules()), 17)

    def test_no_bare_wp_prefix(self) -> None:
        for rule in wp_defaults.wp_exclusion_rules():
            prefix = rule["prefix"]
            self.assertIn(prefix, ALL_WP_PREFIXES)
            self.assertNotEqual(prefix, "wp-")

    def test_all_entries_marked_excluded(self) -> None:
        rules = wp_defaults.wp_exclusion_rules()
        self.assertTrue(all(r["system"] == "excluded" for r in rules))


class ModeInitSystemPathsWordpressTests(unittest.TestCase):
    """Depends on Phase 2/T004 — expected RED until then (test-first)."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="smith-wp-init-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _target(self) -> Path:
        return self.tmp / ".smith" / "index" / "config" / "system-paths.json"

    def test_wp_fixture_17_rules_no_admin_includes_dupes(self) -> None:
        (self.tmp / "wp-load.php").write_text("<?php\n", encoding="utf-8")
        (self.tmp / "wp-admin").mkdir()
        (self.tmp / "wp-includes").mkdir()
        rc = run_mod.mode_init_system_paths(self.tmp)
        self.assertEqual(rc, 0)
        payload = json.loads(self._target().read_text(encoding="utf-8"))
        self.assertEqual(len(payload["rules"]), 17)
        systems = {r["system"] for r in payload["rules"]}
        self.assertNotIn("system-wp-admin", systems)
        self.assertNotIn("system-wp-includes", systems)

    def test_non_wp_fixture_matches_wp_defaults_none_monkeypatch(self) -> None:
        (self.tmp / "src").mkdir()
        (self.tmp / "docs").mkdir()
        original = run_mod.wp_defaults
        run_mod.wp_defaults = None
        try:
            run_mod.mode_init_system_paths(self.tmp)
        finally:
            run_mod.wp_defaults = original
        expected = json.loads(self._target().read_text(encoding="utf-8"))["rules"]

        self._target().unlink()
        run_mod.mode_init_system_paths(self.tmp)
        actual = json.loads(self._target().read_text(encoding="utf-8"))["rules"]
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
