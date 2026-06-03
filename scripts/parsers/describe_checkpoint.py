#!/usr/bin/env python3
"""
describe_checkpoint.py — Rule-4 JSONL log + checkpoint state for
/smith-index --describe (v3 spec/23-task-llm-backend §A3).

Subcommands:

  append    --log <jsonl-path> --record '<json>'
            Append one record line to a JSONL log.

  save      --path <state-path> --processed <rel_path>
            Append a single rel_path to the checkpoint state file's
            `processed_files` list (creating the file with defaults if
            missing).

  load      --path <state-path>
            Print the checkpoint state JSON to stdout (empty object if
            absent).

  load-completed --log-dir <dir> --state <state-path>
            Print a JSON array of completed rel_paths (union of state
            file + JSONL `ok` records). Used by --resume.

  summary   --log <jsonl-path> --start-iso <iso>
            Print the Rule-4 summary line to stdout. Format:
              /smith-index --describe: N files described
              (succeeded=S failed=F skipped=K) in T.Ts

Stdlib only. Importable as a module.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

CHECKPOINT_VERSION = 3


def _iso_now_ms() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _read_log_records(log_path: Path):
    if not log_path.exists():
        return
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


# --- append ---------------------------------------------------------------


def append_record(log_path: Path, record: dict) -> None:
    """Append one JSON record to the JSONL log. Adds a default timestamp
    if missing."""
    if "timestamp" not in record:
        record = dict(record)
        record["timestamp"] = _iso_now_ms()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _cmd_append(args: argparse.Namespace) -> int:
    try:
        record = json.loads(args.record)
    except json.JSONDecodeError as e:
        print(f"describe_checkpoint: --record is not valid JSON: {e}", file=sys.stderr)
        return 2
    if not isinstance(record, dict):
        print("describe_checkpoint: --record must be a JSON object", file=sys.stderr)
        return 2
    append_record(Path(args.log), record)
    return 0


# --- save -----------------------------------------------------------------


def save_processed(state_path: Path, rel_path: str, *, backend: str = "task") -> None:
    """Append rel_path to the processed_files list in the checkpoint
    state file (creating the file if missing). Idempotent: adding a
    rel_path that's already present is a no-op."""
    state = _load_state(state_path) or {
        "version": CHECKPOINT_VERSION,
        "started_at": _iso_now_ms(),
        "last_batch_index": 0,
        "backend": backend,
        "processed_files": [],
    }
    processed = list(state.get("processed_files") or [])
    if rel_path not in processed:
        processed.append(rel_path)
    state["processed_files"] = processed
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def _cmd_save(args: argparse.Namespace) -> int:
    save_processed(Path(args.path), args.processed, backend=args.backend)
    return 0


# --- load -----------------------------------------------------------------


def _load_state(state_path: Path):
    if not state_path.exists():
        return None
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _cmd_load(args: argparse.Namespace) -> int:
    state = _load_state(Path(args.path)) or {}
    print(json.dumps(state, indent=2))
    return 0


# --- load-completed -------------------------------------------------------


def load_completed(log_dir: Path, state_path: Path) -> list[str]:
    """Return the union of (state.processed_files) and (JSONL ok records)
    across every smith-index-describe-*.jsonl file in `log_dir`.
    Used by --resume."""
    completed: set[str] = set()
    state = _load_state(state_path) or {}
    for p in state.get("processed_files") or []:
        completed.add(str(p))

    if log_dir.exists() and log_dir.is_dir():
        for log_file in sorted(log_dir.glob("smith-index-describe-*.jsonl")):
            for rec in _read_log_records(log_file):
                if rec.get("stage") == "describe" and rec.get("status") == "ok":
                    item = rec.get("item_id")
                    if item:
                        completed.add(str(item))
    return sorted(completed)


def _cmd_load_completed(args: argparse.Namespace) -> int:
    completed = load_completed(Path(args.log_dir), Path(args.state))
    print(json.dumps(completed))
    return 0


# --- summary --------------------------------------------------------------


def summary(log_path: Path, start_iso: str) -> str:
    succeeded = 0
    failed = 0
    skipped = 0
    total = 0
    for rec in _read_log_records(log_path):
        total += 1
        status = rec.get("status")
        if status == "ok":
            succeeded += 1
        elif status == "failed":
            failed += 1
        elif status == "skipped":
            skipped += 1

    try:
        start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    except ValueError:
        start_dt = None
    if start_dt is not None:
        elapsed = (datetime.now(timezone.utc) - start_dt).total_seconds()
        elapsed_s = f"{elapsed:.1f}s"
    else:
        elapsed_s = "unknown"

    return (
        f"/smith-index --describe: {total} files described "
        f"(succeeded={succeeded} failed={failed} skipped={skipped}) "
        f"in {elapsed_s}"
    )


def _cmd_summary(args: argparse.Namespace) -> int:
    print(summary(Path(args.log), args.start_iso))
    return 0


# --- CLI plumbing ---------------------------------------------------------


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="describe_checkpoint")
    sub = parser.add_subparsers(dest="cmd")

    ap_append = sub.add_parser("append", help="Append one JSONL record")
    ap_append.add_argument("--log", required=True)
    ap_append.add_argument("--record", required=True)
    ap_append.set_defaults(func=_cmd_append)

    ap_save = sub.add_parser("save", help="Add a rel_path to checkpoint state")
    ap_save.add_argument("--path", required=True)
    ap_save.add_argument("--processed", required=True)
    ap_save.add_argument("--backend", default="task")
    ap_save.set_defaults(func=_cmd_save)

    ap_load = sub.add_parser("load", help="Print checkpoint state JSON")
    ap_load.add_argument("--path", required=True)
    ap_load.set_defaults(func=_cmd_load)

    ap_lc = sub.add_parser(
        "load-completed", help="Print completed rel_paths (JSON array)"
    )
    ap_lc.add_argument("--log-dir", required=True)
    ap_lc.add_argument("--state", required=True)
    ap_lc.set_defaults(func=_cmd_load_completed)

    ap_sum = sub.add_parser("summary", help="Print Rule-4 summary line")
    ap_sum.add_argument("--log", required=True)
    ap_sum.add_argument("--start-iso", required=True)
    ap_sum.set_defaults(func=_cmd_summary)

    return parser


def main(argv: list[str]) -> int:
    parser = _build_argparser()
    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
