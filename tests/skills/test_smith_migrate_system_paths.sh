#!/usr/bin/env bash
# test_smith_migrate_system_paths.sh — end-to-end test for the A3 migration
# skill helper at skills/smith-migrate-system-paths/scripts/migrate.py.
#
# Fixture mimics armory-style hand-authored prose system specs (no YAML
# frontmatter, conventions like "Implementation lives in `backend/...`",
# bulleted file lists). Verifies:
#   (a) frontmatter is prepended correctly
#   (b) proposed paths are plausibly derived from the prose
#   (c) re-run is a no-op (already-migrated detection)
#   (d) body bytes are preserved verbatim
#   (e) path-resolver tier 1 picks up the new paths after migration
#   (f) glob characters in synthetic prose never leak into output
#   (g) dry-run does NOT modify any files
#
# Exit 0 on success, 1 on failure.

set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
MIGRATE="${REPO_ROOT}/skills/smith-migrate-system-paths/scripts/migrate.py"
PROPOSE="${REPO_ROOT}/skills/smith-migrate-system-paths/scripts/propose_paths.py"
RESOLVER="${REPO_ROOT}/scripts/parsers/path-resolver.py"

[[ -f "$MIGRATE" ]] || { echo "missing: $MIGRATE" >&2; exit 1; }
[[ -f "$PROPOSE" ]] || { echo "missing: $PROPOSE" >&2; exit 1; }
[[ -f "$RESOLVER" ]] || { echo "missing: $RESOLVER" >&2; exit 1; }

TMPDIR_TEST="$(mktemp -d -t smith-migrate-test-XXXXXX)"
trap 'rm -rf "$TMPDIR_TEST"' EXIT

fail=0
say() { printf '  %s\n' "$1"; }
ok() { printf '  ✓ %s\n' "$1"; }
err() { printf '  ✗ %s\n' "$1" >&2; fail=1; }

# --- Build a synthetic project with prose system specs ---
PROJ="$TMPDIR_TEST/proj"
mkdir -p "$PROJ/.specify/systems/system-05-communication-triage"
mkdir -p "$PROJ/.specify/systems/system-12-content-engine"
mkdir -p "$PROJ/.specify/systems/system-01-already-migrated"
mkdir -p "$PROJ/.specify/systems/system-99-noise"

# System 05 — heavy prose, multiple convention prefixes, one star-glob in prose.
cat > "$PROJ/.specify/systems/system-05-communication-triage/spec.md" <<'EOF'
# System 05: Communication Triage

**Owners**: Foo, Bar
**Status**: active

This system handles triage of inbound communications. Implementation lives in
`backend/src/services/triage/` with frontend bindings in
`frontend/src/lib/triage/` and React components in
`frontend/src/components/triage/`.

The triage pipeline lives under `services/triage-pipeline/` (legacy) and
will eventually migrate to `services/triage/` (new path).

**Files:**

- backend/src/services/triage/router.py
- backend/src/services/triage/processor.py
- frontend/src/components/triage/TriageBoard.tsx

Glob in prose (should be ignored by propose): see `services/*/router.py` —
this is intentionally a forbidden pattern that the heuristic must not pick up.
EOF

# System 12 — different conventions; prose lighter; uses `apps/`.
cat > "$PROJ/.specify/systems/system-12-content-engine/spec.md" <<'EOF'
# System 12: Content Engine

**Owners**: Baz

Implementation in `services/content-engine/` plus dashboards at
`apps/content-dashboard/`. Shared utilities sit under `packages/content-utils/`.

This system depends on `services/content-engine/` heavily and lightly on
`apps/content-dashboard/`.
EOF

# System 01 — ALREADY MIGRATED; should be skipped.
cat > "$PROJ/.specify/systems/system-01-already-migrated/spec.md" <<'EOF'
---
system: system-01-already-migrated
status: complete
paths:
  - services/already/
also_affects: []
---

# System 01: Already Migrated

This file already has frontmatter — the migration skill should skip it.
EOF

# System 99 — pure noise; no prose hints; should be skipped-no-proposal.
cat > "$PROJ/.specify/systems/system-99-noise/spec.md" <<'EOF'
# System 99: Noise

This file has no path-like content whatsoever. It just describes purpose
in plain English without any directories or code references at all.
EOF

# --- Test 1: --dry-run does not modify files ---
say "=== Test 1: --dry-run preserves all files ==="
# Snapshot pre-state hashes
PRE_HASH_05="$(shasum "$PROJ/.specify/systems/system-05-communication-triage/spec.md" | awk '{print $1}')"
PRE_HASH_12="$(shasum "$PROJ/.specify/systems/system-12-content-engine/spec.md" | awk '{print $1}')"
PRE_HASH_01="$(shasum "$PROJ/.specify/systems/system-01-already-migrated/spec.md" | awk '{print $1}')"

python3 "$MIGRATE" --project-root "$PROJ" --dry-run --auto-confirm --non-interactive > "$TMPDIR_TEST/dry-run.log" 2>&1

POST_HASH_05="$(shasum "$PROJ/.specify/systems/system-05-communication-triage/spec.md" | awk '{print $1}')"
POST_HASH_12="$(shasum "$PROJ/.specify/systems/system-12-content-engine/spec.md" | awk '{print $1}')"
POST_HASH_01="$(shasum "$PROJ/.specify/systems/system-01-already-migrated/spec.md" | awk '{print $1}')"

[[ "$PRE_HASH_05" == "$POST_HASH_05" ]] && ok "dry-run preserves system-05" || err "dry-run modified system-05"
[[ "$PRE_HASH_12" == "$POST_HASH_12" ]] && ok "dry-run preserves system-12" || err "dry-run modified system-12"
[[ "$PRE_HASH_01" == "$POST_HASH_01" ]] && ok "dry-run preserves system-01" || err "dry-run modified system-01"

# Summary should mention DRY RUN
grep -q "DRY RUN" "$TMPDIR_TEST/dry-run.log" && ok "dry-run summary mentions DRY RUN" || err "DRY RUN not in summary"

# --- Test 2: --auto-confirm migrates eligible specs ---
say "=== Test 2: --auto-confirm migrates eligible specs ==="

# Save body content (after frontmatter strip) so we can verify preservation.
PRE_BODY_05="$PROJ/.specify/systems/system-05-communication-triage/spec.md"
PRE_BODY_05_HASH="$(shasum "$PRE_BODY_05" | awk '{print $1}')"

python3 "$MIGRATE" --project-root "$PROJ" --auto-confirm --non-interactive > "$TMPDIR_TEST/run.log" 2>&1

# System-05 should now have frontmatter with paths
if head -1 "$PROJ/.specify/systems/system-05-communication-triage/spec.md" | grep -q '^---$'; then
  ok "system-05 has frontmatter prepended"
else
  err "system-05 missing frontmatter after migration"
fi

# Extract the paths block from system-05
PATHS_05="$(python3 - <<PYEOF
import sys, pathlib
text = pathlib.Path("$PROJ/.specify/systems/system-05-communication-triage/spec.md").read_text()
assert text.startswith("---\n")
end = text.find("\n---\n", 4)
fm = text[4:end]
in_paths = False
for line in fm.splitlines():
    if line.startswith("paths:"):
        in_paths = True
        continue
    if in_paths and line.startswith("  - "):
        print(line[4:].strip())
    elif in_paths and not line.startswith("  "):
        in_paths = False
PYEOF
)"

if echo "$PATHS_05" | grep -q '^backend/src/services/triage/$'; then
  ok "system-05 proposed backend/src/services/triage/"
else
  err "system-05 did NOT propose backend/src/services/triage/ (got: $PATHS_05)"
fi

# Should NOT contain any glob characters
if echo "$PATHS_05" | grep -qF '*'; then
  err "system-05 paths contain glob character"
else
  ok "system-05 paths free of glob characters"
fi

# System-12 should have paths (services/content-engine/ or apps/...)
PATHS_12="$(python3 - <<PYEOF
import pathlib
text = pathlib.Path("$PROJ/.specify/systems/system-12-content-engine/spec.md").read_text()
assert text.startswith("---\n")
end = text.find("\n---\n", 4)
fm = text[4:end]
in_paths = False
for line in fm.splitlines():
    if line.startswith("paths:"):
        in_paths = True
        continue
    if in_paths and line.startswith("  - "):
        print(line[4:].strip())
    elif in_paths and not line.startswith("  "):
        in_paths = False
PYEOF
)"

if echo "$PATHS_12" | grep -q '^services/content-engine/$'; then
  ok "system-12 proposed services/content-engine/"
else
  err "system-12 did NOT propose services/content-engine/ (got: $PATHS_12)"
fi

# --- Test 3: already-migrated spec is unchanged ---
say "=== Test 3: already-migrated spec is skipped ==="
POST_HASH_01_2="$(shasum "$PROJ/.specify/systems/system-01-already-migrated/spec.md" | awk '{print $1}')"
[[ "$PRE_HASH_01" == "$POST_HASH_01_2" ]] && ok "system-01 unchanged (already-migrated detection)" || err "system-01 was modified"

# Summary log should mention "already has paths"
grep -q "already has paths" "$TMPDIR_TEST/run.log" && ok "summary mentions already-migrated count" || err "missing 'already has paths' in summary"

# --- Test 4: noise spec is skipped-no-proposal ---
say "=== Test 4: spec with no prose hints is skipped (no proposal) ==="
# The noise spec body should NOT have gained frontmatter
if head -1 "$PROJ/.specify/systems/system-99-noise/spec.md" | grep -q '^---$'; then
  err "system-99 gained frontmatter despite no proposals"
else
  ok "system-99 left unchanged (no prose hints)"
fi
grep -q "no prose hints" "$TMPDIR_TEST/run.log" && ok "summary mentions no-prose-hints count" || err "missing 'no prose hints' in summary"

# --- Test 5: re-run is a no-op ---
say "=== Test 5: re-run is idempotent ==="
PRE_RERUN_05="$(shasum "$PROJ/.specify/systems/system-05-communication-triage/spec.md" | awk '{print $1}')"
PRE_RERUN_12="$(shasum "$PROJ/.specify/systems/system-12-content-engine/spec.md" | awk '{print $1}')"

python3 "$MIGRATE" --project-root "$PROJ" --auto-confirm --non-interactive > "$TMPDIR_TEST/rerun.log" 2>&1

POST_RERUN_05="$(shasum "$PROJ/.specify/systems/system-05-communication-triage/spec.md" | awk '{print $1}')"
POST_RERUN_12="$(shasum "$PROJ/.specify/systems/system-12-content-engine/spec.md" | awk '{print $1}')"

[[ "$PRE_RERUN_05" == "$POST_RERUN_05" ]] && ok "system-05 unchanged on re-run" || err "system-05 changed on re-run"
[[ "$PRE_RERUN_12" == "$POST_RERUN_12" ]] && ok "system-12 unchanged on re-run" || err "system-12 changed on re-run"

# --- Test 6: body bytes preserved verbatim (after migration) ---
say "=== Test 6: body bytes preserved ==="
# The body of system-05 (after the inserted frontmatter) should byte-equal the original file.
ORIGINAL_05="$(cat <<'EOF'
# System 05: Communication Triage

**Owners**: Foo, Bar
**Status**: active

This system handles triage of inbound communications. Implementation lives in
`backend/src/services/triage/` with frontend bindings in
`frontend/src/lib/triage/` and React components in
`frontend/src/components/triage/`.

The triage pipeline lives under `services/triage-pipeline/` (legacy) and
will eventually migrate to `services/triage/` (new path).

**Files:**

- backend/src/services/triage/router.py
- backend/src/services/triage/processor.py
- frontend/src/components/triage/TriageBoard.tsx

Glob in prose (should be ignored by propose): see `services/*/router.py` —
this is intentionally a forbidden pattern that the heuristic must not pick up.
EOF
)"

ACTUAL_05="$(python3 - <<PYEOF
import pathlib
text = pathlib.Path("$PROJ/.specify/systems/system-05-communication-triage/spec.md").read_text()
assert text.startswith("---\n")
end = text.find("\n---\n", 4)
body = text[end + len("\n---\n"):]
print(body, end="")
PYEOF
)"

if [[ "$ORIGINAL_05" == "$ACTUAL_05" ]]; then
  ok "system-05 body bytes preserved verbatim"
else
  err "system-05 body bytes differ after migration"
  diff <(printf '%s' "$ORIGINAL_05") <(printf '%s' "$ACTUAL_05") | head -20 >&2
fi

# --- Test 7: path-resolver tier 1 picks up the migrated paths ---
say "=== Test 7: path-resolver reads migrated paths ==="
result="$(python3 "$RESOLVER" "backend/src/services/triage/router.py" "$PROJ" 2>&1)"
if [[ "$result" == "system-05-communication-triage" ]]; then
  ok "resolver picks up system-05 via tier 1"
else
  err "resolver wrong for system-05: got '$result'"
fi

result="$(python3 "$RESOLVER" "services/content-engine/index.js" "$PROJ" 2>&1)"
if [[ "$result" == "system-12-content-engine" ]]; then
  ok "resolver picks up system-12 via tier 1"
else
  err "resolver wrong for system-12: got '$result'"
fi

echo ""
if (( fail == 0 )); then
  printf '%s\n' "PASS: test_smith_migrate_system_paths"
  exit 0
else
  printf '%s\n' "FAIL: test_smith_migrate_system_paths"
  exit 1
fi
