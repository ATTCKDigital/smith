#!/usr/bin/env bash
# doc-counts.test.sh — pins every skill/hook count written into README.md and
# docs/architecture.md against the actual contents of skills/ and hooks/.
#
# The bug this file exists to catch is drift, and in this repo drift is fast:
#   - docs/architecture.md said "Skills (33) / Hooks (8)" against a real 36/21;
#   - feature 60 corrected four README counts to 35 in the morning, and
#     feature 67 added skills/smith-question/ the same day, so README was stale
#     again before the day was out.
#
# A corrected number on its own just resets that clock, so the numbers are
# derived here rather than transcribed. Nothing in this file may ever contain a
# literal skill or hook count — a number written here is the same bug one level
# up (the same rule tests/uninstall-hook-coverage.test.sh works under).
#
# Three assertions:
#   1. every digit written next to the word "skill(s)" in either doc equals the
#      number of directories under skills/
#   2. every digit written next to the word "hook(s)" equals the number of
#      hooks/*.sh
#   3. README actually NAMES every shipped skill and hook — a header that says
#      21 over a table listing 12 is the same defect wearing a correct number
#
# Convention this relies on: a count in these docs that is deliberately NOT the
# total is spelled as a word, not a digit. README already does this ("Eight
# design-phase skills", "Three skills:"), and assertions 1-2 only look at digits.
#
# Run: bash tests/doc-counts.test.sh
# CI:  .github/workflows/test-install.yml globs tests/*.test.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"

command -v python3 >/dev/null 2>&1 || { echo "FATAL: python3 required"; exit 1; }

echo "=== tests/doc-counts.test.sh ==="

python3 - "$REPO_ROOT" <<'PY'
import os
import re
import sys

root = sys.argv[1]
docs = ["README.md", os.path.join("docs", "architecture.md")]

PASS = [0]
FAIL = [0]


def assert_(ok, msg):
    if ok:
        print("  ok   %s" % msg)
        PASS[0] += 1
    else:
        print("  FAIL %s" % msg)
        FAIL[0] += 1


# --- ground truth: the filesystem, counted the way install.sh globs it -----
skills_dir = os.path.join(root, "skills")
hooks_dir = os.path.join(root, "hooks")

skills = sorted(
    d for d in os.listdir(skills_dir) if os.path.isdir(os.path.join(skills_dir, d))
)
hooks = sorted(
    f
    for f in os.listdir(hooks_dir)
    if f.endswith(".sh") and os.path.isfile(os.path.join(hooks_dir, f))
)

real = {"skill": len(skills), "hook": len(hooks)}
print("  (repo ships %d skills/ directories and %d hooks/*.sh)" % (real["skill"], real["hook"]))

# --- every digit written beside "skill(s)" / "hook(s)" ---------------------
# Three shapes, all present in README today:
#   "35 skills" / "26 Smith skills"   (optionally one word in between)
#   "Skills (35)"                     (section headers, architecture diagram)
#   "badge/skills-35"                 (the shields.io badge URL)
COUNT_RE = re.compile(
    r"(?i)"
    r"(?:(\d+)\s+(?:[A-Za-z][\w-]*\s+)?(skills?|hooks?)\b)"
    r"|(?:\b(skills?|hooks?)\s*\((\d+)\))"
    r"|(?:badge/(skills?|hooks?)-(\d+))"
)


def written_counts(path):
    """Yield (lineno, matched_text, noun, number) for every count in a doc."""
    with open(os.path.join(root, path), encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            for m in COUNT_RE.finditer(line):
                if m.group(1):
                    num, noun = m.group(1), m.group(2)
                elif m.group(4):
                    num, noun = m.group(4), m.group(3)
                else:
                    num, noun = m.group(6), m.group(5)
                yield lineno, m.group(0), noun.lower().rstrip("s"), int(num)


for doc in docs:
    bad = []
    seen = 0
    for lineno, text, noun, num in written_counts(doc):
        seen += 1
        if num != real[noun]:
            bad.append((lineno, text, noun, num))
    if seen == 0:
        assert_(False, "%s states at least one skill/hook count" % doc)
        continue
    if bad:
        assert_(False, "%s: all %d written counts match the filesystem" % (doc, seen))
        for lineno, text, noun, num in bad:
            print(
                "       %s:%d  %r says %d, repo ships %d %ss"
                % (doc, lineno, text, num, real[noun], noun)
            )
    else:
        assert_(True, "%s: all %d written counts match the filesystem" % (doc, seen))

# --- the counts must also agree with what README actually enumerates -------
readme = open(os.path.join(root, "README.md"), encoding="utf-8").read()

missing_skills = [
    s for s in skills if not re.search(r"/%s(?![\w-])" % re.escape(s), readme)
]
if missing_skills:
    assert_(False, "README names every shipped skill")
    for s in missing_skills:
        print("       skills/%s/ is shipped but never named in README.md" % s)
else:
    assert_(True, "README names every shipped skill (%d)" % len(skills))

missing_hooks = [h for h in hooks if h not in readme]
if missing_hooks:
    assert_(False, "README names every shipped hook")
    for h in missing_hooks:
        print("       hooks/%s is shipped but never named in README.md" % h)
else:
    assert_(True, "README names every shipped hook (%d)" % len(hooks))

print()
print("  passed: %d   failed: %d" % (PASS[0], FAIL[0]))
sys.exit(1 if FAIL[0] else 0)
PY
