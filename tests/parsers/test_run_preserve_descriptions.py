"""Regression test for run.py process_file's description preservation.

Bug history: scripts/smith-index/run.py:865 called render_meta() WITHOUT
existing_descriptions, then wrote the (description-less) .meta to disk
at line 868. The "preservation" code at lines 882-891 then read the
just-written file, which was already description-less, so module_desc
came out empty AND every per-method Description: line was destroyed.

Result: every full /smith-index rebuild after PR #21 silently wiped the
v2 description layer from every .meta file. Hit by armory tonight after
~26.7M Haiku tokens worth of descriptions.

This test asserts the fix: pre-seed a .meta with a description layer,
run process_file on the corresponding source file, then verify the
description layer survives the rebuild AND that entry["module_description"]
is populated for the per-system manifest.

Run:
    python3 tests/parsers/test_run_preserve_descriptions.py
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
import textwrap
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


SAMPLE_SOURCE = '''"""Sample module for description-preservation test."""


def first_func(x: int) -> int:
    """First func."""
    result = x + 1
    result = result * 2
    result = result - 3
    return result


def second_func(y: str) -> str:
    """Second func."""
    out = y.strip()
    out = out.upper()
    out = out.replace(" ", "_")
    return out
'''


def _seed_meta_with_descriptions(meta_path: Path, source_path: Path) -> None:
    """Write a .meta file matching the fix's expected v2 shape: structural
    sections + description layer (**Description:**, Described-Against-Hash,
    Described-At, per-method Description: lines).

    We don't need to compute the real method ids — render_meta only uses
    them to splice descriptions back via existing_descriptions, and our
    assertion is that the layer fields survive.
    """
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(
        textwrap.dedent(
            """\
            # services/sample/foo.py
            Last Updated: 2026-06-04T00:00:00Z
            Language: python
            Lines: 18
            Hash: abc123
            **Description:** Sample module — describes a synthetic two-function tool used in tests.
            Described-Against-Hash: abc123
            Described-At: 2026-06-04T00:00:00Z

            ## Imports

            _None._

            ## Routes

            _None._

            ## Classes

            _None._

            ## Functions

            - `first_func(x: int) -> int` (line 4)
              Id: aaaaaaaaaaaaaaaa
              Description: SEEDED-FIRST-FUNC-DESCRIPTION
            - `second_func(y: str) -> str` (line 12)
              Id: bbbbbbbbbbbbbbbb
              Description: SEEDED-SECOND-FUNC-DESCRIPTION

            ## Exports

            _None._

            ## Parse Errors

            _None._
            """
        ),
        encoding="utf-8",
    )


class PreserveDescriptionsTests(unittest.TestCase):
    def setUp(self) -> None:
        # macOS /tmp -> /private/tmp; resolve so paths line up with
        # IndexRun.__init__'s self.project_root.resolve().
        self.tmp = Path(tempfile.mkdtemp(prefix="smith-preserve-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        # Create the source file
        self.rel = "services/sample/foo.py"
        self.src = self.tmp / self.rel
        self.src.parent.mkdir(parents=True, exist_ok=True)
        self.src.write_text(SAMPLE_SOURCE, encoding="utf-8")
        # Pre-seed the .meta with a description layer
        self.meta_path = self.tmp / ".smith" / "index" / "files" / (self.rel + ".meta")
        _seed_meta_with_descriptions(self.meta_path, self.src)

    def _make_index_run(self) -> "run_mod.IndexRun":
        log_path = self.tmp / ".smith" / "logs" / "test.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        run = run_mod.IndexRun(project_root=self.tmp, log_path=log_path)
        run.setup_dirs()
        return run

    def test_module_description_survives_rebuild(self) -> None:
        """The module-level **Description:** line in the pre-seeded .meta
        must survive a process_file call."""
        run = self._make_index_run()
        run.process_file(self.src)
        new_text = self.meta_path.read_text(encoding="utf-8")
        self.assertIn(
            "**Description:** Sample module — describes a synthetic two-function tool used in tests.",
            new_text,
        )

    def test_described_against_hash_survives_rebuild(self) -> None:
        """The Described-Against-Hash provenance line must survive."""
        run = self._make_index_run()
        run.process_file(self.src)
        new_text = self.meta_path.read_text(encoding="utf-8")
        self.assertIn("Described-Against-Hash: abc123", new_text)
        self.assertIn("Described-At: 2026-06-04T00:00:00Z", new_text)

    def test_per_method_descriptions_survive_rebuild(self) -> None:
        """Per-method Description: lines under ## Functions must survive
        (note: method ids in the seed may not match real parser output;
        render_meta passes them through the existing_descriptions dict
        keyed by id, so they survive ONLY if the ids match what the
        parser emits. We assert the BUG-FIX SHAPE: existing descriptions
        for ids that ARE in the current parser output survive)."""
        run = self._make_index_run()
        # Pull qualifying ids from the parser to inject real ids into the
        # pre-seeded .meta.
        ext = self.src.suffix
        resolution = run_mod.resolve_parser(ext, self.tmp)
        self.assertIsNotNone(resolution)
        lang, parser_path = resolution
        parsed = run_mod.run_parser(parser_path, lang, self.src)
        fns = parsed.get("functions") or []
        self.assertGreaterEqual(len(fns), 2, "parser should find both functions")
        real_first_id = fns[0].get("id")
        real_second_id = fns[1].get("id")
        # Rewrite the .meta with the REAL ids so existing_descriptions
        # will splice them back correctly.
        self.meta_path.write_text(
            self.meta_path.read_text(encoding="utf-8")
            .replace("aaaaaaaaaaaaaaaa", real_first_id)
            .replace("bbbbbbbbbbbbbbbb", real_second_id),
            encoding="utf-8",
        )
        run.process_file(self.src)
        new_text = self.meta_path.read_text(encoding="utf-8")
        self.assertIn("SEEDED-FIRST-FUNC-DESCRIPTION", new_text)
        self.assertIn("SEEDED-SECOND-FUNC-DESCRIPTION", new_text)

    def test_systems_entry_module_description_populated(self) -> None:
        """run.systems[<sys>] is what drives the per-system manifest's
        Description column. Confirm module_description is non-empty when
        the .meta has one."""
        run = self._make_index_run()
        result = run.process_file(self.src)
        self.assertIsNotNone(result, "process_file returned None")
        # The per-system entry got registered in run.systems
        system = result["system"]
        self.assertIn(system, run.systems)
        entries = run.systems[system]
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertIn("module_description", entry)
        self.assertNotEqual(
            entry["module_description"],
            "",
            "module_description was empty after rebuild — preservation bug regression",
        )
        self.assertIn("Sample module", entry["module_description"])

    def test_fresh_meta_without_descriptions_still_works(self) -> None:
        """If the .meta doesn't exist yet, process_file should still
        succeed (no existing descriptions to preserve, but the rebuild
        path still has to work)."""
        # Remove the seeded .meta
        self.meta_path.unlink()
        run = self._make_index_run()
        result = run.process_file(self.src)
        self.assertIsNotNone(result)
        # No descriptions existed, so the systems-entry module_description is empty
        system = result["system"]
        entries = run.systems.get(system, [])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].get("module_description"), "")
        # But the .meta itself should have been created
        self.assertTrue(self.meta_path.exists())

    def test_v1_meta_without_description_layer_round_trips(self) -> None:
        """A v1 .meta (no description layer) should round-trip without
        adding any phantom description lines."""
        # Strip the description layer from the seeded .meta
        text = self.meta_path.read_text(encoding="utf-8")
        text = "\n".join(
            line
            for line in text.splitlines()
            if not line.startswith("**Description:**")
            and not line.startswith("Described-")
            and "Description: SEEDED-" not in line
        )
        self.meta_path.write_text(text + "\n", encoding="utf-8")
        run = self._make_index_run()
        result = run.process_file(self.src)
        self.assertIsNotNone(result)
        new_text = self.meta_path.read_text(encoding="utf-8")
        # No phantom description fields added
        self.assertNotIn("**Description:**", new_text)
        self.assertNotIn("Described-Against-Hash:", new_text)
        system = result["system"]
        entries = run.systems.get(system, [])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].get("module_description"), "")


if __name__ == "__main__":
    unittest.main()
