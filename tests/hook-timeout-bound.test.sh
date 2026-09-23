#!/usr/bin/env bash
# hook-timeout-bound.test.sh — proves the two python3-delegating hooks really
# do bound their helper on a machine that has no `timeout` binary.
#
# The bug this file exists to catch:
#   hooks/context-loader.sh and hooks/manifest-updater.sh both did
#
#       TIMEOUT_BIN=""
#       if command -v timeout  ...; then TIMEOUT_BIN="timeout 5s"
#       elif command -v gtimeout ...; then TIMEOUT_BIN="gtimeout 5s"
#       fi
#       ... | $TIMEOUT_BIN python3 "$HELPER" ...
#
#   Stock macOS ships neither `timeout` nor `gtimeout`. `$TIMEOUT_BIN` expanded
#   to nothing and the helper ran completely unbounded, while the comments and
#   docs advertised 5s (context-loader) and 2s (manifest-updater). A hung helper
#   hung the hook — and context-loader.sh is a UserPromptSubmit hook, so that is
#   every single prompt.
#
# The test is behavioral, not structural: it hands each hook a helper that
# sleeps for ten minutes and asserts the hook comes back anyway. It deliberately
# does NOT grep the hook for a particular implementation — `timeout`, `gtimeout`
# and an in-process python3 bound are all acceptable answers, and the point is
# that at least one of them takes effect.
#
# Two guards keep this from passing for the wrong reason:
#   - the child runs with a PATH that provably contains neither `timeout` nor
#     `gtimeout` (CI runs on Linux, where both exist and would mask the bug);
#   - the elapsed time must be ABOVE a floor as well as below the ceiling, so a
#     hook that bails early (no helper found, no python3 on PATH) fails instead
#     of looking instantaneous and therefore "bounded".
#
# Run: bash tests/hook-timeout-bound.test.sh
# CI:  .github/workflows/test-install.yml globs tests/*.test.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"

PASS=0
FAIL=0
assert() {
    local ok="$1" msg="$2"
    if [ "$ok" = "0" ]; then
        printf '  ok   %s\n' "$msg"
        PASS=$((PASS + 1))
    else
        printf '  FAIL %s\n' "$msg"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== tests/hook-timeout-bound.test.sh ==="

BASH_BIN="$(command -v bash)"
PYTHON_BIN="$(command -v python3 || true)"
if [ -z "$PYTHON_BIN" ]; then
    echo "FATAL: python3 is required to run this test (and by both hooks)"
    exit 1
fi

SANDBOX="$(mktemp -d "${TMPDIR:-/tmp}/smith-hook-timeout.XXXXXX")"
trap 'rm -rf "$SANDBOX"' EXIT INT TERM

SAFE_BIN="$SANDBOX/bin"
SAFE_HOME="$SANDBOX/home"
mkdir -p "$SAFE_BIN" "$SAFE_HOME"

# ---------------------------------------------------------------------------
# A PATH with everything the hooks legitimately use and nothing that can time
# a process out for them. Symlinks, not copies, so the real binaries run.
# `timeout` and `gtimeout` are conspicuously absent — that is the whole point.
# ---------------------------------------------------------------------------
for tool in env bash sh cat date mkdir dirname basename grep head sed tr cut \
            awk mktemp rm ls find wc sort uname sleep python3 tee cp chmod stat; do
    src="$(command -v "$tool" 2>/dev/null || true)"
    [ -n "$src" ] && ln -sf "$src" "$SAFE_BIN/$tool"
done

# ---------------------------------------------------------------------------
# run_hook <hook-path> <stdin-payload> <cwd> <hard-cap-seconds>
#   echoes: "<rc> <killed> <elapsed>"
#
# The hard cap is the TEST's watchdog, not the hook's. It exists so the RED
# case (an unbounded hook) takes `cap` seconds instead of forever. The child
# gets its own session so a hung grandchild helper dies with it.
# ---------------------------------------------------------------------------
run_hook() {
    "$PYTHON_BIN" - "$BASH_BIN" "$1" "$2" "$3" "$SAFE_HOME" "$SAFE_BIN" "$4" <<'PY'
import os, signal, subprocess, sys, time

bash, hook, payload, cwd, home, path, cap = sys.argv[1:8]
cap = float(cap)
env = {"HOME": home, "PATH": path, "LANG": "C", "LC_ALL": "C"}

t0 = time.monotonic()
p = subprocess.Popen(
    [bash, hook],
    stdin=subprocess.PIPE,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    cwd=cwd,
    env=env,
    start_new_session=True,
)
killed = 0
try:
    p.communicate(payload.encode(), timeout=cap)
    rc = p.returncode
except subprocess.TimeoutExpired:
    killed = 1
    rc = 999
    try:
        os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass
    try:
        p.communicate(timeout=5)
    except Exception:
        pass
elapsed = time.monotonic() - t0
print("%d %d %.2f" % (rc, killed, elapsed))
PY
}

# ---------------------------------------------------------------------------
# Guard 0 — the sanitized PATH is actually sanitized, and still has python3.
#
# Without this, a green result on Linux CI would mean "the real `timeout` did
# its job", and on any box missing python3 it would mean "the hook bailed at
# the no-python3 check in 40ms". Neither is the thing under test.
# ---------------------------------------------------------------------------
LEAKED=$(env -i HOME="$SAFE_HOME" PATH="$SAFE_BIN" "$BASH_BIN" -c \
    'command -v timeout; command -v gtimeout' 2>/dev/null || true)
if [ -z "$LEAKED" ]; then
    assert 0 "sandbox PATH exposes neither timeout nor gtimeout"
else
    assert 1 "sandbox PATH exposes neither timeout nor gtimeout"
    printf '       leaked: %s\n' "$LEAKED"
fi

SEEN_PY=$(env -i HOME="$SAFE_HOME" PATH="$SAFE_BIN" "$BASH_BIN" -c \
    'command -v python3' 2>/dev/null || true)
if [ -n "$SEEN_PY" ]; then
    assert 0 "sandbox PATH still exposes python3 (hooks must reach the helper)"
else
    assert 1 "sandbox PATH still exposes python3 (hooks must reach the helper)"
fi

# ---------------------------------------------------------------------------
# check_bounded <label> <hook-basename> <helper-basename> <payload>
#                <ceiling> <floor> <hard-cap> [extra-setup-fn]
# ---------------------------------------------------------------------------
HANGING_HELPER='import time
# Never returns on its own. The hook is the only thing that can stop this.
time.sleep(600)
'

check_bounded() {
    local label="$1" hook_name="$2" helper_name="$3" payload="$4"
    local ceiling="$5" floor="$6" cap="$7" prep="${8:-}"

    local work="$SANDBOX/$label"
    mkdir -p "$work"
    cp "$REPO_ROOT/hooks/$hook_name" "$work/$hook_name"
    printf '%s' "$HANGING_HELPER" > "$work/$helper_name"
    [ -n "$prep" ] && "$prep" "$work"

    local out rc killed elapsed
    out="$(run_hook "$work/$hook_name" "$payload" "$work" "$cap")"
    read -r rc killed elapsed <<EOF
$out
EOF

    echo "  ($label: rc=$rc killed=$killed elapsed=${elapsed}s; helper sleeps 600s)"

    if [ "$killed" = "0" ]; then
        assert 0 "$label returned on its own — the harness never had to kill it"
    else
        assert 1 "$label returned on its own — the harness never had to kill it"
        echo "       UNBOUNDED: still running after ${cap}s with no timeout(1) on PATH"
    fi

    if [ "$rc" = "0" ]; then
        assert 0 "$label fails open (exit 0) when the helper times out"
    else
        assert 1 "$label fails open (exit 0) when the helper times out (got rc=$rc)"
    fi

    if awk "BEGIN{exit !($elapsed < $ceiling)}"; then
        assert 0 "$label finished in ${elapsed}s (< ${ceiling}s ceiling)"
    else
        assert 1 "$label finished in ${elapsed}s (< ${ceiling}s ceiling)"
    fi

    if awk "BEGIN{exit !($elapsed > $floor)}"; then
        assert 0 "$label actually ran the helper (${elapsed}s > ${floor}s floor)"
    else
        assert 1 "$label actually ran the helper (${elapsed}s > ${floor}s floor)"
        echo "       returned too fast — it probably bailed before reaching the helper"
    fi
}

# manifest-updater.sh needs a real, allowlisted, non-excluded file to work on.
seed_sample_py() {
    printf 'def f():\n    return 1\n' > "$1/sample.py"
}

# --- context-loader.sh: advertises <5s, fires on every UserPromptSubmit ----
check_bounded "context-loader" "context-loader.sh" "context-loader-lib.py" \
    '{"prompt":"/smith-new bounded helper probe","cwd":"/tmp"}' \
    9 0.8 12

# --- manifest-updater.sh: advertises 2s, fires on every Write/Edit ---------
MU_WORK="$SANDBOX/manifest-updater"
check_bounded "manifest-updater" "manifest-updater.sh" "manifest-updater-lib.py" \
    "{\"tool_input\":{\"file_path\":\"$MU_WORK/sample.py\"},\"cwd\":\"$MU_WORK\"}" \
    6 0.8 12 seed_sample_py

echo
echo "  passed: $PASS   failed: $FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
