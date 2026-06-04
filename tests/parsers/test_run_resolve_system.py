"""Regression test for IndexRun.resolve_system passing project_root correctly.

Bug history: run.py:800 used to pass project_root="" to
path_resolver.resolve(), which silently broke Tier 1 (.specify/systems/
<id>/spec.md frontmatter lookup). When Tier 1 throws, the surrounding
`except Exception: pass` swallows the error and falls through to the
naive "system-{top_dir}" mapping. This test asserts the fixed behavior:
files matching declared paths: frontmatter resolve to their declared
system, not to the heuristic top-directory fallback.

Run:
    python3 tests/parsers/test_run_resolve_system.py
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
    """Load run.py as a module. It depends on the parsers being importable
    via sys.path manipulation it does at import time."""
    sys.path.insert(0, str(REPO / "scripts" / "parsers"))
    spec = importlib.util.spec_from_file_location("smith_index_run", RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


run_mod = _load_run_py()


class ResolveSystemTier1Tests(unittest.TestCase):
    def setUp(self) -> None:
        # On macOS /tmp is a symlink to /private/tmp; Path.resolve() in
        # IndexRun.__init__ canonicalises to /private/tmp/... so we must
        # match that here to keep `file_path.relative_to(project_root)`
        # working.
        self.tmp = Path(tempfile.mkdtemp(prefix="smith-run-resolve-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _write_spec(self, system_name: str, paths: list[str]) -> None:
        spec_dir = self.tmp / ".specify" / "systems" / system_name
        spec_dir.mkdir(parents=True, exist_ok=True)
        lines = ["---", f"system: {system_name}", "status: active", "paths:"]
        for p in paths:
            lines.append(f"  - {p}")
        lines += ["---", "", f"# {system_name}", "", "Body.", ""]
        (spec_dir / "spec.md").write_text("\n".join(lines), encoding="utf-8")

    def _write_source(self, rel_path: str) -> Path:
        full = self.tmp / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text("// source content\n", encoding="utf-8")
        return full

    def _make_index_run(self) -> "run_mod.IndexRun":
        log_path = self.tmp / ".smith" / "logs" / "test.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        return run_mod.IndexRun(
            project_root=self.tmp,
            log_path=log_path,
        )

    def test_shopify_theme_pattern_resolves_via_tier1(self) -> None:
        """Repro case from gold-canna-theme: snippets/cart-item.liquid
        was bucketed as system-snippets (top-dir heuristic) instead of
        system-01-cart (Tier 1 frontmatter)."""
        self._write_spec("system-01-cart", ["snippets/cart-", "sections/cart"])
        self._write_spec(
            "system-05-homepage",
            ["sections/hero", "templates/index"],
        )
        cart_snippet = self._write_source("snippets/cart-item.liquid")
        hero_section = self._write_source("sections/hero.liquid")

        run = self._make_index_run()
        self.assertEqual(run.resolve_system(cart_snippet), "system-01-cart")
        self.assertEqual(run.resolve_system(hero_section), "system-05-homepage")

    def test_top_dir_fallback_still_works_when_no_frontmatter(self) -> None:
        """Files with no Tier 1 / Tier 2 match still get the heuristic
        top-dir bucket (the fallback behavior is unchanged)."""
        orphan = self._write_source("randomtop/some.py")
        run = self._make_index_run()
        result = run.resolve_system(orphan)
        # Heuristic emits "system-randomtop" for top-level dirs that don't
        # match a declared system.
        self.assertTrue(
            result == "system-randomtop" or result.startswith("system-"),
            f"unexpected fallback result: {result}",
        )

    def test_root_level_file_unassigned(self) -> None:
        """File at the project root (no top-level dir) should be unassigned
        when no Tier 1 matches it."""
        root_file = self._write_source("README.py")
        run = self._make_index_run()
        self.assertEqual(run.resolve_system(root_file), "unassigned")

    def test_does_not_silently_eat_unrelated_errors(self) -> None:
        """Sanity: resolve_system on a file outside the project_root would
        raise from relative_to; we don't catch that one (only the
        path_resolver.resolve call is guarded)."""
        outside = Path(tempfile.gettempdir()) / "definitely-outside.py"
        outside.write_text("x\n", encoding="utf-8")
        try:
            run = self._make_index_run()
            with self.assertRaises(ValueError):
                run.resolve_system(outside)
        finally:
            try:
                outside.unlink()
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    unittest.main()
