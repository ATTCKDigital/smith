#!/usr/bin/env python3
"""
migrate.py — orchestrator for /smith-migrate-system-paths.

Walks `.specify/systems/system-*/spec.md` files, proposes path prefixes
from prose using `propose_paths.propose()`, and (after operator
confirmation) injects YAML frontmatter above the existing body.

Key invariants:
  - Idempotent: a re-run on a migrated project is a no-op. A file is
    considered migrated when it already has a YAML frontmatter block
    AND that block contains a non-empty `paths:` field.
  - Body bytes are preserved verbatim. Frontmatter is prepended (or, when
    a partial frontmatter already exists, the `paths:` field is inserted
    inside the existing block — body untouched).
  - Operator confirmation per-system in interactive mode. The
    `--auto-confirm` flag is for tests; production invocation by the
    skill should NOT pass it.
  - No glob characters in written paths (rejected at the propose step).

CLI:

    python3 skills/smith-migrate-system-paths/scripts/migrate.py \\
        [--project-root <path>] [--dry-run] [--auto-confirm] [--top-n N]

Exit code 0 on success (or no-op). Non-zero on hard error.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import pathlib
import re
import sys

# Make propose_paths importable when this file is invoked directly.
_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import propose_paths  # noqa: E402

_GLOB_CHARS = set("*?[]{}!")


@dataclasses.dataclass
class MigrationResult:
    spec_path: pathlib.Path
    system_id: str
    status: str  # "migrated" | "already-migrated" | "skipped-no-proposal" | "skipped-by-user" | "errored"
    paths_written: list[str] = dataclasses.field(default_factory=list)
    error: str | None = None


# --- Frontmatter helpers --------------------------------------------------

_FM_OPEN_RE = re.compile(r"^---\s*\n")


def _split_frontmatter(text: str) -> tuple[dict[str, object] | None, str, str]:
    """Return (fm_dict, fm_block_text, body_text).

    - If the file starts with `---\n` and has a closing `\n---\n`, parse
      the block into a dict and return (dict, fm_block_text, body_text)
      where fm_block_text is everything from the opening `---` line through
      (and including) the closing `---\n`.
    - Otherwise return (None, "", text).
    """
    if not text.startswith("---\n"):
        return None, "", text
    end = text.find("\n---\n", 4)
    if end == -1:
        return None, "", text
    fm_body = text[4:end]
    fm_block = text[: end + len("\n---\n")]
    body = text[end + len("\n---\n") :]

    fm: dict[str, object] = {}
    current_list_key: str | None = None
    current_list: list[str] = []
    for raw_line in fm_body.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            current_list_key = None
            continue
        if line.startswith("  - ") and current_list_key:
            current_list.append(line[4:].strip().strip('"').strip("'"))
            fm[current_list_key] = current_list
            continue
        if ":" in line and not line.startswith(" "):
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if val == "":
                current_list_key = key
                current_list = []
                fm[key] = current_list
            elif val == "[]":
                current_list_key = None
                fm[key] = []
            else:
                current_list_key = None
                fm[key] = val.strip('"').strip("'")
    return fm, fm_block, body


def _render_frontmatter(
    system_id: str, paths: list[str], status: str = "in-progress"
) -> str:
    """Build a fresh YAML frontmatter block."""
    lines = ["---", f"system: {system_id}", f"status: {status}"]
    if paths:
        lines.append("paths:")
        for p in paths:
            lines.append(f"  - {p}")
    else:
        lines.append("paths: []")
    lines.append("also_affects: []")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _insert_paths_into_existing_fm(fm_block: str, paths: list[str]) -> str:
    """Insert a `paths:` field into an existing frontmatter block.

    Inserts after the `system:` line if present, otherwise just inside the
    opening `---`. Returns the updated frontmatter block text (still ending
    with `\n---\n`).
    """
    lines = fm_block.splitlines(keepends=True)
    # Find the `system:` line index, or 1 (just after opening ---) as fallback.
    insert_idx: int | None = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith("system:"):
            insert_idx = i + 1
            break
    if insert_idx is None:
        # Insert after the opening `---` line.
        insert_idx = 1

    new_lines: list[str] = []
    if paths:
        new_lines.append("paths:\n")
        for p in paths:
            new_lines.append(f"  - {p}\n")
    else:
        new_lines.append("paths: []\n")

    return "".join(lines[:insert_idx] + new_lines + lines[insert_idx:])


# --- Status extraction (best-effort prose scan) ---------------------------

_STATUS_PROSE_RE = re.compile(
    r"^\s*\*\*Status\*\*\s*:\s*([a-z\-]+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _detect_status_from_prose(body: str) -> str:
    """Extract `**Status**: <value>` from prose body if present, else default."""
    m = _STATUS_PROSE_RE.search(body)
    if not m:
        return "in-progress"
    val = m.group(1).strip().lower()
    valid = {"draft", "in-progress", "complete", "active", "deprecated", "proposed"}
    return val if val in valid else "in-progress"


# --- Per-system migration logic -------------------------------------------


def _is_already_migrated(fm: dict[str, object] | None) -> bool:
    """A file is `already migrated` when it has a frontmatter dict AND a
    non-empty `paths:` list inside it.
    """
    if not fm:
        return False
    paths = fm.get("paths")
    return isinstance(paths, list) and len(paths) > 0


def _prompt_user(message: str, default_yes: bool = True) -> bool:
    """Interactive y/n prompt. Defaults to yes."""
    suffix = "[Y/n]" if default_yes else "[y/N]"
    try:
        resp = input(f"{message} {suffix} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if not resp:
        return default_yes
    return resp in {"y", "yes"}


def _present_proposal(system_id: str, proposals: list[propose_paths.Proposal]) -> None:
    print(f"\nSystem `{system_id}` — proposed paths:")
    if not proposals:
        print("  (no path candidates found in prose)")
        return
    for p in proposals:
        print(f"  - {p.prefix}    (score={p.score}, matches={p.occurrences})")
        for ex in p.excerpts[:2]:
            print(f"      | {ex[:100]}")


def migrate_one(
    spec_path: pathlib.Path,
    *,
    top_n: int = 5,
    auto_confirm: bool = False,
    dry_run: bool = False,
    interactive: bool = True,
) -> MigrationResult:
    """Migrate a single `.specify/systems/<id>/spec.md` file."""
    system_id = spec_path.parent.name

    try:
        original_text = spec_path.read_text(encoding="utf-8")
    except OSError as e:
        return MigrationResult(spec_path, system_id, "errored", error=str(e))

    fm, fm_block, body = _split_frontmatter(original_text)

    if _is_already_migrated(fm):
        return MigrationResult(spec_path, system_id, "already-migrated")

    proposals = propose_paths.propose(body, top_n=top_n)
    if not proposals:
        if interactive and not auto_confirm:
            _present_proposal(system_id, proposals)
            print("  (skipping — nothing to propose)")
        return MigrationResult(spec_path, system_id, "skipped-no-proposal")

    proposed_prefixes = [p.prefix for p in proposals]
    # Defensive — propose_paths.propose() already filters globs, but belt+suspenders.
    proposed_prefixes = [
        p for p in proposed_prefixes if not any(c in _GLOB_CHARS for c in p)
    ]
    # Ensure trailing slash.
    proposed_prefixes = [(p if p.endswith("/") else p + "/") for p in proposed_prefixes]

    if not auto_confirm and interactive:
        _present_proposal(system_id, proposals)
        if not _prompt_user(f"Accept these paths for `{system_id}`?", default_yes=True):
            return MigrationResult(spec_path, system_id, "skipped-by-user")

    if dry_run:
        return MigrationResult(
            spec_path, system_id, "migrated", paths_written=proposed_prefixes
        )

    # Build the new file content.
    if fm is None:
        # No frontmatter at all — prepend a fresh block above the body.
        status = _detect_status_from_prose(body)
        new_fm = _render_frontmatter(system_id, proposed_prefixes, status=status)
        new_text = new_fm + original_text  # body == original_text here
    else:
        # Existing frontmatter without paths — splice in just the paths field.
        updated_fm_block = _insert_paths_into_existing_fm(fm_block, proposed_prefixes)
        new_text = updated_fm_block + body

    # Atomic write via tempfile + rename.
    tmp = spec_path.with_suffix(spec_path.suffix + ".tmp")
    try:
        tmp.write_text(new_text, encoding="utf-8")
        os.replace(tmp, spec_path)
    except OSError as e:
        return MigrationResult(spec_path, system_id, "errored", error=str(e))

    return MigrationResult(
        spec_path, system_id, "migrated", paths_written=proposed_prefixes
    )


def find_system_specs(project_root: pathlib.Path) -> list[pathlib.Path]:
    systems_dir = project_root / ".specify" / "systems"
    if not systems_dir.is_dir():
        return []
    return sorted(systems_dir.glob("system-*/spec.md"))


def run(
    project_root: pathlib.Path,
    *,
    top_n: int = 5,
    auto_confirm: bool = False,
    dry_run: bool = False,
    interactive: bool = True,
) -> list[MigrationResult]:
    specs = find_system_specs(project_root)
    if not specs:
        print(f"No .specify/systems/system-*/spec.md found under {project_root}")
        return []

    results: list[MigrationResult] = []
    for spec in specs:
        res = migrate_one(
            spec,
            top_n=top_n,
            auto_confirm=auto_confirm,
            dry_run=dry_run,
            interactive=interactive,
        )
        results.append(res)

    # Summary report.
    migrated = [r for r in results if r.status == "migrated"]
    already = [r for r in results if r.status == "already-migrated"]
    no_prop = [r for r in results if r.status == "skipped-no-proposal"]
    by_user = [r for r in results if r.status == "skipped-by-user"]
    errored = [r for r in results if r.status == "errored"]

    print("")
    print("=" * 60)
    print("Migration summary")
    print("=" * 60)
    print(f"  migrated:                       {len(migrated)}")
    print(f"  skipped (already has paths):    {len(already)}")
    print(f"  skipped (no prose hints):       {len(no_prop)}")
    print(f"  skipped (by user):              {len(by_user)}")
    if errored:
        print(f"  errored:                        {len(errored)}")
        for r in errored:
            print(f"    - {r.spec_path}: {r.error}")
    if dry_run:
        print("  (DRY RUN — no files were modified)")
    return results


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1].strip())
    ap.add_argument("--project-root", default=".", help="Project root (default: cwd)")
    ap.add_argument("--top-n", type=int, default=5, help="Max proposals per system")
    ap.add_argument(
        "--dry-run", action="store_true", help="Show proposals, don't write"
    )
    ap.add_argument(
        "--auto-confirm",
        action="store_true",
        help="Accept all proposals without prompting (for tests)",
    )
    ap.add_argument(
        "--non-interactive",
        action="store_true",
        help="Suppress prompts entirely (combine with --auto-confirm)",
    )
    args = ap.parse_args(argv)

    project_root = pathlib.Path(args.project_root).resolve()
    results = run(
        project_root,
        top_n=args.top_n,
        auto_confirm=args.auto_confirm,
        dry_run=args.dry_run,
        interactive=not args.non_interactive,
    )
    return 0 if not any(r.status == "errored" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
