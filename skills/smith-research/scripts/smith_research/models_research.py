"""Net-new data models for smith-research (NOT copied from armory).

Kept separate from the verbatim armory models.py (provenance honesty, N5).
These model the research-specific entities: ledger rows, background sources,
atomic claims, and run-level state.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class PageStatus(str, Enum):
    """Crawl-state lifecycle for a URL (B3: terminal states end resume loops)."""

    PENDING = "pending"
    OK = "ok"
    LOW_CONTENT = "low_content"
    ERROR = "error"  # transient — resume re-attempts (until cap)
    BLOCKED = "blocked"  # terminal — anti-bot block after cap
    FAILED_TERMINAL = "failed_terminal"  # terminal — non-block error after cap
    SKIPPED = "skipped"  # terminal — deliberately not crawled

    @classmethod
    def done(cls) -> frozenset["PageStatus"]:
        """Successfully processed — skip on resume."""
        return frozenset({cls.OK, cls.LOW_CONTENT})

    @classmethod
    def terminal(cls) -> frozenset["PageStatus"]:
        """Reached a final state (success or not) — never re-attempted."""
        return frozenset(
            {cls.OK, cls.LOW_CONTENT, cls.BLOCKED, cls.FAILED_TERMINAL, cls.SKIPPED}
        )


class SourceTier(str, Enum):
    """Authority tier for a background source (B2/G8)."""

    FIRST_PARTY = "first_party"  # the target site about itself
    REPUTABLE_SECONDARY = "reputable_secondary"  # news/press/other sites
    SOCIAL_UNVERIFIED = "social_unverified"  # reddit/forums — hedge, never bare fact


class Verdict(str, Enum):
    """Verification outcome for an atomic claim (B1)."""

    SUPPORTED = "supported"
    UNVERIFIED = "unverified"  # no chunk entails it
    CONTRADICTED = "contradicted"  # a chunk refutes it
    REMOVED = "removed"


class Phase(str, Enum):
    """Run-level phase for mid-run resume (S3)."""

    DISCOVER = "discover"
    CRAWL = "crawl"
    INDEX = "index"
    BACKGROUND = "background"
    SYNTHESIZE = "synthesize"
    VERIFY = "verify"
    DONE = "done"


@dataclass
class BackgroundSource:
    """A SERP/Reddit/deep-fetched background result."""

    id: str  # uuid5(engine|query|url)
    engine: str  # google | bing | reddit
    topic: str
    query: str
    url: str | None
    source_tier: SourceTier
    fetched_path: str | None = None
    point_id: str | None = None
    fetched_at: datetime | None = None


@dataclass
class Claim:
    """An ATOMIC factual assertion extracted from the report (B1)."""

    id: str  # uuid5(section|claim_text)
    section: str
    claim_text: str
    source_urls: list[str] = field(default_factory=list)
    chunk_ids: list[str] = field(default_factory=list)
    chunk_texts: list[str] = field(default_factory=list)  # S1: self-contained audit
    source_tier: SourceTier = SourceTier.REPUTABLE_SECONDARY
    verdict: Verdict = Verdict.UNVERIFIED
    verifier_note: str | None = None
    created_at: datetime | None = None
