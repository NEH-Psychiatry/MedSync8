"""Shared test fixtures. No network calls, no real API keys required."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import pytest


class _Embedding:
    def __init__(self, vector: list[float]) -> None:
        self.embedding = vector


class _EmbeddingsResponse:
    def __init__(self, data: list[_Embedding]) -> None:
        self.data = data


class StubEmbedder:
    """Deterministic, hash-seeded embedder used by the retriever in tests.

    Implements the ``Embedder`` protocol from ``backend.embedders`` — no
    third-party network, no model downloads.
    """

    name = "stub:test"

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
            rng = np.random.default_rng(seed)
            out.append(rng.standard_normal(16).tolist())
        return out


class _AnthropicContentBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _AnthropicMessage:
    def __init__(self, text: str) -> None:
        self.content = [_AnthropicContentBlock(text)]


class _StreamDelta:
    """Mimics ``TextDelta`` / ``ThinkingDelta`` on a ``content_block_delta`` event."""

    def __init__(self, type: str, **fields: str) -> None:
        self.type = type
        for name, value in fields.items():
            setattr(self, name, value)


class _StreamEvent:
    """Mimics a raw ``MessageStreamEvent``; only ``content_block_delta`` carries ``delta``."""

    def __init__(self, type: str, delta: _StreamDelta | None = None) -> None:
        self.type = type
        if delta is not None:
            self.delta = delta


class StubMessageStream:
    """Mimics ``anthropic.lib.streaming.MessageStream``: a context manager that
    iterates raw stream events. Records whether the server closed it."""

    def __init__(self, events: list[_StreamEvent]) -> None:
        self._events = events
        self.closed = False

    def __enter__(self) -> "StubMessageStream":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.closed = True

    def __iter__(self):
        yield from self._events


# Reply text is split into deltas so tests can assert on frame ordering and
# reassembly. Joined together they equal the non-streaming stub reply.
STUB_STREAM_PIECES = ("[stub-reply", " to: ", "{last_user}]")
STUB_THINKING_TEXT = "STUB-THINKING-MUST-NOT-LEAK"


class StubAnthropic:
    """Echoes the user's last message back with a marker so tests can assert."""

    class _Messages:
        def __init__(self, parent: "StubAnthropic") -> None:
            self._parent = parent

        @staticmethod
        def _last_user(messages: list[dict[str, Any]]) -> str:
            return next(
                (m["content"] for m in reversed(messages) if m["role"] == "user"),
                "",
            )

        def create(self, *, model: str, max_tokens: int, system: str,
                   messages: list[dict[str, Any]]) -> _AnthropicMessage:
            self._parent.last_call = {"model": model, "system": system, "messages": messages}
            return _AnthropicMessage(f"[stub-reply to: {self._last_user(messages)}]")

        def stream(self, *, model: str, max_tokens: int, system: str,
                   messages: list[dict[str, Any]]) -> StubMessageStream:
            """Yield a thinking block (which the server must drop) followed by
            the reply split across several ``text_delta`` events."""
            self._parent.last_call = {"model": model, "system": system, "messages": messages}
            last_user = self._last_user(messages)
            events = [
                _StreamEvent("message_start"),
                _StreamEvent("content_block_start"),
                _StreamEvent(
                    "content_block_delta",
                    _StreamDelta("thinking_delta", thinking=STUB_THINKING_TEXT),
                ),
                _StreamEvent("content_block_stop"),
                _StreamEvent("content_block_start"),
                *[
                    _StreamEvent(
                        "content_block_delta",
                        _StreamDelta("text_delta", text=piece.format(last_user=last_user)),
                    )
                    for piece in STUB_STREAM_PIECES
                ],
                _StreamEvent("content_block_stop"),
                _StreamEvent("message_stop"),
            ]
            self._parent.last_stream = StubMessageStream(events)
            return self._parent.last_stream

    def __init__(self) -> None:
        self.last_call: dict[str, Any] = {}
        self.last_stream: StubMessageStream | None = None
        self.messages = self._Messages(self)


@pytest.fixture
def stub_embedder() -> StubEmbedder:
    return StubEmbedder()


@pytest.fixture
def stub_anthropic() -> StubAnthropic:
    return StubAnthropic()


@pytest.fixture
def tiny_corpus(tmp_path: Path) -> Path:
    (tmp_path / "dea_ryan_haight.md").write_text(
        "DEA Ryan Haight Act requires an in-person medical evaluation "
        "before prescribing controlled substances via telemedicine. "
        "Exceptions apply under the practice of telemedicine definitions. " * 20
    )
    (tmp_path / "tx_pdmp.md").write_text(
        "Texas Prescription Monitoring Program requires prescribers to "
        "check the PDMP before prescribing opioids, benzodiazepines, "
        "barbiturates, or carisoprodol. " * 20
    )
    return tmp_path
