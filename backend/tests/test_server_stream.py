"""Contract tests for POST /api/chat/stream (Server-Sent Events)."""
from __future__ import annotations

import json
from pathlib import Path

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient

from backend import audit as audit_module
from backend import server as server_module
from backend.retriever import Retriever
from backend.tests.conftest import STUB_THINKING_TEXT


@pytest.fixture
def client(monkeypatch, tmp_path: Path, tiny_corpus: Path, stub_embedder, stub_anthropic):
    retriever = Retriever(str(tiny_corpus), stub_embedder)
    retriever.load_or_build()

    monkeypatch.setattr(server_module.app.router, "lifespan_context", None)
    server_module.app.state.retriever = retriever
    server_module.app.state.anthropic = stub_anthropic

    audit_module.reset_for_tests(tmp_path / "audit.log")
    return TestClient(server_module.app)


def parse_sse(body: str) -> list[tuple[str, dict]]:
    """Split an SSE body into ``(event, data)`` tuples in wire order."""
    frames: list[tuple[str, dict]] = []
    for raw in body.split("\n\n"):
        if not raw.strip():
            continue
        event = "message"
        data_lines: list[str] = []
        for line in raw.split("\n"):
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:"):].lstrip())
        frames.append((event, json.loads("\n".join(data_lines))))
    return frames


def _post_stream(client: TestClient, **overrides):
    payload = {
        "tool": "policy",
        "messages": [{"role": "user", "content": "Draft a PDMP policy for Texas"}],
        "use_rag": True,
    }
    payload.update(overrides)
    return client.post("/api/chat/stream", json=payload)


def test_stream_emits_citations_then_text_then_done(client, stub_anthropic):
    r = _post_stream(client)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")

    frames = parse_sse(r.text)
    events = [e for e, _ in frames]

    # Fixed frame order: exactly one citations frame first, text deltas, one done last.
    assert events[0] == "citations"
    assert events[-1] == "done"
    assert events.count("citations") == 1
    assert events.count("done") == 1
    assert set(events[1:-1]) == {"text"}
    assert len(events[1:-1]) >= 2, "reply must arrive as multiple deltas"

    citations = frames[0][1]["citations"]
    assert len(citations) >= 1
    assert {"index", "doc_id", "chunk_id", "score"} <= set(citations[0].keys())

    reply = "".join(d["delta"] for e, d in frames if e == "text")
    assert reply == "[stub-reply to: Draft a PDMP policy for Texas]"
    assert frames[-1][1]["reply_len"] == len(reply)
    assert frames[-1][1]["model"] == server_module.ANTHROPIC_MODEL

    # Retrieval ran before the model call and was passed as system context.
    assert "RETRIEVED CONTEXT" in stub_anthropic.last_call["system"]
    assert stub_anthropic.last_stream.closed is True


def test_stream_drops_thinking_blocks(client):
    r = _post_stream(client)
    assert r.status_code == 200
    assert STUB_THINKING_TEXT not in r.text
    assert "thinking" not in {e for e, _ in parse_sse(r.text)}


def test_stream_without_rag_sends_empty_citations(client, stub_anthropic):
    r = _post_stream(client, tool="chat", use_rag=False)
    assert r.status_code == 200
    frames = parse_sse(r.text)
    assert frames[0] == ("citations", {"citations": []})
    assert "RETRIEVED CONTEXT" not in stub_anthropic.last_call["system"]


def test_stream_uses_same_model_config_as_sync_chat(client, stub_anthropic):
    _post_stream(client, tool="chat", use_rag=False)
    stream_call = dict(stub_anthropic.last_call)
    client.post("/api/chat", json={
        "tool": "chat",
        "messages": [{"role": "user", "content": "Draft a PDMP policy for Texas"}],
        "use_rag": False,
    })
    assert stub_anthropic.last_call == stream_call


def test_stream_writes_audit_event_with_reply_length(client):
    leaky = "UNIQUE-PATIENT-STRING-stream-abc789"
    r = _post_stream(client, messages=[{"role": "user", "content": leaky}])
    assert r.status_code == 200
    frames = parse_sse(r.text)
    reply = "".join(d["delta"] for e, d in frames if e == "text")

    body = client.get("/api/audit/recent").json()
    assert body["count"] == 1
    event = body["events"][0]
    assert event["event"] == "chat"
    assert event["tool"] == "policy"
    assert event["status"] == "ok"
    assert event["query_len"] == len(leaky)
    assert event["reply_len"] == len(reply)
    assert event["citations"] == len(frames[0][1]["citations"])

    # Hash-only invariant: neither the query nor the reply is persisted.
    log_text = audit_module.get_logger().path.read_text(encoding="utf-8")
    assert leaky not in log_text
    assert "stub-reply" not in log_text
    assert STUB_THINKING_TEXT not in log_text


def test_stream_validation_errors_use_chat_shape(client):
    r = client.post("/api/chat/stream", json={"tool": "chat", "messages": []})
    assert r.status_code == 422
    assert r.json()["detail"] == "invalid chat request shape"


def test_stream_upstream_connect_failure_returns_502_and_audits_error(client, stub_anthropic):
    class _FailingStream:
        def __enter__(self):
            raise anthropic.APIConnectionError(
                request=httpx.Request("POST", "https://api.anthropic.invalid/v1/messages")
            )

        def __exit__(self, *exc):
            return None

    stub_anthropic.messages.stream = lambda **kwargs: _FailingStream()

    r = _post_stream(client, use_rag=False)
    assert r.status_code == 502
    assert r.json()["detail"] == "anthropic error: APIConnectionError"
    # The SDK's message (which can carry request details) never reaches the client.
    assert "Connection error" not in r.text

    event = client.get("/api/audit/recent").json()["events"][0]
    assert event["status"] == "error"
    assert event["error_type"] == "HTTPException"


def test_stream_mid_stream_failure_emits_error_frame_and_audits_error(client, stub_anthropic):
    real_stream = stub_anthropic.messages.stream

    class _ExplodingStream:
        def __init__(self, inner):
            self._inner = inner

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return self._inner.__exit__(*exc)

        def __iter__(self):
            for i, event in enumerate(self._inner):
                if i == 6:  # after the first text delta has been sent
                    raise anthropic.APIConnectionError(
                        request=httpx.Request("POST", "https://api.anthropic.invalid/v1/messages")
                    )
                yield event

    stub_anthropic.messages.stream = lambda **kwargs: _ExplodingStream(real_stream(**kwargs))

    r = _post_stream(client, use_rag=False)
    assert r.status_code == 200
    frames = parse_sse(r.text)
    events = [e for e, _ in frames]
    assert events[0] == "citations"
    assert "text" in events
    assert events[-1] == "error"
    assert "done" not in events
    assert frames[-1][1] == {"detail": "anthropic error: APIConnectionError"}
    assert "Connection error" not in r.text

    event = client.get("/api/audit/recent").json()["events"][0]
    assert event["status"] == "error"
    assert event["error_type"] == "APIConnectionError"


def test_stream_without_text_emits_error_frame(client, stub_anthropic):
    class _EmptyStream:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def __iter__(self):
            return iter(())

    stub_anthropic.messages.stream = lambda **kwargs: _EmptyStream()

    r = _post_stream(client, use_rag=False)
    assert r.status_code == 200
    frames = parse_sse(r.text)
    assert [e for e, _ in frames] == ["citations", "error"]
    assert frames[-1][1]["detail"] == "anthropic response missing text content"
