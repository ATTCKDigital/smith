#!/usr/bin/env bash
# subagent-vault-writeback.sh
# Event: SubagentStop
# Scope: Sub-agents only
#
# Writes sub-agent findings to .smith/vault/agents/<type>/<identifier>.md
# and appends metrics to the current session log.
#
# Metrics (total_tokens, tool_uses, duration_ms) are extracted from the
# sub-agent's sidechain transcript at:
#   ~/.claude/projects/<project>/<session_id>/subagents/agent-<id>.jsonl
#
# The SubagentStop payload only contains session_id, transcript_path, cwd,
# hook_event_name, stop_hook_active, reason — it does NOT include agent_id,
# model, or usage. We identify the sub-agent that just stopped by selecting
# the most-recently-modified transcript in the session's subagents/ directory.
# This is reliable for sequential sub-agents; for parallel fan-outs each
# SubagentStop fires once per sub-agent in completion order, so aggregated
# totals are always correct even if per-invocation pairing may shift.
#
# Type/Model are logged by the parent skill at invocation time (see
# smith-new/bugfix/debug/build pre-invocation logging), so this hook only
# appends the metrics block to the session log to avoid duplication. The
# per-agent findings file still records Model (from sidechain) and task
# description for later audit.

set -euo pipefail

INPUT=$(cat)

VAULT_DIR="${CLAUDE_PROJECT_DIR:-.}/.smith/vault"

HOOK_INPUT="$INPUT" VAULT_DIR="$VAULT_DIR" python3 <<'PYEOF'
import os
import sys
import json
import glob
from datetime import datetime


def parse_ts(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00'))


def classify_agent(description, identifier):
    text = f"{description} {identifier}".lower()
    rules = [
        ('image-analysis', ('image', 'screenshot', 'visual')),
        ('code-review',    ('review', 'architect', 'audit')),
        ('implementation', ('implement', 'build', 'write', 'create', 'fix')),
        ('exploration',    ('search', 'explore', 'find', 'research', 'read')),
        ('testing',        ('test', 'qa', 'quality')),
    ]
    for agent_type, keywords in rules:
        if any(k in text for k in keywords):
            return agent_type
    return 'general'


def safe_filename(s, max_len=100):
    import re
    s = re.sub(r'[^a-zA-Z0-9._-]', '-', s)[:max_len]
    return s or 'unknown'


def main():
    try:
        data = json.loads(os.environ.get('HOOK_INPUT', '{}'))
    except json.JSONDecodeError:
        return

    vault_dir = os.environ.get('VAULT_DIR', '.smith/vault')
    session_id = data.get('session_id', '')
    transcript_path = data.get('transcript_path', '')
    description = data.get('description', '')

    # Best-effort identifier from payload (rarely populated by Claude Code)
    identifier = data.get('agent_name') or data.get('identifier') or ''

    if not session_id or not transcript_path:
        return

    # Sub-agent transcripts live at <project_dir>/<session_id>/subagents/agent-<id>.jsonl
    project_dir = os.path.dirname(transcript_path)
    subagents_dir = os.path.join(project_dir, session_id, 'subagents')

    if not os.path.isdir(subagents_dir):
        return

    # Pick the most-recently-modified sidechain transcript.
    candidates = glob.glob(os.path.join(subagents_dir, 'agent-*.jsonl'))
    if not candidates:
        return
    candidates.sort(key=os.path.getmtime, reverse=True)
    sidechain_path = candidates[0]

    agent_id = os.path.basename(sidechain_path).replace('agent-', '').replace('.jsonl', '')

    # Aggregate usage across all sub-agent turns.
    model = 'unknown'
    total_input = total_output = total_cache_create = total_cache_read = 0
    tool_uses = 0
    first_ts = last_ts = None
    last_assistant_text = ''

    try:
        with open(sidechain_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ts = entry.get('timestamp')
                if ts:
                    if first_ts is None:
                        first_ts = ts
                    last_ts = ts

                msg = entry.get('message') or {}
                if msg.get('model'):
                    model = msg['model']

                usage = msg.get('usage') or {}
                total_input += usage.get('input_tokens') or 0
                total_output += usage.get('output_tokens') or 0
                total_cache_create += usage.get('cache_creation_input_tokens') or 0
                total_cache_read += usage.get('cache_read_input_tokens') or 0

                content = msg.get('content') or []
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get('type') == 'tool_use':
                            tool_uses += 1
                        elif block.get('type') == 'text' and entry.get('type') == 'assistant':
                            txt = block.get('text') or ''
                            if txt:
                                last_assistant_text = txt
    except OSError:
        return

    total_tokens = total_input + total_output + total_cache_create + total_cache_read

    duration_ms = 0
    if first_ts and last_ts:
        try:
            duration_ms = int((parse_ts(last_ts) - parse_ts(first_ts)).total_seconds() * 1000)
        except ValueError:
            duration_ms = 0

    if not identifier:
        identifier = agent_id

    findings = last_assistant_text
    if len(findings) > 4000:
        findings = findings[:4000] + '...[truncated]'
    if not findings:
        findings = 'No findings captured.'

    # Write per-agent findings file
    agent_type = classify_agent(description, identifier)
    agents_dir = os.path.join(vault_dir, 'agents', agent_type)
    os.makedirs(agents_dir, exist_ok=True)
    agent_file = os.path.join(agents_dir, f'{safe_filename(identifier)}.md')

    from datetime import timezone
    utcnow = datetime.now(timezone.utc)
    now_iso = utcnow.strftime('%Y-%m-%dT%H:%M:%S')
    now_time = utcnow.strftime('%H:%M:%S')

    with open(agent_file, 'a', encoding='utf-8') as f:
        f.write(f"\n### Invocation — {now_iso}\n\n")
        f.write(f"**Task:** {description}\n")
        f.write(f"**Model:** {model}\n")
        f.write(f"**Metrics:** tokens:{total_tokens} tools:{tool_uses} duration:{duration_ms}ms\n\n")
        f.write("**Findings:**\n")
        f.write(findings)
        f.write("\n\n---\n")

    # Append metrics-only entry to session log (parent skill logs Type/Model at invocation)
    current_session_ptr = os.path.join(vault_dir, '.current-session')
    if os.path.isfile(current_session_ptr):
        try:
            with open(current_session_ptr, 'r', encoding='utf-8') as f:
                session_file = f.read().strip()
            if session_file and os.path.isfile(session_file):
                with open(session_file, 'a', encoding='utf-8') as f:
                    f.write(f"\n### [{now_time}] Subagent completed\n\n")
                    f.write("**Metrics:**\n")
                    f.write(f"- total_tokens: {total_tokens}\n")
                    f.write(f"- tool_uses: {tool_uses}\n")
                    f.write(f"- duration_ms: {duration_ms}\n\n")
        except OSError:
            pass


main()
PYEOF

exit 0
