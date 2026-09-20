"""Hash-only audit log for /api/chat.

Records *metadata* about every chat request so operators can answer "who
asked what tool when" without ever persisting the request or response
content. This is the minimum log a HIPAA audit would expect:

  - timestamp (ISO-8601 UTC)
  - user identity (from Cloudflare Access claims -- email or sub)
  - tool name (policy / supervision / lecture / chat)
  - query hash (SHA-256 of the last user message, salted)
  - citation count and top doc_id (not content)
  - reply length in characters (not content)
  - latency in milliseconds
  - status ("ok" | "error")

The hash is salted with AUDIT_SALT (env var). Rotate the salt to make old
hashes unlinkable. Without the salt, two different deployments produce
unlinkable hashes for the same query -- a cheap defense against
cross-environment correlation.

Logs are appended to AUDIT_LOG_PATH (default: /data/audit.log on Fly, or
./audit.log locally) as newline-delimited JSON. This is deliberately simple
-- pipe the file to any log shipper (Logpush, Datadog, S3) for long-term
retention. HIPAA expects ~6 years.

IMPORTANT: this module never writes the raw query or reply. If you need
to debug, look at Anthropic's dashboard (ZDR tier) or reproduce locally.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_PATH = os.environ.get("AUDIT_LOG_PATH", "./audit.log")
DEFAULT_AUDIT_SALT = "medsync8-default-salt-change-me"
# A blank AUDIT_SALT is treated as unset so an empty env var can never yield
# an empty salt.
SALT = os.environ.get("AUDIT_SALT", "") or DEFAULT_AUDIT_SALT
_EFFECTIVE_SALT = SALT  # legacy alias
RECENT_BUFFER_SIZE = 200  # in-memory ring buffer for /api/audit/recent


def using_default_salt() -> bool:
    return SALT == DEFAULT_AUDIT_SALT


if using_default_salt():
    log.warning(
        "AUDIT_SALT is not set (or blank). Audit hashes use the default development "
        "salt — set a unique AUDIT_SALT in production to prevent cross-deployment "
        "correlation."
    )


def hash_query(text: str, *, salt: str | None = None) -> str:
    """Return a salted SHA-256 hash of the text, first 16 hex chars.

    16 hex chars = 64 bits; collisions across a single deployment's log
    are effectively impossible while keeping the log compact.
    """
    s = (salt if salt is not None else _EFFECTIVE_SALT).encode("utf-8")
    h = hashlib.sha256(s + b"\x00" + text.encode("utf-8", errors="replace"))
    return h.hexdigest()[:16]


def _bucket_query_len(n: int) -> str:
    """Coarse-bucket query length to reduce side-channel information."""
    if n < 100:
        return "<100"
    if n < 500:
        return "100-499"
    if n < 2000:
        return "500-1999"
    return "2000+"


def identity_from_claims(claims: dict[str, Any] | None) -> str:
    """Pick the best available identity from Access JWT claims.

    Cloudflare Access puts the verified email in `email` and the identity
    provider user id in `sub`. We prefer email for human-readability.
    Returns "anonymous" when Access is disabled (dev/test).
    """
    if not claims:
        return "anonymous"
    return (
        claims.get("email")
        or claims.get("identity_nonce")  # rare
        or claims.get("sub")
        or "unknown"
    )


class AuditLogger:
    """Thread-safe, append-only JSONL audit logger with in-memory tail.

    Safe to use from multiple request workers: writes are guarded by a
    Lock and each event is one flushed line. For higher throughput, swap
    the backend for a queue + background writer -- the interface
    (`emit`, `recent`) stays the same.
    """

    def __init__(self, path: str | Path = DEFAULT_PATH) -> None:
        self.path = Path(path)
        self._lock = Lock()
        self._recent: deque[dict[str, Any]] = deque(maxlen=RECENT_BUFFER_SIZE)
        # Don't pre-create the directory; Fly mounts /data at runtime.
        # We'll handle missing parent on first write.

    def _ensure_parent(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:  # pragma: no cover
            pass

    def emit(self, event: dict[str, Any]) -> None:
        """Append one event. Always includes an ISO-8601 UTC timestamp."""
        event = {"ts": datetime.now(timezone.utc).isoformat(), **event}
        line = json.dumps(event, separators=(",", ":"), ensure_ascii=False)
        with self._lock:
            self._recent.append(event)
            self._ensure_parent()
            try:
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError as e:  # pragma: no cover -- disk failure
                log.error("audit write failed: %s", e)

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._recent)[-limit:]


# Module-level singleton for the app to share.
_logger: AuditLogger | None = None


def get_logger() -> AuditLogger:
    global _logger
    if _logger is None:
        _logger = AuditLogger()
    return _logger


def reset_for_tests(path: str | Path | None = None) -> AuditLogger:
    """Replace the module singleton. Tests only."""
    global _logger
    _logger = AuditLogger(path or DEFAULT_PATH)
    return _logger


class ChatAuditContext:
    """Context manager that times a request and emits one audit event on exit.

    Usage::

        with ChatAuditContext(tool="policy", user_query=q, claims=claims) as ctx:
            # ... do work ...
            ctx.set_result(reply_len=len(reply), citations=cits)

    On exception, the event is still written with status="error" and the
    exception's class name (not its message, which may leak data).
    """

    def __init__(
        self,
        *,
        tool: str,
        user_query: str,
        claims: dict[str, Any] | None,
        logger: AuditLogger | None = None,
    ) -> None:
        self.tool = tool
        self.user_query = user_query
        self.claims = claims
        self.logger = logger or get_logger()
        self._start: float = 0.0
        self._reply_len: int = 0
        self._citations: list[dict[str, Any]] = []

    def set_result(
        self,
        *,
        reply_len: int,
        citations: list[Any],
    ) -> None:
        self._reply_len = reply_len
        # Only keep doc_id + score -- never text.
        self._citations = [
            {"doc_id": getattr(c, "doc_id", None), "score": getattr(c, "score", None)}
            for c in citations
        ]

    def __enter__(self) -> "ChatAuditContext":
        self._start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        latency_ms = int((time.monotonic() - self._start) * 1000)
        event: dict[str, Any] = {
            "event": "chat",
            "user": identity_from_claims(self.claims),
            "tool": self.tool,
            "query_hash": hash_query(self.user_query),
            "query_len_bucket": _bucket_query_len(len(self.user_query)),
            "reply_len": self._reply_len,
            "citations": len(self._citations),
            "top_doc": self._citations[0]["doc_id"] if self._citations else None,
            "latency_ms": latency_ms,
            "status": "ok" if exc_type is None else "error",
        }
        if exc_type is not None:
            event["error_type"] = exc_type.__name__
        self.logger.emit(event)
