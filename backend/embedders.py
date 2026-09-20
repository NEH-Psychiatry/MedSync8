"""Pluggable embedding backends.

Two implementations:

- LocalEmbedder: runs sentence-transformers in-process. No network, no
  third-party data handling. Recommended for PHI corpora.
- OpenAIEmbedder: calls OpenAI's embedding API. Faster cold start, but sends
  chunk text to OpenAI -- needs a BAA before PHI use.

Selection is controlled by the EMBED_BACKEND env var: "local" (default) or
"openai". LocalEmbedder pins sentence-transformers/bge-small-en-v1.5 by
default; override via LOCAL_EMBED_MODEL.
"""

from __future__ import annotations

import logging
import os
from typing import Protocol, runtime_checkable

log = logging.getLogger(__name__)

DEFAULT_LOCAL_MODEL = "sentence-transformers/bge-small-en-v1.5"
DEFAULT_OPENAI_MODEL = "text-embedding-3-small"


@runtime_checkable
class Embedder(Protocol):
    """Minimal interface the retriever depends on."""

    name: str

    def embed(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover
        ...


class LocalEmbedder:
    """In-process sentence-transformers embedder."""

    def __init__(self, model_name: str | None = None) -> None:
        from sentence_transformers import SentenceTransformer  # lazy import

        self.model_name = model_name or os.environ.get(
            "LOCAL_EMBED_MODEL", DEFAULT_LOCAL_MODEL
        )
        log.info("loading local embedder: %s", self.model_name)
        self._model = SentenceTransformer(self.model_name)
        self.name = f"local:{self.model_name}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # normalize_embeddings=True makes cosine == dot product.
        vecs = self._model.encode(
            texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False
        )
        return vecs.tolist()


# Every outbound relay in this backend is time-bounded; an embedding call that
# hangs would otherwise stall a request worker indefinitely.
OPENAI_TIMEOUT_SECONDS = float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "30"))
OPENAI_MAX_RETRIES = int(os.environ.get("OPENAI_MAX_RETRIES", "2"))


def _openai_client():
    from openai import OpenAI  # lazy import

    return OpenAI(timeout=OPENAI_TIMEOUT_SECONDS, max_retries=OPENAI_MAX_RETRIES)


class OpenAIEmbedder:
    """OpenAI API embedder. Legacy / fallback path."""

    def __init__(self, client=None, model: str | None = None) -> None:
        self.model = model or os.environ.get("OPENAI_EMBED_MODEL", DEFAULT_OPENAI_MODEL)
        if client is None:
            client = _openai_client()
        self._client = client
        self.name = f"openai:{self.model}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        # OpenAI accepts up to 2048 inputs; batch modestly for memory safety.
        for i in range(0, len(texts), 64):
            batch = texts[i : i + 64]
            resp = self._client.embeddings.create(model=self.model, input=batch)
            out.extend(d.embedding for d in resp.data)
        return out


def build_embedder_from_env() -> Embedder | None:
    """Factory used by server startup.

    Returns None if the selected backend cannot initialize -- the server logs
    a warning and keeps running with RAG disabled.
    """
    backend = os.environ.get("EMBED_BACKEND", "local").lower()
    try:
        if backend == "openai":
            if not os.environ.get("OPENAI_API_KEY"):
                log.warning("EMBED_BACKEND=openai but OPENAI_API_KEY unset")
                return None
            return OpenAIEmbedder()
        # default
        return LocalEmbedder()
    except Exception as e:  # pragma: no cover -- model load failure
        log.warning("failed to build embedder %s: %s", backend, e)
        return None
