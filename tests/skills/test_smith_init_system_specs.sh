#!/usr/bin/env bash
# test_smith_init_system_specs.sh — contract test for /smith init Phase 4.8
# scaffolding of system spec files.
#
# /smith init is a conversational skill. Claude runs the prompts and writes
# the file in production. Here we don't spawn Claude; we exercise the
# template-substitution mechanics that step 4 of Phase 4.8 prescribes and
# verify:
#   (a) the produced .specify/systems/<id>/spec.md has YAML frontmatter that
#       conforms to scripts/parsers/contracts/system-spec-frontmatter.schema.json
#   (b) path-resolver tier 1 reads the produced spec correctly
#   (c) glob characters in paths are rejected
#   (d) empty paths list produces `paths: []` on a single line
#
# Exit 0 on success, 1 on failure.

set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TEMPLATE="${REPO_ROOT}/skills/smith/templates/system-spec-template.md"
SCHEMA="${REPO_ROOT}/scripts/parsers/contracts/system-spec-frontmatter.schema.json"
RESOLVER="${REPO_ROOT}/scripts/parsers/path-resolver.py"

TMPDIR_TEST="$(mktemp -d -t smith-init-spec-XXXXXX)"
trap 'rm -rf "$TMPDIR_TEST"' EXIT

fail=0
say() { printf '  %s\n' "$1"; }
ok() { printf '  ✓ %s\n' "$1"; }
err() { printf '  ✗ %s\n' "$1" >&2; fail=1; }

[[ -f "$TEMPLATE" ]] || { err "template missing: $TEMPLATE"; exit 1; }
[[ -f "$SCHEMA" ]] || { err "schema missing: $SCHEMA"; exit 1; }
[[ -f "$RESOLVER" ]] || { err "resolver missing: $RESOLVER"; exit 1; }

# Python helper that emulates Phase 4.8 step 4 substitution.
PY=$(cat <<'PYEOF'
import json, os, re, sys, pathlib

template_path = sys.argv[1]
out_path = sys.argv[2]
system_id = sys.argv[3]
paths_csv = sys.argv[4]  # comma-separated, blank = empty list

paths = [p for p in paths_csv.split(",") if p]

# Reject globs and auto-append trailing slash (Phase 4.8 step 3 invariants).
GLOB = set("*?[]{}!")
for p in paths:
    if any(c in GLOB for c in p):
        sys.stderr.write(f"Glob characters not allowed: {p!r}\n")
        sys.exit(2)
paths = [(p if p.endswith("/") else p + "/") for p in paths]

text = pathlib.Path(template_path).read_text(encoding="utf-8")

# Substitute system id.
text = text.replace("system-<NN>-<short-kebab-name>", system_id, 1)

# Substitute paths block. Template has:
#   paths:
#     - <relative-prefix>/
# We need to either expand to multiple `  - <p>` lines or replace with `paths: []`.
if paths:
    lines = "\n".join(f"  - {p}" for p in paths)
    text = text.replace(
        "paths:\n  - <relative-prefix>/",
        f"paths:\n{lines}",
        1,
    )
else:
    text = text.replace(
        "paths:\n  - <relative-prefix>/",
        "paths: []",
        1,
    )

os.makedirs(os.path.dirname(out_path), exist_ok=True)
pathlib.Path(out_path).write_text(text, encoding="utf-8")
print(out_path)
PYEOF
)

# --- Test 1: Scaffold two systems and verify frontmatter conforms to schema ---
say "=== Test 1: scaffold two systems ==="
PROJ="$TMPDIR_TEST/proj"
mkdir -p "$PROJ/.specify/systems"

# System 1: system-01-auth with two paths
python3 -c "$PY" "$TEMPLATE" \
  "$PROJ/.specify/systems/system-01-auth/spec.md" \
  "system-01-auth" \
  "services/auth,backend/api/auth/" \
  >/dev/null || { err "system-01 substitution failed"; exit 1; }

# System 2: system-02-billing with one path
python3 -c "$PY" "$TEMPLATE" \
  "$PROJ/.specify/systems/system-02-billing/spec.md" \
  "system-02-billing" \
  "services/billing/" \
  >/dev/null || { err "system-02 substitution failed"; exit 1; }

[[ -f "$PROJ/.specify/systems/system-01-auth/spec.md" ]] && ok "system-01 spec written" || err "system-01 spec missing"
[[ -f "$PROJ/.specify/systems/system-02-billing/spec.md" ]] && ok "system-02 spec written" || err "system-02 spec missing"

# Validate frontmatter against schema using stdlib pattern checks.
VALIDATE_PY=$(cat <<'PYEOF'
import json, re, sys, pathlib

schema_path = sys.argv[1]
spec_paths = sys.argv[2:]

schema = json.loads(pathlib.Path(schema_path).read_text(encoding="utf-8"))
sys_pat = re.compile(schema["properties"]["system"]["pattern"])
path_pat = re.compile(schema["properties"]["paths"]["items"]["pattern"])
status_enum = set(schema["properties"]["status"]["enum"])

def parse_fm(text):
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end == -1:
        return None
    body = text[4:end]
    out = {}
    current_list_key = None
    current_list = []
    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            current_list_key = None
            continue
        if line.startswith("  - ") and current_list_key:
            current_list.append(line[4:].strip().strip('"').strip("'"))
            out[current_list_key] = current_list
            continue
        if ":" in line and not line.startswith(" "):
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if val == "":
                current_list_key = key
                current_list = []
                out[key] = current_list
            elif val == "[]":
                current_list_key = None
                out[key] = []
            else:
                current_list_key = None
                out[key] = val.strip('"').strip("'")
    return out

failures = 0
for spec_path in spec_paths:
    text = pathlib.Path(spec_path).read_text(encoding="utf-8")
    fm = parse_fm(text)
    if fm is None:
        print(f"FAIL {spec_path}: no frontmatter", file=sys.stderr)
        failures += 1
        continue
    if "system" not in fm:
        print(f"FAIL {spec_path}: missing required `system` field", file=sys.stderr)
        failures += 1
        continue
    if not sys_pat.match(fm["system"]):
        print(f"FAIL {spec_path}: system {fm['system']!r} fails pattern", file=sys.stderr)
        failures += 1
        continue
    for p in fm.get("paths", []):
        if not path_pat.match(p):
            print(f"FAIL {spec_path}: path {p!r} fails pattern", file=sys.stderr)
            failures += 1
            break
    if "status" in fm and fm["status"] not in status_enum:
        print(f"FAIL {spec_path}: bad status {fm['status']!r}", file=sys.stderr)
        failures += 1
        continue
    print(f"OK {spec_path}: system={fm['system']} paths={fm.get('paths', [])}")
sys.exit(1 if failures else 0)
PYEOF
)

if python3 -c "$VALIDATE_PY" "$SCHEMA" \
  "$PROJ/.specify/systems/system-01-auth/spec.md" \
  "$PROJ/.specify/systems/system-02-billing/spec.md"; then
  ok "frontmatter validates against schema"
else
  err "frontmatter failed schema validation"
fi

# --- Test 2: path-resolver tier 1 reads the scaffolded specs ---
say "=== Test 2: path-resolver tier 1 picks up the scaffold ==="

# Resolve a file under services/auth/ — should map to system-01-auth.
result="$(python3 "$RESOLVER" "services/auth/oauth.py" "$PROJ" 2>&1)"
if [[ "$result" == "system-01-auth" ]]; then
  ok "tier 1 resolves services/auth/ → system-01-auth"
else
  err "tier 1 resolution wrong: got '$result', expected 'system-01-auth'"
fi

# Resolve a file under services/billing/ — should map to system-02-billing.
result="$(python3 "$RESOLVER" "services/billing/invoice.py" "$PROJ" 2>&1)"
if [[ "$result" == "system-02-billing" ]]; then
  ok "tier 1 resolves services/billing/ → system-02-billing"
else
  err "tier 1 resolution wrong: got '$result', expected 'system-02-billing'"
fi

# Resolve a file NOT under any declared path — should fall through (and may
# return some heuristic value or empty; just verify it's NOT one of the
# declared systems).
result="$(python3 "$RESOLVER" "unrelated/dir/file.py" "$PROJ" 2>&1)"
if [[ "$result" != "system-01-auth" && "$result" != "system-02-billing" ]]; then
  ok "tier 1 falls through for unrelated paths (got: $result)"
else
  err "tier 1 incorrectly matched unrelated path: $result"
fi

# --- Test 3: glob characters rejected by the substitution helper ---
say "=== Test 3: glob characters rejected ==="
BAD_OUT="$TMPDIR_TEST/bad/system-99-bad/spec.md"
if python3 -c "$PY" "$TEMPLATE" "$BAD_OUT" "system-99-bad" "services/*/auth/" 2>/dev/null; then
  err "glob path was NOT rejected (file written: $BAD_OUT)"
else
  ok "glob path correctly rejected"
fi
[[ ! -f "$BAD_OUT" ]] && ok "no spec file written for bad input" || err "spec file leaked despite rejection"

# --- Test 4: empty paths list produces `paths: []` ---
say "=== Test 4: empty paths list ==="
EMPTY_OUT="$TMPDIR_TEST/empty-proj/.specify/systems/system-03-experimental/spec.md"
python3 -c "$PY" "$TEMPLATE" "$EMPTY_OUT" "system-03-experimental" "" >/dev/null
if grep -q '^paths: \[\]$' "$EMPTY_OUT"; then
  ok "empty paths emits 'paths: []' on a single line"
else
  err "empty paths did not produce 'paths: []' line"
fi

# --- Test 5: body is preserved verbatim from template ---
say "=== Test 5: body preservation ==="
if grep -q "## Purpose" "$PROJ/.specify/systems/system-01-auth/spec.md" \
   && grep -q "## Functional Requirements" "$PROJ/.specify/systems/system-01-auth/spec.md"; then
  ok "body sections from template preserved"
else
  err "expected body sections not found in scaffolded spec"
fi

echo ""
if (( fail == 0 )); then
  printf '%s\n' "PASS: test_smith_init_system_specs"
  exit 0
else
  printf '%s\n' "FAIL: test_smith_init_system_specs"
  exit 1
fi
