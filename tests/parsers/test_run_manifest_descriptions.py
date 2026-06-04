"""Regression tests for /smith-index manifest description rendering.

Three related bugs fixed together (see PR for this commit):

  Bug A: Top-level manifest.md "Description" column always showed a
         title-cased slug (e.g. "Email Archive Contact Graph") and never
         the actual spec.md frontmatter `description:` field. Fix:
         IndexRun.system_descriptions loads spec.md frontmatter at run
         start; render_top_manifest threads it through _system_description.

  Bug B: render_system_manifest() was called without the `description=`
         argument from write_system_manifests(), so each system's
         `## Description` header was the generic "Files mapped to `<system>`
         by the path resolver." fallback even when the spec declared a
         description. Fix: write_system_manifests passes
         self.system_descriptions[<system>].

  Bug C: After /smith-index --describe wrote descriptions into .meta
         files, the manifest tables still reflected the pre-describe
         state because process_file's per-system entries are populated
         during the source walk (before --describe runs). Fix: new
         --rebuild-manifests mode reads existing .meta files and
         re-renders manifest.md + systems/*.md without re-parsing source.

Run:
    python3 tests/parsers/test_run_manifest_descriptions.py
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


SPEC_WITH_DESCRIPTION = """\
---
system: system-04-personal-voice
status: active
description: Personal voice training subsystem — fine-tunes per-user response style from past message archives.
paths:
  - services/voice-training
---

# system-04-personal-voice

Body content.
"""

SPEC_WITHOUT_DESCRIPTION = """\
---
system: system-99-misc
status: active
paths:
  - services/misc
---

# system-99-misc

Body content.
"""

SAMPLE_PY = '''"""Sample module."""


def fn(x: int) -> int:
    """Sample fn."""
    a = x + 1
    a = a * 2
    return a
'''

SEEDED_META = """\
# services/voice-training/foo.py
Last Updated: 2026-06-04T00:00:00Z
Language: python
Lines: 12
Hash: deadbeefcafebabe
**Description:** Sample module — provides a single utility fn used in tests.
Described-Against-Hash: deadbeefcafebabe
Described-At: 2026-06-04T00:00:00Z

## Imports

_None._

## Routes

_None._

## Classes

_None._

## Functions

- `fn(x: int) -> int` (line 4)
  Id: aaaaaaaaaaaaaaaa
  Description: SEEDED-FN-DESCRIPTION

## Exports

_None._

## Parse Errors

_None._
"""


class ManifestDescriptionTests(unittest.TestCase):
    def setUp(self) -> None:
        # macOS /tmp -> /private/tmp; resolve so IndexRun's resolve()
        # canonical form matches.
        self.tmp = Path(tempfile.mkdtemp(prefix="smith-manifest-desc-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _write_spec(self, system_dir_name: str, body: str) -> None:
        spec_dir = self.tmp / ".specify" / "systems" / system_dir_name
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "spec.md").write_text(body, encoding="utf-8")

    def _make_index_run(self) -> "run_mod.IndexRun":
        log_path = self.tmp / ".smith" / "logs" / "test.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        run = run_mod.IndexRun(project_root=self.tmp, log_path=log_path)
        run.setup_dirs()
        return run

    # ------------------------------------------------------------------
    # Bug A: top-level manifest reads spec description
    # ------------------------------------------------------------------

    def test_top_manifest_uses_spec_description_when_present(self) -> None:
        self._write_spec("system-04-personal-voice", SPEC_WITH_DESCRIPTION)
        run = self._make_index_run()
        text = run_mod.render_top_manifest(
            systems={"system-04-personal-voice": [{"path": "x", "lines": 1}]},
            stats={"total": 1, "over_200": 0, "over_300": 0, "over_500": 0},
            system_descriptions=run.system_descriptions,
        )
        self.assertIn("Personal voice training subsystem", text)
        # Sanity: legacy title-case slug should NOT appear for this system.
        # (the bug surfaced because that was the only string emitted)
        self.assertNotIn("| system-04-personal-voice | 1 | 04 Personal Voice", text)

    def test_top_manifest_falls_back_to_title_case_when_spec_missing(self) -> None:
        # No spec written at all — system_descriptions is empty.
        run = self._make_index_run()
        self.assertEqual(run.system_descriptions, {})
        text = run_mod.render_top_manifest(
            systems={"system-foo-bar": [{"path": "x", "lines": 1}]},
            stats={"total": 1, "over_200": 0, "over_300": 0, "over_500": 0},
            system_descriptions=run.system_descriptions,
        )
        # Legacy title-case behavior preserved.
        self.assertIn("Foo Bar", text)

    def test_top_manifest_falls_back_when_spec_omits_description(self) -> None:
        self._write_spec("system-99-misc", SPEC_WITHOUT_DESCRIPTION)
        run = self._make_index_run()
        # spec exists but has no description: → not in dict
        self.assertNotIn("system-99-misc", run.system_descriptions)
        text = run_mod.render_top_manifest(
            systems={"system-99-misc": [{"path": "x", "lines": 1}]},
            stats={"total": 1, "over_200": 0, "over_300": 0, "over_500": 0},
            system_descriptions=run.system_descriptions,
        )
        self.assertIn("99 Misc", text)

    # ------------------------------------------------------------------
    # Bug B: per-system manifest header gets the spec description
    # ------------------------------------------------------------------

    def test_system_manifest_header_uses_spec_description(self) -> None:
        self._write_spec("system-04-personal-voice", SPEC_WITH_DESCRIPTION)
        run = self._make_index_run()
        # Seed an entry so write_system_manifests has something to write.
        run.systems["system-04-personal-voice"] = [
            {
                "path": "services/voice-training/foo.py",
                "lines": 12,
                "exports": "(see .meta)",
                "exceeds": False,
                "module_description": "",
            }
        ]
        run.write_system_manifests()
        target = run.systems_dir / "system-04-personal-voice.md"
        text = target.read_text(encoding="utf-8")
        self.assertIn(
            "Personal voice training subsystem",
            text,
            "system manifest header should contain spec description",
        )
        # Sanity: the generic fallback should NOT appear when a real
        # description is available.
        self.assertNotIn(
            "Files mapped to `system-04-personal-voice` by the path resolver.",
            text,
        )

    def test_system_manifest_falls_back_when_no_description(self) -> None:
        # No specs written — system has no declared description.
        run = self._make_index_run()
        run.systems["system-orphan"] = [
            {
                "path": "x",
                "lines": 1,
                "exports": "(none)",
                "exceeds": False,
                "module_description": "",
            }
        ]
        run.write_system_manifests()
        text = (run.systems_dir / "system-orphan.md").read_text(encoding="utf-8")
        self.assertIn("Files mapped to `system-orphan` by the path resolver.", text)

    # ------------------------------------------------------------------
    # Bug C: --rebuild-manifests propagates module descriptions
    # ------------------------------------------------------------------

    def test_rebuild_manifests_pulls_module_description_from_meta(self) -> None:
        """The whole point: after --describe writes descriptions to .meta,
        --rebuild-manifests should pick them up and put them in the
        per-system manifest's Description column."""
        # Seed a spec so the system bucket is "system-04-personal-voice".
        self._write_spec("system-04-personal-voice", SPEC_WITH_DESCRIPTION)
        # Seed a source file under the declared path.
        rel = "services/voice-training/foo.py"
        src = self.tmp / rel
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text(SAMPLE_PY, encoding="utf-8")
        # Seed a .meta with descriptions (simulating post-describe state).
        meta_path = self.tmp / ".smith" / "index" / "files" / (rel + ".meta")
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(SEEDED_META, encoding="utf-8")

        log_path = self.tmp / ".smith" / "logs" / "rebuild.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        rc = run_mod.mode_rebuild_manifests(self.tmp, log_path)
        self.assertEqual(rc, 0)

        # System manifest's per-file Description column now shows the
        # description salvaged from .meta.
        system_md = (
            self.tmp / ".smith" / "index" / "systems" / "system-04-personal-voice.md"
        )
        self.assertTrue(system_md.exists())
        text = system_md.read_text(encoding="utf-8")
        self.assertIn(
            "Sample module — provides a single utility fn used in tests.",
            text,
        )
        # Header description is also there (Bug B coupling).
        self.assertIn("Personal voice training subsystem", text)

    def test_rebuild_manifests_no_op_when_no_index(self) -> None:
        """Should be friendly when there's no .smith/index/files/ yet."""
        log_path = self.tmp / ".smith" / "logs" / "rebuild.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        rc = run_mod.mode_rebuild_manifests(self.tmp, log_path)
        # No crash, no manifest written.
        self.assertEqual(rc, 0)
        self.assertFalse((self.tmp / ".smith" / "index" / "manifest.md").exists())

    def test_rebuild_manifests_does_not_touch_meta_files(self) -> None:
        """--rebuild-manifests must be read-only on .meta files."""
        self._write_spec("system-04-personal-voice", SPEC_WITH_DESCRIPTION)
        rel = "services/voice-training/foo.py"
        src = self.tmp / rel
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text(SAMPLE_PY, encoding="utf-8")
        meta_path = self.tmp / ".smith" / "index" / "files" / (rel + ".meta")
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(SEEDED_META, encoding="utf-8")
        before_mtime = meta_path.stat().st_mtime_ns
        before_text = meta_path.read_text(encoding="utf-8")

        log_path = self.tmp / ".smith" / "logs" / "rebuild.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        run_mod.mode_rebuild_manifests(self.tmp, log_path)

        # Content unchanged (mtime may shift if filesystem rewrites, so
        # assert content equality is the load-bearing check).
        self.assertEqual(meta_path.read_text(encoding="utf-8"), before_text)
        _ = before_mtime  # not strictly asserted, see above

    # ------------------------------------------------------------------
    # _load_system_descriptions edge cases
    # ------------------------------------------------------------------

    def test_load_system_descriptions_handles_specs_dir(self) -> None:
        """Both .specify/systems/<id>/spec.md (canonical) and specs/<id>/spec.md
        (legacy) should be readable, with .specify/ winning when both exist."""
        # Legacy specs/ location with one description.
        legacy_dir = self.tmp / "specs" / "system-foo"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        (legacy_dir / "spec.md").write_text(
            "---\nsystem: system-foo\ndescription: legacy desc\n---\n",
            encoding="utf-8",
        )
        # Canonical .specify/ location with a different description.
        canonical_dir = self.tmp / ".specify" / "systems" / "system-foo"
        canonical_dir.mkdir(parents=True, exist_ok=True)
        (canonical_dir / "spec.md").write_text(
            "---\nsystem: system-foo\ndescription: canonical desc\n---\n",
            encoding="utf-8",
        )
        run = self._make_index_run()
        self.assertEqual(run.system_descriptions.get("system-foo"), "canonical desc")

    def test_load_system_descriptions_empty_when_no_specs(self) -> None:
        run = self._make_index_run()
        self.assertEqual(run.system_descriptions, {})


if __name__ == "__main__":
    unittest.main()
