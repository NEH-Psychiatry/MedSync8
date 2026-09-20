"""API contract tests. Spins up the FastAPI app with stubbed OpenAI/Anthropic."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import audit as audit_module
from backend import server as server_module
from backend.retriever import Retriever


@pytest.fixture
def client(monkeypatch, tmp_path: Path, tiny_corpus: Path, stub_embedder, stub_anthropic):
    # Build a retriever against the tiny corpus and inject it, skipping lifespan.
    retriever = Retriever(str(tiny_corpus), stub_embedder)
    retriever.load_or_build()

    # Skip the real lifespan (which needs ANTHROPIC_API_KEY env vars).
    monkeypatch.setattr(server_module.app.router, "lifespan_context", None)
    server_module.app.state.retriever = retriever
    server_module.app.state.anthropic = stub_anthropic

    # Route audit writes to a temp file so each test gets a clean logger.
    audit_module.reset_for_tests(tmp_path / "audit.log")

    return TestClient(server_module.app)


def test_anthropic_client_is_time_bounded(monkeypatch):
    """The FastAPI → Anthropic relay must carry an explicit timeout (relay audit)."""
    from backend import server as server_module

    captured: dict = {}

    class FakeAnthropic:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(server_module.anthropic, "Anthropic", FakeAnthropic)
    server_module.build_anthropic_client()
    assert captured["timeout"] == server_module.ANTHROPIC_TIMEOUT_SECONDS > 0
    assert captured["max_retries"] == server_module.ANTHROPIC_MAX_RETRIES


def test_health_returns_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_chat_returns_reply_and_citations(client, stub_anthropic):
    r = client.post("/api/chat", json={
        "tool": "policy",
        "messages": [{"role": "user", "content": "Draft a PDMP policy for Texas"}],
        "use_rag": True,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert "stub-reply" in body["reply"]
    assert len(body["citations"]) >= 1
    c = body["citations"][0]
    assert {"index", "doc_id", "chunk_id", "score"} <= set(c.keys())
    # The stub anthropic recorded the augmented system prompt with citations.
    assert "RETRIEVED CONTEXT" in stub_anthropic.last_call["system"]


def test_chat_without_rag_skips_retrieval(client, stub_anthropic):
    r = client.post("/api/chat", json={
        "tool": "chat",
        "messages": [{"role": "user", "content": "Quick DEA question"}],
        "use_rag": False,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["citations"] == []
    assert "RETRIEVED CONTEXT" not in stub_anthropic.last_call["system"]


def test_chat_rejects_unknown_tool(client):
    r = client.post("/api/chat", json={
        "tool": "cafeteria_menu",
        "messages": [{"role": "user", "content": "hi"}],
    })
    # Pydantic literal validation -> 422
    assert r.status_code == 422


def test_chat_requires_at_least_one_message(client):
    r = client.post("/api/chat", json={"tool": "chat", "messages": []})
    assert r.status_code == 422
    assert r.json()["detail"] == "invalid chat request shape"


def test_chat_rejects_blank_user_message(client):
    r = client.post("/api/chat", json={
        "tool": "chat",
        "messages": [{"role": "user", "content": "   "}],
    })
    assert r.status_code == 422
    body = r.json()
    assert body["detail"] == "invalid chat request shape"
    assert "whitespace-only" in str(body["errors"]).lower()


def test_chat_rejects_too_many_messages(client):
    msgs = [{"role": "user", "content": f"msg-{i}"} for i in range(51)]
    r = client.post("/api/chat", json={"tool": "chat", "messages": msgs})
    assert r.status_code == 422
    assert r.json()["detail"] == "invalid chat request shape"


def test_chat_rejects_message_exceeding_max_length(client):
    r = client.post("/api/chat", json={
        "tool": "chat",
        "messages": [{"role": "user", "content": "a" * 20001}],
    })
    assert r.status_code == 422
    assert r.json()["detail"] == "invalid chat request shape"


def test_chat_handles_anthropic_response_without_text_block(client, stub_anthropic):
    class _NonTextBlock:
        type = "tool_use"

    class _NoTextResponse:
        content = [_NonTextBlock()]

    def _create_without_text(**kwargs):
        stub_anthropic.last_call = kwargs
        return _NoTextResponse()

    stub_anthropic.messages.create = _create_without_text
    r = client.post("/api/chat", json={
        "tool": "chat",
        "messages": [{"role": "user", "content": "hello"}],
    })
    assert r.status_code == 502
    assert r.json()["detail"] == "anthropic response missing text content"


def test_chat_writes_audit_event_without_query_text(client):
    leaky = "UNIQUE-PATIENT-STRING-xyz123"
    r = client.post("/api/chat", json={
        "tool": "policy",
        "messages": [{"role": "user", "content": leaky}],
        "use_rag": False,
    })
    assert r.status_code == 200

    # /api/audit/recent reflects the request.
    r2 = client.get("/api/audit/recent")
    assert r2.status_code == 200
    body = r2.json()
    assert body["count"] == 1
    event = body["events"][0]
    assert event["event"] == "chat"
    assert event["tool"] == "policy"
    assert event["status"] == "ok"
    assert "query_len_bucket" in event

    # Neither the endpoint response nor the persisted file contains the raw query.
    assert leaky not in r2.text
    log_path = audit_module.get_logger().path
    assert leaky not in log_path.read_text(encoding="utf-8")


def test_chat_documentation_tool(client, stub_anthropic):
    r = client.post("/api/chat", json={
        "tool": "documentation",
        "messages": [{"role": "user", "content": "Generate a SOAP note for an ADHD evaluation"}],
        "use_rag": False,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert "stub-reply" in body["reply"]
    assert "SOAP" in stub_anthropic.last_call["system"] or "documentation" in stub_anthropic.last_call["system"].lower()


def test_chat_rejects_too_many_messages(client):
    messages = [{"role": "user", "content": f"msg {i}"} for i in range(101)]
    r = client.post("/api/chat", json={"tool": "chat", "messages": messages})
    assert r.status_code == 422


def test_health_does_not_expose_internals(client):
    r = client.get("/api/health")
    body = r.json()
    assert "model" not in body
    assert "rag_enabled" not in body
    assert "corpus_chunks" not in body
    assert "embedder" not in body
    assert "access_enforced" not in body


def test_audit_event_has_bucketed_query_len(client):
    r = client.post("/api/chat", json={
        "tool": "policy",
        "messages": [{"role": "user", "content": "short"}],
        "use_rag": False,
    })
    assert r.status_code == 200
    events = client.get("/api/audit/recent").json()["events"]
    assert events[-1]["query_len_bucket"] == "<100"
    assert "query_len" not in events[-1]


def test_lifespan_survives_indexing_failure(monkeypatch, tmp_path):
    """Regression: a transient embedding failure during startup must degrade to
    no-RAG operation instead of crashing the server."""

    class ExplodingEmbedder:
        name = "stub:exploding"

        def embed(self, texts):
            raise RuntimeError("transient embed failure")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setattr(server_module, "build_embedder_from_env", ExplodingEmbedder)
    audit_module.reset_for_tests(tmp_path / "audit.log")

    with TestClient(server_module.app) as lifespan_client:
        body = lifespan_client.get("/api/health").json()
        assert body["ok"] is True
        # Degraded to no-RAG operation; /api/health deliberately does not
        # expose retriever state, so assert on app state instead.
        assert server_module.app.state.retriever is None
