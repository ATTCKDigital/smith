---
name: smith-update
description: Update Smith to the latest upstream version. Compares the installed commit SHA against https://github.com/ATTCKDigital/smith main, prompts to update if behind, and refreshes global install (~/.claude/skills, ~/.claude/hooks, ~/.smith) plus per-project artifacts (.specify/scripts, .claude/commands/smith.*, CLAUDE.md / constitution.md via migrate-templates, optional manifest sidecar bootstrap). Workflow-gate compliant.
---

# Smith — Update to Latest

End-to-end skill for keeping Smith up to date. Detects local-vs-upstream commit drift, prompts to update, and runs the existing installer plus per-project refresh steps when invoked inside a Smith-initialized project.

**Arguments:** $ARGUMENTS (no positional args; reserved for future flags like `--check` / `--no-project`)

## When to Use

- "is smith out of date?" / "update smith" / "let's update smith"
- After learning of a new Smith feature you want to adopt
- After an old project's `.smith/index/` was generated against an earlier manifest schema and needs regeneration

## Vault Logging

Throughout this action, log significant events to the vault session log. Read the session log path from `.smith/vault/.current-session`. If the file is missing or the vault is not initialized, skip all logging silently.

Format:

```
### [HH:MM:SS] /smith-update <event>

**User Request:**
> <verbatim user message that triggered this action>

**Synthesized Input:** <brief summary>
**Outcome:** <what happened>
**Artifacts:** <files created/modified>
**Systems affected:** smith-update (smith-repo distribution)
```

Log at: invocation, after version detection (with SHAs + commits-behind), after global update, after per-project update, on completion.

## Natural Language Triggers

If the user says any of these (or similar), treat as invoking this command:
- "update smith"
- "let's update smith"
- "is smith out of date"
- "smith is behind"
- "pull the latest smith"

---

## Phase 0: Activate Workflow Tracking (Workflow-Gate Compliance)

`/smith-update` writes many files: install.sh's destructive `cp -R` of skills, the version file, settings.json merge, per-project script copies, etc. The PreToolUse workflow-gate hook (PR #20) would deny all of these without an active marker. So create the marker first.

**Skip if no `.smith/` directory exists in the current working directory** (the gate naturally exits silent in that case per PR #20, so no marker is needed). Otherwise:

```bash
TS=$(date -u +"%Y-%m-%dT%H-%M-%SZ")
PROJECT_DIR=$(pwd)
if [ -d "$PROJECT_DIR/.smith" ]; then
    mkdir -p "$PROJECT_DIR/.smith/vault/active-workflows"
    cat > "$PROJECT_DIR/.smith/vault/active-workflows/update-${TS}.yaml" << EOF
workflow: smith-update
feature: smith-version-sync
branch: $(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)
started: ${TS//-/:}
EOF
    # remember marker path for cleanup at end
    MARKER_PATH="$PROJECT_DIR/.smith/vault/active-workflows/update-${TS}.yaml"
fi
```

The marker is removed in Phase 6 cleanup (or on exit-with-no-changes paths). Use the shipped helper so it works under a `Bash(rm:*)` deny rule:

```bash
[ -n "${MARKER_PATH:-}" ] && [ -f "$MARKER_PATH" ] && \
    "$PROJECT_DIR/.specify/scripts/bash/clear-active-workflow.sh" "update-${TS}" 2>/dev/null || true
```

---

## Phase 1: Detect Upstream and Installed Versions

```bash
UPSTREAM_REMOTE="https://github.com/ATTCKDigital/smith.git"
SMITH_HOME="$HOME/.smith"
VERSION_FILE="$SMITH_HOME/.installed-version"

# Upstream SHA (network call — graceful on failure per Q4)
UPSTREAM_OUT=$(git ls-remote "$UPSTREAM_REMOTE" refs/heads/main 2>&1)
if [ $? -ne 0 ]; then
    echo "Unable to reach upstream — $UPSTREAM_OUT" >&2
    # cleanup marker, exit cleanly
    exit 0
fi
UPSTREAM_SHA=$(echo "$UPSTREAM_OUT" | awk '{print $1}')

# Installed SHA (per Q2-D: handle absent file by establishing baseline)
if [ -f "$VERSION_FILE" ]; then
    INSTALLED_SHA=$(cat "$VERSION_FILE" | tr -d ' \n\r')
else
    # First invocation since /smith-update shipped. Establish baseline silently.
    mkdir -p "$SMITH_HOME"
    echo "$UPSTREAM_SHA" > "$VERSION_FILE"
    echo "Smith is up to date — version baseline established at ${UPSTREAM_SHA:0:7}."
    # cleanup marker, exit
    exit 0
fi
```

## Phase 2: Compute Commits-Behind

Per Q5-A: `gh` first, shallow-clone fallback.

```bash
COMMITS_BEHIND=""
if command -v gh >/dev/null 2>&1; then
    COMMITS_BEHIND=$(gh api "repos/ATTCKDigital/smith/compare/${INSTALLED_SHA}...${UPSTREAM_SHA}" --jq '.ahead_by' 2>/dev/null)
fi

if [ -z "$COMMITS_BEHIND" ] || ! [[ "$COMMITS_BEHIND" =~ ^[0-9]+$ ]]; then
    # Fallback: shallow-clone the upstream and use git rev-list --count.
    TMPCLONE=$(mktemp -d -t smith-update-XXXXXX)
    trap 'rm -rf "$TMPCLONE"' EXIT  # extended at Phase 6 to include marker cleanup
    if ! git clone --quiet "$UPSTREAM_REMOTE" "$TMPCLONE/smith" 2>/dev/null; then
        echo "Unable to reach upstream — clone failed." >&2
        exit 0
    fi
    COMMITS_BEHIND=$(git -C "$TMPCLONE/smith" rev-list --count "${INSTALLED_SHA}..${UPSTREAM_SHA}" 2>/dev/null || echo "?")
fi

# Up-to-date short-circuit
if [ "$COMMITS_BEHIND" = "0" ]; then
    echo "Smith is up to date (commit ${UPSTREAM_SHA:0:7})."
    exit 0
fi

# Prompt
echo "Smith is $COMMITS_BEHIND commits behind. Update? (y/n)"
read -r REPLY
case "$REPLY" in
    [yY]|[yY][eE][sS]) ;;
    *) echo "Update declined."; exit 0 ;;
esac
```

## Phase 3: Snapshot (Q7-A Rollback Safety)

Before any destructive work, snapshot the global install state. On non-zero exit from install.sh, restore.

```bash
BACKUP_ROOT="$SMITH_HOME/.backups"
BACKUP_DIR="$BACKUP_ROOT/update-${TS}"
mkdir -p "$BACKUP_DIR"

# Snapshot the three writable areas
cp -R "$HOME/.claude/skills" "$BACKUP_DIR/skills" 2>/dev/null || true
cp -R "$HOME/.claude/hooks"  "$BACKUP_DIR/hooks"  2>/dev/null || true
cp    "$HOME/.claude/settings.json" "$BACKUP_DIR/settings.json" 2>/dev/null || true

# GC: keep last 3 (Q7-A keep-last-N policy)
ls -t "$BACKUP_ROOT" 2>/dev/null | tail -n +4 | while read -r old; do
    rm -rf "$BACKUP_ROOT/$old"
done

# Restore function — invoked if install.sh fails
restore_snapshot() {
    echo "Update failed — restoring from $BACKUP_DIR" >&2
    rm -rf "$HOME/.claude/skills" "$HOME/.claude/hooks"
    cp -R "$BACKUP_DIR/skills" "$HOME/.claude/skills" 2>/dev/null || true
    cp -R "$BACKUP_DIR/hooks"  "$HOME/.claude/hooks"  2>/dev/null || true
    cp    "$BACKUP_DIR/settings.json" "$HOME/.claude/settings.json" 2>/dev/null || true
}
```

## Phase 4: Global Update

Clone smith-repo to a temp dir (or reuse the one from Phase 2's fallback), run installer, write version file.

```bash
if [ -z "${TMPCLONE:-}" ] || ! [ -d "$TMPCLONE/smith" ]; then
    TMPCLONE=$(mktemp -d -t smith-update-XXXXXX)
    trap 'rm -rf "$TMPCLONE"' EXIT
    git clone --quiet "$UPSTREAM_REMOTE" "$TMPCLONE/smith"
fi

# Q1-D settings.json dedupe BEFORE running install.sh, so the installer's
# jq merge doesn't compound onto existing duplicates. Dedupe ONLY Smith-owned
# hook entries (those referencing ~/.claude/hooks/<known-name>.sh).
"$TMPCLONE/smith/scripts/dedupe-settings.sh" "$HOME/.claude/settings.json" 2>/dev/null || true

# Run the installer
if ! "$TMPCLONE/smith/scripts/install.sh" -y; then
    restore_snapshot
    echo "install.sh failed. Restored from snapshot at $BACKUP_DIR." >&2
    exit 1
fi

# install.sh now writes $SMITH_HOME/.installed-version itself (this PR adds that),
# but write it again here defensively in case install.sh was pre-versioning.
echo "$UPSTREAM_SHA" > "$VERSION_FILE"
```

## Phase 5: Per-Project Update (Conditional)

Only runs if `$PROJECT_DIR/.smith/` exists. Refresh Smith-owned files; never touch user files; offer manifest bootstrap if `.smith/index/` is absent.

### 5.1 Refresh `.specify/scripts/bash/` and `.claude/commands/smith.*`

Smith-owned files. Safe to overwrite. **Detect orphans first (Q6-A + Q8-B unified pass).**

```bash
if [ -d "$PROJECT_DIR/.smith" ]; then
    # Collect orphans before copying new files.
    UPSTREAM_SCRIPTS="$TMPCLONE/smith/skills/smith/scripts"
    LOCAL_SCRIPTS="$PROJECT_DIR/.specify/scripts/bash"
    ORPHAN_SCRIPTS=()
    if [ -d "$LOCAL_SCRIPTS" ]; then
        for f in "$LOCAL_SCRIPTS"/*; do
            name=$(basename "$f")
            [ -f "$UPSTREAM_SCRIPTS/$name" ] || ORPHAN_SCRIPTS+=("$name")
        done
    fi

    UPSTREAM_CMDS="$TMPCLONE/smith/skills/smith/commands"
    LOCAL_CMDS="$PROJECT_DIR/.claude/commands"
    ORPHAN_CMDS=()
    if [ -d "$LOCAL_CMDS" ]; then
        for f in "$LOCAL_CMDS"/smith.*.md; do
            [ -e "$f" ] || continue
            name=$(basename "$f")
            [ -f "$UPSTREAM_CMDS/$name" ] || ORPHAN_CMDS+=("$name")
        done
    fi

    UPSTREAM_HOOKS="$TMPCLONE/smith/hooks"
    LOCAL_HOOKS="$HOME/.claude/hooks"
    ORPHAN_HOOKS=()
    if [ -d "$LOCAL_HOOKS" ]; then
        for f in "$LOCAL_HOOKS"/*.sh; do
            [ -e "$f" ] || continue
            name=$(basename "$f")
            [ -f "$UPSTREAM_HOOKS/$name" ] || ORPHAN_HOOKS+=("$name")
        done
    fi

    # Q6/Q8 unified orphan prompt (default = n)
    if [ ${#ORPHAN_SCRIPTS[@]} -gt 0 ] || [ ${#ORPHAN_CMDS[@]} -gt 0 ] || [ ${#ORPHAN_HOOKS[@]} -gt 0 ]; then
        echo ""
        echo "Orphaned Smith-owned files detected (no longer in upstream):"
        [ ${#ORPHAN_HOOKS[@]}   -gt 0 ] && printf "  hooks:   %s\n" "${ORPHAN_HOOKS[@]}"
        [ ${#ORPHAN_SCRIPTS[@]} -gt 0 ] && printf "  scripts: %s\n" "${ORPHAN_SCRIPTS[@]}"
        [ ${#ORPHAN_CMDS[@]}    -gt 0 ] && printf "  commands: %s\n" "${ORPHAN_CMDS[@]}"
        echo "Remove these? (y/N)"
        read -r REPLY
        case "$REPLY" in
            [yY]|[yY][eE][sS])
                for n in "${ORPHAN_HOOKS[@]}";   do rm -f "$LOCAL_HOOKS/$n";   done
                for n in "${ORPHAN_SCRIPTS[@]}"; do rm -f "$LOCAL_SCRIPTS/$n"; done
                for n in "${ORPHAN_CMDS[@]}";    do rm -f "$LOCAL_CMDS/$n";    done
                ;;
            *) echo "Keeping orphaned files." ;;
        esac
    fi

    # Refresh Smith-owned files (touch only smith.*.md in .claude/commands per Q8-B)
    if [ -d "$UPSTREAM_SCRIPTS" ] && [ -d "$LOCAL_SCRIPTS" ]; then
        cp "$UPSTREAM_SCRIPTS"/*.sh "$LOCAL_SCRIPTS/" 2>/dev/null || true
        chmod +x "$LOCAL_SCRIPTS"/*.sh
    fi
    if [ -d "$UPSTREAM_CMDS" ] && [ -d "$LOCAL_CMDS" ]; then
        cp "$UPSTREAM_CMDS"/smith.*.md "$LOCAL_CMDS/" 2>/dev/null || true
    fi
fi
```

### 5.2 Run `/smith-index --migrate-templates`

Non-destructively merge new template sections into `CLAUDE.md` and `constitution.md`. Invoke as a sub-action of this skill.

```bash
if [ -d "$PROJECT_DIR/.smith" ]; then
    # Invoke /smith-index --migrate-templates as a Claude Code skill invocation
    # (the parent assistant runs this; not shellable from here directly).
    # See "Invoking sub-skills" note in the Key Rules section below.
    echo "Running /smith-index --migrate-templates..."
fi
```

**Note**: bash can't directly invoke another Claude skill. The PARENT ASSISTANT (the one running this skill) must invoke `/smith-index --migrate-templates` as a Claude tool call after the bash block above echoes its placeholder. This is the only sub-skill invocation in `/smith-update`.

### 5.3 Q9-B — Schema Version Check + Regeneration Prompt

```bash
if [ -d "$PROJECT_DIR/.smith/index" ]; then
    UPSTREAM_SCHEMA_VERSION=$(cat "$TMPCLONE/smith/scripts/parsers/meta_schema_version.txt" 2>/dev/null | tr -d ' \n\r')
    LOCAL_SCHEMA_VERSION=$(cat "$PROJECT_DIR/.smith/index/.schema-version" 2>/dev/null | tr -d ' \n\r')
    LOCAL_SCHEMA_VERSION="${LOCAL_SCHEMA_VERSION:-1}"  # absent → assume legacy v1

    if [ -n "$UPSTREAM_SCHEMA_VERSION" ] && [ "$UPSTREAM_SCHEMA_VERSION" != "$LOCAL_SCHEMA_VERSION" ]; then
        echo ""
        echo "Smith manifest schema mismatch:"
        echo "  Local:    v${LOCAL_SCHEMA_VERSION}"
        echo "  Upstream: v${UPSTREAM_SCHEMA_VERSION}"
        echo "Regenerate the manifest? (y/N) — runs /smith-index to refresh all .meta files."
        read -r REPLY
        case "$REPLY" in
            [yY]|[yY][eE][sS])
                # Parent assistant runs /smith-index here
                echo "Running /smith-index..."
                ;;
            *) echo "Keeping current manifest. You can regenerate later with /smith-index." ;;
        esac
    fi
fi
```

### 5.4 Manifest Sidecar Bootstrap Prompt (Q3-B)

If `.smith/index/` doesn't exist at all (project predates manifest system, PR #19), offer the bootstrap.

```bash
if [ -d "$PROJECT_DIR/.smith" ] && ! [ -d "$PROJECT_DIR/.smith/index" ]; then
    echo ""
    echo "Smith manifest sidecar is missing for this project. Bootstrap now?"
    echo "  (1) Structural only — fast, runs /smith-index"
    echo "  (2) Structural + LLM descriptions — slow, runs /smith-index --describe"
    echo "  (3) Defer — skip (you can run /smith-index manually later)"
    echo "Default: 3 (defer)"
    read -r REPLY
    case "$REPLY" in
        1) echo "Running /smith-index..." ;;             # parent assistant invokes
        2) echo "Running /smith-index --describe..." ;;  # parent assistant invokes
        *) echo "Deferred. Run /smith-index when ready." ;;
    esac
fi
```

### 5.5 Refresh `.gitignore` / `.gitattributes` Policy (Feature 36)

Re-merge the canonical team-shareable vault & index policy into the project-root
`.gitignore` and `.gitattributes`, idempotently, using the same sentinel logic as
`/smith` init. This is **project-config**, not vault data — merging managed lines in
the project-root `.gitignore`/`.gitattributes` does NOT violate the
"NEVER touch `.smith/vault/`" rule (which protects vault *data*: bank, ledger,
sessions, queue, agents, todo). Confirmed permitted for this step.

Source templates (installed copy first, repo-dev clone fallback):
- `$TMPCLONE/smith/skills/smith-index/templates/.gitignore-smith-additions`
  (or installed `~/.claude/skills/smith-index/templates/.gitignore-smith-additions`)
- `$TMPCLONE/smith/skills/smith-index/templates/.gitattributes-smith-additions`

```bash
if [ -d "$PROJECT_DIR/.smith" ]; then
    SMITH_TPL_DIR="$TMPCLONE/smith/skills/smith-index/templates"
    [ -f "$SMITH_TPL_DIR/.gitignore-smith-additions" ] || SMITH_TPL_DIR="$HOME/.claude/skills/smith-index/templates"

    # Q4-A: WARN (do not remove) on known-conflicting bare ignore lines that sit
    # OUTSIDE the sentinels and shadow the now-committed shared paths.
    GI="$PROJECT_DIR/.gitignore"
    if [ -f "$GI" ]; then
        # Strip the managed sentinel region first, then scan the remainder.
        OUTSIDE=$(awk '
            /# >>> smith-gitignore-policy >>>/ {inblk=1}
            !inblk {print}
            /# <<< smith-gitignore-policy <<</ {inblk=0}
        ' "$GI")
        for bad in '.smith/' '.smith/index/' '.smith/index/files/' '.smith/index/systems/'; do
            if printf '%s\n' "$OUTSIDE" | grep -qxF "$bad"; then
                LINE=$(grep -nxF "$bad" "$GI" | head -1 | cut -d: -f1)
                echo ""
                echo "WARNING: $GI line $LINE contains a bare '$bad' ignore OUTSIDE the Smith"
                echo "         sentinels. This shadows the now-committed shared paths"
                echo "         (manifest, .meta describe layer, ledger, bank, agents, sessions)."
                echo "         Smith will NOT remove it automatically. Remove it manually so the"
                echo "         shared Smith artifacts can be committed."
            fi
        done
    fi

    # Idempotent sentinel replace-or-append (same contract as /smith init §4.7).
    python3 - "$SMITH_TPL_DIR" "$PROJECT_DIR" <<'PYEOF'
import sys, pathlib
tpl_dir = pathlib.Path(sys.argv[1]); root = pathlib.Path(sys.argv[2])
def merge(target_path, tpl_path, open_marker, close_marker):
    tpl = pathlib.Path(tpl_path)
    if not tpl.exists():
        print(f"WARNING: template not found: {tpl_path} — skipping"); return
    block = tpl.read_text().rstrip("\n") + "\n"
    target = pathlib.Path(target_path)
    existing = target.read_text() if target.exists() else ""
    if open_marker in existing and close_marker in existing:
        pre = existing.split(open_marker, 1)[0]
        post = existing.split(close_marker, 1)[1]
        new = pre.rstrip("\n") + ("\n\n" if pre.strip() else "") + block + post.lstrip("\n")
        action = "refreshed"
    else:
        sep = "" if (not existing or existing.endswith("\n\n")) else ("\n" if existing.endswith("\n") else "\n\n")
        new = existing + sep + block
        action = "appended"
    target.write_text(new)
    print(f"{action}: {open_marker.split()[1]} in {target}")
merge(root / ".gitignore", tpl_dir / ".gitignore-smith-additions",
      "# >>> smith-gitignore-policy >>>", "# <<< smith-gitignore-policy <<<")
merge(root / ".gitattributes", tpl_dir / ".gitattributes-smith-additions",
      "# >>> smith-gitattributes-policy >>>", "# <<< smith-gitattributes-policy <<<")
PYEOF
fi
```

Per Q4-A the merge only manages the region BETWEEN the sentinels and never deletes
user-authored lines; the warning above is the safe nudge for the operator to clean up
a stale blanket ignore by hand.

## Phase 6: Cleanup

```bash
# Clean up temp clone (also handled by EXIT trap)
[ -n "${TMPCLONE:-}" ] && rm -rf "$TMPCLONE"

# Clear active-workflow marker
if [ -n "${MARKER_PATH:-}" ] && [ -f "$MARKER_PATH" ]; then
    "$PROJECT_DIR/.specify/scripts/bash/clear-active-workflow.sh" "update-${TS}" 2>/dev/null || rm -f "$MARKER_PATH"
fi

# Summary
echo ""
echo "Smith updated to ${UPSTREAM_SHA:0:7}."
echo "  Skills:       refreshed in ~/.claude/skills/"
echo "  Hooks:        refreshed in ~/.claude/hooks/"
echo "  Scheduler:    refreshed in ~/.smith/scheduler/"
[ -d "$PROJECT_DIR/.smith" ] && echo "  Per-project:  .specify/scripts and .claude/commands/smith.* refreshed"
[ -d "$PROJECT_DIR/.smith" ] && echo "  Git policy:   .gitignore/.gitattributes Smith policy block refreshed"
echo "  Snapshot:     $BACKUP_DIR (delete after confirming the update works)"
```

---

## Invoking Sub-Skills

`/smith-update` orchestrates two other skills as sub-actions:

1. **`/smith-index --migrate-templates`** — runs after the global update in any Smith-initialized project (Phase 5.2)
2. **`/smith-index` or `/smith-index --describe`** — runs only if Phase 5.4's bootstrap prompt is accepted

When the parent assistant runs `/smith-update`, it should treat the bash blocks above as the orchestration backbone and invoke the sub-skills via Claude Code's Skill tool at the marked points. The bash blocks emit `Running /smith-index...` placeholders to make the orchestration boundary visible in the session log.

## Key Rules

- **NEVER touch `.smith/vault/`** — user data is sacred (vault is the bank, ledger, sessions, queue, agents, todo — all user-owned). This protects vault *data*; merging the managed Smith policy region in the project-root `.gitignore`/`.gitattributes` (Phase 5.5) is project-config, not vault data, and is permitted.
- **NEVER touch project source code** — only `.specify/scripts/`, `.claude/commands/smith.*`, `CLAUDE.md` (via migrate-templates), `constitution.md` (via migrate-templates), `.smith/index/` (only on explicit prompt)
- **Active-workflow marker must be created BEFORE any file write** (workflow-gate compliance)
- **Snapshot before destructive work** — if `install.sh` fails partway, restore from snapshot
- **Default-defer on LLM-heavy paths** — Phase 5.4's bootstrap prompt defaults to (3); the schema-regen prompt in 5.3 defaults to (n)
- **Settings.json dedupe touches only Smith-owned hook entries** — never modify user-added entries (Q1-D)
- **`python3` not `python`** (Smith convention, per Rule 6 in `~/.claude/CLAUDE.md`)
