#!/usr/bin/env bash
# tests/e2e/test_full_describe_flow.sh — End-to-end v2 description flow.
#
# Covers task T110:
#   1. Create isolated synthetic project under /tmp/ with two systems
#      (services/foo/, services/bar/) and ~5 source files with multi-method
#      classes (NO docstrings — descriptions must come from the LLM stub).
#   2. Author `.specify/systems/system-01-foo/spec.md` and
#      `.specify/systems/system-02-bar/spec.md` with YAML frontmatter
#      declaring their paths.
#   3. Run /smith-index (no --describe). Verify tier-1 resolution buckets
#      files into system-01-foo / system-02-bar (not the heuristic name).
#   4. Run /smith-index --describe against a stdlib http.server mock of the
#      Anthropic Messages API. Verify description-layer fields populated
#      on each .meta.
#   5. Simulate a smith-workflow edit: append a new method to one file,
#      compute touched method ids via the parser+meta_describe.update-touched
#      CLI, verify only the touched method's description is regenerated
#      and untouched method descriptions are byte-identical.
#   6. Verify save hook preserves the description layer when the file is
#      re-written by invoking hooks/manifest-updater.sh with synthetic
#      stdin JSON. Hash updates; description layer + Described-Against-Hash
#      do NOT.
#   7. Verify the /smith-build coverage flag algorithm warns about a method
#      that lacks a description (synthetic git diff vs main).
#
# Exit 0 on all-pass, non-zero on first failure.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RUNNER="$REPO_ROOT/scripts/smith-index/run.py"
PARSER_PY="$REPO_ROOT/scripts/parsers/parse-python.py"
RESOLVER="$REPO_ROOT/scripts/parsers/path-resolver.py"
META_DESCRIBE="$REPO_ROOT/scripts/parsers/meta_describe.py"
SAVE_HOOK="$REPO_ROOT/hooks/manifest-updater.sh"

for f in "$RUNNER" "$PARSER_PY" "$RESOLVER" "$META_DESCRIBE" "$SAVE_HOOK"; do
  if [ ! -f "$f" ]; then
    echo "FAIL: required file missing: $f"
    exit 1
  fi
done

TMP_PROJECT="$(mktemp -d -t smith-e2e-describe-XXXXXX)"
FAKE_HOME="$(mktemp -d -t smith-e2e-home-XXXXXX)"
MOCK_LOG="$TMP_PROJECT/mock-haiku.log"
MOCK_PID=""

cleanup() {
  if [ -n "$MOCK_PID" ]; then
    kill "$MOCK_PID" 2>/dev/null || true
    wait "$MOCK_PID" 2>/dev/null || true
  fi
  rm -rf "$TMP_PROJECT" "$FAKE_HOME"
}
trap cleanup EXIT

PASS=0
FAIL=0
assert() {
  local label="$1"
  if [ "$2" = "true" ]; then
    echo "  PASS $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL $label"
    FAIL=$((FAIL + 1))
  fi
}

# -------------------------------------------------------------------------
# Step 1: build the synthetic source tree.
# -------------------------------------------------------------------------
echo "=== Step 1: build synthetic project ==="

mkdir -p "$TMP_PROJECT/services/foo" "$TMP_PROJECT/services/bar"
mkdir -p "$TMP_PROJECT/.smith/scripts"

# Use the repo parsers (with stable ids) via project-local override so the
# save hook doesn't try to read whatever lives in ~/.smith/scripts.
cp "$PARSER_PY" "$TMP_PROJECT/.smith/scripts/parse-python.py"
cp "$REPO_ROOT/scripts/parsers/parse-js.js" "$TMP_PROJECT/.smith/scripts/parse-js.js"
chmod +x "$TMP_PROJECT/.smith/scripts/parse-python.py" \
        "$TMP_PROJECT/.smith/scripts/parse-js.js"

cat > "$TMP_PROJECT/services/foo/dispatcher.py" <<'EOF'
def dispatch(payload, retry_policy):
    attempts = 0
    while attempts < retry_policy.max_attempts:
        attempts += 1
        if _attempt(payload):
            return True
    return False


def _attempt(payload):
    total = 0
    for item in payload.items:
        total += item.weight
    return total > 0
EOF

cat > "$TMP_PROJECT/services/foo/router.py" <<'EOF'
class Router:
    def __init__(self, table):
        self.table = table

    def route(self, request):
        target = self.table.get(request.kind)
        if target is None:
            return None
        return target.handle(request)

    def add(self, kind, target):
        self.table[kind] = target
        return self
EOF

cat > "$TMP_PROJECT/services/foo/queue.py" <<'EOF'
def enqueue(q, item):
    q.append(item)
    if len(q) > 100:
        q.pop(0)
    return q


def drain(q):
    drained = []
    while q:
        drained.append(q.pop(0))
    return drained
EOF

cat > "$TMP_PROJECT/services/bar/billing.py" <<'EOF'
def compute_invoice(line_items, tax_rate):
    subtotal = 0
    for li in line_items:
        subtotal += li.unit_price * li.quantity
    tax = subtotal * tax_rate
    return subtotal + tax


def refund(invoice, amount):
    if amount > invoice.total:
        return None
    invoice.refunded = amount
    return invoice
EOF

cat > "$TMP_PROJECT/services/bar/ledger.py" <<'EOF'
class Ledger:
    def __init__(self):
        self.entries = []

    def record(self, entry):
        self.entries.append(entry)
        return len(self.entries)

    def balance(self):
        total = 0
        for e in self.entries:
            total += e.amount
        return total
EOF

# Initialise git so the build-coverage algorithm can compare against `main`.
(cd "$TMP_PROJECT" && git init -q -b main >/dev/null 2>&1 || git init -q >/dev/null 2>&1)
cd "$TMP_PROJECT"
git config user.email "test@example.com"
git config user.name "Test"

# -------------------------------------------------------------------------
# Step 2: author the system specs with YAML frontmatter (Phase D template).
# -------------------------------------------------------------------------
echo "=== Step 2: author .specify/systems/ specs with paths frontmatter ==="

mkdir -p "$TMP_PROJECT/.specify/systems/system-01-foo"
mkdir -p "$TMP_PROJECT/.specify/systems/system-02-bar"

cat > "$TMP_PROJECT/.specify/systems/system-01-foo/spec.md" <<'EOF'
---
system: system-01-foo
status: active
paths:
  - services/foo/
also_affects: []
---

# system-01-foo

Synthetic foo system for the v2 E2E test.
EOF

cat > "$TMP_PROJECT/.specify/systems/system-02-bar/spec.md" <<'EOF'
---
system: system-02-bar
status: active
paths:
  - services/bar/
also_affects: []
---

# system-02-bar

Synthetic bar system for the v2 E2E test.
EOF

# Verify tier-1 resolver picks up the declared paths.
resolved_foo="$(python3 "$RESOLVER" services/foo/dispatcher.py "$TMP_PROJECT" 2>/dev/null)"
resolved_bar="$(python3 "$RESOLVER" services/bar/billing.py "$TMP_PROJECT" 2>/dev/null)"
[ "$resolved_foo" = "system-01-foo" ] \
  && assert "resolver tier-1 routes foo file → system-01-foo" true \
  || assert "resolver tier-1 routes foo file → system-01-foo (got $resolved_foo)" false
[ "$resolved_bar" = "system-02-bar" ] \
  && assert "resolver tier-1 routes bar file → system-02-bar" true \
  || assert "resolver tier-1 routes bar file → system-02-bar (got $resolved_bar)" false

# Commit baseline so the coverage step can `git diff main`.
git add . >/dev/null 2>&1
git commit -q -m "baseline" >/dev/null 2>&1
git branch -m main 2>/dev/null || true

# -------------------------------------------------------------------------
# Step 3: run /smith-index (no --describe). Verify systems-bucketing.
# -------------------------------------------------------------------------
echo "=== Step 3: structural /smith-index ==="

export HOME="$FAKE_HOME"
python3 "$RUNNER" --root "$TMP_PROJECT" >/dev/null 2>&1 \
  || true  # mode_full is best-effort; sanity-check via .meta files below.

foo_meta="$TMP_PROJECT/.smith/index/files/services/foo/dispatcher.py.meta"
bar_meta="$TMP_PROJECT/.smith/index/files/services/bar/billing.py.meta"

[ -f "$foo_meta" ] && assert "foo dispatcher .meta exists" true \
                    || assert "foo dispatcher .meta exists" false
[ -f "$bar_meta" ] && assert "bar billing .meta exists" true \
                    || assert "bar billing .meta exists" false

# The structural pass should produce per-system manifests at
# .smith/index/systems/<id>.md. The tier-1 resolver puts files into the
# declared system buckets.
foo_sys_manifest="$TMP_PROJECT/.smith/index/systems/system-01-foo.md"
bar_sys_manifest="$TMP_PROJECT/.smith/index/systems/system-02-bar.md"

if [ -f "$foo_sys_manifest" ]; then
  if grep -q "services/foo/dispatcher.py" "$foo_sys_manifest"; then
    assert "system-01-foo manifest contains foo dispatcher" true
  else
    assert "system-01-foo manifest contains foo dispatcher" false
  fi
else
  assert "system-01-foo manifest written" false
fi

if [ -f "$bar_sys_manifest" ]; then
  if grep -q "services/bar/billing.py" "$bar_sys_manifest"; then
    assert "system-02-bar manifest contains bar billing" true
  else
    assert "system-02-bar manifest contains bar billing" false
  fi
else
  assert "system-02-bar manifest written" false
fi

# Description layer should be EMPTY at this point — structural-only.
if grep -q '^\*\*Description:\*\* ' "$foo_meta" 2>/dev/null; then
  assert "structural pass leaves description layer empty (foo)" false
else
  assert "structural pass leaves description layer empty (foo)" true
fi

# -------------------------------------------------------------------------
# Step 4: spin up mock Haiku and run /smith-index --describe.
# -------------------------------------------------------------------------
echo "=== Step 4: /smith-index --describe with mocked Haiku ==="

MOCK_PORT=18743
python3 - "$MOCK_PORT" "$MOCK_LOG" >/dev/null 2>&1 <<'PYMOCK' &
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(sys.argv[1])
LOG_PATH = sys.argv[2]

# Extract referenced method ids from the prompt body and emit a JSON map of
# id -> description so the bulk path populates real ids (not a stub key).
ID_RE = re.compile(r"\bId:\s*([a-f0-9]{16})\b")

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        body = self.rfile.read(length).decode("utf-8")
        with open(LOG_PATH, "a") as f:
            f.write(body + "\n")
        try:
            req = json.loads(body)
        except json.JSONDecodeError:
            req = {}
        sys_prompt = req.get("system", "")
        if "JSON object" in sys_prompt:
            # Per-method prompt. Pull ids out of the user message and map
            # them to a stable description string.
            content = ""
            msgs = req.get("messages") or []
            if msgs and isinstance(msgs[0], dict):
                content = str(msgs[0].get("content", ""))
            ids = ID_RE.findall(content)
            if not ids:
                ids = ["deadbeefdeadbeef"]
            mapping = {mid: f"Stub method description for {mid[:8]}." for mid in ids}
            text = json.dumps(mapping)
        else:
            text = "Stub module description for e2e."
        payload = {
            "id": "msg_mock",
            "type": "message",
            "role": "assistant",
            "model": req.get("model", "claude-haiku-4-5"),
            "content": [{"type": "text", "text": text}],
        }
        out = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a, **k):
        pass

HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
PYMOCK
MOCK_PID=$!
for _ in 1 2 3 4 5 6 7 8 9 10; do
  python3 -c "import socket; s=socket.socket(); s.settimeout(0.2); s.connect(('127.0.0.1', $MOCK_PORT))" 2>/dev/null && break
  sleep 0.1
done

export ANTHROPIC_API_KEY="test-key"
export SMITH_ANTHROPIC_API_URL="http://127.0.0.1:${MOCK_PORT}/v1/messages"

# Threshold=0 so every method qualifies (synthetic files are small).
describe_out="$(python3 "$RUNNER" --root "$TMP_PROJECT" --describe \
                  --no-interactive --batch-size 5 --threshold 0 2>&1)"
describe_status=$?
[ $describe_status -eq 0 ] \
  && assert "--describe exited 0" true \
  || assert "--describe exited 0 (got $describe_status: $describe_out)" false

# All five files should have a module description now.
desc_count=0
for m in services/foo/dispatcher.py services/foo/router.py services/foo/queue.py \
         services/bar/billing.py services/bar/ledger.py; do
  mp="$TMP_PROJECT/.smith/index/files/${m}.meta"
  if [ -f "$mp" ] && grep -q '^\*\*Description:\*\* ' "$mp" \
                  && grep -q '^Described-Against-Hash: ' "$mp" \
                  && grep -q '^Described-At: ' "$mp"; then
    desc_count=$((desc_count + 1))
  fi
done
[ "$desc_count" -eq 5 ] \
  && assert "all 5 files have description layer (Description / Hash / At)" true \
  || assert "all 5 files have description layer ($desc_count/5)" false

# At least one .meta should carry per-method `Description:` suffixes.
method_desc_count="$(grep -rh '^  Description: ' "$TMP_PROJECT/.smith/index/files/" 2>/dev/null | wc -l | tr -d ' ')"
[ "$method_desc_count" -gt 0 ] \
  && assert "per-method Description: suffixes emitted ($method_desc_count lines)" true \
  || assert "per-method Description: suffixes emitted (got $method_desc_count)" false

# JSONL log and checkpoint.
[ -d "$TMP_PROJECT/.smith/index/logs" ] && assert "describe logs dir created" true \
                                        || assert "describe logs dir created" false
log_file="$(ls -t "$TMP_PROJECT/.smith/index/logs/smith-index-describe-"*.jsonl 2>/dev/null | head -1)"
[ -n "$log_file" ] && [ -f "$log_file" ] \
  && assert "JSONL describe log written" true \
  || assert "JSONL describe log written" false
[ -f "$TMP_PROJECT/.smith/index/.smith-index-describe-checkpoint.json" ] \
  && assert "checkpoint file written" true \
  || assert "checkpoint file written" false

# -------------------------------------------------------------------------
# Step 5: simulate a workflow edit; verify update-touched only regenerates
# the touched method's description.
# -------------------------------------------------------------------------
echo "=== Step 5: workflow edit → update-touched regenerates ONLY touched id ==="

# Snapshot router's pre-edit description-layer lines.
router_meta="$TMP_PROJECT/.smith/index/files/services/foo/router.py.meta"
[ -f "$router_meta" ] && assert "router meta exists pre-edit" true \
                       || assert "router meta exists pre-edit" false

grep '^\(\*\*Description:\*\* \|  Description: \)' "$router_meta" \
  > "$TMP_PROJECT/router-desc-before.txt"
desc_lines_before=$(wc -l < "$TMP_PROJECT/router-desc-before.txt" | tr -d ' ')

# Capture the existing method ids (route, add, __init__).
declare -a PRE_IDS=()
while IFS= read -r line; do
  PRE_IDS+=("$line")
done < <(python3 "$PARSER_PY" "$TMP_PROJECT/services/foo/router.py" \
           | python3 -c '
import json, sys
d = json.load(sys.stdin)
for cls in d.get("classes") or []:
    for m in cls.get("methods") or []:
        if m.get("id"):
            print(m["id"])
for fn in d.get("functions") or []:
    if fn.get("id"):
        print(fn["id"])
')

# Append a NEW method to router.py (simulates a workflow edit).
cat >> "$TMP_PROJECT/services/foo/router.py" <<'EOF'

    def fallback(self, request):
        return None
EOF

# Recompute ids — the new method id is the one not in PRE_IDS.
new_id=""
POST_IDS_STR="$(python3 "$PARSER_PY" "$TMP_PROJECT/services/foo/router.py" \
  | python3 -c '
import json, sys
d = json.load(sys.stdin)
for cls in d.get("classes") or []:
    for m in cls.get("methods") or []:
        if m.get("id"):
            print(m["id"])
for fn in d.get("functions") or []:
    if fn.get("id"):
        print(fn["id"])
')"
PRE_IDS_STR=""
for prev in "${PRE_IDS[@]}"; do
  PRE_IDS_STR="${PRE_IDS_STR} ${prev}"
done
while IFS= read -r pid; do
  [ -z "$pid" ] && continue
  case " ${PRE_IDS_STR} " in
    *" ${pid} "*) ;;
    *) new_id="$pid"; break ;;
  esac
done <<< "$POST_IDS_STR"
[ -n "$new_id" ] \
  && assert "touched (new) method id detected: $new_id" true \
  || assert "touched method id detected" false

# Save the file via the save-hook so .meta is structurally up-to-date but
# description-layer is preserved (we'll verify that below). The hook is
# LLM-free, so it does NOT add a description for the new method on its own.
echo "{\"tool_input\":{\"file_path\":\"$TMP_PROJECT/services/foo/router.py\"},\"cwd\":\"$TMP_PROJECT\"}" \
  | bash "$SAVE_HOOK" >/dev/null 2>&1

# Now invoke meta_describe update-touched for the new method only.
python3 "$META_DESCRIBE" update-touched \
  --rel-path services/foo/router.py \
  --touched-ids "$new_id" \
  --purpose-shifted false \
  --threshold 0 \
  --root "$TMP_PROJECT" >/dev/null 2>&1 \
  || true

# We can't (easily) re-render .meta from the CLI output here — that's the
# job of the workflow skill. Instead, exercise update_touched via the
# python module to confirm it preserves untouched ids and regenerates only
# the touched id. This is the semantic check the workflow skills rely on.

python3 <<PY
import json, sys, pathlib
import importlib.util

repo = pathlib.Path("$REPO_ROOT")
spec = importlib.util.spec_from_file_location(
    "meta_describe", str(repo / "scripts" / "parsers" / "meta_describe.py"),
)
md = importlib.util.module_from_spec(spec)
sys.modules["meta_describe"] = md
spec.loader.exec_module(md)

# Build a small fixture: existing layer with three method ids.
existing = md.MetaDescription(
    module_description="Existing module description.",
    method_descriptions={
        "$new_id": "STALE DESCRIPTION FOR NEW ID",
        "aaaaaaaaaaaaaaaa": "Existing description for aaa — must be preserved.",
        "bbbbbbbbbbbbbbbb": "Existing description for bbb — must be preserved.",
    },
    described_against_hash="oldhash",
    described_at="2026-01-01T00:00:00Z",
)

# Build a parsed dict whose qualifying methods include the new id and two
# existing ids. Body lines >= threshold (threshold=0 here).
parsed = {
    "path": "services/foo/router.py",
    "language": "python",
    "lines": 20,
    "classes": [{
        "name": "Router",
        "methods": [
            {"id": "$new_id", "name": "fallback", "line": 14, "params": [{"name": "self"}], "return_type": None},
            {"id": "aaaaaaaaaaaaaaaa", "name": "route", "line": 5, "params": [{"name": "self"}], "return_type": None},
            {"id": "bbbbbbbbbbbbbbbb", "name": "add", "line": 9, "params": [{"name": "self"}], "return_type": None},
        ],
    }],
    "functions": [],
}

calls = {"count": 0, "saw_new_id": False, "saw_other_ids": False}

def fake_client(messages, system_prompt, model):
    calls["count"] += 1
    if "JSON object" in system_prompt:
        # Per-method batch — should only see the new id.
        content = messages[0]["content"] if messages else ""
        if "$new_id" in content:
            calls["saw_new_id"] = True
        for other in ("aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb"):
            if f"Id: {other}" in content:
                calls["saw_other_ids"] = True
        return json.dumps({"$new_id": "Returns the fallback handler for unrouted requests."})
    return "Should NOT be called when purpose_shifted=False"

source = open("$TMP_PROJECT/services/foo/router.py").read()
desc = md.update_touched(
    rel_path="services/foo/router.py",
    source=source,
    parsed=parsed,
    existing=existing,
    touched_method_ids={"$new_id"},
    purpose_shifted=False,
    threshold=0,
    client=fake_client,
)

# Required behaviors:
#  - new id description changed (no longer "STALE...")
#  - both other ids preserved verbatim
#  - module description preserved (purpose_shifted=False)
#  - LLM was called with new id only, never with others
ok = True
if desc.method_descriptions["$new_id"].startswith("STALE"):
    print("FAIL: touched id description not regenerated", file=sys.stderr); ok = False
if desc.method_descriptions["aaaaaaaaaaaaaaaa"] != "Existing description for aaa — must be preserved.":
    print("FAIL: untouched aaa description changed", file=sys.stderr); ok = False
if desc.method_descriptions["bbbbbbbbbbbbbbbb"] != "Existing description for bbb — must be preserved.":
    print("FAIL: untouched bbb description changed", file=sys.stderr); ok = False
if desc.module_description != "Existing module description.":
    print(f"FAIL: module description regenerated (purpose_shifted=False): {desc.module_description!r}", file=sys.stderr); ok = False
if not calls["saw_new_id"]:
    print("FAIL: LLM never saw new id", file=sys.stderr); ok = False
if calls["saw_other_ids"]:
    print("FAIL: LLM saw untouched ids in prompt", file=sys.stderr); ok = False

sys.exit(0 if ok else 1)
PY
update_touched_status=$?
[ $update_touched_status -eq 0 ] \
  && assert "update_touched: regenerates only touched id; preserves others; module unchanged" true \
  || assert "update_touched: regenerates only touched id; preserves others; module unchanged" false

# -------------------------------------------------------------------------
# Step 6: save hook preserves description layer end-to-end.
# -------------------------------------------------------------------------
echo "=== Step 6: save hook preserves description layer ==="

billing_meta="$TMP_PROJECT/.smith/index/files/services/bar/billing.py.meta"
# Snapshot description-layer lines.
grep '^\(\*\*Description:\*\* \|Described-Against-Hash: \|Described-At: \|  Description: \)' \
  "$billing_meta" > "$TMP_PROJECT/billing-desc-before.txt"
orig_hash="$(grep '^Hash: ' "$billing_meta" | awk '{print $2}')"

# Edit the source body to force a hash change.
cat > "$TMP_PROJECT/services/bar/billing.py" <<'EOF'
def compute_invoice(line_items, tax_rate):
    subtotal = 0
    for li in line_items:
        subtotal += li.unit_price * li.quantity * 1
    tax = subtotal * tax_rate
    return subtotal + tax + 0


def refund(invoice, amount):
    if amount > invoice.total:
        return None
    invoice.refunded = amount
    return invoice
EOF

# Invoke the save hook via stdin (the real Claude Code interface).
echo "{\"tool_input\":{\"file_path\":\"$TMP_PROJECT/services/bar/billing.py\"},\"cwd\":\"$TMP_PROJECT\"}" \
  | bash "$SAVE_HOOK" >/dev/null 2>&1

# Description layer must be byte-identical.
grep '^\(\*\*Description:\*\* \|Described-Against-Hash: \|Described-At: \|  Description: \)' \
  "$billing_meta" > "$TMP_PROJECT/billing-desc-after.txt"
if diff -q "$TMP_PROJECT/billing-desc-before.txt" "$TMP_PROJECT/billing-desc-after.txt" >/dev/null; then
  assert "save hook preserves description layer byte-for-byte" true
else
  assert "save hook preserves description layer byte-for-byte" false
fi

# Hash should have updated; Described-Against-Hash should be unchanged.
new_hash="$(grep '^Hash: ' "$billing_meta" | awk '{print $2}')"
dah="$(grep '^Described-Against-Hash: ' "$billing_meta" | awk '{print $2}')"
if [ "$new_hash" != "$orig_hash" ]; then
  assert "save hook updates Hash after body edit" true
else
  assert "save hook updates Hash after body edit (still $new_hash)" false
fi
if [ "$dah" = "$orig_hash" ]; then
  assert "Described-Against-Hash preserved (staleness detectable)" true
else
  assert "Described-Against-Hash preserved (expected=$orig_hash got=$dah)" false
fi
if [ "$new_hash" != "$dah" ]; then
  assert "Hash != Described-Against-Hash signals stale description" true
else
  assert "Hash != Described-Against-Hash signals stale description" false
fi

# -------------------------------------------------------------------------
# Step 7: /smith-build coverage flag warns about a method without a
# description (use the new fallback method which lacks a description in
# .meta after the save-hook re-render).
# -------------------------------------------------------------------------
echo "=== Step 7: /smith-build coverage flag for undescribed method ==="

# After step 5 we appended `fallback` to router.py. The save hook would
# have re-rendered the .meta but it had no description for the new id.
# Verify that the new id does not have a Description: line in .meta yet.
router_meta_after="$TMP_PROJECT/.smith/index/files/services/foo/router.py.meta"
echo "{\"tool_input\":{\"file_path\":\"$TMP_PROJECT/services/foo/router.py\"},\"cwd\":\"$TMP_PROJECT\"}" \
  | bash "$SAVE_HOOK" >/dev/null 2>&1

# Synthesise a git change on a feature branch: commit baseline (already
# committed in step 1), then make the changes the "feature branch".
cd "$TMP_PROJECT"
git checkout -q -b feature-coverage 2>/dev/null || true
git add . >/dev/null 2>&1
git commit -q -m "add fallback" >/dev/null 2>&1 || true

# Run the coverage algorithm (a simplified extraction of /smith-build's
# step 5.3.1 — see tests/skills/test_smith_build_coverage_flag.sh for the
# full version).
export SMITH_TEST_PARSER="$PARSER_PY"
git diff main --name-only > /tmp/smith-e2e-changed.txt
> /tmp/smith-e2e-misses.txt
while IFS= read -r f; do
  case "$f" in *.py) ;; *) continue ;; esac
  [ -f "$f" ] || continue
  python3 - "$f" >> /tmp/smith-e2e-misses.txt <<'PY' || true
import json, os, re, subprocess, sys, tempfile

rel = sys.argv[1]
parser = os.environ["SMITH_TEST_PARSER"]
try:
    cur = json.loads(subprocess.check_output(["python3", parser, rel]).decode())
except Exception:
    sys.exit(0)

head_methods = []
for fn in cur.get("functions") or []:
    if fn.get("id"):
        head_methods.append((fn["id"], f"{rel}::{fn.get('name', '')}"))
for cls in cur.get("classes") or []:
    for m in cls.get("methods") or []:
        if m.get("id"):
            head_methods.append((m["id"], f"{rel}::{cls.get('name', '')}::{m.get('name', '')}"))

try:
    main_src = subprocess.check_output(
        ["git", "show", f"main:{rel}"], stderr=subprocess.DEVNULL
    ).decode("utf-8", errors="replace")
except subprocess.CalledProcessError:
    main_src = None

prev_ids = set()
if main_src is not None:
    with tempfile.TemporaryDirectory() as scratch:
        staged = os.path.join(scratch, rel)
        os.makedirs(os.path.dirname(staged), exist_ok=True)
        with open(staged, "w") as fh:
            fh.write(main_src)
        try:
            prev = json.loads(subprocess.check_output(["python3", parser, rel], cwd=scratch).decode())
            for fn in prev.get("functions") or []:
                if fn.get("id"):
                    prev_ids.add(fn["id"])
            for cls in prev.get("classes") or []:
                for m in cls.get("methods") or []:
                    if m.get("id"):
                        prev_ids.add(m["id"])
        except Exception:
            pass

touched = [(fid, qname) for (fid, qname) in head_methods if fid not in prev_ids]

meta_path = os.path.join(".smith", "index", "files", rel + ".meta")
desc_ids = set()
if os.path.isfile(meta_path):
    in_funcs = False
    current_id = None
    with open(meta_path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith("## Functions") or line.startswith("## Classes"):
                in_funcs = True; current_id = None; continue
            if line.startswith("## ") and in_funcs:
                in_funcs = False; current_id = None; continue
            if in_funcs:
                m = re.match(r"^\s*Id:\s+(\S+)", line)
                if m:
                    current_id = m.group(1); continue
                m = re.match(r"^\s*Description:\s+(.+)$", line)
                if m and current_id:
                    if m.group(1).strip():
                        desc_ids.add(current_id)
                    current_id = None

for fid, qname in touched:
    if fid not in desc_ids:
        print(f"- {qname} (id: {fid})")
PY
done < /tmp/smith-e2e-changed.txt

# The fallback method should appear in the coverage misses.
if grep -q "router.py::Router::fallback" /tmp/smith-e2e-misses.txt; then
  assert "coverage flag lists undescribed new method (fallback)" true
else
  echo "  --- coverage misses ---"
  sed 's/^/  /' /tmp/smith-e2e-misses.txt
  assert "coverage flag lists undescribed new method (fallback)" false
fi

# -------------------------------------------------------------------------
echo
echo "test_full_describe_flow: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
