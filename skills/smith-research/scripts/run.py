#!/usr/bin/env python3
"""run.py — CLI entrypoint for the smith-research deterministic engine.

Every subcommand here is LLM-FREE (contracts/cli.md). LLM synthesis + verification
are driven by the SKILL.md orchestrator, which calls these subcommands.

Usage:
    python3 skills/smith-research/scripts/run.py <subcommand> [flags]

Run inside the skill-owned venv (SKILL.md Phase 0 activates it).
"""

import argparse
import json
import sys
from pathlib import Path

# Allow `python3 run.py` from anywhere (package dir is alongside this file).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from smith_research.config import ResearchConfig  # noqa: E402
from smith_research import prereqs  # noqa: E402
from smith_research.workspace import Workspace  # noqa: E402

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_PREREQ = 2
EXIT_NO_URLS = 3
EXIT_PARTIAL = 4


def _emit(obj: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(obj, default=str))
    else:
        for k, v in obj.items():
            print(f"{k}: {v}")


def _config_from_args(args) -> ResearchConfig:
    return ResearchConfig.from_env(
        qdrant_url=getattr(args, "qdrant_url", None),
        ollama_url=getattr(args, "ollama_url", None),
        embedding_model=getattr(args, "embedding_model", None),
        playwright_ws=getattr(args, "playwright_ws", None),
        domain=getattr(args, "domain", None),
        depth=getattr(args, "depth", None),
        politeness=getattr(args, "politeness", None),
        output_root=(
            Path(args.output_root).expanduser()
            if getattr(args, "output_root", None)
            else None
        ),
    )


# --------------------------------------------------------------------------
# check — verify prerequisites (FR-21). Exit 2 if any required prereq is down.
# --------------------------------------------------------------------------
def cmd_check(args) -> int:
    cfg = _config_from_args(args)
    results = prereqs.check_all(cfg, require_playwright=not args.no_playwright)
    payload = {
        "ok": all(r.ok for r in results),
        "checks": [
            {"name": r.name, "ok": r.ok, "detail": r.detail, "remedy": r.remedy}
            for r in results
        ],
    }
    _emit(payload, args.json)
    if not payload["ok"] and not args.json:
        print("\nRemediation:", file=sys.stderr)
        for r in results:
            if not r.ok:
                print(f"  [{r.name}] {r.remedy}", file=sys.stderr)
    return EXIT_OK if payload["ok"] else EXIT_PREREQ


# --------------------------------------------------------------------------
# status — summarise a run's workspace + phase (S3). Read-only.
# --------------------------------------------------------------------------
def cmd_status(args) -> int:
    cfg = _config_from_args(args)
    ws = (
        Workspace(Path(args.run_dir))
        if getattr(args, "run_dir", None)
        else Workspace.latest(cfg.output_root, args.domain)
    )
    if ws is None or not ws.run_dir.exists():
        _emit(
            {
                "found": False,
                "domain": args.domain,
                "output_root": str(cfg.output_root),
            },
            args.json,
        )
        return EXIT_OK
    run_json = ws.read_run_json()
    payload = {
        "found": True,
        "run_dir": str(ws.run_dir),
        "phase": run_json.get("phase", "unknown"),
        "section_status": run_json.get("section_status", {}),
        "has_report": ws.report_path.exists(),
        "has_ledger": ws.ledger_path.exists(),
    }
    # Ledger summary if present (P2 fills this in; guard import until then).
    try:
        from smith_research.ledger import Ledger  # noqa: E402

        if ws.ledger_path.exists():
            payload["ledger"] = Ledger(ws.ledger_path).status_summary()
    except ImportError:
        pass
    _emit(payload, args.json)
    return EXIT_OK


# --------------------------------------------------------------------------
# Pipeline subcommands — implemented across P1..P6. Each dispatches to its
# engine module. Kept as thin wrappers so run.py stays a router.
# --------------------------------------------------------------------------
def _dispatch(module_name: str, fn_name: str, args) -> int:
    import importlib

    try:
        mod = importlib.import_module(f"smith_research.{module_name}")
    except ImportError as exc:
        _emit({"error": f"{module_name} not yet available: {exc}"}, args.json)
        return EXIT_ERROR
    fn = getattr(mod, fn_name)
    return fn(args)


def cmd_discover(args):
    return _dispatch("discover", "run_cli", args)


def cmd_crawl(args):
    return _dispatch("crawler", "run_cli", args)


def cmd_index(args):
    return _dispatch("indexer", "run_cli", args)


def cmd_background(args):
    return _dispatch("bg_research", "run_cli", args)


def cmd_retrieve(args):
    return _dispatch("retrieval", "cli_retrieve", args)


def cmd_evidence(args):
    return _dispatch("retrieval", "cli_evidence_check", args)


def cmd_record(args):
    return _dispatch("retrieval", "cli_record_claim", args)


def cmd_verify(args):
    return _dispatch("verify_report", "run_cli", args)


def build_parser() -> argparse.ArgumentParser:
    # Shared global flags live on a parent parser so they are accepted BOTH
    # before and after the subcommand (argparse quirk: a top-parser optional
    # placed after the subcommand is otherwise "unrecognized").
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="machine-readable output")
    common.add_argument("--qdrant-url", dest="qdrant_url")
    common.add_argument("--ollama-url", dest="ollama_url")
    common.add_argument("--embedding-model", dest="embedding_model")
    common.add_argument("--playwright-ws", dest="playwright_ws")
    common.add_argument("--output-root", dest="output_root")
    common.add_argument("--run-dir", dest="run_dir")
    common.add_argument("--politeness", choices=["strict", "normal", "aggressive"])

    p = argparse.ArgumentParser(
        prog="smith-research", description=__doc__, parents=[common]
    )
    sub = p.add_subparsers(dest="command", required=True)

    def add(name, **kw):
        return sub.add_parser(name, parents=[common], **kw)

    c = add("check", help="verify prerequisites (exit 2 if down)")
    c.add_argument("--domain")
    c.add_argument(
        "--no-playwright", action="store_true", help="skip the Playwright server check"
    )
    c.set_defaults(func=cmd_check)

    s = add("status", help="summarise a run workspace")
    s.add_argument("--domain", required=True)
    s.set_defaults(func=cmd_status)

    d = add("discover", help="build the URL frontier")
    d.add_argument("--domain", required=True)
    d.set_defaults(func=cmd_discover)

    cr = add("crawl", help="crawl + extract every URL")
    cr.add_argument("--domain", required=True)
    cr.add_argument("--resume", action="store_true")
    cr.add_argument("--limit", type=int)
    cr.set_defaults(func=cmd_crawl)

    ix = add("index", help="chunk + embed + upsert to Qdrant")
    ix.add_argument("--domain", required=True)
    ix.add_argument("--resume", action="store_true")
    ix.set_defaults(func=cmd_index)

    bg = add("background", help="deep background research")
    bg.add_argument("--domain", required=True)
    bg.add_argument("--depth", choices=["quick", "standard", "thorough"])
    bg.add_argument("--topics", nargs="*")
    bg.set_defaults(func=cmd_background)

    rt = add("retrieve", help="semantic retrieval (read-only)")
    rt.add_argument("--domain", required=True)
    rt.add_argument("--query", required=True)
    rt.add_argument(
        "--collection", choices=["site", "background", "both"], default="both"
    )
    rt.add_argument("--topic")
    rt.add_argument("--k", type=int, default=8)
    rt.set_defaults(func=cmd_retrieve)

    ec = add("evidence-check", help="candidate chunks for a claim")
    ec.add_argument("--domain", required=True)
    ec.add_argument("--claim", required=True)
    ec.add_argument("--k", type=int)
    ec.set_defaults(func=cmd_evidence)

    rc = add("record-claim", help="persist a verified atomic claim")
    rc.add_argument("--domain", required=True)
    rc.add_argument("--section", required=True)
    rc.add_argument("--claim", required=True)
    rc.add_argument("--verdict", required=True)
    rc.add_argument("--source-urls", nargs="*", default=[])
    rc.add_argument("--chunk-ids", nargs="*", default=[])
    rc.add_argument("--chunk-texts", nargs="*", default=[])
    rc.add_argument("--source-tier", default="reputable_secondary")
    rc.set_defaults(func=cmd_record)

    vr = add(
        "verify-report", help="DETERMINISTIC gate: report ⊆ supported-claims"
    )
    vr.add_argument("--domain", required=True)
    vr.set_defaults(func=cmd_verify)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
