#!/usr/bin/env python3
"""_scan_parsers.py — per-tool JSON normalization for dependency-scan.py.

Feature 56-supply-chain-gate. Split out of dependency-scan.py per
plan.md's File Size Policy contingency (mirrors feature 55's own
secret_scan.py/secret_patterns.py split) now that four tool-specific
parsers exist. Every function here is a pure `(json-shaped data) ->
(findings, low_count)` transform — no subprocess calls, no stdout, no
filesystem access — so it is directly unit-testable without stubbing a
scanner executable.

Finding shape (data-model.md §3, FR-17), one dict per Critical/High/Medium
result: sub_layer, source_scanner, ecosystem, manifest_path, package,
version, advisory_id, category (== advisory_id for Sub-layer D — kept as
its own key so format_finding_line() stays sub-layer-agnostic), severity,
fix_available, rationale. Low/info-bucket results are counted, never
rendered as individual findings (FR-11/FR-23) — each parser returns that
count as its second return value.

npm audit (FR-11): reads the real per-package `vulnerabilities` dict when
present; when only the aggregate `metadata.vulnerabilities` bucket counts
are available (no per-advisory detail — e.g. this feature's own minimal
test fixture, research.md §7.1), synthesizes one finding per count-unit
so the severity-threshold contract still holds. Exit code is NEVER
consulted (FR-11) — only stdout JSON.

pip-audit (data-model.md §3): no first-class severity field in its own
JSON in practice — defaults to Medium, noting the default in `rationale`.

osv-scanner/trivy (research.md §7.2): documented-but-not-locally-testable
JSON shapes (both tools confirmed absent on the reference dev machine) —
parsed defensively against each tool's published schema; any unexpected
shape degrades to zero findings rather than raising.
"""

NPM_SEVERITY_MAP = {"critical": "Critical", "high": "High", "moderate": "Medium"}
NPM_LOW_KEYS = ("low", "info")
OSV_SEVERITY_MAP = {
    "critical": "Critical",
    "high": "High",
    "moderate": "Medium",
    "medium": "Medium",
    "low": "Low",
}
TRIVY_SEVERITY_MAP = {
    "critical": "Critical",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
}


def format_finding_line(f):
    """data-model.md §5's exact bullet shape."""
    return (
        f"- **[{f['severity']}]** `{f['package']}@{f['version']}` "
        f"(`{f['manifest_path']}`) — {f['rationale']} "
        f"(category: {f['category']}, sub-layer: {f['sub_layer']})"
    )


def _ecosystem_for(manifest_path, manifest_records):
    for rec in manifest_records:
        if rec["manifest_path"] == manifest_path:
            return rec["ecosystem"]
    return "npm"


def _match_manifest(path, manifest_records):
    """Best-effort: map a scanner-reported path back to a discovered
    manifest_path — exact match, then lockfile match, then directory
    containment, else the raw (normalized) path itself (never dropped)."""
    norm = (path or "").lstrip("./")
    for rec in manifest_records:
        if norm in (rec["manifest_path"], rec.get("lockfile_path")):
            return rec["manifest_path"]
    for rec in manifest_records:
        rec_dir = (
            rec["manifest_path"].rsplit("/", 1)[0]
            if "/" in rec["manifest_path"]
            else ""
        )
        if rec_dir and norm.startswith(rec_dir + "/"):
            return rec["manifest_path"]
    return norm or (
        manifest_records[0]["manifest_path"] if manifest_records else "unknown"
    )


def _d_finding(
    manifest_path,
    ecosystem,
    source_scanner,
    package,
    version,
    advisory_id,
    severity,
    fix_available,
    rationale,
):
    return {
        "sub_layer": "D",
        "source_scanner": source_scanner,
        "ecosystem": ecosystem,
        "manifest_path": manifest_path,
        "package": package,
        "version": version,
        "advisory_id": advisory_id,
        "category": advisory_id,
        "severity": severity,
        "fix_available": fix_available,
        "rationale": rationale,
    }


def parse_npm_audit(data, manifest_path):
    findings = []
    low_count = 0
    per_pkg = data.get("vulnerabilities") if isinstance(data, dict) else None

    if isinstance(per_pkg, dict) and per_pkg:
        for pkg_name, entry in per_pkg.items():
            if not isinstance(entry, dict):
                continue
            fallback_sev = str(entry.get("severity", "")).lower()
            advisories = [
                v for v in (entry.get("via") or []) if isinstance(v, dict)
            ] or [{}]
            fix = entry.get("fixAvailable")
            fix_version = fix.get("version") if isinstance(fix, dict) else None
            for advisory in advisories:
                sev_raw = str(advisory.get("severity", fallback_sev)).lower()
                if sev_raw in NPM_LOW_KEYS:
                    low_count += 1
                    continue
                findings.append(
                    _d_finding(
                        manifest_path,
                        "npm",
                        "npm-audit",
                        pkg_name,
                        entry.get("range") or "unknown",
                        advisory.get("url")
                        or advisory.get("source")
                        or advisory.get("name")
                        or "npm-audit",
                        NPM_SEVERITY_MAP.get(sev_raw, "Medium"),
                        fix_version,
                        advisory.get("title") or f"npm audit advisory for {pkg_name}",
                    )
                )
        return findings, low_count

    # Fallback: only aggregate metadata.vulnerabilities counts available
    # (no per-package detail) — synthesize one finding per count-unit.
    counts = (
        ((data.get("metadata") or {}).get("vulnerabilities"))
        if isinstance(data, dict)
        else {}
    )
    counts = counts or {}
    for key, severity in NPM_SEVERITY_MAP.items():
        for _ in range(int(counts.get(key, 0) or 0)):
            findings.append(
                _d_finding(
                    manifest_path,
                    "npm",
                    "npm-audit",
                    "(npm audit summary)",
                    "unknown",
                    "npm-audit-summary",
                    severity,
                    None,
                    f"npm audit reported a {key} severity advisory; per-advisory "
                    "detail unavailable (metadata-only JSON).",
                )
            )
    low_count += int(counts.get("low", 0) or 0) + int(counts.get("info", 0) or 0)
    return findings, low_count


def parse_pip_audit(data, manifest_path, ecosystem):
    findings = []
    low_count = 0
    deps = data.get("dependencies") if isinstance(data, dict) else data
    if not isinstance(deps, list):
        deps = []

    for dep in deps:
        if not isinstance(dep, dict):
            continue
        name = dep.get("name", "unknown")
        version = dep.get("version", "unknown")
        for vuln in dep.get("vulns") or []:
            if not isinstance(vuln, dict):
                continue
            sev_raw = vuln.get("severity")
            description = vuln.get("description") or f"pip-audit advisory for {name}"
            if sev_raw:
                severity = str(sev_raw).capitalize()
                if severity not in ("Critical", "High", "Medium", "Low"):
                    severity = "Medium"
                rationale = description
            else:
                severity = "Medium"
                rationale = (
                    description
                    + " (severity absent from pip-audit output; defaulted to Medium.)"
                )
            if severity == "Low":
                low_count += 1
                continue
            fix_versions = vuln.get("fix_versions") or []
            findings.append(
                _d_finding(
                    manifest_path,
                    ecosystem,
                    "pip-audit",
                    name,
                    version,
                    vuln.get("id", "pip-audit-advisory"),
                    severity,
                    fix_versions[0] if fix_versions else None,
                    rationale,
                )
            )
    return findings, low_count


def parse_osv_scanner(data, manifest_records):
    findings = []
    low_count = 0
    for result in (data.get("results") or []) if isinstance(data, dict) else []:
        manifest_path = _match_manifest(
            (result.get("source") or {}).get("path"), manifest_records
        )
        for pkg_entry in result.get("packages") or []:
            package = pkg_entry.get("package") or {}
            name = package.get("name", "unknown")
            for vuln in pkg_entry.get("vulnerabilities") or []:
                sev = (
                    (vuln.get("database_specific") or {}).get("severity") or ""
                ).lower()
                severity = OSV_SEVERITY_MAP.get(sev, "Medium")
                if severity == "Low":
                    low_count += 1
                    continue
                findings.append(
                    _d_finding(
                        manifest_path,
                        _ecosystem_for(manifest_path, manifest_records),
                        "osv-scanner",
                        name,
                        package.get("version", "unknown"),
                        vuln.get("id", "osv-advisory"),
                        severity,
                        None,
                        vuln.get("summary") or f"osv-scanner advisory for {name}",
                    )
                )
    return findings, low_count


def parse_trivy(data, manifest_records):
    findings = []
    low_count = 0
    for result in (data.get("Results") or []) if isinstance(data, dict) else []:
        manifest_path = _match_manifest(result.get("Target"), manifest_records)
        for vuln in result.get("Vulnerabilities") or []:
            severity = TRIVY_SEVERITY_MAP.get(
                str(vuln.get("Severity", "")).lower(), "Medium"
            )
            if severity == "Low":
                low_count += 1
                continue
            pkg_name = vuln.get("PkgName", "unknown")
            findings.append(
                _d_finding(
                    manifest_path,
                    _ecosystem_for(manifest_path, manifest_records),
                    "trivy",
                    pkg_name,
                    vuln.get("InstalledVersion", "unknown"),
                    vuln.get("VulnerabilityID", "trivy-advisory"),
                    severity,
                    vuln.get("FixedVersion") or None,
                    vuln.get("Title") or f"trivy advisory for {pkg_name}",
                )
            )
    return findings, low_count
