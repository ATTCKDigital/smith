#!/usr/bin/env bash
# Stable method id tests for scripts/parsers/parse-js.js (v2).
#
# Mirrors tests/parsers/test_stable_id_python.py against the JS parser.
# Uses python3 inline for JSON queries.
#
# Usage: bash tests/parsers/test_stable_id_js.sh
# Exits non-zero on any test failure.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
PARSER="$REPO/scripts/parsers/parse-js.js"

PASS=0
FAIL=0
FAILED_TESTS=()

TMP="$(mktemp -d -t smith-stable-id-js-XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

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

write_src() {
  # write_src <rel> <heredoc-content via stdin>
  local rel="$1"
  local full="$TMP/$rel"
  mkdir -p "$(dirname "$full")"
  cat > "$full"
}

parse_rel() {
  # parse_rel <rel> — runs parser with cwd=TMP so module_path normalizes properly
  ( cd "$TMP" && node "$PARSER" "$1" )
}

jget() {
  python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(eval(sys.argv[2]))" "$1" "$2"
}

# --- 1. ID shape ----------------------------------------------------------
write_src "a.js" <<'EOF'
function alpha(x) { return x + 1; }
class C {
  m(y) { return y; }
}
EOF
OUT="$(parse_rel "a.js")"
assert "id shape: function alpha is 16-char hex" \
  test "$(jget "$OUT" "1 if (len([f for f in d['functions'] if f['name']=='alpha' and len(f.get('id','')) == 16 and all(c in '0123456789abcdef' for c in f['id'])]) == 1) else 0")" = "1"
assert "id shape: class C method m is 16-char hex" \
  test "$(jget "$OUT" "1 if (len([m for c in d['classes'] if c['name']=='C' for m in c['methods'] if m['name']=='m' and len(m.get('id','')) == 16]) == 1) else 0")" = "1"

# --- 2. Body edit preserves id -------------------------------------------
write_src "b.js" <<'EOF'
function deliver(url, payload) { return true; }
EOF
ID1="$(parse_rel "b.js" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(next(f['id'] for f in d['functions'] if f['name']=='deliver'))")"

write_src "b.js" <<'EOF'
function deliver(url, payload) {
  // body completely changed
  const x = 1;
  const y = 2;
  return false;
}
EOF
ID2="$(parse_rel "b.js" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(next(f['id'] for f in d['functions'] if f['name']=='deliver'))")"
assert "body edit preserves id" test "$ID1" = "$ID2"

# --- 3. Rename changes id -------------------------------------------------
write_src "b.js" <<'EOF'
function dispatch(url, payload) { return true; }
EOF
ID3="$(parse_rel "b.js" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(next(f['id'] for f in d['functions'] if f['name']=='dispatch'))")"
assert "rename changes id" test "$ID1" != "$ID3"

# --- 4. Reorder preserves id ---------------------------------------------
write_src "c.js" <<'EOF'
function aaa(x) { return x; }
function bbb(y) { return y; }
EOF
IDA1="$(parse_rel "c.js" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(next(f['id'] for f in d['functions'] if f['name']=='aaa'))")"
write_src "c.js" <<'EOF'
function bbb(y) { return y; }
function aaa(x) { return x; }
EOF
IDA2="$(parse_rel "c.js" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(next(f['id'] for f in d['functions'] if f['name']=='aaa'))")"
assert "reorder preserves id" test "$IDA1" = "$IDA2"

# --- 5. Param add changes id ---------------------------------------------
write_src "p.js" <<'EOF'
function f(x) { return x; }
EOF
P1="$(parse_rel "p.js" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(next(f['id'] for f in d['functions'] if f['name']=='f'))")"
write_src "p.js" <<'EOF'
function f(x, y) { return x; }
EOF
P2="$(parse_rel "p.js" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(next(f['id'] for f in d['functions'] if f['name']=='f'))")"
assert "param add changes id" test "$P1" != "$P2"

# --- 6. Param remove changes id ------------------------------------------
write_src "p.js" <<'EOF'
function f(x) { return x; }
EOF
P3="$(parse_rel "p.js" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(next(f['id'] for f in d['functions'] if f['name']=='f'))")"
assert "param remove changes id" test "$P3" = "$P1"
assert "remove distinct from added" test "$P3" != "$P2"

# --- 7. TS return-type change changes id ---------------------------------
write_src "r.ts" <<'EOF'
function f(x: number): number { return x; }
EOF
R1="$(parse_rel "r.ts" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(next(f['id'] for f in d['functions'] if f['name']=='f'))")"
write_src "r.ts" <<'EOF'
function f(x: number): string { return String(x); }
EOF
R2="$(parse_rel "r.ts" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(next(f['id'] for f in d['functions'] if f['name']=='f'))")"
assert "ts return-type change changes id" test "$R1" != "$R2"

# --- 8. File move changes id ---------------------------------------------
write_src "x/f.js" <<'EOF'
function f(x) { return x; }
EOF
X1="$(parse_rel "x/f.js" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(next(f['id'] for f in d['functions'] if f['name']=='f'))")"
write_src "y/f.js" <<'EOF'
function f(x) { return x; }
EOF
X2="$(parse_rel "y/f.js" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(next(f['id'] for f in d['functions'] if f['name']=='f'))")"
assert "file move changes id" test "$X1" != "$X2"

# --- 9. Same-name distinct files have distinct ids -----------------------
write_src "a/one.js" <<'EOF'
function shared(x) { return x; }
EOF
write_src "b/two.js" <<'EOF'
function shared(x) { return x; }
EOF
S1="$(parse_rel "a/one.js" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(next(f['id'] for f in d['functions'] if f['name']=='shared'))")"
S2="$(parse_rel "b/two.js" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(next(f['id'] for f in d['functions'] if f['name']=='shared'))")"
assert "same-name distinct files distinct ids" test "$S1" != "$S2"

# --- 10. Class method scope_chain distinguishes same-named methods -------
write_src "cls.js" <<'EOF'
class A { m(x) { return x; } }
class B { m(x) { return x; } }
EOF
AM="$(parse_rel "cls.js" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(next(m['id'] for c in d['classes'] if c['name']=='A' for m in c['methods'] if m['name']=='m'))")"
BM="$(parse_rel "cls.js" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(next(m['id'] for c in d['classes'] if c['name']=='B' for m in c['methods'] if m['name']=='m'))")"
assert "class method scope_chain reflects class name" test "$AM" != "$BM"

# --- 11. Exported function gets id ---------------------------------------
write_src "e.js" <<'EOF'
export function exported(x) { return x; }
export const arrow = (y) => y;
export default function def(z) { return z; }
EOF
OUT="$(parse_rel "e.js")"
assert "exported named function has id" \
  test "$(jget "$OUT" "1 if any(f['name']=='exported' and len(f.get('id','')) == 16 for f in d['functions']) else 0")" = "1"
assert "exported arrow gets id" \
  test "$(jget "$OUT" "1 if any(f['name']=='arrow' and len(f.get('id','')) == 16 for f in d['functions']) else 0")" = "1"
assert "default-exported named function has id" \
  test "$(jget "$OUT" "1 if any(f['name']=='def' and len(f.get('id','')) == 16 for f in d['functions']) else 0")" = "1"

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
