"""Tests for the embedder factory and OpenAI wrapper.

The local (sentence-transformers) backend is tested indirectly by the
Docker build prefetch step \u2014 we don't download a 130MB model in CI.
"""
from __future__ import annotations

import pytest

from backend import embedders


def test_factory_returns_none_when_openai_selected_without_key(monkeypatch):
    monkeypatch.setenv("EMBED_BACKEND", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert embedders.build_embedder_from_env() is None


def test_openai_embedder_batches_inputs():
    class FakeClient:
        def __init__(self):
            self.calls: list[list[str]] = []
            self.embeddings = self

        def create(self, model, input):
            self.calls.append(list(input))
            class R:
                data = [type("E", (), {"embedding": [0.0] * 4})() for _ in input]
            return R()

    fake = FakeClient()
    emb = embedders.OpenAIEmbedder(client=fake, model="stub")
    # Make sure the batch size logic (64) actually batches.
    out = emb.embed([f"t{i}" for i in range(150)])
    assert len(out) == 150
    assert [len(c) for c in fake.calls] == [64, 64, 22]


def test_openai_embedder_empty_input_noop():
    class FakeClient:
        embeddings = None  # should never be called
    emb = embedders.OpenAIEmbedder(client=FakeClient(), model="stub")
    assert emb.embed([]) == []


def test_openai_client_is_time_bounded(monkeypatch):
    """The OpenAI relay must never be built without a timeout (relay audit)."""
    import openai

    captured: dict = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.embeddings = None

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    embedders.OpenAIEmbedder(model="stub")  # client=None → builds the real-shaped client
    assert captured["timeout"] == embedders.OPENAI_TIMEOUT_SECONDS > 0
    assert captured["max_retries"] == embedders.OPENAI_MAX_RETRIES


def test_embedder_protocol_satisfied_by_openai_embedder():
    class FakeClient:
        class embeddings:
            @staticmethod
            def create(model, input):
                class R:
                    data = []
                return R()
    emb = embedders.OpenAIEmbedder(client=FakeClient(), model="stub")
    assert isinstance(emb, embedders.Embedder)
    assert emb.name == "openai:stub"
