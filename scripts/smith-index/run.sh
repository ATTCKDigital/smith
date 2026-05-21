#!/usr/bin/env bash
# run.sh — /smith-index bash entrypoint. Delegates to the Python implementation.
#
# Usage:
#   scripts/smith-index/run.sh [--check] [--system <name>] [--migrate-templates]
#                              [--incremental [--from <ref> --to <ref>]]
#                              [--init-system-paths] [--resume]
#                              [--root <path>] [--system-paths <path>]
#
# This script exists so callers (skills/git hooks/installer) can invoke the
# indexer without knowing about the underlying Python module. All flag
# parsing happens inside run.py.

set -uo pipefail

THIS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PY_RUN="${THIS_DIR}/run.py"

if [[ ! -f "$PY_RUN" ]]; then
  printf 'smith-index: run.py not found at %s\n' "$PY_RUN" >&2
  exit 2
fi

if ! command -v python3 >/dev/null 2>&1; then
  printf 'smith-index: python3 not on PATH\n' >&2
  exit 2
fi

exec python3 "$PY_RUN" "$@"
