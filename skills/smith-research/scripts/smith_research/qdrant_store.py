# Adapted (copied, not imported) from armory services/website-indexer/website_indexer/qdrant_store.py.
# Vendored into smith-research per user instruction: no runtime coupling to armory.
# PARAMETERIZED from the armory version: collection name, vector dim, and Qdrant
# URL are now __init__ params (armory hardcoded COLLECTION/VECTOR_DIM). The
# deterministic UUID5 point-ID derivation is generalized to take an arbitrary
# string key so callers can pass e.g. f"{url}#{chunk_index}". A generic
# upsert_point(point_key, vector, payload) is added; upsert_page delegates to it.
"""WebsiteQdrantStore — Qdrant storage for crawled website pages and chunks.

Each point is stored with a deterministic UUID derived from a caller-supplied
string key via uuid.uuid5(NAMESPACE_URL, key). This makes upserts idempotent:
re-indexing the same key overwrites the existing point.

Default collection: website_content (768-dim cosine, mirrors nomic-embed-text).
"""

import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from smith_research.models import WebPage


def _point_id_for_key(key: str) -> str:
    """Derive a deterministic UUID from an arbitrary string key.

    Args:
        key: Any string (e.g. a page URL or f"{url}#{chunk_index}").

    Returns:
        UUID string (uuid5 in NAMESPACE_URL namespace).
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


class WebsiteQdrantStore:
    """Manages a Qdrant collection for crawled website content."""

    def __init__(
        self,
        url: str = "http://localhost:6333",
        collection: str = "website_content",
        vector_dim: int = 768,
    ) -> None:
        self.client = QdrantClient(url=url, timeout=30)
        self.collection = collection
        self.vector_dim = vector_dim

    def ensure_collection(self) -> None:
        """Create the collection if it does not already exist.

        Also creates a keyword payload index on content_type for filtered search.
        Idempotent — safe to call on every crawl start.
        """
        existing = {c.name for c in self.client.get_collections().collections}
        if self.collection not in existing:
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(
                    size=self.vector_dim,
                    distance=Distance.COSINE,
                ),
            )
            # Create payload index for content_type to enable efficient filtered queries
            self.client.create_payload_index(
                collection_name=self.collection,
                field_name="content_type",
                field_schema=PayloadSchemaType.KEYWORD,
            )

    def upsert_point(self, point_key: str, vector: list[float], payload: dict) -> str:
        """Upsert a single point with a deterministic ID derived from point_key.

        Point ID is derived deterministically from point_key so repeated
        upserts of the same key update the existing point rather than creating
        a duplicate. Callers pass whatever key granularity they need — a bare
        URL for page-level points, or f"{url}#{chunk_index}" for chunk-level.

        Args:
            point_key: String used to derive the deterministic point ID.
            vector: Embedding vector (must match the collection's vector_dim).
            payload: Arbitrary payload dict stored alongside the vector.

        Returns:
            The string point ID that was upserted.
        """
        point_id = _point_id_for_key(point_key)

        self.client.upsert(
            collection_name=self.collection,
            points=[
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload,
                )
            ],
        )

        return point_id

    def upsert_page(self, page: WebPage, vector: list[float]) -> str:
        """Upsert a single WebPage into the collection.

        Delegates to upsert_point using the page URL as the deterministic key,
        so repeated crawls of the same URL update the existing point.

        Args:
            page: Fully extracted WebPage dataclass instance.
            vector: Embedding vector from Ollama.

        Returns:
            The string point ID that was upserted.
        """
        payload = {
            "url": page.url,
            "title": page.title,
            "content_type": page.content_type,
            "text_snippet": page.text_snippet,
            "full_text": page.full_text,
            "crawled_at": page.crawled_at.isoformat() if page.crawled_at else None,
            "word_count": page.word_count,
            "http_status": page.http_status,
            "truncated": page.truncated,
            "low_content": page.low_content,
        }

        return self.upsert_point(page.url, vector, payload)

    def delete_by_url(self, url: str) -> None:
        """Delete the point for a given URL from the collection.

        Uses the same deterministic point ID derivation as upsert_page.

        Args:
            url: Absolute page URL whose point should be deleted.
        """
        point_id = _point_id_for_key(url)
        self.client.delete(
            collection_name=self.collection,
            points_selector=Filter(
                must=[FieldCondition(key="url", match=MatchValue(value=url))]
            ),
        )
        # Also delete by ID directly in case payload index is not available
        try:
            self.client.delete(
                collection_name=self.collection,
                points_selector=[point_id],
            )
        except Exception:
            pass

    def close(self) -> None:
        """Close the underlying Qdrant client."""
        self.client.close()
