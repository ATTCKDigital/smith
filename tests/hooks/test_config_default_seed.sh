#!/usr/bin/env bash
# Unit tests for session-start-logger.sh's .smith/config.json seeding step.
#
# Verifies:
#   - Fresh project (no config.json) → seeded from $HOME/.smith/templates/config.default.json
#   - Existing config.json → preserved verbatim (idempotent)
#   - Custom-modified config.json → not overwritten
#   - Missing template across all candidate paths → silent skip (no error)
#   - Fallback chain: $HOME/.smith/templates/ → $HOME/.claude/skills/smith/templates/ → $CLAUDE_PROJECT_DIR/templates/
#
# Run:
#   bash tests/hooks/test_config_default_seed.sh

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
HOOK="$REPO/hooks/session-start-logger.sh"
TEMPLATE_SRC="$REPO/templates/config.default.json"

PASS=0
FAIL=0
FAILED_NAMES=()

assert_eq() {
    local name="$1" expected="$2" actual="$3"
    if [ "$expected" = "$actual" ]; then
        PASS=$((PASS + 1))
        printf 'PASS  %s\n' "$name"
    else
        FAIL=$((FAIL + 1))
        FAILED_NAMES+=("$name")
        printf 'FAIL  %s\n  expected: %s\n  actual:   %s\n' "$name" "$expected" "$actual"
    fi
}

assert_file_exists() {
    local name="$1" file="$2"
    if [ -f "$file" ]; then
        PASS=$((PASS + 1))
        printf 'PASS  %s\n' "$name"
    else
        FAIL=$((FAIL + 1))
        FAILED_NAMES+=("$name")
        printf 'FAIL  %s\n  missing: %s\n' "$name" "$file"
    fi
}

assert_file_missing() {
    local name="$1" file="$2"
    if [ ! -f "$file" ]; then
        PASS=$((PASS + 1))
        printf 'PASS  %s\n' "$name"
    else
        FAIL=$((FAIL + 1))
        FAILED_NAMES+=("$name")
        printf 'FAIL  %s\n  unexpectedly present: %s\n' "$name" "$file"
    fi
}

assert_file_contains() {
    local name="$1" file="$2" needle="$3"
    if grep -qF "$needle" "$file" 2>/dev/null; then
        PASS=$((PASS + 1))
        printf 'PASS  %s\n' "$name"
    else
        FAIL=$((FAIL + 1))
        FAILED_NAMES+=("$name")
        printf 'FAIL  %s\n  needle missing: %s\n  in: %s\n' "$name" "$needle" "$file"
    fi
}

setup_project() {
    # Returns a fresh project root with a fake HOME so we don't clobber the
    # user's real ~/.smith/. Caller is responsible for cleaning up both.
    local project home
    project=$(mktemp -d)
    home=$(mktemp -d)
    mkdir -p "$project/.smith"
    printf '%s\n%s' "$project" "$home"
}

# Drive the hook with a minimal SessionStart payload.
invoke_hook() {
    local project="$1" home="$2" trigger="${3:-startup}"
    CLAUDE_PROJECT_DIR="$project" HOME="$home" \
        bash "$HOOK" >/dev/null 2>&1 <<EOF
{"trigger":"$trigger","session_id":"test-session-123"}
EOF
}

# ---------- 1: shipped template is valid JSON ----------
{
    if command -v python3 >/dev/null 2>&1; then
        if python3 -c "import json; json.load(open('$TEMPLATE_SRC'))" 2>/dev/null; then
            PASS=$((PASS + 1))
            printf 'PASS  shipped template parses as JSON\n'
        else
            FAIL=$((FAIL + 1))
            FAILED_NAMES+=("template parses as JSON")
            printf 'FAIL  shipped template parses as JSON\n  bad JSON in: %s\n' "$TEMPLATE_SRC"
        fi
    else
        PASS=$((PASS + 1))
        printf 'PASS  shipped template parses as JSON (skipped, no python3)\n'
    fi
}

# ---------- 2: shipped template has expected top-level keys ----------
{
    assert_file_contains "template has security section" "$TEMPLATE_SRC" '"security"'
    assert_file_contains "template has ledger section" "$TEMPLATE_SRC" '"ledger"'
    assert_file_contains "template has ledger.enabled" "$TEMPLATE_SRC" '"enabled"'
    assert_file_contains "template has reconcile section" "$TEMPLATE_SRC" '"reconcile"'
}

# ---------- 3: fresh project gets seeded from $HOME/.smith/templates/ ----------
{
    paths=$(setup_project)
    project=$(echo "$paths" | sed -n 1p)
    home=$(echo "$paths" | sed -n 2p)
    mkdir -p "$home/.smith/templates"
    cp "$TEMPLATE_SRC" "$home/.smith/templates/config.default.json"

    invoke_hook "$project" "$home" startup

    assert_file_exists "fresh project: config.json seeded" "$project/.smith/config.json"
    assert_file_contains "fresh project: contains ledger section" "$project/.smith/config.json" '"ledger"'

    # Byte-for-byte equal to the source.
    if cmp -s "$home/.smith/templates/config.default.json" "$project/.smith/config.json"; then
        PASS=$((PASS + 1))
        printf 'PASS  fresh project: byte-for-byte copy of template\n'
    else
        FAIL=$((FAIL + 1))
        FAILED_NAMES+=("byte-for-byte copy")
        printf 'FAIL  fresh project: byte-for-byte copy of template\n'
    fi

    rm -rf "$project" "$home"
}

# ---------- 4: existing config.json is NOT overwritten (idempotency) ----------
{
    paths=$(setup_project)
    project=$(echo "$paths" | sed -n 1p)
    home=$(echo "$paths" | sed -n 2p)
    mkdir -p "$home/.smith/templates"
    cp "$TEMPLATE_SRC" "$home/.smith/templates/config.default.json"

    # Pre-existing user-customized config.
    printf '%s\n' '{"custom":"user-edits","ledger":{"enabled":false}}' \
        > "$project/.smith/config.json"
    before=$(cat "$project/.smith/config.json")

    invoke_hook "$project" "$home" startup
    after=$(cat "$project/.smith/config.json")

    assert_eq "existing config preserved verbatim" "$before" "$after"
    assert_file_contains "existing config still has custom field" "$project/.smith/config.json" '"custom":"user-edits"'

    rm -rf "$project" "$home"
}

# ---------- 5: resume trigger also seeds when missing ----------
{
    paths=$(setup_project)
    project=$(echo "$paths" | sed -n 1p)
    home=$(echo "$paths" | sed -n 2p)
    mkdir -p "$home/.smith/templates"
    cp "$TEMPLATE_SRC" "$home/.smith/templates/config.default.json"

    # Resume trigger requires .current-session pointing at an existing log,
    # otherwise the resume branch no-ops. We don't care about session log
    # creation here, only about config seeding — which runs BEFORE the
    # trigger switch, so it should still fire.
    invoke_hook "$project" "$home" resume

    assert_file_exists "resume: config.json still seeded" "$project/.smith/config.json"
    rm -rf "$project" "$home"
}

# ---------- 6: no template anywhere → silent skip, no crash ----------
{
    paths=$(setup_project)
    project=$(echo "$paths" | sed -n 1p)
    home=$(echo "$paths" | sed -n 2p)
    # Deliberately no templates installed under $home.

    out=$(CLAUDE_PROJECT_DIR="$project" HOME="$home" \
        bash "$HOOK" 2>&1 <<'EOF'
{"trigger":"startup","session_id":"test-session-no-template"}
EOF
    )
    rc=$?

    assert_eq "no-template: hook exits 0" 0 "$rc"
    assert_file_missing "no-template: config.json not created" "$project/.smith/config.json"

    rm -rf "$project" "$home"
}

# ---------- 7: fallback to $HOME/.claude/skills/smith/templates/ ----------
{
    paths=$(setup_project)
    project=$(echo "$paths" | sed -n 1p)
    home=$(echo "$paths" | sed -n 2p)
    # No template at primary location.
    mkdir -p "$home/.claude/skills/smith/templates"
    cp "$TEMPLATE_SRC" "$home/.claude/skills/smith/templates/config.default.json"

    invoke_hook "$project" "$home" startup

    assert_file_exists "fallback path 2: config.json seeded" "$project/.smith/config.json"
    assert_file_contains "fallback path 2: has ledger section" "$project/.smith/config.json" '"ledger"'

    rm -rf "$project" "$home"
}

# ---------- 8: fallback to $CLAUDE_PROJECT_DIR/templates/ ----------
{
    paths=$(setup_project)
    project=$(echo "$paths" | sed -n 1p)
    home=$(echo "$paths" | sed -n 2p)
    # No template in $HOME locations; only in project tree.
    mkdir -p "$project/templates"
    cp "$TEMPLATE_SRC" "$project/templates/config.default.json"

    invoke_hook "$project" "$home" startup

    assert_file_exists "fallback path 3: config.json seeded" "$project/.smith/config.json"

    rm -rf "$project" "$home"
}

# ---------- summary ----------
echo
echo "----------------------------------------------------------------------"
echo "Ran $((PASS + FAIL)) tests: $PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
    printf 'Failed:\n'
    for n in "${FAILED_NAMES[@]}"; do
        printf '  - %s\n' "$n"
    done
    exit 1
fi
