# Adapted (copied, not imported) from armory services/website-indexer/website_indexer/embedder.py.
# Vendored into smith-research per user instruction: no runtime coupling to armory.
"""OllamaEmbedder — single-text embedding via Ollama /api/embed endpoint.

Adapted from services/email-pipeline/email_pipeline/embedding/ollama_client.py.
Uses the nomic-embed-text model with the 'search_document: ' prefix for
asymmetric indexing (correct for pages being stored, not queries).
"""

import time

import httpx


class OllamaEmbedder:
    """Embeds text via Ollama's /api/embed endpoint with retry and backoff."""

    def __init__(
        self, base_url: str = "http://localhost:11434", model: str = "nomic-embed-text"
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.client = httpx.Client(timeout=30.0)

    def embed(self, text: str) -> list[float]:
        """Embed a single text string and return the vector.

        Prepends 'search_document: ' prefix for nomic-embed-text asymmetric indexing.

        Args:
            text: Raw text to embed.

        Returns:
            List of floats (768-dimensional vector for nomic-embed-text).

        Raises:
            RuntimeError: If all 3 attempts fail.
        """
        prefixed = f"search_document: {text}"

        for attempt in range(3):
            try:
                resp = self.client.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.model, "input": [prefixed]},
                )
                resp.raise_for_status()
                data = resp.json()
                embeddings: list[list[float]] = data["embeddings"]
                return embeddings[0]
            except (httpx.HTTPError, KeyError) as exc:
                if attempt == 2:
                    raise RuntimeError(
                        f"Ollama embedding failed after 3 attempts: {exc}"
                    ) from exc
                wait = 2**attempt  # 1s, 2s, 4s
                print(
                    f"  [WARN] Ollama embed attempt {attempt + 1} failed: {exc}, retrying in {wait}s..."
                )
                time.sleep(wait)

        # Unreachable but satisfies the type checker
        raise RuntimeError("Ollama embedding failed after 3 attempts")

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts in a single request.

        Args:
            texts: List of raw text strings to embed.

        Returns:
            List of 768-dimensional float vectors, one per input text.

        Raises:
            RuntimeError: If all 3 attempts fail.
        """
        prefixed = [f"search_document: {t}" for t in texts]

        for attempt in range(3):
            try:
                resp = self.client.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.model, "input": prefixed},
                )
                resp.raise_for_status()
                data = resp.json()
                return data["embeddings"]
            except (httpx.HTTPError, KeyError) as exc:
                if attempt == 2:
                    raise RuntimeError(
                        f"Ollama batch embedding failed after 3 attempts: {exc}"
                    ) from exc
                wait = 2**attempt
                print(
                    f"  [WARN] Ollama embed attempt {attempt + 1} failed: {exc}, retrying in {wait}s..."
                )
                time.sleep(wait)

        raise RuntimeError("Ollama batch embedding failed after 3 attempts")

    def check_health(self) -> bool:
        """Check if Ollama is reachable and has the embedding model loaded.

        Returns:
            True if the model is available, False otherwise.
        """
        try:
            resp = self.client.get(f"{self.base_url}/api/tags")
            resp.raise_for_status()
            models: list[dict] = resp.json().get("models", [])
            model_names = [m["name"] for m in models]
            return any(self.model in name for name in model_names)
        except (httpx.HTTPError, KeyError, ValueError):
            return False

    def close(self) -> None:
        """Close the underlying httpx client."""
        self.client.close()
