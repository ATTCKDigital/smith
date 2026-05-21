#!/usr/bin/env bash
# test_git_hooks.sh — covers the post-merge and post-checkout templates and
# the install-git-hooks.sh installer.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
INSTALLER="$REPO_ROOT/scripts/install-git-hooks.sh"
PASS=0
FAIL=0

assert() {
    if [ "$2" = "true" ]; then
        echo "PASS $1"
        PASS=$((PASS+1))
    else
        echo "FAIL $1"
        FAIL=$((FAIL+1))
    fi
}

# --- Test 1: install copies hooks into .git/hooks/ ----------------------
TMP=$(mktemp -d -t gh.XXXXXX)
trap 'rm -rf "$TMP"' EXIT
(cd "$TMP" && git init -q)
bash "$INSTALLER" --root "$TMP" >/dev/null 2>&1
[ -x "$TMP/.git/hooks/post-merge" ] && assert "post-merge installed and exec" true \
    || assert "post-merge installed and exec" false
[ -x "$TMP/.git/hooks/post-checkout" ] && assert "post-checkout installed and exec" true \
    || assert "post-checkout installed and exec" false

# --- Test 2: post-merge exits silently when .smith/index/ absent --------
RC=0
"$TMP/.git/hooks/post-merge" >/dev/null 2>&1 || RC=$?
[ "$RC" -eq 0 ] && assert "post-merge silent no-op without .smith/index" true \
    || assert "post-merge silent no-op without .smith/index (rc=$RC)" false

# --- Test 3: post-checkout silent no-op with $3=0 (file checkout) -------
RC=0
"$TMP/.git/hooks/post-checkout" abc123 def456 0 >/dev/null 2>&1 || RC=$?
[ "$RC" -eq 0 ] && assert "post-checkout file-checkout silent" true \
    || assert "post-checkout file-checkout silent (rc=$RC)" false

# --- Test 4: existing custom hook is not overwritten -------------------
mkdir -p "$TMP/.git/hooks"
cat > "$TMP/.git/hooks/post-merge" <<'EOF'
#!/usr/bin/env bash
echo "custom user hook"
EOF
chmod +x "$TMP/.git/hooks/post-merge"
bash "$INSTALLER" --root "$TMP" >/dev/null 2>&1
if grep -q "custom user hook" "$TMP/.git/hooks/post-merge"; then
    assert "custom hook not overwritten" true
else
    assert "custom hook not overwritten" false
fi
[ -f "$TMP/.git/hooks/post-merge.smith" ] && assert "Smith hook written as .smith fallback" true \
    || assert "Smith hook written as .smith fallback" false

# --- Test 5: --uninstall removes Smith hooks ----------------------------
# First force a clean install.
rm -f "$TMP/.git/hooks/post-merge" "$TMP/.git/hooks/post-merge.smith"
bash "$INSTALLER" --root "$TMP" >/dev/null 2>&1
bash "$INSTALLER" --root "$TMP" --uninstall >/dev/null 2>&1
[ ! -f "$TMP/.git/hooks/post-merge" ] && assert "uninstall removes post-merge" true \
    || assert "uninstall removes post-merge" false

echo
echo "git hooks tests: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
