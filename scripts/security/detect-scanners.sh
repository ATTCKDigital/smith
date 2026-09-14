#!/usr/bin/env bash
# detect-scanners.sh — presence-detect optional security scanners.
#
# Feature 55-security-review-pass (NFR-4's single reusable presence-detect
# helper). Checks whether gitleaks/semgrep/bandit are on $PATH and prints
# one machine-parseable line per tool: <tool>=present|absent. Silent
# otherwise — never a side-channel warning on the absent path, per
# research.md §7's "silent-skip is the universal fallback" convention.
#
# A standalone script, not inlined into any SKILL.md, so smith-audit's
# Security sub-audit and any future consumer can invoke it directly
# without depending on smith-build's pipeline (this feature does not wire
# smith-audit to call it — OOS-3).
#
# Usage: detect-scanners.sh
# Always exits 0, regardless of how many tools are present or absent.

set -uo pipefail

for tool in gitleaks semgrep bandit; do
    if command -v "$tool" >/dev/null 2>&1; then
        printf '%s=present\n' "$tool"
    else
        printf '%s=absent\n' "$tool"
    fi
done

exit 0
