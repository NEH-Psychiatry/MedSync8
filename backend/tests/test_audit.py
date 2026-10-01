"""Tests for backend.audit -- hash-only audit logging.

Critical invariant under test: the raw user query and raw reply MUST NOT
appear anywhere in the persisted audit record. The log captures
metadata only (hash, length, counts, user identity, timestamps).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend import audit


def test_hash_query_deterministic_and_salted(monkeypatch):
    monkeypatch.setenv("AUDIT_SALT", "salt-a")
    # Reload module salt by re-reading env -- the function takes salt
    # param; use it directly to avoid import-time caching.
    h1 = audit.hash_query("prescribe buprenorphine", salt="salt-a")
    h2 = audit.hash_query("prescribe buprenorphine", salt="salt-a")
    h3 = audit.hash_query("prescribe buprenorphine", salt="salt-b")
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 16
    assert all(c in "0123456789abcdef" for c in h1)


def test_identity_from_claims_prefers_email():
    assert audit.identity_from_claims({"email": "a@b.com", "sub": "uid"}) == "a@b.com"
    assert audit.identity_from_claims({"sub": "uid"}) == "uid"
    assert audit.identity_from_claims(None) == "anonymous"
    assert audit.identity_from_claims({}) == "anonymous"


def test_audit_context_writes_metadata_only(tmp_path: Path):
    log_path = tmp_path / "audit.log"
    logger = audit.AuditLogger(path=log_path)

    secret_query = "DO-NOT-LOG-patient-SSN-123-45-6789"
    secret_reply = "DO-NOT-LOG-diagnosis-F33.1"

    class _Cite:
        def __init__(self, doc_id, score):
            self.doc_id = doc_id
            self.score = score

    with audit.ChatAuditContext(
        tool="policy",
        user_query=secret_query,
        claims={"email": "clinician@example.com"},
        logger=logger,
    ) as ctx:
        ctx.set_result(
            reply_len=len(secret_reply),
            citations=[_Cite("dea.md", 0.91), _Cite("pdmp.md", 0.72)],
        )

    text = log_path.read_text(encoding="utf-8")
    # Invariant: no raw content in the log.
    assert secret_query not in text
    assert secret_reply not in text
    assert "SSN" not in text
    assert "F33.1" not in text

    # But metadata IS present.
    event = json.loads(text.strip())
    assert event["event"] == "chat"
    assert event["tool"] == "policy"
    assert event["user"] == "clinician@example.com"
    assert event["citations"] == 2
    assert event["top_doc"] == "dea.md"
    assert event["reply_len"] == len(secret_reply)
    assert event["query_len"] == len(secret_query)
    assert event["status"] == "ok"
    assert len(event["query_hash"]) == 16
    assert "ts" in event
    assert "latency_ms" in event


def test_audit_context_emits_only_once_when_exited_twice(tmp_path: Path):
    logger = audit.AuditLogger(path=tmp_path / "audit.log")

    with audit.ChatAuditContext(
        tool="chat",
        user_query="synthetic test query",
        claims=None,
        logger=logger,
    ) as ctx:
        ctx.__exit__(None, None, None)

    assert len(logger.recent()) == 1


def test_audit_context_records_errors_without_message(tmp_path: Path):
    log_path = tmp_path / "audit.log"
    logger = audit.AuditLogger(path=log_path)

    leaky_message = "LEAK-patient-name-Jane-Doe"

    with pytest.raises(RuntimeError):
        with audit.ChatAuditContext(
            tool="chat",
            user_query="hello",
            claims={"email": "c@e.com"},
            logger=logger,
        ):
            raise RuntimeError(leaky_message)

    text = log_path.read_text(encoding="utf-8")
    event = json.loads(text.strip())
    assert event["status"] == "error"
    assert event["error_type"] == "RuntimeError"
    # Exception message must not be logged.
    assert leaky_message not in text


def test_recent_buffer_returns_last_n(tmp_path: Path):
    logger = audit.AuditLogger(path=tmp_path / "audit.log")
    for i in range(5):
        logger.emit({"event": "chat", "i": i})
    events = logger.recent(limit=3)
    assert len(events) == 3
    assert [e["i"] for e in events] == [2, 3, 4]
