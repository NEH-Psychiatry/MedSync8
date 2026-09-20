from pathlib import Path

import numpy as np

from backend.retriever import Retriever, _chunk, _sha, format_context


def test_chunk_splits_and_overlaps():
    text = "abcdefghij" * 200  # 2000 chars
    chunks = _chunk(text, chars=500, overlap=100)
    assert len(chunks) >= 4
    # overlap: end of chunk N should appear at start of chunk N+1
    assert chunks[0][-100:] == chunks[1][:100]


def test_chunk_empty_text_returns_empty():
    assert _chunk("") == []
    assert _chunk("   \n\n") == []


def test_sha_stable_and_distinct():
    assert _sha("hello") == _sha("hello")
    assert _sha("hello") != _sha("world")


def test_retriever_builds_index_and_caches(tiny_corpus: Path, stub_embedder):
    r = Retriever(str(tiny_corpus), stub_embedder)
    r.load_or_build()
    assert r.ready()
    assert len(r.chunks) >= 2
    assert (tiny_corpus / "index.json").exists()

    # Second load should reuse the cache — no embedding calls needed.
    r2 = Retriever(str(tiny_corpus), stub_embedder)
    r2.load_or_build()
    assert r2.ready()
    assert len(r2.chunks) == len(r.chunks)
    assert not (tiny_corpus / "index.json.tmp").exists()


def test_retriever_handles_missing_corpus_dir(tmp_path, stub_embedder):
    r = Retriever(str(tmp_path / "does-not-exist"), stub_embedder)
    r.load_or_build()
    assert not r.ready()
    assert r.search("anything") == []


def test_search_returns_topk_hits(tiny_corpus: Path, stub_embedder):
    r = Retriever(str(tiny_corpus), stub_embedder)
    r.load_or_build()
    norms = np.linalg.norm(r.vectors, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)
    hits = r.search("controlled substances", k=3)
    assert 1 <= len(hits) <= 3
    for h in hits:
        assert h.doc_id
        assert 0 <= h.score <= 1.001  # cosine similarity bound


def test_format_context_uses_indexed_citations(tiny_corpus: Path, stub_embedder):
    r = Retriever(str(tiny_corpus), stub_embedder)
    r.load_or_build()
    hits = r.search("Texas PDMP", k=2)
    ctx = format_context(hits)
    assert ctx.startswith("[1]")
    if len(hits) >= 2:
        assert "\n\n[2]" in ctx


def test_chunker_strips_redundant_whitespace():
    chunks = _chunk("a\n\n\nb\t\tc")
    assert chunks == ["a b c"]


def test_cache_without_embedder_field_is_invalidated(tiny_corpus: Path, stub_embedder):
    """Regression: a cache missing its 'embedder' field must be rebuilt, not
    reused — otherwise vectors from different models can silently mix."""
    import json

    r = Retriever(str(tiny_corpus), stub_embedder)
    r.load_or_build()
    index_path = tiny_corpus / "index.json"

    payload = json.loads(index_path.read_text())
    del payload["embedder"]
    # Poison the cached vectors so silent reuse is detectable.
    for c in payload["chunks"]:
        c["vector"] = [0.0] * len(c["vector"])
    index_path.write_text(json.dumps(payload))

    r2 = Retriever(str(tiny_corpus), stub_embedder)
    r2.load_or_build()
    assert r2.ready()
    # Zero vectors survive normalization as zero rows; a rebuild re-embeds.
    assert not np.allclose(r2.vectors, 0.0)
    assert json.loads(index_path.read_text())["embedder"] == stub_embedder.name


def test_cache_not_rewritten_when_unchanged(tiny_corpus: Path, stub_embedder):
    """Regression: a fully reused cache must not be rewritten on startup."""
    r = Retriever(str(tiny_corpus), stub_embedder)
    r.load_or_build()
    index_path = tiny_corpus / "index.json"
    before = index_path.stat().st_mtime_ns

    r2 = Retriever(str(tiny_corpus), stub_embedder)
    r2.load_or_build()
    assert r2.ready()
    assert index_path.stat().st_mtime_ns == before
