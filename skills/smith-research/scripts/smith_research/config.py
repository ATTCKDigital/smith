"""ResearchConfig — runtime configuration for the smith-research engine.

Adapted from armory website-indexer config.py (provenance), but decoupled and
retargeted for NATIVE (non-Docker) execution: defaults point at localhost, adds
smith-research-specific knobs (output root, depth, politeness, Playwright WS,
retry cap, thresholds — N1). All values overridable via environment variables.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path


# Politeness tiers (questions.md; FR-23). Concurrency + delay + retry budget.
_POLITENESS = {
    "strict": {"concurrency": 1, "delay": 2.0, "max_retries": 2},
    "normal": {"concurrency": 3, "delay": 1.0, "max_retries": 3},
    "aggressive": {"concurrency": 6, "delay": 0.3, "max_retries": 4},
}


def default_output_root() -> Path:
    """Artifact root — ~/Documents/smith-research (Deviation D2, questions.md Q7)."""
    env = os.environ.get("SMITH_RESEARCH_OUTPUT_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / "Documents" / "smith-research"


@dataclass
class ResearchConfig:
    """Runtime configuration for a smith-research run."""

    # --- services (native localhost defaults; NOT host.docker.internal) ---
    ollama_url: str = "http://localhost:11434"
    embedding_model: str = "nomic-embed-text"
    embedding_dim: int = 768  # nomic-embed-text
    qdrant_url: str = "http://localhost:6333"
    playwright_ws: str = "ws://localhost:9224/"

    # --- run scope ---
    domain: str | None = None
    output_root: Path = field(default_factory=default_output_root)
    depth: str = "thorough"  # quick | standard | thorough (FR-13)
    politeness: str = "normal"  # strict | normal | aggressive (FR-23)

    # --- crawl behaviour ---
    request_timeout: float = 15.0
    playwright_timeout: float = 20.0
    homepage_warmup_ms: int = 3000  # armory Cloudflare warm-up (R4)

    # --- content thresholds (N1 — pinned so behaviour is deterministic) ---
    max_text_chars: int = 20000  # per-page cap before truncation
    js_render_threshold: int = 200  # trafilatura chars below which we render (FR-5)
    low_content_min_words: int = 50  # below this → status low_content
    chunk_target_chars: int = 3000  # heading-aware chunk target
    chunk_overlap_chars: int = 200

    # --- retrieval / verification (FR-18b/S2) ---
    evidence_k: int = 12  # generous default k for evidence-check

    # --- depth → query-angle count per topic (FR-13) ---
    depth_angles: dict = field(
        default_factory=lambda: {
            "quick": 1,
            "standard": 2,
            "thorough": 4,
        }
    )
    depth_fetch_top: dict = field(
        default_factory=lambda: {
            "quick": 3,
            "standard": 5,
            "thorough": 10,
        }
    )

    def politeness_params(self) -> dict:
        return _POLITENESS.get(self.politeness, _POLITENESS["normal"])

    @property
    def max_retries(self) -> int:
        """Retry budget before a URL is promoted to failed_terminal (B3)."""
        return self.politeness_params()["max_retries"]

    @property
    def concurrency(self) -> int:
        return self.politeness_params()["concurrency"]

    @property
    def request_delay(self) -> float:
        return self.politeness_params()["delay"]

    @classmethod
    def from_env(cls, **overrides) -> "ResearchConfig":
        """Build from env with CLI overrides taking precedence."""
        base = cls(
            ollama_url=os.environ.get("OLLAMA_URL", "http://localhost:11434"),
            embedding_model=os.environ.get("EMBEDDING_MODEL", "nomic-embed-text"),
            qdrant_url=os.environ.get("QDRANT_URL", "http://localhost:6333"),
            playwright_ws=os.environ.get(
                "SMITH_RESEARCH_PLAYWRIGHT_WS", "ws://localhost:9224/"
            ),
        )
        for k, v in overrides.items():
            if v is not None and hasattr(base, k):
                setattr(base, k, v)
        return base
