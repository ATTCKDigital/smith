#!/usr/bin/env bash
# test_detect_scanners.sh — tests for scripts/security/detect-scanners.sh
# (feature 55-security-review-pass, T005).
#
# Stub executables on a scratch $PATH simulate present/absent combinations
# of gitleaks/semgrep/bandit; asserts the exact <tool>=present|absent
# output. Structural template: tests/get-base-branch.test.sh's
# PASS/FAIL/summary-line/exit-status shape.
#
# Run:  bash tests/security/test_detect_scanners.sh
#       zsh  tests/security/test_detect_scanners.sh
#
# NFR-2: self-detects which shell is currently running *this* script and
# invokes the target script under that same interpreter throughout, so a
# bash run and a zsh run each exercise the script end-to-end in that shell
# (mirrors tests/hooks/test_security_guard_mcp_browser.sh's convention).

set -u

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
SCRIPT="$REPO/scripts/security/detect-scanners.sh"

if [ ! -f "$SCRIPT" ]; then
    echo "FATAL: script not found: $SCRIPT" >&2
    exit 2
fi

if [ -n "${ZSH_VERSION:-}" ]; then
    DEFAULT_INTERPRETER="zsh"
else
    DEFAULT_INTERPRETER="bash"
fi
# Resolve the interpreter's absolute path NOW, before any test narrows
# PATH — a bare name looked up under a scratch PATH would fail to find
# the shell binary itself.
INTERPRETER_BIN=$(command -v "$DEFAULT_INTERPRETER")

PASS=0
FAIL=0

# make_path_with <tool>... -> prints a fresh scratch dir containing an
# executable stub for each named tool (empty dir if none given).
make_path_with() {
    local dir
    dir=$(mktemp -d)
    for name in "$@"; do
        printf '#!/usr/bin/env bash\nexit 0\n' > "$dir/$name"
        chmod +x "$dir/$name"
    done
    printf '%s' "$dir"
}

# run_case <name> <scratch-dir> <expected-output>
run_case() {
    local name="$1" scratch="$2" expected="$3" actual ec
    actual=$(PATH="$scratch" "$INTERPRETER_BIN" "$SCRIPT")
    ec=$?
    if [ "$actual" = "$expected" ] && [ "$ec" -eq 0 ]; then
        echo "PASS: $name"
        PASS=$((PASS + 1))
    else
        echo "FAIL: $name"
        echo "  expected (exit 0): $expected"
        echo "  actual   (exit $ec): $actual"
        FAIL=$((FAIL + 1))
    fi
    rm -rf "$scratch"
}

# --- Case 1: all three absent ---
DIR=$(make_path_with)
run_case "all absent" "$DIR" "gitleaks=absent
semgrep=absent
bandit=absent"

# --- Case 2: all three present ---
DIR=$(make_path_with gitleaks semgrep bandit)
run_case "all present" "$DIR" "gitleaks=present
semgrep=present
bandit=present"

# --- Case 3: only gitleaks present ---
DIR=$(make_path_with gitleaks)
run_case "only gitleaks present" "$DIR" "gitleaks=present
semgrep=absent
bandit=absent"

# --- Case 4: only semgrep+bandit present (gitleaks absent) ---
DIR=$(make_path_with semgrep bandit)
run_case "semgrep+bandit present, gitleaks absent" "$DIR" "gitleaks=absent
semgrep=present
bandit=present"

# --- Case 5: only bandit present ---
DIR=$(make_path_with bandit)
run_case "only bandit present" "$DIR" "gitleaks=absent
semgrep=absent
bandit=present"

echo "----"
echo "SUMMARY: $PASS passed, $FAIL failed"

[ "$FAIL" -eq 0 ]
