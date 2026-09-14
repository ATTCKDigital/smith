#!/usr/bin/env bash
# test_dependency_scan.sh — tests for scripts/security/dependency-scan.sh +
# dependency-scan.py + _manifest_discovery.py + _scan_parsers.py
# (feature 56-supply-chain-gate, T006).
#
# Structural template: tests/security/test_secret_scan.sh's make_repo/
# assert_*/PASS/FAIL/summary/exit-status shape, plus
# tests/security/test_detect_scanners.sh's scratch-$PATH stub idiom.
# NO live network calls, ever — every scanner (npm/osv-scanner/trivy/
# pip-audit/poetry) is a planted, executable scratch-$PATH stub printing
# FIXED output. A real python3 (and the handful of POSIX tools the
# scripts themselves need) is symlinked into every scratch dir so the
# engine under test can actually run.
#
# Run:  bash tests/security/test_dependency_scan.sh
#       zsh  tests/security/test_dependency_scan.sh

set -u

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
WRAPPER="$REPO/scripts/security/dependency-scan.sh"
ENGINE="$REPO/scripts/security/dependency-scan.py"

if [ ! -f "$WRAPPER" ] || [ ! -f "$ENGINE" ]; then
    echo "FATAL: dependency-scan.sh or dependency-scan.py not found under $REPO/scripts/security" >&2
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

# ---------- fixture + scratch-PATH helpers ----------

# make_scratch -> prints a fresh dir with a real python3 (+ the few POSIX
# tools the engine/its subprocess calls need) symlinked in, so the
# engine under test can run under a FULLY narrowed $PATH — no real
# scanner on the host machine can leak into a test.
make_scratch() {
    local dir
    dir=$(mktemp -d)
    for tool in python3 sh bash env sleep dirname cat basename; do
        real=$(command -v "$tool" 2>/dev/null) || continue
        ln -sf "$real" "$dir/$tool"
    done
    printf '%s' "$dir"
}

write_stub() {
    local dir="$1" name="$2" body="$3"
    printf '#!/usr/bin/env bash\n%s\n' "$body" > "$dir/$name"
    chmod +x "$dir/$name"
}

# A stub npm printing research.md §7.1's exact live-captured
# goldcanna-inventory/frontend metadata.vulnerabilities shape.
NPM_AUDIT_JSON='{"metadata": {"vulnerabilities": {"info": 0, "low": 1, "moderate": 5, "high": 19, "critical": 3, "total": 28}}}'
write_npm_stub() {
    local dir="$1" exit_code="$2"
    write_stub "$dir" npm "cat <<'JSON'
$NPM_AUDIT_JSON
JSON
exit $exit_code"
}

write_npm_sleep_stub() {
    write_stub "$1" npm "sleep 10
exit 1"
}

write_npm_offline_stub() {
    write_stub "$1" npm ">&2 echo 'npm ERR! network getaddrinfo ENOTFOUND registry.npmjs.org'
exit 1"
}

# A poetry stub handling BOTH "env info -p" (used by _manifest_discovery.py)
# and "run <cmd...>" (used by dependency-scan.py's pip-audit fallback) —
# forwards "run" straight to whatever's next on $PATH (another stub).
write_poetry_stub() {
    write_stub "$1" poetry '
if [ "$1" = "env" ]; then
    echo "/fake/venv"
    exit 0
fi
if [ "$1" = "run" ]; then
    shift
    exec "$@"
fi
exit 1'
}

write_pip_audit_stub() {
    local dir="$1" json="$2"
    write_stub "$dir" pip-audit "cat <<'JSON'
$json
JSON"
}

write_osv_scanner_stub() {
    write_stub "$1" osv-scanner "echo '{\"results\": []}'"
}

write_trivy_stub() {
    write_stub "$1" trivy "echo '{\"Results\": []}'"
}

write_grype_stub() {
    write_stub "$1" grype "echo '{}'"
}

# make_repo -> the goldcanna-inventory-shaped 3-manifest fixture
# (research.md/plan.md's own Test strategy layout).
make_repo() {
    local dir
    dir=$(mktemp -d)
    mkdir -p "$dir/frontend" "$dir/menu-generator" "$dir/backend"
    printf '{"name":"frontend","version":"1.0.0"}\n' > "$dir/frontend/package.json"
    printf '{}\n' > "$dir/frontend/package-lock.json"
    printf '{"name":"menu-generator","version":"1.0.0"}\n' > "$dir/menu-generator/package.json"
    printf '{}\n' > "$dir/menu-generator/package-lock.json"
    printf '[tool.poetry]\nname = "backend"\n' > "$dir/backend/pyproject.toml"
    : > "$dir/backend/poetry.lock"
    printf '%s' "$dir"
}

make_single_npm_repo() {
    local dir
    dir=$(mktemp -d)
    mkdir -p "$dir/app"
    printf '{"name":"app","version":"1.0.0"}\n' > "$dir/app/package.json"
    printf '{}\n' > "$dir/app/package-lock.json"
    printf '%s' "$dir"
}

make_single_poetry_repo() {
    local dir
    dir=$(mktemp -d)
    mkdir -p "$dir/app"
    printf '[tool.poetry]\nname = "app"\n' > "$dir/app/pyproject.toml"
    : > "$dir/app/poetry.lock"
    printf '%s' "$dir"
}

# scan <scratch> <repo> [extra args...] -> stdout of dependency-scan.sh
scan() {
    local scratch="$1" repo="$2"; shift 2
    (PATH="$scratch" "$INTERPRETER_BIN" "$WRAPPER" --repo-root "$repo" "$@")
}
scan_exit() {
    local scratch="$1" repo="$2"; shift 2
    (PATH="$scratch" "$INTERPRETER_BIN" "$WRAPPER" --repo-root "$repo" "$@" >/dev/null 2>&1)
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

# ================= 1: multi-manifest merge (FR-5) =================
{
    repo=$(make_repo)
    scratch=$(make_scratch)
    write_npm_stub "$scratch" 1
    out=$(scan "$scratch" "$repo")
    assert_contains "multi-manifest: MANIFEST_COUNT 3" "$out" "MANIFEST_COUNT: 3"
    assert_contains "multi-manifest: frontend ran:npm-audit" "$out" "frontend/package.json: cve_scan=ran:npm-audit"
    assert_contains "multi-manifest: menu-generator ran:npm-audit" "$out" "menu-generator/package.json: cve_scan=ran:npm-audit"
    assert_contains "multi-manifest: backend skipped:absent (no pip-audit)" "$out" "backend/pyproject.toml: cve_scan=skipped:absent"
    assert_contains "multi-manifest: finding carries frontend manifest_path" "$out" "(\`frontend/package.json\`)"
    assert_contains "multi-manifest: finding carries menu-generator manifest_path" "$out" "(\`menu-generator/package.json\`)"
    rm -rf "$repo" "$scratch"
}

# ================= 2: ENOLOCK skip alongside unaffected sibling (FR-7, US-4) =================
{
    repo=$(make_repo)
    rm -f "$repo/menu-generator/package-lock.json"
    scratch=$(make_scratch)
    write_npm_stub "$scratch" 1
    out=$(scan "$scratch" "$repo")
    assert_contains "enolock: menu-generator skipped:enolock" "$out" "menu-generator/package.json: cve_scan=skipped:enolock"
    assert_contains "enolock: frontend sibling unaffected" "$out" "frontend/package.json: cve_scan=ran:npm-audit"
    rm -rf "$repo" "$scratch"
}

# ================= 3: ENOLOCK-wrong-format skip (research.md §7.1) =================
{
    repo=$(mktemp -d)
    mkdir -p "$repo/app"
    printf '{"name":"app"}\n' > "$repo/app/package.json"
    : > "$repo/app/yarn.lock"
    scratch=$(make_scratch)
    write_npm_stub "$scratch" 1
    out=$(scan "$scratch" "$repo")
    assert_contains "enolock_wrong_format: yarn-only lockfile" "$out" "app/package.json: cve_scan=skipped:enolock_wrong_format"
    rm -rf "$repo" "$scratch"
}

# ================= 4: npm audit severity-bucket mapping + exit-code independence (FR-11) =================
{
    repo=$(make_single_npm_repo)
    scratch1=$(make_scratch); write_npm_stub "$scratch1" 1
    out_exit1=$(scan "$scratch1" "$repo")
    medium_count=$(printf '%s\n' "$out_exit1" | grep -c '\[Medium\]')
    assert_eq "npm audit: moderate->Medium x5" "5" "$medium_count"
    assert_contains "npm audit: exit1 status is ran, never skipped" "$out_exit1" "cve_scan=ran:npm-audit"
    assert_not_contains "npm audit: exit1 status never skipped:*" "$out_exit1" "cve_scan=skipped"

    scratch0=$(make_scratch); write_npm_stub "$scratch0" 0
    out_exit0=$(scan "$scratch0" "$repo")
    assert_eq "npm audit: byte-identical parsed output regardless of exit code" "$out_exit1" "$out_exit0"
    rm -rf "$repo" "$scratch1" "$scratch0"
}

# ================= 5: pip-audit severity-default-to-Medium (gap #3) =================
{
    repo=$(make_single_poetry_repo)
    scratch=$(make_scratch)
    write_poetry_stub "$scratch"
    write_pip_audit_stub "$scratch" '{"dependencies": [{"name": "fixturepkg", "version": "1.0.0", "vulns": [{"id": "PYSEC-9999-0", "fix_versions": ["1.0.1"], "description": "test advisory, no severity field."}]}]}'
    out=$(scan "$scratch" "$repo")
    assert_contains "pip-audit: no-severity finding defaults to Medium" "$out" "[Medium]"
    assert_contains "pip-audit: rationale states default was applied" "$out" "defaulted to Medium"
    assert_contains "pip-audit: status ran:pip-audit" "$out" "cve_scan=ran:pip-audit"
    rm -rf "$repo" "$scratch"
}

# ================= 6: pip-audit-absent skip =================
{
    repo=$(make_single_poetry_repo)
    scratch=$(make_scratch)
    out=$(scan "$scratch" "$repo")
    assert_contains "pip-audit absent: skipped:absent" "$out" "cve_scan=skipped:absent"
    rm -rf "$repo" "$scratch"
}

# ================= 7: timeout simulation (FR-12/US-5) =================
{
    repo=$(make_single_npm_repo)
    scratch=$(make_scratch)
    write_npm_sleep_stub "$scratch"
    start=$(date +%s)
    out=$(scan "$scratch" "$repo" --timeout-seconds 2)
    end=$(date +%s)
    elapsed=$((end - start))
    assert_contains "timeout: skipped:timeout" "$out" "cve_scan=skipped:timeout"
    assert_eq "timeout: test itself completes quickly (bounded, not real 60s default)" "true" "$( [ "$elapsed" -lt 20 ] && echo true || echo false )"
    rm -rf "$repo" "$scratch"
}

# ================= 8: offline simulation =================
{
    repo=$(make_single_npm_repo)
    scratch=$(make_scratch)
    write_npm_offline_stub "$scratch"
    out=$(scan "$scratch" "$repo" --timeout-seconds 5)
    assert_contains "offline: skipped:offline" "$out" "cve_scan=skipped:offline"
    rm -rf "$repo" "$scratch"
}

# ================= 9: zero-manifest silent-skip (FR-6) =================
{
    repo=$(mktemp -d)
    scratch=$(make_scratch)
    out=$(scan "$scratch" "$repo")
    ec=$(scan_exit "$scratch" "$repo")
    assert_eq "zero-manifest: MANIFEST_COUNT 0, nothing else" "MANIFEST_COUNT: 0" "$out"
    assert_eq "zero-manifest: exit code 0" "0" "$ec"
    rm -rf "$repo" "$scratch"
}

# ================= 10: osv-scanner/trivy-preferred-over-fallback (FR-8) =================
{
    repo=$(make_repo)
    scratch=$(make_scratch)
    write_osv_scanner_stub "$scratch"
    out=$(scan "$scratch" "$repo")
    same_scanner=$(printf '%s\n' "$out" | grep -c "cve_scan=ran:osv-scanner")
    assert_eq "osv-scanner only: all 3 manifests report ran:osv-scanner" "3" "$same_scanner"
    rm -rf "$repo" "$scratch"
}
{
    repo=$(make_repo)
    scratch=$(make_scratch)
    write_osv_scanner_stub "$scratch"
    write_trivy_stub "$scratch"
    out=$(scan "$scratch" "$repo")
    assert_contains "both present: osv-scanner preferred over trivy" "$out" "cve_scan=ran:osv-scanner"
    assert_not_contains "both present: trivy never used when osv-scanner present" "$out" "cve_scan=ran:trivy"
    rm -rf "$repo" "$scratch"
}

# ================= 11: grype-detected-but-never-invoked (gap #4) =================
{
    repo=$(make_single_npm_repo)
    scratch=$(make_scratch)
    write_grype_stub "$scratch"
    write_npm_stub "$scratch" 1
    out=$(scan "$scratch" "$repo")
    assert_contains "grype present alone: still falls through to npm-audit fallback" "$out" "cve_scan=ran:npm-audit"
    assert_not_contains "grype present alone: never referenced in output" "$out" "grype"
    rm -rf "$repo" "$scratch"
}

# ================= 12: cve_scan=disabled (config toggle) =================
{
    repo=$(make_single_npm_repo)
    mkdir -p "$repo/.smith"
    printf '{"supply_chain": {"cve_scan": false}}\n' > "$repo/.smith/config.json"
    scratch=$(make_scratch)
    write_npm_stub "$scratch" 1
    out=$(scan "$scratch" "$repo")
    assert_contains "disabled: status is disabled, not ran/skipped" "$out" "cve_scan=disabled"
    assert_not_contains "disabled: no findings emitted" "$out" "[Medium]"
    rm -rf "$repo" "$scratch"
}

# ================= 13: internal-error exit code 2 =================
{
    ec=$(PATH="$(make_scratch)" "$INTERPRETER_BIN" "$WRAPPER" --repo-root "/nonexistent/path/$$" >/dev/null 2>&1; echo $?)
    assert_eq "nonexistent repo-root -> exit code 2" "2" "$ec"
}

# ---------- summary ----------
echo "----"
echo "SUMMARY: $PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
    echo "Failed: ${FAILED_NAMES[*]}"
fi

[ "$FAIL" -eq 0 ]
