#!/usr/bin/env bash
# activity-pricing.test.sh — FR-62 / SC-17.
#
# `hooks/pricing.json` has never been installed by scripts/install.sh: the
# copy loops glob `hooks/*.sh` and `hooks/*.py` and nothing else. Combined with
# the newest shipped family being claude-opus-4-6*, `match_family()` returned
# None for every live session, `cost_usd()` returned None, and the Stop-hook
# workflow summary silently omitted its USD line. Nothing errored. That is the
# shape of every failure this file guards against — a plausible output, not a
# crash — so each assertion targets a specific way the table can be wrong while
# still looking right:
#
#   1. the installer copies hooks/*.json at all;
#   2. after a real install into a clean CLAUDE_HOME, pricing.json is there;
#   3. the running model resolves through load_pricing() + match_family();
#   4. a specific family is never swallowed by a wildcard that precedes it;
#   5. EVERY family carries last_verified, and no numeric rate lacks one.
#
# (4) and (5) are the executable form of "rates are never invented". A
# fabricated rate is indistinguishable from a real one at runtime, so the
# guard sits on the metadata and on the ordering rather than on the number.
#
# CI runs flat tests/*.test.sh only (.github/workflows/test-install.yml:58),
# which is why this is a top-level file and not a subdirectory test.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
PASS=0
FAIL=0

assert() {
    if [ "$2" = "true" ]; then
        echo "PASS $1"; PASS=$((PASS+1))
    else
        echo "FAIL $1"; FAIL=$((FAIL+1))
    fi
}

TMP=$(mktemp -d -t activity-pricing.XXXXXX)
trap 'rm -rf "$TMP"' EXIT

PRICING="$REPO_ROOT/hooks/pricing.json"

# --- Test 1: the installer globs hooks/*.json ------------------------------
# A glob, not a `cp hooks/pricing.json`: the two loops beside it are already
# two stale enumerations, and this file is the proof of what a third costs.
if grep -qE '"\$REPO_ROOT"/hooks/\*\.json' "$REPO_ROOT/scripts/install.sh"; then
    assert "install.sh copies hooks/*.json (a glob, not a single cp)" true
else
    assert "install.sh copies hooks/*.json (a glob, not a single cp)" false
fi

# The preview string beside it was hardcoded at "9 hooks" while the repo
# shipped 19 (FR-63). It must now be derived.
if grep -q 'Copy 9 hooks' "$REPO_ROOT/scripts/install.sh"; then
    assert "install.sh no longer hardcodes a stale hook count" false
else
    assert "install.sh no longer hardcodes a stale hook count" true
fi

# --- Test 2: a real install into a clean CLAUDE_HOME -----------------------
export HOME="$TMP/home"
export CLAUDE_HOME="$TMP/home/.claude"
export SMITH_HOME="$TMP/home/.smith"
export SMITH_ASSUME_YES=1
export SMITH_SKIP_SCHEDULER=1
mkdir -p "$HOME"

INSTALLED_HOOKS="$CLAUDE_HOME/hooks"
[ -e "$INSTALLED_HOOKS/pricing.json" ] \
    && assert "CLAUDE_HOOKS_DIR starts clean" false \
    || assert "CLAUDE_HOOKS_DIR starts clean" true

bash "$REPO_ROOT/scripts/install.sh" -y --no-parsers > "$TMP/install.out" 2>&1
INSTALL_RC=$?
if [ "$INSTALL_RC" -eq 0 ]; then
    assert "scripts/install.sh completed" true
else
    assert "scripts/install.sh completed (rc=$INSTALL_RC)" false
    tail -25 "$TMP/install.out"
fi

[ -f "$INSTALLED_HOOKS/pricing.json" ] \
    && assert "hooks/pricing.json is present in the install location" true \
    || assert "hooks/pricing.json is present in the install location" false

# The lib that reads it must land beside it, or load_pricing() has nothing to
# be called from.
[ -f "$INSTALLED_HOOKS/workflow_summary_lib.py" ] \
    && assert "workflow_summary_lib.py installed beside pricing.json" true \
    || assert "workflow_summary_lib.py installed beside pricing.json" false

# --- Tests 3-5: the INSTALLED table, read the only supported way -----------
# Deliberately against the installed copy rather than the repo copy: the
# defect FR-62 fixes was entirely about the two being different.
PY_OUT="$TMP/pricing.out"
PYTHONPATH="$INSTALLED_HOOKS" python3 - "$INSTALLED_HOOKS/pricing.json" \
        > "$PY_OUT" 2>&1 <<'PY'
import json
import sys

import workflow_summary_lib as W

path = sys.argv[1]
ok = True


def check(label, condition):
    global ok
    print("%s %s" % ("ok" if condition else "NOT-OK", label))
    if not condition:
        ok = False


# The ONLY supported door. match_family() reads a _compiled_patterns key that
# only load_pricing() injects, via `.get(...) or []`, so a raw json.load
# resolves every model to None with no exception and no log line.
table = W.load_pricing(path)
check("load_pricing() returns a table", table is not None)
if table is None:
    sys.exit(1)

check("the running model resolves to a non-None entry",
      W.match_family("claude-opus-5", table) is not None)
check("the [1m] context-window suffix resolves too",
      W.match_family("claude-opus-5[1m]", table) is not None)
check("a dated suffix resolves too",
      W.match_family("claude-opus-5-20260601", table) is not None)

# The trap, asserted from the other side: a raw parse of the SAME file.
with open(path, "r", encoding="utf-8") as fh:
    raw = json.load(fh)
check("a raw json.load of the same file resolves to None (FR-33 trap)",
      W.match_family("claude-opus-5", raw) is None)

# Ordering. match_family() returns the FIRST array-order match and every
# pattern is a prefix glob, so a wildcard placed above a specific family
# silently reprices it — Opus 5.5 at Opus 5's rate, 25% high, with nothing to
# see at runtime.
families = [m["family"] for m in table["models"]]
stems = [(f, f[:-1] if f.endswith("*") else f) for f in families]
pairs = 0
ordered = True
for i, (family, stem) in enumerate(stems):
    for j, (other, other_stem) in enumerate(stems):
        if i == j or not other_stem.startswith(stem):
            continue
        pairs += 1
        if j > i:
            ordered = False
            print("   %s must precede %s" % (other, family))
check("every specific family precedes the wildcard that would match it", ordered)
check("the ordering assertion was not vacuous", pairs > 0)

five_five = W.match_family("claude-opus-5-5", table)
five = W.match_family("claude-opus-5", table)
check("claude-opus-5-5 is not swallowed by claude-opus-5*",
      five_five is not None and five is not None
      and five_five["input_per_mtok"] != five["input_per_mtok"])

# Provenance. A fabricated rate looks exactly like a real one, so the guard
# sits on the metadata: no family without last_verified, and no numeric rate
# without one.
RATE_KEYS = ("input_per_mtok", "output_per_mtok",
             "cache_write_5m_per_mtok", "cache_read_per_mtok")
missing = [e.get("family") for e in raw["models"] if not e.get("last_verified")]
check("every family carries last_verified (missing: %s)" % (missing or "none"),
      not missing)

unsourced = []
for entry in raw["models"]:
    numeric = [k for k in RATE_KEYS if isinstance(entry.get(k), (int, float))]
    if numeric and not entry.get("last_verified"):
        unsourced.append(entry.get("family"))
check("no family carries a numeric rate without last_verified (%s)"
      % (unsourced or "none"), not unsourced)

check("every family carries a source_url",
      all(e.get("source_url") for e in raw["models"]))

sys.exit(0 if ok else 1)
PY
if [ $? -eq 0 ]; then
    assert "installed pricing table: resolution, ordering and provenance" true
else
    assert "installed pricing table: resolution, ordering and provenance" false
    sed -n '1,40p' "$PY_OUT"
fi

# --- Test 6: the repo copy and the installed copy agree --------------------
if cmp -s "$PRICING" "$INSTALLED_HOOKS/pricing.json"; then
    assert "installed pricing.json is byte-identical to the repo copy" true
else
    assert "installed pricing.json is byte-identical to the repo copy" false
fi

echo
echo "activity-pricing tests: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
