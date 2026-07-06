"""Workspace — per-run artifact layout under ~/Documents/smith-research/ (D2).

Owns path derivation, run.json read/write, and the macOS TCC probe write (S5).
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path


def slug_domain(domain: str) -> str:
    """Normalise a domain to a filesystem-safe slug (strip scheme/path/www)."""
    d = domain.strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = d.split("/")[0]
    d = re.sub(r"^www\.", "", d)
    d = re.sub(r"[^a-z0-9.-]", "-", d)
    return d


class Workspace:
    """A single research run's on-disk workspace."""

    SUBDIRS = (
        "pages",
        "raw_html",
        "screenshots",
        "background/serp",
        "background/reddit",
        "background/fetched",
        "logs",
    )

    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)

    # ---- construction ----

    @classmethod
    def create(cls, output_root: Path, domain: str, ts: str) -> "Workspace":
        """Create a fresh run workspace: <root>/<domain>/<ts>/."""
        run_dir = Path(output_root) / slug_domain(domain) / ts
        ws = cls(run_dir)
        ws.ensure()
        return ws

    @classmethod
    def latest(cls, output_root: Path, domain: str) -> "Workspace | None":
        """Return the most recent run workspace for a domain, or None."""
        base = Path(output_root) / slug_domain(domain)
        if not base.is_dir():
            return None
        runs = sorted((p for p in base.iterdir() if p.is_dir()), reverse=True)
        return cls(runs[0]) if runs else None

    def ensure(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        for sub in self.SUBDIRS:
            (self.run_dir / sub).mkdir(parents=True, exist_ok=True)

    def probe_write(self) -> bool:
        """Verify we can actually write here (macOS TCC/Documents prompt, S5)."""
        try:
            p = self.run_dir / ".write-probe"
            p.write_text("ok", encoding="utf-8")
            p.unlink()
            return True
        except OSError:
            return False

    # ---- paths ----

    @property
    def ledger_path(self) -> Path:
        return self.run_dir / "ledger.sqlite"

    @property
    def urls_path(self) -> Path:
        return self.run_dir / "urls.jsonl"

    @property
    def checkpoint_path(self) -> Path:
        return self.run_dir / "checkpoint.json"

    @property
    def report_path(self) -> Path:
        return self.run_dir / "report.md"

    @property
    def evidence_path(self) -> Path:
        return self.run_dir / "evidence.jsonl"

    @property
    def run_json_path(self) -> Path:
        return self.run_dir / "run.json"

    def logs_dir(self) -> Path:
        return self.run_dir / "logs"

    def page_md(self, url_sha1: str) -> Path:
        return self.run_dir / "pages" / f"{url_sha1}.md"

    def raw_html(self, url_sha1: str) -> Path:
        return self.run_dir / "raw_html" / f"{url_sha1}.html"

    def screenshot(self, url_sha1: str) -> Path:
        return self.run_dir / "screenshots" / f"{url_sha1}.png"

    # ---- run.json (run-level state, mirrors run_state; S3) ----

    def read_run_json(self) -> dict:
        if self.run_json_path.exists():
            return json.loads(self.run_json_path.read_text(encoding="utf-8"))
        return {}

    def write_run_json(self, data: dict) -> None:
        data = dict(data)
        data["updated_at"] = datetime.now(tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        tmp = self.run_json_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.run_json_path)


def now_ts() -> str:
    """Run-id timestamp: YYYYMMDD-HHMMSS (UTC)."""
    return datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
