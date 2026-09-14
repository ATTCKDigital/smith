#!/usr/bin/env python3
"""license-inventory.py — Sub-layer L: dependency-free license inventory.

Feature 56-supply-chain-gate. Discovers manifests (_manifest_discovery.py),
walks each npm manifest's node_modules/ for license/licenses[] metadata
and each poetry manifest's env (via `poetry run python3` +
importlib.metadata) for License-Expression/License/Classifier metadata,
merges into a repo-wide inventory keyed on license id, evaluates it
against supply_chain.license_policy.deny (data-model.md §4). Independent
of dependency-scan.py — no shared runtime state or imports (T004, `[P]`).

Usage: python3 license-inventory.py [--repo-root PATH] [--config PATH]

Output (pure stdout, same self-distinguishing line shapes as
dependency-scan.py, data-model.md §5): first `MANIFEST_COUNT: <n>`
always; if 0, nothing else, exit 0. Else: every High `license-policy`
finding (a deny-list hit) as its own bullet line; then one
`<manifest_path>: license_inventory=<ran|skipped:<reason>|disabled>` line
per manifest; then exactly one trailing `LOW_COUNT: 0` (license findings
have no Low/Medium/Critical tier — every deny-list hit is fixed High,
FR-18). Exit: 0 clean; 1 = High finding(s) produced (informational only,
FR-20); 2 = internal/usage error.

The inventory itself (every license id x package, incl. UNKNOWN) is never
printed — only deny-list findings are. `allow` is read but produces no
findings in this version (A-4, documented no-op).
"""

import argparse
import glob
import json
import os
import subprocess
import sys

from _manifest_discovery import _manifest_dir, discover_manifests

DEFAULTS = {"license_inventory": True, "deny": [], "allow": [], "excludes": []}
PYTHON_WALK_TIMEOUT_SECONDS = 30  # fixed, defensive-only (T004) — not configurable

# Enumerates importlib.metadata distributions visible to whichever python3
# actually executes this (the poetry venv's own interpreter in production —
# `poetry run python3` resolves it), resolving each one's license via the
# 3-tier fallback chain (data-model.md §4). One `name\x1fversion\x1flicense`
# record per line on stdout; never raises on a single bad distribution.
_PY_LICENSE_WALK_SCRIPT = """
import importlib.metadata as md
for dist in md.distributions():
    try:
        meta = dist.metadata
        name = meta.get("Name") or "unknown"
        version = dist.version or "unknown"
        expr = meta.get("License-Expression")
        if expr and expr.strip():
            lic = expr.strip()
        else:
            raw = meta.get("License")
            if raw and raw.strip() and raw.strip().upper() != "UNKNOWN":
                lic = raw.strip()
            else:
                classifiers = [c for c in (meta.get_all("Classifier") or []) if c.startswith("License ::")]
                lic = classifiers[-1].strip() if classifiers else "UNKNOWN"
        print(f"{name}\\x1f{version}\\x1f{lic}")
    except Exception:
        continue
"""


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
    if isinstance(sc.get("license_inventory"), bool):
        config["license_inventory"] = sc["license_inventory"]
    policy = sc.get("license_policy")
    if isinstance(policy, dict):
        if isinstance(policy.get("deny"), list):
            config["deny"] = policy["deny"]
        if isinstance(policy.get("allow"), list):
            config["allow"] = policy["allow"]
    if isinstance(sc.get("excludes"), list):
        config["excludes"] = sc["excludes"]
    return config


def _resolve_npm_license(data):
    """license -> legacy licenses[] (join multiple with ' OR ') -> UNKNOWN
    (data-model.md §4's live-verified xmlhttprequest-ssl fallback)."""
    lic = data.get("license")
    if isinstance(lic, str) and lic.strip():
        return lic.strip()
    if isinstance(lic, dict) and lic.get("type"):
        return str(lic["type"]).strip()
    licenses = data.get("licenses")
    if isinstance(licenses, list) and licenses:
        types = [
            str(e["type"]).strip()
            for e in licenses
            if isinstance(e, dict) and e.get("type")
        ]
        if types:
            return " OR ".join(types)
    return "UNKNOWN"


def _npm_license_records(repo_root, manifest):
    node_modules = os.path.join(
        _manifest_dir(repo_root, manifest["manifest_path"]), "node_modules"
    )
    paths = sorted(
        glob.glob(os.path.join(node_modules, "*", "package.json"))
        + glob.glob(os.path.join(node_modules, "@*", "*", "package.json"))
    )
    records = []
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                data = json.load(handle)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        name = data.get("name") or os.path.basename(os.path.dirname(path))
        version = data.get("version") or "unknown"
        records.append((_resolve_npm_license(data), name, version))
    return records


def _python_license_records(repo_root, manifest):
    """None on any failure (poetry/env unavailable, timeout, no output) —
    the caller treats None as a "no_venv"-equivalent skip."""
    try:
        result = subprocess.run(
            ["poetry", "run", "python3", "-c", _PY_LICENSE_WALK_SCRIPT],
            cwd=_manifest_dir(repo_root, manifest["manifest_path"]),
            capture_output=True,
            text=True,
            timeout=PYTHON_WALK_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if not result.stdout or not result.stdout.strip():
        return None
    records = []
    for line in result.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 3:
            name, version, license_id = parts
            records.append((license_id, name, version))
    return records


def _to_records(pairs, path, eco):
    return [
        {
            "license_id": lic,
            "manifest_path": path,
            "ecosystem": eco,
            "package": name,
            "version": version,
        }
        for lic, name, version in pairs
    ]


def _inventory_for_manifest(repo_root, manifest):
    """Returns (records, status_line). npm gated on node_modules_present
    (FR-14); every other ecosystem gated on venv_path being non-null
    (poetry-managed only — pip/go/cargo always have venv_path None per
    T001, so they always fall through to "no_venv", T004's own v1
    boundary, without needing an ecosystem-specific branch)."""
    eco = manifest["ecosystem"]
    path = manifest["manifest_path"]
    ran = f"{path}: license_inventory=ran"

    if eco == "npm":
        if not manifest["node_modules_present"]:
            return [], f"{path}: license_inventory=skipped:no_node_modules"
        return _to_records(_npm_license_records(repo_root, manifest), path, eco), ran

    if not manifest["venv_path"]:
        return [], f"{path}: license_inventory=skipped:no_venv"
    walked = _python_license_records(repo_root, manifest)
    if walked is None:
        return [], f"{path}: license_inventory=skipped:no_venv"
    return _to_records(walked, path, eco), ran


def _license_finding(rec):
    rationale = f"License '{rec['license_id']}' matches a configured deny-list entry (supply_chain.license_policy.deny)."
    return {
        "sub_layer": "L",
        "severity": "High",
        "category": "license-policy",
        "package": rec["package"],
        "version": rec["version"],
        "manifest_path": rec["manifest_path"],
        "ecosystem": rec["ecosystem"],
        "rationale": rationale,
    }


def _evaluate_policy(records, deny_list):
    """One High `license-policy` Finding per record whose license_id
    case-sensitively matches a `deny` entry (FR-18). `allow` is a
    documented no-op (A-4) — not consulted here."""
    deny_set = set(deny_list)
    return [_license_finding(rec) for rec in records if rec["license_id"] in deny_set]


def _format_finding_line(f):
    """data-model.md §5's exact bullet shape."""
    return (
        f"- **[{f['severity']}]** `{f['package']}@{f['version']}` "
        f"(`{f['manifest_path']}`) — {f['rationale']} "
        f"(category: {f['category']}, sub-layer: {f['sub_layer']})"
    )


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
    return parser.parse_args(argv)


def main(argv):
    args = parse_args(argv)
    repo_root = os.path.abspath(args.repo_root)
    if not os.path.isdir(repo_root):
        print(f"license-inventory: repo-root not found: {repo_root}", file=sys.stderr)
        return 2

    config = _load_config(
        args.config or os.path.join(repo_root, ".smith", "config.json")
    )

    try:
        manifests = discover_manifests(repo_root, config["excludes"])
    except Exception as exc:  # never let an internal error masquerade as "clean"
        print(f"license-inventory: internal error: {exc}", file=sys.stderr)
        return 2

    print(f"MANIFEST_COUNT: {len(manifests)}")
    if not manifests:
        return 0

    if not config["license_inventory"]:
        for m in manifests:
            print(f"{m['manifest_path']}: license_inventory=disabled")
        print("LOW_COUNT: 0")
        return 0

    records = []
    status_lines = []
    for manifest in manifests:
        recs, status = _inventory_for_manifest(repo_root, manifest)
        records.extend(recs)
        status_lines.append(status)

    finding_lines = [
        _format_finding_line(f) for f in _evaluate_policy(records, config["deny"])
    ]

    for line in finding_lines:
        print(line)
    for line in status_lines:
        print(line)
    print("LOW_COUNT: 0")

    return 1 if finding_lines else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
