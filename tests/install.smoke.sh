#!/usr/bin/env bash
# Smoke test for install.sh — runs in a fake $HOME to verify the installer
# copies skills, hooks, and merges settings correctly.
#
# Usage: bash tests/install.smoke.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

FAKE_HOME="$(mktemp -d -t smith-smoke.XXXXXX)"
trap 'rm -rf "$FAKE_HOME"' EXIT

export HOME="$FAKE_HOME"
export SMITH_ASSUME_YES=1
export SMITH_SKIP_SCHEDULER=1

echo "=== Running install ==="
bash "$REPO_ROOT/scripts/install.sh" -y

echo
echo "=== Verifying skills ==="
SKILL_COUNT=$(ls -d "$FAKE_HOME/.claude/skills/smith"* 2>/dev/null | wc -l | tr -d ' ')
echo "Skills installed: $SKILL_COUNT"
[ "$SKILL_COUNT" -ge 25 ] || { echo "FAIL: Expected >= 25 skills, got $SKILL_COUNT"; exit 1; }

echo
echo "=== Verifying hooks ==="
HOOK_COUNT=$(ls "$FAKE_HOME/.claude/hooks/"*.sh 2>/dev/null | wc -l | tr -d ' ')
echo "Hooks installed: $HOOK_COUNT"
[ "$HOOK_COUNT" -ge 9 ] || { echo "FAIL: Expected >= 9 hooks, got $HOOK_COUNT"; exit 1; }
[ -x "$FAKE_HOME/.claude/hooks/grade-response.sh" ] || { echo "FAIL: grade-response.sh not installed or not executable"; exit 1; }

echo
echo "=== Verifying global CLAUDE.md rubric ==="
[ -f "$FAKE_HOME/.claude/CLAUDE.md" ] || { echo "FAIL: ~/.claude/CLAUDE.md not installed"; exit 1; }
grep -q "Rule Enforcement System" "$FAKE_HOME/.claude/CLAUDE.md" || { echo "FAIL: CLAUDE.md missing rubric content"; exit 1; }
echo "CLAUDE.md rubric installed"

echo
echo "=== Verifying settings merge ==="
if ! jq '.hooks' "$FAKE_HOME/.claude/settings.json" | grep -q "SessionStart"; then
    echo "FAIL: SessionStart hook not found in settings.json"
    exit 1
fi
if ! jq '.hooks' "$FAKE_HOME/.claude/settings.json" | grep -q "PreToolUse"; then
    echo "FAIL: PreToolUse hook not found in settings.json"
    exit 1
fi
if ! jq '.hooks.Stop' "$FAKE_HOME/.claude/settings.json" | grep -q "grade-response.sh"; then
    echo "FAIL: grade-response Stop hook not registered in settings.json"
    exit 1
fi
echo "Settings merged correctly"

echo
echo "=== Verifying scheduler ==="
[ -f "$FAKE_HOME/.smith/scheduler/smith-scheduler.sh" ] || { echo "FAIL: scheduler script not installed"; exit 1; }
[ -x "$FAKE_HOME/.smith/scheduler/smith-scheduler.sh" ] || { echo "FAIL: scheduler script not executable"; exit 1; }
echo "Scheduler installed"

echo
echo "=== Running uninstall ==="
bash "$REPO_ROOT/scripts/uninstall.sh" -y

echo
echo "=== Verifying cleanup ==="
REMAINING=$(ls -d "$FAKE_HOME/.claude/skills/smith"* 2>/dev/null | wc -l | tr -d ' ' || true)
REMAINING="${REMAINING:-0}"
[ "$REMAINING" -eq 0 ] || { echo "FAIL: $REMAINING skills remain after uninstall"; exit 1; }
echo "Uninstall clean"

echo
echo "=== All smoke tests passed ==="
