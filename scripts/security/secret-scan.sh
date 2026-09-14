#!/usr/bin/env bash
# secret-scan.sh — Layer 1 (built-in secret scan) CLI wrapper (feature 55).
#
# Thin files-in/findings-out wrapper around secret_scan.py: resolves scan
# scope (--files, --diff-base <ref>, or default staged+unstaged-vs-HEAD),
# resolves built-in + config-driven exclude/allowlist globs (data-model.md
# §1), and merges gitleaks findings when told it's present. BASE_BRANCH
# resolution is the CALLER's job (FR-3) — this script is diff-agnostic.
#
# Usage: secret-scan.sh [--diff-base <ref>] [--files <path>...]
#                        [--config <path>] [--with-gitleaks]
# Exit codes: 0 clean; 1 findings present (stdout); 2 internal error.

set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

# Engine resolution: installed-path-preferred, repo-dev fallback (T006).
ENGINE="$SCRIPT_DIR/secret_scan.py"
[ -f "$HOME/.smith/scripts/security/secret_scan.py" ] && ENGINE="$HOME/.smith/scripts/security/secret_scan.py"

BUILTIN_EXCLUDES=("vendor/*" "node_modules/*" ".venv/*" "dist/*" "build/*" ".smith/*")
BUILTIN_ALLOWLIST=("package-lock.json" "yarn.lock")
NL='
'

DIFF_BASE=""
CONFIG_PATH=""
WITH_GITLEAKS=0
EXPLICIT_FILES=0
FILES=()

while [ $# -gt 0 ]; do
    case "$1" in
        --diff-base) DIFF_BASE="${2:-}"; shift 2 ;;
        --config) CONFIG_PATH="${2:-}"; shift 2 ;;
        --with-gitleaks) WITH_GITLEAKS=1; shift ;;
        --files)
            EXPLICIT_FILES=1; shift
            while [ $# -gt 0 ] && [ "${1#--}" = "$1" ]; do
                FILES+=("$1"); shift
            done
            ;;
        *) echo "secret-scan: unknown argument: $1" >&2; exit 2 ;;
    esac
done

command -v python3 >/dev/null 2>&1 || { echo "secret-scan: python3 not found on PATH" >&2; exit 2; }
[ -f "$ENGINE" ] || { echo "secret-scan: engine not found at $ENGINE" >&2; exit 2; }
[ -r "$ENGINE" ] || { echo "secret-scan: engine not readable at $ENGINE" >&2; exit 2; }

# Resolve scan scope.
if [ "$EXPLICIT_FILES" -eq 0 ]; then
    if [ -n "$DIFF_BASE" ]; then
        # Union of (diff vs base) + (untracked non-ignored files), deduped —
        # a file can only be tracked-and-diffing OR untracked, never both,
        # but `sort -u` collapses the (rare) case of either list repeating a
        # path itself. Mirrors the default-scope branch below, which unions
        # the same two file-list sources for the no-DIFF_BASE case.
        while IFS= read -r f; do [ -n "$f" ] && FILES+=("$f"); done < <({ git diff --name-only "$DIFF_BASE" -- 2>/dev/null; git ls-files --others --exclude-standard 2>/dev/null; } | sort -u)
    else
        while IFS= read -r f; do [ -n "$f" ] && FILES+=("$f"); done < <(git diff --name-only HEAD -- 2>/dev/null; git ls-files --others --exclude-standard 2>/dev/null)
    fi
fi
[ "${#FILES[@]}" -eq 0 ] && exit 0

# Config-derived excludes/allowlist (additive; two-step validity gate).
[ -n "$CONFIG_PATH" ] || CONFIG_PATH="$(git rev-parse --show-toplevel 2>/dev/null || pwd)/.smith/config.json"
CONFIG_EXCLUDES=()
CONFIG_ALLOWLIST=()
if [ -f "$CONFIG_PATH" ]; then
    # Single python3 spawn, config path passed via argv (never string-
    # interpolated into source — a path containing a quote could otherwise
    # break out of an inline python -c literal). Emits excludes then a
    # sentinel line then allowlist globs; invalid JSON / non-dict config
    # exits 1 and prints nothing, so CONFIG_EXCLUDES/CONFIG_ALLOWLIST stay
    # empty (same silent-skip behavior as the prior two-step gate).
    CONFIG_OUT=$(python3 - "$CONFIG_PATH" <<'PYEOF' 2>/dev/null
import json, sys

path = sys.argv[1]
try:
    with open(path) as f:
        config = json.load(f)
except Exception:
    sys.exit(1)

sr = config.get("security_review") if isinstance(config, dict) else None
sr = sr if isinstance(sr, dict) else {}
for g in (sr.get("excludes") or []):
    print(g)
print("__SMITH_SECRET_SCAN_ALLOWLIST__")
for g in (sr.get("allowlist_globs") or []):
    print(g)
PYEOF
)
    CONFIG_PY_STATUS=$?
    if [ "$CONFIG_PY_STATUS" -eq 0 ]; then
        CONFIG_SECTION="excludes"
        while IFS= read -r line; do
            if [ "$line" = "__SMITH_SECRET_SCAN_ALLOWLIST__" ]; then
                CONFIG_SECTION="allowlist"
                continue
            fi
            [ -n "$line" ] || continue
            if [ "$CONFIG_SECTION" = "excludes" ]; then
                CONFIG_EXCLUDES+=("$line")
            else
                CONFIG_ALLOWLIST+=("$line")
            fi
        done <<<"$CONFIG_OUT"
    fi
fi

EXCLUDE_ARGS=()
for g in "${BUILTIN_EXCLUDES[@]}" "${CONFIG_EXCLUDES[@]+"${CONFIG_EXCLUDES[@]}"}"; do EXCLUDE_ARGS+=(--exclude "$g"); done
ALLOWLIST_ARGS=()
for g in "${BUILTIN_ALLOWLIST[@]}" "${CONFIG_ALLOWLIST[@]+"${CONFIG_ALLOWLIST[@]}"}"; do ALLOWLIST_ARGS+=(--allowlist-glob "$g"); done

OUTPUT=$(python3 "$ENGINE" "${EXCLUDE_ARGS[@]}" "${ALLOWLIST_ARGS[@]}" -- "${FILES[@]}")
ENGINE_EXIT=$?
[ "$ENGINE_EXIT" -gt 1 ] && exit 2

# Gitleaks merge (FR-7) — only when the caller asserts presence; this
# wrapper never re-detects presence itself (see detect-scanners.sh).
if [ "$WITH_GITLEAKS" -eq 1 ] && command -v gitleaks >/dev/null 2>&1; then
    GITLEAKS_JSON=$(gitleaks detect --source "." --no-git -f json -r /dev/stdout 2>/dev/null)
    if [ -n "$GITLEAKS_JSON" ]; then
        GL_OUTPUT=$(printf '%s' "$GITLEAKS_JSON" | python3 "$ENGINE" --gitleaks-json - 2>/dev/null)
        [ -n "$GL_OUTPUT" ] && OUTPUT="${OUTPUT:+$OUTPUT$NL}$GL_OUTPUT"
    fi
fi

if [ -n "$OUTPUT" ]; then
    printf '%s\n' "$OUTPUT"
    exit 1
fi
exit 0
