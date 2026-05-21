#!/usr/bin/env bash
# Integration tests for scripts/parsers/parse-js.js.
#
# Invokes the parser as a subprocess against each fixture and asserts the
# JSON output. Uses python3 inline for JSON queries.
#
# Usage: bash tests/parsers/test_parse_js.sh
# Exits non-zero on any test failure.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
PARSER="$REPO/scripts/parsers/parse-js.js"
FIX="$HERE/fixtures/js"

PASS=0
FAIL=0
FAILED_TESTS=()

assert() {
  local label="$1"
  shift
  if "$@"; then
    PASS=$((PASS + 1))
    echo "PASS  $label"
  else
    FAIL=$((FAIL + 1))
    FAILED_TESTS+=("$label")
    echo "FAIL  $label"
  fi
}

parse() {
  node "$PARSER" "$1"
}

jget() {
  # jget '<json>' '<python expr>'
  python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(eval(sys.argv[2]))" "$1" "$2"
}

# --- esm_named.js ----------------------------------------------------------
OUT="$(parse "$FIX/esm_named.js")"
assert "esm_named: language=javascript" \
  test "$(jget "$OUT" "d['language']")" = "javascript"
assert "esm_named: no errors" \
  test "$(jget "$OUT" "len(d['errors'])")" = "0"
assert "esm_named: 4 exports (add, multiply, Greeter, helper)" \
  test "$(jget "$OUT" "len(d['exports'])")" = "4"
assert "esm_named: Greeter is a class" \
  test "$(jget "$OUT" "len([c for c in d['classes'] if c['name']=='Greeter'])")" = "1"

# --- default_export.js -----------------------------------------------------
OUT="$(parse "$FIX/default_export.js")"
assert "default_export: 1 default export" \
  test "$(jget "$OUT" "len([e for e in d['exports'] if e['kind']=='default'])")" = "1"

# --- react_component.jsx ---------------------------------------------------
OUT="$(parse "$FIX/react_component.jsx")"
assert "react_component: no errors" \
  test "$(jget "$OUT" "len(d['errors'])")" = "0"
assert "react_component: 3 react-component exports" \
  test "$(jget "$OUT" "len([e for e in d['exports'] if e['kind']=='react-component'])")" = "3"
assert "react_component: language is javascript (jsx)" \
  test "$(jget "$OUT" "d['language']")" = "javascript"

# --- imports_dedup.js ------------------------------------------------------
OUT="$(parse "$FIX/imports_dedup.js")"
assert "imports_dedup: 4 imports total (3 require + 1 dynamic)" \
  test "$(jget "$OUT" "len(d['imports'])")" = "4"
assert "imports_dedup: dynamic import detected" \
  test "$(jget "$OUT" "len([i for i in d['imports'] if i['kind']=='dynamic'])")" = "1"
assert "imports_dedup: require imports detected" \
  test "$(jget "$OUT" "len([i for i in d['imports'] if i['kind']=='require'])")" = "3"

# --- express_routes.js -----------------------------------------------------
OUT="$(parse "$FIX/express_routes.js")"
assert "express_routes: 4 routes" \
  test "$(jget "$OUT" "len(d['routes'])")" = "4"
assert "express_routes: GET / handled by rootHandler" \
  test "$(jget "$OUT" "[r['function'] for r in d['routes'] if r['method']=='GET' and r['path']=='/'][0]")" = "rootHandler"
assert "express_routes: framework=express on all routes" \
  test "$(jget "$OUT" "all(r['framework']=='express' for r in d['routes'])")" = "True"
assert "express_routes: PUT /users/:id handler is updateUser" \
  test "$(jget "$OUT" "[r['function'] for r in d['routes'] if r['method']=='PUT'][0]")" = "updateUser"

# --- ts_interface.ts -------------------------------------------------------
OUT="$(parse "$FIX/ts_interface.ts")"
assert "ts_interface: language=typescript" \
  test "$(jget "$OUT" "d['language']")" = "typescript"
assert "ts_interface: parses without crash" \
  test "$(jget "$OUT" "isinstance(d, dict)")" = "True"

# --- malformed.jsx — partial output, never crash ---------------------------
OUT="$(parse "$FIX/malformed.jsx")"
assert "malformed.jsx: errors populated" \
  test "$(jget "$OUT" "len(d['errors']) > 0")" = "True"
assert "malformed.jsx: still returns required schema fields" \
  test "$(jget "$OUT" "all(k in d for k in ['path','language','lines','functions','classes','imports','routes','exports','errors'])")" = "True"
assert "malformed.jsx: regex fallback finds 'react' import" \
  test "$(jget "$OUT" "len([i for i in d['imports'] if i['name']=='react']) >= 1")" = "True"

# --- tsx_component.tsx -----------------------------------------------------
OUT="$(parse "$FIX/tsx_component.tsx")"
assert "tsx_component: language=typescript" \
  test "$(jget "$OUT" "d['language']")" = "typescript"
assert "tsx_component: parses without crash (jsx + ts)" \
  test "$(jget "$OUT" "isinstance(d, dict)")" = "True"
assert "tsx_component: at least one react-component export" \
  test "$(jget "$OUT" "len([e for e in d['exports'] if e['kind']=='react-component']) >= 1")" = "True"

# --- Performance budget ----------------------------------------------------
START_NS=$(python3 -c 'import time; print(int(time.time()*1000))')
parse "$FIX/esm_named.js" >/dev/null
parse "$FIX/react_component.jsx" >/dev/null
parse "$FIX/ts_interface.ts" >/dev/null
END_NS=$(python3 -c 'import time; print(int(time.time()*1000))')
AVG=$(( (END_NS - START_NS) / 3 ))
assert "performance: avg < 500ms (was ${AVG}ms; hard fail at 500ms)" \
  test "$AVG" -lt 500

echo
echo "Total: $((PASS + FAIL))  Passed: $PASS  Failed: $FAIL"

if [ "$FAIL" -ne 0 ]; then
  echo
  echo "Failures:"
  for t in "${FAILED_TESTS[@]}"; do
    echo "  - $t"
  done
  exit 1
fi

exit 0
