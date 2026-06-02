#!/usr/bin/env bash
# tests/e2e/test_migration_paths.sh — T113.
#
# End-to-end coverage of /smith-migrate-system-paths against an armory-mimic
# fixture (prose-only system specs, no YAML frontmatter). Verifies that:
#   1. migrate.py adds correct paths frontmatter to all system specs;
#   2. the new frontmatter is read back by the path-resolver tier 1 and
#      buckets source files into the right system;
#   3. re-running migrate.py is a no-op on already-migrated specs.
#
# Exit 0 on all-pass, non-zero on first failure.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MIGRATE_PY="$REPO_ROOT/skills/smith-migrate-system-paths/scripts/migrate.py"
RESOLVER="$REPO_ROOT/scripts/parsers/path-resolver.py"

[ -f "$MIGRATE_PY" ] || { echo "FAIL: migrate.py missing: $MIGRATE_PY"; exit 1; }
[ -f "$RESOLVER" ]   || { echo "FAIL: resolver missing: $RESOLVER"; exit 1; }

TMP_PROJECT="$(mktemp -d -t smith-e2e-migrate-XXXXXX)"
trap 'rm -rf "$TMP_PROJECT"' EXIT

PASS=0
FAIL=0
assert() {
  if [ "$2" = "true" ]; then
    echo "  PASS $1"
    PASS=$((PASS + 1))
  else
    echo "  FAIL $1"
    FAIL=$((FAIL + 1))
  fi
}

# Build the armory-mimic fixture: three prose-only system specs.
mkdir -p "$TMP_PROJECT/.specify/systems/system-04-webhooks"
mkdir -p "$TMP_PROJECT/.specify/systems/system-07-billing"
mkdir -p "$TMP_PROJECT/.specify/systems/system-12-empty"
mkdir -p "$TMP_PROJECT/backend/webhooks"
mkdir -p "$TMP_PROJECT/services/webhook_dispatcher"
mkdir -p "$TMP_PROJECT/backend/billing"
mkdir -p "$TMP_PROJECT/services/billing"

# Real source files for the resolver to bucket.
echo "def dispatch(): pass"  > "$TMP_PROJECT/backend/webhooks/dispatcher.py"
echo "def retry(): pass"     > "$TMP_PROJECT/services/webhook_dispatcher/retry.py"
echo "def invoice(): pass"   > "$TMP_PROJECT/backend/billing/invoice.py"
echo "def refund(): pass"    > "$TMP_PROJECT/services/billing/refund.py"

# Prose-only spec for system-04-webhooks (no frontmatter).
cat > "$TMP_PROJECT/.specify/systems/system-04-webhooks/spec.md" <<'EOF'
# system-04-webhooks

Webhook delivery and retry infrastructure.

**Status**: active

## Purpose

Inbound and outbound webhook orchestration. Implementation lives primarily
in `backend/webhooks/` with the dispatcher in
`services/webhook_dispatcher/`. The dispatcher handles retry and backoff;
the backend handles routing and persistence.

## Files

- `backend/webhooks/dispatcher.py`
- `backend/webhooks/retry.py`
- `services/webhook_dispatcher/__init__.py`

## Dependencies

Talks to system-07-billing for refund-event delivery, see
`services/webhook_dispatcher/dispatcher.py`.
EOF

# Prose-only spec for system-07-billing (no frontmatter).
cat > "$TMP_PROJECT/.specify/systems/system-07-billing/spec.md" <<'EOF'
# system-07-billing

Customer invoicing and refund flows.

**Status**: active

## Purpose

Billing pipeline. The invoice generation lives in `backend/billing/`. The
public-facing refund flow is in `services/billing/`. Both depend on the
payment-gateway client.

## Files

- `backend/billing/invoice.py`
- `services/billing/refund.py`
EOF

# Prose-only spec with NO mentioned paths — should be skipped-no-proposal.
cat > "$TMP_PROJECT/.specify/systems/system-12-empty/spec.md" <<'EOF'
# system-12-empty

Placeholder for a forthcoming module. No paths declared yet.

**Status**: proposed
EOF

# --- Run migrate.py --auto-confirm ---------------------------------------
echo "=== Step 1: migrate.py --auto-confirm ==="
migrate_out="$(python3 "$MIGRATE_PY" \
  --project-root "$TMP_PROJECT" \
  --auto-confirm --non-interactive 2>&1)"
migrate_status=$?
[ $migrate_status -eq 0 ] \
  && assert "migrate.py exited 0" true \
  || assert "migrate.py exited 0 (got $migrate_status: $migrate_out)" false

# Verify frontmatter present + correct.
for sys in system-04-webhooks system-07-billing; do
  spec="$TMP_PROJECT/.specify/systems/$sys/spec.md"
  if head -1 "$spec" | grep -q '^---$'; then
    assert "$sys: spec starts with frontmatter" true
  else
    assert "$sys: spec starts with frontmatter" false
  fi
  if grep -q "^system: $sys" "$spec"; then
    assert "$sys: frontmatter has correct system id" true
  else
    assert "$sys: frontmatter has correct system id" false
  fi
  if grep -q "^paths:" "$spec"; then
    assert "$sys: frontmatter has paths field" true
  else
    assert "$sys: frontmatter has paths field" false
  fi
done

# system-04-webhooks should have backend/webhooks/ in its paths.
if grep -q "  - backend/webhooks/" \
    "$TMP_PROJECT/.specify/systems/system-04-webhooks/spec.md"; then
  assert "system-04-webhooks paths include backend/webhooks/" true
else
  assert "system-04-webhooks paths include backend/webhooks/" false
fi

# system-07-billing should have backend/billing/ in its paths.
if grep -q "  - backend/billing/" \
    "$TMP_PROJECT/.specify/systems/system-07-billing/spec.md"; then
  assert "system-07-billing paths include backend/billing/" true
else
  assert "system-07-billing paths include backend/billing/" false
fi

# system-12-empty has no prose hints → skipped-no-proposal.
if grep -q '^---$' "$TMP_PROJECT/.specify/systems/system-12-empty/spec.md"; then
  assert "system-12-empty unchanged (no prose hints)" false
else
  assert "system-12-empty unchanged (no prose hints)" true
fi

# Summary report mentions counts.
if echo "$migrate_out" | grep -q "migrated:" \
   && echo "$migrate_out" | grep -q "skipped (no prose hints)"; then
  assert "summary report present" true
else
  assert "summary report present" false
fi

# --- Step 2: resolver tier 1 picks up the new paths ----------------------
echo "=== Step 2: path resolver tier 1 uses new frontmatter ==="

webhook_sys="$(python3 "$RESOLVER" backend/webhooks/dispatcher.py "$TMP_PROJECT" 2>/dev/null)"
[ "$webhook_sys" = "system-04-webhooks" ] \
  && assert "backend/webhooks/dispatcher.py → system-04-webhooks" true \
  || assert "backend/webhooks/dispatcher.py → system-04-webhooks (got $webhook_sys)" false

billing_sys="$(python3 "$RESOLVER" backend/billing/invoice.py "$TMP_PROJECT" 2>/dev/null)"
[ "$billing_sys" = "system-07-billing" ] \
  && assert "backend/billing/invoice.py → system-07-billing" true \
  || assert "backend/billing/invoice.py → system-07-billing (got $billing_sys)" false

# --- Step 3: re-run is a no-op -------------------------------------------
echo "=== Step 3: re-run is idempotent ==="

# Snapshot the spec contents before re-run.
shasum_before_4="$(shasum "$TMP_PROJECT/.specify/systems/system-04-webhooks/spec.md" | awk '{print $1}')"
shasum_before_7="$(shasum "$TMP_PROJECT/.specify/systems/system-07-billing/spec.md" | awk '{print $1}')"
shasum_before_12="$(shasum "$TMP_PROJECT/.specify/systems/system-12-empty/spec.md" | awk '{print $1}')"

rerun_out="$(python3 "$MIGRATE_PY" \
  --project-root "$TMP_PROJECT" \
  --auto-confirm --non-interactive 2>&1)"
rerun_status=$?
[ $rerun_status -eq 0 ] \
  && assert "re-run exited 0" true \
  || assert "re-run exited 0 (got $rerun_status)" false

shasum_after_4="$(shasum "$TMP_PROJECT/.specify/systems/system-04-webhooks/spec.md" | awk '{print $1}')"
shasum_after_7="$(shasum "$TMP_PROJECT/.specify/systems/system-07-billing/spec.md" | awk '{print $1}')"
shasum_after_12="$(shasum "$TMP_PROJECT/.specify/systems/system-12-empty/spec.md" | awk '{print $1}')"

[ "$shasum_before_4" = "$shasum_after_4" ] \
  && assert "system-04-webhooks unchanged on re-run" true \
  || assert "system-04-webhooks unchanged on re-run" false
[ "$shasum_before_7" = "$shasum_after_7" ] \
  && assert "system-07-billing unchanged on re-run" true \
  || assert "system-07-billing unchanged on re-run" false
[ "$shasum_before_12" = "$shasum_after_12" ] \
  && assert "system-12-empty unchanged on re-run" true \
  || assert "system-12-empty unchanged on re-run" false

# Summary on re-run should show migrated=0, skipped (already)=2 (or more).
if echo "$rerun_out" | grep -E "skipped \(already has paths\):[[:space:]]+[1-9]" >/dev/null; then
  assert "re-run summary shows already-migrated count" true
else
  assert "re-run summary shows already-migrated count" false
fi

echo
echo "test_migration_paths: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
