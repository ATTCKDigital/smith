#!/usr/bin/env bash
# test_license_inventory.sh — tests for scripts/security/license-inventory.sh
# + license-inventory.py + _manifest_discovery.py (feature
# 56-supply-chain-gate, T007).
#
# Structural template: tests/security/test_dependency_scan.sh's make_scratch/
# assert_*/PASS/FAIL/summary/exit-status shape. NO live network/poetry
# calls, ever — the one subprocess this engine invokes (`poetry run
# python3 -c ...`) is stubbed via a scratch-$PATH `poetry` script that
# forwards to a REAL python3 run with `-S` (skip ambient site-packages) +
# PYTHONPATH pointed at a planted fixture dist-info directory — fully
# isolating importlib.metadata's view from whatever happens to be
# installed on the host running this test.
#
# The inventory itself is never printed to stdout by the engine under
# test (only deny-list policy findings are) — so every fallback-chain
# assertion below (npm legacy licenses[], Python License-Expression-only,
# genuinely license-less -> UNKNOWN) is verified INDIRECTLY: a distinctive
# fixture license id is deny-listed, and a resulting High finding proves
# that id was the one actually resolved.
#
# Run:  bash tests/security/test_license_inventory.sh
#       zsh  tests/security/test_license_inventory.sh

set -u

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
WRAPPER="$REPO/scripts/security/license-inventory.sh"
ENGINE="$REPO/scripts/security/license-inventory.py"

if [ ! -f "$WRAPPER" ] || [ ! -f "$ENGINE" ]; then
    echo "FATAL: license-inventory.sh or license-inventory.py not found under $REPO/scripts/security" >&2
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

make_scratch() {
    local dir
    dir=$(mktemp -d)
    for tool in python3 sh bash env dirname cat basename; do
        real=$(command -v "$tool" 2>/dev/null) || continue
        ln -sf "$real" "$dir/$tool"
    done
    printf '%s' "$dir"
}

# write_poetry_stub <scratch-dir> <fixture-site-packages-dir> — handles
# BOTH "env info -p" (_manifest_discovery.py's own venv resolution) and
# "run python3 -c <code>" (license-inventory.py's importlib.metadata
# walk), isolating the latter to ONLY the fixture dir via -S + PYTHONPATH.
write_poetry_stub() {
    local dir="$1" site="$2"
    cat > "$dir/poetry" <<EOF
#!/usr/bin/env bash
if [ "\$1" = "env" ]; then
    echo "/fake/venv"
    exit 0
fi
if [ "\$1" = "run" ]; then
    shift
    if [ "\$1" = "python3" ]; then
        shift
        exec env PYTHONPATH="$site" python3 -S "\$@"
    fi
    exec "\$@"
fi
exit 1
EOF
    chmod +x "$dir/poetry"
}

# make_dist_info <site-dir> <pkg> <version> [extra METADATA line]...
make_dist_info() {
    local site="$1" pkg="$2" version="$3"
    local info_dir="$site/${pkg}-${version}.dist-info"
    mkdir -p "$info_dir"
    shift 3
    {
        echo "Metadata-Version: 2.1"
        echo "Name: $pkg"
        echo "Version: $version"
        for line in "$@"; do echo "$line"; done
    } > "$info_dir/METADATA"
}

make_poetry_repo() {
    local dir
    dir=$(mktemp -d)
    mkdir -p "$dir/backend"
    printf '[tool.poetry]\nname = "backend"\n' > "$dir/backend/pyproject.toml"
    : > "$dir/backend/poetry.lock"
    printf '%s' "$dir"
}

write_config_deny() {
    local repo="$1"; shift
    mkdir -p "$repo/.smith"
    local deny_json="[]"
    if [ "$#" -gt 0 ]; then
        deny_json="[\"$1\"]"
    fi
    printf '{"supply_chain": {"license_policy": {"deny": %s}}}\n' "$deny_json" > "$repo/.smith/config.json"
}

# scan <scratch> <repo> -> stdout of license-inventory.sh
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

# ================= 1: npm legacy licenses[] fallback (xmlhttprequest-ssl shape) =================
{
    repo=$(mktemp -d)
    mkdir -p "$repo/frontend/node_modules/xmlhttprequest-ssl"
    printf '{"name":"frontend"}\n' > "$repo/frontend/package.json"
    : > "$repo/frontend/package-lock.json"
    cat > "$repo/frontend/node_modules/xmlhttprequest-ssl/package.json" <<'EOF'
{"name": "xmlhttprequest-ssl", "version": "1.6.3", "licenses": [{"type": "XHR-LEGACY-FIXTURE", "url": "https://example.test"}]}
EOF
    write_config_deny "$repo" "XHR-LEGACY-FIXTURE"
    scratch=$(make_scratch)
    out=$(scan "$scratch" "$repo")
    assert_contains "npm legacy licenses[] fallback resolves (not UNKNOWN)" "$out" "xmlhttprequest-ssl@1.6.3"
    assert_contains "npm legacy licenses[] fallback: High finding, sub-layer L" "$out" "sub-layer: L"
    rm -rf "$repo" "$scratch"
}

# ================= 2: License-Expression-only fallback (click-shaped) =================
{
    repo=$(make_poetry_repo)
    site=$(mktemp -d)
    make_dist_info "$site" clickfixture 8.1.0 "License-Expression: BSD-3-Clause-TESTFIXTURE"
    write_config_deny "$repo" "BSD-3-Clause-TESTFIXTURE"
    scratch=$(make_scratch)
    write_poetry_stub "$scratch" "$site"
    out=$(scan "$scratch" "$repo")
    assert_contains "License-Expression-only 3-tier chain resolves it" "$out" "clickfixture@8.1.0"
    assert_contains "License-Expression-only: status ran" "$out" "backend/pyproject.toml: license_inventory=ran"
    rm -rf "$repo" "$scratch" "$site"
}

# ================= 3: genuinely license-less -> UNKNOWN bucketing =================
{
    repo=$(mktemp -d)
    mkdir -p "$repo/frontend/node_modules/nolicensepkg"
    printf '{"name":"frontend"}\n' > "$repo/frontend/package.json"
    : > "$repo/frontend/package-lock.json"
    printf '{"name": "nolicensepkg", "version": "2.0.0"}\n' > "$repo/frontend/node_modules/nolicensepkg/package.json"
    write_config_deny "$repo" "UNKNOWN"
    scratch=$(make_scratch)
    out=$(scan "$scratch" "$repo")
    assert_contains "npm genuinely license-less -> UNKNOWN bucket fires" "$out" "nolicensepkg@2.0.0"
    rm -rf "$repo" "$scratch"
}
{
    repo=$(make_poetry_repo)
    site=$(mktemp -d)
    make_dist_info "$site" barelib 3.0.0
    write_config_deny "$repo" "UNKNOWN"
    scratch=$(make_scratch)
    write_poetry_stub "$scratch" "$site"
    out=$(scan "$scratch" "$repo")
    assert_contains "python genuinely license-less (no fallback field) -> UNKNOWN" "$out" "barelib@3.0.0"
    rm -rf "$repo" "$scratch" "$site"
}

# ================= 4: node_modules-absent-but-lockfile-present skip (FR-14, US-6) =================
{
    repo=$(mktemp -d)
    mkdir -p "$repo/frontend"
    printf '{"name":"frontend"}\n' > "$repo/frontend/package.json"
    : > "$repo/frontend/package-lock.json"
    # node_modules/ deliberately absent — package.json + lockfile alone
    # is enough for Sub-layer D's own lockfile-only precondition, but
    # NOT enough for Sub-layer L's stricter node_modules_present gate
    # (FR-14) — a sibling cross-reference only, this file never invokes
    # dependency-scan.py itself.
    scratch=$(make_scratch)
    out=$(scan "$scratch" "$repo")
    assert_contains "node_modules absent -> skipped:no_node_modules" "$out" "frontend/package.json: license_inventory=skipped:no_node_modules"
    rm -rf "$repo" "$scratch"
}

# ================= 5: requirements.txt-only manifest -> skipped:no_venv unconditionally =================
{
    repo=$(mktemp -d)
    mkdir -p "$repo/svc"
    printf 'requests==2.31.0\n' > "$repo/svc/requirements.txt"
    scratch=$(make_scratch)
    out=$(scan "$scratch" "$repo")
    assert_contains "requirements.txt-only -> skipped:no_venv" "$out" "svc/requirements.txt: license_inventory=skipped:no_venv"
    rm -rf "$repo" "$scratch"
}

# ================= 6: deny-list match (FR-18/US-7) =================
{
    repo=$(mktemp -d)
    mkdir -p "$repo/frontend/node_modules/gpl-pkg"
    printf '{"name":"frontend"}\n' > "$repo/frontend/package.json"
    : > "$repo/frontend/package-lock.json"
    printf '{"name": "gpl-pkg", "version": "1.2.3", "license": "GPL-3.0"}\n' > "$repo/frontend/node_modules/gpl-pkg/package.json"
    write_config_deny "$repo" "GPL-3.0"
    scratch=$(make_scratch)
    out=$(scan "$scratch" "$repo")
    ec=$(scan_exit "$scratch" "$repo")
    assert_contains "deny-list hit: High severity" "$out" "[High]"
    assert_contains "deny-list hit: gpl-pkg finding" "$out" "gpl-pkg@1.2.3"
    assert_contains "deny-list hit: category license-policy" "$out" "category: license-policy"
    assert_eq "deny-list hit: exit code 1" "1" "$ec"
    rm -rf "$repo" "$scratch"
}

# ================= 7: allow-list is a documented no-op (A-4) =================
{
    repo=$(mktemp -d)
    mkdir -p "$repo/frontend/node_modules/mitpkg"
    printf '{"name":"frontend"}\n' > "$repo/frontend/package.json"
    : > "$repo/frontend/package-lock.json"
    printf '{"name": "mitpkg", "version": "9.9.9", "license": "MIT"}\n' > "$repo/frontend/node_modules/mitpkg/package.json"
    scratch=$(make_scratch)

    mkdir -p "$repo/.smith"
    printf '{"supply_chain": {"license_policy": {"allow": [], "deny": []}}}\n' > "$repo/.smith/config.json"
    out_empty_allow=$(scan "$scratch" "$repo")

    printf '{"supply_chain": {"license_policy": {"allow": ["Apache-2.0"], "deny": []}}}\n' > "$repo/.smith/config.json"
    out_populated_allow=$(scan "$scratch" "$repo")

    assert_eq "allow-list populated vs empty: identical output (no-op)" "$out_empty_allow" "$out_populated_allow"
    assert_not_contains "allow-list never produces a finding on its own" "$out_populated_allow" "[High]"
    rm -rf "$repo" "$scratch"
}

# ================= 8: zero-manifest case =================
{
    repo=$(mktemp -d)
    scratch=$(make_scratch)
    out=$(scan "$scratch" "$repo")
    ec=$(scan_exit "$scratch" "$repo")
    assert_eq "zero-manifest: MANIFEST_COUNT 0, nothing else" "MANIFEST_COUNT: 0" "$out"
    assert_eq "zero-manifest: exit code 0" "0" "$ec"
    rm -rf "$repo" "$scratch"
}

# ================= 9: license_inventory=disabled (config toggle) =================
{
    repo=$(mktemp -d)
    mkdir -p "$repo/frontend/node_modules/mitpkg"
    printf '{"name":"frontend"}\n' > "$repo/frontend/package.json"
    : > "$repo/frontend/package-lock.json"
    printf '{"name": "mitpkg", "version": "1.0.0", "license": "GPL-3.0"}\n' > "$repo/frontend/node_modules/mitpkg/package.json"
    mkdir -p "$repo/.smith"
    printf '{"supply_chain": {"license_inventory": false, "license_policy": {"deny": ["GPL-3.0"]}}}\n' > "$repo/.smith/config.json"
    scratch=$(make_scratch)
    out=$(scan "$scratch" "$repo")
    assert_contains "license_inventory disabled: status is disabled" "$out" "license_inventory=disabled"
    assert_not_contains "license_inventory disabled: no findings emitted even with a deny hit present" "$out" "[High]"
    rm -rf "$repo" "$scratch"
}

# ---------- summary ----------
echo "----"
echo "SUMMARY: $PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
    echo "Failed: ${FAILED_NAMES[*]}"
fi

[ "$FAIL" -eq 0 ]
