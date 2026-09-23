#!/usr/bin/env bash
# session-log-utc.test.sh — pins the UTC instruction into every SKILL.md that
# tells the model to write a `### [HH:MM:SS]` session-log entry.
#
# The defect (BANK-029): every stamp a HOOK writes into the vault session log
# is UTC — session-start-logger.sh:43-46, file-change-logger.sh:39,
# metrics-tracker.sh:98, create-active-workflow.sh:229 are all `date -u`. The
# `### [HH:MM:SS] <event>` entries, by contrast, are written by the MODEL from
# a format block in a SKILL.md, and those blocks never said which clock to
# read. So the model wrote local time. This repository's own session log
# contains `- \`[15:18:22]\` **Bash**` immediately followed by
# `### [11:18:56] /smith-new invocation` — a four-hour skew inside one file.
#
# That used to be an ordering nuisance. PR #72 made the token window actually
# filter, and it anchors on the UTC `workflow-start` stamp precisely because
# the model-written stamp could not be trusted; the model-written stamp
# survives only as a deliberately-widened fallback. Making the model write UTC
# is what lets that fallback stop hedging, and it is what makes `Started:` in
# the audit block agree with every other number in it.
#
# WHY THIS IS A TEST AND NOT JUST AN EDIT: the instruction is only worth
# anything if it is in EVERY skill that writes such an entry. Scope is
# therefore DISCOVERED, never listed — a file is in scope iff it contains a
# `### [HH:MM:SS]` format block. Add a new skill tomorrow with a logging block
# and no UTC line and this test fails on that file by name; the assertions
# below contain no skill names and no counts, for the same reason
# tests/doc-counts.test.sh derives its numbers instead of transcribing them.
#
# Run: bash tests/session-log-utc.test.sh
# CI:  .github/workflows/test-install.yml globs tests/*.test.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"

command -v python3 >/dev/null 2>&1 || { echo "FATAL: python3 required"; exit 1; }

echo "=== tests/session-log-utc.test.sh ==="

python3 - "$REPO_ROOT" <<'PY'
import os
import re
import sys

root = sys.argv[1]
skills_dir = os.path.join(root, "skills")

PASS = [0]
FAIL = [0]


def assert_(ok, msg):
    if ok:
        print("  ok   %s" % msg)
        PASS[0] += 1
    else:
        print("  FAIL %s" % msg)
        FAIL[0] += 1


# The exact wording is pinned, not just the idea. A paraphrase in one skill and
# a different paraphrase in the next is how this drifts back apart, and a
# sentinel a human can grep for is what makes the next edit obvious.
SENTINEL_HEAD = "**Timestamps are UTC.**"
SENTINEL_CMD = "date -u +%H:%M:%S"

# The format block the model copies. Anchored at line start inside a fence.
FORMAT_BLOCK = re.compile(r"^### \[HH:MM:SS\]", re.MULTILINE)

# A local-clock reading. `date +%H...` without -u is the exact mistake, and
# `$(date +%H:%M:%S)` literal-in-the-log is a regression this repo has already
# shipped once (tests/test_legacy_parse.py::test_malformed_timestamp_not_matched).
LOCAL_CLOCK = re.compile(r"date \+[\"']?%H")

# The second format block, present only in the top-level workflow skills.
SUBAGENT_SECTION = re.compile(
    r"^## Subagent Invocation Logging\s*$(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL
)


def skill_files():
    for name in sorted(os.listdir(skills_dir)):
        path = os.path.join(skills_dir, name, "SKILL.md")
        if os.path.isfile(path):
            yield os.path.join("skills", name, "SKILL.md"), path


in_scope = []
for rel, path in skill_files():
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if FORMAT_BLOCK.search(text):
        in_scope.append((rel, text))

# Guard the discovery itself: if the format block were ever renamed, every
# assertion below would vacuously pass and this test would become a no-op.
assert_(
    bool(in_scope),
    "discovery finds at least one SKILL.md with a '### [HH:MM:SS]' format block",
)
if not in_scope:
    print()
    print("  passed: %d   failed: %d" % (PASS[0], FAIL[0]))
    sys.exit(1)

print("  (%d SKILL.md files write session-log entries)" % len(in_scope))

# --- 1. every in-scope skill carries the UTC instruction -------------------
missing_head = [rel for rel, text in in_scope if SENTINEL_HEAD not in text]
if missing_head:
    assert_(False, "every logging skill states %r" % SENTINEL_HEAD)
    for rel in missing_head:
        print("       %s writes '### [HH:MM:SS]' entries but never says UTC" % rel)
else:
    assert_(True, "every logging skill states %r" % SENTINEL_HEAD)

# --- 2. and names the command that produces one ----------------------------
missing_cmd = [rel for rel, text in in_scope if SENTINEL_CMD not in text]
if missing_cmd:
    assert_(False, "every logging skill names `%s`" % SENTINEL_CMD)
    for rel in missing_cmd:
        print("       %s says UTC but not how to obtain a UTC stamp" % rel)
else:
    assert_(True, "every logging skill names `%s`" % SENTINEL_CMD)

# --- 3. nothing tells the model to read a local clock ----------------------
local = []
for rel, text in in_scope:
    for lineno, line in enumerate(text.splitlines(), 1):
        if LOCAL_CLOCK.search(line):
            local.append((rel, lineno, line.strip()))
if local:
    assert_(False, "no logging skill instructs a local-clock `date +%H...`")
    for rel, lineno, line in local:
        print("       %s:%d  %s" % (rel, lineno, line[:100]))
else:
    assert_(True, "no logging skill instructs a local-clock `date +%H...`")

# --- 4. the second format block is covered where it exists -----------------
# The top-level workflow skills carry a `## Subagent Invocation Logging`
# section with its own `### [HH:MM:SS]` block. A UTC line at the top of the
# file is easy to read past by the time the model reaches it, so the rule is
# restated in that section. Discovered, not listed: a fifth workflow skill
# with the section and no restatement fails here.
with_subagent = [
    (rel, SUBAGENT_SECTION.search(text)) for rel, text in in_scope
]
with_subagent = [(rel, m.group(1)) for rel, m in with_subagent if m]
assert_(
    bool(with_subagent),
    "discovery finds at least one '## Subagent Invocation Logging' section",
)
bad_sub = [rel for rel, body in with_subagent if SENTINEL_CMD not in body]
if bad_sub:
    assert_(False, "every 'Subagent Invocation Logging' section restates the UTC rule")
    for rel in bad_sub:
        print("       %s: the section's own [HH:MM:SS] block is unqualified" % rel)
else:
    assert_(
        True,
        "every 'Subagent Invocation Logging' section restates the UTC rule (%d)"
        % len(with_subagent),
    )

print()
print("  passed: %d   failed: %d" % (PASS[0], FAIL[0]))
sys.exit(1 if FAIL[0] else 0)
PY
