#!/usr/bin/env bash
# test_smith_scheduler_audits_step.sh — integration test for the scheduler's
# audits step (feature 58-scheduled-audits, T002-T007/T009), dry-run only.
#
# Reuses tests/hooks/test_config_default_seed.sh's setup_project() fake-
# $HOME/fake-project fixture pattern (that file's lines 73-81): a mktemp -d
# project root plus a SEPARATE mktemp -d fake $HOME. smith-scheduler.sh
# hardcodes SMITH_DIR="$HOME/.smith" and its projects registry at
# "$HOME/.smith/projects.json" — without overriding $HOME this test would
# read/write the developer's real ~/.smith/, exactly the hazard
# test_config_default_seed.sh's fixture already isolates against.
#
# Only ever invoked with SMITH_AUDIT_DISPATCH_DRY_RUN=1 — never spawns a
# real `claude` process, no network activity, no billing (mirrors the
# queue-step scheduler's own no-live-invocation test convention).
#
# NFR-2: bash/zsh portable. Run:
#   bash tests/scheduler/test_smith_scheduler_audits_step.sh
#   zsh  tests/scheduler/test_smith_scheduler_audits_step.sh

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
SCHEDULER="$REPO/scheduler/smith-scheduler.sh"

if [ ! -f "$SCHEDULER" ]; then
    echo "FATAL: scheduler not found: $SCHEDULER" >&2
    exit 2
fi

# NFR-2: self-detects which shell is running *this* test file and invokes
# smith-scheduler.sh under that same interpreter throughout (mirrors
# tests/security/test_secret_scan.sh's bash/zsh-parity idiom) — so running
# this file under `zsh` gives the scheduler's new audits-step code real
# execution coverage under zsh, not just a `-n` syntax check.
if [ -n "${ZSH_VERSION:-}" ]; then
    DEFAULT_INTERPRETER="zsh"
else
    DEFAULT_INTERPRETER="bash"
fi
INTERPRETER_BIN=$(command -v "$DEFAULT_INTERPRETER")

PASS=0
FAIL=0
FAILED_NAMES=()

assert_log_contains() {
    local name="$1" log="$2" needle="$3"
    if grep -qF "$needle" "$log" 2>/dev/null; then
        PASS=$((PASS + 1))
        printf 'PASS  %s\n' "$name"
    else
        FAIL=$((FAIL + 1))
        FAILED_NAMES+=("$name")
        printf 'FAIL  %s\n  needle missing: %s\n  in: %s\n' "$name" "$needle" "$log"
        if [ -f "$log" ]; then
            echo "  --- log content ---"
            sed 's/^/  /' "$log"
        fi
    fi
}

assert_log_not_contains() {
    local name="$1" log="$2" needle="$3"
    if grep -qF "$needle" "$log" 2>/dev/null; then
        FAIL=$((FAIL + 1))
        FAILED_NAMES+=("$name")
        printf 'FAIL  %s\n  needle unexpectedly present: %s\n  in: %s\n' "$name" "$needle" "$log"
    else
        PASS=$((PASS + 1))
        printf 'PASS  %s\n' "$name"
    fi
}

assert_no_file() {
    local name="$1" file="$2"
    if [ -f "$file" ]; then
        FAIL=$((FAIL + 1))
        FAILED_NAMES+=("$name")
        printf 'FAIL  %s\n  unexpectedly present: %s\n' "$name" "$file"
    else
        PASS=$((PASS + 1))
        printf 'PASS  %s\n' "$name"
    fi
}

# setup_fixture <enabled> <cadence_days> <state_variant>
#   state_variant: "due" | "not_due" | "absent" | "corrupt"
# Prints "<project>\n<fake_home>\n<log_file>" — caller cleans both dirs up.
setup_fixture() {
    local enabled="$1" cadence="$2" state_variant="$3"
    local project home vault

    project=$(mktemp -d -t sched-audits-project.XXXXXX)
    home=$(mktemp -d -t sched-audits-home.XXXXXX)
    vault="$project/.smith/vault"
    mkdir -p "$vault"

    cat > "$project/.smith/config.json" <<EOF
{
  "scheduled_audits": {
    "enabled": $enabled,
    "cadence_days": $cadence,
    "subsets": ["requirements", "codequality", "security", "dependencies", "workflow"],
    "systems": "--all",
    "skip_pdf": true
  }
}
EOF

    case "$state_variant" in
        due)
            # last_run.date far enough in the past to always be due,
            # regardless of cadence_days used in these tests.
            cat > "$vault/.scheduled-audits-state.json" <<'EOF'
{"last_run": {"date": "2020-01-01", "timestamp": "2020-01-01T00:00:00Z", "subsets": ["requirements"], "report_path": "specs/audits/2020-01-01-scheduled-requirements.md", "severity_totals": {"critical": 0, "warning": 0, "info": 0}}}
EOF
            ;;
        not_due)
            # last_run.date = today → never due for any cadence_days >= 1
            # used by these tests.
            local today
            today=$(date +"%Y-%m-%d")
            cat > "$vault/.scheduled-audits-state.json" <<EOF
{"last_run": {"date": "$today", "timestamp": "${today}T00:00:00Z", "subsets": ["requirements"], "report_path": "specs/audits/${today}-scheduled-requirements.md", "severity_totals": {"critical": 0, "warning": 0, "info": 0}}}
EOF
            ;;
        absent)
            : # deliberately no state file — "never run" per FR-22
            ;;
        corrupt)
            printf '{not valid json at all' > "$vault/.scheduled-audits-state.json"
            ;;
        *)
            echo "setup_fixture: unknown state_variant '$state_variant'" >&2
            return 1
            ;;
    esac

    mkdir -p "$home/.smith"
    cat > "$home/.smith/projects.json" <<EOF
{
  "projects": [
    {"path": "$vault"}
  ]
}
EOF

    printf '%s\n%s\n%s\n' "$project" "$home" "$home/.smith/scheduler/scheduler.log"
}

run_scheduler_dry() {
    local home="$1"
    SMITH_SCHEDULER_ENABLED=1 SMITH_AUDIT_DISPATCH_DRY_RUN=1 HOME="$home" \
        "$INTERPRETER_BIN" "$SCHEDULER" >/dev/null 2>&1
}

cleanup() {
    local project="$1" home="$2"
    rm -rf "$project" "$home"
}

# read_fixture_paths <paths-blob-from-setup_fixture>
# Splits setup_fixture's newline-delimited "<project>\n<home>\n<log>" output
# into the bare (caller-scope) variables every test block below reads —
# project/home/log/pname — mirroring how each block already used them before
# this was extracted. Deliberately not `local`: every call site here is a
# top-level `{ ... }` block, not a function, so these must land in the
# caller's own scope exactly as the inlined version did.
read_fixture_paths() {
    local paths="$1"
    project=$(echo "$paths" | sed -n 1p)
    home=$(echo "$paths" | sed -n 2p)
    log=$(echo "$paths" | sed -n 3p)
    pname=$(basename "$project")
}

# ---------- 1: enabled + due (absent state, "never run") → dispatch ----------
{
    paths=$(setup_fixture true 7 absent)
    read_fixture_paths "$paths"

    run_scheduler_dry "$home"

    assert_log_contains "absent state (never run): planned dispatch logged" "$log" \
        "[dry-run] would dispatch audit: /smith-audit --all --scheduled requirements,codequality,security,dependencies,workflow (project: $pname, due=true)"
    assert_no_file "absent state: scheduler never writes .scheduled-audits-state.json" \
        "$project/.smith/vault/.scheduled-audits-state.json"

    cleanup "$project" "$home"
}

# ---------- 2: enabled + due (explicit stale last_run.date) → dispatch ----------
{
    paths=$(setup_fixture true 7 due)
    read_fixture_paths "$paths"

    run_scheduler_dry "$home"

    assert_log_contains "due state: planned dispatch logged" "$log" \
        "[dry-run] would dispatch audit: /smith-audit --all --scheduled requirements,codequality,security,dependencies,workflow (project: $pname, due=true)"

    cleanup "$project" "$home"
}

# ---------- 3: enabled + not due (last_run.date = today) → skip, no dispatch ----------
{
    paths=$(setup_fixture true 7 not_due)
    read_fixture_paths "$paths"

    run_scheduler_dry "$home"

    assert_log_contains "not-due state: skip reason logged" "$log" \
        "Audits: skipping $pname — not yet due, last run"
    assert_log_not_contains "not-due state: no dispatch logged" "$log" \
        "would dispatch audit"

    cleanup "$project" "$home"
}

# ---------- 4: disabled (enabled=false) → skip, no dispatch, no state read needed ----------
{
    paths=$(setup_fixture false 7 due)
    read_fixture_paths "$paths"

    run_scheduler_dry "$home"

    assert_log_contains "disabled: skip reason logged" "$log" \
        "Audits: skipping $pname — scheduled_audits disabled"
    assert_log_not_contains "disabled: no dispatch logged" "$log" \
        "would dispatch audit"

    cleanup "$project" "$home"
}

# ---------- 5: enabled + due but corrupt/unparseable state file → treated as never-run, dispatch ----------
{
    paths=$(setup_fixture true 7 corrupt)
    read_fixture_paths "$paths"

    run_scheduler_dry "$home"

    assert_log_contains "corrupt state: treated as never-run, dispatch logged" "$log" \
        "[dry-run] would dispatch audit: /smith-audit --all --scheduled requirements,codequality,security,dependencies,workflow (project: $pname, due=true)"

    cleanup "$project" "$home"
}

# ---------- 6: cadence_days=0 override → always due even with a fresh last_run.date ----------
{
    paths=$(setup_fixture true 0 not_due)
    read_fixture_paths "$paths"

    run_scheduler_dry "$home"

    assert_log_contains "cadence_days=0: due immediately, dispatch logged" "$log" \
        "[dry-run] would dispatch audit: /smith-audit --all --scheduled requirements,codequality,security,dependencies,workflow (project: $pname, due=true)"

    cleanup "$project" "$home"
}

# ---------- 7: never invokes a real claude process under dry-run ----------
{
    paths=$(setup_fixture true 7 due)
    read_fixture_paths "$paths"

    # A claude on PATH that would fail loudly (non-zero exit + marker file)
    # if the scheduler ever actually invoked it under dry-run.
    stub_dir=$(mktemp -d -t sched-audits-stub.XXXXXX)
    marker="$stub_dir/claude-was-invoked"
    cat > "$stub_dir/claude" <<EOF
#!/usr/bin/env bash
touch "$marker"
exit 1
EOF
    chmod +x "$stub_dir/claude"

    SMITH_SCHEDULER_ENABLED=1 SMITH_AUDIT_DISPATCH_DRY_RUN=1 HOME="$home" \
        PATH="$stub_dir:$PATH" "$INTERPRETER_BIN" "$SCHEDULER" >/dev/null 2>&1

    assert_no_file "dry-run: stub claude binary never invoked" "$marker"

    cleanup "$project" "$home"
    rm -rf "$stub_dir"
}

echo
echo "----------------------------------------------------------------------"
echo "Ran $((PASS + FAIL)) tests: $PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
    printf 'Failed:\n'
    for n in "${FAILED_NAMES[@]}"; do
        printf '  - %s\n' "$n"
    done
    exit 1
fi
