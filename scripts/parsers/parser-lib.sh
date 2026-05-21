#!/usr/bin/env bash
# parser-lib.sh — shared helpers for picking the right Smith parser.
#
# Sourced by hooks (manifest-updater.sh) and the /smith-index runner.
# Exposes:
#   resolve_parser <ext>   -> echoes absolute parser path; non-zero on miss.
#   parser_lang <ext>      -> echoes language tag (python|javascript|...).
#
# Resolution order (Design Decision 5):
#   1. <project-root>/.smith/scripts/parse-<lang>       (per-project override)
#   2. ~/.smith/scripts/parse-<lang>                    (user-installed)
#   3. <this-dir>/parse-<lang>                          (in-repo fallback)
#
# The "language" is derived from the file extension:
#   .py            -> python
#   .js .jsx       -> js
#   .ts .tsx       -> js   (same parser handles both)
#
# Other extensions (.sh, .css, .html, ...) currently have no parser; the
# function returns non-zero so callers can choose to skip silently.

PARSER_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

# Echo the language for an extension. Returns 1 if unsupported.
parser_lang() {
  local ext="${1:-}"
  case "$ext" in
    .py)             echo "python" ;;
    .js|.jsx)        echo "js" ;;
    .ts|.tsx)        echo "js" ;;
    *)               return 1 ;;
  esac
  return 0
}

# Resolve the parser script for a given extension. Echos its absolute path.
# Returns 1 if no parser is available.
resolve_parser() {
  local ext="${1:-}"
  local lang
  lang="$(parser_lang "$ext")" || return 1

  local parser_name
  case "$lang" in
    python)    parser_name="parse-python.py" ;;
    js)        parser_name="parse-js.js" ;;
    *)         return 1 ;;
  esac

  # 1. Per-project override.
  local project_root
  project_root="$(_parser_lib_project_root)"
  if [ -n "$project_root" ] && [ -x "$project_root/.smith/scripts/$parser_name" ]; then
    echo "$project_root/.smith/scripts/$parser_name"
    return 0
  fi

  # 2. User-installed.
  if [ -x "$HOME/.smith/scripts/$parser_name" ]; then
    echo "$HOME/.smith/scripts/$parser_name"
    return 0
  fi

  # 3. In-repo fallback (this directory).
  if [ -x "$PARSER_LIB_DIR/$parser_name" ]; then
    echo "$PARSER_LIB_DIR/$parser_name"
    return 0
  fi

  # Also accept non-executable files (Python doesn't require +x to run).
  if [ -f "$PARSER_LIB_DIR/$parser_name" ]; then
    echo "$PARSER_LIB_DIR/$parser_name"
    return 0
  fi

  return 1
}

# Internal: locate the project root by walking up looking for .git or .smith.
_parser_lib_project_root() {
  local d
  d="${PWD:-$(pwd)}"
  while [ "$d" != "/" ] && [ -n "$d" ]; do
    if [ -d "$d/.smith" ] || [ -d "$d/.git" ]; then
      echo "$d"
      return 0
    fi
    d="$(dirname "$d")"
  done
  echo ""
  return 1
}

# Run a parser against a file and echo the resulting JSON.
# Usage: run_parser <file>
# Returns the parser's exit code (0 on success or graceful failure).
run_parser() {
  local file="$1"
  local ext=".${file##*.}"
  local parser
  if ! parser="$(resolve_parser "$ext")"; then
    return 2
  fi
  case "$ext" in
    .py)     python3 "$parser" "$file" ;;
    *)       node    "$parser" "$file" ;;
  esac
}
