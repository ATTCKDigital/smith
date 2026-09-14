#!/usr/bin/env bash
# test_secret_scan.sh — tests for scripts/security/secret-scan.sh +
# secret_scan.py (feature 55-security-review-pass, T004).
#
# Structural template: tests/get-base-branch.test.sh's make_repo/run_case/
# PASS/FAIL/summary-line/exit-status shape, extended with
# tests/hooks/test_security_guard_mcp_browser.sh's mktemp-per-case
# fixture-planting idiom. Every planted secret is a clearly-synthetic,
# DOCUMENTED-FAKE canary (AWS's own published example key/secret,
# structurally-valid-but-never-issued GitHub/Slack tokens, etc.) — never a
# string that could pass for a real leaked credential.
#
# Run:  bash tests/security/test_secret_scan.sh
#       zsh  tests/security/test_secret_scan.sh
#
# NFR-2: self-detects which shell is running *this* script and invokes
# secret-scan.sh under that same interpreter throughout (mirrors
# tests/hooks/test_security_guard_mcp_browser.sh's bash/zsh-parity idiom).

set -u

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
WRAPPER="$REPO/scripts/security/secret-scan.sh"
ENGINE="$REPO/scripts/security/secret_scan.py"

if [ ! -f "$WRAPPER" ] || [ ! -f "$ENGINE" ]; then
    echo "FATAL: secret-scan.sh or secret_scan.py not found under $REPO/scripts/security" >&2
    exit 2
fi

if [ -n "${ZSH_VERSION:-}" ]; then
    DEFAULT_INTERPRETER="zsh"
else
    DEFAULT_INTERPRETER="bash"
fi
INTERPRETER_BIN=$(command -v "$DEFAULT_INTERPRETER")

PASS=0
FAIL=0
FAILED_NAMES=()

# ---------- fixture + invocation helpers ----------

# make_repo -> prints a fresh throwaway git repo dir.
make_repo() {
    local dir
    dir=$(mktemp -d)
    (
        cd "$dir" || exit 1
        git init -q
        git config user.email test@example.com
        git config user.name test
        git commit -q --allow-empty -m init
    )
    printf '%s' "$dir"
}

# scan <repo> <file>... -> stdout of secret-scan.sh --files <file>...,
# run from inside <repo> under the self-detected interpreter.
scan() {
    local repo="$1"; shift
    (cd "$repo" && "$INTERPRETER_BIN" "$WRAPPER" --files "$@")
}

# scan_exit <repo> <file>... -> exit code of the same invocation.
scan_exit() {
    local repo="$1"; shift
    (cd "$repo" && "$INTERPRETER_BIN" "$WRAPPER" --files "$@" >/dev/null 2>&1)
    printf '%s' "$?"
}

assert_eq() {
    local name="$1" expected="$2" actual="$3"
    if [ "$expected" = "$actual" ]; then
        PASS=$((PASS + 1)); echo "PASS: $name"
    else
        FAIL=$((FAIL + 1)); FAILED_NAMES+=("$name")
        echo "FAIL: $name"; echo "  expected: $expected"; echo "  actual:   $actual"
    fi
}

assert_contains() {
    local name="$1" haystack="$2" needle="$3"
    if printf '%s' "$haystack" | grep -qF "$needle"; then
        PASS=$((PASS + 1)); echo "PASS: $name"
    else
        FAIL=$((FAIL + 1)); FAILED_NAMES+=("$name")
        echo "FAIL: $name"; echo "  expected output to contain: $needle"; echo "  actual: $haystack"
    fi
}

assert_not_contains() {
    local name="$1" haystack="$2" needle="$3"
    if printf '%s' "$haystack" | grep -qF "$needle"; then
        FAIL=$((FAIL + 1)); FAILED_NAMES+=("$name")
        echo "FAIL: $name"; echo "  output UNEXPECTEDLY contains: $needle"
    else
        PASS=$((PASS + 1)); echo "PASS: $name"
    fi
}

# ================= 1: one positive case per catalogue pattern row =================
{
    repo=$(make_repo)
    printf 'aws_key = "AKIAIOSFODNN7EXAMPLE"\n' > "$repo/akia.txt"  # smith-secret-scan: allow
    out=$(scan "$repo" akia.txt)
    assert_contains "aws-akia detected" "$out" "aws-akia"
    assert_eq "aws-akia exit code 1" "1" "$(scan_exit "$repo" akia.txt)"
    rm -rf "$repo"
}
{
    repo=$(make_repo)
    printf 'temp_key = "ASIAIOSFODNN7EXAMPLE"\n' > "$repo/asia.txt"  # smith-secret-scan: allow
    out=$(scan "$repo" asia.txt)
    assert_contains "aws-asia detected" "$out" "aws-asia"
    rm -rf "$repo"
}
{
    repo=$(make_repo)
    printf 'aws_secret_access_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"\n' > "$repo/awssecret.txt"  # smith-secret-scan: allow
    out=$(scan "$repo" awssecret.txt)
    assert_contains "aws-secret-key (context-gated) detected" "$out" "aws-secret-key"
    rm -rf "$repo"
}
{
    repo=$(make_repo)
    printf 'token = "ghp_EXAMPLE1234567890EXAMPLE1234567890EXAMPLE"\n' > "$repo/gh.txt"  # smith-secret-scan: allow
    out=$(scan "$repo" gh.txt)
    assert_contains "github-token detected" "$out" "github-token"
    rm -rf "$repo"
}
{
    repo=$(make_repo)
    printf 'slack = "xoxb-TESTFAKE-TESTFAKE-TESTFAKETOKEN"\n' > "$repo/slack.txt"  # smith-secret-scan: allow
    out=$(scan "$repo" slack.txt)
    assert_contains "slack-token detected" "$out" "slack-token"
    rm -rf "$repo"
}
{
    repo=$(make_repo)
    printf 'DATABASE_URL = "postgres://fakeuser:fakepassEXAMPLE@db.example.com:5432/mydb"\n' > "$repo/conn.txt"  # smith-secret-scan: allow
    out=$(scan "$repo" conn.txt)
    assert_contains "conn-string-creds detected" "$out" "conn-string-creds"
    rm -rf "$repo"
}
{
    repo=$(make_repo)
    printf -- '-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAfakeFakeFakeFakeFakeFakeFakeFakeFakeFake==\n-----END RSA PRIVATE KEY-----\n' > "$repo/pem.txt"  # smith-secret-scan: allow
    out=$(scan "$repo" pem.txt)
    assert_contains "pem-private-key detected" "$out" "pem-private-key"
    rm -rf "$repo"
}
{
    repo=$(make_repo)
    printf '%s\n' '{' > "$repo/gcp.json"
    printf '%s\n' '  "type": "service_account",' >> "$repo/gcp.json"
    printf '%s\n' '  "project_id": "fake-project",' >> "$repo/gcp.json"
    printf '%s\n' '  "private_key_id": "fake-key-id-EXAMPLE",' >> "$repo/gcp.json"  # smith-secret-scan: allow
    printf '%s\n' '  "client_email": "fake@fake-project.iam.gserviceaccount.com"' >> "$repo/gcp.json"
    printf '%s\n' '}' >> "$repo/gcp.json"
    out=$(scan "$repo" gcp.json)
    assert_contains "gcp-sa-json detected" "$out" "gcp-sa-json"
    rm -rf "$repo"
}
{
    repo=$(make_repo)
    printf 'api_key = "Vq3Xn8Kw2Jm7Rt4Lp9Hd5Fs1Gy6Bc0Ez"\n' > "$repo/generic.txt"  # smith-secret-scan: allow
    out=$(scan "$repo" generic.txt)
    assert_contains "generic-high-entropy-assignment detected" "$out" "generic-high-entropy-assignment"
    rm -rf "$repo"
}

# ================= 2: exclude-path suppression =================
{
    repo=$(make_repo)
    mkdir -p "$repo/vendor"
    printf 'aws_key = "AKIAIOSFODNN7EXAMPLE"\n' > "$repo/vendor/secret.js"  # smith-secret-scan: allow
    out=$(scan "$repo" vendor/secret.js)
    assert_eq "vendor/ exclusion suppresses finding" "" "$out"
    assert_eq "vendor/ exclusion exit code 0" "0" "$(scan_exit "$repo" vendor/secret.js)"
    rm -rf "$repo"
}

# ================= 3: glob-allowlist suppression (entropy only) =================
{
    repo=$(make_repo)
    printf 'api_key = "Vq3Xn8Kw2Jm7Rt4Lp9Hd5Fs1Gy6Bc0Ez"\n' > "$repo/package-lock.json"  # smith-secret-scan: allow
    out=$(scan "$repo" package-lock.json)
    assert_eq "package-lock.json allowlist suppresses entropy finding" "" "$out"
    printf 'aws_key = "AKIAIOSFODNN7EXAMPLE"\n' > "$repo/package-lock.json"  # smith-secret-scan: allow
    out=$(scan "$repo" package-lock.json)
    assert_contains "package-lock.json allowlist does NOT suppress deterministic aws-akia" "$out" "aws-akia"
    rm -rf "$repo"
}

# ================= 4: entropy-threshold negative cases =================
{
    repo=$(make_repo)
    printf 'password = "changeme"\ntoken = "test"\ntoken = "aaaaaaaaaaaaaaaaaaaaaaaa"\n' > "$repo/negative.txt"
    out=$(scan "$repo" negative.txt)
    assert_eq "low-entropy/too-short assignments do not fire" "" "$out"
    rm -rf "$repo"
}

# ================= 5: allowlist-marker suppression, with same-pattern contrast =================
{
    repo=$(make_repo)
    printf -- '-----BEGIN RSA PRIVATE KEY----- # smith-secret-scan: allow\napi_key = "Vq3Xn8Kw2Jm7Rt4Lp9Hd5Fs1Gy6Bc0Ez" # smith-secret-scan: allow\n-----BEGIN RSA PRIVATE KEY-----\napi_key = "Vq3Xn8Kw2Jm7Rt4Lp9Hd5Fs1Gy6Bc0Ez"\n' > "$repo/marker.txt"
    out=$(scan "$repo" marker.txt)
    pem_count=$(printf '%s' "$out" | grep -c "pem-private-key")
    generic_count=$(printf '%s' "$out" | grep -c "generic-high-entropy-assignment")
    assert_eq "marker suppresses PEM on line 1, contrast line 3 still fires" "1" "$pem_count"
    assert_eq "marker suppresses generic assignment on line 2, contrast line 4 still fires" "1" "$generic_count"
    assert_contains "surviving pem finding is on line 3, not line 1" "$out" "|3|pem-private-key"
    assert_contains "surviving generic finding is on line 4, not line 2" "$out" "|4|generic-high-entropy-assignment"
    rm -rf "$repo"
}

# ================= 6: redaction verification =================
{
    repo=$(make_repo)
    printf 'aws_key = "AKIAIOSFODNN7EXAMPLE"\n' > "$repo/redact.txt"  # smith-secret-scan: allow
    out=$(scan "$repo" redact.txt)
    assert_not_contains "full AKIA canary absent from stdout" "$out" "AKIAIOSFODNN7EXAMPLE"  # smith-secret-scan: allow
    assert_contains "masked excerpt present instead" "$out" "AKIA********MPLE"
    rm -rf "$repo"
}

# ================= 7: gitleaks-merge behavior via a stubbed executable =================
{
    repo=$(make_repo)
    stub_dir=$(mktemp -d)
    secret_canary="AKIASTUBSTUBSTUBEXAM"  # smith-secret-scan: allow
    printf '%s\n' '#!/usr/bin/env bash' > "$stub_dir/gitleaks"
    printf '%s\n' "echo '[{\"File\":\"fixture.py\",\"StartLine\":5,\"RuleID\":\"aws-access-token\",\"Secret\":\"$secret_canary\"}]'" >> "$stub_dir/gitleaks"
    chmod +x "$stub_dir/gitleaks"
    printf 'aws_key = "AKIAIOSFODNN7EXAMPLE"\n' > "$repo/fixture.py"  # smith-secret-scan: allow
    out=$(cd "$repo" && PATH="$stub_dir:$PATH" "$INTERPRETER_BIN" "$WRAPPER" --files fixture.py --with-gitleaks)
    assert_contains "gitleaks: pattern-id prefix present" "$out" "gitleaks:aws-access-token"
    builtin_line=$(printf '%s\n' "$out" | grep -n "aws-akia" | head -1 | cut -d: -f1)
    gitleaks_line=$(printf '%s\n' "$out" | grep -n "gitleaks:aws-access-token" | head -1 | cut -d: -f1)
    if [ -n "$builtin_line" ] && [ -n "$gitleaks_line" ] && [ "$gitleaks_line" -gt "$builtin_line" ]; then
        PASS=$((PASS + 1)); echo "PASS: gitleaks finding appended AFTER built-in finding"
    else
        FAIL=$((FAIL + 1)); FAILED_NAMES+=("gitleaks-order")
        echo "FAIL: gitleaks finding appended AFTER built-in finding"
        echo "  builtin_line=$builtin_line gitleaks_line=$gitleaks_line"
    fi
    assert_not_contains "gitleaks-sourced secret also redacted" "$out" "AKIASTUBSTUBSTUBEXAM"  # smith-secret-scan: allow
    rm -rf "$repo" "$stub_dir"
}

# ================= 8: empty-diff / no-files case: zero findings, exit 0 =================
{
    repo=$(make_repo)
    out=$(cd "$repo" && "$INTERPRETER_BIN" "$WRAPPER" --files)
    ec=$?
    assert_eq "no files -> empty stdout" "" "$out"
    assert_eq "no files -> exit code 0" "0" "$ec"
    rm -rf "$repo"
}

# ================= 9: multi-finding case asserting exit code 1 =================
{
    repo=$(make_repo)
    printf 'aws_key = "AKIAIOSFODNN7EXAMPLE"\ntemp_key = "ASIAIOSFODNN7EXAMPLE"\n' > "$repo/multi.txt"  # smith-secret-scan: allow
    out=$(scan "$repo" multi.txt)
    line_count=$(printf '%s\n' "$out" | grep -c "|")
    assert_eq "multi-finding file yields 2+ finding lines" "true" "$( [ "$line_count" -ge 2 ] && echo true || echo false )"
    assert_eq "multi-finding exit code 1" "1" "$(scan_exit "$repo" multi.txt)"
    rm -rf "$repo"
}

# ================= 10: exit code 2 — internal error (distinct from 0/1) =================
{
    repo=$(make_repo)
    scratch=$(mktemp -d)
    cp "$WRAPPER" "$scratch/secret-scan.sh"
    cp "$ENGINE" "$scratch/secret_scan.py"
    chmod 000 "$scratch/secret_scan.py"
    printf 'benign\n' > "$repo/f.txt"
    (cd "$repo" && "$INTERPRETER_BIN" "$scratch/secret-scan.sh" --files f.txt >/dev/null 2>&1)
    ec=$?
    assert_eq "unreadable engine -> exit code 2" "2" "$ec"
    chmod 644 "$scratch/secret_scan.py"
    rm -rf "$scratch"

    # Missing python3 on $PATH, simulated via a scratch PATH containing
    # only the non-python tools the wrapper itself needs to start up.
    minimal_bin=$(mktemp -d)
    for tool in dirname cat mktemp chmod basename git; do
        real=$(command -v "$tool" 2>/dev/null) || continue
        ln -s "$real" "$minimal_bin/$tool"
    done
    (cd "$repo" && PATH="$minimal_bin" "$INTERPRETER_BIN" "$WRAPPER" --files f.txt >/dev/null 2>&1)
    ec=$?
    assert_eq "missing python3 on PATH -> exit code 2" "2" "$ec"
    rm -rf "$repo" "$minimal_bin"
}

# ================= 11: --diff-base scope resolution =================
# scan_diff_base <repo> <base-ref> -> stdout of secret-scan.sh --diff-base
# <base-ref>, run from inside <repo> under the self-detected interpreter.
scan_diff_base() {
    local repo="$1" base="$2"
    (cd "$repo" && "$INTERPRETER_BIN" "$WRAPPER" --diff-base "$base")
}
scan_diff_base_exit() {
    local repo="$1" base="$2"
    (cd "$repo" && "$INTERPRETER_BIN" "$WRAPPER" --diff-base "$base" >/dev/null 2>&1)
    printf '%s' "$?"
}
{
    # (a) committed-diff detection: a tracked file changed after base commit.
    repo=$(make_repo)
    base=$(cd "$repo" && git rev-parse HEAD)
    printf 'x=1\n' > "$repo/tracked.txt"
    (cd "$repo" && git add tracked.txt && git commit -q -m "add tracked")
    printf 'x=2\naws_key = "AKIAIOSFODNN7EXAMPLE"\n' > "$repo/tracked.txt"  # smith-secret-scan: allow
    out=$(scan_diff_base "$repo" "$base")
    assert_contains "--diff-base: committed-then-modified tracked file detected" "$out" "tracked.txt"
    assert_eq "--diff-base: committed-diff exit code 1" "1" "$(scan_diff_base_exit "$repo" "$base")"
    rm -rf "$repo"
}
{
    # (b) REGRESSION CASE for the Critical finding: base commit is clean,
    # an UNTRACKED file (never added/committed) carries a canary. The
    # pre-fix wrapper built --diff-base scope from `git diff --name-only
    # "$DIFF_BASE" --` alone, which is blind to untracked files, so this
    # case FAILED (exit 0, no finding) against the pre-fix logic. Must
    # PASS (exit 1, finding present) against the fix.
    repo=$(make_repo)
    base=$(cd "$repo" && git rev-parse HEAD)
    printf 'aws_key = "AKIAIOSFODNN7EXAMPLE"\n' > "$repo/untracked_secret.txt"  # smith-secret-scan: allow
    out=$(scan_diff_base "$repo" "$base")
    assert_contains "--diff-base: untracked file with canary is detected (regression guard)" "$out" "untracked_secret.txt"
    assert_contains "--diff-base: untracked file finding is aws-akia" "$out" "aws-akia"
    assert_eq "--diff-base: untracked-only exit code 1" "1" "$(scan_diff_base_exit "$repo" "$base")"
    rm -rf "$repo"
}
{
    # (c) mixed case: a tracked-modified file AND an untracked file both in
    # scope at once, both must be scanned/reported.
    repo=$(make_repo)
    base=$(cd "$repo" && git rev-parse HEAD)
    printf 'x=1\n' > "$repo/tracked2.txt"
    (cd "$repo" && git add tracked2.txt && git commit -q -m "add tracked2")
    printf 'x=2\ntoken = "ghp_EXAMPLE1234567890EXAMPLE1234567890EXAMPLE"\n' > "$repo/tracked2.txt"  # smith-secret-scan: allow
    printf 'aws_key = "AKIAIOSFODNN7EXAMPLE"\n' > "$repo/untracked2.txt"  # smith-secret-scan: allow
    out=$(scan_diff_base "$repo" "$base")
    assert_contains "--diff-base mixed: tracked-modified file reported" "$out" "tracked2.txt"
    assert_contains "--diff-base mixed: untracked file reported" "$out" "untracked2.txt"
    assert_contains "--diff-base mixed: github-token pattern fired" "$out" "github-token"
    assert_contains "--diff-base mixed: aws-akia pattern fired" "$out" "aws-akia"
    assert_eq "--diff-base mixed exit code 1" "1" "$(scan_diff_base_exit "$repo" "$base")"
    rm -rf "$repo"
}

# ---------- summary ----------
echo "----"
echo "SUMMARY: $PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
    echo "Failed: ${FAILED_NAMES[*]}"
fi

[ "$FAIL" -eq 0 ]
