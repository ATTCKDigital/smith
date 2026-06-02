"""Regression test: /smith-index runtime works against the FLAT production
install layout.

The bug this guards against: scripts/smith-index/run.py computes
`PARSER_DIR_REPO = REPO_ROOT / "scripts" / "parsers"`, where REPO_ROOT is
`Path(__file__).resolve().parent.parent.parent`. In the dev-tree layout
(running from a smith-repo clone), that resolves to
`<clone>/scripts/parsers/` and works. But when run.py is installed
globally at `~/.smith/scripts/smith-index/run.py`, REPO_ROOT computes to
`~/.smith/` and PARSER_DIR_REPO points at `~/.smith/scripts/parsers/` —
which does NOT exist in the install layout because install-parsers.sh
stages parsers FLAT at `~/.smith/scripts/` (no `parsers/` subdir, which is
the correct install convention).

Pre-fix symptom: `path_resolver = None` after run.py imports → tier-1 of
the path resolver never fires → projects with declared `.specify/systems/`
get bucketed by the heuristic instead.

Post-fix behavior: run.py tries `PARSER_DIR_REPO/<name>` first (dev-tree)
and falls back to `PARSER_DIR_GLOBAL/<name>` (= `~/.smith/scripts/<name>`,
flat). This test exercises that fallback path.

Run:
    python3 tests/skills/test_smith_index_global_install_layout.py
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
RUN_PY = REPO / "scripts" / "smith-index" / "run.py"
PARSERS_DIR = REPO / "scripts" / "parsers"


def _load_run_py_with_home(fake_home: Path):
    """Load run.py with HOME pointed at a tempdir mimicking the install layout."""
    original_home = os.environ.get("HOME")
    os.environ["HOME"] = str(fake_home)
    # Force fresh imports so PARSER_DIR_GLOBAL re-resolves against the fake HOME.
    for name in ("path_resolver", "meta_describe", "run"):
        sys.modules.pop(name, None)
    try:
        spec = importlib.util.spec_from_file_location("run", RUN_PY)
        if spec is None or spec.loader is None:
            raise RuntimeError("could not load run.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if original_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = original_home


class GlobalInstallLayoutTests(unittest.TestCase):
    """run.py must resolve parser modules from the flat ~/.smith/scripts/
    layout when the dev-tree layout is absent."""

    def _stage_flat_install(self, fake_home: Path) -> Path:
        """Mimic install-parsers.sh: stage parsers FLAT at <home>/.smith/scripts/.

        Also stages run.py inside the install location so its REPO_ROOT
        resolves to <home>/.smith/ — the exact case that broke pre-fix.
        Returns the directory where run.py was staged.
        """
        scripts_dir = fake_home / ".smith" / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        # Flat install — no parsers/ subdir, matching install-parsers.sh behavior.
        shutil.copy(PARSERS_DIR / "path-resolver.py", scripts_dir / "path-resolver.py")
        shutil.copy(PARSERS_DIR / "meta_describe.py", scripts_dir / "meta_describe.py")
        shutil.copy(PARSERS_DIR / "parse-python.py", scripts_dir / "parse-python.py")
        shutil.copy(PARSERS_DIR / "parse-js.js", scripts_dir / "parse-js.js")
        # Stage run.py inside the install location so REPO_ROOT = <home>/.smith/.
        install_run_dir = scripts_dir / "smith-index"
        install_run_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(RUN_PY, install_run_dir / "run.py")
        return install_run_dir

    def test_flat_install_layout_resolves_path_resolver(self):
        """Pre-fix this fails — PARSER_DIR_REPO points at ~/.smith/scripts/parsers/
        which doesn't exist, and the loader has no fallback. Post-fix it
        resolves via PARSER_DIR_GLOBAL."""
        with tempfile.TemporaryDirectory(prefix="smith-bugfix-") as tmp:
            fake_home = Path(tmp)
            install_run_dir = self._stage_flat_install(fake_home)

            # Load the INSTALLED copy of run.py so REPO_ROOT == ~/.smith/.
            original_home = os.environ.get("HOME")
            os.environ["HOME"] = str(fake_home)
            for name in ("path_resolver", "meta_describe", "run"):
                sys.modules.pop(name, None)
            try:
                spec = importlib.util.spec_from_file_location(
                    "run", install_run_dir / "run.py"
                )
                self.assertIsNotNone(spec)
                self.assertIsNotNone(spec.loader)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                self.assertIsNotNone(
                    module.path_resolver,
                    "path_resolver must load from PARSER_DIR_GLOBAL "
                    "(~/.smith/scripts/) when PARSER_DIR_REPO has no parsers/ subdir",
                )
                self.assertTrue(
                    hasattr(module.path_resolver, "resolve"),
                    "path_resolver module must expose resolve()",
                )
            finally:
                if original_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = original_home

    def test_flat_install_layout_resolves_meta_describe(self):
        """Same fallback applies to meta_describe loading."""
        with tempfile.TemporaryDirectory(prefix="smith-bugfix-") as tmp:
            fake_home = Path(tmp)
            install_run_dir = self._stage_flat_install(fake_home)

            original_home = os.environ.get("HOME")
            os.environ["HOME"] = str(fake_home)
            for name in ("path_resolver", "meta_describe", "run"):
                sys.modules.pop(name, None)
            try:
                spec = importlib.util.spec_from_file_location(
                    "run", install_run_dir / "run.py"
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                self.assertIsNotNone(
                    module._meta_describe,
                    "meta_describe must load from PARSER_DIR_GLOBAL when "
                    "PARSER_DIR_REPO has no parsers/ subdir",
                )
            finally:
                if original_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = original_home

    def test_dev_tree_layout_still_works(self):
        """Regression check: the dev-tree path (scripts/parsers/) must still
        be preferred when present — the fallback should not break the
        existing happy path."""
        # Load run.py from its actual dev-tree location; PARSER_DIR_REPO is
        # <repo>/scripts/parsers/ which exists.
        for name in ("path_resolver", "meta_describe", "run"):
            sys.modules.pop(name, None)
        spec = importlib.util.spec_from_file_location("run", RUN_PY)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        self.assertIsNotNone(module.path_resolver)
        self.assertIsNotNone(module._meta_describe)


if __name__ == "__main__":
    unittest.main(verbosity=2)
