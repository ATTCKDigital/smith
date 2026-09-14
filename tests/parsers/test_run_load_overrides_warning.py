"""Unit tests for IndexRun._load_overrides()'s Part C stderr warning
(FR-14..FR-17, SC-5) — a config author who typed "overrides"/"override"/
"mappings"/"map" instead of "rules" gets exactly one diagnostic stderr
line; the parsed dict is always returned unchanged either way.

Run:
    python3 tests/parsers/test_run_load_overrides_warning.py
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
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
    spec = importlib.util.spec_from_file_location("smith_index_run_warn", RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


run_mod = _load_run_py()


class LoadOverridesWarningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="smith-overrides-warn-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.config_path = (
            self.tmp / ".smith" / "index" / "config" / "system-paths.json"
        )
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

    def _write_json_text(self, text: str) -> None:
        self.config_path.write_text(text, encoding="utf-8")

    def _make_run_capturing_stderr(self) -> tuple["run_mod.IndexRun", str]:
        log_path = self.tmp / ".smith" / "logs" / "test.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            run = run_mod.IndexRun(
                project_root=self.tmp,
                log_path=log_path,
                system_paths_json=self.config_path,
            )
        self.addCleanup(run.logger.close)
        return run, buf.getvalue()

    def test_overrides_alias_warns_once_and_returns_data_unchanged(self) -> None:
        data = {"overrides": [{"prefix": "x/", "system": "system-x"}]}
        self._write_json_text(json.dumps(data))
        run, stderr_text = self._make_run_capturing_stderr()
        lines = [ln for ln in stderr_text.splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1, f"expected exactly one line, got: {lines!r}")
        self.assertIn("overrides", lines[0])
        self.assertIn("rules", lines[0])
        self.assertEqual(run._overrides_dict, data)

    def test_rules_key_present_no_warning(self) -> None:
        data = {"rules": [{"prefix": "x/", "system": "system-x"}]}
        self._write_json_text(json.dumps(data))
        run, stderr_text = self._make_run_capturing_stderr()
        self.assertEqual(stderr_text, "")
        self.assertEqual(run._overrides_dict, data)

    def test_unrelated_key_no_warning(self) -> None:
        data = {"unrelated_key": 1}
        self._write_json_text(json.dumps(data))
        run, stderr_text = self._make_run_capturing_stderr()
        self.assertEqual(stderr_text, "")
        self.assertEqual(run._overrides_dict, data)

    def test_top_level_array_no_warning_no_crash(self) -> None:
        self._write_json_text(json.dumps([1, 2, 3]))
        run, stderr_text = self._make_run_capturing_stderr()
        self.assertEqual(stderr_text, "")
        self.assertEqual(run._overrides_dict, [1, 2, 3])

    def test_invalid_json_no_warning_returns_none(self) -> None:
        self._write_json_text("{not valid json")
        run, stderr_text = self._make_run_capturing_stderr()
        self.assertEqual(stderr_text, "")
        self.assertIsNone(run._overrides_dict)


if __name__ == "__main__":
    unittest.main()
