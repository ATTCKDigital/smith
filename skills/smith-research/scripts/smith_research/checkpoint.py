# Adapted (copied, not imported) from armory services/website-indexer/website_indexer/checkpoint.py.
# Vendored into smith-research per user instruction: no runtime coupling to armory.
"""CheckpointManager — JSONL-based checkpoint and resume for the crawl loop.

The checkpoint file is a JSONL file with one record per processed URL. On
--resume, the manager reads the file and returns a set of URLs that have
already been successfully processed (status "ok" or "low_content"). Error
URLs are NOT included so they will be retried on the next run.

Default checkpoint path: logs/website-indexer-checkpoint-<YYYY-MM-DD>.jsonl
"""

import json
from datetime import datetime, timezone
from pathlib import Path


def _default_checkpoint_path(log_dir: str | Path = "logs") -> Path:
    """Return the default checkpoint path for today's date."""
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    return Path(log_dir) / f"website-indexer-checkpoint-{today}.jsonl"


class CheckpointManager:
    """Manages a JSONL checkpoint file for crawl resume capability."""

    # Statuses that count as "successfully processed" and should be skipped on resume
    _DONE_STATUSES: frozenset[str] = frozenset(["ok", "low_content"])

    def __init__(
        self, path: str | Path | None = None, log_dir: str | Path = "logs"
    ) -> None:
        if path is not None:
            self.path = Path(path)
        else:
            self.path = _default_checkpoint_path(log_dir)

        # Ensure parent directory exists
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load_done_urls(self) -> set[str]:
        """Read the checkpoint file and return the set of successfully processed URLs.

        Only URLs with status "ok" or "low_content" are returned. URLs with
        status "error" will be retried on the next --resume run.

        Returns:
            Set of URL strings that have been successfully indexed.
        """
        done: set[str] = set()
        if not self.path.exists():
            return done

        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    if record.get("status") in self._DONE_STATUSES:
                        url = record.get("url")
                        if url:
                            done.add(url)
                except json.JSONDecodeError:
                    # Skip malformed lines rather than aborting the whole run
                    continue

        return done

    def write(
        self,
        url: str,
        status: str,
        point_id: str | None = None,
        error: str | None = None,
    ) -> None:
        """Append a single checkpoint record to the JSONL file.

        Args:
            url: The page URL that was processed.
            status: One of "ok", "error", "skipped", "low_content".
            point_id: Qdrant point UUID if the page was indexed; None on error.
            error: Error message string if status is "error"; None otherwise.
        """
        record = {
            "url": url,
            "status": status,
            "point_id": point_id,
            "error": error,
            "timestamp": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
            fh.flush()

    def reset(self) -> None:
        """Truncate the checkpoint file for a fresh run."""
        with self.path.open("w", encoding="utf-8") as fh:
            fh.truncate(0)
