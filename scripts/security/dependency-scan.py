#!/usr/bin/env python3
"""dependency-scan.py — Sub-layer D: dependency CVE scan orchestrator.

Feature 56-supply-chain-gate. Discovers manifests (_manifest_discovery.py),
prefers a whole-repo multi-ecosystem scanner (osv-scanner, then trivy)
when present, else falls back per-manifest to npm audit / pip-audit
(research.md §7, data-model.md §2/§3). `grype`'s presence is a
`detect-scanners.sh`-level disclosure concern only — this file never
invokes it (FR-8's tool list is read as exhaustive, not illustrative).

Usage:
    python3 dependency-scan.py [--repo-root PATH] [--config PATH]
                                [--timeout-seconds N]

Output (pure stdout, self-distinguishing line shapes, no other side
effects — this script never touches /tmp itself, data-model.md §5's merge
happens one layer up): first `MANIFEST_COUNT: <n>` always; if n == 0,
nothing else and exit 0. Otherwise: every Critical/High/Medium finding as
its own `data-model.md` §5 bullet line; then one `<manifest_path>:
cve_scan=<ran:<tool>|skipped:<reason>|disabled>` line per manifest; then
exactly one trailing `LOW_COUNT: <n>` line (this run's own Low+info-folded
count — never rendered individually, summed by the caller with
license-inventory.py's own LOW_COUNT, data-model.md §5).

Exit codes: 0 = ran clean, zero Critical/High/Medium findings; 1 = one or
more such findings produced (informational only — never branched on for
control flow, FR-20); 2 = internal/usage error.

Implementation note: the poetry-ecosystem pip-audit fallback invokes
`poetry run pip-audit -f json` (the installed console-script entry point)
rather than `python3 -m pip_audit` — functionally equivalent inside the
poetry-managed environment, but the only form a PATH-stub test harness
can mock (a `-m` module invocation requires real package installation).
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

from _manifest_discovery import _manifest_dir, discover_manifests
from _scan_parsers import (
    format_finding_line,
    parse_npm_audit,
    parse_osv_scanner,
    parse_pip_audit,
    parse_trivy,
)

DEFAULTS = {"cve_scan": True, "timeout_seconds": 60, "excludes": []}


def _load_config(config_path):
    """Defensive file-exists-AND-parses-AND-isinstance(dict) gate,
    mirroring secret-scan.sh:71-113. Any failure -> every field defaults."""
    config = dict(DEFAULTS)
    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except Exception:
        return config
    sc = raw.get("supply_chain") if isinstance(raw, dict) else None
    if not isinstance(sc, dict):
        return config
    if isinstance(sc.get("cve_scan"), bool):
        config["cve_scan"] = sc["cve_scan"]
    if isinstance(sc.get("timeout_seconds"), (int, float)) and not isinstance(
        sc.get("timeout_seconds"), bool
    ):
        config["timeout_seconds"] = sc["timeout_seconds"]
    if isinstance(sc.get("excludes"), list):
        config["excludes"] = sc["excludes"]
    return config


def _detect_tools():
    return {
        name: shutil.which(name) is not None
        for name in ("osv-scanner", "trivy", "npm", "pip-audit", "poetry")
    }


def _safe_json(text):
    try:
        return json.loads(text) if text and text.strip() else {}
    except json.JSONDecodeError:
        return {}


def _run_tool(cmd, cwd, timeout_seconds):
    """Returns ('ok', stdout) | ('timeout', None) | ('offline', stderr).
    Exit code is NEVER consulted (FR-11) — only whether the call itself
    completed and produced usable stdout."""
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout_seconds
        )
    except subprocess.TimeoutExpired:
        return "timeout", None
    except OSError:
        return "offline", ""
    if result.stdout and result.stdout.strip():
        return "ok", result.stdout
    # No usable stdout: never crash the build — bucket under "offline",
    # the closest documented reason for "ran, produced nothing usable"
    # (never used to distinguish pass/fail — no terminate path, FR-20).
    return "offline", result.stderr or ""


def _fallback_for_manifest(repo_root, manifest, tools, timeout_seconds):
    """Step 2 (FR-9): per-manifest fallback, only reached when neither
    osv-scanner nor trivy is present. Returns (status, findings, low)."""
    eco = manifest["ecosystem"]
    manifest_dir = _manifest_dir(repo_root, manifest["manifest_path"])

    if eco == "npm":
        kind = manifest["lockfile_kind"]
        if kind is None:
            return "enolock", [], 0
        if kind != "npm":
            return "enolock_wrong_format", [], 0
        if not tools["npm"]:
            return "absent", [], 0
        outcome, payload = _run_tool(
            ["npm", "audit", "--json", "--package-lock-only"],
            manifest_dir,
            timeout_seconds,
        )
        if outcome in ("timeout", "offline"):
            return outcome, [], 0
        findings, low = parse_npm_audit(_safe_json(payload), manifest["manifest_path"])
        return "ran:npm-audit", findings, low

    if eco in ("poetry", "pip"):
        if not tools["pip-audit"]:
            return "absent", [], 0
        if eco == "poetry":
            if not manifest["venv_path"] or not tools["poetry"]:
                return "absent", [], 0
            cmd = ["poetry", "run", "pip-audit", "-f", "json"]
        else:
            cmd = ["pip-audit", "-f", "json", "-r", manifest["manifest_path"]]
        outcome, payload = _run_tool(
            cmd, repo_root if eco == "pip" else manifest_dir, timeout_seconds
        )
        if outcome in ("timeout", "offline"):
            return outcome, [], 0
        findings, low = parse_pip_audit(
            _safe_json(payload), manifest["manifest_path"], eco
        )
        return "ran:pip-audit", findings, low

    # go / cargo: no fallback tool is named for either ecosystem (FR-9).
    return "absent", [], 0


def _run_multi_scanner(tool, repo_root, manifests, timeout_seconds):
    cmd = (
        ["osv-scanner", "--format", "json", repo_root]
        if tool == "osv-scanner"
        else ["trivy", "fs", "--format", "json", "--scanners", "vuln", repo_root]
    )
    outcome, payload = _run_tool(cmd, repo_root, timeout_seconds)
    if outcome in ("timeout", "offline"):
        return (
            [f"{m['manifest_path']}: cve_scan=skipped:{outcome}" for m in manifests],
            [],
            0,
        )
    parser = parse_osv_scanner if tool == "osv-scanner" else parse_trivy
    findings, low = parser(_safe_json(payload), manifests)
    status = [f"{m['manifest_path']}: cve_scan=ran:{tool}" for m in manifests]
    return status, [format_finding_line(f) for f in findings], low


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", default=".", help="Repository root to scan (default: cwd)."
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to .smith/config.json (default: <repo-root>/.smith/config.json).",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=None,
        help="Override supply_chain.timeout_seconds.",
    )
    return parser.parse_args(argv)


def main(argv):
    args = parse_args(argv)
    repo_root = os.path.abspath(args.repo_root)
    if not os.path.isdir(repo_root):
        print(f"dependency-scan: repo-root not found: {repo_root}", file=sys.stderr)
        return 2

    config = _load_config(
        args.config or os.path.join(repo_root, ".smith", "config.json")
    )
    timeout_seconds = (
        args.timeout_seconds
        if args.timeout_seconds is not None
        else config["timeout_seconds"]
    )

    try:
        manifests = discover_manifests(repo_root, config["excludes"])
    except Exception as exc:  # never let an internal error masquerade as "clean"
        print(f"dependency-scan: internal error: {exc}", file=sys.stderr)
        return 2

    print(f"MANIFEST_COUNT: {len(manifests)}")
    if not manifests:
        return 0

    finding_lines = []
    status_lines = []
    low_count = 0

    if not config["cve_scan"]:
        status_lines = [f"{m['manifest_path']}: cve_scan=disabled" for m in manifests]
    else:
        tools = _detect_tools()
        if tools["osv-scanner"] or tools["trivy"]:
            tool = "osv-scanner" if tools["osv-scanner"] else "trivy"
            status_lines, finding_lines, low_count = _run_multi_scanner(
                tool, repo_root, manifests, timeout_seconds
            )
        else:
            for manifest in manifests:
                reason, findings, low = _fallback_for_manifest(
                    repo_root, manifest, tools, timeout_seconds
                )
                finding_lines.extend(format_finding_line(f) for f in findings)
                low_count += low
                tag = reason if reason.startswith("ran:") else f"skipped:{reason}"
                status_lines.append(f"{manifest['manifest_path']}: cve_scan={tag}")

    for line in finding_lines:
        print(line)
    for line in status_lines:
        print(line)
    print(f"LOW_COUNT: {low_count}")

    return 1 if finding_lines else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
