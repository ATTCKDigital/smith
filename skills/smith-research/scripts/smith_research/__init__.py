"""smith_research — deterministic engine for the smith-research skill.

Layer boundary: everything in this package is DETERMINISTIC and LLM-FREE. It
discovers, crawls, extracts, embeds, stores, retrieves, and mechanically verifies.
All LLM interpretation (synthesis, entailment verification) lives in the skill's
SKILL.md orchestrator, which drives this engine via the CLI (run.py).

Portions adapted (copied, not imported) from the armory project's
services/website-indexer and services/trend-intelligence; see per-file provenance
headers. Zero runtime coupling to armory.
"""

__version__ = "0.1.0"
