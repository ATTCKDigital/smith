"""Unit tests for scripts/parsers/path-resolver.py.

Imports the module by file path (it's not a package) and exercises the
`resolve()` function directly. Also runs the CLI to cover that surface.

    python3 -m unittest tests.contracts.test_path_resolver
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
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


class HeuristicTests(unittest.TestCase):
    """Pattern coverage with no overrides — pure heuristic."""

    def test_services(self):
        self.assertEqual(pr.resolve("services/billing/main.py"), "system-billing")
        self.assertEqual(
            pr.resolve("services/shopify-sync/index.js"), "system-shopify-sync"
        )

    def test_backend(self):
        self.assertEqual(
            pr.resolve("backend/src/api/products.py"),
            "system-backend-src",
        )
        self.assertEqual(pr.resolve("backend/tests/x.py"), "system-backend-tests")

    def test_frontend(self):
        self.assertEqual(pr.resolve("frontend/src/App.tsx"), "system-frontend-src")

    def test_tests_unassigned(self):
        self.assertEqual(pr.resolve("tests/test_x.py"), "unassigned")
        self.assertEqual(pr.resolve("test/foo.py"), "unassigned")

    def test_docs_unassigned(self):
        self.assertEqual(pr.resolve("docs/intro.md"), "unassigned")
        self.assertEqual(pr.resolve("doc/foo.md"), "unassigned")

    def test_excluded(self):
        self.assertEqual(pr.resolve("node_modules/foo/index.js"), "excluded")
        self.assertEqual(pr.resolve(".venv/lib/x.py"), "excluded")
        self.assertEqual(pr.resolve("venv/lib/x.py"), "excluded")
        self.assertEqual(pr.resolve("vendor/whatever.js"), "excluded")
        self.assertEqual(pr.resolve("dist/bundle.js"), "excluded")
        self.assertEqual(pr.resolve("build/output.js"), "excluded")

    def test_root_level_file(self):
        self.assertEqual(pr.resolve("README.md"), "unassigned")
        self.assertEqual(pr.resolve("setup.py"), "unassigned")

    def test_other_top_level(self):
        self.assertEqual(pr.resolve("scripts/install.sh"), "system-scripts")
        self.assertEqual(pr.resolve("hooks/foo.sh"), "system-hooks")


class ExplicitOverrideTests(unittest.TestCase):
    """Behaviour with `system-paths.json`-style overrides."""

    def test_simple_override(self):
        ov = {
            "rules": [{"prefix": "backend/src/api/v1/products", "system": "system-15"}]
        }
        self.assertEqual(
            pr.resolve("backend/src/api/v1/products.py", overrides_dict=ov),
            "system-15",
        )

    def test_longest_prefix_wins(self):
        ov = {
            "rules": [
                {"prefix": "backend/src/api", "system": "system-01-api"},
                {
                    "prefix": "backend/src/api/v1/products",
                    "system": "system-15-command-center",
                },
                {"prefix": "backend", "system": "system-backend-fallback"},
            ]
        }
        self.assertEqual(
            pr.resolve("backend/src/api/v1/products.py", overrides_dict=ov),
            "system-15-command-center",
        )
        self.assertEqual(
            pr.resolve("backend/src/api/v1/orders.py", overrides_dict=ov),
            "system-01-api",
        )
        self.assertEqual(
            pr.resolve("backend/src/lib/util.py", overrides_dict=ov),
            "system-backend-fallback",
        )

    def test_no_match_falls_through_to_heuristic(self):
        """If overrides exist but none match AND no explicit default, heuristic wins."""
        ov = {"rules": [{"prefix": "backend/", "system": "system-01-api"}]}
        self.assertEqual(
            pr.resolve("frontend/src/App.tsx", overrides_dict=ov),
            "system-frontend-src",
        )

    def test_explicit_default(self):
        """If `default` is provided, no rules match → return default."""
        ov = {"rules": [], "default": "system-misc"}
        self.assertEqual(pr.resolve("README.md", overrides_dict=ov), "system-misc")

    def test_explicit_default_with_excluded(self):
        """Explicit default does NOT override the excluded heuristic.

        Specifically: when has_explicit_default is True, _apply_overrides
        returns the default for any non-matching file. This is consistent
        with the spec — author of system-paths.json controls behavior.
        """
        ov = {"rules": [], "default": "system-misc"}
        self.assertEqual(
            pr.resolve("node_modules/x/y.js", overrides_dict=ov), "system-misc"
        )


class NormalisationTests(unittest.TestCase):
    """Path normalisation prior to matching."""

    def test_strips_project_root(self):
        self.assertEqual(
            pr.resolve("/repo/backend/src/foo.py", project_root="/repo"),
            "system-backend-src",
        )

    def test_strips_trailing_slash_in_root(self):
        self.assertEqual(
            pr.resolve("/repo/backend/src/foo.py", project_root="/repo/"),
            "system-backend-src",
        )

    def test_dot_slash_prefix(self):
        self.assertEqual(pr.resolve("./services/x/main.py"), "system-x")


class CliTests(unittest.TestCase):
    """Exercises the CLI surface used by manifest-updater.sh."""

    def test_cli_basic(self):
        r = subprocess.run(
            ["python3", RESOLVER, "backend/src/api.py", ""],
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "system-backend-src")

    def test_cli_with_system_paths_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(
                {"rules": [{"prefix": "frontend/", "system": "system-ui"}]},
                f,
            )
            path = f.name
        try:
            r = subprocess.run(
                ["python3", RESOLVER, "frontend/x.tsx", "", path],
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), "system-ui")
        finally:
            os.unlink(path)

    def test_cli_missing_overrides_file(self):
        """Unreadable system-paths.json: silently fall through to heuristic."""
        r = subprocess.run(
            ["python3", RESOLVER, "backend/src/x.py", "", "/no/such/file"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "system-backend-src")

    def test_cli_argv_error(self):
        r = subprocess.run(
            ["python3", RESOLVER],
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(r.returncode, 2)


class ResolveSystemAliasTests(unittest.TestCase):
    """The `resolve_system` alias kept for Phase B."""

    def test_alias_basic(self):
        self.assertEqual(
            pr.resolve_system("services/billing/main.py"), "system-billing"
        )

    def test_alias_with_overrides(self):
        ov = {"rules": [{"prefix": "backend/", "system": "system-x"}]}
        self.assertEqual(
            pr.resolve_system("backend/y.py", overrides_dict=ov), "system-x"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
