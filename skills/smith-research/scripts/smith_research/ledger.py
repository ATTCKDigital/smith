"""ledger.py — SQLite crawl-state ledger (net-new; replaces armory pg_store).

The ledger is the SOURCE OF TRUTH for resume. It records per-URL crawl state,
background sources, atomic claims, and run-level phase. Portable + self-contained
(Deviation D3, questions.md Q5). No LLM.

Schema mirrors data-model.md. Resume semantics (B3):
  done      = {ok, low_content}                    -> skip
  terminal  = done + {blocked, failed_terminal, skipped}  -> never re-attempt
  retryable = {pending, error}                      -> re-attempt until retry_count cap
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from smith_research.models_research import PageStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    url             TEXT PRIMARY KEY,
    source          TEXT,
    status          TEXT NOT NULL,
    http_status     INTEGER,
    content_sha256  TEXT,
    content_type    TEXT,
    title           TEXT,
    word_count      INTEGER,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    point_ids       TEXT,
    md_path         TEXT,
    html_path       TEXT,
    screenshot_path TEXT,
    error           TEXT,
    first_seen_at   TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pages_status ON pages(status);

CREATE TABLE IF NOT EXISTS background_sources (
    id            TEXT PRIMARY KEY,
    engine        TEXT NOT NULL,
    topic         TEXT NOT NULL,
    query         TEXT NOT NULL,
    url           TEXT,
    source_tier   TEXT NOT NULL,
    fetched_path  TEXT,
    point_id      TEXT,
    fetched_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_bg_topic ON background_sources(topic);

CREATE TABLE IF NOT EXISTS claims (
    id            TEXT PRIMARY KEY,
    section       TEXT NOT NULL,
    claim_text    TEXT NOT NULL,
    source_urls   TEXT NOT NULL,
    chunk_ids     TEXT NOT NULL,
    chunk_texts   TEXT NOT NULL,
    source_tier   TEXT NOT NULL,
    verdict       TEXT NOT NULL,
    verifier_note TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_state (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    phase          TEXT NOT NULL,
    section_status TEXT,
    updated_at     TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Ledger:
    """SQLite-backed crawl-state ledger for one run."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ---- pages ----

    def add_url(self, url: str, source: str) -> bool:
        """Insert a pending URL if new. Returns True if inserted (not a dup)."""
        now = _now()
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO pages (url, source, status, first_seen_at, last_seen_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (url, source, PageStatus.PENDING.value, now, now),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def add_urls(self, urls: list[tuple[str, str]]) -> int:
        """Bulk insert [(url, source), ...]. Returns count newly inserted."""
        inserted = 0
        for url, source in urls:
            if self.add_url(url, source):
                inserted += 1
        return inserted

    def pending_urls(
        self, include_errors: bool = True, max_retries: int = 3
    ) -> list[str]:
        """URLs still needing a crawl attempt (resume-aware, B3).

        pending always; error only while under the retry cap.
        """
        statuses = [PageStatus.PENDING.value]
        rows = self._conn.execute(
            f"SELECT url, status, retry_count FROM pages "
            f"WHERE status IN ({','.join('?' * len(statuses))}) "
            f"   OR (status = ? AND retry_count < ?)",
            (*statuses, PageStatus.ERROR.value, max_retries),
        ).fetchall()
        # error rows only re-attempted if caller allows
        return [
            r["url"]
            for r in rows
            if r["status"] == PageStatus.PENDING.value
            or (include_errors and r["status"] == PageStatus.ERROR.value)
        ]

    def record_page(
        self,
        url: str,
        status: PageStatus | str,
        *,
        http_status: int | None = None,
        content_sha256: str | None = None,
        content_type: str | None = None,
        title: str | None = None,
        word_count: int | None = None,
        point_ids: list[str] | None = None,
        md_path: str | None = None,
        html_path: str | None = None,
        screenshot_path: str | None = None,
        error: str | None = None,
        bump_retry: bool = False,
    ) -> None:
        status_val = status.value if isinstance(status, PageStatus) else status
        now = _now()
        retry_expr = "retry_count = retry_count + 1," if bump_retry else ""
        self._conn.execute(
            f"UPDATE pages SET status=?, {retry_expr} "
            "http_status=COALESCE(?, http_status), "
            "content_sha256=COALESCE(?, content_sha256), "
            "content_type=COALESCE(?, content_type), "
            "title=COALESCE(?, title), "
            "word_count=COALESCE(?, word_count), "
            "point_ids=COALESCE(?, point_ids), "
            "md_path=COALESCE(?, md_path), "
            "html_path=COALESCE(?, html_path), "
            "screenshot_path=COALESCE(?, screenshot_path), "
            "error=?, last_seen_at=? WHERE url=?",
            (
                status_val,
                http_status,
                content_sha256,
                content_type,
                title,
                word_count,
                json.dumps(point_ids) if point_ids is not None else None,
                md_path,
                html_path,
                screenshot_path,
                error,
                now,
                url,
            ),
        )
        self._conn.commit()

    def promote_exhausted(self, max_retries: int) -> int:
        """Promote error URLs at/over the retry cap to failed_terminal (B3).

        Ensures resume always terminates. Returns count promoted.
        """
        cur = self._conn.execute(
            "UPDATE pages SET status=?, last_seen_at=? "
            "WHERE status=? AND retry_count >= ?",
            (
                PageStatus.FAILED_TERMINAL.value,
                _now(),
                PageStatus.ERROR.value,
                max_retries,
            ),
        )
        self._conn.commit()
        return cur.rowcount

    def get_page(self, url: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM pages WHERE url=?", (url,)).fetchone()
        return dict(row) if row else None

    def pages_by_status(self, status: PageStatus | str) -> list[dict]:
        v = status.value if isinstance(status, PageStatus) else status
        rows = self._conn.execute("SELECT * FROM pages WHERE status=?", (v,)).fetchall()
        return [dict(r) for r in rows]

    def crawled_pages(self) -> list[dict]:
        """Pages with usable content for indexing (ok/low_content)."""
        rows = self._conn.execute(
            "SELECT * FROM pages WHERE status IN (?, ?)",
            (PageStatus.OK.value, PageStatus.LOW_CONTENT.value),
        ).fetchall()
        return [dict(r) for r in rows]

    def status_summary(self) -> dict:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) n FROM pages GROUP BY status"
        ).fetchall()
        return {r["status"]: r["n"] for r in rows}

    # ---- background sources ----

    def record_background(
        self,
        *,
        id: str,
        engine: str,
        topic: str,
        query: str,
        url: str | None,
        source_tier: str,
        fetched_path: str | None = None,
        point_id: str | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO background_sources "
            "(id, engine, topic, query, url, source_tier, fetched_path, point_id, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                id,
                engine,
                topic,
                query,
                url,
                source_tier,
                fetched_path,
                point_id,
                _now(),
            ),
        )
        self._conn.commit()

    def background_summary(self) -> dict:
        by_topic = {
            r["topic"]: r["n"]
            for r in self._conn.execute(
                "SELECT topic, COUNT(*) n FROM background_sources GROUP BY topic"
            ).fetchall()
        }
        by_tier = {
            r["source_tier"]: r["n"]
            for r in self._conn.execute(
                "SELECT source_tier, COUNT(*) n FROM background_sources GROUP BY source_tier"
            ).fetchall()
        }
        return {"by_topic": by_topic, "by_tier": by_tier}

    # ---- claims ----

    def record_claim(
        self,
        *,
        id: str,
        section: str,
        claim_text: str,
        source_urls: list[str],
        chunk_ids: list[str],
        chunk_texts: list[str],
        source_tier: str,
        verdict: str,
        verifier_note: str | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO claims "
            "(id, section, claim_text, source_urls, chunk_ids, chunk_texts, "
            " source_tier, verdict, verifier_note, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                id,
                section,
                claim_text,
                json.dumps(source_urls),
                json.dumps(chunk_ids),
                json.dumps(chunk_texts),
                source_tier,
                verdict,
                verifier_note,
                _now(),
            ),
        )
        self._conn.commit()

    def claims(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM claims").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for f in ("source_urls", "chunk_ids", "chunk_texts"):
                d[f] = json.loads(d[f]) if d[f] else []
            out.append(d)
        return out

    def supported_claim_index(self) -> dict[str, dict]:
        """Map normalized claim_text -> claim row, for the verify-report gate."""
        return {
            _norm_claim(c["claim_text"]): c
            for c in self.claims()
            if c["verdict"] == "supported"
        }

    # ---- run state (S3) ----

    def set_phase(self, phase: str, section_status: dict | None = None) -> None:
        self._conn.execute(
            "INSERT INTO run_state (id, phase, section_status, updated_at) "
            "VALUES (1, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET phase=excluded.phase, "
            "section_status=excluded.section_status, updated_at=excluded.updated_at",
            (phase, json.dumps(section_status or {}), _now()),
        )
        self._conn.commit()

    def get_phase(self) -> dict:
        row = self._conn.execute("SELECT * FROM run_state WHERE id=1").fetchone()
        if not row:
            return {"phase": None, "section_status": {}}
        return {
            "phase": row["phase"],
            "section_status": json.loads(row["section_status"] or "{}"),
        }


def _norm_claim(text: str) -> str:
    """Normalize claim text for matching (lowercase, collapse whitespace)."""
    import re

    return re.sub(r"\s+", " ", text.strip().lower())
