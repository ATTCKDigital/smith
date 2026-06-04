#!/usr/bin/env bash
# install-parsers.sh — copy Smith manifest parsers and supporting scripts to
# the user-global ~/.smith/scripts/ location. Idempotent and non-destructive.
#
# Implements spec Component 11 (parser installation) and supports Design
# Decision 5 (parser scripts live globally with per-project escape hatch).
#
# Usage:
#   scripts/install-parsers.sh                # install/update parsers
#   scripts/install-parsers.sh --force        # overwrite without backup
#   scripts/install-parsers.sh --dry-run      # print what would happen
#   scripts/install-parsers.sh --uninstall    # remove parsers from ~/.smith/scripts/

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="${REPO_ROOT}/scripts/parsers"
TARGET_DIR="${HOME}/.smith/scripts"
LOG_FILE="${HOME}/.smith/logs/hooks.log"

DRY_RUN=false
FORCE=false
UNINSTALL=false

for arg in "$@"; do
  case "$arg" in
    --dry-run)   DRY_RUN=true ;;
    --force)     FORCE=true ;;
    --uninstall) UNINSTALL=true ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *)
      printf 'install-parsers: unknown argument: %s\n' "$arg" >&2
      exit 2
      ;;
  esac
done

log() {
  printf '[install-parsers %s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1"
  if [[ -d "$(dirname "$LOG_FILE")" ]]; then
    printf '[install-parsers %s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" >> "$LOG_FILE"
  fi
}

check_runtime() {
  local missing=0
  if ! command -v python3 >/dev/null 2>&1; then
    printf 'install-parsers: WARNING — python3 not on PATH; parse-python.py will not run\n' >&2
    missing=1
  fi
  if ! command -v node >/dev/null 2>&1; then
    printf 'install-parsers: WARNING — node not on PATH; parse-js.js will not run\n' >&2
    missing=1
  fi
  return 0
}

install_file() {
  local src="$1"
  local dst="$2"
  local mode="$3"

  if [[ ! -f "$src" ]]; then
    log "skip (missing source): $src"
    return 0
  fi

  if $DRY_RUN; then
    log "would install: $src -> $dst (mode $mode)"
    return 0
  fi

  if [[ -f "$dst" ]] && ! $FORCE; then
    local backup="${dst}.bak.$(date -u +%Y%m%dT%H%M%SZ)"
    cp -p "$dst" "$backup"
    log "backed up existing: $dst -> $backup"
  fi

  install -m "$mode" "$src" "$dst"
  log "installed: $dst"
}

uninstall_file() {
  local dst="$1"
  if [[ -f "$dst" ]]; then
    if $DRY_RUN; then
      log "would remove: $dst"
    else
      rm -f "$dst"
      log "removed: $dst"
    fi
  fi
}

mkdir -p "${TARGET_DIR}/vendor" "$(dirname "$LOG_FILE")"

if $UNINSTALL; then
  log "uninstall starting"
  uninstall_file "${TARGET_DIR}/parse-python.py"
  uninstall_file "${TARGET_DIR}/parse-js.js"
  uninstall_file "${TARGET_DIR}/path-resolver.py"
  uninstall_file "${TARGET_DIR}/meta_describe.py"
  uninstall_file "${TARGET_DIR}/index_common.py"
  uninstall_file "${TARGET_DIR}/describe_discover.py"
  uninstall_file "${TARGET_DIR}/describe_write.py"
  uninstall_file "${TARGET_DIR}/describe_checkpoint.py"
  uninstall_file "${TARGET_DIR}/meta_schema_version.txt"
  uninstall_file "${TARGET_DIR}/parser-lib.sh"
  uninstall_file "${TARGET_DIR}/vendor/acorn.min.js"
  log "uninstall complete"
  exit 0
fi

check_runtime
log "install starting (source=${SOURCE_DIR}, target=${TARGET_DIR})"

install_file "${SOURCE_DIR}/parse-python.py"           "${TARGET_DIR}/parse-python.py"           755
install_file "${SOURCE_DIR}/parse-js.js"               "${TARGET_DIR}/parse-js.js"               755
install_file "${SOURCE_DIR}/path-resolver.py"          "${TARGET_DIR}/path-resolver.py"          755
# v2 (PR #21): meta_describe.py started life as the shared LLM helper.
# v3 (PR #25) stripped it down to a structural module — datatypes,
# .meta parse/render, threshold filter, prompt-template builders. Still
# imported by all v3 helpers and the save hook.
install_file "${SOURCE_DIR}/meta_describe.py"          "${TARGET_DIR}/meta_describe.py"          755
# v3 (PR #25): four new helpers replace the v2 LLM-call orchestration.
# The skill prose at ~/.claude/skills/smith-index/SKILL.md references
# these via absolute paths (python3 ~/.smith/scripts/describe_*.py),
# so they MUST be present on disk for /smith-index --describe to work.
install_file "${SOURCE_DIR}/index_common.py"           "${TARGET_DIR}/index_common.py"           755
install_file "${SOURCE_DIR}/describe_discover.py"      "${TARGET_DIR}/describe_discover.py"      755
install_file "${SOURCE_DIR}/describe_write.py"         "${TARGET_DIR}/describe_write.py"         755
install_file "${SOURCE_DIR}/describe_checkpoint.py"    "${TARGET_DIR}/describe_checkpoint.py"    755
# Schema version marker — single source of truth for /smith-update's schema
# drift detection. Read by /smith-index when writing .smith/index/.schema-version.
# Mode 644 (data file, not executable).
install_file "${SOURCE_DIR}/meta_schema_version.txt"   "${TARGET_DIR}/meta_schema_version.txt"   644
install_file "${SOURCE_DIR}/parser-lib.sh"             "${TARGET_DIR}/parser-lib.sh"             644
install_file "${SOURCE_DIR}/vendor/acorn.min.js"       "${TARGET_DIR}/vendor/acorn.min.js"       644

log "install complete (parsers at ${TARGET_DIR})"

if ! $DRY_RUN; then
  printf '\nSmith manifest parsers installed to %s\n' "$TARGET_DIR"
  printf 'Verify with: python3 %s/parse-python.py --help\n' "$TARGET_DIR"
fi
