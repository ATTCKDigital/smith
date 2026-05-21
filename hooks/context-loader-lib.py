#!/usr/bin/env python3
"""
context-loader-lib.py — heavy lifting for the context-loader.sh hook.

Three sub-commands:

  resolve-config <skill>
      Resolve the 4-tier per-skill context-manifest.json config and
      print the merged JSON to stdout.

  compose-injection <skill> <session_id>
      Read stdin JSON ({"prompt": "...", "session_id": "...", "cwd": "..."}),
      resolve config, load vault sections, optionally read the manifest,
      and print a single hookSpecificOutput JSON response to stdout.
      All paths are resolved relative to the cwd from the input.

  detect-skill < user-message-string
      Read stdin as a user message; print the matched skill name or
      empty string on no match. (Optional convenience — bash wrapper
      may handle this itself.)

Performance target: <5s p95 including any sub-agent spawn. In practice
the bulk is vault file IO + (optional) navigator subprocess; the merge
+ markdown assembly is sub-100ms.

Sub-agent spawn strategy (v1): we DO NOT spawn a sub-agent in this hook.
Instead, when config.navigator is true and .smith/index/manifest.md
exists, we read the manifest + relevant system manifests directly and
inject their contents. The /smith-navigate skill remains usable for
ad-hoc lookups in interactive sessions; running it here would require a
nested `claude` CLI invocation which is fragile and slow. See
Decision-B note in context-loader.sh comments.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------

THIS_FILE = Path(__file__).resolve()
HOOK_DIR = THIS_FILE.parent
REPO_ROOT_CANDIDATES = [
    HOOK_DIR.parent,  # repo dev layout
]

# Locations to search for the Tier 2 (repo-shipped) default config.
REPO_DEFAULT_CANDIDATES = [
    HOOK_DIR.parent
    / "skills"
    / "smith-index"
    / "templates"
    / "context-manifest.default.json",
    HOOK_DIR.parent / "templates" / "context-manifest.default.json",
    Path.home()
    / ".claude"
    / "skills"
    / "smith-index"
    / "templates"
    / "context-manifest.default.json",
    Path.home() / ".smith" / "templates" / "context-manifest.default.json",
]

# Tier 3: user-global override.
USER_GLOBAL_CONFIG = Path.home() / ".smith" / "config" / "context-manifest.json"

# Tier 1: built-in fallback (compiled in here).
BUILTIN_DEFAULT: dict = {
    "_meta": {"version": 1, "tier_label": "builtin-fallback"},
    "_default": {
        "vault": {
            "sessions": 3,
            "ledger": "top-20",
            "bank": "recent",
            "queue": "pending",
            "agents": "recent",
        },
        "navigator": False,
        "navigator_scope": "task_specific",
        "system_specs": "none",
    },
}

# Smith skill detection — slash commands + natural-language triggers.
SLASH_PATTERN = re.compile(
    r"/smith-(new|bugfix|debug|build|audit|vault|help|bank|explore|"
    r"navigate|index|todo|queue|reflect|finish|plan|tasks|specify|"
    r"implement|analyze|checklist|design|report|migrate-specs|ledger|"
    r"timesheet|taskstoissues|constitution|clarify)\b",
    re.IGNORECASE,
)

# Natural-language trigger phrases (mirror Rule 2 of global CLAUDE.md).
# Maps a phrase substring → skill name.
NL_TRIGGERS: list[tuple[str, str]] = [
    # /smith-new
    ("start a smith workflow", "smith-new"),
    ("let's smith this", "smith-new"),
    ("lets smith this", "smith-new"),
    ("kick off a new feature", "smith-new"),
    ("let's build this", "smith-new"),
    ("lets build this", "smith-new"),
    ("start a new workflow", "smith-new"),
    ("can you smith this", "smith-new"),
    # /smith-debug
    ("debug this", "smith-debug"),
    ("help me debug", "smith-debug"),
    ("something is broken", "smith-debug"),
    ("can you investigate", "smith-debug"),
    # /smith-bugfix
    ("fix this", "smith-bugfix"),
    ("bugfix this", "smith-bugfix"),
    ("quick fix for", "smith-bugfix"),
    ("patch this", "smith-bugfix"),
    ("just fix", "smith-bugfix"),
    # /smith-bank
    ("bank this idea", "smith-bank"),
    ("bank this for later", "smith-bank"),
    ("save this for later", "smith-bank"),
    ("come back to this", "smith-bank"),
    ("park this idea", "smith-bank"),
    ("stash this thought", "smith-bank"),
    ("deposit this", "smith-bank"),
]


# ----------------------------------------------------------------------------
# Skill detection
# ----------------------------------------------------------------------------


def detect_skill(prompt: str) -> str | None:
    """Return the canonical skill name (e.g. 'smith-new') or None."""
    if not prompt:
        return None
    m = SLASH_PATTERN.search(prompt)
    if m:
        return "smith-" + m.group(1).lower()
    low = prompt.lower()
    for phrase, skill in NL_TRIGGERS:
        if phrase in low:
            return skill
    return None


# ----------------------------------------------------------------------------
# 4-tier config resolution
# ----------------------------------------------------------------------------


def _load_json(path: Path) -> dict | None:
    if not path or not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _find_repo_default() -> tuple[dict | None, str | None]:
    for cand in REPO_DEFAULT_CANDIDATES:
        if cand.exists():
            data = _load_json(cand)
            if data:
                return data, str(cand)
    return None, None


def _merge_skill(base: dict, override: dict) -> dict:
    """Field-level merge for one skill block. Per data-model.md section 5:
    scalars replace, nested objects (`vault`) merge per-key."""
    out = dict(base or {})
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            merged = dict(out[k])
            merged.update(v)
            out[k] = merged
        else:
            out[k] = v
    return out


def resolve_config(skill: str, project_root: Path) -> tuple[dict, list[str]]:
    """Resolve the effective config for `skill` through 4 tiers.

    Returns (effective_config_dict, tiers_used) where tiers_used is a
    short label list like ["1", "2", "4"] tracking which tiers actually
    contributed.
    """
    tiers_used: list[str] = []

    # Tier 1: built-in.
    eff: dict = dict(BUILTIN_DEFAULT.get("_default", {}))
    tiers_used.append("1")

    # Tier 2: repo-shipped default.
    repo_data, _repo_path = _find_repo_default()
    if repo_data:
        d2 = repo_data.get("_default") or {}
        eff = _merge_skill(eff, d2)
        s2 = repo_data.get(skill) or {}
        if s2:
            eff = _merge_skill(eff, s2)
        tiers_used.append("2")

    # Tier 3: user global.
    user_data = _load_json(USER_GLOBAL_CONFIG)
    if user_data:
        d3 = user_data.get("_default") or {}
        eff = _merge_skill(eff, d3)
        s3 = user_data.get(skill) or {}
        if s3:
            eff = _merge_skill(eff, s3)
        tiers_used.append("3")

    # Tier 4: project override.
    project_config = (
        project_root / ".smith" / "index" / "config" / "context-manifest.json"
    )
    proj_data = _load_json(project_config)
    if proj_data:
        d4 = proj_data.get("_default") or {}
        eff = _merge_skill(eff, d4)
        s4 = proj_data.get(skill) or {}
        if s4:
            eff = _merge_skill(eff, s4)
        tiers_used.append("4")

    # Apply skill defaults if nothing matched skill name (smith-vault, etc.
    # get their _default-only resolution).
    return eff, tiers_used


# ----------------------------------------------------------------------------
# Vault loading
# ----------------------------------------------------------------------------


def _list_recent(dir_path: Path, n: int = 5, pattern: str = "*.md") -> list[Path]:
    if not dir_path.is_dir():
        return []
    try:
        files = [p for p in dir_path.glob(pattern) if p.is_file()]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return files[:n]
    except OSError:
        return []


def _summarize_file_brief(p: Path, max_chars: int = 80) -> str:
    """First non-empty line, truncated, for a brief vault listing."""
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip().lstrip("#").strip()
                if line:
                    if len(line) > max_chars:
                        return line[: max_chars - 1] + "…"
                    return line
    except OSError:
        return ""
    return ""


def _resolve_sessions_count(value, default: int = 3) -> int | str:
    """Coerce vault.sessions config value to N or 'all'/'none'."""
    if value in ("all", "none"):
        return value
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_vault_sections(project_root: Path, config: dict) -> list[str]:
    """Read vault per config; return list of markdown section blocks."""
    out: list[str] = []
    vault = project_root / ".smith" / "vault"
    vcfg = config.get("vault") or {}

    # Sessions.
    sess_cfg = _resolve_sessions_count(vcfg.get("sessions", 3))
    if sess_cfg != "none" and sess_cfg != 0:
        sessions_dir = vault / "sessions"
        n = 5 if sess_cfg == "all" else int(sess_cfg)
        recent = _list_recent(sessions_dir, n=n)
        if recent:
            lines = [f"### Vault — Recent Sessions ({len(recent)})"]
            for p in recent:
                brief = _summarize_file_brief(p)
                lines.append(
                    f"- **{p.stem}** — {brief} [`{_relpath(p, project_root)}`]"
                )
            out.append("\n".join(lines))

    # Ledger.
    ledger_cfg = vcfg.get("ledger", "top-20")
    if ledger_cfg and ledger_cfg != "none":
        ledger_dir = vault / "ledger"
        if ledger_dir.is_dir():
            entries: list[str] = []
            for sub in (
                "patterns.md",
                "antipatterns.md",
                "tool-preferences.md",
                "edge-cases.md",
            ):
                p = ledger_dir / sub
                if p.exists():
                    try:
                        text = p.read_text(encoding="utf-8")
                        count = sum(
                            1
                            for line in text.splitlines()
                            if line.startswith("- ") or line.startswith("* ")
                        )
                        entries.append(
                            f"- {sub.replace('.md', '').title()}: "
                            f"{count} entries — see `.smith/vault/ledger/{sub}`"
                        )
                    except OSError:
                        pass
            if entries:
                out.append(f"### Vault — Ledger ({ledger_cfg})\n" + "\n".join(entries))

    # Bank.
    bank_cfg = vcfg.get("bank", "recent")
    if bank_cfg and bank_cfg != "none":
        bank_dir = vault / "bank"
        if bank_dir.is_dir():
            n = 10 if bank_cfg == "all" else 3
            files = _list_recent(bank_dir, n=n)
            if files:
                lines = [f"### Vault — Bank ({bank_cfg})"]
                for p in files:
                    brief = _summarize_file_brief(p)
                    lines.append(f"- {p.stem} — {brief}")
                out.append("\n".join(lines))

    # Queue.
    queue_cfg = vcfg.get("queue", "pending")
    if queue_cfg and queue_cfg != "none":
        queue_dir = vault / "queue"
        if queue_dir.is_dir():
            # Count pending vs done by reading queue.md/index.md, or by listing.
            pending = list(queue_dir.glob("*.md"))
            if queue_cfg == "pending":
                # Best effort: skip files with "done" in the name.
                pending = [p for p in pending if "done" not in p.name.lower()]
            if pending:
                lines = [f"### Vault — Queue ({queue_cfg}: {len(pending)})"]
                for p in pending[:10]:
                    brief = _summarize_file_brief(p)
                    lines.append(f"- [{p.stem}] {brief}")
                out.append("\n".join(lines))

    # Agents.
    agents_cfg = vcfg.get("agents", "recent")
    if agents_cfg and agents_cfg != "none":
        agents_dir = vault / "agents"
        if agents_dir.is_dir():
            n = 20 if agents_cfg == "all" else 3
            files = _list_recent(agents_dir, n=n)
            if files:
                out.append(
                    f"### Vault — Sub-agent Memory ({len(files)} files)\n"
                    + "\n".join(f"- `{_relpath(p, project_root)}`" for p in files)
                )

    return out


def _relpath(p: Path, root: Path) -> str:
    try:
        return str(p.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(p)


# ----------------------------------------------------------------------------
# Navigator (manifest reader — v1 in-process)
# ----------------------------------------------------------------------------


def load_navigator_section(project_root: Path) -> tuple[str | None, str]:
    """Read .smith/index/manifest.md and produce a Navigator-style block.

    v1 implementation: instead of spawning a Haiku sub-agent (which is
    slow and fragile from a hook), we directly inline the manifest +
    relevant system manifests. The skill /smith-navigate remains usable
    for ad-hoc invocations.

    Returns (markdown_block, status) where status is one of:
      "ok"       — manifest read and included
      "missing"  — .smith/index/manifest.md not found
      "empty"    — manifest exists but has no systems
    """
    manifest = project_root / ".smith" / "index" / "manifest.md"
    if not manifest.exists():
        return None, "missing"
    try:
        text = manifest.read_text(encoding="utf-8")
    except OSError:
        return None, "missing"

    if not text.strip():
        return None, "empty"

    # Trim to <= 60 lines for injection budget.
    lines = text.splitlines()
    if len(lines) > 60:
        lines = lines[:60] + [
            "",
            f"_…manifest truncated ({len(text.splitlines())} total lines)._",
        ]
    block_parts = ["### Manifest Snapshot", "", *lines]

    # Also surface large/over-threshold files from system manifests if present.
    systems_dir = project_root / ".smith" / "index" / "systems"
    if systems_dir.is_dir():
        large_files: list[str] = []
        for sm in sorted(systems_dir.glob("*.md"))[:5]:
            try:
                stext = sm.read_text(encoding="utf-8")
            except OSError:
                continue
            for line in stext.splitlines():
                if "⚠️" in line and "|" in line:
                    large_files.append(f"  - ({sm.stem}) {line.strip()}")
                    if len(large_files) >= 10:
                        break
            if len(large_files) >= 10:
                break
        if large_files:
            block_parts.extend(["", "### Files > 300 lines (advisory)", *large_files])

    return "\n".join(block_parts), "ok"


# ----------------------------------------------------------------------------
# Soft warning marker (Q10: once per session)
# ----------------------------------------------------------------------------


def soft_warn_should_emit(project_root: Path, session_id: str) -> bool:
    """Return True iff we should emit the manifest-missing warning for this
    session. Touches the marker on first invocation."""
    if not session_id:
        # No session id → emit anyway (no dedup).
        return True
    marker_dir = project_root / ".smith" / "vault"
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker = marker_dir / f".warned-manifest-missing-{session_id}"
    if marker.exists():
        return False
    try:
        marker.touch(exist_ok=True)
    except OSError:
        pass
    return True


# ----------------------------------------------------------------------------
# Injection assembly
# ----------------------------------------------------------------------------


def compose_injection(
    skill: str,
    project_root: Path,
    session_id: str,
    config: dict,
    tiers_used: list[str],
    navigator_status: str,
    navigator_block: str | None,
    soft_warn: bool,
    vault_blocks: list[str],
) -> str:
    """Assemble the additionalContext markdown."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    flags: list[str] = []
    if navigator_status == "missing":
        flags.append("manifest=missing")
    elif navigator_status == "timeout":
        flags.append("navigator=timeout")
    elif navigator_status == "error":
        flags.append("navigator=error")
    flag_suffix = "; " + "; ".join(flags) if flags else ""
    tier_label = ",".join(tiers_used)
    header = (
        f"<!-- smith-context-injection v1; skill={skill}; "
        f"tier={tier_label}; ts={ts}{flag_suffix} -->"
    )
    parts: list[str] = [header, "", "## Smith Context", ""]

    if navigator_status == "missing" and soft_warn:
        parts.append(
            "> ⚠️ Manifest not initialized — run `/smith-index` to enable "
            "structured context retrieval. Proceeding with vault context only."
        )
        parts.append("")

    if vault_blocks:
        parts.extend(vault_blocks)
        parts.append("")

    if config.get("navigator") and navigator_block:
        parts.append("### Manifest Navigator")
        parts.append("")
        parts.append(navigator_block)
        parts.append("")

    if not vault_blocks and not navigator_block and navigator_status != "missing":
        parts.append(
            "_Navigator disabled for this skill. No vault sections requested._"
        )

    return "\n".join(parts).rstrip() + "\n"


# ----------------------------------------------------------------------------
# CLI entry
# ----------------------------------------------------------------------------


def cmd_resolve_config(argv: list[str]) -> int:
    if len(argv) < 1:
        print("resolve-config requires <skill>", file=sys.stderr)
        return 2
    skill = argv[0]
    project_root = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())).resolve()
    if len(argv) > 1:
        project_root = Path(argv[1]).resolve()
    eff, tiers = resolve_config(skill, project_root)
    out = {"_tiers": tiers, **eff}
    print(json.dumps(out, indent=2))
    return 0


def cmd_compose_injection(argv: list[str]) -> int:
    # Read stdin JSON for {prompt, session_id, cwd}.
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}

    prompt = payload.get("prompt") or ""
    session_id = payload.get("session_id") or ""
    cwd = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    project_root = Path(cwd).resolve()

    # If a skill name was passed explicitly on the CLI, use it; else detect.
    if argv:
        skill = argv[0]
    else:
        skill = detect_skill(prompt) or ""

    if not skill:
        # No skill detected — silent exit, no injection.
        return 0

    started = time.monotonic()

    config, tiers_used = resolve_config(skill, project_root)
    vault_blocks = load_vault_sections(project_root, config)

    navigator_block: str | None = None
    navigator_status = "skipped"
    if config.get("navigator"):
        navigator_block, navigator_status = load_navigator_section(project_root)

    soft_warn = False
    if navigator_status == "missing":
        soft_warn = soft_warn_should_emit(project_root, session_id)

    additional = compose_injection(
        skill=skill,
        project_root=project_root,
        session_id=session_id,
        config=config,
        tiers_used=tiers_used,
        navigator_status=navigator_status,
        navigator_block=navigator_block,
        soft_warn=soft_warn,
        vault_blocks=vault_blocks,
    )

    response = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": additional,
        }
    }
    print(json.dumps(response))

    elapsed_ms = int((time.monotonic() - started) * 1000)
    # Structured log to stderr (bash wrapper appends to hooks.log).
    nav_label = navigator_status if config.get("navigator") else "disabled"
    vault_chars = sum(len(b) for b in vault_blocks)
    print(
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} "
        f"context-loader skill={skill} tiers={','.join(tiers_used)} "
        f"vault_chars={vault_chars} navigator_status={nav_label} "
        f"soft_warn={int(soft_warn)} total_ms={elapsed_ms}",
        file=sys.stderr,
        flush=True,
    )
    return 0


def cmd_detect_skill(_argv: list[str]) -> int:
    raw = sys.stdin.read()
    skill = detect_skill(raw or "")
    if skill:
        print(skill)
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(
            "usage: context-loader-lib.py <resolve-config|compose-injection|detect-skill> [args]",
            file=sys.stderr,
        )
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "resolve-config":
        return cmd_resolve_config(rest)
    if cmd == "compose-injection":
        return cmd_compose_injection(rest)
    if cmd == "detect-skill":
        return cmd_detect_skill(rest)
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        rc = main(sys.argv[1:])
    except KeyboardInterrupt:
        rc = 0
    except Exception as e:
        # Never crash the calling hook.
        print(
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} "
            f"context-loader status=crash error={type(e).__name__}",
            file=sys.stderr,
            flush=True,
        )
        rc = 0
    sys.exit(rc)
