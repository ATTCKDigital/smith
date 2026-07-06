# Adapted (copied, not imported) from armory services/website-indexer/website_indexer/logger.py.
# Vendored into smith-research per user instruction: no runtime coupling to armory.
"""CrawlLogger — JSONL audit log for each crawl run.

Creates a new timestamped JSONL file at logger init time. One record is
appended per processed URL. The audit log is write-only and is never read
back by the pipeline — that is the checkpoint file's responsibility.

File format: logs/website-indexer-<YYYY-MM-DD-HH-MM-SS>.jsonl
"""

import json
from datetime import datetime, timezone
from pathlib import Path


class CrawlLogger:
    """Writes a JSONL audit log for a crawl run.

    Opens a new file at init time with the current UTC timestamp in its name.
    Call close() when the crawl finishes to flush and close the file handle.
    """

    def __init__(self, log_dir: str | Path = "logs") -> None:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d-%H-%M-%S")
        self._path = log_path / f"website-indexer-{timestamp}.jsonl"
        self._fh = self._path.open("a", encoding="utf-8")

    @property
    def path(self) -> Path:
        """Return the path to the current audit log file."""
        return self._path

    def write(
        self,
        url: str,
        content_type: str | None,
        status: str,
        error: str | None = None,
        point_id: str | None = None,
        word_count: int | None = None,
        truncated: bool | None = None,
        http_status: int | None = None,
    ) -> None:
        """Append a single audit record to the JSONL log.

        Args:
            url: The page URL that was processed.
            content_type: Classified content type, or None on extraction error.
            status: One of "ok", "error", "skipped", "low_content".
            error: Error message if status is "error"; None otherwise.
            point_id: Qdrant point UUID if indexed; None on error.
            word_count: Pre-truncation word count, or None on error.
            truncated: Whether full_text was truncated at max_text_chars.
            http_status: HTTP response status code, or None on network error.
        """
        record = {
            "timestamp": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "url": url,
            "content_type": content_type,
            "status": status,
            "error": error,
            "point_id": point_id,
            "word_count": word_count,
            "truncated": truncated,
            "http_status": http_status,
        }
        self._fh.write(json.dumps(record) + "\n")
        self._fh.flush()

    def close(self) -> None:
        """Flush and close the audit log file handle."""
        if self._fh and not self._fh.closed:
            self._fh.flush()
            self._fh.close()
