"""FastAPI backend for the MedSync8 telepsychiatry assistant.

Responsibilities:
  * Hide the Anthropic API key server-side.
  * Retrieve relevant context from a local corpus (RAG).
  * Forward the augmented prompt to Claude and return citations.

Run:
  uvicorn backend.server:app --reload --port 8000
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Literal

import anthropic
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
CORPUS_DIR = os.environ.get("CORPUS_DIR", "./corpus")
TOP_K = int(os.environ.get("RAG_TOP_K", "4"))
ALLOWED_ORIGINS = os.environ.get(
    "ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000"
).split(",")
MAX_MESSAGES = int(os.environ.get("CHAT_MAX_MESSAGES", "50"))
MAX_MESSAGE_CHARS = int(os.environ.get("CHAT_MAX_MESSAGE_CHARS", "20000"))


def validate_runtime_security() -> None:
    """Reject incomplete production configuration before serving traffic."""

    app_env = os.environ.get("APP_ENV", "development").strip().lower()
    if app_env not in {"development", "test", "production"}:
        raise RuntimeError("APP_ENV must be development, test, or production")
    if app_env != "production":
        return

    errors: list[str] = []
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        errors.append("ANTHROPIC_API_KEY is required")
    if not os.environ.get("CF_ACCESS_TEAM_DOMAIN", "").strip():
        errors.append("CF_ACCESS_TEAM_DOMAIN is required")
    if not os.environ.get("CF_ACCESS_AUD", "").strip():
        errors.append("CF_ACCESS_AUD is required")

    audit_salt = os.environ.get("AUDIT_SALT", "").strip()
    if not audit_salt or audit_salt == "medsync8-default-salt-change-me":
        errors.append("a unique AUDIT_SALT is required")

    origins = [
        value.strip()
        for value in os.environ.get("ALLOWED_ORIGINS", "").split(",")
        if value.strip()
    ]
    if not origins:
        errors.append("ALLOWED_ORIGINS must contain the production frontend origin")
    elif any(
        origin == "*"
        or origin.startswith("http://localhost")
        or origin.startswith("http://127.0.0.1")
        or origin.endswith(".invalid")
        or "replace-before-deploy" in origin
        for origin in origins
    ):
        errors.append("ALLOWED_ORIGINS must not contain wildcards or local origins")

    if errors:
        raise RuntimeError("unsafe production configuration: " + "; ".join(errors))


# ---------- lifecycle -------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_runtime_security()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.warning("ANTHROPIC_API_KEY not set — /api/chat will fail")

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

    app.state.anthropic = anthropic.Anthropic()
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

    if request.url.path == "/api/chat":
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


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest, claims: dict = Depends(require_access)) -> ChatResponse:
    system_prompt = SYSTEM_PROMPTS[req.tool]
    retriever: Retriever | None = app.state.retriever
    citations: list[Citation] = []

    # Grab the last user message once -- used for retrieval and audit hash.
    # ChatRequest's validator guarantees at least one non-blank user message.
    last_user = next(
        (m.content.strip() for m in reversed(req.messages) if m.role == "user" and m.content.strip()),
        "",
    )

    with ChatAuditContext(tool=req.tool, user_query=last_user, claims=claims) as audit:
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


@app.get("/api/audit/recent")
def audit_recent(
    limit: int = 50,
    claims: dict = Depends(require_access),
) -> dict:
    """Return the last N audit events (metadata only -- no query text).

    Gated by the same Cloudflare Access dependency as /api/chat. Restrict
    further with an Access policy (e.g. admin group) on the CF side if
    needed -- this endpoint does not do role checks itself.
    """
    limit = max(1, min(limit, 200))
    events = get_audit_logger().recent(limit=limit)
    return {"count": len(events), "events": events}
