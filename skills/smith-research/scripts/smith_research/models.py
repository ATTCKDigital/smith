# Adapted (copied, not imported) from armory services/website-indexer/website_indexer/models.py.
# Vendored into smith-research per user instruction: no runtime coupling to armory.
"""Data model dataclasses for the website indexer.

These are the canonical in-memory representations used throughout the pipeline.
They are intentionally free of external dependencies so they can be imported
anywhere without side effects.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class WebPage:
    """A fully extracted and classified page, ready for embedding and storage."""

    url: str
    title: str
    content_type: str
    full_text: str
    text_snippet: str
    word_count: int
    crawled_at: datetime
    http_status: int
    truncated: bool
    low_content: bool
    # Populated after Qdrant upsert
    point_id: str | None = None


@dataclass
class CrawlResult:
    """Wraps the outcome of attempting to crawl a single URL — success or failure."""

    url: str
    success: bool
    page: WebPage | None = None
    point_id: str | None = None
    error: str | None = None
    # ok | error | skipped | low_content
    status: str = field(default="ok")


@dataclass
class CrawlSummary:
    """Aggregated statistics for a completed crawl run."""

    total_discovered: int
    succeeded: int
    failed: int
    skipped: int
    low_content: int
    truncated: int
    elapsed_seconds: float
