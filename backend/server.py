"""FastAPI backend for the MedSync8 telepsychiatry assistant.

Responsibilities:
  * Hide the Anthropic API key server-side.
  * Retrieve relevant context from a local corpus (RAG).
  * Forward the augmented prompt to Claude and return citations.
  * Optionally stream the reply as Server-Sent Events (``/api/chat/stream``).

Run:
  uvicorn backend.server:app --reload --port 8000
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from contextlib import ExitStack, asynccontextmanager
from typing import Literal

import anthropic
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, model_validator

from .audit import (
    ChatAuditContext,
    get_logger as get_audit_logger,
    using_default_salt,
)
from .auth import require_access
from .embedders import build_embedder_from_env
from .prompts import SYSTEM_PROMPTS
from .retriever import Retriever, format_context

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("medsync8")

ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-6")
MAX_TOKENS = int(os.environ.get("ANTHROPIC_MAX_TOKENS", "4096"))
# Per-request bound on the Anthropic client (seconds). For streaming this is
# the httpx read timeout, i.e. the longest wait for the next chunk.
ANTHROPIC_TIMEOUT_SECONDS = float(os.environ.get("ANTHROPIC_TIMEOUT_SECONDS", "120"))
CORPUS_DIR = os.environ.get("CORPUS_DIR", "./corpus")
TOP_K = int(os.environ.get("RAG_TOP_K", "4"))
ALLOWED_ORIGINS = os.environ.get(
    "ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000"
).split(",")
MAX_MESSAGES = int(os.environ.get("CHAT_MAX_MESSAGES", "50"))
MAX_MESSAGE_CHARS = int(os.environ.get("CHAT_MAX_MESSAGE_CHARS", "20000"))
CHAT_PATHS = ("/api/chat", "/api/chat/stream")


# ---------- lifecycle -------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.warning("ANTHROPIC_API_KEY not set — /api/chat and /api/chat/stream will fail")

    embedder = build_embedder_from_env()
    if embedder is None:
        log.warning("no embedder available — retrieval disabled")
        app.state.retriever = None
    else:
        retriever = Retriever(CORPUS_DIR, embedder)
        try:
            retriever.load_or_build()
        except Exception:
            # A transient embedding/indexing failure must not take the whole
            # API down — degrade to no-RAG operation, same as no embedder.
            log.exception("corpus indexing failed — continuing with retrieval disabled")
            retriever = None
        app.state.retriever = retriever

    app.state.anthropic = anthropic.Anthropic(timeout=ANTHROPIC_TIMEOUT_SECONDS)
    if using_default_salt():
        log.warning(
            "AUDIT_SALT is using the default development fallback. "
            "Set AUDIT_SALT to a strong unique value for non-local deployments."
        )
    yield


app = FastAPI(title="MedSync8 Telepsychiatry Backend", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in ALLOWED_ORIGINS if o.strip()],
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type"],
)


@app.exception_handler(RequestValidationError)
async def chat_request_validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    safe_errors = []
    for err in exc.errors():
        clean = dict(err)
        ctx = clean.get("ctx")
        if isinstance(ctx, dict) and "error" in ctx:
            clean["ctx"] = {**ctx, "error": str(ctx["error"])}
        safe_errors.append(clean)

    if request.url.path in CHAT_PATHS:
        return JSONResponse(
            status_code=422,
            content={"detail": "invalid chat request shape", "errors": safe_errors},
        )
    return JSONResponse(status_code=422, content={"detail": safe_errors})


# ---------- schemas ---------------------------------------------------------


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=MAX_MESSAGE_CHARS)


class ChatRequest(BaseModel):
    tool: Literal["policy", "supervision", "lecture", "chat"]
    messages: list[Message] = Field(..., min_length=1, max_length=MAX_MESSAGES)
    use_rag: bool = True

    @model_validator(mode="after")
    def validate_messages(self) -> "ChatRequest":
        has_user_message = False
        for message in self.messages:
            if message.role == "user":
                if not message.content.strip():
                    raise ValueError("user messages must not be blank or whitespace-only")
                has_user_message = True

        if not has_user_message:
            raise ValueError("chat requires at least one user message")

        return self


class Citation(BaseModel):
    index: int
    doc_id: str
    chunk_id: int
    score: float


class ChatResponse(BaseModel):
    reply: str
    citations: list[Citation]
    model: str


# ---------- routes ----------------------------------------------------------


@app.get("/api/health")
def health() -> dict:
    retriever = app.state.retriever
    return {
        "ok": True,
        "model": ANTHROPIC_MODEL,
        "rag_enabled": bool(retriever and retriever.ready()),
        "corpus_chunks": len(retriever.chunks) if retriever and retriever.ready() else 0,
        "embedder": retriever.embedder.name if retriever and retriever.ready() else None,
        "access_enforced": bool(os.environ.get("CF_ACCESS_AUD")),
        "audit_salt_default": using_default_salt(),
    }


def _last_user_message(req: ChatRequest) -> str:
    """Return the last non-blank user message -- used for retrieval and the audit hash.

    ChatRequest's validator guarantees at least one non-blank user message.
    """
    return next(
        (m.content.strip() for m in reversed(req.messages) if m.role == "user" and m.content.strip()),
        "",
    )


def _augment_with_context(req: ChatRequest, last_user: str) -> tuple[str, list[Citation]]:
    """Run retrieval (when enabled) and return the system prompt plus citations."""
    system_prompt = SYSTEM_PROMPTS[req.tool]
    retriever: Retriever | None = app.state.retriever
    citations: list[Citation] = []

    if req.use_rag and retriever and retriever.ready() and last_user:
        hits = retriever.search(last_user, k=TOP_K)
        if hits:
            system_prompt = (
                f"{system_prompt}\n\n"
                "=== RETRIEVED CONTEXT ===\n"
                f"{format_context(hits)}\n"
                "=== END CONTEXT ===\n"
                "Use the context above when relevant. If the user's question "
                "cannot be answered from the context, say so and answer from "
                "general expertise, but do NOT fabricate citations."
            )
            citations = [
                Citation(index=i + 1, doc_id=h.doc_id, chunk_id=h.chunk_id, score=h.score)
                for i, h in enumerate(hits)
            ]

    return system_prompt, citations


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest, claims: dict = Depends(require_access)) -> ChatResponse:
    last_user = _last_user_message(req)

    with ChatAuditContext(tool=req.tool, user_query=last_user, claims=claims) as audit:
        system_prompt, citations = _augment_with_context(req, last_user)

        try:
            resp = app.state.anthropic.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=MAX_TOKENS,
                system=system_prompt,
                messages=[m.model_dump() for m in req.messages],
            )
        except anthropic.APIError as e:
            raise HTTPException(502, f"anthropic error: {e}") from e

        text_blocks = [
            b.text for b in getattr(resp, "content", [])
            if getattr(b, "type", None) == "text" and getattr(b, "text", "")
        ]
        if not text_blocks:
            response_types = [getattr(b, "type", "unknown") for b in getattr(resp, "content", [])]
            log.error("anthropic response missing text block; content types=%s", response_types)
            raise HTTPException(502, "anthropic response missing text content")
        text = "\n".join(text_blocks)
        audit.set_result(reply_len=len(text), citations=citations)

    return ChatResponse(reply=text, citations=citations, model=ANTHROPIC_MODEL)


# ---------- streaming ----------------------------------------------------


def _sse(event: str, data: dict) -> str:
    """Encode one Server-Sent Events frame (JSON payload on a single data line)."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class _StreamFailure(Exception):
    """Abort an in-progress stream with a detail safe to send to the client."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest, claims: dict = Depends(require_access)) -> StreamingResponse:
    """Stream a chat reply as Server-Sent Events (``text/event-stream``).

    Frame order is fixed: one ``citations`` frame (retrieval runs before the
    model call), zero or more ``text`` frames carrying reply deltas, then one
    ``done`` frame. Only text deltas are forwarded -- thinking blocks are
    dropped. Failures before the first frame surface as ordinary HTTP errors
    (401, 422, 502); failures after streaming starts are sent as a single
    ``error`` frame. The exchange is audited exactly like ``/api/chat``
    (hash-only; reply length recorded when the stream completes).
    """
    last_user = _last_user_message(req)

    # The audit context spans retrieval, the upstream request, and the whole
    # stream. ExitStack lets the generator below own the teardown while the
    # pre-stream errors still map onto HTTP status codes here.
    stack = ExitStack()
    audit = stack.enter_context(
        ChatAuditContext(tool=req.tool, user_query=last_user, claims=claims)
    )
    try:
        system_prompt, citations = _augment_with_context(req, last_user)
        stream = stack.enter_context(
            app.state.anthropic.messages.stream(
                model=ANTHROPIC_MODEL,
                max_tokens=MAX_TOKENS,
                system=system_prompt,
                messages=[m.model_dump() for m in req.messages],
            )
        )
    except anthropic.APIError as e:
        # Class name only: the SDK message can carry request details, so it
        # stays out of the response body and the audit log alike.
        log.error("anthropic stream request failed: %s", type(e).__name__)
        with stack:  # closes the audit context with status="error"
            raise HTTPException(502, f"anthropic error: {type(e).__name__}") from e
    except BaseException:
        with stack:
            raise

    def event_stream() -> Iterator[str]:
        try:
            with stack:
                yield _sse("citations", {"citations": [c.model_dump() for c in citations]})

                pieces: list[str] = []
                for event in stream:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        pieces.append(event.delta.text)
                        yield _sse("text", {"delta": event.delta.text})

                text = "".join(pieces)
                if not text:
                    log.error("anthropic stream produced no text content")
                    raise _StreamFailure("anthropic response missing text content")
                audit.set_result(reply_len=len(text), citations=citations)
                yield _sse("done", {"model": ANTHROPIC_MODEL, "reply_len": len(text)})
        except anthropic.APIError as e:
            log.error("anthropic stream failed mid-response: %s", type(e).__name__)
            yield _sse("error", {"detail": f"anthropic error: {type(e).__name__}"})
        except _StreamFailure as e:
            yield _sse("error", {"detail": e.detail})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/audit/recent")
def audit_recent(
    limit: int = 50,
    claims: dict = Depends(require_access),
) -> dict:
    """Return the last N audit events (metadata only -- no query text).

    Gated by the same Cloudflare Access dependency as the chat routes. Restrict
    further with an Access policy (e.g. admin group) on the CF side if
    needed -- this endpoint does not do role checks itself.
    """
    limit = max(1, min(limit, 200))
    events = get_audit_logger().recent(limit=limit)
    return {"count": len(events), "events": events}
