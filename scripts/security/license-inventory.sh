#!/usr/bin/env bash
# license-inventory.sh — thin pass-through shim (run.sh-style, research.md §8).
# Feature 56-supply-chain-gate. All flag parsing lives in license-inventory.py.
#
# Usage: license-inventory.sh [--repo-root PATH] [--config PATH]
# Exit codes: 0 clean; 1 findings present; 2 internal/setup error.

set -uo pipefail

THIS_DIR=$(cd "$(dirname "$0")" && pwd)
ENGINE="$THIS_DIR/license-inventory.py"

command -v python3 >/dev/null 2>&1 || { echo "license-inventory: python3 not found on PATH" >&2; exit 2; }
[ -f "$ENGINE" ] || { echo "license-inventory: engine not found at $ENGINE" >&2; exit 2; }

exec python3 "$ENGINE" "$@"
