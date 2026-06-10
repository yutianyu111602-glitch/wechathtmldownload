"""Vector embedding client for Mac-hosted Ollama endpoints."""
from __future__ import annotations
import math
import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class EndpointInfo:
    url: str
    model: str
    dim: int | None = None
    health_path: str = "/health"
    meta_path: str = "/meta"


class EmbedClient:
    """HTTP client for embedding endpoints on Mac (192.168.8.234).

    - Reads dimension from /meta, never hardcodes.
    - Fails fast on dimension mismatch.
    - Validates embeddings for NaN/Infinity.
    - Supports resume via text_sha1 skip list.
    """

    def __init__(self, endpoint: EndpointInfo, timeout_sec: int = 60, max_retries: int = 3):
        self.endpoint = endpoint
        self.timeout_sec = timeout_sec
        self.max_retries = max_retries
        self._client = httpx.Client(timeout=timeout_sec)
        self._resolved_dim: int | None = None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> EmbedClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def health_check(self) -> dict[str, Any]:
        """GET /health. Returns {ok: bool, error?: str}."""
        try:
            url = f"{self.endpoint.url}{self.endpoint.health_path}"
            resp = self._client.get(url)
            if resp.status_code == 200:
                return {"ok": True, "status": resp.status_code}
            return {"ok": False, "error": f"HTTP {resp.status_code}", "status": resp.status_code}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def resolve_dimension(self) -> int:
        """Read dimension from /meta. Raises on failure or mismatch."""
        try:
            url = f"{self.endpoint.url}{self.endpoint.meta_path}"
            resp = self._client.get(url)
            resp.raise_for_status()
            meta = resp.json()
        except Exception as e:
            raise RuntimeError(f"Failed to read /meta from {self.endpoint.url}: {e}")

        dim = meta.get("dim") or meta.get("dimension") or meta.get("embedding_dim")
        if dim is None:
            raise RuntimeError(f"/meta response missing dimension: {meta}")

        dim = int(dim)

        if self.endpoint.dim is not None and dim != self.endpoint.dim:
            raise RuntimeError(
                f"Dimension mismatch: config says {self.endpoint.dim}, "
                f"endpoint /meta says {dim}. Failing fast."
            )

        self._resolved_dim = dim
        logger.info(f"Resolved dimension {dim} from {self.endpoint.url}")
        return dim

    @property
    def resolved_dim(self) -> int:
        if self._resolved_dim is None:
            return self.resolve_dimension()
        return self._resolved_dim

    def embed(self, text: str) -> list[float] | None:
        """Embed a single text. Returns vector or None on failure.

        Caller must check for NaN/Infinity via validate_vector().
        """
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._client.post(
                    f"{self.endpoint.url}/v1/embeddings",
                    json={"model": self.endpoint.model, "input": [text]},
                )
                if resp.status_code == 404:
                    resp = self._client.post(
                        f"{self.endpoint.url}/embed",
                        json={"model": self.endpoint.model, "texts": [text]},
                    )
                    if resp.status_code == 404:
                        resp = self._client.post(
                            f"{self.endpoint.url}/api/embed",
                            json={"model": self.endpoint.model, "input": text},
                        )
                resp.raise_for_status()
                result = resp.json()

                embeddings = result.get("embeddings") or result.get("embedding") or result.get("data")
                if embeddings is None:
                    raise ValueError(f"No embeddings in response: {list(result.keys())}")

                if (
                    isinstance(embeddings, list)
                    and len(embeddings) > 0
                    and isinstance(embeddings[0], dict)
                    and isinstance(embeddings[0].get("embedding"), list)
                ):
                    vec = embeddings[0]["embedding"]
                elif isinstance(embeddings, list) and len(embeddings) > 0:
                    vec = embeddings[0] if isinstance(embeddings[0], list) else embeddings
                else:
                    raise ValueError(f"Unexpected embeddings shape: {type(embeddings)}")

                return vec

            except Exception as e:
                logger.warning(f"embed attempt {attempt}/{self.max_retries} failed: {e}")
                if attempt == self.max_retries:
                    raise
                continue

        return None

    def validate_vector(self, vector: list[float]) -> tuple[bool, str]:
        """Check for NaN/Infinity and dimension match.

        Returns (is_valid, reason).
        """
        if not vector:
            return False, "empty_vector"

        if self._resolved_dim is not None and len(vector) != self._resolved_dim:
            return False, f"dim_mismatch: expected {self._resolved_dim}, got {len(vector)}"

        for i, v in enumerate(vector):
            if math.isnan(v):
                return False, f"nan_at_index_{i}"
            if math.isinf(v):
                return False, f"inf_at_index_{i}"

        return True, "ok"

    def embed_batch(self, texts: list[str], skip_sha1s: set[str] | None = None) -> list[dict[str, Any]]:
        """Embed a batch of texts. Returns list of {text, vector, valid, error}.

        skip_sha1s: set of text_sha1 to skip (for resume).
        Note: caller must pass texts with their sha1s separately for resume.
        This method embeds all texts passed; filtering by sha1 is done by the caller.
        """
        results = []
        for text in texts:
            try:
                vector = self.embed(text)
                if vector is None:
                    results.append({"text": text, "vector": None, "valid": False, "error": "embed_returned_none"})
                    continue

                valid, reason = self.validate_vector(vector)
                results.append({
                    "text": text,
                    "vector": vector if valid else None,
                    "valid": valid,
                    "error": None if valid else reason,
                })
            except Exception as e:
                results.append({"text": text, "vector": None, "valid": False, "error": str(e)})

        return results
