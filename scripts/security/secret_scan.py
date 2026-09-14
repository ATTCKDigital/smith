#!/usr/bin/env python3
"""secret_scan.py — pattern-catalogue + entropy secret-detection engine.

Feature 55-security-review-pass, Layer 1. A pure, directly-invokable
function of (files, excludes, allowlist_globs) -> findings — see this
feature's `data-model.md` §1/§2 and `research.md` §4/§8.

Usage:
    python3 secret_scan.py [--exclude GLOB]... [--allowlist-glob GLOB]... \
        [--] FILE [FILE ...]
    python3 secret_scan.py --gitleaks-json PATH  # normalize a gitleaks
                                                   # report instead

Output: one pipe-delimited finding per line on stdout —
    severity|file|line|pattern-id|excerpt-redacted
(data-model.md §2). Nothing else goes to stdout; diagnostics go to stderr.
NEVER prints a secret's actual value, whole or in any exploitable
substring — see mask() below.

Exit codes (mirrors secret-scan.sh's own contract): 0 = no findings;
1 = findings present; 2 = internal/usage error.
"""

import argparse
import fnmatch
import json
import math
import os
import re
import sys
from collections import Counter

ALLOW_MARKER = "smith-secret-scan: allow"

# ---- pattern catalogue (research.md §8) ----
# Each row: (pattern_id, severity, compiled_regex). A regex match's whole
# span is masked and reported as-is — no context gating needed.
SIGNATURE_PATTERNS = [
    ("aws-akia", "critical", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("aws-asia", "critical", re.compile(r"ASIA[0-9A-Z]{16}")),
    ("github-token", "critical", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,255}")),
    ("slack-token", "high", re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,72}")),
    (
        "conn-string-creds",
        "critical",
        re.compile(
            r"(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^:\s]+:[^@\s]+@"
        ),
    ),
]

PEM_HEADER_RE = re.compile(
    r"-----BEGIN (RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"
)

# AWS secret key: context-gated (40-char base64 string on a line whose key
# name matches "aws...secret" — raw base64 alone is too high-FP, research.md §8).
AWS_SECRET_CONTEXT_RE = re.compile(r"(?i)aws.*secret")
AWS_SECRET_KEY_RE = re.compile(r"[A-Za-z0-9/+=]{40}")

# Generic token-shaped assignment, entropy-gated (FR-4's "high-entropy
# strings" requirement — see shannon_entropy()/is_high_entropy() below).
GENERIC_ASSIGN_RE = re.compile(
    r"(?i)\b\w*(?:api[_-]?key|secret|token|password|passwd|pwd)\w*"
    r"\s*[:=]\s*['\"]?([^\s'\"]{16,})['\"]?"
)
ENTROPY_MIN_BITS = 3.5
ENTROPY_MIN_LENGTH = 20

# GCP service-account JSON marker: file-level co-occurrence, not per-line.
GCP_TYPE_RE = re.compile(r'"type"\s*:\s*"service_account"')
GCP_KEY_ID_RE = re.compile(r'"private_key_id"')  # smith-secret-scan: allow

BINARY_SNIFF_BYTES = 8192


def shannon_entropy(value):
    """Bits-per-character Shannon entropy of `value`. Empty -> 0.0."""
    if not value:
        return 0.0
    counts = Counter(value)
    length = len(value)
    return -sum(
        (count / length) * math.log2(count / length) for count in counts.values()
    )


def is_high_entropy(value):
    return (
        len(value) >= ENTROPY_MIN_LENGTH and shannon_entropy(value) >= ENTROPY_MIN_BITS
    )


def mask(value):
    """Redact: first4 + a FIXED-length star run + last4; short values are
    fully masked (data-model.md §2 — never leaks the value or its length)."""
    length = len(value)
    if length == 0:
        return ""
    if length <= 8:
        return "*" * length
    return f"{value[:4]}{'*' * 8}{value[-4:]}"


def is_excluded(path, excludes):
    """True if `path` matches an exclude glob (also tried with a leading
    '*/' so 'vendor/*' still catches a nested 'src/vendor/x.js')."""
    for glob in excludes:
        if fnmatch.fnmatch(path, glob) or fnmatch.fnmatch(path, "*/" + glob):
            return True
    return False


def is_allowlisted(path, allowlist_globs):
    """True if `path`/basename matches an allowlist glob. Only consulted
    for the entropy heuristic — signature matches are never exempted."""
    basename = path.rsplit("/", 1)[-1]
    for glob in allowlist_globs:
        if fnmatch.fnmatch(path, glob) or fnmatch.fnmatch(basename, glob):
            return True
    return False


def is_binary(path):
    """Best-effort binary sniff: a NUL byte in the first chunk. An
    unreadable file is treated as skip, never a crash."""
    try:
        with open(path, "rb") as handle:
            chunk = handle.read(BINARY_SNIFF_BYTES)
    except OSError:
        return True
    return b"\x00" in chunk


def scan_line(path, lineno, line, allowlist_globs):
    """Return findings for one line. The per-line allow marker suppresses
    EVERY pattern type on that line, checked first (research.md §8)."""
    if ALLOW_MARKER in line:
        return []

    findings = []

    for pattern_id, severity, regex in SIGNATURE_PATTERNS:
        match = regex.search(line)
        if match:
            findings.append((severity, path, lineno, pattern_id, mask(match.group(0))))

    if AWS_SECRET_CONTEXT_RE.search(line):
        match = AWS_SECRET_KEY_RE.search(line)
        if match:
            findings.append(
                ("critical", path, lineno, "aws-secret-key", mask(match.group(0)))
            )

    if PEM_HEADER_RE.search(line):
        findings.append(
            ("critical", path, lineno, "pem-private-key", "[PEM PRIVATE KEY HEADER]")
        )

    match = GENERIC_ASSIGN_RE.search(line)
    if match:
        value = match.group(1)
        if is_high_entropy(value) and not is_allowlisted(path, allowlist_globs):
            findings.append(
                ("high", path, lineno, "generic-high-entropy-assignment", mask(value))
            )

    return findings


def scan_gcp_marker(path, lines):
    """File-level check: a GCP service-account JSON export co-occurs
    "type": "service_account" with "private_key_id" anywhere in the file
    (research.md §8) — not a single-line pattern."""
    type_line = key_id_line = None
    for lineno, line in enumerate(lines, start=1):
        if type_line is None and GCP_TYPE_RE.search(line):
            type_line = lineno
        if key_id_line is None and GCP_KEY_ID_RE.search(line):
            key_id_line = lineno

    if type_line is None or key_id_line is None:
        return []

    anchor = key_id_line
    anchor_line = lines[anchor - 1] if 0 < anchor <= len(lines) else ""
    if ALLOW_MARKER in anchor_line:
        return []
    return [
        ("critical", path, anchor, "gcp-sa-json", "[GCP SERVICE ACCOUNT JSON MARKERS]")
    ]


def scan_file(path, excludes, allowlist_globs):
    """Scan one file. Guard clauses: excluded, missing, or binary files
    are all silently skipped (never an error)."""
    if is_excluded(path, excludes):
        return []
    if not os.path.isfile(path):
        return []
    if is_binary(path):
        return []

    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            lines = handle.readlines()
    except OSError:
        return []

    findings = []
    for lineno, line in enumerate(lines, start=1):
        findings.extend(scan_line(path, lineno, line, allowlist_globs))
    findings.extend(scan_gcp_marker(path, lines))
    return findings


def normalize_gitleaks(source):
    """Normalize a gitleaks JSON report (`source` path, or '-' for stdin)
    into this engine's line format. Malformed/empty input -> zero findings."""
    raw = sys.stdin.read() if source == "-" else _read_text(source)
    try:
        report = json.loads(raw) if raw.strip() else []
    except json.JSONDecodeError:
        report = []
    if not isinstance(report, list):
        return []

    findings = []
    for entry in report:
        if not isinstance(entry, dict):
            continue
        path = entry.get("File") or entry.get("file") or ""
        lineno = entry.get("StartLine") or entry.get("Line") or entry.get("line") or 0
        rule_id = entry.get("RuleID") or entry.get("rule_id") or "unknown"
        secret = entry.get("Secret") or entry.get("secret") or ""
        excerpt = mask(secret) if secret else "[GITLEAKS FINDING]"
        findings.append(("high", path, lineno, f"gitleaks:{rule_id}", excerpt))
    return findings


def _read_text(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        return handle.read()


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "files", nargs="*", help="Files to scan (ignored with --gitleaks-json)."
    )
    parser.add_argument(
        "--exclude", action="append", default=[], help="Exclude-path glob (repeatable)."
    )
    parser.add_argument(
        "--allowlist-glob",
        action="append",
        default=[],
        dest="allowlist_globs",
        help="Allowlist glob for the entropy heuristic only (repeatable).",
    )
    parser.add_argument(
        "--gitleaks-json",
        metavar="PATH",
        default=None,
        help="Normalize a gitleaks JSON report (PATH, or '-' for stdin) instead of scanning files.",
    )
    return parser.parse_args(argv)


def collect_findings(args):
    if args.gitleaks_json:
        return normalize_gitleaks(args.gitleaks_json)
    if not args.files:
        return []
    findings = []
    for path in args.files:
        findings.extend(scan_file(path, args.exclude, args.allowlist_globs))
    return findings


def main(argv):
    args = parse_args(argv)
    try:
        findings = collect_findings(args)
    except Exception as exc:  # never let an internal error masquerade as "clean"
        print(f"secret_scan: internal error: {exc}", file=sys.stderr)
        return 2

    for severity, path, lineno, pattern_id, excerpt in findings:
        print(f"{severity}|{path}|{lineno}|{pattern_id}|{excerpt}")

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
