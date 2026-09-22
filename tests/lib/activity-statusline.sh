#!/usr/bin/env bash
# activity-statusline.sh — sourced machinery for the statusline (SC-13/SC-12)
# and redaction (SC-14) cases of tests/smith-activity.test.sh.
#
# NOT a test file, and deliberately outside CI's `tests/*.test.sh` glob for
# the same reason activity-helpers.sh is: a sourced helper must never become
# a CI-invisible test.
#
# Split off activity-helpers.sh when the T104-T109 machinery carried it to
# 544 lines, past the repo's 500-line decompose threshold. Sourced from the
# END of activity-helpers.sh, so the test file's sourcing contract (one line,
# one file) is unchanged and every helper is still reachable from it.
#
# Sourcing contract — the caller must already have set REPO_ROOT.

# ===========================================================================
# Statusline (SC-13 / SC-12) and redaction (SC-14) machinery — T104-T109.
# ===========================================================================

STATUSLINE_TEE="$REPO_ROOT/scripts/activity/statusline-tee.sh"
INSTALL_STATUSLINE="$REPO_ROOT/scripts/install-statusline.sh"

# statusline_payload <outfile> [with-rate-limits]
# The data-model.md §4.4 subset. `rate_limits` is present only on request,
# because its ABSENCE is a first-class state (FR-35/SC-12) and half of what
# SC-12 tests — before the first API response, and on non-subscription auth,
# the key is simply not there.
statusline_payload() {
    local out="$1" with="${2:-}"
    if [ -n "$with" ]; then
        printf '%s' '{"session_id":"sl-1","cwd":"/tmp","model":{"id":"claude-opus-5","display_name":"Opus"},"workspace":{"current_dir":"/tmp/demo","project_dir":"/tmp/demo"},"context_window":{"used_percentage":8},"rate_limits":{"five_hour":{"used_percentage":23.5,"resets_at":1738425600},"seven_day":{"used_percentage":41.2,"resets_at":1738857600},"spend_limit":{"used_percentage":62.8,"resets_at":1740787200}}}' > "$out"
    else
        printf '%s' '{"session_id":"sl-1","cwd":"/tmp","model":{"id":"claude-opus-5","display_name":"Opus"},"workspace":{"current_dir":"/tmp/demo","project_dir":"/tmp/demo"},"context_window":{"used_percentage":8}}' > "$out"
    fi
}

# make_statusline <path> <marker> — a pre-existing operator statusline.
#
# It deliberately prints with NO trailing newline and echoes a field parsed out
# of the payload. Both matter: SC-13's claim is byte-for-byte, so a wrapper
# that helpfully appends a newline must fail, and a wrapper that forwards an
# EMPTY payload (the classic "read stdin twice" bug) must fail too rather than
# printing a plausible-looking constant.
make_statusline() {
    local path="$1" marker="$2"
    cat > "$path" <<EOF
#!/usr/bin/env bash
payload=\$(cat)
name=\$(printf '%s' "\$payload" | python3 -c 'import json,sys
try:
    print(json.load(sys.stdin)["model"]["display_name"], end="")
except Exception:
    print("NO-PAYLOAD", end="")' 2>/dev/null)
printf '$marker|%s|tail' "\$name"
EOF
    chmod +x "$path"
}

# install_statusline <settings-json> <smith-home> — the T105 capture + merge,
# fully sandboxed. Neither the operator's ~/.claude/settings.json nor their
# ~/.smith is reachable from here: this machine HAS a pre-existing statusLine,
# so the destructive risk SC-13 guards is the operator's own configuration.
install_statusline() {
    CLAUDE_SETTINGS="$1" SMITH_HOME="$2" \
        bash "$INSTALL_STATUSLINE" --settings "$1" >/dev/null 2>&1
}

# run_tee <smith-home> <payload-file> <outfile> — run the installed tee with
# the payload on stdin. Echoes the exit status.
run_tee() {
    local home="$1" payload="$2" out="$3"
    SMITH_HOME="$home" bash "$home/scripts/activity/statusline-tee.sh" \
        < "$payload" > "$out" 2>/dev/null
    echo $?
}

# json_field <file> <dotted.path> — one value out of a JSON file, or "" if the
# path is absent. Avoids a jq dependency in the assertions.
json_field() {
    python3 - "$1" "$2" <<'PY'
import json
import sys

try:
    with open(sys.argv[1]) as fh:
        node = json.load(fh)
except Exception:
    print("")
    sys.exit(0)
for part in sys.argv[2].split("."):
    if isinstance(node, dict) and part in node:
        node = node[part]
    else:
        print("")
        sys.exit(0)
# A bare `print(node)` here renders Python's spelling — `False`, `None` — and
# every assertion comparing against `false` or `null` then fails for a reason
# that has nothing to do with the daemon. Only a plain string passes through
# unquoted; everything else is re-serialized as JSON.
print(node if isinstance(node, str) else json.dumps(node))
PY
}

# sse_capture <port> <token> <outfile> <seconds> — a bounded /events capture.
#
# Bounded with curl's own --max-time, never a shell `timeout`: neither
# `timeout` nor `gtimeout` exists on a stock macOS, which is the same
# constraint hooks/activity-emitter.sh is written against.
sse_capture() {
    curl -sN --max-time "$4" -H 'Accept: text/event-stream' \
        "http://127.0.0.1:$1/events?token=$2" > "$3" 2>/dev/null
}

# sse_frame <transcript> <event-name> — the `data:` payload of the FIRST frame
# with that event name, or "".
sse_frame() {
    python3 - "$1" "$2" <<'PY'
import sys

name = sys.argv[2]
try:
    with open(sys.argv[1], encoding="utf-8", errors="replace") as fh:
        lines = fh.read().split("\n")
except OSError:
    print("")
    sys.exit(0)
for index, line in enumerate(lines):
    if line.strip() == "event: " + name:
        for follow in lines[index + 1 : index + 4]:
            if follow.startswith("data: "):
                print(follow[len("data: ") :])
                sys.exit(0)
print("")
PY
}

# api_get <port> <token> <route> <outfile> — one token-gated read route.
api_get() {
    curl -s --max-time 5 --connect-timeout 2 \
        "http://127.0.0.1:$1/api/$3?token=$2" > "$4" 2>/dev/null
}

# canary_hits <port> <token> <canary> <sse-transcript> <activity-log>
# The SC-14 wire sweep: every /api/* body, the captured /events transcript and
# activity.log. Echoes the TOTAL number of hits, which must be 0.
canary_hits() {
    local port="$1" token="$2" canary="$3" sse="$4" log="$5"
    local total=0 route body
    body="$(mktemp)"
    for route in state projects workflows worktrees usage vault; do
        api_get "$port" "$token" "$route" "$body"
        # `grep -c` prints a count and exits 1 on no-match, so a `|| echo 0`
        # here appends a SECOND line and breaks the arithmetic. The count
        # alone is already correct.
        total=$((total + $(grep -c "$canary" "$body" 2>/dev/null)))
    done
    rm -f "$body"
    [ -f "$sse" ] && total=$((total + $(grep -c "$canary" "$sse" 2>/dev/null)))
    [ -f "$log" ] && total=$((total + $(grep -c "$canary" "$log" 2>/dev/null)))
    echo "$total"
}

# storage_canary_hits <canary> [capture] — SC-14 at the STORAGE BOUNDARY.
#
# `capture` is the second argument, NOT the ambient environment. An earlier
# version popped SMITH_ACTIVITY_CAPTURE_PROMPTS unconditionally, which made the
# capture-ENABLED case (T109) structurally unable to pass: it asked whether the
# opt-in changes behaviour while forcing the opt-in off.
#
# This is the assertion that can actually fail, and it exists because the
# wire-level sweep above CANNOT. Verified empirically while building this:
# with redaction removed entirely, every /api/* body, the SSE transcript and
# activity.log still contained ZERO hits, because no route currently projects a
# raw `tool_input` onto the wire. A test that stays green when the control it
# guards is deleted proves nothing at all.
#
# `daemon.events_for()` is where the redacted payload actually lands, so that
# is where the canary is counted. RED-CHECKED: replacing ingest.redact()'s body
# with `return payload` makes this return 2 instead of 0.
#
# Two, not three, and the missing one is informative. The third payload hides
# the canary under an `api_key` key, and that value never reaches the store
# even with redaction deleted — `ingest.envelope()` copies only RETAINED_FIELDS
# plus the three content fields, so an unrecognised key is dropped by the field
# allowlist. That is a SECOND, independent defence, and it is why the canary is
# driven through `prompt` and `tool_input` as well: those two are retained by
# design, so redaction is the only thing standing between them and the store.
storage_canary_hits() {
    python3 - "$REPO_ROOT" "$1" "${2:-0}" <<'PY'
import json
import os
import subprocess
import sys
import tempfile

repo, canary, capture = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
sys.path.insert(0, os.path.join(repo, "scripts", "activity"))
os.environ.pop("SMITH_ACTIVITY_CAPTURE_PROMPTS", None)

import daemon as daemon_mod  # noqa: E402

work = tempfile.mkdtemp()
project = os.path.join(work, "proj")
os.makedirs(os.path.join(project, ".smith", "vault"))

# `git init` is REQUIRED, not scenery. handle_ingest attributes an event by
# resolving its cwd to a primary repo through `git rev-parse`, and a plain
# directory resolves to None — the event is counted as unattributed and never
# reaches the event store. An earlier version of this fixture omitted it and
# the canary count came back 0 from an EMPTY list, which is a false pass of
# exactly the kind this whole helper exists to avoid.
subprocess.run(["git", "init", "-q", project], check=False,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

d = daemon_mod.Daemon(
    port=0, activity_dir=os.path.join(work, "activity"), capture_prompts=capture
)
registered = d.register(project)["project"]

for payload in (
    {"session_id": "s1", "cwd": project, "hook_event_name": "UserPromptSubmit",
     "prompt": "please %s the thing" % canary},
    {"session_id": "s1", "cwd": project, "hook_event_name": "PreToolUse",
     "tool_name": "Bash", "tool_input": {"command": "echo %s" % canary}},
    {"session_id": "s1", "cwd": project, "hook_event_name": "PostToolUse",
     "tool_name": "Bash", "api_key": canary},
):
    d.handle_ingest(json.dumps(payload).encode("utf-8"))

events = d.events_for(registered)
# A count of 0 over an EMPTY store is indistinguishable from a count of 0 over
# a properly redacted one, and the second is the only one that means anything.
# `-1` is an impossible hit count, so the caller's `= 0` assertion fails loudly
# instead of passing on a fixture that ingested nothing.
if len(events) != 3:
    print(-1)
else:
    print(json.dumps(events).count(canary))
PY
}

# css_code_only <css-file> — the stylesheet with its /* … */ comments removed.
#
# Load-bearing, and learned the hard way: app.css's own header says "No web
# font, no @import, no external origin of any kind", and a raw grep for
# `@import` therefore condemns the file for DOCUMENTING the invariant it
# satisfies. This is the same failure `code_only` exists to prevent on the
# Python side, and it is why that helper strips docstrings.
css_code_only() {
    python3 - "$1" <<'PY'
import re
import sys

try:
    with open(sys.argv[1], encoding="utf-8", errors="replace") as fh:
        source = fh.read()
except OSError:
    sys.exit(0)          # unreadable: emit nothing rather than a false pass
print(re.sub(r"/\*.*?\*/", " ", source, flags=re.S))
PY
}

# html_external_origins <html-file> — every src= or href= whose VALUE begins
# with `http` or `//` (FR-49/SC-15). Anchored at the opening quote, so a URL
# appearing inside an attribute value (an SVG xmlns, say) is not a false
# positive and a real external asset cannot hide behind one.
html_external_origins() {
    grep -oE '(src|href)[[:space:]]*=[[:space:]]*"[^"]*"' "$1" 2>/dev/null \
        | grep -cE '=[[:space:]]*"(https?:|//)' || true
}
