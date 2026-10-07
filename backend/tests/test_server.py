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


def test_health_reports_rag_enabled(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["rag_enabled"] is True
    assert body["corpus_chunks"] > 0
    assert "audit_salt_default" in body


def test_production_configuration_fails_closed(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    for name in (
        "ANTHROPIC_API_KEY",
        "CF_ACCESS_TEAM_DOMAIN",
        "CF_ACCESS_AUD",
        "AUDIT_SALT",
        "ALLOWED_ORIGINS",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RuntimeError, match="unsafe production configuration"):
        server_module.validate_runtime_security()


@pytest.mark.parametrize(
    ("name", "value", "error"),
    [
        ("ANTHROPIC_API_KEY", None, "ANTHROPIC_API_KEY is required"),
        ("CF_ACCESS_TEAM_DOMAIN", None, "CF_ACCESS_TEAM_DOMAIN is required"),
        ("CF_ACCESS_AUD", None, "CF_ACCESS_AUD is required"),
        ("AUDIT_SALT", audit_module.DEFAULT_AUDIT_SALT, "unique AUDIT_SALT"),
        ("ALLOWED_ORIGINS", "", "production frontend origin"),
        ("ALLOWED_ORIGINS", "*", "explicit https:// production origins"),
        (
            "ALLOWED_ORIGINS",
            "http://localhost:5173",
            "explicit https:// production origins",
        ),
        (
            "ALLOWED_ORIGINS",
            "http://127.0.0.1:8000",
            "explicit https:// production origins",
        ),
        (
            "ALLOWED_ORIGINS",
            "https://localhost:3000",
            "explicit https:// production origins",
        ),
        (
            "ALLOWED_ORIGINS",
            "https://127.0.0.2:8443",
            "explicit https:// production origins",
        ),
        (
            "ALLOWED_ORIGINS",
            "https://[::1]:8443",
            "explicit https:// production origins",
        ),
        (
            "ALLOWED_ORIGINS",
            "http://prod.example.test",
            "explicit https:// production origins",
        ),
        (
            "ALLOWED_ORIGINS",
            "https://replace-before-deploy.invalid",
            "explicit https:// production origins",
        ),
    ],
)
def test_production_configuration_rejects_invalid_setting(
    monkeypatch, name, value, error
):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-test-key")
    monkeypatch.setenv("CF_ACCESS_TEAM_DOMAIN", "example-team")
    monkeypatch.setenv("CF_ACCESS_AUD", "synthetic-audience")
    monkeypatch.setenv("AUDIT_SALT", "synthetic-unique-audit-salt")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://assistant.example.test")
    if value is None:
        monkeypatch.delenv(name, raising=False)
    else:
        monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError, match="unsafe production configuration") as exc:
        server_module.validate_runtime_security()
    assert error in str(exc.value)


def test_production_configuration_accepts_required_controls(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-test-key")
    monkeypatch.setenv("CF_ACCESS_TEAM_DOMAIN", "example-team")
    monkeypatch.setenv("CF_ACCESS_AUD", "synthetic-audience")
    monkeypatch.setenv("AUDIT_SALT", "synthetic-unique-audit-salt")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://assistant.example.test")

    server_module.validate_runtime_security()


def test_development_configuration_remains_local(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("CF_ACCESS_AUD", raising=False)

    server_module.validate_runtime_security()


def test_invalid_app_env_fails_closed(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")

    with pytest.raises(
        RuntimeError, match="APP_ENV must be development, test, or production"
    ):
        server_module.validate_runtime_security()


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
    assert event["query_len"] == len(leaky)

    # Neither the endpoint response nor the persisted file contains the raw query.
    assert leaky not in r2.text
    log_path = audit_module.get_logger().path
    assert leaky not in log_path.read_text(encoding="utf-8")
