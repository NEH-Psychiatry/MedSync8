"""Simple on-disk retriever over a `corpus/` folder.

Design goals: zero required external services, easy to understand, fast
enough for hundreds of policy docs. Uses a pluggable embedder (see
``backend.embedders``) + cosine similarity, cached to a single JSON file so
cold-start is cheap after the first indexing run.

For 10k+ docs, swap ``_cosine_topk`` for FAISS or move to pgvector.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

from .embedders import Embedder

log = logging.getLogger(__name__)

CHUNK_CHARS = 1200
CHUNK_OVERLAP = 200
INDEX_FILE = "index.json"


@dataclass
class Chunk:
    doc_id: str         # file path relative to corpus root
    chunk_id: int       # 0-based position inside the doc
    text: str
    sha: str            # sha256 of the chunk text (for cache invalidation)


@dataclass
class Hit:
    doc_id: str
    chunk_id: int
    text: str
    score: float

    def citation(self) -> str:
        return f"{self.doc_id}#chunk{self.chunk_id}"


# ---------- file loading ----------------------------------------------------


def _read_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader  # optional dep
        except ImportError:
            log.warning("pypdf not installed; skipping %s", path)
            return ""
        try:
            reader = PdfReader(str(path))
            return "\n\n".join((p.extract_text() or "") for p in reader.pages)
        except Exception as e:  # pragma: no cover
            log.warning("failed to read %s: %s", path, e)
            return ""
    return ""


def _chunk(text: str, chars: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    out: list[str] = []
    i = 0
    while i < len(text):
        out.append(text[i : i + chars])
        i += max(1, chars - overlap)
    return out


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _normalize_rows(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return vectors / norms


# ---------- indexing --------------------------------------------------------


class Retriever:
    def __init__(self, corpus_dir: str, embedder: Embedder) -> None:
        self.corpus_dir = Path(corpus_dir)
        self.embedder = embedder
        self.index_path = self.corpus_dir / INDEX_FILE
        self.chunks: list[Chunk] = []
        self.vectors: np.ndarray | None = None

    # ----- public api -----

    def ready(self) -> bool:
        return self.vectors is not None and len(self.chunks) > 0

    def load_or_build(self) -> None:
        if not self.corpus_dir.exists():
            log.info("corpus_dir %s does not exist; retriever disabled", self.corpus_dir)
            return

        disk_chunks = self._collect_chunks()
        if not disk_chunks:
            log.info("no documents in corpus_dir; retriever disabled")
            return

        cache = self._load_cache()
        # Only reuse cache if it was built with the same embedder — mixing
        # vectors from different models gives garbage scores. A cache with no
        # recorded embedder is treated as a mismatch for the same reason.
        if cache and cache.get("embedder") != self.embedder.name:
            log.info(
                "embedder changed (%s -> %s); rebuilding index",
                cache.get("embedder"), self.embedder.name,
            )
            cache = {}
        cached_by_sha = {(c["sha"]): c for c in cache.get("chunks", [])}

        # Reuse embeddings for unchanged chunks, embed the rest.
        to_embed: list[Chunk] = []
        vectors: list[list[float]] = []
        for ch in disk_chunks:
            hit = cached_by_sha.get(ch.sha)
            if hit and "vector" in hit:
                vectors.append(hit["vector"])
            else:
                to_embed.append(ch)
                vectors.append(None)  # placeholder  # type: ignore[arg-type]

        if to_embed:
            log.info("embedding %d new/changed chunks via %s",
                     len(to_embed), self.embedder.name)
            new_vecs = self.embedder.embed([c.text for c in to_embed])
            j = 0
            for idx, v in enumerate(vectors):
                if v is None:
                    vectors[idx] = new_vecs[j]
                    j += 1

        self.chunks = disk_chunks
        self.vectors = _normalize_rows(np.array(vectors, dtype=np.float32))
        # Rewrite the cache only when something actually changed — new/changed
        # chunks were embedded, or docs were removed/reordered.
        cache_shas = [c.get("sha") for c in cache.get("chunks", [])]
        if to_embed or cache_shas != [c.sha for c in disk_chunks]:
            self._save_cache()
        log.info("retriever ready: %d chunks across %d docs",
                 len(self.chunks), len({c.doc_id for c in self.chunks}))

    def search(self, query: str, k: int = 4) -> list[Hit]:
        if not self.ready():
            return []
        qv = np.array(self.embedder.embed([query])[0], dtype=np.float32)
        return self._cosine_topk(qv, k)

    # ----- internals -----

    def _collect_chunks(self) -> list[Chunk]:
        out: list[Chunk] = []
        for path in sorted(self.corpus_dir.rglob("*")):
            if path.name == INDEX_FILE or not path.is_file():
                continue
            text = _read_text(path)
            if not text.strip():
                continue
            rel = str(path.relative_to(self.corpus_dir))
            for i, chunk_text in enumerate(_chunk(text)):
                out.append(Chunk(doc_id=rel, chunk_id=i, text=chunk_text, sha=_sha(chunk_text)))
        return out

    def _load_cache(self) -> dict:
        if not self.index_path.exists():
            return {}
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_cache(self) -> None:
        payload = {
            "embedder": self.embedder.name,
            "chunks": [
                {
                    "doc_id": c.doc_id,
                    "chunk_id": c.chunk_id,
                    "text": c.text,
                    "sha": c.sha,
                    "vector": self.vectors[i].tolist(),  # type: ignore[index]
                }
                for i, c in enumerate(self.chunks)
            ],
        }
        tmp_path = self.index_path.with_suffix(f"{self.index_path.suffix}.tmp")
        tmp_path.write_text(json.dumps(payload), encoding="utf-8")
        tmp_path.replace(self.index_path)

    def _cosine_topk(self, qv: np.ndarray, k: int) -> list[Hit]:
        assert self.vectors is not None
        qn = qv / (np.linalg.norm(qv) + 1e-9)
        scores = self.vectors @ qn
        idx = np.argsort(-scores)[:k]
        return [
            Hit(
                doc_id=self.chunks[i].doc_id,
                chunk_id=self.chunks[i].chunk_id,
                text=self.chunks[i].text,
                score=float(scores[i]),
            )
            for i in idx
        ]


def format_context(hits: Iterable[Hit]) -> str:
    """Render hits as an [N]-indexed context block for the system prompt."""
    blocks = []
    for i, h in enumerate(hits, 1):
        blocks.append(f"[{i}] {h.citation()}\n{h.text}")
    return "\n\n".join(blocks)
